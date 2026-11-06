"""
Styled HTML Export Service
ייצוא קבצי Markdown כ-HTML מעוצב עם ערכות נושא

🔒 אבטחה:
- כל HTML עובר sanitization דרך bleach למניעת XSS
- מותרים רק תגיות ו-attributes ברשימה לבנה
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
import xml.etree.ElementTree as etree
from string import Template
from typing import TYPE_CHECKING, NamedTuple, Optional

import bleach
import markdown
from markdown.blockprocessors import BlockProcessor
from markdown.extensions import Extension
from markdown.util import AtomicString, nearing_recursion_limit

if TYPE_CHECKING:  # pragma: no cover
    from markdown.blockparser import BlockParser

# Pygments for dynamic syntax highlighting CSS
try:
    from pygments.formatters import HtmlFormatter
    from pygments.styles import get_style_by_name

    HAS_PYGMENTS = True
except ImportError:  # pragma: no cover
    HtmlFormatter = None  # type: ignore[assignment, misc]
    get_style_by_name = None  # type: ignore[assignment]
    HAS_PYGMENTS = False

from services.theme_parser_service import (
    FALLBACK_DARK,
    FALLBACK_LIGHT,
    generate_hljs_css_from_tokens,
    generate_pygments_css_from_tokens,
    parse_vscode_theme,
    rebase_hljs_css,
)
from services.theme_presets_service import get_preset_by_id, list_presets

logger = logging.getLogger(__name__)


# ============================================
# 🎨 מיפוי ערכות נושא ל-Pygments Styles
# ============================================
# מיפוי בין מזהי ערכות הנושא שלנו לבין styles מובנים של Pygments
# אם ערכה לא נמצאת כאן, נשתמש ב-style ברירת מחדל לפי סוג הערכה (dark/light)

THEME_TO_PYGMENTS_STYLE: dict[str, str] = {
    # Dark themes
    "tech-guide-dark": "monokai",
    "github-dark": "github-dark",
    "dracula": "dracula",
    "one-dark": "one-dark",
    "monokai": "monokai",
    "gruvbox-dark": "gruvbox-dark",
    "nord": "nord",
    "tokyo-night": "monokai",
    "material-dark": "material",
    "synthwave": "monokai",
    "cyberpunk": "monokai",
    # Light themes
    "clean-light": "default",
    "github-light": "github-dark",  # github-dark works well for light too
    "minimal": "default",
    "solarized-light": "solarized-light",
    "gruvbox-light": "gruvbox-light",
}

# Fallback styles לפי קטגוריה
PYGMENTS_STYLE_DARK_FALLBACK = "monokai"
PYGMENTS_STYLE_LIGHT_FALLBACK = "default"

# ============================================
# 🔒 Sanitization policy (shared)
# ============================================

# רשימה לבנה של תגיות מותרות
ALLOWED_TAGS = list(bleach.sanitizer.ALLOWED_TAGS) + [
    "div",
    "span",
    "p",
    "br",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "pre",
    "code",
    "img",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "blockquote",
    "ul",
    "ol",
    "li",
    "hr",
    "a",
    "b",
    "i",
    "strong",
    "em",
    "del",
    "ins",
    "sup",
    "sub",
    "mark",
    "nav",  # עבור TOC wrapper
    "details",  # עבור ::: details
    "summary",
]

# רשימה לבנה של attributes מותרים
ALLOWED_ATTRS = {
    "*": ["class", "id"],  # id נדרש עבור anchors של TOC
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "title", "width", "height"],
    "th": ["colspan", "rowspan"],
    "td": ["colspan", "rowspan"],
    "code": ["class"],  # עבור codehilite language classes
    "span": ["class"],  # עבור syntax highlighting
    "pre": ["class"],
}

# פרוטוקולים מותרים (חוסם javascript:, data: וכו')
ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


# ============================================
# 📦 מכולות ::: — תיבות הסבר ו-details
# ============================================
# התחביר נקבע בוובאפ: ``md_preview.html`` ו-``live-preview.js`` רושמים את
# ``markdown-it-container`` לכל סוג, והתוויות של הסוגים יושבות ב-
# ``webapp/static/js/admonition-icons.js``. הייצוא רץ בשרת, ב-Python-Markdown,
# ולכן הטבלה כאן היא עותק של הרשימה ההיא. ``tests/test_styled_export_containers_parity.py``
# משווה אותה לשלושת המקורות, כך שסוג שנוסף בוובאפ ולא כאן מפיל את ה-CI
# במקום לצאת בייצוא כטקסט גולמי.


class AdmonitionType(NamedTuple):
    """סוג של תיבת הסבר בייצוא."""

    css_class: str  # מחלקת הצבע בתבנית הייצוא: ``alert-<css_class>``
    title: str  # הכותרת כשלא נכתבה כותרת — ``ADMONITION_TITLES`` ב-admonition-icons.js


#: סוג ← (צבע בייצוא, כותרת ברירת מחדל). הצבעים הולכים אחרי הקבוצות של
#: ``markdown-enhanced.css`` בוובאפ, ככל שלתבנית הייצוא יש צבע מתאים: לסגול של
#: ``important`` ו-``question`` אין מקבילה בערכות הייצוא, ולכן שניהם ``warning``,
#: כמו ש-``important`` היה בייצוא תמיד. הקבוצה האפורה של הוובאפ היא ``neutral``.
ADMONITION_TYPES: dict[str, AdmonitionType] = {
    "note": AdmonitionType("info", "הערה"),
    "info": AdmonitionType("info", "מידע"),
    "example": AdmonitionType("info", "דוגמה"),
    "todo": AdmonitionType("info", "משימות לביצוע"),
    "tip": AdmonitionType("success", "טיפ"),
    "success": AdmonitionType("success", "הצלחה"),
    "warning": AdmonitionType("warning", "אזהרה"),
    "experimental": AdmonitionType("warning", "ניסוי"),
    "important": AdmonitionType("warning", "חשוב"),
    "question": AdmonitionType("warning", "שאלה"),
    "danger": AdmonitionType("danger", "סכנה"),
    "quote": AdmonitionType("neutral", "ציטוט"),
    "deprecated": AdmonitionType("neutral", "לא מומלץ"),
    "abstract": AdmonitionType("neutral", "תקציר"),
}

#: הכותרת של ``::: details`` שלא נכתבה לו כותרת — ``DETAILS_DEFAULT_TITLE``
#: ב-admonition-icons.js. ``details`` אינו תיבת הסבר, ולכן הוא לא בטבלה שמעל.
DETAILS_DEFAULT_TITLE = "לחץ להצגה"

#: כמה מכולות אפשר לקנן זו בתוך זו. שורת פתיחה עמוקה יותר נשארת טקסט.
#: זה המספר של הוובאפ: ``maxNesting: 100`` ב-markdown-it 14.1.0
#: (``lib/presets/default.mjs``), ושם מכולה עמוקה יותר כבר לא מוצגת. התקרה
#: נחוצה גם בלי קשר לוובאפ: בשלב ה-inline של Python-Markdown העלות של כל
#: שבירת שורה גדלה עם עומק הקינון, ומכולה שלא נסגרה נסגרת רק בסוף המסמך —
#: כך ששורות ``:::`` רבות שלא נסגרו מקננות זו בתוך זו עד הסוף.
MAX_CONTAINER_NESTING = 100

# הכללים של markdown-it-container 4.0.0 (``index.mjs``, שהבאנדל של הוובאפ זהה
# לו), כדי שאותו מסמך ייראה אותו דבר בשני הצדדים:
# פתיחה — עד שלושה רווחים, שלוש נקודתיים או יותר, ואחריהן הפרמטרים. ארבעה
# רווחים ומעלה הם בלוק קוד, או המשך של פסקה, גם ב-markdown-it.
_CONTAINER_OPEN_RE = re.compile(r"^ {0,3}(?P<fence>:{3,})(?P<params>.*)$")
# סגירה — לפחות אותו מספר נקודתיים, ואחריהן רק רווחים וטאבים (``skipSpaces``).
_CONTAINER_CLOSE_RE = re.compile(r"^ {0,3}(?P<fence>:{3,})[ \t]*$")
# הסוג הוא המילה הראשונה בפרמטרים, בלי רגישות לרישיות, וכל מה שאחריה הוא
# הכותרת — כמו ``/^note\b\s*(.*)$/i`` בוובאפ. ``re.ASCII`` כי ``\w`` ו-``\b`` של
# JS מכירים רק אותיות לטיניות: בוובאפ ``::: noteכותרת`` הוא תיבת ``note`` עם
# הכותרת "כותרת", ובלי הדגל ``\w`` של פייתון היה בולע גם את העברית ומפספס את הסוג.
_CONTAINER_KIND_RE = re.compile(r"(?P<kind>\w+)(?P<title>.*)", re.ASCII)


def _parse_container_opening(line: str) -> tuple[int, str, str] | None:
    """``(אורך הגדר, סוג, כותרת)`` לשורת פתיחה של מכולה מוכרת, ו-``None`` לכל שורה אחרת."""
    opening = _CONTAINER_OPEN_RE.match(line)
    if opening is None:
        return None
    kind_match = _CONTAINER_KIND_RE.match(opening.group("params").strip())
    if kind_match is None:
        return None
    kind = kind_match.group("kind").lower()
    if kind != "details" and kind not in ADMONITION_TYPES:
        return None
    return len(opening.group("fence")), kind, kind_match.group("title").strip()


class _ContainerBlockProcessor(BlockProcessor):
    """ממיר מכולות ``:::`` לתיבות הסבר ול-``details``, בתוך הפרסר של Python-Markdown.

    **למה מעבד בלוקים ולא החלפה על הטקסט.** ביטוי רגולרי שרץ על הטקסט הגולמי,
    לפני ש-Python-Markdown קורא אותו — כך זה נעשה קודם — לא יודע איפה יש בלוק
    קוד: דוגמה של ``::: note`` בתוך בלוק קוד הפכה ל-``<div>`` בתוך הקוד. מעבד בלוקים
    רץ אחרי ש-``fenced_code`` (preprocessor) כבר החליף כל בלוק קוד בממלא מקום,
    ותוכן התיבה עובר דרך אותו פרסר כמו שאר המסמך — קוד, טבלאות ותיבות בתוך
    תיבות. זו הצורה של ``admonition``, התוסף המובנה של Python-Markdown.

    **התוצאה היא המבנה של הוובאפ:** ``div.alert`` עם ``div.alert-title``, ו-
    ``details.markdown-details`` עם ``summary.markdown-summary`` ו-
    ``div.details-content``. הכותרת היא ``AtomicString``: היא לא עוברת עיבוד
    Markdown, וה-serializer מבריח אותה, כמו ``escapeHtml`` בוובאפ.

    **קינון.** הסגירה היא השורה הראשונה שיש בה לפחות אותו מספר נקודתיים, ולכן
    מקננים בגדר ארוכה יותר בחוץ (``::::`` סביב ``:::``). בגדר שווה, ה-``:::``
    של התיבה הפנימית סוגר את החיצונית — כך זה גם בוובאפ. מכולה שלא נסגרה נסגרת
    בסוף ההורה שלה: בסוף המסמך, או בסוף התיבה שמכילה אותה.
    """

    def __init__(self, parser: BlockParser) -> None:
        super().__init__(parser)
        self._depth = 0

    @staticmethod
    def _find_opening(block: str) -> tuple[int, int, str, str] | None:
        """``(מספר השורה, אורך הגדר, סוג, כותרת)`` של שורת הפתיחה הראשונה בבלוק."""
        for index, line in enumerate(block.split("\n")):
            opening = _parse_container_opening(line)
            if opening is not None:
                return (index, *opening)
        return None

    def test(self, parent: etree.Element, block: str) -> bool:
        # השורה יכולה להיות באמצע הבלוק: מכולה קוטעת פסקה, רשימה או ציטוט
        # בלי שורה ריקה לפניה, כמו ב-markdown-it-container. ובקרבת תקרת
        # הרקורסיה — מוותרים, כמו ``BlockQuoteProcessor`` של Python-Markdown.
        return (
            self._depth < MAX_CONTAINER_NESTING
            and self._find_opening(block) is not None
            and not nearing_recursion_limit()
        )

    def run(self, parent: etree.Element, blocks: list[str]) -> None:
        block = blocks.pop(0)
        found = self._find_opening(block)
        if found is None:
            # ``parseBlocks`` קורא ל-``run`` עם הבלוק ש-``test`` אישר זה עתה, ו-
            # ``_find_opening`` אינה תלויה בשום מצב — אז זו הפרה של החוזה, ולא
            # מקרה שמטפלים בו בשקט.
            raise RuntimeError("export_container: run() קיבל בלוק בלי שורת פתיחה")
        index, fence_len, kind, title = found
        lines = block.split("\n")
        if index > 0:
            self.parser.parseBlocks(parent, ["\n".join(lines[:index])])

        # התוכן נאסף כבלוקים, כמו שהפרסר פיצל אותו לפי שורות ריקות, עד שורת
        # הסגירה — גם כשהיא בבלוק מאוחר יותר. מה שאחריה חוזר לתור.
        content: list[str] = []
        remaining = lines[index + 1 :]
        while True:
            close_at = next(
                (
                    i
                    for i, line in enumerate(remaining)
                    if (closing := _CONTAINER_CLOSE_RE.match(line)) is not None
                    and len(closing.group("fence")) >= fence_len
                ),
                None,
            )
            if close_at is not None:
                if close_at > 0:
                    content.append("\n".join(remaining[:close_at]))
                rest = "\n".join(remaining[close_at + 1 :])
                if rest:
                    blocks.insert(0, rest)
                break
            if remaining:
                content.append("\n".join(remaining))
            if not blocks:
                break  # לא נסגרה — נסגרת בסוף ההורה
            remaining = blocks.pop(0).split("\n")

        body = self._build_container(parent, kind, title)
        self._depth += 1
        try:
            self.parser.parseBlocks(body, content)
        finally:
            self._depth -= 1

    @staticmethod
    def _build_container(parent: etree.Element, kind: str, title: str) -> etree.Element:
        """בונה את המכולה מתחת ל-``parent`` ומחזיר את האלמנט שהתוכן נכנס אליו."""
        if kind == "details":
            details = etree.SubElement(parent, "details")
            details.set("class", "markdown-details")
            summary = etree.SubElement(details, "summary")
            summary.set("class", "markdown-summary")
            summary.text = AtomicString(title or DETAILS_DEFAULT_TITLE)
            body = etree.SubElement(details, "div")
            body.set("class", "details-content")
            return body
        admonition = ADMONITION_TYPES[kind]
        box = etree.SubElement(parent, "div")
        box.set("class", f"alert alert-{admonition.css_class}")
        heading = etree.SubElement(box, "div")
        heading.set("class", "alert-title")
        heading.text = AtomicString(title or admonition.title)
        return box


class _ContainerExtension(Extension):
    """רושם את ``_ContainerBlockProcessor`` במופע של Python-Markdown."""

    def extendMarkdown(self, md: markdown.Markdown) -> None:
        # 95: אחרי ``empty`` (100), שמסיר שורות ריקות בראש בלוק, ולפני כל מעבד
        # שהיה לוקח את הבלוק שבו יושבת שורת הפתיחה — מ-``indent`` (90) ועד
        # ``paragraph`` (10). כך המכולה קוטעת אותם ולא נבלעת בהם.
        # (העדיפויות: ``build_block_parser`` ב-markdown/blockprocessors.py, Markdown 3.9.)
        md.parser.blockprocessors.register(
            _ContainerBlockProcessor(md.parser), "export_container", 95
        )


def markdown_to_html(text: str, include_toc: bool = False) -> tuple[str, str]:
    """
    המרת Markdown ל-HTML עם extensions מתאימים.

    🔒 אבטחה: ה-HTML עובר sanitization דרך bleach למניעת XSS.

    Args:
        text: תוכן Markdown
        include_toc: האם להחזיר גם תוכן עניינים

    Returns:
        tuple של (html_content, toc_html)
        אם include_toc=False, toc_html יהיה ריק
    """
    if not text:
        return ("", "")

    # יצירת אובייקט Markdown (לא פונקציה) כדי לגשת ל-TOC
    md = markdown.Markdown(
        extensions=[
            "fenced_code",  # ```code blocks```
            "tables",  # טבלאות GFM
            "nl2br",  # שורות חדשות → <br>
            "toc",  # תוכן עניינים
            "codehilite",  # הדגשת קוד (עם Pygments)
            "attr_list",  # attributes על אלמנטים
            _ContainerExtension(),  # מכולות ::: — תיבות הסבר ו-details
        ],
        extension_configs={
            "codehilite": {
                "css_class": "highlight",
                "linenums": False,
                "guess_lang": True,
            },
            "toc": {
                "title": "📑 תוכן עניינים",
                "toc_depth": 3,
            },
        },
    )

    # המרה ל-HTML
    html_raw = md.convert(text)
    # 🔒 אבטחה: הסרת בלוקים מסוכנים יחד עם התוכן (script/style)
    html_raw = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", html_raw, flags=re.IGNORECASE | re.DOTALL)

    # ניקוי ה-HTML
    clean_html = bleach.clean(
        html_raw,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,  # הסרת תגיות לא מורשות במקום escape
    )

    # הוספת rel="noopener noreferrer" לכל קישורים עם target="_blank"
    # שימוש ב-regex כדי להימנע מ-duplicate attributes
    def add_noopener(match):
        tag = match.group(0)
        # בדיקה אם יש rel כאטריביוט (לא בתוך href או ערך אחר)
        # שימוש ברגקס שמחפש rel= מחוץ למירכאות
        has_rel_attr = re.search(r'\srel\s*=\s*(["\'])', tag)

        if has_rel_attr:
            # החלפת rel קיים
            # 🔒 חשוב: match של אותו סוג מרכאות בפתיחה/סגירה כדי לא לחתוך ערכים עם גרשיים/מרכאות פנימיים
            tag = re.sub(
                r'\srel\s*=\s*(["\']).*?\1',
                ' rel="noopener noreferrer"',
                tag,
                count=1,
                flags=re.IGNORECASE,
            )
        else:
            # הוספת rel חדש
            tag = tag.replace('target="_blank"', 'target="_blank" rel="noopener noreferrer"')
        return tag

    # מציאת כל תגיות a עם target="_blank"
    clean_html = re.sub(
        r'<a\s[^>]*target="_blank"[^>]*>',
        add_noopener,
        clean_html,
    )

    # החזרת HTML + TOC (אם נדרש)
    toc_html = ""
    if include_toc and hasattr(md, "toc"):
        # TOC נוצר ע"י Python-Markdown ומכיל רק ul/li/a עם anchors
        # אבל נעביר גם אותו דרך bleach לבטיחות
        toc_raw = md.toc
        toc_html = bleach.clean(
            toc_raw,
            tags=["div", "nav", "ul", "li", "a"],
            attributes={"a": ["href", "title"], "*": ["class", "id"]},
            protocols=["http", "https", "#"],  # # עבור anchors פנימיים
            strip=True,
        )

    return (clean_html, toc_html)


# ============================================
# Theme Resolution
# ============================================

#: צבעי VS Code Dark+ להדגשת תחביר של Pygments (``.highlight``), משותפים לכמה ערכות
#: ייצוא. כל ערכה קובעת רק את השם שבהערה ואת צבע הכותרות (``.gh``, ``.gu``).
#: ``string.Template`` ולא f-string, כי ב-CSS יש סוגריים מסולסלים ואין בו ``$``.
#: שימו לב: מפתחות של JSON מקבלים ב-Pygments את אותו טוקן כמו תגית HTML (``.nt``),
#: ולכן הם נצבעים בצבע של התגיות.
_VSCODE_DARK_PLUS_SYNTAX_CSS = Template("""
/* $theme_name - Syntax Highlighting */
.highlight .c, .highlight .c1, .highlight .cm { color: #6a9955; font-style: italic; }  /* Comments */
.highlight .k, .highlight .kd, .highlight .kn { color: #c586c0; }  /* Keywords */
.highlight .s, .highlight .s1, .highlight .s2 { color: #ce9178; }  /* Strings */
.highlight .m, .highlight .mi, .highlight .mf, .highlight .mh { color: #b5cea8; }  /* Numbers */
.highlight .nb, .highlight .bp { color: #b5cea8; }  /* Built-ins / Constants */
.highlight .n, .highlight .nv { color: #9cdcfe; }  /* Variables */
.highlight .nf, .highlight .fm { color: #dcdcaa; }  /* Functions */
.highlight .nc, .highlight .nn { color: #4ec9b0; }  /* Classes / Namespaces */
.highlight .nt { color: #569cd6; }  /* HTML Tags */
.highlight .na { color: #9cdcfe; }  /* Attributes */
.highlight .o, .highlight .p { color: #d4d4d4; }  /* Operators / Punctuation */
.highlight .sr { color: #d16969; }  /* Regex */
.highlight .se { color: #d7ba7d; }  /* Escape */
.highlight .gh, .highlight .gu { color: $heading_color; font-weight: bold; }  /* Headings */
.highlight .ge { font-style: italic; }  /* Emphasis */
.highlight .gs { font-weight: bold; }  /* Strong */
.highlight .err { color: #f44747; text-decoration: underline; }  /* Errors */
""")

#: הבורר שכללי highlight.js של ערכת ייצוא נכתבים תחתיו (``hljs_css``). הייצוא מהעורך הציבורי מרנדר את
#: הקוד בדפדפן, ו-highlight.js נותן ל-``<code>`` את המחלקה ``hljs`` — כך הכללים חלים רק על בלוקי קוד.
EXPORT_HLJS_SELECTOR_PREFIX = "code.hljs"

# צבעי התחביר של ערכות הייצוא של העורך הציבורי (``EXPORT_THEME_IDS`` ב-``webapp/markdown_editor.py``):
# ``tokenColors`` מקובצי ה-VS Code של הערכות (``morass-Tech-theme.json``,
# ``pen-paper-coffee-ui-v4-color-theme.json`` ו-``everforest-dark-v2.json`` ב-CodeKeeper), בלי הרשומות שאין
# להן ``foreground`` — שני המחוללים מדלגים עליהן ממילא. מהרשימה נגזרים גם כללי Pygments (``syntax_css``,
# לייצוא של המחוברים) וגם כללי highlight.js (``hljs_css``, לייצוא מהעורך הציבורי), כך שלכל ערכה יש מקור
# אחד לצבעי התחביר.
_MORASS_TOKEN_COLORS: list[dict] = [
    {
        "scope": [
            "comment",
            "punctuation.definition.comment",
        ],
        "settings": {"foreground": "#6a9955", "fontStyle": "italic"},
    },
    {
        "scope": [
            "keyword",
            "keyword.control",
            "keyword.operator.new",
            "keyword.operator.expression",
            "keyword.operator.cast",
            "keyword.operator.sizeof",
            "keyword.operator.instanceof",
        ],
        "settings": {"foreground": "#c586c0"},
    },
    {"scope": ["storage", "storage.type", "storage.modifier"], "settings": {"foreground": "#c586c0"}},
    {"scope": ["string", "string.quoted", "string.template"], "settings": {"foreground": "#ce9178"}},
    {
        "scope": [
            "constant.numeric",
            "constant.numeric.integer",
            "constant.numeric.float",
            "constant.numeric.hex",
        ],
        "settings": {"foreground": "#b5cea8"},
    },
    {
        "scope": [
            "constant",
            "constant.language",
            "constant.character",
            "constant.other",
        ],
        "settings": {"foreground": "#b5cea8"},
    },
    {"scope": ["variable", "variable.other", "variable.language"], "settings": {"foreground": "#9cdcfe"}},
    {
        "scope": [
            "variable.parameter",
            "meta.function.parameters",
        ],
        "settings": {"foreground": "#9cdcfe", "fontStyle": "italic"},
    },
    {
        "scope": [
            "entity.name.function",
            "meta.function-call",
            "support.function",
        ],
        "settings": {"foreground": "#dcdcaa"},
    },
    {"scope": ["entity.name.method", "meta.method-call"], "settings": {"foreground": "#dcdcaa"}},
    {
        "scope": [
            "entity.name.class",
            "entity.name.type.class",
            "support.class",
        ],
        "settings": {"foreground": "#4ec9b0"},
    },
    {"scope": ["entity.name.type", "support.type", "support.type.primitive"], "settings": {"foreground": "#4ec9b0"}},
    {"scope": ["entity.name.type.interface"], "settings": {"foreground": "#4ec9b0", "fontStyle": "italic"}},
    {"scope": ["entity.name.namespace", "entity.name.module"], "settings": {"foreground": "#4ec9b0"}},
    {
        "scope": [
            "keyword.operator",
            "keyword.operator.arithmetic",
            "keyword.operator.comparison",
            "keyword.operator.logical",
        ],
        "settings": {"foreground": "#d4d4d4"},
    },
    {
        "scope": [
            "punctuation",
            "punctuation.definition",
            "punctuation.separator",
            "punctuation.terminator",
        ],
        "settings": {"foreground": "#d4d4d4"},
    },
    {
        "scope": [
            "variable.other.property",
            "variable.other.object.property",
            "support.variable.property",
        ],
        "settings": {"foreground": "#9cdcfe"},
    },
    {"scope": ["entity.name.tag", "meta.tag"], "settings": {"foreground": "#569cd6"}},
    {"scope": ["entity.other.attribute-name"], "settings": {"foreground": "#9cdcfe"}},
    {"scope": ["string.quoted.double.html", "string.quoted.single.html"], "settings": {"foreground": "#ce9178"}},
    {"scope": ["string.regexp"], "settings": {"foreground": "#d16969"}},
    {"scope": ["constant.character.escape"], "settings": {"foreground": "#d7ba7d"}},
    {"scope": ["meta.embedded", "source.embedded"], "settings": {"foreground": "#c586c0"}},
    {"scope": ["invalid", "invalid.illegal"], "settings": {"foreground": "#f44747", "fontStyle": "underline"}},
    {"scope": ["invalid.deprecated"], "settings": {"foreground": "#f44747", "fontStyle": "strikethrough"}},
    {"scope": ["support.type.property-name.css"], "settings": {"foreground": "#9cdcfe"}},
    {"scope": ["support.constant.property-value.css"], "settings": {"foreground": "#ce9178"}},
    {"scope": ["keyword.other.unit.css"], "settings": {"foreground": "#b5cea8"}},
    {
        "scope": [
            "entity.other.attribute-name.class.css",
            "entity.other.attribute-name.id.css",
        ],
        "settings": {"foreground": "#dcdcaa"},
    },
    {"scope": ["support.type.property-name.json"], "settings": {"foreground": "#9cdcfe"}},
    {
        "scope": [
            "markup.heading",
            "entity.name.section.markdown",
        ],
        "settings": {"foreground": "#0088cc", "fontStyle": "bold"},
    },
    {"scope": ["markup.bold"], "settings": {"foreground": "#dcdcaa", "fontStyle": "bold"}},
    {"scope": ["markup.underline.link"], "settings": {"foreground": "#0088cc"}},
    {"scope": ["markup.inline.raw"], "settings": {"foreground": "#7fdbca"}},
]

_PEN_PAPER_COFFEE_TOKEN_COLORS: list[dict] = [
    {"scope": ["variable"], "settings": {"foreground": "#2b3f6a"}},
    {"scope": ["meta.property-name", "support.type.property-name"], "settings": {"foreground": "#2b3f6a"}},
    {"scope": ["comment"], "settings": {"foreground": "#9ca3b0", "fontStyle": "italic"}},
    {"scope": ["meta.brace"], "settings": {"foreground": "#5e6fa0"}},
    {"scope": ["invalid.illegal"], "settings": {"foreground": "#c16161"}},
    {"scope": ["keyword.operator"], "settings": {"foreground": "#1c4b33", "fontStyle": "bold"}},
    {"scope": ["keyword", "storage"], "settings": {"foreground": "#5e78e1"}},
    {"scope": ["keyword.control"], "settings": {"foreground": "#2b3f6a", "fontStyle": "bold"}},
    {
        "scope": [
            "variable.other.object.property.js",
            "variable.other.property.js",
            "support.type.property-name",
            "meta.objectliteral",
        ],
        "settings": {"foreground": "#5e78e1"},
    },
    {"scope": ["storage.type", "support.type"], "settings": {"foreground": "#5e78e1"}},
    {"scope": ["constant.language", "support.constant"], "settings": {"foreground": "#c16161"}},
    {
        "scope": [
            "variable.parameter",
            "support.variable",
            "variable.other.member",
        ],
        "settings": {"foreground": "#5e78e1"},
    },
    {"scope": ["support.function", "entity.name.function"], "settings": {"foreground": "#d08e25"}},
    {"scope": ["entity.name.exception"], "settings": {"foreground": "#660000"}},
    {"scope": ["keyword.other.unit", "constant.character", "constant"], "settings": {"foreground": "#8f932b"}},
    {"scope": ["constant.numeric", "constant"], "settings": {"foreground": "#c16161"}},
    {"scope": ["string", "punctuation.definition.string"], "settings": {"foreground": "#8f6928"}},
    {"scope": ["constant.character.escape"], "settings": {"foreground": "#777777"}},
    {"scope": ["string.regexp"], "settings": {"foreground": "#379566"}},
    {"scope": ["constant.other.symbol", "variable.other.constant"], "settings": {"foreground": "#c16161"}},
    {"scope": ["punctuation"], "settings": {"foreground": "#777777"}},
    {"scope": ["punctuation.definition.template-expression"], "settings": {"foreground": "#c16161"}},
    {
        "scope": [
            "meta.tag.sgml.doctype",
            "meta.tag.sgml.doctype string",
            "meta.tag.sgml.doctype entity.name.tag",
            "meta.tag.sgml punctuation.definition.tag.html",
        ],
        "settings": {"foreground": "#AAAAAA"},
    },
    {
        "scope": [
            "meta.tag",
            "punctuation.definition.tag.html",
            "punctuation.definition.tag.begin.html",
            "punctuation.definition.tag.end.html",
        ],
        "settings": {"foreground": "#b75c5c"},
    },
    {"scope": ["entity.name.tag"], "settings": {"foreground": "#4B83CD"}},
    {
        "scope": [
            "meta.tag entity.other.attribute-name",
            "entity.other.attribute-name.html",
        ],
        "settings": {"foreground": "#d08e25", "fontStyle": "italic"},
    },
    {"scope": ["constant.character.entity", "punctuation.definition.entity"], "settings": {"foreground": "#AB6526"}},
    {
        "scope": [
            "meta.selector",
            "meta.selector entity",
            "meta.selector entity punctuation",
            "entity.name.tag.css",
        ],
        "settings": {"foreground": "#d08e25"},
    },
    {
        "scope": [
            "meta.property-value",
            "meta.property-value constant.other",
            "support.constant.property-value",
        ],
        "settings": {"foreground": "#448C27"},
    },
    {"scope": ["markup.changed"], "settings": {"foreground": "#8100c6"}},
    {"scope": ["markup.deleted"], "settings": {"foreground": "#c16161"}},
    {"scope": ["markup.italic"], "settings": {"foreground": "#0e72aa", "fontStyle": "italic"}},
    {"scope": ["markup.error"], "settings": {"foreground": "#660000"}},
    {"scope": ["markup.inserted"], "settings": {"foreground": "#000000"}},
    {"scope": ["meta.link"], "settings": {"foreground": "#4B83CD"}},
    {"scope": ["markup.output", "markup.raw"], "settings": {"foreground": "#777777"}},
    {"scope": ["markup.prompt"], "settings": {"foreground": "#777777"}},
    {"scope": ["markup entity.name.section"], "settings": {"foreground": "#2a120a", "fontStyle": "underline"}},
    {"scope": ["markup.heading"], "settings": {"foreground": "#2a120a"}},
    {"scope": ["markup.bold"], "settings": {"foreground": "#0a537b", "fontStyle": "bold"}},
    {"scope": ["markup.traceback"], "settings": {"foreground": "#660000"}},
    {"scope": ["markup.quote"], "settings": {"foreground": "#7e5121c4"}},
    {"scope": ["markup.quote markup.bold"], "settings": {"foreground": "#7e5121c4"}},
    {"scope": ["markup.list"], "settings": {"foreground": "#4B83CD"}},
    {"scope": ["markup.inline.raw"], "settings": {"foreground": "#8f932b"}},
    {"scope": ["punctuation.definition.bold.markdown"], "settings": {"foreground": "#0a537b93"}},
    {"scope": ["punctuation.definition.italic.markdown"], "settings": {"foreground": "#0e71aa9d"}},
    {"scope": ["string.other.link.title.markdown"], "settings": {"foreground": "#2b3f6a"}},
    {
        "scope": [
            "support.function.text.markdown",
            "string.other.link.description.markdown.citation",
        ],
        "settings": {"foreground": "#aa5c08"},
    },
    {"scope": ["meta.diff.range", "meta.diff.index", "meta.separator"], "settings": {"foreground": "#434343"}},
    {"scope": ["meta.diff.header.from-file"], "settings": {"foreground": "#434343"}},
    {"scope": ["meta.diff.header.to-file"], "settings": {"foreground": "#434343"}},
    {"scope": ["invalid.deprecated.line-too-long.git-commit"], "settings": {"foreground": "#c16161"}},
]

# ``scope`` כאן הוא מחרוזת, בדיוק כמו בקובץ הערכה, ולא רשימה: ב-VS Code מחרוזת היא רשימה של בוררים מופרדים
# בפסיק, ורשומה ברשימה אינה מפוצלת (``parseTheme`` ב-``src/theme.ts`` של vscode-textmate 9.3.2). המחוללים של
# ``services/theme_parser_service.py`` עוד לא מפצלים מחרוזת כזו, ולכן רשומה עם פסיק לא צובעת אצלנו כלום —
# בערכה הזו, למשל, ההערות בקוד. התיקון במחוללים ולא כאן, כדי שגם ערכות שמיובאות ייהנו ממנו: כרטיס "מחוללי
# צבעי התחביר — scope עם פסיקים וכיוון ההתאמה" בלוח ה-issues ב-CodeKeeper.
_EVERFOREST_DARK_TOKEN_COLORS: list[dict] = [
    {
        "scope": (
            "keyword, storage.type.function, storage.type.class, storage.type.enum, "
            "storage.type.interface, storage.type.property, keyword.operator.new, "
            "keyword.operator.expression, keyword.operator.new, keyword.operator.delete, "
            "storage.type.extends"
        ),
        "settings": {"foreground": "#e67e80"},
    },
    {"scope": "keyword.other.debugger", "settings": {"foreground": "#e67e80"}},
    {
        "scope": (
            "storage, modifier, keyword.var, entity.name.tag, keyword.control.case, "
            "keyword.control.switch"
        ),
        "settings": {"foreground": "#e69875"},
    },
    {"scope": "keyword.operator", "settings": {"foreground": "#e69875"}},
    {
        "scope": (
            "string, punctuation.definition.string.end, punctuation.definition.string.begin, "
            "punctuation.definition.string.template.begin, "
            "punctuation.definition.string.template.end"
        ),
        "settings": {"foreground": "#dbbc7f"},
    },
    {"scope": "entity.other.attribute-name", "settings": {"foreground": "#dbbc7f"}},
    {
        "scope": (
            "constant.character.escape, punctuation.quasi.element, "
            "punctuation.definition.template-expression, punctuation.section.embedded, "
            "storage.type.format, constant.other.placeholder, constant.other.placeholder, "
            "variable.interpolation"
        ),
        "settings": {"foreground": "#a7c080"},
    },
    {
        "scope": (
            "entity.name.function, support.function, meta.function, meta.function-call, "
            "meta.definition.method"
        ),
        "settings": {"foreground": "#a7c080"},
    },
    {
        "scope": (
            "keyword.control.at-rule, keyword.control.import, keyword.control.export, "
            "storage.type.namespace, punctuation.decorator, keyword.control.directive, "
            "keyword.preprocessor, punctuation.definition.preprocessor, "
            "punctuation.definition.directive, keyword.other.import, keyword.other.package, "
            "entity.name.type.namespace, entity.name.scope-resolution, keyword.other.using, "
            "keyword.package, keyword.import, keyword.map"
        ),
        "settings": {"foreground": "#83c092"},
    },
    {"scope": "storage.type.annotation", "settings": {"foreground": "#83c092"}},
    {"scope": "entity.name.label, constant.other.label", "settings": {"foreground": "#83c092"}},
    {
        "scope": (
            "support.module, support.node, support.other.module, support.type.object.module, "
            "entity.name.type.module, entity.name.type.class.module, keyword.control.module"
        ),
        "settings": {"foreground": "#83c092"},
    },
    {
        "scope": "storage.type, support.type, entity.name.type, keyword.type",
        "settings": {"foreground": "#7fbbb3"},
    },
    {
        "scope": (
            "entity.name.type.class, support.class, entity.name.class, "
            "entity.other.inherited-class, storage.class"
        ),
        "settings": {"foreground": "#7fbbb3"},
    },
    {"scope": "constant.numeric", "settings": {"foreground": "#d699b6"}},
    {"scope": "constant.language.boolean", "settings": {"foreground": "#d699b6"}},
    {"scope": "entity.name.function.preprocessor", "settings": {"foreground": "#d699b6"}},
    {
        "scope": (
            "variable.language.this, variable.language.self, variable.language.super, "
            "keyword.other.this, variable.language.special, constant.language.null, "
            "constant.language.undefined, constant.language.nan"
        ),
        "settings": {"foreground": "#d699b6"},
    },
    {"scope": "constant.language, support.constant", "settings": {"foreground": "#d699b6"}},
    {
        "scope": "variable, support.variable, meta.definition.variable",
        "settings": {"foreground": "#d3c6aa"},
    },
    {
        "scope": (
            "variable.object.property, support.variable.property, variable.other.property, "
            "variable.other.object.property, variable.other.enummember, variable.other.member, "
            "meta.object-literal.key"
        ),
        "settings": {"foreground": "#d3c6aa"},
    },
    {
        "scope": "punctuation, meta.brace, meta.delimiter, meta.bracket",
        "settings": {"foreground": "#d3c6aa"},
    },
    {
        "scope": "heading.1.markdown, markup.heading.setext.1.markdown",
        "settings": {"foreground": "#e67e80", "fontStyle": "bold"},
    },
    {
        "scope": "heading.2.markdown, markup.heading.setext.2.markdown",
        "settings": {"foreground": "#e69875", "fontStyle": "bold"},
    },
    {"scope": "heading.3.markdown", "settings": {"foreground": "#dbbc7f", "fontStyle": "bold"}},
    {"scope": "heading.4.markdown", "settings": {"foreground": "#a7c080", "fontStyle": "bold"}},
    {"scope": "heading.5.markdown", "settings": {"foreground": "#7fbbb3", "fontStyle": "bold"}},
    {"scope": "heading.6.markdown", "settings": {"foreground": "#d699b6", "fontStyle": "bold"}},
    {
        "scope": "punctuation.definition.heading.markdown",
        "settings": {"foreground": "#859289", "fontStyle": "regular"},
    },
    {
        "scope": (
            "string.other.link.title.markdown, constant.other.reference.link.markdown, "
            "string.other.link.description.markdown"
        ),
        "settings": {"foreground": "#d699b6", "fontStyle": "regular"},
    },
    {
        "scope": "markup.underline.link.image.markdown, markup.underline.link.markdown",
        "settings": {"foreground": "#a7c080", "fontStyle": "underline"},
    },
    {
        "scope": (
            "punctuation.definition.string.begin.markdown, "
            "punctuation.definition.string.end.markdown, punctuation.definition.italic.markdown, "
            "punctuation.definition.quote.begin.markdown, "
            "punctuation.definition.metadata.markdown, punctuation.separator.key-value.markdown, "
            "punctuation.definition.constant.markdown"
        ),
        "settings": {"foreground": "#859289"},
    },
    {
        "scope": "punctuation.definition.bold.markdown",
        "settings": {"foreground": "#859289", "fontStyle": "regular"},
    },
    {
        "scope": (
            "meta.separator.markdown, punctuation.definition.constant.begin.markdown, "
            "punctuation.definition.constant.end.markdown"
        ),
        "settings": {"foreground": "#859289", "fontStyle": "bold"},
    },
    {
        "scope": "punctuation.definition.markdown, punctuation.definition.raw.markdown",
        "settings": {"foreground": "#dbbc7f"},
    },
    {"scope": "fenced_code.block.language", "settings": {"foreground": "#dbbc7f"}},
    {
        "scope": "markup.fenced_code.block.markdown, markup.inline.raw.string.markdown",
        "settings": {"foreground": "#a7c080"},
    },
    {"scope": "punctuation.definition.list.begin.markdown", "settings": {"foreground": "#e67e80"}},
    {
        "scope": "punctuation.definition.heading.restructuredtext",
        "settings": {"foreground": "#e69875", "fontStyle": "bold"},
    },
    {
        "scope": (
            "punctuation.definition.field.restructuredtext, "
            "punctuation.separator.key-value.restructuredtext, "
            "punctuation.definition.directive.restructuredtext, "
            "punctuation.definition.constant.restructuredtext, "
            "punctuation.definition.italic.restructuredtext, "
            "punctuation.definition.table.restructuredtext"
        ),
        "settings": {"foreground": "#859289"},
    },
    {
        "scope": "punctuation.definition.bold.restructuredtext",
        "settings": {"foreground": "#859289", "fontStyle": "regular"},
    },
    {
        "scope": (
            "entity.name.tag.restructuredtext, punctuation.definition.link.restructuredtext, "
            "punctuation.definition.raw.restructuredtext, punctuation.section.raw.restructuredtext"
        ),
        "settings": {"foreground": "#83c092"},
    },
    {
        "scope": "constant.other.footnote.link.restructuredtext",
        "settings": {"foreground": "#d699b6"},
    },
    {"scope": "support.directive.restructuredtext", "settings": {"foreground": "#e67e80"}},
    {
        "scope": (
            "entity.name.directive.restructuredtext, markup.raw.restructuredtext, "
            "markup.raw.inner.restructuredtext, string.other.link.title.restructuredtext"
        ),
        "settings": {"foreground": "#a7c080"},
    },
    {
        "scope": (
            "punctuation.definition.function.latex, punctuation.definition.function.tex, "
            "punctuation.definition.keyword.latex, constant.character.newline.tex, "
            "punctuation.definition.keyword.tex"
        ),
        "settings": {"foreground": "#859289"},
    },
    {"scope": "support.function.be.latex", "settings": {"foreground": "#e67e80"}},
    {
        "scope": (
            "support.function.section.latex, keyword.control.table.cell.latex, "
            "keyword.control.table.newline.latex"
        ),
        "settings": {"foreground": "#e69875"},
    },
    {
        "scope": (
            "support.class.latex, variable.parameter.latex, variable.parameter.function.latex, "
            "variable.parameter.definition.label.latex, constant.other.reference.label.latex"
        ),
        "settings": {"foreground": "#dbbc7f"},
    },
    {"scope": "keyword.control.preamble.latex", "settings": {"foreground": "#d699b6"}},
    {"scope": "punctuation.separator.namespace.xml", "settings": {"foreground": "#859289"}},
    {
        "scope": "entity.name.tag.html, entity.name.tag.xml, entity.name.tag.localname.xml",
        "settings": {"foreground": "#e69875"},
    },
    {
        "scope": (
            "entity.other.attribute-name.html, entity.other.attribute-name.xml, "
            "entity.other.attribute-name.localname.xml"
        ),
        "settings": {"foreground": "#dbbc7f"},
    },
    {
        "scope": (
            "string.quoted.double.html, string.quoted.single.html, "
            "punctuation.definition.string.begin.html, punctuation.definition.string.end.html, "
            "punctuation.separator.key-value.html, punctuation.definition.string.begin.xml, "
            "punctuation.definition.string.end.xml, string.quoted.double.xml, "
            "string.quoted.single.xml, punctuation.definition.tag.begin.html, "
            "punctuation.definition.tag.end.html, punctuation.definition.tag.xml, meta.tag.xml, "
            "meta.tag.preprocessor.xml, meta.tag.other.html, meta.tag.block.any.html, "
            "meta.tag.inline.any.html"
        ),
        "settings": {"foreground": "#a7c080"},
    },
    {
        "scope": "variable.language.documentroot.xml, meta.tag.sgml.doctype.xml",
        "settings": {"foreground": "#d699b6"},
    },
    {"scope": "storage.type.proto", "settings": {"foreground": "#dbbc7f"}},
    {
        "scope": (
            "string.quoted.double.proto.syntax, string.quoted.single.proto.syntax, "
            "string.quoted.double.proto, string.quoted.single.proto"
        ),
        "settings": {"foreground": "#a7c080"},
    },
    {
        "scope": "entity.name.class.proto, entity.name.class.message.proto",
        "settings": {"foreground": "#83c092"},
    },
    {
        "scope": (
            "punctuation.definition.entity.css, punctuation.separator.key-value.css, "
            "punctuation.terminator.rule.css, punctuation.separator.list.comma.css"
        ),
        "settings": {"foreground": "#859289"},
    },
    {"scope": "entity.other.attribute-name.class.css", "settings": {"foreground": "#e67e80"}},
    {"scope": "keyword.other.unit", "settings": {"foreground": "#e69875"}},
    {
        "scope": (
            "entity.other.attribute-name.pseudo-class.css, "
            "entity.other.attribute-name.pseudo-element.css"
        ),
        "settings": {"foreground": "#dbbc7f"},
    },
    {
        "scope": (
            "string.quoted.single.css, string.quoted.double.css, "
            "support.constant.property-value.css, meta.property-value.css, "
            "punctuation.definition.string.begin.css, punctuation.definition.string.end.css, "
            "constant.numeric.css, support.constant.font-name.css, "
            "variable.parameter.keyframe-list.css"
        ),
        "settings": {"foreground": "#a7c080"},
    },
    {"scope": "support.type.property-name.css", "settings": {"foreground": "#83c092"}},
    {"scope": "support.type.vendored.property-name.css", "settings": {"foreground": "#7fbbb3"}},
    {
        "scope": (
            "entity.name.tag.css, entity.other.keyframe-offset.css, "
            "punctuation.definition.keyword.css, keyword.control.at-rule.keyframes.css, "
            "meta.selector.css"
        ),
        "settings": {"foreground": "#d699b6"},
    },
    {
        "scope": (
            "punctuation.definition.entity.scss, punctuation.separator.key-value.scss, "
            "punctuation.terminator.rule.scss, punctuation.separator.list.comma.scss"
        ),
        "settings": {"foreground": "#859289"},
    },
    {"scope": "keyword.control.at-rule.keyframes.scss", "settings": {"foreground": "#e69875"}},
    {
        "scope": (
            "punctuation.definition.interpolation.begin.bracket.curly.scss, "
            "punctuation.definition.interpolation.end.bracket.curly.scss"
        ),
        "settings": {"foreground": "#dbbc7f"},
    },
    {
        "scope": (
            "punctuation.definition.string.begin.scss, punctuation.definition.string.end.scss, "
            "string.quoted.double.scss, string.quoted.single.scss, constant.character.css.sass, "
            "meta.property-value.scss"
        ),
        "settings": {"foreground": "#a7c080"},
    },
    {
        "scope": (
            "keyword.control.at-rule.include.scss, keyword.control.at-rule.use.scss, "
            "keyword.control.at-rule.mixin.scss, keyword.control.at-rule.extend.scss, "
            "keyword.control.at-rule.import.scss"
        ),
        "settings": {"foreground": "#d699b6"},
    },
    {"scope": "meta.function.stylus", "settings": {"foreground": "#d3c6aa"}},
    {"scope": "entity.name.function.stylus", "settings": {"foreground": "#dbbc7f"}},
    {"scope": "string.unquoted.js", "settings": {"foreground": "#d3c6aa"}},
    {
        "scope": (
            "punctuation.accessor.js, punctuation.separator.key-value.js, "
            "punctuation.separator.label.js, keyword.operator.accessor.js"
        ),
        "settings": {"foreground": "#859289"},
    },
    {"scope": "punctuation.definition.block.tag.jsdoc", "settings": {"foreground": "#e67e80"}},
    {
        "scope": "storage.type.js, storage.type.function.arrow.js",
        "settings": {"foreground": "#e69875"},
    },
    {"scope": "JSXNested", "settings": {"foreground": "#d3c6aa"}},
    {
        "scope": (
            "punctuation.definition.tag.jsx, entity.other.attribute-name.jsx, "
            "punctuation.definition.tag.begin.js.jsx, punctuation.definition.tag.end.js.jsx, "
            "entity.other.attribute-name.js.jsx"
        ),
        "settings": {"foreground": "#a7c080"},
    },
    {"scope": "entity.name.type.module.ts", "settings": {"foreground": "#d3c6aa"}},
    {
        "scope": (
            "keyword.operator.type.annotation.ts, punctuation.accessor.ts, "
            "punctuation.separator.key-value.ts"
        ),
        "settings": {"foreground": "#859289"},
    },
    {
        "scope": (
            "punctuation.definition.tag.directive.ts, entity.other.attribute-name.directive.ts"
        ),
        "settings": {"foreground": "#a7c080"},
    },
    {
        "scope": (
            "entity.name.type.ts, entity.name.type.interface.ts, entity.other.inherited-class.ts, "
            "entity.name.type.alias.ts, entity.name.type.class.ts, entity.name.type.enum.ts"
        ),
        "settings": {"foreground": "#83c092"},
    },
    {
        "scope": "storage.type.ts, storage.type.function.arrow.ts, storage.type.type.ts",
        "settings": {"foreground": "#e69875"},
    },
    {"scope": "entity.name.type.module.ts", "settings": {"foreground": "#7fbbb3"}},
    {
        "scope": "keyword.control.import.ts, keyword.control.export.ts, storage.type.namespace.ts",
        "settings": {"foreground": "#d699b6"},
    },
    {"scope": "entity.name.type.module.tsx", "settings": {"foreground": "#d3c6aa"}},
    {
        "scope": (
            "keyword.operator.type.annotation.tsx, punctuation.accessor.tsx, "
            "punctuation.separator.key-value.tsx"
        ),
        "settings": {"foreground": "#859289"},
    },
    {
        "scope": (
            "punctuation.definition.tag.directive.tsx, entity.other.attribute-name.directive.tsx, "
            "punctuation.definition.tag.begin.tsx, punctuation.definition.tag.end.tsx, "
            "entity.other.attribute-name.tsx"
        ),
        "settings": {"foreground": "#a7c080"},
    },
    {
        "scope": (
            "entity.name.type.tsx, entity.name.type.interface.tsx, "
            "entity.other.inherited-class.tsx, entity.name.type.alias.tsx, "
            "entity.name.type.class.tsx, entity.name.type.enum.tsx"
        ),
        "settings": {"foreground": "#83c092"},
    },
    {"scope": "entity.name.type.module.tsx", "settings": {"foreground": "#7fbbb3"}},
    {
        "scope": (
            "keyword.control.import.tsx, keyword.control.export.tsx, storage.type.namespace.tsx"
        ),
        "settings": {"foreground": "#d699b6"},
    },
    {
        "scope": (
            "storage.type.tsx, storage.type.function.arrow.tsx, storage.type.type.tsx, "
            "support.class.component.tsx"
        ),
        "settings": {"foreground": "#e69875"},
    },
    {"scope": "storage.type.function.coffee", "settings": {"foreground": "#e69875"}},
    {"scope": "meta.type-signature.purescript", "settings": {"foreground": "#d3c6aa"}},
    {
        "scope": (
            "keyword.other.double-colon.purescript, keyword.other.arrow.purescript, "
            "keyword.other.big-arrow.purescript"
        ),
        "settings": {"foreground": "#e69875"},
    },
    {"scope": "entity.name.function.purescript", "settings": {"foreground": "#dbbc7f"}},
    {
        "scope": (
            "string.quoted.single.purescript, string.quoted.double.purescript, "
            "punctuation.definition.string.begin.purescript, "
            "punctuation.definition.string.end.purescript, string.quoted.triple.purescript, "
            "entity.name.type.purescript"
        ),
        "settings": {"foreground": "#a7c080"},
    },
    {"scope": "support.other.module.purescript", "settings": {"foreground": "#d699b6"}},
    {"scope": "punctuation.dot.dart", "settings": {"foreground": "#859289"}},
    {"scope": "storage.type.primitive.dart", "settings": {"foreground": "#e69875"}},
    {"scope": "support.class.dart", "settings": {"foreground": "#dbbc7f"}},
    {
        "scope": (
            "entity.name.function.dart, string.interpolated.single.dart, "
            "string.interpolated.double.dart"
        ),
        "settings": {"foreground": "#a7c080"},
    },
    {"scope": "variable.language.dart", "settings": {"foreground": "#7fbbb3"}},
    {
        "scope": "keyword.other.import.dart, storage.type.annotation.dart",
        "settings": {"foreground": "#d699b6"},
    },
    {"scope": "entity.other.attribute-name.class.pug", "settings": {"foreground": "#e67e80"}},
    {"scope": "storage.type.function.pug", "settings": {"foreground": "#e69875"}},
    {"scope": "entity.other.attribute-name.tag.pug", "settings": {"foreground": "#83c092"}},
    {
        "scope": "entity.name.tag.pug, storage.type.import.include.pug",
        "settings": {"foreground": "#d699b6"},
    },
    {
        "scope": (
            "meta.function-call.c, storage.modifier.array.bracket.square.c, "
            "meta.function.definition.parameters.c"
        ),
        "settings": {"foreground": "#d3c6aa"},
    },
    {
        "scope": (
            "punctuation.separator.dot-access.c, constant.character.escape.line-continuation.c"
        ),
        "settings": {"foreground": "#859289"},
    },
    {
        "scope": (
            "keyword.control.directive.include.c, punctuation.definition.directive.c, "
            "keyword.control.directive.pragma.c, keyword.control.directive.line.c, "
            "keyword.control.directive.define.c, keyword.control.directive.conditional.c, "
            "keyword.control.directive.diagnostic.error.c, keyword.control.directive.undef.c, "
            "keyword.control.directive.conditional.ifdef.c, keyword.control.directive.endif.c, "
            "keyword.control.directive.conditional.ifndef.c, "
            "keyword.control.directive.conditional.if.c, keyword.control.directive.else.c"
        ),
        "settings": {"foreground": "#e67e80"},
    },
    {"scope": "punctuation.separator.pointer-access.c", "settings": {"foreground": "#e69875"}},
    {"scope": "variable.other.member.c", "settings": {"foreground": "#83c092"}},
    {
        "scope": (
            "meta.function-call.cpp, storage.modifier.array.bracket.square.cpp, "
            "meta.function.definition.parameters.cpp, meta.body.function.definition.cpp"
        ),
        "settings": {"foreground": "#d3c6aa"},
    },
    {
        "scope": (
            "punctuation.separator.dot-access.cpp, constant.character.escape.line-continuation.cpp"
        ),
        "settings": {"foreground": "#859289"},
    },
    {
        "scope": (
            "keyword.control.directive.include.cpp, punctuation.definition.directive.cpp, "
            "keyword.control.directive.pragma.cpp, keyword.control.directive.line.cpp, "
            "keyword.control.directive.define.cpp, keyword.control.directive.conditional.cpp, "
            "keyword.control.directive.diagnostic.error.cpp, keyword.control.directive.undef.cpp, "
            "keyword.control.directive.conditional.ifdef.cpp, keyword.control.directive.endif.cpp, "
            "keyword.control.directive.conditional.ifndef.cpp, "
            "keyword.control.directive.conditional.if.cpp, keyword.control.directive.else.cpp, "
            "storage.type.namespace.definition.cpp, keyword.other.using.directive.cpp, "
            "storage.type.struct.cpp"
        ),
        "settings": {"foreground": "#e67e80"},
    },
    {
        "scope": (
            "punctuation.separator.pointer-access.cpp, "
            "punctuation.section.angle-brackets.begin.template.call.cpp, "
            "punctuation.section.angle-brackets.end.template.call.cpp"
        ),
        "settings": {"foreground": "#e69875"},
    },
    {"scope": "variable.other.member.cpp", "settings": {"foreground": "#83c092"}},
    {"scope": "keyword.other.using.cs", "settings": {"foreground": "#e67e80"}},
    {
        "scope": (
            "keyword.type.cs, constant.character.escape.cs, "
            "punctuation.definition.interpolation.begin.cs, "
            "punctuation.definition.interpolation.end.cs"
        ),
        "settings": {"foreground": "#dbbc7f"},
    },
    {
        "scope": (
            "string.quoted.double.cs, string.quoted.single.cs, "
            "punctuation.definition.string.begin.cs, punctuation.definition.string.end.cs"
        ),
        "settings": {"foreground": "#a7c080"},
    },
    {"scope": "variable.other.object.property.cs", "settings": {"foreground": "#83c092"}},
    {"scope": "entity.name.type.namespace.cs", "settings": {"foreground": "#d699b6"}},
    {
        "scope": "keyword.symbol.fsharp, constant.language.unit.fsharp",
        "settings": {"foreground": "#d3c6aa"},
    },
    {
        "scope": "keyword.format.specifier.fsharp, entity.name.type.fsharp",
        "settings": {"foreground": "#dbbc7f"},
    },
    {
        "scope": (
            "string.quoted.double.fsharp, string.quoted.single.fsharp, "
            "punctuation.definition.string.begin.fsharp, punctuation.definition.string.end.fsharp"
        ),
        "settings": {"foreground": "#a7c080"},
    },
    {"scope": "entity.name.section.fsharp", "settings": {"foreground": "#7fbbb3"}},
    {"scope": "support.function.attribute.fsharp", "settings": {"foreground": "#d699b6"}},
    {
        "scope": "punctuation.separator.java, punctuation.separator.period.java",
        "settings": {"foreground": "#859289"},
    },
    {
        "scope": "keyword.other.import.java, keyword.other.package.java",
        "settings": {"foreground": "#e67e80"},
    },
    {
        "scope": "storage.type.function.arrow.java, keyword.control.ternary.java",
        "settings": {"foreground": "#e69875"},
    },
    {"scope": "variable.other.property.java", "settings": {"foreground": "#83c092"}},
    {
        "scope": (
            "variable.language.wildcard.java, storage.modifier.import.java, "
            "storage.type.annotation.java, punctuation.definition.annotation.java, "
            "storage.modifier.package.java, entity.name.type.module.java"
        ),
        "settings": {"foreground": "#d699b6"},
    },
    {"scope": "keyword.other.import.kotlin", "settings": {"foreground": "#e67e80"}},
    {"scope": "storage.type.kotlin", "settings": {"foreground": "#e69875"}},
    {"scope": "constant.language.kotlin", "settings": {"foreground": "#83c092"}},
    {
        "scope": "entity.name.package.kotlin, storage.type.annotation.kotlin",
        "settings": {"foreground": "#d699b6"},
    },
    {"scope": "entity.name.package.scala", "settings": {"foreground": "#d699b6"}},
    {"scope": "constant.language.scala", "settings": {"foreground": "#7fbbb3"}},
    {"scope": "entity.name.import.scala", "settings": {"foreground": "#83c092"}},
    {
        "scope": (
            "string.quoted.double.scala, string.quoted.single.scala, "
            "punctuation.definition.string.begin.scala, punctuation.definition.string.end.scala, "
            "string.quoted.double.interpolated.scala, string.quoted.single.interpolated.scala, "
            "string.quoted.triple.scala"
        ),
        "settings": {"foreground": "#a7c080"},
    },
    {
        "scope": "entity.name.class, entity.other.inherited-class.scala",
        "settings": {"foreground": "#dbbc7f"},
    },
    {
        "scope": "keyword.declaration.stable.scala, keyword.other.arrow.scala",
        "settings": {"foreground": "#e69875"},
    },
    {"scope": "keyword.other.import.scala", "settings": {"foreground": "#e67e80"}},
    {
        "scope": (
            "keyword.operator.navigation.groovy, meta.method.body.java, "
            "meta.definition.method.groovy, meta.definition.method.signature.java"
        ),
        "settings": {"foreground": "#d3c6aa"},
    },
    {"scope": "punctuation.separator.groovy", "settings": {"foreground": "#859289"}},
    {
        "scope": (
            "keyword.other.import.groovy, keyword.other.package.groovy, "
            "keyword.other.import.static.groovy"
        ),
        "settings": {"foreground": "#e67e80"},
    },
    {"scope": "storage.type.def.groovy", "settings": {"foreground": "#e69875"}},
    {
        "scope": "variable.other.interpolated.groovy, meta.method.groovy",
        "settings": {"foreground": "#a7c080"},
    },
    {
        "scope": "storage.modifier.import.groovy, storage.modifier.package.groovy",
        "settings": {"foreground": "#83c092"},
    },
    {"scope": "storage.type.annotation.groovy", "settings": {"foreground": "#d699b6"}},
    {"scope": "keyword.type.go", "settings": {"foreground": "#e67e80"}},
    {"scope": "entity.name.package.go", "settings": {"foreground": "#83c092"}},
    {"scope": "keyword.import.go, keyword.package.go", "settings": {"foreground": "#d699b6"}},
    {"scope": "entity.name.type.mod.rust", "settings": {"foreground": "#d3c6aa"}},
    {
        "scope": "keyword.operator.path.rust, keyword.operator.member-access.rust",
        "settings": {"foreground": "#859289"},
    },
    {"scope": "storage.type.rust", "settings": {"foreground": "#e69875"}},
    {"scope": "support.constant.core.rust", "settings": {"foreground": "#83c092"}},
    {
        "scope": "meta.attribute.rust, variable.language.rust, storage.type.module.rust",
        "settings": {"foreground": "#d699b6"},
    },
    {
        "scope": "meta.function-call.swift, support.function.any-method.swift",
        "settings": {"foreground": "#d3c6aa"},
    },
    {"scope": "support.variable.swift", "settings": {"foreground": "#83c092"}},
    {"scope": "keyword.operator.class.php", "settings": {"foreground": "#d3c6aa"}},
    {"scope": "storage.type.trait.php", "settings": {"foreground": "#e69875"}},
    {
        "scope": "constant.language.php, support.other.namespace.php",
        "settings": {"foreground": "#83c092"},
    },
    {
        "scope": (
            "storage.type.modifier.access.control.public.cpp, "
            "storage.type.modifier.access.control.private.cpp"
        ),
        "settings": {"foreground": "#7fbbb3"},
    },
    {
        "scope": "keyword.control.import.include.php, storage.type.php",
        "settings": {"foreground": "#d699b6"},
    },
    {"scope": "meta.function-call.arguments.python", "settings": {"foreground": "#d3c6aa"}},
    {
        "scope": "punctuation.definition.decorator.python, punctuation.separator.period.python",
        "settings": {"foreground": "#859289"},
    },
    {"scope": "constant.language.python", "settings": {"foreground": "#83c092"}},
    {
        "scope": "keyword.control.import.python, keyword.control.import.from.python",
        "settings": {"foreground": "#d699b6"},
    },
    {"scope": "constant.language.lua", "settings": {"foreground": "#83c092"}},
    {"scope": "entity.name.class.lua", "settings": {"foreground": "#7fbbb3"}},
    {"scope": "meta.function.method.with-arguments.ruby", "settings": {"foreground": "#d3c6aa"}},
    {"scope": "punctuation.separator.method.ruby", "settings": {"foreground": "#859289"}},
    {
        "scope": "keyword.control.pseudo-method.ruby, storage.type.variable.ruby",
        "settings": {"foreground": "#e69875"},
    },
    {"scope": "keyword.other.special-method.ruby", "settings": {"foreground": "#a7c080"}},
    {
        "scope": "keyword.control.module.ruby, punctuation.definition.constant.ruby",
        "settings": {"foreground": "#d699b6"},
    },
    {
        "scope": (
            "string.regexp.character-class.ruby,string.regexp.interpolated.ruby,"
            "punctuation.definition.character-class.ruby,string.regexp.group.ruby, "
            "punctuation.section.regexp.ruby, punctuation.definition.group.ruby"
        ),
        "settings": {"foreground": "#dbbc7f"},
    },
    {"scope": "variable.other.constant.ruby", "settings": {"foreground": "#7fbbb3"}},
    {
        "scope": (
            "keyword.other.arrow.haskell, keyword.other.big-arrow.haskell, "
            "keyword.other.double-colon.haskell"
        ),
        "settings": {"foreground": "#e69875"},
    },
    {"scope": "storage.type.haskell", "settings": {"foreground": "#dbbc7f"}},
    {
        "scope": (
            "constant.other.haskell, string.quoted.double.haskell, string.quoted.single.haskell, "
            "punctuation.definition.string.begin.haskell, punctuation.definition.string.end.haskell"
        ),
        "settings": {"foreground": "#a7c080"},
    },
    {"scope": "entity.name.function.haskell", "settings": {"foreground": "#7fbbb3"}},
    {
        "scope": "entity.name.namespace, meta.preprocessor.haskell",
        "settings": {"foreground": "#83c092"},
    },
    {
        "scope": "keyword.control.import.julia, keyword.control.export.julia",
        "settings": {"foreground": "#e67e80"},
    },
    {"scope": "keyword.storage.modifier.julia", "settings": {"foreground": "#e69875"}},
    {"scope": "constant.language.julia", "settings": {"foreground": "#83c092"}},
    {"scope": "support.function.macro.julia", "settings": {"foreground": "#d699b6"}},
    {"scope": "keyword.other.period.elm", "settings": {"foreground": "#d3c6aa"}},
    {"scope": "storage.type.elm", "settings": {"foreground": "#dbbc7f"}},
    {"scope": "keyword.other.r", "settings": {"foreground": "#e69875"}},
    {"scope": "entity.name.function.r, variable.function.r", "settings": {"foreground": "#a7c080"}},
    {"scope": "constant.language.r", "settings": {"foreground": "#83c092"}},
    {"scope": "entity.namespace.r", "settings": {"foreground": "#d699b6"}},
    {
        "scope": (
            "punctuation.separator.module-function.erlang, "
            "punctuation.section.directive.begin.erlang"
        ),
        "settings": {"foreground": "#859289"},
    },
    {
        "scope": "keyword.control.directive.erlang, keyword.control.directive.define.erlang",
        "settings": {"foreground": "#e67e80"},
    },
    {"scope": "entity.name.type.class.module.erlang", "settings": {"foreground": "#dbbc7f"}},
    {
        "scope": (
            "string.quoted.double.erlang, string.quoted.single.erlang, "
            "punctuation.definition.string.begin.erlang, punctuation.definition.string.end.erlang"
        ),
        "settings": {"foreground": "#a7c080"},
    },
    {
        "scope": (
            "keyword.control.directive.export.erlang, keyword.control.directive.module.erlang, "
            "keyword.control.directive.import.erlang, keyword.control.directive.behaviour.erlang"
        ),
        "settings": {"foreground": "#d699b6"},
    },
    {
        "scope": "variable.other.readwrite.module.elixir, punctuation.definition.variable.elixir",
        "settings": {"foreground": "#83c092"},
    },
    {"scope": "constant.language.elixir", "settings": {"foreground": "#7fbbb3"}},
    {"scope": "keyword.control.module.elixir", "settings": {"foreground": "#d699b6"}},
    {"scope": "entity.name.type.value-signature.ocaml", "settings": {"foreground": "#d3c6aa"}},
    {"scope": "keyword.other.ocaml", "settings": {"foreground": "#e69875"}},
    {"scope": "constant.language.variant.ocaml", "settings": {"foreground": "#83c092"}},
    {
        "scope": "storage.type.sub.perl, storage.type.declare.routine.perl",
        "settings": {"foreground": "#e67e80"},
    },
    {"scope": "meta.function.lisp", "settings": {"foreground": "#d3c6aa"}},
    {"scope": "storage.type.function-type.lisp", "settings": {"foreground": "#e67e80"}},
    {"scope": "keyword.constant.lisp", "settings": {"foreground": "#a7c080"}},
    {"scope": "entity.name.function.lisp", "settings": {"foreground": "#83c092"}},
    {
        "scope": (
            "constant.keyword.clojure, support.variable.clojure, meta.definition.variable.clojure"
        ),
        "settings": {"foreground": "#a7c080"},
    },
    {"scope": "entity.global.clojure", "settings": {"foreground": "#d699b6"}},
    {"scope": "entity.name.function.clojure", "settings": {"foreground": "#7fbbb3"}},
    {
        "scope": "meta.scope.if-block.shell, meta.scope.group.shell",
        "settings": {"foreground": "#d3c6aa"},
    },
    {
        "scope": "support.function.builtin.shell, entity.name.function.shell",
        "settings": {"foreground": "#dbbc7f"},
    },
    {
        "scope": (
            "string.quoted.double.shell, string.quoted.single.shell, "
            "punctuation.definition.string.begin.shell, punctuation.definition.string.end.shell, "
            "string.unquoted.heredoc.shell"
        ),
        "settings": {"foreground": "#a7c080"},
    },
    {
        "scope": (
            "keyword.control.heredoc-token.shell, variable.other.normal.shell, "
            "punctuation.definition.variable.shell, variable.other.special.shell, "
            "variable.other.positional.shell, variable.other.bracket.shell"
        ),
        "settings": {"foreground": "#d699b6"},
    },
    {"scope": "support.function.builtin.fish", "settings": {"foreground": "#e67e80"}},
    {"scope": "support.function.unix.fish", "settings": {"foreground": "#e69875"}},
    {
        "scope": (
            "variable.other.normal.fish, punctuation.definition.variable.fish, "
            "variable.other.fixed.fish, variable.other.special.fish"
        ),
        "settings": {"foreground": "#7fbbb3"},
    },
    {
        "scope": (
            "string.quoted.double.fish, punctuation.definition.string.end.fish, "
            "punctuation.definition.string.begin.fish, string.quoted.single.fish"
        ),
        "settings": {"foreground": "#a7c080"},
    },
    {"scope": "constant.character.escape.single.fish", "settings": {"foreground": "#d699b6"}},
    {"scope": "punctuation.definition.variable.powershell", "settings": {"foreground": "#859289"}},
    {
        "scope": (
            "entity.name.function.powershell, support.function.attribute.powershell, "
            "support.function.powershell"
        ),
        "settings": {"foreground": "#dbbc7f"},
    },
    {
        "scope": (
            "string.quoted.single.powershell, string.quoted.double.powershell, "
            "punctuation.definition.string.begin.powershell, "
            "punctuation.definition.string.end.powershell, string.quoted.double.heredoc.powershell"
        ),
        "settings": {"foreground": "#a7c080"},
    },
    {"scope": "variable.other.member.powershell", "settings": {"foreground": "#83c092"}},
    {"scope": "string.unquoted.alias.graphql", "settings": {"foreground": "#d3c6aa"}},
    {"scope": "keyword.type.graphql", "settings": {"foreground": "#e67e80"}},
    {"scope": "entity.name.fragment.graphql", "settings": {"foreground": "#d699b6"}},
    {"scope": "entity.name.function.target.makefile", "settings": {"foreground": "#e69875"}},
    {"scope": "variable.other.makefile", "settings": {"foreground": "#dbbc7f"}},
    {"scope": "meta.scope.prerequisites.makefile", "settings": {"foreground": "#a7c080"}},
    {"scope": "string.source.cmake", "settings": {"foreground": "#a7c080"}},
    {"scope": "entity.source.cmake", "settings": {"foreground": "#83c092"}},
    {"scope": "storage.source.cmake", "settings": {"foreground": "#d699b6"}},
    {"scope": "punctuation.definition.map.viml", "settings": {"foreground": "#859289"}},
    {"scope": "storage.type.map.viml", "settings": {"foreground": "#e69875"}},
    {
        "scope": "constant.character.map.viml, constant.character.map.key.viml",
        "settings": {"foreground": "#a7c080"},
    },
    {"scope": "constant.character.map.special.viml", "settings": {"foreground": "#7fbbb3"}},
    {
        "scope": "constant.language.tmux, constant.numeric.tmux",
        "settings": {"foreground": "#a7c080"},
    },
    {
        "scope": "entity.name.function.package-manager.dockerfile",
        "settings": {"foreground": "#e69875"},
    },
    {"scope": "keyword.operator.flag.dockerfile", "settings": {"foreground": "#dbbc7f"}},
    {
        "scope": "string.quoted.double.dockerfile, string.quoted.single.dockerfile",
        "settings": {"foreground": "#a7c080"},
    },
    {"scope": "constant.character.escape.dockerfile", "settings": {"foreground": "#83c092"}},
    {
        "scope": "entity.name.type.base-image.dockerfile, entity.name.image.dockerfile",
        "settings": {"foreground": "#d699b6"},
    },
    {"scope": "punctuation.definition.separator.diff", "settings": {"foreground": "#859289"}},
    {
        "scope": "markup.deleted.diff, punctuation.definition.deleted.diff",
        "settings": {"foreground": "#e67e80"},
    },
    {
        "scope": "meta.diff.range.context, punctuation.definition.range.diff",
        "settings": {"foreground": "#e69875"},
    },
    {"scope": "meta.diff.header.from-file", "settings": {"foreground": "#dbbc7f"}},
    {
        "scope": "markup.inserted.diff, punctuation.definition.inserted.diff",
        "settings": {"foreground": "#a7c080"},
    },
    {
        "scope": "markup.changed.diff, punctuation.definition.changed.diff",
        "settings": {"foreground": "#7fbbb3"},
    },
    {"scope": "punctuation.definition.from-file.diff", "settings": {"foreground": "#d699b6"}},
    {
        "scope": "entity.name.section.group-title.ini, punctuation.definition.entity.ini",
        "settings": {"foreground": "#e67e80"},
    },
    {"scope": "punctuation.separator.key-value.ini", "settings": {"foreground": "#e69875"}},
    {
        "scope": (
            "string.quoted.double.ini, string.quoted.single.ini, "
            "punctuation.definition.string.begin.ini, punctuation.definition.string.end.ini"
        ),
        "settings": {"foreground": "#a7c080"},
    },
    {"scope": "keyword.other.definition.ini", "settings": {"foreground": "#83c092"}},
    {"scope": "support.function.aggregate.sql", "settings": {"foreground": "#dbbc7f"}},
    {
        "scope": (
            "string.quoted.single.sql, punctuation.definition.string.end.sql, "
            "punctuation.definition.string.begin.sql, string.quoted.double.sql"
        ),
        "settings": {"foreground": "#a7c080"},
    },
    {"scope": "support.type.graphql", "settings": {"foreground": "#dbbc7f"}},
    {"scope": "variable.parameter.graphql", "settings": {"foreground": "#7fbbb3"}},
    {"scope": "constant.character.enum.graphql", "settings": {"foreground": "#83c092"}},
    {
        "scope": (
            "punctuation.support.type.property-name.begin.json, "
            "punctuation.support.type.property-name.end.json, "
            "punctuation.separator.dictionary.key-value.json, "
            "punctuation.definition.string.begin.json, punctuation.definition.string.end.json, "
            "punctuation.separator.dictionary.pair.json, punctuation.separator.array.json"
        ),
        "settings": {"foreground": "#859289"},
    },
    {"scope": "support.type.property-name.json", "settings": {"foreground": "#e69875"}},
    {"scope": "string.quoted.double.json", "settings": {"foreground": "#a7c080"}},
    {
        "scope": "punctuation.separator.key-value.mapping.yaml",
        "settings": {"foreground": "#859289"},
    },
    {
        "scope": (
            "string.unquoted.plain.out.yaml, string.quoted.single.yaml, string.quoted.double.yaml, "
            "punctuation.definition.string.begin.yaml, punctuation.definition.string.end.yaml, "
            "string.unquoted.plain.in.yaml, string.unquoted.block.yaml"
        ),
        "settings": {"foreground": "#a7c080"},
    },
    {
        "scope": (
            "punctuation.definition.anchor.yaml, punctuation.definition.block.sequence.item.yaml"
        ),
        "settings": {"foreground": "#83c092"},
    },
    {"scope": "keyword.key.toml", "settings": {"foreground": "#e69875"}},
    {
        "scope": (
            "string.quoted.single.basic.line.toml, string.quoted.single.literal.line.toml, "
            "punctuation.definition.keyValuePair.toml"
        ),
        "settings": {"foreground": "#a7c080"},
    },
    {"scope": "constant.other.boolean.toml", "settings": {"foreground": "#7fbbb3"}},
    {
        "scope": (
            "entity.other.attribute-name.table.toml, punctuation.definition.table.toml, "
            "entity.other.attribute-name.table.array.toml, punctuation.definition.table.array.toml"
        ),
        "settings": {"foreground": "#d699b6"},
    },
    {
        "scope": "comment, string.comment, punctuation.definition.comment",
        "settings": {"foreground": "#859289", "fontStyle": "italic"},
    },
]

# Presets מיוחדים לייצוא (בנוסף לאלו שבגלריה)
#
# מפתחות אופציונליים של ערכה, מעבר למשתנים:
# - ``syntax_css``: הדגשת תחביר בלבד (כללי ``.highlight``).
# - ``hljs_css``: הדגשת תחביר לקוד שמרונדר בדפדפן ב-highlight.js — רק בשלד של הייצוא מהעורך הציבורי
#   (``render_editor_export_skeleton``). הכללים כתובים תחת ``EXPORT_HLJS_SELECTOR_PREFIX``.
# - ``extra_css``: עיצוב ופריסה שנטענים רק כשהערכה נבחרה — צורה שמשתנים לא מבטאים
#   (רדיוס, משקל גופן, קו במקום underline). ``export/styled_document.html`` עוטפת אותו
#   ב-``@media screen``, כך שכללי ה-``@media print`` שלה חלים גם על ערכה שדורסת את
#   ``pre`` ו-``code``. כל כלל צריך selector שווה או חזק מזה שבתבנית. ``get_export_theme``
#   קורא אותו רק מכאן: לא מערכות משתמש שב-DB ולא מ-JSON של VS Code.
EXPORT_PRESETS = {
    "tech-guide-dark": {
        "id": "tech-guide-dark",
        "name": "Tech Guide Dark",
        "description": "עיצוב טכני כהה מקצועי - מושלם למדריכים ותיעוד",
        "category": "dark",
        "variables": {
            # רקעים (מבוססים על editor.background, sideBar.background)
            "--bg-primary": "#0f0f23",
            "--bg-secondary": "#16213e",
            "--bg-tertiary": "#1a1a2e",

            # טקסט (מבוססים על editor.foreground)
            "--text-primary": "#c3cee3",
            "--text-secondary": "#c3cee3",
            "--text-muted": "#3d5a80",
            "--text-heading": "#eeeeee",

            # צבעי מותג
            "--primary": "#0088cc",
            "--primary-hover": "#0099dd",
            "--primary-light": "#0088cc26",
            "--secondary": "#9b59b6",

            # גבולות וצללים
            "--border-color": "#3d5a80",
            "--shadow-color": "rgba(0, 0, 0, 0.4)",

            # סטטוסים (מבוססים על terminal colors)
            "--success": "#2ecc71",
            "--warning": "#f39c12",
            "--error": "#e74c3c",
            "--danger-bg": "#e74c3c",
            "--danger-border": "#c0392b",

            # קוד (מבוססים על terminal.background)
            "--code-bg": "#0f0f23",
            "--code-text": "#7fdbca",
            "--code-border": "#3d5a80",
            "--code-line-highlight": "#16213e",

            # קישורים
            "--link-color": "#0088cc",

            # כרטיסים
            "--card-bg": "#16213e",
            "--card-border": "#3d5a80",

            # Alerts
            "--alert-info-border": "#0088cc",
            "--alert-info-bg": "rgba(0, 136, 204, 0.08)",
            "--alert-warning-border": "#f39c12",
            "--alert-warning-bg": "rgba(243, 156, 18, 0.08)",
            "--alert-success-border": "#2ecc71",
            "--alert-success-bg": "rgba(46, 204, 113, 0.08)",
            "--alert-danger-border": "#e74c3c",
            "--alert-danger-bg": "rgba(231, 76, 60, 0.08)",

            # כפתורים (מבוססים על button.background)
            "--btn-bg": "#0088cc",
            "--btn-hover-bg": "#0099dd",
            "--btn-color": "#ffffff",

            # Copy Button
            "--copy-btn-bg": "rgba(255, 255, 255, 0.1)",
            "--copy-btn-hover-bg": "#0088cc",
            "--copy-btn-success-bg": "#2ecc71",
        },
        # Syntax highlighting CSS (מבוסס על tokenColors מה-JSON)
        "syntax_css": _VSCODE_DARK_PLUS_SYNTAX_CSS.substitute(
            theme_name="Tech Guide Dark", heading_color="#0088cc"
        ),
    },
    "clean-light": {
        "id": "clean-light",
        "name": "Clean Light",
        "description": "עיצוב בהיר ונקי - קריא ומודרני",
        "category": "light",
        "variables": {
            "--bg-primary": "#ffffff",
            "--bg-secondary": "#f8f9fa",
            "--bg-tertiary": "#e9ecef",
            "--text-primary": "#212529",
            "--text-secondary": "#495057",
            "--text-muted": "#6c757d",
            "--primary": "#0d6efd",
            "--primary-hover": "#0b5ed7",
            "--primary-light": "#0d6efd26",
            "--secondary": "#6c757d",
            "--border-color": "#dee2e6",
            "--shadow-color": "rgba(0, 0, 0, 0.1)",
            "--success": "#198754",
            "--warning": "#ffc107",
            "--error": "#dc3545",
            "--danger-bg": "#dc3545",
            "--danger-border": "#b02a37",
            "--code-bg": "#f8f9fa",
            "--code-text": "#212529",
            "--code-border": "#dee2e6",
            "--link-color": "#0d6efd",
            "--card-bg": "#ffffff",
            "--card-border": "#dee2e6",
        },
    },
    "minimal": {
        "id": "minimal",
        "name": "Minimal",
        "description": "עיצוב מינימליסטי - פשוט ואלגנטי",
        "category": "light",
        "variables": {
            "--bg-primary": "#fafafa",
            "--bg-secondary": "#f5f5f5",
            "--bg-tertiary": "#eeeeee",
            "--text-primary": "#333333",
            "--text-secondary": "#666666",
            "--text-muted": "#999999",
            "--primary": "#333333",
            "--primary-hover": "#000000",
            "--primary-light": "#33333326",
            "--secondary": "#666666",
            "--border-color": "#e0e0e0",
            "--shadow-color": "rgba(0, 0, 0, 0.05)",
            "--success": "#4caf50",
            "--warning": "#ff9800",
            "--error": "#f44336",
            "--code-bg": "#f5f5f5",
            "--code-text": "#333333",
            "--code-border": "#e0e0e0",
            "--link-color": "#1976d2",
            "--card-bg": "#ffffff",
            "--card-border": "#e0e0e0",
        },
    },
    "githits-docs": {
        "id": "githits-docs",
        "name": "GitHits Docs",
        "description": "תיעוד כהה ושקט בסגנון GitHits, עם ורוד אחד להדגשות",
        "category": "dark",
        "variables": {
            # רקעים — ה-tertiary זהה לראשי, כדי שהגרדיאנט של ה-body יהיה שטוח
            "--bg-primary": "#13161A",
            "--bg-secondary": "#1A1D22",
            "--bg-tertiary": "#13161A",

            # טקסט
            "--text-primary": "#C4CAD3",
            "--text-secondary": "#A4A0A2",
            "--text-muted": "#757173",
            "--text-heading": "#FFFFFF",

            # צבע מותג — ורוד אחד
            "--primary": "#E15B9F",
            "--primary-hover": "#FF72BE",
            "--primary-light": "#E15B9F1A",
            "--secondary": "#E15B9F",

            # גבולות וצללים
            "--border-color": "#FFFFFF1A",
            "--shadow-color": "transparent",

            # סטטוסים
            "--success": "#2AB673",
            "--warning": "#FF872F",
            "--error": "#FCA5A5",
            "--danger-bg": "#FCA5A5",
            "--danger-border": "#DC2626",

            # קוד
            "--code-bg": "#0B0C0E",
            "--code-text": "#D4D4D4",
            "--code-border": "#FFFFFF1A",

            # קישורים
            "--link-color": "#F8F4F6",

            # כרטיסים
            "--card-bg": "#FFFFFF0D",
            "--card-border": "#FFFFFF1A",

            # Alerts — גבול בצבע המצב, ורקע של אותו צבע ב-10%. מוגדרים כאן ולא
            # נשענים על ברירות המחדל שב-styled_document.html, כי שם הרקע של
            # alert-info כחול.
            "--alert-info-border": "#E15B9F",
            "--alert-info-bg": "#E15B9F1A",
            "--alert-warning-border": "#FF872F",
            "--alert-warning-bg": "#FF872F1A",
            "--alert-success-border": "#2AB673",
            "--alert-success-bg": "#2AB6731A",
            "--alert-danger-border": "#FCA5A5",
            "--alert-danger-bg": "#FCA5A51A",

            # Copy Button
            "--copy-btn-bg": "transparent",
            "--copy-btn-hover-bg": "#E15B9F",
            "--copy-btn-success-bg": "#2AB673",
        },
        "syntax_css": _VSCODE_DARK_PLUS_SYNTAX_CSS.substitute(
            theme_name="GitHits Docs", heading_color="#E15B9F"
        ),
        # הצורה של אתר התיעוד. מה שהתבנית כבר צובעת דרך המשתנים שלמעלה לא נדרס כאן.
        "extra_css": """
/* GitHits Docs - Layout */
header {
    background: var(--bg-primary);
    border-bottom: 1px solid #FF4FAE2E;
    border-radius: 0;
    box-shadow: none;
}

header h1 {
    color: var(--text-heading);
    font-weight: 500;
    letter-spacing: -0.5px;
    text-shadow: none;
}

body {
    letter-spacing: -0.2px;
}

h2 {
    color: var(--text-heading);
    font-weight: 700;
    letter-spacing: -0.025em;
    border-bottom: 1px solid var(--border-color);
}

h3 {
    color: var(--text-heading);
    font-weight: 600;
}

p {
    text-align: start;
}

a {
    color: var(--link-color);
    font-weight: 600;
    text-decoration: none;
    border-bottom: 1px solid #C03B83;
}

a:hover {
    color: var(--primary);
    text-decoration: none;
    border-bottom-color: var(--primary);
}

code {
    font-family: Consolas, "SF Mono", Menlo, Monaco, monospace;
    letter-spacing: normal;
}

:not(pre) > code {
    color: #FFB8DE;
    background: #21262D;
    border-radius: 6px;
    padding: 2px 8px;
    font-weight: 500;
}

pre {
    border-radius: 16px;
    padding: 14px 16px;
    padding-top: 2.5rem; /* מקום לכפתור ההעתקה */
    font-size: 12px;
    line-height: 1.8;
}

/* כלל ה-pre שלמעלה דורס גם את כלל ה-pre שב-@media (max-width: 768px) של התבנית, ולכן לערכה גרסת מובייל משלה */
@media (max-width: 768px) {
    pre {
        padding: 12px 14px;
        padding-top: 2.5rem;
    }
}

/* גודל קבוע: ב-em הכפתור היה קטן יחד עם הקוד */
.copy-btn {
    border: none;
    color: #FFFFFF66;
    font-size: 12px;
}

table {
    background: transparent;
    border-radius: 0;
    box-shadow: none;
}

th {
    background: transparent;
    color: var(--text-heading);
    font-weight: 600;
    border-bottom: 1px solid #44404280;
}

td {
    border-bottom: 1px solid #2B272980;
}

/* התבנית צובעת שורה במעבר עכבר דרך tr:hover td, ולכן מבטלים באותו selector */
tr:hover td {
    background: transparent;
}

details.markdown-details {
    border-radius: 12px;
    background: transparent;
}

/* הרדיוס הפנימי של המסגרת (12px פחות קו של 1px), כדי שהרקע במעבר עכבר לא יבלוט מהפינות */
summary.markdown-summary {
    font-size: 14px;
    color: #D6D3D1;
    border-radius: 11px;
}

details.markdown-details[open] > summary.markdown-summary {
    border-radius: 11px 11px 0 0;
}

summary.markdown-summary:hover {
    background: var(--card-bg);
    color: #E7E5E4;
}

/* הפס בצד ימין מגיע מהתבנית; העיגול עובר לצד שמולו (inline-end, שמאל ב-RTL) */
blockquote {
    background: var(--card-bg);
    font-style: normal;
    border-radius: 0;
    border-start-end-radius: 10px;
    border-end-end-radius: 10px;
}

.toc {
    border-radius: 12px;
}

.toc a {
    border-bottom: none;
}

.toc a:hover {
    color: var(--primary);
}

hr {
    height: 1px;
    background: var(--border-color);
}
""",
    },
    # הערכות של הייצוא מהעורך הציבורי (``webapp/markdown_editor.py``, ``EXPORT_THEME_IDS``). המשתנים הם רק
    # אלה שהתבנית קוראת, בערכים שייבוא הקובץ כערכה (``parse_vscode_theme``) נותן להם; התראות וכפתור ההעתקה
    # נשארים בברירות המחדל של התבנית.
    "morass": {
        "id": "morass",
        "name": "morass",
        "description": "כהה, ירוק-אפור, עם כותרות צהובות",
        "category": "dark",
        "variables": {
            "--bg-primary": "#313a36",
            "--bg-secondary": "#485650",
            "--bg-tertiary": "#36403b",
            "--text-primary": "#e4e3e1",
            "--text-secondary": "#e4e3e1",
            "--text-muted": "#6d6d6d",
            "--primary": "#fdec5a",
            "--primary-hover": "#6cb6ff",
            "--border-color": "#607169",
            "--shadow-color": "rgba(0, 0, 0, 0.4)",
            "--success": "#4ec9b0",
            "--warning": "#dcdcaa",
            "--error": "#f44747",
            "--code-bg": "#252c29",
            "--code-text": "#e4e3e1",
            "--code-border": "#474747",
            "--link-color": "#569cd6",
            "--card-bg": "#485650",
        },
        "syntax_css": generate_pygments_css_from_tokens(_MORASS_TOKEN_COLORS),
        "hljs_css": generate_hljs_css_from_tokens(
            _MORASS_TOKEN_COLORS, selector_prefix=EXPORT_HLJS_SELECTOR_PREFIX
        ),
    },
    "pen-paper-coffee": {
        "id": "pen-paper-coffee",
        "name": "Pen Paper Coffee UI",
        "description": "בהיר, בסגנון מחברת: נייר, עט וקפה",
        "category": "light",
        "variables": {
            "--bg-primary": "#f8f6f1",
            "--bg-secondary": "#ebe8df",
            "--bg-tertiary": "#e0dad3",
            "--text-primary": "#2b3f6a",
            "--text-secondary": "#616161",
            "--text-muted": "#9e9e9e",
            "--primary": "#6e4e44",
            "--primary-hover": "#6e4e44",
            "--border-color": "#e0dad3",
            "--shadow-color": "rgba(0, 0, 0, 0.1)",
            "--success": "#8f932b",
            "--warning": "#d08e25",
            "--error": "#c16161",
            "--code-bg": "#f3f3f3",
            "--code-text": "#333333",
            "--code-border": "#d4d4d4",
            "--link-color": "#5e78e1",
            "--card-bg": "#ebe8df",
        },
        "syntax_css": generate_pygments_css_from_tokens(_PEN_PAPER_COFFEE_TOKEN_COLORS),
        "hljs_css": generate_hljs_css_from_tokens(
            _PEN_PAPER_COFFEE_TOKEN_COLORS, selector_prefix=EXPORT_HLJS_SELECTOR_PREFIX
        ),
    },
    # בקובץ הערכה אין ``terminal.background``, ולכן ``--code-bg`` הוא ברירת המחדל הכהה של הייבוא
    # (``FALLBACK_DARK`` ב-``services/theme_parser_service.py``) — מה שייבוא הקובץ כערכה נותן.
    "everforest-dark": {
        "id": "everforest-dark",
        "name": "Everforest Dark",
        "description": "כהה ורך, בגווני יער, עם כותרות תכלת",
        "category": "dark",
        "variables": {
            "--bg-primary": "#2d353b",
            "--bg-secondary": "#343f44",
            "--bg-tertiary": "#2d353b",
            "--text-primary": "#d3c6aa",
            "--text-secondary": "#859289",
            "--text-muted": "#859289",
            "--primary": "#7fbbb3",
            "--primary-hover": "#a7c080c0",
            "--border-color": "#475258",
            "--shadow-color": "rgba(0, 0, 0, 0.4)",
            "--success": "#83c092",
            "--warning": "#bf983d",
            "--error": "#da6362",
            "--code-bg": "#1e1e1e",
            "--code-text": "#d3c6aa",
            "--code-border": "#474747",
            "--link-color": "#a7c080",
            "--card-bg": "#343f44",
        },
        "syntax_css": generate_pygments_css_from_tokens(_EVERFOREST_DARK_TOKEN_COLORS),
        "hljs_css": generate_hljs_css_from_tokens(
            _EVERFOREST_DARK_TOKEN_COLORS, selector_prefix=EXPORT_HLJS_SELECTOR_PREFIX
        ),
    },
}


def _theme_from_export_preset(preset_id: str) -> dict:
    """הערכה ש-``get_export_theme`` מחזיר עבור Export Preset.

    בונה אחד גם לערכה שנבחרה וגם ל-fallback, כדי שמפתח שנוסף לערכות (כמו
    ``extra_css``) לא ייכתב רק באחד מהם.
    """
    preset = EXPORT_PRESETS[preset_id]
    return {
        "id": preset_id,
        "name": preset["name"],
        "category": preset.get("category", "dark"),
        "variables": preset["variables"],
        "syntax_css": preset.get("syntax_css", ""),
        "extra_css": preset.get("extra_css", ""),
        "hljs_css": preset.get("hljs_css", ""),
        # ערכה עם צבעי highlight.js משלה (``hljs_css``) נשארת בדיוק כמו שהיא; לשאר — הפלטה שנגזרת מהמשתנים
        "hljs_fallback": not preset.get("hljs_css"),
    }


def get_export_theme(
    theme_id: str,
    user_themes: Optional[list] = None,
    vscode_json: Optional[str] = None,
) -> dict:
    """
    מחזיר ערכת נושא לפי ID או JSON.

    סדר עדיפויות:
    1. VS Code JSON (אם סופק)
    2. Export Presets מיוחדים
    3. Presets מהגלריה הכללית
    4. ערכות המשתמש (מ-DB)
    5. Fallback ל-technical-dark

    Args:
        theme_id: מזהה הערכה
        user_themes: רשימת ערכות המשתמש (מ-MongoDB)
        vscode_json: תוכן JSON של ערכת VS Code (אופציונלי)

    Returns:
        dict עם name, variables, ו-syntax_css (אופציונלי). ``extra_css`` מגיע רק מ-Export Presets
        (ומה-fallback, שהוא אחד מהם). ``hljs_css`` — כללי highlight.js תחת ``EXPORT_HLJS_SELECTOR_PREFIX`` — מגיע
        מ-Export Presets שיש להם, ומערכה מיובאת מ-VS Code (קובץ ישיר או ערכת משתמש). ``hljs_fallback`` אומר אם
        הייצוא בדפדפן צריך מתחתם את הפלטה שנגזרת מהמשתנים (``export_hljs_fallback_css`` ב-``webapp/markdown_editor.py``).
    """

    # 1. VS Code JSON ישיר
    if vscode_json:
        try:
            parsed = parse_vscode_theme(vscode_json)
            theme_type = (parsed.get("type") if isinstance(parsed, dict) else None) or "dark"
            fallback = FALLBACK_DARK if str(theme_type).lower() == "dark" else FALLBACK_LIGHT
            return {
                "id": "vscode-import",
                "name": parsed.get("name", "Imported Theme"),
                "category": str(theme_type).lower(),
                "variables": parsed.get("variables", fallback),
                "syntax_css": parsed.get("syntax_css", ""),
                # כללי highlight.js ש-``parse_vscode_theme`` חישב מ-``tokenColors``, תחת הקידומת של הייצוא
                "hljs_css": rebase_hljs_css(parsed.get("syntax_css", ""), EXPORT_HLJS_SELECTOR_PREFIX),
                "hljs_fallback": True,
            }
        except Exception as e:
            logger.warning("Failed to parse VS Code theme: %s", e)

    # 2. Export Presets מיוחדים
    if theme_id in EXPORT_PRESETS:
        return _theme_from_export_preset(theme_id)

    # 3. Presets מהגלריה הכללית
    gallery_preset = get_preset_by_id(theme_id)
    if gallery_preset:
        return {
            "id": theme_id,
            "name": gallery_preset["name"],
            "category": gallery_preset.get("category", "dark"),
            "variables": gallery_preset.get("variables", FALLBACK_DARK),
            "syntax_css": gallery_preset.get("syntax_css", ""),
            # בערכות הגלריה יש רק כללי CodeMirror (``.tok-*``), ולכן הייצוא בדפדפן צובע בפלטה שנגזרת מהמשתנים
            "hljs_fallback": True,
        }

    # 4. ערכות המשתמש
    if user_themes:
        for theme in user_themes:
            if not isinstance(theme, dict):
                continue
            if theme.get("id") == theme_id:
                # 🔧 תיקון: אם ה-syntax_css שמור עם selector ישן (.source),
                # נתקן את ה-Pygments selectors בלבד (לא לפגוע ב-CodeMirror)
                stored_css = theme.get("syntax_css", "")
                if stored_css and ".source " in stored_css:
                    # תיקון Pygments CSS: [data-theme-type="custom"] .source .X → .highlight .X
                    # ⚠️ לא לגעת ב-CodeMirror שמתחיל ב-:root[data-theme-type="custom"]
                    stored_css = stored_css.replace(
                        '[data-theme-type="custom"] .source ',
                        '.highlight '
                    )
                
                return {
                    "id": theme_id,
                    "name": theme.get("name", "My Theme"),
                    "category": theme.get("category", "dark"),
                    "variables": theme.get("variables", FALLBACK_DARK),
                    "syntax_css": stored_css,
                    # ערכה מיובאת מ-VS Code שומרת כללי highlight.js תחת הקידומת של האתר. ערכה ישנה, או ערכה מבונה
                    # הערכות, בלי כללים כאלה — מקבלת רק את הפלטה, שיושבת מתחת לכללים בכל מקרה (כמו בתצוגה).
                    "hljs_css": rebase_hljs_css(stored_css, EXPORT_HLJS_SELECTOR_PREFIX),
                    "hljs_fallback": True,
                }

    # 5. Fallback
    logger.info("Theme '%s' not found, using tech-guide-dark fallback", theme_id)
    return _theme_from_export_preset("tech-guide-dark")


def list_export_presets() -> list[dict]:
    """
    מחזיר רשימת Presets זמינים לייצוא.

    Returns:
        רשימה של {id, name, description, category, preview_colors}
    """
    presets: list[dict] = []

    # Export Presets מיוחדים
    for preset_id, preset in EXPORT_PRESETS.items():
        presets.append(
            {
                "id": preset_id,
                "name": preset["name"],
                "description": preset.get("description", ""),
                "category": preset.get("category", "dark"),
                "preview_colors": _extract_preview_colors(preset.get("variables", {})),
            }
        )

    # Presets מהגלריה הכללית
    gallery_presets = list_presets()
    for p in gallery_presets:
        if p["id"] not in EXPORT_PRESETS:  # הימנעות מכפילויות
            presets.append(p)

    return presets


def _extract_preview_colors(variables: dict) -> list[str]:
    """מחלץ 3 צבעים לתצוגה מקדימה."""
    colors = []
    for key in ["--bg-primary", "--text-primary", "--primary"]:
        if key in variables:
            colors.append(variables[key])
    return colors[:3] or ["#1a1a2e", "#eeeeee", "#0088cc"]


# ============================================
# 🎨 Pygments CSS Generation
# ============================================


def get_pygments_style_for_theme(theme_id: str, theme_category: str = "dark") -> str:
    """
    מחזיר את שם ה-Pygments style המתאים לערכת נושא.

    Args:
        theme_id: מזהה הערכה
        theme_category: קטגוריית הערכה ('dark' או 'light')

    Returns:
        שם ה-Pygments style
    """
    # בדיקה במיפוי הישיר
    if theme_id in THEME_TO_PYGMENTS_STYLE:
        return THEME_TO_PYGMENTS_STYLE[theme_id]

    # fallback לפי קטגוריה
    # 🔒 הגנה מפני None (יכול להגיע מ-MongoDB עם "category": null)
    category = (theme_category or "dark").lower()
    if category == "light":
        return PYGMENTS_STYLE_LIGHT_FALLBACK
    return PYGMENTS_STYLE_DARK_FALLBACK


def generate_pygments_css(
    style_name: str = "monokai",
    css_class: str = ".highlight",
    theme_category: str = "dark",
) -> str:
    """
    מייצר CSS להדגשת תחביר באמצעות Pygments.

    Args:
        style_name: שם ה-Pygments style (לדוגמה: 'monokai', 'default', 'github-dark')
        css_class: ה-CSS class שמשמש לעטיפת הקוד (ברירת מחדל: '.highlight')
        theme_category: קטגוריית הערכה ('dark' או 'light') - משמש לבחירת fallback מתאים

    Returns:
        מחרוזת CSS עם הגדרות הצבעים להדגשת תחביר
    """
    if not HAS_PYGMENTS:
        logger.warning("Pygments not available, returning empty CSS")
        return ""

    try:
        # נסה לטעון את ה-style המבוקש
        try:
            style = get_style_by_name(style_name)
        except Exception:
            # אם לא נמצא, השתמש ב-fallback לפי הקטגוריה
            # 🔒 הגנה מפני None
            category = (theme_category or "dark").lower()
            fallback_style = (
                PYGMENTS_STYLE_LIGHT_FALLBACK
                if category == "light"
                else PYGMENTS_STYLE_DARK_FALLBACK
            )
            logger.warning(
                "Pygments style '%s' not found, using %s fallback for %s theme",
                style_name,
                fallback_style,
                category,
            )
            style = get_style_by_name(fallback_style)

        # יצירת ה-formatter עם ה-style
        formatter = HtmlFormatter(style=style, cssclass=css_class.lstrip("."))

        # קבלת הגדרות ה-CSS
        css_defs = formatter.get_style_defs(css_class)

        return css_defs

    except Exception as e:
        logger.exception("Failed to generate Pygments CSS: %s", e)
        return ""


# ============================================
# HTML Generation
# ============================================

def sanitize_css_value(value: str) -> str:
    """
    🔒 מנקה ערך CSS בודד מתווים מסוכנים.

    מונע CSS injection כמו: #fff; } body { display: none; } :root { --x:
    """
    if not value:
        return ""

    # תווים שיכולים לשבור את ההקשר של CSS value
    dangerous_chars = ["{", "}", ";", "<", ">", '"', "'", "\\", "\n", "\r"]

    clean_value = value
    for char in dangerous_chars:
        clean_value = clean_value.replace(char, "")

    # אם הערך ריק אחרי הניקוי, החזר ערך ברירת מחדל
    return clean_value.strip() or "inherit"


def generate_css_variables(variables: dict) -> str:
    """
    מייצר CSS Variables מתוך מילון.

    Returns:
        CSS string בפורמט: --var-name: value;
    """
    if not variables:
        return ""

    lines = []
    for key, value in variables.items():
        # 🔒 וולידציה של שם המשתנה - רק אותיות, מספרים, מקפים
        if not re.match(r"^--[a-zA-Z0-9\-]+$", str(key)):
            continue
        if value:
            # 🔒 סניטציה של הערך
            safe_value = sanitize_css_value(str(value))
            if safe_value:
                lines.append(f"    {key}: {safe_value};")

    return "\n".join(lines)


def sanitize_css(css_content: str) -> str:
    """
    🔒 מנקה CSS ממחרוזות מסוכנות שעלולות לפרוץ מבלוק <style>.

    מונע הזרקת </style><script>... או expression(...) וכו'.
    """
    if not css_content:
        return ""

    # רשימת דפוסים מסוכנים
    dangerous_patterns = [
        r"</style",  # סגירת תגית style
        r"<script",  # פתיחת script
        r"</script",  # סגירת script
        r"javascript:",  # JavaScript URI
        r"expression\s*\(",  # IE CSS expression
        r"@import",  # חוסם כל @import (גם url() וגם "...")
        r"behavior\s*:",  # IE behavior
        r"-moz-binding",  # Firefox XBL binding
    ]

    clean_css = css_content
    for pattern in dangerous_patterns:
        clean_css = re.sub(pattern, "/* blocked */", clean_css, flags=re.IGNORECASE)

    return clean_css


# ============================================
# 📋 סקריפט כפתור "העתק" לבלוקי קוד
# ============================================
# הסקריפט מוטמע inline בתוך ה-HTML המעוצב כדי שכפתור ההעתקה יעבוד גם בקובץ
# שמורד למחשב (file://) וגם בתצוגה מקדימה. הקבוע כאן הוא ה-Source of Truth
# היחיד: התבנית מרנדרת אותו כמו שהוא, וה-hash ל-CSP מחושב ממנו (ראו מטה),
# כך שאין סיכון לחוסר-התאמה ("drift") בין הסקריפט ל-hash.
COPY_CODE_SCRIPT = """
(function() {
    'use strict';

    // מוסיף כפתור "העתק" לכל בלוק קוד ב-root שעוד אין לו. ``window.ckAttachCopyButtons`` — לתוכן שנכנס לעמוד
    // אחרי שהסקריפט הזה רץ: קישור השיתוף מרנדר את המסמך בדפדפן, אחרי הטעינה (``styled-share-view.js``).
    function attach(root) {
        root.querySelectorAll('pre').forEach(function(codeBlock) {
            if (codeBlock.querySelector(':scope > .copy-btn')) return;
            // יצירת הכפתור
            var button = document.createElement('button');
            button.className = 'copy-btn';
            button.type = 'button';
            button.innerHTML = '📋 <span>העתק</span>';
            button.title = 'העתק קוד ללוח';
            button.setAttribute('aria-label', 'העתק קוד ללוח');

            button.addEventListener('click', function() {
                // מציאת הקוד להעתקה. textContent ולא innerText: innerText נגזר מהפריסה, ומוסיף שורה ריקה סביב כל
                // אלמנט בלוק — וקטע קוד בתוך בלוק קוד בעברית עטוף באחד כזה (rtl-code-ltr)
                var codeEl = codeBlock.querySelector('code');
                var textToCopy = codeEl ? codeEl.textContent : codeBlock.textContent;

                // ניקוי רווחים מיותרים בסוף
                textToCopy = textToCopy.trim();

                // העתקה ללוח
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(textToCopy).then(function() {
                        showSuccess(button);
                    }).catch(function() {
                        fallbackCopy(textToCopy, button);
                    });
                } else {
                    fallbackCopy(textToCopy, button);
                }
            });

            codeBlock.appendChild(button);
        });
    }
    window.ckAttachCopyButtons = attach;
    attach(document);

    // פידבק ויזואלי להצלחה
    function showSuccess(button) {
        var originalHTML = button.innerHTML;
        button.innerHTML = '✅ <span>הועתק!</span>';
        button.classList.add('success');

        setTimeout(function() {
            button.innerHTML = originalHTML;
            button.classList.remove('success');
        }, 2000);
    }

    // fallback לדפדפנים ישנים
    function fallbackCopy(text, button) {
        var textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();

        try {
            document.execCommand('copy');
            showSuccess(button);
        } catch (err) {
            alert('לא הצלחנו להעתיק את הקוד');
        }

        document.body.removeChild(textarea);
    }
})();
"""


def get_copy_script_csp_hash() -> str:
    """מחזיר את מקור ה-CSP מסוג hash (sha256) עבור סקריפט ההעתקה ה-inline.

    בעמוד השיתוף הציבורי אנחנו שומרים CSP מחמיר שחוסם כל סקריפט, ולכן צריך
    להתיר במפורש את הסקריפט המהימן היחיד שלנו. ה-hash מחושב מאותו מחרוזת
    שמוזרקת לתבנית (COPY_CODE_SCRIPT), כך שהוא תמיד תואם לתוכן בפועל.
    """
    digest = hashlib.sha256(COPY_CODE_SCRIPT.encode("utf-8")).digest()
    return "sha256-" + base64.b64encode(digest).decode("ascii")


# מקור CSP מוכן לשימוש (למשל: "sha256-...."), מחושב פעם אחת בטעינת המודול.
COPY_CODE_SCRIPT_CSP_HASH = get_copy_script_csp_hash()

#: ה-hash של גרסאות קודמות של ``COPY_CODE_SCRIPT``. קישור שיתוף מעוצב (``/shared/styled/<token>``) שומר את ה-HTML
#: כמו שנוצר, כולל הסקריפט של אז, וה-CSP שלו נבנה בכל בקשה מהרשימה הזו ומה-hash הנוכחי. בלי ה-hash הקודם, כל שינוי
#: בסקריפט היה חוסם את כפתור ההעתקה בכל קישור שכבר נוצר — וחלקם קבועים, בלי תוקף. לכן גרסה לא יוצאת מכאן.
PREVIOUS_COPY_CODE_SCRIPT_CSP_HASHES: tuple[str, ...] = (
    # עד נובמבר 2026: הסקריפט העתיק ב-innerText
    "sha256-0Wt1VA+WQC23yWC5IwGNSWIqC1UxKDvG1BMM0E4jf1I=",
    # עד 6.11.2026: הסקריפט הוסיף כפתורים רק לבלוקים שהיו בעמוד כשהוא רץ (בלי ``ckAttachCopyButtons``)
    "sha256-AKUzYU7XLfJje15Bqp0r7gwjOWmHGMJ6AromJ/9mgns=",
)


def styled_share_csp() -> str:
    """ה-CSP של עמוד השיתוף המעוצב: רק סקריפט ההעתקה, בגרסה הנוכחית ובכל גרסה קודמת שנשמרה בקישור."""
    hashes = (COPY_CODE_SCRIPT_CSP_HASH, *PREVIOUS_COPY_CODE_SCRIPT_CSP_HASHES)
    return "script-src " + " ".join(f"'{h}'" for h in hashes)


# ============================================
# 📝 השלד של הייצוא מהעורך הציבורי
# ============================================
# בעורך הציבורי (``/markdown-editor``) הטקסט לא נשלח לשרת, וגם לא בייצוא: השרת מגיש "שלד" — העמוד המעוצב
# של הערכה, עם הסמן הזה במקום התוכן — והדפדפן מרנדר את המסמך ומכניס אותו במקום הסמן
# (``webapp/static/js/markdown-editor-export.js``). הנתיב: ``markdown_editor_export_skeleton`` ב-``webapp/app.py``.

#: מה שבא במקום התוכן בשלד: הערת HTML עם הטקסט הזה. הדפדפן מחפש את ההערה (העמוד מקבל את הטקסט מהראוט)
#: ומחליף אותה במסמך.
EDITOR_EXPORT_CONTENT_MARKER_TEXT = "ck-editor-export-content"
EDITOR_EXPORT_CONTENT_MARKER = f"<!--{EDITOR_EXPORT_CONTENT_MARKER_TEXT}-->"

#: הכיתוב בתחתית הקובץ. בלי באנר עליון ובלי "Bot": לקובץ אין שם, וזה מסמך של הגולש ולא פרסומת.
EDITOR_EXPORT_FOOTER = 'נוצר אוטומטית ע"י Code Keeper'

#: הכותרת של השלד, עד שהדפדפן מחליף אותה בכותרת של המסמך.
EDITOR_EXPORT_DEFAULT_TITLE = "מסמך"

#: הכיתוב של הייצוא של המחוברים — בבאנר העליון ובתחתית, ליד שם הקובץ. בשני המסלולים שלו: ``render_styled_html``
#: (השרת) ו-``render_styled_export_skeleton`` (הדפדפן).
STYLED_EXPORT_FOOTER = 'נוצר אוטומטית ע"י Code Keeper Bot'

#: סף הבהירות (0–255) של ``--bg-primary`` שמעליו ערכה נחשבת בהירה — אותו סף ואותה נוסחה של ``pageMermaidTheme``
#: ב-``webapp/static/js/live-preview.js``, שבוחר כך את ערכת ה-Mermaid של התצוגה בערכה מותאמת. שני עותקים בשתי שפות,
#: ו-``test_the_threshold_and_formula_are_those_of_the_live_preview`` קורא את שניהם ומשווה.
_LIGHT_BACKGROUND_BRIGHTNESS = 128
_HEX_COLOR_RE = re.compile(r"^#([0-9a-fA-F]{6})")


def export_mermaid_theme(theme: dict) -> str:
    """ערכת ה-Mermaid שהתרשימים בקובץ המיוצא מצוירים בה: ``default`` (הבהירה) או ``dark``.

    לפי ``category`` של הערכה כשיש לה. לערכת משתמש אין (``import_theme`` לא שומר אותה), ולכן אצלה ההכרעה לפי הבהירות
    של ``--bg-primary``, כמו בתצוגה. ``webapp/markdown_editor.py`` (העורך הציבורי) ו-``/api/export/themes`` (חלון
    הייצוא של המחוברים) קוראים לפונקציה הזו, כדי שתהיה הכרעה אחת.
    """
    category = theme.get("category")
    if category in ("light", "dark"):
        return "default" if category == "light" else "dark"
    # ערכת משתמש מגיעה מהמסד, ו-``variables`` שאינו מילון (רשומה פגומה) נחשב כאילו אין משתנים
    variables = theme.get("variables")
    if not isinstance(variables, dict):
        variables = {}
    match = _HEX_COLOR_RE.match(str(variables.get("--bg-primary", "")).strip())
    if not match:
        return "dark"
    r, g, b = (int(match.group(1)[i:i + 2], 16) for i in (0, 2, 4))
    brightness = (r * 299 + g * 587 + b * 114) / 1000
    return "default" if brightness > _LIGHT_BACKGROUND_BRIGHTNESS else "dark"


def styled_export_title(file_name: str) -> str:
    """הכותרת של הייצוא של המחוברים — בבאנר, ב-``<title>`` ובשם הקובץ שיורד: שם הקובץ בלי ``.md`` / ``.markdown``."""
    return re.sub(r"\.(md|markdown)$", "", file_name or "Untitled", flags=re.IGNORECASE)


def styled_export_filename(title: str) -> str:
    """שם הקובץ שיורד בייצוא של המחוברים: הכותרת (שם הקובץ בלי הסיומת) בלי תווים שאינם אותיות, ספרות, רווח, מקף
    או נקודה, עד 50 תווים, ו-``.html``. כותרת שלא נשאר ממנה כלום — ``document.html``."""
    safe = re.sub(r"[^\w \-.]", "", title or "").strip()[:50] or "document"
    return f"{safe}.html"


def editor_export_meta_csp() -> str:
    """ה-CSP שבתוך הקובץ שיוצא מהעורך הציבורי (``<meta http-equiv>``).

    הקובץ נפתח אצל הגולש מהדיסק, בלי שום כותרת מהשרת, ולכן המדיניות כתובה בו. הכול חסום (``default-src 'none'``),
    חוץ ממה שהקובץ צריך:

    - ``script-src`` — רק סקריפט ההעתקה, לפי ה-hash שלו.
    - ``style-src 'unsafe-inline'`` — העיצוב כולו בתוך הקובץ, וגם ה-``style`` של KaTeX, של Mermaid ושל יישור בטבלה.
    - ``font-src data:`` — הגופנים של KaTeX מוטמעים (``katex_inline_css`` ב-``webapp/markdown_editor.py``).
    - ``img-src`` — תמונות מ-``data:`` וגם מכתובת ``http``/``https``: תמונה שהגולש שם במסמך היא חלק ממנו, ופתיחת
      הקובץ טוענת אותה מהשרת שלה, כמו כל עמוד HTML עם תמונה. בלי זה תמונה חיצונית לא הייתה מוצגת בכלל.

    ``base-uri`` חסום בנפרד, כי ``default-src`` אינו חל עליו. נמדד ב-Chromium על קובץ שנפתח מהדיסק: עם התגית סקריפט אחר
    ו-``onerror`` לא רצו, ובלעדיה רצו; ``tests/test_markdown_editor_export_browser.py`` בודק שסקריפט שנשתל בקובץ חסום,
    ושהגופנים, התרשימים והעיצוב עובדים תחתיה.
    """
    return (
        "default-src 'none'; "
        f"script-src '{COPY_CODE_SCRIPT_CSP_HASH}'; "
        "style-src 'unsafe-inline'; "
        "font-src data:; "
        "img-src data: http: https:; "
        "base-uri 'none'"
    )


def _admonition_groups() -> dict[str, list[str]]:
    """קבוצת צבע ← סוגי ההתראות שבה, לפי ``ADMONITION_TYPES`` (בסדר שלה)."""
    groups: dict[str, list[str]] = {}
    for kind, admonition in ADMONITION_TYPES.items():
        groups.setdefault(admonition.css_class, []).append(kind)
    return groups


def _export_document_context(theme: dict, footer_text: str) -> dict:
    """מה שמשותף לכל HTML מעוצב, בשני המסלולים: משתני הערכה, ``extra_css``, שם הערכה, הכיתוב בתחתית, וסקריפט ההעתקה."""
    return {
        "css_variables": generate_css_variables(theme.get("variables", {})),
        # עיצוב ופריסה של הערכה. ``get_export_theme`` מחזיר אותו רק מ-EXPORT_PRESETS,
        # ובכל זאת הוא עובר אותה סניטציה כמו syntax_css לפני שהוא נכנס לבלוק <style>
        "extra_css": sanitize_css(theme.get("extra_css", "")),
        "theme_name": theme.get("name", "Custom"),
        "footer_text": footer_text,
        "copy_script": COPY_CODE_SCRIPT,
    }


def _render_export_document(**context) -> str:
    """מרנדר את ``export/styled_document.html`` — התבנית האחת של HTML מעוצב, לשני המסלולים."""
    # ייבוא מאוחר כדי לאפשר שימוש בפונקציות אחרות גם בלי Flask (למשל בטסטים)
    from flask import render_template

    return render_template("export/styled_document.html", **context)


def _render_browser_export_skeleton(
    theme: dict,
    *,
    title: str,
    footer_text: str,
    show_header: bool,
    katex_css: str,
    hljs_fallback_css: str,
    share_source: dict | None = None,
) -> str:
    """שלד שהדפדפן מכניס לתוכו את המסמך — המשותף לייצוא מהעורך הציבורי, לייצוא של המחוברים ולקישור השיתוף.

    שונה מ-``render_styled_html`` (``editor_export`` בתבנית): עם ``EDITOR_EXPORT_CONTENT_MARKER`` במקום התוכן, העיצוב
    של markdown-it (``export/_editor_export_styles.css``), הדגשת highlight.js (``hljs_css`` של הערכה, ומתחתיו
    ``hljs_fallback_css`` כשהערכה צריכה אותו) ו-CSP בתוך הקובץ — ובלי כללי Pygments, כי הקוד מסומן ב-highlight.js.

    ``share_source`` — לעמוד של קישור השיתוף (``render_styled_share_page``): הטקסט, ערכת ה-Mermaid וטקסט ההערה, שהעמוד
    מרנדר בעצמו. אז אין CSP בתוך העמוד: הוא מוגש מהשרת עם כותרת (``styled_share_page_csp``), ומדיניות בתוך העמוד הייתה
    נאכפת יחד איתה וחוסמת את הסקריפטים שהוא טוען.
    """
    return _render_export_document(
        **_export_document_context(theme, footer_text),
        title=title,
        content=EDITOR_EXPORT_CONTENT_MARKER,
        toc_html="",
        syntax_css="",
        editor_export=True,
        show_header=show_header,
        meta_csp="" if share_source else editor_export_meta_csp(),
        share_source=share_source,
        admonition_groups=_admonition_groups(),
        hljs_css=sanitize_css(theme.get("hljs_css", "")),
        hljs_fallback_css=sanitize_css(hljs_fallback_css) if theme.get("hljs_fallback") else "",
        katex_css=sanitize_css(katex_css),
    )


def render_editor_export_skeleton(theme: dict, katex_css: str = "", hljs_fallback_css: str = "") -> str:
    """השלד של הייצוא מהעורך הציבורי: העמוד המעוצב של ``theme``, עם ``EDITOR_EXPORT_CONTENT_MARKER`` במקום התוכן.

    שום קלט של הגולש לא מגיע לכאן — רק ערכה מתוך רשימה סגורה (``EXPORT_THEME_IDS`` ב-``webapp/markdown_editor.py``)
    ו-``katex_css``, ה-CSS של KaTeX עם הגופנים, שהשרת קורא מהבאנדל של התצוגה כשבמסמך יש נוסחה. בלי באנר עליון:
    לקובץ אין שם, והכותרת שלו היא הכותרת הראשונה במסמך.
    """
    return _render_browser_export_skeleton(
        theme,
        title=EDITOR_EXPORT_DEFAULT_TITLE,
        footer_text=EDITOR_EXPORT_FOOTER,
        show_header=False,
        katex_css=katex_css,
        hljs_fallback_css=hljs_fallback_css,
    )


def render_styled_export_skeleton(theme: dict, title: str, katex_css: str = "", hljs_fallback_css: str = "") -> str:
    """השלד של הייצוא של המחוברים, כשהמסמך מרונדר בדפדפן: כמו הייצוא שבשרת — באנר עליון עם ``title`` (שם הקובץ),
    ``STYLED_EXPORT_FOOTER`` ושם הערכה — אבל עם הסימון של markdown-it ו-highlight.js, כמו העורך הציבורי.

    ``theme`` הוא מה ש-``get_export_theme`` מחזיר — כל ערכה שאפשר לייצא בה, כולל ערכות המשתמש — ו-``hljs_fallback_css``
    נכנס רק לערכה שצריכה אותו (``hljs_fallback``).
    """
    return _render_browser_export_skeleton(
        theme,
        title=title,
        footer_text=STYLED_EXPORT_FOOTER,
        show_header=True,
        katex_css=katex_css,
        hljs_fallback_css=hljs_fallback_css,
    )


def styled_share_page_csp() -> str:
    """ה-CSP של עמוד קישור השיתוף מהצורה השנייה (``format`` = ``STYLED_SHARE_FORMAT_MARKDOWN`` ב-``styled_shares.py``).

    כאן Markdown של בעל הקובץ — שיכול להיות כל טקסט — מרונדר בדפדפן של מי שפותח את הקישור, בדומיין שלנו, בלי שהוא
    מחובר. ההגנה הראשונה היא המנוע עצמו (markdown-it עם ``html: false``, ‏Mermaid ב-``strict``), והמדיניות כאן היא
    השכבה השנייה: הכול חסום (``default-src 'none'``), חוץ ממה שהעמוד צריך.

    - ``script-src 'self'`` ו-hash של סקריפט ההעתקה — המנוע של התצוגה החיה מהסטטיקה שלנו, ובלי שום סקריפט inline אחר.
    - ``style-src 'unsafe-inline'``, ‏``font-src data:``, ‏``img-src data: http: https:`` — כמו בקובץ שיורד
      (``editor_export_meta_csp``, וההסבר שם).
    - ``connect-src`` חסום (דרך ``default-src``): הרינדור אינו פונה לשום כתובת. פיצ'ר שיצטרך ``fetch`` מהעמוד — ההיתר
      שלו נכתב כאן.
    - ``form-action 'none'`` — אין בעמוד טופס, ולכן גם טופס שהוזרק לא יכול לשלוח לשום מקום. עמוד שיקבל טופס — ההיתר
      נכתב כאן.
    - ``frame-ancestors 'none'`` — העמוד אינו מוטמע באתר אחר. הטמעה שתהיה פיצ'ר — ההיתר נכתב כאן.
    - ``base-uri 'none'`` — ``default-src`` אינו חל עליו.
    """
    return (
        "default-src 'none'; "
        f"script-src 'self' '{COPY_CODE_SCRIPT_CSP_HASH}'; "
        "style-src 'unsafe-inline'; "
        "font-src data:; "
        "img-src data: http: https:; "
        "base-uri 'none'; "
        "form-action 'none'; "
        "frame-ancestors 'none'"
    )


def render_styled_share_page(theme: dict, title: str, *, markdown: str, katex_css: str = "", hljs_fallback_css: str = "") -> str:
    """עמוד קישור השיתוף מהצורה השנייה: השלד של הייצוא של המחוברים (באנר עם ``title``, ``STYLED_EXPORT_FOOTER``), עם
    הטקסט ועם המנוע של התצוגה החיה, שמרנדר אותו בדפדפן של מי שפותח (``webapp/static/js/styled-share-view.js``).

    ``theme`` הוא התמונה של הערכה ששמורה בקישור; ערכת ה-Mermaid נגזרת ממנה (``export_mermaid_theme``), ולא נשמרת לידה.
    ה-CSP של העמוד: ``styled_share_page_csp``.
    """
    return _render_browser_export_skeleton(
        theme,
        title=title,
        footer_text=STYLED_EXPORT_FOOTER,
        show_header=True,
        katex_css=katex_css,
        hljs_fallback_css=hljs_fallback_css,
        share_source={
            "markdown": markdown,
            "mermaidTheme": export_mermaid_theme(theme),
            "marker": EDITOR_EXPORT_CONTENT_MARKER_TEXT,
        },
    )


def render_styled_html(
    content_html: str,
    title: str,
    theme: dict,
    toc_html: str = "",
    footer_text: str = STYLED_EXPORT_FOOTER,
) -> str:
    """
    מרנדר HTML מעוצב מלא.

    Args:
        content_html: תוכן ה-HTML (אחרי המרה מ-Markdown)
        title: כותרת המסמך
        theme: ערכת הנושא (name, variables, syntax_css, id, category, ו-extra_css
            אופציונלי — ראו ``EXPORT_PRESETS``)
        toc_html: HTML של תוכן עניינים (אופציונלי)
        footer_text: טקסט בתחתית המסמך

    Returns:
        HTML מלא מוכן להורדה
    """
    # 🎨 קבלת CSS להדגשת תחביר
    # Pygments CSS נדרש תמיד עבור בלוקי קוד בייצוא HTML
    # CodeMirror CSS (.tok-*) רלוונטי רק לעורך בדפדפן, לא לייצוא

    theme_id = theme.get("id") or ""
    # 🔒 הגנה מפני None (יכול להגיע מ-MongoDB עם "category": null)
    theme_category = theme.get("category") or "dark"

    syntax_css_raw = theme.get("syntax_css", "")

    # בדיקה אם יש Pygments CSS (כללים עם .highlight)
    has_pygments_css = syntax_css_raw and ".highlight " in syntax_css_raw

    if has_pygments_css:
        # יש CSS מוגדר עם Pygments - נשתמש בו
        syntax_css = sanitize_css(syntax_css_raw)
    else:
        # אין Pygments CSS - נייצר דינמית
        # (גם אם יש CodeMirror CSS, הוא לא רלוונטי לייצוא HTML)
        pygments_style = get_pygments_style_for_theme(theme_id, theme_category)

        # ייצור ה-CSS
        # 🔒 CSS מ-Pygments הוא בטוח (מיוצר פנימית), אבל נעביר דרך sanitize בכל מקרה
        syntax_css = sanitize_css(
            generate_pygments_css(pygments_style, ".highlight", theme_category)
        )

    return _render_export_document(
        **_export_document_context(theme, footer_text),
        title=title,
        content=content_html,
        syntax_css=syntax_css,
        toc_html=toc_html,
        show_header=True,
    )

