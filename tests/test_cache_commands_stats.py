import importlib
import types
import asyncio


def test_cache_stats_command_best_effort(monkeypatch):
    import cache_commands as cc
    importlib.reload(cc)

    # Fake cache.get_stats
    class _FakeCache:
        def get_stats(self):
            return {"enabled": True, "hit_rate": 90, "keyspace_hits": 10, "keyspace_misses": 1, "used_memory": "1M", "connected_clients": 1}
    monkeypatch.setattr(cc, 'cache', _FakeCache(), raising=True)

    # Fake telegram context/update
    class _Msg:
        def __init__(self):
            self.last = None
        async def reply_text(self, text, parse_mode=None):  # noqa: ARG002
            self.last = text
    class _Upd:
        def __init__(self):
            self.effective_user = types.SimpleNamespace(id=1)
            self.message = _Msg()
    class _Ctx:
        DEFAULT_TYPE = object

    upd = _Upd()
    ctx = _Ctx()

    asyncio.get_event_loop().run_until_complete(cc.cache_stats_command(upd, ctx))
    assert 'Hit Rate' in (upd.message.last or '')
