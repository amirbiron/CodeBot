"""העתקה מהתצוגה המקדימה בכרטיס — בכרומיום אמיתי, בעמוד ``/files`` האמיתי, במגע של טאבלט.

**מה נבדק כאן ולא בבדיקות השרת.** ``tests/test_card_preview_latest_version.py`` מוכיח
שהשרת מחזיר את הגרסה האחרונה. מה שקורה בדפדפן — שהנגיעה מגיעה לכפתור, שהכתיבה ללוח
מתקבלת גם כשהתוכן מגיע מהרשת רק אחרי הנגיעה, ושבלוח נמצא כל הקובץ ולא מה שמוצג —
אפשר לראות רק כאן (``TESTING-PATTERNS.md`` T1).

**התרחיש הוא זה שהשינוי נבנה בשבילו:** העמוד נטען, ורק אחר כך נשמרת גרסה חדשה — כמו
סוכן ששומר דרך ה-MCP בזמן שהעמוד פתוח בטאבלט. הכרטיס עדיין מחזיק את המזהה של הגרסה
שהייתה האחרונה כשהעמוד נטען.

**הלוח.** שתי ההרשאות מאושרות להקשר, כמו ב-``tests/test_profiler_copy_report_browser.py``:
הקריאה כדי שהבדיקה תראה מה נכתב, והכתיבה כי בלעדיה הקשר של Playwright דוחה אותה גם
בתוך נגיעה (נמדד: ``navigator.permissions`` החזיר ``denied``, והכתיבה נדחתה ב-
``NotAllowedError: Write permission denied``) — מצב שאין אצל משתמש. המשמעות: כרומיום
כאן **אינו** בודק את הדרישה לכתוב בתוך הנגיעה, כי לפי MDN browser-compat-data
(``api/Clipboard.json``, ``write``) הרשאה שאושרה פוטרת ממנה.

**מה לא נבדק כאן:** ספארי ופיירפוקס — יש כאן רק כרומיום, ובהם הדרישה לכתוב בתוך
הנגיעה נאכפת. ההתנהגות שלהם נשענת על המקורות שמצוטטים ב-``copyPreviewCode`` שב-
``webapp/static/js/card-preview.js``. והשרת הוא הוובאפ האמיתי (``admin_live_server``)
מול מונגו אמיתי (``wired_mongo``).

מדולג כשאין Chromium (וב-CI אין: ראו ``docs/testing.rst``).
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timezone

import pytest
from bson import ObjectId

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import open_admin_page, poll, tap_on

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

#: ``admin_live_server`` בונה session למשתמש 1, ולכן הקבצים שלו.
USER_ID = 1
FILE_NAME = "copy_me.py"

#: טאבלט 12 אינץ' לרוחב, בפיקסלים לוגיים — המכשיר שהבקשה הגיעה ממנו.
TABLET = {"width": 1280, "height": 800}

#: יותר שורות ממה שהתצוגה מציגה, כדי שהעתקה של מה שמוצג תיראה מיד.
LINES = 60

CARD = '.file-card[data-file-id="{}"]'
PEEK = CARD + ' button[aria-label="הצץ בקוד"]'
COPY = '[data-testid="card-preview-copy"]'


def file_text(version: int) -> str:
    """השורה הראשונה מוזחת, עברית בכל שורה ושורות ריקות בסוף — וסימן הגרסה בכל שורה."""
    lines = [f"    first_line_v{version} = True"]
    lines += [f"line_{i:02d}_v{version} = 'שורה {i}'" for i in range(2, LINES + 1)]
    return "\n".join(lines) + "\n\n\n"


def save_version(wired_mongo, version: int, *, active: bool = True) -> str:
    """גרסה היא מסמך חדש עם ``_id`` חדש, כמו בכל מסלול שמירה. ``wired_mongo`` מתחיל ריק."""
    oid = ObjectId()
    now = datetime.now(timezone.utc)
    code = file_text(version)
    wired_mongo.get_db().code_snippets.insert_one({
        "_id": oid, "user_id": USER_ID, "file_name": FILE_NAME, "code": code,
        "programming_language": "python", "version": version, "is_active": active,
        "file_size": len(code.encode("utf-8")), "lines_count": len(code.split("\n")),
        "created_at": now, "updated_at": now,
    })
    return str(oid)


@contextlib.contextmanager
def files_page(server, executable, *, init_script: str = ""):
    """עמוד הקבצים במגע של טאבלט — **המקום היחיד שמרים דפדפן כאן**. מחזיר גם את ההודעות
    שנפתחו ב-``alert``. כל הניקוי ב-``finally``."""
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(
                executable_path=executable,
                args=[f"--window-size={TABLET['width']},{TABLET['height']}"],
            )
        except PlaywrightError as exc:  # pragma: no cover - תלוי בסביבה
            pytest.skip(f"אין Chromium זמין: {exc}")
        try:
            page, touch = open_admin_page(browser, server, "/files", viewport=TABLET)
            page.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=server.base_url)
            alerts = []
            page.on("dialog", lambda d: (alerts.append(d.message), d.accept()))
            if init_script:
                # ``open_admin_page`` כבר טען את העמוד, וסקריפט פתיחה חל רק מהטעינה הבאה.
                page.add_init_script(init_script)
                page.reload(wait_until="load")
                page.evaluate("document.querySelectorAll('.welcome-modal, .welcome-modal__backdrop,"
                              " #welcomeModal').forEach(e => e.remove())")
            yield page, touch, alerts
        finally:
            browser.close()


def open_preview(page, touch, card_id: str) -> None:
    tap_on(page, touch, PEEK.format(card_id))
    poll(page, "(sel) => !!document.querySelector(sel)", "התצוגה המקדימה נפתחה",
         f"{CARD.format(card_id)} {COPY}")


def tap_copy(page, touch) -> None:
    """הכפתור יושב מתחת לתצוגה, ובטאבלט הוא מחוץ למסך עד שגוללים אליו — כמו אצל משתמש."""
    page.evaluate("(sel) => document.querySelector(sel).scrollIntoView({block: 'center'})", COPY)
    poll(page, """(sel) => {
      const r = document.querySelector(sel).getBoundingClientRect();
      const y = r.top + r.height / 2;
      return {ok: y >= 0 && y <= innerHeight, y};
    }""", "כפתור ההעתקה על המסך", COPY)
    tap_on(page, touch, COPY)


def clipboard_text(page) -> str:
    return page.evaluate("() => navigator.clipboard.readText()")


def wait_for_clipboard(page, expected: str, what: str) -> None:
    poll(page, """async (expected) => {
      const text = await navigator.clipboard.readText();
      return text === expected ? true : {ok: false, length: text.length, head: text.slice(0, 60)};
    }""", what, expected)


def test_the_copy_holds_the_whole_latest_version_saved_after_the_page_loaded(
        wired_mongo, admin_live_server, chromium_executable):
    first_id = save_version(wired_mongo, 1)
    with files_page(admin_live_server, chromium_executable) as (page, touch, alerts):
        # נשמרת גרסה חדשה אחרי שהעמוד נטען — הכרטיס עדיין מחזיק את המזהה של גרסה 1.
        save_version(wired_mongo, 2)
        open_preview(page, touch, first_id)

        shown = page.locator(f"{CARD.format(first_id)} .card-code-preview").inner_text()
        assert "first_line_v2" in shown and "first_line_v1" not in shown, shown[:200]
        assert "גרסה 2" in page.locator(f"{CARD.format(first_id)} .card-code-preview-wrapper").inner_text()

        tap_copy(page, touch)

        wait_for_clipboard(page, file_text(2), "בלוח כל הקובץ, בגרסה 2")
        poll(page, "(sel) => document.querySelector(sel).textContent.includes('הועתקה גרסה 2')",
             "הכפתור אומר איזו גרסה הועתקה", COPY)
        assert alerts == []


def test_the_copy_takes_what_is_saved_at_the_tap_not_when_the_preview_opened(
        wired_mongo, admin_live_server, chromium_executable):
    first_id = save_version(wired_mongo, 1)
    with files_page(admin_live_server, chromium_executable) as (page, touch, alerts):
        open_preview(page, touch, first_id)
        # התצוגה כבר פתוחה, על גרסה 1 — ועכשיו נשמרת גרסה 2.
        save_version(wired_mongo, 2)

        tap_copy(page, touch)

        wait_for_clipboard(page, file_text(2), "בלוח הגרסה שנשמרה אחרי שהתצוגה נפתחה")
        assert alerts == []


def test_without_clipboard_item_the_copy_falls_back_to_write_text(
        wired_mongo, admin_live_server, chromium_executable):
    """הענף של דפדפן בלי ``ClipboardItem`` (פיירפוקס לפני 127): כתיבה אחרי שהתוכן הגיע."""
    first_id = save_version(wired_mongo, 1)
    with files_page(admin_live_server, chromium_executable,
                    init_script="delete window.ClipboardItem;") as (page, touch, alerts):
        assert page.evaluate("() => typeof window.ClipboardItem") == "undefined"
        open_preview(page, touch, first_id)

        tap_copy(page, touch)

        wait_for_clipboard(page, file_text(1), "בלוח כל הקובץ, גם בלי ClipboardItem")
        assert alerts == []


def test_a_file_moved_to_the_recycle_bin_after_the_preview_opened_is_reported_not_copied(
        wired_mongo, admin_live_server, chromium_executable):
    first_id = save_version(wired_mongo, 1)
    with files_page(admin_live_server, chromium_executable) as (page, touch, alerts):
        open_preview(page, touch, first_id)
        before = clipboard_text(page)
        wired_mongo.get_db().code_snippets.update_many(
            {"user_id": USER_ID, "file_name": FILE_NAME}, {"$set": {"is_active": False}})

        # ההודעה היא הסימן שהתשובה הגיעה; המטפל שב-``files_page`` מאשר אותה.
        with page.expect_event("dialog"):
            tap_copy(page, touch)

        assert alerts == ["הקובץ נמצא בסל המיחזור"]
        assert page.evaluate("(sel) => document.querySelector(sel).disabled", COPY) is False
        assert clipboard_text(page) == before
