from sqlmodel import SQLModel


class EmployeeRead(SQLModel):
    id: int
    name: str
    is_active: bool
    max_weekly_hours: int


class RoleRead(SQLModel):
    id: int
    name: str


class ScheduleRuleRead(SQLModel):
    id: int
    day_of_week: str
    shift_type: str
    role_id: int
    required_count: int
