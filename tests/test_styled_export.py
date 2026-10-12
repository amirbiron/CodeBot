import base64
import hashlib
import html as html_lib
import re

import pytest
from bs4 import BeautifulSoup

from services.styled_export_service import (
    ADMONITION_TYPES,
    COPY_CODE_SCRIPT,
    COPY_CODE_SCRIPT_CSP_HASH,
    DETAILS_DEFAULT_TITLE,
    MAX_CONTAINER_NESTING,
    generate_pygments_css,
    get_copy_script_csp_hash,
    get_export_theme,
    get_pygments_style_for_theme,
    markdown_to_html,
    HAS_PYGMENTS,
)
from services.theme_presets_service import list_presets


def _soup(text: str) -> BeautifulSoup:
    """הייצוא של ``text`` כמו שהראוטים מקבלים אותו — דרך ``markdown_to_html``."""
    html, _toc = markdown_to_html(text)
    return BeautifulSoup(html, "html.parser")


def _visible_text(html: str) -> str:
    """הטקסט בלי תגיות — בלוק קוד מפוצל על ידי Pygments לכמה ``<span>``."""
    return html_lib.unescape(re.sub(r"<[^>]+>", "", html))


#: הצבע שאושר לכל סוג. כתוב כאן במפורש, ולא נגזר מ-``ADMONITION_TYPES``, כדי
#: ששינוי בטבלה שבשירות יהיה החלטה שנראית בטסט — לא סחיפה שעוברת בשקט.
EXPECTED_ALERT_CLASS = {
    "note": "info",
    "info": "info",
    "example": "info",
    "todo": "info",
    "tip": "success",
    "success": "success",
    "warning": "warning",
    "experimental": "warning",
    "important": "warning",
    "question": "warning",
    "danger": "danger",
    "quote": "neutral",
    "deprecated": "neutral",
    "abstract": "neutral",
}


class TestContainers:
    """מכולות ``:::`` בייצוא — תיבות הסבר ו-``details``, כמו בתצוגת ה-Markdown בוובאפ.

    כולם עוברים דרך ``markdown_to_html``, הפונקציה שהראוטים של הייצוא והשיתוף
    קוראים לה. ההתאמה של רשימת הסוגים לוובאפ נבדקת ב-
    ``tests/test_styled_export_containers_parity.py``.
    """

    def test_every_type_is_a_box_with_its_color_and_default_title(self):
        assert set(EXPECTED_ALERT_CLASS) == set(ADMONITION_TYPES)
        problems = []
        for kind, css_class in EXPECTED_ALERT_CLASS.items():
            box = _soup(f"::: {kind}\nתוכן\n:::").select_one("div.alert")
            if box is None:
                problems.append(f"{kind}: לא הפך לתיבה")
                continue
            if box["class"] != ["alert", f"alert-{css_class}"]:
                problems.append(f"{kind}: מחלקה {box['class']}, ציפינו ל-alert-{css_class}")
            title = box.select_one("div.alert-title")
            if title is None or title.get_text() != ADMONITION_TYPES[kind].title:
                problems.append(f"{kind}: כותרת {title.get_text() if title else None!r}")
            content = box.select_one("p")
            if content is None or content.get_text() != "תוכן":
                problems.append(f"{kind}: התוכן לא נכנס לתיבה")
        assert not problems, "\n".join(problems)

    def test_custom_title_replaces_the_default(self):
        box = _soup("::: warning כותרת משלי\nx\n:::").select_one("div.alert-warning")
        assert box.select_one("div.alert-title").get_text() == "כותרת משלי"

    def test_title_is_escaped_text_not_html_or_markdown(self):
        html, _ = markdown_to_html("::: note <b>x</b> **y**\nתוכן\n:::")
        assert '<div class="alert-title">&lt;b&gt;x&lt;/b&gt; **y**</div>' in html

    def test_details_with_and_without_a_title(self):
        soup = _soup("::: details כותרת\nתוכן מוסתר\n:::\n\n::: details\nעוד\n:::")
        first, second = soup.select("details.markdown-details")
        assert first.select_one("summary.markdown-summary").get_text() == "כותרת"
        assert first.select_one("div.details-content > p").get_text() == "תוכן מוסתר"
        assert second.select_one("summary.markdown-summary").get_text() == DETAILS_DEFAULT_TITLE
        assert not first.has_attr("open"), "::: details נפתח סגור, כמו בוובאפ"

    def test_details_title_is_escaped(self):
        html, _ = markdown_to_html("::: details <img src=x onerror=alert(1)>\ny\n:::")
        summary = '<summary class="markdown-summary">&lt;img src=x onerror=alert(1)&gt;</summary>'
        assert summary in html

    def test_type_is_case_insensitive_and_ends_at_a_latin_word_boundary(self):
        """כמו ``/^note\\b\\s*(.*)$/i`` בוובאפ, שבו ``\\b`` מכיר רק אותיות לטיניות."""
        assert _soup("::: NOTE\nx\n:::").select_one("div.alert-info") is not None
        hebrew_title = _soup("::: noteכותרת\nx\n:::").select_one("div.alert-info div.alert-title")
        assert hebrew_title is not None and hebrew_title.get_text() == "כותרת"
        assert _soup("::: notebook\nx\n:::").select_one("div.alert") is None
        assert _soup("::: custom\nx\n:::").select_one("div.alert") is None

    @pytest.mark.parametrize("fence", ["```", "~~~"])
    def test_container_syntax_inside_a_code_block_stays_code(self, fence):
        """מדריך שמדגים את התחביר בבלוק קוד — הדוגמה נשארת כמו שהיא."""
        sample = "::: details כותרת\n::: note\nx\n:::\n:::"
        html, _ = markdown_to_html(f"{fence}markdown\n{sample}\n{fence}")
        assert 'class="alert' not in html and "<details" not in html
        assert sample in _visible_text(html)

    def test_code_and_table_inside_a_box_are_rendered(self):
        soup = _soup("::: tip\n```python\nprint(1)\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |\n:::")
        box = soup.select_one("div.alert-success")
        assert box.select_one("div.highlight pre") is not None
        assert box.select_one("table td").get_text() == "1"

    def test_a_longer_outer_fence_nests_containers(self):
        soup = _soup(":::: details פרטים\n::: tip\nטיפ\n:::\n::::")
        inner = soup.select_one("details.markdown-details > .details-content > .alert-success")
        assert inner is not None and inner.select_one("p").get_text() == "טיפ"
        assert ":::" not in soup.get_text()

    def test_an_equal_fence_inner_closer_closes_the_outer_box_like_the_webapp(self):
        """ה-``:::`` הראשון סוגר את החיצונית — כך גם ב-markdown-it-container."""
        soup = _soup("::: details\n::: note\nx\n:::\n:::")
        assert soup.select_one("details div.details-content > div.alert-info") is not None
        assert soup.find_all("p")[-1].get_text() == ":::"

    def test_an_empty_box_does_not_swallow_what_follows(self):
        soup = _soup("::: note\n:::\nטקסט באמצע\n::: warning\nw\n:::")
        note, warning = soup.select("div.alert")
        assert note.select_one("p") is None
        assert "טקסט באמצע" not in note.get_text() and "טקסט באמצע" not in warning.get_text()
        assert warning["class"] == ["alert", "alert-warning"]

    def test_unclosed_box_ends_at_the_end_of_the_document(self):
        box = _soup("::: note\nx").select_one("div.alert-info")
        assert box is not None and box.select_one("p").get_text() == "x"

    @pytest.mark.parametrize(
        "text",
        ["::: note\nx\n:::   ", ":::: note\nx\n::::", "::: note\nx\n::::", ":::note\nx\n:::"],
        ids=["closer-trailing-spaces", "four-colons", "longer-closer", "no-space-after-colons"],
    )
    def test_fence_variants_the_webapp_accepts(self, text):
        box = _soup(text).select_one("div.alert-info")
        assert box is not None and box.select_one("p").get_text() == "x"

    def test_a_box_interrupts_a_paragraph_and_a_list(self):
        soup = _soup("לפני\n::: note\nx\n:::\nאחרי\n\n- פריט\n::: tip\ny\n:::")
        assert [p.get_text() for p in soup.find_all("p", recursive=False)] == ["לפני", "אחרי"]
        assert soup.select_one("ul > li").get_text() == "פריט"
        assert soup.select_one("ul div.alert") is None

    def test_heading_inside_details_is_in_the_toc(self):
        text = "# ראשי\n\n::: details פרטים\n## בפנים\ntext\n:::"
        html, toc = markdown_to_html(text, include_toc=True)
        heading = BeautifulSoup(html, "html.parser").select_one("details div.details-content h2")
        assert heading is not None and heading.get("id")
        assert f'href="#{heading["id"]}"' in toc

    def test_html_inside_a_box_is_sanitized(self):
        html, _ = markdown_to_html(
            "::: note\n<script>alert(1)</script>\n<img src=x onerror=alert(2)>\n"
            "[a](javascript:alert(3))\n:::"
        )
        assert "<script" not in html.lower()
        assert "onerror" not in html.lower()
        assert "javascript:" not in html.lower()

    def test_nesting_stops_at_the_cap_and_keeps_the_text(self):
        depth = MAX_CONTAINER_NESTING + 5
        openings = "".join(":" * (depth + 3 - i) + " note\n" for i in range(depth))
        closings = "".join(":" * (4 + i) + "\n" for i in range(depth))
        html, _ = markdown_to_html(openings + "עמוק\n" + closings)
        assert html.count('<div class="alert alert-info">') == MAX_CONTAINER_NESTING
        assert "עמוק" in html

    def test_containers_near_the_recursion_limit_stay_text_instead_of_crashing(self):
        """ליד תקרת הרקורסיה של פייתון המכולה מוותרת ונשארת טקסט — כמו הציטוט של Python-Markdown.

        ציטוטים מקוננים עד העומק שבו הספרייה עצמה מפסיקה לקנן אותם, ובתוכם מכולות
        מקוננות עד ``MAX_CONTAINER_NESTING``. בלי ``nearing_recursion_limit`` ב-``test``
        של המעבד זה נפל ב-``RecursionError``, כלומר הייצוא כולו נכשל. העומק נגזר
        כאן ולא נקבע מראש, כי המחסנית שמתחת לטסט משתנה עם הדרך שבה הוא רץ.
        """
        probe, _ = markdown_to_html("> " * 1000 + "x")
        quotes = probe.count("<blockquote>")
        n = MAX_CONTAINER_NESTING
        openings = [":" * (n + 3 - i) + " note" for i in range(n)]
        lines = openings + ["עמוק"] + [":" * (4 + i) for i in range(n)]
        html, _ = markdown_to_html("\n".join("> " * quotes + line for line in lines))
        assert html.count("<blockquote>") == quotes
        assert "עמוק" in html

    def test_consecutive_boxes_are_not_merged(self):
        soup = _soup("::: info\nFirst alert\n:::\n\n::: warning\nSecond alert\n:::")
        classes = [box["class"][1] for box in soup.select("div.alert")]
        assert classes == ["alert-info", "alert-warning"]


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

        # התבנית מזריקה את הקבוע מילה-במילה בין התגיות, בלי רווחים נוספים, ולכן
        # ה-hash שב-CSP תואם בדיוק לתוכן. בודקים זאת בהשוואת מחרוזת מדויקת (ולא
        # ב-regex של חילוץ HTML, שמעורר את חוקת "Bad HTML filtering" של CodeQL):
        expected_script_block = "<script>" + COPY_CODE_SCRIPT + "</script>"
        assert expected_script_block in html
        assert _sha256_csp(COPY_CODE_SCRIPT) == COPY_CODE_SCRIPT_CSP_HASH

