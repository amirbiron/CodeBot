"""
Theme Parser Service
מפרסר ערכות נושא מפורמטים שונים ומייצר CSS Variables

⚠️ אבטחה:
- אין לאפשר ערכי CSS מסוכנים (url/expression/javascript וכו')
- ולידציה מוגבלת במכוון ל-Hex/RGB/RGBA בלבד כדי לצמצם סיכוני CSS injection
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from services.vscode_token_theme import (
    CM_CLASS_TAGS,
    CM_TAG_REPRESENTATIVES,
    GENERIC_ROOT_SCOPE,
    HLJS_LANGUAGES,
    HLJS_REPRESENTATIVES,
    TokenStyle,
    VSCodeTokenTheme,
    is_valid_hex_color,
)

logger = logging.getLogger(__name__)

# ==========================================
# 🔒 SECURITY: Regex לוולידציה של צבעים
# ==========================================
# ⚠️ אזהרה חשובה: ה-Regex הזה מכוון להיות **מגביל**.
# אל תרחיב אותו לקבל פורמטים נוספים ללא בדיקה קפדנית!
#
# מאפשר **רק**:
#   - Hex: #fff, #ffff, #ffffff, #ffffffff
#   - RGB: rgb(r, g, b)
#   - RGBA: rgba(r, g, b, a)
# ==========================================
_RGB_COMPONENT_REGEX = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"  # 0..255
_RGBA_ALPHA_REGEX = r"(?:0(?:\.\d+)?|1(?:\.0+)?|\.\d+)"  # 0..1 (כולל 1.0, .5)

# ⚠️ שים לב: חייב להיות מסונכרן עם normalize_color_to_rgba (כל מה שמאושר כאן חייב להינרמל בהצלחה)
VALID_COLOR_REGEX = re.compile(
    rf"^(?:"
    rf"(?:#[0-9a-fA-F]{{3}}|#[0-9a-fA-F]{{4}}|#[0-9a-fA-F]{{6}}|#[0-9a-fA-F]{{8}})"  # hex: 3/4/6/8
    rf"|rgb\(\s*{_RGB_COMPONENT_REGEX}\s*,\s*{_RGB_COMPONENT_REGEX}\s*,\s*{_RGB_COMPONENT_REGEX}\s*\)"
    rf"|rgba\(\s*{_RGB_COMPONENT_REGEX}\s*,\s*{_RGB_COMPONENT_REGEX}\s*,\s*{_RGB_COMPONENT_REGEX}\s*,\s*{_RGBA_ALPHA_REGEX}\s*\)"
    rf")$"
)

# ערך blur (px) - נדרש עבור --glass-blur במערכת הקיימת
_VALID_PX_REGEX = re.compile(r'^\d{1,3}(\.\d{1,2})?px$')

# רשימה לבנה של משתני CSS מותרים - אל תוסיף משתנים ללא בדיקה
# ⚠️ הרשימה מסונכרנת עם מסמך הארכיטקטורה: docs/webapp/theming_and_css.rst
ALLOWED_VARIABLES_WHITELIST = frozenset([
    # Level 1 - Primitives
    "--primary", "--primary-hover", "--primary-light",
    "--secondary",
    "--success", "--warning", "--error",
    "--danger-bg", "--danger-border", "--text-on-warning",
    "--glass", "--glass-blur", "--glass-border", "--glass-hover",

    # Level 2 - Semantic Tokens (רקעים וטקסט)
    "--bg-primary", "--bg-secondary", "--bg-tertiary",
    "--text-primary", "--text-secondary", "--text-muted",
    "--border-color", "--shadow-color",
    "--card-bg", "--card-border",
    "--navbar-bg",
    "--input-bg", "--input-border",
    "--link-color",
    "--code-bg", "--code-text", "--code-border",

    # Level 2 - כפתורים (Button Tokens)
    "--btn-primary-bg", "--btn-primary-color", "--btn-primary-border", "--btn-primary-shadow",
    "--btn-primary-hover-bg", "--btn-primary-hover-color",

    # Level 2 - Markdown & Split View
    "--md-surface", "--md-text",
    "--split-preview-bg", "--split-preview-meta", "--split-preview-placeholder",

    # Level 2 - Markdown Enhanced (inline code, tables, mermaid)
    "--md-inline-code-bg", "--md-inline-code-border", "--md-inline-code-color",
    "--md-table-bg", "--md-table-border", "--md-table-header-bg",
    "--md-mermaid-bg",

    # Level 3 - Collections
    # מאפשר לערכה בודדת לקבוע את צבע שמות הקבצים בכרטיס אוסף, בלי שהדבר
    # ישפיע על ערכות אחרות. ראו את וו הדריסה ב-webapp/static/css/collections.css.
    "--collections-link-override",

    # Level 3 - Global Search
    # מאפשר לערכה בודדת לקבוע את צבע הטקסט בהצעות ההשלמה של החיפוש הגלובלי.
    # אותו מסלול בדיוק: ההצעות הן <a>, ולכן [data-theme="custom"] a צובע אותן
    # ב---primary על רקע לבן קבוע. ראו את וו הדריסה ב-
    # webapp/static/css/global_search.css.
    "--search-suggestion-text-override",

    # Level 3 - Repo Browser (Markdown preview)
    # מאפשר לערכה בודדת לקבוע את הרקע ואת הגבול של בלוקי הקוד בתצוגת ה-Markdown של
    # דפדפן הריפו, בלי שהדבר ישפיע על ערכות אחרות. ראו את וו הדריסה ב-
    # webapp/static/css/markdown-preview.css.
    "--repo-md-code-block-bg-override",
    "--repo-md-code-block-border-override",

    # Level 3 - Primary buttons
    # מאפשר לערכה בודדת לקבוע את צבע הטקסט של כפתור primary בכל מקום שבו הוא נצבע
    # היום ב---primary: כפתור שהוא <a> (דרך [data-theme="custom"] a), הכפתורים "ערוך"
    # ו"העתק קוד", ומצבי פוקוס/לחיצה. ראו את וו הדריסה ב-webapp/static/css/dark-mode.css,
    # בבלוק primary-btn-states-custom-type ב-webapp/templates/base.html, וב-
    # webapp/templates/view_file.html.
    "--btn-primary-text-override",

    # Level 3 - ערכה מיובאת בהירה
    # הרכיבים האלה צבועים בצבעים קבועים לרקע כהה (לבן שקוף, טקסט כמעט לבן), כמו כל ערכה
    # מיובאת, ולערכה בהירה אין דרך לקבוע אותם. כל טוקן נקרא בכלל שצובע היום את הרכיב, עם
    # fallback לערך שנצבע בו היום:
    # - שדות טופס: .form-field ב-webapp/static/css/file-editor.css (עריכה והעלאה), וה-style
    #   של שדות הסינון ב-webapp/templates/files.html.
    # - הפיד והפוש בדשבורד: .timeline-item, .timeline-group, .timeline-badge-*, .status-*
    #   ב-webapp/templates/dashboard.html.
    # - שורת החיפוש בתצוגת ה-Markdown: .md-search-capsule ב-webapp/templates/md_preview.html.
    "--form-field-border-override",
    "--form-field-bg-override",
    "--form-field-focus-border-override",
    "--timeline-block-bg-override",
    "--timeline-item-border-override",
    "--timeline-badge-text-override",
    "--status-pill-text-override",
    "--md-search-capsule-border-override",
])


# מיפוי בין VS Code keys לבין CSS Variables שלנו
# ⚠️ הערה: חלק מהמפתחות ממופים לרשימה של משתנים (כאשר ערך אחד צריך למלא כמה טוקנים)
VSCODE_TO_CSS_MAP = {
    # רקעים - editor.background ממלא גם את --md-surface למניעת "לבן מסנוור" ב-Markdown
    "editor.background": ["--bg-primary", "--md-surface"],
    "sideBar.background": "--bg-secondary",
    "activityBar.background": "--bg-tertiary",
    "tab.activeBackground": "--bg-primary",
    "input.background": "--input-bg",
    "dropdown.background": "--bg-secondary",
    "panel.background": "--bg-secondary",

    # טקסט - editor.foreground ממלא גם את --md-text לעקביות ב-Markdown Preview
    "editor.foreground": ["--text-primary", "--md-text"],
    "sideBar.foreground": "--text-secondary",
    "descriptionForeground": "--text-muted",
    "input.foreground": "--text-primary",

    # כפתורים (Level 2 Tokens) - לא משתמשים ב---primary הגנרי!
    # button.background ממלא גם את הגבול למניעת אי-תאימות ויזואלית
    "button.background": ["--btn-primary-bg", "--btn-primary-border"],
    "button.foreground": "--btn-primary-color",
    "button.hoverBackground": "--btn-primary-hover-bg",
    "focusBorder": "--primary",
    "textLink.foreground": "--link-color",
    "textLink.activeForeground": "--primary-hover",

    # גבולות
    "input.border": "--input-border",
    "panel.border": "--border-color",
    "sideBar.border": "--border-color",
    "tab.border": "--border-color",
    "activityBar.border": "--border-color",

    # סטטוסים ושגיאות - שימוש ב---danger-bg לפי ארכיטקטורת הטוקנים
    "notificationsErrorIcon.foreground": ["--error", "--danger-bg"],
    "notificationsWarningIcon.foreground": "--warning",
    "notificationsInfoIcon.foreground": "--primary",
    "testing.iconPassed": "--success",
    "testing.iconFailed": "--error",
    "editorError.foreground": "--error",
    "editorWarning.foreground": "--warning",

    # קוד
    "terminal.background": "--code-bg",
    "terminal.foreground": "--code-text",

    # Navbar / Header
    "titleBar.activeBackground": "--navbar-bg",
    "titleBar.inactiveBackground": "--navbar-bg",
    "statusBar.background": "--navbar-bg",

    # Cards
    "editorWidget.background": "--card-bg",
    "editorHoverWidget.background": "--card-bg",
}


# ערכי fallback למקרה שחסרים
# מסונכרן עם מסמך הארכיטקטורה: docs/webapp/theming_and_css.rst
FALLBACK_DARK = {
    # רקעים וטקסט
    "--bg-primary": "#1e1e1e",
    "--bg-secondary": "#252526",
    "--bg-tertiary": "#333333",
    "--text-primary": "#d4d4d4",
    "--text-secondary": "#9d9d9d",
    "--text-muted": "#6d6d6d",

    # צבעי מותג
    "--primary": "#569cd6",
    "--primary-hover": "#6cb6ff",
    "--primary-light": "#569cd626",

    # גבולות וצללים
    "--border-color": "#474747",
    "--shadow-color": "rgba(0, 0, 0, 0.4)",

    # סטטוסים (Level 1)
    "--success": "#4ec9b0",
    "--warning": "#dcdcaa",
    "--error": "#f44747",
    "--danger-bg": "#f44747",
    "--danger-border": "#d32f2f",
    "--text-on-warning": "#1a1a1a",

    # קוד
    "--code-bg": "#1e1e1e",
    "--code-text": "#d4d4d4",
    "--code-border": "#474747",

    # UI elements
    "--link-color": "#569cd6",
    "--navbar-bg": "#323233",
    "--card-bg": "#252526",
    "--card-border": "#474747",
    "--input-bg": "#3c3c3c",
    "--input-border": "#474747",

    # כפתורים (Level 2)
    "--btn-primary-bg": "#569cd6",
    "--btn-primary-color": "#ffffff",
    "--btn-primary-border": "#569cd6",
    "--btn-primary-shadow": "rgba(86, 156, 214, 0.3)",
    "--btn-primary-hover-bg": "#6cb6ff",
    "--btn-primary-hover-color": "#ffffff",

    # Markdown & Split View (Level 2)
    "--md-surface": "#1e1e1e",
    "--md-text": "#d4d4d4",

    # Glass (Level 1)
    "--glass": "rgba(255, 255, 255, 0.05)",
    "--glass-border": "rgba(255, 255, 255, 0.1)",
    "--glass-hover": "rgba(255, 255, 255, 0.08)",
    "--glass-blur": "20px",

    # Split View (Level 2 subset for this guide)
    # ``--split-preview-bg`` צובע את התצוגה החיה רק במצבי קוד ו-HTML. במצב Markdown היא על הנייר של
    # המסמך (``--md-paper-bg`` ב-``webapp/static/css/md-content-colors.css``), שנגזר מ-``--bg-primary``
    # — ``editor.background`` של הערכה — ולכן הערך הקבוע כאן לא חל עליה שם.
    "--split-preview-bg": "#1e1e1e",
    "--split-preview-meta": "#9d9d9d",
    "--split-preview-placeholder": "#6d6d6d",
}

FALLBACK_LIGHT = {
    # רקעים וטקסט
    "--bg-primary": "#ffffff",
    "--bg-secondary": "#f3f3f3",
    "--bg-tertiary": "#e5e5e5",
    "--text-primary": "#333333",
    "--text-secondary": "#616161",
    "--text-muted": "#9e9e9e",

    # צבעי מותג
    "--primary": "#007acc",
    "--primary-hover": "#005a9e",
    "--primary-light": "#007acc26",

    # גבולות וצללים
    "--border-color": "#d4d4d4",
    "--shadow-color": "rgba(0, 0, 0, 0.1)",

    # סטטוסים (Level 1)
    "--success": "#388a34",
    "--warning": "#bf8803",
    "--error": "#e51400",
    "--danger-bg": "#e51400",
    "--danger-border": "#c62828",
    "--text-on-warning": "#1a1a1a",

    # קוד
    "--code-bg": "#f3f3f3",
    "--code-text": "#333333",
    "--code-border": "#d4d4d4",

    # UI elements
    "--link-color": "#007acc",
    "--navbar-bg": "#dddddd",
    "--card-bg": "#ffffff",
    "--card-border": "#d4d4d4",
    "--input-bg": "#ffffff",
    "--input-border": "#cecece",

    # כפתורים (Level 2)
    "--btn-primary-bg": "#007acc",
    "--btn-primary-color": "#ffffff",
    "--btn-primary-border": "#007acc",
    "--btn-primary-shadow": "rgba(0, 122, 204, 0.3)",
    "--btn-primary-hover-bg": "#005a9e",
    "--btn-primary-hover-color": "#ffffff",

    # Markdown & Split View — ערך כהה גם בתמה בהירה, ו-``editor.background`` / ``editor.foreground``
    # דורסים אותו (``VSCODE_TO_CSS_MAP``). התצוגה החיה במצב Markdown אינה קוראת אותו: ראו ההערה על
    # ``--split-preview-bg`` ב-``FALLBACK_DARK``.
    "--md-surface": "#1e1e1e",
    "--md-text": "#d4d4d4",

    # Glass (Level 1)
    "--glass": "rgba(0, 0, 0, 0.02)",
    "--glass-border": "rgba(0, 0, 0, 0.05)",
    "--glass-hover": "rgba(0, 0, 0, 0.04)",
    "--glass-blur": "20px",

    # Split View (Level 2 subset for this guide)
    "--split-preview-bg": "#1e1e1e",
    "--split-preview-meta": "#9d9d9d",
    "--split-preview-placeholder": "#6d6d6d",
}


def is_valid_color(value: str) -> bool:
    """בודק אם הערך הוא צבע תקני לפי ה-Regex המגביל (Hex/RGB/RGBA בלבד)."""
    if not value or not isinstance(value, str):
        return False
    return bool(VALID_COLOR_REGEX.match(value.strip()))


def _is_valid_px(value: str) -> bool:
    if not value or not isinstance(value, str):
        return False
    return bool(_VALID_PX_REGEX.match(value.strip().lower()))


def sanitize_css_value(value: str) -> str | None:
    """
    מנקה ומוודא שערך CSS בטוח לשימוש.

    ⚠️ מחזיר None אם הערך לא בטוח!
    """
    if not value or not isinstance(value, str):
        return None

    value = value.strip().lower()

    # חסימת ערכים מסוכנים במפורש
    dangerous_patterns = [
        "url(", "expression(", "javascript:",
        "data:", "behavior:", "binding:",
        "@import", "@charset", "<", ">",
        "/*", "*/", "\\", "\n", "\r",
    ]

    for pattern in dangerous_patterns:
        if pattern in value:
            logger.warning("Blocked dangerous CSS value: %s...", value[:50])
            return None

    # וולידציה כצבע
    if VALID_COLOR_REGEX.match(value):
        return value

    return None


def validate_and_sanitize_theme_variables(variables: dict) -> dict:
    """
    מוודא ומנקה את כל המשתנים בערכה.

    Returns:
        מילון מנוקה עם רק משתנים בטוחים
    """
    sanitized: dict[str, str] = {}

    if not isinstance(variables, dict):
        return sanitized

    for key, value in variables.items():
        if key not in ALLOWED_VARIABLES_WHITELIST:
            logger.warning("Skipped unknown variable: %s", key)
            continue

        # --glass-blur הוא px (לא צבע)
        if key == "--glass-blur":
            if isinstance(value, str) and _is_valid_px(value):
                sanitized[key] = value.strip().lower()
            else:
                logger.warning("Skipped invalid value for %s: %s", key, str(value)[:30])
            continue

        clean_value = sanitize_css_value(value)  # type: ignore[arg-type]
        if clean_value:
            sanitized[key] = clean_value
        else:
            try:
                logger.warning("Skipped invalid value for %s: %s...", key, str(value)[:30])
            except Exception:
                logger.warning("Skipped invalid value for %s", key)

    return sanitized


def strip_jsonc_comments(json_content: str) -> str:
    """
    מסיר הערות JSONC מתוכן JSON.

    VS Code themes עשויים להכיל הערות /* */ או // שלא נתמכות ב-JSON סטנדרטי.
    פונקציה זו מסירה אותן בצורה בטוחה תוך שמירה על strings.

    Args:
        json_content: תוכן JSON/JSONC גולמי

    Returns:
        תוכן JSON ללא הערות
    """
    result = []
    i = 0
    in_string = False
    escape_next = False

    while i < len(json_content):
        char = json_content[i]

        # Handle escape sequences inside strings
        if escape_next:
            result.append(char)
            escape_next = False
            i += 1
            continue

        if in_string:
            result.append(char)
            if char == "\\":
                escape_next = True
            elif char == '"':
                in_string = False
            i += 1
            continue

        # Not in string - check for comments
        if char == '"':
            in_string = True
            result.append(char)
            i += 1
            continue

        # Check for // single-line comment
        if char == "/" and i + 1 < len(json_content) and json_content[i + 1] == "/":
            # Skip until end of line
            while i < len(json_content) and json_content[i] != "\n":
                i += 1
            continue

        # Check for /* multi-line comment */
        if char == "/" and i + 1 < len(json_content) and json_content[i + 1] == "*":
            i += 2  # Skip /*
            # Find closing */
            while i + 1 < len(json_content):
                if json_content[i] == "*" and json_content[i + 1] == "/":
                    i += 2  # Skip */
                    break
                i += 1
            else:
                # Unclosed comment - skip to end
                i = len(json_content)
            continue

        result.append(char)
        i += 1

    return "".join(result)


def _validate_variables_block(variables: object) -> tuple[bool, str]:
    """מוודא בלוק ``variables`` של ערכה — שם המשתנה וערכו.

    מוחזר ``(True, "")`` כשהבלוק תקין, ואחרת ``(False, <הודעה שמציינת את המפתח>)``.
    """
    if not isinstance(variables, dict):
        return False, "'variables' חייב להיות אובייקט"

    for key, value in variables.items():
        if not str(key).startswith("--"):
            return False, f"משתנה CSS חייב להתחיל ב---: {key}"
        if str(key) == "--glass-blur":
            if not _is_valid_px(str(value)):
                return False, f"ערך blur לא תקין: {key}={value}"
        else:
            if not is_valid_color(str(value)):
                return False, f"ערך צבע לא תקין: {key}={value}"

    return True, ""


def validate_theme_json(json_content: str) -> tuple[bool, str]:
    """מוודא שקובץ JSON הוא ערכת נושא תקינה."""
    # הסרת הערות JSONC לפני פרסור (VS Code themes עשויים להכיל /* */ או //)
    cleaned_content = strip_jsonc_comments(json_content)

    try:
        data = json.loads(cleaned_content)
    except json.JSONDecodeError:
        # 🔒 אבטחה: לא מחזירים הודעת חריגה גולמית ללקוח
        logger.exception("Invalid theme JSON content")
        return False, "קובץ JSON לא תקין"

    if not isinstance(data, dict):
        return False, "הקובץ חייב להיות אובייקט JSON"

    # בלוק variables נבדק בשני המסלולים. ערכת VS Code יכולה לשאת אותו כדי לדרוס
    # טוקן שאין לו מקבילה ב-VS Code, וללא הבדיקה הזו ערך פגום בו היה נזרק בשקט
    # אחרי שהמשתמש כבר קיבל "יובאה בהצלחה" — כשל שמדווח כהצלחה.
    if "variables" in data:
        ok, error = _validate_variables_block(data["variables"])
        if not ok:
            return False, error

    # בדיקה אם זו ערכת VS Code
    if "colors" in data:
        if not isinstance(data["colors"], dict):
            return False, "'colors' חייב להיות אובייקט"
        if len(data["colors"]) < 3:
            return False, "ערכת VS Code חייבת להכיל לפחות 3 צבעים"
        return True, ""

    # בדיקה אם זו ערכה בפורמט שלנו
    if "variables" in data:
        return True, ""

    return False, "הקובץ חייב להכיל 'colors' (VS Code) או 'variables' (פורמט מקומי)"


def parse_native_theme(json_content: str | dict) -> dict:
    """
    מפרסר ערכה בפורמט המקומי שלנו.
    """
    if isinstance(json_content, str):
        data = json.loads(json_content)
    else:
        data = json_content

    variables = data.get("variables", {}) if isinstance(data, dict) else {}
    validated_vars = validate_and_sanitize_theme_variables(variables)

    return {
        "name": (data.get("name") if isinstance(data, dict) else None) or "Imported Theme",
        "description": (data.get("description") if isinstance(data, dict) else None) or "",
        "variables": validated_vars,
    }


def parse_vscode_theme(json_content: str | dict) -> dict:
    """
    מפרסר ערכת VS Code ומייצר מילון של CSS Variables.

    Returns:
        מילון עם:
        - name: שם הערכה
        - type: "dark" או "light"
        - variables: CSS Variables
        - syntax_css: CSS להדגשת תחביר (Pygments + CodeMirror fallback)
        - syntax_colors: מילון צבעים לפי tag עבור CodeMirror HighlightStyle דינמי
    """
    if isinstance(json_content, str):
        try:
            # VS Code themes עשויים להיות JSONC (עם // או /* */)
            cleaned = strip_jsonc_comments(json_content)
            theme_data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}")
    else:
        theme_data = json_content

    if not isinstance(theme_data, dict):
        raise ValueError("Theme must be a JSON object")

    colors = theme_data.get("colors", {})
    if not colors:
        raise ValueError("Theme must contain a 'colors' object")

    theme_type = (theme_data.get("type", "dark") or "dark").lower()
    fallback = FALLBACK_DARK if theme_type == "dark" else FALLBACK_LIGHT

    # מיפוי הצבעים
    result = fallback.copy()

    for vscode_key, css_vars in VSCODE_TO_CSS_MAP.items():
        if vscode_key in colors:
            color_value = colors[vscode_key]
            if is_valid_color(str(color_value)):
                if isinstance(css_vars, list):
                    for css_var in css_vars:
                        result[css_var] = str(color_value)
                else:
                    result[css_vars] = str(color_value)
            else:
                logger.warning("Invalid color value for %s: %s", vscode_key, str(color_value))

    result = _compute_derived_colors(result)

    # 🎨 יצירת CSS להדגשת תחביר מ-tokenColors
    syntax_css_parts = []
    syntax_colors: dict[str, dict] = {}
    token_colors = theme_data.get("tokenColors", [])

    if token_colors:
        # צבע הטקסט של העורך: מה ש-VS Code נותן לטוקן שאף כלל בערכה לא צובע
        editor_fg = colors.get("editor.foreground")
        editor_bg = colors.get("editor.background")

        # 🆕 מילון צבעים לפי tag (עבור HighlightStyle דינמי)
        syntax_colors = generate_syntax_colors_from_tokens(token_colors, editor_fg)

        # CodeMirror CSS (.tok-* classes) - fallback
        cm_css = generate_codemirror_css_from_tokens(token_colors, editor_fg)
        cm_css = sanitize_codemirror_css(cm_css)
        if cm_css:
            syntax_css_parts.append("/* CodeMirror syntax highlighting */")
            syntax_css_parts.append(cm_css)

        # Pygments CSS (.source .k, .source .c, etc.)
        py_css = generate_pygments_css_from_tokens(token_colors)
        if py_css:
            syntax_css_parts.append("\n/* Pygments syntax highlighting */")
            syntax_css_parts.append(py_css)

        # 🆕 Highlight.js CSS (.hljs-* classes) - for Markdown Preview
        # מעבירים את צבעי ברירת המחדל לטקסט שלא מסומן (משתנים, קבועים וכו')
        hljs_css = generate_hljs_css_from_tokens(token_colors, editor_fg, editor_bg)
        if hljs_css:
            syntax_css_parts.append("\n/* Highlight.js syntax highlighting (Preview) */")
            syntax_css_parts.append(hljs_css)

    syntax_css = "\n".join(syntax_css_parts)

    return {
        "name": theme_data.get("name", "Imported Theme"),
        "type": theme_type,
        "variables": result,
        "syntax_css": syntax_css,
        "syntax_colors": syntax_colors,  # 🆕 לשימוש ב-HighlightStyle דינמי
    }


def _compute_derived_colors(variables: dict) -> dict:
    """
    מחשב צבעים נגזרים שלא קיימים ישירות ב-VS Code.
    """
    result = variables.copy()

    # primary-light מבוסס על primary
    if "--primary" in result and "--primary-light" not in result:
        primary = result["--primary"]
        result["--primary-light"] = color_with_opacity(primary, 0.15)

    # shadow-color מבוסס על סוג הערכה
    if "--shadow-color" not in result:
        bg = result.get("--bg-primary", "#000")
        if _is_dark_color(str(bg)):
            result["--shadow-color"] = "rgba(0, 0, 0, 0.4)"
        else:
            result["--shadow-color"] = "rgba(0, 0, 0, 0.1)"

    # גזירת טוקני כפתורים למניעת אי-תאימות ויזואלית
    if "--btn-primary-bg" in result and "--btn-primary-border" not in result:
        result["--btn-primary-border"] = result["--btn-primary-bg"]

    if "--btn-primary-hover-bg" in result and "--btn-primary-hover-color" not in result:
        result["--btn-primary-hover-color"] = result.get("--btn-primary-color", "#ffffff")

    if "--btn-primary-bg" in result and "--btn-primary-shadow" not in result:
        result["--btn-primary-shadow"] = color_with_opacity(result["--btn-primary-bg"], 0.3)

    return result


# ==========================================
# פונקציות עזר למניפולציית צבעים בטוחה
# ==========================================

def normalize_color_to_rgba(color: str) -> tuple[int, int, int, float] | None:
    """
    ממיר כל פורמט צבע תקני ל-tuple של (R, G, B, A).

    תומך ב:
    - Hex מקוצר: #fff
    - Hex מלא: #ffffff
    - Hex עם alpha: #ffffffff
    - RGB: rgb(255, 255, 255)
    - RGBA: rgba(255, 255, 255, 0.5)
    """
    if not color or not isinstance(color, str):
        return None

    color = color.strip().lower()

    # Hex format
    if color.startswith("#"):
        hex_val = color[1:]

        if len(hex_val) == 3:
            r = int(hex_val[0] * 2, 16)
            g = int(hex_val[1] * 2, 16)
            b = int(hex_val[2] * 2, 16)
            return (r, g, b, 1.0)
        if len(hex_val) == 4:
            r = int(hex_val[0] * 2, 16)
            g = int(hex_val[1] * 2, 16)
            b = int(hex_val[2] * 2, 16)
            a = int(hex_val[3] * 2, 16) / 255
            return (r, g, b, a)
        if len(hex_val) == 6:
            try:
                r = int(hex_val[0:2], 16)
                g = int(hex_val[2:4], 16)
                b = int(hex_val[4:6], 16)
                return (r, g, b, 1.0)
            except ValueError:
                return None
        if len(hex_val) == 8:
            try:
                r = int(hex_val[0:2], 16)
                g = int(hex_val[2:4], 16)
                b = int(hex_val[4:6], 16)
                a = int(hex_val[6:8], 16) / 255
                return (r, g, b, a)
            except ValueError:
                return None
        return None

    # RGB format
    rgb_match = re.match(
        rf"^rgb\(\s*({_RGB_COMPONENT_REGEX})\s*,\s*({_RGB_COMPONENT_REGEX})\s*,\s*({_RGB_COMPONENT_REGEX})\s*\)$",
        color,
    )
    if rgb_match:
        r, g, b = map(int, rgb_match.groups())
        if all(0 <= c <= 255 for c in (r, g, b)):
            return (r, g, b, 1.0)
        return None

    # RGBA format
    rgba_match = re.match(
        rf"^rgba\(\s*({_RGB_COMPONENT_REGEX})\s*,\s*({_RGB_COMPONENT_REGEX})\s*,\s*({_RGB_COMPONENT_REGEX})\s*,\s*({_RGBA_ALPHA_REGEX})\s*\)$",
        color,
    )
    if rgba_match:
        r, g, b = map(int, rgba_match.groups()[:3])
        try:
            a = float(rgba_match.group(4))
        except ValueError:
            return None
        if all(0 <= c <= 255 for c in (r, g, b)) and 0.0 <= a <= 1.0:
            return (r, g, b, a)
        return None

    return None


def rgba_to_css(r: int, g: int, b: int, a: float) -> str:
    """ממיר RGBA tuple למחרוזת CSS."""
    if a >= 0.999:
        return f"#{r:02x}{g:02x}{b:02x}"
    return f"rgba({r}, {g}, {b}, {a:.2f})"


def color_with_opacity(color: str, opacity: float) -> str:
    """
    מחזיר צבע עם שקיפות חדשה.
    """
    rgba = normalize_color_to_rgba(color)
    if rgba is None:
        return "rgba(128, 128, 128, 0.15)"
    r, g, b, _ = rgba
    return rgba_to_css(r, g, b, opacity)


def lighten_color(color: str, amount: float = 0.2) -> str:
    rgba = normalize_color_to_rgba(color)
    if rgba is None:
        return color
    r, g, b, a = rgba
    r = min(255, int(r + (255 - r) * amount))
    g = min(255, int(g + (255 - g) * amount))
    b = min(255, int(b + (255 - b) * amount))
    return rgba_to_css(r, g, b, a)


def darken_color(color: str, amount: float = 0.2) -> str:
    rgba = normalize_color_to_rgba(color)
    if rgba is None:
        return color
    r, g, b, a = rgba
    r = max(0, int(r * (1 - amount)))
    g = max(0, int(g * (1 - amount)))
    b = max(0, int(b * (1 - amount)))
    return rgba_to_css(r, g, b, a)


def _is_dark_color(hex_color: str) -> bool:
    """בודק אם צבע hex הוא כהה (luminance נמוך)."""
    if not isinstance(hex_color, str) or not hex_color.startswith("#"):
        return True

    hex_val = hex_color.lstrip("#")
    if len(hex_val) == 3:
        hex_val = "".join(c * 2 for c in hex_val)
    if len(hex_val) not in (6, 8):
        return True

    try:
        r = int(hex_val[0:2], 16)
        g = int(hex_val[2:4], 16)
        b = int(hex_val[4:6], 16)
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return luminance < 0.5
    except Exception:
        return True


# ==========================================
# Syntax Highlighting: tokenColors → CodeMirror ו-highlight.js
# ==========================================
# הצבע של כל מחלקה הוא מה ש-VS Code נותן לטוקן שהיא צובעת: ההכרעה והנציגים ב-``services/vscode_token_theme.py``.
# Pygments (``TOKEN_TO_PYGMENTS_MAP`` למטה) נשאר עם המיפוי הישן. הוא צובע קוד שמרונדר בשרת ב-Pygments: עמוד הקובץ והייצוא שבשרת.


TOKEN_TO_PYGMENTS_MAP: dict[str, str] = {
    # ===========================================
    # Comments
    # ===========================================
    "comment": ".c",
    "comment.line": ".c1",
    "comment.block": ".cm",
    "comment.block.documentation": ".cm",
    "punctuation.definition.comment": ".c",

    # ===========================================
    # Strings
    # ===========================================
    "string": ".s",
    "string.quoted": ".s",
    "string.quoted.single": ".s1",
    "string.quoted.double": ".s2",
    "string.quoted.triple": ".s",
    "string.template": ".s",
    "string.regexp": ".sr",
    "string.interpolated": ".si",
    "string.other": ".s",

    # ===========================================
    # Keywords
    # ===========================================
    "keyword": ".k",
    "keyword.control": ".k",
    "keyword.control.flow": ".k",
    "keyword.control.import": ".kn",
    "keyword.control.export": ".kn",
    "keyword.control.conditional": ".k",
    "keyword.control.loop": ".k",
    "keyword.control.return": ".k",
    "keyword.control.trycatch": ".k",
    "keyword.other": ".k",
    "keyword.other.unit": ".k",
    "keyword.operator": ".o",

    # ===========================================
    # Storage (types and modifiers)
    # ===========================================
    "storage": ".k",
    "storage.type": ".kt",
    "storage.type.function": ".kd",
    "storage.type.class": ".kd",
    "storage.modifier": ".kd",
    "storage.modifier.async": ".k",

    # ===========================================
    # Constants (numbers, booleans, etc.)
    # ===========================================
    "constant": ".kc",
    "constant.numeric": ".m",
    "constant.numeric.integer": ".mi",
    "constant.numeric.float": ".mf",
    "constant.numeric.hex": ".mh",
    "constant.numeric.octal": ".mo",
    "constant.numeric.binary": ".mb",
    "constant.language": ".kc",  # true, false, null
    "constant.character": ".sc",
    "constant.character.escape": ".se",
    "constant.other": ".kc",

    # ===========================================
    # Functions
    # ===========================================
    "entity.name.function": ".nf",
    "entity.name.function.method": ".nf",
    "entity.name.function.decorator": ".nd",
    "support.function": ".nf",
    "meta.function-call": ".nf",

    # ===========================================
    # Classes and Types
    # ===========================================
    "entity.name.class": ".nc",
    "entity.name.type": ".nc",
    "entity.name.type.class": ".nc",
    "support.class": ".nc",
    "support.type": ".kt",
    "entity.other.inherited-class": ".nc",

    # ===========================================
    # Variables
    # ===========================================
    "variable": ".n",
    "variable.other": ".n",
    "variable.parameter": ".n",
    "variable.language": ".nb",  # self, this
    "variable.function": ".nf",

    # ===========================================
    # HTML/XML Tags and Attributes
    # ===========================================
    "entity.name.tag": ".nt",
    "entity.other.attribute-name": ".na",
    "punctuation.definition.tag": ".p",

    # ===========================================
    # Operators and Punctuation
    # ===========================================
    "punctuation": ".p",
    "punctuation.separator": ".p",
    "punctuation.definition.string": ".p",

    # ===========================================
    # Markdown
    # ===========================================
    "entity.name.section.markdown": ".gh",  # Generic.Heading
    "markup.heading": ".gh",
    "markup.bold": ".gs",
    "markup.italic": ".ge",
    "markup.raw": ".s",  # code block
    "markup.inline.raw": ".s",
    "markup.deleted": ".gd",
    "markup.inserted": ".gi",
    "markup.changed": ".go",

    # ===========================================
    # Invalid/Error
    # ===========================================
    "invalid": ".err",
    "invalid.deprecated": ".err",
}


# ==========================================
# 🎨 Dynamic Syntax Colors (for HighlightStyle.define)
# ==========================================


def _hex_or_none(value: object) -> str | None:
    """צבע ברירת מחדל נכנס להכרעה רק אם VS Code היה מקבל אותו (``isValidHexColor``)."""
    return value if isinstance(value, str) and is_valid_hex_color(value) else None


def _resolve_generic(theme: VSCodeTokenTheme, stack: tuple[str, ...]) -> TokenStyle:
    return theme.resolve((GENERIC_ROOT_SCOPE, *stack))


def _css_declarations(style: TokenStyle) -> list[str]:
    """ההצהרות של כלל צבע, עם ``!important`` כדי לדרוס את גיליון ברירת המחדל. בלי צבע — אין כלל.

    ``strikethrough`` לא נכתב: הניקוי של ``syntax_css`` (``_sanitize_custom_theme_rules``) מקבל רק את שלושת אלה.
    """
    if not style.foreground:
        return []
    parts = [f"color: {style.foreground} !important"]
    if style.italic:
        parts.append("font-style: italic !important")
    if style.bold:
        parts.append("font-weight: bold !important")
    if style.underline:
        parts.append("text-decoration: underline !important")
    return parts


def generate_syntax_colors_from_tokens(token_colors: list[dict], default_foreground: str | None = None) -> dict[str, dict]:
    """
    ממיר tokenColors של VS Code למילון צבעים עבור CodeMirror HighlightStyle.

    לכל tag ב-``CM_TAG_REPRESENTATIVES``, הצבע ש-VS Code נותן לטוקן שה-tag מסמן. ``default_foreground``
    (``editor.foreground``) הוא הצבע של tag ש-VS Code משאיר בצבע ברירת המחדל; בלעדיו tag כזה לא נכתב.

    Returns:
        מילון בפורמט: {
            "keyword": {"color": "#ff0000"},
            "controlKeyword": {"color": "#00ff00", "fontWeight": "bold"},
            ...
        }
    """
    if not isinstance(token_colors, list):
        return {}

    theme = VSCodeTokenTheme(token_colors, default_foreground=_hex_or_none(default_foreground))
    colors_by_tag: dict[str, dict] = {}
    for tag, stack in CM_TAG_REPRESENTATIVES.items():
        resolved = _resolve_generic(theme, stack)
        if not resolved.foreground:
            continue
        style: dict[str, str] = {"color": resolved.foreground}
        if resolved.italic:
            style["fontStyle"] = "italic"
        if resolved.bold:
            style["fontWeight"] = "bold"
        if resolved.underline:
            style["textDecoration"] = "underline"
        colors_by_tag[tag] = style
    return colors_by_tag


#: הבורר שכללי ``generate_hljs_css_from_tokens`` נכתבים תחתיו כברירת מחדל: ערכה מותאמת או משותפת באתר.
HLJS_SITE_THEME_SELECTOR_PREFIX = ':root[data-theme-type="custom"]'


def hljs_language_selector_suffix(class_names: tuple[str, ...]) -> str:
    """הסיומת של כלל לפי שפה: ``:is(.language-python *, .language-py *)``.

    הבלוק נושא ``language-<שם>`` על ה-``<code>`` (highlight.js מוסיף את השם הקנוני ב-``updateClassName``), והטוקן הוא
    צאצא שלו. ``:is()`` מוסיף לספציפיות בדיוק מחלקה אחת — כך שהכלל גובר על הכלל הכללי של אותה מחלקה — והוא עובד באותה
    צורה בקידומת של האתר (אב של הבלוק) ובזו של הייצוא (הבלוק עצמו).
    """
    return ":is(" + ", ".join(f".language-{name} *" for name in class_names) + ")"


def generate_hljs_css_from_tokens(
    token_colors: list[dict],
    default_foreground: str | None = None,
    default_background: str | None = None,
    selector_prefix: str = HLJS_SITE_THEME_SELECTOR_PREFIX,
    *,
    token_foreground: str | None = None,
) -> str:
    """
    ממיר tokenColors של VS Code ל-CSS עבור highlight.js.

    לכל מחלקה, הצבע ש-VS Code נותן לטוקן שהיא צובעת (``HLJS_REPRESENTATIVES``). לפייתון ול-JavaScript יש גם כללים
    לפי שפה (``HLJS_LANGUAGES``), שנכתבים רק כשהם שונים מהכלל הכללי — ולפניו, כדי שמחלקה מדויקת יותר (למשל
    ``.hljs-title.function_.invoke__``) תגבר על כלל שפה של מחלקה כללית יותר בתיקו של ספציפיות.

    Args:
        token_colors: רשימת tokenColors מערכת VS Code
        default_foreground: צבע ברירת מחדל לטקסט (editor.foreground) — גם לכלל הבסיסי ``.hljs``
        default_background: צבע רקע לבלוקי קוד (editor.background) — רק לכלל הבסיסי
        selector_prefix: הבורר שכל כלל נכתב תחתיו. ברירת המחדל היא ערכה של האתר; קובץ HTML מעוצב
            שאין בו את המאפיין הזה (הייצוא מהעורך הציבורי, ``EXPORT_PRESETS``) מעביר בורר משלו.
        token_foreground: הצבע של טוקן ש-VS Code משאיר בצבע ברירת המחדל, כשאין ``default_foreground`` (ערכות הייצוא
            מעבירות את צבע הטקסט של הבלוק). בלי אף אחד מהשניים, מחלקה כזו לא נכתבת.

    Returns:
        CSS string עם כללים בפורמט:
        <selector_prefix> .hljs-keyword { color: #...; }
    """
    if not isinstance(token_colors, list):
        return ""

    css_rules: list[str] = []

    # 🆕 הוספת צבע ברירת מחדל עבור .hljs (טקסט שלא מסומן)
    # זה חשוב עבור משתנים, קבועים ואלמנטים ש-highlight.js לא מסמן
    if default_foreground and is_valid_color(str(default_foreground)):
        base_parts = [f"color: {str(default_foreground).strip()} !important"]
        if default_background and is_valid_color(str(default_background)):
            base_parts.append(f"background: {str(default_background).strip()} !important")
        css_rules.append(f'{selector_prefix} .hljs {{ {"; ".join(base_parts)}; }}')

    theme = VSCodeTokenTheme(
        token_colors, default_foreground=_hex_or_none(token_foreground) or _hex_or_none(default_foreground)
    )
    general = {selector: _resolve_generic(theme, stack) for selector, stack in HLJS_REPRESENTATIVES.items()}

    for language in HLJS_LANGUAGES.values():
        suffix = hljs_language_selector_suffix(language.class_names)
        for selector, stack in language.representatives.items():
            resolved = theme.resolve((language.root_scope, *stack))
            parts = _css_declarations(resolved)
            if parts and resolved != general.get(selector):
                css_rules.append(f'{selector_prefix} {selector}{suffix} {{ {"; ".join(parts)}; }}')

    for selector, resolved in general.items():
        parts = _css_declarations(resolved)
        if parts:
            css_rules.append(f'{selector_prefix} {selector} {{ {"; ".join(parts)}; }}')

    return "\n".join(css_rules)


def _find_pygments_class(scope: str) -> str | None:
    """
    מוצא את ה-Pygments class המתאים ל-scope.

    Args:
        scope: VS Code TextMate scope (e.g., "keyword.control.import")

    Returns:
        Pygments CSS class (e.g., ".kn") או None אם אין התאמה
    """
    if not scope or not isinstance(scope, str):
        return None

    # התאמה מדויקת - עדיפות ראשונה
    if scope in TOKEN_TO_PYGMENTS_MAP:
        return TOKEN_TO_PYGMENTS_MAP[scope]

    # חיפוש ההתאמה הספציפית ביותר (הארוכה ביותר)
    best_match: str | None = None
    best_match_length = 0

    for vs_scope, py_class in TOKEN_TO_PYGMENTS_MAP.items():
        if scope.startswith(vs_scope + ".") or scope == vs_scope:
            if len(vs_scope) > best_match_length:
                best_match = py_class
                best_match_length = len(vs_scope)
        elif vs_scope.startswith(scope + ".") or vs_scope == scope:
            if len(scope) > best_match_length:
                best_match = py_class
                best_match_length = len(scope)

    return best_match


def generate_pygments_css_from_tokens(token_colors: list[dict]) -> str:
    """
    ממיר tokenColors של VS Code ל-CSS עבור Pygments.

    🔑 אם יש כמה scopes שממופים לאותו Pygments class,
    הכלל הראשון מנצח (הספציפי יותר בד"כ מופיע קודם בקובץ VS Code).

    Returns:
        CSS string עם כללים בפורמט:
        .highlight .k { color: #...; }
    """
    if not isinstance(token_colors, list):
        return ""

    # שימוש ב-dict כדי לדדופ כללים לפי selector
    css_by_selector: dict[str, str] = {}

    for token in token_colors:
        if not isinstance(token, dict):
            continue

        scopes = token.get("scope", [])
        if isinstance(scopes, str):
            scopes = [scopes]
        if not isinstance(scopes, list):
            continue

        settings = token.get("settings", {})
        if not isinstance(settings, dict):
            continue

        foreground = settings.get("foreground")
        font_style = settings.get("fontStyle", "") or ""

        if not foreground or not is_valid_color(str(foreground)):
            continue

        for scope in scopes:
            py_class = _find_pygments_class(str(scope))
            if not py_class:
                continue

            # אם כבר יש כלל לזה, נדלג (הראשון מנצח)
            if py_class in css_by_selector:
                continue

            # CSS עם !important כדי לדרוס Pygments default styles
            rule_parts = [f"color: {str(foreground).strip()} !important"]

            fs = str(font_style).lower()
            if "italic" in fs:
                rule_parts.append("font-style: italic !important")
            if "bold" in fs:
                rule_parts.append("font-weight: bold !important")
            if "underline" in fs:
                rule_parts.append("text-decoration: underline !important")

            # Selector: .highlight .k (מתאים ל-codehilite Markdown extension)
            selector = f'.highlight {py_class}'
            css_by_selector[py_class] = f'{selector} {{ {"; ".join(rule_parts)}; }}'

    return "\n".join(css_by_selector.values())


def generate_codemirror_css_from_tokens(token_colors: list[dict], default_foreground: str | None = None) -> str:
    """
    ממיר tokenColors של VS Code ל-CSS עבור CodeMirror (המחלקות של ``classHighlighter``).

    לכל מחלקה ב-``CM_CLASS_TAGS``, הצבע ש-VS Code נותן לטוקן של ה-tag שהיא מקבלת. ``default_foreground`` כמו ב-
    ``generate_syntax_colors_from_tokens``.
    """
    if not isinstance(token_colors, list):
        return ""

    theme = VSCodeTokenTheme(token_colors, default_foreground=_hex_or_none(default_foreground))
    css_rules: list[str] = []
    for cm_class, tag in CM_CLASS_TAGS.items():
        parts = _css_declarations(_resolve_generic(theme, CM_TAG_REPRESENTATIVES[tag]))
        if parts:
            # 🎨 !important נדרש כדי לדרוס inline styles של CodeMirror themes; data-theme-type="custom" תופס גם Shared Themes
            css_rules.append(f':root[data-theme-type="custom"] {cm_class} {{ {"; ".join(parts)}; }}')
    return "\n".join(css_rules)


# 🎨 הבוררים ש-``sanitize_codemirror_css`` מקבל: tok- (CodeMirror 6 classHighlighter) ו-cm- (legacy), גם משורשרים
# — עד 3 classes (לדוג' ``.tok-variableName.tok-definition.tok-local``).
_CODEMIRROR_SINGLE_CLASS = r'(\.tok-[a-zA-Z0-9_-]+|\.cm-[a-z0-9_-]+)'
_CODEMIRROR_SELECTOR_RE = re.compile(f'^{_CODEMIRROR_SINGLE_CLASS}({_CODEMIRROR_SINGLE_CLASS}){{0,2}}$')

# הבוררים של highlight.js ש-``generate_hljs_css_from_tokens`` כותב: מחלקה ``hljs-`` ועד שלוש מחלקות-המשך
# (``.hljs-title.function_``, ‏``.hljs-title.class_.inherited__``), ואחריהן אולי הסיומת של כלל לפי שפה
# (``hljs_language_selector_suffix``: ``:is(.language-python *, .language-py *)``). בלי ``.hljs`` לבד: הכלל הבסיסי
# של הערכה (צבע ורקע לכל הבלוק) אינו כלל של טוקן.
_HLJS_LANGUAGE_CLASS = r'\.language-[a-z0-9_+-]{1,40} \*'
_HLJS_SELECTOR_RE = re.compile(
    r'\.hljs-[a-zA-Z0-9_-]+(\.[a-zA-Z0-9_-]+){0,3}'
    rf'(:is\({_HLJS_LANGUAGE_CLASS}(, {_HLJS_LANGUAGE_CLASS}){{0,7}}\))?'
)

#: הקידומת שכללי ערכה מותאמת או משותפת כתובים תחתיה בעמודי האתר — אותה קידומת של כללי highlight.js.
_CUSTOM_THEME_RULE_PREFIX = HLJS_SITE_THEME_SELECTOR_PREFIX


def sanitize_codemirror_css(css: str) -> str:
    """
    🔒 מנקה CSS של CodeMirror (syntax_css) כדי למנוע CSS injection.

    מאפשר רק חוקים בפורמט:
    :root[data-theme-type="custom"] .<tok|cm>-<token> { color: <HEX/RGB/RGBA>; [font-style: italic;] [font-weight: bold;] [text-decoration: underline;] }

    תומך גם ב-tok- classes (CodeMirror 6 classHighlighter) וגם ב-cm- classes (legacy).
    """
    return _sanitize_custom_theme_rules(css, _CODEMIRROR_SELECTOR_RE, _CUSTOM_THEME_RULE_PREFIX)


def rebase_hljs_css(css: str, selector_prefix: str) -> str:
    """🔒 כללי highlight.js מתוך ``syntax_css`` של ערכה מיובאת, תחת ``selector_prefix`` במקום הקידומת של האתר.

    ``parse_vscode_theme`` כותב את כללי highlight.js תחת ``HLJS_SITE_THEME_SELECTOR_PREFIX``, שמתאים רק בעמודי האתר
    (``:root[data-theme-type="custom"]``), ו-``tokenColors`` עצמם לא נשמרים עם הערכה — כך שאי אפשר לחשב אותם מחדש.
    הפונקציה לוקחת את הכללים השמורים ומחזירה אותם תחת קידומת אחרת (בייצוא: ``EXPORT_HLJS_SELECTOR_PREFIX``).

    הטקסט מגיע מהמסד, ולכן הוא עובר אותו ניקוי של ``sanitize_codemirror_css``, שורה-שורה: רק בורר ``hljs-``, רק
    ``color`` תקין ו-``font-style: italic`` / ``font-weight: bold`` / ``text-decoration: underline``. כל השאר —
    כללי CodeMirror ו-Pygments שבאותו ``syntax_css``, והכלל הבסיסי ``.hljs`` — לא עובר.
    """
    return _sanitize_custom_theme_rules(css, _HLJS_SELECTOR_RE, selector_prefix)


def _sanitize_custom_theme_rules(css: str, selector_re: re.Pattern, output_prefix: str) -> str:
    """הניקוי המשותף: כללים בשורה אחת, תחת הקידומת של ערכה מותאמת (בפורמט הישן או החדש), שהבורר שלהם תואם
    ל-``selector_re`` וההצהרות שלהן ברשימה הסגורה. כל כלל תקין יוצא תחת ``output_prefix``."""
    if not css or not isinstance(css, str):
        return ""

    safe_rules: list[str] = []
    max_line_length = 500  # 🔒 הגנה מפני ReDoS / קלט חריג

    for raw_line in css.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if len(line) > max_line_length:
            continue

        # חסימת תבניות מסוכנות במפורש
        lower = line.lower()
        dangerous_patterns = [
            "url(", "expression(", "javascript:",
            "data:", "behavior:", "binding:",
            "@import", "@charset", "<", ">",
            "/*", "*/", "\\",
        ]
        if any(p in lower for p in dangerous_patterns):
            continue

        # 🔒 אבטחה/ביצועים: הימנעות מ-Regex כבד על קלט לא נשלט (ReDoS)
        # תומך גם בפורמט הישן (data-theme="custom") וגם בחדש (data-theme-type="custom")
        # כדי לשמור תאימות לאחור לערכות קיימות.
        allowed_prefixes = (
            ':root[data-theme="custom"]',
            ':root[data-theme-type="custom"]',
        )
        prefix = next((p for p in allowed_prefixes if line.startswith(p)), None)
        if not prefix:
            continue

        open_idx = line.find("{")
        close_idx = line.rfind("}")
        if open_idx == -1 or close_idx == -1 or close_idx < open_idx:
            continue

        before = line[:open_idx].strip()
        body = line[open_idx + 1 : close_idx].strip()
        after = line[close_idx + 1 :].strip()
        if after:
            continue

        rest = before[len(prefix) :].strip()
        if not rest:
            continue
        selector = rest

        if not selector_re.fullmatch(selector):
            continue

        decls = [d.strip() for d in body.split(";") if d.strip()]
        if not decls:
            continue

        out_parts: list[str] = []
        ok = True

        for d in decls:
            if ":" not in d:
                ok = False
                break
            prop, val = d.split(":", 1)
            prop = prop.strip().lower()
            val = val.strip()
            # 🎨 הסר !important לצורך וולידציה, נוסיף אותו בחזרה אחר כך
            has_important = val.lower().endswith("!important")
            if has_important:
                val = val[: -len("!important")].strip()

            if prop == "color":
                clean = sanitize_css_value(val)
                if not clean:
                    ok = False
                    break
                out_parts.append(f"color: {clean} !important")
            elif prop == "font-style":
                if val.strip().lower() != "italic":
                    ok = False
                    break
                out_parts.append("font-style: italic !important")
            elif prop == "font-weight":
                if val.strip().lower() != "bold":
                    ok = False
                    break
                out_parts.append("font-weight: bold !important")
            elif prop == "text-decoration":
                if val.strip().lower() != "underline":
                    ok = False
                    break
                out_parts.append("text-decoration: underline !important")
            else:
                ok = False
                break

        if not ok:
            continue

        # חייב להיות לפחות color
        if not any(p.startswith("color:") for p in out_parts):
            continue

        # ``sanitize_codemirror_css`` מנרמל תמיד לפורמט החדש, כדי שיתפוס גם custom וגם shared (דרך data-theme-type).
        safe_rules.append(f'{output_prefix} {selector} {{ {"; ".join(out_parts)}; }}')

    return "\n".join(safe_rules)


def export_theme_to_json(theme: dict) -> str:
    """מייצא ערכה לפורמט JSON להורדה."""
    export_data = {
        "name": (theme or {}).get("name", "Exported Theme"),
        "description": (theme or {}).get("description", ""),
        "version": "1.0",
        "variables": (theme or {}).get("variables", {}),
    }
    return json.dumps(export_data, indent=2, ensure_ascii=False)

