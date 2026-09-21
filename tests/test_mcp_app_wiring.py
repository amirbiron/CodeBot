"""The service entry point carries the two request limits from the environment into the app it builds.

``limit_from_env`` is unit-tested and ``build_app`` is tested with explicit
values; the lines that connect them in ``mcp_server/app.py::create_app`` were
exercised by no test (WARN-001 in the seven-PR review). A misspelled variable
name or a dropped keyword would have shipped silently: the service would run
on the defaults while the config inspector shows the operator's value.

The technique is the one ``tests/test_mcp_logging_visible.py`` uses: a fresh
interpreter imports ``mcp_server.app`` exactly as uvicorn does. What differs is
that ``create_app`` has to *succeed* here, so the probe puts a fake ``database``
module on ``sys.modules`` before the import (the only place the entry point
touches the database layer is ``from database import db`` inside
``create_app``; every ``mcp_server`` module imports it lazily) and switches the
repo autosync off through its own environment flag. Both auth branches of
``create_app`` are driven — PAT, and OAuth with a strong ``SECRET_KEY`` — and a
control run without the variables shows the defaults, so the runs with them are
measuring the wiring and not a coincidence.

The body cap is read off the installed ``BodySizeLimitMiddleware`` (Starlette
keeps ``cls``/``kwargs`` on ``app.user_middleware``); the limiter's budget is
observed through a subclass installed on ``mcp_server.server`` before the import,
because ``build_mcp`` constructs ``ToolRateLimiter`` through that module's
global name and the built app does not expose the ``FastMCP`` instance.
"""

import json
import os
import pathlib
import subprocess
import sys
import textwrap

import pytest

pytest.importorskip("mcp")

from mcp_server import handlers, limits  # noqa: E402

REPO = str(pathlib.Path(__file__).resolve().parents[1])
TESTS = str(pathlib.Path(__file__).resolve().parent)

_PROBE = """
import json, sys, types
# The repo root first, so ``config`` resolves to the real module the service
# imports and not to the stub ``tests/config.py``; ``tests/`` after it, for the fake.
sys.path.insert(0, {tests!r})
sys.path.insert(0, {repo!r})
from _fake_mongo import FakeDB

# ``from database import db as db_manager`` inside create_app, then
# ``resolve_mongo(db_manager)`` reads ``db_manager.db``: a manager whose ``db``
# is the in-memory fake, and nothing else from the real package.
fake_database = types.ModuleType("database")
fake_database.db = types.SimpleNamespace(db=FakeDB())
sys.modules["database"] = fake_database

import mcp_server.server as server_module

constructed = []


class _Observed(server_module.ToolRateLimiter):
    def __init__(self, per_minute=server_module.DEFAULT_RATE_LIMIT_PER_MINUTE):
        constructed.append(per_minute)
        super().__init__(per_minute)


server_module.ToolRateLimiter = _Observed

import mcp_server.app as app_module
from mcp_server.limits import BodySizeLimitMiddleware

caps = [dict(m.kwargs) for m in app_module.app.user_middleware if m.cls is BodySizeLimitMiddleware]
print("WIRING=" + json.dumps({{
    "caps": caps,
    "limiters": constructed,
    "middleware": [m.cls.__name__ for m in app_module.app.user_middleware],
}}), flush=True)
print("PROBE-DONE", flush=True)
"""

_STRONG_SECRET = "wiring-test-secret-" + "x" * 48


def _wiring(mode: str, **variables: str) -> dict:
    """Import the entry point in a fresh interpreter and return what it wired."""
    env = dict(os.environ)
    for key in ("MCP_MAX_REQUEST_BYTES", "MCP_RATE_LIMIT_PER_MINUTE", "MAX_CODE_SIZE",
                "MCP_SERVER_URL", "WEBAPP_URL"):
        env.pop(key, None)
    env["MCP_REPO_AUTOSYNC"] = "0"
    if mode == "oauth":
        env["MCP_SERVER_URL"] = "https://mcp.test"
        env["WEBAPP_URL"] = "https://web.test"
        env["SECRET_KEY"] = _STRONG_SECRET
    env.update(variables)
    proc = subprocess.run(
        [sys.executable, "-B", "-c", textwrap.dedent(_PROBE.format(repo=REPO, tests=TESTS))],
        capture_output=True, text=True, timeout=180, cwd=REPO, env=env,
    )
    assert "PROBE-DONE" in proc.stdout, f"the probe did not finish\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    line = next(ln for ln in proc.stdout.splitlines() if ln.startswith("WIRING="))
    return json.loads(line[len("WIRING="):])


@pytest.mark.parametrize("mode", ["pat", "oauth"])
def test_the_two_limits_from_the_environment_reach_the_built_app(mode):
    wired = _wiring(mode, MCP_MAX_REQUEST_BYTES="131072", MCP_RATE_LIMIT_PER_MINUTE="5")

    assert wired["caps"] == [{"max_bytes": 131072}], wired
    assert wired["limiters"] == [5], wired
    assert "BodySizeLimitMiddleware" in wired["middleware"]
    assert ("PATAuthMiddleware" in wired["middleware"]) == (mode == "pat"), wired["middleware"]


def test_without_the_variables_the_app_runs_on_the_documented_defaults():
    """The control: the same probe, nothing set — so the run above measured the variables."""
    wired = _wiring("pat")

    assert wired["caps"] == [{"max_bytes": limits.DEFAULT_MAX_REQUEST_BYTES}], wired
    assert wired["limiters"] == [limits.DEFAULT_RATE_LIMIT_PER_MINUTE], wired


def test_the_body_cap_follows_the_code_size_ceiling_the_service_runs_with():
    """SUGG-022 at the entry point: ``MAX_CODE_SIZE`` raised in the environment raises the cap with it.

    ``create_app`` derives the cap from ``max_code_size()`` — the config's value,
    read at startup — so the two ceilings cannot drift apart in a deployment
    either; ``MCP_MAX_REQUEST_BYTES`` then only raises it further.
    """
    raised = 3 * handlers.DEFAULT_MAX_CODE_SIZE
    wired = _wiring("pat", MAX_CODE_SIZE=str(raised))

    assert wired["caps"] == [{"max_bytes": limits.request_bytes_for(raised)}], wired
    assert wired["caps"][0]["max_bytes"] > limits.DEFAULT_MAX_REQUEST_BYTES
