"""ההשוואה של צבעי התחביר שלנו מול VS Code — משותפת לטסט של המחוללים (``tests/test_vscode_token_theme.py``) ולטסט
הדפדפן (``tests/test_syntax_colors_vscode_browser.py``).

**מה יש כאן.** ``tests/fixtures/syntax_colors_vscode_reference.json`` (נוצר ב-``scripts/syntax_colors/``) מחזיק, לכל
דוגמת קוד, את המקטעים: הטקסט, שרשרת ה-scopes של VS Code, המחלקות של highlight.js ושל CodeMirror; ולכל ערכה, הצבע ש-VS Code
נותן לכל שרשרת. הפונקציות כאן מחשבות את הצבע שה-CSS שלנו נותן לכל תו — בחיקוי של כללי ה-CSS שחלים עליו — ומשוות.

**החיקוי.** כל הכללים שלנו נושאים ``!important``, ולכן בין הכללים שחלים על אותו אלמנט מכריעה הספציפיות ואחריה הסדר;
אלמנט בלי כלל משלו יורש מההורה, ובלי אף כלל בשרשרת — הצבע של הבלוק (``None`` כאן, "ברירת המחדל"). הדפדפן עצמו נמדד
בטסט הדפדפן.

**האיחודים** (``MERGES``) — טוקנים שהמחלקה שלהם צובעת גם טוקנים ש-VS Code צובע אחרת. תו שיוצא בצבע אחר מ-VS Code חייב
להיות באחד מהם, וכל אחד מהם חייב להופיע לפחות פעם אחת, כדי שהרשימה לא תתיישן.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "syntax_colors_vscode_reference.json"

#: ה-``class_names`` של כל שפה בדוגמאות — הבלוק בדוגמה נושא את השם הקנוני.
SAMPLE_LANGUAGE_CLASS = {"python": "python", "javascript": "javascript"}


def load_reference() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class _Rule:
    classes: frozenset[str]
    languages: frozenset[str] | None
    color: str
    order: int

    @property
    def specificity(self) -> int:
        return len(self.classes) + (1 if self.languages else 0)


_RULE_RE = re.compile(r"^(?P<selector>.*?)\s*\{\s*(?P<body>.*?)\s*\}\s*$")
_COLOR_RE = re.compile(r"(?:^|;\s*)color:\s*(#[0-9a-fA-F]{3,8})")
_LANG_SUFFIX_RE = re.compile(r":is\((?P<inner>[^)]*)\)$")


def parse_rules(css: str, prefix: str) -> list[_Rule]:
    """כללי הצבע שהמחוללים כתבו תחת ``prefix``, בלי הכלל הבסיסי ``.hljs``."""
    rules: list[_Rule] = []
    for order, line in enumerate(css.splitlines()):
        m = _RULE_RE.match(line.strip())
        if not m or not m.group("selector").startswith(prefix):
            continue
        selector = m.group("selector")[len(prefix):].strip()
        color = _COLOR_RE.search(m.group("body"))
        if not color or selector in (".hljs", ""):
            continue
        languages = None
        lang = _LANG_SUFFIX_RE.search(selector)
        if lang:
            languages = frozenset(re.findall(r"\.language-([a-z0-9_+-]+) \*", lang.group("inner")))
            selector = selector[: lang.start()]
        classes = frozenset(c for c in selector.split(".") if c)
        rules.append(_Rule(classes, languages, color.group(1).lower(), order))
    return rules


def _element_color(classes: set[str], rules: list[_Rule], language: str | None) -> str | None:
    best: _Rule | None = None
    for rule in rules:
        if rule.languages is not None and language not in rule.languages:
            continue
        if not rule.classes <= classes:
            continue
        if best is None or (rule.specificity, rule.order) > (best.specificity, best.order):
            best = rule
    return best.color if best else None


def color_for_path(class_path: list[list[str]], rules: list[_Rule], language: str | None) -> str | None:
    """הצבע של תו שעוטפים אותו האלמנטים ב-``class_path`` (מבחוץ פנימה): הכלל של האלמנט הפנימי ביותר שיש לו כלל."""
    for classes in reversed(class_path):
        color = _element_color(set(classes), rules, language)
        if color:
            return color
    return None


def color_for_cm_tags(tag_chains: list[list[str]], syntax_colors: dict[str, dict]) -> str | None:
    """הצבע ש-``HighlightStyle`` נותן: לכל tag, השם הראשון בשרשרת שיש לו צבע; בכמה tags — הכלל המאוחר מנצח."""
    order = {name: index for index, name in enumerate(syntax_colors)}
    best: tuple[int, str] | None = None
    for chain in tag_chains:
        for name in chain:
            if name in syntax_colors:
                if best is None or order[name] > best[0]:
                    best = (order[name], syntax_colors[name]["color"].lower())
                break
    return best[1] if best else None


@dataclass(frozen=True)
class Mismatch:
    renderer: str
    language: str
    css_class: str
    scope: str
    text: str
    ours: str | None
    vscode: str | None


def _innermost_class(class_path: list[list[str]]) -> str:
    return "." + ".".join(class_path[-1]) if class_path else "(none)"


def mismatches(
    reference: dict,
    theme_id: str,
    language: str,
    *,
    hljs_css: str | None = None,
    hljs_prefix: str = "",
    cm_css: str | None = None,
    syntax_colors: dict[str, dict] | None = None,
    default_color: str | None = None,
) -> list[Mismatch]:
    """התווים (בלי רווחים) שיוצאים אצלנו בצבע אחר מ-VS Code, ברינדור אחד: highlight.js, ‏``.tok-*`` או ``syntax_colors``.

    ``default_color`` — צבע שאצלנו פירושו "ברירת המחדל" (צבע הטקסט של הבלוק, שערכות הייצוא כותבות במפורש).
    """
    styles = reference["themes"][theme_id]
    lang_class = SAMPLE_LANGUAGE_CLASS[language]
    if hljs_css is not None:
        renderer, rules = "hljs", parse_rules(hljs_css, hljs_prefix)
    elif cm_css is not None:
        renderer, rules = "cm-class", parse_rules(cm_css, ':root[data-theme-type="custom"]')
    else:
        renderer, rules = "cm-tags", []
    default = default_color.lower() if default_color else None

    out: list[Mismatch] = []
    for seg in reference["languages"][language]:
        if not seg["text"].strip():
            continue
        vscode = style_for(styles, seg["scopes"])["fg"]
        if renderer == "hljs":
            ours = color_for_path(seg["hljs"], rules, lang_class)
            css_class = _innermost_class(seg["hljs"])
        elif renderer == "cm-class":
            classes = seg["cmClass"].split()
            ours = color_for_path([classes] if classes else [], rules, None)
            css_class = "." + ".".join(classes) if classes else "(none)"
        else:
            ours = color_for_cm_tags(seg["cmTags"], syntax_colors or {})
            css_class = "|".join(c[0] for c in seg["cmTags"] if c) or "(none)"
        # צבע הטקסט של הבלוק הוא "ברירת המחדל" בשני הצדדים: גם כלל של הערכה שצובע בדיוק בו אינו הבדל שרואים
        if ours == default:
            ours = None
        if vscode == default:
            vscode = None
        if ours != vscode:
            text = "".join(seg["text"].split())
            out.append(Mismatch(renderer, language, css_class, seg["scopes"][-1], text, ours, vscode))
    return out


def style_for(styles: dict, scopes: list[str]) -> dict:
    """ההכרעה של VS Code לשרשרת — המפתח הוא ``JSON.stringify`` של ``reference.mjs``, בלי רווחים."""
    return styles[json.dumps(scopes, separators=(",", ":"), ensure_ascii=False)]


# ---------------------------------------------------------------------------
# האיחודים המוצהרים
# ---------------------------------------------------------------------------

ANY = "*"
_UNMARKED = ("", "הטוקן לא מסומן בכלל — משתנים, אופרטורים ופיסוק — ומקבל את צבע הטקסט של הבלוק")
_ONE_CLASS = "המפענח של CodeMirror נותן תג או מחלקה אחת לטוקנים ש-VS Code מבדיל ביניהם"
_LANGUAGE_RULE = "כלל לפי שפה (``constant.language.python``): לעורך של CodeMirror אין סימון שפה"

#: האיחודים: ``(rendering, שפה, מחלקה) → (סיבה, קידומות של ה-scope הפנימי ביותר ב-VS Code)``. "מחלקה" ב-``cm-tags`` היא
#: השם הראשון בשרשרת של ה-tag. תו שיוצא בצבע אחר מ-VS Code חייב להתאים לאחת מהן.
MERGES: dict[tuple[str, str, str], tuple[str, tuple[str, ...]]] = {
    # --- highlight.js ---
    ("hljs", ANY, "(none)"): (_UNMARKED[1], (_UNMARKED[0],)),
    ("hljs", "python", ".hljs-built_in"): (
        "‏``built_in`` כולל גם טיפוסים מובנים (``list``, ‏``float``, ‏``str``); הנציג הוא הפונקציות — החלטה, נובמבר 2026",
        ("support.type.python",),
    ),
    ("hljs", "python", ".hljs-keyword"): (
        "מחלקה אחת ל-``import``, ל-``and``/``or`` ול-``def``/``class``; הנציג הוא מילות הבקרה",
        ("keyword.control.import", "keyword.operator.logical", "storage.type"),
    ),
    ("hljs", "python", ".hljs-string"): (
        "המחרוזת היא span אחד, עם הקידומת (``f``, ‏``b``, ‏``r``), המרכאות, ה-escape ותבנית ה-regex שבתוכה",
        (
            "storage.type.string",
            "punctuation.definition.string",
            "constant.character.escape",
            "keyword.operator.quantifier.regexp",
            "support.other.escape.special.regexp",
        ),
    ),
    ("hljs", "python", ".hljs-subst"): (
        "הסוגריים והביטוי בתוך f-string הם span אחד; ובתוך קריאה לפונקציה הערכה צובעת לפי הקריאה",
        ("constant.character.format.placeholder", "meta.fstring"),
    ),
    ("hljs", "python", ".hljs-params"): (
        "הסוגריים, הפסיקים, הנקודתיים וה-``=`` שבין הפרמטרים הם חלק מה-span",
        ("keyword.operator.assignment", "punctuation.definition.arguments", "punctuation.separator"),
    ),
    ("hljs", "python", ".hljs-meta"): (
        "ה-``@`` והסוגריים של decorator הם חלק מה-span",
        ("punctuation.definition.decorator", "punctuation.definition.arguments"),
    ),
    ("hljs", "python", ".hljs-number"): ("הקידומת ``0x`` היא חלק מהמספר", ("storage.type.number",)),
    ("hljs", "python", ".hljs-type"): (
        "שם מ-``typing`` מחוץ ל-annotation (בשורת ה-import), או ב-annotation של פרמטר שהערכה צובעת אחרת",
        ("source.python", "meta.indexed-name.python"),
    ),
    ("hljs", "python", ".hljs-comment"): ("סימן ההערה הוא חלק מה-span", ("punctuation.definition.comment",)),
    ("hljs", "javascript", ".hljs-keyword"): (
        "מחלקה אחת ל-``import``/``export``, ל-``const``/``class``, ל-``typeof``/``new`` ולמילות הבקרה; הנציג הוא מילות הבקרה",
        ("keyword.control.import", "keyword.control.export", "keyword.operator", "storage.type", "storage.modifier"),
    ),
    ("hljs", "javascript", ".hljs-string"): (
        "המרכאות וה-escape הם חלק מה-span",
        ("constant.character.escape", "punctuation.definition.string"),
    ),
    ("hljs", "javascript", ".hljs-subst"): ("‏``${`` ו-``}`` הם חלק מה-span", ("punctuation.definition.template-expression",)),
    ("hljs", "javascript", ".hljs-params"): (
        "ה-``=`` והפסיקים שבין הפרמטרים הם חלק מה-span",
        ("keyword.operator.assignment", "punctuation.separator"),
    ),
    ("hljs", "javascript", ".hljs-regexp"): (
        "הביטוי הוא span אחד, עם הלוכסנים, הכמתים והדגלים",
        ("keyword.operator.quantifier.regexp", "keyword.other", "punctuation.definition.string"),
    ),
    ("hljs", "javascript", ".hljs-number"): ("הנקודה העשרונית היא חלק מהמספר", ("meta.delimiter.decimal.period",)),
    ("hljs", "javascript", ".hljs-comment"): ("סימן ההערה הוא חלק מה-span", ("punctuation.definition.comment",)),
    ("hljs", "javascript", ".hljs-function"): (
        "עטיפה של פונקציית חץ, בלי צבע משלה (מחלקה מיושנת ב-highlight.js): החץ והסוגריים שבתוכה",
        ("storage.type.function.arrow", "punctuation.definition.parameters"),
    ),
    ("hljs", "javascript", ".hljs-title.class_"): (
        "שם מחלקה מסמן גם ``new X()``, ‏``Math``, ‏``JSON`` ו-``NaN``",
        ("entity.name.function", "variable.other.object", "variable.other.constant.object", "constant.language.nan"),
    ),
    ("hljs", "javascript", ".hljs-title.function_"): ("‏``constructor`` מסומן כשם פונקציה", ("storage.type",)),
    ("hljs", "javascript", ".hljs-variable.language_"): (
        "‏``console`` ו-``document`` מסומנים כמו ``this``",
        ("variable.other.object",),
    ),
    # --- CodeMirror: המחלקות של classHighlighter ---
    ("cm-class", ANY, "(none)"): (_UNMARKED[1], (_UNMARKED[0],)),
    ("cm-class", "python", ".tok-bool"): (_LANGUAGE_RULE, ("constant.language.python",)),
    ("cm-class", "python", ".tok-keyword"): (
        _ONE_CLASS,
        ("constant.language.python", "keyword.control.import", "keyword.operator.logical", "storage.type"),
    ),
    ("cm-class", "python", ".tok-comment"): (_ONE_CLASS, ("punctuation.definition.comment",)),
    ("cm-class", "python", ".tok-meta"): (_ONE_CLASS, ("punctuation.definition.decorator",)),
    ("cm-class", "python", ".tok-number"): (_ONE_CLASS, ("storage.type.number",)),
    ("cm-class", "python", ".tok-operator"): (_ONE_CLASS, ("punctuation.separator.period",)),
    ("cm-class", "python", ".tok-propertyName"): (_ONE_CLASS, ("meta.attribute", "meta.function-call.generic")),
    ("cm-class", "python", ".tok-punctuation"): (_ONE_CLASS, ("constant.character.format.placeholder",)),
    ("cm-class", "python", ".tok-string"): (
        _ONE_CLASS,
        (
            "storage.type.string",
            "punctuation.definition.string",
            "keyword.operator.quantifier.regexp",
            "support.other.escape.special.regexp",
        ),
    ),
    ("cm-class", "python", ".tok-string2"): (_ONE_CLASS, ("storage.type.string", "constant.character.escape")),
    ("cm-class", "python", ".tok-variableName"): (
        "כל שם — משתנה, פרמטר, טיפוס מובנה, קריאה ל-builtin, decorator, ובפייתון גם שם רגיל, ש-VS Code לא מסמן — מקבל אותה מחלקה",
        (
            "constant.other.caps",
            "entity.name.function.decorator",
            "entity.other.inherited-class",
            "meta.fstring",
            "meta.function-call.arguments",
            "meta.indexed-name",
            "source.python",
            "support.function.builtin",
            "support.type",
            "variable.language.special.self",
            "variable.parameter",
        ),
    ),
    ("cm-class", "python", ".tok-variableName.tok-definition"): (
        "שם של פונקציה בהגדרה מקבל את המחלקה של הגדרת משתנה",
        ("entity.name.function", "support.function.magic"),
    ),
    ("cm-class", "javascript", ".tok-atom"): (_ONE_CLASS, ("variable.language.super",)),
    ("cm-class", "javascript", ".tok-className"): (_ONE_CLASS, ("entity.name.function",)),
    ("cm-class", "javascript", ".tok-comment"): (_ONE_CLASS, ("punctuation.definition.comment",)),
    ("cm-class", "javascript", ".tok-keyword"): (
        _ONE_CLASS,
        (
            "constant.language.null",
            "keyword.control.export",
            "keyword.control.import",
            "keyword.operator",
            "storage.modifier",
            "storage.type",
            "variable.language.this",
        ),
    ),
    ("cm-class", "javascript", ".tok-number"): (_ONE_CLASS, ("meta.delimiter.decimal.period",)),
    ("cm-class", "javascript", ".tok-operator"): (_ONE_CLASS, ("punctuation.accessor",)),
    ("cm-class", "javascript", ".tok-propertyName"): (
        _ONE_CLASS,
        ("entity.name.function", "support.variable.property", "variable.other.property"),
    ),
    ("cm-class", "javascript", ".tok-propertyName.tok-definition"): (
        _ONE_CLASS,
        ("entity.name.function", "meta.object-literal.key", "storage.type"),
    ),
    ("cm-class", "javascript", ".tok-punctuation"): (
        _ONE_CLASS,
        ("meta.brace", "punctuation.definition.template-expression", "punctuation.separator.key-value", "storage.type.function.arrow"),
    ),
    ("cm-class", "javascript", ".tok-string"): (_ONE_CLASS, ("punctuation.definition.string",)),
    ("cm-class", "javascript", ".tok-string2"): (
        _ONE_CLASS,
        (
            "constant.character.escape",
            "keyword.operator.quantifier.regexp",
            "keyword.other",
            "punctuation.definition.string",
            "string.regexp",
        ),
    ),
    ("cm-class", "javascript", ".tok-variableName"): (
        _ONE_CLASS,
        ("constant.language", "entity.name.function", "entity.other.inherited-class", "support.class", "variable.other.constant.object"),
    ),
    ("cm-class", "javascript", ".tok-variableName.tok-definition"): (
        _ONE_CLASS,
        ("entity.name.function", "variable.other.constant", "variable.parameter"),
    ),
    # --- CodeMirror: HighlightStyle (syntax_colors) ---
    ("cm-tags", ANY, "(none)"): (_UNMARKED[1], (_UNMARKED[0],)),
    ("cm-tags", "python", "bool"): (_LANGUAGE_RULE, ("constant.language.python",)),
    ("cm-tags", "python", "null"): (_LANGUAGE_RULE, ("constant.language.python",)),
    ("cm-tags", "python", "brace"): (_ONE_CLASS, ("constant.character.format.placeholder",)),
    ("cm-tags", "python", "definitionKeyword"): (_ONE_CLASS, ("keyword.control", "storage.type")),
    ("cm-tags", "python", "function(propertyName)"): (_ONE_CLASS, ("meta.function-call.generic",)),
    ("cm-tags", "python", "function(variableName)"): (
        "קריאה ל-``float()`` או ל-``RuntimeError()`` היא קריאה לפונקציה בעיני CodeMirror",
        ("support.type",),
    ),
    ("cm-tags", "python", "keyword"): (_ONE_CLASS, ("keyword.control.flow",)),
    ("cm-tags", "python", "lineComment"): (_ONE_CLASS, ("punctuation.definition.comment",)),
    ("cm-tags", "python", "meta"): (_ONE_CLASS, ("punctuation.definition.decorator",)),
    ("cm-tags", "python", "modifier"): (_ONE_CLASS, ("storage.type.function.async",)),
    ("cm-tags", "python", "moduleKeyword"): (_ONE_CLASS, ("keyword.control.import",)),
    ("cm-tags", "python", "number"): (_ONE_CLASS, ("storage.type.number",)),
    ("cm-tags", "python", "operator"): (_ONE_CLASS, ("punctuation.separator.period",)),
    ("cm-tags", "python", "operatorKeyword"): (_ONE_CLASS, ("keyword.control.flow",)),
    ("cm-tags", "python", "paren"): (_ONE_CLASS, ("punctuation.definition",)),
    ("cm-tags", "python", "propertyName"): (_ONE_CLASS, ("meta.attribute",)),
    ("cm-tags", "python", "special(string)"): (_ONE_CLASS, ("storage.type.string",)),
    ("cm-tags", "python", "squareBracket"): (_ONE_CLASS, ("punctuation.definition",)),
    ("cm-tags", "python", "string"): (
        _ONE_CLASS,
        (
            "storage.type.string",
            "punctuation.definition.string",
            "keyword.operator.quantifier.regexp",
            "support.other.escape.special.regexp",
        ),
    ),
    ("cm-tags", "python", "variableName"): (
        "כל שם — משתנה, פרמטר, טיפוס מובנה, decorator, ובפייתון גם שם רגיל, ש-VS Code לא מסמן — מקבל אותו tag",
        (
            "constant.other.caps",
            "entity.name.function.decorator",
            "entity.other.inherited-class",
            "meta.fstring",
            "meta.function-call.arguments",
            "meta.indexed-name",
            "source.python",
            "support.type",
            "variable.language.special.self",
            "variable.parameter",
        ),
    ),
    ("cm-tags", "javascript", "atom"): (_ONE_CLASS, ("variable.language.super",)),
    ("cm-tags", "javascript", "blockComment"): (_ONE_CLASS, ("punctuation.definition.comment",)),
    ("cm-tags", "javascript", "lineComment"): (_ONE_CLASS, ("punctuation.definition.comment",)),
    ("cm-tags", "javascript", "brace"): (_ONE_CLASS, ("punctuation.definition.template-expression",)),
    ("cm-tags", "javascript", "className"): (_ONE_CLASS, ("entity.name.function",)),
    ("cm-tags", "javascript", "definition(propertyName)"): (
        _ONE_CLASS,
        ("entity.name.function", "meta.object-literal.key", "storage.type"),
    ),
    ("cm-tags", "javascript", "definition(variableName)"): (
        _ONE_CLASS,
        ("entity.name.function", "variable.other.constant", "variable.parameter"),
    ),
    ("cm-tags", "javascript", "definitionKeyword"): (_ONE_CLASS, ("storage.modifier", "storage.type")),
    ("cm-tags", "javascript", "keyword"): (_ONE_CLASS, ("keyword.operator.new",)),
    ("cm-tags", "javascript", "moduleKeyword"): (_ONE_CLASS, ("keyword.control.from",)),
    ("cm-tags", "javascript", "number"): (_ONE_CLASS, ("meta.delimiter.decimal.period",)),
    ("cm-tags", "javascript", "operator"): (_ONE_CLASS, ("punctuation.accessor",)),
    ("cm-tags", "javascript", "operatorKeyword"): (_ONE_CLASS, ("keyword.control.flow", "keyword.operator.expression")),
    ("cm-tags", "javascript", "paren"): (_ONE_CLASS, ("punctuation.definition.parameters",)),
    ("cm-tags", "javascript", "propertyName"): (_ONE_CLASS, ("support.variable.property", "variable.other.property")),
    ("cm-tags", "javascript", "punctuation"): (_ONE_CLASS, ("punctuation.separator.key-value", "storage.type.function.arrow")),
    ("cm-tags", "javascript", "regexp"): (
        _ONE_CLASS,
        ("keyword.operator.quantifier.regexp", "keyword.other", "punctuation.definition.string"),
    ),
    ("cm-tags", "javascript", "special(string)"): (_ONE_CLASS, ("punctuation.definition.string.template",)),
    ("cm-tags", "javascript", "string"): (_ONE_CLASS, ("punctuation.definition.string",)),
    ("cm-tags", "javascript", "variableName"): (
        _ONE_CLASS,
        ("constant.language", "entity.other.inherited-class", "support.class", "variable.other.constant.object"),
    ),
}


def scope_matches(scope: str, prefix: str) -> bool:
    return prefix == "" or scope == prefix or scope.startswith(prefix + ".")


def declared_merge(renderer: str, language: str, css_class: str, scope: str) -> tuple[str, str, str, str] | None:
    for lang in (language, ANY):
        entry = MERGES.get((renderer, lang, css_class))
        if entry:
            for prefix in entry[1]:
                if scope_matches(scope, prefix):
                    return (renderer, lang, css_class, prefix)
    return None
