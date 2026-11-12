"""איפה ה-"@" של שם המשתמש נוחת על המסך — בכרומיום, בעמוד ``/settings`` האמיתי.

הדיווח: בכרטיס "פרטי חשבון" שם המשתמש הוצג "moominAmir@". העמוד כתוב מימין לשמאל,
ו-"@" שבתחילת השורה נצמד לכיוון העברי. המאקרו ``telegram_username`` מבודד את השם
ב-``<bdi dir="ltr">``. כאן נמדד המיקום של התו "@" מול האות הראשונה של השם, בפריסה
שהדפדפן עשה בפועל.

**ובקרה באותו עמוד:** אותו שם בצורה הישנה (``" @moominAmir "`` בתוך ``<p>`` של העמוד)
מוזרק ליד, ושם ה-"@" חייב לנחות **מימין** לשם. בלי הבקרה, מדידה שבורה — למשל
מלבן ריק של תו — הייתה מאשרת כל פלט.

**העמוד אמיתי, המסד לא** — אותה דרך של ``tests/test_search_on_enter_browser.py``.

מדולג כשאין Chromium.
"""

from __future__ import annotations

import itertools
from urllib.parse import urlsplit

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _fake_mongo import FakeDB  # noqa: E402

HOST = "ck.test"
USER_ID = 7165
USERNAME = "moominAmir"
FORWARDED_HEADERS = ("content-type", "cache-control", "etag")
_ADDRESSES = itertools.count(1)

#: ‏x של התו "@" ושל האות שאחריו, בתוך צומת הטקסט הראשון של ``el``.
POSITIONS_JS = """(el) => {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode()) && node.data.indexOf('@') === -1) {}
  const at = node.data.indexOf('@');
  const rect = (i) => { const r = document.createRange(); r.setStart(node, i); r.setEnd(node, i + 1);
                        const b = r.getBoundingClientRect(); return {left: b.left, right: b.right, width: b.width}; };
  return {at: rect(at), first: rect(at + 1), dir: getComputedStyle(el).direction};
}"""


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


def test_the_at_sign_is_left_of_the_username_on_the_settings_page(browser, monkeypatch):
    import webapp.app as wa

    db = FakeDB()
    db["users"].insert_one({"user_id": USER_ID, "username": USERNAME, "first_name": "בדיקה"})
    monkeypatch.setattr(wa, "get_db", lambda: db)
    client = wa.app.test_client()
    client.environ_base["HTTP_X_FORWARDED_FOR"] = f"192.0.2.{next(_ADDRESSES) % 250 + 1}"
    with client.session_transaction() as sess:
        sess["user_id"] = USER_ID
        sess["user_data"] = {"id": USER_ID, "first_name": "בדיקה", "username": USERNAME}

    def handle(route, request):
        u = urlsplit(request.url)
        if u.hostname != HOST:
            return route.abort()
        target = u.path + (f"?{u.query}" if u.query else "")
        r = client.open(target, method=request.method, data=request.post_data_buffer,
                        headers={"Content-Type": request.headers.get("content-type", "")})
        headers = {k: v for k, v in r.headers.items() if k.lower() in FORWARDED_HEADERS}
        route.fulfill(status=r.status_code, body=r.data, headers=headers)

    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    try:
        ctx.route("**/*", handle)
        page = ctx.new_page()
        page.goto(f"http://{HOST}/settings")
        bdi = page.locator("bdi", has_text=f"@{USERNAME}").first
        p = bdi.locator("xpath=..")
        # הבקרה: אותו <p>, עם הטקסט כמו שהתבנית הישנה כתבה אותו.
        page.evaluate("""([username]) => {
          const p = [...document.querySelectorAll('bdi')].find(b => b.textContent === '@' + username).parentElement;
          const old = p.cloneNode(false);
          old.id = 'oldMarkup';
          old.textContent = ' @' + username + ' ';
          p.after(old);
        }""", [USERNAME])

        new = p.evaluate(POSITIONS_JS)
        old = page.locator("#oldMarkup").evaluate(POSITIONS_JS)

        assert new["dir"] == "rtl" and old["dir"] == "rtl", (new, old)
        assert new["at"]["width"] > 0 and new["first"]["width"] > 0, new
        # אחרי התיקון: "@" משמאל לשם.
        assert new["at"]["right"] <= new["first"]["left"] + 0.5, new
        # הבקרה: בצורה הישנה "@" מימין לשם — התקלה מהדיווח.
        assert old["at"]["left"] >= old["first"]["right"] - 0.5, old
    finally:
        ctx.close()
