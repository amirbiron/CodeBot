"""קישור במסמך Markdown שמוביל לעמוד נפתח בלשונית חדשה, ועוגן בתוך המסמך נשאר — בכרומיום אמיתי, בכל המשטחים.

**השינוי.** עד היום לחיצה על קישור בתצוגה של מסמך החליפה את העמוד: בתצוגת המסמך איבדה את המקום בקריאה, ובתצוגה החיה
בעמוד העריכה עזבה את העורך. התוסף ``md-link-target-plugin.js`` כותב ``target="_blank"`` ו-``rel="noopener noreferrer"``
על כל קישור לעמוד, בכל רנדרר (הכלל וההסבר בראש התוסף; הכלל עצמו נבדק מול טבלה
ב-``tests/md-link-target-plugin.test.js``).

**המשטחים, בעמודים האמיתיים** (``TESTING-PATTERNS.md`` T1), כמו ב-``tests/test_md_autolink_browser.py``: תצוגת המסמך
(``/md/<id>``), התצוגה החיה בעמוד העריכה (``/edit/<id>``, דרך הכפתור), העורך הציבורי (``/markdown-editor``, עם טיוטה
בדפדפן), דפדפן הריפו (``/repo/``, הרנדרר ``default`` שגם כרטיסי החיפוש בתיעוד משתמשים בו), ודפדפן הריפו כש-
``live-preview.js`` לא נטען — מסלול הגיבוי ``renderMarkdownFallback`` ב-``repo-browser.js``. בעורך הציבורי נבדק גם
הייצוא (``MarkdownLiveRenderer.renderForExport``, הסוג ``export``), שממנו נבנים הקובץ שיורד וקישור השיתוף. השרת הוא
הוובאפ האמיתי (``admin_live_server``), המסד הוא הדמה של מונגו, ובדפדפן הריפו ה-API של הריפו מזויף. בקשות לכל מארח אחר
נקטעות.

**מה נבדק בכל משטח:**

- המאפיינים: כל קישור לעמוד — ``[טקסט](כתובת)``, כתובת חשופה, כתובת באתר עצמו — עם ``target="_blank"`` ו-
  ``rel="noopener noreferrer"``; קישור פנימי, תוכן העניינים, ``¶`` ומייל — בלי.
- הלחיצה עצמה, שהיא מה שהדפדפן עושה עם המאפיינים: לחיצה על הקישור לאתר פותחת לשונית חדשה בכתובת שלו, והעמוד נשאר; לחיצה
  על הקישור הפנימי לא פותחת לשונית.
- אין בקונסול אזהרה שהתוסף לא נטען.

כרטיסי החיפוש בתיעוד (``/files``) אינם כאן: העמוד מריץ צינורות ``aggregate`` שהדמה של המסד אינה מכירה, ולכן הבדיקה שלו
(``tests/test_docs_search_card_browser.py``) רצה רק מול מונגו אמיתי. הם מרנדרים בסוג ``default`` — זה שדפדפן הריפו בודק
כאן — והטעינה של התוסף ב-``files.html`` נבדקת ב-``tests/md-link-target-plugin.test.js``.

מדולג כשאין Chromium (וב-CI אין: ראו ``docs/testing.rst``).
"""

from __future__ import annotations

import contextlib
import json
import time
from urllib.parse import unquote, urlsplit

import pytest
from bson import ObjectId

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import open_admin_page, poll
from _fake_mongo import FakeDB

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

#: ``admin_live_server`` בונה session למשתמש 1, ולכן הקובץ שלו.
USER_ID = 1
FILE_OID = ObjectId("0123456789abcdef0123ab43")

#: טאבלט 12 אינץ' לרוחב, בפיקסלים לוגיים.
TABLET = {"width": 1280, "height": 800}

#: הקובץ באתר שהקישור המקומי מוביל אליו — קטן, סטטי, ולא דורש התחברות.
LOCAL_TARGET_PATH = "/static/manifest.json"

#: המסמך. ``{local}`` — כתובת מלאה בשרת של הבדיקה, כדי שהלשונית שנפתחת תיטען בלי לצאת לרשת.
MARKDOWN_TEMPLATE = (
    "${{toc}}\n\n"
    "# פתיחה\n\n"
    "קישור [לאתר]({local}), [מדריך](https://example.com/docs), כתובת חשופה https://example.com/guide,"
    " [פנימי](#פתיחה) ומייל someone@example.com.\n\n"
    "## סוף\n\nשורה אחרונה.\n"
)
LAST_TEXT = "שורה אחרונה."

ROOTS = {
    "md_preview": "#md-content",
    "live_preview": "[data-preview-canvas]",
    "public_editor": "[data-preview-canvas]",
    "repo_browser": "#markdown-preview-content",
    "repo_fallback": "#markdown-preview-content",
}

#: הקישורים בתוכן, אחרי שהתוכן רונדר.
LINKS_JS = """([root, last]) => {
  const c = document.querySelector(root);
  if (!c || c.textContent.indexOf(last) < 0) return 'not rendered yet';
  const links = [...c.querySelectorAll('a[href]')].map((a) => ({
    text: a.textContent.trim(),
    href: a.getAttribute('href'),
    target: a.getAttribute('target'),
    rel: a.getAttribute('rel'),
  }));
  return {ok: true, links};
}"""

#: האזהרה שהרנדררים כותבים לקונסול כשהתוסף לא נטען.
MISSING_PLUGIN_WARNING = "md-link-target-plugin.js לא נטען"

#: הטיוטה של העורך הציבורי. ``STORAGE_KEY`` ו-``loadDraft`` ב-``webapp/static/js/markdown-editor.js``.
PUBLIC_EDITOR_DRAFT_KEY = "markdownEditorDraft.v1"

#: הקובץ שדפדפן הריפו מציג. ``DEFAULT_REPO_NAME`` ב-``webapp/routes/repo_browser.py``.
REPO = "CodeBot"
REPO_MD_PATH = "docs/links.md"

NEW_TAB = ("_blank", "noopener noreferrer")
SAME_TAB = (None, None)


def _markdown(server) -> str:
    return MARKDOWN_TEMPLATE.format(local=f"{server.base_url}{LOCAL_TARGET_PATH}")


def _repo_api(markdown: str):
    """ה-API של הריפו מזויף, כמו ב-``tests/test_md_autolink_browser.py``. כל השאר לשרת."""
    def handle(route) -> None:
        url = urlsplit(route.request.url)
        if url.hostname != "127.0.0.1":
            route.abort()
            return
        path = unquote(url.path)
        body = None
        if path == f"/repo/api/file/{REPO_MD_PATH}":
            body = {"content": markdown, "language": "markdown", "path": REPO_MD_PATH}
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
    return handle


@pytest.fixture(scope="module")
def site(admin_live_server, chromium_executable):
    """הוובאפ מול מסד הדמה, ודפדפן אחד למודול — **המקום היחיד שמרים דפדפן כאן**."""
    import webapp.app as wa

    db = FakeDB()
    db["code_snippets"].insert_one({
        "_id": FILE_OID,
        "user_id": USER_ID,
        "file_name": "links.md",
        "code": _markdown(admin_live_server),
        "programming_language": "markdown",
        "version": 1,
        "is_active": True,
    })
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(wa, "get_db", lambda: db)
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(executable_path=chromium_executable) if chromium_executable \
                    else pw.chromium.launch()
            except PlaywrightError as exc:  # pragma: no cover - תלוי בסביבה
                pytest.skip(f"אין Chromium זמין: {exc}")
            try:
                yield browser, admin_live_server
            finally:
                browser.close()


@contextlib.contextmanager
def opened(surface: str, browser, server):
    """העמוד של המשטח, אחרי שהתוכן רונדר. מחזיר ``(page, state, console)``."""
    console: list[str] = []
    markdown = _markdown(server)
    if surface in ("repo_browser", "repo_fallback"):
        context = browser.new_context(viewport=TABLET, locale="he-IL")
        context.add_cookies([{
            "name": "session", "value": server.session_cookie, "domain": "127.0.0.1", "path": "/",
        }])
        context.add_init_script("try{localStorage.setItem('repo-browser-markdown-preview','true');}catch(e){}")
        page = context.new_page()
        page.on("console", lambda msg: console.append(msg.text))
        blocked = "/static/js/live-preview.js" if surface == "repo_fallback" else None
        api = _repo_api(markdown)
        page.route("**/*", lambda route: route.abort()
                   if blocked and urlsplit(route.request.url).path == blocked else api(route))
        page.goto(f"{server.base_url}/repo/#file={REPO_MD_PATH}", wait_until="load")
    else:
        path, storage = {
            "md_preview": (f"/md/{FILE_OID}", None),
            "live_preview": (f"/edit/{FILE_OID}", None),
            "public_editor": ("/markdown-editor", {
                PUBLIC_EDITOR_DRAFT_KEY: json.dumps({"code": markdown, "savedAt": 1}),
            }),
        }[surface]
        page, _touch = open_admin_page(browser, server, path, viewport=TABLET, local_storage=storage)
        context = page.context
        page.on("console", lambda msg: console.append(msg.text))
        if surface == "live_preview":
            page.click('[data-action="toggle-live-preview"]')
    # הלשונית שנפתחת מהקישור טוענת רק מהשרת של הבדיקה; כל מארח אחר נקטע גם בה.
    context.route("**/*", lambda route: route.abort()
                  if urlsplit(route.request.url).hostname != "127.0.0.1" else route.fallback())
    try:
        state = poll(page, LINKS_JS, f"{surface}: התוכן רונדר", [ROOTS[surface], LAST_TEXT])
        if surface == "repo_fallback":
            # בקרה: אילו ``live-preview.js`` נטען בכל זאת, הבדיקה הייתה עוברת במסלול הרגיל.
            assert page.evaluate("() => typeof window.MarkdownLiveRenderer") == "undefined", (
                "repo_fallback: MarkdownLiveRenderer נטען — המסלול שנבדק אינו renderMarkdownFallback"
            )
        yield page, state, console
    finally:
        context.close()


def _by_text(links: list, text: str) -> list:
    return [(a["target"], a["rel"]) for a in links if a["text"] == text]


@pytest.mark.parametrize("surface", list(ROOTS))
def test_page_links_open_in_a_new_tab_and_anchors_stay(site, surface):
    browser, server = site
    with opened(surface, browser, server) as (page, state, console):
        links = state["links"]
        assert _by_text(links, "לאתר") == [NEW_TAB], links
        assert _by_text(links, "מדריך") == [NEW_TAB], links
        assert _by_text(links, "https://example.com/guide") == [NEW_TAB], links
        assert _by_text(links, "someone@example.com") == [SAME_TAB], links
        assert _by_text(links, "פנימי") == [SAME_TAB], links
        # כל עוגן בתוכן — תוכן העניינים, ``¶``, הקישור הפנימי — בלי target. בלי הבדיקה על הכמות, תוכן עניינים שלא רונדר
        # היה משאיר רק את הקישור הפנימי, והבדיקה הייתה עוברת בלי לבדוק אותו. מסלול הגיבוי (``renderMarkdownFallback``)
        # הוא markdown-it בלי תוספים — בלי תוכן עניינים ובלי ``¶`` — ולכן שם יש רק הקישור הפנימי.
        fragments = [a for a in links if (a["href"] or "").startswith("#")]
        assert len(fragments) >= (1 if surface == "repo_fallback" else 2), links
        assert all((a["target"], a["rel"]) == SAME_TAB for a in fragments), fragments

        start_url = page.url
        context = page.context
        local = page.locator(f'{ROOTS[surface]} a', has_text="לאתר")
        with context.expect_page(timeout=10000) as popup_info:
            local.click()
        popup = popup_info.value
        popup.wait_for_load_state()
        assert urlsplit(popup.url).path == LOCAL_TARGET_PATH, popup.url
        assert page.url == start_url, "העמוד המקורי עזב את הכתובת שלו"
        popup.close()

        pages_before = len(context.pages)
        page.locator(f'{ROOTS[surface]} a', has_text="פנימי").click()
        # לשונית חדשה נפתחת מיד בלחיצה; חצי שנייה מספיקה כדי שהיא תופיע אם הייתה נפתחת.
        time.sleep(0.5)
        assert len(context.pages) == pages_before, "לחיצה על עוגן פתחה לשונית"

        if surface == "public_editor":
            exported = page.evaluate(
                """async (text) => {
                  const box = await window.MarkdownLiveRenderer.renderForExport(text, {});
                  return [...box.querySelectorAll('a[href]')]
                    .map((a) => [a.textContent.trim(), a.getAttribute('target')]);
                }""",
                _markdown(server),
            )
            assert ["מדריך", "_blank"] in exported, exported
            assert ["פנימי", None] in exported, exported
    assert not [line for line in console if MISSING_PLUGIN_WARNING in line], console
