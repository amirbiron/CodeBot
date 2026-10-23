"""הצ'קליסט "צעדים ראשונים" בדשבורד — בכרומיום אמיתי, מול הוובאפ האמיתי ומונגו אמיתי.

**למה דפדפן.** פתיחה וסגירה של צעד (``<details>``) בלחיצה, במגע ובמקלדת; כפתור שמוביל ליעד שלו,
כולל עוגן שמגיע למסך; הסתרה שנשמרת גם ב"מכשיר אחר" — הקשר דפדפן חדש של אותו משתמש, בלי ה-cookies
וה-localStorage של הראשון; ופריסה בלי גלילה אופקית ברוחב של טלפון. את כל אלה רק דפדפן עושה.
השרת הוא ``admin_live_server`` (session של משתמש 1) מול ``wired_mongo``, עם התבניות, ה-CSS
וה-JS מהדיסק. בקשות לכל מארח אחר נקטעות, ולכן גם Font Awesome אינו נטען.

**"בטעינה הבאה לא רצה אף שאילתה של הצ'קליסט" נמדד כאן מול המסד עצמו:** ה-profiler של mongod
(``tests/_mongo_profiler.py``) רושם כל פקודה, ו-``_checklist_queries`` מזהה את השאילתות של הצ'קליסט לפי הצורה שלהן — ולא לפי
האוסף בלבד, כי גם כרטיס "פתקים אחרונים" קורא מ-``sticky_notes`` באותה טעינה. הצד של CI לאותה
טענה, עם מונה קריאות על דמה, ב-``tests/test_first_steps.py``.

**שגיאות קונסול:** כל ``pageerror`` נכשל, וכל שגיאת קונסול שמקורה ב-``127.0.0.1``. שגיאה על
משאב ממארח אחר היא הבקשה שנקטעה כאן, ולא תקלה בעמוד.

**"הצג שוב"** נשמר כבקשה לראות את הכרטיס (``first_steps_hidden: false``) ומוחק את הנעילה, ולכן
אחריו הבדיקות רצות שוב. ומי שסיים הכל רואה את הכרטיס מלא עד שהוא מסתיר אותו שוב — גם אחרי ריענון
והחלפת ערכה. נבדקים כאן גם משתמש שהסתיר לפני שסיים וגם משתמש שסיים.

מדולג כשאין Chromium (וב-CI אין: ראו ``docs/testing.rst``), וכשאין מונגו (``wired_mongo``).
"""

from __future__ import annotations

import contextlib
from urllib.parse import urlsplit

import pytest

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import Touch, poll, tap_on
from _mongo_profiler import profiled

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

#: ``admin_live_server`` בונה session למשתמש 1.
USER_ID = 1

#: טאבלט 12 אינץ' לרוחב — המכשיר של המשתמש — וטלפונים לאורך.
TABLET = {"width": 1280, "height": 900}
PHONES = ({"width": 320, "height": 700}, {"width": 360, "height": 780}, {"width": 390, "height": 844})

STEP_KEYS = ("theme", "collection", "note", "ai")


class _Pages:
    """הקשרי דפדפן ("מכשירים") של אותו משתמש, והשגיאות שכל העמודים בהם דיווחו."""

    def __init__(self, browser, server):
        self.browser = browser
        self.server = server
        self.errors: list[str] = []
        self._contexts = []

    def device(self, viewport=TABLET):
        """הקשר חדש — "מכשיר" בלי cookies ובלי localStorage — עם ה-session של המשתמש בלבד."""
        context = self.browser.new_context(
            viewport=viewport, has_touch=True, is_mobile=viewport["width"] < 700, locale="he-IL",
        )
        self._contexts.append(context)
        context.add_cookies([{
            "name": "session", "value": self.server.session_cookie, "domain": "127.0.0.1", "path": "/",
        }])
        page = context.new_page()
        page.on("pageerror", lambda exc: self.errors.append(f"pageerror: {exc}"))
        page.on("console", self._on_console)
        page.route("**/*", lambda route: route.abort()
                   if urlsplit(route.request.url).hostname != "127.0.0.1" else route.continue_())
        return page

    def _on_console(self, msg):
        if msg.type != "error":
            return
        source = urlsplit((msg.location or {}).get("url") or "").hostname
        if source in (None, "", "127.0.0.1"):
            self.errors.append(f"console.error: {msg.text} @ {(msg.location or {}).get('url')}")

    def goto(self, page, path):
        """ניווט פנימי: עם ``referer`` מאותו אתר, כמו לחיצה על קישור."""
        response = page.goto(f"{self.server.base_url}{path}", wait_until="load",
                             referer=f"{self.server.base_url}/files")
        assert response is not None and response.status == 200, (path, response and response.status)
        return response

    def close(self):
        for context in self._contexts:
            context.close()


@contextlib.contextmanager
def _browser_pages(server, executable):
    """**המקום היחיד שמרים דפדפן כאן.** בסוף: אף עמוד לא דיווח שגיאה."""
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=executable) if executable else pw.chromium.launch()
        except PlaywrightError as exc:  # pragma: no cover - תלוי בסביבה
            pytest.skip(f"אין Chromium זמין: {exc}")
        pages = _Pages(browser, server)
        try:
            yield pages
            assert pages.errors == [], pages.errors
        finally:
            pages.close()
            browser.close()


def _checklist_queries(entries):
    """השאילתות של ``webapp/first_steps.py``, לפי הצורה שלהן."""
    found = []
    for entry in entries:
        collection = str(entry.get("ns", "")).split(".", 1)[-1]
        command = entry.get("command") or {}
        query = command.get("filter") or {}
        if collection in {"mcp_tokens", "mcp_oauth_tokens"}:
            found.append(entry)
        elif collection == "user_collections" and isinstance(query.get("name"), dict) and "$ne" in query["name"]:
            found.append(entry)
        elif (collection == "sticky_notes" and "find" in command
              and isinstance(query.get("board_id"), dict) and "$nin" in query["board_id"]):
            found.append(entry)
    return found


def _card_state(page):
    """הכרטיס כמו שהוא מוצג: האם הוא קיים, המונה, ולכל צעד — מצב, פתוח, ותוכן גלוי."""
    return page.evaluate("""() => {
      const card = document.getElementById('firstSteps');
      if (!card) return {present: false};
      const steps = Array.from(card.querySelectorAll('.first-steps-item')).map(li => {
        const details = li.querySelector('details');
        const body = li.querySelector('.first-steps-body');
        return {
          id: li.id, state: li.getAttribute('data-testid'), open: details.open,
          // ``checkVisibility`` ולא גובה: ב-<details> סגור ``::details-content`` הוא
          // ``content-visibility: hidden``, והתוכן נשאר ``display: block`` ומחזיר גובה (נמדד
          // ב-Chromium 141.0.7390.37: גובה 18, ``checkVisibility()`` מחזיר false).
          bodyVisible: !!body && body.checkVisibility(),
          struck: getComputedStyle(li.querySelector('.first-steps-title')).textDecorationLine,
        };
      });
      const count = card.querySelector('[data-testid="first-steps-count"]').textContent.trim();
      return {present: true, count, steps};
    }""")


def _steps_by_id(state):
    return {step["id"].removeprefix("first-step-"): step for step in state["steps"]}


def _api(page, method, path, body=None):
    """בקשה מתוך העמוד, עם ה-cookies שלו — אותם נתיבים שהממשק עצמו קורא להם."""
    return page.evaluate(
        """async ([method, path, body]) => {
          const resp = await fetch(path, {method, headers: {'Content-Type': 'application/json'},
                                          body: body === null ? undefined : JSON.stringify(body)});
          let data = null;
          try { data = await resp.json(); } catch (e) {}
          return {status: resp.status, data};
        }""",
        [method, path, body],
    )


def _create_collection_and_board_note(page):
    created = _api(page, "POST", "/api/collections", {"name": "Roadmap"})
    assert created["status"] == 200 and created["data"]["ok"], created
    boards = _api(page, "GET", "/api/note-boards")
    assert boards["status"] == 200 and boards["data"]["ok"], boards
    board_id = next(b["id"] for b in boards["data"]["boards"] if b["is_default"])
    note = _api(page, "POST", f"/api/sticky-notes/board/{board_id}", {"content": "משימה ראשונה"})
    assert note["status"] == 201 and note["data"]["ok"], note
    return created["data"]["collection"]["id"]


def _complete_every_step(page, wired_mongo):
    """ערכה, אוסף, פתק על לוח וטוקן אישי — כל אחד דרך הכותב שלו."""
    from mcp_server.token_store import MCPTokenStore

    saved = _api(page, "POST", "/api/ui_prefs", {"theme": "dark"})
    assert saved["status"] == 200 and saved["data"]["ok"], saved
    collection_id = _create_collection_and_board_note(page)
    # הטוקן האישי מונפק מהבוט (``/connect_claude``), ובאותה פונקציה בדיוק.
    MCPTokenStore(wired_mongo.get_db()).issue(USER_ID)
    return collection_id


def _ui_prefs(wired_mongo):
    doc = wired_mongo.get_db().users.find_one({"user_id": USER_ID}) or {}
    return doc.get("ui_prefs") or {}


# --- משתמש חדש -------------------------------------------------------------------------------------


def test_a_new_user_sees_four_closed_steps_that_open_by_click_touch_and_keyboard(
        wired_mongo, admin_live_server, chromium_executable):
    with _browser_pages(admin_live_server, chromium_executable) as pages:
        page = pages.device()
        pages.goto(page, "/dashboard")
        state = _card_state(page)
        assert state["present"] and state["count"] == "0 מתוך 4", state
        assert [s["id"] for s in state["steps"]] == [f"first-step-{k}" for k in STEP_KEYS]
        assert {(s["state"], s["open"], s["bodyVisible"]) for s in state["steps"]} == {
            ("first-step-todo", False, False)}

        # לחיצה פותחת ומציגה את ההסבר ואת הכפתור, ולחיצה נוספת סוגרת.
        page.click("#first-step-theme summary")
        theme = _steps_by_id(_card_state(page))["theme"]
        assert theme["open"] and theme["bodyVisible"], theme
        assert page.evaluate("() => document.querySelector('#first-step-theme .first-steps-action').checkVisibility()")
        page.click("#first-step-theme summary")
        assert not _steps_by_id(_card_state(page))["theme"]["open"]

        # מגע אמיתי, דרך צינור הקלט של הדפדפן.
        touch = Touch(page.context.new_cdp_session(page))
        tap_on(page, touch, "#first-step-collection summary")
        poll(page, "() => document.querySelector('#first-step-collection details').open", "נגיעה פתחה")
        tap_on(page, touch, "#first-step-collection summary")
        poll(page, "() => !document.querySelector('#first-step-collection details').open", "נגיעה סגרה")

        # מקלדת: Enter פותח, רווח סוגר.
        page.focus("#first-step-note summary")
        page.keyboard.press("Enter")
        assert _steps_by_id(_card_state(page))["note"]["open"]
        page.keyboard.press(" ")
        assert not _steps_by_id(_card_state(page))["note"]["open"]


def test_every_button_leads_to_its_target(wired_mongo, admin_live_server, chromium_executable):
    with _browser_pages(admin_live_server, chromium_executable) as pages:
        page = pages.device()
        expected = {
            "theme": ("/settings", "appearance"),
            "collection": ("/collections", None),
            "note": (None, None),
            "ai": ("/settings", "ai-connect"),
        }
        for key, (path, anchor) in expected.items():
            pages.goto(page, "/dashboard")
            page.click(f"#first-step-{key} summary")
            with page.expect_navigation(wait_until="load"):
                page.click(f"#first-step-{key} .first-steps-action")
            url = urlsplit(page.url)
            if key == "note":
                default = wired_mongo.get_db().note_boards.find_one({"user_id": USER_ID, "is_default": True})
                assert default is not None and default["name"] == "לוח עבודה", default
                assert url.path == f"/boards/{default['_id']}", page.url
                continue
            assert url.path == path, page.url
            if anchor:
                assert url.fragment == anchor, page.url
                poll(page, """(id) => {
                  const el = document.getElementById(id);
                  if (!el) return {ok: false, why: 'אין עוגן'};
                  const r = el.getBoundingClientRect();
                  return {ok: r.top >= -2 && r.top < innerHeight, top: r.top};
                }""", f"העוגן #{anchor} על המסך", anchor)


def test_a_collection_and_a_board_note_check_their_steps_after_a_refresh(
        wired_mongo, admin_live_server, chromium_executable):
    with _browser_pages(admin_live_server, chromium_executable) as pages:
        page = pages.device()
        pages.goto(page, "/dashboard")
        _create_collection_and_board_note(page)
        page.reload(wait_until="load")

        state = _card_state(page)
        steps = _steps_by_id(state)
        assert state["count"] == "2 מתוך 4", state
        assert steps["collection"]["state"] == steps["note"]["state"] == "first-step-done", steps
        assert steps["theme"]["state"] == steps["ai"]["state"] == "first-step-todo", steps
        assert "line-through" in steps["collection"]["struck"], steps


# --- נעילה -------------------------------------------------------------------------------------------


def test_completing_every_step_locks_the_card_and_deleting_a_collection_does_not_bring_it_back(
        wired_mongo, admin_live_server, chromium_executable):
    with _browser_pages(admin_live_server, chromium_executable) as pages:
        page = pages.device()
        pages.goto(page, "/dashboard")
        collection_id = _complete_every_step(page, wired_mongo)

        page.reload(wait_until="load")
        assert _card_state(page) == {"present": False}
        assert _ui_prefs(wired_mongo).get("first_steps_done") is True

        db = wired_mongo.get_db()
        with profiled(db) as entries:
            page.reload(wait_until="load")
            assert _card_state(page) == {"present": False}
        assert entries, "ה-profiler לא רשם כלום — המדידה עצמה לא עבדה"
        assert _checklist_queries(entries) == []

        deleted = _api(page, "DELETE", f"/api/collections/{collection_id}")
        assert deleted["status"] == 200 and deleted["data"]["ok"], deleted
        with profiled(db) as entries:
            page.reload(wait_until="load")
            assert _card_state(page) == {"present": False}
        assert _checklist_queries(entries) == []


# --- הסתרה ו"הצג שוב" ----------------------------------------------------------------------------


def test_hiding_holds_after_refresh_and_on_another_device_and_show_again_returns_it(
        wired_mongo, admin_live_server, chromium_executable):
    db = wired_mongo.get_db()
    with _browser_pages(admin_live_server, chromium_executable) as pages:
        page = pages.device()
        pages.goto(page, "/dashboard")
        with page.expect_response(lambda r: urlsplit(r.url).path == "/api/ui_prefs"
                                  and r.request.method == "POST") as hid:
            page.click("#firstStepsHide")
        assert hid.value.ok
        poll(page, "() => !document.getElementById('firstSteps')", "הכרטיס ירד אחרי שהשרת אישר")
        assert _ui_prefs(wired_mongo).get("first_steps_hidden") is True

        with profiled(db) as entries:
            page.reload(wait_until="load")
            assert _card_state(page) == {"present": False}
        assert entries and _checklist_queries(entries) == []

        other = pages.device()
        pages.goto(other, "/dashboard")
        assert _card_state(other) == {"present": False}, "מוסתר גם במכשיר אחר"

        pages.goto(other, "/settings")
        assert other.is_visible("#firstStepsShowAgain")
        with profiled(db) as entries:
            with other.expect_navigation(url=f"{admin_live_server.base_url}/dashboard", wait_until="load"):
                other.click("#firstStepsShowAgain")
            state = _card_state(other)
        assert state["present"] and state["count"] == "0 מתוך 4", state
        assert _checklist_queries(entries), "אחרי \"הצג שוב\" הבדיקות רצות שוב"
        prefs = _ui_prefs(wired_mongo)
        assert prefs.get("first_steps_hidden") is False and "first_steps_done" not in prefs, prefs


def test_show_again_after_finishing_keeps_the_whole_card_until_it_is_hidden(
        wired_mongo, admin_live_server, chromium_executable):
    from webapp.first_steps import STEPS

    total = len(STEPS)
    with _browser_pages(admin_live_server, chromium_executable) as pages:
        page = pages.device()
        pages.goto(page, "/dashboard")
        _complete_every_step(page, wired_mongo)
        page.reload(wait_until="load")
        assert _card_state(page) == {"present": False}
        assert _ui_prefs(wired_mongo).get("first_steps_done") is True

        # הכפתור בתחתית ההגדרות, כמו שהשורה בכרטיס אומרת: מתחת לכל כרטיס, ומעל קישור העזרה.
        pages.goto(page, "/settings")
        place = page.evaluate("""() => {
          const btn = document.getElementById('firstStepsShowAgain');
          const top = btn.getBoundingClientRect().top + scrollY;
          const cards = Array.from(btn.closest('.first-steps-reset').parentElement.querySelectorAll('.glass-card'))
            .filter(c => c.checkVisibility());
          const help = document.querySelector('.settings-help-link');
          return {cards: cards.length, visible: btn.checkVisibility(),
                  belowEveryCard: cards.every(c => c.getBoundingClientRect().bottom + scrollY <= top),
                  aboveHelp: !!help && help.getBoundingClientRect().top + scrollY > top};
        }""")
        assert place["cards"] > 0 and place["visible"] and place["belowEveryCard"] and place["aboveHelp"], place
        with page.expect_navigation(url=f"{admin_live_server.base_url}/dashboard", wait_until="load"):
            page.click("#firstStepsShowAgain")

        state = _card_state(page)
        assert state["present"] and state["count"] == f"{total} מתוך {total}", state
        assert {(s["state"], s["open"]) for s in state["steps"]} == {("first-step-done", False)}, state
        hrefs = page.evaluate("""() => Object.fromEntries(Array.from(
          document.querySelectorAll('#firstSteps .first-steps-item'),
          li => [li.id, li.querySelector('.first-steps-action').getAttribute('href')]))""")
        assert hrefs == {f"first-step-{step['key']}": step["action_href"] for step in STEPS}, hrefs
        for key in STEP_KEYS:
            page.click(f"#first-step-{key} summary")
            step = _steps_by_id(_card_state(page))[key]
            assert step["open"] and step["bodyVisible"], step

        hint = page.evaluate("""() => {
          const btn = document.getElementById('firstStepsHide');
          const hint = document.getElementById(btn.getAttribute('aria-describedby'));
          const card = document.getElementById('firstSteps').getBoundingClientRect();
          const b = btn.getBoundingClientRect(), h = hint.getBoundingClientRect();
          // "מתחת לכפתור" גם לרוחב: השורה והכפתור חופפים בציר האופקי. בלי זה שורה שזזה הצידה,
          // ועדיין בתוך הכרטיס, עוברת (נמדד: margin שלילי מימין הזיז אותה 270px בטאבלט).
          return {text: hint.textContent.trim(), visible: hint.checkVisibility(), below: h.top >= b.bottom - 1,
                  underButton: h.left < b.right && h.right > b.left,
                  inside: h.left >= card.left && h.right <= card.right && h.bottom <= card.bottom};
        }""")
        assert hint == {"text": "אפשר להחזיר את הכרטיס מתחתית עמוד ההגדרות", "visible": True,
                        "below": True, "underButton": True, "inside": True}, hint

        # נשאר אחרי ריענון ואחרי החלפת ערכה, והנעילה לא נכתבת.
        page.reload(wait_until="load")
        assert _card_state(page)["count"] == f"{total} מתוך {total}"
        changed = _api(page, "POST", "/api/ui_prefs", {"theme": "ocean"})
        assert changed["status"] == 200 and changed["data"]["ok"], changed
        page.reload(wait_until="load")
        assert page.evaluate("() => document.documentElement.getAttribute('data-theme')") == "ocean"
        assert _card_state(page)["count"] == f"{total} מתוך {total}"
        prefs = _ui_prefs(wired_mongo)
        assert prefs.get("first_steps_hidden") is False and "first_steps_done" not in prefs, prefs

        with page.expect_response(lambda r: urlsplit(r.url).path == "/api/ui_prefs"
                                  and r.request.method == "POST") as hid:
            page.click("#firstStepsHide")
        assert hid.value.ok
        poll(page, "() => !document.getElementById('firstSteps')", "הכרטיס ירד אחרי שהשרת אישר")
        assert _ui_prefs(wired_mongo).get("first_steps_hidden") is True
        pages.goto(page, "/settings")
        assert page.is_visible("#firstStepsShowAgain")


# --- ערכה "רק במכשיר הזה" ------------------------------------------------------------------------


def test_a_theme_chosen_for_this_device_only_checks_the_step_on_another_device(
        wired_mongo, admin_live_server, chromium_executable):
    with _browser_pages(admin_live_server, chromium_executable) as pages:
        page = pages.device()
        pages.goto(page, "/settings")
        # הרשימה נבנית מחדש מ-``/api/themes/list`` אחרי הטעינה; בחירה לפני כן הייתה נדרסת.
        # ``nebula`` ולא ``dark``: העמוד מסתיר חלק מהערכות המובנות (``__ckHiddenBuiltinThemes``).
        poll(page, "() => !!document.querySelector('#themeSelect optgroup option[value=\"nebula\"]')",
             "רשימת הערכות נטענה")
        with page.expect_response(lambda r: urlsplit(r.url).path == "/api/ui_prefs"
                                  and r.request.method == "POST") as scoped:
            page.select_option("#themeScopeSelect", "device")
        assert scoped.value.ok
        # לפי גוף הבקשה ולא לפי הנתיב בלבד: שינוי התחולה שולח בקשה משלו ל-/api/ui_prefs, ובעמוד
        # הזה ``extra_js`` מרונדר פעמיים, ולכן היא יכולה להגיע פעמיים ולהקדים את בקשת הערכה.
        with page.expect_response(lambda r: urlsplit(r.url).path == "/api/ui_prefs"
                                  and r.request.method == "POST"
                                  and (r.request.post_data_json or {}).get("theme") == "nebula") as chosen:
            page.select_option("#themeSelect", "nebula")
        assert chosen.value.ok

        prefs = _ui_prefs(wired_mongo)
        assert "theme" not in prefs, prefs
        assert prefs.get("device_theme_chosen") is True, prefs

        other = pages.device()
        pages.goto(other, "/dashboard")
        assert other.evaluate("() => document.documentElement.getAttribute('data-theme')") != "nebula"
        assert _steps_by_id(_card_state(other))["theme"]["state"] == "first-step-done"


# --- רוחב טלפון ----------------------------------------------------------------------------------


@pytest.mark.parametrize("viewport", PHONES, ids=lambda v: f"{v['width']}px")
def test_phone_widths_have_no_horizontal_scroll(viewport, wired_mongo, admin_live_server, chromium_executable):
    with _browser_pages(admin_live_server, chromium_executable) as pages:
        page = pages.device(viewport)
        pages.goto(page, "/dashboard")
        page.click("#first-step-ai summary")
        page.wait_for_timeout(100)
        # גם התוכן עצמו בתוך הכרטיס: אילו עמוד או מיכל חותכים גלישה (``overflow-x: hidden``),
        # תוכן שבורח מהכרטיס לא היה מייצר גלילה — והמשתמש היה רואה טקסט חתוך.
        layout = page.evaluate("""() => {
          const cardEl = document.getElementById('firstSteps');
          const card = cardEl.getBoundingClientRect();
          const escaped = Array.from(cardEl.querySelectorAll('*')).filter(el => el.checkVisibility())
            .map(el => [el, el.getBoundingClientRect()])
            .filter(([, r]) => r.width > 0 && (r.left < card.left - 1 || r.right > card.right + 1))
            .map(([el, r]) => `${el.tagName}.${el.className} ${Math.round(r.left)}..${Math.round(r.right)}`);
          return {overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
                  cardLeft: card.left, cardRight: card.right, width: innerWidth, escaped};
        }""")
        assert layout["overflow"] == 0, layout
        assert layout["cardLeft"] >= 0 and layout["cardRight"] <= layout["width"], layout
        assert layout["escaped"] == [], layout
        assert page.is_visible("#firstStepsHideHint"), "השורה מתחת ל\"הבנתי, להסתיר\" מוצגת גם בטלפון"
