"""טסטים ל-``services/md_parser.py`` — שש ההכרעות שהתוכנית קבעה.

**למה קריאה ישירה לפונקציה ולא דרך ממשק ה-MCP.** הכלל בפרויקט הוא
שטסט עובר דרך אותו ממשק כמו הצרכן. כאן אין צרכן: הפארסר נוסף ואינו
מחווט לאף כלי — ``docs_handlers`` ממשיך לקרוא ל-``rst_parser`` בלבד —
והחיווט הוא PR נפרד. לפונקציה טהורה בלי צרכן חיצוני, הקריאה הישירה
**היא** הממשק. כשיהיה צרכן, הטסטים שלו יעברו דרך ממשק ה-MCP.

**וכל טענה כאן נמדדה בהרצה**, ולא נגזרה מקריאת הקוד של
``markdown-it-py``. ההפניות למקור הן לפי שם מודול ופונקציה ולא לפי
מספר שורה.
"""

import re
from pathlib import Path

import pytest
from markdown_it import MarkdownIt

from services import doc_sections, md_parser

_REPO = Path(__file__).resolve().parents[1]


# ════════════════════════════════════════════════════════════════════
# הכרעה 1 — רק ``token.level == 0`` נכנס למפה
# ════════════════════════════════════════════════════════════════════

_CONTAINERS = """## אמיתית א

טקסט

> ## בתוך ציטוט

- ## בתוך פריט רשימה

## אמיתית ב

סוף
"""


def test_a_heading_inside_a_container_is_not_a_section():
    """כותרת בתוך ציטוט או פריט רשימה מזוהה ככותרת ואינה סעיף במפה.

    נמדד ב-``markdown-it-py``: ברמת המסמך ``token.level`` הוא ``0``,
    בתוך ציטוט ``1``, ובתוך פריט רשימה ``2``.
    """
    doc = md_parser.parse_document(_CONTAINERS)
    assert [s.title for s in doc.sections] == ["אמיתית א", "אמיתית ב"]


def test_the_container_does_not_cut_the_range_of_the_section_around_it():
    """זו הטענה שהמוטציה מפילה, ולא רק הספירה.

    הסעיף "אמיתית א" חייב להימשך עד הכותרת הבאה **ברמת המסמך**. אילו
    הכותרות שבתוך המכלים היו נכנסות למפה, ``_finalize`` היה מסיים אותו
    בשורה שלפני הציטוט — כלומר סעיף שנקטע באמצע.
    """
    doc = md_parser.parse_document(_CONTAINERS)
    first, second = doc.sections
    assert first.end_line == second.heading_line - 1
    body = doc_sections.section_text(doc, first, True)
    assert "בתוך ציטוט" in body, "גוף הסעיף חייב להכיל את הציטוט שיושב בתוכו"


# ════════════════════════════════════════════════════════════════════
# הכרעה 2 — ``\r`` בודד נדחה, CRLF לא
# ════════════════════════════════════════════════════════════════════

_LF = "# A\n\n## B\n\n### C\n"


def test_a_lone_cr_is_refused():
    with pytest.raises(doc_sections.InconsistentLineEndings):
        md_parser.parse_document("# A\r\r## B\r\r### C\r")


def test_the_same_file_in_crlf_returns_the_same_line_numbers():
    """CRLF אינו מושפע — זה המקרה הנפוץ, והוא חייב להמשיך לעבוד."""
    lf = md_parser.parse_document(_LF)
    crlf = md_parser.parse_document(_LF.replace("\n", "\r\n"))
    assert [(s.level, s.heading_line, s.end_line, s.title) for s in lf.sections] == [
        (s.level, s.heading_line, s.end_line, s.title) for s in crlf.sections
    ]
    assert lf.lines == crlf.lines


def test_counting_lines_is_not_enough_to_catch_the_lone_cr():
    """**המקרה החד, וזו הסיבה שהבדיקה היא על נוכחות ולא על ספירה.**

    בקלט הזה ``split("\\n")`` ו-``splitlines()`` נותנים **אותו מספר
    בדיוק** — שש שורות — ובכל זאת ``markdown-it-py`` מדווח על הכותרת
    האחרונה בשורה 6, בזמן שב-``split("\\n")`` היא בשורה 5. שומר שהיה
    משווה ספירות היה עובר את הקלט הזה ומחזיר מפה שמצביעה לשורה הלא
    נכונה, עם ``ok: true``.
    """
    sneaky = "# A\n\n## B\rX\n\n### C\n"
    assert len(sneaky.split("\n")) == len(sneaky.splitlines()) == 6, "הנחת המקרה"

    plain = MarkdownIt("commonmark").disable("inline")
    tokens = plain.parse(sneaky, {})
    by_markdown_it = [t.map[0] + 1 for t in tokens if t.type == "heading_open"]
    by_split = [i + 1 for i, ln in enumerate(sneaky.split("\n")) if ln.startswith("#")]
    assert by_markdown_it[-1] == 6 and by_split[-1] == 5, "שתי הספירות נפרדות כאן"

    with pytest.raises(doc_sections.InconsistentLineEndings):
        md_parser.parse_document(sneaky)


# ════════════════════════════════════════════════════════════════════
# הכרעה 3 — front matter אינו מזיז שורות ואינו מייצר סעיף מומצא
# ════════════════════════════════════════════════════════════════════

_FRONT_MATTER = """---
summary: מסמך לדוגמה
tags: [a, b]
---

# כותרת אמיתית

## סעיף
"""


def test_front_matter_does_not_become_a_section():
    """בלי הטיפול, שתי שורות ה-YAML היו כותרת setext ברמה 2 בשורה 2.

    נמדד: פארסר בלי התוסף מחזיר על הקלט הזה
    ``[('h2', 2, 'summary: …\\ntags: [a, b]'), ('h1', 6, …), ('h2', 8, …)]``.
    """
    doc = md_parser.parse_document(_FRONT_MATTER)
    assert [(s.level, s.heading_line, s.title) for s in doc.sections] == [
        (1, 6, "כותרת אמיתית"),
        (2, 8, "סעיף"),
    ]


def test_the_document_lines_are_the_source_and_not_the_parsed_text():
    """**הטענה המרכזית של ההכרעה הזאת.**

    ``Document.lines`` הן שורות המקור. קורא שיבקש סעיף שמכיל את הבלוק
    חייב לקבל את ה-YAML עצמו — לא שורות ריקות, ולא טקסט שעבר עיבוד.
    ומכיוון שמספרי השורות **זהים** בשני המצבים, טעות כאן אינה מסגירה
    את עצמה באף מספר.
    """
    doc = md_parser.parse_document(_FRONT_MATTER)
    assert doc.lines == _FRONT_MATTER.split("\n")
    assert doc.lines[1] == "summary: מסמך לדוגמה"

    # וקצה-לקצה: הטקסט שהקורא באמת מקבל
    whole = doc_sections.section_text(doc, doc.sections[0], True)
    assert whole.startswith("# כותרת אמיתית")


def test_an_unclosed_front_matter_block_is_a_no_op():
    """בלי סוגר אין front matter, וה-``---`` חוזר להיות קו רגיל."""
    doc = md_parser.parse_document("---\na: 1\n\n# כותרת\n")
    assert [(s.level, s.heading_line, s.title) for s in doc.sections] == [(1, 4, "כותרת")]


@pytest.mark.parametrize(
    "name, block",
    [
        ("בלי בלוק", ""),
        ("רגיל", "---\na: 1\n---\n"),
        ("סוגר ...", "---\na: 1\n...\n"),
        ("פותח מוזח", "  ---\na: 1\n---\n"),
        ("פותח רווח בסוף", "--- \na: 1\n---\n"),
        ("סוגר מוזח", "---\na: 1\n  ---\n"),
        ("סוגר רווח בסוף", "---\na: 1\n--- \n"),
        ("ארבעה מקפים", "----\na: 1\n----\n"),
        ("לא נסגר", "---\na: 1\n"),
        ("פותח עם טקסט", "---title\na: 1\n---\n"),
    ],
)
def test_front_matter_never_moves_a_line_number(name, block):
    """עשר צורות, וביניהן ארבע שנמדדו כחלוקות בין שני כללים שנכתבו ביד.

    הטענה היא לא "הבלוק זוהה" אלא **שהכותרות יושבות בשורות שבהן הן
    באמת יושבות בקובץ**. זה מה שמחזיק את ההבטחה שכל שורה שהמפה מחזירה
    אפשר לבקש עם ``lines=``, והוא נכון כאן בזכות זה שהטקסט אינו משתנה
    כלל — לא נמחק ולא הוחלף.
    """
    text = block + "# כותרת אמיתית\n\ntext\n\n## סעיף\n"
    lines = text.split("\n")
    doc = md_parser.parse_document(text)
    found = {s.title: s.heading_line for s in doc.sections}
    assert found["כותרת אמיתית"] == lines.index("# כותרת אמיתית") + 1
    assert found["סעיף"] == lines.index("## סעיף") + 1
    assert doc.lines == lines


# ════════════════════════════════════════════════════════════════════
# הכרעה 4 — התקרה נאכפת בתוך הפרסור
# ════════════════════════════════════════════════════════════════════

def _many_headings(count):
    return "".join(f"## h{i}\n\nbody {i}\n\n" for i in range(count))


def test_the_ceiling_stops_inside_the_parse_and_not_after_it():
    """הראיה היא **היכן** נעצרנו, ולא רק שהחריגה הורמה.

    ``TooManySections`` נושאת את מספר השורה שבה הכלל עצר. אם הבדיקה
    הייתה רצה אחרי ``md.parse``, כל העבודה כבר הייתה נעשית — והמספר
    היה סוף הקובץ או לא היה קיים כלל.
    """
    text = _many_headings(50)
    total_lines = len(text.split("\n"))
    assert total_lines == 201, "הנחת המקרה"
    with pytest.raises(doc_sections.TooManySections) as caught:
        md_parser.parse_document(text, max_sections=5)
    stopped_at = caught.value.args[0]

    # הכותרת השישית — זו שחוצה תקרה של חמש — יושבת בשורה 21, והכלל נורה
    # בתחילת הבלוק שאחריה. הסף כאן הדוק בכוונה: ``< total_lines`` לבדו
    # היה עובר גם על מימוש שמפרסר הכול ומסנן בסוף, וזה בדיוק מה שנמדד
    # בבדיקת מוטציה שקרה לניסוח הרופף הקודם.
    assert 0 < stopped_at < 40, (stopped_at, total_lines)


def test_the_second_gate_catches_a_section_that_the_in_parse_rule_never_sees():
    """**השער השני אינו קוד מת, וזה נמדד.**

    הכלל שבתוך הפרסור נקרא ב**תחילת** בלוק, ולכן הסעיף האחרון בקובץ —
    זה שאין אחריו בלוק נוסף — אינו נסרק על ידו לעולם. בקלט הזה שש
    הכותרות נגמרות בסוף הקובץ ממש, והסירוב מגיע מהשער שאחרי הפרסור.
    הארגומנט הוא סוף הקובץ, וזה מה שמבדיל בין שני השערים.
    """
    text = "".join(f"## h{i}\n\n" for i in range(6))
    total_lines = len(text.split("\n"))
    with pytest.raises(doc_sections.TooManySections) as caught:
        md_parser.parse_document(text, max_sections=5)
    assert caught.value.args[0] == total_lines


def test_a_file_with_exactly_the_ceiling_passes():
    """הגבול זהה ל-``Capped.append`` ול-``add_section``: הסעיף שמעליו עוצר."""
    doc = md_parser.parse_document(_many_headings(5), max_sections=5)
    assert len(doc.sections) == 5
    with pytest.raises(doc_sections.TooManySections):
        md_parser.parse_document(_many_headings(6), max_sections=5)


def test_the_default_ceiling_is_the_documented_constant():
    """טענת O(1) על הערך, במקום לבנות 50,001 סעיפים אמיתיים בכל ריצת CI."""
    import inspect

    assert md_parser.MAX_SECTIONS == 50_000
    default = inspect.signature(md_parser.parse_document).parameters["max_sections"].default
    assert default is md_parser.MAX_SECTIONS, "ברירת המחדל היא התקרה, לא None"


def test_the_ceiling_can_be_turned_off_explicitly():
    doc = md_parser.parse_document(_many_headings(20), max_sections=None)
    assert len(doc.sections) == 20


def test_the_counter_never_examines_a_token_twice():
    """המונה סורק רק טוקנים חדשים — אחרת הוא O(n²) והתקרה היא המחיר.

    טענה מדידה על המונה עצמו, ולא בדיקת זמן שמתנדנדת ב-CI.
    """
    counter = md_parser._SectionCounter(max_sections=10)
    tokens = []
    for step in range(20):
        tokens.extend([_FakeToken("paragraph_open", 0), _FakeToken("heading_open", 0)])
        counter.scan(tokens)
        assert counter.examined <= len(tokens), f"סריקה חוזרת בצעד {step}"
    assert counter.examined == len(tokens)
    assert counter.seen == 20


class _FakeToken:
    """טוקן מינימלי למונה. סטאב מלא ולא מצומצם — שני השדות שהוא קורא."""

    def __init__(self, type_, level):
        self.type = type_
        self.level = level


def test_the_counter_ignores_headings_inside_containers():
    counter = md_parser._SectionCounter(max_sections=100)
    counter.scan([_FakeToken("heading_open", 1), _FakeToken("heading_open", 2)])
    assert counter.seen == 0


# ════════════════════════════════════════════════════════════════════
# הכרעה 5 — ``inline`` כבוי, והשם גולמי
# ════════════════════════════════════════════════════════════════════

def test_the_inline_core_rule_is_disabled():
    """נמדד: עם הכלל כבוי, הכללים הליבתיים הפעילים הם
    ``['normalize', 'block', 'text_join']``.
    """
    assert "inline" not in md_parser._MD.get_active_rules()["core"]
    assert "block" in md_parser._MD.get_active_rules()["core"], "הפרסור עצמו חייב להישאר"


@pytest.mark.parametrize(
    "source, expected",
    [
        ("# כותרת ATX\n", "כותרת ATX"),
        ("## כותרת ##\n", "כותרת"),
        ("כותרת setext\n===\n", "כותרת setext"),
        ("שורה ראשונה\nשורה שנייה\n---\n", "שורה ראשונה\nשורה שנייה"),
        ("### דפוס 1 — `MissingGreenlet`\n", "דפוס 1 — `MissingGreenlet`"),
        ("# כותרת עם \\# סולמית\n", "כותרת עם \\# סולמית"),
        ("## **מודגש** [x](y)\n", "**מודגש** [x](y)"),
        ("###\n", ""),
    ],
)
def test_the_title_is_the_raw_source_text(source, expected):
    """כל שמונה הצורות מטבלת המדידה. הבקטיקים, ההדגשה, הקישור וה-escape
    נשמרים; ה-``#`` וקו ה-setext מוסרים; רווחים מסביב מקוצצים.
    """
    doc = md_parser.parse_document(source)
    assert [s.title for s in doc.sections] == [expected]


def test_the_adornment_is_the_markup_of_the_heading():
    doc = md_parser.parse_document("# א\n\n## ב\n\nsetext\n===\n\nאחר\n---\n")
    assert [s.adornment for s in doc.sections] == ["#", "##", "=", "-"]
    assert all(s.over is False for s in doc.sections)


# ════════════════════════════════════════════════════════════════════
# הכרעה 6 — ``end_line`` מחושב, ולא נלקח מ-``token.map``
# ════════════════════════════════════════════════════════════════════

_NESTED = """## ראשון

a

### תת א

b

### תת ב

c

## שני

d
"""


def test_the_section_ends_before_the_next_heading_at_the_same_or_higher_level():
    doc = md_parser.parse_document(_NESTED)
    by_title = {s.title: s for s in doc.sections}
    assert by_title["תת א"].end_line == by_title["תת ב"].heading_line - 1
    assert by_title["ראשון"].end_line == by_title["שני"].heading_line - 1
    assert by_title["שני"].end_line == len(doc.lines)


def test_token_map_covers_only_the_heading_line_itself():
    """זו הסיבה ש-``end_line`` אינו יכול לבוא מ-``token.map``.

    נמדד: ``map`` הוא ``(1, 1)`` ל-ATX ו-``(1, 3)`` ל-setext רב-שורתי —
    כלומר הוא אינו יודע דבר על גוף הסעיף. אילו ה-``end`` היה נלקח משם,
    "ראשון" היה נגמר בשורה שלו עצמו.
    """
    plain = MarkdownIt("commonmark").disable("inline")
    maps = [t.map for t in plain.parse(_NESTED, {}) if t.type == "heading_open"]
    assert maps[0] == [0, 1], maps
    doc = md_parser.parse_document(_NESTED)
    assert doc.sections[0].end_line > maps[0][1]


# ════════════════════════════════════════════════════════════════════
# הרחבת ה-GFM היחידה שמזיזה כותרת
# ════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "name, source",
    [
        ("טבלה ואז --- צמוד", "| a | b |\n|---|---|\n| 1 | 2 |\n---\n\n## אחרי\n"),
        ("טבלה ואז === צמוד", "| a | b |\n|---|---|\n| 1 | 2 |\n===\n\n## אחרי\n"),
        ("טבלה בלי גוף ואז ---", "| a | b |\n|---|---|\n---\n\n## אחרי\n"),
    ],
)
def test_a_table_is_a_table_and_not_a_setext_heading(name, source):
    """**זו הרגרסיה שהפריסט ``commonmark`` לבדו מייצר.**

    בלי ``enable("table")`` שורות הטבלה הן פסקה, והקו שאחריהן הופך אותה
    לכותרת setext: מתקבל סעיף שכותרתו היא הטבלה כולה, **והסעיף שמעליו
    נגמר לפני הטבלה במקום אחריה**. הטבלה המחוללת שב-
    ``tests/test_md_parser_oracle.py`` לא כיסתה את המחלקה הזאת, כי היא
    לעולם אינה מציבה שורת תא ושורת מפריד זו אחרי זו — ולכן הצורות האלה
    מקובעות כאן בנפרד, ושם נוספה משפחה שמחוללת אותן.
    """
    sections = md_parser.parse_document(source).sections
    assert [s.title for s in sections] == ["אחרי"], name


def test_only_the_table_extension_is_enabled_on_top_of_commonmark():
    """ארבע ההרחבות האחרות של GFM נבדקו ואינן משנות זיהוי כותרות.

    ``strikethrough`` ו-``autolink`` הן inline, ``tagfilter`` נוגע
    ברינדור, ו-``tasklist`` משנה פריט רשימה ולא גבול בלוק. הן נשארות
    כבויות כדי שלא ידלק כאן שום דבר שלא נמדד.
    """
    block_rules = md_parser._MD.get_active_rules()["block"]
    assert "table" in block_rules
    inline_rules = md_parser._MD.get_active_rules()["inline"]
    assert "strikethrough" not in inline_rules
    assert "autolink" not in md_parser._MD.get_active_rules()["inline2"]


# ════════════════════════════════════════════════════════════════════
# ערוץ הכשל, ונעיצת התלויות
# ════════════════════════════════════════════════════════════════════

def test_a_file_without_headings_is_an_empty_map_and_not_a_failure():
    doc = md_parser.parse_document("סתם פסקה\n\nועוד אחת\n")
    assert doc.sections == []
    assert doc.lines == ["סתם פסקה", "", "ועוד אחת", ""]


@pytest.mark.parametrize("bad", [None, 17, b"# bytes\n", ["# list"]])
def test_input_that_is_not_a_string_is_refused_in_the_entry(bad):
    """הטקסט מגיע מחוץ לתהליך, ולכן הטיפוס נבדק לפני כל ``.replace``."""
    with pytest.raises(TypeError):
        md_parser.parse_document(bad)


def test_the_two_exceptions_come_from_the_same_module():
    """המטפל שימיר אותן לתשובת MCP מייבא את שתיהן ממקום אחד."""
    assert md_parser.TooManySections is doc_sections.TooManySections
    assert md_parser.InconsistentLineEndings is doc_sections.InconsistentLineEndings


@pytest.mark.parametrize(
    "package, module",
    [("markdown-it-py", "markdown_it"), ("mdit-py-plugins", "mdit_py_plugins")],
)
def test_the_parser_dependencies_are_pinned_directly_in_base_requirements(package, module):
    """``markdown-it-py`` הגיע עד היום רק כתלות עקיפה של ``rich``, בטווח
    פתוח. נעיצה ישירה היא התנאי הראשון מדוח המדידה, והטסט הזה מוודא
    שהיא לא נשמטה ושהיא תואמת למה שבאמת מותקן.
    """
    import importlib.metadata as metadata

    base = (_REPO / "requirements" / "base.txt").read_text(encoding="utf-8")
    found = re.search(rf"^{re.escape(package)}==(\S+)$", base, re.MULTILINE)
    assert found, f"{package} אינו נעוץ ישירות ב-requirements/base.txt"
    assert found.group(1) == metadata.version(package)
    __import__(module)


#: הדרישות שנקראו מהמטא-דאטה של ``myst-parser`` בגרסה שנעוצה ב-
#: ``docs/requirements.txt``. אילוץ, ולא העדפה: הוא זה שקובע כמה גבוה
#: מותר לנעוץ ב-``requirements/base.txt``.
_MYST_PINNED = "4.0.1"
_MYST_REQUIRES = {"markdown-it-py": "3.0", "mdit-py-plugins": "0.4"}


def test_the_parser_pins_can_be_installed_next_to_the_docs_toolchain():
    """שני קבצי התלויות של הריפו הזה חייבים להיות ברי-התקנה יחד.

    **וזה לא תיאורטי:** ``.github/workflows/documentation-py39.yml``
    מתקין את ``docs/requirements.txt`` ואת ``requirements/production.txt``
    לאותה סביבה, ומפתח שמריץ את שניהם יחד מקבל
    ``ResolutionImpossible`` — נמדד. ``myst-parser==4.0.1`` דורש
    ``markdown-it-py~=3.0``, ולכן נעיצה ל-4.2.0 כאן הייתה סתירה בין שני
    קבצים באותו ריפו.

    .. important::

       **הטסט הזה ייפול כששדרגו את myst-parser, וזו המטרה.** הדרישות
       שב-``_MYST_REQUIRES`` נקראו מהמטא-דאטה של הגרסה שב-
       ``_MYST_PINNED``, ולכן שינוי בצד אחד מחייב לקרוא מחדש את הצד
       השני. ‏myst-parser 5.x, למשל, דורש ``markdown-it-py~=4.2`` —
       ואז **צריך** להעלות כאן, לא להשאיר.
    """
    import importlib.metadata as metadata

    docs = (_REPO / "docs" / "requirements.txt").read_text(encoding="utf-8")
    base = (_REPO / "requirements" / "base.txt").read_text(encoding="utf-8")

    found = re.search(r"^myst-parser==(\S+)$", docs, re.MULTILINE)
    assert found, "myst-parser אינו נעוץ ב-docs/requirements.txt"
    assert found.group(1) == _MYST_PINNED, (
        f"myst-parser עודכן ל-{found.group(1)} — קרא מחדש את הדרישות שלו "
        f"ועדכן את _MYST_REQUIRES יחד עם הנעיצות ב-base.txt"
    )

    for package, required_series in _MYST_REQUIRES.items():
        pinned = re.search(rf"^{re.escape(package)}==(\S+)$", base, re.MULTILINE)
        assert pinned, f"{package} אינו נעוץ ב-requirements/base.txt"
        assert pinned.group(1).startswith(required_series + "."), (
            f"{package}=={pinned.group(1)} ב-base.txt אינו מקיים את "
            f"~={required_series} ש-myst-parser {_MYST_PINNED} דורש"
        )
        # ומה שבאמת מותקן, כדי שהקובץ והסביבה לא ייפרדו בשקט
        assert metadata.version(package) == pinned.group(1)


def test_the_oracle_is_a_test_dependency_only():
    """``cmarkgfm`` הוא אורקל, לא תלות ייצור. אם הוא ייכנס ל-base הוא
    יותקן בשירות בלי שום קורא — ומי שיראה אותו שם יניח שהוא בשימוש.
    """
    base = (_REPO / "requirements" / "base.txt").read_text(encoding="utf-8")
    dev = (_REPO / "requirements" / "development.txt").read_text(encoding="utf-8")
    assert "cmarkgfm" not in base
    assert re.search(r"^cmarkgfm==\S+$", dev, re.MULTILINE)


# ════════════════════════════════════════════════════════════════════
# טסט הסחיפה — שני העותקים הקיימים בריפו, מול הספרייה עצמה
# ════════════════════════════════════════════════════════════════════
#
# ‏``md_parser`` אינו כותב אף אחד משני הכללים האלה בעצמו: את ה-front
# matter הוא מקבל מהתוסף, ואת ה-``\r`` הבודד הוא בודק בביטוי שזהה
# מילה במילה לזה שבמנתב. מה שנשאר לבדוק הוא **שני העותקים שכבר קיימים
# בריפו** — והאמת שמולה הם נמדדים היא ``markdown-it-py`` עצמו.


def _load_ai_map_generator():
    """טעינה לפי נתיב, כי ``scripts`` אינה חבילה — כמו ב-
    ``tests/test_ai_map_generator.py``."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "generate_ai_map_for_drift", _REPO / "scripts" / "generate_ai_map.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_LINE_ENDING_INPUTS = [
    ("LF", "# A\n\n## B\n"),
    ("CRLF", "# A\r\n\r\n## B\r\n"),
    ("CR בלבד", "# A\r\r## B\r"),
    ("LF עם CR באמצע", "# A\n\n## B\rX\n\n### C\n"),
    ("CR בסוף הקובץ", "# A\n\n## B\r"),
    ("בלי שום CR", "סתם טקסט\n"),
]


@pytest.mark.parametrize("name, text", _LINE_ENDING_INPUTS)
def test_the_lone_cr_rule_matches_markdown_it(name, text):
    """שני העותקים של כלל ה-``\\r`` הבודד, מול ההתנהגות שהם מתארים.

    אמת המידה אינה אחד מהם אלא ``markdown-it-py``: הכלל שלו,
    ``rules_core/normalize.py`` עם ``\\r\\n?|\\n``, הוא מה שהופך ``\\r``
    בודד לשורה חדשה — ומשם הפער מול ``split("\\n")`` שכל שדות ה-
    ``lines`` ב-MCP נספרים בו.

    הטסט מריץ את הביטוי משני המקומות ואת הספרייה, ודורש שהשלושה יסכימו
    על כל קלט. פיצול עתידי של אחד מהם ייפול כאן.
    """
    from mcp_server import outline as outline_router

    by_router = bool(outline_router._CR_WITHOUT_LF.search(text))
    by_parser = bool(md_parser._CR_WITHOUT_LF.search(text))

    # האמת: האם ``markdown-it-py`` סופר שורות אחרת מ-``split("\n")``?
    normalized_by_library = re.sub(r"\r\n?|\n", "\n", text)
    normalized_by_us = text.replace("\r\n", "\n")
    by_library = normalized_by_library != normalized_by_us

    assert by_router == by_parser == by_library, {
        "מנתב": by_router,
        "פארסר": by_parser,
        "הספרייה": by_library,
    }


#: הפער שנמדד בין ``_body_start`` לבין התוסף, צורה ← האם התוסף רואה כאן
#: front matter. ``True`` פירושו שהתוסף מזהה בלוק והפונקציה הישנה לא, או
#: להפך — הפירוט בעמודה השלישית.
_FRONT_MATTER_SHAPES = [
    # (שם, טקסט, האם התוסף מזהה בלוק, האם _body_start מזהה בלוק)
    ("רגיל", "---\na: 1\n---\n\n# כותרת\n", True, True),
    ("סוגר ...", "---\na: 1\n...\n\n# כותרת\n", True, True),
    ("לא נסגר", "---\na: 1\n\n# כותרת\n", False, False),
    ("פותח 4 סוגר 3", "----\na: 1\n---\n\n# כותרת\n", False, False),
    ("ריק", "", False, False),
    # ── חמש הצורות שבהן הם חלוקים, כפי שנמדדו ──
    ("פותח מוזח", "  ---\na: 1\n---\n\n# כותרת\n", False, True),
    ("פותח רווח בסוף", "--- \na: 1\n---\n\n# כותרת\n", True, True),
    ("סוגר מוזח", "---\na: 1\n  ---\n\n# כותרת\n", True, True),
    ("ארבעה מקפים", "----\na: 1\n----\n\n# כותרת\n", True, False),
    ("פותח 3 סוגר 4", "---\na: 1\n----\n\n# כותרת\n", True, False),
    ("פותח עם טקסט", "---title\na: 1\n---\n\n# כותרת\n", True, False),
]


@pytest.mark.parametrize("name, text, plugin_sees, body_start_sees", _FRONT_MATTER_SHAPES)
def test_the_front_matter_rules_still_disagree_as_measured(
    name, text, plugin_sees, body_start_sees
):
    """**הטסט הזה מקבע פער מדוד, ולא התנהגות רצויה.**

    אמת המידה היא ``mdit_py_plugins.front_matter`` — מה ש-MyST באמת
    מריץ, ומה ש-``md_parser`` רושם על מופע הפארסר שלו.
    ``scripts/generate_ai_map.py::_body_start`` הוא **הסוטה**: הוא
    כותב את אותו כלל ביד ו-``.strip()`` שבו מקבל ``---`` מוזח שהתוסף
    דוחה, ופוסל ``----`` וסוגר ארוך מהפותח שהתוסף מקבל.

    .. warning::

       **נפילה של הטסט הזה אחרי שהפער ייסגר היא תוצאה מכוונת.** היעד
       הוא ש-``_body_start`` יעבור להשתמש בתוסף; ביום שזה יקרה, הטסט
       הזה **חייב** להיערך יחד עם השינוי ועם האישו שמתעד אותו. אל
       "תתקן" אותו כאילו היה באג — הוא הדבר היחיד שמונע מהפער להיסחף
       בשקט לכיוון שלישי.

    בקורפוס של היום אין לאף אחת מחמש הצורות החלוקות מופע: 23 מתוך 34
    קובצי ה-``.md`` תחת ``docs/`` פותחים ב-``---`` מדויק, ואפס במוזח או
    עם רווח. כלומר המפה שנוצרת היום נכונה, והפער הוא חוב ולא תקלה.
    """
    from mdit_py_plugins.front_matter import front_matter_plugin

    probe = MarkdownIt("commonmark").use(front_matter_plugin).disable("inline")
    saw_block = any(t.type == "front_matter" for t in probe.parse(text, {}))
    assert saw_block is plugin_sees, f"התנהגות התוסף השתנתה בצורה {name!r}"

    generator = _load_ai_map_generator()
    assert bool(generator._body_start(text.split("\n"))) is body_start_sees, (
        f"‏_body_start השתנה בצורה {name!r} — עדכן את הטבלה יחד עם האישו"
    )


def test_the_parser_never_invents_a_section_where_the_plugin_sees_front_matter():
    """הצד שבאמת חשוב לקורא: בכל צורה שהתוסף מזהה כבלוק, אין סעיף מומצא.

    וגם ההפך — בצורה שהתוסף **אינו** מזהה (``---`` מוזח), הכותרת
    ה"מומצאת" היא התנהגות CommonMark נכונה ולא באג שלנו, ולכן היא
    מוצהרת כאן במפורש.
    """
    for name, text, plugin_sees, _old in _FRONT_MATTER_SHAPES:
        if not text:
            continue
        titles = [s.title for s in md_parser.parse_document(text).sections]
        if plugin_sees:
            assert titles == ["כותרת"], (name, titles)
        else:
            assert "כותרת" in titles, (name, titles)
