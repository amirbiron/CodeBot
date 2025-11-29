"""
ריכוז לוגיקה משותפת לרישום פעילות משתמשים מתוך ה-Web App.
שומר על אותם כללי דגימה (25% עם משקל 4) כמו שכבת הבוט כדי
להימנע מעומס על MongoDB ולשמור אחידות בסטטיסטיקות.
"""
from __future__ import annotations

import random
from typing import Optional

try:
    from user_stats import user_stats as _user_stats  # type: ignore
except Exception:  # pragma: no cover
    _user_stats = None  # type: ignore

_SAMPLE_PROBABILITY = 0.25
_WEIGHT = 4  # 1 / 0.25


def log_user_event(user_id: int, username: Optional[str] = None) -> bool:
    """רושם פעילות משתמש (עם דגימה) עבור סטטיסטיקות הווב-אפליקציה."""
    if not user_id or _user_stats is None:
        return False

    try:
        sampled = random.random() < _SAMPLE_PROBABILITY
    except Exception:
        sampled = True

    if not sampled:
        return False

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
