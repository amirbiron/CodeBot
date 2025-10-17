import importlib
import os
import types


def _install_fake_redis(monkeypatch, last_kwargs_box):
    class _FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
        def ping(self):
            return True
    def from_url(url, **kwargs):  # noqa: ARG001 - used for side effects
        last_kwargs_box["kwargs"] = dict(kwargs)
        return _FakeClient(**kwargs)
    fake_mod = types.SimpleNamespace(from_url=from_url)
    monkeypatch.setitem(importlib.import_module('sys').modules, 'redis', fake_mod)


def test_connect_respects_env_timeouts(monkeypatch):
    # Arrange: fake redis module to capture kwargs
    last = {}
    _install_fake_redis(monkeypatch, last)

    # Env: explicit timeouts
    monkeypatch.setenv('REDIS_URL', 'redis://localhost:6379/0')
    monkeypatch.setenv('REDIS_CONNECT_TIMEOUT', '2')
    monkeypatch.setenv('REDIS_SOCKET_TIMEOUT', '3')
    monkeypatch.delenv('SAFE_MODE', raising=False)

    # Reload module to pick fake redis and env
    cm = importlib.import_module('cache_manager')
    importlib.reload(cm)

    # Act
    mgr = cm.CacheManager()

    # Assert: timeouts from env are honored
    assert float(last["kwargs"].get("socket_connect_timeout")) == 2.0
    assert float(last["kwargs"].get("socket_timeout")) == 3.0


def test_connect_safe_mode_defaults_to_1s(monkeypatch):
    # Arrange: fake redis again
    last = {}
    _install_fake_redis(monkeypatch, last)

    # Env: SAFE_MODE enabled, no explicit timeouts
    monkeypatch.setenv('REDIS_URL', 'redis://localhost:6379/0')
    monkeypatch.setenv('SAFE_MODE', '1')
    monkeypatch.delenv('REDIS_CONNECT_TIMEOUT', raising=False)
    monkeypatch.delenv('REDIS_SOCKET_TIMEOUT', raising=False)

    cm = importlib.import_module('cache_manager')
    importlib.reload(cm)

    # Act
    _ = cm.CacheManager()

    # Assert: defaults to 1s when in SAFE_MODE
    assert float(last["kwargs"].get("socket_connect_timeout")) == 1.0
    assert float(last["kwargs"].get("socket_timeout")) == 1.0


def test_clear_stale_skips_in_safe_mode(monkeypatch):
    import cache_manager as cm
    importlib.reload(cm)

    monkeypatch.setenv('SAFE_MODE', '1')

    mgr = cm.CacheManager()
    mgr.is_enabled = True

    class _NoPingClient:
        def ping(self):  # should not be called under SAFE_MODE
            raise AssertionError("ping should not be called in SAFE_MODE")

    mgr.redis_client = _NoPingClient()

    assert mgr.clear_stale() == 0


def test_clear_stale_returns_quickly_when_ping_fails(monkeypatch):
    import cache_manager as cm
    importlib.reload(cm)

    monkeypatch.setenv('SAFE_MODE', '0')

    mgr = cm.CacheManager()
    mgr.is_enabled = True

    class _FailPingClient:
        def ping(self):
            raise RuntimeError("redis down")

    mgr.redis_client = _FailPingClient()

    assert mgr.clear_stale() == 0


def test_clear_stale_budget_limits_work(monkeypatch):
    import cache_manager as cm
    importlib.reload(cm)

    monkeypatch.setenv('SAFE_MODE', '0')
    monkeypatch.setenv('CACHE_CLEAR_BUDGET_SECONDS', '0.000001')

    mgr = cm.CacheManager()
    mgr.is_enabled = True

    class _Client:
        def ping(self):
            return True
        def scan_iter(self, match='*', count=500):  # noqa: ARG002
            for i in range(1000):
                yield f"k{i}"
        def ttl(self, key):  # noqa: ARG002
            return -2  # treat as expired to trigger delete
        def delete(self, key):  # noqa: ARG002
            return 1

    mgr.redis_client = _Client()

    n = mgr.clear_stale(max_scan=1000)
    # Should stop early due to budget; definitely less than full 1000
    assert 0 <= n <= 10


def test_predictive_engine_safe_mode_skip(monkeypatch):
    import predictive_engine as pe
    importlib.reload(pe)

    # Enable SAFE_MODE
    monkeypatch.setenv('SAFE_MODE', '1')

    # Capture emitted events
    events = []
    def _emit(event, severity="info", **fields):  # noqa: ARG001
        events.append(event)
    monkeypatch.setattr(pe, 'emit_event', _emit)

    # Make cache explode if called (it shouldn't)
    class _Boom:
        def clear_stale(self):
            raise AssertionError("clear_stale should not be called in SAFE_MODE")
    monkeypatch.setattr(pe, '_cache', _Boom())

    tr = pe.Trend(metric="latency_seconds", slope_per_minute=1.0, intercept=0.0, current_value=1.0, threshold=0.5, predicted_cross_ts=123.0)

    pe._trigger_preemptive_action(tr)

    assert "PREDICTIVE_ACTION_SKIPPED" in events
