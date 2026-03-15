"""LLM-backed intent parsing for chat messages.

This module converts natural-language user messages into validated
`ChatAction` objects by calling the LLM with structured output and a
TypedDict schema, then normalizes key enum fields.
"""

from typing import Literal

from typing_extensions import TypedDict

from app.core.config import settings
from app.models.scheduling import DAYS_OF_WEEK, SHIFT_TYPES
from app.schemas.scheduling import ChatAction


class LLMParseError(ValueError):
    """Raised when any step of LLM parsing fails."""

    pass


IntentType = Literal[
    "AUTOFILL_DAY",
    "SWAP_ASSIGNMENT",
    "SET_RULE",
    "UNKNOWN",
    "autofill_day",
    "swap_assignment",
    "set_rule",
    "unknown",
]

ShiftTypeValue = Literal["LUNCH", "DINNER", "lunch", "dinner"]

DayOfWeekValue = Literal[
    "MONDAY",
    "TUESDAY",
    "WEDNESDAY",
    "THURSDAY",
    "FRIDAY",
    "SATURDAY",
    "SUNDAY",
    "WEEKEND",
    "WEEKENDS",
    "WEEKDAY",
    "WEEKDAYS",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "weekend",
    "weekends",
    "weekday",
    "weekdays",
]


class RoleRequirementPayload(TypedDict):
    role_id: int
    required_count: int


class IntentPayloadOptional(TypedDict, total=False):
    date: str
    reoptimize: bool
    assignment_id: int | None
    replacement_employee_id: int | None
    day_of_week: DayOfWeekValue
    shift_type: ShiftTypeValue
    role_id: int
    required_count: int
    requirements: list[RoleRequirementPayload]


class IntentPayload(IntentPayloadOptional):
    type: IntentType


def _build_system_prompt(role_context: list[dict[str, int | str]]) -> str:
    """Build the system prompt including allowed actions and known roles."""

    role_lines = "\n".join(
        f"- id={item['id']}, name={item['name']}" for item in role_context
    )

    return (
        "You are an intent parser for a restaurant scheduling application. "
        "Return one valid JSON object only, with no markdown and no extra text.\n"
        "The user message may include a CONTEXT_JSON block with employees and assignments. "
        "Use that context to resolve concrete ids.\n"
        "CONTEXT_JSON may include a 'today' ISO date. "
        "If user provides only a weekday name (e.g., monday), convert it to the nearest upcoming matching date from today and output it in date.\n"
        "Allowed action types for this product are only: SET_RULE, AUTOFILL_DAY, SWAP_ASSIGNMENT.\n"
        "Do not output LIST_SCHEDULE.\n"
        "Task 1 - Define schedule demand: use SET_RULE with day_of_week and role demand. "
        "For one role use role_id + required_count. "
        "For multiple roles use requirements=[{role_id, required_count}, ...]. "
        "If user says weekend/weekends, set day_of_week='WEEKEND'. "
        "If shift is not specified, omit shift_type so backend applies both LUNCH and DINNER.\n"
        "Task 2 - Fill schedule: use AUTOFILL_DAY with date. "
        "If the request targets one shift, include shift_type. "
        "If the request targets one or more roles, include requirements as [{role_id, required_count}]. "
        "If user asks for weekend/weekends fill, set day_of_week='WEEKEND' and omit date so backend fills Saturday and Sunday. "
        "Use reoptimize=true only when user explicitly asks to rebalance/reoptimize.\n"
        "Users will normally refer to employee names, not ids. Resolve names to ids using CONTEXT_JSON.\n"
        "Task 3 - Swap/remove person and fill the gap: use SWAP_ASSIGNMENT with assignment_id and replacement_employee_id. "
        "For direct replacement/swap, replacement_employee_id must be the target employee id. "
        "If user references employees by name, map those names to ids from CONTEXT_JSON. "
        "If user references shift/date/role and not assignment id, find the matching assignment in CONTEXT_JSON and output its assignment_id. "
        "For remove/unassign or remove-and-fill-gap workflow, set replacement_employee_id to null.\n"
        "When user says fill any shift on a date, return AUTOFILL_DAY with date and omit shift_type.\n"
        "When user says fill a specific role in a shift, return AUTOFILL_DAY with date, shift_type, and requirements.\n"
        "Prefer conservative values and never invent ids; rely on CONTEXT_JSON and role ids list.\n"
        f"Valid day_of_week: {', '.join(DAYS_OF_WEEK)}.\n"
        f"Valid shift_type: {', '.join(SHIFT_TYPES)}.\n"
        "Available role ids:\n"
        f"{role_lines if role_lines else '- no roles found'}\n"
        "If input is ambiguous, infer the most likely action among the 3 allowed actions and keep values conservative.\n"
        "If the message is not related to scheduling (e.g., greetings, questions, or off-topic text), "
        "output {\"type\": \"UNKNOWN\"} with no other fields."
    )


def _get_openai_client():
    if not settings.openai_api_key:
        raise LLMParseError("OPENAI_API_KEY is not configured.")

    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise LLMParseError("langchain-openai is not installed.") from exc

    return ChatOpenAI(
        model=settings.openai_model,
        temperature=0,
        openai_api_key=settings.openai_api_key,
    )


def parse_action_from_message(
    message: str,
    role_context: list[dict[str, int | str]],
) -> ChatAction:
    """Parse a free-text message into a validated `ChatAction`.

    Flow:
    1) Validate configuration and SDK availability
    2) Send a JSON-only completion request to OpenAI
    3) Deserialize JSON payload and validate against `ChatAction`
    4) Normalize enum-like fields to uppercase for downstream consistency
    """

    model = _get_openai_client()

    try:
        structured_llm = model.with_structured_output(IntentPayload)
        payload = structured_llm.invoke(
            [
                ("system", _build_system_prompt(role_context)),
                ("human", message),
            ]
        )
    except Exception as exc:  # noqa: BLE001
        raise LLMParseError(f"OpenAI request failed: {exc}") from exc

    if not isinstance(payload, dict) or not payload:
        raise LLMParseError("OpenAI returned an empty structured payload.")

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
