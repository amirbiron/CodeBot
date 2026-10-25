"""קוד בתוך בלוק עברי מוצג משמאל לימין — בכרומיום אמיתי, בשלושת המשטחים שמרנדרים Markdown.

**הבאג.** בלוק קוד שהתוכן שלו עברי מקבל ``direction: rtl`` (``applyRtlIfHebrew`` ב-
``webapp/static/js/utils/rtl-code.js``). כשבתוכו יש דוגמה עם גדרות משלה, הכיוון חל גם
עליה: ``` ```python ``` הוצג כ-``python``` ``, והשורה המוזחת התחילה משמאל לשורה שמעליה.
התיקון עוטף כל קטע שמתחיל בגדר פנימית ונגמר בגדר הסוגרת שלה ב-``.rtl-code-ltr``
(``wrapInnerFences``), אחרי ההדגשה, וכל שאר השורות נשארות כמו שהיו.

**שלושת המשטחים, בעמודים האמיתיים** (``TESTING-PATTERNS.md`` T1): תצוגת ה-Markdown
(``/md/<id>``), התצוגה החיה בעמוד העריכה (``/edit/<id>``, דרך הכפתור), ודפדפן הריפו
(``/repo/``). השרת הוא הוובאפ האמיתי (``admin_live_server``), שני הראשונים מול מונגו
אמיתי (``wired_mongo``), ובדפדפן הריפו רק ה-API של הריפו מזויף, כמו ב-
``tests/test_markdown_preview_css_browser.py``. בקשות לכל מארח אחר נקטעות.

**המדידה היא של הציור, לא של ה-DOM.** ``MEASURE_LINES_JS`` מקבץ תווים לשורות לפי
המקום שבו הדפדפן צייר אותם (``top``), ולכל שורה מחזיר איפה היא מתחילה ונגמרת ביחס
לתיבת התוכן של ה-``code``, ואם התו הראשון שלה בסדר הלוגי יושב בחצי השמאלי — כלומר אם
היא מוצגת משמאל לימין. אותה מדידה כמו ``measureLines`` ב-``scripts/check-editor.js``
של Markdown-Docs, שממנו התיקון הועבר.

**מה נבדק:** הקטע הפנימי הוא אלמנט אחד מגדר לגדר; שורת הגדר בסדר הנכון ומשמאל; שורה
מוזחת נשארת מוזחת; גדר שלא נסגרה נמשכת עד סוף הבלוק; ```` לא נסגרת ב-``` שבתוכה;
שורה ארוכה — ההתחלה גלויה מיד והסוף נגיש בגלילה; וכפתור ההעתקה מעתיק בדיוק את המקור.
**ומה לא נשבר:** השורות העבריות מימין, השורות הריקות סביב הקטע, הרשימה מ"המיפוי השלם
בייבוא ערכת VS Code", ובלוק עם שפה מוצהרת.

**מה לא נבדק כאן:** ספארי ופיירפוקס — יש כאן רק כרומיום. הפתקים — יש להם רנדרר משלהם,
והם PR נפרד. וכרטיסי החיפוש בתיעוד בעמוד הקבצים, שעוברים דרך אותו
``MarkdownLiveRenderer.enhance`` כמו דפדפן הריפו.

מדולג כשאין Chromium (וב-CI אין: ראו ``docs/testing.rst``).
"""

from __future__ import annotations

import contextlib
import json
from urllib.parse import unquote, urlsplit

import pytest
from bson import ObjectId

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import open_admin_page, poll

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

#: ``admin_live_server`` בונה session למשתמש 1, ולכן הקבצים שלו.
USER_ID = 1

#: טאבלט 12 אינץ' לרוחב, בפיקסלים לוגיים.
TABLET = {"width": 1280, "height": 800}

#: ארוכה מכל ``pre`` בשלושת המשטחים ברוחב הזה, גם בחצי המסך של התצוגה החיה.
LONG_LINE = (
    "const a_very_long_identifier_for_overflow_checks = someFunctionCall(argumentNumberOne, "
    "argumentNumberTwo, argumentNumberThree, argumentNumberFour, argumentNumberFive, END_OF_LINE);"
)

#: התוכן של כל בלוק — מה שבין הגדרות, כולל ירידת השורה האחרונה, בדיוק כמו
#: ש-markdown-it שם ב-``code``. זה גם מה שכפתור ההעתקה חייב להעתיק.
NESTED_PYTHON = "\n".join([
    "## כותרת בתוך הדוגמה", "", "```python", "def greet():", '    print("שלום")', "```", "",
    "סוף הדוגמה",
]) + "\n"
UNCLOSED_JS = "\n".join(["שורה ראשונה", "```js", "עדיין בתוך אותו בלוק"]) + "\n"
VSCODE_LIST = "\n".join([
    "**מה המייבא לוקח:** ב-`theme_parser_service.py` רק שלושה צבעים מגיעים:",
    "- `editor.background` → רקע המסמך (`--md-surface`)",
    "- `editor.foreground`",
]) + "\n"
LONG_INNER = "\n".join([
    "שורה עברית ראשונה בדוגמה", "שורה עברית שנייה בדוגמה", "שורה עברית שלישית בדוגמה",
    "```js", LONG_LINE, "```", "שורה עברית אחרונה בדוגמה",
]) + "\n"
FOUR_IN_FIVE = "\n".join([
    "טקסט עברי לפני הדוגמה", "````md", "```", "בתוך", "```", "````", "טקסט עברי אחרי הדוגמה",
]) + "\n"
DECLARED = "\n".join(["# הערה בעברית בתוך קוד פייתון, וגם היא ארוכה מספיק כדי להיות רוב", 'print("שלום")']) + "\n"

#: הבלוקים לפי סדרם במסמך: (מחרוזת שמזהה את ה-``pre``, גדר פותחת, תוכן).
BLOCKS = [
    ("print(", "````markdown", NESTED_PYTHON),
    ("שורה ראשונה", "```", UNCLOSED_JS),
    ("theme_parser_service", "```", VSCODE_LIST),
    ("END_OF_LINE", "````markdown", LONG_INNER),
    ("טקסט עברי לפני הדוגמה", "`````", FOUR_IN_FIVE),
    ("# הערה בעברית", "```python", DECLARED),
]


def _closing(fence: str) -> str:
    """הגדר הסוגרת: אותם גרשיים כמו בפותחת, בלי שם השפה."""
    return fence[: len(fence) - len(fence.lstrip("`"))]


MARKDOWN = "# קוד בתוך בלוק עברי\n\n" + "\n".join(
    f"{fence}\n{content}{_closing(fence)}\n" for _, fence, content in BLOCKS
)

#: איפה כל משטח מרנדר, ואיפה כפתור ההעתקה של בלוק.
#:
#: ``repo_fallback`` הוא דפדפן הריפו כש-``live-preview.js`` לא נטען: אז אין
#: ``MarkdownLiveRenderer``, והתצוגה עוברת ל-``renderMarkdownFallback`` ול-
#: ``enhanceMarkdownFallback`` ב-``repo-browser.js`` — הצרכן השלישי של ``wrapInnerFences``,
#: שבמסלול הרגיל אינו רץ בכלל.
ROOTS = {
    "md_preview": "#md-content",
    "live_preview": "[data-preview-canvas]",
    "repo_browser": "#markdown-preview-content",
    "repo_fallback": "#markdown-preview-content",
}

#: הבלוק שמכיל את ``match``, מתוך ה-``root`` של המשטח. משותף לכל הסקריפטים למטה.
FIND_PRE_JS = """
  const findPre = (root, match) => [...document.querySelectorAll(root + ' pre')]
    .filter((el) => (el.textContent || '').indexOf(match) >= 0)[0] || null;
"""

#: מוכן: ליד כל בלוק יש כפתור העתקה. בשלושת המשטחים הכפתור נוסף אחרי
#: ``wrapInnerFences`` — ב-``live-preview.js`` ו-``repo-browser.js`` באותה לולאה, וב-
#: ``md_preview.html`` ב-``addCopyButtons``, שרץ אחרי ההדגשה והעטיפה.
#:
#: **וגם: שום אנימציה אינה רצה על התוכן.** ב-``md_preview.html`` הבלוקים נכנסים באנימציה
#: (``#md-content > *``), ומדידה באמצעה נתנה מרווח שורות של 15px במקום 24px — כלומר תוכן
#: שעוד לא הגיע לגודלו. "רצה" ולא כל מה ש-``getAnimations()`` מחזיר, מאותה סיבה כמו
#: ``CENTER_JS`` ב-``tests/_browser_harness.py``.
READY_JS = """([root, count]) => {
  const pres = [...document.querySelectorAll(root + ' pre')];
  const highlighted = pres.filter((p) => {
    const c = p.querySelector('code');
    return c && c.dataset.highlighted === 'yes';
  });
  const buttons = pres.filter((p) => p.querySelector('.code-copy-btn')
    || (p.closest('.code-block') && p.closest('.code-block').querySelector('.md-copy-btn')));
  const container = document.querySelector(root);
  const moving = document.getAnimations().filter((a) => a.playState === 'running'
    && a.effect && a.effect.target && container && container.contains(a.effect.target)).length;
  return {ok: pres.length >= count && buttons.length >= count && moving === 0,
          pres: pres.length, highlighted: highlighted.length, buttons: buttons.length, moving};
}"""

#: משטחים שצובעים את הקוד — כולם. עד שהתלויות של עמוד העריכה עברו ל-
#: ``_live_preview_scripts.html``, ``utils/safe-highlight.js`` לא נטען שם, והתצוגה החיה
#: לא צבעה בכלל (נמדד: אפס בלוקים עם ``data-highlighted``). מאז גם שם העטיפה רצה על HTML
#: צבוע, ולכן גם שם נדרשת צביעה של כל הבלוקים.
HIGHLIGHTING_SURFACES = {"md_preview", "live_preview", "repo_browser", "repo_fallback"}

#: הטקסט של כל קטע ``.rtl-code-ltr`` בבלוק, וגם אם הבלוק בכלל עברי — בקרה: בלוק
#: שלא התהפך היה נותן "אין קטעים" מהסיבה הלא נכונה.
PARTS_JS = """([root, match]) => {
""" + FIND_PRE_JS + """
  const pre = findPre(root, match);
  if (!pre) return null;
  return {rtl: pre.classList.contains('rtl-code'),
          parts: [...pre.querySelectorAll('.rtl-code-ltr')].map((el) => el.textContent)};
}"""

#: גאומטריה של שורות, כפי שהדפדפן צייר אותן. ``gapL``/``gapR`` — המרחק בין קצות
#: השורה לקצות תיבת התוכן של ה-``code``; ``startX`` — היכן מצויר התו הלא-ריק הראשון
#: בסדר הלוגי; ``firstOnLeft`` — האם הוא בחצי השמאלי של השורה.
MEASURE_LINES_JS = """([root, match, needles]) => {
""" + FIND_PRE_JS + """
  const pre = findPre(root, match);
  if (!pre) return needles.map(() => ({found: false}));
  const code = pre.querySelector('code');
  const cs = getComputedStyle(code);
  const box = code.getBoundingClientRect();
  const left = box.left + parseFloat(cs.borderLeftWidth) + parseFloat(cs.paddingLeft);
  const right = box.right - parseFloat(cs.borderRightWidth) - parseFloat(cs.paddingRight);
  const rows = new Map();
  const walker = document.createTreeWalker(code, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    for (let i = 0; i < node.data.length; i++) {
      if (node.data[i] === '\\n') continue;
      const r = document.createRange();
      r.setStart(node, i); r.setEnd(node, i + 1);
      const rc = r.getBoundingClientRect();
      if (!rc.width) continue;
      const top = Math.round(rc.top);
      if (!rows.has(top)) rows.set(top, []);
      rows.get(top).push({c: node.data[i], rc});
    }
  }
  const lines = [...rows.entries()]
    .filter(([, chars]) => chars.some((x) => x.c.trim()))
    .map(([top, chars]) => ({top, chars, text: chars.map((x) => x.c).join('')}));
  return needles.map((needle) => {
    const line = lines.filter((l) => l.text.indexOf(needle) >= 0)[0];
    if (!line) return {found: false, needle};
    const minL = Math.min(...line.chars.map((x) => x.rc.left));
    const maxR = Math.max(...line.chars.map((x) => x.rc.right));
    const first = line.chars.filter((x) => x.c.trim())[0];
    return {found: true, needle, top: line.top,
            gapL: Math.round(minL - left), gapR: Math.round(right - maxR),
            startX: Math.round(first.rc.left - left),
            firstOnLeft: first.rc.left < (minL + maxR) / 2};
  });
}"""

#: שורת קוד ארוכה בקטע LTR בתוך pre RTL. ההתחלה גלויה מיד, כמו בכל בלוק קוד, והסוף
#: נגיש בגלילה — של ה-``pre``, של ה-``code`` או של הקטע, מה שגולל. בכיוון RTL
#: ``scrollLeft`` של כרומיום שלילי, ולכן נבדקים שני הקצוות.
REACH_JS = """([root, match]) => {
""" + FIND_PRE_JS + """
  const pre = findPre(root, match);
  if (!pre) return {found: false};
  const find = (needle) => {
    const w = document.createTreeWalker(pre, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = w.nextNode())) {
      const i = n.data.indexOf(needle);
      if (i >= 0) {
        return () => {
          const r = document.createRange();
          r.setStart(n, i); r.setEnd(n, i + needle.length);
          return r.getBoundingClientRect();
        };
      }
    }
    return null;
  };
  // ``` ולא ```js: ההדגשה יכולה לפצל את הגדר לכמה צמתי טקסט, והראשון שמכיל ```
  // בבלוק הזה הוא הגדר הפותחת של הקטע.
  const fence = find('```'), head = find('a_very_long_identifier'), tail = find('END_OF_LINE');
  if (!fence || !head || !tail) return {found: false};
  const box = pre.getBoundingClientRect();
  const visible = (rc) => rc.left >= box.left - 1 && rc.right <= box.right + 1;
  const initial = {fence: visible(fence()), head: visible(head()), tailHidden: !visible(tail())};
  const seen = {head: false, tail: false};
  const scrollers = [pre, pre.querySelector('code'), pre.querySelector('.rtl-code-ltr')].filter(Boolean);
  for (const el of scrollers) {
    for (const x of [0, -1e6, 1e6]) {
      el.scrollLeft = x;
      if (visible(head())) seen.head = true;
      if (visible(tail())) seen.tail = true;
    }
    el.scrollLeft = 0;
  }
  return {found: true, initial, seen};
}"""


def _insert(wired_mongo) -> str:
    """``wired_mongo`` מתחיל ממסד ריק בכל בדיקה, ולכן אין כאן ניקוי."""
    oid = ObjectId()
    wired_mongo.get_db().code_snippets.insert_one({
        "_id": oid, "user_id": USER_ID, "file_name": "inner_fences.md", "code": MARKDOWN,
        "programming_language": "markdown", "version": 1, "is_active": True,
    })
    return str(oid)


#: הקובץ שדפדפן הריפו מציג. ``DEFAULT_REPO_NAME`` ב-``webapp/routes/repo_browser.py``.
REPO = "CodeBot"
REPO_MD_PATH = "docs/inner_fences.md"


def _repo_api(route) -> None:
    """ה-API של הריפו מזויף, כמו ב-``tests/test_markdown_preview_css_browser.py``. כל השאר לשרת."""
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


@contextlib.contextmanager
def opened(surface: str, server, executable, wired_mongo=None, init_script: str = ""):
    """העמוד של המשטח, אחרי שכל הבלוקים קיבלו כפתור העתקה — **המקום היחיד שמרים דפדפן כאן**.

    מחזיר ``(page, root, console)``: ``console`` הוא כל הודעות הקונסול של הטעינה שבה
    הרינדור רץ. ``init_script`` רץ לפני כל סקריפט של העמוד.
    """
    console: list[str] = []
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(
                executable_path=executable,
                args=[f"--window-size={TABLET['width']},{TABLET['height']}"],
            )
        except PlaywrightError as exc:  # pragma: no cover - תלוי בסביבה
            pytest.skip(f"אין Chromium זמין: {exc}")
        try:
            if surface in ("repo_browser", "repo_fallback"):
                context = browser.new_context(viewport=TABLET, locale="he-IL")
                context.add_cookies([{
                    "name": "session", "value": server.session_cookie, "domain": "127.0.0.1", "path": "/",
                }])
                context.add_init_script(
                    "try{localStorage.setItem('repo-browser-markdown-preview','true');}catch(e){}"
                )
                if init_script:
                    context.add_init_script(init_script)
                page = context.new_page()
                page.on("console", lambda msg: console.append(msg.text))
                blocked = "/static/js/live-preview.js" if surface == "repo_fallback" else None
                page.route("**/*", lambda route: route.abort()
                           if blocked and urlsplit(route.request.url).path == blocked else _repo_api(route))
                page.goto(f"{server.base_url}/repo/#file={REPO_MD_PATH}", wait_until="load")
            else:
                file_id = _insert(wired_mongo)
                path = f"/md/{file_id}" if surface == "md_preview" else f"/edit/{file_id}"
                page, _touch = open_admin_page(browser, server, path, viewport=TABLET)
                page.on("console", lambda msg: console.append(msg.text))
                if init_script:
                    # ``open_admin_page`` כבר טען את העמוד, וסקריפט פתיחה חל רק מהטעינה הבאה
                    # — כמו ב-``tests/test_card_preview_copy_browser.py``.
                    page.add_init_script(init_script)
                    page.reload(wait_until="load")
                if surface == "live_preview":
                    page.click('[data-action="toggle-live-preview"]')
                    poll(page, "() => !!document.querySelector('[data-preview-status][data-state=\"ready\"]')",
                         "התצוגה החיה רונדרה")
            page.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=server.base_url)
            ready = poll(page, READY_JS, f"{surface}: כל הבלוקים קיבלו כפתור העתקה", [ROOTS[surface], len(BLOCKS)])
            if surface in HIGHLIGHTING_SURFACES:
                # בקרה: בלי צביעה, העטיפה לא נבדקת על HTML צבוע — וזה העיקר כאן.
                assert ready["highlighted"] == len(BLOCKS), f"{surface}: לא כל הבלוקים נצבעו: {ready}"
            if surface == "repo_fallback":
                # בקרה: אילו ``live-preview.js`` נטען בכל זאת, הבדיקה הייתה עוברת במסלול הרגיל.
                assert page.evaluate("() => typeof window.MarkdownLiveRenderer") == "undefined", (
                    "repo_fallback: MarkdownLiveRenderer נטען — המסלול שנבדק אינו enhanceMarkdownFallback"
                )
            yield page, ROOTS[surface], console
        finally:
            browser.close()


SURFACES = list(ROOTS)


@pytest.fixture(params=SURFACES)
def surface(request, admin_live_server, chromium_executable):
    """העמוד של כל משטח. רק שניים מהם צריכים מסד, ולכן ``wired_mongo`` נשלף רק להם —
    דפדפן הריפו רץ גם בלי ``NOTE_FONTS_TEST_MONGO_URI``."""
    mongo = request.getfixturevalue("wired_mongo") if request.param in ("md_preview", "live_preview") else None
    with opened(request.param, admin_live_server, chromium_executable, mongo) as (page, root, _console):
        yield request.param, page, root


def _parts(page, root, match):
    found = page.evaluate(PARTS_JS, [root, match])
    assert found is not None, f"לא נמצא הבלוק עם {match!r}"
    assert found["rtl"], f"הבלוק עם {match!r} לא זוהה כעברי — כל טענה עליו הייתה נבדקת על בלוק אחר"
    return found["parts"]


def _lines(page, root, match, needles):
    result = page.evaluate(MEASURE_LINES_JS, [root, match, needles])
    for line in result:
        assert line["found"], f"לא נמדדה שורה עם {line.get('needle')!r}"
    return result


def test_inner_code_is_one_left_to_right_segment_from_fence_to_fence(surface):
    """הקטע הפנימי הוא אלמנט אחד, מהגדר הפותחת ועד הסוגרת כולל שתיהן; שורת הגדר בסדר
    הנכון ומשמאל, ושורה מוזחת נשארת מוזחת ימינה מהשורה שמעליה."""
    name, page, root = surface

    assert _parts(page, root, "print(") == ['```python\ndef greet():\n    print("שלום")\n```\n'], name
    fence, define, call = _lines(page, root, "print(", ["```python", "def greet", "print("])
    assert fence["firstOnLeft"] and fence["gapL"] <= 1, f"{name}: ```python לא בסדר הנכון או לא משמאל: {fence}"
    assert define["gapL"] <= 1, f"{name}: def לא מיושר לשמאל: {define}"
    assert call["startX"] > define["startX"] + 10, (
        f"{name}: השורה המוזחת לא מוזחת ימינה — def ב-{define['startX']}px, print ב-{call['startX']}px"
    )

    # גדר שלא נסגרה נמשכת עד סוף הבלוק — כולל ירידת השורה האחרונה של התוכן.
    assert _parts(page, root, "שורה ראשונה") == ["```js\nעדיין בתוך אותו בלוק\n"], name
    js_fence, js_rest = _lines(page, root, "שורה ראשונה", ["```js", "עדיין בתוך אותו בלוק"])
    assert js_fence["firstOnLeft"] and js_fence["gapL"] <= 1, f"{name}: ```js: {js_fence}"
    assert js_rest["gapL"] <= 1, f"{name}: שורת התוכן של הקטע לא משמאל: {js_rest}"

    # ```` אינה נסגרת ב-``` שבתוכה (CommonMark 0.31.2, דוגמה 124).
    assert _parts(page, root, "טקסט עברי לפני הדוגמה") == ["````md\n```\nבתוך\n```\n````\n"], name


def test_the_rest_of_the_block_is_unchanged(surface):
    """מה שאינו קוד הולך עם כיוון הבלוק — לפני התיקון ואחריו.

    השורות העבריות מימין, השורות הריקות סביב הקטע נשמרות ולא נוספת אחת, הרשימה
    שפריטיה מתחילים במזהה לועזי נשארת כולה מימין ובלי אף קטע, ובלוק עם שפה מוצהרת
    לא נוגעים בו."""
    name, page, root = surface

    head, fence, call, end = _lines(page, root, "print(",
                                    ["כותרת בתוך הדוגמה", "```python", "print(", "סוף הדוגמה"])
    for line in (head, end):
        assert not line["firstOnLeft"] and line["gapR"] <= 1, f"{name}: שורה עברית לא מימין: {line}"
    define = _lines(page, root, "print(", ["def greet"])[0]
    pitch = call["top"] - define["top"]
    assert pitch > 0
    # כותרת ← שורה ריקה ← גדר: שתי שורות. print ← ``` ← שורה ריקה ← סוף: שלוש.
    assert abs((fence["top"] - head["top"]) - 2 * pitch) <= 2, (
        f"{name}: בין הכותרת לגדר {fence['top'] - head['top']}px, שורה {pitch}px"
    )
    assert abs((end["top"] - call["top"]) - 3 * pitch) <= 2, (
        f"{name}: בין print לסוף {end['top'] - call['top']}px, שורה {pitch}px"
    )

    before = _lines(page, root, "שורה ראשונה", ["שורה ראשונה"])[0]
    assert not before["firstOnLeft"] and before["gapR"] <= 1, f"{name}: השורה שלפני הגדר: {before}"
    after = _lines(page, root, "טקסט עברי לפני הדוגמה", ["טקסט עברי אחרי הדוגמה"])[0]
    assert not after["firstOnLeft"] and after["gapR"] <= 1, f"{name}: השורה שאחרי הקטע לא חזרה לימין: {after}"

    listed = _lines(page, root, "theme_parser_service",
                    ["מה המייבא לוקח", "editor.background", "editor.foreground"])
    for line in listed:
        assert not line["firstOnLeft"] and line["gapR"] <= 1, f"{name}: פריט ברשימה קפץ שמאלה: {line}"
    assert _parts(page, root, "theme_parser_service") == [], f"{name}: בלוק בלי גדר פנימית קיבל קטע"

    declared = page.evaluate(PARTS_JS, [root, "# הערה בעברית"])
    assert declared == {"rtl": False, "parts": []}, f"{name}: בלוק python נגע: {declared}"


def test_a_long_inner_line_starts_visible_and_its_end_is_reachable(surface):
    """בלי גלילה משלו, הקטע חותך: הסוף של שורה ארוכה גולש לצד שאין אליו גלילה."""
    name, page, root = surface

    assert _parts(page, root, "END_OF_LINE") == ["```js\n" + LONG_LINE + "\n```\n"], name
    reach = page.evaluate(REACH_JS, [root, "END_OF_LINE"])
    assert reach["found"], name
    # בקרה: השורה באמת ארוכה מה-``pre``. אחרת "הסוף נגיש" היה נכון בלי גלילה בכלל.
    assert reach["initial"]["tailHidden"], f"{name}: השורה לא ארוכה מהבלוק — הבדיקה לא מודדת כלום: {reach}"
    assert reach["initial"]["fence"] and reach["initial"]["head"], f"{name}: תחילת הקטע לא גלויה: {reach}"
    assert reach["seen"]["tail"], f"{name}: סוף השורה לא נגיש בשום גלילה: {reach}"


def test_the_copy_button_copies_exactly_the_source(surface):
    """``textContent`` של הבלוקים זהה למקור תו בתו, וכפתור ההעתקה — בלחיצה אמיתית —
    מעתיק בדיוק אותו. ב-``md_preview.html`` הכפתור קרא ``innerText``, שמוסיף ירידת שורה
    בכל גבול של אלמנט בלוק, ולכן שורה ריקה לפני הקטע ואחריו."""
    name, page, root = surface

    for match, _fence, content in BLOCKS:
        page.evaluate("""([root, match]) => {
""" + FIND_PRE_JS + """
          document.querySelectorAll('[data-test-copy]').forEach((el) => el.removeAttribute('data-test-copy'));
          const pre = findPre(root, match);
          const btn = pre.querySelector('.code-copy-btn')
            || pre.closest('.code-block').querySelector('.md-copy-btn');
          btn.setAttribute('data-test-copy', '1');
          btn.scrollIntoView({block: 'center'});
        }""", [root, match])
        page.evaluate("() => navigator.clipboard.writeText('')")
        page.click("[data-test-copy]")
        poll(page, CLIPBOARD_IS_JS, f"{name}: הכפתור של הבלוק עם {match!r} העתיק בדיוק את המקור", content)

    if name == "md_preview":
        # "העתק כמארקדאון" מעתיק את קובץ המקור (``copyMarkdownSource``), לא את ה-DOM —
        # ולכן העטיפה אינה יכולה לשנות אותו. נבדק כאן כי זה חלק מאותה הבטחה למשתמש.
        page.evaluate("() => navigator.clipboard.writeText('')")
        page.click("#mdCopySourceBtn")
        poll(page, CLIPBOARD_IS_JS, "md_preview: העתק כמארקדאון העתיק בדיוק את הקובץ", MARKDOWN)


CLIPBOARD_IS_JS = """async (expected) => {
  const text = await navigator.clipboard.readText();
  return text === expected ? true : {ok: false, text};
}"""


#: ``wrapInnerFences`` שזורקת. ``rtl-code.js`` מציב ``window.RtlCode = {...}``, והמציב
#: כאן מחליף בו את הפונקציה לפני שאיש קרא לה.
THROWING_WRAP_JS = """(() => {
  let real;
  Object.defineProperty(window, 'RtlCode', {
    configurable: true,
    get() { return real; },
    set(value) { value.wrapInnerFences = () => { throw new Error('wrap-probe'); }; real = value; },
  });
})();"""

#: התווית שכל צרכן רושם כשהעטיפה נכשלת, והתווית של ה-catch שמתחתיה — זו שחריגה
#: מהעטיפה הייתה מקבלת בלי ה-try שלה.
WRAP_FAILURE_LABELS = {
    "md_preview": ("md_preview: wrapInnerFences failed", "Markdown preview failed"),
    "live_preview": ("wrapInnerFences failed", "hljs highlight failed"),
    "repo_browser": ("wrapInnerFences failed", "hljs highlight failed"),
    "repo_fallback": ("wrapInnerFences failed", "enhance failed"),
}


@pytest.mark.parametrize("name", SURFACES)
def test_a_failing_wrap_leaves_the_page_rendered(name, request, admin_live_server, chromium_executable):
    """חריגה בעטיפה היא באג, ולכן כל צרכן תופס אותה ברוחב — אבל רק בגבול של בלוק אחד.

    הבלוק נשאר כמו לפני התיקון, כפתור ההעתקה שלו קיים (``opened`` מחכה לכפתור ליד כל
    בלוק), שאר העמוד מרונדר, והחריגה נרשמת בתווית של העטיפה — לא בתווית של ה-catch
    שמתחתיה. ב-``md_preview.html`` ה-catch ההוא מחליף את כל המסמך בהודעת שגיאה.
    """
    mongo = request.getfixturevalue("wired_mongo") if name in ("md_preview", "live_preview") else None
    own, outer = WRAP_FAILURE_LABELS[name]
    with opened(name, admin_live_server, chromium_executable, mongo, THROWING_WRAP_JS) as (page, root, console):
        # בקרה: העטיפה באמת נכשלה — אחרת הבדיקה עוברת על המסלול הרגיל.
        assert page.evaluate(PARTS_JS, [root, "print("])["parts"] == [], f"{name}: העטיפה לא נכשלה"
        assert any(text.startswith(own) and "wrap-probe" in text for text in console), (
            f"{name}: לא נרשם {own!r}: {console}"
        )
        assert not any(text.startswith(outer) for text in console), f"{name}: החריגה הגיעה ל-{outer!r}"
        if name == "md_preview":
            assert page.evaluate("() => !document.querySelector('#md-content .alert-error')"), (
                "md_preview: המסמך הוחלף בהודעת שגיאה"
            )
