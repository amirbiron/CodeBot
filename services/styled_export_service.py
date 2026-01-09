"""
Styled HTML Export Service
ייצוא קבצי Markdown כ-HTML מעוצב עם ערכות נושא

🔒 אבטחה:
- כל HTML עובר sanitization דרך bleach למניעת XSS
- מותרים רק תגיות ו-attributes ברשימה לבנה
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import bleach
import markdown

from services.theme_parser_service import (
    FALLBACK_DARK,
    FALLBACK_LIGHT,
    parse_vscode_theme,
)
from services.theme_presets_service import get_preset_by_id, list_presets

logger = logging.getLogger(__name__)

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
    - ::: info/warning/danger/success/tip → <div class="alert alert-*">
    """
    if not text:
        return ""

    # Pattern for ::: type ... :::
    # הסוגר ::: חייב להופיע בתחילת שורה (אחרי newline או בסוף) כדי למנוע חיתוך מוקדם
    # אם התוכן מכיל ::: באמצע, זה לא יתפוס כסוגר
    pattern = r"^:::\s?(info|warning|danger|success|tip)\s*\n(.*?)\n:::$"

    def replacer(match):
        alert_type = match.group(1).lower()
        content = match.group(2).strip()

        # מיפוי סוגים ל-CSS classes
        type_map = {
            "tip": "success",
            "info": "info",
            "warning": "warning",
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
        has_rel_attr = re.search(r'\srel\s*=\s*["\']', tag)

        if has_rel_attr:
            # החלפת rel קיים
            tag = re.sub(r'\srel\s*=\s*["\'][^"\']*["\']', ' rel="noopener noreferrer"', tag)
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
                "name": parsed.get("name", "Imported Theme"),
                "variables": parsed.get("variables", fallback),
                "syntax_css": parsed.get("syntax_css", ""),
            }
        except Exception as e:
            logger.warning("Failed to parse VS Code theme: %s", e)

    # 2. Export Presets מיוחדים
    if theme_id in EXPORT_PRESETS:
        preset = EXPORT_PRESETS[theme_id]
        return {
            "name": preset["name"],
            "variables": preset["variables"],
            "syntax_css": preset.get("syntax_css", ""),
        }

    # 3. Presets מהגלריה הכללית
    gallery_preset = get_preset_by_id(theme_id)
    if gallery_preset:
        return {
            "name": gallery_preset["name"],
            "variables": gallery_preset.get("variables", FALLBACK_DARK),
            "syntax_css": gallery_preset.get("syntax_css", ""),
        }

    # 4. ערכות המשתמש
    if user_themes:
        for theme in user_themes:
            if not isinstance(theme, dict):
                continue
            if theme.get("id") == theme_id:
                return {
                    "name": theme.get("name", "My Theme"),
                    "variables": theme.get("variables", FALLBACK_DARK),
                    "syntax_css": theme.get("syntax_css", ""),
                }

    # 5. Fallback
    logger.info("Theme '%s' not found, using tech-guide-dark fallback", theme_id)
    return {
        "name": "Tech Guide Dark",
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
        theme: ערכת הנושא (name, variables, syntax_css)
        toc_html: HTML של תוכן עניינים (אופציונלי)
        footer_text: טקסט בתחתית המסמך

    Returns:
        HTML מלא מוכן להורדה
    """
    css_variables = generate_css_variables(theme.get("variables", {}))
    # 🔒 XSS Protection - sanitize CSS before rendering
    syntax_css = sanitize_css(theme.get("syntax_css", ""))

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
    )

