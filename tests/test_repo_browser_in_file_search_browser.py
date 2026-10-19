"""החיפוש בתוך קובץ בתצוגה המרונדרת של דפדפן הריפו — בכרומיום אמיתי, מול הוובאפ האמיתי.

**מה נבדק.** בתצוגה המרונדרת (קובץ Markdown, ועמוד rst מאתר התיעוד) החיפוש עובר על מה שמוצג, ולא על
המקור: הספירה היא של מה שמוצג, כל ההתאמות מודגשות והפעילה בולטת, הבא/הקודם גוללים אליה — את התצוגה,
ולא את העמוד — מעבר בין התצוגות עם חיפוש פתוח מחפש מחדש בתצוגה החדשה, וסגירה מנקה את ההדגשות.

**למה בדפדפן.** כל השאלות כאן הן של הדפדפן: מה הרינדור מציג (קישור מציג את הטקסט ולא את הכתובת),
מה נגלל כש-``scrollIntoView`` רץ (גם העמוד, נמדד), והאם ההתאמה הפעילה באמת על המסך
(``elementFromPoint`` במרכז שלה). כל פעולה עוברת דרך הממשק: הקלדה בתיבה, הכפתורים שבסרגל, המקשים,
וכפתור התצוגה.

השרת, המסד, המראה והעמוד — ``_repo_browser_harness.py``. הדפדפן מורם כאן, בפיקסצ'ר ``browser``.

מדולג כשאין Chromium (וב-CI אין: ראו ``docs/testing.rst``), וכשאין git.
"""

from __future__ import annotations

import pytest

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import poll
from _docs_index_harness import page, section
from _git_mirror_harness import GIT
from _repo_browser_harness import REPO, mirror_world, open_file, repo_page

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

pytestmark = pytest.mark.skipif(GIT is None, reason="git is not installed")

MD = "docs/guide.md"
RST = "docs/webapp/code-browser.rst"
TERM = "lantern"

#: הקובץ, כך שהתצוגה והמקור נבדלים בספירה, ושההתאמות מפוזרות במקומות שצריך לגלול אליהם: כותרת, פסקה
#: עם אותה מילה ברישיות אחרות, קישור שהמילה רק בכתובת שלו (במקור — כן; בתצוגה — לא), עשרות פסקאות
#: מילוי, שורת קוד ארוכה משמאל לימין ושורת קוד ארוכה בעברית (שתיהן נגללות לרוחב, כל אחת לכיוון שלה),
#: טבלה, ופסקה אחרונה.
MD_TEXT = (
    "# Lantern guide\n\n"
    "A lantern in a paragraph, and LANTERN again.\n\n"
    "[המדריך](https://example.com/lantern)\n\n"
    + "\n\n".join(f"פסקת מילוי מספר {i}, בלי המילה." for i in range(60))
    + "\n\n```python\nvalue = 1  # " + "a" * 300 + " lantern\n```\n\n"
    + "```\n" + "שורה ארוכה בעברית " * 30 + "lantern\n```\n\n"
    "| שם | ערך |\n| --- | --- |\n| lantern | 2 |\n\n"
    "הפסקה האחרונה, עם lantern.\n"
)
SHOWN = 7
IN_SOURCE = 8

RST_SOURCE = "דפדפן קוד\n=========\n"


def _pages():
    """עמוד rst שבו ``initial_import`` מופיע פעמיים, בקוד בשורה ובבלוק קוד — ובמקור של קובץ ה-rst אינו מופיע."""
    return [
        page(
            "webapp/code-browser.html", RST,
            section("code-browser", "דפדפן קוד", markdown="ייבוא ריפו לדפדפן הקוד, עם `initial_import`."),
            section(
                "import", "דפדפן קוד", "ייבוא ריפו חדש", title_markdown="ייבוא ריפו חדש",
                markdown="יש להריץ את הפקודה:\n\n```python\nres = initial_import(\"url\", \"שם\", get_db())\n```",
            ),
        ),
    ]


@pytest.fixture
def world(tmp_path, monkeypatch):
    return mirror_world(tmp_path, monkeypatch, {MD: MD_TEXT, RST: RST_SOURCE}, _pages())


@pytest.fixture(scope="module")
def browser(chromium_executable):
    """הדפדפן של הקובץ — **המקום היחיד שמרים דפדפן כאן**. ההרמה נשארת בקובצי ``*_browser.py``
    (``tests/test_browser_suite_is_gated_once.py``), ו-``repo_page`` מקימה בו context לכל בדיקה."""
    with sync_playwright() as pw:
        try:
            launched = pw.chromium.launch(executable_path=chromium_executable)
        except PlaywrightError as exc:  # pragma: no cover - תלוי בסביבה
            pytest.skip(f"אין Chromium זמין: {exc}")
        try:
            yield launched
        finally:
            launched.close()


_RENDERED = "() => !!document.querySelector('#markdown-preview-content h1')"

#: מה שהחיפוש מציג עכשיו: המונה, ההתאמות בתצוגה המרונדרת, ואיזו מהן פעילה.
_STATE = """
() => {
  const hits = Array.from(document.querySelectorAll('#markdown-preview-content .in-file-search-hit'));
  return {
    count: document.getElementById('in-file-search-count').textContent,
    hits: hits.length,
    active: hits.map((h, i) => h.classList.contains('is-active') ? i : -1).filter((i) => i >= 0),
  };
}
"""

#: האם ההתאמה הפעילה באמת על המסך, ומה נגלל. ``elementFromPoint`` במרכז ההתאמה מחזיר אותה רק כשהיא
#: לא חתוכה בשום מכל — לא מעל או מתחת לתצוגה, ולא מחוץ לחלון של בלוק קוד שנגלל לרוחב. ``scroller`` הוא
#: המכל הקרוב שנגלל לרוחב, אם יש.
_ACTIVE_ON_SCREEN = """
() => {
  const hit = document.querySelector('#markdown-preview-content .in-file-search-hit.is-active');
  if (!hit) return {ok: false, why: 'אין התאמה פעילה'};
  const r = hit.getBoundingClientRect();
  const at = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  let scroller = null;
  for (let b = hit.parentElement; b && b.id !== 'markdown-preview-container'; b = b.parentElement) {
    if (b.scrollWidth > b.clientWidth && getComputedStyle(b).overflowX !== 'visible') { scroller = b; break; }
  }
  const container = document.getElementById('markdown-preview-container');
  return {
    ok: !!at && (at === hit || hit.contains(at)),
    count: document.getElementById('in-file-search-count').textContent,
    containerTop: container.scrollTop,
    page: [document.body.scrollTop, document.documentElement.scrollTop, window.scrollY],
    scrollLeft: scroller ? scroller.scrollLeft : null,
    direction: scroller ? getComputedStyle(scroller).direction : null,
  };
}
"""


#: הצבעים, כפי שהדפדפן מחשב אותם מ-``repo-browser.css``: כל ההתאמות בצהוב, והפעילה בכתום עם טבעת שחורה
#: והילה לבנה.
_COLORS = """
() => {
  const bg = (h) => getComputedStyle(h).backgroundColor;
  const hits = Array.from(document.querySelectorAll('#markdown-preview-content .in-file-search-hit'));
  const others = Array.from(new Set(hits.filter((h) => !h.classList.contains('is-active')).map(bg)));
  const active = hits.filter((h) => h.classList.contains('is-active'));
  const cs = active.length === 1 ? getComputedStyle(active[0]) : null;
  return {
    ok: others.length === 1 && others[0] === 'rgb(255, 235, 59)' && !!cs
        && cs.backgroundColor === 'rgb(255, 150, 50)' && cs.outlineColor === 'rgb(0, 0, 0)'
        && cs.boxShadow.startsWith('rgb(255, 255, 255)'),
    others, active: cs && [cs.backgroundColor, cs.outlineColor, cs.boxShadow],
  };
}
"""

#: ערכות הנושא של הוובאפ — ``allowed`` ב-``webapp/templates/base.html``, בלי ``custom`` (שאין לה צבעים קבועים).
THEMES = ("classic", "ocean", "rose-pine-dawn", "dark", "dim", "nebula", "high-contrast")

#: ניגודיות WCAG בין כל אחד משני צבעי הטבעת לבין הרקע שמאחורי ההתאמה הפעילה — הרקע האטום הראשון בשרשרת
#: האבות, כי רקע התצוגה בחלק מהערכות שקוף ונלקח מהמכל שמעליו.
_RING_CONTRAST = """
() => {
  const rgb = (c) => (c.match(/[\\d.]+/g) || []).map(Number);
  const lum = ([r, g, b]) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  const hit = document.querySelector('#markdown-preview-content .in-file-search-hit.is-active');
  let bg = null;
  for (let n = hit.parentElement; n && !bg; n = n.parentElement) {
    const c = rgb(getComputedStyle(n).backgroundColor);
    if (c.length === 3 || (c.length === 4 && c[3] === 1)) bg = c.slice(0, 3);
  }
  const cs = getComputedStyle(hit);
  // רק צבעים שבאמת מוגדרים: ``box-shadow: none`` אינו צבע, וחישוב עליו היה ``NaN`` שעובר כל השוואה בשקט.
  const colors = [cs.outlineColor, cs.boxShadow].map((c) => rgb(c).slice(0, 3)).filter((c) => c.length === 3);
  return {
    theme: document.documentElement.getAttribute('data-theme'),
    colors: colors.length,
    best: colors.length ? +Math.max(...colors.map((c) => ratio(c, bg))).toFixed(2) : null,
  };
}
"""


def _search(tab, term) -> None:
    """פותח את החיפוש בכפתור שבראש הקובץ, ומקליד בתיבה."""
    tab.click("#search-in-file")
    tab.fill("#in-file-search-input", term)


def _count_is(tab, text, what) -> None:
    """מחכה למונה ``text``. כשלא הגיע, הכישלון מראה מה המונה הציג."""
    poll(tab, "(text) => { const c = document.getElementById('in-file-search-count').textContent;"
              " return c === text ? true : {ok: false, count: c}; }", what, text)


def test_rendered_markdown_counts_highlights_and_navigates_what_is_shown(
    world, admin_live_server, browser
):
    with repo_page(browser, admin_live_server) as (tab, errors):
        open_file(tab, admin_live_server, MD)
        poll(tab, _RENDERED, "הקובץ רונדר")
        _search(tab, TERM)
        _count_is(tab, f"1 / {SHOWN}", "המונה סופר את מה שמוצג")

        state = tab.evaluate(_STATE)
        # הצבע נמדד בדגימה ולא פעם אחת: בערכות הכהות ``dark-mode.css`` מעביר את ``background-color`` במעבר
        # של 0.3 שניות, ומדידה מיידית הייתה תופסת צבע ביניים.
        poll(tab, _COLORS, "כל ההתאמות צהובות, והפעילה כתומה")
        first = tab.evaluate(_ACTIVE_ON_SCREEN)

        # הבא, עד ההתאמה בשורת הקוד הארוכה משמאל לימין, ואז זו שבשורה העברית.
        for _ in range(3):
            tab.click("#in-file-search button[title=Next]")
        _count_is(tab, f"4 / {SHOWN}", "הבא")
        ltr = tab.evaluate(_ACTIVE_ON_SCREEN)
        tab.press("#in-file-search-input", "Enter")
        _count_is(tab, f"5 / {SHOWN}", "Enter הוא הבא")
        rtl = tab.evaluate(_ACTIVE_ON_SCREEN)
        tab.click("#in-file-search button[title=Next]")
        tab.click("#in-file-search button[title=Next]")
        _count_is(tab, f"7 / {SHOWN}", "עד האחרונה")
        last = tab.evaluate(_ACTIVE_ON_SCREEN)

        tab.click("#in-file-search button[title=Next]")
        _count_is(tab, f"1 / {SHOWN}", "מהאחרונה, הבא חוזר לראשונה")
        wrapped = tab.evaluate(_ACTIVE_ON_SCREEN)
        tab.press("#in-file-search-input", "Shift+Enter")
        _count_is(tab, f"{SHOWN} / {SHOWN}", "מהראשונה, הקודם עובר לאחרונה")
        back = tab.evaluate(_STATE)

    assert state == {"count": f"1 / {SHOWN}", "hits": SHOWN, "active": [0]}
    for name, where in (("ראשונה", first), ("משמאל לימין", ltr), ("בעברית", rtl), ("אחרונה", last),
                        ("אחרי המעבר לראשונה", wrapped)):
        assert where["ok"], (name, where)
        # העמוד לא זז: נגללת רק התצוגה. ``scrollIntoView`` היה גולל גם את ``body``.
        assert where["page"] == [0, 0, 0], (name, where)
    assert last["containerTop"] > 0 and wrapped["containerTop"] < last["containerTop"], (last, wrapped)
    # כל שורת קוד נגללה לכיוון שלה: משמאל לימין ``scrollLeft`` חיובי, ובעברית שלילי (ב-RTL הוא מתחיל ב-0
    # בקצה הימני ויורד שמאלה).
    assert ltr["direction"] == "ltr" and ltr["scrollLeft"] > 0, ltr
    assert rtl["direction"] == "rtl" and rtl["scrollLeft"] < 0, rtl
    assert back["active"] == [SHOWN - 1], back
    assert errors == [], "\n".join(errors)


def test_the_active_ring_stands_out_in_every_theme(world, admin_live_server, browser):
    """הטבעת של ההתאמה הפעילה נראית על הרקע של התצוגה בכל ערכה — לפחות אחד משני צבעיה ביחס 3:1 מולו
    (WCAG 2.1, 1.4.11). טבעת בצבע אחד נכשלה כאן: ``--accent-blue`` מול הרקע של rose-pine-dawn יצא 1.58."""
    with repo_page(browser, admin_live_server) as (tab, errors):
        open_file(tab, admin_live_server, MD)
        poll(tab, _RENDERED, "הקובץ רונדר")
        _search(tab, TERM)
        _count_is(tab, f"1 / {SHOWN}", "החיפוש רץ")
        measured = []
        for theme in THEMES:
            tab.evaluate("(t) => document.documentElement.setAttribute('data-theme', t)", theme)
            # ``dark-mode.css`` מעביר צבעים במעבר של 0.3 שניות בערכות הכהות, ולכן דוגמים עד שהערך נעמד.
            poll(tab, "(t) => document.documentElement.getAttribute('data-theme') === t", "הערכה הוחלפה", theme)
            tab.wait_for_timeout(400)
            measured.append(tab.evaluate(_RING_CONTRAST))

    # ``>= 3`` ולא ``< 3``: ערך שאינו מספר נכשל כאן, ולא עובר.
    weak = [m for m in measured if not (isinstance(m["best"], (int, float)) and m["best"] >= 3)]
    assert [m["theme"] for m in measured] == list(THEMES)
    assert weak == [], measured
    assert errors == [], "\n".join(errors)


def test_switching_views_with_the_search_open_searches_the_new_view(world, admin_live_server, browser):
    with repo_page(browser, admin_live_server) as (tab, errors):
        open_file(tab, admin_live_server, MD)
        poll(tab, _RENDERED, "הקובץ רונדר")
        _search(tab, TERM)
        _count_is(tab, f"1 / {SHOWN}", "בתצוגה המרונדרת")

        tab.click("#markdown-preview-toggle")
        # בתצוגת הקוד נספר המקור, כולל הכתובת של הקישור.
        _count_is(tab, f"1 / {IN_SOURCE}", "אחרי המעבר לקוד, המונה של המקור")
        in_code = tab.evaluate(_STATE)

        tab.click("#markdown-preview-toggle")
        poll(tab, _RENDERED, "חזרה לתצוגה המרונדרת")
        _count_is(tab, f"1 / {SHOWN}", "אחרי החזרה, שוב המונה של מה שמוצג")
        rendered_again = tab.evaluate(_STATE)

    # ההדגשות של התצוגה המרונדרת לא נשארות בה מאחורי הקלעים.
    assert in_code["hits"] == 0, in_code
    assert rendered_again == {"count": f"1 / {SHOWN}", "hits": SHOWN, "active": [0]}
    assert errors == [], "\n".join(errors)


def test_closing_the_search_removes_every_highlight(world, admin_live_server, browser):
    with repo_page(browser, admin_live_server) as (tab, errors):
        open_file(tab, admin_live_server, MD)
        poll(tab, _RENDERED, "הקובץ רונדר")
        before = tab.evaluate("() => document.getElementById('markdown-preview-content').innerHTML")
        _search(tab, TERM)
        _count_is(tab, f"1 / {SHOWN}", "החיפוש רץ")

        tab.click("#in-file-search button[title=Close]")
        after_close = tab.evaluate(_STATE)
        html_after_close = tab.evaluate("() => document.getElementById('markdown-preview-content').innerHTML")

        # ושוב, והפעם סגירה ב-Escape.
        _search(tab, TERM)
        _count_is(tab, f"1 / {SHOWN}", "החיפוש רץ שוב")
        tab.press("#in-file-search-input", "Escape")
        after_escape = tab.evaluate(_STATE)
        bar = tab.evaluate("() => document.getElementById('in-file-search').style.display")

    assert after_close == {"count": "", "hits": 0, "active": []}
    # התצוגה חוזרת בדיוק למה שהייתה, כולל צמתי הטקסט שהעטיפות פיצלו.
    assert html_after_close == before
    assert after_escape == {"count": "", "hits": 0, "active": []}
    assert bar == "none"
    assert errors == [], "\n".join(errors)


def test_closing_right_after_typing_leaves_no_highlights(world, admin_live_server, browser):
    """הקלדה ואחריה ``Escape`` בתוך ההשהיה של התיבה: החיפוש שהקלדה תזמנה לא רץ אחרי הסגירה. ההמתנה
    כאן ארוכה מההשהיה, ולכן חיפוש שהיה רץ אחרי הסגירה היה משאיר הדגשות בתצוגה."""
    with repo_page(browser, admin_live_server) as (tab, errors):
        open_file(tab, admin_live_server, MD)
        poll(tab, _RENDERED, "הקובץ רונדר")
        _search(tab, TERM)
        tab.press("#in-file-search-input", "Escape")
        tab.wait_for_timeout(600)
        state = tab.evaluate(_STATE)
        bar = tab.evaluate("() => document.getElementById('in-file-search').style.display")

    assert bar == "none"
    assert state == {"count": "", "hits": 0, "active": []}
    assert errors == [], "\n".join(errors)


def test_a_rendered_rst_page_is_searched_as_shown(world, admin_live_server, browser):
    """במקור של קובץ ה-rst אין ``initial_import`` בכלל, והעמוד מאתר התיעוד מציג אותו פעמיים."""
    with repo_page(browser, admin_live_server) as (tab, errors):
        open_file(tab, admin_live_server, RST)
        poll(tab, _RENDERED, "העמוד מאתר התיעוד רונדר")
        _search(tab, "initial_import")
        _count_is(tab, "1 / 2", "המונה סופר את העמוד המוצג")
        state = tab.evaluate(_STATE)
        tab.click("#in-file-search button[title=Next]")
        _count_is(tab, "2 / 2", "הבא")
        second = tab.evaluate(_ACTIVE_ON_SCREEN)

    assert state == {"count": "1 / 2", "hits": 2, "active": [0]}
    assert second["ok"], second
    assert errors == [], "\n".join(errors)


def test_a_version_from_the_history_is_searched_again(world, admin_live_server, browser):
    """"צפה" בפאנל ההיסטוריה מחליף את התוכן המוצג (``RepoState.setFileContent``), והחיפוש הפתוח רץ שוב עליו."""
    later = world.repo.commit({MD: MD_TEXT + "\nפסקה שנוספה אחרי הבנייה, עם lantern.\n"})
    # כמו סנכרון של קובץ שהשתנה: הקובץ מוצג מה-``commit_sha`` שלו (``_shown_ref`` ב-``webapp/routes/repo_browser.py``).
    world.db.repo_files.update_one({"repo_name": REPO, "path": MD}, {"$set": {"commit_sha": later}})

    with repo_page(browser, admin_live_server) as (tab, errors):
        open_file(tab, admin_live_server, MD)
        poll(tab, _RENDERED, "הקובץ רונדר")
        _search(tab, TERM)
        _count_is(tab, f"1 / {SHOWN + 1}", "בגרסה הנוכחית")

        tab.click(".file-history-btn")
        view = f'.history-commit[data-hash="{world.built}"] .view-btn'
        poll(tab, f"() => !!document.querySelector('{view}')", "הקומיט הקודם בפאנל ההיסטוריה")
        tab.click(view)
        _count_is(tab, f"1 / {SHOWN}", "בגרסה מההיסטוריה")
        state = tab.evaluate(_STATE)

    assert state == {"count": f"1 / {SHOWN}", "hits": SHOWN, "active": [0]}
    assert errors == [], "\n".join(errors)
