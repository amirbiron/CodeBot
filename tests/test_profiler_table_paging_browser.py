"""מיון, "טען עוד" ומקטע הדפוסים בדשבורד הפרופיילר — בדפדפן אמיתי.

בדיקת שרת מאמתת שה-HTML נוצר. היא **אינה** יכולה לאמת שלחיצה על כותרת
שולחת ``sort`` לשרת, שהכפתור **מוסיף** שורות ולא מחליף אותן, או שהכרטיס
באמת מגיע למקטע — כל אלה קורים ב-JS. לכן כאן מיירטים את הבקשות ובודקים
את הגוף שלהן ואת מה שעל המסך.

מדולג בשקט כשאין Chromium. הרמת השרת ואיתור הדפדפן מגיעים מ-``conftest.py``.
"""

from __future__ import annotations

import json
import time
from urllib.parse import parse_qs, urlsplit

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

SUMMARY = {
    "status": "success",
    "data": {
        "total_slow_queries": 72,
        "avg_execution_time_ms": 1234.5,
        "collections_affected": ["code_snippets"],
        "unique_patterns": 16,
    },
}

PATTERNS = {
    "status": "success",
    "count": 2,
    "total": 16,
    "data": [
        {
            "query_id": "p1", "collection": "code_snippets", "operation": "find",
            "count": 40, "avg_time_ms": 1500.0, "max_time_ms": 2200.0,
            "query_shape": {"user_id": "<value>"}, "last_seen": "2026-09-07T10:00:00",
        },
        {
            "query_id": "p2", "collection": "note_reminders", "operation": "aggregate",
            "count": 5, "avg_time_ms": 1100.0, "max_time_ms": 1200.0,
            "query_shape": {"pipeline": []}, "last_seen": "2026-09-07T09:00:00",
        },
    ],
}


def _row(index, *, cursor_page):
    """שורת שאילתה איטית. ``cursor_page`` מבדיל בין הדף הראשון לשני."""
    return {
        "query_id": f"{'b' if cursor_page else 'a'}{index}",
        "collection": "code_snippets",
        "operation": "find",
        "query_shape": {"user_id": "<value>"},
        "query_raw": None,
        "raw_withheld_reason": None,
        "execution_time_ms": 1500.0 - index,
        "timestamp": "2026-09-07T10:00:00",
    }


@pytest.fixture
def dashboard(admin_live_server, chromium_executable, stub_profiler_api):
    """הדשבורד, ורשימת ה-query strings שהוא שלח ל-``/api/profiler/slow-queries``."""
    base_url = admin_live_server.base_url
    with sync_playwright() as pw:
        try:
            browser = (
                pw.chromium.launch(executable_path=chromium_executable)
                if chromium_executable else pw.chromium.launch()
            )
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"אין Chromium זמין: {exc}")

        with browser, browser.new_context(viewport={"width": 1280, "height": 900}) as context:
            context.add_cookies([{
                "name": "session", "value": admin_live_server.session_cookie,
                "domain": "127.0.0.1", "path": "/",
            }])
            page = context.new_page()
            page.add_init_script(
                "try{localStorage.setItem('welcomeModalSeen','1');"
                "localStorage.setItem('onboarding_completed','1');}catch(e){}"
            )
            stub_profiler_api(page)

            asked = []

            def _slow_queries(route):
                query = parse_qs(urlsplit(route.request.url).query)
                asked.append(query)
                first_page = "cursor" not in query
                body = {
                    "status": "success",
                    "data": [_row(i, cursor_page=not first_page) for i in range(3)],
                    "count": 3,
                    "total": 6,
                    # דף ראשון מחזיר קורסור, השני לא — כך הכפתור נעלם בסוף.
                    "next_cursor": "CURSOR-1" if first_page else None,
                }
                route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

            page.route("**/api/profiler/summary*", lambda r: r.fulfill(
                status=200, content_type="application/json", body=json.dumps(SUMMARY)))
            page.route("**/api/profiler/patterns*", lambda r: r.fulfill(
                status=200, content_type="application/json", body=json.dumps(PATTERNS)))
            page.route("**/api/profiler/slow-queries*", _slow_queries)

            page.goto(f"{base_url}/admin/profiler", wait_until="domcontentloaded")
            page.wait_for_selector("#slow-queries-table tbody tr", timeout=10000)
            page.evaluate(
                "document.querySelectorAll('.welcome-modal, .welcome-modal__backdrop, #welcomeModal')"
                ".forEach(e => e.remove())"
            )
            yield page, asked


class _Gate:
    """שולט מתי כל בקשת ``slow-queries`` נענית — כך המרוץ הופך דטרמיניסטי.

    בלי זה אי אפשר לבדוק תנאי מרוץ בדפדפן: הבקשות מסתיימות בסדר שרירותי,
    והטסט או עובר תמיד או נכשל אקראית. כאן הבקשה **מוחזקת פתוחה** (לא
    ``fulfill``), מבצעים את הפעולה השנייה, ורק אז משחררים — כלומר התגובה
    הישנה מגיעה אחרונה, בדיוק המקרה שהמזהה דור אמור לזרוק.
    """

    def __init__(self):
        self.asked = []
        self.held = []
        self.auto = True  # טעינת העמוד נענית מיד; אחריה עוברים לשליטה ידנית

    def handle(self, route):
        query = parse_qs(urlsplit(route.request.url).query)
        self.asked.append(query)
        if self.auto:
            self.release(route, tag="load")
        else:
            self.held.append(route)

    @staticmethod
    def release(route, *, tag, next_cursor="CURSOR-1", status=200):
        if status != 200:
            route.fulfill(status=status, content_type="application/json",
                          body=json.dumps({"status": "error", "message": "internal_error"}))
            return
        body = {
            "status": "success",
            # ``query_id`` נושא את התג, כך שאפשר לראות **איזו** תגובה ניצחה.
            "data": [dict(_row(i, cursor_page=False), query_id=f"{tag}-{i}") for i in range(3)],
            "count": 3,
            "total": 6,
            "next_cursor": next_cursor,
        }
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))


@pytest.fixture
def racing_dashboard(admin_live_server, chromium_executable, stub_profiler_api):
    """אותו דשבורד, אבל עם ``_Gate`` שמחזיק את הבקשות."""
    base_url = admin_live_server.base_url
    gate = _Gate()
    with sync_playwright() as pw:
        try:
            browser = (
                pw.chromium.launch(executable_path=chromium_executable)
                if chromium_executable else pw.chromium.launch()
            )
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"אין Chromium זמין: {exc}")

        with browser, browser.new_context(viewport={"width": 1280, "height": 900}) as context:
            context.add_cookies([{
                "name": "session", "value": admin_live_server.session_cookie,
                "domain": "127.0.0.1", "path": "/",
            }])
            page = context.new_page()
            page.add_init_script(
                "try{localStorage.setItem('welcomeModalSeen','1');"
                "localStorage.setItem('onboarding_completed','1');}catch(e){}"
            )
            stub_profiler_api(page)

            page.route("**/api/profiler/summary*", lambda r: r.fulfill(
                status=200, content_type="application/json", body=json.dumps(SUMMARY)))
            page.route("**/api/profiler/patterns*", lambda r: r.fulfill(
                status=200, content_type="application/json", body=json.dumps(PATTERNS)))
            page.route("**/api/profiler/slow-queries*", gate.handle)

            page.goto(f"{base_url}/admin/profiler", wait_until="domcontentloaded")
            page.wait_for_selector("#slow-queries-table tbody tr", timeout=10000)
            page.evaluate(
                "document.querySelectorAll('.welcome-modal, .welcome-modal__backdrop, #welcomeModal')"
                ".forEach(e => e.remove())"
            )
            gate.auto = False
            yield page, gate


def _body_rows(page, table_id):
    return page.query_selector_all(f"#{table_id} tbody tr")


def test_the_header_says_how_many_of_how_many(dashboard):
    """מה שנחתך נאמר בקול. שני המספרים סופרים את אותו חלון."""
    page, _asked = dashboard

    text = page.inner_text("#slow-queries-shown")

    assert "3" in text and "6" in text, f"הכותרת לא אומרת כמה מתוך כמה: {text!r}"


def test_load_more_appends_and_does_not_replace(dashboard):
    """הכפתור מוסיף שורות. אם הוא מחליף — הוא נראה כאילו אינו עושה דבר."""
    page, asked = dashboard
    assert len(_body_rows(page, "slow-queries-table")) == 3

    page.click("#load-more-slow-queries")
    # ``wait_for_selector`` ולא ``wait_for_function``: ה-CSP של העמוד אוסר
    # ``unsafe-eval``, ופרדיקט כמחרוזת נחסם שם. בורר CSS עובד תמיד.
    page.wait_for_selector("#slow-queries-table tbody tr:nth-child(4)", timeout=10000)

    assert len(_body_rows(page, "slow-queries-table")) == 6, "הדף השני החליף את הראשון"
    assert asked[-1]["cursor"] == ["CURSOR-1"], "הקורסור לא נשלח, כלומר זו אותה בקשה שוב"


def test_the_button_disappears_when_there_is_no_next_page(dashboard):
    page, _asked = dashboard
    page.click("#load-more-slow-queries")
    # ``wait_for_selector`` ולא ``wait_for_function``: ה-CSP של העמוד אוסר
    # ``unsafe-eval``, ופרדיקט כמחרוזת נחסם שם. בורר CSS עובד תמיד.
    page.wait_for_selector("#slow-queries-table tbody tr:nth-child(4)", timeout=10000)

    assert page.query_selector("#load-more-slow-queries").is_hidden(), (
        "הכפתור נשאר גלוי בלי דף הבא — לחיצה עליו לא תעשה כלום"
    )


def test_clicking_a_header_sorts_on_the_server(dashboard):
    """**בשרת ולא בלקוח.** עם "טען עוד", מיון של מה שנטען בלבד הוא מיון שקרי."""
    page, asked = dashboard

    page.click("[data-testid='sort-timestamp']")
    page.wait_for_selector(
        "#slow-queries-table thead th[data-sort-field=timestamp][aria-sort]", timeout=10000
    )

    assert asked[-1]["sort"] == ["timestamp"], "המיון לא הגיע לשרת"
    assert asked[-1]["dir"] == ["desc"]
    assert "cursor" not in asked[-1], "שינוי מיון חייב לאפס את הקורסור — אחרת הוא נטבע למיון אחר"


def test_clicking_the_same_header_twice_flips_the_direction(dashboard):
    page, asked = dashboard

    page.click("[data-testid='sort-timestamp']")
    page.wait_for_selector(
        "#slow-queries-table thead th[data-sort-field=timestamp][aria-sort=descending]", timeout=10000
    )
    page.click("[data-testid='sort-timestamp']")
    page.wait_for_selector(
        "#slow-queries-table thead th[data-sort-field=timestamp][aria-sort=ascending]", timeout=10000
    )

    assert asked[-1]["dir"] == ["asc"]


def test_the_sorted_column_is_announced_to_screen_readers(dashboard):
    """``aria-sort`` על ה-``th``, ורק על זו שממוינת."""
    page, _asked = dashboard

    page.click("[data-testid='sort-collection']")
    page.wait_for_selector(
        "#slow-queries-table thead th[data-sort-field=collection][aria-sort=descending]", timeout=10000
    )

    marked = page.eval_on_selector_all(
        "#slow-queries-table thead th[aria-sort]", "els => els.map(e => e.dataset.sortField)"
    )
    assert marked == ["collection"], f"יותר מעמודה אחת מסומנת כממוינת: {marked}"


def test_the_headers_are_real_buttons(dashboard):
    """``<button>`` ולא ``th`` עם ``onclick``: Enter ו-Space מגיעים מהדפדפן."""
    page, _asked = dashboard

    tags = page.eval_on_selector_all(
        "#slow-queries-table thead .sort-header", "els => els.map(e => e.tagName)"
    )

    assert tags and set(tags) == {"BUTTON"}, f"כותרת מיון שאינה כפתור: {tags}"


def test_the_patterns_section_is_filled(dashboard):
    page, _asked = dashboard
    page.wait_for_selector("#query-patterns-table tbody tr", timeout=10000)

    rows = _body_rows(page, "query-patterns-table")
    assert len(rows) == 2
    assert "code_snippets" in rows[0].inner_text()
    assert "40" in rows[0].inner_text(), "מספר המופעים לא הגיע לטבלה"


def test_the_patterns_header_says_how_many_of_how_many(dashboard):
    """``$limit`` הוא חיתוך, ולכן הוא נאמר — בדיוק כמו בטבלת השאילתות."""
    page, _asked = dashboard
    page.wait_for_selector("#query-patterns-table tbody tr", timeout=10000)

    text = page.inner_text("#patterns-shown")

    assert "2" in text and "16" in text, f"החיתוך נעלם במקום להיאמר: {text!r}"


def test_the_patterns_card_is_a_real_link_to_the_section(dashboard):
    """קישור עוגן אמיתי, כמו כרטיס "שאילתות איטיות" — לא div עם מאזין."""
    page, _asked = dashboard

    card = page.query_selector('#summary-section a[href="#query-patterns"]')

    assert card is not None, "הכרטיס אינו קישור, ולכן מקלדת וקורא מסך לא מגיעים אליו"
    assert page.query_selector("#query-patterns") is not None, "יעד העוגן אינו קיים"


def _wait_for(condition, *, timeout=10.0, what=""):
    """המתנה על תנאי בצד פייתון. ``wait_for_function`` חסום כאן — ה-CSP של
    העמוד אוסר ``unsafe-eval``, ופרדיקט כמחרוזת נחסם שם."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError(f"פג הזמן בהמתנה ל: {what}")


class TestConcurrentRequestsDoNotOverwriteEachOther:
    """שתי בקשות במקביל — התגובה האיטית לא מנצחת."""

    def test_a_stale_response_does_not_overwrite_a_newer_one(self, racing_dashboard):
        """לחיצה על מיון אחד, ואז על אחר, והראשונה חוזרת **אחרי** השנייה.

        בלי מזהה דור, התגובה שמגיעה אחרונה כותבת גם את הטבלה וגם את
        ``slowQueryCursor`` — כלומר המסך מציג מיון שהמשתמש כבר עזב, והקורסור
        שנשמר שייך למיון ההוא. הלחיצה הבאה על "טען עוד" הייתה נדחית ב-400
        (``cursor_sort_mismatch``) או מחזירה שורות של מיון אחר.
        """
        page, gate = racing_dashboard

        page.click("[data-testid='sort-timestamp']")
        _wait_for(lambda: len(gate.held) == 1, what="הבקשה הראשונה יצאה")
        page.click("[data-testid='sort-collection']")
        _wait_for(lambda: len(gate.held) == 2, what="הבקשה השנייה יצאה")

        # ``query_id`` יושב ב-``data-query-id`` ולא בטקסט הנראה, ולכן הבדיקה
        # היא על התכונה. (הגרסה הראשונה של הטסט חיפשה אותו ב-``inner_text``
        # ונכשלה — כשל של הטסט, לא של הקוד.)
        def _shown():
            return page.eval_on_selector_all(
                "#slow-queries-table tbody tr", "els => els.map(e => e.dataset.queryId)"
            )

        # השנייה חוזרת ראשונה, והראשונה — הישנה — חוזרת אחריה.
        gate.release(gate.held[1], tag="newer")
        _wait_for(lambda: any(q.startswith("newer-") for q in _shown()),
                  what="התגובה החדשה הוצגה")
        gate.release(gate.held[0], tag="stale")

        # שהות קצרה כדי לתת לתגובה המיושנת הזדמנות אמיתית לכתוב על המסך.
        page.wait_for_timeout(400)
        shown = _shown()
        assert not any(q.startswith("stale-") for q in shown), f"התגובה המיושנת דרסה את החדשה: {shown}"
        assert all(q.startswith("newer-") for q in shown), shown

    def test_the_button_is_disabled_while_a_request_is_in_flight(self, racing_dashboard):
        """כפתור פעיל בזמן בקשה = אותו קורסור נשלח פעמיים, והשורות מוכפלות.

        הנטרול הוא מה שמונע את זה בשורש — כפתור מנוטרל אינו מפעיל את המאזין
        שלו כלל, ולכן אין צורך בשמירה נוספת ב-JS.
        """
        page, gate = racing_dashboard

        page.click("#load-more-slow-queries")
        _wait_for(lambda: len(gate.held) == 1, what="בקשת 'טען עוד' יצאה")

        assert page.query_selector("#load-more-slow-queries").is_disabled(), (
            "הכפתור פעיל בזמן שהבקשה באוויר — לחיצה נוספת תשלח את אותו קורסור שוב"
        )

        gate.release(gate.held[0], tag="page2")
        _wait_for(lambda: not page.query_selector("#load-more-slow-queries").is_disabled(),
                  what="הכפתור חזר לפעילות")

    def test_a_failed_request_gives_the_button_back(self, racing_dashboard):
        """**הכשל שגרוע מהמרוץ.**

        אם ההחזרה יושבת בסוף מסלול ההצלחה במקום ב-``finally``, בקשה שנכשלה
        משאירה את הכפתור מנוטרל לצמיתות — בלי שום דבר על המסך שמסביר למה,
        ובלי יציאה חוץ מרענון העמוד.
        """
        page, gate = racing_dashboard

        page.click("#load-more-slow-queries")
        _wait_for(lambda: len(gate.held) == 1, what="בקשת 'טען עוד' יצאה")
        gate.release(gate.held[0], tag="boom", status=500)

        _wait_for(lambda: not page.query_selector("#load-more-slow-queries").is_disabled(),
                  what="הכפתור חזר לפעילות אחרי כשל")
