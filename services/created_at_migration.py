"""מיגרציית ``created_at`` — "נוצר" של קובץ שייך לקובץ הלוגי, לא לגרסה.

הרקע: כל עריכת תוכן יוצרת מסמך גרסה חדש, ועד התיקון ההורשה ב-
``save_code_snippet`` השדה ``created_at`` שלו נקבע לרגע העריכה. ה-UI מציג
תמיד את מסמך הגרסה האחרונה, ולכן "נוצר" זז בכל עריכה. התיקון קדימה חי
בקוד; המיגרציה כאן מיישרת את המצב הקיים — בלעדיה קובץ ותיק יוריש הלאה
את התאריך השגוי שכבר יש לו.

מה היא עושה: לכל ``(user_id, file_name)`` פעיל, קובעת לגרסה **האחרונה
בלבד** ``created_at = המוקדם מבין כל גרסאות הקובץ``. גרסאות ישנות אינן
נגועות — תאריכי ההיסטוריה שלהן נשארים כמות שהם.

מופעלת מעמוד האדמין ``/admin/migrations/created-at`` בלבד: dry-run
לקריאה בלבד, ואחריו החלה מפורשת. שני המסלולים כותבים מסמך audit
ל-``migration_audit`` כדי שיישאר תיעוד למה שנבדק ומה הוחל.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

AUDIT_COLLECTION = "migration_audit"
MIGRATION_NAME = "created_at_from_first_version"

# צינור משותף לשני המסלולים: אותו חישוב בדיוק ב-dry-run ובהחלה, כדי שמה
# שהוצג הוא מה שיוחל. שינוי בצנרת של אחד בלי השני הוא באג, לא גמישות.
_PIPELINE: List[Dict[str, Any]] = [
    {"$match": {"is_active": True}},
    {"$sort": {"user_id": 1, "file_name": 1, "version": -1}},
    {
        "$group": {
            "_id": {"user_id": "$user_id", "file_name": "$file_name"},
            "latest_id": {"$first": "$_id"},
            "latest_created": {"$first": "$created_at"},
            "earliest_created": {"$min": "$created_at"},
            "versions": {"$sum": 1},
        }
    },
    # רק קבצים שבהם יש מה לתקן: התאריך של הגרסה האחרונה מאוחר מהמוקדם.
    {"$match": {"$expr": {"$gt": ["$latest_created", "$earliest_created"]}}},
]


def _affected(db) -> List[Dict[str, Any]]:
    return list(db.code_snippets.aggregate(_PIPELINE, allowDiskUse=True))


def _write_audit(db, doc: Dict[str, Any]) -> None:
    try:
        db[AUDIT_COLLECTION].insert_one(doc)
    except Exception:
        # audit הוא תיעוד, לא שער: כישלון בו לא מפיל את המיגרציה עצמה.
        pass


def dry_run(db, *, sample_size: int = 20) -> Dict[str, Any]:
    """קריאה בלבד. מחזיר כמה קבצים ייפגעו, מתוך כמה, ודוגמאות."""
    affected = _affected(db)
    total = 0
    try:
        agg = list(
            db.code_snippets.aggregate(
                [
                    {"$match": {"is_active": True}},
                    {"$group": {"_id": {"user_id": "$user_id", "file_name": "$file_name"}}},
                    {"$count": "n"},
                ]
            )
        )
        total = int(agg[0]["n"]) if agg else 0
    except Exception:
        total = 0
    samples = [
        {
            "file_name": row["_id"]["file_name"],
            "user_id": row["_id"]["user_id"],
            "versions": row["versions"],
            "current_created": row["latest_created"],
            "new_created": row["earliest_created"],
        }
        for row in affected[:sample_size]
    ]
    result = {
        "migration": MIGRATION_NAME,
        "mode": "dry_run",
        "affected_count": len(affected),
        "total_files": total,
        "samples": samples,
        "ran_at": datetime.now(timezone.utc),
    }
    _write_audit(db, dict(result))
    return result


def apply(db) -> Dict[str, Any]:
    """מחיל, ואז **מאמת בקריאה חוזרת** — ערך ההחזרה של הכתיבה אינו אימות."""
    from pymongo import UpdateOne

    affected = _affected(db)
    ops = [
        UpdateOne(
            {"_id": row["latest_id"]},
            {"$set": {"created_at": row["earliest_created"]}},
        )
        for row in affected
    ]
    modified = 0
    if ops:
        res = db.code_snippets.bulk_write(ops, ordered=False)
        modified = int(getattr(res, "modified_count", 0) or 0)

    # אימות: אחרי ההחלה, כמה קבצים עדיין עומדים בתנאי הפער. אמור להיות 0.
    remaining = len(_affected(db))

    result = {
        "migration": MIGRATION_NAME,
        "mode": "apply",
        "planned": len(affected),
        "modified": modified,
        "remaining_after": remaining,
        "ran_at": datetime.now(timezone.utc),
    }
    _write_audit(db, dict(result))
    return result
