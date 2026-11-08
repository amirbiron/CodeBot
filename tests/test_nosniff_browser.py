"""‏``X-Content-Type-Options: nosniff`` בדפדפן אמיתי: טקסט משותף לא רץ כסקריפט, ועמודי האתר נטענים כרגיל.

**למה בדפדפן.** את הכותרת אוכף רק הדפדפן — ``test_client`` של Flask רק רואה שהיא נשלחה (``tests/test_nosniff.py``).
ושתי השאלות כאן הן שאלות על הדפדפן: האם הוא באמת מסרב להריץ ``text/plain`` שנטען ב-``<script src>``, והאם הוא לא
מסרב גם לסקריפט או לגיליון סגנון של האתר עצמו.

**איך העמודים מוגשים.** כמו בשאר בדיקות הדפדפן: כל בקשה ל-``ck.test`` עוברת דרך ``route`` של Playwright ל-
``test_client`` של Flask, ובקשה לאתר חיצוני נחסמת. הכותרות שעוברות לדפדפן הן ``FORWARDED_HEADERS`` — ובהן
``x-content-type-options``, שבלעדיה הבדיקה הייתה רצה בלי הכותרת שהיא בודקת. השיתוף נוצר דרך הראוט, כמו בכפתור, על
דמה בעבודת יד (``_fake_mongo``).

**מה נבדק:**

- עמוד באתר עם ``script-src 'self'`` שטוען את ``/share/<id>/download`` כסקריפט: עם הכותרת הקוד לא רץ, וב-console
  מופיע הסירוב של הדפדפן. **בקרה:** אותה תשובה בדיוק, רק בלי הכותרת — והקוד רץ. בלי הבקרה הבדיקה הייתה עוברת גם
  אם הקוד לא רץ מסיבה אחרת.
- שלושה עמודים אמיתיים — העורך הציבורי, עמוד שיתוף לאורח ועמוד קובץ למחובר — נטענים בלי אף סירוב של "strict MIME",
  וכל סקריפט וגיליון סגנון שלהם הגיע עם הכותרת.

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
from _browser_harness import poll  # noqa: E402
from _fake_mongo import FakeDB  # noqa: E402

HOST = "ck.test"
OWNER_ID = 7160
FILE_OID = ObjectId("0123456789abcdef0123ab08")
FORWARDED_HEADERS = (
    "content-type",
    "content-security-policy",
    "content-disposition",
    "cache-control",
    "etag",
    "x-content-type-options",
)

#: הקוד שבעל השיתוף כתב. אם הוא רץ — ``window.sharedTextRan`` הוא ``true``.
SHARED_CODE = "window.sharedTextRan = true;\n"

#: עמוד באתר שטוען את השיתוף כסקריפט, תחת ``script-src 'self'``. הכתובת באמת מהאתר, ולכן ה-CSP מתיר אותה.
HOST_PAGE_PATH = "/nosniff-host-page"
HOST_PAGE_CSP = "script-src 'self'"

#: סירוב של הדפדפן לסקריפט או לגיליון סגנון בגלל הסוג — הנוסח של Chromium (נמדד ב-Chrome for Testing 153).
MIME_REFUSAL = "strict MIME"

_ADDRESSES = itertools.count(1)


@pytest.fixture(scope="module")
def site(chromium_executable):
    import webapp.app as wa

    db = FakeDB()
    db["code_snippets"].insert_one({
        "_id": FILE_OID,
        "user_id": OWNER_ID,
        "file_name": "guide.md",
        "code": SHARED_CODE,
        "programming_language": "markdown",
        "version": 1,
        "is_active": True,
    })
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(wa, "get_db", lambda: db)
        # העורך הציבורי מבקש ערכה משותפת; בלעדיה הוא מרנדר את ערכת ברירת המחדל של האתר
        patch.setattr(wa, "_get_shared_theme_cached", lambda theme_id: None)
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
            except Exception as exc:  # כשל חולף בהרמה, אחרי שהשער כבר אמר שיש דפדפן
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


class Visit:
    """הקשר דפדפן אחד: הבקשות, הודעות ה-console, והתשובות של הסקריפטים וגיליונות הסגנון מהאתר."""

    def __init__(self, site, *, user_id=None, strip_nosniff=False, host_page=None):
        b, wa, _share_id = site
        client = _client(wa, user_id)
        self.requested: list[str] = []
        self.console: list[str] = []
        self.assets: list[tuple[str, str, int, str | None]] = []
        self.ctx = b.new_context(viewport={"width": 1280, "height": 900})

        def handle(route, request):
            u = urlsplit(request.url)
            if u.hostname != HOST:
                return route.abort()
            self.requested.append(u.path)
            if host_page is not None and u.path == HOST_PAGE_PATH:
                return route.fulfill(
                    status=200,
                    body=host_page,
                    headers={"Content-Type": "text/html; charset=utf-8", "Content-Security-Policy": HOST_PAGE_CSP},
                )
            target = u.path + (f"?{u.query}" if u.query else "")
            r = client.open(
                target, method=request.method, data=request.post_data_buffer,
                headers={"Content-Type": request.headers.get("content-type", "")},
            )
            headers = {k: v for k, v in r.headers.items() if k.lower() in FORWARDED_HEADERS}
            if strip_nosniff:
                headers = {k: v for k, v in headers.items() if k.lower() != "x-content-type-options"}
            route.fulfill(status=r.status_code, body=r.data, headers=headers)

        def on_response(response):
            if urlsplit(response.url).hostname == HOST and response.request.resource_type in ("script", "stylesheet"):
                self.assets.append((
                    response.request.resource_type,
                    urlsplit(response.url).path,
                    response.status,
                    response.headers.get("x-content-type-options"),
                ))

        self.ctx.route("**/*", handle)
        self.page = self.ctx.new_page()
        self.page.on("console", lambda msg: self.console.append(msg.text))
        self.page.on("response", on_response)

    def refusals(self) -> list[str]:
        return [m for m in self.console if MIME_REFUSAL in m]

    def close(self):
        self.ctx.close()


@pytest.fixture
def visit(site):
    visits: list[Visit] = []

    def make(**kwargs):
        v = Visit(site, **kwargs)
        visits.append(v)
        return v

    yield make
    for v in visits:
        v.close()


@pytest.mark.parametrize("strip_nosniff, runs", [(False, False), (True, True)], ids=["with-nosniff", "control-without"])
def test_a_share_loaded_as_a_script_from_a_page_on_the_site_runs_only_without_nosniff(site, visit, strip_nosniff, runs):
    _b, _wa, share_id = site
    download = f"/share/{share_id}/download"
    v = visit(strip_nosniff=strip_nosniff, host_page=f'<!doctype html><title>t</title><script src="{download}"></script>')

    v.page.goto(f"http://{HOST}{HOST_PAGE_PATH}")  # ממתין ל-load, כלומר גם לסקריפט שבעמוד

    assert download in v.requested
    assert v.page.evaluate("window.sharedTextRan === true") is runs
    if runs:
        assert v.refusals() == []
    else:
        assert any("text/plain" in m and "not executable" in m for m in v.refusals()), v.console


@pytest.mark.parametrize("page_kind", ["markdown-editor", "public-share", "owner-file"])
def test_the_sites_own_pages_load_every_script_and_stylesheet_under_nosniff(site, visit, page_kind):
    _b, _wa, share_id = site
    path, user_id = {
        "markdown-editor": ("/markdown-editor", None),
        "public-share": (f"/share/{share_id}", None),
        "owner-file": (f"/file/{FILE_OID}", OWNER_ID),
    }[page_kind]
    v = visit(user_id=user_id)

    response = v.page.goto(f"http://{HOST}{path}", wait_until="networkidle")
    assert response.status == 200
    assert response.headers.get("x-content-type-options") == "nosniff"
    # לפני ההמתנה לתצוגה החיה: סקריפט שנחסם משאיר אותה לא מוכנה, והכישלון צריך לומר מה נחסם
    assert v.refusals() == []
    if page_kind == "markdown-editor":
        # התצוגה החיה טוענת עוד סקריפטים אחרי הטעינה; גם הם נבדקים
        poll(v.page, "document.querySelector('[data-preview-status]')?.dataset.state === 'ready'", "התצוגה החיה מוכנה")
        assert v.refusals() == []
    scripts = [a for a in v.assets if a[0] == "script"]
    styles = [a for a in v.assets if a[0] == "stylesheet"]
    assert scripts and styles, v.assets
    assert [a for a in v.assets if a[2] != 200 or a[3] != "nosniff"] == []
