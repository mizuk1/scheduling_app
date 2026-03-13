import json
from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.api.deps import get_db
from app.models.scheduling import (
    Assignment,
    Availability,
    ChatCommand,
    DAYS_OF_WEEK,
    Employee,
    EmployeeRole,
    SHIFT_TYPES,
    Role,
    ScheduleRule,
    Shift,
)
from app.schemas.scheduling import (
    ChatCommandRequest,
    ChatCommandResponse,
    ChatAction,
    ChatImpactPreview,
    ChatPreviewResponse,
    RoleRequirement,
    ScheduleRuleRead,
)
from app.services.schedule_queries import (
    build_autofill_response,
    build_swap_response,
    get_schedule_shifts,
)
from app.services.local_chat_parser import (
    parse_action_from_message_local,
    parse_swap_remove_intent_local,
)
from app.services.scheduler import fill_day, swap_assignment
from app.services.llm_parser import LLMParseError, parse_action_from_message

router = APIRouter()


def _resolve_action(payload: ChatCommandRequest, session: Session) -> ChatAction:
    action: ChatAction
    if payload.action is not None:
        action = payload.action
    else:
        if not payload.message:
            raise ValueError("message is required when action is omitted")

        employee_names = [
            employee.name
            for employee in session.exec(select(Employee).where(Employee.is_active == True)).all()
            if employee.id is not None
        ]
        remove_intent = parse_swap_remove_intent_local(payload.message, employee_names)
        if remove_intent is not None:
            assignment_query = (
                select(Assignment, Shift, Employee)
                .join(Shift, Assignment.shift_id == Shift.id)
                .join(Employee, Assignment.employee_id == Employee.id)
                .where(Employee.name == remove_intent.employee_name)
            )

            if remove_intent.target_date is not None:
                assignment_query = assignment_query.where(Shift.date == remove_intent.target_date)
            if remove_intent.shift_type is not None:
                assignment_query = assignment_query.where(
                    Shift.shift_type == remove_intent.shift_type
                )

            matches = session.exec(assignment_query.order_by(Shift.date.desc())).all()
            if not matches:
                raise ValueError("no assignment found for employee with the provided filters")

            if len(matches) > 1 and (
                remove_intent.target_date is None or remove_intent.shift_type is None
            ):
                raise ValueError(
                    "multiple assignments found; include both date and shift in the message"
                )

            assignment = matches[0][0]
            if assignment.id is None:
                raise ValueError("assignment id could not be resolved")

            action = ChatAction(
                type="SWAP_ASSIGNMENT",
                assignment_id=assignment.id,
                replacement_employee_id=None,
            )
            return action

        role_context = [
            {"id": role.id, "name": role.name}
            for role in session.exec(select(Role)).all()
            if role.id is not None
        ]

        # Prefer deterministic local parsing for day autofill commands with role counts.
        local_action = parse_action_from_message_local(payload.message, role_context)
        if local_action is not None:
            action = local_action
        else:
            action = parse_action_from_message(payload.message, role_context)

    action.type = action.type.upper()
    if action.day_of_week:
        action.day_of_week = action.day_of_week.upper()
    if action.shift_type:
        action.shift_type = action.shift_type.upper()
    return action


def _build_autofill_preview(action: ChatAction, session: Session) -> ChatImpactPreview:
    if not action.date:
        raise ValueError("date is required for AUTOFILL_DAY")

    shift_types = list(SHIFT_TYPES)
    if action.shift_type:
        if action.shift_type not in SHIFT_TYPES:
            raise ValueError("shift_type is invalid")
        shift_types = [action.shift_type]

    custom_requirements: dict[int, int] | None = None
    if action.requirements:
        custom_requirements = _validate_role_requirements(action.requirements, session)

    day_of_week = DAYS_OF_WEEK[action.date.weekday()]
    impacted_shifts = 0
    assignments_to_create = 0
    eligible_people: set[int] = set()

    for shift_type in shift_types:
        if custom_requirements is not None:
            required_by_role = custom_requirements
        else:
            rules = session.exec(
                select(ScheduleRule)
                .where(ScheduleRule.day_of_week == day_of_week)
                .where(ScheduleRule.shift_type == shift_type)
            ).all()
            if not rules:
                continue

            required_by_role = {rule.role_id: rule.required_count for rule in rules}

        existing_rows = session.exec(
            select(Assignment)
            .join(Shift, Assignment.shift_id == Shift.id)
            .where(Shift.date == action.date)
            .where(Shift.shift_type == shift_type)
        ).all()

        existing_by_role: dict[int, int] = defaultdict(int)
        for assignment in existing_rows:
            existing_by_role[assignment.role_id] += 1

        missing_by_role: dict[int, int] = {}
        missing_total = 0
        for role_id, required_count in required_by_role.items():
            missing = max(required_count - existing_by_role.get(role_id, 0), 0)
            if missing > 0:
                missing_by_role[role_id] = missing
                missing_total += missing

        if missing_total <= 0:
            continue

        impacted_shifts += 1
        assignments_to_create += missing_total

        missing_role_ids = list(missing_by_role.keys())
        role_people = set(
            session.exec(
                select(EmployeeRole.employee_id)
                .join(Employee, EmployeeRole.employee_id == Employee.id)
                .where(Employee.is_active == True)
                .where(EmployeeRole.role_id.in_(missing_role_ids))
            ).all()
        )
        available_people = set(
            session.exec(
                select(Availability.employee_id)
                .where(Availability.day_of_week == day_of_week)
                .where(Availability.shift_type == shift_type)
                .where(Availability.is_available == True)
            ).all()
        )
        eligible_people.update(role_people & available_people)

    people_count = min(assignments_to_create, len(eligible_people))
    summary = (
        f"I will update {impacted_shifts} shifts and potentially {people_count} people "
        f"({assignments_to_create} assignments)."
    )
    return ChatImpactPreview(
        shifts=impacted_shifts,
        people=people_count,
        assignments=assignments_to_create,
        summary=summary,
    )


def _validate_role_requirements(
    requirements: list[RoleRequirement],
    session: Session,
) -> dict[int, int]:
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


def _build_swap_preview(action: ChatAction, session: Session) -> ChatImpactPreview:
    if not action.assignment_id:
        raise ValueError("assignment_id is required for SWAP_ASSIGNMENT")

    assignment = session.get(Assignment, action.assignment_id)
    if not assignment:
        raise ValueError("assignment not found")

    people_count = 1
    if (
        action.replacement_employee_id is not None
        and action.replacement_employee_id != assignment.employee_id
    ):
        people_count = 2

    summary = f"I will update 1 shift and {people_count} person(s) in the swap."
    return ChatImpactPreview(
        shifts=1,
        people=people_count,
        assignments=1,
        summary=summary,
    )


def _build_list_preview(action: ChatAction, session: Session) -> ChatImpactPreview:
    schedules = get_schedule_shifts(session, action.start_date, action.end_date)
    viewed = len(schedules)
    summary = f"Schedule query: {viewed} shifts viewed, no changes applied."
    return ChatImpactPreview(shifts=0, people=0, assignments=0, summary=summary)


def _build_set_rule_preview(action: ChatAction, session: Session) -> ChatImpactPreview:
    if (
        not action.day_of_week
        or not action.shift_type
        or action.role_id is None
        or action.required_count is None
    ):
        raise ValueError(
            "day_of_week, shift_type, role_id, required_count are required for SET_RULE"
        )

    day_of_week = action.day_of_week.upper()
    shift_type = action.shift_type.upper()
    if day_of_week not in DAYS_OF_WEEK:
        raise ValueError("day_of_week is invalid")
    if shift_type not in SHIFT_TYPES:
        raise ValueError("shift_type is invalid")

    role = session.get(Role, action.role_id)
    if not role:
        raise ValueError("role not found")

    summary = "I will update 1 rule. No shift is changed immediately."
    return ChatImpactPreview(shifts=0, people=0, assignments=0, summary=summary)


def _build_impact_preview(action: ChatAction, session: Session) -> ChatImpactPreview:
    action_type = action.type.upper()
    if action_type == "AUTOFILL_DAY":
        return _build_autofill_preview(action, session)
    if action_type == "SWAP_ASSIGNMENT":
        return _build_swap_preview(action, session)
    if action_type == "LIST_SCHEDULE":
        return _build_list_preview(action, session)
    if action_type == "SET_RULE":
        return _build_set_rule_preview(action, session)
    raise ValueError("unsupported action type")


@router.post("/chat/preview", response_model=ChatPreviewResponse)
def chat_preview(
    payload: ChatCommandRequest, session: Session = Depends(get_db)
) -> ChatPreviewResponse:
    try:
        action = _resolve_action(payload, session)
        impact = _build_impact_preview(action, session)
    except LLMParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ChatPreviewResponse(
        status="PREVIEW",
        action_type=action.type,
        action=action,
        impact=impact,
        preview_message=f"Preview: {impact.summary} Confirm execution?",
    )


@router.post("/chat/command", response_model=ChatCommandResponse)
def chat_command(
    payload: ChatCommandRequest, session: Session = Depends(get_db)
) -> ChatCommandResponse:
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
            if not action.date:
                raise ValueError("date is required for AUTOFILL_DAY")

            shift_types, requirements_by_shift = _build_autofill_shift_config(
                action, session
            )
            results = fill_day(
                session,
                action.date,
                reoptimize=action.reoptimize,
                requirements_by_shift=requirements_by_shift,
                shift_types=shift_types,
            )
            response = build_autofill_response(action.date, results)
            result_payload = response.model_dump(mode="json")
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
        elif action_type == "LIST_SCHEDULE":
            schedules = get_schedule_shifts(session, action.start_date, action.end_date)
            result_payload = [item.model_dump(mode="json") for item in schedules]
        elif action_type == "SET_RULE":
            if (
                not action.day_of_week
                or not action.shift_type
                or action.role_id is None
                or action.required_count is None
            ):
                raise ValueError(
                    "day_of_week, shift_type, role_id, required_count are required for SET_RULE"
                )

            day_of_week = action.day_of_week.upper()
            shift_type = action.shift_type.upper()

            if day_of_week not in DAYS_OF_WEEK:
                raise ValueError("day_of_week is invalid")
            if shift_type not in SHIFT_TYPES:
                raise ValueError("shift_type is invalid")

            role = session.get(Role, action.role_id)
            if not role:
                raise ValueError("role not found")

            rule = session.exec(
                select(ScheduleRule)
                .where(ScheduleRule.day_of_week == day_of_week)
                .where(ScheduleRule.shift_type == shift_type)
                .where(ScheduleRule.role_id == action.role_id)
            ).first()

            if rule:
                rule.required_count = action.required_count
            else:
                rule = ScheduleRule(
                    day_of_week=day_of_week,
                    shift_type=shift_type,
                    role_id=action.role_id,
                    required_count=action.required_count,
                )
                session.add(rule)

            session.commit()
            session.refresh(rule)
            result_payload = ScheduleRuleRead(
                id=rule.id,
                day_of_week=rule.day_of_week,
                shift_type=rule.shift_type,
                role_id=rule.role_id,
                required_count=rule.required_count,
            ).model_dump(mode="json")
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
