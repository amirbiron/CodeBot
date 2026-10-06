"""גלילה וחיפוש בתצוגת קובץ — בכרומיום אמיתי, בעמוד ``/file/<id>`` האמיתי, במגע של טאבלט.

**ארבע התקלות שהקובץ הזה נולד מהן**, ולכל אחת בדיקה אחת. ההסבר המלא יושב ליד
כל תיקון, וכאן רק ההפניה אליו:

1. **מסך רגיל: סרגל החיפוש לא נשאר על המסך.** אחרי קפיצה לתוצאה, ``#code-search``
   נגלל עם העמוד אל מעל המסך, ולא היה על מה ללחוץ כדי להמשיך. ההסבר: הכלל
   ``.main-content, .container`` ב-``base.html``.
2. **מתקדם, מסך רגיל: ▼ לא גולל לתוצאה.** ההסבר: ``EditorView.scrollHandler``
   ב-``view-codemirror-toggle.js``.
3. **מתקדם, מסך מלא: אין גלילה בכלל.**
4. **בסיסי, מסך מלא: סוף הקובץ חתוך.** ההסבר לשתיהן: ``#codeCard:fullscreen``
   ב-``view_file.html``.

ובנוסף, הצד השני של תקלה 1: **סרגל החיפוש של תצוגת ה-Markdown** (``#md-search``)
נשבר מאותה סיבה, ואחרי שהוא נצמד, כותרת שגוללים אליה צריכה לנחות מתחתיו ולא
מאחוריו. ההסבר: ``--md-toolbar-h`` ב-``md_preview.html``.

**וסבב שני: הסרגלים נצמדים רק בזמן חיפוש.** אחרי התיקון של תקלה 1 הסרגל נצמד גם בלי
חיפוש, והסתיר את ראש התוכן לאורך כל הגלילה. עכשיו הוא נצמד רק כשיש טקסט בתיבה, בשתי
התצוגות. ההסבר: ``.editor-toolbar:has(...)`` ב-``view_file.html`` ו-
``.md-editor-toolbar:has(...)`` ב-``md_preview.html``.

**למה דפדפן, ולמה העמוד האמיתי.** כל התקלות הן גאומטריה של פריסה: מי גולל, מי
קופסת הגלילה של מי, ואיפה נגמר אלמנט ביחס לקצה המסך. השרת הוא הוובאפ האמיתי
(``admin_live_server``) מול מונגו אמיתי (``wired_mongo``), עם ``base.html``, ה-CSS
וה-JS מהדיסק, ו-CodeMirror מהחבילה המקומית. בקשות לכל מארח אחר נקטעות.

**המגע אמיתי** (``Touch`` ב-``tests/_browser_harness.py``), והדפדפן מורם עם
``--window-size`` ששווה לאזור התצוגה, מהסיבה שנמדדה ב-``tests/test_repo_notes_browser.py``.

**מה לא נבדק כאן:** מכשיר אנדרואיד אמיתי — זו אמולציית מגע בכרומיום. גם לא שורת
הכתובת שמתכווצת, מסך מלא עם פסי המערכת, והמקלדת הווירטואלית.

מדולג כשאין Chromium (וב-CI אין: ראו ``docs/testing.rst``).
"""

from __future__ import annotations

import contextlib

import pytest
from bson import ObjectId

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import open_admin_page, poll, tap_on

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

#: ``admin_live_server`` בונה session למשתמש 1, ולכן הקבצים שלו.
USER_ID = 1

#: מחרוזת שמופיעה רק בשורות האלה. ההתאמה הראשונה רחוקה מראש הקובץ, כדי שהקפיצה
#: אליה תגלול את העמוד הרבה מעבר למקום הטבעי של הסרגל.
TERM = "zebra_marker"
MATCH_LINES = (60, 150, 280)
LINES = 300

#: טאבלט 12 אינץ' לרוחב, בפיקסלים לוגיים — המכשיר שהתקלות נמצאו בו.
TABLET = {"width": 1280, "height": 800}
#: טלפון לאורך. שם הסרגל של ה-Markdown נשבר לכמה שורות, ולכן הוא גבוה בהרבה.
PHONE = {"width": 390, "height": 844}


def code_text() -> str:
    lines = []
    for i in range(1, LINES + 1):
        if i in MATCH_LINES:
            lines.append(f"value_{i:04d} = '{TERM}'  # line {i}")
        else:
            lines.append(f"value_{i:04d} = {i} * 2  # plain line")
    return "\n".join(lines) + "\n"


def markdown_text() -> str:
    parts = []
    for h in range(1, 9):
        parts.append(f"## Section {h}\n")
        parts.extend(f"paragraph {h}.{i} lorem ipsum dolor sit amet.\n" for i in range(1, 25))
    return "\n".join(parts)


def _insert(wired_mongo, file_name: str, code: str, language: str) -> str:
    """``wired_mongo`` מתחיל ממסד ריק בכל בדיקה, ולכן אין כאן ניקוי."""
    oid = ObjectId()
    wired_mongo.get_db().code_snippets.insert_one({
        "_id": oid, "user_id": USER_ID, "file_name": file_name, "code": code,
        "programming_language": language, "version": 1, "is_active": True,
    })
    return str(oid)


@pytest.fixture
def code_file_id(wired_mongo):
    return _insert(wired_mongo, "long_module.py", code_text(), "python")


@pytest.fixture
def md_file_id(wired_mongo):
    return _insert(wired_mongo, "long_doc.md", markdown_text(), "markdown")


@contextlib.contextmanager
def tablet_page(server, executable, path: str, *, view_mode: str = "basic", viewport=None):
    """עמוד אמיתי במגע של טאבלט — **המקום היחיד שמרים דפדפן כאן**.

    ``ck_view_mode`` נזרע לפני הטעינה, ולכן ``view-codemirror-toggle.js`` עולה ישר
    בתצוגה המבוקשת, כמו אצל משתמש שבחר בה בעבר. כל הניקוי ב-``finally``.
    """
    vp = viewport or TABLET
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(
                executable_path=executable,
                args=[f"--window-size={vp['width']},{vp['height']}"],
            )
        except PlaywrightError as exc:  # pragma: no cover - תלוי בסביבה
            pytest.skip(f"אין Chromium זמין: {exc}")
        try:
            page, touch = open_admin_page(browser, server, path, viewport=vp,
                                          local_storage={"ck_view_mode": view_mode})
            if view_mode == "advanced":
                poll(page, "() => !!document.querySelector('#codeMirrorContainer .cm-editor')"
                           " && !document.getElementById('codeMirrorContainer').hidden",
                     "התצוגה המתקדמת (CodeMirror) עלתה")
            yield page, touch
        finally:
            browser.close()


def enter_fullscreen(page, touch) -> None:
    """כפתור המסך המלא, בנגיעה — ``requestFullscreen`` דורש מחווה אמיתית של המשתמש."""
    tap_on(page, touch, "#fullscreenBtn")
    poll(page, "() => !!document.fullscreenElement && document.fullscreenElement.id === 'codeCard'",
         "הכרטיס עבר למסך מלא")


#: ההתאמה הפעילה: איזו היא, האם היא על המסך, והאם הסרגל מכסה אותה. בתצוגה
#: המתקדמת זו הבחירה של CodeMirror, ובבסיסית ההדגשה הפעילה.
ACTIVE_MATCH_JS = """() => {
  const bar = document.getElementById('code-search').getBoundingClientRect();
  let r = null, which = null;
  const v = window.__ck_view_cm_view;
  if (v && !document.getElementById('codeMirrorContainer').hidden) {
    which = v.state.selection.main.from;
    r = v.coordsAtPos(which);
  } else {
    const all = Array.from(document.querySelectorAll('#codeCard .md-highlight'));
    const el = document.querySelector('#codeCard .md-highlight.is-active');
    if (el) { which = all.indexOf(el); r = el.getBoundingClientRect(); }
  }
  const onScreen = !!r && r.top >= 0 && r.bottom <= innerHeight;
  const underBar = !!r && r.top < bar.bottom && r.bottom > bar.top;
  return {ok: onScreen && !underBar, which,
          match: r ? [Math.round(r.top), Math.round(r.bottom)] : null,
          bar: [Math.round(bar.top), Math.round(bar.bottom)], innerHeight};
}"""

#: הסרגל צמוד לראש המסך.
BAR_PINNED_JS = """() => {
  const top = document.getElementById('code-search').getBoundingClientRect().top;
  return {ok: Math.abs(top) <= 1, barTop: Math.round(top)};
}"""

#: הסרגל נגלל עם העמוד ויצא מהמסך — כלומר **אינו** צמוד. העמוד גלול מעבר למקום
#: הטבעי של הסרגל, ולכן סרגל צמוד היה יושב ב-0 ולא מעל המסך.
BAR_SCROLLED_AWAY_JS = """() => {
  const r = document.getElementById('code-search').getBoundingClientRect();
  return {ok: r.bottom < 0, barTop: Math.round(r.top), barBottom: Math.round(r.bottom),
          scrolled: Math.round(document.body.scrollTop),
          value: document.getElementById('codeSearchInput').value};
}"""


def test_basic_view_search_bar_stays_on_screen_after_jumping_to_a_match(
        code_file_id, admin_live_server, chromium_executable):
    """תקלה 1: אחרי קפיצה לתוצאה, הסרגל צמוד לראש המסך, ואפשר לגעת ב-▼ שעליו.

    הבדיקה אינה נשענת על **לאיזו** התאמה ▼ מוביל: מה שהנגיעה הראשונה אחרי חיפוש
    עושה הוא ממצא 1 ב-#3477, שיתוקן בנפרד. לכן נבדק שהנגיעה הגיעה לכפתור, ושההתאמה
    הפעילה אחריה על המסך ולא מתחת לסרגל.
    """
    with tablet_page(admin_live_server, chromium_executable, f"/file/{code_file_id}") as (page, touch):
        page.fill("#codeSearchInput", TERM)
        poll(page, ACTIVE_MATCH_JS, "הקפיצה הביאה את ההתאמה הראשונה למסך")
        poll(page, BAR_PINNED_JS, "הסרגל צמוד לראש המסך אחרי הקפיצה")
        page.evaluate("""() => {
          window.__nextTaps = 0;
          document.getElementById('nextMatchBtn').addEventListener('click', () => { window.__nextTaps += 1; });
        }""")
        tap_on(page, touch, "#nextMatchBtn")
        poll(page, "() => window.__nextTaps === 1", "הנגיעה הגיעה ל-▼")
        poll(page, ACTIVE_MATCH_JS, "ההתאמה הפעילה על המסך, לא מתחת לסרגל")
        poll(page, BAR_PINNED_JS, "הסרגל עדיין צמוד, ואפשר להמשיך")


def test_advanced_view_next_arrow_brings_the_next_match_on_screen(
        code_file_id, admin_live_server, chromium_executable):
    """תקלה 2: ▼ בתצוגה המתקדמת עובר להתאמה הבאה ומביא אותה למסך, ולא מתחת לסרגל."""
    with tablet_page(admin_live_server, chromium_executable, f"/file/{code_file_id}",
                     view_mode="advanced") as (page, touch):
        page.fill("#codeSearchInput", TERM)
        first = poll(page, ACTIVE_MATCH_JS, "ההתאמה הראשונה על המסך")["which"]
        tap_on(page, touch, "#nextMatchBtn")
        poll(page, f"""() => {{
          const s = ({ACTIVE_MATCH_JS})();
          return {{...s, ok: s.ok && s.which !== {first}}};
        }}""", "ההתאמה הבאה על המסך, לא מתחת לסרגל")


def test_advanced_fullscreen_scrolls_by_touch(code_file_id, admin_live_server, chromium_executable):
    """תקלה 3: במסך מלא בתצוגה המתקדמת, החלקה מזיזה את הקוד."""
    with tablet_page(admin_live_server, chromium_executable, f"/file/{code_file_id}",
                     view_mode="advanced") as (page, touch):
        enter_fullscreen(page, touch)
        # ``.cm-content`` תמיד ב-DOM, גם כשהשורות שבראשו כבר אינן מרונדרות.
        content_top = "document.querySelector('#codeMirrorContainer .cm-content').getBoundingClientRect().top"
        before = page.evaluate(f"() => {content_top}")
        touch.swipe(TABLET["width"] / 2, TABLET["height"] * 0.8, 0, -TABLET["height"] * 0.5)
        poll(page, f"""(before) => {{
          const top = {content_top};
          return {{ok: top <= before - 100, before: Math.round(before), now: Math.round(top)}};
        }}""", "הקוד זז למעלה אחרי ההחלקה", before)


def test_basic_fullscreen_reaches_the_last_line(code_file_id, admin_live_server, chromium_executable):
    """תקלה 4: במסך מלא בתצוגה הבסיסית, השורה האחרונה נכנסת למסך כשגוללים עד הסוף."""
    with tablet_page(admin_live_server, chromium_executable, f"/file/{code_file_id}") as (page, touch):
        enter_fullscreen(page, touch)
        poll(page, """(lastLine) => {
          const box = document.querySelector('#codeCard .code-container');
          box.scrollTop = box.scrollHeight;
          // כל שורה של Pygments נפתחת בעוגן line-N, והאלמנט שאחריו הוא הטוקן הראשון בשורה.
          const r = document.getElementById('line-' + lastLine).nextElementSibling.getBoundingClientRect();
          return {ok: r.bottom <= innerHeight, lastLineBottom: Math.round(r.bottom), innerHeight};
        }""", "השורה האחרונה בתוך המסך", LINES)


@pytest.mark.parametrize("view_mode", ["basic", "advanced"])
def test_code_search_bar_is_pinned_only_while_the_box_has_text(
        code_file_id, admin_live_server, chromium_executable, view_mode):
    """בלי טקסט בתיבה הסרגל נגלל עם העמוד; עם טקסט הוא נצמד; ✕ משחרר אותו.

    ✕ מנקה את התיבה מקוד — ובתצוגה המתקדמת דרך מאזין משלה ב-``view-codemirror-toggle.js``
    — ולכן נבדק שגם ניקוי כזה משחרר את הסרגל, בשתי התצוגות. הגלילה בשלבי ההכנה
    נעשית בקוד: מה שנבדק הוא איפה הסרגל במיקום גלילה נתון, לא איך הגיעו אליו.

    **ולא דרך הקפיצה לתוצאה, וזה מכוון.** נמדד שבתצוגה הבסיסית הקלדה אות אחר אות בתיבה
    שקיבלה פוקוס בנגיעה לא גוללת את העמוד לתוצאה הראשונה, ורק מילוי של כל המחרוזת
    בבת אחת (``page.fill``) גולל — גם לפני השינוי הזה. בדיקה שנשענת על הקפיצה הייתה
    בודקת את ``fill`` ולא את מה שמשתמש עושה.
    """
    with tablet_page(admin_live_server, chromium_executable, f"/file/{code_file_id}",
                     view_mode=view_mode) as (page, touch):
        page.evaluate("document.body.scrollTop = 900")
        poll(page, BAR_SCROLLED_AWAY_JS, "בלי טקסט בתיבה, הסרגל נגלל עם העמוד ויצא מהמסך")

        page.evaluate("document.body.scrollTop = 0")
        tap_on(page, touch, "#codeSearchInput")
        page.keyboard.type(TERM)
        page.evaluate("document.body.scrollTop = 900")
        poll(page, BAR_PINNED_JS, "עם טקסט בתיבה, הסרגל צמוד לראש המסך")

        tap_on(page, touch, "#closeSearchBtn")
        poll(page, f"""() => {{
          const s = ({BAR_SCROLLED_AWAY_JS})();
          return {{...s, ok: s.ok && s.value === ''}};
        }}""", "אחרי ✕ התיבה ריקה, והסרגל נגלל שוב עם העמוד")


#: המצב בתצוגת ה-Markdown אחרי נגיעה בקישור הקבוע של הכותרת השישית.
MD_LANDING_JS = """() => {
  const bar = document.getElementById('md-search').getBoundingClientRect();
  const h = document.querySelectorAll('#md-content h2')[5].getBoundingClientRect();
  return {barTop: Math.round(bar.top), barBottom: Math.round(bar.bottom), headingTop: Math.round(h.top)};
}"""


def _tap_the_sixth_heading_link(page, touch) -> None:
    """הדרך לכותרת היא הקישור הקבוע שלידה (``.header-anchor``), כמו אצל משתמש."""
    poll(page, "() => document.querySelectorAll('#md-content h2 .header-anchor').length === 8",
         "המסמך רונדר עם קישור ליד כל כותרת")
    # הכנה: הכותרת השישית בתחתית המסך, כאילו המשתמש גלל אליה. בתחתית ולא באמצע,
    # כי בטלפון תוכן העניינים הצף (``#mdToc``) מכסה את החלק העליון של המסך.
    page.evaluate("document.querySelectorAll('#md-content h2')[5]"
                  ".scrollIntoView({block: 'end', behavior: 'instant'})")
    tap_on(page, touch, "#md-content h2 .header-anchor", 5)


@pytest.mark.parametrize("viewport", [TABLET, PHONE], ids=["tablet", "phone"])
def test_markdown_search_bar_is_pinned_only_while_searching(
        md_file_id, admin_live_server, chromium_executable, viewport):
    """בלי חיפוש הסרגל נגלל עם המסמך והכותרת נוחתת בראש המסך; בחיפוש — מתחתיו.

    הרווח מעל כותרת (``scroll-margin-top``) חל רק כשהסרגל צמוד, באותו תנאי. בטלפון
    הסרגל גבוה בהרבה, ולכן שני הגדלים.

    **עמוד נפרד לכל מצב, וזה מכוון.** הקישור הקבוע מעתיק ללוח וגולל רק אחרי
    ש-``navigator.clipboard.writeText`` מסתיים. נמדד שנגיעה שנייה באותו קישור, באותו
    עמוד, לא תמיד גוללת בדפדפן הבדיקה. למה ההעתקה השנייה לא מסתיימת שם — לא אומת.
    """
    with tablet_page(admin_live_server, chromium_executable, f"/md/{md_file_id}",
                     viewport=viewport) as (page, touch):
        _tap_the_sixth_heading_link(page, touch)
        poll(page, f"""() => {{
          const s = ({MD_LANDING_JS})();
          return {{...s, ok: s.barBottom < 0 && Math.abs(s.headingTop) <= 1}};
        }}""", "בלי חיפוש: הסרגל נגלל עם המסמך, והכותרת נחתה בראש המסך")

    with tablet_page(admin_live_server, chromium_executable, f"/md/{md_file_id}",
                     viewport=viewport) as (page, touch):
        tap_on(page, touch, "#mdSearchInput")
        page.keyboard.type("Section")
        _tap_the_sixth_heading_link(page, touch)
        poll(page, f"""() => {{
          const s = ({MD_LANDING_JS})();
          return {{...s, ok: Math.abs(s.barTop) <= 1 && s.headingTop >= s.barBottom
                                && s.headingTop <= s.barBottom + 40}};
        }}""", "בחיפוש: הסרגל צמוד, והכותרת נחתה ממש מתחתיו")
