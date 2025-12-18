from datetime import datetime, timezone
import json
import os
from pathlib import Path
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
    # Quick-fix telemetry should NOT pollute the Incident Replay timeline.
    assert payload["counts"]["chatops"] == 0
    assert payload["events"]
    assert all(evt.get("type") != "chatops" for evt in payload["events"])


def test_fetch_incident_replay_classifies_deployment_from_metadata_type(monkeypatch):
    def _fake_fetch_alerts(**kwargs):
        return (
            [
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "alert_type": None,
                    "name": "Deployment Event",
                    "severity": "info",
                    "summary": "deploy happened",
                    "alert_uid": "uid-deploy-1",
                    "metadata": {"type": "Deployment Event"},
                }
            ],
            1,
        )

    monkeypatch.setattr(obs.alerts_storage, "fetch_alerts", _fake_fetch_alerts)
    payload = obs.fetch_incident_replay(start_dt=None, end_dt=None, limit=50)
    assert payload["counts"]["deployments"] == 1
    assert payload["counts"]["alerts"] == 0
    assert payload["events"]
    assert payload["events"][0]["type"] == "deployment"
    assert payload["events"][0]["metadata"]["alert_type"] == "Deployment Event"


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

    # Ensure normalization matches even when alert_type uses different separators.
    alert = {"alert_type": "demo-alert", "timestamp": "2025-01-01T00:00:00+00:00"}
    actions = obs.get_quick_fix_actions(alert)
    assert actions and actions[0]["label"] == "Demo Action"


def test_get_quick_fix_actions_uses_metadata_type_when_alert_type_missing(monkeypatch, tmp_path):
    yaml_text = """
runbooks:
  db_connection_issue:
    title: DB Issue
    aliases:
      - no_replica_set_members
    steps:
      - id: triage_db
        title: Triage DB
        action:
          label: /triage db
          type: copy
          payload: "/triage db"
"""
    path = tmp_path / "runbook.yml"
    path.write_text(yaml_text, encoding="utf-8")
    monkeypatch.setattr(obs, "_RUNBOOK_PATH", path)
    monkeypatch.setattr(obs, "_RUNBOOK_CACHE", {})
    monkeypatch.setattr(obs, "_RUNBOOK_ALIAS_MAP", {})
    monkeypatch.setattr(obs, "_RUNBOOK_MTIME", 0.0)

    # Simulate older DB rows where alert_type isn't stored top-level, but exists under metadata "type".
    alert = {
        "alert_type": None,
        "timestamp": "2025-01-01T00:00:00+00:00",
        "metadata": {"type": "no_replica_set_members"},
    }
    actions = obs.get_quick_fix_actions(alert)
    assert actions and actions[0]["label"] == "/triage db"


def test_get_quick_fix_actions_json_fallback_uses_metadata_type(monkeypatch, tmp_path):
    # Runbook exists (matches via alias) but has no actions, so get_quick_fix_actions
    # will fall back to the JSON quick-fixes config. That fallback should use the
    # same metadata-based alert_type extraction.
    yaml_text = """
runbooks:
  db_connection_issue:
    title: DB Issue
    aliases:
      - no_replica_set_members
    steps:
      - id: only_text
        title: No action step
        description: "step without action so actions list is empty"
"""
    runbook_path = tmp_path / "runbook.yml"
    runbook_path.write_text(yaml_text, encoding="utf-8")
    monkeypatch.setattr(obs, "_RUNBOOK_PATH", runbook_path)
    monkeypatch.setattr(obs, "_RUNBOOK_CACHE", {})
    monkeypatch.setattr(obs, "_RUNBOOK_ALIAS_MAP", {})
    monkeypatch.setattr(obs, "_RUNBOOK_MTIME", 0.0)

    cfg = {
        "by_alert_type": {
            "no_replica_set_members": [
                {"id": "demo", "label": "Demo", "type": "copy", "payload": "/triage db"}
            ]
        }
    }
    qf_path = tmp_path / "quick_fix.json"
    qf_path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(obs, "_QUICK_FIX_PATH", qf_path)
    monkeypatch.setattr(obs, "_QUICK_FIX_CACHE", {})
    monkeypatch.setattr(obs, "_QUICK_FIX_MTIME", 0.0)

    alert = {"alert_type": None, "timestamp": "2025-01-01T00:00:00+00:00", "metadata": {"type": "no_replica_set_members"}}
    actions = obs.get_quick_fix_actions(alert)
    assert actions and actions[0]["label"] == "Demo"


def test_get_quick_fix_actions_matches_config_key_with_different_separators(monkeypatch, tmp_path):
    cfg = {
        "by_alert_type": {
            "demo_alert": [
                {
                    "id": "demo_action",
                    "label": "Demo",
                    "type": "link",
                    "href": "/demo?ts={{timestamp}}",
                }
            ]
        }
    }
    path = tmp_path / "quick_fix.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(obs, "_QUICK_FIX_PATH", path)
    monkeypatch.setattr(obs, "_QUICK_FIX_CACHE", {})
    monkeypatch.setattr(obs, "_QUICK_FIX_MTIME", 0.0)

    alert = {"alert_type": "demo-alert", "timestamp": "2025-01-01T00:00:00+00:00"}
    actions = obs.get_quick_fix_actions(alert)
    assert actions and actions[0]["href"].endswith("2025-01-01T00:00:00+00:00")


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


def test_update_runbook_step_status_uses_fallback_metadata(monkeypatch, tmp_path):
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

    payload = obs.update_runbook_step_status(
        event_id="evt-3",
        step_id="check",
        completed=True,
        user_id=9,
        fallback_metadata={
            "id": "evt-3",
            "alert_type": "demo_alert",
            "type": "alert",
            "title": "Demo Alert",
            "summary": "S",
            "timestamp": "2025-01-01T02:00:00+00:00",
            "severity": "critical",
            "metadata": {"alert_type": "demo_alert"},
        },
    )
    assert payload["status"]["completed_steps"] == ["check"]
    assert payload["runbook"]["steps"][0]["completed"] is True


def test_runbook_relative_path_resolves_from_repo_root_when_cwd_differs(monkeypatch, tmp_path):
    """Regression: production CWD isn't guaranteed to be repo root."""
    monkeypatch.setattr(obs, "_RUNBOOK_PATH", Path("config/observability_runbooks.yml"))
    monkeypatch.setattr(obs, "_RUNBOOK_CACHE", {})
    monkeypatch.setattr(obs, "_RUNBOOK_ALIAS_MAP", {})
    monkeypatch.setattr(obs, "_RUNBOOK_MTIME", 0.0)
    monkeypatch.setattr(obs, "_RUNBOOK_RESOLVED_PATH", None)
    obs._RUNBOOK_EVENT_CACHE.clear()

    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        payload = obs.fetch_runbook_for_event(
            event_id="evt-relative",
            fallback_metadata={
                "id": "evt-relative",
                "alert_type": "some_unknown_alert_type",
                "type": "alert",
                "title": "Demo",
                "summary": "S",
                "timestamp": "2025-01-01T00:00:00+00:00",
                "severity": "critical",
                "metadata": {"alert_type": "some_unknown_alert_type"},
            },
        )
    finally:
        os.chdir(old_cwd)

    assert payload
    assert payload["runbook"]
    assert payload["runbook"]["steps"]


def test_runbook_path_resolution_does_not_crash_if_cwd_unavailable(monkeypatch):
    """Regression: Path.cwd()/exists() failures must not bubble up."""
    monkeypatch.setattr(obs, "_RUNBOOK_PATH", Path("config/observability_runbooks.yml"))
    monkeypatch.setattr(obs, "_RUNBOOK_CACHE", {})
    monkeypatch.setattr(obs, "_RUNBOOK_ALIAS_MAP", {})
    monkeypatch.setattr(obs, "_RUNBOOK_MTIME", 0.0)
    monkeypatch.setattr(obs, "_RUNBOOK_RESOLVED_PATH", None)

    def _boom(*args, **kwargs):
        raise FileNotFoundError("cwd_missing")

    monkeypatch.setattr(obs.Path, "cwd", classmethod(_boom), raising=True)

    payload = obs.fetch_runbook_for_event(
        event_id="evt-cwd-missing",
        fallback_metadata={
            "id": "evt-cwd-missing",
            "alert_type": "some_unknown_alert_type",
            "type": "alert",
            "title": "Demo",
            "summary": "S",
            "timestamp": "2025-01-01T00:00:00+00:00",
            "severity": "critical",
            "metadata": {"alert_type": "some_unknown_alert_type"},
        },
    )

    assert payload
    assert payload["runbook"]


def test_get_quick_fix_actions_dynamic_latency_prefers_pool_branch(monkeypatch, tmp_path):
    yaml_text = """
version: 1
quick_fix_rules:
  latency_v1:
    enabled: true
    thresholds:
      queue_delay_ms: 500
      duration_ms: 3000
      pool_utilization_high_pct: 90
    actions:
      queue_pool_high:
        label: "🔌 הגדל Connection Pool / Kill Slow Queries"
        type: copy
        payload: "/triage db"
        safety: caution
runbooks:
  slow_response:
    title: Slow Response
    steps:
      - id: triage
        title: Triage
        action:
          label: /triage latency
          type: copy
          payload: "/triage latency"
"""
    path = tmp_path / "runbook.yml"
    path.write_text(yaml_text, encoding="utf-8")
    monkeypatch.setattr(obs, "_RUNBOOK_PATH", path)
    monkeypatch.setattr(obs, "_RUNBOOK_CACHE", {})
    monkeypatch.setattr(obs, "_RUNBOOK_ALIAS_MAP", {})
    monkeypatch.setattr(obs, "_RUNBOOK_MTIME", 0.0)

    alert = {
        "alert_type": "slow_response",
        "timestamp": "2025-01-01T00:00:00+00:00",
        "metadata": {"queue_delay": 600, "duration_ms": 1200, "db_pool_utilization_pct": 95},
    }
    actions = obs.get_quick_fix_actions(alert)
    assert actions
    assert "Connection Pool" in (actions[0].get("label") or "")
    assert actions[0].get("payload") == "/triage db"


def test_get_quick_fix_actions_dynamic_latency_duration_mongo_branch(monkeypatch, tmp_path):
    yaml_text = """
version: 1
quick_fix_rules:
  latency_v1:
    enabled: true
    thresholds:
      queue_delay_ms: 500
      duration_ms: 3000
    actions:
      processing_mongo:
        label: "🔍 בדוק אינדקסים / currentOp (Slow Query)"
        type: copy
        payload: "/triage db"
        safety: caution
runbooks:
  slow_response:
    title: Slow Response
    steps: []
"""
    path = tmp_path / "runbook.yml"
    path.write_text(yaml_text, encoding="utf-8")
    monkeypatch.setattr(obs, "_RUNBOOK_PATH", path)
    monkeypatch.setattr(obs, "_RUNBOOK_CACHE", {})
    monkeypatch.setattr(obs, "_RUNBOOK_ALIAS_MAP", {})
    monkeypatch.setattr(obs, "_RUNBOOK_MTIME", 0.0)

    alert = {
        "alert_type": "slow_response",
        "timestamp": "2025-01-01T00:00:00+00:00",
        "summary": "something about mongo timeout",
        "metadata": {"queue_delay": 50, "duration_ms": 4000, "trace": "MongoDB"},
    }
    actions = obs.get_quick_fix_actions(alert)
    assert actions
    assert "currentOp" in (actions[0].get("label") or "")
    assert actions[0].get("payload") == "/triage db"


def test_get_quick_fix_actions_dynamic_latency_fallback_when_metrics_missing(monkeypatch, tmp_path):
    yaml_text = """
version: 1
quick_fix_rules:
  latency_v1:
    enabled: true
    thresholds:
      queue_delay_ms: 500
    actions:
      queue_generic:
        label: "📈 Scale Up"
        type: copy
        payload: "/triage system"
        safety: safe
runbooks:
  slow_response:
    title: Slow Response
    steps: []
"""
    path = tmp_path / "runbook.yml"
    path.write_text(yaml_text, encoding="utf-8")
    monkeypatch.setattr(obs, "_RUNBOOK_PATH", path)
    monkeypatch.setattr(obs, "_RUNBOOK_CACHE", {})
    monkeypatch.setattr(obs, "_RUNBOOK_ALIAS_MAP", {})
    monkeypatch.setattr(obs, "_RUNBOOK_MTIME", 0.0)

    alert = {
        "alert_type": "slow_response",
        "timestamp": "2025-01-01T00:00:00+00:00",
        "metadata": {"queue_delay": 800},
    }
    actions = obs.get_quick_fix_actions(alert)
    assert actions
    assert "Scale Up" in (actions[0].get("label") or "")
    assert actions[0].get("payload") == "/triage system"


def test_heavy_query_detected_alias_maps_to_slow_response_and_links_performance_bible(monkeypatch):
    # Use the real repo runbooks config to ensure the alias + step exist.
    monkeypatch.setattr(obs, "_RUNBOOK_PATH", Path("config/observability_runbooks.yml"))
    monkeypatch.setattr(obs, "_RUNBOOK_CACHE", {})
    monkeypatch.setattr(obs, "_RUNBOOK_ALIAS_MAP", {})
    monkeypatch.setattr(obs, "_RUNBOOK_MTIME", 0.0)
    monkeypatch.setattr(obs, "_RUNBOOK_RESOLVED_PATH", None)

    alert = {"alert_type": "heavy_query_detected", "timestamp": "2025-01-01T00:00:00+00:00", "metadata": {}}
    actions = obs.get_quick_fix_actions(alert)
    assert actions
    assert any("docs/performance-bible.md" in str(a.get("href") or "") for a in actions)
