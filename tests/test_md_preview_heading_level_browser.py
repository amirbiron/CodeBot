"""תצוגת המסמך (``md_preview.html``) בכרומיום: כותרות רק עד H4, ו-``#####`` / ``######`` כפסקה כמו שנכתבו.

**הבאג.** H5/H6 בוטלו קודם בתצוגה החיה בלבד: הכלל היה כתוב בתוך ``live-preview.js``, ותצוגת המסמך — העמוד של
הקובץ (``/md/<file_id>``) והשיתוף הציבורי (``/share/<share_id>?view=md``), שניהם מאותה תבנית — המשיכה לרנדר
אותן ככותרות. היום הכלל יושב ב-``md-heading-level-plugin.js``, ושני הרנדררים מתקינים אותו.

**מה נבדק:** שאין ``h5``/``h6`` במסמך, ושהשורות נשארו כפסקה עם הסולמיות ועם שורת המקור שלהן
(``data-source-line``, שהפתקים הדביקים נעזרים בה); שעוגן מפורש של כותרת שאחרי ``#####`` נוחת על הכותרת שלו —
העוגנים נספרים לפי המספר הסידורי של הכותרת, ולכן ``renderWithAnchors`` מקבל את הרמה שהותקנה; ושתוכן העניינים
הצף בנוי מהכותרות שנשארו.

**איך העמוד מוגש.** ``md_preview.html`` מרונדר עם ``render_template`` ונתוני דוגמה, בלי מסד, כמו עמוד העריכה ב-
``tests/test_edit_page_frame_browser.py``; הסטטיקה מגיעה מ-``test_client`` של Flask, ובקשה לאתר חיצוני נחסמת.
מדולג כשאין Chromium.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

HOST = "ck.test"
ORIGIN = f"https://{HOST}"

MARKDOWN = (
    "# ראשית\n\n"
    "##### חמישית\n\n"
    '## יעד <a id="target"></a>\n\n'
    "###### שישית\n\n"
    "## הבאה\n\n"
    "#### רביעית\n"
)


def _render_document(wa) -> str:
    from flask import render_template, session

    user = {"id": 1, "first_name": "x", "username": "x"}
    with wa.app.test_request_context("/md/1"):
        session["user_id"] = 1
        session["user_data"] = user
        return render_template(
            "md_preview.html",
            user=user,
            file={"id": "1", "file_name": "doc.md", "language": "markdown"},
            md_code=MARKDOWN,
            bot_username="x",
            can_save_shared=False,
            is_admin=False,
        )


STATE = """() => {
  const c = document.getElementById('md-content');
  const target = document.getElementById('target');
  const text = (el) => el.textContent.replace('¶', '').trim();
  return {
    headings: [...c.querySelectorAll('h1, h2, h3, h4, h5, h6')].map((h) => h.tagName + ' ' + text(h)),
    paragraphs: [...c.querySelectorAll('p')].map((p) => [p.textContent.trim(), p.getAttribute('data-source-line')]),
    anchorLandsOn: target && target.nextElementSibling ? text(target.nextElementSibling) : null,
    toc: [...document.querySelectorAll('.md-toc-item')].map((i) => i.textContent.trim()),
  };
}"""


@pytest.fixture(scope="module")
def document(chromium_executable):
    import webapp.app as wa

    def _no_db(*args, **kwargs):
        raise RuntimeError("no database in this test")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(wa, "get_db", _no_db)
        html = _render_document(wa)
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
            console: list[str] = []

            def handle(route):
                u = urlsplit(route.request.url)
                if u.hostname != HOST:
                    return route.abort()
                if u.path == "/md":
                    return route.fulfill(
                        status=200, body=html, content_type="text/html; charset=utf-8"
                    )
                r = client.get(u.path + (f"?{u.query}" if u.query else ""))
                route.fulfill(
                    status=r.status_code,
                    body=r.data,
                    headers={k: v for k, v in r.headers.items() if k.lower() == "content-type"},
                )

            ctx = browser.new_context(viewport={"width": 1000, "height": 800})
            ctx.route("**/*", handle)
            page = ctx.new_page()
            page.on("console", lambda msg: console.append(msg.text))
            page.goto(f"{ORIGIN}/md")
            page.wait_for_function(
                "() => document.querySelectorAll('.md-toc-item').length > 0", timeout=30000
            )
            try:
                yield page.evaluate(STATE), console
            finally:
                browser.close()


def test_h5_and_h6_are_paragraphs_as_written(document):
    state, console = document
    assert state["headings"] == ["H1 ראשית", "H2 יעד", "H2 הבאה", "H4 רביעית"], state
    assert state["paragraphs"] == [["##### חמישית", "2"], ["###### שישית", "6"]], state
    assert not [line for line in console if "md-heading-level-plugin" in line], console


def test_an_anchor_after_an_h5_lands_on_its_own_heading(document):
    state, _console = document
    assert state["anchorLandsOn"] == "יעד", state


def test_the_table_of_contents_lists_only_the_headings_that_remain(document):
    state, _console = document
    assert state["toc"] == ["ראשית", "יעד", "הבאה", "רביעית"], state
