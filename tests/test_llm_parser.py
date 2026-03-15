from typing import get_args
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.schemas.scheduling import ChatAction
from app.services.llm_parser import (
    DayOfWeekValue,
    IntentPayload,
    IntentType,
    LLMParseError,
    parse_action_from_message,
)


def _patch_fake_model(
    monkeypatch: pytest.MonkeyPatch,
    *,
    structured_invoke_impl=None,
    invoke_impl=None,
) -> dict:
    captured: dict = {}

    class FakeStructuredModel:
        def invoke(self, messages):
            captured["structured_messages"] = messages
            if structured_invoke_impl is None:
                return {}
            return structured_invoke_impl(messages)

    class FakeModel:
        def with_structured_output(self, schema):
            captured["schema"] = schema
            return FakeStructuredModel()

        def invoke(self, messages):
            captured["messages"] = messages
            if invoke_impl is None:
                return SimpleNamespace(content="")
            return invoke_impl(messages)

    monkeypatch.setattr(
        "app.services.llm_parser._get_openai_client",
        lambda: FakeModel(),
    )

    return captured


def test_intent_payload_schema_has_one_required_key() -> None:
    assert IntentPayload.__required_keys__ == {"type"}
    assert "date" in IntentPayload.__optional_keys__
    assert "assignment_id" in IntentPayload.__optional_keys__
    assert "requirements" in IntentPayload.__optional_keys__
    assert "start_date" not in IntentPayload.__optional_keys__
    assert "end_date" not in IntentPayload.__optional_keys__


@pytest.mark.parametrize(
    "message,payload,expected_type",
    [
        (
            "Fill 2026-03-19 with 2 cooks for dinner and reoptimize",
            {
                "type": "autofill_day",
                "date": "2026-03-19",
                "reoptimize": True,
                "shift_type": "dinner",
                "requirements": [{"role_id": 1, "required_count": 2}],
            },
            "AUTOFILL_DAY",
        ),
        (
            "Fill any shift on 2026-03-22",
            {
                "type": "autofill_day",
                "date": "2026-03-22",
            },
            "AUTOFILL_DAY",
        ),
        (
            "Fill one server for lunch on 2026-03-22",
            {
                "type": "autofill_day",
                "date": "2026-03-22",
                "shift_type": "lunch",
                "requirements": [{"role_id": 3, "required_count": 1}],
            },
            "AUTOFILL_DAY",
        ),
        (
            "Swap Ana Silva with Joao Mendes on dinner 2026-03-22",
            {
                "type": "swap_assignment",
                "assignment_id": 17,
                "replacement_employee_id": 3,
            },
            "SWAP_ASSIGNMENT",
        ),
        (
            "Remove Ana Silva from dinner on 2026-03-22 and fill the gap",
            {
                "type": "swap_assignment",
                "assignment_id": 17,
                "replacement_employee_id": None,
            },
            "SWAP_ASSIGNMENT",
        ),
        (
            "On Monday lunch we need 4 cooks",
            {
                "type": "set_rule",
                "day_of_week": "monday",
                "shift_type": "lunch",
                "role_id": 1,
                "required_count": 4,
            },
            "SET_RULE",
        ),
    ],
)
def test_parse_action_from_message_supports_varied_nlp_texts(
    monkeypatch: pytest.MonkeyPatch,
    message: str,
    payload: dict,
    expected_type: str,
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_model", "gpt-4o-mini")

    captured: dict = {}

    captured = _patch_fake_model(
        monkeypatch,
        structured_invoke_impl=lambda _messages: payload,
    )

    action = parse_action_from_message(message, [{"id": 1, "name": "Cook"}])

    assert action.type == expected_type
    assert captured["structured_messages"][1] == ("human", message)

    if payload.get("shift_type"):
        assert action.shift_type == payload["shift_type"].upper()
    if payload.get("day_of_week"):
        assert action.day_of_week == payload["day_of_week"].upper()


def test_parse_action_from_message_requires_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", None)

    with pytest.raises(LLMParseError, match="OPENAI_API_KEY is not configured"):
        parse_action_from_message("fill tomorrow", [{"id": 1, "name": "Cook"}])


def test_parse_action_from_message_handles_openai_request_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    def structured_invoke_impl(_messages):
        raise RuntimeError("network down")

    _patch_fake_model(monkeypatch, structured_invoke_impl=structured_invoke_impl)

    with pytest.raises(LLMParseError, match="OpenAI request failed"):
        parse_action_from_message("fill tomorrow", [{"id": 1, "name": "Cook"}])


def test_parse_action_from_message_handles_empty_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    _patch_fake_model(monkeypatch, structured_invoke_impl=lambda _messages: {})

    with pytest.raises(LLMParseError, match="empty structured payload"):
        parse_action_from_message("fill tomorrow", [{"id": 1, "name": "Cook"}])


def test_parse_action_from_message_handles_invalid_structured_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    _patch_fake_model(monkeypatch, structured_invoke_impl=lambda _messages: "not-json")

    with pytest.raises(LLMParseError, match="empty structured payload"):
        parse_action_from_message("fill tomorrow", [{"id": 1, "name": "Cook"}])


def test_parse_action_from_message_handles_schema_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    _patch_fake_model(
        monkeypatch,
        structured_invoke_impl=lambda _messages: {"date": "2026-03-19"},
    )

    with pytest.raises(LLMParseError, match="action validation failed"):
        parse_action_from_message("fill tomorrow", [{"id": 1, "name": "Cook"}])


def test_intent_type_allows_only_three_actions() -> None:
    allowed = set(get_args(IntentType))

    assert "AUTOFILL_DAY" in allowed
    assert "SWAP_ASSIGNMENT" in allowed
    assert "SET_RULE" in allowed
    assert "UNKNOWN" in allowed
    assert "autofill_day" in allowed
    assert "swap_assignment" in allowed
    assert "set_rule" in allowed
    assert "unknown" in allowed
    assert "LIST_SCHEDULE" not in allowed
    assert "list_schedule" not in allowed


def test_day_of_week_literal_supports_scoped_values() -> None:
    allowed = set(get_args(DayOfWeekValue))

    assert "WEEKEND" in allowed
    assert "WEEKENDS" in allowed
    assert "WEEKDAY" in allowed
    assert "WEEKDAYS" in allowed
    assert "weekend" in allowed
    assert "weekdays" in allowed


def test_parse_action_from_message_prompt_enforces_name_resolution_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    captured = _patch_fake_model(
        monkeypatch,
        structured_invoke_impl=lambda _messages: {
            "type": "swap_assignment",
            "assignment_id": 17,
            "replacement_employee_id": 3,
        },
    )

    parse_action_from_message(
        "Swap Ana Silva with Joao Mendes on dinner 2026-03-22",
        [{"id": 1, "name": "Cook"}],
    )

    system_prompt = captured["structured_messages"][0][1]
    assert "Users will normally refer to employee names, not ids" in system_prompt
    assert "Resolve names to ids using CONTEXT_JSON" in system_prompt
    assert "find the matching assignment in CONTEXT_JSON and output its assignment_id" in system_prompt


