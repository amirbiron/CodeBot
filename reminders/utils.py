from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional


def parse_time(text: str, user_tz: str) -> Optional[datetime]:
    """Very lightweight time parser for common phrases.

    Supports:
    - "tomorrow HH:MM"
    - "HH:MM" (today)
    - "in X hours" / "בעוד X שעות" / "בעוד שעה"
    - "in X minutes" / "בעוד X דקות" / "בעוד דקה"
    - "בעוד רבע שעה" (15 דקות) / "בעוד חצי שעה" (30 דקות)
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

        # in X minutes
        if text.lower().startswith("in ") and "minute" in text.lower():
            try:
                num = int("".join([c for c in text if c.isdigit()]))
                return now + timedelta(minutes=num)
            except Exception:
                pass

        # בעו̄ד X שעות / שעה
        if text.startswith("בעוד") and "שעות" in text:
            try:
                num = int("".join([c for c in text if c.isdigit()]))
                return now + timedelta(hours=num)
            except Exception:
                pass

        # בעוד שעה (ללא מספר)
        if text.startswith("בעוד") and "שעה" in text and "שעות" not in text:
            return now + timedelta(hours=1)

        # בעוד X דקות / דקה
        if text.startswith("בעוד") and ("דקות" in text or "דקה" in text):
            # אם יש ספרות – השתמש בהן; אחרת, "דקה" => 1
            digits = "".join([c for c in text if c.isdigit()])
            if digits:
                try:
                    return now + timedelta(minutes=int(digits))
                except Exception:
                    pass
            # "דקה" ללא מספר
            if "דקה" in text and "דקות" not in text:
                return now + timedelta(minutes=1)

        # בעוד רבע שעה (15 דקות)
        if text.startswith("בעוד") and "רבע" in text and "שעה" in text:
            return now + timedelta(minutes=15)

        # בעוד חצי שעה (30 דקות)
        if text.startswith("בעוד") and "חצי" in text and "שעה" in text:
            return now + timedelta(minutes=30)

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
