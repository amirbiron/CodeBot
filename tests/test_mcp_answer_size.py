"""תקרת התשובה של כלי MCP: ההצהרה ב-``tools/list``, הרשת, והקלט הגרוע של כל כלי (#3460).

שלושה דברים נבדקים כאן, בשלוש קבוצות:

1. **הרשת** (``AdminAwareFastMCP._within_declared_size``) — עם תקרה קטנה שמוזרקת לכלי
   בטסט, כך שעלות הבדיקה אינה קשורה ל-``OUTPUT_BYTE_BUDGET``: כלי שמצהיר ועובר את מה
   שהצהיר מקבל סירוב, בשני הענפים של ``call_tool``, גם כשהוא נרשם בדרך שעוקפת את
   ``add_tool``; כלי שאינו מצהיר אינו נוגעים בו; וכל בלוק נספר.
2. **ההצהרה** — נגזרת מהרישום של הכלי, והערך שלה נבדק ברישום. דרך session אמיתי של
   הפרוטוקול, עם PostHog דלוק, כי זו התצורה שהלקוח רואה.
3. **כל כלי שמצהיר עומד בתקרה בעצמו** — על הקלט הגרוע שלו, דרך ``call_tool``, בלי
   שהרשת נדלקת (``_assert_net_silent``). המספרים של הקלטים נמדדו על main לפני התיקון,
   ורשומים בגוף ה-PR.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import logging
import shutil
import subprocess
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
from mcp_server import analytics, answer_size, docs_handlers, handlers, read_batch, repo_handlers  # noqa: E402
from mcp_server.backend import ProductionBackend  # noqa: E402
from mcp_server.repo_backend import RepoBackend  # noqa: E402
from services.git_mirror_service import GitMirrorService  # noqa: E402

_GIT = shutil.which("git")
requires_git = pytest.mark.skipif(_GIT is None, reason="git is not installed")

BUDGET = answer_size.OUTPUT_BYTE_BUDGET
_USER = 4242
_DOC_ID = "a" * 24
_MD_REPO = "amir-bug-patterns"  # מדיניות התיעוד: שורש הריפו, .md
_CODE_REPO = "CodeBot"

#: הכלים שמצהירים על תקרת תשובה — ההחלטה של #3460, לא רשימה שהקוד קורא ממנה. הקוד
#: קורא את ההצהרה מהרישום של כל כלי; הרשימה כאן מקבעת **אילו** כלים הוחלט שיצהירו.
#: ``codekeeper_list_repo_notes`` אינו ביניהם בכוונה: 20 פתקים של 20,000 תווים הם
#: לפחות 400,000 בתים, ואין לו מצב רזה.
DECLARING = frozenset({
    "codekeeper_get_file",
    "codekeeper_get_repo_file",
    "codekeeper_search_repo",
    "codekeeper_list_repo_tree",
    "codekeeper_list_notes",
    "codekeeper_list_board_notes",
    "codekeeper_docs_get_section",
    "codekeeper_read_batch",
})


# ---------------------------------------------------------------------------
# עזרים
# ---------------------------------------------------------------------------


def _sent(result: Any) -> tuple[dict[str, Any], int]:
    """התשובה ומספר הבתים שלה **כפי שנשלחה** — בלוק הטקסט היחיד, לא הערכה."""
    blocks = result.content if isinstance(result, mcp_types.CallToolResult) else result
    blocks = blocks[0] if isinstance(blocks, tuple) else blocks
    (block,) = blocks
    return json.loads(block.text), len(block.text.encode("utf-8"))


@contextlib.contextmanager
def _as_admin():
    """מה שה-SDK קובע לכל ``tools/call``: הקשר בקשה, ומשתמש מאומת מהטוקן."""
    request_token = request_ctx.set(RequestContext(request_id=1, meta=None, session=None, lifespan_context=None))
    access = AccessToken(token="t", client_id="c", scopes=["read"], subject=str(_USER))
    auth_token = auth_context_var.set(AuthenticatedUser(access))
    try:
        yield
    finally:
        auth_context_var.reset(auth_token)
        request_ctx.reset(request_token)


async def _call(mcp: Any, name: str, arguments: dict[str, Any]) -> tuple[dict[str, Any], int]:
    with _as_admin():
        return _sent(await mcp.call_tool(name, arguments))


@pytest.fixture
def net_log(caplog):
    """הרשומות של הרשת — ``answer_size_net`` הוא הסמן הקבוע שלה בלוג."""
    caplog.set_level(logging.WARNING, logger=srv.logger.name)
    return lambda: [r for r in caplog.records if "answer_size_net" in r.getMessage()]


def _assert_net_silent(net_log) -> None:
    """הכלי התאים את התשובה בעצמו: הרשת לא נדרשה. בלי זה, טסט של כלי היה עובר גם כשרק הרשת עוצרת."""
    assert net_log() == [], "הרשת תפסה תשובה שהכלי היה צריך להתאים בעצמו"


class _Dbm:
    """קובץ שמור אחד, בשלוש הקריאות ש-``ProductionBackend.get_file`` עושה."""

    def __init__(self, *, code: str | None = None, content: str | None = None, name: str = "big.txt",
                 language: str = "text", **extra: Any) -> None:
        self.doc = {"_id": _DOC_ID, "user_id": _USER, "file_name": name, "version": 2,
                    "programming_language": language, "is_active": True, **extra}
        if code is not None:
            self.doc["code"] = code
        if content is not None:
            self.doc["content"] = content

    def get_latest_version_fresh(self, user_id: int, file_name: str):
        return dict(self.doc) if (user_id, file_name) == (_USER, self.doc["file_name"]) else None

    def get_file_by_id(self, file_id: str):
        return dict(self.doc) if file_id == _DOC_ID else None

    def get_version(self, *args: Any):
        return None


def _saved(monkeypatch: Any, dbm: _Dbm) -> tuple[Any, ProductionBackend]:
    """שרת MCP אמיתי מעל ``ProductionBackend`` אמיתי, עם קובץ שמור אחד."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: _USER)
    backend = ProductionBackend(db_manager=dbm)
    return srv.build_mcp(backend, repo_backend=None, rate_limit_per_minute=0), backend


def _git(*args: str, cwd: Path) -> None:
    subprocess.run((_GIT, *args), cwd=str(cwd), check=True, capture_output=True)


def _mirror(tmp_path: Path, name: str, files: dict[str, str]) -> None:
    """ריפו עובד תחת ``tmp_path``, ומשם ``clone --mirror`` — המבנה שהשירות מצפה לו."""
    work = tmp_path / "work" / name
    work.mkdir(parents=True)
    _git("init", "-q", "-b", "main", ".", cwd=work)
    for rel, body in files.items():
        target = work / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body.encode("utf-8"))
    _git("add", "-A", cwd=work)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init", cwd=work)
    mirrors = tmp_path / "mirrors"
    mirrors.mkdir(exist_ok=True)
    _git("clone", "-q", "--mirror", str(work), str(mirrors / f"{name}.git"), cwd=tmp_path)


class _Collection:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self.docs = docs

    def find_one(self, query: dict[str, Any], *args: Any, **kwargs: Any):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return dict(doc)
        return None

    def find(self, *args: Any, **kwargs: Any):
        return []


class _Db(dict):
    """``db["x"]`` וגם ``db.x`` — כמו pymongo."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def _repos(tmp_path: Path, monkeypatch: Any, files: dict[str, dict[str, str]], *,
           search_service: Any = None) -> tuple[Any, RepoBackend]:
    """שרת MCP עם מראות git אמיתיות, ואדמין שמבקש."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("MCP_DOCS_REPO", f"{_MD_REPO},{_CODE_REPO}")
    from config import config as _cfg

    monkeypatch.setattr(_cfg, "ADMIN_USER_IDS", [_USER], raising=False)
    for name, repo_files in files.items():
        _mirror(tmp_path, name, repo_files)
    db = _Db({
        "repo_metadata": _Collection([{"repo_name": name, "default_branch": "main"} for name in files]),
        "sync_jobs": _Collection([]),
        "repo_files": _Collection([]),
    })
    backend = RepoBackend(db=db, mirror=GitMirrorService(base_path=str(tmp_path / "mirrors")),
                          search_service=search_service)
    return srv.build_mcp(object(), repo_backend=backend, rate_limit_per_minute=0), backend


_HEBREW_LINE = "שורה עברית ארוכה שמודדת בתים ולא תווים, " * 3
#: 300,000 תווים עבריים — פי שניים מהתקציב בבתים. נמדד על main: קריאה מלאה 547,927 בתים.
_BIG_HEBREW = "\n".join([_HEBREW_LINE] * (300_000 // len(_HEBREW_LINE)))


# ===========================================================================
# 1. הרשת
# ===========================================================================


def _toy_server(monkeypatch: Any) -> Any:
    monkeypatch.setenv("ENVIRONMENT", "production")
    return srv.build_mcp(object(), repo_backend=None, rate_limit_per_minute=0)


async def test_a_tool_over_what_it_declared_is_refused_and_one_that_declares_nothing_is_left_alone(
    monkeypatch, net_log,
):
    """הרשת קוראת את התקרה מהרישום של הכלי, ורק ממנו.

    תקרה קטנה מוזרקת בטסט (100), ולכן הבדיקה אינה תלויה ב-``OUTPUT_BYTE_BUDGET``. כלי
    שמצהיר ועובר — ``answer_too_large`` עם ``bytes`` (מה שהיה נשלח) ו-``max`` (מה שהוצהר);
    כלי בלי הצהרה — התשובה כמו שהיא, גם כשהיא גדולה. והלוג נושא את שם הכלי והמספרים,
    ולא את התשובה (K13).

    מוטציות שמפילות: הרשת לא נקראת (``return result`` ב-``call_tool``); הרשת קוראת תקרה
    גם לכלי שלא הצהיר.
    """
    mcp = _toy_server(monkeypatch)
    secret_body = "תוכן פרטי " * 40

    @mcp.tool(name="toy_declared", meta={answer_size.DECLARED_SIZE_KEY: 100})
    def toy_declared() -> dict:
        return {"body": secret_body}

    @mcp.tool(name="toy_silent")
    def toy_silent() -> dict:
        return {"body": secret_body}

    answer, sent = _sent(await mcp.call_tool("toy_declared", {}))
    whole = len(answer_size.wire_json({"body": secret_body}))
    assert answer == {"ok": False, "error": "answer_too_large", "bytes": whole, "max": 100,
                      "hint": srv._NET_HINT}
    assert sent <= 100 * 4  # הסירוב עצמו קטן; המספר המדויק אינו העניין כאן
    (record,) = net_log()
    message = record.getMessage()
    assert "toy_declared" in message and str(whole) in message and "100" in message
    assert "תוכן פרטי" not in message

    answer, sent = _sent(await mcp.call_tool("toy_silent", {}))
    assert answer == {"body": secret_body} and sent == whole
    assert len(net_log()) == 1


async def test_a_tool_registered_past_add_tool_is_still_held_to_its_meta(monkeypatch, net_log):
    """הרשת קוראת את ``Tool.meta`` בזמן הקריאה — גם כלי שנרשם ישירות ב-``ToolManager``.

    זה המסלול שעוקף את ``AdminAwareFastMCP.add_tool`` (ואיתו את בדיקת הערך). ההצהרה
    עדיין מגיעה ללקוח — ``FastMCP.list_tools`` שולח את ה-``meta`` של כל כלי — ולכן
    הרשת חייבת לחול עליו. מוטציה שמפילה: הרשת קוראת את התקרה מטבלה שנבנית ב-``add_tool``.
    """
    mcp = _toy_server(monkeypatch)

    def raw() -> dict:
        return {"body": "x" * 500}

    mcp._tool_manager.add_tool(raw, name="toy_raw", meta={answer_size.DECLARED_SIZE_KEY: 100})
    answer, _ = _sent(await mcp.call_tool("toy_raw", {}))
    assert answer["error"] == "answer_too_large" and answer["max"] == 100
    assert len(net_log()) == 1


@requires_git
async def test_the_net_holds_the_batch_branch_too(tmp_path, monkeypatch, net_log):
    """``codekeeper_read_batch`` עובר בענף אחר של ``call_tool`` (``ENTERED_AT``) — והרשת גם שם.

    מוטציה שמפילה: הרשת רק בענף הרגיל.
    """
    mcp, _ = _repos(tmp_path, monkeypatch, {_MD_REPO: {"a.md": "# א\n\n" + "שורה\n" * 200}})
    tool = mcp._tool_manager.get_tool(read_batch.TOOL_NAME)
    monkeypatch.setattr(tool, "meta", {answer_size.DECLARED_SIZE_KEY: 300})
    answer, _ = await _call(mcp, read_batch.TOOL_NAME,
                            {"items": [{"kind": "file", "repo": _MD_REPO, "path": "a.md"}]})
    assert answer["error"] == "answer_too_large" and answer["max"] == 300 and answer["bytes"] > 300
    assert len(net_log()) == 1


def test_every_block_of_what_is_sent_is_counted():
    """``_sent_bytes`` סופר כל בלוק ואת ``structuredContent`` — לא רק את הבלוק הראשון, לא רק טקסט.

    מוטציות שמפילות: למדוד רק ``content[0]``; לדלג על בלוק שאינו טקסט; להתעלם מ-
    ``structuredContent``; לנחש גודל לצורה שאינה מוכרת במקום ``None``.
    """
    text = mcp_types.TextContent(type="text", text="שלום")
    other = mcp_types.TextContent(type="text", text="x" * 10)
    image = mcp_types.ImageContent(type="image", data="QUFB", mimeType="image/png")
    image_bytes = len(answer_size.wire_json(image.model_dump(mode="json", by_alias=True)))
    structured = {"k": "ערך"}

    assert srv._sent_bytes([text]) == len("שלום".encode("utf-8"))
    assert srv._sent_bytes([text, other]) == 8 + 10
    assert srv._sent_bytes([text, image]) == 8 + image_bytes
    assert srv._sent_bytes(([text], structured)) == 8 + len(answer_size.wire_json(structured))
    assert srv._sent_bytes(mcp_types.CallToolResult(content=[text], structuredContent=structured)) == (
        8 + len(answer_size.wire_json(structured)))
    assert srv._sent_bytes(structured) == (
        len(json.dumps(structured, indent=2).encode("utf-8")) + len(answer_size.wire_json(structured)))
    assert srv._sent_bytes(object()) is None
    assert srv._sent_bytes([object()]) is None


def test_what_cannot_be_measured_is_refused(monkeypatch, net_log):
    """fail-closed: כלי שמצהיר ומחזיר צורה שאי אפשר למדוד — סירוב, ולא מעבר בשקט."""
    mcp = _toy_server(monkeypatch)

    @mcp.tool(name="toy_odd", meta={answer_size.DECLARED_SIZE_KEY: 1000})
    def toy_odd() -> dict:
        return {}

    refused = mcp._within_declared_size("toy_odd", object())
    answer, _ = _sent(refused)
    assert answer == {"ok": False, "error": "answer_too_large", "max": 1000, "hint": srv._NET_HINT}
    assert "unmeasurable" in net_log()[0].getMessage()


@pytest.mark.parametrize("value", [True, 0, -1, answer_size.CLIENT_CEILING_CHARS + 1, "256000", 1.5, None])
def test_a_declared_value_the_client_cannot_use_stops_the_registration(monkeypatch, value):
    """ערך שהלקוח לא יכבד — לא מספר שלם, בוליאני, אפס או פחות, מעל 500,000 — עוצר את הרישום.

    הכלי אינו נשאר רשום, כמו בשאר הסירובים של ``add_tool``. מוטציה שמפילה: לדלג על הבדיקה.
    """
    mcp = _toy_server(monkeypatch)
    with pytest.raises(TypeError, match=answer_size.DECLARED_SIZE_KEY):
        @mcp.tool(name="toy_bad", meta={answer_size.DECLARED_SIZE_KEY: value})
        def toy_bad() -> dict:
            return {}
    assert mcp._tool_manager.get_tool("toy_bad") is None


def test_the_ceiling_itself_is_accepted(monkeypatch):
    mcp = _toy_server(monkeypatch)

    @mcp.tool(name="toy_max", meta={answer_size.DECLARED_SIZE_KEY: answer_size.CLIENT_CEILING_CHARS})
    def toy_max() -> dict:
        return {}

    assert mcp._tool_manager.get_tool("toy_max") is not None


# ===========================================================================
# 2. ההצהרה, דרך session אמיתי עם PostHog דלוק
# ===========================================================================


async def test_the_declaration_the_client_sees_is_the_registration_and_the_net_holds_it(
    monkeypatch, net_log,
):
    """``_meta`` ב-``tools/list`` הוא בדיוק ה-``meta`` שכל כלי נרשם איתו — ושום דבר אחר.

    דרך session אמיתי של הפרוטוקול, עם האינסטרומנטציה של PostHog דלוקה (לקוח ``Posthog``
    אמיתי, ``send=False``) — התצורה של הייצור: היא עוטפת את ``tools/list`` ואת
    ``ToolManager.call_tool``. שלושה דברים:

    * לכל כלי, ``_meta`` שהלקוח רואה שווה ל-``Tool.meta`` שלו — אין הצהרה שאינה מהרישום;
    * הכלים שמצהירים הם בדיוק :data:`DECLARING`, וכולם מצהירים ``DECLARED_MAX_RESULT_CHARS``;
    * כלי שהתקרה שלו הונמכה בטסט מסורב גם כשהקריאה עוברת את כל השכבות.

    מוטציות שמפילות: ``list_tools`` שמזריק ``_meta`` לכלי שלא הצהיר; כלי שמצהיר בערך אחר;
    הצהרה שנמחקה מאחד הכלים.
    """
    from mcp.shared.memory import create_connected_server_and_client_session
    from posthog import Posthog

    client = Posthog("phc_test_token_not_real", host="https://us.i.posthog.com", send=False,
                     before_send=analytics.scrub_mcp_payload, enable_exception_autocapture=False,
                     capture_exception_code_variables=False)
    monkeypatch.setattr(analytics, "_CLIENT", client)
    monkeypatch.setattr(analytics, "_ANALYTICS", None)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: _USER)
    mcp = srv.build_mcp(ProductionBackend(db_manager=_Dbm(code="# a\n", name="a.md")),
                        repo_backend=object(), rate_limit_per_minute=0)
    monkeypatch.setattr(mcp, "_request_is_admin", lambda: True)

    async with create_connected_server_and_client_session(mcp._mcp_server) as session:
        listed = {tool.name: tool.meta for tool in (await session.list_tools()).tools}
        registered = {tool.name: tool.meta for tool in mcp._tool_manager.list_tools()}
        assert registered.keys() <= listed.keys()
        for name in listed.keys() - registered.keys():
            # הכלי הווירטואלי של PostHog (``get_more_tools``) — לא שלנו, ובלי הצהרה.
            assert not (listed[name] or {}).get(answer_size.DECLARED_SIZE_KEY), name
        for name, meta in registered.items():
            assert listed[name] == meta, name
        declaring = {name for name, meta in listed.items()
                     if (meta or {}).get(answer_size.DECLARED_SIZE_KEY) is not None}
        assert declaring == DECLARING
        for name in declaring:
            assert listed[name] == answer_size.declared_size_meta(), name

        tool = mcp._tool_manager.get_tool("codekeeper_get_file")
        monkeypatch.setattr(tool, "meta", {answer_size.DECLARED_SIZE_KEY: 50})
        result = await session.call_tool("codekeeper_get_file", {"file_name": "a.md", "context": "size check"})
        answer = json.loads(result.content[0].text)
        assert answer["error"] == "answer_too_large" and answer["max"] == 50
    assert len(net_log()) == 1


# ===========================================================================
# 3. כל כלי עומד בתקרה בעצמו — הקלט הגרוע שלו
# ===========================================================================

# --- codekeeper_get_file -----------------------------------------------------


async def test_a_whole_saved_file_over_the_budget_is_refused_with_a_way_to_read_it(monkeypatch, net_log):
    """קריאה מלאה של 300,000 תווים עבריים: על main — 547,927 בתים. עכשיו — סירוב שנכנס.

    ``bytes`` הוא גודל התשובה שהייתה נשלחת, ``file`` — המטא-דאטה בלי התוכן ועם ה-hash של
    הקובץ המלא, וה-``hint`` מפנה לפי סוג הקובץ. נופלת על main: שם התשובה המלאה יוצאת.
    """
    mcp, backend = _saved(monkeypatch, _Dbm(code=_BIG_HEBREW))
    answer, sent = await _call(mcp, "codekeeper_get_file", {"file_name": "big.txt"})

    whole = backend.get_file(_USER, file_name="big.txt")
    assert answer["ok"] is False and answer["error"] == "answer_too_large"
    assert answer["bytes"] == len(answer_size.wire_json({"found": True, "file": whole})) > BUDGET
    assert answer["max"] == BUDGET and sent <= BUDGET
    assert "code" not in answer["file"] and answer["file"]["content_sha256"] == whole["content_sha256"]
    assert "lines=[start, end]" in answer["hint"] and "query=" in answer["hint"]
    _assert_net_silent(net_log)


async def test_a_whole_markdown_file_points_at_its_heading_map(monkeypatch, net_log):
    mcp, _ = _saved(monkeypatch, _Dbm(code="# כותרת\n\n" + _BIG_HEBREW, name="big.md", language="markdown"))
    answer, sent = await _call(mcp, "codekeeper_get_file", {"file_name": "big.md"})
    assert answer["error"] == "answer_too_large" and sent <= BUDGET
    assert "toc=true" in answer["hint"]
    _assert_net_silent(net_log)


async def test_a_saved_file_that_fits_is_the_same_answer_as_before(monkeypatch, net_log):
    """אפס-דיף: תשובה שנכנסת היא ``{"found": true, "file": ...}`` כמו שהייתה, בלי שדה חדש."""
    mcp, backend = _saved(monkeypatch, _Dbm(code="שורה\n" * 100))
    answer, _ = await _call(mcp, "codekeeper_get_file", {"file_name": "big.txt"})
    assert answer == json.loads(answer_size.wire_json(
        {"found": True, "file": backend.get_file(_USER, file_name="big.txt")}))
    _assert_net_silent(net_log)


async def _read_in_ranges(mcp: Any, name: str, arguments: dict[str, Any], range_of) -> tuple[list[str], int]:
    """קורא קובץ בטווחים עד סופו, ממשיך תמיד מ-``end + 1``. מחזיר את השורות, ומספר הקריאות."""
    start, pieces, calls = 1, [], 0
    while True:
        answer, sent = await _call(mcp, name, {**arguments, "lines": [start, 10_000_000]})
        calls += 1
        assert sent <= BUDGET
        text, rng = range_of(answer)
        pieces.append(text)
        if rng.get("truncation_reason") != "byte_budget":
            assert rng["end"] == rng["total_lines"]
            return pieces, calls
        assert rng["truncated"] is True and rng["start"] == start <= rng["end"] < rng["total_lines"]
        assert text.count("\n") == rng["end"] - start  # השורות שחזרו הן בדיוק start..end
        start = rng["end"] + 1


@pytest.mark.parametrize("stored_as", ["code", "content"], ids=["snippet", "large_file"])
async def test_a_range_over_the_budget_ends_at_a_line_and_continuing_rebuilds_the_file(
    monkeypatch, net_log, stored_as,
):
    """הסבב המלא: טווח שנחתך, ואז המשך מ-``end + 1``, ואז חיבור — זהה לקובץ, בלי כפל ובלי חסר.

    ``range.end`` הוא השורה האחרונה שחזרה בפועל, ``truncation_reason: "byte_budget"`` אומר
    שיש עוד. בקובץ גדול (``LargeFile``) התוכן יושב גם ב-``code`` וגם ב-``content``, ושניהם
    נחתכים יחד ונספרים. על main: ``lines=[1, ∞]`` על הקובץ הזה — 548,037 בתים.

    מוטציות שמפילות: ``end`` שמדווח את מה שביקשו ולא את מה שחזר; חיתוך באמצע שורה; ספירה
    של ``code`` בלבד בקובץ גדול.
    """
    mcp, _ = _saved(monkeypatch, _Dbm(**{stored_as: _BIG_HEBREW}))

    def range_of(answer):
        doc = answer["file"]
        if stored_as == "content":
            assert doc["content"] == doc["code"]
        return doc["code"], doc["range"]

    pieces, calls = await _read_in_ranges(mcp, "codekeeper_get_file", {"file_name": "big.txt"}, range_of)
    assert calls >= 2 and "\n".join(pieces) == _BIG_HEBREW
    _assert_net_silent(net_log)


async def test_a_single_line_larger_than_the_budget_is_refused_and_named(monkeypatch, net_log):
    mcp, _ = _saved(monkeypatch, _Dbm(code="קצר\n" + "ש" * 200_000 + "\nקצר"))
    answer, sent = await _call(mcp, "codekeeper_get_file", {"file_name": "big.txt", "lines": [2, 3]})
    assert answer["error"] == "answer_too_large" and answer["bytes"] > answer["max"] == BUDGET
    assert "Line 2" in answer["hint"] and "range" not in answer["file"] and sent <= BUDGET
    answer, _ = await _call(mcp, "codekeeper_get_file", {"file_name": "big.txt", "lines": [1, 1]})
    assert answer["file"]["code"] == "קצר" and "truncation_reason" not in answer["file"]["range"]
    _assert_net_silent(net_log)


async def test_a_query_answer_is_measured_as_sent_and_says_why_it_stopped(monkeypatch, net_log):
    """#3474: המתכון מהאישו — על main 259,168 בתים, כי נמדדו רק רשומות דחוסות.

    עכשיו המעטפת שמורה והרשומות נמדדות כפי שהן יושבות ברשימה: התשובה נכנסת, ו-
    ``truncation_reason`` אומר שהתקציב עצר. מוטציה שמפילה: לחזור ל-``json.dumps`` הדחוס.
    """
    code = "\n".join(["א" * 230 + " needle"] * 400)
    mcp, _ = _saved(monkeypatch, _Dbm(code=code, description="תיאור " * 40))
    answer, sent = await _call(mcp, "codekeeper_get_file",
                               {"file_name": "big.txt", "query": "needle", "context_lines": 10, "max_results": 100})
    assert sent <= BUDGET
    assert answer["truncated"] is True and answer["truncation_reason"] == "byte_budget"
    assert 0 < answer["count"] < 100 == min(answer["total"], 100)
    _assert_net_silent(net_log)


async def test_a_query_near_the_budget_never_passes_it(monkeypatch, net_log):
    """סריקה סביב הסף: תיאור שגדל בצעדים קטנים מזיז את המעטפת, והתשובה אף פעם אינה עוברת.

    זה המקום שבו מדידה שמתעלמת מהמעטפת נכשלת — היא נכונה רחוק מהסף ושגויה לידו. הרשומות
    כאן הן של המתכון של #3474, כך שהמדידה הדחוסה של main מכניסה אותן כמעט עד התקציב,
    והתשובה שנשלחת עוברת אותו בכל אחד מהצעדים.
    """
    code = "\n".join(["א" * 230 + " needle"] * 400)
    for extra in range(0, 4_000, 250):
        mcp, _ = _saved(monkeypatch, _Dbm(code=code, description="ת" * extra))
        answer, sent = await _call(mcp, "codekeeper_get_file",
                                   {"file_name": "big.txt", "query": "needle", "context_lines": 10, "max_results": 100})
        assert sent <= BUDGET, extra
        assert answer["count"] > 0
    _assert_net_silent(net_log)


async def test_a_query_cut_by_the_count_says_max_results(monkeypatch, net_log):
    mcp, _ = _saved(monkeypatch, _Dbm(code="hit\n" * 20))
    answer, _ = await _call(mcp, "codekeeper_get_file", {"file_name": "big.txt", "query": "hit", "max_results": 5})
    assert answer["count"] == 5 and answer["truncation_reason"] == handlers.MAX_RESULTS_REASON
    answer, _ = await _call(mcp, "codekeeper_get_file", {"file_name": "big.txt", "query": "hit", "max_results": 50})
    assert answer["truncated"] is False and "truncation_reason" not in answer
    _assert_net_silent(net_log)


async def test_a_refusal_drops_a_huge_description_whole_and_says_how_big_it_was(monkeypatch, net_log):
    """#3489 בצד הקריאה: תיאור של 200,000 תווים עבריים. על main הסירוב עצמו יצא 400,523 בתים.

    עכשיו התיאור יורד מהסירוב שלם, ו-``description_bytes`` אומר כמה הוא היה — בכל צורה
    של הכלי: מפה, ``query``, קריאה מלאה וטווח. מוטציה שמפילה: להשאיר את התיאור.
    """
    description = "ת" * 200_000
    mcp, _ = _saved(monkeypatch, _Dbm(code="# a\n\ntext\n\n## b\n\nmore\n", name="big.md",
                                      language="markdown", description=description))
    for arguments in ({"toc": True}, {"query": "text"}, {}, {"lines": [1, 3]}):
        answer, sent = await _call(mcp, "codekeeper_get_file", {"file_name": "big.md", **arguments})
        assert answer["error"] == "answer_too_large" and sent <= BUDGET, arguments
        assert "description" not in answer["file"], arguments
        assert answer["file"]["description_bytes"] == len(description.encode("utf-8")), arguments
    _assert_net_silent(net_log)


# --- codekeeper_get_repo_file / codekeeper_read_batch -----------------------


#: בין תקציב התשובה (256,000) לתקרת המראה על קריאה מלאה (500KB): גדול מדי לתשובה אחת,
#: וקטן מספיק כדי שהמראה תגיש אותו ולא תחזיר ``too_large``.
_BIG_MD = "# ראשי\n\n" + "\n".join(f"## סעיף {i}\n\n" + _HEBREW_LINE * 10 for i in range(120))


@requires_git
async def test_a_whole_repo_file_over_the_budget_is_refused_with_its_ways_in(tmp_path, monkeypatch, net_log):
    """קריאה מלאה של קובץ במראה: על main ``docs/mcp-server.rst`` יצא 299,038 בתים.

    הסירוב נושא ``file`` (עם ``lines``), ו-``hint`` ל-``lines``/``outline``. קובץ שכלי
    הסעיפים מגיש — גם ``read_with``/``read_with_arguments``, והארגומנטים עובדים.
    """
    code = "\n".join(f"def f{i}():\n    return '{_HEBREW_LINE}'" for i in range(1500))
    mcp, _ = _repos(tmp_path, monkeypatch, {_MD_REPO: {"big.md": _BIG_MD}, _CODE_REPO: {"app.py": code}})

    answer, sent = await _call(mcp, "codekeeper_get_repo_file", {"repo": _CODE_REPO, "path": "app.py"})
    assert answer["error"] == "answer_too_large" and answer["bytes"] > answer["max"] == BUDGET
    assert sent <= BUDGET and answer["file"]["lines"] == 3000 and "outline=true" in answer["hint"]
    assert "read_with" not in answer

    answer, sent = await _call(mcp, "codekeeper_get_repo_file", {"repo": _MD_REPO, "path": "big.md"})
    assert answer["error"] == "answer_too_large" and sent <= BUDGET
    assert answer["read_with"] == docs_handlers.SECTION_TOOL_NAME
    toc, _ = await _call(mcp, answer["read_with"], answer["read_with_arguments"])
    assert toc["ok"] is True and toc["toc"]
    _assert_net_silent(net_log)


@requires_git
async def test_a_repo_range_over_the_budget_ends_at_a_line_and_continuing_rebuilds_the_file(
    tmp_path, monkeypatch, net_log,
):
    """אותו סבב מלא כמו בקובץ שמור. על main ``webapp/app.py`` עם ``lines`` מלא — 932,955 בתים."""
    mcp, _ = _repos(tmp_path, monkeypatch, {_CODE_REPO: {"big.txt": _BIG_HEBREW}})
    pieces, calls = await _read_in_ranges(
        mcp, "codekeeper_get_repo_file", {"repo": _CODE_REPO, "path": "big.txt"},
        lambda answer: (answer["content"], answer["range"]))
    assert calls >= 2 and "\n".join(pieces) == _BIG_HEBREW
    _assert_net_silent(net_log)


@requires_git
async def test_a_batch_file_item_answers_like_the_single_tool_and_its_section_item_still_parses(
    tmp_path, monkeypatch, net_log,
):
    """פריט קובץ ופריט סעיף של אותו קובץ גדול: הקריאה משותפת, והתקציב חל רק על פריט הקובץ.

    פריט הקובץ זהה בית-בית לכלי הבודד (``answer_too_large`` עם ההפניה שלו), ופריט הסעיף
    מפרסר את הקובץ כולו ועונה. מוטציה שמפילה: להחיל את התקציב על הקריאה המשותפת
    (``RepoBackend.get_file``) — אז פריט הסעיף מקבל סירוב במקום מסמך.
    """
    mcp, _ = _repos(tmp_path, monkeypatch, {_MD_REPO: {"big.md": _BIG_MD}})
    single, _ = await _call(mcp, "codekeeper_get_repo_file", {"repo": _MD_REPO, "path": "big.md"})
    batch, sent = await _call(mcp, read_batch.TOOL_NAME, {"items": [
        {"kind": "file", "repo": _MD_REPO, "path": "big.md"},
        {"kind": "section", "repo": _MD_REPO, "path": "big.md", "section": "סעיף 7"},
    ]})
    assert sent <= BUDGET and batch["count"] == 2
    assert batch["items"][0]["result"] == single and single["error"] == "answer_too_large"
    section = batch["items"][1]["result"]
    assert section["ok"] is True and section["section"] == "סעיף 7"
    _assert_net_silent(net_log)


_LONG_CSS = "\n".join(
    ", ".join(f".component-{i}-variant-{j} .inner-element-name" for j in range(10)) + " { color: red; }"
    for i in range(1200)
) + "\n"


@requires_git
async def test_an_outline_page_is_measured_whole_as_sent(tmp_path, monkeypatch, net_log):
    """על main עמוד של 500 סימבולים נמדד 247,684 בתים (החלון, דחוס) ויצא 261,992.

    עכשיו התשובה כולה נמדדת: העמוד הזה הוא ``page_too_large``, עם ``bytes`` של מה שהיה
    נשלח, ועמוד קטן ממנו נכנס. מוטציה שמפילה: לחזור למדידת החלון הדחוס.
    """
    mcp, _ = _repos(tmp_path, monkeypatch, {_CODE_REPO: {"long.css": _LONG_CSS}})
    answer, _ = await _call(mcp, "codekeeper_get_repo_file",
                            {"repo": _CODE_REPO, "path": "long.css", "outline": True, "per_page": 500})
    assert answer == {"ok": False, "error": "page_too_large", "bytes": answer["bytes"], "max": BUDGET,
                      "per_page": 500}
    assert answer["bytes"] > BUDGET
    answer, sent = await _call(mcp, "codekeeper_get_repo_file",
                               {"repo": _CODE_REPO, "path": "long.css", "outline": True, "per_page": 200})
    assert answer["status"] == "outline" and sent <= BUDGET
    _assert_net_silent(net_log)


# --- codekeeper_list_repo_tree ---------------------------------------------


class _TreeMirror:
    def __init__(self, files: list[str]) -> None:
        self.files = files

    def resolve_commit(self, repo: str, ref: str) -> dict[str, Any]:
        return {"ok": True, "commit": "c0ffee"}

    def list_all_files(self, repo: str, ref: str) -> list[str]:
        return list(self.files)

    def list_all_files_with_sizes(self, repo: str, ref: str) -> list[dict[str, Any]]:
        return [{"path": f, "size": 123_456} for f in self.files]


async def test_a_tree_page_over_the_budget_is_refused_whole_through_the_tool(monkeypatch, net_log):
    """#3481 דרך הכלי: 1,000 נתיבים ארוכים עם ``include_stats`` — ``page_too_large``, ועמודים
    קטנים מחזירים את כולם, כל אחד בתוך התקציב. על main העמוד נחתך באמצע והמשכו אבד.
    """
    files = [f"src/{'עמוק/' * 30}file_{i:04d}.py" for i in range(1000)]
    monkeypatch.setenv("ENVIRONMENT", "production")
    from config import config as _cfg

    monkeypatch.setattr(_cfg, "ADMIN_USER_IDS", [_USER], raising=False)
    db = _Db({"repo_metadata": _Collection([{"repo_name": "r", "default_branch": "main"}]),
              "sync_jobs": _Collection([]), "repo_files": _Collection([])})
    backend = RepoBackend(db=db, mirror=_TreeMirror(files))
    mcp = srv.build_mcp(object(), repo_backend=backend, rate_limit_per_minute=0)

    answer, _ = await _call(mcp, "codekeeper_list_repo_tree", {"repo": "r", "per_page": 1000, "include_stats": True})
    assert answer["error"] == "page_too_large" and answer["bytes"] > answer["max"] == BUDGET
    seen: list[str] = []
    for page in range(1, 5):
        answer, sent = await _call(mcp, "codekeeper_list_repo_tree",
                                   {"repo": "r", "per_page": 250, "page": page, "include_stats": True})
        assert sent <= BUDGET and answer["truncated"] is False
        seen += answer["paths"]
    assert seen == files
    _assert_net_silent(net_log)


# --- codekeeper_search_repo -------------------------------------------------


class _QuoteSearch:
    """מנוע חיפוש שמחזיר שורות מלאות מירכאות ולוכסנים — הקלט שבו ``str()`` הכי רחוק מ-JSON.

    על main עמוד כזה נמדד 248,234 בתים ויצא 374,931.
    """

    def search(self, repo: str, query: str, **kwargs: Any) -> dict[str, Any]:
        line = '"\\"' * 160
        rows = [{"path": f"dir/file_{i}.json", "line": i + 1, "content": line,
                 "context_before": [line] * kwargs["context_lines"],
                 "context_after": [line] * kwargs["context_lines"]}
                for i in range(kwargs["max_results"])]
        return {"results": rows, "total": 5000, "truncated": True, "truncation_reason": "max_results"}


async def test_a_search_page_is_measured_as_sent(monkeypatch, net_log):
    monkeypatch.setenv("ENVIRONMENT", "production")
    from config import config as _cfg

    monkeypatch.setattr(_cfg, "ADMIN_USER_IDS", [_USER], raising=False)
    db = _Db({"repo_metadata": _Collection([{"repo_name": "r", "default_branch": "main"}]),
              "sync_jobs": _Collection([])})
    backend = RepoBackend(db=db, mirror=_TreeMirror([]), search_service=_QuoteSearch())
    mcp = srv.build_mcp(object(), repo_backend=backend, rate_limit_per_minute=0)

    answer, sent = await _call(mcp, "codekeeper_search_repo",
                               {"repo": "r", "query": "q\"", "max_results": 100, "context_lines": 10})
    assert sent <= BUDGET and 0 < answer["count"] < 100 and answer["truncated"] is True
    # המנוע נעצר ב-``max_results``, אבל מה שקיצר את העמוד הוא התקציב — וזו הסיבה שחוזרת,
    # כי ``max_results`` היה שולח את הקורא להגדיל תקרה שלא הייתה עוזרת.
    assert answer["truncation_reason"] == "byte_budget"
    _assert_net_silent(net_log)


# --- codekeeper_list_notes / codekeeper_list_board_notes --------------------


class _Cursor(list):
    def sort(self, *args: Any, **kwargs: Any) -> "_Cursor":
        return self

    def limit(self, n: int) -> "_Cursor":
        return _Cursor(self[:n])


class _Notes:
    """אוסף פתקים: ``find`` למסלול המלא ו-``aggregate`` לרזה. סופר כמה שורות נמשכו מהסמן."""

    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self.docs = docs
        self.pulled = 0

    def _pull(self, rows):
        for row in rows:
            self.pulled += 1
            yield row

    def find(self, query: dict[str, Any], *args: Any, **kwargs: Any):
        cursor = _Cursor(self.docs)
        original_limit = cursor.limit
        cursor.limit = lambda n: self._pull(original_limit(n))  # type: ignore[method-assign]
        return cursor

    def aggregate(self, pipeline: list[dict[str, Any]]):
        return self._pull({"_id": d["_id"], "title": d["title"], "color": d["color"],
                           "updated_at": d["updated_at"], "created_at": d["created_at"],
                           "content_bytes": len(d["content"].encode("utf-8"))} for d in self.docs)


def _notes(count: int, chars: int, *, title: str = "") -> list[dict[str, Any]]:
    body = ("פתק עם תוכן עברי ארוך " * (chars // 22 + 1))[:chars]
    when = dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc)
    return [{"_id": f"{i:024x}", "user_id": _USER, "content": body, "title": title or f"n{i}",
             "color": "yellow", "created_at": when, "updated_at": when} for i in range(count)]


def _board(monkeypatch: Any, docs: list[dict[str, Any]]) -> tuple[Any, _Notes]:
    mcp, backend = _saved(monkeypatch, _Dbm(code=""))
    notes = _Notes(docs)
    monkeypatch.setattr(backend, "_notes_coll", lambda: notes)
    monkeypatch.setattr(backend, "_owned_board", lambda user_id, board_id: {"_id": "b" * 24, "name": "לוח"})
    monkeypatch.setattr(backend, "_canonical_board_id", lambda board: "b" * 24)
    monkeypatch.setattr(backend, "_related_file_ids", lambda user_id, file_name: [])
    return mcp, notes


@pytest.mark.parametrize(("tool", "arguments"), [
    ("codekeeper_list_board_notes", {"board_id": "b" * 24}),
    ("codekeeper_list_notes", {"file_name": "a.md"}),
])
async def test_a_full_note_listing_over_the_budget_is_refused_early_and_the_lean_one_fits(
    monkeypatch, net_log, tool, arguments,
):
    """200 פתקים של 20,000 תווים: על main 7,173,206 בתים. עכשיו — סירוב, והקריאה נעצרת.

    הסירוב מפנה ל-``include_content=false``, והרשימה הרזה של אותם פתקים נכנסת. הקריאה
    מהסמן נעצרת כשהתקציב עבר, ולכן נמשכים פחות פתקים ממה שיש. מוטציות שמפילות: חיתוך
    הרשימה במקום סירוב; קריאת כל הפתקים לפני המדידה.
    """
    mcp, notes = _board(monkeypatch, _notes(200, 20_000))
    answer, sent = await _call(mcp, tool, arguments)
    assert answer["error"] == "answer_too_large" and answer["bytes"] > answer["max"] == BUDGET
    assert sent <= BUDGET and "include_content=false" in answer["hint"]
    assert notes.pulled < 200

    answer, sent = await _call(mcp, tool, {**arguments, "include_content": False})
    assert answer["ok"] is True and answer["count"] == 200 and sent <= BUDGET
    _assert_net_silent(net_log)


async def test_a_lean_listing_past_the_soft_cap_is_refused_with_the_search_as_the_way(monkeypatch, net_log):
    """רק כשהתקרה הרכה נפרצה: 500 פתקים עם כותרת של 80 אימוג'י — על main 262,616 בתים ברזה."""
    mcp, _ = _board(monkeypatch, _notes(500, 10, title="😀" * 80))
    answer, sent = await _call(mcp, "codekeeper_list_board_notes", {"board_id": "b" * 24, "include_content": False})
    assert answer["error"] == "answer_too_large" and sent <= BUDGET
    assert "codekeeper_search_notes" in answer["hint"]
    _assert_net_silent(net_log)


async def test_a_full_listing_that_fits_is_the_same_answer_as_before(monkeypatch, net_log):
    mcp, _ = _board(monkeypatch, _notes(18, 3_600))
    answer, sent = await _call(mcp, "codekeeper_list_board_notes", {"board_id": "b" * 24})
    assert set(answer) == {"ok", "board_id", "board_name", "count", "notes"} and answer["count"] == 18
    assert sent <= BUDGET
    _assert_net_silent(net_log)


# --- codekeeper_docs_get_section --------------------------------------------


@requires_git
async def test_the_largest_section_page_of_wide_characters_fits(tmp_path, monkeypatch, net_log):
    """``docs_get_section`` כבר מתאים את העמוד (``_fit_page``) — וכאן זה נבדק דרך הכלי, על הקלט
    הגרוע: סעיף ענק של CJK ותווי בקרה עם ``max_chars`` בתקרה, ומפת כותרות של מאות כותרות
    ארוכות. השינוי כאן העביר את הכלי לייבא את המדידה והתקציב מ-``answer_size``.
    """
    wide = "# ראשי\n\n## ענק\n\n" + ("汉\u0001" * 60_000) + "\n"
    headings = "# ראשי\n\n" + "\n".join(f"## {'כותרת ארוכה ' * 20}{i}\n\nגוף.\n" for i in range(600))
    mcp, _ = _repos(tmp_path, monkeypatch, {_MD_REPO: {"wide.md": wide, "headings.md": headings}})

    answer, sent = await _call(mcp, docs_handlers.SECTION_TOOL_NAME,
                               {"repo": _MD_REPO, "path": "wide.md", "section": "ענק", "max_chars": 100_000})
    assert sent <= BUDGET and answer["truncated"] is True
    answer, sent = await _call(mcp, docs_handlers.SECTION_TOOL_NAME, {"repo": _MD_REPO, "path": "headings.md"})
    assert sent <= BUDGET and answer["toc"]
    _assert_net_silent(net_log)


# ===========================================================================
# 4. אוצר מילים אחד
# ===========================================================================


def test_one_word_for_each_size_outcome():
    """הקודים והסיבות של תשובה גדולה — מילה אחת כל אחד, מבעלים אחד (``answer_size``)."""
    assert docs_handlers.ANSWER_TOO_LARGE is answer_size.ANSWER_TOO_LARGE == "answer_too_large"
    assert repo_handlers.ANSWER_TOO_LARGE is answer_size.ANSWER_TOO_LARGE
    assert docs_handlers._BYTE_BUDGET_REASON is answer_size.BYTE_BUDGET_REASON == "byte_budget"
    assert read_batch.UNREAD_BYTE_BUDGET is answer_size.BYTE_BUDGET_REASON
    assert repo_handlers.OUTPUT_BYTE_BUDGET is answer_size.OUTPUT_BYTE_BUDGET
    assert answer_size.DECLARED_MAX_RESULT_CHARS == answer_size.OUTPUT_BYTE_BUDGET


def test_the_leaf_imports_nothing_from_the_package():
    """``answer_size`` הוא עלה: מודול בחבילה שמייבא ממנו לא יכול ליצור מעגל דרכו."""
    source = Path(answer_size.__file__).read_text(encoding="utf-8")
    assert "from ." not in source and "import mcp_server" not in source


def test_the_numbers_in_the_answer_size_section_are_the_code_numbers():
    """המספרים בסעיף :ref:`mcp-answer-size` נגזרים מהקבועים, ולא מוקלדים לצידם.

    קובץ RST אינו יכול לגזור דבר (``prose-restates-code-fact``), ולכן הטסט מחשב כל מספר
    מהקבוע ומשווה למה שכתוב: החשבון של ``codekeeper_list_repo_notes`` — שעליו נשענת
    ההחלטה לא להצהיר — התקציב, ותקרת הלקוח. מי שמשנה קבוע בלי התיעוד, או להפך, מפיל אותו.
    """
    import re

    from sticky_notes_target import MAX_NOTE_CHARS, MAX_NOTES_PER_REPO_FILE

    page = (Path(__file__).resolve().parent.parent / "docs" / "mcp-server.rst").read_text(encoding="utf-8")
    start = page.index(".. _mcp-answer-size:")
    section = page[start:page.index(".. _mcp-request-limits:", start)]

    notes, chars, total = re.search(r"הם (\d+) × ([\d,]+) = ([\d,]+) תווים", section).groups()
    assert int(notes) == MAX_NOTES_PER_REPO_FILE
    assert int(chars.replace(",", "")) == MAX_NOTE_CHARS
    assert int(total.replace(",", "")) == MAX_NOTES_PER_REPO_FILE * MAX_NOTE_CHARS > BUDGET
    assert f"``OUTPUT_BYTE_BUDGET`` ({BUDGET:,})" in section
    assert f"מעל {answer_size.CLIENT_CEILING_CHARS:,} (``CLIENT_CEILING_CHARS``)" in section
    assert "עד 500,000 **תווים**" in section and answer_size.CLIENT_CEILING_CHARS == 500_000
    for name in DECLARING:
        assert f"``{name}``" in section, name
