"""התצוגה החיה של Markdown נראית כמו תצוגת המסמך — בצבעים ובפריסה, בכל ערכה.

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

**והבאג השני: הפריסה.** גם הפריסה של התצוגה החיה הייתה עותק משלה ב-``split-view.css``, והוא נסחף:
קוד בשורה קיבל ``word-break: break-word``, ובטבלה עמודה עם קוד נשברה כל כמה אותיות (בטבלת הכלים —
``codekeeper_list_repos`` בשלוש שורות), בזמן שבתצוגת המסמך אותו קוד נשאר בשורה אחת והטבלה נגללה; ובלוק
קוד נבנה שם עם כפתור קטן בפינה, כמו בדפדפן הריפו. היום הפריסה של המסמך יושבת ב-``md-content-layout.css``,
ובלוק הקוד — מסגרת, פס כותרת עם שם השפה וכפתור העתקה — נבנה ב-``md-code-blocks.js``, בשתי התצוגות.

**מה נבדק.** לכל ערכה: הנייר — הרקע והטקסט של אזור התצוגה כולו שווים לאלה של ``#md-content``
בתצוגת המסמך; הצבעים והפריסה של האלמנטים ש-markdown-it מייצר, ושל בלוק הקוד, שווים בין שתי התצוגות;
קוד בשורה בתוך טבלה נשאר בשורה אחת; שאין תווית ``data-theme`` על המכל; ושמה שקיים רק בתצוגה החיה —
שורת המידע — קריא, וגם כפתור ההעתקה.

**איך נבנית תצוגת המסמך (T1).** מאותו מפל שהשרת מרכיב: ה-``<head>`` של ``base.html``, ובמקום
``extra_css`` הבלוק של ``md_preview.html`` (``build_head`` של ``test_live_preview_blockquote_browser``).
התוכן של ``#md-content`` הוא ה-HTML שהתצוגה החיה רינדרה באותה ערכה, כולל בלוק הקוד שבנה
``md-code-blocks.js``, כך ששתי התצוגות נמדדות על אותו DOM. שתצוגת המסמך עצמה בונה את הבלוק מאותו
מודול — ``tests/sticky-notes-target.test.js`` בודק שהיא טוענת אותו וקוראת לו, ואין לה עותק משלה.

**לא נבדק כאן:** רוחבים וגבהים — חלון התצוגה החיה הוא חצי מסך, ולכן טבלה וטקסט נשברים בו אחרת גם
כשהכללים זהים; אנימציית הכניסה, שקיימת בכוונה רק בתצוגת המסמך; ובורר הרקע של תצוגת המסמך
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
    "---\n\n"
    "- פריט ראשון\n- פריט שני\n\n"
    "| עמודה | ב |\n|---|---|\n| 1 | 2 |\n\n"
    "```python\ndef f(x):\n    s = 'מחרוזת'  # הערה\n    return x\n```\n\n"
    "::: note\nפסקה בתוך אדמוניציה.\n:::\n\n"
    # הטבלאות מהדיווח: קוד בשורה בעמודה צרה, ומחרוזת ארוכה בלי רווחים לידה.
    "| כלי | תיאור |\n|---|---|\n"
    "| `codekeeper_list_repos` | רשימת הריפואים המשוקפים (מטא-דאטה) |\n"
    "| `codekeeper_list_repo_tree` | נתיבי קבצים בריפו, עם עימוד וסינון לפי תיקייה |\n\n"
    "| כלי | ערך ארוך | תיאור |\n|---|---|---|\n"
    "| טוקן לדוגמה | `"
    + "a8f3e9c1b7d24f6a90e5c3b8d1f7a2e4" * 3
    + "` | תיאור רגיל שאמור להתפרס על פני כמה שורות |\n"
)

#: האלמנטים שמושווים, יחסית לשורש — ה-canvas בתצוגה החיה, ``#md-content`` בתצוגת המסמך.
SELECTORS = [
    "h1",
    "h2",
    ":scope > p",
    "p strong",
    "p > a",
    # בלי ``a.header-anchor``: מאוקטובר 2026 התצוגה החיה לא מרנדרת ``¶`` ליד כותרת (``livePreview`` ב-
    # ``RENDERER_VARIANTS``), ולכן אין לה מה להשוות. קו ההפרדה (``hr``) כן, באותו צבע ובאותו מרווח.
    "hr",
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
    ".code-block",
    ".md-code-header",
    ".md-code-lang",
    ".md-copy-btn",
    "td > code",
    ".admonition-content > p",
]
#: צבע, ואחריו פריסה. רוחבים וגבהים — לא: ראו ה-docstring.
PROPS = [
    "color",
    "background-color",
    "border-top-color",
    "border-inline-start-color",
    "text-decoration-color",
    "font-size",
    "font-family",
    "font-weight",
    "line-height",
    "display",
    "direction",
    "text-align",
    "white-space",
    "word-break",
    "overflow-wrap",
    "margin-top",
    "margin-bottom",
    "padding-top",
    "padding-inline-start",
    "border-top-width",
    "border-inline-start-width",
    "border-top-left-radius",
    "list-style-position",
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
    repr([":scope", *SELECTORS]).replace("'", '"'),
    repr(PROPS).replace("'", '"'),
)

LIVE_JS = (
    """() => {
  const styles = %s;
  const box = document.querySelector('[data-preview-content]');
  const canvas = document.querySelector('[data-preview-canvas]');
  const s = getComputedStyle(box);
  const btn = canvas.querySelector('.md-copy-btn');
  const header = btn ? btn.closest('.md-code-header') : null;
  // קוד בשורה בתוך טבלה: כמה שורות הוא תופס — הגובה שלו מול הגובה של עותק עם תו אחד, באותו מקום
  // ובאותם כללים. לא ``getClientRects``: לאלמנט ``inline-block`` (כך היה הקוד בתצוגה החיה) יש מלבן
  // אחד גם כשהטקסט בתוכו נשבר לכמה שורות.
  const cellCode = [...canvas.querySelectorAll('td > code')].map((c) => {
    const one = c.cloneNode(false);
    one.textContent = 'x';
    c.after(one);
    const lineHeight = one.getBoundingClientRect().height;
    one.remove();
    return { text: c.textContent, lines: Math.round(c.getBoundingClientRect().height / lineHeight) };
  });
  return {
    stamp: box.getAttribute('data-theme'),
    mode: box.dataset.mode || null,
    boxBg: s.backgroundColor,
    boxColor: s.color,
    metaColor: getComputedStyle(document.querySelector('[data-preview-meta]')).color,
    copyColor: btn ? getComputedStyle(btn).color : null,
    copyBg: btn ? getComputedStyle(btn).backgroundColor : null,
    headerBg: header ? getComputedStyle(header).backgroundColor : null,
    shellBg: header ? getComputedStyle(header.parentElement).backgroundColor : null,
    cellCode: cellCode,
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
def test_colors_and_layout_match_the_document(measured, name):
    """הצבעים והפריסה של כל אלמנט שנמדד — כולל בלוק הקוד ופס הכותרת שלו — זהים בין התצוגה החיה לתצוגת
    המסמך."""
    live, doc = measured[name]["live"]["ink"], measured[name]["doc"]
    missing = [sel for sel in SELECTORS if live.get(sel) is None or doc.get(sel) is None]
    # אלמנט שלא רונדר היה עובר את ההשוואה בלי לבדוק דבר.
    assert not missing, f"{name}: לא נמצאו {missing}"
    offenders = [
        f"{sel} {prop}: חי {live[sel][prop]} מול מסמך {doc[sel][prop]}"
        for sel in SELECTORS
        for prop in PROPS
        if live[sel][prop] != doc[sel][prop]
    ]
    assert not offenders, f"{name}:\n" + "\n".join(offenders)


@pytest.mark.parametrize("name", list(THEMES))
def test_inline_code_in_a_table_stays_on_one_line(measured, name):
    """קוד בשורה בתוך תא נשאר שלם, כמו בתצוגת המסמך: העמודה מתרחבת, והטבלה נגללת לצד.

    עד שהפריסה של המסמך הפכה למשותפת, קוד בשורה בתצוגה החיה נשבר כל כמה אותיות
    (``word-break: break-word`` ב-``split-view.css``).
    """
    cells = measured[name]["live"]["cellCode"]
    assert len(cells) >= 3, f"{name}: לא נמצא קוד בתאי הטבלאות ({cells})"
    broken = [c for c in cells if c["lines"] != 1]
    assert not broken, f"{name}: קוד שנשבר בתוך תא: {broken}"


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

    # הכפתור בפס הכותרת: הרקע שלו מעל הפס, והפס מעל המסגרת של הבלוק.
    shell = _over(live["shellBg"], paper)
    header = _over(live["headerBg"], shell)
    button = _over(live["copyBg"], header)
    icon = _contrast(_over(live["copyColor"], button), button)
    assert icon >= 3.0, f"{name}: אייקון ההעתקה בניגודיות {icon:.2f}"


#: קו הפרדה וכותרות בתצוגת המסמך — הכללים שלהם ב-``md-content-layout.css`` וב-``md-content-colors.css``,
#: המשותפים לתצוגה החיה (שם הם נבדקים ב-``tests/test_markdown_editor_browser.py``).
SEPARATOR_JS = """() => {
  const c = document.getElementById('md-content');
  const hr = getComputedStyle(c.querySelector('hr'));
  return {height: hr.height, borderTop: hr.borderTopWidth, borderBottom: hr.borderBottomWidth,
          background: hr.backgroundColor, ink: getComputedStyle(c).color, marginTop: parseFloat(hr.marginTop),
          h1: getComputedStyle(c.querySelector('h1')).borderBottomWidth,
          h2: getComputedStyle(c.querySelector('h2')).borderBottomWidth};
}"""


@pytest.fixture(scope="module")
def separators(chromium_executable):
    html = "<h1>ראשית</h1><h2>משנה</h2><p>לפני</p><hr><p>אחרי</p>"
    return _measure_pages(
        chromium_executable,
        {name: _document_page(name, html) for name in THEMES},
        None,
        SEPARATOR_JS,
    )


@pytest.mark.parametrize("name", list(THEMES))
def test_the_document_separator_is_a_thin_line_in_the_paper_ink(separators, name):
    """``---`` בתצוגת המסמך: קו של פיקסל אחד בצבע הדיו של הנייר בשקיפות, עם מרווח — ולא הקו ה"בולט" האפור של
    הדפדפן, שעל נייר כהה נראה כמו פס לבן. ול-H1 ול-H2 אין קו תחתון."""
    m = separators[name]
    assert m["height"] == "1px" and m["borderTop"] == "0px" and m["borderBottom"] == "0px", m
    line, alpha = _rgba(m["background"])
    ink, _ = _rgba(m["ink"])
    assert all(abs(a - b) <= 1 / 255 for a, b in zip(line, ink)), m
    assert 0.1 < alpha < 0.4, m
    assert m["marginTop"] > 8, m
    assert m["h1"] == "0px" and m["h2"] == "0px", m
