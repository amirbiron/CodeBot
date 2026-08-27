"""ה-ETag של ``/md/<id>`` רגיש לגופן הפתקים.

**למה זה קיים.** ``_note_fonts_head.html`` מרנדר את ההעדפה **לתוך
ה-HTML**. אם היא אינה נכנסת לוולידטור, שינוי ההגדרה אינו משנה את ה-ETag,
השרת מחזיר 304, והדפדפן מציג את העמוד הישן עם הדגל הישן.

המסלול הזה **אינו תלוי בקאש של Redis**: הוא רץ ב-``md_preview`` לפני
בלוק הקאש ובלי קשר ל-``should_cache``. לכן הוא חי בכל תצורה.

``theme`` כבר נמצא ב-ETag מאותה סיבה בדיוק. זו אותה החלטה, על הערך השני
שמרונדר פר-משתמש.
"""

import pytest
from bson import ObjectId

pytest.importorskip("flask")

from tests.conftest import requires_test_mongo

pytestmark = requires_test_mongo


def _seed(wired_mongo, bits="000"):
    from webapp.app import _decode_note_fonts

    db = wired_mongo.get_db()
    db.users.delete_many({"user_id": 7})
    db.users.insert_one({"user_id": 7, "ui_prefs": {
        "note_fonts": _decode_note_fonts(bits)}})

    file_id = ObjectId()
    db.code_snippets.delete_many({})
    db.code_snippets.insert_one({
        "_id": file_id,
        "user_id": 7,
        "file_name": "README.md",
        "code": "# כותרת\n\nטקסט",
        "programming_language": "markdown",
        "version": 1,
        "is_active": True,
    })

    client = wired_mongo.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 7
    return client, str(file_id)


def test_the_etag_differs_between_font_settings(wired_mongo):
    client, file_id = _seed(wired_mongo, "000")
    etag_off = client.get(f"/md/{file_id}").headers.get("ETag")
    assert etag_off, "העמוד אינו מגיש ETag כלל"

    wired_mongo.get_db().users.update_one(
        {"user_id": 7}, {"$set": {"ui_prefs.note_fonts.md": True}})
    etag_on = client.get(f"/md/{file_id}").headers.get("ETag")

    assert etag_off != etag_on, f"אותו ETag לשני מצבים: {etag_off}"


def test_a_changed_setting_returns_a_fresh_body_and_not_304(wired_mongo):
    """**המסלול שהמשתמש עובר בפועל**, ולא השוואת מחרוזות.

    הבדיקה מוודאת קודם שהוולידטור בכלל עובד (304 כשכלום לא השתנה),
    כדי שה-200 שאחריו יהיה ראיה ולא מקריות.
    """
    client, file_id = _seed(wired_mongo, "000")
    etag = client.get(f"/md/{file_id}").headers["ETag"]

    unchanged = client.get(f"/md/{file_id}", headers={"If-None-Match": etag})
    assert unchanged.status_code == 304, "הוולידטור אינו עובד כלל"

    wired_mongo.get_db().users.update_one(
        {"user_id": 7}, {"$set": {"ui_prefs.note_fonts.md": True}})

    after = client.get(f"/md/{file_id}", headers={"If-None-Match": etag})
    assert after.status_code == 200, "הוחזר 304 עם הדגל הישן"
    assert "STICKY_FONT_FROM_SETTINGS = true" in after.get_data(as_text=True)
