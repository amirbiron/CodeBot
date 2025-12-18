from __future__ import annotations

from typing import Any, Dict, Optional

# מילון תרגומים בסיסי (אפשר להרחיב לקבצי JSON בהמשך)
TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "he": {
        "welcome": "ברוך הבא לבוט הדיווחים! 🐾",
        "report_success": "הדיווח נקלט בהצלחה במערכת.",
        "error_generic": "מצטערים, אירעה שגיאה. הדיווח הועבר לטיפול ב-Sentry.",
    },
    "en": {
        "welcome": "Welcome to the Reporting Bot! 🐾",
        "report_success": "The report has been successfully recorded.",
        "error_generic": "Sorry, an error occurred. The issue has been logged in Sentry.",
    },
}

_SUPPORTED_LANGS = {"he", "en"}
_DEFAULT_LANG = "he"

# Public aliases (נוח לייבוא מבחוץ בלי להישען על שמות פנימיים)
SUPPORTED_LANGS = tuple(sorted(_SUPPORTED_LANGS))
DEFAULT_LANG = _DEFAULT_LANG


def _normalize_lang(lang: Optional[str]) -> str:
    value = (lang or "").strip().lower()
    if not value:
        return _DEFAULT_LANG

    # תומכים רק he/en כרגע; כל דבר אחר נופל ל-default.
    if value in _SUPPORTED_LANGS:
        return value

    # קודים בסגנון he-IL / en-US
    if value.startswith("he"):
        return "he"
    if value.startswith("en"):
        return "en"

    return _DEFAULT_LANG


def get_text(key: str, lang: str = _DEFAULT_LANG) -> str:
    """שליפת טקסט מתורגם לפי שפה.

    אם המפתח לא קיים, מחזיר את `key` כדי לא לקרוס.
    """
    safe_lang = _normalize_lang(lang)
    return TRANSLATIONS.get(safe_lang, TRANSLATIONS[_DEFAULT_LANG]).get(key, key)


async def detect_user_language(telegram_user: Any, db_user: Any = None) -> str:
    """זיהוי שפת המשתמש (he/en) וסנכרון מול מודל משתמש מה-DB.

    סדר עדיפויות:
    1) אם ב-DB כבר שמורה שפה (db_user.language או db_user['language']) — משתמשים בה.
    2) אחרת, משתמשים ב-language_code של טלגרם (he* => he, אחרת en).

    "סנכרון": אם לא הייתה שפה ב-DB אבל הצלחנו לזהות — ננסה לעדכן את האובייקט/מילון
    `db_user` בזיכרון (best-effort), כדי ששאר ה-flow ישאר עקבי.
    """

    # 1) נסה להביא שפה מה-DB (תומך גם באובייקט וגם ב-dict)
    db_lang: Optional[str] = None
    if db_user is not None:
        try:
            if isinstance(db_user, dict):
                raw = db_user.get("language")
            else:
                raw = getattr(db_user, "language", None)
            db_lang = str(raw).strip() if raw is not None else None
        except Exception:
            db_lang = None

    normalized_db = _normalize_lang(db_lang)
    if db_lang and normalized_db in _SUPPORTED_LANGS:
        return normalized_db

    # 2) fallback לטלגרם
    tg_lang = None
    try:
        tg_lang = getattr(telegram_user, "language_code", None)
    except Exception:
        tg_lang = None

    tg_value = (str(tg_lang) if tg_lang is not None else "").strip().lower()
    if not tg_value:
        detected = _DEFAULT_LANG
    else:
        detected = "he" if tg_value.startswith("he") else "en"

    # best-effort sync חזרה למודל user (בזיכרון)
    if db_user is not None and not db_lang:
        try:
            if isinstance(db_user, dict):
                db_user["language"] = detected
            else:
                # אם זה dataclass / אובייקט רגיל
                setattr(db_user, "language", detected)
        except Exception:
            pass

    return detected
