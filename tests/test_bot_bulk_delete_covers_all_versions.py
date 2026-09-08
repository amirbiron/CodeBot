"""מחיקה מרובה **בבוט** מוחקת קבצים, לא גרסאות.

הדוח על הבאג הניח שהבוט הוא קוד ההשוואה התקין. זה נכון למחיקה של קובץ
בודד (``delete_file`` לפי שם), אבל **לא** למחיקה מרובה: ``rf_delete_do``
רץ בלולאה על ``delete_file_by_id``, שסינן לפי ה-``_id`` של הגרסה
האחרונה — בדיוק כמו הראוט בוובאפ. שני מסלולי המחיקה-המרובה, בשני
הצדדים, היו שבורים.

הבדיקה על ה-callback עצמו ולא על שכבת ה-DB: מה שנשבר כאן הוא **החיווט**
— איזו פונקציה נקראת ובאילו ארגומנטים. הסמנטיקה של המחיקה עצמה נבדקת
ב-``tests/test_repository_delete_file_by_id_smoke.py``.
"""

import types

import pytest


class _Facade:
    """פסאדה מדומה שמקליטה את הקריאה — או מדווחת כשל."""

    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def soft_delete_files_by_ids(self, user_id, file_ids):
        self.calls.append((user_id, list(file_ids)))
        return self.outcome

    def get_regular_files_paginated(self, user_id, page=1, per_page=10):
        return ([], 0)


class _Query:
    def __init__(self, data):
        self.data = data
        self.text = None

    async def answer(self, *a, **k):
        return None

    async def edit_message_text(self, text=None, reply_markup=None, parse_mode=None):
        self.text = text


class _Update:
    def __init__(self, data):
        self.callback_query = _Query(data)

    @property
    def effective_user(self):
        return types.SimpleNamespace(id=7)


async def _run(monkeypatch, facade):
    import conversation_handlers as ch
    monkeypatch.setattr(ch, "_get_files_facade_or_none", lambda: facade)
    u = _Update("rf_delete_do")
    ctx = types.SimpleNamespace(
        user_data={"rf_selected_ids": ["id1", "id2"], "files_last_page": 1})
    await ch.handle_callback_query(u, ctx)
    return u.callback_query.text


@pytest.mark.asyncio
async def test_all_selected_ids_go_in_one_call_by_file_identity(monkeypatch):
    facade = _Facade({"files": 2, "versions": 9, "missing": 0})

    text = await _run(monkeypatch, facade)

    # קריאה **אחת** עם שני המזהים, ולא לולאה של קריאה לכל מזהה
    assert facade.calls == [(7, ["id1", "id2"])], facade.calls
    # והמונה שמוצג הוא קבצים ולא מסמכי גרסה — תשעה מסמכים, שני קבצים
    assert "2 קבצים" in text, text
    assert "9" not in text, text


@pytest.mark.asyncio
async def test_a_failed_delete_is_not_reported_as_success(monkeypatch):
    """‏``None`` הוא "לא ידוע", ולא "לא נמחק דבר".

    בלי ההבחנה הזו תקלה במסד הייתה מוצגת כ-"✅ הועברו לסל 0 קבצים" —
    אישור שקרי בדיוק על הפעולה שלא קרתה (``CRITICAL-PATTERNS.md`` K11).
    """
    text = await _run(monkeypatch, _Facade(None))

    assert "✅" not in text, text
    assert "נכשלה" in text, text
