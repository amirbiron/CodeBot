"""The service's log lines have to be visible *in the service*, not in ``caplog``.

``caplog`` installs its own handler on the root logger, so a test written with it
passes no matter what the process is configured to do. That is how log lines
shipped green and produced nothing in production. Two separate causes, both
found by running rather than reading:

* The capacity line was emitted before anything in the process had configured
  logging, so the root logger was still at ``WARNING`` with no handlers and the
  record was dropped where it stood. What configures logging in this service is
  ``FastMCP.__init__``, which ends with ``configure_logging(...)`` — so the line
  moved to after ``build_mcp`` returns, where a handler certainly exists.
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


build_app(_FakeBackend(), repo_backend=_FakeBackend())

request_ctx.set(RequestContext(request_id=1, meta=None, session=None, lifespan_context=None,
    request=types.SimpleNamespace(state=types.SimpleNamespace(user_id=1, scopes=["write"]))))
auth_context_var.set(types.SimpleNamespace(access_token=AccessToken(
    token="t", client_id="u", scopes=["write"], expires_at=None)))


async def main():
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
    """Startup has to say how many reads can run at once, where someone can read it."""
    output = _run(_PRELUDE.format(repo=REPO), _BUILD_AND_WRITE)
    assert "mcp dispatch capacity" in output, output
    assert "read pool" in output and "cpu quota" in output, output


def test_the_write_queue_wait_is_printed_at_a_level_that_survives():
    """A level nobody prints is not a log line.

    The level in force is ``INFO`` — set by ``mcp_server/app.py`` on import, and
    by ``FastMCP.__init__`` in any case — so this asserts the ordinary,
    non-slow write timing survives it. At ``debug``, where it started, it did
    not.
    """
    output = _run(_PRELUDE.format(repo=REPO), _BUILD_AND_WRITE)
    assert "queued" in output and "ran" in output, output


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
        from mcp_server.server import _log_dispatch_capacity
        _log_dispatch_capacity()
        print(f"HANDLERS={len(logging.getLogger().handlers)}", flush=True)
        print("PROBE-DONE", flush=True)
        """
    )
    assert "HANDLERS=0" in output, output
    assert "mcp dispatch capacity" not in output, output
