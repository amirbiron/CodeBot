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
import json
from urllib.parse import urlsplit

import pytest
from bson import ObjectId

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import Touch, poll  # noqa: E402
from _fake_mongo import FakeDB  # noqa: E402

HOST = "ck.test"
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
#: דף זר שהמסגרת עוברת אליו. הוא מוגש בלי ה-CSP שלנו, ולכן במסגרת עם ``allow-scripts`` הסקריפט שלו רץ: הוא מודיע
#: שרץ, ושולח את ההודעה שהמאזין של הסימניות קיבל עד נובמבר 2026 בלי לבדוק מי שלח.
FOREIGN_PATH = "/__foreign-page"
FOREIGN_PAGE = (
    "<!doctype html><body>דף זר<script>parent.postMessage({type:'foreign-script-ran'},'*');"
    "parent.postMessage({type:'html-anchor-click',anchorId:'x',anchorText:'x'},'*');</script></body>"
)

_OIDS = (ObjectId(f"0123456789abcdef01{n:06x}") for n in itertools.count(0x7100))
#: **משתמש לכל קובץ.** המגביל של האתר (``default_limits`` ב-``webapp/app.py``, "50 per hour") סופר לפי ``user_id`` שבסשן
#: (``_client_rate_key``), והמסד והשרת משותפים לכל הקובץ: עם משתמש אחד, ריצה של כל הבדיקות עברה את המכסה, ובדיקה מאוחרת
#: קיבלה 429 על רשימת הפתקים — ולא הציגה אף פתק (נמדד, נובמבר 2026). איפוס של המגביל אינו התשובה: ב-CI ``REDIS_URL``
#: מצביע על כתובת דמה (``tests/conftest.py``), ו-``Limiter.reset`` היה זורק שם.
_OWNERS = itertools.count(7171)


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


def _file(db, *, note=None, code=HTML) -> ObjectId:
    """קובץ HTML חדש, של משתמש משלו (``_OWNERS``), ועליו — כשנמסר ``note`` — פתק עם השדות האלה."""
    oid = next(_OIDS)
    owner = next(_OWNERS)
    db["code_snippets"].insert_one({
        "_id": oid, "user_id": owner, "file_name": f"page-{oid}.html", "code": code,
        "programming_language": "html", "version": 1, "is_active": True,
    })
    if note is not None:
        db["sticky_notes"].insert_one({
            "user_id": owner, "file_id": str(oid), "content": "פתק", "color": "yellow",
            "width": 260, "height": 200, "is_minimized": False, **note,
        })
    return oid


def _owner(db, oid) -> int:
    """המשתמש שהקובץ שלו — זה שנכנס לעמוד, ושהמגביל סופר."""
    return db["code_snippets"].find_one({"_id": oid})["user_id"]


def _open(site, oid, *, viewport=None, touch=False, query="", bookmark_requests=None, wait_for_report=True):
    """העמוד, אחרי שהמנהל עלה והמסגרת דיווחה פעם ראשונה. מחזיר גם את ההודעות שהדף קיבל.

    ``bookmark_requests`` — רשימה שאליה נרשמת כל בקשת כתיבה של סימנייה (``/api/bookmarks/...``), שנענית כאן ולא מגיעה
    לשרת. ``FOREIGN_PATH`` מוגש תמיד כדף זר — בלי ה-CSP שלנו — שהקובץ יכול להוביל אליו את המסגרת.
    ``wait_for_report=False`` — רק שהמנהל עלה: מסגרת שעוברת מיד לדף זר (``meta refresh``) לא תשאיר דיווח.
    """
    b, wa, db = site
    owner = _owner(db, oid)
    client = wa.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = owner
        sess["user_data"] = {"id": owner, "first_name": "בדיקה"}
    errors: list[str] = []

    def handle(route, request):
        u = urlsplit(request.url)
        if u.hostname != HOST:
            return route.abort()
        if u.path == FOREIGN_PATH:
            return route.fulfill(status=200, content_type="text/html; charset=utf-8", body=FOREIGN_PAGE)
        if bookmark_requests is not None and request.method != "GET" and u.path.startswith("/api/bookmarks/"):
            bookmark_requests.append(u.path)
            return route.fulfill(status=200, content_type="application/json",
                                 body='{"ok": true, "action": "added", "bookmark": {}}')
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
    if wait_for_report:
        poll(page, "() => !!(window.htmlPreviewNotes && window.htmlPreviewNotes.report())", "המסגרת דיווחה")
    else:
        poll(page, "() => !!(window.htmlPreviewNotes && window.htmlPreviewNotes.hasManager())", "המנהל עלה")
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


SHORT_HTML = '<!doctype html><html dir="rtl"><body><p>קצר</p></body></html>'


@pytest.mark.parametrize("case", ["short-file", "long-file-scrolled"])
def test_a_note_dragged_past_the_bottom_keeps_its_header_inside_the_frame(site, case):
    """המשטח סביב המסגרת אינו גדל כמו לוח, ולכן גרירה אל מתחת לתחתית נעצרת כשהכותרת — ידית הגרירה — בתחתית המשטח.
    בריצת בקרה על הקוד שלפני החסימה, בקובץ הקצר, הכותרת נחתה כולה מתחת למשטח, והפתק נשמר נמוך מגובה המסמך — במקום
    ששום גלילה לא מגיעה אליו. בקובץ הארוך, אחרי גלילה, המיקום עדיין נשמר במרחב התוכן: הגלילה ועוד המיקום במסגרת."""
    _b, _wa, db = site
    scrolled = 0 if case == "short-file" else 2000
    oid = _file(db, code=SHORT_HTML if case == "short-file" else HTML,
                note={"anchor_id": "__pinned__", "position_x": 40, "position_y": scrolled + 40})
    ctx, page, errors = _open(site, oid)
    try:
        if scrolled:
            _scroll_frame(page, scrolled)
        _note_settled(page, ".sticky-note.is-pinned")
        assert page.evaluate("parseInt(document.querySelector('.sticky-note').style.top, 10)") == 40
        x, y = _drag_handle_center(page)
        surface_bottom = page.evaluate("Math.round(document.getElementById('htmlPreviewSurface')"
                                       ".getBoundingClientRect().bottom)")
        page.mouse.move(x, y)
        page.mouse.down()
        for i in range(1, 11):
            page.mouse.move(x, y + (surface_bottom + 60 - y) * i / 10)
        page.mouse.up()
        header_bottom = page.evaluate("Math.round(document.querySelector('.sticky-note .sticky-note-header')"
                                      ".getBoundingClientRect().bottom)")
        assert header_bottom == surface_bottom, (header_bottom, surface_bottom)
        style_top = page.evaluate("parseInt(document.querySelector('.sticky-note').style.top, 10)")
        assert style_top > 40, style_top
        assert _poll_saved(page, db, oid, (40, scrolled + style_top)) == (40, scrolled + style_top)
        if case == "short-file":
            doc_height = _frame(page).evaluate("document.documentElement.scrollHeight")
            assert style_top < doc_height, (style_top, doc_height)
        assert errors == []
    finally:
        ctx.close()


NOTE_GEOMETRY = "() => { const el = document.querySelector('.sticky-note'), r = el.getBoundingClientRect(); " \
                "return {left: Math.round(r.left), top: Math.round(r.top), width: Math.round(r.width), " \
                "height: Math.round(r.height), pinned: el.classList.contains('is-pinned')}; }"


@pytest.mark.parametrize("gesture", ["drag", "press", "resize"])
def test_a_touch_the_system_cancels_leaves_the_note_as_it_was(site, gesture):
    """``touchcancel`` (מעבר לאפליקציה אחרת, סיבוב המסך, דחיית כף יד — MDN) מגיע במקום ``touchend``.

    הפתק חוזר למקום ולגודל שהיו לו, שום דבר לא נשמר, טיימר הלחיצה הארוכה אינו מחליף את 📌, והמסגרת מקבלת
    שוב נגיעות. ואז נגיעה חדשה על המסגרת — שאינה נוגעת בפתק. בריצת בקרה על הקוד שלפני מאזין ה-``touchcancel``
    הגרירה נשארה דלוקה, והנגיעה החדשה הזיזה את הפתק ושמרה אותו; בלחיצה בלבד הטיימר הפך את הפתק לצמוד למסך;
    בשינוי גודל — הנגיעה החדשה המשיכה לשנות אותו."""
    _b, _wa, db = site
    oid = _file(db, note={"anchor_id": "__pinned__", "position_x": 40, "position_y": 40})
    ctx, page, errors = _open(site, oid, viewport={"width": 1112, "height": 834}, touch=True)
    saves: list[str] = []
    page.on("request", lambda r: saves.append(r.url) if r.method == "PUT" and "/api/sticky-notes/" in r.url else None)
    try:
        _note_settled(page, ".sticky-note.is-pinned")
        start = page.evaluate(NOTE_GEOMETRY)
        touch = Touch(ctx.new_cdp_session(page))
        if gesture == "resize":
            x, y = page.evaluate("() => { const r = document.querySelector('.sticky-note .sticky-note-resize')"
                                 ".getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }")
        else:
            x, y = _drag_handle_center(page)
        touch.start(x, y)
        if gesture != "press":
            for i in range(1, 9):
                touch.move(x + 20 * i, y + 15 * i)
            assert page.evaluate(NOTE_GEOMETRY) != start, "המחווה לא התחילה — הבדיקה לא בודקת כלום"
        touch.cdp.send("Input.dispatchTouchEvent", {"type": "touchCancel", "touchPoints": []})
        assert page.evaluate(NOTE_GEOMETRY) == start
        assert not page.evaluate("document.getElementById('htmlPreviewSurface')"
                                 ".classList.contains('sticky-note-gesture')")
        page.wait_for_timeout(600)  # יותר מ-``LONG_PRESS_MS`` (450)
        frame = page.evaluate(FRAME_BOX)
        touch.swipe(frame["left"] + 700, frame["top"] + 500, -120, -90)
        page.wait_for_timeout(700)  # ``debounce`` של השמירה
        assert page.evaluate(NOTE_GEOMETRY) == start
        assert saves == [], saves
        doc = next(iter(db["sticky_notes"].find({"file_id": str(oid)})))
        assert (doc["position_x"], doc["position_y"], doc["anchor_id"]) == (40, 40, "__pinned__")
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


@pytest.mark.parametrize("how", ["link", "refresh"])
def test_a_foreign_page_the_frame_navigates_to_cannot_act_for_the_user(site, how):
    """המסגרת מתירה סקריפטים בשביל המדווח, ולכן מסמך שהיא עוברת אליו — בקישור שבקובץ, או ב-``meta refresh`` — מריץ
    את הסקריפטים שלו (נעילה של ה-``sandbox`` אחרי הטעינה לא עוצרת את ה-``refresh``; ``webapp/html_preview_frame.py``).
    לכן אף מאזין בעמוד אינו מבצע פעולה בשם המשתמש על סמך הודעה מהמסגרת. עד נובמבר 2026 המאזין של הסימניות עשה את זה:
    בריצת בקרה על הקוד הקודם, ההודעה של הדף הזר שלחה בקשה ליצירת סימנייה."""
    _b, _wa, db = site
    if how == "link":
        code = f'<!doctype html><body><a id="go" href="{FOREIGN_PATH}" style="font-size:40px">קישור</a></body>'
    else:
        code = f'<!doctype html><head><meta http-equiv="refresh" content="0;url={FOREIGN_PATH}"></head><body>x</body>'
    requests: list[str] = []
    ctx, page, errors = _open(site, _file(db, code=code), bookmark_requests=requests, wait_for_report=False)
    try:
        if how == "link":
            page.frame_locator("#previewFrame").locator("#go").click()
        poll(page, "() => window.__messages.includes('foreign-script-ran')", "הדף הזר נטען במסגרת והסקריפט שלו רץ")
        assert _frame(page).url.endswith(FOREIGN_PATH)
        page.wait_for_timeout(300)
        assert requests == [], requests
        assert errors == []
    finally:
        ctx.close()


NOSCRIPT_HTML = '<!doctype html><body><p>רגיל</p><noscript><p id="fallback">הגרסה בלי JS</p></noscript></body>'


def test_noscript_content_shows_while_the_files_scripts_are_off(site):
    """הדפדפן מסתיר ``<noscript>`` לפי ה-``sandbox``, ולא לפי ה-CSP — ולכן עם ``allow-scripts`` הוא הוסתר גם כשאף
    סקריפט של הקובץ לא רץ. המדווח מציג אותו בעצמו כש"אפשר JS" כבוי (``_NOSCRIPT_JS``), כמו לפני שהיה מדווח; עם "אפשר
    JS" הוא מוסתר, כמו תמיד. בריצת בקרה בלי ``_NOSCRIPT_JS`` התוכן לא הוצג."""
    _b, _wa, db = site
    ctx, page, errors = _open(site, _file(db, code=NOSCRIPT_HTML))
    try:
        shown = _frame(page).evaluate("(() => { const el = document.getElementById('fallback'); "
                                      "return !!el && el.getBoundingClientRect().height > 0; })()")
        assert shown is True
        page.check("#toggleJs")
        poll(page, "() => document.getElementById('previewFrame').src.includes('allow=scripts')", "המסגרת במצב JS")
        poll(page, "() => !!(window.htmlPreviewNotes && window.htmlPreviewNotes.report())", "המסגרת דיווחה")
        page.wait_for_timeout(300)
        assert _frame(page).evaluate("!document.getElementById('fallback')") is True
        assert errors == []
    finally:
        ctx.close()


OWN_CSP_NOSCRIPT_HTML = ('<!doctype html><html><head><meta http-equiv="Content-Security-Policy" '
                         "content=\"script-src 'none'\"></head><body><p>רגיל</p>"
                         '<noscript><p id="fallback">הגרסה בלי JS</p></noscript></body></html>')


def test_noscript_shows_in_a_file_with_its_own_policy(site):
    """קובץ שאוסר סקריפטים ב-CSP משלו חוסם את המדווח, ולכן גם ``_NOSCRIPT_JS`` לא רץ — ועם ``allow-scripts`` הדפדפן
    הסתיר את ``<noscript>``. עכשיו קובץ כזה מוגש בלי מדווח (``declares_own_csp``), וה-``sandbox`` של התשובה מבטל את
    ``allow-scripts`` של המסגרת. בריצת בקרה על הקוד שלפני התיקון התוכן לא הוצג."""
    _b, _wa, db = site
    ctx, page, errors = _open(site, _file(db, code=OWN_CSP_NOSCRIPT_HTML), wait_for_report=False)
    try:
        # ``wait_for`` ולא ``is_visible``: האחרון אינו מחכה, ומסגרת שעוד נטענת הייתה נראית כמו תוכן מוסתר.
        page.frame_locator("#previewFrame").locator("#fallback").wait_for(state="visible", timeout=10000)
        assert errors == []
    finally:
        ctx.close()


#: הדיאלוג נגיש כשהנגיעה במרכז הכפתור או השדה הראשון שלו פוגעת בו — ולא במה שמצויר מעליו.
DIALOG_REACHABLE = """(sel) => { const m = document.querySelector(sel); if (!m) return 'אין דיאלוג';
  const t = [...m.querySelectorAll('button, input')].find((x) => x.getBoundingClientRect().width > 0);
  const r = t.getBoundingClientRect();
  const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  return (hit && m.contains(hit)) ? 'נגיש' : `הנגיעה פגעה ב-${hit && (hit.id || hit.className)}`; }"""


@pytest.mark.parametrize("dialog, menu_item, selector", [
    ("color", None, ".sticky-color-modal"),
    ("reminder", "reminder", ".sticky-reminder-modal"),
    ("archive-name", "archive", ".sticky-archive-modal"),
])
def test_the_note_dialogs_are_reachable_in_fullscreen(site, dialog, menu_item, selector):
    """המשטח עובר למסך מלא עם הפתקים, והדפדפן מצייר רק אותו. דיאלוג שנתלה ב-``body`` נוצר מתחתיו: בריצת בקרה על הקוד
    שלפני ``_dialogHost`` הנגיעה במקום הדיאלוג פגעה במסגרת (``previewFrame``), בשלושתם."""
    _b, _wa, db = site
    ctx, page, errors = _open(site, _file(db, note={"anchor_id": "__pinned__", "position_x": 40, "position_y": 40}))
    try:
        _note_settled(page, ".sticky-note.is-pinned")
        page.click("#btnFullscreen")
        poll(page, "() => document.fullscreenElement && document.fullscreenElement.id === 'htmlPreviewSurface'",
             "המשטח במסך מלא")
        if menu_item is None:
            page.click(".sticky-note .sticky-note-color")
        else:
            page.click(".sticky-note .sticky-note-more")
            page.click(f'.sticky-note .sticky-note-menu-item[data-menu-item="{menu_item}"]')
        poll(page, f"() => !!document.querySelector({selector!r})", f"הדיאלוג ({dialog}) נפתח")
        assert page.evaluate(DIALOG_REACHABLE, selector) == "נגיש"
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
    _b, wa, db = site
    client = wa.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = _owner(db, oid)
    resp = client.get(f"/note/{note['_id']}")
    assert resp.status_code == 302, resp.status_code
    assert resp.headers["Location"] == f"/html/{oid}?note={note['_id']}"


def _scroll_command_type():
    from webapp import html_preview_frame
    return html_preview_frame.SCROLL_COMMAND_TYPE


def test_a_scroll_command_is_taken_only_from_the_page_and_only_with_numbers(site):
    """הוראת הגלילה (``SCROLL_COMMAND_TYPE``) מתקבלת רק כשהשולח הוא ``parent``, ורק עם שני מספרים סופיים. במצב
    "אפשר JS" הקובץ שולח לעצמו הוראה באותו ``type`` — והמסגרת לא זזה; הדף שולח הוראה עם מחרוזת במקום מספר — ולא
    זזה; והוראה תקינה מהדף — זזה, כך שהשתיים הראשונות אינן עוברות רק כי הערוץ שבור. במוטציה בלי בדיקת השולח
    המסגרת נגללה בהוראה של הקובץ."""
    _b, _wa, db = site
    command = json.dumps(_scroll_command_type())
    code = (f'<!doctype html><html dir="rtl"><body style="margin:0">{ROWS}'
            "<script>addEventListener('load',function(){setTimeout(function(){"
            f"window.postMessage({{type:{command},x:0,y:3000}},'*');"
            "parent.postMessage({type:'self-command-sent'},'*');},300);});</script></body></html>")
    ctx, page, errors = _open(site, _file(db, code=code))
    try:
        page.check("#toggleJs")
        poll(page, "() => window.__messages.includes('self-command-sent')", "הקובץ שלח לעצמו הוראת גלילה")
        page.wait_for_timeout(300)
        assert _frame(page).evaluate("window.scrollY") == 0

        send = (f"(y) => document.getElementById('previewFrame').contentWindow"
                f".postMessage({{type: {command}, x: 0, y}}, '*')")
        page.evaluate(send, "3000")
        page.wait_for_timeout(300)
        assert _frame(page).evaluate("window.scrollY") == 0

        page.evaluate(send, 3000)
        poll(page, "() => window.htmlPreviewNotes.report().y === 3000", "הוראה תקינה מהדף גוללת")
        assert errors == []
    finally:
        ctx.close()


def test_the_link_of_a_note_deep_in_the_file_scrolls_the_frame_to_it(site):
    """פתק שמתחת לחלון המסגרת: הקישור גולל את **התוכן שבמסגרת** אליו (הוראת גלילה למדווח), והפתק מוצג יחד עם התוכן.
    בריצת בקרה על הקוד שלפני התיקון, ``scrollIntoView`` גלל את המשטח עצמו: המסגרת יצאה מהמסך, המסגרת לא נגללה (0),
    והפתק נשאר מוסתר.

    ובסוף — **המשטח אינו נגלל בכלל** (``overflow: clip``): פתק שני, רחוק מתחת, יוצר גלישה במשטח, וגלילה שלו מקוד
    נשארת 0. עם ``hidden`` בלבד היא זזה (מוטציה)."""
    _b, _wa, db = site
    oid = _file(db, note={"anchor_id": "__pinned__", "position_x": 40, "position_y": 3000})
    note = next(iter(db["sticky_notes"].find({"file_id": str(oid)})))
    db["sticky_notes"].insert_one({"user_id": _owner(db, oid), "file_id": str(oid), "content": "רחוק",
                                   "color": "yellow", "width": 260, "height": 200, "is_minimized": False,
                                   "anchor_id": "__pinned__", "position_x": 400, "position_y": 7000})
    ctx, page, errors = _open(site, oid, query=f"?note={note['_id']}")
    try:
        frame_before = page.evaluate(FRAME_BOX)
        selector = f'.sticky-note[data-note-id="{note["_id"]}"]'
        poll(page, f"() => {{ const el = document.querySelector({selector!r}),"
                   " f = document.getElementById('previewFrame'); if (!el) return false;"
                   " const r = el.getBoundingClientRect(), fr = f.getBoundingClientRect();"
                   " return el.style.visibility !== 'hidden' && r.top >= fr.top && r.bottom <= fr.bottom; }",
             "הפתק מוצג כולו בתוך המסגרת")
        assert page.evaluate(FRAME_BOX) == frame_before
        assert page.evaluate("document.getElementById('htmlPreviewSurface').scrollTop") == 0
        _note_settled(page, selector)
        report_y = page.evaluate("window.htmlPreviewNotes.report().y")
        note_top = page.evaluate(f"Math.round(document.querySelector({selector!r}).getBoundingClientRect().top)")
        assert note_top == frame_before["top"] + 3000 - report_y, (note_top, frame_before, report_y)
        assert page.evaluate("(() => { const s = document.getElementById('htmlPreviewSurface');"
                             " const overflowing = s.scrollHeight > s.clientHeight; s.scrollTop = 500;"
                             " return [overflowing, s.scrollTop]; })()") == [True, 0]
        assert errors == []
    finally:
        ctx.close()
