"""הייצוא ל-HTML מעוצב מהעורך הציבורי, בדפדפן אמיתי: מהלחיצה בעמוד ועד הקובץ שירד, כשהוא נפתח לבד ובלי רשת.

**למה בדפדפן.** המסמך מרונדר בדפדפן ומוכנס לשלד שם (``markdown-editor-export.js``), ה-CSP שבתוך הקובץ נאכף רק
בדפדפן, וכל מה שהקובץ צריך — העיצוב, KaTeX, Mermaid — נראה רק כשהוא נפתח. מה שהשרת מגיש נבדק ב-
``tests/test_markdown_editor_export.py``.

**איך העמוד מוגש.** כמו ב-``tests/test_markdown_editor_browser.py``: כל בקשה עוברת דרך ``route`` של Playwright ל-
``test_client`` של Flask, ובקשה לאתר חיצוני נחסמת. ההבדל: כאן גם כותרות ה-CSP וה-ETag עוברות לדפדפן, כי העמוד והשלד
צריכים לעבוד תחת המדיניות האמיתית. לכל הקשר דפדפן כתובת IP משלו (``X-Forwarded-For``), כי השלד כפוף למגבלת הקצב
הגורפת, והאחסון שלה משותף לכל הטסטים בתהליך.

**מה נבדק כאן ולא נראה בקוד:** שהטקסט לא יוצא מהדפדפן; שהקובץ עובד בלי רשת, בשתי הערכות, רכיב-רכיב; שהייצוא
עובד גם כשהתצוגה החיה כבויה ועל תוכן בקיפול סגור; שאף ניסיון הזרקה לא מריץ קוד בקובץ; שכפתור ההעתקה מעתיק בלוק
קוד בעברית בלי שורות שלא היו בו; ושני רינדורים במקביל לא מערבבים ערכות Mermaid ולא חולקים מזהים.

מדולג כשאין Chromium (``chromium_executable`` ב-``tests/conftest.py``).
"""

from __future__ import annotations

import itertools
import json
from urllib.parse import urlsplit

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

HOST = "ck.test"
URL = f"http://{HOST}/markdown-editor"
DRAFT_KEY = "markdownEditorDraft.v1"
FORWARDED_HEADERS = ("content-type", "content-security-policy", "etag", "cache-control")

FAKE_THEME = {
    "id": "everforest_dark",
    "name": "Everforest Dark",
    "description": "",
    "colors": {"--bg-primary": "#2d353b"},
    "syntax_css": "",
    "syntax_colors": {},
    "is_featured": False,
}

#: מילה שאין בשום מקום אחר — אם היא מופיעה בבקשה לשרת, הטקסט יצא מהדפדפן.
SECRET_WORD = "סודי-ביותר-7f3a"

#: תוכן בתוך קיפול סגור: תרשים ונוסחה, שהמנוע מרנדר גם כשהם מוסתרים.
HIDDEN_DOC = f"""# {SECRET_WORD}

::: details מוסתר
```mermaid
graph TD
  A[התחלה] --> B[סוף]
```

$$\\int_0^1 x^2 dx$$
:::
"""

#: ניסיונות הזרקה: HTML גולמי, קישור javascript:, ‏\\href ב-KaTeX, ותווית ו-click ב-Mermaid.
INJECTION_DOC = """# הזרקות

<img src=x onerror="alert(1)"><script>alert(2)</script>

[קישור](javascript:alert(3))

$\\href{javascript:alert(4)}{לחץ}$

```mermaid
graph TD
  A["<img src=x onerror=alert(5)>"] --> B
  click A "javascript:alert(6)"
```
"""

PLAIN_DOC = "# בלי נוסחאות\n\nרק טקסט, ו-`קוד` בשורה.\n"

#: בלוק קוד בעברית, ובתוכו קטע קוד משמאל לימין (``wrapInnerFences`` ב-``rtl-code.js``).
HEBREW_BLOCK_SOURCE = "טקסט בעברית לפני הקוד\n```python\nx = 1\nprint(x)\n```\nטקסט בעברית אחרי הקוד"
HEBREW_BLOCK_DOC = f"# העתקה\n\n````\n{HEBREW_BLOCK_SOURCE}\n````\n"

_ADDRESSES = itertools.count(1)

#: מה שנמדד בקובץ שירד: כל רכיב, והמצב שממנו אפשר לדעת שהוא עוצב.
PROBE_FILE = r"""
() => {
  const root = document.querySelector('main.container');
  const cs = (el) => getComputedStyle(el);
  const out = { header: !!document.querySelector('body > header'), footer: document.querySelector('footer').innerText };

  const alerts = [...root.querySelectorAll('.admonition')];
  out.alerts = { count: alerts.length,
    styled: alerts.filter((a) => parseFloat(cs(a).borderInlineStartWidth) >= 4 && cs(a).backgroundColor !== 'rgba(0, 0, 0, 0)').length };

  let tok = 0, colored = 0;
  root.querySelectorAll('pre code.hljs').forEach((code) => {
    const base = cs(code).color;
    const walker = document.createTreeWalker(code, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = walker.nextNode())) {
      const len = n.textContent.replace(/\s+/g, '').length;
      const el = n.parentElement;
      if (!len || el === code) continue;
      tok += len;
      if (cs(el).color !== base) colored += len;
    }
  });
  out.code = { pres: root.querySelectorAll('pre').length, tokenChars: tok, coloredPct: tok ? Math.round(100 * colored / tok) : 0,
    copyButtonsPerPre: [...root.querySelectorAll('pre')].map((p) => p.querySelectorAll('.copy-btn').length),
    themeCopyButtons: root.querySelectorAll('.md-copy-btn').length,
    headerLabels: [...root.querySelectorAll('.md-code-header')].map((h) => h.textContent) };

  out.alignedCells = [...root.querySelectorAll('td[style]')].map((c) => cs(c).textAlign);
  out.nestedDepth = Math.max(0, ...[...root.querySelectorAll('li')].map((li) => { let d = 0, p = li; while ((p = p.parentElement && p.parentElement.closest('li'))) d++; return d; }));
  const boxes = [...root.querySelectorAll('input[type=checkbox]')];
  out.tasks = { count: boxes.length, checked: boxes.filter((b) => b.checked).length, disabled: boxes.filter((b) => b.disabled).length,
    bullets: boxes.filter((b) => cs(b.closest('li')).listStyleType !== 'none').length };
  const mark = root.querySelector('mark');
  out.markBg = mark ? cs(mark).backgroundColor : null;
  const strike = root.querySelector('s');
  out.strike = strike ? cs(strike).textDecorationLine : null;
  out.h5h6 = root.querySelectorAll('h5, h6').length;
  const internal = [...root.querySelectorAll('a[href^="#"]')];
  out.anchors = { internal: internal.length, broken: internal.filter((a) => !document.getElementById(decodeURIComponent(a.getAttribute('href').slice(1)))).length };
  const k = root.querySelector('.katex');
  out.katex = { count: root.querySelectorAll('.katex').length,
    mathmlShown: k ? cs(k.querySelector('.katex-mathml')).position !== 'absolute' : null,
    font: k && k.querySelector('.mord') ? cs(k.querySelector('.mord')).fontFamily : null,
    fontsLoaded: [...document.fonts].filter((f) => f.family.includes('KaTeX') && f.status === 'loaded').length,
    pageScrollsSideways: document.scrollingElement.scrollWidth > document.scrollingElement.clientWidth };
  const rect = root.querySelector('.mermaid-diagram .node rect, .mermaid-diagram .node polygon');
  out.mermaid = { svgs: root.querySelectorAll('.mermaid-diagram svg').length, nodeFill: rect ? cs(rect).fill : null };
  out.internal = { sourceLines: root.querySelectorAll('[data-source-line]').length, highlighted: root.querySelectorAll('[data-highlighted]').length };
  return out;
}
"""

#: הסימנים שקוד הזרקה רץ: סקריפט שאינו סקריפט ההעתקה, מאפיין on*, או כתובת javascript:.
PROBE_INJECTION = r"""
() => ({
  scripts: [...document.scripts].filter((s) => !s.textContent.includes("copy-btn")).length,
  onAttrs: [...document.querySelectorAll('*')].filter((e) => [...e.attributes].some((a) => /^on/i.test(a.name))).length,
  javascriptUrls: [...document.querySelectorAll('[href],[src]')].filter((e) => /^\s*javascript:/i.test(e.getAttribute('href') || e.getAttribute('src') || '')).length,
  rawHtmlShownAsText: document.body.innerText.includes('<img src=x onerror'),
})
"""


@pytest.fixture(scope="module")
def browser(chromium_executable):
    import webapp.app as wa

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            wa,
            "_get_shared_theme_cached",
            lambda theme_id: dict(FAKE_THEME) if theme_id == "everforest_dark" else None,
        )
        with sync_playwright() as pw:
            try:
                b = (
                    pw.chromium.launch(executable_path=chromium_executable)
                    if chromium_executable
                    else pw.chromium.launch()
                )
            except Exception as exc:  # כשל חולף בהרמה, אחרי שהשער כבר אמר שיש דפדפן
                pytest.skip(f"Chromium לא עלה: {exc}")
            try:
                yield b, wa.app
            finally:
                b.close()


class Session:
    """הקשר דפדפן אחד מול העמוד: הבקשות שנשלחו (עם הגוף), השגיאות, והדף."""

    def __init__(self, browser, *, draft=None):
        b, app = browser
        self.browser = b
        self.requests: list[tuple[str, str, bytes]] = []
        self.errors: list[str] = []
        self.dialogs: list[str] = []
        client = app.test_client()
        client.environ_base["HTTP_X_FORWARDED_FOR"] = f"203.0.113.{next(_ADDRESSES) % 250 + 1}"
        self.ctx = b.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True)
        if draft is not None:
            payload = json.dumps({"code": draft, "savedAt": 1})
            self.ctx.add_init_script(f"localStorage.setItem({json.dumps(DRAFT_KEY)}, {json.dumps(payload)});")

        def handle(route, request):
            u = urlsplit(request.url)
            if u.hostname != HOST:
                return route.abort()
            target = u.path + (f"?{u.query}" if u.query else "")
            self.requests.append((request.method, target, request.post_data_buffer or b""))
            headers = {"Content-Type": request.headers.get("content-type", "")}
            if request.headers.get("if-none-match"):
                headers["If-None-Match"] = request.headers["if-none-match"]
            r = client.open(target, method=request.method, data=request.post_data_buffer, headers=headers)
            route.fulfill(
                status=r.status_code,
                body=r.data,
                headers={k: v for k, v in r.headers.items() if k.lower() in FORWARDED_HEADERS},
            )

        self.ctx.route("**/*", handle)
        self.page = self.ctx.new_page()
        self.page.on("pageerror", lambda exc: self.errors.append(str(exc)))
        self.page.on("dialog", lambda d: (self.dialogs.append(d.message), d.dismiss()))
        self.page.goto(URL)
        self.page.wait_for_function(
            "document.querySelector('[data-preview-status]').dataset.state === 'ready'", timeout=60000
        )

    def choose(self, theme_id):
        if self.page.get_attribute("[data-md-editor-export-toggle]", "aria-expanded") != "true":
            self.page.click("[data-md-editor-export-toggle]")
        self.page.check(f"input[name=mdEditorExportTheme][value={theme_id}]")

    def download(self, theme_id, tmp_path):
        self.choose(theme_id)
        with self.page.expect_download(timeout=60000) as info:
            self.page.click("[data-md-editor-export-action=download]")
        path = tmp_path / f"{theme_id}.html"
        info.value.save_as(path)
        return info.value, path

    def close(self):
        self.ctx.close()


def open_file(browser, path):
    """פותח קובץ שירד, לבד, בהקשר חדש שבו כל בקשה שאינה לקובץ מקומי נחסמת ונרשמת."""
    b, _app = browser
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    attempts: list[str] = []
    dialogs: list[str] = []

    def block(route, request):
        if request.url.startswith("file://"):
            return route.continue_()
        attempts.append(request.url)
        return route.abort()

    ctx.route("**/*", block)
    page = ctx.new_page()
    page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    page.goto(path.as_uri())
    page.wait_for_function("document.readyState === 'complete'")
    return ctx, page, attempts, dialogs


@pytest.fixture
def session(browser):
    sessions: list[Session] = []

    def make(**kwargs):
        s = Session(browser, **kwargs)
        sessions.append(s)
        return s

    yield make
    for s in sessions:
        s.close()


# ---------------------------------------------------------------------------
# הקובץ, רכיב-רכיב
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("theme_id, light", [("pen-paper-coffee", True), ("morass", False)])
def test_the_downloaded_file_works_on_its_own_without_network(browser, session, tmp_path, theme_id, light):
    s = session()
    download, path = s.download(theme_id, tmp_path)
    assert download.suggested_filename == "document.html"
    assert s.errors == []

    ctx, page, attempts, dialogs = open_file(browser, path)
    try:
        r = page.evaluate(PROBE_FILE)
    finally:
        ctx.close()

    assert attempts == [], attempts  # בטקסט ההדגמה אין תמונה מבחוץ: כל מה שהקובץ צריך בתוכו
    assert dialogs == []
    assert r["header"] is False
    assert "Code Keeper" in r["footer"] and "Bot" not in r["footer"]
    assert r["alerts"]["count"] == 15 and r["alerts"]["styled"] == 15, r["alerts"]
    assert r["code"]["tokenChars"] > 300 and r["code"]["coloredPct"] >= 90, r["code"]
    assert r["code"]["copyButtonsPerPre"] == [1] * r["code"]["pres"], r["code"]
    assert r["code"]["themeCopyButtons"] == 0
    assert "Python" in r["code"]["headerLabels"]
    assert {"center", "left"} <= set(r["alignedCells"]), r["alignedCells"]
    assert r["nestedDepth"] == 2
    assert r["tasks"] == {"count": 11, "checked": 6, "disabled": 11, "bullets": 0}, r["tasks"]
    assert r["markBg"] not in (None, "rgb(255, 255, 0)"), r["markBg"]  # לא הצהוב של הדפדפן
    assert r["strike"] == "line-through"
    assert r["h5h6"] == 0
    assert r["anchors"]["internal"] == 10 and r["anchors"]["broken"] == 0, r["anchors"]
    assert r["katex"]["count"] == 5 and r["katex"]["mathmlShown"] is False, r["katex"]
    assert r["katex"]["font"] == "KaTeX_Math" and r["katex"]["fontsLoaded"] > 0, r["katex"]
    assert r["katex"]["pageScrollsSideways"] is False
    assert r["mermaid"]["svgs"] == 3
    # הערכה של Mermaid היא של הקובץ: הבהירה (``default``) צובעת צמתים ב-#ECECFF
    assert (r["mermaid"]["nodeFill"] == "rgb(236, 236, 255)") is light, r["mermaid"]
    assert r["internal"] == {"sourceLines": 0, "highlighted": 0}


def test_a_document_without_math_does_not_carry_katex(browser, session, tmp_path):
    s = session(draft=PLAIN_DOC)
    _download, path = s.download("morass", tmp_path)
    html = path.read_text(encoding="utf-8")

    assert "@font-face" not in html and ".katex" not in html
    skeleton_requests = [t for m, t, _ in s.requests if "export-skeleton" in t]
    assert skeleton_requests and all("math=" not in t for t in skeleton_requests), skeleton_requests


# ---------------------------------------------------------------------------
# הטקסט לא יוצא מהדפדפן
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["download", "preview"])
def test_exporting_sends_nothing_of_the_text(session, tmp_path, mode):
    s = session(draft=HIDDEN_DOC)
    before = len(s.requests)
    if mode == "download":
        s.download("pen-paper-coffee", tmp_path)
    else:
        s.choose("pen-paper-coffee")
        with s.ctx.expect_page(timeout=60000) as info:
            s.page.click("[data-md-editor-export-action=preview]")
        tab = info.value
        tab.wait_for_url(lambda u: u.startswith("blob:"), wait_until="commit", timeout=60000)
    during = s.requests[before:]

    # העמוד עצמו מבקש דברים ברקע (favicon, למשל); מה שנבדק הוא שאף בקשה לא נושאת את הטקסט, שאין בקשה שאינה
    # GET, ושבקשת ה-API היחידה היא השלד
    api = [target for _m, target, _b in during if target.startswith("/api/")]
    assert api, "בקרה: הייצוא לא שלח אפילו את בקשת השלד"
    assert all(target.startswith("/api/markdown-editor/export-skeleton/") for target in api), api
    assert all(method == "GET" for method, _t, _b in during), during
    assert not any(SECRET_WORD in target or SECRET_WORD.encode() in body for _m, target, body in during)


# ---------------------------------------------------------------------------
# התצוגה כבויה, ותוכן מוסתר
# ---------------------------------------------------------------------------


def test_the_export_works_when_the_live_preview_is_off(browser, session, tmp_path):
    s = session(draft=HIDDEN_DOC)
    s.page.click('[data-action="toggle-live-preview"]')
    # בקרה: התצוגה באמת כבויה, ומוצג בה רק טקסט ההסבר
    assert SECRET_WORD not in s.page.inner_text("[data-preview-canvas]")

    _download, path = s.download("morass", tmp_path)
    assert "<h1" in path.read_text(encoding="utf-8")
    ctx, page, _attempts, _dialogs = open_file(browser, path)
    try:
        assert SECRET_WORD in page.inner_text("main.container h1")
    finally:
        ctx.close()


def test_content_inside_a_closed_details_is_rendered(browser, session, tmp_path):
    s = session(draft=HIDDEN_DOC)
    _download, path = s.download("pen-paper-coffee", tmp_path)
    ctx, page, _attempts, _dialogs = open_file(browser, path)
    try:
        r = page.evaluate(
            """() => { const d = document.querySelector('main.container details');
              return { open: d.open, svgs: d.querySelectorAll('svg[id^="mmd_"]').length,
                       labels: [...d.querySelectorAll('.nodeLabel')].map((l) => l.textContent),
                       katex: d.querySelectorAll('.katex').length }; }"""
        )
    finally:
        ctx.close()

    assert r["open"] is False
    assert r["svgs"] == 1 and r["labels"] == ["התחלה", "סוף"], r
    assert r["katex"] == 1


# ---------------------------------------------------------------------------
# אבטחה: הקובץ לא מריץ שום דבר מהמסמך
# ---------------------------------------------------------------------------


def test_injection_attempts_run_nothing_in_the_file(browser, session, tmp_path):
    s = session(draft=INJECTION_DOC)
    _download, path = s.download("pen-paper-coffee", tmp_path)
    assert s.dialogs == []

    ctx, page, _attempts, dialogs = open_file(browser, path)
    try:
        page.wait_for_timeout(300)
        r = page.evaluate(PROBE_INJECTION)
    finally:
        ctx.close()

    assert dialogs == []
    assert r == {"scripts": 0, "onAttrs": 0, "javascriptUrls": 0, "rawHtmlShownAsText": True}, r


def test_the_csp_inside_the_file_blocks_a_script_that_got_in(browser, session, tmp_path):
    """הגנה נוספת, למקרה שמשהו עקף את המנוע: סקריפט שנכנס לקובץ אחרי הייצוא לא רץ, וסקריפט ההעתקה כן."""
    s = session(draft=HEBREW_BLOCK_DOC)
    _download, path = s.download("morass", tmp_path)
    html = path.read_text(encoding="utf-8")
    planted = html.replace("</main>", "<script>window.__planted = 1;</script></main>", 1)
    assert planted != html
    path.write_text(planted, encoding="utf-8")

    ctx, page, _attempts, _dialogs = open_file(browser, path)
    try:
        assert page.evaluate("window.__planted") is None
        # בקרה: סקריפטים כן רצים בקובץ — סקריפט ההעתקה הוסיף את הכפתור
        assert page.evaluate("document.querySelectorAll('pre .copy-btn').length") == 1
    finally:
        ctx.close()


# ---------------------------------------------------------------------------
# "הצג", והעתקה
# ---------------------------------------------------------------------------


def test_preview_opens_the_file_in_a_new_tab_with_the_document_title(session):
    s = session()
    s.choose("pen-paper-coffee")
    with s.ctx.expect_page(timeout=60000) as info:
        s.page.click("[data-md-editor-export-action=preview]")
    tab = info.value
    tab.wait_for_url(lambda u: u.startswith("blob:"), wait_until="commit", timeout=60000)
    tab.wait_for_function("document.readyState === 'complete' && document.querySelector('main.container h1')")

    assert tab.title().startswith("ברוך הבא לעורך מארקדאון")
    # סקריפט ההעתקה רץ בטאב, תחת ה-CSP של העמוד ושל הקובץ יחד
    assert tab.evaluate("document.querySelectorAll('pre .copy-btn').length") == tab.evaluate(
        "document.querySelectorAll('main.container pre').length"
    ) > 0
    assert s.page.evaluate("document.querySelector('[data-md-editor-export-action=preview]').disabled") is False


def test_the_copy_button_copies_a_hebrew_block_without_added_lines(session):
    """הטקסט שסקריפט ההעתקה שולח ללוח. הלוח עצמו מוחלף ברשם: העמוד מוגש ב-http, שאינו הקשר מאובטח, ושם
    ``navigator.clipboard`` לא קיים. מה שנבדק הוא ההחלטה של הסקריפט איזה טקסט להעתיק — היא אמיתית."""
    s = session(draft=HEBREW_BLOCK_DOC)
    s.choose("pen-paper-coffee")
    with s.ctx.expect_page(timeout=60000) as info:
        s.page.click("[data-md-editor-export-action=preview]")
    tab = info.value
    tab.wait_for_url(lambda u: u.startswith("blob:"), wait_until="commit", timeout=60000)
    tab.wait_for_function("document.querySelector('pre.rtl-code .copy-btn')")
    # בקרה: הקטע הפנימי באמת עטוף באלמנט בלוק — המצב שבו innerText מוסיף שורות
    assert tab.evaluate("getComputedStyle(document.querySelector('pre.rtl-code .rtl-code-ltr')).display") == "block"
    tab.evaluate(
        """() => Object.defineProperty(navigator, 'clipboard', { configurable: true,
             value: { writeText: (text) => { window.__copied = text; return Promise.resolve(); } } })"""
    )

    tab.click("pre.rtl-code .copy-btn", force=True)
    tab.wait_for_function("window.__copied !== undefined")
    assert tab.evaluate("window.__copied") == HEBREW_BLOCK_SOURCE


# ---------------------------------------------------------------------------
# שני רינדורים במקביל
# ---------------------------------------------------------------------------


def test_two_exports_at_once_keep_their_mermaid_theme_and_their_own_ids(session):
    s = session()
    r = s.page.evaluate(
        """async () => {
          const text = '```mermaid\\ngraph TD\\n  A --> B\\n```\\n\\n```mermaid\\ngraph TD\\n  C --> D\\n```\\n';
          const [light, dark] = await Promise.all([
            window.MarkdownLiveRenderer.renderForExport(text, { mermaidTheme: 'default' }),
            window.MarkdownLiveRenderer.renderForExport(text, { mermaidTheme: 'dark' }),
          ]);
          document.body.append(light, dark);
          // מלבן אחד לכל צומת: ב-Mermaid 11 יש בצומת שני מלבנים, והצבע של הצומת הוא של ``label-container``
          const fills = (box) => [...box.querySelectorAll('.node rect.label-container')].map((n) => getComputedStyle(n).fill);
          const ids = [...light.querySelectorAll('svg'), ...dark.querySelectorAll('svg')].map((v) => v.id);
          const out = { light: fills(light), dark: fills(dark), ids };
          light.remove(); dark.remove();
          return out;
        }"""
    )

    assert len(r["light"]) == 4 and set(r["light"]) == {"rgb(236, 236, 255)"}, r
    assert len(r["dark"]) == 4 and "rgb(236, 236, 255)" not in r["dark"], r
    assert len(r["ids"]) == 4 and len(set(r["ids"])) == 4, r["ids"]


def test_the_theme_choices_come_from_the_server(session):
    """הבורר נבנה מ-``EXPORT_THEME_IDS``, וכל ערכה נושאת את כתובת השלד שלה — הצרכן קורא אותן מה-HTML."""
    from webapp.markdown_editor import EXPORT_THEME_IDS

    s = session()
    choices = s.page.eval_on_selector_all(
        "input[name=mdEditorExportTheme]",
        "els => els.map((e) => [e.value, e.getAttribute('data-skeleton-url'), e.getAttribute('data-mermaid-theme')])",
    )
    assert [c[0] for c in choices] == list(EXPORT_THEME_IDS)
    assert all(url == f"/api/markdown-editor/export-skeleton/{tid}" for tid, url, _m in choices)
    assert dict((tid, m) for tid, _u, m in choices) == {"morass": "dark", "pen-paper-coffee": "default"}
