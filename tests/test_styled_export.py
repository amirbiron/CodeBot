import pytest

from services.styled_export_service import (
    get_export_theme,
    markdown_to_html,
    preprocess_markdown,
)
from services.theme_presets_service import list_presets


class TestPreprocessMarkdown:
    def test_converts_info_alert(self):
        text = "::: info\nזו הודעת מידע\n:::"
        result = preprocess_markdown(text)
        assert 'class="alert alert-info"' in result
        assert "זו הודעת מידע" in result

    def test_converts_warning_alert(self):
        text = "::: warning\nזהירות!\n:::"
        result = preprocess_markdown(text)
        assert 'class="alert alert-warning"' in result

    def test_converts_tip_to_success(self):
        text = "::: tip\nטיפ שימושי\n:::"
        result = preprocess_markdown(text)
        assert 'class="alert alert-success"' in result

    def test_handles_multiline_content(self):
        text = "::: info\nשורה 1\nשורה 2\n:::"
        result = preprocess_markdown(text)
        assert "שורה 1" in result
        assert "שורה 2" in result

    def test_consecutive_alerts_not_merged(self):
        text = "::: info\nFirst alert\n:::\n\n::: warning\nSecond alert\n:::"
        result = preprocess_markdown(text)
        assert "alert-info" in result
        assert "alert-warning" in result
        assert result.count('class="alert') == 2


class TestGetExportTheme:
    def test_returns_builtin_preset(self):
        theme = get_export_theme("tech-guide-dark")
        assert theme["name"] == "Tech Guide Dark"
        assert "--bg-primary" in theme["variables"]
        assert theme["variables"]["--bg-primary"] == "#0f0f23"

    def test_returns_gallery_preset_when_available(self):
        presets = list_presets()
        if not presets:
            pytest.skip("No gallery presets available in this repo")
        first = presets[0]
        theme = get_export_theme(first["id"])
        assert theme["name"]
        assert isinstance(theme.get("variables", {}), dict)

    def test_fallback_to_default(self):
        theme = get_export_theme("nonexistent-theme")
        assert theme["name"] == "Tech Guide Dark"

    def test_syntax_css_included_for_tech_preset(self):
        theme = get_export_theme("tech-guide-dark")
        assert theme.get("syntax_css")
        assert ".highlight .k" in theme["syntax_css"]  # Keywords


class TestSecuritySanitization:
    """🔒 טסטי אבטחה - וידוא שהקוד חוסם XSS"""

    def test_blocks_script_tags_and_content(self):
        text = "Hello <script>alert('xss')</script> World"
        html, _ = markdown_to_html(text)
        assert "<script" not in html.lower()
        assert "alert(" not in html

    def test_blocks_javascript_protocol(self):
        text = "[Click me](javascript:alert('xss'))"
        html, _ = markdown_to_html(text)
        assert "javascript:" not in html.lower()

    def test_blocks_onerror_attribute(self):
        text = '<img src="x" onerror="alert(1)">'
        html, _ = markdown_to_html(text)
        assert "onerror" not in html.lower()

    def test_allows_safe_links(self):
        text = "[Google](https://google.com)"
        html, _ = markdown_to_html(text)
        assert 'href="https://google.com"' in html

    def test_adds_noopener_to_blank_target(self):
        text = '<a href="https://example.com" target="_blank">Link</a>'
        html, _ = markdown_to_html(text)
        assert 'rel="noopener noreferrer"' in html

    def test_noopener_replaces_rel_without_corrupting_quotes(self):
        # מקרה קצה: rel עם גרשיים בתוך מרכאות כפולות (לא סטנדרטי אבל יכול להגיע מ-HTML גולמי)
        text = '<a href="https://example.com" target="_blank" rel="don\'t">Link</a>'
        html, _ = markdown_to_html(text)
        assert 'rel="noopener noreferrer"' in html
        assert 'rel="noopener noreferrer"t"' not in html


class TestTocGeneration:
    """📑 טסטי TOC - וידוא שתוכן עניינים עובד"""

    def test_toc_generated_when_requested(self):
        text = "# Heading 1\n\nContent\n\n## Heading 2\n\nMore content"
        _html, toc = markdown_to_html(text, include_toc=True)
        assert toc
        assert "<ul" in toc or "<li" in toc

    def test_toc_empty_when_not_requested(self):
        text = "# Heading 1\n\nContent"
        _html, toc = markdown_to_html(text, include_toc=False)
        assert toc == ""

