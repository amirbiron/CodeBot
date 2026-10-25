"""ארכיון הפתקים בכרומיום, מול הוובאפ האמיתי **ומונגו אמיתי** — הזרימה כולה, כמו שמשתמש עובר בה.

**למה מסד אמיתי ולא API מזויף** (כמו ב-``tests/test_note_menu_pages_browser.py``): הזרימה כאן
עוברת בין שלושה עמודים — הלוח, הארכיון והקישור הקבוע — וכל אחד מהם קורא את מה שהקודם כתב.
API מזויף היה בודק שהלקוח שולח את מה שהטסט ציפה לו; כאן נבדק שמה שנכתב בלוח הוא מה שעמוד
הארכיון מציג, ושמה שנערך בארכיון נשמר. כל המודולים של הוובאפ מגיעים למסד דרך
``webapp.app.get_db`` (ייבוא מקומי בכל קריאה), ולכן הוא היחיד שמוחלף — במסד זמני.

**מה נמדד:** מרכוז הפתק הפתוח במסך, שהמיקום אינו נשמר והגודל כן, ``inert`` על הרשת, שהמיקוד
חוזר לכרטיס, חיתוך השם לארבע שורות, הכיוון של רצף לטיני בשם עברי (מול בקרה בלי הבידוד), מצב
השגיאה, הקישור העמוק, מסך של טלפון, ערכות כהה וניגודיות גבוהה (יחס ניגודיות מחושב), כתב היד בשם
הכרטיס מול הפתק הפתוח, בהגדרה כבויה ודלוקה, ו"כלול ארכיון" בעמוד החיפוש — במחשב ובטלפון.

**מה לא נבדק כאן:** מכשיר אמיתי — זו אמולציה בכרומיום. האנימציה של החזרה לכרטיס נבדקת רק בכך
שהפתק יורד והמיקוד חוזר, לא במסלול שלה.

מדולג כשאין Chromium, או כשאין שרת מונגו (``mongo_reachable`` מדלג רק על "אין שרת").
"""

from __future__ import annotations

import contextlib
import os
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")
pytest.importorskip("pymongo")

from bson import ObjectId  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _note_threads_harness import insert_board, insert_note, mongo_reachable, temp_database  # noqa: E402

import note_threads as nt  # noqa: E402

pytestmark = pytest.mark.skipif(not mongo_reachable(), reason="דורש MONGODB_URL עם שרת מונגו נגיש")

#: המשתמש של ``admin_live_server`` (``ADMIN_USER_IDS=1``).
USER = 1
DESKTOP = {"width": 1280, "height": 800}
PHONE = {"width": 390, "height": 844}
#: לשם צילומי המסך שמצורפים ל-PR — תיקייה זמנית בלבד, ולעולם לא בעץ הקוד.
SHOTS = os.environ.get("ARCHIVE_SHOTS_DIR", "").strip()


@pytest.fixture
def db(monkeypatch):
    import webapp.app as app_mod

    with temp_database("codebot_archive_browser_") as database:
        monkeypatch.setattr(app_mod, "get_db", lambda: database)
        yield database


@contextlib.contextmanager
def opened(server, executable, path, viewport=DESKTOP, *, mobile=False):
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=executable)
        except Exception as exc:  # pragma: no cover - תלוי בסביבה
            pytest.skip(f"אין Chromium זמין: {exc}")
        try:
            context = browser.new_context(viewport=viewport, device_scale_factor=2 if mobile else 1,
                                          is_mobile=mobile, has_touch=mobile, locale="he-IL")
            context.add_cookies([{"name": "session", "value": server.session_cookie,
                                  "domain": "127.0.0.1", "path": "/"}])
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.on("dialog", lambda dialog: dialog.accept())
            page.goto(f"{server.base_url}{path}", wait_until="load")
            page.js_errors = errors
            yield page
        finally:
            browser.close()


def shot(page, name: str) -> None:
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, f"{name}.png"))


def archived(db, title: str, *, minutes: int = 0, color: str = "yellow", **extra) -> str:
    """פתק שכבר בארכיון — בצורה שההעברה כותבת (``archived_at`` תאריך, בלי שדות יעד)."""
    oid = ObjectId()
    # **יחסית לעכשיו**, לא תאריך קבוע: פתק שמועבר בטסט נחתם בזמן ההעברה, ותאריך קבוע שבמקרה
    # מאוחר משעת הריצה היה "חדש" ממנו — והסדר ברשת היה נבדק הפוך.
    when = datetime.now(timezone.utc) - timedelta(hours=1) + timedelta(minutes=minutes)
    doc = {"_id": oid, "user_id": USER, "content": f"# {title}\nגוף", "title": title, "color": color,
           "width": 320, "height": 240, "archived_at": when, "created_at": when, "updated_at": when}
    doc.update(extra)
    db.sticky_notes.insert_one(doc)
    return str(oid)


def card(page, note_id: str):
    return page.locator(f'.archive-card[data-note-id="{note_id}"]')


def open_note(page, note_id: str):
    card(page, note_id).click()
    note = page.locator(f'.sticky-note.is-archive-open[data-note-id="{note_id}"]')
    note.wait_for(state="visible", timeout=10000)
    settled(note)
    return note


def settled(locator) -> None:
    """מחכה לסוף האנימציות של האלמנט. ``noteAppear`` (``sticky-notes.css``) מגדיל כל פתק חדש
    מ-90% במשך 0.2 שניות, ומלבן שנמדד באמצע הוא המלבן המוקטן — לא הגודל של הפתק."""
    locator.evaluate("e => Promise.all(e.getAnimations().map(a => a.finished))")


def action(note, text: str):
    return note.locator(".sticky-note-actions > button", has_text=text)


def _luminance(rgb) -> float:
    def channel(v: float) -> float:
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(float(c)) for c in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(page, selector: str) -> float:
    """יחס הניגודיות (WCAG 2.x) בין צבע הטקסט של האלמנט **לרקע כפי שצויר**.

    הרקע נדגם מפיקסלים — הצבע השכיח בצילום של האלמנט — ולא מ-``background-color``: רקע העמוד
    בכמה ערכות הוא גרדיאנט, שנוחת ב-``background-image`` ומשאיר את ``background-color`` שקוף
    (``docs/webapp/theming_and_css.rst``: "צבע על משטח כזה נמדד בדגימת פיקסל"). הטקסט — מה-
    ``color`` המחושב, שהוא הצבע שהגליפים נצבעים בו.
    """
    import io

    from PIL import Image

    target = page.locator(selector).first
    image = Image.open(io.BytesIO(target.screenshot())).convert("RGB")
    background = max(image.getcolors(image.width * image.height), key=lambda hit: hit[0])[1]
    channels = [float(v) for v in target.evaluate("e => getComputedStyle(e).color.match(/[\\d.]+/g)")]
    # צבע עם שקיפות (``rgba(255, 255, 255, .65)`` בכמה ערכות) מצויר מעורבב ברקע — וכך נמדד.
    alpha = channels[3] if len(channels) > 3 else 1.0
    text = [alpha * c + (1 - alpha) * b for c, b in zip(channels[:3], background)]
    lighter, darker = sorted((_luminance(text), _luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


# == הזרימה — מהלוח לארכיון, ובחזרה לכרטיס ===================================================


def test_from_the_board_to_the_archive_and_back(admin_live_server, chromium_executable, db):
    """⋮ ← 🗃️ ← חלון שם עם הצעה ← הודעה עם קישור ← הכרטיס בראש הרשת ← פתיחה במרכז ← עריכת
    שם ← "—" מעדכן את הכרטיס. כל שלב נקרא גם מהמסד."""
    board = insert_board(db, USER, "לוח")
    older = archived(db, "פתק ישן", minutes=-60)
    note = insert_note(db, USER, board_id=board, content="# רעיון לפיצ'ר\nפרטים", width=300, height=220,
                       position_x=200, position_y=150)

    with opened(admin_live_server, chromium_executable, f"/boards/{board}") as page:
        el = page.locator(f'#boardSurface .sticky-note[data-note-id="{note}"]')
        el.wait_for(state="visible", timeout=20000)
        el.locator(".sticky-note-more").click()
        page.locator('.sticky-note-menu-item[aria-label="העבר לארכיון"]').click()

        dialog = page.locator(".sticky-archive-modal")
        dialog.wait_for(state="visible")
        assert dialog.locator(".sticky-archive-input").input_value() == "רעיון לפיצ'ר"
        shot(page, "1-name-dialog")
        dialog.locator(".sticky-archive-submit").click()

        el.wait_for(state="detached", timeout=10000)
        link = page.locator(".ck-toast .ck-toast__link")
        link.wait_for(state="visible")
        assert link.get_attribute("href") == "/boards/archive"
        stored = db.sticky_notes.find_one({"_id": ObjectId(note)})
        assert isinstance(stored["archived_at"], datetime) and stored["title"] == "רעיון לפיצ'ר"
        assert "board_id" not in stored

        link.click()
        page.wait_for_url("**/boards/archive")
        card(page, note).wait_for(state="visible", timeout=10000)
        order = page.locator(".archive-card:not(.is-skeleton)").evaluate_all(
            "cards => cards.map(c => c.dataset.noteId)")
        assert order == [note, older], "החדש בראש הרשת"
        assert page.locator("#archiveCount").inner_text() == "2"  # אדמין — בלי תקרה
        shot(page, "2-archive-grid")

        opened_note = open_note(page, note)
        box = opened_note.bounding_box()
        assert abs(box["x"] + box["width"] / 2 - DESKTOP["width"] / 2) <= 2, box
        assert abs(box["y"] + box["height"] / 2 - DESKTOP["height"] / 2) <= 2, box
        assert page.evaluate("document.getElementById('archiveMain').inert") is True
        assert opened_note.get_attribute("role") == "dialog"
        assert opened_note.locator(".sticky-note-pin").count() == 0
        shot(page, "3-open-note")

        opened_note.locator(".sticky-note-edit-title").click()
        title = opened_note.locator(".sticky-note-title")
        title.fill("שם חדש")
        title.press("Enter")
        action(opened_note, "—").click()
        opened_note.wait_for(state="detached", timeout=10000)

        assert card(page, note).locator(".archive-card-title").inner_text() == "שם חדש"
        assert page.evaluate("document.activeElement.dataset.noteId") == note, "המיקוד חזר לכרטיס"
        assert page.evaluate("document.getElementById('archiveMain').inert") is False
        assert db.sticky_notes.find_one({"_id": ObjectId(note)})["title"] == "שם חדש"
        assert page.js_errors == []


def test_the_open_note_keeps_its_size_but_not_its_place(admin_live_server, chromium_executable, db):
    """גרירה היא לרגע הזה בלבד — בפתיחה הבאה הפתק שוב במרכז. שינוי גודל נשמר ומכובד."""
    note = archived(db, "גודל")

    with opened(admin_live_server, chromium_executable, "/boards/archive") as page:
        card(page, note).wait_for(state="visible", timeout=20000)
        el = open_note(page, note)
        handle = el.locator(".sticky-note-drag").bounding_box()
        page.mouse.move(handle["x"] + 20, handle["y"] + handle["height"] / 2)
        page.mouse.down()
        page.mouse.move(handle["x"] + 140, handle["y"] + 100, steps=8)
        page.mouse.up()
        assert abs(el.bounding_box()["x"] - (DESKTOP["width"] - 320) / 2) > 50, "בקרה: הגרירה הזיזה"

        grip = el.locator(".sticky-note-resize").bounding_box()
        page.mouse.move(grip["x"] + grip["width"] / 2, grip["y"] + grip["height"] / 2)
        page.mouse.down()
        page.mouse.move(grip["x"] + 80, grip["y"] + 60, steps=8)
        page.mouse.up()
        resized = el.bounding_box()
        action(el, "—").click()
        el.wait_for(state="detached", timeout=10000)

        stored = db.sticky_notes.find_one({"_id": ObjectId(note)})
        assert abs(stored["width"] - resized["width"]) <= 2, (stored["width"], resized)
        assert "position_x" not in stored and "position_y" not in stored, "המיקום לא נכתב"

        again = open_note(page, note).bounding_box()
        assert abs(again["width"] - resized["width"]) <= 2, "הגודל השמור"
        assert abs(again["x"] + again["width"] / 2 - DESKTOP["width"] / 2) <= 2, "ושוב במרכז"


def test_escape_and_the_backdrop_close_and_x_deletes(admin_live_server, chromium_executable, db):
    first = archived(db, "ראשון", minutes=1)
    second = archived(db, "שני")

    with opened(admin_live_server, chromium_executable, "/boards/archive") as page:
        card(page, first).wait_for(state="visible", timeout=20000)
        el = open_note(page, first)
        page.keyboard.press("Escape")
        el.wait_for(state="detached")

        el = open_note(page, first)
        page.mouse.click(10, DESKTOP["height"] - 10)
        el.wait_for(state="detached")

        el = open_note(page, first)
        action(el, "×").click()
        card(page, first).wait_for(state="detached", timeout=10000)
        assert db.sticky_notes.find_one({"_id": ObjectId(first)}) is None
        assert page.locator("#archiveCount").inner_text() == "1"
        assert page.evaluate("document.activeElement.dataset.noteId") == second, "המיקוד עבר לשכן"


# == קישור עמוק, ומצב שגיאה =================================================================


def test_the_note_link_opens_an_archived_note_on_the_archive_page(admin_live_server, chromium_executable, db):
    """התראת תזכורת, תוצאת חיפוש והתראת תגובה פותחות את ``/note/<id>`` — והפתק נפתח בארכיון,
    עם השרשור. הפרמטרים יורדים מהכתובת, כדי שרענון לא יפתח שוב פתק שנסגר."""
    note = archived(db, "מהתראה")
    thread = nt.create_thread(db[nt.NOTE_THREADS_COLLECTION], user_id=USER, note_id=note,
                              author=nt.user_author(), body="שאלה")["thread_id"]

    with opened(admin_live_server, chromium_executable, f"/note/{note}?thread={thread}") as page:
        el = page.locator(f'.sticky-note.is-archive-open[data-note-id="{note}"]')
        el.wait_for(state="visible", timeout=20000)
        page.wait_for_function("location.search === ''")
        assert page.url.endswith("/boards/archive")
        panel = el.locator(':scope > [data-testid="thread-panel"]')
        panel.wait_for(state="visible", timeout=10000)
        page.wait_for_function("p => p.textContent.includes('שאלה')", arg=panel.element_handle(), timeout=10000)
        assert page.js_errors == []


def test_a_failed_load_says_so_and_try_again_recovers(admin_live_server, chromium_executable, db):
    note = archived(db, "אחרי תקלה")
    failures = {"left": 1}

    def flaky(route):
        if failures["left"]:
            failures["left"] -= 1
            route.fulfill(status=500, content_type="application/json",
                          body='{"ok": false, "error": "Failed to list archived notes"}')
        else:
            route.continue_()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=chromium_executable)
        try:
            context = browser.new_context(viewport=DESKTOP, locale="he-IL")
            context.add_cookies([{"name": "session", "value": admin_live_server.session_cookie,
                                  "domain": "127.0.0.1", "path": "/"}])
            page = context.new_page()
            page.route("**/api/sticky-notes/archive", flaky)
            page.goto(f"{admin_live_server.base_url}/boards/archive", wait_until="load")
            page.get_by_test_id("archive-state-error").wait_for(state="visible", timeout=20000)
            assert page.get_by_test_id("archive-state-empty").is_hidden(), "שגיאה אינה \"ריק\""
            shot(page, "4-error-state")
            page.locator("#archiveRetry").click()
            card(page, note).wait_for(state="visible", timeout=10000)
            assert page.get_by_test_id("archive-state-error").is_hidden()
        finally:
            browser.close()


# == שם, כיוון ומסך ========================================================================


def test_a_long_name_is_cut_after_four_lines_and_a_path_keeps_its_slash(admin_live_server, chromium_executable, db):
    """הכרטיס חותך את השם אחרי ארבע שורות. ``/admin/mcp`` בשם עברי — הלוכסן משמאל ל-``admin``,
    כמו בכתיבה שלו. **הבקרה**: אותו שם בלי בידוד הרצף, באותו עמוד — שם הלוכסן נודד ימינה."""
    long_one = archived(db, "מילה " * 30, minutes=1)
    mixed = archived(db, "תיקון /admin/mcp בדף")

    with opened(admin_live_server, chromium_executable, "/boards/archive") as page:
        card(page, mixed).wait_for(state="visible", timeout=20000)
        title = card(page, long_one).locator(".archive-card-title")
        metrics = title.evaluate("""t => ({clamp: getComputedStyle(t).webkitLineClamp,
                                           line: parseFloat(getComputedStyle(t).lineHeight),
                                           client: t.clientHeight, scroll: t.scrollHeight})""")
        assert metrics["clamp"] == "4"
        assert metrics["scroll"] > metrics["client"], "השם הארוך נחתך"
        assert abs(metrics["client"] - 4 * metrics["line"]) <= 2, metrics

        order = card(page, mixed).locator('.archive-card-run[dir="ltr"]').evaluate("""run => {
            const at = (node, i) => { const r = document.createRange(); r.setStart(node, i); r.setEnd(node, i + 1);
                                      return r.getBoundingClientRect().left; };
            const isolated = run.firstChild;
            const control = document.createElement('div');
            control.dir = 'rtl';
            control.style.cssText = 'position:absolute;top:0;inline-size:600px;font:inherit';
            control.textContent = 'תיקון /admin/mcp בדף';
            document.body.appendChild(control);
            const raw = control.firstChild, slash = raw.data.indexOf('/');
            const out = {isolated: at(isolated, 0) < at(isolated, 1), control: at(raw, slash) < at(raw, slash + 1)};
            control.remove();
            return out;
        }""")
        assert order["isolated"] is True, "בכרטיס: הלוכסן משמאל ל-a"
        assert order["control"] is False, "בקרה: בלי בידוד הלוכסן נודד — אחרת הבדיקה אינה מוכיחה דבר"


@pytest.mark.parametrize("setting", [False, True], ids=["setting-off", "setting-on"])
def test_card_names_are_handwritten_and_the_open_note_follows_the_setting(
    setting, admin_live_server, chromium_executable, db,
):
    """שם הכרטיס בכתב יד **תמיד**; הפתק שנפתח מעליו — לפי ההגדרה של הלוחות
    (``ui_prefs.note_fonts.board``, שעמוד הארכיון קורא דרך ``_note_fonts_head.html``).

    **מה נבדק ומה לא:** הגופן נטען מ-Google Fonts, ובסביבה בלי רשת הוא לא יגיע. לכן נבדקים
    ה-``font-family`` המחושב ושה-``<link>`` של הגופן קיים בעמוד, ולא שהגליפים צוירו בגופן."""
    if setting:
        db.users.insert_one({"user_id": USER, "ui_prefs": {"note_fonts": {"board": True}}})
    note = archived(db, "רשימה ביד")

    with opened(admin_live_server, chromium_executable, "/boards/archive") as page:
        card(page, note).wait_for(state="visible", timeout=20000)
        family = card(page, note).locator(".archive-card-title").evaluate("t => getComputedStyle(t).fontFamily")
        assert family.startswith('"Gveret Levin"'), family
        assert page.locator("link#hw-font").count() == 1, "הגופן נטען גם בהגדרה כבויה"
        shot(page, f"8-handwriting-{'on' if setting else 'off'}")

        content = open_note(page, note).locator(".sticky-note-content")
        body = content.evaluate("e => getComputedStyle(e).fontFamily")
        assert body.startswith('"Gveret Levin"') is setting, body
        assert page.js_errors == []


def test_on_a_phone_the_grid_has_two_columns_and_the_note_fits(admin_live_server, chromium_executable, db):
    notes = [archived(db, f"פתק {i}", minutes=i) for i in range(4)]

    with opened(admin_live_server, chromium_executable, "/boards/archive", PHONE, mobile=True) as page:
        card(page, notes[0]).wait_for(state="visible", timeout=20000)
        lefts = {round(b["x"]) for b in (card(page, n).bounding_box() for n in notes)}
        assert len(lefts) >= 2, f"לפחות שתי עמודות — {lefts}"
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "בלי גלילה לרוחב"
        shot(page, "5-phone-grid")

        card(page, notes[0]).tap()
        el = page.locator(f'.sticky-note.is-archive-open[data-note-id="{notes[0]}"]')
        el.wait_for(state="visible", timeout=10000)
        settled(el)
        box = el.bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= PHONE["width"], box
        shot(page, "6-phone-open")
        action(el, "—").tap()
        el.wait_for(state="detached", timeout=10000)


# == החיפוש בפתקים ו"כלול ארכיון" ==========================================================


def search_hits(page) -> dict[str, str]:
    """מזהה הפתק ← התווית של המקום שלו, לכל תוצאה שמוצגת (``TARGET_LABELS`` ב-``notes_search.js``)."""
    return page.locator(".notes-search-link").evaluate_all(
        """links => Object.fromEntries(links.map(a => [a.getAttribute('href').split('/').pop(),
                                                      a.querySelector('.notes-search-meta').textContent]))""")


def wait_for_hits(page, count: int) -> None:
    # ``expect`` ולא ``wait_for_function`` עם מחרוזת: ה-CSP של האתר אוסר ``unsafe-eval``.
    from playwright.sync_api import expect

    expect(page.locator(".notes-search-link")).to_have_count(count, timeout=10000)


def test_the_notes_search_shows_the_archive_only_with_the_box_ticked(admin_live_server, chromium_executable, db):
    """בלי התיבה — רק הפתק הפעיל. מסמנים — גם פתק הארכיון, עם התווית "ארכיון", והבחירה נכנסת
    לכתובת: רענון שומר אותה, והסרת הסימון מוציאה אותה. הכול מול השרת והמסד האמיתיים."""
    board = insert_board(db, USER)
    live = insert_note(db, USER, board_id=board, title="רעיון פעיל")
    gone = archived(db, "רעיון ישן")

    with opened(admin_live_server, chromium_executable, "/notes/search?q=רעיון") as page:
        wait_for_hits(page, 1)
        box = page.locator("#noteSearchArchive")
        assert box.is_checked() is False
        assert search_hits(page) == {live: "לוח"}

        box.check()
        wait_for_hits(page, 2)
        assert search_hits(page) == {live: "לוח", gone: "ארכיון"}
        assert "include_archived=1" in page.url
        shot(page, "9-search-with-archive")

        page.reload(wait_until="load")
        wait_for_hits(page, 2)
        assert page.locator("#noteSearchArchive").is_checked() is True, "רענון שומר את הבחירה"

        page.locator("#noteSearchArchive").uncheck()
        wait_for_hits(page, 1)
        assert "include_archived" not in page.url
        assert page.js_errors == []


def test_on_a_phone_the_archive_box_fits_and_its_label_is_tappable(admin_live_server, chromium_executable, db):
    """בטלפון: בלי גלילה לרוחב, והתווית כולה לחיצה — נגיעה במילים מסמנת את התיבה."""
    archived(db, "רעיון ישן")

    with opened(admin_live_server, chromium_executable, "/notes/search?q=רעיון", PHONE, mobile=True) as page:
        page.locator("#noteSearchMsg").wait_for(state="visible", timeout=10000)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "בלי גלילה לרוחב"
        label = page.locator(".notes-search-archive")
        box = label.bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= PHONE["width"], box
        page.get_by_text("כלול ארכיון").tap()
        wait_for_hits(page, 1)
        assert page.locator("#noteSearchArchive").is_checked() is True
        shot(page, "10-phone-search-with-archive")


#: הערכות המובנות — הרשימה ``allowed`` ב-``base.html``, בלי ``custom`` (תלוי במשתמש).
THEMES = ("classic", "ocean", "rose-pine-dawn", "dark", "dim", "nebula", "high-contrast")


@pytest.mark.parametrize("theme", THEMES)
def test_the_page_stays_readable_in_every_theme(theme, admin_live_server, chromium_executable, db):
    """הכרטיס הוא נייר של פתק — צבע הפתק והדיו שלו בכל ערכה; הטקסט שיושב על רקע העמוד (הספירה,
    "אין פתקים") יורש את צבע הטקסט של העמוד. נמדד בפיקסלים, ב-4.5:1 של טקסט רגיל.

    **שני דברים שנפלו כאן לפני התיקון:** ``[data-theme="high-contrast"] button`` צבע את הכרטיס
    שחור (``!important``) והדיו נשארה עליו; ו-``--text-muted`` על רקע העמוד ירד ל-2.7:1 ב-dim
    (וגם ``--text-secondary`` נשאר מתחת ל-4.5 ב-classic וב-rose-pine-dawn)."""
    from sticky_notes_target import note_color_hex

    note = archived(db, "ניגודיות")
    hexed = note_color_hex("yellow").lstrip("#")
    expected = "rgb({}, {}, {})".format(*(int(hexed[i:i + 2], 16) for i in (0, 2, 4)))

    with opened(admin_live_server, chromium_executable, "/boards/archive") as page:
        card(page, note).wait_for(state="visible", timeout=20000)
        page.evaluate(f"document.documentElement.setAttribute('data-theme', '{theme}')")
        page.wait_for_timeout(100)
        assert card(page, note).evaluate("c => getComputedStyle(c).backgroundColor") == expected
        assert contrast(page, f'.archive-card[data-note-id="{note}"] .archive-card-title') >= 4.5
        assert contrast(page, "#archiveCount") >= 4.5
        # מצב "ריק" באותו עמוד: ה-CSS והרקע אמיתיים, ורק ההסתרה מוסרת.
        page.evaluate("document.getElementById('archiveEmpty').hidden = false")
        for line in ("#archiveEmpty > div:first-child", "#archiveEmpty .archive-empty-hint"):
            assert contrast(page, line) >= 4.5, line
        shot(page, f"7-theme-{theme}")
