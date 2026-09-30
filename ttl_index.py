"""האם שורה מ-``list_indexes()`` היא אינדקס TTL כפי שהוצהר — בדיקה אחת לכל מפרט.

**למה מודול נפרד.** שני אינדקסי TTL שהם **התנהגות** ולא ביצועים נבדקים מול
המסד באותה צורה בדיוק: זה שמרוקן את סל המיחזור (``file_deletion.py``) וזה
שמוחק העלאות ממתינות של שירות ה-MCP (``mcp_uploads.py``). הבדיקה נכתבה פעם
אחת, לסל, והועברה לכאן כשנוסף השני — עותק שני שלה היה סוטה מהראשון בשקט,
וסטייה כאן פירושה אינדקס שנחשב "מאומת" בלי שהוא מוחק דבר.

**טהור** — ``typing`` ותו לא, בלי pymongo ובלי מסד. אותה תבנית של
``file_dates.py`` ו-``file_deletion.py``, ומאותה סיבה: שני הצדדים מייבאים
אותו בלי לגרור את ``database/__init__.py``, שיוצר ``DatabaseManager()`` גלובלי
בזמן הייבוא.
"""

from __future__ import annotations

from typing import Any, Mapping

__all__ = ["is_ttl_index"]


def _is_number(value: Any) -> bool:
    # ``bool`` הוא תת-מחלקה של ``int``, ו-``True == 1``; מפתח אינדקס אינו בוליאני.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_ttl_index(
    index_info: Any,
    *,
    field: str,
    expire_after_seconds: int,
    partial_filter: Mapping[str, Any] | None = None,
) -> bool:
    """האם ``index_info`` — שורה אחת מ-``list_indexes()`` — היא ה-TTL שהוצהר.

    הבדיקה היא על המפרט ולא על השם: מונגו מוחק לפי המפתח, החלון והמסנן, ואינדקס
    תקין בשם אחר עושה את אותה עבודה. מפתח מורכב אינו מתאים גם אם יש עליו חלון:
    אינדקס TTL הוא חד-שדה (https://www.mongodb.com/docs/manual/core/index-ttl/),
    ומול 8.0.32 נמדד שהשרת **דוחה** יצירה כזו (``OperationFailure`` קוד 67) ולא
    "מתעלם" כמו שהתיעוד מנסח. הבדיקה נשארת בכל זאת, כי השורה מגיעה מחוץ לתהליך.

    המספרים נבדקים בערכם ולא בטיפוס: אינדקס שנוצר מ-mongosh שומר ``1.0`` ולא
    ``1``, ושניהם אותו מפרט. הכיוון חייב להיות ``1``, כפי שכל מפרט בריפו מצהיר.

    ``partial_filter``: כשהוא נתון, המסנן החלקי של האינדקס חייב להיות שווה לו.
    כשאינו נתון, לאינדקס **אסור** להיות מסנן: TTL חלקי מוחק רק את מה שעונה
    למסנן, וזו הבטחה אחרת מזו שהוצהרה.
    """
    if not isinstance(index_info, Mapping):
        return False

    key = index_info.get("key")
    if not isinstance(key, Mapping) or list(key.keys()) != [field]:
        return False
    direction = key.get(field)
    if not _is_number(direction) or direction != 1:
        return False

    expire = index_info.get("expireAfterSeconds")
    if not _is_number(expire) or expire != expire_after_seconds:
        return False

    partial = index_info.get("partialFilterExpression")
    if partial_filter is None:
        return partial is None
    if not isinstance(partial, Mapping):
        return False
    return dict(partial) == dict(partial_filter)
