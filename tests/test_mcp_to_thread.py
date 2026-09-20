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
from mcp.server.fastmcp.exceptions import ToolError  # noqa: E402
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
    # ``output_schema`` and ``annotations`` are the two fields a wrapper is most
    # likely to drop without anything else noticing, so they are named here
    # rather than left to the three above to imply.
    assert b.output_schema == a.output_schema
    assert b.annotations == a.annotations
    assert b.title == a.title


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

    ``ast.AsyncFunctionDef`` is matched as well as ``ast.FunctionDef``. They are
    separate classes with no inheritance between them, so checking only the
    latter would leave this counter blind to exactly the tool shape that
    ``_offload_to_thread`` now refuses — and blind in the same direction as the
    bug, which is the worst way for a cross-check to fail.
    """
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path("mcp_server/server.py").read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
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


def _routed_to_write_pool(tool):
    """Which branch of ``_offload_to_thread`` actually produced this tool's body.

    ``functools.wraps`` copies ``__name__`` and ``__qualname__`` from the tool,
    so those say nothing about the wrapper. ``__code__.co_name`` belongs to the
    code object and is not copied, so it names the branch that ran — which is
    the point: this reads what ``add_tool`` built, not what the test would build
    if it made the decision itself.
    """
    return tool.fn.__code__.co_name == "_run_on_write_pool"


def test_exactly_the_write_tools_are_routed_to_the_write_pool():
    """The write queue covers the write tools — no more, and no fewer.

    Fewer would reopen the interleaving this change is meant to preserve; more
    would queue reads for no reason, and ``codekeeper_docs_get_section`` at
    ~155ms sitting behind a 4.8s save is the whole problem again.

    This asserts on the wrapper ``build_mcp`` produced for each real tool. An
    earlier version of this test recomputed ``_declares_write`` in its own
    recorder and compared that to the AST set — which held even when the
    registration path was mutated to serialize nothing at all, because both
    sides of the comparison were descriptions and neither was the wiring.
    """
    mcp = build_mcp(_FakeBackend(), repo_backend=_FakeBackend())
    tools = _registered(mcp)
    assert tools, "no tools registered — the fixture is wrong, not the code"

    routed = {t.name for t in tools if _routed_to_write_pool(t)}
    assert routed == _write_tool_names_from_source()


def test_every_read_tool_still_goes_to_the_shared_executor():
    """The other half: a read must not be sitting in the write queue.

    Without this, routing everything to the single write worker would satisfy
    the test above's "no fewer" half and destroy read throughput silently.
    """
    mcp = build_mcp(_FakeBackend(), repo_backend=_FakeBackend())
    reads = [t for t in _registered(mcp) if not _routed_to_write_pool(t)]
    assert reads, "every tool was routed to the write pool"
    assert all(t.fn.__code__.co_name == "_run_on_shared_pool" for t in reads)


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


# ── the write queue: one worker, its own pool, in order ──────────────────────


def _shared_pool_size():
    """How many threads ``asyncio.to_thread`` has to hand out.

    Read rather than assumed: ``min(32, cpu_count + 4)`` is the default
    executor's size, and the tests below need a writer count above it to
    reproduce what the shared pool used to do to readers.
    """
    import os

    return min(32, (os.cpu_count() or 1) + 4)


async def test_write_bodies_run_on_the_write_pool_and_reads_do_not(request_context):
    """The two destinations are real threads, not a naming convention.

    Without this, routing could quietly collapse back to one pool and every
    other test here would still pass — they assert ordering and latency, both of
    which one pool can satisfy on a quiet machine.
    """
    mcp = AdminAwareFastMCP("t")
    seen = {}

    def writer(ctx: Context) -> dict:
        seen["write"] = threading.current_thread().name
        return {}

    def reader(ctx: Context) -> dict:
        seen["read"] = threading.current_thread().name
        return {}

    mcp.add_tool(writer, name="w", annotations={"readOnlyHint": False})
    mcp.add_tool(reader, name="r", annotations={"readOnlyHint": True})
    await mcp.call_tool("w", {})
    await mcp.call_tool("r", {})

    assert seen["write"].startswith("mcp-write"), seen
    assert not seen["read"].startswith("mcp-write"), seen


async def test_a_read_runs_while_the_shared_pool_would_have_been_full(
    request_context,
):
    """The reader must not wait, however many writes are already in flight.

    This is the case the process-wide lock could not cover: a writer blocked on
    it still held one of the shared executor's threads, so once there were more
    writes than that pool had threads, a read had nowhere to run.

    The writes are held on an event rather than on a sleep, so the assertion is
    structural instead of a race the scheduler might win: while every write is
    parked, a read still has to complete. On the old code it could not, because
    the parked writers *were* the shared pool.
    """
    writers = _shared_pool_size() * 2
    mcp = AdminAwareFastMCP("t")
    release = threading.Event()
    first_started = threading.Event()

    def held_write(ctx: Context) -> dict:
        first_started.set()
        release.wait(10.0)
        return {}

    def quick_read(ctx: Context) -> dict:
        return {"ok": True}

    mcp.add_tool(held_write, name="w", annotations={"readOnlyHint": False})
    mcp.add_tool(quick_read, name="r", annotations={"readOnlyHint": True})

    pending = [asyncio.create_task(mcp.call_tool("w", {})) for _ in range(writers)]
    try:
        await asyncio.to_thread(first_started.wait, 5.0)
        await asyncio.wait_for(mcp.call_tool("r", {}), timeout=5.0)
    finally:
        release.set()
        await asyncio.gather(*pending)


async def test_writes_finish_in_the_order_they_were_sent(request_context):
    """Order, not just mutual exclusion.

    A ``threading.Lock`` guarantees no ordering, and above the shared pool's
    size the writes measurably finished out of the order they were sent in — the
    one property the lock was there to restore. A single worker fed by
    ``queue.SimpleQueue`` takes them in submit order, which is what an agent
    sending two dependent writes together actually needs.

    Several rounds, because one round is a coin toss: on the old code a round
    came out ordered often enough that a single round proved nothing. Under the
    fix every round is ordered for a structural reason, so repeating costs
    nothing and removes the luck.
    """
    import time

    writers = _shared_pool_size() * 4
    mcp = AdminAwareFastMCP("t")
    done: list[int] = []

    def writer(ctx: Context, n: int = 0) -> dict:
        time.sleep(0.001)
        done.append(n)
        return {}

    mcp.add_tool(writer, name="w", annotations={"readOnlyHint": False})

    for round_no in range(5):
        done.clear()
        await asyncio.gather(*[mcp.call_tool("w", {"n": i}) for i in range(writers)])
        assert done == sorted(done), f"round {round_no} completed out of order: {done}"


async def test_two_writes_still_never_overlap(request_context):
    """The guarantee the lock used to make, kept by the pool's single worker.

    Measured rather than assumed, and kept as its own test because everything
    else here would still pass if the pool were widened to two workers.
    """
    import time

    mcp = AdminAwareFastMCP("t")
    inside = 0
    max_inside = 0
    guard = threading.Lock()

    def writer(ctx: Context) -> dict:
        nonlocal inside, max_inside
        with guard:
            inside += 1
            max_inside = max(max_inside, inside)
        time.sleep(0.05)
        with guard:
            inside -= 1
        return {}

    mcp.add_tool(writer, name="w", annotations={"readOnlyHint": False})
    await asyncio.gather(*[mcp.call_tool("w", {}) for _ in range(4)])

    assert max_inside == 1, f"{max_inside} writes ran at once"


# ── what counts as a write, and what counts as async ─────────────────────────


def test_annotations_that_do_not_say_read_only_are_treated_as_writes():
    """Fail closed on a missing hint, because the protocol's default says so.

    ``mcp/types.py`` documents ``readOnlyHint`` as "If true, the tool does not
    modify its environment. Default: false", so an absent hint describes a tool
    that may modify. The previous ``hint is False`` read every other shape as
    read-only, which is the same silent loss of serialization #3379 was about —
    only for the next tool someone adds without the key.
    """
    from mcp.types import ToolAnnotations

    from mcp_server.server import _declares_write

    assert _declares_write({"readOnlyHint": False}) is True
    assert _declares_write(ToolAnnotations(readOnlyHint=False)) is True
    # the shapes that used to fall through to "read-only"
    assert _declares_write({"title": "writes, but nobody said so"}) is True
    assert _declares_write({}) is True
    assert _declares_write(None) is True
    assert _declares_write(ToolAnnotations()) is True
    # and the one case that really is a read
    assert _declares_write({"readOnlyHint": True}) is False
    assert _declares_write(ToolAnnotations(readOnlyHint=True)) is False


async def test_a_tool_with_no_annotations_is_actually_queued(request_context):
    """The fail-closed rule reaches the wiring, not just the helper.

    ``_declares_write`` returning True is worth nothing if ``add_tool`` still
    sends the tool to the shared executor.
    """
    mcp = AdminAwareFastMCP("t")
    seen = {}

    def unannotated(ctx: Context) -> dict:
        seen["thread"] = threading.current_thread().name
        return {}

    mcp.add_tool(unannotated, name="u")
    await mcp.call_tool("u", {})

    assert seen["thread"].startswith("mcp-write"), seen


def test_positional_annotations_are_read_too():
    """The SDK takes ``annotations`` positionally; so must we.

    Every registration in ``server.py`` passes it by keyword, so this can only
    ever be caught deliberately: a positional call would otherwise register a
    write tool with no queue, no error, and an identical schema.
    """
    from mcp_server.server import _annotations_of, _declares_write

    # add_tool(fn, name, title, description, annotations) — fn is not in *args
    positional = ("tool-name", None, "a description", {"readOnlyHint": False})
    assert _declares_write(_annotations_of(positional, {})) is True
    assert _annotations_of((), {"annotations": {"readOnlyHint": True}}) == {
        "readOnlyHint": True
    }


def test_our_async_check_agrees_with_the_sdk():
    """Our copy of the SDK's private async test must not drift from it.

    ``_is_async_callable`` is private in ``mcp/server/fastmcp/tools/base.py``, so
    it is reimplemented rather than imported. That is only safe while the two
    agree, and this is what makes an SDK change fail here instead of silently
    splitting the definition of "async" between the dispatcher and the wrapper.
    """
    import functools as ft

    from mcp.server.fastmcp.tools.base import _is_async_callable as sdk_version

    from mcp_server.server import _is_async_callable as ours

    async def async_fn():
        return None

    def sync_fn():
        return None

    class AsyncCallable:
        async def __call__(self):
            return None

    class SyncCallable:
        def __call__(self):
            return None

    shapes = [
        async_fn,
        sync_fn,
        AsyncCallable(),
        SyncCallable(),
        ft.partial(async_fn),
        ft.partial(sync_fn),
        lambda: None,
    ]
    assert [ours(s) for s in shapes] == [sdk_version(s) for s in shapes]
    # and the narrower check really is narrower — otherwise this test is a no-op
    assert ours(AsyncCallable()) and not asyncio.iscoroutinefunction(AsyncCallable())


def test_an_async_write_tool_is_refused_at_registration():
    """An async body cannot be serialized by a worker pool, so it is not accepted.

    Handing the worker a coroutine function makes it return a coroutine object
    immediately: the body would then run on the loop, unqueued and interleaved,
    with the tool still advertised as a write. Refusing at registration is the
    only point where that is visible.
    """
    mcp = AdminAwareFastMCP("t")

    async def async_writer(ctx: Context) -> dict:
        return {}

    async def async_reader(ctx: Context) -> dict:
        return {}

    with pytest.raises(TypeError, match="declares a write but is async"):
        mcp.add_tool(async_writer, name="aw", annotations={"readOnlyHint": False})

    # a read tool may be async — it needs no queue and no thread hop
    mcp.add_tool(async_reader, name="ar", annotations={"readOnlyHint": True})
    assert mcp._tool_manager.get_tool("ar").fn is async_reader


# ── auth, cancellation and the signal ────────────────────────────────────────


async def test_a_write_denied_for_scope_still_surfaces_as_an_error(request_context):
    """``require_write`` must keep working from inside the write pool.

    ``loop.run_in_executor`` does not carry the ``contextvars.Context`` the way
    ``asyncio.to_thread`` does, so the scope gate now depends on an explicit
    ``copy_context()``. Drop that and ``get_access_token()`` returns ``None`` in
    the worker: the gate stops seeing who is asking rather than failing loudly,
    which is the direction that matters for a permission check.
    """
    from mcp_server.auth import require_write

    mcp = AdminAwareFastMCP("t")

    def writer(ctx: Context) -> dict:
        require_write(ctx)
        return {"reached": True}

    mcp.add_tool(writer, name="w", annotations={"readOnlyHint": False})

    # the fixture's token carries "write": the allowed path must still work
    await mcp.call_tool("w", {})

    # and a read-only token must be refused, from the worker thread
    token = AccessToken(token="t", client_id="user-42", scopes=["read"], expires_at=None)
    reset = auth_context_var.set(types.SimpleNamespace(access_token=token))
    request = types.SimpleNamespace(state=types.SimpleNamespace(user_id=4242, scopes=["read"]))
    rc = RequestContext(
        request_id=2, meta=None, session=None, lifespan_context=None, request=request
    )
    rc_reset = request_ctx.set(rc)
    try:
        with pytest.raises(ToolError) as excinfo:
            await mcp.call_tool("w", {})
        assert "insufficient_scope" in str(excinfo.value)
    finally:
        request_ctx.reset(rc_reset)
        auth_context_var.reset(reset)


async def test_a_write_cancelled_while_still_queued_never_runs(request_context):
    """A caller who gives up before their turn does not spend the worker's time.

    ``asyncio`` cancellation reaches the pool: ``_chain_future`` cancels the
    underlying ``concurrent.futures.Future``, and ``_WorkItem.run`` checks
    ``set_running_or_notify_cancel()`` before calling anything. The behaviour is
    documented next to the pool because it is the opposite of the running case
    below, and guessing which one applies is how a retry storm gets built.
    """
    import time

    mcp = AdminAwareFastMCP("t")
    ran: list[str] = []

    def writer(ctx: Context, tag: str = "") -> dict:
        ran.append(tag)
        time.sleep(0.2)
        return {}

    mcp.add_tool(writer, name="w", annotations={"readOnlyHint": False})

    first = asyncio.create_task(mcp.call_tool("w", {"tag": "first"}))
    await asyncio.sleep(0.05)  # first is now on the worker
    queued = asyncio.create_task(mcp.call_tool("w", {"tag": "queued"}))
    await asyncio.sleep(0.02)  # queued is behind it, not started
    queued.cancel()
    await first
    await asyncio.sleep(0.1)  # give it every chance to run anyway

    assert ran == ["first"], f"the cancelled write ran: {ran}"


async def test_a_write_cancelled_after_it_started_runs_to_completion(request_context):
    """Once the body is running, cancelling the request does not stop it.

    A synchronous body cannot be interrupted, on a thread or on the loop. The
    caller stops waiting, the write still happens, and the worker is busy until
    it finishes — which is why a client that times out and retries can queue two
    writes it believes are one.
    """
    import time

    mcp = AdminAwareFastMCP("t")
    started = threading.Event()
    finished = threading.Event()

    def writer(ctx: Context) -> dict:
        started.set()
        time.sleep(0.15)
        finished.set()
        return {}

    mcp.add_tool(writer, name="w", annotations={"readOnlyHint": False})

    task = asyncio.create_task(mcp.call_tool("w", {}))
    await asyncio.to_thread(started.wait, 2.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert await asyncio.to_thread(finished.wait, 2.0), "the running body was cut short"


async def test_the_queue_wait_line_carries_both_numbers(request_context, caplog):
    """Both numbers on one line, because either alone sends the reader elsewhere.

    Total duration blames the write path for a queue problem, and queue depth
    alone says nothing about whether the writes themselves got slower.

    This checks the *content* of the line. Whether it is visible in the running
    service is a different question, and ``caplog`` cannot answer it — it
    attaches its own handler, so it reports a record the service would have
    dropped. ``tests/test_mcp_logging_visible.py`` answers that one, in a fresh
    process, and exists because this test passed while production printed
    nothing.
    """
    import logging as _logging
    import time

    import mcp_server.server as server_module

    mcp = AdminAwareFastMCP("t")

    def writer(ctx: Context) -> dict:
        time.sleep(0.02)
        return {}

    mcp.add_tool(writer, name="w", annotations={"readOnlyHint": False})

    with caplog.at_level(_logging.DEBUG, logger="mcp_server.server"):
        await mcp.call_tool("w", {})
    timing = [r for r in caplog.records if "queued" in r.getMessage()]
    assert timing, "no timing line for a write"
    assert timing[-1].levelno == _logging.INFO, (
        f"the ordinary write timing is at {timing[-1].levelname}; the service runs at "
        "INFO, so anything lower is absent rather than quiet"
    )
    assert "ran" in timing[-1].getMessage()

    caplog.clear()
    # a threshold no wait can stay under, so the WARNING branch is exercised
    # without holding the suite for ten seconds
    original = server_module._SLOW_WRITE_QUEUE_WAIT
    server_module._SLOW_WRITE_QUEUE_WAIT = -1.0
    try:
        with caplog.at_level(_logging.DEBUG, logger="mcp_server.server"):
            await mcp.call_tool("w", {})
    finally:
        server_module._SLOW_WRITE_QUEUE_WAIT = original
    warnings = [r for r in caplog.records if r.levelno == _logging.WARNING]
    assert warnings, "a wait past the threshold produced no warning"
    assert "write queue" in warnings[-1].getMessage()


async def test_a_failing_write_does_not_wedge_the_queue(request_context):
    """One worker means one bad write could, in principle, stop every write.

    It does not: ``_WorkItem.run`` catches ``BaseException`` and puts it on the
    future, so the worker loop survives and takes the next item. Worth its own
    test because the failure it guards against is not a slow write — it is every
    write in the process failing forever, with the pool's single thread gone and
    nothing replacing it.
    """
    mcp = AdminAwareFastMCP("t")
    ran: list[str] = []

    def explodes(ctx: Context) -> dict:
        ran.append("boom")
        raise RuntimeError("write blew up")

    def after(ctx: Context) -> dict:
        ran.append("after")
        return {}

    mcp.add_tool(explodes, name="boom", annotations={"readOnlyHint": False})
    mcp.add_tool(after, name="after", annotations={"readOnlyHint": False})

    # ``ToolError`` and not a bare ``Exception``: the point is that the failure
    # arrives the normal way, so a test that would also pass on a ``TypeError``
    # from a broken wrapper is not checking what it claims to.
    with pytest.raises(ToolError):
        await mcp.call_tool("boom", {})
    await mcp.call_tool("after", {})

    assert ran == ["boom", "after"], ran


async def test_a_write_cancelled_in_the_queue_is_logged_with_its_wait(
    request_context, caplog
):
    """The queue-depth signal has to cover the callers who gave up.

    The timing is measured by the body, and a write cancelled while queued never
    has a body run — so without the handler in the coroutine this is the one
    case that produces no line at all. It is also the case that matters most: a
    queue deep enough that clients time out is exactly what the threshold exists
    to report, and it would otherwise be the quietest thing in the log.
    """
    import logging as _logging
    import time

    mcp = AdminAwareFastMCP("t")
    ran: list[str] = []

    def writer(ctx: Context, tag: str = "") -> dict:
        ran.append(tag)
        time.sleep(0.2)
        return {}

    mcp.add_tool(writer, name="w", annotations={"readOnlyHint": False})

    with caplog.at_level(_logging.DEBUG, logger="mcp_server.server"):
        occupier = asyncio.create_task(mcp.call_tool("w", {"tag": "occupier"}))
        await asyncio.sleep(0.05)
        queued = asyncio.create_task(mcp.call_tool("w", {"tag": "queued"}))
        await asyncio.sleep(0.02)
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
        await occupier

    assert ran == ["occupier"], f"the cancelled write ran: {ran}"
    cancelled_lines = [
        r for r in caplog.records if "cancelled before it ran" in r.getMessage()
    ]
    assert len(cancelled_lines) == 1, [r.getMessage() for r in caplog.records]
    assert "queued" in cancelled_lines[0].getMessage()


async def test_a_write_cancelled_after_it_started_is_not_logged_as_unrun(
    request_context, caplog
):
    """The other half, and the reason the handler asks the future rather than a flag.

    Cancelling a request whose body is already running raises ``CancelledError``
    just the same. Logging on that would print a second line about a write that
    did run, and the line would say the opposite of what happened.
    """
    import logging as _logging
    import time

    mcp = AdminAwareFastMCP("t")
    started = threading.Event()
    finished = threading.Event()

    def writer(ctx: Context) -> dict:
        started.set()
        time.sleep(0.15)
        finished.set()
        return {}

    mcp.add_tool(writer, name="w", annotations={"readOnlyHint": False})

    with caplog.at_level(_logging.DEBUG, logger="mcp_server.server"):
        task = asyncio.create_task(mcp.call_tool("w", {}))
        await asyncio.to_thread(started.wait, 2.0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await asyncio.to_thread(finished.wait, 2.0)
        await asyncio.sleep(0.05)  # let the body's own line land

    messages = [r.getMessage() for r in caplog.records]
    assert not [m for m in messages if "cancelled before it ran" in m], messages
    assert [m for m in messages if "ran" in m], messages


# ── the capacity the dispatch model actually has ─────────────────────────────
#
# The read pool is sized from the container's memory quota (#3391). Each
# condition below has one test, and each test was run against a mutated copy
# of the code that removes exactly that condition and fails there — the
# mutations and their results are recorded in the pull request.

_MiB = 1024 * 1024


def _probe_pool(workers):
    from concurrent.futures import ThreadPoolExecutor

    return ThreadPoolExecutor(max_workers=workers, thread_name_prefix="probe")


def test_startup_names_the_read_pool_the_cpu_quota_and_the_memory_limit(caplog):
    """The concurrency ceiling has to be readable, not inferred — and read off the pool.

    ``os.cpu_count()`` is the machine's count rather than the container's share
    — CPython says so itself — and the pool is no longer sized from it, but it
    stays on the line beside the quota because that gap is the whole story of
    #3391. The memory limit joins them because it is what the pool is sized
    from now.

    The pool handed in is deliberately sized to 3 — a number no formula in the
    module produces: not the floor, not the production result of 10, not the
    cap — while the sizing passed beside it says 10. A record that describes
    state reads the state (``state-record-without-state-change``): a line that
    recomputed its own number, or echoed the sizing instead of the executor,
    prints something other than ``read pool 3 threads``.
    """
    import logging as _logging

    from mcp_server.server import _log_dispatch_capacity, _read_pool_size

    pool = _probe_pool(3)
    try:
        with caplog.at_level(_logging.INFO, logger="mcp_server.server"):
            _log_dispatch_capacity(pool, "cgroup v2: 512.0MiB", _read_pool_size(512 * _MiB))
    finally:
        pool.shutdown(wait=False)

    assert caplog.records, "startup said nothing about capacity"
    line = caplog.records[-1].getMessage()
    for expected in (
        "read pool 3 threads",
        "os.cpu_count=",
        "usable=",
        "write pool 1",
        "cpu quota",
        "memory limit cgroup v2: 512.0MiB",
    ):
        assert expected in line, (expected, line)


def test_the_pool_is_sized_from_the_memory_budget():
    """``(limit - baseline - margin) // cost of one parse`` — and a different limit gives a different answer.

    The expected numbers are worked out by hand from the constants, not read
    back from the function, so a constant ``10`` cannot pass: the production
    plan gives 10, and a plan of 448MiB gives 8 — (448 − 92 − 64) ÷ 35.2.
    """
    from mcp_server.server import _read_pool_size

    production = _read_pool_size(512 * _MiB)
    assert (production.workers, production.source) == (10, "memory"), production
    assert "sized from memory" in production.detail, production.detail

    smaller = _read_pool_size(448 * _MiB)
    assert (smaller.workers, smaller.source) == (8, "memory"), smaller


def test_the_pool_never_drops_below_the_floor():
    """One stuck Mongo read must not stall every other read, whatever the plan.

    On 192MiB the formula allows one thread; the floor holds it at two and
    the line says the floor decided, not the arithmetic.
    """
    from mcp_server.server import _READ_POOL_FLOOR, _read_pool_size

    sizing = _read_pool_size(192 * _MiB)
    assert _READ_POOL_FLOOR == 2
    assert (sizing.workers, sizing.source) == (2, "floor"), sizing
    assert sizing.detail.startswith("floor 2:"), sizing.detail


def test_the_pool_never_rises_above_the_cap():
    """A move to a larger plan must not widen the pool past the width production already ran.

    The cap is 12, the width the service ran before #3391. On 1GiB the formula
    allows 24 and on 4GiB 112; the cap holds both at 12 and the line says the
    cap decided, not the arithmetic.
    """
    from mcp_server.server import _READ_POOL_CAP, _read_pool_size

    assert _READ_POOL_CAP == 12
    for limit in (1024 * _MiB, 4 * 1024 * _MiB):
        sizing = _read_pool_size(limit)
        assert (sizing.workers, sizing.source) == (12, "cap"), sizing
        assert sizing.detail.startswith("cap 12:"), sizing.detail


def test_no_readable_memory_limit_falls_back_to_the_floor_and_not_to_cpu_count():
    """The fallback is the conservative constant, and it is not ``cpu_count + 4``.

    ``cpu_count + 4`` is exactly the number this sizing exists to stop relying
    on, so the test pins the fallback to the floor on any machine — on a
    16-core box the old default would have given 20.
    """
    import os

    from mcp_server.server import _READ_POOL_FLOOR, _read_pool_size

    sizing = _read_pool_size(None)
    assert (sizing.workers, sizing.source) == (_READ_POOL_FLOOR, "fallback"), sizing
    assert sizing.workers != min(32, (os.cpu_count() or 1) + 4) or sizing.workers == 2
    assert "no memory limit readable" in sizing.detail, sizing.detail


def _patch_pathlib(monkeypatch, path_factory):
    """Replace ``pathlib`` **as ``mcp_server.server`` sees it**, not the real module.

    The module reads the cgroup files as ``pathlib.Path(...)`` through its own
    global ``pathlib`` name, so swapping that name for a namespace whose
    ``Path`` is the fake reaches every read and nothing else. Patching
    ``pathlib.Path`` itself would reach pytest too: ``Path.__new__`` picks the
    concrete class with ``cls is Path`` against the module global, so while
    the global is a function every ``Path(...)`` anywhere — including the one
    pytest builds while reporting a *failing* assertion — dies with
    ``AttributeError: type object 'Path' has no attribute '_flavour'``, and
    the failure surfaces as an INTERNALERROR instead of a test failure.
    Measured on a mutation run before this helper existed.
    """
    import types as _types

    import mcp_server.server as server_module

    monkeypatch.setattr(server_module, "pathlib", _types.SimpleNamespace(Path=path_factory))


def _fake_cgroup(monkeypatch, tmp_path, files):
    """Point the cgroup paths the module reads at files under ``tmp_path``.

    ``files`` maps the absolute cgroup path to the text it should contain; a
    path not in the map behaves as a missing file. The CPU-quota tests below
    stage their own inline fake through the same ``_patch_pathlib`` seam; this
    helper is the memory reader's version of that staging.
    """
    import pathlib as _pathlib

    staged = {}
    for name, text in files.items():
        target = tmp_path / name.strip("/").replace("/", "__")
        target.write_text(text)
        staged[name] = target

    def fake_path(p, *a, **k):
        if str(p) in staged:
            return staged[str(p)]
        if str(p).startswith("/sys/fs/cgroup/"):
            return tmp_path / "missing" / str(p).strip("/")
        return _pathlib.Path(p, *a, **k)

    _patch_pathlib(monkeypatch, fake_path)


def test_the_memory_limit_is_read_from_cgroup_v2(tmp_path, monkeypatch):
    """The number has to come from the file, or it is decoration."""
    import mcp_server.server as server_module

    _fake_cgroup(monkeypatch, tmp_path, {"/sys/fs/cgroup/memory.max": "536870912\n"})
    assert server_module._memory_limit() == (536870912, "cgroup v2: 512.0MiB")


def test_a_cgroup_v2_limit_of_max_is_no_limit(tmp_path, monkeypatch):
    """``max`` is the kernel's word for unlimited, and unlimited is not a budget."""
    import mcp_server.server as server_module

    _fake_cgroup(monkeypatch, tmp_path, {"/sys/fs/cgroup/memory.max": "max\n"})
    assert server_module._memory_limit() == (None, "cgroup v2: unlimited")


def test_the_memory_limit_is_read_from_cgroup_v1_when_v2_is_absent(tmp_path, monkeypatch):
    import mcp_server.server as server_module

    _fake_cgroup(
        monkeypatch,
        tmp_path,
        {"/sys/fs/cgroup/memory/memory.limit_in_bytes": "268435456\n"},
    )
    assert server_module._memory_limit() == (268435456, "cgroup v1: 256.0MiB")


def test_the_cgroup_v1_unlimited_sentinel_is_no_limit(tmp_path, monkeypatch):
    """v1 has no word for unlimited: it reads back ``LONG_MAX`` rounded to a page.

    That is the value this repository's own CI image shows, and treating it as
    a four-exbibyte budget would have sized the pool to the cap.
    """
    import mcp_server.server as server_module

    _fake_cgroup(
        monkeypatch,
        tmp_path,
        {"/sys/fs/cgroup/memory/memory.limit_in_bytes": "9223372036854771712\n"},
    )
    assert server_module._memory_limit() == (None, "cgroup v1: unlimited")


def test_an_unreadable_memory_cgroup_is_unavailable_and_does_not_break_startup(monkeypatch):
    """Best effort means best effort — the same rule the CPU reader follows."""
    import mcp_server.server as server_module

    class _Exploding:
        def __init__(self, *_a, **_k):
            pass

        def read_text(self, *_a, **_k):
            raise OSError("no cgroup here")

    _patch_pathlib(monkeypatch, _Exploding)
    assert server_module._memory_limit() == (None, "unavailable")


async def test_the_read_pool_really_replaces_the_default_executor_at_startup():
    """Proof that the executor was swapped at run time, not that a function was called.

    Through the real seam: ``build_app`` wraps the Starlette lifespan, and
    entering it is exactly what uvicorn does at startup. Before the lifespan a
    ``to_thread`` call lands on CPython's own default executor (the control);
    inside it the same call lands on a thread the installed pool named, and
    the loop's default executor is that pool, sized by the same reader and
    formula the capacity line reports.
    """
    from concurrent.futures import ThreadPoolExecutor

    from mcp_server.server import _memory_limit, _read_pool_size, build_app

    app = build_app(_FakeBackend(), repo_backend=_FakeBackend())

    before = await asyncio.to_thread(threading.current_thread)
    assert not before.name.startswith("mcp-read"), before.name

    async with app.router.lifespan_context(app):
        inside = await asyncio.to_thread(threading.current_thread)
        assert inside.name.startswith("mcp-read"), inside.name
        pool = asyncio.get_running_loop()._default_executor
        assert isinstance(pool, ThreadPoolExecutor)
        assert pool._max_workers == _read_pool_size(_memory_limit()[0]).workers


async def test_the_lifespan_sizes_from_the_reader_and_reports_a_fallback(monkeypatch, caplog):
    """The wrapper uses the reader, and a fallback is said out loud.

    A worse path nobody reports is the one that stays
    (``silent-fallback-to-worse-path``): with no readable limit the pool is
    the floor **and** a warning names it; with a readable limit the pool is
    the formula's and no warning is logged.
    """
    import contextlib
    import logging as _logging
    import types as _types

    import mcp_server.server as server_module

    @contextlib.asynccontextmanager
    async def _original(_app):
        yield {"state": 1}

    def _app():
        return _types.SimpleNamespace(router=_types.SimpleNamespace(lifespan_context=_original))

    app = _app()
    monkeypatch.setattr(server_module, "_memory_limit", lambda: (None, "unavailable"))
    server_module.attach_read_pool(app)
    with caplog.at_level(_logging.INFO, logger="mcp_server.server"):
        async with app.router.lifespan_context(app) as state:
            assert state == {"state": 1}
            assert asyncio.get_running_loop()._default_executor._max_workers == 2
    warnings = [r.getMessage() for r in caplog.records if r.levelno == _logging.WARNING]
    assert any("fell back to 2 threads" in m for m in warnings), warnings

    caplog.clear()
    app = _app()
    monkeypatch.setattr(server_module, "_memory_limit", lambda: (512 * _MiB, "cgroup v2: 512.0MiB"))
    server_module.attach_read_pool(app)
    with caplog.at_level(_logging.INFO, logger="mcp_server.server"):
        async with app.router.lifespan_context(app):
            assert asyncio.get_running_loop()._default_executor._max_workers == 10
    assert not [r for r in caplog.records if r.levelno == _logging.WARNING], caplog.records


def test_an_app_without_a_lifespan_keeps_its_executor_and_says_so(caplog):
    """No seam, no swap — and the line says the pool is then CPython's default."""
    import logging as _logging
    import types as _types

    from mcp_server.server import attach_read_pool

    app = _types.SimpleNamespace(router=_types.SimpleNamespace())
    with caplog.at_level(_logging.WARNING, logger="mcp_server.server"):
        attach_read_pool(app)

    assert not hasattr(app.router, "lifespan_context")
    assert any("read pool was not installed" in r.getMessage() for r in caplog.records), (
        caplog.records
    )


def test_an_unreadable_cgroup_file_does_not_break_startup(monkeypatch):
    """Best effort means best effort: a missing quota file is not a failed deploy.

    This runs while the service comes up. Neither cgroup layout is guaranteed to
    be present — v1 and v2 keep the number in different files, and a sandbox may
    expose neither — so the only wrong answer here is raising.
    """
    import mcp_server.server as server_module

    class _Exploding:
        def __init__(self, *_a, **_k):
            pass

        def read_text(self, *_a, **_k):
            raise OSError("no cgroup here")

    _patch_pathlib(monkeypatch, _Exploding)
    assert server_module._cpu_budget() == "unavailable"


def test_the_quota_is_read_and_not_invented(tmp_path, monkeypatch):
    """The number has to come from the file, or it is decoration.

    A test that only checks "some string came back" would pass on a function
    that returned a constant, which is the shape of check this repo keeps
    warning about.
    """
    import mcp_server.server as server_module

    import pathlib as _pathlib

    v2 = tmp_path / "cpu.max"
    v2.write_text("150000 100000")

    def fake_path(p, *a, **k):
        return v2 if str(p) == "/sys/fs/cgroup/cpu.max" else _pathlib.Path(p, *a, **k)

    _patch_pathlib(monkeypatch, fake_path)
    assert server_module._cpu_budget() == "cgroup v2: 1.50 cpu"

    v2.write_text("max 100000")
    assert server_module._cpu_budget() == "cgroup v2: unlimited"
