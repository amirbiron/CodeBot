"""צבעי התחביר בדפדפן אמיתי, מול VS Code — בייצוא ל-HTML מעוצב ובתצוגה החיה, בשלוש ערכות הייצוא.

**למה בדפדפן.** הטסט של המחוללים (``tests/test_vscode_token_theme.py``) מחקה את ה-CSS: ספציפיות, ``!important``,
ירושה מההורה, והסיומת ``:is(.language-python *)`` של כלל לפי שפה. רק דפדפן אוכף אותם באמת, ורק בדפדפן נמצאים יחד
ה-CSS האחר של העמוד, highlight.js של הבאנדל, והמחלקה ``language-<שם>`` שהוא מוסיף לבלוק.

**מה נבדק, לכל ערכה ושפה** (בלוק פייתון ובלוק JavaScript — הדוגמאות של ``scripts/syntax_colors/samples``):

- הטקסט בבלוק הוא הדוגמה, והבלוק נושא את ``language-<שם>`` הקנוני.
- הצבע שהדפדפן נותן לכל תו שווה לחיקוי של הטסט האחר — כך החיקוי שם בודק את מה שבאמת מוצג.
- כל תו שיוצא בצבע אחר מ-VS Code (``tests/fixtures/syntax_colors_vscode_reference.json``) הוא איחוד מוצהר
  (``MERGES`` ב-``tests/_syntax_colors_reference.py``).

**איך.** הייצוא: מהעורך הציבורי, כמו ב-``tests/test_markdown_editor_export_browser.py`` (``Session``), והקובץ שירד נפתח
לבד (``open_file``). התצוגה החיה: עמוד העריכה עם ערכה מיובאת, כמו ב-``tests/test_live_preview_blockquote_browser.py``
(``build_page``, ``_measure_pages``, ``custom_theme``) — הערכה נבנית מה-``tokenColors`` של ערכת הייצוא, עם צבע הטקסט שלה
כ-``editor.foreground``. "ברירת המחדל" בשני הצדדים היא צבע הטקסט של הבלוק.

מדולג כשאין Chromium (``chromium_executable`` ב-``tests/conftest.py``).
"""

from __future__ import annotations

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

from _styled_export_harness import open_file  # noqa: E402
from _syntax_colors_reference import (  # noqa: E402
    SAMPLE_LANGUAGE_CLASS,
    color_for_path,
    declared_merge,
    load_reference,
    parse_rules,
    style_for,
)
from test_live_preview_blockquote_browser import _measure_pages, build_page, custom_theme  # noqa: E402
from test_markdown_editor_export_browser import FAKE_THEME, Session  # noqa: E402

from scripts.syntax_colors import generate_reference  # noqa: E402
from services import styled_export_service as export  # noqa: E402

REFERENCE = load_reference()
THEMES = generate_reference.reference_themes()
LANGUAGES = ("python", "javascript")
SAMPLES = {
    lang: (generate_reference.HERE / "samples" / name).read_text(encoding="utf-8")
    for lang, name in generate_reference.SAMPLE_FILES.items()
}
MARKDOWN = "".join(f"```{lang}\n{SAMPLES[lang]}```\n\n" for lang in LANGUAGES)
SITE_PREFIX = ':root[data-theme-type="custom"]'

#: לכל בלוק קוד: המחלקות שלו, צבע הטקסט שלו, ולכל תו שאינו רווח — התו, הצבע שהדפדפן נותן, והמחלקות של האלמנטים
#: שעוטפים אותו (מבחוץ פנימה, בלי הבלוק עצמו).
MEASURE_JS = """(rootSelector) => {
  const root = rootSelector ? document.querySelector(rootSelector) : document;
  const hex = (rgb) => '#' + rgb.match(/\\d+/g).slice(0, 3).map((x) => Number(x).toString(16).padStart(2, '0')).join('');
  return Array.from(root.querySelectorAll('pre code')).map((code) => {
    const chars = [];
    const walker = document.createTreeWalker(code, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const el = node.parentElement;
      const color = hex(getComputedStyle(el).color);
      const path = [];
      for (let e = el; e && e !== code; e = e.parentElement) path.unshift(Array.from(e.classList));
      for (const ch of node.textContent) if (!/\\s/.test(ch)) chars.push([ch, color, path]);
    }
    return { classes: Array.from(code.classList), base: hex(getComputedStyle(code).color), chars };
  });
}"""


def _expected_chars(language: str, theme_id: str) -> list[tuple[str, list[str], str | None]]:
    """לכל תו שאינו רווח בדוגמה: התו, שרשרת ה-scopes של VS Code והצבע ש-VS Code נותן."""
    styles = REFERENCE["themes"][theme_id]
    out = []
    for seg in REFERENCE["languages"][language]:
        fg = style_for(styles, seg["scopes"])["fg"]
        out.extend((ch, seg["scopes"], fg) for ch in seg["text"] if not ch.isspace())
    return out


def _check_block(block: dict, language: str, theme_id: str, rules, *, code_text: str) -> list[tuple]:
    """בודק בלוק אחד ומחזיר את התווים שיוצאים בצבע אחר מ-VS Code (כדי לדווח עליהם)."""
    lang_class = SAMPLE_LANGUAGE_CLASS[language]
    assert f"language-{lang_class}" in block["classes"], block["classes"]
    expected = _expected_chars(language, theme_id)
    assert "".join(c[0] for c in block["chars"]) == "".join(e[0] for e in expected)

    default = code_text.lower()

    def norm(color):
        return None if color is None or color.lower() in (default, block["base"]) else color.lower()

    emulation_differs = []
    differs_from_vscode = []
    for (ch, browser_color, path), (_, scopes, vscode_color) in zip(block["chars"], expected):
        hljs_path = [[c for c in classes] for classes in path]
        ours = norm(browser_color)
        if ours != norm(color_for_path(hljs_path, rules, lang_class)):
            emulation_differs.append((ch, path, browser_color))
        if ours != norm(vscode_color):
            css_class = "." + ".".join(hljs_path[-1]) if hljs_path else "(none)"
            differs_from_vscode.append((css_class, scopes[-1], ch, ours, vscode_color))
    assert emulation_differs == []
    undeclared = [d for d in differs_from_vscode if declared_merge("hljs", language, d[0], d[1]) is None]
    assert undeclared == []
    return differs_from_vscode


# ---------------------------------------------------------------------------
# התצוגה החיה בעמוד העריכה, עם ערכה מיובאת
#
# ראשונה בקובץ, בכוונה: ``_measure_pages`` מרים Playwright משלו וסוגר אותו, ו-pytest מריץ לפי הסדר בקובץ. אחרי
# הייצוא, ה-``browser`` של המודול עוד פתוח, ו-Playwright סינכרוני שני בתוכו נכשל.
# ---------------------------------------------------------------------------


def _imported(theme_id: str) -> tuple[dict, dict]:
    preset = export.EXPORT_PRESETS[theme_id]
    vscode = {
        "name": preset["name"],
        "type": preset["category"],
        "colors": {
            "editor.foreground": preset["variables"]["--code-text"],
            "editor.background": preset["variables"]["--code-bg"],
        },
        "tokenColors": THEMES[theme_id],
    }
    return vscode, custom_theme(vscode)


@pytest.fixture(scope="module")
def live_preview(chromium_executable):
    pages = {theme_id: build_page("custom", _imported(theme_id)[1]) for theme_id in THEMES}
    return _measure_pages(chromium_executable, pages, MARKDOWN, f"() => ({MEASURE_JS})('[data-preview-canvas]')")


@pytest.mark.parametrize("theme_id", sorted(THEMES))
def test_the_live_preview_colors_code_like_vscode_up_to_the_declared_merges(live_preview, theme_id):
    blocks = live_preview[theme_id]
    assert len(blocks) == len(LANGUAGES)
    vscode, theme = _imported(theme_id)
    rules = parse_rules(theme["syntax_css"], SITE_PREFIX)
    for block, language in zip(blocks, LANGUAGES):
        _check_block(block, language, theme_id, rules, code_text=vscode["colors"]["editor.foreground"])


# ---------------------------------------------------------------------------
# הייצוא מהעורך הציבורי
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def browser(chromium_executable):
    import webapp.app as wa

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            wa,
            "_get_shared_theme_cached",
            lambda theme_id: dict(FAKE_THEME) if theme_id == "everforest_dark" else None,
        )
        with sync_playwright() as pw:
            try:
                b = (
                    pw.chromium.launch(executable_path=chromium_executable)
                    if chromium_executable
                    else pw.chromium.launch()
                )
            except Exception as exc:  # כשל חולף בהרמה, אחרי שהשער כבר אמר שיש דפדפן
                pytest.skip(f"Chromium לא עלה: {exc}")
            try:
                yield b, wa.app
            finally:
                b.close()


@pytest.mark.parametrize("theme_id", sorted(THEMES))
def test_the_exported_file_colors_code_like_vscode_up_to_the_declared_merges(browser, tmp_path, theme_id):
    session = Session(browser, draft=MARKDOWN)
    try:
        _, path = session.download(theme_id, tmp_path)
    finally:
        session.close()
    ctx, page, attempts, _dialogs = open_file(browser, path)
    try:
        blocks = page.evaluate(MEASURE_JS, None)
    finally:
        ctx.close()
    assert attempts == []
    assert len(blocks) == len(LANGUAGES)
    rules = parse_rules(export.EXPORT_PRESETS[theme_id]["hljs_css"], export.EXPORT_HLJS_SELECTOR_PREFIX)
    code_text = export.EXPORT_PRESETS[theme_id]["variables"]["--code-text"]
    for block, language in zip(blocks, LANGUAGES):
        _check_block(block, language, theme_id, rules, code_text=code_text)
