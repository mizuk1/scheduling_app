from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.api.deps import get_db
from app.models.scheduling import Assignment, Employee, Role, Shift
from app.schemas.scheduling import (
    AssignmentRead,
    AutofillRequest,
    AutofillResponse,
    ScheduleShiftRead,
    SwapRequest,
    SwapResponse,
)
from app.services.schedule_queries import (
    build_autofill_response,
    build_swap_response,
    get_schedule_shifts,
)
from app.services.scheduler import fill_day, swap_assignment

router = APIRouter()


@router.post("/schedules/autofill", response_model=AutofillResponse)
def autofill_schedule(
    payload: AutofillRequest, session: Session = Depends(get_db)
) -> AutofillResponse:
    results = fill_day(session, payload.date, reoptimize=payload.reoptimize)
    return build_autofill_response(payload.date, results)


@router.get("/assignments", response_model=list[AssignmentRead])
def list_assignments(
    date_filter: date | None = None, session: Session = Depends(get_db)
) -> list[AssignmentRead]:
    query = (
        select(Assignment, Shift, Role, Employee)
        .join(Shift, Assignment.shift_id == Shift.id)
        .join(Role, Assignment.role_id == Role.id)
        .outerjoin(Employee, Assignment.employee_id == Employee.id)
    )
    if date_filter:
        query = query.where(Shift.date == date_filter)

    rows = session.exec(query).all()
    results: list[AssignmentRead] = []
    for assignment, shift, role, employee in rows:
        results.append(
            AssignmentRead(
                assignment_id=assignment.id,
                date=shift.date,
                shift_type=shift.shift_type,
                role_id=role.id,
                role_name=role.name,
                employee_id=employee.id if employee else None,
                employee_name=employee.name if employee else None,
            )
        )

    return results


@router.get("/schedules", response_model=list[ScheduleShiftRead])
def list_schedules(
    start_date: date | None = None,
    end_date: date | None = None,
    session: Session = Depends(get_db),
) -> list[ScheduleShiftRead]:
    return get_schedule_shifts(session, start_date, end_date)


@router.post("/schedules/swap", response_model=SwapResponse)
def swap_schedule_assignment(
    payload: SwapRequest, session: Session = Depends(get_db)
) -> SwapResponse:
    try:
        result = swap_assignment(
            session,
            payload.assignment_id,
            replacement_employee_id=payload.replacement_employee_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if result is None:
        raise HTTPException(status_code=404, detail="Assignment not found.")
    return build_swap_response(result)
