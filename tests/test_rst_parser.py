"""טסטים לפארסר ה-RST — על קבצי RST אמיתיים מהריפו + מקרי קצה סינתטיים ממוקדים."""

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
