import json
from datetime import date

import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.routes.chat import chat_command
from app.models.scheduling import (
    Assignment,
    ChatCommand,
    Employee,
    Role,
    ScheduleRule,
    Shift,
)
from app.schemas.scheduling import ChatAction, ChatCommandRequest, RoleRequirement
from app.services.llm_parser import LLMParseError
from app.seed.seed_data import seed_db
from app.services.scheduler import fill_day


def create_session() -> Session:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _patch_llm_failure(monkeypatch) -> None:
    def failing_parser(_message: str, _roles: list[dict[str, int | str]]) -> ChatAction:
        raise LLMParseError("LLM unavailable")

    monkeypatch.setattr("app.api.routes.chat.parse_action_from_message", failing_parser)


def _latest_command(session: Session) -> ChatCommand | None:
    return session.exec(select(ChatCommand).order_by(ChatCommand.id.desc())).first()


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


def test_chat_rejects_unsupported_action_type() -> None:
    with create_session() as session:
        seed_db(session)

        payload = ChatCommandRequest(action=ChatAction(type="LIST_SCHEDULE"))

        with pytest.raises(HTTPException) as exc_info:
            chat_command(payload, session)

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "unsupported action type"


def test_chat_rejects_unknown_action_with_friendly_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM returning UNKNOWN (e.g. greeting 'hi') must yield a user-friendly 400."""

    def fake_parser(_message: str, _roles: list[dict[str, int | str]]) -> ChatAction:
        return ChatAction(type="UNKNOWN")

    monkeypatch.setattr("app.api.routes.chat.parse_action_from_message", fake_parser)

    with create_session() as session:
        seed_db(session)
        payload = ChatCommandRequest(message="oi")

        with pytest.raises(HTTPException) as exc_info:
            chat_command(payload, session)

        assert exc_info.value.status_code == 400
        assert "scheduling commands" in exc_info.value.detail.lower()


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


def test_chat_set_rule_weekend_multi_role_without_shift_updates_all_weekend_shifts() -> None:
    with create_session() as session:
        seed_db(session)

        cook = session.exec(select(Role).where(Role.name == "Cook")).first()
        server = session.exec(select(Role).where(Role.name == "Server")).first()
        assert cook is not None
        assert server is not None

        payload = ChatCommandRequest(
            action=ChatAction(
                type="SET_RULE",
                day_of_week="WEEKEND",
                requirements=[
                    RoleRequirement(role_id=cook.id, required_count=3),
                    RoleRequirement(role_id=server.id, required_count=8),
                ],
            )
        )

        response = chat_command(payload, session)

        assert response.status == "APPLIED"
        assert response.action_type == "SET_RULE"
        assert isinstance(response.result, dict)
        assert response.result.get("updated_count") == 8

        for day in ("SATURDAY", "SUNDAY"):
            for shift in ("LUNCH", "DINNER"):
                cook_rule = session.exec(
                    select(ScheduleRule)
                    .where(ScheduleRule.day_of_week == day)
                    .where(ScheduleRule.shift_type == shift)
                    .where(ScheduleRule.role_id == cook.id)
                ).first()
                server_rule = session.exec(
                    select(ScheduleRule)
                    .where(ScheduleRule.day_of_week == day)
                    .where(ScheduleRule.shift_type == shift)
                    .where(ScheduleRule.role_id == server.id)
                ).first()

                assert cook_rule is not None
                assert server_rule is not None
                assert cook_rule.required_count == 3
                assert server_rule.required_count == 8


def test_chat_message_uses_llm_parser(monkeypatch) -> None:
    with create_session() as session:
        seed_db(session)

        def fake_parser(_message: str, _roles: list[dict[str, int | str]]) -> ChatAction:
            return ChatAction(type="AUTOFILL_DAY", date=date(2026, 3, 18))

        monkeypatch.setattr("app.api.routes.chat.parse_action_from_message", fake_parser)

        payload = ChatCommandRequest(message="fill any shift on 2026-03-18")
        response = chat_command(payload, session)

        assert response.status == "APPLIED"
        assert response.action_type == "AUTOFILL_DAY"


def test_chat_message_includes_context_json_with_roles_and_employees(monkeypatch) -> None:
    with create_session() as session:
        seed_db(session)
        captured: dict[str, object] = {}

        def fake_parser(message: str, roles: list[dict[str, int | str]]) -> ChatAction:
            captured["message"] = message
            captured["roles"] = roles
            return ChatAction(type="AUTOFILL_DAY", date=date(2026, 3, 18))

        monkeypatch.setattr("app.api.routes.chat.parse_action_from_message", fake_parser)

        payload = ChatCommandRequest(message="fill any shift on 2026-03-18")
        response = chat_command(payload, session)

        assert response.status == "APPLIED"

        parser_message = captured.get("message")
        assert isinstance(parser_message, str)
        assert "\n\nCONTEXT_JSON:\n" in parser_message

        original_message, context_json = parser_message.split("\n\nCONTEXT_JSON:\n", 1)
        assert original_message == "fill any shift on 2026-03-18"

        context = json.loads(context_json)
        assert isinstance(context.get("roles"), list)
        assert isinstance(context.get("employees"), list)
        assert isinstance(context.get("assignments"), list)
        assert any(item.get("name") == "Ana Silva" for item in context["employees"])


def test_chat_message_context_json_includes_assignments_for_name_resolution(
    monkeypatch,
) -> None:
    with create_session() as session:
        seed_db(session)
        fill_day(session, date(2026, 3, 22), reoptimize=True)
        role = session.exec(select(Role)).first()
        assert role is not None

        captured: dict[str, object] = {}

        def fake_parser(message: str, _roles: list[dict[str, int | str]]) -> ChatAction:
            captured["message"] = message
            return ChatAction(
                type="SET_RULE",
                day_of_week="MONDAY",
                shift_type="LUNCH",
                role_id=role.id,
                required_count=2,
            )

        monkeypatch.setattr("app.api.routes.chat.parse_action_from_message", fake_parser)

        payload = ChatCommandRequest(
            message="remove Ana Silva from dinner on 2026-03-22 and fill the gap"
        )
        response = chat_command(payload, session)

        assert response.status == "APPLIED"
        parser_message = captured.get("message")
        assert isinstance(parser_message, str)

        context = json.loads(parser_message.split("\n\nCONTEXT_JSON:\n", 1)[1])
        assignments = context["assignments"]

        assert isinstance(assignments, list)
        assert len(assignments) > 0
        assert any(item.get("date") == "2026-03-22" for item in assignments)
        assert any(item.get("employee_name") for item in assignments)
        first_assignment = assignments[0]
        assert "assignment_id" in first_assignment
        assert "role_name" in first_assignment
        assert "shift_type" in first_assignment


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


def test_chat_autofill_weekend_scope_fills_two_days() -> None:
    with create_session() as session:
        seed_db(session)

        payload = ChatCommandRequest(
            action=ChatAction(
                type="AUTOFILL_DAY",
                day_of_week="WEEKEND",
            )
        )

        response = chat_command(payload, session)

        assert response.status == "APPLIED"
        assert response.action_type == "AUTOFILL_DAY"
        assert isinstance(response.result, dict)

        date_results = response.result.get("dates")
        assert isinstance(date_results, list)
        assert len(date_results) == 2

        total_created = 0
        for entry in date_results:
            results = entry.get("results", [])
            assert len(results) == 2
            total_created += sum(item.get("created", 0) for item in results)

        assignments = session.exec(select(Assignment)).all()
        assert total_created > 0
        assert len(assignments) >= total_created


def test_chat_message_autofill_with_role_counts_uses_llm_action(monkeypatch) -> None:
    with create_session() as session:
        seed_db(session)

        role = session.exec(select(Role).where(Role.name == "Cook")).first()
        assert role is not None

        def fake_parser(_message: str, _roles: list[dict[str, int | str]]) -> ChatAction:
            return ChatAction(
                type="AUTOFILL_DAY",
                date=date(2026, 3, 18),
                shift_type="DINNER",
                requirements=[RoleRequirement(role_id=role.id, required_count=2)],
            )

        monkeypatch.setattr("app.api.routes.chat.parse_action_from_message", fake_parser)

        payload = ChatCommandRequest(
            message="fill 2026-03-18 with 2 cooks and 1 server for dinner"
        )
        response = chat_command(payload, session)

        assert response.status == "APPLIED"
        assert response.action_type == "AUTOFILL_DAY"
        assert response.result is not None
        assert len(response.result.get("results", [])) == 1


def test_chat_autofill_validation_rejects_weekday_date_mismatch(monkeypatch) -> None:
    with create_session() as session:
        seed_db(session)

        def fake_parser(_message: str, _roles: list[dict[str, int | str]]) -> ChatAction:
            return ChatAction(type="AUTOFILL_DAY", date=date(2026, 3, 14))

        monkeypatch.setattr("app.api.routes.chat.parse_action_from_message", fake_parser)

        payload = ChatCommandRequest(message="fill monday")
        with pytest.raises(HTTPException) as exc_info:
            chat_command(payload, session)

        assert exc_info.value.status_code == 400
        assert "does not match day mentioned" in exc_info.value.detail


def test_chat_message_remove_employee_from_shift_uses_llm_action(monkeypatch) -> None:
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

        def fake_parser(_message: str, _roles: list[dict[str, int | str]]) -> ChatAction:
            return ChatAction(type="SWAP_ASSIGNMENT", assignment_id=assignment.id)

        monkeypatch.setattr("app.api.routes.chat.parse_action_from_message", fake_parser)

        payload = ChatCommandRequest(
            message=f"remove {employee.name} from dinner on 22-3-2026"
        )
        response = chat_command(payload, session)

        assert response.status == "APPLIED"
        assert response.action_type == "SWAP_ASSIGNMENT"
        assert response.result is not None
        assert response.result.get("date") == "2026-03-22"
        assert response.result.get("shift_type") == "DINNER"
        assert response.result.get("old_employee_id") == employee.id


def test_chat_message_add_employee_to_shift_uses_llm_action(monkeypatch) -> None:
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
        assert employee.id is not None

        assignment.employee_id = None
        session.add(assignment)
        session.commit()

        def fake_parser(_message: str, _roles: list[dict[str, int | str]]) -> ChatAction:
            return ChatAction(
                type="SWAP_ASSIGNMENT",
                assignment_id=assignment.id,
                replacement_employee_id=employee.id,
            )

        monkeypatch.setattr("app.api.routes.chat.parse_action_from_message", fake_parser)

        payload = ChatCommandRequest(
            message=f"add {employee.name} to dinner on 2026-03-22"
        )
        response = chat_command(payload, session)

        assert response.status == "APPLIED"
        assert response.action_type == "SWAP_ASSIGNMENT"
        assert response.result is not None
        assert response.result.get("date") == "2026-03-22"
        assert response.result.get("shift_type") == "DINNER"
        assert response.result.get("new_employee_id") == employee.id


def test_chat_swap_validation_rejects_assignment_employee_mismatch(monkeypatch) -> None:
    with create_session() as session:
        seed_db(session)
        fill_day(session, date(2026, 3, 22), reoptimize=True)

        rows = session.exec(
            select(Assignment, Employee)
            .join(Shift, Assignment.shift_id == Shift.id)
            .join(Employee, Assignment.employee_id == Employee.id)
            .where(Shift.date == date(2026, 3, 22))
            .where(Shift.shift_type == "DINNER")
        ).all()
        assert len(rows) >= 2
        (wrong_assignment, _), (_, referenced_employee) = rows[0], rows[1]
        assert wrong_assignment.id is not None

        def fake_parser(_message: str, _roles: list[dict[str, int | str]]) -> ChatAction:
            return ChatAction(type="SWAP_ASSIGNMENT", assignment_id=wrong_assignment.id)

        monkeypatch.setattr("app.api.routes.chat.parse_action_from_message", fake_parser)

        payload = ChatCommandRequest(
            message=f"remove {referenced_employee.name} from dinner on 2026-03-22"
        )
        with pytest.raises(HTTPException) as exc_info:
            chat_command(payload, session)

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "assignment_id does not match employee mentioned in message"


def test_chat_swap_validation_rejects_assignment_shift_mismatch(monkeypatch) -> None:
    with create_session() as session:
        seed_db(session)
        fill_day(session, date(2026, 3, 22), reoptimize=True)

        lunch_candidate = session.exec(
            select(Assignment, Employee)
            .join(Shift, Assignment.shift_id == Shift.id)
            .join(Employee, Assignment.employee_id == Employee.id)
            .where(Shift.date == date(2026, 3, 22))
            .where(Shift.shift_type == "LUNCH")
        ).first()
        assert lunch_candidate is not None
        lunch_assignment, lunch_employee = lunch_candidate
        assert lunch_assignment.id is not None

        def fake_parser(_message: str, _roles: list[dict[str, int | str]]) -> ChatAction:
            return ChatAction(type="SWAP_ASSIGNMENT", assignment_id=lunch_assignment.id)

        monkeypatch.setattr("app.api.routes.chat.parse_action_from_message", fake_parser)

        payload = ChatCommandRequest(
            message=f"remove {lunch_employee.name} from dinner on 2026-03-22"
        )
        with pytest.raises(HTTPException) as exc_info:
            chat_command(payload, session)

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "assignment_id does not match shift mentioned in message"


def test_chat_swap_validation_rejects_replacement_employee_mismatch(monkeypatch) -> None:
    with create_session() as session:
        seed_db(session)
        fill_day(session, date(2026, 3, 22), reoptimize=True)

        target = session.exec(
            select(Assignment, Employee)
            .join(Shift, Assignment.shift_id == Shift.id)
            .join(Employee, Assignment.employee_id == Employee.id)
            .where(Shift.date == date(2026, 3, 22))
            .where(Shift.shift_type == "DINNER")
        ).first()
        replacement = session.exec(
            select(Employee).where(Employee.name == "Joao Mendes")
        ).first()
        mentioned = session.exec(
            select(Employee).where(Employee.name == "Ana Silva")
        ).first()
        assert target is not None
        assert replacement is not None
        assert mentioned is not None
        assignment, _ = target
        assert assignment.id is not None
        assert replacement.id is not None
        assert mentioned.id is not None

        assignment.employee_id = None
        session.add(assignment)
        session.commit()

        def fake_parser(_message: str, _roles: list[dict[str, int | str]]) -> ChatAction:
            return ChatAction(
                type="SWAP_ASSIGNMENT",
                assignment_id=assignment.id,
                replacement_employee_id=replacement.id,
            )

        monkeypatch.setattr("app.api.routes.chat.parse_action_from_message", fake_parser)

        payload = ChatCommandRequest(
            message=f"add {mentioned.name} to dinner on 2026-03-22"
        )
        with pytest.raises(HTTPException) as exc_info:
            chat_command(payload, session)

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "replacement_employee_id does not match employee mentioned in message"


def test_chat_swap_validation_rejects_unknown_replacement_name(monkeypatch) -> None:
    with create_session() as session:
        seed_db(session)
        fill_day(session, date(2026, 3, 22), reoptimize=True)

        target = session.exec(
            select(Assignment, Employee)
            .join(Shift, Assignment.shift_id == Shift.id)
            .join(Employee, Assignment.employee_id == Employee.id)
            .where(Shift.date == date(2026, 3, 22))
            .where(Shift.shift_type == "DINNER")
        ).first()
        replacement = session.exec(
            select(Employee).where(Employee.name == "Joao Mendes")
        ).first()
        assert target is not None
        assert replacement is not None
        assignment, current_employee = target
        assert assignment.id is not None
        assert replacement.id is not None

        def fake_parser(_message: str, _roles: list[dict[str, int | str]]) -> ChatAction:
            return ChatAction(
                type="SWAP_ASSIGNMENT",
                assignment_id=assignment.id,
                replacement_employee_id=replacement.id,
            )

        monkeypatch.setattr("app.api.routes.chat.parse_action_from_message", fake_parser)

        payload = ChatCommandRequest(
            message=f"replace {current_employee.name} with Carla Mendes on dinner 2026-03-22"
        )
        with pytest.raises(HTTPException) as exc_info:
            chat_command(payload, session)

        assert exc_info.value.status_code == 400
        assert (
            exc_info.value.detail
            == "replacement employee mentioned in message was not found in context"
        )


def test_chat_command_returns_400_when_swap_assignment_id_missing(monkeypatch) -> None:
    with create_session() as session:
        seed_db(session)

        def fake_parser(_message: str, _roles: list[dict[str, int | str]]) -> ChatAction:
            return ChatAction(type="SWAP_ASSIGNMENT", replacement_employee_id=None)

        monkeypatch.setattr("app.api.routes.chat.parse_action_from_message", fake_parser)

        payload = ChatCommandRequest(message="remove someone from dinner on 2026-03-22")
        with pytest.raises(HTTPException) as exc_info:
            chat_command(payload, session)

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "assignment_id is required for SWAP_ASSIGNMENT"


def test_chat_add_message_returns_400_when_replacement_missing(monkeypatch) -> None:
    with create_session() as session:
        seed_db(session)
        fill_day(session, date(2026, 3, 22), reoptimize=True)

        target = session.exec(
            select(Assignment, Employee)
            .join(Shift, Assignment.shift_id == Shift.id)
            .join(Employee, Assignment.employee_id == Employee.id)
            .where(Shift.date == date(2026, 3, 22))
            .where(Shift.shift_type == "DINNER")
        ).first()
        assert target is not None
        target_assignment, target_employee = target
        assert target_assignment.id is not None
        assert target_employee.id is not None

        def fake_parser(_message: str, _roles: list[dict[str, int | str]]) -> ChatAction:
            return ChatAction(
                type="SWAP_ASSIGNMENT",
                assignment_id=target_assignment.id,
                replacement_employee_id=None,
            )

        monkeypatch.setattr("app.api.routes.chat.parse_action_from_message", fake_parser)

        payload = ChatCommandRequest(
            message=f"add {target_employee.name} to dinner on 2026-03-22"
        )
        with pytest.raises(HTTPException) as exc_info:
            chat_command(payload, session)

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "replacement_employee_id is required for add/assign intents"


def test_chat_replace_without_with_allows_remove_flow(monkeypatch) -> None:
    with create_session() as session:
        seed_db(session)
        fill_day(session, date(2026, 3, 22), reoptimize=True)

        target = session.exec(
            select(Assignment, Employee)
            .join(Shift, Assignment.shift_id == Shift.id)
            .join(Employee, Assignment.employee_id == Employee.id)
            .where(Shift.date == date(2026, 3, 22))
            .where(Shift.shift_type == "LUNCH")
        ).first()
        assert target is not None
        target_assignment, target_employee = target
        assert target_assignment.id is not None

        def fake_parser(_message: str, _roles: list[dict[str, int | str]]) -> ChatAction:
            return ChatAction(
                type="SWAP_ASSIGNMENT",
                assignment_id=target_assignment.id,
                replacement_employee_id=None,
            )

        monkeypatch.setattr("app.api.routes.chat.parse_action_from_message", fake_parser)

        payload = ChatCommandRequest(
            message=f"replace {target_employee.name} for lunch on 2026-03-22"
        )
        response = chat_command(payload, session)

        assert response.status == "APPLIED"
        assert response.action_type == "SWAP_ASSIGNMENT"


def test_chat_swap_from_phrase_allows_remove_flow(monkeypatch) -> None:
    with create_session() as session:
        seed_db(session)
        fill_day(session, date(2026, 3, 22), reoptimize=True)

        target = session.exec(
            select(Assignment, Employee)
            .join(Shift, Assignment.shift_id == Shift.id)
            .join(Employee, Assignment.employee_id == Employee.id)
            .where(Shift.date == date(2026, 3, 22))
            .where(Shift.shift_type == "LUNCH")
        ).first()
        assert target is not None
        target_assignment, target_employee = target
        assert target_assignment.id is not None

        def fake_parser(_message: str, _roles: list[dict[str, int | str]]) -> ChatAction:
            return ChatAction(
                type="SWAP_ASSIGNMENT",
                assignment_id=target_assignment.id,
                replacement_employee_id=None,
            )

        monkeypatch.setattr("app.api.routes.chat.parse_action_from_message", fake_parser)

        payload = ChatCommandRequest(
            message=f"swap {target_employee.name} from lunch on 2026-03-22"
        )
        response = chat_command(payload, session)

        assert response.status == "APPLIED"
        assert response.action_type == "SWAP_ASSIGNMENT"


def test_chat_swap_with_phrase_requires_replacement(monkeypatch) -> None:
    with create_session() as session:
        seed_db(session)
        fill_day(session, date(2026, 3, 22), reoptimize=True)

        rows = session.exec(
            select(Assignment, Employee)
            .join(Shift, Assignment.shift_id == Shift.id)
            .join(Employee, Assignment.employee_id == Employee.id)
            .where(Shift.date == date(2026, 3, 22))
            .where(Shift.shift_type == "DINNER")
        ).all()
        assert len(rows) >= 2
        (target_assignment, target_employee), (_, replacement_employee) = rows[0], rows[1]
        assert target_assignment.id is not None

        def fake_parser(_message: str, _roles: list[dict[str, int | str]]) -> ChatAction:
            return ChatAction(
                type="SWAP_ASSIGNMENT",
                assignment_id=target_assignment.id,
                replacement_employee_id=None,
            )

        monkeypatch.setattr("app.api.routes.chat.parse_action_from_message", fake_parser)

        payload = ChatCommandRequest(
            message=(
                f"swap {target_employee.name} with {replacement_employee.name} "
                "on dinner 2026-03-22"
            )
        )
        with pytest.raises(HTTPException) as exc_info:
            chat_command(payload, session)

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "replacement_employee_id is required for add/assign intents"


def test_chat_swap_from_phrase_auto_selects_replacement_when_available(monkeypatch) -> None:
    with create_session() as session:
        seed_db(session)

        cook = session.exec(select(Role).where(Role.name == "Cook")).first()
        assert cook is not None

        fill_day(
            session,
            date(2026, 3, 18),
            reoptimize=True,
            requirements_by_shift={"LUNCH": {cook.id: 1}},
            shift_types=["LUNCH"],
        )

        target = session.exec(
            select(Assignment, Employee)
            .join(Shift, Assignment.shift_id == Shift.id)
            .join(Employee, Assignment.employee_id == Employee.id)
            .where(Shift.date == date(2026, 3, 18))
            .where(Shift.shift_type == "LUNCH")
            .where(Assignment.role_id == cook.id)
        ).first()
        assert target is not None
        target_assignment, target_employee = target
        assert target_assignment.id is not None
        assert target_employee.id is not None

        def fake_parser(_message: str, _roles: list[dict[str, int | str]]) -> ChatAction:
            return ChatAction(
                type="SWAP_ASSIGNMENT",
                assignment_id=target_assignment.id,
                replacement_employee_id=None,
            )

        monkeypatch.setattr("app.api.routes.chat.parse_action_from_message", fake_parser)

        payload = ChatCommandRequest(
            message=f"swap {target_employee.name} from lunch on 2026-03-18"
        )
        response = chat_command(payload, session)

        assert response.status == "APPLIED"
        assert response.action_type == "SWAP_ASSIGNMENT"
        assert response.result is not None
        assert response.result.get("old_employee_id") == target_employee.id
        assert response.result.get("new_employee_id") is not None
        assert response.result.get("new_employee_id") != target_employee.id


def test_chat_command_returns_400_when_llm_unavailable_and_no_local_match(monkeypatch) -> None:
    with create_session() as session:
        seed_db(session)
        _patch_llm_failure(monkeypatch)

        payload = ChatCommandRequest(message="show assignments for next payroll period")
        with pytest.raises(HTTPException) as exc_info:
            chat_command(payload, session)

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "LLM unavailable"


def test_chat_message_swap_returns_400_when_assignment_not_found(monkeypatch) -> None:
    with create_session() as session:
        seed_db(session)

        def fake_parser(_message: str, _roles: list[dict[str, int | str]]) -> ChatAction:
            return ChatAction(type="SWAP_ASSIGNMENT", assignment_id=9999)

        monkeypatch.setattr("app.api.routes.chat.parse_action_from_message", fake_parser)

        payload = ChatCommandRequest(
            message="remove anyone from dinner on 2099-01-01"
        )
        with pytest.raises(HTTPException) as exc_info:
            chat_command(payload, session)

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "assignment not found"


@pytest.mark.parametrize(
    "requirements,expected_detail",
    [
        ([RoleRequirement(role_id=1, required_count=-1)], "required_count must be >= 0"),
        ([RoleRequirement(role_id=9999, required_count=1)], "role not found: 9999"),
        (
            [RoleRequirement(role_id=1, required_count=0)],
            "requirements must include at least one item with required_count > 0",
        ),
    ],
)
def test_chat_autofill_rejects_invalid_requirements(
    requirements: list[RoleRequirement],
    expected_detail: str,
) -> None:
    with create_session() as session:
        seed_db(session)

        payload = ChatCommandRequest(
            action=ChatAction(
                type="AUTOFILL_DAY",
                date=date(2026, 3, 18),
                requirements=requirements,
            )
        )

        with pytest.raises(HTTPException) as exc_info:
            chat_command(payload, session)

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == expected_detail

        command = _latest_command(session)
        assert command is not None
        assert command.status == "FAILED"


def test_chat_swap_assignment_not_found_marks_command_failed() -> None:
    with create_session() as session:
        seed_db(session)

        payload = ChatCommandRequest(
            action=ChatAction(type="SWAP_ASSIGNMENT", assignment_id=9999)
        )

        with pytest.raises(HTTPException) as exc_info:
            chat_command(payload, session)

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "assignment not found"

        command = _latest_command(session)
        assert command is not None
        assert command.status == "FAILED"


def test_chat_command_persists_applied_status() -> None:
    with create_session() as session:
        seed_db(session)

        payload = ChatCommandRequest(
            action=ChatAction(type="AUTOFILL_DAY", date=date(2026, 3, 18))
        )
        response = chat_command(payload, session)

        assert response.status == "APPLIED"

        command = _latest_command(session)
        assert command is not None
        assert command.status == "APPLIED"
