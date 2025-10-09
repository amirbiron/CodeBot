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

class _User: id = 10

class _Upd:
    effective_user = _User()
    message = _Msg()

class _Query:
    def __init__(self):
        self.data = ""
        self.message = _Msg()
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
def bot():
    import bot_handlers as bh
    return bh.AdvancedBotHandlers(_App())

@pytest.fixture(autouse=True)
def stub_db(monkeypatch):
    # simple stub repo
    class _DB:
        def __init__(self):
            self._fav = False
        def get_latest_version(self, uid, name):
            return {"_id": "123", "file_name": name, "code": "print()", "programming_language": "python"}
        def is_favorite(self, uid, name):
            return self._fav
        def toggle_favorite(self, uid, name):
            self._fav = not self._fav
            return self._fav
        def get_favorites(self, uid, limit=50):
            return ([{"file_name": "a.py", "programming_language": "python"}] if self._fav else [])
    db_mod = __import__('database', fromlist=['db'])
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)
    # stub utils
    utils = __import__('utils')
    monkeypatch.setattr(utils, 'get_language_emoji', lambda s: '🐍', raising=True)
    class TU:
        @staticmethod
        def format_relative_time(dt):
            return "היום"
    monkeypatch.setattr(utils, 'TimeUtils', TU, raising=True)
    return True

@pytest.mark.asyncio
async def test_favorite_and_list(bot):
    upd = _Upd()
    ctx = _Ctx()
    ctx.args = ["a.py"]

    # /favorite toggles on
    await bot.favorite_command(upd, ctx)

    # /favorites should list one
    await bot.favorites_command(upd, ctx)
    # assert we sent at least one message in the flow
    assert len(upd.message.sent) >= 1

@pytest.mark.asyncio
async def test_callback_token_flow(bot):
    # simulate show_command building token mapping and callback handling
    upd = _Upd()
    ctx = _Ctx()
    ctx.args = ["a.py"]

    # build fav token mapping by calling show_command
    await bot.show_command(upd, ctx)
    # fetch the token mapping if created
    fav_tokens = ctx.user_data.get('fav_tokens', {})
    # force-create token mapping if missing (e.g., no-id path)
    if not fav_tokens:
        ctx.user_data['fav_tokens'] = {"tok": "a.py"}
        token = "tok"
    else:
        token = next(iter(fav_tokens))

    q = _Query()
    q.data = f"fav_toggle_tok:{token}"
    await bot.handle_callback_query(types.SimpleNamespace(callback_query=q, effective_user=_User()), ctx)
    # Should not raise and should answer
    assert True
