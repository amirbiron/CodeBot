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
    python scripts/migrate_reminder_acked_status.py           # דיווח בלבד
    python scripts/migrate_reminder_acked_status.py --apply   # כותב

**בלי ``--apply`` הסקריפט רק מדווח**, כמו ``migrate_note_boards.py``,
``migrate_note_colors.py`` ו-``cleanup_repo_tags.py`` (המוסכמה מתועדת
ב-``docs/development/scripts.rst``). הגרסה הראשונה כתבה כברירת מחדל ודילגה
רק עם ``--dry-run`` — הפוך מכל סקריפט אחר בתיקייה, ומי שהריץ "כדי לראות מה
יקרה" כתב. הכיוון בטוח; ההפתעה לא.
"""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

#: **שורש הריפו נכנס ל-``sys.path`` מפורשות.** ‏``python scripts/X.py``
#: שם ב-``sys.path[0]`` את התיקייה של **הסקריפט** — ``scripts/`` — ולא את
#: ספריית העבודה, ולכן ``services`` ו-``note_reminder_state`` אינם נמצאים
#: גם כשמריצים מתוך שורש הפרויקט. נמדד: ההרצה נפלה על
#: ``No module named 'services'`` בדיוק מהתיקייה שההודעה ממליצה עליה.
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _parse_args(argv):
    parser = argparse.ArgumentParser(description="סגירת status לתזכורות פתקים שכבר אושרו")
    parser.add_argument("--apply", action="store_true", help="לכתוב בפועל, ולא רק לדווח")
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(sys.argv[1:] if argv is None else argv)

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
        print("\nהתקינו את תלויות הפרויקט:")
        print("  pip install -r requirements/production.txt")
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

    # ``DATABASE_NAME`` שגוי נותן אוסף אמיתי וריק — ואז "אין מה לעדכן" עם קוד
    # יציאה 0 נראה בדיוק כמו הצלחה. שם המסד וגודל האוסף מודפסים לפני כל מסקנה.
    print(f"🗄️ מסד: {getattr(db, 'name', '?')} — {collection.estimated_document_count()} מסמכים באוסף note_reminders")

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

    if not args.apply:
        print("\n🔍 דיווח בלבד — לא מבצע שינויים")
        for doc in collection.find(stale_filter, {"note_id": 1, "status": 1, "ack_at": 1}).limit(5):
            print(
                f"  - {doc.get('_id')}: note_id={doc.get('note_id')}, "
                f"status={doc.get('status')!r} → {REMINDER_STATUS_ACKED!r} "
                f"(ack_at={doc.get('ack_at')})"
            )
        if total > 5:
            print(f"  ... ועוד {total - 5} מסמכים")
        print("\nלכתיבה בפועל, הרץ עם --apply")
        return

    # תחילת הריצה נרשמת לפני הכתיבה: הספירה החוזרת תחומה לאישורים שכבר היו
    # קיימים אז. פוד ישן שמאשר באמצע הריצה כותב ``ack_at`` בלי ``status`` ויוצר
    # מסמך "ישן" חדש בין הכתיבה לספירה — הוא שייך לריצה הבאה, לא לכשל של זו.
    started_at = datetime.now(timezone.utc)
    print(f"\n🔄 מעדכן status ל-{REMINDER_STATUS_ACKED!r}...")
    result = collection.update_many(
        stale_filter, {"$set": {"status": REMINDER_STATUS_ACKED}}
    )
    print(f"   נכתבו {result.modified_count} מסמכים")
    print("   אישור שנחת בזמן הריצה נספר לריצה הבאה; הרצה חוזרת בטוחה, הכיוון היחיד הוא מאושר לאושר.")

    # ערך החזרה של כתיבה אינו אימות — סופרים שוב מהמסד, רק מה שאושר לפני שהתחלנו.
    remaining = collection.count_documents(dict(stale_filter, ack_at={"$ne": None, "$lte": started_at}))
    if remaining == 0:
        print(f"\n✅ מיגרציה הושלמה בהצלחה! עודכנו {result.modified_count} מסמכים")
    else:
        print(f"\n⚠️ נותרו {remaining} מסמכים שלא עודכנו — הרץ שוב")
        sys.exit(1)


if __name__ == "__main__":
    main()
