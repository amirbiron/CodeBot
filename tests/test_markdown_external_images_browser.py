"""תמונה מאתר אחר במסמך Markdown — בכרומיום אמיתי, בעמוד ``/md/<id>`` האמיתי ובשיתוף הציבורי שלו, עם ה-CSP שהשרת שולח.

**למה בדפדפן.** את ה-CSP אוכף רק הדפדפן. ``test_client`` של Flask רואה רק שהכותרת נשלחה, ולא שהיא חוסמת. וזה היה הבאג:
``_add_default_csp`` ב-``webapp/app.py`` התיר תמונות רק מהאתר עצמו, ולכן ``![alt](https://...)`` במסמך הוצג כתמונה
שבורה, בלי שום עקבה בשרת.

**איך העמודים מוגשים.** כמו ב-``tests/test_nosniff_browser.py``: כל בקשה ל-``ck.test`` עוברת דרך ``route`` של Playwright
ל-``test_client`` של Flask, עם הכותרות שלו — ובהן ``content-security-policy``. התמונה מגיעה מ-``img.test``, מקור אחר,
ו-``route`` מגיש לה PNG קטן. בקשה לכל מארח אחר נחסמת. המסמך נשמר בדמה בעבודת יד (``_fake_mongo``), והשיתוף נוצר דרך
הראוט, כמו בכפתור.

**מה נבדק:** בשני העמודים התמונה נטענת (רוחב טבעי גדול מאפס), הבקשה אליה יצאה, ואין ב-console שום הפרה של CSP.

מדולג כשאין Chromium (``chromium_executable`` ב-``tests/conftest.py``).
"""

from __future__ import annotations

import itertools
from urllib.parse import urlparse, urlsplit

import pytest
from bson import ObjectId

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import png_bytes, poll  # noqa: E402
from _fake_mongo import FakeDB  # noqa: E402

HOST = "ck.test"
IMAGE_HOST = "img.test"
IMAGE_URL = f"https://{IMAGE_HOST}/blog-images/diagram.png"
OWNER_ID = 7161
FILE_OID = ObjectId("0123456789abcdef0123ab09")
FORWARDED_HEADERS = ("content-type", "content-security-policy", "cache-control", "etag")
MARKDOWN = f"# מדריך\n\nפסקה לפני התמונה.\n\n![תרשים לדוגמה]({IMAGE_URL})\n\nפסקה אחרי התמונה.\n"

#: ההודעה של Chromium על הפרה של CSP (``Refused to load`` / ``violates the following Content Security Policy directive``).
CSP_VIOLATION = "Content Security Policy"

_ADDRESSES = itertools.count(1)


IMAGE_BYTES = png_bytes(48, 24)


@pytest.fixture(scope="module")
def site(chromium_executable):
    import webapp.app as wa

    db = FakeDB()
    db["code_snippets"].insert_one({
        "_id": FILE_OID,
        "user_id": OWNER_ID,
        "file_name": "guide.md",
        "code": MARKDOWN,
        "programming_language": "markdown",
        "version": 1,
        "is_active": True,
    })
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(wa, "get_db", lambda: db)
        owner = _client(wa, OWNER_ID)
        resp = owner.post(f"/api/share/{FILE_OID}", json={"type": "temporary", "permanent": False})
        assert resp.status_code == 200, resp.get_data(as_text=True)
        share_id = urlparse(resp.get_json()["url"]).path.rsplit("/", 1)[-1]
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
                yield b, wa, share_id
            finally:
                b.close()


def _client(wa, user_id: int | None):
    """‏``test_client`` עם כתובת IP משלו — מגבלת הקצב הגורפת משותפת לכל הטסטים בתהליך."""
    client = wa.app.test_client()
    client.environ_base["HTTP_X_FORWARDED_FOR"] = f"192.0.2.{next(_ADDRESSES) % 250 + 1}"
    if user_id is not None:
        with client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["user_data"] = {"id": user_id, "first_name": "בדיקה"}
    return client


@pytest.mark.parametrize("page_kind", ["owner-md-preview", "public-share-md-view"])
def test_an_image_from_another_site_loads_in_the_markdown_view(site, page_kind):
    b, wa, share_id = site
    path, user_id = {
        "owner-md-preview": (f"/md/{FILE_OID}", OWNER_ID),
        "public-share-md-view": (f"/share/{share_id}?view=md", None),
    }[page_kind]
    client = _client(wa, user_id)
    image_requests: list[str] = []
    console: list[str] = []
    csp_headers: list[str] = []

    def handle(route, request):
        u = urlsplit(request.url)
        if u.hostname == IMAGE_HOST:
            image_requests.append(request.url)
            return route.fulfill(status=200, body=IMAGE_BYTES, headers={"Content-Type": "image/png"})
        if u.hostname != HOST:
            return route.abort()
        target = u.path + (f"?{u.query}" if u.query else "")
        r = client.open(
            target, method=request.method, data=request.post_data_buffer,
            headers={"Content-Type": request.headers.get("content-type", "")},
        )
        headers = {k: v for k, v in r.headers.items() if k.lower() in FORWARDED_HEADERS}
        if request.is_navigation_request():
            csp_headers.extend(r.headers.getlist("Content-Security-Policy"))
        route.fulfill(status=r.status_code, body=r.data, headers=headers)

    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    try:
        ctx.route("**/*", handle)
        page = ctx.new_page()
        page.on("console", lambda msg: console.append(msg.text))
        page.goto(f"http://{HOST}{path}")

        # העמוד נבחן תחת המדיניות שהשרת שלח לו, ולא בלעדיה.
        assert len(csp_headers) == 1, csp_headers
        state = poll(
            page,
            """(url) => {
              const img = document.querySelector(`#md-content img[src="${url}"]`);
              if (!img) return 'no <img> yet';
              if (!img.complete) return 'loading';
              return { ok: true, width: img.naturalWidth, alt: img.getAttribute('alt') };
            }""",
            "התמונה במסמך סיימה להיטען (או להיכשל)",
            IMAGE_URL,
        )
    finally:
        ctx.close()

    violations = [m for m in console if CSP_VIOLATION in m]
    assert violations == [], violations
    assert image_requests == [IMAGE_URL]
    assert state["alt"] == "תרשים לדוגמה"
    assert state["width"] == 48
