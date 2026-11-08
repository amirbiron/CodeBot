"""הייצוא ל-HTML מעוצב מעמוד הקובץ, בדפדפן אמיתי: מהלחיצה בחלון הייצוא ועד הקובץ שירד, כשהוא נפתח לבד ובלי רשת.

**למה בדפדפן.** המסמך מרונדר בדפדפן ומוכנס לשלד שם (``export-modal.js`` דרך ``StyledExportCore``), המנוע נטען רק
בלחיצה מתוך ``<template>``, וכל מה שהקובץ צריך — הערכה, הדגשת התחביר, KaTeX, Mermaid — נראה רק כשהוא נפתח. מה שהשרת
מגיש נבדק ב-``tests/test_styled_export_view_file.py``.

**איך העמוד מוגש.** כמו ב-``tests/test_markdown_editor_export_browser.py``: כל בקשה עוברת דרך ``route`` של Playwright
ל-``test_client`` של Flask, עם הכותרות שהעמוד והשלד נשענים עליהן (CSP, ``X-Export-Filename``). הקובץ מגיע מ-
``_get_user_any_file_by_id`` — אותה פונקציה שעמוד הקובץ, השלד ו-``/download`` קוראים לה — ושאר המסד מתירני. לכל הקשר
דפדפן משתמש משלו, כי המגביל הגורף סופר לפי ``session['user_id']``.

**תוכן הקובץ** הוא טקסט ההדגמה של העורך הציבורי, ולכן המדידה (``_styled_export_harness.PROBE_FILE``) והמספרים שלה
זהים לאלה של הייצוא מהעורך: אותו מנוע, אותו קובץ.

מדולג כשאין Chromium (``chromium_executable`` ב-``tests/conftest.py``).
"""

from __future__ import annotations

import itertools
import json
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

from _browser_harness import poll  # noqa: E402
from _styled_export_harness import PROBE_FILE, open_file  # noqa: E402

HOST = "ck.test"
FILE_ID = "c" * 24
BIG_ID = "d" * 24
INJECTION_ID = "f" * 24

#: ניסיונות הזרקה במסמך ששותף: HTML גולמי, קישור javascript:, ‏\\href ב-KaTeX, ותווית ו-click ב-Mermaid. כאן הם
#: מרונדרים בדפדפן של מי שפותח את הקישור, בדומיין שלנו.
INJECTION_DOC = """# הזרקות

<img src=x onerror="alert(1)"><script>alert(2)</script>

[קישור](javascript:alert(3))

$\\href{javascript:alert(4)}{לחץ}$

```mermaid
graph TD
  A["<img src=x onerror=alert(5)>"] --> B
  click A "javascript:alert(6)"
```

</script><script>alert(7)</script>
"""
FORWARDED_HEADERS = (
    "content-type", "content-security-policy", "etag", "cache-control", "content-disposition", "x-export-filename",
)
_USERS = itertools.count(930_000)

#: השורה האחרונה של הקובץ הגדול — אם היא בקובץ שירד, הטקסט הגיע מ-``/download`` בשלמותו.
BIG_END = "סוף-הקובץ-הגדול-91c2"

#: ערכת VS Code בהירה, עם שלושה טוקנים בצבע משלה
VSCODE_LIGHT = {
    "name": "Light Sample",
    "type": "light",
    "colors": {"editor.background": "#fcfbf7", "editor.foreground": "#222222", "editorLineNumber.foreground": "#999999"},
    "tokenColors": [
        {"scope": ["keyword"], "settings": {"foreground": "#a626a4"}},
        {"scope": ["string"], "settings": {"foreground": "#50a14f"}},
        {"scope": ["comment"], "settings": {"foreground": "#a0a1a7", "fontStyle": "italic"}},
    ],
}


def _imported_user_theme() -> dict:
    """ערכת משתמש כמו שייבוא מ-VS Code שומר אותה: המשתנים, וכללי highlight.js תחת הקידומת של האתר."""
    from services.theme_parser_service import parse_vscode_theme

    parsed = parse_vscode_theme(json.dumps(VSCODE_LIGHT))
    return {"id": "imported-light", "name": "מיובאת", "variables": parsed["variables"], "syntax_css": parsed["syntax_css"]}


class _Cursor(list):
    def sort(self, key=None, direction=None, *a, **k):
        if isinstance(key, str):
            super().sort(key=lambda d: d.get(key), reverse=direction == -1)
        return self

    def limit(self, *a, **k):
        return self

    def skip(self, *a, **k):
        return self

    def batch_size(self, *a, **k):
        return self


class _Coll:
    def __init__(self, find_one_result=None):
        self.find_one_result = find_one_result

    def find_one(self, *a, **k):
        return self.find_one_result

    def find(self, *a, **k):
        return _Cursor()

    def aggregate(self, *a, **k):
        return _Cursor()

    def count_documents(self, *a, **k):
        return 0

    def distinct(self, *a, **k):
        return []

    def update_one(self, *a, **k):
        return SimpleNamespace(modified_count=0, matched_count=0, upserted_id=None)

    def insert_one(self, *a, **k):
        return SimpleNamespace(inserted_id="x")

    def create_index(self, *a, **k):
        return "x"

    def find_one_and_update(self, *a, **k):
        return None


class _Shares:
    """אוסף ``styled_shares`` בזיכרון: היצירה כותבת, העמוד הציבורי קורא, והרשימה והביטול מוצאים ומוחקים."""

    def __init__(self):
        self.docs: list[dict] = []

    def _match(self, doc, query):
        return all(doc.get(k) == v for k, v in query.items())

    def insert_one(self, doc):
        self.docs.append(doc)
        return SimpleNamespace(inserted_id="x")

    def find_one(self, query, *a, **k):
        return next((d for d in self.docs if self._match(d, query)), None)

    def update_one(self, *a, **k):
        return SimpleNamespace(modified_count=0, matched_count=0, upserted_id=None)

    def find(self, query, projection=None):
        return _Cursor(dict(d) for d in self.docs if self._match(d, query))

    def delete_one(self, query):
        for d in list(self.docs):
            if self._match(d, query):
                self.docs.remove(d)
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)


class _Db:
    def __init__(self, user_theme):
        self.users = _Coll({"custom_themes": [user_theme]})
        self.styled_shares = _Shares()

    def __getattr__(self, name):
        return _Coll()

    def __getitem__(self, name):
        return getattr(self, name)


@pytest.fixture(scope="module")
def browser(chromium_executable):
    import webapp.app as wa
    from webapp.markdown_editor import demo_text

    user_theme = _imported_user_theme()
    big = "# קובץ גדול\n\n" + "".join(f"פסקה {i} של טקסט רגיל.\n\n" for i in range(40_000)) + BIG_END + "\n"
    assert len(big.encode("utf-8")) > 1024 * 1024, "הקובץ הגדול אינו גדול מהסף של עמוד הקובץ"
    docs = {
        FILE_ID: {"_id": FILE_ID, "file_name": "מדריך.md", "programming_language": "markdown", "code": demo_text()},
        BIG_ID: {"_id": BIG_ID, "file_name": "גדול.md", "programming_language": "markdown", "code": big},
        INJECTION_ID: {"_id": INJECTION_ID, "file_name": "הזרקות.md", "programming_language": "markdown", "code": INJECTION_DOC},
    }
    for doc in docs.values():
        doc.update(version=1, is_active=True)
    db = _Db(user_theme)  # אחד לכל המודול: קישור שנוצר בהקשר אחד נפתח מהקשר אחר

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(wa, "get_db", lambda: db)
        patch.setattr(wa, "is_admin", lambda uid: False)
        patch.setattr(wa, "is_premium", lambda uid: True)
        patch.setattr(
            wa, "_get_user_any_file_by_id",
            lambda db, uid, fid: (dict(docs[fid]), "regular") if fid in docs else (None, None),
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
                yield b, wa
            finally:
                b.close()


class Session:
    """הקשר דפדפן אחד מול עמוד הקובץ: הבקשות שנשלחו, השגיאות, והדף."""

    def __init__(self, browser, *, file_id=FILE_ID, fail=None, blocked=()):
        b, wa = browser
        self.browser_pair = browser
        self.file_id = file_id
        # ``(תחילת נתיב, קוד)`` — תשובה שנכפית על בקשה, כדי לבדוק ייצוא שנכשל
        self.fail = fail
        # סוף נתיב של בקשות שנכשלות ברשת — סקריפט שלא נטען
        self.blocked = tuple(blocked)
        # סוף נתיב של הבקשה הבאה שתוחזק בלי תשובה עד ``release`` (פעם אחת). התשובה מחושבת כבר ברגע ההחזקה, כמו תשובה
        # שהשרת שלח והרשת עיכבה — ולכן היא משקפת את המצב של אז
        self.hold = None
        # ``True`` — השרת מטפל בבקשה המוחזקת רק בשחרור, כמו בקשה שהרשת עיכבה בדרך אליו
        self.hold_defer = False
        self.held: list = []
        self.requests: list[tuple[str, str]] = []
        self.errors: list[str] = []
        client = wa.app.test_client()
        uid = next(_USERS)
        client.environ_base["HTTP_X_FORWARDED_FOR"] = f"198.51.100.{uid % 250 + 1}"
        with client.session_transaction() as sess:
            sess["user_id"] = uid
            sess["user_data"] = {"id": uid, "first_name": "בדיקה", "is_admin": False, "is_premium": True}
        self.ctx = b.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True)
        # העמוד מוגש ב-http, שאינו הקשר מאובטח, ושם ``navigator.clipboard`` לא קיים. רשם במקומו: מה ש"העתק קישור"
        # שולח ללוח הוא הקישור שנוצר, וממנו הטסט יודע מה לפתוח
        self.ctx.add_init_script(
            "Object.defineProperty(navigator, 'clipboard', { configurable: true,"
            " value: { writeText: (text) => { window.__copied = text; return Promise.resolve(); } } });"
        )
        self.dialogs: list[str] = []

        def handle(route, request):
            u = urlsplit(request.url)
            if u.hostname != HOST:
                return route.abort()
            target = u.path + (f"?{u.query}" if u.query else "")
            self.requests.append((request.method, target))
            if self.fail and u.path.startswith(self.fail[0]):
                return route.fulfill(status=self.fail[1], body="", headers={"Content-Type": "text/plain"})
            if any(u.path.endswith(b) for b in self.blocked):
                return route.abort()
            def respond():
                return client.open(
                    target, method=request.method, data=request.post_data_buffer,
                    headers={"Content-Type": request.headers.get("content-type", "")},
                )

            if self.hold and u.path.endswith(self.hold):
                self.hold = None
                # ``Response`` של werkzeug הוא עצמו callable (אפליקציית WSGI), ולכן הדחייה מסומנת במפורש ולא לפי callable
                self.held.append((route, None if self.hold_defer else respond(), respond))
                return None
            r = respond()
            route.fulfill(
                status=r.status_code,
                body=r.data,
                headers={k: v for k, v in r.headers.items() if k.lower() in FORWARDED_HEADERS},
            )

        self.ctx.route("**/*", handle)
        self.page = self.ctx.new_page()
        self.page.on("pageerror", lambda exc: self.errors.append(str(exc)))
        # ``confirm`` של ביטול קישור מאושר; כל חלון נרשם
        self.page.on("dialog", lambda d: (self.dialogs.append(d.message), d.accept()))
        self.page.goto(f"http://{HOST}/file/{file_id}")
        # הסקריפטים ``defer``, ו-``styled-export-core.js`` לפני ``export-modal.js``: כשהחלון מוכן, ה-Core כבר נטען — אם נטען
        poll(self.page, "typeof window.openExportModal === 'function'", "חלון הייצוא מוכן")

    def open_modal(self):
        self.page.evaluate("(fid) => window.openExportModal(fid)", self.file_id)
        poll(self.page, "document.querySelectorAll('#exportPresetsGrid .export-theme-card').length > 0", "הערכות נטענו")

    def choose(self, theme_id, *, user=False):
        if user:
            self.page.click("#exportThemeModal [data-tab=my-themes]")
        grid = "#exportUserThemesGrid" if user else "#exportPresetsGrid"
        self.page.click(f'{grid} .export-theme-card[data-theme-id="{theme_id}"]')

    def download(self, tmp_path, name):
        with self.page.expect_download(timeout=90000) as info:
            self.page.click('#exportThemeModal [data-action="download"]')
        path = tmp_path / name
        info.value.save_as(path)
        return info.value, path

    def paths(self, method=None):
        return [t for m, t in self.requests if method is None or m == method]

    def count(self, path_suffix):
        return sum(1 for t in self.paths() if urlsplit(t).path.endswith(path_suffix))

    def create_link(self, theme_id, *, permanent=False):
        """"העתק קישור" בחלון הייצוא — המסלול של המשתמש. מחזיר את ה-token מהקישור שנשלח ללוח."""
        self.page.evaluate("window.__copied = undefined")
        self.open_modal()
        self.choose(theme_id)
        if permanent:
            self.page.check("#exportPermanentLink")
        self.page.click('#exportThemeModal [data-action="copy-link"]')
        poll(self.page, "window.__copied !== undefined", "הקישור נוצר והועתק")
        url = self.page.evaluate("window.__copied")
        return urlsplit(url).path.rsplit("/", 1)[-1]

    def release(self):
        """משחרר את הבקשה שהוחזקה, עם התשובה שחושבה ברגע ההחזקה."""
        for route, r, respond in self.held:
            if r is None:
                r = respond()
            route.fulfill(status=r.status_code, body=r.data,
                          headers={k: v for k, v in r.headers.items() if k.lower() in FORWARDED_HEADERS})
        self.held.clear()

    def close(self):
        self.ctx.close()


#: מעכב את הרינדור של עמוד הקישור עד אחרי ``load`` — המצב של מסמך ארוך או טלפון איטי. Chromium ממשיך לנסות לגלול
#: לעוגן שבכתובת עד ``load`` (נמדד: בלי העיכוב, הגלילה קרתה גם בלי ``scrollToHash``), ולכן רק כך נבדק הקוד שגולל אחרי
#: שהמסמך נכנס. עוטף את ``renderMarkdown`` ברגע ש-``styled-export-core.js`` מציב את ``window.StyledExportCore``.
RENDER_AFTER_LOAD = """
(() => {
  let core;
  const afterLoad = () => new Promise((resolve) => {
    const later = () => setTimeout(resolve, 300);
    if (document.readyState === 'complete') later(); else window.addEventListener('load', later, { once: true });
  });
  Object.defineProperty(window, 'StyledExportCore', {
    configurable: true,
    get() { return core; },
    set(value) {
      const render = value.renderMarkdown;
      core = Object.assign({}, value, { renderMarkdown: async (...args) => {
        await afterLoad();
        window.__renderStartedAfterLoad = document.readyState === 'complete';
        return render(...args);
      } });
    },
  });
})();
"""


def open_share(browser, token, *, fragment="", render_after_load=False):
    """פותח קישור שיתוף כמו מי שקיבל אותו: הקשר חדש, בלי התחברות, תחת הכותרות שהשרת שולח (ה-CSP בראשן).

    מחזיר ``(ctx, page, seen)``: ב-``seen`` הסטטוס של העמוד, הפרות ה-CSP (``securitypolicyviolation``, שנרשמות מסקריפט
    שהדפדפן מריץ לפני העמוד ולכן אינו כפוף ל-CSP שלו), שגיאות, חלונות, והבקשות שיצאו. ``render_after_load`` —
    :data:`RENDER_AFTER_LOAD`.
    """
    b, wa = browser
    client = wa.app.test_client()
    client.environ_base["HTTP_X_FORWARDED_FOR"] = f"198.51.100.{next(_USERS) % 250 + 1}"
    seen = {"status": None, "csp": [], "errors": [], "dialogs": [], "requests": []}
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    ctx.add_init_script(
        "window.__csp = []; document.addEventListener('securitypolicyviolation',"
        " (e) => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));"
    )
    if render_after_load:
        ctx.add_init_script(RENDER_AFTER_LOAD)

    def handle(route, request):
        u = urlsplit(request.url)
        seen["requests"].append(u.path)
        if u.hostname != HOST:
            return route.abort()
        r = client.open(u.path + (f"?{u.query}" if u.query else ""), method=request.method)
        route.fulfill(status=r.status_code, body=r.data,
                      headers={k: v for k, v in r.headers.items() if k.lower() in FORWARDED_HEADERS})

    ctx.route("**/*", handle)
    page = ctx.new_page()
    page.on("pageerror", lambda exc: seen["errors"].append(str(exc)))
    page.on("dialog", lambda d: (seen["dialogs"].append(d.message), d.dismiss()))
    resp = page.goto(f"http://{HOST}/shared/styled/{token}{fragment}")
    seen["status"] = resp.status if resp else None
    return ctx, page, seen


def wait_rendered(page):
    poll(page, "document.documentElement.dataset.shareRendered === 'true'"
               " || document.documentElement.dataset.shareRendered === 'failed'", "עמוד הקישור סיים לרנדר")
    assert page.evaluate("document.documentElement.dataset.shareRendered") == "true"


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


def _skeleton_requests(s):
    return [(m, t) for m, t in s.requests if urlsplit(t).path == f"/export/styled/{s.file_id}/skeleton"]


def _server_exports(s):
    """בקשות לייצוא שבשרת — ``/export/styled/<id>`` עצמו, לא השלד."""
    return [t for _m, t in s.requests if urlsplit(t).path == f"/export/styled/{s.file_id}"]


# ---------------------------------------------------------------------------
# הקובץ, רכיב-רכיב — בכל סוג של ערכה
# ---------------------------------------------------------------------------


#: כמה מהתווים ש-highlight.js מסמן מקבלים ב-morass צבע אחר מצבע הטקסט — נמדד ב-8.11.2026, בטסטים של הקובץ הזה. מאז
#: המחוללים צובעים כמו VS Code (``services/vscode_token_theme.py``), וטוקן ש-VS Code משאיר בצבע הטקסט (פרמטר, משתנה,
#: פיסוק בתוך span) אינו נספר "צבוע". הנאמנות ל-VS Code, תו-תו, נבדקת ב-``tests/test_syntax_colors_vscode_browser.py``.
MORASS_COLORED_PCT = 87


@pytest.mark.parametrize(
    "theme_id, user, light, min_colored_pct",
    [
        # ערכות עם צבעי highlight.js משלהן
        ("pen-paper-coffee", False, True, 90),
        ("morass", False, False, MORASS_COLORED_PCT),
        # ערכה בלי צבעים משלה — הפלטה שנגזרת מהמשתנים
        ("tech-guide-dark", False, False, 90),
        # ערכת משתמש מיובאת: הכללים שלה עברו לקידומת של הייצוא, והפלטה מתחתם. ב-``VSCODE_LIGHT`` יש רק מילות מפתח,
        # מחרוזות והערות, ו-VS Code מציג כל טוקן אחר ב-``editor.foreground`` — וכך גם הכללים שלה מאז 8.11.2026
        # (נמדד אז: 53). הפלטה נשארת למחלקות שאין להן כלל.
        ("imported-light", True, True, 53),
    ],
)
def test_the_file_is_built_in_the_browser_and_works_on_its_own(
    browser, session, tmp_path, theme_id, user, light, min_colored_pct
):
    s = session()
    assert s.count("/md_preview.bundle.js") == 0, "המנוע נטען כבר בטעינת העמוד"
    s.open_modal()
    s.choose(theme_id, user=user)
    download, path = s.download(tmp_path, f"{theme_id}.html")

    assert download.suggested_filename == "מדריך.html"
    assert s.errors == []
    assert s.page.is_hidden("#exportThemeModal"), "החלון לא נסגר אחרי ההורדה"
    # הקובץ נבנה בדפדפן: שלד אחד עם הערכה ו-math=1 (בטקסט יש נוסחאות), בלי ייצוא בשרת ובלי ``/download``
    [(method, skeleton)] = _skeleton_requests(s)
    assert method == "GET"
    assert parse_qs(urlsplit(skeleton).query) == {"theme": [theme_id], "math": ["1"]}
    assert _server_exports(s) == []
    assert s.count(f"/download/{FILE_ID}") == 0

    ctx, page, attempts, dialogs = open_file(browser, path)
    try:
        r = page.evaluate(PROBE_FILE)
        title = page.title()
    finally:
        ctx.close()

    assert attempts == [], attempts
    assert dialogs == []
    assert title == "מדריך"
    assert r["header"] is True
    assert "Code Keeper Bot" in r["footer"]
    assert r["alerts"]["count"] == 15 and r["alerts"]["styled"] == 15, r["alerts"]
    assert r["code"]["tokenChars"] > 300 and r["code"]["coloredPct"] >= min_colored_pct, r["code"]
    assert r["code"]["copyButtonsPerPre"] == [1] * r["code"]["pres"], r["code"]
    assert r["code"]["themeCopyButtons"] == 0
    assert "Python" in r["code"]["headerLabels"]
    assert r["tasks"] == {"count": 11, "checked": 6, "disabled": 11, "bullets": 0}, r["tasks"]
    assert r["markBg"] not in (None, "rgb(255, 255, 0)"), r["markBg"]
    assert r["strike"] == "line-through"
    assert r["h5h6"] == 0
    assert r["anchors"]["internal"] == 10 and r["anchors"]["broken"] == 0, r["anchors"]
    assert r["katex"]["count"] == 5 and r["katex"]["mathmlShown"] is False, r["katex"]
    assert r["katex"]["font"] == "KaTeX_Math" and r["katex"]["fontsLoaded"] > 0, r["katex"]
    assert r["katex"]["pageScrollsSideways"] is False
    assert r["mermaid"]["svgs"] == 3
    # ערכת ה-Mermaid היא של הקובץ: הבהירה (``default``) צובעת צמתים ב-#ECECFF
    assert (r["mermaid"]["nodeFill"] == "rgb(236, 236, 255)") is light, r["mermaid"]
    assert r["internal"] == {"sourceLines": 0, "highlighted": 0}


def test_the_engine_loads_on_the_first_export_only(session, tmp_path):
    s = session()
    s.open_modal()
    s.choose("morass")
    s.download(tmp_path, "first.html")
    s.open_modal()
    s.download(tmp_path, "second.html")

    assert s.count("/md_preview.bundle.js") == 1
    assert s.count("/live-preview.js") == 1
    assert len(_skeleton_requests(s)) == 2
    assert s.errors == []


def test_preview_opens_the_built_file_in_a_new_tab(session):
    s = session()
    s.open_modal()
    s.choose("pen-paper-coffee")
    with s.ctx.expect_page(timeout=90000) as info:
        s.page.click('#exportThemeModal [data-action="preview"]')
    tab = info.value
    tab.wait_for_url(lambda u: u.startswith("blob:"), wait_until="commit", timeout=90000)
    tab.wait_for_function("document.readyState === 'complete' && document.querySelector('main.container h1')")

    assert tab.title() == "מדריך"
    assert tab.evaluate("document.querySelectorAll('pre .copy-btn').length") == tab.evaluate(
        "document.querySelectorAll('main.container pre').length"
    ) > 0
    assert s.page.evaluate("document.querySelector('#exportThemeModal [data-action=preview]').disabled") is False
    assert _server_exports(s) == []


def test_a_file_too_large_to_show_is_read_from_download(session, tmp_path):
    """בקובץ מעל 1MB העמוד אינו מציג את הטקסט (אין ``#rawCode``), והייצוא מביא אותו מ-``/download`` — אותה גרסה."""
    s = session(file_id=BIG_ID)
    assert s.page.query_selector("#rawCode") is None
    s.open_modal()
    s.choose("morass")
    download, path = s.download(tmp_path, "big.html")

    assert download.suggested_filename == "גדול.html"
    assert s.count(f"/download/{BIG_ID}") == 1
    html = path.read_text(encoding="utf-8")
    assert BIG_END in html and "פסקה 39999 של טקסט רגיל." in html


def test_a_vscode_theme_is_posted_with_the_skeleton_request(browser, session, tmp_path):
    theme_file = tmp_path / "light.json"
    theme_file.write_text(json.dumps(VSCODE_LIGHT), encoding="utf-8")
    s = session()
    s.open_modal()
    s.page.click("#exportThemeModal [data-tab=import]")
    s.page.set_input_files("#exportThemeFileInput", str(theme_file))
    poll(s.page, "!document.getElementById('exportUploadStatus').hidden", "הערכה מ-VS Code נטענה")
    _download, path = s.download(tmp_path, "vscode.html")

    [(method, _target)] = _skeleton_requests(s)
    assert method == "POST"
    ctx, page, attempts, _dialogs = open_file(browser, path)
    try:
        # הרקע הוא מעבר צבע (``background-image``), ולכן נמדד המשתנה שהוא נבנה ממנו
        bg = page.evaluate("getComputedStyle(document.body).getPropertyValue('--bg-primary').trim().toLowerCase()")
        fill = page.evaluate(
            "(() => { const r = document.querySelector('.mermaid-diagram .node rect, .mermaid-diagram .node polygon');"
            " return r ? getComputedStyle(r).fill : null; })()"
        )
        katex = page.evaluate("document.querySelectorAll('.katex').length")
    finally:
        ctx.close()
    assert attempts == []
    assert bg == "#fcfbf7"  # editor.background של הערכה
    assert fill == "rgb(236, 236, 255)"  # ערכה בהירה ← Mermaid בהיר
    assert katex == 5


# ---------------------------------------------------------------------------
# ייצוא שנכשל
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status, message", [(429, "יותר מדי ייצואים"), (500, "הייצוא נכשל")])
@pytest.mark.parametrize("mode", ["download", "preview"])
def test_a_failed_export_tells_the_user_and_frees_the_buttons(session, status, message, mode):
    s = session(fail=(f"/export/styled/{FILE_ID}/skeleton", status))
    s.open_modal()
    s.choose("morass")
    downloads: list = []
    s.page.on("download", lambda d: downloads.append(d))
    tab = None
    if mode == "preview":
        with s.ctx.expect_page(timeout=90000) as info:
            s.page.click('#exportThemeModal [data-action="preview"]')
        tab = info.value
    else:
        s.page.click('#exportThemeModal [data-action="download"]')
    poll(
        s.page,
        "!document.querySelector('.export-error-message').hidden"
        " && !document.querySelector('#exportThemeModal [data-action=download]').disabled",
        "הודעת שגיאה והכפתורים חזרו",
    )
    if tab is not None:
        if not tab.is_closed():
            tab.wait_for_event("close", timeout=15000)
        assert tab.is_closed()

    assert message in s.page.inner_text(".export-error-message")
    assert s.page.get_attribute("#exportThemeModal", "aria-busy") == "false"
    assert s.page.is_visible("#exportThemeModal"), "החלון נסגר למרות שהייצוא נכשל"
    assert downloads == []
    # בקרה: בקשת השלד באמת נשלחה ונכשלה, ולא הייצוא נעצר לפניה
    assert len(_skeleton_requests(s)) == 1


# ---------------------------------------------------------------------------
# המתג
# ---------------------------------------------------------------------------


def test_the_switch_off_keeps_the_server_export(browser, session, tmp_path, monkeypatch):
    _b, wa = browser
    monkeypatch.setattr(wa, "STYLED_EXPORT_BROWSER_RENDER", False)
    s = session()
    assert s.page.get_attribute("#exportThemeModal", "data-browser-render") == "0"
    s.open_modal()
    s.choose("morass")
    download, _path = s.download(tmp_path, "server.html")

    assert download.suggested_filename == "מדריך.html"
    assert _server_exports(s) == [f"/export/styled/{FILE_ID}?theme=morass"]
    assert _skeleton_requests(s) == []
    assert s.count("/md_preview.bundle.js") == 0



# ---------------------------------------------------------------------------
# קישור השיתוף — נבנה בדפדפן של מי שפותח
# ---------------------------------------------------------------------------


def test_a_share_renders_in_the_visitors_browser_under_its_policy(browser, session):
    token = session().create_link("morass")
    ctx, page, seen = open_share(browser, token)
    try:
        wait_rendered(page)
        r = page.evaluate(PROBE_FILE)
        csp = page.evaluate("window.__csp")
        title = page.title()
        status_line = page.query_selector("#ckShareStatus")
        # קריאה נוספת (רינדור חוזר, למשל) לא מוסיפה כפתור שני לבלוק שכבר יש לו
        page.evaluate("window.ckAttachCopyButtons(document)")
        again = page.evaluate("[...document.querySelectorAll('main pre')].map((p) => p.querySelectorAll('.copy-btn').length)")
    finally:
        ctx.close()

    assert seen["status"] == 200
    assert csp == [], csp
    assert seen["errors"] == [] and seen["dialogs"] == []
    # מה שיצא מהעמוד: העמוד עצמו והסקריפטים מהסטטיקה שלנו, ולא שום דבר אחר
    assert {p for p in seen["requests"] if p != f"/shared/styled/{token}"} <= {
        p for p in seen["requests"] if p.startswith("/static/js/")
    }, seen["requests"]
    assert title == "מדריך" and status_line is None
    assert r["header"] is True and "Code Keeper Bot" in r["footer"]
    assert r["alerts"]["count"] == 15 and r["alerts"]["styled"] == 15, r["alerts"]
    assert r["code"]["tokenChars"] > 300 and r["code"]["coloredPct"] >= MORASS_COLORED_PCT, r["code"]
    # כפתורי ההעתקה נוספו אחרי שהמסמך נכנס לעמוד — אחד לכל בלוק
    assert r["code"]["pres"] > 0 and r["code"]["copyButtonsPerPre"] == [1] * r["code"]["pres"], r["code"]
    assert again == [1] * r["code"]["pres"], again
    assert r["tasks"] == {"count": 11, "checked": 6, "disabled": 11, "bullets": 0}, r["tasks"]
    assert r["anchors"]["internal"] == 10 and r["anchors"]["broken"] == 0, r["anchors"]
    assert r["katex"]["count"] == 5 and r["katex"]["font"] == "KaTeX_Math" and r["katex"]["fontsLoaded"] > 0, r["katex"]
    assert r["mermaid"]["svgs"] == 3 and r["mermaid"]["nodeFill"] != "rgb(236, 236, 255)", r["mermaid"]
    assert r["internal"] == {"sourceLines": 0, "highlighted": 0}


def test_injection_attempts_in_a_shared_file_run_nothing(browser, session):
    token = session(file_id=INJECTION_ID).create_link("morass")
    ctx, page, seen = open_share(browser, token)
    try:
        wait_rendered(page)
        found = page.evaluate(
            """() => ({
              onAttrs: [...document.querySelectorAll('main *')].filter((e) => [...e.attributes].some((a) => /^on/i.test(a.name))).length,
              javascriptUrls: [...document.querySelectorAll('main [href], main [src]')].filter((e) =>
                /^\\s*javascript:/i.test(e.getAttribute('href') || e.getAttribute('src') || '')).length,
              scriptsInMain: document.querySelectorAll('main script').length,
              rawShownAsText: document.querySelector('main').innerText.includes('<img src=x onerror'),
            })"""
        )
        # והשכבה השנייה: גם מה שעוקף את המנוע ונכנס לעמוד לא רץ — ה-CSP חוסם handler מוטמע
        page.evaluate(
            """() => { const d = document.createElement('div');
                       d.innerHTML = '<img src="x" onerror="window.__pwned = 1">'; document.body.appendChild(d); }"""
        )
        page.wait_for_timeout(500)
        pwned = page.evaluate("window.__pwned === 1")
        csp = page.evaluate("window.__csp")
    finally:
        ctx.close()

    assert seen["dialogs"] == [], seen["dialogs"]
    assert found == {"onAttrs": 0, "javascriptUrls": 0, "scriptsInMain": 0, "rawShownAsText": True}, found
    assert pwned is False
    assert any(v.startswith("script-src") for v in csp), csp  # הבקרה: ה-handler נחסם, ולא פשוט לא נוסה


def test_a_share_opens_at_the_anchor_in_its_address(browser, session):
    token = session().create_link("pen-paper-coffee")
    ctx, page, _seen = open_share(browser, token)
    try:
        wait_rendered(page)
        anchor = page.evaluate("[...document.querySelectorAll('main h2[id]')].pop().id")
    finally:
        ctx.close()

    ctx, page, _seen = open_share(browser, token, fragment="#" + anchor, render_after_load=True)
    try:
        wait_rendered(page)
        # בקרה: העיכוב הופעל, והרינדור התחיל רק אחרי ``load``
        assert page.evaluate("window.__renderStartedAfterLoad") is True
        top = page.evaluate("(id) => document.getElementById(id).getBoundingClientRect().top", anchor)
        scrolled = page.evaluate("document.scrollingElement.scrollTop")
    finally:
        ctx.close()
    # הכותרת בראש החלון; שבר של פיקסל מעליו הוא עיגול של הדפדפן (נמדד: ‎-0.44)
    assert scrolled > 500 and -2 <= top < 200, (scrolled, top)


def test_a_link_revoked_from_the_modal_stops_opening(browser, session):
    s = session()
    token = s.create_link("morass", permanent=True)
    s.page.click("#exportThemeModal [data-tab=links]")
    poll(s.page, f"!!document.querySelector('#exportLinksList [data-token=\"{token}\"]')", "הקישור ברשימה")
    row = s.page.inner_text(f'#exportLinksList [data-token="{token}"]')
    assert "קבוע" in row and "0 צפיות" in row, row

    s.page.click(f'#exportLinksList [data-token="{token}"] [data-link-action=revoke]')
    poll(s.page, f"!document.querySelector('#exportLinksList [data-token=\"{token}\"]')", "הקישור ירד מהרשימה")

    assert any("לבטל את הקישור" in m for m in s.dialogs), s.dialogs
    ctx, _page, seen = open_share(browser, token)
    ctx.close()
    assert seen["status"] == 404


def test_a_share_from_before_still_opens_with_its_copy_buttons(browser, session, monkeypatch):
    """הצורה הראשונה — HTML שהשרת בנה — נוצרת כש-``STYLED_EXPORT_BROWSER_RENDER`` כבוי, ומוגשת כמו שנשמרה."""
    _b, wa = browser
    monkeypatch.setattr(wa, "STYLED_EXPORT_BROWSER_RENDER", False)
    token = session().create_link("morass")
    ctx, page, seen = open_share(browser, token)
    try:
        page.wait_for_function("document.readyState === 'complete'")
        buttons = page.evaluate("document.querySelectorAll('pre .copy-btn').length")
        pres = page.evaluate("document.querySelectorAll('main pre').length")
        csp = page.evaluate("window.__csp")
        engine = page.evaluate("!!document.getElementById('ckShareSource')")
    finally:
        ctx.close()
    assert seen["status"] == 200 and csp == []
    assert engine is False
    assert pres > 0 and buttons == pres


def test_a_file_too_large_to_share_is_refused_with_a_message(session):
    s = session(file_id=BIG_ID)
    s.open_modal()
    s.choose("morass")
    s.page.click('#exportThemeModal [data-action="copy-link"]')
    poll(s.page, "!document.querySelector('.export-error-message').hidden", "הודעת שגיאה")
    assert "גדול מכדי לשתף" in s.page.inner_text(".export-error-message")
    assert s.page.evaluate("window.__copied") is None


# ---------------------------------------------------------------------------
# מצבים שבהם משהו נתקע או חסר
# ---------------------------------------------------------------------------


def test_a_missing_export_core_is_reported_and_not_replaced_by_the_server(session, tmp_path):
    """``styled-export-core.js`` לא נטען: "הורד HTML" אומר למה אין ייצוא, ואינו עובר בשקט לייצוא שבשרת — מנוע אחר."""
    s = session(blocked=("/utils/styled-export-core.js",))
    assert s.page.evaluate("typeof window.StyledExportCore") == "undefined"  # בקרה: באמת חסר
    s.open_modal()
    s.choose("morass")
    downloads: list = []
    s.page.on("download", lambda d: downloads.append(d))
    s.page.click('#exportThemeModal [data-action="download"]')
    poll(s.page, "!document.querySelector('.export-error-message').hidden", "הודעת שגיאה")

    assert "רכיב הייצוא לא נטען" in s.page.inner_text(".export-error-message")
    assert downloads == []
    assert _server_exports(s) == [] and _skeleton_requests(s) == []


def test_a_hung_engine_script_is_requested_again(session, tmp_path):
    """בקשה לבאנדל שלא חוזרת: הניסיון הבא מבקש אותו מחדש, ולא מחכה לאותה בקשה תקועה עד רענון. וכשהבקשה התקועה
    מסתיימת בכל זאת והבאנדל רץ פעם שנייה, הייצוא עדיין עובד."""
    s = session()
    s.hold = "/md_preview.bundle.js"
    load = (
        "async (ms) => { try { await window.StyledExportCore.loadEngine("
        "document.getElementById('styledExportEngine'), ms); return 'ok'; } catch (e) { return e.message; } }"
    )
    assert s.page.evaluate(load, 1500) == "engine_timeout"
    assert len(s.held) == 1  # בקרה: הבקשה הראשונה באמת תקועה

    second = s.page.evaluate(load, 30000)
    assert (second, s.count("/md_preview.bundle.js")) == ("ok", 2)

    s.page.evaluate("window.__hljsBefore = window.hljs")
    s.release()  # הבקשה הישנה מסתיימת
    s.page.wait_for_timeout(1000)
    # בקרה: הבאנדל באמת רץ פעם שנייה (מופע חדש של highlight.js), ולא רק לא הפריע
    assert s.page.evaluate("!!window.hljs && window.hljs !== window.__hljsBefore") is True
    s.open_modal()
    s.choose("morass")
    _download, path = s.download(tmp_path, "after-rerun.html")
    ctx, page, attempts, _dialogs = open_file(s.browser_pair, path)
    try:
        r = page.evaluate(PROBE_FILE)
    finally:
        ctx.close()
    assert attempts == []
    assert r["code"]["coloredPct"] >= MORASS_COLORED_PCT and r["mermaid"]["svgs"] == 3 and r["katex"]["count"] == 5, r
    assert s.errors == []


def test_finishing_an_export_does_not_reenable_a_pending_copy_link(browser, session, tmp_path):
    _b, wa = browser
    before = len(wa.get_db().styled_shares.docs)
    s = session()
    s.open_modal()
    s.choose("morass")
    s.hold = f"/api/export/styled/{FILE_ID}/share"
    s.page.click('#exportThemeModal [data-action="copy-link"]')
    poll(s.page, "document.querySelector('#exportThemeModal [data-action=copy-link]').disabled", "יוצר קישור")
    s.download(tmp_path, "while-copying.html")  # הייצוא מסתיים באמצע יצירת הקישור
    s.open_modal()  # וגם פתיחה מחדש של החלון באמצע

    assert s.page.evaluate("document.querySelector('#exportThemeModal [data-action=copy-link]').disabled") is True
    s.release()
    poll(s.page, "window.__copied !== undefined", "הקישור נוצר")
    assert len(wa.get_db().styled_shares.docs) == before + 1


def test_a_stale_links_response_is_not_shown(session):
    """טעינה שהתחילה לפני ביטול חוזרת אחרי טעינה חדשה — והקישור שבוטל לא חוזר לרשימה."""
    s = session()
    token = s.create_link("morass")
    s.hold = f"/api/export/styled/{FILE_ID}/shares"
    s.page.click("#exportThemeModal [data-tab=links]")
    deadline = time.monotonic() + 10
    while not s.held and time.monotonic() < deadline:
        s.page.wait_for_timeout(50)
    assert len(s.held) == 1  # התשובה הישנה, עם הקישור, מוחזקת

    s.page.evaluate(
        "(t) => fetch(`/api/export/styled/shares/${t}/revoke`,"
        " { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })",
        token,
    )
    s.page.click("#exportThemeModal [data-tab=links]")
    poll(s.page, "document.querySelector('#exportLinksList').innerText.includes('אין קישורים')", "הרשימה הריקה")
    s.release()
    s.page.wait_for_timeout(500)

    assert s.page.query_selector(f'#exportLinksList [data-token="{token}"]') is None
    assert "אין קישורים" in s.page.inner_text("#exportLinksList")


def test_a_refresh_during_revoke_does_not_leave_the_revoked_link(session):
    """"קישורים" נפתחת שוב בזמן שהביטול בדרך לשרת: הרשימה שחוזרת עוד מכילה את הקישור, והיא מתחלפת כשהביטול מסתיים."""
    s = session()
    token = s.create_link("morass")
    s.page.click("#exportThemeModal [data-tab=links]")
    poll(s.page, f"!!document.querySelector('#exportLinksList [data-token=\"{token}\"]')", "הקישור ברשימה")
    s.hold, s.hold_defer = "/revoke", True
    s.page.click(f'#exportLinksList [data-token="{token}"] [data-link-action=revoke]')
    deadline = time.monotonic() + 10
    while not s.held and time.monotonic() < deadline:
        s.page.wait_for_timeout(50)
    assert len(s.held) == 1  # הביטול עוד לא הגיע לשרת

    s.page.click("#exportThemeModal [data-tab=links]")
    poll(s.page, f"!!document.querySelector('#exportLinksList [data-token=\"{token}\"]')", "הרשימה, עם הקישור")
    s.release()
    poll(s.page, "document.querySelector('#exportLinksList').innerText.includes('אין קישורים')", "הרשימה אחרי הביטול")
    assert s.page.query_selector(f'#exportLinksList [data-token="{token}"]') is None


def test_a_link_created_while_the_links_tab_is_open_appears_in_it(session):
    s = session()
    s.open_modal()
    s.page.click("#exportThemeModal [data-tab=links]")
    poll(s.page, "document.querySelector('#exportLinksList').innerText.includes('אין קישורים')", "רשימה ריקה")
    s.page.evaluate("window.__copied = undefined")
    s.page.click('#exportThemeModal [data-action="copy-link"]')
    poll(s.page, "window.__copied !== undefined", "הקישור נוצר")
    token = urlsplit(s.page.evaluate("window.__copied")).path.rsplit("/", 1)[-1]
    poll(s.page, f"!!document.querySelector('#exportLinksList [data-token=\"{token}\"]')", "הקישור החדש ברשימה")


def test_links_requests_keep_a_deadline_without_the_export_core(session):
    """בלי ``StyledExportCore`` לבקשות של הקישורים עדיין יש תקרת זמן: בקשה תקועה לרשימה מסתיימת בהודעה, ולא ב"טוען"
    לתמיד. ``LINKS_TIMEOUT_MS`` הוא 15 שניות, ולכן הטסט מחכה לו."""
    s = session(blocked=("/utils/styled-export-core.js",))
    assert s.page.evaluate("typeof window.StyledExportCore") == "undefined"  # בקרה: באמת חסר
    s.open_modal()
    s.hold = f"/api/export/styled/{FILE_ID}/shares"
    s.page.click("#exportThemeModal [data-tab=links]")
    # ``poll`` מוגבל ל-15 שניות — בדיוק התקרה שמחכים לה — ולכן דגימה עם תקרה משלה
    deadline = time.monotonic() + 30
    text = ""
    while time.monotonic() < deadline and "שגיאה בטעינת הקישורים" not in text:
        s.page.wait_for_timeout(250)
        text = s.page.inner_text("#exportLinksList")
    assert "שגיאה בטעינת הקישורים" in text, text
    assert len(s.held) == 1  # הבקשה באמת לא קיבלה תשובה — מה שסיים אותה הוא התקרה
