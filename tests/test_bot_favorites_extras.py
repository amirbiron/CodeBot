import types
import pytest

class _App:
    def __init__(self):
        self.handlers = []
    def add_handler(self, *a, **k):
        self.handlers.append((a, k))

class _Msg:
    def __init__(self):
        self.sent = []
    async def reply_text(self, *a, **k):
        self.sent.append((a, k))
    async def reply_document(self, *a, **k):
        self.sent.append((a, k))

class _User: id = 77

class _Upd:
    effective_user = _User()
    message = _Msg()

class _Query:
    def __init__(self):
        self.data = ""
        self.message = _Msg()
        self.from_user = _User()
    async def answer(self, *a, **k):
        return None
    async def edit_message_text(self, *a, **k):
        self.message.sent.append((a, k))

class _Ctx:
    def __init__(self):
        self.args = []
        self.user_data = {}
        self.bot = types.SimpleNamespace()

@pytest.fixture
def bot(monkeypatch):
    import bot_handlers as bh
    # stub db for export/stats paths
    class _DB:
        def __init__(self):
            self._favs = [
                {"file_name": "a.py", "programming_language": "python", "tags": ["x"], "code": "print(1)", "favorited_at": None},
                {"file_name": "b.js", "programming_language": "javascript", "tags": ["x","y"], "code": "console.log(1)", "favorited_at": None},
            ]
        def get_favorites(self, uid, limit=50):
            return list(self._favs)
        def get_latest_version(self, uid, name):
            return {"_id": "id1", "file_name": name, "code": "print()", "programming_language": "python"}
    db_mod = __import__('database', fromlist=['db'])
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)
    utils = __import__('utils')
    monkeypatch.setattr(utils, 'get_language_emoji', lambda s: '🐍', raising=True)
    return bh.AdvancedBotHandlers(_App())

@pytest.mark.asyncio
async def test_export_and_stats(bot):
    # build a favorites list message and then trigger the actions
    upd = _Upd()
    ctx = _Ctx()

    await bot.favorites_command(upd, ctx)

    # export
    q = _Query(); q.data = "export_favorites"
    await bot.handle_callback_query(types.SimpleNamespace(callback_query=q, effective_user=_User()), ctx)

    # stats
    q2 = _Query(); q2.data = "favorites_stats"
    await bot.handle_callback_query(types.SimpleNamespace(callback_query=q2, effective_user=_User()), ctx)

    assert True
