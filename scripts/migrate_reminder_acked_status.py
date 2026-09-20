#!/usr/bin/env python3
"""
Migration script: סגירת ``status`` לתזכורות שכבר אושרו.

עד לתיקון, ``reminders_ack`` כתב ``ack_at`` ולא נגע ב-``status``. לכן כל
תזכורת שהמשתמש ראה וסגר נשארה ``pending`` (או ``snoozed``) לנצח, וכרטיס
הדשבורד — שסופר לפי ``status`` בלבד — דיווח אותן כ"בהמתנה".

הקוד החדש כותב את שני השדות יחד, אבל הוא אינו נוגע במסמכים שכבר נכתבו.
הסקריפט הזה מיישר אותם פעם אחת: מסמך עם ``ack_at`` מלא שעדיין במצב פעיל
מקבל ``status="acked"``.

**הכיוון היחיד הוא מ"אושר" ל"אושר".** הסקריפט אינו נוגע במסמך שאין לו
``ack_at``, ולכן הוא אינו יכול לסגור תזכורת שעדיין ממתינה למשתמש.

Usage:
    python scripts/migrate_reminder_acked_status.py [--dry-run]

Options:
    --dry-run    מציג מה יעודכן בלי לכתוב כלום
"""
import sys


def main():
    dry_run = "--dry-run" in sys.argv

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    try:
        from services.db_provider import get_db
        from note_reminder_state import (
            ACTIVE_REMINDER_STATUSES,
            REMINDER_STATUS_ACKED,
        )
    except ImportError as e:
        print(f"❌ חסרות תלויות: {e}")
        print("\nהרץ מתוך תיקיית הפרויקט:")
        print("  cd /path/to/project && python scripts/migrate_reminder_acked_status.py")
        sys.exit(1)

    db = get_db()
    try:
        if getattr(db, "name", "") == "noop_db":
            raise RuntimeError("noop_db")
    except Exception:
        print("❌ לא ניתן להתחבר ל-MongoDB (קיבלתי noop DB).")
        print("   ודא ש-MONGODB_URL מוגדר בסביבה וש-DISABLE_DB לא פעיל")
        sys.exit(1)

    collection = db.note_reminders

    # ``$ne: None`` דורש שהשדה **קיים ואינו null**. מסמך בלי ``ack_at`` כלל
    # אינו נתפס — וזה בדיוק הרצוי: אין לו אישור, הוא עדיין ממתין.
    #
    # מקור: MongoDB Manual, "Query for Null or Missing Fields", סעיף
    # Non-Equality Filter — *"To query for fields that exist and are not
    # null, use the { $ne : null } filter."*
    # https://www.mongodb.com/docs/manual/tutorial/query-for-null-fields/
    #
    # שימו לב שזה **אינו** מה שדף ``$ne`` הכללי מרמז ("includes documents
    # that do not contain the field") — ההשוואה ל-null היא המקרה החריג,
    # והדף הזה הוא הסמכות עליו.
    stale_filter = {
        "ack_at": {"$ne": None},
        "status": {"$in": list(ACTIVE_REMINDER_STATUSES)},
    }
    total = collection.count_documents(stale_filter)

    if total == 0:
        print("✅ אין תזכורות מאושרות שנשארו במצב פעיל — אין צורך במיגרציה")
        return

    print(f"📊 נמצאו {total} תזכורות עם ack_at מלא שעדיין במצב פעיל")

    if dry_run:
        print("\n🔍 מצב dry-run - לא מבצע שינויים")
        for doc in collection.find(stale_filter, {"note_id": 1, "status": 1, "ack_at": 1}).limit(5):
            print(
                f"  - {doc.get('_id')}: note_id={doc.get('note_id')}, "
                f"status={doc.get('status')!r} → {REMINDER_STATUS_ACKED!r} "
                f"(ack_at={doc.get('ack_at')})"
            )
        if total > 5:
            print(f"  ... ועוד {total - 5} מסמכים")
        print("\nלהרצה אמיתית, הרץ ללא --dry-run")
        return

    print(f"\n🔄 מעדכן status ל-{REMINDER_STATUS_ACKED!r}...")
    result = collection.update_many(
        stale_filter, {"$set": {"status": REMINDER_STATUS_ACKED}}
    )
    print(f"   נכתבו {result.modified_count} מסמכים")

    # ערך החזרה של כתיבה אינו אימות — סופרים שוב מהמסד.
    remaining = collection.count_documents(stale_filter)
    if remaining == 0:
        print(f"\n✅ מיגרציה הושלמה בהצלחה! עודכנו {result.modified_count} מסמכים")
    else:
        print(f"\n⚠️ נותרו {remaining} מסמכים שלא עודכנו")
        sys.exit(1)


if __name__ == "__main__":
    main()
