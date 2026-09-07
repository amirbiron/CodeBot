r"""מחיקה רכה של קבצים — השאילתה שהבוט והוובאפ חולקים.

**למה מודול נפרד ולא מתודה ב-**\ ``Repository``\ **.** ``webapp.app`` מחזיק
לקוח מונגו משלו (``get_db``) ואינו עובר דרך ``database.db``, שהוא סינגלטון
על חיבור אחר. פיקסצ'ר הבדיקות ``wired_mongo`` מפנה מחדש **רק** את
``webapp.app``, ולכן ראוט שיקרא ל-``database.db`` יכתוב בבדיקות למסד אחר —
ואולי לאמיתי. הפונקציות כאן מקבלות את ה-collection כפרמטר, וכך שני הצדדים
מריצים את אותו קוד בלי לחלוק חיבור.

**המודול יושב בשורש והוא טהור** — ``dataclasses``, ``datetime``
ו-``typing`` ותו לא, בלי Flask ובלי מסד. אותה תבנית של ``file_dates.py``,
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
from typing import Any, Iterable, List, Sequence, Tuple

__all__ = [
    "SoftDeleteResult",
    "resolve_owned_file_names",
    "soft_delete_files_by_names",
]


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
                "deleted_expires_at": expires_at,
            }
        },
    )
    versions = int(getattr(result, "modified_count", 0) or 0)
    if not versions:
        # השאילתה מצאה שמות פעילים ובכל זאת לא שינתה דבר — לא לדווח
        # מחיקה שלא קרתה. ראו K11 §4.
        return SoftDeleteResult()
    return SoftDeleteResult(file_names=list(live), versions=versions)
