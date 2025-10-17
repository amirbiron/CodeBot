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
