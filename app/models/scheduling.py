from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, SQLModel

SHIFT_TYPES = ("LUNCH", "DINNER")
DAYS_OF_WEEK = (
    "MONDAY",
    "TUESDAY",
    "WEDNESDAY",
    "THURSDAY",
    "FRIDAY",
    "SATURDAY",
    "SUNDAY",
)
COMMAND_STATUSES = ("PENDING", "APPLIED", "FAILED")


class Employee(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    is_active: bool = Field(default=True)
    max_weekly_hours: int = Field(default=40)


class Role(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)


class EmployeeRole(SQLModel, table=True):
    employee_id: int = Field(foreign_key="employee.id", primary_key=True)
    role_id: int = Field(foreign_key="role.id", primary_key=True)


class Availability(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    employee_id: int = Field(foreign_key="employee.id")
    day_of_week: str = Field(index=True)
    shift_type: str = Field(index=True)
    is_available: bool = Field(default=True)


class ScheduleRule(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    day_of_week: str = Field(index=True)
    shift_type: str = Field(index=True)
    role_id: int = Field(foreign_key="role.id")
    required_count: int


class Shift(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    date: date
    shift_type: str = Field(index=True)


class Assignment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    shift_id: int = Field(foreign_key="shift.id")
    role_id: int = Field(foreign_key="role.id")
    employee_id: Optional[int] = Field(default=None, foreign_key="employee.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ChatCommand(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    message: str
    action_json: str
    status: str = Field(default="PENDING")
    created_at: datetime = Field(default_factory=datetime.utcnow)
