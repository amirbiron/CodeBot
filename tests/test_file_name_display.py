"""שם קובץ בשורה עברית, בצד השרת — ``webapp/file_name_display.py`` מול התאום שלו, ``utils/file-name.js``.

שני המימושים חייבים להחליט אותו דבר: עמוד שהשרת בונה (רשימת הקבצים, הכותרת של עמוד הקובץ) ועמוד שה-JS בונה
(החיפוש, האוספים) מציגים את אותו שם, ושם שמפורק באחד ולא בשני היה מוצג פעם כך ופעם אחרת. לכן הטסטים כאן מריצים את
ה-JS האמיתי דרך node ומשווים — על רשימת שמות, על כל תו ביוניקוד, ועל המבנה של ה-``<bdi>``.

ומעבר להשוואה: הפילטר ``file_name`` רשום על האפליקציה, הוא מקודד את השם, וכל מקום בתבניות שמציג שם קובץ של
המשתמש כטקסט עובר דרכו.

מה שלא נבדק כאן — שהשם באמת מוצג נכון על המסך — נמדד בכרומיום ב-``tests/test_file_name_display_browser.py``.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

from webapp.file_name_display import (
    HEBREW_LETTERS,
    LATIN_LETTERS,
    TEMPLATE_FILTERS,
    file_name_html,
    file_name_parts,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
JS_MODULE = REPO_ROOT / "webapp" / "static" / "js" / "utils" / "file-name.js"
TEMPLATES = REPO_ROOT / "webapp" / "templates"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node לא זמין להרצת קוד הצד-לקוח")

#: שמות שמכסים את כל הענפים של ההחלטה — אותם מקרים כמו ב-``tests/file-name.test.js``, ועוד כמה שנוגעים בקידוד.
NAMES = [
    "מדריך-תצוגת-Markdown-RTL.md", "חילוץ-חיבור-וואטסאפ-myAgent.md", "הצעת-דפוס-tagName-מול-SVG.md",
    "Report-דוח-Q3.md", "דוח-Q3.json", "אתר-התיעוד-RTL-דוח-שלב-1.md", "המיפוי השלם בייבוא ערכת VS Code.md",
    "תפריט-café.md", "דוח-\U00010780.md", "ערכות.md", "הפניות-שלא-חלו.md", "pdf-עברי-ל-markdown-אפיון-גרסה-ראשונה.md",
    "morass-Tech-theme.json", "archive.tar.gz", "foo()", "--flag", "דוח.tar.gz", "גרסה-1.2.md", "מדריך-RTL.v2.md",
    "docs/מדריך/Guide-RTL.md", "docs/מדריך/קובץ.md", "תיקייה\\Guide-RTL.md", "דוח-RTL.", "דוח-RTL.mdabcdefghi",
    "דוח-RTL.mdabcdefgh", "דוח-RTL.m d", "דוח-RTL.קובץ", "דוח-RTL.7z", "דוח-RTL.md\n", "התקינו את Node.js",
    "_draft.md", "2026-סיכום.md", "", '<b>"x"&מדריך-A.md', "<script>alert(1)</script>.md", "שם'עם'גרש-A.md",
    # שמות שמתחילים באות לטינית ורובם עברית — הגרסה הראשונה של התיקון (``dir="auto"``) הפכה אותם.
    "pdf-עברי-ל-markdown-אפיון-גרסה-ראשונה.md", "Handoff: שרשורי תגובות על פתקים — סשן 2.md", "My README עברית.md",
]

#: ``parts``, ``element`` (על DOM מינימלי) והטבלאות של ה-JS — כ-JSON. ``process.argv[1]`` ולא ``[2]``: ב-``node -e``
#: אין משבצת לשם קובץ סקריפט (כמו ב-``tests/test_file_size_display.py``).
_NAMES_HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const sb = { window: {} };
vm.createContext(sb);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), sb);
const F = sb.window.FileName;
const text = (v) => ({ nodeType: 3, nodeValue: String(v) });
const doc = {
  createTextNode: text,
  createElement(tag) {
    return { nodeType: 1, tag, attrs: {}, kids: [],
      setAttribute(k, v) { this.attrs[k] = String(v); },
      appendChild(c) { this.kids.push(c); return c; },
      set textContent(v) { this.kids = String(v) === '' ? [] : [text(v)]; } };
  },
};
const tree = (n) => n.nodeType === 3 ? n.nodeValue : [n.tag, n.attrs, n.kids.map(tree)];
const names = JSON.parse(process.argv[2]);
process.stdout.write(JSON.stringify({
  parts: names.map((s) => { const p = F.parts(s); return p ? [p.stem, p.extension] : null; }),
  trees: names.map((s) => tree(F.element(s, doc))),
  hebrew: F.HEBREW_LETTERS, latin: F.LATIN_LETTERS,
}));
"""

#: לכל נקודת קוד, הכיוון של ה-``<bdi>`` של ``"a" + התו`` (שם בלי סיומת, ולכן בלי פירוק): ``r`` ל-``rtl`` ו-``a`` ל-``auto``.
_DIR_HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const sb = { window: {} };
vm.createContext(sb);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), sb);
const F = sb.window.FileName;
const doc = { createTextNode: (v) => ({ v }), createElement() { return { attrs: {}, setAttribute(k, v) { this.attrs[k] = v; },
  appendChild() {}, set textContent(_v) {} }; } };
let out = '';
for (let c = 0; c <= 0x10FFFF; c++) {
  if (c >= 0xD800 && c <= 0xDFFF) { out += '-'; continue; }
  out += F.element('a' + String.fromCodePoint(c), doc).attrs.dir === 'rtl' ? 'r' : 'a';
}
process.stdout.write(out);
"""

#: לכל נקודת קוד, שני שמות: ``א`` + התו + ``.md`` (האם התו נחשב אות לטינית אחרי העברית — וגם נקודה ולוכסן), והתו +
#: ``a.md`` (האם התו נחשב אות עברית). התשובה — שורת ``0``/``1`` לכל שם, ו-``-`` לתחום ה-surrogates.
_CODE_POINTS_HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const sb = { window: {} };
vm.createContext(sb);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), sb);
const F = sb.window.FileName;
let after = '', before = '';
for (let c = 0; c <= 0x10FFFF; c++) {
  if (c >= 0xD800 && c <= 0xDFFF) { after += '-'; before += '-'; continue; }
  const ch = String.fromCodePoint(c);
  after += F.parts('א' + ch + '.md') ? '1' : '0';
  before += F.parts(ch + 'a.md') ? '1' : '0';
}
process.stdout.write(after + '\n' + before);
"""


def _node(harness: str, *args: str) -> str:
    result = subprocess.run(
        ["node", "-e", harness, "--", str(JS_MODULE), *args],
        capture_output=True, text=True, timeout=120, check=False,
    )
    assert result.returncode == 0, f"node נכשל:\n{result.stderr}"
    return result.stdout


class _Tree(HTMLParser):
    """ה-HTML שהפילטר בונה, כעץ באותה צורה ש-``tree`` ב-harness מחזיר: ``[tag, attrs, kids]`` וטקסט כמחרוזת."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root: list = ["root", {}, []]
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = [tag, {k: v or "" for k, v in attrs}, []]
        self.stack[-1][2].append(node)
        self.stack.append(node)

    def handle_endtag(self, tag):
        assert self.stack[-1][0] == tag, (self.stack[-1][0], tag)
        self.stack.pop()

    def handle_data(self, data):
        kids = self.stack[-1][2]
        if kids and isinstance(kids[-1], str):
            kids[-1] += data
        else:
            kids.append(data)


def _python_tree(name: str):
    parser = _Tree()
    parser.feed(str(file_name_html(name)))
    parser.close()
    assert len(parser.root[2]) == 1, parser.root
    return parser.root[2][0]


# ---------------------------------------------------------------- ההחלטה


@needs_node
def test_python_and_javascript_split_the_same_names():
    js = json.loads(_node(_NAMES_HARNESS, json.dumps(NAMES)))
    py = [list(p) if p else None for p in map(file_name_parts, NAMES)]
    assert py == js["parts"]


@needs_node
def test_python_and_javascript_agree_on_every_code_point():
    """התו שאחרי העברית (לטיני או לא) והתו שלפני הלטיני (עברי או לא), לכל נקודת קוד ביוניקוד. כך גם טבלה שנסחפה
    בשורה אחת, או לולאה שעוברת לפי יחידות UTF-16 במקום נקודות קוד, נתפסות — לא רק השמות שברשימה."""
    js_after, js_before = _node(_CODE_POINTS_HARNESS).split("\n")
    py_after, py_before = [], []
    for code_point in range(0x110000):
        if 0xD800 <= code_point <= 0xDFFF:
            py_after.append("-")
            py_before.append("-")
            continue
        char = chr(code_point)
        py_after.append("1" if file_name_parts("א" + char + ".md") else "0")
        py_before.append("1" if file_name_parts(char + "a.md") else "0")
    for label, js, py in (("אחרי העברית", js_after, "".join(py_after)), ("לפני הלטיני", js_before, "".join(py_before))):
        diff = [f"U+{i:04X}" for i, (a, b) in enumerate(zip(js, py)) if a != b]
        assert len(js) == len(py) == 0x110000, label
        assert not diff, f"{label}: JS ופייתון מחליטים אחרת על {len(diff)} תווים: {diff[:20]}"


@needs_node
def test_python_and_javascript_give_every_code_point_the_same_direction():
    """``rtl`` לשם שיש בו אות עברית, ``auto`` לשם בלי — לכל נקודת קוד, בשני המימושים."""
    js = _node(_DIR_HARNESS)
    py = []
    for code_point in range(0x110000):
        if 0xD800 <= code_point <= 0xDFFF:
            py.append("-")
            continue
        py.append("r" if 'dir="rtl"' in str(file_name_html("a" + chr(code_point))) else "a")
    py_text = "".join(py)
    diff = [f"U+{i:04X}" for i, (a, b) in enumerate(zip(js, py_text)) if a != b]
    assert len(js) == len(py_text) == 0x110000
    assert not diff, f"JS ופייתון נותנים כיוון אחר ל-{len(diff)} תווים: {diff[:20]}"
    assert py_text.count("r") == sum(end - start + 1 for start, end in HEBREW_LETTERS), "rtl בדיוק לאותיות העבריות"


@needs_node
def test_the_two_tables_are_the_same_numbers():
    js = json.loads(_node(_NAMES_HARNESS, "[]"))
    assert [list(r) for r in HEBREW_LETTERS] == js["hebrew"]
    assert [list(r) for r in LATIN_LETTERS] == js["latin"]


# ---------------------------------------------------------------- ה-HTML


@needs_node
def test_the_filter_builds_the_same_bdi_as_the_javascript():
    js = json.loads(_node(_NAMES_HARNESS, json.dumps(NAMES)))
    for name, js_tree in zip(NAMES, js["trees"]):
        assert _python_tree(name) == js_tree, name


@pytest.mark.parametrize(
    "name, expected",
    [
        ("מדריך-תצוגת-Markdown-RTL.md", '<bdi dir="rtl">מדריך-תצוגת-Markdown-RTL.<bdi>md</bdi></bdi>'),
        ("ערכות.md", '<bdi dir="rtl">ערכות.md</bdi>'),
        ("pdf-עברי-ל-markdown-אפיון-גרסה-ראשונה.md", '<bdi dir="rtl">pdf-עברי-ל-markdown-אפיון-גרסה-ראשונה.md</bdi>'),
        ("README.md", '<bdi dir="auto">README.md</bdi>'),
        (None, '<bdi dir="auto"></bdi>'),
        ('<b>"x"&מדריך-A.md', '<bdi dir="rtl">&lt;b&gt;&#34;x&#34;&amp;מדריך-A.<bdi>md</bdi></bdi>'),
        ("<script>alert(1)</script>.md", '<bdi dir="auto">&lt;script&gt;alert(1)&lt;/script&gt;.md</bdi>'),
    ],
)
def test_the_filter_output(name, expected):
    """המבנה, וקידוד של כל ערך — השם הוא קלט של משתמש, ו-``Markup.format`` מקודד אותו."""
    assert str(file_name_html(name)) == expected


def test_the_text_of_the_bdi_is_the_name_exactly():
    """בלי רווחים ובלי תווים נסתרים בין החלקים — העתקה והטקסט של האלמנט מחזירים את השם."""
    for name in NAMES:
        tree = _python_tree(name)
        flat = "".join(k if isinstance(k, str) else "".join(k[2]) for k in tree[2])
        assert flat == name, name


# ---------------------------------------------------------------- החיווט


def test_the_filter_is_registered_on_the_app():
    import webapp.app as webapp_app

    for name, func in TEMPLATE_FILTERS.items():
        assert webapp_app.app.jinja_env.filters.get(name) is func, name


class _VisibleText(HTMLParser):
    """הטקסט הגלוי של תבנית — בלי מאפיינים, בלי ``<script>``, ``<style>`` ו-``<title>``."""

    SKIP = {"script", "style", "title"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.depth = 0
        self.chunks: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if not self.depth:
            self.chunks.append(data)


#: התבניות שמציגות שם קובץ של המשתמש בשרת (המיפוי של ה-PR, נובמבר 2026).
SERVER_TEMPLATES = [
    "files.html", "view_file.html", "md_preview.html", "html_preview.html", "svg_preview.html", "compare.html",
    "trash.html", "dashboard.html",
]


@pytest.mark.parametrize("template_name", SERVER_TEMPLATES)
def test_every_visible_file_name_in_the_template_goes_through_the_filter(template_name):
    """``{{ ….file_name }}`` בטקסט גלוי בלי ``|file_name`` היה מציג שם עברי שנגמר בחלק לטיני עם הסיומת באמצע. מאפיינים
    (``title``, ``data-*``, ``alt``), ``<title>`` ו-JS אינם טקסט גלוי, ושם אי אפשר תגיות — הם נשארים כמו שהם."""
    source = (TEMPLATES / template_name).read_text(encoding="utf-8")
    source = re.sub(r"\{#.*?#\}", "", source, flags=re.S)
    source = re.sub(r"\{%\s*block title\s*%\}.*?\{%\s*endblock\s*%\}", "", source, flags=re.S)
    parser = _VisibleText()
    parser.feed(source)
    parser.close()
    unfiltered = [
        expr for chunk in parser.chunks
        for expr in re.findall(r"\{\{[^}]*\}\}", chunk)
        if re.search(r"\bfile_?name\b", expr) and "|file_name" not in expr.replace(" ", "")
    ]
    assert not unfiltered, unfiltered


def test_the_reader_mode_title_goes_through_the_filter():
    """במצב קריאה הכותרת היא שם הקובץ (``title=file_name`` בשני הראוטים שמרנדרים את ``reader_mode.html``)."""
    source = (TEMPLATES / "reader_mode.html").read_text(encoding="utf-8")
    assert '<h1 class="reader-title">{{ title|file_name }}</h1>' in source
