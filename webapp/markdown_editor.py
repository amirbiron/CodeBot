"""העורך הציבורי (``/markdown-editor``): עורך Markdown ותצוגה חיה, בלי התחברות, לגולשים שמגיעים מחיפוש.

כאן רק הנתונים שהעמוד נשען עליהם; הראוט הוא ``markdown_editor`` ב-``webapp/app.py``, והתבנית
``webapp/templates/markdown_editor.html``.

- **טקסט ההדגמה** — ``markdown_editor_demo.md`` שליד הקובץ הזה. העורך מציג אותו בכניסה הראשונה, ו"טען דוגמה"
  מחזיר אותו. הוא עותק של המסמך ``CodeKeeper_Markdown.md`` ב-CodeKeeper, בלי הכותרות H5 ו-H6 (התצוגה החיה לא
  מרנדרת אותן — ``RENDERER_VARIANTS`` ב-``live-preview.js``), והעותק כאן הוא מה שהעמוד מציג: שינוי במסמך שם
  אינו מגיע לעמוד בלי עדכון של הקובץ כאן.
- **הערכה** — :data:`THEME_ID` הוא ה-slug של ערכה ציבורית ב-``shared_themes``. העמוד מוצג בה לכל גולש,
  מחובר או לא, בלי קשר לערכה שבחר לשאר האתר.

התיעוד: ``docs/webapp/markdown-editor.rst``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

#: הערכה הציבורית (``shared_themes``) שהעמוד מוצג בה.
THEME_ID = "everforest_dark"

DEMO_PATH = Path(__file__).with_name("markdown_editor_demo.md")


@lru_cache(maxsize=1)
def demo_text() -> str:
    """טקסט ההדגמה, כפי שהוא בקובץ.

    נקרא בבקשה הראשונה ולא בזמן ייבוא, ונשמר בזיכרון של התהליך. ``lru_cache`` שומר רק ערך שהוחזר:
    קריאה שזרקה (קובץ חסר) תנסה שוב בבקשה הבאה, ולא תיזכר ככישלון.
    """
    return DEMO_PATH.read_text(encoding="utf-8")
