from datetime import date

from sqlmodel import Session, SQLModel, create_engine, select

from app.models.scheduling import (
    Assignment,
    Availability,
    Employee,
    Role,
    ScheduleRule,
    Shift,
)
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
