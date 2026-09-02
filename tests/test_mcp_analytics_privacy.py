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


def test_payload_properties_are_not_in_the_default_allowlist():
    """The two sets stay disjoint, so nothing payload-bearing ships by default.

    Named for what it actually proves. It used to be called "never allowlisted",
    which stopped being true once ``_ALLOWED_BY_EVENT`` admitted ``$mcp_intent``
    on one event — the assertion still passed, because that exception lives in a
    separate mapping, so the name promised more than the check delivered. The
    conditional exception is pinned by the tests below instead.
    """
    assert not (analytics._ALLOWED_MCP_PROPERTIES & analytics._PAYLOAD_PROPERTIES)


def test_the_only_per_event_exception_is_the_intent_on_missing_capability():
    """Pins the whole exception table, so adding a second one is a deliberate act.

    A new entry here widens the privacy gate, and the widening would otherwise
    be invisible in review — this test makes it show up as a failing assertion.
    """
    assert analytics._ALLOWED_BY_EVENT == {
        "$mcp_missing_capability": frozenset({"$mcp_intent", "$mcp_intent_source"})
    }


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


def test_intent_is_still_blocked_on_an_ordinary_tool_call():
    """The security boundary of the exception: it is scoped to one event name.

    On this server a regular tool call cannot even produce an intent —
    ``posthog.mcp._intent`` resolves one only when ``context`` is enabled or an
    ``intent_fallback`` is set, and both are off. This test holds the line
    anyway, so turning ``context`` on later cannot quietly start shipping the
    agent's free text on every single call.
    """
    scrubbed = analytics.scrub_mcp_payload(
        _tool_call_event(**{"$mcp_intent": "read the user's private notes", "$mcp_intent_source": "context_parameter"})
    )

    properties = scrubbed["properties"]
    assert "$mcp_intent" not in properties
    assert "$mcp_intent_source" not in properties
    assert properties["$mcp_tool_name"] == "codekeeper_get_file"


def test_a_lookalike_event_name_does_not_inherit_the_exception():
    """The key is the exact event name, not a prefix or a substring."""
    for name in ("$mcp_missing_capability_v2", "mcp_missing_capability", "$mcp_tools_list"):
        event = _missing_capability_event()
        event["event"] = name

        scrubbed = analytics.scrub_mcp_payload(event)

        assert "$mcp_intent" not in scrubbed["properties"], name


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


# ---------------------------------------------------------------------------
# החריג השני: הודעת שגיאה על ``ValidationError`` בלבד
#
# החריג הזה שונה מהראשון בכך שהוא **כן** עלול לשאת קטע מתוכן המשתמש: Pydantic
# מרנדר את ``input_value`` לתוך ההודעה, מקצץ ל-50 תווים, ושומר ראש וזנב. זה
# נמדד והתקבל במודע. מה שהטסטים כאן שומרים הוא **ההיקף**: סוג שגיאה אחד,
# מפתח אחד, ובכל מצב אחר — חסום.
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


def test_the_whole_error_type_exception_table_is_pinned():
    """הרחבה של הטבלה הזו מרחיבה את השער, ולכן היא חייבת להיות מעשה מודע.

    בלי הקיבוע, סוג שגיאה נוסף היה נכנס בשקט בביקורת קוד.
    """
    assert analytics._ALLOWED_BY_ERROR_TYPE == {
        "ValidationError": frozenset({"$mcp_error_message"})
    }


def test_a_validation_error_message_reaches_posthog():
    """המטרה של החריג: לראות **איזה שדה** נדחה, ולא רק שמשהו נדחה."""
    out = analytics.scrub_mcp_payload(_failed_tool_call("ValidationError"))

    assert out["properties"]["$mcp_error_message"] == _VALIDATION_MESSAGE
    assert "file_name" in out["properties"]["$mcp_error_message"]


def test_a_runtime_error_message_is_still_blocked():
    """``RuntimeError`` הוא הסוג שכבר עקף את השער פעם אחת.

    בגרסה מוקדמת של ה-hook, ``RuntimeError("mongo query failed for <file>")``
    הגיע לרשת שלם. החריג החדש הוא לפי סוג, ולכן הוא בדיוק המקום שבו הטעות
    הזו יכולה לחזור.
    """
    out = analytics.scrub_mcp_payload(
        _failed_tool_call("RuntimeError", "mongo query failed for notes.py")
    )

    assert "$mcp_error_message" not in out["properties"]
    assert "notes.py" not in _payload_text(out)


@pytest.mark.parametrize(
    "error_type",
    ["ValueError", "TypeError", "KeyError", "ToolError", "Exception", ""],
)
def test_no_other_error_type_opens_the_message(error_type):
    out = analytics.scrub_mcp_payload(_failed_tool_call(error_type))

    assert "$mcp_error_message" not in out["properties"]


@pytest.mark.parametrize(
    "error_type",
    ["validationerror", "VALIDATIONERROR", " ValidationError", "ValidationError "],
)
def test_the_match_is_exact_and_not_fuzzy(error_type):
    """התאמה לפי שוויון מדויק. ``in`` או ``lower()`` היו פותחים שמות שכנים."""
    out = analytics.scrub_mcp_payload(_failed_tool_call(error_type))

    assert "$mcp_error_message" not in out["properties"]


def test_a_missing_error_type_blocks_the_message():
    """נכשל-סגור: בלי מבחין אין היתר."""
    event = _failed_tool_call("ValidationError")
    del event["properties"]["$mcp_error_type"]

    out = analytics.scrub_mcp_payload(event)

    assert "$mcp_error_message" not in out["properties"]


@pytest.mark.parametrize("error_type", [None, 42, 3.5, True, ["ValidationError"], {"a": 1}])
def test_a_non_string_error_type_blocks_the_message(error_type):
    """טיפוס לא צפוי חוסם — **ואינו מפיל את ה-hook**.

    רשימה ומילון אינם בני-גיבוב; חיפוש ישיר שלהם במילון היה זורק
    ``TypeError``, מה שהיה מוחק את האירוע כולו. בטוח, אבל רועש ומיותר.
    """
    out = analytics.scrub_mcp_payload(_failed_tool_call(error_type))

    assert out is not None
    assert "$mcp_error_message" not in out["properties"]


def test_the_exception_does_not_reopen_parameters_or_response():
    """הדרישה המפורשת: ``$mcp_parameters`` חסום גם על האירוע הזה.

    אחרת החריג היה הופך לדלת אחורית לקריאת הארגומנטים — כלומר לקובץ עצמו.
    """
    out = analytics.scrub_mcp_payload(_failed_tool_call("ValidationError"))

    assert "$mcp_parameters" not in out["properties"]
    assert "$mcp_response" not in out["properties"]
    assert _FILE_BODY not in _payload_text(out)


def test_the_error_type_exception_is_keyed_on_the_type_and_not_on_the_event():
    """המבחין הוא סוג השגיאה בלבד, בכל אירוע — וזה מה שהטסט הזה מקבע.

    **השם הקודם של הטסט הזה שיקר.** הוא נקרא
    ``..._does_not_leak_into_other_events`` בזמן שהאסרשן שלו אישר בדיוק את
    ההפך: שההודעה **כן** עוברת על ``$mcp_missing_capability``. זה אותו דפוס
    שכבר תוקן בקובץ הזה פעם אחת — טסט שמבטיח יותר ממה שהוא בודק — ובגרסה
    ההיא לפחות האסרשן היה נכון והשם היה רחב מדי. כאן השם אמר את ההפך
    מהאסרשן, וזה גרוע יותר: קורא שסורק שמות היה מסיק שיש גידור שאין.

    ההתנהגות עצמה מכוונת ותואמת למפרט: ``$mcp_error_message`` נפתח לפי
    ``$mcp_error_type`` **בלבד**, בלי תנאי נוסף על שם האירוע. שגיאת ולידציה
    על ``get_more_tools`` היא עדיין שגיאת ולידציה, ואותו ערך אבחוני.

    צמצום לאירוע ``$mcp_tool_call`` בלבד הוא שינוי מפרט, לא תיקון באג, ולכן
    הוא לא נעשה כאן בשקט.
    """
    event = _missing_capability_event(
        **{"$mcp_error_type": "ValidationError", "$mcp_error_message": "field required"}
    )

    out = analytics.scrub_mcp_payload(event)

    assert out["properties"]["$mcp_error_message"] == "field required"


# ---------------------------------------------------------------------------
# מה שנכנס דרך חריג חייב להיות מחרוזת
#
# החריגים פותחים שדות שההצדקה שלהם היא "משפט שאדם קורא". מילון או רשימה תחת
# אותו שם אינם המשפט הזה — הם מבנה שלם שעובר שלם. הבדיקה הקודמת אימתה את
# **המבחין** ולא את מה שנמסר, כלומר בדקה מי מבקש ולא מה עובר.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        {"loc": ["file_name"], "input": _FILE_BODY},
        [{"input": _FILE_BODY}],
        {"nested": {"deeper": _FILE_BODY}},
    ],
)
def test_a_structured_error_message_does_not_ride_the_exception(message):
    """נמדד לפני התיקון: מילון תחת ``$mcp_error_message`` עבר עם התוכן בפנים."""
    out = analytics.scrub_mcp_payload(_failed_tool_call("ValidationError", message))

    assert "$mcp_error_message" not in out["properties"]
    assert _FILE_BODY not in _payload_text(out)


@pytest.mark.parametrize("message", [None, 42, True, 3.5])
def test_a_non_string_error_message_is_dropped_even_on_a_validation_error(message):
    out = analytics.scrub_mcp_payload(_failed_tool_call("ValidationError", message))

    assert "$mcp_error_message" not in out["properties"]


@pytest.mark.parametrize(
    "intent",
    [{"text": _FILE_BODY}, [_FILE_BODY], None, 42],
)
def test_the_same_rule_guards_the_older_intent_exception(intent):
    """אותו חור בדיוק היה גם בחריג של ``$mcp_intent``, שנשלח ב-#3315.

    תיקון של החדש בלבד היה משאיר את הישן פתוח — כלומר טלאי, לא שורש.
    """
    event = _missing_capability_event(**{"$mcp_intent": intent})

    out = analytics.scrub_mcp_payload(event)

    assert "$mcp_intent" not in out["properties"]
    assert _FILE_BODY not in _payload_text(out)


def test_a_plain_sentence_still_passes_through_both_exceptions():
    """הכלל מצמצם ולא סוגר: מה שהחריגים נועדו לו ממשיך לעבור.

    בלי הטסט הזה, "לחסום הכל" היה עובר את כל השאר.
    """
    tool_call = analytics.scrub_mcp_payload(
        _failed_tool_call("ValidationError", "1 validation error\nfile_name")
    )
    missing = analytics.scrub_mcp_payload(_missing_capability_event())

    assert tool_call["properties"]["$mcp_error_message"] == "1 validation error\nfile_name"
    assert missing["properties"]["$mcp_intent"]


def test_the_exception_list_message_stays_redacted_even_on_validation_errors():
    """ההודעה מותרת; התאום שלה ב-``$exception_list`` נשאר מושחר.

    ההודעה עוברת מקוצצת ל-2,048 תווים בידי ה-SDK, בעוד ה-``$exception_list``
    נושא את השרשרת המלאה. פתיחת שניהם הייתה מרחיבה את החריג בלי שאיש ביקש.
    """
    event = _failed_tool_call("ValidationError")
    event["properties"]["$exception_list"] = [
        {"type": "ValidationError", "value": _FILE_BODY, "stacktrace": {"frames": []}}
    ]

    out = analytics.scrub_mcp_payload(event)

    assert out["properties"]["$mcp_error_message"] == _VALIDATION_MESSAGE
    assert _FILE_BODY not in _payload_text(out)


class _LooksLikeValidationError:
    """אינו מחרוזת, אבל ``str()`` שלו מחזיר בדיוק את שם הסוג המותר."""

    def __str__(self):  # pragma: no cover - נקרא רק אם המימוש שגוי
        return "ValidationError"

    __repr__ = __str__


def test_something_that_merely_prints_like_the_allowed_type_is_blocked():
    """הבדיקה חייבת להיות על **הטיפוס**, לא על הייצוג הטקסטואלי.

    זה הפער היחיד שמפריד בין ``isinstance(value, str)`` לבין ``str(value)``:
    לכל טיפוס לא צפוי אחר — ``None``, מספר, רשימה — שתי הגרסאות חוסמות
    ממילא, כי הייצוג שלהן אינו ``"ValidationError"``. מוטציה שהחליפה את
    ``isinstance`` ב-``str`` שרדה את כל שאר הטסטים, וזה מה שהיא פספסה:
    אובייקט שמדפיס את עצמו כשם המותר היה פותח את השער.

    ולא מדובר בהמצאה תיאורטית — ``StrEnum`` ו-wrappers של ספריות מדפיסים
    בדיוק כך, ו-``$mcp_error_type`` מגיע מ-SDK חיצוני.
    """
    out = analytics.scrub_mcp_payload(_failed_tool_call(_LooksLikeValidationError()))

    assert out is not None
    assert "$mcp_error_message" not in out["properties"]


def test_a_str_subclass_is_still_accepted():
    """הצד השני: תת-מחלקה של ``str`` היא מחרוזת, ואין סיבה לחסום אותה.

    בלי הטסט הזה, "תקן את מוטציה C" היה מזמין בדיקה נוקשה מדי
    (``type(value) is str``) שהייתה חוסמת ערך תקין לחלוטין.
    """

    class _StrEnumLike(str):
        pass

    out = analytics.scrub_mcp_payload(_failed_tool_call(_StrEnumLike("ValidationError")))

    assert out["properties"]["$mcp_error_message"] == _VALIDATION_MESSAGE
