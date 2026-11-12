"""ווי הדריסה של שם הקובץ, התיאור שלו והמטא של כרטיס הקובץ — בעמוד הקבצים ובראש תצוגת הקוד, ה-Markdown וה-HTML.

בערכה מיובאת השם נצבע בכלל הכותרות של ``dark-mode.css`` (``--text-primary``), התיאור בכלל הפסקאות
(``--text-secondary``), והשורות, הגודל והתאריכים בכרטיס יורשים את צבע הטקסט. ערכה שנותנת לשני הטוקנים אותו ערך
— כמו morass — מקבלת כרטיס בצבע אחד. ערכה בודדת מצהירה על צבעים משלה בבלוק ``variables``, והטוקנים נקראים
ב-``webapp/static/css/dark-mode.css``.

הבדיקות כאן אינן צריכות דפדפן, ולכן רצות גם ב-CI: רשימה לבנה, בלי ברירת מחדל בשום מקום, fallback שהוא בדיוק מה
שנצבע היום, ובכל תבנית — ה-class יושב על האלמנט שמציג את שם הקובץ או את התיאור. את המפל עצמו מודד
``tests/test_file_name_colors_hook_browser.py``.
"""

import json
import re
import textwrap
from html.parser import HTMLParser
from pathlib import Path

import pytest

from services.theme_parser_service import (
    ALLOWED_VARIABLES_WHITELIST,
    FALLBACK_DARK,
    FALLBACK_LIGHT,
    validate_and_sanitize_theme_variables,
    validate_theme_json,
)

NAME = "--file-name-color-override"
DESCRIPTION = "--file-description-color-override"
META = "--file-card-meta-color-override"
TOKENS = (NAME, DESCRIPTION, META)

NAME_CLASS = "file-name-text"
DESCRIPTION_CLASS = "file-description-text"
META_CLASS = "file-card-meta"

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = REPO_ROOT / "webapp/templates"
DARK_MODE_CSS = REPO_ROOT / "webapp/static/css/dark-mode.css"

#: כל עמוד שמציג את שם הקובץ בכותרת, והאם הוא מציג גם את התיאור.
NAME_PAGES = {"files.html": True, "view_file.html": True, "md_preview.html": False, "html_preview.html": False}


def _scoped(cls):
    """הבורר של כלל שחל רק בערכה מיובאת או משותפת."""
    return f'[data-theme="custom"] .{cls}, [data-theme^="shared:"] .{cls}'


def _normalized(path):
    """ה-CSS בלי הערות ועם רווחים מנורמלים — ההערה שמעל הווים מזכירה את הטוקנים ואת הבוררים בכוונה."""
    text = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)
    return " ".join(text.split())


def _rule_body(css, selectors):
    """גוף הכלל שהבורר שלו הוא בדיוק ``selectors``, או None."""
    match = re.search(r"(?:^|\})\s*" + re.escape(selectors) + r"\s*\{([^}]*)\}", css)
    return match.group(1) if match else None


def _typography(*elements):
    """הבורר של כלל ה-Typography של הערכות המיובאות ב-``dark-mode.css``, לאלמנטים הנתונים."""
    return ", ".join(
        [f'[data-theme="dark"] {e}' for e in elements]
        + [f'[data-theme="dim"] {e}' for e in elements]
        + [f'[data-theme="nebula"] {e}' for e in elements]
        + [f'[data-theme="custom"] {e}' for e in elements]
        + [f'[data-theme^="shared:"] {e}' for e in elements]
    )


class _ClassedElements(HTMLParser):
    """אוסף, לכל אלמנט בתבנית שנושא אחד מה-classes של הווים, את התג, המאפיינים והטקסט הישיר שלו.

    התבנית נקראת כמו שהיא, עם ה-Jinja: ``{{ file.file_name }}`` הוא הטקסט של האלמנט שמציג את השם. מאפיין כמו
    ``{% if not file.description %} hidden{% endif %}`` נקרא כמה מאפיינים חסרי משמעות, וזה לא מפריע.
    """

    VOID = {"input", "img", "br", "hr", "meta", "link", "source"}

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.found: list[dict] = []
        self._open: list[dict | None] = []

    def handle_starttag(self, tag, attrs):
        attributes = {name: value for name, value in attrs}
        classes = (attributes.get("class") or "").split()
        record = None
        if {NAME_CLASS, DESCRIPTION_CLASS, META_CLASS} & set(classes):
            record = {"tag": tag, "classes": classes, "attrs": attributes, "text": ""}
            self.found.append(record)
        if tag not in self.VOID:
            self._open.append(record)

    def handle_endtag(self, tag):
        if tag not in self.VOID and self._open:
            self._open.pop()

    def handle_data(self, data):
        if self._open and self._open[-1] is not None:
            self._open[-1]["text"] += data


def _hooked(template_name):
    parser = _ClassedElements()
    parser.feed((TEMPLATES / template_name).read_text(encoding="utf-8"))
    return parser.found


def _with_class(found, cls):
    return [e for e in found if cls in e["classes"]]


def test_tokens_are_whitelisted():
    """בלי זה הטוקנים מסוננים בייבוא ולא מגיעים ל-CSS."""
    for token in TOKENS:
        assert token in ALLOWED_VARIABLES_WHITELIST, token


def test_tokens_survive_the_import_filter():
    """``validate_and_sanitize_theme_variables`` הוא מה שהייבוא מריץ על בלוק ``variables``."""
    declared = {token: "#7fdbca" for token in TOKENS}
    assert validate_and_sanitize_theme_variables(declared) == declared


def test_tokens_are_not_in_the_fallback_dicts():
    """``parse_vscode_theme`` מעתיק את מילון ה-FALLBACK לכל ערכה מיובאת לפני המיפוי. טוקן שיושב שם מוגדר בכל ערכה
    מיובאת, ה-fallback ב-CSS לא רץ אף פעם, והווו הופך לשינוי גורף."""
    for token in TOKENS:
        assert token not in FALLBACK_DARK, token
        assert token not in FALLBACK_LIGHT, token


def test_no_stylesheet_or_template_gives_the_tokens_a_value():
    """ערך ברירת מחדל בכל מקום — ``:root`` בתבנית, בלוק בקובץ CSS אחר — מבטל את ה-fallback."""
    sources = list((REPO_ROOT / "webapp/static").rglob("*.css"))
    sources += list(TEMPLATES.rglob("*.html"))
    for path in sources:
        text = path.read_text(encoding="utf-8", errors="replace")
        for token in TOKENS:
            assert not re.search(re.escape(token) + r"\s*:", text), f"{token} מקבל ערך ב-{path.name}"


def test_name_falls_back_to_the_heading_rule():
    """בלי הטוקן השם נשאר בצבע שכלל הכותרות של ``dark-mode.css`` נותן לו בערכה מיובאת. אם הצבע שם ישתנה, ה-
    fallback כאן חייב להשתנות איתו — אחרת ערכה שאינה מצהירה תקבל שם קובץ בצבע אחר משאר הכותרות."""
    css = _normalized(DARK_MODE_CSS)
    headings = _rule_body(css, _typography("h1", "h2", "h3", "h4", "h5", "h6"))
    assert headings is not None, "כלל הכותרות של הערכות המיובאות לא נמצא ב-dark-mode.css"
    assert "color: var(--text-primary);" in headings, headings
    body = _rule_body(css, _scoped(NAME_CLASS))
    assert body is not None, "הכלל של שם הקובץ לא נמצא"
    assert f"color: var({NAME}, var(--text-primary));" in body, body


def test_description_falls_back_to_the_paragraph_rule():
    css = _normalized(DARK_MODE_CSS)
    paragraphs = _rule_body(css, _typography("p"))
    assert paragraphs is not None, "כלל הפסקאות של הערכות המיובאות לא נמצא ב-dark-mode.css"
    assert "color: var(--text-secondary);" in paragraphs, paragraphs
    body = _rule_body(css, _scoped(DESCRIPTION_CLASS))
    assert body is not None, "הכלל של התיאור לא נמצא"
    assert f"color: var({DESCRIPTION}, var(--text-secondary));" in body, body


def test_card_meta_falls_back_to_the_color_it_inherits():
    """השורות, הגודל והתאריכים בכרטיס אינם נצבעים היום בשום כלל — הם יורשים."""
    body = _rule_body(_normalized(DARK_MODE_CSS), _scoped(META_CLASS))
    assert body is not None, "הכלל של המטא בכרטיס לא נמצא"
    assert f"color: var({META}, inherit);" in body, body


@pytest.mark.parametrize("template_name", sorted(NAME_PAGES))
def test_the_name_hook_sits_on_the_element_that_shows_the_file_name(template_name):
    """ה-class נמצא על אלמנט אחד בעמוד, והטקסט שלו הוא שם הקובץ בלבד. בתצוגת ה-HTML השם הוא חלק מכותרת עם
    תחילית ("תצוגת דפדפן:"), ולכן ה-class על ``span`` שעוטף את השם — התחילית נשארת בצבע של הכותרת."""
    names = _with_class(_hooked(template_name), NAME_CLASS)
    assert len(names) == 1, names
    assert names[0]["text"].strip() == "{{ file.file_name }}", names[0]


@pytest.mark.parametrize("template_name", sorted(NAME_PAGES))
def test_the_description_hook_sits_on_the_element_that_shows_the_description(template_name):
    descriptions = _with_class(_hooked(template_name), DESCRIPTION_CLASS)
    if not NAME_PAGES[template_name]:
        assert descriptions == [], "לעמוד הזה אין תיאור"
        return
    assert len(descriptions) == 1, descriptions
    assert descriptions[0]["text"].strip() == "{{ file.description }}", descriptions[0]


def test_the_meta_hook_covers_the_lines_size_and_dates_of_the_card():
    """שלושת האלמנטים שמסומנים ב-``data-testid`` בכרטיס — ורק הם. התגיות וכפתורי הפעולה אינם מטא."""
    meta = _with_class(_hooked("files.html"), META_CLASS)
    assert sorted(e["attrs"].get("data-testid") for e in meta) == [
        "file-card-dates",
        "file-card-lines",
        "file-card-size",
    ], meta


def test_the_meta_hook_is_only_in_the_files_card():
    for template_name in sorted(set(NAME_PAGES) - {"files.html"}):
        assert _with_class(_hooked(template_name), META_CLASS) == [], template_name


def test_the_cross_tab_sync_named_in_the_docs_keeps_data_theme_type():
    """הנימוק לבורר ``[data-theme]`` ולא ``[data-theme-type]``, כפי שהוא כתוב בתיעוד וב-``dark-mode.css``: סנכרון
    הערכה בין טאבים (``initThemeCrossTabSync`` ב-``base.html``) מציב ``data-theme`` של ערכה מובנית שנבחרה בטאב אחר,
    ואינו נוגע ב-``data-theme-type``. אם הפונקציה תשנה שם או תתחיל לעדכן את ``data-theme-type``, הנימוק בפרוזה
    מתיישן — והטסט הזה הוא מה שיזכיר לעדכן אותו."""
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    marker = "(function initThemeCrossTabSync(){"
    assert base.count(marker) == 1, "initThemeCrossTabSync, שהתיעוד נוקב בשמו, לא נמצא פעם אחת ב-base.html"
    start = base.index(marker)
    body = base[start : base.index("})();", start)]
    assert "setAttribute('data-theme', " in body, body
    assert "data-theme-type" not in body, "הסנכרון בין טאבים מעדכן עכשיו את data-theme-type — לעדכן את הנימוק בתיעוד"
    for path in (DARK_MODE_CSS, REPO_ROOT / "docs/webapp/custom_themes_guide.rst"):
        assert "initThemeCrossTabSync" in path.read_text(encoding="utf-8"), path.name


def _documented_variables():
    """בלוק ``variables`` של הדוגמה בתיעוד — בלוק ה-JSON הראשון אחרי העוגן ``theme-variables-file-name-hook`` ב-
    ``custom_themes_guide.rst`` — כפי שהוא כתוב שם. נקרא מהתיעוד ולא מועתק לכאן: עותק בטסט נשאר מאחור כשהדוגמה
    משתנה, וממשיך לעבור על צבעים שכבר אינם בתיעוד."""
    lines = (REPO_ROOT / "docs/webapp/custom_themes_guide.rst").read_text(encoding="utf-8").splitlines()
    anchor = ".. _theme-variables-file-name-hook:"
    assert lines.count(anchor) == 1, "העוגן של הסעיף לא נמצא פעם אחת בתיעוד"
    # הדירקטיבה בעמודה 0 (``index`` משווה שורה שלמה), ולכן לפי RST הבלוק שלה נגמר בשורה הראשונה שאינה ריקה
    # ומתחילה גם היא בעמודה 0 — בלי הנחה על עומק ההזחה. אופציות (``:caption:``) צמודות לדירקטיבה, לפני התוכן.
    directive = lines.index(".. code-block:: json", lines.index(anchor))
    body = []
    for line in lines[directive + 1 :]:
        if line.strip() and not line[0].isspace():
            break
        body.append(line)
    while body and body[0].strip().startswith(":"):
        body.pop(0)
    snippet = textwrap.dedent("\n".join(body)).strip()
    parsed = json.loads("{" + snippet + "}")
    assert "variables" in parsed, f"בלוק ה-JSON של הדוגמה אינו בלוק variables: {snippet!r}"
    return parsed["variables"]


def test_documented_example_passes_validation():
    """הדוגמה שבתיעוד (``custom_themes_guide.rst``, ``theme-variables-file-name-hook``) מצהירה על שלושת הטוקנים,
    ועוברת את הוולידציה ואת הסינון של הייבוא כפי שהיא כתובה."""
    variables = _documented_variables()
    assert set(variables) == set(TOKENS), variables
    theme = {
        "name": "morass",
        "type": "dark",
        "colors": {
            "editor.background": "#313a36",
            "editor.foreground": "#e4e3e1",
            "focusBorder": "#fdec5a",
        },
        "tokenColors": [],
        "variables": variables,
    }
    ok, error = validate_theme_json(json.dumps(theme))
    assert ok, error
    assert validate_and_sanitize_theme_variables(variables) == variables
