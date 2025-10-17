import time
import sys
import types
import importlib


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
