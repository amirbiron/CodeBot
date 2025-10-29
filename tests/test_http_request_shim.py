import types


def test_http_request_get_uses_requests_get(monkeypatch):
    import github_menu_handler as gh

    calls = []

    class _Resp:
        pass

    def _stub_get(url, **kwargs):
        calls.append({"url": url, "kwargs": kwargs})
        return _Resp()

    # If this is called in this test, we want to know
    def _should_not_be_called(*args, **kwargs):  # pragma: no cover - guard
        raise AssertionError("_http_sync_request should not be called for GET when requests.get is patched")

    monkeypatch.setattr(gh.requests, "get", _stub_get)
    monkeypatch.setattr(gh, "_http_sync_request", _should_not_be_called)

    resp = gh.http_request("GET", "https://example.com/data", headers={"A": "B"}, stream=True, timeout=1)

    assert isinstance(resp, _Resp)
    assert calls and calls[0]["url"] == "https://example.com/data"
    assert calls[0]["kwargs"].get("stream") is True


def test_requests_shim_get_delegates_to__http_sync_request(monkeypatch):
    import github_menu_handler as gh

    sentinel = object()
    recorded = types.SimpleNamespace(calls=0, last=None)

    def _stub_sync_request(method, url, **kwargs):
        recorded.calls += 1
        recorded.last = (method, url, kwargs)
        assert method == "GET"
        return sentinel

    # Do not patch gh.requests.get so the shim path executes
    monkeypatch.setattr(gh, "_http_sync_request", _stub_sync_request)

    resp = gh.http_request("GET", "https://example.com/zip", stream=True)

    assert resp is sentinel
    assert recorded.calls == 1
    assert recorded.last[0] == "GET"
    assert recorded.last[1] == "https://example.com/zip"
    assert recorded.last[2].get("stream") is True


def test_http_request_non_get_calls__http_sync_request(monkeypatch):
    import github_menu_handler as gh

    sentinel = object()
    seen = {}

    def _stub_sync_request(method, url, **kwargs):
        seen["method"] = method
        seen["url"] = url
        seen["kwargs"] = kwargs
        return sentinel

    # Ensure non-GET goes straight to the underlying request impl
    monkeypatch.setattr(gh, "_http_sync_request", _stub_sync_request)

    resp = gh.http_request("POST", "https://example.com/upload", data=b"x=1")

    assert resp is sentinel
    assert seen.get("method") == "POST"
    assert seen.get("url") == "https://example.com/upload"
    assert seen.get("kwargs", {}).get("data") == b"x=1"
