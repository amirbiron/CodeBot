import pytest

from services.theme_parser_service import (
    color_with_opacity,
    export_theme_to_json,
    generate_codemirror_css_from_tokens,
    is_valid_color,
    normalize_color_to_rgba,
    parse_native_theme,
    parse_vscode_theme,
    sanitize_css_value,
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
        token_colors = [
            {"scope": ["comment"], "settings": {"foreground": "#6272a4", "fontStyle": "italic"}},
            {"scope": ["keyword"], "settings": {"foreground": "#ff79c6"}},
        ]
        css = generate_codemirror_css_from_tokens(token_colors)
        assert ':root[data-theme="custom"] .cm-comment' in css
        assert "color: #6272a4" in css
        assert "font-style: italic" in css
        assert ':root[data-theme="custom"] .cm-keyword' in css


class TestExportTheme:
    def test_export_theme_to_json(self):
        theme = {"name": "X", "description": "Y", "variables": {"--bg-primary": "#000"}}
        out = export_theme_to_json(theme)
        assert '"name": "X"' in out
        assert '"--bg-primary": "#000"' in out

