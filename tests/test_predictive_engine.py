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

    trends = pe.evaluate_predictions(now_ts=base + 12 * 60, horizon_seconds=15 * 60)
    lat_trend = [t for t in trends if t.metric == "latency_seconds"][0]
    assert lat_trend.slope_per_minute < 0
    assert lat_trend.predicted_cross_ts is None
