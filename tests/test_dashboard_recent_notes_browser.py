"""שם הפתק ב"פתקים אחרונים" הוא קישור — רק הטקסט שלו, בלשונית חדשה, ובכל ערכה כמו שם של קובץ נעוץ.

**למה מול שם של קובץ נעוץ.** ``.pinned-card__name`` הוא הדפוס הקיים בדשבורד לשם שאפשר ללחוץ
עליו: צבע הטקסט, בלי קו תחתון, וקו בריחוף. שם הפתק (``.note-title``) בנוי באותה צורה. אבל
``<a>`` בדשבורד נצבע גם בכללי הקישורים של הערכות — ``[data-theme="dark"] a`` ודומיו ב-
``dark-mode.css``, ו-``[data-theme="high-contrast"] a`` עם ``!important`` ב-``high-contrast.css``
— ואלה גוברים בספציפיות על כלל של מחלקה אחת. לכן נמדד כאן, בכל ערכה, שהשם של הפתק יוצא כמו
השם של הקובץ הנעוץ, ושבריחוף ובפוקוס מהמקלדת יש לו קו תחתון.

**רק הטקסט הוא הקישור.** עד נובמבר 2026 הקישור היה ``display: block``, ולכן כל רוחב השורה — גם
השטח הריק אחרי השם — פתח את הפתק. נמדד כאן מה שהדפדפן באמת פוגע בו בנקודה שבשורה ומחוץ לטקסט.

**ובלשונית חדשה.** לחיצה על השם פותחת עמוד חדש בכתובת של הפתק, והדשבורד נשאר במקומו.

**התבנית אמיתית, השרת לא.** ``dashboard.html`` מרונדר מהדיסק (``tests/_dashboard_render.py``),
עם בלוק ה-``<style>`` שלו, ולידו שני קבצי הערכות שנטענים בכל עמוד. העמוד מוגש מכתובת מדומה
(``HOST``) דרך ``route``, כדי שהקישור היחסי ``/note/<id>`` ייפתח לכתובת אמיתית. הטוקנים של
``base.html`` אינם בעמוד, ולכן ``--primary`` מוגדר כאן לצבע שאפשר לזהות: כך נראה אם כלל
הקישורים של הערכה הוא שקבע את הצבע.

מדולג כשאין Chromium (וב-CI אין: ראו ``docs/testing.rst``).
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")
pytest.importorskip("jinja2")

from playwright.sync_api import sync_playwright  # noqa: E402

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _dashboard_render import render_dashboard  # noqa: E402

CSS_DIR = Path(__file__).resolve().parents[1] / "webapp" / "static" / "css"
HOST = "https://ck.test"
NOTE_ID = "64b7f1d2e3a4b5c6d7e8f901"
NOTE_URL = f"/note/{NOTE_ID}"

#: הערכות המובנות. שלוש הראשונות אינן צובעות ``a``; ארבע שאחריהן כן — ``custom`` בשם כל ערכה
#: מיובאת — ו-``high-contrast`` עם ``!important`` וקו תחתון קבוע.
THEMES = ("classic", "ocean", "rose-pine-dawn", "dark", "dim", "nebula", "custom", "high-contrast")

PRIMARY = "rgb(1, 2, 3)"
TEXT = "rgb(200, 200, 200)"

NOTE = ".notes-card a.note-title"
PINNED = ".pinned-card__name"

_STYLE = """sel => { const s = getComputedStyle(document.querySelector(sel));
  return {color: s.color, decoration: s.textDecorationLine}; }"""


def _page_html(theme: str) -> str:
    body = render_dashboard(
        notes_snapshot={"has_notes": True, "notes": [{
            "id": NOTE_ID, "title": "שם קצר", "location": "לוח רעיונות",
            "url": NOTE_URL, "relative_time": "לפני 5 שעות",
        }]},
        pinned_files=[{"id": "f1", "file_name": "קובץ נעוץ.py", "language": "python", "icon": "",
                       "tags": [], "description": "", "lines": 1}],
    )
    themes_css = "\n".join(
        (CSS_DIR / name).read_text(encoding="utf-8") for name in ("high-contrast.css", "dark-mode.css")
    )
    return (
        f'<!doctype html><html dir="rtl" data-theme="{theme}"><head><meta charset="utf-8">'
        f"<style>:root {{ --primary: {PRIMARY}; --primary-dark: {PRIMARY}; }} body {{ color: {TEXT}; }}</style>"
        f"<style>{themes_css}</style></head><body>{body}</body></html>"
    )


def _serve(route):
    """``/dashboard/<ערכה>`` — הדשבורד המרונדר; ``/note/<id>`` — עמוד ריק, היעד של הקישור."""
    path = urlsplit(route.request.url).path
    if path.startswith("/dashboard/"):
        route.fulfill(status=200, content_type="text/html; charset=utf-8",
                      body=_page_html(path.rsplit("/", 1)[-1]))
    elif path.startswith("/note/"):
        route.fulfill(status=200, content_type="text/html; charset=utf-8", body="<!doctype html><p>פתק</p>")
    else:
        route.abort()


@pytest.fixture(scope="module")
def context(chromium_executable):
    with sync_playwright() as pw:
        browser = (pw.chromium.launch(executable_path=chromium_executable)
                   if chromium_executable else pw.chromium.launch())
        try:
            ctx = browser.new_context(viewport={"width": 1280, "height": 900})
            ctx.route(f"{HOST}/**", _serve)
            yield ctx
        finally:
            browser.close()


@pytest.fixture
def page(context):
    page = context.new_page()
    yield page
    page.close()


def _open(page, theme: str):
    page.goto(f"{HOST}/dashboard/{theme}")
    page.mouse.move(0, 0)


@pytest.mark.parametrize("theme", THEMES)
def test_the_note_title_looks_like_a_pinned_file_name(page, theme):
    _open(page, theme)

    note = page.evaluate(_STYLE, NOTE)
    assert note == page.evaluate(_STYLE, PINNED), theme
    # ולא רק "שווים": בערכה שאינה צובעת ``a`` — צבע הטקסט, בלי קו; בערכה שצובעת — ``--primary``.
    # ב-High Contrast הצבע והקו הם של ``high-contrast.css``, וההשוואה לשם הנעוץ מספיקה.
    if theme in ("classic", "ocean", "rose-pine-dawn"):
        assert note == {"color": TEXT, "decoration": "none"}, theme
    elif theme != "high-contrast":
        assert note == {"color": PRIMARY, "decoration": "none"}, theme


@pytest.mark.parametrize("theme", THEMES)
def test_the_note_title_is_underlined_on_hover_and_on_keyboard_focus(page, theme):
    _open(page, theme)

    page.hover(NOTE)
    assert page.evaluate(_STYLE, NOTE)["decoration"] == "underline", (theme, "hover")

    page.mouse.move(0, 0)
    page.keyboard.press("Shift")  # פוקוס אחרי מקלדת הוא ``:focus-visible``
    page.focus(NOTE)
    assert page.evaluate(_STYLE, NOTE)["decoration"] == "underline", (theme, "focus")


def test_only_the_title_text_is_the_link(page):
    """בנקודה שבשורה של השם, אבל מחוץ לטקסט שלו, הדפדפן אינו פוגע בקישור.

    הנקודה נבחרת לפי המדידה ולא לפי כיוון: בצד שבו יש יותר מקום ריק בין הטקסט לקצה השורה.
    """
    _open(page, "classic")

    hit = page.evaluate("""sel => {
      const a = document.querySelector(sel);
      // ``elementFromPoint`` עונה רק בתוך החלון, ושורת הכרטיסים בדשבורד נגללת לרוחב.
      a.scrollIntoView({block: 'center', inline: 'center'});
      const row = a.closest('li').getBoundingClientRect();
      const text = a.getBoundingClientRect();
      const y = text.top + text.height / 2;
      const x = (text.left - row.left) > (row.right - text.right) ? row.left + 4 : row.right - 4;
      const el = document.elementFromPoint(x, y);
      return {rowWidth: row.width, textWidth: text.width, insideRow: !!el && a.closest('li').contains(el),
              onLink: !!el && a.contains(el)};
    }""", NOTE)

    assert hit["textWidth"] < hit["rowWidth"] / 2, hit
    assert hit["insideRow"] and not hit["onLink"], hit


def test_the_note_title_opens_the_note_in_a_new_tab(page, context):
    _open(page, "classic")

    with context.expect_page() as opened:
        page.click(NOTE)
    new_tab = opened.value
    new_tab.wait_for_load_state()

    assert new_tab.url == f"{HOST}{NOTE_URL}"
    assert page.url == f"{HOST}/dashboard/classic", "הדשבורד נשאר במקומו"
    new_tab.close()
