import json
import sys
import types


def test_incident_log_write_and_read(tmp_path, monkeypatch):
    # Make data dir local to tmp
    (tmp_path / "data").mkdir()
    monkeypatch.chdir(tmp_path)

    # Stub observability
    def _emit(*a, **k):
        return None
    monkeypatch.setitem(sys.modules, 'observability', types.SimpleNamespace(emit_event=_emit))

    import importlib
    rm = importlib.import_module('remediation_manager')

    # Write two incidents
    i1 = rm.handle_critical_incident("High Error Rate", "error_rate_percent", 15.0, 10.0, {"current_percent": 15.0})
    i2 = rm.handle_critical_incident("High Latency", "latency_seconds", 2.5, 1.0, {"current_seconds": 2.5})
    assert i1 and i2

    items = rm.get_incidents(limit=5)
    assert isinstance(items, list) and len(items) >= 2
    last = items[-1]
    assert set(["incident_id", "name", "metric", "response_action"]).issubset(set(last.keys()))
