"""הקישור הציבורי מהעורך ("צור קישור"), בדפדפן אמיתי: מהלחיצה בעורך, דרך עמוד הקישור תחת ה-CSP שלו, ועד המחיקה.

**למה בדפדפן.** שהטקסט לא יוצא מהדפדפן בלי לחיצה — רואים רק בבקשות הרשת. שעמוד הקישור מציג את אותו מסמך כמו הקובץ
שיוצא — רק כשהוא מרונדר, אצל מי שפותח. וה-CSP נאכף רק בדפדפן. מה שהשרת שומר ודוחה — ב-
``tests/test_public_editor_share.py``.

**איך העמודים מוגשים.** כמו ב-``tests/test_markdown_editor_export_browser.py``: כל בקשה עוברת דרך ``route`` של
Playwright ל-``test_client`` של Flask, עם הגוף, ובקשה לאתר חיצוני נחסמת. המסד מדומה (אוסף ``styled_shares`` בזיכרון),
ולכל הקשר דפדפן כתובת IP משלו, כי ליצירה יש מגבלת קצב לכל גולש.

מדולג כשאין Chromium (``chromium_executable`` ב-``tests/conftest.py``).
"""

from __future__ import annotations

import itertools
import json
from types import SimpleNamespace
from urllib.parse import unquote_plus, urlsplit

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

from _browser_harness import poll  # noqa: E402
from _styled_export_harness import PROBE_FILE, open_file  # noqa: E402

HOST = "ck.test"
EDITOR = f"http://{HOST}/markdown-editor"
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
SECRET_WORD = "סודי-לקישור-91c2"
SECRET_DOC = f"# {SECRET_WORD}\n\nטקסט שלא יוצא בלי לחיצה.\n"

#: ניסיונות הזרקה — אותם של הייצוא, ועוד ניסיון לסגור את תגית ה-JSON שהטקסט יושב בה בעמוד.
INJECTION_DOC = """# הזרקות

<img src=x onerror="alert(1)"><script>alert(2)</script>

</script><script>window.__pwnedJson = 1</script>

[קישור](javascript:alert(3))

[קישור רגיל](https://example.com/page)

$\\href{javascript:alert(4)}{לחץ}$

```mermaid
graph TD
  A["<img src=x onerror=alert(5)>"] --> B
  click A "javascript:alert(6)"
```
"""

_ADDRESSES = itertools.count(1)
_IDS = itertools.count(1)

PROBE_INJECTION = r"""
() => ({
  onAttrs: [...document.querySelectorAll('main *')].filter((e) => [...e.attributes].some((a) => /^on/i.test(a.name))).length,
  javascriptUrls: [...document.querySelectorAll('main [href], main [src]')].filter((e) =>
    /^\s*javascript:/i.test(e.getAttribute('href') || e.getAttribute('src') || '')).length,
  scriptsInMain: document.querySelectorAll('main script').length,
  rawShownAsText: document.querySelector('main').innerText.includes('<img src=x onerror'),
  pwnedJson: window.__pwnedJson === 1,
  externalRel: [...document.querySelectorAll('main a[href^="https://"]')].map((a) => a.getAttribute('rel')),
})
"""


class _Shares:
    def __init__(self):
        self.docs: list[dict] = []

    @staticmethod
    def _matches(doc, query):
        for key, want in query.items():
            if isinstance(want, dict) and "$gte" in want:
                if doc.get(key) is None or doc[key] < want["$gte"]:
                    return False
            elif doc.get(key) != want:
                return False
        return True

    def count_documents(self, query):
        return sum(1 for d in self.docs if self._matches(d, query))

    def insert_one(self, doc):
        stored = dict(doc, _id=f"id{next(_IDS)}")
        self.docs.append(stored)
        return SimpleNamespace(inserted_id=stored["_id"])

    def find_one(self, query, projection=None):
        doc = next((d for d in self.docs if self._matches(d, query)), None)
        if doc is None or not projection:
            return None if doc is None else dict(doc)
        return {k: v for k, v in doc.items() if projection.get(k)}

    def update_one(self, *args, **kwargs):
        return None

    def delete_one(self, query):
        doc = next((d for d in self.docs if self._matches(d, query)), None)
        if doc is None:
            return SimpleNamespace(deleted_count=0)
        self.docs.remove(doc)
        return SimpleNamespace(deleted_count=1)

    def find_one_and_delete(self, query, projection=None):
        doc = next((d for d in self.docs if self._matches(d, query)), None)
        if doc is None:
            return None
        self.docs.remove(doc)
        return {k: v for k, v in doc.items() if not projection or projection.get(k)}


class _Db:
    def __init__(self):
        self.styled_shares = _Shares()
        # מסמך המשתמש של עמוד אדמין (``inject_globals``): אין, והעמוד עולה בלעדיו
        self.users = SimpleNamespace(find_one=lambda *a, **k: None)

    def __getitem__(self, name):
        return getattr(self, name)


@pytest.fixture(scope="module")
def browser(chromium_executable):
    import webapp.app as wa

    db = _Db()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            wa,
            "_get_shared_theme_cached",
            lambda theme_id: dict(FAKE_THEME) if theme_id == "everforest_dark" else None,
        )
        patch.setattr(wa, "get_db", lambda: db)
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
                yield SimpleNamespace(browser=b, app=wa.app, db=db)
            finally:
                b.close()


class Session:
    """הקשר דפדפן אחד: הבקשות שנשלחו (עם הגוף), השגיאות, הדיאלוגים, והדף. ``accept_dialogs`` — מה עונים לאישור."""

    def __init__(self, env, *, draft=None, accept_dialogs=False, viewport=None, blocked=(), user_id=None):
        self.env = env
        # סוף נתיב של בקשות שנכשלות ברשת — סקריפט שלא נטען
        self.blocked = tuple(blocked)
        self.requests: list[tuple[str, str, bytes]] = []
        self.errors: list[str] = []
        self.dialogs: list[str] = []
        self.authorizations: list[tuple[str, str]] = []
        self.accept_dialogs = accept_dialogs
        self.client = env.app.test_client()
        self.client.environ_base["HTTP_X_FORWARDED_FOR"] = f"198.18.0.{next(_ADDRESSES) % 250 + 1}"
        if user_id is not None:
            # הדפדפן עובר דרך ה-client, ולכן ה-session של ה-client הוא ה-session של הדפדפן
            with self.client.session_transaction() as sess:
                sess["user_id"] = user_id
        self.ctx = env.browser.new_context(viewport=viewport or {"width": 1280, "height": 900}, accept_downloads=True)
        self.ctx.add_init_script(
            "window.__csp = []; document.addEventListener('securitypolicyviolation',"
            " (e) => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));"
        )
        if draft is not None:
            payload = json.dumps({"code": draft, "savedAt": 1})
            self.ctx.add_init_script(f"localStorage.setItem({json.dumps(DRAFT_KEY)}, {json.dumps(payload)});")
        self.ctx.route("**/*", self._handle)

    def _handle(self, route, request):
        u = urlsplit(request.url)
        if u.hostname != HOST:
            return route.abort()
        target = u.path + (f"?{u.query}" if u.query else "")
        self.requests.append((request.method, target, request.post_data_buffer or b""))
        if any(u.path.endswith(b) for b in self.blocked):
            return route.abort()
        headers = {"Content-Type": request.headers.get("content-type", "")}
        if request.headers.get("authorization"):
            headers["Authorization"] = request.headers["authorization"]
            self.authorizations.append((target, request.headers["authorization"]))
        r = self.client.open(target, method=request.method, data=request.post_data_buffer, headers=headers)
        route.fulfill(
            status=r.status_code,
            body=r.data,
            headers={k: v for k, v in r.headers.items() if k.lower() in FORWARDED_HEADERS},
        )

    def _on_dialog(self, dialog):
        self.dialogs.append(dialog.message)
        if self.accept_dialogs:
            dialog.accept()
        else:
            dialog.dismiss()

    def open_page(self, url):
        page = self.ctx.new_page()
        page.on("pageerror", lambda exc: self.errors.append(str(exc)))
        page.on("dialog", self._on_dialog)
        page.goto(url)
        return page

    def open_editor(self, url=EDITOR):
        self.page = self.open_page(url)
        poll(self.page, "document.querySelector('[data-preview-status]').dataset.state === 'ready'", "התצוגה החיה מוכנה")
        return self.page

    def choose(self, theme_id):
        if self.page.get_attribute("[data-md-editor-export-toggle]", "aria-expanded") != "true":
            self.page.click("[data-md-editor-export-toggle]")
        self.page.check(f"input[name=mdEditorExportTheme][value={theme_id}]")

    def create_share(self, theme_id):
        """"צור קישור", וחוזר עם הקישור וקישור המחיקה, כמו שהגולש רואה אותם."""
        self.choose(theme_id)
        self.page.click("[data-md-editor-share-action=create]")
        poll(self.page, "!!document.querySelector('[data-md-editor-share-link]').value", "הקישור נוצר")
        return (
            local(self.page.input_value("[data-md-editor-share-link]")),
            local(self.page.input_value("[data-md-editor-share-delete-link]")),
        )

    def download(self, theme_id, tmp_path):
        self.choose(theme_id)
        with self.page.expect_download(timeout=60000) as info:
            self.page.click("[data-md-editor-export-action=download]")
        path = tmp_path / f"{theme_id}.html"
        info.value.save_as(path)
        return path

    def share_status(self, share_url):
        return self.client.get(urlsplit(share_url).path).status_code

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


def local(url):
    """כתובת שהשרת החזיר, תחת השרת המדומה של הטסט: השרת בונה אותה מ-``_webapp_base_url`` (``WEBAPP_URL``, או הכתובת של
    הבקשה), והטסט מגיש רק את ``HOST``. הנתיב והחלק שאחרי ``#`` נשארים כמו שהם."""
    u = urlsplit(url)
    return f"http://{HOST}{u.path}" + (f"#{u.fragment}" if u.fragment else "")


def wait_rendered(page):
    # בעמוד הקישור ה-CSP אוסר ``unsafe-eval``, ולכן ``wait_for_function`` חסום והתנאי נדגם מבחוץ (``poll``)
    poll(page, "['true', 'failed'].includes(document.documentElement.dataset.shareRendered)", "עמוד הקישור סיים לרנדר")
    assert page.evaluate("document.documentElement.dataset.shareRendered") == "true"


def _carries_secret(requests):
    # הכתובת מפוענחת לפני החיפוש: בכתובת שנשלחה עברית מקודדת באחוזים
    return [r for r in requests if SECRET_WORD in unquote_plus(r[1]) or SECRET_WORD.encode() in r[2]]


# ---------------------------------------------------------------------------
# בלי לחיצה, הטקסט לא יוצא
# ---------------------------------------------------------------------------


def test_the_text_leaves_the_browser_only_on_the_click(session, tmp_path):
    s = session(draft=SECRET_DOC)
    s.open_editor()
    # כל מה שגולש עושה בעמוד חוץ מ"צור קישור": כתיבה, פתיחת השורה, בחירת ערכה, וייצוא שירד
    s.page.click(".cm-content")
    s.page.keyboard.type(" עוד טקסט")
    s.choose("pen-paper-coffee")
    s.download("pen-paper-coffee", tmp_path)
    s.page.wait_for_timeout(500)
    assert _carries_secret(s.requests) == [], _carries_secret(s.requests)
    assert all(method == "GET" for method, _t, _b in s.requests), s.requests

    before = len(s.requests)
    s.create_share("pen-paper-coffee")
    after = s.requests[before:]
    posts = [(t, json.loads(b)) for m, t, b in after if m == "POST"]
    # בקרה: הלחיצה היא ששלחה, בקשה אחת, עם הטקסט והערכה
    assert [t for t, _ in posts] == ["/api/markdown-editor/share"], after
    assert SECRET_WORD in posts[0][1]["markdown"] and posts[0][1]["theme"] == "pen-paper-coffee"
    assert s.errors == []


def test_a_document_over_the_ceiling_is_stopped_before_sending(browser, session, monkeypatch):
    import webapp.app as wa

    # התקרה שהעמוד מקבל היא הקבוע של השרת (``data-max-bytes``) — כאן קטנה, כדי שטקסט ההדגמה יעבור אותה
    monkeypatch.setattr(wa, "STYLED_SHARE_MAX_MARKDOWN_BYTES", 50)
    s = session()
    s.open_editor()
    s.choose("morass")
    before = len(s.requests)
    s.page.click("[data-md-editor-share-action=create]")
    poll(s.page, "document.querySelector('[data-md-editor-status]').textContent.includes('גדול')", "הודעת הגודל")
    assert [m for m, _t, _b in s.requests[before:] if m == "POST"] == []
    assert s.page.is_hidden("[data-md-editor-share-result]")


def test_the_daily_ceiling_is_explained(browser, session):
    from datetime import datetime, timezone

    from webapp.markdown_editor import PUBLIC_SHARE_DAILY_LIMIT

    filler = [{"origin": "public_editor", "created_at": datetime.now(timezone.utc)} for _ in range(PUBLIC_SHARE_DAILY_LIMIT)]
    browser.db.styled_shares.docs.extend(filler)
    try:
        s = session()
        s.open_editor()
        s.choose("morass")
        s.page.click("[data-md-editor-share-action=create]")
        poll(s.page, "document.querySelector('[data-md-editor-status]').textContent.includes('מכסה היומית')", "הודעת התקרה")
        # הכפתורים השתחררו אחרי הסירוב
        assert s.page.is_enabled("[data-md-editor-share-action=create]")
        assert s.page.is_enabled("[data-md-editor-export-action=download]")
    finally:
        for doc in filler:
            browser.db.styled_shares.docs.remove(doc)


# ---------------------------------------------------------------------------
# עמוד הקישור: אותו מסמך כמו הייצוא
# ---------------------------------------------------------------------------

#: מה שנמדד ב-``PROBE_FILE`` ושווה בין הקובץ שירד לעמוד הקישור. בלי ``header`` ו-``footer``: אלה נבדקים לחוד, ובלי
#: ``fontsLoaded``, שתלוי במה שהדף כבר צייר.
_SAME_KEYS = ("alerts", "code", "alignedCells", "nestedDepth", "tasks", "markBg", "strike", "h5h6", "anchors", "mermaid", "internal")


@pytest.mark.parametrize("theme_id", ["pen-paper-coffee", "morass", "everforest-dark"])
def test_the_share_page_shows_the_document_the_export_shows(browser, session, tmp_path, theme_id):
    s = session()
    s.open_editor()
    path = s.download(theme_id, tmp_path)
    share_url, _delete_url = s.create_share(theme_id)

    ctx, file_page, _attempts, _dialogs = open_file((browser.browser, browser.app), path)
    try:
        exported = file_page.evaluate(PROBE_FILE)
        file_title = file_page.title()
    finally:
        ctx.close()

    page = s.open_page(share_url)
    wait_rendered(page)
    shared = page.evaluate(PROBE_FILE)
    csp = page.evaluate("window.__csp")
    notice = page.inner_text("[data-testid=public-editor-share-notice]")
    title = page.title()
    status_line = page.query_selector("#ckShareStatus")

    assert {k: shared[k] for k in _SAME_KEYS} == {k: exported[k] for k in _SAME_KEYS}
    assert shared["katex"]["count"] == exported["katex"]["count"] == 5
    assert shared["katex"]["font"] == "KaTeX_Math" and shared["katex"]["pageScrollsSideways"] is False
    assert shared["mermaid"]["svgs"] == 3
    # בלי באנר של שם קובץ, עם הכיתוב של העורך בתחתית, וההודעה שהתוכן של גולש
    assert shared["header"] is False and "Code Keeper" in shared["footer"] and "Bot" not in shared["footer"]
    assert "גולש" in notice
    # שם העמוד — הכותרת הראשונה במסמך, כמו בקובץ שירד
    assert title == file_title and title != "מסמך"
    assert status_line is None
    assert csp == [], csp
    assert s.errors == []


@pytest.mark.parametrize("via", ["editor", "api"])
def test_injection_attempts_on_the_share_page_run_nothing(browser, session, via):
    s = session(draft=INJECTION_DOC)
    if via == "editor":
        s.open_editor()
        share_url, _delete = s.create_share("morass")
    else:
        # בקשה ישירה, שעוקפת את הממשק — מה שכל אחד יכול לשלוח
        resp = s.client.post("/api/markdown-editor/share", json={"markdown": INJECTION_DOC, "theme": "morass"})
        assert resp.status_code == 200, resp.get_data(as_text=True)
        share_url = local(resp.get_json()["share_url"])

    page = s.open_page(share_url)
    wait_rendered(page)
    found = page.evaluate(PROBE_INJECTION)
    # והשכבה השנייה: גם מה שעוקף את המנוע ונכנס לעמוד לא רץ — ה-CSP חוסם handler מוטמע
    page.evaluate(
        """() => { const d = document.createElement('div');
                   d.innerHTML = '<img src="x" onerror="window.__pwned = 1">'; document.body.appendChild(d); }"""
    )
    page.wait_for_timeout(500)
    pwned = page.evaluate("window.__pwned === 1")
    csp = page.evaluate("window.__csp")

    assert s.dialogs == [], s.dialogs
    assert found == {
        "onAttrs": 0, "javascriptUrls": 0, "scriptsInMain": 0, "rawShownAsText": True, "pwnedJson": False,
        "externalRel": ["ugc nofollow noreferrer"],
    }, found
    assert pwned is False
    assert any(v.startswith("script-src") for v in csp), csp  # הבקרה: ה-handler נחסם, ולא פשוט לא נוסה


# ---------------------------------------------------------------------------
# המחיקה
# ---------------------------------------------------------------------------


def test_the_delete_link_deletes_after_confirmation_and_leaves_the_address(browser, session):
    creator = session()
    creator.open_editor()
    share_url, delete_url = creator.create_share("morass")
    assert creator.share_status(share_url) == 200  # בקרה

    # מי שפותח את קישור המחיקה ומסרב — לא נמחק, והמפתח כבר לא בכתובת
    refuser = session()
    page = refuser.open_editor(delete_url)
    poll(page, "document.querySelector('[data-md-editor-status]').textContent.includes('לא נמחק')", "הסירוב")
    assert page.url == EDITOR and refuser.dialogs
    assert creator.share_status(share_url) == 200

    deleter = session(accept_dialogs=True)
    page = deleter.open_editor(delete_url)
    poll(page, "document.querySelector('[data-md-editor-status]').textContent.includes('נמחק,')", "המחיקה")
    assert page.url == EDITOR
    # המזהה בגוף, והמפתח בכותרת ``Authorization`` — לא בכתובת ולא בגוף
    key = delete_url.rsplit(".", 1)[1]
    [(target, body)] = [(t, b) for m, t, b in deleter.requests if m == "POST"]
    assert target == "/api/markdown-editor/share/delete" and set(json.loads(body)) == {"token"}
    assert key.encode() not in body and key not in target
    assert deleter.authorizations == [("/api/markdown-editor/share/delete", f"Bearer {key}")]
    assert creator.share_status(share_url) == 404


def test_delete_now_removes_the_link_just_created(session):
    s = session(accept_dialogs=True)
    s.open_editor()
    share_url, _delete_url = s.create_share("pen-paper-coffee")
    s.page.click("[data-md-editor-share-action=delete]")
    poll(s.page, "document.querySelector('[data-md-editor-share-result]').hidden", "האזור של הקישור נסגר")
    assert s.share_status(share_url) == 404
    assert s.page.input_value("[data-md-editor-share-delete-link]") == ""


def test_the_share_result_fits_a_phone_width(session):
    s = session(viewport={"width": 390, "height": 844})
    s.open_editor()
    s.create_share("morass")
    sideways = s.page.evaluate(
        "() => document.scrollingElement.scrollWidth > document.scrollingElement.clientWidth"
    )
    box = s.page.evaluate(
        """() => { const r = document.querySelector('[data-md-editor-share-result]').getBoundingClientRect();
                   return { left: r.left, right: r.right, width: innerWidth }; }"""
    )
    assert sideways is False
    assert box["left"] >= 0 and box["right"] <= box["width"], box


# ---------------------------------------------------------------------------
# כשרכיב הבקשות לא נטען
# ---------------------------------------------------------------------------


def test_a_delete_link_without_the_export_core_says_so_and_keeps_the_key(session):
    """``styled-export-core.js`` לא נטען: קישור המחיקה לא נבלע בשקט — הגולש מקבל הסבר, והקישור נשאר בכתובת, כדי
    שרענון ינסה שוב. וגם "צור קישור" אומר למה אינו עובד."""
    creator = session()
    creator.open_editor()
    share_url, delete_url = creator.create_share("morass")

    s = session(accept_dialogs=True, blocked=("/js/utils/styled-export-core.js",))
    page = s.open_page(delete_url)
    poll(page, "document.querySelector('[data-md-editor-status]').textContent.includes('אי אפשר למחוק')", "ההסבר")
    assert page.url == delete_url
    assert s.dialogs == []
    assert [t for m, t, _b in s.requests if m == "POST"] == []
    assert creator.share_status(share_url) == 200

    page.click("[data-md-editor-export-toggle]")
    page.click("[data-md-editor-share-action=create]")
    poll(page, "document.querySelector('[data-md-editor-status]').textContent.includes('ליצור קישור')", "ההסבר ליצירה")


# ---------------------------------------------------------------------------
# המחיקה של אדמין
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_is_1(monkeypatch):
    import webapp.app as wa

    monkeypatch.setattr(wa, "is_admin", lambda uid: uid == 1)


def _status(page):
    return page.inner_text("#styledShareStatus")


def test_an_admin_deletes_a_pasted_link_after_confirming(browser, session, admin_is_1):
    guest = session()
    resp = guest.client.post("/api/markdown-editor/share", json={"markdown": "# לדיווח\n", "theme": "morass"})
    share_url = local(resp.get_json()["share_url"])
    assert guest.share_status(share_url) == 200  # בקרה

    # סירוב באישור — לא נמחק, ולא נשלחה בקשה
    refuser = session(user_id=1)
    page = refuser.open_page(f"http://{HOST}/admin/styled-shares")
    page.fill("#styledShareLink", share_url)
    page.click("#styledShareDelete")
    page.wait_for_timeout(300)
    assert refuser.dialogs and [t for m, t, _b in refuser.requests if m == "POST"] == []
    assert guest.share_status(share_url) == 200

    admin = session(user_id=1, accept_dialogs=True)
    page = admin.open_page(f"http://{HOST}/admin/styled-shares")
    page.fill("#styledShareLink", share_url)
    page.click("#styledShareDelete")
    poll(page, "document.querySelector('#styledShareStatus').textContent.startsWith('נמחק')", "המחיקה")
    assert "גולש" in _status(page) and page.input_value("#styledShareLink") == ""
    assert page.is_enabled("#styledShareDelete")
    assert guest.share_status(share_url) == 404
    assert admin.errors == []

    # ועכשיו אותו קישור שוב — כבר אין מה למחוק, וזה נאמר
    page.fill("#styledShareLink", share_url)
    page.click("#styledShareDelete")
    poll(page, "document.querySelector('#styledShareStatus').textContent.includes('לא נמצא')", "הקישור כבר נמחק")


def test_an_admin_paste_that_is_not_a_link_is_explained(session, admin_is_1):
    admin = session(user_id=1, accept_dialogs=True)
    page = admin.open_page(f"http://{HOST}/admin/styled-shares")
    page.fill("#styledShareLink", "https://[ck.example/shared/styled/abc")
    page.click("#styledShareDelete")
    poll(page, "document.querySelector('#styledShareStatus').textContent.includes('לא קישור מעוצב')", "הסירוב")
    assert page.is_enabled("#styledShareDelete")


def test_the_admin_page_without_the_export_core_says_so(session, admin_is_1):
    admin = session(user_id=1, accept_dialogs=True, blocked=("/js/utils/styled-export-core.js",))
    page = admin.open_page(f"http://{HOST}/admin/styled-shares")
    page.fill("#styledShareLink", "z" * 43)
    page.click("#styledShareDelete")
    poll(page, "document.querySelector('#styledShareStatus').textContent.includes('לא נטען')", "ההסבר")
    assert admin.dialogs == [] and [t for m, t, _b in admin.requests if m == "POST"] == []


def test_the_admin_delete_works_in_a_browser_without_abortsignal_timeout(session, admin_is_1):
    """דפדפן שאינו מכיר ``AbortSignal.timeout`` (Safari לפני 16): הבקשה עדיין יוצאת עם תקרת זמן, מ-``AbortController``
    (``StyledExportCore.timeoutSignal``), ולא נכשלת לפני שהיא נשלחת."""
    guest = session()
    resp = guest.client.post("/api/markdown-editor/share", json={"markdown": "# ישן\n", "theme": "morass"})
    share_url = local(resp.get_json()["share_url"])

    admin = session(user_id=1, accept_dialogs=True)
    admin.ctx.add_init_script("delete AbortSignal.timeout;")
    page = admin.open_page(f"http://{HOST}/admin/styled-shares")
    assert page.evaluate("typeof AbortSignal.timeout") == "undefined"  # בקרה
    page.fill("#styledShareLink", share_url)
    page.click("#styledShareDelete")
    poll(page, "document.querySelector('#styledShareStatus').textContent.startsWith('נמחק')", "המחיקה")
    assert guest.share_status(share_url) == 404
