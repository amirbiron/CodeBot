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

class _User: id = 99

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
            # generate many entries to approach Telegram message limit
            return [{
                'file_name': f'file_{i}.py', 'programming_language': 'python', 'tags': [], 'code': 'print(1)',
                'favorited_at': None
            } for i in range(120)]
    db_mod = __import__('database', fromlist=['db'])
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)
    utils = __import__('utils')
    monkeypatch.setattr(utils, 'get_language_emoji', lambda s: '🐍', raising=True)
    class TU:
        @staticmethod
        def format_relative_time(dt):
            return 'היום'
    monkeypatch.setattr(utils, 'TimeUtils', TU, raising=True)
    return bh.AdvancedBotHandlers(_App())

@pytest.mark.asyncio
async def test_favorites_command_handles_long_message(bot):
    # Build a long favorites message and ensure it doesn't raise
    upd = _Upd(); ctx = _Ctx()
    await bot.favorites_command(upd, ctx)
    # At least one message should be sent
    assert len(upd.message.sent) >= 1
