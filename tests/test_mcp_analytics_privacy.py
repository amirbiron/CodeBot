"""The privacy gate on PostHog MCP analytics — the part that must not regress.

This server's tool arguments and results are user files, sticky notes and
mirrored documents, so ``mcp_server.analytics.scrub_mcp_payload`` is what keeps
that content out of an analytics event. Every payload shape asserted here was
read off a real instrumented ``FastMCP`` run, not written from the docs: an
actual ``codekeeper_get_file`` call put the file body in
``$mcp_response.content[0].text``, a ``codekeeper_save_file`` call put it in
``$mcp_parameters.request.params.arguments.code``, and a raising tool put it in
``$mcp_error_message`` *and* in two ``$exception_list[*].value`` entries.

Each test here fails on the pre-change code, where there is no hook at all and
every one of those five places goes out as-is.
"""

import pytest

from mcp_server import analytics

_FILE_BODY = "def secret():\n    return 'user file content'\n"


def _tool_call_event(**extra_properties):
    """A ``$mcp_tool_call`` in the shape a real instrumented run produced."""
    properties = {
        "$mcp_source": "posthog_mcp_analytics",
        "$session_id": "ses_01a05d46-ded2-7c31-90be-8ebd6d289ae3",
        "$mcp_tool_name": "codekeeper_get_file",
        "$mcp_resource_name": "codekeeper_get_file",
        "$mcp_tool_description": "Full content of a saved file.",
        "$mcp_duration_ms": 12.5,
        "$mcp_is_error": False,
        "$mcp_client_name": "claude-code",
        "$mcp_client_version": "2.1.0",
        "$mcp_protocol_version": "2025-11-25",
        "$mcp_server_name": "CodeKeeper",
        "$mcp_listed_tool_names": ["codekeeper_get_file"],
        "$process_person_profile": False,
        "$lib": "posthog-python",
        "$mcp_parameters": {
            "request": {
                "method": "tools/call",
                "params": {
                    "name": "codekeeper_save_file",
                    "arguments": {"file_name": "notes.py", "code": _FILE_BODY},
                },
            }
        },
        "$mcp_response": {"content": [{"type": "text", "text": _FILE_BODY}]},
    }
    properties.update(extra_properties)
    return {
        "event": "$mcp_tool_call",
        "distinct_id": "ses_01a05d46-ded2-7c31-90be-8ebd6d289ae3",
        "properties": properties,
    }


def _payload_text(event):
    """Every string anywhere in the event, flattened."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            found.append(node)

    walk(event)
    return "\n".join(found)


def test_tool_call_loses_arguments_response_and_error_text():
    """The three payload keys the SDK puts a real tool call's content into."""
    event = _tool_call_event(
        **{
            "$mcp_is_error": True,
            "$mcp_error_type": "ValueError",
            "$mcp_error_message": "failed while reading " + _FILE_BODY,
        }
    )

    scrubbed = analytics.scrub_mcp_payload(event)

    properties = scrubbed["properties"]
    assert "$mcp_parameters" not in properties
    assert "$mcp_response" not in properties
    assert "$mcp_error_message" not in properties
    # The file body must be gone from the whole event, not just from the keys
    # named above — the same string sat in three of them.
    assert _FILE_BODY not in _payload_text(scrubbed)


def test_tool_call_keeps_the_metadata_the_dashboard_runs_on():
    """The gate must not be so blunt that it empties the analytics it guards."""
    scrubbed = analytics.scrub_mcp_payload(
        _tool_call_event(**{"$mcp_is_error": True, "$mcp_error_type": "ValueError"})
    )

    properties = scrubbed["properties"]
    for key in (
        "$mcp_tool_name",
        "$mcp_duration_ms",
        "$mcp_is_error",
        "$mcp_error_type",
        "$mcp_client_name",
        "$session_id",
        "$mcp_listed_tool_names",
    ):
        assert key in properties, key
    # Non-MCP infrastructure properties are left exactly as PostHog built them.
    assert properties["$process_person_profile"] is False
    assert properties["$lib"] == "posthog-python"


def test_unknown_mcp_property_is_dropped_not_forwarded():
    """The allowlist is the point: the MCP SDK is pre-1.0, so a payload property
    added in a future release must not ship just because nobody listed it."""
    event = _tool_call_event(**{"$mcp_tool_output_preview": _FILE_BODY})

    scrubbed = analytics.scrub_mcp_payload(event)

    assert "$mcp_tool_output_preview" not in scrubbed["properties"]
    assert _FILE_BODY not in _payload_text(scrubbed)


def test_exception_sibling_loses_the_message_and_keeps_the_stack():
    """``$mcp_error_message`` is *read from* ``$exception_list[*].value``, so
    removing only the former moves the leak one key over. An ``__cause__`` chain
    arrives as further entries in the same list — hence two entries here."""
    event = {
        "event": "$exception",
        "distinct_id": "ses_1",
        "properties": {
            "$session_id": "ses_1",
            "$mcp_tool_name": "codekeeper_get_file",
            "$exception_level": "error",
            "$exception_list": [
                {
                    "type": "ToolError",
                    "value": "Error executing tool: " + _FILE_BODY,
                    "mechanism": {"type": "generic", "handled": True},
                    "stacktrace": {"frames": [{"function": "run", "lineno": 101}]},
                },
                {"type": "ValueError", "value": _FILE_BODY},
            ],
        },
    }

    scrubbed = analytics.scrub_mcp_payload(event)

    entries = scrubbed["properties"]["$exception_list"]
    assert [entry["type"] for entry in entries] == ["ToolError", "ValueError"]
    assert entries[0]["stacktrace"] == {"frames": [{"function": "run", "lineno": 101}]}
    assert all(entry["value"] == analytics._EXCEPTION_VALUE_PLACEHOLDER for entry in entries)
    assert _FILE_BODY not in _payload_text(scrubbed)


def test_client_level_exception_autocapture_is_redacted_too():
    """The gate cannot be scoped to events that carry a ``$mcp_*`` property.

    ``enable_exception_autocapture`` installs ``sys.excepthook`` and
    ``threading.excepthook``, so an uncaught exception in any thread of the MCP
    process — the repo-autosync daemon, for one — arrives here as a plain
    ``$exception`` with no ``$mcp_*`` key anywhere on it. Verified by raising in
    a worker thread with a real client: the message reached the wire intact
    while this hook only looked at MCP events.
    """
    event = {
        "event": "$exception",
        "distinct_id": "worker",
        "properties": {
            "$exception_level": "error",
            "$exception_list": [
                {
                    "type": "RuntimeError",
                    "value": "mongo query failed for " + _FILE_BODY,
                    "stacktrace": {"frames": [{"function": "_sync_once"}]},
                }
            ],
        },
    }

    scrubbed = analytics.scrub_mcp_payload(event)

    entry = scrubbed["properties"]["$exception_list"][0]
    assert entry["value"] == analytics._EXCEPTION_VALUE_PLACEHOLDER
    # Type and frames survive, so error-tracking still groups these.
    assert entry["type"] == "RuntimeError"
    assert entry["stacktrace"] == {"frames": [{"function": "_sync_once"}]}
    assert _FILE_BODY not in _payload_text(scrubbed)


def test_client_is_built_with_the_settings_the_privacy_gate_depends_on(monkeypatch):
    """The gate is only in force because the constructor wires it in. Losing
    ``before_send`` — or a future SDK flipping ``capture_exception_code_variables``
    to default-on, which captures the local variables holding file content —
    would disable the protection with nothing else failing."""
    monkeypatch.setenv(analytics.ENV_PROJECT_TOKEN, "phc_test_token_not_real")
    monkeypatch.setenv(analytics.ENV_HOST, "https://us.i.posthog.com")

    captured = {}

    class _FakePosthog:
        def __init__(self, token, **kwargs):
            captured["token"] = token
            captured.update(kwargs)

        def shutdown(self):  # registered with atexit
            pass

    import posthog

    monkeypatch.setattr(posthog, "Posthog", _FakePosthog)

    client = analytics._build_client()

    assert client is not None
    assert captured["token"] == "phc_test_token_not_real"
    assert captured["host"] == "https://us.i.posthog.com"
    assert captured["before_send"] is analytics.scrub_mcp_payload
    assert captured["capture_exception_code_variables"] is False
    assert captured["enable_exception_autocapture"] is True


def test_client_is_not_built_when_either_variable_is_missing(monkeypatch):
    """Both are required: the host decides the region, and guessing it sends
    events somewhere they cannot be read."""
    monkeypatch.setenv(analytics.ENV_PROJECT_TOKEN, "phc_test_token_not_real")
    monkeypatch.delenv(analytics.ENV_HOST, raising=False)
    assert analytics._build_client() is None

    monkeypatch.delenv(analytics.ENV_PROJECT_TOKEN, raising=False)
    monkeypatch.setenv(analytics.ENV_HOST, "https://us.i.posthog.com")
    assert analytics._build_client() is None


def test_scrubber_failure_drops_the_event_instead_of_sending_it_raw():
    """Fail-closed. A hook that raised and let the original event through would
    send exactly the payload it exists to remove."""

    class _Hostile(dict):
        def items(self):
            raise RuntimeError("boom")

    properties = _Hostile()
    properties["$mcp_parameters"] = {"code": _FILE_BODY}

    assert analytics.scrub_mcp_payload({"event": "$mcp_tool_call", "properties": properties}) is None


def test_allowlist_names_still_exist_in_the_installed_sdk():
    """A rename in the SDK's property constants must fail here, loudly, rather
    than silently drop a field the allowlist no longer matches.

    Imported directly and not through ``importorskip``: ``posthog`` is pinned in
    ``requirements/base.txt``, so the module going missing is itself the
    regression, not a reason to skip.
    """
    from posthog.mcp import constants

    known = {
        value
        for name, value in vars(constants.PostHogMCPAnalyticsProperty).items()
        if not name.startswith("_") and isinstance(value, str)
    }
    unknown = {
        name
        for name in analytics._ALLOWED_MCP_PROPERTIES | analytics._PAYLOAD_PROPERTIES
        if name.startswith("$mcp_") and name not in known
    }
    assert not unknown, f"no longer emitted by the SDK: {sorted(unknown)}"


def test_payload_properties_are_never_allowlisted():
    """The two sets must stay disjoint; an overlap would silently open the gate."""
    assert not (analytics._ALLOWED_MCP_PROPERTIES & analytics._PAYLOAD_PROPERTIES)


def test_missing_configuration_is_loud_in_development_and_quiet_in_production(monkeypatch):
    """A production box must still boot; a developer must not be left guessing."""
    monkeypatch.delenv(analytics.ENV_PROJECT_TOKEN, raising=False)
    monkeypatch.delenv(analytics.ENV_HOST, raising=False)

    monkeypatch.setenv("ENVIRONMENT", "development")
    with pytest.raises(RuntimeError) as excinfo:
        analytics._report_missing_configuration()
    assert analytics.ENV_PROJECT_TOKEN in str(excinfo.value)
    assert "silently missed" in str(excinfo.value)

    monkeypatch.setenv("ENVIRONMENT", "production")
    analytics._report_missing_configuration()  # no raise


def test_instrumenting_without_configuration_is_a_noop_in_production(monkeypatch):
    """A production box with no PostHog configuration still builds its server."""
    monkeypatch.setattr(analytics, "_CLIENT", None)
    monkeypatch.delenv(analytics.ENV_PROJECT_TOKEN, raising=False)
    monkeypatch.delenv(analytics.ENV_HOST, raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")

    analytics.instrument_mcp_server(object())


def test_shutdown_drain_is_not_attached_without_a_client(monkeypatch):
    """With analytics off, the app's lifespan is left exactly as it was."""
    monkeypatch.setattr(analytics, "_CLIENT", None)

    class _Router:
        lifespan_context = "sentinel"

    class _App:
        router = _Router()

    app = _App()
    analytics.attach_shutdown_drain(app)
    assert app.router.lifespan_context == "sentinel"


def test_shutdown_drain_wraps_the_lifespan_and_flushes_both_queues():
    """``FastMCP.streamable_http_app()`` passes an explicit ``lifespan=``, and a
    Starlette ``Router`` then ignores ``on_shutdown`` entirely — so the wrapper
    has to replace ``lifespan_context`` and still run the original."""
    import asyncio
    import contextlib

    calls = []

    class _FakeAnalytics:
        async def flush(self):
            calls.append("analytics.flush")

    class _FakeClient:
        def flush(self):
            calls.append("client.flush")

    @contextlib.asynccontextmanager
    async def _original(app):
        calls.append("original.startup")
        yield {"state": 1}
        calls.append("original.shutdown")

    class _Router:
        lifespan_context = staticmethod(_original)

    class _App:
        router = _Router()

    app = _App()

    saved = (analytics._CLIENT, analytics._ANALYTICS)
    analytics._CLIENT = _FakeClient()
    analytics._ANALYTICS = _FakeAnalytics()
    try:
        analytics.attach_shutdown_drain(app)

        async def _run():
            async with app.router.lifespan_context(app) as state:
                assert state == {"state": 1}

        asyncio.run(_run())
    finally:
        analytics._CLIENT, analytics._ANALYTICS = saved

    # Both queues drained, and the original lifespan still ran on both edges.
    assert calls == [
        "original.startup",
        "analytics.flush",
        "client.flush",
        "original.shutdown",
    ]


async def test_a_real_instrumented_tool_call_reaches_posthog_with_no_content(monkeypatch):
    """End-to-end through the wiring the guarantee actually depends on.

    The unit tests above call ``scrub_mcp_payload`` directly, so a regression
    that dropped the hook from the client — or wired ``instrument_mcp_server``
    to a different one — would leave them all green while the gate did nothing
    in production. This drives a real ``FastMCP`` server through a real MCP
    session with a real ``Posthog`` client and asserts on what the client was
    about to send.

    ``send=False`` keeps everything inside the test: the payload is built and
    passed through ``before_send``, then dropped instead of going to the network.
    """
    pytest.importorskip("mcp")
    from mcp.server.fastmcp import FastMCP
    from mcp.shared.memory import create_connected_server_and_client_session
    from posthog import Posthog

    about_to_send = []

    def recording_gate(event):
        # Wraps the real hook rather than replacing it, so what is recorded is
        # exactly what the client would have queued.
        result = analytics.scrub_mcp_payload(event)
        if result is not None:
            about_to_send.append(result)
        return result

    client = Posthog(
        "phc_test_token_not_real",
        host="https://us.i.posthog.com",
        send=False,
        before_send=recording_gate,
        enable_exception_autocapture=False,
        capture_exception_code_variables=False,
    )
    monkeypatch.setattr(analytics, "_CLIENT", client)
    monkeypatch.setattr(analytics, "_ANALYTICS", None)

    server = FastMCP("CodeKeeper-test", stateless_http=True)

    @server.tool(name="codekeeper_get_file", description="Full content of a saved file.")
    def get_file(file_name: str) -> dict:
        return {"file_name": file_name, "code": _FILE_BODY}

    analytics.instrument_mcp_server(server)

    try:
        async with create_connected_server_and_client_session(server._mcp_server) as session:
            listed = await session.list_tools()
            await session.call_tool("codekeeper_get_file", {"file_name": "notes.py"})
        await analytics._drain()
    finally:
        client.shutdown()

    tool_calls = [e for e in about_to_send if e.get("event") == "$mcp_tool_call"]
    assert tool_calls, "instrumentation captured nothing — the wiring is broken"

    properties = tool_calls[0]["properties"]
    assert properties["$mcp_tool_name"] == "codekeeper_get_file"
    assert properties["$mcp_duration_ms"] is not None
    assert "$mcp_parameters" not in properties
    assert "$mcp_response" not in properties
    # The tool really did return the file body; none of it may be on the wire.
    assert _FILE_BODY not in _payload_text(about_to_send)

    # Instrumentation is additive: the advertised schema is untouched, with no
    # `context` or `conversation_id` argument injected into it.
    schema = next(t.inputSchema for t in listed.tools if t.name == "codekeeper_get_file")
    assert sorted(schema.get("properties") or {}) == ["file_name"]
