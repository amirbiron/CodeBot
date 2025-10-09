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

class _User: id = 777

class _Upd:
    effective_user = _User()
    message = _Msg()

class _Query:
    def __init__(self):
        self.data = ""
        self.message = _Msg()
        self.from_user = _User()
        self.answered = []
    async def answer(self, *a, **k):
        self.answered.append((a, k))
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
        def get_favorites(self, uid, limit=50):
            # non-empty deterministic list
            return [
                {'file_name': 'a.py', 'programming_language': 'python', 'tags': ['x'], 'code': 'print(1)'},
                {'file_name': 'b.js', 'programming_language': 'javascript', 'tags': [], 'code': 'console.log(1)'},
                {'file_name': 'c.py', 'programming_language': 'python', 'tags': ['y'], 'code': 'print(2)'}
            ]
    db_mod = __import__('database', fromlist=['db'])
    inst = _DB()
    monkeypatch.setattr(db_mod, 'db', inst, raising=True)
    monkeypatch.setattr(bh, 'db', inst, raising=True)
    return bh.AdvancedBotHandlers(_App())

@pytest.mark.asyncio
async def test_export_favorites_json_strict(bot):
    upd = _Upd(); ctx = _Ctx()
    q = _Query(); q.data = "export_favorites"
    await bot.handle_callback_query(types.SimpleNamespace(callback_query=q, effective_user=_User()), ctx)
    # Extract document payload and validate JSON structure and counts
    sent = q.message.sent
    assert sent, "no document was sent"
    found = None
    for args, kwargs in sent:
        for obj in args:
            if isinstance(obj, io.BytesIO):
                found = obj
                break
    assert found is not None, "no BytesIO document found"
    data = found.getvalue().decode('utf-8')
    js = json.loads(data)
    favs = js.get('favorites')
    assert isinstance(favs, list) and len(favs) > 0
    assert js.get('total_favorites') == len(favs)
