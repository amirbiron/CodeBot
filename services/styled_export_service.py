"""
Styled HTML Export Service
ייצוא קבצי Markdown כ-HTML מעוצב עם ערכות נושא

🔒 אבטחה:
- כל HTML עובר sanitization דרך bleach למניעת XSS
- מותרים רק תגיות ו-attributes ברשימה לבנה
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
from typing import Optional

import bleach
import markdown

# Pygments for dynamic syntax highlighting CSS
try:
    from pygments.formatters import HtmlFormatter
    from pygments.styles import get_style_by_name

    HAS_PYGMENTS = True
except ImportError:  # pragma: no cover
    HtmlFormatter = None  # type: ignore[assignment, misc]
    get_style_by_name = None  # type: ignore[assignment]
    HAS_PYGMENTS = False

from services.theme_parser_service import (
    FALLBACK_DARK,
    FALLBACK_LIGHT,
    parse_vscode_theme,
)
from services.theme_presets_service import get_preset_by_id, list_presets

logger = logging.getLogger(__name__)


# ============================================
# 🎨 מיפוי ערכות נושא ל-Pygments Styles
# ============================================
# מיפוי בין מזהי ערכות הנושא שלנו לבין styles מובנים של Pygments
# אם ערכה לא נמצאת כאן, נשתמש ב-style ברירת מחדל לפי סוג הערכה (dark/light)

THEME_TO_PYGMENTS_STYLE: dict[str, str] = {
    # Dark themes
    "tech-guide-dark": "monokai",
    "github-dark": "github-dark",
    "dracula": "dracula",
    "one-dark": "one-dark",
    "monokai": "monokai",
    "gruvbox-dark": "gruvbox-dark",
    "nord": "nord",
    "tokyo-night": "monokai",
    "material-dark": "material",
    "synthwave": "monokai",
    "cyberpunk": "monokai",
    # Light themes
    "clean-light": "default",
    "github-light": "github-dark",  # github-dark works well for light too
    "minimal": "default",
    "solarized-light": "solarized-light",
    "gruvbox-light": "gruvbox-light",
}

# Fallback styles לפי קטגוריה
PYGMENTS_STYLE_DARK_FALLBACK = "monokai"
PYGMENTS_STYLE_LIGHT_FALLBACK = "default"

# ============================================
# 🔒 Sanitization policy (shared)
# ============================================

# רשימה לבנה של תגיות מותרות
ALLOWED_TAGS = list(bleach.sanitizer.ALLOWED_TAGS) + [
    "div",
    "span",
    "p",
    "br",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "pre",
    "code",
    "img",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "blockquote",
    "ul",
    "ol",
    "li",
    "hr",
    "a",
    "b",
    "i",
    "strong",
    "em",
    "del",
    "ins",
    "sup",
    "sub",
    "mark",
    "nav",  # עבור TOC wrapper
]

# רשימה לבנה של attributes מותרים
ALLOWED_ATTRS = {
    "*": ["class", "id"],  # id נדרש עבור anchors של TOC
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "title", "width", "height"],
    "th": ["colspan", "rowspan"],
    "td": ["colspan", "rowspan"],
    "code": ["class"],  # עבור codehilite language classes
    "span": ["class"],  # עבור syntax highlighting
    "pre": ["class"],
}

# פרוטוקולים מותרים (חוסם javascript:, data: וכו')
ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


# ============================================
# Markdown Preprocessing
# ============================================

def preprocess_markdown(text: str) -> str:
    """
    עיבוד מקדים של Markdown לפני המרה ל-HTML.

    ממיר סינטקס מיוחד:
    - ::: note/info/warning/important/danger/success/tip → <div class="alert alert-*">
    """
    if not text:
        return ""

    # Pattern for ::: type ... :::
    # הסוגר ::: חייב להופיע בתחילת שורה (אחרי newline או בסוף) כדי למנוע חיתוך מוקדם
    # אם התוכן מכיל ::: באמצע, זה לא יתפוס כסוגר
    # תומך גם ב-title אופציונלי אחרי הסוג (מושלך) כדי לא לשבור שימושים עתידיים:
    # ::: warning כותרת
    # תוכן...
    # :::
    pattern = r"^:::\s*(note|info|warning|important|danger|success|tip)\b[^\n]*\n(.*?)\n:::$"

    def replacer(match):
        alert_type = match.group(1).lower()
        content = match.group(2).strip()

        # מיפוי סוגים ל-CSS classes
        type_map = {
            "note": "info",
            "tip": "success",
            "info": "info",
            "warning": "warning",
            "important": "warning",
            "danger": "danger",
            "success": "success",
        }
        css_class = type_map.get(alert_type, "info")

        # המרת תוכן פנימי ל-HTML (תומך ב-Markdown בתוך alerts)
        inner_html = markdown.markdown(content, extensions=["nl2br"])

        # 🔒 סניטציה מיידית ל-HTML הפנימי כדי לצמצם תלות בשלבי עיבוד מאוחרים
        clean_inner_html = bleach.clean(
            inner_html,
            tags=ALLOWED_TAGS,
            attributes=ALLOWED_ATTRS,
            protocols=ALLOWED_PROTOCOLS,
            strip=True,
        )

        return f'<div class="alert alert-{css_class}">{clean_inner_html}</div>'

    # MULTILINE כדי ש-^ ו-$ יתאימו לתחילת/סוף שורה, DOTALL כדי ש-. יתפוס newlines
    return re.sub(pattern, replacer, text, flags=re.DOTALL | re.MULTILINE)


def markdown_to_html(text: str, include_toc: bool = False) -> tuple[str, str]:
    """
    המרת Markdown ל-HTML עם extensions מתאימים.

    🔒 אבטחה: ה-HTML עובר sanitization דרך bleach למניעת XSS.

    Args:
        text: תוכן Markdown
        include_toc: האם להחזיר גם תוכן עניינים

    Returns:
        tuple של (html_content, toc_html)
        אם include_toc=False, toc_html יהיה ריק
    """
    if not text:
        return ("", "")

    # עיבוד מקדים
    processed = preprocess_markdown(text)

    # יצירת אובייקט Markdown (לא פונקציה) כדי לגשת ל-TOC
    md = markdown.Markdown(
        extensions=[
            "fenced_code",  # ```code blocks```
            "tables",  # טבלאות GFM
            "nl2br",  # שורות חדשות → <br>
            "toc",  # תוכן עניינים
            "codehilite",  # הדגשת קוד (עם Pygments)
            "attr_list",  # attributes על אלמנטים
        ],
        extension_configs={
            "codehilite": {
                "css_class": "highlight",
                "linenums": False,
                "guess_lang": True,
            },
            "toc": {
                "title": "📑 תוכן עניינים",
                "toc_depth": 3,
            },
        },
    )

    # המרה ל-HTML
    html_raw = md.convert(processed)
    # 🔒 אבטחה: הסרת בלוקים מסוכנים יחד עם התוכן (script/style)
    html_raw = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", html_raw, flags=re.IGNORECASE | re.DOTALL)

    # ניקוי ה-HTML
    clean_html = bleach.clean(
        html_raw,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,  # הסרת תגיות לא מורשות במקום escape
    )

    # הוספת rel="noopener noreferrer" לכל קישורים עם target="_blank"
    # שימוש ב-regex כדי להימנע מ-duplicate attributes
    def add_noopener(match):
        tag = match.group(0)
        # בדיקה אם יש rel כאטריביוט (לא בתוך href או ערך אחר)
        # שימוש ברגקס שמחפש rel= מחוץ למירכאות
        has_rel_attr = re.search(r'\srel\s*=\s*(["\'])', tag)

        if has_rel_attr:
            # החלפת rel קיים
            # 🔒 חשוב: match של אותו סוג מרכאות בפתיחה/סגירה כדי לא לחתוך ערכים עם גרשיים/מרכאות פנימיים
            tag = re.sub(
                r'\srel\s*=\s*(["\']).*?\1',
                ' rel="noopener noreferrer"',
                tag,
                count=1,
                flags=re.IGNORECASE,
            )
        else:
            # הוספת rel חדש
            tag = tag.replace('target="_blank"', 'target="_blank" rel="noopener noreferrer"')
        return tag

    # מציאת כל תגיות a עם target="_blank"
    clean_html = re.sub(
        r'<a\s[^>]*target="_blank"[^>]*>',
        add_noopener,
        clean_html,
    )

    # החזרת HTML + TOC (אם נדרש)
    toc_html = ""
    if include_toc and hasattr(md, "toc"):
        # TOC נוצר ע"י Python-Markdown ומכיל רק ul/li/a עם anchors
        # אבל נעביר גם אותו דרך bleach לבטיחות
        toc_raw = md.toc
        toc_html = bleach.clean(
            toc_raw,
            tags=["div", "nav", "ul", "li", "a"],
            attributes={"a": ["href", "title"], "*": ["class", "id"]},
            protocols=["http", "https", "#"],  # # עבור anchors פנימיים
            strip=True,
        )

    return (clean_html, toc_html)


# ============================================
# Theme Resolution
# ============================================

# Presets מיוחדים לייצוא (בנוסף לאלו שבגלריה)
EXPORT_PRESETS = {
    "tech-guide-dark": {
        "id": "tech-guide-dark",
        "name": "Tech Guide Dark",
        "description": "עיצוב טכני כהה מקצועי - מושלם למדריכים ותיעוד",
        "category": "dark",
        "variables": {
            # רקעים (מבוססים על editor.background, sideBar.background)
            "--bg-primary": "#0f0f23",
            "--bg-secondary": "#16213e",
            "--bg-tertiary": "#1a1a2e",

            # טקסט (מבוססים על editor.foreground)
            "--text-primary": "#c3cee3",
            "--text-secondary": "#c3cee3",
            "--text-muted": "#3d5a80",
            "--text-heading": "#eeeeee",

            # צבעי מותג
            "--primary": "#0088cc",
            "--primary-hover": "#0099dd",
            "--primary-light": "#0088cc26",
            "--secondary": "#9b59b6",

            # גבולות וצללים
            "--border-color": "#3d5a80",
            "--shadow-color": "rgba(0, 0, 0, 0.4)",

            # סטטוסים (מבוססים על terminal colors)
            "--success": "#2ecc71",
            "--warning": "#f39c12",
            "--error": "#e74c3c",
            "--danger-bg": "#e74c3c",
            "--danger-border": "#c0392b",

            # קוד (מבוססים על terminal.background)
            "--code-bg": "#0f0f23",
            "--code-text": "#7fdbca",
            "--code-border": "#3d5a80",
            "--code-line-highlight": "#16213e",

            # קישורים
            "--link-color": "#0088cc",

            # כרטיסים
            "--card-bg": "#16213e",
            "--card-border": "#3d5a80",

            # Alerts
            "--alert-info-border": "#0088cc",
            "--alert-info-bg": "rgba(0, 136, 204, 0.08)",
            "--alert-warning-border": "#f39c12",
            "--alert-warning-bg": "rgba(243, 156, 18, 0.08)",
            "--alert-success-border": "#2ecc71",
            "--alert-success-bg": "rgba(46, 204, 113, 0.08)",
            "--alert-danger-border": "#e74c3c",
            "--alert-danger-bg": "rgba(231, 76, 60, 0.08)",

            # כפתורים (מבוססים על button.background)
            "--btn-bg": "#0088cc",
            "--btn-hover-bg": "#0099dd",
            "--btn-color": "#ffffff",

            # Copy Button
            "--copy-btn-bg": "rgba(255, 255, 255, 0.1)",
            "--copy-btn-hover-bg": "#0088cc",
            "--copy-btn-success-bg": "#2ecc71",
        },
        # Syntax highlighting CSS (מבוסס על tokenColors מה-JSON)
        "syntax_css": """
/* Tech Guide Dark - Syntax Highlighting */
.highlight .c, .highlight .c1, .highlight .cm { color: #6a9955; font-style: italic; }  /* Comments */
.highlight .k, .highlight .kd, .highlight .kn { color: #c586c0; }  /* Keywords */
.highlight .s, .highlight .s1, .highlight .s2 { color: #ce9178; }  /* Strings */
.highlight .m, .highlight .mi, .highlight .mf, .highlight .mh { color: #b5cea8; }  /* Numbers */
.highlight .nb, .highlight .bp { color: #b5cea8; }  /* Built-ins / Constants */
.highlight .n, .highlight .nv { color: #9cdcfe; }  /* Variables */
.highlight .nf, .highlight .fm { color: #dcdcaa; }  /* Functions */
.highlight .nc, .highlight .nn { color: #4ec9b0; }  /* Classes / Namespaces */
.highlight .nt { color: #569cd6; }  /* HTML Tags */
.highlight .na { color: #9cdcfe; }  /* Attributes */
.highlight .o, .highlight .p { color: #d4d4d4; }  /* Operators / Punctuation */
.highlight .sr { color: #d16969; }  /* Regex */
.highlight .se { color: #d7ba7d; }  /* Escape */
.highlight .gh, .highlight .gu { color: #0088cc; font-weight: bold; }  /* Headings */
.highlight .ge { font-style: italic; }  /* Emphasis */
.highlight .gs { font-weight: bold; }  /* Strong */
.highlight .err { color: #f44747; text-decoration: underline; }  /* Errors */
""",
    },
    "clean-light": {
        "id": "clean-light",
        "name": "Clean Light",
        "description": "עיצוב בהיר ונקי - קריא ומודרני",
        "category": "light",
        "variables": {
            "--bg-primary": "#ffffff",
            "--bg-secondary": "#f8f9fa",
            "--bg-tertiary": "#e9ecef",
            "--text-primary": "#212529",
            "--text-secondary": "#495057",
            "--text-muted": "#6c757d",
            "--primary": "#0d6efd",
            "--primary-hover": "#0b5ed7",
            "--primary-light": "#0d6efd26",
            "--secondary": "#6c757d",
            "--border-color": "#dee2e6",
            "--shadow-color": "rgba(0, 0, 0, 0.1)",
            "--success": "#198754",
            "--warning": "#ffc107",
            "--error": "#dc3545",
            "--danger-bg": "#dc3545",
            "--danger-border": "#b02a37",
            "--code-bg": "#f8f9fa",
            "--code-text": "#212529",
            "--code-border": "#dee2e6",
            "--link-color": "#0d6efd",
            "--card-bg": "#ffffff",
            "--card-border": "#dee2e6",
        },
    },
    "minimal": {
        "id": "minimal",
        "name": "Minimal",
        "description": "עיצוב מינימליסטי - פשוט ואלגנטי",
        "category": "light",
        "variables": {
            "--bg-primary": "#fafafa",
            "--bg-secondary": "#f5f5f5",
            "--bg-tertiary": "#eeeeee",
            "--text-primary": "#333333",
            "--text-secondary": "#666666",
            "--text-muted": "#999999",
            "--primary": "#333333",
            "--primary-hover": "#000000",
            "--primary-light": "#33333326",
            "--secondary": "#666666",
            "--border-color": "#e0e0e0",
            "--shadow-color": "rgba(0, 0, 0, 0.05)",
            "--success": "#4caf50",
            "--warning": "#ff9800",
            "--error": "#f44336",
            "--code-bg": "#f5f5f5",
            "--code-text": "#333333",
            "--code-border": "#e0e0e0",
            "--link-color": "#1976d2",
            "--card-bg": "#ffffff",
            "--card-border": "#e0e0e0",
        },
    },
}


def get_export_theme(
    theme_id: str,
    user_themes: Optional[list] = None,
    vscode_json: Optional[str] = None,
) -> dict:
    """
    מחזיר ערכת נושא לפי ID או JSON.

    סדר עדיפויות:
    1. VS Code JSON (אם סופק)
    2. Export Presets מיוחדים
    3. Presets מהגלריה הכללית
    4. ערכות המשתמש (מ-DB)
    5. Fallback ל-technical-dark

    Args:
        theme_id: מזהה הערכה
        user_themes: רשימת ערכות המשתמש (מ-MongoDB)
        vscode_json: תוכן JSON של ערכת VS Code (אופציונלי)

    Returns:
        dict עם name, variables, ו-syntax_css (אופציונלי)
    """

    # 1. VS Code JSON ישיר
    if vscode_json:
        try:
            parsed = parse_vscode_theme(vscode_json)
            theme_type = (parsed.get("type") if isinstance(parsed, dict) else None) or "dark"
            fallback = FALLBACK_DARK if str(theme_type).lower() == "dark" else FALLBACK_LIGHT
            return {
                "id": "vscode-import",
                "name": parsed.get("name", "Imported Theme"),
                "category": str(theme_type).lower(),
                "variables": parsed.get("variables", fallback),
                "syntax_css": parsed.get("syntax_css", ""),
            }
        except Exception as e:
            logger.warning("Failed to parse VS Code theme: %s", e)

    # 2. Export Presets מיוחדים
    if theme_id in EXPORT_PRESETS:
        preset = EXPORT_PRESETS[theme_id]
        return {
            "id": theme_id,
            "name": preset["name"],
            "category": preset.get("category", "dark"),
            "variables": preset["variables"],
            "syntax_css": preset.get("syntax_css", ""),
        }

    # 3. Presets מהגלריה הכללית
    gallery_preset = get_preset_by_id(theme_id)
    if gallery_preset:
        return {
            "id": theme_id,
            "name": gallery_preset["name"],
            "category": gallery_preset.get("category", "dark"),
            "variables": gallery_preset.get("variables", FALLBACK_DARK),
            "syntax_css": gallery_preset.get("syntax_css", ""),
        }

    # 4. ערכות המשתמש
    if user_themes:
        for theme in user_themes:
            if not isinstance(theme, dict):
                continue
            if theme.get("id") == theme_id:
                # 🔧 תיקון: אם ה-syntax_css שמור עם selector ישן (.source),
                # נתקן את ה-Pygments selectors בלבד (לא לפגוע ב-CodeMirror)
                stored_css = theme.get("syntax_css", "")
                if stored_css and ".source " in stored_css:
                    # תיקון Pygments CSS: [data-theme-type="custom"] .source .X → .highlight .X
                    # ⚠️ לא לגעת ב-CodeMirror שמתחיל ב-:root[data-theme-type="custom"]
                    stored_css = stored_css.replace(
                        '[data-theme-type="custom"] .source ',
                        '.highlight '
                    )
                
                return {
                    "id": theme_id,
                    "name": theme.get("name", "My Theme"),
                    "category": theme.get("category", "dark"),
                    "variables": theme.get("variables", FALLBACK_DARK),
                    "syntax_css": stored_css,
                }

    # 5. Fallback
    logger.info("Theme '%s' not found, using tech-guide-dark fallback", theme_id)
    return {
        "id": "tech-guide-dark",
        "name": "Tech Guide Dark",
        "category": "dark",
        "variables": EXPORT_PRESETS["tech-guide-dark"]["variables"],
        "syntax_css": EXPORT_PRESETS["tech-guide-dark"].get("syntax_css", ""),
    }


def list_export_presets() -> list[dict]:
    """
    מחזיר רשימת Presets זמינים לייצוא.

    Returns:
        רשימה של {id, name, description, category, preview_colors}
    """
    presets: list[dict] = []

    # Export Presets מיוחדים
    for preset_id, preset in EXPORT_PRESETS.items():
        presets.append(
            {
                "id": preset_id,
                "name": preset["name"],
                "description": preset.get("description", ""),
                "category": preset.get("category", "dark"),
                "preview_colors": _extract_preview_colors(preset.get("variables", {})),
            }
        )

    # Presets מהגלריה הכללית
    gallery_presets = list_presets()
    for p in gallery_presets:
        if p["id"] not in EXPORT_PRESETS:  # הימנעות מכפילויות
            presets.append(p)

    return presets


def _extract_preview_colors(variables: dict) -> list[str]:
    """מחלץ 3 צבעים לתצוגה מקדימה."""
    colors = []
    for key in ["--bg-primary", "--text-primary", "--primary"]:
        if key in variables:
            colors.append(variables[key])
    return colors[:3] or ["#1a1a2e", "#eeeeee", "#0088cc"]


# ============================================
# 🎨 Pygments CSS Generation
# ============================================


def get_pygments_style_for_theme(theme_id: str, theme_category: str = "dark") -> str:
    """
    מחזיר את שם ה-Pygments style המתאים לערכת נושא.

    Args:
        theme_id: מזהה הערכה
        theme_category: קטגוריית הערכה ('dark' או 'light')

    Returns:
        שם ה-Pygments style
    """
    # בדיקה במיפוי הישיר
    if theme_id in THEME_TO_PYGMENTS_STYLE:
        return THEME_TO_PYGMENTS_STYLE[theme_id]

    # fallback לפי קטגוריה
    # 🔒 הגנה מפני None (יכול להגיע מ-MongoDB עם "category": null)
    category = (theme_category or "dark").lower()
    if category == "light":
        return PYGMENTS_STYLE_LIGHT_FALLBACK
    return PYGMENTS_STYLE_DARK_FALLBACK


def generate_pygments_css(
    style_name: str = "monokai",
    css_class: str = ".highlight",
    theme_category: str = "dark",
) -> str:
    """
    מייצר CSS להדגשת תחביר באמצעות Pygments.

    Args:
        style_name: שם ה-Pygments style (לדוגמה: 'monokai', 'default', 'github-dark')
        css_class: ה-CSS class שמשמש לעטיפת הקוד (ברירת מחדל: '.highlight')
        theme_category: קטגוריית הערכה ('dark' או 'light') - משמש לבחירת fallback מתאים

    Returns:
        מחרוזת CSS עם הגדרות הצבעים להדגשת תחביר
    """
    if not HAS_PYGMENTS:
        logger.warning("Pygments not available, returning empty CSS")
        return ""

    try:
        # נסה לטעון את ה-style המבוקש
        try:
            style = get_style_by_name(style_name)
        except Exception:
            # אם לא נמצא, השתמש ב-fallback לפי הקטגוריה
            # 🔒 הגנה מפני None
            category = (theme_category or "dark").lower()
            fallback_style = (
                PYGMENTS_STYLE_LIGHT_FALLBACK
                if category == "light"
                else PYGMENTS_STYLE_DARK_FALLBACK
            )
            logger.warning(
                "Pygments style '%s' not found, using %s fallback for %s theme",
                style_name,
                fallback_style,
                category,
            )
            style = get_style_by_name(fallback_style)

        # יצירת ה-formatter עם ה-style
        formatter = HtmlFormatter(style=style, cssclass=css_class.lstrip("."))

        # קבלת הגדרות ה-CSS
        css_defs = formatter.get_style_defs(css_class)

        return css_defs

    except Exception as e:
        logger.exception("Failed to generate Pygments CSS: %s", e)
        return ""


# ============================================
# HTML Generation
# ============================================

def sanitize_css_value(value: str) -> str:
    """
    🔒 מנקה ערך CSS בודד מתווים מסוכנים.

    מונע CSS injection כמו: #fff; } body { display: none; } :root { --x:
    """
    if not value:
        return ""

    # תווים שיכולים לשבור את ההקשר של CSS value
    dangerous_chars = ["{", "}", ";", "<", ">", '"', "'", "\\", "\n", "\r"]

    clean_value = value
    for char in dangerous_chars:
        clean_value = clean_value.replace(char, "")

    # אם הערך ריק אחרי הניקוי, החזר ערך ברירת מחדל
    return clean_value.strip() or "inherit"


def generate_css_variables(variables: dict) -> str:
    """
    מייצר CSS Variables מתוך מילון.

    Returns:
        CSS string בפורמט: --var-name: value;
    """
    if not variables:
        return ""

    lines = []
    for key, value in variables.items():
        # 🔒 וולידציה של שם המשתנה - רק אותיות, מספרים, מקפים
        if not re.match(r"^--[a-zA-Z0-9\-]+$", str(key)):
            continue
        if value:
            # 🔒 סניטציה של הערך
            safe_value = sanitize_css_value(str(value))
            if safe_value:
                lines.append(f"    {key}: {safe_value};")

    return "\n".join(lines)


def sanitize_css(css_content: str) -> str:
    """
    🔒 מנקה CSS ממחרוזות מסוכנות שעלולות לפרוץ מבלוק <style>.

    מונע הזרקת </style><script>... או expression(...) וכו'.
    """
    if not css_content:
        return ""

    # רשימת דפוסים מסוכנים
    dangerous_patterns = [
        r"</style",  # סגירת תגית style
        r"<script",  # פתיחת script
        r"</script",  # סגירת script
        r"javascript:",  # JavaScript URI
        r"expression\s*\(",  # IE CSS expression
        r"@import",  # חוסם כל @import (גם url() וגם "...")
        r"behavior\s*:",  # IE behavior
        r"-moz-binding",  # Firefox XBL binding
    ]

    clean_css = css_content
    for pattern in dangerous_patterns:
        clean_css = re.sub(pattern, "/* blocked */", clean_css, flags=re.IGNORECASE)

    return clean_css


# ============================================
# 📋 סקריפט כפתור "העתק" לבלוקי קוד
# ============================================
# הסקריפט מוטמע inline בתוך ה-HTML המעוצב כדי שכפתור ההעתקה יעבוד גם בקובץ
# שמורד למחשב (file://) וגם בתצוגה מקדימה. הקבוע כאן הוא ה-Source of Truth
# היחיד: התבנית מרנדרת אותו כמו שהוא, וה-hash ל-CSP מחושב ממנו (ראו מטה),
# כך שאין סיכון לחוסר-התאמה ("drift") בין הסקריפט ל-hash.
COPY_CODE_SCRIPT = """
(function() {
    'use strict';

    // מוסיף כפתור "העתק" לכל בלוק קוד
    document.querySelectorAll('pre').forEach(function(codeBlock) {
        // יצירת הכפתור
        var button = document.createElement('button');
        button.className = 'copy-btn';
        button.type = 'button';
        button.innerHTML = '📋 <span>העתק</span>';
        button.title = 'העתק קוד ללוח';
        button.setAttribute('aria-label', 'העתק קוד ללוח');

        button.addEventListener('click', function() {
            // מציאת הקוד להעתקה
            var codeEl = codeBlock.querySelector('code');
            var textToCopy = codeEl ? codeEl.innerText : codeBlock.innerText;

            // ניקוי רווחים מיותרים בסוף
            textToCopy = textToCopy.trim();

            // העתקה ללוח
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(textToCopy).then(function() {
                    showSuccess(button);
                }).catch(function() {
                    fallbackCopy(textToCopy, button);
                });
            } else {
                fallbackCopy(textToCopy, button);
            }
        });

        codeBlock.appendChild(button);
    });

    // פידבק ויזואלי להצלחה
    function showSuccess(button) {
        var originalHTML = button.innerHTML;
        button.innerHTML = '✅ <span>הועתק!</span>';
        button.classList.add('success');

        setTimeout(function() {
            button.innerHTML = originalHTML;
            button.classList.remove('success');
        }, 2000);
    }

    // fallback לדפדפנים ישנים
    function fallbackCopy(text, button) {
        var textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();

        try {
            document.execCommand('copy');
            showSuccess(button);
        } catch (err) {
            alert('לא הצלחנו להעתיק את הקוד');
        }

        document.body.removeChild(textarea);
    }
})();
"""


def get_copy_script_csp_hash() -> str:
    """מחזיר את מקור ה-CSP מסוג hash (sha256) עבור סקריפט ההעתקה ה-inline.

    בעמוד השיתוף הציבורי אנחנו שומרים CSP מחמיר שחוסם כל סקריפט, ולכן צריך
    להתיר במפורש את הסקריפט המהימן היחיד שלנו. ה-hash מחושב מאותו מחרוזת
    שמוזרקת לתבנית (COPY_CODE_SCRIPT), כך שהוא תמיד תואם לתוכן בפועל.
    """
    digest = hashlib.sha256(COPY_CODE_SCRIPT.encode("utf-8")).digest()
    return "sha256-" + base64.b64encode(digest).decode("ascii")


# מקור CSP מוכן לשימוש (למשל: "sha256-...."), מחושב פעם אחת בטעינת המודול.
COPY_CODE_SCRIPT_CSP_HASH = get_copy_script_csp_hash()


def render_styled_html(
    content_html: str,
    title: str,
    theme: dict,
    toc_html: str = "",
    footer_text: str = 'נוצר אוטומטית ע"י Code Keeper Bot',
) -> str:
    """
    מרנדר HTML מעוצב מלא.

    Args:
        content_html: תוכן ה-HTML (אחרי המרה מ-Markdown)
        title: כותרת המסמך
        theme: ערכת הנושא (name, variables, syntax_css, id, category)
        toc_html: HTML של תוכן עניינים (אופציונלי)
        footer_text: טקסט בתחתית המסמך

    Returns:
        HTML מלא מוכן להורדה
    """
    css_variables = generate_css_variables(theme.get("variables", {}))

    # 🎨 קבלת CSS להדגשת תחביר
    # Pygments CSS נדרש תמיד עבור בלוקי קוד בייצוא HTML
    # CodeMirror CSS (.tok-*) רלוונטי רק לעורך בדפדפן, לא לייצוא

    theme_id = theme.get("id") or ""
    # 🔒 הגנה מפני None (יכול להגיע מ-MongoDB עם "category": null)
    theme_category = theme.get("category") or "dark"

    syntax_css_raw = theme.get("syntax_css", "")

    # בדיקה אם יש Pygments CSS (כללים עם .highlight)
    has_pygments_css = syntax_css_raw and ".highlight " in syntax_css_raw

    if has_pygments_css:
        # יש CSS מוגדר עם Pygments - נשתמש בו
        syntax_css = sanitize_css(syntax_css_raw)
    else:
        # אין Pygments CSS - נייצר דינמית
        # (גם אם יש CodeMirror CSS, הוא לא רלוונטי לייצוא HTML)
        pygments_style = get_pygments_style_for_theme(theme_id, theme_category)

        # ייצור ה-CSS
        # 🔒 CSS מ-Pygments הוא בטוח (מיוצר פנימית), אבל נעביר דרך sanitize בכל מקרה
        syntax_css = sanitize_css(
            generate_pygments_css(pygments_style, ".highlight", theme_category)
        )

    # ייבוא מאוחר כדי לאפשר שימוש בפונקציות אחרות גם בלי Flask (למשל בטסטים)
    from flask import render_template

    return render_template(
        "export/styled_document.html",
        title=title,
        content=content_html,
        css_variables=css_variables,
        syntax_css=syntax_css,
        theme_name=theme.get("name", "Custom"),
        toc_html=toc_html,
        footer_text=footer_text,
        copy_script=COPY_CODE_SCRIPT,
    )

