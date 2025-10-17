import pytest
import json


def test_alerts_endpoint_flask(monkeypatch):
    try:
        import webapp.app as flask_app
    except Exception:
        pytest.skip("Flask not available")

    app = flask_app.app
    client = app.test_client()

    # Seed some internal alerts to verify GET /alerts shape
    try:
        from internal_alerts import emit_internal_alert
        emit_internal_alert("unit_test_alert", severity="warn", summary="testing")
    except Exception:
        pass

    res = client.get("/alerts?limit=2")
    assert res.status_code == 200
    data = res.get_json()
    assert isinstance(data, dict)
    assert "alerts" in data
    assert isinstance(data["alerts"], list)

    # POST /alerts on aiohttp service is covered separately; here ensure Flask GET works


def test_uptime_endpoint_flask():
    try:
        import webapp.app as flask_app
    except Exception:
        pytest.skip("Flask not available")

    app = flask_app.app
    client = app.test_client()

    res = client.get("/uptime")
    assert res.status_code == 200
    js = res.get_json()
    assert "uptime_percent" in js
    assert "process_uptime_seconds" in js
