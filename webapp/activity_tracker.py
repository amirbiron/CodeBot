"""
ריכוז לוגיקה משותפת לרישום פעילות משתמשים מתוך ה-Web App.
עודכן: בוצע מעבר לרישום מלא (100% מהאירועים) עם משקל 1,
כדי לקבל נתונים מדויקים ולבטל את מנגנון הדגימה.
"""
from __future__ import annotations

from typing import Optional

try:
    from user_stats import user_stats as _user_stats  # type: ignore
except Exception:  # pragma: no cover
    _user_stats = None  # type: ignore

# שינינו ל-100% ומשקל 1 (כל כניסה נספרת כאחת)
_SAMPLE_PROBABILITY = 1.0
_WEIGHT = 1


def log_user_event(user_id: int, username: Optional[str] = None) -> bool:
    """רושם פעילות משתמש (ללא דגימה - תיעוד מלא) עבור סטטיסטיקות הווב-אפליקציה."""
    if not user_id or _user_stats is None:
        return False

    # הסרנו את בדיקת ה-Random. כעת הקוד תמיד ינסה לרשום את האירוע.

    try:
        _user_stats.log_user(user_id, username, weight=_WEIGHT)
        return True
    except TypeError:
        # תאימות לאחור במידה והחתימה אינה תומכת ב-weight.
        _user_stats.log_user(user_id, username)
        return True
    except Exception:
        # לעולם לא נכשיל בקשה רק בגלל סטטיסטיקה.
        return False
