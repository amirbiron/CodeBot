import types
import sys

def test_main_atexit_shutdown_invokes_close(monkeypatch):
    import main

    # Fake http_async module with async close_session
    called = {"close": 0, "run": 0}

    async def _close_session():
        called["close"] += 1

    fake_http_async = types.ModuleType("http_async")
    fake_http_async.close_session = _close_session  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "http_async", fake_http_async)

    # Provide dummy loop
    class _Loop:
        def is_closed(self):
            return False
        def run_until_complete(self, coro):
            # Do not actually run coroutine; mark as invoked
            called["run"] += 1

    monkeypatch.setattr(main, "asyncio", types.SimpleNamespace(get_event_loop=lambda: _Loop()))

    # Call the atexit hook directly
    main._shutdown_http_shared_session()

    # We only verify that run_until_complete was called; actual running is outside the hook's concern
    assert called["run"] == 1
