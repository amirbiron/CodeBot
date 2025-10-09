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

class _User: id = 888

class _Upd:
    effective_user = _User()
    message = _Msg()

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
            return [{
                'file_name': f'file_{i}.py', 'programming_language': 'python', 'tags': [], 'code': 'print(1)'
            } for i in range(200)]
    db_mod = __import__('database', fromlist=['db'])
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)
    return bh.AdvancedBotHandlers(_App())

@pytest.mark.asyncio
async def test_favorites_command_sends_message(bot):
    upd = _Upd(); ctx = _Ctx()
    await bot.favorites_command(upd, ctx)
    # לפחות הודעה אחת נשלחה — לא בודקים פיצול בפועל, רק יציבות
    assert len(upd.message.sent) >= 1
