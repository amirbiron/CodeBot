r"""מחיקה רכה של קבצים — השאילתה שהבוט והוובאפ חולקים.

**למה מודול נפרד ולא מתודה ב-**\ ``Repository``\ **.** ``webapp.app`` מחזיק
לקוח מונגו משלו (``get_db``) ואינו עובר דרך ``database.db``, שהוא סינגלטון
על חיבור אחר. פיקסצ'ר הבדיקות ``wired_mongo`` מפנה מחדש **רק** את
``webapp.app``, ולכן ראוט שיקרא ל-``database.db`` יכתוב בבדיקות למסד אחר —
ואולי לאמיתי. הפונקציות כאן מקבלות את ה-collection כפרמטר, וכך שני הצדדים
מריצים את אותו קוד בלי לחלוק חיבור.

**המודול יושב בשורש והוא טהור** — ``dataclasses``, ``datetime``,
``types``, ``typing`` ו-``ttl_index`` (מודול שורש טהור אחר) ותו לא, בלי Flask
ובלי מסד. אותה תבנית של ``file_dates.py``,
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

from ttl_index import is_ttl_index

__all__ = [
    "LARGE_FILES_COLLECTION",
    "RECYCLE_BIN_COLLECTIONS",
    "RECYCLE_BIN_GROUPED_FIELDS",
    "RECYCLE_BIN_TTL_EXPIRE_AFTER_SECONDS",
    "RECYCLE_BIN_TTL_FIELD",
    "RECYCLE_BIN_TTL_INDEX_NAME",
    "RECYCLE_BIN_TTL_PARTIAL_FILTER",
    "RestoreConflict",
    "SINGLE_ACTIVE_COLLECTIONS",
    "SoftDeleteResult",
    "is_recycle_bin_ttl_index",
    "purge_files_by_names",
    "recycle_bin_count_stages",
    "recycle_bin_group_stages",
    "recycle_bin_page_stages",
    "recycle_bin_rows_pipeline",
    "resolve_owned_file_names",
    "resolve_trashed_file_names",
    "restore_files_by_names",
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

#: אוסף הקבצים הגדולים, בשמו. כלל שתלוי בזהות האוסף נכתב מולו ולא מול מיקום
#: ב-:data:`RECYCLE_BIN_COLLECTIONS` — סדר חדש של הטאפל היה מחיל בשקט את
#: הכלל על האוסף הלא נכון (ראו :data:`SINGLE_ACTIVE_COLLECTIONS`).
LARGE_FILES_COLLECTION = "large_files"

#: הקולקציות שהסל יושב בהן. קובץ יכול לשבת בכל אחת מהן, ולכן כל פעולה על
#: הסל מונה את שתיהן.
RECYCLE_BIN_COLLECTIONS: Tuple[str, ...] = ("code_snippets", LARGE_FILES_COLLECTION)

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


def is_recycle_bin_ttl_index(index_info: Any) -> bool:
    """האם שורה מ-``list_indexes()`` היא אינדקס שמרוקן את הסל כפי שהוצהר.

    הבדיקה עצמה — מפרט ולא שם, מספרים לפי ערך, מפתח חד-שדה — יושבת ב-
    :func:`ttl_index.is_ttl_index`, שמשרת גם את אינדקס ה-TTL של העלאות ה-MCP.
    כאן רק המפרט של הסל.
    """
    return is_ttl_index(
        index_info,
        field=RECYCLE_BIN_TTL_FIELD,
        expire_after_seconds=RECYCLE_BIN_TTL_EXPIRE_AFTER_SECONDS,
        partial_filter=RECYCLE_BIN_TTL_PARTIAL_FILTER,
    )


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


# --- תצוגת הסל: שורה אחת לכל קובץ -----------------------------------------
#
# אותה זהות שהמחיקה עובדת לפיה, גם בקריאה. עד אוקטובר 2026 שני מסכי הסל
# הציגו שורה לכל **מסמך גרסה**: קובץ בן שש גרסאות תפס שש שורות עם אותו שם,
# אותו תאריך מחיקה ואותו תאריך תפוגה. ולקבצים גדולים אין ``version`` כלל
# (``database/models.py``, ``LargeFile``), ולכן השורות שלהם היו חסרות כל
# מבדיל — ו-``Repository.save_large_file`` מוריד את הקודם לסל בכל שמירה
# מחדש, כך שזה המצב הרגיל ולא קצה.

#: השדות שהשורה המקובצת מצהירה עליהם, והשדות שנדרשים כדי לחשב אותם.
#: ההיטלה היא **הכללה** ומונה אותם במפורש, ולא החרגה של הכבדים: רשימה
#: מפורשת אינה מכניסה שדה חדש לתשובה מעצמה כשהסכימה גדלה.
RECYCLE_BIN_GROUPED_FIELDS: Tuple[str, ...] = (
    "file_name",
    "programming_language",
    "deleted_at",
    RECYCLE_BIN_TTL_FIELD,
    "version",
)


def recycle_bin_group_stages(user_id: int, *, source: str) -> List[dict]:
    r"""שלבי "שורה אחת לכל קובץ בסל", לקולקציה אחת.

    מחזיר שלבים בלבד — בלי ``$sort`` סופי, ``$skip`` או ``$limit`` — כדי
    שהקורא יוסיף את הזנב שלו, בדיוק כמו ``_latest_version_per_file_stages``
    ב-``webapp/app.py``. ``source`` הוא שם הקולקציה, מתוך
    :data:`RECYCLE_BIN_COLLECTIONS`.

    **סדר השלבים הוא כל העניין, ומאותה סיבה שם: רק** ``$match`` **רשאי לבוא
    לפני ההיטלה.** שלב אחר באמצע — ``$addFields`` למשל — משאיר את ההיטלה
    כשלב בצינור, והמיון והקיבוץ שאחריה עדיין נספרים על המסמכים המלאים.
    הנימוק, והמדידה על הקלאסטר שמאחוריו, יושבים ב-docstring של
    ``_latest_version_per_file_stages`` ב-``webapp/app.py`` — שם הבעלים
    של הכלל הזה, ואין טעם בעותק שני של אותם מספרים. ולכן גם מסמן
    הקולקציה נכנס **בתוך** ההיטלה ולא בשלב נפרד, ודווקא כ-``$literal``:
    מחרוזת חשופה ב-``$project`` נקראת כשם שדה ולא כערך.

    מה שנמדד כאן, מקומית על mongod 7.0.14 (6.10.2026): ה-``$match``
    נתפס על ``idx_snippets_latest_version`` ב-``IXSCAN``, והצינור כולו
    סיים ב-``usedDisk: false``. המודד הוא
    ``scripts/measure_recycle_bin_pipeline.py``. גודל המיון **לא** נמדד
    כאן בצורה עקבית, ולכן אין עליו טענה — המדידה הקנונית היא זו
    שב-``webapp/app.py``.

    **ובלי** ``$first: "$$ROOT"``\ **, בניגוד למסכי הקבצים.** ``$$ROOT`` נוגע
    בכל השדות, ולכן הורדת השדות הכבדים לפניו הייתה משנה את התוצאה במקום
    להקטין אותה. האקומולטורים כאן מפורשים, וכל אחד מהם מצהיר בדיוק מה
    השורה אומרת — וזה גם מה שמאפשר להוריד את גוף הקובץ כבר ב-``$match``.

    **למה ה-**\ ``_id``\ ** מורכב משם ומקולקציה.** אותו ``file_name`` יכול
    לשבת גם ב-``code_snippets`` וגם ב-``large_files`` — אלה שתי ישויות
    נפרדות, ועם מפתח של שם לבד הן היו נדחסות לשורה אחת.

    **ולמה** ``$min`` **על שני התאריכים.** אינדקס ה-TTL מוחק **מסמך-מסמך**
    (ראו :data:`RECYCLE_BIN_TTL_PARTIAL_FILTER`), ואין בו שום מושג של קובץ.
    כשגרסאות של אותו שם נמחקו בזמנים שונים — מה שקורה ב-
    ``Repository.save_large_file`` וברצף מחיקה-שמירה-מחיקה — התאריך
    **המוקדם** הוא הרגע שבו הקובץ מפסיק להיות שלם, ולכן הוא מה שהשורה
    מצהירה. ``$max`` היה מבטיח שחזור מלא עד תאריך שבו חלק מההיסטוריה כבר
    נמחקה.
    """
    projection: dict = {field_name: 1 for field_name in RECYCLE_BIN_GROUPED_FIELDS}
    projection["_source"] = {"$literal": source}
    return [
        {"$match": {"user_id": user_id, "is_active": False}},
        {"$project": projection},
        # נותן ל-``$first`` תוצאה דטרמיניסטית: הגרסה הגבוהה מייצגת את הקובץ.
        # ל-``large_files`` אין ``version``, וחסר ממוין לפני כל ערך — כלומר
        # שם הסדר נקבע ב-``_id``, שהוא עדיין יציב בין קריאות.
        {"$sort": {"file_name": 1, "version": -1, "_id": -1}},
        {
            "$group": {
                "_id": {"name": "$file_name", "src": "$_source"},
                "versions": {"$sum": 1},
                "deleted_at": {"$min": "$deleted_at"},
                "expires_at": {"$min": "$" + RECYCLE_BIN_TTL_FIELD},
                "language": {"$first": "$programming_language"},
                # הכתובת שהשורה נושאת. מזהה של גרסה מייצגת, שהשרת מתרגם
                # בחזרה לשם — ראו ``resolve_trashed_file_names``. שם קובץ
                # ב-``callback_data`` של טלגרם היה חורג מהמכסה ומתנגש
                # בתו ההפרדה.
                "action_id": {"$first": "$_id"},
            }
        },
    ]


def recycle_bin_rows_pipeline(user_id: int) -> List[dict]:
    r"""הצינור המלא של שורות הסל — שתי הקולקציות, מקובצות, בקריאה אחת.

    ``$unionWith`` מצרף את ``large_files``, וכל ענף נושא את זוג
    ``$match``\ +\ ``$project`` שלו — כך הצמידות נשמרת בשניהם ולא רק
    בשורש. אין dedup ואין דרישה ל-``_id`` ייחודי בין הקולקציות, וזה בסדר:
    ``_id`` אינו מפתח הקיבוץ.

    **רוויזיה של קובץ שקיים אינה מוצגת.** ``Repository.save_large_file``
    מוריד את הגרסה הקודמת לסל בכל שמירה מחדש, ולכן לקובץ גדול **חי** יש
    דרך קבע מסמכים בסל. סל מיחזור מציג קבצים שנמחקו, לא היסטוריית
    רוויזיות, ולכן השלבים האחרונים מוציאים כל שם שיש לו גרסה פעילה.
    ה-TTL מנקה אותן מהמסד כרגיל — ההסתרה היא בתצוגה בלבד, ואינה מוחקת
    דבר.

    ההוצאה הזו עושה עוד שתי עבודות: היא מייתרת את השאלה מה עושה שחזור
    כשכבר קיים קובץ פעיל באותו שם — מצב שבו ``get_large_file`` היה בוחר
    שרירותית בין שני מסמכים פעילים, בלי שגיאה — והיא מסתירה גם רוויזיות
    של ``code_snippets`` שנוצרו ממסלול חריג כזה.

    **וההוצאה היא לפי הקולקציה של השורה.** אותו שם יכול לחיות ב-
    ``code_snippets`` ולהיות מחוק ב-``large_files``; בדיקה לפי שם לבדו
    הייתה מעלימה את השורה המחוקה. התנאי הזה יושב ב-``$set`` שאחרי שני
    ה-``$lookup`` ולא **בתוכם**: בתוכם הוא השוואה בין משתנה לקבוע, ובשורות
    שבהן היא שקר מונגו סורק את האוסף כולו. הפירוט והמספרים בהערה שם,
    והסקריפט שמדד הוא ``scripts/measure_recycle_bin_pipeline.py``.
    """
    return [
        *recycle_bin_group_stages(user_id, source=RECYCLE_BIN_COLLECTIONS[0]),
        {
            "$unionWith": {
                "coll": RECYCLE_BIN_COLLECTIONS[1],
                "pipeline": recycle_bin_group_stages(
                    user_id, source=RECYCLE_BIN_COLLECTIONS[1]
                ),
            }
        },
        # יש לשם הזה גרסה פעילה באותה קולקציה? אם כן — זו היסטוריה ולא
        # מחיקה. ה-``let`` נדרש כי בתוך ``pipeline`` של ``$lookup`` אין
        # גישה לשדות המסמך החיצוני אלא דרכו.
        #
        # ‏``user_id`` ו-``is_active`` הם שוויונות רגילים, והשם עובר דרך
        # ``$expr`` כי הוא מגיע מה-``let``. **האינדקס משמש גם את השם:** לפי
        # התיעוד של ``$lookup``, ``$eq`` בתוך ``$expr`` משתמש באינדקס של אוסף
        # ה-``from`` כשה-``let`` נפתר לקבוע, והאינדקס אינו multikey, חלקי או
        # sparse (https://www.mongodb.com/docs/manual/reference/operator/aggregation/lookup/).
        # שני האינדקסים כאן — ``idx_snippets_latest_version`` ו-
        # ``idx_large_files_user_active_name`` — אינם אף אחד מהשלושה. גם צורה
        # שבה שלושת התנאים בתוך ``$expr`` נמדדה זהה.
        #
        # מה שאסור כאן הוא **השוואה בין משתנה לקבוע** — ראו ההערה על ה-``$set``
        # שאחרי. נמדד ב-6.10.2026 על mongod 7.0.14 ועל 8.0.30, באינדקסים של
        # הפרודקשן, בזרע של ``scripts/measure_recycle_bin_pipeline.py`` (שמות
        # בסל שלחלקם יש גרסה פעילה): ‏``totalKeysExamined`` שווה בדיוק למספר
        # ההתאמות, ו-``collectionScans`` הוא 0.
        *(
            {
                "$lookup": {
                    "from": collection_name,
                    "let": {"n": "$_id.name"},
                    "pipeline": [
                        {
                            "$match": {
                                "user_id": user_id,
                                "is_active": True,
                                "$expr": {"$eq": ["$file_name", "$$n"]},
                            }
                        },
                        {"$limit": 1},
                        {"$project": {"_id": 1}},
                    ],
                    "as": "_alive_" + collection_name,
                }
            }
            for collection_name in RECYCLE_BIN_COLLECTIONS
        ),
        # כל שורה נמדדת מול הקולקציה **שלה**. התנאי הזה היה בתוך שני
        # ה-``$lookup`` (``$eq: ["$$src", <הקולקציה>]``) — השוואה בין משתנה
        # לקבוע, בלי שדה. בשורה של האוסף **האחר** היא שקר, כל ה-``$and``
        # שקר, ומונגו סרק את האוסף כולו לשורה הזו. באותה מדידה: 20 סריקות
        # אוסף ב-``code_snippets`` ו-60 ב-``large_files`` — אחת לכל שורה
        # מהאוסף האחר — ו-``indexesUsed`` עדיין הציג את האינדקס, כי הוא שימש
        # את שאר השורות. ``$lookup`` רץ בכל מקרה, ולכן אין בהוצאת התנאי לכאן
        # עלות נוספת.
        {
            "$set": {
                "_alive": {
                    "$size": {
                        "$cond": [
                            {"$eq": ["$_id.src", RECYCLE_BIN_COLLECTIONS[0]]},
                            "$_alive_" + RECYCLE_BIN_COLLECTIONS[0],
                            "$_alive_" + RECYCLE_BIN_COLLECTIONS[1],
                        ]
                    }
                }
            }
        },
        {"$match": {"_alive": 0}},
        {
            "$project": {
                "_id": "$action_id",
                "file_name": "$_id.name",
                "source": "$_id.src",
                "language": 1,
                "versions": 1,
                "deleted_at": 1,
                "expires_at": 1,
                # שדה חסר משתווה ל-``null``, ו-``null`` נמוך מ-``Date``
                # בסדר ההשוואה של BSON — ולכן שורה בלי ``deleted_at``
                # הייתה שוקעת מתחת לכולן. מפתח מיון מפורש, כמו
                # ``_timeline_latest_files`` בוובאפ.
                "sort_at": {"$ifNull": ["$deleted_at", datetime.min.replace(tzinfo=timezone.utc)]},
            }
        },
    ]


def recycle_bin_page_stages(*, page: int, per_page: int) -> List[dict]:
    """זנב העימוד — בשאילתה ולא בפייתון.

    שני מסכי הסל שלפו עד אוקטובר 2026 את **כל** הסל לזיכרון, מיינו שם
    וחתכו ``combined[start:end]``. ``$skip`` שלילי הוא שגיאת שרת ולא 0
    שקט, ולכן ההצמדה כאן ולא אצל הקורא.
    """
    page = max(1, int(page))
    per_page = max(1, int(per_page))
    return [
        {"$sort": {"sort_at": -1, "_id": -1}},
        {"$skip": (page - 1) * per_page},
        {"$limit": per_page},
    ]


def recycle_bin_count_stages() -> List[dict]:
    """ספירת **קבצים**, לא מסמכי גרסה.

    אותה תבנית שעמוד הקבצים מריץ: אותם שלבים בדיוק ועוד ``$count``, כדי
    שהמספר שהכותרת מציגה יספור את מה שמוצג.
    """
    return [{"$count": "total"}]


def resolve_trashed_file_names(
    collection: Any, user_id: int, object_ids: Sequence[Any]
) -> Tuple[List[str], List[Any]]:
    r"""כמו :func:`resolve_owned_file_names`, אבל על מה שיושב בסל.

    מחזיר ``(file_names, found_ids)``. הבעלות **ו**\ ``is_active: False``
    נאכפים בשאילתה: מזהה של משתמש אחר, או של קובץ פעיל, פשוט אינו חוזר —
    ולכן ``found_ids`` קצר מהקלט והקורא יכול להחזיר 404. התיחום ל"בסל" הוא
    מה שמונע מפעולת סל לגעת בקובץ חי.
    """
    ids = list(dict.fromkeys(object_ids))
    if not ids:
        return [], []

    names: List[str] = []
    found: List[Any] = []
    for doc in collection.find(
        {"_id": {"$in": ids}, "user_id": user_id, "is_active": False},
        {"_id": 1, "file_name": 1},
    ):
        found.append(doc.get("_id"))
        name = (doc.get("file_name") or "").strip()
        if name and name not in names:
            names.append(name)
    return names, found


def _trashed_ids_for_names(
    collection: Any, user_id: int, names: Sequence[str]
) -> List[Any]:
    """מזהי **כל** מסמכי הסל של השמות האלה.

    נאספים **לפני** הפעולה: אחרי ``delete_many`` אין מה לאסוף, ואחרי
    ``update_many`` המסמכים כבר אינם ``is_active: False``. הם נדרשים כדי
    שניקוי הצ'אנקים והסימון לאינדוקס מחדש יקבלו את כל הגרסאות ולא אחת.

    **ממוינים, והראשון הוא הגרסה האחרונה.** הסדר הוא של
    ``database.manager.is_latest_active_snippet`` — הבעלים של "מי הגרסה
    האחרונה", ושם גם ה-worker מכריע אם לעבד מסמך. ``restore_files_by_names``
    מבטיח לקורא שהמזהה הראשון הוא זה שכדאי לסמן; בלי המיון זה היה המסמך
    הראשון בסדר הטבעי — בדרך כלל הגרסה **הישנה**, שה-worker מסיים באפס
    צ'אנקים, והקובץ המשוחזר לא היה חוזר לחיפוש הסמנטי לעולם.
    """
    return [
        doc["_id"]
        for doc in collection.find(
            {"user_id": user_id, "file_name": {"$in": list(names)}, "is_active": False},
            {"_id": 1},
            sort=[("version", -1), ("updated_at", -1), ("_id", -1)],
        )
    ]


#: אוספים שבהם לכל שם קובץ יש **לכל היותר מסמך פעיל אחד**. ב-``code_snippets``
#: כל גרסה היא מסמך פעיל, והשחזור מחזיר את כולן. ב-``large_files`` מסמך הוא
#: הקובץ: ``Repository.save_large_file`` מוריד את הקודם לסל בכל שמירה מחדש,
#: והקוראים (``get_large_file``, ``get_user_large_files``) מניחים פעיל אחד —
#: שניים היו מציגים את הקובץ פעמיים ומגישים רוויזיה שרירותית.
SINGLE_ACTIVE_COLLECTIONS: frozenset = frozenset({LARGE_FILES_COLLECTION})


class RestoreConflict(Exception):
    """לשם הזה כבר יש מסמך פעיל באוסף שמחזיק פעיל אחד לכל שם.

    ערוץ נפרד מ"לא נמצא מה לשחזר" (``([], [])``), כי לקורא יש מה לומר
    עליו: הקובץ קיים, והשחזור היה יוצר עותק שני שלו. ראו
    :data:`SINGLE_ACTIVE_COLLECTIONS`.
    """

    def __init__(self, file_name: str) -> None:
        super().__init__(file_name)
        self.file_name = file_name


def _restore_latest_revision(
    collection: Any, user_id: int, names: Sequence[str]
) -> Tuple[List[str], List[Any]]:
    """שחזור באוסף של פעיל-אחד-לכל-שם: הרוויזיה שהייתה חיה אחרונה, לכל שם.

    **הבדיקה לפני כל כתיבה:** שם אחד שכבר פעיל עוצר את כולם, כדי ששחזור
    של כמה שמות לא ייעצר באמצע.

    **``deleted_at`` ולא ``updated_at``.** שחזור מגיבוי מעביר ``updated_at``
    היסטורי (``services/personal_backup_service.py`` ← ``save_large_file``,
    שמרענן אותו רק כשיש קובץ פעיל), ולכן קובץ שנמחק, שוחזר מגיבוי ישן ונמחק
    שוב היה נבחר לפי התוכן הלא נכון. כל מסלול העברה לסל כותב ``deleted_at``,
    והרוויזיה שנמחקה אחרונה היא זו שהייתה חיה אחרונה. ``created_at`` אינו
    מבחין בכלל: הוא עובר בירושה בין רוויזיות.

    השאר נשארות בסל. הצינור מסתיר אותן מרגע שלשם יש מסמך פעיל
    (:func:`recycle_bin_rows_pipeline`), וה-TTL מוחק אותן כרגיל.

    **חלון שנשאר פתוח, וסגירתו מתוכננת ל-PR המשך:** שמירה מקבילה של אותו
    שם בין הבדיקה לעדכון עדיין יכולה ליצור שני פעילים, כי הבדיקה כאן היא
    בקוד. הסגירה מהשורש היא במסד: אינדקס ייחודי חלקי על ``large_files`` —
    ייחודי על ``(user_id, file_name)`` עם ``partialFilterExpression`` של
    ``{"is_active": True}`` — שדוחה עותק פעיל שני בכל מסלול כתיבה, לא רק
    כאן. אותו מנגנון כבר קיים בלוחות הפתקים (``one_default_per_user`` ב-
    ``webapp/sticky_notes_api.py``). לפני שהוא נוצר, שני תנאים:

    1. שאילתה לקריאה בלבד שסופרת אם כבר יש היום ב-``large_files`` שמות עם
       יותר ממסמך פעיל אחד — אינדקס ייחודי לא נוצר על נתונים שמפרים אותו.
    2. היצירה נבדקת **בקריאה חוזרת** של האינדקסים: ``safe_create_index``
       מחזיר ``False`` ואינו זורק, ולכן אינדקס שנכשל בגלל כפילויות קיימות
       פשוט לא ייווצר, בשקט (``BY-STACK/mongodb.md`` דפוס 9 ב-
       ``amir-bug-patterns``).
    """
    for name in names:
        alive = collection.find_one(
            {"user_id": user_id, "file_name": name, "is_active": True}, {"_id": 1}
        )
        if alive is not None:
            raise RestoreConflict(name)

    restored_names: List[str] = []
    restored_ids: List[Any] = []
    for name in names:
        latest = collection.find_one(
            {"user_id": user_id, "file_name": name, "is_active": False},
            {"_id": 1},
            sort=[("deleted_at", -1), ("_id", -1)],
        )
        if latest is None:
            continue
        res = collection.update_one(
            {"_id": latest["_id"], "user_id": user_id, "is_active": False},
            {
                "$set": {"is_active": True},
                "$unset": {"deleted_at": "", RECYCLE_BIN_TTL_FIELD: ""},
            },
        )
        if int(getattr(res, "modified_count", 0) or 0):
            restored_names.append(name)
            restored_ids.append(latest["_id"])
    return restored_names, restored_ids


def restore_files_by_names(
    collection: Any, user_id: int, file_names: Iterable[str], *, source: str
) -> Tuple[List[str], List[Any]]:
    r"""מחזיר מהסל את הקבצים שברשימה — ומה "מחזיר" תלוי באוסף, לפי ``source``:

    - **``code_snippets``** — **כל** הגרסאות שבסל. זה ההופכי של
      :func:`soft_delete_files_by_names`, ובמכוון: המחיקה מורידה את כל
      הגרסאות יחד, ולכן שחזור שמחזיר אחת היה משאיר קובץ עם היסטוריה קטועה —
      התאום ההפוך של הבאג שהמחיקה תוקנה ממנו.
    - **אוסף שב-:data:`SINGLE_ACTIVE_COLLECTIONS`** (``large_files``) —
      **רוויזיה אחת** לכל שם, זו שנמחקה אחרונה; השאר נשארות בסל. ראו
      :func:`_restore_latest_revision`.

    מחזיר ``(restored_names, restored_ids)``, והמזהים הם של כל המסמכים
    שחזרו — הם נדרשים לקורא, אבל **לא** כדי לסמן את כולם לאינדוקס סמנטי
    מחדש. ``services/embedding_worker`` בודק ``is_latest_active_snippet``
    ומסיים כל גרסה שאינה האחרונה עם אפס צ'אנקים, ולכן סימון של N גרסאות
    קונה N סבבי worker ואפס תוצאה. הקורא מסמן את הגרסה הגבוהה בלבד — והיא
    ``restored_ids[0]``, כי :func:`_trashed_ids_for_names` ממיין.

    ``source`` הוא שם האוסף, מתוך :data:`RECYCLE_BIN_COLLECTIONS`, והוא
    **חובה**: באוסף שב-:data:`SINGLE_ACTIVE_COLLECTIONS` חוזרת רוויזיה אחת
    בלבד, ראו :func:`_restore_latest_revision`.

    ערוץ הכשל: זריקה — ובכללה :class:`RestoreConflict`, כשלשם כבר יש מסמך
    פעיל באוסף כזה. רשימה ריקה פירושה "לא נמצא מה לשחזר" ותו לא.
    """
    names = [n for n in dict.fromkeys(str(n or "").strip() for n in file_names) if n]
    if not names:
        return [], []

    if source in SINGLE_ACTIVE_COLLECTIONS:
        return _restore_latest_revision(collection, user_id, names)

    ids = _trashed_ids_for_names(collection, user_id, names)
    if not ids:
        return [], []

    res = collection.update_many(
        {"user_id": user_id, "file_name": {"$in": names}, "is_active": False},
        {
            "$set": {"is_active": True},
            # התאריכים מוסרים, ולא רק מתעלמים מהם: אינדקס ה-TTL מסנן
            # ``is_active: False``, אבל השארת ``deleted_expires_at`` על קובץ
            # פעיל היא מלכודת למסלול הבא שישכח את המסנן.
            "$unset": {"deleted_at": "", RECYCLE_BIN_TTL_FIELD: ""},
        },
    )
    if not int(getattr(res, "modified_count", 0) or 0):
        # נמצאו מסמכים בסל ובכל זאת לא שונה דבר — לא לדווח שחזור שלא קרה.
        # ראו ``bugbot-rules/return-value-failure-unchecked.md`` §4
        # ב-``amir-bug-patterns``.
        return [], []
    return names, ids


def purge_files_by_names(
    collection: Any, user_id: int, file_names: Iterable[str]
) -> Tuple[List[str], List[Any]]:
    r"""מוחק לצמיתות את **כל** הגרסאות של כל שם קובץ ברשימה.

    ‏``is_active: False`` במסנן הוא שומר ולא קישוט: בלעדיו הפעולה הזו הייתה
    מוחקת קובץ פעיל, ואין ממנה חזרה.

    מחזיר ``(purged_names, purged_ids)``, והמזהים נאספים לפני המחיקה כדי
    שניקוי הצ'אנקים יוכל לרוץ עליהם אחריה — ומוחזרים רק אלה שבאמת נמחקו.

    ⚠️ **הקורא חייב להעביר אותם ל-**\ ``delete_snippet_chunks`` **כ-**\
    ``snippet_ids``\ **, לא כ-**\ ``file_names``\ **.** הצורה שלפי שם
    מתרגמת שם למזהים בשאילתה משלה **בלי** לסנן ``is_active``, ולכן בקובץ
    שחלק מגרסאותיו פעילות היא הייתה מוחקת גם את הצ'אנקים של הגרסאות
    החיות. המזהים שכאן מתוחמים ל"בסל" בשאילתה.

    ערוץ הכשל: זריקה.
    """
    names = [n for n in dict.fromkeys(str(n or "").strip() for n in file_names) if n]
    if not names:
        return [], []

    ids = _trashed_ids_for_names(collection, user_id, names)
    if not ids:
        return [], []

    # ``_id`` במסנן: המחיקה תחומה למסמכים שנאספו, ולכן ``deleted_count``
    # משתווה ל-``len(ids)`` בדיוק כשכולם נמחקו.
    res = collection.delete_many(
        {
            "_id": {"$in": ids},
            "user_id": user_id,
            "file_name": {"$in": names},
            "is_active": False,
        }
    )
    deleted = int(getattr(res, "deleted_count", 0) or 0)
    if not deleted:
        return [], []
    if deleted < len(ids):
        # מזהה שלא נמחק — גרסה ששוחזרה בין האיסוף למחיקה — **אינו** מוחזר:
        # הקורא שולח את הרשימה ל-``delete_snippet_chunks``, ושם הוא היה מוחק
        # את הצ'אנקים של גרסה חיה. קוראים מה עוד קיים, ולא מניחים.
        survivors = {
            doc["_id"]
            for doc in collection.find({"_id": {"$in": ids}}, {"_id": 1})
        }
        ids = [oid for oid in ids if oid not in survivors]
        if not ids:
            return [], []
    return names, ids
