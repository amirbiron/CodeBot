"""טסטים לפארסר ה-RST — על קבצי RST אמיתיים מהריפו + מקרי קצה סינתטיים ממוקדים."""

import json
import re
from pathlib import Path

from services import rst_parser

_ENV_RST = Path(__file__).resolve().parents[1] / "docs" / "environment-variables.rst"


def _env_doc():
    return rst_parser.parse_document(_ENV_RST.read_text(encoding="utf-8"))


# ---- על RST אמיתי (environment-variables.rst) ----

def test_literal_block_lines_not_parsed_as_headings():
    """הבאג הכי צפוי: שורות בתוך literal block (Development:: ...) אינן כותרות."""
    doc = _env_doc()
    titles = [s.title for s in doc.sections]
    assert not [t for t in titles if "=" in t or "BOT_TOKEN" in t or t != t.strip()]
    assert "דוגמאות קונפיגורציה" in titles  # הכותרת עצמה כן, התוכן המוזח לא


def test_dynamic_hierarchy_is_per_file():
    """= → רמה 1, - → רמה 2 — נקבע דינמית לפי סדר ההופעה, לא קשיח."""
    doc = _env_doc()
    h1 = [s for s in doc.sections if s.level == 1]
    assert len(h1) == 1 and h1[0].title == "משתני סביבה - רפרנס" and h1[0].adornment == "="
    h2 = [s for s in doc.sections if s.level == 2]
    assert h2 and all(s.adornment == "-" for s in h2)
    assert "טבלה מרכזית" in [s.title for s in h2]


def test_main_table_bounds_cover_whole_table():
    """'טבלה מרכזית' מכסה את כל ה-list-table (חיתוך לפי טווח שורות מטפל בדירקטיבה המוזחת)."""
    doc = _env_doc()
    secs = rst_parser.find_sections(doc, "טבלה מרכזית")
    assert len(secs) == 1
    text = rst_parser.section_text(doc, secs[0], include_subsections=True)
    assert ".. list-table:: Environment Variables" in text
    assert "BOT_TOKEN" in text  # שורה מתוך הטבלה
    assert secs[0].breadcrumb == ["משתני סביבה - רפרנס", "טבלה מרכזית"]


def test_forgiving_match_spaces_and_hyphen():
    doc = _env_doc()
    # מקף רגיל, רווחים כפולים ורווחי קצה — כולם צריכים להתאים
    assert len(rst_parser.find_sections(doc, "  טבלה   מרכזית ")) == 1


# ---- מקרי קצה סינתטיים ----

def test_overline_underline_heading():
    doc = rst_parser.parse_document("======\nTitle\n======\n\nbody\n")
    assert len(doc.sections) == 1
    assert doc.sections[0].title == "Title" and doc.sections[0].over is True


def test_duplicate_headings_return_all():
    rst = "Doc\n===\n\nמטרה\n----\n\naaa\n\nחלק\n----\n\nbbb\n\nמטרה\n----\n\nccc\n"
    doc = rst_parser.parse_document(rst)
    assert len(rst_parser.find_sections(doc, "מטרה")) == 2


def test_case_insensitive_english():
    doc = rst_parser.parse_document("Title\n=====\n\nMy Section\n----------\n\nx\n")
    assert len(rst_parser.find_sections(doc, "my section")) == 1


def test_no_headings_returns_empty():
    doc = rst_parser.parse_document("just text\nmore text without headings\n")
    assert doc.sections == []
    assert rst_parser.build_toc(doc) == []


def test_include_collected_not_expanded():
    doc = rst_parser.parse_document("Doc\n===\n\n.. include:: other.rst\n\nbody\n")
    assert doc.includes == ["other.rst"]


def test_code_block_dashes_not_heading():
    """שורת ---- בתוך code-block אינה כותרת."""
    rst = "Doc\n===\n\n.. code-block:: text\n\n   ----\n   inner line\n\nReal\n----\n\nx\n"
    doc = rst_parser.parse_document(rst)
    titles = [s.title for s in doc.sections]
    assert "Real" in titles
    assert "inner line" not in titles


def test_include_subsections_false_stops_before_child():
    rst = "Parent\n======\n\nintro\n\nChild\n-----\n\nchild body\n"
    doc = rst_parser.parse_document(rst)
    sec = rst_parser.find_sections(doc, "Parent")[0]
    full = rst_parser.section_text(doc, sec, include_subsections=True)
    partial = rst_parser.section_text(doc, sec, include_subsections=False)
    assert "child body" in full
    assert "child body" not in partial
    assert "intro" in partial


# ============================================================================
# אורקלים בלתי-תלויים מול docutils 0.23
# ============================================================================
#
# שני האורקלים שלמטה נכתבו **בנפרד ובמנותק** מ-``services.rst_parser``: הם
# אינם מייבאים ממנו דבר ואינם קוראים לו. זה מכוון, ומאותו נימוק שכתוב
# ב-``.. warning::`` של ``_structural_blocks`` בטסטי האאוטליין — אורקל שגוזר
# את הציפייה מהמימוש מעמיד את שני צידי ההשוואה על מקור אחד, ואז קריסה חלקית
# עוברת בשקט. השכפול כאן **הוא** ההגנה, ואין להחליף אותו בייבוא.
#
# כל טענה בטסטים שלמטה נמדדה בהרצה של docutils 0.23 עצמו, ולא נגזרה מקריאת
# הקוד שלו. ההפניות למקור הן לפי שם הפונקציה ולא לפי מספר שורה, כי מספר
# שורה מצביע למקום אחר בגרסה הבאה.

_DOCS = Path(__file__).resolve().parents[1] / "docs"

# מחלקת תווי ה-adornment: ``Body.pats['nonalphanum7bit']`` היא ``[!-/:-@[-`{-~]``
_PUNCTUATION = frozenset(c for c in map(chr, range(0x21, 0x7F)) if not c.isalnum())

# ``docutils.utils.column_width``
_WIDTHS = {"W": 2, "F": 2, "Na": 1, "H": 1, "N": 1, "A": 1}

# שורות ש-``Body`` תופס לפני מעבר ה-``text``, ולכן אינן יכולות להיות
# הכותרת עצמה. מנוסחות כאן מחדש ובנפרד מהמימוש; החלוקה לשלוש ההתנהגויות
# נמדדה מול docutils שהורץ, ומתועדת בטבלה שבראש ``services/rst_parser.py``.
# ``enumerator`` ו-``option_marker`` **אינם** כאן בכוונה — הם מתנהגים כמו
# פסקה, ונמדדו ככאלה.
_STRUCTURAL = re.compile(
    r"(?:[-+*\u2022\u2023\u2043]( +|$)"
    r"|:(?![: ])([^:\\]|\\.|:(?!([ `]|$)))*(?<! ):( +|$)"
    r"|\|( +|$)"
    r"|\+-[-+]+-\+ *$"
    r"|\.\.( +|$)"
    r"|__( +|$))"
)
_DOCTEST = re.compile(r">>>( +|$)")
_TABLE_TOP = re.compile(r"=+( +=+)+ *$")
_TABLE_BORDER = re.compile(r"=+( +=+)* *$")


def _display_width(text):
    """רוחב בעמודות: תו רחב שווה 2, תו משולב (ניקוד) שווה 0."""
    import unicodedata
    wide = sum(_WIDTHS.get(unicodedata.east_asian_width(c), 1) for c in text)
    return wide - sum(1 for c in text if unicodedata.combining(c))


def _is_punctuation_line(stripped):
    return bool(stripped) and stripped[0] in _PUNCTUATION and all(
        c == stripped[0] for c in stripped)


def _adornment_is_long_enough(title, adornment):
    """``underline()``: קצר מרוחב הכותרת וגם מ-4 — אינו כותרת; 4+ — כן."""
    return _display_width(title) <= len(adornment) or len(adornment) >= 4


def _independent_headings(lines):
    """כל הכותרות בקובץ, לפי צורת הטקסט בלבד: (כותרת, סגנון, שורת-פתיחה).

    מזהה שנכתב מאפס ואינו יודע דבר על literal blocks, על ``::`` או על
    דירקטיבות — הוא מדלג על שורות מוזחות, מסווג שורות מבניות לפי התבניות
    שלמעלה, מכבד את העובדה ש**פסקה שנפתחה בולעת את הבלוק עד השורה
    הריקה**, ומחזיק את היקף הטבלה הפשוטה לפי שלושת תנאי הסגירה
    שבמקור ולא לפי הגבול הראשון. העובדה שהוא מסכים עם המימוש על כל קובץ בריפו היא מה שהופך
    אותו לעוגן: הוא מגיע לאותה תשובה דרך היגיון אחר.

    הסגנון הוא התו ב-underline-only, וזוג התווים ב-overline+underline —
    כפי ש-docutils בונה אותו בשני אתרי הקריאה ל-``section()``.
    """
    found, i, n = [], 0, len(lines)
    while i < n:
        cur = lines[i]
        if not cur.strip():
            i += 1
            continue
        if cur[:1] in (" ", "\t"):
            i += 1
            continue
        top = cur.rstrip()

        # overline: שורת פיסוק, ואחריה כותרת ואותה שורת פיסוק בדיוק
        if _is_punctuation_line(top):
            middle = lines[i + 1] if i + 1 < n else None
            bottom = lines[i + 2].rstrip() if i + 2 < n else None
            middle_ok = middle is not None and bool(middle.strip()) and (
                middle[:1] in (" ", "\t") or not _is_punctuation_line(middle.rstrip()))
            # ``rstrip`` ולא ``strip``, וזה נגזר מ-``Line.text`` במקור:
            # שם ``title.rstrip()`` נמדד מול הקו, וה-``lstrip`` קורה אחר כך
            # ורק לטקסט שנשמר — כלומר **ההזחה נספרת ברוחב**. עם ``strip``
            # האורקל החזיר כאן כותרת ש-docutils דוחה, כלומר הוא הפסיק
            # להיות עוגן בדיוק לכלל שהמימוש תיקן.
            if (middle_ok and bottom is not None and bottom == top
                    and _adornment_is_long_enough(middle.rstrip(), bottom)):
                found.append((middle.strip(), (top[0], top[0]), i + 1))
                i += 3
                continue

            # **ו-overline פגום נצרך כקונסטרוקט, ואינו נופל חזרה לזיהוי
            # underline-only.** נגזר ממצב ``Line`` במקור, שבו כל מוצא
            # מתפצל על אורך ה-overline: קצר מ-4 ← ``short_overline``
            # ו-``state_correction``, כלומר השורה חוזרת למעבר ה-``text``
            # ומותר ליפול; ארבעה ומעלה ← שגיאה וחזרה ל-``Body``, כלומר
            # השורות נצרכות ואין סעיף. שלושת המוצאים: שורה ריקה אחריה היא
            # ``Line.blank`` וצורכת אחת; שורת פיסוק אחריה היא
            # ``Line.underline`` וצורכת שתיים; וטקסט אחריה הוא
            # ``Line.text``, שצורך שתיים בסוף קלט ושלוש כשה-underline
            # חסר או שונה.
            #
            # בלי זה האורקל קרא ``=====`` / כותרת / ``-----`` פעמיים: פעם
            # כ-overline שנכשל, ואז את הכותרת והקו שמתחתיה כסעיף
            # underline-only — כלומר הוא **המציא** כותרת ש-docutils
            # והמימוש שניהם דוחים.
            if len(top) >= 4:
                if middle is None or not middle.strip():
                    i += 1
                elif _is_punctuation_line(middle.rstrip()):
                    i += 2
                else:
                    i += 2 if bottom is None else 3
                continue

        # שורות מבניות — אינן יכולות להיות הכותרת
        if _DOCTEST.match(top):
            while i < n and lines[i].strip():
                i += 1
            continue
        if _TABLE_TOP.match(top):
            # היקף הטבלה, נגזר מהתיאור של ``isolate_simple_table``: הגבול
            # הסוגר הוא הראשון מבין השלושה — השני שנמצא, האחרון בקלט, או
            # אחד שאחריו שורה ריקה — והוא נכלל בהיקף. שורה ריקה בתוך הגוף
            # אינה מסיימת. גבול באורך אחר מסמן טבלה פגומה שנגמרת בו, וטבלה
            # בלי גבול כלל בולעת את השאר.
            #
            # **והכלל נגזר כאן מהמקור ולא מהמימוש שנבדק** — זו כל הנקודה
            # של אורקל בלתי-תלוי, וההעתקה מהקוד שמולו הוא מושווה הייתה
            # מעמידה את שני הצדדים על מקור אחד.
            width = len(top)
            seen = 0
            last_edge = None
            closing = None
            probe = i + 1
            while probe < n:
                edge = lines[probe].rstrip()
                if _TABLE_BORDER.match(edge):
                    if len(edge) != width:
                        closing = probe
                        break
                    seen += 1
                    last_edge = probe
                    if seen == 2 or probe + 1 >= n or not lines[probe + 1].strip():
                        closing = probe
                        break
                probe += 1
            if closing is None:
                # הלולאה מומשה בלי תנאי סגירה: במקור ההיקף נגמר בגבול
                # האחרון שנמצא, ובלי גבול כלל — בסוף הקלט.
                closing = last_edge if last_edge is not None else n - 1
            i = closing + 1
            continue
        # שורה מבנית אינה יכולה להיות הכותרת עצמה, והיא גם אינה בולמת
        # כותרת שמתחתיה — ולכן שורה אחת בלבד.
        #
        # **ושורת פיסוק קצרה מ-4 אינה כאן.** ב-``Line`` שבמקור היא עוברת
        # ``short_overline`` ואז ``state_correction``, כלומר היא חוזרת
        # למעבר ה-``text`` ונעשית **הכותרת בפוטנציה** — והשורה שאחריה
        # לבדה מכריעה: קו פיסוק שנכנס באורך ← כותרת בשם השורה הקצרה,
        # וכל דבר אחר ← פסקה שבולעת את הבלוק. דילוג של שורה אחת כאן
        # העביר את התור לשורה הבאה, ואז ``=`` / ``T`` / ``-`` נתן כותרת
        # ``T`` ש-docutils והמימוש שניהם דוחים. לכן היא נופלת למסלול
        # הפסקה שלמטה, שמחזיק בדיוק את שני הכיוונים האלה.
        if _STRUCTURAL.match(top):
            i += 1
            continue

        # שורת פסקה: או שהשורה הבאה היא קו והיא כותרת, או שהפסקה בולעת
        # את הבלוק ואין בו כותרת
        if i + 1 < n:
            bottom = lines[i + 1].rstrip()
            if (_is_punctuation_line(bottom)
                    and lines[i + 1][:1] not in (" ", "\t")
                    and _adornment_is_long_enough(top, bottom)):
                found.append((top.strip(), bottom[0], i + 1))
                i += 2
                continue
        # הבלוק נגמר בשורה ריקה **או** בשורה מוזחת, כי ``Text.text`` קורא
        # אותו ב-``get_text_block(flush_left=True)``. בלי העצירה על ההזחה
        # האורקל איבד כותרת ש-docutils והמימוש שניהם מחזירים.
        #
        # וזה אינו נכון ללולאת ה-doctest שלמעלה: ``Body.doctest`` קורא
        # ``get_text_block()`` בלי ``flush_left``, ושם רק שורה ריקה מסיימת.
        i += 1
        while i < n and lines[i].strip() and lines[i][:1] not in (" ", "\t"):
            i += 1
    return found


def _docutils_levels(styles, *, guard=True):
    """הרמות ש-docutils נותן לרצף סגנונות, ומי מהם נזרק.

    שחזור של ``check_subsection`` (docutils 0.23, ``parsers/rst/states.py``).
    שלושת הכללים, מהמקור:

        newlevel = title_styles.index(style) + 1     (ובכשל: len + 1)
        newlevel > oldlevel + 1   → 'Inconsistent title style' → הסקשן נזרק
        newlevel > len(title_styles) → הסגנון נרשם

    ``oldlevel`` שם הוא ``len(parent_sections) + section_level_offset``, עם
    הערה בקוד: "current section level: (0 root, 1 section, 2 subsection...)".
    סקשן שאושר הופך לסקשן הפתוח, ולכן זו הרמה של האחרון שאושר.
    ``section_level_offset`` הוא אפס מחוץ ל-``nested_parse``.

    ענף הכשל השני שם — 'A level N section cannot be used here' — אינו ניתן
    להגעה בפרסור מסמך שלם: האינדקס בו שלילי, והוא חורג רק כאשר newlevel < 1.

    ``guard=False`` מנטרל את שומר הדילוג, והוא קיים כדי שטסט המוטציה יוכיח
    שהאורקל מסוגל להיכשל.

    מחזיר רשימה באורך ``styles``: הרמה, או ``None`` לסגנון שנזרק.
    """
    title_styles, levels, oldlevel = [], [], 0
    for style in styles:
        try:
            newlevel = title_styles.index(style) + 1
        except ValueError:
            newlevel = len(title_styles) + 1
        if guard and newlevel > oldlevel + 1:
            levels.append(None)
            continue
        if newlevel > len(title_styles):
            title_styles.append(style)
        levels.append(newlevel)
        oldlevel = newlevel
    return levels


def _expected_sections(text, *, guard=True):
    """(כותרת, רמה) לכל סקשן, משני האורקלים יחד ובלי לגעת במימוש."""
    headings = _independent_headings(text.split("\n"))
    levels = _docutils_levels([style for _t, style, _l in headings], guard=guard)
    return [(title, lvl)
            for (title, _style, _line), lvl in zip(headings, levels, strict=True)
            if lvl is not None]


def _rst_files():
    assert _DOCS.is_dir(), f"תיקיית התיעוד חסרה: {_DOCS}"
    files = sorted(_DOCS.rglob("*.rst"))
    # תיקייה שקיימת ומחזירה אפס קבצים היא כישלון, לא דילוג
    assert files, f"אפס קובצי .rst תחת {_DOCS}"
    return files


class TestHierarchyMatchesDocutilsCheckSubsection:
    """הרמות נקבעות לפי סדר הופעת הסגנונות, כולל חזרה לרמה קודמת."""

    def test_every_rst_file_in_the_repo_matches_the_two_oracles(self):
        """כל 1,336 הסקשנים בכל קובצי ה-RST — מול מזהה ואורקל עצמאיים."""
        mismatches = []
        total = 0
        for path in _rst_files():
            text = path.read_text(encoding="utf-8", errors="replace")
            actual = [(s.title, s.level)
                      for s in rst_parser.parse_document(text).sections]
            expected = _expected_sections(text)
            total += len(expected)
            if actual != expected:
                mismatches.append((path.name, len(actual), len(expected)))
        assert not mismatches, f"אי-התאמה מול האורקלים: {mismatches[:5]}"
        assert total > 1000, f"האורקל מצא רק {total} סקשנים — חשוד מדי"

    def test_a_repeated_adornment_returns_to_its_earlier_level(self):
        """'=', '-', '=' → 1, 2, 1. נמדד ב-docutils."""
        text = "A\n===\n\nB\n---\n\nC\n===\n\nגוף\n"
        levels = [s.level for s in rst_parser.parse_document(text).sections]
        assert levels == [1, 2, 1]
        assert [lvl for _t, lvl in _expected_sections(text)] == [1, 2, 1]

    def test_a_new_adornment_after_returning_is_dropped(self):
        """'=', '-', '=', '~' → docutils זורק את הרביעי.

        ``skip from level 1 to 3`` — נמדד: docutils מחזיר A=1, B=2, C=1 ו-D
        אינו קיים בעץ. לפני התיקון הפארסר ייצר אותו ברמה 3.
        """
        text = "A\n===\n\nB\n---\n\nC\n===\n\nD\n~~~\n\nגוף\n"
        titles = [s.title for s in rst_parser.parse_document(text).sections]
        assert titles == ["A", "B", "C"], "D אינו סקשן ב-docutils"
        assert [t for t, _lvl in _expected_sections(text)] == ["A", "B", "C"]

    def test_overline_and_underline_is_a_style_of_its_own(self):
        """אותו תו, פעם underline-only ופעם overline+underline → שתי רמות.

        ``section()`` נקרא משני אתרים: ``style = underline[0]`` לעומת
        ``style = (overline[0], underline[0])``, ו-``check_subsection`` משווה
        ביניהם ב-``index(style)``. נמדד: docutils נותן 1 ואז 2.
        """
        text = "כותרת א\n========\n\n========\nכותרת ב\n========\n\nגוף\n"
        secs = rst_parser.parse_document(text).sections
        assert [(s.title, s.level, s.over) for s in secs] == [
            ("כותרת א", 1, False), ("כותרת ב", 2, True)]

    def test_going_deeper_and_back_up_again_keeps_working(self):
        """'=','-','~','-','~' → 1,2,3,2,3. שומר הדילוג אינו נדלק כאן."""
        text = ("A\n===\n\nB\n---\n\nC\n~~~\n\nD\n---\n\nE\n~~~\n\nגוף\n")
        levels = [s.level for s in rst_parser.parse_document(text).sections]
        assert levels == [1, 2, 3, 2, 3]

    def test_the_oracle_can_actually_fail(self):
        """אורקל שלא מסוגל להפיל מימוש שגוי אינו ראיה.

        מנטרל את שומר הדילוג באורקל, ודורש שהוא **יחלוק** על המימוש — כלומר
        שהטענה בטסט למעלה נשענת על השומר ולא עוברת ממילא.
        """
        text = "A\n===\n\nB\n---\n\nC\n===\n\nD\n~~~\n\nגוף\n"
        with_guard = _expected_sections(text)
        without_guard = _expected_sections(text, guard=False)
        assert with_guard != without_guard
        assert [t for t, _ in without_guard] == ["A", "B", "C", "D"]
        assert [t for t, _ in with_guard] == ["A", "B", "C"]


class TestTitleRecognitionMatchesDocutils:
    """מה נחשב כותרת בכלל. כל טענה נמדדה בהרצה של docutils 0.23."""

    def test_an_adornment_shorter_than_the_title_but_at_least_four_is_a_title(self):
        """docutils: 'Title underline too short' — אזהרה, והסקשן **נוצר**.

        לפני התיקון הפארסר הפיל את המקרה הזה, כלומר השמיט בשקט סעיף שקיים.
        """
        doc = rst_parser.parse_document("כותרת ארוכה\n====\n\nגוף\n")
        assert [s.title for s in doc.sections] == ["כותרת ארוכה"]

    def test_an_adornment_shorter_than_the_title_and_shorter_than_four_is_not(self):
        """docutils: ``len(underline) < 4`` → 'Treating it as ordinary text'."""
        doc = rst_parser.parse_document("כותרת ארוכה\n===\n\nגוף\n")
        assert doc.sections == []

    def test_the_length_rule_measures_display_width_not_character_count(self):
        """ההשוואה היא מול ``column_width``, לא מול ``len``.

        'שָׁלוֹם עוֹלָם' הוא 14 תווים אבל 9 עמודות — חמישה סימני ניקוד נחשבים
        אפס. קו באורך 10 קצר מ-``len`` וארוך מהרוחב, ולכן ב-docutils זו
        כותרת נקייה בלי אזהרה. לפני התיקון הפארסר השמיט אותה.
        """
        title = "שָׁלוֹם עוֹלָם"
        assert len(title) == 14, "ה-fixture נשען על הניקוד — אין לנרמל אותו"
        doc = rst_parser.parse_document(f"{title}\n{'=' * 10}\n\nגוף\n")
        assert [s.title for s in doc.sections] == [title]

    def test_an_emoji_counts_as_two_columns(self):
        """תו רחב תופס שתי עמודות, ולכן קו באורך len אינו מספיק.

        הקובץ ``docs/testing.rst`` הוא התקדים החי: הכותרת שם היא 19 תווים
        ו-20 עמודות, והקו שמתחתיה נכתב 20.
        """
        assert _display_width("🚀 a") == 4 and len("🚀 a") == 3
        doc = rst_parser.parse_document("🚀 a\n===\n\nגוף\n")
        assert doc.sections == [], "רוחב 4 מול קו 3 שקצר מ-4 → אינו כותרת"

    def test_comma_and_semicolon_are_adornment_characters(self):
        """המקור מגדיר 32 תווי פיסוק; הרשימה שקדמה מנתה 30 והחסירה את שניהם."""
        for char in (",", ";"):
            doc = rst_parser.parse_document(f"כותרת\n{char * 6}\n\nגוף\n")
            assert [s.title for s in doc.sections] == ["כותרת"], char

    def test_every_ascii_punctuation_character_is_an_adornment(self):
        """כל 32 התווים, ולא רק השניים שהיו חסרים."""
        assert len(_PUNCTUATION) == 32
        for char in sorted(_PUNCTUATION):
            doc = rst_parser.parse_document(f"כותרת\n{char * 6}\n\nגוף\n")
            assert [s.title for s in doc.sections] == ["כותרת"], repr(char)

    def test_an_overline_must_match_the_underline_in_length_too(self):
        """``Line.text()``: ``elif overline != underline`` — השוואת מחרוזות.

        כלומר אותו תו **וגם** אותו אורך. נמדד: overline באורך 5 מול underline
        באורך 9 מחזיר ``Title overline & underline mismatch`` ואפס סקשנים.
        """
        doc = rst_parser.parse_document("=====\nכותרת\n=========\n\nגוף\n")
        assert doc.sections == []

    def test_an_overline_equal_to_the_underline_is_a_title(self):
        """בקרה לטסט שמעליו: שווים בדיוק — כן כותרת."""
        doc = rst_parser.parse_document("=========\nכותרת\n=========\n\nגוף\n")
        assert [(s.title, s.over) for s in doc.sections] == [("כותרת", True)]

    def test_a_single_character_title_with_a_single_character_adornment(self):
        """תבנית ה-``line`` היא ``(nonalphanum7bit)\\1* *$`` — תו אחד מספיק.

        נמדד: 'A' מעל '=' הוא סקשן ב-docutils. שומר "לפחות 2 תווים" שהיה
        בפארסר הסתיר אותו.
        """
        doc = rst_parser.parse_document("A\n=\n\nגוף\n")
        assert [s.title for s in doc.sections] == ["A"]

    def test_a_lone_bullet_is_not_an_overline(self):
        """'-' בודד נחטף על ידי תבנית ה-``bullet``, לפני תבנית ה-``line``.

        ``Body.initial_transitions`` מתחיל ב-'bullet' ו-'line' מופיע בו אחד
        לפני האחרון. נמדד מול טבלת התבניות: '-', '+', '*', '|', '..', '__'
        ו-'>>>' הן **כל** המחרוזות האחידות שנחטפות. נמדד ב-docutils שהצורה
        הזאת מחזירה אפס סקשנים; לפני התיקון הפארסר ייצר כותרת בשם '-'.
        """
        doc = rst_parser.parse_document("-\n---\n\nגוף\n")
        assert doc.sections == []

    def test_a_table_top_is_still_an_adornment(self):
        """'====' אינו נחטף על ידי תבניות הטבלאות — אחרת הכותרת הנפוצה
        ביותר ב-RST הייתה נקראת כראש טבלה."""
        doc = rst_parser.parse_document("====\nכותרת\n====\n\nגוף\n")
        assert [s.title for s in doc.sections] == ["כותרת"]

    def test_a_line_of_only_colons_is_not_a_literal_block_marker(self):
        """שורה שכולה ':' נכנסת למצב ``Line`` ככל שורת פיסוק.

        המקרה המיוחד ל-'::' ב-``Body.line()`` מותנה ב-``match_titles`` כבוי,
        ולכן אינו חל על פרסור מסמך. נמדד: docutils מחזיר אפס סקשנים לצורה
        הזאת, ולפני התיקון הפארסר ייצר את 'a' כסקשן.
        """
        doc = rst_parser.parse_document("::::\na\n:::\n\nגוף\n")
        assert doc.sections == []

    def test_a_paragraph_ending_in_colons_still_suppresses_its_literal_block(self):
        """הבקרה לטסט שמעליו: 'Development::' כן סמן literal.

        נמדד ב-docutils על שתי הצורות — פסקה שנגמרת ב-'::' ו-'::' לבד בשורה
        אחרי פסקה — ובשתיהן ה-'----' המוזח אינו כותרת.
        """
        with_paragraph = rst_parser.parse_document(
            "Doc\n===\n\nDevelopment::\n\n   ----\n   inner\n\nReal\n----\n\nx\n")
        assert [s.title for s in with_paragraph.sections] == ["Doc", "Real"]
        on_its_own = rst_parser.parse_document(
            "Doc\n===\n\nתפריט:\n::\n\n   [כפתור]\n   ----\n\nReal\n----\n\nx\n")
        assert [s.title for s in on_its_own.sections] == ["Doc", "Real"]

    def test_a_heading_inside_a_doctest_block_is_not_a_heading(self):
        """``Body.patterns['doctest']`` הוא ``>>>( +|$)``, לפני ``line``.

        בלוק doctest נמשך עד השורה הריקה, ולכן צורת כותרת בתוכו אינה כותרת.
        נמדד בשתי הצורות — '>>>' לבד ו-'>>> foo' — ובשתיהן docutils מחזיר
        אפס סקשנים. הבקרה: שורה ריקה אחרי ה-doctest פותחת את הבלוק, ואז
        הכותרת שאחריה **כן** כותרת.
        """
        for opener in (">>>", ">>> foo"):
            doc = rst_parser.parse_document(f"{opener}\na\n---\n\nגוף\n")
            assert doc.sections == [], opener
        after_blank = rst_parser.parse_document(">>>\n\na\n---\n\nגוף\n")
        assert [s.title for s in after_blank.sections] == ["a"]

    def test_a_paragraph_that_already_opened_swallows_the_line_below_it(self):
        """שתי שורות טקסט ואחריהן קו — אין כאן כותרת.

        ``Text`` הוא "השורה השנייה של בלוק טקסט": אם היא אינה קו פיסוק,
        ``Text.text()`` קורא את **כל** הבלוק עד השורה הריקה כפסקה אחת, וקו
        הפיסוק שבתוכו אינו נבדק בכלל. נמדד: docutils מחזיר אפס סקשנים לשתי
        שורות ולשלוש. לפני התיקון הפארסר ייצר כותרת מהשורה האחרונה בפסקה.
        """
        for body in ("שורה א\nשורה ב\n=========\n\nגוף\n",
                     "א\nב\nג\n=========\n\nגוף\n"):
            assert rst_parser.parse_document(body).sections == [], body
            assert _expected_sections(body) == []

    def test_a_blank_line_above_reopens_the_block(self):
        """הבקרה: שורה ריקה מפרידה, ואז הכותרת **כן** כותרת."""
        doc = rst_parser.parse_document("שורה א\n\nשורה ב\n=========\n\nגוף\n")
        assert [s.title for s in doc.sections] == ["שורה ב"]

    def test_a_structural_line_above_does_not_swallow_the_heading(self):
        """והכלל אינו "אחרי שורה ריקה" אלא "פסקה שכבר נפתחה".

        נמדד ב-docutils: בולט, שורת שדה, דירקטיבה, ``line_block``, ראש
        טבלת grid ויעד אנונימי — כולם מעל כותרת, בלי שורה ריקה ביניהם —
        וה**כותרת נוצרת**. רק שורת פסקה בולמת.

        וקו הפיסוק של הכותרת שלפניה גם הוא אינו בולם, אבל מסיבה אחרת: הוא
        נצרך כחלק מאותה כותרת. **הבחנה שנמדדה ולא הונחה** — קו פיסוק שיושב
        מעל כותרת ואינו נצרך כך הוא overline, ואם אורכו שונה מה-underline
        docutils דוחה את כל הצורה: ``======`` מעל כותרת שהקו שלה
        ``=========`` מחזיר אפס סקשנים.
        """
        for above in ("- פריט", ":שדה: ערך", ".. note:: x", "| שורה",
                      "+---+", "__ יעד"):
            doc = rst_parser.parse_document(f"{above}\nכותרת\n=========\n\nגוף\n")
            assert "כותרת" in [s.title for s in doc.sections], above
        after_heading = rst_parser.parse_document(
            "Doc\n===\nכותרת\n=========\n\nגוף\n")
        assert [s.title for s in after_heading.sections] == ["Doc", "כותרת"]
        mismatched_overline = rst_parser.parse_document(
            "======\nכותרת\n=========\n\nגוף\n")
        assert mismatched_overline.sections == []

    def test_a_structural_line_cannot_be_the_title_itself(self):
        """שורה ש-``Body`` תופס אינה יכולה להיות הכותרת ב-underline-only.

        נמדד: בולט, שורת שדה, ``line_block``, דירקטיבה, ראש טבלת grid, ראש
        טבלה פשוטה ויעד אנונימי — כל אחד מהם עם קו פיסוק מתחתיו מחזיר אפס
        סקשנים. לפני התיקון כל אחד מהם הפך לכותרת בשם עצמו.
        """
        for line in ("- פריט", ":שדה: ערך", "| שורה", ".. note:: x",
                     "+---+", "== ==", "__ יעד"):
            doc = rst_parser.parse_document(f"{line}\n{'=' * 12}\n\nגוף\n")
            assert doc.sections == [], line

    def test_an_enumerator_and_an_option_behave_like_a_paragraph(self):
        """שתי התבניות שנופלות חזרה ל-``text``, ולכן כן כותרת.

        ``Body.enumerator`` ו-``Body.option_marker`` זורקים
        ``TransitionCorrection('text')`` כשהם אינם מרכיבים פריט תקין — וזה
        המצב כשמתחתיהם קו פיסוק. נמדד בשתי הצורות, וגם בתפקיד ההפוך: שתיהן
        **כן** בולמות כותרת שמתחתיהן, בדיוק כמו פסקה.
        """
        for line in ("1. פריט", "-x ערך"):
            doc = rst_parser.parse_document(f"{line}\n{'=' * 12}\n\nגוף\n")
            assert [s.title for s in doc.sections] == [line], line
            below = rst_parser.parse_document(f"{line}\nכותרת\n{'=' * 12}\n\nגוף\n")
            assert below.sections == [], line

    def test_a_simple_table_ends_at_its_closing_border_not_at_the_blank_line(self):
        """היקף טבלה פשוטה נקרא עד הגבול הסוגר, ורק אחריו אפשר כותרת.

        נמדד: ``== ==`` ואחריו ``====``, כותרת ו-``====`` מחזיר **כן**
        כותרת — ה-``====`` סוגר את הטבלה. ובקרה: ``== ==`` ואחריו כותרת
        וקו, בלי גבול סוגר, מחזיר אפס.
        """
        with_border = rst_parser.parse_document(
            "== ==\n====\nכותרת\n====\n\nגוף\n")
        assert [s.title for s in with_border.sections] == ["כותרת"]
        without = rst_parser.parse_document("== ==\nכותרת\n=========\n\nגוף\n")
        assert without.sections == []

    def test_an_indented_title_between_two_overlines_is_a_title(self):
        """``Line.indent = text`` — שורה מוזחת מנותבת למסלול הכותרת.

        נמדד: כותרת מוזחת בין שני overline זהים היא סקשן, ו-docutils
        מחזיר אותה אחרי ``lstrip``. וגם שורת פיסוק **מוזחת** במקום הזה היא
        סקשן, כי ההזחה מונעת ממעבר ה-``underline`` לתפוס אותה. שורה ריקה
        אינה.
        """
        doc = rst_parser.parse_document("======\n   כותרת\n======\n\nגוף\n")
        assert [(s.title, s.over) for s in doc.sections] == [("כותרת", True)]
        dashes = rst_parser.parse_document("======\n   -----\n======\n\nגוף\n")
        assert [s.title for s in dashes.sections] == ["-----"]
        blank = rst_parser.parse_document("======\n\n======\n\nגוף\n")
        assert blank.sections == []

    def test_the_independent_recognizer_can_actually_fail(self):
        """מזהה שלא מסוגל להפיל מימוש שגוי אינו ראיה.

        נותן לו קלט שבו הכלל חוסם — כותרת רחבה עם קו בן 3 — ודורש שהוא
        יחזיר אפס. מזהה שמתעלם מכלל האורך יחזיר כאן כותרת.
        """
        assert _independent_headings("כותרת ארוכה\n===\n\nגוף\n".split("\n")) == []
        assert len(_independent_headings("כותרת ארוכה\n====\n\nגוף\n".split("\n"))) == 1


# ---- מחלקת הקלט שהקורפוס אינו מכיל: סיומות שורה ו-whitespace לא מנורמל ----
#
# .. warning::
#
#    **הלקח שהמחלקה הזאת לימדה, והוא שווה יותר מהטסטים שמתחתיו.** כל 208
#    קובצי ה-RST בריפו הם LF, וכל האימות של הפארסר נשען עליהם — מזהה
#    בלתי-תלוי, דיף אפס, והסכמה מלאה עם docutils על כל קובץ. ובדיוק
#    האחידות הזאת היא מה שהסתיר לולאה אינסופית: קורפוס אחיד אינו יכול
#    לגלות מחלקת קלט שאין לה בו אף מופע.
#
#    **אימות מול קורפוס אמיתי אינו תחליף לאימות מול מחלקות קלט.** הטסטים
#    שלמטה נגזרים מהמחלקה — סיומת שורה, תו whitespace שאין לו נרמול —
#    ולא מקובץ שקיים.

_HANGING_INPUTS = (
    # CRLF, הצורה הנפוצה: קובץ שנוצר ב-Windows עם שורה ריקה אחת
    "Doc\r\n===\r\n\r\nגוף\r\n",
    "\r\n",
    "x\n\r\n",
    # ותווי whitespace שאין להם נרמול, בקובץ LF תקין לגמרי.
    # **כולם נכתבים ב-escape ולא כתו עצמו**, וזה אותו כלל
    # ש-``BY-STACK/hebrew-source.md`` H1 קובע לתווים בלתי-נראים
    # במקור: תו שנכתב ישירות אינו נראה לעורך הבא, ואם עריכה או
    # העברה דרך ערוץ שמנרמל רווחים תחליף אותו ברווח רגיל —
    # ההערה שלידו תשקר והטסט ימשיך לעבור. נמדד: החלפת שני
    # התווים האלה ברווח משאירה את הטסט ירוק בדיוק אותו דבר.
    "x\n\x0b\n",      # vertical tab
    "x\n\x0c\n",      # form feed
    "x\n\x1c\n",      # file separator
    "x\n\x85\n",      # next line
    "x\n\xa0\n",      # no-break space
    "x\n\u2028\n",   # line separator
    "x\n\u3000\n",   # ideographic space
    # ושתיים שמגיעות דרך מסלול אחר: overline קצר נצרך קודם, והשורה
    # הפוגעת נפגשת בסיבוב הבא
    "=\n\r\nגוף\n",
    "=\n\xa0\nגוף\n",
)


def test_a_line_that_is_blank_only_after_strip_does_not_hang_the_parser(tmp_path):
    """שורה שאינה ריקה אך ריקה תחת ``strip`` תקעה את הפארסר **לנצח**.

    ``_is_title_text`` בדק ``not line`` ואישר שורה שכולה ``\\r``, בזמן
    שהלולאה שבולעת את הפסקה עוצרת על ``lines[i].strip()`` — אפס איטרציות,
    ו-``continue`` חוזר לאותה שורה. שתי הגדרות שונות של "שורה ריקה"
    באותה פונקציה.

    **הטסט רץ בתת-תהליך, וזה מכוון ולא קוסמטי.** קריאה ישירה לקוד תקוע
    הייתה תולה את הסוויטה עד שתקרת ה-60 שניות תהרוג אותה, ואז ההודעה
    אומרת "timeout" ולא "הקלט הזה אינו חוזר". תת-תהליך עם ``timeout``
    הופך את התקיעה לכשל **בשם**, והוא גם אינו מתנגש ב-SIGALRM
    ש-pytest-timeout משתמש בו (ראו ההערה ב-``pytest.ini``).

    הורץ על הקוד שלפני התיקון: כל שנים-עשר הקלטים נתקעו ויצאו ב-124.
    """
    import subprocess
    import sys

    root = str(Path(__file__).resolve().parents[1])
    program = (
        "import sys, json\n"
        f"sys.path.insert(0, {root!r})\n"
        "from services import rst_parser\n"
        "for text in json.loads(sys.argv[1]):\n"
        "    rst_parser.parse_document(text)\n"
        "print('all returned')\n"
    )

    # **והתקרה הפנימית נמוכה מהגלובלית בכוונה.** ``pytest.ini`` מציב
    # ``timeout = 60``, ובתקרה פנימית שווה לה נמדד שהתקרה הגלובלית מקדימה:
    # הכשל יוצא ``Failed: Timeout (>60s) from pytest-timeout`` ב-
    # ``selectors.py``, בלי לנקוב בקלט ובלי לנקוב בפארסר. עם תקרה נמוכה
    # יותר יוצא ``subprocess.TimeoutExpired`` שנושא את שורת הפקודה, ובה
    # הקלט התוקע עצמו — וזו כל הסיבה שהטסט הזה רץ בתת-תהליך.
    #
    # ושימו לב שהאסרשן שמתחת **אינו** מה שרץ בתקיעה אמיתית:
    # ``subprocess.run`` זורק ואינו חוזר. הוא מה שרץ כשהתת-תהליך חזר עם
    # קוד יציאה שאינו אפס.
    #
    # ``-B`` ו-``cwd=tmp_path``, ושניהם נמדדו ולא נבחרו לנוחות: בלי
    # ``-B`` התת-תהליך כותב ``__pycache__`` לתוך ``services/`` — כלומר
    # לתוך עץ המקור, שכלל הבטיחות בפרויקט אוסר לכתוב בו מטסט — ועם הדגל
    # לא נוצר דבר. ו-``cwd`` בתיקייה ייחודית לכל ריצה מבודד ריצות מקבילות
    # זו מזו. ה-``sys.path.insert`` בתוכנית הוא נתיב מוחלט, ולכן הייבוא
    # אינו תלוי ב-cwd בכלל.
    done = subprocess.run(
        [sys.executable, "-B", "-c", program, json.dumps(list(_HANGING_INPUTS))],
        capture_output=True,
        text=True,
        timeout=45,
        cwd=str(tmp_path),
    )
    assert done.returncode == 0, (
        f"הפארסר לא חזר על אחד מהקלטים. stderr={done.stderr[-400:]!r}"
    )
    assert "all returned" in done.stdout


def test_a_whitespace_only_line_does_not_become_a_section_with_an_empty_name():
    """ולא רק שהפארסר חוזר — הוא גם אינו ממציא סימבול בשם ריק.

    לפני התיקון, שורת form feed מעל קו פיסוק ייצרה סקשן שהכותרת שלו היא
    המחרוזת הריקה, ומשם שם מנוקד שנגמר בנקודה ואינו מציין דבר בקובץ.
    הטענה הזאת יושבת כאן ולא בטסט התקיעה כדי שתיקון שרק "מחזיר תשובה"
    לא ייראה כמו תיקון מלא.
    """
    for whitespace in ("\x0c", "\x0b", "\xa0"):
        doc = rst_parser.parse_document(
            f"אמיתי\n=====\n\nגוף\n\n{whitespace}\n-----\n\nעוד\n"
        )
        titles = [s.title for s in doc.sections]
        assert titles == ["אמיתי"], f"{whitespace!r} ייצר {titles!r}"
        assert all(s.title.strip() for s in doc.sections)


def test_crlf_normalisation_keeps_the_mcp_line_unit():
    """הנרמול מותר **רק** משום שהוא אינו משנה כמה שורות יש.

    כל שדות ה-``lines`` בתשובות ה-MCP נספרים ב-``count_lines``, שמפצל
    ב-``split("\\n")``. ``\\r\\n`` ← ``\\n`` שומר על המספר; ``splitlines()``
    לא, והוא גם מפצל על עשרה תווים במקום אחד — ולכן הוא נדחה, וזה מקובע
    כאן ולא רק בהערה.

    המוטציה שמפילה: להחליף את הנרמול ב-``splitlines()``. אז קובץ שנגמר
    ב-newline נותן מספר קטן ב-1 והטענה נופלת.
    """
    from mcp_server.handlers import count_lines

    for text in (
        "A\r\n=\r\n\r\nגוף\r\n",
        "A\r\n=\r\n\r\nגוף",
        "A\n=\n\nגוף\n",
        "A\n=\r\n\r\nגוף\n",
    ):
        assert len(rst_parser.parse_document(text).lines) == count_lines(text), (
            f"מספר השורות נפרד מיחידת השורה של ה-MCP על {text!r}"
        )


def test_a_heading_after_an_indented_line_is_not_swallowed_by_the_paragraph():
    """``Text.text`` קורא את הפסקה ב-``get_text_block(flush_left=True)``.

    כלומר הבלוק נגמר גם בשורה מוזחת, לא רק בשורה ריקה. הלולאה שבלעה עד
    השורה הריקה החביאה כותרת שכתובה בקובץ, והטווח שמעליה בלע אותה —
    כלומר ``lines=[start, end]`` שיבוא אחרי המפה מחזיר את הקטע הלא נכון
    בלי שום סימן שמשהו אבד.

    נמדד מול docutils 0.23 שהורץ, ומול הגרסה שלפני השינוי: שתיהן
    מחזירות את הכותרת, והגרסה שאחריו לא. כלומר זו הייתה רגרסיה.
    """
    doc = rst_parser.parse_document(
        "פסקה\n  שורה מוזחת\nכותרת\n=====\n\nגוף\n"
    )
    assert [s.title for s in doc.sections] == ["כותרת"]

    # ובקרה: עם שורה ריקה לפני הכותרת התוצאה זהה, וזה מה שמצמיד את
    # הסיבה להזחה ולא למשהו אחר.
    with_blank = rst_parser.parse_document(
        "פסקה\n  שורה מוזחת\n\nכותרת\n=====\n\nגוף\n"
    )
    assert [s.title for s in with_blank.sections] == ["כותרת"]


def test_a_heading_after_an_indented_line_survives_the_short_overline_path_too():
    """אותו כלל, האתר השני — ובלעדיו כותרת שכתובה בקובץ נעלמה מהמפה.

    ``short_overline`` מחזיר את השורה ל-``Body`` דרך מעבר ה-``text``, ולכן
    הבלוק שנבלע במסלול הזה הוא בלוק של ``Text.text`` בדיוק כמו במסלול
    ה-underline-only — ונגמר גם בשורה מוזחת. הכלל היה כתוב בשני מקומות,
    אחד מהם קיבל את העצירה והשני לא, וזה השני. **הוא מאוחד עכשיו
    ב-``_skip_paragraph_block``**, כלומר אין יותר שני נוסחים שיכולים
    להיסחף.

    נמדד מול docutils 0.23 שהורץ: הוא מחזיר את הכותרת, והמימוש לפני
    התיקון החזיר אפס סקשנים. **ומול** ``origin/main`` **שמחזיר אותה גם
    הוא** — כלומר בלי התיקון זו רגרסיה ולא פער חדש. על מדגם של 37,376
    צורות, 280 חלקו על docutils וכולן חזרו להסכמה.

    המוטציה שמפילה: להחזיר את הלולאה ``while ... lines[i].strip()`` במקום
    הקריאה ל-``_skip_paragraph_block``.
    """
    doc = rst_parser.parse_document("--\n  מוזח\nכותרת\n======\n\nגוף\n")
    assert [s.title for s in doc.sections] == ["כותרת"]

    # ובקרה: שורה ריקה לפני הכותרת נותנת אותה תוצאה, וזה מצמיד את הסיבה
    # להזחה ולא לקו הקצר שמעליה.
    with_blank = rst_parser.parse_document("--\n  מוזח\n\nכותרת\n======\n\nגוף\n")
    assert [s.title for s in with_blank.sections] == ["כותרת"]


def test_the_doctest_block_still_ends_at_the_blank_line_only():
    """הבקרה שמונעת "איחוד" שגוי של שלוש הלולאות לאחת.

    ``Body.doctest`` קורא ``get_text_block()`` **בלי** ``flush_left``, ולכן
    בלוק doctest נגמר בשורה ריקה בלבד, ושורה מוזחת בתוכו אינה מסיימת אותו
    — כלומר הכותרת שאחריה **כן** נבלעת, וזו ההתנהגות הנכונה. אומת במקור
    של docutils 0.23 ובהרצה שלו: שלוש הצורות כאן מוחזרות זהות.

    מי שיעביר גם את הלולאה הזאת ל-``_skip_paragraph_block`` יחזיר את
    הכותרת ש-Sphinx אינו בונה, והטסט הזה הוא מה שיתפוס אותו.
    """
    swallowed = rst_parser.parse_document(">>> foo()\n  מוזח\nכותרת\n======\n\nגוף\n")
    assert [s.title for s in swallowed.sections] == []

    # ובקרה: שורה ריקה כן מסיימת את הבלוק, ואז הכותרת חוזרת — כלומר
    # הטסט מודד את ההזחה ולא את ה-doctest כשלעצמו.
    after_blank = rst_parser.parse_document(">>> foo()\n\nכותרת\n======\n\nגוף\n")
    assert [s.title for s in after_blank.sections] == ["כותרת"]


def test_a_heading_whose_text_ends_with_a_double_colon_is_still_a_heading():
    """``underline`` נבדק לפני ``text``, ולכן ה-``::`` אינו מתפקד כסמן.

    במצב ``Text`` שבמקור סדר המעברים הוא blank ← indent ← underline ←
    text. כלומר כשהשורה שאחרי הטקסט היא קו פיסוק, זה **סעיף** — וסיומת
    ה-``::`` שבטקסט אינה מגיעה לשמש סמן ל-literal block.

    לפני התיקון הענף של ה-``::`` רץ קודם, והכותרת נעלמה מהמפה **כולה**:
    ``codekeeper_docs_get_section`` ענה "סעיף לא נמצא" על סעיף שכתוב
    בקובץ, והטווח של הסעיף שמעליו בלע אותו. נמדד מול docutils 0.23
    שהורץ: הוא בונה שני סעיפים.

    המוטציה שמפילה: להחזיר את ענף ה-``::`` לפני בדיקת הכותרות.
    """
    doc = rst_parser.parse_document("Doc\n===\n\nConfiguration::\n---------------\n\nגוף\n")

    assert [(s.title, s.level) for s in doc.sections] == [("Doc", 1), ("Configuration::", 2)]


def test_a_paragraph_that_opens_a_literal_block_is_consumed_as_a_paragraph():
    """ה-literal block נכנס **אחרי** שהפסקה נצרכה, לא במקומה.

    ב-docutils ``Text.blank`` ו-``Text.text`` קוראים את הפסקה ואז, אם היא
    נגמרת ב-``::``, מפרסרים את ה-literal block. הענף שהיה כאן קידם שורה
    **אחת** בלבד, ולכן שורות שהיו בתוך אותה פסקה נבחנו שוב ככותרות —
    והמפה **המציאה** סעיף שאינו קיים.

    נמדד: ``"Run this::"`` ואחריה שורת טקסט וקו פיסוק החזירה גם את שורת
    הטקסט כסעיף (שורות 5-9), בזמן ש-docutils מחזיר רק את הכותרת
    הראשונה. ובלוק literal מוזח ממשיך לעבוד בלי הענף, כי שומר ההזחה
    בראש הלולאה מדלג עליו.

    המוטציה שמפילה: להחזיר את הענף.
    """
    invented = rst_parser.parse_document(
        "Intro\n=====\n\nRun this::\nand see the output\n------------------\n\nגוף\n"
    )
    assert [s.title for s in invented.sections] == ["Intro"]

    # והצורה שהייתה רגרסיה מול ``origin/main``: שם ובלעדיו התוצאה ריקה,
    # ובאמצע היא החזירה כותרת.
    regressed = rst_parser.parse_document("text::\nLong title\n=====\n  מוזח\n\n- פריט\n")
    assert regressed.sections == []

    # ובקרה שהדילוג על בלוק מוזח לא אבד: כותרת שאחרי בלוק literal מוזח
    # חוזרת, והשורות שבתוכו אינן הופכות לסעיפים.
    with_block = rst_parser.parse_document(
        "Intro\n=====\n\nכך מריצים::\n\n   Heading\n   =======\n\nכותרת\n------\n\nגוף\n"
    )
    assert [s.title for s in with_block.sections] == ["Intro", "כותרת"]


def test_the_independent_recognizer_consumes_a_malformed_overline_construct():
    """overline פגום נצרך כקונסטרוקט, ואינו נופל חזרה לזיהוי underline-only.

    **הסחיפה השלישית של האורקל, ובאותה מחלקה כמו שתי הראשונות.** במצב
    ``Line`` שבמקור, כל מוצא מתפצל על אורך ה-overline: ארבעה ומעלה ←
    שגיאה וחזרה ל-``Body``, כלומר השורות נצרכות; קצר מ-4 ←
    ``short_overline`` ו-``state_correction``, כלומר השורה חוזרת למעבר
    ה-``text`` ונעשית הכותרת בפוטנציה בעצמה.

    לפני התיקון האורקל קרא ``=====`` / כותרת / ``-----`` פעמיים — פעם
    כ-overline שנכשל, ואז את שתי השורות שמתחת כסעיף — והמציא כותרת
    ש-docutils והמימוש שניהם דוחים. ועל overline קצר הוא דילג שורה אחת,
    והכותרת הבאה נוצרה מהשורה הלא נכונה.

    נמדד אחרי התיקון: על מדגם של 37,376 צורות האורקל מסכים עם docutils
    ב**כולן**, מול 7,936 אי-הסכמות לפני.

    המוטציות שמפילות: להסיר את בלוק הצריכה של ``len(top) >= 4``, או
    להחזיר את ``_is_punctuation_line(top)`` לשומר הדילוג.
    """
    # ארבעה ומעלה: ה-underline שונה, ולכן שלוש השורות נצרכות ואין סעיף
    assert _independent_headings("=====\nTitle\n-----\n\nbody\n".split("\n")) == []
    # ובקרה: overline זהה ל-underline הוא כן סעיף
    matched = _independent_headings("=====\nTitle\n=====\n\nbody\n".split("\n"))
    assert [row[0] for row in matched] == ["Title"]

    # קצר מ-4: השורה עצמה הכותרת בפוטנציה, והשורה שאחריה מכריעה
    assert _independent_headings("=\nT\n-\n\nbody\n".split("\n")) == []
    demoted = _independent_headings("=\n-\nbody\n".split("\n"))
    assert [row[0] for row in demoted] == ["="]

    # **ושני הקלטים שמפילים את המוטציה הראשונה.** בלי בלוק הצריכה, שתי
    # שורות פיסוק ברצף נופלות למסלול הפסקה והשנייה הופכת לכותרת בשם
    # ``====``. במקור זה ``Line.underline``, שצורך שתיים ואינו יוצר סעיף.
    # נמדד: בלי הבלוק 1,848 צורות מתוך 37,376 סוטות מ-docutils, ואיתו אפס.
    assert _independent_headings("====\n====\n--\n".split("\n")) == []
    assert _independent_headings("  indented\n====\n====\n".split("\n")) == []


def test_the_independent_recognizer_holds_the_two_rules_the_parser_fixed():
    """אורקל שאינו מחזיק את הכלל אינו עוגן — הוא מאשר רגרסיה.

    שני הכללים האלה תוקנו במימוש והאורקל נשאר מאחור, **וכל אחד בכיוון
    הפוך**: בכלל הרוחב הוא המציא כותרת ש-docutils דוחה, ובבלוק הפסקה הוא
    איבד כותרת ש-docutils מחזיר. הטסט על הקורפוס לא תפס את זה, כי אף אחד
    מ-208 הקבצים אינו נושא את שתי הצורות — אותה מחלקת קלט חסרה שה-
    ``.. warning::`` שלמעלה מתעד.

    **שני הכללים נגזרו כאן מהמקור של docutils** (``Line.text`` שעושה
    ``rstrip`` לפני מדידת הרוחב, ו-``Text.text`` שקורא
    ``get_text_block(flush_left=True)``) ולא מהמימוש — אורקל שמעתיק מהקוד
    שמולו הוא מושווה מעמיד את שני הצדדים על מקור אחד.

    המוטציות שמפילות: ``middle.strip()`` במקום ``middle.rstrip()``, והסרת
    העצירה על ההזחה מלולאת הפסקה.
    """
    # כלל הרוחב: הטקסט לבדו הוא עמודה אחת ונכנס בקו בן תו אחד; עם ההזחה
    # הוא שתיים, והקו קצר מ-4 — ולכן אין כותרת.
    assert _independent_headings("=\n T\n=\n\nזנב\n".split("\n")) == []
    assert [row[0] for row in _independent_headings("=\nT\n=\n\nזנב\n".split("\n"))] == ["T"]

    # בלוק הפסקה: נגמר גם בשורה מוזחת, ולכן הכותרת שאחריה נשארת.
    after_indent = _independent_headings("פסקה\n  מוזח\nכותרת\n=====\n\nגוף\n".split("\n"))
    assert [row[0] for row in after_indent] == ["כותרת"]


def test_the_overline_length_rule_counts_the_indentation_of_the_title():
    """``Line.text`` עושה ל-``title`` רק ``rstrip`` לפני מדידת הרוחב.

    ה-``lstrip`` קורה אחר כך, ורק לטקסט שנשמר. כלומר **ההזחה נספרת
    ברוחב**, ושורה מוזחת בין שני overline קצרים מ-4 אינה כותרת אף
    שהטקסט לבדו היה נכנס. נמדד: על מדגם של 384 צורות בממד ההזחה, הצורה
    שעשתה ``strip`` חלקה על docutils ב-30 מהן וכולן בכיוון של **המצאת**
    כותרת.

    המוטציה שמפילה: להחזיר ``strip()`` במקום ``rstrip()``.
    """
    # רוחב הטקסט לבדו הוא 1 ונכנס ב-overline באורך 1; עם ההזחה הוא 2
    # ואינו נכנס, וה-overline קצר מ-4 — ולכן אין כותרת.
    assert rst_parser.parse_document("=\n T\n=\n\nזנב\n").sections == []

    # ובקרה בשני הכיוונים: בלי הזחה זו כותרת, ועם overline באורך 4 ומעלה
    # ההזחה רק מייצרת אזהרה ב-docutils והכותרת נשארת.
    assert [s.title for s in rst_parser.parse_document("=\nT\n=\n\nזנב\n").sections] == ["T"]
    wide = rst_parser.parse_document("====\n  T\n====\n\nזנב\n")
    assert [s.title for s in wide.sections] == ["T"]


# ---- שני כללים שה-docstring מנמק באריכות, ושאף טסט לא קיבע ----
#
# נמדד במצבת מוטציות: שתי המוטציות שלמטה השאירו את כל הסוויטה ירוקה,
# בזמן ששלוש מוטציות בקרה כן נתפסו. כלל שמנומק בפרוזה ואינו מקובע הוא
# תיעוד של כוונה, לא של התנהגות — והתיקון הבא ימחק אותו בלי שאיש יראה.


def test_the_length_rule_subtracts_combining_characters():
    """כותרת מנוקדת: שלושה תווים, אבל **שתי** עמודות תצוגה.

    ``column_width`` מחסר תווים משולבים, ולכן ניקוד עברי תופס אפס. הקלט
    כאן נבחר כך שכלל ה-``>= 4`` **לא יכול להציל** אותו: ה-adornment הוא
    שני תווים, ולכן אם הרוחב נמדד בלי החיסור הכותרת נופלת לגמרי.

    זה מה שהפריד את הטסט הזה משני הטסטים שכבר היו על רוחב התצוגה: הם
    עברו גם בלי החיסור, כי אצלם ה-adornment ארוך דיו וכלל ה-4 החזיר את
    הכותרת מסיבה אחרת.

    המוטציה שמפילה: ``return width`` במקום
    ``return width - sum(1 for c in text if unicodedata.combining(c))``.
    נמדד: בלי החיסור הקלט הזה מחזיר אפס סקשנים.
    """
    doc = rst_parser.parse_document("אָב\n==\n\nגוף\n")
    assert [s.title for s in doc.sections] == ["אָב"]

    # ובקרה שהכלל עצמו לא בוטל: אותה כותרת בלי ניקוד היא שני תווים
    # ושתי עמודות, ועם קו בן תו אחד היא **אינה** כותרת.
    assert rst_parser.parse_document("אב\n=\n\nגוף\n").sections == []


def test_a_style_rejected_by_the_skip_guard_is_not_registered():
    """``title_styles.append`` יושב **אחרי** ה-``return False`` של השומר.

    כלומר סגנון שהסקשן שלו נדחה על "דילוג רמה" אינו נכנס לרשימה, ולכן
    התו החדש **הבא** מקבל את הרמה שהייתה מתקבלת לולא הדחייה. אומת מול
    קוד המקור של docutils 0.23 (``check_subsection``, שני ה-return בסדר
    הזה) ומול הרצה שלו.

    הרצף כאן הוא היחיד שמבחין, וזה למה הוא נראה מסובך: צריך סגנון שנדחה
    **ועוד** תו חדש אחריו, אחרת שתי הצורות נותנות את אותה רמה ואין מה
    למדוד. ``~`` נדחה אחרי החזרה לרמה 1, ואז ``^`` חייב לקבל רמה 3.

    המוטציה שמפילה: להוציא את ``order.append`` מחוץ לשומר. נמדד: אז
    ``^`` מקבל רמה 4, השומר דוחה אותו, והכותרת ``F`` נעלמת מהמפה.
    """
    doc = rst_parser.parse_document(
        "A\n=\n\nB\n-\n\nC\n=\n\nD\n~\n\nE\n-\n\nF\n^\n\nגוף\n"
    )
    assert [(s.title, s.level) for s in doc.sections] == [
        ("A", 1), ("B", 2), ("C", 1), ("E", 2), ("F", 3)
    ]


# ---- היקף הטבלה הפשוטה, מול ``isolate_simple_table`` ----
#
# שלושת התנאים של הגבול הסוגר נבדקים כאן אחד-אחד, כי עצירה על הגבול
# הראשון מטפלת נכון רק בצורה אחת מהשלוש — ודווקא היא הצורה שבקורפוס.

_TABLE = "====  ===="


def test_a_header_separator_is_not_the_closing_border_of_a_simple_table():
    """הגבול הראשון בטבלה עם מפריד כותרת הוא המפריד, לא הסוגר.

    עצירה עליו השאירה את גוף הטבלה כשורת פסקה, והפסקה בלעה את הכותרת
    שבאה מיד אחרי הגבול הסוגר — כלומר כותרת שכתובה בקובץ נעלמה מהמפה,
    והסעיף שמעליה בלע אותה. ``isolate_simple_table`` סוגר על הגבול
    ה**שני**, וזה מה שמוכיח הקלט הזה.

    שורת ההפרדה בין הצורות היא **היעדר שורה ריקה** לפני הכותרת: עם שורה
    ריקה, הפסקה נגמרת בה והכותרת חוזרת גם בקוד הישן.
    """
    doc = rst_parser.parse_document(
        f"ראש\n====\n\n{_TABLE}\nc1    c2\n{_TABLE}\na     b\n{_TABLE}\n"
        "כותרת\n------\n\nגוף\n"
    )
    assert [(s.title, s.level) for s in doc.sections] == [("ראש", 1), ("כותרת", 2)]


def test_a_blank_row_inside_a_simple_table_does_not_end_it():
    """``isolate_simple_table`` מחפש גבולות ואינו עוצר על שורה ריקה.

    טבלה פשוטה יכולה להכיל שורה ריקה בין שורות גוף, ולכן סריקה שעוצרת
    על שורה ריקה מסיימת את הטבלה מוקדם מדי — ואז הגבול הסוגר והכותרת
    שאחריו נבלעים כפסקה.
    """
    doc = rst_parser.parse_document(
        f"ראש\n====\n\n{_TABLE}\na     b\n\nc     d\n{_TABLE}\n"
        "כותרת\n------\n\nגוף\n"
    )
    assert [(s.title, s.level) for s in doc.sections] == [("ראש", 1), ("כותרת", 2)]


def test_a_simple_table_with_no_closing_border_swallows_the_rest():
    """הבקרה בכיוון ההפוך, וזו הצורה שהקוד הישן **המציא** בה כותרת.

    כשאין גבול סוגר בכלל, ``isolate_simple_table`` מדווח טבלה פגומה
    ובולע את שאר הקלט — נמדד ב-docutils, שאינו מחזיר את הכותרת. סריקה
    שעוצרת על השורה הריקה מחזירה אותה, וזו כותרת שאינה קיימת מבחינת
    Sphinx.
    """
    doc = rst_parser.parse_document(
        f"ראש\n====\n\n{_TABLE}\na     b\n\nכותרת\n------\n\nגוף\n"
    )
    assert [(s.title, s.level) for s in doc.sections] == [("ראש", 1)]
