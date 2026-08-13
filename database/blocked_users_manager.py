"""חסימת משתמשים מהבוט.

**נקודת אכיפה אחת.** השער ב-``main.py`` קורא ל-``is_blocked`` ותו לא.
חסימה שנוספת לכל handler בנפרד מפספסת את ה-handler הבא שנוסיף, וזה
כשל שקשה לגלות — הוא נראה כמו פיצ'ר שעובד.

שלוש שכבות, לפי הסדר:

1. **אדמין** — לעולם לא נחסם, גם אם המזהה שלו ברשימה. הבדיקה הראשונה,
   כדי שלא תיווצר מצב שבו נועלים את עצמנו החוצה בלי דרך חזרה.
2. **``BLOCKED_USER_IDS`` מ-ENV** — רשת הביטחון. נקרא בלי שאילתה,
   ו**אי אפשר לבטל אותו מתוך הבוט**. מי שיצליח להשיג הרשאת אדמין לא
   יוכל לשחרר את עצמו.
3. **הקולקציה ``blocked_users``** — הניהול השוטף, דרך ``/ban``.

**למה יש כאן קאש, ולמה הוא לא אופטימיזציה.** השער רץ על כל הודעה וכל
לחיצת כפתור, ו-pymongo כאן **סינכרוני**. שאילתה ישירה מתוך handler
אסינכרוני חוסמת את ה-event loop כולו — עשרים הודעות בדקה הן עשרים
חסימות. הקאש מחזיק את **כל** קבוצת החסומים (עשרות רשומות לכל היותר),
ולכן טעינה אחת זולה משאילתה פר-משתמש.

הרענון היחיד שעובר ל-DB רץ ב-``asyncio.to_thread``. ``/ban`` ו-``/unban``
מאפסים את הקאש מיד, כדי שחסימה תיכנס לתוקף בשנייה ולא אחרי דקה.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

COLLECTION_NAME = "blocked_users"

# חלון הרענון של הקאש. שינוי דרך ``/ban`` אינו ממתין לו — הוא מאפס
# מיד — ולכן הערך הזה מכסה רק שינויים שנעשו מחוץ לתהליך (כתיבה ישירה
# ל-DB, או מופע שני של השירות).
CACHE_TTL_SECONDS = 60.0

# תקרה לגודל הטעינה. ההנחה היא עשרות רשומות, ואין מי שיאכוף אותה מחר —
# בלי התקרה, רשימה שתגדל בשקט תמשוך את כל הקולקציה לזיכרון בכל רענון.
# חריגה נרשמת בלוג, כי היא סימן שהעיצוב כאן כבר לא מתאים.
MAX_BLOCKED_LOADED = 5000


class _Cache:
    """קבוצת המזהים החסומים, עם תפוגה.

    ``None`` פירושו "לא נטען עדיין" — נבדל מ-``set()`` שפירושו "נטען,
    ואין אף חסום". בלי ההבחנה הזו כל טעינה שמחזירה רשימה ריקה הייתה
    נראית כמו קאש שפג, ומייצרת שאילתה בכל בקשה.
    """

    def __init__(self) -> None:
        self._ids: frozenset[int] | None = None
        self._loaded_at: float = 0.0
        self._version: int = 0
        self._lock = threading.Lock()

    def version(self) -> int:
        """המספר הסידורי הנוכחי. יש לצלם אותו **לפני** שמתחילים לטעון."""
        with self._lock:
            return self._version

    def get(self) -> frozenset[int] | None:
        with self._lock:
            if self._ids is None:
                return None
            if (time.monotonic() - self._loaded_at) >= CACHE_TTL_SECONDS:
                return None
            return self._ids

    def set_if_current(self, ids: frozenset[int], version: int) -> bool:
        """כותב רק אם לא בוצע ``invalidate`` מאז שהטעינה התחילה.

        בלי התנאי הזה נוצר מרוץ: הטעינה קוראת את ה-DB, ``/ban`` מאפס
        את הקאש בזמן שהיא רצה, והכתיבה המאוחרת מחזירה את הקבוצה
        הישנה — כלומר החסימה החדשה לא תופסת עד לפקיעת ה-TTL, בדיוק
        ההפך ממה ש-``block_user`` מבטיח.
        """
        with self._lock:
            if version != self._version:
                return False
            self._ids = ids
            self._loaded_at = time.monotonic()
            return True

    def invalidate(self) -> None:
        with self._lock:
            self._ids = None
            self._loaded_at = 0.0
            self._version += 1


_cache = _Cache()

# מונע טעינות מקבילות כשהקאש פג. נוצר עצלנית כדי לא להיקשר ל-event loop
# מסוים בזמן הייבוא — בדיקות מריצות כמה לולאות.
_load_lock = asyncio.Lock()


def _parse_ids(raw: str | None) -> frozenset[int]:
    """מפרק רשימת מזהים מופרדת בפסיקים.

    ערך פגום מדולג בשקט ולא מפיל את הפירוק, כי משתנה סביבה עם פסיק
    מיותר אינו סיבה לחסום את כל המשתמשים או לפתוח את כולם.
    """
    if not raw:
        return frozenset()
    out: set[int] = set()
    for part in str(raw).split(","):
        part = part.strip()
        # ``lstrip('-')`` כדי ש-``-5`` לא ייחשב מזהה. מזהי טלגרם חיוביים.
        if part.isdigit():
            out.add(int(part))
    return frozenset(out)


def env_blocked_ids() -> frozenset[int]:
    """הרשימה מ-ENV. נקראת בכל פעם, כי ``os.environ`` זול ובדיקות משנות אותו."""
    return _parse_ids(os.getenv("BLOCKED_USER_IDS"))


def _admin_ids() -> frozenset[int]:
    """מזהי האדמינים, מאותו מקור שהבוט כבר משתמש בו.

    הייבוא מקומי כדי לא ליצור תלות מעגלית: ``main`` מייבא את המודול
    הזה, ולכן ייבוא ברמת המודול היה נסגר על עצמו.
    """
    try:
        from main import get_admin_ids  # type: ignore

        return frozenset(get_admin_ids() or [])
    except Exception:
        return _parse_ids(os.getenv("ADMIN_USER_IDS"))


def _collection() -> Any | None:
    """הקולקציה, או ``None`` אם אין DB זמין."""
    try:
        from services.db_provider import get_db

        database = get_db()
        if database is None:
            return None
        return database[COLLECTION_NAME]
    except Exception:
        logger.debug("blocked_users: אין גישה ל-DB", exc_info=True)
        return None


def ensure_indexes() -> None:
    """אינדקס ייחודי על ``user_id``.

    הייחודיות נאכפת ב-DB ולא בקוד, ולכן ``/ban`` פעמיים על אותו משתמש
    אינו יוצר שתי רשומות — בלי check-then-act שיכול להיכשל בין שני
    מפעילים במקביל.
    """
    coll = _collection()
    if coll is None:
        return
    try:
        coll.create_index("user_id", unique=True, name="blocked_user_id_unique")
    except Exception:
        logger.debug("blocked_users: יצירת אינדקס הייחודיות נכשלה", exc_info=True)
    try:
        # ``list_blocked`` ממיין לפי התאריך. בלי אינדקס המיון מתבצע
        # בזיכרון — זניח היום, אבל השאילתה נשארת צפויה גם כשהרשימה תגדל.
        coll.create_index([("blocked_at", -1)], name="blocked_at_desc")
    except Exception:
        logger.debug("blocked_users: יצירת אינדקס התאריך נכשלה", exc_info=True)


def _load_from_db() -> frozenset[int] | None:
    """טעינת כל החסומים. סינכרוני — לקרוא רק דרך ``asyncio.to_thread``.

    ``None`` פירושו **כשל**, ו-``frozenset()`` פירושו "נטען, ואין אף
    חסום". ההבחנה חיונית: בלעדיה "אין DB" נראה בדיוק כמו "אין חסומים",
    והקאש היה שומר את הכשל לדקה — כלומר DB שלא הספיק לעלות היה מבטל
    את כל החסימות עד לפקיעה.
    """
    coll = _collection()
    if coll is None:
        return None
    ids: set[int] = set()
    for doc in coll.find({}, {"user_id": 1, "_id": 0}).limit(MAX_BLOCKED_LOADED):
        try:
            ids.add(int(doc["user_id"]))
        except (KeyError, TypeError, ValueError):
            continue
    if len(ids) >= MAX_BLOCKED_LOADED:
        logger.warning(
            "blocked_users: נטענו %d רשומות — הגבול הוא %d, וחסימות מעבר לו אינן נאכפות",
            len(ids),
            MAX_BLOCKED_LOADED,
        )
    return frozenset(ids)


async def blocked_ids() -> frozenset[int]:
    """קבוצת החסומים מה-DB, דרך הקאש.

    כשל ב-DB מחזיר קבוצה ריקה — **fail-open**. משתמש לא ייחסם בגלל
    תקלת תשתית. זו אותה החלטה שכבר קיימת במגביל הקצב, ומאותה סיבה:
    לנעול את כל המשתמשים בכל תקלת DB גרוע בהרבה מלתת לספאמר בודד
    לעבור בזמן תקלה.

    התוצאה **אינה** נכנסת לקאש בכשל, כדי שהניסיון הבא לא ידלג על DB
    שכבר חזר לעבוד. שני מסלולי כשל מטופלים זהה — חריגה, ו-DB שאינו
    זמין בכלל — כי מבחינת הקאש אין ביניהם הבדל.
    """
    cached = _cache.get()
    if cached is not None:
        return cached

    # נעילה סביב הטעינה: בלעדיה, עשרים הודעות שמגיעות ברגע שהקאש פג
    # פותחות עשרים שאילתות במקביל — בדיוק ההפך מהחוזה של המודול הזה.
    async with _load_lock:
        cached = _cache.get()
        if cached is not None:
            return cached

        # הגרסה מצולמת לפני הטעינה, כדי ש-invalidate שיקרה תוך כדי
        # יבטל את הכתיבה ולא ידרס על ידה.
        version = _cache.version()
        try:
            ids = await asyncio.to_thread(_load_from_db)
        except Exception:
            logger.warning("blocked_users: טעינה מה-DB נכשלה, לא חוסמים", exc_info=True)
            return frozenset()
        if ids is None:
            logger.warning("blocked_users: אין DB זמין, לא חוסמים ולא שומרים בקאש")
            return frozenset()
        _cache.set_if_current(ids, version)
        return ids


async def is_blocked(user_id: int) -> bool:
    """האם המשתמש חסום. זו הפונקציה היחידה שהשער צריך."""
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return False
    if uid <= 0:
        return False

    # אדמין ראשון, ולפני שתי הרשימות: מזהה אדמין שנכנס לרשימה בטעות
    # לא ינעל את מי שאמור לשחרר אותו.
    if uid in _admin_ids():
        return False

    if uid in env_blocked_ids():
        return True

    return uid in await blocked_ids()


# ── ניהול ─────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(UTC)


def block_user(user_id: int, *, reason: str = "", blocked_by: int = 0) -> bool:
    """חוסם משתמש. מחזיר ``False`` אם אין DB או שהפעולה נכשלה.

    ``upsert`` ולא ``insert``: חסימה חוזרת מעדכנת את הסיבה במקום
    להיכשל על האינדקס הייחודי. ``blocked_at`` נשמר רק ביצירה, כדי
    שהתאריך המקורי לא ידרס בכל עדכון.

    הקאש מאופס מיד — בלי זה החסימה הייתה נכנסת לתוקף רק אחרי דקה,
    והמפעיל היה מסיק שהפקודה לא עבדה.
    """
    coll = _collection()
    if coll is None:
        return False
    try:
        coll.update_one(
            {"user_id": int(user_id)},
            {
                "$set": {"reason": str(reason or ""), "blocked_by": int(blocked_by or 0)},
                "$setOnInsert": {"user_id": int(user_id), "blocked_at": _now()},
            },
            upsert=True,
        )
    except Exception:
        logger.error("blocked_users: חסימה נכשלה", exc_info=True)
        return False
    _cache.invalidate()
    return True


def unblock_user(user_id: int) -> bool:
    """משחרר משתמש. ``False`` אם לא היה חסום, אין DB, או שהפעולה נכשלה."""
    coll = _collection()
    if coll is None:
        return False
    try:
        result = coll.delete_one({"user_id": int(user_id)})
    except Exception:
        logger.error("blocked_users: שחרור נכשל", exc_info=True)
        return False
    _cache.invalidate()
    return bool(getattr(result, "deleted_count", 0))


def list_blocked(limit: int = 100) -> list[dict]:
    """הרשומות המלאות, לתצוגה. החדשות קודם."""
    coll = _collection()
    if coll is None:
        return []
    try:
        cursor = coll.find({}, {"_id": 0}).sort("blocked_at", -1).limit(int(limit))
        return list(cursor)
    except Exception:
        logger.error("blocked_users: שליפת הרשימה נכשלה", exc_info=True)
        return []


def invalidate_cache() -> None:
    """איפוס יזום. נחוץ בבדיקות, ולמי שכותב ל-DB מבחוץ."""
    _cache.invalidate()
