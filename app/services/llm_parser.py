from __future__ import annotations

import json

from app.core.config import settings
from app.models.scheduling import DAYS_OF_WEEK, SHIFT_TYPES
from app.schemas.scheduling import ChatAction


class LLMParseError(ValueError):
    pass


def _build_system_prompt(role_context: list[dict[str, int | str]]) -> str:
    role_lines = "\n".join(
        f"- id={item['id']}, name={item['name']}" for item in role_context
    )

    return (
        "You are an intent parser for a restaurant scheduling application. "
        "Return a single JSON object only, with no markdown.\n"
        "Allowed action types: AUTOFILL_DAY, LIST_SCHEDULE, SWAP_ASSIGNMENT, SET_RULE.\n"
        "For AUTOFILL_DAY include: type, date (YYYY-MM-DD), optional reoptimize (boolean), "
        "optional shift_type, and optional requirements as array of {role_id, required_count}.\n"
        "For LIST_SCHEDULE include: type, start_date, end_date (YYYY-MM-DD).\n"
        "For SWAP_ASSIGNMENT include: type, assignment_id, replacement_employee_id (or null).\n"
        "For SET_RULE include: type, day_of_week, shift_type, role_id, required_count.\n"
        f"Valid day_of_week: {', '.join(DAYS_OF_WEEK)}.\n"
        f"Valid shift_type: {', '.join(SHIFT_TYPES)}.\n"
        "Available role ids:\n"
        f"{role_lines if role_lines else '- no roles found'}\n"
        "If input is ambiguous, infer the most likely action and keep values conservative."
    )


def parse_action_from_message(
    message: str,
    role_context: list[dict[str, int | str]],
) -> ChatAction:
    if not settings.openai_api_key:
        raise LLMParseError("OPENAI_API_KEY is not configured.")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise LLMParseError("OpenAI SDK is not installed.") from exc

    client = OpenAI(api_key=settings.openai_api_key)

    try:
        response = client.chat.completions.create(
            model=settings.openai_model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _build_system_prompt(role_context)},
                {"role": "user", "content": message},
            ],
        )
    except Exception as exc:  # noqa: BLE001
        raise LLMParseError(f"OpenAI request failed: {exc}") from exc

    content = response.choices[0].message.content if response.choices else None
    if not content:
        raise LLMParseError("OpenAI returned an empty response.")

    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMParseError("OpenAI response is not valid JSON.") from exc

    try:
        action = ChatAction.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        raise LLMParseError(f"OpenAI action validation failed: {exc}") from exc

    action.type = action.type.upper()
    if action.day_of_week:
        action.day_of_week = action.day_of_week.upper()
    if action.shift_type:
        action.shift_type = action.shift_type.upper()

    return action
