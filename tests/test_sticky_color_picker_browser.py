"""בורר הצבע של הפתק — בכרומיום אמיתי, בדגימת פיקסלים, על כל צבע בפלטה.

**למה דפדפן.** המבנה של הבורר — עיגול לכל צבע, בסדר הפלטה, והצבע ב-``style`` של העיגול —
ננעל ב-``tests/sticky-notes-target.test.js``, ב-node. כאן מה שרק דפדפן עונה עליו: מה מצויר
בפועל. הגבול של העיגול (``border`` של ``.sticky-color-swatch`` ב-``sticky-notes.css``) הוא דיו
שקופה בחלקה מעל הצבע עצמו, ולכן הגוון שלו נקבע בהרכבה של הדפדפן, ושום שורה בקוד אינה מחזיקה אותו.

**על כל צבע ב-``NOTE_COLOR_ORDER``, ולא על רשימה מוקלדת.** הסעיף "הצבעים והמדידה" בעמוד השרת
(``docs/dev/sticky_notes_extending_backend.rst``) קובע שלושה מספרים שכל צבע בפלטה צריך לעמוד
בהם, ועד שהבדיקה הזו נכתבה הם נמדדו ביד בכל פעם שנוסף צבע. צבע שיתווסף לפלטה נכנס לכאן מאליו.
הבדיקה אוכפת ספים — ולא את המספרים עצמם, שמתועדים שם.

**העמוד.** העמוד הסינתטי של ``tests/test_sticky_note_search_browser.py`` — ה-CSS וה-JS מהדיסק,
ו-``fetch`` מדומה. הבורר נפתח מכפתור ה-🎨 של הפתק, כמו אצל המשתמש.

מדולג כשאין Chromium.
"""

from __future__ import annotations

import pytest

from sticky_notes_target import NOTE_COLORS

pytest.importorskip("playwright", reason="playwright אינו מותקן")

# **העזרים והפיקסצ'רים של העמוד הסינתטי, ולא עותק שלהם** — כמו ב-
# ``tests/test_sticky_note_menu_browser.py``. ``browser`` ו-``playwright_instance`` הם פיקסצ'רים
# של מודול, ונרשמים כאן מחדש למודול הזה, עם דפדפן משלו. הם מגיעים לשער (``chromium_executable``)
# דרך ``browser``. גם הדגימה (``_pixels``, ``_mode``, ``_darkest``) והניגודיות (``_contrast``)
# משם, כדי ששתי המדידות של הנייר יימדדו באותה שיטה בדיוק.
from test_sticky_note_search_browser import (  # noqa: E402,F401
    PAPERS, NotePage, _contrast, _darkest, _mode, _pixels, browser, note, playwright_instance,
)

#: הסף לטקסט: WCAG AAA. הוא שמתיר לתווית לשבת **על** הצבע, בלי רצועה משלה.
TEXT_MIN = 7
#: הסף לגבול ולטבעת: WCAG 1.4.11, רכיבי ממשק.
UI_MIN = 3

#: המלבנים של הבורר, ומה הדפדפן מוצא במרכז העיגול המסומן — כלומר מה מצויר שם בפועל.
PICKER_JS = """() => {
  const box = (e) => { const r = e.getBoundingClientRect();
    return { left: r.left, top: r.top, right: r.right, bottom: r.bottom }; };
  const swatches = [...document.querySelectorAll('.sticky-color-swatch')];
  const active = swatches.find((s) => s.getAttribute('aria-pressed') === 'true');
  if (!active) return { ids: swatches.map((s) => s.getAttribute('data-color-id')), active: null };
  const a = box(active);
  const hit = document.elementFromPoint((a.left + a.right) / 2, (a.top + a.bottom) / 2);
  const card = document.querySelector('.sticky-color-card');
  return { ids: swatches.map((s) => s.getAttribute('data-color-id')),
           active: active.getAttribute('data-color-id'), swatch: a,
           label: box(active.querySelector('.sticky-color-label')),
           card: box(card), cardPadding: parseFloat(getComputedStyle(card).paddingLeft),
           cardBg: getComputedStyle(card).backgroundColor,
           hitIsSwatch: !!hit && hit.closest('.sticky-color-swatch') === active };
}"""


def _hex_rgb(value):
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def _css_rgb(value):
    """``rgb(r, g, b)`` כפי ש-``getComputedStyle`` מחזיר צבע אטום."""
    return tuple(int(part) for part in value[value.index("(") + 1:value.index(")")].split(","))


@pytest.mark.parametrize("paper", PAPERS)
def test_every_palette_colour_is_readable_in_the_picker(browser, paper):  # noqa: F811
    """הטקסט על העיגול, הגבול שלו לשני הכיוונים, וטבעת הבחירה — בדגימת פיקסל.

    **הגבול נמדד לשני הכיוונים**, כי הוא פס שיושב חציו על העיגול וחציו על הכרטיס. מול הכרטיס
    הוא נחלש ככל שהצבע בהיר יותר: 30% ממנו הם הצבע עצמו. לכן צבע בהיר מהקיימים מוריד את המקרה
    הגרוע, וזה בדיוק מה שהבדיקה הזו תופסת בלי שמישהו יזכור למדוד.
    """
    np = NotePage(browser, [note("n", "פתק", w=300, color=paper)],
                  viewport=(480, 900), context_opts={"device_scale_factor": 2})
    np.page.click(np.sel("n", ".sticky-note-color"))
    np.page.wait_for_selector(".sticky-color-swatch")
    # העכבר נשאר על 🎨, ובמודאל שנפתח מעליו הוא עלול לרחף מעל עיגול ולהוסיף לו צל.
    np.page.mouse.move(1, 1)
    info = np.page.evaluate(PICKER_JS)
    assert info["ids"] == list(PAPERS), "עיגול לכל צבע, בסדר הפלטה"
    assert info["active"] == paper, "העיגול של צבע הפתק מסומן"
    assert info["hitIsSwatch"], "במרכז העיגול המסומן מצויר העיגול עצמו"
    s, card, label = info["swatch"], info["card"], info["label"]
    im = _pixels(np.page)
    # התווית יושבת בתחתית העיגול (``align-items: flex-end``), ולכן הצבע נדגם בחלקו העליון.
    inside = _mode(im, (s["left"] + 10, s["top"] + 6, s["right"] - 10, s["top"] + 18), 2)
    border = _mode(im, (s["left"] + 20, s["top"], s["right"] - 20, s["top"] + 1), 2)
    ring = _mode(im, (s["left"] + 20, s["top"] - 2.5, s["right"] - 20, s["top"] - 1), 2)
    text = _darkest(im, (label["left"], label["top"], label["right"], label["bottom"]), 2)
    # הריפוד של הכרטיס, בגובה העיגול — מחוץ לפינה המעוגלת ומחוץ לרשת. נדגם בחציו הפנימי בלבד,
    # כדי שלא ייגע בגבול הכרטיס ולא ברשת.
    pad = info["cardPadding"]
    mid = (s["top"] + s["bottom"]) / 2
    card_px = _mode(im, (card["left"] + pad * 0.25, mid - 3, card["left"] + pad * 0.75, mid + 3), 2)
    np.close()
    # בקרות שפיות: נדגם הצבע עצמו, נדגם הכרטיס עצמו, והגבול הוא פס נפרד משניהם. בלעדיהן מדידה
    # של האזור הלא נכון הייתה עוברת או נכשלת מהסיבה הלא נכונה.
    assert inside == _hex_rgb(NOTE_COLORS[paper]["hex"]), inside
    assert card_px == _css_rgb(info["cardBg"]), (card_px, info["cardBg"])
    assert border not in (inside, card_px), border

    assert _contrast(text, inside) >= TEXT_MIN, (text, inside)
    assert _contrast(border, inside) >= UI_MIN, (border, inside)
    assert _contrast(border, card_px) >= UI_MIN, (border, card_px)
    assert _contrast(ring, inside) >= UI_MIN, (ring, inside)
