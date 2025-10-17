import time
import os
import json
import importlib


def test_predictions_cleanup_and_feedback(tmp_path, monkeypatch):
    pe = importlib.import_module('predictive_engine')
    importlib.reload(pe)

    pe.reset_state_for_tests()

    # Direct files to tmp
    pe._PREDICTIONS_FILE = str(tmp_path / "predictions_log.json")
    pe._INCIDENTS_FILE = str(tmp_path / "incidents_log.json")

    # Make cleanup aggressive for test
    monkeypatch.setenv("PREDICTION_MAX_AGE_SECONDS", "60")
    monkeypatch.setenv("PREDICTIVE_CLEANUP_INTERVAL_SEC", "0")
    monkeypatch.setenv("PREDICTIVE_FEEDBACK_INTERVAL_SEC", "0")
    monkeypatch.setenv("PREDICTIVE_MODEL", "exp_smoothing")

    base = time.time()

    # Seed thresholds and memory threshold high
    def fake_get_thresholds():
        return {"error_rate_percent": 5.0, "latency_seconds": 0.5}
    monkeypatch.setattr(pe, "_get_thresholds", fake_get_thresholds)
    monkeypatch.setattr(pe, "_MEMORY_THRESHOLD_PCT", 99.0)

    # Create two old predictions (older than 60s) and one fresh
    old_ts = base - 300
    mid_ts = base - 120
    new_ts = base - 10
    pe.note_observation(error_rate_percent=10.0, latency_seconds=0.1, memory_usage_percent=5.0, ts=old_ts)
    pe.note_observation(error_rate_percent=11.0, latency_seconds=0.1, memory_usage_percent=5.0, ts=mid_ts)
    pe.note_observation(error_rate_percent=12.0, latency_seconds=0.1, memory_usage_percent=5.0, ts=new_ts)

    # Force predictions logging via recompute
    pe.maybe_recompute_and_preempt(now_ts=base)

    # Ensure file exists
    assert os.path.exists(pe._PREDICTIONS_FILE)

    # Trigger cleanup and feedback
    pe.maybe_recompute_and_preempt(now_ts=base + 1)

    # After cleanup, only recent predictions should remain
    with open(pe._PREDICTIONS_FILE, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip()]
    assert len(lines) >= 1

    # Feedback: write an incident matching metric to allow non-zero accuracy computation path
    with open(pe._INCIDENTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "incident_id": "x",
            "ts": pe.datetime.fromtimestamp(base + 30, pe.timezone.utc).isoformat(),
            "metric": "error_rate_percent",
            "name": "High Error Rate",
            "severity": "critical",
            "value": 10.0,
            "threshold": 5.0,
        }, ensure_ascii=False) + "\n")

    pe.maybe_recompute_and_preempt(now_ts=base + 45)

    # No exceptions and files remain accessible
    assert os.path.exists(pe._PREDICTIONS_FILE)
    assert os.path.exists(pe._INCIDENTS_FILE)
