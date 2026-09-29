"""The service's log lines have to be visible *in the service*, not in ``caplog``.

``caplog`` installs its own handler on the root logger, so a test written with it
passes no matter what the process is configured to do. That is how log lines
shipped green and produced nothing in production. Two separate causes, both
found by running rather than reading:

* The capacity line was emitted before anything in the process had configured
  logging, so the root logger was still at ``WARNING`` with no handlers and the
  record was dropped where it stood. What configures logging in this service is
  ``FastMCP.__init__``, which ends with ``configure_logging(...)`` — so the line
  moved to after ``build_mcp`` returns, where a handler certainly exists. Since
  #3391 it is emitted later still, from the ASGI lifespan that installs the
  read pool it describes, so the probe below enters that lifespan the way
  uvicorn does.
* The per-write timing was at ``debug``, and the level the SDK sets is ``INFO``.

A third fix sits beside them: ``mcp_server/app.py`` now configures logging on
import, so records emitted before the MCP server is built are not lost either.
Each of the three is isolated by exactly one test below, and reverting any one
of them fails that test and no other.

So these tests do not use ``caplog``. They start a fresh interpreter, run the
real startup path, and read what actually reached that process's stdout and
stderr. The last test is the control: it reproduces the ordering trap and
asserts the line really does vanish, so the others are known to be measuring
configuration rather than that a function was called.
"""

import os
import pathlib
import subprocess
import sys
import textwrap

import pytest

pytest.importorskip("mcp")
pytest.importorskip("structlog")

REPO = str(pathlib.Path(__file__).resolve().parents[1])

_PRELUDE = """
import sys, types, logging
sys.path.insert(0, {repo!r})
root = logging.getLogger()
assert not root.handlers, f"the probe started with logging already configured: {{root.handlers}}"
"""

#: Exactly what uvicorn does with ``mcp_server.app:app``: import the module.
#: ``create_app()`` raises because there is no MongoDB here, which is the point —
#: the logging setup sits above it and has already run.
_REAL_STARTUP = """
try:
    import mcp_server.app  # noqa: F401
except Exception:
    pass
"""

_BUILD_AND_WRITE = """
import asyncio
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.provider import AccessToken
from mcp.server.fastmcp import Context
from mcp.server.lowlevel.server import request_ctx
from mcp.shared.context import RequestContext
from mcp_server.server import AdminAwareFastMCP, build_app


class _FakeBackend:
    def __getattr__(self, _name):
        return lambda *a, **k: {}


app = build_app(_FakeBackend(), repo_backend=_FakeBackend())

request_ctx.set(RequestContext(request_id=1, meta=None, session=None, lifespan_context=None,
    request=types.SimpleNamespace(state=types.SimpleNamespace(user_id=1, scopes=["write"]))))
auth_context_var.set(types.SimpleNamespace(access_token=AccessToken(
    token="t", client_id="u", scopes=["write"], expires_at=None)))


async def main():
    # The capacity line is emitted from the ASGI lifespan, where the read pool
    # is installed; entering it here is what uvicorn does at startup.
    async with app.router.lifespan_context(app):
        pass
    mcp = AdminAwareFastMCP("probe")
    def writer(ctx: Context) -> dict:
        return {}
    mcp.add_tool(writer, name="w", annotations={"readOnlyHint": False})
    await mcp.call_tool("w", {})


asyncio.run(main())
print("PROBE-DONE", flush=True)
"""


def _run(*parts: str, drop_env: tuple[str, ...] = ()) -> str:
    """Run the given fragments as one script in a fresh interpreter.

    Each fragment is dedented on its own: they are written at different
    indentation levels in this file, so dedenting the concatenation would leave
    the first fragment flush left and the rest indented under nothing.

    ``drop_env`` removes variables the test suite's ``conftest`` sets for
    everyone. That matters here: with ``MONGODB_URL`` present, ``create_app()``
    gets far enough to build the MCP server, and the SDK configures logging on
    the way — which would hide whether this package configured anything itself.
    """
    env = dict(os.environ)
    for key in drop_env:
        env.pop(key, None)
    script = "\n".join(textwrap.dedent(part) for part in parts)
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=REPO,
        env=env,
    )
    assert "PROBE-DONE" in proc.stdout, (
        f"the probe did not finish\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    return proc.stdout + proc.stderr


def test_the_app_module_configures_logging_even_when_startup_fails_early():
    """The package configures logging itself, and not only as a side effect.

    ``FastMCP.__init__`` ends with ``configure_logging(...)``, so a service that
    gets as far as building the MCP server ends up with a handler whether or not
    this package asked for one. That is exactly why this test removes
    ``MONGODB_URL``: ``create_app()`` then fails before it ever builds anything,
    and what is left is what ``mcp_server/app.py`` did on its own.

    Without that, every record emitted before ``build_mcp`` — including the one
    ``app.py`` itself writes when the repo autosync fails to start — is dropped
    where it stands, which is what issue #3375 measured.
    """
    output = _run(
        _PRELUDE.format(repo=REPO),
        _REAL_STARTUP,
        """
        root = logging.getLogger()
        print(f"HANDLERS={len(root.handlers)}", flush=True)
        server_log = logging.getLogger('mcp_server.server')
        print(f"INFO_ENABLED={server_log.isEnabledFor(logging.INFO)}", flush=True)
        print("PROBE-DONE", flush=True)
        """,
        drop_env=("MONGODB_URL",),
    )
    assert "HANDLERS=0" not in output, output
    assert "INFO_ENABLED=True" in output, output


def test_the_capacity_line_reaches_the_process_output():
    """Startup has to say how many reads can run at once, where someone can read it.

    The line is emitted from the lifespan that installs the read pool, so it
    names the pool that exists and the memory limit it was sized from.
    """
    output = _run(_PRELUDE.format(repo=REPO), _BUILD_AND_WRITE)
    assert "mcp dispatch capacity" in output, output
    assert "read pool" in output and "cpu quota" in output, output
    assert "memory limit" in output, output


def test_the_write_queue_wait_is_printed_at_a_level_that_survives():
    """A level nobody prints is not a log line.

    The level in force is ``INFO`` — set by ``mcp_server/app.py`` on import, and
    by ``FastMCP.__init__`` in any case — so this asserts the ordinary,
    non-slow write timing survives it. At ``debug``, where it started, it did
    not.
    """
    output = _run(_PRELUDE.format(repo=REPO), _BUILD_AND_WRITE)
    assert "queued" in output and "ran" in output, output


_FIT_FROM_A_WORKER = """
import threading
from mcp_server import answer_fit, answer_size


async def fit_probe():
    mcp = AdminAwareFastMCP("probe")

    def reader(ctx: Context, lines: str = "", secret_arg: str = "") -> dict:
        print(f"IN-WORKER={threading.current_thread() is not threading.main_thread()}", flush=True)
        answer_fit.cut(returned=3, of=40)
        return {"ok": False, **answer_fit.too_large(999_999), "hint": "h"}

    mcp.add_tool(reader, name="probe_read", annotations={"readOnlyHint": True},
                 meta=answer_size.declared_size_meta())
    await mcp.call_tool("probe_read", {"lines": "1-2", "secret_arg": "S3CR3T-VALUE"})


asyncio.run(fit_probe())
print("FIT-PROBE-DONE", flush=True)
"""


def test_a_fitted_answer_is_logged_from_the_worker_thread_by_argument_names_only():
    """SUGG-004: ``answer_too_large`` וחיתוך ב-``byte_budget`` נרשמים — גם כשהגוף רץ בחוט עובד.

    הגוף של כלי קריאה רץ ב-``asyncio.to_thread`` (``_offload_to_thread``), והפנקס שאליו
    בונה הסירוב ונקודת החיתוך כותבים נפתח ב-``call_tool``, על הלולאה. הוא מגיע לחוט רק
    כי ``to_thread`` מעתיק את ה-``Context``, והפנקס עצמו הוא אותו אובייקט בשני העותקים.
    אם זה נשבר, הפנקס נשאר ריק בשקט ואין שום שורה — ולכן זה נבדק כאן, בתהליך נקי ולא ב-
    ``caplog``, דרך ``call_tool`` ובכלי שמוכיח שרץ בחוט עובד. השורה נושאת את שם הכלי,
    **שמות** הארגומנטים והמספרים, ולא אף ערך (K13).
    """
    from mcp_server.answer_size import OUTPUT_BYTE_BUDGET

    # rich שובר שורה לפי רוחב הקונסולה, שנקרא מ-``COLUMNS`` כשהיא נבנית (rich 14.2.0,
    # ``Console.__init__``). כאן נבדק **מה** בשורה, ולכן היא לא נשברת באמצע.
    wide = "import os\nos.environ['COLUMNS'] = '1000'\n"
    output = _run(_PRELUDE.format(repo=REPO), wide, _BUILD_AND_WRITE, _FIT_FROM_A_WORKER)
    assert "FIT-PROBE-DONE" in output and "IN-WORKER=True" in output, output
    lines = [line for line in output.splitlines() if "answer_size_fit" in line]
    assert len(lines) == 1, output
    (line,) = lines
    assert "probe_read" in line and "lines" in line and "secret_arg" in line, line
    assert f"answer_too_large bytes=999999 max={OUTPUT_BYTE_BUDGET}" in line, line
    assert "byte_budget returned=3 of=40" in line, line
    assert "S3CR3T-VALUE" not in output and "1-2" not in line, line


def test_a_line_emitted_before_logging_is_configured_is_lost():
    """The control: the trap that produced the original bug, reproduced.

    Nothing here configures logging, and the record is dropped where it stands.
    This is why the capacity line is emitted after ``build_mcp`` rather than
    before it, and why the tests above are evidence rather than a tautology — if
    an unconfigured process started printing, they would pass for free.
    """
    output = _run(
        _PRELUDE.format(repo=REPO),
        """
        from concurrent.futures import ThreadPoolExecutor
        from mcp_server.server import _log_dispatch_capacity, _read_pool_size
        _log_dispatch_capacity(ThreadPoolExecutor(max_workers=2), "unavailable", _read_pool_size(None))
        print(f"HANDLERS={len(logging.getLogger().handlers)}", flush=True)
        print("PROBE-DONE", flush=True)
        """
    )
    assert "HANDLERS=0" in output, output
    assert "mcp dispatch capacity" not in output, output
