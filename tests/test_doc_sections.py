"""טסטים ל-``services/doc_sections.py`` — המודל המשותף של סעיפי מסמך.

**למה יש כאן טסטים מבניים ולא רק התנהגותיים.** ה-PR שיצר את המודול הזה הוא
ריפקטור טהור, וההוכחה המרכזית שלו היא **אפס-דיף** מדוד
(``scripts/docs_section_zero_diff.py``) — כלומר ``docs_get_section`` מחזיר את
אותם בייטים בדיוק על כל 208 קובצי ה-RST, לפני ואחרי. אפס-דיף מוכיח שההווה לא
נשבר; הוא **אינו** מוכיח שהמבנה יישאר. שלוש הדרכים שבהן הריפקטור הזה יכול
להתפרק מחר הן בדיוק אלה שאין להן שום ביטוי בפלט של היום:

1. מישהו יגדיר מחדש פונקציה שעברה, במקום לייבא אותה — ואז יש **שתי הגדרות**
   לאותו כלל, והן יסטו בשקט.
2. מישהו "ינקה" את הייצוא-מחדש ב-``rst_parser``, ואז ``rst_parser.Section``
   יפסיק להיות **אותו אובייקט** — מה ששובר ``except`` וטסטים שמחליפים אותו.
3. מישהו יוסיף ל-``doc_sections`` ייבוא של פארסר, והמודול יפסיק להיות
   בלתי-תלוי-בשפה — כלומר יאבד את כל הסיבה שבגללה הוא נוצר.

שלושתם נבדקים כאן על ה**מקור**, לא על ההתנהגות — מאותו נימוק שכתוב
ב-``tests/test_rst_parser.py`` ליד השומר שעובר על ה-AST: התנהגות אפשר לבדוק
רק במסלול שכבר קיים, ומה שצריך לתפוס הוא המסלול שעוד לא נכתב.

**והטסטים ההתנהגותיים כאן בונים ``Section`` ביד ולא דרך פארסר.** זו לא
נוחות: ``tests/test_rst_parser.py`` כבר בודק את המודל דרך RST, וטסט שני
שיעשה את אותו דבר היה בודק את הפארסר פעמיים ואת המודול אף פעם. הבנייה
הישירה היא בדיוק הממשק שדרכו פארסר — כל פארסר, גם זה שטרם נכתב — משתמש
במודול הזה.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from mcp_server import docs_handlers
from services import doc_sections, rst_parser

_ROOT = Path(__file__).resolve().parents[1]
_DOC_SECTIONS_SRC = _ROOT / "services" / "doc_sections.py"
_RST_PARSER_SRC = _ROOT / "services" / "rst_parser.py"


def _top_level_names(path: Path) -> set[str]:
    """שמות שהקובץ **מגדיר** ברמה העליונה — לא שמות שהוא מייבא."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


# ---------------------------------------------------------------------------
# שומרי המבנה — שלוש דרכי הפירוק שאין להן ביטוי בפלט
# ---------------------------------------------------------------------------


def test_moved_names_have_exactly_one_definition():
    """אף שם שעבר ל-``doc_sections`` אינו מוגדר שוב ב-``rst_parser``.

    זו ההבטחה שכל המודול נבנה בשבילה: הגדרה אחת לכל כלל. הכשל שהיא חוסמת
    שקט לחלוטין — הגדרה מקומית ב-``rst_parser`` הייתה **מסתירה** את זו
    שמיובאת, בלי שגיאת ייבוא ובלי טסט נופל, ומאותו רגע תיקון באחת מהן לא
    היה מגיע לשנייה.
    """
    moved = _top_level_names(_DOC_SECTIONS_SRC)
    redefined = moved & _top_level_names(_RST_PARSER_SRC)
    assert not redefined, f"הוגדרו מחדש ב-rst_parser במקום להיות מיובאים: {sorted(redefined)}"


def test_reexport_is_the_same_object_and_not_a_copy():
    """``rst_parser.X is doc_sections.X`` לכל שם שעבר.

    **זהות, ולא שוויון, וזה ההבדל שמחזיק את הייצור.**
    ``mcp_server/outline_scanners/rst.py`` תופס
    ``except rst_parser.TooManySections``, ו-``parse_document`` מרימה את זו
    של ``doc_sections``. אם השתיים היו שני אובייקטי מחלקה שונים — למשל
    כי מישהו יגדיר מחדש במקום לייבא — ה-``except`` היה **מפספס**, והחריגה
    הייתה עולה מהסורק במקום להיהפך ל-``too_many_symbols``.
    """
    for name in rst_parser.__all__:
        if name == "parse_document":
            continue  # מוגדר ב-rst_parser עצמו, ואינו ייצוא-מחדש
        assert getattr(rst_parser, name) is getattr(doc_sections, name), (
            f"rst_parser.{name} אינו אותו אובייקט כמו doc_sections.{name}"
        )


def test_doc_sections_imports_no_parser_and_no_mcp():
    """הכיוון חד-סטרי: המודל אינו יודע על אף פארסר ועל אף חלק מ-MCP.

    ברגע שהמודול הזה ייבא פארסר הוא מפסיק להיות בלתי-תלוי-בשפה, ופארסר
    שני לא יוכל להישען עליו בלי לגרור את הראשון. וייבוא מ-``mcp_server``
    היה הופך את הכיוון להדדי — ``services`` אינו מייבא מ-``mcp_server``.

    **והבדיקה אוספת גם את השמות המיובאים ולא רק את שם המודול.** הגרסה
    הראשונה שלה בדקה את ``node.module`` בלבד, ולכן ``from services import
    rst_parser`` — שהוא **בדיוק הסגנון הנהוג בריפו**, ולכן הצורה הסבירה
    ביותר שמישהו יכתוב — התחמק ממנה: שם המודול שם הוא ``services``, והפארסר
    יושב ב-``names``. נמדד: המוטציה הזאת עברה את הבדיקה, ונתפסה רק במקרה
    על ידי ייבוא מעגלי שהפיל טסט אחר.
    """
    tree = ast.parse(_DOC_SECTIONS_SRC.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or "." * node.level
            imported.append(base)
            imported += [f"{base}.{a.name}" for a in node.names]

    offenders = [m for m in imported
                 if "parser" in m or m.split(".")[0] in {"mcp_server", "database"}]
    assert not offenders, f"doc_sections מייבא מה שאסור לו: {offenders}"


def test_doc_sections_pulls_no_heavy_modules():
    """ייבוא המודול אינו גורר pymongo/bson/telegram/flask/``database``.

    **בתת-תהליך נקי ולא בתוך ה-session הזה**, כי pytest כבר ייבא חצי מהריפו
    וכל בדיקה בתוך התהליך הזה הייתה מודדת את מה ש-pytest טען ולא את מה
    שהמודול גורר. הכלל עצמו מנומק ב-``mcp_server/__init__.py``:
    ``import database.schemas`` מריץ ``db = DatabaseManager()`` בזמן טעינת
    מודול, כלומר חיבור למונגו.
    """
    code = (
        "import sys\n"
        "before = set(sys.modules)\n"
        "from services import doc_sections\n"
        "new = set(sys.modules) - before\n"
        "heavy = sorted(m for m in new\n"
        "               if m.split('.')[0] in "
        "{'pymongo', 'bson', 'telegram', 'flask', 'database'})\n"
        "print(','.join(heavy))\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], cwd=str(_ROOT),
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "", f"נגררו מודולים כבדים: {proc.stdout.strip()}"


def test_every_name_the_handler_uses_survives_the_reexport():
    """כל ``rst_parser.<attr>`` ש-``docs_handlers`` כותב באמת קיים.

    **נגזר מהמקור של הצרכן ולא מרשימה מוקלדת**, כי רשימה מוקלדת היא בדיוק
    המקום השני לסנכרן: מי שיוסיף מחר קריאה ל-``rst_parser.section_bounds``
    ב-handler לא יעדכן רשימה בטסט, והשומר היה ממשיך לדווח ירוק על משטח
    שכבר אינו מכוסה.
    """
    tree = ast.parse(Path(docs_handlers.__file__).read_text(encoding="utf-8"))
    used = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "rst_parser"
    }
    assert used, "לא נמצאה אף גישה ל-rst_parser ב-docs_handlers — הבדיקה איבדה את הנושא שלה"
    missing = [name for name in sorted(used) if not hasattr(rst_parser, name)]
    assert not missing, f"docs_handlers קורא לשמות שאינם קיימים ב-rst_parser: {missing}"


# ---------------------------------------------------------------------------
# המודל עצמו — נבנה ביד, בלי אף פארסר
# ---------------------------------------------------------------------------


def _section(title, level, line, adornment="="):
    """``Section`` שטוח; ``end_line`` מקבל ערך זמני ש-``_finalize`` דורס."""
    return doc_sections.Section(
        title=title, level=level, title_line=line, heading_line=line,
        end_line=0, adornment=adornment,
    )


@pytest.fixture
def tree_doc():
    """מסמך בן שש שורות עם עץ של שלוש רמות, בנוי ביד.

    המבנה::

        1  אב            (רמה 1)
        2  בן א          (רמה 2)
        3  נכד           (רמה 3)
        4  בן ב          (רמה 2)
        5  אב שני        (רמה 1)
        6  זנב
    """
    sections = [
        _section("אב", 1, 1),
        _section("בן א", 2, 2),
        _section("נכד", 3, 3),
        _section("בן ב", 2, 4),
        _section("אב שני", 1, 5),
    ]
    lines = ["אב", "בן א", "נכד", "בן ב", "אב שני", "זנב"]
    doc_sections._finalize(sections, len(lines))
    return doc_sections.Document(lines=lines, sections=sections)


def test_finalize_ends_a_section_before_the_next_one_at_its_level_or_above(tree_doc):
    ends = {s.title: s.end_line for s in tree_doc.sections}
    assert ends["נכד"] == 3, "הנכד חייב להיגמר לפני 'בן ב', שרמתו גבוהה ממנו"
    assert ends["בן א"] == 3, "'בן א' נגמר לפני 'בן ב' — אותה רמה"
    assert ends["אב"] == 4, "'אב' נגמר לפני 'אב שני' — אותה רמה"
    assert ends["אב שני"] == 6, "האחרון נמתח עד סוף המסמך"


def test_finalize_builds_parents_children_and_breadcrumb(tree_doc):
    by_title = {s.title: s for s in tree_doc.sections}
    assert by_title["אב"].parent is None
    assert by_title["נכד"].breadcrumb == ["אב", "בן א", "נכד"]
    assert [tree_doc.sections[c].title for c in by_title["אב"].children] == ["בן א", "בן ב"]
    assert [tree_doc.sections[c].title for c in by_title["בן א"].children] == ["נכד"]


def test_section_bounds_stops_before_the_first_child_without_subsections(tree_doc):
    father = tree_doc.sections[0]
    assert doc_sections.section_bounds(tree_doc, father, include_subsections=True) == (1, 4)
    assert doc_sections.section_bounds(tree_doc, father, include_subsections=False) == (1, 1)
    # לסעיף בלי ילדים שתי הצורות זהות — אין מה לקצץ.
    leaf = tree_doc.sections[2]
    assert (doc_sections.section_bounds(tree_doc, leaf, include_subsections=False)
            == doc_sections.section_bounds(tree_doc, leaf, include_subsections=True))


def test_section_text_cuts_from_the_documents_own_lines(tree_doc):
    father = tree_doc.sections[0]
    assert doc_sections.section_text(tree_doc, father, True) == "אב\nבן א\nנכד\nבן ב"
    assert doc_sections.section_text(tree_doc, father, False) == "אב"


def test_neighbors_are_siblings_under_the_same_parent(tree_doc):
    by_title = {s.title: s for s in tree_doc.sections}
    prev, nxt = doc_sections.neighbors(tree_doc, by_title["בן א"])
    assert prev is None and nxt.title == "בן ב"
    # הנכד הוא ילד יחיד — אין לו אף שכן, ובוודאי לא 'בן ב' שהוא דוד שלו.
    assert doc_sections.neighbors(tree_doc, by_title["נכד"]) == (None, None)
    prev_root, nxt_root = doc_sections.neighbors(tree_doc, by_title["אב שני"])
    assert prev_root.title == "אב" and nxt_root is None


def test_build_toc_measures_bytes_and_not_characters():
    """``approx_bytes`` הוא בייטים, וזה נבדק דווקא על עברית.

    באנגלית תו הוא בייט אחד ושתי היחידות זהות, ולכן מדידה שגויה הייתה
    עוברת כל בדיקה שנכתבה באנגלית. זו המחלקה שמתוארת ב-``H6``
    ב-amir-bug-patterns; כאן היחידה הנכונה היא **בייטים**, כי הערך הזה
    משרת את תקציב הבתים של התשובה ולא ספירת תווים.
    """
    sections = [_section("שלום", 1, 1)]
    lines = ["שלום", "עולם"]
    doc_sections._finalize(sections, len(lines))
    doc = doc_sections.Document(lines=lines, sections=sections)

    (item,) = doc_sections.build_toc(doc)
    assert item["approx_bytes"] == len("שלום\nעולם".encode("utf-8")) == 17
    assert item["approx_bytes"] != len("שלום\nעולם"), "נמדדו תווים במקום בייטים"
    assert item["line_range"] == [1, 2]
    assert item["level"] == 1 and item["breadcrumb"] == ["שלום"]


@pytest.mark.parametrize("query, expected", [
    ("  רווחים   כפולים  ", "רווחים כפולים"),   # strip + כיווץ רווחים
    ("MiXeD Case", "mixed case"),                # casefold
    ("מקף—ארוך", "מקף-ארוך"),               # em dash → מקף אחיד
    ("מקף‐רגיל", "מקף-רגיל"),               # hyphen → מקף אחיד
])
def test_normalize_title_applies_all_three_rules(query, expected):
    assert doc_sections.normalize_title(query) == expected


def test_find_sections_is_full_equality_after_normalization():
    """שוויון מלא, **לא הכלה** — וזה החוזה שהמדידה קיבעה.

    ``section="K11"`` על כותרת ``K11. טקסט`` מחזיר **אפס** היום. התאמת
    המזהה היא PR נפרד בתוכנית, והטסט הזה הוא מה שיראה כשההתנהגות תשתנה.
    """
    sections = [_section("K11. כשל שמדווח בערך החזרה נבלע", 1, 1)]
    doc_sections._finalize(sections, 2)
    doc = doc_sections.Document(lines=["K11. כשל שמדווח בערך החזרה נבלע", "גוף"],
                                sections=sections)

    assert doc_sections.find_sections(doc, "K11") == []
    assert doc_sections.find_sections(doc, "K11.") == []
    assert len(doc_sections.find_sections(doc, "  k11.   כשל שמדווח בערך החזרה נבלע ")) == 1


def test_find_sections_returns_every_duplicate_and_not_the_first():
    sections = [_section("ראה גם", 2, 1), _section("אחר", 2, 2), _section("ראה גם", 2, 3)]
    doc_sections._finalize(sections, 4)
    doc = doc_sections.Document(lines=["ראה גם", "אחר", "ראה גם", "זנב"], sections=sections)

    matches = doc_sections.find_sections(doc, "ראה גם")
    assert [s.title_line for s in matches] == [1, 3], "כפילות חייבת לחזור במלואה"


def test_suggest_returns_close_titles_and_never_the_query_itself():
    sections = [_section("Configuration", 1, 1), _section("Deployment", 1, 2)]
    doc_sections._finalize(sections, 3)
    doc = doc_sections.Document(lines=["Configuration", "Deployment", "x"], sections=sections)

    assert doc_sections.suggest(doc, "Configuraton") == ["Configuration"]
    # שאילתה רחוקה מכל כותרת מחזירה רשימה ריקה — ``difflib`` עם ``cutoff=0.5``.
    assert doc_sections.suggest(doc, "זזזז") == []


def test_direct_subsections_returns_children_only_and_not_grandchildren(tree_doc):
    father = tree_doc.sections[0]
    assert [s.title for s in doc_sections.direct_subsections(tree_doc, father)] == ["בן א", "בן ב"]
