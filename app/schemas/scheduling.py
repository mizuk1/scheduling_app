import datetime as dt
from typing import Any

from sqlmodel import SQLModel


class EmployeeRead(SQLModel):
    id: int
    name: str
    is_active: bool
    max_weekly_hours: int


class RoleRead(SQLModel):
    id: int
    name: str


class AvailabilityRead(SQLModel):
    id: int
    employee_id: int
    day_of_week: str
    shift_type: str
    is_available: bool


class AutofillRequest(SQLModel):
    date: dt.date
    reoptimize: bool = False


class UnfilledRole(SQLModel):
    role_id: int
    missing: int


class ShiftFillResult(SQLModel):
    shift_type: str
    created: int
    unfilled: list[UnfilledRole]


class AutofillResponse(SQLModel):
    date: dt.date
    results: list[ShiftFillResult]


class AssignmentRead(SQLModel):
    assignment_id: int
    date: dt.date
    shift_type: str
    role_id: int
    role_name: str
    employee_id: int | None
    employee_name: str | None


class ScheduleAssignmentRead(SQLModel):
    assignment_id: int
    role_id: int
    role_name: str
    employee_id: int | None
    employee_name: str | None


class ScheduleShiftRead(SQLModel):
    date: dt.date
    shift_type: str
    assignments: list[ScheduleAssignmentRead]


class SwapRequest(SQLModel):
    assignment_id: int
    replacement_employee_id: int | None = None


class SwapResponse(SQLModel):
    date: dt.date
    shift_type: str
    old_employee_id: int | None
    new_employee_id: int | None
    created: int
    unfilled: list[UnfilledRole]


class ChatAction(SQLModel):
    type: str
    date: dt.date | None = None
    reoptimize: bool = False
    assignment_id: int | None = None
    replacement_employee_id: int | None = None
    start_date: dt.date | None = None
    end_date: dt.date | None = None


class ChatCommandRequest(SQLModel):
    message: str | None = None
    action: ChatAction


class ChatCommandResponse(SQLModel):
    status: str
    action_type: str
    result: Any | None = None


class ScheduleRuleRead(SQLModel):
    id: int
    day_of_week: str
    shift_type: str
    role_id: int
    required_count: int
