from datetime import date

from sqlmodel import Session, SQLModel, create_engine, select

from app.api.routes.chat import chat_command
from app.models.scheduling import Role, ScheduleRule
from app.schemas.scheduling import ChatAction, ChatCommandRequest
from app.seed.seed_data import seed_db


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_chat_autofill_day() -> None:
    with create_session() as session:
        seed_db(session)
        payload = ChatCommandRequest(
            message="fill wednesday",
            action=ChatAction(type="AUTOFILL_DAY", date=date(2026, 3, 18)),
        )

        response = chat_command(payload, session)

        assert response.status == "APPLIED"
        assert response.action_type == "AUTOFILL_DAY"
        assert response.result is not None
        assert response.result.get("date") == "2026-03-18"
        assert len(response.result.get("results", [])) == 2


def test_chat_list_schedule() -> None:
    with create_session() as session:
        seed_db(session)
        autofill_payload = ChatCommandRequest(
            action=ChatAction(type="AUTOFILL_DAY", date=date(2026, 3, 18))
        )
        chat_command(autofill_payload, session)

        list_payload = ChatCommandRequest(
            action=ChatAction(
                type="LIST_SCHEDULE",
                start_date=date(2026, 3, 18),
                end_date=date(2026, 3, 18),
            )
        )
        response = chat_command(list_payload, session)

        assert response.status == "APPLIED"
        assert response.action_type == "LIST_SCHEDULE"
        assert isinstance(response.result, list)
        assert len(response.result) == 2


def test_chat_set_rule_updates_rule() -> None:
    with create_session() as session:
        seed_db(session)
        role = session.exec(select(Role)).first()
        assert role is not None

        payload = ChatCommandRequest(
            action=ChatAction(
                type="SET_RULE",
                day_of_week="MONDAY",
                shift_type="LUNCH",
                role_id=role.id,
                required_count=5,
            )
        )
        response = chat_command(payload, session)

        assert response.status == "APPLIED"
        assert response.action_type == "SET_RULE"

        rule = session.exec(
            select(ScheduleRule)
            .where(ScheduleRule.day_of_week == "MONDAY")
            .where(ScheduleRule.shift_type == "LUNCH")
            .where(ScheduleRule.role_id == role.id)
        ).first()
        assert rule is not None
        assert rule.required_count == 5
