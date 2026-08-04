"""
בדיקות לכפתור "העתק תוכן הדף" שבאתר התיעוד (docs/_static/copy-page.js).

הקובץ הוא JavaScript שרץ בדפדפן, ולכן הבדיקות כאן משלבות שתי רמות:

1. בדיקות סטטיות – מוודאות שהמנגנונים החשובים לא נמחקו בטעות מהקוד.
2. בדיקות התנהגות – מריצות את פונקציות העזר עצמן דרך Node (אם הוא מותקן),
   כדי לוודא שהפלט באמת נכון ולא רק שהקוד "נראה" נכון.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

# נתיב יחסי לקובץ הבדיקה עצמו, כדי שהבדיקות לא יהיו תלויות בתיקייה שממנה הורצו.
COPY_PAGE_JS = Path(__file__).resolve().parents[1] / "docs" / "_static" / "copy-page.js"


def _read_js() -> str:
    return COPY_PAGE_JS.read_text(encoding="utf-8")


def test_docs_copy_page_uses_webapp_admonition_syntax():
    """
    בדיקה בסיסית כדי לוודא שכפתור "העתק תוכן הדף" בדוקס
    מייצר admonitions בפורמט הווב-אפ (::: type ... :::) ולא בפורמט MkDocs (!!!).
    """
    js = _read_js()
    assert "::: ${type}" in js
    assert "!!!" not in js


def test_mermaid_source_is_captured_before_render():
    """
    ספריית mermaid מוחקת את קוד המקור מה-DOM ושמה במקומו SVG.
    לכן חייבת להיות לכידה מוקדמת של הקוד, אחרת ההעתקה תיקח את טקסט ה-SVG.
    """
    js = _read_js()
    assert "captureMermaidSources" in js, "חסר מנגנון לכידה של קוד המרמייד"
    assert "DOMContentLoaded" in js, "הלכידה חייבת לרוץ לפני שmermaid מרנדר (window load)"
    # הכלל שממיר תרשים ל-Markdown חייב לקרוא מהמקור השמור ולא מה-DOM החי.
    assert "getMermaidSource(node)" in js


def test_mermaid_rule_does_not_fall_back_to_svg_text():
    """
    אם אין מקור שמור והתרשים כבר הומר ל-SVG – עדיף בלוק ריק על פני טקסט זבל.
    """
    js = _read_js()
    assert "isMermaidRendered" in js
    assert "data-processed" in js


def test_code_blocks_use_dynamic_fence():
    """
    בלוק קוד שמכיל בעצמו ``` (למשל דוגמת Markdown של תרשים) חייב גדר ארוכה יותר,
    אחרת ה-fence נסגר באמצע והפלט שבור.
    """
    js = _read_js()
    assert "buildFence" in js
    assert "wrapInFence" in js


# ---------------------------------------------------------------------------
# בדיקות התנהגות – הרצה אמיתית של פונקציות ה-JS דרך Node
# ---------------------------------------------------------------------------

# הקובץ נטען כ-CommonJS, אבל בשורש הפרויקט יש "type": "module",
# ולכן מעתיקים אותו לקובץ .cjs זמני (ב-tmp בלבד) לפני ההרצה.
_NODE_DRIVER = """
const api = require(process.argv[2]);
const cases = JSON.parse(process.argv[3]);
const out = {};
for (const [name, spec] of Object.entries(cases)) {
  out[name] = api[spec.fn](...spec.args);
}
process.stdout.write(JSON.stringify(out));
"""


def _run_js(tmp_path: Path, cases: dict) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js אינו מותקן – מדלגים על בדיקות ההתנהגות")

    module_path = tmp_path / "copy-page.cjs"
    module_path.write_text(_read_js(), encoding="utf-8")
    driver_path = tmp_path / "driver.cjs"
    driver_path.write_text(_NODE_DRIVER, encoding="utf-8")

    result = subprocess.run(
        [node, str(driver_path), str(module_path), json.dumps(cases)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, f"הרצת Node נכשלה: {result.stderr}"
    return json.loads(result.stdout)


def _run_js_script(tmp_path: Path, script: str) -> dict:
    """מריץ סקריפט Node שמקבל את המודול דרך require ומדפיס JSON."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js אינו מותקן – מדלגים על בדיקות ההתנהגות")

    module_path = tmp_path / "copy-page.cjs"
    module_path.write_text(_read_js(), encoding="utf-8")
    script_path = tmp_path / "scenario.cjs"
    script_path.write_text(script, encoding="utf-8")

    result = subprocess.run(
        [node, str(script_path), str(module_path)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, f"הרצת Node נכשלה: {result.stderr}"
    return json.loads(result.stdout)


# סקריפט שמדמה את מחזור החיים האמיתי בדפדפן: קודם ה-DOM מכיל את קוד התרשים,
# ואז mermaid מוחק אותו ושם במקומו SVG. כך אפשר לבדוק שהלכידה באמת מצילה את הקוד.
_MERMAID_SCENARIO = """
const api = require(process.argv[2]);

const makeNode = ({ text = '', rendered = false } = {}) => {
  const attrs = Object.create(null);
  const node = {
    textContent: text,
    getAttribute(name) {
      if (name === 'data-processed') {
        return node.__rendered ? 'true' : null;
      }
      return name in attrs ? attrs[name] : null;
    },
    setAttribute(name, value) {
      attrs[name] = value;
    },
    querySelector(selector) {
      return node.__rendered && selector === 'svg' ? {} : null;
    },
    __rendered: rendered,
    // מדמה את מה ש-mermaid עושה: מוחק את הקוד ומשאיר טקסט של תוויות ה-SVG.
    render(svgText) {
      node.textContent = svgText;
      node.__rendered = true;
    },
  };
  return node;
};

const scopeOf = (nodes) => ({ querySelectorAll: () => nodes });
const out = {};

// (1) המקרה של הבאג: לכידה לפני הרינדור, קריאה אחרי הרינדור.
const captured = makeNode({ text: '\\n        graph TD\\n  A[Bot] --> B[Handlers]\\n    ' });
api.captureMermaidSources(scopeOf([captured]));
captured.render('Telegram BotHandlers');
out.afterRender = api.getMermaidSource(captured);

// (2) תרשים שכבר רונדר ולא נלכד – חייב להחזיר ריק ולא את טקסט ה-SVG.
const renderedOnly = makeNode({ text: 'Telegram BotHandlers', rendered: true });
out.renderedWithoutCapture = api.getMermaidSource(renderedOnly);

// (3) תרשים שטרם רונדר ולא נלכד – נפילה חזרה ל-textContent עם דה-דנט.
const rawOnly = makeNode({ text: '\\n        graph TD\\n  A --> B\\n    ' });
out.unrenderedWithoutCapture = api.getMermaidSource(rawOnly);

// (4) הלכידה עצמה חייבת לדלג על תרשים שכבר רונדר, כדי לא לשמור זבל.
const alreadyRendered = makeNode({ text: 'Telegram BotHandlers', rendered: true });
api.captureMermaidSources(scopeOf([alreadyRendered]));
out.captureSkipsRendered = alreadyRendered.getAttribute('data-copy-page-mermaid-id');

process.stdout.write(JSON.stringify(out));
"""


def test_mermaid_source_survives_render(tmp_path):
    """
    ליבת התיקון: הקוד נלכד לפני ש-mermaid מוחק אותו, ולכן ההעתקה מחזירה
    את קוד התרשים גם אחרי שה-DOM כבר מכיל רק SVG.
    """
    out = _run_js_script(tmp_path, _MERMAID_SCENARIO)
    assert out["afterRender"] == "graph TD\nA[Bot] --> B[Handlers]"
    # הרגרסיה שאנחנו מגנים מפניה: טקסט התוויות המודבק של ה-SVG.
    assert "Telegram BotHandlers" not in out["afterRender"]


def test_mermaid_source_empty_for_rendered_node_without_capture(tmp_path):
    """נפילה בטוחה: בלוק ריק עדיף על טקסט ה-SVG."""
    out = _run_js_script(tmp_path, _MERMAID_SCENARIO)
    assert out["renderedWithoutCapture"] == ""


def test_mermaid_source_falls_back_to_dom_when_not_rendered(tmp_path):
    """אם התרשים עדיין גולמי ב-DOM – מותר ונכון לקרוא ממנו ישירות."""
    out = _run_js_script(tmp_path, _MERMAID_SCENARIO)
    assert out["unrenderedWithoutCapture"] == "graph TD\nA --> B"


def test_capture_skips_already_rendered_nodes(tmp_path):
    """הלכידה לא שומרת טקסט SVG של תרשים שכבר רונדר."""
    out = _run_js_script(tmp_path, _MERMAID_SCENARIO)
    assert out["captureSkipsRendered"] is None


def test_dedent_fixes_sphinx_first_line_indent(tmp_path):
    """
    Sphinx מזיח רק את השורה הראשונה של התרשים (8 רווחים מול 2 בשאר),
    ולכן חישוב מינימום על כל השורות היה משאיר אותה עקומה.
    """
    raw = "\n        graph TD\n  A[Bot] --> B[Handlers]\n  B --> C[Services]\n    "
    out = _run_js(tmp_path, {"r": {"fn": "dedentCodeBlock", "args": [raw]}})["r"]
    assert out == "graph TD\nA[Bot] --> B[Handlers]\nB --> C[Services]"


def test_dedent_preserves_nested_indentation(tmp_path):
    """הזחה פנימית (subgraph) חייבת להישמר – אחרת התרשים מאבד מבנה."""
    raw = (
        "\n        graph TB\n"
        "    subgraph \"Telegram Interface\"\n"
        "        U[User] --> TB[Bot]\n"
        "    end\n    "
    )
    out = _run_js(tmp_path, {"r": {"fn": "dedentCodeBlock", "args": [raw]}})["r"]
    assert out == 'graph TB\nsubgraph "Telegram Interface"\n    U[User] --> TB[Bot]\nend'


def test_dedent_keeps_hierarchy_on_uniform_indent(tmp_path):
    """
    כשההזחה אחידה (השורה הראשונה אינה מוזחת יותר מהשאר) מסירים את המינימום
    מכל השורות – ולא מיישרים את הראשונה לחוד.
    """
    raw = "    flowchart LR\n      A --> B\n      B --> C"
    out = _run_js(tmp_path, {"r": {"fn": "dedentCodeBlock", "args": [raw]}})["r"]
    assert out == "flowchart LR\n  A --> B\n  B --> C"


def test_dedent_handles_empty_and_single_line(tmp_path):
    cases = {
        "empty": {"fn": "dedentCodeBlock", "args": ["   \n\n  "]},
        "single": {"fn": "dedentCodeBlock", "args": ["\n        graph TD\n    "]},
    }
    out = _run_js(tmp_path, cases)
    assert out["empty"] == ""
    assert out["single"] == "graph TD"


def test_build_fence_grows_past_inner_backticks(tmp_path):
    cases = {
        "plain": {"fn": "buildFence", "args": ["flowchart LR"]},
        "three": {"fn": "buildFence", "args": ["```mermaid\nflowchart LR\n```"]},
        "four": {"fn": "buildFence", "args": ["````\nnested\n````"]},
    }
    out = _run_js(tmp_path, cases)
    assert out["plain"] == "```"
    assert out["four"] == "`````"
    assert out["three"] == "````"


def test_wrap_in_fence_keeps_block_closed(tmp_path):
    """הבלוק שמכיל דוגמת ```mermaid חייב להישאר סגור ותקין."""
    code = "```mermaid\nflowchart LR\n  A --> B\n```"
    out = _run_js(tmp_path, {"r": {"fn": "wrapInFence", "args": [code, "markdown"]}})["r"]
    assert out.startswith("\n\n````markdown\n")
    assert out.endswith("\n````\n\n")
    # מספר גדרות בתחילת שורה חייב להיות זוגי, אחרת ה-Markdown שבור.
    fences = [line for line in out.split("\n") if line.startswith("```")]
    assert len(fences) % 2 == 0


def test_wrap_in_fence_handles_empty_and_null_input(tmp_path):
    """
    קלט ריק או null לא אמור להפיל את ההמרה ולא להדפיס "null" בתוך הבלוק,
    והגדר במקרה כזה נשארת בת שלושה גרשיים.
    """
    cases = {
        "empty": {"fn": "wrapInFence", "args": ["", "python"]},
        "null": {"fn": "wrapInFence", "args": [None, ""]},
    }
    out = _run_js(tmp_path, cases)
    assert out["empty"] == "\n\n```python\n\n```\n\n"
    assert out["null"] == "\n\n```\n\n```\n\n"
    assert "null" not in out["null"].replace("\n", "")
    assert "None" not in out["empty"]


def test_wrap_in_fence_trims_only_trailing_whitespace(tmp_path):
    """הזחה מובילה היא חלק מהקוד ואסור למחוק אותה; רק רווחים בסוף נחתכים."""
    out = _run_js(tmp_path, {"r": {"fn": "wrapInFence", "args": ["  A --> B   \n\n", ""]}})["r"]
    assert out == "\n\n```\n  A --> B\n```\n\n"
