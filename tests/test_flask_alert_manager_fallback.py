import importlib
import pytest


def _build_app():
    try:
        app_mod = importlib.import_module("webapp.app")
    except Exception:
        pytest.skip("Flask app not importable in this environment")
    app = app_mod.app
    app.testing = True
    return app_mod, app


def test_flask_records_alert_manager_samples_when_metrics_unavailable(monkeypatch):
    # We intentionally simulate "metrics import failed" environments where
    # record_request_outcome is a noop. In that case, the Flask middleware
    # should still feed alert_manager so /triage system|latency have data.
    app_mod, app = _build_app()

    calls = []

    def _fake_note_request(status_code, duration_seconds, *a, **k):
        calls.append((int(status_code), float(duration_seconds)))

    monkeypatch.setattr(app_mod, "_METRICS_AVAILABLE", False, raising=False)
    monkeypatch.setattr(app_mod, "record_request_outcome", lambda *a, **k: None, raising=False)

    import alert_manager as am

    monkeypatch.setattr(am, "note_request", _fake_note_request, raising=True)

    with app.test_client() as client:
        resp = client.get("/login")
        assert resp.status_code in (200, 302)

    assert calls, "expected alert_manager.note_request to be called at least once"


def test_flask_records_alert_manager_samples_when_metrics_available_too(monkeypatch):
    # Regression guard: even when metrics are available, the Flask middleware
    # should still feed alert_manager so /triage system|latency have data.
    app_mod, app = _build_app()

    calls = []

    def _fake_note_request(status_code, duration_seconds, *a, **k):
        calls.append((int(status_code), float(duration_seconds)))

    monkeypatch.setattr(app_mod, "_METRICS_AVAILABLE", True, raising=False)
    # Avoid coupling this test to metrics.record_request_outcome behavior
    monkeypatch.setattr(app_mod, "record_request_outcome", lambda *a, **k: None, raising=False)

    import alert_manager as am

    monkeypatch.setattr(am, "note_request", _fake_note_request, raising=True)

    with app.test_client() as client:
        resp = client.get("/login")
        assert resp.status_code in (200, 302)

    assert calls, "expected alert_manager.note_request to be called at least once"

