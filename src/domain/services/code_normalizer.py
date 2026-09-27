"""ניקוי מינימלי לקוד שמודבק בבוט — ההגדרה היחידה.

**למה יש ניקוי, ולמה רק בבוט.** קוד שמודבק בטלגרם מגיע עם שאריות של הדרך
שעבר: סופי שורה של Windows, BOM, ורווחים מיוחדים שהעתקה מדפדפן או ממעבד
תמלילים משאירה. חלק מהם מפילים קוד: נמדד על Python 3.11 ש-NBSP, NNBSP,
THIN SPACE, IDEOGRAPHIC SPACE ו-ZWSP בתוך קוד מרימים ``SyntaxError``. זה
הצורך שבשבילו נבנה הנרמול (#637), והוא שייך לכניסה הזו בלבד.

**כל שאר הכניסות שומרות בדיוק את מה שנשלח.** עד היום הנרמול ישב גם בשכבת
השמירה (``Repository.save_code_snippet`` ועוד שתיים), ולכן שכתב בשקט גם קבצים
שהגיעו מה-MCP, מהוובאפ ומהעלאת מסמכים: מחק LRM ו-RLM ממסמכים בעברית, מחק
רצפי escape טקסטואליים מקוד מקור (#643), ומחק את ה-newline שבסוף הקובץ
(#1662). ``tests/test_content_cleaning_stays_in_the_bot.py`` נופל אם אחת
הפונקציות כאן נקראת מ-``database/``, ``webapp/`` או ``mcp_server/``.

מודול טהור: בלי I/O, ובזמן ייבוא לא רץ כלום מלבד הגדרות.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Tuple

from src.domain.services.language_detector import MARKDOWN_SUFFIXES

_BOM = "\ufeff"
_ZWSP = "\u200b"

#: מחלקות הכיווניות (Bidi_Class) של תווי ה-embedding, ה-override וה-isolate
#: לפי UAX #9 — תשעת התווים שבטבלה 1 של מאמר Trojan Source (CVE-2021-42574).
#: **מחלקה ולא רשימת תווים:** ההגדרה מתעדכנת עם התקן, והמקור לא מחזיק את
#: התווים עצמם (H1 — תו כזה בקובץ מקור מפיל את bandit ב-B613). נמדד על
#: Python 3.11.15 (Unicode 14.0): בדיוק U+202A–U+202E ו-U+2066–U+2069 נופלים
#: בהן, ו-LRM, RLM ו-ALM (מחלקות L, R ו-AL) לא. הטסטים מקבעים את זה.
_EXPLICIT_BIDI_CLASSES = frozenset({"LRE", "RLE", "PDF", "LRO", "RLO", "LRI", "RLI", "FSI", "PDI"})


@dataclass(frozen=True)
class PasteCleanup:
    """מה :func:`clean_pasted_code` החזירה: הטקסט הנקי, ומה בדיוק נעשה בו.

    הספירות קיימות כדי שהבוט יוכל לומר למשתמש מה נוקה — ניקוי שאיש לא
    מספר עליו הוא בדיוק השכתוב השקט שהמודול הזה בא להחליף.
    """

    text: str
    #: זוגות ``\r\n`` שהפכו ל-``\n``.
    crlf: int = 0
    #: ``\r`` בודד (הפורמט של Mac שלפני 2001) שהפך ל-``\n``.
    lone_cr: int = 0
    #: האם נמחק BOM (אחד או רצף) מתחילת הטקסט.
    bom: bool = False
    #: תווי ``Zs`` שאינם רווח רגיל והוחלפו ברווח רגיל. רק בקוד, לא ב-Markdown.
    special_spaces: int = 0
    #: תווי ZWSP שנמחקו. רק בקוד, לא ב-Markdown.
    zwsp: int = 0
    #: שורות שנמחקו מסופן רווחים או טאבים. רק בקוד, לא ב-Markdown.
    trailing_whitespace_lines: int = 0
    #: מספרי השורות (מ-1, בטקסט הנקי) שיש בהן תו embedding, override או
    #: isolate. **לא נוגעים בהם** — הם יכולים להיות שם בכוונה (FSI ו-PDI סביב
    #: שם משתמש במחרוזת UI בעברית), והמשתמש מקבל עליהם אזהרה.
    bidi_control_lines: Tuple[int, ...] = ()

    @property
    def changed(self) -> bool:
        """האם הטקסט הנקי שונה מזה שנשלח."""
        return bool(
            self.crlf
            or self.lone_cr
            or self.bom
            or self.special_spaces
            or self.zwsp
            or self.trailing_whitespace_lines
        )


def is_markdown_filename(name: object) -> bool:
    """האם שם הקובץ הוא של מסמך Markdown, לפי הסיומת.

    הסיומות הן :data:`~src.domain.services.language_detector.MARKDOWN_SUFFIXES`
    — אותה הגדרה שזיהוי השפה משתמש בה, כדי שקובץ שמזוהה כ-Markdown יקבל גם
    את הניקוי של Markdown. הסיומת נקראת מ-``PurePosixPath(...).suffix`` ולא
    בהשוואת קידומת או סיומת של מחרוזת. שם שאינו מחרוזת אינו Markdown.
    """
    if not isinstance(name, str):
        return False
    return PurePosixPath(name.strip()).suffix.lower() in MARKDOWN_SUFFIXES


def _has_explicit_bidi_control(line: str) -> bool:
    return any(unicodedata.bidirectional(ch) in _EXPLICIT_BIDI_CLASSES for ch in line)


def clean_pasted_code(text: str, *, is_markdown: bool) -> PasteCleanup:
    """הניקוי המינימלי לקוד שמודבק בבוט. מחזירה :class:`PasteCleanup`.

    **בכל קובץ:**

    - ``\\r\\n`` ו-``\\r`` בודד ← ``\\n``.
    - BOM בתחילת הטקסט נמחק — גם כמה ברצף. ``U+FEFF`` במקום אחר אינו BOM ונשאר.

    **רק כש-``is_markdown`` שקרי:**

    - כל תו בקטגוריה ``Zs`` (NBSP, NNBSP, THIN SPACE, IDEOGRAPHIC SPACE
      ועוד) ← רווח רגיל. קטגוריה ולא רשימה, כדי לא לפספס את התו הבא.
    - ZWSP (``U+200B``) נמחק. ב-Markdown הוא לא שובר כלום, ואולי הוכנס בכוונה.
    - רווחים וטאבים בסוף כל שורה נמחקים. ב-Markdown שני רווחים בסוף שורה הם
      Hard break, ולכן שם הם נשארים.

    **לעולם לא נוגעים ב:** LRM, RLM, ALM, ZWNJ, ZWJ, WJ, שאר תווי ``Cf``,
    תווי ``Cc``, רצפי escape טקסטואליים (``"\\u200f"`` בתוך קוד הוא קוד), וה-newline
    בסוף הטקסט. תווי embedding, override ו-isolate נשארים, ומדווחים ב-
    :attr:`PasteCleanup.bidi_control_lines`.

    הניקוי אידמפוטנטי: הרצה שנייה על הטקסט הנקי לא משנה בו דבר.

    :raises TypeError: כש-``text`` אינו מחרוזת. ההמרה של ``None`` למחרוזת
        ריקה היא החלטה של הקורא, לא של הפונקציה.
    """
    if not isinstance(text, str):
        raise TypeError(f"clean_pasted_code expects str, got {type(text).__name__}")

    # כל הרצף שבתחילת הטקסט: גם BOM שני ברצף מפיל קוד (נמדד על Python 3.11),
    # ומחיקה של אחד בלבד הייתה משאירה קוד שבור והופכת הרצה שנייה למשנה.
    out = text.lstrip(_BOM)
    bom = len(out) != len(text)

    crlf = out.count("\r\n")
    if crlf:
        out = out.replace("\r\n", "\n")
    lone_cr = out.count("\r")
    if lone_cr:
        out = out.replace("\r", "\n")

    special_spaces = 0
    zwsp = 0
    trailing_whitespace_lines = 0
    if not is_markdown:
        out, special_spaces, zwsp = _replace_special_spaces_and_drop_zwsp(out)
        # אחרי ההחלפה של Zs, כדי ש-NBSP בסוף שורה ייחתך יחד עם שאר הרווחים.
        out, trailing_whitespace_lines = _trim_trailing_whitespace(out)

    return PasteCleanup(
        text=out,
        crlf=crlf,
        lone_cr=lone_cr,
        bom=bom,
        special_spaces=special_spaces,
        zwsp=zwsp,
        trailing_whitespace_lines=trailing_whitespace_lines,
        bidi_control_lines=explicit_bidi_control_lines(out),
    )


def _replace_special_spaces_and_drop_zwsp(text: str) -> Tuple[str, int, int]:
    """``Zs`` ← רווח רגיל, ו-ZWSP נמחק. מחזירה את הטקסט ואת שתי הספירות."""
    # מסלול מהיר: טקסט ASCII אינו יכול להכיל Zs (חוץ מרווח רגיל) או ZWSP.
    if text.isascii():
        return text, 0, 0
    special_spaces = 0
    zwsp = 0
    kept = []
    for ch in text:
        if ch == _ZWSP:
            zwsp += 1
        elif ch != " " and unicodedata.category(ch) == "Zs":
            special_spaces += 1
            kept.append(" ")
        else:
            kept.append(ch)
    return "".join(kept), special_spaces, zwsp


def _trim_trailing_whitespace(text: str) -> Tuple[str, int]:
    """מוחקת רווחים וטאבים בסוף כל שורה. מחזירה את הטקסט ואת מספר השורות שהשתנו."""
    lines = text.split("\n")
    trimmed = [line.rstrip(" \t") for line in lines]
    changed = sum(1 for before, after in zip(lines, trimmed) if before != after)
    return ("\n".join(trimmed) if changed else text), changed


def explicit_bidi_control_lines(text: object) -> Tuple[int, ...]:
    """מספרי השורות (מ-1, לפי ``\\n``) שיש בהן תו embedding, override או isolate.

    **ההגדרה האחת לזיהוי, לשני צרכנים:** :func:`clean_pasted_code`, שממנה הבוט
    מזהיר בהודעת השמירה, ותצוגת הקוד בוובאפ, דרך
    ``services/code_service.bidi_warning_for_display``. התווים נשמרים כמו שנשלחו,
    ולכן מי שקורא את הקוד אחר כך — גם בקישור שיתוף ציבורי — צריך את האזהרה
    בעמוד עצמו, ולא רק מי ששמר אותו.

    ערך שאינו מחרוזת (למשל שדה פגום במסמך) אינו קוד שמוצג, ולכן אין בו שורות.
    """
    if not isinstance(text, str) or text.isascii():
        return ()
    return tuple(
        number
        for number, line in enumerate(text.split("\n"), start=1)
        if _has_explicit_bidi_control(line)
    )
