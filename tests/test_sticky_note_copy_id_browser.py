"""כפתור המזהה — העתקת מזהה הפתק — והגודל של פתק חדש, בכרומיום אמיתי ודרך הממשק.

**למה דפדפן.** שלושה דברים כאן רק דפדפן עונה עליהם: הקליפבורד (``navigator.clipboard``
קיים רק בהקשר מאובטח, ונשען על הרשאה), החיווי (מחלקות, ``title`` וטיימר אמיתיים), והגאומטריה
של שורת הכפתורים — מה נכנס בה ומה נחתך בגבול הפתק. ההיגיון עצמו — מה נשלח להעתקה ומתי, ואיזה
גודל נשלח בפתק חדש — ננעל ב-``tests/sticky-notes-target.test.js``, ב-node.

**העמוד.** העמוד הסינתטי של ``tests/test_sticky_note_search_browser.py`` — ה-CSS וה-JS מהדיסק,
ו-``fetch`` מדומה — מוגש ב-``localhost``, כתובת שהדפדפן מחשיב למאובטחת. כך ``_copyText`` עובר
ב-``navigator.clipboard``, כמו בייצור (https), והבדיקה קוראת את הקליפבורד בחזרה. הבקרה שהעמוד
באמת מאובטח נמדדת בכל בדיקה (``isSecureContext``), ולא מונחת.

**פתק שהשרת לא נתן לו מזהה** אינו נוצר מהממשק היום: פתק מוצג רק אחרי שתשובת היצירה הגיעה. כאן
הוא נוצר בדיוק כך — ``createNote`` מול שרת שעונה ``{"ok": true}`` בלי ``id``. זה המצב שבו הכפתור
אומר "הפתק עוד לא נשמר".

**מה לא נבדק כאן:** הקליפבורד של מכשיר אמיתי, וטאבלט או טלפון אמיתיים — הטלפון כאן הוא אמולציה
של כרומיום (``is_mobile``, ``has_touch``). פתק ריפו נבדק בעמוד ``/repo/`` האמיתי, ב-
``tests/test_repo_notes_browser.py``.

מדולג כשאין Chromium.
"""

from __future__ import annotations

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

# **העזרים והפיקסצ'רים של העמוד הסינתטי, ולא עותק שלהם.** ``browser`` ו-``playwright_instance``
# הם פיקסצ'רים של מודול: כאן הם נרשמים מחדש למודול הזה, עם דפדפן משלו — וזה בדיוק ה-scope
# שלהם. הם מגיעים לשער (``chromium_executable``) דרך ``browser``.
from test_sticky_note_search_browser import NotePage, browser, note, playwright_instance  # noqa: E402,F401

#: מזהה בצורה שהשרת שולח: ``str`` של ``ObjectId``.
SAVED = "6ad28b63a89ec90949f8f09e"
#: המזהה שהשרת "נותן" לפתק חדש, בבדיקות שיוצרות פתק.
CREATED = "6ad29310a89ec90949f8f13f"

ORIGIN = "http://localhost"
CLIPBOARD = {"permissions": ["clipboard-read", "clipboard-write"]}
#: אורך החיווי ב-``_flashCopyResult``, ועוד מרווח.
FLASH_DONE_MS = 1800 + 400

DESKTOP = (1280, 800)
PHONE = (390, 844)
PHONE_CONTEXT = {"is_mobile": True, "has_touch": True, "device_scale_factor": 3}

#: ``fetch`` שעונה על יצירת פתק כמו השרת — ``{"ok": true, "id": ...}`` — או בלי ``id`` בכלל,
#: כשהמזהה הוא ``null``. כל השאר עובר ל-``fetch`` המדומה של העמוד.
CREATE_ANSWER_JS = """(id) => {
  const inner = window.fetch;
  window.fetch = async (url, opts) => {
    const method = (opts && opts.method) || 'GET';
    if (method === 'POST' && /\\/api\\/sticky-notes\\/(board\\/[^/]+|file1)$/.test(String(url))) {
      window.__requests.push({ url: String(url), method, body: JSON.parse(String(opts.body)) });
      const answer = id === null ? { ok: true } : { ok: true, id };
      return { ok: true, status: 201, json: async () => answer };
    }
    return inner(url, opts);
  };
}"""


def open_page(browser, notes, *, viewport=DESKTOP, context_opts=None, **page_opts) -> NotePage:  # noqa: F811
    np = NotePage(browser, notes, viewport=viewport, context_opts=dict(CLIPBOARD, **(context_opts or {})),
                  origin=ORIGIN, **page_opts)
    assert np.page.evaluate("() => window.isSecureContext"), "בקרה: העמוד אינו בהקשר מאובטח"
    np.page.evaluate("() => navigator.clipboard.writeText('לפני הלחיצה')")
    return np


def clipboard(np) -> str:
    return np.page.evaluate("() => navigator.clipboard.readText()")


def copy_id_button(np, nid) -> dict:
    return np.page.eval_on_selector(np.sel(nid, ".sticky-note-copy-id"),
                                    "b => ({ title: b.title, cls: b.className, label: b.getAttribute('aria-label') })")


def create_note(np, answer_id):
    """``createNote`` מול שרת שעונה ``answer_id`` (או ``None`` — בלי מזהה); מחזיר את מה שנשלח."""
    np.page.evaluate(CREATE_ANSWER_JS, answer_id)
    before = np.page.evaluate("() => document.querySelectorAll('.sticky-note').length")
    np.page.evaluate("() => window.__mgr.createNote()")
    np.page.wait_for_function("(n) => document.querySelectorAll('.sticky-note').length === n + 1", arg=before)
    sent = np.page.evaluate("() => window.__requests.filter(r => r.method === 'POST').pop().body")
    nid = "undefined" if answer_id is None else answer_id
    np.wait_settled(nid)
    return sent, nid


# ---------------------------------------------------------------------------
# ההעתקה
# ---------------------------------------------------------------------------

#: איפה כפתור המזהה יושב: מיד אחרי כפתור החיפוש בשורת השם, ולא בשורת הפעולות.
PLACEMENT_JS = """(nid) => {
  const n = document.querySelector(`.sticky-note[data-note-id="${nid}"]`);
  const id = n.querySelector('.sticky-note-copy-id');
  return { inNameRow: id.parentElement.classList.contains('sticky-note-drag'),
           afterSearch: !!id.previousElementSibling && id.previousElementSibling.classList.contains('sticky-note-search-btn'),
           inActions: !!n.querySelector('.sticky-note-actions .sticky-note-copy-id') };
}"""


@pytest.mark.parametrize("kind", ["board-surface", "board-screen", "file-screen"])
def test_copies_exactly_the_id_on_every_kind_of_note(browser, kind):  # noqa: F811
    """בלוח (מוצמד ללוח וצמוד למסך) ובקובץ: כפתור המזהה בשורת השם, ליד החיפוש, ומעתיק את 24 התווים בלבד."""
    if kind == "file-screen":
        notes = [note(SAVED, "תוכן", mode="", board_id="", anchor_id="__floating__")]
        np = open_page(browser, notes, file_mode=True)
    else:
        notes = [note(SAVED, "תוכן", mode=kind.split("-")[1])]
        np = open_page(browser, notes)
    try:
        where = np.page.evaluate(PLACEMENT_JS, SAVED)
        assert where == {"inNameRow": True, "afterSearch": True, "inActions": False}, where
        np.page.click(np.sel(SAVED, ".sticky-note-copy-id"))
        np.page.wait_for_function("() => document.querySelector('.sticky-note-copy-id').classList.contains('is-copy-done')")
        assert clipboard(np) == SAVED
        np.page.wait_for_timeout(FLASH_DONE_MS)
        after = copy_id_button(np, SAVED)
        assert "is-copy-done" not in after["cls"] and after["title"] == "העתק את מזהה הפתק", after
        assert np.errors == [], np.errors
    finally:
        np.close()


def test_a_new_note_copies_the_id_the_server_gave_it(browser):  # noqa: F811
    """פתק חדש: מה שמועתק הוא המזהה מתשובת היצירה — הוא שנכתב לפתק, ונקרא ברגע הלחיצה."""
    np = open_page(browser, [])
    try:
        _sent, nid = create_note(np, CREATED)
        np.page.click(np.sel(nid, ".sticky-note-copy-id"))
        np.page.wait_for_function(
            "(nid) => document.querySelector(`.sticky-note[data-note-id='${nid}'] .sticky-note-copy-id`)"
            ".classList.contains('is-copy-done')", arg=nid)
        assert clipboard(np) == CREATED
    finally:
        np.close()


def test_a_note_the_server_gave_no_id_says_not_saved_and_copies_nothing(browser):  # noqa: F811
    """תשובת יצירה בלי ``id``: אין העתקה, והכפתור אומר "הפתק עוד לא נשמר" — ואחר כך חוזר להיות כפתור."""
    np = open_page(browser, [])
    try:
        _sent, nid = create_note(np, None)
        np.page.click(np.sel(nid, ".sticky-note-copy-id"))
        flashing = copy_id_button(np, nid)
        assert "is-copy-fail" in flashing["cls"] and flashing["title"] == "הפתק עוד לא נשמר", flashing
        assert clipboard(np) == "לפני הלחיצה", "הקליפבורד השתנה"
        np.page.wait_for_timeout(FLASH_DONE_MS)
        after = copy_id_button(np, nid)
        assert "is-copy-fail" not in after["cls"] and after["title"] == "העתק את מזהה הפתק", after
        assert after["label"] == "העתקת מזהה הפתק", "השם הנגיש אינו משתנה"
    finally:
        np.close()


BLOCK_CLIPBOARD_JS = """() => {
  Object.defineProperty(navigator, 'clipboard', { configurable: true,
    value: { writeText: () => Promise.reject(new Error('blocked')) } });
  document.execCommand = () => false;
}"""


@pytest.mark.parametrize("button", ["copy-id-not-saved", "copy-content-blocked"])
def test_two_quick_failures_leave_the_original_title(browser, button):  # noqa: F811
    """שתי לחיצות שנכשלות ברצף אינן נועלות את הודעת הכשל על הכפתור.

    נמדד לפני התיקון, על ⧉ עם קליפבורד חסום: אחרי שתי לחיצות בהפרש 300 מילישניות הכפתור נשאר עם
    "ההעתקה נחסמה בדפדפן" גם אחרי שהחיווי ירד — כל לחיצה לכדה את ה-``title`` של אותו רגע.
    """
    np = open_page(browser, [note(SAVED, "תוכן")])
    try:
        if button == "copy-id-not-saved":
            _sent, nid = create_note(np, None)
            sel, original = np.sel(nid, ".sticky-note-copy-id"), "העתק את מזהה הפתק"
        else:
            np.page.evaluate(BLOCK_CLIPBOARD_JS)
            sel, original = np.sel(SAVED, ".sticky-note-copy"), "העתק את תוכן הפתק"
        np.page.click(sel)
        np.page.wait_for_timeout(300)
        np.page.click(sel)
        np.page.wait_for_timeout(FLASH_DONE_MS)
        after = np.page.eval_on_selector(sel, "b => ({ title: b.title, cls: b.className })")
        assert after["title"] == original and "is-copy-fail" not in after["cls"], after
    finally:
        np.close()


# ---------------------------------------------------------------------------
# הגודל של פתק חדש, ושורת הכפתורים
# ---------------------------------------------------------------------------

#: מה שנחתך, ומה שהשורה צריכה. השורה אינה נשברת (``flex: 0 0 auto``) ומתחילה בקצה ה-``start``
#: של הכותרת; כפתור "נחתך" כשהוא חוצה את קצה תיבת הריפוד של הפתק, שם ``overflow: hidden`` חותך.
ROW_JS = """(nid) => {
  const n = document.querySelector(`.sticky-note[data-note-id="${nid}"]`);
  const cs = getComputedStyle(n);
  const r = n.getBoundingClientRect();
  const left = r.left + parseFloat(cs.borderLeftWidth), right = r.right - parseFloat(cs.borderRightWidth);
  const row = n.querySelector('.sticky-note-actions');
  const hs = getComputedStyle(n.querySelector('.sticky-note-header'));
  const startPad = parseFloat(cs.direction === 'rtl' ? hs.paddingRight : hs.paddingLeft);
  const clipped = [...row.children].filter(b => {
    const br = b.getBoundingClientRect();
    return br.left < left - 0.5 || br.right > right + 0.5;
  }).map(b => b.textContent.trim());
  return { width: r.width, height: r.height, clipped, buttons: row.children.length,
           needed: row.getBoundingClientRect().width + startPad
                   + parseFloat(cs.borderLeftWidth) + parseFloat(cs.borderRightWidth) };
}"""


def test_a_new_note_on_a_wide_screen_is_bigger_and_its_whole_row_fits(browser):  # noqa: F811
    """מחשב: הפתק נפתח בגודל שנשלח, ביחס של הגודל הקודם (260×200), וכל שורת הכפתורים בתוכו."""
    np = open_page(browser, [], viewport=DESKTOP)
    try:
        sent, nid = create_note(np, CREATED)
        size = sent["size"]
        assert size["width"] * 200 == size["height"] * 260 and size["width"] > 260, size
        row = np.page.evaluate(ROW_JS, nid)
        assert (round(row["width"]), round(row["height"])) == (size["width"], size["height"]), (row, size)
        assert row["clipped"] == [], row
        assert row["needed"] <= row["width"], row
    finally:
        np.close()


#: האם כפתור המזהה גלוי כולו בתוך הפתק, ומה הדפדפן מוצא במרכז שלו.
VISIBLE_JS = """(nid) => {
  const n = document.querySelector(`.sticky-note[data-note-id="${nid}"]`);
  const id = n.querySelector('.sticky-note-copy-id');
  const nb = n.getBoundingClientRect(), b = id.getBoundingClientRect();
  const hit = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
  return { inside: b.left >= nb.left && b.right <= nb.right && b.top >= nb.top && b.bottom <= nb.bottom,
           hitsIt: hit === id || id.contains(hit) };
}"""


def test_a_new_note_on_a_phone_keeps_the_size_it_had_and_shows_the_id_button(browser):  # noqa: F811
    """טלפון: 200×160, כמו לפני השינוי — בהחלטה. שורת הפעולות אינה נכנסת בו (#3478), אבל כפתור המזהה כן.

    כפתור המזהה בשורת השם בדיוק בשביל זה: שורת הפעולות אינה נשברת, ובפתק ברוחב 200 הקצה שלה חתוך;
    שורת השם יורדת לשורה משלה ומקבלת את כל הרוחב. כאן נבדק שהוא גלוי כולו ושהנגיעה במרכזו
    מגיעה אליו — וגם שההעתקה עוברת במגע.
    """
    np = open_page(browser, [], viewport=PHONE, context_opts=PHONE_CONTEXT)
    try:
        sent, nid = create_note(np, CREATED)
        assert (sent["size"]["width"], sent["size"]["height"]) == (200, 160), sent["size"]
        row = np.page.evaluate(ROW_JS, nid)
        assert (round(row["width"]), round(row["height"])) == (200, 160), row
        assert row["clipped"], f"בקרה: שורת הפעולות אמורה להיחתך ברוחב 200 — {row}"
        assert np.page.evaluate(VISIBLE_JS, nid) == {"inside": True, "hitsIt": True}
        np.page.tap(np.sel(nid, ".sticky-note-copy-id"))
        np.page.wait_for_function(
            "(nid) => document.querySelector(`.sticky-note[data-note-id='${nid}'] .sticky-note-copy-id`)"
            ".classList.contains('is-copy-done')", arg=nid)
        assert clipboard(np) == CREATED
    finally:
        np.close()


def test_notes_that_exist_keep_their_size(browser):  # noqa: F811
    """פתק עם גודל שמור — בגודל שלו; ופתק בלי גודל בכלל — בגיבוי, כמו לפני השינוי ולא כמו פתק חדש."""
    saved = note(SAVED, "תוכן", w=300, h=250, y=20)
    bare = note(CREATED, "תוכן", y=320)
    del bare["size"]
    np = open_page(browser, [saved, bare], viewport=DESKTOP)
    try:
        shown = {nid: np.page.evaluate(ROW_JS, nid) for nid in (SAVED, CREATED)}
        assert (round(shown[SAVED]["width"]), round(shown[SAVED]["height"])) == (300, 250), shown[SAVED]
        assert (round(shown[CREATED]["width"]), round(shown[CREATED]["height"])) == (260, 200), shown[CREATED]
    finally:
        np.close()
