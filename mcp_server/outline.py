"""חילוץ מפת סימבולים מקובץ פייתון, לניווט בקבצים גדולים.

הכלי מחזיר שם, שורת התחלה ושורת סיום לכל פונקציה ומחלקה, כדי שהקורא
יוכל להמשיך ל-``lines=[start, end]`` במקום לנחש חלון. ``webapp/app.py``
הוא 20,035 שורות; בלי מפה, סוכן שמחפש בו פונקציה קורא ומנחש.

**ערוץ הכשל הוא ערך ההחזרה, לא חריגה.** הפונקציה מחזירה תמיד מילון עם
``status``: ``"ok"`` או ``"no_outline"``. קורא שבודק רק אם נזרקה חריגה
יקבל "אין אאוטליין" בשקט ויחשוב שהקובץ ריק — זהו דפוס K11 ב-
``amir-bug-patterns``, ולכן הבחירה מוצהרת כאן ולא משתמעת.
"""

from __future__ import annotations

import ast
from typing import Any

#: מרחב שמות בפייתון הוא פונקציה או מחלקה. ``if``/``try``/``with``/``for``
#: **אינם** — הם משנים זרימה, לא שיוך. לכן המעבר חוצה אותם בלי להוסיף
#: תחילית, ופונקציה שהוגדרה בתוך ``except ImportError`` נשארת ברמה שלה.
_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
_SCOPE_NODES = _FUNCTION_NODES + (ast.ClassDef,)

_PYTHON_SUFFIX = ".py"


def extract_outline(text: str, path: str, symbol: str | None = None) -> dict[str, Any]:
    """מפת הסימבולים של ``text``, או ``no_outline`` עם הסיבה.

    ``symbol`` מסנן לפי תת-מחרוזת ב**שם המלא**, ללא תלות ברישיות. לכן
    ``symbol="build_mcp"`` מחזיר גם את הפונקציה וגם את כל מה שמוגדר
    בתוכה — "תן לי הכול תחת המרחב הזה". ``total`` סופר את ההתאמות אחרי
    הסינון, כי עליו נשען העימוד.
    """
    if not path.endswith(_PYTHON_SUFFIX):
        return {"status": "no_outline", "reason": "unsupported_language"}

    # ההרחבה הגורפת עוטפת **רק** את הפרסינג, ובכוונה. הקלט הוא קובץ
    # שמישהו אחר כתב, וסוג החריגה משתנה בין גרסאות פייתון: בייט אפס הוא
    # ``SyntaxError`` ב-3.11 ו-``ValueError`` במקומות אחרים, ו-surrogate
    # לא חוקי הוא ``UnicodeEncodeError``. מניית סוגים כאן היא בדיוק
    # הגישה השברירית שהכלל נגד הרחבת except בא למנוע — הרחבה מנומקת
    # עדיפה על רשימה שתתיישן בשקט.
    #
    # מעבר העץ שמתחת רץ **מחוץ** ל-``try``: באג שלנו חייב ליפול בקול ולא
    # להתחפש ל"אין אאוטליין" על קובץ תקין לגמרי.
    try:
        tree = ast.parse(text)
    except Exception as error:
        return {
            "status": "no_outline",
            "reason": "parse_error",
            "error_type": type(error).__name__,
            "line": getattr(error, "lineno", None),
        }

    rows = _collect(tree)

    # ממוין לפי שורת התחלה, ושובר-שוויון לפי שם. אין כאן מקרה של מעטר
    # משותף — מעטר שייך לסימבול אחד — אבל שובר-שוויון קבוע הוא מה שהופך
    # את גבול העמוד ליציב בין קריאה לקריאה.
    rows.sort(key=lambda row: (row["start"], row["name"]))

    if symbol:
        needle = symbol.lower()
        rows = [row for row in rows if needle in row["name"].lower()]

    return {"status": "ok", "symbols": rows, "total": len(rows)}


def _collect(tree: ast.AST) -> list[dict[str, Any]]:
    """מעבר על העץ עם מחסנית מפורשת, ולא ברקורסיה.

    קינון עמוק לא יכול לייצר ``RecursionError`` בצד שלנו — וזה מה שמאפשר
    ל-``except`` שלמעלה להישאר צר סביב הפרסינג בלבד, בלי פיתוי להרחיב
    אותו כדי לבלוע נפילה של המעבר.
    """
    rows: list[dict[str, Any]] = []
    stack: list[tuple[ast.AST, str]] = [(tree, "")]
    while stack:
        node, prefix = stack.pop()
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _SCOPE_NODES):
                name = f"{prefix}{child.name}"
                rows.append(
                    {
                        "name": name,
                        # שורת ההתחלה היא של המעטר הראשון ולא של ה-``def``.
                        # ב-``webapp/app.py`` 203 מתוך 408 הפונקציות ברמה
                        # העליונה מעוטרות, ובלי זה טווח שנקרא לפי האאוטליין
                        # היה מתחיל **אחרי** ``@app.route(...)`` — כלומר
                        # מחמיץ את השורה שמזהה את הנתיב.
                        "start": min(
                            [child.lineno] + [d.lineno for d in child.decorator_list]
                        ),
                        "end": child.end_lineno or child.lineno,
                    }
                )
                stack.append((child, f"{name}."))
            else:
                stack.append((child, prefix))
    return rows
