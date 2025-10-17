import time


def test_preemptive_actions_triggered(monkeypatch):
    import importlib
    pe = importlib.import_module('predictive_engine')
    importlib.reload(pe)

    # Stub cache with counters
    class _StubCache:
        def __init__(self):
            self.clears = 0
        def clear_stale(self, max_scan=1000, ttl_seconds_threshold=60):
            self.clears += 1
            return 1

    stub = _StubCache()
    monkeypatch.setattr(pe, "_cache", stub)

    base = time.time()
    # Thresholds: low latency threshold to force predicted breach
    def fake_get_thresholds():
        return {"error_rate_percent": 100.0, "latency_seconds": 0.2}
    monkeypatch.setattr(pe, "_get_thresholds", fake_get_thresholds)
    monkeypatch.setattr(pe, "_MEMORY_THRESHOLD_PCT", 99.0)

    # Rising latency sequence
    for i in range(10):
        pe.note_observation(error_rate_percent=0.1, latency_seconds=0.05 + i * 0.03, memory_usage_percent=5.0, ts=base + i * 60)

    trends = pe.maybe_recompute_and_preempt(now_ts=base + 10 * 60)
    # Either immediate or on next call due to throttling
    if not trends:
        trends = pe.maybe_recompute_and_preempt(now_ts=base + 10 * 60 + 61)

    # Ensure cache clear was attempted at least once
    assert stub.clears >= 1
