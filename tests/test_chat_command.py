from datetime import date

from sqlmodel import Session, SQLModel, create_engine, select

from app.api.routes.chat import chat_command, chat_preview
from app.models.scheduling import Assignment, Employee, Role, ScheduleRule, Shift
from app.schemas.scheduling import ChatAction, ChatCommandRequest, RoleRequirement
from app.services.llm_parser import LLMParseError
from app.seed.seed_data import seed_db
from app.services.scheduler import fill_day


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


def test_chat_message_uses_llm_parser(monkeypatch) -> None:
    with create_session() as session:
        seed_db(session)

        def fake_parser(_message: str, _roles: list[dict[str, int | str]]) -> ChatAction:
            return ChatAction(
                type="LIST_SCHEDULE",
                start_date=date(2026, 3, 18),
                end_date=date(2026, 3, 18),
            )

        monkeypatch.setattr("app.api.routes.chat.parse_action_from_message", fake_parser)

        payload = ChatCommandRequest(message="show me march 18 schedule")
        response = chat_command(payload, session)

        assert response.status == "APPLIED"
        assert response.action_type == "LIST_SCHEDULE"


def test_chat_preview_autofill_estimates_impact() -> None:
    with create_session() as session:
        seed_db(session)

        payload = ChatCommandRequest(
            message="preview fill",
            action=ChatAction(type="AUTOFILL_DAY", date=date(2026, 3, 18)),
        )
        response = chat_preview(payload, session)

        assert response.status == "PREVIEW"
        assert response.action_type == "AUTOFILL_DAY"
        assert response.impact.assignments >= 0
        assert response.impact.shifts >= 0
        assert response.impact.people >= 0
        assert "Confirm execution" in response.preview_message


def test_chat_preview_message_uses_llm_parser(monkeypatch) -> None:
    with create_session() as session:
        seed_db(session)

        def fake_parser(_message: str, _roles: list[dict[str, int | str]]) -> ChatAction:
            return ChatAction(
                type="LIST_SCHEDULE",
                start_date=date(2026, 3, 18),
                end_date=date(2026, 3, 18),
            )

        monkeypatch.setattr("app.api.routes.chat.parse_action_from_message", fake_parser)

        payload = ChatCommandRequest(message="show schedule first")
        response = chat_preview(payload, session)

        assert response.status == "PREVIEW"
        assert response.action_type == "LIST_SCHEDULE"
        assert response.impact.shifts == 0
        assert response.impact.people == 0


def test_chat_autofill_day_with_custom_role_requirements() -> None:
    with create_session() as session:
        seed_db(session)
        role = session.exec(select(Role)).first()
        assert role is not None

        payload = ChatCommandRequest(
            action=ChatAction(
                type="AUTOFILL_DAY",
                date=date(2026, 3, 18),
                shift_type="LUNCH",
                requirements=[
                    RoleRequirement(role_id=role.id, required_count=1),
                ],
            )
        )
        response = chat_command(payload, session)

        assert response.status == "APPLIED"
        assert response.action_type == "AUTOFILL_DAY"
        assert response.result is not None
        assert len(response.result.get("results", [])) == 1
        assert response.result.get("results", [])[0]["shift_type"] == "LUNCH"


def test_chat_message_autofill_with_role_counts_without_llm(monkeypatch) -> None:
    with create_session() as session:
        seed_db(session)

        def failing_parser(_message: str, _roles: list[dict[str, int | str]]) -> ChatAction:
            raise LLMParseError("LLM unavailable")

        monkeypatch.setattr("app.api.routes.chat.parse_action_from_message", failing_parser)

        payload = ChatCommandRequest(
            message="preencher 2026-03-18 com 2 cozinheiros e 1 garcom no jantar"
        )
        response = chat_command(payload, session)

        assert response.status == "APPLIED"
        assert response.action_type == "AUTOFILL_DAY"
        assert response.result is not None
        assert len(response.result.get("results", [])) == 1
        assert response.result.get("results", [])[0]["shift_type"] == "DINNER"


def test_chat_message_remove_employee_from_shift_without_llm(monkeypatch) -> None:
    with create_session() as session:
        seed_db(session)
        fill_day(session, date(2026, 3, 22), reoptimize=True)

        candidate = session.exec(
            select(Assignment, Employee)
            .join(Shift, Assignment.shift_id == Shift.id)
            .join(Employee, Assignment.employee_id == Employee.id)
            .where(Shift.date == date(2026, 3, 22))
            .where(Shift.shift_type == "DINNER")
        ).first()
        assert candidate is not None
        assignment, employee = candidate
        assert assignment.id is not None

        def failing_parser(_message: str, _roles: list[dict[str, int | str]]) -> ChatAction:
            raise LLMParseError("LLM unavailable")

        monkeypatch.setattr("app.api.routes.chat.parse_action_from_message", failing_parser)

        payload = ChatCommandRequest(
            message=f"remover {employee.name} da janta do dia 22-3-2026"
        )
        response = chat_command(payload, session)

        assert response.status == "APPLIED"
        assert response.action_type == "SWAP_ASSIGNMENT"
        assert response.result is not None
        assert response.result.get("date") == "2026-03-22"
        assert response.result.get("shift_type") == "DINNER"
        assert response.result.get("old_employee_id") == employee.id
