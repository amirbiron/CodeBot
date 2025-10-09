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

class _User: id = 654

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
        def get_favorites(self, uid, limit=50):
            return [
                {'file_name': 'a.py', 'programming_language': 'python', 'tags': ['x', 'common']},
                {'file_name': 'b.js', 'programming_language': 'javascript', 'tags': ['y', 'common']},
                {'file_name': 'c.py', 'programming_language': 'python', 'tags': ['common']},
            ]
    db_mod = __import__('database', fromlist=['db'])
    inst = _DB()
    monkeypatch.setattr(db_mod, 'db', inst, raising=True)
    monkeypatch.setattr(bh, 'db', inst, raising=True)
    return bh.AdvancedBotHandlers(_App())

@pytest.mark.asyncio
async def test_favorites_stats_content(bot):
    q = _Query(); q.data = "favorites_stats"
    ctx = _Ctx()
    await bot.handle_callback_query(types.SimpleNamespace(callback_query=q, effective_user=_User()), ctx)
    # One edited message should be present
    assert q.message.sent
    text = q.message.sent[0][0][0] if q.message.sent and q.message.sent[0][0] else ""
    assert "סטטיסטיקות" in text and "⭐" in text
