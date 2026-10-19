"""דפדפן הריפו בכרומיום אמיתי, מול הוובאפ האמיתי — העולם והדפדפן של בדיקות הדפדפן של דפדפן הריפו.

פונקציות ולא fixtures (T3), כמו ``_docs_index_harness.py``. משמש את
``test_repo_browser_docs_page_browser.py`` ואת ``test_repo_browser_in_file_search_browser.py``, כדי שהרמת
העולם והדפדפן תיכתב פעם אחת.

השרת הוא הוובאפ האמיתי (``admin_live_server``). ``/repo/api/file`` ו-``/repo/api/docs-page`` מגיעים
אליו: המסד הוא הדמה של מונגו, שהמעבר האמיתי מילא (``_docs_index_harness``), והמראה היא מראה git
אמיתית תחת ``tmp_path``. את שאר ה-API של העמוד (העץ, רשימת הריפואים, הפתקים) הבדיקה עונה בעצמה, כמו
ב-``tests/test_rtl_inner_fences_browser.py``.
"""

from __future__ import annotations

import contextlib
import json
from typing import Dict, List
from urllib.parse import unquote, urlsplit

import pytest

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _docs_index_harness import fill, make_world
from _fake_mongo import FakeDB
from _git_mirror_harness import RepoWithMirror

from services import docs_search_contract as contract
from services.git_mirror_service import GitMirrorService

#: טאבלט 12 אינץ' לרוחב, כמו בשאר בדיקות הדפדפן של הוובאפ.
TABLET = {"width": 1280, "height": 800}
REPO = contract.SOURCE_REPO_NAME


def mirror_world(tmp_path, monkeypatch, files: Dict[str, str], pages: List[dict]):
    """אינדקס שנבנה מהבנייה של הקומיט ``built`` (שבו ``files``), והוובאפ האמיתי מול אותו מסד ומול המראה.

    מחזיר את העולם של ``make_world``, ועליו גם ``repo`` (המראה) ו-``built`` (הקומיט). כל קובץ ב-``files``
    רשום ב-``repo_files`` של אותו קומיט, והוא גם הקומיט האחרון שהמראה סונכרנה אליו.
    """
    from webapp.routes import repo_browser

    repo = RepoWithMirror(tmp_path, REPO)
    built = repo.commit(files)
    world = make_world(monkeypatch, FakeDB())
    fill(world, pages=pages, commit=built)
    for path in files:
        world.db.repo_files.insert_one({"repo_name": REPO, "path": path, "commit_sha": built, "language": "text"})
    world.db.repo_metadata.insert_one({"repo_name": REPO, "default_branch": "main", "last_synced_sha": built})
    mirror_service = GitMirrorService(base_path=str(repo.mirrors))
    monkeypatch.setattr(repo_browser, "get_mirror_service", lambda: mirror_service)
    # ההיסטוריה עוברת ב-``get_git_service``, ששומר את השירות על האפליקציה (``app.extensions``) בקריאה
    # הראשונה. השרת משותף לטסטים, ולכן בלי זה ההיסטוריה הייתה רצה מול מראה של טסט קודם (נמדד: הטסט של
    # ההיסטוריה נכשל רק כשרץ אחרי טסטים אחרים של דפדפן הריפו).
    monkeypatch.setattr(repo_browser, "get_git_service", lambda: mirror_service)
    monkeypatch.setattr(repo_browser, "get_db", lambda: world.db)
    world.repo = repo
    world.built = built
    return world


def page_api(route) -> None:
    """הקובץ, העמוד וההיסטוריה של הקובץ — לשרת. העץ, רשימת הריפואים והפתקים — מכאן. מארח אחר — נחסם."""
    url = urlsplit(route.request.url)
    if url.hostname != "127.0.0.1":
        route.abort()
        return
    path = unquote(url.path)
    body = None
    if path.startswith(("/repo/api/file/", "/repo/api/docs-page/", "/repo/api/history", "/repo/api/file-at-commit/")):
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
KNOWN_LOAD_ERRORS = ("Failed to load resource", "Refused to load the script 'https://cdnjs.cloudflare.com/")


@contextlib.contextmanager
def repo_page(server, executable, *, rendered: bool = True, viewport: dict = TABLET):
    """דפדפן הריפו. ``rendered`` — העדפה לתצוגה מרונדרת, כמו אצל מי שבחר בה. מחזיר ``(page, errors)``:
    שגיאות JS שלא נתפסו, ושגיאות קונסול שאינן טעינה של משאב חיצוני שהבדיקה חסמה. **המקום היחיד שמרים
    דפדפן לבדיקות דפדפן הריפו.**"""
    # בלי ``try`` סביב היבוא: מודול שמשתמש בפונקציה הזו מדלג קודם, ב-``pytest.importorskip("playwright")``.
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=executable)
        except PlaywrightError as exc:  # pragma: no cover - תלוי בסביבה
            pytest.skip(f"אין Chromium זמין: {exc}")
        try:
            context = browser.new_context(viewport=viewport, locale="he-IL")
            context.add_cookies([{
                "name": "session", "value": server.session_cookie, "domain": "127.0.0.1", "path": "/",
            }])
            preference = "true" if rendered else "false"
            context.add_init_script(
                f"try{{localStorage.setItem('repo-browser-markdown-preview','{preference}');}}catch(e){{}}"
            )
            tab = context.new_page()
            errors = []
            tab.on("pageerror", lambda exc: errors.append(str(exc)))
            tab.on("console", lambda msg: errors.append(msg.text)
                   if msg.type == "error" and not msg.text.startswith(KNOWN_LOAD_ERRORS) else None)
            tab.route("**/*", page_api)
            yield tab, errors
        finally:
            browser.close()


def open_file(tab, server, path) -> None:
    tab.goto(f"{server.base_url}/repo/#file={path}", wait_until="load")
