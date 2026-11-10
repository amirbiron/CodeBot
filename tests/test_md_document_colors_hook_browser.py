"""ווי הדריסה של צבעי המסמך, נמדדים בדפדפן: תצוגת המסמך (``md_preview.html``) והתצוגה החיה בעמוד העריכה.

ערכה שמצהירה בבלוק ``variables`` על ``--md-heading-color-override`` ושכניו מקבלת את הצבעים בשתי התצוגות — גם
כשהיא פורסמה לציבורית, דרך מסלול הפרסום האמיתי. ערכה שאינה מצהירה נשארת כמו היום: הכותרת ב-``--text-primary``,
ההדגשה בצבע שהיא יורשת, הקוד בשורה ב-``--code-text`` והציטוט ב-``--md-blockquote-border``. וכותרת בממשק, מחוץ
למסמך, לא זזה גם כשהטוקנים מוצהרים.

העמודים נבנים מהתבניות כמו ב-``tests/test_live_preview_blockquote_browser.py``, ואת החוזה הטקסטואלי (רשימה לבנה,
בלי ברירת מחדל, fallback של היום) בודק ``tests/services/test_theme_variables_md_document_colors_hook.py``.

מדולג כשאין Chromium.
"""

from __future__ import annotations

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from test_live_preview_blockquote_browser import (  # noqa: E402
    CUSTOM_VSCODE_THEME,
    EDIT_TEMPLATE,
    TEMPLATES_DIR,
    _measure_pages,
    build_head,
    build_page,
    custom_theme,
    html_theme_attributes,
    shared_theme,
)

MD_PREVIEW_TEMPLATE = TEMPLATES_DIR / "md_preview.html"

#: פלטה א' של morass — הצבעים שנבחרו לערכה. כל אחד שונה מכל צבע שהערכה נותנת בלי הטוקנים.
DECLARED = {
    "--md-heading-color-override": "#e1c636",
    "--md-subheading-color-override": "#cfd394",
    "--md-strong-color-override": "#dcdcaa",
    "--md-inline-code-color-override": "#b5cea8",
    "--md-blockquote-border-override": "#e1c636",
}

WITH_TOKENS = {**CUSTOM_VSCODE_THEME, "variables": DECLARED}

MARKDOWN = "# א\n\n## ב\n\n### ג\n\n#### ד\n\nפסקה **מודגש** ו-`קוד`\n\n- פריט **מודגש**\n\n> ציטוט **מודגש**\n"
DOCUMENT_HTML = (
    "<h1>א</h1><h2>ב</h2><h3>ג</h3><h4>ד</h4><p>פסקה <strong>מודגש</strong> ו-<code>קוד</code></p>"
    "<ul><li>פריט <strong>מודגש</strong></li></ul><blockquote><p>ציטוט <strong>מודגש</strong></p></blockquote>"
)

#: אותה מדידה בשתי התצוגות. ``probe`` צובע אלמנט זמני בתוך המסמך בביטוי נתון, כדי לקרוא את הערך שהטוקנים של היום
#: נותנים באותו מקום; ``uiHeading`` הוא כותרת שמחוץ למסמך.
MEASURE_JS = """() => {
    const root = document.getElementById('md-content');
    if (!root || !root.querySelector('blockquote')) {
        return { rendered: false };
    }
    const color = (s) => getComputedStyle(root.querySelector(s)).color;
    const probe = (expr) => {
        const el = document.createElement('span');
        el.style.color = expr;
        root.appendChild(el);
        const value = getComputedStyle(el).color;
        el.remove();
        return value;
    };
    const ui = document.createElement('h2');
    document.body.appendChild(ui);
    const uiHeading = getComputedStyle(ui).color;
    ui.remove();
    return {
        rendered: true,
        h1: color('h1'), h2: color('h2'), h3: color('h3'), h4: color('h4'),
        p: color('p'), pStrong: color('p strong'), li: color('li'), liStrong: color('li strong'),
        quoteText: color('blockquote p'), quoteStrong: color('blockquote strong'),
        code: color('p code'),
        quoteBorder: getComputedStyle(root.querySelector('blockquote')).borderInlineStartColor,
        textPrimary: probe('var(--text-primary)'),
        codeText: probe('var(--code-text, var(--text-primary))'),
        quoteToken: probe('var(--md-blockquote-border)'),
        uiHeading: uiHeading,
    };
}"""

#: ``(data-theme, ערכה עם הטוקנים או בלעדיהם)`` — אישית ושפורסמה לציבורית.
CASES = {
    "custom-declared": ("custom", WITH_TOKENS),
    "shared-declared": ("shared", WITH_TOKENS),
    "custom-plain": ("custom", CUSTOM_VSCODE_THEME),
    "shared-plain": ("shared", CUSTOM_VSCODE_THEME),
}


def _rgb(hex_color: str) -> str:
    value = hex_color.lstrip("#")
    return "rgb({}, {}, {})".format(*(int(value[i : i + 2], 16) for i in (0, 2, 4)))


def _theme(attr: str, vscode: dict) -> dict:
    return shared_theme(vscode) if attr == "shared" else custom_theme(vscode)


def _document_page(attr: str, theme: dict) -> str:
    head = (
        build_head(shared=theme, template=MD_PREVIEW_TEMPLATE)
        if attr == "shared"
        else build_head(theme, MD_PREVIEW_TEMPLATE)
    )
    return (
        f'<!doctype html><html dir="rtl" lang="he" {html_theme_attributes(attr)}>'
        f'<head><meta charset="utf-8">{head}</head>'
        f'<body><div id="md-root"><div id="md-content">{DOCUMENT_HTML}</div></div></body></html>'
    )


@pytest.fixture(scope="module")
def measured(chromium_executable):
    themes = {name: (attr, _theme(attr, vscode)) for name, (attr, vscode) in CASES.items()}
    documents = _measure_pages(
        chromium_executable,
        {f"doc-{name}": _document_page(attr, theme) for name, (attr, theme) in themes.items()},
        None,
        MEASURE_JS,
    )
    live = _measure_pages(
        chromium_executable,
        {
            f"live-{name}": build_page(attr, theme, EDIT_TEMPLATE)
            for name, (attr, theme) in themes.items()
        },
        MARKDOWN,
        MEASURE_JS,
    )
    return {**documents, **live}


def _case(measured, view: str, name: str) -> dict:
    m = measured[f"{view}-{name}"]
    assert m.get("rendered"), f"{view}-{name}: המסמך לא רונדר"
    return m


@pytest.mark.parametrize("view", ["doc", "live"])
@pytest.mark.parametrize("name", ["custom-declared", "shared-declared"])
def test_declared_tokens_paint_the_document(measured, view, name):
    m = _case(measured, view, name)
    heading = _rgb(DECLARED["--md-heading-color-override"])
    subheading = _rgb(DECLARED["--md-subheading-color-override"])
    strong = _rgb(DECLARED["--md-strong-color-override"])
    assert (m["h1"], m["h2"]) == (heading, heading), m
    assert (m["h3"], m["h4"]) == (subheading, subheading), m
    assert (m["pStrong"], m["liStrong"], m["quoteStrong"]) == (strong, strong, strong), m
    assert m["code"] == _rgb(DECLARED["--md-inline-code-color-override"]), m
    assert m["quoteBorder"] == _rgb(DECLARED["--md-blockquote-border-override"]), m


@pytest.mark.parametrize("view", ["doc", "live"])
@pytest.mark.parametrize("name", ["custom-plain", "shared-plain"])
def test_undeclared_tokens_leave_the_document_as_it_was(measured, view, name):
    m = _case(measured, view, name)
    assert m["h1"] == m["h2"] == m["h3"] == m["h4"] == m["textPrimary"], m
    assert (
        m["pStrong"] == m["p"] and m["liStrong"] == m["li"] and m["quoteStrong"] == m["quoteText"]
    ), m
    assert m["code"] == m["codeText"], m
    assert m["quoteBorder"] == m["quoteToken"], m


@pytest.mark.parametrize("view", ["doc", "live"])
def test_interface_headings_stay_out_of_it(measured, view):
    """הטוקנים צובעים כותרות רק בתוך ``#md-content``. כותרת בממשק נשארת בכלל ה-Typography של ``dark-mode.css``."""
    m = _case(measured, view, "shared-declared")
    assert m["uiHeading"] == m["textPrimary"], m
    assert m["uiHeading"] != _rgb(DECLARED["--md-heading-color-override"]), m
