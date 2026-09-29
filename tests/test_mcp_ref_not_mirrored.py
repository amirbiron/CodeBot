"""ענף שלא במראה מול קובץ שלא קיים — דרך ממשק ה-MCP, על מראות git אמיתיות.

**הבאג.** ``codekeeper_get_repo_file`` החזיר ``{"ok": false, "error": "not_found"}``
גם לקובץ שאינו קיים וגם לכל נתיב בענף שהמראה עוד לא משכה — ובלי לומר איזה ענף
או איזה commit נבדקו. סוכן שקיבל את זה הסיק "ההפניה שבורה", כשבפועל המראה פשוט
לא ראתה את הענף. ``codekeeper_list_repo_tree`` איחד עוד יותר: ריפו בלי מראה, שם
פגום וענף שלא במראה היו כולם ``repo_or_ref_not_found``.

**העולם כאן.** ב-``amir-bug-patterns`` יש ``main`` ו-``feature`` שנמשכו, ו-``late``
שנוצר במקור **אחרי** ה-``clone --mirror`` — ענף שנדחף אחרי המשיכה האחרונה, בדיוק
המקרה שהקוד קיים בשבילו. ה-``origin`` של המראה הוא הריפו המקומי, ולכן ``git fetch``
היה מביא את ``late`` בהצלחה: טסט "אין משיכה" יכול להיכשל באמת. ב-``trunk-only``
המטא-דאטה אומרת ``main`` והמראה מחזיקה רק ``trunk`` — ענף ראשי שחסר במראה, המקרה
היחיד שבו ``search_repo`` ופריטי הבאץ' (שאינם מקבלים ``ref``) יכולים לענות
``ref_not_mirrored``. ``Broken.git`` היא תיקייה שאינה ריפו: מראה שבורה, שאסור
שתיקרא "ענף שלא במראה".

הכול תחת ``tmp_path``, ודרך ``mcp.call_tool`` עם זהות מטוקן (T1).
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp")

from mcp import types as mcp_types  # noqa: E402
from mcp.server.auth.middleware.auth_context import auth_context_var  # noqa: E402
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser  # noqa: E402
from mcp.server.auth.provider import AccessToken  # noqa: E402
from mcp.server.lowlevel.server import request_ctx  # noqa: E402
from mcp.shared.context import RequestContext  # noqa: E402

import mcp_server.server as srv  # noqa: E402
from mcp_server import read_batch  # noqa: E402
from mcp_server.repo_backend import INVALID_REF_MESSAGE, RepoBackend  # noqa: E402
from mcp_server.repo_handlers import MIRROR_REFRESH_NOTE  # noqa: E402
from services import git_mirror_service  # noqa: E402
from services.git_mirror_service import GitMirrorService  # noqa: E402

_GIT = shutil.which("git")
requires_git = pytest.mark.skipif(_GIT is None, reason="git is not installed")

_ADMIN = 4242
_MD = "amir-bug-patterns"  # מדיניות הסעיפים: שורש הריפו, .md
_RST = "CodeBot"  # מדיניות הסעיפים: docs/, .rst
_TRUNK = "trunk-only"  # המטא-דאטה אומרת main, והמראה מחזיקה רק trunk
_BROKEN = "Broken"  # תיקיית מראה שאינה ריפו

_MD_MAIN = {
    "CRITICAL-PATTERNS.md": "# דפוסים קריטיים\n\n## K11. כשל שנבלע\n\nגוף K11.\n",
    "hooks/primer.sh": "echo hi\n",
}
_MD_FEATURE = {
    "NEW-ONLY-ON-FEATURE.md": "# חדש\n\n## סעיף\n\nקיים רק ב-feature.\n",
    "new-dir/x.md": "# x\n",
}

#: מה שקריאה לקריאה בלבד מריצה. כל תת-פקודה אחרת של git במסלולים האלה היא
#: שינוי מצב — ``fetch`` היא זו שהכלל אוסר במפורש.
_READ_ONLY_GIT = frozenset({"rev-parse", "ls-tree", "cat-file", "show", "grep"})


def _git(*args: str, cwd: Path) -> str:
    done = subprocess.run((_GIT, *args), cwd=str(cwd), check=True, capture_output=True, text=True)
    return done.stdout.strip()


def _commit(work: Path, files: dict[str, str], message: str) -> None:
    for name, body in files.items():
        target = work / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body.encode("utf-8"))
    _git("add", "-A", cwd=work)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", message, cwd=work)


def _repo(tmp_path: Path, name: str, branch: str, files: dict[str, str]) -> Path:
    work = tmp_path / "work" / name
    work.mkdir(parents=True)
    _git("init", "-q", "-b", branch, ".", cwd=work)
    _commit(work, files, "init")
    return work


def _clone_mirror(tmp_path: Path, work: Path, name: str) -> Path:
    target = tmp_path / "mirrors" / f"{name}.git"
    _git("clone", "-q", "--mirror", str(work), str(target), cwd=tmp_path)
    return target


class _Collection:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self.docs = docs

    def find_one(self, query: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any] | None:
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return dict(doc)
        return None


@dataclass
class _World:
    mcp: Any
    mirror: GitMirrorService
    mirrors: Path
    md_work: Path
    sync_jobs: _Collection
    main_sha: str
    feature_sha: str


def _world(tmp_path: Path, monkeypatch: Any) -> _World:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("MCP_DOCS_REPO", f"{_MD},{_RST}")
    monkeypatch.setenv("REPO_MIRROR_PATH", str(tmp_path / "unused-default"))
    from config import config as _cfg

    monkeypatch.setattr(_cfg, "ADMIN_USER_IDS", [_ADMIN], raising=False)

    (tmp_path / "mirrors").mkdir()
    md_work = _repo(tmp_path, _MD, "main", _MD_MAIN)
    _git("checkout", "-q", "-b", "feature", cwd=md_work)
    _commit(md_work, _MD_FEATURE, "feature")
    _git("checkout", "-q", "main", cwd=md_work)
    _clone_mirror(tmp_path, md_work, _MD)
    # ``late`` נוצר במקור אחרי המשיכה: המראה לא ראתה אותו, ו-``git fetch`` היה מביא אותו.
    _git("checkout", "-q", "-b", "late", cwd=md_work)
    _commit(md_work, {"LATE.md": "# מאוחר\n"}, "late")
    _git("checkout", "-q", "main", cwd=md_work)

    _clone_mirror(tmp_path, _repo(tmp_path, _RST, "main", {
        "docs/guide.rst": "Guide\n=====\n\nIntro.\n",
        "docs/notes.md": "# Notes\n\n## A\n",
    }), _RST)
    _clone_mirror(tmp_path, _repo(tmp_path, _TRUNK, "trunk", {"README.md": "# r\n"}), _TRUNK)
    broken = tmp_path / "mirrors" / f"{_BROKEN}.git"
    broken.mkdir()
    (broken / "file.txt").write_text("not a repository\n", encoding="utf-8")

    sync_jobs = _Collection([])
    db = {
        "repo_metadata": _Collection([
            {"repo_name": name, "default_branch": "main"} for name in (_MD, _RST, _TRUNK, _BROKEN)
        ]),
        "sync_jobs": sync_jobs,
    }
    mirror = GitMirrorService(base_path=str(tmp_path / "mirrors"))
    # המנוע של החיפוש בונה מראה משלו בבנאי (``get_mirror_service``); הקיבוע כאן
    # הוא על המפעל, כמו ב-``tests/test_mcp_search_total.py``.
    from services import repo_search_service as rss

    monkeypatch.setattr(rss, "get_mirror_service", lambda: mirror)
    search = rss.RepoSearchService(db=None)
    backend = RepoBackend(db=db, mirror=mirror, search_service=search)
    mcp = srv.build_mcp(object(), repo_backend=backend)
    return _World(
        mcp, mirror, tmp_path / "mirrors", md_work, sync_jobs,
        main_sha=_git("rev-parse", "main", cwd=md_work),
        feature_sha=_git("rev-parse", "feature", cwd=md_work),
    )


@contextlib.contextmanager
def _as(user: int):
    request_token = request_ctx.set(RequestContext(request_id=1, meta=None, session=None, lifespan_context=None))
    access = AccessToken(token="t", client_id="c", scopes=["read"], subject=str(user))
    auth_token = auth_context_var.set(AuthenticatedUser(access))
    try:
        yield
    finally:
        auth_context_var.reset(auth_token)
        request_ctx.reset(request_token)


async def _call(mcp: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    with _as(_ADMIN):
        result = await mcp.call_tool(name, arguments)
    content = result.content if isinstance(result, mcp_types.CallToolResult) else result
    (block,) = content
    return json.loads(block.text)


def _assert_not_in_mirror(answer: dict[str, Any], *, repo: str, ref: str, **where: Any) -> None:
    """הצורה של ``ref_not_mirrored`` — והניסוח: "לא במראה", לא "לא קיים"."""
    message = answer.pop("message")
    assert answer == {"ok": False, "error": "ref_not_mirrored", "repo": repo, "ref": ref, **where}
    assert "not in this host's mirror" in message
    assert "not the same as not existing on GitHub" in message
    assert MIRROR_REFRESH_NOTE in message


# ===========================================================================
# 1. שלושת המצבים, בכל כלי שמקבל ref
# ===========================================================================


@requires_git
@pytest.mark.parametrize("mode", [{}, {"lines": [1, 2]}, {"outline": True}], ids=["whole", "lines", "outline"])
async def test_get_repo_file_tells_the_three_states_apart(tmp_path, monkeypatch, mode):
    world = _world(tmp_path, monkeypatch)

    missing_ref = await _call(world.mcp, "codekeeper_get_repo_file",
                              {"repo": _MD, "path": "CRITICAL-PATTERNS.md", "ref": "late", **mode})
    _assert_not_in_mirror(missing_ref, repo=_MD, ref="late", path="CRITICAL-PATTERNS.md")

    missing_file = await _call(world.mcp, "codekeeper_get_repo_file",
                               {"repo": _MD, "path": "NOPE.md", "ref": "feature", **mode})
    assert missing_file == {"ok": False, "error": "not_found", "ref": "feature",
                            "resolved_commit": world.feature_sha}

    present = await _call(world.mcp, "codekeeper_get_repo_file",
                          {"repo": _MD, "path": "NEW-ONLY-ON-FEATURE.md", "ref": "feature", **mode})
    assert present["ok"] is True
    assert present["file"]["ref"] == "feature"
    assert present["file"]["resolved_commit"] == world.feature_sha


@requires_git
async def test_not_found_names_the_default_branch_it_read_when_no_ref_was_given(tmp_path, monkeypatch):
    world = _world(tmp_path, monkeypatch)
    answer = await _call(world.mcp, "codekeeper_get_repo_file", {"repo": _MD, "path": "NOPE.md"})
    assert answer == {"ok": False, "error": "not_found", "ref": "refs/heads/main",
                      "resolved_commit": world.main_sha}


@requires_git
async def test_docs_get_section_tells_the_three_states_apart(tmp_path, monkeypatch):
    world = _world(tmp_path, monkeypatch)

    missing_ref = await _call(world.mcp, "codekeeper_docs_get_section",
                              {"repo": _MD, "path": "CRITICAL-PATTERNS", "ref": "late"})
    _assert_not_in_mirror(missing_ref, repo=_MD, ref="late", path="CRITICAL-PATTERNS.md")

    # עד כאן ``not_found`` של הכלי הזה נשא רק ``repo`` ו-``path``.
    missing_file = await _call(world.mcp, "codekeeper_docs_get_section",
                               {"repo": _MD, "path": "NOPE", "ref": "feature"})
    assert missing_file == {"ok": False, "error": "not_found", "ref": "feature",
                            "resolved_commit": world.feature_sha, "repo": _MD, "path": "NOPE.md"}

    present = await _call(world.mcp, "codekeeper_docs_get_section",
                          {"repo": _MD, "path": "NEW-ONLY-ON-FEATURE", "ref": "feature"})
    assert present["ok"] is True and present["mode"] == "toc"
    assert present["ref"] == "feature" and present["resolved_commit"] == world.feature_sha


@requires_git
async def test_list_repo_tree_tells_the_three_states_apart(tmp_path, monkeypatch):
    """בעץ "קובץ חסר" הוא תיקייה שאין בענף: ``ok`` עם ``total: 0`` — ועכשיו גם באיזה commit."""
    world = _world(tmp_path, monkeypatch)

    missing_ref = await _call(world.mcp, "codekeeper_list_repo_tree", {"repo": _MD, "ref": "late"})
    _assert_not_in_mirror(missing_ref, repo=_MD, ref="late", path=None)

    empty = await _call(world.mcp, "codekeeper_list_repo_tree",
                        {"repo": _MD, "ref": "feature", "path": "no-such-dir"})
    assert empty["ok"] is True and empty["total"] == 0 and empty["paths"] == []
    assert empty["resolved_commit"] == world.feature_sha

    present = await _call(world.mcp, "codekeeper_list_repo_tree",
                          {"repo": _MD, "ref": "feature", "path": "new-dir"})
    assert present["paths"] == ["new-dir/x.md"]
    assert present["ref"] == "feature" and present["resolved_commit"] == world.feature_sha


# ===========================================================================
# 2. פגום מול חסר — שני קודים, ומראה שבורה אינה "ענף חסר"
# ===========================================================================

_REF_TOOLS = [
    ("codekeeper_get_repo_file", {"repo": _MD, "path": "CRITICAL-PATTERNS.md"}, {"path": "CRITICAL-PATTERNS.md"}),
    ("codekeeper_docs_get_section", {"repo": _MD, "path": "CRITICAL-PATTERNS"}, {"path": "CRITICAL-PATTERNS.md"}),
    ("codekeeper_list_repo_tree", {"repo": _MD}, {"path": None}),
]


@requires_git
@pytest.mark.parametrize("tool, arguments, where", _REF_TOOLS, ids=[t[0] for t in _REF_TOOLS])
async def test_a_malformed_ref_and_a_ref_the_mirror_lacks_are_two_codes(tmp_path, monkeypatch, tool, arguments, where):
    """‏``bad:ref`` לא עובר את ``BASIC_REF_PATTERN`` — git לא נשאל עליו בכלל, והקורא יכול לתקן.

    ‏``late`` ו-SHA שאינו במראה עוברים אותו ו-git לא מוצא אותם. עד כאן שלושתם
    היו ``not_found`` (ובעץ ``repo_or_ref_not_found``).
    """
    world = _world(tmp_path, monkeypatch)

    malformed = await _call(world.mcp, tool, {**arguments, "ref": "bad:ref"})
    assert malformed == {"ok": False, "error": "invalid_ref", "repo": _MD, "ref": "bad:ref",
                         **where, "message": INVALID_REF_MESSAGE}

    for ref in ("late", "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"):
        _assert_not_in_mirror(await _call(world.mcp, tool, {**arguments, "ref": ref}),
                              repo=_MD, ref=ref, **where)


@requires_git
async def test_a_broken_mirror_is_not_called_a_ref_the_mirror_lacks(tmp_path, monkeypatch):
    """תיקייה שאינה ריפו: ``rev-parse`` יוצא ב-128 ולא ב-1, והתשובה היא כשל קריאה.

    **המוטציה שהטסט הזה מפיל:** "כל יציאה שאינה 0 ← ``ref_not_mirrored``". היא
    הייתה מחזירה בדיוק את האיחוד שהתיקון הזה מפרק, רק רמה אחת למטה: מראה שבורה
    הייתה נקראת "הענף עוד לא נמשך", והסוכן היה מחכה לרענון שלא יעזור.
    """
    world = _world(tmp_path, monkeypatch)
    records: list[logging.LogRecord] = []

    class _Keep(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    target = logging.getLogger(git_mirror_service.__name__)
    handler = _Keep(logging.WARNING)
    target.addHandler(handler)
    try:
        read = await _call(world.mcp, "codekeeper_get_repo_file", {"repo": _BROKEN, "path": "file.txt"})
        tree = await _call(world.mcp, "codekeeper_list_repo_tree", {"repo": _BROKEN})
    finally:
        target.removeHandler(handler)

    assert read == {"ok": False, "error": "read_failed"}
    assert tree == {"ok": False, "error": "read_failed"}
    warnings = [r.getMessage() for r in records if "rev-parse failed" in r.getMessage()]
    assert warnings and all("exit 128" in text and "not a git repository" in text for text in warnings)


@requires_git
def test_the_split_is_born_in_the_ref_check_by_exit_code(tmp_path):
    """‏``_validate_ref_with_git`` הוא המקום היחיד שבו ההבחנה נוצרת — נבדק כאן ישירות.

    ‏``--verify --quiet`` יוצא ב-1 כשהשם אינו נפתר (``die_no_single_rev`` ב-
    ``builtin/rev-parse.c``), וכל תקלה אחרת יוצאת ב-128 דרך ``die()`` (git v2.43.0).
    תיקיית מראה שנמחקה מגיעה לכאן רק במרוץ — הכלים בודקים שהיא קיימת לפני — ולכן
    היא נבדקת ישירות, לצד תיקייה שאינה ריפו.
    """
    work = _repo(tmp_path, "r", "main", {"a.md": "x\n"})
    (tmp_path / "mirrors").mkdir()
    _clone_mirror(tmp_path, work, "r")
    (tmp_path / "mirrors" / "plain.git").mkdir()
    svc = GitMirrorService(base_path=str(tmp_path / "mirrors"))

    assert svc._validate_ref_with_git("r", "refs/heads/main") == {
        "valid": True, "resolved_sha": _git("rev-parse", "main", cwd=work)}
    assert svc._validate_ref_with_git("r", "bad:ref")["error"] == "invalid_ref"
    assert svc._validate_ref_with_git("r", "refs/heads/nope")["error"] == "ref_not_mirrored"
    assert svc._validate_ref_with_git("r", "deadbeefdeadbeef")["error"] == "ref_not_mirrored"
    assert svc._validate_ref_with_git("plain", "refs/heads/main")["error"] == "git_error"
    assert svc._validate_ref_with_git("deleted", "refs/heads/main")["error"] == "git_error"


# ===========================================================================
# 3. search_repo ופריטי הבאץ' — רק כשהענף הראשי עצמו חסר
# ===========================================================================


@requires_git
async def test_search_and_a_batch_item_name_a_default_branch_the_mirror_lacks(tmp_path, monkeypatch):
    world = _world(tmp_path, monkeypatch)

    searched = await _call(world.mcp, "codekeeper_search_repo", {"repo": _TRUNK, "query": "# r"})
    _assert_not_in_mirror(searched, repo=_TRUNK, ref="refs/heads/main")

    batch = await _call(world.mcp, read_batch.TOOL_NAME,
                        {"items": [{"kind": "file", "repo": _TRUNK, "path": "README.md"}]})
    (item,) = batch["items"]
    _assert_not_in_mirror(item["result"], repo=_TRUNK, ref="refs/heads/main", path="README.md")


@requires_git
async def test_search_on_a_repo_without_a_mirror_says_so(tmp_path, monkeypatch):
    """עד כאן ``mirror_not_found`` של המנוע הגיע לקורא כ-``search_failed``."""
    world = _world(tmp_path, monkeypatch)
    answer = await _call(world.mcp, "codekeeper_search_repo", {"repo": "ghost", "query": "# r"})
    assert answer == {"ok": False, "error": "repo_not_mirrored"}


# ===========================================================================
# 4. הבקשה לא מושכת את הענף — נמדד בספירת קריאות git, ובמצב המראה
# ===========================================================================


def _subcommand(argv: list[str]) -> str:
    """תת-הפקודה של ``git [-C <path>] [-c <k=v>] <sub> ...``."""
    rest = list(argv[1:])
    while rest and rest[0] in ("-C", "-c"):
        rest = rest[2:]
    return rest[0] if rest else ""


@requires_git
async def test_asking_for_a_ref_the_mirror_lacks_never_fetches(tmp_path, monkeypatch):
    """אחרת כל קורא יכול להפעיל משיכות מ-GitHub. אילו ענפים נכנסים זו מדיניות ה-autosync.

    כל תהליך git שהשירות מריץ נספר (``subprocess.run`` ו-``subprocess.Popen``, שני
    הערוצים שלו), ואף אחד אינו מחוץ לקבוצת הפקודות שרק קוראות. ובנוסף למה שהורץ —
    המצב: הרפים במראה זהים לפני ואחרי, ו-``late`` עדיין לא שם. ה-``origin`` כאן הוא
    ריפו מקומי שבו ``late`` קיים, ולכן משיכה הייתה מצליחה ומשנה את שניהם.
    """
    world = _world(tmp_path, monkeypatch)
    mirror_dir = world.mirrors / f"{_MD}.git"
    refs_before = _git("for-each-ref", "--format=%(objectname) %(refname)", cwd=mirror_dir)

    commands: list[list[str]] = []
    real_run, real_popen = subprocess.run, subprocess.Popen

    def counting_run(args, *a, **k):
        commands.append([str(x) for x in args])
        return real_run(args, *a, **k)

    class CountingPopen(real_popen):  # type: ignore[misc, valid-type]
        def __init__(self, args, *a, **k):
            commands.append([str(x) for x in args])
            super().__init__(args, *a, **k)

    monkeypatch.setattr(git_mirror_service.subprocess, "run", counting_run)
    monkeypatch.setattr(git_mirror_service.subprocess, "Popen", CountingPopen)

    answers = [
        await _call(world.mcp, tool, arguments)
        for tool, arguments in (
            ("codekeeper_get_repo_file", {"repo": _MD, "path": "LATE.md", "ref": "late"}),
            ("codekeeper_list_repo_tree", {"repo": _MD, "ref": "late"}),
            ("codekeeper_docs_get_section", {"repo": _MD, "path": "LATE", "ref": "late"}),
            ("codekeeper_search_repo", {"repo": _TRUNK, "query": "# r"}),
        )
    ]
    monkeypatch.undo()

    # קודם מה שהורץ ומה שהשתנה, ורק אחר כך התשובות: משיכה שהייתה מביאה את
    # ``late`` הייתה גם משנה את התשובות, ואז הטסט היה נופל עליהן בלי לומר למה.
    git_commands = [c for c in commands if c and Path(c[0]).name == "git"]
    assert git_commands, "הספירה לא ראתה אף תהליך git — הטסט לא היה מסוגל להיכשל"
    assert {_subcommand(c) for c in git_commands} <= _READ_ONLY_GIT, git_commands
    assert _git("for-each-ref", "--format=%(objectname) %(refname)", cwd=mirror_dir) == refs_before
    assert world.mirror.resolve_commit(_MD, "late") == {"ok": False, "error": "ref_not_mirrored"}
    assert [answer.get("error") for answer in answers] == ["ref_not_mirrored"] * 4


# ===========================================================================
# 5. sync_in_progress גובר
# ===========================================================================

_SYNC_CASES = [
    ("codekeeper_get_repo_file", {"repo": _MD, "path": "CRITICAL-PATTERNS.md", "ref": "late"}),
    ("codekeeper_list_repo_tree", {"repo": _MD, "ref": "late"}),
    ("codekeeper_docs_get_section", {"repo": _MD, "path": "CRITICAL-PATTERNS", "ref": "late"}),
    ("codekeeper_search_repo", {"repo": _TRUNK, "query": "# r"}),
]


@requires_git
@pytest.mark.parametrize("tool, arguments", _SYNC_CASES, ids=[c[0] for c in _SYNC_CASES])
async def test_a_running_sync_wins_over_ref_not_mirrored(tmp_path, monkeypatch, tool, arguments):
    """רענון שרץ עכשיו יכול להביא את הענף — "נסה שוב" נכון יותר מ"לא במראה"."""
    world = _world(tmp_path, monkeypatch)
    world.sync_jobs.docs.append({"repo_name": arguments["repo"], "status": "running"})
    answer = await _call(world.mcp, tool, arguments)
    assert answer["error"] == "sync_in_progress" and answer["retry_after"] > 0


@requires_git
async def test_the_local_autosync_also_wins(tmp_path, monkeypatch):
    from mcp_server import repo_autosync

    world = _world(tmp_path, monkeypatch)
    monkeypatch.setattr(repo_autosync, "is_refreshing", lambda name: name == _MD)
    answer = await _call(world.mcp, "codekeeper_get_repo_file",
                         {"repo": _MD, "path": "CRITICAL-PATTERNS.md", "ref": "late"})
    assert answer["error"] == "sync_in_progress"


# ===========================================================================
# 6. ההפניה מ-outline ל-docs_get_section — נגזרת מהמדיניות, ורצה כמו שהיא
# ===========================================================================


@requires_git
@pytest.mark.parametrize("ref", [None, "feature"], ids=["default-branch", "feature"])
async def test_the_redirect_runs_as_given_and_carries_the_ref(tmp_path, monkeypatch, ref):
    world = _world(tmp_path, monkeypatch)
    path = "NEW-ONLY-ON-FEATURE.md" if ref else "CRITICAL-PATTERNS.md"
    asked = {"repo": _MD, "path": path, "outline": True, **({"ref": ref} if ref else {})}

    answer = await _call(world.mcp, "codekeeper_get_repo_file", asked)

    # ``no_outline`` נשאר ``status``, והתשובה נשארת ``ok: true`` — ההפניה היא שדה נוסף.
    assert answer["ok"] is True and answer["status"] == "no_outline"
    assert answer["reason"] == "unsupported_language"
    assert answer["read_with"] == "codekeeper_docs_get_section"
    assert answer["read_with_arguments"] == {"repo": _MD, "path": path, **({"ref": ref} if ref else {})}

    followed = await _call(world.mcp, answer["read_with"], answer["read_with_arguments"])
    assert followed["ok"] is True and followed["mode"] == "toc"
    assert followed["resolved_commit"] == (world.feature_sha if ref else world.main_sha)
    if ref:
        # בלי ה-``ref`` ההפניה הייתה קוראת את ``main``, שאין בו את הקובץ.
        without_ref = {k: v for k, v in answer["read_with_arguments"].items() if k != "ref"}
        assert (await _call(world.mcp, answer["read_with"], without_ref))["error"] == "not_found"


@requires_git
@pytest.mark.parametrize("repo, path, ref", [
    (_RST, "docs/notes.md", None),  # CodeBot מגיש רק docs/*.rst
    (_MD, "hooks/primer.sh", None),  # השער היה משלים ל-...sh.md — קובץ אחר
    # ריפו מחוץ ל-MCP_DOCS_REPO. ‏``trunk`` במפורש, כי הענף הראשי שלו חסר במראה.
    (_TRUNK, "README.md", "trunk"),
], ids=["codebot-md", "unknown-suffix", "repo-not-allowed"])
async def test_no_redirect_where_the_docs_tool_would_not_serve_that_file(tmp_path, monkeypatch, repo, path, ref):
    world = _world(tmp_path, monkeypatch)
    answer = await _call(world.mcp, "codekeeper_get_repo_file",
                         {"repo": repo, "path": path, "outline": True, **({"ref": ref} if ref else {})})
    assert answer["ok"] is True and answer["status"] == "no_outline"
    assert "read_with" not in answer and "read_with_arguments" not in answer


@requires_git
async def test_a_redirect_appears_exactly_where_the_docs_tool_serves_the_same_file(tmp_path, monkeypatch):
    """הכיוון ההפוך: לכל קובץ בלי מפה, יש הפניה **אם ורק אם** כלי הסעיפים מגיש אותו.

    האורקל הוא הצרכן ולא השער: ``docs_get_section`` על אותו נתיב, ו-``ok`` על
    **אותו** ``path``. גזירה של הציפייה מ-``section_read_arguments`` עצמה הייתה
    טאוטולוגיה — היא הייתה עוברת גם כשהשער שגוי.
    """
    world = _world(tmp_path, monkeypatch)
    checked = 0
    for repo in (_MD, _RST):
        listing = _git("ls-tree", "-r", "--name-only", "HEAD", cwd=world.mirrors / f"{repo}.git")
        for path in listing.splitlines():
            answer = await _call(world.mcp, "codekeeper_get_repo_file",
                                 {"repo": repo, "path": path, "outline": True})
            if answer.get("reason") != "unsupported_language":
                continue
            checked += 1
            served = await _call(world.mcp, "codekeeper_docs_get_section", {"repo": repo, "path": path})
            serves_this_file = served.get("ok") is True and served.get("path") == path
            assert ("read_with" in answer) is serves_this_file, (repo, path, answer, served)
    assert checked >= 3, "אין מספיק קבצים בלי מפה — הטסט לא בדק כלום"


# ===========================================================================
# 7. משפט הרענון: מקור אחד, בכל פרמטר ref — והמדיניות שהוא מתאר
# ===========================================================================


def test_every_ref_parameter_carries_the_refresh_note():
    """שלושת הכלים שמקבלים ``ref``, ורק הם — וכולם מאותו מקור."""
    mcp = srv.build_mcp(object(), repo_backend=RepoBackend(db=None))
    with_ref = {
        tool.name: tool.parameters["properties"]["ref"].get("description")
        for tool in mcp._tool_manager.list_tools()
        if "ref" in tool.parameters.get("properties", {})
    }
    assert with_ref == dict.fromkeys(
        ("codekeeper_get_repo_file", "codekeeper_list_repo_tree", "codekeeper_docs_get_section"),
        MIRROR_REFRESH_NOTE,
    )
    assert MIRROR_REFRESH_NOTE.startswith("The mirror is refreshed only when the repo's default branch changes.")


def test_the_refresh_note_matches_the_webhook_policy(monkeypatch):
    """‏``MIRROR_REFRESH_NOTE`` אומר שהמראה מתרעננת רק כשהענף הראשי משתנה. זה החצי של הוובאפ.

    push לענף אחר אינו מפעיל סנכרון, ולכן גם לא כותב SHA חדש למונגו — וה-autosync
    של ה-MCP מושך רק כשה-SHA הזה משתנה (``test_equal_shas_skip_fetch`` /
    ``test_sha_drift_triggers_fetch`` ב-``tests/test_mcp_repo_autosync.py``). מי
    שמשנה את המדיניות ורואה את הטסט הזה נופל — מעדכן גם את המשפט.
    """
    import importlib

    from flask import Flask

    from services import repo_sync_service
    from webapp.routes.webhooks import webhooks_bp

    # המודול ולא ``from database import db_manager``: לחבילה יש שם תכונה בשם
    # הזה (מופע של ``DatabaseManager``), והמטפל מייבא את ``get_db`` מהמודול.
    db_manager = importlib.import_module("database.db_manager")

    secret = "test-secret"
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", secret)

    class _Meta:
        def find_one(self, query: dict[str, Any]) -> dict[str, Any]:
            return {"repo_name": query.get("repo_name"), "default_branch": "main"}

    class _Db:
        repo_metadata = _Meta()

    monkeypatch.setattr(db_manager, "get_db", lambda: _Db())
    queued: list[dict[str, Any]] = []
    monkeypatch.setattr(repo_sync_service, "trigger_sync", lambda **k: queued.append(k) or "job-1")

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(webhooks_bp)
    client = app.test_client()

    def push(ref: str):
        body = json.dumps({"ref": ref, "after": "a" * 40, "before": "b" * 40,
                           "repository": {"name": _MD, "default_branch": "main"}}).encode()
        signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return client.post("/api/webhooks/github", data=body, content_type="application/json",
                           headers={"X-Hub-Signature-256": signature, "X-GitHub-Event": "push"})

    other = push("refs/heads/feature")
    assert other.status_code == 200 and queued == []

    default = push("refs/heads/main")
    assert default.status_code == 202 and [q["repo_name"] for q in queued] == [_MD]
