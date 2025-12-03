import pytest

from services import observability_http as obs_http
from services import observability_dashboard as obs_dash


def test_is_private_ip_detects_loopback():
    assert obs_http.is_private_ip("127.0.0.1") is True
    assert obs_http.is_private_ip("8.8.8.8") is False


def test_resolve_and_validate_domain_rejects_private(monkeypatch):
    def fake_getaddrinfo(*_args, **_kwargs):
        return [(None, None, None, None, ("10.0.0.5", 0))]

    monkeypatch.setattr(obs_http.socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(obs_http.SecurityError):
        obs_http.resolve_and_validate_domain("example.com")


def test_fetch_graph_securely_rewrites_host(monkeypatch):
    locked_ip = "93.184.216.34"

    def fake_getaddrinfo(*_args, **_kwargs):
        return [(None, None, None, None, (locked_ip, 0))]

    monkeypatch.setattr(obs_http.socket, "getaddrinfo", fake_getaddrinfo)

    class DummyResponse:
        def __init__(self, content: bytes):
            self.content = content

        def raise_for_status(self):
            return None

    class DummySession:
        def __init__(self):
            self.called = {}
            self.mounted = {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def mount(self, prefix, adapter):
            self.mounted[prefix] = adapter

        def get(self, url, headers, timeout, allow_redirects, verify):
            self.called = {
                "url": url,
                "headers": headers,
                "timeout": timeout,
                "allow_redirects": allow_redirects,
                "verify": verify,
            }
            return DummyResponse(b'{"ok": true}')

    dummy_session = DummySession()
    monkeypatch.setattr(obs_http.requests, "Session", lambda: dummy_session)

    payload = obs_http.fetch_graph_securely(
        "https://grafana.example.com/render?panel={panel}",
        panel="45",
    )

    assert payload == b'{"ok": true}'
    assert dummy_session.called["url"].startswith(f"https://{locked_ip}")
    assert dummy_session.called["headers"]["Host"] == "grafana.example.com"
    assert dummy_session.called["allow_redirects"] is False


def test_http_get_json_decodes_payload(monkeypatch):
    monkeypatch.setattr(obs_dash, "fetch_graph_securely", lambda *a, **k: b'{"value": 1}')
    data = obs_dash._http_get_json("https://example.com/path")
    assert data == {"value": 1}


def test_http_get_json_wraps_security_error(monkeypatch):
    def _raise(*_args, **_kwargs):
        raise obs_http.SecurityError("blocked")

    monkeypatch.setattr(obs_dash, "fetch_graph_securely", _raise)
    with pytest.raises(obs_http.SecurityError) as exc:
        obs_dash._http_get_json("https://example.com/path")
    assert "visual_context_fetch_blocked" in str(exc.value)
