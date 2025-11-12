import sys
import types


def _install_http_stub(monkeypatch, close_impl):
    fake_http_async = types.ModuleType("http_async")
    fake_http_async.close_session = close_impl  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "http_async", fake_http_async)


def _unexpected(name: str):
    def _raiser(*_a, **_k):
        raise AssertionError(f"unexpected call to {name}")
    return _raiser


def test_main_atexit_shutdown_runs_coroutine_when_loop_idle(monkeypatch):
    import main

    calls = {"close": 0, "run": 0}

    async def _close_session():
        calls["close"] += 1

    _install_http_stub(monkeypatch, _close_session)

    class _Loop:
        def is_closed(self):
            return False

        def is_running(self):
            return False

        def run_until_complete(self, coro):
            calls["run"] += 1
            try:
                coro.send(None)
            except StopIteration:
                pass

    fake_asyncio = types.SimpleNamespace(
        get_event_loop=lambda: _Loop(),
        new_event_loop=_unexpected("new_event_loop"),
        set_event_loop=lambda _loop: None,
    )
    monkeypatch.setattr(main, "asyncio", fake_asyncio)

    main._shutdown_http_shared_session()

    assert calls == {"close": 1, "run": 1}


def test_main_atexit_shutdown_handles_none_coroutine(monkeypatch):
    import main

    calls = {"run": 0}

    def _close_session():
        return None

    _install_http_stub(monkeypatch, _close_session)

    class _Loop:
        def is_closed(self):
            return False

        def is_running(self):
            return False

        def run_until_complete(self, coro):
            calls["run"] += 1

    fake_asyncio = types.SimpleNamespace(
        get_event_loop=lambda: _Loop(),
        new_event_loop=_unexpected("new_event_loop"),
        set_event_loop=lambda _loop: None,
    )
    monkeypatch.setattr(main, "asyncio", fake_asyncio)

    main._shutdown_http_shared_session()

    assert calls["run"] == 0


def test_main_atexit_shutdown_closes_coroutine_on_run_failure(monkeypatch):
    import main

    instances = []

    class _DummyCoro:
        def __init__(self):
            self.closed = False
            self.awaited = False
            instances.append(self)

        def __await__(self):
            self.awaited = True
            yield from ()
            return

        def close(self):
            self.closed = True

    def _close_session():
        return _DummyCoro()

    _install_http_stub(monkeypatch, _close_session)

    class _Loop:
        def is_closed(self):
            return False

        def is_running(self):
            return False

        def run_until_complete(self, coro):
            raise RuntimeError("run failed")

    fake_asyncio = types.SimpleNamespace(
        get_event_loop=lambda: _Loop(),
        new_event_loop=_unexpected("new_event_loop"),
        set_event_loop=lambda _loop: None,
    )
    monkeypatch.setattr(main, "asyncio", fake_asyncio)

    main._shutdown_http_shared_session()

    assert instances, "close_session should have been called"
    dummy = instances[-1]
    assert dummy.closed is True
    assert dummy.awaited is False


def test_main_atexit_shutdown_creates_new_loop_when_running(monkeypatch):
    import main

    events = []

    async def _close_session():
        events.append("close")

    _install_http_stub(monkeypatch, _close_session)

    class _OriginalLoop:
        def is_closed(self):
            return False

        def is_running(self):
            return True

    class _TempLoop:
        def __init__(self):
            self.run_calls = 0

        def run_until_complete(self, coro):
            self.run_calls += 1
            events.append("run")
            try:
                coro.send(None)
            except StopIteration:
                pass

        def close(self):
            events.append("close_loop")

    original_loop = _OriginalLoop()
    temp_loop = _TempLoop()

    def _new_event_loop():
        events.append("new_loop")
        return temp_loop

    def _set_event_loop(loop):
        events.append(("set_loop", loop))

    fake_asyncio = types.SimpleNamespace(
        get_event_loop=lambda: original_loop,
        new_event_loop=_new_event_loop,
        set_event_loop=_set_event_loop,
    )
    monkeypatch.setattr(main, "asyncio", fake_asyncio)

    main._shutdown_http_shared_session()

    assert ("set_loop", temp_loop) in events
    assert ("set_loop", original_loop) in events
    assert temp_loop.run_calls == 1
    assert events.count("new_loop") == 1
    assert "close" in events  # coroutine fully awaited
    assert "close_loop" in events


def test_main_atexit_shutdown_treats_is_running_errors_as_not_running(monkeypatch):
    import main

    calls = {"run": 0, "close": 0}

    async def _close_session():
        calls["close"] += 1

    _install_http_stub(monkeypatch, _close_session)

    class _Loop:
        def is_closed(self):
            return False

        def is_running(self):
            raise RuntimeError("cannot check running state")

        def run_until_complete(self, coro):
            calls["run"] += 1
            try:
                coro.send(None)
            except StopIteration:
                pass

    fake_asyncio = types.SimpleNamespace(
        get_event_loop=lambda: _Loop(),
        new_event_loop=_unexpected("new_event_loop"),
        set_event_loop=lambda _loop: None,
    )
    monkeypatch.setattr(main, "asyncio", fake_asyncio)

    main._shutdown_http_shared_session()

    assert calls["close"] == 1
    assert calls["run"] == 1
