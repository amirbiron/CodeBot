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

#: ``.pyi`` הוא פייתון תקין ש-``ast.parse`` מנתחת, והוא נפוץ הרבה יותר
#: מסיומת באותיות גדולות. הבדיקה מנורמלת, ולא השוואת מחרוזת אחת.
_PYTHON_SUFFIXES = frozenset({".py", ".pyi"})

#: תקרת אורך לשם סימבול. השם הארוך ביותר בריפו הזה הוא 81 תווים
#: (``DatabaseManager.connect._init_noop_collections.NoOpCollection.find_one_and_update``),
#: אז 200 לא ייגע בשום דבר אמיתי. מה שהוא כן עושה: הופך את גודל הרשומה
#: לחסום, וזה מה שמאפשר להוכיח שעמוד שלם נכנס בתקציב הפלט במקום לקוות
#: לזה ולחתוך בזמן ריצה. חיתוך בזמן ריצה בתוך עמוד + עימוד אריתמטי הוא
#: בדיוק הצירוף שמאבד סימבולים בשקט.
_MAX_NAME_LENGTH = 200


def extract_outline(text: str, path: str, symbol: str | None = None) -> dict[str, Any]:
    """מפת הסימבולים של ``text``, או ``no_outline`` עם הסיבה.

    ``symbol`` מסנן לפי תת-מחרוזת ב**שם המלא**, ללא תלות ברישיות. לכן
    ``symbol="build_mcp"`` מחזיר גם את הפונקציה וגם את כל מה שמוגדר
    בתוכה — "תן לי הכול תחת המרחב הזה". ``total`` סופר את ההתאמות אחרי
    הסינון, כי עליו נשען העימוד.
    """
    if not any(path.lower().endswith(suffix) for suffix in _PYTHON_SUFFIXES):
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

    rows = _collect(tree, text.split("\n"))

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


def _bounded(name: str) -> str:
    """שם חסום באורך, כדי שגודל הרשומה יהיה חסום.

    בלי חסם, שום ערך של ``per_page`` אינו בטוח-בהוכחה מול תקציב הפלט —
    ואז נדרש חיתוך בזמן ריצה, שיחד עם עימוד אריתמטי מאבד סימבולים.
    """
    if len(name) <= _MAX_NAME_LENGTH:
        return name
    return name[: _MAX_NAME_LENGTH - 1] + "\u2026"


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
    decorators = getattr(node, "decorator_list", [])
    start = min([node.lineno] + [d.lineno for d in decorators])
    if not decorators:
        return start
    index = start - 1  # 0-based
    while index > 0 and lines[index - 1].lstrip().startswith("@"):
        index -= 1
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
                        "name": _bounded(name),
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
