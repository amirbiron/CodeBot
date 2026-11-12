"""בחירה מרובה בעמוד הקבצים — אחרי פעולה שהצליחה תיבות הסימון באמת נעלמות מהמסך.

הדיווח: אחרי פעולה על כמה קבצים, הריבועים של תיבות הסימון נשארו. הלוגיקה —
``finishBulkAction`` ב-``multi-select.js`` — נבדקת ב-CI ב-
``tests/files-bulk-exit-mode.test.js``, אבל שם רק המחלקה על ``body`` נבדקת. מה שמסתיר
את התיבות הוא ה-CSS (``.multi-select-active .file-selection`` ב-``multi-select.css``,
דרך ``opacity``), ולכן כאן נמדדת ה-``opacity`` המחושבת שלהן בעמוד ``/files`` האמיתי:
גלויות בזמן הבחירה, שקופות אחרי "הוסף למועדפים" שהשרת אישר, ועדיין שקופות אחרי
רענון. ובקרה: פעולה שהשרת דחה משאירה אותן גלויות.

**העמוד אמיתי, המסד לא.** ``/files`` מרונדר דרך ``test_client``, כמו ב-
``tests/test_search_on_enter_browser.py``. ה-``aggregate`` של הדמה מחזיר שני קבצים
בלי להריץ את הצינור — מה שנבדק כאן הוא הדפדפן, לא השאילתה. בקשת הפעולה
(``POST /api/files/bulk-favorite``) נענית כאן.

מדולג כשאין Chromium.
"""

from __future__ import annotations

import itertools
import json
from datetime import datetime, timezone
from urllib.parse import urlsplit

import pytest
from bson import ObjectId

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import poll  # noqa: E402
from _fake_mongo import FakeCollection, FakeDB  # noqa: E402

HOST = "ck.test"
USER_ID = 7167
FORWARDED_HEADERS = ("content-type", "cache-control", "etag")
_ADDRESSES = itertools.count(1)
NOW = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)
FILES = [
    {"_id": ObjectId("0123456789abcdef0123ab71"), "user_id": USER_ID, "file_name": "a.py",
     "programming_language": "python", "file_size": 10, "lines_count": 1, "created_at": NOW, "updated_at": NOW},
    {"_id": ObjectId("0123456789abcdef0123ab72"), "user_id": USER_ID, "file_name": "b.py",
     "programming_language": "python", "file_size": 10, "lines_count": 1, "created_at": NOW, "updated_at": NOW},
]


class _Snippets(FakeCollection):
    """``aggregate`` בלי צינור: ספירה לצינור שנגמר ב-``$count``, ושני הקבצים לכל צינור אחר."""

    def aggregate(self, pipeline, **_kwargs):
        if pipeline and "$count" in pipeline[-1]:
            return iter([{"total": len(FILES)}])
        return iter([dict(f) for f in FILES])

    def distinct(self, _field, _query=None):
        return ["python"]


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


class _CacheDisabled:
    """``/files`` שומר את ה-HTML המרונדר בקאש; כאן כל בקשה מרנדרת מחדש."""

    is_enabled = False


def _open(browser, monkeypatch, *, accept: bool):
    import webapp.app as wa

    db = FakeDB()
    db.c["code_snippets"] = _Snippets()
    monkeypatch.setattr(wa, "get_db", lambda: db)
    monkeypatch.setattr(wa, "cache", _CacheDisabled(), raising=True)
    client = wa.app.test_client()
    client.environ_base["HTTP_X_FORWARDED_FOR"] = f"192.0.2.{next(_ADDRESSES) % 250 + 1}"
    with client.session_transaction() as sess:
        sess["user_id"] = USER_ID
        sess["user_data"] = {"id": USER_ID, "first_name": "בדיקה"}

    def handle(route, request):
        u = urlsplit(request.url)
        if u.hostname != HOST:
            return route.abort()
        if u.path == "/api/files/bulk-favorite" and request.method == "POST":
            body = {"success": True, "updated": 2} if accept else {"success": False, "error": "nope"}
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
        target = u.path + (f"?{u.query}" if u.query else "")
        r = client.open(target, method=request.method, data=request.post_data_buffer,
                        headers={"Content-Type": request.headers.get("content-type", "")})
        headers = {k: v for k, v in r.headers.items() if k.lower() in FORWARDED_HEADERS}
        route.fulfill(status=r.status_code, body=r.data, headers=headers)

    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    ctx.route("**/*", handle)
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"http://{HOST}/files")
    poll(page, "() => !!window.multiSelect && document.querySelectorAll('.file-checkbox').length === 2",
         "העמוד עלה עם שני קבצים ומנהל הבחירה")
    return ctx, page, errors


#: ה-``opacity`` המחושבת של כל תיבות הסימון — בלי תלות במעבר של 0.3 שניות, דרך poll.
OPACITIES_JS = "() => [...document.querySelectorAll('.file-selection')].map(el => getComputedStyle(el).opacity)"


def _wait_opacity(page, value: str, what: str):
    poll(page, f"""() => {{ const o = ({OPACITIES_JS})(); return {{ok: o.length === 2 && o.every(x => x === {value!r}), o}}; }}""", what)


def _select_both_and_favorite(page):
    page.click("#multiSelectToggleBtn")
    _wait_opacity(page, "1", "במצב בחירה התיבות גלויות")
    for box in page.locator(".file-checkbox").all():
        box.check()
    poll(page, "() => window.multiSelect.getSelectedCount() === 2", "שני קבצים נבחרו")
    page.click("button[onclick='bulkAddToFavorites()']")


def test_the_checkboxes_disappear_after_a_successful_action_and_stay_hidden_after_reload(browser, monkeypatch):
    ctx, page, errors = _open(browser, monkeypatch, accept=True)
    try:
        _select_both_and_favorite(page)
        _wait_opacity(page, "0", "אחרי הצלחה התיבות שקופות")
        assert page.evaluate("document.body.classList.contains('multi-select-active')") is False
        page.reload()
        poll(page, "() => !!window.multiSelect", "העמוד עלה שוב")
        _wait_opacity(page, "0", "אחרי רענון התיבות עדיין שקופות")
        assert errors == []
    finally:
        ctx.close()


def test_the_checkboxes_stay_after_a_rejected_action(browser, monkeypatch):
    ctx, page, errors = _open(browser, monkeypatch, accept=False)
    try:
        _select_both_and_favorite(page)
        poll(page, "() => !!document.querySelector('.notification.error')", "הוצגה שגיאה")
        _wait_opacity(page, "1", "אחרי כשל התיבות גלויות")
        assert page.evaluate("window.multiSelect.getSelectedCount()") == 2
        assert errors == []
    finally:
        ctx.close()
