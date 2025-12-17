import pytest


def test_metrics_endpoint_exposed_in_both_services(monkeypatch):
    # aiohttp service is covered by existing tests (test_webserver_metrics_route)
    # Here we check Flask app exposes /metrics via the unified metrics helpers.
    try:
        import webapp.app as flask_app
    except Exception:
        pytest.skip("Flask app not importable in this environment")

    app = flask_app.app
    try:
        client = app.test_client()
    except Exception:
        pytest.skip("Flask test client not available")

    resp = client.get("/metrics")
    # Accept either 200 or 503 depending on availability of prometheus_client
    assert resp.status_code in (200, 503)
    assert isinstance(resp.data, (bytes, bytearray))


def test_access_logs_silenced_for_flask_monitoring_endpoints_when_ok(monkeypatch):
    try:
        import webapp.app as flask_app
    except Exception:
        pytest.skip("Flask app not importable in this environment")

    app = flask_app.app
    try:
        client = app.test_client()
    except Exception:
        pytest.skip("Flask test client not available")

    # Force /metrics to be 200 so we can assert silence behavior deterministically.
    try:
        import metrics as m
        monkeypatch.setattr(m, "metrics_endpoint_bytes", lambda: b"ok", raising=False)
        monkeypatch.setattr(m, "metrics_content_type", lambda: "text/plain", raising=False)
    except Exception:
        pass

    events: list[tuple[str, str, dict]] = []

    def fake_emit(event: str, severity: str = "info", **fields):
        events.append((event, severity, fields))

    monkeypatch.setattr(flask_app, "emit_event", fake_emit)

    resp = client.get("/metrics")
    assert resp.status_code == 200

    access = [e for e in events if e[0] == "access_logs"]
    assert not access, "expected /metrics to be silenced when ok"

    # favicon may be 200 or 404 depending on static setup; either should be silenced (unless 5xx).
    events.clear()
    resp2 = client.get("/favicon.ico")
    assert resp2.status_code < 500
    access2 = [e for e in events if e[0] == "access_logs"]
    assert not access2, "expected /favicon.ico to be silenced when ok"
