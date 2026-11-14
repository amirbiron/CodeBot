"""קוד בתוך שורה ותאי טבלה מוצגים לפי הכיוון של התוכן שלהם — בכרומיום אמיתי, בכל המשטחים שמרנדרים Markdown.

**הבאג.** העמודים הם ``dir="rtl"``, וקוד בשורה ותא בטבלה ירשו את הכיוון הזה: ``--flag`` הוצג ``flag--``, ``foo()``
הוצג ``()foo``, ובטבלה ``C++`` הוצג ``++C`` ומיושר לימין. כותרת של עמודה קיבלה מהדפדפן יישור למרכז. התיקון הוא
``md-auto-dir-plugin.js``, שכותב ``dir="auto"`` על כל קוד בשורה ועל כל תא (ההסבר בראש הקובץ), ו-``text-align: start``
בכלל הטבלה של כל משטח. מה ש-markdown-it מוציא נבדק ב-``tests/md-auto-dir-plugin.test.js``.

**המשטחים, בעמודים האמיתיים** (``TESTING-PATTERNS.md`` T1), כמו ב-``tests/test_md_autolink_browser.py``: תצוגת המסמך
(``/md/<id>``), התצוגה החיה בעמוד העריכה (``/edit/<id>``, דרך הכפתור), דפדפן הריפו (``/repo/``, הרנדרר ``default`` שגם
כרטיסי החיפוש בתיעוד משתמשים בו), ודפדפן הריפו כש-``live-preview.js`` לא נטען, כלומר מסלול הגיבוי
``renderMarkdownFallback`` ב-``repo-browser.js``. השרת הוא הוובאפ האמיתי (``admin_live_server``), המסד הוא הדמה של מונגו
(``_fake_mongo``), ובדפדפן הריפו ה-API של הריפו מזויף. בקשות לכל מארח אחר נקטעות.

**המדידה היא של הציור, לא של ה-DOM.** ``MEASURE_JS`` מחשב לכל תו את המרכז האופקי שלו על המסך (``Range`` על התו),
ומשווה: ב-``--flag`` המקף הראשון צריך להיות משמאל ל-``f``. היישור של תא נמדד כמרחק בין קצה הטקסט לקצה התוכן של התא.

**מה נבדק:** ``--flag``, ``foo()`` ו-``C++`` מוצגים כמו במקור; ``C++`` מיושר לשמאל ושתי כותרות העמודות לימין; כל קוד
בשורה וכל תא נושאים ``dir="auto"``, והדפדפן נותן להם ``unicode-bidi: isolate``; ואין בקונסול אזהרה שהתוסף לא נטען.
**ומה לא נשבר:** שם קובץ בעברית, ``הפניות-שלא-חלו.md``, נשאר בסדר הקריאה הטבעי — הסיומת משמאל לשם. ``direction: ltr``
על כל קוד בשורה, כמו בפתקים, היה מעביר אותה לימין, לפני השם.

**מה לא נבדק כאן:** ספארי ופיירפוקס — יש כאן רק כרומיום. הפתקים — יש להם רנדרר משלהם, בלי markdown-it. והקובץ
המיוצא מהעורך הציבורי — הוא עובר דרך אותו ``ensureRenderer``, ומה שהוא מוציא נבדק ב-node.

מדולג כשאין Chromium (וב-CI אין: ראו ``docs/testing.rst``).
"""

from __future__ import annotations

import contextlib
import json
from urllib.parse import unquote, urlsplit

import pytest
from bson import ObjectId

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import CHAR_X_JS, FILE_NAME_SHAPE_JS, copied_to_clipboard, open_admin_page, poll
from _fake_mongo import FakeDB

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

#: ``admin_live_server`` בונה session למשתמש 1, ולכן הקובץ שלו.
USER_ID = 1
FILE_OID = ObjectId("0123456789abcdef0123ad11")

#: טאבלט 12 אינץ' לרוחב, בפיקסלים לוגיים.
TABLET = {"width": 1280, "height": 800}

#: בכל עמודה של הטבלה יש תא רחב מהכותרת (``פונקציה``, ``foo(bar)``) ותא צר ממנו, כדי שהיישור יהיה מדיד: תא שממלא
#: את העמודה נראה מיושר לכל צד.
MARKDOWN = (
    "# כיוון\n\n"
    "פסקה עם `--flag` באמצע.\n\n"
    "קריאה ל-`foo()` כאן.\n\n"
    "שמרו ל-`הפניות-שלא-חלו.md` בסוף.\n\n"
    "המדריך: `מדריך-תצוגת-Markdown-RTL.md` כאן.\n\n"
    "הדוח: `Report-דוח-Q3.md` כאן.\n\n"
    "האפיון: `pdf-עברי-ל-markdown-אפיון-גרסה-ראשונה.md` כאן.\n\n"
    "המסירה: `Handoff: שרשורי תגובות על פתקים — סשן 2.md` כאן.\n\n"
    "| שם | ערך |\n"
    "|---|---|\n"
    "| שפה | C++ |\n"
    "| פונקציה | foo(bar) |\n"
    "| עברית | כן |\n"
)

#: האזהרה שהרנדררים כותבים לקונסול כשהתוסף לא נטען.
MISSING_PLUGIN_WARNING = "md-auto-dir-plugin.js לא נטען"

ROOTS = {
    "md_preview": "#md-content",
    "live_preview": "[data-preview-canvas]",
    "repo_browser": "#markdown-preview-content",
    "repo_fallback": "#markdown-preview-content",
}

#: המדידה. מחזירה מחרוזת עד שהתוכן רונדר, ואחר כך מילון עם ``ok``.
#: שמות שמתחילים באות לטינית ורובם עברית. עם ``dir="auto"`` לבדו האות הלטינית הראשונה קבעה את הכיוון, והמילים
#: התהפכו; ``FileName.codeDir`` נותן להם ``dir="rtl"``.
LATIN_FIRST_HEBREW = ["pdf-עברי-ל-markdown-אפיון-גרסה-ראשונה.md", "Handoff: שרשורי תגובות על פתקים — סשן 2.md"]

MEASURE_JS = """([root]) => {
  const LATIN_FIRST_HEBREW = """ + json.dumps(LATIN_FIRST_HEBREW, ensure_ascii=False) + """;
  const c = document.querySelector(root);
  if (!c) return 'no root';
  const inline = [...c.querySelectorAll('code')].filter((el) => !el.closest('pre'));
  const code = (t) => inline.find((el) => el.textContent === t);
  const cell = (t) => [...c.querySelectorAll('td')].find((el) => el.textContent.trim() === t);
  const flag = code('--flag'), foo = code('foo()'), heb = code('הפניות-שלא-חלו.md'), cpp = cell('C++');
  const guide = code('מדריך-תצוגת-Markdown-RTL.md'), report = code('Report-דוח-Q3.md');
  const latinFirst = LATIN_FIRST_HEBREW.map(code);
  const ths = [...c.querySelectorAll('th')];
  if (!flag || !foo || !heb || !cpp || !guide || !report || latinFirst.some((el) => !el) || ths.length !== 2) {
    return 'not rendered yet';
  }
  // התווים לפי הסדר על המסך, מימין לשמאל — ואותו טקסט בשורה רגילה מימין לשמאל, הסדר שהיה עד ``dir="auto"``.
  const order = (el) => { const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT); const out = []; let n;
    while ((n = w.nextNode())) for (let i = 0; i < n.data.length; i++) { const r = document.createRange();
      r.setStart(n, i); r.setEnd(n, i + 1); const b = r.getBoundingClientRect(); out.push([b.left, n.data[i]]); }
    return out.sort((a, b) => b[0] - a[0]).map((v) => v[1]).join(''); };
  const reference = (t) => { const d = document.createElement('div'); d.dir = 'rtl';
    d.style.cssText = 'position:absolute;top:-2000px;white-space:nowrap'; d.textContent = t; document.body.appendChild(d);
    const o = order(d); d.remove(); return o; };
  // שם קובץ עברי שמפורק — ``FILE_NAME_SHAPE_JS`` ב-``tests/_browser_harness.py``.
  const shape = """ + FILE_NAME_SHAPE_JS + """;
  // המרכז האופקי של התו במיקום i בתוך el, לפי מה שהדפדפן צייר.
  const x = """ + CHAR_X_JS + """;
  // המרחק בין קצה הטקסט לקצה התוכן של התא (בלי הריפוד), משני הצדדים.
  const gaps = (el) => {
    const r = document.createRange(); r.selectNodeContents(el);
    const t = r.getBoundingClientRect(), b = el.getBoundingClientRect(), s = getComputedStyle(el);
    return {
      left: Math.round(t.left - b.left - parseFloat(s.paddingLeft) - parseFloat(s.borderLeftWidth)),
      right: Math.round(b.right - t.right - parseFloat(s.paddingRight) - parseFloat(s.borderRightWidth)),
    };
  };
  const dot = heb.textContent.indexOf('.');
  const cells = [...ths, ...c.querySelectorAll('td')];
  return {
    ok: true,
    flag_dash_left_of_f: x(flag, 0) < x(flag, 2),
    foo_paren_right_of_f: x(foo, 3) > x(foo, 0),
    cpp_c_left_of_plus: x(cpp, 0) < x(cpp, 1),
    heb_name_reads_rtl: x(heb, 0) > x(heb, 1),
    heb_suffix_left_of_name: x(heb, dot) < x(heb, dot - 1),
    cpp_gaps: gaps(cpp),
    th_gaps: ths.map(gaps),
    guide_shape: shape(guide),
    report_shape: shape(report),
    isolated: inline.filter((el) => el.querySelector('bdi')).map((el) => el.textContent).sort(),
    latin_first: latinFirst.map((el) => ({ shown: order(el), reference: reference(el.textContent) })),
    code_dirs: Object.fromEntries(inline.map((el) => [el.textContent, el.getAttribute('dir')])),
    cell_dirs: cells.map((el) => el.getAttribute('dir')),
    isolate: { code: getComputedStyle(flag).unicodeBidi, cell: getComputedStyle(cpp).unicodeBidi },
  };
}"""

#: הקובץ שדפדפן הריפו מציג. ``DEFAULT_REPO_NAME`` ב-``webapp/routes/repo_browser.py``.
REPO = "CodeBot"
REPO_MD_PATH = "docs/direction.md"


def _repo_api(route) -> None:
    """ה-API של הריפו מזויף, כמו ב-``tests/test_md_autolink_browser.py``. כל השאר לשרת."""
    url = urlsplit(route.request.url)
    if url.hostname != "127.0.0.1":
        route.abort()
        return
    path = unquote(url.path)
    body = None
    if path == f"/repo/api/file/{REPO_MD_PATH}":
        body = {"content": MARKDOWN, "language": "markdown", "path": REPO_MD_PATH}
    elif path == "/repo/api/tree":
        body = [{"name": REPO_MD_PATH.rsplit("/", 1)[-1], "path": REPO_MD_PATH, "type": "file"}]
    elif path == "/repo/api/repos":
        body = {"success": True, "repos": [{"repo_name": REPO}], "current": REPO, "current_source": "default"}
    elif path.startswith("/repo/api/"):
        body = {"success": True, "types": []}
    elif path.startswith("/api/sticky-notes/"):
        body = {"ok": True, "notes": []}
    if body is None:
        route.continue_()
    else:
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))


@pytest.fixture(scope="module")
def site(admin_live_server, chromium_executable):
    """הוובאפ מול מסד הדמה, ודפדפן אחד למודול — **המקום היחיד שמרים דפדפן כאן**."""
    import webapp.app as wa

    db = FakeDB()
    db["code_snippets"].insert_one({
        "_id": FILE_OID,
        "user_id": USER_ID,
        "file_name": "direction.md",
        "code": MARKDOWN,
        "programming_language": "markdown",
        "version": 1,
        "is_active": True,
    })
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(wa, "get_db", lambda: db)
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(executable_path=chromium_executable) if chromium_executable \
                    else pw.chromium.launch()
            except PlaywrightError as exc:  # pragma: no cover - תלוי בסביבה
                pytest.skip(f"אין Chromium זמין: {exc}")
            try:
                yield browser, admin_live_server
            finally:
                browser.close()


@contextlib.contextmanager
def opened(surface: str, browser, server):
    """העמוד של המשטח, אחרי שהתוכן רונדר. מחזיר ``(state, console)``."""
    console: list[str] = []
    if surface in ("repo_browser", "repo_fallback"):
        context = browser.new_context(viewport=TABLET, locale="he-IL")
        context.add_cookies([{
            "name": "session", "value": server.session_cookie, "domain": "127.0.0.1", "path": "/",
        }])
        context.add_init_script("try{localStorage.setItem('repo-browser-markdown-preview','true');}catch(e){}")
        page = context.new_page()
        page.on("console", lambda msg: console.append(msg.text))
        blocked = "/static/js/live-preview.js" if surface == "repo_fallback" else None
        page.route("**/*", lambda route: route.abort()
                   if blocked and urlsplit(route.request.url).path == blocked else _repo_api(route))
        page.goto(f"{server.base_url}/repo/#file={REPO_MD_PATH}", wait_until="load")
    else:
        path = f"/md/{FILE_OID}" if surface == "md_preview" else f"/edit/{FILE_OID}"
        page, _touch = open_admin_page(browser, server, path, viewport=TABLET)
        context = page.context
        page.on("console", lambda msg: console.append(msg.text))
        if surface == "live_preview":
            page.click('[data-action="toggle-live-preview"]')
    try:
        state = poll(page, MEASURE_JS, f"{surface}: התוכן רונדר", [ROOTS[surface]])
        # העתקה אמיתית ללוח של שני שמות הקבצים שמפורקים — ``copied_to_clipboard`` ב-``tests/_browser_harness.py``.
        state["clipboard"] = {
            name: copied_to_clipboard(page, server.base_url, ROOTS[surface] + " code", text)
            for name, text in (("guide", "מדריך-תצוגת-Markdown-RTL.md"), ("report", "Report-דוח-Q3.md"))
        }
        if surface == "repo_fallback":
            # בקרה: אילו ``live-preview.js`` נטען בכל זאת, הבדיקה הייתה עוברת במסלול הרגיל.
            assert page.evaluate("() => typeof window.MarkdownLiveRenderer") == "undefined", (
                "repo_fallback: MarkdownLiveRenderer נטען — המסלול שנבדק אינו renderMarkdownFallback"
            )
        yield state, console
    finally:
        context.close()


@pytest.mark.parametrize("surface", list(ROOTS))
def test_inline_code_and_table_cells_follow_their_own_direction(site, surface):
    browser, server = site
    with opened(surface, browser, server) as (state, console):
        pass
    assert state["flag_dash_left_of_f"], f"--flag מוצג הפוך: {state}"
    assert state["foo_paren_right_of_f"], f"foo() מוצג הפוך: {state}"
    assert state["cpp_c_left_of_plus"], f"C++ מוצג הפוך: {state}"
    assert state["cpp_gaps"]["left"] <= 1, f"C++ אינו מיושר לשמאל: {state['cpp_gaps']}"
    assert all(g["right"] <= 1 for g in state["th_gaps"]), f"כותרת עמודה אינה מיושרת לימין: {state['th_gaps']}"
    # ``rtl`` לכל שם קובץ עם עברית (``FileName.codeDir``) — מפורק או לא — ו-``auto`` לכל השאר.
    hebrew_names = {"הפניות-שלא-חלו.md", "מדריך-תצוגת-Markdown-RTL.md", "Report-דוח-Q3.md", *LATIN_FIRST_HEBREW}
    assert state["code_dirs"] == {t: ("rtl" if t in hebrew_names else "auto") for t in state["code_dirs"]}, state["code_dirs"]
    # שם שמתחיל באות לטינית ורובו עברית נראה כמו בשורה מימין לשמאל — ולא הפוך, כמו עם ``dir="auto"``.
    for item in state["latin_first"]:
        assert item["shown"] == item["reference"], item
    assert set(state["cell_dirs"]) == {"auto"}, state["cell_dirs"]
    assert state["isolate"] == {"code": "isolate", "cell": "isolate"}, state["isolate"]
    assert not [line for line in console if MISSING_PLUGIN_WARNING in line], console


@pytest.mark.parametrize("surface", list(ROOTS))
def test_a_hebrew_file_name_keeps_its_reading_order(site, surface):
    browser, server = site
    with opened(surface, browser, server) as (state, console):
        pass
    assert state["heb_name_reads_rtl"], f"השם העברי אינו מימין לשמאל: {state}"
    assert state["heb_suffix_left_of_name"], f"הסיומת עברה לצד ימין של השם: {state}"


#: מה ששם מפורק צריך להראות ב-``FILE_NAME_SHAPE_JS``: כל הסדר מימין לשמאל, והסיומת בקצה השמאלי.
SPLIT_RIGHT = {"one_line": True, "starts_right": True, "tail_left_of_hebrew": True, "dot_left_of_tail": True,
               "extension_left_of_dot": True}


@pytest.mark.parametrize("surface", list(ROOTS))
def test_a_hebrew_file_name_with_a_latin_part_shows_the_extension_at_the_left_end(site, surface):
    """שם קובץ עברי שהחלק האחרון שלו לפני הסיומת לטיני — גם כשהוא מתחיל באנגלית — מוצג עם הסיומת בקצה השמאלי,
    והעתקה שלו ללוח מחזירה אותו בדיוק. נופל על המצב שלפני הפירוק: שם ``dir="auto"`` לבדו השאיר את הסיומת צמודה לחלק
    הלטיני, באמצע השם (נמדד בבקרה ב-``tests/test_sticky_inline_code_dir_browser.py``, על אותו קוד)."""
    browser, server = site
    with opened(surface, browser, server) as (state, console):
        pass
    assert state["guide_shape"] == SPLIT_RIGHT, state["guide_shape"]
    assert state["report_shape"] == SPLIT_RIGHT, state["report_shape"]
    assert state["isolated"] == sorted(["מדריך-תצוגת-Markdown-RTL.md", "Report-דוח-Q3.md"]), state["isolated"]
    assert state["clipboard"] == {"guide": "מדריך-תצוגת-Markdown-RTL.md", "report": "Report-דוח-Q3.md"}, \
        f"Ctrl+C וקריאה מהלוח מחזירים את השם כמו שנכתב: {state['clipboard']}"
    # האזהרות שהתוסף ו-``rtl-code.js`` רושמים כש-``window.FileName`` חסר (``utils/file-name.js`` לא נטען).
    assert not [line for line in console if "file-name.js לא נטען" in line or "window.FileName חסר" in line], console
