"""וו הדריסה של בלוקי הקוד בתצוגת ה-Markdown של דפדפן הריפו.

בערכה מיובאת, ``webapp/static/css/markdown-preview.css`` צובע את המעטפת
(``.markdown-preview-container``) ב-``--bg-tertiary``, את בלוק הקוד ב-``--code-bg``
ואת הגבול שלו ב-``--border-color`` — שלושה טוקנים ש-``VSCODE_TO_CSS_MAP`` גוזר כל
אחד ממפתחות אחרים של VS Code. בערכה שבה שלושתם יוצאים באותו צבע (Cobalt Next)
הבלוק אינו נבדל מהטקסט שסביבו. שני הטוקנים כאן נותנים לערכה כזו לקבוע לעצמה רקע
וגבול, בלי לגעת בערכות אחרות.

הבדיקות טקסטואליות: הן שומרות על החוזה של וו דריסה — רשימה לבנה, בלי ברירת מחדל
בשום מקום, ו-fallback שהוא בדיוק מה שנצבע היום — ולא מודדות את המפל מחדש.
"""

import json
import re
from pathlib import Path

from services.theme_parser_service import (
    ALLOWED_VARIABLES_WHITELIST,
    FALLBACK_DARK,
    FALLBACK_LIGHT,
    validate_theme_json,
)

BG_TOKEN = "--repo-md-code-block-bg-override"
BORDER_TOKEN = "--repo-md-code-block-border-override"
TOKENS = (BG_TOKEN, BORDER_TOKEN)

REPO_ROOT = Path(__file__).resolve().parents[2]
CSS_PATH = REPO_ROOT / "webapp/static/css/markdown-preview.css"

#: הכלל שצובע היום את בלוק הקוד בערכה מיובאת או משותפת. הטוקנים נקראים בו ולא
#: בכלל חדש, כדי שהמפל של ערכה שאינה מצהירה יישאר זהה.
HOOK_SELECTORS = (
    '[data-theme="custom"] .markdown-preview-content pre, '
    '[data-theme^="shared:"] .markdown-preview-content pre'
)


def _css():
    """ה-CSS בלי הערות ועם רווחים מנורמלים — ההערה שמעל הווו מזכירה את הטוקנים בכוונה."""
    text = re.sub(r"/\*.*?\*/", "", CSS_PATH.read_text(encoding="utf-8"), flags=re.DOTALL)
    return " ".join(text.split())


def _rule_body(css, selectors):
    """גוף הכלל שהבורר שלו הוא בדיוק ``selectors``, או None."""
    match = re.search(r"(?:^|\})\s*" + re.escape(selectors) + r"\s*\{([^}]*)\}", css)
    return match.group(1) if match else None


def test_tokens_are_whitelisted():
    """בלי זה הטוקנים מסוננים בשקט בייבוא ולא מגיעים ל-CSS."""
    for token in TOKENS:
        assert token in ALLOWED_VARIABLES_WHITELIST, token


def test_tokens_are_not_in_the_fallback_dicts():
    """``parse_vscode_theme`` מעתיק את מילון ה-FALLBACK לכל ערכה מיובאת לפני המיפוי.

    טוקן שיושב שם מוגדר בכל ערכה מיובאת, ה-fallback ב-CSS לא רץ אף פעם, והווו
    הופך לשינוי גורף.
    """
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
            assert not re.search(re.escape(token) + r"\s*:", text), f"{token} מקבל ערך ב-{path.name}"


def test_the_imported_theme_rule_reads_both_tokens_with_todays_fallbacks():
    """ה-fallback של כל טוקן הוא מה שהכלל הזה צבע לפני הווו, ולכן ערכה שאינה מצהירה לא זזה."""
    body = _rule_body(_css(), HOOK_SELECTORS)
    assert body is not None, "הכלל של הערכות המיובאות לבלוקי קוד לא נמצא"
    assert f"background: var({BG_TOKEN}, var(--code-bg, var(--bg-secondary, #1e1e1e)));" in body, body
    # ``--md-preview-border`` קורא את ``--border-color`` של הערכה (markdown-preview.css), ולכן בערכה
    # מיובאת שאינה מצהירה על הווו הגבול הוא עדיין הגבול של הערכה, כמו לפני הווו.
    assert f"border-color: var({BORDER_TOKEN}, var(--md-preview-border));" in body, body


def test_the_border_fallback_is_what_the_general_rule_paints():
    """הגבול של הבלוק מגיע מהכלל הכללי ``.markdown-preview-content pre``, ולא מהכלל של הווו.

    אם הצבע שם ישתנה, ה-fallback בווו חייב להשתנות איתו — אחרת ערכה מיובאת שאינה
    מצהירה תקבל גבול שונה מכל שאר הערכות.
    """
    css = _css()
    general = [
        body
        for body in re.findall(r"\}\s*\.markdown-preview-content pre\s*\{([^}]*)\}", css)
        if "border:" in body
    ]
    assert len(general) == 1, general
    color = re.search(r"border: 1px solid ([^;]+);", general[0])
    assert color, general[0]
    assert f"var({BORDER_TOKEN}, {color.group(1).strip()})" in _rule_body(css, HOOK_SELECTORS)


def test_documented_example_passes_validation():
    """הדוגמה שבתיעוד (``custom_themes_guide.rst``) עוברת את הוולידציה כפי שהיא כתובה."""
    theme = {
        "name": "Cobalt Next",
        "type": "dark",
        "colors": {
            "editor.background": "#1b2b34",
            "editor.foreground": "#d8dee9",
            "focusBorder": "#ffffff",
        },
        "tokenColors": [],
        "variables": {
            "--collections-link-override": "#2e6161",
            "--search-suggestion-text-override": "#2e6161",
            BG_TOKEN: "#21313a",
            BORDER_TOKEN: "#374751",
        },
    }
    ok, error = validate_theme_json(json.dumps(theme))
    assert ok, error
