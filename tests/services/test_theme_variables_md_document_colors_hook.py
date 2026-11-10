"""ווי הדריסה של צבעי המסמך — כותרות, הדגשה, קוד בשורה ופס הציטוט — בתצוגת ה-Markdown ובתצוגה החיה.

התצוגה המרונדרת של VS Code צובעת כותרות והדגשה ב-``editor.foreground``, בלי מפתח משלהן, ולכן לערכה מיובאת אין
מקור לצבעים האלה בקובץ שלה: ערכה בודדת מצהירה עליהם בבלוק ``variables``. הטוקנים נקראים ב-
``webapp/static/css/md-content-colors.css``.

הבדיקות כאן טקסטואליות, כמו של שאר ווי הדריסה: רשימה לבנה, בלי ברירת מחדל בשום מקום, ו-fallback שהוא בדיוק מה
שנצבע היום. את המפל עצמו מודד ``tests/test_md_document_colors_hook_browser.py``.
"""

import json
import re
from pathlib import Path

from services.theme_parser_service import (
    ALLOWED_VARIABLES_WHITELIST,
    FALLBACK_DARK,
    FALLBACK_LIGHT,
    validate_and_sanitize_theme_variables,
    validate_theme_json,
)

HEADING = "--md-heading-color-override"
SUBHEADING = "--md-subheading-color-override"
STRONG = "--md-strong-color-override"
INLINE_CODE = "--md-inline-code-color-override"
QUOTE = "--md-blockquote-border-override"
TOKENS = (HEADING, SUBHEADING, STRONG, INLINE_CODE, QUOTE)

REPO_ROOT = Path(__file__).resolve().parents[2]
CSS_PATH = REPO_ROOT / "webapp/static/css/md-content-colors.css"
DARK_MODE_CSS = REPO_ROOT / "webapp/static/css/dark-mode.css"


def _scoped(*elements):
    """הבורר של כלל שחל רק בתוך המסמך, ורק בערכה מיובאת או משותפת."""
    parts = [f'[data-theme="custom"] #md-content {e}' for e in elements]
    parts += [f'[data-theme^="shared:"] #md-content {e}' for e in elements]
    return ", ".join(parts)


def _normalized(path):
    """ה-CSS בלי הערות ועם רווחים מנורמלים — ההערות שמעל הווים מזכירות את הטוקנים בכוונה."""
    text = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)
    return " ".join(text.split())


def _rule_body(css, selectors):
    """גוף הכלל שהבורר שלו הוא בדיוק ``selectors``, או None."""
    match = re.search(r"(?:^|\})\s*" + re.escape(selectors) + r"\s*\{([^}]*)\}", css)
    return match.group(1) if match else None


def test_tokens_are_whitelisted():
    """בלי זה הטוקנים מסוננים בייבוא ולא מגיעים ל-CSS."""
    for token in TOKENS:
        assert token in ALLOWED_VARIABLES_WHITELIST, token


def test_tokens_survive_the_import_filter():
    """``validate_and_sanitize_theme_variables`` הוא מה שהייבוא מריץ על בלוק ``variables``."""
    declared = {token: "#e1c636" for token in TOKENS}
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
    sources += list((REPO_ROOT / "webapp/templates").rglob("*.html"))
    for path in sources:
        text = path.read_text(encoding="utf-8", errors="replace")
        for token in TOKENS:
            assert not re.search(
                re.escape(token) + r"\s*:", text
            ), f"{token} מקבל ערך ב-{path.name}"


def test_heading_fallback_is_the_typography_rule_of_dark_mode():
    """בלי הטוקן הכותרת נשארת בצבע שכלל ה-Typography של ``dark-mode.css`` נותן לה בערכה מיובאת. אם הצבע שם ישתנה,
    ה-fallback כאן חייב להשתנות איתו — אחרת ערכה שאינה מצהירה תקבל במסמך כותרת בצבע אחר מזה של הממשק.
    """
    headings = ", ".join(
        [f'[data-theme="custom"] h{n}' for n in range(1, 7)]
        + [f'[data-theme^="shared:"] h{n}' for n in range(1, 7)]
    )
    typography = _normalized(DARK_MODE_CSS)
    match = re.search(re.escape(headings) + r"\s*\{([^}]*)\}", typography)
    assert match, "כלל ה-Typography של הערכות המיובאות לא נמצא ב-dark-mode.css"
    assert "color: var(--text-primary);" in match.group(1), match.group(1)

    css = _normalized(CSS_PATH)
    assert f"color: var({HEADING}, var(--text-primary));" in (
        _rule_body(css, _scoped("h1", "h2")) or ""
    )
    assert f"color: var({SUBHEADING}, var(--text-primary));" in (
        _rule_body(css, _scoped("h3", "h4", "h5", "h6")) or ""
    )


def test_strong_falls_back_to_the_color_it_inherits():
    body = _rule_body(_normalized(CSS_PATH), _scoped("strong", "b"))
    assert body is not None, "כלל ההדגשה של צבעי המסמך לא נמצא"
    assert f"color: var({STRONG}, inherit);" in body, body


def test_inline_code_reads_the_token_in_the_existing_rule():
    """הטוקן נקרא בכלל שצובע היום קוד בשורה בערכה מיובאת, ולא בכלל חדש — כך המפל של ערכה שאינה מצהירה זהה."""
    body = _rule_body(_normalized(CSS_PATH), _scoped("code:not(pre code)"))
    assert body is not None, "הכלל של קוד בשורה בערכות המיובאות לא נמצא"
    assert f"color: var({INLINE_CODE}, var(--code-text, var(--text-primary)));" in body, body


def test_blockquote_border_falls_back_to_todays_token():
    body = _rule_body(_normalized(CSS_PATH), "#md-content blockquote")
    assert body is not None, "כלל הציטוט לא נמצא"
    assert (
        f"border-inline-start: 4px solid var({QUOTE}, var(--md-blockquote-border));" in body
    ), body


def test_documented_example_passes_validation():
    """הדוגמה שבתיעוד (``custom_themes_guide.rst``, ``theme-variables-md-document-colors-hook``) עוברת את הוולידציה
    כפי שהיא כתובה."""
    theme = {
        "name": "morass",
        "type": "dark",
        "colors": {
            "editor.background": "#313a36",
            "editor.foreground": "#e4e3e1",
            "focusBorder": "#fdec5a",
        },
        "tokenColors": [],
        "variables": {
            "--primary": "#E1C636",
            HEADING: "#E1C636",
            SUBHEADING: "#cfd394",
            STRONG: "#dcdcaa",
            "--link-color": "#7fdbca",
            INLINE_CODE: "#b5cea8",
            QUOTE: "#E1C636",
        },
    }
    ok, error = validate_theme_json(json.dumps(theme))
    assert ok, error
