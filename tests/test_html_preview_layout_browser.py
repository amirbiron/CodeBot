"""תצוגת הדפדפן לקובץ HTML (``/html/<id>``, ``html_preview.html``) ממלאת את המסך — נמדד בכרומיום, בעמוד האמיתי.

כשגוללים את העמוד עד הסוף: בראש המסך נמצאת שורת הכלים של התצוגה (JS, מסך מלא, חלון חדש), ושורת קוד/הורד/חזור
שמעליה מחוץ למסך; ומסביב לכרטיס — הרווח של ``--html-preview-gutter`` מכל צד, ולא יותר. נבדק בשלושה רוחבים, ובטלפון
בערכה כהה, כי ``dark-mode.css`` נותן ל-``.glass-card`` ריפוד משלו במסך צר.

**וסוף הדף המוצג נגיש.** עד התיקון ה-iframe קיבל 100% מגובה הכרטיס, ושורת הכלים ישבה מעליו באותו כרטיס; מה שגלש
נחתך ב-``overflow: hidden``, ותחתית הדף לא הייתה נגישה בשום גלילה. הבדיקה הזו, על הקוד שלפני התיקון (כרומיום 153,
20.11.2026): 28 פיקסלים בטאבלט ובמחשב, ו-93 בטלפון, ששם שורת הכלים נשברת לכמה שורות. כאן גוללים את התוכן שבתוך
ה-iframe עד הסוף, ובודקים שהסמן שבתחתית הדף נמצא כולו בשטח שרואים.

**העמוד אמיתי, המסד לא** — אותה דרך של ``tests/test_bookmarks_disabled_browser.py``: הראוט של Flask דרך
``test_client``, והקובץ בדמה (``_fake_mongo``). FontAwesome מגיע מ-CDN, וכאן כל בקשה לדומיין אחר נחסמת, ולכן העמוד
עובר למצב ``no-fa-icons`` והכפתורים מציגים כיתוב במקום אייקון. זה מצב אמיתי של העמוד, והבדיקות לא נשענות על
גודל מוחלט של כפתור: גודל הכפתורים בשורת הכלים נמדד מול כפתור רגיל באותו עמוד.

מדולג כשאין Chromium.
"""

from __future__ import annotations

import itertools
import time
from urllib.parse import urlsplit

import pytest
from bson import ObjectId

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import WAIT_S, poll  # noqa: E402
from _fake_mongo import FakeDB  # noqa: E402

HOST = "ck.test"
OWNER_ID = 7164
HTML_OID = ObjectId("0123456789abcdef0123ab71")
#: דף ארוך מהמסגרת, שבתחתיתו סמן — כדי לבדוק שאפשר להגיע לסוף שלו.
PAGE = (
    '<!doctype html><html><body style="margin:0">'
    '<div style="height:2000px">דף ארוך</div>'
    '<div id="end" style="height:40px">סוף</div>'
    "</body></html>"
)
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
  const card = frame.parentElement;
  const toolbar = document.getElementById('toggleJs').closest('label').parentElement;
  const headerRow = document.querySelector('a[href^="/download/"]').parentElement;
  const rect = el => {
    const r = el.getBoundingClientRect();
    return {left: r.left, top: r.top, right: r.right, bottom: r.bottom, height: r.height};
  };
  const cardStyle = getComputedStyle(card);
  const c = rect(card);
  return {
    vw: innerWidth, vh: innerHeight,
    scrollTop: document.body.scrollTop,
    scrollable: document.body.scrollHeight > document.body.clientHeight,
    gutter: parseFloat(getComputedStyle(document.querySelector('.main-content')).paddingBottom),
    card: c,
    cardVisibleBottom: cardStyle.overflowY === 'visible' ? Infinity : c.bottom - parseFloat(cardStyle.borderBottomWidth),
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


def _settled_box(locator) -> dict:
    """המיקום של האלמנט אחרי שהגלילה שבתוך ה-iframe נעצרה: שתי קריאות רצופות זהות.

    לא ``poll``: המסגרת בסנדבוקס בלי ``allow-scripts``, ולכן את התנאי מודדים מבחוץ, דרך המיקום שהדפדפן מדווח.
    """
    deadline = time.monotonic() + WAIT_S
    last = None
    while True:
        box = locator.bounding_box()
        assert box is not None, "הסמן שבתחתית הדף לא נמצא"
        if box == last:
            return box
        if time.monotonic() > deadline:
            raise AssertionError(f"הגלילה בתוך המסגרת לא נעצרה תוך {WAIT_S} שניות — אחרון: {box!r}")
        last = box
        time.sleep(0.15)


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
def test_the_end_of_the_shown_page_is_reachable(site, name, width, height, mode):
    """גלילה בתוך ה-iframe עד הסוף מביאה את הסמן שבתחתית הדף, כולו, לשטח שרואים."""
    ctx, page = _open(site, width, height, mode)
    try:
        m = page.evaluate(MEASURE)
        frame_box = m["frame"]
        x = (frame_box["left"] + frame_box["right"]) / 2
        y = (frame_box["top"] + min(frame_box["bottom"], m["vh"])) / 2
        page.mouse.move(x, y)
        for _ in range(6):
            page.mouse.wheel(0, 1500)
        inner = next(f for f in page.frames if f is not page.main_frame)
        _scroll_page_to_the_end(page)
        box = _settled_box(inner.locator("#end"))
        m = page.evaluate(MEASURE)
        visible_bottom = min(m["vh"], m["cardVisibleBottom"], m["frame"]["bottom"])
        hidden = box["y"] + box["height"] - visible_bottom
        assert hidden <= 0.5, f"{hidden:.2f} פיקסלים מתחתית הדף אינם נראים (סמן: {box}, הגבול: {visible_bottom})"
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
    """המסגרת היא עכשיו פריט flex. "מסך מלא" עדיין מציג אותה על כל המסך, ויציאה מחזירה אותה למקומה."""
    ctx, page = _open(site, 1333, 680, "dark")
    try:
        before = page.evaluate(MEASURE)["frame"]
        page.click("#btnFullscreen")
        state = poll(page, """() => {
          const f = document.getElementById('previewFrame');
          const r = f.getBoundingClientRect();
          return {ok: document.fullscreenElement === f && r.width === innerWidth && r.height === innerHeight,
                  fullscreen: document.fullscreenElement === f, w: r.width, h: r.height, vw: innerWidth, vh: innerHeight};
        }""", "המסגרת במסך מלא, בגודל המסך")
        assert state["fullscreen"]
        # הכפתור מוסתר מתחת למסגרת שבמסך מלא, ולכן היציאה ישירה, כמו Esc
        page.evaluate("() => document.exitFullscreen()")
        poll(page, "() => document.fullscreenElement === null", "יציאה ממסך מלא")
        _scroll_page_to_the_end(page)
        after = page.evaluate(MEASURE)["frame"]
        assert after == before, (before, after)
    finally:
        ctx.close()
