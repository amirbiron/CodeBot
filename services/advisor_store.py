"""מצב היועץ — זיכרון השיחה והמכסה היומית, ב-MongoDB.

**זיכרון השיחה** (``advisor_history``): מסמך אחד לכל זוג שאלה-תשובה. בבוט
הנפרד (``codekeeper_advisor_bot``) השאלה והתשובה היו שתי שורות ב-SQLite שנשמרו
בטרנזקציה אחת; כאן הן שדות של אותו מסמך, ולכן ``insert_one`` אחד שומר את שתיהן
או אף אחת — בלי טרנזקציה. השמירה נעשית רק אחרי תשובה מוצלחת, כדי שהודעת תקלה
לא תיכנס לזיכרון של המודל.

**המכסה היומית** (``advisor_daily_usage``): מגבלת הקצב של הבוט (``_rate_limit_gate``
ב-``main.py``) סופרת הודעות בדקה, כלומר עוצרת הצפה ולא עלות — גולש יכול לשלוח
עשרות שאלות בשעה בלי לגעת בה, וכל אחת היא קריאה בתשלום. לכן לכל גולש יש תקרה
של ``DAILY_QUESTION_LIMIT`` שאלות ליום, לפי היום בשעון ישראל.

**מחיקה:** המסמכים בשני האוספים נמחקים לבד באינדקס TTL (``advisor_indexes``), שנוצר בכל
עליית שירות ב-``DatabaseManager._create_advisor_indexes``. לזיכרון השיחה זו
התנהגות שמובטחת לגולש בהודעת הפתיחה, ולא היגיינה: אף שורת קוד שלנו אינה מוחקת
ממנו. ``get_history`` מסנן גם לפי גיל בעצמו, כי תהליך ה-TTL של מונגו אינו
מיידי: *"The TTL index does not guarantee that expired data is deleted immediately
upon expiration"* (https://www.mongodb.com/docs/manual/core/index-ttl/).

כל פונקציה כאן שניגשת למסד זורקת ``AdvisorStoreError`` בכל כשל שלו — זה ערוץ
הכשל היחיד שלהן.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

from utils import TimeUtils

HISTORY_COLLECTION = "advisor_history"
USAGE_COLLECTION = "advisor_daily_usage"

#: כמה ימים נשמר זיכרון השיחה. ``WELCOME_TEXT`` ב-``handlers/advisor.py`` מציג אותו לגולש.
HISTORY_RETENTION_DAYS = 7

#: כמה זוגות שאלה-תשובה אחרונים נכנסים לפרומפט.
CONTEXT_EXCHANGES = 5

#: כמה שאלות ליועץ מותרות לגולש ביום אחד (לפי שעון ישראל).
DAILY_QUESTION_LIMIT = 30

# מסמך המכסה של יום נמחק יומיים אחרי שנוצר — אחרי שהיום שלו הסתיים בוודאות.
# הקריאה עצמה אינה נשענת על המחיקה: המפתח כולל את התאריך.
_USAGE_TTL_SECONDS = 2 * 24 * 60 * 60


class AdvisorStoreError(RuntimeError):
    """כשל של המסד בפעולה של היועץ. הסיבה המקורית ב-``__cause__``."""


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


def _collection(name: str) -> Any:
    # ייבוא מאוחר: database/manager.py מייבא את המודול הזה בשביל advisor_indexes
    from database import db as _manager

    database = _manager.db
    if database is None:
        raise AdvisorStoreError("no database handle")
    return database[name]


def _now(now: Optional[datetime]) -> datetime:
    return now if now is not None else datetime.now(timezone.utc)


def israel_day(now: datetime) -> str:
    """התאריך בשעון ישראל, בצורה ``YYYY-MM-DD`` — "היום" של המכסה.

    השרת רץ ב-UTC, ובלי ההמרה היום היה מתחלף בשתיים או שלוש בלילה.
    """
    return TimeUtils.to_israel_time(now).date().isoformat()


def get_history(user_id: int, now: Optional[datetime] = None) -> List[Dict[str, str]]:
    """``CONTEXT_EXCHANGES`` הזוגות האחרונים, מהישן לחדש, בפורמט ההודעות של מודל השפה."""
    since = _now(now) - timedelta(days=HISTORY_RETENTION_DAYS)
    try:
        cursor = (
            _collection(HISTORY_COLLECTION)
            .find(
                {"user_id": user_id, "created_at": {"$gte": since}},
                {"_id": 0, "question": 1, "answer": 1},
            )
            .sort([("created_at", -1), ("_id", -1)])
            .limit(CONTEXT_EXCHANGES)
        )
        docs = list(cursor)
    except PyMongoError as exc:
        raise AdvisorStoreError("advisor history read failed") from exc

    messages: List[Dict[str, str]] = []
    for doc in reversed(docs):
        question, answer = doc.get("question"), doc.get("answer")
        if isinstance(question, str) and isinstance(answer, str):
            messages.append({"role": "user", "content": question})
            messages.append({"role": "assistant", "content": answer})
    return messages


def save_exchange(user_id: int, question: str, answer: str, now: Optional[datetime] = None) -> None:
    """שמירת שאלה ותשובה במסמך אחד — שתיהן או אף אחת."""
    doc = {"user_id": user_id, "question": question, "answer": answer, "created_at": _now(now)}
    try:
        result = _collection(HISTORY_COLLECTION).insert_one(doc)
    except PyMongoError as exc:
        raise AdvisorStoreError("advisor history write failed") from exc
    # מסד no-op (DISABLE_DB או חיבור שנכשל בעלייה) מחזיר הצלחה בלי מזהה
    if result.inserted_id is None:
        raise AdvisorStoreError("advisor history write returned no id")


def take_daily_question(user_id: int, now: Optional[datetime] = None) -> bool:
    """רישום שאלה במכסה של היום. ``True`` — מותר; ``False`` — המכסה מלאה.

    בדיקה ורישום בפעולה אטומית אחת. המסנן תופס את המסמך של היום רק כשנשאר בו
    מקום, ו-``upsert`` יוצר אותו בשאלה הראשונה של היום. כשהמכסה מלאה המסנן לא
    תופס, ה-``upsert`` מנסה ליצור מסמך שני עם אותו ``_id``, ומונגו דוחה אותו —
    ``_id`` ייחודי תמיד, בלי אינדקס שצריך ליצור. אותה דחייה מגיעה גם כשקריאה
    מקבילה יצרה את המסמך רגע לפני, ולכן אחריה יש ניסיון אחד בלי ``upsert``: הוא
    מצליח רק אם עדיין נשאר מקום.
    """
    current = _now(now)
    day = israel_day(current)
    selector = {"_id": f"{user_id}:{day}", "count": {"$lt": DAILY_QUESTION_LIMIT}}
    collection = _collection(USAGE_COLLECTION)
    try:
        try:
            doc = collection.find_one_and_update(
                selector,
                {
                    "$inc": {"count": 1},
                    "$setOnInsert": {"user_id": user_id, "day": day, "created_at": current},
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            retry = collection.find_one_and_update(
                selector, {"$inc": {"count": 1}}, return_document=ReturnDocument.AFTER
            )
            return retry is not None
    except PyMongoError as exc:
        raise AdvisorStoreError("advisor usage update failed") from exc
    # עם upsert ו-AFTER מונגו מחזיר תמיד מסמך; None מגיע רק ממסד no-op
    if doc is None:
        raise AdvisorStoreError("advisor usage update returned no document")
    return True
