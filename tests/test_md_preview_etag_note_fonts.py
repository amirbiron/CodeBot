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


def test_the_etag_differs_between_font_sizes(wired_mongo):
    """אותה מלכודת, על ההעדפה השנייה שמרונדרת לתוך אותו ``head``.

    גודל הטקסט נוסף אחרי כתב היד, והוא נופל לאותו כשל בדיוק אם הוא
    נשאר מחוץ לוולידטור.
    """
    client, file_id = _seed(wired_mongo, "000")
    etag_normal = client.get(f"/md/{file_id}").headers.get("ETag")

    wired_mongo.get_db().users.update_one(
        {"user_id": 7}, {"$set": {"ui_prefs.note_font_size": "lg"}})
    etag_large = client.get(f"/md/{file_id}").headers.get("ETag")

    assert etag_normal and etag_normal != etag_large, f"אותו ETag לשני גדלים: {etag_normal}"


def test_a_changed_size_returns_a_fresh_body_and_not_304(wired_mongo):
    """המסלול שהמשתמש עובר: משנה גודל בהגדרות, וחוזר לעמוד ה-Markdown.

    כמו אצל שכנתה — קודם מוודאים שהוולידטור בכלל עובד, כדי שה-200
    שאחריו יהיה ראיה.
    """
    client, file_id = _seed(wired_mongo, "000")
    etag = client.get(f"/md/{file_id}").headers["ETag"]

    unchanged = client.get(f"/md/{file_id}", headers={"If-None-Match": etag})
    assert unchanged.status_code == 304, "הוולידטור אינו עובד כלל"

    wired_mongo.get_db().users.update_one(
        {"user_id": 7}, {"$set": {"ui_prefs.note_font_size": "mid"}})

    after = client.get(f"/md/{file_id}", headers={"If-None-Match": etag})
    assert after.status_code == 200, "הוחזר 304 עם הגודל הישן"
    assert 'STICKY_NOTE_FONT_SIZE = "mid"' in after.get_data(as_text=True)


def test_the_board_surface_does_not_carry_the_settings_size(wired_mongo):
    """עמוד ה-Markdown כן, הלוח לא — וזו החלטה שצריך לאכוף.

    שתי החלטות על אותה מחלקה היו נאבקות, ולכן התבנית המשותפת מרנדרת
    ריק בלוחות. הבדיקה עוברת דרך העמוד המרונדר, ולא דרך התבנית.
    """
    client, file_id = _seed(wired_mongo, "000")
    wired_mongo.get_db().users.update_one(
        {"user_id": 7}, {"$set": {"ui_prefs.note_font_size": "lg"}})

    md_html = client.get(f"/md/{file_id}").get_data(as_text=True)
    assert 'STICKY_NOTE_FONT_SIZE = "lg"' in md_html, "העמוד לא קיבל את הגודל"

    board = client.get("/boards/507f1f77bcf86cd799439011")
    assert board.status_code == 200
    assert 'STICKY_NOTE_FONT_SIZE = ""' in board.get_data(as_text=True), (
        "הלוח קיבל את הגודל מעמוד ההגדרות"
    )
