import types
import pytest

import importlib


@pytest.mark.asyncio
async def test_correlation_layer_registers_typehandler(monkeypatch):
    # Minimal stubs for builder
    class _MiniApp:
        def __init__(self):
            self.handlers = []
            self.bot_data = {}
            class _JQ:
                def run_once(self, *a, **k):
                    return None
            self.job_queue = _JQ()
        def add_handler(self, handler, group=None):
            self.handlers.append((handler, group))
        def add_error_handler(self, *a, **k):
            pass
        def remove_handler(self, *a, **k):
            pass

    class _Builder:
        def token(self, *a, **k):
            return self
        def defaults(self, *a, **k):
            return self
        def persistence(self, *a, **k):
            return self
        def post_init(self, *a, **k):
            return self
        def build(self):
            return _MiniApp()

    class _AppNS:
        def builder(self):
            return _Builder()

    import main as mod
    import config as cfg
    importlib.reload(cfg)
    importlib.reload(mod)

    monkeypatch.setattr(mod, 'Application', _AppNS())

    bot = mod.CodeKeeperBot()

    # verify a handler with group = -100 exists (correlation layer)
    groups = [g for h, g in bot.application.handlers]
    assert -100 in groups


@pytest.mark.asyncio
async def test_tracing_layer_wraps_process_update(monkeypatch):
    call_log = []

    class _MiniApp:
        def __init__(self):
            self.handlers = []
            self.bot_data = {}
            self._codebot_tracing_installed = False

        async def process_update(self, update, *args, **kwargs):
            call_log.append(("original", getattr(update, "update_id", None)))

        def add_handler(self, handler, group=None):
            self.handlers.append((handler, group))

        def add_error_handler(self, *_a, **_k):
            pass

        def remove_handler(self, *_a, **_k):
            pass

    class _Builder:
        def token(self, *a, **k):
            return self

        def defaults(self, *a, **k):
            return self

        def persistence(self, *a, **k):
            return self

        def post_init(self, *a, **k):
            return self

        def build(self):
            return _MiniApp()

    class _AppNS:
        def builder(self):
            return _Builder()

    span_events: list[tuple[str, object]] = []

    class _DummySpan:
        def __init__(self) -> None:
            self.attributes: list[tuple[str, object]] = []

        def set_attribute(self, key: str, value: object) -> None:
            self.attributes.append((key, value))
            span_events.append(("set_attribute", (key, value)))

    class _DummySpanContext:
        def __init__(self, name: str, attrs: dict[str, object]):
            self.name = name
            self.attrs = attrs

        def __enter__(self):
            span_events.append(("enter", (self.name, self.attrs)))
            return _DummySpan()

        def __exit__(self, exc_type, exc, tb):
            span_events.append(("exit", exc_type))
            return False

    def _fake_start_span(name: str, attrs: dict[str, object]) -> _DummySpanContext:
        span_events.append(("start", (name, attrs)))
        return _DummySpanContext(name, attrs)

    def _fake_set_current(attrs: dict[str, object]) -> None:
        span_events.append(("set_current", attrs))

    import observability_instrumentation as oi

    monkeypatch.setattr(oi, "start_span", _fake_start_span, raising=False)
    monkeypatch.setattr(oi, "set_current_span_attributes", _fake_set_current, raising=False)

    import main as mod
    import config as cfg
    importlib.reload(cfg)
    importlib.reload(mod)

    monkeypatch.setattr(mod, 'Application', _AppNS())

    bot = mod.CodeKeeperBot()

    class _DummyMessage:
        text = "/start"

    class _DummyUpdate:
        update_id = 42
        message = _DummyMessage()

    update = _DummyUpdate()

    await bot.application.process_update(update)

    assert ("original", 42) in call_log
    start_events = [evt for evt in span_events if evt[0] == "start"]
    assert start_events and start_events[0][1][0] == "bot.update"
