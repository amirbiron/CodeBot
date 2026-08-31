"""ראוטי המטא-דאטה בוובאפ אינם מדווחים שהקובץ נערך.

**למה זה קיים.** ``updated_at`` מציין מתי התוכן, התיאור או השם של הקובץ
השתנו: ``file_was_edited`` נגזרת ממנו כדי להחליט אם להציג "עודכן", והפיד
בדשבורד ממיין לפיו.

התיקון בשכבת ה-DB (``repository`` ו-``manager``) לא הספיק, כי הוובאפ
מחזיק **מימוש מקביל** — הראוטים האלה כותבים ישירות ל-``code_snippets``
במקום לעבור דרך ה-repository, ולכן המשיכו לחתום. אותו פער בדיוק כבר
הופיע בתיקון ``created_at``, שם נדרשו שבעה ראוטים.

הבדיקות רצות דרך ה-HTTP client — כלומר המסלול שהדפדפן עובר בו — וקוראות
בחזרה את **כל** מסמכי הגרסה, כי ה-``update_many`` נוגע בכולם.
"""

from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId

pytest.importorskip("flask")

USER_ID = 7
STAMP = datetime(2019, 3, 7, 9, 15, tzinfo=timezone.utc)


def _seed(wired_mongo, file_name="amir.md", versions=3, **extra):
    """קובץ עם כמה גרסאות, כולן עם ``updated_at`` היסטורי וקבוע."""
    db = wired_mongo.get_db()
    db.code_snippets.delete_many({})
    ids = []
    for v in range(1, versions + 1):
        oid = ObjectId()
        ids.append(oid)
        doc = {
            "_id": oid,
            "user_id": USER_ID,
            "file_name": file_name,
            "code": f"# גרסה {v}",
            "programming_language": "markdown",
            "version": v,
            "is_active": True,
            "created_at": STAMP,
            "updated_at": STAMP + timedelta(minutes=v),
        }
        doc.update(extra)
        db.code_snippets.insert_one(doc)

    client = wired_mongo.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = USER_ID
        sess["user_data"] = {"id": USER_ID, "first_name": "בדיקה",
                             "is_admin": False, "is_premium": False}
    return client, ids


def _stamps(wired_mongo, file_name="amir.md"):
    """‏``updated_at`` של כל הגרסאות, בקריאה חוזרת מהמסד."""
    docs = wired_mongo.get_db().code_snippets.find(
        {"user_id": USER_ID, "file_name": file_name}).sort("version", 1)
    return [d.get("updated_at") for d in docs]


def _expected(versions=3):
    return [STAMP + timedelta(minutes=v) for v in range(1, versions + 1)]


def test_toggle_favorite_route_does_not_touch_updated_at(wired_mongo):
    client, ids = _seed(wired_mongo)

    resp = client.post(f"/api/favorite/toggle/{ids[-1]}")
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]

    assert _stamps(wired_mongo) == _expected(), _stamps(wired_mongo)
    docs = list(wired_mongo.get_db().code_snippets.find({"user_id": USER_ID}))
    assert any(d.get("favorited_at") for d in docs), "הפעולה עצמה לא תועדה"


def test_bulk_favorite_routes_do_not_touch_updated_at(wired_mongo):
    client, ids = _seed(wired_mongo)
    payload = {"file_ids": [str(i) for i in ids]}

    assert client.post("/api/files/bulk-favorite", json=payload).status_code == 200
    assert _stamps(wired_mongo) == _expected(), "סימון מרובה שינה את updated_at"

    assert client.post("/api/files/bulk-unfavorite", json=payload).status_code == 200
    assert _stamps(wired_mongo) == _expected(), "ביטול סימון מרובה שינה את updated_at"


def test_move_to_trash_route_does_not_touch_updated_at(wired_mongo):
    client, ids = _seed(wired_mongo)

    resp = client.post(f"/api/file/{ids[-1]}/trash")
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]

    assert _stamps(wired_mongo) == _expected(), "מחיקה רכה שינתה את updated_at"
    docs = list(wired_mongo.get_db().code_snippets.find({"user_id": USER_ID}))
    assert all(d.get("deleted_at") for d in docs), "המחיקה עצמה לא תועדה"
    assert all(d.get("is_active") is False for d in docs)


def test_restore_from_trash_route_does_not_touch_updated_at(wired_mongo):
    client, ids = _seed(wired_mongo, is_active=False,
                        deleted_at=STAMP + timedelta(days=1))

    resp = client.post(f"/api/trash/{ids[-1]}/restore")
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]

    assert _stamps(wired_mongo) == _expected(), "שחזור מהסל שינה את updated_at"


def test_bulk_delete_route_does_not_touch_updated_at(wired_mongo):
    client, ids = _seed(wired_mongo)

    resp = client.post("/api/files/bulk-delete", json={"file_ids": [str(i) for i in ids]})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]

    assert _stamps(wired_mongo) == _expected(), "מחיקה מרובה שינתה את updated_at"
    docs = list(wired_mongo.get_db().code_snippets.find({"user_id": USER_ID}))
    assert all(d.get("deleted_at") for d in docs), "המחיקה עצמה לא תועדה"


def test_a_fresh_file_is_not_marked_edited_after_a_metadata_route(wired_mongo):
    """ההבטחה של ה-PR, במסלול שהדפדפן עובר בו.

    קובץ בגרסה אחת שמעולם לא נערך: ``created_at == updated_at``, ולכן
    ``file_was_edited`` היא ``False`` והתא "עודכן" מוסתר. סימון מועדף אינו
    אמור לשנות את זה.
    """
    from file_dates import file_was_edited

    db = wired_mongo.get_db()
    db.code_snippets.delete_many({})
    oid = ObjectId()
    db.code_snippets.insert_one({
        "_id": oid, "user_id": USER_ID, "file_name": "fresh.md",
        "code": "# טרי", "programming_language": "markdown", "version": 1,
        "is_active": True, "created_at": STAMP, "updated_at": STAMP,
    })
    client = wired_mongo.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = USER_ID
        sess["user_data"] = {"id": USER_ID, "first_name": "בדיקה",
                             "is_admin": False, "is_premium": False}

    assert client.post(f"/api/favorite/toggle/{oid}").status_code == 200

    doc = db.code_snippets.find_one({"_id": oid})
    assert file_was_edited(doc.get("created_at"), doc.get("updated_at")) is False, (
        doc.get("created_at"), doc.get("updated_at"))
