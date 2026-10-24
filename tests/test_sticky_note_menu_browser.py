"""תפריט ⋮ בשורת הפעולות של הפתק — בכרומיום אמיתי, דרך הממשק.

**למה דפדפן.** המבנה והחיווט של התפריט — איפה ⋮ יושב, מה בתפריט, מתי הוא נסגר ולאן הפוקוס
חוזר — ננעלים ב-``tests/sticky-notes-target.test.js``, ב-node. כאן מה שרק דפדפן עונה עליו:
**לאן התפריט נפתח** (כלפי מטה אל תוך הפתק, וכלפי מעלה רק כשאין מקום — הכרעה של המשתמש),
**שהוא נשאר על המסך** ליד הקצה (מצמצמים לפני שמזיזים, H7), **שהוא מצויר מעל** פתק שכן, ושפתק
ממוזער שמפסיק לחתוך בזמן שהתפריט פתוח **אינו מגלה שום דבר שהחיתוך הסתיר**.

**שתי הפריסות.** החשבון במלבנים שנמדדו, ולכן אמור להיות נכון בשני הכיוונים — וזה נמדד כאן,
ב-RTL של העמודים וב-LTR, ולא מונח (``rtl-geometry-and-clamp`` ב-``amir-bug-patterns``).

**העמוד.** העמוד הסינתטי של ``tests/test_sticky_note_search_browser.py`` — ה-CSS וה-JS
מהדיסק, ו-``fetch`` מדומה. הלוח האמיתי ודפדפן הריפו, שבו המסגרת חותכת את מה שיוצא ממנה,
נבדקים ב-``tests/test_note_menu_pages_browser.py``.

**מה לא נבדק כאן:** טאבלט או טלפון אמיתיים — הטלפון כאן הוא אמולציה של כרומיום (``is_mobile``,
``has_touch``).

מדולג כשאין Chromium.
"""

from __future__ import annotations

import io

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

# **העזרים והפיקסצ'רים של העמוד הסינתטי, ולא עותק שלהם** — כמו ב-
# ``tests/test_sticky_note_copy_id_browser.py``. ``browser`` ו-``playwright_instance`` הם
# פיקסצ'רים של מודול, ונרשמים כאן מחדש למודול הזה, עם דפדפן משלו. הם מגיעים לשער
# (``chromium_executable``) דרך ``browser``.
from test_sticky_note_search_browser import NotePage, browser, note, playwright_instance  # noqa: E402,F401

DESKTOP = (1280, 800)
PHONE = (390, 844)
PHONE_CONTEXT = {"is_mobile": True, "has_touch": True, "device_scale_factor": 3}

#: ``NOTE_EDGE_GAP`` ב-``sticky-notes.js`` — השוליים מקצה המסך. כאן כדי שהבדיקה תדע מה לצפות.
EDGE_GAP = 12

#: המלבנים של ⋮, של התפריט ושל הפתק, ומה הדפדפן מוצא במרכז הפריט הראשון — כלומר מה מצויר
#: שם בפועל. ``null`` כשהתפריט סגור.
MENU_JS = """(nid) => {
  const n = document.querySelector(`.sticky-note[data-note-id="${nid}"]`);
  const box = (e) => { const r = e.getBoundingClientRect();
    return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height }; };
  const more = n.querySelector('.sticky-note-more');
  const menu = n.querySelector('.sticky-note-menu');
  const out = { note: box(n), more: box(more), expanded: more.getAttribute('aria-expanded'),
                vw: document.documentElement.clientWidth, vh: window.innerHeight,
                unclipped: n.classList.contains('is-unclipped'), menu: null };
  if (!menu) return out;
  const item = menu.querySelector('.sticky-note-menu-item');
  const ib = item.getBoundingClientRect();
  const hit = document.elementFromPoint(ib.left + ib.width / 2, ib.top + ib.height / 2);
  out.menu = box(menu);
  out.above = menu.classList.contains('is-above');
  out.items = [...menu.querySelectorAll('.sticky-note-menu-item')].map((b) => b.textContent);
  out.hitsItem = hit === item || item.contains(hit);
  return out;
}"""

#: מה מוקד עכשיו — לפי מחלקה, כדי לדעת אם זה ⋮, פריט בתפריט, או משהו אחר.
FOCUS_JS = "() => document.activeElement ? document.activeElement.className : null"


def open_menu(np, nid):
    np.page.click(np.sel(nid, ".sticky-note-more"))
    np.page.wait_for_selector(np.sel(nid, ".sticky-note-menu"))
    return np.page.evaluate(MENU_JS, nid)


def centered_under_more(m) -> float:
    """כמה מרכז התפריט רחוק ממרכז ⋮, לרוחב."""
    return abs((m["menu"]["left"] + m["menu"]["right"]) / 2 - (m["more"]["left"] + m["more"]["right"]) / 2)


def assert_on_screen(m):
    menu = m["menu"]
    assert menu["left"] >= EDGE_GAP - 0.5 and menu["right"] <= m["vw"] - EDGE_GAP + 0.5, m
    assert menu["top"] >= EDGE_GAP - 0.5 and menu["bottom"] <= m["vh"] - EDGE_GAP + 0.5, m
    assert m["hitsItem"], f"הפריט אינו מצויר למעלה — מה שמצויר שם אחר: {m}"


# ---------------------------------------------------------------------------
# כיוון הפתיחה
# ---------------------------------------------------------------------------

def test_the_menu_opens_down_into_the_note(browser):  # noqa: F811
    """פתק פתוח עם מקום: התפריט נפתח מתחת ל-⋮, ממורכז מתחתיו, וכולו בתוך הפתק — מעל התוכן."""
    np = NotePage(browser, [note("a", "שורה\n" * 12, w=360, h=320, x=200, y=160)], viewport=DESKTOP)
    try:
        m = open_menu(np, "a")
        assert m["items"] == ["🔔"], m
        assert m["expanded"] == "true" and m["unclipped"], m
        assert not m["above"] and m["menu"]["top"] >= m["more"]["bottom"], m
        assert centered_under_more(m) < 1, m
        note_box, menu = m["note"], m["menu"]
        assert (menu["left"] >= note_box["left"] and menu["right"] <= note_box["right"]
                and menu["bottom"] <= note_box["bottom"]), f"התפריט אמור להיות בתוך הפתק: {m}"
        assert_on_screen(m)
        assert np.errors == [], np.errors
    finally:
        np.close()


@pytest.mark.parametrize("where", ["bottom", "top"])
def test_a_minimized_note_opens_the_menu_up_only_when_there_is_no_room_below(browser, where):  # noqa: F811
    """פתק ממוזער הוא שורת הכותרת בלבד, והתפריט יוצא ממנו. בתחתית המסך — כלפי מעלה; למעלה — כלפי מטה.

    ``top`` הוא הבקרה: אותו פתק, אותו תפריט, ורק המקום משתנה — כך ההיפוך נגזר מהמקום ולא מהמזעור.

    **פתק ``surface`` ולא ``screen``.** פתק ``screen`` מוצמד למסך לפי הגודל שנקבע לו ולא לפי מה
    שמוצג (``_fitAndClampToViewport``), ולכן גם פתק ממוזער נעצר גבוה מספיק מהתחתית כדי שהתפריט
    ייכנס מתחתיו (נמדד: ``top`` 700 במסך של 800, והתפריט נגמר ב-778). פתק על המשטח נגלל עם
    העמוד, ולכן הכותרת שלו יכולה לשבת ממש בתחתית המסך — וזה המקרה שבו אין מקום.
    """
    y = DESKTOP[1] - 60 if where == "bottom" else 100
    np = NotePage(browser, [note("m", "תוכן", w=360, h=240, x=300, y=y, minimized=True)], viewport=DESKTOP)
    try:
        m = open_menu(np, "m")
        if where == "bottom":
            assert m["above"] and m["menu"]["bottom"] <= m["more"]["top"], m
        else:
            assert not m["above"] and m["menu"]["top"] >= m["more"]["bottom"], m
            assert m["menu"]["bottom"] > m["note"]["bottom"], f"בקרה: התפריט אמור לצאת מהפתק הממוזער: {m}"
        assert_on_screen(m)
        assert np.errors == [], np.errors
    finally:
        np.close()


#: עוטף את משטח הלוח באב שחותך (``overflow: hidden``) בגובה 400 — אב של ה-containing block של
#: הפתקים, ולא ה-containing block עצמו.
CLIP_WRAP_JS = """() => {
  const s = document.getElementById('boardSurface');
  const wrap = document.createElement('div');
  wrap.id = 'clipWrap';
  wrap.style.cssText = 'height:400px; overflow:hidden;';
  s.parentNode.insertBefore(wrap, s);
  wrap.appendChild(s);
}"""


def test_inside_a_clipping_ancestor_the_menu_flips_before_the_screen_edge(browser):  # noqa: F811
    """אב שחותך את הפתק קובע את הגבול, ולא רק המסך: מתחת ל-⋮ יש מקום במסך, אבל לא בתוך האב.

    האב הוא הורה של משטח הלוח, כלומר של ה-containing block — ולכן הבדיקה עוברת גם בענף שבו
    ``_noteMenuBounds`` מטפס מעל ``offsetParent`` (CSS 2.1, סעיף 11.1.1). בלי החיתוך עם האב,
    התפריט נפתח כלפי מטה ונחתך בקצה האב — ``hitsItem`` נופל.
    """
    np = NotePage(browser, [], viewport=DESKTOP)
    try:
        np.page.evaluate(CLIP_WRAP_JS)
        np.page.evaluate("""() => window.__mgr._renderNote({ id: 'w', board_id: 'b1', content: 'תוכן', title: '',
            position: { x: 300, y: 330 }, size: { width: 360, height: 240 }, color: 'yellow',
            mode: 'surface', is_minimized: true })""")
        np.wait_settled("w")
        wrap = np.rect("#clipWrap")
        m = open_menu(np, "w")
        assert m["vh"] - m["more"]["bottom"] > 200, f"בקרה: מתחת ל-⋮ אמור להיות מקום במסך: {m}"
        assert m["above"] and m["menu"]["bottom"] <= m["more"]["top"], m
        assert m["menu"]["top"] >= wrap["top"] + EDGE_GAP - 0.5, (m, wrap)
        assert m["hitsItem"], f"הפריט אינו מצויר למעלה: {m}"
    finally:
        np.close()


def test_a_file_note_opens_the_menu_down(browser):  # noqa: F811
    """פתק על קובץ (``/md/<id>``) — הקונטיינר הוא ה-body, ו-``offsetParent`` של פתק צף הוא null."""
    np = NotePage(browser, [note("f", "תוכן", w=360, h=300, x=300, y=160, mode="", board_id="",
                                 anchor_id="__floating__")], viewport=DESKTOP, file_mode=True)
    try:
        where = np.page.eval_on_selector(np.sel("f"), "n => [n.style.position, n.offsetParent === null]")
        assert where == ["fixed", True], f"בקרה: פתק צף על קובץ אמור להיות fixed, בלי offsetParent — {where}"
        m = open_menu(np, "f")
        assert not m["above"] and m["menu"]["top"] >= m["more"]["bottom"], m
        assert centered_under_more(m) < 1, m
        assert_on_screen(m)
        assert np.errors == [], np.errors
    finally:
        np.close()


# ---------------------------------------------------------------------------
# ליד קצה המסך, ובשתי הפריסות
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("direction", ["rtl", "ltr"])
def test_the_menu_is_centered_under_the_button_in_both_layouts(browser, direction):  # noqa: F811
    """ב-RTL ⋮ הוא הכפתור השמאלי בשורה, וב-LTR הימני — והתפריט ממורכז מתחתיו בשני המקרים."""
    np = NotePage(browser, [note("a", "תוכן", w=360, h=300, x=400, y=160)], viewport=DESKTOP)
    try:
        np.page.evaluate("(d) => { document.documentElement.dir = d; }", direction)
        row = np.page.evaluate("""(nid) => [...document.querySelector(`.sticky-note[data-note-id="${nid}"]`
            + ' .sticky-note-actions').children].map((b) => b.getBoundingClientRect().left)""", "a")
        more_left = row[-1]
        if direction == "rtl":
            assert more_left == min(row), f"ב-RTL ⋮ אמור להיות השמאלי: {row}"
        else:
            assert more_left == max(row), f"ב-LTR ⋮ אמור להיות הימני: {row}"
        m = open_menu(np, "a")
        assert centered_under_more(m) < 1, m
        assert not m["above"] and m["menu"]["top"] >= m["more"]["bottom"], m
        assert_on_screen(m)
    finally:
        np.close()


@pytest.mark.parametrize("direction", ["rtl", "ltr"])
def test_near_the_edge_the_menu_is_pulled_back_onto_the_screen(browser, direction):  # noqa: F811
    """⋮ ליד קצה המסך — שמאל ב-RTL, ימין ב-LTR: התפריט אינו ממורכז, אלא נשאר במרחק השוליים מהקצה.

    הבקרה בתוך הבדיקה: ``centered_under_more`` גדול מאפס, כלומר ההצמדה באמת פעלה — אחרת
    הבדיקה הייתה עוברת גם על תפריט ממורכז שבמקרה נכנס.
    """
    np = NotePage(browser, [], viewport=PHONE, context_opts=PHONE_CONTEXT)
    try:
        np.page.evaluate("(d) => { document.documentElement.dir = d; }", direction)
        # פתק ברוחב 280 בקצה: ב-RTL השורה מתחילה מימין, ו-⋮ שבסופה נוחת ליד הקצה השמאלי. ברוחב
        # 300 הוא נוחת רחוק מספיק מהקצה כדי שתפריט ממורכז ייכנס (נמדד: 33px מהקצה), והבקרה
        # שלמטה נכשלה עליו — כלומר הבדיקה לא בדקה הצמדה.
        x = 0 if direction == "rtl" else PHONE[0] - 280
        np.page.evaluate("""([x]) => window.__mgr._renderNote({ id: 'e', board_id: 'b1', content: 'תוכן',
            title: '', position: { x, y: 160 }, size: { width: 280, height: 240 }, color: 'yellow',
            mode: 'surface', is_minimized: false })""", [x])
        np.wait_settled("e")
        np.page.tap(np.sel("e", ".sticky-note-more"))
        np.page.wait_for_selector(np.sel("e", ".sticky-note-menu"))
        m = np.page.evaluate(MENU_JS, "e")
        assert centered_under_more(m) > 0.5, f"בקרה: ⋮ אמור להיות קרוב מספיק לקצה כדי שתפריט ממורכז יגלוש: {m}"
        if direction == "rtl":
            assert abs(m["menu"]["left"] - EDGE_GAP) < 1, m
        else:
            assert abs(m["menu"]["right"] - (m["vw"] - EDGE_GAP)) < 1, m
        assert_on_screen(m)
        assert np.errors == [], np.errors
    finally:
        np.close()


# ---------------------------------------------------------------------------
# מה מצויר מעל מה, ומה החיתוך הסתיר
# ---------------------------------------------------------------------------

def test_the_menu_is_drawn_over_a_neighbouring_note(browser):  # noqa: F811
    """פתק שכן שמצויר אחרי הפתק מכסה את מה שמתחת ל-⋮ — ופתיחת התפריט מעלה את הפתק מעליו."""
    np = NotePage(browser, [note("a", "תוכן", w=360, h=300, x=400, y=160),
                            note("b", "שכן", w=360, h=300, x=300, y=200)], viewport=DESKTOP)
    try:
        before = np.page.evaluate("""() => {
            const more = document.querySelector('.sticky-note[data-note-id="a"] .sticky-note-more').getBoundingClientRect();
            const hit = document.elementFromPoint(more.left + more.width / 2, more.bottom + 20);
            const n = hit && hit.closest('.sticky-note');
            return n ? n.dataset.noteId : null; }""")
        assert before == "b", f"בקרה: מתחת ל-⋮ של A אמור להיות מצויר B — נמצא {before}"
        # הפתיחה דרך המקלדת: B מכסה גם את ⋮ של A, ולחיצה בעכבר הייתה נוחתת על B.
        np.page.focus(np.sel("a", ".sticky-note-more"))
        np.page.keyboard.press("Enter")
        np.page.wait_for_selector(np.sel("a", ".sticky-note-menu"))
        m = np.page.evaluate(MENU_JS, "a")
        assert m["hitsItem"], f"התפריט של A מוסתר מאחורי B: {m}"
    finally:
        np.close()


def _png_pixels(png: bytes):
    from PIL import Image

    img = Image.open(io.BytesIO(png)).convert("RGB")
    return img, img.load()


#: רדיוס הפינה של הפתק — ``--note-radius`` ב-``sticky-notes.css``.
NOTE_RADIUS = 10


def test_a_minimized_note_reveals_nothing_while_its_menu_is_open(browser):  # noqa: F811
    """פתק ממוזער מפסיק לחתוך כשהתפריט פתוח (``.is-unclipped``) — ושום דבר שהחיתוך הסתיר לא יוצא.

    זה צירוף שלא היה קיים לפני התפריט: החיפוש והשרשורים מושבתים בפתק ממוזער, ולכן פתק ממוזער
    לא הפסיק לחתוך אף פעם. ההשוואה היא של ``test_nothing_the_note_clipped_leaks_out_while_searching``
    (``tests/test_sticky_note_search_browser.py``): מה שמחוץ לפתק, ו**ארבע** הפינות מחוץ לקשת —
    בפתק ממוזער הכותרת היא כל הפתק, ולכן גם הפינות התחתונות שלה. מה שמוחרג: התפריט, והצל שלו.

    נמדד לפני תיקון ה-CSS: הפינות התחתונות של הכותרת יצאו ישרות, ורקע הכותרת נראה מחוץ לקשת.
    """
    from PIL import ImageChops  # מוצמד ב-requirements/base.txt

    content = "\n".join(f"שורה ארוכה מאוד מספר {i} שממלאת את רוחב הפתק כולו" for i in range(30))
    np = NotePage(browser, [note("m", content, w=360, h=400, x=300, y=300, minimized=True)], viewport=DESKTOP,
                  context_opts={"device_scale_factor": 2})
    try:
        np.page.hover(np.sel("m", ".sticky-note-more"))
        before, _ = _png_pixels(np.page.screenshot())
        m = open_menu(np, "m")
        assert m["unclipped"], f"בקרה: הפתק אמור להפסיק לחתוך כשהתפריט פתוח: {m}"
        after, _ = _png_pixels(np.page.screenshot())
    finally:
        np.close()
    diff = ImageChops.difference(before, after).load()
    dpr = before.width / DESKTOP[0]
    # הצל של התפריט (``box-shadow`` עם טשטוש של 30px) יוצא ממנו — ולכן מחריגים שוליים סביבו.
    halo = 48
    menu, box = m["menu"], m["note"]
    nx0, nx1, ny0, ny1 = box["left"], box["right"], box["top"], box["bottom"]
    r = NOTE_RADIUS
    leaks = []
    for py in range(before.height):
        for px in range(before.width):
            if sum(diff[px, py]) <= 12:
                continue
            x, y = (px + 0.5) / dpr, (py + 0.5) / dpr        # מרכז הפיקסל, בפיקסלי CSS
            if menu["left"] - halo <= x <= menu["right"] + halo and menu["top"] - halo <= y <= menu["bottom"] + halo:
                continue
            outside = not (nx0 <= x < nx1 and ny0 <= y < ny1)
            cx = nx0 + r if x < nx0 + r else (nx1 - r if x >= nx1 - r else None)
            cy = ny0 + r if y < ny0 + r else (ny1 - r if y >= ny1 - r else None)
            # חצי פיקסל של החלקת קצוות על הקשת, כמו ב-``test_nothing_the_note_clipped_leaks_out_once_it_has_bubbles``.
            corner = cx is not None and cy is not None and ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 > r + 0.5
            if outside or corner:
                leaks.append((round(x, 1), round(y, 1)))
    assert not leaks, f"{len(leaks)} פיקסלים מחוץ לפתק השתנו, למשל {leaks[:5]}"


# ---------------------------------------------------------------------------
# פעולה, מקלדת וסגירה
# ---------------------------------------------------------------------------

def test_tapping_the_bell_on_a_phone_opens_the_reminder_window(browser):  # noqa: F811
    """בטלפון, במגע: ⋮ ← 🔔 פותח את חלון התזכורת, והתפריט נסגר."""
    np = NotePage(browser, [note("p", "תוכן", w=330, h=240, x=30, y=160)], viewport=PHONE, context_opts=PHONE_CONTEXT)
    try:
        np.page.tap(np.sel("p", ".sticky-note-more"))
        np.page.wait_for_selector(np.sel("p", ".sticky-note-menu"))
        assert_on_screen(np.page.evaluate(MENU_JS, "p"))
        np.page.tap(np.sel("p", '.sticky-note-menu-item[data-menu-item="reminder"]'))
        np.page.wait_for_selector(".sticky-reminder-modal")
        m = np.page.evaluate(MENU_JS, "p")
        assert m["menu"] is None and m["expanded"] == "false" and not m["unclipped"], m
        assert np.errors == [], np.errors
    finally:
        np.close()


KEY_SPY_JS = "() => { window.__docKeys = []; document.addEventListener('keydown', (e) => window.__docKeys.push(e.key)); }"


def test_keyboard_opens_moves_and_closes_and_keys_stay_in_the_menu(browser):  # noqa: F811
    """Enter על ⋮ פותח ומפקס את הפריט הראשון; Escape סוגר, מחזיר את הפוקוס ל-⋮, ואינו מגיע לעמוד."""
    np = NotePage(browser, [note("k", "תוכן", w=360, h=300, x=300, y=160)], viewport=DESKTOP)
    try:
        np.page.evaluate(KEY_SPY_JS)
        np.page.focus(np.sel("k", ".sticky-note-more"))
        np.page.keyboard.press("Enter")
        np.page.wait_for_selector(np.sel("k", ".sticky-note-menu"))
        assert np.page.evaluate(FOCUS_JS) == "sticky-note-menu-item"
        np.page.keyboard.press("ArrowDown")
        assert np.page.evaluate(FOCUS_JS) == "sticky-note-menu-item", "פריט אחד — ArrowDown חוזר אליו"
        np.page.keyboard.press("Escape")
        m = np.page.evaluate(MENU_JS, "k")
        assert m["menu"] is None and m["expanded"] == "false", m
        assert "sticky-note-more" in np.page.evaluate(FOCUS_JS)
        keys = np.page.evaluate("() => window.__docKeys")
        assert "Escape" not in keys and "ArrowDown" not in keys, f"מקשים מהתפריט הגיעו לעמוד: {keys}"
    finally:
        np.close()


#: מה מוקד עכשיו, ובתוך מה: ``inModal`` — בתוך חלון התזכורת; ``preset`` — ה-``data-preset`` שלו;
#: ``more`` — מזהה הפתק כשהמוקד הוא ⋮ שלו.
WHERE_FOCUS_JS = """() => { const a = document.activeElement;
  const note = a && a.closest ? a.closest('.sticky-note') : null;
  return { tag: a ? a.tagName : null,
           inModal: !!(a && a.closest && a.closest('.sticky-reminder-modal')),
           preset: a && a.getAttribute ? a.getAttribute('data-preset') : null,
           more: a && a.classList && a.classList.contains('sticky-note-more') && note ? note.dataset.noteId : null }; }"""


@pytest.mark.parametrize("how", ["close-button", "backdrop"])
def test_choosing_the_bell_moves_focus_into_the_reminder_window_and_back_to_more(browser, how):  # noqa: F811
    """מהמקלדת: ⋮ ← Enter ← Enter על 🔔 — המיקוד עובר לכפתור הקיצור הראשון בחלון, ובסגירה חוזר ל-⋮.

    הפריט שנלחץ יורד מה-DOM יחד עם התפריט, ולכן בלי מיקוד מפורש בחלון המיקוד נפל ל-``body`` —
    משתמש מקלדת היה ממשיך מראש העמוד, מאחורי החלון. ובסגירה, כשהחלון יורד, אותו דבר.
    """
    np = NotePage(browser, [note("r", "תוכן", w=360, h=300, x=300, y=160)], viewport=DESKTOP)
    try:
        np.page.focus(np.sel("r", ".sticky-note-more"))
        np.page.keyboard.press("Enter")
        np.page.wait_for_selector(np.sel("r", ".sticky-note-menu"))
        np.page.keyboard.press("Enter")
        np.page.wait_for_selector(".sticky-reminder-modal")
        f = np.page.evaluate(WHERE_FOCUS_JS)
        assert f["inModal"] and f["preset"] == "1h", f"המיקוד אמור להיות על הקיצור הראשון בחלון: {f}"
        if how == "close-button":
            np.page.click(".sticky-reminder-close")
        else:
            np.page.mouse.click(5, 5)
        assert np.page.evaluate("() => document.querySelector('.sticky-reminder-modal')") is None
        f = np.page.evaluate(WHERE_FOCUS_JS)
        assert f["more"] == "r", f"בסגירה המיקוד אמור לחזור ל-⋮ של הפתק: {f}"
        assert np.errors == [], np.errors
    finally:
        np.close()


def test_a_reminder_window_that_is_already_open_takes_the_focus(browser):  # noqa: F811
    """חלון שכבר פתוח אינו נפתח שוב — והמיקוד עובר לכפתור הקיצור הראשון בו, ולא נשאר במקום אחר.

    עד התיקון הענף הזה קרא ``focus`` על החלון עצמו, ``div`` בלי ``tabindex`` — והמיקוד לא זז.
    """
    np = NotePage(browser, [note("r", "תוכן", w=360, h=300, x=300, y=160)], viewport=DESKTOP)
    try:
        np.page.evaluate("() => window.__mgr._openReminderModal(document.querySelector('.sticky-note[data-note-id=\"r\"]'))")
        np.page.wait_for_selector(".sticky-reminder-modal")
        np.page.focus(".sr-save")
        assert np.page.evaluate(WHERE_FOCUS_JS)["preset"] is None, "בקרה: המיקוד הוזז אל מחוץ לקיצורים"
        np.page.evaluate("() => window.__mgr._openReminderModal(document.querySelector('.sticky-note[data-note-id=\"r\"]'))")
        assert np.page.evaluate("() => document.querySelectorAll('.sticky-reminder-modal').length") == 1
        f = np.page.evaluate(WHERE_FOCUS_JS)
        assert f["inModal"] and f["preset"] == "1h", f"המיקוד אמור לעבור לקיצור הראשון בחלון הקיים: {f}"
    finally:
        np.close()


def test_a_click_outside_closes_the_menu(browser):  # noqa: F811
    np = NotePage(browser, [note("o", "תוכן", w=360, h=300, x=300, y=160)], viewport=DESKTOP)
    try:
        open_menu(np, "o")
        np.page.mouse.click(1100, 700)
        m = np.page.evaluate(MENU_JS, "o")
        assert m["menu"] is None and m["expanded"] == "false" and not m["unclipped"], m
    finally:
        np.close()


# ---------------------------------------------------------------------------
# פתק צר
# ---------------------------------------------------------------------------

#: אילו כפתורים בשורה חוצים את קצה הפתק — בנוסחה של ``ROW_JS`` ב-``tests/test_sticky_note_copy_id_browser.py``.
CLIPPED_JS = """(nid) => {
  const n = document.querySelector(`.sticky-note[data-note-id="${nid}"]`);
  const cs = getComputedStyle(n);
  const r = n.getBoundingClientRect();
  const left = r.left + parseFloat(cs.borderLeftWidth), right = r.right - parseFloat(cs.borderRightWidth);
  const row = [...n.querySelector('.sticky-note-actions').children];
  return { row: row.map((b) => b.textContent.trim()),
           clipped: row.filter((b) => { const br = b.getBoundingClientRect();
             return br.left < left - 0.5 || br.right > right + 0.5; }).map((b) => b.textContent.trim()) };
}"""


def test_in_a_narrow_note_the_more_button_is_cut_first(browser):  # noqa: F811
    """פתק צר חותך את סוף השורה (#3478), ו-⋮ הוא הראשון שנחתך — הכרעה של המשתמש: מה שבתוכו
    הוא מה שאפשר לוותר עליו. מה שנחתך הוא תמיד סיפא של השורה, ו-⋮ בתוכה."""
    np = NotePage(browser, [note("n", "תוכן", w=240, h=200, x=300, y=160)], viewport=DESKTOP)
    try:
        r = np.page.evaluate(CLIPPED_JS, "n")
        assert r["clipped"], f"בקרה: ברוחב 240 השורה אמורה להיחתך — {r}"
        assert r["row"][-len(r["clipped"]):] == r["clipped"] and r["clipped"][-1] == "⋮", r
    finally:
        np.close()
