import types
import io
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
        # capture document for assertions
        self.sent.append((a, k))

class _User: id = 123

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
        def __init__(self):
            self._fav = False
            self._docs = {
                'readme.md': {
                    '_id': '507f1f77bcf86cd799439011', 'file_name': 'readme.md', 'code': '# hi', 'programming_language': 'markdown'
                }
            }
        def get_latest_version(self, uid, name):
            return self._docs.get(name)
        def get_file_by_id(self, fid):
            # החזר את המסמך לפי _id המדומה
            for d in self._docs.values():
                if d.get('_id') == fid:
                    return d
            return None
        def is_favorite(self, uid, name):
            return self._fav
        def toggle_favorite(self, uid, name):
            self._fav = not self._fav
            return self._fav
        def get_favorites(self, uid, limit=50):
            return ([{'file_name': 'readme.md', 'programming_language': 'markdown', 'tags': [], 'code': '# hi'}] if self._fav else [])
    db_mod = __import__('database', fromlist=['db'])
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)
    utils = __import__('utils')
    monkeypatch.setattr(utils, 'get_language_emoji', lambda s: '📝', raising=True)
    return bh.AdvancedBotHandlers(_App())

@pytest.mark.asyncio
async def test_show_add_favorite_via_id_and_export(bot):
    upd = _Upd()
    ctx = _Ctx()
    # show readme.md -> should build favorite button with id path
    ctx.args = ['readme.md']
    await bot.show_command(upd, ctx)

    # simulate pressing the favorite toggle button by id
    q = _Query(); q.data = "fav_toggle_id:507f1f77bcf86cd799439011"
    await bot.handle_callback_query(types.SimpleNamespace(callback_query=q, effective_user=_User()), ctx)

    # now /favorites should have one, and export should produce a document
    await bot.favorites_command(upd, ctx)

    q2 = _Query(); q2.data = "export_favorites"
    await bot.handle_callback_query(types.SimpleNamespace(callback_query=q2, effective_user=_User()), ctx)

    # Validate that a document was queued for sending (reply_document called on query.message)
    sent = q2.message.sent
    assert len(sent) >= 1
