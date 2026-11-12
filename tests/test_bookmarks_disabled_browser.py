"""סימניות כבויות בהגדרות — בכרומיום, בעמודים האמיתיים ``/file/<id>`` ו-``/md/<id>``.

"הצגת כפתור סימניות" ← מוסתר (``bookmarks_toggle_btn_visible = '0'`` ב-localStorage):
הכפתור הצף לא מוצג, נגיעה במספר שורה לא שולחת בקשת יצירה ולא פותחת את הקישור
``#line-N`` שהמספר עוטף, ונגיעה בכותרת במארקדאון לא שולחת בקשה. בכל מקרה נבדק גם
"מוצג", באותו עמוד ובאותה נגיעה, כדי להוכיח שהבקשה הייתה נשלחת — אחרת "לא נשלחה"
לא אומר כלום. כל דרכי היצירה נבדקות ב-CI ב-``tests/bookmarks-disabled.test.js``; כאן
נבדק שהנגיעה האמיתית מגיעה לשער.

**העמוד אמיתי, המסד לא** — אותה דרך של ``tests/test_search_on_enter_browser.py``:
הראוט של Flask דרך ``test_client``, והקובץ בדמה (``_fake_mongo``). בקשת היצירה
(``POST /api/bookmarks/<id>/toggle``) נספרת ונענית כאן, ולא מגיעה לשרת.

מדולג כשאין Chromium.
"""

from __future__ import annotations

import itertools
import json
from urllib.parse import urlsplit

import pytest
from bson import ObjectId

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import poll  # noqa: E402
from _fake_mongo import FakeDB  # noqa: E402

HOST = "ck.test"
OWNER_ID = 7163
CODE_OID = ObjectId("0123456789abcdef0123ab61")
MD_OID = ObjectId("0123456789abcdef0123ab62")
CODE = "".join(f"value_{i:02d} = {i}\n" for i in range(1, 21))
MARKDOWN = "# כותרת ראשית\n\nפסקה.\n\n## סעיף שני\n\nעוד פסקה.\n"
FORWARDED_HEADERS = ("content-type", "cache-control", "etag")

_ADDRESSES = itertools.count(1)


@pytest.fixture(scope="module")
def site(chromium_executable):
    import webapp.app as wa

    db = FakeDB()
    for oid, name, code, lang in ((CODE_OID, "lines.py", CODE, "python"),
                                  (MD_OID, "doc.md", MARKDOWN, "markdown")):
        db["code_snippets"].insert_one({
            "_id": oid, "user_id": OWNER_ID, "file_name": name, "code": code,
            "programming_language": lang, "version": 1, "is_active": True,
        })
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(wa, "get_db", lambda: db)
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
                yield b, wa
            finally:
                b.close()


def _open(site, path: str, *, visible: str):
    """העמוד, עם ההגדרה ``visible`` ב-localStorage, ורשימה של בקשות היצירה שנשלחו."""
    b, wa = site
    client = wa.app.test_client()
    client.environ_base["HTTP_X_FORWARDED_FOR"] = f"192.0.2.{next(_ADDRESSES) % 250 + 1}"
    with client.session_transaction() as sess:
        sess["user_id"] = OWNER_ID
        sess["user_data"] = {"id": OWNER_ID, "first_name": "בדיקה"}
    toggles: list[dict] = []
    errors: list[str] = []

    def handle(route, request):
        u = urlsplit(request.url)
        if u.hostname != HOST:
            return route.abort()
        if request.method == "POST" and u.path.startswith("/api/bookmarks/") and u.path.endswith("/toggle"):
            toggles.append(json.loads(request.post_data or "{}"))
            return route.fulfill(status=200, content_type="application/json",
                                 body=json.dumps({"ok": True, "action": "added", "bookmark": {"color": "yellow"}}))
        target = u.path + (f"?{u.query}" if u.query else "")
        r = client.open(target, method=request.method, data=request.post_data_buffer,
                        headers={"Content-Type": request.headers.get("content-type", "")})
        headers = {k: v for k, v in r.headers.items() if k.lower() in FORWARDED_HEADERS}
        route.fulfill(status=r.status_code, body=r.data, headers=headers)

    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    ctx.add_init_script(f"try {{ localStorage.setItem('bookmarks_toggle_btn_visible', '{visible}'); }} catch (e) {{}}")
    ctx.route("**/*", handle)
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"http://{HOST}{path}")
    # ``BookmarkManager`` מאזין לנגיעות רק בסוף ``init`` (אחרי טעינת ההעדפות והסימניות).
    poll(page, "() => !!window.bookmarkManager && !!window.bookmarkManager.ui", "מערכת הסימניות עלתה")
    page.wait_for_load_state("networkidle")
    return ctx, page, toggles, errors


LINE = ".highlighttable .linenos a, .linenodiv a"


@pytest.mark.parametrize("visible, expect_toggle", [("0", False), ("1", True)], ids=["hidden", "shown"])
def test_tapping_a_line_number(site, visible, expect_toggle):
    ctx, page, toggles, errors = _open(site, f"/file/{CODE_OID}", visible=visible)
    try:
        button_shown = page.evaluate("getComputedStyle(document.getElementById('toggleBookmarksBtn')).display !== 'none'")
        assert button_shown is expect_toggle
        page.locator(LINE).nth(4).click()
        # הבקשה יוצאת מקוד אסינכרוני; 300ms מספיקים לה כשהיא נשלחת, ולכן הם גם הזמן
        # שבו "לא נשלחה" נמדד.
        page.wait_for_timeout(300)
        if expect_toggle:
            assert len(toggles) == 1 and toggles[0].get("line_number") == 5, toggles
        else:
            assert toggles == []
        # בשני המצבים הקישור ``#line-5`` לא נפתח — הכרעה א' של המשתמש למצב הכבוי,
        # וכך זה היה תמיד במצב הפעיל.
        assert urlsplit(page.url).fragment == ""
        assert errors == []
    finally:
        ctx.close()


@pytest.mark.parametrize("visible, expect_toggle", [("0", False), ("1", True)], ids=["hidden", "shown"])
def test_tapping_a_markdown_heading(site, visible, expect_toggle):
    ctx, page, toggles, errors = _open(site, f"/md/{MD_OID}", visible=visible)
    try:
        poll(page, "() => !!document.querySelector('#md-content h2[id]')", "המסמך רונדר עם עוגנים")
        # הנגיעה בטקסט של הכותרת, לא בקישור הקבוע שלידה.
        page.evaluate("""() => {
          const h = document.querySelector('#md-content h2[id]');
          const r = document.createRange(); r.selectNodeContents(h.firstChild);
          const box = r.getBoundingClientRect();
          window.__headingPoint = [box.left + 4, box.top + box.height / 2];
          window.getSelection().removeAllRanges();
        }""")
        x, y = page.evaluate("window.__headingPoint")
        page.mouse.click(x, y)
        page.wait_for_timeout(300)
        if expect_toggle:
            assert len(toggles) == 1 and toggles[0].get("anchor_id"), toggles
        else:
            assert toggles == []
        assert errors == []
    finally:
        ctx.close()
