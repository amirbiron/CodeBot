"""התצוגה המרונדרת של עמוד rst בדפדפן הריפו — בכרומיום אמיתי, מול הוובאפ האמיתי.

**מה נבדק כאן ולא בבדיקות השרת.** ``tests/test_repo_browser_docs_page.py`` מוכיח מה השרת מחזיר, ו-
``tests/repo-browser-docs-page.test.js`` מה הסקריפט עושה עם זה ב-DOM מדומה. מה שרק דפדפן מראה: שהעמוד
באמת מרונדר, מימין לשמאל ועם קוד משמאל לימין (עיצוב ``markdown-preview.css`` על הרינדור של
``MarkdownLiveRenderer``), שההודעה מוצגת כשהקובץ השתנה, ושקובץ בלי עמוד נשאר קוד — בלי שגיאות JS.

השרת הוא הוובאפ האמיתי (``admin_live_server``). ``/repo/api/file`` ו-``/repo/api/docs-page`` מגיעים
אליו: המסד הוא הדמה של מונגו, שהמעבר האמיתי מילא (``_docs_index_harness``), והמראה היא מראה git
אמיתית תחת ``tmp_path``. את שאר ה-API של העמוד (העץ, רשימת הריפואים, הפתקים) הבדיקה עונה בעצמה, כמו
ב-``tests/test_rtl_inner_fences_browser.py``.

מדולג כשאין Chromium (וב-CI אין: ראו ``docs/testing.rst``), וכשאין git.
"""

from __future__ import annotations

import contextlib
import json
from urllib.parse import unquote, urlsplit

import pytest

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import poll
from _docs_index_harness import fill, make_world, page, section
from _fake_mongo import FakeDB
from _git_mirror_harness import GIT, RepoWithMirror

from services import docs_search_contract as contract
from services.git_mirror_service import GitMirrorService

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

pytestmark = pytest.mark.skipif(GIT is None, reason="git is not installed")

#: טאבלט 12 אינץ' לרוחב, כמו בשאר בדיקות הדפדפן של הוובאפ.
TABLET = {"width": 1280, "height": 800}
REPO = contract.SOURCE_REPO_NAME
RST = "docs/webapp/code-browser.rst"
API_RST = "docs/api/handlers.rst"


def _pages():
    """עמוד שיש בו כל מה שהכיוון נוגע בו: פסקה בעברית, קוד בשורה, בלוק קוד עם שפה, טבלה והערה."""
    return [
        page(
            "webapp/code-browser.html", RST,
            section("code-browser", "דפדפן קוד", markdown="ייבוא ריפו לדפדפן הקוד, עם `initial_import`."),
            section(
                "import", "דפדפן קוד", "ייבוא ריפו חדש", title_markdown="ייבוא ריפו חדש",
                markdown=(
                    "יש להריץ את הפקודה:\n\n```python\nres = initial_import(\"url\", \"שם\", get_db())\n```\n\n"
                    "| שדה | ערך |\n| --- | --- |\n| Secret | הסוד |\n\n::: warning\nודאו שהסוד תואם.\n:::"
                ),
            ),
        ),
    ]


@pytest.fixture
def world(tmp_path, monkeypatch):
    """אינדקס שנבנה מהבנייה של הקומיט ``built``, והוובאפ האמיתי מול אותו מסד ומול המראה."""
    from webapp.routes import repo_browser

    repo = RepoWithMirror(tmp_path, REPO)
    built = repo.commit({RST: "דפדפן קוד\n=========\n", API_RST: "api\n===\n"})
    world = make_world(monkeypatch, FakeDB())
    fill(world, pages=_pages(), commit=built)
    for path in (RST, API_RST):
        world.db.repo_files.insert_one({"repo_name": REPO, "path": path, "commit_sha": built, "language": "text"})
    world.db.repo_metadata.insert_one({"repo_name": REPO, "default_branch": "main"})
    mirror_service = GitMirrorService(base_path=str(repo.mirrors))
    monkeypatch.setattr(repo_browser, "get_mirror_service", lambda: mirror_service)
    monkeypatch.setattr(repo_browser, "get_db", lambda: world.db)
    world.repo = repo
    return world


def _page_api(route) -> None:
    """הקובץ והעמוד — לשרת. העץ, רשימת הריפואים והפתקים — מכאן. מארח אחר — נחסם."""
    url = urlsplit(route.request.url)
    if url.hostname != "127.0.0.1":
        route.abort()
        return
    path = unquote(url.path)
    body = None
    if path.startswith(("/repo/api/file/", "/repo/api/docs-page/")):
        route.continue_()
        return
    if path == "/repo/api/tree":
        body = [{"name": "docs", "path": "docs", "type": "directory"}]
    elif path == "/repo/api/repos":
        body = {"success": True, "repos": [{"repo_name": REPO}], "current": REPO, "current_source": "default"}
    elif path.startswith("/repo/api/"):
        body = {"success": True, "types": []}
    elif path.startswith("/api/sticky-notes/"):
        body = {"ok": True, "notes": []}
    elif path.startswith("/api/collections/"):
        # ``collections.js`` שואל על מטא-דאטה של תגיות, ובלי מסד השרת עונה בדף שגיאה. ``ok: false`` הוא
        # התשובה שאחריה הוא נשאר עם ברירת המחדל שלו.
        body = {"ok": False}
    if body is None:
        route.continue_()
    else:
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))


#: שגיאות טעינה של משאבים, שאינן של הפיצ'ר: משאב חיצוני שהבדיקה חסמה, וסקריפטים מ-cdnjs. ``repo/base_repo.html``
#: טוען משם את CodeMirror 5 ואת highlight.js, וה-CSP של הוובאפ (``_add_default_csp`` ב-``webapp/app.py``) אינו מתיר
#: סקריפטים מ-cdnjs. נמדד גם על הקוד שלפני השינוי הזה (19.10.2026): אותן חסימות, בדיוק באותו עמוד.
_KNOWN_LOAD_ERRORS = ("Failed to load resource", "Refused to load the script 'https://cdnjs.cloudflare.com/")


@contextlib.contextmanager
def repo_page(server, executable):
    """דפדפן הריפו, עם העדפה לתצוגה מרונדרת כמו אצל מי שבחר בה. מחזיר ``(page, errors)``: שגיאות JS
    שלא נתפסו, ושגיאות קונסול שאינן טעינה של משאב חיצוני שהבדיקה חסמה. **המקום היחיד שמרים דפדפן כאן.**"""
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=executable)
        except PlaywrightError as exc:  # pragma: no cover - תלוי בסביבה
            pytest.skip(f"אין Chromium זמין: {exc}")
        try:
            context = browser.new_context(viewport=TABLET, locale="he-IL")
            context.add_cookies([{
                "name": "session", "value": server.session_cookie, "domain": "127.0.0.1", "path": "/",
            }])
            context.add_init_script("try{localStorage.setItem('repo-browser-markdown-preview','true');}catch(e){}")
            tab = context.new_page()
            errors = []
            tab.on("pageerror", lambda exc: errors.append(str(exc)))
            tab.on("console", lambda msg: errors.append(msg.text)
                   if msg.type == "error" and not msg.text.startswith(_KNOWN_LOAD_ERRORS) else None)
            tab.route("**/*", _page_api)
            yield tab, errors
        finally:
            browser.close()


def _open(tab, server, path):
    tab.goto(f"{server.base_url}/repo/#file={path}", wait_until="load")


#: הכיוון של כל מה שהעמוד המרונדר מציג: המיכל, הכותרת והפסקה, וכל בלוק קוד.
_DIRECTIONS = """
() => {
  const root = document.getElementById('markdown-preview-content');
  const dir = (el) => el ? getComputedStyle(el).direction : null;
  return {
    container: dir(document.getElementById('markdown-preview-container')),
    heading: dir(root.querySelector('h1')),
    paragraph: dir(root.querySelector('p')),
    table: dir(root.querySelector('table')),
    code: Array.from(root.querySelectorAll('pre')).map((pre) => dir(pre)),
  };
}
"""

_RENDERED = "() => !!document.querySelector('#markdown-preview-content h1')"


def test_an_rst_page_is_rendered_right_to_left_with_its_code_left_to_right(
    world, admin_live_server, chromium_executable
):
    with repo_page(admin_live_server, chromium_executable) as (tab, errors):
        _open(tab, admin_live_server, RST)
        poll(tab, _RENDERED, "העמוד מאתר התיעוד רונדר")

        # הרינדור מוסיף לכל כותרת סימן עוגן (``¶``), כמו בתצוגת ה-Markdown של כל קובץ.
        heading = tab.evaluate(
            "() => document.querySelector('#markdown-preview-content h1').textContent.replace('¶', '').trim()"
        )
        assert heading == "דפדפן קוד"
        directions = tab.evaluate(_DIRECTIONS)
        assert directions["container"] == directions["heading"] == directions["paragraph"] == "rtl", directions
        assert directions["code"] and set(directions["code"]) == {"ltr"}, directions
        toggle = tab.evaluate(
            "() => { const b = document.getElementById('markdown-preview-toggle');"
            " return {shown: getComputedStyle(b).display !== 'none', title: b.title}; }"
        )
        assert toggle == {"shown": True, "title": "תצוגה מרונדרת מאתר התיעוד (Ctrl+Shift+M)"}
        assert tab.evaluate("() => document.getElementById('markdown-preview-note').hidden") is True
    assert errors == [], "\n".join(errors)


def test_a_file_that_changed_after_the_build_shows_the_note(world, admin_live_server, chromium_executable):
    later = world.repo.commit({RST: "דפדפן קוד\n=========\n\nפסקה חדשה.\n"})
    world.db.repo_files.update_one({"repo_name": REPO, "path": RST}, {"$set": {"commit_sha": later}})

    with repo_page(admin_live_server, chromium_executable) as (tab, errors):
        _open(tab, admin_live_server, RST)
        poll(tab, _RENDERED, "העמוד מאתר התיעוד רונדר")

        note = tab.evaluate(
            "() => { const n = document.getElementById('markdown-preview-note');"
            " return {hidden: n.hidden, shown: n.getBoundingClientRect().height > 0, text: n.textContent}; }"
        )
    assert note == {
        "hidden": False, "shown": True, "text": "התצוגה מהבנייה האחרונה של אתר התיעוד; הקובץ השתנה מאז",
    }
    assert errors == [], "\n".join(errors)


def test_an_rst_file_without_a_page_stays_code(world, admin_live_server, chromium_executable):
    with repo_page(admin_live_server, chromium_executable) as (tab, errors):
        _open(tab, admin_live_server, API_RST)
        poll(tab, "() => document.getElementById('code-header').style.display === 'flex'", "הקובץ נטען")

        shown = tab.evaluate(
            "() => ({toggle: document.getElementById('markdown-preview-toggle').style.display,"
            " preview: document.getElementById('markdown-preview-container').style.display})"
        )
    assert shown == {"toggle": "none", "preview": "none"}
    assert errors == [], "\n".join(errors)
