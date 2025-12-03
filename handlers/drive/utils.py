from __future__ import annotations

from typing import Any, Optional


def extract_schedule_key(prefs: Any) -> Optional[str]:
    """Normalize historic/new drive schedule preference structures."""
    if not isinstance(prefs, dict):
        return None
    candidate = prefs.get("schedule")
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    if isinstance(candidate, dict):
        for field in ("key", "value", "name"):
            val = candidate.get(field)
            if isinstance(val, str) and val.strip():
                return val.strip()
    alt = prefs.get("schedule_key") or prefs.get("scheduleKey")
    if isinstance(alt, str) and alt.strip():
        return alt.strip()
    return None
