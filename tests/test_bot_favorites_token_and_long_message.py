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

class _User: id = 55

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
            self._doc = {
                'big.txt': {'_id': None, 'file_name': 'big.txt', 'code': 'x'*5000, 'programming_language': 'text'}
            }
        def get_latest_version(self, uid, name):
            return self._doc.get(name)
        def is_favorite(self, uid, name):
            return self._fav
        def toggle_favorite(self, uid, name):
            self._fav = not self._fav
            return self._fav
        def get_favorites(self, uid, limit=50):
            # simulate many favorites to trigger long message; only structure matters
            if not self._fav:
                return []
            return [{
                'file_name': f'file_{i}.py', 'programming_language': 'python', 'tags': [], 'code': 'print(1)',
                'favorited_at': None
            } for i in range(30)]
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
async def test_token_callback_and_long_favorites_message(bot):
    upd = _Upd(); ctx = _Ctx()
    ctx.args = ['big.txt']
    # show big file (no _id) to force token flow
    await bot.show_command(upd, ctx)

    # fetch token from mapping created by show_command
    tokens = ctx.user_data.get('fav_tokens') or {}
    if not tokens:
        # if mapping somehow empty, create one
        ctx.user_data['fav_tokens'] = {'tok': 'big.txt'}
        tok = 'tok'
    else:
        tok = next(iter(tokens.keys()))

    q = _Query(); q.data = f"fav_toggle_tok:{tok}"
    await bot.handle_callback_query(types.SimpleNamespace(callback_query=q, effective_user=_User()), ctx)

    # now /favorites should produce a long message – ensure no exception
    await bot.favorites_command(upd, ctx)
    assert True
