"""טסטים לפארסר ה-RST — על קבצי RST אמיתיים מהריפו + מקרי קצה סינתטיים ממוקדים."""

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
    שלמעלה, ומכבד את העובדה ש**פסקה שנפתחה בולעת את הבלוק עד השורה
    הריקה**. העובדה שהוא מסכים עם המימוש על כל קובץ בריפו היא מה שהופך
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
        if _is_punctuation_line(top) and i + 2 < n:
            middle, bottom = lines[i + 1], lines[i + 2].rstrip()
            middle_ok = bool(middle.strip()) and (
                middle[:1] in (" ", "\t") or not _is_punctuation_line(middle.rstrip()))
            if (middle_ok and bottom == top
                    and _adornment_is_long_enough(middle.strip(), bottom)):
                found.append((middle.strip(), (top[0], top[0]), i + 1))
                i += 3
                continue

        # שורות מבניות — אינן יכולות להיות הכותרת
        if _DOCTEST.match(top):
            while i < n and lines[i].strip():
                i += 1
            continue
        if _TABLE_TOP.match(top):
            i += 1
            while i < n and lines[i].strip() and not _TABLE_BORDER.match(lines[i].rstrip()):
                i += 1
            if i < n and lines[i].strip():
                i += 1
            continue
        if _STRUCTURAL.match(top) or _is_punctuation_line(top):
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
        while i < n and lines[i].strip():
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
