"""עמוד האדמין של אינדקס התיעוד — בכרומיום אמיתי, תחת ה-CSP האמיתי, במגע של טאבלט.

**מה נבדק כאן ולא בבדיקות השרת.** ``tests/test_docs_index_routes.py`` מוכיח שה-API מחזיר את
המצב ושהכתובות בעמוד הן הראוטים הרשומים. מה שרק דפדפן מראה הוא שהסקריפט שבתוך העמוד בכלל רץ
תחת ה-CSP של הוובאפ, שה-``fetch`` שלו מגיע, ושהכפתורים מובילים מ"בדוק עכשיו" דרך "מחכה לאישור"
ועד אינדקס שלם (``TESTING-PATTERNS.md`` T1).

השרת הוא הוובאפ האמיתי (``admin_live_server``), מול ``_fake_mongo`` ואתר ומטמיע מדומים
(``_docs_index_harness``): "בדוק עכשיו" ו"אשר והתחל" מריצים מעבר שלם בתוך הבקשה.

מדולג כשאין Chromium (וב-CI אין: ראו ``docs/testing.rst``).
"""

from __future__ import annotations

import contextlib

import pytest
from pymongo.errors import OperationFailure

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import open_admin_page, poll, tap_on
from _docs_index_harness import SHA_A, make_world, site_pages
from _fake_mongo import FakeCollection, FakeDB

from services import docs_index_service as svc
from services import docs_search_contract as contract

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

#: טאבלט 12 אינץ' לרוחב, בפיקסלים לוגיים — המכשיר שהעמוד נבנה בשבילו.
TABLET = {"width": 1280, "height": 800}


class _SearchNotEnabled(FakeCollection):
    """אוסף בשרת שאינו Atlas, כמו MongoDB 8.0.32 עונה (נמדד 7.10.2026)."""

    def list_search_indexes(self, name=None, session=None, comment=None, **kwargs):
        raise OperationFailure("search is not enabled", code=svc.SEARCH_NOT_ENABLED_CODE)


@pytest.fixture
def world(monkeypatch):
    import webapp.app as wa

    db = FakeDB()
    db.c[contract.CHUNKS_COLLECTION] = _SearchNotEnabled()
    world = make_world(monkeypatch, db)
    monkeypatch.setattr(wa, "get_db", lambda: db)
    world.site.publish(SHA_A, site_pages())
    return world


@contextlib.contextmanager
def docs_index_page(server, executable):
    """העמוד במגע של טאבלט — **המקום היחיד שמרים דפדפן כאן**. מחזיר גם את שגיאות הקונסול,
    שבהן מופיעה גם הפרה של ה-CSP. כל הניקוי ב-``finally``."""
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(
                executable_path=executable,
                args=[f"--window-size={TABLET['width']},{TABLET['height']}"],
            )
        except PlaywrightError as exc:  # pragma: no cover - תלוי בסביבה
            pytest.skip(f"אין Chromium זמין: {exc}")
        try:
            errors = []
            page, touch = open_admin_page(browser, server, "/admin/docs-index", viewport=TABLET)
            page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            yield page, touch, errors
        finally:
            browser.close()


def _shown(testid):
    return f"() => !!document.querySelector('[data-testid=\"{testid}\"]')"


def test_check_then_approve_fills_the_index_from_the_page(world, admin_live_server, chromium_executable):
    with docs_index_page(admin_live_server, chromium_executable) as (page, touch, errors):
        poll(page, _shown("docs-index-status-never-ran"), "העמוד טען את המצב: עוד לא רץ מעבר")
        poll(page, _shown("docs-index-vector-unknown"), "האינדקס הווקטורי מוצג כ'לא ידוע' בשרת שאינו Atlas")
        assert page.evaluate("() => document.getElementById('docsIndexStart').hidden") is True

        tap_on(page, touch, "#docsIndexCheck")
        poll(page, _shown("docs-index-status-awaiting_approval"), "בדיקה ידנית עצרה לאישור המילוי הראשון")
        poll(page, _shown("docs-index-approval-first_fill_or_model_change"), "הסיבה לאישור מוצגת")
        poll(page, "() => !document.getElementById('docsIndexStart').hidden", "כפתור האישור הופיע")

        tap_on(page, touch, "#docsIndexStart")
        poll(page, _shown("docs-index-status-complete"), "המעבר המאושר הסתיים")
        poll(page, _shown("docs-index-index-complete"), "האינדקס מוצג כשלם")

    state = svc.read_state(world.db)
    assert state["indexed_source_commit"] == SHA_A
    assert errors == [], errors


def test_a_computed_plan_survives_a_refresh_of_the_state(world, admin_live_server, chromium_executable):
    with docs_index_page(admin_live_server, chromium_executable) as (page, touch, errors):
        poll(page, _shown("docs-index-status-never-ran"), "העמוד טען את המצב")

        tap_on(page, touch, "#docsIndexComputePlan")
        poll(page, "() => !document.getElementById('docsIndexStart').hidden", "תוכנית חושבה ואפשר לאשר אותה")
        tap_on(page, touch, "#docsIndexRefresh")
        poll(page, _shown("docs-index-status-never-ran"), "המצב נטען מחדש")

        assert page.evaluate("() => document.getElementById('docsIndexStart').hidden") is False
    assert svc.read_state(world.db) is None
    assert errors == [], errors
