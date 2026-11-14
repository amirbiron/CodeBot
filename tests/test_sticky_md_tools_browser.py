"""כלי MD בתפריט ⋮ של הפתק — בכרומיום אמיתי, דרך הממשק.

**למה דפדפן.** המבנה, החיווט וההזרקה עצמה (טקסט נכנס, טקסט יוצא) ננעלים ב-``tests/sticky-notes-target.test.js``,
ב-node. כאן מה שרק דפדפן עונה עליו:

- **אחרי ההזרקה** המיקוד באמת ב-textarea והטקסט למילוי באמת מסומן — גם בפתק שהציג את התצוגה המרונדרת, גם
  במגע — **הדבקה** מחליפה את המסומן, ו**ביטול אחד** מחזיר את מה שהיה לפני ההזרקה.
- **לאן החלונית נפתחת**: מעל הפתק כשיש שם מקום, בצד או מתחתיו כשאין, ועל הפתק רק כשאין מקום באף צד — ותמיד
  בתוך המסך. בשתי הפריסות, RTL ו-LTR, כי החשבון במלבנים שנמדדו (``rtl-geometry-and-clamp`` ב-
  ``amir-bug-patterns``).
- **האייקון בתפריט** נטען, ונראה בגודל של האימוג'ים שלידו — נמדד בגודל הדיו, בפיקסלים.

**העמוד.** העמוד הסינתטי של ``tests/test_sticky_note_search_browser.py`` — ה-CSS וה-JS מהדיסק, ו-``fetch`` מדומה.
מקור ``localhost``, כי שם ``navigator.clipboard`` קיים (הקשר מאובטח), כמו בייצור.

**מה לא נבדק כאן:** טאבלט או טלפון אמיתיים — המגע כאן הוא אמולציה של כרומיום (``is_mobile``, ``has_touch``),
ולכן גם פתיחת המקלדת אחרי המיקוד אינה נמדדת. וגופן אימוג'י אחר (אפל, סמסונג) מצייר מעט אחרת מ-Noto.

מדולג כשאין Chromium.
"""

from __future__ import annotations

import io

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

# **העזרים והפיקסצ'רים של העמוד הסינתטי, ולא עותק שלהם** — כמו ב-``tests/test_sticky_note_menu_browser.py``.
from test_sticky_note_search_browser import NotePage, browser, note, playwright_instance  # noqa: E402,F401

DESKTOP = (1280, 800)
TABLET_CONTEXT = {"is_mobile": True, "has_touch": True}
ORIGIN = "http://localhost"

#: ``NOTE_EDGE_GAP`` ב-``sticky-notes.js`` — השוליים מקצה המסך. כאן כדי שהבדיקה תדע מה לצפות.
EDGE_GAP = 12

#: מצב ה-textarea של הפתק: מה מסומן, האם הוא במיקוד, האם הוא מוסתר, והגלילה הפנימית שלו.
TEXTAREA_JS = """(nid) => {
  const t = document.querySelector(`.sticky-note[data-note-id="${nid}"] .sticky-note-content`);
  return { value: t.value, selected: t.value.slice(t.selectionStart, t.selectionEnd),
           start: t.selectionStart, end: t.selectionEnd, active: document.activeElement === t, hidden: t.hidden,
           scrollTop: t.scrollTop, scrollHeight: t.scrollHeight, clientHeight: t.clientHeight };
}"""

#: המלבנים של הפתק ושל החלונית, כמה שורות ברשת, האם יש גלילה, ומה מצויר במרכז הכפתור הראשון.
PANEL_JS = """(nid) => {
  const n = document.querySelector(`.sticky-note[data-note-id="${nid}"]`);
  const p = n.querySelector('.sticky-md-tools');
  const box = (e) => { const r = e.getBoundingClientRect();
    return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height }; };
  const out = { note: box(n), vw: document.documentElement.clientWidth, vh: window.innerHeight, panel: null };
  if (!p) return out;
  const cells = [...p.querySelectorAll('.sticky-md-tool')];
  const first = cells[0].getBoundingClientRect();
  const hit = document.elementFromPoint(first.left + first.width / 2, first.top + first.height / 2);
  out.panel = box(p);
  out.rows = new Set(cells.map((c) => Math.round(c.getBoundingClientRect().top))).size;
  out.cells = cells.length;
  out.scrolls = p.scrollHeight > p.clientHeight || p.scrollWidth > p.clientWidth;
  out.hitsFirst = hit === cells[0] || cells[0].contains(hit);
  return out;
}"""


def open_tools(np, nid, tap=False):
    """⋮ ← "כלי MD", כמו המשתמש. מחזיר את הגאומטריה של החלונית."""
    press = np.page.tap if tap else np.page.click
    press(np.sel(nid, ".sticky-note-more"))
    press(np.sel(nid, '[data-menu-item="md-tools"]'))
    np.page.wait_for_selector(np.sel(nid, ".sticky-md-tools"))
    return np.page.evaluate(PANEL_JS, nid)


def assert_on_screen(g):
    p = g["panel"]
    assert p["left"] >= EDGE_GAP - 0.5 and p["right"] <= g["vw"] - EDGE_GAP + 0.5, g
    assert p["top"] >= EDGE_GAP - 0.5 and p["bottom"] <= g["vh"] - EDGE_GAP + 0.5, g
    assert g["hitsFirst"], f"הכפתור הראשון אינו מצויר למעלה — משהו אחר מכסה אותו: {g}"


def overlaps(a, b) -> bool:
    return a["left"] < b["right"] and b["left"] < a["right"] and a["top"] < b["bottom"] and b["top"] < a["bottom"]


# ---------------------------------------------------------------------------
# ההזרקה, הסימון, ההדבקה והביטול
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("device", ["desktop", "tablet"])
def test_injecting_a_link_selects_the_url_paste_fills_it_and_each_undo_is_one_step(browser, device):  # noqa: F811
    """הסמן באמצע שורה ← קישור: ``https://`` מסומן בתוך הסוגריים, הדבקה נכנסת בדיוק שם, ביטול אחד מוריד את
    ההדבקה, וביטול שני מחזיר את התוכן שלפני ההזרקה — ההזרקה היא צעד אחד בדיוק."""
    tap = device == "tablet"
    np = NotePage(browser, [note("a", "אבג דהו", w=360, h=260, x=420, y=330)], viewport=DESKTOP,
                  context_opts=TABLET_CONTEXT if tap else None, origin=ORIGIN)
    try:
        page = np.page
        (page.tap if tap else page.click)(np.sel("a", ".sticky-note-content"))
        page.evaluate("""() => document.querySelector('.sticky-note[data-note-id="a"] .sticky-note-content')
            .setSelectionRange(4, 4)""")
        open_tools(np, "a", tap=tap)
        (page.tap if tap else page.click)(np.sel("a", '[data-md-tool="link"]'))
        t = page.evaluate(TEXTAREA_JS, "a")
        assert page.query_selector(np.sel("a", ".sticky-md-tools")) is None, "החלונית נסגרה"
        assert t["value"] == "אבג [טקסט הקישור](https://)דהו", t
        assert t["active"], f"המיקוד חזר ל-textarea: {t}"
        assert t["selected"] == "https://", f"מסומן https:// שבתוך הסוגריים: {t}"

        page.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=ORIGIN)
        page.evaluate("() => navigator.clipboard.writeText('https://example.com/x')")
        page.keyboard.press("Control+V")
        t = page.evaluate(TEXTAREA_JS, "a")
        assert t["value"] == "אבג [טקסט הקישור](https://example.com/x)דהו", f"ההדבקה החליפה את המסומן: {t}"

        undo = np.sel("a", ".sticky-note-undo")
        page.click(undo)
        assert page.evaluate(TEXTAREA_JS, "a")["value"] == "אבג [טקסט הקישור](https://)דהו", "ביטול אחד — בלי ההדבקה"
        page.click(undo)
        assert page.evaluate(TEXTAREA_JS, "a")["value"] == "אבג דהו", "ביטול שני — התוכן שלפני ההזרקה"
        assert np.errors == [], np.errors
    finally:
        np.ctx.close()


#: מה ש"השרת" המדומה שמר לפתק — מה שהגיע אליו בבקשת השמירה, ולא מה שעומד בתור (``FETCH_STUB``).
SAVED_JS = "(nid) => window.__contents[nid]"


def wait_saved(np, nid, expected):
    """מחכה שהשמירה תגיע לשרת המדומה עם התוכן הזה. **קריאה חוזרת של המצב** — לא התור של הלקוח."""
    np.page.wait_for_function("([nid, want]) => window.__contents[nid] === want", arg=[nid, expected], timeout=10000)
    return np.page.evaluate(SAVED_JS, nid)


def test_injecting_reaches_the_server_and_one_undo_restores_the_note(browser):  # noqa: F811
    """הזרקה: התוכן החדש מגיע לשרת בבקשת השמירה. ומיד ביטול: ביטול אחד מחזיר את התוכן שלפני ההזרקה, וגם
    הוא נשמר."""
    np = NotePage(browser, [note("a", "שורה", w=360, h=260, x=420, y=330)], viewport=DESKTOP)
    try:
        open_tools(np, "a")
        np.page.click(np.sel("a", '[data-md-tool="alert-warning"]'))
        t = np.page.evaluate(TEXTAREA_JS, "a")
        injected = "שורה\n::: warning\nתוכן ההתראה\n:::"
        assert t["value"] == injected, f"פתק שלא קיבל מיקוד — בסוף התוכן: {t}"
        assert t["selected"] == "תוכן ההתראה", t
        assert wait_saved(np, "a", injected) == injected
        np.page.click(np.sel("a", ".sticky-note-undo"))
        assert np.page.evaluate(TEXTAREA_JS, "a")["value"] == "שורה"
        assert wait_saved(np, "a", "שורה") == "שורה"
    finally:
        np.ctx.close()


@pytest.mark.parametrize("device", ["desktop", "tablet"])
def test_a_rendered_note_goes_to_edit_with_the_fill_selected_and_visible(browser, device):  # noqa: F811
    """פתק מרונדר שמעולם לא קיבל מיקוד — ה-textarea מוסתר מאחורי התצוגה. בלוק מתקפל: הוא מוזרק בסוף, ה-textarea
    מוצג ובמיקוד, ``כותרת`` מסומנת, והגלילה הפנימית מגיעה אליה — הפתק ארוך מהתיבה."""
    tap = device == "tablet"
    content = "# כותרת ראשית\n" + "\n".join(f"שורה מספר {i}" for i in range(60))
    np = NotePage(browser, [note("a", content, w=360, h=240, x=420, y=330)], viewport=DESKTOP,
                  context_opts=TABLET_CONTEXT if tap else None)
    try:
        before = np.page.evaluate(TEXTAREA_JS, "a")
        assert before["hidden"], f"בקרה: הפתק מציג את התצוגה, וה-textarea מוסתר: {before}"
        open_tools(np, "a", tap=tap)
        (np.page.tap if tap else np.page.click)(np.sel("a", '[data-md-tool="details"]'))
        t = np.page.evaluate(TEXTAREA_JS, "a")
        assert t["value"] == content + "\n::: details כותרת\nתוכן\n:::", "בסוף התוכן, בשורה משלו"
        assert not t["hidden"] and t["active"], f"ה-textarea מוצג ובמיקוד: {t}"
        assert t["selected"] == "כותרת", t
        assert t["scrollTop"] + t["clientHeight"] >= t["scrollHeight"] - 1, f"הגלילה הגיעה לסוף, אל המסומן: {t}"
    finally:
        np.ctx.close()


# ---------------------------------------------------------------------------
# לאן החלונית נפתחת
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("direction", ["rtl", "ltr"])
def test_with_room_above_the_panel_opens_above_the_note(browser, direction):  # noqa: F811
    """מקום מעל הפתק: החלונית שם — לא מכסה אותו — כל הכפתורים בשלוש שורות, בלי גלילה."""
    np = NotePage(browser, [note("a", "תוכן", w=380, h=260, x=420, y=330)], viewport=DESKTOP)
    try:
        np.page.evaluate("(d) => { document.documentElement.dir = d; }", direction)
        g = open_tools(np, "a")
        assert g["panel"]["bottom"] <= g["note"]["top"], f"מעל הפתק: {g}"
        assert not overlaps(g["panel"], g["note"]), g
        assert g["rows"] == 3 and not g["scrolls"], f"שלוש שורות, בלי גלילה: {g}"
        assert_on_screen(g)
    finally:
        np.ctx.close()


@pytest.mark.parametrize("direction", ["rtl", "ltr"])
def test_a_note_at_the_top_of_the_screen_gets_the_panel_beside_or_below_not_above(browser, direction):  # noqa: F811
    """פתק בראש המסך: אין מקום מעליו, ולכן החלונית בצד או מתחתיו — לא מעליו ולא עליו — ובתוך המסך."""
    np = NotePage(browser, [note("a", "תוכן", w=380, h=260, x=420, y=24)], viewport=DESKTOP)
    try:
        np.page.evaluate("(d) => { document.documentElement.dir = d; }", direction)
        g = open_tools(np, "a")
        p, n = g["panel"], g["note"]
        assert p["top"] >= n["bottom"] or p["right"] <= n["left"] or p["left"] >= n["right"], \
            f"בצד או מתחת, ולא מעל: {g}"
        assert not overlaps(p, n), f"אינה מכסה את הפתק: {g}"
        assert not g["scrolls"], g
        assert_on_screen(g)
    finally:
        np.ctx.close()


@pytest.mark.parametrize("direction", ["rtl", "ltr"])
def test_when_only_one_side_has_room_the_panel_opens_there(browser, direction):  # noqa: F811
    """פתק גבוה ליד הקצה השמאלי של מסך רחב ונמוך: אין מקום מעליו, מתחתיו או משמאלו — רק מימינו. החלונית שם."""
    np = NotePage(browser, [note("a", "תוכן", w=300, h=470, x=40, y=60)], viewport=(1600, 600))
    try:
        np.page.evaluate("(d) => { document.documentElement.dir = d; }", direction)
        g = open_tools(np, "a")
        assert g["panel"]["left"] >= g["note"]["right"], f"מימין לפתק: {g}"
        assert not g["scrolls"], g
        assert_on_screen(g)
    finally:
        np.ctx.close()


def test_with_no_room_anywhere_the_panel_sits_on_the_note_inside_the_screen(browser):  # noqa: F811
    """טלפון, ופתק שתופס את כל המסך: אין מקום באף צד, והחלונית על הפתק — הרוחב מצומצם קודם, והיא בתוך המסך.

    **בשום צד אין אפילו פיקסל** (הפתק חורג מכל השוליים), ולכן אף ניסיון של צד לא כתב רוחב — זה המקרה שבו רק
    הצמצום של המוצא האחרון מחזיק את החלונית בתוך המסך."""
    np = NotePage(browser, [note("a", "תוכן", w=380, h=840, x=5, y=2)], viewport=(390, 844),
                  context_opts=TABLET_CONTEXT)
    try:
        # הבקרה נמדדת **לפני** הפתיחה: חלונית שחורגת מהמסך מזיזה את אזור התצוגה במגע, ואז גם הפתק נמדד אחרת.
        n = np.rect(np.sel("a"))
        assert n["top"] < EDGE_GAP and n["left"] < EDGE_GAP and n["right"] > 390 - EDGE_GAP \
            and n["bottom"] > 844 - EDGE_GAP, f"בקרה: הפתק חורג מהשוליים בכל צד: {n}"
        g = open_tools(np, "a", tap=True)
        assert overlaps(g["panel"], g["note"]), f"מוצא אחרון — על הפתק: {g}"
        assert g["panel"]["width"] <= g["vw"] - 2 * EDGE_GAP + 0.5, f"הרוחב צומצם קודם (H7): {g}"
        assert_on_screen(g)
    finally:
        np.ctx.close()


# ---------------------------------------------------------------------------
# האייקון בתפריט
# ---------------------------------------------------------------------------

def _ink(png: bytes):
    """רוחב וגובה של מה שצויר — הפיקסלים ששונים מהרקע — בפיקסלים של המכשיר."""
    from PIL import Image  # מוצמד ב-requirements/base.txt

    img = Image.open(io.BytesIO(png)).convert("RGB")
    bg = img.getpixel((1, 1))
    px = img.load()
    xs, ys = [], []
    for y in range(img.height):
        for x in range(img.width):
            if sum(abs(px[x, y][i] - bg[i]) for i in range(3)) > 40:
                xs.append(x)
                ys.append(y)
    return (max(xs) - min(xs) + 1, max(ys) - min(ys) + 1) if xs else (0, 0)


def test_the_icon_file_looks_the_size_of_the_emoji_beside_it(browser):  # noqa: F811
    """האייקון של "כלי MD" נטען, וגודל הדיו שלו כגודל הדיו של 🔔 שלידו — בפחות מפיקסל, ב-4 פיקסלים למכשיר לכל
    פיקסל של CSS. גודל הקופסה אינו המדד: באימוג'י ובציור יש שוליים שקופים שונים."""
    scale = 4
    np = NotePage(browser, [note("a", "תוכן", w=400, h=300, x=300, y=200)], viewport=DESKTOP,
                  context_opts={"device_scale_factor": scale})
    try:
        page = np.page
        page.click(np.sel("a", ".sticky-note-more"))
        page.wait_for_function("""() => { const i = document.querySelector('.sticky-note-menu-icon');
            return !!i && i.complete && i.naturalWidth > 0; }""")
        # בלי מיקוד ובלי ריחוף — שום רקע של מצב לא נכנס לצילום.
        page.evaluate("() => document.activeElement && document.activeElement.blur()")
        page.mouse.move(2, 2)
        shot = lambda item: page.locator(np.sel("a", f'[data-menu-item="{item}"]')).screenshot()  # noqa: E731
        icon = [v / scale for v in _ink(shot("md-tools"))]
        bell = [v / scale for v in _ink(shot("reminder"))]
        assert icon[0] > 0 and bell[0] > 0, (icon, bell)
        assert abs(icon[0] - bell[0]) < 1 and abs(icon[1] - bell[1]) < 1, f"כלי MD {icon} מול 🔔 {bell}"
    finally:
        np.ctx.close()
