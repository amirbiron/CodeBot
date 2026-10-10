"""ישויות HTML שהוקלדו בפתק בלוח: שמירה, ריענון, ומה שהמשתמש רואה — בכרומיום אמיתי.

**זה הבאג כפי שהמשתמש ראה אותו.** ``&amp; &lt;div&gt; &quot;`` הוקלד שלוש פעמים — בטקסט, בקוד
בשורה ובבלוק קוד. לפני הריענון הכול הוצג כמו שהוקלד, כי הדפדפן הציג את מה שזכר. אחרי הריענון
שלושתם הוצגו ``& <div> "``, גם במצב עריכה: עד אוקטובר 2026 השרת פענח את הישויות בשמירה
ובקריאה. בדיקות השרת (``tests/test_note_boards_api.py``,
``tests/test_note_content_preserved_real_mongo.py``) מוכיחות מה נשמר ומה חוזר; כאן נבדק מה
מוצג — התצוגה המרונדרת, שנבנית ב-``textContent``, ומצב העריכה אחרי ריענון (T1).

**השמירה, ולמה שני ריענונים.** הלוח שומר ב-debounce, ובהרצות מקומיות נמדד שלפעמים הבקשה
יוצאת רק כשהעמוד נפרק (``pagehide``), כשבקשות למארחים אחרים נקטעות (``open_admin_page``).
לכן הריענון הראשון מוציא את השמירה, הבדיקה מחכה שהגוף יגיע למסד, והריענון השני נטען רק
אחרי שהשמירה נחתה — ולא במרוץ איתה.

הוובאפ האמיתי (``admin_live_server``) מול מונגו אמיתי (``wired_mongo``). מדולג כשאין Chromium
או מונגו (וב-CI אין: ראו ``docs/testing.rst``).
"""

from __future__ import annotations

import contextlib
import json
import time

import pytest
from bson import ObjectId

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import WAIT_S, open_admin_page, poll

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

#: טאבלט 12 אינץ' לרוחב, בפיקסלים לוגיים — המכשיר שהדיווח הגיע ממנו.
TABLET = {"width": 1280, "height": 800}

ENTITIES = "&amp; &lt;div&gt; &quot;"
#: בטקסט, בקוד בשורה ובבלוק קוד — שלוש השורות שהמשתמש הקליד.
LINES = [ENTITIES, f"`{ENTITIES}`", "```", ENTITIES, "```"]
TYPED = "\n".join(LINES)

#: הפתק: ה-textarea, והתצוגה המרונדרת עם צמתי ה-``<code>`` שבה. ``rendered`` — לחכות גם
#: לתצוגה שכבר נבנתה, ולא רק לפתק שקיים בעמוד.
NOTE_JS = """(rendered) => {
  const el = document.querySelector('.sticky-note');
  const ta = el && el.querySelector('.sticky-note-content');
  const view = el && el.querySelector('.sticky-note-tasks');
  if (!ta || !view) return {ok: false, note: !!el};
  return {ok: !rendered || !!view.textContent, textarea: ta.value, view: view.textContent,
          codes: Array.from(view.querySelectorAll('code')).map(c => c.textContent)};
}"""


def _drop_welcome(page) -> None:
    page.evaluate("document.querySelectorAll('.welcome-modal, .welcome-modal__backdrop,"
                  " #welcomeModal').forEach(e => e.remove())")


def _post(page, base: str, path: str, body: dict) -> dict:
    res = page.request.post(base + path, data=json.dumps(body), headers={"Content-Type": "application/json"})
    assert res.ok, (path, res.status, res.text())
    return res.json()


def _wait_for_body(notes, note_id: str) -> str:
    """הגוף שבמסד, כשהשמירה כבר נחתה — לא ערך ההחזרה של הבקשה."""
    deadline = time.monotonic() + WAIT_S
    while True:
        body = (notes.find_one({"_id": ObjectId(note_id)}) or {}).get("content")
        if body:
            return body
        assert time.monotonic() < deadline, f"הגוף לא הגיע למסד תוך {WAIT_S} שניות"
        time.sleep(0.1)


@contextlib.contextmanager
def _board_page(server, executable):
    """לוח עם פתק ריק — מה ש"פתק חדש" יוצר — **המקום היחיד שמרים דפדפן כאן**."""
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=executable)
        except PlaywrightError as exc:  # pragma: no cover - תלוי בסביבה
            pytest.skip(f"אין Chromium זמין: {exc}")
        try:
            page, _touch = open_admin_page(browser, server, "/boards", viewport=TABLET)
            board = _post(page, server.base_url, "/api/note-boards", {"name": "ישויות"})["board"]["id"]
            created = _post(page, server.base_url, f"/api/sticky-notes/board/{board}", {"content_b64": ""})
            page.goto(f"{server.base_url}/boards/{board}", wait_until="load")
            _drop_welcome(page)
            yield page, created["id"]
        finally:
            browser.close()


def test_entities_typed_in_a_board_note_survive_save_and_reload(
        wired_mongo, admin_live_server, chromium_executable):
    notes = wired_mongo.get_db().sticky_notes
    with _board_page(admin_live_server, chromium_executable) as (page, note_id):
        poll(page, NOTE_JS, "הפתק נטען", False)
        page.locator(".sticky-note .sticky-note-content").first.click()
        for i, line in enumerate(LINES):
            page.keyboard.type(line)
            if i < len(LINES) - 1:
                page.keyboard.press("Enter")
        page.mouse.click(5, 5)  # יציאה מהעריכה, כמו משתמש
        before = poll(page, NOTE_JS, "התצוגה נבנתה", True)
        assert before["textarea"] == TYPED, before  # בקרת שפיות: מה שהוקלד הגיע ל-textarea

        page.reload(wait_until="load")
        stored = _wait_for_body(notes, note_id)
        assert stored == TYPED, f"נשמר {stored!r} ({len(stored.encode())} בתים), הוקלד {len(TYPED.encode())}"

        page.reload(wait_until="load")
        _drop_welcome(page)
        after = poll(page, NOTE_JS, "הפתק נטען מחדש עם התצוגה", True)
        assert after["view"].count(ENTITIES) == 3, after
        assert ENTITIES in after["codes"], after

        page.locator(".sticky-note .sticky-note-tasks").first.click()  # כניסה לעריכה, כמו משתמש
        editing = poll(page, NOTE_JS, "מצב עריכה", False)
        assert editing["textarea"] == TYPED, editing
