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


def test_sampling_keeps_when_rate_high(monkeypatch):
    monkeypatch.setenv("LOG_INFO_SAMPLE_RATE", "1.0")
    monkeypatch.delenv("LOG_INFO_SAMPLE_ALLOWLIST", raising=False)
    out = _call_maybe_sample("info", "evt_any", request_id="z9y8x7w6")
    assert out["event"] == "evt_any"


def test_sampling_without_request_id_uses_random(monkeypatch):
    # Case 1: random returns high value -> drop when rate=0.5
    monkeypatch.setenv("LOG_INFO_SAMPLE_RATE", "0.5")
    monkeypatch.delenv("LOG_INFO_SAMPLE_ALLOWLIST", raising=False)
    monkeypatch.setattr(obs.random, "random", lambda: 0.9)
    with pytest.raises(structlog.DropEvent):
        _call_maybe_sample("info", "evt_no_req")

    # Case 2: random returns low value -> keep
    monkeypatch.setattr(obs.random, "random", lambda: 0.1)
    out = _call_maybe_sample("info", "evt_no_req")
    assert out["event"] == "evt_no_req"


def test_default_allowlist_includes_business_metric(monkeypatch):
    # No explicit allowlist; rate=0 should still keep business_metric
    monkeypatch.setenv("LOG_INFO_SAMPLE_RATE", "0.0")
    monkeypatch.delenv("LOG_INFO_SAMPLE_ALLOWLIST", raising=False)
    out = _call_maybe_sample("info", "business_metric", request_id="abcd1234")
    assert out["event"] == "business_metric"
