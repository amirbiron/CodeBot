"""דפדפן הריפו בוובאפ: כל קוד שבדיקת ה-ref מחזירה מגיע עם סטטוס שהמפה מכירה.

``/repo/api/history`` ו-``/repo/api/file-at-commit/<commit>`` ממפים את קוד השגיאה של
``GitMirrorService`` לסטטוס HTTP, ו-500 הוא ברירת המחדל של קוד שהמפה אינה מכירה.
שני השירותים שמאחוריהם (``get_file_history``, ``get_file_at_commit``) מעבירים את קוד
הבדיקה של ``_validate_ref_with_git`` כמות שהוא — ולכן כל קוד שהבדיקה מסוגלת להחזיר
חייב שורה בשתי המפות. בלעדיה, ענף שלא במראה (``ref_not_mirrored``) היה נהיה 500:
זה מה שנמדד על הקוד לפני שהמפות עודכנו.

**רשימת הקודים אינה כתובה כאן.** היא נקראת מקוד המקור של הבדיקה (``ast``), וטסט
נפרד מריץ את הבדיקה האמיתית עד שכל קוד ברשימה באמת חוזר ממנה. קוד חדש שיתווסף שם
יופיע ברשימה לבד, ויפיל את הטסט של המפות עד שיקבל סטטוס — בלי שמישהו יזכור לעדכן
רשימה בטסט.

הריפואים, המראות וכל קלט/פלט — תחת ``tmp_path``.
"""

from __future__ import annotations

import ast
import inspect
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from flask import Flask

from services import git_mirror_service
from services.git_mirror_service import GitMirrorService
from webapp.routes.repo_browser import repo_bp

_GIT = shutil.which("git")
requires_git = pytest.mark.skipif(_GIT is None, reason="git is not installed")

#: הסטטוס שכל קוד של הבדיקה מקבל בשני ה-routes. קוד שחסר כאן נופל ב-KeyError
#: בטסט של המפות — וזו הכוונה: קוד חדש דורש החלטה, לא 500 שקט. ל-``git_error`` ול-
#: ``internal_error`` 500 הוא ההחלטה (תקלה של השרת), ולכן במקרה שלהם הטסט אינו
#: יכול להבדיל בין שורה במפה לבין ברירת המחדל — שתיהן נכונות.
_EXPECTED_STATUS = {
    "invalid_ref": 400,
    "ref_not_mirrored": 404,
    "git_error": 500,
    "timeout": 504,
    "internal_error": 500,
}

_ROUTES = {
    "history": "/repo/api/history?repo={repo}&file=a.md&ref={ref}",
    "file-at-commit": "/repo/api/file-at-commit/{ref}?repo={repo}&file=a.md",
}


def _git(*args: str, cwd: Path) -> str:
    done = subprocess.run((_GIT, *args), cwd=str(cwd), check=True, capture_output=True, text=True)
    return done.stdout.strip()


def _mirrors(tmp_path: Path) -> GitMirrorService:
    """ריפו ``r`` עם ``a.md`` ב-``main`` ומראה שלו, ו-``plain.git`` — תיקייה שאינה ריפו."""
    work = tmp_path / "work"
    work.mkdir()
    (work / "a.md").write_text("# a\n", encoding="utf-8")
    _git("init", "-q", "-b", "main", ".", cwd=work)
    _git("add", "-A", cwd=work)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init", cwd=work)
    mirrors = tmp_path / "mirrors"
    mirrors.mkdir()
    _git("clone", "-q", "--mirror", str(work), str(mirrors / "r.git"), cwd=tmp_path)
    (mirrors / "plain.git").mkdir()
    return GitMirrorService(base_path=str(mirrors))


@pytest.fixture
def client(tmp_path, monkeypatch):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test"
    app.extensions["git_mirror_service"] = _mirrors(tmp_path)
    # דפדפן הקוד חסום לאדמינים — אותו ``webapp.app`` מדומה כמו ב-``tests/test_git_history.py``.
    stub = ModuleType("webapp.app")
    stub.is_admin = lambda uid: int(uid) == 999
    stub.is_impersonating_safe = lambda: False
    monkeypatch.setitem(sys.modules, "webapp.app", stub)
    app.register_blueprint(repo_bp)
    test_client = app.test_client()
    with test_client.session_transaction() as sess:
        sess["user_id"] = 999
    return test_client


def _codes_written_in_the_check() -> set[str]:
    """כל ערך של ``"error"`` שכתוב ב-``_validate_ref_with_git`` — מהמקור, לא מרשימה כאן."""
    source = textwrap.dedent(inspect.getsource(GitMirrorService._validate_ref_with_git))
    codes: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and key.value == "error":
                assert isinstance(value, ast.Constant) and isinstance(value.value, str), (
                    "קוד error שאינו מחרוזת מפורשת — הטסט הזה לא יכול לראות אותו")
                codes.add(value.value)
    return codes


# ===========================================================================
# 1. המצבים האמיתיים, על מראה אמיתית
# ===========================================================================


@requires_git
@pytest.mark.parametrize("route", sorted(_ROUTES))
def test_a_malformed_ref_and_a_ref_the_mirror_lacks_get_their_own_status(client, route):
    def get(repo: str, ref: str):
        response = client.get(_ROUTES[route].format(repo=repo, ref=ref))
        return response.status_code, response.get_json()

    status, body = get("r", "no-such-branch")
    assert (status, body["error"]) == (404, "ref_not_mirrored")
    assert "לא נמצא במראה" in body["message"]

    status, body = get("r", "bad:ref")
    assert (status, body["error"]) == (400, "invalid_ref")

    # מראה שבורה היא תקלה של השרת, לא ענף חסר — והמפה מכירה את הקוד שלה.
    status, body = get("plain", "main")
    assert (status, body["error"]) == (500, "git_error")

    status, _ = get("r", "main")
    assert status == 200


# ===========================================================================
# 2. כל קוד שהבדיקה מסוגלת להחזיר — מגיע, ויש לו סטטוס בשתי המפות
# ===========================================================================


@requires_git
def test_every_code_written_in_the_check_really_comes_back_from_it(tmp_path, monkeypatch):
    """הרשימה שנקראת מהמקור היא בדיוק מה שהבדיקה מחזירה — לא פחות ולא יותר."""
    svc = _mirrors(tmp_path)
    driven = {
        svc._validate_ref_with_git("r", "bad:ref")["error"],
        svc._validate_ref_with_git("r", "refs/heads/nope")["error"],
        svc._validate_ref_with_git("plain", "refs/heads/main")["error"],
    }

    def timing_out(*args: Any, **kwargs: Any):
        raise subprocess.TimeoutExpired(args[0], 10)

    def exploding(*args: Any, **kwargs: Any):
        raise OSError("boom")

    for replacement in (timing_out, exploding):
        with monkeypatch.context() as patched:
            patched.setattr(git_mirror_service.subprocess, "run", replacement)
            driven.add(svc._validate_ref_with_git("r", "refs/heads/main")["error"])

    assert driven == _codes_written_in_the_check()


@requires_git
@pytest.mark.parametrize("route", sorted(_ROUTES))
def test_every_code_the_check_can_return_has_a_status_in_both_routes(client, monkeypatch, route):
    """הלולאה בגוף הטסט ולא ב-``parametrize``: כך קוד המקור נקרא כשהטסט רץ, ולא באיסוף."""
    codes = sorted(_codes_written_in_the_check())
    assert codes, "לא נמצא אף קוד בבדיקה — הטסט לא היה בודק כלום"
    for code in codes:
        def failing_check(self, repo_name: str, ref: str, timeout: float = 10, _code: str = code) -> dict[str, Any]:
            return {"valid": False, "error": _code, "message": "m"}

        with monkeypatch.context() as patched:
            patched.setattr(GitMirrorService, "_validate_ref_with_git", failing_check)
            response = client.get(_ROUTES[route].format(repo="r", ref="main"))

        assert response.get_json()["error"] == code
        assert code in _EXPECTED_STATUS, (
            f"{code} חוזר מ-_validate_ref_with_git ואין לו סטטוס — הוסף אותו לשתי המפות ב-"
            "webapp/routes/repo_browser.py ול-_EXPECTED_STATUS כאן")
        assert response.status_code == _EXPECTED_STATUS[code], code
