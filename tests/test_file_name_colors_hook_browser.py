"""ווי הדריסה של שם הקובץ, התיאור והמטא של כרטיס הקובץ, נמדדים בדפדפן — בכרטיס בעמוד הקבצים ובראש תצוגת הקוד,
ה-Markdown וה-HTML.

ערכה שמצהירה בבלוק ``variables`` על ``--file-name-color-override`` ושכניו מקבלת את הצבעים בכל ארבעת העמודים — גם
כשהיא פורסמה לציבורית, דרך מסלול הפרסום האמיתי. ערכה שאינה מצהירה נשארת כמו היום: השם ב-``--text-primary`` של
כלל הכותרות, התיאור ב-``--text-secondary`` של כלל הפסקאות, והמטא בצבע שהוא יורש. ערכה מובנית לא מושפעת מה-class
בכלל. ובתצוגת ה-HTML התחילית שלפני השם, והמשפט על ה-sandbox, לא זזים.

כל עמוד נבנה מה-CSS האמיתי שלו (ראש ``base.html``, ``extra_css`` ובלוקי ה-``style`` של התבנית) ומה-markup האמיתי
של הכותרת שלו, כפי שהוא בתבנית. את החוזה הטקסטואלי, שרץ גם בלי דפדפן, בודק
``tests/services/test_theme_variables_file_name_hook.py``.

מדולג כשאין Chromium.
"""

from __future__ import annotations

import re

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from markupsafe import Markup  # noqa: E402

from test_live_preview_blockquote_browser import (  # noqa: E402
    CUSTOM_VSCODE_THEME,
    TEMPLATES_DIR,
    _measure_pages,
    _render_fragment,
    build_head,
    custom_theme,
    html_theme_attributes,
    shared_theme,
)

#: פלטה ג' של morass. כל צבע שונה מכל צבע שהערכה של הבדיקה נותנת בלי הטוקנים.
DECLARED = {
    "--file-name-color-override": "#7fdbca",
    "--file-description-color-override": "#dcdcaa",
    "--file-card-meta-color-override": "#afd0c4",
}

WITH_TOKENS = {**CUSTOM_VSCODE_THEME, "variables": DECLARED}

FILE = {
    "id": "0123456789abcdef01234567",
    "file_name": "ערכות-VS-Code-בלוק-variables.md",
    "description": "הסבר: בלוק variables בקובץ ערכת VS Code",
    "language": "markdown",
    "lines": 125,
    "size": "7.6 KB",
    "tags": ["themes"],
    "created_at": "10/11/2026 05:02",
    "updated_at": "10/11/2026 13:50",
    "was_edited": True,
    "version": 2,
}


def _lang_icon(*_args, **_kwargs):
    """אייקון השפה אינו חלק מהמדידה — רק מקום בכותרת, כמו בעמוד."""
    return Markup('<span class="lang-icon" style="display:inline-block;width:48px;height:48px"></span>')


#: ``(תבנית, סמן תחילה, סמן סוף, סגירה)``: הקטע של התבנית שמציג את שם הקובץ, מהסמן הראשון עד סוף הסמן השני, ואחריו
#: התגים שסוגרים את מה שהקטע פתח. בעמוד הקבצים — רשת הכרטיסים כולה.
FRAGMENTS = {
    "files": ("files.html", '<div class="files-grid stagger-feed"', "{% endfor %}\n</div>", ""),
    "view_file": ("view_file.html", '<div class="file-header">', "{{ file.description }}</p>", "</div></div>"),
    "md_preview": ("md_preview.html", '<div id="md-file-name-wrap">', "</h1>", "</div>"),
    "html_preview": ("html_preview.html", '<div class="file-header">', "</p>", "</div></div>"),
}


def _fragment(name: str) -> str:
    template_name, start, end, closing = FRAGMENTS[name]
    source = (TEMPLATES_DIR / template_name).read_text(encoding="utf-8")
    assert source.count(start) == 1, f"הסמן {start!r} לא נמצא פעם אחת ב-{template_name}"
    begin = source.index(start)
    assert end in source[begin:], f"הסמן {end!r} לא נמצא אחרי {start!r} ב-{template_name}"
    stop = source.index(end, begin) + len(end)
    return _render_fragment(
        source[begin:stop] + closing,
        file=FILE,
        files=[FILE],
        files_compact_view=False,
        lang_icon=_lang_icon,
        LANG_ICON_SIZES={"file_row": 48},
    )


def _content_styles(template_name: str) -> str:
    """בלוקי ה-``style`` שבתוך ``{% block content %}`` — חלק מהמפל של העמוד, כמו ``extra_css``."""
    source = (TEMPLATES_DIR / template_name).read_text(encoding="utf-8")
    content = source.split("{% block content %}", 1)[1].split("{% endblock %}", 1)[0]
    return "\n".join(re.findall(r"<style>.*?</style>", content, re.S))


def _page(name: str, attr: str, theme: dict | None) -> str:
    template = TEMPLATES_DIR / FRAGMENTS[name][0]
    # העמוד של משתמש רגיל: ``user_is_admin`` הוא המשתנה היחיד שה-``extra_css`` של עמוד הקבצים קורא.
    context = {"user_is_admin": False}
    if attr == "shared":
        head = build_head(shared=theme, template=template, **context)
    elif attr == "custom":
        head = build_head(theme, template, **context)
    else:
        head = build_head(None, template, **context)
    return (
        f'<!doctype html><html dir="rtl" lang="he" {html_theme_attributes(attr)}>'
        f'<head><meta charset="utf-8">{head}{_content_styles(template.name)}</head>'
        f'<body><main class="container" id="page">{_fragment(name)}</main></body></html>'
    )


#: אותה מדידה בכל העמודים. ``probe`` יוצר בתוך העמוד אלמנט זמני — צבוע בביטוי נתון, או אלמנט ``h3`` / ``p`` בלי
#: ה-class — כדי לקרוא את הערך שהטוקנים של היום נותנים באותו מקום.
MEASURE_JS = """() => {
    const page = document.getElementById('page');
    const color = (el) => el ? getComputedStyle(el).color : null;
    const probe = (make) => {
        const el = make();
        page.appendChild(el);
        const value = getComputedStyle(el).color;
        el.remove();
        return value;
    };
    const painted = (expr) => probe(() => { const el = document.createElement('span'); el.style.color = expr; return el; });
    const plain = (tag) => probe(() => document.createElement(tag));
    const names = [...document.querySelectorAll('.file-name-text')];
    const meta = [...document.querySelectorAll('.file-card-meta')];
    const heading = document.querySelector('.file-header h1');
    return {
        names: names.length,
        name: color(names[0]),
        description: color(document.querySelector('.file-description-text')),
        meta: meta.map(color),
        metaIcons: [...document.querySelectorAll('.file-card-meta i')].map(color),
        metaParents: meta.map((el) => color(el.parentElement)),
        htmlHeading: heading && heading.querySelector('.file-name-text') ? color(heading) : null,
        sandboxNote: color(document.querySelector('.file-header .file-info > p:not(.file-description-text)')),
        textPrimary: painted('var(--text-primary)'),
        textSecondary: painted('var(--text-secondary)'),
        plainHeading: plain('h3'),
        plainParagraph: plain('p'),
    };
}"""

#: ``(data-theme, ערכה עם הטוקנים או בלעדיהם)`` — אישית, שפורסמה לציבורית, ומובנות.
CASES = {
    "custom-declared": ("custom", WITH_TOKENS),
    "shared-declared": ("shared", WITH_TOKENS),
    "custom-plain": ("custom", CUSTOM_VSCODE_THEME),
    "shared-plain": ("shared", CUSTOM_VSCODE_THEME),
    "classic": ("classic", None),
    "dark": ("dark", None),
}

PAGE_NAMES = list(FRAGMENTS)
WITH_DESCRIPTION = {"files", "view_file"}


def _rgb(hex_color: str) -> str:
    value = hex_color.lstrip("#")
    return "rgb({}, {}, {})".format(*(int(value[i : i + 2], 16) for i in (0, 2, 4)))


def _theme(attr: str, vscode: dict | None) -> dict | None:
    if vscode is None:
        return None
    return shared_theme(vscode) if attr == "shared" else custom_theme(vscode)


@pytest.fixture(scope="module")
def measured(chromium_executable):
    themes = {name: (attr, _theme(attr, vscode)) for name, (attr, vscode) in CASES.items()}
    pages = {
        f"{page}-{case}": _page(page, attr, theme)
        for case, (attr, theme) in themes.items()
        for page in PAGE_NAMES
    }
    return _measure_pages(chromium_executable, pages, None, MEASURE_JS)


def _case(measured, page: str, case: str) -> dict:
    m = measured[f"{page}-{case}"]
    assert m["names"] == 1, f"{page}-{case}: שם הקובץ לא נמצא פעם אחת: {m}"
    return m


@pytest.mark.parametrize("page", PAGE_NAMES)
@pytest.mark.parametrize("case", ["custom-declared", "shared-declared"])
def test_declared_tokens_paint_the_name_and_description(measured, page, case):
    m = _case(measured, page, case)
    assert m["name"] == _rgb(DECLARED["--file-name-color-override"]), m
    if page in WITH_DESCRIPTION:
        assert m["description"] == _rgb(DECLARED["--file-description-color-override"]), m


@pytest.mark.parametrize("case", ["custom-declared", "shared-declared"])
def test_declared_tokens_paint_the_card_meta(measured, case):
    """השורות, הגודל והתאריכים — והאייקונים של התאריכים, שיורשים מהם."""
    m = _case(measured, "files", case)
    meta = _rgb(DECLARED["--file-card-meta-color-override"])
    assert len(m["meta"]) == 3 and set(m["meta"]) == {meta}, m
    assert m["metaIcons"] and set(m["metaIcons"]) == {meta}, m


@pytest.mark.parametrize("page", PAGE_NAMES)
@pytest.mark.parametrize("case", ["custom-plain", "shared-plain"])
def test_undeclared_tokens_leave_the_page_as_it_was(measured, page, case):
    """הערכה של הבדיקה נותנת ל-``--text-primary`` ול-``--text-secondary`` ערכים שונים, ולכן ההשוואה מבחינה בין
    ה-fallback של השם לזה של התיאור."""
    m = _case(measured, page, case)
    assert m["textPrimary"] != m["textSecondary"], m
    assert m["name"] == m["textPrimary"] == m["plainHeading"], m
    if page in WITH_DESCRIPTION:
        assert m["description"] == m["textSecondary"] == m["plainParagraph"], m
    if page == "files":
        assert len(m["meta"]) == 3 and m["meta"] == m["metaParents"], m


@pytest.mark.parametrize("page", PAGE_NAMES)
@pytest.mark.parametrize("case", ["classic", "dark"])
def test_builtin_themes_ignore_the_hook_classes(measured, page, case):
    """הכללים חלים רק בערכה מיובאת או משותפת: בערכה מובנית השם צבוע כמו כל כותרת, והתיאור כמו כל פסקה."""
    m = _case(measured, page, case)
    assert m["name"] == m["plainHeading"], m
    if page in WITH_DESCRIPTION:
        assert m["description"] == m["plainParagraph"], m
    if page == "files":
        assert m["meta"] == m["metaParents"], m


@pytest.mark.parametrize("case", ["custom-declared", "shared-declared"])
def test_the_html_preview_prefix_and_sandbox_note_stay(measured, case):
    """בתצוגת ה-HTML השם הוא חלק מכותרת עם תחילית. רק השם נצבע; התחילית נשארת בצבע של הכותרת, והמשפט על
    ה-sandbox — שאינו התיאור של הקובץ — בצבע של הפסקה."""
    m = _case(measured, "html_preview", case)
    assert m["htmlHeading"] == m["textPrimary"] != m["name"], m
    assert m["sandboxNote"] == m["textSecondary"], m


@pytest.mark.parametrize("page", PAGE_NAMES)
def test_other_headings_and_paragraphs_stay(measured, page):
    """הטוקנים צובעים רק את האלמנטים שנושאים את ה-class. כותרת ופסקה אחרות באותו עמוד נשארות בכללי ה-Typography."""
    m = _case(measured, page, "shared-declared")
    assert m["plainHeading"] == m["textPrimary"], m
    assert m["plainParagraph"] == m["textSecondary"], m
