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
ולקרוא לאותם שמות. **בדיוק אותם שמות — למעט שניים:** ``md_parser``
מייצא גם ``MAX_SECTIONS`` ו-``InconsistentLineEndings``, ש-``rst_parser``
אינו מרים ואינו מגדיר. חריגות הסירוב נתפסות לכן דרך המודול הזה, לא דרך
הפארסר — ראו את ה-docstring של :class:`InconsistentLineEndings`.

**ומה שהם כן עושים אחרת, כי זה נראה כמו סתירה למי שלא יודע:** ברירת
המחדל של ``max_sections``. ב-``rst_parser`` היא ``None`` וב-``md_parser``
היא התקרה, וההבדל מנומק בשני ה-docstrings.

**ומי הבעלים של שני ערוצי הסירוב: המתקשר, והיום אין מתקשר שתופס אותם.**
``TooManySections`` ו-``InconsistentLineEndings`` אינן נתפסות בשום מקום
במסלול הזה — ``mcp_server/docs_handlers.py`` אינו מכיל ``except`` בכלל,
והקריאה היחידה שלו היא ``rst_parser.parse_document(content)``. מי שיחליף
שם פארסר מכניס שני מסלולי חריגה לאתר קריאה לא-מוגן, והמרתם לתשובת
``error`` של MCP היא עבודה של אותו שינוי — לא של המודול הזה, שאינו יודע
דבר על MCP.

**ובדיקת הכניסה עצמה עדיין אינה זהה בין השניים.** נמדד:
``rst_parser.parse_document(None)`` מחזיר ``Document`` ריק **בשקט**,
ו-``rst_parser.parse_document(17)`` זורק ``AttributeError`` גולמי; שניהם
ב-``md_parser`` הם ``TypeError`` שאומר מה התקבל. הפארסר החדש הוא זה
שמתנהג נכון, ולכן אין כאן מה להחליש — אבל יישור של הוותיק הוא שינוי
התנהגות על מסלול חי, ולכן הוא **מתועד באישו #3421** ואינו נעשה כאן.

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
from typing import List, NamedTuple, Optional, Tuple


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
    """הקלט חוצה את התקרה שהמתקשר העביר ב-``max_sections``.

    **ומה בדיוק נספר תלוי בפארסר, וזה מכוון.** ב-``rst_parser`` נספרים
    סקשנים, וב-``md_parser`` נספרות **כותרות** — כולל כותרת בתוך ציטוט
    או פריט רשימה, שאינה נכנסת למפה בכלל. בשני המקרים התקרה מגבילה את
    העבודה שהפרסור עושה, ובמסלול ה-Markdown כותרת בתוך מכל עולה בדיוק
    כמו כל אחרת — ההנמקה המלאה ב-``services/md_parser.py::MAX_SECTIONS``.
    המחלקה אחת כי מה שהקורא צריך לדעת זהה: הקלט גדול מדי, ואין מפה.

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


#: הצורה של **מזהה סעיף**: עד שלוש אותיות ואחריהן עד שלוש ספרות — ``K11``,
#: ``U3``, ``H2``, ``P3``. **הגדרה אחת ושני שימושים**, כי שני רגקסים שמתארים
#: את אותה צורה הם בדיוק ``duplicate-rule-second-copy``: מי שירחיב את הצורה
#: (ארבע ספרות, סיפא באות) יתקן אחד מהם וישכח את השני, ושניהם נכונים עד אז.
_IDENTIFIER = r"[A-Za-z]{1,3}\d{1,3}"

#: השאילתה **עצמה** היא מזהה, עם נקודה אופציונלית בסוף. ``fullmatch`` ולא
#: ``$``, כי ``$`` מתיר שורה חדשה אחת בסוף — ושאילתה מגיעה מחוץ לתהליך.
_IDENTIFIER_QUERY_RE = re.compile(rf"{_IDENTIFIER}\.?")

#: הכותרת **נפתחת** במזהה, ואחריו נקודה, רווח, או סוף הכותרת. הגבול מפורש
#: ולא משתמע: ``K11abc`` אינו המזהה ``K11``.
#:
#: **ו-``(?!\d)`` אחרי הנקודה הוא מה שמפריד בין שתי משמעויות שלה.**
#: ב-``K11. טקסט`` הנקודה **מסיימת** את המזהה; ב-``K11.1 טקסט`` היא
#: **מפרידה** בתוך מזהה ארוך יותר, ו-``K11.1`` אינו ``K11``. בלי השלילה
#: הזאת ``section="K11"`` היה מחזיר ``ambiguous_section`` עם ``K11.`` ועם
#: כל תת-הסעיפים שלו — כלומר בדיוק הזרימה שהענף הזה נבנה לתקן, ומאותה
#: מחלקה בדיוק כמו ``K1`` שתופס את ``K10``: גבול שנבדק כתו בודד, בלי
#: לשאול מה בא אחריו. **ומכאן שכותרת בתת-מספור אינה נגישה דרך הענף
#: כלל** — ``K11.1`` אינו בצורת המזהה שהחוזה מגדיר, ולכן היא נמצאת
#: בשמה המלא בלבד, כמו כל כותרת אחרת.
_IDENTIFIER_TITLE_RE = re.compile(rf"^({_IDENTIFIER})(?:\.(?!\d)|\s|\Z)")

#: תקרת המזהים שמוחזרים כהצעה. רשימת הצעות היא **רמז**, ורמז בן עשרות אלפי
#: פריטים אינו רמז — וגם לא נכנס בתשובה, שנושאת ממילא את ה-TOC כולו (חסום
#: ב-400 פריטים ב-``mcp_server/docs_handlers.py``). נמדד ב-20.09.2026 על
#: הקורפוס שהסוכנים קוראים (``amir-bug-patterns``, ‏``889c234``): הקובץ
#: העשיר ביותר נושא 16 מזהים, כלומר לתקרה הזאת יש בערך פי שלושה מרווח.
#: **והחיתוך אינו שקט** — ``Suggestions.truncated`` אומר שהוא קרה.
MAX_IDENTIFIER_SUGGESTIONS = 50


class Suggestions(NamedTuple):
    """מה ש-:func:`suggest` מחזיר: הכותרות, והאם הרשימה נחתכה.

    **זה ``NamedTuple`` ולא רשימה, וזה שינוי חוזה שכדאי לשים לב אליו.**
    קורא ישן שכתב ``for t in suggest(...)`` יקבל **טאפל של שני איברים** —
    רשימת המחרוזות, ואחריה ``True``/``False`` — ולא את הכותרות אחת-אחת.
    שום דבר לא ייזרק; הלולאה פשוט תרוץ על משהו אחר. הצורה הנכונה היא
    ``suggest(...).titles``.

    **ולמה בכלל דגל ולא רשימה חתוכה בשקט.** ``truncated`` הוא האמירה
    שהתקרה נגעה. בלעדיו זה בדיוק ``silent-truncation-at-sink``: הקורא
    מקבל תשובה שנראית שלמה, ואין בה שום הפרש שאפשר לראות.
    """

    titles: List[str]
    truncated: bool = False


def _identifier_query(query: str) -> Optional[str]:
    """המזהה שהשאילתה **עצמה** בנויה ממנו, מנורמל ובלי הנקודה — או ``None``.

    **זה השומר שמכבה את הענף.** בלי הדרישה הזאת, הכלל "הכותרת נפתחת במה
    שביקשת ואחריו גבול" חל על **כל** מחרוזת, ואז ``section="איך"`` תופס
    את כל הכותרות ``איך זה נראה`` שבקורפוס — נמדד ש-``איך``, ``כלל``
    ו-``ראה`` היו מחזירים 15 התאמות כל אחד.

    .. warning::

       **ובכל זאת, הוא נושא משקל שונה בשני הקוראים שלו, וכדאי לדעת מה
       בדיוק שובר מה.** ב-:func:`suggest` הוא **הכרחי**: שם אין כותרת
       שהותאמה, ולכן שום דבר אחר לא מונע משאילתה עברית לקבל את רשימת
       המזהים במקום ``difflib``. ב-:func:`find_sections` הוא **מסנן
       מוקדם בלבד**: הצד השני של ההשוואה הוא מזהה שפורק מכותרת, ולכן
       שאילתה שאינה מזהה לא יכולה להשתוות לו ממילא. כלומר הסרתו משם
       אינה משנה התנהגות, ואין טסט שייפול עליה — מה שכן נופל הוא השילוב
       ההיסטורי של הסרת השומר **יחד** עם חזרה ל-``startswith``.

       זה כתוב כאן כדי שאיש לא "ינקה" את :func:`_leading_identifier`
       בהנחה שהשומר הזה מגן עליו. הוא לא מגן — הוא מקצר.

    הנרמול הוא ``normalize_title`` ולא ``strip`` מקומי, כדי שהמזהה שיוחזר
    יושווה באותם כללים בדיוק שבהם מושווה השוויון המלא.
    """
    match = _IDENTIFIER_QUERY_RE.fullmatch(normalize_title(query))
    return match.group(0).rstrip(".") if match else None


def _leading_identifier(title: str) -> Optional[str]:
    """המזהה שהכותרת **נפתחת** בו, כפי שנכתב במקור — או ``None``.

    **הפירוק הוא מה שסוגר את מבחן הגבול, ולא תנאי נוסף שאפשר להסיר.**
    ``K1`` הוא תחילית של ``K10`` עד ``K15``, וכלל שנכתב כ"הכותרת מתחילה
    במחרוזת שביקשת" היה מחזיר לו **שבע** התאמות במקום אחת. זה ``K16``
    ב-amir-bug-patterns — אותה משפחה בדיוק כמו נתיב שנבדק כרצף תווים —
    והתשובה שם היא להשוות את היחידה שפורקה ולא את הרצף. כאן הכותרת
    ``K10. טקסט`` מפורקת למזהה ``K10``, והוא פשוט **אינו שווה** ל-``K1``:
    אין קידומת, ואין גבול שצריך לזכור לבדוק.

    **והמזהה מוחזר כפי שנכתב ולא מנורמל**, כי :func:`suggest` מגיש אותו
    לסוכן כמחרוזת שהוא יקליד בשאילתה הבאה.
    """
    match = _IDENTIFIER_TITLE_RE.match((title or "").strip())
    return match.group(1) if match else None


def _document_identifiers(doc: Document) -> List[str]:
    """המזהים שבמסמך, בסדר הופעתם ובלי כפילויות (השוואה ב-``casefold``)."""
    found: List[str] = []
    seen = set()
    for sec in doc.sections:
        identifier = _leading_identifier(sec.title)
        if identifier is None:
            continue
        key = identifier.casefold()
        if key not in seen:
            seen.add(key)
            found.append(identifier)
    return found


def find_sections(doc: Document, title: str) -> List[Section]:
    """כל הסקשנים שכותרתם תואמת (סלחני). ריק/יחיד/מרובה — המתקשר מחליט.

    **שני ענפים, ובסדר הזה בדיוק.** קודם שוויון מלא אחרי ``normalize_title``
    — ההתנהגות ההיסטורית, בלי שינוי. ורק אם הוא לא מצא **כלום**, ורק אם
    השאילתה עצמה בנויה כמזהה, נבדקת התאמת-מזהה: הכותרת נפתחת באותו מזהה.

    **למה דווקא בסדר הזה:** הענף אינו יכול לגבור על התאמה מדויקת קיימת.
    מסמך שיש בו כותרת ששמה בדיוק ``K11`` וגם כותרת ``K11. טקסט`` מחזיר את
    הראשונה בלבד — מה שהמשתמש הקליד הוא מה שהוא ביקש.

    **והצורך עצמו נמדד, לא שוער:** הסוכנים מפנים לפי מזהה ("קרא K11",
    "ראו U3"), וללא הענף ``section="K11"`` מחזיר ``section_not_found``
    שההצעות שלו **ריקות** — ``difflib`` עם ``cutoff=0.5`` אינו מוצא קרבה
    בין שלושה תווים לכותרת עברית ארוכה.

    **ולמה זה אינו משנה את מסלול ה-RST:** אף כותרת בעמודי התיעוד שבריפו
    הזה אינה נפתחת במזהה, ולכן הענף שם אינו נדלק ושאילתה בצורת מזהה מחזירה
    בדיוק מה שהחזירה קודם. **זה נמדד ולא הונח**, והמדידה ניתנת להרצה חוזרת:
    ``scripts/docs_section_zero_diff.py`` שואל כל כותרת בשמה המלא **וגם**
    שאילתות בצורת מזהה על כל קובץ, ומדווח כמה פעמים הענף נדלק.
    """
    target = normalize_title(title)
    exact = [s for s in doc.sections if normalize_title(s.title) == target]
    if exact:
        return exact

    identifier = _identifier_query(title)
    if identifier is None:
        return []
    return [
        s for s in doc.sections
        if (leading := _leading_identifier(s.title)) is not None
        and leading.casefold() == identifier
    ]


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


def suggest(doc: Document, query: str, n: int = 5) -> Suggestions:
    """כותרות קרובות לשאילתה שלא נמצאה, לשילוב ב-not-found.

    **ההחזרה היא :class:`Suggestions` — ``NamedTuple`` בן שני שדות**,
    ``titles`` ו-``truncated`` — ולא רשימה. קורא ישן שעשה
    ``for t in suggest(...)`` יקבל טאפל של שני איברים ולא את הכותרות;
    ראו את ה-docstring של המחלקה.

    **``difflib`` קודם, ורשימת המזהים היא מוצא אחרון.** הסדר הזה חשוב:
    הרשימה קיימת **בדיוק בגלל** ש-``difflib`` מחזיר ריק לשאילתת מזהה —
    נמדד ש-``suggest("K11")`` ו-``suggest("U3")`` מחזירים רשימה **ריקה**,
    כי ``cutoff=0.5`` אינו מוצא קרבה בין שלושה תווים לכותרת עברית ארוכה,
    וכך ההבטחה "לעולם לא רק לא-נמצא" מתנוונת ל-TOC. אבל כש-``difflib``
    **כן** מצא משהו, הוא מצא כותרת אמיתית שהקורא יכול להעתיק — וזו תשובה
    טובה יותר מרשימת מזהים.

    .. warning::

       **הסדר ההפוך נראה סביר והוא שגוי, ולכן כתוב כאן למה.** מחרוזת
       יכולה להיות בצורת מזהה בלי להיות מזהה במסמך הזה: ``IPv6`` הוא
       שלוש אותיות וספרה, כלומר הוא עובר את :func:`_identifier_query`.
       בקובץ שיש בו ולו מזהה אחד, מסלול-מזהה-קודם היה מחזיר לשאילתה
       ``IPv6`` את רשימת המזהים — למשל ``["K11"]`` — במקום את הכותרת
       ``IPv6/IPv4 dual stack`` שיושבת באותו קובץ. תשובה שאינה קשורה
       לשאלה גרועה מתשובה ריקה.

    **ותנאי אחד לרשימה עצמה: השאילתה בצורת מזהה.** הוא היחיד שנושא
    משקל — בלעדיו שאילתה עברית שאין לה כותרת קרובה הייתה מקבלת את רשימת
    המזהים במקום רשימה ריקה.

    **ומה ששומר על מסלול ה-RST הוא מבנה, לא שומר.** גרסה קודמת של
    הפונקציה בדקה כאן גם "ויש בקובץ מזהים", והתנאי הזה הפך לחסר-השפעה
    ברגע ש-``difflib`` עבר לראש: כשאין בקובץ מזהים, ``_document_identifiers``
    מחזיר רשימה ריקה, ו-``Suggestions([], False)`` הוא בדיוק מה שהיה חוזר
    ממילא. תנאי שאינו יכול לשנות תוצאה ומוצג כהגנה הוא הבטחה שהקוד אינו
    מקיים, ולכן הוא הוסר ולא הושאר "ליתר ביטחון".

    **והמזהה שנשאל אינו יכול להופיע ברשימה שחוזרת**, כי אילו היה בקובץ
    :func:`find_sections` היה מוצא אותו, והמתקשר לא היה מגיע לכאן בכלל.
    """
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
    if out:
        return Suggestions(out)

    identifier = _identifier_query(query)
    if identifier is None:
        return Suggestions(out)

    identifiers = _document_identifiers(doc)
    return Suggestions(identifiers[:MAX_IDENTIFIER_SUGGESTIONS],
                       len(identifiers) > MAX_IDENTIFIER_SUGGESTIONS)
