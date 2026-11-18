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

    def __init__(self, browser, server, *, reduced_motion="no-preference", viewport=TABLET):
        self.server = server
        self.errors: list[str] = []
        self.context = browser.new_context(viewport=viewport, locale="he-IL", reduced_motion=reduced_motion)
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


def _seed_files(db, count, *, now=None, languages=None):
    """``count`` קבצים פעילים של המשתמש, שעודכנו בשעה האחרונה — מה שקבוצת הקבצים בפיד מציגה.
    ``languages`` — שפה לכל קובץ, לפי הסדר; רשימת "שפות" בעמוד הקבצים נבנית מהשפות של הקבצים."""
    assert languages is None or len(languages) >= count, f"צריך שפה לכל אחד מ-{count} הקבצים, התקבלו {len(languages)}"
    now = now or datetime.now(timezone.utc)
    ids = []
    for i in range(count):
        oid = ObjectId()
        stamp = now - timedelta(minutes=i + 1)
        db.code_snippets.insert_one({
            "_id": oid, "user_id": USER_ID, "file_name": f"demo_{i}.py",
            "code": "print('hi')\n", "programming_language": languages[i] if languages is not None else "python",
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

    step = p.js("() => window.AnimUtils.menuMotion().step")
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


#: הזווית שבה האלמנט מצויר עכשיו, במעלות — האורקל של הבדיקה, כתוב כאן בנפרד מ-``AnimUtils.rotationOf``
#: כדי שבאג שם לא יעבור גם כאן. הטווח (-90, 270], כמו שם.
ANGLE_JS = """(sel) => {
  const t = getComputedStyle(document.querySelector(sel)).transform;
  if (t === 'none') return 0;
  const m = new DOMMatrixReadOnly(t);
  const d = Math.atan2(m.b, m.a) * 180 / Math.PI;
  return d <= -90 ? d + 360 : d;
}"""

#: הזוויות שבמסגרות של אנימציית הסיבוב היחידה שעל האלמנט, או מילון שאומר כמה אנימציות יש עליו.
KEYFRAME_ANGLES_JS = r"""(sel) => {
  const anims = document.querySelector(sel).getAnimations();
  if (anims.length !== 1) return {count: anims.length};
  return anims[0].effect.getKeyframes().map((k) => {
    const m = /^rotate\((-?[\d.e+-]+)deg\)$/.exec(k.transform || '');
    return m ? parseFloat(m[1]) : k.transform;
  });
}"""


def test_the_chevron_turns_from_the_angle_it_is_drawn_at(make_page, db):
    """החץ מתחיל להסתובב מהזווית שמצוירת ברגע ההקשה, ומגיע לזווית שה-CSS קובע.

    שני מקרים, ושניהם עלו בריוויו של ה-PR: בהקשה רגילה ההתחלה היא הזווית שלפני ההחלפה — זווית
    שנקראת **אחרי** ההחלפה כבר שווה ליעד, והחץ היה קופץ בלי להסתובב (נמדד); ובהקשה חוזרת באמצע
    הסיבוב ההתחלה היא הזווית שבה הוא עצר — עם שתי זוויות קבועות הוא קפץ קודם לזווית ההתחלה הקבועה.
    """
    _seed_files(db, 3)
    p = make_page()
    p.goto("/dashboard")
    p.page.wait_for_selector(f"{GROUP_SEL}.is-open")
    chevron = f"{GROUP_SEL} .group-toggle > .fa-chevron-down"
    toggle = f"{GROUP_SEL} .group-toggle"
    assert abs(p.js(ANGLE_JS, chevron) - 180) < 1, "קבוצה פתוחה — החץ מצביע למעלה"

    # הקשה רגילה: מ-180 (פתוחה) אל 0, וגם בפריים הראשון החץ עוד מצויר ב-180.
    p.page.click(toggle)
    p.js(FREEZE_JS, chevron)
    assert p.js(KEYFRAME_ANGLES_JS, chevron) == pytest.approx([180, 0], abs=1)
    p.js(SEEK_JS, [chevron, 0])
    assert abs(p.js(ANGLE_JS, chevron) - 180) < 1
    p.js(FINISH_JS, chevron)

    # הקשה חוזרת באמצע: נפתחת (0 ← 180), נעצרת בדרך, ונסגרת שוב — מהזווית שבה החץ עצר.
    p.page.click(toggle)
    p.js(FREEZE_JS, chevron)
    p.js(SEEK_JS, [chevron, 0.3])
    mid = p.js(ANGLE_JS, chevron)
    assert 5 < mid < 175, mid
    p.page.click(toggle)
    p.js(FREEZE_JS, chevron)
    assert p.js(KEYFRAME_ANGLES_JS, chevron) == pytest.approx([mid, 0], abs=1), \
        "הסיבוב הקודם בוטל, והחדש מתחיל מהזווית שמצוירת"


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


# --- 5. חלוניות הסרגל (🚀, 🪄) ורשימת "שפות" -------------------------------------------------

#: טלפון לאורך — שם הסרגל מקופל להמבורגר, וחלונית 🚀 היא רשת של ארבע עמודות.
HAMBURGER = {"width": 767, "height": 1227}

#: לכל פריט: ההשהיות של אנימציות ה-JS שעליו (נקראות לפני הסיום), ואחרי שכולן הסתיימו — המרחק
#: של מרכזו ממרכז הכפתור, על המלבן בלי ההזזה של האנימציה.
CASCADE_JS = """([anchorSel, itemSel]) => {
  const items = [...document.querySelectorAll(itemSel)];
  const script = (el) => el.getAnimations()
    .filter((a) => !(a instanceof CSSAnimation) && !(a instanceof CSSTransition));
  const delays = items.map((el) => script(el).map((a) => a.effect.getTiming().delay).sort((p, q) => p - q));
  items.forEach((el) => script(el).forEach((a) => a.finish()));
  const b = document.querySelector(anchorSel).getBoundingClientRect();
  const ax = b.left + b.width / 2, ay = b.top + b.height / 2;
  return items.map((el, i) => {
    const r = el.getBoundingClientRect();
    return {delays: delays[i], d: Math.hypot(r.left + r.width / 2 - ax, r.top + r.height / 2 - ay)};
  });
}"""

#: האם פריט בשורה העליונה של החלונית נחתך בזמן הכניסה: אנימציות ה-JS של הפריטים מוקפאות בהתחלה
#: (הפריט מוזז למעלה), ובודקים מה הדפדפן מוצא בנקודה שבתוך הפריט, ממש מתחת לקצה העליון שלו. חיתוך
#: חוסם גם את בדיקת הפגיעה, ולכן פריט חתוך אינו נמצא שם.
#:
#: **מעברי ה-CSS של החלונית מסתיימים קודם, ולא מוקפאים.** החלונית נפתחת במעבר של ``opacity`` ו-
#: ``visibility``, ובזמן 0 שלו היא עוד ``visibility: hidden`` — ונקודה עוברת דרכה. הקפאה של כל מה
#: שבחלונית נתנה "חתוך" גם כשלא היה שום חיתוך (נמדד: הנקודה פגעה בסרגל גם באמצע הפריט).
TOP_ROW_CLIPPED_JS = """([panelSel, itemSel]) => {
  const panel = document.querySelector(panelSel);
  panel.getAnimations({subtree: true}).forEach((a) => {
    if (a instanceof CSSTransition || a instanceof CSSAnimation) { a.finish(); } else { a.pause(); a.currentTime = 0; }
  });
  const items = [...panel.querySelectorAll(itemSel)];
  const top = Math.min(...items.map((el) => el.getBoundingClientRect().top));
  const el = items.find((x) => Math.abs(x.getBoundingClientRect().top - top) < 0.5);
  const r = el.getBoundingClientRect(), p = panel.getBoundingClientRect();
  const at = (y) => {
    const h = document.elementFromPoint(r.left + r.width / 2, y);
    return !!h && (h === el || el.contains(h));
  };
  return {aboveThePanel: r.top < p.top, clipped: !at(r.top + 1),
          control: at(r.top + r.height / 2), overflowY: getComputedStyle(panel).overflowY};
}"""


def _assert_cascades_outward(rows, step):
    """ההשהיות הן 0, step, 2·step… — אחת לכל פריט — ופריט עם השהיה גדולה יותר אינו קרוב יותר לכפתור."""
    assert all(len(r["delays"]) == 2 and r["delays"][0] == r["delays"][1] for r in rows), rows
    by_delay = sorted(rows, key=lambda r: r["delays"][0])
    assert [r["delays"][0] for r in by_delay] == [i * step for i in range(len(rows))], rows
    distances = [r["d"] for r in by_delay]
    assert distances == sorted(distances), f"הכניסה אינה מהכפתור והחוצה: {by_delay}"


SHORTCUT_MENUS = {
    "rocket": (".quick-access-toggle", "#quickAccessDropdown", "#quickAccessDropdown .quick-access-item"),
    "effects": (".fun-mode-toggle", "#funModeDropdown", "#funModeDropdown .fun-mode-item"),
}


@pytest.mark.parametrize("layout", ["tablet", "hamburger"])
@pytest.mark.parametrize("menu", sorted(SHORTCUT_MENUS))
def test_the_navbar_menus_cascade_out_of_their_button(make_page, db, menu, layout):
    toggle, panel, items = SHORTCUT_MENUS[menu]
    p = make_page(viewport=TABLET if layout == "tablet" else HAMBURGER)
    p.goto("/files")
    if layout == "hamburger":
        assert p.js("() => getComputedStyle(document.querySelector('.mobile-menu-toggle')).display") != "none", \
            "בקרה: הסרגל באמת מקופל להמבורגר"
        if menu == "effects":
            # השרביט בתוך רשימת ההמבורגר. ל-``<i>`` של הכפתור אין קופסה כשהגופן מה-CDN אינו נטען
            # (הבקשות למארחים אחרים נקטעות), ולכן נותנים לו גודל — כמו ``_open_hamburger`` ב-
            # ``tests/test_navbar_menus_browser.py``.
            p.js("""() => { const i = document.querySelector('.mobile-menu-toggle i');
              i.style.display = 'inline-block'; i.style.width = '1em'; i.style.height = '1em'; }""")
            p.page.click(".mobile-menu-toggle")
            poll(p.page, "() => document.getElementById('navMenu').classList.contains('active')"
                         " && !document.getElementById('navMenu').getAnimations({subtree: true})"
                         ".some((a) => a.playState === 'running')", "רשימת ההמבורגר נפתחה ונרגעה")
    p.page.click(toggle)
    p.js(FREEZE_JS, panel)
    step = p.js("() => window.AnimUtils.menuMotion().step")
    _assert_cascades_outward(p.js(CASCADE_JS, [toggle, items]), step)


@pytest.mark.parametrize("direction", ["rtl", "ltr"])
@pytest.mark.parametrize("menu", sorted(SHORTCUT_MENUS))
def test_the_navbar_menus_do_not_clip_items_entering_from_above(make_page, db, menu, direction):
    """החלונית אינה קופסת גלילה (``overflow-x: clip`` ולא ``hidden``), ולכן פריט שנכנס מעט מעליה
    אינו נחתך בקצה העליון שלה."""
    toggle, panel, items = SHORTCUT_MENUS[menu]
    p = make_page()
    p.goto("/files")
    p.js("(d) => { document.documentElement.dir = d; }", direction)
    p.page.click(toggle)
    res = p.js(TOP_ROW_CLIPPED_JS, [panel, items.split(" ", 1)[1]])
    assert res["aboveThePanel"], f"בקרה: בתחילת הכניסה הפריט מעל קצה החלונית — {res}"
    assert res["control"], f"בקרה: באמצע הפריט הנקודה פוגעת בו — {res}"
    assert not res["clipped"], res
    # ``hidden`` או ``auto`` בציר כלשהו הופכים את החלונית לקופסת גלילה, שחותכת בשני הצירים.
    assert p.js("(s) => { const cs = getComputedStyle(document.querySelector(s));"
                " return [cs.overflowX, cs.overflowY]; }", panel) == ["clip", "visible"]


LANGUAGES = ["bash", "c", "cpp", "csharp", "css", "go", "html", "java",
             "javascript", "json", "kotlin", "markdown", "php", "python", "ruby", "rust"]


def test_the_language_list_cascades_only_the_rows_you_can_see(make_page, db):
    _seed_files(db, len(LANGUAGES), languages=LANGUAGES)
    p = make_page()
    p.goto("/files")
    p.page.click("#languageFilterBtn")
    p.js(FREEZE_JS, "#languageFilterDropdown")
    rows = p.js("""() => {
      const list = document.querySelector('#languageFilterDropdown .lang-dropdown-list');
      const box = list.getBoundingClientRect();
      return [...list.querySelectorAll('label')].map((el) => {
        const r = el.getBoundingClientRect();
        return {visible: r.bottom > box.top && r.top < box.bottom, animated: el.getAnimations().length > 0};
      });
    }""")
    assert len(rows) == len(LANGUAGES), rows
    visible = [r["visible"] for r in rows]
    assert any(visible) and not all(visible), f"בקרה: הרשימה נגללת, וחלק מהשורות מתחת לקצה — {rows}"
    assert [r["animated"] for r in rows] == visible, "רק השורות הגלויות מונפשות"
    step = p.js("() => window.AnimUtils.menuMotion().step")
    seen = p.js(CASCADE_JS, ["#languageFilterBtn", "#languageFilterDropdown .lang-dropdown-list label"])
    _assert_cascades_outward([r for r, v in zip(seen, visible) if v], step)


# --- 6. ה-select בחיפוש הגלובלי -------------------------------------------------------------

SEARCH_SELECTS = ("#searchType", "#resultsPerPage", "#sortOrder")

#: האפשרויות של select פתוח: שמות אנימציות ה-CSS וההשהיות שלהן, ואחרי שהן הסתיימו — המלבנים, מול
#: המלבן של התיבה ורוחב החלון.
OPTIONS_JS = """(sel) => {
  const s = document.querySelector(sel);
  const opts = [...s.options];
  const anims = opts.map((o) => o.getAnimations().map((a) => [a.animationName, a.effect.getTiming().delay]).sort());
  s.getAnimations({subtree: true}).forEach((a) => a.finish());
  const box = s.getBoundingClientRect();
  return {open: s.matches(':open'), appearance: getComputedStyle(s).appearance, anims,
          selectBottom: box.bottom,
          rects: opts.map((o) => { const r = o.getBoundingClientRect(); return [r.left, r.right, r.top]; }),
          vw: document.documentElement.clientWidth};
}"""


@pytest.mark.parametrize("direction", ["rtl", "ltr"])
def test_the_search_selects_open_in_the_page_and_their_options_cascade_in(make_page, db, direction):
    p = make_page()
    p.goto("/files")
    p.js("(d) => { document.documentElement.dir = d; }", direction)
    step = p.js("() => window.AnimUtils.menuMotion().step")
    for sel in SEARCH_SELECTS:
        p.page.click(sel)
        p.js(FREEZE_JS, sel)
        res = p.js(OPTIONS_JS, sel)
        assert res["appearance"] == "base-select" and res["open"], (sel, res)
        for i, anims in enumerate(res["anims"]):
            assert anims == [["menuItemFadeIn", i * step], ["menuItemSpringIn", i * step]], (sel, i, anims)
        for left, right, top in res["rects"]:
            assert top >= res["selectBottom"], f"{sel}: הרשימה נפתחת מתחת לתיבה — {res}"
            assert 0 <= left and right <= res["vw"], f"{sel}: הרשימה בתוך רוחב החלון — {res}"
        p.page.keyboard.press("Escape")
        assert not p.js("(s) => document.querySelector(s).matches(':open')", sel), sel


#: הרוחב של הטאבלט של המשתמש (בצילום המסך שלו) ושל טלפון לאורך — שני הרוחבים שבהם השורה לא נכנסה.
NARROW_LAYOUTS = {"tablet": {"width": 1250, "height": 900}, "phone": {"width": 412, "height": 915}}

#: כל הפקדים בשורת הפילטרים, מול הקופסה של השורה עצמה: האם התוכן נכנס בכל תיבה, האם משהו גולש מהשורה,
#: והגובה של כל select — שורת טקסט אחת או יותר.
FILTER_ROW_JS = """() => {
  const row = document.querySelector('.search-and-filters .filters-row').getBoundingClientRect();
  const ids = ['searchType', 'resultsPerPage', 'sortOrder', 'languageFilterBtn'];
  return ids.map((id) => {
    const e = document.getElementById(id), r = e.getBoundingClientRect();
    return {id, value: e.value, scroll: e.scrollWidth, client: e.clientWidth, height: Math.round(r.height),
            inside: r.left >= row.left - 0.5 && r.right <= row.right + 0.5};
  });
}"""


@pytest.mark.parametrize("direction", ["rtl", "ltr"])
@pytest.mark.parametrize("layout", sorted(NARROW_LAYOUTS))
def test_the_filter_row_fits_every_search_type(make_page, db, layout, direction):
    """לכל סוג חיפוש: כל תיבה מכילה את הטקסט ואת החץ, שום פקד אינו יוצא מהשורה, והטקסט בשורה אחת —
    שלוש התיבות באותו גובה כמו כשנבחר "תוכן". ``base-select`` אינו מתכווץ ואינו חותך כמו ה-select
    הרגיל, ולכן תיבה צרה צירה את החץ מחוץ למסגרת, שורה שלא נשברה גלשה בטלפון, ו"חיפוש חכם" נשבר לשתי
    שורות ומתח איתו את שאר התיבות."""
    p = make_page(viewport=NARROW_LAYOUTS[layout])
    p.goto("/files")
    p.js("(d) => { document.documentElement.dir = d; }", direction)
    values = p.js("() => [...document.getElementById('searchType').options].map((o) => o.value)")
    assert "semantic" in values and "docs" in values, f"בקרה: כל סוגי החיפוש, כולל 'תיעוד' של אדמין — {values}"
    baseline = None
    for value in values:
        p.js("""(v) => { const s = document.getElementById('searchType'); s.value = v;
          s.dispatchEvent(new Event('change', {bubbles: true})); }""", value)
        boxes = p.js(FILTER_ROW_JS)
        for b in boxes:
            assert b["scroll"] <= b["client"], f"{value}: התוכן גולש מהתיבה — {b}"
            assert b["inside"], f"{value}: הפקד יוצא מהשורה — {boxes}"
        heights = [b["height"] for b in boxes[:3]]
        baseline = baseline or heights
        assert heights == baseline, f"{value}: גובה התיבות {heights}, ובשורה אחת הוא {baseline}"


def test_the_blocked_search_selects_look_blocked(make_page, db):
    """כשנבחר "תיעוד", מספר התוצאות והמיון חסומים (``syncFiltersWithSearchType``), ונראים חסומים כמו
    שנראו ב-select הרגיל. האורקל הוא select רגיל וחסום באותו עמוד — השקיפות שהדפדפן נותן לו — ולא
    מספר שמוקלד כאן."""
    p = make_page()
    p.goto("/files")
    native = p.js("""() => { const s = document.createElement('select'); s.disabled = true;
      s.style.appearance = 'auto'; document.body.appendChild(s);
      const o = getComputedStyle(s).opacity; s.remove(); return o; }""")
    assert float(native) < 1, f"בקרה: הדפדפן מסמן select רגיל וחסום בשקיפות — {native}"
    p.js("""() => { const s = document.getElementById('searchType'); s.value = 'docs';
      s.dispatchEvent(new Event('change', {bubbles: true})); }""")
    for sel in ("#resultsPerPage", "#sortOrder"):
        state = p.js("(s) => { const e = document.querySelector(s);"
                     " return [e.disabled, getComputedStyle(e).opacity]; }", sel)
        assert state == [True, native], f"{sel}: {state}, וה-select הרגיל החסום — {native}"
        p.page.click(sel, force=True)
        assert not p.js("(s) => document.querySelector(s).matches(':open')", sel), f"{sel}: תיבה חסומה לא נפתחת"
    p.js("""() => { const s = document.getElementById('searchType'); s.value = 'content';
      s.dispatchEvent(new Event('change', {bubbles: true})); }""")
    assert p.js("() => getComputedStyle(document.getElementById('sortOrder')).opacity") == "1"


def test_a_choice_in_the_search_selects_reaches_the_search(make_page, db):
    """בחירה בעכבר ובמקלדת משנה את הערך ומפעילה ``change`` כמו ב-select רגיל — והחיפוש שולח אותה."""
    _seed_files(db, 1)
    p = make_page()
    p.goto("/files")
    p.js("""() => { window.__changes = [];
      ['searchType', 'resultsPerPage', 'sortOrder'].forEach((id) => document.getElementById(id)
        .addEventListener('change', (e) => window.__changes.push(id + '=' + e.target.value))); }""")
    p.page.click("#resultsPerPage")
    p.page.click("#resultsPerPage option[value='20']")
    p.page.click("#sortOrder")
    p.page.click("#sortOrder option[value='name_asc']")
    # מקלדת: החץ פותח את הרשימה על הבחירה הנוכחית, החץ הבא עובר לאפשרות שאחריה, ו-Enter בוחר.
    p.page.focus("#searchType")
    p.page.keyboard.press("ArrowDown")
    assert p.js("() => document.getElementById('searchType').matches(':open')")
    p.page.keyboard.press("ArrowDown")
    p.page.keyboard.press("Enter")
    assert p.js("() => window.__changes") == ["resultsPerPage=20", "sortOrder=name_asc", "searchType=semantic"]

    p.js("() => { document.getElementById('searchType').value = 'content'; }")
    p.page.fill("#globalSearchInput", "print")
    with p.page.expect_request(lambda r: urlsplit(r.url).path == "/api/search/global") as req:
        p.page.click("#searchBtn")
    body = json.loads(req.value.post_data)
    assert (body["limit"], body["sort"]) == (20, "name_asc"), body


def _luminance(rgb):
    def channel(c):
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _rgba(css):
    nums = [float(x) for x in css[css.index("(") + 1:css.index(")")].replace("/", ",").split(",")]
    return nums + [1.0] * (4 - len(nums))


@pytest.mark.parametrize("theme", [None, "dark", "high-contrast"])
def test_the_search_select_list_is_readable_in_every_theme(make_page, db, theme):
    """הרשימה היא המשטח הקשיח (``--solid-surface-*``), אטום, והאפשרויות שקופות עליו — כך שהצבע מאחורי
    הטקסט הוא צבע הרשימה. בלי הצבע המפורש של האפשרויות, הכלל של הרשימה הרגילה צובע אותן ב-
    ``--text-primary``, ובערכת ברירת המחדל ובכהה זה לבן על לבן (נמדד: 1.00). ערכת הניגודיות הגבוהה
    כאן כי היא צובעת את ה-``select`` עצמו בלבן עם ``!important``."""
    p = make_page()
    p.goto("/files")
    if theme:
        p.js("(t) => document.documentElement.setAttribute('data-theme', t)", theme)
    p.page.click("#sortOrder")
    colors = p.js("""() => { const s = document.getElementById('sortOrder');
      const pk = getComputedStyle(s, '::picker(select)');
      return {bg: pk.backgroundColor, options: [...s.options].map((o) => [getComputedStyle(o).color,
              getComputedStyle(o).backgroundColor])}; }""")
    bg = _rgba(colors["bg"])
    assert bg[3] == 1.0, f"הרשימה אטומה — {colors}"
    for color, option_bg in colors["options"]:
        assert _rgba(option_bg)[3] == 0.0, f"האפשרות שקופה על הרשימה — {colors}"
        fg = _rgba(color)
        light, dark = sorted((_luminance(fg[:3]), _luminance(bg[:3])), reverse=True)
        ratio = (light + 0.05) / (dark + 0.05)
        assert ratio >= 4.5, f"ניגודיות {ratio:.2f} בערכה {theme}: {colors}"


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
    assert p.js(SCRIPT_ANIMS_JS, "#quickAccessDropdown") == 0
    p.page.click(".quick-access-item[title='קבצים שנפתחו לאחרונה']")
    p.page.wait_for_selector(".recent-files-modal")
    assert not p.js("() => document.querySelector('.recent-files-modal').classList.contains('is-morph')")
    assert p.js(SCRIPT_ANIMS_JS, ".recent-files-modal") == 0

    p.goto("/files")
    p.page.click(".fun-mode-toggle")
    assert p.js(SCRIPT_ANIMS_JS, "#funModeDropdown") == 0
    p.page.click("#languageFilterBtn")
    assert p.js(SCRIPT_ANIMS_JS, "#languageFilterDropdown") == 0
    # ה-select: אנימציות CSS, ולכן נבדק שאין אף אנימציה על האפשרויות — גם לא כזו שמחכה בהשהיה.
    p.page.click("#searchType")
    assert p.js("() => document.getElementById('searchType').matches(':open')")
    assert p.js("() => [...document.getElementById('searchType').options]"
                ".reduce((n, o) => n + o.getAnimations().length, 0)") == 0
