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
