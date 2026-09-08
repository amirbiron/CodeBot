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
import time

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

        with browser, browser.new_context(
            viewport={"width": 1280, "height": 900},
            # בלי ההרשאות האלה ``clipboard.readText`` נחסם, וטסט הדוח היה
            # בודק מחרוזת ריקה במקום את מה שבאמת הודבק.
            permissions=["clipboard-read", "clipboard-write"],
        ) as context:
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


def _copy_report(page, timeout_ms=5000):
    """מעתיק את הדוח ומחזיר את **תוכן הלוח בפועל**.

    ``navigator.clipboard.writeText()`` אסינכרוני, ולכן המתנה קבועה היא טסט
    שנופל מהסיבה הלא נכונה: על מכונה עמוסה הכתיבה עוד לא נחתה, ``readText``
    מחזיר ריק, והכישלון נראה כאילו הדוח שגוי. פולינג עד שיש תוכן.
    """
    page.click("button:has-text('העתק דוח ל-AI')")
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        text = page.evaluate("navigator.clipboard.readText()")
        if text:
            return text
        page.wait_for_timeout(50)
    raise AssertionError("הלוח נשאר ריק — ההעתקה לא קרתה כלל")


def test_the_request_declares_the_encoding_of_what_it_carries(dashboard):
    """הניב מוצהר בבקשה. בלי זה השרת מפרש ``{"$date": …}`` כמילון ולא כתאריך."""
    page, sent = dashboard
    _row(page, "with-values").query_selector("button[data-analyze-with='raw']").click()
    page.wait_for_selector("#analysis-results", state="visible", timeout=10000)

    assert sent[-1]["encoding"] == "extended_json"

    _row(page, "withheld").query_selector("button[data-analyze-with='shape']").click()
    page.wait_for_selector("#analysis-results", state="visible", timeout=10000)

    assert sent[-1]["encoding"] == "json", (
        "השלד חייב להישאר בניב הרגיל: תחת Extended JSON ה-``<value>`` שבתוך "
        "``$options`` הופך ל-Regex עם דגלים אקראיים במקום לשגיאה רועשת"
    )


def test_the_report_says_the_analysis_ran_on_real_values(dashboard):
    """שתי עובדות נפרדות, ושתיהן חייבות להיאמר.

    **הדוח עצמו מנורמל תמיד** — נבדק בקוד בשלושת חלקיו: צורת השאילתה נלקחת
    מ-``explain.query_shape`` שהשרת מנרמל, תוכנית הביצוע עוברת ב-``describeStage``
    שמדפיס ``stage``/``index_name``/``direction`` בלבד ולעולם לא ``filter_condition``,
    והסטטיסטיקות הן מספרים. לכן ההצהרה על פרטיות נכונה גם כאן.

    **מה שכן שונה הוא על מה ה-explain רץ.** בלי לומר את זה, מי שקורא "הערכים
    מנורמלים" עלול להסיק שגם המדידה נעשתה על ``<value>`` ולפסול מספרים תקפים.
    """
    page, _sent = dashboard
    _row(page, "with-values").query_selector("button[data-analyze-with='raw']").click()
    page.wait_for_selector("#analysis-results", state="visible", timeout=10000)
    report = _copy_report(page)

    assert "אין בדוח נתונים אישיים" in report, "הדוח באמת מנורמל — ההצהרה נכונה גם כאן"
    assert "הניתוח עצמו רץ על הערכים האמיתיים" in report, (
        "בלי זה המספרים ייקראו כאילו נמדדו על שלד שאינו מתאים לאף מסמך"
    )


def test_the_report_does_not_claim_a_real_run_when_it_was_the_skeleton(dashboard):
    """הכיוון השני: על השלד אסור להבטיח מדידה על ערכים אמיתיים.

    בלי הטסט הזה "תיקון" שפשוט מוסיף את המשפט תמיד היה עובר — ואז דוח על
    שלד היה מבטיח מספרים אמיתיים, טעות הפוכה ולא פחות גרועה.
    """
    page, _sent = dashboard
    _row(page, "withheld").query_selector("button[data-analyze-with='shape']").click()
    page.wait_for_selector("#analysis-results", state="visible", timeout=10000)
    report = _copy_report(page)

    assert "אין בדוח נתונים אישיים" in report
    assert "הניתוח עצמו רץ על הערכים האמיתיים" not in report


def test_the_encoding_does_not_leak_into_the_next_analysis(dashboard):
    """הניב אינו מצב גלובלי — הוא נאמר על ידי מי שיודע, ולא נותר מהפעם הקודמת.

    כמשתנה ברמת המודול, רק ``analyzeQueryFromRow`` כתב אליו — ולכן ניתוח של
    שורה גולמית הדליק ``extended_json``, ואז הכפתור הידני (או לחיצה על המלצה,
    דרך ``analyzeQueryById``) שלח את מה שבטופס עם אותו דגל.

    זה לא היה תיאורטי אלא בדיוק התשובה השגויה השקטה שהמנגנון קיים למנוע:
    ``json_util.loads`` על ``{"$options": "<value>"}`` מחזיר ``Regex`` עם דגלים
    אקראיים — רץ, ומחזיר אפס תוצאות — במקום השגיאה הרועשת שמונגו נותנת.
    """
    page, sent = dashboard
    _row(page, "with-values").query_selector("button[data-analyze-with='raw']").click()
    page.wait_for_selector("#analysis-results", state="visible", timeout=10000)
    assert sent[-1]["encoding"] == "extended_json", "המסלול שכן יודע חייב להצהיר"

    page.click('button[onclick="analyzeQuery()"]')
    page.wait_for_selector("#analysis-results", state="visible", timeout=10000)

    assert sent[-1]["encoding"] == "json", (
        "הניב דלף מהניתוח הקודם — מסלול שלא הצהיר חייב לקבל את ברירת המחדל הבטוחה"
    )
