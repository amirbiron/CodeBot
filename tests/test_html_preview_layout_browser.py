"""תצוגת הדפדפן לקובץ HTML (``/html/<id>``, ``html_preview.html``) ממלאת את המסך — נמדד בכרומיום, בעמוד האמיתי.

כשגוללים את העמוד עד הסוף: בראש המסך נמצאת שורת הכלים של התצוגה (JS, מסך מלא, חלון חדש), ושורת קוד/הורד/חזור
שמעליה מחוץ למסך; ומסביב לכרטיס — הרווח של ``--html-preview-gutter`` מכל צד, ולא יותר. נבדק בשלושה רוחבים, ובטלפון
בערכה כהה, כי ``dark-mode.css`` נותן ל-``.glass-card`` ריפוד משלו במסך צר.

שהמסגרת עצמה לא נחתכת בתחתית הכרטיס בודק ``test_the_bottom_of_the_frame_is_not_cut_off`` ב-
``tests/test_html_preview_notes_browser.py``; כאן נבדק רק שהיא נגמרת בתוך המסך כשגוללים עד הסוף.

**העמוד אמיתי, המסד לא** — אותה דרך של ``tests/test_bookmarks_disabled_browser.py``: הראוט של Flask דרך
``test_client``, והקובץ בדמה (``_fake_mongo``). FontAwesome מגיע מ-CDN, וכאן כל בקשה לדומיין אחר נחסמת, ולכן העמוד
עובר למצב ``no-fa-icons`` והכפתורים מציגים כיתוב במקום אייקון. זה מצב אמיתי של העמוד, והבדיקות לא נשענות על
גודל מוחלט של כפתור: גודל הכפתורים בשורת הכלים נמדד מול כפתור רגיל באותו עמוד.

מדולג כשאין Chromium.
"""

from __future__ import annotations

import itertools
from urllib.parse import urlsplit

import pytest
from bson import ObjectId

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import poll  # noqa: E402
from _fake_mongo import FakeDB  # noqa: E402

HOST = "ck.test"
OWNER_ID = 7164
HTML_OID = ObjectId("0123456789abcdef0123ab71")
#: דף ארוך מהמסגרת, כמו רוב הקבצים שמוצגים כאן.
PAGE = '<!doctype html><html><body style="margin:0"><div style="height:2000px">דף ארוך</div></body></html>'
FORWARDED_HEADERS = ("content-type", "content-security-policy", "cache-control")

#: ``(שם, רוחב, גובה, מצב כהה)``. הטאבלט — כמו בצילום מסך של המשתמש, טאבלט 12.7 אינץ' לרוחב.
VIEWPORTS = [
    ("phone", 390, 844, "dark"),
    ("tablet", 1333, 680, "dark"),
    ("desktop", 1440, 900, "light"),
]

_ADDRESSES = itertools.count(1)

#: המצב של העמוד, אחרי שה-``body`` (שהוא שגולל באתר, ``html, body`` ב-base.html) נגלל עד הסוף.
#: האלמנטים נמצאים לפי מזהים ו-``href``, לא לפי ה-classes שהתיקון הוסיף — כדי שאותה בדיקה תרוץ גם על הקוד שלפניו.
MEASURE = r"""() => {
  const frame = document.getElementById('previewFrame');
  const card = document.getElementById('htmlPreviewSurface').parentElement;
  const toolbar = document.getElementById('toggleJs').closest('label').parentElement;
  const headerRow = document.querySelector('a[href^="/download/"]').parentElement;
  const rect = el => {
    const r = el.getBoundingClientRect();
    return {left: r.left, top: r.top, right: r.right, bottom: r.bottom, height: r.height};
  };
  const c = rect(card);
  return {
    vw: innerWidth, vh: innerHeight,
    scrollTop: document.body.scrollTop,
    scrollable: document.body.scrollHeight > document.body.clientHeight,
    gutter: parseFloat(getComputedStyle(document.querySelector('.main-content')).paddingBottom),
    card: c,
    frame: rect(frame),
    toolbar: rect(toolbar),
    headerRow: rect(headerRow),
    fullscreen: rect(document.getElementById('btnFullscreen')),
    newWindow: rect(document.getElementById('btnNewWindow')),
    pageButton: rect(headerRow.querySelector('a[href^="/download/"]')),
  };
}"""


@pytest.fixture(scope="module")
def site(chromium_executable):
    import webapp.app as wa

    db = FakeDB()
    db["code_snippets"].insert_one({
        "_id": HTML_OID, "user_id": OWNER_ID, "file_name": "page.html", "code": PAGE,
        "programming_language": "html", "version": 1, "is_active": True,
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


def _open(site, width: int, height: int, mode: str):
    """העמוד בגודל המסך הנתון, אחרי שה-``body`` נגלל עד הסוף."""
    b, wa = site
    client = wa.app.test_client()
    client.environ_base["HTTP_X_FORWARDED_FOR"] = f"192.0.2.{next(_ADDRESSES) % 250 + 1}"
    with client.session_transaction() as sess:
        sess["user_id"] = OWNER_ID
        sess["user_data"] = {"id": OWNER_ID, "first_name": "בדיקה"}

    def handle(route, request):
        u = urlsplit(request.url)
        if u.hostname != HOST:
            return route.abort()
        target = u.path + (f"?{u.query}" if u.query else "")
        r = client.open(target, method=request.method, data=request.post_data_buffer,
                        headers={"Content-Type": request.headers.get("content-type", "")})
        headers = {k: v for k, v in r.headers.items() if k.lower() in FORWARDED_HEADERS}
        route.fulfill(status=r.status_code, body=r.data, headers=headers)

    ctx = b.new_context(viewport={"width": width, "height": height})
    ctx.add_init_script(f"try {{ localStorage.setItem('dark_mode_preference', '{mode}'); }} catch (e) {{}}")
    ctx.route("**/*", handle)
    page = ctx.new_page()
    page.goto(f"http://{HOST}/html/{HTML_OID}")
    page.wait_for_load_state("networkidle")
    poll(page, f"() => document.documentElement.getAttribute('data-theme') === '{'dark' if mode == 'dark' else 'classic'}'",
         "הערכה של הבדיקה הוחלה")
    _scroll_page_to_the_end(page)
    return ctx, page


def _scroll_page_to_the_end(page) -> None:
    page.evaluate("() => { document.body.scrollTop = document.body.scrollHeight; }")
    b = "document.body"
    poll(page, f"() => {b}.scrollTop > 0 && {b}.scrollTop + {b}.clientHeight >= {b}.scrollHeight - 1", "העמוד נגלל עד הסוף")


@pytest.mark.parametrize("name, width, height, mode", VIEWPORTS, ids=[v[0] for v in VIEWPORTS])
def test_scrolled_to_the_end_the_preview_fills_the_screen(site, name, width, height, mode):
    """בראש המסך שורת הכלים ולא השורה שמעליה, ובכל צד של הכרטיס רווח אחד של ``--html-preview-gutter``."""
    ctx, page = _open(site, width, height, mode)
    try:
        m = page.evaluate(MEASURE)
        assert m["scrollable"] and m["scrollTop"] > 0, m
        assert m["toolbar"]["top"] >= 0, f"שורת הכלים יצאה מראש המסך: {m['toolbar']}"
        assert m["headerRow"]["bottom"] <= 0, f"שורת קוד/הורד/חזור עדיין במסך: {m['headerRow']}"
        g = m["gutter"]
        gaps = {
            "left": m["card"]["left"],
            "right": m["vw"] - m["card"]["right"],
            "top": m["card"]["top"],
            "bottom": m["vh"] - m["card"]["bottom"],
        }
        # עד פיקסל אחד: הגלילה נעצרת על מספר שלם, וגובה הכותרת שמעל אינו שלם.
        assert all(abs(v - g) <= 1 for v in gaps.values()), f"gutter={g}, gaps={gaps}"
        assert m["frame"]["bottom"] <= min(m["card"]["bottom"], m["vh"]), m
    finally:
        ctx.close()


@pytest.mark.parametrize("name, width, height, mode", VIEWPORTS, ids=[v[0] for v in VIEWPORTS])
def test_the_toolbar_buttons_are_smaller_and_stay_together(site, name, width, height, mode):
    """"מסך מלא" ו"חלון חדש" נמוכים מכפתור רגיל באותו עמוד, ויושבים באותה שורה — גם כששורת הכלים נשברת."""
    ctx, page = _open(site, width, height, mode)
    try:
        m = page.evaluate(MEASURE)
        for key in ("fullscreen", "newWindow"):
            assert m[key]["height"] < m["pageButton"]["height"], (key, m[key], m["pageButton"])
        assert abs(m["fullscreen"]["top"] - m["newWindow"]["top"]) <= 1, (m["fullscreen"], m["newWindow"])
    finally:
        ctx.close()


def test_fullscreen_still_fills_the_screen(site):
    """"מסך מלא" מציג את משטח הפתקים — והמסגרת שבתוכו — על כל המסך, גם עם הריפוד והרווחים של הכרטיס כאן, ויציאה
    מחזירה את המסגרת למקומה."""
    ctx, page = _open(site, 1333, 680, "dark")
    try:
        before = page.evaluate(MEASURE)["frame"]
        page.click("#btnFullscreen")
        state = poll(page, """() => {
          const s = document.getElementById('htmlPreviewSurface'), f = document.getElementById('previewFrame');
          const sr = s.getBoundingClientRect(), fr = f.getBoundingClientRect();
          const full = r => r.left === 0 && r.top === 0 && r.width === innerWidth && r.height === innerHeight;
          return {ok: document.fullscreenElement === s && full(sr) && full(fr),
                  element: document.fullscreenElement && document.fullscreenElement.id,
                  surface: [sr.width, sr.height], frame: [fr.width, fr.height], viewport: [innerWidth, innerHeight]};
        }""", "המשטח והמסגרת במסך מלא, בגודל המסך")
        assert state["element"] == "htmlPreviewSurface", state
        # הכפתור מוסתר מתחת למשטח שבמסך מלא, ולכן היציאה ישירה, כמו Esc
        page.evaluate("() => document.exitFullscreen()")
        poll(page, "() => document.fullscreenElement === null", "יציאה ממסך מלא")
        _scroll_page_to_the_end(page)
        after = page.evaluate(MEASURE)["frame"]
        assert after == before, (before, after)
    finally:
        ctx.close()
