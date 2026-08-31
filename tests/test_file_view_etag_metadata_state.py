"""ה-ETag של ``/file/<id>`` רגיש למצב מועדף ונעוץ.

**למה זה קיים.** ``view_file.html`` מרנדר את המצב הזה **לתוך ה-HTML** —
תוויות הכפתורים, ``aria-pressed`` ו-``data-is-pinned``. אם הוא אינו נכנס
לוולידטור, החלפת המצב אינה משנה את ה-ETag, השרת מחזיר 304, והדפדפן מציג
כוכב תקוע.

עד עכשיו זה עבד **במקרה**: ``toggle_favorite`` ו-``toggle_pin`` חתמו
``updated_at``, וה-ETag נגזר ממנו. אבל ``updated_at`` משמעותו "התוכן
נערך" — ``file_was_edited`` נגזרת ממנה כדי להחליט אם להציג "עודכן" —
ולכן החתימה הזו הוסרה. בלי הוספת המצב לוולידטור, ההסרה הייתה מחליפה באג
תאריך בבאג קאש.

זו אותה החלטה שכבר התקבלה עבור ``theme`` ועבור גופן הפתקים: כל ערך
שמרונדר לתוך העמוד שייך לוולידטור.
"""

import pytest
from bson import ObjectId

pytest.importorskip("flask")

USER_ID = 7


def _seed(wired_mongo, *, is_favorite=False, is_pinned=False):
    db = wired_mongo.get_db()
    file_id = ObjectId()
    db.code_snippets.delete_many({})
    db.code_snippets.insert_one({
        "_id": file_id,
        "user_id": USER_ID,
        "file_name": "amir.md",
        "code": "# כותרת\n\nטקסט",
        "programming_language": "markdown",
        "version": 1,
        "is_active": True,
        "is_favorite": is_favorite,
        "is_pinned": is_pinned,
    })

    client = wired_mongo.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = USER_ID
        # ``view_file`` מרנדר את ``session['user_data']`` ישירות, ולכן הוא
        # חובה ולא נוחות — בלעדיו הראוט נופל ב-500 לפני ה-ETag.
        sess["user_data"] = {"id": USER_ID, "first_name": "בדיקה",
                             "is_admin": False, "is_premium": False}
    return client, str(file_id)


def test_the_etag_differs_between_favorite_states(wired_mongo):
    client, file_id = _seed(wired_mongo, is_favorite=False)
    etag_off = client.get(f"/file/{file_id}").headers.get("ETag")
    assert etag_off, "העמוד אינו מגיש ETag כלל"

    wired_mongo.get_db().code_snippets.update_one(
        {"_id": ObjectId(file_id)}, {"$set": {"is_favorite": True}})
    etag_on = client.get(f"/file/{file_id}").headers.get("ETag")

    assert etag_off != etag_on, f"אותו ETag לשני מצבי מועדף: {etag_off}"


def test_the_etag_differs_between_pinned_states(wired_mongo):
    client, file_id = _seed(wired_mongo, is_pinned=False)
    etag_off = client.get(f"/file/{file_id}").headers.get("ETag")
    assert etag_off

    wired_mongo.get_db().code_snippets.update_one(
        {"_id": ObjectId(file_id)}, {"$set": {"is_pinned": True}})
    etag_on = client.get(f"/file/{file_id}").headers.get("ETag")

    assert etag_off != etag_on, f"אותו ETag לשני מצבי נעיצה: {etag_off}"


def test_a_changed_favorite_returns_a_fresh_body_and_not_304(wired_mongo):
    """**המסלול שהדפדפן עובר בפועל**, ולא השוואת מחרוזות.

    קודם מוודאים שהוולידטור בכלל עובד (304 כשכלום לא השתנה), כדי שה-200
    שאחריו יהיה ראיה ולא מקריות.

    שימו לב ש-``updated_at`` **אינו** משתנה כאן — זו בדיוק הנקודה: סימון
    מועדף אינו עריכה, ולכן הרעננות חייבת לנבוע מהמצב עצמו.
    """
    client, file_id = _seed(wired_mongo, is_favorite=False)
    etag = client.get(f"/file/{file_id}").headers["ETag"]

    unchanged = client.get(f"/file/{file_id}", headers={"If-None-Match": etag})
    assert unchanged.status_code == 304, "הוולידטור אינו עובד כלל"

    wired_mongo.get_db().code_snippets.update_one(
        {"_id": ObjectId(file_id)}, {"$set": {"is_favorite": True}})

    after = client.get(f"/file/{file_id}", headers={"If-None-Match": etag})
    assert after.status_code == 200, "הוחזר 304 עם מצב המועדף הישן"
    assert "הסר ממועדפים" in after.get_data(as_text=True)


def test_if_modified_since_alone_does_not_serve_a_stale_state(wired_mongo):
    """הוולידטור השני: ``Last-Modified`` לבדו.

    ``If-None-Match`` גובר לפי RFC 7232 §3.3, ולכן דפדפן ששמר את שני
    הוולידטורים מוגן על ידי ה-ETag. אבל לקוח ששולח **רק**
    ``If-Modified-Since`` — ``curl -z``, או דפדפן שאיבד את ה-ETag — נשען
    על התאריך בלבד. כיוון שסימון מועדף אינו נוגע ב-``updated_at``, התאריך
    חייב להיגזר גם מ-``favorited_at`` ו-``pinned_at``.
    """
    client, file_id = _seed(wired_mongo, is_favorite=False)
    first = client.get(f"/file/{file_id}")
    last_modified = first.headers.get("Last-Modified")
    assert last_modified, "העמוד אינו מגיש Last-Modified כלל"

    unchanged = client.get(f"/file/{file_id}", headers={"If-Modified-Since": last_modified})
    assert unchanged.status_code == 304, "הוולידטור אינו עובד כלל"

    # סימון מועדף **אחרי** ה-Last-Modified שנמסר, בלי לגעת ב-updated_at
    from datetime import datetime, timedelta, timezone
    wired_mongo.get_db().code_snippets.update_one(
        {"_id": ObjectId(file_id)},
        {"$set": {"is_favorite": True,
                  "favorited_at": datetime.now(timezone.utc) + timedelta(seconds=5)}},
    )

    after = client.get(f"/file/{file_id}", headers={"If-Modified-Since": last_modified})
    assert after.status_code == 200, "הוחזר 304 עם מצב המועדף הישן"
    assert "הסר ממועדפים" in after.get_data(as_text=True)
