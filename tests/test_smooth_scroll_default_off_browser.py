"""הגלילה החלקה כבויה כברירת מחדל — נמדד בדפדפן אמיתי, לא מתוך הקוד.

``smooth-scroll.js`` נטען מ-``base.html`` בכל עמוד. כשהוא פעיל הוא רושם
מאזין קליק על כל ``a[href^="#"]``, מבטל את התנהגות הדפדפן וגולל בעצמו —
**בלי לכתוב את העוגן לכתובת**. לכן שום קישור עוגן באפליקציה לא עדכן את
``location.hash``: אין Back, ``:target`` לא נדלק, ו-``hashchange`` לא ירה.

ההחלטה: המנגנון כבוי כברירת מחדל, ההעדפה השמורה כבר לא מדליקה אותו,
והכרטיס ירד מההגדרות. הטסטים כאן מוכיחים את שלושת הדברים על עמודים
אמיתיים, ואת הרביעי — שקישור עוגן חזר לעבוד כמו קישור עוגן.

הטסט מדולג בשקט כשאין Chromium. הדפוס לקוח מ-``test_profiler_copy_report_browser.py``;
הרמת השרת ואיתור Chromium מגיעים מהפיקסצ'רים המשותפים ב-``tests/conftest.py``;
pytest מוצא אותם לבד, בלי ייבוא בין קבצי טסט.
"""

from __future__ import annotations


import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402


@pytest.fixture(scope="module")
def browser(chromium_executable):
    executable = chromium_executable
    with sync_playwright() as pw:
        try:
            b = (
                pw.chromium.launch(executable_path=executable)
                if executable
                else pw.chromium.launch()
            )
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"אין Chromium זמין: {exc}")
        with b:
            yield b


@pytest.fixture
def open_page(browser, admin_live_server):
    """פותח עמוד בקונטקסט **חדש** לכל טסט, עם ה-session של האדמין.

    קונטקסט חדש = ``localStorage`` ריק. זה מהותי: טסט אחד זורע העדפה
    שמורה, וטסט אחר חייב להתחיל בלי שום העדפה.
    ``init_script`` רץ **לפני** כל סקריפט של העמוד — כך זורעים
    ``localStorage`` כפי שמשתמש ותיק היה מגיע עם ההעדפה כבר שמורה.
    """
    base_url = admin_live_server.base_url
    session_cookie = admin_live_server.session_cookie
    opened = []

    def _open(path, *, init_script=None):
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        opened.append(context)
        context.add_cookies([{
            "name": "session", "value": session_cookie,
            "domain": "127.0.0.1", "path": "/",
        }])
        page = context.new_page()
        page.add_init_script(
            "try{localStorage.setItem('welcomeModalSeen','1');"
            "localStorage.setItem('onboarding_completed','1');}catch(e){}"
        )
        if init_script:
            page.add_init_script(init_script)
        response = page.goto(f"{base_url}{path}", wait_until="domcontentloaded")
        page.wait_for_timeout(300)
        page.evaluate(
            "document.querySelectorAll('.welcome-modal, .welcome-modal__backdrop, #welcomeModal')"
            ".forEach(e => e.remove())"
        )
        return page, response

    yield _open
    for context in opened:
        context.close()


def _smooth_scroll_enabled(page):
    """קורא את מצב המנגנון אחרי שהסקריפט (``defer``) סיים לרוץ."""
    page.wait_for_function("() => window.smoothScroll !== undefined", timeout=5000)
    return page.evaluate("() => Boolean(window.smoothScroll.config.enabled)")


def test_smooth_scroll_is_off_by_default(open_page):
    """בלי שום העדפה שמורה — כבוי.

    בכרומיום של Playwright ``prefers-reduced-motion`` הוא ``no-preference``,
    ולכן על הקוד הישן (``enabled: !reduce``) הטסט נופל.
    """
    page, _ = open_page("/admin/profiler")
    assert _smooth_scroll_enabled(page) is False, "הגלילה החלקה דולקת כברירת מחדל"


def test_a_saved_preference_cannot_turn_it_back_on(open_page):
    """משתמש שהדליק את הכרטיס בעבר מחזיק ``enabled:true`` ב-localStorage.

    "כבוי כברירת מחדל" שנכון רק למשתמש חדש אינו כבוי: ההעדפה הישנה הייתה
    מחיה את הבאג בדיוק אצל מי שכבר נתקל בו.
    """
    # ``duration: 250`` ולא 400: 400 היא ברירת המחדל, ואיתה הטסט לא היה
    # מבחין אם ערכי הכוונון נזרקו יחד עם ``enabled``. 250 בתוך הטווח
    # ש-``normalizeConfig`` מקבל (0–2000).
    page, _ = open_page(
        "/admin/profiler",
        init_script="localStorage.setItem('smoothScrollPrefs', JSON.stringify({enabled: true, duration: 250}))",
    )
    assert _smooth_scroll_enabled(page) is False, "העדפה שמורה הדליקה את הגלילה החלקה"
    duration = page.evaluate("() => window.smoothScroll.config.duration")
    assert duration == 250, f"ערכי הכוונון השמורים נזרקו יחד עם enabled: duration={duration!r}"


def test_an_anchor_link_updates_the_url_again(open_page):
    """קישור עוגן חוזר להתנהג כקישור עוגן: ``location.hash`` מתעדכן.

    בעמוד הזה אין קישור עוגן, ולכן הטסט **מוסיף** אחד ל-DOM. זו תוספת של
    קלט ולא של מנגנון: המאזין הגלובלי האמיתי, על עמוד אמיתי, הוא מה שנבדק.
    על הקוד הישן המאזין בולע את הקליק והכתובת נשארת בלי עוגן.
    """
    page, _ = open_page("/admin/profiler")
    page.wait_for_function("() => window.smoothScroll !== undefined", timeout=5000)
    assert page.query_selector("#slow-queries-table") is not None, "היעד לעוגן לא קיים בעמוד"
    page.evaluate(
        "() => { const a = document.createElement('a');"
        " a.id = 'probe-anchor'; a.href = '#slow-queries-table'; a.textContent = 'probe';"
        " document.body.prepend(a); }"
    )
    page.click("#probe-anchor")
    assert page.url.endswith("#slow-queries-table"), f"העוגן נבלע: {page.url}"


def test_the_settings_page_has_no_smooth_scroll_card(open_page):
    """הכרטיס ירד. הבדיקה מאשרת קודם שעמוד ההגדרות **באמת** רונדר —
    אחרת "אין כרטיס" היה עובר גם על עמוד שגיאה ריק."""
    page, response = open_page("/settings")
    assert response is not None and response.status == 200, (
        f"עמוד ההגדרות לא עלה: {getattr(response, 'status', None)}"
    )
    assert page.query_selector("#noteFontsMsg") is not None, "זה לא עמוד ההגדרות המוכר"
    assert page.query_selector("#smoothScrollSettingsCard") is None, "כרטיס הגלילה החלקה עדיין בהגדרות"
