"""שם הפתק ב"פתקים אחרונים" הוא קישור — ובכל ערכה הוא נראה כמו שם של קובץ נעוץ, בכרומיום.

**למה מול שם של קובץ נעוץ.** ``.pinned-card__name`` הוא הדפוס הקיים בדשבורד לשם שאפשר ללחוץ
עליו: צבע הטקסט, בלי קו תחתון, וקו בריחוף. שם הפתק (``.note-title``) בנוי באותה צורה. אבל
``<a>`` בדשבורד נצבע גם בכללי הקישורים של הערכות — ``[data-theme="dark"] a`` ודומיו ב-
``dark-mode.css``, ו-``[data-theme="high-contrast"] a`` עם ``!important`` ב-``high-contrast.css``
— ואלה גוברים בספציפיות על כלל של מחלקה אחת. לכן נמדד כאן, בכל ערכה, שהשם של הפתק יוצא כמו
השם של הקובץ הנעוץ, ושבריחוף ובפוקוס מהמקלדת יש לו קו תחתון.

**התבנית אמיתית, השרת לא.** ``dashboard.html`` מרונדר מהדיסק (``tests/_dashboard_render.py``),
עם בלוק ה-``<style>`` שלו, ולידו שני קבצי הערכות שנטענים בכל עמוד. הטוקנים של ``base.html``
אינם בעמוד, ולכן ``--primary`` מוגדר כאן לצבע שאפשר לזהות: כך נראה אם כלל הקישורים של הערכה
הוא שקבע את הצבע.

מדולג כשאין Chromium (וב-CI אין: ראו ``docs/testing.rst``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")
pytest.importorskip("jinja2")

from playwright.sync_api import sync_playwright  # noqa: E402

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _dashboard_render import render_dashboard  # noqa: E402

CSS_DIR = Path(__file__).resolve().parents[1] / "webapp" / "static" / "css"

#: הערכות המובנות. ארבע הראשונות אינן צובעות ``a``; ארבע האחרונות כן — ``custom`` בשם כל ערכה
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
            "id": "64b7f1d2e3a4b5c6d7e8f901", "title": "שם הפתק", "location": "לוח רעיונות",
            "url": "/note/64b7f1d2e3a4b5c6d7e8f901", "relative_time": "לפני 5 שעות",
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


@pytest.fixture(scope="module")
def page(chromium_executable):
    with sync_playwright() as pw:
        browser = (pw.chromium.launch(executable_path=chromium_executable)
                   if chromium_executable else pw.chromium.launch())
        try:
            yield browser.new_page()
        finally:
            browser.close()


@pytest.mark.parametrize("theme", THEMES)
def test_the_note_title_looks_like_a_pinned_file_name(page, theme):
    page.set_content(_page_html(theme))
    page.mouse.move(0, 0)

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
    page.set_content(_page_html(theme))

    page.hover(NOTE)
    assert page.evaluate(_STYLE, NOTE)["decoration"] == "underline", (theme, "hover")

    page.mouse.move(0, 0)
    page.keyboard.press("Shift")  # פוקוס אחרי מקלדת הוא ``:focus-visible``
    page.focus(NOTE)
    assert page.evaluate(_STYLE, NOTE)["decoration"] == "underline", (theme, "focus")
