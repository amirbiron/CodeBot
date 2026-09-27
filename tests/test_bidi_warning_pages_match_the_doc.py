"""הרשימות בתיעוד של איפה מוצגת אזהרה על תווי כיווניות, ואיפה עוד לא — מול הקוד.

``docs/quality/code-normalization.md`` מונה, בסעיף על תווים שמשנים את סדר
התצוגה, את הראוטים בוובאפ שמציגים אזהרה ואת אלה שעוד לא. חלק מזה נגזר מהקוד:
ראוט מזהיר כשהוא קורא ל-``_bidi_warning_for_highlighted_code``. רשימה שמוקלדת
ביד מתיישנת בשקט — הגרסה הקודמת של העמוד מנתה רק חלק מהמקומות בלי אזהרה, ואיש
לא ידע. לכן הטסט גוזר את הקוראים מ-``webapp/app.py`` ומשווה.

לכל ראוט שהעמוד כותב כשם של פונקציה ומיד אחריו הכתובת בסוגריים, כמו
`` `view_file` (`/file/<file_id>`) ``:

- בסעיף "איפה מוצגת אזהרה" — השמות הם בדיוק הראוטים שקוראים לפונקציה.
- בסעיף "איפה עדיין אין אזהרה" — הראוט קיים, ואינו קורא לה.
- בשניהם — הכתובת היא אחת מאלה שב-``@app.route`` של הפונקציה.

**מה הטסט לא תופס:** עמוד חדש שמציג קוד שמור ולא נכתב באף רשימה. "מציג קוד
שמור" אינו משהו שאפשר לגזור מהקוד, ולכן העמוד אומר את זה במפורש. והוא סופר
רק קריאה ישירה מתוך הראוט: ראוט שיקרא לפונקציה דרך פונקציית עזר ייראה לו
כראוט בלי אזהרה, והטסט ייפול עד שיעדכנו אותו — בקול, לא בשקט.

הסריקה היא על ה-AST ולא על הטקסט, כמו ב-``tests/test_content_cleaning_stays_in_the_bot.py``,
כדי שהערה או מחרוזת שמזכירות את השם לא ייספרו כקריאה.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "quality" / "code-normalization.md"
APP = ROOT / "webapp" / "app.py"
BANNER = "_bidi_warning_for_highlighted_code"
WARNS_HEADING = "### איפה מוצגת אזהרה"
NO_WARNING_HEADING = "### איפה עדיין אין אזהרה"

#: ראוט כמו שהעמוד כותב אותו: שם הפונקציה, ומיד אחריו הכתובת בסוגריים.
_ROUTE_IN_PROSE = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)` \(`(/[^`]*)`\)")


def _section(text: str, heading: str) -> str:
    """השורות שבין הכותרת לכותרת הבאה, מכל רמה."""
    lines = text.split("\n")
    assert heading in lines, f"הכותרת {heading!r} לא נמצאה ב-{DOC.relative_to(ROOT)}"
    body: List[str] = []
    for line in lines[lines.index(heading) + 1 :]:
        if line.startswith("#"):
            break
        body.append(line)
    return "\n".join(body)


def _routes_in(section: str) -> List[Tuple[str, str]]:
    return _ROUTE_IN_PROSE.findall(section)


def _app_routes(tree: ast.Module) -> Dict[str, Set[str]]:
    """לכל פונקציה עם ``@app.route`` — הכתובות שבדקורטורים שלה."""
    routes: Dict[str, Set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr == "route"
                and isinstance(dec.func.value, ast.Name)
                and dec.func.value.id == "app"
                and dec.args
                and isinstance(dec.args[0], ast.Constant)
                and isinstance(dec.args[0].value, str)
            ):
                routes.setdefault(node.name, set()).add(dec.args[0].value)
    return routes


def _calls(node: ast.AST, name: str) -> bool:
    for inner in ast.walk(node):
        if isinstance(inner, ast.Call):
            func = inner.func
            if isinstance(func, ast.Name) and func.id == name:
                return True
            if isinstance(func, ast.Attribute) and func.attr == name:
                return True
    return False


def _routes_that_call(tree: ast.Module, name: str) -> Set[str]:
    routes = _app_routes(tree)
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in routes
        and _calls(node, name)
    }


def _load() -> Tuple[str, Dict[str, Set[str]], Set[str]]:
    tree = ast.parse(APP.read_text(encoding="utf-8"), filename=str(APP))
    return DOC.read_text(encoding="utf-8"), _app_routes(tree), _routes_that_call(tree, BANNER)


def _wrong_urls(pairs: List[Tuple[str, str]], routes: Dict[str, Set[str]]) -> List[str]:
    problems = []
    for name, url in pairs:
        if name not in routes:
            problems.append(f"{name}: אין ב-webapp/app.py פונקציה עם @app.route בשם הזה")
        elif url not in routes[name]:
            problems.append(f"{name}: הכתובת {url} אינה אחת מ-{sorted(routes[name])}")
    return problems


def test_the_doc_names_exactly_the_routes_that_show_the_warning():
    text, routes, warn = _load()
    assert warn, f"אף ראוט לא קורא ל-{BANNER} — הסריקה איבדה את מה שהיא מודדת"
    listed = _routes_in(_section(text, WARNS_HEADING))
    documented = {name for name, _url in listed}
    assert documented == warn, (
        f"בתיעוד: {sorted(documented)}. בקוד, הראוטים שקוראים ל-{BANNER}: {sorted(warn)}. "
        "ראוט שנוסף לו או ירד ממנו הבאנר עובר בין שתי הרשימות בסעיף."
    )
    assert not _wrong_urls(listed, routes), "\n".join(_wrong_urls(listed, routes))


def test_every_route_the_doc_lists_without_a_warning_exists_and_does_not_show_it():
    text, routes, warn = _load()
    listed = _routes_in(_section(text, NO_WARNING_HEADING))
    assert listed, "לא נמצא אף ראוט בצורה `שם` (`/כתובת`) בסעיף — הטסט איבד את מה שהוא בודק"
    problems = _wrong_urls(listed, routes)
    problems += [
        f"{name}: קורא ל-{BANNER}, כלומר כבר מזהיר — המקום שלו ב\"איפה מוצגת אזהרה\""
        for name, _url in listed
        if name in warn
    ]
    assert not problems, "\n".join(problems)


def test_the_scanners_catch_what_they_claim_to():
    """בלי זה, סורק שבור היה מחזיר קבוצות ריקות ששוות זו לזו — ירוק על כלום."""
    source = (
        "@app.route('/a/<x>')\n"
        "def a(x):\n"
        "    return render(warning=_bidi_warning_for_highlighted_code(code, lexer))\n"
        "\n"
        "@app.route('/b')\n"
        "@app.route('/b/<y>')\n"
        "def b(y=None):\n"
        "    # _bidi_warning_for_highlighted_code is not called here\n"
        "    return '_bidi_warning_for_highlighted_code'\n"
        "\n"
        "@bp.route('/c')\n"
        "def c():\n"
        "    return _bidi_warning_for_highlighted_code(code, lexer)\n"
    )
    tree = ast.parse(source)
    assert _app_routes(tree) == {"a": {"/a/<x>"}, "b": {"/b", "/b/<y>"}}
    assert _routes_that_call(tree, BANNER) == {"a"}

    prose = "- `view_file` (`/file/<file_id>`) — תצוגה; ו-`public_share` עם `?view=md`, ו-`x` (`?q`)."
    assert _routes_in(prose) == [("view_file", "/file/<file_id>")]
