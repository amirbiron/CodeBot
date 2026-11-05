"""העורך הציבורי (``/markdown-editor``): עורך Markdown ותצוגה חיה, בלי התחברות, לגולשים שמגיעים מחיפוש.

כאן רק הנתונים שהעמוד נשען עליהם; הראוט הוא ``markdown_editor`` ב-``webapp/app.py``, והתבנית
``webapp/templates/markdown_editor.html``.

- **טקסט ההדגמה** — ``markdown_editor_demo.md`` שליד הקובץ הזה. העורך מציג אותו בכניסה הראשונה, ו"טען דוגמה"
  מחזיר אותו. הוא עותק של המסמך ``CodeKeeper_Markdown.md`` ב-CodeKeeper, בלי הכותרות H5 ו-H6 (התצוגה החיה לא
  מרנדרת אותן — ``DOCUMENT_MAX_LEVEL`` ב-``md-heading-level-plugin.js``), והעותק כאן הוא מה שהעמוד מציג: שינוי במסמך שם
  אינו מגיע לעמוד בלי עדכון של הקובץ כאן.
- **הערכה** — :data:`THEME_ID` הוא ה-slug של ערכה ציבורית ב-``shared_themes``. העמוד מוצג בה לכל גולש,
  מחובר או לא, בלי קשר לערכה שבחר לשאר האתר.
- **הייצוא ל-HTML מעוצב** — :data:`EXPORT_THEME_IDS` הן הערכות שאפשר לייצא בהן (מתוך ``EXPORT_PRESETS``),
  ו-:func:`katex_inline_css` הוא ה-CSS של KaTeX שנכנס לקובץ כשבמסמך יש נוסחה. השרת מגיש רק את השלד, בלי
  הטקסט — ההסבר בראש החלק על השלד ב-``services/styled_export_service.py``.

התיעוד: ``docs/webapp/markdown-editor.rst``.
"""

from __future__ import annotations

import base64
import re
from functools import lru_cache
from pathlib import Path

from services.styled_export_service import EXPORT_PRESETS

#: הערכה הציבורית (``shared_themes``) שהעמוד מוצג בה.
THEME_ID = "everforest_dark"

DEMO_PATH = Path(__file__).with_name("markdown_editor_demo.md")

#: הערכות שאפשר לייצא בהן מהעורך, לפי הסדר שבו הן מוצגות. כל ערך אחר בנתיב השלד מקבל 404.
EXPORT_THEME_IDS: tuple[str, ...] = ("morass", "pen-paper-coffee")

#: ה-CSS של התצוגה, שבתוכו ה-CSS של KaTeX. esbuild (``webapp/static_build/build-md-preview.mjs``) כותב לפני כל
#: קובץ מקור הערה עם הנתיב שלו, והקטע של KaTeX הוא מההערה שלו ועד ההערה של הקובץ הבא.
MD_PREVIEW_BUNDLE_CSS = Path(__file__).with_name("static") / "css" / "md_preview.bundle.css"
KATEX_CSS_START = "/* node_modules/katex/dist/katex.min.css */"
KATEX_CSS_END = "/* webapp/static_build/md-preview-style.css */"

# הצהרת ``src`` של גופן בקטע של KaTeX, ובתוכה רשומות ``url("./fonts/<שם>") format("<סוג>")``. כל הצהרה נבנית מחדש
# בשלמותה מרשומת ה-woff2 שלה — כל דפדפן שתומך ב-KaTeX קורא אותו — ולכן הסדר של הרשומות, וה-woff וה-ttf שלצדה, לא
# משנים את מה שיוצא.
_KATEX_FONT_SRC_DECL_RE = re.compile(r"src:\s*(?P<entries>[^;]+);")
_KATEX_FONT_ENTRY_RE = re.compile(r'url\("\./fonts/(?P<name>[^"]+)"\)\s*format\("(?P<format>[^"]+)"\)')


def export_themes() -> list[dict]:
    """הערכות של הייצוא, לבורר בעמוד: מזהה, שם, וערכת ה-Mermaid לפי בהירות הערכה."""
    themes = []
    for theme_id in EXPORT_THEME_IDS:
        preset = EXPORT_PRESETS[theme_id]
        themes.append({
            "id": theme_id,
            "name": preset["name"],
            "description": preset.get("description", ""),
            # ``default`` היא הערכה הבהירה של Mermaid, ו-``dark`` הכהה
            "mermaid_theme": "default" if preset.get("category") == "light" else "dark",
            "bg": preset["variables"]["--bg-primary"],
            "accent": preset["variables"]["--primary"],
        })
    return themes


@lru_cache(maxsize=1)
def katex_inline_css() -> str:
    """ה-CSS של KaTeX מתוך הבאנדל של התצוגה, עם גופני woff2 בתוכו (base64), לקובץ שנפתח בלי רשת.

    נקרא בבקשה הראשונה שצריכה אותו ונשמר בזיכרון של התהליך. כשל — סימון שחסר בבאנדל, או גופן שחסר
    בתיקייה — **זורק**, ולא מחזיר CSS חלקי: נוסחה בלי ה-CSS שלה מותחת את כל העמוד לרוחב (השורש הריבועי של
    KaTeX 0.16.25 מצויר ב-SVG ברוחב ``400em``; על טקסט ההדגמה העמוד נמתח ל-6,670px, נמדד ב-Chromium ב-5.11.2026).
    ``lru_cache`` לא שומר חריגה, ולכן הבקשה הבאה תנסה שוב. ``tests/test_markdown_editor_export.py`` בודק שכל גופן
    נכנס, ושגופן חסר זורק.
    """
    bundle = MD_PREVIEW_BUNDLE_CSS.read_text(encoding="utf-8")
    start = bundle.index(KATEX_CSS_START)
    end = bundle.index(KATEX_CSS_END, start)
    fonts_dir = MD_PREVIEW_BUNDLE_CSS.parent / "fonts"

    def embed(match: re.Match) -> str:
        woff2 = [m.group("name") for m in _KATEX_FONT_ENTRY_RE.finditer(match.group("entries")) if m.group("format") == "woff2"]
        if len(woff2) != 1:
            raise ValueError(f"katex_inline_css: בהצהרת src יש {len(woff2)} גופני woff2 במקום אחד: {match.group(0)[:200]}")
        data = (fonts_dir / woff2[0]).read_bytes()
        return f'src: url(data:font/woff2;base64,{base64.b64encode(data).decode("ascii")}) format("woff2");'

    css = _KATEX_FONT_SRC_DECL_RE.sub(embed, bundle[start:end])
    if "./fonts/" in css:
        raise ValueError("katex_inline_css: נשארה הפניה לגופן בקובץ חיצוני")
    return css


@lru_cache(maxsize=1)
def demo_text() -> str:
    """טקסט ההדגמה, כפי שהוא בקובץ.

    נקרא בבקשה הראשונה ולא בזמן ייבוא, ונשמר בזיכרון של התהליך. ``lru_cache`` שומר רק ערך שהוחזר:
    קריאה שזרקה (קובץ חסר) תנסה שוב בבקשה הבאה, ולא תיזכר ככישלון.
    """
    return DEMO_PATH.read_text(encoding="utf-8")
