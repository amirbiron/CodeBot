"""ערכת נושא שנשמרה בטאב אחד חלה מיד בטאב אחר של האתר — נמדד בדפדפן אמיתי.

ההגדרות ובוחר הערכות כותבים ``user_theme`` ו-``dark_mode_preference`` ל-localStorage.
הדפדפן מודיע על כתיבה כזאת (אירוע ``storage``) לכל **שאר** הטאבים של אותו
מקור, והמאזין ``initThemeCrossTabSync`` ב-``base.html`` מחיל אצלם את הערכה.

**למה זה כאן:** המאזין ישב עד היום בתוך אשף הערכות של ה-Onboarding, ולא היה
עליו טסט. בהסרת ה-Onboarding הוא עבר לבלוק משלו, והטסט הזה מוודא שהוא לא
נמחק יחד עם האשף — מחיקה כזאת שוברת את הסנכרון לכל המשתמשים, בשקט.

שני הטאבים חולקים קונטקסט אחד של Playwright, כלומר אחסון אחד, כמו שני טאבים
באותו דפדפן. הטסט מדולג בשקט כשאין Chromium. הרמת השרת ואיתור Chromium מגיעים
מהפיקסצ'רים המשותפים ב-``tests/conftest.py``.
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
def two_tabs(browser, admin_live_server):
    """שני טאבים של אותו משתמש, באותו קונטקסט ולכן עם אותו localStorage."""
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    context.add_cookies([{
        "name": "session", "value": admin_live_server.session_cookie,
        "domain": "127.0.0.1", "path": "/",
    }])
    tabs = []
    for _ in range(2):
        page = context.new_page()
        page.goto(f"{admin_live_server.base_url}/privacy", wait_until="load")
        tabs.append(page)
    yield tabs
    context.close()


def _theme(page) -> str | None:
    return page.evaluate("() => document.documentElement.getAttribute('data-theme')")


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("user_theme", "nebula", "nebula"),
        ("dark_mode_preference", "dim", "dim"),
        ("dark_mode_preference", "light", "classic"),
    ],
)
def test_a_theme_saved_in_one_tab_applies_in_the_other(two_tabs, key, value, expected):
    writer, reader = two_tabs
    # הטאב הקורא מתחיל בערכה אחרת מהצפויה, אחרת הטסט היה עובר גם בלי מאזין.
    start = "ocean"
    reader.evaluate("t => document.documentElement.setAttribute('data-theme', t)", start)
    assert _theme(reader) == start

    writer.evaluate("([k, v]) => localStorage.setItem(k, v)", [key, value])

    reader.wait_for_function(
        "t => document.documentElement.getAttribute('data-theme') === t", arg=expected, timeout=5000,
    )
    assert _theme(reader) == expected


def test_an_unknown_theme_from_another_tab_is_ignored(two_tabs):
    """ערך שאינו ערכה מוכרת לא מגיע ל-``data-theme`` — רשימת ההיתר נשמרה במעבר."""
    writer, reader = two_tabs
    reader.evaluate("() => document.documentElement.setAttribute('data-theme', 'ocean')")
    # כל ערך ש-``data-theme`` מקבל מעכשיו נרשם, כדי לתפוס גם החלה רגעית.
    reader.evaluate("""() => {
        window.__seenThemes = [];
        new MutationObserver(() => {
            window.__seenThemes.push(document.documentElement.getAttribute('data-theme'));
        }).observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme']});
    }""")

    writer.evaluate("() => localStorage.setItem('user_theme', 'no-such-theme')")
    # אירועי ``storage`` מגיעים לפי סדר הכתיבה: כשהכתיבה התקינה הזו כבר חלה,
    # הכתיבה הקודמת כבר טופלה — כלומר ההמתנה הספיקה כדי שהיא הייתה נרשמת.
    writer.evaluate("() => localStorage.setItem('dark_mode_preference', 'dim')")
    reader.wait_for_function(
        "() => document.documentElement.getAttribute('data-theme') === 'dim'", timeout=5000,
    )
    seen = reader.evaluate("() => window.__seenThemes")
    assert "no-such-theme" not in seen, f"ערך לא מוכר הוחל: {seen}"
    assert seen[-1] == "dim", seen
