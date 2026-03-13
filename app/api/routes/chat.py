import json

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.api.deps import get_db
from app.models.scheduling import (
    ChatCommand,
    DAYS_OF_WEEK,
    SHIFT_TYPES,
    Role,
    ScheduleRule,
)
from app.schemas.scheduling import (
    ChatCommandRequest,
    ChatCommandResponse,
    ScheduleRuleRead,
)
from app.services.schedule_queries import (
    build_autofill_response,
    build_swap_response,
    get_schedule_shifts,
)
from app.services.scheduler import fill_day, swap_assignment

router = APIRouter()


@router.post("/chat/command", response_model=ChatCommandResponse)
def chat_command(
    payload: ChatCommandRequest, session: Session = Depends(get_db)
) -> ChatCommandResponse:
    action = payload.action
    action_type = action.type.upper()
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
            results = fill_day(session, action.date, reoptimize=action.reoptimize)
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
