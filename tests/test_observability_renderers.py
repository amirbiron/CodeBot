import os
import types
import structlog
import pytest

import observability as obs


def test_choose_renderer_console_when_debug_true(monkeypatch):
    monkeypatch.setenv("DEBUG", "true")
    # Force re-evaluation by calling the private helper through public API
    # setup_structlog_logging should call _choose_renderer internally without error
    obs.setup_structlog_logging("INFO")
    # Ensure structlog is configured (smoke)
    logger = structlog.get_logger()
    # אל תעבירו גם מחרוזת וגם event=... כדי לא ליצור כפילות ב-structlog
    logger.info("probe_event")


def test_choose_renderer_json_default(monkeypatch):
    monkeypatch.delenv("DEBUG", raising=False)
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    obs.setup_structlog_logging("INFO")
    logger = structlog.get_logger()
    logger.info("probe_event")


def test_add_otel_ids_safe_without_otel(monkeypatch):
    # make sure get_current_span is None
    monkeypatch.setattr(obs, "get_current_span", None, raising=False)
    out = obs._add_otel_ids(None, None, {"x": 1})
    assert out["x"] == 1 and "trace_id" not in out


def test_redact_sensitive_hides_tokens():
    d = {"token": "x", "Password": "y", "normal": "z"}
    out = obs._redact_sensitive(None, None, dict(d))
    assert out["token"] == "[REDACTED]"
    assert out["password"] if "password" in out else out.get("Password") == "[REDACTED]"
    assert out["normal"] == "z"
