"""קישורי השיתוף של ייצוא ה-HTML המעוצב (``/shared/styled/<token>``) — המפרט שהמסד והוובאפ חולקים.

הוובאפ הוא הכותב היחיד לאוסף (``api_create_styled_share`` ב-``webapp/app.py``) והקורא היחיד שלו
(``public_shared_styled``). ``DatabaseManager._create_indexes``, שהוובאפ עובר בכל עלייה, מצהיר על
האינדקסים מכאן.

**טהור** — בלי pymongo ובלי מסד, מאותה סיבה של ``mcp_uploads.py``: מודול תחת ``database/`` היה גורר את
``database/__init__.py``, שיוצר ``DatabaseManager()`` גלובלי בזמן הייבוא.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "STYLED_SHARES_COLLECTION",
    "STYLED_SHARE_EXPIRES_FIELD",
    "STYLED_SHARE_TOKEN_INDEX_NAME",
    "STYLED_SHARE_TTL_INDEX_NAME",
    "styled_shares_indexes",
]

STYLED_SHARES_COLLECTION = "styled_shares"

#: מועד הפקיעה של קישור זמני, כ-``datetime`` (ולא מחרוזת: מסמך שהשדה שלו אינו תאריך לא נמחק לעולם).
#: לקישור קבוע הערך ``None``, ו-TTL מדלג על מסמך שהשדה שלו אינו תאריך
#: (https://www.mongodb.com/docs/manual/core/index-ttl/), כך שהוא נשאר.
STYLED_SHARE_EXPIRES_FIELD = "expires_at"

STYLED_SHARE_TTL_INDEX_NAME = "styled_shares_ttl"
STYLED_SHARE_TOKEN_INDEX_NAME = "styled_shares_token"


def styled_shares_indexes() -> list[dict[str, Any]]:
    """הגדרות האינדקסים, בצורה ש-``safe_create_index`` מקבלת.

    ``required`` מסמן אינדקס של **התנהגות**: כשל שלו יוצא כאירוע ``db_styled_shares_index_missing`` ברמת
    error (``DatabaseManager._create_styled_shares_indexes``).
    """
    return [
        {
            # אף שורת קוד שלנו אינה מוחקת קישור שפקע. הקורא כבר עונה 404 על קישור כזה, ולכן ה-TTL הוא מה
            # שמוחק את ה-HTML (ומעכשיו את ה-Markdown) של המשתמש מהמסד, ולא רק מסתיר אותו.
            "keys": [(STYLED_SHARE_EXPIRES_FIELD, 1)],
            "name": STYLED_SHARE_TTL_INDEX_NAME,
            "expire_after_seconds": 0,
            # אינדקס קיים בשם הזה שאינו במפרט היה מתנגש, ובלי אכיפה ה-TTL לא היה נבנה לעולם.
            "enforce": True,
            "required": True,
        },
        {
            # הקורא מוצא קישור לפי ``token`` (``find_one``). ‏256 ביט אקראיים (``secrets.token_urlsafe(32)``)
            # אינם מתנגשים בפועל; האינדקס הייחודי הוא מה שהופך את "לא בפועל" ל"לא", ומונע סריקה מלאה.
            # כפילות קיימת הייתה מכשילה את היצירה, וזה מדווח באותו אירוע.
            "keys": [("token", 1)],
            "name": STYLED_SHARE_TOKEN_INDEX_NAME,
            "unique": True,
            "enforce": True,
            "required": True,
        },
    ]
