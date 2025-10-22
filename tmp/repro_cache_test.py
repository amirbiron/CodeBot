import types, importlib, asyncio, os, sys

# Shim observability (collect events)
captured = {"evts": []}
fake_obs = types.SimpleNamespace(
    setup_structlog_logging=lambda *_a, **_k: None,
    init_sentry=lambda: None,
    bind_request_id=lambda *_a, **_k: None,
    generate_request_id=lambda: "",
    emit_event=lambda evt, severity="info", **kw: captured["evts"].append((evt, severity, kw)),
)
sys.modules["observability"] = fake_obs

# Fake cache that tracks calls to clear_stale
called = {"n": 0}
fake_cache = types.SimpleNamespace(clear_stale=lambda **_k: (called.__setitem__('n', called['n'] + 1) or 2))
sys.modules["cache_manager"] = types.SimpleNamespace(cache=fake_cache)

import main as m

class _JobQ:
    def run_repeating(self, fn, interval, first, name=None):  # noqa: ARG002
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # mimic test env raising when nested run_until_complete is called
            raise RuntimeError("Event loop is running")
        loop.run_until_complete(fn(None))

class _Bot:
    async def delete_my_commands(self):
        return None
    async def set_my_commands(self, *a, **k):  # noqa: ARG002
        return None

class _App:
    job_queue = _JobQ()
    bot = _Bot()

app = _App()

# Ensure background cleanup not disabled
os.environ.pop('DISABLE_BACKGROUND_CLEANUP', None)

loop = asyncio.get_event_loop()
loop.run_until_complete(m.setup_bot_data(app))

print("called_n", called['n'])
print("events", [e[0] for e in captured['evts']])
