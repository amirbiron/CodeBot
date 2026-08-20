"""
User Roles — מקור אמת יחיד ל"מי אדמין" ו"מי פרימיום".

שתי הפונקציות האלה קובעות הרשאות, והן היו משוכפלות מילה במילה בשני מקומות:
``webapp/app.is_admin``/``is_premium`` ו-``webapp/code_tools_api._is_admin``/
``_is_premium``. שני עותקים של לוגיקת הרשאות הם שני מקומות שיכולים לסטות,
ורק אחד מהם ייבדק.

המודול טהור בכוונה — קורא ``os.environ`` ותו לא, בלי Flask ובלי מסד. זה מה
שמאפשר ל-``webapp/sticky_notes_api`` לייבא אותו: ``webapp/app`` **מייבא** את
``sticky_notes_api``, ולכן ייבוא הפוך היה יוצר מעגל. אותה תבנית שכבר עובדת
עם ``sticky_notes_scope``, שמיובא משלושה מודולים.
"""
from __future__ import annotations

import os
from typing import List


def _ids_from_env(var_name: str) -> List[int]:
    """רשימת מזהי משתמש ממשתנה סביבה מופרד בפסיקים.

    ערך שאינו ספרתי מדולג בשקט — כך התנהגו שני העותקים הקודמים, וזו גם
    ההתנהגות הבטוחה: רשומה פגומה ברשימת אדמינים לא אמורה להעניק הרשאה,
    וגם לא להפיל את הבקשה.
    """
    try:
        raw = os.getenv(var_name, "") or ""
        return [int(part.strip()) for part in raw.split(",") if part.strip().isdigit()]
    except Exception:
        return []


def is_admin(user_id: int) -> bool:
    """בודק אם משתמש הוא אדמין לפי ``ADMIN_USER_IDS``."""
    try:
        return int(user_id) in _ids_from_env("ADMIN_USER_IDS")
    except Exception:
        return False


def is_premium(user_id: int) -> bool:
    """בודק אם משתמש הוא פרימיום לפי ``PREMIUM_USER_IDS``."""
    try:
        return int(user_id) in _ids_from_env("PREMIUM_USER_IDS")
    except Exception:
        return False
