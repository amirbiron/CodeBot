import types
import io
import json
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

class _User: id = 321

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
            self._fav = True
        def get_favorites(self, uid, limit=50):
            return [
                {'file_name': 'a.py', 'programming_language': 'python', 'tags': ['x'], 'code': 'print(1)'},
                {'file_name': 'b.js', 'programming_language': 'javascript', 'tags': [], 'code': 'console.log(1)'},
            ]
        def is_favorite(self, uid, name):
            return True
        def get_latest_version(self, uid, name):
            return {'_id': '507f1f77bcf86cd799439011', 'file_name': name, 'code': 'x', 'programming_language': 'python'}
    db_mod = __import__('database', fromlist=['db'])
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)
    return bh.AdvancedBotHandlers(_App())

@pytest.mark.asyncio
async def test_export_favorites_json_content(bot):
    upd = _Upd(); ctx = _Ctx()
    # Trigger export
    q = _Query(); q.data = "export_favorites"
    await bot.handle_callback_query(types.SimpleNamespace(callback_query=q, effective_user=_User()), ctx)
    # Extract document payload and validate JSON
    sent = q.message.sent
    assert sent, "no document was sent"
    # find the document tuple (args, kwargs)
    found = None
    for args, kwargs in sent:
        for obj in args:
            if isinstance(obj, io.BytesIO):
                found = obj
                break
    assert found is not None, "no BytesIO document found"
    data = found.getvalue().decode('utf-8')
    js = json.loads(data)
    assert 'favorites' in js and isinstance(js['favorites'], list) and len(js['favorites']) == 2
    names = [it.get('file_name') for it in js['favorites']]
    assert set(names) == {'a.py', 'b.js'}
