"""עמוד העריכה בדפדפן אמיתי: נגיעה במסגרת של העורך, וההודעה הזמנית בשורת הכפתורים.

שני התיקונים יושבים בקבצים המשותפים לכל עמודי העורך (``split-view.css``, ``editor-manager.js`` ו-
``codemirror-custom.css``), ונמדדו קודם בעורך הציבורי (``tests/test_markdown_editor_browser.py``). כאן הם
נבדקים בעמוד העריכה, כי שם הם נראים במלואם:

- **המסגרת.** בעמוד העריכה העורך משמאל לימין, ושורות הטקסט נמשכות עד הצד הימני שלו. נגיעה במסגרת שמימין
  לעורך — הריפוד של הפאנל, או הגבול של ה-Split View — הכניסה את הסמן לטקסט, ובנייד פתחה מקלדת: Chrome מציב את
  הסמן בטקסט הקרוב לנגיעה. בעורך הציבורי, מימין לטקסט יושבים מספרי השורות, ולכן הבדיקה שם אינה מספיקה.
- **ההודעה הזמנית** ("כל הקוד סומן"). היא מופיעה במקום התווית שבשורת הכפתורים, ולכן העורך לא זז.

העמוד מרונדר מ-``edit_file.html`` עם ``render_template`` ונתוני דוגמה, בלי מסד: ``get_db`` זורק, ו-
``inject_globals`` ממשיך בלי מסמך משתמש, כמו בכל כשל מסד. מדולג כשאין Chromium.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

HOST = "ck.test"
CODE = "# כותרת\n\n" + "\n\n".join(
    f"line {i} with some text that runs to the right edge" for i in range(40)
)


def _render_edit_page(wa) -> str:
    from flask import render_template, session

    user = {"id": 1, "first_name": "x", "username": "x"}
    file = {
        "id": "1",
        "file_name": "notes.md",
        "language": "markdown",
        "description": "",
        "tags": [],
        "is_large": False,
        "source_url": "",
    }
    with wa.app.test_request_context("/edit/1"):
        session["user_id"] = 1
        session["user_data"] = user
        return render_template(
            "edit_file.html",
            user=user,
            file=file,
            code_value=CODE,
            languages=["python", "markdown"],
            existing_images=[],
            error=None,
            success=None,
        )


@pytest.fixture(scope="module")
def edit_page(chromium_executable):
    import webapp.app as wa

    def _no_db(*args, **kwargs):
        raise RuntimeError("no database in this test")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(wa, "get_db", _no_db)
        html = _render_edit_page(wa)
        client = wa.app.test_client()
        with sync_playwright() as pw:
            try:
                browser = (
                    pw.chromium.launch(executable_path=chromium_executable)
                    if chromium_executable
                    else pw.chromium.launch()
                )
            except Exception as exc:  # כשל חולף בהרמה, אחרי שהשער כבר אמר שיש דפדפן
                pytest.skip(f"Chromium לא עלה: {exc}")
            ctx = browser.new_context(
                viewport={"width": 1000, "height": 620},
                device_scale_factor=2,
                is_mobile=True,
                has_touch=True,
            )

            def handle(route):
                u = urlsplit(route.request.url)
                if u.hostname != HOST:
                    return route.abort()
                if u.path == "/edit":
                    return route.fulfill(
                        status=200, body=html, content_type="text/html; charset=utf-8"
                    )
                r = client.get(u.path + (f"?{u.query}" if u.query else ""))
                route.fulfill(
                    status=r.status_code,
                    body=r.data,
                    headers={k: v for k, v in r.headers.items() if k.lower() == "content-type"},
                )

            ctx.route("**/*", handle)
            page = ctx.new_page()
            page.goto(f"http://{HOST}/edit")
            page.wait_for_selector(".cm-editor", timeout=30000)
            try:
                yield page
            finally:
                browser.close()


def test_tapping_the_frame_beside_the_editor_does_not_put_the_caret_in_it(edit_page):
    page = edit_page
    page.click('[data-action="toggle-live-preview"]')
    page.wait_for_function(
        "document.querySelector('[data-preview-status]').dataset.state === 'ready'", timeout=30000
    )
    page.evaluate(
        "() => document.getElementById('livePreviewRoot').scrollIntoView({block: 'start'})"
    )
    geo = page.evaluate(
        """() => {
      const q = (sel) => document.querySelector(sel).getBoundingClientRect();
      return {root: q('#livePreviewRoot'), panel: q('.split-panel--editor'), cm: q('.codemirror-container')};
    }"""
    )
    y = int(min(geo["cm"]["y"] + 60, 600))
    assert (
        page.evaluate("() => getComputedStyle(document.querySelector('.cm-content')).direction")
        == "ltr"
    )

    points = {
        "split-view border": int(geo["root"]["x"] + geo["root"]["width"] - 1),
        "editor panel padding": int(geo["panel"]["x"] + geo["panel"]["width"] - 4),
    }
    for name, x in points.items():
        page.evaluate("() => document.activeElement && document.activeElement.blur()")
        page.touchscreen.tap(x, y)
        page.wait_for_timeout(250)
        editable = page.evaluate(
            "() => { const a = document.activeElement;"
            " return !!a && (a.isContentEditable || a.tagName === 'TEXTAREA'); }"
        )
        assert not editable, f"נגיעה ב-{name} ({x}, {y}) הכניסה את הסמן לעורך"

    # בקרה: נגיעה בטקסט עצמו כן נכנסת לעורך — אחרת הבדיקה הייתה עוברת גם על עורך שאינו מגיב
    page.touchscreen.tap(int(geo["cm"]["x"] + 120), y)
    page.wait_for_timeout(250)
    assert page.evaluate("() => document.activeElement.isContentEditable")


def test_a_notice_does_not_move_the_editor(edit_page):
    """ההודעה מופיעה במקום התווית "קיצורי מקלדת זמינים", ולכן העורך לא זז. עד התיקון היא ישבה בשורה משלה,
    שגדלה כשהטקסט הופיע (נמדד כאן: כפיקסל אחד), וכששורת הכפתורים נשברת לכמה שורות — שורה שלמה."""
    page = edit_page
    before = page.evaluate(
        "() => ({row: document.querySelector('.editor-switcher-row').getBoundingClientRect().height,"
        " cm: document.querySelector('.codemirror-container').getBoundingClientRect().top"
        " - document.querySelector('.editor-switcher').getBoundingClientRect().top})"
    )
    page.click(".btn-editor-select")
    page.wait_for_function(
        "document.querySelector('.editor-info-status').textContent.trim() !== ''"
    )
    after = page.evaluate(
        "() => ({row: document.querySelector('.editor-switcher-row').getBoundingClientRect().height,"
        " cm: document.querySelector('.codemirror-container').getBoundingClientRect().top"
        " - document.querySelector('.editor-switcher').getBoundingClientRect().top})"
    )
    assert after == before, (before, after)
