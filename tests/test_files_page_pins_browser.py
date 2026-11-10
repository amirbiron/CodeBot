"""נעיצת פתקים לעמוד הקבצים בכרומיום, מול הוובאפ האמיתי **ומונגו אמיתי** — הזרימה כולה, כמו שמשתמש עובר בה.

**למה מסד אמיתי:** הזרימה עוברת בין הלוח (📎 בתפריט ⋮) לעמוד הקבצים, וכל אחד מהם קורא את מה שהשני כתב.
כל המודולים של הוובאפ מגיעים למסד דרך ``webapp.app.get_db``, ולכן הוא היחיד שמוחלף — במסד זמני.

**מה נמדד:** נעיצה מהלוח והמתג המסומן; הכרטיס בעמוד הקבצים, הראשון שננעץ ראשון מימין; הפתק שנפתח
מעליו — במרכז, כחלון, עם ``inert`` על התוכן והמיקוד, ו-``Escape`` שמחזיר את המיקוד לכרטיס; הסרה
והעברה לארכיון מתוך הפתק הפתוח; בטלפון — כמה כרטיסים נכנסים ו-"+N" (שנקרא "+N" ולא "N+"), הרשימה שלו,
והנעיצה שנחסמת כשבמסך אין מקום; פס הכותרות בחלון נמוך ובזמן הכרזה; עמוד בלי נעוצים — זהה לעמוד שלפני
השינוי; מצב השגיאה; ושורה שאינה גולשת בשום רוחב.

**מה לא נבדק כאן:** מכשיר אמיתי — זו אמולציה בכרומיום.

מדולג כשאין Chromium, או כשאין שרת מונגו (``mongo_reachable`` מדלג רק על "אין שרת").
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")
pytest.importorskip("pymongo")

from bson import ObjectId  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import poll  # noqa: E402
from _note_threads_harness import insert_board, mongo_reachable, temp_database  # noqa: E402

pytestmark = pytest.mark.skipif(not mongo_reachable(), reason="דורש MONGODB_URL עם שרת מונגו נגיש")

#: המשתמש של ``admin_live_server`` (``ADMIN_USER_IDS=1``).
USER = 1
FIELD = "files_page_pinned_at"
DESKTOP = {"width": 1280, "height": 800}
PHONE = {"width": 390, "height": 844}
PHONE_LANDSCAPE = {"width": 844, "height": 390}


@pytest.fixture
def db(monkeypatch):
    import webapp.app as app_mod

    with temp_database("codebot_files_pins_browser_") as database:
        monkeypatch.setattr(app_mod, "get_db", lambda: database)
        yield database


@contextlib.contextmanager
def opened(server, executable, path, viewport=DESKTOP, *, local_storage=None):
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=executable)
        except Exception as exc:  # pragma: no cover - תלוי בסביבה
            pytest.skip(f"אין Chromium זמין: {exc}")
        try:
            context = browser.new_context(viewport=viewport, locale="he-IL")
            context.add_cookies([{"name": "session", "value": server.session_cookie,
                                  "domain": "127.0.0.1", "path": "/"}])
            if local_storage:
                script = "".join(f"localStorage.setItem({k!r}, {v!r});" for k, v in local_storage.items())
                context.add_init_script(f"try {{ {script} }} catch (e) {{}}")
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.on("dialog", lambda dialog: dialog.accept())
            page.goto(f"{server.base_url}{path}", wait_until="load")
            page.js_errors = errors
            yield page
        finally:
            browser.close()


def board_note(db, board: str, title: str, *, pinned_minutes=None, y: int = 40) -> str:
    oid = ObjectId()
    now = datetime.now(timezone.utc)
    doc = {"_id": oid, "user_id": USER, "board_id": board, "content": f"# {title}\nגוף", "title": title,
           "color": "yellow", "mode": "surface", "position_x": 40, "position_y": y, "width": 420, "height": 300,
           "created_at": now, "updated_at": now}
    if pinned_minutes is not None:
        doc[FIELD] = now - timedelta(hours=1) + timedelta(minutes=pinned_minutes)
    db.sticky_notes.insert_one(doc)
    return str(oid)


def card_ids(page) -> list[str]:
    return page.evaluate("() => [...document.querySelectorAll('#filesPageCards > [data-note-id]')]"
                         ".map(c => c.getAttribute('data-note-id'))")


def wait_cards(page, count: int) -> None:
    # ``wait_for_function`` חסום ב-CSP של העמודים (``unsafe-eval``) — התנאי נדגם (``poll``).
    poll(page, f"() => document.querySelectorAll('#filesPageCards > [data-note-id]').length === {count}",
         f"{count} כרטיסים בשורה")


def open_card(page, note_id: str):
    page.locator(f'#filesPageCards [data-note-id="{note_id}"]').click()
    note = page.locator(f'.sticky-note.is-overlay-open[data-note-id="{note_id}"]')
    note.wait_for(state="visible", timeout=10000)
    note.evaluate("e => Promise.all(e.getAnimations().map(a => a.finished))")
    return note


def menu_item(page, note, item: str):
    note.locator(".sticky-note-more").click()
    return page.locator(f'.sticky-note-menu-item[data-menu-item="{item}"]')


def test_pin_from_the_board_and_open_it_on_the_files_page(db, admin_live_server, chromium_executable):
    board = insert_board(db, USER)
    first = board_note(db, board, "ראשון", pinned_minutes=0, y=40)
    second = board_note(db, board, "שני", y=400)

    with opened(admin_live_server, chromium_executable, f"/boards/{board}") as page:
        note = page.locator(f'.sticky-note[data-note-id="{second}"]')
        note.wait_for(state="visible", timeout=10000)
        item = menu_item(page, note, "files-page-pin")
        assert item.get_attribute("role") == "menuitemcheckbox"
        assert item.get_attribute("aria-checked") == "false"
        item.click()
        poll(page, "() => !!document.querySelector('.ck-toast')", "הודעה")
        assert isinstance(db.sticky_notes.find_one({"_id": ObjectId(second)})[FIELD], datetime)
        assert menu_item(page, note, "files-page-pin").get_attribute("aria-checked") == "true"
        assert page.js_errors == []

    with opened(admin_live_server, chromium_executable, "/files") as page:
        wait_cards(page, 2)
        assert card_ids(page) == [first, second], "הראשון שננעץ ראשון"
        # מימין לשמאל: הראשון קרוב לכותרת, כלומר מימין לשני
        rights = page.evaluate("() => [...document.querySelectorAll('#filesPageCards > [data-note-id]')]"
                               ".map(c => c.getBoundingClientRect().right)")
        assert rights[0] > rights[1]
        stored_before = db.sticky_notes.find_one({"_id": ObjectId(first)})

        el = open_card(page, first)
        info = page.evaluate("""() => {
            const n = document.querySelector('.sticky-note.is-overlay-open'); const r = n.getBoundingClientRect();
            return {role: n.getAttribute('role'), left: r.left, width: r.width, vw: innerWidth,
                    inert: document.querySelector('main.main-content').inert, focused: document.activeElement === n,
                    pin: !!n.querySelector('.sticky-note-pin')};
        }""")
        assert info["role"] == "dialog" and info["inert"] is True and info["focused"] is True
        assert abs(info["left"] - (info["vw"] - info["width"]) / 2) <= 1, info
        assert info["width"] == 420, "הגודל השמור"
        assert info["pin"] is False, "אין 📌 בפתק שנפתח מעל עמוד"
        items = menu_item(page, el, "files-page-pin")
        assert items.get_attribute("aria-checked") == "true"
        page.keyboard.press("Escape")   # התפריט
        page.keyboard.press("Escape")   # הפתק
        poll(page, "() => document.getElementById('filesPageNoteOverlay').hidden", "השכבה נסגרה")
        page.wait_for_timeout(300)
        state = page.evaluate("() => ({inert: document.querySelector('main.main-content').inert, "
                              "focus: document.activeElement && document.activeElement.getAttribute('data-note-id')})")
        assert state == {"inert": False, "focus": first}, state
        stored_after = db.sticky_notes.find_one({"_id": ObjectId(first)})
        # הפתיחה מעל העמוד אינה נוגעת במקום של הפתק בלוח ובמצב שלו
        for key in ("position_x", "position_y", "mode", "board_id"):
            assert stored_after.get(key) == stored_before.get(key), key
        assert page.js_errors == []


def test_unpin_and_archive_from_the_opened_note_take_the_card_down(db, admin_live_server, chromium_executable):
    board = insert_board(db, USER)
    a = board_note(db, board, "להסרה", pinned_minutes=0)
    b = board_note(db, board, "לארכיון", pinned_minutes=1)

    with opened(admin_live_server, chromium_executable, "/files") as page:
        wait_cards(page, 2)
        el = open_card(page, a)
        menu_item(page, el, "files-page-pin").click()
        wait_cards(page, 1)
        assert card_ids(page) == [b]
        assert FIELD not in db.sticky_notes.find_one({"_id": ObjectId(a)})
        assert db.sticky_notes.find_one({"_id": ObjectId(a)})["board_id"] == board, "נשאר בלוח"
        assert page.evaluate("() => document.getElementById('filesPageNoteOverlay').hidden") is True
        # המיקוד עבר לכרטיס שנשאר. השורה נבנתה מחדש בהסרה, ולכן אלמנט השכן שנשמר לפניה כבר לא היה
        # ב-DOM — ועד התיקון המיקוד נפל ל-``body``.
        assert page.evaluate(
            "() => document.activeElement && document.activeElement.getAttribute('data-note-id')"
        ) == b

        el = open_card(page, b)
        menu_item(page, el, "archive").click()
        poll(page, "() => document.getElementById('filesPageNotes').hidden", "האזור ירד")
        stored = db.sticky_notes.find_one({"_id": ObjectId(b)})
        assert isinstance(stored.get("archived_at"), datetime) and FIELD not in stored
        assert page.js_errors == []


def test_on_a_phone_the_row_shows_what_fits_and_plus_n_opens_the_rest(db, admin_live_server, chromium_executable):
    board = insert_board(db, USER)
    ids = [board_note(db, board, f"נעוץ {i}", pinned_minutes=i) for i in range(4)]

    with opened(admin_live_server, chromium_executable, "/files", PHONE) as page:
        wait_cards(page, 1)
        more = page.locator("#filesPageCards .files-page-more")
        assert more.inner_text() == "+3"
        # "+N" ולא "N+": הטקסט נקרא משמאל לימין גם במסמך RTL
        first_char_left = page.evaluate("""() => {
            const b = document.querySelector('#filesPageCards .files-page-more'); const r = document.createRange();
            r.setStart(b.firstChild, 0); r.setEnd(b.firstChild, 1); const plus = r.getBoundingClientRect().left;
            r.setStart(b.firstChild, 1); r.setEnd(b.firstChild, 2); return plus < r.getBoundingClientRect().left;
        }""")
        assert first_char_left is True
        assert page.evaluate("() => { const r = document.getElementById('filesPageCards'); return r.scrollWidth <= r.clientWidth; }")
        more.click()
        listed = page.evaluate("() => [...document.querySelectorAll('.files-page-more-list [data-note-id]')]"
                               ".map(c => c.getAttribute('data-note-id'))")
        assert listed == ids[1:]
        page.locator(f'.files-page-more-list [data-note-id="{ids[2]}"]').click()
        page.locator(f'.sticky-note.is-overlay-open[data-note-id="{ids[2]}"]').wait_for(state="visible", timeout=10000)
        stored = page.evaluate("() => Number(localStorage.getItem('sticky-notes:files-page-row-width'))")
        assert 300 < stored < 390, stored
        assert page.js_errors == []


def test_a_phone_with_no_room_cannot_pin_another_note(db, admin_live_server, chromium_executable):
    """שני כרטיסים נכנסים בשורה בטלפון: אחרי שהעמוד מדד אותה, נעיצה שלישית מהטלפון נחסמת — ומהמחשב לא."""
    board = insert_board(db, USER)
    for i in range(2):
        board_note(db, board, f"נעוץ {i}", pinned_minutes=i, y=40 + i * 340)
    third = board_note(db, board, "שלישי", y=760)

    with opened(admin_live_server, chromium_executable, "/files", PHONE) as page:
        wait_cards(page, 2)
        page.goto(f"{admin_live_server.base_url}/boards/{board}", wait_until="load")
        note = page.locator(f'.sticky-note[data-note-id="{third}"]')
        note.wait_for(state="attached", timeout=10000)
        note.scroll_into_view_if_needed()
        menu_item(page, note, "files-page-pin").click()
        poll(page, "() => !!document.querySelector('.ck-toast')", "הודעה")
        toast = page.evaluate("() => document.querySelector('.ck-toast').textContent")
        assert "במסך הזה" in toast, toast
        assert FIELD not in db.sticky_notes.find_one({"_id": ObjectId(third)})

    with opened(admin_live_server, chromium_executable, f"/boards/{board}") as page:
        note = page.locator(f'.sticky-note[data-note-id="{third}"]')
        note.wait_for(state="visible", timeout=10000)
        menu_item(page, note, "files-page-pin").click()
        poll(page, "() => !!document.querySelector('.ck-toast')", "הודעה")
        assert isinstance(db.sticky_notes.find_one({"_id": ObjectId(third)})[FIELD], datetime)


def test_a_short_window_and_an_announcement_turn_the_cards_into_a_strip(db, admin_live_server, chromium_executable):
    board = insert_board(db, USER)
    for i in range(3):
        board_note(db, board, f"נעוץ {i}", pinned_minutes=i)

    with opened(admin_live_server, chromium_executable, "/files", PHONE_LANDSCAPE) as page:
        wait_cards(page, 3)
        assert page.evaluate("() => document.getElementById('filesPageNotes').dataset.mode") == "strip"
        heights = page.evaluate("() => [...document.querySelectorAll('#filesPageCards > [data-note-id]')]"
                                ".map(c => Math.round(c.getBoundingClientRect().height))")
        assert max(heights) < 40, heights

    db.announcements.insert_one({"text": "הכרזה לבדיקה", "is_active": True, "paths": ["/files"],
                                 "updated_at": datetime.now(timezone.utc)})
    with opened(admin_live_server, chromium_executable, "/files") as page:
        poll(page, "() => document.getElementById('announcementBanner').getAttribute('aria-hidden') === 'false'",
             "ההכרזה מוצגת")
        poll(page, "() => document.getElementById('filesPageNotes').dataset.mode === 'strip'", "פס כותרות")


def test_without_pins_the_page_looks_like_before(db, admin_live_server, chromium_executable):
    """נמדד על הקוד שלפני השינוי באותו מסך (1280×800): הכותרת 103–162, והחיפוש מתחיל ב-194."""
    with opened(admin_live_server, chromium_executable, "/files") as page:
        page.wait_for_timeout(800)
        box = page.evaluate("""() => {
            const t = document.querySelector('h1.page-title').getBoundingClientRect();
            const s = document.querySelector('.search-and-filters').getBoundingClientRect();
            return {hidden: document.getElementById('filesPageNotes').hidden, top: Math.round(t.top),
                    bottom: Math.round(t.bottom), search: Math.round(s.top)};
        }""")
        assert box == {"hidden": True, "top": 103, "bottom": 162, "search": 194}, box
        assert page.evaluate("() => !!document.getElementById('hw-font')") is False, "הגופן לא נטען בלי כרטיסים"


def test_a_failed_load_says_so_and_retry_brings_the_cards(db, admin_live_server, chromium_executable):
    board = insert_board(db, USER)
    note = board_note(db, board, "נעוץ", pinned_minutes=0)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=chromium_executable)
        try:
            context = browser.new_context(viewport=DESKTOP, locale="he-IL")
            context.add_cookies([{"name": "session", "value": admin_live_server.session_cookie,
                                  "domain": "127.0.0.1", "path": "/"}])
            page = context.new_page()
            page.route("**/api/sticky-notes/files-page", lambda route: route.fulfill(status=500, body="{}"))
            page.goto(f"{admin_live_server.base_url}/files", wait_until="load")
            page.locator('[data-testid="files-notes-state-error"]').wait_for(state="visible", timeout=10000)
            # טקסט על רקע העמוד יורש את צבע העמוד — כמו הכותרת שלידו
            same = page.evaluate("() => getComputedStyle(document.getElementById('filesPageNotesError')).color === "
                                 "getComputedStyle(document.querySelector('h1.page-title')).color")
            assert same is True
            page.unroute("**/api/sticky-notes/files-page")
            page.locator("#filesPageNotesRetry").click()
            wait_cards(page, 1)
            assert card_ids(page) == [note]
            assert page.locator('[data-testid="files-notes-state-error"]').is_hidden()
        finally:
            browser.close()


@pytest.mark.parametrize("width", [390, 768, 1024, 1366])
def test_the_row_never_overflows(db, admin_live_server, chromium_executable, width):
    board = insert_board(db, USER)
    for i in range(4):
        board_note(db, board, f"נעוץ עם שם ארוך מאוד שנחתך {i}", pinned_minutes=i)

    with opened(admin_live_server, chromium_executable, "/files", {"width": width, "height": 900}) as page:
        poll(page, "() => document.querySelectorAll('#filesPageCards > *').length > 0", "השורה נבנתה")
        page.wait_for_timeout(300)
        result = page.evaluate("""() => {
            const r = document.getElementById('filesPageCards'); const box = r.getBoundingClientRect();
            const kids = [...r.children].map(c => c.getBoundingClientRect());
            return {overflow: r.scrollWidth - r.clientWidth,
                    inside: kids.every(k => k.left >= box.left - 0.5 && k.right <= box.right + 0.5),
                    font: getComputedStyle(document.querySelector('#filesPageCards .archive-card-title')).fontFamily};
        }""")
        assert result["overflow"] <= 0 and result["inside"], result
        assert "Gveret Levin" in result["font"]
