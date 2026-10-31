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
בלוקי ה-``<style>`` וקישורי ה-CSS נשלפים מ-``base.html`` לפי סדרם, הבלוקים
``extra_css`` ו-``extra_js`` נשלפים מ-``edit_file.html`` (או מ-``upload.html``),
מרונדרים ב-Jinja — כדי שה-``{% include %}`` של התלויות המשותפות ייפתר כמו בשרת —
ומוצבים במקום שבו ``base.html`` מציב את הבלוקים. גם ה-DOM של התצוגה החיה נשלף משם.
הרינדור עובר דרך ``LivePreviewController`` האמיתי: לחיצה על כפתור ה-Live Preview,
בדיוק כמו משתמש.

**הבאג השני שהקובץ שומר עליו: בלוק קוד (```).** ב-``live-preview.js``,
``highlightBlocks`` מדגיש רק דרך ``window.SafeHighlight``. שני העמודים לא טענו את
``safe-highlight.js``, ולבלוק לא היה עיצוב: הקוד נראה כמו טקסט בגופן מונו, בלי צבעים (נמדד
לפני התיקון). מאז הבלוק הוא הבלוק של תצוגת המסמך — מסגרת, פס כותרת עם שם השפה וכפתור העתקה,
מ-``md-code-blocks.js`` ומ-``md-content-layout.css``. ``code_measured`` מודד בלוקים בשני העמודים
ובכל ערכה — שורה ארוכה, בלוק עברי, ושפה ש-highlight.js לא מכיר.

**ומה כבר לא נבדק כאן: שהפריסה של התצוגה החיה נכונה בפני עצמה.** הפריסה של התוכן היא של
המסמך (``md-content-layout.css``), ו-``tests/test_live_preview_paper_browser.py`` משווה אותה,
יחד עם הצבעים, לתצוגת המסמך. הבדיקות כאן שומרות על מה שהמשתמש רואה: ציטוט שנראה כציטוט,
רשימה עם תבליטים, טבלה עם קווים, ובלוק קוד שאפשר לקרוא ולהעתיק.

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
UPLOAD_TEMPLATE = TEMPLATES_DIR / "upload.html"

#: העמודים שמארחים את התצוגה החיה. שניהם כוללים את אותם partials של תלויות, ובכל זאת
#: נבדקים שניהם: הבדיקה מודדת את מה שהעמוד בפועל מרכיב, ולא את מה שהוא אמור לכלול.
PAGES = {"edit": EDIT_TEMPLATE, "upload": UPLOAD_TEMPLATE}

MIME_TYPES = {".js": "application/javascript", ".css": "text/css", ".html": "text/html"}

#: קישור לקובץ סטטי מקומי, כפי שהוא כתוב בתבניות.
STATIC_URL_RE = re.compile(r"""\{\{\s*url_for\('static',\s*filename='([^']+)'\)\s*\}\}(?:\?v=\{\{\s*static_version\s*\}\})?""")

#: הדברים שבונים את מפל ה-CSS ב-``<head>`` של ``base.html``, לפי סדרם: בלוק
#: ``<style>`` בלי מאפיינים, קישור ל-CSS מקומי, המקום שבו נכנס ``extra_css``,
#: ובלוקי ``user-custom-theme`` ו-``user-custom-syntax`` — Jinja שמזריק את משתני
#: הערכה המותאמת הפעילה ואת צבעי התחביר שלה. הבלוק השני נוגע בתצוגה החיה מאז שיש בה
#: הדגשה: הוא צובע את ``.hljs`` ברקע של הערכה, ב-``!important``. בלוקי הערכה המשותפת
#: (``shared-theme-*``) אינם נמדדים כאן.
HEAD_PART_RE = re.compile(
    r"<style>(?P<style>.*?)</style>"
    r"|(?P<custom><style id=\"user-custom-theme\">.*?</style>)"
    r"|(?P<syntax><style id=\"user-custom-syntax\">.*?</style>)"
    r"|<link rel=\"stylesheet\" href=\"\{\{ url_for\('static', filename='(?P<css>css/[^']+)'\) \}\}[^\"]*\">"
    r"|(?P<extra>\{% block extra_css %\}\{% endblock %\})",
    re.S,
)

#: הערכות שנמדדות. כל אחת מגיעה לציטוט דרך מסלול טוקנים אחר ב-``split-view.css``:
#: ברירת המחדל, בלוק כהה משותף, בלוקים ייעודיים, ערכה בהירה, ניגודיות גבוהה
#: (שאין לה בלוק ב-``base.html``), וערכה מותאמת שנגזרת מטוקנים סמנטיים.
THEMES = ["classic", "dark", "ocean", "forest", "rose-pine-dawn", "high-contrast", "custom"]

#: הערכה המיובאת שמוזרקת לעמוד של ``custom``. הצבעים שונים מכל ברירת מחדל,
#: כדי ש-``test_the_custom_page_runs_on_the_injected_theme`` יוכל להבחין בין
#: ערכה שהוזרקה לבין נפילה לערכי ה-fallback.
#:
#: ערכה מיובאת **בהירה** נבדקת ב-``tests/test_live_preview_paper_browser.py``, שמשווה את
#: התצוגה החיה לתצוגת המסמך בכל ערכה. עד שהתצוגה החיה קיבלה את הנייר של המסמך, ערכה כזו
#: לא הייתה קריאה בה: ``--split-preview-bg`` כהה מ-``FALLBACK_LIGHT`` מתחת לטקסט הכהה של הערכה.
#:
#: **ועם ``tokenColors``, בשביל בלוק הקוד.** מהם נבנה ה-``syntax_css`` של הערכה, ובו
#: ``:root[data-theme-type="custom"] .hljs`` עם הרקע של העורך ב-``!important``. בלי
#: ``tokenColors`` הכלל הזה לא היה נוצר, והבדיקה שהוא לא מצייר בלוק בתוך הבלוק הייתה
#: עוברת בלי לבדוק כלום.
CUSTOM_VSCODE_THEME = {
    "name": "Live preview test",
    "type": "dark",
    "colors": {"editor.background": "#282a36", "editor.foreground": "#f8f8f2"},
    "tokenColors": [
        {"scope": ["keyword"], "settings": {"foreground": "#ff79c6"}},
        {"scope": ["comment"], "settings": {"foreground": "#6272a4"}},
    ],
}

MARKDOWN = (
    "פסקה ראשונה.\n\n"
    "פסקה רגילה לפני הציטוט.\n\n"
    "> זה ציטוט.\n> עם שורה שנייה.\n\n"
    "פסקה רגילה אחרי הציטוט.\n\n"
    "- פריט ראשון\n- פריט שני\n\n"
    "| כותרת-ארוכה-בעמודה-הראשונה | ב |\n|---|---|\n| 1 | תוכן-ארוך-בעמודה-השנייה-של-הגוף |\n\n"
    "| " + " | ".join(f"עמודה-רחבה-מספר-{i}" for i in range(12)) + " |\n|" + "---|" * 12 + "\n"
    "| " + " | ".join(str(i) for i in range(12)) + " |\n\n"
    "::: note\nפסקה בתוך אדמוניציה.\n:::\n"
)


def _block(template: Path, name: str) -> str:
    match = re.search(
        r"\{% block " + name + r" %\}(.*?)\{% endblock %\}", template.read_text(encoding="utf-8"), re.S
    )
    assert match, f"לא נמצא בלוק {name} ב-{template.name}"
    return match.group(1)


def _to_served_paths(fragment: str) -> str:
    return STATIC_URL_RE.sub(lambda m: "/" + m.group(1), fragment)


def _served_url_for(endpoint: str, filename: str) -> str:
    """``url_for`` של הבדיקה: הנתיב שהשרת של הבדיקה מגיש (``STATIC_DIR`` יושב בשורש)."""
    assert endpoint == "static", endpoint
    return "/" + filename


def _render_fragment(fragment: str, **context) -> str:
    """מרנדר קטע מתבנית של עמוד ב-Jinja, כמו השרת: ``{% include %}`` נפתר מתיקיית התבניות.

    ``StrictUndefined`` בכוונה: משתנה שהבדיקה לא סיפקה נכשל בקול, ולא מתרנדר כמחרוזת ריקה
    שנראית כמו עמוד תקין.
    """
    from jinja2 import Environment, FileSystemLoader, StrictUndefined

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True, undefined=StrictUndefined)
    env.globals["url_for"] = _served_url_for
    return env.from_string(fragment).render(static_version="test", **context)


def custom_theme(vscode_theme: dict) -> dict:
    """הערכה המיובאת כפי ש-``base.html`` מקבל אותה — אותו מסלול כמו ייבוא ב-``themes_api``.

    ``parse_vscode_theme`` ואחריו ``validate_and_sanitize_theme_variables`` למשתנים, ו-
    ``syntax_css`` כפי ש-``parse_vscode_theme`` מחזיר אותו — כך ``themes_api`` שומר אותו
    בייבוא. כך נבדק מה שבאמת נשמר ומוזרק, כולל הרשימה הלבנה, ולא ערכים שנבחרו ביד.
    """
    from services.theme_parser_service import parse_vscode_theme, validate_and_sanitize_theme_variables

    parsed = parse_vscode_theme(vscode_theme)
    return {
        "is_active": True,
        "variables": validate_and_sanitize_theme_variables(parsed["variables"]),
        "syntax_css": parsed["syntax_css"],
    }


def _render_custom_theme_block(block: str, theme: dict) -> str:
    """מרנדר בלוק Jinja אמיתי מ-``base.html``, עם autoescape כמו ב-Flask."""
    from jinja2 import Environment

    return Environment(autoescape=True).from_string(block).render(custom_theme=theme)


def build_head(theme: dict | None = None, template: Path = EDIT_TEMPLATE) -> str:
    """ה-CSS של העמוד, בסדר שבו ``base.html`` + העמוד (``edit_file.html`` כברירת מחדל) מרכיבים אותו.

    ``theme`` — ערכה מותאמת פעילה (``custom_theme``). בלעדיה בלוקי הערכה אינם מרונדרים,
    בדיוק כמו ב-``base.html`` כשאין ערכה מותאמת פעילה.
    """
    base = BASE_TEMPLATE.read_text(encoding="utf-8")
    head = base[base.index("<head>") : base.index("</head>")]
    extra_css = _render_fragment(_block(template, "extra_css"))

    parts: list[str] = []
    saw_extra = saw_custom = saw_syntax = False
    for match in HEAD_PART_RE.finditer(head):
        if match.group("style") is not None:
            assert "{{" not in match.group("style") and "{%" not in match.group("style"), (
                "בלוק <style> בלי מאפיינים ב-base.html מכיל Jinja — צריך לעדכן את בניית העמוד"
            )
            parts.append(f"<style>{match.group('style')}</style>")
        elif match.group("custom") is not None:
            saw_custom = True
            if theme:
                parts.append(_render_custom_theme_block(match.group("custom"), theme))
        elif match.group("syntax") is not None:
            saw_syntax = True
            if theme:
                parts.append(_render_custom_theme_block(match.group("syntax"), theme))
        elif match.group("css") is not None:
            parts.append(f'<link rel="stylesheet" href="/{match.group("css")}">')
        else:
            saw_extra = True
            parts.append(extra_css)
    assert saw_extra, "לא נמצא המקום של extra_css ב-<head> של base.html"
    assert saw_custom, "לא נמצא בלוק user-custom-theme ב-<head> של base.html"
    assert saw_syntax, "לא נמצא בלוק user-custom-syntax ב-<head> של base.html"
    return "\n".join(parts)


def build_body(template: Path = EDIT_TEMPLATE) -> str:
    """ה-DOM של התצוגה החיה מהעמוד, והסקריפטים של ``extra_js``."""
    page = template.read_text(encoding="utf-8")
    start = page.index('<div id="livePreviewRoot"')
    end = page.index('<div class="source-url-block"', start)
    root = page[start:end]
    assert "code_value" in root, f"מבנה ה-textarea ב-{template.name} השתנה"
    root = _render_fragment(root, code_value="")

    base = BASE_TEMPLATE.read_text(encoding="utf-8")
    size_format = re.search(r"<script[^>]*?js/utils/size-format\.js[^>]*?>\s*</script>", base)
    assert size_format, "לא נמצא תג הטעינה של size-format.js ב-base.html"

    return "\n".join(
        [
            # ``resolvePreviewMode`` ו-``isPreviewEligible`` קוראים את השפה ואת
            # שם הקובץ מהטופס; בשני העמודים הם יושבים מחוץ ל-livePreviewRoot.
            '<input id="fileNameInput" type="text" name="file_name" value="notes.md">',
            '<select id="languageSelect" name="language"><option value="markdown" selected>markdown</option></select>',
            root,
            _to_served_paths(size_format.group(0)),
            _render_fragment(_block(template, "extra_js")),
        ]
    )


def build_page(theme_name: str, theme: dict | None = None, template: Path = EDIT_TEMPLATE) -> str:
    # ``data-theme-type="custom"`` — מה שהסקריפט בראש ``base.html`` מציב לצד ``data-theme="custom"``.
    # ה-``syntax_css`` של ערכה מיובאת נשען עליו (``:root[data-theme-type="custom"] .hljs``).
    theme_type = ' data-theme-type="custom"' if theme_name == "custom" else ""
    return (
        f'<!doctype html><html dir="rtl" lang="he" data-theme="{theme_name}"{theme_type}>'
        f'<head><meta charset="utf-8">{build_head(theme, template)}</head>'
        f"<body>{build_body(template)}</body></html>"
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
        statusMargin: getComputedStyle(status).margin,
        quoteColor: qs.color,
        tables: Array.from(canvas.querySelectorAll('table')).map((table) => ({
            // [left, width] של כל תא, שורה אחר שורה — כותרת ואז גוף.
            columns: Array.from(table.querySelectorAll('tr')).map((row) =>
                Array.from(row.children).map((cell) => {
                    const box = cell.getBoundingClientRect();
                    return [Math.round(box.left), Math.round(box.width)];
                })
            ),
            clientWidth: table.clientWidth,
            scrollWidth: table.scrollWidth,
        })),
        canvasClientWidth: canvas.clientWidth,
        canvasScrollWidth: canvas.scrollWidth,
    };
}"""


def _measure_pages(
    chromium_executable, pages: dict[str, str], markdown: str | None, measure_js: str
) -> dict[str, dict]:
    """טוען כל עמוד, מקליד את ה-Markdown, מפעיל את התצוגה החיה בכפתור, ומחזיר מה שנמדד.

    ``pages`` ממפה שם לעמוד HTML; העמוד מוגש ב-``/page-<שם>.html``, וכל השאר מ-``STATIC_DIR``.
    כתובת מחוץ לו (האייקונים של Bootstrap מ-cdnjs) מקבלת 404 — הבדיקה לא תלויה ברשת.

    ``markdown=None`` — העמוד אינו עמוד עריכה (למשל תצוגת המסמך ב-
    ``tests/test_live_preview_paper_browser.py``): נטען ונמדד כמו שהוא, בלי הקלדה ובלי הכפתור.
    """

    def serve(route):
        path = urlsplit(route.request.url).path
        name = path.removeprefix("/page-").removesuffix(".html")
        if path.startswith("/page-") and name in pages:
            route.fulfill(status=200, content_type="text/html", body=pages[name])
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
            for name in pages:
                page = browser.new_page(viewport={"width": 1400, "height": 900})
                page.route("**/*", serve)
                page.goto(f"http://codebot.test/page-{name}.html", wait_until="load")
                if markdown is not None:
                    page.fill('textarea[name="code"]', markdown)
                    page.click('[data-action="toggle-live-preview"]')
                    page.wait_for_selector('[data-preview-status][data-state="ready"]', timeout=15000)
                results[name] = page.evaluate(measure_js)
                page.close()
        finally:
            browser.close()
    return results


@pytest.fixture(scope="module")
def imported_theme():
    return custom_theme(CUSTOM_VSCODE_THEME)


@pytest.fixture(scope="module")
def measured(chromium_executable, imported_theme):
    """מרנדר את אותו Markdown בכל ערכה, דרך הכפתור, ומחזיר את מה שנמדד."""
    pages = {
        theme: build_page(theme, imported_theme if theme == "custom" else None) for theme in THEMES
    }
    results = _measure_pages(chromium_executable, pages, MARKDOWN, MEASURE_JS)
    for theme in THEMES:
        results[theme]["injected"] = imported_theme["variables"] if theme == "custom" else None
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


def test_the_status_line_is_outside_the_markdown_scope(measured):
    """שורת הסטטוס היא ``<p>`` בתוך ``.split-preview-content`` אבל מחוץ ל-canvas."""
    assert measured["dark"]["statusMargin"] == "0px", measured["dark"]["statusMargin"]


def _hex_to_rgb(value: str) -> str:
    value = value.lstrip("#")
    return "rgb({}, {}, {})".format(*(int(value[i : i + 2], 16) for i in (0, 2, 4)))


def test_the_custom_page_runs_on_the_injected_theme(measured):
    """העמוד של ``custom`` רץ על המשתנים שהוזרקו, ולא על ערכי ה-fallback.

    בלי זה, עמוד ``custom`` שבלוק ה-``user-custom-theme`` שלו לא רונדר היה עובר
    את כל שאר הבדיקות על ערכי ברירת המחדל — וזה בדיוק מה שקרה בגרסה הראשונה.
    """
    m = measured["custom"]
    injected = m["injected"]

    # הרקע הוא הנייר של המסמך — ``--bg-primary`` של הערכה, ``editor.background`` בקובץ שלה — ולא
    # ``--split-preview-bg``: המייבא שם בו ערך ברירת מחדל קבוע לכל ערכה, והוא חל עכשיו רק במצבי קוד
    # ו-HTML. ראו ``.split-preview-content[data-mode="markdown"]`` ב-``split-view.css``.
    assert m["previewBg"] == _hex_to_rgb(injected["--bg-primary"]), m["previewBg"]
    # הציטוט בצבע של ציטוט במסמך: ``--md-blockquote-color`` בבלוק של ערכה מותאמת ב-
    # ``md-content-colors.css`` קורא את ``--text-secondary`` של הערכה.
    assert m["quoteColor"] == _hex_to_rgb(injected["--text-secondary"]), m["quoteColor"]


def test_table_columns_line_up_between_header_and_body(measured):
    """``display: block`` על ``<table>`` אינו מפרק את העמודות.

    סוקרים העלו שהעמודות לא יתיישרו בין הכותרת לגוף. ההתנהגות שנמדדה הפוכה:
    ``thead`` ו-``tbody`` שאינם ישירות תחת טבלה נעטפים יחד בטבלה אנונימית אחת
    (CSS 2.1, סעיף 17.2.1), ולכן חולקים את אותן עמודות. בטבלה כאן הכותרת ארוכה
    בעמודה הראשונה והגוף ארוך בשנייה — כל אחת מושכת עמודה אחרת.
    """
    rows = measured["dark"]["tables"][0]["columns"]

    assert len(rows) >= 2
    for row in rows[1:]:
        assert row == rows[0], f"העמודות לא מיושרות: כותרת {rows[0]} מול שורה {row}"


def test_a_wide_table_scrolls_inside_itself(measured):
    """טבלה רחבה נגללת בתוך עצמה, והתצוגה עצמה לא מתרחבת.

    זו הסיבה ל-``display: block``: ``overflow-x`` לא חל על קופסת ``table``. בלעדיו
    הטבלה הרחבה דוחפת את כל ה-canvas לגלילה אופקית, יחד עם שאר התוכן.
    """
    m = measured["dark"]
    wide = m["tables"][1]

    assert wide["scrollWidth"] > wide["clientWidth"], "הטבלה הרחבה לא רחבה מהתצוגה — הבדיקה לא מודדת כלום"
    assert wide["clientWidth"] <= m["canvasClientWidth"]
    assert m["canvasScrollWidth"] <= m["canvasClientWidth"], (
        f"ה-canvas נגלל אופקית ({m['canvasScrollWidth']} > {m['canvasClientWidth']})"
    )


# ---------------------------------------------------------------------------
# בלוק קוד (```) וכפתור ההעתקה
# ---------------------------------------------------------------------------

#: ארבעה בלוקים, כל אחד מכסה מקרה אחר: שפה מוכרת (הדגשה), שורה ארוכה (גלילה בתוך הבלוק),
#: בלוק עברי בלי שפה (``pre.rtl-code``, כיוון rtl — הפריסה השנייה של מיקום הכפתור), ושפה ש-
#: highlight.js לא מכיר: שם ``highlightElement`` נסוג ל-no-highlight ואינו מוסיף ``hljs``
#: (``blockLanguage`` ב-``highlight.js/lib/core.js`` 11.11.1), כלומר עיצוב שנשען על ``.hljs``
#: לא היה חל עליו.
CODE_MARKDOWN = (
    "פסקה לפני הקוד.\n\n"
    "```python\ndef double(x):\n    return x * 2  # comment\n```\n\n"
    '```bash\necho "' + "x" * 300 + '"\n```\n\n'
    "```\nשורה ראשונה בעברית בתוך בלוק קוד\nושורה שנייה בעברית\n```\n\n"
    "```nosuchlang\nplain text in a language that is not registered\n```\n\n"
    "פסקה אחרי הקוד.\n"
)

#: מודד כל ``pre`` בתצוגה, ואת הבלוק של תצוגת המסמך שעוטף אותו (``.code-block`` עם ``.md-code-header``,
#: מ-``md-code-blocks.js``). הגיאומטריה נמדדת אחרי ``scrollIntoView``, כדי ש-``elementFromPoint`` יראה את
#: הכפתור בתוך חלון הגלילה של ה-canvas. ``scroller`` — האלמנט שהשורה הארוכה נגללת בו: ה-``code`` כש-
#: highlight.js עיצב אותו (``#md-content .hljs`` עם ``overflow-x``), אחרת ה-``pre``.
MEASURE_CODE_JS = """() => {
    const canvas = document.querySelector('[data-preview-canvas]');
    const box = (el) => {
        const r = el.getBoundingClientRect();
        return { top: r.top, right: r.right, bottom: r.bottom, left: r.left, width: r.width, height: r.height };
    };
    const blocks = Array.from(canvas.querySelectorAll('pre')).map((pre) => {
        const shell = pre.closest('.code-block');
        (shell || pre).scrollIntoView({ block: 'center' });
        const code = pre.querySelector('code');
        const header = shell ? shell.querySelector('.md-code-header') : null;
        const lang = header ? header.querySelector('.md-code-lang') : null;
        const btn = header ? header.querySelector('.md-copy-btn') : null;
        const ss = shell ? getComputedStyle(shell) : null;
        const ps = getComputedStyle(pre);
        const cs = getComputedStyle(code);
        const keyword = code.querySelector('.hljs-keyword');
        const scroller = [code, pre].find((el) => el.scrollWidth > el.clientWidth) || null;
        const out = {
            shell: !!shell,
            legacyButton: !!pre.querySelector('.code-copy-btn'),
            preClass: pre.className,
            codeClass: code.className,
            direction: ps.direction,
            bg: ss ? ss.backgroundColor : null,
            borderWidth: ss ? parseFloat(ss.borderTopWidth) : 0,
            borderStyle: ss ? ss.borderTopStyle : null,
            radius: ss ? parseFloat(ss.borderTopLeftRadius) : 0,
            margin: ss ? [parseFloat(ss.marginTop), parseFloat(ss.marginBottom)] : [0, 0],
            padding: [ps.paddingTop, ps.paddingRight, ps.paddingBottom, ps.paddingLeft].map(parseFloat),
            codeBg: cs.backgroundColor,
            codePadding: [cs.paddingTop, cs.paddingRight, cs.paddingBottom, cs.paddingLeft].map(parseFloat),
            spans: code.querySelectorAll('[class^="hljs-"], [class*=" hljs-"]').length,
            keywordColor: keyword ? getComputedStyle(keyword).color : null,
            lang: lang ? lang.textContent : null,
            shellBox: shell ? box(shell) : null,
            code: box(code),
            scroller: scroller ? (scroller === code ? 'code' : 'pre') : null,
            btn: null,
        };
        if (btn) {
            const b = box(btn);
            const hit = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
            out.btn = Object.assign(b, { hittable: !!(hit && hit.closest('.md-copy-btn') === btn) });
            if (scroller) {
                scroller.scrollLeft = 200;
                out.scrolledBy = scroller.scrollLeft;
                out.btnAfterScroll = box(btn);
                scroller.scrollLeft = 0;
            }
        }
        return out;
    });
    return {
        blocks: blocks,
        previewBg: getComputedStyle(document.querySelector('[data-preview-content]')).backgroundColor,
        canvasClientWidth: canvas.clientWidth,
        canvasScrollWidth: canvas.scrollWidth,
    };
}"""

CODE_CASES = [f"{page}-{theme}" for page in PAGES for theme in THEMES]


@pytest.fixture(scope="module")
def code_measured(chromium_executable, imported_theme):
    """אותם ארבעה בלוקים בשני העמודים ובכל ערכה."""
    pages = {}
    for page, template in PAGES.items():
        for theme in THEMES:
            pages[f"{page}-{theme}"] = build_page(theme, imported_theme if theme == "custom" else None, template)
    return _measure_pages(chromium_executable, pages, CODE_MARKDOWN, MEASURE_CODE_JS)


def _blocks(code_measured, case):
    blocks = code_measured[case]["blocks"]
    assert len(blocks) == 4, f"{case}: ציפיתי לארבעה בלוקי קוד, נמצאו {len(blocks)}"
    return blocks


@pytest.mark.parametrize("case", CODE_CASES)
def test_code_block_is_a_visible_box(code_measured, case):
    """הבלוק של תצוגת המסמך (``.code-block``): רקע שנבדל מהתצוגה, מסגרת, פינות מעוגלות, ריפוד וריווח
    מסביב — בכל בלוק. ובלי הכפתור הקטן של דפדפן הריפו בפינת ה-``pre``."""
    preview_bg = code_measured[case]["previewBg"]
    for i, b in enumerate(_blocks(code_measured, case)):
        where = f"{case}, בלוק {i}"
        assert b["shell"], f"{where}: ה-pre לא עטוף ב-.code-block"
        assert not b["legacyButton"], f"{where}: הכפתור הקטן (.code-copy-btn) עדיין בתוך ה-pre"
        assert _alpha(b["bg"]) > 0 and b["bg"] != preview_bg, f"{where}: אין רקע לבלוק ({b['bg']})"
        assert b["borderWidth"] >= 1 and b["borderStyle"] == "solid", f"{where}: אין מסגרת"
        assert b["radius"] >= 4, f"{where}: פינות ישרות ({b['radius']}px)"
        assert min(b["padding"][1:]) >= 8, f"{where}: ריפוד צר ({b['padding']})"
        assert min(b["margin"]) >= 8, f"{where}: הבלוק צמוד למה שסביבו ({b['margin']})"


@pytest.mark.parametrize("case", CODE_CASES)
def test_the_code_element_draws_no_box_of_its_own(code_measured, case):
    """הרקע והריפוד הם של ה-``pre`` בלבד.

    ``md_preview.bundle.css`` נותן ל-``code.hljs`` רקע ו-``padding: 1em``, וב-``custom`` ה-
    ``syntax_css`` של הערכה צובע את ``.hljs`` ברקע של העורך ב-``!important``. כל אחד מהם
    היה מצייר בלוק בתוך הבלוק.
    """
    for i, b in enumerate(_blocks(code_measured, case)):
        assert _alpha(b["codeBg"]) == 0, f"{case}, בלוק {i}: ל-code יש רקע משלו ({b['codeBg']})"
        assert b["codePadding"] == [0, 0, 0, 0], f"{case}, בלוק {i}: ל-code יש ריפוד ({b['codePadding']})"


@pytest.mark.parametrize("case", CODE_CASES)
def test_code_is_highlighted(code_measured, case):
    python = _blocks(code_measured, case)[0]
    assert "language-python" in python["codeClass"], python["codeClass"]
    assert python["spans"] > 0, f"{case}: אין הדגשת תחביר בבלוק python"


def test_an_imported_theme_keeps_its_own_syntax_colors(code_measured, imported_theme):
    """הנטרול חל על הרקע של ``.hljs`` בלבד — צבעי התחביר של הערכה המיובאת ממשיכים לחול."""
    assert ".hljs-keyword" in imported_theme["syntax_css"], "ה-syntax_css של הערכה לא צובע מילות מפתח"
    for page in PAGES:
        python = _blocks(code_measured, f"{page}-custom")[0]
        assert python["keywordColor"] == _hex_to_rgb("#ff79c6"), python["keywordColor"]


@pytest.mark.parametrize("case", CODE_CASES)
def test_the_copy_button_sits_in_the_header_strip_on_the_right(code_measured, case):
    """הכפתור בפס הכותרת של הבלוק, מעל הקוד ולא עליו, בצד ימין, ואפשר ללחוץ עליו — ולידו שם השפה.

    כולל הבלוק העברי, שהכיוון שלו rtl: פס הכותרת יורש ``direction: ltr`` מ-``.code-block``, ולכן
    הכפתור מימין גם שם, כמו בתצוגת המסמך.
    """
    blocks = _blocks(code_measured, case)
    assert any(b["direction"] == "rtl" for b in blocks), f"{case}: אין בלוק rtl — הפריסה השנייה לא נמדדת"
    assert blocks[0]["lang"] == "Python", f"{case}: שם השפה של בלוק python הוא {blocks[0]['lang']!r}"
    for i, b in enumerate(blocks):
        where = f"{case}, בלוק {i} ({b['direction']})"
        btn = b["btn"]
        assert btn, f"{where}: אין כפתור העתקה בפס הכותרת"
        assert b["lang"], f"{where}: אין שם שפה בפס הכותרת"
        assert btn["width"] >= 24 and btn["height"] >= 24, f"{where}: כפתור קטן ({btn['width']}×{btn['height']})"
        assert btn["top"] - b["shellBox"]["top"] <= 24, f"{where}: הכפתור לא בראש הבלוק"
        assert b["shellBox"]["right"] - btn["right"] <= 32, f"{where}: הכפתור לא בצד ימין"
        assert btn["bottom"] <= b["code"]["top"], f"{where}: הכפתור מכסה את הקוד"
        assert btn["hittable"], f"{where}: משהו מכסה את הכפתור"


@pytest.mark.parametrize("case", CODE_CASES)
def test_a_long_line_scrolls_inside_the_block(code_measured, case):
    """השורה הארוכה נגללת בתוך הבלוק, והכפתור — בפס הכותרת — לא נגלל איתה.

    בלי גלילה משלו, הבלוק דחף את כל ה-canvas לגלילה אופקית (נמדד לפני התיקון).
    """
    m = code_measured[case]
    long = _blocks(code_measured, case)[1]
    assert long["scroller"], "השורה לא ארוכה מהבלוק — הבדיקה לא מודדת כלום"
    assert m["canvasScrollWidth"] <= m["canvasClientWidth"], (
        f"ה-canvas נגלל אופקית ({m['canvasScrollWidth']} > {m['canvasClientWidth']})"
    )
    assert long["scrolledBy"] > 0, f"ה-{long['scroller']} לא נגלל"
    assert long["btnAfterScroll"]["left"] == long["btn"]["left"], "הכפתור זז עם הגלילה"
