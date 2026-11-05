"""Shared validation for optional, user-written offer callouts."""

from __future__ import annotations

import math
from typing import Any

MAX_CALLOUT_CHARS = 180


def get_custom_callout(row: Any) -> str:
    """Return the optional product callout, rejecting overly long copy."""
    try:
        value = row.get("chamada", "")
    except Exception:
        value = ""

    if value is None:
        return ""
    try:
        if math.isnan(value):
            return ""
    except (TypeError, ValueError):
        pass

    text = str(value).strip()
    if text.casefold() in {"nan", "<na>"}:
        return ""
    if len(text) > MAX_CALLOUT_CHARS:
        raise ValueError(
            f"A chamada personalizada deve ter no máximo {MAX_CALLOUT_CHARS} caracteres."
        )
    return text
