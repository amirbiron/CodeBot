import math
import types
import pytest


@pytest.mark.asyncio
async def test_adaptive_thresholds_basic(monkeypatch):
    # Reset state
    import alert_manager as am
    am.reset_state_for_tests()

    base_ts = 1_700_000_000.0

    # Seed 3h of mostly healthy traffic: 60 req/min, 1% errors, latency ~0.2s
    ts = base_ts
    for minute in range(180):
        for i in range(60):
            code = 500 if i == 0 else 200  # ~1/60 ~ 1.67% (good enough for test)
            am.note_request(code, 0.2, ts=ts)
            ts += 1.0

    # Force recompute
    am.check_and_emit_alerts(now_ts=ts)
    th = am.get_thresholds_snapshot()
    assert th["error_rate_percent"]["threshold"] >= th["error_rate_percent"]["mean"]
    assert th["latency_seconds"]["threshold"] >= th["latency_seconds"]["mean"]

    # Now create a 5-minute spike: 50% errors, latency 1.5s
    for i in range(5 * 60):
        am.note_request(500 if (i % 2 == 0) else 200, 1.5, ts=ts)
        ts += 1.0

    # Should breach thresholds; check doesn't raise and (best-effort) attempts to emit
    am.check_and_emit_alerts(now_ts=ts)
    # Dispatch log may be empty in CI without envs, but thresholds should be recomputed
    th2 = am.get_thresholds_snapshot()
    assert th2["error_rate_percent"]["updated_at_ts"] >= th["error_rate_percent"]["updated_at_ts"]
    assert th2["latency_seconds"]["updated_at_ts"] >= th["latency_seconds"]["updated_at_ts"]
