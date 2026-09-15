"""Every tool body runs on a worker thread, not on the event loop (#3379).

The bug this guards against is not a slow request — it is a **shared outage**.
``mcp 1.28.1`` dispatches a sync tool as ``return fn(**arguments_parsed_dict)``
straight from ``func_metadata.call_fn_with_arg_validation``, so one long body
froze every other session on the process until it finished. ``codekeeper_docs_get_section``
is a public tool, which is what turns that from an admin footgun into something
any authenticated user can trigger.

Each test below was run against the code *without* ``_offload_to_thread`` and
fails there — the guard, the responsiveness test and the off-loop test all fail;
the schema and auth tests are the control group that must pass either way.
"""

import asyncio
import threading
import types

import pytest

pytest.importorskip("mcp")
pytest.importorskip("starlette")

from mcp.server.auth.middleware.auth_context import (  # noqa: E402
    auth_context_var,
    get_access_token,
)
from mcp.server.auth.provider import AccessToken  # noqa: E402
from mcp.server.fastmcp import Context, FastMCP  # noqa: E402
from mcp.server.lowlevel.server import request_ctx  # noqa: E402
from mcp.shared.context import RequestContext  # noqa: E402

from mcp_server.server import AdminAwareFastMCP, _offload_to_thread, build_mcp  # noqa: E402


class _FakeBackend:
    """Only needs to exist — no tool body is executed by the registration tests."""

    def __getattr__(self, _name):
        return lambda *a, **k: {}


def _registered(mcp):
    return list(mcp._tool_manager._tools.values())


@pytest.fixture
def request_context():
    """A real request + auth context, the way ``FastMCP.call_tool`` sees one."""
    request = types.SimpleNamespace(
        state=types.SimpleNamespace(user_id=4242, scopes=["write"])
    )
    rc = RequestContext(
        request_id=1, meta=None, session=None, lifespan_context=None, request=request
    )
    token = AccessToken(
        token="t", client_id="user-42", scopes=["write"], expires_at=None
    )
    rc_reset = request_ctx.set(rc)
    auth_reset = auth_context_var.set(types.SimpleNamespace(access_token=token))
    try:
        yield
    finally:
        auth_context_var.reset(auth_reset)
        request_ctx.reset(rc_reset)


# ── the guard: no tool may be registered as a sync function ──────────────────


def test_every_registered_tool_is_a_coroutine_function():
    """The rule holds for all 29 tools, not just the ones someone remembered.

    This is the test that makes ``add_tool`` the single definition: a tool added
    tomorrow as a plain ``def`` is wrapped on the way in, and a refactor that
    bypasses the wrapper fails here instead of quietly returning to the loop.
    """
    mcp = build_mcp(_FakeBackend(), repo_backend=_FakeBackend())
    tools = _registered(mcp)
    assert tools, "no tools registered — the fixture is wrong, not the code"

    sync_tools = [t.name for t in tools if not asyncio.iscoroutinefunction(t.fn)]
    assert sync_tools == [], f"these tool bodies would run on the event loop: {sync_tools}"


def test_the_guard_can_fail(monkeypatch):
    """The guard above is only evidence if it is able to fail — prove it.

    Without this, a refactor that turned ``_offload_to_thread`` into the identity
    function would leave the suite green.
    """
    monkeypatch.setattr(
        "mcp_server.server._offload_to_thread", lambda fn, **_kw: fn
    )
    mcp = build_mcp(_FakeBackend(), repo_backend=_FakeBackend())
    sync_tools = [t.name for t in _registered(mcp) if not asyncio.iscoroutinefunction(t.fn)]
    assert sync_tools, "identity wrapper left every tool async — the guard proves nothing"


# ── behaviour: the body really leaves the loop, and the loop keeps running ───


async def test_sync_tool_body_runs_off_the_event_loop(request_context):
    mcp = AdminAwareFastMCP("t")
    seen = {}
    loop_thread = threading.get_ident()

    def probe(ctx: Context) -> dict:
        seen["thread"] = threading.get_ident()
        return {"ok": True}

    mcp.add_tool(probe, name="probe")
    await mcp.call_tool("probe", {})

    assert seen["thread"] != loop_thread


async def test_event_loop_keeps_running_while_a_tool_blocks(request_context):
    """The actual promise: a blocking body must not stop other work.

    A counter coroutine ticks while the tool sleeps in ``time.sleep``. On the
    code before this change the counter cannot advance at all, because the body
    holds the only thread the loop has.
    """
    import time

    mcp = AdminAwareFastMCP("t")
    started = threading.Event()

    def slow(ctx: Context) -> dict:
        started.set()
        time.sleep(0.25)
        return {"ok": True}

    mcp.add_tool(slow, name="slow")

    ticks = 0

    async def ticker():
        nonlocal ticks
        while not stop.is_set():
            ticks += 1
            await asyncio.sleep(0.01)

    stop = asyncio.Event()
    spinner = asyncio.create_task(ticker())
    await mcp.call_tool("slow", {})
    stop.set()
    await spinner

    assert started.is_set()
    assert ticks > 5, f"the loop only advanced {ticks} times — it was blocked"


# ── control group: what must NOT change ─────────────────────────────────────


def test_input_schema_is_identical_with_and_without_the_wrapper():
    """``functools.wraps`` keeps the signature, so the advertised schema is the same.

    A wrapper that lost ``__wrapped__`` would advertise ``(*args, **kwargs)`` and
    every client would start sending nothing — a silent break, which is exactly
    the class this repo keeps finding.
    """
    def probe(ctx: Context, page: int = 1, name: str | None = None) -> dict:
        """Docstring that must survive."""
        return {}

    plain = FastMCP("plain")
    plain.add_tool(probe, name="probe")
    wrapped = AdminAwareFastMCP("wrapped")
    wrapped.add_tool(probe, name="probe")

    a = plain._tool_manager.get_tool("probe")
    b = wrapped._tool_manager.get_tool("probe")
    assert b.parameters == a.parameters
    assert b.description == a.description
    assert b.context_kwarg == a.context_kwarg


async def test_auth_context_survives_the_thread_hop(request_context):
    """``require_admin`` / ``require_write`` read these two — from the worker thread.

    ``ctx.request_context`` is an instance attribute, but ``get_access_token()``
    is a ``ContextVar``; this asserts that ``asyncio.to_thread`` really does
    carry the context across, rather than trusting the documentation.
    """
    mcp = AdminAwareFastMCP("t")
    seen = {}

    def probe(ctx: Context) -> dict:
        token = get_access_token()
        seen["client_id"] = getattr(token, "client_id", None)
        request = getattr(ctx.request_context, "request", None)
        seen["user_id"] = getattr(getattr(request, "state", None), "user_id", None)
        return {}

    mcp.add_tool(probe, name="probe")
    await mcp.call_tool("probe", {})

    assert seen["client_id"] == "user-42"
    assert seen["user_id"] == 4242


def test_async_tool_is_returned_untouched():
    """An already-async body must not collect a pointless thread hop."""

    async def already_async(ctx: Context) -> dict:
        return {}

    assert _offload_to_thread(already_async) is already_async


# ── write tools stay serialized, readers do not wait ─────────────────────────


def _write_tool_names_from_source():
    """Tool names whose body calls ``require_write`` — read from the AST.

    An independent counter, on purpose: deriving the expected set from the same
    annotations the implementation reads would be circular, and would pass even
    if every annotation were wrong. ``require_write`` is the other, unrelated
    place where "this tool writes" is already stated.
    """
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path("mcp_server/server.py").read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        calls_require_write = any(
            isinstance(c, ast.Call)
            and isinstance(c.func, ast.Name)
            and c.func.id == "require_write"
            for c in ast.walk(node)
        )
        if not calls_require_write:
            continue
        for deco in node.decorator_list:
            if isinstance(deco, ast.Call):
                for kw in deco.keywords:
                    if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                        names.add(kw.value.value)
    return names


def test_exactly_the_write_tools_are_serialized():
    """The lock covers the write tools — no more, and no fewer.

    Fewer would reopen the interleaving this change is meant to preserve; more
    would serialize reads for no reason, and ``codekeeper_docs_get_section`` at
    ~155ms sitting behind a 4.8s save is the whole problem again.
    """
    from mcp_server.server import _declares_write

    serialized = set()

    # Record the flag per tool by re-registering through a recording subclass.
    class _Recorder(AdminAwareFastMCP):
        def add_tool(self, fn, *args, **kwargs):
            if _declares_write(kwargs.get("annotations")):
                serialized.add(kwargs.get("name"))
            return super().add_tool(fn, *args, **kwargs)

    import mcp_server.server as s

    real = s.AdminAwareFastMCP
    s.AdminAwareFastMCP = _Recorder
    try:
        build_mcp(_FakeBackend(), repo_backend=_FakeBackend())
    finally:
        s.AdminAwareFastMCP = real

    assert serialized == _write_tool_names_from_source()


async def test_two_writes_from_one_agent_never_overlap(request_context):
    """Measured, not assumed: the second write waits for the first to finish.

    ``Claude Code`` sends tool calls in parallel, so this is the case the event
    loop used to cover for free and that ``to_thread`` would otherwise reopen.
    """
    import time

    mcp = AdminAwareFastMCP("t")
    inside = 0
    max_inside = 0
    lock = threading.Lock()

    def writer(ctx: Context) -> dict:
        nonlocal inside, max_inside
        with lock:
            inside += 1
            max_inside = max(max_inside, inside)
        time.sleep(0.15)
        with lock:
            inside -= 1
        return {"ok": True}

    mcp.add_tool(writer, name="w", annotations={"readOnlyHint": False})
    await asyncio.gather(mcp.call_tool("w", {}), mcp.call_tool("w", {}))

    assert max_inside == 1, f"{max_inside} writes ran at once — the lock did not hold"


async def test_a_read_does_not_wait_behind_a_long_write(request_context):
    """The reader must overtake the writer, or the lock has cost us the fix.

    Ordering is the assertion, not elapsed time: a wall-clock threshold would
    be the flaky test this repo keeps warning about.
    """
    import time

    mcp = AdminAwareFastMCP("t")
    finished: list[str] = []

    def slow_write(ctx: Context) -> dict:
        time.sleep(0.3)
        finished.append("write")
        return {}

    def quick_read(ctx: Context) -> dict:
        finished.append("read")
        return {}

    mcp.add_tool(slow_write, name="w", annotations={"readOnlyHint": False})
    mcp.add_tool(quick_read, name="r", annotations={"readOnlyHint": True})

    writer = asyncio.create_task(mcp.call_tool("w", {}))
    await asyncio.sleep(0.05)          # let the writer take the lock first
    await mcp.call_tool("r", {})
    await writer

    assert finished == ["read", "write"], f"the read queued behind the write: {finished}"
