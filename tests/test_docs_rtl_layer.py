"""שומר על ההחלטות של כיוון אתר התיעוד (מימין לשמאל).

האתר מקבל ``dir`` על התגית ``html`` מעותק של ``layout.html`` של
sphinx_rtd_theme (``docs/_templates/layout.html``), ו-``docs/_static/custom.css``
מתרגם את הצדדים הקבועים של הערכה למאפיינים לוגיים. שני הדברים נכונים לגרסה
אחת של הערכה, והם נמדדו בדפדפן (Playwright) לפני שנכנסו. הבדיקות כאן לא
מודדות מחדש. הן שומרות שההחלטות לא בוטלו בשקט:

1. הגרסה הנעולה ב-``docs/requirements.txt`` זהה לגרסה שכתובה בראש
   ``layout.html`` ובראש שכבת הכיוון ב-``custom.css``. שדרוג של הערכה מפיל
   את הבדיקה, עד שמעתיקים את התבנית מחדש ומודדים את הערכים.
2. התגית ``html`` בתבנית נושאת ``dir`` מתוך משתנה, ו-``conf.py`` קובע את
   המשתנה הזה ב-``html_context`` ומחבר את הפונקציה ל-``config-inited``. בלי
   החיבור Jinja מרנדר ``dir=""``, והעמוד חוזר משמאל לימין בלי שום אזהרה.
3. ב-``custom.css`` אין ``direction`` ואין ``border-left`` מחוץ לשני מקומות
   מכוונים, ושניהם עדיין שם: ``direction: ltr`` בבלוקי הקוד, ו-``border-left``
   בבלוקים של autodoc, שהפס שלהם נשאר בשמאל בכוונה (החתימה בימין).

הקבצים נקראים כטקסט ו-``conf.py`` נקרא כ-AST, בלי לייבא אותו: הייבוא מריץ קוד
ברמת המודול שמשנה את ``os.environ`` של תהליך הבדיקות. ראו "כיוון האתר" ב-
``docs/doc-authoring.rst``.
"""

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
REQUIREMENTS = DOCS / "requirements.txt"
LAYOUT = DOCS / "_templates" / "layout.html"
CUSTOM_CSS = DOCS / "_static" / "custom.css"
CONF = DOCS / "conf.py"

# ``^`` עם MULTILINE: רק שורת הדרישה עצמה, לא אזכור בהערה
_PIN_RE = re.compile(r"^sphinx-rtd-theme==([0-9][^\s#;]*)", re.MULTILINE)
# הגרסה בהערות של התבנית ושל ה-CSS; נגמרת בספרה או באות, כדי שנקודה של סוף משפט לא תיכנס
_VERSION_RE = re.compile(r"sphinx-rtd-theme==([0-9][0-9A-Za-z.]*[0-9A-Za-z])")
# שורת התגית ולא ``<html[^>]*>``: בתוך התגית יש ``{% if ... >= (7, 2) %}``
_HTML_TAG_LINE_RE = re.compile(r"^<html\b.*$", re.MULTILINE)
_DIR_VAR_RE = re.compile(r'\bdir="\{\{\s*(\w+)\s*\}\}"')

# המקומות היחידים שבהם מותר צד קבוע, לפי הסלקטור כפי שהוא כתוב בקובץ
_DIRECTION_ALLOWED = {".highlight": "ltr", ".literal-block": "ltr"}
_BORDER_LEFT_ALLOWED = ".class, .function, .method"


def _css_rules(css):
    """מחזיר ``(at_rule, selector, [(prop, value), ...])`` לכל כלל, גם בתוך ``@media``."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    rules = []

    def walk(text, at_rule):
        pos = 0
        while True:
            start = text.find("{", pos)
            if start == -1:
                return
            head = " ".join(text[pos:start].split())
            depth, end = 1, start + 1
            while depth:
                if text[end] == "{":
                    depth += 1
                elif text[end] == "}":
                    depth -= 1
                end += 1
            body = text[start + 1:end - 1]
            if head.startswith("@"):
                walk(body, head)
            else:
                parts = (decl.partition(":") for decl in body.split(";"))
                decls = [(prop.strip().lower(), value.strip()) for prop, sep, value in parts if sep]
                rules.append((at_rule, head, decls))
            pos = end

    walk(css, None)
    return rules


def _versions(path):
    return _VERSION_RE.findall(path.read_text(encoding="utf-8"))


def test_the_layout_copy_and_the_rtl_layer_match_the_pinned_theme_version():
    pins = _PIN_RE.findall(REQUIREMENTS.read_text(encoding="utf-8"))
    assert len(pins) == 1, f"צריכה להיות שורת sphinx-rtd-theme אחת ב-docs/requirements.txt, נמצאו {pins}"
    pinned = pins[0]
    copies = {
        "docs/_templates/layout.html": _versions(LAYOUT),
        "docs/_static/custom.css": _versions(CUSTOM_CSS),
    }
    for path, versions in copies.items():
        assert versions == [pinned], (
            f"sphinx-rtd-theme נעול על {pinned}, אבל {path} נכתב ל-{versions or 'גרסה לא מצוינת'}. "
            "בשדרוג הערכה: מעתיקים מחדש את layout.html של הגרסה החדשה ומחזירים את dir, מודדים "
            "מחדש את הערכים בשכבת הכיוון ב-custom.css, ורק אז מעדכנים את הגרסה בשלושת המקומות."
        )


def test_the_html_tag_takes_its_dir_from_the_variable_conf_sets():
    tag_lines = _HTML_TAG_LINE_RE.findall(LAYOUT.read_text(encoding="utf-8"))
    assert len(tag_lines) == 1, f"צריכה להיות שורת <html> אחת ב-layout.html, נמצאו {len(tag_lines)}"
    dir_vars = _DIR_VAR_RE.findall(tag_lines[0])
    assert len(dir_vars) == 1, f"התגית html ב-layout.html צריכה לשאת dir מתוך משתנה: {tag_lines[0]}"
    variable = dir_vars[0]

    tree = ast.parse(CONF.read_text(encoding="utf-8"))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert "_set_text_direction" in functions, "conf.py צריך להגדיר את _set_text_direction"
    keys = [
        key.value
        for node in ast.walk(functions["_set_text_direction"])
        if isinstance(node, ast.Dict)
        for key in node.keys
        if isinstance(key, ast.Constant)
    ]
    assert variable in keys, f"layout.html קורא את {variable!r}, אבל _set_text_direction קובע רק {keys}"

    connects = [
        [arg.value if isinstance(arg, ast.Constant) else getattr(arg, "id", None) for arg in node.args]
        for node in ast.walk(functions["setup"])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "connect"
    ]
    assert ["config-inited", "_set_text_direction"] in connects, (
        f"setup ב-conf.py צריך לחבר את _set_text_direction ל-config-inited. נמצאו: {connects}"
    )


def test_fixed_sides_in_custom_css_stay_only_where_they_are_meant_to():
    rules = _css_rules(CUSTOM_CSS.read_text(encoding="utf-8"))
    offenders = [
        f"{at_rule or ''} {selector} {{ {prop}: {value} }}".strip()
        for at_rule, selector, decls in rules
        for prop, value in decls
        if (prop == "direction" and _DIRECTION_ALLOWED.get(selector) != value)
        or (prop.startswith("border-left") and selector != _BORDER_LEFT_ALLOWED)
    ]
    assert not offenders, (
        "כיוון הדף מגיע מ-dir על התגית html, וב-custom.css כותבים מאפיינים לוגיים "
        "(border-inline-start, margin-inline-start, inset-inline-start). "
        f"נמצא צד קבוע מחוץ למקומות המכוונים: {offenders}"
    )

    declared = {
        (selector, prop)
        for at_rule, selector, decls in rules
        if at_rule is None
        for prop, _value in decls
    }
    for selector in _DIRECTION_ALLOWED:
        assert (selector, "direction") in declared, (
            f"{selector} צריך להישאר direction: ltr, כדי שהקוד יוצג משמאל לימין"
        )
    assert any(
        selector == _BORDER_LEFT_ALLOWED and prop.startswith("border-left") for selector, prop in declared
    ), "הפס של בלוקי autodoc נשאר בשמאל בכוונה, כי החתימה בימין: border-left ולא border-inline-start"
