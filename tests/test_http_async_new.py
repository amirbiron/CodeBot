from __future__ import annotations

import asyncio
import pytest


def test_normalize_headers_various_types():
    import http_async as ha

    assert ha._normalize_headers(None) == {}
    assert ha._normalize_headers({"A": 1}) == {"A": "1"}
    class Obj:
        def __iter__(self):
            return iter([("B", 2)])
    assert ha._normalize_headers(Obj()) == {"B": "2"}


def test_prepare_headers_with_observability(monkeypatch):
    import http_async as ha

    def fake_prepare(base):
        return {"X-Request-ID": "rid"}

    monkeypatch.setattr("observability.prepare_outgoing_headers", fake_prepare, raising=False)
    prepared = ha._prepare_headers(None)
    # May be a CIMultiDict or a plain dict, but should include our key
    assert dict(prepared).get("X-Request-ID") == "rid"


@pytest.mark.asyncio
async def test_instrument_session_wraps_request(monkeypatch):
    import http_async as ha

    async def fake_request(method, url, **kwargs):
        # Return headers to validate injection
        return kwargs.get("headers")

    class DummySession:
        def __init__(self):
            self._request = fake_request
            self._loop = asyncio.get_event_loop()
            self.closed = False

    # Ensure _prepare_headers produces something predictable
    monkeypatch.setattr(ha, "_prepare_headers", lambda h: {"A": "1"})
    s = DummySession()
    ha._instrument_session(s)
    result = await s._request("GET", "http://x", headers={"B": "2"})
    assert dict(result) == {"A": "1"}


@pytest.mark.asyncio
async def test_close_session_resets_global_session(monkeypatch):
    import http_async as ha

    class Dummy:
        def __init__(self):
            self.closed = False

        async def close(self):
            self.closed = True

    dummy = Dummy()
    ha._session = dummy
    await ha.close_session()
    assert ha._session is None
