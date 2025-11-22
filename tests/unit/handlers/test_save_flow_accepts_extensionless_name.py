import types
import asyncio
import os


def test_save_flow_accepts_extensionless_name(monkeypatch):
    # Ensure old flow path (simpler to stub)
    monkeypatch.delenv('USE_NEW_SAVE_FLOW', raising=False)

    import handlers.save_flow as sf

    # Stub database module used inside save_flow
    db_mod = types.ModuleType('database')

    class _DB:
        def get_latest_version(self, user_id, filename):
            return None

    db_mod.db = _DB()
    monkeypatch.setitem(__import__('sys').modules, 'database', db_mod)

    class _User:
        id = 1

    class _Msg:
        def __init__(self, text):
            self.text = text
            self.from_user = _User()

        async def reply_text(self, *a, **k):
            return None

    class _Update:
        def __init__(self, text):
            self.message = _Msg(text)

    class _Ctx:
        def __init__(self):
            self.user_data = {}

    update = _Update("Dockerfile")
    ctx = _Ctx()

    result = asyncio.run(sf.get_filename(update, ctx))
    assert result == sf.GET_NOTE
    assert ctx.user_data.get("pending_filename") == "Dockerfile"
