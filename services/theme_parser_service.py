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

    # Markdown & Split View - נשאר כהה גם בתמה בהירה!
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

    # בדיקה אם זו ערכת VS Code
    if "colors" in data:
        if not isinstance(data["colors"], dict):
            return False, "'colors' חייב להיות אובייקט"
        if len(data["colors"]) < 3:
            return False, "ערכת VS Code חייבת להכיל לפחות 3 צבעים"
        return True, ""

    # בדיקה אם זו ערכה בפורמט שלנו
    if "variables" in data:
        if not isinstance(data["variables"], dict):
            return False, "'variables' חייב להיות אובייקט"

        for key, value in data["variables"].items():
            if not str(key).startswith("--"):
                return False, f"משתנה CSS חייב להתחיל ב---: {key}"
            if str(key) == "--glass-blur":
                if not _is_valid_px(str(value)):
                    return False, f"ערך blur לא תקין: {key}={value}"
            else:
                if not is_valid_color(str(value)):
                    return False, f"ערך צבע לא תקין: {key}={value}"

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
    result = _derive_glass_tokens(result)

    # 🎨 יצירת CSS להדגשת תחביר מ-tokenColors
    syntax_css_parts = []
    syntax_colors: dict[str, dict] = {}
    token_colors = theme_data.get("tokenColors", [])

    if token_colors:
        # 🆕 מילון צבעים לפי tag (עבור HighlightStyle דינמי)
        syntax_colors = generate_syntax_colors_from_tokens(token_colors)

        # CodeMirror CSS (.tok-* classes) - fallback
        cm_css = generate_codemirror_css_from_tokens(token_colors)
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
        editor_fg = colors.get("editor.foreground")
        editor_bg = colors.get("editor.background")
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


# כמה להכהות את הרקע המשני כדי לקבל את משטח הזכוכית בערכה בהירה.
# ה-body צבוע linear-gradient(--bg-primary → --bg-secondary), ולכן משטח
# שצבעו בדיוק --bg-secondary נעלם בקצה אחד של הגרדיאנט (ניגודיות 1.000).
_GLASS_SURFACE_DARKEN = 0.06
_GLASS_HOVER_DARKEN = 0.06
_GLASS_BORDER_OPACITY = 0.18
# הפרדה מינימלית של המשטח משני קצות הגרדיאנט, ומספר הכהיות מרבי עד שמגיעים אליה.
_GLASS_MIN_SURFACE_CONTRAST = 1.10
_GLASS_MAX_DARKEN_STEPS = 8


def _derive_glass_tokens(variables: dict) -> dict:
    """
    גוזר --glass / --glass-border / --glass-hover מצבעי הערכה — רק לערכה בהירה.

    למה זה נחוץ: הממשק מצייר כרטיסים, badges, navbar וכפתורים משניים עם
    הטוקנים האלה, ואף מפתח ב-VSCODE_TO_CSS_MAP לא ממלא אותם. ערכה מיובאת
    מקבלת אותם מ-FALLBACK_DARK/LIGHT בלבד.

    למה רק בהירה: ערכי ה-FALLBACK הם גוונים לבנים, והם נכונים לערכה כהה.
    בערכה בהירה הם 2%/5% שחור — נמדד בכרומיום מול השרת האמיתי: כרטיס מול
    רקע = 1.053, כלומר בלתי נראה. ערכה כהה נשארת כפי שהיא.

    הגדר לפי הבהירות שנמדדת ולא לפי "type" שבקובץ: type נכתב ביד, יכול
    להיות חסר, ואז parse_vscode_theme מניח "dark".
    """
    result = variables.copy()

    bg_primary = result.get("--bg-primary")
    if not bg_primary or _is_dark_color(str(bg_primary)):
        return result

    # ה-body צבוע גרדיאנט רציף בין שני הרקעים, ולכן הוא עובר בכל גוון שביניהם.
    # משטח שהלומיננסיה שלו נופלת בתוך הרצועה נעלם בנקודה שבה הגרדיאנט משתווה
    # לו — גם כשהניגודיות מול שני הקצוות מצוינת (נמדד: 3.43 ו-1.15, ובכל זאת
    # בלתי נראה באמצע). לכן מעגנים בקצה הכהה ומכהים ממנו: כך המשטח יוצא כהה
    # משני הקצוות ונשאר מחוץ לרצועה בכל מצב.
    gradient_ends = [str(end) for end in (bg_primary, result.get("--bg-secondary")) if end]
    if any(_relative_luminance(end) is None for end in gradient_ends):
        return result
    usable_ends = gradient_ends

    surface = darken_color(min(usable_ends, key=_relative_luminance), _GLASS_SURFACE_DARKEN)
    if normalize_color_to_rgba(surface) is None:
        return result

    for _ in range(_GLASS_MAX_DARKEN_STEPS):
        ratios = [contrast_ratio(surface, end) for end in usable_ends]
        if min(ratios) >= _GLASS_MIN_SURFACE_CONTRAST:
            break
        darker = darken_color(surface, _GLASS_SURFACE_DARKEN)
        if darker == surface:
            break  # התכנסות (שחור) — אין טעם להמשיך
        surface = darker

    result["--glass"] = surface
    result["--glass-hover"] = darken_color(surface, _GLASS_HOVER_DARKEN)

    text_primary = result.get("--text-primary")
    if text_primary and normalize_color_to_rgba(str(text_primary)) is not None:
        result["--glass-border"] = color_with_opacity(str(text_primary), _GLASS_BORDER_OPACITY)

    return result


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

        # הצורה המקוצרת מורחבת לצורה המלאה, וכך כל הפרסור עובר בענף אחד
        # מוגן ב-try/except. קודם ענפי ה-3 וה-4 פרסרו ישירות ובלי הגנה,
        # ולכן #ggg זרק ValueError במקום להחזיר None כפי שהחוזה מבטיח.
        if len(hex_val) in (3, 4):
            hex_val = "".join(ch * 2 for ch in hex_val)

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


def composite_over(color: str, background: str) -> str | None:
    """
    מחזיר את הצבע שהדפדפן מצייר בפועל: ``color`` (אולי שקוף למחצה) מעל ``background``.

    ``background`` נדרש להיות אטום — אין שכבה נוספת מתחתיו להרכיב מעליה.
    מחזיר ``None`` אם אחד הערכים אינו ניתן לפרסור.
    """
    fg = normalize_color_to_rgba(color)
    bg = normalize_color_to_rgba(background)
    if fg is None or bg is None:
        return None
    alpha = fg[3]
    mixed = tuple(
        max(0, min(255, round(channel * alpha + base * (1 - alpha))))
        for channel, base in zip(fg[:3], bg[:3])
    )
    return "#%02x%02x%02x" % mixed


def _relative_luminance(color: str) -> float | None:
    """
    לומיננסיה יחסית לפי WCAG 2.1.

    מחזיר ``None`` אם הצבע אינו ניתן לפרסור, וגם אם הוא אינו אטום: לצבע
    שקוף למחצה אין לומיננסיה משל עצמו — היא תלויה במה שמתחתיו. התעלמות
    מ-alpha החזירה 19.44 עבור ``rgba(0, 0, 0, 0.02)`` מעל נייר בהיר, בעוד
    הצבע המצויר בפועל נותן 1.045. הרכיבו קודם עם :func:`composite_over`.
    """
    rgba = normalize_color_to_rgba(color)
    if rgba is None or rgba[3] < 1.0:
        return None

    def _lin(channel: float) -> float:
        c = channel / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b, _ = rgba
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast_ratio(color_a: str, color_b: str) -> float | None:
    """
    יחס ניגודיות WCAG בין שני צבעים (1.0 = זהים, 21.0 = לבן מול שחור).

    מחזיר ``None`` אם אחד הצבעים אינו ניתן לפרסור או אינו אטום — ראו
    :func:`_relative_luminance`.
    """
    lum_a = _relative_luminance(color_a)
    lum_b = _relative_luminance(color_b)
    if lum_a is None or lum_b is None:
        return None
    hi, lo = max(lum_a, lum_b), min(lum_a, lum_b)
    return (hi + 0.05) / (lo + 0.05)


def _is_dark_color(color: str) -> bool:
    """
    בודק אם צבע כהה.

    תומך בכל הפורמטים ש-``VALID_COLOR_REGEX`` מאשר — hex בן 3/4/6/8 תווים,
    ``rgb()`` ו-``rgba()`` — ולא ב-hex בלבד. ערכה בהירה שהצהירה על צבעיה
    ב-``rgb()`` נחשבה קודם כהה, ולכן לא נכנסה לגזירת הזכוכית.

    ⚠️ ‏alpha אינו נלקח בחשבון: אין כאן רקע ידוע להרכיב מעליו, והצבע נבחן
    כאילו הוא אטום. זו גם ההתנהגות שהייתה קודם עבור hex בן 8 תווים.

    ערך שאינו ניתן לפרסור נחשב כהה — ברירת מחדל שמרנית שמונעת גזירה.
    """
    rgba = normalize_color_to_rgba(color) if isinstance(color, str) else None
    if rgba is None:
        return True
    r, g, b, _ = rgba
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255 < 0.5


# ==========================================
# Syntax Highlighting: tokenColors → CodeMirror
# ==========================================

# ==========================================
# 🎨 CodeMirror 6 Tags Mapping (for HighlightStyle.define)
# ==========================================
# המיפוי הזה ממיר VS Code TextMate scopes לשמות של CodeMirror tags.
# ה-tags משמשים ליצירת HighlightStyle דינמי ב-JavaScript.
#
# ⚠️ חשוב: שמות ה-tags חייבים להתאים לשמות ב-@lezer/highlight
# ראה: https://lezer.codemirror.net/docs/ref/#highlight.tags
# ==========================================

# מיפוי VS Code scopes → CodeMirror tag names (לא classes!)
# זה מאפשר יצירת HighlightStyle דינמי עם צבעים ייחודיים לכל סוג
VSCODE_TO_CM_TAG: dict[str, str] = {
    # ===========================================
    # Comments - מיפוי פשוט
    # ===========================================
    "comment": "comment",
    "comment.line": "lineComment",
    "comment.block": "blockComment",
    "comment.block.documentation": "docComment",
    "punctuation.definition.comment": "comment",

    # ===========================================
    # Strings
    # ===========================================
    "string": "string",
    "string.quoted": "string",
    "string.quoted.single": "string",
    "string.quoted.double": "string",
    "string.quoted.triple": "string",
    "string.template": "special(string)",
    "string.regexp": "regexp",
    "string.interpolated": "special(string)",

    # ===========================================
    # Keywords
    # ===========================================
    "keyword": "keyword",
    "keyword.control": "controlKeyword",
    "keyword.control.flow": "controlKeyword",
    "keyword.control.import": "moduleKeyword",
    "keyword.control.export": "moduleKeyword",
    "keyword.control.conditional": "controlKeyword",
    "keyword.control.loop": "controlKeyword",
    "keyword.control.return": "controlKeyword",
    "keyword.control.trycatch": "controlKeyword",
    "keyword.other": "keyword",
    "keyword.other.unit": "unit",

    # ===========================================
    # Storage (def, class, var, let, const)
    # ===========================================
    "storage": "definitionKeyword",
    "storage.type": "definitionKeyword",
    "storage.type.function": "definitionKeyword",
    "storage.type.class": "definitionKeyword",
    "storage.modifier": "modifier",
    "storage.modifier.async": "modifier",

    # ===========================================
    # Functions - הבחנה בין הגדרה לקריאה!
    # ===========================================
    # 🔑 CodeMirror Python parser משתמש ב-function(definition(...)) לא definition(function(...))!
    # ראה: codemirror.local.js שורה ~25146
    "entity.name.function": "function(definition(variableName))",
    "entity.name.function.method": "function(definition(variableName))",
    "entity.name.function.decorator": "macroName",
    "meta.function.decorator": "macroName",
    # קריאות לפונקציות
    "meta.function-call": "function(variableName)",
    "meta.function-call.generic": "function(variableName)",
    "entity.name.function.call": "function(variableName)",
    # פונקציות מובנות
    "support.function": "standard(function(variableName))",
    "support.function.builtin": "standard(function(variableName))",
    "support.function.magic": "special(function(variableName))",

    # ===========================================
    # Variables - הבחנה בין סוגים שונים
    # ===========================================
    "variable": "variableName",
    "variable.parameter": "local(variableName)",
    "variable.parameter.function": "local(variableName)",
    "variable.other": "variableName",
    "variable.other.readwrite": "variableName",
    "variable.other.constant": "constant(variableName)",
    "variable.other.enummember": "constant(variableName)",
    "variable.language": "self",
    "variable.language.this": "self",
    "variable.language.self": "self",
    "variable.language.super": "self",

    # ===========================================
    # Constants & Numbers
    # ===========================================
    "constant": "atom",
    "constant.numeric": "number",
    "constant.numeric.integer": "integer",
    "constant.numeric.float": "float",
    "constant.numeric.hex": "integer",
    "constant.numeric.binary": "integer",
    "constant.numeric.octal": "integer",
    "constant.language": "atom",
    "constant.language.boolean": "bool",
    "constant.language.boolean.true": "bool",
    "constant.language.boolean.false": "bool",
    "constant.language.null": "null",
    "constant.language.undefined": "null",
    "constant.character": "character",
    "constant.character.escape": "escape",
    "constant.other": "atom",

    # ===========================================
    # Types & Classes
    # ===========================================
    "entity.name.type": "typeName",
    "entity.name.type.class": "className",
    "entity.name.type.interface": "typeName",
    "entity.name.type.enum": "typeName",
    "entity.name.type.module": "namespace",
    "entity.name.type.namespace": "namespace",
    "entity.name.class": "definition(className)",
    "entity.name.namespace": "namespace",
    "entity.name.module": "namespace",
    "support.type": "standard(typeName)",
    "support.type.primitive": "typeName",
    "support.class": "standard(className)",
    "support.class.builtin": "standard(className)",

    # ===========================================
    # Operators
    # ===========================================
    "keyword.operator": "operator",
    "keyword.operator.assignment": "definitionOperator",
    "keyword.operator.comparison": "compareOperator",
    "keyword.operator.logical": "logicOperator",
    "keyword.operator.arithmetic": "arithmeticOperator",
    "keyword.operator.bitwise": "bitwiseOperator",
    "keyword.operator.ternary": "operator",
    "keyword.operator.spread": "operator",
    "keyword.operator.new": "operatorKeyword",
    "keyword.operator.expression": "operatorKeyword",
    "keyword.operator.typeof": "operatorKeyword",
    "keyword.operator.instanceof": "operatorKeyword",

    # ===========================================
    # Properties & Attributes
    # ===========================================
    "entity.other.attribute-name": "attributeName",
    "entity.other.attribute-name.class": "attributeName",
    "entity.other.attribute-name.id": "attributeName",
    "support.type.property-name": "propertyName",
    "support.type.property-name.json": "propertyName",
    "meta.object-literal.key": "propertyName",
    "variable.other.property": "propertyName",
    "variable.other.object.property": "propertyName",
    "meta.attribute": "attributeName",

    # ===========================================
    # Tags (HTML/XML/JSX)
    # ===========================================
    "entity.name.tag": "tagName",
    "entity.name.tag.html": "tagName",
    "entity.name.tag.xml": "tagName",
    "entity.name.tag.css": "tagName",
    "punctuation.definition.tag": "angleBracket",
    "punctuation.definition.tag.begin": "angleBracket",
    "punctuation.definition.tag.end": "angleBracket",
    "support.class.component": "className",
    "support.class.component.jsx": "className",

    # ===========================================
    # Punctuation
    # ===========================================
    "punctuation": "punctuation",
    "punctuation.definition.string": "string",
    "punctuation.definition.string.begin": "string",
    "punctuation.definition.string.end": "string",
    "punctuation.separator": "separator",
    "punctuation.terminator": "punctuation",
    "punctuation.accessor": "punctuation",
    "punctuation.bracket": "bracket",
    "punctuation.section": "punctuation",
    "meta.brace": "brace",
    "meta.brace.round": "paren",
    "meta.brace.square": "squareBracket",
    "meta.brace.curly": "brace",

    # ===========================================
    # Errors & Special
    # ===========================================
    "invalid": "invalid",
    "invalid.illegal": "invalid",
    "invalid.deprecated": "invalid",

    # ===========================================
    # Markup (Markdown)
    # ===========================================
    "markup.heading": "heading",
    "markup.heading.1": "heading1",
    "markup.heading.2": "heading2",
    "markup.heading.setext": "heading",
    "markup.bold": "strong",
    "markup.italic": "emphasis",
    "markup.underline": "link",
    "markup.underline.link": "link",
    "markup.inserted": "inserted",
    "markup.deleted": "deleted",
    "markup.changed": "changed",
    "markup.quote": "quote",
    "markup.list": "list",
    "markup.raw": "monospace",
    "markup.inline.raw": "monospace",

    # ===========================================
    # Git Diff
    # ===========================================
    "meta.diff.header": "meta",
    "markup.inserted.diff": "inserted",
    "markup.deleted.diff": "deleted",

    # ===========================================
    # Labels & Special Names
    # ===========================================
    "entity.name.label": "labelName",
    "entity.name.section": "heading",

    # ===========================================
    # Additional
    # ===========================================
    "meta": "meta",
    "meta.embedded": "meta",
    "meta.preprocessor": "processingInstruction",
    "emphasis": "emphasis",
    "strong": "strong",
    "link": "link",
    "url": "url",
    "source": "content",
}


# ==========================================
# 🎨 Legacy: CodeMirror 6 CSS Classes Mapping (for classHighlighter)
# ==========================================
# שמור לתאימות לאחור עם classHighlighter
# ==========================================

TOKEN_TO_CODEMIRROR_MAP: dict[str, str] = {
    # ===========================================
    # Comments
    # ===========================================
    "comment": ".tok-comment",
    "comment.line": ".tok-comment",
    "comment.block": ".tok-comment",
    "comment.block.documentation": ".tok-comment",
    "punctuation.definition.comment": ".tok-comment",

    # ===========================================
    # Strings
    # ===========================================
    "string": ".tok-string",
    "string.quoted": ".tok-string",
    "string.quoted.single": ".tok-string",
    "string.quoted.double": ".tok-string",
    "string.quoted.triple": ".tok-string",
    "string.template": ".tok-string2",
    "string.regexp": ".tok-string2",
    "string.interpolated": ".tok-string2",

    # ===========================================
    # Keywords (מילות מפתח של השפה)
    # ===========================================
    "keyword": ".tok-keyword",
    "keyword.control": ".tok-keyword",
    "keyword.control.flow": ".tok-keyword",
    "keyword.control.import": ".tok-keyword",
    "keyword.control.export": ".tok-keyword",
    "keyword.control.conditional": ".tok-keyword",
    "keyword.control.loop": ".tok-keyword",
    "keyword.control.return": ".tok-keyword",
    "keyword.control.trycatch": ".tok-keyword",
    "keyword.other": ".tok-keyword",
    "keyword.other.unit": ".tok-keyword",

    # ===========================================
    # Storage (הגדרות משתנים/פונקציות)
    # ===========================================
    "storage": ".tok-keyword",
    "storage.type": ".tok-keyword",
    "storage.type.function": ".tok-keyword",
    "storage.type.class": ".tok-keyword",
    "storage.modifier": ".tok-keyword",
    "storage.modifier.async": ".tok-keyword",

    # ===========================================
    # Functions (פונקציות והגדרותיהן)
    # ===========================================
    # הגדרות פונקציות משתמשות ב-definition class
    "entity.name.function": ".tok-variableName.tok-definition",
    "entity.name.function.method": ".tok-variableName.tok-definition",
    "entity.name.function.decorator": ".tok-macroName",
    # קריאות לפונקציות (ללא definition)
    "meta.function-call": ".tok-variableName",
    "meta.function-call.generic": ".tok-variableName",
    "entity.name.function.call": ".tok-variableName",
    "entity.name.function.method.call": ".tok-variableName",
    # Built-in functions
    "support.function": ".tok-variableName",
    "support.function.builtin": ".tok-variableName",
    "support.function.magic": ".tok-variableName",

    # ===========================================
    # Variables (משתנים)
    # ===========================================
    "variable": ".tok-variableName",
    "variable.parameter": ".tok-variableName.tok-local",
    "variable.parameter.function": ".tok-variableName.tok-local",
    "variable.other": ".tok-variableName",
    "variable.other.readwrite": ".tok-variableName",
    "variable.other.constant": ".tok-variableName2",
    "variable.other.enummember": ".tok-variableName2",
    "variable.language": ".tok-variableName2",
    "variable.language.this": ".tok-variableName2",
    "variable.language.self": ".tok-variableName2",
    "variable.language.super": ".tok-variableName2",

    # ===========================================
    # Constants (קבועים ומספרים)
    # ===========================================
    "constant": ".tok-atom",
    "constant.numeric": ".tok-number",
    "constant.numeric.integer": ".tok-number",
    "constant.numeric.float": ".tok-number",
    "constant.numeric.hex": ".tok-number",
    "constant.numeric.binary": ".tok-number",
    "constant.numeric.octal": ".tok-number",
    "constant.language": ".tok-atom",
    "constant.language.boolean": ".tok-bool",
    "constant.language.boolean.true": ".tok-bool",
    "constant.language.boolean.false": ".tok-bool",
    "constant.language.null": ".tok-atom",
    "constant.language.undefined": ".tok-atom",
    "constant.character": ".tok-string",
    "constant.character.escape": ".tok-string2",
    "constant.other": ".tok-atom",

    # ===========================================
    # Types & Classes (טיפוסים ומחלקות)
    # ===========================================
    "entity.name.type": ".tok-typeName",
    "entity.name.type.class": ".tok-className",
    "entity.name.type.interface": ".tok-typeName",
    "entity.name.type.enum": ".tok-typeName",
    "entity.name.type.module": ".tok-namespace",
    "entity.name.type.namespace": ".tok-namespace",
    "entity.name.class": ".tok-className",
    "entity.name.namespace": ".tok-namespace",
    "entity.name.module": ".tok-namespace",
    "support.type": ".tok-typeName",
    "support.type.primitive": ".tok-typeName",
    "support.class": ".tok-className",
    "support.class.builtin": ".tok-className",

    # ===========================================
    # Operators (אופרטורים)
    # ===========================================
    "keyword.operator": ".tok-operator",
    "keyword.operator.assignment": ".tok-operator",
    "keyword.operator.comparison": ".tok-operator",
    "keyword.operator.logical": ".tok-operator",
    "keyword.operator.arithmetic": ".tok-operator",
    "keyword.operator.bitwise": ".tok-operator",
    "keyword.operator.ternary": ".tok-operator",
    "keyword.operator.spread": ".tok-operator",
    "keyword.operator.new": ".tok-keyword",
    "keyword.operator.expression": ".tok-keyword",
    "keyword.operator.typeof": ".tok-keyword",
    "keyword.operator.instanceof": ".tok-keyword",

    # ===========================================
    # Properties & Attributes
    # ===========================================
    "entity.other.attribute-name": ".tok-propertyName",
    "entity.other.attribute-name.class": ".tok-propertyName",
    "entity.other.attribute-name.id": ".tok-propertyName",
    "support.type.property-name": ".tok-propertyName",
    "support.type.property-name.json": ".tok-propertyName",
    "meta.object-literal.key": ".tok-propertyName",
    "variable.other.property": ".tok-propertyName",
    "variable.other.object.property": ".tok-propertyName",

    # ===========================================
    # Tags (HTML/XML/JSX)
    # ===========================================
    "entity.name.tag": ".tok-tagName",
    "entity.name.tag.html": ".tok-tagName",
    "entity.name.tag.xml": ".tok-tagName",
    "entity.name.tag.css": ".tok-tagName",
    "punctuation.definition.tag": ".tok-punctuation",
    "punctuation.definition.tag.begin": ".tok-punctuation",
    "punctuation.definition.tag.end": ".tok-punctuation",
    "support.class.component": ".tok-className",
    "support.class.component.jsx": ".tok-className",

    # ===========================================
    # Punctuation (סימני פיסוק)
    # ===========================================
    "punctuation": ".tok-punctuation",
    "punctuation.definition.string": ".tok-string",
    "punctuation.definition.string.begin": ".tok-string",
    "punctuation.definition.string.end": ".tok-string",
    "punctuation.separator": ".tok-punctuation",
    "punctuation.terminator": ".tok-punctuation",
    "punctuation.accessor": ".tok-punctuation",
    "punctuation.bracket": ".tok-punctuation",
    "punctuation.section": ".tok-punctuation",
    "meta.brace": ".tok-punctuation",
    "meta.brace.round": ".tok-punctuation",
    "meta.brace.square": ".tok-punctuation",
    "meta.brace.curly": ".tok-punctuation",

    # ===========================================
    # Errors & Special
    # ===========================================
    "invalid": ".tok-invalid",
    "invalid.illegal": ".tok-invalid",
    "invalid.deprecated": ".tok-invalid",

    # ===========================================
    # Markup (Markdown/HTML content)
    # ===========================================
    "markup.heading": ".tok-heading",
    "markup.heading.1": ".tok-heading",
    "markup.heading.2": ".tok-heading",
    "markup.heading.setext": ".tok-heading",
    "markup.bold": ".tok-strong",
    "markup.italic": ".tok-emphasis",
    "markup.underline": ".tok-link",
    "markup.underline.link": ".tok-link",
    "markup.inserted": ".tok-inserted",
    "markup.deleted": ".tok-deleted",
    "markup.changed": ".tok-atom",
    "markup.quote": ".tok-meta",
    "markup.list": ".tok-punctuation",
    "markup.raw": ".tok-string",
    "markup.inline.raw": ".tok-string",

    # ===========================================
    # Git Diff
    # ===========================================
    "meta.diff.header": ".tok-meta",
    "markup.inserted.diff": ".tok-inserted",
    "markup.deleted.diff": ".tok-deleted",

    # ===========================================
    # Labels & Special Names
    # ===========================================
    "entity.name.label": ".tok-labelName",
    "entity.name.section": ".tok-heading",

    # ===========================================
    # Additional CodeMirror 6 Classes
    # ===========================================
    "meta": ".tok-meta",
    "meta.embedded": ".tok-meta",
    "meta.preprocessor": ".tok-meta",
    "emphasis": ".tok-emphasis",
    "strong": ".tok-strong",
    "link": ".tok-link",
    "url": ".tok-url",
    "source": ".tok-meta",
}

# ==========================================
# 🎨 Pygments Token Classes Mapping
# ==========================================
# מיפוי VS Code TextMate scopes ל-Pygments CSS classes
# ראה: https://pygments.org/docs/tokens/
# ==========================================

# ==========================================
# 🎨 Highlight.js Classes Mapping
# ==========================================
# מיפוי VS Code TextMate scopes ל-highlight.js CSS classes
# ראה: https://highlightjs.readthedocs.io/en/latest/css-classes-reference.html
# ==========================================

TOKEN_TO_HLJS_MAP: dict[str, str] = {
    # ===========================================
    # Comments
    # ===========================================
    "comment": ".hljs-comment",
    "comment.line": ".hljs-comment",
    "comment.block": ".hljs-comment",
    "comment.block.documentation": ".hljs-doctag",
    "punctuation.definition.comment": ".hljs-comment",

    # ===========================================
    # Strings
    # ===========================================
    "string": ".hljs-string",
    "string.quoted": ".hljs-string",
    "string.quoted.single": ".hljs-string",
    "string.quoted.double": ".hljs-string",
    "string.quoted.triple": ".hljs-string",
    "string.template": ".hljs-string",
    "string.regexp": ".hljs-regexp",
    "string.interpolated": ".hljs-string",
    "string.other": ".hljs-string",

    # ===========================================
    # Keywords
    # ===========================================
    "keyword": ".hljs-keyword",
    "keyword.control": ".hljs-keyword",
    "keyword.control.flow": ".hljs-keyword",
    "keyword.control.import": ".hljs-keyword",
    "keyword.control.export": ".hljs-keyword",
    "keyword.control.conditional": ".hljs-keyword",
    "keyword.control.loop": ".hljs-keyword",
    "keyword.control.return": ".hljs-keyword",
    "keyword.control.trycatch": ".hljs-keyword",
    "keyword.other": ".hljs-keyword",
    "keyword.other.unit": ".hljs-number",
    "keyword.operator": ".hljs-operator",

    # ===========================================
    # Storage (types and modifiers)
    # ===========================================
    "storage": ".hljs-keyword",
    "storage.type": ".hljs-type",
    "storage.type.function": ".hljs-keyword",
    "storage.type.class": ".hljs-keyword",
    "storage.modifier": ".hljs-keyword",
    "storage.modifier.async": ".hljs-keyword",

    # ===========================================
    # Constants (numbers, booleans, etc.)
    # ===========================================
    "constant": ".hljs-literal",
    "constant.numeric": ".hljs-number",
    "constant.numeric.integer": ".hljs-number",
    "constant.numeric.float": ".hljs-number",
    "constant.numeric.hex": ".hljs-number",
    "constant.numeric.octal": ".hljs-number",
    "constant.numeric.binary": ".hljs-number",
    "constant.language": ".hljs-literal",
    "constant.language.boolean": ".hljs-literal",
    "constant.language.boolean.true": ".hljs-literal",
    "constant.language.boolean.false": ".hljs-literal",
    "constant.language.null": ".hljs-literal",
    "constant.language.undefined": ".hljs-literal",
    "constant.character": ".hljs-string",
    "constant.character.escape": ".hljs-char.escape_",
    "constant.other": ".hljs-literal",

    # ===========================================
    # Functions
    # ===========================================
    "entity.name.function": ".hljs-title.function_",
    "entity.name.function.method": ".hljs-title.function_",
    "entity.name.function.decorator": ".hljs-meta",
    "support.function": ".hljs-built_in",
    "support.function.builtin": ".hljs-built_in",
    "meta.function-call": ".hljs-title.function_",

    # ===========================================
    # Classes and Types
    # ===========================================
    "entity.name.class": ".hljs-title.class_",
    "entity.name.type": ".hljs-type",
    "entity.name.type.class": ".hljs-title.class_",
    "support.class": ".hljs-built_in",
    "support.type": ".hljs-type",
    "entity.other.inherited-class": ".hljs-title.class_.inherited__",

    # ===========================================
    # Variables
    # ===========================================
    "variable": ".hljs-variable",
    "variable.other": ".hljs-variable",
    "variable.parameter": ".hljs-params",
    "variable.language": ".hljs-variable.language_",
    "variable.language.this": ".hljs-variable.language_",
    "variable.language.self": ".hljs-variable.language_",

    # ===========================================
    # HTML/XML Tags and Attributes
    # ===========================================
    "entity.name.tag": ".hljs-name",
    "entity.other.attribute-name": ".hljs-attr",
    "punctuation.definition.tag": ".hljs-tag",

    # ===========================================
    # Operators and Punctuation
    # ===========================================
    "punctuation": ".hljs-punctuation",
    "punctuation.separator": ".hljs-punctuation",
    "punctuation.definition.string": ".hljs-string",

    # ===========================================
    # Markdown
    # ===========================================
    "entity.name.section.markdown": ".hljs-section",
    "markup.heading": ".hljs-section",
    "markup.bold": ".hljs-strong",
    "markup.italic": ".hljs-emphasis",
    "markup.raw": ".hljs-code",
    "markup.inline.raw": ".hljs-code",
    "markup.deleted": ".hljs-deletion",
    "markup.inserted": ".hljs-addition",
    "markup.list": ".hljs-bullet",

    # ===========================================
    # Meta
    # ===========================================
    "meta": ".hljs-meta",
    "meta.preprocessor": ".hljs-meta",
    "meta.decorator": ".hljs-meta",

    # ===========================================
    # Invalid/Error
    # ===========================================
    "invalid": ".hljs-comment",  # no error class in hljs, fallback to comment
    "invalid.deprecated": ".hljs-comment",

    # ===========================================
    # Links & URLs
    # ===========================================
    "markup.underline.link": ".hljs-link",
    "string.other.link": ".hljs-link",

    # ===========================================
    # Quote
    # ===========================================
    "markup.quote": ".hljs-quote",

    # ===========================================
    # Symbols
    # ===========================================
    "constant.other.symbol": ".hljs-symbol",
    "entity.name.label": ".hljs-symbol",
}


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


def _find_cm_tag(scope: str) -> str | None:
    """
    מוצא את ה-CodeMirror tag המתאים ל-scope.

    Args:
        scope: VS Code TextMate scope (e.g., "keyword.control.import")

    Returns:
        CodeMirror tag name (e.g., "moduleKeyword") או None אם אין התאמה
    """
    if not scope or not isinstance(scope, str):
        return None

    # התאמה מדויקת
    if scope in VSCODE_TO_CM_TAG:
        return VSCODE_TO_CM_TAG[scope]

    # חיפוש ההתאמה הספציפית ביותר
    best_match: str | None = None
    best_match_length = 0

    for vs_scope, cm_tag in VSCODE_TO_CM_TAG.items():
        if scope.startswith(vs_scope + ".") or scope == vs_scope:
            if len(vs_scope) > best_match_length:
                best_match = cm_tag
                best_match_length = len(vs_scope)
        elif vs_scope.startswith(scope + ".") or vs_scope == scope:
            if len(scope) > best_match_length:
                best_match = cm_tag
                best_match_length = len(scope)

    return best_match


def generate_syntax_colors_from_tokens(token_colors: list[dict]) -> dict[str, dict]:
    """
    ממיר tokenColors של VS Code למילון צבעים עבור CodeMirror HighlightStyle.

    🎨 זה מאפשר צביעה עשירה יותר מאשר classHighlighter בלבד,
    כי כל tag מקבל צבע ייחודי (לא רק classes משותפים).

    Args:
        token_colors: רשימת tokenColors מקובץ VS Code theme

    Returns:
        מילון בפורמט: {
            "keyword": {"color": "#ff0000"},
            "controlKeyword": {"color": "#00ff00", "fontStyle": "bold"},
            ...
        }
    """
    if not isinstance(token_colors, list):
        return {}

    # מילון צבעים לפי tag
    colors_by_tag: dict[str, dict] = {}

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
            cm_tag = _find_cm_tag(str(scope))
            if not cm_tag:
                continue

            # 🔑 אם כבר יש צבע לזה, נדלג (הראשון מנצח - בד"כ הספציפי יותר)
            if cm_tag in colors_by_tag:
                continue

            style: dict[str, str] = {"color": str(foreground).strip()}

            fs = str(font_style).lower()
            if "italic" in fs:
                style["fontStyle"] = "italic"
            if "bold" in fs:
                style["fontWeight"] = "bold"

            colors_by_tag[cm_tag] = style

    return colors_by_tag


def _find_hljs_class(scope: str) -> str | None:
    """
    מוצא את ה-highlight.js class המתאים ל-scope.

    Args:
        scope: VS Code TextMate scope (e.g., "keyword.control.import")

    Returns:
        highlight.js CSS class (e.g., ".hljs-keyword") או None אם אין התאמה
    """
    if not scope or not isinstance(scope, str):
        return None

    # התאמה מדויקת - עדיפות ראשונה
    if scope in TOKEN_TO_HLJS_MAP:
        return TOKEN_TO_HLJS_MAP[scope]

    # חיפוש ההתאמה הספציפית ביותר (הארוכה ביותר)
    best_match: str | None = None
    best_match_length = 0

    for vs_scope, hljs_class in TOKEN_TO_HLJS_MAP.items():
        if scope.startswith(vs_scope + ".") or scope == vs_scope:
            if len(vs_scope) > best_match_length:
                best_match = hljs_class
                best_match_length = len(vs_scope)
        elif vs_scope.startswith(scope + ".") or vs_scope == scope:
            if len(scope) > best_match_length:
                best_match = hljs_class
                best_match_length = len(scope)

    return best_match


def generate_hljs_css_from_tokens(
    token_colors: list[dict],
    default_foreground: str | None = None,
    default_background: str | None = None,
) -> str:
    """
    ממיר tokenColors של VS Code ל-CSS עבור highlight.js.

    🔑 אם יש כמה scopes שממופים לאותו hljs class,
    הכלל הראשון מנצח (הספציפי יותר בד"כ מופיע קודם בקובץ VS Code).

    Args:
        token_colors: רשימת tokenColors מערכת VS Code
        default_foreground: צבע ברירת מחדל לטקסט (editor.foreground)
        default_background: צבע רקע לבלוקי קוד (editor.background)

    Returns:
        CSS string עם כללים בפורמט:
        .hljs-keyword { color: #...; }
    """
    if not isinstance(token_colors, list):
        return ""

    # שימוש ב-dict כדי לדדופ כללים לפי selector
    css_by_selector: dict[str, str] = {}

    # 🆕 הוספת צבע ברירת מחדל עבור .hljs (טקסט שלא מסומן)
    # זה חשוב עבור משתנים, קבועים ואלמנטים ש-highlight.js לא מסמן
    if default_foreground and is_valid_color(str(default_foreground)):
        base_parts = [f"color: {str(default_foreground).strip()} !important"]
        if default_background and is_valid_color(str(default_background)):
            base_parts.append(f"background: {str(default_background).strip()} !important")
        css_by_selector[".hljs"] = f':root[data-theme-type="custom"] .hljs {{ {"; ".join(base_parts)}; }}'

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
            hljs_class = _find_hljs_class(str(scope))
            if not hljs_class:
                continue

            # אם כבר יש כלל לזה, נדלג (הראשון מנצח)
            if hljs_class in css_by_selector:
                continue

            # CSS עם !important כדי לדרוס hljs default styles
            rule_parts = [f"color: {str(foreground).strip()} !important"]

            fs = str(font_style).lower()
            if "italic" in fs:
                rule_parts.append("font-style: italic !important")
            if "bold" in fs:
                rule_parts.append("font-weight: bold !important")
            if "underline" in fs:
                rule_parts.append("text-decoration: underline !important")

            # highlight.js classes need to work inside .hljs container
            # תומך גם ב-custom וגם ב-shared themes
            # הסלקטור צריך לעבוד כשה-theme הוא custom או shared
            css_by_selector[hljs_class] = f':root[data-theme-type="custom"] {hljs_class} {{ {"; ".join(rule_parts)}; }}'

    return "\n".join(css_by_selector.values())


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


def _find_codemirror_class(scope: str) -> str | None:
    """
    מוצא את ה-CodeMirror class המתאים ל-scope.
    תומך בהתאמה חלקית (prefix matching) ומעדיף התאמה ספציפית יותר.

    לדוגמה: עבור "constant.numeric.integer.decimal":
    - יתאים ל-"constant.numeric" (6 תווים prefix) ✓
    - יתאים ל-"constant" (8 תווים prefix) ✓
    - יחזיר "constant.numeric" כי הוא הספציפי ביותר (ארוך יותר)
    """
    if not scope or not isinstance(scope, str):
        return None

    # התאמה מדויקת - עדיפות ראשונה
    if scope in TOKEN_TO_CODEMIRROR_MAP:
        return TOKEN_TO_CODEMIRROR_MAP[scope]

    # חיפוש ההתאמה הספציפית ביותר (הארוכה ביותר)
    best_match: str | None = None
    best_match_length = 0

    for vs_scope, cm_class in TOKEN_TO_CODEMIRROR_MAP.items():
        # בדיקה: האם ה-scope מתחיל ב-vs_scope
        # לדוגמה: "constant.numeric.integer" מתחיל ב-"constant.numeric"
        if scope.startswith(vs_scope + ".") or scope == vs_scope:
            if len(vs_scope) > best_match_length:
                best_match = cm_class
                best_match_length = len(vs_scope)

        # בדיקה הפוכה: האם vs_scope מתחיל ב-scope
        # לדוגמה: "constant.numeric" מתחיל ב-"constant"
        # (פחות שכיח אבל נשמר לתאימות)
        elif vs_scope.startswith(scope + ".") or vs_scope == scope:
            if len(scope) > best_match_length:
                best_match = cm_class
                best_match_length = len(scope)

    return best_match


def generate_codemirror_css_from_tokens(token_colors: list[dict]) -> str:
    """
    ממיר tokenColors של VS Code ל-CSS עבור CodeMirror.

    🔑 אם יש כמה scopes שממופים לאותו CodeMirror class,
    הכלל הראשון מנצח (הספציפי יותר בד"כ מופיע קודם בקובץ VS Code).
    """
    if not isinstance(token_colors, list):
        return ""

    # 🎨 שימוש ב-dict כדי לדדופ כללים לפי selector
    # הכלל הראשון לכל selector מנצח
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
            cm_class = _find_codemirror_class(str(scope))
            if not cm_class:
                continue

            # 🔑 אם כבר יש כלל לזה, נדלג (הראשון מנצח)
            if cm_class in css_by_selector:
                continue

            # 🎨 !important נדרש כדי לדרוס inline styles של CodeMirror themes
            rule_parts = [f"color: {str(foreground).strip()} !important"]

            fs = str(font_style).lower()
            if "italic" in fs:
                rule_parts.append("font-style: italic !important")
            if "bold" in fs:
                rule_parts.append("font-weight: bold !important")
            if "underline" in fs:
                rule_parts.append("text-decoration: underline !important")

            # חשוב: אנחנו תומכים גם ב-Shared Themes, לכן משתמשים ב-data-theme-type="custom"
            # (במקום data-theme="custom" הקשיח)
            css_by_selector[cm_class] = (
                f':root[data-theme-type="custom"] {cm_class} {{ {"; ".join(rule_parts)}; }}'
            )

    return "\n".join(css_by_selector.values())


def sanitize_codemirror_css(css: str) -> str:
    """
    🔒 מנקה CSS של CodeMirror (syntax_css) כדי למנוע CSS injection.

    מאפשר רק חוקים בפורמט:
    :root[data-theme-type="custom"] .<tok|cm>-<token> { color: <HEX/RGB/RGBA>; [font-style: italic;] [font-weight: bold;] [text-decoration: underline;] }

    תומך גם ב-tok- classes (CodeMirror 6 classHighlighter) וגם ב-cm- classes (legacy).
    """
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

        # 🎨 תומך גם ב-tok- (CodeMirror 6) וגם ב-cm- (legacy)
        # תומך גם ב-composite selectors כמו .tok-variableName.tok-definition
        tok_pattern = r'\.tok-[a-zA-Z0-9_-]+'
        cm_pattern = r'\.cm-[a-z0-9_-]+'
        single_class = f'({tok_pattern}|{cm_pattern})'
        # מאפשר עד 3 classes משורשרים (לדוג' .tok-variableName.tok-definition.tok-local)
        composite_pattern = f'^{single_class}({single_class}){{0,2}}$'
        if not re.match(composite_pattern, selector):
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

        # ננרמל תמיד לפורמט החדש, כדי שיתפוס גם custom וגם shared (דרך data-theme-type).
        safe_rules.append(f':root[data-theme-type="custom"] {selector} {{ {"; ".join(out_parts)}; }}')

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

