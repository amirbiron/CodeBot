"""התצוגה המקדימה בכרטיס וההעתקה ממנה — של הגרסה האחרונה של הקובץ, ולא של המזהה שבכרטיס.

כל שמירה של קובץ רגיל יוצרת מסמך חדש עם ``_id`` חדש, והכרטיס בעמוד הקבצים מחזיק את
המזהה של הגרסה שהייתה האחרונה כשהעמוד נטען. ``file_preview`` ו-``api_file_content``
משתמשים במזהה רק כדי לדעת על איזה קובץ מדובר (``_latest_file_doc_by_id`` ב-
``webapp/app.py``), ולכן קובץ שנשמרה לו גרסה חדשה מאז שהעמוד נטען מוצג ומועתק בגרסה
החדשה.

הבדיקות עוברות דרך ה-HTTP client, כמו ``card-preview.js``. מוסכמת הריפו: דמה בעבודת
יד (``tests/_fake_mongo.py``), כי ``wired_mongo`` מדלג ב-CI. את הזרימה בדפדפן, מול
מונגו אמיתי, בודק ``tests/test_card_preview_copy_browser.py``.
"""

from __future__ import annotations

import pytest
from bson import ObjectId
from pymongo.errors import PyMongoError

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _fake_mongo import FakeDB

from webapp import app as webapp_app

USER_ID = 7341
OTHER_USER_ID = 9922
FILE_NAME = "notes.py"

OLD_ID = ObjectId("0123456789abcdef01230001")
NEW_ID = ObjectId("0123456789abcdef01230002")

OLD_CODE = "old_marker = 'v1'\n"

#: הגרסה החדשה, בכוונה עם כל מה שמעבר דרך צובע התחביר משנה: הזחה בשורה הראשונה,
#: סוף שורה של Windows, עברית, ושורות ריקות בסוף — ויותר שורות ממה שהתצוגה מציגה.
NEW_CODE = (
    "    new_marker = 'v2'\r\n"
    + "".join(f"line_{i:02d} = 'שורה {i}'\n" for i in range(1, 40))
    + "\n\n"
)


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(webapp_app, "get_db", lambda: fake)
    return fake


@pytest.fixture
def client():
    c = webapp_app.app.test_client()
    with c.session_transaction() as sess:
        sess["user_id"] = USER_ID
        sess["user_data"] = {"id": USER_ID, "first_name": "Test", "is_admin": False, "is_premium": False}
    return c


def _save(db, oid, version, code, *, active=True, user_id=USER_ID, name=FILE_NAME):
    doc = {
        "_id": oid,
        "user_id": user_id,
        "file_name": name,
        "programming_language": "python",
        "code": code,
        "version": version,
    }
    if active is not None:
        doc["is_active"] = active
    db["code_snippets"].insert_one(doc)


def _two_versions(db, *, active=True):
    _save(db, OLD_ID, 1, OLD_CODE, active=active)
    _save(db, NEW_ID, 2, NEW_CODE, active=active)


def test_the_copy_from_a_card_with_an_old_id_returns_the_latest_version_whole(db, client):
    _two_versions(db)

    resp = client.get(f"/api/file/{OLD_ID}/content")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["code"] == NEW_CODE  # תו בתו: הזחה, CRLF, עברית ושורות ריקות בסוף
    assert data["version"] == 2


def test_the_copy_response_is_not_stored_in_any_cache(db, client):
    """מה שנשמר במטמון הוא מה שהיה שמור **אז** — בדיוק מה שההעתקה לא אמורה להחזיר."""
    _two_versions(db)

    resp = client.get(f"/api/file/{NEW_ID}/content")

    assert resp.status_code == 200
    assert resp.headers.get("Cache-Control") == "no-store"


def test_the_preview_from_a_card_with_an_old_id_shows_the_latest_version_and_says_which(db, client):
    _two_versions(db)

    resp = client.get(f"/api/file/{OLD_ID}/preview")

    assert resp.status_code == 200
    data = resp.get_json()
    assert "new_marker" in data["highlighted_html"]
    assert "old_marker" not in data["highlighted_html"]
    assert data["version"] == 2
    assert data["file_id"] == str(NEW_ID)


def test_a_file_in_the_recycle_bin_is_reported_instead_of_shown_or_copied(db, client):
    _two_versions(db, active=False)

    preview = client.get(f"/api/file/{NEW_ID}/preview")
    content = client.get(f"/api/file/{NEW_ID}/content")

    assert preview.status_code == 404
    assert preview.get_json()["error"] == "in_recycle_bin"
    assert content.status_code == 404
    assert content.get_json()["error"] == "in_recycle_bin"


def test_another_users_file_is_not_found(db, client):
    _save(db, OLD_ID, 1, OLD_CODE, user_id=OTHER_USER_ID)

    preview = client.get(f"/api/file/{OLD_ID}/preview")
    content = client.get(f"/api/file/{OLD_ID}/content")

    assert preview.status_code == 404
    assert preview.get_json()["error"] == "not_found"
    assert content.status_code == 404
    assert content.get_json()["error"] == "not_found"


def test_a_document_without_is_active_is_the_file_itself(db, client):
    """מסמך ישן בלי השדה ``is_active`` אינו בסל, ואין גרסה פעילה אחרת בשמו."""
    _save(db, OLD_ID, 1, OLD_CODE, active=None)

    resp = client.get(f"/api/file/{OLD_ID}/content")

    assert resp.status_code == 200
    assert resp.get_json()["code"] == OLD_CODE


def test_a_large_file_is_copied_from_its_own_document_without_a_version(db, client):
    """``large_files`` נשמר במקום, בלי גרסאות — המסמך שבמזהה הוא הקובץ."""
    db["large_files"].insert_one({
        "_id": OLD_ID,
        "user_id": USER_ID,
        "file_name": "big.log",
        "programming_language": "text",
        "content": NEW_CODE,
        "is_active": True,
    })

    resp = client.get(f"/api/file/{OLD_ID}/content")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["code"] == NEW_CODE
    assert data["version"] is None


def test_no_database_connection_is_503_and_not_a_missing_file(monkeypatch, client):
    """``get_db`` מחזיר ``None`` כשאין חיבור — וזה לא "הקובץ לא נמצא"."""
    monkeypatch.setattr(webapp_app, "get_db", lambda: None)

    preview = client.get(f"/api/file/{OLD_ID}/preview")
    content = client.get(f"/api/file/{OLD_ID}/content")

    assert preview.status_code == 503
    assert preview.get_json()["error"] == "service_unavailable"
    assert content.status_code == 503
    assert content.get_json()["error"] == "service_unavailable"


def test_a_failed_latest_version_lookup_is_an_error_and_never_the_old_version(monkeypatch, db, client):
    """הנפילה-לאחור האסורה: להחזיר את המסמך שבמזהה כשהשאלה "מה האחרונה" נכשלה."""
    _two_versions(db)

    def _broken(*_a, **_k):
        raise PyMongoError("simulated failure")

    monkeypatch.setattr(webapp_app, "_latest_active_version_doc", _broken)

    preview = client.get(f"/api/file/{OLD_ID}/preview")
    content = client.get(f"/api/file/{OLD_ID}/content")

    assert preview.status_code == 500
    assert "old_marker" not in preview.get_data(as_text=True)
    assert content.status_code == 500
    assert content.get_json() == {"ok": False, "error": "db_error"}


def test_the_copy_requires_a_logged_in_user(db):
    _two_versions(db)

    resp = webapp_app.app.test_client().get(f"/api/file/{NEW_ID}/content")

    assert resp.status_code == 401
    assert "code" not in (resp.get_json() or {})
