"""``sanitize_syntax_css`` — הניקוי של ``syntax_css`` לפני שמירה (פרסום ערכה ציבורית, עדכון שלה, וערכות מוכנות).

עד התיקון הפרסום עבר דרך ``sanitize_codemirror_css``, שמכיר רק את כללי CodeMirror, ולכן ערכה ציבורית איבדה בשקט את
כללי highlight.js ו-Pygments שהערכה האישית שממנה פורסמה מקבלת: בלוק JSON ב-Markdown נצבע בפלטה שנגזרת ממשתני
הממשק, ולא בצבעי ``tokenColors`` של הערכה.

הטסט הראשון הוא גלאי הסחיפה: הוא מריץ את ``parse_vscode_theme`` על כל ה-scopes שבשלוש מפות המחוללים, ובודק שכל כלל
שנוצר עובר את הניקוי. מחולל שיתחיל לכתוב בורר או קבוצה שהניקוי לא מכיר — יפיל אותו, במקום לאבד צבעים בשקט.
"""

from __future__ import annotations

import pytest

from services.shared_theme_service import MAX_SYNTAX_CSS_LENGTH
from services.theme_parser_service import (
    TOKEN_TO_CODEMIRROR_MAP,
    TOKEN_TO_HLJS_MAP,
    TOKEN_TO_PYGMENTS_MAP,
    parse_vscode_theme,
    sanitize_syntax_css,
)

#: צבע ארוך מכל צבע hex של VS Code (``#rrggbbaa`` הוא תשעה תווים), כדי שהמדידה תהיה חסם עליון לערכה אמיתית.
_LONG_COLOR = "rgba(255, 255, 255, 0.555)"


def _rule_lines(css: str) -> list[str]:
    """שורות הכללים — בלי שורות ריקות ובלי הכותרות שבהערה שהפרסור כותב בין הקבוצות."""
    return [
        line.strip()
        for line in css.splitlines()
        if line.strip() and not line.strip().startswith("/*")
    ]


def _syntax_css_for_every_scope(color: str = "#9cdcfe") -> str:
    """``syntax_css`` של ערכה שנותנת צבע, נטוי, מודגש וקו תחתון לכל scope שבשלוש מפות המחוללים."""
    scopes = sorted(
        set(TOKEN_TO_CODEMIRROR_MAP) | set(TOKEN_TO_HLJS_MAP) | set(TOKEN_TO_PYGMENTS_MAP)
    )
    theme = {
        "name": "every scope",
        "colors": {
            "editor.background": color,
            "editor.foreground": color,
            "sideBar.background": "#000000",
        },
        "tokenColors": [
            {
                "scope": scope,
                "settings": {"foreground": color, "fontStyle": "italic bold underline"},
            }
            for scope in scopes
        ],
    }
    return parse_vscode_theme(theme)["syntax_css"]


def test_every_rule_parse_vscode_theme_generates_survives():
    generated = _syntax_css_for_every_scope()
    result = sanitize_syntax_css(generated)

    assert result.dropped == 0
    # כלל שעבר יוצא בפורמט שהמחולל כותב, תו-בתו (הצבע כאן כבר באותיות קטנות, כמו שהניקוי מנרמל אותו)
    assert _rule_lines(result.css) == _rule_lines(generated)

    rules = _rule_lines(result.css)
    assert any(".tok-" in r for r in rules), "אין כללי CodeMirror"
    assert any(".hljs-" in r for r in rules), "אין כללי highlight.js"
    assert any(
        r.startswith(':root[data-theme-type="custom"] .hljs {') and "background:" in r
        for r in rules
    ), "הכלל הבסיסי של highlight.js, עם הרקע, לא עבר"
    assert any(r.startswith(".highlight .") for r in rules), "אין כללי Pygments"


def test_json_keys_and_strings_keep_the_theme_colors():
    """המקרה שהתגלה: בלוק JSON ב-Markdown (highlight.js) מאבד את התכלת של המפתחות ואת החום של המחרוזות."""
    from services.styled_export_service import _MORASS_TOKEN_COLORS

    theme = {
        "name": "morass",
        "colors": {
            "editor.background": "#313a36",
            "editor.foreground": "#e4e3e1",
            "sideBar.background": "#485650",
        },
        "tokenColors": _MORASS_TOKEN_COLORS,
    }
    css = sanitize_syntax_css(parse_vscode_theme(theme)["syntax_css"]).css

    assert ':root[data-theme-type="custom"] .hljs-attr { color: #9cdcfe !important; }' in css
    assert ':root[data-theme-type="custom"] .hljs-string { color: #ce9178 !important; }' in css
    assert ".highlight .s2 { color: #ce9178 !important; }" in css


def test_max_syntax_css_length_is_twice_the_largest_generated_css():
    """``MAX_SYNTAX_CSS_LENGTH`` נגזר מהמדידה הזו. נכשל כשהמחוללים גדלים מעבר למחצית התקרה."""
    largest = len(_syntax_css_for_every_scope(_LONG_COLOR).strip())
    assert MAX_SYNTAX_CSS_LENGTH >= 2 * largest, (largest, MAX_SYNTAX_CSS_LENGTH)


def test_comment_only_and_blank_lines_are_not_counted_as_dropped():
    css = "\n/* Pygments syntax highlighting */\n\n.highlight .k { color: #c586c0 !important; }\n"
    result = sanitize_syntax_css(css)
    assert result.css == ".highlight .k { color: #c586c0 !important; }"
    assert result.dropped == 0


def test_the_old_prefix_is_normalized():
    result = sanitize_syntax_css(':root[data-theme="custom"] .hljs-string { color: #ABCDEF; }')
    assert (
        result.css == ':root[data-theme-type="custom"] .hljs-string { color: #abcdef !important; }'
    )
    assert result.dropped == 0


@pytest.mark.parametrize(
    "line",
    [
        # ערך מסוכן
        ':root[data-theme-type="custom"] .hljs-keyword { color: url(https://evil.test/x); }',
        ':root[data-theme-type="custom"] .hljs { color: #ffffff; background: url(https://evil.test/x); }',
        ':root[data-theme-type="custom"] .tok-keyword { color: expression(alert(1)); }',
        # רקע מותר רק בכלל הבסיסי של highlight.js
        ':root[data-theme-type="custom"] .hljs-keyword { color: #ffffff; background: #000000; }',
        ':root[data-theme-type="custom"] .tok-keyword { color: #ffffff; background: #000000; }',
        ".highlight .k { color: #ffffff; background: #000000; }",
        # בלי color
        ':root[data-theme-type="custom"] .hljs { background: #000000; }',
        # הצהרה מחוץ לרשימה
        ':root[data-theme-type="custom"] .hljs-keyword { color: #ffffff; position: fixed; }',
        # בריחה מהכלל
        ".highlight .k { color: #ffffff; } body { color: #ff0000; }",
        # בורר שאף מחולל לא כותב
        "body { color: #ffffff; }",
        ".highlight .k, body { color: #ffffff; }",
        ".highlight .keyword { color: #ffffff; }",
        # קבוצה בלי הצורה שהמחולל שלה כותב: Pygments עם קידומת, CodeMirror ו-highlight.js בלעדיה
        ':root[data-theme-type="custom"] .highlight .k { color: #ffffff; }',
        ".tok-keyword { color: #ffffff; }",
        ".hljs-keyword { color: #ffffff; }",
        # הערה בתוך כלל
        ':root[data-theme-type="custom"] .hljs-keyword { color: #ffffff; } /* x */',
        # שורה ארוכה מהמותר
        ':root[data-theme-type="custom"] .hljs-keyword { color: #ffffff;' + " " * 500 + "}",
    ],
)
def test_a_rule_outside_the_generators_is_dropped_and_counted(line):
    result = sanitize_syntax_css(line)
    assert result.css == ""
    assert result.dropped == 1


def test_non_string_input_is_a_type_error():
    with pytest.raises(TypeError):
        sanitize_syntax_css(["not", "css"])  # type: ignore[arg-type]
