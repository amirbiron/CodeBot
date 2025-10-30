from __future__ import annotations

from datetime import datetime, timedelta
import re
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

        # Hebrew specific quick phrases first
        if re.match(r"^בעוד\s+רבע\s+שעה\s*$", text):
            return now + timedelta(minutes=15)
        if re.match(r"^בעוד\s+חצי\s+שעה\s*$", text):
            return now + timedelta(minutes=30)

        # Hebrew minutes: "בעוד X דקות" or "בעוד דקה"
        m = re.match(r"^בעוד\s+(\d+)\s*דקות?\s*$", text)
        if m:
            return now + timedelta(minutes=int(m.group(1)))
        if re.match(r"^בעוד\s+דקה\s*$", text):
            return now + timedelta(minutes=1)

        # Hebrew hours: "בעוד X שעות" or "בעוד שעה"
        m = re.match(r"^בעוד\s+(\d+)\s*שעות?\s*$", text)
        if m:
            return now + timedelta(hours=int(m.group(1)))
        if re.match(r"^בעוד\s+שעה\s*$", text):
            return now + timedelta(hours=1)

        # English minutes/hours: "in X minutes/hours"
        m = re.match(r"^in\s+(\d+)\s*minutes?\s*$", text, flags=re.IGNORECASE)
        if m:
            return now + timedelta(minutes=int(m.group(1)))
        m = re.match(r"^in\s+(\d+)\s*hours?\s*$", text, flags=re.IGNORECASE)
        if m:
            return now + timedelta(hours=int(m.group(1)))

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
