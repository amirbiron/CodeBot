"""עריכה בוובאפ, בדפדפן אמיתי: מה שנשמר הוא מה שהעורך החזיק.

**למה דפדפן ולא ``test_client``.** את ה-CRLF מוסיף הדפדפן עצמו, כשהוא מקודד את
הטופס (HTML Living Standard, סעיף 4.10.22.8), והעורך מסנכרן את התוכן ל-textarea
ב-JavaScript רגע לפני השליחה. ``tests/test_save_preserves_content_webapp.py``
מחקה את שני אלה; הטסט כאן מריץ אותם.

**בקרות בתוך המדידה:** לפני השליחה נקרא מהעורך מה הוא מחזיק (אחרת "נשמר" יכול
להיות גם תוכן שמעולם לא הוקלד), ואחריה נבדק שנוצרה גרסה חדשה.

ב-CI אין דפדפן, ולכן הטסט מדולג שם (``chromium_executable`` ב-``tests/conftest.py``).
ה-DB הוא הדמה המשותפת: ``admin_live_server`` מריץ את הוובאפ בחוט באותו תהליך,
ולכן ``get_db`` שהוחלף תקף גם לבקשות של הדפדפן. תווי כיווניות כתובים רק
כ-escapes (H1).
"""

from __future__ import annotations

import pytest
from bson import ObjectId

pytest.importorskip("playwright")

from playwright.sync_api import sync_playwright  # noqa: E402

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _fake_mongo import FakeDB  # noqa: E402

#: ``admin_live_server`` בונה session למשתמש 1, ולכן הקבצים שלו.
USER_ID = 1
FILE_OID = ObjectId("0123456789abcdef0123beef")
RLM = "\u200f"

TYPED = (
    "גרסה" + RLM + " 2.0\n"
    'RLM = "\\u200f"\n'
    "שורה עם שבירה  \n"
    "\n\n"
)


@pytest.fixture
def db(monkeypatch):
    import webapp.app as webapp_app

    fake = FakeDB()
    existing = {
        "_id": FILE_OID,
        "user_id": USER_ID,
        "file_name": "browser.md",
        "programming_language": "markdown",
        "code": "before\n",
        "description": "",
        "tags": [],
        "version": 1,
        "is_active": True,
    }
    fake["code_snippets"].insert_one(dict(existing))
    monkeypatch.setattr(webapp_app, "get_db", lambda: fake)
    monkeypatch.setattr(
        webapp_app,
        "_get_user_any_file_by_id",
        lambda db_ref, user_id, file_id: (dict(existing), "regular"),
    )
    return fake


def test_the_saved_version_is_exactly_what_the_editor_held(db, admin_live_server, chromium_executable):
    with sync_playwright() as pw:
        try:
            browser = (
                pw.chromium.launch(executable_path=chromium_executable)
                if chromium_executable
                else pw.chromium.launch()
            )
        except Exception as exc:  # pragma: no cover - תלוי בסביבה
            pytest.skip(f"אין Chromium זמין: {exc}")

        with browser, browser.new_context(viewport={"width": 1280, "height": 900}) as context:
            context.add_cookies([{
                "name": "session", "value": admin_live_server.session_cookie,
                "domain": "127.0.0.1", "path": "/",
            }])
            page = context.new_page()
            page.add_init_script(
                "try{localStorage.setItem('welcomeModalSeen','1');"
                "localStorage.setItem('onboarding_completed','1');}catch(e){}"
            )
            page.goto(f"{admin_live_server.base_url}/edit/{FILE_OID}", wait_until="domcontentloaded")
            page.wait_for_function(
                "window.editorManager && typeof window.editorManager.setEditorContent === 'function'",
                timeout=15000,
            )
            page.evaluate("v => window.editorManager.setEditorContent(v)", TYPED)
            # בקרה: העורך באמת מחזיק את מה שהוקלד.
            assert page.evaluate("() => window.editorManager.getEditorContent()") == TYPED

            with page.expect_navigation(timeout=15000):
                page.evaluate("() => document.querySelector('#editForm button[type=submit]').click()")

    versions = [d for d in db["code_snippets"].docs if d.get("file_name") == "browser.md"]
    newest = max(versions, key=lambda d: int(d.get("version", 0) or 0))
    assert newest["version"] == 2, "ציפינו לגרסה חדשה"
    assert "\r" not in newest["code"], "ה-CRLF של שליחת הטופס לא פוענח"
    assert newest["code"] == TYPED
