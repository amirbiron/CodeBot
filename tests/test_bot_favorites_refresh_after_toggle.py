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

class _User: id = 202

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
def bot_and_db(monkeypatch):
    import bot_handlers as bh
    class _DB:
        def __init__(self):
            self._fav = False
            self._docs = {
                'readme.md': {'_id': 'id123', 'file_name': 'readme.md', 'code': '#', 'programming_language': 'markdown'}
            }
        def get_file_by_id(self, fid):
            for d in self._docs.values():
                if d.get('_id') == fid:
                    return d
            return None
        def toggle_favorite(self, uid, name):
            self._fav = not self._fav
            return self._fav
        def get_latest_version(self, uid, name):
            return self._docs.get(name)
    inst = _DB()
    db_mod = __import__('database', fromlist=['db'])
    monkeypatch.setattr(db_mod, 'db', inst, raising=True)
    monkeypatch.setattr(bh, 'db', inst, raising=True)
    return bh.AdvancedBotHandlers(_App()), inst

@pytest.mark.asyncio
async def test_refresh_after_toggle_by_id(bot_and_db):
    bot, _ = bot_and_db
    q = _Query(); q.data = "fav_toggle_id:id123"
    ctx = _Ctx()
    await bot.handle_callback_query(types.SimpleNamespace(callback_query=q, effective_user=_User()), ctx)
    # צפויה עריכת הודעה לרענון (נשלחת כ-edit_message_text)
    assert len(q.message.sent) >= 1

@pytest.mark.asyncio
async def test_refresh_after_toggle_by_token(bot_and_db):
    bot, _ = bot_and_db
    q = _Query(); q.data = "fav_toggle_tok:tok"
    ctx = _Ctx(); ctx.user_data['fav_tokens'] = {'tok': 'readme.md'}
    await bot.handle_callback_query(types.SimpleNamespace(callback_query=q, effective_user=_User()), ctx)
    assert len(q.message.sent) >= 1
