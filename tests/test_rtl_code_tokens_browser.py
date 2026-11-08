"""עברית בתוך שורת קוד — בכרומיום אמיתי, בעמודים שמדגישים קוד דרך ``SafeHighlight``.

**הבאג.** כל שורה בבלוק קוד היא פסקה משמאל לימין. הערה כמו ``// הצורה המינימלית של צומת hast
שהתוסף צריך`` מתפרקת לשני קטעים עבריים משני צדי ``hast``, והם מסודרים משמאל לימין — בסדר הקריאה
ההפוך. התיקון עוטף את הגוף של הערה או מחרוזת עבריות ב-``<span dir="rtl">``
(``RtlCode.isolateHebrewTokens`` ב-``webapp/static/js/utils/rtl-code.js``), ו-``SafeHighlight.highlightBlock``
מריץ אותו אחרי כל הדגשה.

**העמודים** (``TESTING-PATTERNS.md`` T1): דפדפן הריפו בתצוגה המרונדרת — דרך ``live-preview.js``
(``highlightBlocks``, אותה פונקציה שהתצוגה החיה בעמוד העריכה מדגישה בה), ודרך המסלול החלופי כש-
``live-preview.js`` לא נטען (``enhanceMarkdownFallback``) — וספריית הסניפטים (``/snippets``), שמדגישה
דרך ``highlightBlock`` ישירות ומפרקת את הבלוק אחר כך לטבלת שורות. השרת, המסד והמראה של דפדפן הריפו —
``_repo_browser_harness.py``. בספריית הסניפטים ה-API מזויף, ו-highlight.js מה-CDN מוגש מהבאנדל המקומי
(``md_preview.bundle.js``, 11.11.1; ה-CDN מגיש 11.9.0, ומבנה הטוקנים של הערות ומחרוזות זהה בשתיהן —
נבדק ב-8.11.2026). תוסף מספרי השורות מוגש כ-404, כמו בפרודקשן: ``highlightjs-line-numbers.js@2.11.0``
אינו קיים ב-npm (הגרסה האחרונה 2.9.1), ולכן העמוד תמיד בונה את הטבלה בעצמו.

**המדידה היא של הציור.** לכל ביטוי עברי: סדר המילים על המסך זהה לסדר שלהן באותו טקסט בתוך ``div``
עם ``dir="rtl"`` — כלומר הוא נקרא כמו פסקה עברית. לכל שורה: השלד שלה (כל תו שאינו עברי, אינו רווח
ואינו חלק מגוף שצריך להיעטף — ``WRAPPED`` — וכל גוף כיחידה אחת) מצויר משמאל לימין בסדר הלוגי, והקצה
השמאלי שלה לא זז מריצת הבקרה. השלד נגזר מהגופים ולא מהעטיפות שבעמוד, ולכן סימן הערה או tag של מחרוזת
שנכנסו לעטיפה נמדדים כשלד, ונתפסים כשהם מצוירים בצד הלא נכון של הגוף. **ריצת הבקרה** היא אותו
עמוד כש-``isolateHebrewTokens`` לא עושה כלום, והיא מוכיחה שהמדידה רואה את הבאג: שם הביטויים לא
נקראים כעברית, והשורה עם מחרוזת והערה עבריות מאבדת את סדר השלד שלה.

**מה לא נבדק כאן:** תצוגת המסמך (``/md/<id>``), התצוגה החיה בעמוד העריכה ותצוגת הסניפט של האדמין —
שלושתם דורשים מונגו אמיתי (``wired_mongo``). שלושתם מדגישים דרך אותו ``highlightBlock``, והחיווט שלהם
נבדק ב-``tests/sticky-notes-target.test.js``. ספארי ופיירפוקס — יש כאן רק כרומיום.

מדולג כשאין Chromium (וב-CI אין: ראו ``docs/testing.rst``), וכשאין git.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import poll
from _docs_index_harness import site_pages
from _git_mirror_harness import GIT
from _repo_browser_harness import TABLET, mirror_world, open_file, repo_page

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

pytestmark = pytest.mark.skipif(GIT is None, reason="git is not installed")

ROOT = Path(__file__).resolve().parent.parent
BUNDLE = ROOT / "webapp" / "static" / "js" / "md_preview.bundle.js"

#: הבלוקים: (שפה, קוד). אותו קוד בשני העמודים — בקובץ Markdown בדפדפן הריפו, וכסניפטים.
SAMPLES = [
    ("javascript", "\n".join([
        "  // הצורה המינימלית של צומת hast שהתוסף צריך",
        "  const x = 1; // TODO: לתקן את זה כשיהיה API חדש",
        "  /* הערה ארוכה על ה-parser",
        "   * שורה שנייה עם hast בעברית",
        "   */",
        '  const t = "שלום עולם"; // הערה בעברית אחרי מחרוזת',
    ])),
    ("python", "\n".join([
        "async def f(name):",
        '    """True אם ההודעה נשלחה בהצלחה ל-user',
        "    שורה שנייה של הסבר עם API",
        '    """',
        '    await reply(f"✅ הקובץ {name} נשמר בהצלחה ב-MongoDB")',
        "    # הערה",
    ])),
    ("html", "\n".join([
        "<!-- הערה עם div בעברית -->",
        '<p title="כותרת עם id בעברית">x</p>',
    ])),
    ("sql", "\n".join([
        "-- שאילתה שמחזירה users פעילים",
        "-- the user ה-id",
    ])),
    ("yaml", "name: ערך בעברית ארוך"),
    # סימן הערה שאינו ברשימה של הבלוג, ומחרוזת raw של C++ עם tag שאינו סימטרי במראה.
    ("ini", "; הערה ארוכה על key בעברית\nkey = value"),
    ("cpp", 'auto s = R"-=(שלום עם id בעברית)-=";'),
]

#: מה שנעטף, בסדר המסמך — הגוף בלבד: בלי ההזחה, בלי סימני ההערה ובלי השלד של המחרוזת.
#: לא נעטפים: ``# הערה`` (מילה אחת), ``-- the user ה-id`` (העברית מתחת לסף) וערך ה-YAML —
#: highlight.js צובע אותו כטוקן לכל מילה.
WRAPPED = [
    "הצורה המינימלית של צומת hast שהתוסף צריך",
    "TODO: לתקן את זה כשיהיה API חדש",
    "הערה ארוכה על ה-parser",
    "שורה שנייה עם hast בעברית",
    "שלום עולם",
    "הערה בעברית אחרי מחרוזת",
    "True אם ההודעה נשלחה בהצלחה ל-user",
    "שורה שנייה של הסבר עם API",
    "✅ הקובץ {name} נשמר בהצלחה ב-MongoDB",
    "הערה עם div בעברית",
    "כותרת עם id בעברית",
    "שאילתה שמחזירה users פעילים",
    "הערה ארוכה על key בעברית",
    "שלום עם id בעברית",
]

#: ביטויים שיש בהם מילה לועזית בין העבריות — בריצת הבקרה הם **לא** נקראים כעברית, ואחרי התיקון כן.
FIXED = [w for w in WRAPPED if w != "שלום עולם" and w != "הערה בעברית אחרי מחרוזת"]

#: מילים עבריות צמודות בלי עטיפה — נקראות כעברית לפני התיקון ואחריו. ערך ה-YAML הוא טוקן לכל מילה,
#: ועטיפה של כל אחת לבד הייתה הופכת את הסדר שלהן.
KEPT = ["ערך בעברית ארוך"]

#: השורה שבה מחרוזת עברית והערה עברית נדבקות לרצף אחד בלי התיקון — והשלד שביניהן (``"; //``) זז.
MERGED_LINE = '  const t = "שלום עולם"; // הערה בעברית אחרי מחרוזת'

#: בלוק עברי בלי שפה (``pre.rtl-code``) — כולו מימין לשמאל, ולכן העטיפה מדלגת עליו.
RTL_BLOCK = "הערה בעברית בלי שפה // עם hast בתוכה"

MD = "docs/tokens.md"
MD_TEXT = "# עברית בתוך קוד\n\n" + "".join(f"```{lang}\n{code}\n```\n\n" for lang, code in SAMPLES) + (
    f"```\n{RTL_BLOCK}\n```\n"
)

#: איך נבנה כל מצב: בקרה — העטיפה לא עושה כלום; כשל — היא זורקת. ``rtl-code.js`` מציב
#: ``window.RtlCode = {...}``, והמציב כאן מחליף בו את הפונקציה לפני שאיש קרא לה.
_REPLACE_ISOLATE = """(() => {{
  let real;
  Object.defineProperty(window, 'RtlCode', {{
    configurable: true,
    get() {{ return real; }},
    set(value) {{ value.isolateHebrewTokens = {impl}; real = value; }},
  }});
}})();"""
MODES = {
    "fixed": "",
    "control": _REPLACE_ISOLATE.format(impl="() => 0"),
    "throwing": _REPLACE_ISOLATE.format(impl="() => { throw new Error('iso-probe'); }"),
}

#: היכן כל עמוד מציג את הבלוקים, וכמה בלוקים יש בו.
SURFACES = {
    "repo_browser": ("#markdown-preview-content", len(SAMPLES) + 1),
    "repo_fallback": ("#markdown-preview-content", len(SAMPLES) + 1),
    "snippets": ("#results", len(SAMPLES)),
}

#: מוכן: כל הבלוקים צבועים. בדפדפן הריפו — ``data-highlighted`` וכפתור העתקה ליד כל בלוק (הכפתור
#: נוסף אחרי ההדגשה). בספריית הסניפטים — טבלת השורות, שנבנית אחרי ההדגשה.
READY_JS = """([root, count]) => {
  const pres = [...document.querySelectorAll(root + ' pre')];
  const done = pres.filter((p) => {
    const c = p.querySelector('code');
    return p.querySelector('table.hljs-ln')
      || (c && c.dataset.highlighted === 'yes' && p.querySelector('.code-copy-btn'));
  });
  return {ok: pres.length >= count && done.length >= count, pres: pres.length, done: done.length};
}"""

#: לכל שורה של כל בלוק: הטקסט, הקצה השמאלי, האם השלד מסודר משמאל לימין, ומה נמדד לכל ביטוי.
#: שורה היא מה שבין ירידות שורה, או תא בטבלת השורות של ספריית הסניפטים.
MEASURE_JS = r"""([root, needles, bodies]) => {
  const HEB = /[֐-׿]/;
  const WORD = /[\p{L}\p{N}]/u;
  const lines = [];
  document.querySelectorAll(root + ' pre').forEach((pre) => {
    let line = null;
    let cell;
    const rtl = pre.classList.contains('rtl-code');
    const walker = document.createTreeWalker(pre, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = walker.nextNode())) {
      if (n.parentElement.closest('button')) continue;
      const inCell = n.parentElement.closest('.hljs-ln-code');
      if (!line || inCell !== cell) { line = {chars: [], rtl}; lines.push(line); cell = inCell; }
      const wrap = n.parentElement.closest('span[dir="rtl"]');
      const font = getComputedStyle(n.parentElement).font;
      for (let i = 0; i < n.data.length; i++) {
        if (n.data[i] === '\n') { line = {chars: [], rtl}; lines.push(line); continue; }
        const r = document.createRange();
        r.setStart(n, i); r.setEnd(n, i + 1);
        const b = r.getBoundingClientRect();
        line.chars.push({c: n.data[i], left: b.left, right: b.right, cy: (b.top + b.bottom) / 2, wrap, font});
      }
    }
  });
  // **שורה ארוכה נשברת לכמה שורות מסך** בספריית הסניפטים (``white-space: pre-wrap`` על
  // ``.hljs-ln-line`` ב-``snippets.css``). סדר הקריאה הוא שורות מסך מלמעלה למטה, ובכל אחת לפי
  // הכיוון — ולכן לכל תו מספר שורת מסך. גובה התווים בשורה אחת אינו זהה (גופן חלופי לעברית), ולכן
  // האשכול לפי מרכז, עם סובלנות של חצי שורה.
  lines.forEach((l) => {
    const centers = [...new Set(l.chars.filter((x) => x.c.trim()).map((x) => Math.round(x.cy)))].sort((a, b) => a - b);
    const rows = [];
    centers.forEach((c) => { if (!rows.length || c - rows[rows.length - 1] > 8) rows.push(c); });
    l.chars.forEach((x) => {
      let row = 0;
      rows.forEach((c, k) => { if (Math.abs(x.cy - c) < Math.abs(x.cy - rows[row])) row = k; });
      x.row = row;
    });
  });
  const ref = document.createElement('div');
  ref.dir = 'rtl';
  ref.style.cssText = 'position:absolute;top:0;right:0;white-space:pre;visibility:hidden';
  document.body.appendChild(ref);
  const words = (text, from) => {
    const out = [];
    let cur = null;
    for (let i = 0; i < text.length; i++) {
      if (!WORD.test(text[i])) { cur = null; continue; }
      if (!cur) { cur = {s: from + i, e: from + i + 1}; out.push(cur); } else cur.e = from + i + 1;
    }
    return out;
  };
  // סדר הקריאה של מילים מימין לשמאל: שורת מסך עליונה קודם, ובתוכה מימין לשמאל.
  const order = (ws, placeOf) => ws.map((w, i) => ({i, ...placeOf(w)}))
    .sort((a, b) => (a.row - b.row) || (b.x - a.x)).map((o) => o.i);
  const result = lines.filter((l) => l.chars.length).map((l) => {
    const text = l.chars.map((x) => x.c).join('');
    const visible = l.chars.filter((x) => x.c.trim());
    // **השלד נגזר מהגופים שצריכים להיעטף (``WRAPPED``), ולא מהעטיפות שבעמוד** — כך סימן הערה או
    // tag שנכנסו בטעות לעטיפה נמדדים כשלד, ונתפסים כשהם מצוירים בצד הלא נכון של הגוף.
    const bodyOf = new Array(text.length).fill(-1);
    bodies.forEach((body, b) => {
      for (let at = text.indexOf(body); at >= 0; at = text.indexOf(body, at + 1)) {
        for (let k = at; k < at + body.length; k++) bodyOf[k] = b;
      }
    });
    const items = [];
    // גוף שנשבר לשתי שורות מסך הוא שתי יחידות, אחת בכל שורה.
    l.chars.forEach((x, k) => {
      if (!x.c.trim()) return;
      if (bodyOf[k] >= 0) {
        const last = items[items.length - 1];
        if (last && last.body === bodyOf[k] && last.row === x.row) {
          last.left = Math.min(last.left, x.left); last.right = Math.max(last.right, x.right);
        } else items.push({body: bodyOf[k], row: x.row, left: x.left, right: x.right});
        return;
      }
      if (HEB.test(x.c)) return;
      items.push({c: x.c, row: x.row, left: x.left, right: x.right});
    });
    // שורה בבלוק עברי (``pre.rtl-code``) מסודרת מימין לשמאל בכוונה, ואין לה שלד משמאל לימין.
    const ordered = l.rtl || items.every((it, i) => i === 0 || items[i - 1].row < it.row
      || (items[i - 1].row === it.row && items[i - 1].right <= it.left + 1));
    return {text, edge: visible.length ? Math.round(Math.min(...visible.map((x) => x.left))) : null,
            ordered, chars: l.chars};
  });
  const measured = needles.map((needle) => {
    const line = result.find((l) => l.text.indexOf(needle) >= 0);
    if (!line) return {needle, found: false};
    const at = line.text.indexOf(needle);
    const ws = words(needle, at);
    const center = (w) => {
      const cs = line.chars.slice(w.s, w.e);
      return {row: cs[0].row, x: cs.reduce((s, x) => s + (x.left + x.right) / 2, 0) / cs.length};
    };
    ref.style.font = line.chars[at].font;
    ref.textContent = needle;
    const tn = ref.firstChild;
    // ההפניה בשורה אחת (``white-space: pre``) — הסדר שבו פסקה עברית נקראת.
    const refCenter = (w) => {
      const r = document.createRange();
      let sum = 0;
      for (let k = w.s - at; k < w.e - at; k++) {
        r.setStart(tn, k); r.setEnd(tn, k + 1);
        const b = r.getBoundingClientRect();
        sum += (b.left + b.right) / 2;
      }
      return {row: 0, x: sum / (w.e - w.s)};
    };
    const screen = order(ws, center);
    const expected = order(ws, refCenter);
    return {needle, found: true, hebrew: JSON.stringify(screen) === JSON.stringify(expected), screen, expected};
  });
  ref.remove();
  const wrappers = [...document.querySelectorAll(root + ' span[dir="rtl"]')];
  const style = wrappers.length ? getComputedStyle(wrappers[0]) : null;
  return {
    lines: result.map(({text, edge, ordered}) => ({text, edge, ordered})),
    needles: measured,
    wrapped: wrappers.map((w) => w.textContent),
    bidi: style && {unicodeBidi: style.unicodeBidi, direction: style.direction},
    rtlBlockWrappers: [...document.querySelectorAll(root + ' pre.rtl-code span[dir="rtl"]')].length,
  };
}"""


def _snippet_items():
    return [
        {"id": f"s{i}", "title": f"דוגמה {i}", "description": "", "language": lang, "code": code, "username": "t"}
        for i, (lang, code) in enumerate(SAMPLES)
    ]


def _snippets_api(route) -> None:
    """ה-API של ספריית הסניפטים, highlight.js מה-CDN ותוסף מספרי השורות. מארח אחר — נחסם."""
    url = urlsplit(route.request.url)
    path = unquote(url.path)
    if url.hostname == "cdn.jsdelivr.net" and path.endswith("/highlight.min.js"):
        route.fulfill(status=200, content_type="application/javascript", body=BUNDLE.read_text(encoding="utf-8"))
        return
    if url.hostname == "cdn.jsdelivr.net" and "highlightjs-line-numbers" in path:
        route.fulfill(status=404, body="")
        return
    if url.hostname != "127.0.0.1":
        route.abort()
        return
    if path == "/api/snippets/languages":
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "languages": []}))
    elif path == "/api/snippets":
        items = _snippet_items()
        body = {"ok": True, "items": items, "page": 1, "per_page": 30, "total": len(items)}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
    else:
        route.continue_()


@pytest.fixture(scope="module")
def browser(chromium_executable):
    """הדפדפן של הקובץ — **המקום היחיד שמרים דפדפן כאן** (``tests/test_browser_suite_is_gated_once.py``)."""
    with sync_playwright() as pw:
        try:
            launched = pw.chromium.launch(executable_path=chromium_executable)
        except PlaywrightError as exc:  # pragma: no cover - תלוי בסביבה
            pytest.skip(f"אין Chromium זמין: {exc}")
        try:
            yield launched
        finally:
            launched.close()


@pytest.fixture
def world(tmp_path, monkeypatch):
    # אתר התיעוד אינו חלק מהבדיקה, אבל ``mirror_world`` בונה אינדקס ודורש בו עמוד אחד לפחות.
    return mirror_world(tmp_path, monkeypatch, {MD: MD_TEXT}, site_pages())


@contextlib.contextmanager
def opened(surface: str, mode: str, browser, server):
    """העמוד של המשטח במצב ``mode``, אחרי שכל הבלוקים נצבעו. מחזיר ``(page, root, console)``."""
    root, count = SURFACES[surface]
    console: list[str] = []
    if surface == "snippets":
        context = browser.new_context(viewport=TABLET, locale="he-IL")
        try:
            context.add_cookies([{
                "name": "session", "value": server.session_cookie, "domain": "127.0.0.1", "path": "/",
            }])
            page = context.new_page()
            page.on("console", lambda msg: console.append(msg.text))
            if MODES[mode]:
                page.add_init_script(MODES[mode])
            page.route("**/*", _snippets_api)
            page.goto(f"{server.base_url}/snippets", wait_until="load")
            poll(page, f"() => document.querySelectorAll('{root} details').length >= {count}", "הסניפטים הוצגו")
            # הקוד בתוך ``details`` סגור, וההדגשה רצה כשהוא נפתח (``toggle`` ב-``snippets.js``).
            page.evaluate(f"() => document.querySelectorAll('{root} details').forEach((d) => {{ d.open = true; }})")
            poll(page, READY_JS, f"{surface}: כל הבלוקים נצבעו", [root, count])
            yield page, root, console
        finally:
            context.close()
        return
    with repo_page(browser, server) as (page, _errors):
        page.on("console", lambda msg: console.append(msg.text))
        if MODES[mode]:
            page.add_init_script(MODES[mode])
        if surface == "repo_fallback":
            # נרשם אחרי ה-route של ``repo_page``, ולכן קודם לו.
            page.route("**/static/js/live-preview.js*", lambda route: route.abort())
        open_file(page, server, MD)
        poll(page, READY_JS, f"{surface}: כל הבלוקים נצבעו", [root, count])
        if surface == "repo_fallback":
            # בקרה: אילו ``live-preview.js`` נטען בכל זאת, הבדיקה הייתה עוברת במסלול הרגיל.
            assert page.evaluate("() => typeof window.MarkdownLiveRenderer") == "undefined"
        yield page, root, console


def _measure(page, root):
    return page.evaluate(MEASURE_JS, [root, FIXED + KEPT, WRAPPED])


@pytest.mark.parametrize("surface", list(SURFACES))
def test_hebrew_in_a_code_line_reads_right_to_left(surface, browser, admin_live_server, world):
    """כל ביטוי עברי בהערה או במחרוזת נקרא כמו פסקה עברית, שלד השורה נשאר משמאל לימין בסדר הלוגי,
    והקצה השמאלי של אף שורה לא זז. ריצת הבקרה — אותו עמוד בלי העטיפה — מראה שהמדידה רואה את הבאג."""
    with opened(surface, "control", browser, admin_live_server) as (page, root, _):
        before = _measure(page, root)
    with opened(surface, "fixed", browser, admin_live_server) as (page, root, _):
        after = _measure(page, root)

    for m in before["needles"] + after["needles"]:
        assert m["found"], f"{surface}: לא נמצא {m['needle']!r}"
    # בקרה: בלי העטיפה הביטויים לא נקראים כעברית, והשורה הממוזגת מאבדת את סדר השלד.
    assert before["wrapped"] == [], f"{surface}: בריצת הבקרה נוצרו עטיפות"
    still = [m["needle"] for m in before["needles"] if m["needle"] in FIXED and m["hebrew"]]
    assert still == [], f"{surface}: בבקרה נקראו כעברית כבר לפני התיקון — הביטוי לא בודק כלום: {still}"
    merged = [ln for ln in before["lines"] if ln["text"] == MERGED_LINE]
    assert merged and not merged[0]["ordered"], f"{surface}: בבקרה השלד של השורה הממוזגת מסודר: {merged}"

    assert after["wrapped"] == WRAPPED, f"{surface}: מה שנעטף: {after['wrapped']}"
    assert after["bidi"] == {"unicodeBidi": "isolate", "direction": "rtl"}, f"{surface}: {after['bidi']}"
    wrong = [m for m in after["needles"] if not m["hebrew"]]
    assert wrong == [], f"{surface}: לא נקראים כעברית: {wrong}"
    disordered = [ln["text"] for ln in after["lines"] if not ln["ordered"]]
    assert disordered == [], f"{surface}: שלד השורה לא משמאל לימין: {disordered}"
    assert [ln["text"] for ln in before["lines"]] == [ln["text"] for ln in after["lines"]], surface
    moved = [(b["text"], b["edge"], a["edge"]) for b, a in zip(before["lines"], after["lines"])
             if b["edge"] is not None and abs(b["edge"] - a["edge"]) > 1]
    assert moved == [], f"{surface}: הקצה השמאלי של שורות זז: {moved}"
    if surface != "snippets":
        assert after["rtlBlockWrappers"] == 0, f"{surface}: בלוק עברי בלי שפה קיבל עטיפה"


CODE_TEXTS_JS = """(root) => [...document.querySelectorAll(root + ' pre code')].map((c) => c.textContent)"""
CELLS_JS = """(root) => [...document.querySelectorAll(root + ' pre')].map(
  (p) => [...p.querySelectorAll('.hljs-ln-code')].map((td) => td.textContent))"""

#: שולח שוב את כל הבלוקים בעמוד דרך העטיפה, ישירות ואחר כך דרך הדגשה מחדש מאפס. מחזיר כמה עטיפות
#: הוסיפה הקריאה הישירה, אם ה-HTML השתנה אחריה, כמה בלוקים נצבעו מחדש, ואם ה-HTML השתנה אחריהם.
#:
#: **``data-highlighted`` נמחק לפני ``highlightBlock``.** בלוק שכבר נצבע נושא אותו, ו-``highlightBlock``
#: חוזר מיד כשהוא קיים — כך שקריאה בלעדיו לא הייתה מגיעה לעטיפה בכלל. בלעדיו ההדגשה בונה את הבלוק
#: מחדש מהטקסט שלו, ומריצה את העטיפה על הבלוק החדש.
REPEAT_JS = """(root) => {
  const pres = [...document.querySelectorAll(root + ' pre')];
  const html = pres.map((p) => p.innerHTML);
  const added = pres.reduce((sum, p) => sum + window.RtlCode.isolateHebrewTokens(p), 0);
  const direct = pres.every((p, i) => p.innerHTML === html[i]);
  let rebuilt = 0;
  pres.forEach((p) => {
    const c = p.querySelector('code');
    if (!c) return;
    delete c.dataset.highlighted;
    window.SafeHighlight.highlightBlock(c);
    if (c.dataset.highlighted === 'yes') rebuilt += 1;
  });
  return {added, direct, rebuilt, same: pres.every((p, i) => p.innerHTML === html[i])};
}"""


@pytest.mark.parametrize("surface", list(SURFACES))
def test_the_text_is_unchanged_and_a_second_pass_adds_nothing(surface, browser, admin_live_server, world):
    """הטקסט של כל בלוק זהה למקור תו בתו, וכפתור ההעתקה — בלחיצה אמיתית — מעתיק בדיוק אותו. הרצה
    נוספת של העטיפה ישירות אינה מוסיפה עטיפה ואינה משנה את ה-HTML, והדגשה מחדש מאפס דרך
    ``highlightBlock`` בונה בדיוק אותו HTML. בספריית הסניפטים הבלוק כבר הפך לטבלת שורות ואין בו
    ``code``, ולכן שם נבדקת רק הקריאה הישירה."""
    with opened(surface, "fixed", browser, admin_live_server) as (page, root, _):
        if surface == "snippets":
            # הטבלה של ספריית הסניפטים: תא לכל שורה, ושורה ריקה הופכת לרווח (``snippets.js``).
            expected = [[line or " " for line in code.split("\n")] for _lang, code in SAMPLES]
            assert page.evaluate(CELLS_JS, root) == expected
        else:
            expected = [code + "\n" for _lang, code in SAMPLES] + [RTL_BLOCK + "\n"]
            assert page.evaluate(CODE_TEXTS_JS, root) == expected
            page.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=admin_live_server.base_url)
            for index, content in enumerate(expected):
                page.evaluate("() => navigator.clipboard.writeText('')")
                page.locator(f"{root} pre").nth(index).locator(".code-copy-btn").click()
                poll(page, """async (expected) => {
                  const text = await navigator.clipboard.readText();
                  return text === expected ? true : {ok: false, text};
                }""", f"{surface}: הכפתור של בלוק {index} העתיק בדיוק את המקור", content)
        rebuilt = 0 if surface == "snippets" else len(expected)
        assert page.evaluate(REPEAT_JS, root) == {"added": 0, "direct": True, "rebuilt": rebuilt, "same": True}, surface


#: התווית שכל צרכן רושם כשהדגשה של בלוק נכשלת — זו שחריגה מהעטיפה הייתה מקבלת בלי ה-``try`` שלה.
#: בספריית הסניפטים ה-``catch`` של ``applySyntaxHighlight`` שקט, ושם ההוכחה היא טבלת השורות: היא
#: נבנית אחרי ההדגשה, באותו ``try``, ו-``opened`` מחכה לה.
OUTER_LABELS = {
    "repo_browser": "hljs highlight failed",
    "repo_fallback": "enhance failed",
    "snippets": None,
}


@pytest.mark.parametrize("surface", list(SURFACES))
def test_a_failing_isolation_leaves_the_blocks_highlighted(surface, browser, admin_live_server, world):
    """חריגה בעטיפה היא באג, ולכן ``highlightBlock`` תופס אותה ברוחב — בגבול של בלוק אחד, ובשם שלה.
    הבלוק נשאר צבוע, עם כפתור ההעתקה שלו או טבלת השורות שלו (``opened`` מחכה להם), ובלי עטיפה — כמו
    לפני התיקון."""
    with opened(surface, "throwing", browser, admin_live_server) as (page, root, console):
        assert page.evaluate(f"() => document.querySelectorAll('{root} span[dir=\"rtl\"]').length") == 0
        assert any(t.startswith("isolateHebrewTokens failed") and "iso-probe" in t for t in console), console
        if OUTER_LABELS[surface]:
            assert not any(t.startswith(OUTER_LABELS[surface]) for t in console), console
