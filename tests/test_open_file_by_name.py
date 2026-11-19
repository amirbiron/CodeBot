"""פתיחת קובץ לפי השם — ``open_file_by_name`` (הפניה) ו-``api_resolve_file_by_name`` (JSON).

כרטיס באוסף מחזיק את **שם** הקובץ. הקישור שלו (``openFileLinkAttrs`` ב-``collections.js``) והכפתור 🌐
(``openDirectView``) פותחים את ``open_file_by_name`` בלשונית חדשה, והשרת מפנה משם לגרסה הפעילה האחרונה.
שני הראוטים מכריעים "קיים / בסל / לא קיים" באותה פונקציה — ``_resolve_file_doc_by_name``.

הבדיקות עוברות דרך ה-HTTP client, עם הדמה המשותפת (``tests/_fake_mongo.py``) — מוסכמת הריפו, כמו
``tests/test_card_preview_latest_version.py``. הנתיבים נגזרים מהראוטים (``url_for``) ולא ממחרוזות.
את הלחיצה בדפדפן בודק ``tests/test_open_file_in_new_tab_browser.py``.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from bson import ObjectId
from flask import url_for
from pymongo.errors import PyMongoError

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _fake_mongo import FakeDB

from webapp import app as webapp_app

USER_ID = 7341
OTHER_USER_ID = 9922
FILE_NAME = "מדריך RTL.md"

OLD_ID = ObjectId("0123456789abcdef01230001")
NEW_ID = ObjectId("0123456789abcdef01230002")


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


def _url(endpoint, **values):
    with webapp_app.app.test_request_context():
        return url_for(endpoint, **values)


def _save(db, oid, version, *, active=True, user_id=USER_ID, name=FILE_NAME, trashed_at=None):
    doc = {
        "_id": oid,
        "user_id": user_id,
        "file_name": name,
        "programming_language": "markdown",
        "code": f"# v{version}\n",
        "version": version,
        "is_active": active,
    }
    if trashed_at is not None:
        doc["deleted_at"] = trashed_at
    db["code_snippets"].insert_one(doc)


def _two_versions(db, *, active=True):
    _save(db, OLD_ID, 1, active=active)
    _save(db, NEW_ID, 2, active=active)


def _location_path(resp):
    return urlsplit(resp.headers["Location"]).path


# ------------------------------------------------------------------ ההפניה: open_file_by_name


def test_the_route_is_not_swallowed_by_the_file_id_route():
    """``/file/by-name`` ו-``/file/<file_id>`` חולקים קידומת. אם הכתובת הייתה נתפסת כמזהה קובץ,
    הקישורים באוספים היו מקבלים 404 של "הקובץ by-name לא קיים"."""
    adapter = webapp_app.app.url_map.bind("localhost")
    assert adapter.match(_url("open_file_by_name"))[0] == "open_file_by_name"


def test_a_name_opens_the_latest_active_version(db, client):
    _two_versions(db)

    resp = client.get(_url("open_file_by_name", name=FILE_NAME))

    assert resp.status_code == 302
    assert _location_path(resp) == _url("view_file", file_id=str(NEW_ID))


@pytest.mark.parametrize("view, endpoint", [("md", "md_preview"), ("html", "html_preview"), ("svg", "svg_preview")])
def test_a_direct_view_opens_that_view_of_the_latest_version(db, client, view, endpoint):
    """הכתובות שה-🌐 פתח עד היום (``/md/``, ``/html/``, ``/svg/`` ב-``collections.js``) — עכשיו דרך ההפניה."""
    _two_versions(db)

    resp = client.get(_url("open_file_by_name", name=FILE_NAME, view=view))

    assert resp.status_code == 302
    assert _location_path(resp) == _url(endpoint, file_id=str(NEW_ID))


@pytest.mark.parametrize("view", [None, "html"])
def test_a_file_in_the_recycle_bin_opens_the_file_page_with_its_banner(db, client, view):
    """בסל — לעמוד הקובץ, גם כשביקשו תצוגה: הבאנר "הקובץ נמצא בסל המיחזור" נמצא שם, ולא בתצוגת ה-HTML."""
    _two_versions(db, active=False)

    resp = client.get(_url("open_file_by_name", name=FILE_NAME, view=view))

    assert resp.status_code == 302
    assert _location_path(resp) == _url("view_file", file_id=str(NEW_ID))


def test_a_name_with_no_file_is_404(db, client):
    _save(db, OLD_ID, 1, name="other.md")

    resp = client.get(_url("open_file_by_name", name=FILE_NAME))

    assert resp.status_code == 404


def test_another_users_file_is_404(db, client):
    _save(db, OLD_ID, 1, user_id=OTHER_USER_ID)

    resp = client.get(_url("open_file_by_name", name=FILE_NAME))

    assert resp.status_code == 404


@pytest.mark.parametrize("query", [{}, {"name": "   "}, {"name": FILE_NAME, "view": "pdf"}])
def test_a_missing_name_or_an_unknown_view_is_400(db, client, query):
    _two_versions(db)

    resp = client.get(_url("open_file_by_name", **query))

    assert resp.status_code == 400
    assert "Location" not in resp.headers


def test_a_failed_lookup_is_500_and_never_a_redirect(monkeypatch, db, client):
    """שגיאת מסד אינה "לא נמצא" ואינה הפניה למזהה כלשהו."""
    _two_versions(db)

    def _broken(*_a, **_k):
        raise PyMongoError("simulated failure")

    monkeypatch.setattr(webapp_app, "_latest_active_version_doc", _broken)

    resp = client.get(_url("open_file_by_name", name=FILE_NAME))

    assert resp.status_code == 500
    assert "Location" not in resp.headers


def test_the_redirect_is_not_stored_in_any_cache(db, client):
    """ההפניה מצביעה על הגרסה של **עכשיו**. הפניה שנשמרה במטמון הייתה פותחת אחרי שמירה חדשה את הגרסה הישנה.
    הכותרת באה מ-``_disable_html_cache`` (גוף ההפניה הוא ``text/html``), ולא מהראוט."""
    _two_versions(db)

    resp = client.get(_url("open_file_by_name", name=FILE_NAME))

    assert resp.status_code == 302
    assert "no-store" in resp.headers.get("Cache-Control", "")


def test_a_logged_out_user_goes_to_login_and_comes_back_to_the_same_link(db):
    _two_versions(db)
    link = _url("open_file_by_name", name=FILE_NAME)

    resp = webapp_app.app.test_client().get(link)

    assert resp.status_code == 302
    location = urlsplit(resp.headers["Location"])
    assert location.path == _url("auth.login")
    assert urlsplit(parse_qs(location.query)["next"][0]).path == urlsplit(link).path
    assert parse_qs(urlsplit(parse_qs(location.query)["next"][0]).query)["name"] == [FILE_NAME]


# --------------------------------------------------------------- ה-JSON: api_resolve_file_by_name


def test_the_api_answers_the_latest_active_version(db, client):
    _two_versions(db)

    resp = client.get(_url("api_resolve_file_by_name", name=FILE_NAME))

    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "id": str(NEW_ID), "file_name": FILE_NAME, "language": "markdown"}


def test_the_api_reports_a_file_in_the_recycle_bin(db, client):
    _two_versions(db, active=False)

    resp = client.get(_url("api_resolve_file_by_name", name=FILE_NAME))

    data = resp.get_json()
    assert data["ok"] is False
    assert data["error"] == "in_recycle_bin"
    assert data["file_name"] == FILE_NAME


def test_the_api_reports_a_missing_file(db, client):
    resp = client.get(_url("api_resolve_file_by_name", name=FILE_NAME))

    assert resp.get_json() == {"ok": False, "error": "not_found"}


def test_a_failed_api_lookup_is_an_error_and_not_a_missing_file(monkeypatch, db, client):
    """עד נובמבר 2026 שגיאת המסד נבלעה ל-``not_found``, וטופס השמירה (``resolveExisting`` ב-
    ``file-form-manager.js``) שמר בלי לשאול אם לדרוס קובץ קיים. תשובת שגיאה מביאה אותו לשאלה
    "לא הצלחנו לבדוק"."""
    _two_versions(db)

    def _broken(*_a, **_k):
        raise PyMongoError("simulated failure")

    monkeypatch.setattr(webapp_app, "_latest_active_version_doc", _broken)

    resp = client.get(_url("api_resolve_file_by_name", name=FILE_NAME))

    assert resp.status_code == 500
    assert resp.get_json() == {"ok": False, "error": "internal_error"}


def test_the_lookups_do_not_pull_the_file_content(db, client):
    """המזהה והמטא-דאטה בלבד: שם הקובץ אינו מצדיק משיכת התוכן (``projection`` של ``_resolve_file_doc_by_name``)."""
    _two_versions(db)
    seen: list = []
    original = db["code_snippets"].find_one

    def _spy(q=None, projection=None, *a, **k):
        seen.append(projection)
        return original(q, projection, *a, **k)

    db["code_snippets"].find_one = _spy

    client.get(_url("api_resolve_file_by_name", name=FILE_NAME))
    client.get(_url("open_file_by_name", name=FILE_NAME))

    assert len(seen) == 2
    assert all(p and "code" not in p and all(v for v in p.values()) for p in seen), seen
