"""חילוץ מפת סימבולים מקובץ, לניווט בקבצים גדולים.

הכלי מחזיר שם, שורת התחלה ושורת סיום לכל סימבול, כדי שהקורא יוכל להמשיך
ל-``lines=[start, end]`` במקום לנחש חלון. ``webapp/app.py`` הוא מעל 20,000
שורות; בלי מפה, סוכן שמחפש בו פונקציה קורא ומנחש.

**המודול הזה מנתב בלבד.** הוא בוחר סורק לפי סיומת, מריץ אותו, וממיין ומסנן
את מה שחזר. הלוגיקה של כל שפה יושבת ב-``outline_scanners/``, וה-docstring
שם מתאר את החוזה שכל סורק ממלא.

**המיון והסינון יושבים כאן, לא בסורקים.** הם המאפיינים שהעימוד נשען עליהם,
וסורק חדש שישכפל אותם הוא סורק שאפשר לשכוח בו אחד מהם — והתוצאה תהיה סדר
לא יציב בשפה אחת בלבד, כלומר סימבול שמדלג בין עמודים. מקום אחד, בלי אפשרות
לשכוח.

**ערוץ הכשל הוא ערך ההחזרה, לא חריגה.** הפונקציה מחזירה תמיד מילון עם
``status``: ``"ok"`` או ``"no_outline"``. קורא שבודק רק אם נזרקה חריגה
יקבל "אין אאוטליין" בשקט ויחשוב שהקובץ ריק — זהו דפוס K11 ב-
``amir-bug-patterns``, ולכן הבחירה מוצהרת כאן ולא משתמעת.
"""

from __future__ import annotations

from typing import Any, Callable

from .outline_scanners import python as _python

#: הסיומת ← הסורק. **זהו המקום היחיד שאומר מה נתמך**, וזה מכוון: תיאור
#: הכלי ב-``server.py`` והתיעוד ב-``docs/mcp-server.rst`` מתארים את הטבלה
#: הזו, ושתי רשימות שצריך לסנכרן היו נסחפות זו מזו בשקט.
#:
#: המפתחות באותיות קטנות, וההשוואה מנרמלת — ``.pyi`` הוא פייתון תקין
#: ש-``ast.parse`` מנתחת, והוא נפוץ הרבה יותר מסיומת באותיות גדולות.
_SCANNERS: dict[str, Callable[[str, list[str]], dict[str, Any]]] = {
    ".py": _python.extract,
    ".pyi": _python.extract,
}


def extract_outline(text: str, path: str, symbol: str | None = None) -> dict[str, Any]:
    """מפת הסימבולים של ``text``, או ``no_outline`` עם הסיבה.

    ``symbol`` מסנן לפי תת-מחרוזת ב**שם המלא**, ללא תלות ברישיות. לכן
    ``symbol="build_mcp"`` מחזיר גם את הפונקציה וגם את כל מה שמוגדר
    בתוכה — "תן לי הכול תחת המרחב הזה". ``total`` סופר את ההתאמות אחרי
    הסינון, כי עליו נשען העימוד.
    """
    scanner = _scanner_for(path)
    if scanner is None:
        return {"status": "no_outline", "reason": "unsupported_language"}

    # הסורק מקבל גם את הטקסט וגם את פיצולו לשורות, כי כמעט כולם צריכים את
    # שניהם — פייתון למעטרים, הסורקים הלקסיקליים לחישוב מספר שורה. פיצול
    # אחד כאן זול יותר מפיצול בכל סורק, והוא גם מבטיח שכולם סופרים שורות
    # באותו אופן בדיוק.
    result = scanner(text, text.split("\n"))
    if result.get("status") == "no_outline":
        return result

    rows: list[dict[str, Any]] = result["symbols"]

    # ממוין לפי שורת התחלה, ושובר-שוויון לפי שם. אין כאן מקרה של מעטר
    # משותף — מעטר שייך לסימבול אחד — אבל שובר-שוויון קבוע הוא מה שהופך
    # את גבול העמוד ליציב בין קריאה לקריאה.
    rows.sort(key=lambda row: (row["start"], row["name"]))

    if symbol:
        # ``casefold`` ולא ``lower``: זה הפרימיטיב להשוואה חסרת-רישיות.
        # ``lower`` מפספסת מיפויים של יותר מתו אחד, למשל ``straße`` מול
        # ``STRASSE``.
        needle = symbol.casefold()
        rows = [row for row in rows if needle in row["name"].casefold()]

    return {"status": "ok", "symbols": rows, "total": len(rows)}


def _scanner_for(path: str) -> Callable[[str, list[str]], dict[str, Any]] | None:
    """הסורק שמתאים לסיומת של ``path``, או ``None`` אם אין כזה.

    ההתאמה נבדקת מהסיומת **הארוכה ביותר** כלפי מטה, ולא לפי סדר המילון:
    כשתתווסף סיומת מורכבת (``.html.j2`` לצד ``.j2``), הראשונה שתתאים חייבת
    להיות הספציפית יותר. עם הטבלה של היום התוצאה זהה בכל סדר, וזו בדיוק
    הסיבה לקבוע את הכלל עכשיו — אחר כך זה באג שקט שתלוי בסדר הכתיבה.
    """
    lowered = path.casefold()
    for suffix in sorted(_SCANNERS, key=len, reverse=True):
        if lowered.endswith(suffix):
            return _SCANNERS[suffix]
    return None
