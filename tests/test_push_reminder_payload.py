"""גוף ההתראה של תזכורת נושא את המועד שהיא נורתה עליו.

ה-Service Worker מחזיר אותו ב-``ack``, כדי שהאישור ייקשר למועד הזה ולא
ל"איזו שהיא" תזכורת של הפתק (WARN-001 בסקירת #3430). בלי השדה, לחיצה על
התראה ישנה במגש סגרה תזכורת שנקבעה מחדש למחר.
"""
from __future__ import annotations

import importlib
from datetime import datetime, timezone

push_mod = importlib.import_module('webapp.push_api')


class _NoNotes:
    def find_one(self, *args, **kwargs):
        return None


class _DB:
    sticky_notes = _NoNotes()


def test_the_payload_carries_the_occurrence():
    fired_at = datetime(2026, 9, 20, 9, 0, 0, 123000, tzinfo=timezone.utc)
    payload = push_mod._build_reminder_payload(_DB(), {'note_id': 'n1', 'file_id': 'f1', 'remind_at': fired_at})
    assert payload['data']['remind_at'] == fired_at.isoformat()


def test_a_reminder_without_a_time_carries_an_empty_occurrence():
    """מסמך בלי ``remind_at`` (לא אמור לקרות, אבל השדה מגיע מהמסד): מחרוזת ריקה,
    שהשרת קורא כ"בלי קשירה", ולא חריגה שמפילה את השליחה כולה."""
    payload = push_mod._build_reminder_payload(_DB(), {'note_id': 'n1', 'file_id': 'f1'})
    assert payload['data']['remind_at'] == ''
