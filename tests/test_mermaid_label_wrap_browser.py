"""תוויות בתרשים Mermaid: רוחב הגלישה של האתר, הנחיה של תרשים שגוברת עליו, ובלי חיתוך — בכרומיום אמיתי.

**רוחב הגלישה של האתר.** תווית רחבה מ-``flowchart.wrappingWidth`` נשברת לשורות ברוחב הזה, וצרה ממנו נשארת בשורה
אחת. ברירת המחדל של Mermaid היא 200, ובה משפט עברי קצר כבר נשבר; האתר קובע ערך משלו, ``MERMAID_WRAPPING_WIDTH`` ב-
``webapp/static_build/mermaid-site-config.mjs``, ששני המקומות שמציירים תרשימים מקבלים מ-``window.mermaidSiteConfig``.
תרשים בודד יכול לקבוע ערך אחר עם ``%%{init: {"flowchart": {"wrappingWidth": ...}}}%%``. כאן נמדד שתווית בינונית
נשארת בשורה אחת, שתווית רחבה מהרוחב נשברת בו, ושהנחיה של תרשים גוברת. הערך עצמו נקרא מהעמוד, ולא מוקלד כאן.

**החיתוך.** בתרשים בתצוגת המסמך, בטאבלט, "📦 יומנים ישנים עוברים לארכיון" הוצג "לארכיו". ``addHtmlSpan`` של Mermaid
עובר למצב גלישה רק כשהמדידה של התווית **שווה בדיוק** לרוחב הגלישה (mermaid-js/mermaid#7794), וביחס פיקסלים שאינו
שלם המדידה חוזרת עם שארית: התווית נשארת בשורה אחת, והטקסט שארוך מה-``foreignObject`` נחתך — בעברית, סוף המשפט.
התיקון בבנייה של הבאנדל: ``webapp/static_build/mermaid-label-wrap-fix.mjs``. התרשים עם ההנחיה מחזיר את הרוחב ל-200,
ולכן התווית מהדיווח נמדדת כאן בדיוק בתנאי שבו היא נחתכה.

**איך מגיעים לתנאי.** כרומיום מורם עם ``--force-device-scale-factor=2.2`` — יחס פיקסלים אמיתי, ולא האמולציה של
``device_scale_factor`` בהקשר: באמולציה (``Emulation.setDeviceMetricsOverride``) המדידה יוצאת שלמה, והבאג לא משתחזר —
כך נמדד כאן, וכך מתואר גם באישו. ``test_the_environment_reproduces_the_condition`` מוודא שהתנאי אכן קיים בריצה
(המדידה ש-Mermaid ראה שונה מהרוחב), ובלי זה בדיקת החיתוך הייתה עוברת גם על הקוד הישן.

**שני המשטחים, בעמודים האמיתיים** (``TESTING-PATTERNS.md`` T1): תצוגת המסמך (``md_preview.html``, מרונדר עם
``render_template`` בלי מסד, כמו ב-``tests/test_md_preview_heading_level_browser.py``) והעורך הציבורי
(``/markdown-editor``, דרך ``test_client``, כמו ב-``tests/test_markdown_editor_browser.py``). שניהם טוענים את
``md_preview.bundle.js``. כל בקשה לאתר אחר נחסמת.

**מה לא נבדק:** ספארי ופיירפוקס (יש כאן רק כרומיום, ולפי האישו הבאג של כרומיום בלבד), מצב הקריאה
(``reader_mode.html`` טוען Mermaid מ-CDN עם תצורה משלו, ולא את הבאנדל), ותרשימים שאינם flowchart.

מדולג כשאין Chromium (וב-CI אין: ראו ``docs/testing.rst``).
"""

from __future__ import annotations

import re
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

#: הרוחב הטבעי של התוויות, בגופנים של הסביבה הזו (כרומיום 1243, ``"trebuchet ms", verdana, arial, sans-serif``
#: ב-16px), נמדד בנובמבר 2026: הקצרה 148, הבינונית 285, הארוכה 684, והשורה הארוכה של התווית עם ``<br/>`` 548.
#: הבינונית באמצע בין 200 ל-400, והארוכות רחבות מ-400 בהרבה, כדי שהבדיקות לא ייפלו על הבדל קטן בגופן.
SHORT = "⚠️ הזיכרון הולך ותופח"
MEDIUM = "מלכודת שכבר נפלו בה עם הסימפטום שלה"
LONG_ONE_LINE = (
    "הסוכן נדרש לחפש בהיסטוריה במקום לקבל את המצב העדכני, ולכן הוא מפספס החלטות שכבר התקבלו"
)
LONG_WITH_BREAK = "החלטות<br/>ההחלטה והנימוק שלה, החלופה שנשקלה ונפסלה ולמה, וההנחה שעליה היא נשענת"
#: התווית מהדיווח: 208 — רחבה מ-200, ולכן בתרשים עם ההנחיה היא נחסמת בדיוק כמו בטאבלט.
REPORTED = "📦 יומנים ישנים עוברים לארכיון"

#: הרוחב שהתרשים השני קובע לעצמו בהנחיה.
DIRECTIVE_WIDTH = 200

SITE_DIAGRAM = (
    "```mermaid\n"
    "flowchart TB\n"
    f'    S["{SHORT}"] --> M["{MEDIUM}"]\n'
    f'    M --> L["{LONG_ONE_LINE}"]\n'
    f'    L --> B["{LONG_WITH_BREAK}"]\n'
    "```\n"
)
DIRECTIVE_DIAGRAM = (
    "```mermaid\n"
    f'%%{{init: {{"flowchart": {{"wrappingWidth": {DIRECTIVE_WIDTH}}}}}}}%%\n'
    "flowchart TB\n"
    f'    R["{REPORTED}"] --> M["{MEDIUM}"]\n'
    "```\n"
)
MARKDOWN = SITE_DIAGRAM + "\n" + DIRECTIVE_DIAGRAM


def _text(label: str) -> str:
    """התווית כפי שהיא ב-DOM: ``<br/>`` הופך לשבירת שורה, שאינה חלק מ-``textContent``."""
    return label.replace("<br/>", "")


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

#: לכל תרשים בעמוד, לכל תווית בו: כמה הטקסט, כפי שצויר, חורג מה-``foreignObject`` בכל צד (בפיקסלי CSS של
#: המסך), הרוחב והגובה של ה-``foreignObject`` (ביחידות של התרשים), ומצב ה-``white-space`` של התווית.
MEASURE_JS = """() => Array.from(document.querySelectorAll('#md-content svg')).map(svg =>
  Array.from(svg.querySelectorAll('foreignObject')).map(fo => {
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
      width: parseFloat(fo.getAttribute('width')),
      height: parseFloat(fo.getAttribute('height')),
      whiteSpace: getComputedStyle(div).whiteSpace,
    };
  }).filter(Boolean))"""

#: רוחב הגלישה של האתר, כפי שהעמוד מעביר ל-``mermaid.initialize``. ``null`` כשאין ``window.mermaidSiteConfig``.
SITE_WIDTH_JS = """() => window.mermaidSiteConfig
  ? window.mermaidSiteConfig('dark').flowchart.wrappingWidth : null"""

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
            md_code=MARKDOWN,
            bot_username="x",
            can_save_shared=False,
            is_admin=False,
        )


def _wait_for_diagrams(page):
    """עד ששני התרשימים **האלה** צוירו — בעורך הציבורי יש בטקסט ההדגמה תרשים אחר, והוא מצויר קודם."""
    poll(
        page,
        "(texts) => { const found = Array.from(document.querySelectorAll('#md-content svg foreignObject'))"
        ".map(fo => fo.textContent.trim()); return texts.every(t => found.includes(t)); }",
        "התרשימים צוירו",
        [_text(t) for t in (SHORT, MEDIUM, LONG_ONE_LINE, LONG_WITH_BREAK, REPORTED)],
    )


def _collect(page):
    return {
        "svgs": page.evaluate(MEASURE_JS),
        "clamps": page.evaluate("window.__labelClampMeasurements"),
        "site_width": page.evaluate(SITE_WIDTH_JS),
    }


def _measure_document(ctx):
    page = ctx.new_page()
    page.goto(f"{ORIGIN}/md")
    _wait_for_diagrams(page)
    result = _collect(page)
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
        MARKDOWN,
    )
    _wait_for_diagrams(page)
    result = _collect(page)
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


def _diagram(surface: dict, marker: str) -> dict:
    """התוויות של התרשים שיש בו את ``marker``, לפי הטקסט. תרשים חסר הוא כישלון, לא דילוג."""
    for labels in surface["svgs"]:
        by_text = {row["text"]: row for row in labels}
        if _text(marker) in by_text:
            return by_text
    raise AssertionError(f"אין בעמוד תרשים עם {marker!r}: {surface['svgs']}")


def _site(surface: dict) -> dict:
    return _diagram(surface, SHORT)


def _with_directive(surface: dict) -> dict:
    return _diagram(surface, REPORTED)


def _wrapping_width_of(diagram: str) -> int:
    """הרוחב שהתרשים קובע בהנחיה — מהטקסט של התרשים, כדי שהבדיקה תשווה למה שנכתב בו."""
    return int(re.search(r'"wrappingWidth": (\d+)', diagram).group(1))


@pytest.mark.parametrize("surface", ["document", "editor"])
def test_the_environment_reproduces_the_condition(measured, surface):
    """בקרה: ב-2.2 המדידה ש-Mermaid ראה לתווית שנחסמה **שונה** מה-``max-width``, וב-1 שווה לו בדיוק.

    בלי התנאי הזה בריצה, ``addHtmlSpan`` הישן היה עובר למצב גלישה בעצמו, ובדיקת החיתוך הייתה עוברת גם בלי
    התיקון. בכרומיום 1243 נמדד ב-2.2 ‏200.00010681152344 מול 200. אם גרסה אחרת תחזיר כאן מספר שלם — מחפשים
    יחס פיקסלים אחר שמשחזר (‏1.75 ו-3.5 שחזרו בבדיקה ידנית), ולא מוחקים את הבקרה.
    """
    clamped_texts = {_text(t) for t in (LONG_ONE_LINE, LONG_WITH_BREAK, REPORTED, MEDIUM)}
    clamps = [
        m
        for m in measured[surface]["clamps"]
        if m["text"].strip() in clamped_texts and m["width"] >= m["maxWidth"] - 1
    ]
    assert clamps, f"Mermaid לא מדד אף תווית שנחסמה: {measured[surface]['clamps']}"
    off = [m for m in clamps if m["width"] != m["maxWidth"]]
    if measured["zoom"]:
        assert (
            off
        ), f"ב-{measured['zoom']} כל המדידות יצאו שוות ל-max-width, והתנאי לא משתחזר: {clamps}"
    else:
        assert not off, f"ביחס 1 המדידה הייתה צריכה להיות בדיוק max-width: {off}"


@pytest.mark.parametrize("surface", ["document", "editor"])
def test_no_label_text_is_clipped(measured, surface):
    """אף תווית, בשני התרשימים, אינה חורגת מה-``foreignObject`` שלה — מה שחורג נחתך, ובעברית זה סוף המשפט."""
    clipped = {
        row["text"]: round(row["overflow"], 2)
        for labels in measured[surface]["svgs"]
        for row in labels
        if row["overflow"] > TOLERANCE_PX
    }
    assert not clipped, f"תוויות שחורגות מהתיבה שלהן (בפיקסלים): {clipped}"


@pytest.mark.parametrize("surface", ["document", "editor"])
def test_a_label_narrower_than_the_site_width_stays_on_one_line(measured, surface):
    """בלי הנחיה, התווית הבינונית (רחבה מברירת המחדל של Mermaid) נשארת ``nowrap`` ובשורה אחת, כמו הקצרה."""
    site_width = measured[surface]["site_width"]
    assert site_width, "אין window.mermaidSiteConfig בעמוד — הבאנדל לא נבנה מחדש (npm run build-md)"
    labels = _site(measured[surface])
    line = labels[_text(SHORT)]["height"]
    for text in (SHORT, MEDIUM):
        row = labels[_text(text)]
        assert row["whiteSpace"] == "nowrap", row
        assert abs(row["height"] - line) <= TOLERANCE_PX, (row, f"שורה: {line}")
        assert row["width"] < site_width, (row, f"רוחב האתר: {site_width}")


@pytest.mark.parametrize("surface", ["document", "editor"])
def test_labels_wider_than_the_site_width_wrap_at_it(measured, surface):
    """בלי הנחיה, תווית רחבה מרוחב האתר במצב גלישה, ברוחב הזה בדיוק, ובגובה של יותר מהשורות שלה."""
    site_width = measured[surface]["site_width"]
    assert site_width, "אין window.mermaidSiteConfig בעמוד — הבאנדל לא נבנה מחדש (npm run build-md)"
    labels = _site(measured[surface])
    line = labels[_text(SHORT)]["height"]
    for text in (LONG_ONE_LINE, LONG_WITH_BREAK):
        row = labels[_text(text)]
        assert row["whiteSpace"] == "break-spaces", row
        assert abs(row["width"] - site_width) < 1, (row, f"רוחב האתר: {site_width}")
        # התווית עם ``<br/>`` היא כבר שתי שורות בלי שום גלישה; כאן היא צריכה יותר.
        lines_without_wrapping = text.count("<br/>") + 1
        assert row["height"] > lines_without_wrapping * line + TOLERANCE_PX, (row, f"שורה: {line}")


@pytest.mark.parametrize("surface", ["document", "editor"])
def test_a_diagram_directive_overrides_the_site_width(measured, surface):
    """תרשים עם ``%%{init}%%`` נשבר ברוחב שלו: הבינונית, שנשארת בשורה אחת ברוחב האתר, נשברת כאן — וגם התווית מהדיווח."""
    directive_width = _wrapping_width_of(DIRECTIVE_DIAGRAM)
    labels = _with_directive(measured[surface])
    single_line = _site(measured[surface])[_text(SHORT)]["height"]
    for text in (REPORTED, MEDIUM):
        row = labels[_text(text)]
        assert row["whiteSpace"] == "break-spaces", row
        assert abs(row["width"] - directive_width) < 1, (row, f"רוחב ההנחיה: {directive_width}")
        assert row["height"] > single_line + TOLERANCE_PX, (row, f"שורה: {single_line}")
