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

#: הדברים שבונים את מפל ה-CSS ב-``<head>`` של ``base.html``, לפי סדרם: בלוק
#: ``<style>`` בלי מאפיינים, קישור ל-CSS מקומי, המקום שבו נכנס ``extra_css``,
#: ובלוק ``user-custom-theme`` — Jinja שמזריק את משתני הערכה המותאמת הפעילה.
#: שאר הבלוקים עם ``id`` (הדגשת תחביר, ערכה משותפת) אינם נוגעים בתצוגה החיה.
HEAD_PART_RE = re.compile(
    r"<style>(?P<style>.*?)</style>"
    r"|(?P<custom><style id=\"user-custom-theme\">.*?</style>)"
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
#: **ערכה כהה ולא בהירה, בכוונה.** בערכה בהירה מיובאת התצוגה החיה כולה אינה
#: קריאה עוד לפני התיקון הזה: ``FALLBACK_LIGHT`` קובע ``--split-preview-bg`` כהה
#: ("נשאר כהה גם בתמה בהירה"), ובלוק ה-custom ב-``split-view.css`` לוקח את
#: הטקסט מ-``--text-primary`` הכהה של הערכה. זה פגם נפרד, מחוץ ל-PR הזה.
CUSTOM_VSCODE_THEME = {
    "name": "Live preview test",
    "type": "dark",
    "colors": {"editor.background": "#282a36", "editor.foreground": "#f8f8f2"},
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


def _block(template: str, name: str) -> str:
    match = re.search(r"\{% block " + name + r" %\}(.*?)\{% endblock %\}", template, re.S)
    assert match, f"לא נמצא בלוק {name} ב-{EDIT_TEMPLATE.name}"
    return match.group(1)


def _to_served_paths(fragment: str) -> str:
    return STATIC_URL_RE.sub(lambda m: "/" + m.group(1), fragment)


def custom_theme_variables(vscode_theme: dict) -> dict:
    """המשתנים שערכה מיובאת מקבלת — אותו מסלול כמו ייבוא ב-``themes_api``.

    ``parse_vscode_theme`` ואחריו ``validate_and_sanitize_theme_variables``: כך
    נבדק מה שבאמת נשמר ומוזרק, כולל הרשימה הלבנה, ולא ערכים שנבחרו ביד.
    """
    from services.theme_parser_service import parse_vscode_theme, validate_and_sanitize_theme_variables

    return validate_and_sanitize_theme_variables(parse_vscode_theme(vscode_theme)["variables"])


def _render_custom_theme_block(block: str, variables: dict) -> str:
    """מרנדר את בלוק ה-Jinja האמיתי מ-``base.html``, עם autoescape כמו ב-Flask."""
    from jinja2 import Environment

    return Environment(autoescape=True).from_string(block).render(
        custom_theme={"is_active": True, "variables": variables}
    )


def build_head(custom_variables: dict | None = None) -> str:
    """ה-CSS של עמוד העריכה, בסדר שבו ``base.html`` + ``edit_file.html`` מרכיבים אותו.

    ``custom_variables`` — משתני ערכה מותאמת פעילה. בלעדיהם הבלוק אינו מרונדר,
    בדיוק כמו ב-``base.html`` כשאין ערכה מותאמת פעילה.
    """
    base = BASE_TEMPLATE.read_text(encoding="utf-8")
    head = base[base.index("<head>") : base.index("</head>")]
    extra_css = _to_served_paths(_block(EDIT_TEMPLATE.read_text(encoding="utf-8"), "extra_css"))

    parts: list[str] = []
    saw_extra = saw_custom = False
    for match in HEAD_PART_RE.finditer(head):
        if match.group("style") is not None:
            assert "{{" not in match.group("style") and "{%" not in match.group("style"), (
                "בלוק <style> בלי מאפיינים ב-base.html מכיל Jinja — צריך לעדכן את בניית העמוד"
            )
            parts.append(f"<style>{match.group('style')}</style>")
        elif match.group("custom") is not None:
            saw_custom = True
            if custom_variables:
                parts.append(_render_custom_theme_block(match.group("custom"), custom_variables))
        elif match.group("css") is not None:
            parts.append(f'<link rel="stylesheet" href="/{match.group("css")}">')
        else:
            saw_extra = True
            parts.append(extra_css)
    assert saw_extra, "לא נמצא המקום של extra_css ב-<head> של base.html"
    assert saw_custom, "לא נמצא בלוק user-custom-theme ב-<head> של base.html"
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


def build_page(theme: str, custom_variables: dict | None = None) -> str:
    return (
        f'<!doctype html><html dir="rtl" lang="he" data-theme="{theme}"><head><meta charset="utf-8">'
        f"{build_head(custom_variables)}</head><body>{build_body()}</body></html>"
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


@pytest.fixture(scope="module")
def measured(chromium_executable):
    """מרנדר את אותו Markdown בכל ערכה, דרך הכפתור, ומחזיר את מה שנמדד."""
    custom_variables = custom_theme_variables(CUSTOM_VSCODE_THEME)

    def serve(route):
        path = urlsplit(route.request.url).path
        theme = path.removeprefix("/page-").removesuffix(".html")
        if path.startswith("/page-") and theme in THEMES:
            injected = custom_variables if theme == "custom" else None
            route.fulfill(status=200, content_type="text/html", body=build_page(theme, injected))
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
                results[theme]["injected"] = custom_variables if theme == "custom" else None
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

    assert m["previewBg"] == _hex_to_rgb(injected["--split-preview-bg"]), m["previewBg"]
    assert m["quoteColor"] == _hex_to_rgb(injected["--text-primary"]), m["quoteColor"]


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
