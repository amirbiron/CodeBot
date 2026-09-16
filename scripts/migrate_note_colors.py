#!/usr/bin/env python3
"""מיגרציה של צבעי הפתקים מ-``hex`` למזהה יציב מהפלטה.

הרצה::

    python scripts/migrate_note_colors.py                      # דוח בלבד, לא כותב
    python scripts/migrate_note_colors.py --apply              # מקפל hex של הפלטה למזהה
    python scripts/migrate_note_colors.py --apply --normalize-legacy

הסקריפט בטוח להרצה חוזרת: הוא קורא את הערכים שקיימים בפועל, ממפה כל אחד
דרך ``sticky_notes_target.resolve_note_color``, ומעדכן רק את מה שבאמת זז.
הרצה שנייה לא תמצא מה לשנות.

**למה סקריפט ולא רק נורמליזציה בקריאה.** הקריאה כבר מנורמלת — ``note_color_id``
מקפל ``#FFFFCC`` ל-``yellow_light`` בכל שליפה, ולכן התצוגה נכונה גם בלי
להריץ כאן שום דבר. מה שהיא **אינה** פותרת הוא השאילתה: סינון פתקים לפי
צבע מחפש ערך אחד במסד, ואם חלק מהפתקים שמורים כ-``#ffffcc`` וחלק
כ-``yellow_light`` הוא מחזיר חלק מהתשובה — בלי שגיאה ובלי סימן. לכן שני
החצאים נחוצים: הסקריפט מיישר את מה שקיים, והנורמליזציה בקריאה מכסה את
מה שנכתב בין ההרצה לפריסה, ואת גיבויים שמשוחזרים אחריה.

**ברירת המחדל היא דוח בלבד**, בתבנית ``scripts/migrate_note_boards.py``:
סקריפט שכותב ברגע שמריצים אותו הוא סקריפט שאי אפשר להריץ כדי פשוט לראות
מה המצב.

**‏``--normalize-legacy`` הוא דגל נפרד, ובכוונה.** צבע שאינו בפלטה אינו
מוחלף בכוח — זו הדרישה. אבל ``#AABBCC`` ו-``#aabbcc`` הם אותו פיקסל
בדיוק ושני ערכים שונים במסד, כלומר אותה בעיית סינון בקטן. הדגל מיישר
*את צורת הכתיבה בלבד* ולעולם לא את הצבע עצמו, וההחלטה להריץ אותו נשארת
של מי שמריץ.
"""

from __future__ import annotations

import argparse
import logging
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)


#: מסמך שבו ``color`` הוא **מערך** אינו פתק חוקי — אף כותב אינו מייצר
#: אחד כזה — אבל הוא יכול לשבת במסד מכתיבה ישירה או מגיבוי פגום, והוא
#: המקרה היחיד שבו הסקריפט הזה עלול **להרוס** נתונים במקום ליישר אותם.
#:
#: **שרשרת הכשל, ושלושת חוליותיה מתועדות ב-MongoDB:**
#:
#: 1. ``distinct`` מפרק מערכים — "If the value of the specified field is an
#:    array, distinct considers each element of the array as a separate
#:    value" (``reference/command/distinct``). כלומר ``["#FFFFCC", "x"]``
#:    תורם את המחרוזת ``"#FFFFCC"`` לסריקה, ונראה בדיוק כמו ערך רגיל.
#: 2. שאילתת שוויון תואמת **איבר** במערך — "To query if the array field
#:    contains at least one element with the specified value, use the filter
#:    ``{ <field>: <value> }``" (``tutorial/query-arrays``). כלומר המסמך
#:    נספר ונכנס לעדכון.
#: 3. ``$set`` דורס את השדה כולו, ולכן המערך היה מוחלף במחרוזת אחת —
#:    **איבוד האיברים האחרים**, בפעולה שכל מטרתה לא לשנות שום צבע בכוח.
#:
#: ההגנה היא ``$type: "array"``, שהוא **היחיד** שמתייחס לשדה עצמו ולא
#: לאיבריו: "Queries for ``$type: 'array'`` return documents where the field
#: itself is an array" (``reference/operator/query/type``). ``$type:
#: "string"`` דווקא **אינו** מגן — על מערך הוא תואם אם איבר אחד מתאים.
_NOT_AN_ARRAY = {"$not": {"$type": "array"}}


def _scalar_color_filter(value: Any) -> Dict[str, Any]:
    """הפילטר שמזהה **בדיוק** את המסמכים שבהם ``color`` הוא הערך הזה כשדה.

    מקום אחד לספירה ולעדכון כאחד. שני פילטרים שהיו נכתבים בנפרד הם בדיוק
    המצב שבו סופרים קבוצה אחת ומעדכנים אחרת — והמונה היה מדווח "לא נכתבו
    כולם" על הסיבה הלא נכונה.
    """
    return {"color": {"$eq": value, **_NOT_AN_ARRAY}}


def plan_color_migration(db: Any, *, normalize_legacy: bool = False) -> Dict[str, Any]:
    """מה היה משתנה — **בלי לכתוב דבר**.

    מחזיר לכל ערך מאוחסן את היעד שלו ואת מספר הפתקים שנושאים אותו, מחולק
    לשלוש קבוצות: מה שמתקפל לפלטה, מה שנשאר ``legacy``, ומה שכבר במקומו.

    ``distinct`` ולא סריקת מסמכים: מספר הצבעים **המובחנים** קטן בסדרי גודל
    ממספר הפתקים, ולכן זו שאילתה אחת קלה במקום מעבר על האוסף. המחיר הוא
    שהוא מפרק מערכים, וכל הספירות והעדכונים כאן עוברים דרך
    :func:`_scalar_color_filter` בגלל זה.
    """
    from sticky_notes_target import NOTE_COLORS, resolve_note_color

    notes = db.sticky_notes
    stored_values: List[Any] = list(notes.distinct("color"))
    # נספר ומדווח, ולעולם לא נכתב. ראו את ההערה על ``_NOT_AN_ARRAY``.
    array_valued = notes.count_documents({"color": {"$type": "array"}})

    to_palette: List[Tuple[Any, str, int]] = []
    legacy_reshaped: List[Tuple[Any, str, int]] = []
    already_ok = 0
    unreadable = 0

    for value in stored_values:
        count = notes.count_documents(_scalar_color_filter(value))
        if isinstance(value, str) and value in NOTE_COLORS:
            already_ok += count
            continue

        # ``default=None`` — ערך שאי אפשר לפענח כלל (``None``, מספר, זבל)
        # מוחזר כ-``""`` ואינו מקבל ברירת מחדל בכוח. הוא נספר ומדווח, ולא
        # נכתב: הוא כבר מוצג כצהוב בקריאה, וכתיבה עליו הייתה הופכת ניחוש
        # של שכבת התצוגה לעובדה במסד.
        if count == 0:
            # הערך הגיע מפירוק מערך בלבד — אין אף מסמך שנושא אותו כשדה.
            continue

        target = resolve_note_color(value, default=None)
        if not target:
            unreadable += count
            continue

        if target in NOTE_COLORS:
            to_palette.append((value, target, count))
        elif normalize_legacy and target != value:
            legacy_reshaped.append((value, target, count))
        else:
            already_ok += count

    return {
        "distinct_values": len(stored_values),
        "to_palette": to_palette,
        "legacy_reshaped": legacy_reshaped,
        "already_ok": already_ok,
        "unreadable": unreadable,
        "array_valued": array_valued,
        "total_notes": notes.count_documents({}),
    }


def apply_color_migration(db: Any, plan: Dict[str, Any]) -> Dict[str, int]:
    """מחיל את התוכנית, ו**בודק את מה שהמסד החזיר**.

    ``update_many`` מדווח על העבודה שנעשתה ב-``modified_count`` ואינו
    זורק כשלא נגע בכלום. דיווח הצלחה שנשען על "לא נזרקה חריגה" הוא בדיוק
    האישור השקרי ש-``CRITICAL-PATTERNS`` K11 מתאר, ולכן המונה שמוחזר כאן
    נגזר ממה שהמסד אמר ולא ממה שביקשנו.
    """
    moved = 0
    mismatched = 0

    for value, target, expected in plan["to_palette"] + plan["legacy_reshaped"]:
        result = db.sticky_notes.update_many(_scalar_color_filter(value), {"$set": {"color": target}})
        modified = int(getattr(result, "modified_count", 0) or 0)
        moved += modified
        if modified != expected:
            # אינו כשל בהכרח — פתק יכול היה להשתנות בין הספירה לכתיבה —
            # אבל הוא **חייב להיראות**, כי הוא גם הצורה שבה כתיבה שלא
            # נתפסה הייתה מתחבאת.
            mismatched += 1
            log.warning(
                "‏%r ← %r: נכתבו %d מתוך %d שנספרו", value, target, modified, expected
            )

    return {"moved": moved, "mismatched": mismatched}


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="מיגרציה של צבעי פתקים לפלטה")
    parser.add_argument("--apply", action="store_true", help="לכתוב בפועל, ולא רק לדווח")
    parser.add_argument(
        "--normalize-legacy",
        action="store_true",
        help="ליישר גם את צורת הכתיבה של hex שאינו בפלטה (אותו צבע, כתיב אחיד)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        from webapp.app import get_db
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("לא ניתן לייבא את get_db מ-webapp.app") from exc

    db = get_db()
    plan = plan_color_migration(db, normalize_legacy=args.normalize_legacy)

    print("— צבעי פתקים —")
    print(f"  סה\"כ פתקים:              {plan['total_notes']}")
    print(f"  ערכי צבע מובחנים:        {plan['distinct_values']}")
    print(f"  כבר במזהה/בצורה תקינה:   {plan['already_ok']}")
    print(f"  שאי אפשר לפענח (נשארים): {plan['unreadable']}")
    if plan["array_valued"]:
        print(f"  ⚠ עם color שהוא מערך:     {plan['array_valued']}  (לא נגעתי בהם — ראו את ההערה בקוד)")

    def _show(title: str, rows: List[Tuple[Any, str, int]]) -> int:
        if not rows:
            return 0
        print(f"\n  {title}")
        for value, target, count in sorted(rows, key=lambda r: -r[2]):
            print(f"    {value!r:24} ← {target:16} ({count} פתקים)")
        return sum(r[2] for r in rows)

    pending = _show("מתקפלים לפלטה:", plan["to_palette"])
    pending += _show("יישור כתיב (legacy):", plan["legacy_reshaped"])

    if not args.apply:
        if pending:
            print(f"\n  {pending} פתקים ישתנו. הרץ עם --apply כדי לכתוב.")
        else:
            print("\n  אין מה לשנות.")
        return 0

    outcome = apply_color_migration(db, plan)
    print(f"\n  עודכנו {outcome['moved']} פתקים.")
    if outcome["mismatched"]:
        print(f"  ⚠ {outcome['mismatched']} ערכים נכתבו בכמות שונה מהספירה — ראה את הלוג.")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
