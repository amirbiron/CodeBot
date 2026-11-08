"""צבעי התחביר של ערכת VS Code — כמו ש-VS Code צובע, ומה שנשאר שונה הוא רק מה שהמחלקה עצמה מאחדת.

**הרקע** (הפתק "מחוללי צבעי התחביר — scope עם פסיקים וכיוון ההתאמה" בלוח ה-issues ב-CodeKeeper). המחוללים ב-
``services/theme_parser_service.py`` הפכו ``tokenColors`` לכללי צבע אחרת מ-VS Code, בשלוש שכבות: ``scope`` עם פסיקים לא
פוצל (שכבה 1); בורר צר נלקח כצבע של מחלקה רחבה, והכלל הראשון זכה (שכבה 2); וכל מחלקה יוצגה במפה במפתח שאינו הטוקן שהיא
צובעת (שכבה 3). ב-Everforest Dark ההערות לא נצבעו בכלל, ושמות הפונקציות יצאו סגולים.

**מה נבדק כאן:**

- **ההכרעה** (``services/vscode_token_theme.py``, שכבות 1–2) נותנת בדיוק את מה ש-vscode-textmate 9.3.2 נותנת, לכל שרשרת
  scopes שהדקדוקים של VS Code מייצרים בדוגמאות — הערכים הצפויים ב-``tests/fixtures/syntax_colors_vscode_reference.json``,
  שנוצר ב-``scripts/syntax_colors/`` — וגם במקרי קצה של הדקדוק, בערכות קטנות שנכתבו כאן.
- **הנציגים** (שכבה 3): לכל ערכה, שפה ורינדור (highlight.js, המחלקות ``.tok-*`` של CodeMirror ו-``syntax_colors``), כל תו
  שיוצא בצבע אחר מ-VS Code נמצא באיחוד מוצהר ב-``MERGES``, וכל איחוד מוצהר מופיע — כך שהרשימה אינה מתיישנת.
- **הנקודות שנבדקו ב-Everforest**, כל אחת בטסט משלה, כולל שתי הנקודות שהמחלקה של highlight.js לא מאפשרת.
- **מה שלא משתנה:** הכלל הבסיסי ``.hljs`` (צבע ורקע) כמו קודם, וערכות הייצוא בלי רקע.
- **הניקוי:** כלל לפי שפה עובר את ``rebase_hljs_css`` ונכתב נכון תחת הקידומת של הייצוא, וצורות פגומות שלו לא עוברות.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from _syntax_colors_reference import (
    MERGES,
    color_for_path,
    declared_merge,
    load_reference,
    mismatches,
    parse_rules,
    scope_matches,
    style_for,
)
from scripts.syntax_colors import generate_reference
from services import styled_export_service as export
from services.theme_parser_service import (
    HLJS_SITE_THEME_SELECTOR_PREFIX,
    generate_codemirror_css_from_tokens,
    generate_hljs_css_from_tokens,
    generate_syntax_colors_from_tokens,
    parse_vscode_theme,
    rebase_hljs_css,
)
from services.vscode_token_theme import (
    CM_CLASS_TAGS,
    CM_TAG_REPRESENTATIVES,
    FONT_STYLE_BOLD,
    FONT_STYLE_ITALIC,
    HLJS_LANGUAGES,
    VSCodeTokenTheme,
    parse_token_rules,
)

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = load_reference()
THEMES = generate_reference.reference_themes()
LANGUAGES = ("python", "javascript")
RENDERERS = ("hljs", "cm-class", "cm-tags")
EXPORT_PREFIX = export.EXPORT_HLJS_SELECTOR_PREFIX

def _code_text(theme_id: str) -> str:
    return export.EXPORT_PRESETS[theme_id]["variables"]["--code-text"]


def _mismatches(theme_id: str, language: str, renderer: str):
    tokens = THEMES[theme_id]
    fg = _code_text(theme_id)
    if renderer == "hljs":
        return mismatches(
            REFERENCE, theme_id, language, hljs_css=export.EXPORT_PRESETS[theme_id]["hljs_css"],
            hljs_prefix=EXPORT_PREFIX, default_color=fg,
        )
    if renderer == "cm-class":
        return mismatches(REFERENCE, theme_id, language, cm_css=generate_codemirror_css_from_tokens(tokens, fg), default_color=fg)
    return mismatches(REFERENCE, theme_id, language, syntax_colors=generate_syntax_colors_from_tokens(tokens, fg), default_color=fg)


# ---------------------------------------------------------------------------
# ה-fixture וההכרעה
# ---------------------------------------------------------------------------


def test_the_reference_was_generated_from_todays_themes_and_samples():
    """שינוי בערכת ייצוא או בדוגמה מחייב להריץ את ``scripts/syntax_colors/generate_reference.py`` מחדש."""
    inputs = REFERENCE["inputs"]
    for theme_id, tokens in THEMES.items():
        assert inputs["token_colors_sha256"][theme_id] == generate_reference.sha256_json(tokens), theme_id
    for language, name in generate_reference.SAMPLE_FILES.items():
        code = (generate_reference.HERE / "samples" / name).read_text(encoding="utf-8")
        assert inputs["samples_sha256"][language] == generate_reference.sha256_json(code), language
    assert REFERENCE["versions"]["vscode-textmate"] == "9.3.2"


@pytest.mark.parametrize("theme_id", sorted(THEMES))
def test_the_resolver_gives_what_vscode_textmate_gives(theme_id):
    theme = VSCodeTokenTheme(THEMES[theme_id])
    styles = REFERENCE["themes"][theme_id]
    assert len(styles) > 200
    wrong = []
    for language in LANGUAGES:
        for seg in REFERENCE["languages"][language]:
            expected = style_for(styles, seg["scopes"])
            got = theme.resolve(seg["scopes"])
            fg = got.foreground.lower() if got.foreground else None
            if (fg, got.font_style) != (expected["fg"], expected["fontStyle"]):
                wrong.append((seg["scopes"], fg, got.font_style, expected))
    assert wrong == []


def _style(token_colors, *scopes):
    return VSCodeTokenTheme(token_colors).resolve(scopes)


def test_layer1_a_scope_string_is_a_comma_separated_list_and_a_list_is_not_split():
    as_string = [{"scope": ",comment, string.comment ,", "settings": {"foreground": "#111111"}}]
    as_list = [{"scope": ["comment, string.comment"], "settings": {"foreground": "#111111"}}]
    assert _style(as_string, "source.x", "comment.line").foreground == "#111111"
    assert _style(as_string, "source.x", "string.comment").foreground == "#111111"
    # ברשימה: בורר אחד, ``string.comment`` עם ההורה ``comment,`` — לא חל על הערה
    assert _style(as_list, "source.x", "comment.line").foreground is None


def test_layer2_a_selector_applies_to_its_scope_and_below_and_the_more_specific_wins():
    tokens = [
        {"scope": "variable.interpolation", "settings": {"foreground": "#222222"}},
        {"scope": "variable", "settings": {"foreground": "#111111"}},
        {"scope": "variable.other.readwrite", "settings": {"foreground": "#333333"}},
    ]
    assert _style(tokens, "source.x", "variable.other").foreground == "#111111"
    assert _style(tokens, "source.x", "variable.other.readwrite.js").foreground == "#333333"
    assert _style(tokens, "source.x", "variables").foreground is None  # גבול של נקודה, לא קידומת של תווים


def test_layer2_a_narrow_selector_does_not_color_the_broad_class():
    """הבאג המקורי: כלל ל-``variable.interpolation`` נלקח כצבע של כל המשתנים. ב-VS Code הוא חל רק על מה שמתחתיו."""
    tokens = [{"scope": "variable.interpolation", "settings": {"foreground": "#222222"}}]
    assert _style(tokens, "source.x", "variable").foreground is None
    assert _style(tokens, "source.x", "variable.other").foreground is None
    assert ".hljs-variable " not in generate_hljs_css_from_tokens(tokens)
    assert "variableName" not in generate_syntax_colors_from_tokens(tokens)


def test_layer2_a_tie_goes_to_the_later_rule_and_each_attribute_is_inherited_on_its_own():
    tokens = [
        {"scope": "constant", "settings": {"foreground": "#111111", "fontStyle": "italic"}},
        {"scope": "constant.language", "settings": {"foreground": "#222222"}},
        {"scope": "constant.language", "settings": {"foreground": "#333333"}},
        {"scope": "constant.language.null", "settings": {"fontStyle": ""}},
    ]
    style = _style(tokens, "source.x", "constant.language.boolean")
    assert (style.foreground, style.font_style) == ("#333333", FONT_STYLE_ITALIC)
    style = _style(tokens, "source.x", "constant.language.null")
    assert (style.foreground, style.font_style) == ("#333333", 0)


def test_layer2_parent_scopes_and_the_child_combinator():
    tokens = [
        {"scope": "source.python constant.language", "settings": {"foreground": "#111111"}},
        {"scope": "meta.a > string", "settings": {"foreground": "#222222", "fontStyle": "bold"}},
    ]
    assert _style(tokens, "source.python", "constant.language.python").foreground == "#111111"
    assert _style(tokens, "source.js", "constant.language.js").foreground is None
    assert _style(tokens, "source.x", "meta.a", "string.quoted").font_style == FONT_STYLE_BOLD
    assert _style(tokens, "source.x", "meta.a", "meta.b", "string.quoted").foreground is None


def test_a_long_run_of_commas_parses_in_linear_time():
    """הפסיקים בקצוות נחתכים ב-``strip``. רגקס ``,+$`` היה בודק רצף ארוך של פסיקים באמצע המחרוזת — שאחריו תו אחר — מכל
    נקודת התחלה: על 20 אלף פסיקים הוא לקח 1.2 שניות, וזמנו גדל בריבוע. כאן הרצף ארוך פי שניים וחצי (נמדד ב-8.11.2026)."""
    import time

    started = time.perf_counter()
    rules = parse_token_rules([{"scope": "comment" + "," * 50_000 + "x", "settings": {"foreground": "#111111"}}])
    assert time.perf_counter() - started < 1.0
    # כמו ב-VS Code: כל קטע ריק בין שני פסיקים הוא בורר ריק, כלומר כלל ברירת מחדל
    assert (rules[0].scope, rules[-1].scope, len(rules)) == ("comment", "x", 50_001)


def test_every_export_preset_with_highlightjs_colors_is_in_the_reference():
    """ערכת ייצוא עם ``hljs_css`` נבנית מ-``EXPORT_PRESET_TOKEN_COLORS`` — ולכן נכנסת להשוואה מול VS Code."""
    with_hljs = {pid for pid, preset in export.EXPORT_PRESETS.items() if preset.get("hljs_css")}
    assert with_hljs == set(export.EXPORT_PRESET_TOKEN_COLORS) == set(THEMES) == set(REFERENCE["themes"])


def test_malformed_entries_are_skipped_like_vscode_skips_them():
    tokens = [
        "not a rule",
        {"scope": "comment"},
        {"scope": "comment", "settings": "x"},
        {"scope": ["comment", 7], "settings": {"foreground": " #111111"}},  # רווח: VS Code לא מנקה
        {"scope": "string", "settings": {"foreground": "rgb(1,2,3)"}},
        {"scope": "keyword", "settings": {"foreground": "#abc"}},
    ]
    assert _style(tokens, "source.x", "comment.line").foreground is None
    assert _style(tokens, "source.x", "string.quoted").foreground is None
    assert _style(tokens, "source.x", "keyword.control").foreground == "#abc"


# ---------------------------------------------------------------------------
# שכבה 3: מה שנשאר שונה הוא רק האיחודים המוצהרים
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("renderer", RENDERERS)
@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("theme_id", sorted(THEMES))
def test_every_character_that_differs_from_vscode_is_a_declared_merge(theme_id, language, renderer):
    undeclared = [
        (m.css_class, m.scope, m.text, m.ours, m.vscode)
        for m in _mismatches(theme_id, language, renderer)
        if declared_merge(renderer, language, m.css_class, m.scope) is None
    ]
    assert undeclared == []


def test_every_declared_merge_actually_happens():
    used = set()
    for theme_id in THEMES:
        for language in LANGUAGES:
            for renderer in RENDERERS:
                for m in _mismatches(theme_id, language, renderer):
                    hit = declared_merge(renderer, language, m.css_class, m.scope)
                    if hit:
                        used.add(hit)
    declared = {(r, lang, cls, prefix) for (r, lang, cls), (_, prefixes) in MERGES.items() for prefix in prefixes}
    assert declared - used == set()


# ---------------------------------------------------------------------------
# הנקודות שנבדקו ב-Everforest Dark, בבלוק פייתון
# ---------------------------------------------------------------------------

_EVERFOREST_RULES = parse_rules(export.EXPORT_PRESETS["everforest-dark"]["hljs_css"], EXPORT_PREFIX)


def _ours(class_path, language="python"):
    return color_for_path(class_path, _EVERFOREST_RULES, language)


def _vscode(language, text, scope_prefix):
    styles = REFERENCE["themes"]["everforest-dark"]
    for seg in REFERENCE["languages"][language]:
        if seg["text"] == text and scope_matches(seg["scopes"][-1], scope_prefix):
            return style_for(styles, seg["scopes"])["fg"]
    raise AssertionError(f"{text!r} not in the {language} sample")


@pytest.mark.parametrize(
    "text, scope, class_path, color",
    [
        ("True", "constant.language.python", [["hljs-literal"]], "#83c092"),
        ("None", "constant.language.python", [["hljs-literal"]], "#83c092"),
        ("sum", "support.function.builtin.python", [["hljs-built_in"]], "#a7c080"),
        ("len", "support.function.builtin.python", [["hljs-built_in"]], "#a7c080"),
        ("print", "support.function.builtin.python", [["hljs-built_in"]], "#a7c080"),
        ("Docstring for the class.", "string.quoted.docstring", [["hljs-string"]], "#dbbc7f"),
        ("norm", "entity.name.function.python", [["hljs-title", "function_"]], "#a7c080"),
        ("2.5", "constant.numeric", [["hljs-number"]], "#d699b6"),
        (" comment line", "comment.line", [["hljs-comment"]], "#859289"),
    ],
)
def test_everforest_python_matches_vscode_on_the_points_that_were_checked(text, scope, class_path, color):
    assert _vscode("python", text, scope) == color
    assert _ours(class_path) == color


def test_everforest_comments_are_italic():
    rule = next(r for r in export.EXPORT_PRESETS["everforest-dark"]["hljs_css"].splitlines() if ".hljs-comment " in r)
    assert "font-style: italic" in rule


def test_true_and_none_come_from_a_python_rule_and_javascript_keeps_its_own_color():
    assert _ours([["hljs-literal"]], "javascript") == _vscode("javascript", "true", "constant.language") == "#d699b6"


@pytest.mark.parametrize(
    "text, scope, class_path, vscode_color, our_color",
    [
        # ``built_in`` מאחד את ``list``/``float`` עם ``print`` — הם מקבלים את הירוק של הפונקציות (החלטה, נובמבר 2026)
        ("list", "support.type.python", [["hljs-built_in"]], "#7fbbb3", "#a7c080"),
        ("float", "support.type.python", [["hljs-built_in"]], "#7fbbb3", "#a7c080"),
        # הקידומת ``f`` היא חלק מה-span של המחרוזת
        ("f", "storage.type.string.python", [["hljs-string"]], "#7fbbb3", "#dbbc7f"),
    ],
)
def test_the_two_points_highlightjs_cannot_separate_get_the_color_of_their_class(text, scope, class_path, vscode_color, our_color):
    assert _vscode("python", text, scope) == vscode_color
    assert _ours(class_path) == our_color
    assert declared_merge("hljs", "python", "." + ".".join(class_path[-1]), scope)


# ---------------------------------------------------------------------------
# מה שלא משתנה, והניקוי
# ---------------------------------------------------------------------------


def test_the_base_hljs_rule_keeps_its_color_and_background():
    css = generate_hljs_css_from_tokens([], "#d3c6aa", "#2d353b")
    assert css.splitlines()[0] == (
        f"{HLJS_SITE_THEME_SELECTOR_PREFIX} .hljs {{ color: #d3c6aa !important; background: #2d353b !important; }}"
    )


@pytest.mark.parametrize("theme_id", sorted(THEMES))
def test_export_presets_add_no_background_and_no_base_rule(theme_id):
    css = export.EXPORT_PRESETS[theme_id]["hljs_css"]
    assert "background" not in css
    assert all(line.startswith(f"{EXPORT_PREFIX} .hljs-") for line in css.splitlines())


def test_language_rules_come_first_and_only_where_they_differ():
    lines = export.EXPORT_PRESETS["everforest-dark"]["hljs_css"].splitlines()
    is_language = [":is(.language-" in line for line in lines]
    assert any(is_language) and is_language == sorted(is_language, reverse=True)
    general = {line.split(" {")[0].split(" ", 1)[1]: line.split("{")[1] for line, lang in zip(lines, is_language) if not lang}
    for line in (line for line, lang in zip(lines, is_language) if lang):
        selector = line.split(" {")[0].split(" ", 1)[1].split(":is(")[0]
        assert general.get(selector) != line.split("{")[1], line


def test_a_language_rule_survives_rebase_under_the_export_prefix():
    css = generate_hljs_css_from_tokens(THEMES["everforest-dark"], "#d3c6aa", "#2d353b")
    site_rule = next(line for line in css.splitlines() if ".hljs-literal:is(.language-python *" in line)
    rebased = rebase_hljs_css(css, EXPORT_PREFIX)
    assert site_rule.replace(HLJS_SITE_THEME_SELECTOR_PREFIX, EXPORT_PREFIX, 1) in rebased.splitlines()
    # הכלל הבסיסי (עם הרקע) לא עובר, כמו קודם
    assert ".hljs {" not in rebased


@pytest.mark.parametrize(
    "selector",
    [
        ".hljs-literal:is(.language-python *) .x",
        ".hljs-literal:is(.language-python)",
        ".hljs-literal:is(.language-Python *)",
        ".hljs-literal:is(.language-python *, *)",
        ".hljs-literal:not(.language-python *)",
        ".hljs-literal:is(.language-python *):is(.language-js *)",
    ],
)
def test_malformed_language_rules_do_not_survive_rebase(selector):
    css = f"{HLJS_SITE_THEME_SELECTOR_PREFIX} {selector} {{ color: #123456 !important; }}"
    assert rebase_hljs_css(css, EXPORT_PREFIX) == ""


def test_parse_vscode_theme_gives_codemirror_the_editor_foreground_for_uncolored_tags():
    parsed = parse_vscode_theme({
        "type": "dark",
        "colors": {"editor.foreground": "#d3c6aa", "editor.background": "#2d353b"},
        "tokenColors": [{"scope": "comment", "settings": {"foreground": "#859289"}}],
    })
    assert parsed["syntax_colors"]["comment"] == {"color": "#859289"}
    assert parsed["syntax_colors"]["variableName"] == {"color": "#d3c6aa"}
    assert ':root[data-theme-type="custom"] .tok-variableName { color: #d3c6aa !important; }' in parsed["syntax_css"]


# ---------------------------------------------------------------------------
# הטבלאות מול CodeMirror ו-highlight.js — כדי שלא ייסחפו
# ---------------------------------------------------------------------------


def test_the_codemirror_tags_are_the_keys_of_tag_name_map():
    src = (ROOT / "webapp/static_build/codemirror.bundle.entry.mjs").read_text(encoding="utf-8")
    block = src[src.index("const TAG_NAME_MAP = {"): src.index("};", src.index("const TAG_NAME_MAP = {"))]
    keys = [a or b for a, b in re.findall(r"^\s*(?:'([^']+)'|([A-Za-z0-9]+)):\s*tags\.", block, re.M)]
    assert set(CM_TAG_REPRESENTATIVES) == set(keys)


def test_the_codemirror_classes_are_the_classes_of_class_highlighter_in_the_bundle():
    src = (ROOT / "webapp/static/js/codemirror.local.js").read_text(encoding="utf-8")
    block = src[src.index("var classHighlighter = tagHighlighter(["): src.index("]);", src.index("var classHighlighter"))]
    classes = {"." + ".".join(c.split()) for c in re.findall(r'class: "([^"]+)"', block)}
    assert set(CM_CLASS_TAGS) == classes


@pytest.mark.parametrize("name", sorted(HLJS_LANGUAGES))
def test_the_language_class_names_are_the_highlightjs_name_and_aliases(name):
    """השם הקנוני (מה ש-``updateClassName`` מוסיף לבלוק) והכינויים מ-``aliases`` בשפה של highlight.js שבבאנדל."""
    src = (ROOT / "node_modules/highlight.js/lib/languages" / f"{name}.js").read_text(encoding="utf-8")
    aliases = re.findall(r"'([a-z0-9_+-]+)'", re.search(r"aliases:\s*\[(.*?)\]", src, re.S).group(1))
    assert HLJS_LANGUAGES[name].class_names == (name, *aliases)
