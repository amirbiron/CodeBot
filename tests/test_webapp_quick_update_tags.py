"""מודאל התגיות בעמוד הקובץ — מה שהשרת עושה בשבילו, מול מונגו אמיתי.

המודאל שולח שורת טקסט ל-``POST /api/file/<id>/quick-update`` ומציג את
``tags`` שחוזר בתשובה. שלושה דברים צריכים להיות נכונים בשרת כדי שזה יעבוד:
החיתוך זהה לעמוד העריכה (``#`` הוא מפריד), התשובה נושאת את התגיות כפי
שנשמרו, ועמוד הקובץ אינו מוגש מהמטמון אחרי שינוי תגיות — שינוי שבכוונה
אינו מזיז את ``updated_at``. הזרימה בדפדפן עצמו:
``tests/test_file_tags_modal_browser.py``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from html.parser import HTMLParser

import pytest
from bson import ObjectId

pytest.importorskip("flask")

USER_ID = 7
STAMP = datetime(2019, 3, 7, 9, 15, tzinfo=timezone.utc)


def _seed(wired_mongo, tags=None):
    db = wired_mongo.get_db()
    db.code_snippets.delete_many({})
    db.large_files.delete_many({})
    oid = ObjectId()
    db.code_snippets.insert_one({
        "_id": oid, "user_id": USER_ID, "file_name": "demo.py",
        "code": "print('hi')\n", "programming_language": "python",
        "version": 1, "is_active": True, "created_at": STAMP, "updated_at": STAMP,
        "description": "קובץ הדגמה",
        "tags": ["Python", "repo:amirbiron/CodeBot"] if tags is None else tags,
    })
    client = wired_mongo.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = USER_ID
        sess["user_data"] = {"id": USER_ID, "first_name": "בדיקה",
                             "is_admin": False, "is_premium": False}
    return client, oid


def _stored(wired_mongo, oid):
    return wired_mongo.get_db().code_snippets.find_one({"_id": oid}, {"tags": 1, "updated_at": 1})


def _post_tags(client, oid, tags):
    return client.post(f"/api/file/{oid}/quick-update", json={"tags": tags})


def test_the_answer_carries_the_tags_as_stored_not_as_typed(wired_mongo):
    """המודאל מציג את ``tags`` שבתשובה. השרת מנרמל, ולכן זה אינו מה שהוקלד."""
    client, oid = _seed(wired_mongo)

    resp = _post_tags(client, oid, "Python, Utils")
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    body = resp.get_json()
    assert body["ok"] is True
    assert body["tags"] == ["python", "utils"], body
    assert _stored(wired_mongo, oid)["tags"] == body["tags"]


def test_a_hash_in_the_text_is_a_separator_as_in_the_edit_page(wired_mongo):
    """``#python`` נשמר כ-``python``, כמו בעמוד העריכה — ולא כ-``#python``,
    שעמוד הקובץ היה מציג כ-``##python``."""
    client, oid = _seed(wired_mongo)

    resp = _post_tags(client, oid, "#Python, #api")
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert _stored(wired_mongo, oid)["tags"] == ["python", "api"]


def test_a_tags_only_update_does_not_move_updated_at(wired_mongo):
    client, oid = _seed(wired_mongo)

    _post_tags(client, oid, "a, b")
    stored = _stored(wired_mongo, oid)
    assert stored["tags"] == ["a", "b"], "הכתיבה עצמה לא קרתה — הבדיקה הייתה עוברת על ראוט שבור"
    assert stored["updated_at"].replace(tzinfo=timezone.utc) == STAMP


@pytest.mark.parametrize("tags", [{"a": 1}, ["ok", 3], 5])
def test_a_malformed_tags_value_is_refused_and_nothing_is_written(wired_mongo, tags):
    """עד כאן ``{"a": 1}`` ו-``5`` הפילו את הראוט ב-500, ו-``["ok", 3]`` נשמר כ-``["ok", "3"]``."""
    client, oid = _seed(wired_mongo)

    resp = _post_tags(client, oid, tags)
    assert resp.status_code == 400, resp.get_data(as_text=True)[:300]
    assert resp.get_json()["ok"] is False
    assert _stored(wired_mongo, oid)["tags"] == ["Python", "repo:amirbiron/CodeBot"]


def test_a_json_body_that_is_not_an_object_is_refused(wired_mongo):
    client, oid = _seed(wired_mongo)

    resp = client.post(f"/api/file/{oid}/quick-update", json=["tags"])
    assert resp.status_code == 400, resp.get_data(as_text=True)[:300]


def test_a_failed_read_back_answers_null_tags_and_keeps_the_write(wired_mongo, monkeypatch):
    """שגיאת מסד בקריאה החוזרת: הכתיבה כבר קרתה, והתשובה אומרת "לא ידוע"
    (``tags: null``) — והמודאל טוען את העמוד מחדש במקום להציג ניחוש."""
    from pymongo.collection import Collection
    from pymongo.errors import AutoReconnect

    client, oid = _seed(wired_mongo)
    real_find_one = Collection.find_one

    def flaky_find_one(self, *args, **kwargs):
        if self.name == "code_snippets" and len(args) > 1 and args[1] == {"tags": 1}:
            raise AutoReconnect("simulated")
        return real_find_one(self, *args, **kwargs)

    monkeypatch.setattr(Collection, "find_one", flaky_find_one)

    resp = _post_tags(client, oid, "x")
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    body = resp.get_json()
    assert body["ok"] is True
    assert body["tags"] is None, body
    monkeypatch.undo()
    assert _stored(wired_mongo, oid)["tags"] == ["x"]


def test_a_bug_in_the_read_back_is_not_labelled_a_db_failure(wired_mongo, monkeypatch):
    """רק ``PyMongoError`` הוא "המסד לא נתן לקרוא". חריגה אחרת היא באג, והיא
    עולה — ולא מקבלת את התווית ``tags: null`` (``RECURRING-PATTERNS.md`` R10)."""
    from pymongo.collection import Collection

    client, oid = _seed(wired_mongo)
    real_find_one = Collection.find_one

    def broken_find_one(self, *args, **kwargs):
        if self.name == "code_snippets" and len(args) > 1 and args[1] == {"tags": 1}:
            raise TypeError("simulated bug")
        return real_find_one(self, *args, **kwargs)

    monkeypatch.setattr(Collection, "find_one", broken_find_one)

    resp = _post_tags(client, oid, "x")
    assert resp.status_code == 500, resp.get_data(as_text=True)[:300]


def test_the_file_page_is_revalidated_after_a_tags_only_change(wired_mongo):
    """ה-ETag של עמוד הקובץ כולל את התגיות.

    בלעדיהן, שינוי תגיות — שאינו מזיז את ``updated_at`` — השאיר את ה-ETag
    כמו שהיה: הדפדפן קיבל 304 והציג את התגיות הישנות, ומודאל התגיות נפתח
    איתן. נמדד גם ב-Chromium מול שרת חי.
    """
    client, oid = _seed(wired_mongo)
    first = client.get(f"/file/{oid}")
    assert first.status_code == 200
    etag = first.headers["ETag"]

    # בלי שינוי — עדיין 304: התיקון לא שבר את המטמון
    assert client.get(f"/file/{oid}", headers={"If-None-Match": etag}).status_code == 304

    _post_tags(client, oid, "fresh")
    again = client.get(f"/file/{oid}", headers={"If-None-Match": etag})
    assert again.status_code == 200, "שינוי תגיות החזיר 304 — הדפדפן יציג את התגיות הישנות"
    assert "#fresh" in again.get_data(as_text=True)


class _TagsListParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags_list = None
        self.menu_actions = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id") == "fileTagsList":
            self.tags_list = attrs
        if "data-menu-action" in attrs:
            self.menu_actions.append(attrs["data-menu-action"])


def _parse(html):
    parser = _TagsListParser()
    parser.feed(html)
    return parser


def test_the_page_hands_the_modal_the_tags_as_json_even_with_quotes(wired_mongo):
    """המודאל נפתח מ-``data-tags``, ולא מפירוק הטקסט שמוצג.

    ``tojson`` אינו מקודד ``"``, וה-attribute במירכאות כפולות — ולכן
    ``forceescape``. תגית עם מירכאות היא הקלט ששובר את ה-attribute בלעדיו.
    """
    client, oid = _seed(wired_mongo, tags=['say "hi"', "שלום"])
    page = _parse(client.get(f"/file/{oid}").get_data(as_text=True))

    assert page.tags_list is not None, "אין מכל תגיות בעמוד"
    assert json.loads(page.tags_list["data-tags"]) == ['say "hi"', "שלום"]
    assert "tags" in page.menu_actions


def test_a_file_without_tags_still_has_the_hidden_row(wired_mongo):
    """המכל קיים גם בלי תגיות, מוסתר, כדי שהמודאל יוכל למלא אותו חי."""
    client, oid = _seed(wired_mongo, tags=[])
    page = _parse(client.get(f"/file/{oid}").get_data(as_text=True))

    assert page.tags_list is not None
    assert "hidden" in page.tags_list
    assert json.loads(page.tags_list["data-tags"]) == []


def test_a_large_file_has_no_tags_item_because_quick_update_cannot_reach_it(wired_mongo):
    """``quick-update`` כותב רק ל-``code_snippets``. קובץ גדול יושב ב-``large_files``,
    ולכן הפריט אינו מוצג שם — והבדיקה מקבעת גם את הסיבה, ההערה בתבנית."""
    client, _ = _seed(wired_mongo)
    large_id = ObjectId()
    wired_mongo.get_db().large_files.insert_one({
        "_id": large_id, "user_id": USER_ID, "file_name": "big.txt", "content": "x\n",
        "programming_language": "text", "is_active": True,
        "created_at": STAMP, "updated_at": STAMP, "tags": ["big"],
    })

    page = _parse(client.get(f"/file/{large_id}").get_data(as_text=True))
    assert "tags" not in page.menu_actions

    resp = _post_tags(client, large_id, "x")
    assert resp.status_code == 404, resp.get_data(as_text=True)[:300]
