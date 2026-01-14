import sys
import time
import types

import pytest

import metrics


@pytest.fixture(autouse=True)
def reset_metrics_state():
    with metrics._HTTP_SAMPLES_LOCK:  # type: ignore[attr-defined]
        metrics._HTTP_REQUEST_SAMPLES.clear()  # type: ignore[attr-defined]
    with metrics._ERR_TIMESTAMPS_LOCK:  # type: ignore[attr-defined]
        metrics._ERR_TIMESTAMPS.clear()  # type: ignore[attr-defined]
    with metrics._ACTIVE_REQUESTS_LOCK:  # type: ignore[attr-defined]
        metrics._ACTIVE_REQUESTS = 0  # type: ignore[attr-defined]
    metrics._EWMA_RT = None
    metrics._ANOMALY_LAST_TS = 0.0
    metrics._LAST_DEPLOYMENT_TS = None
    yield
    with metrics._HTTP_SAMPLES_LOCK:  # type: ignore[attr-defined]
        metrics._HTTP_REQUEST_SAMPLES.clear()  # type: ignore[attr-defined]
    with metrics._ERR_TIMESTAMPS_LOCK:  # type: ignore[attr-defined]
        metrics._ERR_TIMESTAMPS.clear()  # type: ignore[attr-defined]
    with metrics._ACTIVE_REQUESTS_LOCK:  # type: ignore[attr-defined]
        metrics._ACTIVE_REQUESTS = 0  # type: ignore[attr-defined]
    metrics._EWMA_RT = None
    metrics._ANOMALY_LAST_TS = 0.0
    metrics._LAST_DEPLOYMENT_TS = None


def test_get_top_slow_endpoints_sorts_by_max_duration():
    base = time.time()
    metrics._note_http_request_sample("GET", "/slow", 200, 4.0, ts=base - 10)  # type: ignore[attr-defined]
    metrics._note_http_request_sample("GET", "/normal", 200, 1.0, ts=base - 5)  # type: ignore[attr-defined]
    metrics._note_http_request_sample("POST", "/slow", 500, 6.0, ts=base - 1)  # type: ignore[attr-defined]

    results = metrics.get_top_slow_endpoints(limit=2, window_seconds=60)

    assert results
    assert results[0]["endpoint"] == "/slow"
    assert results[0]["method"] == "POST"
    assert results[0]["max_duration"] == pytest.approx(6.0)
    assert results[0]["count"] == 1
    assert len(results) == 2
    assert results[1]["endpoint"] == "/slow"
    assert results[1]["method"] == "GET"


def test_recent_error_counter_respects_window():
    base = time.time()
    metrics._record_error_timestamp(ts=base - 90)  # type: ignore[attr-defined]
    metrics._record_error_timestamp(ts=base - 10)  # type: ignore[attr-defined]
    metrics._record_error_timestamp(ts=base - 5)  # type: ignore[attr-defined]

    assert metrics.get_recent_errors_count(minutes=5) == 3
    assert metrics.get_recent_errors_count(minutes=1) == 2


def test_active_request_gauge_tracks_current_value():
    metrics.note_request_started()
    metrics.note_request_started()
    assert metrics.get_active_requests_count() == 2

    metrics.note_request_finished()
    assert metrics.get_active_requests_count() == 1

    metrics.note_request_finished()
    metrics.note_request_finished()  # extra finish should not go negative
    assert metrics.get_active_requests_count() == 0


def test_anomaly_includes_deploy_metadata(monkeypatch):
    events: list[dict] = []

    fake_module = types.SimpleNamespace()

    def fake_emit_internal_alert(**payload):
        events.append(payload)

    fake_module.emit_internal_alert = fake_emit_internal_alert
    monkeypatch.setitem(sys.modules, "internal_alerts", fake_module)

    metrics._note_http_request_sample("GET", "/deploy-slow", 200, 5.5, ts=time.time())  # type: ignore[attr-defined]
    metrics._EWMA_RT = float(metrics._DEPLOY_AVG_RT_THRESHOLD + 2.0)
    metrics._ANOMALY_LAST_TS = 0.0
    metrics.note_deployment_started("test deployment window")
    events.clear()  # ignore the deployment event

    metrics._maybe_trigger_anomaly()

    assert events, "anomaly event was not emitted"
    payload = events[0]
    assert payload["name"] == "anomaly_detected"
    labels = payload.get("labels") or {}
    assert "top_slow_endpoint" in labels
    assert "active_requests" in labels
    slow_endpoints = payload.get("slow_endpoints")
    assert isinstance(slow_endpoints, list)


def test_ewma_excludes_5xx_and_timeout_like_failures():
    # First request sets EWMA baseline
    metrics.record_request_outcome(200, 1.0, path="/ok")
    assert metrics.get_avg_response_time_seconds() == pytest.approx(1.0)

    # Failures should not affect EWMA (e.g., gateway/worker timeout)
    metrics.record_request_outcome(504, 30.0, path="/timeout")
    assert metrics.get_avg_response_time_seconds() == pytest.approx(1.0)

    # Another success should update EWMA from the previous served baseline
    metrics.record_request_outcome(200, 2.0, path="/ok2")
    assert metrics.get_avg_response_time_seconds() > 1.0
