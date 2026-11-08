import pytest

from services.theme_parser_service import (
    color_with_opacity,
    export_theme_to_json,
    generate_codemirror_css_from_tokens,
    generate_syntax_colors_from_tokens,
    is_valid_color,
    normalize_color_to_rgba,
    parse_native_theme,
    parse_vscode_theme,
    sanitize_css_value,
    strip_jsonc_comments,
    validate_and_sanitize_theme_variables,
    validate_theme_json,
)


class TestIsValidColor:
    def test_valid_hex_short(self):
        assert is_valid_color("#fff")
        assert is_valid_color("#FFF")
        assert is_valid_color("#ffff")

    def test_valid_hex_full(self):
        assert is_valid_color("#ffffff")
        assert is_valid_color("#282a36")

    def test_valid_hex_with_alpha(self):
        assert is_valid_color("#ffffff26")
        assert is_valid_color("#000000ff")

    def test_valid_rgb(self):
        assert is_valid_color("rgb(255, 255, 255)")
        assert is_valid_color("rgb(0,0,0)")

    def test_valid_rgba(self):
        assert is_valid_color("rgba(0, 0, 0, 0.5)")
        assert is_valid_color("rgba(255,255,255,1)")

    def test_invalid_colors(self):
        assert not is_valid_color("")
        assert not is_valid_color("red")
        assert not is_valid_color("#gggggg")
        assert not is_valid_color("#fffff")  # 5 hex chars - לא חוקי
        assert not is_valid_color("#fffffff")  # 7 hex chars - לא חוקי
        assert not is_valid_color("rgb(999,0,0)")  # רכיב RGB חייב להיות 0..255
        assert not is_valid_color("rgba(0,0,0,1.5)")  # alpha חייב להיות 0..1
        assert not is_valid_color("rgba(0,0,0,1.1.1)")  # פורמט עשרוני לא תקין
        assert not is_valid_color("rgba(0,0,0,.5.)")  # נקודה כפולה/סופית לא תקינה
        assert not is_valid_color("expression(alert())")


class TestColorNormalization:
    def test_hex_short_to_rgba(self):
        assert normalize_color_to_rgba("#fff") == (255, 255, 255, 1.0)

    def test_hex_full_to_rgba(self):
        assert normalize_color_to_rgba("#ff0000") == (255, 0, 0, 1.0)

    def test_hex_with_alpha_to_rgba(self):
        result = normalize_color_to_rgba("#ff000080")
        assert result is not None
        assert result[0] == 255
        assert result[1] == 0
        assert result[2] == 0
        assert 0.49 < result[3] < 0.51  # ~0.5

    def test_rgb_to_rgba(self):
        assert normalize_color_to_rgba("rgb(100, 150, 200)") == (100, 150, 200, 1.0)

    def test_rgba_to_rgba(self):
        assert normalize_color_to_rgba("rgba(100, 150, 200, 0.75)") == (100, 150, 200, 0.75)

    def test_invalid_returns_none(self):
        assert normalize_color_to_rgba("red") is None
        assert normalize_color_to_rgba("url(...)") is None
        assert normalize_color_to_rgba("") is None


class TestColorWithOpacity:
    def test_hex_with_opacity(self):
        assert color_with_opacity("#ff0000", 0.5) == "rgba(255, 0, 0, 0.50)"

    def test_rgb_with_opacity(self):
        assert color_with_opacity("rgb(255, 0, 0)", 0.15) == "rgba(255, 0, 0, 0.15)"

    def test_short_hex_with_opacity(self):
        assert color_with_opacity("#f00", 0.25) == "rgba(255, 0, 0, 0.25)"

    def test_invalid_color_returns_fallback(self):
        result = color_with_opacity("invalid", 0.5)
        assert "rgba" in result


class TestSanitization:
    def test_blocks_url(self):
        assert sanitize_css_value("url('https://evil.com')") is None

    def test_blocks_expression(self):
        assert sanitize_css_value("expression(alert(1))") is None

    def test_blocks_javascript(self):
        assert sanitize_css_value("javascript:alert(1)") is None

    def test_blocks_data_uri(self):
        assert sanitize_css_value("data:text/html,<script>") is None

    def test_blocks_html_tags(self):
        assert sanitize_css_value("<script>") is None
        assert sanitize_css_value("</style>") is None

    def test_allows_valid_colors(self):
        assert sanitize_css_value("#ff0000") == "#ff0000"
        assert sanitize_css_value("rgb(255,0,0)") == "rgb(255,0,0)"

    def test_validate_theme_variables_filters_unknown_and_dangerous(self):
        variables = {
            "--bg-primary": "#000",
            "--unknown-var": "#fff",
            "--text-primary": "url(evil)",
        }
        result = validate_and_sanitize_theme_variables(variables)
        assert "--bg-primary" in result
        assert "--unknown-var" not in result
        assert "--text-primary" not in result


class TestStripJsoncComments:
    """טסטים לפונקציה שמסירה הערות JSONC מתוכן JSON."""

    def test_removes_single_line_comment(self):
        """הסרת הערות // מתוכן JSON."""
        json_content = """{
            "name": "Test", // this is a comment
            "value": 123
        }"""
        result = strip_jsonc_comments(json_content)
        assert "//" not in result
        assert '"name": "Test"' in result
        assert '"value": 123' in result

    def test_removes_multiline_comment(self):
        """הסרת הערות /* */ מתוכן JSON."""
        json_content = """{
            /* This is a
               multiline comment */
            "name": "Test"
        }"""
        result = strip_jsonc_comments(json_content)
        assert "/*" not in result
        assert "*/" not in result
        assert '"name": "Test"' in result

    def test_preserves_comment_like_strings(self):
        """שמירה על מחרוזות שנראות כמו הערות."""
        json_content = '{"url": "http://example.com", "desc": "/* not a comment */"}'
        result = strip_jsonc_comments(json_content)
        assert '"http://example.com"' in result
        assert '"/* not a comment */"' in result

    def test_handles_nord_theme_comment(self):
        """טיפול בהערה אמיתית מערכת Nord."""
        json_content = """{
            "minimapSlider.hoverBackground": "#434c5eaa",

            /* `notification.*` keys are legacy support for VS Code versions >1.21.0 */
            "notification.background": "#3b4252"
        }"""
        result = strip_jsonc_comments(json_content)
        assert "/*" not in result
        assert "legacy support" not in result
        assert '"notification.background": "#3b4252"' in result

    def test_empty_content(self):
        """תוכן ריק."""
        assert strip_jsonc_comments("") == ""

    def test_no_comments(self):
        """תוכן ללא הערות."""
        json_content = '{"name": "Test", "value": 123}'
        assert strip_jsonc_comments(json_content) == json_content

    def test_escape_sequences_in_strings(self):
        """טיפול נכון ב-escape sequences בתוך מחרוזות."""
        json_content = r'{"path": "C:\\Users\\test", "quote": "say \"hello\""}' + " // comment"
        result = strip_jsonc_comments(json_content)
        assert r'"C:\\Users\\test"' in result
        assert r'"say \"hello\""' in result
        assert "// comment" not in result


class TestValidateThemeJson:
    def test_valid_vscode_theme(self):
        json_content = """
        {
            "name": "Test",
            "colors": {
                "editor.background": "#282a36",
                "editor.foreground": "#f8f8f2",
                "button.background": "#bd93f9"
            }
        }
        """
        is_valid, error = validate_theme_json(json_content)
        assert is_valid
        assert error == ""

    def test_vscode_theme_with_comments(self):
        """טסט חשוב: ערכת VS Code עם הערות JSONC."""
        json_content = """{
            "name": "Nord",
            "colors": {
                "editor.background": "#2e3440",
                /* Legacy support comment */
                "editor.foreground": "#d8dee9",
                "button.background": "#88c0d0" // inline comment
            }
        }"""
        is_valid, error = validate_theme_json(json_content)
        assert is_valid, f"Should accept JSONC with comments, got error: {error}"

    def test_valid_native_theme(self):
        json_content = """
        {
            "name": "Test",
            "variables": {
                "--bg-primary": "#282a36",
                "--text-primary": "#f8f8f2",
                "--glass-blur": "20px"
            }
        }
        """
        is_valid, _ = validate_theme_json(json_content)
        assert is_valid

    def test_invalid_json(self):
        is_valid, error = validate_theme_json("{invalid json}")
        assert not is_valid
        assert "JSON" in error

    def test_missing_colors_and_variables(self):
        is_valid, error = validate_theme_json('{"name": "Test"}')
        assert not is_valid
        assert "colors" in error or "variables" in error


class TestParseVscodeTheme:
    def test_basic_parsing(self):
        theme = {
            "name": "Dracula",
            "type": "dark",
            "colors": {
                "editor.background": "#282a36",
                "editor.foreground": "#f8f8f2",
                "button.background": "#bd93f9",
                "button.foreground": "#f8f8f2",
            },
        }
        result = parse_vscode_theme(theme)
        assert result["name"] == "Dracula"
        assert result["type"] == "dark"
        assert result["variables"]["--bg-primary"] == "#282a36"
        assert result["variables"]["--md-surface"] == "#282a36"
        assert result["variables"]["--text-primary"] == "#f8f8f2"
        assert result["variables"]["--md-text"] == "#f8f8f2"
        assert result["variables"]["--btn-primary-bg"] == "#bd93f9"
        assert result["variables"]["--btn-primary-color"] == "#f8f8f2"
        assert result["variables"]["--btn-primary-border"] == "#bd93f9"

    def test_uses_fallback_for_missing(self):
        theme = {"name": "Minimal", "type": "dark", "colors": {"editor.background": "#000000"}}
        result = parse_vscode_theme(theme)
        assert "--text-primary" in result["variables"]
        assert "--btn-primary-bg" in result["variables"]

    def test_generates_syntax_css_from_token_colors(self):
        """בדיקה שערכת VS Code עם tokenColors מייצרת syntax_css."""
        theme = {
            "name": "Morass",
            "type": "dark",
            "colors": {"editor.background": "#313a36", "editor.foreground": "#e4e3e1"},
            "tokenColors": [
                {"scope": "comment", "settings": {"foreground": "#63776d"}},
                {"scope": "string", "settings": {"foreground": "#f8bb39"}},
                {"scope": "keyword", "settings": {"foreground": "#afd0c4"}},
                {"scope": "constant.numeric", "settings": {"foreground": "#f8bb39"}},
                {"scope": "entity.name.function", "settings": {"foreground": "#afb54c"}},
                # ‏``entity.name.type.class`` ולא ``entity.name.class``: זה ה-scope ששמות מחלקות מקבלים בדקדוקים של VS Code
                {"scope": "entity.name.type.class", "settings": {"foreground": "#68875a", "fontStyle": "underline"}},
                {"scope": "invalid", "settings": {"foreground": "#cf433e"}},
            ],
        }
        result = parse_vscode_theme(theme)

        # וודא ש-syntax_css קיים ולא ריק
        assert "syntax_css" in result
        assert result["syntax_css"]

        # וודא שיש כללים עבור classes שונים
        syntax_css = result["syntax_css"]
        assert ".tok-comment" in syntax_css
        assert ".tok-string" in syntax_css
        assert ".tok-keyword" in syntax_css
        assert ".tok-number" in syntax_css
        assert ".tok-variableName.tok-definition" in syntax_css
        assert ".tok-className" in syntax_css
        assert ".tok-invalid" in syntax_css

        # וודא שיש צבעים ו-!important
        assert "#63776d" in syntax_css  # comment color
        assert "#f8bb39" in syntax_css  # string color
        assert "!important" in syntax_css

        # וודא שיש text-decoration עבור class name (underline)
        assert "text-decoration: underline" in syntax_css

    def test_generates_syntax_colors_dict(self):
        """בדיקה שערכת VS Code עם tokenColors מייצרת גם syntax_colors (מילון לפי tags)."""
        theme = {
            "name": "Colorful",
            "type": "dark",
            "colors": {"editor.background": "#1e1e1e", "editor.foreground": "#d4d4d4"},
            "tokenColors": [
                {"scope": "comment", "settings": {"foreground": "#6a9955"}},
                {"scope": "keyword", "settings": {"foreground": "#569cd6"}},
                {"scope": "string", "settings": {"foreground": "#ce9178"}},
                {"scope": "entity.name.function", "settings": {"foreground": "#dcdcaa", "fontStyle": "bold"}},
                {"scope": "variable.language", "settings": {"foreground": "#9cdcfe"}},
            ],
        }
        result = parse_vscode_theme(theme)

        # וודא ש-syntax_colors קיים ולא ריק
        assert "syntax_colors" in result
        assert isinstance(result["syntax_colors"], dict)
        assert len(result["syntax_colors"]) > 0

        syntax_colors = result["syntax_colors"]

        # בדיקת צבעים לפי tag names
        assert "comment" in syntax_colors
        assert syntax_colors["comment"]["color"] == "#6a9955"

        assert "keyword" in syntax_colors
        assert syntax_colors["keyword"]["color"] == "#569cd6"

        assert "string" in syntax_colors
        assert syntax_colors["string"]["color"] == "#ce9178"

        # בדיקה שפונקציות ממופות ל-function(definition(variableName))
        # 🔑 CodeMirror Python parser משתמש ב-function(definition(...)) לא definition(function(...))
        assert "function(definition(variableName))" in syntax_colors
        assert syntax_colors["function(definition(variableName))"]["color"] == "#dcdcaa"
        assert syntax_colors["function(definition(variableName))"]["fontWeight"] == "bold"

        # בדיקה ש-variable.language ממופה ל-self
        assert "self" in syntax_colors
        assert syntax_colors["self"]["color"] == "#9cdcfe"


class TestNativeTheme:
    def test_parse_native_theme_sanitizes(self):
        theme = {
            "name": "Native",
            "variables": {
                "--bg-primary": "#000",
                "--text-primary": "url(evil)",
                "--glass-blur": "20px",
            },
        }
        parsed = parse_native_theme(theme)
        assert parsed["name"] == "Native"
        assert parsed["variables"]["--bg-primary"] == "#000"
        assert "--text-primary" not in parsed["variables"]
        assert parsed["variables"]["--glass-blur"] == "20px"


class TestTokenColorsToCodeMirrorCSS:
    def test_generates_css_rules(self):
        """בדיקה שנוצרים חוקי CSS עם tok- classes (CodeMirror 6)."""
        token_colors = [
            {"scope": ["comment"], "settings": {"foreground": "#6272a4", "fontStyle": "italic"}},
            {"scope": ["keyword"], "settings": {"foreground": "#ff79c6"}},
        ]
        css = generate_codemirror_css_from_tokens(token_colors)
        # CodeMirror 6 classHighlighter משתמש ב-tok- classes
        assert ':root[data-theme-type="custom"] .tok-comment' in css
        # !important נדרש כדי לדרוס inline styles של CodeMirror themes
        assert "color: #6272a4 !important" in css
        assert "font-style: italic !important" in css
        assert ':root[data-theme-type="custom"] .tok-keyword' in css

    def test_each_class_gets_the_color_vscode_gives_its_tokens(self):
        """כל מחלקה מקבלת את הצבע שהבורר של הערכה נותן ב-VS Code לטוקן שלה — ובורר שאינו חל עליו לא צובע אותה."""
        token_colors = [
            {"scope": ["keyword.control"], "settings": {"foreground": "#ff79c6"}},
            {"scope": ["entity.name.type.class"], "settings": {"foreground": "#8be9fd"}},
            {"scope": ["entity.name.type"], "settings": {"foreground": "#66d9ef"}},
            {"scope": ["constant.numeric"], "settings": {"foreground": "#bd93f9"}},
            {"scope": ["constant.language.boolean"], "settings": {"foreground": "#ff5555"}},
            {"scope": ["variable.language.this"], "settings": {"foreground": "#f8f8f2"}},
        ]
        css = generate_codemirror_css_from_tokens(token_colors)
        rules = {line.split(" {")[0].split(" ", 1)[1]: line for line in css.splitlines()}
        assert "#ff79c6" in rules[".tok-keyword"]
        assert "#8be9fd" in rules[".tok-className"]
        assert "#66d9ef" in rules[".tok-typeName"]
        assert "#bd93f9" in rules[".tok-number"]
        assert "#ff5555" in rules[".tok-bool"]
        assert "#f8f8f2" in rules[".tok-variableName2"]

    def test_a_rule_for_a_neighbouring_scope_does_not_color_the_class(self):
        """‏``support.class`` (מחלקה מובנית) אינו ``entity.name.type.class`` (שם מחלקה), ו-VS Code לא צובע את האחד בכלל של השני.
        עד נובמבר 2026 ההתאמה כאן קיבלה גם את הכיוון ההפוך, וכלל צר צבע מחלקה רחבה שלמה."""
        css = generate_codemirror_css_from_tokens([{"scope": "support.class", "settings": {"foreground": "#8be9fd"}}])
        assert ".tok-className" not in css

    def test_all_font_styles(self):
        """בדיקה שכל סגנונות הפונט נתמכים (עם !important)."""
        token_colors = [
            {"scope": "comment", "settings": {"foreground": "#888", "fontStyle": "italic"}},
            {"scope": "keyword", "settings": {"foreground": "#f00", "fontStyle": "bold"}},
            {"scope": "string", "settings": {"foreground": "#0f0", "fontStyle": "underline"}},
            {"scope": "variable", "settings": {"foreground": "#00f", "fontStyle": "bold italic underline"}},
        ]
        css = generate_codemirror_css_from_tokens(token_colors)

        # !important נדרש כדי לדרוס inline styles של CodeMirror themes
        assert "font-style: italic !important" in css
        assert "font-weight: bold !important" in css
        assert "text-decoration: underline !important" in css


class TestSanitizeCodeMirrorCSS:
    """בדיקות ל-sanitize_codemirror_css - וידוא שCSS לא מסוכן נחסם."""

    def test_allows_simple_tok_selectors(self):
        """בדיקה שselectors פשוטים של tok- מאושרים."""
        from services.theme_parser_service import sanitize_codemirror_css

        css = ':root[data-theme-type="custom"] .tok-keyword { color: #ff79c6 !important; }'
        result = sanitize_codemirror_css(css)
        assert ".tok-keyword" in result
        assert "color: #ff79c6 !important" in result

    def test_allows_composite_tok_selectors(self):
        """בדיקה שselectors מורכבים (composite) של tok- מאושרים."""
        from services.theme_parser_service import sanitize_codemirror_css

        css = ':root[data-theme-type="custom"] .tok-variableName.tok-definition { color: #50fa7b !important; }'
        result = sanitize_codemirror_css(css)
        assert ".tok-variableName.tok-definition" in result
        assert "color: #50fa7b !important" in result

    def test_allows_triple_composite_selectors(self):
        """בדיקה שselectors עם עד 3 classes מאושרים."""
        from services.theme_parser_service import sanitize_codemirror_css

        css = ':root[data-theme-type="custom"] .tok-variableName.tok-definition.tok-local { color: #ffb86c !important; }'
        result = sanitize_codemirror_css(css)
        assert ".tok-variableName.tok-definition.tok-local" in result

    def test_blocks_too_many_composite_selectors(self):
        """בדיקה שselectors עם יותר מ-3 classes נחסמים."""
        from services.theme_parser_service import sanitize_codemirror_css

        # 4 classes - צריך להיחסם
        css = ':root[data-theme-type="custom"] .tok-a.tok-b.tok-c.tok-d { color: #fff !important; }'
        result = sanitize_codemirror_css(css)
        assert result == ""

    def test_blocks_url_in_css(self):
        """בדיקה שCSS עם url() נחסם."""
        from services.theme_parser_service import sanitize_codemirror_css

        css = ':root[data-theme-type="custom"] .tok-keyword { color: url(evil.com) !important; }'
        result = sanitize_codemirror_css(css)
        assert result == ""

    def test_blocks_javascript_in_css(self):
        """בדיקה שCSS עם javascript: נחסם."""
        from services.theme_parser_service import sanitize_codemirror_css

        css = ':root[data-theme-type="custom"] .tok-keyword { color: javascript:alert(1) !important; }'
        result = sanitize_codemirror_css(css)
        assert result == ""


class TestSyntaxColorsGeneration:
    """בדיקות לפונקציות החדשות של syntax_colors (HighlightStyle דינמי)."""

    def test_generate_syntax_colors_basic(self):
        """בדיקה בסיסית של generate_syntax_colors_from_tokens."""
        token_colors = [
            {"scope": "comment", "settings": {"foreground": "#6a9955", "fontStyle": "italic"}},
            {"scope": "keyword", "settings": {"foreground": "#569cd6"}},
        ]
        colors = generate_syntax_colors_from_tokens(token_colors)

        assert "comment" in colors
        assert colors["comment"]["color"] == "#6a9955"
        assert colors["comment"]["fontStyle"] == "italic"

        assert "keyword" in colors
        assert colors["keyword"]["color"] == "#569cd6"
        assert "fontStyle" not in colors["keyword"]

    def test_generate_syntax_colors_the_later_rule_wins_a_tie(self):
        """שני כללים לאותו בורר: המאוחר מנצח, כמו ב-VS Code (``resolveParsedThemeRules`` ממיין לפי המיקום בקובץ).
        עד נובמבר 2026 הראשון ניצח."""
        token_colors = [
            {"scope": "keyword", "settings": {"foreground": "#ff0000"}},
            {"scope": "keyword", "settings": {"foreground": "#00ff00"}},
        ]
        colors = generate_syntax_colors_from_tokens(token_colors)

        assert colors["keyword"]["color"] == "#00ff00"

    def test_generate_syntax_colors_empty_input(self):
        """בדיקה שקלט ריק מחזיר מילון ריק."""
        assert generate_syntax_colors_from_tokens([]) == {}
        assert generate_syntax_colors_from_tokens(None) == {}
        assert generate_syntax_colors_from_tokens("invalid") == {}

    def test_generate_syntax_colors_font_styles(self):
        """בדיקה שכל סגנונות הפונט נתמכים."""
        token_colors = [
            {"scope": "comment", "settings": {"foreground": "#888", "fontStyle": "italic"}},
            {"scope": "keyword", "settings": {"foreground": "#f00", "fontStyle": "bold"}},
            {"scope": "string", "settings": {"foreground": "#0f0", "fontStyle": "bold italic"}},
        ]
        colors = generate_syntax_colors_from_tokens(token_colors)

        assert colors["comment"]["fontStyle"] == "italic"
        assert colors["keyword"]["fontWeight"] == "bold"
        assert colors["string"]["fontWeight"] == "bold"
        assert colors["string"]["fontStyle"] == "italic"


class TestExportTheme:
    def test_export_theme_to_json(self):
        theme = {"name": "X", "description": "Y", "variables": {"--bg-primary": "#000"}}
        out = export_theme_to_json(theme)
        assert '"name": "X"' in out
        assert '"--bg-primary": "#000"' in out

