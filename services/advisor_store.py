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

**מחיקה:** המסמכים בשני האוספים נמחקים לבד באינדקס TTL (``advisor_indexes`` ב-``advisor_collections.py``,
יחד עם שמות האוספים וחלון השמירה), שנוצר בכל עליית שירות ב-``DatabaseManager._create_advisor_indexes``. לזיכרון השיחה זו
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

from advisor_collections import HISTORY_COLLECTION, HISTORY_RETENTION_DAYS, USAGE_COLLECTION
from utils import TimeUtils

#: כמה שאלות ליועץ מותרות לגולש ביום אחד (לפי שעון ישראל).
DAILY_QUESTION_LIMIT = 30


class AdvisorStoreError(RuntimeError):
    """כשל של המסד בפעולה של היועץ. הסיבה המקורית ב-``__cause__``."""


def _collection(name: str) -> Any:
    # ייבוא מאוחר: database/__init__.py יוצר DatabaseManager() שמתחבר כבר בבנאי,
    # ובלי זה כל ייבוא של המודול הזה היה פותח חיבור למסד
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


def get_history(user_id: int, limit: int, now: Optional[datetime] = None) -> List[Dict[str, str]]:
    """``limit`` הזוגות האחרונים, מהישן לחדש, בפורמט ההודעות של מודל השפה.

    ``limit`` מגיע מ-``ADVISOR_CONTEXT_EXCHANGES`` (``advisor_service.load_settings``), שמוודא שהוא חיובי.
    """
    since = _now(now) - timedelta(days=HISTORY_RETENTION_DAYS)
    try:
        cursor = (
            _collection(HISTORY_COLLECTION)
            .find(
                {"user_id": user_id, "created_at": {"$gte": since}},
                {"_id": 0, "question": 1, "answer": 1},
            )
            .sort([("created_at", -1), ("_id", -1)])
            .limit(limit)
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
