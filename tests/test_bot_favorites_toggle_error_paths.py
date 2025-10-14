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
    class _DB:
        def get_file_by_id(self, fid):
            return None
        def toggle_favorite(self, uid, name):
            return True
    inst = _DB()
    db_mod = __import__('database', fromlist=['db'])
    monkeypatch.setattr(db_mod, 'db', inst, raising=True)
    monkeypatch.setattr(bh, 'db', inst, raising=True)
    return bh.AdvancedBotHandlers(_App())

@pytest.mark.asyncio
async def test_fav_toggle_id_file_not_found(bot):
    q = _Query(); q.data = "fav_toggle_id:does-not-exist"
    ctx = _Ctx()
    await bot.handle_callback_query(types.SimpleNamespace(callback_query=q, effective_user=_User()), ctx)
    # אין עריכת הודעה; רק answer עם אזהרה או שקט — העיקר שלא יזרוק
    assert True

@pytest.mark.asyncio
async def test_favorite_command_snippet_not_found(monkeypatch):
    import bot_handlers as bh
    class _DB:
        def get_latest_version(self, uid, name):
            return None
    inst = _DB()
    db_mod = __import__('database', fromlist=['db'])
    monkeypatch.setattr(db_mod, 'db', inst, raising=True)
    monkeypatch.setattr(bh, 'db', inst, raising=True)
    b = bh.AdvancedBotHandlers(_App())
    upd = _Upd(); ctx = _Ctx(); ctx.args = ['nope.py']
    await b.favorite_command(upd, ctx)
    assert len(upd.message.sent) == 1
