import types
import sys


def test_atexit_runtimeerror_creates_new_loop_and_runs(monkeypatch):
    import main

    # Fake http_async.close_session
    calls = {"run": 0, "set_loop": 0, "new_loop": 0}

    async def _close_session():
        # nothing, just awaitable
        return None

    fake_http_async = types.ModuleType("http_async")
    fake_http_async.close_session = _close_session  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "http_async", fake_http_async)

    class _Loop:
        def run_until_complete(self, coro):
            calls["run"] += 1
        def close(self):
            pass

    # get_event_loop raises -> fallback path creates new loop and runs
    def _get_event_loop():
        raise RuntimeError("no loop")

    def _new_event_loop():
        calls["new_loop"] += 1
        return _Loop()

    def _set_event_loop(loop):
        calls["set_loop"] += 1

    fake_asyncio = types.SimpleNamespace(
        get_event_loop=_get_event_loop,
        new_event_loop=_new_event_loop,
        set_event_loop=_set_event_loop,
    )
    monkeypatch.setattr(main, "asyncio", fake_asyncio)

    main._shutdown_http_shared_session()

    assert calls["new_loop"] == 1
    assert calls["set_loop"] == 1
    assert calls["run"] == 1


def test_atexit_loop_exists_but_closed_does_nothing(monkeypatch):
    import main

    # Fake http_async.close_session
    async def _close_session():
        return None

    fake_http_async = types.ModuleType("http_async")
    fake_http_async.close_session = _close_session  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "http_async", fake_http_async)

    class _Loop:
        def is_closed(self):
            return True
        def run_until_complete(self, coro):
            raise AssertionError("should not be called when loop is closed")

    fake_asyncio = types.SimpleNamespace(get_event_loop=lambda: _Loop())
    monkeypatch.setattr(main, "asyncio", fake_asyncio)

    # Should not raise and should not run the coroutine
    main._shutdown_http_shared_session()
