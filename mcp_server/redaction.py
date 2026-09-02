"""סינון סודות משותף — רשימת דפוסים אחת לכל צרכן בשרת ה-MCP.

**למה מודול נפרד ולא פונקציה בתוך** ``primer.py``\ **.** את הרשימה הזו צריכים
היום שני מסלולים שאין ביניהם שום קשר: הפריימר, שמגיש טקסט שהמשתמש כתב לתוך
ההקשר של המודל, ושער הפרטיות של האנליטיקס, שמעביר טקסט חופשי ל-PostHog.
``primer.py`` הוא ראוט HTTP — הוא מייבא ``starlette`` ואת ``mcp_server.auth``,
ו-``analytics.py`` אינו צריך אף אחד מהם. ייבוא של ראוט רק כדי להגיע לרג'קס הוא
בדיוק סוג הצימוד שהופך הוספת תלות במקום אחד לתקלה במקום אחר.

הכיוון ההפוך — להעתיק את הדפוסים — כבר נכשל בפרויקט הזה: כשלכל רשת הייתה
רשימה משלה, דפוס נוסף לאחת ולא לשנייה (ראו ההערה ב-``utils.SensitiveDataFilter``).
לכן: מודול טהור שמייבא ``logging`` ו-``re`` בלבד, ושני הצרכנים מייבאים ממנו.
אותה תבנית של ``file_dates.py`` בשורש הריפו.

**מה זה כן, ומה זה לא.** זו רשימת דפוסים, כלומר רשימה שחורה של **צורות**
מוכרות. היא תופסת מפתח AWS, טוקן GitHub, JWT, ``Bearer``, ומחרוזת חיבור עם
סיסמה — בכל מקום במחרוזת. יש בה גם כלל אחד לפי **שם** ולא לפי צורה
(``FOO_TOKEN=...``), כפי ש-``CRITICAL-PATTERNS.md`` K14 דורש — אבל הוא מעוגן
לתחילת שורה, בכוונה, כדי לא לשבש פרוזה בפריימר. **הכלל הזה אינו יורה על
מחרוזת חד-שורתית**, וזה נמדד. ראו את ה-docstring של :func:`redact_secrets`.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# סינון סודות
# --------------------------------------------------------------------------
# מרחיב את הדפוסים של ``utils.SensitiveDataFilter`` (שמסנן לוגים) ומוסיף את
# הטוקנים של השירות הזה עצמו. הסינון רץ על **כל** הגוף המוגמר, לא רק על שדה
# ההוראות — כדי ששום נתיב עתידי שיוסיף תוכן לגוף לא יעקוף אותו בטעות.
_REDACTED = "***REDACTED***"

_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # מפתחות פרטיים — קודם, כי הם רב-שורתיים ובולעים את מה שביניהם
    (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
        f"[PRIVATE KEY {_REDACTED}]",
    ),
    # GitHub
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}"), _REDACTED),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), _REDACTED),
    # הטוקנים של CodeKeeper עצמו: PAT, OAuth access, OAuth refresh, auth code
    (re.compile(r"ck(?:mcp|oat|ort|oc)_[A-Za-z0-9\-_]{16,}"), _REDACTED),
    # ספקי AI / ענן נפוצים
    (re.compile(r"sk-(?:ant-|proj-)?[A-Za-z0-9\-_]{20,}"), _REDACTED),
    (re.compile(r"AKIA[0-9A-Z]{16}"), _REDACTED),
    (re.compile(r"xox[abprs]-[A-Za-z0-9\-]{10,}"), _REDACTED),
    (re.compile(r"AIza[A-Za-z0-9\-_]{30,}"), _REDACTED),
    # JWT (שלושה חלקים base64url)
    (
        re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
        _REDACTED,
    ),
    # כותרת Authorization שהודבקה כטקסט
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-_.=:/+]{10,}"), f"Bearer {_REDACTED}"),
    # שורות השמה בסגנון .env, למשל ``FOO_TOKEN=...`` או ``export API_KEY: ...``
    #
    # שתי הגבלות שמונעות פגיעה בטקסט רגיל — פריימר מושחת גרוע מפריימר לא מסונן:
    # (1) הערך חייב להיות באורך של סוד אמיתי (12+ תווים), כדי ש-``key=value``
    #     בתוך הסבר לא ייעלם; (2) placeholder או הפניה למשתנה סביבה
    #     (``<your-key>``, ``${OPENAI_KEY}``, ``...``) אינם סוד ונשארים קריאים.
    (
        re.compile(
            r"(?im)^([ \t]*(?:export[ \t]+)?[A-Za-z0-9_]*"
            r"(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIALS?|APIKEY)[A-Za-z0-9_]*)"
            r"[ \t]*[=:][ \t]*(?!['\"]?(?:<|\$\{|\$[A-Za-z_]|\.\.\.|\{\{))"
            r"['\"]?[^\s'\"]{12,}"
        ),
        r"\1=" + _REDACTED,
    ),
    # מחרוזות חיבור עם סיסמה מוטמעת: scheme://user:pass@host
    (
        re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://[^\s:/@]+):[^\s/@]+@"),
        r"\1:" + _REDACTED + "@",
    ),
)


def redact_secrets(text: str) -> str:
    """מחזיר את הטקסט כשכל מה שנראה כמו מפתח/טוקן מוחלף.

    פייל-סייף: אם דפוס כלשהו נכשל, מדלגים עליו וממשיכים — עדיף סינון חלקי על
    פריימר שנופל. שאר הדפוסים עדיין רצים.

    **מה נמדד שהוא תופס, ומה לא.** הדפוסים לפי *צורה* אינם מעוגנים, ולכן הם
    עובדים גם באמצע מחרוזת: מפתח AWS בזנב של הודעת ``ValidationError`` של
    Pydantic מוחלף, וכך גם ``ghp_``, ``ckmcp_``, ``sk-``, JWT, ``Bearer`` ו-
    ``scheme://user:pass@host``.

    הכלל לפי **שם** (``API_KEY=...``) הוא היחיד שמעוגן ב-``^``, ולכן הוא
    **אינו** יורה כשההשמה יושבת באמצע שורה — למשל ``input_value={'e':
    'API_KEY=…'}``. העיגון הוא הגנה על הפריימר: בלעדיו ``key=value`` בתוך
    הסבר היה נמחק, ופריימר מושחת גרוע מפריימר לא מסונן. זו הגבלה ידועה ולא
    פער שהוסתר — הרחבתה נוגעת בשני הצרכנים ומחזירה את ה-false positive של
    ``monkey=`` שמתואר ב-K14, ולכן היא החלטה בפני עצמה.

    נתיבי קבצים ושמות אינם סודות ואינם מסוננים כאן; זה מכוון.
    """
    out = text or ""
    for pattern, replacement in _SECRET_PATTERNS:
        try:
            out = pattern.sub(replacement, out)
        except Exception:  # pragma: no cover — הגנה, לא זרימה צפויה
            logger.warning("redaction pattern failed", exc_info=True)
    return out
