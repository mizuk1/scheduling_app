from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

from sqlmodel import Session, select

from app.models.scheduling import (
    Assignment,
    Availability,
    DAYS_OF_WEEK,
    Employee,
    EmployeeRole,
    Role,
    ScheduleRule,
    Shift,
    SHIFT_TYPES,
)

SHIFT_HOURS = {
    "LUNCH": 4,
    "DINNER": 5,
}


@dataclass
class FillResult:
    created: int
    unfilled: dict[int, int]


@dataclass
class SwapResult:
    date: date
    shift_type: str
    old_employee_id: int | None
    new_employee_id: int | None
    created: int
    unfilled: dict[int, int]


def get_day_of_week(target_date: date) -> str:
    return DAYS_OF_WEEK[target_date.weekday()]


def _get_week_range(target_date: date) -> tuple[date, date]:
    week_start = target_date - timedelta(days=target_date.weekday())
    week_end = week_start + timedelta(days=6)
    return week_start, week_end


def _load_weekly_hours(
    session: Session, week_start: date, week_end: date
) -> dict[int, int]:
    hours: dict[int, int] = defaultdict(int)
    assignments = session.exec(
        select(Assignment, Shift)
        .join(Shift, Assignment.shift_id == Shift.id)
        .where(Shift.date >= week_start)
        .where(Shift.date <= week_end)
        .where(Assignment.employee_id.is_not(None))
    ).all()

    for assignment, shift in assignments:
        if assignment.employee_id is None:
            continue
        hours[assignment.employee_id] += SHIFT_HOURS.get(shift.shift_type, 0)

    return hours


def _get_shift(session: Session, target_date: date, shift_type: str) -> Shift:
    shift = session.exec(
        select(Shift)
        .where(Shift.date == target_date)
        .where(Shift.shift_type == shift_type)
    ).first()
    if shift:
        return shift

    shift = Shift(date=target_date, shift_type=shift_type)
    session.add(shift)
    session.commit()
    session.refresh(shift)
    return shift


def _get_role_requirements(
    session: Session, day_of_week: str, shift_type: str
) -> dict[int, int]:
    rules = session.exec(
        select(ScheduleRule)
        .where(ScheduleRule.day_of_week == day_of_week)
        .where(ScheduleRule.shift_type == shift_type)
    ).all()
    return {rule.role_id: rule.required_count for rule in rules}


def _build_role_domains(
    session: Session, day_of_week: str, shift_type: str
) -> dict[int, list[int]]:
    employees = session.exec(select(Employee).where(Employee.is_active == True)).all()
    employee_ids = {employee.id for employee in employees if employee.id is not None}

    role_memberships = session.exec(select(EmployeeRole)).all()
    available = session.exec(
        select(Availability)
        .where(Availability.day_of_week == day_of_week)
        .where(Availability.shift_type == shift_type)
        .where(Availability.is_available == True)
    ).all()

    available_ids = {availability.employee_id for availability in available}

    role_to_employees: dict[int, set[int]] = defaultdict(set)
    for membership in role_memberships:
        if membership.employee_id in employee_ids:
            role_to_employees[membership.role_id].add(membership.employee_id)

    domains: dict[int, list[int]] = {}
    for role_id, members in role_to_employees.items():
        eligible = members & available_ids
        domains[role_id] = sorted(eligible)

    return domains


def _build_max_hours(session: Session) -> dict[int, int]:
    max_hours: dict[int, int] = {}
    for employee in session.exec(select(Employee)).all():
        if employee.id is None:
            continue
        max_hours[employee.id] = employee.max_weekly_hours
    return max_hours


def _is_employee_eligible(
    session: Session, employee_id: int, role_id: int, day_of_week: str, shift_type: str
) -> bool:
    employee = session.get(Employee, employee_id)
    if not employee or not employee.is_active:
        return False

    membership = session.exec(
        select(EmployeeRole)
        .where(EmployeeRole.employee_id == employee_id)
        .where(EmployeeRole.role_id == role_id)
    ).first()
    if not membership:
        return False

    availability = session.exec(
        select(Availability)
        .where(Availability.employee_id == employee_id)
        .where(Availability.day_of_week == day_of_week)
        .where(Availability.shift_type == shift_type)
        .where(Availability.is_available == True)
    ).first()

    return availability is not None


def _select_slot(slots: list[int], domains: list[list[int]]) -> int:
    best_index = 0
    best_size = len(domains[0])
    for idx, domain in enumerate(domains):
        size = len(domain)
        if size < best_size:
            best_index = idx
            best_size = size
    return best_index


def _solve_slots(
    slots: list[int],
    domains: list[list[int]],
    used: set[int],
    weekly_hours: dict[int, int],
    max_hours: dict[int, int],
    shift_hours: int,
) -> list[tuple[int, int]] | None:
    if not slots:
        return []

    slot_index = _select_slot(slots, domains)
    role_id = slots[slot_index]
    domain = domains[slot_index]

    candidates = [emp for emp in domain if emp not in used]
    candidates.sort(key=lambda emp: weekly_hours.get(emp, 0))

    if not candidates:
        return None

    next_slots = slots[:slot_index] + slots[slot_index + 1 :]
    next_domains = domains[:slot_index] + domains[slot_index + 1 :]

    for employee_id in candidates:
        current_hours = weekly_hours.get(employee_id, 0)
        if current_hours + shift_hours > max_hours.get(employee_id, 0):
            continue

        used.add(employee_id)
        weekly_hours[employee_id] = current_hours + shift_hours

        solved = _solve_slots(
            next_slots,
            next_domains,
            used,
            weekly_hours,
            max_hours,
            shift_hours,
        )
        if solved is not None:
            return [(role_id, employee_id)] + solved

        used.remove(employee_id)
        weekly_hours[employee_id] = current_hours

    return None


def _greedy_assign(
    slots: list[int],
    domains: list[list[int]],
    used: set[int],
    weekly_hours: dict[int, int],
    max_hours: dict[int, int],
    shift_hours: int,
) -> tuple[list[tuple[int, int]], dict[int, int]]:
    assignments: list[tuple[int, int]] = []
    unfilled: dict[int, int] = defaultdict(int)

    ordered = sorted(range(len(slots)), key=lambda idx: len(domains[idx]))

    for idx in ordered:
        role_id = slots[idx]
        domain = domains[idx]
        candidates = [emp for emp in domain if emp not in used]
        candidates.sort(key=lambda emp: weekly_hours.get(emp, 0))

        assigned = False
        for employee_id in candidates:
            current_hours = weekly_hours.get(employee_id, 0)
            if current_hours + shift_hours > max_hours.get(employee_id, 0):
                continue
            used.add(employee_id)
            weekly_hours[employee_id] = current_hours + shift_hours
            assignments.append((role_id, employee_id))
            assigned = True
            break

        if not assigned:
            unfilled[role_id] += 1

    return assignments, unfilled


def _delete_assignments(session: Session, assignments: Iterable[Assignment]) -> None:
    for assignment in assignments:
        session.delete(assignment)


def fill_shift(
    session: Session,
    target_date: date,
    shift_type: str,
    reoptimize: bool = False,
    requirements_override: dict[int, int] | None = None,
) -> FillResult:
    day_of_week = get_day_of_week(target_date)
    requirements = (
        requirements_override
        if requirements_override is not None
        else _get_role_requirements(session, day_of_week, shift_type)
    )
    if not requirements:
        return FillResult(created=0, unfilled={})

    shift = _get_shift(session, target_date, shift_type)
    existing = session.exec(
        select(Assignment).where(Assignment.shift_id == shift.id)
    ).all()

    if reoptimize and existing:
        _delete_assignments(session, existing)
        session.commit()
        existing = []

    used = {assignment.employee_id for assignment in existing if assignment.employee_id}

    existing_by_role: dict[int, int] = defaultdict(int)
    for assignment in existing:
        existing_by_role[assignment.role_id] += 1

    slots: list[int] = []
    for role_id, required_count in requirements.items():
        missing = required_count - existing_by_role.get(role_id, 0)
        if missing > 0:
            slots.extend([role_id] * missing)

    if not slots:
        return FillResult(created=0, unfilled={})

    domains_by_role = _build_role_domains(session, day_of_week, shift_type)
    domains = [domains_by_role.get(role_id, []) for role_id in slots]

    week_start, week_end = _get_week_range(target_date)
    weekly_hours = _load_weekly_hours(session, week_start, week_end)
    max_hours = _build_max_hours(session)
    shift_hours = SHIFT_HOURS.get(shift_type, 0)

    solution = _solve_slots(
        slots, domains, used.copy(), weekly_hours.copy(), max_hours, shift_hours
    )

    if solution is None:
        solution, unfilled = _greedy_assign(
            slots, domains, used, weekly_hours, max_hours, shift_hours
        )
    else:
        unfilled = {}

    for role_id, employee_id in solution:
        session.add(
            Assignment(
                shift_id=shift.id,
                role_id=role_id,
                employee_id=employee_id,
            )
        )

    session.commit()
    return FillResult(created=len(solution), unfilled=unfilled)


def fill_day(
    session: Session,
    target_date: date,
    reoptimize: bool = False,
    requirements_by_shift: dict[str, dict[int, int]] | None = None,
    shift_types: list[str] | None = None,
) -> dict[str, FillResult]:
    results: dict[str, FillResult] = {}
    target_shift_types = shift_types or list(SHIFT_TYPES)

    for shift_type in target_shift_types:
        results[shift_type] = fill_shift(
            session,
            target_date,
            shift_type,
            reoptimize=reoptimize,
            requirements_override=(requirements_by_shift or {}).get(shift_type),
        )
    return results


def swap_assignment(
    session: Session,
    assignment_id: int,
    replacement_employee_id: int | None = None,
) -> SwapResult | None:
    assignment = session.get(Assignment, assignment_id)
    if not assignment:
        return None

    shift = session.get(Shift, assignment.shift_id)
    if not shift:
        return None

    day_of_week = get_day_of_week(shift.date)
    old_employee_id = assignment.employee_id

    if replacement_employee_id is None:
        session.delete(assignment)
        session.commit()
        fill_result = fill_shift(session, shift.date, shift.shift_type)
        return SwapResult(
            date=shift.date,
            shift_type=shift.shift_type,
            old_employee_id=old_employee_id,
            new_employee_id=None,
            created=fill_result.created,
            unfilled=fill_result.unfilled,
        )

    if not _is_employee_eligible(
        session, replacement_employee_id, assignment.role_id, day_of_week, shift.shift_type
    ):
        raise ValueError("Replacement employee is not eligible for this role/shift.")

    already_assigned = session.exec(
        select(Assignment)
        .where(Assignment.shift_id == shift.id)
        .where(Assignment.employee_id == replacement_employee_id)
    ).first()
    if already_assigned:
        raise ValueError("Replacement employee is already assigned in this shift.")

    week_start, week_end = _get_week_range(shift.date)
    weekly_hours = _load_weekly_hours(session, week_start, week_end)
    max_hours = _build_max_hours(session)
    shift_hours = SHIFT_HOURS.get(shift.shift_type, 0)

    if old_employee_id:
        weekly_hours[old_employee_id] = max(
            0, weekly_hours.get(old_employee_id, 0) - shift_hours
        )

    current_hours = weekly_hours.get(replacement_employee_id, 0)
    if current_hours + shift_hours > max_hours.get(replacement_employee_id, 0):
        raise ValueError("Replacement employee exceeds weekly hours limit.")

    assignment.employee_id = replacement_employee_id
    session.add(assignment)
    session.commit()

    return SwapResult(
        date=shift.date,
        shift_type=shift.shift_type,
        old_employee_id=old_employee_id,
        new_employee_id=replacement_employee_id,
        created=0,
        unfilled={},
    )
