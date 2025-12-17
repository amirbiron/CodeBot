import time
import sys
import types
import importlib

import pytest


def _load_alert_manager(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(sys.modules, 'observability', types.SimpleNamespace(emit_event=lambda *a, **k: None))
    if 'alert_manager' in sys.modules:
        am = importlib.reload(sys.modules['alert_manager'])
    else:
        am = importlib.import_module('alert_manager')
    am.reset_state_for_tests()
    return am


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


def test_external_errors_emit_warning_only(tmp_path, monkeypatch):
    am = _load_alert_manager(tmp_path, monkeypatch)

    warnings: list[tuple[str, str, str, dict]] = []

    def _fake_alert(name, severity="info", summary="", **details):
        warnings.append((name, severity, summary, details))

    monkeypatch.setitem(sys.modules, 'internal_alerts', types.SimpleNamespace(emit_internal_alert=_fake_alert))

    import metrics  # noqa: WPS433

    gauge_values: list[float] = []
    monkeypatch.setattr(metrics, "set_external_error_rate_percent", lambda value=None: gauge_values.append(value or 0.0))

    critical_calls: list[tuple] = []
    monkeypatch.setattr(am, "_emit_critical_once", lambda *a, **k: critical_calls.append((a, k)))

    now = time.time()
    for i in range(30):
        am.note_request(503, 0.2, ts=now - 60 + i, source="external")

    am._thresholds['error_rate_percent'].threshold = 1.0  # type: ignore[attr-defined]
    am.check_and_emit_alerts(now_ts=now)

    assert not critical_calls
    assert any(name == "External Service Degraded" and severity == "warning" for name, severity, *_ in warnings)
    assert gauge_values and gauge_values[-1] > 0.0


def test_external_warning_includes_service_when_context_available(tmp_path, monkeypatch):
    am = _load_alert_manager(tmp_path, monkeypatch)

    captured: list[tuple[str, str, str, dict]] = []

    def _fake_alert(name, severity="info", summary="", **details):
        captured.append((name, severity, summary, details))

    monkeypatch.setitem(sys.modules, 'internal_alerts', types.SimpleNamespace(emit_internal_alert=_fake_alert))

    import metrics  # noqa: WPS433

    monkeypatch.setattr(metrics, "set_external_error_rate_percent", lambda value=None: None)

    now = time.time()
    # Seed external errors with a component in context (best-effort service attribution)
    for i in range(6):
        am.note_request(
            503,
            0.2,
            ts=now - 60 + i,
            source="external",
            context={"source": "external", "component": "OpenAI_API"},
        )

    am.check_and_emit_alerts(now_ts=now)

    warn = next((d for n, sev, _s, d in captured if n == "External Service Degraded" and sev == "warning"), None)
    assert warn is not None
    assert warn.get("service") == "OpenAI_API"


def test_internal_errors_trigger_high_error_rate(tmp_path, monkeypatch):
    am = _load_alert_manager(tmp_path, monkeypatch)

    criticals: list[tuple[str, str, dict]] = []

    def _fake_alert(name, severity="info", summary="", **details):
        criticals.append((name, severity, details))

    monkeypatch.setitem(sys.modules, 'internal_alerts', types.SimpleNamespace(emit_internal_alert=_fake_alert))

    import remediation_manager as rm  # noqa: WPS433

    incidents: list[tuple[str, str, dict]] = []

    def _fake_handle(name, metric, value, threshold, details=None):
        incidents.append((name, metric, details or {}))
        return "incident-1"

    monkeypatch.setattr(rm, "handle_critical_incident", _fake_handle)

    now = time.time()
    for i in range(30):
        status = 500 if i % 2 == 0 else 200
        am.note_request(status, 0.2, ts=now - 60 + i, source="internal")

    am._thresholds['error_rate_percent'].threshold = 10.0  # type: ignore[attr-defined]
    am.check_and_emit_alerts(now_ts=now)

    assert incidents, "expected remediation to be triggered for internal errors"
    assert incidents[-1][0] == "High Error Rate"
    assert incidents[-1][2].get("source") == "internal"
    assert any(severity == "critical" for _, severity, _ in criticals)


def test_high_latency_details_include_source(tmp_path, monkeypatch):
    am = _load_alert_manager(tmp_path, monkeypatch)

    captured: list[tuple[str, str, dict]] = []

    def _fake_alert(name, severity="info", summary="", **details):
        captured.append((name, severity, details))

    monkeypatch.setitem(sys.modules, 'internal_alerts', types.SimpleNamespace(emit_internal_alert=_fake_alert))

    import remediation_manager as rm  # noqa: WPS433

    monkeypatch.setattr(rm, "handle_critical_incident", lambda *a, **k: None)

    now = time.time()
    for i in range(20):
        am.note_request(200, 2.5, ts=now - 60 + i, source="internal")

    am._thresholds['latency_seconds'].threshold = 1.0  # type: ignore[attr-defined]
    am.check_and_emit_alerts(now_ts=now)

    latency_details = next(
        (details for name, _, details in captured if name == "High Latency"),
        None,
    )
    assert latency_details is not None
    assert latency_details.get("source") == "internal"
    assert latency_details.get("alert_type") == "slow_response"
    assert latency_details.get("duration_ms") is not None


def test_mixed_samples_only_internal_counted(tmp_path, monkeypatch):
    am = _load_alert_manager(tmp_path, monkeypatch)

    monkeypatch.setitem(sys.modules, 'internal_alerts', types.SimpleNamespace(emit_internal_alert=lambda *a, **k: None))

    import remediation_manager as rm  # noqa: WPS433

    monkeypatch.setattr(rm, "handle_critical_incident", lambda *a, **k: None)

    critical_calls: list[tuple] = []
    monkeypatch.setattr(am, "_emit_critical_once", lambda *a, **k: critical_calls.append((a, k)))

    now = time.time()
    for i in range(20):
        am.note_request(200, 0.1, ts=now - 60 + i, source="internal")
    for i in range(20):
        am.note_request(502, 0.1, ts=now - 60 + i, source="external")

    am._thresholds['error_rate_percent'].threshold = 5.0  # type: ignore[attr-defined]
    am.check_and_emit_alerts(now_ts=now)

    assert not critical_calls, "external errors should not trigger high error rate without internal breaches"


def test_error_context_does_not_override_internal_source(tmp_path, monkeypatch):
    am = _load_alert_manager(tmp_path, monkeypatch)

    # Avoid side effects
    monkeypatch.setitem(sys.modules, 'internal_alerts', types.SimpleNamespace(emit_internal_alert=lambda *a, **k: None))

    import remediation_manager as rm  # noqa: WPS433

    monkeypatch.setattr(rm, "handle_critical_incident", lambda *a, **k: None)

    captured_details: list[dict] = []

    def _capture(*args, **kwargs):
        captured_details.append(kwargs.get("details", {}))

    monkeypatch.setattr(am, "_emit_critical_once", _capture)

    now = time.time()
    # External error to seed contexts
    am.note_request(
        502,
        0.2,
        ts=now - 120,
        source="external",
        context={"command": "uptimerobot.check", "source": "external"},
    )
    # Internal traffic that should trigger the alert
    for i in range(30):
        status = 500 if i % 2 == 0 else 200
        am.note_request(status, 0.2, ts=now - 60 + i, source="internal", context={"command": "webapp:ping"})

    am._thresholds['error_rate_percent'].threshold = 5.0  # type: ignore[attr-defined]
    am.check_and_emit_alerts(now_ts=now)

    assert captured_details, "expected High Error Rate alert to be emitted"
    assert captured_details[0].get("source") == "internal"
