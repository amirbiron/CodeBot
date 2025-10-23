from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional


def parse_time(text: str, user_tz: str) -> Optional[datetime]:
    """Very lightweight time parser for common phrases.

    Supports:
    - "tomorrow HH:MM"
    - "HH:MM" (today)
    - "in X hours" / "בעוד X שעות"
    - ISO-like "YYYY-MM-DD HH:MM"
    """
    try:
        text = (text or "").strip()
        if not text:
            return None
        tz = ZoneInfo(user_tz or "UTC")
        now = datetime.now(tz)

        # tomorrow HH:MM
        if text.lower().startswith("tomorrow"):
            parts = text.split()
            if len(parts) >= 2 and ":" in parts[1]:
                hh, mm = parts[1].split(":", 1)
                dt = (now + timedelta(days=1)).replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
                return dt

        # HH:MM today
        if ":" in text and len(text) <= 5 and text.replace(":", "").isdigit():
            hh, mm = text.split(":", 1)
            dt = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
            if dt <= now:
                dt = dt + timedelta(days=1)
            return dt

        # in X hours
        if text.lower().startswith("in ") and "hour" in text.lower():
            try:
                num = int("".join([c for c in text if c.isdigit()]))
                return now + timedelta(hours=num)
            except Exception:
                pass

        # בעידן X שעות
        if text.startswith("בעוד") and "שעות" in text:
            try:
                num = int("".join([c for c in text if c.isdigit()]))
                return now + timedelta(hours=num)
            except Exception:
                pass

        # ISO-like
        for fmt in ("%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
            try:
                dt_naive = datetime.strptime(text, fmt)
                return dt_naive.replace(tzinfo=tz)
            except Exception:
                continue

        return None
    except Exception:
        return None
