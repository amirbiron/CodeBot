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
