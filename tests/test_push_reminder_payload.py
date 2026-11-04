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


# -- השורה שמתחת לכותרת: שם הפתק --------------------------------------------------------


class _Notes:
    """``sticky_notes`` שמכבד את ההיטלה — כמו המסד. דמה שמחזירה את כל המסמך הייתה מעבירה
    את הטסט גם כש-``title`` חסר בהיטלה, ובמסד האמיתי השם לא היה מגיע."""

    def __init__(self, docs):
        self.docs = docs
        self.projections = []

    def find_one(self, filt, projection=None, *args, **kwargs):
        self.projections.append(projection)
        for doc in self.docs:
            if doc.get('_id') == filt.get('_id'):
                if projection is None:
                    return dict(doc)
                return {k: v for k, v in doc.items() if k == '_id' or projection.get(k)}
        return None


class _NotesDB:
    def __init__(self, docs):
        self.sticky_notes = _Notes(docs)


NOTE_OID = '64b7f1d2e3a4b5c6d7e8f901'


def _note(**fields):
    from bson import ObjectId

    return dict({'_id': ObjectId(NOTE_OID), 'user_id': 1, 'content': 'אחת שתיים שלוש'}, **fields)


def _body(db):
    payload = push_mod._build_reminder_payload(db, {'note_id': NOTE_OID, 'file_id': '', 'board_id': 'b1'})
    assert payload['notification']['body'] == payload['data']['body']
    return payload['notification']['body']


def test_the_body_is_the_note_name():
    assert _body(_NotesDB([_note(title='שם הפתק')])) == 'שם הפתק'


def test_without_a_name_the_body_is_the_start_of_the_note():
    assert _body(_NotesDB([_note()])) == 'אחת שתיים שלוש'


def test_a_note_whose_id_is_a_plain_string_is_still_found():
    """תזכורות ישנות: מזהה שאינו ObjectId — מחפשים אותו כמחרוזת, כמו קודם."""
    db = _NotesDB([{'_id': 'legacy-1', 'title': 'ישן'}])
    payload = push_mod._build_reminder_payload(db, {'note_id': 'legacy-1'})
    assert payload['notification']['body'] == 'ישן'


def test_a_note_that_is_gone_leaves_the_body_empty():
    assert _body(_NotesDB([])) == ''


def test_a_failing_read_still_builds_the_notification_and_is_logged(caplog):
    """גבול של לולאת השליחה: התזכורת כבר נתפסה, וחריגה שעולה עוצרת את הסבב לכל המשתמשים."""

    class _Broken:
        def find_one(self, *args, **kwargs):
            raise RuntimeError('boom')

    class _DB:
        sticky_notes = _Broken()

    with caplog.at_level('ERROR', logger=push_mod.logger.name):
        assert _body(_DB()) == ''
    assert any(r.getMessage() == 'push_reminder_label_failed' and r.exc_info for r in caplog.records)
