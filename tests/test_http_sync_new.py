from __future__ import annotations

import types


def test_merge_observability_headers_prefers_observability(monkeypatch):
    import http_sync as hs

    def fake_prepare(base):
        return {"A": "1"}

    monkeypatch.setattr("observability.prepare_outgoing_headers", fake_prepare, raising=False)
    merged = hs._merge_observability_headers(None)
    assert merged == {"A": "1"}


def test_request_uses_merged_headers_and_respects_slow_logging(monkeypatch):
    import http_sync as hs

    captured = {}

    class FakeResp:
        status_code = 200

    class FakeSession:
        def request(self, *, method, url, timeout, **kwargs):
            captured["method"] = method
            captured["url"] = url
            captured["timeout"] = timeout
            captured["headers"] = dict(kwargs.get("headers") or {})
            return FakeResp()

    # Patch get_session to return our fake session
    monkeypatch.setattr(hs, "get_session", lambda: FakeSession())
    # Simulate a slow request (200ms) with a NON-exhausting clock: first read is
    # t0, every later read is t0+200ms. A plain 2-element pop() is fragile — this
    # patches the *global* time module, so any extra perf_counter() call (an error
    # path, metrics, logging) drains the list and raises IndexError.
    import itertools

    ticks = itertools.chain([100.0], itertools.repeat(100.2))
    monkeypatch.setattr(hs.time, "perf_counter", lambda: next(ticks))

    # Ensure merged headers come from our merger
    monkeypatch.setattr(hs, "_merge_observability_headers", lambda h: {"X": "Y"})

    resp = hs.request("GET", "http://example", headers={"Foo": "Bar"})
    assert isinstance(resp, FakeResp)
    assert captured["headers"] == {"X": "Y"}


def test_get_session_reuses_thread_local():
    import http_sync as hs

    s1 = hs.get_session()
    s2 = hs.get_session()
    assert s1 is s2
