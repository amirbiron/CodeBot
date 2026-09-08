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

The gate has three layers:

1. ``enable_conversation_id`` stays off. ``report_missing`` is on: it adds one
   virtual ``get_more_tools`` tool the agent calls to say which capability it
   wishes existed, and it changes none of the existing tools. ``context`` is
   **on**, and it is the one option here that does change what the server
   advertises — see :func:`instrument_mcp_server` for what it costs and what it
   buys.
2. ``before_send`` on the ``Posthog`` client keeps an **allowlist** of
   ``$mcp_*`` properties. Deleting the known payload keys would be a blocklist,
   and the MCP SDK is pre-1.0: a payload property added in a future release
   would ship before anyone thought to extend the list. An allowlist drops the
   unknown key instead of forwarding it. Two of the allowlisted properties are
   agent- or library-written free text rather than server metadata, so they sit
   in their own set and are admitted **only when the value is a string** — a
   dict or a list under the same name is a whole structure, and it travels
   whole.
3. Every ``$exception_list[*].value`` is replaced, on **every** event. Two
   separate routes end there. The sibling event that rides along with a failed
   tool call carries the *full* exception chain, while ``$mcp_error_message``
   carries only the primary entry the SDK already truncated to 2,048
   characters. And ``enable_exception_autocapture`` hooks ``sys.excepthook`` /
   ``threading.excepthook``, so an uncaught exception anywhere in the process —
   the repo-autosync daemon, a pymongo error naming a file — arrives as a plain
   ``$exception`` with no ``$mcp_*`` key to key off. This client serves only
   this server, so the rule is unconditional.

**What still never leaves, and what now does.** ``$mcp_parameters`` (on a write
tool, the file itself) and ``$mcp_response`` (file bodies, sticky notes,
mirrored documents) are blocked on every event, with no exception and no
discriminator that can open them. What *is* forwarded is two free-text fields
whose exposure was accepted deliberately by the project owner, not derived:

* ``$mcp_intent`` — the sentence the agent writes about what it is trying to
  do. Agent-authored, and the parameter's own description tells the agent to
  keep content and credentials out of it. That instruction is guidance to a
  model, not an enforced boundary.
* ``$mcp_error_message`` — the failed call's primary exception message, for
  **every** error type rather than only ``ValidationError`` as before. Measured
  costs, so nobody has to rediscover them: Pydantic renders the rejected
  ``input_value`` into a validation message and keeps its head *and* its tail
  around a 50-character cap, so a secret at either end of the input travels
  whole; on a missing required field it reports the entire arguments object.
  Beyond Pydantic, a library exception that escapes a tool arrives here too —
  a pymongo failure can name the queried title, an OS error can name a path.
  The tool bodies in ``repo_backend.py`` catch broadly and return
  ``{"ok": False, "error": ...}`` rather than raising, which is what keeps this
  narrow in practice; that is a property of today's code, not a guarantee of
  the gate.

Both of those strings are then run through
:func:`mcp_server.redaction.redact_secrets` — the **same** pattern list that
filters the agent primer, imported rather than re-implemented. Inventing a
second sanitizer for free text is what fails silently (see
``amir-bug-patterns``, ``secret-in-derived-text``): when each sink kept its own
list, a pattern was added to one and forgotten in the other.

**What that filter buys, measured — and what it does not.** Every known secret
*shape* is caught anywhere in the string, mid-message included: an AWS key in
the tail of a Pydantic ``input_value``, ``ghp_``, ``ckmcp_``, ``sk-``, a JWT, a
``Bearer`` header, a ``scheme://user:pass@host`` connection string. What it
does **not** catch is the name-based rule (``API_KEY=…``) when the assignment
sits mid-line, because that rule is anchored to the start of a line — and a
Pydantic message is one long line. That anchor protects the primer from having
``key=value`` deleted out of prose. So this is a real reduction in exposure and
**not** a guarantee: the fields above are still free text, and the paragraph
about what they can carry still stands.

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

from .redaction import redact_secrets

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

#: ``$mcp_intent_source`` — מאיפה הגיעה הכוונה, לא מה היא אמרה.
#:
#: תווית סגורה שה-SDK כותב בעצמו, ולכן היא נאכפת מול הערכים שלו ולא מתקבלת
#: כמחרוזת חופשית. הערכים נקראו מ-``posthog.mcp._intent``:
#: ``context_parameter`` כשהסוכן העביר ``context``, ו-``inferred`` כש-
#: ``intent_fallback`` גזר אותה (כבוי כאן, ונשמר כדי שהדלקתו לא תשתיק את
#: השדה).
#:
#: **למה לא ברשימת המטא-דאטה הרגילה.** שם כל ערך עובר בלי בדיקת טיפוס, וזה
#: נכון לשדות שה-SDK מייצר כמספר או כבוליאני. כאן השדה אמור להיות אחת משתי
#: מילים, ומבנה שיגיע תחתיו במהדורה עתידית היה עובר שלם — אותו חור בדיוק
#: שכבר נמדד ב-``$mcp_error_message``, רק בשם אחר.
_ALLOWED_INTENT_SOURCES = frozenset({"context_parameter", "inferred"})

#: Allowed like the set above, **but only when the value is a string** — and the
#: string is run through :func:`~mcp_server.redaction.redact_secrets` first.
#:
#: These two are the free text the gate forwards on purpose: the sentence an
#: agent wrote, and the message a failed call raised. The type check is not
#: decoration. It was measured: a dict sent under ``$mcp_error_message`` — and
#: the same under ``$mcp_intent`` — passed an earlier version of this gate with
#: a file body nested inside it. "A sentence a human reads" is the whole
#: justification for admitting them, and a dict or a list is not that sentence;
#: it is a structure, and a structure travels whole.
#:
#: They are kept in their own set rather than folded into
#: ``_ALLOWED_MCP_PROPERTIES`` so neither the string rule nor the redaction can
#: be lost by someone moving a name between lines. What the two of them cost is
#: written out in the module docstring, in measurements rather than adjectives.
_ALLOWED_FREE_TEXT_PROPERTIES = frozenset(
    {
        "$mcp_error_message",
        "$mcp_intent",
    }
)

#: The description of the injected ``context`` parameter, as the agent reads it.
#:
#: Replaces the SDK's default, which is seven lines long, repeats itself, and
#: shouts ``YOU MUST provide 15-25 words (count carefully)`` — schema text that
#: is served with **every** tool this server advertises. Short is not the only
#: goal: this string is also the one place an agent is ever told what must not
#: go into a field whose contents now reach PostHog verbatim. That last line is
#: guidance to a model, not a boundary the server enforces, and the gate is
#: written on the assumption that it can be ignored.
_CONTEXT_DESCRIPTION = (
    "One short sentence, in the third person, on what this call is for — "
    "roughly 10 to 20 words. It is recorded for usage analytics only and never "
    "changes the result. Never put file contents, credentials, tokens or "
    "personal data in it."
)

# Blocked on every event, with no discriminator anywhere in this module that can
# open them. Named here so the reason is on the record rather than inferred from
# an absence:
#   $mcp_parameters  the tool arguments — on save/edit/append they *are* the file
#   $mcp_response    the tool result — file bodies, sticky notes, documents
# The list is documentation. The two allowlists above are what actually decide,
# and a test keeps this set disjoint from both of them.
_PAYLOAD_PROPERTIES = frozenset(
    {
        "$mcp_parameters",
        "$mcp_response",
    }
)

# ---------------------------------------------------------------------------
# מאפיין משלנו: באיזה **מצב קריאה** רצה קריאת קובץ
# ---------------------------------------------------------------------------
#
# ``outline=true`` ו-``lines=[5, 80]`` הן אותו כלי, ולכן הדשבורד סופר אותן
# באותה עמודה — בזמן שהן הפוכות במשמעות: אאוטליין הוא מפה זולה, וקריאת תוכן
# היא הניווט היקר שהמפה באה להחליף. עמודה שסופרת את שתיהן יחד לא יכולה להראות
# שהאחת החליפה את השנייה, וזה בדיוק המדד שהעמוד נבנה כדי למדוד.
#
# **למה מאפיין נגזר ולא הפרמטרים עצמם.** ההבחנה חיה ב-``$mcp_parameters``,
# והוא חסום — ונשאר חסום, כי בכלי הכתיבה הוא הקובץ עצמו. לכן במקום לפתוח את
# הארגומנטים, השרת מחשב בעצמו **תווית אחת מתוך קבוצה סגורה** ושולח אותה. מה
# שיוצא הוא המילה ``outline``, ``range`` או ``full`` — לעולם לא ערך שהגיע
# מהקורא. הנגזרת נשענת על **נוכחות** הפרמטר, לא על תוכנו.
CK_READ_MODE_KEY = "ck_read_mode"
READ_MODE_OUTLINE = "outline"
READ_MODE_RANGE = "range"
READ_MODE_FULL = "full"

#: הקבוצה הסגורה שהשער אוכף. מאפיין משלנו אינו נושא את התחילית ``$mcp_``
#: ולכן רשימת ההיתר שלמעלה אינה חלה עליו — בלי האכיפה הזו היה כאן שם שדרכו
#: אפשר לשלוח כל מחרוזת, כלומר בדיוק החור שהשער קיים כדי לסגור. באג בקולבק
#: שיחזיר משהו אחר מפיל את הערך, לא מעביר אותו.
_ALLOWED_CUSTOM_PROPERTIES: dict[str, frozenset[str]] = {
    CK_READ_MODE_KEY: frozenset({READ_MODE_OUTLINE, READ_MODE_RANGE, READ_MODE_FULL}),
}

#: שני הכלים שמקבלים ``lines``, ורק הם.
#:
#: **הרשימה משוכפלת כאן ולא מיובאת מ-``server.py``, וזו הגבלה אמיתית ולא
#: העדפה:** ``server.py`` מייבא את המודול הזה, וייבוא הפוך היה מעגלי. שמות
#: הכלים עצמם הם מחרוזות בתוך המעטרים ``@mcp.tool(name=...)``, ולהוציא אותם
#: למודול קבועים פירושו לגעת בכל הרשמות הכלים — שינוי רחב בהרבה ממה שהמדד
#: הזה מצדיק, ובמשטח שטעות הקלדה בו שוברת כלי בפרודקשן.
#:
#: **מה שסוגר את הפער הוא אכיפה, לא זיכרון:**
#: ``test_the_file_read_tool_names_still_match_the_registered_tools`` בונה שרת
#: אמיתי, שואל אילו כלים מצהירים על ``lines`` בסכימה שלהם, ומשווה לקבוצה כאן.
#: הוא נגזר ממקור האמת ולא מרשימה שנייה קשיחה, ולכן שינוי שם כלי מפיל אותו
#: ברעש. בלעדיו הכשל היה שקט לגמרי: הטבלה ב-``/admin/mcp`` הייתה ממשיכה
#: להיטען, פשוט עם אפסים בשתי העמודות החדשות.
#:
#: אותה מוסכמה שכבר קיימת בין ``outline.py`` ל-``backend.py``.
FILE_READ_TOOLS = frozenset({"codekeeper_get_file", "codekeeper_get_repo_file"})

_TOOL_CALL_METHOD = "tools/call"
_MCP_PROPERTY_PREFIX = "$mcp_"
_EXCEPTION_LIST_KEY = "$exception_list"
_INTENT_SOURCE_KEY = "$mcp_intent_source"
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


def read_mode_properties(
    request: Any, extra: Any = None
) -> Optional[dict[str, str]]:
    """``event_properties`` callback: tag a file read with **how** it read.

    Returns ``{"ck_read_mode": "outline" | "range" | "full"}`` for a
    ``tools/call`` on one of :data:`FILE_READ_TOOLS`, and ``None`` for
    everything else. That ``None`` is the interesting half. The SDK runs this
    callback on *every* auto-captured event — ``$mcp_initialize`` and
    ``$mcp_tools_list`` included — and a version that fell through to ``full``
    stamped a read mode on the handshake too (measured against
    ``posthog 7.45.3``). Those events would then have been counted as full file
    reads, so the column built to prove that ``outline`` replaced content reads
    would have been inflated by traffic that read no file at all.

    **Only presence is read, never a value.** ``lines`` carries line numbers and
    ``outline`` carries a flag, and neither is echoed: the return value is one
    of three literals defined in this module, and the gate rejects anything
    else. This is what makes the split possible while ``$mcp_parameters`` stays
    blocked.

    ``outline`` is checked first, so a call passing both — which the tool
    rejects as ``outline_and_lines`` — is counted as an outline read. That call
    reads no content either way, so the cheap column is the honest place for it.

    Never raises. ``resolve_event_properties`` in the SDK would swallow an
    exception here anyway, but analytics must not depend on someone else's
    error handling to stay off the tool path.
    """
    try:
        if not isinstance(request, dict) or request.get("method") != _TOOL_CALL_METHOD:
            return None
        params = request.get("params")
        if not isinstance(params, dict) or params.get("name") not in FILE_READ_TOOLS:
            return None
        arguments = params.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {}
        if arguments.get("outline"):
            return {CK_READ_MODE_KEY: READ_MODE_OUTLINE}
        if arguments.get("lines") is not None:
            return {CK_READ_MODE_KEY: READ_MODE_RANGE}
        return {CK_READ_MODE_KEY: READ_MODE_FULL}
    except Exception:
        logger.warning("read_mode_properties failed; the event ships without it", exc_info=True)
        return None


def scrub_mcp_payload(event: dict) -> Optional[dict]:
    """``before_send`` hook: decide, key by key, what this client may send.

    Three rules, applied to every event:

    * a ``$mcp_*`` property survives only if it is on one of the two allowlists,
      and the free-text one additionally requires the value to be a string;
    * a property of ours (:data:`_ALLOWED_CUSTOM_PROPERTIES`) survives only if
      its value is one of the literals declared for it;
    * an ``$exception_list`` message is always replaced.

    "Every event" is load-bearing. ``enable_exception_autocapture`` installs
    ``sys.excepthook`` and ``threading.excepthook``, so an uncaught exception in
    any thread of this process — the repo-autosync daemon, say — is captured as
    a plain ``$exception`` carrying no ``$mcp_*`` property at all. An earlier
    version of this hook only looked at MCP events, and a raised
    ``RuntimeError("mongo query failed for <file name>")`` reached the wire
    intact through that gap.

    ``$mcp_parameters`` and ``$mcp_response`` are blocked here on every event,
    with no discriminator that can reopen them, so nothing above becomes a way
    to read a call's arguments or its result. The two free-text properties that
    *are* forwarded, and the measured cost of forwarding them, are set out in
    the module docstring.

    Fails **closed**: any error while scrubbing drops the event rather than
    letting an unscrubbed one continue. The posthog client also drops an event
    whose ``before_send`` raises (``Client._enqueue``), but a redaction path
    must not depend on someone else's error handling for its guarantee.
    """
    try:
        properties = event.get("properties")
        if not isinstance(properties, dict):
            return event

        kept: dict = {}
        for key, value in properties.items():
            if isinstance(key, str) and key.startswith(_MCP_PROPERTY_PREFIX):
                if key in _ALLOWED_MCP_PROPERTIES:
                    pass
                elif key == _INTENT_SOURCE_KEY:
                    # תווית סגורה, לא טקסט חופשי — ראו ``_ALLOWED_INTENT_SOURCES``.
                    #
                    # ``isinstance`` לפני ההשוואה, מאותה סיבה בדיוק שבמאפיין
                    # שלנו למטה: ``value in frozenset`` על מילון או רשימה זורק
                    # ``TypeError`` (טיפוס לא בר-גיבוב), וזה היה מפיל את ה-hook
                    # ומוחק את **כל** האירוע במקום להפיל מפתח אחד. בטוח, אבל
                    # רועש ומיותר. הטסט על מילון תפס את זה.
                    if not isinstance(value, str) or value not in _ALLOWED_INTENT_SOURCES:
                        continue
                elif key in _ALLOWED_FREE_TEXT_PROPERTIES and isinstance(value, str):
                    # **מה שנכנס דרך רשימת הטקסט החופשי חייב להיות מחרוזת.**
                    # שני השדות האלה מוצדקים כ"משפט שאדם קורא": המשפט של
                    # הסוכן, והודעת השגיאה. מילון או רשימה תחת אותו שם אינם
                    # המשפט הזה — הם מבנה שלם, והוא עובר שלם.
                    #
                    # זה נמדד: ``$mcp_error_message`` כמילון שמכיל גוף קובץ
                    # עבר גרסה קודמת של השער עם התוכן בפנים, וכך גם
                    # ``$mcp_intent``. הבדיקה דאז אימתה את ה**מבחין** ולא את
                    # מה שנמסר בפועל — כלומר בדקה מי מבקש, ולא מה עובר.
                    #
                    # **ואז מסננים סודות.** אותה רשימת דפוסים שמסננת את הפריימר
                    # (``mcp_server.redaction``), ולא רג'קס שהומצא כאן: סניטציה
                    # מקומית על טקסט חופשי היא בדיוק מה שנכשל בשקט
                    # (``amir-bug-patterns``, ``secret-in-derived-text``). מה
                    # שהיא תופסת ומה שלא — נמדד, וכתוב ב-``redact_secrets``.
                    # היא מצמצמת חשיפה; היא אינה הופכת את השדות האלה לבטוחים.
                    value = redact_secrets(value)
                else:
                    continue
            elif key in _ALLOWED_CUSTOM_PROPERTIES:
                # מאפיין שהשרת הזה מחשב בעצמו. הוא אינו נושא את התחילית
                # ``$mcp_``, ולכן רשימת ההיתר שלמעלה לא הייתה נוגעת בו והוא
                # היה עובר כל ערך — שם שדרכו אפשר לשלוח מחרוזת חופשית.
                #
                # ``isinstance`` לפני ההשוואה אינו קישוט: ``value in frozenset``
                # על מילון או רשימה זורק ``TypeError`` (טיפוס לא בר-גיבוב), מה
                # שהיה מפיל את ה-hook כולו ומוחק את האירוע. בטוח, אבל רועש
                # ומיותר — כאן פשוט מפילים את המפתח.
                if not isinstance(value, str) or value not in _ALLOWED_CUSTOM_PROPERTIES[key]:
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
    """Wrap the MCP server so tool calls are captured. Idempotent.

    Must run **before** ``streamable_http_app()`` is built: ``instrument()``
    also wraps that factory, to carry one ``$session_id`` across a stateless
    deployment.

    **This is no longer purely additive, and that is the point.** ``context=True``
    makes the SDK add a ``context`` string to every tool's advertised input
    schema and to its ``required`` list. Measured against ``mcp 1.28.1`` +
    ``posthog 7.45.3`` on this server's FastMCP path: a call that omits
    ``context`` is **not** rejected — the tool runs exactly as before and the
    injected argument never reaches the tool body — so no existing client
    breaks; what changes is what the tool listing advertises, and that agents
    are asked for a sentence they were not asked for before.

    What it buys is the whole intent layer. Without it ``posthog.mcp._intent``
    resolves an intent only for ``get_more_tools``, so ``$mcp_intent`` exists on
    one rare event and the ``/admin/mcp`` tables stay pure numbers: which
    session made 15 calls, never what it was trying to do. Opening the property
    in the gate alone would have changed nothing, because nothing was producing
    it.
    """
    global _ANALYTICS

    if _CLIENT is None:
        _report_missing_configuration()
        return

    try:
        from posthog.mcp import instrument
        from posthog.mcp.types import MCPAnalyticsContextOptions, MCPAnalyticsOptions
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
                # Intent capture. The description is ours rather than the SDK's
                # default for two reasons: the default is a seven-line block
                # that shouts "YOU MUST provide 15-25 words (count carefully)",
                # which is a lot of schema for every one of this server's tools;
                # and this text is the only place an agent is told what not to
                # put in a field that now reaches PostHog.
                context=MCPAnalyticsContextOptions(description=_CONTEXT_DESCRIPTION),
                # Registers a virtual `get_more_tools` tool so an agent can
                # report a capability this server does not offer. Additive to
                # the listing; it touches no existing tool.
                report_missing=True,
                # Adds a `conversation_id` argument *and* appends an instruction
                # to every tool result asking the agent to echo it back. The
                # result text is the tool's contract with its caller, and
                # analytics does not get to edit it.
                enable_conversation_id=False,
                # Splits `outline=true` from a content read without opening
                # `$mcp_parameters`. See :func:`read_mode_properties`.
                event_properties=read_mode_properties,
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
