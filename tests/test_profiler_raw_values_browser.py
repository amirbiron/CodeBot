"""כפתור 🔍 בדשבורד הפרופיילר שולח את הערכים האמיתיים כשהם קיימים.

הרשומה יכולה לשאת ``query_raw`` (ערכים אמיתיים, רק לשאילתות שזוהו בוודאות
כשל משתמש מורשה) או ``raw_withheld_reason`` (למה אין). מה שהכפתור שולח
ל-``/api/profiler/recommendations`` מורכב ב-JS בדפדפן, ולכן זה נבדק
בדפדפן אמיתי: מיירטים את הבקשה ובודקים את הגוף שלה.

הרמת השרת ואיתור Chromium מגיעים מ-``admin_live_server`` ו-``chromium_executable``
שב-``tests/conftest.py``; pytest מוצא אותם לבד, בלי ייבוא בין קבצי טסט.
מדולג בשקט כשאין Chromium.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

ME = 6865105071
RAW_QUERY = {"user_id": ME, "programming_language": "python"}

#: שלוש רשומות: אחת עם ערכים אמיתיים, אחת שנמנעה בגלל שדה לא מוכר,
#: ואחת ``update`` שנמנעה — כדי שהשורה בלי כפתור ניתוח תיבדק גם היא.
SLOW_QUERIES = {
    "status": "success",
    "data": [
        {
            "query_id": "with-values",
            "collection": "code_snippets",
            "operation": "find",
            "query_shape": {"user_id": "<value>", "programming_language": "<value>"},
            "query_raw": RAW_QUERY,
            "raw_withheld_reason": None,
            "execution_time_ms": 1500.0,
            "timestamp": "2026-09-06T00:00:00",
        },
        {
            "query_id": "withheld",
            "collection": "code_snippets",
            "operation": "find",
            "query_shape": {"user_id": "<value>", "owner_id": "<value>"},
            "query_raw": None,
            "raw_withheld_reason": "unknown_field:owner_id",
            "execution_time_ms": 1200.0,
            "timestamp": "2026-09-06T00:00:00",
        },
        {
            "query_id": "withheld-update",
            "collection": "code_snippets",
            "operation": "update",
            "query_shape": {"user_id": "<value>", "owner_id": "<value>"},
            "query_raw": None,
            "raw_withheld_reason": "unknown_field:owner_id",
            "execution_time_ms": 1100.0,
            "timestamp": "2026-09-06T00:00:00",
        },
    ],
}
SLOW_QUERIES["count"] = len(SLOW_QUERIES["data"])

#: תשובת ניתוח מינימלית — הטסט בודק את הבקשה, לא את הרינדור.
ANALYSIS = {
    "status": "success",
    "data": {
        "explain": {
            "query_id": "q", "collection": "code_snippets", "query_shape": {"user_id": "<value>"},
            "winning_plan": {"stage": "COLLSCAN", "index_name": None, "direction": "forward",
                             "filter_condition": None, "input_stage": None, "children": []},
            "rejected_plans": [], "stats": None, "timestamp": "2026-09-06T00:00:00",
        },
        "recommendations": [],
    },
}


@pytest.fixture
def dashboard(admin_live_server, chromium_executable, stub_profiler_api):
    """הדשבורד עם רשימת השאילתות המזויפת, ורשימת גופי הבקשות שהכפתור שלח."""
    base_url = admin_live_server.base_url
    session_cookie = admin_live_server.session_cookie
    executable = chromium_executable
    with sync_playwright() as pw:
        try:
            browser = (
                pw.chromium.launch(executable_path=executable) if executable else pw.chromium.launch()
            )
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"אין Chromium זמין: {exc}")

        with browser, browser.new_context(viewport={"width": 1280, "height": 900}) as context:
            context.add_cookies([{
                "name": "session", "value": session_cookie, "domain": "127.0.0.1", "path": "/",
            }])
            page = context.new_page()
            page.add_init_script(
                "try{localStorage.setItem('welcomeModalSeen','1');"
                "localStorage.setItem('onboarding_completed','1');}catch(e){}"
            )
            # היירוט הכללי **ראשון**; הראוטים הספציפיים שאחריו מנצחים אותו
            # (playwright מכניס כל ראוט חדש לראש הרשימה).
            stub_profiler_api(page)

            sent = []
            page.route(
                "**/api/profiler/slow-queries*",
                lambda route: route.fulfill(
                    status=200, content_type="application/json", body=json.dumps(SLOW_QUERIES)
                ),
            )

            def _capture(route):
                sent.append(route.request.post_data_json)
                route.fulfill(status=200, content_type="application/json", body=json.dumps(ANALYSIS))

            page.route("**/api/profiler/recommendations", _capture)
            page.goto(f"{base_url}/admin/profiler", wait_until="domcontentloaded")
            page.wait_for_selector("#slow-queries-table tbody tr", timeout=10000)
            page.evaluate(
                "document.querySelectorAll('.welcome-modal, .welcome-modal__backdrop, #welcomeModal')"
                ".forEach(e => e.remove())"
            )
            yield page, sent


def _row(page, query_id):
    rows = page.query_selector_all("#slow-queries-table tbody tr")
    for row in rows:
        if row.get_attribute("data-query-id") == query_id:
            return row
    raise AssertionError(f"אין שורה עם data-query-id={query_id!r}; יש {len(rows)} שורות")


def test_no_profiler_request_ever_reaches_the_real_server(dashboard, admin_live_server):
    """בידוד נבדק בספירה בצד השרת, לא בהיעדר שגיאה בדפדפן.

    כל כשל רשת ב-JS של הדשבורד נבלע ב-``catch``, ולכן "הטסט לא נפל" אינו
    ראיה לכלום. כאן סופרים בעטיפת ה-WSGI מה באמת הגיע.

    **הטסט נשען על הטעינה הראשונית ולא על ה-``setInterval``.** הדשבורד מרענן
    את הסיכום כל 30 שניות, וטסט קצר לא היה מגיע לזה — כלומר היה עובר גם בלי
    היירוט, מהסיבה הלא נכונה. ``DOMContentLoaded`` לבדו יורה גם
    ``loadSummary()`` וגם ``refreshSlowQueries()``, ולכן זה מספיק כדי שהסרת
    היירוט הכללי תפיל את הטסט.
    """
    page, _ = dashboard
    page.wait_for_selector("#slow-queries-table tbody tr", timeout=10000)

    assert admin_live_server.profiler_hits == [], (
        f"בקשות פרופיילר הגיעו לשרת האמיתי: {admin_live_server.profiler_hits}"
    )


def test_the_button_sends_the_real_values_when_the_record_carries_them(dashboard):
    page, sent = dashboard
    button = _row(page, "with-values").query_selector("button[data-analyze-with='raw']")
    assert button is not None, "לרשומה עם ערכים אמיתיים אין כפתור שמסומן ככזה"

    button.click()
    page.wait_for_selector("#analysis-results", state="visible", timeout=10000)

    assert sent, "הכפתור לא שלח בקשת ניתוח"
    assert sent[-1]["query"] == RAW_QUERY, "הניתוח נשלח על השלד במקום על הערכים האמיתיים"


def test_a_withheld_record_says_why_and_analyzes_the_skeleton(dashboard):
    page, sent = dashboard
    row = _row(page, "withheld")
    note = row.query_selector("[data-testid='raw-withheld']")
    assert note is not None, "רשומה שנמנעה חייבת להסביר למה — ברירה בטוחה שקטה היא באג"
    assert "owner_id" in (note.text_content() or ""), "הסיבה חייבת לנקוב בשם השדה"

    button = row.query_selector("button[data-analyze-with='shape']")
    assert button is not None
    button.click()
    page.wait_for_selector("#analysis-results", state="visible", timeout=10000)

    assert sent[-1]["query"] == {"user_id": "<value>", "owner_id": "<value>"}


def test_a_row_without_an_analyze_button_still_says_why_the_values_are_missing(dashboard):
    """``update``/``delete`` נשמרים גם הם, עוברים את אותה החלטת ערכים, ואין להם כפתור.

    ה-explain אינו מנתח אותם, ולכן אין בשורה שום רמז אחר — אם הסיבה לא מוצגת
    שם, האדמין רואה מקף ותו לא, ולא יודע שהערכים נמנעו ולמה. הסיבה עצמה אינה
    ערך רגיש; היא ההסבר לכך שאין ערך.
    """
    page, _sent = dashboard
    row = _row(page, "withheld-update")

    assert row.query_selector("button[data-analyze-with]") is None, "ל-update אין מה לנתח"

    note = row.query_selector("[data-testid='raw-withheld']")
    assert note is not None, "שורה בלי כפתור עדיין חייבת להסביר למה אין ערכים אמיתיים"
    assert "owner_id" in (note.text_content() or ""), "הסיבה חייבת לנקוב בשם השדה"
