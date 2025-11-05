from __future__ import annotations

import structlog

import pytest


def test_prepare_outgoing_headers_adds_request_id(monkeypatch):
    import observability as obs

    # Ensure a clean structlog context and configure processors once
    obs.setup_structlog_logging("INFO")
    rid = "rid-123"
    obs.bind_request_id(rid)
    headers = obs.prepare_outgoing_headers(None)
    assert headers.get("X-Request-ID") == rid


def test_prepare_outgoing_headers_preserves_existing_request_id(monkeypatch):
    import observability as obs

    obs.setup_structlog_logging("INFO")
    obs.bind_request_id("rid-wont-override")
    result = obs.prepare_outgoing_headers({"X-Request-ID": "pre-set"})
    assert result.get("X-Request-ID") == "pre-set"


def test_get_recent_errors_records_error_events(monkeypatch):
    import observability as obs

    # Record an error event and verify it appears in the recent buffer (best-effort)
    obs.emit_event(
        "unit_test_error",
        severity="error",
        error_code="UT-1",
        operation="op",
        message="boom",
    )
    recent = obs.get_recent_errors(limit=5)
    assert any(e.get("event") == "unit_test_error" for e in recent)
    assert any(e.get("error_code") == "UT-1" for e in recent)


def test_bind_command_sanitizes_and_sets_context():
    import observability as obs

    obs.bind_command("/start@MyBot extra\nnoise")
    ctx = obs.get_observability_context()
    assert ctx.get("command") == "start"


def test_sampling_drops_info_when_rate_zero(monkeypatch):
    import observability as obs

    monkeypatch.setenv("LOG_INFO_SAMPLE_RATE", "0.0")
    event_dict = {"level": "info", "event": "regular_event", "request_id": "abcd"}
    with pytest.raises(structlog.DropEvent):
        obs._maybe_sample_info(None, None, event_dict)


def test_sampling_keeps_allowlisted_even_when_rate_zero(monkeypatch):
    import observability as obs

    monkeypatch.setenv("LOG_INFO_SAMPLE_RATE", "0.0")
    # "business_metric" הוא ברשימת allowlist המובנית
    event_dict = {"level": "info", "event": "business_metric", "request_id": "abcd"}
    # לא נזרק DropEvent
    rv = obs._maybe_sample_info(None, None, event_dict)
    assert rv is event_dict


def test_init_sentry_idempotent_and_reinit_on_dsn_change(monkeypatch):
    import observability as obs

    calls = {"count": 0}

    def fake_init(**kwargs):  # type: ignore[no-redef]
        calls["count"] += 1
        return None

    # Patch sentry_sdk.init globally
    monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "0.0")
    monkeypatch.setenv("SENTRY_PROFILES_SAMPLE_RATE", "0.0")
    monkeypatch.setattr("sentry_sdk.init", fake_init, raising=False)

    # First init
    monkeypatch.setenv("SENTRY_DSN", "http://example.com/1")
    obs.init_sentry()
    assert calls["count"] == 1

    # Second init with same DSN should be skipped
    obs.init_sentry()
    assert calls["count"] == 1

    # Change DSN -> should re-init once more
    monkeypatch.setenv("SENTRY_DSN", "http://example.com/2")
    obs.init_sentry()
    assert calls["count"] == 2
