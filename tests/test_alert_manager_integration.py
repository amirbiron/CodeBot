import time
import sys
import types
import importlib

import pytest


def test_alert_manager_emits_remediation_and_bump(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    monkeypatch.chdir(tmp_path)

    # Stub observability
    monkeypatch.setitem(sys.modules, 'observability', types.SimpleNamespace(emit_event=lambda *a, **k: None))

    # Stub internal_alerts to avoid side effects
    monkeypatch.setitem(sys.modules, 'internal_alerts', types.SimpleNamespace(emit_internal_alert=lambda *a, **k: None))

    # Ensure remediation_manager is importable
    import remediation_manager as rm  # noqa: F401

    am = importlib.import_module('alert_manager')

    # Seed threshold and then bump
    am._thresholds['error_rate_percent'].threshold = 10.0  # type: ignore[attr-defined]
    am.bump_threshold('error_rate_percent', 1.2)
    assert am._thresholds['error_rate_percent'].threshold > 10.0  # type: ignore[attr-defined]

    # Trigger critical once; should create an incident via remediation_manager
    am._emit_critical_once(
        key='error_rate_percent',
        name='High Error Rate',
        summary='err>thr',
        details={'current_percent': 12.0},
        now_ts=time.time(),
    )

    # Verify incident file exists and non-empty
    p = tmp_path / 'data' / 'incidents_log.json'
    assert p.exists() and p.stat().st_size > 0


def test_high_error_rate_alert_carries_meta(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    monkeypatch.chdir(tmp_path)

    monkeypatch.setitem(sys.modules, 'observability', types.SimpleNamespace(emit_event=lambda *a, **k: None))

    captured = {}

    def _fake_emit_internal_alert(name, severity="info", summary="", **details):
        captured["name"] = name
        captured["severity"] = severity
        captured["summary"] = summary
        captured["details"] = details

    monkeypatch.setitem(sys.modules, 'internal_alerts', types.SimpleNamespace(emit_internal_alert=_fake_emit_internal_alert))

    import remediation_manager as rm  # noqa: WPS433

    monkeypatch.setattr(rm, "handle_critical_incident", lambda *a, **k: None)

    am = importlib.import_module('alert_manager')
    am.reset_state_for_tests()

    ts = time.time()
    am.note_request(
        500,
        0.2,
        ts=ts,
        context={
            "command": "webapp:post:push_api.subscribe",
            "path": "/api/push/subscribe",
            "method": "POST",
            "request_id": "req-meta-123456",
            "user_id": "user-abc",
            "source": "webapp",
        },
    )
    am._thresholds['error_rate_percent'].threshold = 5.0  # type: ignore[attr-defined]

    am._emit_critical_once(
        key='error_rate_percent',
        name='High Error Rate',
        summary='err>thr',
        details={'current_percent': 5.63, 'sample_count': 120, 'threshold_percent': 5.0, 'window_seconds': 300},
        now_ts=ts + 1,
    )

    payload = captured["details"]
    assert payload.get("alert_type") == "high_error_rate"
    assert payload.get("feature") == "push_api.subscribe"
    assert payload.get("request_id") == "req-meta-123456"
    assert payload.get("error_rate_percent") == pytest.approx(5.63, rel=1e-3)
    assert "meta_summary" in payload and "push_api.subscribe" in payload["meta_summary"]
