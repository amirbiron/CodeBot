"""המודל המשותף של סעיפי מסמך — ``Section``, ``Document``, ופונקציות העץ.

מודול טהור בלי שום תלות ב-MCP ובלי תלות באף פארסר. הוא מחזיק את כל מה
ש**אינו תלוי בשפת המקור**: מבנה הסעיף, מבנה המסמך, חישוב ``end_line``
וההיררכיה, והפונקציות שעונות על שאלות מעל העץ — חיפוש כותרת, טווח,
חיתוך טקסט, שכנים, תוכן עניינים והצעות.

**למה מודול נפרד, ולא "פשוט להשאיר ב-``rst_parser``".** יש צרכן שני
לאותו חוזה — ``services/md_parser.py``, פארסר ה-Markdown. שני פארסרים
שבונים ``Section`` משלהם ומחשבים
``end_line`` משלהם הם **שתי הגדרות לאותו כלל**, וזה בדיוק הכשל שהמודול
הזה קיים כדי למנוע: מי שיתקן באג בחישוב ההיררכיה יתקן אותו באחד משניהם,
והשני יסטה בשקט. במודול הזה יש הגדרה אחת, ושני הפארסרים בונים לתוכה.

**התקדים בריפו הוא מודולי-האחות של הסורקים.** ``_lines.py`` ו-``_ceiling.py``
יושבים ליד סורקי האאוטליין בדיוק מאותה סיבה, וה-docstring של
``_ceiling.py`` מנמק זאת במפורש — "הגיון שמשותף לכמה סורקים גר במודול
משלו", כי ייבוא לרוחב מסורק שכן היה יוצר תלות בין סורקים. כאן זה אותו
דבר בדיוק בין פארסרים.

**הכיוון חד-סטרי, וזה נאכף בקריאה ולא בהערה.** המודול הזה **אינו מייבא
אף פארסר**, ולכן אינו יכול להיות תלוי בשפה כלשהי. הפארסרים מייבאים ממנו.

**מה שהמודול הזה אינו יודע עליו כלום, בכוונה:** תווי adornment, סולמיות,
front matter, גדרות קוד — כל אלה הם עניין של הפארסר שבונה את הסעיפים.
כאן לא מופיעה אף מחרוזת שתלויה בתחביר של שפה אחת.

**שני הפארסרים שבונים לתוך המודול הזה**, כדי שהקורא לא יצטרך לחפש:
``services/rst_parser.py`` ו-``services/md_parser.py``. שניהם מייצאים
מחדש את השמות שכאן, ולכן ``rst_parser.Section`` ו-``md_parser.Section``
הם **אותו אובייקט מחלקה** — וזה מה שמאפשר לצרכן לבחור מודול לפי סיומת
ולקרוא לאותם שמות בדיוק.

**ומה שהם כן עושים אחרת, כי זה נראה כמו סתירה למי שלא יודע:** ברירת
המחדל של ``max_sections``. ב-``rst_parser`` היא ``None`` וב-``md_parser``
היא התקרה, וההבדל מנומק בשני ה-docstrings.

**ייבוא קל בלבד** — ``re``, ``dataclasses``, ``difflib``, ``typing``. הכלל
מנומק ב-``mcp_server/__init__.py``: ``import database.schemas`` מריץ
``database/__init__.py``, ושורה 11 שם היא ``db = DatabaseManager()``,
כלומר חיבור למונגו בזמן טעינת מודול. הסורק ``mcp_server/outline_scanners/rst.py``
נמצא בשרשרת הייבוא של המודול הזה, ולכן הכלל חל גם עליו.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import get_close_matches
from typing import List, Optional, Tuple


@dataclass
class Section:
    """סקשן בודד בעץ הכותרות.

    **``title_line`` מול ``heading_line``, ולמה שניהם.** ``title_line`` היא
    השורה שבה יושב הטקסט של הכותרת; ``heading_line`` היא השורה שבה הסעיף
    **מתחיל**, ומשם נחתך התוכן. ב-RST השתיים נבדלות בדיוק במקרה אחד —
    כותרת עם קו-מעל (overline), שבה הסעיף מתחיל שורה אחת לפני הטקסט.
    בפארסר שאין לו צורה כזאת (Markdown) השתיים זהות תמיד.

    **זו אינה כפילות, וחשוב לא "לנקות" אותה**: ``_finalize`` ו-``section_bounds``
    נשענים דווקא על ``heading_line``, כי גבול הסעיף חייב לכלול את הקו-מעל.
    ``title_line`` משמש לזיהוי הסעיף (למשל ב-``neighbors``), ולכן איחוד
    השניים היה מקצר כל סעיף עם overline בשורה אחת — בשקט.

    ``adornment`` ו-``over`` הם תיאור הצורה שבה הכותרת נכתבה במקור: ב-RST
    תו ה-adornment והאם היה קו-מעל, וב-Markdown הסימון שהפארסר מדווח.
    """
    title: str
    level: int
    title_line: int          # 1-based — שורת הטקסט של הכותרת
    heading_line: int        # 1-based — השורה שבה הסעיף מתחיל (ראו docstring)
    end_line: int            # 1-based inclusive — סוף התוכן (מחושב ב-_finalize)
    adornment: str
    over: bool = False
    parent: Optional[int] = None
    children: List[int] = field(default_factory=list)
    breadcrumb: List[str] = field(default_factory=list)


@dataclass
class Document:
    """המסמך המפורסר: שורות המקור, עץ הסעיפים, והפניות חיצוניות.

    **``lines`` הן שורות המקור, ולא טקסט שעבר עיבוד לצורך הפרסור.**
    מכאן חותכים ``section_text`` ו-``build_toc``, ולכן פארסר שמעביר לעצמו
    טקסט מעובד (למשל כזה שמסמן front matter בשורות ריקות) חייב לבנות את
    השדה הזה מהמקור — אחרת הקורא יקבל שורות ריקות במקום התוכן, ו**אף מספר
    שורה לא ישתנה כדי להסגיר את זה**.

    **``includes`` הוא שדה של פארסר ולא של המודל.** היום רק ``rst_parser``
    ממלא אותו (יעדי ``.. include::``, בלי הרחבה); פארסר שאין לו מושג כזה
    משאיר אותו ריק, וזו ברירת המחדל.
    """

    lines: List[str]
    sections: List[Section]
    includes: List[str] = field(default_factory=list)


class TooManySections(Exception):
    """הקלט מייצר יותר סקשנים מהתקרה שהמתקשר העביר ב-``max_sections``.

    **חריגה, ולא ערך החזרה ולא ``Document`` חלקי עם דגל "נקטע".** המתקשר
    היחיד שמעביר תקרה הוא סורק האאוטליין, ושם הכלל כבר נקבע ומנומק
    ב-``mcp_server/outline_scanners/_ceiling.py``: מפה חלקית שמתחזה
    למלאה היא בדיוק הכשל שהתקרה קיימת כדי למנוע. דגל דורש בדיקה בכל אתר
    קריאה, ובדיקה אחת שנשכחת מחזירה תוכן עניינים שחסרות בו כותרות בלי
    שאיש יידע — ואילו חריגה נכשלת בקול.

    **ומוגדרת ב-``services`` ולא ב-``mcp_server``**, כי הכיוון חד-סטרי:
    הסורק מייבא מ-``services``, ו-``services`` אינו מייבא מ-``mcp_server``.

    **וכאן ולא ב-``rst_parser``**, כי היא חלק מהחוזה של המודל ולא של שפה
    אחת: פארסר שני שיחרוג מהתקרה חייב להרים את **אותה** חריגה, אחרת
    ה-``except`` בסורק היה צריך לתפוס שתיים — ומי שיוסיף את השלישית ישכח
    אותה שם. ``rst_parser`` מייצא אותה מחדש, ולכן
    ``rst_parser.TooManySections`` נשאר **אותו אובייקט מחלקה** בדיוק, וזה
    מה שמחזיק את ה-``except`` הקיים ואת הטסטים שתופסים אותה דרך השם ההוא.

    ההורשה היא מ-``Exception`` ישירות ולא מחריגת ספריית תקן, כדי שתפיסה
    צרה של החריגה הזאת לא תוכל להתנגש בשגיאה אמיתית.
    """


class InconsistentLineEndings(Exception):
    """הקלט מערבב סיומות שורה, ולכן ספירת השורות שלו אינה חד-משמעית.

    הצורה היחידה שמפילה את ההבחנה היא ``\\r`` שאינו חלק מ-``\\r\\n`` — הפורמט
    של Mac שלפני 2001. **CRLF אינו מושפע ועובד במלואו**, כי שם שתי
    הספירות מסכימות, והוא המקרה הנפוץ.

    **למה זה חשוב דווקא כאן:** כל שדות ה-``lines`` בתשובות ה-MCP נספרים
    ב-``split("\\n")``, ואילו ``markdown-it-py`` מנרמל לפי
    ``rules_core/normalize.py`` עם ``\\r\\n?|\\n`` — כלומר ``\\r`` בודד הוא אצלו
    שורה חדשה. בקובץ כזה המפה מצביעה לשורה ש-``lines=[start, end]`` לא
    מגיעה אליה, ו**מפה שמצביעה לשומקום גרועה ממפה שאין**.

    **חריגה ולא ערך החזרה**, מאותו נימוק שכתוב ב-:class:`TooManySections`
    ממש למעלה: ערך "עצור" דורש בדיקה בכל אתר קריאה, ובדיקה אחת שנשכחת
    מחזירה מפה שגויה בשקט.

    **וכאן ולא בפארסר**, כדי שהמטפל שימיר אותה לתשובת MCP ייבא את שתי
    חריגות הסירוב מאותו מודול, ושפארסר שלישי ירים את **אותה** מחלקה.
    השם שהתשובה תישא בחוץ, ``inconsistent_line_endings``, כבר קיים
    באוצר המילים — ``mcp_server/outline.py`` מחזיר אותו כ-``reason``
    על בדיוק אותה מחלקת קלט.

    **מה שהיא אינה:** היא אינה מתארת קובץ ב-CRLF, ואינה מתארת קידוד
    שבור. רק ``\\r`` בודד.
    """


def _finalize(sections: List[Section], total_lines: int) -> None:
    """מחשב end_line, parent/children, ו-breadcrumb לכל סקשן."""
    for idx, sec in enumerate(sections):
        end = total_lines
        for j in range(idx + 1, len(sections)):
            if sections[j].level <= sec.level:
                end = sections[j].heading_line - 1
                break
        sec.end_line = end

    stack: List[int] = []  # אינדקסים של אבות פתוחים
    for idx, sec in enumerate(sections):
        while stack and sections[stack[-1]].level >= sec.level:
            stack.pop()
        if stack:
            parent = stack[-1]
            sec.parent = parent
            sections[parent].children.append(idx)
            sec.breadcrumb = sections[parent].breadcrumb + [sec.title]
        else:
            sec.parent = None
            sec.breadcrumb = [sec.title]
        stack.append(idx)


def normalize_title(s: str) -> str:
    """נרמול סלחני להשוואת כותרות: רווחים, מקפים, ו-case לחלק האנגלי."""
    s = (s or "").strip()
    s = re.sub(r"[‐-―\-]", "-", s)  # מקף/מקף ארוך → מקף אחיד
    s = re.sub(r"\s+", " ", s)                # רווחים כפולים → יחיד
    return s.casefold()                       # case-insensitive (עברית לא מושפעת)


def find_sections(doc: Document, title: str) -> List[Section]:
    """כל הסקשנים שכותרתם תואמת (סלחני). ריק/יחיד/מרובה — המתקשר מחליט."""
    target = normalize_title(title)
    return [s for s in doc.sections if normalize_title(s.title) == target]


def section_bounds(doc: Document, sec: Section, include_subsections: bool) -> Tuple[int, int]:
    """טווח שורות (1-based inclusive) של תוכן הסקשן — עם או בלי תת-סקשנים."""
    start = sec.heading_line
    if include_subsections or not sec.children:
        return start, sec.end_line
    first_child = doc.sections[sec.children[0]]
    return start, first_child.heading_line - 1


def section_text(doc: Document, sec: Section, include_subsections: bool) -> str:
    start, end = section_bounds(doc, sec, include_subsections)
    return "\n".join(doc.lines[start - 1:end])


def direct_subsections(doc: Document, sec: Section) -> List[Section]:
    return [doc.sections[c] for c in sec.children]


def neighbors(doc: Document, sec: Section) -> Tuple[Optional[Section], Optional[Section]]:
    """הסקשן הקודם והבא באותה רמה תחת אותו אב (לניווט בלי TOC)."""
    siblings = ([doc.sections[c] for c in doc.sections[sec.parent].children]
                if sec.parent is not None
                else [s for s in doc.sections if s.parent is None])
    ids = [s.title_line for s in siblings]
    try:
        pos = ids.index(sec.title_line)
    except ValueError:
        return None, None
    prev = siblings[pos - 1] if pos > 0 else None
    nxt = siblings[pos + 1] if pos + 1 < len(siblings) else None
    return prev, nxt


def build_toc(doc: Document) -> List[dict]:
    """עץ כותרות: כותרת, רמה, טווח שורות, גודל משוער (bytes) — בלי תוכן."""
    toc = []
    for sec in doc.sections:
        approx = len("\n".join(doc.lines[sec.heading_line - 1:sec.end_line]).encode("utf-8"))
        toc.append({
            "title": sec.title,
            "level": sec.level,
            "breadcrumb": list(sec.breadcrumb),
            "line_range": [sec.heading_line, sec.end_line],
            "approx_bytes": approx,
        })
    return toc


def suggest(doc: Document, query: str, n: int = 5) -> List[str]:
    """כותרות קרובות לשאילתה שלא נמצאה (difflib), לשילוב ב-not-found."""
    titles = [s.title for s in doc.sections]
    norm_map = {normalize_title(t): t for t in titles}
    close = get_close_matches(normalize_title(query), list(norm_map.keys()), n=n, cutoff=0.5)
    # שמור על סדר ייחודי
    out, seen = [], set()
    for c in close:
        t = norm_map[c]
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out
