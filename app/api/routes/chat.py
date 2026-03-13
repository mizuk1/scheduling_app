import json

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.api.deps import get_db
from app.models.scheduling import ChatCommand
from app.schemas.scheduling import ChatCommandRequest, ChatCommandResponse
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
