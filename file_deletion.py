r"""מחיקה רכה של קבצים — השאילתה שהבוט והוובאפ חולקים.

**למה מודול נפרד ולא מתודה ב-**\ ``Repository``\ **.** ``webapp.app`` מחזיק
לקוח מונגו משלו (``get_db``) ואינו עובר דרך ``database.db``, שהוא סינגלטון
על חיבור אחר. פיקסצ'ר הבדיקות ``wired_mongo`` מפנה מחדש **רק** את
``webapp.app``, ולכן ראוט שיקרא ל-``database.db`` יכתוב בבדיקות למסד אחר —
ואולי לאמיתי. הפונקציות כאן מקבלות את ה-collection כפרמטר, וכך שני הצדדים
מריצים את אותו קוד בלי לחלוק חיבור.

**המודול יושב בשורש והוא טהור** — ``dataclasses``, ``datetime``,
``types`` ו-``typing`` ותו לא, בלי Flask ובלי מסד. אותה תבנית של ``file_dates.py``,
ומאותה סיבה: מודול תחת ``database/`` היה גורר את ``database/__init__.py``,
שיוצר ``DatabaseManager()`` גלובלי בזמן הייבוא. כך שני הצדדים מייבאים
ישירות, בלי ה-``try/except`` שנופל ל-no-op בסביבה מינימלית — ומחיקה
שנופלת ל-no-op היא בדיוק הכשל השקט שאסור כאן.

**זהות הקובץ, וזה כל הסיפור.** קובץ הוא ``(user_id, file_name)``; כל גרסה
היא מסמך נפרד. מסכי הרשימה מקבצים לפי ``file_name`` ומוסרים לממשק את
ה-``_id`` של הגרסה **האחרונה בלבד**, ולכן מחיקה שמסננת לפי ``_id`` נגעה
בגרסה אחת והשאירה את שאר הגרסאות פעילות: הקובץ נעלם מהמסך וחזר ברענון,
גרסה אחת אחורה. כאן המזהה משמש **לזיהוי הקובץ בלבד**, והמחיקה עצמה
מתבצעת לפי שם.

**ערוץ הכשל: זריקה.** הפונקציות כאן אינן בולעות שגיאות DB ואינן מחזירות
ערך falsy בכשל. ``files == 0`` פירושו "לא נמצא מה למחוק" ותו לא, והקורא
מתרגם כשל לשגיאה שלו. ראו ``CRITICAL-PATTERNS.md`` K11: פונקציה חדשה
בוחרת ערוץ כשל אחד ומתעדת אותו, כדי שהקורא הבא לא ידווח ✅ על כלום.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any, Iterable, List, Mapping, Sequence, Tuple

__all__ = [
    "RECYCLE_BIN_COLLECTIONS",
    "RECYCLE_BIN_TTL_EXPIRE_AFTER_SECONDS",
    "RECYCLE_BIN_TTL_FIELD",
    "RECYCLE_BIN_TTL_INDEX_NAME",
    "RECYCLE_BIN_TTL_PARTIAL_FILTER",
    "SoftDeleteResult",
    "is_recycle_bin_ttl_index",
    "resolve_owned_file_names",
    "soft_delete_files_by_names",
]


# --- פקיעת הסל: המפרט של אינדקס ה-TTL --------------------------------------
#
# המחיקה הרכה כותבת ``deleted_expires_at``, ואף שורת קוד שלנו אינה מוחקת
# בתאריך הזה — את העבודה עושה אינדקס TTL בצד השרת. זה הבעלים היחיד של
# המפרט שלו: ``DatabaseManager._create_recycle_bin_ttl_indexes`` יוצר אותו
# בכל עלייה, ``/recycle_backfill`` קורא לאותה פונקציה, ו-``/admin/verify-indexes``
# בודק מולו. הוא כאן ולא תחת ``database/`` מאותה סיבה שהמחיקה עצמה כאן:
# הוובאפ מייבא אותו בלי לגרור את ``database/__init__.py``.

#: הקולקציות שהסל יושב בהן. קובץ יכול לשבת בכל אחת מהן, ולכן כל פעולה על
#: הסל מונה את שתיהן.
RECYCLE_BIN_COLLECTIONS: Tuple[str, ...] = ("code_snippets", "large_files")

RECYCLE_BIN_TTL_INDEX_NAME = "deleted_ttl"

#: השדה שכל מסלולי המחיקה הרכה כותבים — ``soft_delete_files_by_names``
#: כאן ו-``Repository.delete_large_file`` — והעמוד ``/trash`` מציג כ"נמחק
#: סופית ב-". הכיוון ``1`` הוא ``pymongo.ASCENDING``; המודול הזה אינו מייבא
#: את pymongo.
RECYCLE_BIN_TTL_FIELD = "deleted_expires_at"

#: ``0``: המסמך נמחק בדיוק בתאריך שבשדה, שהוא התאריך שהמשתמש רואה —
#: *"specify an expireAfterSeconds value of 0"* ב-"Expire Documents at a
#: Specific Clock Time" (https://www.mongodb.com/docs/manual/tutorial/expire-data/).
RECYCLE_BIN_TTL_EXPIRE_AFTER_SECONDS = 0

#: TTL חלקי: נמחק רק מה שבאמת בסל. כל מסלולי השחזור היום מסירים את התאריך,
#: אבל מסלול עתידי ששוכח היה משאיר קובץ פעיל שהאינדקס מוחק — וזו פעולה שאין
#: ממנה חזרה. שוויון מותר ב-``partialFilterExpression``, ו-TTL חלקי נתמך:
#: *"Partial indexes can also be TTL indexes"*
#: (https://www.mongodb.com/docs/manual/core/index-partial/).
RECYCLE_BIN_TTL_PARTIAL_FILTER: Mapping[str, Any] = MappingProxyType({"is_active": False})


def _is_number(value: Any) -> bool:
    # ``bool`` הוא תת-מחלקה של ``int``, ו-``True == 1``; מפתח אינדקס אינו בוליאני.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_recycle_bin_ttl_index(index_info: Any) -> bool:
    """האם שורה מ-``list_indexes()`` היא אינדקס שמרוקן את הסל כפי שהוצהר.

    הבדיקה היא על המפרט ולא על השם: מונגו מוחק לפי המפתח, החלון והמסנן, ואינדקס
    תקין בשם אחר עושה את אותה עבודה. מפתח מורכב אינו מתאים גם אם יש עליו חלון:
    אינדקס TTL הוא חד-שדה (https://www.mongodb.com/docs/manual/core/index-ttl/),
    ומול 8.0.32 נמדד שהשרת **דוחה** יצירה כזו (``OperationFailure`` קוד 67) ולא
    "מתעלם" כמו שהתיעוד מנסח. הבדיקה נשארת בכל זאת, כי השורה מגיעה מחוץ לתהליך.

    המספרים נבדקים בערכם ולא בטיפוס: אינדקס שנוצר מ-mongosh שומר ``1.0`` ולא
    ``1``, ושניהם אותו מפרט.
    """
    if not isinstance(index_info, Mapping):
        return False

    key = index_info.get("key")
    if not isinstance(key, Mapping) or list(key.keys()) != [RECYCLE_BIN_TTL_FIELD]:
        return False
    direction = key.get(RECYCLE_BIN_TTL_FIELD)
    if not _is_number(direction) or direction != 1:
        return False

    expire = index_info.get("expireAfterSeconds")
    if not _is_number(expire) or expire != RECYCLE_BIN_TTL_EXPIRE_AFTER_SECONDS:
        return False

    partial = index_info.get("partialFilterExpression")
    if not isinstance(partial, Mapping):
        return False
    return dict(partial) == dict(RECYCLE_BIN_TTL_PARTIAL_FILTER)


@dataclass(frozen=True)
class SoftDeleteResult:
    """מה נמחק בפועל — קבצים ומסמכים, בנפרד.

    שני המספרים נחוצים ואינם מתחלפים: המשתמש סופר **קבצים**
    (``multi-select.js`` מדפיס "N קבצים הועברו לסל"), והמסד מונה
    **מסמכי גרסה**. קובץ אחד בן שש גרסאות הוא ``files=1, versions=6``.
    """

    file_names: List[str] = field(default_factory=list)
    versions: int = 0

    @property
    def files(self) -> int:
        return len(self.file_names)

    def __bool__(self) -> bool:
        return bool(self.file_names)


def resolve_owned_file_names(
    collection: Any, user_id: int, object_ids: Sequence[Any]
) -> Tuple[List[str], List[Any]]:
    """ממפה מזהי גרסה לשמות הקבצים שלהם, מסונן לפי בעלות.

    מחזיר ``(file_names, found_ids)``. הבעלות נאכפת **בשאילתה**, ולא
    בבדיקה נפרדת שאפשר לשכוח: מזהה של משתמש אחר פשוט לא חוזר, ולכן
    ``found_ids`` קצר מהקלט והקורא יכול להחזיר 404.

    ``file_names`` ייחודי ושומר על סדר ההופעה, כי שני מזהים של אותו קובץ
    הם קובץ אחד — וספירה של "כמה קבצים" חייבת לספור קבצים.
    """
    ids = list(dict.fromkeys(object_ids))
    if not ids:
        return [], []

    names: List[str] = []
    found: List[Any] = []
    for doc in collection.find(
        {"_id": {"$in": ids}, "user_id": user_id},
        {"_id": 1, "file_name": 1},
    ):
        found.append(doc.get("_id"))
        name = (doc.get("file_name") or "").strip()
        if name and name not in names:
            names.append(name)
    return names, found


def soft_delete_files_by_names(
    collection: Any,
    user_id: int,
    file_names: Iterable[str],
    *,
    ttl_days: int,
    now: datetime | None = None,
) -> SoftDeleteResult:
    """מעביר לסל את **כל** הגרסאות הפעילות של כל שם קובץ ברשימה.

    ``ttl_days`` נכפף למינימום 1: ``deleted_expires_at`` בעבר היה גורם
    ל-TTL של מונגו למחוק את הקובץ מיידית, בלי שהמשתמש יוכל לשחזר.

    ספירת הקבצים נלקחת מ-``distinct`` **לפני** העדכון, כי אחריו השמות
    כבר אינם ``is_active: True`` ואי אפשר לספור אותם. מגבלה ידועה: אם
    בקשה מקבילה מוחקת את אותו שם בדיוק בין שתי הפעולות, המונה יספור
    אותו כאן וגם שם. התוצאה במסד נכונה בשני המקרים — הקובץ בסל — וזה
    מונה תצוגה, לא החלטה.
    """
    names = [n for n in dict.fromkeys(str(n or "").strip() for n in file_names) if n]
    if not names:
        return SoftDeleteResult()

    now = now or datetime.now(timezone.utc)
    expires_at = now + timedelta(days=max(1, int(ttl_days)))

    live: List[str] = list(
        collection.distinct(
            "file_name",
            {"user_id": user_id, "file_name": {"$in": names}, "is_active": True},
        )
    )
    if not live:
        return SoftDeleteResult()

    result = collection.update_many(
        {"user_id": user_id, "file_name": {"$in": live}, "is_active": True},
        {
            "$set": {
                # ``deleted_at`` מתעד את המחיקה, וסל המיחזור ממיין לפיו.
                # ``updated_at`` נשאר על העריכה האחרונה בפועל — מחיקה רכה
                # היא תווית על הקובץ ולא שינוי בו.
                "is_active": False,
                "deleted_at": now,
                # השדה שאינדקס ה-TTL קורא — ראו ``RECYCLE_BIN_TTL_FIELD``.
                RECYCLE_BIN_TTL_FIELD: expires_at,
            }
        },
    )
    versions = int(getattr(result, "modified_count", 0) or 0)
    if not versions:
        # השאילתה מצאה שמות פעילים ובכל זאת לא שינתה דבר — לא לדווח
        # מחיקה שלא קרתה. ראו K11 §4.
        return SoftDeleteResult()
    return SoftDeleteResult(file_names=list(live), versions=versions)
