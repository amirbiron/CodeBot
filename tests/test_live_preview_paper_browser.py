"""התצוגה החיה של Markdown מציגה את הצבעים של תצוגת המסמך — בכל ערכה.

**הבאג שהקובץ הזה נולד ממנו.** התצוגה החיה בעמודי העריכה וההעלאה הוצגה על רקע כהה קבוע בכל ערכה —
גם בערכות הבהירות, ובערכה מיובאת ב-``#1e1e1e`` במקום הרקע של הערכה. שתי סיבות:

- ``live-preview.js`` הציב על המכל ``data-theme="dark"``, וזה הכניס לתצוגה את כללי הטקסט של
  הערכות הכהות ב-``dark-mode.css`` (כותרות, פסקאות, קישורים) עם צבעי הטקסט של העמוד — ב-Classic
  וב-Ocean לבן. על רקע לבן הטקסט נעלם, ולכן הרקע הוחזק כהה.
- הצבעים של המסמך — הנייר, צבעי התחביר, קוד בשורה, ציטוט, טבלה — ישבו בתוך ה-``<style>`` של
  ``md_preview.html``, ועמודי העריכה לא טענו אותם. מה שהתצוגה החיה הציגה במקומם תוכנן לרקע כהה בלבד.

היום הצבעים של המסמך יושבים ב-``md-content-colors.css``, ששני העמודים טוענים, והמכל של התצוגה החיה
במצב Markdown צובע את עצמו בנייר של המסמך (``.split-preview-content[data-mode="markdown"]`` ב-
``split-view.css``).

**מה נבדק.** לכל ערכה: הנייר — הרקע והטקסט של אזור התצוגה כולו שווים לאלה של ``#md-content``
בתצוגת המסמך; הדיו — הצבעים של האלמנטים ש-markdown-it מייצר שווים בין שתי התצוגות; שאין תווית
``data-theme`` על המכל; ושמה שקיים רק בתצוגה החיה — שורת המידע וכפתור ההעתקה — קריא.

**איך נבנית תצוגת המסמך (T1).** מאותו מפל שהשרת מרכיב: ה-``<head>`` של ``base.html``, ובמקום
``extra_css`` הבלוק של ``md_preview.html`` (``build_head`` של ``test_live_preview_blockquote_browser``).
התוכן של ``#md-content`` הוא ה-HTML שהתצוגה החיה רינדרה באותה ערכה, כך ששתי התצוגות נמדדות על אותו
DOM. מה שתצוגת המסמך בונה בנוסף ב-JS שלה — פס הכותרת של בלוק קוד עם שם השפה וכפתור משלו — אינו כאן,
וגם לא בתצוגה החיה.

**לא נבדק כאן:** פריסה — גדלים, ריווח, הקו התחתון של כותרות — ובורר הרקע של תצוגת המסמך
(``bg-sepia`` ודומיו), שקיים רק שם.

מדולג כשאין Chromium.
"""

from __future__ import annotations

import re

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from test_live_preview_blockquote_browser import (  # noqa: E402
    CUSTOM_VSCODE_THEME,
    TEMPLATES_DIR,
    _measure_pages,
    build_head,
    build_page,
    custom_theme,
)

MD_PREVIEW_TEMPLATE = TEMPLATES_DIR / "md_preview.html"

#: ערכה מיובאת **בהירה**, בצבעים של Pen Paper Coffee: בה התצוגה החיה לא הייתה קריאה בכלל — טקסט
#: כהה על ה-``--split-preview-bg`` הכהה ש-``FALLBACK_LIGHT`` נותן לכל ערכה מיובאת.
LIGHT_VSCODE_THEME = {
    "name": "Live preview paper — light",
    "type": "light",
    "colors": {
        "editor.background": "#f8f6f1",
        "editor.foreground": "#2b3f6a",
        "textLink.foreground": "#5e78e1",
        "textLink.activeForeground": "#6e4e44",
    },
    "tokenColors": [
        {"scope": ["keyword"], "settings": {"foreground": "#8f5e15"}},
        {"scope": ["string"], "settings": {"foreground": "#3f7d3a"}},
        {"scope": ["comment"], "settings": {"foreground": "#7a7f8a"}},
    ],
}

#: הערכות שנמדדות: כל המובנות, ערכה מיובאת כהה וערכה מיובאת בהירה. ``(data-theme, ערכה מיובאת)``.
THEMES = {
    "classic": ("classic", None),
    "ocean": ("ocean", None),
    "rose-pine-dawn": ("rose-pine-dawn", None),
    "dark": ("dark", None),
    "dim": ("dim", None),
    "nebula": ("nebula", None),
    "high-contrast": ("high-contrast", None),
    "custom-dark": ("custom", CUSTOM_VSCODE_THEME),
    "custom-light": ("custom", LIGHT_VSCODE_THEME),
}

MARKDOWN = (
    "# כותרת ראשית\n\n"
    "## כותרת עם [קישור](https://example.com/h2)\n\n"
    "פסקה עם **הדגשה**, [קישור](https://example.com/a), `קוד בשורה` ו-==סימון==.\n\n"
    "> ציטוט עם שורה.\n\n"
    "- פריט ראשון\n- פריט שני\n\n"
    "| עמודה | ב |\n|---|---|\n| 1 | 2 |\n\n"
    "```python\ndef f(x):\n    s = 'מחרוזת'  # הערה\n    return x\n```\n"
)

#: האלמנטים שמושווים, יחסית לשורש — ה-canvas בתצוגה החיה, ``#md-content`` בתצוגת המסמך.
INK_SELECTORS = [
    "h1",
    "h2",
    ":scope > p",
    "p strong",
    "p > a",
    "a.header-anchor",
    "p > code",
    "mark",
    "blockquote",
    "blockquote p",
    "li",
    "thead",
    "th",
    "td",
    "pre",
    "pre code",
    ".hljs-keyword",
    ".hljs-string",
    ".hljs-comment",
]
INK_PROPS = [
    "color",
    "background-color",
    "border-top-color",
    "border-inline-start-color",
    "text-decoration-color",
]

_STYLES_JS = """(root) => {
  const out = {};
  for (const sel of %s) {
    const el = sel === ':scope' ? root : root.querySelector(sel);
    if (!el) { out[sel] = null; continue; }
    const s = getComputedStyle(el);
    out[sel] = Object.fromEntries(%s.map((p) => [p, s.getPropertyValue(p)]));
  }
  return out;
}""" % (
    repr([":scope", *INK_SELECTORS]).replace("'", '"'),
    repr(INK_PROPS).replace("'", '"'),
)

LIVE_JS = (
    """() => {
  const styles = %s;
  const box = document.querySelector('[data-preview-content]');
  const canvas = document.querySelector('[data-preview-canvas]');
  const s = getComputedStyle(box);
  const btn = canvas.querySelector('.code-copy-btn');
  return {
    stamp: box.getAttribute('data-theme'),
    mode: box.dataset.mode || null,
    boxBg: s.backgroundColor,
    boxColor: s.color,
    metaColor: getComputedStyle(document.querySelector('[data-preview-meta]')).color,
    copyColor: btn ? getComputedStyle(btn).color : null,
    copyBg: btn ? getComputedStyle(btn).backgroundColor : null,
    html: canvas.innerHTML,
    ink: styles(canvas),
  };
}"""
    % _STYLES_JS
)

DOC_JS = """() => (%s)(document.getElementById('md-content'))""" % _STYLES_JS


def _theme(name: str) -> tuple[str, dict | None]:
    attr, vscode = THEMES[name]
    return attr, (custom_theme(vscode) if vscode else None)


def _document_page(name: str, html: str) -> str:
    """תצוגת המסמך באותה ערכה, ו-``html`` בתוך ``#md-content``.

    ``build_head`` עם ``md_preview.html``: ה-``<head>`` של ``base.html``, ו-``extra_css`` של התבנית במקומו.
    """
    attr, theme = _theme(name)
    theme_type = ' data-theme-type="custom"' if attr == "custom" else ""
    return (
        f'<!doctype html><html dir="rtl" lang="he" data-theme="{attr}"{theme_type}>'
        f'<head><meta charset="utf-8">{build_head(theme, MD_PREVIEW_TEMPLATE)}</head>'
        f'<body><div id="md-root"><div id="md-content">{html}</div></div></body></html>'
    )


@pytest.fixture(scope="module")
def measured(chromium_executable):
    """לכל ערכה: מה שנמדד בתצוגה החיה, ומה שנמדד בתצוגת המסמך על אותו HTML."""
    live = _measure_pages(
        chromium_executable, {name: build_page(*_theme(name)) for name in THEMES}, MARKDOWN, LIVE_JS
    )
    documents = _measure_pages(
        chromium_executable,
        {name: _document_page(name, live[name]["html"]) for name in THEMES},
        None,
        DOC_JS,
    )
    return {name: {"live": live[name], "doc": documents[name]} for name in THEMES}


_NUMBERS = re.compile(r"[\d.]+")


def _rgba(colour: str) -> tuple[list[float], float]:
    """צבע מחושב (``rgb(...)`` / ``rgba(...)`` / ``color(srgb ...)``) — ערוצים בין 0 ל-1, ושקיפות."""
    unit = 1.0 if colour.startswith("color(") else 255.0
    values = [float(v) for v in _NUMBERS.findall(colour.replace("color(srgb", ""))]
    alpha = values[3] if len(values) > 3 else 1.0
    return [v / unit for v in values[:3]], alpha


def _over(colour: str, below: list[float]) -> list[float]:
    rgb, alpha = _rgba(colour)
    return [c * alpha + b * (1 - alpha) for c, b in zip(rgb, below)]


def _contrast(fg: list[float], bg: list[float]) -> float:
    """יחס הניגודיות לפי WCAG 2."""

    def luminance(rgb):
        lin = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    hi, lo = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("name", list(THEMES))
def test_the_preview_is_on_the_document_paper(measured, name):
    """כל אזור התצוגה — לא רק התוכן — ברקע ובצבע הטקסט של ``#md-content`` בתצוגת המסמך."""
    live, doc = measured[name]["live"], measured[name]["doc"][":scope"]
    assert (
        live["boxBg"] == doc["background-color"]
    ), f"{name}: רקע התצוגה {live['boxBg']} מול המסמך {doc['background-color']}"
    assert (
        live["boxColor"] == doc["color"]
    ), f"{name}: טקסט התצוגה {live['boxColor']} מול המסמך {doc['color']}"
    assert live["ink"][":scope"]["background-color"] == doc["background-color"], live["ink"][
        ":scope"
    ]


@pytest.mark.parametrize("name", ["custom-dark", "custom-light"])
def test_an_imported_theme_shows_its_own_background(measured, name):
    """ערכה מיובאת — ``editor.background`` שלה, ולא ``--split-preview-bg`` שהמייבא נותן לכל ערכה.

    בלי זה, עמוד שבלוק הערכה שלו לא רונדר היה עובר את ההשוואה למסמך על ערכי ברירת המחדל של שניהם.
    """
    expected = THEMES[name][1]["colors"]["editor.background"].lstrip("#")
    rgb = "rgb({}, {}, {})".format(*(int(expected[i : i + 2], 16) for i in (0, 2, 4)))
    assert measured[name]["live"]["boxBg"] == rgb, measured[name]["live"]["boxBg"]


@pytest.mark.parametrize("name", list(THEMES))
def test_the_ink_matches_the_document(measured, name):
    """הצבעים של כל אלמנט שנמדד זהים בין התצוגה החיה לתצוגת המסמך."""
    live, doc = measured[name]["live"]["ink"], measured[name]["doc"]
    missing = [sel for sel in INK_SELECTORS if live.get(sel) is None or doc.get(sel) is None]
    # אלמנט שלא רונדר היה עובר את ההשוואה בלי לבדוק דבר.
    assert not missing, f"{name}: לא נמצאו {missing}"
    offenders = [
        f"{sel} {prop}: חי {live[sel][prop]} מול מסמך {doc[sel][prop]}"
        for sel in INK_SELECTORS
        for prop in INK_PROPS
        if live[sel][prop] != doc[sel][prop]
    ]
    assert not offenders, f"{name}:\n" + "\n".join(offenders)


@pytest.mark.parametrize("name", list(THEMES))
def test_the_preview_does_not_borrow_the_page_theme_label(measured, name):
    """בלי ``data-theme`` על המכל: התווית הכניסה לתצוגה את צבעי הטקסט של העמוד."""
    live = measured[name]["live"]
    assert live["stamp"] is None, f"{name}: data-theme={live['stamp']!r} על המכל"
    assert live["mode"] == "markdown", live["mode"]


@pytest.mark.parametrize("name", list(THEMES))
def test_what_only_the_preview_shows_is_readable(measured, name):
    """שורת המידע (טקסט קטן — 4.5) ואייקון כפתור ההעתקה (רכיב — 3, WCAG 1.4.11) על הנייר."""
    live = measured[name]["live"]
    paper = _over(live["boxBg"], [1.0, 1.0, 1.0])
    meta = _contrast(_over(live["metaColor"], paper), paper)
    assert meta >= 4.5, f"{name}: שורת המידע בניגודיות {meta:.2f}"

    pre = _over(live["ink"]["pre"]["background-color"], paper)
    button = _over(live["copyBg"], pre)
    icon = _contrast(_over(live["copyColor"], button), button)
    assert icon >= 3.0, f"{name}: אייקון ההעתקה בניגודיות {icon:.2f}"
