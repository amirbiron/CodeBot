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
VALID_COLOR_REGEX = re.compile(
    r'^#[0-9a-fA-F]{3,8}$|'  # hex (3, 4, 6, or 8 chars)
    r'^rgb\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\)$|'  # rgb
    r'^rgba\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*[\d.]+\s*\)$'  # rgba
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


def validate_theme_json(json_content: str) -> tuple[bool, str]:
    """מוודא שקובץ JSON הוא ערכת נושא תקינה."""
    try:
        data = json.loads(json_content)
    except json.JSONDecodeError as e:
        return False, f"קובץ JSON לא תקין: {e}"

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
    """
    if isinstance(json_content, str):
        try:
            theme_data = json.loads(json_content)
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

    return {
        "name": theme_data.get("name", "Imported Theme"),
        "type": theme_type,
        "variables": result,
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
    rgb_match = re.match(r"^rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)$", color)
    if rgb_match:
        r, g, b = map(int, rgb_match.groups())
        if all(0 <= c <= 255 for c in (r, g, b)):
            return (r, g, b, 1.0)
        return None

    # RGBA format
    rgba_match = re.match(
        r"^rgba\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*([\d.]+)\s*\)$",
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
# Syntax Highlighting: tokenColors → CodeMirror CSS
# ==========================================

TOKEN_TO_CODEMIRROR_MAP: dict[str, str] = {
    # Comments
    "comment": ".cm-comment",
    "punctuation.definition.comment": ".cm-comment",

    # Strings
    "string": ".cm-string",
    "string.quoted": ".cm-string",

    # Keywords
    "keyword": ".cm-keyword",
    "storage.type": ".cm-keyword",
    "storage.modifier": ".cm-keyword",

    # Functions
    "entity.name.function": ".cm-def",
    "support.function": ".cm-builtin",

    # Variables
    "variable": ".cm-variable",
    "variable.parameter": ".cm-variable-2",
    "variable.other": ".cm-variable-3",

    # Constants
    "constant.numeric": ".cm-number",
    "constant.language": ".cm-atom",

    # Types
    "entity.name.type": ".cm-type",
    "support.type": ".cm-type",

    # Operators
    "keyword.operator": ".cm-operator",

    # Properties
    "entity.other.attribute-name": ".cm-attribute",
    "support.type.property-name": ".cm-property",

    # Tags (HTML/XML)
    "entity.name.tag": ".cm-tag",

    # Errors
    "invalid": ".cm-error",
}


def _find_codemirror_class(scope: str) -> str | None:
    """מוצא את ה-CodeMirror class המתאים ל-scope. תומך בהתאמה חלקית (prefix matching)."""
    if not scope or not isinstance(scope, str):
        return None

    # התאמה מדויקת
    if scope in TOKEN_TO_CODEMIRROR_MAP:
        return TOKEN_TO_CODEMIRROR_MAP[scope]

    # התאמה לפי prefix
    for vs_scope, cm_class in TOKEN_TO_CODEMIRROR_MAP.items():
        if scope.startswith(vs_scope) or vs_scope.startswith(scope):
            return cm_class

    return None


def generate_codemirror_css_from_tokens(token_colors: list[dict]) -> str:
    """
    ממיר tokenColors של VS Code ל-CSS עבור CodeMirror.
    """
    if not isinstance(token_colors, list):
        return ""

    css_rules: list[str] = []

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

            rule_parts = [f"color: {str(foreground).strip()}"]

            fs = str(font_style).lower()
            if "italic" in fs:
                rule_parts.append("font-style: italic")
            if "bold" in fs:
                rule_parts.append("font-weight: bold")
            if "underline" in fs:
                rule_parts.append("text-decoration: underline")

            css_rules.append(
                f':root[data-theme="custom"] {cm_class} {{ {"; ".join(rule_parts)}; }}'
            )

    return "\n".join(css_rules)


def sanitize_codemirror_css(css: str) -> str:
    """
    🔒 מנקה CSS של CodeMirror (syntax_css) כדי למנוע CSS injection.

    מאפשר רק חוקים בפורמט:
    :root[data-theme="custom"] .cm-<token> { color: <HEX/RGB/RGBA>; [font-style: italic;] [font-weight: bold;] [text-decoration: underline;] }
    """
    if not css or not isinstance(css, str):
        return ""

    safe_rules: list[str] = []

    for raw_line in css.splitlines():
        line = raw_line.strip()
        if not line:
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

        m = re.match(r'^:root\[data-theme="custom"\]\s+(\.[^\s{]+)\s*\{\s*(.*?)\s*\}\s*$', line)
        if not m:
            continue

        selector = m.group(1).strip()
        body = m.group(2).strip()

        if not re.match(r'^\.(cm-[a-z0-9_-]+)$', selector):
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

            if prop == "color":
                clean = sanitize_css_value(val)
                if not clean:
                    ok = False
                    break
                out_parts.append(f"color: {clean}")
            elif prop == "font-style":
                if val.strip().lower() != "italic":
                    ok = False
                    break
                out_parts.append("font-style: italic")
            elif prop == "font-weight":
                if val.strip().lower() != "bold":
                    ok = False
                    break
                out_parts.append("font-weight: bold")
            elif prop == "text-decoration":
                if val.strip().lower() != "underline":
                    ok = False
                    break
                out_parts.append("text-decoration: underline")
            else:
                ok = False
                break

        if not ok:
            continue

        # חייב להיות לפחות color
        if not any(p.startswith("color:") for p in out_parts):
            continue

        safe_rules.append(f':root[data-theme="custom"] {selector} {{ {"; ".join(out_parts)}; }}')

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

