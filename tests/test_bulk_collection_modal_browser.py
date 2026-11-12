"""חלון "הוסף לאוסף" ב-``base.html`` — מה שהוספה מרובה מבקשת להריץ, רץ רק אחרי אישור השרת.

בעמוד הקבצים, הוספה לאוסף של קבצים שנבחרו בבחירה מרובה פותחת את החלון המשותף עם
``onSuccess`` (``openBulkAddToCollectionModal(names, {onSuccess})``), ושם — יציאה ממצב
הבחירה. כאן נבדק החלון עצמו, בעמוד אמיתי: ``onSuccess`` רץ אחרי שהשרת אישר; לא רץ
כשמבטלים, וגם לא כשהשרת דוחה; ולא זולג לפתיחה של קובץ יחיד שבאה אחרי פתיחה מרובה.
שאר השרשרת — מ-``bulk-actions.js`` ועד היציאה מהמצב — ב-``tests/files-bulk-exit-mode.test.js``.

**העמוד אמיתי, המסד לא.** ``/settings`` מרונדר דרך ``test_client``, כמו ב-
``tests/test_search_on_enter_browser.py``. החלון נמצא ב-``base.html``, ולכן הוא שם
בכל עמוד. בקשות ``/api/collections`` נענות כאן.

מדולג כשאין Chromium.
"""

from __future__ import annotations

import itertools
import json
from urllib.parse import urlsplit

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import poll  # noqa: E402
from _fake_mongo import FakeDB  # noqa: E402

HOST = "ck.test"
USER_ID = 7166
FORWARDED_HEADERS = ("content-type", "cache-control", "etag")
_ADDRESSES = itertools.count(1)
COLLECTIONS = {"ok": True, "collections": [{"id": "c1", "name": "אוסף בדיקה"}]}


@pytest.fixture(scope="module")
def browser(chromium_executable):
    with sync_playwright() as pw:
        try:
            b = (
                pw.chromium.launch(executable_path=chromium_executable)
                if chromium_executable
                else pw.chromium.launch()
            )
        except Exception as exc:  # noqa: BLE001 — כשל חולף בהרמה, אחרי שהשער כבר אמר שיש דפדפן
            pytest.skip(f"Chromium לא עלה: {exc}")
        try:
            yield b
        finally:
            b.close()


@pytest.fixture
def page_factory(browser, monkeypatch):
    import webapp.app as wa

    db = FakeDB()
    monkeypatch.setattr(wa, "get_db", lambda: db)
    contexts = []

    def make(*, accept_items: bool, hold: list | None = None):
        """``hold`` — רשימה: בקשת ההוספה נשמרת בה ולא נענית, עד שהטסט עונה עליה."""
        client = wa.app.test_client()
        client.environ_base["HTTP_X_FORWARDED_FOR"] = f"192.0.2.{next(_ADDRESSES) % 250 + 1}"
        with client.session_transaction() as sess:
            sess["user_id"] = USER_ID
            sess["user_data"] = {"id": USER_ID, "first_name": "בדיקה"}
        posted: list[dict] = []

        def handle(route, request):
            u = urlsplit(request.url)
            if u.hostname != HOST:
                return route.abort()
            if u.path == "/api/collections" and request.method == "GET":
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(COLLECTIONS))
            if u.path == "/api/collections/c1/items" and request.method == "POST":
                posted.append(json.loads(request.post_data or "{}"))
                if hold is not None:
                    hold.append(route)
                    return None
                status, body = (200, {"ok": True}) if accept_items else (400, {"ok": False, "error": "nope"})
                return route.fulfill(status=status, content_type="application/json", body=json.dumps(body))
            target = u.path + (f"?{u.query}" if u.query else "")
            r = client.open(target, method=request.method, data=request.post_data_buffer,
                            headers={"Content-Type": request.headers.get("content-type", "")})
            headers = {k: v for k, v in r.headers.items() if k.lower() in FORWARDED_HEADERS}
            route.fulfill(status=r.status_code, body=r.data, headers=headers)

        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        contexts.append(ctx)
        ctx.route("**/*", handle)
        page = ctx.new_page()
        alerts: list[str] = []
        page.on("dialog", lambda d: (alerts.append(d.message), d.accept()))
        page.goto(f"http://{HOST}/settings")
        page.evaluate("window.__success = 0")
        return page, posted, alerts

    yield make
    for ctx in contexts:
        ctx.close()


def _open_bulk(page):
    page.evaluate("openBulkAddToCollectionModal(['a.py', 'b.py'], { onSuccess: () => { window.__success += 1; } })")
    poll(page, "() => !!document.querySelector('#addToCollectionBody input[name=collectionId]')", "האוספים נטענו")


def _confirm(page):
    page.click("#addToCollectionModal button.btn-primary")


def test_on_success_runs_once_after_the_server_accepts(page_factory):
    page, posted, alerts = page_factory(accept_items=True)
    _open_bulk(page)
    page.check("#addToCollectionBody input[name=collectionId]")
    _confirm(page)
    poll(page, "() => window.__success === 1", "onSuccess רץ אחרי האישור")
    assert [i["file_name"] for i in posted[0]["items"]] == ["a.py", "b.py"]
    assert page.evaluate("document.getElementById('addToCollectionModal').style.display") == "none"
    assert alerts == ["נוספו 2 קבצים לאוסף"]


def test_on_success_does_not_run_when_the_server_rejects(page_factory):
    page, posted, alerts = page_factory(accept_items=False)
    _open_bulk(page)
    page.check("#addToCollectionBody input[name=collectionId]")
    _confirm(page)
    # ה-alert של השגיאה מגיע אחרי התשובה מהשרת; עד שתי שניות.
    for _ in range(40):
        if alerts:
            break
        page.wait_for_timeout(50)
    assert len(posted) == 1
    assert alerts == ["שגיאה בהוספה לאוסף"]
    assert page.evaluate("window.__success") == 0


def test_cancel_and_a_later_single_file_add_do_not_run_it(page_factory):
    page, posted, alerts = page_factory(accept_items=True)
    _open_bulk(page)
    page.click("#addToCollectionModal button.btn-secondary")
    assert page.evaluate("window.__success") == 0

    # אחרי פתיחה מרובה — פתיחה של קובץ יחיד, ואישור שלה.
    _open_bulk(page)
    page.evaluate("openAddToCollectionModal('c.py')")
    poll(page, "() => !!document.querySelector('#addToCollectionBody input[name=collectionId]')", "האוספים נטענו")
    page.check("#addToCollectionBody input[name=collectionId]")
    _confirm(page)
    poll(page, "() => document.getElementById('addToCollectionModal').style.display === 'none'", "החלון נסגר")
    assert [i["file_name"] for i in posted[-1]["items"]] == ["c.py"]
    assert page.evaluate("window.__success") == 0, "onSuccess של הפתיחה המרובה זלג לקובץ יחיד"


def _wait_for(page, predicate, what: str):
    """המתנה לתנאי בצד של הטסט (בקשה שנעצרה ב-route), עד חמש שניות."""
    for _ in range(100):
        if predicate():
            return
        page.wait_for_timeout(50)
    raise AssertionError(f"לא התקיים: {what}")


def _release(route):
    route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True}))


def test_on_success_runs_when_the_answer_arrives_after_the_window_was_closed(page_factory):
    """הבקשה בדרך, והחלון נסגר. ההוספה שהשרת אישר שייכת לבחירה ששלחה אותה."""
    hold: list = []
    page, posted, alerts = page_factory(accept_items=True, hold=hold)
    _open_bulk(page)
    page.check("#addToCollectionBody input[name=collectionId]")
    _confirm(page)
    _wait_for(page, lambda: hold, "בקשת ההוספה יצאה")
    page.click("#addToCollectionModal button.btn-secondary")  # "בטל" — הסגירה מאפסת את ה-callback
    _release(hold.pop())
    poll(page, "() => window.__success === 1", "onSuccess של הבקשה רץ אחרי התשובה")
    assert alerts == ["נוספו 2 קבצים לאוסף"]


def test_an_answer_for_an_earlier_opening_does_not_close_the_window_that_is_open_now(page_factory):
    """הבקשה בדרך, החלון נסגר ונפתח שוב לקובץ יחיד. התשובה לא סוגרת את הפתיחה החדשה."""
    hold: list = []
    page, posted, alerts = page_factory(accept_items=True, hold=hold)
    _open_bulk(page)
    page.check("#addToCollectionBody input[name=collectionId]")
    _confirm(page)
    _wait_for(page, lambda: hold, "בקשת ההוספה יצאה")
    page.click("#addToCollectionModal button.btn-secondary")
    page.evaluate("openAddToCollectionModal('c.py')")
    poll(page, "() => !!document.querySelector('#addToCollectionBody input[name=collectionId]')", "החלון החדש נטען")

    _release(hold.pop())
    poll(page, "() => window.__success === 1", "onSuccess של הבקשה המרובה רץ")
    state = page.evaluate("""() => {
      const m = document.getElementById('addToCollectionModal');
      return { display: m.style.display, name: m.getAttribute('data-file-name') };
    }""")
    assert state == {"display": "flex", "name": "c.py"}, state
