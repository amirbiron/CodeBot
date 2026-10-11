"""דפדפן הקוד, "ערוך / העתק" והאינדקס של הריפו מקבלים מהמראה את הקובץ כמו שהוא בריפו — ו"ערוך / העתק" פתוח לאדמין בלבד.

הטסטים עוברים בממשק שהצרכן משתמש בו: ``/repo/api/file/<path>``, שממנו ``repo-browser.js``
טוען את הקובץ; ``/upload/from-repo``, שהקישור "ערוך / העתק קטעים" בדפדפן הקוד פותח; ו-
``initial_import``, שבונה את האינדקס. המראה היא מראה git אמיתית תחת ``tmp_path``. המסד הוא
דמה, כי התוכן נקרא מהמראה ולא ממנו.

השורש — ``_run_git_command`` העביר את ה-stdout של git ב-``_sanitize_output`` — נבדק בטסטים
של השירות, ב-``tests/test_git_mirror_service.py``.
"""

from __future__ import annotations

import html
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, Tuple

import pytest
from flask import Flask

from services import git_mirror_service, repo_sync_service
from services.git_mirror_service import GitMirrorService
from webapp.routes import repo_browser
from webapp.routes.repo_browser import repo_bp

_GIT = shutil.which("git")
requires_git = pytest.mark.skipif(_GIT is None, reason="git is not installed")

#: שתי הדוגמאות מהפרודקשן. ``key = index_info.get("key")`` הוצג ``key=***``, ובקובץ השני
#: ``OWNER_CHAT_ID=`` נבלע לתוך ``BOT_TOKEN=***``, כך שהקובץ הוצג בשורה אחת פחות. והשלישי
#: קובץ Windows: ``text=True`` של ``subprocess`` החליף את ה-CRLF וה-CR הבודד שבו ב-LF.
_FILES = {
    "ttl_index.py": 'def ttl_key(index_info):\n    key = index_info.get("key")\n    return key\n',
    "TESTS_LANGUAGE_DETECTION_EDIT_VIEW.md": "# === Bot Configuration ===\nBOT_TOKEN=\nOWNER_CHAT_ID=\n",
    "windows.txt": "line one\r\nline two\r\nold mac\rend\n",
}

_ADMIN_ID = 999
_USER_ID = 2


def _git(*args: str, cwd: Path) -> str:
    assert _GIT is not None, "הטסטים שקוראים לכאן מסומנים ב-requires_git"
    done = subprocess.run(
        # ``core.autocrlf=false``: בלעדיו git עלול לנרמל את ה-CRLF כבר ב-``add``
        (_GIT, "-c", "user.email=t@t", "-c", "user.name=t", "-c", "core.autocrlf=false", *args),
        cwd=str(cwd), check=True, capture_output=True, text=True,
    )
    return done.stdout.strip()


def _mirror(tmp_path: Path) -> Tuple[GitMirrorService, str]:
    """ריפו עם ``_FILES`` בקומיט אחד, ומראה ``probe`` שלו; מחזיר את השירות ואת ה-sha."""
    work = tmp_path / "work"
    work.mkdir()
    for name, text in _FILES.items():
        # בתים ולא ``write_text``: במצב טקסט כל ``\n`` נכתב כ-``os.linesep``, ובווינדוס ``\r\n`` היה נכתב ``\r\r\n``
        (work / name).write_bytes(text.encode("utf-8"))
    _git("init", "-q", "-b", "main", ".", cwd=work)
    _git("add", "-A", cwd=work)
    _git("commit", "-qm", "init", cwd=work)
    mirrors = tmp_path / "mirrors"
    mirrors.mkdir()
    _git("clone", "-q", "--mirror", str(work), str(mirrors / "probe.git"), cwd=tmp_path)
    return GitMirrorService(base_path=str(mirrors)), _git("rev-parse", "HEAD", cwd=work)


class _FindOne:
    def __init__(self, doc: Dict[str, Any]) -> None:
        self.doc = doc

    def find_one(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return dict(self.doc)

    def distinct(self, *args: Any, **kwargs: Any) -> list:
        return []


# ===========================================================================
# 1. דפדפן הקוד: ``/repo/api/file/<path>``
# ===========================================================================


@pytest.fixture
def browser(tmp_path, monkeypatch):
    svc, sha = _mirror(tmp_path)

    class _Db:
        # קובץ שאונדקס נושא את הקומיט שבו אונדקס, ו-``api_get_file`` קורא בו
        repo_files = _FindOne({"commit_sha": sha, "language": "text"})
        repo_metadata = _FindOne({"default_branch": "main"})

    monkeypatch.setattr(repo_browser, "get_mirror_service", lambda: svc)
    monkeypatch.setattr(repo_browser, "get_db", lambda: _Db())
    # דפדפן הקוד חסום לאדמינים — אותו ``webapp.app`` מדומה כמו ב-``tests/test_repo_browser_ref_errors.py``.
    stub = ModuleType("webapp.app")
    stub.is_admin = lambda uid: int(uid) == _ADMIN_ID
    stub.is_impersonating_safe = lambda: False
    monkeypatch.setitem(sys.modules, "webapp.app", stub)

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test"
    app.register_blueprint(repo_bp)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = _ADMIN_ID
    return client


@requires_git
@pytest.mark.parametrize("path", sorted(_FILES))
def test_the_code_browser_gets_the_file_exactly_as_in_the_repo(browser, path):
    response = browser.get(f"/repo/api/file/{path}?repo=probe")

    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()["content"] == _FILES[path]


# ===========================================================================
# 2. "ערוך / העתק": ``/upload/from-repo``
# ===========================================================================


@pytest.fixture
def upload(tmp_path, monkeypatch):
    """האפליקציה האמיתית, עם המראה של הטסט ומסד מדומה; מחזיר פונקציה שמבקשת את הקובץ בשם משתמש."""
    from webapp import app as webapp_app

    svc, _ = _mirror(tmp_path)

    class _Db:
        repo_metadata = _FindOne({})
        code_snippets = _FindOne({})

    # הראוט מייבא את ``get_mirror_service`` מהמודול בזמן הבקשה
    monkeypatch.setattr(git_mirror_service, "get_mirror_service", lambda: svc)
    monkeypatch.setattr(webapp_app, "get_db", lambda: _Db())
    monkeypatch.setenv("ADMIN_USER_IDS", str(_ADMIN_ID))

    def get(path: str, user_id: int):
        client = webapp_app.app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["user_data"] = {"id": user_id, "first_name": "Test"}
        # אותה צורה שהקישור ב-``repo-browser.js`` בונה: ``path`` ו-``repo``
        return client.get(f"/upload/from-repo?path={path}&repo=probe")

    return get


def _code_field(page: str) -> str:
    """התוכן ש-``codeTextarea`` נושא ב-HTML שהשרת שלח, לפני שהדפדפן מפרסר אותו.

    בדפדפן ערך של textarea לא מחזיק CR (``docs/quality/code-normalization.md``), ולכן בקובץ עם
    CRLF או CR בודד הטופס עצמו מחזיק LF.
    """
    match = re.search(r'<textarea id="codeTextarea"[^>]*>(.*?)</textarea>', page, re.S)
    assert match, "אין textarea של קוד בעמוד"
    return html.unescape(match.group(1))


@requires_git
@pytest.mark.parametrize("path", sorted(_FILES))
def test_edit_from_repo_puts_the_file_into_the_page_exactly_as_in_the_repo(upload, path):
    """השרת שם את הקובץ ב-HTML של הטופס תו בתו. מה שהטופס מחזיק בדפדפן — ראו ``_code_field``."""
    response = upload(path, _ADMIN_ID)

    assert response.status_code == 200
    assert _code_field(response.get_data(as_text=True)) == _FILES[path]


@requires_git
def test_edit_from_repo_is_closed_to_a_user_who_is_not_an_admin(upload):
    """דפדפן הקוד חסום לאדמינים, ו"ערוך / העתק" קורא מאותן מראות — ולכן גם הוא.

    עד התיקון הראוט היה מוגן ב-``login_required`` בלבד: משתמש מחובר שאינו אדמין קיבל את
    תוכן הקובץ, מכל מראה, בזמן ש-``/repo/api/file`` החזיר לו 403.
    """
    response = upload("TESTS_LANGUAGE_DETECTION_EDIT_VIEW.md", _USER_ID)

    assert response.status_code == 403
    assert "OWNER_CHAT_ID" not in response.get_data(as_text=True)


# ===========================================================================
# 3. האינדקס: ``initial_import``
# ===========================================================================


@requires_git
def test_the_index_counts_the_file_as_it_is_in_the_repo(tmp_path, monkeypatch):
    """``lines`` ו-``size`` באינדקס מחושבים מהתוכן שהאינדוקס קרא מ-``get_file_content``.

    עד התיקון זה היה התוכן אחרי הניקוי: השורה שנבלעה הורידה את ``lines``, והתו שהוחלף
    שינה את ``size``. ``lines`` הוא מה ש-``codekeeper_list_repo_tree`` מחזיר לסוכנים.
    """
    svc, _ = _mirror(tmp_path)
    written: Dict[str, Dict[str, Any]] = {}

    class _Files:
        def update_one(self, filt, update, upsert=False):
            written[filt["path"]] = update["$set"]

        def distinct(self, field, filt=None):
            return []

        def count_documents(self, filt):
            return len(written)

    class _Metadata:
        def update_one(self, filt, update, upsert=False):
            return None

    class _Db:
        repo_files = _Files()
        repo_metadata = _Metadata()

    monkeypatch.setattr(repo_sync_service, "get_mirror_service", lambda: svc)

    out = repo_sync_service.initial_import("https://github.com/o/probe.git", "probe", _Db())

    assert out.get("status") == "completed", out
    for path, text in _FILES.items():
        assert written[path]["lines"] == len(text.splitlines()), path
        assert written[path]["size"] == len(text), path
