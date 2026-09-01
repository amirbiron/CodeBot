"""PostHog MCP analytics for the CodeKeeper MCP server.

``posthog.mcp.instrument(server, client)`` auto-captures a ``$mcp_*`` event for
every tool call, tool listing and handshake. The instrumentation itself is one
line; everything else in this module is the **privacy gate** around it.

Why a gate is needed here specifically: on this server the tool arguments and
the tool results *are* the user's content. ``codekeeper_get_file`` returns a
file body, ``codekeeper_save_file`` receives one, and sticky notes and mirrored
documents run through the same tools. The SDK's own sanitizer redacts sensitive
**keys** by name and binary blobs — it does not, and does not claim to, keep
file content out of an event.

Three layers, all fail-closed:

1. ``context`` and ``enable_conversation_id`` stay off, so the SDK never
   injects an argument into an existing tool's schema. ``report_missing`` is
   on, and it is the one thing the server advertises that it did not before: a
   virtual ``get_more_tools`` the agent can call to say which capability it
   wishes existed. It adds a tool to the listing; it changes none of the
   existing ones.
2. ``before_send`` on the ``Posthog`` client keeps an **allowlist** of
   ``$mcp_*`` properties. Deleting the three known payload keys would be a
   blocklist, and the MCP SDK is pre-1.0: a payload property added in a future
   release would ship before anyone thought to extend the list. An allowlist
   drops the unknown key instead of forwarding it. ``_ALLOWED_BY_EVENT`` holds
   its single, per-event exception.
3. Every ``$exception_list[*].value`` is replaced, on **every** event. Two
   separate routes end there. The sibling event that rides along with a failed
   tool call carries the same free text that ``$mcp_error_message`` is *read
   from*, so removing only that key would move the leak one key over. And
   ``enable_exception_autocapture`` hooks ``sys.excepthook`` /
   ``threading.excepthook``, so an uncaught exception anywhere in the process —
   the repo-autosync daemon, a pymongo error naming a file — arrives as a plain
   ``$exception`` with no ``$mcp_*`` key to key off. This client serves only
   this server, so the rule is unconditional.

A missing or broken PostHog configuration never takes the server down: in
production analytics simply does not run, and only a development/debug
environment fails loudly.
"""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

ENV_PROJECT_TOKEN = "POSTHOG_PROJECT_TOKEN"
ENV_HOST = "POSTHOG_HOST"

# Verbatim from the PostHog framework rules: a missing key must never be a
# silent no-op in development, because "no events" and "analytics disabled"
# look identical from the outside.
_MISSING_CONFIG_TEMPLATE = (
    "{var} variable required by PostHog is missing or un-configured, this causes "
    "events to be silently missed. This error stops appearing once {var} is configured"
)

# ``$mcp_*`` properties allowed onto the wire. Every name here was read off
# ``posthog.mcp.constants.PostHogMCPAnalyticsProperty`` and is server- or
# protocol-side metadata: a name, a version, a duration, a boolean or an id.
# Anything else carrying the ``$mcp_`` prefix is dropped — including a property
# a future SDK release adds that nobody here has seen yet.
_ALLOWED_MCP_PROPERTIES = frozenset(
    {
        "$mcp_source",
        "$mcp_client_name",
        "$mcp_client_version",
        "$mcp_client_user_agent",
        "$mcp_vendor_client",
        "$mcp_protocol_version",
        "$mcp_conversation_id",
        "$mcp_duration_ms",
        "$mcp_is_error",
        "$mcp_error_type",
        "$mcp_listed_tool_names",
        "$mcp_resource_name",
        "$mcp_server_name",
        "$mcp_server_version",
        "$mcp_tool_category",
        "$mcp_tool_description",
        "$mcp_tool_name",
    }
)

# Not allowlisted by default, and named here only so the reason is on the record
# rather than inferred from an absence:
#   $mcp_parameters     the tool arguments — on save/edit/append they *are* the file
#   $mcp_response       the tool result — file bodies, sticky notes, documents
#   $mcp_error_message  free text from a failed tool
#   $mcp_intent         agent-narrated free text (with $mcp_intent_source), which
#                       ``_ALLOWED_BY_EVENT`` below re-admits on exactly one event
# The list is documentation. The allowlist above is what actually decides.
_PAYLOAD_PROPERTIES = frozenset(
    {
        "$mcp_parameters",
        "$mcp_response",
        "$mcp_error_message",
        "$mcp_intent",
        "$mcp_intent_source",
    }
)

# The one exception to the allowlist, admitted per event name.
#
# ``report_missing`` advertises a virtual ``get_more_tools`` tool so an agent can
# say which capability it wishes this server had. That sentence *is* the event —
# the SDK puts it in ``$mcp_intent`` and leaves ``$mcp_parameters`` empty
# (measured: ``arguments: {}``). Blocked, the event degrades to a counter with no
# reason, which is the same as not having the feature.
#
# The scope is tight by construction, not by care: ``posthog.mcp._intent`` only
# resolves an intent when ``options.context`` is enabled or an ``intent_fallback``
# is set. Both are off here, so ``get_more_tools`` is the only producer of
# ``$mcp_intent`` on this server, and a regular ``$mcp_tool_call`` still cannot
# carry one. ``$mcp_parameters`` stays blocked even on this event.
_ALLOWED_BY_EVENT: dict[str, frozenset[str]] = {
    "$mcp_missing_capability": frozenset({"$mcp_intent", "$mcp_intent_source"}),
}

_MCP_PROPERTY_PREFIX = "$mcp_"
_EXCEPTION_LIST_KEY = "$exception_list"
_EXCEPTION_VALUE_PLACEHOLDER = (
    "[redacted by CodeKeeper: exception text is not sent to PostHog]"
)

_PRODUCTION_ENVIRONMENTS = ("production", "prod")


def _resolve_environment() -> str:
    """The deployment environment, using the same expression as the rest of the
    repo (``main.py``, ``webapp/app.py``, ``observability_otel.py``): unset means
    production, so tests and a bare production box both stay silent."""
    return (os.getenv("ENVIRONMENT") or os.getenv("ENV") or "production").strip().lower()


def _is_debug_environment() -> bool:
    """True anywhere that is not production, which is where a missing key
    should stop the boot instead of quietly disabling analytics."""
    return _resolve_environment() not in _PRODUCTION_ENVIRONMENTS


def _redact_exception_values(exception_list: Any) -> Any:
    """Replace the message on every ``$exception_list`` entry, keeping the type,
    the mechanism and the stack frames.

    An ``Error.__cause__`` chain arrives as further entries in the same list, so
    every entry is treated the same way. The frames are this repo's own source
    positions — local variables are only captured with
    ``capture_exception_code_variables``, which stays off (see
    :func:`_build_client`) — so error grouping still works on type + stack."""
    if not isinstance(exception_list, list):
        return exception_list
    redacted = []
    for entry in exception_list:
        if isinstance(entry, dict) and entry.get("value"):
            entry = {**entry, "value": _EXCEPTION_VALUE_PLACEHOLDER}
        redacted.append(entry)
    return redacted


def scrub_mcp_payload(event: dict) -> Optional[dict]:
    """``before_send`` hook: strip free text from every event this client sends.

    One rule, applied to everything: ``$mcp_*`` properties survive only if
    they are on the allowlist, and an ``$exception_list`` message is always
    replaced.

    The "everything" is load-bearing. ``enable_exception_autocapture`` installs
    ``sys.excepthook`` and ``threading.excepthook``, so an uncaught exception in
    any thread of this process — the repo-autosync daemon, say — is captured as
    a plain ``$exception`` carrying no ``$mcp_*`` property at all. An earlier
    version of this hook let those through, and a raised
    ``RuntimeError("mongo query failed for <file name>")`` reached the wire
    intact. This client serves only the MCP server, and everything that server
    touches is user content, so no free text leaves it by any route.

    Fails **closed**: any error while scrubbing drops the event rather than
    letting an unscrubbed one continue. The posthog client also drops an event
    whose ``before_send`` raises (``Client._enqueue``), but a redaction path
    must not depend on someone else's error handling for its guarantee.
    """
    try:
        properties = event.get("properties")
        if not isinstance(properties, dict):
            return event

        allowed = _ALLOWED_MCP_PROPERTIES | _ALLOWED_BY_EVENT.get(
            event.get("event"), frozenset()
        )

        kept: dict = {}
        for key, value in properties.items():
            if isinstance(key, str) and key.startswith(_MCP_PROPERTY_PREFIX):
                if key not in allowed:
                    continue
            elif key == _EXCEPTION_LIST_KEY:
                value = _redact_exception_values(value)
            kept[key] = value

        event["properties"] = kept
        return event
    except Exception:
        logger.warning(
            "PostHog before_send failed; dropping the event rather than sending it "
            "unscrubbed",
            exc_info=True,
        )
        return None


def _build_client() -> Any:
    """Construct the module-scope ``Posthog`` client, or ``None``.

    Never raises: an SDK constructor that throws at import time takes the whole
    ASGI app down with it, and analytics is not worth a boot failure. The loud
    development-time complaint about missing configuration lives in
    :func:`instrument_mcp_server`, at the point where events actually start
    going missing.
    """
    token = os.environ.get(ENV_PROJECT_TOKEN, "").strip()
    host = os.environ.get(ENV_HOST, "").strip()
    if not token or not host:
        return None

    try:
        from posthog import Posthog
    except Exception:
        logger.warning("posthog is not importable; MCP analytics disabled", exc_info=True)
        return None

    try:
        client = Posthog(
            token,
            host=host,
            before_send=scrub_mcp_payload,
            enable_exception_autocapture=True,
            # Passed explicitly even though False is the default: this one
            # captures local variables at the point an exception is raised, and
            # in this server those locals hold file content. A future default
            # flip must not turn it on behind our back.
            capture_exception_code_variables=False,
        )
    except Exception:
        logger.warning("PostHog client init failed; MCP analytics disabled", exc_info=True)
        return None

    # Long-running web service: uvicorn exits on SIGTERM and whatever is still
    # in the batch queue goes with it unless the client is drained.
    atexit.register(client.shutdown)
    return client


_CLIENT = _build_client()
_ANALYTICS: Any = None


def _report_missing_configuration() -> None:
    """Loud in development, a logged warning in production. Silence in both would
    make "analytics is off" indistinguishable from "analytics is broken"."""
    missing = [
        name
        for name in (ENV_PROJECT_TOKEN, ENV_HOST)
        if not os.environ.get(name, "").strip()
    ]
    if not missing:
        # Configured, but the client could not be built — already logged there.
        return
    message = "; ".join(_MISSING_CONFIG_TEMPLATE.format(var=name) for name in missing)
    if _is_debug_environment():
        raise RuntimeError(message)
    logger.warning(message)


def instrument_mcp_server(server: Any) -> None:
    """Wrap the MCP server so tool calls are captured. Additive and idempotent.

    Must run **before** ``streamable_http_app()`` is built: ``instrument()``
    also wraps that factory, to carry one ``$session_id`` across a stateless
    deployment.
    """
    global _ANALYTICS

    if _CLIENT is None:
        _report_missing_configuration()
        return

    try:
        from posthog.mcp import instrument
        from posthog.mcp.types import MCPAnalyticsOptions
    except Exception:
        logger.warning(
            "posthog.mcp is not importable; MCP analytics disabled", exc_info=True
        )
        return

    try:
        _ANALYTICS = instrument(
            server,
            _CLIENT,
            MCPAnalyticsOptions(
                # Intent capture adds a `context` argument to every tool's input
                # schema. That changes what this server advertises to its
                # clients, and the argument itself is agent free text.
                context=False,
                # Registers a virtual `get_more_tools` tool so an agent can
                # report a capability this server does not offer. This is the
                # only addition to the advertised tool list; the existing tools
                # and their schemas are untouched. The agent's sentence arrives
                # as `$mcp_intent`, which `_ALLOWED_BY_EVENT` admits on the
                # `$mcp_missing_capability` event only.
                report_missing=True,
                # Adds an optional `conversation_id` argument, plus an
                # instruction appended to tool results asking the agent to echo
                # it back. Same reason.
                enable_conversation_id=False,
                logger=lambda message: logger.info("posthog mcp: %s", message),
            ),
        )
    except Exception:
        logger.warning(
            "PostHog MCP instrumentation failed; the server runs without analytics",
            exc_info=True,
        )


async def _drain() -> None:
    """Await in-flight auto-captures, then push the client's queue out."""
    try:
        if _ANALYTICS is not None:
            await _ANALYTICS.flush()
        if _CLIENT is not None:
            # flush() blocks; keep it off the event loop even at shutdown.
            await asyncio.to_thread(_CLIENT.flush)
    except Exception:
        logger.warning("PostHog drain on shutdown failed", exc_info=True)


def attach_shutdown_drain(app: Any) -> None:
    """Drain analytics on ASGI shutdown, while the event loop is still alive.

    ``atexit`` alone is not enough. Auto-captures are scheduled as asyncio tasks
    on uvicorn's loop, and a task still pending when that loop closes never
    reaches ``capture()`` at all — so there is nothing in the queue for
    ``atexit`` to flush.

    ``FastMCP.streamable_http_app()`` builds its Starlette app with an explicit
    ``lifespan=``, and Starlette's ``Router`` then ignores ``on_shutdown``
    entirely, so wrapping the lifespan is the only seam. The wrapper adds a
    shutdown step and changes nothing about startup.
    """
    if _CLIENT is None:
        return

    router = getattr(app, "router", None)
    original = getattr(router, "lifespan_context", None)
    if original is None:
        logger.warning(
            "no lifespan on the ASGI app; PostHog events will drain via atexit only"
        )
        return

    @contextlib.asynccontextmanager
    async def _lifespan_with_drain(scope_app: Any):
        async with original(scope_app) as state:
            try:
                yield state
            finally:
                await _drain()

    router.lifespan_context = _lifespan_with_drain
