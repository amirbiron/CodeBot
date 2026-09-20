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
# BOM — מוסר בכניסה, ורק הוא
# ════════════════════════════════════════════════════════════════════

_BOM = "\ufeff"


def test_a_leading_bom_does_not_hide_the_headings():
    """קובץ עם BOM נותן **אותה** מפה כמו בלעדיו.

    בלי ההסרה ``markdown-it`` רואה פסקה שמתחילה בתו בלתי נראה ולא
    כותרת, והפארסר החזיר **אפס סעיפים בלי חריגה** — מפה ריקה שמתחזה
    לקובץ בלי כותרות. נמדד. הייצור לא נפגע (המראה מפענחת ב-``utf-8-sig``),
    ולכן זה נתפס רק בסקירה, על הסקריפט.
    """
    plain = "# Title\n\ntext\n\n## Sub\n"
    with_bom = md_parser.parse_document(_BOM + plain)
    without = md_parser.parse_document(plain)
    assert [(s.level, s.heading_line, s.title) for s in with_bom.sections] == \
        [(s.level, s.heading_line, s.title) for s in without.sections]
    assert with_bom.lines == without.lines, "ה-BOM חייב לרדת גם מ-lines[0]"
    assert len(with_bom.sections) == 2


def test_only_one_bom_and_only_at_the_start_is_removed():
    """‏``U+FEFF`` באמצע הטקסט הוא ZWNBSP — תוכן, ולא נוגעים בו.

    ושני BOM רצופים: רק הראשון הוא סימון קידוד. השני הוא כבר תו בגוף
    השורה — וזה מה ש-cmark עושה בפועל, נמדד.
    """
    doc = md_parser.parse_document(_BOM + _BOM + "# A\n\ntext " + _BOM + "here\n")
    assert doc.lines[0] == _BOM + "# A"
    assert _BOM in doc.lines[2]
    assert doc.sections == [], "BOM שני בראש השורה מונע כותרת — כמו ב-cmark"


# ════════════════════════════════════════════════════════════════════
# הכרעה 2 — ``\r`` בודד נדחה, CRLF לא
# ════════════════════════════════════════════════════════════════════

_LF = "# A\n\n## B\n\n### C\n"


def test_a_lone_cr_is_refused():
    with pytest.raises(doc_sections.InconsistentLineEndings):
        md_parser.parse_document("# A\r\r## B\r\r### C\r")


@pytest.mark.parametrize(
    "name, text, expected_line",
    [
        ("בשורה הראשונה", "# a\rb\n## c\n", 1),
        ("באמצע הקובץ", "# a\n\n## b\rx\n\n### c\n", 3),
        ("בסוף הקובץ", "# a\n\n## b\r", 3),
    ],
)
def test_the_refusal_says_where_the_lone_cr_is(name, text, expected_line):
    """מבין שלושת ערוצי הסירוב, זה היה היחיד שלא אמר איפה.

    ‏``TooManySections`` נושאת את השורה שבה נעצרנו, ו-``TypeError``
    נושא את הסוג שהתקבל. ``InconsistentLineEndings`` הורמה ריקה, ומי
    שהיה צריך לתקן את הקובץ קיבל רק "יש ``\\r`` איפשהו". המיקום ממילא
    מחושב — ``search`` מחזיר אובייקט התאמה — והוא נזרק לפח.
    """
    with pytest.raises(doc_sections.InconsistentLineEndings) as caught:
        md_parser.parse_document(text)

    assert caught.value.args == (expected_line,), name


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
    """טוקן מינימלי למונה.

    ‏``type`` הוא מה שהמונה קורא היום; ``level`` נשאר כאן כי הוא מה
    שמבדיל כותרת שנכנסת למפה מכותרת שבתוך מכל, וזו בדיוק ההבחנה שהמונה
    **אינו** עושה יותר — טסט שבונה טוקן בלי ``level`` לא היה יכול
    להראות את זה.
    """

    def __init__(self, type_, level):
        self.type = type_
        self.level = level


def test_the_counter_counts_headings_inside_containers():
    """התקרה מגבילה עבודה ולא תוצאה, ולכן כותרת במכל נספרת.

    היא **אינה** נכנסת למפה — זה נבדק ב-
    ``test_a_heading_inside_a_container_is_not_a_section`` — אבל היא
    עולה בדיוק כמו כל כותרת אחרת. נמדד: 500KB של ``> ## h`` הם ~64,000
    כותרות, וספירה לפי ``level == 0`` ראתה בהן אפס ולא עצרה לעולם.
    """
    counter = md_parser._SectionCounter(max_sections=100)
    counter.scan([_FakeToken("heading_open", 1), _FakeToken("heading_open", 2)])
    assert counter.seen == 2


def test_the_ceiling_is_not_fooled_by_a_container_heading_in_the_last_block():
    """הדלף שהיה נפתח אילו רק המונה היה משתנה, בלי השער השני.

    הכלל שבתוך הפרסור נקרא בתחילת כל בלוק ולכן אינו רואה את הבלוק
    האחרון, והשער שאחרי הפרסור היה סופר **סעיפים** — שכאן הם אפס, כי
    כל הכותרות בתוך ציטוט. כלומר שני השערים היו מודדים שני דברים
    שונים, והקלט הזה היה עובר בלי שום סירוב. נמדד בדיוק כך.
    """
    ceiling = 20
    text = "> ## q\n\n" * ceiling + "> ## last\n"

    with pytest.raises(md_parser.TooManySections):
        md_parser.parse_document(text, max_sections=ceiling)


# ════════════════════════════════════════════════════════════════════
# המופע המשותף — נבנה **במלואו** לפני שהוא מתפרסם
# ════════════════════════════════════════════════════════════════════

def test_every_ruler_a_real_parse_uses_is_compiled_before_publish(monkeypatch):
    """אף ruler לא נבנה בפעם הראשונה **תוך כדי** פרסור.

    ‏``markdown-it`` בונה את רשימת הכללים של כל ruler עצלה, בקריאה
    הראשונה ל-``getRules``, בלי מנעול; ו-``Ruler.__compile__`` מפרסם
    מילון ריק לפני שהוא ממלא אותו. כלומר שני חוטים שמפרסרים ראשונים
    יחד יכולים לראות רשימת כללים חלקית — ואז ``parse_document`` מחזיר
    מפה ריקה למסמך שיש בו כותרות, בלי שום חריגה.

    ‏``_build_parser`` סוגר את זה בפרסור חימום. **הטסט הזה בודק את
    הכיסוי ולא את הקריאה**: הוא מרגל אחרי ``getRules`` ומחפש ruler
    שהגיע אליו לא מקומפל. לכן הוא לא יתיישן — אם גרסה עתידית של
    ``markdown-it`` תוסיף ruler למסלול והחימום יפספס אותו, הטסט ייפול
    במקום שהחלון ייפתח בשקט.

    **ולמה אין כאן טסט עם חוטים, למרות ש-T1 ב-``TESTING-PATTERNS``
    דורש שתכונת מקביליות תיבדק במקביל.** מה שהקוד מבטיח הוא תכונה
    **דטרמיניסטית** — "כל ruler שפרסור אמיתי צורך מקומפל לפני
    הפרסום" — וזה בדיוק מה שנטען כאן. הסירוב המקבילי עצמו נמדד
    בהרצת עומס ולא בטסט: טסט חוטים היה מנסה להוכיח **היעדר** מרוץ,
    וריצה ירוקה שלו אינה ראיה. המספרים, לפני ואחרי, בגוף ה-PR.
    """
    from markdown_it.ruler import Ruler

    md = md_parser._build_parser()
    by_id = {
        id(md.core.ruler): "core",
        id(md.block.ruler): "block",
        id(md.inline.ruler): "inline",
        id(md.inline.ruler2): "inline2",
    }
    found_uncompiled = []
    original = Ruler.getRules

    def spy(self, chainName=""):
        if self.__cache__ is None:
            found_uncompiled.append(by_id.get(id(self), f"<{id(self)}>"))
        return original(self, chainName)

    monkeypatch.setattr(Ruler, "getRules", spy)
    # מסמך מייצג ולא מינימלי: כותרת, מכל, טבלה, גדר ו-front matter —
    # כדי שכל ענף במסלול יתבקש להביא את הכללים שלו.
    md.parse(
        "---\na: 1\n---\n\n# כותרת\n\n> ## בציטוט\n\n- ## בפריט\n\n"
        "| a | b |\n|---|---|\n| 1 | 2 |\n\n```py\nx = 1\n```\n\nסטקסט\n------\n"
    )

    assert not found_uncompiled, (
        "פרסור החימום ב-``_build_parser`` פספס rulers שפרסור אמיתי צורך, "
        f"והם נבנו תוך כדי הפרסור: {sorted(set(found_uncompiled))}. "
        "זה החלון של lazy-init-guard-publish-order — הרחב את מסמך החימום."
    )


def test_the_ceiling_anchor_fails_loudly_when_the_plugin_is_not_registered():
    """העוגן ``before("front_matter", ...)`` קונה כשל מיידי — ועל מה בדיוק.

    ה-docstring של ``_build_parser`` טען קודם שהעוגן תופס **תלות
    חסרה**, וזה לא מדויק: חבילה שאינה מותקנת מפילה את הייבוא שבראש
    הקובץ, הרבה לפני שמגיעים לכאן. מה שהעוגן באמת תופס הוא **הסרה של
    הרישום** — מישהו שימחק את ``.use(front_matter_plugin)`` וישאיר את
    השורה הזאת. הטסט מקבע את המנגנון שהמשפט המתוקן מתאר.
    """
    bare = MarkdownIt("commonmark").disable("inline")

    with pytest.raises(KeyError, match="front_matter"):
        bare.block.ruler.before("front_matter", "ck_max_sections", md_parser._ceiling_rule)


def test_a_heading_token_without_a_map_is_refused_and_not_dropped():
    """הענף היחיד במודול שהיה מפיל סעיף בשקט — עכשיו מרים.

    אומת מול ``rules_block/heading.py`` ו-``lheading.py``: כל מסלול
    שדוחף ``heading_open`` מציב ``map`` ללא תנאי, ולכן הענף אינו ניתן
    להגעה היום והטסט בונה את המצב ביד. מה שנבדק הוא ההכרעה: מפה שחסר
    בה סעיף, בלי לוג ובלי חריגה, היא בדיוק ה"לא נמצא שנראה כמו נשבר"
    שה-docstring של המודול מצהיר שאין בו.
    """

    class _MaplessHeading:
        type = "heading_open"
        level = 0
        tag = "h2"
        markup = "##"
        map = None

    with pytest.raises(RuntimeError, match="heading_open"):
        md_parser._sections_from_tokens([_MaplessHeading()], total_lines=1)


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


#: כותרת setext רב-שורתית: המקור, והטקסט שהכותרת אמורה לשאת.
#: המדידה שמאחורי כל שורה היא ה-HTML של ``markdown-it-py`` **עצמה** —
#: לא פרשנות שלנו — ושל cmark-gfm, ושניהם מסכימים.
_MULTILINE_SETEXT = [
    ("המשך מוזח בארבעה רווחים", "aaa\n    bbb\n===\n", "aaa\nbbb"),
    ("המשך מוזח בטאב", "aaa\n\tbbb\n===\n", "aaa\nbbb"),
    ("רווח בודד בסוף השורה הראשונה", "aaa \nbbb\n===\n", "aaa\nbbb"),
    ("שני רווחים — hardbreak", "aaa  \nbbb\n===\n", "aaa\nbbb"),
    ("שלוש שורות, שתי הזחות שונות", "aaa\n  bbb\n\tccc\n===\n", "aaa\nbbb\nccc"),
    ("רווח סופי והזחה יחד", "aaa  \n   bbb\n===\n", "aaa\nbbb"),
    # השארית המכוונת: רווח כפול **בתוך** השורה אינו רווח של מעבר שורה,
    # ולכן הוא נשמר — גם ב-markdown-it וגם ב-cmark.
    ("רווח כפול באמצע השורה", "aaa  bbb\n===\n", "aaa  bbb"),
]


@pytest.mark.parametrize("name, source, expected", _MULTILINE_SETEXT)
def test_a_multiline_setext_title_drops_the_whitespace_that_is_not_text(name, source, expected):
    """ההזחה של שורת ההמשך אינה חלק מהכותרת, ואצלנו היא הייתה שורדת.

    זו הייתה סטייה **שלנו** ולא של הספרייה: ה-HTML של ``markdown-it-py``
    עצמה מחזיר ``<h1>aaa\\nbbb</h1>``, כלומר כלל ה-softbreak שלה מוריד
    את הרווחים — והוא חי ב-``inline``, שאנחנו מכבים. כל עוד לא שיחזרנו
    את הכלל הזה, ``token.content`` נשא הזחה שלא הופיעה בשום רינדור,
    והיא הייתה מגיעה למשתמש דרך ``build_toc``.

    נתפס על ידי השוואת הטקסט מול cmark-gfm שנוספה באותו סבב — לפני שהיא
    נוספה, ההשוואה הייתה על רמה ומספר שורה בלבד ולא יכלה לראות את זה.
    """
    doc = md_parser.parse_document(source)
    assert [s.title for s in doc.sections] == [expected], name


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

    ``strikethrough`` ו-GFM autolink (``linkify`` ב-``markdown-it``) הן
    inline, ``tagfilter`` נוגע ברינדור, ו-``tasklist`` משנה פריט רשימה
    ולא גבול בלוק. הן נשארות כבויות כדי שלא ידלק כאן שום דבר שלא נמדד.
    """
    block_rules = md_parser._MD.get_active_rules()["block"]
    assert "table" in block_rules
    inline_rules = md_parser._MD.get_active_rules()["inline"]
    assert "strikethrough" not in inline_rules
    # **``linkify`` ולא ``autolink``.** ``autolink`` הוא הכלל של CommonMark
    # ל-``<https://a.b>`` — הוא דלוק, ונשאר דלוק, ואינו ההרחבה של GFM.
    # ההרחבה של GFM (``www.a.b`` הופך לקישור) היא ``linkify``, שיושב
    # **בשני** rulers — ``core`` ו-``inline`` — ושניהם חייבים להיות
    # כבויים. הטענה הקודמת בדקה ``autolink`` ב-``inline2``, ששם הוא לא
    # ישב מעולם — טענה שלא יכלה ליפול. ``enable("linkify")`` מדליק את
    # שניהם, ולכן היא נופלת עליו.
    active = md_parser._MD.get_active_rules()
    assert "linkify" not in active["core"]
    assert "linkify" not in active["inline"]


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


def test_the_two_parsers_export_the_same_names_but_two():
    """"בני-החלפה" היא טענה בת-בדיקה, לא משאלה.

    כל שם ש-``rst_parser`` מייצא קיים גם ב-``md_parser``, וההפרש הוא
    **בדיוק** שני השמות שהפרוזה מונה. שם שיתווסף לאחד מהם בלי השני,
    או ייצוא של ``InconsistentLineEndings`` מ-``rst_parser`` (שאינו מרים
    אותה), מפיל את זה.
    """
    from services import rst_parser

    rst, md = set(rst_parser.__all__), set(md_parser.__all__)
    assert rst <= md, f"שמות שרק ב-rst_parser: {sorted(rst - md)}"
    assert md - rst == {"MAX_SECTIONS", "InconsistentLineEndings"}


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
#: **המפרטים כפי שהם כתובים במטא-דאטה של myst-parser**, ולא הסדרה
#: שגזרנו מהם. ההבדל אינו סגנוני: ``~=3.0`` פירושו ``>=3.0, ==3.*``
#: ולכן ``3.1.0`` מקיים אותו, ו-``~=0.4`` פירושו ``>=0.4, ==0.*`` ולכן
#: גם ``0.5.0`` מקיים. בדיקה שהשוותה קידומת ``"3.0."`` הייתה דוחה את
#: שניהם ומאשימה את myst-parser בדרישה שאין לו.
_MYST_REQUIRES = {
    "markdown-it-py": "~=3.0",
    "mdit-py-plugins": "~=0.4,>=0.4.1",
}


def _satisfies_myst_requirement(package: str, version: str) -> bool:
    """האם ``version`` מקיים את מה ש-myst-parser דורש מ-``package``.

    **הפרדיקט מחולץ כדי שיהיה מה לשמור עליו.** ``packaging`` הוא
    המימוש הרשמי של PEP 440 והוא מגיע עם pytest, ולכן זמין בכל מקום
    שהטסטים רצים בו בלי להצהיר עליו. לכתוב כאן פרשן מפרטים ביד — או
    להסתפק בהשוואת קידומת, כפי שהיה — הוא בדיוק הכלל-שנכתב-שוב שהענף
    הזה נלחם בו, ולכן ``test_the_pin_check_accepts_every_version_...``
    שומר עליו.
    """
    from packaging.specifiers import SpecifierSet
    from packaging.version import Version

    return Version(version) in SpecifierSet(_MYST_REQUIRES[package])


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

    for package, requirement in _MYST_REQUIRES.items():
        pinned = re.search(rf"^{re.escape(package)}==(\S+)$", base, re.MULTILINE)
        assert pinned, f"{package} אינו נעוץ ב-requirements/base.txt"
        assert _satisfies_myst_requirement(package, pinned.group(1)), (
            f"{package}=={pinned.group(1)} ב-base.txt אינו מקיים את "
            f"{requirement} ש-myst-parser {_MYST_PINNED} דורש"
        )
        # ומה שבאמת מותקן, כדי שהקובץ והסביבה לא ייפרדו בשקט
        assert metadata.version(package) == pinned.group(1)


def test_the_pin_check_accepts_every_version_myst_parser_allows():
    """הבדיקה למעלה אינה קפדנית מהאילוץ שהיא מצטטת.

    **וזה היה שגוי.** הנוסח הקודם השווה קידומת (``"3.0."``), ולכן דחה
    את ``markdown-it-py 3.1.0`` ואת ``mdit-py-plugins 0.5.0`` — שתיהן
    גרסאות ש-myst-parser 4.0.1 **מתיר**. הודעת הכשל הייתה אומרת
    "אינו מקיים את ~=3.0", טענה שאינה נכונה, ושולחת את המתחזק לחקור
    את החבילה הלא נכונה.

    .. note::

       **הטסט הזה אינו נופל על הקוד שלפני התיקון, וזה מכוון.** הפגם
       הישן היה בצורת ההשוואה בתוך הטסט השכן, ולא בקוד ייצור. מה שהוא
       כן עושה הוא לשמור על ``_satisfies_myst_requirement``: כל חזרה
       להשוואת קידומת תפיל אותו. זו ההגנה שאפשר לתת כאן.
    """
    allowed = {
        "markdown-it-py": ["3.0.0", "3.1.0", "3.9.9"],
        "mdit-py-plugins": ["0.4.1", "0.4.2", "0.5.0", "0.6.0"],
    }
    forbidden = {
        "markdown-it-py": ["2.2.0", "4.0.0", "4.2.0"],
        "mdit-py-plugins": ["0.4.0", "1.0.0"],
    }

    for package, requirement in _MYST_REQUIRES.items():
        for version in allowed[package]:
            assert _satisfies_myst_requirement(package, version), (
                f"{package} {version} מקיים את {requirement} ולכן הבדיקה "
                "חייבת לקבל אותו — נוסח שדוחה אותו יאשים את myst-parser בטעות"
            )
        for version in forbidden[package]:
            assert not _satisfies_myst_requirement(package, version), (
                f"{package} {version} אינו מקיים את {requirement}"
            )


def test_the_oracle_is_a_test_dependency_only():
    """``cmarkgfm`` הוא אורקל, לא תלות ייצור. אם הוא ייכנס ל-base הוא
    יותקן בשירות בלי שום קורא — ומי שיראה אותו שם יניח שהוא בשימוש.
    """
    base = (_REPO / "requirements" / "base.txt").read_text(encoding="utf-8")
    dev = (_REPO / "requirements" / "development.txt").read_text(encoding="utf-8")
    assert "cmarkgfm" not in base
    assert re.search(r"^cmarkgfm==\S+$", dev, re.MULTILINE)


# ════════════════════════════════════════════════════════════════════
# סקריפט ההשוואה — מה הוא באמת רואה, ומה קורה כשקובץ אחד מוזר
# ════════════════════════════════════════════════════════════════════

def _load_compare_script():
    """טעינה לפי נתיב, כמו ב-``_load_ai_map_generator``."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "compare_md_parser_for_tests", _REPO / "scripts" / "compare_md_parser_to_cmark.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_compare_script_sees_a_lone_cr_and_survives_one_bad_file(tmp_path, capsys):
    """שני כשלים באותה לולאה, ושניהם שקטים לפני התיקון.

    **הראשון:** ``Path.read_text`` פותח את הקובץ במצב טקסט עם universal
    newlines וממיר כל ``\\r`` ל-``\\n``, ולכן ``InconsistentLineEndings``
    לא יכלה להידלק כאן על שום קובץ — הסקריפט היה מדווח "אפס
    אי-הסכמות" גם על הקלט שהוא קיים כדי לתפוס.

    **והשני:** הדוח נבנה אחרי הלולאה, ולכן קובץ יחיד שאינו UTF-8 היה
    מפיל את הריצה כולה ומוחק גם את מה שכבר נסרק. הסקריפט מכוון על ריפו
    **זר**, ולכן קובץ מוזר הוא המקרה הצפוי ולא החריג.
    """
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "a_good.md").write_bytes(b"# \xd7\x90\n\nbody\n\n## \xd7\x91\n")
    (corpus / "b_lone_cr.md").write_bytes(b"# Title\r\r## Sub\r\nbody\n")
    (corpus / "c_not_utf8.md").write_bytes(b"\xff\xfe# broken\n")

    script = _load_compare_script()
    exit_code = script.main([str(corpus)])
    report = capsys.readouterr().out

    # טענות על **מה** שהדוח אומר ולא על הריווח שלו: יישור עמודות הוא
    # קוסמטיקה, וטסט שנשבר ממנו הוא טסט שמתרגלים להתעלם ממנו.
    assert exit_code == 0, "אין אי-הסכמות בקובץ התקין, ולכן הריצה מצליחה"
    assert re.search(r"הושוו\s*1.*סורבו\s*2", report), report
    assert "b_lone_cr.md" in report and "\\r בודד" in report, "ה-CR הבודד חייב להיתפס"
    assert "c_not_utf8.md" in report and "אינו UTF-8" in report
    assert re.search(r"כותרות:\s+2\b", report), "הקובץ התקין חייב להיספר למרות שני הסירובים"


def test_the_compare_script_does_not_call_an_empty_run_a_success(tmp_path, capsys):
    """"אפס אי-הסכמות" על אפס קבצים שהושוו הוא אישור שקרי.

    זה אותו נימוק שכבר כתוב בסקריפט על ריפו בלי קובצי ``.md`` — מספר
    שנראה טוב כי לא נבדק דבר. בלי הבדיקה הזאת, בידוד התקלות לכל קובץ
    היה **יוצר** את הכשל הזה: לפניו ריפו כזה היה מפיל את הריצה בקול.
    """
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "only_bad.md").write_bytes(b"\xff\xfe# broken\n")

    script = _load_compare_script()
    exit_code = script.main([str(corpus)])

    assert exit_code == 1, "ריצה שלא השוותה דבר אינה מצליחה"
    assert "כל הקבצים סורבו" in capsys.readouterr().out


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
    # ── צורות שנראות חשודות ובכל זאת **מסכימות** — כאן בכוונה, כי
    #    "בדקנו ואין פער" הוא מידע בדיוק כמו פער ──
    ("פותח רווח בסוף", "--- \na: 1\n---\n\n# כותרת\n", True, True),
    ("סוגר מוזח 2 רווחים", "---\na: 1\n  ---\n\n# כותרת\n", True, True),
    # ── והצורות שבהן הם באמת חלוקים. המספר כאן אינו מוקלד בפרוזה:
    #    ``test_the_measured_front_matter_gap_matches_the_prose`` גוזר
    #    אותו מהטבלה ומשווה למה שכתוב ב-``md_parser`` ──
    ("פותח מוזח", "  ---\na: 1\n---\n\n# כותרת\n", False, True),
    # ארבעה רווחים הם בלוק קוד לפי CommonMark, ולכן התוסף אינו רואה
    # סוגר — ואילו ``_body_start`` עושה ``.strip()`` ומקבל. הצורה
    # הזאת נמדדה, הוזכרה ב-``generate_ai_map`` ונשמטה מהטבלה.
    ("סוגר מוזח 4 רווחים", "---\na: 1\n    ---\n\n# כותרת\n", False, True),
    ("ארבעה מקפים", "----\na: 1\n----\n\n# כותרת\n", True, False),
    ("פותח 3 סוגר 4", "---\na: 1\n----\n\n# כותרת\n", True, False),
    ("פותח עם טקסט", "---title\na: 1\n---\n\n# כותרת\n", True, False),
]

#: מספר הצורות שבהן התוסף ו-``_body_start`` חלוקים, **נגזר מהטבלה**.
#: הפרוזה ב-``services/md_parser.py`` וב-``requirements/base.txt``
#: מצטטת אותו, וטסט משווה — כדי שתוספת צורה בלי עדכון הפרוזה תפיל.
_FRONT_MATTER_DISAGREEMENTS = sum(
    1 for _, _, plugin_sees, body_start_sees in _FRONT_MATTER_SHAPES
    if plugin_sees is not body_start_sees
)

#: מילות המספר שהפרוזה משתמשת בהן. טווח קטן בכוונה: אם הטבלה תגדל מעבר
#: לו, הטסט ייפול על ``KeyError`` ויכריח מבט — וזה עדיף על השלמה שקטה.
_HEBREW_NUMBERS = {
    3: "שלוש", 4: "ארבע", 5: "חמש", 6: "שש", 7: "שבע", 8: "שמונה",
    9: "תשע", 10: "עשר", 11: "אחת-עשרה", 12: "שתים-עשרה",
    13: "שלוש-עשרה", 14: "ארבע-עשרה", 15: "חמש-עשרה",
}


def test_the_measured_front_matter_gap_matches_the_prose():
    """הפער שנמדד בטבלה הוא מה שכתוב בפרוזה, בשני המקומות שמצטטים אותו.

    **למה טסט ולא סתם לתקן את המספר.** זה בדיוק מה שכבר קרה: הטבלה
    גדלה, והפרוזה נשארה על "חמש מתוך שלוש-עשרה" בזמן שבטבלה היו
    אחת-עשרה שורות וארבע חלוקות — שלוש רשימות שונות של "חמש הצורות"
    חיו בריפו בו-זמנית. מספר שמוקלד ביד במקום שני מתיישן בשקט; מספר
    שנגזר מהקוד לא יכול.
    """
    disagreements = _HEBREW_NUMBERS[_FRONT_MATTER_DISAGREEMENTS]
    total = _HEBREW_NUMBERS[len(_FRONT_MATTER_SHAPES)]
    expected = f"{disagreements} מתוך {total}"

    parser_source = (_REPO / "services" / "md_parser.py").read_text(encoding="utf-8")
    base = (_REPO / "requirements" / "base.txt").read_text(encoding="utf-8")

    for name, text in (("services/md_parser.py", parser_source), ("requirements/base.txt", base)):
        assert expected in text, (
            f"{name} אינו אומר {expected!r}. הטבלה מכילה עכשיו "
            f"{len(_FRONT_MATTER_SHAPES)} צורות ובהן {_FRONT_MATTER_DISAGREEMENTS} "
            "חלוקות — עדכן את הפרוזה יחד עם הטבלה."
        )


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


# ════════════════════════════════════════════════════════════════════
# פונקציות העץ המשותפות — על מסמך Markdown, ולא רק על RST
# ════════════════════════════════════════════════════════════════════

# ‏``services/doc_sections.py`` נכתב עבור ``rst_parser`` והיה לו עד עכשיו
# מזין אחד בלבד. הפארסר הזה מזין אותו בצורה שהוא לא ראה קודם: כותרת
# שנושאת **סימון גולמי** (בקטיקים, הדגשה, קישור), וכותרת setext שנפרסת
# על שתי שורות ולכן ה-``title`` שלה מכיל ``\n`` באמצע. ב-RST שתי
# הצורות אינן קיימות.
#
# הטסטים כאן מריצים את כל הפונקציות המשותפות שאין להן אף הרצה כזאת —
# ‏``build_toc``, ‏``find_sections``, ‏``neighbors``, ‏``normalize_title``,
# ‏``section_bounds``, ‏``suggest``, ‏``direct_subsections``. ‏(``section_text``
# כבר מורץ למעלה.) הם נכתבו לפני שנבדק אם משהו נשבר: אם הכול עובר,
# הערך שלהם הוא הקיבוע — שינוי עתידי באחת מהן ייתפס גם מהצד הזה.
_MARKDOWN_SHAPED = """# `code` ו-**bold**

מבוא

## [קישור](https://example.com) בכותרת

תוכן א

כותרת setext
שנפרסת על שתי שורות
---

תוכן ב

### תת-סעיף

תוכן ג
"""


def _shaped() -> doc_sections.Document:
    return md_parser.parse_document(_MARKDOWN_SHAPED)


def test_the_shared_tree_sees_the_markdown_document_as_three_top_levels():
    """קודם המבנה, כי כל השאר נשען עליו."""
    doc = _shaped()
    assert [(s.level, s.title) for s in doc.sections] == [
        (1, "`code` ו-**bold**"),
        (2, "[קישור](https://example.com) בכותרת"),
        (2, "כותרת setext\nשנפרסת על שתי שורות"),
        (3, "תת-סעיף"),
    ]


def test_find_sections_matches_a_title_that_carries_raw_markup():
    """‏``find_sections`` עובר דרך ``normalize_title``, וזה המסלול שנבדק.

    הסימון הגולמי **אינו** מוסר בדרך — מי שמחפש מחפש את מה שכתוב
    בקובץ. מה שכן נסלח הוא רווח כפול, וזה נבדק כאן יחד.
    """
    doc = _shaped()
    found = doc_sections.find_sections(doc, "`code`  ו-**bold**")
    assert [s.level for s in found] == [1]
    assert doc_sections.find_sections(doc, "code ו-bold") == []


def test_a_setext_title_that_spans_two_lines_is_found_by_its_flattened_form():
    """ה-``\\n`` שבתוך הכותרת מתקפל לרווח בנרמול, ולכן חיפוש בשורה אחת תופס.

    זו הצורה שהפארסר הזה מזין ל-``doc_sections`` ו-RST אינו מזין
    לעולם: ב-RST כותרת היא תמיד שורה אחת.
    """
    doc = _shaped()
    flat = "כותרת setext שנפרסת על שתי שורות"
    assert doc_sections.normalize_title(flat) == doc_sections.normalize_title(
        "כותרת setext\nשנפרסת על שתי שורות"
    )
    found = doc_sections.find_sections(doc, flat)
    assert len(found) == 1
    # ‏``adornment`` של setext הוא **תו אחד** ולא הקו המלא, כפי שכבר
    # מקובע ב-``test_the_adornment_is_the_markup_of_the_heading``.
    assert found[0].adornment == "-"


def test_section_bounds_and_direct_subsections_agree_on_where_the_child_starts():
    """שתי הפונקציות מתארות את אותו גבול משני צדדים."""
    doc = _shaped()
    setext = doc_sections.find_sections(doc, "כותרת setext שנפרסת על שתי שורות")[0]
    children = doc_sections.direct_subsections(doc, setext)
    assert [c.title for c in children] == ["תת-סעיף"]

    without = doc_sections.section_bounds(doc, setext, False)
    with_kids = doc_sections.section_bounds(doc, setext, True)
    assert without[1] == children[0].heading_line - 1
    assert with_kids[1] == len(doc.lines)
    # הכותרת עצמה נכללת בטווח, כולל שתי שורות הטקסט שלה וקו ה-``---``.
    body = doc_sections.section_text(doc, setext, False)
    assert body.startswith("כותרת setext\nשנפרסת על שתי שורות\n---")


def test_neighbors_walks_the_two_top_level_twos_and_not_the_child():
    """שכנות היא לפי אותו אב ואותה רמה — כאן שתי ה-``##``."""
    doc = _shaped()
    link, setext, child = doc.sections[1], doc.sections[2], doc.sections[3]

    prev, nxt = doc_sections.neighbors(doc, link)
    assert prev is None
    assert nxt is setext

    prev, nxt = doc_sections.neighbors(doc, setext)
    assert prev is link
    assert nxt is None

    # ל-``תת-סעיף`` אין אחים, ולכן שני הצדדים ריקים.
    assert doc_sections.neighbors(doc, child) == (None, None)


def test_build_toc_carries_the_raw_title_and_a_range_that_holds_the_body():
    """ה-TOC הוא מה שיוצג למשתמש, ולכן הכותרת בו היא המקור הגולמי."""
    doc = _shaped()
    toc = doc_sections.build_toc(doc)
    assert [row["title"] for row in toc] == [s.title for s in doc.sections]
    assert [row["level"] for row in toc] == [1, 2, 2, 3]

    child = toc[3]
    assert child["breadcrumb"] == [
        "`code` ו-**bold**",
        "כותרת setext\nשנפרסת על שתי שורות",
        "תת-סעיף",
    ]
    start, end = child["line_range"]
    assert "תוכן ג" in "\n".join(doc.lines[start - 1:end])
    # הגודל נמדד בבייטים של UTF-8, ולכן על עברית הוא גדול ממספר התווים.
    assert child["approx_bytes"] > end - start


def test_suggest_returns_the_title_as_it_was_written_in_the_file():
    """שאילתה שלא נמצאה מקבלת הצעה — והיא חייבת לחזור עם הסימון הגולמי."""
    doc = _shaped()
    assert doc_sections.find_sections(doc, "תת סעיף") == []
    assert "תת-סעיף" in doc_sections.suggest(doc, "תת סעיף")


# ════════════════════════════════════════════════════════════════════
# שתי התקרות — מספר אחד בשני קבצים
# ════════════════════════════════════════════════════════════════════


def test_the_two_ceilings_are_the_same_number():
    """‏``MAX_SECTIONS`` ו-``MAX_SYMBOLS`` מתארים את אותו גבול, ולא נגזרים זה מזה.

    ‏``services`` אינו מייבא מ-``mcp_server`` — הכיוון חד-סטרי ומנומק
    ב-``TooManySections`` — ולכן הערך מוקלד פעמיים, ושתי הפרוזות מפנות
    זו לזו. טסט רשאי לייבא משתי החבילות, וזה המקום היחיד שבו השוויון
    באמת נבדק. בלי הטסט הזה, שינוי באחד מהשניים היה משאיר את השני
    מאחור בשקט — ובדיוק זה מה ששני זוגות המספרים האחרים בענף הזה
    מקובעים מפניו.
    """
    from mcp_server.outline_scanners import _ceiling

    assert md_parser.MAX_SECTIONS == _ceiling.MAX_SYMBOLS
