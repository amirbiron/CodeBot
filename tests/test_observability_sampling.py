import os
import structlog
import pytest

import observability as obs


def _call_maybe_sample(level: str, event: str, **extra):
    d = {"level": level, "event": event}
    d.update(extra)
    return obs._maybe_sample_info(None, None, d)


def test_sampling_drops_info_when_rate_zero_and_not_allowlisted(monkeypatch):
    monkeypatch.setenv("LOG_INFO_SAMPLE_RATE", "0.0")
    monkeypatch.delenv("LOG_INFO_SAMPLE_ALLOWLIST", raising=False)
    with pytest.raises(structlog.DropEvent):
        _call_maybe_sample("info", "some_event", request_id="abcd1234")


def test_sampling_keeps_info_when_allowlisted_even_with_rate_zero(monkeypatch):
    monkeypatch.setenv("LOG_INFO_SAMPLE_RATE", "0.0")
    monkeypatch.setenv("LOG_INFO_SAMPLE_ALLOWLIST", "business_metric")
    out = _call_maybe_sample("info", "business_metric", request_id="abcd1234")
    assert out["event"] == "business_metric"


def test_sampling_keeps_non_info_levels(monkeypatch):
    monkeypatch.setenv("LOG_INFO_SAMPLE_RATE", "0.0")
    out = _call_maybe_sample("error", "err_evt")
    assert out["event"] == "err_evt"


def test_sampling_is_stable_per_request_id(monkeypatch):
    monkeypatch.setenv("LOG_INFO_SAMPLE_RATE", "0.5")
    # With a fixed request_id, the decision should repeat deterministically
    req_id = "abcd1234"

    def _decision():
        try:
            _call_maybe_sample("info", "evt", request_id=req_id)
            return "keep"
        except structlog.DropEvent:
            return "drop"

    first = _decision()
    second = _decision()
    assert first == second
