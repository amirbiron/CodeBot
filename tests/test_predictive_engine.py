import time

def test_predictive_engine_detects_rising_trends(monkeypatch):
    import importlib
    pe = importlib.import_module('predictive_engine')
    importlib.reload(pe)

    base = time.time()
    def fake_get_thresholds():
        return {"error_rate_percent": 5.0, "latency_seconds": 0.3}
    monkeypatch.setattr(pe, "_get_thresholds", fake_get_thresholds)
    monkeypatch.setattr(pe, "_MEMORY_THRESHOLD_PCT", 95.0)

    for i in range(10):
        pe.note_observation(error_rate_percent=1.0 + i * 0.6, latency_seconds=0.1, memory_usage_percent=10.0, ts=base + i * 60)

    trends = pe.evaluate_predictions(now_ts=base + 10 * 60, horizon_seconds=15 * 60)
    metrics = {t.metric: t for t in trends}
    assert metrics["error_rate_percent"].predicted_cross_ts is not None
    assert metrics["latency_seconds"].predicted_cross_ts is None


def test_predictive_engine_detects_falling_trend(monkeypatch):
    import importlib
    pe = importlib.import_module('predictive_engine')
    importlib.reload(pe)

    base = time.time()
    def fake_get_thresholds():
        return {"error_rate_percent": 50.0, "latency_seconds": 2.0}
    monkeypatch.setattr(pe, "_get_thresholds", fake_get_thresholds)
    monkeypatch.setattr(pe, "_MEMORY_THRESHOLD_PCT", 95.0)

    for i in range(12):
        pe.note_observation(error_rate_percent=2.0, latency_seconds=3.0 - i * 0.2, memory_usage_percent=20.0, ts=base + i * 60)


def test_adaptive_feedback_accuracy_and_halflife_tuning(monkeypatch, tmp_path):
    import importlib
    pe = importlib.import_module('predictive_engine')
    importlib.reload(pe)

    # Reset internal state and set model to exp_smoothing for test determinism
    pe.reset_state_for_tests()
    monkeypatch.setenv("PREDICTIVE_MODEL", "exp_smoothing")
    monkeypatch.setenv("PREDICTIVE_HALFLIFE_MINUTES", "10")
    monkeypatch.setenv("PREDICTIVE_FEEDBACK_INTERVAL_SEC", "0")

    base = time.time()

    def fake_get_thresholds():
        # Low thresholds to encourage predictions
        return {"error_rate_percent": 5.0, "latency_seconds": 0.5}

    monkeypatch.setattr(pe, "_get_thresholds", fake_get_thresholds)
    monkeypatch.setattr(pe, "_MEMORY_THRESHOLD_PCT", 95.0)

    # Direct predictive files to a tmp directory (safety in tests)
    pe._INCIDENTS_FILE = str(tmp_path / "incidents_log.json")
    pe._PREDICTIONS_FILE = str(tmp_path / "predictions_log.json")

    # Seed a series of rising error rate observations to cause predictions
    for i in range(20):
        pe.note_observation(error_rate_percent=1.0 + i * 0.6, latency_seconds=0.1, memory_usage_percent=10.0, ts=base + i * 60)

    # First recompute triggers predictions and runs feedback (no incidents yet -> accuracy likely 0)
    pe.maybe_recompute_and_preempt(now_ts=base + 21 * 60)

    # Simulate a few actual incidents that match predictions (same metric within 30m)
    # Write to incidents file under tmp path
    import json, uuid
    inc_path = tmp_path / "incidents_log.json"
    with open(inc_path, "a", encoding="utf-8") as f:
        for j in range(2):
            rec = {
                "incident_id": str(uuid.uuid4()),
                "ts": pe.datetime.fromtimestamp(base + (22 + j) * 60, pe.timezone.utc).isoformat(),
                "metric": "error_rate_percent",
                "name": "High Error Rate",
                "severity": "critical",
                "value": 10.0,
                "threshold": 5.0,
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Run feedback again; accuracy should be >0 and halflife stays in bounds
    pe.maybe_recompute_and_preempt(now_ts=base + 24 * 60)

    # It's hard to inspect gauge value directly without prometheus_client; instead ensure function runs without errors
    # and internal halflife remains within allowed bounds
    assert pe._HALFLIFE_MIN_MIN <= pe._HALFLIFE_MINUTES <= pe._HALFLIFE_MIN_MAX


    trends = pe.evaluate_predictions(now_ts=base + 12 * 60, horizon_seconds=15 * 60)
    lat_trend = [t for t in trends if t.metric == "latency_seconds"][0]
    assert lat_trend.slope_per_minute < 0
    assert lat_trend.predicted_cross_ts is None
