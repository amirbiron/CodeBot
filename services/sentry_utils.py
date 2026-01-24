from __future__ import annotations

from typing import Any, Optional


def coerce_non_negative_int(value: Any) -> Optional[int]:
    try:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            parsed = int(value)
        else:
            text = str(value).strip()
            if not text:
                return None
            parsed = int(float(text))
        if parsed < 0:
            return None
        return parsed
    except Exception:
        return None


def first_int(*values: Any) -> Optional[int]:
    for value in values:
        parsed = coerce_non_negative_int(value)
        if parsed is not None:
            return parsed
    return None
