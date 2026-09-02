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


def test_tool_call_loses_its_arguments_and_its_result():
    """The two payload keys the SDK puts a real tool call's content into.

    These are the guarantee that survived every widening of this gate: on a
    write tool ``$mcp_parameters`` *is* the file, and ``$mcp_response`` is the
    body of whatever was read. Nothing in this module can reopen either.

    The error message on this event is deliberately content-free, because the
    message is now forwarded (see the section at the bottom of this file) and
    it would otherwise be the string proving the assertion below rather than
    the two keys under test.
    """
    event = _tool_call_event(
        **{
            "$mcp_is_error": True,
            "$mcp_error_type": "ValueError",
            "$mcp_error_message": "database is locked",
        }
    )

    scrubbed = analytics.scrub_mcp_payload(event)

    properties = scrubbed["properties"]
    assert "$mcp_parameters" not in properties
    assert "$mcp_response" not in properties
    # The file body must be gone from the whole event, not just from the keys
    # named above — the same string sat in both of them.
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


def test_the_blocked_payload_keys_are_on_neither_allowlist():
    """The blocked set stays disjoint from **both** allowlists.

    Named for what it actually proves. An earlier version was called "never
    allowlisted", which stopped being true the moment a separate mapping
    re-admitted ``$mcp_intent`` on one event: the assertion still passed,
    because that exception lived somewhere this test never looked, so the name
    promised more than the check delivered. Now there is nowhere else to look —
    the two sets below are the whole decision — and this assertion means what
    its name says.
    """
    allowed = analytics._ALLOWED_MCP_PROPERTIES | analytics._ALLOWED_FREE_TEXT_PROPERTIES
    assert not (allowed & analytics._PAYLOAD_PROPERTIES)
    assert analytics._PAYLOAD_PROPERTIES == {"$mcp_parameters", "$mcp_response"}


def test_the_free_text_allowlist_is_pinned_to_exactly_two_names():
    """Adding a third free-text property widens the gate, so it must be loud.

    Both names here forward text this server did not write — an agent's
    sentence and a library's exception message — and both were accepted with
    their costs measured. A fourth name arriving quietly in review is exactly
    what this assertion exists to prevent.
    """
    assert analytics._ALLOWED_FREE_TEXT_PROPERTIES == {
        "$mcp_error_message",
        "$mcp_intent",
    }


def test_no_conditional_discriminator_survives_in_the_module():
    """The per-event and per-error-type tables are **gone**, not dormant.

    Both were mappings from a discriminator to an extra allowlist, and both
    lost their last entry when the two properties they guarded were admitted
    unconditionally. An empty mapping left behind reads like a gate that is
    still deciding something, and the next person to widen the surface would
    have reached for it. Dead code shaped like a security control is worse than
    no code, so it was deleted — and this test keeps it deleted.
    """
    assert not hasattr(analytics, "_ALLOWED_BY_EVENT")
    assert not hasattr(analytics, "_ALLOWED_BY_ERROR_TYPE")


def _missing_capability_event(**extra_properties):
    """An ``$mcp_missing_capability`` in the shape a real instrumented run produced.

    Measured against ``mcp 1.28.1`` + ``posthog 7.45.3``: the agent's sentence
    lands in ``$mcp_intent``, and ``$mcp_parameters`` carries ``arguments: {}``
    because the SDK strips the injected ``context`` argument out of it itself.
    """
    properties = {
        "$mcp_source": "posthog_mcp_analytics",
        "$session_id": "ses_1",
        "$mcp_resource_name": "get_more_tools",
        "$mcp_server_name": "CodeKeeper",
        "$mcp_intent": "I wish I could grep inside sticky notes",
        "$mcp_intent_source": "context_parameter",
        "$mcp_parameters": {
            "request": {"method": "tools/call", "params": {"arguments": {}}}
        },
    }
    properties.update(extra_properties)
    return {
        "event": "$mcp_missing_capability",
        "distinct_id": "ses_1",
        "properties": properties,
    }


def test_the_agents_sentence_survives_on_a_missing_capability_event():
    """Without this the feature is a counter with no reason, which is the same
    as not having it."""
    scrubbed = analytics.scrub_mcp_payload(_missing_capability_event())

    properties = scrubbed["properties"]
    assert properties["$mcp_intent"] == "I wish I could grep inside sticky notes"
    assert properties["$mcp_intent_source"] == "context_parameter"
    assert properties["$mcp_resource_name"] == "get_more_tools"


def test_the_exception_does_not_reopen_parameters_on_that_same_event():
    """The exception admits the intent and nothing else."""
    scrubbed = analytics.scrub_mcp_payload(
        _missing_capability_event(**{"$mcp_response": {"content": [{"text": _FILE_BODY}]}})
    )

    properties = scrubbed["properties"]
    assert "$mcp_parameters" not in properties
    assert "$mcp_response" not in properties
    assert _FILE_BODY not in _payload_text(scrubbed)


def test_the_agents_sentence_rides_an_ordinary_tool_call_too():
    """The intent is no longer scoped to ``$mcp_missing_capability``.

    This is the half of the change that makes the navigation-cost table
    readable: without it every row says a session made 15 calls and nothing
    says what it was trying to do. It is a deliberate widening — the sentence
    is free text an agent wrote — and it is only reachable because
    ``instrument_mcp_server`` turns ``context`` on, which is what makes the SDK
    produce an intent on a plain tool call at all.
    """
    scrubbed = analytics.scrub_mcp_payload(
        _tool_call_event(
            **{
                "$mcp_intent": "reading the outline before requesting a line range",
                "$mcp_intent_source": "context_parameter",
            }
        )
    )

    properties = scrubbed["properties"]
    assert properties["$mcp_intent"] == "reading the outline before requesting a line range"
    assert properties["$mcp_intent_source"] == "context_parameter"
    assert properties["$mcp_tool_name"] == "codekeeper_get_file"
    # Widening the intent did not widen anything next to it.
    assert "$mcp_parameters" not in properties
    assert "$mcp_response" not in properties
    assert _FILE_BODY not in _payload_text(scrubbed)


def test_the_intent_is_not_keyed_on_an_event_name_any_more():
    """No event name is privileged, and none is excluded.

    The old gate keyed the intent on one exact event name, and this test used
    to prove that lookalike names did not inherit it. The property is now
    admitted on its own merits, so the same names prove the opposite — and the
    test is kept rather than deleted precisely because the assertion flipped:
    a reader comparing the two versions can see the decision, not just its
    result.
    """
    for name in ("$mcp_missing_capability_v2", "mcp_missing_capability", "$mcp_tools_list"):
        event = _missing_capability_event()
        event["event"] = name

        scrubbed = analytics.scrub_mcp_payload(event)

        assert scrubbed["properties"]["$mcp_intent"], name


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
            await session.call_tool(
                "codekeeper_get_file",
                {"file_name": "notes.py", "context": "reading a saved file to answer a question"},
            )
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

    # The agent's sentence made it through the real pipeline, which is what the
    # intent column on `/admin/mcp` reads. The unit tests above prove the gate
    # admits it; only this one proves anything produces it.
    assert properties["$mcp_intent"] == "reading a saved file to answer a question"
    assert properties["$mcp_intent_source"] == "context_parameter"

    # `codekeeper_get_file` is a file-read tool called with neither `lines` nor
    # `outline`, so it is a full content read — the expensive kind the outline
    # feature exists to replace.
    assert properties[analytics.CK_READ_MODE_KEY] == analytics.READ_MODE_FULL

    # Instrumentation is **no longer** schema-neutral, and this is the assertion
    # that used to say it was. `context=True` adds one string parameter to every
    # tool, and marks it required — measured, not assumed. `conversation_id`
    # stays off, so it must not appear here.
    schema = next(t.inputSchema for t in listed.tools if t.name == "codekeeper_get_file")
    assert sorted(schema.get("properties") or {}) == ["context", "file_name"]
    assert "context" in (schema.get("required") or [])
    assert "conversation_id" not in (schema.get("properties") or {})


# ---------------------------------------------------------------------------
# הודעת השגיאה — עוברת עכשיו על **כל** סוג שגיאה
#
# עד לשינוי הזה ההודעה הייתה מגודרת ל-``ValidationError`` בלבד, והגידור הוא
# שמנע ממנה לשאת שמות קבצים ונתיבים מהודעות של ספריות. הגידור הוסר בהחלטה
# מפורשת של בעל הפרויקט, אחרי שהעלות הוצגה. מה שהטסטים כאן שומרים הוא לא
# ההיקף — הוא נפתח — אלא **מה שנשאר סגור לצידו**: הארגומנטים, התוצאה,
# ושרשרת החריגות המלאה.
# ---------------------------------------------------------------------------

_VALIDATION_MESSAGE = (
    "1 validation error for save_fileArguments\n"
    "file_name\n"
    "  Field required [type=missing, "
    "input_value={'code': 'PASSWORD=hunter...AWS_KEY=AKIA_BOTTOM\\n'}, "
    "input_type=dict]"
)


def _failed_tool_call(error_type, message=_VALIDATION_MESSAGE, **extra):
    return _tool_call_event(
        **{
            "$mcp_is_error": True,
            "$mcp_error_type": error_type,
            "$mcp_error_message": message,
            **extra,
        }
    )


def test_a_validation_error_message_reaches_posthog():
    """המטרה המקורית של הפתיחה: לראות **איזה שדה** נדחה, ולא רק שמשהו נדחה."""
    out = analytics.scrub_mcp_payload(_failed_tool_call("ValidationError"))

    assert out["properties"]["$mcp_error_message"] == _VALIDATION_MESSAGE
    assert "file_name" in out["properties"]["$mcp_error_message"]


@pytest.mark.parametrize(
    "error_type",
    ["RuntimeError", "ValueError", "TypeError", "KeyError", "ToolError", "Exception", ""],
)
def test_every_other_error_type_now_carries_its_message_too(error_type):
    """הפוך מהטסט שהיה כאן — וזו בדיוק הנקודה.

    הגרסה הקודמת אכפה ש``RuntimeError`` נחסם, כי ``RuntimeError("mongo query
    failed for <קובץ>")`` הוא המקרה שכבר עקף את השער פעם אחת. הגידור הזה הוסר
    ביודעין, ולכן ההודעה הזו יוצאת עכשיו. הטסט לא נמחק אלא הופך: מי שמשווה את
    שתי הגרסאות רואה החלטה, לא שינוי שקט.
    """
    out = analytics.scrub_mcp_payload(
        _failed_tool_call(error_type, "mongo query failed for notes.py")
    )

    assert out["properties"]["$mcp_error_message"] == "mongo query failed for notes.py"


def test_a_message_without_any_error_type_is_forwarded():
    """אין יותר מבחין, ולכן אין יותר מה להיכשל-סגור עליו.

    בגרסה הקודמת היעדר ``$mcp_error_type`` חסם את ההודעה. זה נשמר כטסט כדי
    שהמעבר מ"נכשל-סגור על מבחין" ל"אין מבחין" יהיה כתוב ולא משתמע.
    """
    event = _failed_tool_call("ValidationError")
    del event["properties"]["$mcp_error_type"]

    out = analytics.scrub_mcp_payload(event)

    assert out["properties"]["$mcp_error_message"] == _VALIDATION_MESSAGE


def test_opening_the_message_did_not_open_the_arguments_or_the_result():
    """הדרישה המפורשת, וההגנה היחידה שנשארה על גוף הקובץ בקריאת כתיבה.

    ``$mcp_parameters`` הוא הקובץ עצמו ב-``save_file``/``edit_file``, ולכן
    פתיחת ההודעה אסור לה לגרור אותו. אין שום מסלול במודול שיכול לפתוח אותו.
    """
    out = analytics.scrub_mcp_payload(_failed_tool_call("RuntimeError"))

    assert "$mcp_parameters" not in out["properties"]
    assert "$mcp_response" not in out["properties"]
    assert _FILE_BODY not in _payload_text(out)


def test_the_exception_list_message_stays_redacted_even_when_the_message_passes():
    """ההודעה מותרת; התאום שלה ב-``$exception_list`` נשאר מושחר.

    אלה לא אותם נתונים: ``$mcp_error_message`` נושא את הרשומה הראשית בלבד,
    מקוצצת ל-2,048 תווים בידי ה-SDK, ואילו ``$exception_list`` נושא את שרשרת
    ה-``__cause__`` **המלאה ובלי תקרה**. פתיחת השני יחד עם הראשון הייתה
    הרחבה שאיש לא ביקש, ולכן ההשחרה שם נשארת ללא תנאי.
    """
    event = _failed_tool_call("ValidationError")
    event["properties"]["$exception_list"] = [
        {"type": "ValidationError", "value": _FILE_BODY, "stacktrace": {"frames": []}}
    ]

    out = analytics.scrub_mcp_payload(event)

    assert out["properties"]["$mcp_error_message"] == _VALIDATION_MESSAGE
    assert _FILE_BODY not in _payload_text(out)


# ---------------------------------------------------------------------------
# מה שנכנס דרך רשימת הטקסט החופשי חייב להיות מחרוזת
#
# שני השדות מוצדקים כ"משפט שאדם קורא". מילון או רשימה תחת אותו שם אינם המשפט
# הזה — הם מבנה שלם שעובר שלם. זו הבדיקה היחידה ששרדה את הסרת הגידור, והיא גם
# היחידה שמפרידה בין "טקסט חופשי" לבין "כל מה שה-SDK ישים שם".
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        {"loc": ["file_name"], "input": _FILE_BODY},
        [{"input": _FILE_BODY}],
        {"nested": {"deeper": _FILE_BODY}},
    ],
)
def test_a_structured_error_message_is_still_dropped(message):
    """נמדד לפני שהכלל נוסף: מילון תחת ``$mcp_error_message`` עבר עם התוכן בפנים."""
    out = analytics.scrub_mcp_payload(_failed_tool_call("ValidationError", message))

    assert "$mcp_error_message" not in out["properties"]
    assert _FILE_BODY not in _payload_text(out)


@pytest.mark.parametrize("message", [None, 42, True, 3.5])
def test_a_non_string_error_message_is_dropped(message):
    out = analytics.scrub_mcp_payload(_failed_tool_call("ValidationError", message))

    assert "$mcp_error_message" not in out["properties"]


@pytest.mark.parametrize(
    "intent",
    [{"text": _FILE_BODY}, [_FILE_BODY], None, 42],
)
def test_the_same_rule_guards_the_intent(intent):
    """אותו חור בדיוק היה גם ב-``$mcp_intent``, ולכן אותו כלל חל על שניהם.

    עכשיו זה חשוב יותר מקודם: הכוונה מגיעה על **כל** קריאת כלי, ולא על אירוע
    נדיר אחד.
    """
    event = _tool_call_event(**{"$mcp_intent": intent})

    out = analytics.scrub_mcp_payload(event)

    assert "$mcp_intent" not in out["properties"]
    assert _FILE_BODY not in _payload_text(out)


def test_a_plain_sentence_still_passes_through_both_names():
    """הכלל מצמצם ולא סוגר: מה שהשדות נועדו לו ממשיך לעבור.

    בלי הטסט הזה, "לחסום הכל" היה עובר את כל השאר.
    """
    tool_call = analytics.scrub_mcp_payload(
        _failed_tool_call("ValidationError", "1 validation error\nfile_name")
    )
    missing = analytics.scrub_mcp_payload(_missing_capability_event())

    assert tool_call["properties"]["$mcp_error_message"] == "1 validation error\nfile_name"
    assert missing["properties"]["$mcp_intent"]


def test_a_str_subclass_is_accepted():
    """תת-מחלקה של ``str`` **היא** מחרוזת, ואין סיבה לחסום אותה.

    בלי הטסט הזה, הכלל היה מזמין בדיקה נוקשה מדי (``type(value) is str``)
    שהייתה חוסמת ערך תקין לחלוטין — ``StrEnum`` הוא המקרה הנפוץ.
    """

    class _StrEnumLike(str):
        pass

    out = analytics.scrub_mcp_payload(
        _failed_tool_call("ValidationError", _StrEnumLike(_VALIDATION_MESSAGE))
    )

    assert out["properties"]["$mcp_error_message"] == _VALIDATION_MESSAGE


# ---------------------------------------------------------------------------
# ``ck_read_mode`` — מאפיין שהשרת מחשב בעצמו
#
# ``outline=true`` ו-``lines=[5, 80]`` הן אותו כלי, וההבחנה ביניהן חיה
# ב-``$mcp_parameters`` שחסום ונשאר חסום. במקום לפתוח אותו, השרת גוזר תווית
# אחת מתוך קבוצה סגורה. הטסטים כאן שומרים את שני הצדדים: שהתווית נכונה, ושדרך
# השם הזה לא יכולה לעבור מחרוזת חופשית.
# ---------------------------------------------------------------------------


def _tool_call_request(name, arguments):
    """הצורה ש-``posthog.mcp`` בונה ומעביר לקולבק (``build_tool_call_request``)."""
    return {"method": "tools/call", "params": {"name": name, "arguments": arguments}}


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ({"repo": "r", "path": "p", "outline": True}, analytics.READ_MODE_OUTLINE),
        ({"repo": "r", "path": "p", "lines": [5, 80]}, analytics.READ_MODE_RANGE),
        ({"repo": "r", "path": "p"}, analytics.READ_MODE_FULL),
        # אאוטליין וטווח יחד נדחים בכלי כ-``outline_and_lines``. הקריאה לא
        # קראה תוכן, ולכן העמודה הזולה היא המקום הישר בשבילה.
        (
            {"repo": "r", "path": "p", "outline": True, "lines": [5, 80]},
            analytics.READ_MODE_OUTLINE,
        ),
        # ``outline=false`` מפורש הוא קריאה מלאה, לא אאוטליין — הבדיקה היא על
        # הערך ולא רק על קיום המפתח.
        ({"repo": "r", "path": "p", "outline": False}, analytics.READ_MODE_FULL),
    ],
)
def test_the_read_mode_is_derived_from_which_parameter_was_passed(arguments, expected):
    props = analytics.read_mode_properties(
        _tool_call_request("codekeeper_get_repo_file", arguments)
    )

    assert props == {analytics.CK_READ_MODE_KEY: expected}


def test_the_read_mode_never_echoes_a_value_that_came_from_the_caller():
    """הטענה המרכזית של הפיצ'ר: מה שיוצא הוא תווית, לא ארגומנט.

    בלי זה הפיצול היה הופך לדלת אחורית ל-``$mcp_parameters`` — בדיוק מה שהוא
    נבנה כדי לעקוף.
    """
    props = analytics.read_mode_properties(
        _tool_call_request(
            "codekeeper_get_repo_file",
            {"repo": "secret-repo", "path": "config/.env.production", "lines": [1, 40]},
        )
    )

    assert props == {analytics.CK_READ_MODE_KEY: analytics.READ_MODE_RANGE}
    assert "secret-repo" not in str(props)
    assert ".env" not in str(props)


@pytest.mark.parametrize(
    "request_payload",
    [
        # לחיצת היד ורשימת הכלים — ה-SDK מריץ את הקולבק גם עליהן. גרסה
        # שנפלה כאן ל-``full`` תייגה אותן כקריאת קובץ מלאה, וניפחה בדיוק את
        # העמודה שהפיצ'ר נבנה כדי למדוד. נמדד מול ``posthog 7.45.3``.
        {"method": "initialize", "params": {}},
        {"method": "tools/list", "params": {}},
        # כלי אמיתי שאינו קורא קבצים.
        {
            "method": "tools/call",
            "params": {"name": "codekeeper_search_repo", "arguments": {"query": "x"}},
        },
        {"method": "tools/call", "params": {"name": "get_more_tools", "arguments": {}}},
        # קלט פגום מ-SDK חיצוני — נכשל-סגור, בלי לזרוק.
        {"method": "tools/call", "params": None},
        {"method": "tools/call"},
        None,
        "tools/call",
    ],
)
def test_nothing_but_a_file_read_gets_tagged(request_payload):
    assert analytics.read_mode_properties(request_payload) is None


def test_the_gate_forwards_a_declared_read_mode():
    event = _tool_call_event(**{analytics.CK_READ_MODE_KEY: analytics.READ_MODE_OUTLINE})

    out = analytics.scrub_mcp_payload(event)

    assert out["properties"][analytics.CK_READ_MODE_KEY] == analytics.READ_MODE_OUTLINE


@pytest.mark.parametrize(
    "value",
    [
        "def secret():\n    return 'user file content'\n",
        {"mode": "outline", "path": "config/.env"},
        ["outline"],
        None,
        42,
        "OUTLINE",
        "",
    ],
)
def test_the_gate_drops_anything_the_read_mode_was_not_declared_to_be(value):
    """מאפיין משלנו אינו נושא ``$mcp_`` ולכן רשימת ההיתר אינה חלה עליו.

    בלי האכיפה הזו היה כאן שם שדרכו אפשר לשלוח כל מחרוזת — כלומר בדיוק החור
    שהשער קיים כדי לסגור, רק בשם אחר. המילון והרשימה כאן אינם קישוט: ``value
    in frozenset`` על טיפוס לא בר-גיבוב זורק ``TypeError``, וזה היה מפיל את
    ה-hook ומוחק את האירוע כולו.
    """
    event = _tool_call_event(**{analytics.CK_READ_MODE_KEY: value})

    out = analytics.scrub_mcp_payload(event)

    assert out is not None
    assert analytics.CK_READ_MODE_KEY not in out["properties"]


async def test_the_file_read_tool_names_still_match_the_registered_tools():
    """הרשימה משוכפלת מ-``server.py`` ולכן חייבת להיאכף, לא להיזכר.

    ``analytics.py`` אינו יכול לייבא מ-``server.py`` (ייבוא מעגלי), ולכן שמות
    הכלים כתובים בשני מקומות. שינוי שם כלי בלי לעדכן כאן לא היה מפיל שום דבר:
    הטבלה ב-``/admin/mcp`` הייתה ממשיכה להיטען, פשוט עם אפסים בשתי העמודות
    החדשות — כשל שקט, וזה בדיוק מה שהטסט הזה הופך לרועש.

    הכלים נגזרים מהסכימה המוצהרת ולא מרשימה שנייה קשיחה: כלי שמקבל ``lines``
    הוא כלי שקורא תוכן קובץ, וזו ההגדרה שהמדד נשען עליה.
    """
    pytest.importorskip("mcp")
    from mcp_server.server import build_mcp

    # ``object()`` ולא דמה מקובץ טסט אחר. שתי סיבות, ושתיהן שורש:
    # ``tests`` אינו חבילה, ולכן ``from tests.x import y`` תלוי במה שנאסף
    # באותה ריצה — הטסט הזה עבר לבד ונפל בסוויטה. ומעבר לכך, אין מה לדמות:
    # ההרשמה של הכלים בונה סגורים בלבד, ושיטות ה-backend נקראות רק בקריאה
    # בפועל. ``repo_backend`` חייב להיות לא-``None`` כדי שכלי הריפו יירשמו.
    mcp = build_mcp(object(), repo_backend=object())
    mcp._request_is_admin = lambda: True
    with_lines = {
        tool.name
        for tool in await mcp.list_tools()
        if "lines" in ((tool.inputSchema or {}).get("properties") or {})
    }

    assert with_lines == analytics.FILE_READ_TOOLS
