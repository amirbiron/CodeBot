"""``codekeeper_read_batch`` — דרך ממשק ה-MCP, מעל ``RepoBackend`` ומראת git אמיתיים.

**למה דרך ``mcp.call_tool`` ולא דרך ``read_batch.read_batch``.** החוזה של הכלי
חי בין שכבות: השקילה והתקרה ב-``AdminAwareFastMCP.call_tool``, הזהות בטוקן,
הניתוב למאגר הקריאות ב-``add_tool``, הקיבוע ל-commit ב-``RepoBackend``, והתשובה
בצורה שה-SDK שולח. קריאה ישירה לפונקציה הייתה עוקפת את רובן (T1).

**והזהות היא זו של הייצור.** טוקן OAuth אמיתי ב-``auth_context_var`` של ה-SDK
(מה ש-``AuthContextMiddleware`` קובע בכל בקשה), ו-``config.ADMIN_USER_IDS``
כמקור האדמיניות — שני השערים, ``_caller_identity`` ו-``require_admin``, נבדקים
כמו שהם, בלי ``monkeypatch`` על אף אחד מהם.

**"זהה בית-בית"** נבדק כך: ה-``result`` של כל פריט מסודר מחדש בדיוק כמו שה-SDK
מסדר תשובת ``dict`` (``pydantic_core.to_json(..., indent=2)``), ומושווה לטקסט
שהכלי הבודד מחזיר על אותם ארגומנטים — כולל תשובות הסירוב.

הריפואים, המראות וכל קלט/פלט יושבים תחת ``tmp_path``. בלי ``sleep``: הדדליין
נבדק בשעון מוזרק, וה-ref שזז — ב-``git fetch`` שרץ בין שתי קריאות.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
import random
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp")

import pydantic_core  # noqa: E402
from mcp import types as mcp_types  # noqa: E402
from mcp.server.auth.middleware.auth_context import auth_context_var  # noqa: E402
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser  # noqa: E402
from mcp.server.auth.provider import AccessToken  # noqa: E402
from mcp.server.fastmcp.exceptions import ToolError  # noqa: E402
from mcp.server.lowlevel.server import request_ctx  # noqa: E402
from mcp.shared.context import RequestContext  # noqa: E402

import mcp_server.server as srv  # noqa: E402
from mcp_server import analytics, docs_handlers, read_batch, repo_handlers  # noqa: E402
from mcp_server.repo_backend import RepoBackend  # noqa: E402
from rate_limiter import RateLimiter  # noqa: E402
from services import md_parser  # noqa: E402
from services.git_mirror_service import GitMirrorService  # noqa: E402

_GIT = shutil.which("git")
requires_git = pytest.mark.skipif(_GIT is None, reason="git is not installed")

_ADMIN = 4242
_OTHER = 7
_MD = "amir-bug-patterns"  # מדיניות: שורש הריפו, .md
_RST = "CodeBot"  # מדיניות: docs/, .rst
_GHOST = "ghost-repo"  # ריפו בלי מראה

_MD_FILES = {
    "CRITICAL-PATTERNS.md": (
        "# דפוסים קריטיים\n\n## K11. כשל שנבלע\n\nגוף K11 — ערך החזרה שלא נבדק.\n\n"
        "## K13. סוד רוכב\n\nגוף K13 — סוד בתוך הודעת חריגה.\n"
    ),
    "TESTING-PATTERNS.md": (
        "# דפוסי בדיקות\n\n## T1. המפרט אינו הצרכן\n\nגוף T1.\n\n## T3. תשתית הבדיקות\n\nגוף T3.\n"
    ),
    "DUP.md": "# ראשי\n\n## כפול\n\nא\n\n## כפול\n\nב\n",
    "bugbot-rules/one.md": "# אחד\n\nשורה ראשונה\nשורה שנייה\nשורה שלישית\n",
    "bugbot-rules/two.md": "# שניים\n\nתוכן שני, גרסה ראשונה.\n",
    "secrets.md": "# לא לקרוא\n",
    # ``\r`` בודד — הצורה היחידה שמפילה את ספירת השורות (``InconsistentLineEndings``).
    "CR.md": "# כותרת\rעם CR בודד\n",
    # front matter: הפרסור רץ על טקסט שבו שורות הבלוק ריקות, ו-``section_text``
    # חותך מהטקסט המקורי — מספרי השורות זהים בשניהם.
    "FM.md": "---\ntitle: עם front matter\ntags: [a, b]\n---\n\n# ראשי\n\n## סעיף\n\nגוף הסעיף.\n",
    # כותרות בתוך ציטוט ובתוך רשימה אינן סעיפים (``token.level != 0``).
    "NESTED.md": "# ראשי\n\n> # בתוך ציטוט\n\n- # בתוך רשימה\n\n## אמיתי\n\nגוף.\n",
}
_RST_FILES = {"docs/guide.rst": "Guide\n=====\n\nIntro.\n\nFirst\n-----\n\nBody.\n"}


def _git(*args: str, cwd: Path) -> str:
    done = subprocess.run((_GIT, *args), cwd=str(cwd), check=True, capture_output=True, text=True)
    return done.stdout.strip()


def _commit(work: Path, files: dict[str, str], message: str) -> None:
    for name, body in files.items():
        target = work / name
        target.parent.mkdir(parents=True, exist_ok=True)
        # בתים ולא טקסט: ``write_text`` היה מתרגם סיומות שורה בפלטפורמות אחרות,
        # ו-``CR.md`` קיים בדיוק בשביל ה-``\r`` שלו.
        target.write_bytes(body.encode("utf-8"))
    _git("add", "-A", cwd=work)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", message, cwd=work)


def _mirror(tmp_path: Path, name: str, files: dict[str, str]) -> Path:
    """ריפו עובד תחת ``tmp_path``, ומשם ``clone --mirror`` — המבנה שהשירות מצפה לו."""
    work = tmp_path / "work" / name
    work.mkdir(parents=True)
    _git("init", "-q", "-b", "main", ".", cwd=work)
    _commit(work, files, "init")
    mirrors = tmp_path / "mirrors"
    mirrors.mkdir(exist_ok=True)
    _git("clone", "-q", "--mirror", str(work), str(mirrors / f"{name}.git"), cwd=tmp_path)
    return work


class _Collection:
    """``find_one`` על רשימת מסמכים — שתי השאילתות ש-``RepoBackend`` שולח לכאן."""

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
    backend: RepoBackend
    mirror: GitMirrorService
    mirrors: Path
    md_work: Path
    sync_jobs: _Collection


def _world(tmp_path: Path, monkeypatch: Any, *, extra: dict[str, str] | None = None,
           rate: int = 0) -> _World:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("MCP_DOCS_REPO", f"{_MD},{_RST}")
    monkeypatch.setenv("REPO_MIRROR_PATH", str(tmp_path / "unused-default"))
    from config import config as _cfg

    monkeypatch.setattr(_cfg, "ADMIN_USER_IDS", [_ADMIN], raising=False)

    md_work = _mirror(tmp_path, _MD, {**_MD_FILES, **(extra or {})})
    _mirror(tmp_path, _RST, _RST_FILES)
    sync_jobs = _Collection([])
    db = {
        "repo_metadata": _Collection([
            {"repo_name": _MD, "default_branch": "main"},
            {"repo_name": _RST, "default_branch": "main"},
        ]),
        "sync_jobs": sync_jobs,
    }
    mirror = GitMirrorService(base_path=str(tmp_path / "mirrors"))
    backend = RepoBackend(db=db, mirror=mirror)
    mcp = srv.build_mcp(object(), repo_backend=backend, rate_limit_per_minute=rate)
    return _World(mcp, backend, mirror, tmp_path / "mirrors", md_work, sync_jobs)


@contextlib.contextmanager
def _as(user: int):
    """מה שה-SDK קובע לכל ``tools/call``: הקשר בקשה, ומשתמש מאומת מהטוקן."""
    request_token = request_ctx.set(RequestContext(request_id=1, meta=None, session=None, lifespan_context=None))
    access = AccessToken(token="t", client_id="c", scopes=["read"], subject=str(user))
    auth_token = auth_context_var.set(AuthenticatedUser(access))
    try:
        yield
    finally:
        auth_context_var.reset(auth_token)
        request_ctx.reset(request_token)


async def _text(mcp: Any, name: str, arguments: dict[str, Any], *, user: int = _ADMIN) -> str:
    with _as(user):
        result = await mcp.call_tool(name, arguments)
    content = result.content if isinstance(result, mcp_types.CallToolResult) else result
    (block,) = content
    return block.text


async def _batch(mcp: Any, items: list[Any], *, user: int = _ADMIN) -> tuple[str, dict[str, Any]]:
    text = await _text(mcp, read_batch.TOOL_NAME, {"items": items}, user=user)
    return text, json.loads(text)


def _as_sent(value: Any) -> str:
    """איך ה-SDK מסדר תשובת ``dict`` — ``_convert_to_content`` (mcp 1.28.1)."""
    return pydantic_core.to_json(value, fallback=str, indent=2).decode()


class _Spy:
    """עוטף מתודה ומונה קריאות, בלי לשנות את מה שהיא מחזירה."""

    def __init__(self, fn: Any, after: Any = None) -> None:
        self.fn = fn
        self.calls: list[tuple[tuple, dict]] = []
        self.after = after

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((args, kwargs))
        result = self.fn(*args, **kwargs)
        if self.after is not None:
            self.after(len(self.calls))
        return result


@contextlib.contextmanager
def _records(name: str):
    """רשומות הלוג של ``name`` — בלי ``caplog``: handler ישירות על הלוגר, ומוסר ביציאה."""
    records: list[logging.LogRecord] = []

    class _Keep(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    target = logging.getLogger(name)
    assert not target.disabled, f"הלוגר {name} מושבת, ולכן טסט הלוג לא היה רואה דבר"
    handler = _Keep(logging.DEBUG)
    target.addHandler(handler)
    try:
        yield records
    finally:
        target.removeHandler(handler)


# ===========================================================================
# 1. כל פריט זהה בית-בית לכלי הבודד — בהצלחה ובכל סירוב
# ===========================================================================

#: פריט בבאץ' ← הכלי הבודד והארגומנטים שלו. כל מסלול תשובה של שני הכלים
#: שהפריט יכול להגיע אליו, כולל כל תשובות הסירוב שהבריף מונה.
_IDENTITY_CASES = [
    ({"kind": "section", "repo": _MD, "path": "CRITICAL-PATTERNS", "section": "K11"},
     ("codekeeper_docs_get_section", {"repo": _MD, "path": "CRITICAL-PATTERNS", "section": "K11"})),
    ({"kind": "section", "repo": _MD, "path": "TESTING-PATTERNS"},
     ("codekeeper_docs_get_section", {"repo": _MD, "path": "TESTING-PATTERNS"})),
    ({"kind": "section", "repo": _MD, "path": "CRITICAL-PATTERNS", "section": "K99"},
     ("codekeeper_docs_get_section", {"repo": _MD, "path": "CRITICAL-PATTERNS", "section": "K99"})),
    ({"kind": "section", "repo": _MD, "path": "DUP", "section": "כפול"},
     ("codekeeper_docs_get_section", {"repo": _MD, "path": "DUP", "section": "כפול"})),
    ({"kind": "section", "repo": _MD, "path": "NOPE"},
     ("codekeeper_docs_get_section", {"repo": _MD, "path": "NOPE"})),
    ({"kind": "section", "repo": _MD, "path": "secrets"},
     ("codekeeper_docs_get_section", {"repo": _MD, "path": "secrets"})),
    ({"kind": "section", "repo": _MD, "path": "guide.rst"},
     ("codekeeper_docs_get_section", {"repo": _MD, "path": "guide.rst"})),
    ({"kind": "section", "repo": _MD, "path": "../etc/passwd"},
     ("codekeeper_docs_get_section", {"repo": _MD, "path": "../etc/passwd"})),
    ({"kind": "section", "repo": _MD, "path": "a" * 5000},
     ("codekeeper_docs_get_section", {"repo": _MD, "path": "a" * 5000})),
    ({"kind": "section", "repo": "not-allowed", "path": "x"},
     ("codekeeper_docs_get_section", {"repo": "not-allowed", "path": "x"})),
    ({"kind": "section", "repo": _MD, "path": ""},
     ("codekeeper_docs_get_section", {"repo": _MD, "path": ""})),
    ({"kind": "section", "repo": _MD, "path": "CR"},
     ("codekeeper_docs_get_section", {"repo": _MD, "path": "CR"})),
    ({"kind": "section", "path": "CRITICAL-PATTERNS", "section": "K13"},
     ("codekeeper_docs_get_section", {"path": "CRITICAL-PATTERNS", "section": "K13"})),
    ({"kind": "section", "repo": _RST, "path": "guide", "section": "First"},
     ("codekeeper_docs_get_section", {"repo": _RST, "path": "guide", "section": "First"})),
    ({"kind": "section", "repo": _RST, "path": "docs/guide.md"},
     ("codekeeper_docs_get_section", {"repo": _RST, "path": "docs/guide.md"})),
    ({"kind": "section", "repo": _MD, "path": "FM", "section": "סעיף"},
     ("codekeeper_docs_get_section", {"repo": _MD, "path": "FM", "section": "סעיף"})),
    ({"kind": "section", "repo": _MD, "path": "NESTED"},
     ("codekeeper_docs_get_section", {"repo": _MD, "path": "NESTED"})),
    ({"kind": "section", "repo": _MD, "path": "NESTED", "section": "בתוך ציטוט"},
     ("codekeeper_docs_get_section", {"repo": _MD, "path": "NESTED", "section": "בתוך ציטוט"})),
]

_FILE_IDENTITY_CASES = [
    ({"kind": "file", "repo": _MD, "path": "bugbot-rules/one.md"},
     ("codekeeper_get_repo_file", {"repo": _MD, "path": "bugbot-rules/one.md"})),
    ({"kind": "file", "repo": _MD, "path": "bugbot-rules/one.md", "lines": [2, 3]},
     ("codekeeper_get_repo_file", {"repo": _MD, "path": "bugbot-rules/one.md", "lines": [2, 3]})),
    ({"kind": "file", "repo": _MD, "path": "bugbot-rules/one.md", "lines": [5, 1]},
     ("codekeeper_get_repo_file", {"repo": _MD, "path": "bugbot-rules/one.md", "lines": [5, 1]})),
    ({"kind": "file", "repo": _MD, "path": "bugbot-rules/nope.md"},
     ("codekeeper_get_repo_file", {"repo": _MD, "path": "bugbot-rules/nope.md"})),
    ({"kind": "file", "repo": _MD, "path": "secrets.md"},
     ("codekeeper_get_repo_file", {"repo": _MD, "path": "secrets.md"})),
    ({"kind": "file", "repo": "   ", "path": "x.md"},
     ("codekeeper_get_repo_file", {"repo": "   ", "path": "x.md"})),
    ({"kind": "file", "repo": _MD, "path": ""},
     ("codekeeper_get_repo_file", {"repo": _MD, "path": ""})),
    ({"kind": "file", "repo": _GHOST, "path": "x.md"},
     ("codekeeper_get_repo_file", {"repo": _GHOST, "path": "x.md"})),
    ({"kind": "file", "repo": _MD, "path": "CRITICAL-PATTERNS.md"},
     ("codekeeper_get_repo_file", {"repo": _MD, "path": "CRITICAL-PATTERNS.md"})),
]


async def _assert_identical(world: _World, cases: list) -> None:
    _, answer = await _batch(world.mcp, [item for item, _ in cases])
    assert answer["ok"] is True and "unread" not in answer
    assert [entry["index"] for entry in answer["items"]] == list(range(len(cases)))
    for entry, (item, (tool, arguments)) in zip(answer["items"], cases):
        single = await _text(world.mcp, tool, arguments)
        assert entry["request"] == item
        assert _as_sent(entry["result"]) == single, f"פריט {entry['index']} ({item}) אינו זהה לכלי הבודד"


@requires_git
async def test_every_section_item_is_byte_identical_to_the_single_tool(tmp_path, monkeypatch):
    """הצלחה, TOC, ``section_not_found``, ``ambiguous_section``, ``not_found``,
    ``path_denied``, ``suffix_not_allowed``, ``path_outside_root``, ``path_too_long``,
    ``repo_not_allowed``, ``missing_path``, ``inconsistent_line_endings``, ריפו ברירת
    המחדל, ו-RST — כולם באותו באץ', וכולם זהים לכלי הבודד.

    **מוטציה שמפילה:** להפוך שגיאת פריט לשגיאה של הקריאה כולה — הבאץ' כולו היה
    חוזר ``ok: false`` בלי ``items``.
    """
    world = _world(tmp_path, monkeypatch)
    await _assert_identical(world, _IDENTITY_CASES)


@requires_git
async def test_every_file_item_is_byte_identical_to_the_single_tool(tmp_path, monkeypatch):
    """קריאה מלאה, טווח, טווח פגום, ``not_found``, ``path_denied``, ``missing_repo``,
    ``missing_path``, ``repo_not_mirrored`` — כמו שהכלי הבודד מחזיר אותם."""
    world = _world(tmp_path, monkeypatch)
    await _assert_identical(world, _FILE_IDENTITY_CASES)


@requires_git
async def test_a_sync_in_progress_answers_the_same_in_both_kinds(tmp_path, monkeypatch):
    """ריפו בלי מראה שסנכרון רץ עליו: ``sync_in_progress`` עם ``retry_after``, כמו בכלי הבודד."""
    world = _world(tmp_path, monkeypatch)
    world.sync_jobs.docs.append({"repo_name": _GHOST, "status": "running"})
    monkeypatch.setenv("MCP_DOCS_REPO", f"{_MD},{_RST},{_GHOST}")
    monkeypatch.setitem(docs_handlers._DOCS_PATH_POLICY_TABLE, _GHOST, docs_handlers._DocsPathPolicy(root="", suffix=".md"))
    cases = [
        ({"kind": "file", "repo": _GHOST, "path": "a.md"},
         ("codekeeper_get_repo_file", {"repo": _GHOST, "path": "a.md"})),
        ({"kind": "section", "repo": _GHOST, "path": "a"},
         ("codekeeper_docs_get_section", {"repo": _GHOST, "path": "a"})),
    ]
    await _assert_identical(world, cases)
    _, answer = await _batch(world.mcp, [item for item, _ in cases])
    assert {e["result"]["error"] for e in answer["items"]} == {"sync_in_progress"}


@requires_git
async def test_a_too_many_sections_refusal_is_the_same_in_the_batch(tmp_path, monkeypatch):
    """``too_many_sections`` עם ``max`` וההקשר — הפארסר מוקטן, כמו בטסטים של הכלי הבודד."""
    world = _world(tmp_path, monkeypatch)
    real = md_parser.parse_document

    def _tiny(text, **kwargs):
        return real(text, max_sections=1)

    monkeypatch.setattr(md_parser, "parse_document", _tiny)
    cases = [
        ({"kind": "section", "repo": _MD, "path": "CRITICAL-PATTERNS", "section": "K11"},
         ("codekeeper_docs_get_section", {"repo": _MD, "path": "CRITICAL-PATTERNS", "section": "K11"})),
    ]
    await _assert_identical(world, cases)
    _, answer = await _batch(world.mcp, [cases[0][0]])
    assert answer["items"][0]["result"]["error"] == "too_many_sections"


@requires_git
async def test_a_missing_file_and_a_missing_section_fail_only_themselves(tmp_path, monkeypatch):
    world = _world(tmp_path, monkeypatch)
    _, answer = await _batch(world.mcp, [
        {"kind": "section", "repo": _MD, "path": "CRITICAL-PATTERNS", "section": "K11"},
        {"kind": "file", "repo": _MD, "path": "bugbot-rules/nope.md"},
        {"kind": "section", "repo": _MD, "path": "CRITICAL-PATTERNS", "section": "לא קיים"},
        {"kind": "file", "repo": _MD, "path": "bugbot-rules/two.md"},
    ])
    results = [entry["result"] for entry in answer["items"]]
    assert answer["ok"] is True and answer["count"] == 4
    assert results[0]["mode"] == "section" and "גוף K11" in results[0]["content"]
    assert results[1] == {"ok": False, "error": "not_found"}
    assert results[2]["error"] == "section_not_found"
    assert results[3]["status"] == "ok" and "גרסה ראשונה" in results[3]["content"]


@requires_git
async def test_an_item_that_does_not_match_the_schema_fails_alone(tmp_path, monkeypatch):
    """מפתח זר, טיפוס שגוי, ``kind`` לא מוכר, ופריט שאינו אובייקט — ``invalid_item`` לכל אחד.

    ``ref`` הוא המקרה המעניין: הכלים הבודדים מקבלים אותו, והבאץ' לא — התעלמות
    שקטה ממנו הייתה קוראת מהענף הראשי כשביקשו ענף אחר.
    """
    world = _world(tmp_path, monkeypatch)
    _, answer = await _batch(world.mcp, [
        {"kind": "file", "repo": _MD, "path": "bugbot-rules/one.md", "ref": "other"},
        {"kind": "section", "path": 5},
        {"kind": "sections", "path": "x"},
        "U1",
        {"kind": "file", "repo": _MD, "path": "bugbot-rules/two.md"},
    ])
    results = [entry["result"] for entry in answer["items"]]
    for result in results[:4]:
        assert result["ok"] is False and result["error"] == "invalid_item"
        assert result["problems"] and all("loc" in p and "msg" in p for p in result["problems"])
    assert results[4]["status"] == "ok"
    assert answer["items"][3]["request"] == "U1"


@requires_git
async def test_a_comma_separated_string_is_not_a_list_of_items(tmp_path, monkeypatch):
    """הצורה שנפסלה בהחלטה הקודמת (``"U1,U3"``): כותרות יכולות להכיל פסיק, ולכן הקלט הוא רשימה בלבד."""
    world = _world(tmp_path, monkeypatch)
    with pytest.raises(ToolError):
        await _text(world.mcp, read_batch.TOOL_NAME, {"items": "U1,U3"})


# ===========================================================================
# 2. קריאה ופרסור אחד לכל קובץ, commit אחד לכל ריפו
# ===========================================================================


@requires_git
async def test_items_that_read_the_same_file_share_one_read_and_one_parse(tmp_path, monkeypatch):
    """שני סעיפים מאותו קובץ **שאינם צמודים**, כפילות, ופריט קובץ על אותו נתיב.

    שלושה קבצים שונים ← שלוש קריאות מהמראה; שני מסמכי Markdown עם סעיפים ← שני
    פרסורים. **מוטציה שמפילה:** לפרסר לכל פריט (``load_document`` בכל איטרציה).
    """
    world = _world(tmp_path, monkeypatch)
    reads = _Spy(world.mirror.get_file_at_commit)
    monkeypatch.setattr(world.mirror, "get_file_at_commit", reads)
    parses = _Spy(md_parser.parse_document)
    monkeypatch.setattr(md_parser, "parse_document", parses)

    items = [
        {"kind": "section", "repo": _MD, "path": "CRITICAL-PATTERNS", "section": "K11"},
        {"kind": "section", "repo": _MD, "path": "TESTING-PATTERNS", "section": "T1"},
        {"kind": "file", "repo": _MD, "path": "bugbot-rules/one.md"},
        {"kind": "section", "repo": _MD, "path": "CRITICAL-PATTERNS", "section": "K13"},
        {"kind": "section", "repo": _MD, "path": "TESTING-PATTERNS", "section": "T3"},
        {"kind": "section", "repo": _MD, "path": "CRITICAL-PATTERNS", "section": "K11"},
        {"kind": "file", "repo": _MD, "path": "CRITICAL-PATTERNS.md"},
    ]
    _, answer = await _batch(world.mcp, items)

    assert len(reads.calls) == 3, [c[0][1] for c in reads.calls]
    assert len(parses.calls) == 2
    assert answer["items"][0]["result"] == answer["items"][5]["result"], "כפילות חוזרת במקומה, זהה"
    assert [e["index"] for e in answer["items"]] == list(range(len(items)))


@requires_git
async def test_a_section_item_never_parses_text_read_under_the_range_ceiling(tmp_path, monkeypatch):
    """קובץ מעל 500KB: פריט טווח קורא אותו (תקרת 10MB), ופריט סעיף על אותו קובץ — ``unreadable_too_large``.

    תקרת 500KB היא ההגנה היחידה על הפרסור. פריט הסעיף מקבל בדיוק את מה שהכלי
    הבודד מחזיר, כי הוא אינו חולק קריאה עם פריט הטווח: ``lines`` הוא חלק
    ממפתח הקבוצה, והוא מה שמכריע את התקרה. ופריט קובץ **בלי** ``lines`` על אותו
    קובץ — קריאה מלאה, ולכן כן חולק עם הסעיף — מחזיר ``too_large``, שוב כמו הכלי.

    **מוטציה שמפילה:** להוריד את ``lines`` ממפתח הקבוצה — אז הסעיף היה מפרסר
    את הטווח שנקרא תחת 10MB, ועונה מתוכו.
    """
    huge = {"huge.md": "# ענק\n\n## בפנים\n\n" + "שורה בעברית מעל התקרה.\n" * 13_000}
    assert len(huge["huge.md"].encode("utf-8")) > 500 * 1024
    world = _world(tmp_path, monkeypatch, extra=huge)
    await _assert_identical(world, [
        ({"kind": "file", "repo": _MD, "path": "huge.md", "lines": [1, 3]},
         ("codekeeper_get_repo_file", {"repo": _MD, "path": "huge.md", "lines": [1, 3]})),
        ({"kind": "section", "repo": _MD, "path": "huge", "section": "בפנים"},
         ("codekeeper_docs_get_section", {"repo": _MD, "path": "huge", "section": "בפנים"})),
        ({"kind": "file", "repo": _MD, "path": "huge.md"},
         ("codekeeper_get_repo_file", {"repo": _MD, "path": "huge.md"})),
    ])
    _, answer = await _batch(world.mcp, [
        {"kind": "file", "repo": _MD, "path": "huge.md", "lines": [1, 3]},
        {"kind": "section", "repo": _MD, "path": "huge", "section": "בפנים"},
    ])
    assert answer["items"][0]["result"]["status"] == "ok"
    assert answer["items"][1]["result"]["error"] == "unreadable_too_large"


@requires_git
async def test_a_batch_builds_no_markdown_parser_of_its_own(tmp_path, monkeypatch):
    """הבאץ' מפרסר דרך המופע היחיד של ``md_parser`` — זה שעבר חימום בזמן הבנייה.

    ``markdown-it`` בונה את הכללים שלו בשימוש הראשון, ומופע חדש שרץ בכמה חוטים
    במקביל נתן מפות שגויות (PR #3418). הפיצול של ``docs_get_section`` אינו
    יוצר מופע — לא לכל קריאה ולא לכל תמונת מצב — וזה נספר, לא מונח.
    """
    import markdown_it

    world = _world(tmp_path, monkeypatch)
    built = []
    real_init = markdown_it.MarkdownIt.__init__

    def _count(self, *args, **kwargs):
        built.append(1)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(markdown_it.MarkdownIt, "__init__", _count)
    parses = _Spy(md_parser.parse_document)
    monkeypatch.setattr(md_parser, "parse_document", parses)

    _, answer = await _batch(world.mcp, [
        {"kind": "section", "repo": _MD, "path": "CRITICAL-PATTERNS", "section": "K11"},
        {"kind": "section", "repo": _MD, "path": "TESTING-PATTERNS", "section": "T1"},
    ])
    assert [entry["result"]["mode"] for entry in answer["items"]] == ["section", "section"]
    assert len(parses.calls) == 2, "הפרסור באמת רץ — אחרת הספירה למטה לא הייתה אומרת דבר"
    assert built == []


@requires_git
async def test_interleaved_items_from_large_files_match_a_run_without_sharing(tmp_path, monkeypatch):
    """פריטים מעורבבים משלושה קבצים גדולים — כל אחד זהה לכלי הבודד, שאינו משתף דבר.

    זה הטסט שהאישור ביקש על השמירה בין פריטים: הקיבוץ עונה על פריט מאוחר בזמן
    שהוא קורא קבוצה, ומחזיק את התשובה עד שהמעבר מגיע אליו. תשובה שהוחזקה, חושבה
    מהמסמך הלא נכון, או נכנסה במקום אחר, הייתה נראית כאן.
    """
    big = {}
    for name in ("A", "B", "C"):
        sections = "".join(
            f"## {name}{i}. סעיף {i}\n\n" + ("שורה בעברית עם תוכן כלשהו.\n" * 120) + "\n"
            for i in range(1, 4)
        )
        big[f"big/{name}.md"] = f"# קובץ {name}\n\n" + sections
    world = _world(tmp_path, monkeypatch, extra=big)
    reads = _Spy(world.mirror.get_file_at_commit)
    monkeypatch.setattr(world.mirror, "get_file_at_commit", reads)

    cases = []
    for i in range(1, 4):
        for name in ("A", "B", "C"):
            cases.append(({"kind": "section", "repo": _MD, "path": f"big/{name}", "section": f"{name}{i}"},
                          ("codekeeper_docs_get_section", {"repo": _MD, "path": f"big/{name}", "section": f"{name}{i}"})))
    cases.append(({"kind": "file", "repo": _MD, "path": "big/B.md"},
                  ("codekeeper_get_repo_file", {"repo": _MD, "path": "big/B.md"})))

    _, answer = await _batch(world.mcp, [item for item, _ in cases])
    assert len(reads.calls) == 3, "קריאה אחת לכל קובץ, גם כשהפריטים שלו מפוזרים"
    assert "unread" not in answer
    for entry, (item, (tool, arguments)) in zip(answer["items"], cases):
        assert _as_sent(entry["result"]) == await _text(world.mcp, tool, arguments), item


@requires_git
async def test_every_item_of_a_repo_is_read_at_one_commit_even_when_the_branch_moves(tmp_path, monkeypatch):
    """הענף זז בין הקריאה הראשונה לשנייה — ובכל זאת שני הפריטים מאותו commit.

    דטרמיניסטי, בלי ``sleep``: commit שני כבר קיים בריפו העובד, וה-``fetch``
    שמביא אותו למראה רץ מתוך הקריאה הראשונה, אחרי שהיא הסתיימה. **מוטציה
    שמפילה:** לפתור את ה-ref מחדש לכל פריט.
    """
    world = _world(tmp_path, monkeypatch)
    first_commit = _git("rev-parse", "main", cwd=world.md_work)
    _commit(world.md_work, {"bugbot-rules/two.md": "# שניים\n\nתוכן שני, גרסה שנייה.\n"}, "move")

    def _move_the_branch(calls: int) -> None:
        if calls == 1:
            _git("fetch", "-q", cwd=world.mirrors / f"{_MD}.git")

    reads = _Spy(world.mirror.get_file_at_commit, after=_move_the_branch)
    monkeypatch.setattr(world.mirror, "get_file_at_commit", reads)

    _, answer = await _batch(world.mcp, [
        {"kind": "file", "repo": _MD, "path": "bugbot-rules/one.md"},
        {"kind": "file", "repo": _MD, "path": "bugbot-rules/two.md"},
    ])
    moved = _git("rev-parse", "main", cwd=world.mirrors / f"{_MD}.git")
    assert moved != first_commit, "הענף באמת זז באמצע הבאץ'"
    commits = {entry["resolved_commit"] for entry in answer["items"]}
    assert commits == {first_commit}
    assert "גרסה ראשונה" in answer["items"][1]["result"]["content"]
    assert {entry["result"]["file"]["ref"] for entry in answer["items"]} == {"refs/heads/main"}, (
        "התשובה מדווחת את ה-ref שהתבקש, כמו הכלי הבודד — לא את ה-SHA")


@requires_git
async def test_a_transient_pin_failure_is_logged_once_and_each_item_names_its_commit(tmp_path, monkeypatch):
    """הקיבוע נכשל ב-``timeout``: הקריאה ממשיכה בשם הענף, אזהרה אחת לריפו, ו-``resolved_commit`` בכל פריט."""
    world = _world(tmp_path, monkeypatch)
    monkeypatch.setattr(world.mirror, "resolve_commit", lambda repo, ref: {"ok": False, "error": "timeout"})
    with _records("mcp_server.repo_backend") as records:
        _, answer = await _batch(world.mcp, [
            {"kind": "file", "repo": _MD, "path": "bugbot-rules/one.md"},
            {"kind": "section", "repo": _MD, "path": "CRITICAL-PATTERNS", "section": "K11"},
        ])
    head = _git("rev-parse", "main", cwd=world.md_work)
    assert [entry["resolved_commit"] for entry in answer["items"]] == [head, head]
    warnings = [r for r in records if r.levelno == logging.WARNING and "could not pin" in r.getMessage()]
    assert len(warnings) == 1


@requires_git
async def test_a_ref_that_does_not_exist_is_not_logged_and_answers_like_the_single_tool(tmp_path, monkeypatch):
    """``invalid_ref`` הוא תשובה רגילה ולא תקלה: בלי לוג, והפריט מקבל את מה שהכלי הבודד היה מחזיר."""
    world = _world(tmp_path, monkeypatch)
    world.backend._db["repo_metadata"].docs[0]["default_branch"] = "no-such-branch"
    with _records("mcp_server.repo_backend") as records:
        await _assert_identical(world, [
            ({"kind": "file", "repo": _MD, "path": "bugbot-rules/one.md"},
             ("codekeeper_get_repo_file", {"repo": _MD, "path": "bugbot-rules/one.md"})),
        ])
    assert not [r for r in records if r.levelno >= logging.WARNING]


# ===========================================================================
# 3. תקציב הבתים — בעברית, שלם או לא בכלל
# ===========================================================================

_HEBREW_LINE = "שורת עברית שמודדת בתים ולא תווים.\n"


def _hebrew_files(count: int, lines: int) -> dict[str, str]:
    return {f"heb/{i}.md": f"# קובץ {i}\n\n" + _HEBREW_LINE * lines for i in range(count)}


async def _costs(world: _World, items: list[dict[str, Any]]) -> list[int]:
    """מה שכל פריט עולה בחשבון של הכלי — מתשובה שנבנתה באמת, בתקציב שאינו חוסם."""
    _, answer = await _batch(world.mcp, items)
    assert "unread" not in answer
    return [read_batch._entry_cost(entry) for entry in answer["items"]]


@requires_git
async def test_an_answer_that_fits_exactly_is_whole_and_one_byte_less_leaves_the_last_item_unread(tmp_path, monkeypatch):
    """גבול התקציב, בעברית: בדיוק ← הכול נכנס; בית אחד פחות ← הפריט האחרון ב-``unread``.

    **מוטציה שמפילה:** ``>=`` במקום ``>`` בהשוואה של התקציב.
    """
    world = _world(tmp_path, monkeypatch, extra=_hebrew_files(3, 40))
    items = [{"kind": "file", "repo": _MD, "path": f"heb/{i}.md"} for i in range(3)]
    costs = await _costs(world, items)
    exact = read_batch._reserve(len(items)) + sum(costs)

    monkeypatch.setattr(read_batch, "OUTPUT_BYTE_BUDGET", exact)
    text, whole = await _batch(world.mcp, items)
    assert whole["count"] == 3 and "unread" not in whole
    assert len(text.encode("utf-8")) <= exact

    monkeypatch.setattr(read_batch, "OUTPUT_BYTE_BUDGET", exact - 1)
    text, short = await _batch(world.mcp, items)
    assert short["count"] == 2
    assert short["unread"] == [2] and short["unread_reason"] == "byte_budget"
    assert len(text.encode("utf-8")) <= exact - 1


@requires_git
async def test_an_item_larger_than_the_budget_alone_is_refused_and_not_cut(tmp_path, monkeypatch):
    """פריט גדול מהתקציב לבדו: ``item_too_large`` עם הגודל, התקרה והכלי הבודד — ולא חצי תוכן.

    **מוטציה שמפילה:** לחתוך את התוכן כדי שייכנס, במקום לדחות.
    """
    files = {"heb/small.md": "# קטן\n\nשורה.\n", "heb/huge.md": "# ענק\n\n" + _HEBREW_LINE * 400}
    world = _world(tmp_path, monkeypatch, extra=files)
    items = [
        {"kind": "file", "repo": _MD, "path": "heb/small.md"},
        {"kind": "file", "repo": _MD, "path": "heb/huge.md"},
        {"kind": "section", "repo": _MD, "path": "heb/huge", "section": "ענק"},
        {"kind": "file", "repo": _MD, "path": "heb/small.md"},
    ]
    budget = 6_000
    monkeypatch.setattr(read_batch, "OUTPUT_BYTE_BUDGET", budget)
    text, answer = await _batch(world.mcp, items)

    assert answer["count"] == 4 and "unread" not in answer
    too_large = answer["items"][1]["result"]
    assert set(too_large) == {"ok", "error", "bytes", "max", "read_with"}
    assert too_large["error"] == "item_too_large" and too_large["bytes"] > too_large["max"]
    assert too_large["max"] == budget - read_batch._reserve(len(items))
    assert too_large["read_with"] == "codekeeper_get_repo_file"
    assert answer["items"][2]["result"]["read_with"] == "codekeeper_docs_get_section"
    assert answer["items"][0]["result"]["status"] == "ok"
    assert answer["items"][3]["result"]["status"] == "ok"
    assert len(text.encode("utf-8")) <= budget


@requires_git
async def test_items_past_the_budget_are_listed_as_unread_from_the_first_that_did_not_fit(tmp_path, monkeypatch):
    """הסכום עובר: רצף מתחילת הבקשה נכנס, ומהפריט הראשון שלא נכנס — כולם ב-``unread``.

    כולל פריט קטן **אחרי** החור, שהיה נכנס לבדו: התשובה היא רצף, כדי ש-``unread``
    יהיה רשימה אחת לשלוח שוב וסיבה אחת. והתשובה כולה — עם רשימת ה-``unread`` —
    בתוך התקציב, כי מקום המעטפת נשמר מראש.

    **התקציב נבחר על הקצה שהשמירה מכריעה:** חסר בית אחד לפריט השלישי **יחד עם**
    המעטפת השמורה. **מוטציה שמפילה:** לבטל את השמירה — אז הפריט השלישי נכנס.
    """
    world = _world(tmp_path, monkeypatch, extra=_hebrew_files(4, 60))
    items = [{"kind": "file", "repo": _MD, "path": f"heb/{i}.md"} for i in range(4)]
    items.append({"kind": "section", "repo": _MD, "path": "CRITICAL-PATTERNS", "section": "K11"})
    costs = await _costs(world, items)
    budget = read_batch._reserve(len(items)) + costs[0] + costs[1] + costs[2] - 1
    monkeypatch.setattr(read_batch, "OUTPUT_BYTE_BUDGET", budget)

    text, answer = await _batch(world.mcp, items)
    assert [entry["index"] for entry in answer["items"]] == [0, 1]
    assert answer["unread"] == [2, 3, 4] and answer["unread_reason"] == "byte_budget"
    assert len(text.encode("utf-8")) <= budget
    assert len(json.dumps(answer, ensure_ascii=False).encode("utf-8")) <= budget, (
        "ובנוסחה של הריפו — שלעולם אינה גדולה מהצורה שנשלחת")


def test_the_accounting_never_undercounts_what_is_sent():
    """החשבון (מעטפת שמורה + מחיר כל פריט) לעולם אינו קטן מהתשובה כפי שהיא נשלחת.

    מבנים אקראיים עם עברית, תווי בקרה, קינון ורשימות ריקות — הצורות שבהן
    ההזחה של ``indent=2`` משנה את הגודל. והפער חסום: פסיק אחד לפריט ומקום
    רשימת ה-``unread`` הגרועה.
    """
    rng = random.Random(7)
    atoms = [1, 22, True, None, "שלום עולם", "a\nb\tc", "x" * 40, 3.5, "", "\u0001 "]

    def value(depth: int = 0) -> Any:
        roll = rng.random()
        if depth > 3 or roll < 0.3:
            return rng.choice(atoms)
        if roll < 0.65:
            return {f"k{i}": value(depth + 1) for i in range(rng.randint(0, 4))}
        return [value(depth + 1) for _ in range(rng.randint(0, 4))]

    for _ in range(2_000):
        count = rng.randint(1, 20)
        kept = rng.randint(0, count)
        entries = [{"index": i, "request": value(), "result": value()} for i in range(kept)]
        answer: dict[str, Any] = {"ok": True, "count": kept, "items": entries}
        if kept < count:
            answer["unread"] = list(range(kept, count))
            answer["unread_reason"] = rng.choice(["byte_budget", "timeout"])
        sent = len(_as_sent(answer).encode("utf-8"))
        accounted = read_batch._reserve(count) + sum(read_batch._entry_cost(e) for e in entries)
        assert sent <= accounted <= sent + read_batch._reserve(count) + kept


def test_the_wire_form_is_never_smaller_than_the_repos_formula():
    """``indent=2`` רק מוסיף — ולכן תשובה שנכנסת בצורה שנשלחת נכנסת גם בנוסחה של הריפו."""
    sample = {"a": ["שלום", 1, {"b": None, "c": "x\ny"}], "d": [], "e": {}}
    assert len(_as_sent(sample).encode("utf-8")) >= len(json.dumps(sample, ensure_ascii=False).encode("utf-8"))


# ===========================================================================
# 4. תקרות — נדחות ולא נצמדות, ולפני השקילה
# ===========================================================================


@requires_git
async def test_more_items_than_the_cap_are_refused_whole_and_nothing_is_read(tmp_path, monkeypatch):
    world = _world(tmp_path, monkeypatch, rate=60)
    reads = _Spy(world.mirror.get_file_at_commit)
    monkeypatch.setattr(world.mirror, "get_file_at_commit", reads)
    item = {"kind": "file", "repo": _MD, "path": "bugbot-rules/one.md"}

    _, refused = await _batch(world.mcp, [item] * (read_batch.MAX_BATCH_ITEMS + 1))
    assert refused == {"ok": False, "error": "too_many_items",
                       "count": read_batch.MAX_BATCH_ITEMS + 1, "max": read_batch.MAX_BATCH_ITEMS}
    assert reads.calls == [], "נדחה ולא נצמד: שום פריט לא נקרא"

    _, empty = await _batch(world.mcp, [])
    assert empty == {"ok": False, "error": "missing_items"}


@requires_git
async def test_the_cap_is_refused_before_the_weighing(tmp_path, monkeypatch):
    """בקשה של 50 פריטים מזהות שמיצתה את המכסה מקבלת ``too_many_items`` — לא ``rate_limited``.

    ובקשה שנדחתה על התקרה אינה עולה יחידה: באץ' מלא עובר מיד אחריה. **מוטציה
    שמפילה:** להזיז את בדיקת התקרה אל אחרי ``admit``.
    """
    world = _world(tmp_path, monkeypatch, rate=read_batch.MAX_BATCH_ITEMS)
    item = {"kind": "file", "repo": _MD, "path": "bugbot-rules/one.md"}

    _, over = await _batch(world.mcp, [item] * 50)
    assert over["error"] == "too_many_items"
    _, full = await _batch(world.mcp, [item] * read_batch.MAX_BATCH_ITEMS)
    assert full["ok"] is True and full["count"] == read_batch.MAX_BATCH_ITEMS
    _, still_over = await _batch(world.mcp, [item] * 50)
    assert still_over["error"] == "too_many_items", "גם כשהמכסה מלאה, הסיבה האמיתית היא התקרה"
    _, empty = await _batch(world.mcp, [])
    assert empty == {"ok": False, "error": "missing_items"}


@requires_git
async def test_a_per_minute_limit_below_the_cap_lowers_the_cap(tmp_path, monkeypatch):
    """מכסה של 5 לדקה: באץ' של 6 לעולם לא היה עובר, ולכן הוא ``too_many_items`` עם ``max`` 5."""
    world = _world(tmp_path, monkeypatch, rate=5)
    item = {"kind": "file", "repo": _MD, "path": "bugbot-rules/one.md"}
    _, refused = await _batch(world.mcp, [item] * 6)
    assert refused == {"ok": False, "error": "too_many_items", "count": 6, "max": 5}
    _, fits = await _batch(world.mcp, [item] * 5)
    assert fits["count"] == 5


# ===========================================================================
# 5. קצב — N פריטים עולים N, וההכרעה לפני כל עבודה
# ===========================================================================


@requires_git
async def test_a_batch_costs_one_call_per_item_and_is_refused_whole_before_any_read(tmp_path, monkeypatch):
    """מכסה של 20: באץ' של 14 עובר, באץ' של 7 נדחה בלי לקרוא דבר, באץ' של 6 עובר.

    **מוטציה שמפילה:** לחייב יחידה אחת לבאץ' — אז גם ה-7 היה עובר.
    """
    world = _world(tmp_path, monkeypatch, rate=20)
    reads = _Spy(world.mirror.get_file_at_commit)
    monkeypatch.setattr(world.mirror, "get_file_at_commit", reads)
    item = {"kind": "file", "repo": _MD, "path": "bugbot-rules/one.md"}

    _, first = await _batch(world.mcp, [item] * 14)
    assert first["ok"] is True
    reads.calls.clear()

    _, refused = await _batch(world.mcp, [item] * 7)
    assert refused["ok"] is False and refused["error"] == "rate_limited"
    assert refused["limit_per_minute"] == 20 and 0 < refused["retry_after_seconds"] <= 60
    assert reads.calls == [], "הסירוב קרה לפני שפריט אחד נקרא"

    _, last = await _batch(world.mcp, [item] * 6)
    assert last["ok"] is True and last["count"] == 6


@requires_git
async def test_a_non_admin_does_not_see_the_tool_and_is_refused_by_the_body(tmp_path, monkeypatch):
    """מי שאינו אדמין: לא ברשימה, ``require_admin`` מסרב — ולא לומד את התקרה ממשהו אחר.

    ``too_many_items`` היה מגלה לו שהכלי קיים ומה התקרה שלו, ולכן הבדיקה המוקדמת
    רצה רק לאדמין; הוא מחויב קריאה אחת, כמו כל קריאה שהגוף מסרב לה.
    """
    world = _world(tmp_path, monkeypatch, rate=60)
    with _as(_OTHER):
        names = {tool.name for tool in await world.mcp.list_tools()}
    assert read_batch.TOOL_NAME not in names
    with _as(_ADMIN):
        listed = {tool.name: tool for tool in await world.mcp.list_tools()}
    assert read_batch.TOOL_NAME in listed

    item = {"kind": "file", "repo": _MD, "path": "bugbot-rules/one.md"}
    with pytest.raises(ToolError, match="admin_only"):
        await _batch(world.mcp, [item], user=_OTHER)
    with pytest.raises(ToolError, match="admin_only"):
        await _batch(world.mcp, [item] * 50, user=_OTHER)


def test_the_tool_is_admin_only_read_only_and_runs_on_the_read_pool():
    """``_ADMIN_TOOLS``, ``readOnlyHint`` מפורש, ומאגר הקריאות ולא תור הכתיבה.

    **מוטציה שמפילה:** להסיר את ``readOnlyHint`` — ``_declares_write`` נכשל-סגור
    והכלי היה נכנס לתור של העובד היחיד.
    """
    mcp = srv.build_mcp(object(), repo_backend=object())
    tool = mcp._tool_manager.get_tool(read_batch.TOOL_NAME)
    assert read_batch.TOOL_NAME in srv._ADMIN_TOOLS
    assert srv._declares_write(tool.annotations) is False
    assert tool.fn.__code__.co_name == "_run_on_shared_pool"
    assert not inspect.iscoroutinefunction(tool.fn.__wrapped__), "גוף סינכרוני, שעובר לחוט"


# ===========================================================================
# 6. חריגה בפריט, ודדליין
# ===========================================================================


@requires_git
async def test_an_exception_in_one_item_is_an_internal_error_for_that_item_alone(tmp_path, monkeypatch):
    world = _world(tmp_path, monkeypatch)
    real = docs_handlers.answer_section

    def _breaks_on_k13(loaded, *, section=None, **kwargs):
        if section == "K13":
            raise RuntimeError("synthetic")
        return real(loaded, section=section, **kwargs)

    monkeypatch.setattr(docs_handlers, "answer_section", _breaks_on_k13)
    with _records("mcp_server.read_batch") as records:
        _, answer = await _batch(world.mcp, [
            {"kind": "section", "repo": _MD, "path": "CRITICAL-PATTERNS", "section": "K11"},
            {"kind": "section", "repo": _MD, "path": "CRITICAL-PATTERNS", "section": "K13"},
            {"kind": "file", "repo": _MD, "path": "bugbot-rules/one.md"},
        ])
    results = [entry["result"] for entry in answer["items"]]
    assert results[0]["mode"] == "section"
    assert results[1] == {"ok": False, "error": "internal_error"}
    assert results[2]["status"] == "ok"
    logged = [r for r in records if r.levelno == logging.ERROR]
    assert len(logged) == 1 and logged[0].exc_info is not None


@requires_git
async def test_an_exception_while_reading_a_group_fails_that_group_and_is_logged_once(tmp_path, monkeypatch):
    world = _world(tmp_path, monkeypatch)
    real = repo_handlers.get_repo_file

    def _breaks_on_one(backend, **kwargs):
        if kwargs["path"] == "bugbot-rules/one.md":
            raise RuntimeError("synthetic")
        return real(backend, **kwargs)

    monkeypatch.setattr(repo_handlers, "get_repo_file", _breaks_on_one)
    with _records("mcp_server.read_batch") as records:
        _, answer = await _batch(world.mcp, [
            {"kind": "file", "repo": _MD, "path": "bugbot-rules/one.md"},
            {"kind": "file", "repo": _MD, "path": "bugbot-rules/two.md"},
            {"kind": "file", "repo": _MD, "path": "bugbot-rules/one.md"},
        ])
    results = [entry["result"] for entry in answer["items"]]
    assert results[0] == results[2] == {"ok": False, "error": "internal_error"}
    assert results[1]["status"] == "ok"
    assert len([r for r in records if r.levelno == logging.ERROR]) == 1


class _Clock:
    """שעון מוזרק: ערך קבוע, שמתקדם רק כשמשהו מקדם אותו."""

    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@requires_git
async def test_the_deadline_stops_before_the_next_read_and_what_was_read_comes_back(tmp_path, monkeypatch):
    """כל קריאה מהמראה "לוקחת" שש שניות: שתיים נקראות, והשלישית ב-``unread`` עם ``timeout``.

    **מוטציה שמפילה:** לבדוק את הדדליין רק בסוף הבאץ' — אז שלושתן היו נקראות.
    """
    world = _world(tmp_path, monkeypatch)
    clock = _Clock()
    monkeypatch.setattr(read_batch, "clock", clock)

    def _slow(calls: int) -> None:
        clock.now += 6.0

    reads = _Spy(world.mirror.get_file_at_commit, after=_slow)
    monkeypatch.setattr(world.mirror, "get_file_at_commit", reads)

    _, answer = await _batch(world.mcp, [
        {"kind": "file", "repo": _MD, "path": "bugbot-rules/one.md"},
        {"kind": "file", "repo": _MD, "path": "bugbot-rules/two.md"},
        {"kind": "section", "repo": _MD, "path": "CRITICAL-PATTERNS", "section": "K11"},
    ])
    assert len(reads.calls) == 2
    assert [entry["index"] for entry in answer["items"]] == [0, 1]
    assert answer["unread"] == [2] and answer["unread_reason"] == "timeout"


@requires_git
async def test_the_deadline_counts_from_the_moment_the_call_arrived(tmp_path, monkeypatch):
    """השעון של הלקוח התחיל ב-``call_tool``, כולל ההמתנה לחוט — וכך גם הדדליין.

    הכניסה נרשמת ב-1,000; עד שהגוף מגיע לקריאה הראשונה עברו עשר וחצי שניות.
    הפריט שנענה בלי קריאה (``invalid_item``) חוזר, והקובץ אינו נקרא. **מוטציה
    שמפילה:** למדוד מתחילת הגוף — אז הדדליין היה 1,020.5 והקובץ היה נקרא.
    """
    world = _world(tmp_path, monkeypatch)
    ticks = iter([1_000.0])

    def _clock() -> float:
        return next(ticks, 1_010.5)

    monkeypatch.setattr(read_batch, "clock", _clock)
    reads = _Spy(world.mirror.get_file_at_commit)
    monkeypatch.setattr(world.mirror, "get_file_at_commit", reads)

    _, answer = await _batch(world.mcp, [
        {"kind": "nope"},
        {"kind": "file", "repo": _MD, "path": "bugbot-rules/one.md"},
    ])
    assert reads.calls == []
    assert [entry["index"] for entry in answer["items"]] == [0]
    assert answer["items"][0]["result"]["error"] == "invalid_item"
    assert answer["unread"] == [1] and answer["unread_reason"] == "timeout"


# ===========================================================================
# 7. החוזה המוצהר: סכימה, ``_meta``, תיאור, אנליטיקס
# ===========================================================================


async def test_the_advertised_item_schema_is_the_one_the_body_validates_with():
    mcp = srv.build_mcp(object(), repo_backend=object())
    mcp._request_is_admin = lambda: True
    (tool,) = [t for t in await mcp.list_tools() if t.name == read_batch.TOOL_NAME]
    items = tool.inputSchema["properties"]["items"]
    assert items["type"] == "array"
    assert items["items"] == {"oneOf": [read_batch.SectionItem.model_json_schema(),
                                        read_batch.FileItem.model_json_schema()]}
    assert "$defs" not in json.dumps(tool.inputSchema) and "$ref" not in json.dumps(tool.inputSchema)
    assert str(read_batch.MAX_BATCH_ITEMS) in tool.description
    assert str(repo_handlers.OUTPUT_BYTE_BUDGET) in items["description"]


async def test_the_tool_declares_its_result_size_in_characters_as_the_byte_budget():
    """``anthropic/maxResultSizeChars`` = תקציב הבתים: תווים ≤ בתים, ולכן התשובה לעולם אינה עוברת אותו."""
    mcp = srv.build_mcp(object(), repo_backend=object())
    mcp._request_is_admin = lambda: True
    (tool,) = [t for t in await mcp.list_tools() if t.name == read_batch.TOOL_NAME]
    assert tool.meta == {"anthropic/maxResultSizeChars": repo_handlers.OUTPUT_BYTE_BUDGET}
    assert read_batch.MAX_RESULT_CHARS == repo_handlers.OUTPUT_BYTE_BUDGET


def test_a_section_item_uses_the_single_tools_defaults():
    """``answer_section`` נושא את ברירות המחדל של ``docs_get_section`` — ושתי החתימות לא נפרדו."""
    batch = inspect.signature(docs_handlers.answer_section).parameters
    single = inspect.signature(docs_handlers.docs_get_section).parameters
    for name in ("section", "include_subsections", "max_chars", "offset"):
        assert batch[name].default == single[name].default, name


def test_the_single_tools_named_in_item_too_large_are_real_tools():
    mcp = srv.build_mcp(object(), repo_backend=object())
    names = {tool.name for tool in mcp._tool_manager.list_tools()}
    assert set(read_batch._SINGLE_TOOL.values()) <= names


def test_the_batch_carries_no_read_mode_label():
    """מחוץ ל-``_TOOL_READ_MODE_PARAMS`` בכוונה, כמו ``codekeeper_get_note``: אין ``ck_read_mode``."""
    request = {"method": "tools/call", "params": {
        "name": read_batch.TOOL_NAME,
        "arguments": {"items": [{"kind": "file", "repo": _MD, "path": "x.md", "lines": [1, 2]}]},
    }}
    assert analytics.read_mode_properties(request) is None
    assert read_batch.TOOL_NAME not in analytics._TOOL_READ_MODE_PARAMS


# ===========================================================================
# 8. המגביל המשותף — משקל, הכול או כלום
# ===========================================================================


async def test_a_weighted_charge_is_all_or_nothing():
    limiter = RateLimiter(max_per_minute=5)
    assert await limiter.check_rate_limit(1, weight=3) is True
    assert await limiter.check_rate_limit(1, weight=3) is False, "נשארו שתיים — שלוש לא נכנסות"
    assert await limiter.get_current_usage_ratio(1) == pytest.approx(3 / 5), "סירוב לא רשם אף יחידה"
    assert await limiter.check_rate_limit(1, weight=2) is True
    assert await limiter.check_rate_limit(1) is False


async def test_concurrent_weighted_charges_never_exceed_the_window():
    """עשר קריאות בו-זמנית במשקל 3 מול חלון של 10: בדיוק שלוש עוברות (U1, T1(d))."""
    limiter = RateLimiter(max_per_minute=10)
    admitted = await asyncio.gather(*(limiter.check_rate_limit(1, weight=3) for _ in range(10)))
    assert sum(admitted) == 3
    assert len(limiter._requests[1]) == 9


async def test_the_wait_is_until_the_whole_weight_fits():
    """החלון מלא (5 מתוך 5): משקל 1 מחכה לרשומה הראשונה, משקל 3 — לשלישית."""
    from datetime import datetime, timedelta, timezone

    limiter = RateLimiter(max_per_minute=5)
    now = datetime.now(timezone.utc)
    limiter._requests[1] = [now - timedelta(seconds=50 - i) for i in range(5)]
    assert 9 <= await limiter.seconds_until_allowed(1) <= 10
    assert 11 <= await limiter.seconds_until_allowed(1, weight=3) <= 12


@pytest.mark.parametrize("weight", [0, -1, 6])
async def test_a_weight_outside_the_window_is_a_bug_of_the_caller(weight):
    limiter = RateLimiter(max_per_minute=5)
    with pytest.raises(ValueError):
        await limiter.check_rate_limit(1, weight=weight)
    with pytest.raises(ValueError):
        await limiter.seconds_until_allowed(1, weight=weight)


# ===========================================================================
# 9. ``GitMirrorService.resolve_commit``
# ===========================================================================


@requires_git
def test_resolve_commit_answers_the_sha_or_names_why_not(tmp_path):
    work = _mirror(tmp_path, "r", {"a.md": "x\n"})
    mirror = GitMirrorService(base_path=str(tmp_path / "mirrors"))
    assert mirror.resolve_commit("r", "refs/heads/main") == {"ok": True, "commit": _git("rev-parse", "main", cwd=work)}
    assert mirror.resolve_commit("r", "refs/heads/nope") == {"ok": False, "error": "invalid_ref"}
    assert mirror.resolve_commit("missing", "HEAD") == {"ok": False, "error": "repo_not_found"}
    assert mirror.resolve_commit("../r", "HEAD") == {"ok": False, "error": "invalid_repo_name"}
