"""אנימציות מעבר המצב — בכרומיום אמיתי, בעמודים האמיתיים, מול השרת האמיתי ומונגו אמיתי.

ארבעה רכיבים, כולם דרך ``AnimUtils`` שב-``webapp/static/js/utils/animations.js``: מיזעור פתק בלוח,
תפריט ⋮ בעמוד הקובץ, קבוצה בפיד האחרון בדשבורד, והחלונית "קבצים אחרונים" מחלונית קיצורי הדרך.
ההסבר המלא — ``docs/webapp/theming_and_css.rst``, העוגן ``anim-utils-state-motion``.

**איך מודדים אמצע של אנימציה.** אחרי הלחיצה, ``getAnimations()`` של האלמנט מחזיר את האנימציות
שהופעלו. כל אחת מוקפאת (``pause``) ומוזזת לזמן נתון (``currentTime``), והמדידה נעשית שם — כך
התוצאה אינה תלויה בכמה מהר הבדיקה הגיעה לשורה הבאה. ``finish`` מקפיץ לסוף, ומשחרר את מי שמחכה
ל-``finished``.

**התזמונים נקראים מ-``AnimUtils.MOTION``**, ולא מוקלדים כאן שוב: הבדיקה בודקת שההשהיות בנויות
מהם, לא את המספרים עצמם.

**ומה כל בדיקה מוכיחה מעבר ל"יש אנימציה":** שהמצב עצמו משתנה מיד (המחלקה, ``hidden``, המסד),
שהאנימציה לא משאירה כלום אחרי הסוף, ושמי שביקש פחות תנועה (``reduced_motion``) לא מקבל אף אחת.
מדולג כשאין Chromium או מונגו — וב-CI אין (``docs/testing.rst``).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import pytest
from bson import ObjectId

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import poll

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

#: ``admin_live_server`` בונה session למשתמש 1.
USER_ID = 1

#: טאבלט 12 אינץ' לרוחב — המכשיר של המשתמש. מעל 900px הקבוצות בפיד נפתחות בטעינה.
TABLET = {"width": 1280, "height": 900}

NOTE_SEL = '.sticky-note[data-note-id="{}"]'

#: האנימציות של אלמנט אחד (לא של צאצאיו): אילו תכונות כל אחת מנפישה, ותזמון. ``null`` כשאין אלמנט.
ANIMS_JS = """(sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  const skip = new Set(['offset', 'easing', 'composite', 'computedOffset']);
  return el.getAnimations().map((a) => {
    const t = a.effect.getTiming();
    const props = Object.keys(a.effect.getKeyframes()[0]).filter((k) => !skip.has(k)).sort();
    return {props, delay: t.delay, duration: t.duration, easing: t.easing, fill: t.fill};
  });
}"""

#: מקפיא את כל האנימציות של האלמנט בשבריר ``frac`` מהמשך שלהן, ומודד אותו שם.
SEEK_JS = """([sel, frac]) => {
  const el = document.querySelector(sel);
  el.getAnimations().forEach((a) => { a.pause(); a.currentTime = frac * a.effect.getTiming().duration; });
  const r = el.getBoundingClientRect();
  const cs = getComputedStyle(el);
  return {top: r.top, left: r.left, width: r.width, height: r.height,
          overflow: cs.overflow, opacity: cs.opacity, transform: cs.transform};
}"""

#: מסיים את כל האנימציות של האלמנט (``finish``) ומודד אותו אחרי הסוף.
FINISH_JS = """(sel) => {
  const el = document.querySelector(sel);
  el.getAnimations().forEach((a) => a.finish());
  const r = el.getBoundingClientRect();
  const cs = getComputedStyle(el);
  return {top: r.top, left: r.left, width: r.width, height: r.height, left_anims: el.getAnimations().length,
          overflow: cs.overflow, transform: cs.transform, scroll: el.scrollHeight, client: el.clientHeight};
}"""

RECT_JS = """(sel) => { const r = document.querySelector(sel).getBoundingClientRect();
  return {top: r.top, left: r.left, width: r.width, height: r.height}; }"""

#: כמה אנימציות של JS (``Element.animate`` — לא ``CSSAnimation`` ולא ``CSSTransition``) רצות על האלמנט ועל
#: צאצאיו. בעמוד יש מעברי CSS שאינם קשורים לכאן — למשל על ``max-width`` של מסגרת התפריט, כש-
#: ``clampDropdownToViewport`` מציב אותו — וגם הם רצים, לרגע, אצל מי שביקש פחות תנועה.
SCRIPT_ANIMS_JS = """(sel) => document.querySelector(sel).getAnimations({subtree: true})
  .filter((a) => !(a instanceof CSSAnimation) && !(a instanceof CSSTransition)).length"""

#: מקפיא מיד אחרי הלחיצה את כל האנימציות של האלמנט ושל צאצאיו, כדי שאף אחת לא תסתיים לפני שנבדקה.
FREEZE_JS = "(sel) => { document.querySelector(sel).getAnimations({subtree: true}).forEach((a) => a.pause()); }"


# --- דפדפן ושרת ------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def browser(chromium_executable):
    with sync_playwright() as pw:
        try:
            b = (pw.chromium.launch(executable_path=chromium_executable) if chromium_executable
                 else pw.chromium.launch())
        except Exception as exc:  # pragma: no cover — אין Chromium בסביבה
            pytest.skip(f"אין Chromium זמין: {exc}")
        with b:
            yield b


class _Page:
    """עמוד אחד של המשתמש, וכל שגיאת JS שהוא דיווח. בקשות לכל מארח אחר נקטעות."""

    def __init__(self, browser, server, *, reduced_motion="no-preference"):
        self.server = server
        self.errors: list[str] = []
        self.context = browser.new_context(viewport=TABLET, locale="he-IL", reduced_motion=reduced_motion)
        self.context.add_cookies([{
            "name": "session", "value": server.session_cookie, "domain": "127.0.0.1", "path": "/",
        }])
        self.page = self.context.new_page()
        self.page.on("pageerror", lambda exc: self.errors.append(f"pageerror: {exc}"))
        self.page.route("**/*", lambda route: route.abort()
                        if urlsplit(route.request.url).hostname != "127.0.0.1" else route.continue_())

    def goto(self, path):
        self.page.goto(self.server.base_url + path, wait_until="load")

    def api(self, method, path, body=None):
        res = self.context.request.fetch(
            self.server.base_url + path, method=method,
            data=None if body is None else json.dumps(body),
            headers={"Content-Type": "application/json"},
        )
        assert res.ok, (method, path, res.status, res.text())
        return res.json()

    def js(self, script, arg=None):
        return self.page.evaluate(script, arg)

    def close(self):
        self.context.close()


@pytest.fixture
def make_page(browser, admin_live_server):
    pages: list[_Page] = []

    def factory(**kwargs):
        p = _Page(browser, admin_live_server, **kwargs)
        pages.append(p)
        return p

    yield factory
    for p in pages:
        assert not p.errors, p.errors
        p.close()


@pytest.fixture(autouse=True)
def _fresh_rate_limits(monkeypatch):
    """מגבלות הקצב של ראוטי הפתקים חיות בזיכרון התהליך, והשרת משותף לכל הקובץ (T3)."""
    import webapp.sticky_notes_api as sticky_notes_api

    monkeypatch.setattr(sticky_notes_api, "_RATE_LOG", {})


@pytest.fixture
def db(wired_mongo):
    database = wired_mongo.get_db()
    for name in ("code_snippets", "large_files", "sticky_notes", "note_boards", "recent_opens"):
        database[name].delete_many({})
    return database


def _seed_files(db, count, *, now=None):
    """``count`` קבצים פעילים של המשתמש, שעודכנו בשעה האחרונה — מה שקבוצת הקבצים בפיד מציגה."""
    now = now or datetime.now(timezone.utc)
    ids = []
    for i in range(count):
        oid = ObjectId()
        stamp = now - timedelta(minutes=i + 1)
        db.code_snippets.insert_one({
            "_id": oid, "user_id": USER_ID, "file_name": f"demo_{i}.py",
            "code": "print('hi')\n", "programming_language": "python",
            "version": 1, "is_active": True, "created_at": stamp, "updated_at": stamp,
        })
        ids.append(str(oid))
    return ids


def poll_db(check, timeout_s=10.0):
    """דוגם תנאי על המסד עד שהוא מתקיים — השמירה יוצאת ברקע אחרי הלחיצה."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.1)
    return False


def _between(value, a, b, margin=1.0):
    lo, hi = min(a, b), max(a, b)
    return lo + margin < value < hi - margin


# --- 1. מיזעור פתק ---------------------------------------------------------------------------


def _board_with_note(p, *, h=220):
    board = p.api("POST", "/api/note-boards", {"name": "אנימציות"})["board"]["id"]
    nid = p.api("POST", f"/api/sticky-notes/board/{board}", {
        "content": "פתק שמתקפל", "position": {"x": 80, "y": 120}, "size": {"width": 260, "height": h},
    })["id"]
    p.goto(f"/boards/{board}")
    p.page.wait_for_selector(NOTE_SEL.format(nid))
    poll(p.page, "() => !document.getAnimations().some(a => a.playState === 'running')", "הלוח נרגע")
    return nid


def _stored_minimized(db, nid):
    doc = db.sticky_notes.find_one({"_id": ObjectId(nid)}, {"is_minimized": 1})
    return bool(doc and doc.get("is_minimized"))


def test_minimizing_a_note_folds_it_to_its_header_and_opens_it_back(make_page, db):
    p = make_page()
    nid = _board_with_note(p, h=220)
    sel = NOTE_SEL.format(nid)
    button = f'{sel} .sticky-note-actions .sticky-note-btn[title="מזער"]'
    full = p.js(RECT_JS, sel)

    # --- קיפול: המחלקה מתחלפת מיד, והקופסה יורדת בהדרגה ב-min-height ---
    p.page.click(button)
    p.js(FREEZE_JS, sel)
    assert p.js("(s) => document.querySelector(s).classList.contains('is-minimized')", sel), \
        "המחלקה צריכה להתחלף באותו רגע, לא בסוף האנימציה"
    anims = p.js(ANIMS_JS, sel)
    assert [a["props"] for a in anims] == [["minHeight"]], anims
    start = p.js(SEEK_JS, [sel, 0])
    early = p.js(SEEK_JS, [sel, 0.1])
    folded = p.js(FINISH_JS, sel)
    # הכותרת ועוד הגבול של הפתק, למעלה ולמטה — זה כל מה שנשאר מפתק ממוזער.
    header = p.js("""(s) => { const el = document.querySelector(s), cs = getComputedStyle(el);
      return el.querySelector(':scope > .sticky-note-header').getBoundingClientRect().height
        + parseFloat(cs.borderTopWidth) + parseFloat(cs.borderBottomWidth); }""", sel)
    assert abs(start["height"] - full["height"]) < 1, (start, full)
    assert _between(early["height"], full["height"], folded["height"]), (early, full, folded)
    assert abs(folded["height"] - header) < 1, (folded, header)
    assert folded["left_anims"] == 0, "אחרי הסוף לא נשארת אנימציה שמחזיקה ערך"
    # רק הגובה זז: המיקום נשמר מהמלבן (``_notePayloadFromEl``), ושמירה באמצע הייתה קוראת אותו.
    assert start["top"] == early["top"] == folded["top"], (start, early, folded)
    assert poll_db(lambda: _stored_minimized(db, nid)), "המיזעור נשמר במסד"

    # --- פתיחה: הגובה גדל בחזרה לגודל שנקבע, והתוכן מופיע בהדרגה ---
    p.page.click(button)
    p.js(FREEZE_JS, sel)
    assert not p.js("(s) => document.querySelector(s).classList.contains('is-minimized')", sel)
    assert [a["props"] for a in p.js(ANIMS_JS, sel)] == [["height"]]
    content_anims = p.js(ANIMS_JS, f"{sel} > .sticky-note-content")
    assert [a["props"] for a in content_anims] == [["opacity"]], content_anims
    start = p.js(SEEK_JS, [sel, 0])
    early = p.js(SEEK_JS, [sel, 0.1])
    opened = p.js(FINISH_JS, sel)
    assert abs(start["height"] - folded["height"]) < 1, (start, folded)
    assert _between(early["height"], folded["height"], full["height"]), (early, folded, full)
    assert abs(opened["height"] - full["height"]) < 1, (opened, full)
    assert opened["left_anims"] == 0
    assert poll_db(lambda: not _stored_minimized(db, nid)), "הפתיחה נשמרה במסד"


def test_a_second_click_mid_fold_continues_from_the_visible_height(make_page, db):
    """לחיצה באמצע הקיפול מבטלת אותו ומתחילה את הפתיחה מהגובה שרואים — לא קופצת לגובה הכותרת."""
    p = make_page()
    nid = _board_with_note(p, h=220)
    sel = NOTE_SEL.format(nid)
    button = f'{sel} .sticky-note-actions .sticky-note-btn[title="מזער"]'

    p.page.click(button)
    p.js(FREEZE_JS, sel)
    mid = p.js(SEEK_JS, [sel, 0.1])
    p.page.click(button)
    p.js(FREEZE_JS, sel)
    anims = p.js(ANIMS_JS, sel)
    assert [a["props"] for a in anims] == [["height"]], "הקיפול בוטל, ורק הפתיחה רצה"
    start = p.js(SEEK_JS, [sel, 0])
    assert abs(start["height"] - mid["height"]) < 1, (start, mid)


# --- 2. תפריט ⋮ בעמוד הקובץ ------------------------------------------------------------------


@pytest.mark.parametrize("theme", [None, "dark"])
def test_the_file_menu_items_cascade_in_and_the_frame_stays_still(make_page, db, theme):
    """גם בערכה כהה: ``dark-mode.css`` דורס כל ``transition`` שנכתב על מחלקה אחת (``[data-theme] *``),
    ולכן הבחירה ב-``Element.animate`` היא מה שמחזיק את האנימציה שם — וזה נבדק, לא מונח."""
    (file_id,) = _seed_files(db, 1)
    p = make_page()
    p.goto(f"/file/{file_id}")
    p.page.wait_for_selector("#fileActionsMenuButton")
    if theme:
        p.js("(t) => document.documentElement.setAttribute('data-theme', t)", theme)
        assert p.js("() => getComputedStyle(document.querySelector('.file-actions__menu-item')).transitionProperty") \
            .startswith("background-color"), "הכלל של dark-mode.css חל על פריטי התפריט"
    p.page.click("#fileActionsMenuButton")
    p.js(FREEZE_JS, "#fileActionsMenu")
    assert p.js("() => !document.getElementById('fileActionsMenu').hidden"), "התפריט נפתח מיד"

    step = p.js("() => window.AnimUtils.MOTION.menuItem.step")
    info = p.js("""() => {
      const items = [...document.querySelectorAll('#fileActionsMenu .file-actions__menu-item')]
        .filter((el) => el.getClientRects().length > 0);
      return {
        frame: document.getElementById('fileActionsMenu').getAnimations().length,
        items: items.map((el) => el.getAnimations().map((a) => ({
          props: Object.keys(a.effect.getKeyframes()[0])
            .filter((k) => !['offset', 'easing', 'composite', 'computedOffset'].includes(k)),
          delay: a.effect.getTiming().delay, fill: a.effect.getTiming().fill,
        }))),
      };
    }""")
    assert info["frame"] == 0, "המסגרת לא זזה — clampDropdownToViewport כותב עליה transform"
    assert len(info["items"]) >= 3, info
    for i, anims in enumerate(info["items"]):
        assert sorted(tuple(a["props"]) for a in anims) == [("opacity",), ("transform",)], (i, anims)
        assert {a["delay"] for a in anims} == {i * step}, (i, anims)
        assert {a["fill"] for a in anims} == {"backwards"}, (i, anims)

    # פריט שעוד מחכה לתורו מוצג במצב ההתחלה (``fill: backwards``), ולא מופיע לרגע.
    waiting = p.js("""() => {
      const items = [...document.querySelectorAll('#fileActionsMenu .file-actions__menu-item')]
        .filter((el) => el.getClientRects().length > 0);
      const last = items[items.length - 1];
      last.getAnimations().forEach((a) => { a.pause(); a.currentTime = 0; });
      return getComputedStyle(last).opacity;
    }""")
    assert waiting == "0", waiting

    # הסגירה מיידית: Escape מוריד את התפריט מהציור באותו רגע.
    p.page.keyboard.press("Escape")
    assert p.js("() => document.getElementById('fileActionsMenu').getClientRects().length") == 0


# --- 3. קבוצה בפיד האחרון --------------------------------------------------------------------

GROUP_SEL = '.timeline-group[data-group="files"]'


def test_a_feed_group_folds_and_opens_in_place_without_cutting_a_long_list(make_page, db):
    # 14 קבצים: הקבוצה מציגה עמוד אחד ו"טען עוד" — גבוהה הרבה יותר מגובה קבוע כמו 260px.
    _seed_files(db, 14)
    p = make_page()
    p.goto("/dashboard")
    p.page.wait_for_selector(f"{GROUP_SEL}.is-open")
    # הפתיחה בטעינה (``syncDesktop``) אינה מונפשת.
    assert p.js(ANIMS_JS, GROUP_SEL) == []
    chevron = f"{GROUP_SEL} .group-toggle > .fa-chevron-down"
    assert p.js("(s) => getComputedStyle(document.querySelector(s)).transform", chevron) != "none", \
        "קבוצה פתוחה — החץ מצביע למעלה"
    full = p.js(RECT_JS, GROUP_SEL)
    assert full["height"] > 400, full

    # --- סגירה ---
    p.page.click(f"{GROUP_SEL} .group-toggle")
    p.js(FREEZE_JS, GROUP_SEL)
    assert not p.js("(s) => document.querySelector(s).classList.contains('is-open')", GROUP_SEL)
    anims = p.js(ANIMS_JS, GROUP_SEL)
    assert [a["props"] for a in anims] == [["minHeight", "overflow"]], anims
    early = p.js(SEEK_JS, [GROUP_SEL, 0.1])
    closed = p.js(FINISH_JS, GROUP_SEL)
    header = p.js(RECT_JS, f"{GROUP_SEL} .group-toggle")
    assert _between(early["height"], full["height"], closed["height"]), (early, full, closed)
    assert abs(closed["height"] - header["height"]) < 1, (closed, header)
    p.js(FINISH_JS, chevron)
    assert p.js("(s) => getComputedStyle(document.querySelector(s)).transform", chevron) == "none"

    # --- פתיחה ---
    p.page.click(f"{GROUP_SEL} .group-toggle")
    p.js(FREEZE_JS, GROUP_SEL)
    anims = p.js(ANIMS_JS, GROUP_SEL)
    assert [a["props"] for a in anims] == [["height", "overflow"]], anims
    early = p.js(SEEK_JS, [GROUP_SEL, 0.1])
    assert early["overflow"] == "hidden", "בזמן הגדילה התוכן נחתך בגבול הקופסה"
    assert _between(early["height"], closed["height"], full["height"]), (early, closed, full)

    motion = p.js("() => window.AnimUtils.MOTION.groupRow")
    rows = p.js(f"""() => [...document.querySelectorAll('{GROUP_SEL} .group-items > [data-timeline-event]')]
      .map((el) => el.getAnimations().map((a) => a.effect.getTiming().delay))""")
    assert len(rows) >= 10, rows
    for i, delays in enumerate(rows):
        assert delays == [min(i, motion["maxIndex"]) * motion["step"]] * 2, (i, delays)

    opened = p.js(FINISH_JS, GROUP_SEL)
    assert abs(opened["height"] - full["height"]) < 1, (opened, full)
    assert opened["overflow"] == "visible", "החיתוך מוחזק רק בזמן האנימציה"
    assert opened["scroll"] <= opened["client"], "שום שורה לא נחתכה"


# --- 4. "קבצים אחרונים" ----------------------------------------------------------------------


@pytest.mark.parametrize("direction", ["rtl", "ltr"])
def test_recent_files_grow_out_of_the_button_that_opened_them(make_page, db, direction):
    """המדידה בשתי הפריסות (H7): הצמיחה מחושבת מהפרש מלבנים, ולא מ-``direction``."""
    p = make_page()
    p.goto("/files")
    p.js("(d) => { document.documentElement.dir = d; }", direction)
    p.page.click(".quick-access-toggle")
    trigger = ".quick-access-item[title='קבצים שנפתחו לאחרונה']"
    poll(p.page, f"""() => {{ const r = document.querySelector("{trigger}").getBoundingClientRect();
      return r.width > 0 && !document.querySelector('#quickAccessDropdown').getAnimations({{subtree: true}})
        .some(a => a.playState === 'running'); }}""", "החלונית נפתחה ונרגעה")
    button = p.js(RECT_JS, trigger)

    content = ".recent-files-modal .modal-content"
    with p.page.expect_response(lambda r: urlsplit(r.url).path == "/api/files/recent"):
        p.page.click(trigger)
        p.js(FREEZE_JS, ".recent-files-modal")
    assert p.js("() => document.querySelector('.recent-files-modal').classList.contains('is-morph')")
    anims = p.js(ANIMS_JS, content)
    assert [a["props"] for a in anims] == [["borderRadius", "transform"]], anims
    start = p.js(SEEK_JS, [content, 0])
    for key in ("left", "top", "width", "height"):
        assert abs(start[key] - button[key]) < 1, (key, start, button)

    # התשובה כבר הגיעה, והרשימה עדיין לא נכנסה: היא מחכה לסוף הצמיחה. ההמתנה הקצרה נותנת
    # ל-JS לקרוא את גוף התשובה — בלי ההמתנה לצמיחה, הרשימה הייתה נכנסת בתוכה.
    p.page.wait_for_timeout(300)
    assert p.js("() => !!document.querySelector('#recentFilesList .loading')"), "הרשימה נכנסה באמצע הצמיחה"
    final = p.js(FINISH_JS, content)
    assert final["left_anims"] == 0
    poll(p.page, "() => !document.querySelector('#recentFilesList .loading')", "הרשימה נכנסה אחרי הצמיחה")


def test_recent_files_without_a_button_keep_the_css_entrance(make_page, db):
    """קריאה מתוך קוד (``showRecentFiles()`` בלי כפתור) — בלי צמיחה, עם ``modalSlideUp`` של ה-CSS."""
    p = make_page()
    p.goto("/files")
    p.js("() => { showRecentFiles(); }")
    p.page.wait_for_selector(".recent-files-modal .modal-content")
    assert not p.js("() => document.querySelector('.recent-files-modal').classList.contains('is-morph')")
    names = p.js("""() => document.querySelector('.recent-files-modal .modal-content').getAnimations()
      .map((a) => a.animationName || null)""")
    assert names == ["modalSlideUp"], names


# --- מי שביקש פחות תנועה ---------------------------------------------------------------------


def test_reduced_motion_gets_the_same_state_changes_without_any_animation(make_page, db):
    (file_id,) = _seed_files(db, 1)
    p = make_page(reduced_motion="reduce")

    nid = _board_with_note(p)
    sel = NOTE_SEL.format(nid)
    p.page.click(f'{sel} .sticky-note-actions .sticky-note-btn[title="מזער"]')
    assert p.js("(s) => document.querySelector(s).classList.contains('is-minimized')", sel)
    assert p.js(SCRIPT_ANIMS_JS, sel) == 0

    p.goto(f"/file/{file_id}")
    p.page.wait_for_selector("#fileActionsMenuButton")
    p.page.click("#fileActionsMenuButton")
    assert p.js(SCRIPT_ANIMS_JS, "#fileActionsMenu") == 0

    p.goto("/dashboard")
    p.page.wait_for_selector(f"{GROUP_SEL}.is-open")
    p.page.click(f"{GROUP_SEL} .group-toggle")
    assert not p.js("(s) => document.querySelector(s).classList.contains('is-open')", GROUP_SEL)
    assert p.js(SCRIPT_ANIMS_JS, GROUP_SEL) == 0

    p.page.click(".quick-access-toggle")
    p.page.click(".quick-access-item[title='קבצים שנפתחו לאחרונה']")
    p.page.wait_for_selector(".recent-files-modal")
    assert not p.js("() => document.querySelector('.recent-files-modal').classList.contains('is-morph')")
    assert p.js(SCRIPT_ANIMS_JS, ".recent-files-modal") == 0
