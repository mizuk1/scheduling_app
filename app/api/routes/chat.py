"""Chat endpoints and orchestration for schedule commands.

This module receives either explicit actions or natural-language messages,
resolves them to structured actions, executes updates, and stores command
audit status in the database.
"""

import json
import re
from collections.abc import Sequence
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.api.deps import get_db
from app.models.scheduling import (
    Assignment,
    ChatCommand,
    DAYS_OF_WEEK,
    Employee,
    SHIFT_TYPES,
    Role,
    ScheduleRule,
    Shift,
)
from app.schemas.scheduling import (
    ChatCommandRequest,
    ChatCommandResponse,
    ChatAction,
    RoleRequirement,
    ScheduleRuleRead,
)
from app.services.schedule_queries import build_autofill_response, build_swap_response
from app.services.scheduler import fill_day, swap_assignment
from app.services.llm_parser import LLMParseError, parse_action_from_message

router = APIRouter()
MAX_ASSIGNMENTS_IN_CONTEXT = 250
SUPPORTED_CHAT_ACTION_TYPES = {"AUTOFILL_DAY", "SWAP_ASSIGNMENT", "SET_RULE"}
DAY_SCOPE_TO_DAYS = {
    "WEEKDAY": ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"),
    "WEEKDAYS": ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"),
    "WEEKEND": ("SATURDAY", "SUNDAY"),
    "WEEKENDS": ("SATURDAY", "SUNDAY"),
}
DAY_TOKEN_TO_WEEKDAY = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
DATE_HINT_RE = re.compile(
    r"\b(?:\d{1,4}[-/]\d{1,2}[-/]\d{1,4}|jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b",
    re.IGNORECASE,
)


def _build_role_context(session: Session) -> list[dict[str, int | str]]:
    return [
        {"id": role.id, "name": role.name}
        for role in session.exec(select(Role)).all()
        if role.id is not None
    ]


def _build_employee_context(session: Session) -> list[dict[str, int | str]]:
    return [
        {"id": employee.id, "name": employee.name}
        for employee in session.exec(select(Employee).where(Employee.is_active == True)).all()
        if employee.id is not None
    ]


def _build_assignment_context(session: Session) -> list[dict[str, int | str | None]]:
    rows = session.exec(
        select(Assignment, Shift, Role, Employee)
        .join(Shift, Assignment.shift_id == Shift.id)
        .join(Role, Assignment.role_id == Role.id)
        .outerjoin(Employee, Assignment.employee_id == Employee.id)
        .order_by(Shift.date, Shift.shift_type, Role.name)
    ).all()

    assignments = [
        {
            "assignment_id": assignment.id,
            "date": shift.date.isoformat(),
            "shift_type": shift.shift_type,
            "role_id": role.id,
            "role_name": role.name,
            "employee_id": employee.id if employee else None,
            "employee_name": employee.name if employee else None,
        }
        for assignment, shift, role, employee in rows
        if assignment.id is not None and role.id is not None
    ]

    if len(assignments) > MAX_ASSIGNMENTS_IN_CONTEXT:
        assignments = assignments[-MAX_ASSIGNMENTS_IN_CONTEXT:]

    return assignments


def _build_parser_message(
    message: str,
    role_context: list[dict[str, int | str]],
    session: Session,
) -> str:
    context_payload = {
        "today": date.today().isoformat(),
        "roles": role_context,
        "employees": _build_employee_context(session),
        "assignments": _build_assignment_context(session),
    }
    return f"{message}\n\nCONTEXT_JSON:\n{json.dumps(context_payload)}"


def _normalize_message(message: str | None) -> str:
    return (message or "").strip().lower()


def _is_add_like_message(message: str | None) -> bool:
    normalized = _normalize_message(message)
    return bool(
        re.search(r"\b(add|assign|swap)\b", normalized)
        or re.search(r"\breplace\b.*\bwith\b", normalized)
    )


def _message_requires_replacement_employee(
    message: str | None,
    mentioned_employees: Sequence[Employee],
) -> bool:
    normalized = _normalize_message(message)
    if not normalized:
        return False

    if re.search(r"\b(add|assign)\b", normalized):
        return True

    if re.search(r"\breplace\b.*\bwith\b", normalized):
        return True

    if re.search(r"\bswap\b", normalized):
        if _message_has_with_clause(message):
            return True
        return len(mentioned_employees) >= 2

    return False


def _message_has_with_clause(message: str | None) -> bool:
    return bool(re.search(r"\bwith\b", _normalize_message(message)))


def _is_remove_like_message(message: str | None) -> bool:
    return bool(re.search(r"\b(remove|unassign|delete)\b", _normalize_message(message)))


def _message_mentions_shift(message: str | None) -> str | None:
    normalized = _normalize_message(message)
    if "lunch" in normalized:
        return "LUNCH"
    if "dinner" in normalized:
        return "DINNER"
    return None


def _message_has_date_hint(message: str | None) -> bool:
    return bool(DATE_HINT_RE.search(_normalize_message(message)))


def _message_mentions_target_date(message: str | None, target_date: date) -> bool:
    normalized = _normalize_message(message)
    month_name = target_date.strftime("%B").lower()
    month_short = target_date.strftime("%b").lower()
    year = target_date.year
    month = target_date.month
    day = target_date.day
    candidates = {
        target_date.isoformat(),
        f"{year}/{month:02d}/{day:02d}",
        f"{day}-{month}-{year}",
        f"{day}/{month}/{year}",
        f"{day:02d}-{month:02d}-{year}",
        f"{day:02d}/{month:02d}/{year}",
        f"{month}-{day}-{year}",
        f"{month}/{day}/{year}",
        f"{month:02d}-{day:02d}-{year}",
        f"{month:02d}/{day:02d}/{year}",
        f"{month_name} {day} {year}",
        f"{month_name} {day}, {year}",
        f"{month_short} {day} {year}",
        f"{month_short} {day}, {year}",
    }
    return any(candidate in normalized for candidate in candidates)


def _extract_weekday_hints(message: str | None) -> set[int]:
    normalized = _normalize_message(message)
    return {
        weekday
        for token, weekday in DAY_TOKEN_TO_WEEKDAY.items()
        if re.search(rf"\b{token}\b", normalized)
    }


def _validate_autofill_day_consistency(
    message: str | None,
    action: ChatAction,
) -> None:
    if action.type != "AUTOFILL_DAY" or not message or action.date is None:
        return

    weekday_hints = _extract_weekday_hints(message)
    if weekday_hints and action.date.weekday() not in weekday_hints:
        raise ValueError(
            "resolved date does not match day mentioned in message; "
            "please provide an explicit date (YYYY-MM-DD)"
        )


def _find_employee_mentions(
    message: str | None,
    employees: Sequence[Employee],
) -> list[Employee]:
    normalized = _normalize_message(message)
    mentions: list[tuple[int, Employee]] = []

    for employee in employees:
        if employee.id is None:
            continue
        index = normalized.find(employee.name.lower())
        if index >= 0:
            mentions.append((index, employee))

    mentions.sort(key=lambda item: item[0])
    deduped: list[Employee] = []
    seen_ids: set[int] = set()
    for _, employee in mentions:
        if employee.id in seen_ids:
            continue
        seen_ids.add(employee.id)
        deduped.append(employee)
    return deduped


_NOT_A_COMMAND_MESSAGE = (
    "This chat only accepts scheduling commands. "
    "Try something like: 'Fill Monday lunch shift', "
    "'Swap Ana for dinner on Tuesday', or 'Set 2 cooks for Friday lunch'."
)


def _validate_supported_action_type(action_type: str) -> None:
    if action_type == "UNKNOWN":
        raise ValueError(_NOT_A_COMMAND_MESSAGE)
    if action_type not in SUPPORTED_CHAT_ACTION_TYPES:
        raise ValueError("unsupported action type")


def _validate_swap_action_consistency(
    message: str | None,
    action: ChatAction,
    session: Session,
) -> None:
    if action.type != "SWAP_ASSIGNMENT" or not message or action.assignment_id is None:
        return

    assignment = session.get(Assignment, action.assignment_id)
    if assignment is None:
        return

    shift = session.get(Shift, assignment.shift_id)
    if shift is None:
        return

    shift_hint = _message_mentions_shift(message)
    if shift_hint and shift.shift_type != shift_hint:
        raise ValueError("assignment_id does not match shift mentioned in message")

    if _message_has_date_hint(message) and not _message_mentions_target_date(message, shift.date):
        raise ValueError("assignment_id does not match date mentioned in message")

    employees = session.exec(select(Employee).where(Employee.is_active == True)).all()
    mentioned_employees = _find_employee_mentions(message, employees)
    if not mentioned_employees:
        return

    if _is_add_like_message(message) and _message_has_with_clause(message) and len(mentioned_employees) == 1:
        raise ValueError("replacement employee mentioned in message was not found in context")

    current_employee = session.get(Employee, assignment.employee_id) if assignment.employee_id else None
    replacement_employee = (
        session.get(Employee, action.replacement_employee_id)
        if action.replacement_employee_id is not None
        else None
    )

    if action.replacement_employee_id is None:
        if current_employee and mentioned_employees[0].id != current_employee.id:
            raise ValueError("assignment_id does not match employee mentioned in message")
        return

    if _is_remove_like_message(message):
        if current_employee and mentioned_employees[0].id != current_employee.id:
            raise ValueError("assignment_id does not match employee mentioned in message")
        return

    if _is_add_like_message(message) and len(mentioned_employees) == 1:
        if replacement_employee and mentioned_employees[0].id != replacement_employee.id:
            raise ValueError(
                "replacement_employee_id does not match employee mentioned in message"
            )
        return

    if current_employee and mentioned_employees[0].id != current_employee.id:
        raise ValueError("assignment_id does not match employee mentioned in message")

    if replacement_employee and mentioned_employees[-1].id != replacement_employee.id:
        raise ValueError(
            "replacement_employee_id does not match employee mentioned in message"
        )


def _resolve_action(payload: ChatCommandRequest, session: Session) -> ChatAction:
    """Resolve incoming payload to a normalized ChatAction.

    Resolution strategy:
    - Explicit action payloads are accepted directly.
    - Natural-language messages are always parsed by the LLM.
    """

    from_llm = False
    action: ChatAction
    if payload.action is not None:
        action = payload.action
    else:
        if not payload.message:
            raise ValueError("message is required when action is omitted")

        role_context = _build_role_context(session)
        parser_message = _build_parser_message(payload.message, role_context, session)
        action = parse_action_from_message(parser_message, role_context)
        from_llm = True

    action.type = action.type.upper()
    _validate_supported_action_type(action.type)
    if action.day_of_week:
        action.day_of_week = action.day_of_week.upper()
    if action.shift_type:
        action.shift_type = action.shift_type.upper()

    if from_llm:
        _validate_autofill_day_consistency(payload.message, action)
        _validate_swap_action_consistency(payload.message, action, session)

    if action.type == "SWAP_ASSIGNMENT" and action.replacement_employee_id is None:
        employees = session.exec(
            select(Employee).where(Employee.is_active == True)
        ).all()
        mentioned_employees = _find_employee_mentions(payload.message, employees)
        if _message_requires_replacement_employee(payload.message, mentioned_employees):
            raise ValueError("replacement_employee_id is required for add/assign intents")

    return action


def _validate_role_requirements(
    requirements: list[RoleRequirement],
    session: Session,
) -> dict[int, int]:
    """Validate role requirements and return compact role_id -> required_count."""

    validated: dict[int, int] = {}
    for item in requirements:
        if item.required_count < 0:
            raise ValueError("required_count must be >= 0")
        role = session.get(Role, item.role_id)
        if role is None:
            raise ValueError(f"role not found: {item.role_id}")
        if item.required_count == 0:
            continue
        validated[item.role_id] = item.required_count

    if not validated:
        raise ValueError(
            "requirements must include at least one item with required_count > 0"
        )

    return validated


def _build_autofill_shift_config(
    action: ChatAction,
    session: Session,
) -> tuple[list[str], dict[str, dict[int, int]] | None]:
    """Build target shifts and optional requirements overrides for autofill."""

    shift_types = list(SHIFT_TYPES)
    if action.shift_type:
        if action.shift_type not in SHIFT_TYPES:
            raise ValueError("shift_type is invalid")
        shift_types = [action.shift_type]

    if not action.requirements:
        return shift_types, None

    requirements = _validate_role_requirements(action.requirements, session)
    requirements_by_shift = {
        shift_type: dict(requirements) for shift_type in shift_types
    }
    return shift_types, requirements_by_shift


def _next_or_same_weekday(start_date: date, weekday: int) -> date:
    delta = (weekday - start_date.weekday()) % 7
    return start_date + timedelta(days=delta)


def _resolve_autofill_target_dates(action: ChatAction) -> list[date]:
    if action.date is not None:
        return [action.date]

    if action.day_of_week:
        day_token = action.day_of_week.upper()
        today = date.today()

        if day_token in {"WEEKEND", "WEEKENDS"}:
            saturday = _next_or_same_weekday(today, 5)
            return [saturday, saturday + timedelta(days=1)]

        if day_token in DAY_TOKEN_TO_WEEKDAY:
            weekday = DAY_TOKEN_TO_WEEKDAY[day_token.lower()]
            return [_next_or_same_weekday(today, weekday)]

    raise ValueError("date is required for AUTOFILL_DAY")


def _resolve_set_rule_days(day_of_week: str) -> list[str]:
    normalized = day_of_week.upper()
    if normalized in DAYS_OF_WEEK:
        return [normalized]

    scoped_days = DAY_SCOPE_TO_DAYS.get(normalized)
    if scoped_days:
        return list(scoped_days)

    raise ValueError("day_of_week is invalid")


def _resolve_set_rule_shift_types(shift_type: str | None) -> list[str]:
    if not shift_type:
        return list(SHIFT_TYPES)

    normalized = shift_type.upper()
    if normalized not in SHIFT_TYPES:
        raise ValueError("shift_type is invalid")
    return [normalized]


def _build_set_rule_requirements(
    action: ChatAction,
    session: Session,
) -> dict[int, int]:
    if action.requirements:
        entries = action.requirements
    elif action.role_id is not None and action.required_count is not None:
        entries = [
            RoleRequirement(role_id=action.role_id, required_count=action.required_count)
        ]
    else:
        raise ValueError(
            "day_of_week and at least one role requirement are required for SET_RULE"
        )

    requirements: dict[int, int] = {}
    for item in entries:
        if item.required_count < 0:
            raise ValueError("required_count must be >= 0")

        role = session.get(Role, item.role_id)
        if role is None:
            raise ValueError(f"role not found: {item.role_id}")

        requirements[item.role_id] = item.required_count

    if not requirements:
        raise ValueError("at least one role requirement is required for SET_RULE")

    return requirements


@router.post("/chat", response_model=ChatCommandResponse)
def chat_command(
    payload: ChatCommandRequest, session: Session = Depends(get_db)
) -> ChatCommandResponse:
    """Execute a resolved chat action and persist command status lifecycle.

    Status transitions: PENDING -> APPLIED on success, PENDING -> FAILED on
    validation/runtime business errors.
    """

    try:
        action = _resolve_action(payload, session)
    except LLMParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    action_type = action.type
    action_payload = action.model_dump(mode="json")
    action_json = json.dumps(action_payload)

    command = ChatCommand(
        message=payload.message or "",
        action_json=action_json,
        status="PENDING",
    )
    session.add(command)
    session.commit()

    try:
        if action_type == "AUTOFILL_DAY":
            target_dates = _resolve_autofill_target_dates(action)
            shift_types, requirements_by_shift = _build_autofill_shift_config(
                action, session
            )
            if len(target_dates) == 1:
                target_date = target_dates[0]
                results = fill_day(
                    session,
                    target_date,
                    reoptimize=action.reoptimize,
                    requirements_by_shift=requirements_by_shift,
                    shift_types=shift_types,
                )
                response = build_autofill_response(target_date, results)
                result_payload = response.model_dump(mode="json")
            else:
                date_results: list[dict[str, object]] = []
                for target_date in target_dates:
                    results = fill_day(
                        session,
                        target_date,
                        reoptimize=action.reoptimize,
                        requirements_by_shift=requirements_by_shift,
                        shift_types=shift_types,
                    )
                    response = build_autofill_response(target_date, results)
                    date_results.append(response.model_dump(mode="json"))

                result_payload = {
                    "dates": date_results,
                }
        elif action_type == "SWAP_ASSIGNMENT":
            if not action.assignment_id:
                raise ValueError("assignment_id is required for SWAP_ASSIGNMENT")

            swap_result = swap_assignment(
                session,
                action.assignment_id,
                replacement_employee_id=action.replacement_employee_id,
            )

            if swap_result is None:
                raise ValueError("assignment not found")

            response = build_swap_response(swap_result)
            result_payload = response.model_dump(mode="json")
        elif action_type == "SET_RULE":
            if not action.day_of_week:
                raise ValueError("day_of_week is required for SET_RULE")

            day_values = _resolve_set_rule_days(action.day_of_week)
            shift_types = _resolve_set_rule_shift_types(action.shift_type)
            requirements = _build_set_rule_requirements(action, session)

            updated_rules: list[ScheduleRule] = []
            for day_of_week in day_values:
                for shift_type in shift_types:
                    for role_id, required_count in requirements.items():
                        rule = session.exec(
                            select(ScheduleRule)
                            .where(ScheduleRule.day_of_week == day_of_week)
                            .where(ScheduleRule.shift_type == shift_type)
                            .where(ScheduleRule.role_id == role_id)
                        ).first()

                        if rule:
                            rule.required_count = required_count
                        else:
                            rule = ScheduleRule(
                                day_of_week=day_of_week,
                                shift_type=shift_type,
                                role_id=role_id,
                                required_count=required_count,
                            )
                            session.add(rule)

                        updated_rules.append(rule)

            session.commit()
            for rule in updated_rules:
                session.refresh(rule)

            serialized_rules = [
                ScheduleRuleRead(
                    id=rule.id,
                    day_of_week=rule.day_of_week,
                    shift_type=rule.shift_type,
                    role_id=rule.role_id,
                    required_count=rule.required_count,
                ).model_dump(mode="json")
                for rule in updated_rules
            ]
            result_payload = (
                serialized_rules[0]
                if len(serialized_rules) == 1
                else {
                    "updated_count": len(serialized_rules),
                    "updated_rules": serialized_rules,
                }
            )
        else:
            raise ValueError("unsupported action type")

        command.status = "APPLIED"
        session.add(command)
        session.commit()

        return ChatCommandResponse(
            status="APPLIED",
            action_type=action_type,
            result=result_payload,
        )
    except ValueError as exc:
        command.status = "FAILED"
        session.add(command)
        session.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
