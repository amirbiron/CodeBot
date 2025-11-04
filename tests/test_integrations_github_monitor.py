import types
import pytest

import integrations_github_monitor as mon
import http_async as ha


@pytest.mark.asyncio
async def test_summarize_rate_limit_and_fetch(monkeypatch):
    # Patch aiohttp ClientSession to avoid network
    class _Resp:
        async def json(self):
            return {"resources": {"core": {"limit": 100, "remaining": 75}}}
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
        async def release(self):
            return None

    class _Ctx:
        def __init__(self, resp):
            self._resp = resp
        async def __aenter__(self):
            return self._resp
        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        ha,
        "request",
        lambda *a, **k: _Ctx(_Resp()),
        raising=False,
    )

    data = await mon.fetch_rate_limit(token="t")
    s = mon.summarize_rate_limit(data)
    assert s["limit"] == 100 and s["remaining"] == 75 and s["used_pct"] == 25
