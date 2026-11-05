"""הייצוא ל-HTML מעוצב מהעורך הציבורי — מה שהשרת מגיש: השלד, הערכות, וה-CSS שנכנס לקובץ.

השרת לא רואה את הטקסט של הגולש: הוא מגיש רק את העמוד המעוצב של הערכה, עם הערת HTML במקום התוכן
(``markdown_editor_export_skeleton`` ב-``webapp/app.py``), והדפדפן מכניס לשם את המסמך. הזרימה בדפדפן — הרינדור,
ההורדה, התצוגה, והקובץ כשהוא נפתח לבד — ב-``tests/test_markdown_editor_export_browser.py``.
הרקע: ``docs/webapp/markdown-editor.rst``.
"""

from __future__ import annotations

import base64
import hashlib
import html
import itertools
import re
from pathlib import Path

import pytest

pytest.importorskip("flask")

from flask import Flask  # noqa: E402

from services.styled_export_service import (  # noqa: E402
    ADMONITION_TYPES,
    COPY_CODE_SCRIPT,
    COPY_CODE_SCRIPT_CSP_HASH,
    EDITOR_EXPORT_CONTENT_MARKER,
    EDITOR_EXPORT_FOOTER,
    EXPORT_HLJS_SELECTOR_PREFIX,
    EXPORT_PRESETS,
    PREVIOUS_COPY_CODE_SCRIPT_CSP_HASHES,
    _EVERFOREST_DARK_TOKEN_COLORS,
    _MORASS_TOKEN_COLORS,
    _PEN_PAPER_COFFEE_TOKEN_COLORS,
    get_export_theme,
    list_export_presets,
    render_editor_export_skeleton,
    render_styled_html,
    sanitize_css,
    styled_share_csp,
)
from services.theme_parser_service import (  # noqa: E402
    HLJS_SITE_THEME_SELECTOR_PREFIX,
    generate_hljs_css_from_tokens,
    generate_pygments_css_from_tokens,
)

REPO = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO / "webapp" / "templates"
JS_DIR = REPO / "webapp" / "static" / "js"
SKELETON_PATH = "/api/markdown-editor/export-skeleton/{}"
#: עותק מכוון של ``EXPORT_THEME_IDS`` (``webapp/markdown_editor.py``), כדי שהטסטים יקבעו מה הרשימה ולא רק יקראו
#: אותה. ``test_the_editor_export_themes_are_listed_for_the_logged_in_export_too`` משווה בין השניים.
THEMES = ("morass", "pen-paper-coffee", "everforest-dark")


def _sha256_csp(text: str) -> str:
    return "sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii")


def _css_rules(css: str) -> dict[str, str]:
    """בורר ← גוף הכלל, אחרי הורדת הערות ורווחים מיותרים. כלל שמופיע פעמיים — האחרון."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    rules = {}
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        rules[" ".join(selector.split())] = " ".join(body.split())
    return rules


def _render_skeleton(theme_id: str, katex_css: str = "") -> str:
    app = Flask(__name__, template_folder=str(TEMPLATES_DIR))
    with app.app_context():
        return render_editor_export_skeleton(get_export_theme(theme_id), katex_css=katex_css)


@pytest.fixture
def wa():
    import webapp.app as webapp_app

    return webapp_app


_GUEST_ADDRESSES = itertools.count(1)


def guest_client(wa):
    """client חדש, בלי session — כמו גולש שהגיע מחיפוש — עם כתובת IP משלו.

    הנתיב כפוף למגבלת הקצב הגורפת (``default_limits`` של ה-``Limiter`` ב-``webapp/app.py``), והמגביל סופר לפי
    ``X-Forwarded-For`` (``_client_rate_key``). בתהליך
    הבדיקה האחסון שלו בזיכרון ומשותף לכל הטסטים, ולכן בלי כתובת לכל client הטסטים היו נחסמים זה בגלל זה — לפי
    הסדר שבו רצו (TESTING-PATTERNS T3). כתובת חדשה במקום איפוס של המגביל: הטסט לא נוגע במצב של אחרים.
    """
    c = wa.app.test_client()
    c.environ_base["HTTP_X_FORWARDED_FOR"] = f"198.51.100.{next(_GUEST_ADDRESSES) % 250 + 1}"
    return c


@pytest.fixture
def client(wa):
    return guest_client(wa)


# ---------------------------------------------------------------------------
# הנתיב
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("theme_id", THEMES)
def test_the_skeleton_answers_without_login(client, theme_id):
    resp = client.get(SKELETON_PATH.format(theme_id))

    # 200 ישיר ולא הפניה ל-/login
    assert resp.status_code == 200, resp.status_code
    assert resp.mimetype == "text/html"


@pytest.mark.parametrize(
    "path",
    [
        SKELETON_PATH.format("tech-guide-dark"),  # ערכת ייצוא קיימת, אבל לא של העורך
        SKELETON_PATH.format("no-such-theme"),
        SKELETON_PATH.format("morass") + "?math=0",
        SKELETON_PATH.format("morass") + "?math=true",
        SKELETON_PATH.format("morass") + "?math=",
    ],
)
def test_any_other_theme_or_math_value_is_not_found(client, path):
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("theme_id", THEMES)
def test_the_skeleton_carries_one_marker_and_no_header_banner(client, theme_id):
    body = client.get(SKELETON_PATH.format(theme_id)).get_data(as_text=True)

    assert body.count(EDITOR_EXPORT_CONTENT_MARKER) == 1
    # בלי באנר עליון: לקובץ אין שם, והכיתוב נשאר רק בתחתית — בלי "Bot"
    assert "<header>" not in body
    assert body.count('class="subtitle"') == 0
    footer = body[body.index("<footer>"):body.index("</footer>")]
    assert EDITOR_EXPORT_FOOTER.replace('"', "&#34;") in footer
    assert "Bot" not in footer
    assert f"Theme: {EXPORT_PRESETS[theme_id]['name']}" in footer


def test_the_skeleton_is_under_the_global_rate_limit(wa):
    """שלא כמו העמוד, השלד אינו פטור: זו פעולה שגולש מפעיל, לא עמוד שסורקים נכנסים אליו."""
    from flask_limiter import ExemptionScope

    assert wa.limiter is not None
    manager = wa.limiter.limit_manager
    assert not manager.exemption_scope(wa.app, "markdown_editor_export_skeleton", None) & ExemptionScope.DEFAULT
    # בקרה: העמוד עצמו פטור, כלומר הבדיקה מסוגלת להבחין
    assert manager.exemption_scope(wa.app, "markdown_editor", None) & ExemptionScope.DEFAULT


def test_the_skeleton_is_the_same_for_every_visitor(wa):
    """אין בשלד שום דבר של הבקשה: שני גולשים, אחד עם session, מקבלים אותו גוף בדיוק."""
    first = guest_client(wa).get(SKELETON_PATH.format("morass")).get_data()
    member = guest_client(wa)
    with member.session_transaction() as sess:
        sess["user_id"] = 4242
    second = member.get(SKELETON_PATH.format("morass")).get_data()
    assert first == second


def test_the_skeleton_has_its_own_strict_csp(client):
    resp = client.get(SKELETON_PATH.format("pen-paper-coffee"))
    csp = resp.headers.get_all("Content-Security-Policy")

    # כותרת אחת: המדיניות הגורפת של העמודים (``_add_default_csp``) לא נוספת לידה (browser-policy B1)
    assert len(csp) == 1, csp
    directives = {d.split()[0]: d.split()[1:] for d in csp[0].split("; ")}
    assert directives["default-src"] == ["'none'"]
    assert directives["script-src"] == [f"'{COPY_CODE_SCRIPT_CSP_HASH}'"]


@pytest.mark.parametrize("theme_id", THEMES)
def test_the_file_carries_a_csp_that_allows_only_the_copy_script(client, theme_id):
    """הקובץ נפתח אצל הגולש מהדיסק, בלי כותרת מהשרת — ולכן המדיניות בתוכו."""
    body = client.get(SKELETON_PATH.format(theme_id)).get_data(as_text=True)
    meta = re.findall(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">', body)

    assert len(meta) == 1
    directives = {d.split()[0]: d.split()[1:] for d in html.unescape(meta[0]).split("; ")}
    # הכול חסום, חוץ ממה שהקובץ צריך: סקריפט ההעתקה, העיצוב שבתוכו, הגופנים המוטמעים, ותמונות
    assert directives == {
        "default-src": ["'none'"],
        "script-src": [f"'{COPY_CODE_SCRIPT_CSP_HASH}'"],
        "style-src": ["'unsafe-inline'"],
        "font-src": ["data:"],
        "img-src": ["data:", "http:", "https:"],
        "base-uri": ["'none'"],
    }
    # התגית לפני הסקריפט (CSP ב-meta חל רק על מה שאחריו), והסקריפט הוא בדיוק מה שה-hash מתיר
    assert body.index('http-equiv="Content-Security-Policy"') < body.index("<script>")
    assert "<script>" + COPY_CODE_SCRIPT + "</script>" in body


def test_the_skeleton_is_revalidated_with_an_etag(client):
    resp = client.get(SKELETON_PATH.format("morass"))
    assert resp.headers["Cache-Control"] == "no-cache"
    etag = resp.headers.get("ETag")
    assert etag

    again = client.get(SKELETON_PATH.format("morass"), headers={"If-None-Match": etag})
    assert again.status_code == 304
    assert again.get_data() == b""
    # בקרה: ETag אחר מקבל את הגוף המלא
    other = client.get(SKELETON_PATH.format("morass"), headers={"If-None-Match": '"other"'})
    assert other.status_code == 200 and other.get_data()


def test_katex_is_in_the_file_only_when_the_document_has_math(client):
    plain = client.get(SKELETON_PATH.format("morass")).get_data(as_text=True)
    with_math = client.get(SKELETON_PATH.format("morass") + "?math=1").get_data(as_text=True)

    assert "@font-face" not in plain and ".katex" not in plain
    assert ".katex" in with_math
    # כל הגופנים בתוך הקובץ: אין הפניה לקובץ חיצוני
    assert with_math.count("url(data:font/woff2;base64,") == with_math.count("@font-face") > 0
    assert "./fonts/" not in with_math
    # ה-ETag שונה, כי הגוף שונה
    assert client.get(SKELETON_PATH.format("morass")).headers["ETag"] != client.get(
        SKELETON_PATH.format("morass") + "?math=1"
    ).headers["ETag"]


# ---------------------------------------------------------------------------
# ה-CSS של KaTeX
# ---------------------------------------------------------------------------


def test_the_katex_css_embeds_one_woff2_per_font_and_passes_sanitization():
    from webapp.markdown_editor import katex_inline_css

    katex_inline_css.cache_clear()
    css = katex_inline_css()
    faces = re.findall(r"@font-face\s*\{(.*?)\n\}", css, re.DOTALL)

    assert faces, "אין @font-face — הסימונים של esbuild בבאנדל השתנו?"
    assert [face.count("url(data:font/woff2;base64,") for face in faces] == [1] * len(faces)
    assert not re.search(r'format\("(woff|truetype)"\)', css)
    # הסניטציה שהתבנית מפעילה לא משנה בו כלום — base64 לא מכיל את התבניות שהיא חוסמת
    assert sanitize_css(css) == css


def test_a_missing_katex_font_fails_loudly_and_is_not_remembered(monkeypatch, tmp_path):
    """CSS חלקי היה מותח את כל העמוד לרוחב (השורש הריבועי של KaTeX), ולכן כשל זורק ולא נשמר."""
    import webapp.markdown_editor as me

    bundle = tmp_path / "md_preview.bundle.css"
    bundle.write_text(
        me.KATEX_CSS_START
        + '\n@font-face { src: url("./fonts/missing.woff2") format("woff2"); }\n'
        + me.KATEX_CSS_END,
        encoding="utf-8",
    )
    (tmp_path / "fonts").mkdir()
    monkeypatch.setattr(me, "MD_PREVIEW_BUNDLE_CSS", bundle)
    me.katex_inline_css.cache_clear()
    try:
        with pytest.raises(FileNotFoundError):
            me.katex_inline_css()
        (tmp_path / "fonts" / "missing.woff2").write_bytes(b"woff2")
        assert "url(data:font/woff2;base64,d29mZjI=)" in me.katex_inline_css()
    finally:
        me.katex_inline_css.cache_clear()


def _katex_css_from(monkeypatch, tmp_path, src: str, fonts: dict[str, bytes]) -> str:
    """``katex_inline_css`` על באנדל מדומה, עם הצהרת ``src`` אחת וגופנים בתיקייה."""
    import webapp.markdown_editor as me

    bundle = tmp_path / "md_preview.bundle.css"
    bundle.write_text(f"{me.KATEX_CSS_START}\n@font-face {{\n  src: {src};\n}}\n{me.KATEX_CSS_END}", encoding="utf-8")
    (tmp_path / "fonts").mkdir()
    for name, data in fonts.items():
        (tmp_path / "fonts" / name).write_bytes(data)
    monkeypatch.setattr(me, "MD_PREVIEW_BUNDLE_CSS", bundle)
    me.katex_inline_css.cache_clear()
    try:
        return me.katex_inline_css()
    finally:
        me.katex_inline_css.cache_clear()


def test_the_katex_src_is_rebuilt_whatever_the_order_of_its_entries(monkeypatch, tmp_path):
    """ההצהרה נבנית מחדש מרשומת ה-woff2 שלה, ולכן woff2 שאינו ראשון לא משאיר ``src: ,`` שבור."""
    css = _katex_css_from(
        monkeypatch,
        tmp_path,
        'url("./fonts/a.ttf") format("truetype"), url("./fonts/a.woff2") format("woff2"), url("./fonts/a.woff") format("woff")',
        {"a.woff2": b"woff2"},
    )
    assert 'src: url(data:font/woff2;base64,d29mZjI=) format("woff2");' in css
    assert "truetype" not in css and ".woff\"" not in css


def test_a_katex_src_without_exactly_one_woff2_fails_loudly(monkeypatch, tmp_path):
    with pytest.raises(ValueError):
        _katex_css_from(monkeypatch, tmp_path, 'url("./fonts/a.ttf") format("truetype")', {})


# ---------------------------------------------------------------------------
# העיצוב של markdown-it בשלד (R6: עותק שני של כללים — ולכן משווים)
# ---------------------------------------------------------------------------


def test_every_admonition_type_gets_the_colors_of_its_alert_group():
    """לכל סוג התראה של markdown-it אותם צבעים כמו ``.alert-<קבוצה>`` שהתבנית נותנת לייצוא של המחוברים."""
    rules = _css_rules(_render_skeleton("pen-paper-coffee"))
    alert_rules = {sel: body for sel, body in rules.items() if sel.startswith(".alert-")}
    admonition_bodies = {}
    for selector, body in rules.items():
        for kind in re.findall(r"\.admonition-([a-z]+)", selector):
            if kind not in ("title", "content"):
                admonition_bodies[kind] = body

    assert set(admonition_bodies) == set(ADMONITION_TYPES)
    for kind, admonition in ADMONITION_TYPES.items():
        expected = alert_rules[f".alert-{admonition.css_class}"]
        assert _decl(admonition_bodies[kind]) == _decl(expected), kind


def _decl(body: str) -> dict[str, str]:
    """הצבעים של כלל התראה בלבד (גבול ורקע) — שאר ההצהרות שונות בכוונה (``border-inline-start`` מול ``border-right``)."""
    out = {}
    for part in body.split(";"):
        if ":" in part:
            name, value = part.split(":", 1)
            if name.strip() in ("border-color", "background"):
                out[name.strip()] = " ".join(value.split())
    return out


@pytest.mark.parametrize(
    "css_class, source",
    [
        ("admonition-title", "live-preview.js"),
        ("admonition-content", "live-preview.js"),
        ("mermaid-diagram", "live-preview.js"),
        ("code-block", "md-code-blocks.js"),
        ("md-code-header", "md-code-blocks.js"),
        ("rtl-code", "utils/rtl-code.js"),
        ("rtl-code-ltr", "utils/rtl-code.js"),
        ("task-list-item-checkbox", "md_preview.bundle.js"),
    ],
)
def test_the_classes_the_skeleton_styles_are_the_ones_the_engine_emits(css_class, source):
    """שם מחלקה שהשלד מעצב ושהמנוע הפסיק לייצר — עיצוב שלא חל על כלום, בלי שום שגיאה."""
    css = (TEMPLATES_DIR / "export" / "_editor_export_styles.css").read_text(encoding="utf-8")
    assert f".{css_class}" in css
    assert css_class in (JS_DIR / source).read_text(encoding="utf-8")


def test_the_logged_in_export_keeps_its_banner_and_has_none_of_the_editor_parts():
    """הייצוא של המחוברים (Python-Markdown) לא משתנה: באנר, הכיתוב עם "Bot", כללי Pygments, ובלי CSP בקובץ."""
    app = Flask(__name__, template_folder=str(TEMPLATES_DIR))
    with app.app_context():
        html = render_styled_html("<p>x</p>", "t", get_export_theme("morass"))
    assert "<header>" in html
    assert "Code Keeper Bot" in html
    assert ".highlight ." in html
    assert "http-equiv" not in html
    assert ".admonition" not in html and "code.hljs" not in html


# ---------------------------------------------------------------------------
# הערכות של הייצוא מהעורך
# ---------------------------------------------------------------------------


def test_the_editor_export_themes_are_listed_for_the_logged_in_export_too():
    from webapp.markdown_editor import EXPORT_THEME_IDS

    assert EXPORT_THEME_IDS == THEMES
    listed = {p["id"]: p for p in list_export_presets()}
    assert {theme_id: listed[theme_id]["category"] for theme_id in THEMES} == {
        "morass": "dark",
        "pen-paper-coffee": "light",
        "everforest-dark": "dark",
    }


@pytest.mark.parametrize(
    "theme_id, tokens",
    [
        ("morass", _MORASS_TOKEN_COLORS),
        ("pen-paper-coffee", _PEN_PAPER_COFFEE_TOKEN_COLORS),
        ("everforest-dark", _EVERFOREST_DARK_TOKEN_COLORS),
    ],
)
def test_both_syntax_styles_come_from_the_theme_token_colors(theme_id, tokens):
    """מקור אחד לצבעי התחביר: Pygments לייצוא של המחוברים, highlight.js לייצוא מהעורך."""
    theme = get_export_theme(theme_id)
    assert theme["syntax_css"] == generate_pygments_css_from_tokens(tokens)
    assert theme["hljs_css"] == generate_hljs_css_from_tokens(tokens, selector_prefix=EXPORT_HLJS_SELECTOR_PREFIX)
    assert all(line.startswith("code.hljs .hljs-") for line in theme["hljs_css"].splitlines())


def test_the_editor_export_themes_keep_the_template_headings():
    """החלטה: הקו מתחת ל-H2 וצבעי הכותרות של התבנית נשארים — אין לערכות ``extra_css`` שדורס אותם."""
    for theme_id in THEMES:
        assert not EXPORT_PRESETS[theme_id].get("extra_css")


def test_the_site_themes_keep_the_default_hljs_prefix():
    tokens = [{"scope": "keyword", "settings": {"foreground": "#123456"}}]
    assert generate_hljs_css_from_tokens(tokens) == (
        f"{HLJS_SITE_THEME_SELECTOR_PREFIX} .hljs-keyword {{ color: #123456 !important; }}"
    )


# ---------------------------------------------------------------------------
# סקריפט ההעתקה, וקישורי שיתוף שכבר נוצרו
# ---------------------------------------------------------------------------

#: סקריפט ההעתקה כמו שהיה עד נובמבר 2026 — כמו שהוא שמור בקישורי שיתוף מעוצבים שנוצרו עד אז (ה-HTML נשמר
#: ביצירה, ``styled_shares``). מועתק בדיוק, בייט-לבייט, מייצוא שנוצר לפני השינוי.
COPY_CODE_SCRIPT_UNTIL_NOV_2026 = """
(function() {
    'use strict';

    // מוסיף כפתור "העתק" לכל בלוק קוד
    document.querySelectorAll('pre').forEach(function(codeBlock) {
        // יצירת הכפתור
        var button = document.createElement('button');
        button.className = 'copy-btn';
        button.type = 'button';
        button.innerHTML = '📋 <span>העתק</span>';
        button.title = 'העתק קוד ללוח';
        button.setAttribute('aria-label', 'העתק קוד ללוח');

        button.addEventListener('click', function() {
            // מציאת הקוד להעתקה
            var codeEl = codeBlock.querySelector('code');
            var textToCopy = codeEl ? codeEl.innerText : codeBlock.innerText;

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


def test_the_copy_script_copies_the_characters_and_not_the_layout():
    """``innerText`` מוסיף שורה ריקה סביב כל אלמנט בלוק — וקטע קוד בתוך בלוק קוד בעברית עטוף באחד כזה.
    ההוכחה בדפדפן: ``tests/test_markdown_editor_export_browser.py``."""
    assert "var textToCopy = codeEl ? codeEl.textContent : codeBlock.textContent;" in COPY_CODE_SCRIPT
    assert ".innerText" not in COPY_CODE_SCRIPT


def test_shares_created_with_the_previous_copy_script_keep_their_copy_button():
    """הקישור מגיש את ה-HTML כמו שנשמר, וה-CSP שלו נבנה בכל בקשה — ולכן הוא חייב להתיר גם את הסקריפט הישן."""
    assert _sha256_csp(COPY_CODE_SCRIPT_UNTIL_NOV_2026) in PREVIOUS_COPY_CODE_SCRIPT_CSP_HASHES
    allowed = re.findall(r"'(sha256-[^']+)'", styled_share_csp())
    assert _sha256_csp(COPY_CODE_SCRIPT_UNTIL_NOV_2026) in allowed
    assert COPY_CODE_SCRIPT_CSP_HASH in allowed


def test_the_share_route_sends_the_csp_that_allows_both_versions(wa, monkeypatch):
    class _Shares:
        def find_one(self, query):
            return {
                "token": query["token"],
                "is_permanent": True,  # קישור קבוע — בדיוק המקרה שאין לו תוקף שיפוג
                "styled_html": "<html><script>" + COPY_CODE_SCRIPT_UNTIL_NOV_2026 + "</script></html>",
            }

        def update_one(self, *args, **kwargs):
            return None

    class _Db:
        styled_shares = _Shares()

    monkeypatch.setattr(wa, "get_db", lambda: _Db())
    resp = guest_client(wa).get("/shared/styled/abc")

    assert resp.status_code == 200, resp.status_code
    assert resp.headers["Content-Security-Policy"] == styled_share_csp()
