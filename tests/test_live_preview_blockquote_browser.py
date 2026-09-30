"""ציטוט (``>``) בתצוגה החיה של עורך הקבצים נראה כציטוט, בכל ערכות הנושא.

**הבאג שהבדיקה הזו נולדה ממנו.** ``live-preview.js`` מרנדר Markdown עם
markdown-it, והפלט **כן** כולל ``<blockquote>``. אבל כלל העיצוב היחיד של ציטוט
Markdown ישב ב-``<style>`` הפנימי של ``md_preview.html``, ועמוד העריכה אינו טוען
אותו. מה שכן חל על ``<blockquote>`` שם הוא כלל האיפוס ``*`` מבלוק ה-``<style>``
של ``base.html``, שמאפס את ה-``margin`` — ובכך מוחק גם את ההזחה שהדפדפן נותן
לציטוט כברירת מחדל. התוצאה: ציטוט שנראה בדיוק כמו פסקה רגילה. האדמוניציות
(``::: note``) לא נפגעו, כי העיצוב שלהן יושב ב-``markdown-enhanced.css`` שנטען
גלובלית.

**למה העמוד נבנה מהתבניות ולא נכתב כאן (T1).** הבאג הוא מפל CSS: מה נטען, באיזה
סדר, ומה דורס מה. עמוד שנכתב ביד היה בודק את המפל שהבדיקה מקווה שקיים. לכן:
בלוקי ה-``<style>`` וקישורי ה-CSS נשלפים מ-``base.html`` לפי סדרם, קישורי
``extra_css`` ו-``extra_js`` נשלפים מ-``edit_file.html`` ומוצבים במקום שבו
``base.html`` מציב את הבלוקים, וגם ה-DOM של התצוגה החיה נשלף משם. הרינדור עובר
דרך ``LivePreviewController`` האמיתי: לחיצה על כפתור ה-Live Preview, בדיוק כמו
משתמש.

מדולג כשאין Chromium.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "webapp" / "static"
TEMPLATES_DIR = REPO_ROOT / "webapp" / "templates"
BASE_TEMPLATE = TEMPLATES_DIR / "base.html"
EDIT_TEMPLATE = TEMPLATES_DIR / "edit_file.html"

MIME_TYPES = {".js": "application/javascript", ".css": "text/css", ".html": "text/html"}

#: קישור לקובץ סטטי מקומי, כפי שהוא כתוב בתבניות.
STATIC_URL_RE = re.compile(r"""\{\{\s*url_for\('static',\s*filename='([^']+)'\)\s*\}\}(?:\?v=\{\{\s*static_version\s*\}\})?""")

#: שלושת הדברים שבונים את מפל ה-CSS ב-``<head>`` של ``base.html``, לפי סדרם:
#: בלוק ``<style>`` בלי מאפיינים (הבלוקים עם ``id`` מוזרקים לערכה מותאמת
#: ומכילים Jinja), קישור ל-CSS מקומי, והמקום שבו נכנס ``extra_css``.
HEAD_PART_RE = re.compile(
    r"<style>(?P<style>.*?)</style>"
    r"|<link rel=\"stylesheet\" href=\"\{\{ url_for\('static', filename='(?P<css>css/[^']+)'\) \}\}[^\"]*\">"
    r"|(?P<extra>\{% block extra_css %\}\{% endblock %\})",
    re.S,
)

#: הערכות שנמדדות. כל אחת מגיעה לציטוט דרך מסלול טוקנים אחר ב-``split-view.css``:
#: ברירת המחדל, בלוק כהה משותף, בלוקים ייעודיים, ערכה בהירה, ניגודיות גבוהה
#: (שאין לה בלוק ב-``base.html``), וערכה מותאמת שנגזרת מטוקנים סמנטיים.
THEMES = ["classic", "dark", "ocean", "forest", "rose-pine-dawn", "high-contrast", "custom"]

MARKDOWN = (
    "פסקה ראשונה.\n\n"
    "פסקה רגילה לפני הציטוט.\n\n"
    "> זה ציטוט.\n> עם שורה שנייה.\n\n"
    "פסקה רגילה אחרי הציטוט.\n\n"
    "- פריט ראשון\n- פריט שני\n\n"
    "| א | ב |\n|---|---|\n| 1 | 2 |\n\n"
    "::: note\nפסקה בתוך אדמוניציה.\n:::\n"
)


def _block(template: str, name: str) -> str:
    match = re.search(r"\{% block " + name + r" %\}(.*?)\{% endblock %\}", template, re.S)
    assert match, f"לא נמצא בלוק {name} ב-{EDIT_TEMPLATE.name}"
    return match.group(1)


def _to_served_paths(fragment: str) -> str:
    return STATIC_URL_RE.sub(lambda m: "/" + m.group(1), fragment)


def build_head() -> str:
    """ה-CSS של עמוד העריכה, בסדר שבו ``base.html`` + ``edit_file.html`` מרכיבים אותו."""
    base = BASE_TEMPLATE.read_text(encoding="utf-8")
    head = base[base.index("<head>") : base.index("</head>")]
    extra_css = _to_served_paths(_block(EDIT_TEMPLATE.read_text(encoding="utf-8"), "extra_css"))

    parts: list[str] = []
    saw_extra = False
    for match in HEAD_PART_RE.finditer(head):
        if match.group("style") is not None:
            assert "{{" not in match.group("style") and "{%" not in match.group("style"), (
                "בלוק <style> בלי מאפיינים ב-base.html מכיל Jinja — צריך לעדכן את בניית העמוד"
            )
            parts.append(f"<style>{match.group('style')}</style>")
        elif match.group("css") is not None:
            parts.append(f'<link rel="stylesheet" href="/{match.group("css")}">')
        else:
            saw_extra = True
            parts.append(extra_css)
    assert saw_extra, "לא נמצא המקום של extra_css ב-<head> של base.html"
    return "\n".join(parts)


def build_body() -> str:
    """ה-DOM של התצוגה החיה מ-``edit_file.html``, והסקריפטים של ``extra_js``."""
    edit = EDIT_TEMPLATE.read_text(encoding="utf-8")
    start = edit.index('<div id="livePreviewRoot"')
    end = edit.index('<div class="source-url-block"', start)
    root = edit[start:end]
    assert "{{" in root and "code_value" in root, "מבנה ה-textarea ב-edit_file.html השתנה"
    root = re.sub(r"\{\{\s*code_value\s*\}\}", "", root)
    assert "{{" not in root and "{%" not in root, "נשאר Jinja ב-DOM של התצוגה החיה"

    base = BASE_TEMPLATE.read_text(encoding="utf-8")
    size_format = re.search(r"<script[^>]*?js/utils/size-format\.js[^>]*?>\s*</script>", base)
    assert size_format, "לא נמצא תג הטעינה של size-format.js ב-base.html"

    return "\n".join(
        [
            # ``resolvePreviewMode`` ו-``isPreviewEligible`` קוראים את השפה ואת
            # שם הקובץ מהטופס; ב-edit_file.html הם יושבים מחוץ ל-livePreviewRoot.
            '<input id="fileNameInput" type="text" name="file_name" value="notes.md">',
            '<select id="languageSelect" name="language"><option value="markdown" selected>markdown</option></select>',
            root,
            _to_served_paths(size_format.group(0)),
            _to_served_paths(_block(edit, "extra_js")),
        ]
    )


def build_page(theme: str) -> str:
    return (
        f'<!doctype html><html dir="rtl" lang="he" data-theme="{theme}"><head><meta charset="utf-8">'
        f"{build_head()}</head><body>{build_body()}</body></html>"
    )


MEASURE_JS = """() => {
    const canvas = document.querySelector('[data-preview-canvas]');
    const quote = canvas.querySelector('blockquote');
    const para = canvas.querySelector(':scope > p');
    if (!quote || !para) {
        return { rendered: false, html: canvas.innerHTML.slice(0, 500) };
    }
    const qs = getComputedStyle(quote);
    const paras = canvas.querySelectorAll(':scope > p');
    const li = canvas.querySelector('li');
    const td = canvas.querySelector('td');
    const admonitionP = canvas.querySelector('.admonition-content > p');
    const status = document.querySelector('[data-preview-status]');
    const inner = quote.querySelector('p') || quote;
    // RTL: תחילת השורה היא הקצה הימני.
    const inset = para.getBoundingClientRect().right - inner.getBoundingClientRect().right;
    return {
        rendered: true,
        borderWidth: parseFloat(qs.borderInlineStartWidth),
        borderStyle: qs.borderInlineStartStyle,
        borderColor: qs.borderInlineStartColor,
        quoteBg: qs.backgroundColor,
        previewBg: getComputedStyle(document.querySelector('[data-preview-content]')).backgroundColor,
        inset: inset,
        paragraphGap: paras[1].getBoundingClientRect().top - paras[0].getBoundingClientRect().bottom,
        listInset: li ? para.getBoundingClientRect().right - li.getBoundingClientRect().right : null,
        cellBorderWidth: td ? parseFloat(getComputedStyle(td).borderTopWidth) : null,
        cellBorderStyle: td ? getComputedStyle(td).borderTopStyle : null,
        admonitionFirstMarginTop: admonitionP ? getComputedStyle(admonitionP).marginTop : null,
        statusMargin: getComputedStyle(status).margin,
    };
}"""


@pytest.fixture(scope="module")
def measured(chromium_executable):
    """מרנדר את אותו Markdown בכל ערכה, דרך הכפתור, ומחזיר את מה שנמדד."""

    def serve(route):
        path = urlsplit(route.request.url).path
        theme = path.removeprefix("/page-").removesuffix(".html")
        if path.startswith("/page-") and theme in THEMES:
            route.fulfill(status=200, content_type="text/html", body=build_page(theme))
            return
        target = (STATIC_DIR / path.lstrip("/")).resolve()
        if not target.is_file() or STATIC_DIR.resolve() not in target.parents:
            route.fulfill(status=404, body="")
            return
        route.fulfill(
            status=200,
            content_type=MIME_TYPES.get(target.suffix, "text/plain"),
            body=target.read_bytes(),
        )

    results: dict[str, dict] = {}
    with sync_playwright() as p:
        try:
            browser = (
                p.chromium.launch(executable_path=chromium_executable)
                if chromium_executable
                else p.chromium.launch()
            )
        except Exception as exc:  # noqa: BLE001 — כל כשל השקה פירושו אין דפדפן
            pytest.skip(f"אין Chromium זמין: {exc}")
        try:
            for theme in THEMES:
                page = browser.new_page(viewport={"width": 1400, "height": 900})
                page.route("**/*", serve)
                page.goto(f"http://codebot.test/page-{theme}.html", wait_until="load")
                page.fill('textarea[name="code"]', MARKDOWN)
                page.click('[data-action="toggle-live-preview"]')
                page.wait_for_selector('[data-preview-status][data-state="ready"]', timeout=15000)
                results[theme] = page.evaluate(MEASURE_JS)
                page.close()
        finally:
            browser.close()
    return results


def _alpha(color: str) -> float:
    """ערוץ השקיפות של צבע מחושב (``rgb(...)`` / ``rgba(...)`` / ``color(srgb ...)``)."""
    if color.startswith("rgba("):
        return float(color[5:-1].split(",")[3])
    if color.startswith("color(") and "/" in color:
        return float(color.rsplit("/", 1)[1].rstrip(") "))
    return 1.0


@pytest.mark.parametrize("theme", THEMES)
def test_blockquote_has_a_visible_start_border(measured, theme):
    """הפס בתחילת הציטוט — הסימן שמבדיל ציטוט מפסקה."""
    m = measured[theme]
    assert m["rendered"], f"markdown-it לא רינדר ציטוט: {m.get('html')!r}"

    assert m["borderWidth"] >= 2, f"{theme}: אין פס בתחילת הציטוט ({m['borderWidth']}px)"
    assert m["borderStyle"] == "solid", f"{theme}: סגנון הפס {m['borderStyle']!r}"
    assert _alpha(m["borderColor"]) > 0, f"{theme}: הפס שקוף ({m['borderColor']})"
    assert m["borderColor"] != m["previewBg"], f"{theme}: הפס בצבע הרקע ({m['borderColor']})"


@pytest.mark.parametrize("theme", THEMES)
def test_blockquote_text_is_inset_from_the_surrounding_paragraphs(measured, theme):
    """הטקסט של הציטוט מוזח פנימה ביחס לפסקה שלידו — ולא מתחיל באותו קו."""
    m = measured[theme]
    assert m["rendered"], f"markdown-it לא רינדר ציטוט: {m.get('html')!r}"

    assert m["inset"] >= 8, f"{theme}: הציטוט מתחיל באותו קו כמו פסקה רגילה (הזחה {m['inset']}px)"


@pytest.mark.parametrize("theme", THEMES)
def test_blockquote_background_is_distinct_from_the_preview(measured, theme):
    """רקע הציטוט נבדל מרקע התצוגה, ואינו שקוף."""
    m = measured[theme]
    assert m["rendered"], f"markdown-it לא רינדר ציטוט: {m.get('html')!r}"

    assert _alpha(m["quoteBg"]) > 0, f"{theme}: רקע הציטוט שקוף ({m['quoteBg']})"
    assert m["quoteBg"] != m["previewBg"], f"{theme}: רקע הציטוט זהה לרקע התצוגה ({m['quoteBg']})"


@pytest.mark.parametrize("theme", THEMES)
def test_paragraphs_do_not_stick_together(measured, theme):
    """שתי פסקאות נפרדות נראות כשתיים, ולא כפסקה אחת עם שבירת שורה."""
    assert measured[theme]["paragraphGap"] >= 8, f"{theme}: פסקאות צמודות ({measured[theme]['paragraphGap']}px)"


@pytest.mark.parametrize("theme", THEMES)
def test_list_items_leave_room_for_their_markers(measured, theme):
    """בלי הזחה התבליט יושב מחוץ ל-canvas ונחתך — הרשימה נראית כשורות טקסט."""
    inset = measured[theme]["listInset"]
    assert inset is not None, "markdown-it לא רינדר רשימה"
    assert inset >= 8, f"{theme}: פריט הרשימה מתחיל באותו קו כמו פסקה (הזחה {inset}px)"


@pytest.mark.parametrize("theme", THEMES)
def test_table_cells_have_borders(measured, theme):
    m = measured[theme]
    assert m["cellBorderWidth"] is not None, "markdown-it לא רינדר טבלה"
    assert m["cellBorderWidth"] >= 1 and m["cellBorderStyle"] == "solid", (
        f"{theme}: לתא אין קו ({m['cellBorderWidth']}px, {m['cellBorderStyle']})"
    )


def test_admonitions_keep_their_own_spacing(measured):
    """הכללים עטופים ב-``:where()`` כדי שלא ינצחו את ``markdown-enhanced.css``.

    שם ``.admonition-content > *:first-child`` מאפס את השוליים העליונים של
    הפסקה הראשונה. כלל ``p`` בספציפיות מלאה היה דורס אותו ומזיז את התוכן
    של כל אדמוניציה — והאדמוניציות הן בדיוק מה שעבד לפני התיקון.
    """
    assert measured["dark"]["admonitionFirstMarginTop"] == "0px", measured["dark"]["admonitionFirstMarginTop"]


def test_the_status_line_is_outside_the_markdown_scope(measured):
    """שורת הסטטוס היא ``<p>`` בתוך ``.split-preview-content`` אבל מחוץ ל-canvas."""
    assert measured["dark"]["statusMargin"] == "0px", measured["dark"]["statusMargin"]
