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
    def sort(self, *a, **k):
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


class _Db:
    def __init__(self, user_theme):
        self.users = _Coll({"custom_themes": [user_theme]})

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
    }
    for doc in docs.values():
        doc.update(version=1, is_active=True)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(wa, "get_db", lambda: _Db(user_theme))
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

    def __init__(self, browser, *, file_id=FILE_ID, fail=None):
        b, wa = browser
        self.file_id = file_id
        # ``(תחילת נתיב, קוד)`` — תשובה שנכפית על בקשה, כדי לבדוק ייצוא שנכשל
        self.fail = fail
        self.requests: list[tuple[str, str]] = []
        self.errors: list[str] = []
        client = wa.app.test_client()
        uid = next(_USERS)
        client.environ_base["HTTP_X_FORWARDED_FOR"] = f"198.51.100.{uid % 250 + 1}"
        with client.session_transaction() as sess:
            sess["user_id"] = uid
            sess["user_data"] = {"id": uid, "first_name": "בדיקה", "is_admin": False, "is_premium": True}
        self.ctx = b.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True)

        def handle(route, request):
            u = urlsplit(request.url)
            if u.hostname != HOST:
                return route.abort()
            target = u.path + (f"?{u.query}" if u.query else "")
            self.requests.append((request.method, target))
            if self.fail and u.path.startswith(self.fail[0]):
                return route.fulfill(status=self.fail[1], body="", headers={"Content-Type": "text/plain"})
            r = client.open(
                target, method=request.method, data=request.post_data_buffer,
                headers={"Content-Type": request.headers.get("content-type", "")},
            )
            route.fulfill(
                status=r.status_code,
                body=r.data,
                headers={k: v for k, v in r.headers.items() if k.lower() in FORWARDED_HEADERS},
            )

        self.ctx.route("**/*", handle)
        self.page = self.ctx.new_page()
        self.page.on("pageerror", lambda exc: self.errors.append(str(exc)))
        self.page.goto(f"http://{HOST}/file/{file_id}")
        poll(self.page, "typeof window.openExportModal === 'function' && !!window.StyledExportCore", "חלון הייצוא מוכן")

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

    def close(self):
        self.ctx.close()


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


@pytest.mark.parametrize(
    "theme_id, user, light, min_colored_pct",
    [
        # ערכות עם צבעי highlight.js משלהן
        ("pen-paper-coffee", False, True, 90),
        ("morass", False, False, 90),
        # ערכה בלי צבעים משלה — הפלטה שנגזרת מהמשתנים
        ("tech-guide-dark", False, False, 90),
        # ערכת משתמש מיובאת: הכללים שלה עברו לקידומת של הייצוא, והפלטה מתחתם
        ("imported-light", True, True, 90),
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
