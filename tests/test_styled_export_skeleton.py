"""הייצוא של המחוברים כשהמסמך מרונדר בדפדפן — מה שהשרת מגיש: צבעי highlight.js לכל סוג ערכה, והשלד.

- **צבעי highlight.js:** לערכות הייצוא של העורך יש ``hljs_css`` משלהן; ערכה מיובאת מ-VS Code שומרת כללים תחת הקידומת של
  האתר, והם עוברים לקידומת של הייצוא (``rebase_hljs_css``); לכל ערכה אחרת — הפלטה שנגזרת מהמשתנים, שנקראת
  מ-``md-content-colors.css`` (``export_hljs_fallback_css``) ולא נכתבת שוב.
- **השלד:** ``render_styled_export_skeleton`` — באנר עם שם הקובץ, הכיתוב של המחוברים, הסימון של markdown-it וה-CSP
  שבקובץ.

הזרימה בדפדפן — ב-``tests/test_styled_export_browser.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("flask")

from markupsafe import escape  # noqa: E402

from services.styled_export_service import (  # noqa: E402
    EDITOR_EXPORT_CONTENT_MARKER,
    EXPORT_HLJS_SELECTOR_PREFIX,
    STYLED_EXPORT_FOOTER,
    editor_export_meta_csp,
    get_export_theme,
    render_editor_export_skeleton,
    render_styled_export_skeleton,
)
from services.theme_parser_service import (  # noqa: E402
    HLJS_SITE_THEME_SELECTOR_PREFIX,
    parse_vscode_theme,
    rebase_hljs_css,
)

REPO = Path(__file__).resolve().parent.parent

# ערכת VS Code קטנה: שני טוקנים עם צבע, וצבעי עורך (שמהם נבנה הכלל הבסיסי ``.hljs``)
VSCODE_THEME = {
    "name": "Tiny",
    "type": "dark",
    "colors": {"editor.background": "#101010", "editor.foreground": "#eeeeee"},
    "tokenColors": [
        {"scope": ["keyword"], "settings": {"foreground": "#ff0000"}},
        {"scope": ["comment"], "settings": {"foreground": "#00ff00", "fontStyle": "italic"}},
    ],
}


@pytest.fixture
def app_ctx():
    import webapp.app as wa

    with wa.app.test_request_context("/"):
        yield wa


def _user_theme() -> dict:
    """ערכה כמו ש-``import_theme`` שומר אותה: ``syntax_css`` עם CodeMirror, ‏Pygments ו-highlight.js תחת הקידומת של האתר."""
    parsed = parse_vscode_theme(VSCODE_THEME)
    return {"id": "u1", "name": "Tiny", "category": "dark", "variables": parsed["variables"], "syntax_css": parsed["syntax_css"]}


# ---------------------------------------------------------------------------
# rebase_hljs_css
# ---------------------------------------------------------------------------


def test_rebase_takes_only_the_hljs_token_rules_under_the_new_prefix():
    stored = parse_vscode_theme(VSCODE_THEME)["syntax_css"]
    assert f"{HLJS_SITE_THEME_SELECTOR_PREFIX} .hljs-keyword" in stored  # הקלט: כמו שהערכה נשמרת
    assert ".highlight " in stored and ".tok-" in stored  # ולצידו Pygments ו-CodeMirror

    rebased = rebase_hljs_css(stored, EXPORT_HLJS_SELECTOR_PREFIX)
    lines = rebased.splitlines()

    assert lines and all(line.startswith(f"{EXPORT_HLJS_SELECTOR_PREFIX} .hljs-") for line in lines), rebased
    assert "code.hljs .hljs-keyword { color: #ff0000 !important; }" in lines
    assert "code.hljs .hljs-comment { color: #00ff00 !important; font-style: italic !important; }" in lines
    # הכלל הבסיסי ``.hljs`` (צבע ורקע של העורך לכל הבלוק) אינו כלל של טוקן — הייצוא שומר על צבעי הקוד של התבנית
    assert ".hljs {" not in rebased and "#101010" not in rebased


@pytest.mark.parametrize(
    "line",
    [
        ':root[data-theme-type="custom"] .hljs-keyword { color: #f00; background: url(https://evil.example/x) }',
        ':root[data-theme-type="custom"] .hljs-keyword { color: #f00 } body { display: none }',
        ':root[data-theme-type="custom"] .hljs-keyword { position: fixed; color: #f00; }',
        ':root[data-theme-type="custom"] .hljs-keyword, body { color: #f00; }',
        'body .hljs-keyword { color: #f00; }',
        ':root[data-theme-type="custom"] .hljs-keyword { color: expression(alert(1)); }',
        # הכלל הבסיסי, גם כשיש בו רק צבע (ערכה בלי ``editor.background``): הוא היה צובע את כל הבלוק
        ':root[data-theme-type="custom"] .hljs { color: #eeeeee !important; }',
    ],
)
def test_rebase_drops_anything_that_is_not_a_plain_token_color(line):
    """הטקסט מגיע מהמסד, ולכן כל שורה שאינה צבע של טוקן נשמטת — לא מנוקה חלקית."""
    assert rebase_hljs_css(line, EXPORT_HLJS_SELECTOR_PREFIX) == ""


def test_the_codemirror_sanitizer_still_keeps_only_codemirror_rules():
    """``sanitize_codemirror_css`` ו-``rebase_hljs_css`` חולקים את הניקוי; כל אחד מקבל רק את הבוררים שלו."""
    from services.theme_parser_service import sanitize_codemirror_css

    stored = parse_vscode_theme(VSCODE_THEME)["syntax_css"]
    cleaned = sanitize_codemirror_css(stored)
    assert cleaned and all(line.startswith(':root[data-theme-type="custom"] .tok-') for line in cleaned.splitlines())


# ---------------------------------------------------------------------------
# get_export_theme — מאיפה מגיעים צבעי highlight.js
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("theme_id", ["morass", "pen-paper-coffee", "everforest-dark"])
def test_a_preset_with_its_own_hljs_stays_as_it_is(theme_id):
    theme = get_export_theme(theme_id)
    assert theme["hljs_css"] and theme["hljs_fallback"] is False


@pytest.mark.parametrize("theme_id", ["tech-guide-dark", "clean-light", "minimal", "githits-docs", "dracula", "nord"])
def test_a_theme_without_hljs_gets_the_palette(theme_id):
    theme = get_export_theme(theme_id)
    assert not theme.get("hljs_css") and theme["hljs_fallback"] is True


def test_an_imported_user_theme_brings_its_hljs_rules():
    theme = get_export_theme("u1", user_themes=[_user_theme()])
    assert "code.hljs .hljs-keyword { color: #ff0000 !important; }" in theme["hljs_css"]
    assert HLJS_SITE_THEME_SELECTOR_PREFIX not in theme["hljs_css"]
    assert theme["hljs_fallback"] is True  # הפלטה מתחת, כמו בתצוגה — לטוקנים שאין להם כלל


def test_a_user_theme_without_hljs_rules_gets_only_the_palette():
    """ערכה מבונה הערכות, או ערכה שיובאה לפני שנשמרו כללי highlight.js."""
    theme = get_export_theme("u2", user_themes=[{"id": "u2", "name": "Built", "variables": {}, "syntax_css": ""}])
    assert theme["hljs_css"] == "" and theme["hljs_fallback"] is True


def test_a_one_off_vscode_theme_brings_its_hljs_rules():
    theme = get_export_theme("vscode-import", vscode_json=json.dumps(VSCODE_THEME))
    assert "code.hljs .hljs-keyword { color: #ff0000 !important; }" in theme["hljs_css"]
    assert theme["hljs_fallback"] is True


# ---------------------------------------------------------------------------
# export_hljs_fallback_css — הפלטה, מקור אחד עם התצוגה
# ---------------------------------------------------------------------------


def test_the_palette_is_read_from_the_preview_colors():
    from webapp.markdown_editor import EXPORT_HLJS_FALLBACK_ROOT, export_hljs_fallback_css

    css = export_hljs_fallback_css()
    site = (REPO / "webapp" / "static" / "css" / "md-content-colors.css").read_text(encoding="utf-8")

    assert "#md-content" not in css
    assert css.startswith(EXPORT_HLJS_FALLBACK_ROOT + " {")
    # אותן הצהרות כמו בבלוק של ערכה מותאמת בתצוגה — אותו טקסט, לא עותק שנכתב ביד
    for decl in ("--hljs-keyword: var(--primary, #c678dd);", "--hljs-string: var(--success, #98c379);",
                 "--hljs-comment: var(--text-muted, #5c6370);"):
        assert decl in css and decl in site
    assert f"{EXPORT_HLJS_FALLBACK_ROOT} .hljs-keyword," in css


def test_the_palette_fails_loudly_when_the_markers_are_gone(tmp_path, monkeypatch):
    import webapp.markdown_editor as me

    broken = tmp_path / "md-content-colors.css"
    broken.write_text("#md-content .hljs-keyword { color: red; }\n", encoding="utf-8")
    monkeypatch.setattr(me, "MD_CONTENT_COLORS_CSS", broken)
    me.export_hljs_fallback_css.cache_clear()
    try:
        with pytest.raises(ValueError):
            me.export_hljs_fallback_css()
    finally:
        # המטמון משותף לכל הטסטים בתהליך: מנקים אותו כדי שהבא יקרא את הקובץ האמיתי (TESTING-PATTERNS T3)
        me.export_hljs_fallback_css.cache_clear()


# ---------------------------------------------------------------------------
# השלד של המחוברים
# ---------------------------------------------------------------------------


def test_the_logged_in_skeleton_has_the_banner_and_the_browser_markup(app_ctx):
    from webapp.markdown_editor import export_hljs_fallback_css

    html = render_styled_export_skeleton(get_export_theme("tech-guide-dark"), "המדריך שלי",
                                         hljs_fallback_css=export_hljs_fallback_css())

    assert html.count(EDITOR_EXPORT_CONTENT_MARKER) == 1
    assert "<header>" in html and "<h1>המדריך שלי</h1>" in html and "<title>המדריך שלי</title>" in html
    # בבאנר ובתחתית, כמו בייצוא שבשרת. התבנית מבריחה את המירכאות של ע"י, ולכן משווים לגרסה המוברחת
    assert html.count(str(escape(STYLED_EXPORT_FOOTER))) == 2
    assert f'<meta http-equiv="Content-Security-Policy" content="{escape(editor_export_meta_csp())}">' in html
    assert ".admonition" in html and "main.container .hljs-keyword" in html
    assert ".highlight ." not in html  # בלי Pygments: הקוד מסומן ב-highlight.js


def test_the_palette_goes_only_to_a_theme_that_needs_it(app_ctx):
    from webapp.markdown_editor import export_hljs_fallback_css

    palette = export_hljs_fallback_css()
    with_own = render_styled_export_skeleton(get_export_theme("morass"), "t", hljs_fallback_css=palette)
    assert "main.container .hljs-keyword" not in with_own and "code.hljs .hljs-" in with_own

    imported = render_styled_export_skeleton(get_export_theme("u1", user_themes=[_user_theme()]), "t",
                                             hljs_fallback_css=palette)
    # הפלטה קודם, והכללים של הערכה אחריה (עם ``!important``) — כמו בתצוגה
    assert imported.index("main.container .hljs-keyword") < imported.index("code.hljs .hljs-keyword")


def test_the_editor_skeleton_still_has_no_banner(app_ctx):
    html = render_editor_export_skeleton(get_export_theme("morass"))
    assert "<header>" not in html and str(escape(STYLED_EXPORT_FOOTER)) not in html
