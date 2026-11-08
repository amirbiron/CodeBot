"""‏``X-Content-Type-Options: nosniff`` על התשובות של הוובאפ — ``_add_nosniff`` ב-``webapp/app.py``.

**למה הכותרת קיימת.** בלעדיה הדפדפן מנחש את סוג התוכן, ו-Chromium מריץ כסקריפט טקסט שהוגש כ-``text/plain``
אם עמוד באתר טוען אותו ב-``<script src>``. ‏``/share/<id>/download`` מגיש בדיוק טקסט כזה — מה שבעל השיתוף כתב — ולכן
עמוד באתר עם ``script-src 'self'`` לא היה מוגן ממנו. מה שהדפדפן עושה עם הכותרת נמדד ב-``tests/test_nosniff_browser.py``;
כאן נבדק מה השרת שולח.

**מה נבדק:**

- הכותרת מגיעה לסוגי התשובות השונים: עמוד HTML, ‏JSON מ-blueprint, ‏404, ‏``/sw.js``, קבצים סטטיים (סקריפט, גיליון
  סגנון, גופן) והורדה של שיתוף.
- נתיב שקבע את הכותרת בעצמו (``raw_html``, ``raw_svg``) לא מקבל עותק שני — ``setdefault`` ולא השמה.
- **התנאי שבזכותו הכותרת בטוחה לכל האתר:** כל קובץ ``.js`` ו-``.css`` תחת ``webapp/static`` מוגש בסוג שהדפדפן
  מקבל תחת ``nosniff``. קובץ שיוגש בסוג אחר — סיומת חדשה שטבלת ה-``mimetypes`` לא מכירה, למשל — ייחסם בדפדפן
  בשקט, ולכן הוא מפיל את הטסט הזה.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import pytest
from bson import ObjectId

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _fake_mongo import FakeDB

from webapp import app as webapp_app

OWNER_ID = 7150
FILE_OID = ObjectId("0123456789abcdef0123ab07")
STATIC_DIR = Path(webapp_app.app.static_folder)

#: שני הסוגים ש-Flask מגיש לקובצי ``.js`` (לפי טבלת ``mimetypes`` של הפייתון ושל המערכת). שניהם בין סוגי
#: ה-JavaScript שהדפדפן מריץ תחת ``nosniff``; הרשימה כאן צרה מזו של הדפדפן בכוונה — סוג שלישי ידרוש בדיקה.
SCRIPT_TYPES = {"text/javascript", "application/javascript"}

#: סיומות של קובצי סקריפט. היום יש רק ``.js``; ‏``.mjs`` ו-``.cjs`` כאן כדי שקובץ כזה שיתווסף ייבדק גם הוא.
SCRIPT_SUFFIXES = (".js", ".mjs", ".cjs")


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(webapp_app, "get_db", lambda: fake)
    return fake


def _client_as(user_id: int | None):
    client = webapp_app.app.test_client()
    if user_id is not None:
        with client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["user_data"] = {"id": user_id, "first_name": "Test"}
    return client


def _share(db) -> str:
    """שיתוף שנוצר דרך הראוט, כמו בכפתור (``tests/test_public_share_page_actions.py``); מחזיר את מזהה השיתוף."""
    db["code_snippets"].insert_one({
        "_id": FILE_OID,
        "user_id": OWNER_ID,
        "file_name": "notes.txt",
        "code": "window.ran = true;\n",
        "programming_language": "text",
        "version": 1,
        "is_active": True,
    })
    resp = _client_as(OWNER_ID).post(f"/api/share/{FILE_OID}", json={"type": "temporary", "permanent": False})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return urlparse(resp.get_json()["url"]).path.rsplit("/", 1)[-1]


def _static_files(*suffixes: str) -> list[str]:
    return sorted(p.relative_to(STATIC_DIR).as_posix() for p in STATIC_DIR.rglob("*") if p.is_file() and p.suffix in suffixes)


@pytest.mark.parametrize(
    "path, status, content_type",
    [
        ("/", 200, "text/html"),
        ("/api/files", 401, "application/json"),
        ("/no-such-page-for-nosniff", 404, "text/html"),
        ("/sw.js", 200, "application/javascript"),
        ("/static/js/utils/styled-export-core.js", 200, None),
        ("/static/css/animations.css", 200, "text/css"),
        ("/static/" + _static_files(".woff2")[0], 200, "font/woff2"),
    ],
    ids=["html-page", "json-from-blueprint", "404", "service-worker", "static-script", "static-style", "static-font"],
)
def test_the_header_reaches_pages_api_errors_and_static_files(db, path, status, content_type):
    resp = _client_as(None).get(path)
    try:
        assert resp.status_code == status
        if content_type:
            assert resp.mimetype == content_type
        assert resp.headers.getlist("X-Content-Type-Options") == ["nosniff"]
    finally:
        resp.close()


def test_the_share_download_is_plain_text_with_nosniff(db):
    """ההורדה של שיתוף היא טקסט שבעל השיתוף כתב — התשובה שבשבילה הכותרת נוספה."""
    resp = _client_as(None).get(f"/share/{_share(db)}/download")

    assert resp.status_code == 200
    assert resp.mimetype == "text/plain"
    assert resp.get_data(as_text=True) == "window.ran = true;\n"
    assert resp.headers.getlist("X-Content-Type-Options") == ["nosniff"]


@pytest.mark.parametrize("route, file_name, code", [
    ("raw_html", "page.html", "<p>hi</p>"),
    ("raw_svg", "icon.svg", '<svg xmlns="http://www.w3.org/2000/svg"></svg>'),
])
def test_a_route_that_sets_the_header_itself_keeps_one_copy(monkeypatch, route, file_name, code):
    doc = {"_id": FILE_OID, "user_id": OWNER_ID, "file_name": file_name, "code": code, "is_active": True}
    monkeypatch.setattr(webapp_app, "get_db", lambda: object())
    monkeypatch.setattr(webapp_app, "_get_user_any_file_by_id", lambda db_ref, user_id, file_id: (doc, "regular"))

    resp = _client_as(OWNER_ID).get(f"/{route}/{FILE_OID}")

    assert resp.status_code == 200
    assert resp.headers.getlist("X-Content-Type-Options") == ["nosniff"]


def test_every_static_script_and_stylesheet_is_served_with_a_type_the_browser_accepts_under_nosniff():
    client = _client_as(None)
    wrong = []
    scripts = _static_files(*SCRIPT_SUFFIXES)
    styles = _static_files(".css")
    assert scripts and styles
    for rel in scripts + styles:
        resp = client.get(f"/static/{rel}")
        try:
            assert resp.status_code == 200, rel
            ok = resp.mimetype in SCRIPT_TYPES if rel in scripts else resp.mimetype == "text/css"
            if not ok:
                wrong.append((rel, resp.mimetype))
        finally:
            resp.close()
    assert wrong == []
