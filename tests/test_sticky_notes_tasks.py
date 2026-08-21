"""בדיקות לצ'קבוקסים בפתקים — הפונקציות הטהורות והראוט.

האפיון מסמן את הפיצ'ר הזה כמקור הבאג הצפוי, ובניסוח מדויק: *"לחיצה על
צ'קבוקס היא כתיבה למסד, לא שינוי תצוגה"*. הכשל הצפוי הוא שהתצוגה מתהפכת
מיד, השמירה נכשלת בשקט, וברענון הסימון חוזר אחורה — בלי ששום דבר דיווח.

לכן רוב הבדיקות כאן אינן על "האם התו התחלף", אלא על **מה קורה כשהכתיבה
לא נקלטה**.
"""

import pytest

from sticky_notes_tasks import count_tasks, task_state_at_index, toggle_task_at_index


# ---------------------------------------------------------------- טהור

def test_toggles_the_nth_occurrence_not_the_first_match():
    """שלוש שורות זהות — ומסמנים בדיוק את השנייה.

    ``str.replace`` היה מסמן את הראשונה בכל המקרים, ולחיצה על השנייה
    הייתה "קופצת" לראשונה. זו הסיבה שהזיהוי הוא סידורי ולא טקסטואלי.
    """
    content = "- [ ] לבדוק\n- [ ] לבדוק\n- [ ] לבדוק"

    out, changed = toggle_task_at_index(content, 1, True)

    assert changed is True
    assert out == "- [ ] לבדוק\n- [x] לבדוק\n- [ ] לבדוק"


def test_preserves_indent_bullet_and_trailing_text():
    content = "  * [ ] משימה מוזחת עם *הדגשה*"

    out, changed = toggle_task_at_index(content, 0, True)

    assert changed is True
    assert out == "  * [x] משימה מוזחת עם *הדגשה*"


def test_uncheck_returns_a_space():
    out, changed = toggle_task_at_index("- [x] בוצע", 0, False)

    assert changed is True
    assert out == "- [ ] בוצע"


def test_uppercase_x_counts_as_checked():
    """``- [X]`` הוא מסומן. השוואת תווים ישירה הייתה מייצרת כתיבה מיותרת."""
    assert task_state_at_index("- [X] בוצע", 0) is True

    out, changed = toggle_task_at_index("- [X] בוצע", 0, True)
    assert changed is False
    assert out == "- [X] בוצע"


def test_already_in_desired_state_is_a_noop():
    """אידמפוטנטי — ואין כתיבה. הראוט נשען על זה."""
    out, changed = toggle_task_at_index("- [x] בוצע", 0, True)

    assert changed is False
    assert out == "- [x] בוצע"


def test_missing_index_changes_nothing():
    out, changed = toggle_task_at_index("- [ ] אחת", 5, True)

    assert changed is False
    assert out == "- [ ] אחת"
    assert task_state_at_index("- [ ] אחת", 5) is None


def test_non_task_lines_are_not_counted():
    content = "כותרת\n- [ ] אחת\nסתם שורה\n- פריט רגיל\n- [x] שתיים"

    assert count_tasks(content) == 2
    assert task_state_at_index(content, 0) is False
    assert task_state_at_index(content, 1) is True


def test_crlf_content_round_trips():
    """``\\r\\n`` שורד את הפיצול והחיבור מחדש, בלי ענף מיוחד.

    זו התנהגות שנבדקה ולא הונחה: הפיצול על ``\\n`` משאיר ``\\r`` בסוף
    השורה, ה-regex עדיין תואם, והחיבור מרכיב את ``\\r\\n`` בחזרה.
    """
    content = "- [ ] אחת\r\n- [ ] שתיים"

    out, changed = toggle_task_at_index(content, 1, True)

    assert changed is True
    assert out == "- [ ] אחת\r\n- [x] שתיים"


def test_cr_only_content_is_split_correctly():
    """``\\r`` לבדו כן דורש טיפול — בלעדיו שתי משימות נספרות כאחת.

    זו הבדיקה שמגנה על הענף היחיד שנשאר ב-``_split_lines``. אומת
    במוטציה: הסרתו מורידה את הספירה ל-1 ומפילה כאן.
    """
    content = "- [ ] אחת\r- [ ] שתיים"

    assert count_tasks(content) == 2

    out, changed = toggle_task_at_index(content, 1, True)
    assert changed is True
    assert out == "- [ ] אחת\r- [x] שתיים"


def test_lines_inside_a_fence_are_counted_too():
    """החלטה מתועדת: לא מפרשים בלוקי קוד.

    האלטרנטיבה היא פרסר מארקדאון מלא, שהוא מחוץ להיקף — וכבר ידוע בריפו
    הזה מה עולה פרסור מארקדאון שנכתב ביד. הבדיקה קיימת כדי שההחלטה תהיה
    מתועדת ולא הפתעה.
    """
    content = "- [ ] אמיתית\n```\n- [ ] בתוך גדר\n```"

    assert count_tasks(content) == 2


def test_toggle_preserves_length():
    """``- [ ]`` ו-``- [x]`` זהים באורכם, ולכן תקרת 5,000 לא יכולה להישבר."""
    content = "- [ ] " + "א" * 100

    out, _ = toggle_task_at_index(content, 0, True)

    assert len(out) == len(content)


# ---------------------------------------------------------------- הראוט

flask = pytest.importorskip("flask")


class _Res:
    def __init__(self, modified_count=1):
        self.modified_count = modified_count


class _NotesColl:
    def __init__(self, docs):
        self.docs = docs
        self.writes = 0
        self.write_is_noop = False

    def find_one(self, query, projection=None):
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return doc
        return None

    def update_one(self, query, update):
        self.writes += 1
        if self.write_is_noop:
            return _Res()  # מדווח הצלחה, לא כותב
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                doc.update(update.get("$set", {}))
                return _Res()
        return _Res(modified_count=0)


@pytest.fixture
def client(monkeypatch):
    from webapp import sticky_notes_api

    note = {"_id": 1, "user_id": 7, "content": "- [ ] אחת\n- [ ] שתיים"}
    coll = _NotesColl([note])
    db = type("DB", (), {"sticky_notes": coll})()

    monkeypatch.setattr(sticky_notes_api, "get_db", lambda: db)
    monkeypatch.setattr(sticky_notes_api, "ObjectId", lambda x: int(x))

    app = flask.Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sticky_notes_api.sticky_notes_bp)
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["user_id"] = 7
    c.coll = coll
    c.note = note
    return c


def _toggle(c, index, checked=True, **extra):
    payload = {"index": index, "checked": checked}
    payload.update(extra)
    return c.post("/api/sticky-notes/note/1/task", json=payload)


def test_route_toggles_and_returns_authoritative_content(client):
    res = _toggle(client, 1, True)
    body = res.get_json()

    assert res.status_code == 200
    assert body["changed"] is True
    assert body["content"] == "- [ ] אחת\n- [x] שתיים"
    assert client.note["content"] == "- [ ] אחת\n- [x] שתיים"


def test_route_returns_409_when_the_write_did_not_apply(client):
    """הכתיבה מדווחת הצלחה, והקריאה החוזרת מגלה שהתוכן לא זז.

    **זו הבדיקה המרכזית של הפיצ'ר.** בלי הקריאה החוזרת הראוט היה מחזיר
    200, הלקוח היה משאיר את התיבה מסומנת, וברענון הסימון היה נעלם — בלי
    ששום דבר דיווח על כשל. בדיוק מה שהאפיון אוסר.
    """
    client.coll.write_is_noop = True

    res = _toggle(client, 0, True)
    body = res.get_json()

    assert res.status_code == 409
    assert body["error"] == "task_toggle_not_applied"
    # התשובה נושאת את התוכן האמיתי, כדי שהלקוח יוכל להחזיר את התצוגה
    assert body["content"] == "- [ ] אחת\n- [ ] שתיים"


def test_route_rejects_a_stale_index(client):
    """סידורי שאינו קיים ⇒ 409 ולא 200. התצוגה של הלקוח מתארת פתק אחר."""
    res = _toggle(client, 9, True)

    assert res.status_code == 409
    assert res.get_json()["error"] == "task_index_not_found"
    assert client.coll.writes == 0


def test_route_is_idempotent_without_writing(client):
    _toggle(client, 0, True)
    writes_after_first = client.coll.writes

    res = _toggle(client, 0, True)

    assert res.status_code == 200
    assert res.get_json()["changed"] is False
    assert client.coll.writes == writes_after_first  # לא נכתב שוב


def test_route_uses_compare_and_swap(client):
    """הפילטר כולל את התוכן הקודם, כדי שכותב מקביל לא יידרס."""
    captured = {}
    original_update = client.coll.update_one

    def _spy(query, update):
        captured.update(query)
        return original_update(query, update)

    client.coll.update_one = _spy
    _toggle(client, 0, True)

    assert captured.get("content") == "- [ ] אחת\n- [ ] שתיים"


def test_route_404_for_foreign_note(client):
    client.coll.docs.append({"_id": 2, "user_id": 99, "content": "- [ ] של אחר"})

    res = client.post("/api/sticky-notes/note/2/task", json={"index": 0, "checked": True})

    assert res.status_code == 404


def test_route_rejects_bad_index(client):
    assert _toggle(client, "לא-מספר").status_code == 400
    assert _toggle(client, -1).status_code == 400
