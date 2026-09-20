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


def test_doc_sections_pulls_no_heavy_modules(tmp_path):
    """ייבוא המודול אינו גורר pymongo/bson/telegram/flask/``database``.

    **בתת-תהליך נקי ולא בתוך ה-session הזה**, כי pytest כבר ייבא חצי מהריפו
    וכל בדיקה בתוך התהליך הזה הייתה מודדת את מה ש-pytest טען ולא את מה
    שהמודול גורר. הכלל עצמו מנומק ב-``mcp_server/__init__.py``:
    ``import database.schemas`` מריץ ``db = DatabaseManager()`` בזמן טעינת
    מודול, כלומר חיבור למונגו.

    **ו-``-B`` ו-``cwd=tmp_path`` אינם קוסמטיקה** — זה בדיוק החיווט
    ש-``tests/test_rst_parser.py`` כבר משתמש בו, וההערה שם מנמקת אותו:
    בלי ``-B`` התת-תהליך כותב ``__pycache__`` לתוך ``services/``, כלומר
    טסט שכותב לעץ המקור, וזה מה שכלל הבטיחות בפרויקט אוסר. ו-``cwd``
    בתיקייה ייחודית לכל ריצה מבודד ריצות מקבילות זו מזו.

    **ולכן ``sys.path.insert`` בתוכנית הוא נתיב מוחלט.** עד עכשיו הייבוא
    עבד רק מפני שה-``cwd`` היה שורש הריפו, כלומר ההסתמכות על עץ המקור
    הייתה גם מה שאפשר את המדידה. הנתיב המוחלט מנתק את השניים, ומאותה
    סיבה הוא נלקח מ-``_ROOT`` ולא מ-``os.getcwd()``.
    """
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(_ROOT)!r})\n"
        "before = set(sys.modules)\n"
        "from services import doc_sections\n"
        "new = set(sys.modules) - before\n"
        "heavy = sorted(m for m in new\n"
        "               if m.split('.')[0] in "
        "{'pymongo', 'bson', 'telegram', 'flask', 'database'})\n"
        "print(','.join(heavy))\n"
    )
    proc = subprocess.run([sys.executable, "-B", "-c", code], cwd=str(tmp_path),
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


def _identified(*titles):
    """מסמך שכל שורה בו היא כותרת — לבדיקות התאמת המזהה."""
    sections = [_section(t, 2, i + 1, adornment="#") for i, t in enumerate(titles)]
    doc_sections._finalize(sections, len(titles) + 1)
    return doc_sections.Document(lines=list(titles) + ["זנב"], sections=sections)


def test_find_sections_is_still_full_equality_and_not_containment():
    """החצי שלא השתנה: הכלה **אינה** התאמה, גם אחרי שנוסף ענף המזהה.

    הענף החדש מתאים מזהה ולא מחרוזת כלשהי, ולכן מילה מתוך הכותרת —
    בתחילתה או באמצעה — ממשיכה להחזיר אפס, בדיוק כמו קודם.
    """
    doc = _identified("K11. כשל שמדווח בערך החזרה נבלע")

    assert doc_sections.find_sections(doc, "כשל") == []
    assert doc_sections.find_sections(doc, "כשל שמדווח") == []
    assert len(doc_sections.find_sections(doc, "  k11.   כשל שמדווח בערך החזרה נבלע ")) == 1


@pytest.mark.parametrize("query", ["K11", "K11.", "k11", "  K11  "])
def test_an_identifier_query_finds_the_heading_that_opens_with_it(query):
    """הזרימה שלשמה הענף נבנה: הסוכן מפנה לפי מזהה, לא לפי הכותרת המלאה.

    ארבע הצורות הן אותו מזהה: עם נקודה ובלעדיה, ברישיות אחרת, ועם רווחים
    מסביב — כי כולן עוברות דרך ``normalize_title`` כמו השוויון המלא.
    """
    doc = _identified("K11. כשל שמדווח בערך החזרה נבלע", "K12. דגל שמרחיב הרשאה")

    (match,) = doc_sections.find_sections(doc, query)
    assert match.title == "K11. כשל שמדווח בערך החזרה נבלע"


def test_full_equality_wins_and_the_identifier_branch_cannot_override_it():
    """סדר מפורש: מה שהמשתמש הקליד הוא מה שהוא ביקש.

    מסמך שיש בו כותרת ששמה **בדיוק** ``K11`` וגם כותרת ``K11. טקסט``
    מחזיר את הראשונה בלבד. מוטציה שמזיזה את הענף לפני השוויון מחזירה
    שתיים ומפילה את זה.
    """
    doc = _identified("K11", "K11. טקסט")

    (match,) = doc_sections.find_sections(doc, "K11")
    assert match.title == "K11"


def test_k1_does_not_catch_k10_through_k15():
    """מבחן הגבול, והסיבה שהמימוש מפרק ולא משווה קידומת.

    ``K1`` הוא תחילית של שישה מזהים אחרים באותו קובץ. כלל שנכתב כ"הכותרת
    מתחילה במחרוזת שביקשת" היה מחזיר כאן **שבע** התאמות במקום אחת — זה
    ``K16`` ב-amir-bug-patterns. מוטציה שמחליפה את שוויון-המזהים
    ב-``startswith`` מפילה את הטסט הזה.
    """
    doc = _identified("K1. ראשון", *[f"K1{d}. טקסט" for d in range(6)])

    (match,) = doc_sections.find_sections(doc, "K1")
    assert match.title == "K1. ראשון"
    assert [s.title for s in doc_sections.find_sections(doc, "K10")] == ["K10. טקסט"]


@pytest.mark.parametrize("query", [
    "איך", "כלל", "ראה",          # מילים נפוצות שהן התחילית של כותרות אמיתיות
    "K", "11", "K-11", "k11x", "KKKK1", "U", "P",   # צורות כמעט-מזהה
])
def test_a_query_that_is_not_an_identifier_never_lights_the_branch(query):
    """השומר, וזה הצד שנמדד רק בסבב השלישי של המדידה.

    בלי הדרישה שהשאילתה **עצמה** תהיה מזהה, ``section="איך"`` היה תופס את
    כל חמש-עשרה הכותרות ``איך זה נראה`` שבקורפוס — כי אחרי ``איך`` בא
    רווח. מוטציה שמסירה את ``_IDENTIFIER_QUERY_RE`` מפילה את זה.
    """
    doc = _identified("איך זה נראה", "כלל לזיהוי", "ראה גם", "K11. טקסט", "P3 — טקסט")

    assert doc_sections.find_sections(doc, query) == []


def test_the_space_format_matches_and_the_full_name_still_works():
    """הפורמט השני בקורפוס — ``P3 — טקסט`` — ובו הגבול הוא רווח ולא נקודה.

    ומצדו השני: ``איך זה נראה`` ממשיך להחזיר את שתי הכפילויות דרך השוויון
    המלא. ההגבלה מכבה את הענף החדש, לא את ההתנהגות הקיימת.
    """
    doc = _identified("P3 — טקסט", "איך זה נראה", "איך זה נראה")

    assert [s.title for s in doc_sections.find_sections(doc, "P3")] == ["P3 — טקסט"]
    assert [s.title for s in doc_sections.find_sections(doc, "P3.")] == ["P3 — טקסט"]
    assert len(doc_sections.find_sections(doc, "איך זה נראה")) == 2


def test_a_dot_that_starts_a_sub_number_is_not_a_boundary():
    """‏``K11`` אינו ``K11.1``, ולכן תת-סעיפים אינם הופכים את המזהה לרב-משמעי.

    **זו אותה מחלקה בדיוק כמו ``K1`` מול ``K10``, רק במסווה של נקודה.**
    הנקודה ב-``K11. טקסט`` **מסיימת** את המזהה, וב-``K11.1 טקסט`` היא
    **מפרידה** בתוך מזהה ארוך יותר. גבול שנבדק כתו בודד בלי לשאול מה בא
    אחריו היה מחזיר כאן שלוש התאמות ו-``ambiguous_section`` — כלומר
    שובר בדיוק את הזרימה שהענף נבנה לתקן, ובקובץ שבו ``suggest`` ממליץ
    להקליד ``K11``.

    וכותרת בתת-מספור לא הולכת לאיבוד: היא נמצאת בשמה המלא, כמו כל כותרת.
    **מוטציה:** הסרת ``(?!\\d)`` מהרגקס מפילה את השורה הראשונה.
    """
    doc = _identified("K11. כשל", "K11.1 תת-סעיף", "K11.2 תת-סעיף")

    assert [s.title for s in doc_sections.find_sections(doc, "K11")] == ["K11. כשל"]
    assert doc_sections.find_sections(doc, "K11.1") == []
    assert len(doc_sections.find_sections(doc, "K11.1 תת-סעיף")) == 1


def test_a_repeated_identifier_returns_every_match():
    """מזהה שאינו ייחודי הוא ``ambiguous_section``, לא ניחוש.

    זה המקרה של ``P1``/``P2``/``P3`` בקובץ שבו הם תוויות עדיפות ולא
    מזהים. המתקשר מקבל את כל המועמדים, בדיוק כמו בכותרת כפולה.
    """
    doc = _identified("P3 — ראשון", "אחר", "P3 — שני")

    assert [s.title_line for s in doc_sections.find_sections(doc, "P3")] == [1, 3]


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

    assert doc_sections.suggest(doc, "Configuraton").titles == ["Configuration"]
    # שאילתה רחוקה מכל כותרת מחזירה רשימה ריקה — ``difflib`` עם ``cutoff=0.5``.
    assert doc_sections.suggest(doc, "זזזז").titles == []


def test_suggest_answers_an_identifier_query_with_the_files_identifiers():
    """ההבטחה "לעולם לא רק \'לא נמצא\'" — שהתנוונה בדיוק במקרה הזה.

    נמדד ש-``suggest("K11")`` ו-``suggest("U3")`` מחזירים רשימה **ריקה**
    דרך ``difflib``, כי ``cutoff=0.5`` אינו מוצא קרבה בין שלושה תווים
    לכותרת עברית ארוכה. המזהים חוזרים **כפי שנכתבו**, כי הסוכן מקליד
    אותם בשאילתה הבאה — מוטציה שמחזירה את הצורה המנורמלת מפילה את זה.
    """
    doc = _identified("K11. כשל", "K12. דגל", "איך זה נראה")

    assert doc_sections.suggest(doc, "K99") == doc_sections.Suggestions(["K11", "K12"], False)
    # ובאותו קובץ: שאילתה שאינה מזהה ואין לה כותרת קרובה מקבלת רשימה ריקה,
    # ולא את המזהים. זה השומר היחיד שנשאר בפונקציה, ולכן הוא נבדק כאן.
    assert doc_sections.suggest(doc, "זזזז").titles == []


def test_suggest_keeps_difflib_when_the_file_carries_no_identifiers():
    """התנאי השני, והוא מה ששומר על כל מסלול ה-RST ללא שינוי.

    **וכותרת ``H2O`` אינה קישוט.** הגרסה הראשונה של הטסט הזה בדקה שקובץ
    בלי מזהים מחזיר רשימה ריקה לשאילתה ``K99`` — ו**מוטציה שמסירה את
    התנאי עברה אותה בשקט**, כי שני המסלולים מחזירים ריק כשאין מזהים ואין
    כותרת קרובה. מה שמבדיל ביניהם הוא כותרת שאינה מזהה אבל ``difflib``
    כן מוצא אותה: ``H2O`` אינו מזהה (אחרי ``H2`` באה אות ולא גבול), והוא
    קרוב מספיק ל-``H2`` כדי לחזור כהצעה. מוטציה שמסירה את התנאי מחזירה
    כאן רשימה ריקה ונופלת.
    """
    doc = _identified("H2O", "Deployment")

    assert doc_sections.suggest(doc, "H2").titles == ["H2O"]
    assert doc_sections.suggest(doc, "Deploymen").titles == ["Deployment"]


def test_suggest_prefers_a_close_title_over_the_identifier_list():
    """‏``difflib`` קודם — ורשימת המזהים היא מוצא אחרון, לא ברירת מחדל.

    **מחרוזת יכולה להיות בצורת מזהה בלי להיות מזהה במסמך הזה.** ``H2``
    עובר את שומר הצורה, ובקובץ שיש בו ולו מזהה אחד הסדר ההפוך היה מחזיר
    לו את רשימת המזהים — ``["K11"]`` — במקום את הכותרת ``H2O`` שיושבת
    באותו קובץ ונמדדה כקרובה אליו (יחס 0.8). תשובה שאינה קשורה לשאלה
    גרועה מתשובה ריקה.

    **ומה שלא השתנה:** כששום כותרת אינה קרובה, הרשימה עדיין חוזרת —
    זה מה שהטסט שמעל בודק. **מוטציה:** החזרת מסלול המזהים לראש הפונקציה
    מפילה את זה.
    """
    doc = _identified("K11. כשל שמדווח בערך החזרה נבלע", "H2O")

    assert doc_sections.suggest(doc, "H2").titles == ["H2O"]
    # ובאותו קובץ בדיוק, שאילתת מזהה שאין לה כותרת קרובה — הרשימה כן חוזרת.
    assert doc_sections.suggest(doc, "K99").titles == ["K11"]


def test_suggest_caps_the_identifier_list_and_says_that_it_cut():
    """התקרה נבדקת בהתנהגות, ולא רק בקיום הקבוע.

    **שתי תקרות, ושתיהן נבדקות כאן.** ``n`` הוא מה שהקורא ביקש, ו-
    ``MAX_IDENTIFIER_SUGGESTIONS`` הוא הגבול שהוא אינו יכול לחרוג ממנו;
    מה שנאכף הוא הקטן מביניהם. קורא שמבקש 100 מקבל 50, וקורא שמבקש 2
    מקבל 2 — גם כשבקובץ יש עשרות. הצורה השבורה שהייתה כאן קודם אכפה את
    הקבוע בלבד והתעלמה מ-``n`` לגמרי.

    ובכל אחד מהמקרים **הדגל אומר את האמת**: דלוק כשנחתך, כבוי כשלא.
    """
    over = _identified(*[f"K{i}. טקסט" for i in range(1, 52)])

    # הקורא מבקש יותר מהגבול ← הגבול מנצח
    cut = doc_sections.suggest(over, "Z9", n=100)
    assert len(cut.titles) == doc_sections.MAX_IDENTIFIER_SUGGESTIONS == 50
    assert cut.truncated is True

    # הקורא מבקש פחות מהגבול ← הבקשה מנצחת
    asked_two = doc_sections.suggest(over, "Z9", n=2)
    assert len(asked_two.titles) == 2, "‏n אינו נאכף במסלול המזהים"
    assert asked_two.truncated is True

    # וברירת המחדל היא מה שסוכן דרך הכלי מקבל בפועל
    default = doc_sections.suggest(over, "Z9")
    assert len(default.titles) == doc_sections.DEFAULT_SUGGESTIONS == 5
    assert default.truncated is True

    under = _identified(*[f"K{i}. טקסט" for i in range(1, 16)])
    whole = doc_sections.suggest(under, "Z9", n=100)
    assert len(whole.titles) == 15 and whole.truncated is False


def test_suggest_returns_a_two_field_namedtuple_and_not_a_list():
    """שינוי החוזה נבדק במפורש, כדי שלא יהיה שקט.

    קורא ישן שכתב ``for t in suggest(...)`` מקבל **טאפל של שני איברים**
    ולא את הכותרות — הלולאה לא תזרוק, היא פשוט תרוץ על משהו אחר. הטסט
    מקבע את הצורה שהקורא החדש אמור לצרוך.
    """
    doc = _identified("Configuration")
    result = doc_sections.suggest(doc, "Configuraton")

    assert isinstance(result, tuple) and len(result) == 2
    assert result.titles == ["Configuration"] and result.truncated is False
    assert list(result) == [["Configuration"], False]


def test_direct_subsections_returns_children_only_and_not_grandchildren(tree_doc):
    father = tree_doc.sections[0]
    assert [s.title for s in doc_sections.direct_subsections(tree_doc, father)] == ["בן א", "בן ב"]


def test_suggest_says_that_the_difflib_list_was_cut_too():
    """הדגל אומר "היו עוד" גם במסלול הכותרות, ולא רק במסלול המזהים.

    **זה היה חצי-מיושם, והחצי החסר הוא בדיוק מה שהדגל נולד למנוע.**
    ``truncated`` נוסף כדי שרשימה חתוכה לא תיראה שלמה — ובאותה פונקציה,
    החיתוך של ``difflib`` ב-``n`` המשיך להחזיר ``False``. עמוד עם עשר
    כותרות קרובות החזיר חמש, ולא אמר דבר.

    שני הכיוונים נבדקים: ``n`` קטן מהמספר שנמצא ← נחתך והדגל דלוק;
    ``n`` גדול ממנו ← הכול חוזר והדגל כבוי. השני הוא מה שמונע דגל
    שדלוק תמיד, שהוא חסר-משמעות באותה מידה.
    """
    doc = _identified(*[f"מסלול שמירה מספר {i}" for i in range(10)])

    cut = doc_sections.suggest(doc, "מסלול שמירה מספר", n=5)
    assert len(cut.titles) == 5
    assert cut.truncated is True, "חיתוך ב-difflib נשאר שקט"

    whole = doc_sections.suggest(doc, "מסלול שמירה מספר", n=100)
    assert len(whole.titles) == 10 and whole.truncated is False


def test_suggest_on_a_document_with_no_headings_returns_empty_instead_of_raising():
    """מסמך בלי כותרות מחזיר רשימה ריקה — ולא ``ValueError``.

    **זה מסלול חריגה שהתיקון עצמו יצר, ונתפס בקריאת המקור של ``difflib``.**
    כדי לדעת ש-``difflib`` חתך, הפונקציה מבקשת ממנו את **כל** ההתאמות —
    ``n=len(norm_map)``. ובמסמך בלי כותרות זה ``n=0``, ו-``get_close_matches``
    פותח ב-``if not n > 0: raise ValueError``. כלומר במקום
    ``section_not_found`` היה חוזר 500 מכלי MCP ציבורי, במסלול שאין בו
    ``try``.

    בקורפוס ה-RST אין קובץ בלי כותרות, אבל קובץ Markdown שכולו פרוזה הוא
    בדיוק המקרה — והמודול הזה נבנה לשני הפארסרים.
    """
    empty = doc_sections.Document(lines=["סתם פסקה", "ועוד אחת"], sections=[])

    assert doc_sections.suggest(empty, "K11") == doc_sections.Suggestions([], False)
    assert doc_sections.suggest(empty, "כל טקסט אחר") == doc_sections.Suggestions([], False)


def test_a_query_with_a_trailing_dot_matches_a_heading_that_is_only_the_identifier():
    """הענף ה-``\\Z`` של הרגקס — הגבול שמגיעים אליו רק מכיוון אחד.

    הכותרת ``K11`` (בלי נקודה, בלי טקסט אחריה) מסתיימת מיד אחרי המזהה,
    ולכן ההתאמה נסמכת על ``\\Z`` ולא על נקודה או רווח. ומכיוון שהשאילתה
    ``K11.`` נושאת נקודה אופציונלית שמוסרת בנרמול, היא אותו מזהה בדיוק.
    זה המקרה היחיד שמפעיל את החלופה הזאת, ובלי טסט עליה כל שינוי בגבול
    היה עובר בלי סימן.
    """
    doc = _identified("K11", "K12. טקסט")

    assert [s.title for s in doc_sections.find_sections(doc, "K11.")] == ["K11"]
    assert [s.title for s in doc_sections.find_sections(doc, "K11")] == ["K11"]
    # ומהצד השני: הנקודה בשאילתה אינה הופכת אותה למזהה אחר
    assert [s.title for s in doc_sections.find_sections(doc, "K12.")] == ["K12. טקסט"]


@pytest.mark.parametrize("count, expected, cut", [(49, 49, False), (50, 50, False), (51, 50, True)])
def test_the_identifier_ceiling_is_exact_at_fifty(count, expected, cut):
    """התקרה נבדקת **על** הגבול ולא סביבו — 49, 50 ו-51.

    ההשוואה בקוד היא ``>``, ולכן 50 בדיוק חוזר שלם והדגל כבוי; 51 נחתך
    ל-50 והדגל דלוק. מוטציה שמחליפה ל-``>=`` נראית זהה בכל מספר אחר
    ונופלת כאן בלבד.

    ‏``n=100`` כדי להגיע לגבול הזה בכלל: מאז ש-``n`` נאכף גם במסלול
    המזהים, ברירת המחדל חוסמת הרבה לפניו.
    """
    doc = _identified(*[f"K{i}. טקסט" for i in range(1, count + 1)])

    result = doc_sections.suggest(doc, "Z9", n=100)

    assert len(result.titles) == expected
    assert result.truncated is cut


@pytest.mark.parametrize("too_long", ["K1234", "K1234.", "ABCD1", "K1234 טקסט"])
def test_four_digits_or_four_letters_are_not_an_identifier(too_long):
    """גבול הספירה, משני צדדיו — גם כשאילתה וגם ככותרת.

    הצורה היא עד שלוש אותיות ועד שלוש ספרות. בלי טסט על הגבול, הרחבה
    שגויה של הכמות הייתה משנה אילו כותרות נתפסות בלי ששום דבר יצעק.
    """
    assert doc_sections._identifier_query(too_long) is None
    assert doc_sections._leading_identifier(too_long) is None


@pytest.mark.parametrize("arabic_indic", ["K\u0661\u0661", "K\u06f1\u06f2", "U\u0663"])
def test_non_ascii_digits_are_not_an_identifier(arabic_indic):
    """‏``[0-9]`` ולא ``\\d`` — ספרה ערבית-הודית אינה ספרה כאן.

    ‏``\\d`` ב-Python תופס כל ספרה עשרונית ביוניקוד, ולכן השאילתה הזאת
    הייתה מסווגת כמזהה ונשלחת למסלול המזהים — שם היא יכולה רק להחזיר
    רשימה שאינה קשורה לשאלה, כי אף כותרת אינה כתובה בספרות כאלה.

    הספרות כתובות כרצפי ``\\u`` ולא כתווים, כדי שמי שקורא את המקור יראה
    בדיוק מה נבדק.
    """
    assert doc_sections._identifier_query(arabic_indic) is None


def test_a_bidi_mark_does_not_hide_a_heading_from_either_lookup():
    """סימן כיווניות אינו מסתיר כותרת — לא בשמה המלא ולא לפי המזהה.

    **זה רלוונטי בדיוק בריפו הזה:** הפרוזה העברית כאן מציבה סימן
    ימין-לשמאל סביב אסימונים לטיניים, וכותב הכותרת אינו רואה אותו.
    ``str.strip()`` אינו מסיר אותו, ולכן לפני התיקון כותרת כזו יצאה מכל
    מסלולי החיפוש בבת אחת.

    **והטסט בודק את החומר שלו לפני שהוא נשען עליו — וזה לא קישוט.**
    הגרסה הראשונה של הטסט הזה נכתבה עם הסימן **כתו ממשי** במקור, בניגוד
    לדוקסטרינג של עצמה. הנזק אינו אסתטי: אם התו נעלם — עורך, העתקה, כלי
    שמנקה רווחים — הוא נעלם **גם מהקלט וגם מערך הציפייה**, וכל האסרשנים
    ממשיכים לעבור. כלומר הכיסוי מתאדה בלי שאף אחד ידע, והטסט מפסיק להיות
    מסוגל ליפול על הדבר שהוא נועד לבדוק. זה בדיוק מה ש-
    ``BY-STACK/hebrew-source.md`` מזהיר מפניו.

    לכן הסימן מוגדר **פעם אחת כרצף בריחה**, ושתי השורות הראשונות בגוף
    מאמתות שהוא באמת מה שחשבנו ושהוא באמת נכנס לנתונים. מחיקה של התו
    מהמקור אינה יכולה לפגוע בקבוע — הוא נבנה מרצף, לא ממחרוזת ליטרלית.
    """
    import unicodedata

    RLM = "\u200f"
    assert unicodedata.category(RLM) == "Cf", "הקבוע אינו תו פורמט — המקור שונה"

    marked = RLM + "K11. כשל שמדווח בערך החזרה"
    assert RLM in marked, "הסימן לא נכנס לנתוני הטסט"

    doc = _identified(marked, "K12. אחר")

    # הכותרת נמצאת בשמה המלא — גם כשהשואל לא הקליד את הסימן
    found = doc_sections.find_sections(doc, "K11. כשל שמדווח בערך החזרה")
    assert [s.title for s in found] == [marked]

    # וגם לפי המזהה
    assert [s.title for s in doc_sections.find_sections(doc, "K11")] == [marked]

    # ומהכיוון ההפוך: הסימן בשאילתה אינו מסתיר כותרת נקייה
    assert [s.title for s in doc_sections.find_sections(doc, RLM + "K12")] == ["K12. אחר"]
    assert doc_sections._identifier_query(RLM + "K12") == "k12"

    # **והכותרת חוזרת לקורא כטקסט המקור, עם הסימן.** הנרמול מייצר מפתח
    # השוואה בלבד; מי שיחזיר את הצורה המנורמלת ישנה את מה שהסוכן רואה.
    assert found[0].title == marked
