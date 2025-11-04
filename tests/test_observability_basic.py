import types
import sys
import os
import pytest

import observability as obs


def test_generate_request_id_length_and_uniqueness():
    a = obs.generate_request_id()
    b = obs.generate_request_id()
    assert isinstance(a, str) and isinstance(b, str)
    assert len(a) == 8 and len(b) == 8
    assert a != b


def test_bind_request_id_calls_structlog_bind(monkeypatch):
    called = {}

    def _bind_contextvars(**kwargs):
        called.update(kwargs)

    monkeypatch.setattr(obs.structlog.contextvars, "bind_contextvars", _bind_contextvars)
    monkeypatch.setattr(obs, "_set_sentry_tag", lambda *a, **k: None)
    obs.bind_request_id("abc12345")
    assert called.get("request_id") == "abc12345"


def test_emit_event_routes_to_severity_methods(monkeypatch):
    calls = {"info": [], "warning": [], "error": []}

    class _Logger:
        def info(self, **fields):
            calls["info"].append(fields)
        def warning(self, **fields):
            calls["warning"].append(fields)
        def error(self, **fields):
            calls["error"].append(fields)

    monkeypatch.setattr(obs.structlog, "get_logger", lambda: _Logger())

    obs.emit_event("evt_info", severity="info", a=1)
    obs.emit_event("evt_warn", severity="warn", b=2)
    obs.emit_event("evt_error", severity="error", c=3)

    assert calls["info"] and calls["info"][0]["event"] == "evt_info"
    assert calls["warning"] and calls["warning"][0]["event"] == "evt_warn"
    assert calls["error"] and calls["error"][0]["event"] == "evt_error"


def test_init_sentry_without_dsn_no_crash(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    obs.init_sentry()  # should not raise


def test_init_sentry_with_dsn_invokes_init(monkeypatch):
    # Prepare fake sentry_sdk and its logging integration
    sentry_mod = types.ModuleType("sentry_sdk")
    captured = {}
    def _init(**kwargs):
        captured.update(kwargs)
    sentry_mod.init = _init

    integ_mod = types.ModuleType("sentry_sdk.integrations.logging")
    class LoggingIntegration:
        def __init__(self, level=None, event_level=None):
            self.level = level
            self.event_level = event_level
    integ_mod.LoggingIntegration = LoggingIntegration

    sys.modules["sentry_sdk"] = sentry_mod
    sys.modules["sentry_sdk.integrations.logging"] = integ_mod

    monkeypatch.setenv("SENTRY_DSN", "https://example@sentry.io/1")

    obs.init_sentry()

    # Validate that init was called with our DSN and integration passed
    assert captured.get("dsn") == "https://example@sentry.io/1"
    integrations = captured.get("integrations") or []
    assert any(getattr(x, "event_level", None) is not None for x in integrations)


def test_recent_errors_buffer_and_getter(monkeypatch):
    import observability as obs
    # clear buffer
    try:
        obs._RECENT_ERRORS.clear()  # type: ignore[attr-defined]
    except Exception:
        pytest.skip("recent errors buffer not available")
    # emit two errors
    obs.emit_event("evt1", severity="error", error_code="E1", error="boom1")
    obs.emit_event("evt2", severity="critical", error_code="E2", error="boom2")
    recent = obs.get_recent_errors(limit=2)
    assert isinstance(recent, list) and len(recent) >= 2
    codes = {r.get("error_code") for r in recent[-2:]}
    assert {"E1", "E2"}.issubset(codes)
    assert all("error_category" in r for r in recent[-2:])


def test_bind_user_context_hashes_identifiers(monkeypatch):
    monkeypatch.setattr(obs, "_set_sentry_tag", lambda *a, **k: None)
    try:
        obs.structlog.contextvars.clear_contextvars()
    except Exception:
        pass
    obs.bind_user_context(user_id=12345, chat_id="chat-1")
    ctx = obs.get_observability_context()
    assert ctx.get("user_id") and ctx.get("user_id") != "12345"
    assert ctx.get("chat_id") and ctx.get("chat_id") != "chat-1"


def test_bind_command_sanitizes(monkeypatch):
    captured = {}

    def _bind_contextvars(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(obs.structlog.contextvars, "bind_contextvars", _bind_contextvars)
    monkeypatch.setattr(obs, "_set_sentry_tag", lambda *a, **k: None)
    obs.bind_command("/Status@Bot  extra")
    assert captured.get("command") == "status"


def test_emit_event_adds_error_classification(monkeypatch, tmp_path):
    import observability as obs

    cfg = tmp_path / "error_signatures.yml"
    cfg.write_text(
        """
noise_allowlist: []

categories:
  config:
    default_severity: critical
    default_policy: escalate
    signatures:
      - id: oom_killed
        summary: זיכרון נגמר
        pattern: 'Out of memory'
""",
        encoding="utf-8",
    )

    # Reset caches and environment
    monkeypatch.setenv("ERROR_SIGNATURES_PATH", str(cfg))
    monkeypatch.setattr(obs, "_ERROR_SIGNATURES_CACHE", None, raising=False)
    monkeypatch.setattr(obs, "_mirror_to_log_aggregator", lambda l, m, ed: ed, raising=False)
    monkeypatch.setattr(obs, "_maybe_alert_single_error", lambda *a, **k: None)
    monkeypatch.setattr(obs, "_set_sentry_tag", lambda *a, **k: None)

    calls = {"error": None}

    class _Logger:
        def info(self, **fields):
            pass

        def warning(self, **fields):
            pass

        def error(self, **fields):
            calls["error"] = dict(fields)

    monkeypatch.setattr(obs.structlog, "get_logger", lambda: _Logger())

    try:
        obs._RECENT_ERRORS.clear()  # type: ignore[attr-defined]
    except Exception:
        pass

    obs.emit_event("oom_event", severity="error", error="Out of memory while processing")

    error_fields = calls["error"]
    assert error_fields is not None
    assert error_fields.get("error_category") == "config"
    assert error_fields.get("error_signature") == "oom_killed"
    assert error_fields.get("error_policy") == "escalate"


def test_prepare_outgoing_headers_adds_request_id(monkeypatch):
    monkeypatch.setattr(obs, "_set_sentry_tag", lambda *a, **k: None)
    try:
        obs.structlog.contextvars.clear_contextvars()
    except Exception:
        pass
    obs.bind_request_id("req-xyz")
    headers = obs.prepare_outgoing_headers({})
    assert headers.get("X-Request-ID") == "req-xyz"
