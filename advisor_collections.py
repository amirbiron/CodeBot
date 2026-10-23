"""מצב היועץ — שני האוספים במונגו ומפרט האינדקסים שלהם, שהמסד והשירות חולקים.

``DatabaseManager._create_indexes`` מצהיר על האינדקסים בכל עלייה, ו-``services/advisor_store.py``,
הכותב והקורא היחיד של שני האוספים, משתמש באותם שמות ובאותו חלון שמירה.

**טהור** — בלי pymongo ובלי מסד, כמו ``mcp_uploads.py``. ``database/manager.py`` מייבא אותו
ברמת המודול, ושם יש ``try`` סביב ``import pymongo`` שמבטיח שהמודול עולה גם כשהייבוא הזה
נכשל. מודול שמייבא pymongo בעצמו היה מפיל את ``database.manager`` כולו במצב הזה.

**חלון השמירה קבוע בקוד ולא משתנה סביבה.** ``DatabaseManager()`` מתחבר ומריץ את
``_create_indexes`` בבנאי, כלומר בכל שירות שמייבא את ``database`` ולא רק בבוט, ו-``enforce``
מעדכן אינדקס TTL קיים לחלון של מי שהתחבר אחרון. ערך שמוגדר רק בשירות של הבוט היה מתהפך
בכל עלייה של שירות אחר.
"""

from __future__ import annotations

from typing import Any, Dict, List

HISTORY_COLLECTION = "advisor_history"
USAGE_COLLECTION = "advisor_daily_usage"

#: כמה ימים נשמר זיכרון השיחה. ``WELCOME_TEXT`` ב-``handlers/advisor.py`` מציג אותו לגולש.
HISTORY_RETENTION_DAYS = 7

# מסמך המכסה של יום נמחק יומיים אחרי שנוצר — אחרי שהיום שלו הסתיים בוודאות.
# הקריאה עצמה אינה נשענת על המחיקה: המפתח כולל את התאריך.
_USAGE_TTL_SECONDS = 2 * 24 * 60 * 60


def advisor_indexes() -> List[Dict[str, Any]]:
    """הגדרות האינדקסים, בצורה ש-``safe_create_index`` מקבלת, עם שם האוסף.

    ``required`` מסמן אינדקס של **התנהגות** — כשל שלו יוצא כאירוע ברמת error
    (``DatabaseManager._create_advisor_indexes``). אינדקס ביצועים אינו מסומן.
    """
    return [
        {
            "collection": HISTORY_COLLECTION,
            "keys": [("created_at", 1)],
            "name": "advisor_history_ttl",
            "expire_after_seconds": HISTORY_RETENTION_DAYS * 24 * 60 * 60,
            # אינדקס קיים בשם הזה באורך חלון אחר מתעדכן, ולא נשאר כמו שהוא
            "enforce": True,
            "required": True,
        },
        {
            # השאילתה של get_history: שוויון על user_id, מיון וטווח על created_at,
            # ו-_id כשובר שוויון למיון יציב
            "collection": HISTORY_COLLECTION,
            "keys": [("user_id", 1), ("created_at", -1), ("_id", -1)],
            "name": "advisor_history_user_recent",
        },
        {
            "collection": USAGE_COLLECTION,
            "keys": [("created_at", 1)],
            "name": "advisor_daily_usage_ttl",
            "expire_after_seconds": _USAGE_TTL_SECONDS,
            "enforce": True,
            "required": True,
        },
    ]
