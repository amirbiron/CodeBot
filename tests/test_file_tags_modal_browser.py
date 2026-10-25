"""מודאל התגיות בעמוד הקובץ, בדפדפן אמיתי — המסלול שהמשתמש עובר.

**למה דפדפן ולא ``test_client``.** הרשימה שבראש העמוד נבנית מחדש ב-JS מתוך
``tags`` שבתשובה, ומ-``<template>`` שהתבנית מרנדרת; המכל הריק מוסתר רק אם
ה-CSS גובר על ``display: flex``; וה-304 שהדפדפן מקבל אחרי שינוי תגיות הוא
מה שהשאיר את התגיות הישנות על המסך. אף אחד מהם אינו נראה ב-HTML שהשרת
מחזיר. בדיקות השרת עצמו: ``tests/test_webapp_quick_update_tags.py``.

**ו-Escape.** מאזין המקלדת של העמוד מחזיר אחורה ב-Escape, והוא רץ לפני
מאזין המודאל — כך שסגירת מודאל ב-Escape גם עזבה את העמוד. נמדד ב-Chromium
על הקוד שלפני התיקון, במודאל התיאור.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from bson import ObjectId

pytest.importorskip("playwright")

from playwright.sync_api import sync_playwright  # noqa: E402

from _browser_harness import poll  # noqa: E402

#: ``admin_live_server`` בונה session למשתמש 1, ולכן הקבצים שלו.
USER_ID = 1
STAMP = datetime(2019, 3, 7, 9, 15, tzinfo=timezone.utc)

_BADGES_JS = "() => Array.from(document.querySelectorAll('#fileTagsList .badge')).map((b) => b.textContent.trim())"


@pytest.fixture
def file_id(wired_mongo):
    db = wired_mongo.get_db()
    db.code_snippets.delete_many({})
    db.large_files.delete_many({})
    oid = ObjectId()
    db.code_snippets.insert_one({
        "_id": oid, "user_id": USER_ID, "file_name": "demo.py",
        "code": "print('hi')\n", "programming_language": "python",
        "version": 1, "is_active": True, "created_at": STAMP, "updated_at": STAMP,
        "description": "קובץ הדגמה", "tags": ["Python", "repo:amirbiron/CodeBot"],
    })
    return str(oid)


@pytest.fixture
def browser_page(admin_live_server, chromium_executable):
    with sync_playwright() as pw:
        try:
            browser = (
                pw.chromium.launch(executable_path=chromium_executable)
                if chromium_executable
                else pw.chromium.launch()
            )
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"אין Chromium זמין: {exc}")

        with browser, browser.new_context(viewport={"width": 1280, "height": 900}) as context:
            context.add_cookies([{
                "name": "session", "value": admin_live_server.session_cookie,
                "domain": "127.0.0.1", "path": "/",
            }])
            yield context.new_page()


def _open_file(page, server, file_id):
    page.goto(f"{server.base_url}/file/{file_id}", wait_until="domcontentloaded")
    page.wait_for_selector("#fileActionsMenuButton")


def _open_modal(page, action, modal_id):
    page.click("#fileActionsMenuButton")
    page.click(f"[data-menu-action='{action}']")
    poll(page, f"() => !document.getElementById('{modal_id}').hidden", f"המודאל {modal_id} נפתח")


def test_the_modal_opens_with_the_current_tags(browser_page, admin_live_server, file_id):
    _open_file(browser_page, admin_live_server, file_id)
    _open_modal(browser_page, "tags", "editTagsModal")

    assert browser_page.input_value("#tagsModalInput") == "Python, repo:amirbiron/CodeBot"


def test_saving_shows_what_the_server_stored(browser_page, admin_live_server, file_id, wired_mongo):
    """``Python`` חוזר מהשרת כ-``python``, ו-``#api`` כ-``api`` — והרשימה מציגה את זה."""
    page = browser_page
    _open_file(page, admin_live_server, file_id)
    _open_modal(page, "tags", "editTagsModal")
    page.fill("#tagsModalInput", "Python, #api")
    page.click("#tagsModalSave")

    badges = poll(page, f"() => {{ const b = ({_BADGES_JS})(); return {{ok: b.length === 2 && b[0] === '#python', b}}; }}",
                  "הרשימה בעמוד התעדכנה")
    assert badges["b"] == ["#python", "#api"]
    assert page.evaluate("() => document.getElementById('editTagsModal').hidden") is True

    stored = wired_mongo.get_db().code_snippets.find_one({"_id": ObjectId(file_id)})
    assert stored["tags"] == ["python", "api"]
    assert stored["updated_at"].replace(tzinfo=timezone.utc) == STAMP, "שינוי תגיות בלבד הזיז את updated_at"


def test_coming_back_after_saving_shows_the_new_tags(browser_page, admin_live_server, file_id):
    """בלי התגיות ב-ETag, הכניסה החוזרת קיבלה 304 והציגה את התגיות הישנות."""
    page = browser_page
    _open_file(page, admin_live_server, file_id)
    _open_modal(page, "tags", "editTagsModal")
    page.fill("#tagsModalInput", "fresh")
    page.click("#tagsModalSave")
    poll(page, f"() => ({_BADGES_JS})()[0] === '#fresh'", "הרשימה בעמוד התעדכנה")

    _open_file(page, admin_live_server, file_id)
    assert page.evaluate(_BADGES_JS) == ["#fresh"]


def test_clearing_all_tags_hides_the_row(browser_page, admin_live_server, file_id):
    """``.file-tags`` הוא ``display: flex``, וזה גובר על ``hidden`` של הדפדפן."""
    page = browser_page
    _open_file(page, admin_live_server, file_id)
    _open_modal(page, "tags", "editTagsModal")
    page.fill("#tagsModalInput", "")
    page.click("#tagsModalSave")

    row = poll(page, """() => { const b = document.getElementById('fileTagsList');
        return {ok: b.hidden && b.children.length === 0, display: getComputedStyle(b).display,
                height: b.getBoundingClientRect().height}; }""", "המכל התרוקן והוסתר")
    assert row["display"] == "none" and row["height"] == 0, row


@pytest.mark.parametrize("action, modal_id", [
    ("tags", "editTagsModal"),
    ("description", "editDescriptionModal"),
])
def test_escape_closes_the_modal_and_stays_on_the_page(browser_page, admin_live_server, file_id, action, modal_id):
    page = browser_page
    page.goto(f"{admin_live_server.base_url}/healthz")  # שתהיה היסטוריה לחזור אליה
    _open_file(page, admin_live_server, file_id)
    _open_modal(page, action, modal_id)
    file_url = page.url

    page.keyboard.press("Escape")
    poll(page, f"() => document.getElementById('{modal_id}').hidden", "המודאל נסגר")
    page.wait_for_timeout(500)
    assert page.url == file_url, f"Escape במודאל עזב את העמוד אל {page.url}"


def test_escape_with_nothing_open_still_goes_back(browser_page, admin_live_server, file_id):
    """ההתנהגות של העמוד עצמו נשארה: בלי שכבה פתוחה, Escape חוזר אחורה."""
    page = browser_page
    page.goto(f"{admin_live_server.base_url}/healthz")
    _open_file(page, admin_live_server, file_id)

    page.keyboard.press("Escape")
    page.wait_for_url(lambda url: "/healthz" in url, timeout=10000)
