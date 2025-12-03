from datetime import datetime, timezone
import json
import sys
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
