"""סורק האאוטליין של פייתון — פונקציות ומחלקות, עם טווח שורות.

הרקע: ``webapp/app.py`` הוא מעל 20,000 שורות. בלי מפה, סוכן שמחפש בו פונקציה
קורא טווח ומנחש. עם מפה הוא מקבל שורת התחלה וסיום ועובר ל-``lines=``.

**ערוץ הכשל הוא ערך ההחזרה, לא חריגה** — קובץ שאינו נפרס מוחזר כ-
``no_outline`` עם הסיבה, ולא כזריקה. זהו דפוס K11 ב-``amir-bug-patterns``,
ולכן הבחירה מוצהרת כאן ולא משתמעת.
"""

from __future__ import annotations

import ast
from typing import Any

#: מרחב שמות בפייתון הוא פונקציה או מחלקה. ``if``/``try``/``with``/``for``
#: **אינם** — הם משנים זרימה, לא שיוך. לכן המעבר חוצה אותם בלי להוסיף
#: תחילית, ופונקציה שהוגדרה בתוך ``except ImportError`` נשארת ברמה שלה.
_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
_SCOPE_NODES = _FUNCTION_NODES + (ast.ClassDef,)


def extract(text: str, lines: list[str]) -> dict[str, Any]:
    """מפת הסימבולים של ``text``, או ``no_outline`` עם הסיבה."""
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

    return {"symbols": _collect(tree, lines)}


def _start_line(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, lines: list[str]
) -> int:
    """שורת ההתחלה: המעטר הראשון, ולא ה-``def``.

    ב-``webapp/app.py`` 203 מתוך 408 הפונקציות ברמה העליונה מעוטרות, וטווח
    שהיה מתחיל ב-``def`` היה מחמיץ את ``@app.route(...)``.

    ``decorator_list[i].lineno`` הוא שורת ה**ביטוי**, לא שורת ה-``@``.
    בכתיב הרגיל הם זהים, אבל ב-``@(``ואז ירידת שורה הביטוי מתחיל שורה
    מאוחר יותר — נמדד. לכן סריקה אחורה עד השורה שמתחילה ב-``@``. מעטר
    קודם שייתפס בדרך שייך לאותו סימבול ממילא, ולכן הרחבה כזו נכונה.
    """
    # ``decorator_list`` קיים בוודאות בשלושת הטיפוסים שבחתימה, ולכן גישה
    # ישירה ולא ``getattr`` עם ברירת מחדל — הגנה שהטיפוס כבר נותן היא
    # רעש שמסתיר את מה שבאמת יכול להיכשל.
    decorators = node.decorator_list
    start = min([node.lineno] + [d.lineno for d in decorators])
    if not decorators:
        return start
    # סריקה אחורה עד השורה שפותחת ב-``@``. בין ה-``@`` לבין הביטוי יכולות
    # לשבת שורות ריקות והערות, ולכן הן מדולגות — אבל **רק** אם בסוף נוחתים
    # על ``@`` אמיתי. אם לא, נשארים במקום: עדיף טווח מדויק-חלקית מטווח
    # שבלע שורות של סימבול קודם.
    index = start - 1  # 0-based
    scan = index
    while scan > 0:
        previous = lines[scan - 1].strip()
        if previous.startswith("@"):
            scan -= 1
            index = scan
            continue
        if previous == "" or previous.startswith("#"):
            scan -= 1
            continue
        break
    return index + 1


def _collect(tree: ast.AST, lines: list[str]) -> list[dict[str, Any]]:
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
                        "start": _start_line(child, lines),
                        "end": child.end_lineno or child.lineno,
                    }
                )
                stack.append((child, f"{name}."))
            else:
                stack.append((child, prefix))
    return rows
