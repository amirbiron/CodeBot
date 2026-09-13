"""פארסר RST קליל וטהור — לחילוץ סקשנים לפי כותרות.

מודול עצמאי (בלי תלות ב-MCP) שנועד לשמש כלים שקוראים מקבצי RST של התיעוד:
``docs_get_section`` (עכשיו) ובעתיד ``docs_search`` / ``docs_lookup_config``.

עקרונות מנחים:
- היררכיית הכותרות ב-RST נקבעת **דינמית פר-קובץ** לפי סדר הופעת תווי ה-adornment
  (אין הנחה קשיחה ש-``=`` היא רמה 1). תמיכה ב-underline-only וב-overline+underline.
- כותרות מזוהות אך ורק ב-column 0. תוכן מוזח (list-table, note, code-block, literal blocks)
  שייך לסקשן שמעליו ואינו מפורסר פנימה — חיתוך לפי טווח שורות מטפל בזה נכון.
- שורת ``===``/``---`` בתוך literal block (אחרי ``::``) או ``.. code-block::`` אינה כותרת.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import get_close_matches
from typing import List, Optional, Tuple

# תווי adornment חוקיים לכותרות RST. docutils מגדיר את המחלקה הזאת
# ב-``Body.pats['nonalphanum7bit']`` כ-``[!-/:-@[-`{-~]`` — כל 32 תווי
# הפיסוק ב-ASCII. נגזר כאן מהטווח ולא מוקלד ביד, כי רשימה מוקלדת סוחפת:
# הרשימה שקדמה לזו מנתה 30 תווים והחסירה ',' ו-';', ולכן הסתירה כותרות
# שלמות שהיו כתובות בהם.
_ADORNMENT_CHARS = frozenset(c for c in map(chr, range(0x21, 0x7F)) if not c.isalnum())

# רוחב בעמודות לכל מחלקת רוחב של Unicode, לפי ``docutils.utils.column_width``.
# 'A' (ambiguous) הוא 1 בכוונה — כך במקור, עם הערה שמנמקת שההקשר לא זמין.
_EAST_ASIAN_WIDTHS = {"W": 2, "F": 2, "Na": 1, "H": 1, "N": 1, "A": 1}

# קו adornment קצר מהכותרת אינו כותרת כלל רק אם הוא גם קצר מזה. במקור:
# ``underline()`` ל-underline-only, ו-``Line`` ל-overline.
_MIN_SHORT_ADORNMENT = 4

# ``Body.initial_transitions`` בודק תבניות בסדר קבוע, ומעבר ה-``text`` הוא
# האחרון — כלומר שורה נעשית פסקה רק כשאף תבנית אחרת לא תפסה אותה. שתי
# הקבוצות למטה מתועתקות מ-``Body.patterns`` של docutils 0.23 כמחרוזות, ולא
# נוסחו מחדש.
#
# **וחלוקת הקבוצות נמדדה מול docutils שהורץ, לא נגזרה מקריאת הקוד.** לכל שורה
# יש שני תפקידים נפרדים, והם **אינם** משלימים — וזו ההפתעה שחייבה מדידה:
#
#   השורה                 | יכולה להיות הכותרת? | בולמת כותרת מתחתיה?
#   פסקה רגילה            |         כן          |        כן
#   ``1. פריט``           |         כן          |        כן
#   ``-x ערך``            |         כן          |        כן
#   ``- פריט``            |         לא          |        לא
#   ``:שדה: ערך``         |         לא          |        לא
#   ``.. note:: x``       |         לא          |        לא
#   ``| שורה``            |         לא          |        לא
#   ``+---+``             |         לא          |        לא
#   ``__ יעד``            |         לא          |        לא
#   ``== ==``             |         לא          |        כן
#   ``>>> foo``           |         לא          |        כן
#
# ``enumerator`` ו-``option_marker`` מתנהגים כמו פסקה, ולכן אין להם תבנית
# כאן בכלל: שניהם נופלים חזרה למעבר ה-``text`` דרך ``TransitionCorrection``
# כשהם אינם מרכיבים פריט רשימה תקין, וזה בדיוק המצב כשמתחתיהם קו פיסוק.

# שורה מבנית שנצרכת כשורה אחת, ואינה בולמת כותרת מתחתיה
_BLOCK_LINE_RE = re.compile(
    r"(?:[-+*\u2022\u2023\u2043]( +|$)"          # bullet
    r"|:(?![: ])([^:\\]|\\.|:(?!([ `]|$)))*(?<! ):( +|$)"   # field_marker
    r"|\|( +|$)"                                   # line_block
    r"|\+-[-+]+-\+ *$"                             # grid_table_top
    r"|\.\.( +|$)"                                 # explicit_markup
    r"|__( +|$))"                                  # anonymous
)

# בלוק doctest נמשך עד השורה הריקה, וכותרת בתוכו אינה כותרת
_DOCTEST_RE = re.compile(r">>>( +|$)")

# טבלה פשוטה נפתחת בשורת גבול ונסגרת בשורת גבול — לא בשורה הריקה. לכן
# ההיקף שלה נקרא עד הגבול הסוגר ועד בכלל, ורק אחריו אפשר לזהות כותרת.
# נמדד: ``== ==`` ואחריו קו ``====`` וכותרת מחזיר **כן** כותרת ב-docutils,
# כי ה-``====`` סוגר את הטבלה. בלי הכלל הזה הבלוק נבלע עד השורה הריקה
# והכותרת נעלמת.
_SIMPLE_TABLE_TOP_RE = re.compile(r"=+( +=+)+ *$")
_SIMPLE_TABLE_BORDER_RE = re.compile(r"=+( +=+)* *$")

_DIRECTIVE_RE = re.compile(r"^\.\.[ \t]+\S")  # ".. something::" וכו'
_CODE_DIRECTIVE_RE = re.compile(r"^\.\.[ \t]+(code-block|code|sourcecode|parsed-literal)::")
_INCLUDE_RE = re.compile(r"^\.\.[ \t]+include::[ \t]*(\S.*)$")


@dataclass
class Section:
    """סקשן בודד בעץ הכותרות."""
    title: str
    level: int
    title_line: int          # 1-based — שורת הטקסט של הכותרת
    heading_line: int        # 1-based — שורת ה-overline (או == title_line אם אין overline)
    end_line: int            # 1-based inclusive — סוף התוכן (מחושב ב-_finalize)
    adornment: str
    over: bool = False
    parent: Optional[int] = None
    children: List[int] = field(default_factory=list)
    breadcrumb: List[str] = field(default_factory=list)


@dataclass
class Document:
    lines: List[str]
    sections: List[Section]
    includes: List[str] = field(default_factory=list)  # יעדי .. include:: (לא מורחבים)


def _is_indented(line: str) -> bool:
    return line[:1] in (" ", "\t")


def _adornment_char(line: str) -> Optional[str]:
    """מחזיר את תו ה-adornment אם השורה כולה תו-חזרה בודד (בלי הזחה), אחרת None."""
    if not line or _is_indented(line):
        return None
    s = line.rstrip()
    if not s:
        return None
    # אין מינימום אורך. תבנית ה-``line`` במקור היא
    # ``(nonalphanum7bit)\1* *$`` — תו אחד מספיק, וההכרעה אם זו כותרת
    # נופלת כולה על כלל האורך ב-``_adornment_fits``. שומר "לפחות 2 תווים"
    # שהיה כאן הסתיר כותרת בת תו אחד (docutils: 'A' מעל '=' הוא סקשן),
    # והוסיף כותרת מדומה בשם '-' — כי הוא גם גרם ל-'-' בודד להיראות כטקסט.
    ch = s[0]
    if ch not in _ADORNMENT_CHARS:
        return None
    return ch if all(c == ch for c in s) else None


def _is_title_text(line: str) -> bool:
    """שורה שיכולה להיות טקסט של כותרת: לא ריקה, לא מוזחת, לא adornment-only."""
    if not line or _is_indented(line):
        return False
    return _adornment_char(line) is None


def _is_overlined_title(line: str) -> bool:
    """האם השורה יכולה להיות הכותרת שבין overline ל-underline.

    במצב ``Line`` יש שני מעברים בלבד — ``underline`` ואחריו ``text``,
    שהוא catch-all — ובנוסף ``indent = text``, כלומר שורה מוזחת מנותבת
    לאותו מסלול. לכן כל שורה לא-ריקה מתאימה, למעט שורת פיסוק **לא מוזחת**
    שנתפסת קודם על ידי מעבר ה-``underline``.

    נמדד: כותרת מוזחת בין שני overline זהים היא סקשן, וגם שורת פיסוק
    **מוזחת** במקום הזה היא סקשן (docutils מחזיר '-----' ככותרת). שורה
    ריקה אינה.

    זה נבדל מ-``_is_title_text``, שמשרת את ה-underline-only: שם השורה חייבת
    להיות לא מוזחת, כי במצב ``Body`` שורה מוזחת היא blockquote.
    """
    if not line.strip():
        return False
    if _is_indented(line):
        return True
    return _adornment_char(line) is None


def _display_width(text: str) -> int:
    """רוחב הטקסט בעמודות, כפי ש-docutils מודד אותו ב-``column_width``.

    זה אינו ``len``: תו CJK רחב או full-width תופס שתי עמודות, ותו משולב —
    ניקוד עברי (``U+0591``–``U+05C7``) וסימני הטעמה — תופס אפס. docutils
    משווה את אורך ה-adornment דווקא מול המדידה הזאת, ולכן ``len`` נותן
    תשובה אחרת על עברית מנוקדת ועל אמוג'י.

    בריפו הזה יש תקדים חי: הכותרת '🚀 Quickstart לטסטים' היא 19 תווים אבל
    20 עמודות, והקו שמתחתיה נכתב באורך 20 — כלומר מי שכתב את הקובץ יישר
    לפי רוחב התצוגה, וזה מה ש-docutils דורש.

    ``east_asian_width`` מחזירה אחת משש המחלקות שבטבלה, ולכן ברירת המחדל
    אינה ניתנת להגעה היום; היא קיימת כדי שמחלקה חדשה בגרסת Unicode עתידית
    לא תפיל את הפארסר כולו על ``KeyError``.
    """
    width = sum(_EAST_ASIAN_WIDTHS.get(unicodedata.east_asian_width(c), 1) for c in text)
    return width - sum(1 for c in text if unicodedata.combining(c))


def _adornment_fits(title: str, adornment: str) -> bool:
    """האם שורת ה-adornment ארוכה דיה כדי שהכותרת תיחשב כותרת.

    docutils מפצל את המקרה לשניים — ``underline()`` ל-underline-only,
    ו-``Line.text()`` ל-overline+underline:

    - קו שאינו קצר מרוחב התצוגה של הכותרת → כותרת.
    - קו קצר ממנה **וקצר מ-4** → ``TransitionCorrection``, כלומר אינו כותרת.
    - קו קצר ממנה אבל באורך 4 ומעלה → **כן כותרת**, עם אזהרה
      ('Title underline too short' / 'Title overline too short').

    הפארסר הזה אינו מדווח אזהרות, ולכן השורה האמצעית היא כל ההבדל: לפניה
    כותרת שקיימת הייתה נשמטת מהמפה בשקט.
    """
    line = adornment.rstrip()
    if _display_width(title.rstrip()) > len(line):
        return len(line) >= _MIN_SHORT_ADORNMENT
    return True


def _opens_literal(stripped: str) -> bool:
    """שורה (לא מוזחת) שפותחת literal/code block שבו אין לזהות כותרות."""
    if _CODE_DIRECTIVE_RE.match(stripped):
        return True
    if not stripped.endswith("::") or _DIRECTIVE_RE.match(stripped):
        return False
    # paragraph המסתיים ב-'::' (למשל 'Development::') הוא סמן literal, ולכן
    # הבלוק המוזח שאחריו מדולג כאן.
    #
    # שורה שכולה נקודתיים אינה נכנסת למסלול הזה, כי ב-``Body`` תבנית
    # ה-``line`` נבדקת לפני ``text``: היא נכנסת למצב ``Line`` ככל שורת
    # פיסוק אחרת, ולכן היא **כן** מועמדת ל-overline. (המקרה המיוחד ל-'::'
    # ב-``Body.line()`` מותנה ב-``match_titles`` כבוי, כלומר אינו חל על
    # פרסור מסמך.)
    #
    # **וזה אינו אומר שאין שם literal block.** נמדד ב-docutils 0.23: '::'
    # לבד ואחריו בלוק מוזח מייצר ``literal_block``, ו-':::' מייצר פסקה
    # ואחריה ``literal_block`` — כשאין כותרת תקפה, ``Body.paragraph``
    # מזהה את סיומת ה-'::' ומסמן ``literalnext``. הבלוק המוזח שם אינו
    # מכיל כותרות, וכאן זה יוצא נכון מסיבה אחרת: שורה מוזחת אינה מועמדת
    # לכותרת מלכתחילה. לכן אין להסיק מההערה הזאת שאפשר להסיר את הדילוג על
    # בלוקים מוזחים.
    return _adornment_char(stripped) is None


def parse_document(text: str) -> Document:
    """מפרסר טקסט RST לעץ סקשנים. עמיד ל-literal/code blocks ולדירקטיבות מוזחות."""
    lines = (text or "").split("\n")
    n = len(lines)
    sections: List[Section] = []
    includes: List[str] = []
    # סדר הופעת ה**סגנונות** → קובע את הרמות. סגנון הוא התו ב-underline-only
    # וזוג התווים ב-overline+underline, בדיוק כפי ש-docutils בונה אותו בשני
    # אתרי הקריאה ל-``section()``: ``underline[0]`` מול
    # ``(overline[0], underline[0])``. ``check_subsection`` משווה אותם
    # ב-``title_styles.index(style)``, ולכן '=' ו-('=','=') הם שתי רמות.
    order: List[object] = []

    # docutils ``check_subsection``: ``oldlevel`` — עומק הסקשן הפתוח כרגע,
    # שנגזר שם מ-``len(self.parent.section_hierarchy())``. סקשן שאושר הופך
    # לסקשן הפתוח, ולכן זו הרמה של הסקשן האחרון שאושר.
    current_level = 0

    def level_of(style: object) -> int:
        """הרמה של סגנון, בלי לרשום אותו.

        docutils: ``title_styles.index(style) + 1``, ובכשל
        ``len(title_styles) + 1``. הרישום נפרד בכוונה — סקשן שנדחה על שומר
        הדילוג אינו רושם את הסגנון שלו, כי ה-``return False`` שם קודם
        ל-``title_styles.append``.
        """
        try:
            return order.index(style) + 1
        except ValueError:
            return len(order) + 1

    i = 0
    while i < n:
        raw = lines[i]
        if not _is_indented(raw):
            stripped = raw.rstrip()
            # .. include:: — נאסף בלי הרחבה
            m_inc = _INCLUDE_RE.match(stripped)
            if m_inc:
                includes.append(m_inc.group(1).strip())
                i += 1
                continue
            # literal/code block — דלג על הבלוק המוזח שאחרי השורה הפותחת
            if _opens_literal(stripped):
                i += 1
                while i < n and lines[i].strip() == "":
                    i += 1
                if i < n and _is_indented(lines[i]):
                    block_indent = len(lines[i]) - len(lines[i].lstrip())
                    while i < n:
                        ln = lines[i]
                        if ln.strip() == "":
                            i += 1
                            continue
                        if (len(ln) - len(ln.lstrip())) < block_indent:
                            break
                        i += 1
                continue

            # שורה מבנית: ``Body`` תופס אותה לפני מעבר ה-``text``, ולכן היא
            # אינה יכולה להיות הכותרת עצמה ב-underline-only.
            if _DOCTEST_RE.match(stripped):
                while i < n and lines[i].strip():
                    i += 1
                continue
            if _SIMPLE_TABLE_TOP_RE.match(stripped):
                i += 1
                while i < n and lines[i].strip() and not _SIMPLE_TABLE_BORDER_RE.match(
                        lines[i].rstrip()):
                    i += 1
                if i < n and lines[i].strip():
                    i += 1          # הגבול הסוגר נצרך אף הוא
                continue
            if _BLOCK_LINE_RE.match(stripped):
                i += 1
                continue

        # overline + underline. docutils נכנס כאן למצב ``Line``, ויש לו שלוש
        # יציאות: טקסט ואחריו אותה שורת פיסוק בדיוק → כותרת; כל צורה אחרת
        # כשה-overline באורך 4+ → שגיאה, אין כותרת, והשורות נצרכות; וכל צורה
        # אחרת כשה-overline קצר מ-4 → ``short_overline`` מחזיר את השורה
        # לקריאה כטקסט רגיל, ואז כלל ה-underline-only שמתחת הוא שמכריע.
        over = _adornment_char(raw)
        if over is not None:
            title_line = lines[i + 1] if i + 1 < n else ""
            under_line = lines[i + 2] if i + 2 < n else ""
            # ``Line.text()``: ``elif overline != underline`` — השוואת
            # מחרוזות אחרי rstrip, כלומר אותו תו **וגם אותו אורך**.
            if (_is_overlined_title(title_line)
                    and under_line.rstrip() == raw.rstrip()
                    and _adornment_fits(title_line.strip(), raw)):
                style: object = (over, over)
                lvl = level_of(style)
                if lvl <= current_level + 1:
                    if lvl > len(order):
                        order.append(style)
                    current_level = lvl
                    sections.append(Section(
                        title=title_line.strip(), level=lvl,
                        title_line=i + 2, heading_line=i + 1, end_line=n,
                        adornment=over, over=True,
                    ))
                # אחרת: שומר הדילוג של ``check_subsection`` דחה את הסקשן.
                # השורות נצרכות בכל מקרה — השגיאה מחליפה את הסקשן, ולא את הטקסט.
                i += 3
                continue
            if len(raw.rstrip()) >= _MIN_SHORT_ADORNMENT:
                # overline באורך 4+ שאין לו כותרת תקינה: ב-docutils זו שגיאה
                # ואין כותרת. מספר השורות שנצרכות תלוי ביציאה שנבחרה שם.
                if title_line.strip() and _adornment_char(title_line) is None:
                    i += 3          # ``Line.text`` / ``Line.indent`` — טקסט
                elif title_line.strip():
                    i += 2          # ``Line.underline`` — שתי שורות פיסוק
                else:
                    i += 1          # ``Line.blank`` — transition
                continue
            # overline קצר מ-4 שאין לו כותרת תקינה: ``short_overline`` קורא
            # ל-``state_correction``, שמחזיר את השורה ל-Body דרך מעבר
            # ה-``text`` — כלומר השורה שהודחה נכנסת למצב ``Text`` ככותרת
            # בפוטנציה, ומשם השורה ה**באה בלבד** מכריעה: adornment → כותרת
            # בשם השורה שהודחה; כל דבר אחר → פסקה שבולעת את הבלוק עד השורה
            # הריקה, ואין בה כותרת.
            demoted = _adornment_char(title_line)
            if demoted is not None and _adornment_fits(raw, title_line):
                lvl = level_of(demoted)
                if lvl <= current_level + 1:
                    if lvl > len(order):
                        order.append(demoted)
                    current_level = lvl
                    sections.append(Section(
                        title=raw.strip(), level=lvl,
                        title_line=i + 1, heading_line=i + 1, end_line=n,
                        adornment=demoted, over=False,
                    ))
                i += 2
                continue
            while i < n and lines[i].strip():
                i += 1
            continue

        # underline-only: טקסט ואחריו שורת פיסוק
        if _is_title_text(raw) and i + 1 < n:
            under = _adornment_char(lines[i + 1])
            if under is not None and _adornment_fits(raw, lines[i + 1]):
                lvl = level_of(under)
                if lvl <= current_level + 1:
                    if lvl > len(order):
                        order.append(under)
                    current_level = lvl
                    sections.append(Section(
                        title=raw.strip(), level=lvl,
                        title_line=i + 1, heading_line=i + 1, end_line=n,
                        adornment=under, over=False,
                    ))
                # אחרת: שומר הדילוג דחה. גם כאן השורות נצרכות.
                i += 2
                continue
            # השורה אינה כותרת, והיא שורת פסקה — ולכן ``Text.text()`` קורא
            # את כל הבלוק עד השורה הריקה כפסקה אחת. כל מה שבתוכו אינו
            # כותרת, גם אם הוא נראה כמו אחת: פסקה בת שתי שורות ואחריה קו
            # פיסוק אינה סקשן, נמדד ב-docutils.
            while i < n and lines[i].strip():
                i += 1
            continue

        i += 1

    _finalize(sections, n)
    return Document(lines=lines, sections=sections, includes=includes)


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
