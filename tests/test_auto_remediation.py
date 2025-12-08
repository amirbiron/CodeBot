import os
import json
import sys
import types


def test_handle_critical_incident_logs_and_actions(tmp_path, monkeypatch):
    # Ensure data dir points to tmp
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.chdir(tmp_path)

    # Fake observability.emit_event
    events = {"evts": []}
    def _emit(event, severity="info", **kw):
        events["evts"].append((event, severity, kw))
    fake_obs = types.SimpleNamespace(emit_event=_emit)
    monkeypatch.setitem(sys.modules, 'observability', fake_obs)

    # Fake cache manager
    class _FakeCache:
        def __init__(self):
            self.cleared = False
        def clear_all(self):
            self.cleared = True
        def delete_pattern(self, pattern):
            self.cleared = True
    fake_cache_mod = types.SimpleNamespace(cache=_FakeCache())
    monkeypatch.setitem(sys.modules, 'cache_manager', fake_cache_mod)

    # Use remediation_manager
    import importlib
    rm = importlib.import_module('remediation_manager')

    # Trigger High Latency path (should clear cache)
    inc_id = rm.handle_critical_incident(
        name="High Latency",
        metric="latency_seconds",
        value=3.5,
        threshold=2.0,
        details={"current_seconds": 3.5},
    )
    assert isinstance(inc_id, str) and len(inc_id) > 0

    # Verify incidents file written
    log_file = tmp_path / 'data' / 'incidents_log.json'
    assert log_file.exists()
    content = log_file.read_text(encoding='utf-8').strip().splitlines()
    assert content and json.loads(content[-1])["response_action"] in {"clear_cache", "reconnect_mongodb", "restart_service:webapp"}

    # Verify event emitted
    assert any(e[0] == "AUTO_REMEDIATION_EXECUTED" for e in events["evts"]) 


def test_handle_critical_incident_skips_external(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.chdir(tmp_path)

    events = {"evts": []}

    def _emit(event, severity="info", **kw):
        events["evts"].append((event, severity, kw))

    fake_obs = types.SimpleNamespace(emit_event=_emit)
    monkeypatch.setitem(sys.modules, 'observability', fake_obs)

    import importlib
    rm = importlib.reload(importlib.import_module('remediation_manager'))

    restart_called = {"value": False}
    monkeypatch.setattr(rm, "_restart_service", lambda *_a, **_k: restart_called.__setitem__("value", True))

    inc_id = rm.handle_critical_incident(
        name="High Error Rate",
        metric="error_rate_percent",
        value=15.0,
        threshold=5.0,
        details={"source": "external"},
    )

    assert isinstance(inc_id, str) and inc_id
    assert restart_called["value"] is False
    assert any(e[0] == "AUTO_REMEDIATION_SKIPPED" for e in events["evts"])

    log_file = tmp_path / 'data' / 'incidents_log.json'
    assert log_file.exists()
    content = log_file.read_text(encoding='utf-8').strip().splitlines()
    assert content
    last = json.loads(content[-1])
    assert last["response_action"] == "skipped_external"
    assert last.get("source") == "external"
