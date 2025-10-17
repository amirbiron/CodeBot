import sys
import types
import time


def test_recurring_issue_bumps_threshold(monkeypatch, tmp_path):
    (tmp_path / "data").mkdir()
    monkeypatch.chdir(tmp_path)

    # Stub observability
    monkeypatch.setitem(sys.modules, 'observability', types.SimpleNamespace(emit_event=lambda *a, **k: None))

    # Stub metrics.set_adaptive_observability_gauges to capture updates
    captured = {"args": []}
    def _set_gauges(**kw):
        captured["args"].append(kw)
    monkeypatch.setitem(sys.modules, 'metrics', types.SimpleNamespace(set_adaptive_observability_gauges=_set_gauges))

    # Provide thresholds snapshot
    def _snap():
        return {
            "error_rate_percent": {"threshold": 10.0},
            "latency_seconds": {"threshold": 2.0},
        }
    monkeypatch.setitem(sys.modules, 'alert_manager', types.SimpleNamespace(get_thresholds_snapshot=_snap))

    import importlib
    rm = importlib.import_module('remediation_manager')

    # First incident
    rm.handle_critical_incident("High Error Rate", "error_rate_percent", 12.0, 10.0, {"current_percent": 12.0})
    # Second incident with same kind within 15m (immediate)
    rm.handle_critical_incident("High Error Rate", "error_rate_percent", 13.0, 10.0, {"current_percent": 13.0})

    # Expect a bump call occurred (factor 1.2 applied)
    assert captured["args"], "expected gauges to be updated"
    bumped = False
    for kw in captured["args"]:
        if kw.get("error_rate_threshold_percent") and kw["error_rate_threshold_percent"] > 10.0:
            bumped = True
    assert bumped, "should bump error rate threshold on recurring"
