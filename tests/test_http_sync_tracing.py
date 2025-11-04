import types
import pytest


class _DummyResponse:
    def __init__(self, status_code: int = 200, history_len: int = 0) -> None:
        self.status_code = status_code

        class _Retries:
            def __init__(self, length: int) -> None:
                self.history = [object()] * length

        class _Raw:
            def __init__(self, length: int) -> None:
                self.retries = _Retries(length)

        self.raw = _Raw(history_len)


def _install_span_stubs(monkeypatch):
    events: list[tuple[str, object]] = []

    class _Span:
        def set_attribute(self, key: str, value: object) -> None:
            events.append(("attr", key, value))

    class _SpanCtx:
        def __init__(self, name: str, attrs: dict[str, object]) -> None:
            events.append(("start", (name, attrs)))
            self.name = name

        def __enter__(self):
            events.append(("enter", self.name))
            return _Span()

        def __exit__(self, exc_type, exc, tb):
            events.append(("exit", exc_type))
            return False

    import http_sync

    def _fake_start_span(name: str, attrs: dict[str, object]) -> _SpanCtx:
        return _SpanCtx(name, attrs)

    def _fake_set_current(attrs: dict[str, object]) -> None:
        events.append(("set_current", attrs))

    monkeypatch.setattr(http_sync, "start_span", _fake_start_span, raising=False)
    monkeypatch.setattr(http_sync, "set_current_span_attributes", _fake_set_current, raising=False)

    return events


def test_http_sync_request_records_attributes(monkeypatch):
    events = _install_span_stubs(monkeypatch)

    class _Session:
        def request(self, *args, **kwargs):
            return _DummyResponse(status_code=201, history_len=2)

    import http_sync

    monkeypatch.setattr(http_sync, "get_session", lambda: _Session())

    resp = http_sync.request("GET", "https://example.com")
    assert resp.status_code == 201

    # span started with expected attributes
    start_events = [evt for evt in events if evt[0] == "start"]
    assert start_events and start_events[0][1][0] == "http.client"

    attr_pairs = [(key, value) for kind, key, value in (evt for evt in events if evt[0] == "attr")]
    assert ("http.status_code", 201) in attr_pairs
    assert any(key == "retry_count" and value == 2 for key, value in attr_pairs)


def test_http_sync_request_propagates_exceptions(monkeypatch):
    events = _install_span_stubs(monkeypatch)

    class _Session:
        def request(self, *args, **kwargs):
            raise RuntimeError("boom")

    import http_sync

    monkeypatch.setattr(http_sync, "get_session", lambda: _Session())

    with pytest.raises(RuntimeError):
        http_sync.request("POST", "https://example.com")

    exit_events = [evt for evt in events if evt[0] == "exit"]
    assert exit_events and exit_events[0][1] is RuntimeError


def test_http_sync_retries_on_http_error(monkeypatch):
    import http_sync

    # Speed up retries in CI: eliminate backoff sleep
    monkeypatch.setenv("HTTP_RESILIENCE_BACKOFF_BASE", "0.0")
    monkeypatch.setenv("HTTP_RESILIENCE_BACKOFF_MAX", "0.0")
    monkeypatch.setenv("HTTP_RESILIENCE_JITTER", "0.0")

    class _Session:
        def __init__(self):
            self.calls = 0

        def request(self, *args, **kwargs):
            self.calls += 1

            class _Resp:
                def __init__(self, status_code):
                    self.status_code = status_code

                raw = types.SimpleNamespace(retries=types.SimpleNamespace(history=[object(), object()]))

                def close(self):
                    return None

            if self.calls < 3:
                return _Resp(502)
            return _Resp(200)

    session = _Session()
    monkeypatch.setattr(http_sync, "get_session", lambda: session, raising=False)

    statuses: list[str] = []
    retries: list[tuple[str, str]] = []

    monkeypatch.setattr(
        http_sync,
        "note_request_duration",
        lambda service, endpoint, status, duration: statuses.append(status),
    )
    monkeypatch.setattr(
        http_sync,
        "note_retry",
        lambda service, endpoint: retries.append((service, endpoint)),
    )

    resp = http_sync.request(
        "GET",
        "https://api.test.example/v1/status",
        backoff_base=0.0,
        backoff_cap=0.0,
        jitter=0.0,
        max_attempts=3,
    )
    assert resp.status_code == 200

    assert statuses.count("http_error") == 2
    assert statuses[-1] == "success"
    assert len(retries) == 2
    assert session.calls == 3
