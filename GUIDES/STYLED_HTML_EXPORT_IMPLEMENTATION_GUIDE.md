# 🎨 מדריך מימוש: ייצוא HTML מעוצב ממארקדאון

## 📋 סקירה כללית

פיצ'ר זה מאפשר למשתמש לייצא קבצי Markdown כקבצי HTML מעוצבים להורדה, עם אפשרות לבחור ערכת עיצוב.

### התהליך:
1. המשתמש לוחץ על כפתור "ייצוא HTML מעוצב" (בעמוד צפייה בקובץ Markdown)
2. נפתח מודאל לבחירת ערכת עיצוב
3. המשתמש בוחר ערכה מ:
   - 🎨 **Presets מוכנים** (Technical Dark, GitHub Light, וכו')
   - 🖼️ **הגלריה שלו** (ערכות שייבא/יצר בעבר)
   - 📁 **העלאת VS Code JSON** (בזמן אמת)
4. תצוגה מקדימה אופציונלית
5. השרת ממיר Markdown → HTML, מזריק לתבנית עם CSS Variables, ושולח להורדה

---

## 🏗️ ארכיטקטורה

```
┌─────────────────────────────────────────────────────────────────────┐
│                           Frontend                                   │
├─────────────────────────────────────────────────────────────────────┤
│  view_file.html                                                      │
│  ├─ כפתור "📥 ייצוא HTML מעוצב" (רק לקבצי Markdown)                │
│  └─ מודאל בחירת ערכה (export_theme_modal.html)                      │
│      ├─ Tab 1: Presets מוכנים                                       │
│      ├─ Tab 2: הערכות שלי (מ-DB)                                    │
│      └─ Tab 3: ייבוא VS Code JSON                                   │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                           Backend                                    │
├─────────────────────────────────────────────────────────────────────┤
│  webapp/app.py                                                       │
│  ├─ GET  /export/styled/<file_id>?theme=<theme_id>                  │
│  │       → הורדת HTML מעוצב                                         │
│  ├─ POST /api/export/preview                                         │
│  │       → תצוגה מקדימה (HTML string)                               │
│  └─ POST /api/export/parse-vscode                                    │
│          → פרסור VS Code JSON → CSS Variables                       │
│                                                                      │
│  services/styled_export_service.py (חדש)                            │
│  ├─ preprocess_markdown()  ← המרת ::: alerts                        │
│  ├─ render_styled_html()   ← הזרקה לתבנית                           │
│  └─ get_export_theme()     ← שליפת ערכה לפי ID                      │
│                                                                      │
│  services/theme_parser_service.py (קיים)                            │
│  └─ parse_vscode_theme()   ← כבר ממומש! ✅                          │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                           Templates                                  │
├─────────────────────────────────────────────────────────────────────┤
│  webapp/templates/export/                                            │
│  ├─ styled_document.html   ← תבנית HTML עם CSS Variables            │
│  └─ export_modal.html      ← מודאל בחירת ערכה (partial)             │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 📁 מבנה קבצים חדשים

```
webapp/
├── templates/
│   └── export/
│       ├── styled_document.html      # תבנית ה-HTML המיוצא
│       └── export_modal.html         # מודאל בחירת ערכה (include)
├── static/
│   ├── css/
│   │   └── export-modal.css          # עיצוב המודאל
│   └── js/
│       └── export-modal.js           # לוגיקת המודאל
services/
└── styled_export_service.py          # שירות הייצוא
```

---

## 🔧 שלב 1: שירות הייצוא (Backend)

### `services/styled_export_service.py`

```python
"""
Styled HTML Export Service
ייצוא קבצי Markdown כ-HTML מעוצב עם ערכות נושא
"""

from __future__ import annotations

import re
import logging
from typing import Optional

import markdown
from flask import render_template

from services.theme_parser_service import (
    parse_vscode_theme,
    FALLBACK_DARK,
    FALLBACK_LIGHT,
)
from services.theme_presets_service import get_preset_by_id, list_presets

logger = logging.getLogger(__name__)


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
    pattern = r":::\s?(info|warning|danger|success|tip)\s?(.*?):::"
    
    def replacer(match):
        alert_type = match.group(1).lower()
        content = match.group(2).strip()
        
        # מיפוי סוגים ל-CSS classes
        type_map = {
            'tip': 'success',
            'info': 'info', 
            'warning': 'warning',
            'danger': 'danger',
            'success': 'success'
        }
        css_class = type_map.get(alert_type, 'info')
        
        # המרת תוכן פנימי ל-HTML (תומך ב-Markdown בתוך alerts)
        inner_html = markdown.markdown(content, extensions=['nl2br'])
        
        return f'<div class="alert alert-{css_class}">{inner_html}</div>'
    
    # DOTALL כדי לתפוס תוכן מרובה שורות
    return re.sub(pattern, replacer, text, flags=re.DOTALL)


def markdown_to_html(text: str) -> str:
    """
    המרת Markdown ל-HTML עם extensions מתאימים.
    """
    if not text:
        return ""
    
    # עיבוד מקדים
    processed = preprocess_markdown(text)
    
    # המרה ל-HTML
    html = markdown.markdown(
        processed,
        extensions=[
            'fenced_code',      # ```code blocks```
            'tables',           # טבלאות GFM
            'nl2br',            # שורות חדשות → <br>
            'toc',              # תוכן עניינים (אופציונלי)
            'codehilite',       # הדגשת קוד (עם Pygments)
            'attr_list',        # attributes על אלמנטים
        ],
        extension_configs={
            'codehilite': {
                'css_class': 'highlight',
                'linenums': False,
                'guess_lang': True,
            }
        }
    )
    
    return html


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
"""
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
        }
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
        }
    }
}


def get_export_theme(
    theme_id: str,
    user_themes: Optional[list] = None,
    vscode_json: Optional[str] = None
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
            return {
                "name": parsed.get("name", "Imported Theme"),
                "variables": parsed.get("variables", FALLBACK_DARK),
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
    presets = []
    
    # Export Presets מיוחדים
    for preset_id, preset in EXPORT_PRESETS.items():
        presets.append({
            "id": preset_id,
            "name": preset["name"],
            "description": preset.get("description", ""),
            "category": preset.get("category", "dark"),
            "preview_colors": _extract_preview_colors(preset.get("variables", {})),
        })
    
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
        if key.startswith("--") and value:
            lines.append(f"    {key}: {value};")
    
    return "\n".join(lines)


def render_styled_html(
    content_html: str,
    title: str,
    theme: dict,
    include_toc: bool = False,
    footer_text: str = "נוצר אוטומטית ע\"י Code Keeper Bot"
) -> str:
    """
    מרנדר HTML מעוצב מלא.
    
    Args:
        content_html: תוכן ה-HTML (אחרי המרה מ-Markdown)
        title: כותרת המסמך
        theme: ערכת הנושא (name, variables, syntax_css)
        include_toc: האם לכלול תוכן עניינים
        footer_text: טקסט בתחתית המסמך
    
    Returns:
        HTML מלא מוכן להורדה
    """
    css_variables = generate_css_variables(theme.get("variables", {}))
    syntax_css = theme.get("syntax_css", "")
    
    return render_template(
        "export/styled_document.html",
        title=title,
        content=content_html,
        css_variables=css_variables,
        syntax_css=syntax_css,
        theme_name=theme.get("name", "Custom"),
        include_toc=include_toc,
        footer_text=footer_text,
    )
```

---

## 🎨 שלב 2: תבנית HTML מעוצבת

### `webapp/templates/export/styled_document.html`

```html
<!DOCTYPE html>
<html dir="rtl" lang="he">
<head>
    <meta charset="UTF-8">
    <title>{{ title }}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="generator" content="Code Keeper Bot">
    <meta name="theme-name" content="{{ theme_name }}">
    <style>
        /* ============================================
         * CSS Variables (מוזרקים מערכת הנושא)
         * ============================================ */
        :root {
{{ css_variables }}
        }

        /* ============================================
         * Base Styles
         * ============================================ */
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: 'Segoe UI', Tahoma, Arial, sans-serif;
            background: linear-gradient(135deg, var(--bg-primary) 0%, var(--bg-tertiary, var(--bg-primary)) 100%);
            color: var(--text-primary);
            line-height: 1.8;
            min-height: 100vh;
        }

        /* ============================================
         * Header
         * ============================================ */
        header {
            text-align: center;
            padding: 60px 20px;
            background: linear-gradient(135deg, var(--primary) 0%, var(--primary-hover, var(--primary)) 100%);
            margin-bottom: 40px;
            border-radius: 0 0 30px 30px;
            box-shadow: 0 10px 40px var(--shadow-color, rgba(0, 0, 0, 0.3));
        }

        header h1 {
            font-size: 2.5em;
            margin: 0 0 0.5rem;
            color: #ffffff;
            text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.3);
        }

        header .subtitle {
            color: rgba(255, 255, 255, 0.85);
            font-size: 1rem;
        }

        /* ============================================
         * Content Container
         * ============================================ */
        .container {
            max-width: 900px;
            margin: 0 auto;
            padding: 0 20px 60px 20px;
        }

        /* ============================================
         * Typography
         * ============================================ */
        h2 {
            color: var(--primary);
            border-bottom: 3px solid var(--primary);
            padding-bottom: 10px;
            margin-top: 2.5rem;
            margin-bottom: 1rem;
            font-size: 1.75em;
        }

        h3 {
            color: var(--secondary, var(--primary));
            margin-top: 2rem;
            margin-bottom: 0.75rem;
            font-size: 1.35em;
        }

        h4 {
            color: var(--text-primary);
            margin-top: 1.5rem;
            margin-bottom: 0.5rem;
            font-size: 1.15em;
        }

        p {
            margin-bottom: 1rem;
            text-align: justify;
        }

        a {
            color: var(--link-color, var(--primary));
            text-decoration: none;
            font-weight: 500;
            transition: color 0.2s ease;
        }

        a:hover {
            text-decoration: underline;
            color: var(--primary-hover, var(--primary));
        }

        /* ============================================
         * Lists
         * ============================================ */
        ul, ol {
            margin: 1rem 0;
            padding-right: 2rem;
        }

        li {
            margin-bottom: 0.5rem;
        }

        /* ============================================
         * Tables
         * ============================================ */
        table {
            width: 100%;
            border-collapse: collapse;
            background: var(--card-bg, var(--bg-secondary));
            border-radius: 10px;
            overflow: hidden;
            margin: 1.5rem 0;
            box-shadow: 0 4px 15px var(--shadow-color, rgba(0, 0, 0, 0.1));
        }

        th, td {
            padding: 15px;
            border-bottom: 1px solid var(--border-color);
            text-align: right;
        }

        th {
            background: var(--primary);
            color: #ffffff;
            font-weight: 600;
        }

        tr:last-child td {
            border-bottom: none;
        }

        tr:hover td {
            background: var(--bg-tertiary, rgba(255, 255, 255, 0.02));
        }

        /* ============================================
         * Code Blocks
         * ============================================ */
        pre {
            position: relative; /* מאפשר הצמדת כפתור Copy לפינה */
            background: var(--code-bg, #1e1e1e);
            padding: 20px;
            padding-top: 2.5rem; /* מקום לכפתור */
            border-radius: 10px;
            overflow-x: auto;
            border: 1px solid var(--code-border, var(--border-color));
            margin: 1.5rem 0;
            direction: ltr;
            text-align: left;
        }

        code {
            font-family: 'Consolas', 'Fira Code', 'Monaco', monospace;
            color: var(--code-text, #d4d4d4);
            font-size: 0.9em;
        }

        /* Inline code */
        p code, li code, td code {
            background: var(--code-bg, rgba(0, 0, 0, 0.1));
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 0.85em;
        }

        /* ============================================
         * Copy Button
         * ============================================ */
        .copy-btn {
            position: absolute;
            top: 8px;
            left: 8px; /* בשמאל כי הקוד הוא LTR */
            background: var(--copy-btn-bg, rgba(255, 255, 255, 0.1));
            border: 1px solid var(--border-color);
            color: var(--text-primary);
            padding: 6px 10px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.85em;
            transition: all 0.2s ease;
            opacity: 0;
            display: flex;
            align-items: center;
            gap: 4px;
        }

        pre:hover .copy-btn,
        pre:focus-within .copy-btn {
            opacity: 1;
        }

        .copy-btn:hover {
            background: var(--copy-btn-hover-bg, var(--primary));
            border-color: var(--primary);
            color: #ffffff;
        }

        .copy-btn.success {
            background: var(--copy-btn-success-bg, var(--success));
            border-color: var(--success);
            color: #ffffff;
        }

        /* תמיד מוצג במובייל (אין hover) */
        @media (max-width: 768px) {
            .copy-btn {
                opacity: 1;
            }
        }

        /* ============================================
         * Alerts (Custom Conversion from :::)
         * ============================================ */
        .alert {
            padding: 1rem 1.25rem;
            border-radius: 10px;
            margin: 1.5rem 0;
            border-right: 5px solid;
            background: rgba(255, 255, 255, 0.03);
        }

        .alert p:last-child {
            margin-bottom: 0;
        }

        .alert-info {
            border-color: var(--alert-info-border, var(--primary));
            background: rgba(var(--primary), 0.05);
        }

        .alert-warning {
            border-color: var(--alert-warning-border, var(--warning));
            background: rgba(243, 156, 18, 0.08);
        }

        .alert-success {
            border-color: var(--alert-success-border, var(--success));
            background: rgba(46, 204, 113, 0.08);
        }

        .alert-danger {
            border-color: var(--alert-danger-border, var(--error));
            background: rgba(231, 76, 60, 0.08);
        }

        /* ============================================
         * Blockquotes
         * ============================================ */
        blockquote {
            border-right: 4px solid var(--primary);
            padding: 1rem 1.5rem;
            margin: 1.5rem 0;
            background: var(--bg-secondary, rgba(255, 255, 255, 0.02));
            border-radius: 0 10px 10px 0;
            font-style: italic;
            color: var(--text-secondary);
        }

        blockquote p:last-child {
            margin-bottom: 0;
        }

        /* ============================================
         * Images
         * ============================================ */
        img {
            max-width: 100%;
            height: auto;
            border-radius: 10px;
            margin: 1rem 0;
            box-shadow: 0 4px 15px var(--shadow-color, rgba(0, 0, 0, 0.2));
        }

        /* ============================================
         * Horizontal Rule
         * ============================================ */
        hr {
            border: none;
            height: 2px;
            background: linear-gradient(90deg, transparent, var(--border-color), transparent);
            margin: 2.5rem 0;
        }

        /* ============================================
         * Footer
         * ============================================ */
        footer {
            text-align: center;
            padding: 2rem;
            margin-top: 3rem;
            border-top: 1px solid var(--border-color);
            color: var(--text-muted);
            font-size: 0.9rem;
        }

        /* ============================================
         * Table of Contents (אופציונלי)
         * ============================================ */
        .toc {
            background: var(--card-bg, var(--bg-secondary));
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 1.5rem;
            margin-bottom: 2rem;
        }

        .toc h2 {
            margin-top: 0;
            font-size: 1.25em;
            border-bottom: none;
        }

        .toc ul {
            list-style: none;
            padding-right: 0;
        }

        .toc li {
            margin-bottom: 0.5rem;
        }

        .toc a {
            color: var(--text-secondary);
        }

        /* ============================================
         * Responsive
         * ============================================ */
        @media (max-width: 768px) {
            header {
                padding: 40px 15px;
            }

            header h1 {
                font-size: 1.75em;
            }

            .container {
                padding: 0 15px 40px;
            }

            h2 {
                font-size: 1.5em;
            }

            pre {
                padding: 15px;
                font-size: 0.85em;
            }
        }

        /* ============================================
         * Print Styles
         * ============================================ */
        @media print {
            body {
                background: white;
                color: black;
            }

            header {
                background: var(--primary);
                border-radius: 0;
            }

            pre {
                border: 1px solid #ddd;
                background: #f5f5f5;
            }

            code {
                color: #333;
            }
        }
    </style>
    {% if syntax_css %}
    <style>
        /* Syntax Highlighting (מערכת הנושא) */
{{ syntax_css | safe }}
    </style>
    {% endif %}
</head>
<body>
    <header>
        <h1>{{ title }}</h1>
        <p class="subtitle">{{ footer_text }}</p>
    </header>

    <main class="container">
        {% if include_toc %}
        <nav class="toc">
            <h2>📑 תוכן עניינים</h2>
            <!-- TOC יוזרק כאן אם נדרש -->
        </nav>
        {% endif %}

        {{ content | safe }}
    </main>

    <footer>
        <p>{{ footer_text }}</p>
        <p style="margin-top: 0.5rem; font-size: 0.8rem;">
            Theme: {{ theme_name }}
        </p>
    </footer>

    <!-- Copy Button Script -->
    <script>
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
    </script>
</body>
</html>
```

---

## 🌐 שלב 3: Routes (Backend)

### הוספה ל-`webapp/app.py`

```python
# ============================================
# Styled HTML Export Routes
# ============================================

from services.styled_export_service import (
    markdown_to_html,
    get_export_theme,
    list_export_presets,
    render_styled_html,
)
from services.theme_parser_service import parse_vscode_theme, validate_theme_json


@app.route('/export/styled/<file_id>')
@login_required
@traced("export.styled_html")
def export_styled_html(file_id):
    """
    ייצוא קובץ Markdown כ-HTML מעוצב להורדה.
    
    Query params:
        theme: מזהה ערכת הנושא (default: technical-dark)
        preview: אם '1', מחזיר HTML לתצוגה מקדימה במקום להורדה
    """
    db = get_db()
    user_id = session['user_id']
    
    # שליפת הקובץ
    try:
        file, _kind = _get_user_any_file_by_id(db, user_id, file_id)
    except Exception as e:
        logger.exception("DB error fetching file for export", extra={"file_id": file_id})
        abort(500)
    
    if not file:
        abort(404)
    
    # וידוא שזה קובץ Markdown
    language = (file.get('programming_language') or '').lower()
    file_name = file.get('file_name', '')
    is_markdown = language == 'markdown' or file_name.lower().endswith(('.md', '.markdown'))
    
    if not is_markdown:
        flash('ייצוא HTML מעוצב זמין רק לקבצי Markdown', 'warning')
        return redirect(url_for('view_file', file_id=file_id))
    
    # שליפת ערכת הנושא
    theme_id = request.args.get('theme', 'tech-guide-dark')
    
    # שליפת ערכות המשתמש (אם בחר ערכה אישית)
    user_data = db.users.find_one({"user_id": int(user_id)}, {"custom_themes": 1})
    user_themes = user_data.get("custom_themes", []) if user_data else []
    
    theme = get_export_theme(theme_id, user_themes=user_themes)
    
    # המרת Markdown ל-HTML
    raw_content = file.get('code') or file.get('content') or ''
    html_content = markdown_to_html(raw_content)
    
    # רינדור HTML מלא
    title = file.get('file_name', 'Untitled').replace('.md', '').replace('.markdown', '')
    rendered_html = render_styled_html(
        content_html=html_content,
        title=title,
        theme=theme,
    )
    
    # תצוגה מקדימה או הורדה
    is_preview = request.args.get('preview') == '1'
    
    if is_preview:
        return rendered_html
    
    # הורדה
    response = make_response(rendered_html)
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    
    safe_filename = re.sub(r'[^\w\s\-.]', '', title)[:50] or 'document'
    response.headers['Content-Disposition'] = f'attachment; filename="{safe_filename}.html"'
    
    return response


@app.route('/api/export/themes')
@login_required
def api_export_themes():
    """
    מחזיר רשימת ערכות נושא זמינות לייצוא.
    
    Returns:
        JSON עם:
        - presets: ערכות מוכנות מראש
        - user_themes: ערכות המשתמש
    """
    db = get_db()
    user_id = session['user_id']
    
    # Presets
    presets = list_export_presets()
    
    # ערכות המשתמש
    user_data = db.users.find_one({"user_id": int(user_id)}, {"custom_themes": 1})
    user_themes = []
    
    if user_data and user_data.get("custom_themes"):
        for theme in user_data["custom_themes"]:
            user_themes.append({
                "id": theme.get("id"),
                "name": theme.get("name", "My Theme"),
                "description": theme.get("description", ""),
                "category": "custom",
            })
    
    return jsonify({
        "ok": True,
        "presets": presets,
        "user_themes": user_themes,
    })


@app.route('/api/export/parse-vscode', methods=['POST'])
@login_required
def api_parse_vscode_theme():
    """
    מפרסר JSON של ערכת VS Code ומחזיר CSS Variables.
    
    Body (JSON):
        json_content: תוכן הקובץ JSON
    
    Returns:
        JSON עם name, variables, syntax_css
    """
    data = request.get_json()
    if not data or not data.get('json_content'):
        return jsonify({"ok": False, "error": "Missing json_content"}), 400
    
    json_content = data['json_content']
    
    # וולידציה
    is_valid, error_msg = validate_theme_json(json_content)
    if not is_valid:
        return jsonify({"ok": False, "error": error_msg}), 400
    
    # פרסור
    try:
        parsed = parse_vscode_theme(json_content)
        return jsonify({
            "ok": True,
            "name": parsed.get("name", "VS Code Theme"),
            "type": parsed.get("type", "dark"),
            "variables": parsed.get("variables", {}),
            "syntax_css": parsed.get("syntax_css", ""),
        })
    except Exception as e:
        logger.exception("Failed to parse VS Code theme")
        return jsonify({"ok": False, "error": str(e)}), 400
```

---

## 🖼️ שלב 4: מודאל בחירת ערכה (Frontend)

### `webapp/templates/export/export_modal.html`

```html
{# מודאל בחירת ערכה לייצוא HTML מעוצב #}
{# Usage: {% include 'export/export_modal.html' %} #}

<div id="exportThemeModal" class="export-modal" role="dialog" aria-modal="true" aria-labelledby="exportModalTitle" hidden>
    <div class="export-modal__surface">
        <div class="export-modal__header">
            <h3 id="exportModalTitle">
                <i class="fas fa-file-export"></i>
                ייצוא HTML מעוצב
            </h3>
            <button type="button" class="export-modal__close" data-export-close aria-label="סגור">✕</button>
        </div>

        <div class="export-modal__tabs">
            <button type="button" class="export-tab active" data-tab="presets">
                <i class="fas fa-star"></i>
                ערכות מוכנות
            </button>
            <button type="button" class="export-tab" data-tab="my-themes">
                <i class="fas fa-palette"></i>
                הערכות שלי
            </button>
            <button type="button" class="export-tab" data-tab="import">
                <i class="fas fa-file-import"></i>
                ייבוא VS Code
            </button>
        </div>

        <div class="export-modal__content">
            {# Tab 1: Presets #}
            <div class="export-tab-content active" id="export-presets-tab">
                <div class="export-themes-grid" id="exportPresetsGrid">
                    <div class="export-loading">
                        <i class="fas fa-spinner fa-spin"></i>
                        טוען ערכות...
                    </div>
                </div>
            </div>

            {# Tab 2: My Themes #}
            <div class="export-tab-content" id="export-my-themes-tab">
                <div class="export-themes-grid" id="exportUserThemesGrid">
                    <p class="export-empty">טוען...</p>
                </div>
            </div>

            {# Tab 3: Import VS Code #}
            <div class="export-tab-content" id="export-import-tab">
                <div class="export-import-section">
                    <p class="text-muted">
                        העלה קובץ JSON של ערכת VS Code מ-
                        <a href="https://vscodethemes.com" target="_blank" rel="noopener">vscodethemes.com</a>
                    </p>
                    
                    <div class="export-upload-area" id="exportUploadArea">
                        <i class="fas fa-cloud-upload-alt"></i>
                        <p>גרור קובץ JSON לכאן<br>או לחץ לבחירה</p>
                        <input type="file" id="exportThemeFileInput" accept=".json" hidden>
                    </div>

                    <div class="export-upload-status" id="exportUploadStatus" hidden>
                        <i class="fas fa-check-circle"></i>
                        <span id="exportUploadFileName">theme.json</span>
                    </div>
                </div>
            </div>
        </div>

        <div class="export-modal__footer">
            <div class="export-selected-info">
                <span class="export-selected-label">ערכה נבחרת:</span>
                <strong id="exportSelectedThemeName">Tech Guide Dark</strong>
            </div>
            <div class="export-modal__actions">
                <button type="button" class="btn btn-secondary" data-action="preview">
                    <i class="fas fa-eye"></i>
                    תצוגה מקדימה
                </button>
                <button type="button" class="btn btn-primary" data-action="download">
                    <i class="fas fa-download"></i>
                    הורד HTML
                </button>
            </div>
        </div>
    </div>
</div>
```

### `webapp/static/js/export-modal.js`

```javascript
/**
 * Export Modal - לוגיקת מודאל ייצוא HTML מעוצב
 */
(function () {
    'use strict';

    // State
    let selectedTheme = {
        id: 'tech-guide-dark',
        name: 'Tech Guide Dark',
        source: 'preset', // 'preset' | 'user' | 'vscode'
        vscodeJson: null,  // תוכן JSON אם מקור הוא VS Code
    };
    let fileId = null;
    let presetsLoaded = false;

    // DOM Elements
    const modal = document.getElementById('exportThemeModal');
    if (!modal) return;

    const presetsGrid = document.getElementById('exportPresetsGrid');
    const userThemesGrid = document.getElementById('exportUserThemesGrid');
    const selectedNameEl = document.getElementById('exportSelectedThemeName');
    const uploadArea = document.getElementById('exportUploadArea');
    const uploadStatus = document.getElementById('exportUploadStatus');
    const uploadFileName = document.getElementById('exportUploadFileName');
    const fileInput = document.getElementById('exportThemeFileInput');

    // ============================================
    // Modal Open/Close
    // ============================================

    window.openExportModal = function (fid) {
        fileId = fid;
        modal.hidden = false;
        document.body.style.overflow = 'hidden';
        
        if (!presetsLoaded) {
            loadThemes();
        }
    };

    function closeModal() {
        modal.hidden = true;
        document.body.style.overflow = '';
    }

    // Close handlers
    modal.querySelectorAll('[data-export-close]').forEach(btn => {
        btn.addEventListener('click', closeModal);
    });

    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeModal();
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !modal.hidden) closeModal();
    });

    // ============================================
    // Tabs
    // ============================================

    const tabs = modal.querySelectorAll('.export-tab');
    const tabContents = modal.querySelectorAll('.export-tab-content');

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const targetTab = tab.dataset.tab;

            tabs.forEach(t => t.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));

            tab.classList.add('active');
            document.getElementById(`export-${targetTab}-tab`).classList.add('active');
        });
    });

    // ============================================
    // Load Themes
    // ============================================

    async function loadThemes() {
        try {
            const resp = await fetch('/api/export/themes');
            const data = await resp.json();

            if (!data.ok) throw new Error(data.error || 'Failed to load themes');

            renderPresets(data.presets || []);
            renderUserThemes(data.user_themes || []);
            presetsLoaded = true;
        } catch (err) {
            console.error('Load themes error:', err);
            presetsGrid.innerHTML = '<p class="export-error">שגיאה בטעינת ערכות</p>';
        }
    }

    function renderPresets(presets) {
        if (!presets.length) {
            presetsGrid.innerHTML = '<p class="export-empty">אין ערכות מוכנות</p>';
            return;
        }

        presetsGrid.innerHTML = presets.map(p => `
            <button type="button" 
                    class="export-theme-card ${p.id === selectedTheme.id ? 'selected' : ''}"
                    data-theme-id="${p.id}"
                    data-theme-name="${p.name}"
                    data-source="preset">
                <div class="export-theme-preview">
                    ${(p.preview_colors || []).map(c => `<span style="background:${c}"></span>`).join('')}
                </div>
                <div class="export-theme-info">
                    <strong>${p.name}</strong>
                    <small>${p.description || ''}</small>
                </div>
            </button>
        `).join('');

        bindThemeCards(presetsGrid);
    }

    function renderUserThemes(themes) {
        if (!themes.length) {
            userThemesGrid.innerHTML = `
                <p class="export-empty">
                    אין לך ערכות מותאמות אישית.
                    <a href="/settings/theme-gallery">צור ערכה חדשה</a>
                </p>
            `;
            return;
        }

        userThemesGrid.innerHTML = themes.map(t => `
            <button type="button"
                    class="export-theme-card"
                    data-theme-id="${t.id}"
                    data-theme-name="${t.name}"
                    data-source="user">
                <div class="export-theme-info">
                    <strong>${t.name}</strong>
                    <small>${t.description || 'ערכה מותאמת אישית'}</small>
                </div>
            </button>
        `).join('');

        bindThemeCards(userThemesGrid);
    }

    function bindThemeCards(container) {
        container.querySelectorAll('.export-theme-card').forEach(card => {
            card.addEventListener('click', () => selectTheme(card));
        });
    }

    function selectTheme(card) {
        // Remove previous selection
        modal.querySelectorAll('.export-theme-card.selected').forEach(c => {
            c.classList.remove('selected');
        });

        card.classList.add('selected');

        selectedTheme = {
            id: card.dataset.themeId,
            name: card.dataset.themeName,
            source: card.dataset.source,
            vscodeJson: null,
        };

        selectedNameEl.textContent = selectedTheme.name;
    }

    // ============================================
    // VS Code Import
    // ============================================

    uploadArea.addEventListener('click', () => fileInput.click());

    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.classList.add('dragover');
    });

    uploadArea.addEventListener('dragleave', () => {
        uploadArea.classList.remove('dragover');
    });

    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('dragover');

        const file = e.dataTransfer.files[0];
        if (file) handleFileUpload(file);
    });

    fileInput.addEventListener('change', () => {
        const file = fileInput.files[0];
        if (file) handleFileUpload(file);
    });

    async function handleFileUpload(file) {
        if (!file.name.endsWith('.json')) {
            alert('נא להעלות קובץ JSON');
            return;
        }

        try {
            const content = await file.text();

            // Parse and validate
            const resp = await fetch('/api/export/parse-vscode', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ json_content: content }),
            });

            const data = await resp.json();

            if (!data.ok) {
                alert(`שגיאה בפרסור הערכה: ${data.error}`);
                return;
            }

            // Success - update state
            selectedTheme = {
                id: 'vscode-import',
                name: data.name || file.name.replace('.json', ''),
                source: 'vscode',
                vscodeJson: content,
            };

            selectedNameEl.textContent = selectedTheme.name;
            uploadStatus.hidden = false;
            uploadFileName.textContent = file.name;

            // Visual feedback
            uploadArea.classList.add('success');
            setTimeout(() => uploadArea.classList.remove('success'), 2000);

        } catch (err) {
            console.error('File upload error:', err);
            alert('שגיאה בקריאת הקובץ');
        }
    }

    // ============================================
    // Actions: Preview & Download
    // ============================================

    modal.querySelector('[data-action="preview"]').addEventListener('click', async () => {
        const url = buildExportUrl(true);
        window.open(url, '_blank');
    });

    modal.querySelector('[data-action="download"]').addEventListener('click', async () => {
        if (selectedTheme.source === 'vscode' && selectedTheme.vscodeJson) {
            // VS Code theme - need to POST the JSON
            await downloadWithVscodeTheme();
        } else {
            // Preset or user theme - simple GET
            const url = buildExportUrl(false);
            window.location.href = url;
        }
        
        closeModal();
    });

    function buildExportUrl(isPreview) {
        let url = `/export/styled/${fileId}?theme=${encodeURIComponent(selectedTheme.id)}`;
        if (isPreview) url += '&preview=1';
        return url;
    }

    async function downloadWithVscodeTheme() {
        // For VS Code themes, we need to send the JSON content
        // Create a form and submit it
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = `/export/styled/${fileId}`;
        form.style.display = 'none';

        const jsonInput = document.createElement('input');
        jsonInput.type = 'hidden';
        jsonInput.name = 'vscode_json';
        jsonInput.value = selectedTheme.vscodeJson;
        form.appendChild(jsonInput);

        document.body.appendChild(form);
        form.submit();
        document.body.removeChild(form);
    }

})();
```

---

## 🔘 שלב 5: הוספת כפתור לממשק

### עדכון `view_file.html`

הוסף את הכפתור בתוך `file-actions__list` (רק לקבצי Markdown):

```html
{% if file.language|lower == 'markdown' or (file.file_name|lower).endswith('.md') %}
<button type="button" 
        class="btn btn-secondary btn-icon"
        data-overflow-id="export-styled"
        data-overflow-priority="5"
        data-menu-label="📥 HTML מעוצב"
        onclick="openExportModal('{{ file.id }}')"
        title="ייצוא HTML מעוצב">
    <i class="fas fa-file-export"></i>
    <span class="btn-text">HTML מעוצב</span>
</button>
{% endif %}
```

בסוף הקובץ, לפני `{% endblock %}`:

```html
{% if file.language|lower == 'markdown' or (file.file_name|lower).endswith('.md') %}
{% include 'export/export_modal.html' %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/export-modal.css') }}?v={{ static_version }}">
<script src="{{ url_for('static', filename='js/export-modal.js') }}?v={{ static_version }}" defer></script>
{% endif %}
```

---

## 🎨 שלב 6: CSS למודאל

### `webapp/static/css/export-modal.css`

```css
/* ============================================
 * Export Modal Styles
 * ============================================ */

.export-modal {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.7);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 10000;
    padding: 1rem;
    backdrop-filter: blur(4px);
}

.export-modal[hidden] {
    display: none;
}

.export-modal__surface {
    background: var(--card-bg, #1f2a44);
    border: 1px solid var(--border-color, rgba(255, 255, 255, 0.1));
    border-radius: 16px;
    width: min(600px, 100%);
    max-height: 85vh;
    display: flex;
    flex-direction: column;
    box-shadow: 0 25px 50px rgba(0, 0, 0, 0.5);
}

.export-modal__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 1.25rem 1.5rem;
    border-bottom: 1px solid var(--border-color);
}

.export-modal__header h3 {
    margin: 0;
    font-size: 1.25rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.export-modal__close {
    background: transparent;
    border: none;
    color: var(--text-muted);
    font-size: 1.25rem;
    cursor: pointer;
    padding: 0.5rem;
    border-radius: 8px;
    transition: all 0.2s;
}

.export-modal__close:hover {
    background: rgba(255, 255, 255, 0.1);
    color: var(--text-primary);
}

/* Tabs */
.export-modal__tabs {
    display: flex;
    gap: 0;
    padding: 0 1rem;
    border-bottom: 1px solid var(--border-color);
}

.export-tab {
    background: transparent;
    border: none;
    color: var(--text-secondary);
    padding: 1rem 1.25rem;
    font-size: 0.95rem;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    border-bottom: 2px solid transparent;
    transition: all 0.2s;
}

.export-tab:hover {
    color: var(--text-primary);
    background: rgba(255, 255, 255, 0.05);
}

.export-tab.active {
    color: var(--primary);
    border-bottom-color: var(--primary);
}

/* Content */
.export-modal__content {
    flex: 1;
    overflow-y: auto;
    padding: 1.5rem;
}

.export-tab-content {
    display: none;
}

.export-tab-content.active {
    display: block;
}

/* Themes Grid */
.export-themes-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 1rem;
}

.export-theme-card {
    background: var(--bg-secondary, rgba(255, 255, 255, 0.05));
    border: 2px solid transparent;
    border-radius: 12px;
    padding: 0.75rem;
    cursor: pointer;
    text-align: right;
    transition: all 0.2s;
}

.export-theme-card:hover {
    background: var(--bg-tertiary, rgba(255, 255, 255, 0.08));
    border-color: var(--border-color);
}

.export-theme-card.selected {
    border-color: var(--primary);
    background: var(--primary-light, rgba(0, 136, 204, 0.15));
}

.export-theme-preview {
    display: flex;
    gap: 4px;
    margin-bottom: 0.75rem;
    height: 24px;
    border-radius: 6px;
    overflow: hidden;
}

.export-theme-preview span {
    flex: 1;
}

.export-theme-info strong {
    display: block;
    font-size: 0.9rem;
    margin-bottom: 0.25rem;
}

.export-theme-info small {
    color: var(--text-muted);
    font-size: 0.8rem;
    display: block;
    line-height: 1.3;
}

/* Upload Area */
.export-upload-area {
    border: 2px dashed var(--border-color);
    border-radius: 12px;
    padding: 2rem;
    text-align: center;
    cursor: pointer;
    transition: all 0.2s;
}

.export-upload-area:hover,
.export-upload-area.dragover {
    border-color: var(--primary);
    background: var(--primary-light, rgba(0, 136, 204, 0.1));
}

.export-upload-area.success {
    border-color: var(--success);
    background: rgba(46, 204, 113, 0.1);
}

.export-upload-area i {
    font-size: 2.5rem;
    color: var(--text-muted);
    margin-bottom: 1rem;
}

.export-upload-status {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 1rem;
    background: rgba(46, 204, 113, 0.1);
    border-radius: 8px;
    margin-top: 1rem;
    color: var(--success);
}

/* Footer */
.export-modal__footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 1rem 1.5rem;
    border-top: 1px solid var(--border-color);
    gap: 1rem;
    flex-wrap: wrap;
}

.export-selected-info {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    color: var(--text-secondary);
    font-size: 0.9rem;
}

.export-modal__actions {
    display: flex;
    gap: 0.75rem;
}

/* Utilities */
.export-loading,
.export-empty,
.export-error {
    text-align: center;
    padding: 2rem;
    color: var(--text-muted);
}

.export-error {
    color: var(--error);
}

/* Responsive */
@media (max-width: 600px) {
    .export-modal__surface {
        max-height: 95vh;
    }

    .export-themes-grid {
        grid-template-columns: 1fr 1fr;
    }

    .export-modal__footer {
        flex-direction: column;
        align-items: stretch;
    }

    .export-modal__actions {
        justify-content: stretch;
    }

    .export-modal__actions .btn {
        flex: 1;
    }
}
```

---

## ✅ צ'קליסט מימוש

- [ ] **שלב 1**: יצירת `services/styled_export_service.py`
- [ ] **שלב 2**: יצירת `webapp/templates/export/styled_document.html`
- [ ] **שלב 3**: הוספת Routes ל-`webapp/app.py`
- [ ] **שלב 4**: יצירת `webapp/templates/export/export_modal.html`
- [ ] **שלב 5**: יצירת `webapp/static/js/export-modal.js`
- [ ] **שלב 6**: יצירת `webapp/static/css/export-modal.css`
- [ ] **שלב 7**: עדכון `view_file.html` עם הכפתור וה-include
- [ ] **שלב 8**: טסטים
- [ ] **שלב 9**: תיעוד

---

## 🧪 טסטים מומלצים

```python
# tests/test_styled_export.py

import pytest
from services.styled_export_service import (
    preprocess_markdown,
    markdown_to_html,
    get_export_theme,
)


class TestPreprocessMarkdown:
    def test_converts_info_alert(self):
        text = "::: info\nזו הודעת מידע\n:::"
        result = preprocess_markdown(text)
        assert 'class="alert alert-info"' in result
        assert 'זו הודעת מידע' in result

    def test_converts_warning_alert(self):
        text = "::: warning\nזהירות!\n:::"
        result = preprocess_markdown(text)
        assert 'class="alert alert-warning"' in result

    def test_converts_tip_to_success(self):
        text = "::: tip\nטיפ שימושי\n:::"
        result = preprocess_markdown(text)
        assert 'class="alert alert-success"' in result

    def test_handles_multiline_content(self):
        text = "::: info\nשורה 1\nשורה 2\n:::"
        result = preprocess_markdown(text)
        assert 'שורה 1' in result
        assert 'שורה 2' in result


class TestGetExportTheme:
    def test_returns_builtin_preset(self):
        theme = get_export_theme("tech-guide-dark")
        assert theme["name"] == "Tech Guide Dark"
        assert "--bg-primary" in theme["variables"]
        assert theme["variables"]["--bg-primary"] == "#0f0f23"

    def test_returns_gallery_preset(self):
        theme = get_export_theme("github-dark")
        assert "GitHub" in theme["name"]

    def test_fallback_to_default(self):
        theme = get_export_theme("nonexistent-theme")
        assert theme["name"] == "Tech Guide Dark"
    
    def test_syntax_css_included(self):
        theme = get_export_theme("tech-guide-dark")
        assert theme.get("syntax_css")
        assert ".highlight .k" in theme["syntax_css"]  # Keywords
```

---

## 📝 הערות נוספות

### התאמה לעיצוב ה-HTML מהאפיון

העיצוב ב-`styled_document.html` כבר מותאם לאפיון שבתיאור ה-PR, עם שינויים קלים:

1. **CSS Variables במקום ערכים קשיחים** - מאפשר החלפת ערכה
2. **תמיכה ב-Alerts מרובי שורות** - עם Markdown פנימי
3. **Print Styles** - להדפסה נכונה
4. **Responsive Design** - מותאם למובייל

### שיפורים עתידיים אפשריים

1. **תצוגה מקדימה בזמן אמת** - רינדור AJAX במודאל
2. **שמירת ערכה מועדפת** - per-user default
3. **ייצוא PDF** - עם wkhtmltopdf / Playwright
4. **תבניות נוספות** - Resume, Presentation, Newsletter

---

## 🎨 נספח: ערכת Tech Guide Dark (VS Code JSON)

ערכת הנושא המקורית בפורמט VS Code, לשימוש בייבוא או כגיבוי:

<details>
<summary>לחץ לצפייה בקובץ JSON המלא</summary>

```json
{
    "$schema": "vscode://schemas/color-theme",
    "name": "Tech Guide Dark",
    "type": "dark",
    "colors": {
        "editor.background": "#0f0f23",
        "editor.foreground": "#c3cee3",
        "editorCursor.foreground": "#0088cc",
        "editor.lineHighlightBackground": "#16213e",
        "editor.selectionBackground": "#3d5a8066",
        "editor.findMatchBackground": "#f39c1266",
        "editor.findMatchHighlightBackground": "#f39c1244",
        "editorLineNumber.foreground": "#3d5a80",
        "editorLineNumber.activeForeground": "#0088cc",
        "editorGutter.background": "#1a1a2e",
        "editorBracketMatch.border": "#0088cc",
        "editorBracketMatch.background": "#0088cc33",
        "editorIndentGuide.background": "#3d5a8044",
        "editorIndentGuide.activeBackground": "#0088cc",
        "sideBar.background": "#16213e",
        "sideBar.foreground": "#c3cee3",
        "sideBar.border": "#3d5a80",
        "sideBarTitle.foreground": "#eeeeee",
        "activityBar.background": "#1a1a2e",
        "activityBar.foreground": "#0088cc",
        "activityBar.border": "#3d5a80",
        "activityBarBadge.background": "#0088cc",
        "activityBarBadge.foreground": "#ffffff",
        "statusBar.background": "#0088cc",
        "statusBar.foreground": "#ffffff",
        "statusBar.border": "#005577",
        "titleBar.activeBackground": "#1a1a2e",
        "titleBar.activeForeground": "#eeeeee",
        "titleBar.inactiveBackground": "#0f0f23",
        "titleBar.inactiveForeground": "#c3cee3",
        "tab.activeBackground": "#16213e",
        "tab.activeForeground": "#eeeeee",
        "tab.inactiveBackground": "#1a1a2e",
        "tab.inactiveForeground": "#c3cee3",
        "tab.border": "#3d5a80",
        "tab.activeBorderTop": "#0088cc",
        "panel.background": "#16213e",
        "panel.border": "#3d5a80",
        "terminal.background": "#0f0f23",
        "terminal.foreground": "#c3cee3",
        "terminal.ansiBlack": "#0f0f23",
        "terminal.ansiRed": "#e74c3c",
        "terminal.ansiGreen": "#2ecc71",
        "terminal.ansiYellow": "#f39c12",
        "terminal.ansiBlue": "#0088cc",
        "terminal.ansiMagenta": "#9b59b6",
        "terminal.ansiCyan": "#7fdbca",
        "terminal.ansiWhite": "#eeeeee",
        "terminal.ansiBrightBlack": "#3d5a80",
        "terminal.ansiBrightRed": "#e74c3c",
        "terminal.ansiBrightGreen": "#2ecc71",
        "terminal.ansiBrightYellow": "#f39c12",
        "terminal.ansiBrightBlue": "#0088cc",
        "terminal.ansiBrightMagenta": "#c586c0",
        "terminal.ansiBrightCyan": "#9cdcfe",
        "terminal.ansiBrightWhite": "#ffffff",
        "input.background": "#0f0f23",
        "input.foreground": "#eeeeee",
        "input.border": "#3d5a80",
        "input.placeholderForeground": "#3d5a80",
        "dropdown.background": "#16213e",
        "dropdown.foreground": "#eeeeee",
        "dropdown.border": "#3d5a80",
        "button.background": "#0088cc",
        "button.foreground": "#ffffff",
        "button.hoverBackground": "#0099dd",
        "badge.background": "#0088cc",
        "badge.foreground": "#ffffff",
        "scrollbar.shadow": "#00000066",
        "scrollbarSlider.background": "#3d5a8066",
        "scrollbarSlider.hoverBackground": "#3d5a8099",
        "scrollbarSlider.activeBackground": "#0088cc",
        "list.activeSelectionBackground": "#0088cc",
        "list.activeSelectionForeground": "#ffffff",
        "list.inactiveSelectionBackground": "#16213e",
        "list.hoverBackground": "#16213e",
        "list.focusBackground": "#0088cc44",
        "gitDecoration.addedResourceForeground": "#2ecc71",
        "gitDecoration.modifiedResourceForeground": "#f39c12",
        "gitDecoration.deletedResourceForeground": "#e74c3c",
        "gitDecoration.untrackedResourceForeground": "#9b59b6",
        "gitDecoration.ignoredResourceForeground": "#3d5a80",
        "editorError.foreground": "#e74c3c",
        "editorWarning.foreground": "#f39c12",
        "editorInfo.foreground": "#0088cc"
    },
    "tokenColors": [
        {
            "name": "Comment",
            "scope": ["comment", "punctuation.definition.comment"],
            "settings": { "foreground": "#6a9955", "fontStyle": "italic" }
        },
        {
            "name": "Keyword",
            "scope": ["keyword", "keyword.control", "keyword.operator.new", "keyword.operator.expression", "keyword.operator.cast", "keyword.operator.sizeof", "keyword.operator.instanceof"],
            "settings": { "foreground": "#c586c0" }
        },
        {
            "name": "Storage",
            "scope": ["storage", "storage.type", "storage.modifier"],
            "settings": { "foreground": "#c586c0" }
        },
        {
            "name": "String",
            "scope": ["string", "string.quoted", "string.template"],
            "settings": { "foreground": "#ce9178" }
        },
        {
            "name": "Number",
            "scope": ["constant.numeric", "constant.numeric.integer", "constant.numeric.float", "constant.numeric.hex"],
            "settings": { "foreground": "#b5cea8" }
        },
        {
            "name": "Constant",
            "scope": ["constant", "constant.language", "constant.character", "constant.other"],
            "settings": { "foreground": "#b5cea8" }
        },
        {
            "name": "Variable",
            "scope": ["variable", "variable.other", "variable.language"],
            "settings": { "foreground": "#9cdcfe" }
        },
        {
            "name": "Parameter",
            "scope": ["variable.parameter", "meta.function.parameters"],
            "settings": { "foreground": "#9cdcfe", "fontStyle": "italic" }
        },
        {
            "name": "Function",
            "scope": ["entity.name.function", "meta.function-call", "support.function"],
            "settings": { "foreground": "#dcdcaa" }
        },
        {
            "name": "Class",
            "scope": ["entity.name.class", "entity.name.type.class", "support.class"],
            "settings": { "foreground": "#4ec9b0" }
        },
        {
            "name": "Type",
            "scope": ["entity.name.type", "support.type", "support.type.primitive"],
            "settings": { "foreground": "#4ec9b0" }
        },
        {
            "name": "Operator",
            "scope": ["keyword.operator", "keyword.operator.arithmetic", "keyword.operator.comparison", "keyword.operator.logical"],
            "settings": { "foreground": "#d4d4d4" }
        },
        {
            "name": "Punctuation",
            "scope": ["punctuation", "punctuation.definition", "punctuation.separator", "punctuation.terminator"],
            "settings": { "foreground": "#d4d4d4" }
        },
        {
            "name": "HTML/XML Tag",
            "scope": ["entity.name.tag", "meta.tag"],
            "settings": { "foreground": "#569cd6" }
        },
        {
            "name": "HTML/XML Attribute",
            "scope": ["entity.other.attribute-name"],
            "settings": { "foreground": "#9cdcfe" }
        },
        {
            "name": "Regex",
            "scope": ["string.regexp"],
            "settings": { "foreground": "#d16969" }
        },
        {
            "name": "Escape Character",
            "scope": ["constant.character.escape"],
            "settings": { "foreground": "#d7ba7d" }
        },
        {
            "name": "Invalid",
            "scope": ["invalid", "invalid.illegal"],
            "settings": { "foreground": "#f44747", "fontStyle": "underline" }
        },
        {
            "name": "JSON Key",
            "scope": ["support.type.property-name.json"],
            "settings": { "foreground": "#9cdcfe" }
        },
        {
            "name": "Markdown Heading",
            "scope": ["markup.heading", "entity.name.section.markdown"],
            "settings": { "foreground": "#0088cc", "fontStyle": "bold" }
        },
        {
            "name": "Markdown Bold",
            "scope": ["markup.bold"],
            "settings": { "foreground": "#dcdcaa", "fontStyle": "bold" }
        },
        {
            "name": "Markdown Italic",
            "scope": ["markup.italic"],
            "settings": { "fontStyle": "italic" }
        },
        {
            "name": "Markdown Link",
            "scope": ["markup.underline.link"],
            "settings": { "foreground": "#0088cc" }
        },
        {
            "name": "Markdown Code",
            "scope": ["markup.inline.raw", "markup.fenced_code"],
            "settings": { "foreground": "#7fdbca" }
        }
    ]
}
```

</details>

ניתן לשמור קובץ זה כ-`tech-guide-dark.json` ולייבא אותו ישירות מתוך המודאל.
