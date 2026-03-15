import os

import pytest

from app.core.config import settings
from app.models.scheduling import SHIFT_TYPES
from app.services.llm_parser import parse_action_from_message

_ALLOWED_TYPES = {"AUTOFILL_DAY", "SWAP_ASSIGNMENT", "SET_RULE"}


def _require_live_llm() -> None:
    if os.getenv("RUN_LLM_INTEGRATION_TESTS") != "1":
        pytest.skip("Set RUN_LLM_INTEGRATION_TESTS=1 to run live LLM integration tests.")

    if not settings.openai_api_key:
        pytest.skip("OPENAI_API_KEY is not configured.")


@pytest.mark.parametrize(
    "message",
    [
        "Fill 2026-03-19 dinner with reoptimize.",
        "Swap Ana Silva with Joao Mendes on dinner 2026-03-22.",
        "On Monday lunch, role 1 needs 4 people.",
    ],
)
def test_llm_parser_real_openai_varied_nlp_prompts(message: str) -> None:
    _require_live_llm()

    role_context = [
        {"id": 1, "name": "Cook"},
        {"id": 2, "name": "Dishwasher"},
        {"id": 3, "name": "Server"},
        {"id": 4, "name": "Manager"},
    ]

    action = parse_action_from_message(message, role_context)

    assert action.type in _ALLOWED_TYPES
    assert action.type == action.type.upper()

    if action.day_of_week:
        assert action.day_of_week == action.day_of_week.upper()
    if action.shift_type:
        assert action.shift_type in SHIFT_TYPES
