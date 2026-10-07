"""פתקים בדפדפן הריפו — בכרומיום אמיתי, בעמוד ``/repo/`` האמיתי, במגע של טאבלט.

**שני הבאגים שהקובץ הזה נולד מהם, ושניהם רק בדפדפן הריפו:**

1. **פתק חדש נוצר בראש הקובץ.** ``createNote`` שאל "כמה מהקונטיינר נגלל מעל
   החלון", אבל בדפדפן הריפו הקונטיינר אינו נגלל — הגלילה קורית בתוך
   ``CodeMirror``. פתק שנוצר בתחתית קובץ ארוך נשמר בראשו, מחוץ לתחום הנראה,
   ולמשתמש נראה שהלחיצה לא עשתה כלום. ובשורות ארוכות, אותו דבר לרוחב.
2. **גלילת הקוד ננעלת.** ``_applySurfaceExtent`` הגדיל את הקונטיינר
   (``min-height``) כדי שיכיל את הפתקים, כמו שהוא עושה ללוח. אבל בדפדפן הריפו
   הקונטיינר הוא מסגרת בגובה קבוע בתוך הורה עם ``overflow: hidden``: העורך
   נמתח איתו, טווח הגלילה שלו התקצר בדיוק בכמה שנחתך, וסוף הקובץ לא היה נגיש.

**למה דפדפן, ולמה העמוד האמיתי.** שניהם גאומטריה של פריסה — איפה ``CodeMirror``
גולל, מה ``.repo-content`` חותך, ואיך ``min-height`` אינליין גובר על
``min-height: 0`` של הקונטיינר. בסנדבוקס של ``tests/sticky-notes-target.test.js``
אין פריסה כלל, ועמוד שנכתב ביד היה בודק את הפריסה שהבדיקה מקווה שקיימת. לכן
השרת הוא הוובאפ האמיתי (``admin_live_server``), עם ``base.html`` ותבניות הריפו,
ה-CSS וה-JS מהדיסק, ו-``CodeMirror 6`` מהחבילה המקומית — מה שרץ בפרודקשן,
שבו ה-CSP חוסם את ``CodeMirror 5`` מ-cdnjs. **רק ה-API מזויף**, דרך
``page.route``: עץ הריפו, תוכן הקובץ, והפתקים.

**המגע אמיתי.** ההחלקות והנגיעות עוברות ב-``Input.dispatchTouchEvent`` של
CDP, כלומר בצינור הקלט של הדפדפן ולא ב-``TouchEvent`` שנבנה ב-JS, שאינו מפעיל
גלילה. ההקשר הוא של טאבלט (``is_mobile``, ``has_touch``), בשני הכיוונים.

**מלכודת מדידה שנתפסה בבניית הקובץ:** מחווה שמתחילה מתחת לחלון האמיתי של
הדפדפן מגיעה לאלמנט כאירועי מגע, אבל אינה גוללת. נמדד: החלקה שהתחילה בגובה
757 באזור תצוגה של 800 שלחה ``touchmove`` ל-``.cm-line`` והשאירה את
``scrollTop`` על 0; עם ``--window-size`` ששווה לאזור התצוגה, אותה החלקה גללה.
לכן הדפדפן מורם כאן תמיד עם ``--window-size``.

**מה לא נבדק כאן:** מקלדת וירטואלית אמיתית, תפריט ההקשר של לחיצה ממושכת,
ומכשיר אנדרואיד בכלל — זו אמולציית מגע בכרומיום, לא טאבלט.

מדולג כשאין Chromium (וב-CI אין: ראו ``docs/testing.rst``).
"""

from __future__ import annotations

import contextlib
import json
import time
from urllib.parse import unquote, urlsplit

import pytest

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import WAIT_S, Touch, poll

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

#: הריפו שהעמוד מרנדר כשאין לו ריפו אחר ב-URL או ב-session — ``DEFAULT_REPO_NAME``
#: ב-``webapp/routes/repo_browser.py``. הפתקים מזוהים בזוג (ריפו, נתיב).
REPO = "CodeBot"
CODE_PATH = "src/long_module.py"
MD_PATH = "docs/long_doc.md"

#: טאבלט 12 אינץ' בכרום אנדרואיד, בפיקסלים לוגיים, בשני הכיוונים.
LANDSCAPE = {"width": 1280, "height": 800}
PORTRAIT = {"width": 800, "height": 1280}


def code_file(lines: int, width: int = 0) -> str:
    """קובץ פייתון. ``width`` מאריך כל שורה, כדי שהקוד ייגלל גם לרוחב."""
    tail = "x" * width
    return "\n".join(f"line_{i:05d} = {i}  # {tail}" for i in range(1, lines + 1))


def repo_note(nid: str, *, x: int = 40, y: int, mode: str = "surface", path: str = CODE_PATH) -> dict:
    """פתק ריפו בצורה שהשרת מחזיר ברשימה (``position``/``size``, צבע כ-``hex``)."""
    return {
        "id": nid, "repo_name": REPO, "repo_path": path, "content": nid, "title": "",
        "position": {"x": x, "y": y}, "size": {"width": 260, "height": 200},
        "color": "#FFFFCC", "mode": mode, "is_minimized": False,
    }


class FakeRepoApi:
    """ה-API של דפדפן הריפו ושל הפתקים, בזיכרון.

    **רק מה שהבדיקות צריכות מזויף, וכל השאר עובר לשרת האמיתי.** בקשות
    החוצה (cdnjs, Google Fonts) נקטעות: ה-CSP ממילא חוסם חלק מהן, והבדיקה
    אינה יוצאת מהמכונה. ההתאמה לנתיבים מלאה ולא לפי קידומת, כדי שבקשה אחרת
    תחת ``/api/sticky-notes/`` (סיכום התזכורות, למשל) לא תיבלע כאן בטעות.

    ``created`` הוא מה שנשלח ביצירת פתק — הערך שהשרת היה שומר.
    """

    def __init__(self, path: str, content: str, notes=()):
        self.path = path
        self.content = content
        self.notes = [dict(n) for n in notes]
        self.created: list[dict] = []
        self._scope = f"/api/sticky-notes/repo/{REPO}/{path}"

    def _json(self, route, body, status: int = 200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body))

    def handle(self, route):
        request = route.request
        url = urlsplit(request.url)
        if url.hostname != "127.0.0.1":
            route.abort()
            return
        path = unquote(url.path)
        method = request.method
        if path == f"/repo/api/file/{self.path}":
            language = "markdown" if self.path.endswith(".md") else "python"
            self._json(route, {"content": self.content, "language": language, "path": self.path})
        elif path == "/repo/api/tree":
            name = self.path.rsplit("/", 1)[-1]
            self._json(route, [{"name": name, "path": self.path, "type": "file"}])
        elif path == "/repo/api/repos":
            self._json(route, {"success": True, "repos": [{"repo_name": REPO}],
                               "current": REPO, "current_source": "default"})
        elif path.startswith("/repo/api/"):
            # סוגי קבצים, סטטיסטיקות — שום דבר שהבדיקות כאן נוגעות בו
            self._json(route, {"success": True, "types": []})
        elif path == self._scope and method == "GET":
            self._json(route, {"ok": True, "notes": self.notes})
        elif path == self._scope and method == "POST":
            body = json.loads(request.post_data or "{}")
            self.created.append(body)
            self._json(route, {"ok": True, "id": f"new{len(self.created)}"})
        elif path == "/api/sticky-notes/batch":
            updates = json.loads(request.post_data or "{}").get("updates", [])
            self._json(route, {"ok": True, "results": [
                {"id": u.get("id"), "ok": True, "updated_at": "2026-10-05T00:00:00Z"} for u in updates
            ]})
        elif path.startswith("/api/sticky-notes/note/"):
            self._json(route, {"ok": True, "updated_at": "2026-10-05T00:00:00Z"})
        else:
            route.continue_()


@contextlib.contextmanager
def repo_page(server, executable, api: FakeRepoApi, viewport: dict, *, md_preview: bool = False):
    """עמוד ``/repo/`` על הקובץ של ``api``, עם הפתקים דלוקים — **המקום היחיד שמרים דפדפן כאן**.

    ההעדפה ``repo-notes:<ריפו>:<נתיב>`` נזרעת לפני הטעינה, ולכן ``repo-notes.js``
    מרכיב את המנהל כמו אצל משתמש שכבר הדליק פתקים על הקובץ. כל הניקוי
    ב-``finally``: כשל באמצע לא מדליף דפדפן.
    """
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(
                executable_path=executable,
                args=[f"--window-size={viewport['width']},{viewport['height']}"],
            )
        except Exception as exc:  # pragma: no cover - תלוי בסביבה
            pytest.skip(f"אין Chromium זמין: {exc}")
        try:
            context = browser.new_context(
                viewport=viewport, device_scale_factor=2, is_mobile=True, has_touch=True, locale="he-IL",
            )
            context.add_cookies([{
                "name": "session", "value": server.session_cookie,
                "domain": "127.0.0.1", "path": "/",
            }])
            seed = f"localStorage.setItem('repo-notes:{REPO}:{api.path}','1');"
            seed += "localStorage.setItem('welcomeModalSeen','1');localStorage.setItem('onboarding_completed','1');"
            if md_preview:
                seed += "localStorage.setItem('repo-browser-markdown-preview','true');"
            context.add_init_script("try{" + seed + "}catch(e){}")
            page = context.new_page()
            page.route("**/*", api.handle)
            page.goto(f"{server.base_url}/repo/#file={api.path}", wait_until="load")
            # מודאל הפתיחה מכסה את העמוד ובולע נגיעות; הוא מרונדר גם כשה-localStorage זרוע
            page.evaluate(
                "document.querySelectorAll('.welcome-modal, .welcome-modal__backdrop, #welcomeModal')"
                ".forEach(e => e.remove())"
            )
            if md_preview:
                page.wait_for_selector("#markdown-preview-container .markdown-preview-content > *", timeout=20000)
            else:
                page.wait_for_selector("#code-viewer-container .cm-scroller .cm-line", timeout=20000)
            poll(page, "() => !!(window.repoNotes && window.repoNotes.hasManager())", "מנהל הפתקים הורכב")
            page.wait_for_selector("#code-viewer-container .sticky-note-fab", state="attached", timeout=20000)
            yield page, Touch(context.new_cdp_session(page))
        finally:
            browser.close()


#: הגולל של התצוגה הפעילה — אותה בחירה בדיוק כמו ה-``scroller`` ש-``repo-notes.js`` מזריק.
SCROLLER_JS = """() => {
  const host = document.getElementById('code-viewer-container');
  const md = host.querySelector('.markdown-preview-container');
  return (md && md.offsetParent) ? md : host.querySelector('.cm-scroller');
}"""


def scroller_state(page) -> dict:
    """מצב הגולל: מיקום הגלילה, קופסת ה-client שלו, ו**מה שרואים ממנה באמת**.

    ``client`` היא קופסת התוכן של הגולל. ``visible`` היא החיתוך שלה עם כל אב
    שחותך ועם החלון — וזה ההבדל שהבאג השני יושב בו: כשהקונטיינר נמתח, קופסת
    ה-client של הגולל ארוכה מהמסך, והחלק התחתון שלה אינו נראה בשום גלילה.
    מחוות מגע ובדיקות "בתוך מה שרואים" נמדדות לכן מול ``visible``.
    """
    return page.evaluate(f"""() => {{
      const sc = ({SCROLLER_JS})();
      const b = sc.getBoundingClientRect();
      const left = b.left + sc.clientLeft, top = b.top + sc.clientTop;
      const client = {{left, top, right: left + sc.clientWidth, bottom: top + sc.clientHeight}};
      const visible = Object.assign({{}}, client);
      for (let e = sc.parentElement; e && e !== document.body; e = e.parentElement) {{
        const cs = getComputedStyle(e);
        if (cs.overflowX === 'visible' && cs.overflowY === 'visible') continue;
        const r = e.getBoundingClientRect();
        visible.left = Math.max(visible.left, r.left); visible.top = Math.max(visible.top, r.top);
        visible.right = Math.min(visible.right, r.right); visible.bottom = Math.min(visible.bottom, r.bottom);
      }}
      visible.left = Math.max(visible.left, 0); visible.top = Math.max(visible.top, 0);
      visible.right = Math.min(visible.right, innerWidth); visible.bottom = Math.min(visible.bottom, innerHeight);
      return {{scrollTop: sc.scrollTop, scrollLeft: sc.scrollLeft,
               maxTop: sc.scrollHeight - sc.clientHeight, maxLeft: sc.scrollWidth - sc.clientWidth,
               client, visible}};
    }}""")


def scroll_by_touch(page, touch, *, down_to=None, right_to=None, to_end=False):
    """גולל את התצוגה בהחלקות אצבע, מתוך האזור שבו אין פתקים, עד היעד.

    ההחלקה מתחילה בתוך מה שרואים (``visible``), לא בתוך קופסת ה-client: כשהגולל
    נמתח מעבר למסך, נקודה בתחתית הקופסה יושבת מחוץ לחלון, ומחווה משם אינה גוללת.
    """
    for _ in range(300):
        s = scroller_state(page)
        c = s["visible"]
        need_down = (s["scrollTop"] < s["maxTop"] - 1) if to_end else (down_to is not None and s["scrollTop"] < down_to)
        need_right = right_to is not None and s["scrollLeft"] < right_to
        if not need_down and not need_right:
            return s
        x = c["left"] + (c["right"] - c["left"]) * 0.75
        y = c["bottom"] - 40
        if need_down:
            touch.swipe(x, y, 0, -(c["bottom"] - c["top"]) * 0.6)
        else:
            touch.swipe(x, (c["top"] + c["bottom"]) / 2 + 150, -(c["right"] - c["left"]) * 0.4, 0)
        page.wait_for_timeout(30)
    raise AssertionError(f"הגלילה במגע לא הגיעה ליעד: {scroller_state(page)}")


def settle(page):
    """ממתין שגלילת התנופה תיעצר, ושאנימציית ההופעה של פתק (``noteAppear``) תיגמר.

    **התנופה נמדדת, ולא מנוחשת.** נגיעה בזמן שהתוכן עוד גולש מהחלקה קודמת
    עוצרת את הגלישה ואינה הופכת ללחיצה — כך בדפדפן, ולכן גם כאן. נמדד: בתצוגת
    ה-Markdown נגיעה בכפתור חצי שנייה אחרי ההחלקה האחרונה לא יצרה פתק. לכן
    ממתינים עד ששני מיקומי גלילה רצופים זהים.
    """
    deadline = time.monotonic() + WAIT_S
    previous = None
    while time.monotonic() < deadline:
        current = page.evaluate(f"() => {{ const s = ({SCROLLER_JS})(); return [s.scrollTop, s.scrollLeft]; }}")
        if current == previous:
            break
        previous = current
        page.wait_for_timeout(150)
    else:
        raise AssertionError(f"הגלילה לא נעצרה תוך {WAIT_S} שניות")
    page.wait_for_timeout(400)


def tap_fab(page, touch):
    fab = page.evaluate("""() => { const b = document.querySelector('#code-viewer-container .sticky-note-fab').getBoundingClientRect();
                                   return [b.left + b.width / 2, b.top + b.height / 2]; }""")
    hit = page.evaluate("([x, y]) => { const e = document.elementFromPoint(x, y); return !!(e && e.closest('.sticky-note-fab')); }", fab)
    assert hit, "בקרה: הנקודה שנוגעים בה אינה כפתור הוספת הפתק"
    touch.tap(*fab)


def note_box(page, nid=None) -> dict:
    return page.evaluate("""(nid) => {
      const n = nid ? document.querySelector(`.sticky-note[data-note-id="${nid}"]`) : document.querySelector('.sticky-note');
      const b = n.getBoundingClientRect();
      return {left: b.left, top: b.top, right: b.right, bottom: b.bottom, visibility: getComputedStyle(n).visibility};
    }""", nid)


def assert_fully_in_view(page, box: dict, what: str):
    c = scroller_state(page)["visible"]
    assert box["visibility"] != "hidden", f"{what}: הפתק מוסתר"
    inside = (box["left"] >= c["left"] - 1 and box["right"] <= c["right"] + 1
              and box["top"] >= c["top"] - 1 and box["bottom"] <= c["bottom"] + 1)
    assert inside, f"{what}: הפתק {box} אינו בתוך מה שרואים מהתצוגה {c}"


# -------------------------------------------------------------------------
# באג 1: פתק חדש נפתח איפה שהמשתמש נמצא
# -------------------------------------------------------------------------


def test_a_new_note_opens_where_the_code_is_scrolled_to(admin_live_server, chromium_executable):
    """בתחתית קובץ ארוך, הנגיעה בכפתור פותחת פתק שרואים — ונשמר המיקום שבו הוא מוצג.

    לפני התיקון: הפתק נשמר ב-``inset`` מראש הקובץ, נרשם הרחק מעל הגולל ונשאר
    מוסתר. ההשוואה של מה שנשמר מול מה שמוצג נעשית מה-DOM, בנוסחה עצמאית —
    הפינה של הפתק פחות הפינה של קופסת ה-client של הגולל, ועוד הגלילה — ולא
    דרך הפונקציות של המנהל, שאותן היא בודקת.
    """
    api = FakeRepoApi(CODE_PATH, code_file(600))
    with repo_page(admin_live_server, chromium_executable, api, LANDSCAPE) as (page, touch):
        scroll_by_touch(page, touch, to_end=True)
        settle(page)
        assert scroller_state(page)["scrollTop"] > 5000, "בקרה: הקוד לא נגלל לעומק"
        tap_fab(page, touch)
        poll(page, "() => document.querySelectorAll('#code-viewer-container .sticky-note').length === 1", "הפתק החדש נוצר")
        settle(page)

        assert_fully_in_view(page, note_box(page), "פתק חדש בתחתית קובץ ארוך")
        assert len(api.created) == 1, api.created
        saved = api.created[0]["position"]
        s = scroller_state(page)
        box = note_box(page)
        shown = {"x": box["left"] - s["client"]["left"] + s["scrollLeft"],
                 "y": box["top"] - s["client"]["top"] + s["scrollTop"]}
        assert abs(saved["x"] - shown["x"]) <= 1 and abs(saved["y"] - shown["y"]) <= 1, (
            f"נשמר {saved} אבל מוצג במיקום {shown} בתוך הקובץ")


def test_a_new_note_opens_in_view_when_the_code_is_scrolled_sideways(admin_live_server, chromium_executable):
    """שורות ארוכות בטאבלט לאורך: אחרי גלילה ימינה, הפתק נפתח בתוך מה שרואים.

    לפני התיקון ``x`` היה ``inset`` מתחילת השורה, וגם אחרי תיקון ציר אחד בלבד
    ההצמדה במרחב האחסון (רוחב הקונטיינר) הייתה מחזירה אותו אל מחוץ לתחום.
    """
    api = FakeRepoApi(CODE_PATH, code_file(400, width=180))
    with repo_page(admin_live_server, chromium_executable, api, PORTRAIT) as (page, touch):
        s = scroller_state(page)
        assert s["maxLeft"] > 900, f"בקרה: הקוד אינו רחב מהתצוגה ({s})"
        scroll_by_touch(page, touch, down_to=3000, right_to=900)
        settle(page)
        tap_fab(page, touch)
        poll(page, "() => document.querySelectorAll('#code-viewer-container .sticky-note').length === 1", "הפתק החדש נוצר")
        settle(page)
        assert_fully_in_view(page, note_box(page), "פתק חדש אחרי גלילה לרוחב")


def test_a_new_note_in_the_markdown_preview_opens_in_view(admin_live_server, chromium_executable):
    """תצוגת ה-Markdown היא גולל אחר, ``direction: rtl`` — אותו כלל חל עליה.

    זה המסלול שבו ``_surfaceReach`` עובר בענף ה-``rtl``; ולפני התיקון הפתק
    נשמר גם כאן בראש המסמך.
    """
    doc = "\n\n".join(f"## כותרת {i}\n\nפסקה {i} עם טקסט בעברית." for i in range(1, 250))
    api = FakeRepoApi(MD_PATH, doc)
    with repo_page(admin_live_server, chromium_executable, api, LANDSCAPE, md_preview=True) as (page, touch):
        assert page.evaluate(f"() => getComputedStyle(({SCROLLER_JS})()).direction") == "rtl", (
            "בקרה: התצוגה הפעילה אינה הגולל של ה-Markdown")
        scroll_by_touch(page, touch, down_to=3000)
        settle(page)
        tap_fab(page, touch)
        poll(page, "() => document.querySelectorAll('#code-viewer-container .sticky-note').length === 1", "הפתק החדש נוצר")
        settle(page)
        assert_fully_in_view(page, note_box(page), "פתק חדש בתצוגת Markdown שנגללה")


# -------------------------------------------------------------------------
# באג 2: פתק אינו נועל את גלילת הקוד
# -------------------------------------------------------------------------


def last_line_reachable(page, touch, lines: int):
    """גולל במגע עד הסוף, ומחזיר את השורה האחרונה שנראית ואם היא באמת השורה האחרונה.

    "נראית" — בתוך כל אב שחותך (``overflow`` שאינו ``visible``) עד ה-body. ה-body
    עצמו מחוץ למדידה: הוא נגלל בכמה עשרות פיקסלים בלי שום קשר לפתקים, וזו לא
    השאלה כאן.
    """
    scroll_by_touch(page, touch, to_end=True)
    settle(page)
    return page.evaluate("""(lines) => {
      const sc = document.querySelector('#code-viewer-container .cm-scroller');
      let top = -Infinity, bottom = Infinity;
      for (let e = sc.parentElement; e && e !== document.body; e = e.parentElement) {
        if (getComputedStyle(e).overflowY !== 'visible') {
          const b = e.getBoundingClientRect(); top = Math.max(top, b.top); bottom = Math.min(bottom, b.bottom);
        }
      }
      const shown = Array.from(sc.querySelectorAll('.cm-line')).filter(l => l.getBoundingClientRect().bottom <= bottom + 1);
      const last = shown[shown.length - 1];
      const want = 'line_' + String(lines).padStart(5, '0');
      return {lastShown: last ? last.textContent.slice(0, 10) : null, ok: !!last && last.textContent.startsWith(want)};
    }""", lines)


def frame_state(page) -> dict:
    return page.evaluate("""() => {
      const c = document.getElementById('code-viewer-container');
      return {minHeight: c.style.minHeight, height: c.getBoundingClientRect().height,
              parentHeight: c.parentElement.getBoundingClientRect().height};
    }""")


def header_point(page, nid):
    """נקודה בכותרת הפתק שאינה כפתור — שם הגרירה מתחילה."""
    point = page.evaluate("""(nid) => {
      const h = document.querySelector(`.sticky-note[data-note-id="${nid}"] .sticky-note-header`);
      const b = h.getBoundingClientRect();
      for (let x = b.left + 4; x < b.right - 4; x += 6) {
        const e = document.elementFromPoint(x, b.top + b.height / 2);
        if (e && e.closest('.sticky-note-header') === h && !e.closest('.sticky-note-btn')) return [x, b.top + b.height / 2];
      }
      return null;
    }""", nid)
    assert point, "בקרה: אין בכותרת הפתק נקודה שאינה כפתור"
    return point


@pytest.mark.parametrize("scenario", ["deep-note", "dragged-down", "toggled-to-screen"])
def test_a_note_never_cuts_off_the_end_of_the_file(admin_live_server, chromium_executable, scenario):
    """עם פתק בקובץ, גלילה במגע עדיין מגיעה עד השורה האחרונה.

    שלושת התרחישים מהמדידה, בשני מצבי המיקום:

    - ``deep-note`` — פתק ``surface`` עמוק בקובץ, מהטעינה.
    - ``dragged-down`` — פתק שנגרר אל תחתית התצוגה. ``onUp`` של הגרירה מחשב
      מחדש את גובה המשטח.
    - ``toggled-to-screen`` — אותו פתק עמוק, שהועבר ב-📌 לצף על המסך. החלפת
      המצב אינה מחשבת מחדש, ולכן לפני התיקון הנעילה נשארה עם פתק ``screen``.

    לפני התיקון כל אחד מהם הגדיל את הקונטיינר מעבר להורה, וסוף הקובץ נחתך.
    """
    lines = 600
    notes = [repo_note("a", y=100)] if scenario == "dragged-down" else [repo_note("a", y=2400)]
    api = FakeRepoApi(CODE_PATH, code_file(lines), notes)
    with repo_page(admin_live_server, chromium_executable, api, LANDSCAPE) as (page, touch):
        if scenario == "dragged-down":
            # הכותרת נגררת עד סמוך לתחתית התצוגה, כלומר רוב הפתק יורד מתחתיה —
            # המקום שבו לפני התיקון התחתית שלו עברה את גובה הקונטיינר.
            x, y = header_point(page, "a")
            frame = scroller_state(page)["visible"]
            touch.swipe(x, y, 0, frame["bottom"] - 15 - y, steps=10)
            settle(page)
        elif scenario == "toggled-to-screen":
            page.evaluate(f"() => {{ ({SCROLLER_JS})().scrollTop = 2300; }}")
            settle(page)
            pin = page.evaluate("""() => { const b = document.querySelector('.sticky-note[data-note-id="a"] .sticky-note-pin').getBoundingClientRect();
                                           return [b.left + b.width / 2, b.top + b.height / 2]; }""")
            touch.tap(*pin)
            poll(page, "() => document.querySelector('.sticky-note[data-note-id=\"a\"]').classList.contains('is-floating')",
                 "הפתק עבר למצב צף")
            settle(page)

        frame = frame_state(page)
        result = last_line_reachable(page, touch, lines)
        assert result["ok"], (
            f"{scenario}: השורה האחרונה שאפשר להגיע אליה היא {result['lastShown']} — סוף הקובץ חסום "
            f"(הקונטיינר בגובה {frame['height']} מול {frame['parentHeight']}, min-height={frame['minHeight']!r})")
        assert frame["height"] <= frame["parentHeight"] + 1, f"{scenario}: הקונטיינר גדל מעבר להורה: {frame}"


# -------------------------------------------------------------------------
# הציר האופקי: פתק נשאר איפה שהונח
# -------------------------------------------------------------------------


def test_a_note_dropped_while_scrolled_sideways_stays_where_it_was_dropped(admin_live_server, chromium_executable):
    """גרירה בזמן גלילה לרוחב, ואז גלילה קטנה למטה — הפתק אינו קופץ.

    הגלילה מריצה מחדש את הפריסה של הפתקים הנעוצים (``_updatePinnedForScroll``),
    ושם ההצמדה במרחב האחסון השתמשה ברוחב הקונטיינר: מיקום שנשמר ימינה מהרוחב
    הזה נדחף שמאלה — כלומר הפתק זז בלי שנגעו בו, והמיקום ששמור כבר אינו המוצג.
    """
    api = FakeRepoApi(CODE_PATH, code_file(300, width=180), [repo_note("a", x=300, y=200)])
    with repo_page(admin_live_server, chromium_executable, api, PORTRAIT) as (page, touch):
        page.evaluate(f"() => {{ const s = ({SCROLLER_JS})(); s.scrollTop = 100; s.scrollLeft = 200; }}")
        settle(page)
        x, y = header_point(page, "a")
        touch.swipe(x, y, 150, 0, steps=10)
        settle(page)
        dropped = note_box(page, "a")
        assert_fully_in_view(page, dropped, "בקרה: הפתק אחרי השחרור")

        page.evaluate(f"() => {{ ({SCROLLER_JS})().scrollTop += 1; }}")
        settle(page)
        after = note_box(page, "a")
        assert abs(after["left"] - dropped["left"]) <= 1, (
            f"הפתק קפץ לרוחב אחרי גלילה של פיקסל אחד: {dropped['left']} ← {after['left']}")


def test_a_note_dropped_at_the_right_edge_of_the_markdown_preview_stays_there(admin_live_server, chromium_executable):
    """גרירה אל הקצה הימני של תצוגת ה-Markdown, ואז גלילה של פיקסל — הפתק אינו זז.

    הגרירה מצמידה את הפתק למסגרת — הקונטיינר — והגולל של ה-Markdown צר ממנה:
    ה-``margin`` וה-``border`` של ``.markdown-preview-container`` ב-``markdown-preview.css``.
    הבקרה הראשונה מודדת את ההפרש בעמוד, ולא סומכת על הערכים בקובץ ה-CSS.
    טווח שנגזר מהקופסה של הגולל ולא מהמסגרת הזיז את הפתק
    בגלילה הבאה שמאלה ברוחב שלהם, בדיוק בצד שבו הטקסט העברי מתחיל. בקוד
    שלפני התיקון הפתק לא זז כאן: הבדיקה שומרת על הטווח של הציר האופקי עצמו.
    """
    doc = "\n\n".join(f"## כותרת {i}\n\nפסקה {i} עם טקסט בעברית." for i in range(1, 120))
    api = FakeRepoApi(MD_PATH, doc, [repo_note("a", x=300, y=120, path=MD_PATH)])
    with repo_page(admin_live_server, chromium_executable, api, LANDSCAPE, md_preview=True) as (page, touch):
        page.wait_for_selector('.sticky-note[data-note-id="a"]', state="visible", timeout=20000)
        settle(page)
        edges = page.evaluate(f"""() => {{
          const c = document.getElementById('code-viewer-container'), sc = ({SCROLLER_JS})();
          const cb = c.getBoundingClientRect(), sb = sc.getBoundingClientRect();
          return {{dir: getComputedStyle(sc).direction, frameRight: cb.left + c.clientLeft + c.clientWidth,
                   scrollerRight: sb.left + sc.clientLeft + sc.clientWidth}};
        }}""")
        assert edges["dir"] == "rtl", "בקרה: התצוגה הפעילה אינה הגולל של ה-Markdown"
        assert edges["frameRight"] - edges["scrollerRight"] > 1, (
            f"בקרה: הגולל אינו צר מהמסגרת, ואין כאן מה למדוד ({edges})")

        x, y = header_point(page, "a")
        touch.swipe(x, y, edges["frameRight"] - note_box(page, "a")["right"] + 120, 0, steps=10)
        settle(page)
        dropped = note_box(page, "a")
        assert abs(dropped["right"] - edges["frameRight"]) <= 1, (
            f"בקרה: הגרירה לא הגיעה לקצה המסגרת ({dropped}, {edges})")

        page.evaluate(f"() => {{ ({SCROLLER_JS})().scrollTop += 1; }}")
        settle(page)
        after = note_box(page, "a")
        assert abs(after["left"] - dropped["left"]) <= 1, (
            f"הפתק קפץ לרוחב אחרי גלילה של פיקסל אחד: {dropped['left']} ← {after['left']}")


# -------------------------------------------------------------------------
# מה שאסור שישבר: הלוח עדיין גדל עם הפתקים שלו
# -------------------------------------------------------------------------


def test_the_board_surface_still_grows_with_its_notes(admin_live_server, chromium_executable):
    """בלוח המשטח **כן** גדל — זו כל הסיבה ל-``_applySurfaceExtent``.

    התיקון לדפדפן הריפו מוציא אותו מהמסלול הזה; הבדיקה כאן מוודאת שהלוח
    לא יצא איתו. פתק בעומק המשטח חייב להאריך אותו כך שיהיה אפשר לגלול אליו.
    """
    note = {"id": "deep", "board_id": "b1", "content": "far", "title": "",
            "position": {"x": 40, "y": 2600}, "size": {"width": 260, "height": 200},
            "color": "#FFFFCC", "mode": "surface", "is_minimized": False}

    def handle(route):
        url = urlsplit(route.request.url)
        if url.hostname != "127.0.0.1":
            route.abort()
        elif url.path == "/api/note-boards":
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"ok": True, "boards": [{"id": "b1", "name": "לוח"}]}))
        elif url.path == "/api/sticky-notes/board/b1":
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "notes": [note]}))
        else:
            route.continue_()

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=chromium_executable)
        except Exception as exc:  # pragma: no cover - תלוי בסביבה
            pytest.skip(f"אין Chromium זמין: {exc}")
        try:
            context = browser.new_context(viewport=LANDSCAPE)
            context.add_cookies([{"name": "session", "value": admin_live_server.session_cookie,
                                  "domain": "127.0.0.1", "path": "/"}])
            page = context.new_page()
            page.route("**/*", handle)
            page.goto(f"{admin_live_server.base_url}/boards/b1", wait_until="load")
            page.wait_for_selector('#boardSurface .sticky-note[data-note-id="deep"]', state="attached", timeout=20000)
            # ``_updateSurfaceExtent`` כותב בפריים הבא, לא ברינדור עצמו
            page.wait_for_timeout(400)
            surface = page.evaluate("""() => { const s = document.getElementById('boardSurface');
                                               return {minHeight: s.style.minHeight, height: s.getBoundingClientRect().height}; }""")
            assert surface["minHeight"], "המשטח של הלוח כבר אינו נמדד לפי הפתקים שעליו"
            assert surface["height"] >= 2600 + 200, f"המשטח קצר מהפתק העמוק שעליו: {surface}"
        finally:
            browser.close()
