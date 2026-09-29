"""טבלת סוגי החיפוש בתיעוד היא עותק של הרשימה הנפתחת בממשק — והטסט הזה משווה ביניהן.

``docs/webapp/global-search.rst`` מתעד, בסעיף ``global-search-types``, כל סוג
חיפוש עם התווית שהמשתמש רואה והערך שנשלח לשרת. הרשימה עצמה חיה במקום אחר:
``<select id="searchType">`` ב-``webapp/templates/files.html``. שני העותקים
נכונים ביום הכתיבה, והם נסחפים בתיקון הבא שנזכר רק באחד מהם
(``RECURRING-PATTERNS.md`` R6 ב-amir-bug-patterns).

**הרשימה נגזרת מהתבנית ולא מ-``SearchType``.** ה-enum מכיל את מה שהמנוע
מכיר; הממשק מכיל את מה שהמשתמש יכול לבחור, והתיעוד מתאר את הממשק. גזירה
מה-enum הייתה מאמתת את המפרט ולא את הצרכן (``TESTING-PATTERNS.md`` T1).
"""

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "webapp" / "templates" / "files.html"
PAGE = ROOT / "docs" / "webapp" / "global-search.rst"
SECTION_ID = "global-search-types"


class _SearchTypeOptions(HTMLParser):
    """אוסף את ה-``<option>`` שבתוך ``<select id="searchType">`` בלבד."""

    def __init__(self) -> None:
        super().__init__()
        self.options: dict[str, str] = {}
        self._in_select = False
        self._value: str | None = None
        self._label: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "select" and attrs.get("id") == "searchType":
            self._in_select = True
        elif tag == "option" and self._in_select:
            self._value = attrs.get("value")
            self._label = []

    def handle_data(self, data):
        if self._value is not None:
            self._label.append(data)

    def handle_endtag(self, tag):
        if tag == "option" and self._value is not None:
            self.options[self._value] = "".join(self._label).strip()
            self._value = None
        elif tag == "select" and self._in_select:
            self._in_select = False


def _ui_search_types(template: Path = TEMPLATE) -> dict[str, str]:
    """ערך ← תווית, כמו שהמשתמש רואה אותם ברשימה הנפתחת."""
    parser = _SearchTypeOptions()
    parser.feed(template.read_text(encoding="utf-8"))
    return parser.options


_ROW_START = re.compile(r"^(?P<indent>\s*)\* - (?P<cell>.*)$")
_CELL = re.compile(r"^\s+- (?P<cell>.*)$")
_LITERAL = re.compile(r"^``(?P<value>[^`]+)``$")
_HEADER_ROWS = re.compile(r"^\s+:header-rows:\s*(?P<n>\d+)\s*$")


def _documented_search_types(page: Path = PAGE) -> dict[str, str]:
    """ערך ← תווית, מתוך ה-``list-table`` הראשון אחרי העוגן ``global-search-types``.

    **בלי docutils, בכוונה.** CI מתקין רק את ``requirements/development.txt``,
    ו-docutils אינו נמשך ממנו — ולכן טסט עם ``importorskip("docutils")`` היה
    מדולג שם בשקט, והשמירה מפני סחיפה לא הייתה קיימת בדיוק במקום שבו היא
    נחוצה. הפרסור כאן מכיר רק את מה שהטבלה הזו משתמשת בו: שורה שנפתחת
    ב-``* -``, תאים שנפתחים ב-``-``, ו-``:header-rows:``.
    """
    lines = page.read_text(encoding="utf-8").splitlines()
    anchor = f".. _{SECTION_ID}:"
    assert anchor in lines, f"אין עוגן {anchor!r} ב-{page.name}"
    i = lines.index(anchor)
    while i < len(lines) and not lines[i].startswith(".. list-table::"):
        i += 1
    assert i < len(lines), f"אין list-table אחרי העוגן {SECTION_ID!r}"

    header_rows = 0
    rows: list[list[str]] = []
    for line in lines[i + 1:]:
        if line and not line[0].isspace():
            break  # שורה בלי הזחה — ה-directive נגמר
        if m := _HEADER_ROWS.match(line):
            header_rows = int(m["n"])
        elif m := _ROW_START.match(line):
            rows.append([m["cell"].strip()])
        elif rows and (m := _CELL.match(line)):
            rows[-1].append(m["cell"].strip())

    documented: dict[str, str] = {}
    for row in rows[header_rows:]:
        assert len(row) >= 2, f"שורה בלי עמודת ערך: {row!r}"
        literal = _LITERAL.match(row[1])
        assert literal, f"בשורה {row[0]!r} הערך אינו ``code span``: {row[1]!r}"
        documented[literal["value"]] = row[0]
    return documented


def _drift(ui: dict[str, str], documented: dict[str, str]) -> list[str]:
    """כל הפערים בין הממשק לתיעוד, בניסוח שאומר מה לתקן."""
    problems: list[str] = []
    for value in sorted(ui.keys() - documented.keys()):
        problems.append(f"בממשק ואינו מתועד: {value!r} ({ui[value]})")
    for value in sorted(documented.keys() - ui.keys()):
        problems.append(f"מתועד ואינו בממשק: {value!r} ({documented[value]})")
    for value in sorted(ui.keys() & documented.keys()):
        if ui[value] != documented[value]:
            problems.append(
                f"תווית שונה עבור {value!r}: בממשק {ui[value]!r}, בתיעוד {documented[value]!r}"
            )
    return problems


def test_the_documented_search_types_are_the_ones_the_dropdown_offers():
    """כל סוג ברשימה הנפתחת מתועד, עם אותה תווית — ואין בתיעוד סוג שאינו בה."""
    ui = _ui_search_types()
    documented = _documented_search_types()

    # רשימה ריקה היא כישלון ולא מעבר: הפרסור איבד את מה שהוא מודד.
    assert ui, "לא נמצאו אפשרויות ב-<select id=\"searchType\"> — הפרסור של התבנית איבד את הרשימה"
    assert documented, "לא נמצאו שורות בטבלת סוגי החיפוש — הפרסור של העמוד איבד את הטבלה"

    problems = _drift(ui, documented)
    assert not problems, (
        "הטבלה ב-docs/webapp/global-search.rst (סעיף global-search-types) אינה תואמת "
        "את <select id=\"searchType\"> ב-webapp/templates/files.html:\n  " + "\n  ".join(problems)
    )


def _mutate(src: Path, dst_dir: Path, old: str, new: str) -> Path:
    text = src.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"המוטציה צריכה מופע יחיד של {old!r} ב-{src.name}"
    dst = dst_dir / src.name
    dst.write_text(text.replace(old, new), encoding="utf-8")
    return dst


@pytest.mark.parametrize(
    "target, old, new, expected",
    [
        # תווית שהשתנתה בתיעוד בלבד
        ("page", "   * - מטושטש\n", "   * - התאמה משוערת\n", "תווית שונה עבור 'fuzzy'"),
        # שורה שנמחקה מהתיעוד
        (
            "page",
            "   * - פונקציות\n     - ``function``\n"
            "     - שמות פונקציות שחולצו מהקוד\n     - השאילתה מופיעה בתוך שם הפונקציה\n",
            "",
            "בממשק ואינו מתועד: 'function'",
        ),
        # אפשרות שנוספה לממשק בלי תיעוד
        (
            "template",
            '<option value="function">פונקציות</option>',
            '<option value="function">פונקציות</option>\n              <option value="exact">מדויק</option>',
            "בממשק ואינו מתועד: 'exact'",
        ),
    ],
    ids=["label-renamed-in-docs", "row-removed-from-docs", "option-added-to-ui"],
)
def test_the_comparison_catches_each_kind_of_drift(tmp_path, target, old, new, expected):
    """אותה השוואה, על עותק שסחף — חייבת לדווח עליו.

    בלי זה אין הבדל בין "התיעוד תואם" לבין "ההשוואה לא מסוגלת לראות פער".
    """
    page, template = PAGE, TEMPLATE
    if target == "page":
        page = _mutate(PAGE, tmp_path, old, new)
    else:
        template = _mutate(TEMPLATE, tmp_path, old, new)

    problems = _drift(_ui_search_types(template), _documented_search_types(page))

    assert any(expected in p for p in problems), problems
