"""Spoken confirmation for actions that open the house up.

When ``confirm_sensitive_actions`` is on, a tool call that would unlock a door,
disarm an alarm or open a cover is refused unless the assistant's previous turn
ended with a question. The prompt tells the model to ask first, and the guard
here makes that more than a suggestion: a model that skips the question gets a
refusal it can read, and it then asks.
"""

from __future__ import annotations

from typing import Any

from .const import SENSITIVE_DOMAINS, SENSITIVE_TOOL_NAMES
from .logging_config import get_logger

_LOGGER = get_logger(__name__)

CONFIRMATION_REQUIRED = (
    "Confirmation requise : demande d'abord à l'utilisateur de confirmer cette action à voix haute, "
    "puis réessaie une fois qu'il a répondu oui."
)
# A question mark at the end of the previous answer means Home Assistant kept the
# microphone open, so the user has had the chance to answer.
_QUESTION_MARKS = ("?", "？", ";")


def _entity_ids(arguments: Any) -> list[str]:
    """Collect entity ids out of a tool-call payload, whatever shape it takes."""
    if not isinstance(arguments, dict):
        return []
    found: list[str] = []
    for key in ("entity_id", "entity_ids", "name", "area"):
        value = arguments.get(key)
        if isinstance(value, str):
            found.append(value)
        elif isinstance(value, list):
            found.extend(item for item in value if isinstance(item, str))
    domain = arguments.get("domain")
    if isinstance(domain, str):
        found.append(f"{domain}.")
    return found


def is_sensitive(tool_name: str, arguments: Any) -> bool:
    """True when the call targets a lock, an alarm or a cover through a state-changing tool."""
    if tool_name not in SENSITIVE_TOOL_NAMES:
        return False
    for candidate in _entity_ids(arguments):
        domain = candidate.split(".", 1)[0].lower()
        if domain in SENSITIVE_DOMAINS:
            return True
    return False


def was_confirmed(chat_log: Any) -> bool:
    """True when the assistant already asked a question in this conversation."""
    for content in reversed(getattr(chat_log, "content", None) or []):
        if getattr(content, "role", None) != "assistant":
            continue
        text = (getattr(content, "content", None) or "").strip()
        if text:
            return text.endswith(_QUESTION_MARKS)
    return False


def guard(tool_name: str, arguments: Any, chat_log: Any, *, enabled: bool) -> dict[str, str] | None:
    """Return a refusal payload when the call needs a confirmation it does not have."""
    if not enabled or not is_sensitive(tool_name, arguments):
        return None
    if was_confirmed(chat_log):
        return None
    _LOGGER.info(f"[SAFETY] {tool_name} on {arguments} needs a spoken confirmation first")
    return {"error": CONFIRMATION_REQUIRED}
