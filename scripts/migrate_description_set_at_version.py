#!/usr/bin/env python3
"""מיגרציה חד-פעמית: חותמת גיל התיאור לקבצים שנשמרו לפני שהשדה קיים.

``description_set_at_version`` נכתב מכאן ואילך בכל מסלול שיוצר גרסה
(``file_description.py``), אבל קובץ שנשמר קודם אין לו אותו — והגיל שלו
יחזור ``null`` עד שמישהו ייגע בתיאור. הסקריפט הזה משחזר את החותמת
מההיסטוריה שכבר קיימת במסד.

**איך משחזרים.** כל גרסה היא מסמך נפרד ונושאת את התיאור שהיה לה באותו
רגע, ולכן אפשר ללכת אחורה מהגרסה האחרונה כל עוד התיאור זהה. הגרסה
המוקדמת ביותר ברצף הזה היא הגרסה שבה התיאור נקבע.

**ומתי לא משחזרים.** אם הליכה אחורה נתקלת במספר גרסה **שאינו קיים**,
השרשרת קטועה — מספור הגרסאות רץ על כל המסמכים של אותו שם קובץ כולל אלה
שבסל המיחזור, ולכן גרסאות שנמחקו משאירות חורים. במקרה כזה החותמת נשארת
ריקה והגיל יישאר ``null``. ``null`` אומר "לא ידוע" ואפס אומר "נקבע
עכשיו"; ניחוש שהיה נראה כמו אפס הוא בדיוק הטענה שאסור להמציא.

**אידמפוטנטית, ולא רק במובן ש"אפשר להריץ שוב".** הסקריפט **אינו נוגע
בקובץ שכבר יש לגרסתו האחרונה חותמת**, וזה לא ייעול אלא נכונות:
``codekeeper_update_file_description`` מזיז את החותמת בלי ליצור גרסה,
ולכן שרשרת הגרסאות כבר לא מתארת אותה. הרצה שנייה שהייתה מחשבת מחדש
הייתה מחזירה את הגיל אחורה ומוחקת עדכון אמיתי.

שימוש::

    python scripts/migrate_description_set_at_version.py [--dry-run]

``--dry-run`` מדפיס את אותו דוח בדיוק בלי לכתוב כלום.
"""
from __future__ import annotations

import os
import sys
from typing import Any

# הרצה כסקריפט מתוך ``scripts/`` — שורש הפרויקט צריך להיות ב-path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from file_description import DESCRIPTION_SET_AT_VERSION_FIELD  # noqa: E402


def stamp_from_version_chain(versions: list[dict[str, Any]]) -> int | None:
    """הגרסה שבה התיאור של הקובץ נקבע, או ``None`` כשאי אפשר לדעת.

    **פונקציה טהורה, ובכוונה בנפרד מהסקריפט.** היא המקום היחיד שבו
    ההיגיון של המיגרציה יושב, ולכן אפשר לבדוק אותה על שרשרות בנויות ביד
    — כולל אלה שקשה לייצר במסד, כמו חור באמצע — בלי להריץ מיגרציה.

    ``versions`` הוא רשימת מסמכי הגרסה **הפעילים** של קובץ אחד, בכל סדר.
    כל מסמך צריך ``version`` ו-``description``.

    שלוש התוצאות:

    - **מספר** — הגרסה המוקדמת ביותר ברצף שבו התיאור זהה לזה של הגרסה
      האחרונה.
    - **``None`` כי אין תיאור** — לא היה מה לתארך.
    - **``None`` כי השרשרת קטועה** — חסר מספר גרסה באמצע הדרך אחורה.
      הקורא אינו צריך להבדיל בין השניים: שניהם משאירים את הקובץ בלי
      חותמת, ואת הגיל ``null``.
    """
    by_version: dict[int, str] = {}
    for doc in versions:
        if not isinstance(doc, dict):
            continue
        raw_version = doc.get("version")
        if isinstance(raw_version, bool) or raw_version is None:
            continue
        try:
            number = int(raw_version)
        except (TypeError, ValueError):
            continue
        if number < 1:
            continue
        description = doc.get("description")
        # מסמך בלי תיאור נכנס עם מחרוזת ריקה ולא מושמט: "לא היה תיאור
        # בגרסה הזו" הוא **שוני** מהתיאור הנוכחי, ולכן הוא עוצר את הרצף.
        # השמטה הייתה נראית כמו חור בשרשרת ומחזירה ``None`` במקום את
        # התשובה הנכונה.
        by_version[number] = description if isinstance(description, str) else ""
    if not by_version:
        return None

    latest = max(by_version)
    current = by_version[latest]
    if not current:
        return None

    run_start = latest
    probe = latest - 1
    while probe >= 1:
        if probe not in by_version:
            return None
        if by_version[probe] != current:
            return run_start
        run_start = probe
        probe -= 1
    return run_start


def _chains(collection: Any):
    """כל קובץ פעיל, עם שרשרת הגרסאות שלו, בשליפה אחת.

    ``$project`` לפני ה-``$group`` הוא מה שמונע מהצינור למשוך את
    ``code`` של כל גרסה של כל קובץ למסד הביניים — חוק ה-Smart Projection,
    ובקנה המידה הזה גם ההבדל בין שאילתה שרצה לשאילתה שנופלת על זיכרון.
    """
    pipeline = [
        {"$match": {"is_active": True}},
        {"$project": {
            "user_id": 1,
            "file_name": 1,
            "version": 1,
            "description": 1,
            DESCRIPTION_SET_AT_VERSION_FIELD: 1,
        }},
        {"$group": {
            "_id": {"user_id": "$user_id", "file_name": "$file_name"},
            "versions": {"$push": "$$ROOT"},
        }},
    ]
    return collection.aggregate(pipeline, allowDiskUse=True)


def migrate(collection: Any, *, dry_run: bool = False) -> dict[str, int]:
    """מריצה את המיגרציה ומחזירה את המונים לדוח.

    המונים אינם קישוט: "כמה קיבלו חותמת" לבד אינו אומר אם המיגרציה
    הצליחה, כי קובץ בלי תיאור וקובץ ששרשרתו קטועה נראים ממנו זהים —
    שניהם "לא קיבלו". ההפרדה ביניהם היא מה שמאפשר לקרוא את הדוח.
    """
    counters = {
        "files": 0,
        "stamped": 0,
        "unknown": 0,
        "no_description": 0,
        "already_stamped": 0,
        "documents_written": 0,
    }
    for chain in _chains(collection):
        counters["files"] += 1
        versions = chain.get("versions") or []
        latest = max(
            (d for d in versions if isinstance(d, dict)),
            key=lambda d: int(d.get("version", 0) or 0),
            default=None,
        )
        if isinstance(latest, dict) and latest.get(DESCRIPTION_SET_AT_VERSION_FIELD) is not None:
            # כבר מתוארך. לא לגעת — ראו ה-docstring של המודול.
            counters["already_stamped"] += 1
            continue
        description = (latest or {}).get("description")
        if not isinstance(description, str) or not description:
            counters["no_description"] += 1
            continue
        stamp = stamp_from_version_chain(versions)
        if stamp is None:
            counters["unknown"] += 1
            continue
        counters["stamped"] += 1
        if dry_run:
            continue
        key = chain.get("_id") or {}
        result = collection.update_many(
            {
                "user_id": key.get("user_id"),
                "file_name": key.get("file_name"),
                "is_active": True,
                # כל הגרסאות מ-``stamp`` ומעלה נושאות את אותו תיאור, ולכן
                # אותה חותמת נכונה לכולן — וכך גם קריאה מפורשת של גרסה
                # ישנה מקבלת גיל ולא ``null``.
                "version": {"$gte": stamp},
                DESCRIPTION_SET_AT_VERSION_FIELD: {"$exists": False},
            },
            {"$set": {DESCRIPTION_SET_AT_VERSION_FIELD: stamp}},
        )
        counters["documents_written"] += int(getattr(result, "modified_count", 0) or 0)
    return counters


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    try:
        from services.db_provider import get_db
    except ImportError as exc:
        print(f"❌ חסרות תלויות: {exc}")
        print("\nהרץ מתוך תיקיית הפרויקט:")
        print("  cd /path/to/project && python scripts/migrate_description_set_at_version.py")
        sys.exit(1)

    db = get_db()
    if getattr(db, "name", "") == "noop_db":
        print("❌ לא ניתן להתחבר ל-MongoDB (קיבלתי noop DB).")
        print("   ודא ש-MONGODB_URL מוגדר בסביבה וש-DISABLE_DB לא פעיל")
        sys.exit(1)

    if dry_run:
        print("🔍 מצב dry-run — לא נכתב דבר\n")

    counters = migrate(db.code_snippets, dry_run=dry_run)

    print(f"📊 קבצים שנסרקו:        {counters['files']}")
    print(f"✅ קיבלו חותמת:          {counters['stamped']}")
    print(f"➖ כבר היו מתוארכים:      {counters['already_stamped']}")
    print(f"➖ בלי תיאור (אין מה לתארך): {counters['no_description']}")
    print(f"❓ נשארו null (שרשרת קטועה): {counters['unknown']}")
    if not dry_run:
        print(f"✍️  מסמכי גרסה שעודכנו:   {counters['documents_written']}")


if __name__ == "__main__":
    main()
