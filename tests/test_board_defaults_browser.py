"""ברירות המחדל של לוח, בעמוד ``/boards/<id>`` האמיתי בכרומיום: גודל הטקסט והגלילה האינסופית.

**מה נבדק כאן ולא ב-``tests/board-handwriting.test.js``.** שם הבלוקים מחולצים מהתבנית ורצים מול
``document`` ו-``localStorage`` מדומים. כאן רץ העמוד כולו, כמו שהשרת מרנדר אותו: ההכללה המשותפת
עם ברירת המחדל שהשרת הזריק (``NOTE_FONT_SIZE_DEFAULT`` ← ``STICKY_NOTE_FONT_SIZE_DEFAULT``), ה-CSS
של הפתקים, המנהל שנבנה עם ``readInfinite()``, ו-``localStorage`` אמיתי ששורד רענון. והמדידה היא על
מה שהמשתמש רואה — גודל הגופן המחושב בתוך פתק — ולא רק על מחלקה שנוספה ל-``<html>``.

**רק ה-API מזויף** (``board_page`` ב-``tests/test_note_menu_pages_browser.py``): רשימת הלוחות
והפתקים. אין כאן מסד.

מדולג כשאין Chromium (וב-CI אין: ראו ``docs/testing.rst``).
"""

from __future__ import annotations

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from test_note_menu_pages_browser import BOARD, board_note, board_page  # noqa: E402

NOTE = "n1"
FONT_KEY = f"board-font-size:{BOARD}"
INFINITE_KEY = f"board-infinite:{BOARD}"

#: מה שהמשתמש רואה: גודל הגופן המחושב של תוכן הפתק, בפיקסלים.
NOTE_FONT_PX_JS = """(nid) => parseFloat(getComputedStyle(
  document.querySelector(`.sticky-note[data-note-id="${nid}"] .sticky-note-content`)).fontSize)"""

#: מצב הלוח אחרי הטעינה: המחלקות על ``<html>``, הבורר, המתג, המנהל, והאחסון של הלוח.
STATE_JS = """([fontKey, infiniteKey]) => ({
  classes: [...document.documentElement.classList].filter((c) => c.startsWith('sticky-font-')),
  injectedDefault: window.STICKY_NOTE_FONT_SIZE_DEFAULT,
  select: document.getElementById('noteFontSizeSelect').value,
  toggle: document.getElementById('infiniteScrollToggle').checked,
  manager: window._boardNotes.infiniteScroll,
  storedFont: localStorage.getItem(fontKey),
  storedInfinite: localStorage.getItem(infiniteKey),
})"""


def _state(page):
    return page.evaluate(STATE_JS, [FONT_KEY, INFINITE_KEY])


def _reload(page):
    page.reload(wait_until="load")
    page.wait_for_selector(f'#boardSurface .sticky-note[data-note-id="{NOTE}"]', timeout=20000)


def test_a_board_nobody_chose_for_opens_extra_large_with_infinite_scroll(admin_live_server, chromium_executable):
    """לוח בלי שום בחירה: "גדול מאוד" — בתצוגה, בבורר ובגופן שבפתק — והגלילה האינסופית דלוקה.

    **והטעינה אינה כותבת דבר.** ברירת מחדל שנכתבת לאחסון בטעינה הייתה הופכת לבחירה, ושינוי עתידי
    של ברירת המחדל לא היה מגיע ללוח הזה.
    """
    from webapp.app import NOTE_FONT_SIZE_DEFAULT

    with board_page(admin_live_server, chromium_executable, [board_note(NOTE, y=40)]) as page:
        state = _state(page)
        assert state["injectedDefault"] == NOTE_FONT_SIZE_DEFAULT == "xlarge", state
        assert state["classes"] == ["sticky-font-xlarge"], state
        assert state["select"] == "xlarge", state
        assert state["toggle"] is True and state["manager"] is True, state
        assert state["storedFont"] is None and state["storedInfinite"] is None, state


def test_choosing_normal_shrinks_the_note_and_survives_a_reload(admin_live_server, chromium_executable):
    """בחירה ב"רגיל" נשמרת — גם שהיא אינה ברירת המחדל — ושורדת רענון.

    **הגופן בפתק נמדד לפני ואחרי, ולא מושווה למספר.** "רגיל" קטן מברירת המחדל, ולכן הגופן קטן;
    ואחרי הרענון הוא נשאר באותו גודל קטן. עד נובמבר 2026 "רגיל" נשמר כהיעדר מפתח, ואחרי שברירת המחדל
    עברה ל"גדול מאוד" רענון היה מחזיר את הלוח לגדול.
    """
    with board_page(admin_live_server, chromium_executable, [board_note(NOTE, y=40)]) as page:
        default_px = page.evaluate(NOTE_FONT_PX_JS, NOTE)

        page.click("#boardSettingsBtn")
        page.select_option("#noteFontSizeSelect", "normal")
        chosen_px = page.evaluate(NOTE_FONT_PX_JS, NOTE)
        assert chosen_px < default_px, (chosen_px, default_px)
        assert _state(page)["storedFont"] == "normal"

        _reload(page)
        state = _state(page)
        assert state["classes"] == [] and state["select"] == "normal" and state["storedFont"] == "normal", state
        assert page.evaluate(NOTE_FONT_PX_JS, NOTE) == chosen_px


def test_turning_infinite_scroll_off_survives_a_reload(admin_live_server, chromium_executable):
    """כיבוי הגלילה נשמר במפורש (``'0'``), ואחרי רענון המתג והמנהל כבויים — ברירת המחדל אינה גוברת."""
    with board_page(admin_live_server, chromium_executable, [board_note(NOTE, y=40)]) as page:
        page.click("#boardSettingsBtn")
        page.uncheck("#infiniteScrollToggle")
        state = _state(page)
        assert state["storedInfinite"] == "0" and state["manager"] is False, state

        _reload(page)
        state = _state(page)
        assert state["toggle"] is False and state["manager"] is False, state
