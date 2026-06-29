import base64
import hashlib
import re

import pytest

from services.styled_export_service import (
    COPY_CODE_SCRIPT,
    COPY_CODE_SCRIPT_CSP_HASH,
    generate_pygments_css,
    get_copy_script_csp_hash,
    get_export_theme,
    get_pygments_style_for_theme,
    markdown_to_html,
    preprocess_markdown,
    HAS_PYGMENTS,
)
from services.theme_presets_service import list_presets


class TestPreprocessMarkdown:
    def test_converts_note_to_info_alert(self):
        text = "::: note\nהערה קצרה\n:::"
        result = preprocess_markdown(text)
        assert 'class="alert alert-info"' in result
        assert "הערה קצרה" in result

    def test_converts_important_to_warning_alert(self):
        text = "::: important\nזה חשוב\n:::"
        result = preprocess_markdown(text)
        assert 'class="alert alert-warning"' in result
        assert "זה חשוב" in result

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


class TestPygmentsCssGeneration:
    """🎨 טסטי יצירת CSS דינמי להדגשת תחביר"""

    @pytest.mark.skipif(not HAS_PYGMENTS, reason="Pygments not installed")
    def test_generate_pygments_css_returns_css(self):
        """ייצור CSS בסיסי"""
        css = generate_pygments_css("monokai", ".highlight")
        assert css
        assert ".highlight" in css
        # בדיקה שיש הגדרות צבעים
        assert "color:" in css or "background:" in css

    @pytest.mark.skipif(not HAS_PYGMENTS, reason="Pygments not installed")
    def test_generate_pygments_css_fallback_dark_on_invalid_style(self):
        """fallback ל-monokai (dark) כשהסגנון לא קיים וקטגוריה כהה"""
        css = generate_pygments_css("nonexistent-style-xyz", ".highlight", "dark")
        assert css  # אמור להחזיר CSS גם כשהסגנון לא קיים

    @pytest.mark.skipif(not HAS_PYGMENTS, reason="Pygments not installed")
    def test_generate_pygments_css_fallback_light_on_invalid_style(self):
        """fallback ל-default (light) כשהסגנון לא קיים וקטגוריה בהירה"""
        css = generate_pygments_css("nonexistent-style-xyz", ".highlight", "light")
        assert css  # אמור להחזיר CSS מתאים לערכה בהירה

    @pytest.mark.skipif(not HAS_PYGMENTS, reason="Pygments not installed")
    def test_generate_pygments_css_default_style(self):
        """בדיקת סגנון default"""
        css = generate_pygments_css("default", ".code")
        assert css
        assert ".code" in css

    def test_get_pygments_style_for_known_theme(self):
        """מיפוי ערכה ידועה לסגנון Pygments"""
        style = get_pygments_style_for_theme("tech-guide-dark", "dark")
        assert style == "monokai"

    def test_get_pygments_style_fallback_dark(self):
        """fallback לערכה לא ידועה בקטגוריה כהה"""
        style = get_pygments_style_for_theme("unknown-theme", "dark")
        assert style == "monokai"  # PYGMENTS_STYLE_DARK_FALLBACK

    def test_get_pygments_style_fallback_light(self):
        """fallback לערכה לא ידועה בקטגוריה בהירה"""
        style = get_pygments_style_for_theme("unknown-theme", "light")
        assert style == "default"  # PYGMENTS_STYLE_LIGHT_FALLBACK

    def test_get_pygments_style_handles_none_category(self):
        """הגנה מפני category=None (יכול להגיע מ-MongoDB)"""
        # לא צריך לזרוק AttributeError
        style = get_pygments_style_for_theme("unknown-theme", None)  # type: ignore[arg-type]
        assert style == "monokai"  # fallback to dark


class TestGetExportThemeWithMetadata:
    """בדיקות שה-get_export_theme מחזיר גם id ו-category"""

    def test_returns_id_and_category_for_builtin(self):
        theme = get_export_theme("tech-guide-dark")
        assert theme.get("id") == "tech-guide-dark"
        assert theme.get("category") == "dark"

    def test_returns_id_and_category_for_fallback(self):
        theme = get_export_theme("nonexistent-theme-xyz")
        assert theme.get("id") == "tech-guide-dark"
        assert theme.get("category") == "dark"

    def test_clean_light_theme_has_light_category(self):
        theme = get_export_theme("clean-light")
        assert theme.get("id") == "clean-light"
        assert theme.get("category") == "light"


def _sha256_csp(text: str) -> str:
    """מחשב מקור CSP מסוג sha256 כפי שדפדפן מחשב עבור סקריפט inline."""
    return "sha256-" + base64.b64encode(
        hashlib.sha256(text.encode("utf-8")).digest()
    ).decode("ascii")


class TestCopyButtonCspHash:
    """כפתור ההעתקה בבלוקי קוד חייב לעבוד גם בקישור השיתוף הציבורי.

    בעמוד השיתוף יש CSP מחמיר (``script-src 'sha256-...'``) שמתיר רק את סקריפט
    ההעתקה ה-inline. אם ה-hash לא תואם בדיוק לתוכן שמוזרק לתבנית — הדפדפן יחסום
    את הסקריפט והכפתור ייעלם. הטסטים האלה נועלים את ההתאמה הזו.
    """

    def test_csp_hash_is_self_consistent(self):
        assert COPY_CODE_SCRIPT_CSP_HASH == _sha256_csp(COPY_CODE_SCRIPT)
        assert get_copy_script_csp_hash() == COPY_CODE_SCRIPT_CSP_HASH
        assert COPY_CODE_SCRIPT_CSP_HASH.startswith("sha256-")

    def test_rendered_template_script_matches_csp_hash(self):
        """מרנדר את התבנית האמיתית ומוודא שה-hash של הסקריפט בפועל תואם ל-CSP.

        זה התרחיש שמגלה "drift" של רווחים: אם בתבנית יש רווח/שורה בין התגיות
        ``<script>``/``</script>`` לבין ``{{ copy_script }}`` — ה-hash ישתנה.
        """
        jinja2 = pytest.importorskip("jinja2")
        from jinja2 import Environment, FileSystemLoader, select_autoescape

        env = Environment(
            loader=FileSystemLoader("webapp/templates"),
            autoescape=select_autoescape(["html"]),
        )
        tpl = env.get_template("export/styled_document.html")
        html = tpl.render(
            title="t",
            content="<pre><code>x = 1</code></pre>",
            css_variables="",
            syntax_css="",
            theme_name="T",
            toc_html="",
            footer_text="f",
            copy_script=COPY_CODE_SCRIPT,
        )

        # הכפתור והסקריפט קיימים ב-HTML
        assert "copy-btn" in html
        assert "navigator.clipboard" in html

        # התוכן שבין התגיות זהה בדיוק לקבוע, ולכן ה-hash תואם ל-CSP.
        # ה-regex מתיר attributes ו-case שונה בתגית כדי להיות עמיד (CodeQL).
        match = re.search(
            r"<script\b[^>]*>(.*?)</script\s*>", html, re.DOTALL | re.IGNORECASE
        )
        assert match is not None, "לא נמצא בלוק <script> ב-HTML המעוצב"
        script_body = match.group(1)
        assert script_body == COPY_CODE_SCRIPT
        assert _sha256_csp(script_body) == COPY_CODE_SCRIPT_CSP_HASH

