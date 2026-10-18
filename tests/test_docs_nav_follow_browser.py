"""תפריט הצד של אתר התיעוד עוקב אחרי הסעיף שקוראים בו — בדפדפן אמיתי, על אתר שנבנה עם ``docs/conf.py``.

**מה נבדק.** ``docs/_static/nav-follow.js`` מסמן בתפריט את הסעיף שקוראים בו, ומזיז את התפריט
רק כשהפריט המסומן יוצא מהתצוגה, כך שיהיה באמצע. הוא מזיז רק את התפריט ולא את העמוד, ועוקב
אחרי גלילה במגע של טאבלט. בנוסף, ``sticky_navigation`` של הערכה כבוי. כשהוא דלוק, הערכה
גוללת את התפריט באותו מרחק שהעמוד זז, וזה הבאג שהסקריפט בא להחליף.

**למה אתר שנבנה ולא עמוד שכתוב ביד.** ההתנהגות נקבעת יחד עם הערכה: ה-CSS שלה מקפל את
תתי-הסעיפים של פריט שלא נבחר, ה-JS שלה מסמן פריט ומגלגל אותו לתצוגה בטעינה (``reset`` ב-``theme.js``), וההגדרה
ב-``docs/conf.py`` קובעת אם היא גוללת את התפריט עם העמוד. עמוד שמחקה את המבנה לא היה כולל
אף אחד מאלה. לכן Sphinx בונה כאן אתר קטן עם ``docs/conf.py`` עצמו, התבנית ו-``_static``
של האתר. יש שני שינויים בלבד, ושניהם מוסברים ב-``_CONF``.

התפריט האמיתי ארוך מהמסך, ולכן גם כאן: שלושים סעיפים. תתי-הסעיפים של סעיף 5 מקופלים
בתפריט, כמו בעמודים של האתר.

מדולג כשאין Chromium (הפיקסצ'ר ``chromium_executable`` ב-``tests/conftest.py``), או כשאין את
התלויות של ``docs/requirements.txt``. כלומר הבדיקה **לא רצה ב-CI**: שם אין דפדפן בג'וב של
pytest. ההחלטות עצמן, בלי DOM, נבדקות ב-CI ב-``tests/docs-nav-follow.test.js``.
"""

from __future__ import annotations

import functools
import http.server
import subprocess
import sys
import threading
from pathlib import Path

import pytest

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import Touch, poll

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

#: הטאבלט שהבאג נראה בו (12.7 אינץ', לרוחב), במגע.
_TABLET = {
    "viewport": {"width": 1186, "height": 600},
    "device_scale_factor": 1.69,
    "is_mobile": True,
    "has_touch": True,
}

#: ``docs/conf.py`` עצמו, עם שני שינויים בלבד. הנתיבים: Sphinx פותר נתיבים יחסיים מתיקיית
#: הקונפיגורציה, והיא כאן תיקייה זמנית. ובלי ``intersphinx_mapping``: ההרחבה מורידה מלאי
#: מאתרים חיצוניים, ולעמודים כאן אין קישורים אליהם. ``exec`` הוא מה ש-Sphinx עצמו עושה
#: לקובץ הקונפיגורציה.
_CONF = """\
import pathlib
_REAL = pathlib.Path({real!r})
exec(compile(_REAL.read_text(encoding="utf-8"), str(_REAL), "exec"))
templates_path = [str(_REAL.parent / "_templates")]
html_static_path = [str(_REAL.parent / "_static")]
intersphinx_mapping = {{}}
"""

_PARAGRAPH = "שורה של טקסט בסעיף. " * 40


def _long_page() -> str:
    lines = ["עמוד ארוך", "=========", "", _PARAGRAPH, ""]
    for i in range(1, 31):
        lines += [f".. _sec-{i}:", "", f"סעיף {i}", "-" * 10, "", _PARAGRAPH, ""]
        if i == 5:
            for j in range(1, 4):
                lines += [f".. _sub-5-{j}:", "", f"תת-סעיף 5.{j}", "~" * 14, "", _PARAGRAPH, ""]
    return "\n".join(lines)


@pytest.fixture(scope="module")
def site(chromium_executable, tmp_path_factory):
    """האתר הקטן, בנוי. דורש את התלויות של ``docs/requirements.txt``."""
    pytest.importorskip("sphinx_rtd_theme", reason="אין את התלויות של docs/requirements.txt")
    work = tmp_path_factory.mktemp("nav_follow")
    src = work / "src"
    src.mkdir()
    (src / "conf.py").write_text(_CONF.format(real=str(DOCS / "conf.py")), encoding="utf-8")
    (src / "index.rst").write_text("בית\n===\n\n.. toctree::\n\n   long\n   other\n", encoding="utf-8")
    (src / "other.rst").write_text("עמוד אחר\n========\n\nטקסט.\n", encoding="utf-8")
    (src / "long.rst").write_text(_long_page(), encoding="utf-8")
    out = work / "html"
    built = subprocess.run(
        [sys.executable, "-B", "-m", "sphinx", "-b", "html", "-q", str(src), str(out)],
        cwd=work,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert built.returncode == 0, f"בניית האתר נכשלה:\n{(built.stdout + built.stderr)[-3000:]}"
    return out


@pytest.fixture(scope="module")
def server(site):
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_QuietHandler, directory=site))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture(scope="module")
def browser(chromium_executable):
    with sync_playwright() as p:
        launched = (
            p.chromium.launch(executable_path=chromium_executable) if chromium_executable else p.chromium.launch()
        )
        try:
            yield launched
        finally:
            launched.close()


@pytest.fixture
def page(browser, server):
    context = browser.new_context(**_TABLET)
    try:
        tab = context.new_page()
        tab.goto(f"{server}/long.html", wait_until="load")
        yield tab
    finally:
        context.close()


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:  # noqa: D401 — שקט בפלט של pytest
        pass


#: מצב העמוד והתפריט. ``expected`` הוא הכלל, כפי שהמשתמש רואה אותו: מבין הסעיפים שהכותרת
#: שלהם עברה את קו הקריאה, האחרון. אם הפריט שלו מקופל בתפריט, הפריט המוצג הקרוב שמעליו.
#: קו הקריאה נלקח מהסקריפט (``readLine``), והחישוב שלו נבדק ב-``tests/docs-nav-follow.test.js``.
_STATE_JS = """() => {
  const scroller = document.querySelector('.wy-side-scroll');
  const box = scroller.getBoundingClientRect();
  const line = window.DocNavFollow.readLine(innerHeight, document.documentElement.scrollHeight - innerHeight, scrollY);
  let expected = null, best = -Infinity;
  for (const a of document.querySelectorAll('.wy-menu-vertical a[href^="#"]')) {
    const section = document.getElementById(a.getAttribute('href').slice(1));
    if (!section) continue;
    const top = section.getBoundingClientRect().top;
    if (top <= line && top > best) { expected = a; best = top; }
  }
  while (expected && expected.getClientRects().length === 0) {
    const parent = expected.closest('li').parentElement.closest('li');
    expected = parent ? parent.querySelector(':scope > a') : null;
  }
  const marked = [...document.querySelectorAll('.doc-nav-active')];
  const a = marked[0] || null;
  const r = a ? a.getBoundingClientRect() : null;
  return {
    y: Math.round(scrollY), menu: scroller.scrollTop, menuMax: scroller.scrollHeight - scroller.clientHeight,
    count: marked.length, marked: a ? a.getAttribute('href') : null,
    expected: expected ? expected.getAttribute('href') : null,
    inView: a ? r.top >= box.top - 1 && r.bottom <= box.bottom + 1 : null,
    offCenter: a ? Math.abs((r.top + r.bottom) / 2 - (box.top + box.bottom) / 2) : null,
  };
}"""

#: שתי פריימים: הסקריפט מעדכן ב-``requestAnimationFrame`` אחרי אירוע הגלילה.
_FRAMES_JS = "() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))"

#: הגלילה נעצרה: אותו ``scrollY`` לאורך עשרה פריימים (מגע ממשיך לגלול אחרי שהאצבע עוזבת).
_SETTLED_JS = """() => new Promise((done) => {
  const start = scrollY; let frames = 0;
  const tick = () => {
    frames += 1;
    if (frames < 10) requestAnimationFrame(tick); else done({ok: scrollY === start, y: scrollY});
  };
  requestAnimationFrame(tick);
})"""


def _state_at(page, y: int) -> dict:
    page.evaluate("(y) => window.scrollTo(0, y)", y)
    page.evaluate(_FRAMES_JS)
    return {**page.evaluate(_STATE_JS), "asked": y}


def _scroll_to_section(page, anchor: str, offset: int = 10) -> dict:
    """מביא את הכותרת של ``anchor`` ל-``offset`` פיקסלים מראש המסך, כלומר מעל קו הקריאה."""
    y = page.evaluate(
        "([id, offset]) => Math.round(document.getElementById(id).getBoundingClientRect().top + scrollY - offset)",
        [anchor, offset],
    )
    return _state_at(page, y)


def test_reading_down_the_page_marks_each_section_and_moves_only_the_menu(page):
    end = page.evaluate("() => document.documentElement.scrollHeight - innerHeight")
    rows = [_state_at(page, y) for y in [*range(0, end, 120), end]]

    assert rows[0]["menuMax"] > 0, "בקרה: התפריט קצר מהקופסה שלו, ואז אין מה לגלול"
    assert [r["y"] for r in rows] == [r["asked"] for r in rows], "העמוד זז בלי שגללו אותו"
    assert max(r["count"] for r in rows) == 1
    assert [(r["asked"], r["marked"], r["expected"]) for r in rows if r["marked"] != r["expected"]] == []
    assert [r["asked"] for r in rows if r["marked"] and not r["inView"]] == [], "פריט מסומן שאינו נראה בתפריט"

    pairs = list(zip(rows, rows[1:]))
    moves = [(a, b) for a, b in pairs if a["menu"] != b["menu"]]
    changes = [(a, b) for a, b in pairs if a["marked"] != b["marked"]]
    assert [(b["asked"], b["marked"]) for a, b in moves if a["marked"] == b["marked"]] == [], (
        "התפריט זז בלי שהסעיף המסומן התחלף"
    )
    assert 0 < len(moves) < len(changes), f"{len(moves)} תזוזות של התפריט, {len(changes)} החלפות של הסעיף"
    assert [
        (b["asked"], b["offCenter"]) for a, b in moves if b["offCenter"] > 1 and b["menu"] not in (0, b["menuMax"])
    ] == [], "אחרי תזוזה הפריט אינו באמצע, והתפריט לא הגיע לקצה שלו"
    # גם הסעיפים שבסוף העמוד, שהכותרת שלהם לא יכולה לעלות עד החמישית העליונה, ולפי הסדר
    assert {f"#sec-{i}" for i in range(1, 31)} - {r["marked"] for r in rows} == set(), "סעיף שלא סומן אף פעם"
    order = [int(r["marked"].split("-")[1]) for r in rows if r["marked"]]
    assert order == sorted(order), f"הסימון חזר לסעיף קודם בזמן גלילה למטה: {order}"
    assert rows[-1]["marked"] == "#sec-30", "בתחתית העמוד מסומן הסעיף האחרון"


def test_the_mark_is_a_bar_on_the_side_where_the_text_starts(page):
    _scroll_to_section(page, "sec-12")
    bar = page.evaluate("""() => {
      const bars = [...document.querySelectorAll('.wy-menu-vertical a')]
        .filter((a) => getComputedStyle(a, '::before').content !== 'none');
      const style = getComputedStyle(bars[0], '::before');
      return {count: bars.length, href: bars[0].getAttribute('href'), width: style.width,
              dir: document.documentElement.dir, right: style.right, left: style.left};
    }""")
    assert bar["dir"] == "rtl", "בקרה: האתר נבנה בעברית"
    assert (bar["count"], bar["href"], bar["width"], bar["right"]) == (1, "#sec-12", "3px", "0px"), bar
    assert bar["left"] != "0px", bar


def test_the_menu_stays_where_the_reader_left_it_until_the_next_section(page):
    marked = _scroll_to_section(page, "sec-15")
    assert marked["marked"] == "#sec-15"
    # הקורא גולל את התפריט לראשו, והפריט המסומן יוצא מהתצוגה
    page.evaluate("() => { document.querySelector('.wy-side-scroll').scrollTop = 0; }")
    page.evaluate(_FRAMES_JS)
    assert page.evaluate(_STATE_JS)["inView"] is False, "בקרה: הפריט עדיין נראה, ואז אין מה לבדוק"

    same = _state_at(page, marked["asked"] + 60)
    assert (same["marked"], same["menu"]) == ("#sec-15", 0), "התפריט קפץ חזרה בתוך אותו סעיף"

    following = _scroll_to_section(page, "sec-16")
    assert following["marked"] == "#sec-16"
    assert following["inView"] and following["offCenter"] <= 1, following


def test_a_section_inside_a_folded_entry_marks_the_entry(page):
    assert page.evaluate("() => document.querySelector('a[href=\"#sub-5-2\"]').getClientRects().length") == 0, (
        "בקרה: תתי-הסעיפים של סעיף 5 אינם מקופלים בתפריט"
    )
    state = _scroll_to_section(page, "sub-5-2")
    assert (state["marked"], state["inView"]) == ("#sec-5", True), state


def test_opening_a_link_to_a_section_marks_it_without_moving_the_page(page, server):
    page.goto(f"{server}/long.html#sec-20", wait_until="load")
    poll(page, f"() => ({_STATE_JS})().marked === '#sec-20'", "הסעיף מהקישור מסומן")
    page.evaluate(_FRAMES_JS)
    state = page.evaluate(_STATE_JS)
    top = page.evaluate("() => document.getElementById('sec-20').getBoundingClientRect().top")
    assert abs(top) <= 1, f"העמוד זז מהעוגן: הכותרת ב-{top}"
    assert state["inView"], state


def test_swiping_through_the_page_keeps_the_marked_item_in_the_menu(page):
    touch = Touch(page.context.new_cdp_session(page))
    assert page.evaluate("() => !document.elementFromPoint(300, 450).closest('.wy-nav-side')"), (
        "בקרה: נקודת המגע נופלת על התפריט ולא על הטקסט"
    )
    rows = []
    for _ in range(10):
        touch.swipe(300, 450, 0, -240)
        poll(page, _SETTLED_JS, "הגלילה נעצרה")
        rows.append(page.evaluate(_STATE_JS))
    assert rows[-1]["y"] > 0, "בקרה: המגע לא גלל את העמוד"
    assert [(r["y"], r["marked"], r["expected"]) for r in rows if r["marked"] != r["expected"]] == []
    assert [r["y"] for r in rows if r["marked"] and not r["inView"]] == []
