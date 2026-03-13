from datetime import date

from sqlmodel import Session, SQLModel, create_engine, select

from app.models.scheduling import (
    Assignment,
    Availability,
    Employee,
    EmployeeRole,
    Role,
    ScheduleRule,
    Shift,
)
from app.api.routes.employees import list_employee_insights
from app.seed.seed_data import seed_db
from app.services.scheduler import fill_day


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_seed_creates_core_data() -> None:
    with create_session() as session:
        seed_db(session)

        assert session.exec(select(Employee)).first() is not None
        assert session.exec(select(Role)).first() is not None
        assert session.exec(select(Availability)).first() is not None
        assert session.exec(select(ScheduleRule)).first() is not None

        availability_count = len(session.exec(select(Availability)).all())
        rule_count = len(session.exec(select(ScheduleRule)).all())

        assert availability_count == 12 * 7 * 2
        assert rule_count == 4 * 7 * 2


def test_fill_day_creates_assignments() -> None:
    with create_session() as session:
        seed_db(session)
        results = fill_day(session, date(2026, 3, 18))

        assert "LUNCH" in results
        assert "DINNER" in results

        shifts = session.exec(select(Shift)).all()
        assignments = session.exec(select(Assignment)).all()

        assert len(shifts) == 2
        assert len(assignments) > 0

        for shift in shifts:
            shift_assignments = session.exec(
                select(Assignment).where(Assignment.shift_id == shift.id)
            ).all()
            employee_ids = [
                assignment.employee_id
                for assignment in shift_assignments
                if assignment.employee_id is not None
            ]
            assert len(employee_ids) == len(set(employee_ids))


def test_employee_insights_include_restrictions_and_weekly_hours() -> None:
    with create_session() as session:
        seed_db(session)
        fill_day(session, date(2026, 3, 18))

        insights = list_employee_insights(week_start=date(2026, 3, 16), session=session)
        assert len(insights) > 0

        sample = insights[0]
        assert sample.max_weekly_hours >= 0
        assert sample.worked_hours_week >= 0
        assert sample.remaining_hours_week >= 0

        roles_count = session.exec(select(EmployeeRole)).all()
        assert len(roles_count) > 0

        restricted = [item for item in insights if len(item.restrictions) > 0]
        assert len(restricted) > 0


def test_fill_day_with_custom_requirements_for_selected_shift() -> None:
    with create_session() as session:
        seed_db(session)

        role = session.exec(select(Role)).first()
        assert role is not None

        results = fill_day(
            session,
            date(2026, 3, 18),
            reoptimize=True,
            requirements_by_shift={"LUNCH": {role.id: 1}},
            shift_types=["LUNCH"],
        )

        assert set(results.keys()) == {"LUNCH"}

        lunch_shift = session.exec(
            select(Shift)
            .where(Shift.date == date(2026, 3, 18))
            .where(Shift.shift_type == "LUNCH")
        ).first()
        assert lunch_shift is not None

        assignments = session.exec(
            select(Assignment).where(Assignment.shift_id == lunch_shift.id)
        ).all()

        assert len(assignments) <= 1
        assert all(assignment.role_id == role.id for assignment in assignments)
