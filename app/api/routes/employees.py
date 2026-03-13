import datetime as dt
from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.api.deps import get_db
from app.models.scheduling import Assignment, Availability, Employee, EmployeeRole, Role, Shift
from app.schemas.scheduling import EmployeeInsightRead, EmployeeRead
from app.services.scheduler import SHIFT_HOURS

router = APIRouter()


@router.get("/employees", response_model=list[EmployeeRead])
def list_employees(session: Session = Depends(get_db)) -> list[EmployeeRead]:
    return session.exec(select(Employee).order_by(Employee.name)).all()


@router.get("/employees/insights", response_model=list[EmployeeInsightRead])
def list_employee_insights(
    week_start: dt.date | None = None,
    session: Session = Depends(get_db),
) -> list[EmployeeInsightRead]:
    if week_start is None:
        today = dt.date.today()
        week_start = today - dt.timedelta(days=today.weekday())

    week_end = week_start + dt.timedelta(days=6)

    employees = session.exec(select(Employee).order_by(Employee.name)).all()

    role_rows = session.exec(
        select(EmployeeRole, Role).join(Role, EmployeeRole.role_id == Role.id)
    ).all()
    roles_by_employee: dict[int, list[str]] = defaultdict(list)
    for membership, role in role_rows:
        roles_by_employee[membership.employee_id].append(role.name)

    restrictions_rows = session.exec(
        select(Availability)
        .where(Availability.is_available == False)
        .order_by(Availability.day_of_week, Availability.shift_type)
    ).all()
    restrictions_by_employee: dict[int, list[str]] = defaultdict(list)
    for row in restrictions_rows:
        restrictions_by_employee[row.employee_id].append(
            f"{row.day_of_week} {row.shift_type}"
        )

    assignment_rows = session.exec(
        select(Assignment, Shift)
        .join(Shift, Assignment.shift_id == Shift.id)
        .where(Assignment.employee_id.is_not(None))
        .where(Shift.date >= week_start)
        .where(Shift.date <= week_end)
    ).all()
    worked_hours_by_employee: dict[int, int] = defaultdict(int)
    for assignment, shift in assignment_rows:
        if assignment.employee_id is None:
            continue
        worked_hours_by_employee[assignment.employee_id] += SHIFT_HOURS.get(
            shift.shift_type, 0
        )

    insights: list[EmployeeInsightRead] = []
    for employee in employees:
        if employee.id is None:
            continue
        worked_hours = worked_hours_by_employee.get(employee.id, 0)
        insights.append(
            EmployeeInsightRead(
                id=employee.id,
                name=employee.name,
                is_active=employee.is_active,
                max_weekly_hours=employee.max_weekly_hours,
                worked_hours_week=worked_hours,
                remaining_hours_week=max(employee.max_weekly_hours - worked_hours, 0),
                roles=roles_by_employee.get(employee.id, []),
                restrictions=restrictions_by_employee.get(employee.id, []),
            )
        )

    return insights
