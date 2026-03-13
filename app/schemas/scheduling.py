import datetime as dt
from typing import Any

from pydantic import model_validator
from sqlmodel import SQLModel


class EmployeeRead(SQLModel):
    id: int
    name: str
    is_active: bool
    max_weekly_hours: int


class EmployeeInsightRead(SQLModel):
    id: int
    name: str
    is_active: bool
    max_weekly_hours: int
    worked_hours_week: int
    remaining_hours_week: int
    roles: list[str]
    restrictions: list[str]


class RoleRead(SQLModel):
    id: int
    name: str


class AvailabilityRead(SQLModel):
    id: int
    employee_id: int
    day_of_week: str
    shift_type: str
    is_available: bool


class RoleRequirement(SQLModel):
    role_id: int
    required_count: int


class AutofillRequest(SQLModel):
    date: dt.date
    reoptimize: bool = False
    shift_type: str | None = None
    requirements: list[RoleRequirement] | None = None


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
    day_of_week: str | None = None
    shift_type: str | None = None
    role_id: int | None = None
    required_count: int | None = None
    requirements: list[RoleRequirement] | None = None


class ChatCommandRequest(SQLModel):
    message: str | None = None
    action: ChatAction | None = None

    @model_validator(mode="after")
    def validate_message_or_action(self) -> "ChatCommandRequest":
        if not self.message and self.action is None:
            raise ValueError("either message or action is required")
        return self


class ChatCommandResponse(SQLModel):
    status: str
    action_type: str
    result: Any | None = None


class ChatImpactPreview(SQLModel):
    shifts: int
    people: int
    assignments: int
    summary: str


class ChatPreviewResponse(SQLModel):
    status: str
    action_type: str
    action: ChatAction
    impact: ChatImpactPreview
    preview_message: str


class ScheduleRuleRead(SQLModel):
    id: int
    day_of_week: str
    shift_type: str
    role_id: int
    required_count: int
