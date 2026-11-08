"""הצבע של טוקן, כמו ש-VS Code מכריע אותו — מ-``tokenColors`` של ערכה ומשרשרת ה-scopes של הטוקן.

**למה הקובץ הזה קיים.** המחוללים ב-``services/theme_parser_service.py`` הופכים ערכת VS Code לכללי צבע של highlight.js
ושל CodeMirror. עד כאן הם עשו את זה אחרת מ-VS Code, בשלוש שכבות שכל אחת הסתירה את הבאה: ``scope`` שכתוב כמחרוזת עם
פסיקים לא פוצל; בורר שנכתב ל-scope צר נלקח כצבע של כל המחלקה הרחבה, והכלל הראשון שהתאים זכה; וכל מחלקה יוצגה במפה על
ידי מפתח שאינו הטוקן שהיא באמת צובעת. הקובץ הזה מחליף את שלושתן: הוא מכריע צבע בדיוק כמו VS Code, והמחוללים שואלים
אותו "איזה צבע VS Code נותן לטוקן כזה" לכל מחלקה.

**ההכרעה** היא פורט של vscode-textmate 9.3.2, הספרייה ש-VS Code צובע בה: ``parseTheme``, ``resolveParsedThemeRules``,
``ThemeTrieElement`` ו-``Theme.match`` ב-``src/theme.ts``, ``isValidHexColor``, ``strcmp`` ו-``strArrCmp`` ב-``src/utils.ts``,
והמיזוג לאורך שרשרת ה-scopes ב-``AttributedScopeStack`` (``src/grammar/grammar.ts``). ``tests/test_vscode_token_theme.py``
משווה אותה לתשובות של vscode-textmate עצמה, על כל שרשרת scopes שהדקדוקים של VS Code מייצרים בדוגמאות שבטסט.

**הנציגים** — לכל מחלקה, שרשרת ה-scopes ש-VS Code נותן לטוקן שהמחלקה צובעת. בפייתון וב-JavaScript הם נמדדו על
הדקדוקים של VS Code (``scripts/syntax_colors/``), ושם יש גם כללים לפי שפה. מחלקה שמאחדת טוקנים ש-VS Code צובע אחרת —
``built_in`` בפייתון, למשל, שכולל גם את ``print`` וגם את ``list`` — מקבלת נציג אחד, ו-``SYNTAX_COLOR_MERGES`` בטסט מונה
את האיחודים האלה.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from typing import Iterable, Sequence

# --- סגנון הגופן — אותם ערכים כמו ``FontStyle`` ב-``src/theme.ts`` ---
FONT_STYLE_NOT_SET = -1
FONT_STYLE_NONE = 0
FONT_STYLE_ITALIC = 1
FONT_STYLE_BOLD = 2
FONT_STYLE_UNDERLINE = 4
FONT_STYLE_STRIKETHROUGH = 8

_FONT_STYLE_SEGMENTS = {
    "italic": FONT_STYLE_ITALIC,
    "bold": FONT_STYLE_BOLD,
    "underline": FONT_STYLE_UNDERLINE,
    "strikethrough": FONT_STYLE_STRIKETHROUGH,
}

# ``isValidHexColor``: ‏#rgb, ‏#rgba, ‏#rrggbb, ‏#rrggbbaa — בלי רווחים מסביב (VS Code לא מנקה אותם).
_HEX_COLOR_RE = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})")


def is_valid_hex_color(value: object) -> bool:
    return isinstance(value, str) and _HEX_COLOR_RE.fullmatch(value) is not None


def _js_key(value: str) -> bytes:
    """מפתח מיון שמשווה כמו ``<`` של JavaScript — לפי יחידות UTF-16, ולא לפי code points כמו פייתון."""
    return value.encode("utf-16-be", "surrogatepass")


def _strcmp(a: str, b: str) -> int:
    ka, kb = _js_key(a), _js_key(b)
    return -1 if ka < kb else (1 if ka > kb else 0)


def _str_arr_cmp(a: tuple[str, ...] | None, b: tuple[str, ...] | None) -> int:
    # ‏``None`` ולא "ריק": ב-JavaScript מערך ריק הוא אמת, ולכן רק ``null`` נכנס לענפים האלה
    if a is None and b is None:
        return 0
    if a is None:
        return -1
    if b is None:
        return 1
    if len(a) == len(b):
        for x, y in zip(a, b):
            res = _strcmp(x, y)
            if res != 0:
                return res
        return 0
    return len(a) - len(b)


@dataclass(frozen=True)
class _ParsedRule:
    scope: str
    parent_scopes: tuple[str, ...] | None
    index: int
    font_style: int
    foreground: str | None


def parse_token_rules(token_colors: object, *, default_foreground: str | None = None) -> list[_ParsedRule]:
    """``parseTheme``: כל בורר ברשומות של ``tokenColors`` הופך לכלל.

    ``scope`` שכתוב כמחרוזת הוא רשימת בוררים מופרדים בפסיק, וכל אחד עובר trim; ``scope`` שכתוב כרשימה לא מפוצל.
    רשומה בלי ``scope`` היא כלל ברירת מחדל. ``default_foreground`` נכנס ראשון, כמו ש-VS Code מכניס את
    ``editor.foreground`` לפני ה-``tokenColors`` של הערכה.

    הקלט מגיע מקובץ שהמשתמש העלה, ולכן כל שדה נבדק לפני שקוראים ממנו: רשומה שאינה מילון, ``settings`` שאינו מילון,
    ובורר שאינו מחרוזת — מדולגים.
    """
    entries: list[object] = []
    if default_foreground is not None:
        entries.append({"settings": {"foreground": default_foreground}})
    if isinstance(token_colors, list):
        entries.extend(token_colors)

    rules: list[_ParsedRule] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        settings = entry.get("settings")
        if not settings or not isinstance(settings, dict):
            continue

        raw_scope = entry.get("scope")
        if isinstance(raw_scope, str):
            # כמו ``replace(/^[,]+/, '')`` ו-``replace(/[,]+$/, '')`` — אבל ``strip`` ולא רגקס: ‏``,+$`` על רצף ארוך של פסיקים
            # שאחריו תו אחר בודק את כל הרצף מכל נקודת התחלה (זמן ריבועי), והמחרוזת מגיעה מקובץ שהמשתמש העלה
            stripped = raw_scope.strip(",")
            scopes: list[object] = list(stripped.split(","))
        elif isinstance(raw_scope, list):
            scopes = list(raw_scope)
        else:
            scopes = [""]

        font_style = FONT_STYLE_NOT_SET
        raw_font_style = settings.get("fontStyle")
        if isinstance(raw_font_style, str):
            font_style = FONT_STYLE_NONE
            for segment in raw_font_style.split(" "):
                font_style |= _FONT_STYLE_SEGMENTS.get(segment, 0)

        raw_foreground = settings.get("foreground")
        foreground = raw_foreground if is_valid_hex_color(raw_foreground) else None

        for raw in scopes:
            if not isinstance(raw, str):
                continue
            segments = raw.strip().split(" ")
            parent_scopes: tuple[str, ...] | None = None
            if len(segments) > 1:
                parent_scopes = tuple(reversed(segments[:-1]))
            rules.append(_ParsedRule(segments[-1], parent_scopes, index, font_style, foreground))
    return rules


class _TrieRule:
    __slots__ = ("scope_depth", "parent_scopes", "font_style", "foreground")

    def __init__(self, scope_depth: int, parent_scopes: tuple[str, ...] | None, font_style: int, foreground: str | None):
        self.scope_depth = scope_depth
        self.parent_scopes: tuple[str, ...] = parent_scopes or ()
        self.font_style = font_style
        self.foreground = foreground

    def clone(self) -> "_TrieRule":
        return _TrieRule(self.scope_depth, self.parent_scopes, self.font_style, self.foreground)

    def accept_overwrite(self, scope_depth: int, font_style: int, foreground: str | None) -> None:
        if self.scope_depth <= scope_depth:
            self.scope_depth = scope_depth
        if font_style != FONT_STYLE_NOT_SET:
            self.font_style = font_style
        if foreground is not None:
            self.foreground = foreground


def _cmp_by_specificity(a: _TrieRule, b: _TrieRule) -> int:
    if a.scope_depth != b.scope_depth:
        return b.scope_depth - a.scope_depth
    ai = bi = 0
    while True:
        if ai < len(a.parent_scopes) and a.parent_scopes[ai] == ">":
            ai += 1
        if bi < len(b.parent_scopes) and b.parent_scopes[bi] == ">":
            bi += 1
        if ai >= len(a.parent_scopes) or bi >= len(b.parent_scopes):
            break
        diff = len(b.parent_scopes[bi]) - len(a.parent_scopes[ai])
        if diff != 0:
            return diff
        ai += 1
        bi += 1
    return len(b.parent_scopes) - len(a.parent_scopes)


_SPECIFICITY_KEY = functools.cmp_to_key(_cmp_by_specificity)


class _TrieElement:
    __slots__ = ("main_rule", "rules_with_parent_scopes", "children")

    def __init__(self, main_rule: _TrieRule, rules_with_parent_scopes: list[_TrieRule] | None = None):
        self.main_rule = main_rule
        self.rules_with_parent_scopes = rules_with_parent_scopes or []
        self.children: dict[str, _TrieElement] = {}

    def match(self, scope: str) -> list[_TrieRule]:
        if scope != "":
            head, _, tail = scope.partition(".")
            child = self.children.get(head)
            if child is not None:
                return child.match(tail)
        rules = self.rules_with_parent_scopes + [self.main_rule]
        return sorted(rules, key=_SPECIFICITY_KEY)

    def insert(self, scope_depth: int, scope: str, parent_scopes: tuple[str, ...] | None, font_style: int, foreground: str | None) -> None:
        if scope == "":
            self._do_insert_here(scope_depth, parent_scopes, font_style, foreground)
            return
        head, _, tail = scope.partition(".")
        child = self.children.get(head)
        if child is None:
            child = _TrieElement(self.main_rule.clone(), [r.clone() for r in self.rules_with_parent_scopes])
            self.children[head] = child
        child.insert(scope_depth + 1, tail, parent_scopes, font_style, foreground)

    def _do_insert_here(self, scope_depth: int, parent_scopes: tuple[str, ...] | None, font_style: int, foreground: str | None) -> None:
        if parent_scopes is None:
            self.main_rule.accept_overwrite(scope_depth, font_style, foreground)
            return
        for rule in self.rules_with_parent_scopes:
            if _str_arr_cmp(rule.parent_scopes, parent_scopes) == 0:
                rule.accept_overwrite(scope_depth, font_style, foreground)
                return
        if font_style == FONT_STYLE_NOT_SET:
            font_style = self.main_rule.font_style
        if foreground is None:
            foreground = self.main_rule.foreground
        self.rules_with_parent_scopes.append(_TrieRule(scope_depth, parent_scopes, font_style, foreground))


def _matches_scope(scope_name: str, pattern: str) -> bool:
    """``_matchesScope``: הבורר חל על ה-scope שלו ועל מה שמתחתיו — שווה, או קידומת שאחריה נקודה."""
    return pattern == scope_name or (
        scope_name.startswith(pattern) and len(scope_name) > len(pattern) and scope_name[len(pattern)] == "."
    )


def _scope_path_matches_parent_scopes(path: Sequence[str], parent_scopes: tuple[str, ...]) -> bool:
    """``_scopePathMatchesParentScopes``: ``path`` הוא ההורים של הטוקן, מבחוץ פנימה; ``parent_scopes`` הפוכים, הקרוב ראשון."""
    if not parent_scopes:
        return True
    pos = len(path) - 1
    index = 0
    while index < len(parent_scopes):
        pattern = parent_scopes[index]
        must_match = False
        if pattern == ">":
            if index == len(parent_scopes) - 1:
                return False
            index += 1
            pattern = parent_scopes[index]
            must_match = True
        while pos >= 0:
            if _matches_scope(path[pos], pattern):
                break
            if must_match:
                return False
            pos -= 1
        if pos < 0:
            return False
        pos -= 1
        index += 1
    return True


@dataclass(frozen=True)
class TokenStyle:
    """הסגנון שהטוקן מקבל. ``foreground`` הוא ``None`` כשאין צבע — לא בערכה ולא ב-``default_foreground``."""

    foreground: str | None
    font_style: int

    @property
    def italic(self) -> bool:
        return bool(self.font_style & FONT_STYLE_ITALIC)

    @property
    def bold(self) -> bool:
        return bool(self.font_style & FONT_STYLE_BOLD)

    @property
    def underline(self) -> bool:
        return bool(self.font_style & FONT_STYLE_UNDERLINE)


class VSCodeTokenTheme:
    """``tokenColors`` של ערכה, מוכנים להכרעה: ``resolve(scopes)`` מחזיר את מה ש-VS Code נותן לטוקן עם השרשרת הזו."""

    def __init__(self, token_colors: object, *, default_foreground: str | None = None):
        rules = parse_token_rules(token_colors, default_foreground=default_foreground)
        rules.sort(
            key=functools.cmp_to_key(
                lambda a, b: _strcmp(a.scope, b.scope)
                or _str_arr_cmp(a.parent_scopes, b.parent_scopes)
                or (a.index - b.index)
            )
        )
        self.default_font_style = FONT_STYLE_NONE
        self.default_foreground: str | None = None
        while rules and rules[0].scope == "":
            incoming = rules.pop(0)
            if incoming.font_style != FONT_STYLE_NOT_SET:
                self.default_font_style = incoming.font_style
            if incoming.foreground is not None:
                self.default_foreground = incoming.foreground
        self._root = _TrieElement(_TrieRule(0, None, FONT_STYLE_NOT_SET, None))
        for rule in rules:
            self._root.insert(0, rule.scope, rule.parent_scopes, rule.font_style, rule.foreground)

    def _match(self, path: Sequence[str]) -> _TrieRule | None:
        """``Theme.match``: הכלל שחל על ה-scope האחרון בשרשרת, לפי הספציפיות, אם ההורים שלו נמצאים בשרשרת."""
        candidates = self._root.match(path[-1])
        parents = path[:-1]
        return next((r for r in candidates if _scope_path_matches_parent_scopes(parents, r.parent_scopes)), None)

    def resolve(self, scopes: Iterable[str]) -> TokenStyle:
        """הסגנון של טוקן ש-``scopes`` היא שרשרת ה-scopes שלו, מבחוץ פנימה (``source.python`` ראשון).

        כמו ב-``AttributedScopeStack``: מתחילים מברירות המחדל של הערכה, ולכל scope בשרשרת — הכלל שחל עליו דורס את מה
        שהוא קובע, צבע וגופן כל אחד בנפרד.
        """
        path: list[str] = []
        font_style = self.default_font_style
        foreground = self.default_foreground
        for scope in scopes:
            path.append(scope)
            rule = self._match(path)
            if rule is None:
                continue
            if rule.font_style != FONT_STYLE_NOT_SET:
                font_style = rule.font_style
            if rule.foreground is not None:
                foreground = rule.foreground
        return TokenStyle(foreground, font_style)


# ---------------------------------------------------------------------------
# הנציגים: לכל מחלקה, שרשרת ה-scopes שהטוקן שהיא צובעת מקבל ב-VS Code (בלי ה-scope של השפה, שנוסף בהכרעה)
# ---------------------------------------------------------------------------

#: ה-scope של השפה לנציגים הכלליים. בורר ל-``source`` חל ב-VS Code על כל קוד, ובורר ל-``source.python`` רק על פייתון.
GENERIC_ROOT_SCOPE = "source"

#: מחלקות highlight.js, לפי ``docs/css-classes-reference.rst`` של highlight.js 11.11.1, בבוררי CSS (מחלקת-משנה
#: מקבלת קו תחתון אחד או שניים, כמו ש-highlight.js כותב אותן). ``class``, ``function`` ו-``formula`` וה-``template-*``
#: לא כאן: שתי הראשונות מסומנות ב-highlight.js כמיושנות ומשמשות מעטפת לחלקים אחרים, ולשאר אין scope אחד שמייצג אותן.
HLJS_REPRESENTATIVES: dict[str, tuple[str, ...]] = {
    ".hljs-keyword": ("keyword.control",),
    ".hljs-built_in": ("support.function.builtin",),
    ".hljs-type": ("storage.type",),
    ".hljs-literal": ("constant.language",),
    ".hljs-number": ("constant.numeric",),
    ".hljs-operator": ("keyword.operator",),
    ".hljs-punctuation": ("punctuation",),
    ".hljs-property": ("variable.other.property",),
    ".hljs-regexp": ("string.regexp",),
    ".hljs-string": ("string.quoted",),
    ".hljs-char.escape_": ("string.quoted", "constant.character.escape"),
    ".hljs-subst": ("string.interpolated", "meta.embedded.line"),
    ".hljs-symbol": ("constant.other.symbol",),
    ".hljs-variable": ("variable.other",),
    # ``this``/``self``: כך רוב הדקדוקים מסמנים אותם (``variable.language.this.js``, ‏``.java``, ‏``.cs``, ‏``.php``)
    ".hljs-variable.language_": ("variable.language.this",),
    ".hljs-variable.constant_": ("variable.other.constant",),
    ".hljs-title": ("entity.name",),
    ".hljs-title.class_": ("entity.name.type.class",),
    ".hljs-title.class_.inherited__": ("entity.other.inherited-class",),
    ".hljs-title.function_": ("entity.name.function",),
    ".hljs-title.function_.invoke__": ("meta.function-call", "entity.name.function"),
    ".hljs-params": ("variable.parameter",),
    ".hljs-comment": ("comment",),
    ".hljs-doctag": ("comment.block.documentation", "storage.type.class.jsdoc"),
    ".hljs-meta": ("meta.preprocessor",),
    # מחלקות הסימון — בעיקר Markdown ו-diff: השרשראות של הדקדוקים של VS Code (tm-grammars 1.32.22, ``markdown.json``
    # ו-``diff.json``), כדי שגם כלל שנכתב ל-``markup.heading.markdown`` יחול, ולא רק כלל ל-``markup.heading``
    ".hljs-section": ("markup.heading.markdown", "heading.1.markdown", "entity.name.section.markdown"),
    ".hljs-tag": ("meta.tag", "punctuation.definition.tag"),
    ".hljs-name": ("meta.tag", "entity.name.tag"),
    ".hljs-attr": ("entity.other.attribute-name",),
    ".hljs-attribute": ("support.type.property-name",),
    ".hljs-bullet": ("markup.list.unnumbered.markdown", "punctuation.definition.list.begin.markdown"),
    ".hljs-code": ("meta.paragraph.markdown", "markup.inline.raw.string.markdown"),
    ".hljs-emphasis": ("meta.paragraph.markdown", "markup.italic.markdown"),
    ".hljs-strong": ("meta.paragraph.markdown", "markup.bold.markdown"),
    ".hljs-link": ("meta.paragraph.markdown", "meta.link.inline.markdown", "markup.underline.link.markdown"),
    ".hljs-quote": ("markup.quote.markdown", "meta.paragraph.markdown"),
    ".hljs-selector-tag": ("meta.selector", "entity.name.tag"),
    ".hljs-selector-id": ("meta.selector", "entity.other.attribute-name.id"),
    ".hljs-selector-class": ("meta.selector", "entity.other.attribute-name.class"),
    ".hljs-selector-attr": ("meta.selector", "entity.other.attribute-name"),
    ".hljs-selector-pseudo": ("meta.selector", "entity.other.attribute-name.pseudo-class"),
    ".hljs-addition": ("markup.inserted.diff",),
    ".hljs-deletion": ("markup.deleted.diff",),
}


@dataclass(frozen=True)
class HljsLanguage:
    """שפה שיש לה כללים משלה: ה-scope של הדקדוק שלה ב-VS Code, השמות שהבלוק יכול לשאת (``language-<שם>``), ונציגים."""

    root_scope: str
    class_names: tuple[str, ...]
    representatives: dict[str, tuple[str, ...]]


#: הנציגים לפי שפה נמדדו על הדקדוקים של VS Code, כפי ש-tm-grammars 1.32.22 אורז אותם: MagicPython
#: (``extensions/python/syntaxes/MagicPython.tmLanguage.json``, קומיט ``cf4c9e46`` של microsoft/vscode) ו-JavaScript
#: (``extensions/javascript/syntaxes/JavaScript.tmLanguage.json``, קומיט ``21054190``). לכל מחלקה, השרשרת של הטוקנים
#: שהיא מכסה ברוב התווים בדוגמאות של ``scripts/syntax_colors/``. ``class_names``: השם הקנוני, שהוא מה ש-highlight.js
#: מוסיף לבלוק (``updateClassName``), והכינויים מ-``aliases`` של השפה ב-highlight.js 11.11.1 — לבלוק שעוד לא הודגש מחדש.
HLJS_LANGUAGES: dict[str, HljsLanguage] = {
    "python": HljsLanguage(
        root_scope="source.python",
        class_names=("python", "py", "gyp", "ipython"),
        representatives={
            # ``import``, ``and`` ו-``def`` הם אותה מחלקה; הנציג הוא מילות הבקרה (``if``, ``return``), הרוב בדוגמה
            ".hljs-keyword": ("keyword.control.flow.python",),
            # כולל גם את ``list``/``float`` (``support.type.python``); הנציג הוא הפונקציות — החלטה, נובמבר 2026
            ".hljs-built_in": ("meta.function-call.python", "support.function.builtin.python"),
            ".hljs-literal": ("constant.language.python",),
            # ``typing``: השם כמעט תמיד ב-annotation של פונקציה, עם סוגריים מרובעים (``List[int]``)
            ".hljs-type": ("meta.function.python", "meta.item-access.python", "meta.indexed-name.python"),
            ".hljs-number": ("constant.numeric.dec.python",),
            ".hljs-string": ("string.quoted.single.python",),
            # הביטוי בתוך ``{}`` של f-string: ב-MagicPython הוא כבר לא בתוך ה-scope של המחרוזת
            ".hljs-subst": ("meta.fstring.python",),
            ".hljs-comment": ("comment.line.number-sign.python",),
            ".hljs-meta": ("meta.function.decorator.python", "entity.name.function.decorator.python"),
            ".hljs-params": (
                "meta.function.python",
                "meta.function.parameters.python",
                "variable.parameter.function.language.python",
            ),
            ".hljs-title.function_": ("meta.function.python", "entity.name.function.python"),
            ".hljs-title.class_": ("meta.class.python", "entity.name.type.class.python"),
            ".hljs-title.class_.inherited__": (
                "meta.class.python",
                "meta.class.inheritance.python",
                "entity.other.inherited-class.python",
            ),
            ".hljs-variable.language_": ("variable.language.special.self.python",),
        },
    ),
    "javascript": HljsLanguage(
        root_scope="source.js",
        class_names=("javascript", "js", "jsx", "mjs", "cjs"),
        representatives={
            # ``const``, ``import`` ו-``return`` הם אותה מחלקה; הנציג הוא מילות הבקרה, כמו בפייתון
            ".hljs-keyword": ("keyword.control.flow.js",),
            # ``parseInt``, ``setTimeout``: ב-VS Code קריאה לפונקציה רגילה
            ".hljs-built_in": ("meta.function-call.js", "entity.name.function.js"),
            ".hljs-literal": ("constant.language.boolean.true.js",),
            ".hljs-number": ("constant.numeric.decimal.js",),
            ".hljs-string": ("string.quoted.single.js",),
            ".hljs-subst": (
                "string.template.js",
                "meta.template.expression.js",
                "meta.embedded.line.js",
                "variable.other.readwrite.js",
            ),
            ".hljs-regexp": ("string.regexp.js",),
            ".hljs-comment": ("comment.line.double-slash.js",),
            ".hljs-params": ("meta.parameters.js", "variable.parameter.js"),
            # ב-JavaScript highlight.js מסמן כך גם קריאות (``log``, ``map``) — הרוב בדוגמה
            ".hljs-title.function_": ("meta.function-call.js", "entity.name.function.js"),
            ".hljs-title.class_": ("meta.class.js", "entity.name.type.class.js"),
            ".hljs-title.class_.inherited__": ("meta.class.js", "entity.other.inherited-class.js"),
            ".hljs-variable.language_": ("variable.language.this.js",),
            ".hljs-variable.constant_": ("meta.definition.variable.js", "variable.other.constant.js"),
            ".hljs-property": ("variable.other.property.js",),
            ".hljs-attr": ("meta.objectliteral.js", "meta.object.member.js", "meta.object-literal.key.js"),
        },
    ),
}

#: ה-tags של CodeMirror ש-``syntax_colors`` צובע — המפתחות של ``TAG_NAME_MAP`` ב-``webapp/static_build/codemirror.bundle.entry.mjs``
#: (``tests/test_vscode_token_theme.py`` משווה). ל-CodeMirror אין סימון שפה על העורך, ולכן אין כאן כללים לפי שפה.
CM_TAG_REPRESENTATIVES: dict[str, tuple[str, ...]] = {
    "comment": ("comment",),
    "lineComment": ("comment.line",),
    "blockComment": ("comment.block",),
    "docComment": ("comment.block.documentation",),
    "string": ("string.quoted",),
    "special(string)": ("string.template",),
    "regexp": ("string.regexp",),
    "escape": ("string.quoted", "constant.character.escape"),
    "character": ("constant.character",),
    "keyword": ("keyword",),
    "controlKeyword": ("keyword.control",),
    "moduleKeyword": ("keyword.control.import",),
    "definitionKeyword": ("storage.type",),
    "operatorKeyword": ("keyword.operator.logical",),
    "modifier": ("storage.modifier",),
    "unit": ("keyword.other.unit",),
    "variableName": ("variable.other.readwrite",),
    "local(variableName)": ("variable.parameter",),
    "definition(variableName)": ("meta.definition.variable", "variable.other.readwrite"),
    "constant(variableName)": ("variable.other.constant",),
    "function(variableName)": ("meta.function-call", "entity.name.function"),
    "function(definition(variableName))": ("meta.function", "entity.name.function"),
    "definition(function(variableName))": ("meta.function", "entity.name.function"),
    "standard(function(variableName))": ("meta.function-call", "support.function.builtin"),
    "special(function(variableName))": ("meta.function-call", "support.function"),
    "function(propertyName)": ("meta.function-call", "entity.name.function"),
    "self": ("variable.language.this",),
    "typeName": ("entity.name.type",),
    "className": ("entity.name.type.class",),
    "namespace": ("entity.name.namespace",),
    "standard(typeName)": ("support.type",),
    "standard(className)": ("support.class",),
    "definition(className)": ("meta.class", "entity.name.type.class"),
    "macroName": ("entity.name.function.preprocessor",),
    "atom": ("constant.language",),
    "bool": ("constant.language.boolean",),
    "number": ("constant.numeric",),
    "integer": ("constant.numeric.integer",),
    "float": ("constant.numeric.float",),
    "null": ("constant.language.null",),
    "operator": ("keyword.operator",),
    "definitionOperator": ("keyword.operator.assignment",),
    "compareOperator": ("keyword.operator.comparison",),
    "logicOperator": ("keyword.operator.logical",),
    "arithmeticOperator": ("keyword.operator.arithmetic",),
    "bitwiseOperator": ("keyword.operator.bitwise",),
    "propertyName": ("variable.other.property",),
    "definition(propertyName)": ("variable.object.property",),
    "attributeName": ("entity.other.attribute-name",),
    "tagName": ("meta.tag", "entity.name.tag"),
    "angleBracket": ("meta.tag", "punctuation.definition.tag"),
    "punctuation": ("punctuation",),
    "separator": ("punctuation.separator",),
    "bracket": ("punctuation.section.brackets",),
    "brace": ("punctuation.definition.block",),
    "paren": ("meta.brace.round",),
    "squareBracket": ("meta.brace.square",),
    "heading": ("markup.heading", "entity.name.section"),
    "heading1": ("markup.heading", "entity.name.section"),
    "heading2": ("markup.heading", "entity.name.section"),
    "strong": ("markup.bold",),
    "emphasis": ("markup.italic",),
    "link": ("markup.underline.link",),
    "quote": ("markup.quote",),
    "list": ("markup.list", "punctuation.definition.list.begin"),
    "monospace": ("markup.inline.raw",),
    "inserted": ("markup.inserted",),
    "deleted": ("markup.deleted",),
    "changed": ("markup.changed",),
    "meta": ("meta.function.decorator", "punctuation.definition.decorator"),
    "processingInstruction": ("meta.tag.preprocessor",),
    # הטקסט של מסמך סימון (פסקה ב-Markdown)
    "content": ("meta.paragraph.markdown",),
    "labelName": ("entity.name.label",),
    "url": ("markup.underline.link",),
    "invalid": ("invalid",),
}

#: המחלקות של ``classHighlighter`` ב-``@lezer/highlight`` 1.2.3, וה-tag שכל אחת מקבלת ממנו — הנציג שלה הוא של ה-tag.
#: ``tests/test_vscode_token_theme.py`` משווה לטבלה שבבאנדל (``webapp/static/js/codemirror.local.js``).
CM_CLASS_TAGS: dict[str, str] = {
    ".tok-link": "link",
    ".tok-heading": "heading",
    ".tok-emphasis": "emphasis",
    ".tok-strong": "strong",
    ".tok-keyword": "controlKeyword",
    ".tok-atom": "atom",
    ".tok-bool": "bool",
    ".tok-url": "url",
    ".tok-labelName": "labelName",
    # ``literal`` לבד (לא מחרוזת ולא מספר): ‏``tags.literal`` אינו ב-``TAG_NAME_MAP``, והקרוב אליו שם הוא ``atom``
    ".tok-literal": "atom",
    ".tok-inserted": "inserted",
    ".tok-deleted": "deleted",
    ".tok-string": "string",
    ".tok-number": "number",
    ".tok-string2": "special(string)",
    ".tok-variableName": "variableName",
    ".tok-variableName.tok-local": "local(variableName)",
    ".tok-variableName.tok-definition": "definition(variableName)",
    ".tok-variableName2": "self",
    ".tok-propertyName.tok-definition": "definition(propertyName)",
    ".tok-typeName": "typeName",
    ".tok-namespace": "namespace",
    ".tok-className": "className",
    ".tok-macroName": "macroName",
    ".tok-propertyName": "propertyName",
    ".tok-operator": "operator",
    ".tok-comment": "comment",
    ".tok-meta": "meta",
    ".tok-invalid": "invalid",
    ".tok-punctuation": "punctuation",
}
