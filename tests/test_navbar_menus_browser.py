"""תפריטי הסרגל העליון — בכרומיום אמיתי, בעמוד אמיתי, במגע של טאבלט.

**התקלה.** בכל עמוד, חלונית קיצורי הדרך (🚀) ותפריט האפקטים (🪄) נפתחו ונראו תקינים,
אבל נגיעה בכפתור לא עשתה כלום. ההסבר המלא יושב מעל הכלל ``.navbar:has(...)`` ב-
``base.html``: החלוניות יוצאות מתחת לסרגל, אל השטח של ``.main-content`` שמצויר מעליו,
והנגיעה הלכה לשם. בתפריט האפקטים היו עוד שתי סיבות: החלונית נפתחה אל מחוץ למסך (העיגון
ב-``.fun-mode-dropdown``), ובפריסת ההמבורגר הרשימה חתכה אותה (``.nav-menu.active``).

**מה נבדק.** נגיעה אמיתית בכל כפתור בשני התפריטים, בשתי הפריסות של הסרגל: טאבלט
לרוחב, בלי המבורגר, ופריסת ההמבורגר, שבה השרביט נמצא בתוך הרשימה. ובנוסף שומר:
אחרי שתפריט נסגר, כפתור הסימניות 🔖 וכותרת פאנל הסימניות לחיצים בראש עמוד קובץ. השומר
עובר גם לפני התיקון, וזה מכוון — הוא עומד מול התיקון שנראה מתבקש, הרמה קבועה של
הסרגל, שנמדד שמסתיר את שניהם.

**איך יודעים שהנגיעה הגיעה.** מאזין בשלב הלכידה על כל כפתור רושם את הלחיצה ובולע
אותה, כך שהכפתור לא מנווט ולא מפעיל אפקט, והתפריט נשאר פתוח לנגיעה הבאה. היעד נמדד
מהאירוע עצמו: במגע הדפדפן יכול להצמיד נגיעה לכפתור סמוך, ולכן ``elementFromPoint``
אינו ההוכחה.

**כפתור ההמבורגר.** האייקון שלו הוא גליף של Font Awesome מ-CDN, וכאן כל בקשה החוצה
נקטעת — ולכן לכפתור אין גודל ואי אפשר לגעת בו. הבדיקה נותנת לאייקון קופסה בגודל
הגליף, ונוגעת בכפתור בנגיעה אמיתית.

**מה לא נבדק כאן:** מכשיר אנדרואיד אמיתי — זו אמולציית מגע בכרומיום. גם לא Telegram
Mini App, שבו ``body.telegram-mini-app .navbar`` משנה את הסרגל.

מדולג כשאין Chromium (וב-CI אין: ראו ``docs/testing.rst``). את ההחלטות שומר גם בלי
דפדפן ``tests/test_navbar_and_search_bars_css.py``.
"""
from __future__ import annotations

import contextlib

import pytest
from bson import ObjectId

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import open_admin_page, poll, tap_on

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

#: ``admin_live_server`` בונה session למשתמש 1, שהוא אדמין.
USER_ID = 1

#: שתי הפריסות של הסרגל. כל בדיקה מוודאת קודם שהיא באמת בפריסה שהיא מתיימרת לבדוק.
TABLET = {"width": 1280, "height": 800}
HAMBURGER = {"width": 767, "height": 1227}
LAYOUTS = {"tablet": TABLET, "hamburger": HAMBURGER}

QUICK = {"toggle": ".quick-access-toggle", "panel": "#quickAccessDropdown",
         "items": "#quickAccessDropdown .quick-access-item"}
EFFECTS = {"toggle": ".fun-mode-toggle", "panel": "#funModeDropdown",
           "items": "#funModeDropdown .fun-mode-item"}

#: קיצור שמרונדר רק לאדמין. ``dashboard`` מרנדר את העמוד בלי הרשאת אדמין כשהמסד נכשל, ולכן
#: הנוכחות שלו היא הבקרה שהעמוד עלה כרגיל — ושגם הכפתור הזה נבדק.
ADMIN_ONLY_SHORTCUT = '#quickAccessDropdown a[href="/repo/"]'

#: נגיעה שהגיעה לכפתור נרשמת כאן ונבלעת. מאזין לכידה על הכפתור עצמו רץ לפני ה-``onclick``
#: שלו ולפני מאזין הסגירה שעל ``document``, ולכן הכפתור לא פועל והתפריט נשאר פתוח.
RECORD_TAPS_JS = """(sel) => {
  window.__taps = [];
  const items = Array.from(document.querySelectorAll(sel));
  items.forEach((el, i) => el.addEventListener('click', (ev) => {
    ev.preventDefault(); ev.stopImmediatePropagation(); window.__taps.push(i);
  }, true));
  return items.length;
}"""

#: החלונית פתוחה לגמרי: מסומנת כפתוחה, אטומה, ושום מעבר כבר לא רץ עליה.
PANEL_OPEN_JS = """(sel) => {
  const el = document.querySelector(sel);
  const moving = document.getAnimations().some(a => a.effect && a.effect.target
      && (a.effect.target === el || el.contains(a.effect.target)));
  return {ok: el.classList.contains('active') && getComputedStyle(el).opacity === '1' && !moving,
          active: el.classList.contains('active'), opacity: getComputedStyle(el).opacity, moving};
}"""

HAMBURGER_SHOWN_JS = "() => getComputedStyle(document.querySelector('.mobile-menu-toggle')).display !== 'none'"


@contextlib.contextmanager
def layout_page(server, executable, path: str, viewport: dict):
    """עמוד אמיתי במגע — **המקום היחיד שמרים דפדפן בקובץ הזה**.

    ההרמה כאן ולא ב-``tests/_browser_harness.py``: ``tests/test_browser_suite_is_gated_once.py``
    מוודא שרק קובצי ``*_browser.py`` מרימים דפדפן. ``--window-size`` שווה לאזור התצוגה,
    מהסיבה שנמדדה ב-``tests/test_repo_notes_browser.py``.
    """
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(
                executable_path=executable,
                args=[f"--window-size={viewport['width']},{viewport['height']}"],
            )
        except PlaywrightError as exc:  # pragma: no cover - תלוי בסביבה
            pytest.skip(f"אין Chromium זמין: {exc}")
        try:
            yield open_admin_page(browser, server, path, viewport=viewport)
        finally:
            browser.close()


def _check_layout(page, viewport: dict) -> None:
    """בקרה: הפריסה היא זו שהבדיקה מתיימרת לבדוק — אחרת היא בודקת פריסה אחרת בשקט."""
    shown = page.evaluate(HAMBURGER_SHOWN_JS)
    assert shown == (viewport is HAMBURGER), (
        f"הפריסה אינה הצפויה ב-{viewport}: כפתור ההמבורגר {'מוצג' if shown else 'מוסתר'}"
    )


def _open_hamburger(page, touch) -> None:
    """פותח את רשימת ההמבורגר בנגיעה אמיתית, אחרי שהאייקון קיבל קופסה.

    הגופן אינו נטען כאן, ולכן הקופסה ניתנת ישירות לאלמנט, בערך בגודל של אות אחת. הגודל
    המדויק אינו העניין: הבדיקה צריכה כפתור שאפשר לגעת בו, ושום טענה שלה לא נשענת עליו.
    """
    page.evaluate("""() => {
      const icon = document.querySelector('.mobile-menu-toggle i');
      icon.style.display = 'inline-block'; icon.style.width = '1em'; icon.style.height = '1em';
    }""")
    tap_on(page, touch, ".mobile-menu-toggle")
    poll(page, "() => document.getElementById('navMenu').classList.contains('active')",
         "רשימת ההמבורגר נפתחה")


def _tap_every_item(page, touch, menu: dict) -> None:
    """פותח את התפריט בנגיעה בכפתור שלו, ונוגע בכל כפתור שבו — כל נגיעה חייבת להגיע אליו."""
    count = page.evaluate(RECORD_TAPS_JS, menu["items"])
    assert count > 0, f"לא נמצא אף כפתור ב-{menu['panel']}"
    tap_on(page, touch, menu["toggle"])
    poll(page, PANEL_OPEN_JS, f"{menu['panel']} נפתח לגמרי", menu["panel"])
    for i in range(count):
        tap_on(page, touch, menu["items"], i)
        poll(page, f"() => window.__taps.includes({i})",
             f"הנגיעה בכפתור {i + 1} מתוך {count} ב-{menu['panel']} הגיעה אליו")


@pytest.mark.parametrize("layout", list(LAYOUTS))
def test_every_quick_access_button_takes_a_tap(wired_mongo, admin_live_server, chromium_executable, layout):
    """כל הקיצורים: כל נגיעה מגיעה לכפתור. בפריסת ההמבורגר הקיצורים מחוץ לרשימה.

    ``wired_mongo`` כי בלי מסד העמוד עולה במסלול השגיאה שלו, בלי הרשאת אדמין.
    """
    viewport = LAYOUTS[layout]
    with layout_page(admin_live_server, chromium_executable, "/dashboard", viewport) as (page, touch):
        _check_layout(page, viewport)
        assert page.locator(ADMIN_ONLY_SHORTCUT).count() == 1, "הקיצור של האדמין לא רונדר"
        _tap_every_item(page, touch, QUICK)


@pytest.mark.parametrize("layout", list(LAYOUTS))
def test_every_effects_button_takes_a_tap(wired_mongo, admin_live_server, chromium_executable, layout):
    """כל האפקטים: כל נגיעה מגיעה לכפתור. בפריסת ההמבורגר השרביט בתוך הרשימה."""
    viewport = LAYOUTS[layout]
    with layout_page(admin_live_server, chromium_executable, "/dashboard", viewport) as (page, touch):
        _check_layout(page, viewport)
        if viewport is HAMBURGER:
            _open_hamburger(page, touch)
        _tap_every_item(page, touch, EFFECTS)


@pytest.fixture
def code_file_id(wired_mongo):
    """``wired_mongo`` מתחיל ממסד ריק בכל בדיקה, ולכן אין כאן ניקוי."""
    oid = ObjectId()
    wired_mongo.get_db().code_snippets.insert_one({
        "_id": oid, "user_id": USER_ID, "file_name": "module.py",
        "code": "\n".join(f"value_{i} = {i}" for i in range(1, 80)) + "\n",
        "programming_language": "python", "version": 1, "is_active": True,
    })
    return str(oid)


def test_buttons_floating_over_the_bar_still_take_taps_after_a_menu_closes(
        code_file_id, admin_live_server, chromium_executable):
    """שומר: אחרי שתפריט נסגר, 🔖 וכותרת פאנל הסימניות לחיצים בראש עמוד קובץ.

    שניהם יושבים בתוך ``.main-content`` ועולים על הסרגל בראש העמוד. סרגל שמורם לתמיד
    מסתיר אותם — נמדד: הנגיעה הגיעה ל-``.nav-content``. התפריט נפתח ונסגר קודם, כדי
    שהשומר יתפוס גם סרגל שעולה בפתיחה ולא יורד בסגירה.
    """
    with layout_page(admin_live_server, chromium_executable, f"/file/{code_file_id}", TABLET) as (page, touch):
        tap_on(page, touch, QUICK["toggle"])
        poll(page, PANEL_OPEN_JS, "הקיצורים נפתחו", QUICK["panel"])
        tap_on(page, touch, QUICK["toggle"])
        poll(page, "() => !document.querySelector('#quickAccessDropdown').classList.contains('active')",
             "הקיצורים נסגרו")

        tap_on(page, touch, "#toggleBookmarksBtn")
        poll(page, "() => document.getElementById('bookmarksPanel').classList.contains('open')",
             "הנגיעה ב-🔖 פתחה את פאנל הסימניות")

        page.evaluate("""() => {
          window.__infoTaps = 0;
          document.getElementById('bookmarksInfoBtn').addEventListener('click', (ev) => {
            ev.preventDefault(); ev.stopImmediatePropagation(); window.__infoTaps += 1;
          }, true);
        }""")
        tap_on(page, touch, "#bookmarksInfoBtn")
        poll(page, "() => window.__infoTaps === 1", "הנגיעה הגיעה לכפתור ההסבר שבכותרת הפאנל")
