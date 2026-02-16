import sys
import types
import pytest


@pytest.mark.asyncio
async def test_send_admin_report_non_2xx_does_not_call_sync_fallback(monkeypatch):
    import main as main_mod

    monkeypatch.setenv("ALERTMANAGER_API_URL", "https://alertmanager.example")

    class FakeResp:
        status = 400

        async def text(self):
            return "bad request"

    class FakeAsyncCtx:
        async def __aenter__(self):
            return FakeResp()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def fake_http_async_request(_method, _url, **_kwargs):
        return FakeAsyncCtx()

    def fake_http_sync_request(*_a, **_k):
        raise AssertionError("sync fallback should not be called when async returned non-2xx")

    monkeypatch.setitem(sys.modules, "http_async", types.SimpleNamespace(request=fake_http_async_request))
    monkeypatch.setitem(sys.modules, "http_sync", types.SimpleNamespace(request=fake_http_sync_request))

    ok = await main_mod._send_admin_report_via_alertmanager("hello", user_id=1, username="u", display="u")
    assert ok is False


@pytest.mark.asyncio
async def test_send_admin_report_async_exception_calls_sync_fallback(monkeypatch):
    import main as main_mod

    monkeypatch.setenv("ALERTMANAGER_API_URL", "https://alertmanager.example")

    class FakeAsyncCtxRaises:
        async def __aenter__(self):
            raise RuntimeError("network down")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def fake_http_async_request(_method, _url, **_kwargs):
        return FakeAsyncCtxRaises()

    calls = {"n": 0}

    class FakeSyncResp:
        status_code = 200

    def fake_http_sync_request(_method, _url, **_kwargs):
        calls["n"] += 1
        return FakeSyncResp()

    monkeypatch.setitem(sys.modules, "http_async", types.SimpleNamespace(request=fake_http_async_request))
    monkeypatch.setitem(sys.modules, "http_sync", types.SimpleNamespace(request=fake_http_sync_request))

    ok = await main_mod._send_admin_report_via_alertmanager("hello")
    assert ok is True
    assert calls["n"] == 1

