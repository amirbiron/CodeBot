"""חמשת מסלולי הכתיבה בוובאפ משמרים את "נוצר" — מול **מונגו אמיתי**.

הבדיקות ב-``test_created_at_inheritance_mongo`` מכסות את ``save_code_snippet``,
כלומר את מסלול ה-repository. אבל הוובאפ עוקף אותו: חמישה מקומות כותבים
``insert_one`` ישירות לאוסף, כל אחד עם ההיגיון שלו לירושה. מסלול שאין
עליו בדיקה יידרדר בשקט ברגע שמישהו יערוך את המילון שם.

הבדיקות מריצות את הראוטים **האמיתיים** דרך ``test_client`` מול מסד זמני,
ומאמתות בקריאה חוזרת מה-DB — לא לפי ערך ההחזרה של הראוט.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone

import pytest

from mongo_it import make_mongo_db_fixture, requires_mongo

pytestmark = requires_mongo

#: תחילית ייעודית לקובץ הזה — סורג המחיקה ב-``mongo_it`` נשען עליה.
mongo_db = make_mongo_db_fixture("codebot_created_web_it_")

USER_ID = 4242
ORIGIN = datetime(2024, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def client(mongo_db, monkeypatch):
    """‏test client מחובר, מעל אותו מסד שהבדיקה מכינה.

    ``get_db`` מוחלף ולא ``MongoClient``: כל חמשת המסלולים ניגשים למסד
    דרכו, ולכן זו נקודת ההזרקה היחידה שמכסה את כולם בלי לגעת בקוד.
    """
    import webapp.app as W

    monkeypatch.setattr(W, "get_db", lambda: mongo_db)
    W.app.config["TESTING"] = True
    c = W.app.test_client()
    with c.session_transaction() as sess:
        sess["user_id"] = USER_ID
        sess["user_data"] = {"id": USER_ID, "first_name": "t", "username": "t"}
    return c


def _seed(mongo_db, file_name: str, *, version: int = 1, created_at=ORIGIN, **extra):
    """גרסה קיימת עם "נוצר" ותיק — נקודת ההשוואה של כל בדיקה."""
    doc = {
        "user_id": USER_ID,
        "file_name": file_name,
        "code": "original",
        "programming_language": "python",
        "description": "",
        "tags": [],
        "version": version,
        "is_active": True,
        "created_at": created_at,
        "updated_at": created_at,
    }
    doc.update(extra)
    return mongo_db.code_snippets.insert_one(doc).inserted_id


def _latest(mongo_db, file_name: str):
    return mongo_db.code_snippets.find_one({"file_name": file_name}, sort=[("version", -1)])


def test_edit_route_keeps_created_at(client, mongo_db):
    """‏POST ל-``/edit/<id>`` יוצר גרסה חדשה עם ה"נוצר" של הקודמת."""
    file_id = _seed(mongo_db, "edit_me.py")

    resp = client.post(
        f"/edit/{file_id}",
        data={"code": "changed", "file_name": "edit_me.py", "language": "python",
              "description": "desc", "tags": "a,b"},
        follow_redirects=False,
    )
    assert resp.status_code in (200, 302), resp.status_code

    latest = _latest(mongo_db, "edit_me.py")
    assert latest["version"] == 2, "לא נוצרה גרסה חדשה — הבדיקה אינה בודקת כלום"
    assert latest["created_at"] == ORIGIN
    assert latest["updated_at"] > ORIGIN


def test_edit_route_falls_back_per_field_when_prev_lacks_created_at(client, mongo_db):
    """‏``prev`` קיים אך בלי ``created_at`` — הנפילה היא **לפי שדה**.

    ‏``file`` נטען לפי ה-id שבכתובת, ו-``prev`` לפי שם הקובץ עם
    ``version`` הגבוה ביותר — אלה שני מסמכים שונים. כשפותחים לעריכה id
    של גרסה ותיקה שיש בה ``created_at``, בעוד שהגרסה האחרונה בשם הזה
    כבר איבדה אותו, ``(prev or file).get(...)`` בוחר את ``prev`` (מילון
    לא-ריק), מקבל ``None``, ונופל ל-``now``. הנפילה לפי שדה מוצאת את
    התאריך ב-``file``.
    """
    old_id = mongo_db.code_snippets.insert_one({
        "user_id": USER_ID, "file_name": "twohop.py", "code": "v1",
        "programming_language": "python", "description": "", "tags": [],
        "version": 1, "is_active": True, "created_at": ORIGIN, "updated_at": ORIGIN,
    }).inserted_id
    # הגרסה האחרונה — ``prev`` — בלי ``created_at`` כלל
    mongo_db.code_snippets.insert_one({
        "user_id": USER_ID, "file_name": "twohop.py", "code": "v2",
        "programming_language": "python", "description": "", "tags": [],
        "version": 2, "is_active": True, "updated_at": ORIGIN + timedelta(days=1),
    })

    resp = client.post(
        f"/edit/{old_id}",
        data={"code": "v3", "file_name": "twohop.py", "language": "python",
              "description": "", "tags": ""},
    )
    assert resp.status_code in (200, 302)
    latest = _latest(mongo_db, "twohop.py")
    assert latest["version"] == 3, "לא נוצרה גרסה חדשה — הבדיקה אינה בודקת כלום"
    assert latest["created_at"] == ORIGIN


def test_edit_route_rename_inherits_from_the_edited_document(client, mongo_db):
    """שינוי שם: אין ``prev`` בשם החדש — התאריך בא מהמסמך שנערך.

    זה הענף שבו ``file`` הוא המקור היחיד. בלעדיו כל שינוי שם היה מאפס
    את "נוצר".
    """
    file_id = _seed(mongo_db, "before_rename.py")

    resp = client.post(
        f"/edit/{file_id}",
        data={"code": "renamed body", "file_name": "after_rename.py",
              "language": "python", "description": "", "tags": ""},
    )
    assert resp.status_code in (200, 302)
    latest = _latest(mongo_db, "after_rename.py")
    assert latest is not None, "שינוי השם לא יצר מסמך"
    assert latest["created_at"] == ORIGIN


def test_restore_route_keeps_created_at(client, mongo_db):
    """שחזור גרסה ישנה יוצר גרסה חדשה — ו"נוצר" נשאר של הקובץ."""
    _seed(mongo_db, "restore_me.py", version=1, created_at=ORIGIN)
    later = ORIGIN + timedelta(days=30)
    latest_id = _seed(mongo_db, "restore_me.py", version=2, created_at=ORIGIN,
                      updated_at=later, code="v2")

    resp = client.post(f"/api/file/{latest_id}/restore", json={"version": 1})
    assert resp.status_code == 200, resp.get_data(as_text=True)

    latest = _latest(mongo_db, "restore_me.py")
    assert latest["version"] == 3, "לא נוצרה גרסה משוחזרת"
    assert latest["code"] == "original", "לא שוחזר התוכן הישן"
    assert latest["created_at"] == ORIGIN


def test_upload_route_keeps_created_at(client, mongo_db):
    """העלאת קובץ בשם שכבר קיים — גרסה חדשה, "נוצר" ישן."""
    _seed(mongo_db, "uploaded.py")

    resp = client.post(
        "/upload",
        # שם השדה הוא ``code_file`` — כך הראוט קורא אותו
        data={"code_file": (io.BytesIO(b"print('new')"), "uploaded.py"),
              "file_name": "uploaded.py", "language": "python"},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code in (200, 302), resp.status_code

    latest = _latest(mongo_db, "uploaded.py")
    assert latest["version"] == 2, "ההעלאה לא יצרה גרסה חדשה"
    assert latest["created_at"] == ORIGIN


def test_shared_save_route_keeps_created_at(client, mongo_db, monkeypatch):
    """שמירת קובץ משותף על שם קיים — "נוצר" יורש מהגרסה הקיימת."""
    import webapp.app as W

    _seed(mongo_db, "shared_doc.md", programming_language="markdown")
    monkeypatch.setattr(
        W, "get_internal_share",
        lambda share_id: {"code": "# new content", "file_name": "shared_doc.md",
                          "language": "markdown", "description": "d"},
    )

    resp = client.post("/api/shared/save",
                       json={"share_id": "abc", "file_name": "shared_doc.md"})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert json.loads(resp.get_data(as_text=True)).get("ok") is True

    latest = _latest(mongo_db, "shared_doc.md")
    assert latest["version"] == 2
    assert latest["created_at"] == ORIGIN


def test_story_export_keeps_created_at(client, mongo_db):
    """ייצוא סיפור לקובץ ``.md`` קיים — גרסה חדשה עם "נוצר" ישן.

    נקראת הפונקציה עצמה ולא הראוט: היא הבעלים של הכתיבה, והראוט רק
    מספק לה סיפור. בדיקה דרך הראוט הייתה מוסיפה תלות בבניית הסיפור בלי
    להוסיף כיסוי ליחידה שנבדקת.
    """
    import webapp.app as W

    _seed(mongo_db, "story.md", programming_language="markdown")

    with W.app.test_request_context():
        result = W._persist_story_markdown_file(
            user_id=USER_ID, file_name="story.md", markdown="# updated story"
        )
    assert result, "הכתיבה לא דיווחה על הצלחה"

    latest = _latest(mongo_db, "story.md")
    assert latest["version"] == 2
    assert latest["created_at"] == ORIGIN


def test_updated_badge_shows_for_an_edit_within_the_same_minute(client, mongo_db):
    """קובץ שנערך **באותה דקה** שבה נוצר — "עודכן" חייב להופיע.

    ‏``format_datetime_display`` מעגל לדקות, ולכן השוואת המחרוזות
    המפורמטות שהייתה בתבנית הכריזה "מעולם לא נערך" על עריכה אמיתית
    והסתירה את השדה. ההכרעה עברה ל-``has_real_update`` שמשווה את
    ה-``datetime`` הגולמי, ו-``has_update`` מועבר לתבנית.
    """
    created = datetime(2024, 1, 1, 10, 30, 10, tzinfo=timezone.utc)
    edited = created.replace(second=50)
    file_id = _seed(mongo_db, "sameminute.py", created_at=created, updated_at=edited)

    html = client.get(f"/file/{file_id}").get_data(as_text=True)
    assert 'id="metaUpdatedItem"' in html, "פריט 'עודכן' לא מרונדר כלל"
    marker = html[html.index('id="metaUpdatedItem"'):]
    marker = marker[: marker.index(">")]
    assert "hidden" not in marker, '"עודכן" הוסתר למרות עריכה באותה דקה'


def test_updated_badge_hidden_when_the_file_was_never_edited(client, mongo_db):
    """הכיוון השני: בלי עריכה, "עודכן" הוא רעש ולא מוצג."""
    stamp = datetime(2024, 1, 1, 10, 30, 10, tzinfo=timezone.utc)
    file_id = _seed(mongo_db, "never_edited.py", created_at=stamp, updated_at=stamp)

    html = client.get(f"/file/{file_id}").get_data(as_text=True)
    marker = html[html.index('id="metaUpdatedItem"'):]
    marker = marker[: marker.index(">")]
    assert "hidden" in marker, '"עודכן" מוצג על קובץ שמעולם לא נערך'
