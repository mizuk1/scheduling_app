from __future__ import annotations

from datetime import date
from typing import Iterable

from sqlmodel import Session, select

from app.models.scheduling import Assignment, Employee, Role, Shift
from app.schemas.scheduling import (
    AutofillResponse,
    ScheduleAssignmentRead,
    ScheduleShiftRead,
    ShiftFillResult,
    SwapResponse,
    UnfilledRole,
)
from app.services.scheduler import FillResult, SwapResult


def build_autofill_response(
    target_date: date, results: dict[str, FillResult]
) -> AutofillResponse:
    response_results: list[ShiftFillResult] = []

    for shift_type, result in results.items():
        unfilled = [
            UnfilledRole(role_id=role_id, missing=missing)
            for role_id, missing in result.unfilled.items()
        ]
        response_results.append(
            ShiftFillResult(
                shift_type=shift_type,
                created=result.created,
                unfilled=unfilled,
            )
        )

    return AutofillResponse(date=target_date, results=response_results)


def build_swap_response(result: SwapResult) -> SwapResponse:
    unfilled = [
        UnfilledRole(role_id=role_id, missing=missing)
        for role_id, missing in result.unfilled.items()
    ]
    return SwapResponse(
        date=result.date,
        shift_type=result.shift_type,
        old_employee_id=result.old_employee_id,
        new_employee_id=result.new_employee_id,
        created=result.created,
        unfilled=unfilled,
    )


def fetch_schedule_rows(
    session: Session, start_date: date | None, end_date: date | None
) -> list[tuple[Assignment, Shift, Role, Employee | None]]:
    query = (
        select(Assignment, Shift, Role, Employee)
        .join(Shift, Assignment.shift_id == Shift.id)
        .join(Role, Assignment.role_id == Role.id)
        .outerjoin(Employee, Assignment.employee_id == Employee.id)
    )
    if start_date:
        query = query.where(Shift.date >= start_date)
    if end_date:
        query = query.where(Shift.date <= end_date)

    return session.exec(
        query.order_by(Shift.date, Shift.shift_type, Role.name)
    ).all()


def build_schedule_shifts(
    rows: Iterable[tuple[Assignment, Shift, Role, Employee | None]]
) -> list[ScheduleShiftRead]:
    grouped: dict[tuple[date, str], list[ScheduleAssignmentRead]] = {}
    for assignment, shift, role, employee in rows:
        key = (shift.date, shift.shift_type)
        grouped.setdefault(key, []).append(
            ScheduleAssignmentRead(
                assignment_id=assignment.id,
                role_id=role.id,
                role_name=role.name,
                employee_id=employee.id if employee else None,
                employee_name=employee.name if employee else None,
            )
        )

    return [
        ScheduleShiftRead(date=key[0], shift_type=key[1], assignments=assignments)
        for key, assignments in grouped.items()
    ]


def get_schedule_shifts(
    session: Session, start_date: date | None = None, end_date: date | None = None
) -> list[ScheduleShiftRead]:
    rows = fetch_schedule_rows(session, start_date, end_date)
    return build_schedule_shifts(rows)
