"""תוויות ארוכות בתרשים Mermaid נשברות לשורות ואינן נחתכות, גם ביחס פיקסלים שאינו שלם — בכרומיום אמיתי.

**הבאג.** בתרשים בתצוגת המסמך, בטאבלט, "📦 יומנים ישנים עוברים לארכיון" הוצג "לארכיו", ו"במקום לקבל את המצב
העדכני" — "העדכנ". ``addHtmlSpan`` של Mermaid מודד תווית עם ``max-width`` של רוחב הגלישה, ועובר למצב גלישה רק
כשהמדידה **שווה בדיוק** לרוחב (mermaid-js/mermaid#7794). ביחס פיקסלים שאינו שלם המדידה חוזרת עם שארית, התווית
נשארת בשורה אחת, והטקסט שארוך מה-``foreignObject`` נחתך בקצה שלו — בעברית, הסוף של המשפט. התיקון בבנייה של הבאנדל:
``webapp/static_build/mermaid-label-wrap-fix.mjs`` (ההסבר שם), ו-``tests/md-preview-mermaid-label-wrap.test.js``
שומר ב-CI שהבאנדל שבריפו נבנה איתו.

**איך מגיעים לתנאי.** כרומיום מורם עם ``--force-device-scale-factor=2.2`` — יחס פיקסלים אמיתי, ולא האמולציה של
``device_scale_factor`` בהקשר: באמולציה (``Emulation.setDeviceMetricsOverride``) המדידה יוצאת 200 בדיוק, והבאג לא
משתחזר — כך נמדד כאן, וכך מתואר גם באישו. ``test_the_environment_reproduces_the_condition`` מוודא שהתנאי אכן
קיים בריצה (המדידה ש-Mermaid ראה שונה מהרוחב), ובלי זה כל שאר הבדיקות היו עוברות גם על הקוד הישן.

**שני המשטחים, בעמודים האמיתיים** (``TESTING-PATTERNS.md`` T1): תצוגת המסמך (``md_preview.html``, מרונדר עם
``render_template`` בלי מסד, כמו ב-``tests/test_md_preview_heading_level_browser.py``) והעורך הציבורי
(``/markdown-editor``, דרך ``test_client``, כמו ב-``tests/test_markdown_editor_browser.py``). שניהם טוענים את
``md_preview.bundle.js``. כל בקשה לאתר אחר נחסמת.

**מה נבדק:** אף תווית אינה חורגת מה-``foreignObject`` שלה, בשני יחסי הפיקסלים ובשני המשטחים; התוויות הארוכות
במצב גלישה ובגובה של יותר משורה, והקצרה בשורה אחת. **מה לא נבדק:** ספארי ופיירפוקס (יש כאן רק כרומיום, ולפי
האישו הבאג של כרומיום בלבד), מצב הקריאה (``reader_mode.html`` טוען Mermaid מ-CDN, ולא את הבאנדל), ותרשימים
שאינם flowchart — הם עוברים באותה ``addHtmlSpan``, ולא נמדדו.

מדולג כשאין Chromium (וב-CI אין: ראו ``docs/testing.rst``).
"""

from __future__ import annotations

from urllib.parse import urlsplit

import pytest

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import poll

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

HOST = "ck.test"
ORIGIN = f"https://{HOST}"

#: טאבלט לרוחב, בפיקסלים לוגיים.
TABLET = {"width": 1280, "height": 800}

#: התוויות מהתרשים שבו הבאג נראה. שתי הארוכות רחבות מרוחב הגלישה של Mermaid בגופנים של הסביבה הזו, ולכן
#: ``addHtmlSpan`` חוסם אותן ב-``max-width``; הקצרה — לא.
LONG_ONE_LINE = "📦 יומנים ישנים עוברים לארכיון"
LONG_WITH_BREAK = "הסוכן נדרש לחפש בהיסטוריה<br/>במקום לקבל את המצב העדכני"
SHORT = "⚠️ הזיכרון הולך ותופח"
DIAGRAM = (
    "```mermaid\n"
    "flowchart TB\n"
    f'    LIMIT["{SHORT}"] --> ARCH["{LONG_ONE_LINE}"]\n'
    f'    ARCH --> STALE["{LONG_WITH_BREAK}"]\n'
    "```\n"
)
LABELS = {
    "short": SHORT,
    "long_one_line": LONG_ONE_LINE,
    "long_with_break": LONG_WITH_BREAK.replace("<br/>", ""),
}

#: ``None`` — בלי הדגל, כלומר יחס 1. ‏2.2 — הטאבלט שבו הבאג נראה (נגזר מהצילום: 110 פיקסלי מסך בין שני צמתים,
#: שהמרווח ביניהם ב-Mermaid הוא 50).
ZOOMS = {"יחס פיקסלים 2.2": "2.2", "יחס פיקסלים 1": None}

#: מה ``addHtmlSpan`` מדד: מעטפת ל-``getBoundingClientRect`` שרושמת כל מדידה של אלמנט בתוך ``foreignObject``
#: שיש לו ``max-width`` — הרוחב שהוחזר, והרוחב שביקשו. היא מחזירה את אותה תוצאה בדיוק, ולכן אינה משנה דבר.
SPY_JS = """(() => {
  const original = Element.prototype.getBoundingClientRect;
  window.__labelClampMeasurements = [];
  Element.prototype.getBoundingClientRect = function () {
    const rect = original.call(this);
    try {
      if (this.style && this.style.maxWidth && this.closest && this.closest('foreignObject')) {
        window.__labelClampMeasurements.push({
          text: this.textContent, width: rect.width, maxWidth: parseFloat(this.style.maxWidth),
        });
      }
    } catch (e) { /* מדידה שלא נרשמה רק מחסירה שורה מהבקרה */ }
    return rect;
  };
})();"""

#: לכל תווית בתרשים: כמה הטקסט, כפי שצויר, חורג מה-``foreignObject`` בכל צד (בפיקסלי CSS של המסך), גובה
#: ה-``foreignObject`` ומצב ה-``white-space`` של התווית.
MEASURE_JS = """() => Array.from(document.querySelectorAll('#md-content svg foreignObject')).map(fo => {
  const div = fo.querySelector('div');
  const text = div ? div.textContent.trim() : '';
  if (!text) return null;
  const box = fo.getBoundingClientRect();
  const range = document.createRange();
  range.selectNodeContents(div);
  const glyphs = Array.from(range.getClientRects()).filter(r => r.width > 0);
  const left = Math.min(...glyphs.map(r => r.left)), right = Math.max(...glyphs.map(r => r.right));
  const top = Math.min(...glyphs.map(r => r.top)), bottom = Math.max(...glyphs.map(r => r.bottom));
  return {
    text,
    overflow: Math.max(box.left - left, right - box.right, box.top - top, bottom - box.bottom),
    height: parseFloat(fo.getAttribute('height')),
    whiteSpace: getComputedStyle(div).whiteSpace,
  };
}).filter(Boolean)"""

#: כמה פיקסלי CSS של חריגה עוד נחשבים "בתוך": שגיאת עיגול של הציור, לא אות שנחתכה (אות עברית — כ-8 פיקסלים).
TOLERANCE_PX = 0.5


def _render_document(wa) -> str:
    from flask import render_template, session

    user = {"id": 1, "first_name": "x", "username": "x"}
    with wa.app.test_request_context("/md/1"):
        session["user_id"] = 1
        session["user_data"] = user
        return render_template(
            "md_preview.html",
            user=user,
            file={"id": "1", "file_name": "diagram.md", "language": "markdown"},
            md_code=DIAGRAM,
            bot_username="x",
            can_save_shared=False,
            is_admin=False,
        )


def _wait_for_diagram(page):
    """עד שהתרשים **הזה** צויר — בעורך הציבורי יש בטקסט ההדגמה תרשים אחר, והוא מצויר קודם."""
    poll(
        page,
        "(texts) => { const found = Array.from(document.querySelectorAll('#md-content svg foreignObject'))"
        ".map(fo => fo.textContent.trim()); return texts.every(t => found.includes(t)); }",
        "התרשים צויר",
        list(LABELS.values()),
    )


def _measure_document(ctx):
    page = ctx.new_page()
    page.goto(f"{ORIGIN}/md")
    _wait_for_diagram(page)
    result = {
        "labels": page.evaluate(MEASURE_JS),
        "clamps": page.evaluate("window.__labelClampMeasurements"),
    }
    page.close()
    return result


def _measure_editor(ctx):
    page = ctx.new_page()
    page.goto(f"{ORIGIN}/markdown-editor")
    poll(page, "() => !!(window.editorManager && window.editorManager.cmInstance)", "העורך עלה")
    poll(
        page,
        "() => document.querySelector('[data-preview-status]').dataset.state === 'ready'",
        "התצוגה החיה מוכנה",
    )
    page.evaluate(
        "(t) => { const v = window.editorManager.cmInstance;"
        " v.dispatch({changes: {from: 0, to: v.state.doc.length, insert: t}}); }",
        DIAGRAM,
    )
    _wait_for_diagram(page)
    result = {
        "labels": page.evaluate(MEASURE_JS),
        "clamps": page.evaluate("window.__labelClampMeasurements"),
    }
    page.close()
    return result


@pytest.fixture(scope="module", params=sorted(ZOOMS), ids=sorted(ZOOMS))
def measured(request, chromium_executable):
    """המדידות של שני המשטחים ביחס פיקסלים אחד: ``{"zoom", "document", "editor"}``."""
    import webapp.app as wa

    def _no_db(*args, **kwargs):
        raise RuntimeError("no database in this test")

    zoom = ZOOMS[request.param]
    args = [f"--force-device-scale-factor={zoom}"] if zoom else []
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(wa, "get_db", _no_db)
        html = _render_document(wa)
        client = wa.app.test_client()
        with sync_playwright() as pw:
            try:
                browser = (
                    pw.chromium.launch(executable_path=chromium_executable, args=args)
                    if chromium_executable
                    else pw.chromium.launch(args=args)
                )
            except Exception as exc:  # כשל חולף בהרמה, אחרי שהשער כבר אמר שיש דפדפן
                pytest.skip(f"Chromium לא עלה: {exc}")
            try:
                ctx = browser.new_context(viewport=TABLET, locale="he-IL")

                def handle(route):
                    u = urlsplit(route.request.url)
                    if u.hostname != HOST:
                        return route.abort()
                    if u.path == "/md":
                        return route.fulfill(
                            status=200, body=html, content_type="text/html; charset=utf-8"
                        )
                    r = client.open(
                        u.path + (f"?{u.query}" if u.query else ""),
                        method=route.request.method,
                        data=route.request.post_data_buffer,
                        headers={"Content-Type": route.request.headers.get("content-type", "")},
                    )
                    route.fulfill(
                        status=r.status_code,
                        body=r.data,
                        headers={k: v for k, v in r.headers.items() if k.lower() == "content-type"},
                    )

                ctx.route("**/*", handle)
                ctx.add_init_script(SPY_JS)
                yield {
                    "zoom": zoom,
                    "document": _measure_document(ctx),
                    "editor": _measure_editor(ctx),
                }
            finally:
                browser.close()


def _labels(surface: dict) -> dict:
    """התוויות שנמדדו, לפי המפתחות של ``LABELS``. תווית שחסרה בתרשים היא כישלון, לא דילוג."""
    by_text = {row["text"]: row for row in surface["labels"]}
    missing = [key for key, text in LABELS.items() if text not in by_text]
    assert not missing, f"לא נמצאו בתרשים: {missing} — נמצאו: {sorted(by_text)}"
    return {key: by_text[text] for key, text in LABELS.items()}


@pytest.mark.parametrize("surface", ["document", "editor"])
def test_the_environment_reproduces_the_condition(measured, surface):
    """בקרה: ב-2.2 המדידה ש-Mermaid ראה לתווית ארוכה **שונה** מה-``max-width``, וב-1 שווה לו בדיוק.

    בלי התנאי הזה בריצה, ``addHtmlSpan`` הישן היה עובר למצב גלישה בעצמו, וכל שאר הבדיקות היו עוברות גם בלי
    התיקון. בכרומיום 1243 נמדד ב-2.2 ‏200.00010681152344 מול 200. אם גרסה אחרת תחזיר כאן 200 בדיוק — מחפשים
    יחס פיקסלים אחר שמשחזר (‏1.75 ו-3.5 שחזרו בבדיקה ידנית), ולא מוחקים את הבקרה.
    """
    long_texts = {LABELS["long_one_line"], LABELS["long_with_break"]}
    clamps = [m for m in measured[surface]["clamps"] if m["text"].strip() in long_texts]
    assert clamps, f"Mermaid לא מדד אף תווית ארוכה עם max-width: {measured[surface]['clamps']}"
    off = [m for m in clamps if m["width"] != m["maxWidth"]]
    if measured["zoom"]:
        assert (
            off
        ), f"ב-{measured['zoom']} כל המדידות יצאו שוות ל-max-width, והתנאי לא משתחזר: {clamps}"
    else:
        assert not off, f"ביחס 1 המדידה הייתה צריכה להיות בדיוק max-width: {off}"


@pytest.mark.parametrize("surface", ["document", "editor"])
def test_no_label_text_is_clipped(measured, surface):
    """אף תווית אינה חורגת מה-``foreignObject`` שלה — מה שחורג נחתך, ובעברית זה סוף המשפט."""
    clipped = {
        key: round(row["overflow"], 2)
        for key, row in _labels(measured[surface]).items()
        if row["overflow"] > TOLERANCE_PX
    }
    assert not clipped, f"תוויות שחורגות מהתיבה שלהן (בפיקסלים): {clipped}"


@pytest.mark.parametrize("surface", ["document", "editor"])
def test_long_labels_wrap_and_the_short_one_stays_on_one_line(measured, surface):
    """התוויות שנחסמו ב-``max-width`` במצב גלישה ובגובה של יותר משורה; הקצרה — ``nowrap`` ובשורה אחת."""
    labels = _labels(measured[surface])
    line = labels["short"]["height"]
    assert labels["short"]["whiteSpace"] == "nowrap", labels["short"]
    for key in ("long_one_line", "long_with_break"):
        row = labels[key]
        assert row["whiteSpace"] == "break-spaces", (key, row)
        # התווית עם ``<br/>`` היא כבר שתי שורות בלי שום גלישה; כאן היא צריכה יותר.
        lines_without_wrapping = 2 if key == "long_with_break" else 1
        assert row["height"] > lines_without_wrapping * line + TOLERANCE_PX, (
            key,
            row,
            f"שורה: {line}",
        )
