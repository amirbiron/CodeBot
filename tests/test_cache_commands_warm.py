import importlib
import types


def test_cache_commands_warm(monkeypatch):
    # Fake DB like in /api/stats
    class _Coll:
        def aggregate(self, *a, **k):  # noqa: ARG002
            return []
        def count_documents(self, *a, **k):  # noqa: ARG002
            return 1
        def distinct(self, *a, **k):  # noqa: ARG002
            return ["python"]
        def find(self, *a, **k):  # noqa: ARG002
            class _C:
                def sort(self, *a, **k):
                    return self
                def limit(self, *a, **k):
                    return [{"file_name": "a.py", "created_at": __import__('datetime').datetime.now(__import__('datetime').timezone.utc)}]
            return _C()
    class _DB:
        code_snippets = _Coll()
    def _get_db():
        return _DB()

    # Shim webapp.app.get_db for cache_commands module
    monkeypatch.setitem(importlib.sys.modules, 'webapp.app', types.SimpleNamespace(get_db=_get_db))

    # Fake cache with set_dynamic
    class _Cache:
        def set_dynamic(self, *a, **k):  # noqa: ARG002
            return True
    fake_cache = _Cache()

    # Patch cache_commands.cache to fake cache
    import cache_commands as cc
    importlib.reload(cc)
    monkeypatch.setattr(cc, 'cache', fake_cache, raising=True)

    # Fake Telegram update/context
    class _Msg:
        def __init__(self):
            self.last = None
        async def reply_text(self, text, parse_mode=None):  # noqa: ARG002
            self.last = text
    class _Upd:
        def __init__(self):
            self.effective_user = types.SimpleNamespace(id=7)
            self.message = _Msg()
    class _Ctx:
        DEFAULT_TYPE = object

    upd = _Upd()
    ctx = _Ctx()

    # Run command
    import asyncio
    asyncio.get_event_loop().run_until_complete(cc.cache_warm_command(upd, ctx))

    assert isinstance(upd.message.last, str)
    assert 'קאש' in upd.message.last or 'ok' in upd.message.last.lower()
