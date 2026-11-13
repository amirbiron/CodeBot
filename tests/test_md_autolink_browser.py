"""שם קובץ במסמך Markdown נשאר טקסט, וכתובת עם פרוטוקול נשארת קישור — בכרומיום אמיתי, בכל המשטחים שמרנדרים Markdown.

**הבאג.** markdown-it נוצר עם ``linkify: true``, ו-linkify-it ניחש כתובות גם בלי פרוטוקול: כל ``מילה.XX`` שבה XX הוא
קוד מדינה. בתצוגה החיה בעמוד העריכה ``myAgent-spec.md`` ו-``myAgent-spec.py`` הוצגו כקישור ל-``http://myAgent-spec.md``,
והלחיצה הובילה לדף שגיאה של הדפדפן. התיקון הוא ``md-linkify-plugin.js``, שמכבה את הניחוש בכל רנדרר (ההסבר בראש
הקובץ), וההתנהגות של markdown-it עצמה נבדקת ב-``tests/md-linkify-plugin.test.js``.

**המשטחים, בעמודים האמיתיים** (``TESTING-PATTERNS.md`` T1), כמו ב-``tests/test_rtl_inner_fences_browser.py``: תצוגת
המסמך (``/md/<id>``), התצוגה החיה בעמוד העריכה (``/edit/<id>``, דרך הכפתור — המקום של הדיווח), דפדפן הריפו
(``/repo/``, הרנדרר ``default`` שגם כרטיסי החיפוש בתיעוד משתמשים בו), ודפדפן הריפו כש-``live-preview.js`` לא נטען, כלומר
מסלול הגיבוי ``renderMarkdownFallback`` ב-``repo-browser.js``. השרת הוא הוובאפ האמיתי (``admin_live_server``), המסד הוא
הדמה של מונגו (``_fake_mongo``), ובדפדפן הריפו ה-API של הריפו מזויף. בקשות לכל מארח אחר נקטעות.

**מה נבדק:** הקישורים בתוכן הם בדיוק הכתובת עם הפרוטוקול, המייל וה-``[טקסט](כתובת)`` — לאותה כתובת; שמות הקבצים
ו-``www.example.com`` מוצגים כטקסט; ואין בקונסול אזהרה שהתוסף לא נטען.

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
from _fake_mongo import FakeDB

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

#: ``admin_live_server`` בונה session למשתמש 1, ולכן הקובץ שלו.
USER_ID = 1
FILE_OID = ObjectId("0123456789abcdef0123ab42")

#: טאבלט 12 אינץ' לרוחב, בפיקסלים לוגיים.
TABLET = {"width": 1280, "height": 800}

#: השמות מהדיווח, שורה לכל שם כמו בצילום, ושורה של כתובות. לפני כל כתובת רווח ולא ``ו-``: linkify-it מזהה מייל
#: רק אחרי רווח או סימן פיסוק מסוים (``tpl_email_fuzzy`` ב-``node_modules/linkify-it/lib/re.mjs``), ו-``ו-someone@example.com``
#: לא היה קישור גם לפני התיקון.
FILE_NAMES = [
    "מדריך-תצוגת-Markdown-RTL.md",
    "package.json",
    "myAgent-spec.md",
    "myAgent-spec.ms",
    "myAgent-spec.py",
    "myAgent-spec.ht",
]
MARKDOWN = (
    "# קבצים\n\n"
    + "\n".join(FILE_NAMES)
    + "\n\nכתובות: https://example.com/guide וגם someone@example.com וגם [מדריך](https://example.com/docs)"
    " וגם www.example.com\n"
)

#: הקישורים שמותר שיהיו בתוכן, כ-``[טקסט, href]``, לפי הסדר.
EXPECTED_LINKS = [
    ["https://example.com/guide", "https://example.com/guide"],
    ["someone@example.com", "mailto:someone@example.com"],
    ["מדריך", "https://example.com/docs"],
]

#: האזהרה שהרנדררים כותבים לקונסול כשהתוסף לא נטען.
MISSING_PLUGIN_WARNING = "md-linkify-plugin.js לא נטען"

ROOTS = {
    "md_preview": "#md-content",
    "live_preview": "[data-preview-canvas]",
    "repo_browser": "#markdown-preview-content",
    "repo_fallback": "#markdown-preview-content",
}

#: הקישורים בתוכן שאינם עוגנים בתוך העמוד (``¶`` של כותרת, תוכן עניינים), ואם כל שמות הקבצים כבר שם.
LINKS_JS = """([root, last]) => {
  const c = document.querySelector(root);
  if (!c || c.textContent.indexOf(last) < 0) return 'not rendered yet';
  const links = [...c.querySelectorAll('a[href]')]
    .filter((a) => !(a.getAttribute('href') || '').startsWith('#'))
    .map((a) => [a.textContent.trim(), a.getAttribute('href')]);
  return {ok: true, links, text: c.textContent};
}"""

#: הקובץ שדפדפן הריפו מציג. ``DEFAULT_REPO_NAME`` ב-``webapp/routes/repo_browser.py``.
REPO = "CodeBot"
REPO_MD_PATH = "docs/files.md"


def _repo_api(route) -> None:
    """ה-API של הריפו מזויף, כמו ב-``tests/test_rtl_inner_fences_browser.py``. כל השאר לשרת."""
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


@pytest.fixture(scope="module")
def site(admin_live_server, chromium_executable):
    """הוובאפ מול מסד הדמה, ודפדפן אחד למודול — **המקום היחיד שמרים דפדפן כאן**."""
    import webapp.app as wa

    db = FakeDB()
    db["code_snippets"].insert_one({
        "_id": FILE_OID,
        "user_id": USER_ID,
        "file_name": "files.md",
        "code": MARKDOWN,
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
    """העמוד של המשטח, אחרי שהתוכן רונדר. מחזיר ``(state, console)``."""
    console: list[str] = []
    if surface in ("repo_browser", "repo_fallback"):
        context = browser.new_context(viewport=TABLET, locale="he-IL")
        context.add_cookies([{
            "name": "session", "value": server.session_cookie, "domain": "127.0.0.1", "path": "/",
        }])
        context.add_init_script("try{localStorage.setItem('repo-browser-markdown-preview','true');}catch(e){}")
        page = context.new_page()
        page.on("console", lambda msg: console.append(msg.text))
        blocked = "/static/js/live-preview.js" if surface == "repo_fallback" else None
        page.route("**/*", lambda route: route.abort()
                   if blocked and urlsplit(route.request.url).path == blocked else _repo_api(route))
        page.goto(f"{server.base_url}/repo/#file={REPO_MD_PATH}", wait_until="load")
    else:
        path = f"/md/{FILE_OID}" if surface == "md_preview" else f"/edit/{FILE_OID}"
        page, _touch = open_admin_page(browser, server, path, viewport=TABLET)
        context = page.context
        page.on("console", lambda msg: console.append(msg.text))
        if surface == "live_preview":
            page.click('[data-action="toggle-live-preview"]')
    try:
        state = poll(page, LINKS_JS, f"{surface}: התוכן רונדר", [ROOTS[surface], FILE_NAMES[-1]])
        if surface == "repo_fallback":
            # בקרה: אילו ``live-preview.js`` נטען בכל זאת, הבדיקה הייתה עוברת במסלול הרגיל.
            assert page.evaluate("() => typeof window.MarkdownLiveRenderer") == "undefined", (
                "repo_fallback: MarkdownLiveRenderer נטען — המסלול שנבדק אינו renderMarkdownFallback"
            )
        yield state, console
    finally:
        context.close()


@pytest.mark.parametrize("surface", list(ROOTS))
def test_file_names_stay_text_and_written_links_stay_links(site, surface):
    browser, server = site
    with opened(surface, browser, server) as (state, console):
        pass
    assert state["links"] == EXPECTED_LINKS, state["links"]
    for name in FILE_NAMES:
        assert name in state["text"], f"{name} לא מוצג בתוכן"
    assert "www.example.com" in state["text"], state["text"]
    assert not [line for line in console if MISSING_PLUGIN_WARNING in line], console
