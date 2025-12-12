from datetime import datetime, timezone
import json
import sys
import time
import types

from services import observability_dashboard as obs


def _stub_emit_event(*args, **kwargs):
    return None


def test_get_quick_fix_actions_loads_mapping(monkeypatch, tmp_path):
    cfg = {
        "by_alert_type": {
            "demo_alert": [
                {
                    "id": "demo_action",
                    "label": "Demo",
                    "type": "link",
                    "href": "/demo?ts={{timestamp}}"
                }
            ]
        }
    }
    path = tmp_path / "quick_fix.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(obs, "_QUICK_FIX_PATH", path)
    monkeypatch.setattr(obs, "_QUICK_FIX_CACHE", {})
    monkeypatch.setattr(obs, "_QUICK_FIX_MTIME", 0.0)

    alert = {"alert_type": "demo_alert", "timestamp": "2025-01-01T00:00:00+00:00"}
    actions = obs.get_quick_fix_actions(alert)
    assert actions and actions[0]["href"].endswith("2025-01-01T00:00:00+00:00")


def test_record_quick_fix_action_appends(monkeypatch):
    fake_obs = types.SimpleNamespace(emit_event=_stub_emit_event)
    monkeypatch.setitem(sys.modules, "observability", fake_obs)
    obs._QUICK_FIX_ACTIONS.clear()
    obs.record_quick_fix_action(
        action_id="copy",
        action_label="Copy",
        alert_snapshot={"alert_uid": "u1", "alert_type": "t", "severity": "critical", "timestamp": datetime.now(timezone.utc).isoformat()},
        user_id=42,
    )
    assert obs._QUICK_FIX_ACTIONS


def test_fetch_incident_replay_includes_quick_fix(monkeypatch):
    def _fake_fetch_alerts(**kwargs):
        return ([{
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "alert_type": "anomaly",
            "name": "demo",
            "severity": "critical",
            "summary": "test",
            "alert_uid": "uid-demo",
        }], 1)

    monkeypatch.setattr(obs.alerts_storage, "fetch_alerts", _fake_fetch_alerts)
    obs._QUICK_FIX_ACTIONS.clear()
    obs._QUICK_FIX_ACTIONS.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action_id": "demo",
        "alert_uid": "uid-demo",
    })

    payload = obs.fetch_incident_replay(start_dt=None, end_dt=None, limit=50)
    assert payload["counts"]["chatops"] == 1
    assert payload["events"]


def test_get_quick_fix_actions_prefers_runbook(monkeypatch, tmp_path):
    yaml_text = """
runbooks:
  demo_alert:
    title: Demo
    steps:
      - id: check
        title: Check
        action:
          label: Demo Action
          type: copy
          payload: "/triage demo"
"""
    path = tmp_path / "runbook.yml"
    path.write_text(yaml_text, encoding="utf-8")
    monkeypatch.setattr(obs, "_RUNBOOK_PATH", path)
    monkeypatch.setattr(obs, "_RUNBOOK_CACHE", {})
    monkeypatch.setattr(obs, "_RUNBOOK_ALIAS_MAP", {})
    monkeypatch.setattr(obs, "_RUNBOOK_MTIME", 0.0)

    alert = {"alert_type": "demo_alert", "timestamp": "2025-01-01T00:00:00+00:00"}
    actions = obs.get_quick_fix_actions(alert)
    assert actions and actions[0]["label"] == "Demo Action"


def test_fetch_runbook_for_event_uses_cache(monkeypatch, tmp_path):
    yaml_text = """
runbooks:
  demo_alert:
    title: Demo Runbook
    steps:
      - id: check
        title: Check status
        action:
          label: Copy Cmd
          type: copy
          payload: "/triage demo"
"""
    path = tmp_path / "runbook.yml"
    path.write_text(yaml_text, encoding="utf-8")
    monkeypatch.setattr(obs, "_RUNBOOK_PATH", path)
    monkeypatch.setattr(obs, "_RUNBOOK_CACHE", {})
    monkeypatch.setattr(obs, "_RUNBOOK_ALIAS_MAP", {})
    monkeypatch.setattr(obs, "_RUNBOOK_MTIME", 0.0)
    obs._RUNBOOK_EVENT_CACHE.clear()
    obs._RUNBOOK_EVENT_CACHE["evt-1"] = (
        time.time(),
        {
            "id": "evt-1",
            "alert_uid": "evt-1",
            "type": "alert",
            "title": "Demo Alert",
            "summary": "S",
            "timestamp": "2025-01-01T00:00:00+00:00",
            "severity": "critical",
            "alert_type": "demo_alert",
            "metadata": {},
            "link": "/admin/observability",
        },
    )
    payload = obs.fetch_runbook_for_event(event_id="evt-1")
    assert payload
    assert payload["runbook"]["title"] == "Demo Runbook"
    assert payload["runbook"]["steps"][0]["title"] == "Check status"


def test_update_runbook_step_status_tracks_completion(monkeypatch, tmp_path):
    yaml_text = """
runbooks:
  demo_alert:
    title: Demo Runbook
    steps:
      - id: check
        title: Check status
        action:
          label: Copy Cmd
          type: copy
          payload: "/triage demo"
"""
    path = tmp_path / "runbook.yml"
    path.write_text(yaml_text, encoding="utf-8")
    monkeypatch.setattr(obs, "_RUNBOOK_PATH", path)
    monkeypatch.setattr(obs, "_RUNBOOK_CACHE", {})
    monkeypatch.setattr(obs, "_RUNBOOK_ALIAS_MAP", {})
    monkeypatch.setattr(obs, "_RUNBOOK_MTIME", 0.0)
    obs._RUNBOOK_EVENT_CACHE.clear()
    obs._RUNBOOK_STATE.clear()
    obs._RUNBOOK_EVENT_CACHE["evt-2"] = (
        time.time(),
        {
            "id": "evt-2",
            "alert_uid": "evt-2",
            "type": "alert",
            "title": "Demo Alert",
            "summary": "S",
            "timestamp": "2025-01-01T01:00:00+00:00",
            "severity": "critical",
            "alert_type": "demo_alert",
            "metadata": {},
            "link": "/admin/observability",
        },
    )
    payload = obs.update_runbook_step_status(
        event_id="evt-2",
        step_id="check",
        completed=True,
        user_id=7,
    )
    assert payload["status"]["completed_steps"] == ["check"]
    assert payload["runbook"]["steps"][0]["completed"] is True
