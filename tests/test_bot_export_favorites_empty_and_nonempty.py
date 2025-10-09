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

class _User: id = 9

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

@pytest.mark.asyncio
async def test_export_favorites_empty(bot_empty):
    upd = _Upd(); ctx = _Ctx()
    q = _Query(); q.data = "export_favorites"
    await bot_empty.handle_callback_query(types.SimpleNamespace(callback_query=q, effective_user=_User()), ctx)
    sent = q.message.sent
    assert sent
    # Extract JSON and assert total_favorites == 0
    bio = next(obj for args, _ in sent for obj in args if isinstance(obj, io.BytesIO))
    js = json.loads(bio.getvalue().decode('utf-8'))
    assert js.get('total_favorites') == 0
    assert isinstance(js.get('favorites'), list) and len(js.get('favorites')) == 0

@pytest.mark.asyncio
async def test_export_favorites_nonempty(bot_nonempty):
    upd = _Upd(); ctx = _Ctx()
    q = _Query(); q.data = "export_favorites"
    await bot_nonempty.handle_callback_query(types.SimpleNamespace(callback_query=q, effective_user=_User()), ctx)
    sent = q.message.sent
    assert sent
    bio = next(obj for args, _ in sent for obj in args if isinstance(obj, io.BytesIO))
    js = json.loads(bio.getvalue().decode('utf-8'))
    assert js.get('total_favorites') == 2
    assert isinstance(js.get('favorites'), list) and len(js.get('favorites')) == 2

@pytest.fixture
def bot_empty(monkeypatch):
    import bot_handlers as bh
    class _DB:
        def get_favorites(self, uid, limit=200):
            return []
    inst = _DB()
    db_mod = __import__('database', fromlist=['db'])
    monkeypatch.setattr(db_mod, 'db', inst, raising=True)
    monkeypatch.setattr(bh, 'db', inst, raising=True)
    return bh.AdvancedBotHandlers(_App())

@pytest.fixture
def bot_nonempty(monkeypatch):
    import bot_handlers as bh
    class _DB:
        def get_favorites(self, uid, limit=200):
            return [
                {'file_name': 'a.py', 'programming_language': 'python'},
                {'file_name': 'b.js', 'programming_language': 'javascript'}
            ]
    inst = _DB()
    db_mod = __import__('database', fromlist=['db'])
    monkeypatch.setattr(db_mod, 'db', inst, raising=True)
    monkeypatch.setattr(bh, 'db', inst, raising=True)
    return bh.AdvancedBotHandlers(_App())
