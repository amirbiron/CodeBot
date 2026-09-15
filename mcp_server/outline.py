"""חילוץ מפת סימבולים מקובץ, לניווט בקבצים גדולים.

הכלי מחזיר שם, שורת התחלה ושורת סיום לכל סימבול, כדי שהקורא יוכל להמשיך
ל-``lines=[start, end]`` במקום לנחש חלון. ``webapp/app.py`` הוא מעל 20,000
שורות; בלי מפה, סוכן שמחפש בו פונקציה קורא ומנחש.

**המודול הזה מנתב בלבד.** הוא בוחר סורק לפי סיומת, מריץ אותו, וממיין ומסנן
את מה שחזר. הלוגיקה של כל שפה יושבת ב-``outline_scanners/``, וה-docstring
שם מתאר את החוזה שכל סורק ממלא.

**המיון והסינון יושבים כאן, לא בסורקים** — הנימוק ב-``outline_scanners``.

**ערוץ הכשל הוא ערך ההחזרה, לא חריגה.** הפונקציה מחזירה תמיד מילון עם
``status``: ``"ok"`` או ``"no_outline"``. קורא שבודק רק אם נזרקה חריגה
יקבל "אין אאוטליין" בשקט ויחשוב שהקובץ ריק — זהו דפוס K11 ב-
``amir-bug-patterns``, ולכן הבחירה מוצהרת כאן ולא משתמעת.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from .outline_scanners import css as _css
from .outline_scanners import html as _html
from .outline_scanners import python as _python
from .outline_scanners import rst as _rst

#: ``\r`` שאינו חלק מ-``\r\n``. ה-lookahead השלילי הוא כל ההבחנה: CRLF
#: הוא המקרה הנפוץ ושתי ספירות השורות מסכימות עליו, ולכן הוא חייב להמשיך
#: לעבוד. רק CR בודד — הפורמט של Mac שלפני 2001 — מפריד ביניהן.
#:
#: ``search`` ולא ``replace``: הוא עוצר על ההתאמה הראשונה ואינו מקצה עותק
#: של הטקסט, שיכול להיות 10MB לפי ``RANGE_READ_MAX_BYTES``.
_CR_WITHOUT_LF = re.compile(r"\r(?!\n)")

#: **השורה היחידה שהמסלול הזה כותב, והיא נכתבת כאן ולא בסורקים.** כאן יש גם
#: את הנתיב וגם את גודל הקלט, ולכן זו הנקודה היחידה שבה שורה אחת מזהה מה
#: נסרק; סורק אינו מקבל נתיב בכלל, לפי החוזה.
#:
#: ולמה בכלל: קלט פתולוגי על המסלול הזה נמדד כיקר, ואז אין בקוד שום רשומה
#: שאומרת **איזה** קובץ. עד #3379 הוא גם חסם את לולאת האירועים, כי הגוף
#: סינכרוני וה-SDK קרא לו ישירות; מאז הוא רץ על חוט עובד, כך שהוא תופס
#: זיכרון משותף וחוט מתוך מספר חסום במקום להשבית את כולם. השורה הזאת
#: נחוצה בדיוק כמו קודם — היא עדיין הדבר היחיד שמזהה את הקובץ.
#: ``debug`` ולא ``info``, כי זו בקשה רגילה ואין סיבה שהיא תרעיש בלוג
#: בייצור.
#:
#: .. warning::
#:
#:    **והיא אינה נראית בייצור כפי שהתהליך עולה היום — נמדד.** פקודת
#:    ההרצה המתועדת היא ``uvicorn mcp_server.app:app``, ואף מודול תחת
#:    ``mcp_server/`` אינו קורא ל-``basicConfig``, ל-``dictConfig`` או
#:    ל-``setLevel``: הקונפיגורציה יושבת ב-``main.py``, ב-``webapp/app.py``
#:    וב-``services/webserver.py``, שאף אחד מהם אינו נטען בתהליך הזה.
#:    המדידה: ה-root ב-``WARNING`` עם **אפס** handlers,
#:    ``isEnabledFor(DEBUG)`` הוא ``False``, ו-stdout ו-stderr ריקים סביב
#:    קריאה ל-``extract_outline``. וגם חיבור של
#:    ``setup_structlog_logging`` לא היה מספיק לבד, כי ברירת המחדל שלו
#:    היא ``INFO``.
#:
#:    השורה נשארת בכוונה, ולא נמחקת: היא הרשומה היחידה שמזהה **איזה**
#:    קובץ נסרק, וזה מה שהיה חסר כשקלט פתולוגי נעל את השרת. חיבור הלוגים
#:    לתהליך ה-MCP הוא שינוי תשתיתי שחורג מהיקף השינוי הזה, והוא מדווח
#:    בנפרד.
logger = logging.getLogger(__name__)

#: הסיומת ← הסורק. **זהו המקום היחיד שאומר מה נתמך**, וזה מכוון: תיאור
#: הפרמטר ``outline`` ב-``server.py`` (‏``_OUTLINE_PARAM_DOC``) והתיעוד
#: ב-``docs/mcp-server.rst`` מתארים את הטבלה הזו, ושתי רשימות שצריך
#: לסנכרן היו נסחפות זו מזו בשקט.
#:
#: **הרשימה ישבה עד כה בתיאור הכלי**, ועברה לתיאור הפרמטר כשתיאור הכלי
#: קוצר מ-2,482 תווים — לקוח שחותך תיאור ארוך חתך בדיוק את הרשימה הזו.
#: ‏``test_the_description_names_every_suffix_the_outline_router_supports``
#: קורא מהמיקום החדש.
#:
#: המפתחות באותיות קטנות, וההשוואה מנרמלת — ``.pyi`` הוא פייתון תקין
#: ש-``ast.parse`` מנתחת, והוא נפוץ הרבה יותר מסיומת באותיות גדולות.
_SCANNERS: dict[str, Callable[[str], dict[str, Any]]] = {
    ".py": _python.extract,
    ".pyi": _python.extract,
    ".html": _html.extract,
    ".htm": _html.extract,
    ".jinja": _html.extract,
    ".jinja2": _html.extract,
    ".j2": _html.extract,
    ".css": _css.extract,
    ".rst": _rst.extract,
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

    # **שתי הגדרות שונות של "שורה", ולכן סירוב מפורש כשהן נפרדות.**
    #
    # ``apply_line_range`` מפצל ב-``split("\n")``, וההערה שם (handlers.py)
    # מנמקת למה: ``file.lines_count`` נספר כך ומשותף עם הוובאפ. אבל
    # ``ast.parse`` סופר עם universal newlines, כלומר ``\r`` בודד הוא אצלו
    # שורה חדשה. בקובץ שמכיל ``\r`` שאינו חלק מ-``\r\n`` השתיים נפרדות —
    # וזה נמדד: ``ast`` דיווח על שורה 5 בטקסט ש-``split("\n")`` רואה כשורה
    # אחת, מה שהפיל ``IndexError`` ב-``_start_line``, והוא **בורח דרך
    # הכלי** כי אף שלב במסלול לא עוטף בחריגה.
    #
    # תיקון ה-``IndexError`` לבדו לא היה מספיק, והוא המלכודת כאן: המפה
    # הייתה חוזרת תקינה למראה ומצביעה על שורה ש-``lines=[start, end]``
    # לא מגיעה אליה. הערך היחיד של המפה הוא שאפשר להמשיך ממנה לטווח —
    # מפה שמצביעה לשומקום גרועה ממפה שאין.
    #
    # CRLF **אינו** מושפע ועובד במלואו: שם שתי הספירות זהות, וזה המקרה
    # הנפוץ. מה שנדחה הוא ``\r`` בודד בלבד.
    if _CR_WITHOUT_LF.search(text):
        return {"status": "no_outline", "reason": "inconsistent_line_endings"}

    # ``chars`` ולא ``bytes``, כי ``len`` על ``str`` מודד תווים. השם הקודם
    # היה ``bytes`` והוא שיקר בדיוק בקלט שבגללו הרשומה קיימת: נמדד שעברית
    # היא 1.83 בתים לתו (60 תווים ← 110 בתים), ולכן עמוד עברי היה נרשם
    # כחצי מגודלו. ותקרות הכלי — 500KB ו-10MB — נמדדות **בבתים**, כלומר
    # המספר כאן אינו בר-השוואה אליהן ישירות, וזה בדיוק מה שמי שקורא את
    # הרשומה בזמן תקיעה צריך לדעת.
    #
    # ולא ``len(text.encode("utf-8"))``: זה עותק שלם של הקלט — עד 10MB —
    # בכל סריקה, בשביל רשומה שברירת המחדל שלה אינה נכתבת בכלל.
    logger.debug("outline scan: path=%s chars=%d", path, len(text))
    result = scanner(text)

    # **החוזה נאכף כאן, ובקול.** גרסה קודמת בדקה רק
    # ``result.get("status") == "no_outline"`` ואז ניגשה ל-``result["symbols"]``.
    # זה עובד על הסורק היחיד שקיים, אבל סורק עתידי שיחזיר צורה שלישית —
    # ``{"status": "error", ...}``, ``None``, מילון ריק — היה מפיל
    # ``KeyError`` או ``AttributeError`` סתומים שלא אומרים מי הסורק ומה
    # הוא החזיר, ו**המסלול עד הכלי אינו עוטף בחריגה**: לא
    # ``_outline_response`` ולא ``RepoBackend.get_file``.
    #
    # הבחירה כאן היא **לא** לבלוע ולהחזיר ``no_outline``. סורק שמחזיר
    # צורה מחוץ לחוזה הוא באג שלנו, וזו בדיוק אותה הבחנה ש-
    # ``test_a_bug_in_the_traversal_is_not_swallowed_as_no_outline``
    # מקבע שכבה אחת פנימה: קלט פגום חוזר כערך, באג נופל. מה שהיה חסר זה
    # לא הבליעה אלא **האבחון** — ולכן ההודעה נוקבת בסורק ובמה שחזר.
    # ``isinstance`` על **הערך** ולא רק נוכחות המפתח: ``{"symbols": None}``
    # עובר בדיקת נוכחות ואז מפיל ``AttributeError`` על ``.sort`` — אותה
    # חריגה סתומה בשורה אחת מאוחר יותר. בדיקת טיפוס לפני שימוש היא U3.
    if isinstance(result, dict) and isinstance(result.get("symbols"), list):
        rows: list[dict[str, Any]] = result["symbols"]
        # **גם תוכן הרשימה, ולא רק העובדה שהיא רשימה.** הבדיקה החיצונית
        # לבדה עצרה שלוש צורות ופספסה את הרביעית, שהיא החמורה: רשומה בלי
        # ``end`` עברה את כל המסלול והגיעה ללקוח כ-``ok: true`` עם
        # ``status: outline``. ה-``sort`` שלמטה נוגע רק ב-``start`` וב-
        # ``name``, ולכן ``end`` לא נבדק **בשום מקום** — וזה השדה שכל
        # הפיצ'ר קיים בשבילו, כי ממנו נגזר ה-``lines=`` הבא.
        invalid = _first_invalid_row(rows)
        if invalid >= 0:
            raise TypeError(
                f"סורק האאוטליין של {path!r} החזיר רשומה שאינה בחוזה "
                f"(נדרשים name כמחרוזת, start ו-end כמספרים שלמים) "
                f"במקום {invalid}: {rows[invalid]!r}"
            )
    elif (
        isinstance(result, dict)
        and result.get("status") == "no_outline"
        # ``reason`` אינו רשות: התיעוד מבטיח אותו בכל תשובת ``no_outline``,
        # והוא ההבדל בין "הקובץ לא נתמך" ל"התחביר שבור" אצל הקורא.
        and isinstance(result.get("reason"), str)
    ):
        return result
    else:
        raise TypeError(
            f"סורק האאוטליין של {path!r} החזיר צורה שאינה בחוזה של "
            f"outline_scanners (נדרש 'symbols', או status='no_outline' עם "
            f"'reason'): {result!r}"
        )

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


def _first_invalid_row(rows: list[Any]) -> int:
    """המקום של הרשומה הראשונה שאינה בחוזה, או ``-1`` אם כולן תקינות.

    מוחזר **מקום** ולא הרשומה עצמה, כי ``None`` הוא גם ערך פגום אפשרי
    ואז "אין פגומה" ו"הפגומה היא None" היו נראים אותו דבר לקורא.

    ``bool`` הוא תת-מחלקה של ``int`` בפייתון ולכן ``start=True`` יעבור
    כאן. זה מקרה תיאורטי שאין לו מסלול הגעה מאף סורק, ובדיקה שתחסום
    אותו הייתה עולה יותר ממה שהיא מונעת.
    """
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            return index
        if not isinstance(row.get("name"), str):
            return index
        if not isinstance(row.get("start"), int) or not isinstance(row.get("end"), int):
            return index
    return -1


def _scanner_for(path: str) -> Callable[[str], dict[str, Any]] | None:
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
