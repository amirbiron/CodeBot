"""פארסר Markdown שבונה את מודל הסעיפים המשותף שב-``doc_sections``.

מודול תאום ל-``services/rst_parser.py``: אותו ``Document``, אותם
``Section``, ואותן פונקציות עץ — ולכן ``mcp_server/docs_handlers.py``
יוכל לבחור פארסר לפי סיומת ולהמשיך זהה בית-בית. כל מה שאינו תלוי-שפה
נקרא מ-``doc_sections`` ואינו נכתב כאן מחדש, ובכלל זה חישוב ה-``end_line``
וההיררכיה.

**למה ``markdown-it-py`` ולא פארסר משלנו.** נמדד מול cmark-gfm — הפארסר
ש-GitHub מריץ בפועל — על 11,400 צורות מחוללות ועל כל 1,001 הכותרות
בקורפוס של ``amir-bug-patterns``: **אפס אי-הסכמות**. פארסר שנכתב ביד היה
צריך להוכיח את השקילות הזאת מחדש בכל שינוי, והסורק ל-RST שכן נכתב ביד
עבר ארבעה סבבי סקירה שכל אחד מהם מצא מה שקודמו פספס. המחיר מוצהר: הוא
איטי פי 10–25 מ-cmark-gfm, וזה נסבל בשכבה שחלה כאן.

**מה שהמודול הזה לא עושה, כדי שהקורא לא ישלים מהדמיון:**

* **אין חסם על מספר שורות.** התקרה שכאן סופרת **סעיפים**, והזיכרון של
  ``markdown-it-py`` נגזר ממספר ה**שורות** — נמדד כ-107 בתים לשורה,
  כלומר 10MB של שורות ריקות הם כג'יגה-בייט, והתקרה הזאת אינה נוגעת בהם.
  מה שחוסם אותם היום הוא תקרת ה-500KB של שירות המראה, שחלה על הקורא
  היחיד המתוכנן (``docs_get_section`` קורא בלי ``lines`` ובלי
  ``outline``). חסם שורות יידרש כשהמודול הזה ישרת גם את האאוטליין, ששם
  התקרה היא 10MB.
* **אין דה-דופליקציה של כותרות ואין נרמול של טקסט הכותרת.** השם מוחזר
  כפי שהוא במקור, עם בקטיקים, הדגשות וקישורים.
* **אין ``includes``** — לצורה הזאת אין מקבילה ב-Markdown, והשדה נשאר ריק.

**ערוץ הכשל הוא חריגה בלבד.** ``parse_document`` אף פעם אינו מחזיר
``None``, ``Document`` חלקי, או מפה ריקה כדי לסמן כשל: קובץ בלי כותרות
מחזיר מפה ריקה **תקינה**, וכל סירוב הוא חריגה — ``TypeError``,
``InconsistentLineEndings`` או ``TooManySections``. זה נכתב במפורש כי
פונקציה עם שני ערוצי כשל היא בדיוק מה שמלכד את הקורא הבא.
"""

from __future__ import annotations

import re
from typing import List, Optional

from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.front_matter import front_matter_plugin

from .doc_sections import (
    Document,
    InconsistentLineEndings,
    Section,
    TooManySections,
    _finalize,
    build_toc,
    direct_subsections,
    find_sections,
    neighbors,
    normalize_title,
    section_bounds,
    section_text,
    suggest,
)

# ``__all__`` מוצהר מאותו נימוק שכתוב ב-``rst_parser``: בלי ההצהרה, כל
# שם שמיובא כאן רק כדי להיות מיוצא מחדש מקבל ``F401`` מ-pyflakes, ו-``#
# noqa`` על כל אחד מהם היה מסתיר את האזהרה במקום להצהיר על הכוונה.
#
# והייצוא־מחדש עצמו אינו נוחות: הוא מה שהופך את שני הפארסרים ל**בני
# החלפה**. ``docs_handlers`` יוכל לבחור מודול לפי סיומת ולקרוא לאותם
# שמות בדיוק, בלי אף ``if`` נוסף במסלול.
__all__ = [
    "MAX_SECTIONS",
    "Document",
    "InconsistentLineEndings",
    "Section",
    "TooManySections",
    "build_toc",
    "direct_subsections",
    "find_sections",
    "neighbors",
    "normalize_title",
    "parse_document",
    "section_bounds",
    "section_text",
    "suggest",
]

#: מקסימום סעיפים לקובץ, ומעליו הפרסור נעצר. **אותו ערך בדיוק כמו
#: ``MAX_SYMBOLS`` ב-``mcp_server/outline_scanners/_ceiling.py``**, ושם
#: כתובות שתי המדידות שקבעו אותו — השיא שהתקרה מרשה, והיחס לקובץ אמיתי.
#: מי שמשנה את אחד מהשניים צריך לפתוח את השני: הם מתארים את אותו גבול
#: על אותה מפה, והסורק שיגיע לכאן בשלב 2 יעביר את זה במקום את זה.
#:
#: ``_ceiling.MAX_SYMBOLS`` אינו מיובא לכאן, כי ``services`` אינו מייבא
#: מ-``mcp_server`` — הכיוון חד-סטרי ומנומק ב-``TooManySections``.
MAX_SECTIONS = 50_000

#: ``\r`` שאינו חלק מ-``\r\n``. ההגדרה חוזרת כאן ואינה מיובאת מ-
#: ``mcp_server/outline.py::_CR_WITHOUT_LF``, מאותה סיבה: הכיוון חד-סטרי.
#: השקילות בין השניים אינה תקווה — ``tests/test_md_parser.py`` משווה את
#: שניהם מול ההתנהגות של ``markdown-it-py`` עצמו על טבלת קלטים אחת.
#:
#: ``search`` ולא ``replace``: הוא עוצר על ההתאמה הראשונה ואינו מקצה
#: עותק של הטקסט.
_CR_WITHOUT_LF = re.compile(r"\r(?!\n)")

#: המפתח שתחתיו יושב מונה הסעיפים ב-``env`` של פרסור בודד.
_ENV_COUNTER = "ck_md_section_counter"


class _SectionCounter:
    """סופר סעיפים ברמת המסמך תוך כדי הפרסור, בלי לסרוק טוקן פעמיים.

    **המצב יושב כאן ולא על המופע המשותף של ``MarkdownIt``.** המופע נבנה
    פעם אחת ברמת המודול ונקרא ממספר חוטים — גופי הכלים רצים ב-
    ``asyncio.to_thread`` — ולכן מונה שהיה יושב עליו היה מרוץ. ``env``
    הוא פר-פרסור ומועבר לתוך ``md.parse``, ואומת שהוא אותו אובייקט
    שיוצא בסוף.

    **ו-``scanned`` הוא כל העניין.** כלל שסורק את ``state.tokens`` כולו
    בכל קריאה הוא O(n²), וזה בדיוק מה שהופך תקרה שנועדה לחסוך עבודה
    למקור העבודה. ``examined`` נספר כדי שאפשר יהיה לטעון על זה בטסט
    במקום למדוד זמן שמתנדנד ב-CI.
    """

    __slots__ = ("max_sections", "seen", "scanned", "examined")

    def __init__(self, max_sections: int) -> None:
        self.max_sections = max_sections
        self.seen = 0
        self.scanned = 0
        self.examined = 0

    def scan(self, tokens: List[Token]) -> bool:
        """סורק את הטוקנים החדשים בלבד. ``True`` = התקרה נחצתה.

        הגבול זהה ל-``Capped.append`` וְל-``add_section`` ב-``rst_parser``:
        קובץ עם בדיוק ``max_sections`` סעיפים עובר במלואו, והסעיף שמעליו
        עוצר.
        """
        for token in tokens[self.scanned:]:
            self.examined += 1
            if token.type == "heading_open" and token.level == 0:
                self.seen += 1
        self.scanned = len(tokens)
        return self.seen > self.max_sections


def _ceiling_rule(state, startLine: int, endLine: int, silent: bool) -> bool:
    """כלל בלוק שאינו מייצר טוקנים — הוא רק סופר, ועוצר בתקרה.

    החתימה היא ``RuleFuncBlockType`` של ``markdown_it/parser_block.py``,
    ו-``False`` פירושו "לא אני" — כלומר שרשרת הכללים ממשיכה כרגיל
    והפלט זהה בדיוק לפלט בלי הכלל הזה.

    **למה בתוך הפרסור ולא אחריו:** ``ParserBlock.tokenize`` קורא לכל
    כלל בתחילת כל בלוק, כולל בתוך ציטוטים ורשימות (הוא משתמש ב-
    ``getRules("")``, שהיא **כל** הכללים). לכן חריגה כאן עוצרת את העבודה
    באמצע. נמדד על 50 כותרות עם תקרה של 5: העצירה בשורה 23 מתוך 201.
    בדיקה אחרי ``md.parse`` הייתה מסננת פלט אחרי שכל העבודה כבר נעשתה —
    וזה בדיוק ההבדל שנמדד ב-``_ceiling.py``.
    """
    counter: Optional[_SectionCounter] = state.env.get(_ENV_COUNTER)
    if counter is not None and counter.scan(state.tokens):
        raise TooManySections(startLine + 1)
    return False


def _build_parser() -> MarkdownIt:
    """המופע היחיד. **הגדרה, לא עבודה** — אין כאן רשת, דיסק או תהליכון.

    שלוש החלטות, וכל אחת נמדדה:

    1. **``commonmark``** ולא ``gfm-like``. נמדד שהרחבות ה-GFM אינן
       נוגעות בזיהוי כותרות — שורת ``|---|`` אינה קו setext בשתי הגישות,
       כי היא מכילה ``|`` — ושהפלט זהה ל-cmark-gfm על כל הקורפוס.
    2. **``front_matter_plugin``** במקום סימון ידני של הבלוק. זו
       ההגדרה ש-MyST משתמש בה, ולכן היא הכלל שקובע מהו front matter גם
       בקובצי ה-``.md`` שתחת ``docs/`` בריפו הזה. נמדד שהיא **אינה מזיזה
       אף מספר שורה** באף אחת מעשר הצורות שנבדקו — כולל בלוק שאינו נסגר,
       ``---`` מוזח, ו-``---`` עם רווח בסוף — כי הטקסט עצמו אינו משתנה
       כלל. וכלל שהיינו כותבים בעצמנו כן היה סוטה ממנה: נמדד שפרוטוטיפ
       שמשווה ``---`` מדויק חולק עליה בחמש מתוך שלוש-עשרה צורות.
    3. **``disable("inline")``** — הכלל ה**ליבתי** בשם הזה, שהוא זה
       שמפרק את תוכן הכותרת לטוקנים פנימיים. נמדד: עד 40% חיסכון בזמן
       ו-37% בזיכרון, **ואפס שינוי בזיהוי הכותרות ובטווחים** — כי השם
       נלקח מ-``token.content``, שהוא הטקסט הגולמי מהמקור בשני המצבים.

    ``before("front_matter", ...)`` ולא ``before("table", ...)``: הוא
    מציב את התקרה ראשונה בשרשרת, **ונכשל ב-``KeyError`` אם התוסף לא
    נרשם** — כלומר תלות חסרה נופלת כאן ולא בשקט בזמן פרסור.
    """
    md = MarkdownIt("commonmark").use(front_matter_plugin).disable("inline")
    md.block.ruler.before("front_matter", "ck_max_sections", _ceiling_rule)
    return md


#: המופע נבנה **בשלמותו לפני שהוא מתפרסם**, בהצבה אחת, ואין כאן שומר
#: שנבדק בנפרד מהערך — כלומר זה אינו ``lazy-init-guard-publish-order``
#: אלא ה-False positive המוצהר שלו. אין אתחול עצל ואין חלון.
_MD = _build_parser()


def parse_document(text: str, *, max_sections: Optional[int] = MAX_SECTIONS) -> Document:
    """בונה ``Document`` מטקסט Markdown.

    **סדר הבדיקות בכניסה, והוא אינו שרירותי:**

    1. ``isinstance(text, str)`` — הטקסט מגיע מחוץ לתהליך (קובץ מהמראה,
       גוף בקשה), ו-``.replace`` על ערך שאינו מחרוזת היה מפיל
       ``AttributeError`` ממקום שלא מסביר כלום.
    2. ``\\r`` בודד → :class:`~services.doc_sections.InconsistentLineEndings`.
    3. נרמול ``\\r\\n`` ← ``\\n``, והוא **הנרמול היחיד שמותר**, כי הוא
       היחיד שאינו משנה כמה שורות יש. ``splitlines()`` נשקל ונדחה באותו
       נימוק שכתוב ב-``rst_parser``: הוא מפצל על עשרה תווים במקום אחד.
    4. פרסור.

    **ה-front matter מטופל בתוך הפרסור ולא לפניו**, ולכן הוא אינו שלב
    ברשימה הזאת. אילו הוא היה שלב — כלומר אילו היינו מחליפים את שורות
    הבלוק לפני הבדיקות — הוא היה יכול לבלוע ``\\r`` בודד שיושב בתוכו,
    ולהסתיר בדיוק את הקלט שבדיקה 2 קיימת בשבילו.

    :param max_sections: התקרה. ברירת המחדל היא :data:`MAX_SECTIONS`,
        ו-``None`` מכבה אותה במפורש.

        .. important::

           **ברירת המחדל כאן הפוכה מזו של**
           ``services.rst_parser.parse_document``\\ **, שם היא ``None``.**
           שם הפרמטר נוסף לפארסר שכבר היה בייצור, וברירת מחדל שאינה
           ``None`` הייתה משנה את התנהגות ``docs_get_section`` באותו
           קומיט; כאן אין התנהגות קודמת לשמר, ולכן נבחרה ההנחה היקרה —
           קורא ששכח להעביר תקרה מקבל הגנה ולא את היעדרה. ההבדל מוצהר
           בשני המקומות בכוונה, ויישור של ``rst_parser`` נשקל בנפרד כי
           הוא שינוי התנהגות על מסלול חי.

    :raises TypeError: ``text`` אינו מחרוזת.
    :raises ~services.doc_sections.InconsistentLineEndings: יש ``\\r``
        שאינו חלק מ-``\\r\\n``.
    :raises ~services.doc_sections.TooManySections: הקלט מייצר יותר
        סעיפים מהתקרה. הארגומנט הוא מספר השורה שבה נעצרנו — מה שמבדיל
        עצירה בתוך הפרסור מסינון של פלט אחריו.
    """
    if not isinstance(text, str):
        raise TypeError(f"parse_document expects str, got {type(text).__name__}")
    if _CR_WITHOUT_LF.search(text):
        raise InconsistentLineEndings

    normalized = text.replace("\r\n", "\n")
    lines = normalized.split("\n")

    env: dict = {}
    if max_sections is not None:
        env[_ENV_COUNTER] = _SectionCounter(max_sections)

    tokens = _MD.parse(normalized, env)
    sections = _sections_from_tokens(tokens, total_lines=len(lines))

    # **שער שני לאותה תקרה, ולא כפילות.** הכלל שבתוך הפרסור נקרא
    # ב**תחילת** כל בלוק, ולכן הטוקנים שנדחפו אחרי הקריאה האחרונה שלו
    # אינם נסרקים — כלומר קלט שחוצה את התקרה בסעיף האחרון ממש היה חומק.
    # זה בדיוק התקדים שכבר קיים במסלול ה-RST, שם ``add_section`` ו-
    # ``Capped.append`` שומרים על אותו מספר משני צדדים.
    if max_sections is not None and len(sections) > max_sections:
        raise TooManySections(sections[max_sections].heading_line)

    _finalize(sections, len(lines))
    return Document(lines=lines, sections=sections)


def _sections_from_tokens(tokens: List[Token], *, total_lines: int) -> List[Section]:
    """הסעיפים שבמפה, לפי הכללים שהוכרעו במדידה.

    **רק ``token.level == 0``.** כותרת בתוך ציטוט או בתוך פריט רשימה
    **מזוהה** ככותרת — הפארסר אינו מתווכח עם GitHub — אבל אינה סעיף
    במסמך: היא חלק מהמכל שלה. ו**הטווח שלה שבור מעצם ההגדרה**, כי
    ``end_line`` נמתח עד הכותרת הבאה באותה רמה או גבוהה ממנה, כלומר
    הרבה מעבר לסוף הציטוט. נמדד: ברמת המסמך ``level`` הוא ``0``, בתוך
    ציטוט ``1``, בתוך פריט רשימה ``2``, ובקינון עמוק יותר — יותר.

    **וה-``end_line`` כאן זמני.** ``token.map`` מכסה את שורת הכותרת
    בלבד — ``(1, 1)`` ל-ATX ו-``(1, 3)`` ל-setext רב-שורתי — ואינו יודע
    דבר על גוף הסעיף. החישוב האמיתי הוא של ``_finalize`` המשותף, וזו
    הסיבה שהוא לא נכתב כאן מחדש.
    """
    sections: List[Section] = []
    for index, token in enumerate(tokens):
        if token.type != "heading_open" or token.level != 0:
            continue
        # ``is None`` ולא בדיקה בוליאנית: ``map`` הוא שדה של אובייקט
        # SDK, והצורה הזאת נכונה תמיד.
        if token.map is None:
            continue
        start = token.map[0] + 1
        sections.append(
            Section(
                title=_title_of(tokens, index),
                level=int(token.tag[1:]),
                title_line=start,
                heading_line=start,
                end_line=total_lines,
                adornment=token.markup,
                over=False,
            )
        )
    return sections


def _title_of(tokens: List[Token], heading_index: int) -> str:
    """טקסט הכותרת, גולמי מהמקור.

    עם ``inline`` כבוי, ``token.content`` של הטוקן שאחרי ה-``heading_open``
    הוא **כבר** הטקסט כפי שנכתב: ה-``#`` וקו ה-setext מוסרים, רווחים
    מסביב מקוצצים, וכל השאר נשמר — בקטיקים, הדגשה, קישורים, ו-``\\#``
    שעבר escape. לכן אין כאן שום חיתוך מחרוזות; חיתוך ידני הוא בדיוק מה
    שהיה מוסיף מחלקת כשל שאין לה שום צורך להתקיים.

    בכותרת setext רב-שורתית התוכן נושא ``\\n`` באמצעו, וזה מכוון: זה מה
    שכתוב במקור. ``normalize_title`` מכווץ רווחים, ולכן חיפוש הכותרת
    אינו נפגע.
    """
    following = tokens[heading_index + 1] if heading_index + 1 < len(tokens) else None
    if following is None or following.type != "inline":
        return ""
    return following.content.strip()
