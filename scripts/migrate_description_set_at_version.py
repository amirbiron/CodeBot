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

**אידמפוטנטית, ולא רק במובן ש"אפשר להריץ שוב".** חותמת קיימת אינה
נדרסת לעולם. אבל "לא לדרוס" אינו "לא לגעת", ושתי הצורות נבדלות בדיוק
במקרה שבו הרצה חוזרת נחוצה: ``update_many`` אינו אטומי בין מסמכים,
ולכן הרצה שנקטעה משאירה חלק מהשרשרת כתוב וחלק לא.

- **החותמת הקיימת שווה למה שהשרשרת אומרת** ← משלימים את המסמכים
  החסרים. בטוח בהגדרה, כי הערך שנכתב זהה לזה שכבר שם.
- **החותמת הקיימת שונה** ← לא נוגעים.
  ``codekeeper_update_file_description`` מזיז את החותמת בלי ליצור
  גרסה, ומאותו רגע שרשרת הגרסאות כבר לא מתארת אותה. חישוב מחדש היה
  מחזיר את הגיל אחורה ומוחק עדכון אמיתי.

**היקף: ``code_snippets`` בלבד, וזו החלטה ולא השמטה.** לאותה ישות יש
בפרויקט הזה שני אחסונים אפשריים — ``code_snippets`` ו-``large_files`` —
ופעולה גורפת שמונה רק אחד מהם נכשלת בשקט
(``bugbot-rules/logical-entity-vs-version-document.md`` §4). כאן השני
נשקל ונפסל: קובץ גדול נשמר ב**דריסה** (מחיקה ואז הכנסה) ואין לו שדה
``version`` כלל, ולכן אין לו "גרסה שבה התיאור נקבע" ואין ממה לגזור גיל.
מסלולי הקריאה כבר מתייחסים אליו כך — ``description_age_field`` אינו
מחזיר את השדה בכלל למסמך בלי ``version``, ולא ``null``.

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

from file_description import (  # noqa: E402
    DESCRIPTION_SET_AT_VERSION_FIELD,
    normalized_version,
)


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
        # ``normalized_version`` ולא בדיקה מקומית: זו אותה שאלה בדיוק
        # ששאר הקוד שואל על אותו שדה, ועותק שני שלה כאן כבר עלה לנו —
        # ראו ה-docstring של :func:`_latest_version_doc`.
        number = normalized_version(doc.get("version"))
        if number is None:
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


def _latest_version_doc(versions: Any) -> dict[str, Any] | None:
    """מסמך הגרסה הגבוהה ביותר בשרשרת, או ``None`` כשאין אף מסמך תקין.

    **קיימת בגלל באג אמיתי, לא בשביל סדר.** קודם הבחירה כאן הייתה
    ``max(..., key=lambda d: int(d.get("version", 0) or 0))``, כלומר
    עותק **שלישי** של "מה נחשב מספר גרסה" — ועותק שסינן פחות משני
    האחרים: ``int("bad")`` זורק ``ValueError``, וכל המיגרציה הייתה
    נופלת באמצע על מסמך פגום יחיד, בזמן ש-:func:`stamp_from_version_chain`
    על אותם נתונים בדיוק מדלגת עליו וממשיכה.

    מיגרציה שקורסת באמצע גרועה במיוחד: היא כבר כתבה לחלק מהקבצים, ומי
    שמריץ אותה שוב אינו יודע איפה היא עצרה. ולכן שתי הפונקציות כאן
    שואלות עכשיו את **אותה** שאלה, דרך ``normalized_version``.
    """
    best: dict[str, Any] | None = None
    best_version = 0
    for doc in versions or []:
        if not isinstance(doc, dict):
            continue
        number = normalized_version(doc.get("version"))
        if number is None or number <= best_version:
            continue
        best, best_version = doc, number
    return best


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


#: כמה מזהים נשלחים ב-``$in`` אחד. התקרה קיימת כי שרשרת גרסאות אינה
#: חסומה מלמעלה, ושאילתה עם מזהים בלי גבול היא שאילתה שגדלה עם הנתונים.
#: 250 הוא אותו גודל מנה שכבר נבחר ל-``get_latest_versions_by_names``
#: ב-``database/repository.py`` — אותו סוג שאילתה, אותה מנה.
_ID_BATCH = 250


def _documents_to_stamp(versions: Any, stamp: int) -> list:
    """המזהים של מסמכי הגרסה שצריכים לקבל את ``stamp``, ועוד לא קיבלו.

    **הבחירה נעשית בפייתון ולא בפילטר של מונגו, וזה תיקון לבאג ולא
    העדפת סגנון.** הצורה הקודמת סיננה ``{"version": {"$gte": stamp}}``,
    ומונגו משווה בין טיפוסים לפי סדר טיפוסים — מספר **אינו** מתאים
    למחרוזת. נמדד מול MongoDB 7.0.14: על שרשרת ``1, "2", 3`` הפילטר
    ``$gte: 1`` עדכן שני מסמכים והשאיר את ``"2"`` בלי חותמת, בשקט.

    וזה בדיוק המסמך שהכי חשוב לתפוס: ``normalized_version`` מקבל מספר
    שנשמר כמחרוזת **במכוון**, כי מסמכים ישנים במונגו נושאים כאלה. שני
    חצאים של אותה מיגרציה החזיקו שתי תשובות שונות לשאלה "מה נחשב מספר
    גרסה", והחצי שכותב הוא זה שהחמיץ.

    מסמך שכבר נושא חותמת אינו נבחר — ``$exists`` נשמר גם בפילטר הכתיבה
    עצמו, כך שגם כותב מקביל שנכנס בין הבחירה לכתיבה אינו נדרס.
    """
    out = []
    for doc in versions or []:
        if not isinstance(doc, dict):
            continue
        if doc.get(DESCRIPTION_SET_AT_VERSION_FIELD) is not None:
            continue
        number = normalized_version(doc.get("version"))
        if number is None or number < stamp:
            continue
        out.append(doc["_id"])
    return out


def _write_stamp(collection: Any, ids: list, stamp: int) -> int:
    """כותב את החותמת למזהים שנבחרו, במנות, ומחזיר כמה מסמכים השתנו."""
    written = 0
    for start in range(0, len(ids), _ID_BATCH):
        batch = ids[start:start + _ID_BATCH]
        result = collection.update_many(
            {
                "_id": {"$in": batch},
                # **שווה ל-``None`` ולא ``$exists: False``**, כי אלה שני
                # פילטרים שונים: נמדד מול MongoDB 7.0.14 —
                # ``$exists: False`` תופס **רק** שדה חסר, והשוואה
                # ל-``None`` תופסת **גם חסר וגם ``null`` מפורש**. שניהם
                # אינם תופסים ערך מספרי, ולכן חותמת אמיתית אינה נדרסת
                # בשום צורה.
                #
                # ההבדל היה באג: הבחירה ב-:func:`_documents_to_stamp`
                # פוסלת לפי ``is not None``, כלומר מסמך עם ``null``
                # מפורש **נבחר**, והפילטר הזה לא כלל אותו — הקובץ נספר
                # כמטופל והמסמך נשאר ריק, בכל הרצה מחדש. שני חצאים של
                # אותה פעולה עם שתי תשובות לשאלה "מה נחשב חסר חותמת".
                #
                # והפילטר נשאר למרות שהבחירה כבר סיננה, כי בין הקריאה
                # לכתיבה יכול להיכנס כותב אחר.
                DESCRIPTION_SET_AT_VERSION_FIELD: None,
            },
            {"$set": {DESCRIPTION_SET_AT_VERSION_FIELD: stamp}},
        )
        written += int(getattr(result, "modified_count", 0) or 0)
    return written


def migrate(collection: Any, *, dry_run: bool = False) -> dict[str, int]:
    """מריצה את המיגרציה ומחזירה את המונים לדוח.

    המונים אינם קישוט: "כמה קיבלו חותמת" לבד אינו אומר אם המיגרציה
    הצליחה, כי קובץ בלי תיאור וקובץ ששרשרתו קטועה נראים ממנו זהים —
    שניהם "לא קיבלו". ההפרדה ביניהם היא מה שמאפשר לקרוא את הדוח.

    **וקובץ שכבר יש לגרסתו האחרונה חותמת אינו מדולג בעיוורון.** הצורה
    הקודמת עשתה בדיוק את זה, ובכך שברה את ההבטחה שהמודול נושא:
    ``update_many`` אינו אטומי בין מסמכים, ולכן הרצה שנקטעה באמצע
    משאירה חלק מהשרשרת כתוב וחלק לא. נמדד: אחרי קטיעה כזו, הרצה חוזרת
    ספרה את הקובץ כ"כבר מתוארך" ולא השלימה כלום — כלומר "ניתנת להרצה
    חוזרת" הייתה נכונה רק כשלא היה צורך בה.

    ההכרעה מפרידה בין שני מצבים שנראים זהים מבחוץ:

    - **החותמת הקיימת שווה למה שהשרשרת אומרת** ← משלימים את מסמכי
      השרשרת שחסרים. זה בטוח בהגדרה, כי הערך שנכתב זהה לזה שכבר שם.
    - **החותמת הקיימת שונה** ← לא נוגעים.
      ``codekeeper_update_file_description`` מזיז חותמת בלי ליצור גרסה,
      ומאותו רגע השרשרת אינה מתארת אותה. חישוב מחדש היה מחזיר את הגיל
      אחורה ומוחק עדכון אמיתי.
    """
    counters = {
        "files": 0,
        "stamped": 0,
        "backfilled": 0,
        "already_complete": 0,
        "stamp_differs": 0,
        "unknown": 0,
        "no_description": 0,
        "documents_written": 0,
    }
    for chain in _chains(collection):
        counters["files"] += 1
        versions = chain.get("versions") or []
        latest = _latest_version_doc(versions)
        description = (latest or {}).get("description")
        if not isinstance(description, str) or not description:
            counters["no_description"] += 1
            continue
        stamp = stamp_from_version_chain(versions)
        if stamp is None:
            counters["unknown"] += 1
            continue
        existing = normalized_version((latest or {}).get(DESCRIPTION_SET_AT_VERSION_FIELD))
        if existing is not None and existing != stamp:
            counters["stamp_differs"] += 1
            continue
        targets = _documents_to_stamp(versions, stamp)
        if existing is None:
            counters["stamped"] += 1
        elif targets:
            counters["backfilled"] += 1
        else:
            counters["already_complete"] += 1
        if dry_run or not targets:
            continue
        counters["documents_written"] += _write_stamp(collection, targets, stamp)
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

    print(f"📊 קבצים שנסרקו:                {counters['files']}")
    print(f"✅ קיבלו חותמת:                  {counters['stamped']}")
    print(f"🩹 הושלמו (הרצה קודמת נקטעה):    {counters['backfilled']}")
    print(f"➖ כבר היו שלמים:                {counters['already_complete']}")
    print(f"🔒 חותמת שונה מהשרשרת (לא נגענו): {counters['stamp_differs']}")
    print(f"➖ בלי תיאור (אין מה לתארך):      {counters['no_description']}")
    print(f"❓ נשארו null (שרשרת קטועה):      {counters['unknown']}")
    if not dry_run:
        print(f"✍️  מסמכי גרסה שעודכנו:   {counters['documents_written']}")


if __name__ == "__main__":
    main()
