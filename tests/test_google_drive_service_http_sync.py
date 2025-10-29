import types
import json
import builtins
import pytest
import requests


class DummyResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.content = json.dumps(self._body).encode("utf-8") if isinstance(self._body, dict) else (self._body or b"")

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        if isinstance(self._body, (bytes, bytearray)):
            return json.loads(self._body.decode("utf-8"))
        return self._body


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "x")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/db")


def test_start_device_authorization_success(monkeypatch):
    # Arrange
    import services.google_drive_service as gds

    called = {}

    def fake_request(method, url, **kwargs):
        called["args"] = (method, url, kwargs)
        return DummyResponse(200, {
            "verification_url": "https://example.com/verify",
            "user_code": "ABC-123",
            "device_code": "dev-xyz",
            "interval": 5,
            "expires_in": 1800,
        })

    monkeypatch.setattr(gds, "http_request", fake_request)
    # config is evaluated on import; set directly on loaded config
    gds.config.GOOGLE_CLIENT_ID = "cid"

    # Act
    data = gds.start_device_authorization(user_id=1)

    # Assert
    assert data["verification_url"].startswith("https://")
    assert data["user_code"] == "ABC-123"
    assert data["device_code"] == "dev-xyz"
    assert data["interval"] == 5
    assert data["expires_in"] == 1800
    m, u, kw = called["args"]
    assert m == "POST" and isinstance(u, str)


def test_start_device_authorization_http_error(monkeypatch):
    import services.google_drive_service as gds

    def fake_request(method, url, **kwargs):
        raise requests.Timeout("timeout")

    monkeypatch.setattr(gds, "http_request", fake_request)
    gds.config.GOOGLE_CLIENT_ID = "cid"

    with pytest.raises(RuntimeError) as ei:
        gds.start_device_authorization(user_id=1)
    assert "Device auth request error" in str(ei.value)


def test_start_device_authorization_bad_json_not_masked(monkeypatch):
    import services.google_drive_service as gds

    # Return body that will raise on .json()
    class BadJSON:
        def __call__(self):
            raise ValueError("bad json")

    class Resp:
        status_code = 200
        content = b"{not json}"
        def json(self):
            raise ValueError("bad json")

    def fake_request(method, url, **kwargs):
        return Resp()

    monkeypatch.setattr(gds, "http_request", fake_request)
    gds.config.GOOGLE_CLIENT_ID = "cid"

    with pytest.raises(ValueError):
        gds.start_device_authorization(user_id=1)
