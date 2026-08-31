"""מיגרציית ``created_at`` — "נוצר" של קובץ שייך לקובץ הלוגי, לא לגרסה.

הרקע: כל עריכת תוכן יוצרת מסמך גרסה חדש, ועד התיקון ההורשה ב-
``save_code_snippet`` השדה ``created_at`` שלו נקבע לרגע העריכה. ה-UI מציג
תמיד את מסמך הגרסה האחרונה, ולכן "נוצר" זז בכל עריכה. התיקון קדימה חי
בקוד; המיגרציה כאן מיישרת את המצב הקיים — בלעדיה קובץ ותיק יוריש הלאה
את התאריך השגוי שכבר יש לו.

מה היא עושה: לכל ``(user_id, file_name)`` פעיל, קובעת לכל מסמך שנמצא
ב**גרסה הגבוהה ביותר** ``created_at = המוקדם מבין כל גרסאות הקובץ``.
גרסאות ישנות אינן נגועות — תאריכי ההיסטוריה שלהן נשארים כמות שהם.

**למה "כל מסמך בגרסה הגבוהה" ולא "המסמך האחרון":** מרוץ כתיבה ידוע
מייצר שני מסמכים עם אותו ``version``, והאפליקציה בוחרת ביניהם עם
``{"$sort": {"file_name": 1, "version": -1}}`` בלי שובר-שוויון
(``database/repository.py`` — שבעה מופעים) — כלומר הבחירה אינה יציבה.
לכן ``$first`` כאן היה מתקן מסמך שאולי אינו זה שמוצג. תיקון של כל
התאומים מוציא את הניחוש מהמשוואה.

מופעלת מעמוד האדמין ``/admin/migrations/created-at`` בלבד: dry-run
לקריאה בלבד, ואחריו החלה מפורשת **באצוות** — כל הרצה מטפלת בכמות חסומה
כדי שלא תחסום בקשת HTTP, ומדווחת כמה נותרו. ההחלה אידמפוטנטית, ולכן
הרצה חוזרת בטוחה. שני המסלולים כותבים מסמך audit ל-``migration_audit``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

AUDIT_COLLECTION = "migration_audit"
MIGRATION_NAME = "created_at_from_first_version"

#: כמה קבצים מטופלים בהחלה אחת. ההחלה רצה בתוך בקשת HTTP של האדמין,
#: ולכן חייבת להיחסם בזמן. הערך נבחר כדי שגם ``bulk_write`` וגם ביטול
#: הקאש שאחריו יסתיימו הרבה לפני timeout של פרוקסי.
DEFAULT_BATCH_SIZE = 500


class MigrationError(RuntimeError):
    """כשל שאסור להציג כ-0 או כהצלחה — הדו"ח הזה הוא בסיס להחלטה."""


def _pipeline(*, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """הצינור המשותף ל-dry-run ולהחלה — אותו חישוב בדיוק בשניהם.

    ``$min`` מתעלם מ-``null`` ומשדה חסר (נמדד מול mongod 7.0.14), ולכן
    ``earliest_created`` הוא תמיד תאריך אמיתי אם קיים ולו אחד; קובץ שאין
    בו אף ``created_at`` יקבל ``null`` ויוסנן החוצה — אין לו מה לרשת.
    """
    stages: List[Dict[str, Any]] = [
        {"$match": {"is_active": True}},
        {
            "$group": {
                "_id": {"user_id": "$user_id", "file_name": "$file_name"},
                "max_version": {"$max": "$version"},
                "earliest_created": {"$min": "$created_at"},
                "versions": {"$sum": 1},
                "docs": {
                    "$push": {"_id": "$_id", "version": "$version", "created_at": "$created_at"}
                },
            }
        },
        # רק קבצים שיש להם ממה לרשת.
        {"$match": {"earliest_created": {"$ne": None}}},
        {
            "$addFields": {
                # המועמדים לתיקון: מסמכי הגרסה הגבוהה ביותר שהתאריך שלהם
                # מאוחר מהמוקדם — או חסר לגמרי. השוואת ``$gt`` מול ``null``
                # מחזירה ``false`` (נמדד), ולכן החסרים חייבים תנאי נפרד;
                # בלעדיו קובץ שגרסתו האחרונה בלי ``created_at`` היה נשאר
                # שבור והורשת התיקון קדימה הייתה נותנת לו ``now`` שוב.
                "targets": {
                    "$filter": {
                        "input": "$docs",
                        "as": "d",
                        "cond": {
                            "$and": [
                                {"$eq": ["$$d.version", "$max_version"]},
                                {
                                    "$or": [
                                        {"$eq": [{"$ifNull": ["$$d.created_at", None]}, None]},
                                        {"$gt": ["$$d.created_at", "$earliest_created"]},
                                    ]
                                },
                            ]
                        },
                    }
                },
            }
        },
        {"$match": {"targets.0": {"$exists": True}}},
        {"$project": {"docs": 0}},
        # סדר יציב בין הרצות, כדי שהחלה באצוות תתקדם ולא תדשדש.
        {"$sort": {"_id.user_id": 1, "_id.file_name": 1}},
    ]
    if limit is not None:
        stages.append({"$limit": int(limit)})
    return stages


def _affected(db, *, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    return list(db.code_snippets.aggregate(_pipeline(limit=limit), allowDiskUse=True))


def count_affected(db) -> int:
    """כמה קבצים לוגיים עדיין דורשים תיקון. חלק מה-API הציבורי: עמוד
    האדמין משתמש בו כחתימת התוצאה, כדי לוודא שההחלה חלה על מה שהוצג."""
    rows = list(
        db.code_snippets.aggregate(_pipeline() + [{"$count": "n"}], allowDiskUse=True)
    )
    return int(rows[0]["n"]) if rows else 0


def _count_total_files(db) -> int:
    """סך הקבצים הלוגיים הפעילים. כשל כאן **נזרק**, לא מוחלף ב-0.

    המספר הזה הוא המכנה בדו"ח שעליו האדמין מחליט אם להחיל. ``0`` שקט
    הופך "1200 מתוך 40000" ל-"1200 מתוך 0" — מטעה בדיוק ברגע ההחלטה.
    """
    try:
        rows = list(
            db.code_snippets.aggregate(
                [
                    {"$match": {"is_active": True}},
                    {"$group": {"_id": {"user_id": "$user_id", "file_name": "$file_name"}}},
                    {"$count": "n"},
                ],
                allowDiskUse=True,
            )
        )
    except Exception as exc:  # pragma: no cover - תלוי בכשל DB אמיתי
        raise MigrationError(f"ספירת סך הקבצים נכשלה: {exc}") from exc
    return int(rows[0]["n"]) if rows else 0


def _write_audit(db, doc: Dict[str, Any]) -> Optional[str]:
    """כותב רשומת audit ומחזיר את הודעת השגיאה אם נכשל — ``None`` בהצלחה.

    לא בולעים: "מיגרציה שאפשר לעמוד מאחוריה" כוללת את התיעוד שלה. דיווח
    הצלחה בזמן שהרשומה לא נכתבה הוא בדיוק הדפוס של הצלחה מדומה, ולכן
    הכישלון חוזר בתוצאה ומוצג לאדמין.
    """
    try:
        db[AUDIT_COLLECTION].insert_one(dict(doc))
        return None
    except Exception as exc:
        logger.warning("כתיבת audit למיגרציה %s נכשלה: %s", MIGRATION_NAME, exc)
        return str(exc)


def _invalidate_users(user_ids) -> Dict[str, Any]:
    """מבטל קאש למשתמשים שנגענו בהם, ומדווח את **מה שנמדד**.

    ‏``cache.invalidate_user_cache`` עוטף את כל גופו ב-``except Exception``
    ומחזיר ``int`` — מספר המפתחות שנמחקו בפועל. כלומר הוא **אינו זורק**,
    ולכן ``try/except`` סביבו הוא ``except`` שלא ירוץ לעולם, ו-"הקריאה
    חזרה" אינו מידע. ערוץ הכשל היחיד שלו הוא ערך ההחזרה — וזה מה שנקרא
    כאן (K11, ו-``return-value-failure-unchecked`` §4).

    **‏0 אינו מסומן ככשל.** לפי K11 הקובע הוא החוזה: מפתח קיים רק אם
    מישהו שלף את רשימת הקבצים של המשתמש קודם, ולכן קאש קר הוא מצב
    לגיטימי. מה שכן ניתן להבחין בו — ולכן מדווח בנפרד — הוא היעדר
    backend קאש בכלל, שהוא כשל אמיתי שהיה מוסתר מאחורי "0 מפתחות".

    מחזיר ``users``, ``keys_deleted`` ו-``backend`` (האם יש קאש פעיל),
    ו-``error`` כשה-import עצמו נכשל.
    """
    try:
        from cache_manager import cache  # type: ignore
    except Exception as exc:
        logger.warning("ביטול קאש למיגרציה נכשל: לא ניתן לטעון cache_manager: %s", exc)
        return {"users": len(user_ids), "keys_deleted": 0, "backend": False, "error": str(exc)}

    # ``is_enabled`` הוא הדגל ש-``cache_manager`` מציב כשיש Redis חי, והוא
    # מה ש-``delete_pattern`` עצמו בודק. הדוקסטרינג שלו קובע במפורש שכאשר
    # הוא כבוי הניקוי חל **רק על הפולבק שבתהליך הזה**, ושבמצב הזה 0 אינו
    # מבחין בין "לא היה מה למחוק" לבין "לא יכולתי לגשת". לכן מדווחים אותו
    # לאדמין ולא מסתפקים במספר.
    backend = bool(getattr(cache, "is_enabled", False))

    keys_deleted = 0
    for uid in user_ids:
        keys_deleted += int(cache.invalidate_user_cache(int(uid)) or 0)

    if not backend:
        logger.warning(
            "המיגרציה עדכנה %d משתמשים בזמן ש-Redis אינו זמין — ביטול הקאש "
            "חל רק על הפולבק שבתהליך הזה, ו-workers אחרים עשויים להמשיך "
            "להגיש את התאריך הישן עד ש-TTL יפוג",
            len(user_ids),
        )
    return {"users": len(user_ids), "keys_deleted": keys_deleted, "backend": backend}


def _sample_of(row: Dict[str, Any]) -> Dict[str, Any]:
    targets = row.get("targets") or []
    currents = [t.get("created_at") for t in targets]
    return {
        "file_name": row["_id"]["file_name"],
        "user_id": row["_id"]["user_id"],
        "versions": row.get("versions"),
        "duplicate_latest": len(targets) > 1,
        "current_created": currents[0] if currents else None,
        "new_created": row.get("earliest_created"),
    }


def dry_run(db, *, sample_size: int = 20) -> Dict[str, Any]:
    """קריאה בלבד. מחזיר כמה קבצים ייפגעו, מתוך כמה, ודוגמאות."""
    affected_count = count_affected(db)
    total = _count_total_files(db)
    samples = [_sample_of(row) for row in _affected(db, limit=max(0, int(sample_size)))]
    result: Dict[str, Any] = {
        "migration": MIGRATION_NAME,
        "mode": "dry_run",
        "affected_count": affected_count,
        "total_files": total,
        "batch_size": DEFAULT_BATCH_SIZE,
        "samples": samples,
        "ran_at": datetime.now(timezone.utc),
    }
    result["audit_error"] = _write_audit(db, result)
    return result


def apply(db, *, batch_size: int = DEFAULT_BATCH_SIZE) -> Dict[str, Any]:
    """מחיל אצווה אחת, ואז **מאמת בקריאה חוזרת** — ערך ההחזרה של הכתיבה אינו אימות."""
    from pymongo import UpdateOne

    batch = _affected(db, limit=int(batch_size))
    ops: List[Any] = []
    user_ids = set()
    for row in batch:
        for target in row.get("targets") or []:
            ops.append(
                UpdateOne(
                    {"_id": target["_id"]},
                    {"$set": {"created_at": row["earliest_created"]}},
                )
            )
        user_ids.add(row["_id"]["user_id"])

    modified = 0
    if ops:
        res = db.code_snippets.bulk_write(ops, ordered=False)
        modified = int(getattr(res, "modified_count", 0) or 0)

    cache_report = (
        _invalidate_users(sorted(user_ids))
        if user_ids
        else {"users": 0, "keys_deleted": 0, "backend": True}
    )

    # אימות בקריאה חוזרת: כמה קבצים עדיין עומדים בתנאי. הצינור אינו רואה
    # את מה שכבר תוקן, ולכן זהו גם מונה ההתקדמות של האצוות הבאות.
    remaining = count_affected(db)

    result: Dict[str, Any] = {
        "migration": MIGRATION_NAME,
        "mode": "apply",
        "files_in_batch": len(batch),
        "documents_planned": len(ops),
        "modified": modified,
        "remaining_after": remaining,
        "done": remaining == 0,
        "cache_invalidation": cache_report,
        "ran_at": datetime.now(timezone.utc),
    }
    result["audit_error"] = _write_audit(db, result)
    return result
