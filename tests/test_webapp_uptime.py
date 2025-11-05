import pytest
import requests


@pytest.fixture(autouse=True)
def _reset_uptime_cache():
    # Reset cache before each test to avoid cross-test coupling
    import webapp.app as wap

    with wap._uptime_cache_lock:
        wap._uptime_cache["data"] = None
        wap._uptime_cache["provider"] = None
        wap._uptime_cache["fetched_at"] = 0.0
    yield
    with wap._uptime_cache_lock:
        wap._uptime_cache["data"] = None
        wap._uptime_cache["provider"] = None
        wap._uptime_cache["fetched_at"] = 0.0


def test_api_uptime_returns_503_on_failure_without_stale(monkeypatch):
    import webapp.app as wap

    # Configure provider and API key
    wap.UPTIME_PROVIDER = "uptimerobot"
    wap.UPTIME_API_KEY = "dummy"
    wap.UPTIME_MONITOR_ID = ""

    # Force http client to raise connection error
    def _boom(*_a, **_k):  # noqa: D401
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(wap, "http_request", _boom)

    client = wap.app.test_client()
    resp = client.get("/api/uptime")
    assert resp.status_code == 503
    data = resp.get_json()
    assert data and data.get("ok") is False


def test_api_uptime_uses_stale_on_failure(monkeypatch):
    import webapp.app as wap

    # Pre-populate cache with a stale-but-valid value
    with wap._uptime_cache_lock:
        wap._uptime_cache["data"] = {
            "provider": "uptimerobot",
            "uptime_percentage": 98.76,
            "status_url": None,
        }
        # make it very old to simulate TTL expiry
        wap._uptime_cache["fetched_at"] = 1.0

    wap.UPTIME_PROVIDER = "uptimerobot"
    wap.UPTIME_API_KEY = "dummy"
    wap.UPTIME_MONITOR_ID = ""

    # Now make the live call fail
    def _boom(*_a, **_k):  # noqa: D401
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(wap, "http_request", _boom)

    client = wap.app.test_client()
    resp = client.get("/api/uptime")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data and data.get("ok") is True
    assert data.get("provider") == "uptimerobot"
    # Numbers might be rounded, so compare tolerance
    val = float(data.get("uptime_percentage"))
    assert abs(val - 98.76) < 0.01
