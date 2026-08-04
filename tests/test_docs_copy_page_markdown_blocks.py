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

COPY_PAGE_JS = Path("docs/_static/copy-page.js")


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
