"""
כלים לפרסור טווחי זמן עבור פקודות ChatOps.

תומך ב:
- --since <duration>  (m/h/d)
- --from <iso8601> --to <iso8601>

עקרונות:
- ברירת מחדל: now - default_since .. now
- Timezone: אם לא צוין, מניחים UTC
- Safety: חלון מקסימלי (למשל 24h) כדי למנוע שאילתות כבדות
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Iterable, List, Optional, Tuple


class TimeRangeParseError(ValueError):
    """קלט טווח זמן לא תקין עבור פקודות ChatOps."""


_DURATION_RE = re.compile(r"^(?P<num>\d+)(?P<unit>[mhd])$", re.IGNORECASE)


def _utcnow() -> datetime:
    # עטיפה כדי לאפשר monkeypatch בטסטים.
    return datetime.now(timezone.utc)


def _parse_duration(text: str) -> timedelta:
    raw = str(text or "").strip()
    m = _DURATION_RE.match(raw)
    if not m:
        raise TimeRangeParseError("פורמט --since לא תקין. דוגמאות: 15m, 2h, 1d")
    num = int(m.group("num"))
    unit = m.group("unit").lower()
    if num <= 0:
        raise TimeRangeParseError("משך חייב להיות גדול מ-0")
    if unit == "m":
        return timedelta(minutes=num)
    if unit == "h":
        return timedelta(hours=num)
    if unit == "d":
        return timedelta(days=num)
    raise TimeRangeParseError("יחידת זמן לא נתמכת (m/h/d)")


def _parse_iso8601_utc(text: str) -> datetime:
    raw = str(text or "").strip()
    if not raw:
        raise TimeRangeParseError("זמן ריק אינו תקין")
    # תמיכה ב-Z
    raw2 = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw2)
    except Exception:
        raise TimeRangeParseError("פורמט זמן לא תקין. דוגמה: 2025-12-16T10:00 (UTC)")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


@dataclass(frozen=True)
class TimeRange:
    start: datetime
    end: datetime
    label: str  # תיאור קצר להצגה למשתמש

    def duration(self) -> timedelta:
        return self.end - self.start


def parse_time_range(
    args: Iterable[str] | None,
    *,
    default_since: timedelta = timedelta(minutes=5),
    max_window: timedelta = timedelta(hours=24),
) -> Tuple[TimeRange, List[str]]:
    """Parse a time range out of args and return (range, remaining_args)."""
    tokens = [str(t) for t in (args or []) if str(t).strip() != ""]
    consumed: set[int] = set()

    since_raw: Optional[str] = None
    from_raw: Optional[str] = None
    to_raw: Optional[str] = None

    def _take_flag_value(idx: int) -> str:
        if idx + 1 >= len(tokens):
            raise TimeRangeParseError("חסר ערך אחרי הדגל (לדוגמה: --since 15m)")
        consumed.add(idx)
        consumed.add(idx + 1)
        return tokens[idx + 1]

    for i, tok in enumerate(tokens):
        t = tok.strip()
        tl = t.lower()

        # --- GNU style flags: --since / --from / --to (also supports --flag=value) ---
        if tl == "--since":
            since_raw = _take_flag_value(i)
            continue
        if tl.startswith("--since="):
            consumed.add(i)
            since_raw = t.split("=", 1)[1].strip()
            continue
        if tl == "--from":
            from_raw = _take_flag_value(i)
            continue
        if tl.startswith("--from="):
            consumed.add(i)
            from_raw = t.split("=", 1)[1].strip()
            continue
        if tl == "--to":
            to_raw = _take_flag_value(i)
            continue
        if tl.startswith("--to="):
            consumed.add(i)
            to_raw = t.split("=", 1)[1].strip()
            continue

        # --- Back-compat: key=value tokens ---
        if "=" in t:
            k, v = t.split("=", 1)
            key = (k or "").strip().lower()
            val = (v or "").strip()
            if key in {"since", "from", "to"}:
                consumed.add(i)
                if key == "since":
                    since_raw = val
                elif key == "from":
                    from_raw = val
                elif key == "to":
                    to_raw = val

    if since_raw and (from_raw or to_raw):
        raise TimeRangeParseError("אי אפשר לשלב --since עם --from/--to")
    if (from_raw and not to_raw) or (to_raw and not from_raw):
        raise TimeRangeParseError("כדי להשתמש ב--from חייבים גם --to (ולהפך)")

    now = _utcnow()
    if since_raw:
        delta = _parse_duration(since_raw)
        start = now - delta
        end = now
        label = f"{start.strftime('%Y-%m-%d %H:%M')} - {end.strftime('%Y-%m-%d %H:%M')} UTC (since {since_raw})"
    elif from_raw and to_raw:
        start = _parse_iso8601_utc(from_raw)
        end = _parse_iso8601_utc(to_raw)
        label = f"{start.strftime('%Y-%m-%d %H:%M')} - {end.strftime('%Y-%m-%d %H:%M')} UTC"
    else:
        # default
        start = now - default_since
        end = now
        minutes = int(max(1, default_since.total_seconds() // 60))
        label = f"{start.strftime('%Y-%m-%d %H:%M')} - {end.strftime('%Y-%m-%d %H:%M')} UTC (default {minutes}m)"

    # Validation
    if end <= start:
        raise TimeRangeParseError("טווח זמן לא תקין: from חייב להיות קטן מ-to")
    if (end - start) > max_window:
        hours = max_window.total_seconds() / 3600.0
        raise TimeRangeParseError(f"טווח זמן ארוך מדי (מקסימום {hours:.0f} שעות)")

    # Normalize to UTC aware
    try:
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        else:
            start = start.astimezone(timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        else:
            end = end.astimezone(timezone.utc)
    except Exception:
        start = start.replace(tzinfo=timezone.utc)
        end = end.replace(tzinfo=timezone.utc)

    remaining = [tok for idx, tok in enumerate(tokens) if idx not in consumed]
    return TimeRange(start=start, end=end, label=label), remaining

