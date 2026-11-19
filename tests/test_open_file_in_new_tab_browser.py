"""כניסה לקובץ מהאוספים ומכרטיס הנעוצים בדשבורד — נפתחת בלשונית חדשה, והעמוד שממנו לחצו נשאר.

**באוספים** הכרטיס מחזיק את שם הקובץ. שם הקובץ הוא קישור אמיתי עם ``target="_blank"`` (``openFileLinkAttrs`` ב-
``collections.js``), והכפתור 🌐 פותח ב-``window.open`` בתוך הלחיצה עצמה (``openDirectView``). שניהם מצביעים על
``open_file_by_name``, שמפנה בשרת לגרסה האחרונה. עד נובמבר 2026 הדף שאל קודם את ``/api/files/resolve`` מה המזהה ורק
אחרי התשובה עבר — באותה לשונית. לכן נבדק כאן גם **שאין בקשה כזו לפני הפתיחה**: ``window.open`` אחרי המתנה לרשת
נחסם כשהיא ארוכה מהזמן שהדפדפן מרשה אחרי לחיצה.

העמוד האמיתי מהאפליקציה (``admin_live_server``), עם הסקריפטים שלו ותשובות API מדומות, כמו ב-
``tests/test_file_name_display_browser.py``. ליעד של הלשונית החדשה (``open_file_by_name``) עונה כאן עמוד ריק: בשרת
של הטסטים אין מסד, ואת ההפניה עצמה בודק ``tests/test_open_file_by_name.py``.

**בדשבורד** ``dashboard.html`` מרונדר מהדיסק (``tests/_dashboard_render.py``) ומוגש מכתובת מדומה, כמו ב-
``tests/test_dashboard_recent_notes_browser.py``.

נבדק בלחיצת עכבר ובנגיעה (``tap``, עם מסך מגע ברוחב של טאבלט). ריצת הבקרה — עם ``collections.js`` ו-
``dashboard.html`` שלפני השינוי — נכשלה בכל המקרים: לא נפתחה לשונית.

מדולג כשאין Chromium (``chromium_executable`` ב-``tests/conftest.py``).
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")
pytest.importorskip("jinja2")

from flask import url_for  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _dashboard_render import render_dashboard  # noqa: E402

from webapp import app as webapp_app  # noqa: E402

FILE_NAME = "מדריך RTL.md"

_COLLECTION = {"id": "c1", "name": "אוסף", "icon": "📁", "color": "blue", "items_count": 1, "is_favorite": False}
_WORKSPACE = {"id": "w1", "name": "שולחן עבודה", "slug": "workspace", "icon": "🖥️", "color": "blue", "items_count": 1,
              "is_favorite": False}


def _items(**extra):
    return {"ok": True, "items": [{"source": "regular", "file_name": FILE_NAME, "id": "i1", **extra}], "total": 1,
            "page": 1, "per_page": 20}


#: עמוד, תשובות API מדומות (קידומת נתיב ← JSON, הספציפית קודם), והכרטיס.
PAGES = {
    "collection": ("/collections/c1", {"/api/collections/c1/items": _items(),
                                       "/api/collections/c1": {"ok": True, "collection": _COLLECTION},
                                       "/api/collections": {"ok": True, "collections": [_COLLECTION]}},
                   ".collection-card", ".collection-card__link"),
    "workspace": ("/collections/w1", {"/api/collections/w1/items": _items(workspace_state="todo"),
                                      "/api/collections/w1": {"ok": True, "collection": _WORKSPACE},
                                      "/api/collections": {"ok": True, "collections": [_WORKSPACE]}},
                  ".workspace-card", ".workspace-card__link"),
}

#: לחיצת עכבר במסך מחשב, ונגיעה במסך מגע ברוחב של טאבלט.
INPUTS = {
    "mouse": {"viewport": {"width": 1280, "height": 900}},
    "touch": {"viewport": {"width": 1024, "height": 1366}, "has_touch": True},
}

DASHBOARD_HOST = "https://ck.test"


def _url(endpoint, **values):
    with webapp_app.app.test_request_context():
        return url_for(endpoint, **values)


@pytest.fixture(scope="module")
def browser(chromium_executable):
    with sync_playwright() as pw:
        try:
            b = pw.chromium.launch(executable_path=chromium_executable) if chromium_executable else pw.chromium.launch()
        except Exception as exc:  # noqa: BLE001 — כל כשל השקה פירושו אין דפדפן
            pytest.skip(f"אין Chromium זמין: {exc}")
        try:
            yield b
        finally:
            b.close()


def _press(locator, how: str) -> None:
    if how == "touch":
        locator.tap()
    else:
        locator.click()


def _open_collection_page(browser, server, place: str, how: str):
    path, api, card_sel, _link = PAGES[place]
    prefixes = sorted(api, key=len, reverse=True)
    context = browser.new_context(locale="he-IL", **INPUTS[how])
    context.add_cookies([{"name": "session", "value": server.session_cookie, "domain": "127.0.0.1", "path": "/"}])
    seen = {"resolve": [], "dialogs": [], "errors": []}

    def api_route(route):
        url_path = urlsplit(route.request.url).path
        if url_path.startswith(_url("api_resolve_file_by_name")):
            seen["resolve"].append(route.request.url)
        for prefix in prefixes:
            if url_path.startswith(prefix):
                route.fulfill(status=200, content_type="application/json", body=json.dumps(api[prefix]))
                return
        route.continue_()

    context.route("**/api/**", api_route)
    # היעד של הלשונית החדשה. בשרת של הטסטים אין מסד — וההפניה אינה מה שנבדק כאן.
    context.route(f"**{_url('open_file_by_name')}*", lambda route: route.fulfill(
        status=200, content_type="text/html; charset=utf-8", body="<!doctype html><p>הקובץ</p>"))
    page = context.new_page()
    page.on("pageerror", lambda exc: seen["errors"].append(str(exc)))
    page.on("dialog", lambda dialog: (seen["dialogs"].append(dialog.message), dialog.dismiss()))
    page.goto(f"{server.base_url}{path}", wait_until="load")
    page.locator(card_sel).first.wait_for(state="visible")
    return context, page, seen


def _query(url: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


@pytest.mark.parametrize("how", sorted(INPUTS))
@pytest.mark.parametrize("place", sorted(PAGES))
def test_the_file_name_in_a_collection_opens_the_file_in_a_new_tab(browser, admin_live_server, place, how):
    context, page, seen = _open_collection_page(browser, admin_live_server, place, how)
    try:
        before = page.url
        link = page.locator(PAGES[place][3]).first
        with context.expect_page(timeout=5000) as new_tab:
            _press(link, how)
        tab = new_tab.value
        tab.wait_for_load_state()

        assert urlsplit(tab.url).path == _url("open_file_by_name")
        assert _query(tab.url) == {"name": FILE_NAME}
        assert page.url == before
        assert link.get_attribute("rel") == "noopener"
        assert seen == {"resolve": [], "dialogs": [], "errors": []}
    finally:
        context.close()


@pytest.mark.parametrize("how", sorted(INPUTS))
@pytest.mark.parametrize("place", sorted(PAGES))
def test_the_direct_view_button_opens_the_view_in_a_new_tab(browser, admin_live_server, place, how):
    context, page, seen = _open_collection_page(browser, admin_live_server, place, how)
    try:
        before = page.url
        button = page.locator(f"{PAGES[place][2]} .open-view").first
        with context.expect_page(timeout=5000) as new_tab:
            _press(button, how)
        tab = new_tab.value
        tab.wait_for_load_state()

        assert urlsplit(tab.url).path == _url("open_file_by_name")
        assert _query(tab.url) == {"name": FILE_NAME, "view": "md"}
        assert page.url == before
        # ``noopener``: הלשונית החדשה אינה מחזיקה הפניה לעמוד האוספים.
        assert tab.evaluate("() => window.opener") is None
        assert seen == {"resolve": [], "dialogs": [], "errors": []}
    finally:
        context.close()


def _serve_dashboard(route):
    path = urlsplit(route.request.url).path
    if path == "/dashboard":
        body = render_dashboard(pinned_files=[{"id": "f1", "file_name": FILE_NAME, "language": "markdown", "icon": "",
                                               "tags": [], "description": "", "lines": 1}])
        html = f'<!doctype html><html dir="rtl"><head><meta charset="utf-8"></head><body>{body}</body></html>'
        route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)
    elif path.startswith("/file/"):
        route.fulfill(status=200, content_type="text/html; charset=utf-8", body="<!doctype html><p>הקובץ</p>")
    else:
        route.abort()


@pytest.mark.parametrize("how", sorted(INPUTS))
def test_a_pinned_file_on_the_dashboard_opens_in_a_new_tab(browser, how):
    context = browser.new_context(**INPUTS[how])
    try:
        context.route(f"{DASHBOARD_HOST}/**", _serve_dashboard)
        page = context.new_page()
        page.goto(f"{DASHBOARD_HOST}/dashboard")
        link = page.locator(".pinned-card__name").first
        with context.expect_page(timeout=5000) as new_tab:
            _press(link, how)
        tab = new_tab.value
        tab.wait_for_load_state()

        assert urlsplit(tab.url).path == "/file/f1"
        assert urlsplit(page.url).path == "/dashboard"
        assert link.get_attribute("rel") == "noopener"
    finally:
        context.close()
