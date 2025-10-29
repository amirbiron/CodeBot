import http_sync
import types


class _DummyLogger:
    def __init__(self):
        self.records = []
    def warning(self, msg, extra=None):
        self.records.append((msg, extra or {}))


def test_http_sync_slow_log(monkeypatch):
    # Force threshold low
    monkeypatch.setenv("HTTP_SLOW_MS", "0.1")

    # Patch logger only within http_sync module
    dummy = _DummyLogger()
    monkeypatch.setattr(http_sync, "logging", types.SimpleNamespace(getLogger=lambda *a, **k: dummy))

    # Patch session.request to simulate ~0.2ms elapsed via perf_counter delta
    class _Sess:
        def request(self, **kwargs):
            class _Resp:
                status_code = 200
            return _Resp()
    monkeypatch.setattr(http_sync, "get_session", lambda: _Sess())

    # Patch perf_counter to simulate elapsed > threshold
    counters = [0.0, 0.0003]
    monkeypatch.setattr(http_sync.time, "perf_counter", lambda: counters.pop(0))

    http_sync.request("GET", "http://example.com")

    assert any(msg == "slow_http" for msg, _ in dummy.records)
