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


def log_user_event(user_id: int, username: Optional[str] = None) -> None:
    """רושם פעילות משתמש (עם דגימה) עבור סטטיסטיקות הווב-אפליקציה."""
    if not user_id or _user_stats is None:
        return

    try:
        sampled = random.random() < _SAMPLE_PROBABILITY
    except Exception:
        sampled = True

    if not sampled:
        return

    try:
        _user_stats.log_user(user_id, username, weight=_WEIGHT)
    except TypeError:
        # תאימות לאחור במידה והחתימה אינה תומכת ב-weight.
        _user_stats.log_user(user_id, username)
    except Exception:
        # לעולם לא נכשיל בקשה רק בגלל סטטיסטיקה.
        pass
