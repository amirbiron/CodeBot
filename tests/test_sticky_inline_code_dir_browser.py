"""קוד בשורה בפתק, ובשם של כרטיס פתק, מוצג לפי הכיוון של התוכן שלו — בכרומיום אמיתי, בעמודים האמיתיים.

**הבאג.** ``.sticky-md-code`` ב-``sticky-notes.css`` כפה ``direction: ltr`` עם ``unicode-bidi: embed`` על כל קוד בשורה
בפתק, וכרטיס של פתק (``fillTitle`` ב-``note-cards.js``) כתב ``dir="ltr"`` על קוד בשם. לכן שם קובץ בעברית בין גרשיים
הוצג הפוך: ב-``הפניות-שלא-חלו.md`` הסיומת עברה לצד ימין, לפני השם, וב-``מדריך-תצוגת-Markdown-RTL.md`` החלק הלטיני עבר
לפני העברי. ובתא טבלה, משפט עברי שמתחיל בקוד ("``foo()`` מחזיר ערך") התהפך כולו לשמאל-לימין, כי הדפדפן קבע את הכיוון
של התא לפי הקוד. **התיקון:** ``dir="auto"`` על הקוד — ``_appendInlineSegments`` בפתק ו-``fillTitle`` בכרטיס — ובלי
``direction`` או ``unicode-bidi`` ב-CSS של שניהם, כמו בתצוגת המסמך (``md-auto-dir-plugin.js``). ה-DOM וה-CSS נבדקים גם
ב-``tests/sticky-notes-target.test.js``, שרץ ב-CI; כאן נמדד מה שמצויר על המסך.

**המשטחים.** לוח (``/boards/<id>``) ופתק ריפו מעל תצוגת ה-Markdown בדפדפן הריפו (``/repo/``), עם הכלים של
``tests/test_note_menu_pages_browser.py`` ו-``tests/test_repo_notes_browser.py``; וכרטיסים בעמוד הארכיון
(``/boards/archive``). השרת הוא הוובאפ האמיתי (``admin_live_server``), ורק ה-API של הפתקים (ושל הריפו) מזויף. אין מסד.

**המדידה היא של הציור, לא של ה-DOM** (``CHAR_X_JS`` ב-``tests/_browser_harness.py``): המרכז האופקי של כל תו על המסך.
בכל משטח יש גם **ריצת בקרה באותו עמוד**: עותק של אותו קוד עם הכלל הישן — בפתק ``direction: ltr`` ו-``unicode-bidi:
embed`` בלי ``dir``, ובכרטיס ``dir="ltr"`` — ושם הסדר חייב לצאת הפוך. בלי הבקרה, מדידה שאינה מבחינה בין שני המצבים
הייתה עוברת גם על הקוד הישן.

**מה לא נבדק כאן:** ספארי ופיירפוקס — יש כאן רק כרומיום. פתק על קובץ בתצוגת המסמך (``/md/<id>``) — אותו מנוע ואותו
CSS, והפתקים שם נבנים תחת ``body`` ולא בתוך ``#md-content``. והפתקים הנעוצים בעמוד הקבצים — אותו רכיב כרטיס כמו
בארכיון, אבל העמוד צריך מונגו אמיתי.

מדולג כשאין Chromium (וב-CI אין: ראו ``docs/testing.rst``).
"""

from __future__ import annotations

import contextlib
import json
from urllib.parse import urlsplit

import pytest

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import CHAR_X_JS, ONE_LINE_JS, poll

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

from test_note_menu_pages_browser import board_note, board_page  # noqa: E402
from test_repo_notes_browser import LANDSCAPE, FakeRepoApi, repo_note, repo_page  # noqa: E402

#: **כל קוד בשורה משלו**, ובשורה קצרה: קוד שנשבר בין שתי שורות מסך היה הופך את ההשוואה בין מיקומי התווים לחסרת
#: משמעות. בטבלה — שני המקרים שבהם התא נשען על הכיוון של הקוד שבתוכו.
NOTE_CONTENT = "\n".join([
    "המדריך: `מדריך-תצוגת-Markdown-RTL.md`",
    "ההפניות: `הפניות-שלא-חלו.md` בסוף",
    "דגל: `--flag` באמצע",
    "קריאה ל-`foo()` כאן",
    "",
    "| מקרה | דוגמה |",
    "|---|---|",
    "| קוד ואז עברית | `foo()` מחזיר ערך |",
    "| רק קוד בעברית | `הפניות-שלא-חלו.md` |",
])

#: פתק רחב מספיק כדי שאף שורה לא תישבר.
NOTE_SIZE = {"width": 640, "height": 420}

#: שם קובץ שמתחיל בעברית נקרא מימין לשמאל. כשאחרי העברית באה רק סיומת, הסיומת צריכה להיות משמאל לשם. כשבא אחריה
#: חלק לטיני (``-Markdown-RTL.md``, מקף ואחריו אות לטינית), החלק הלטיני כולו — עם הסיומת שצמודה אליו — משמאל לעברי,
#: ונקרא משמאל לימין. ``one_line`` נבדק לפני כל השוואה (``ONE_LINE_JS``). ``control`` בונה עותק עם הכלל הישן, מודד
#: אותו ומסיר אותו.
_ORDER_JS = """
  const x = """ + CHAR_X_JS + """;
  const oneLine = """ + ONE_LINE_JS + """;
  const fileName = (el) => {
    const t = el.textContent, dash = t.search(/-[A-Za-z]/);
    const out = {one_line: oneLine(el), name_reads_rtl: x(el, 0) > x(el, 1)};
    if (dash > 0) {
      // ``dash - 1`` היא האות העברית האחרונה, ו-``dash + 1`` תחילת החלק הלטיני.
      out.latin_left_of_hebrew = x(el, dash + 1) < x(el, dash - 1);
      out.latin_reads_ltr = x(el, dash + 1) < x(el, dash + 2);
    } else {
      const dot = t.lastIndexOf('.');
      out.suffix_left_of_name = x(el, dot) < x(el, dot - 1);
    }
    return out;
  };
  const control = (el, mode) => {
    const box = document.createElement('div');
    box.style.whiteSpace = 'nowrap';
    const clone = el.cloneNode(true);
    if (mode === 'note') {
      clone.removeAttribute('dir');
      clone.style.direction = 'ltr';
      clone.style.unicodeBidi = 'embed';
    } else {
      clone.setAttribute('dir', 'ltr');
    }
    box.appendChild(clone);
    el.parentNode.appendChild(box);
    const out = fileName(clone);
    box.remove();
    return out;
  };
"""

#: המדידה בפתק. מחזירה מחרוזת עד שהפתק רונדר, ואחר כך מילון עם ``ok``.
NOTE_MEASURE_JS = """([root]) => {""" + _ORDER_JS + """
  const host = document.querySelector(root);
  if (!host) return 'no note';
  const all = [...host.querySelectorAll('code.sticky-md-code')];
  const line = (t) => all.find((el) => el.textContent === t && !el.closest('.sticky-md-cell'));
  const cell = (t) => [...host.querySelectorAll('td.sticky-md-cell')].find((el) => el.textContent.trim() === t);
  const guide = line('מדריך-תצוגת-Markdown-RTL.md'), refs = line('הפניות-שלא-חלו.md');
  const flag = line('--flag'), foo = line('foo()');
  const mixed = cell('foo() מחזיר ערך'), hebOnly = cell('הפניות-שלא-חלו.md');
  if (!guide || !refs || !flag || !foo || !mixed || !hebOnly) return 'not rendered yet';
  if (!guide.getBoundingClientRect().width) return 'not laid out yet';
  const css = (el) => getComputedStyle(el);
  return {
    ok: true,
    guide: fileName(guide),
    refs: fileName(refs),
    others_one_line: [flag, foo, mixed].every(oneLine),
    flag_dash_left_of_f: x(flag, 0) < x(flag, 2),
    foo_paren_right_of_f: x(foo, 3) > x(foo, 0),
    mixed_cell: {direction: css(mixed).direction,
                 code_right_of_hebrew: x(mixed, 0) > x(mixed, mixed.textContent.indexOf('מ'))},
    heb_only_cell: {direction: css(hebOnly).direction, code: fileName(hebOnly.querySelector('code'))},
    dirs: [...new Set(all.map((el) => el.getAttribute('dir')))],
    bidi: [...new Set(all.map((el) => css(el).unicodeBidi))],
    direction: {guide: css(guide).direction, flag: css(flag).direction},
    control: {guide: control(guide, 'note'), refs: control(refs, 'note')},
  };
}"""

#: כרטיסי הארכיון: שם שכולו קוד עברי, קוד עברי בתוך שם עברי, קוד עברי עם חלק לטיני, וקוד לטיני בתוך שם עברי.
#: **השמות קצרים בכוונה:** הכותרת בכרטיס צרה (כ-135 פיקסלים בטאבלט), ושם ארוך יותר נשבר לכמה שורות — ואז השוואת
#: המיקומים חסרת משמעות. ``one_line`` נבדק בכל מדידה, כדי ששינוי בגודל הכרטיס או בגופן ייכשל בקול.
CARD_TITLES = {
    "a1": "`שלא-חלו.md`",
    "a2": "תיקון `הפניות.md` בסוף",
    "a3": "`מדריך-RTL.md`",
    "a4": "לבדוק `deploy.sh` לפני",
}

CARD_MEASURE_JS = """() => {""" + _ORDER_JS + """
  const code = (id) => document.querySelector(`.archive-card[data-note-id="${id}"] code.archive-card-code`);
  const only = code('a1'), inTitle = code('a2'), mixed = code('a3'), latin = code('a4');
  if (!only || !inTitle || !mixed || !latin) return 'not rendered yet';
  if (!only.getBoundingClientRect().width) return 'not laid out yet';
  const all = [only, inTitle, mixed, latin];
  return {
    ok: true,
    only: fileName(only),
    in_title: fileName(inTitle),
    mixed: fileName(mixed),
    latin: {one_line: oneLine(latin), reads_ltr: x(latin, 0) < x(latin, 1)},
    dirs: [...new Set(all.map((el) => el.getAttribute('dir')))],
    bidi: [...new Set(all.map((el) => getComputedStyle(el).unicodeBidi))],
    control: {only: control(only, 'card'), mixed: control(mixed, 'card')},
  };
}"""

#: מה ששם קובץ בעברית צריך להראות — עם סיומת בלבד, ועם חלק לטיני — על שורה אחת.
RIGHT = {"one_line": True, "name_reads_rtl": True, "suffix_left_of_name": True}
RIGHT_WITH_LATIN = {"one_line": True, "name_reads_rtl": True, "latin_left_of_hebrew": True, "latin_reads_ltr": True}


@contextlib.contextmanager
def _surface(name, server, executable):
    """הפתק ב-``name`` (``board`` / ``repo``) פתוח בעמוד האמיתי. מחזיר ``(page, root)``."""
    if name == "board":
        note = {**board_note("n1", y=40), "content": NOTE_CONTENT, "size": NOTE_SIZE}
        with board_page(server, executable, [note]) as page:
            yield page, '#boardSurface .sticky-note[data-note-id="n1"]'
    else:
        path = "docs/direction.md"
        note = {**repo_note("r1", y=40, path=path), "content": NOTE_CONTENT, "size": NOTE_SIZE}
        api = FakeRepoApi(path, "# מסמך\n\nפסקה.\n", notes=[note])
        with repo_page(server, executable, api, LANDSCAPE, md_preview=True) as (page, _touch):
            yield page, '#code-viewer-container .sticky-note[data-note-id="r1"]'


@pytest.mark.parametrize("surface", ["board", "repo"])
def test_inline_code_in_a_note_follows_its_own_direction(surface, admin_live_server, chromium_executable):
    with _surface(surface, admin_live_server, chromium_executable) as (page, root):
        m = poll(page, NOTE_MEASURE_JS, f"הפתק רונדר ({surface})", [root])

    control = m["control"]
    assert control["refs"]["one_line"] and control["guide"]["one_line"], control
    assert control["refs"]["suffix_left_of_name"] is False, \
        f"בקרה: עם הכלל הישן הסיומת עוברת לימין — אחרת המדידה אינה מבחינה: {control}"
    assert control["guide"]["latin_left_of_hebrew"] is False, f"בקרה: {control}"

    assert m["guide"] == RIGHT_WITH_LATIN, m["guide"]
    assert m["refs"] == RIGHT, m["refs"]
    assert m["others_one_line"] is True
    assert m["flag_dash_left_of_f"] is True
    assert m["foo_paren_right_of_f"] is True
    # הקוד בתא כבר אינו קובע את הכיוון של התא: הדפדפן מדלג על צאצא שיש עליו ``dir`` משלו, והמשפט העברי נשאר מימין
    # לשמאל, עם הקוד בתחילתו — מימין.
    assert m["mixed_cell"] == {"direction": "rtl", "code_right_of_hebrew": True}, m["mixed_cell"]
    # **המחיר, מתועד ב-``docs/dev/sticky_notes_extending_markdown.rst``:** בתא שכל התוכן שלו קוד בעברית אין לתא אות
    # משלו, ולכן הוא משמאל לימין ומיושר לשמאל. הקוד עצמו נקרא נכון.
    assert m["heb_only_cell"] == {"direction": "ltr", "code": RIGHT}, m["heb_only_cell"]
    assert m["dirs"] == ["auto"], m["dirs"]
    assert m["bidi"] == ["isolate"], m["bidi"]
    assert m["direction"] == {"guide": "rtl", "flag": "ltr"}, m["direction"]


@contextlib.contextmanager
def _archive_page(server, executable, notes):
    """עמוד ``/boards/archive`` האמיתי, עם רשימת הארכיון מזויפת. בקשות לכל מארח אחר נקטעות."""
    def handle(route):
        url = urlsplit(route.request.url)
        if url.hostname != "127.0.0.1":
            route.abort()
        elif url.path == "/api/sticky-notes/archive":
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"ok": True, "notes": notes, "max": 500}))
        else:
            route.continue_()

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=executable)
        except Exception as exc:  # pragma: no cover - תלוי בסביבה
            pytest.skip(f"אין Chromium זמין: {exc}")
        try:
            context = browser.new_context(viewport=LANDSCAPE, locale="he-IL")
            context.add_cookies([{"name": "session", "value": server.session_cookie,
                                  "domain": "127.0.0.1", "path": "/"}])
            page = context.new_page()
            page.route("**/*", handle)
            page.goto(f"{server.base_url}/boards/archive", wait_until="load")
            yield page
        finally:
            browser.close()


def test_inline_code_in_a_card_title_follows_its_own_direction(admin_live_server, chromium_executable):
    notes = [{"id": nid, "title": title, "color": "#FFFFCC", "archived_at": "2026-11-13T10:00:00+00:00"}
             for nid, title in CARD_TITLES.items()]
    with _archive_page(admin_live_server, chromium_executable, notes) as page:
        m = poll(page, CARD_MEASURE_JS, "כרטיסי הארכיון רונדרו")

    control = m["control"]
    assert control["only"]["one_line"] and control["mixed"]["one_line"], control
    assert control["only"]["suffix_left_of_name"] is False, \
        f"בקרה: עם dir=\"ltr\" הסיומת עוברת לימין — אחרת המדידה אינה מבחינה: {control}"
    assert control["mixed"]["latin_left_of_hebrew"] is False, f"בקרה: {control}"

    assert m["only"] == RIGHT, m["only"]
    assert m["in_title"] == RIGHT, m["in_title"]
    assert m["mixed"] == RIGHT_WITH_LATIN, m["mixed"]
    assert m["latin"] == {"one_line": True, "reads_ltr": True}, m["latin"]
    assert m["dirs"] == ["auto"], m["dirs"]
    assert m["bidi"] == ["isolate"], m["bidi"]
