from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta

from app.schemas.scheduling import ChatAction, RoleRequirement

_AUTOFILL_KEYWORDS = (
    "autofill",
    "fill",
    "preencher",
    "preencha",
    "escalar",
    "escala",
)

_REMOVE_KEYWORDS = (
    "remove",
    "remover",
    "tirar",
    "delete",
    "excluir",
)

_LUNCH_KEYWORDS = ("lunch", "almoco")
_DINNER_KEYWORDS = ("dinner", "jantar", "janta")

_TODAY_KEYWORDS = ("today", "hoje")
_TOMORROW_KEYWORDS = ("tomorrow", "amanha")
_DAY_AFTER_TOMORROW_KEYWORDS = ("day after tomorrow", "depois de amanha")

_WEEKDAY_ALIASES: dict[int, tuple[str, ...]] = {
    0: ("monday", "segunda", "segunda feira"),
    1: ("tuesday", "terca", "terca feira"),
    2: ("wednesday", "quarta", "quarta feira"),
    3: ("thursday", "quinta", "quinta feira"),
    4: ("friday", "sexta", "sexta feira"),
    5: ("saturday", "sabado"),
    6: ("sunday", "domingo"),
}


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_text).strip().lower()


def _contains_any(text: str, values: tuple[str, ...]) -> bool:
    return any(value in text for value in values)


def _next_weekday(base_date: date, weekday: int, force_next_week: bool) -> date:
    delta = (weekday - base_date.weekday()) % 7
    if force_next_week and delta == 0:
        delta = 7
    return base_date + timedelta(days=delta)


def _extract_date(message: str, normalized_message: str, today: date) -> date | None:
    iso_date_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", message)
    if iso_date_match:
        try:
            return date.fromisoformat(iso_date_match.group(1))
        except ValueError:
            pass

    dmY_match = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b", normalized_message)
    if dmY_match:
        day = int(dmY_match.group(1))
        month = int(dmY_match.group(2))
        year = int(dmY_match.group(3))
        try:
            return date(year, month, day)
        except ValueError:
            pass

    if _contains_any(normalized_message, _DAY_AFTER_TOMORROW_KEYWORDS):
        return today + timedelta(days=2)
    if _contains_any(normalized_message, _TOMORROW_KEYWORDS):
        return today + timedelta(days=1)
    if _contains_any(normalized_message, _TODAY_KEYWORDS):
        return today

    for weekday, aliases in _WEEKDAY_ALIASES.items():
        for alias in aliases:
            if alias not in normalized_message:
                continue

            force_next_week = bool(
                re.search(rf"\b(next|proxima|proximo)\s+{re.escape(alias)}\b", normalized_message)
            )
            return _next_weekday(today, weekday, force_next_week)

    return None


def _extract_shift_type(normalized_message: str) -> str | None:
    has_lunch = _contains_any(normalized_message, _LUNCH_KEYWORDS)
    has_dinner = _contains_any(normalized_message, _DINNER_KEYWORDS)

    if has_lunch and not has_dinner:
        return "LUNCH"
    if has_dinner and not has_lunch:
        return "DINNER"
    return None


@dataclass
class LocalSwapRemoveIntent:
    employee_name: str
    target_date: date | None
    shift_type: str | None


def parse_swap_remove_intent_local(
    message: str,
    employee_names: list[str],
    today: date | None = None,
) -> LocalSwapRemoveIntent | None:
    normalized_message = _normalize(message)
    if not _contains_any(normalized_message, _REMOVE_KEYWORDS):
        return None

    matched_employee: str | None = None
    for name in sorted(employee_names, key=len, reverse=True):
        if _normalize(name) in normalized_message:
            matched_employee = name
            break

    if not matched_employee:
        return None

    base_date = today or date.today()
    target_date = _extract_date(message, normalized_message, base_date)
    shift_type = _extract_shift_type(normalized_message)

    return LocalSwapRemoveIntent(
        employee_name=matched_employee,
        target_date=target_date,
        shift_type=shift_type,
    )


def _build_role_aliases(role_name: str) -> list[str]:
    role = _normalize(role_name)
    aliases = {role, f"{role}s"}

    if role == "cook":
        aliases.update({"cozinheiro", "cozinheiros", "cozinheira", "cozinheiras"})
    if role == "dishwasher":
        aliases.update(
            {
                "lavador de pratos",
                "lavadores de pratos",
                "lava pratos",
                "lavapratos",
            }
        )
    if role == "server":
        aliases.update(
            {
                "garcom",
                "garcons",
                "garcon",
                "garcons",
                "waiter",
                "waiters",
                "atendente",
                "atendentes",
            }
        )
    if role == "manager":
        aliases.update({"gerente", "gerentes"})

    return sorted(aliases, key=len, reverse=True)


def _extract_role_counts(
    normalized_message: str,
    role_context: list[dict[str, int | str]],
) -> dict[int, int]:
    counts: dict[int, int] = {}

    for role in role_context:
        role_id = role.get("id")
        role_name = role.get("name")
        if not isinstance(role_id, int) or not isinstance(role_name, str):
            continue

        aliases = _build_role_aliases(role_name)
        if not aliases:
            continue

        alias_pattern = "|".join(re.escape(alias) for alias in aliases)
        number_before = re.compile(rf"\b(\d+)\s*(?:x\s*)?(?:{alias_pattern})\b")
        number_after = re.compile(rf"\b(?:{alias_pattern})\s*(?:x\s*)?(\d+)\b")

        total = 0
        used_spans: list[tuple[int, int]] = []

        for pattern in (number_before, number_after):
            for match in pattern.finditer(normalized_message):
                span = match.span()
                overlap = any(not (span[1] <= s[0] or span[0] >= s[1]) for s in used_spans)
                if overlap:
                    continue
                used_spans.append(span)
                total += int(match.group(1))

        if total > 0:
            counts[role_id] = total

    return counts


def parse_action_from_message_local(
    message: str,
    role_context: list[dict[str, int | str]],
    today: date | None = None,
) -> ChatAction | None:
    normalized_message = _normalize(message)
    target_date = _extract_date(message, normalized_message, today or date.today())

    role_counts = _extract_role_counts(normalized_message, role_context)
    has_autofill_keyword = _contains_any(normalized_message, _AUTOFILL_KEYWORDS)

    if not role_counts and not has_autofill_keyword:
        return None

    requirements = [
        RoleRequirement(role_id=role_id, required_count=required_count)
        for role_id, required_count in role_counts.items()
    ]

    return ChatAction(
        type="AUTOFILL_DAY",
        date=target_date or (today or date.today()),
        reoptimize=("reoptimize" in normalized_message or "reotim" in normalized_message),
        shift_type=_extract_shift_type(normalized_message),
        requirements=requirements or None,
    )
