import os
import types
import pytest


def test_get_session_builds_with_env_and_reuses(monkeypatch):
    import http_async as ha

    captured: dict[str, dict] = {}

    class _Timeout:
        def __init__(self, **k):
            captured["timeout_ctor"] = k

    class _Connector:
        def __init__(self, **k):
            captured["connector_ctor"] = k

    class _Session:
        def __init__(self, **k):
            captured["session_kwargs"] = k
            self._closed = False
        @property
        def closed(self):
            return self._closed
        async def close(self):
            self._closed = True

    # Env tuning
    monkeypatch.setenv("AIOHTTP_TIMEOUT_TOTAL", "12")
    monkeypatch.setenv("AIOHTTP_POOL_LIMIT", "77")
    monkeypatch.setenv("AIOHTTP_LIMIT_PER_HOST", "33")

    monkeypatch.setattr(
        ha,
        "aiohttp",
        types.SimpleNamespace(ClientSession=_Session, ClientTimeout=_Timeout, TCPConnector=_Connector),
        raising=False,
    )
    monkeypatch.setattr(ha, "_session", None, raising=False)

    s1 = ha.get_session()
    s2 = ha.get_session()
    assert s1 is s2

    # Verify kwargs passed through
    assert "timeout" in captured["session_kwargs"] and "connector" in captured["session_kwargs"]
    assert captured["timeout_ctor"].get("total") == 12
    assert captured["connector_ctor"].get("limit") == 77
    assert captured["connector_ctor"].get("limit_per_host") == 33


@pytest.mark.asyncio
async def test_close_session_idempotent(monkeypatch):
    import http_async as ha

    class _Session:
        def __init__(self):
            self._closed = False
        @property
        def closed(self):
            return self._closed
        async def close(self):
            self._closed = True

    ha._session = _Session()  # type: ignore[attr-defined]
    await ha.close_session()
    assert getattr(ha, "_session", None) is None
    # Second call should be safe
    await ha.close_session()


def test_limit_per_host_zero_sets_none(monkeypatch):
    import http_async as ha

    captured: dict[str, dict] = {}

    class _Timeout:
        def __init__(self, **k):
            pass

    class _Connector:
        def __init__(self, **k):
            captured.update(k)

    class _Session:
        def __init__(self, **k):
            pass
        @property
        def closed(self):
            return False

    monkeypatch.setenv("AIOHTTP_TIMEOUT_TOTAL", "10")
    monkeypatch.setenv("AIOHTTP_POOL_LIMIT", "20")
    monkeypatch.setenv("AIOHTTP_LIMIT_PER_HOST", "0")

    monkeypatch.setattr(
        ha,
        "aiohttp",
        types.SimpleNamespace(ClientSession=_Session, ClientTimeout=_Timeout, TCPConnector=_Connector),
        raising=False,
    )
    monkeypatch.setattr(ha, "_session", None, raising=False)

    _ = ha.get_session()
    assert captured.get("limit_per_host") is None


@pytest.mark.asyncio
async def test_async_request_retries_on_http_error(monkeypatch):
    import http_async as ha

    # Speed up retries in CI: eliminate backoff sleep
    monkeypatch.setenv("HTTP_RESILIENCE_BACKOFF_BASE", "0.0")
    monkeypatch.setenv("HTTP_RESILIENCE_BACKOFF_MAX", "0.0")
    monkeypatch.setenv("HTTP_RESILIENCE_JITTER", "0.0")

    class _Resp:
        def __init__(self, status: int):
            self.status = status
            self._released = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            await self.release()
            return False

        async def release(self):
            self._released = True

    class _Session:
        def __init__(self):
            self.calls = 0

        async def request(self, method, url, **kwargs):
            self.calls += 1
            if self.calls < 3:
                return _Resp(503)
            return _Resp(200)

    session = _Session()
    monkeypatch.setattr(ha, "get_session", lambda: session, raising=False)

    statuses: list[str] = []
    retries: list[tuple[str, str]] = []

    monkeypatch.setattr(
        ha,
        "note_request_duration",
        lambda service, endpoint, status, duration: statuses.append(status),
    )
    monkeypatch.setattr(
        ha,
        "note_retry",
        lambda service, endpoint: retries.append((service, endpoint)),
    )

    async with ha.request("GET", "https://service.example/api/resource") as resp:
        assert resp.status == 200

    assert statuses.count("http_error") == 2
    assert statuses[-1] == "success"
    assert len(retries) == 2
    assert session.calls == 3
