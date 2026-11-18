"""חלון "הוסף לאוסף" ב-``base.html`` — מה שהוספה מרובה מבקשת להריץ, רץ רק אחרי אישור השרת;
ורשימת אוספים ארוכה נגללת בתוך החלון.

בעמוד הקבצים, הוספה לאוסף של קבצים שנבחרו בבחירה מרובה פותחת את החלון המשותף עם
``onSuccess`` (``openBulkAddToCollectionModal(names, {onSuccess})``), ושם — יציאה ממצב
הבחירה. כאן נבדק החלון עצמו, בעמוד אמיתי: ``onSuccess`` רץ אחרי שהשרת אישר; לא רץ
כשמבטלים, וגם לא כשהשרת דוחה; ולא זולג לפתיחה של קובץ יחיד שבאה אחרי פתיחה מרובה.
שאר השרשרת — מ-``bulk-actions.js`` ועד היציאה מהמצב — ב-``tests/files-bulk-exit-mode.test.js``.

**והגובה של החלון** (``.add-to-collection-dialog``): עם הרבה אוספים הכותרת והכפתורים נשארים
בתוך המסך, הרשימה נגללת בתוכו, והאוסף שנבחר בפעם הקודמת — שמסומן מראש — גלוי בלי שהעמוד
שמתחת זז. עד נובמבר 2026 לחלון לא היה גובה מרבי, והוא גלש מהמסך למעלה ולמטה.

**העמוד אמיתי, המסד לא.** ``/settings`` מרונדר דרך ``test_client``, כמו ב-
``tests/test_search_on_enter_browser.py``. החלון נמצא ב-``base.html``, ולכן הוא שם
בכל עמוד. בקשות ``/api/collections`` נענות כאן.

מדולג כשאין Chromium.
"""

from __future__ import annotations

import itertools
import json
from urllib.parse import urlsplit

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import poll  # noqa: E402
from _fake_mongo import FakeDB  # noqa: E402

HOST = "ck.test"
USER_ID = 7166
FORWARDED_HEADERS = ("content-type", "cache-control", "etag")
_ADDRESSES = itertools.count(1)
COLLECTIONS = {"ok": True, "collections": [{"id": "c1", "name": "אוסף בדיקה"}]}


@pytest.fixture(scope="module")
def browser(chromium_executable):
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
            yield b
        finally:
            b.close()


@pytest.fixture
def page_factory(browser, monkeypatch):
    import webapp.app as wa

    db = FakeDB()
    monkeypatch.setattr(wa, "get_db", lambda: db)
    contexts = []

    def make(*, accept_items: bool, hold: list | None = None, added: int | None = None,
             collections: dict | None = None, viewport: dict | None = None):
        """``hold`` — רשימה: בקשת ההוספה נשמרת בה ולא נענית, עד שהטסט עונה עליה.
        ``collections`` — התשובה של ``/api/collections`` (ברירת מחדל: אוסף אחד); ``viewport`` — גודל החלון."""
        collections_answer = json.dumps(COLLECTIONS if collections is None else collections)
        client = wa.app.test_client()
        client.environ_base["HTTP_X_FORWARDED_FOR"] = f"192.0.2.{next(_ADDRESSES) % 250 + 1}"
        with client.session_transaction() as sess:
            sess["user_id"] = USER_ID
            sess["user_data"] = {"id": USER_ID, "first_name": "בדיקה"}
        posted: list[dict] = []

        def handle(route, request):
            u = urlsplit(request.url)
            if u.hostname != HOST:
                return route.abort()
            if u.path == "/api/collections" and request.method == "GET":
                return route.fulfill(status=200, content_type="application/json", body=collections_answer)
            if u.path == "/api/collections/c1/items" and request.method == "POST":
                posted.append(json.loads(request.post_data or "{}"))
                if hold is not None:
                    hold.append(route)
                    return None
                # כמו ``CollectionsManager.add_items``: ``ok`` עם המונים. ``added`` — כמה נוספו
                # בפועל (ברירת מחדל: כולם).
                n = len(posted[-1].get("items") or []) if added is None else added
                ok_body = {"ok": True, "added": n, "updated": 0}
                status, body = (200, ok_body) if accept_items else (400, {"ok": False, "error": "nope"})
                return route.fulfill(status=status, content_type="application/json", body=json.dumps(body))
            target = u.path + (f"?{u.query}" if u.query else "")
            r = client.open(target, method=request.method, data=request.post_data_buffer,
                            headers={"Content-Type": request.headers.get("content-type", "")})
            headers = {k: v for k, v in r.headers.items() if k.lower() in FORWARDED_HEADERS}
            route.fulfill(status=r.status_code, body=r.data, headers=headers)

        ctx = browser.new_context(viewport=viewport or {"width": 1280, "height": 900})
        contexts.append(ctx)
        ctx.route("**/*", handle)
        page = ctx.new_page()
        alerts: list[str] = []
        page.on("dialog", lambda d: (alerts.append(d.message), d.accept()))
        page.goto(f"http://{HOST}/settings")
        page.evaluate("window.__success = 0")
        return page, posted, alerts

    yield make
    for ctx in contexts:
        ctx.close()


def _open_bulk(page):
    page.evaluate("openBulkAddToCollectionModal(['a.py', 'b.py'], { onSuccess: () => { window.__success += 1; } })")
    poll(page, "() => !!document.querySelector('#addToCollectionBody input[name=collectionId]')", "האוספים נטענו")


def _confirm(page):
    page.click("#addToCollectionModal button.btn-primary")


def test_on_success_runs_once_after_the_server_accepts(page_factory):
    page, posted, alerts = page_factory(accept_items=True)
    _open_bulk(page)
    page.check("#addToCollectionBody input[name=collectionId]")
    _confirm(page)
    poll(page, "() => window.__success === 1", "onSuccess רץ אחרי האישור")
    assert [i["file_name"] for i in posted[0]["items"]] == ["a.py", "b.py"]
    assert page.evaluate("document.getElementById('addToCollectionModal').style.display") == "none"
    assert alerts == ["נוספו 2 קבצים לאוסף"]


def test_on_success_does_not_run_when_the_server_rejects(page_factory):
    page, posted, alerts = page_factory(accept_items=False)
    _open_bulk(page)
    page.check("#addToCollectionBody input[name=collectionId]")
    _confirm(page)
    # ה-alert של השגיאה מגיע אחרי התשובה מהשרת; עד שתי שניות.
    for _ in range(40):
        if alerts:
            break
        page.wait_for_timeout(50)
    assert len(posted) == 1
    assert alerts == ["שגיאה בהוספה לאוסף"]
    assert page.evaluate("window.__success") == 0


def test_cancel_and_a_later_single_file_add_do_not_run_it(page_factory):
    page, posted, alerts = page_factory(accept_items=True)
    _open_bulk(page)
    page.click("#addToCollectionModal button.btn-secondary")
    assert page.evaluate("window.__success") == 0

    # אחרי פתיחה מרובה — פתיחה של קובץ יחיד, ואישור שלה.
    _open_bulk(page)
    page.evaluate("openAddToCollectionModal('c.py')")
    poll(page, "() => !!document.querySelector('#addToCollectionBody input[name=collectionId]')", "האוספים נטענו")
    page.check("#addToCollectionBody input[name=collectionId]")
    _confirm(page)
    poll(page, "() => document.getElementById('addToCollectionModal').style.display === 'none'", "החלון נסגר")
    assert [i["file_name"] for i in posted[-1]["items"]] == ["c.py"]
    assert page.evaluate("window.__success") == 0, "onSuccess של הפתיחה המרובה זלג לקובץ יחיד"


def _wait_for(page, predicate, what: str):
    """המתנה לתנאי בצד של הטסט (בקשה שנעצרה ב-route), עד חמש שניות."""
    for _ in range(100):
        if predicate():
            return
        page.wait_for_timeout(50)
    raise AssertionError(f"לא התקיים: {what}")


def _release(route, added: int = 2):
    body = {"ok": True, "added": added, "updated": 0}
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body))


def test_on_success_runs_when_the_answer_arrives_after_the_window_was_closed(page_factory):
    """הבקשה בדרך, והחלון נסגר. ההוספה שהשרת אישר שייכת לבחירה ששלחה אותה."""
    hold: list = []
    page, posted, alerts = page_factory(accept_items=True, hold=hold)
    _open_bulk(page)
    page.check("#addToCollectionBody input[name=collectionId]")
    _confirm(page)
    _wait_for(page, lambda: hold, "בקשת ההוספה יצאה")
    page.click("#addToCollectionModal button.btn-secondary")  # "בטל" — הסגירה מאפסת את ה-callback
    _release(hold.pop())
    poll(page, "() => window.__success === 1", "onSuccess של הבקשה רץ אחרי התשובה")
    assert alerts == ["נוספו 2 קבצים לאוסף"]


def test_an_answer_for_an_earlier_opening_does_not_close_the_window_that_is_open_now(page_factory):
    """הבקשה בדרך, החלון נסגר ונפתח שוב לקובץ יחיד. התשובה לא סוגרת את הפתיחה החדשה."""
    hold: list = []
    page, posted, alerts = page_factory(accept_items=True, hold=hold)
    _open_bulk(page)
    page.check("#addToCollectionBody input[name=collectionId]")
    _confirm(page)
    _wait_for(page, lambda: hold, "בקשת ההוספה יצאה")
    page.click("#addToCollectionModal button.btn-secondary")
    page.evaluate("openAddToCollectionModal('c.py')")
    poll(page, "() => !!document.querySelector('#addToCollectionBody input[name=collectionId]')", "החלון החדש נטען")

    _release(hold.pop())
    poll(page, "() => window.__success === 1", "onSuccess של הבקשה המרובה רץ")
    state = page.evaluate("""() => {
      const m = document.getElementById('addToCollectionModal');
      return { display: m.style.display, name: m.getAttribute('data-file-name') };
    }""")
    assert state == {"display": "flex", "name": "c.py"}, state


def test_a_partial_add_shows_how_many_and_keeps_everything(page_factory):
    """``ok`` עם פחות פריטים מהמבוקש: מציגים כמה נוספו, והחלון והבחירה נשארים לניסיון נוסף."""
    page, posted, alerts = page_factory(accept_items=True, added=1)
    _open_bulk(page)
    page.check("#addToCollectionBody input[name=collectionId]")
    _confirm(page)
    for _ in range(40):
        if alerts:
            break
        page.wait_for_timeout(50)
    assert alerts == ["נוספו 1 מתוך 2 קבצים לאוסף. אפשר לנסות שוב."]
    assert page.evaluate("document.getElementById('addToCollectionModal').style.display") == "flex"
    assert page.evaluate("window.__success") == 0


# ---------------------------------------------------------------------------
# רשימה ארוכה: הגובה של החלון והגלילה בתוכו
# ---------------------------------------------------------------------------

#: הרבה אוספים, כמו אצל משתמש שהרשימה שלו גדלה: "שולחן עבודה" ואחריו ארבעים.
MANY = {"ok": True, "collections": [{"id": "ws", "name": "שולחן עבודה"}]
        + [{"id": f"c{i}", "name": f"אוסף מספר {i}"} for i in range(1, 41)]}

#: טאבלט לרוחב (בערך המסך שבו התגלה הבאג), טלפון לרוחב — החלון הנמוך ביותר — וטלפון לאורך.
VIEWPORTS = {
    "tablet": {"width": 1360, "height": 690},
    "phone-landscape": {"width": 780, "height": 360},
    "phone-portrait": {"width": 390, "height": 844},
}

#: המדידה של החלון כשהוא פתוח: מקום הכותרת, הכפתורים והרשימה ביחס למסך, ואם הרשימה נגללת.
_MEASURE = """() => {
  const vh = window.innerHeight;
  const dialog = document.querySelector('#addToCollectionModal .add-to-collection-dialog').getBoundingClientRect();
  const title = document.querySelector('#addToCollectionModal h3').getBoundingClientRect();
  const buttons = [...document.querySelectorAll('#addToCollectionModal button')].map(b => b.getBoundingClientRect());
  const body = document.getElementById('addToCollectionBody');
  return {
    vh, dialogTop: dialog.top, dialogBottom: dialog.bottom, dialogHeight: dialog.height,
    titleTop: title.top,
    buttonsTop: Math.min(...buttons.map(r => r.top)), buttonsBottom: Math.max(...buttons.map(r => r.bottom)),
    scrolls: body.scrollHeight > body.clientHeight,
  };
}"""

_LOADED = "() => document.querySelectorAll('#addToCollectionBody input[name=collectionId]').length > 1"


@pytest.mark.parametrize("screen", list(VIEWPORTS))
def test_a_long_list_scrolls_inside_the_window_and_the_title_and_buttons_stay_on_screen(page_factory, screen):
    page, _, _ = page_factory(accept_items=True, collections=MANY, viewport=VIEWPORTS[screen])
    page.evaluate("openAddToCollectionModal('a.py')")
    poll(page, _LOADED, "האוספים נטענו")

    m = page.evaluate(_MEASURE)

    # הכותרת והכפתורים בתוך המסך — עד היום הם גלשו ממנו, למעלה ולמטה
    assert m["titleTop"] >= 0 and m["dialogTop"] >= 0, m
    assert m["buttonsTop"] >= 0 and m["buttonsBottom"] <= m["vh"], m
    # החלון בגובה המרבי שלו (70% מהמסך, ``.add-to-collection-dialog``), והרשימה נגללת בתוכו
    assert m["dialogHeight"] <= m["vh"] * 0.7 + 1, m
    assert m["scrolls"] is True, m

    # האוסף האחרון נגיש: גלילה של הרשימה עד הסוף מביאה אותו לתוכה, והכפתורים לא זזים
    reach = page.evaluate("""() => {
      const body = document.getElementById('addToCollectionBody');
      body.scrollTop = body.scrollHeight;
      const box = body.getBoundingClientRect();
      const inputs = body.querySelectorAll('input[name=collectionId]');
      const last = inputs[inputs.length - 1].closest('label').getBoundingClientRect();
      return { inside: last.top >= box.top - 0.5 && last.bottom <= box.bottom + 0.5,
               buttonsBottom: Math.max(...[...document.querySelectorAll('#addToCollectionModal button')]
                                         .map(b => b.getBoundingClientRect().bottom)) };
    }""")
    assert reach["inside"] is True, reach
    assert reach["buttonsBottom"] == m["buttonsBottom"], (reach, m)


def _choice_state(page):
    return page.evaluate("""() => {
      const body = document.getElementById('addToCollectionBody');
      const box = body.getBoundingClientRect();
      const checked = body.querySelector('input[name=collectionId]:checked');
      const opt = checked.closest('label').getBoundingClientRect();
      return { value: checked.value, scrollTop: body.scrollTop,
               page: [window.scrollY, document.documentElement.scrollTop, document.body.scrollTop],
               visible: opt.top >= box.top - 0.5 && opt.bottom <= box.bottom + 0.5 };
    }""")


def _with_tall_page_scrolled(page, y: int) -> list:
    """עמוד ארוך שגלול למטה — כדי שגלילה של העמוד שמתחת לשכבה, אם הייתה, תימדד.

    **מה שנגלל בעמוד הוא ``body`` ולא החלון:** ``html, body { height: 100%; overflow-x: hidden }``
    ב-``base.html`` הופך את ``body`` לקופסת הגלילה, ו-``window.scrollY`` נשאר 0 (נמדד). לכן נמדדים
    שלושתם, ומוחזר המצב שאחרי הגלילה."""
    page.evaluate("""(y) => {
      const spacer = document.createElement('div'); spacer.style.height = '4000px';
      document.body.appendChild(spacer); document.body.scrollTop = y;
    }""", y)
    before = page.evaluate("[window.scrollY, document.documentElement.scrollTop, document.body.scrollTop]")
    assert before[2] == y, before
    return before


def test_the_previously_chosen_collection_is_scrolled_into_view_and_the_page_does_not_move(page_factory):
    """האוסף מהפעם הקודמת מסומן מראש. ברשימה שנגללת הוא היה יושב מתחת לחלק הנראה."""
    page, _, _ = page_factory(accept_items=True, collections=MANY, viewport=VIEWPORTS["tablet"])
    page.evaluate("localStorage.setItem('last_collection_id', 'c35')")
    before = _with_tall_page_scrolled(page, 600)
    page.evaluate("openAddToCollectionModal('a.py')")
    poll(page, _LOADED, "האוספים נטענו")

    state = _choice_state(page)

    assert state["value"] == "c35", state
    assert state["visible"] is True and state["scrollTop"] > 0, state
    # העמוד שמתחת לשכבה לא זז. אין מוטציה מציאותית שמפילה את זה — נמדד שגם ``block: 'center'`` אינו
    # גולל את ``body`` בשביל אפשרות שבתוך השכבה ה-``fixed`` — ולכן זה תיעוד של מה שנמדד, לא שומר על באג ידוע.
    assert state["page"] == before, (state, before)


def test_a_chosen_collection_that_is_already_visible_does_not_scroll_the_list(page_factory):
    """בקרה: ``block: 'nearest'`` — אוסף שגלוי ממילא אינו מזיז את הרשימה.

    **האוסף הוא האחרון שגלוי במלואו לפני כל גלילה**, ונמדד כאן ולא נבחר מראש: אוסף בראש הרשימה
    לא היה מבדיל בין ``nearest`` ל-``center`` — את ראש הרשימה אי אפשר למרכז, והגלילה נעצרת ב-0
    (נמדד: עם ``center`` ואוסף שלישי מלמעלה, הבדיקה עברה)."""
    page, _, _ = page_factory(accept_items=True, collections=MANY, viewport=VIEWPORTS["tablet"])
    page.evaluate("openAddToCollectionModal('a.py')")
    poll(page, _LOADED, "האוספים נטענו")
    last_visible = page.evaluate("""() => {
      const body = document.getElementById('addToCollectionBody');
      const box = body.getBoundingClientRect();
      const shown = [...body.querySelectorAll('input[name=collectionId]')]
        .filter(i => {
          const r = i.closest('label').getBoundingClientRect();
          return r.top >= box.top && r.bottom <= box.bottom;
        });
      return shown[shown.length - 1].value;
    }""")
    page.click("#addToCollectionModal button.btn-secondary")
    page.evaluate("(id) => localStorage.setItem('last_collection_id', id)", last_visible)
    page.evaluate("openAddToCollectionModal('a.py')")
    poll(page, _LOADED, "האוספים נטענו")

    state = _choice_state(page)

    assert last_visible not in ("ws", "c1", "c2"), last_visible
    assert state["value"] == last_visible and state["visible"] is True, state
    assert state["scrollTop"] == 0, state
