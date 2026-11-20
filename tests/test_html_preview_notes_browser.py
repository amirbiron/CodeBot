"""פתקים על תצוגת ה-HTML — בכרומיום, בעמוד ``/html/<id>`` האמיתי.

מה שרק דפדפן יכול להראות: שה-CSP של ``/raw_html`` (``webapp/html_preview_frame.py``) מריץ את מדווח הגלילה וחוסם
את הסקריפטים של הקובץ; שפתק "על הקובץ" נע עם הגלילה בתוך המסגרת, לפי הדיווחים (``html-preview-notes.js``); שפתק
"צמוד למסך" נמדד מהמסך ולא מהכרטיס שסביב המסגרת; שגרירה מעל המסגרת — בעכבר ובמגע — מגיעה עד הסוף; ושתחתית
המסגרת אינה נחתכת. ההיגיון של המנהל ננעל ב-node (``tests/sticky-notes-target.test.js``, הבדיקות שנפתחות
ב"מסגרת:"), ומה שהשרת שולח — ב-``tests/test_html_preview_frame.py``.

**העמוד אמיתי, המסד לא** — אותה דרך של ``tests/test_bookmarks_disabled_browser.py``: הראוטים של Flask דרך
``test_client``, והמסמכים בדמה (``_fake_mongo``), כולל ה-API של הפתקים. כותרת ה-CSP מועברת מהתשובה לדפדפן,
אחרת הבדיקה לא הייתה בודקת את האכיפה. הדמה נותנת לפתק חדש ``ObjectId``, כמו מונגו — המזהה המספרי שלה נדחה
בעדכון (``Invalid note_id``).

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
from _browser_harness import Touch, poll  # noqa: E402
from _fake_mongo import FakeDB  # noqa: E402

HOST = "ck.test"
OWNER_ID = 7171
FORWARDED_HEADERS = ("content-type", "cache-control", "etag", "content-security-policy", "x-content-type-options")
ROWS = "".join(f'<p id="p{i}" style="margin:0;height:40px">שורה {i}</p>' for i in range(200))
#: הסקריפט של הקובץ מודיע לדף שהוא רץ. בלי "אפשר JS" ה-CSP חוסם אותו; עם — הוא רץ, ומזייף דיווח גלילה: שני דיווחים
#: פגומים **אחרי** שהמדווח כבר דיווח וענה לבקשה של הדף בטעינה, ואז הודעה שהזיוף נשלח. זיוף שהיה נשלח לפני המדווח היה
#: נדרס בדיווח האמיתי, והבדיקה לא הייתה יכולה ליפול.
USER_SCRIPT = (
    "<script>parent.postMessage({type:'user-script-ran'},'*');"
    "addEventListener('load',function(){setTimeout(function(){"
    "parent.postMessage({type:'codebot:html-frame-scroll',x:'0',y:5000,"
    "scrollWidth:900,clientWidth:900,direction:'rtl'},'*');"
    "parent.postMessage({type:'codebot:html-frame-scroll',x:NaN,y:5000,"
    "scrollWidth:900,clientWidth:900,direction:'rtl'},'*');"
    "parent.postMessage({type:'user-forged-sent'},'*');"
    "},300);});"
    "</script>"
)
HTML = f'<!doctype html><html dir="rtl"><body style="margin:0">{ROWS}{USER_SCRIPT}</body></html>'

_ADDRESSES = itertools.count(1)
_OIDS = (ObjectId(f"0123456789abcdef01{n:06x}") for n in itertools.count(0x7100))


@pytest.fixture(scope="module")
def site(chromium_executable):
    import webapp.app as wa

    db = FakeDB()
    notes = db["sticky_notes"]
    insert = notes.insert_one

    def insert_with_object_id(doc):
        doc = dict(doc)
        doc.setdefault("_id", ObjectId())
        return insert(doc)

    notes.insert_one = insert_with_object_id
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
                yield b, wa, db
            finally:
                b.close()


def _file(db, *, note=None) -> ObjectId:
    """קובץ HTML חדש למשתמש, ועליו — כשנמסר ``note`` — פתק עם השדות האלה."""
    oid = next(_OIDS)
    db["code_snippets"].insert_one({
        "_id": oid, "user_id": OWNER_ID, "file_name": f"page-{oid}.html", "code": HTML,
        "programming_language": "html", "version": 1, "is_active": True,
    })
    if note is not None:
        db["sticky_notes"].insert_one({
            "user_id": OWNER_ID, "file_id": str(oid), "content": "פתק", "color": "yellow",
            "width": 260, "height": 200, "is_minimized": False, **note,
        })
    return oid


def _open(site, oid, *, viewport=None, touch=False, query=""):
    """העמוד, אחרי שהמנהל עלה והמסגרת דיווחה פעם ראשונה. מחזיר גם את ההודעות שהדף קיבל."""
    b, wa, _db = site
    client = wa.app.test_client()
    client.environ_base["HTTP_X_FORWARDED_FOR"] = f"192.0.2.{next(_ADDRESSES) % 250 + 1}"
    with client.session_transaction() as sess:
        sess["user_id"] = OWNER_ID
        sess["user_data"] = {"id": OWNER_ID, "first_name": "בדיקה"}
    errors: list[str] = []

    def handle(route, request):
        u = urlsplit(request.url)
        if u.hostname != HOST:
            return route.abort()
        target = u.path + (f"?{u.query}" if u.query else "")
        r = client.open(target, method=request.method, data=request.post_data_buffer,
                        headers={"Content-Type": request.headers.get("content-type", "")})
        headers = {k: v for k, v in r.headers.items() if k.lower() in FORWARDED_HEADERS}
        route.fulfill(status=r.status_code, body=r.data, headers=headers)

    options = {"viewport": viewport or {"width": 1280, "height": 800}, "locale": "he-IL"}
    if touch:
        options.update(is_mobile=True, has_touch=True)
    ctx = b.new_context(**options)
    ctx.route("**/*", handle)
    ctx.add_init_script("window.__messages = []; addEventListener('message', (e) => "
                        "window.__messages.push(e.data && e.data.type))")
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"http://{HOST}/html/{oid}{query}")
    poll(page, "() => !!(window.htmlPreviewNotes && window.htmlPreviewNotes.report())", "המסגרת דיווחה")
    return ctx, page, errors


def _frame(page):
    return next(f for f in page.frames if f != page.main_frame)


def _scroll_frame(page, y):
    _frame(page).evaluate(f"window.scrollTo(0, {y})")
    poll(page, f"() => window.htmlPreviewNotes.report().y === {y}", f"דיווח על גלילה ל-{y}")


def _note_settled(page, selector):
    """הפתק מוצג, ואנימציית הכניסה שלו הסתיימה.

    ``noteAppear`` (``sticky-notes.css``) מגדילה את הפתק מ-``scale(.9)``: מלבן שנמדד באמצעה זז בכמה פיקסלים מהמקום
    שהפתק יעמוד בו — וזה בדיוק מה שהבדיקות כאן מודדות.
    """
    poll(page, f"() => {{ const el = document.querySelector({selector!r}); "
               "return !!el && el.getAnimations().length === 0; }", f"{selector} מוצג ונח")


NOTE_BOX = "() => { const r = document.querySelector('.sticky-note').getBoundingClientRect(); " \
           "return {left: Math.round(r.left), top: Math.round(r.top), bottom: Math.round(r.bottom)}; }"
FRAME_BOX = "() => { const r = document.getElementById('previewFrame').getBoundingClientRect(); " \
            "return {left: Math.round(r.left), top: Math.round(r.top), bottom: Math.round(r.bottom)}; }"


def test_the_frame_reports_its_scroll_and_the_files_own_script_is_blocked(site):
    _b, _wa, db = site
    ctx, page, errors = _open(site, _file(db))
    try:
        report = page.evaluate("window.htmlPreviewNotes.report()")
        assert report["y"] == 0 and report["direction"] == "rtl", report
        assert report["scrollWidth"] > 0 and report["clientWidth"] > 0, report
        page.wait_for_timeout(300)
        assert "user-script-ran" not in page.evaluate("window.__messages")
        assert errors == []
    finally:
        ctx.close()


def test_a_pinned_note_moves_with_the_scroll_inside_the_frame_and_hides_when_it_leaves(site):
    _b, _wa, db = site
    ctx, page, errors = _open(site, _file(db, note={"anchor_id": "__pinned__", "position_x": 40, "position_y": 600}))
    try:
        _note_settled(page, ".sticky-note.is-pinned")
        frame = page.evaluate(FRAME_BOX)
        start = page.evaluate(NOTE_BOX)
        assert start["top"] == frame["top"] + 600, (start, frame)

        _scroll_frame(page, 450)
        moved = page.evaluate(NOTE_BOX)
        assert moved["top"] == start["top"] - 450, (start, moved)
        assert page.evaluate("document.querySelector('.sticky-note').style.visibility") == ""

        _scroll_frame(page, 3000)
        assert page.evaluate("document.querySelector('.sticky-note').style.visibility") == "hidden"
        assert errors == []
    finally:
        ctx.close()


def test_a_report_from_anywhere_but_the_frame_is_ignored(site):
    """``origin`` של מסגרת מבודדת הוא ``"null"``, ולכן השולח מזוהה לפי ``source`` — וכאן הוא העמוד עצמו."""
    _b, _wa, db = site
    ctx, page, errors = _open(site, _file(db))
    try:
        page.evaluate("window.postMessage({type: 'codebot:html-frame-scroll', x: 0, y: 4000, scrollWidth: 900, "
                      "clientWidth: 900, direction: 'rtl'}, '*')")
        page.wait_for_timeout(300)
        assert page.evaluate("window.htmlPreviewNotes.report().y") == 0
        assert errors == []
    finally:
        ctx.close()


def test_with_scripts_on_the_files_script_runs_and_its_forged_reports_are_ignored(site):
    _b, _wa, db = site
    ctx, page, errors = _open(site, _file(db))
    try:
        page.check("#toggleJs")
        poll(page, "() => window.__messages.includes('user-script-ran')", "הסקריפט של הקובץ רץ")
        poll(page, "() => window.__messages.includes('user-forged-sent')", "הזיוף נשלח")
        page.wait_for_timeout(200)
        report = page.evaluate("window.htmlPreviewNotes.report()")
        assert report["y"] == 0 and isinstance(report["x"], (int, float)), report
        assert "allow=scripts" in page.evaluate("document.getElementById('previewFrame').src")
        assert "report_scroll=1" in page.evaluate("document.getElementById('previewFrame').src")
        new_window = page.evaluate("document.getElementById('btnNewWindow').getAttribute('href')")
        assert "allow" not in new_window and "report_scroll" not in new_window, new_window
        assert errors == []
    finally:
        ctx.close()


def test_a_note_pinned_to_the_screen_is_measured_from_the_screen(site):
    """``backdrop-filter`` של ``.glass-card`` היה הופך את הכרטיס למכל של פתק ``fixed``: הפתק נמדד מראש הכרטיס."""
    _b, _wa, db = site
    ctx, page, errors = _open(site, _file(db, note={"anchor_id": "__floating__", "position_x": 300, "position_y": 200}))
    try:
        _note_settled(page, ".sticky-note.is-floating")
        box = page.evaluate("() => { const el = document.querySelector('.sticky-note'); "
                            "const r = el.getBoundingClientRect();"
                            " return {top: Math.round(r.top), styleTop: parseInt(el.style.top, 10),"
                            " left: Math.round(r.left), styleLeft: parseInt(el.style.left, 10)}; }")
        assert box["top"] == box["styleTop"] and box["left"] == box["styleLeft"], box
        fab = page.evaluate("() => Math.round(innerHeight - document.querySelector('.sticky-note-fab')"
                            ".getBoundingClientRect().bottom)")
        assert 0 <= fab < 60, fab
        assert errors == []
    finally:
        ctx.close()


def _drag_handle_center(page):
    return page.evaluate("() => { const r = document.querySelector('.sticky-note .sticky-note-drag')"
                         ".getBoundingClientRect();"
                         " return [r.left + r.width / 2, r.top + r.height / 2]; }")


def _poll_saved(page, db, oid, expected):
    """המיקום במסד — לא מה שהממשק אמר. השמירה יוצאת אחרי ``debounce``, ולכן נדגמת."""
    for _ in range(50):
        doc = next(iter(db["sticky_notes"].find({"file_id": str(oid)})), None)
        got = (doc.get("position_x"), doc.get("position_y")) if doc else None
        if got == expected:
            return got
        page.wait_for_timeout(100)
    return got


def test_dragging_a_note_over_the_frame_with_the_mouse_follows_the_pointer(site):
    """עם הכפתור לחוץ, תנועה שמגיעה אל מעל המסגרת — ולא אל מעל הפתק — אינה מגיעה לחלון, וגם השחרור לא.

    בגרירה איטית הסמן נשאר מעל הפתק, שנע איתו, ולכן היא עוברת גם בלי התיקון (נבדק במוטציה). כאן העכבר מקדים
    את הפתק בקפיצה אחת, כמו בתנועה מהירה: הוא נוחת מחוץ לפתק, מעל המסגרת. בזמן מחווה המסגרת אינה מקבלת אירועי
    מצביע (``sticky-note-gesture``), והתנועה והשחרור מגיעים לחלון.
    """
    _b, _wa, db = site
    oid = _file(db, note={"anchor_id": "__pinned__", "position_x": 40, "position_y": 40})
    ctx, page, errors = _open(site, oid)
    try:
        _note_settled(page, ".sticky-note.is-pinned")
        start = page.evaluate(NOTE_BOX)
        x, y = _drag_handle_center(page)
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + 300, y + 260)
        target = page.evaluate(f"(() => {{ const t = document.elementFromPoint({x + 300}, {y + 260}); "
                               "return t && t.closest('.sticky-note') ? 'note' : (t && t.id); })()")
        page.mouse.up()
        end = page.evaluate(NOTE_BOX)
        assert (end["left"] - start["left"], end["top"] - start["top"]) == (300, 260), (start, end, target)
        assert not page.evaluate("document.getElementById('htmlPreviewSurface')"
                                 ".classList.contains('sticky-note-gesture')")
        assert _poll_saved(page, db, oid, (340, 300)) == (340, 300)
        assert errors == []
    finally:
        ctx.close()


def test_dragging_a_note_over_the_frame_by_touch_on_a_tablet(site):
    _b, _wa, db = site
    oid = _file(db, note={"anchor_id": "__pinned__", "position_x": 40, "position_y": 40})
    ctx, page, errors = _open(site, oid, viewport={"width": 1112, "height": 834}, touch=True)
    try:
        _note_settled(page, ".sticky-note.is-pinned")
        start = page.evaluate(NOTE_BOX)
        x, y = _drag_handle_center(page)
        Touch(ctx.new_cdp_session(page)).swipe(x, y, 160, 120, steps=10)
        end = page.evaluate(NOTE_BOX)
        assert (end["left"] - start["left"], end["top"] - start["top"]) == (160, 120), (start, end)
        assert _poll_saved(page, db, oid, (200, 160)) == (200, 160)
        assert errors == []
    finally:
        ctx.close()


@pytest.mark.parametrize("width, height", [(1280, 700), (834, 1112), (1112, 834), (390, 844)],
                         ids=["desktop", "tablet-portrait", "tablet-landscape", "phone"])
def test_the_bottom_of_the_frame_is_not_cut_off(site, width, height):
    """עד נובמבר 2026 המסגרת קיבלה את כל גובה המכל מתחת לשורת הכלים, ו-``overflow: hidden`` חתך ממנה 28 פיקסלים
    (85 בטלפון) — סוף הקובץ לא נראה בשום גלילה. נמדד על הקוד שלפני התיקון באותם ארבעה גדלים."""
    _b, _wa, db = site
    ctx, page, errors = _open(site, _file(db), viewport={"width": width, "height": height})
    try:
        hidden = page.evaluate("() => { const c = document.querySelector('.preview-container'), "
                               "f = document.getElementById('previewFrame'); const cr = c.getBoundingClientRect(); "
                               "return Math.round(f.getBoundingClientRect().bottom - (cr.bottom - "
                               "parseFloat(getComputedStyle(c).borderBottomWidth))); }")
        assert hidden <= 0, hidden
        assert errors == []
    finally:
        ctx.close()


def test_the_link_of_a_note_on_an_html_file_opens_it_in_the_browser_view(site):
    """``/note/<id>`` — הקישור של התראות, הפעמון ו"פתקים אחרונים" — נוחת על התצוגה הזו, והפתק נמצא בה."""
    _b, _wa, db = site
    oid = _file(db, note={"anchor_id": "__pinned__", "position_x": 40, "position_y": 900})
    note = next(iter(db["sticky_notes"].find({"file_id": str(oid)})))
    ctx, page, errors = _open(site, oid, query=f"?note={note['_id']}")
    try:
        assert page.url.endswith(f"/html/{oid}?note={note['_id']}")
        _note_settled(page, ".sticky-note.is-pinned")
        assert errors == []
    finally:
        ctx.close()
    _b, wa, _db = site
    client = wa.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = OWNER_ID
    resp = client.get(f"/note/{note['_id']}")
    assert resp.status_code == 302, resp.status_code
    assert resp.headers["Location"] == f"/html/{oid}?note={note['_id']}"
