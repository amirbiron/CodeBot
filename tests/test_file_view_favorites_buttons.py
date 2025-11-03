import sys
import types
import pytest


class _Btn:
    def __init__(self, text, callback_data=None, url=None, **_):
        self.text = text
        self.callback_data = callback_data
        self.url = url


class _Markup:
    def __init__(self, keyboard):
        self.keyboard = keyboard


class _Query:
    def __init__(self, data):
        self.data = data
        self.edits = []
        self._answered = False
    async def answer(self):
        self._answered = True


class _Update:
    def __init__(self, data, uid=111):
        self.callback_query = _Query(data)
        self._user = types.SimpleNamespace(id=uid)
    @property
    def effective_user(self):
        return self._user


class _Ctx:
    def __init__(self):
        self.user_data = {}


@pytest.mark.asyncio
async def test_view_file_includes_favorites_button_with_id(monkeypatch):
    # Stub DB with is_favorite=False
    fake_db_mod = types.SimpleNamespace(db=types.SimpleNamespace(is_favorite=lambda uid, name: False))
    monkeypatch.setitem(sys.modules, 'database', fake_db_mod)

    import handlers.file_view as fv
    # Stub UI and Telegram utils
    monkeypatch.setattr(fv, 'InlineKeyboardButton', _Btn, raising=True)
    monkeypatch.setattr(fv, 'InlineKeyboardMarkup', _Markup, raising=True)

    captured = {}
    async def _safe_edit(query, text, reply_markup=None, parse_mode=None):
        captured['reply_markup'] = reply_markup
    monkeypatch.setattr(fv.TelegramUtils, 'safe_edit_message_text', _safe_edit, raising=True)

    # Context with a file cached (contains an _id so we expect fav_toggle_id)
    ctx = _Ctx()
    ctx.user_data['files_cache'] = {
        '0': {
            '_id': 'OID1',
            'file_name': 'short.py',
            'programming_language': 'python',
            'code': 'print(1)',
            'version': 1,
        }
    }
    upd = _Update('view_0')

    await fv.handle_view_file(upd, ctx)

    rm = captured.get('reply_markup')
    assert isinstance(rm, _Markup)
    web_btn = rm.keyboard[0][0]
    assert web_btn.text == "🌐 צפייה בWebApp"
    assert web_btn.url == "https://code-keeper-webapp.onrender.com/file/OID1"
    # Favorites row is inserted before the last back row
    flat = [(btn.text, btn.callback_data) for row in rm.keyboard for btn in row]
    assert any(text.startswith('⭐') or text.startswith('💔') for text, _ in flat)
    assert any(cb and cb.startswith('fav_toggle_id:OID1') for _, cb in flat)


@pytest.mark.asyncio
async def test_view_file_uses_token_when_no_id_and_maps_token(monkeypatch):
    # DB: mark as not favorite to show add-to-favorites label
    fake_db_mod = types.SimpleNamespace(db=types.SimpleNamespace(is_favorite=lambda uid, name: False))
    monkeypatch.setitem(sys.modules, 'database', fake_db_mod)

    import handlers.file_view as fv
    # Stub UI
    monkeypatch.setattr(fv, 'InlineKeyboardButton', _Btn, raising=True)
    monkeypatch.setattr(fv, 'InlineKeyboardMarkup', _Markup, raising=True)
    # Deterministic token
    monkeypatch.setattr(fv.secrets, 'token_urlsafe', lambda n=6: 'tokXYZ', raising=True)

    captured = {}
    async def _safe_edit(query, text, reply_markup=None, parse_mode=None):
        captured['reply_markup'] = reply_markup
    monkeypatch.setattr(fv.TelegramUtils, 'safe_edit_message_text', _safe_edit, raising=True)

    ctx = _Ctx()
    ctx.user_data['files_cache'] = {
        '0': {
            # no _id triggers token path
            'file_name': 't.py',
            'programming_language': 'python',
            'code': 'x',
            'version': 1,
        }
    }
    upd = _Update('view_0')

    await fv.handle_view_file(upd, ctx)

    rm = captured.get('reply_markup')
    web_btn = rm.keyboard[0][0]
    assert web_btn.text == "🌐 צפייה בWebApp"
    assert web_btn.url == "https://code-keeper-webapp.onrender.com/files?q=t.py#results"
    flat = [(btn.text, btn.callback_data) for row in rm.keyboard for btn in row]
    # Expect token-based callback and mapping saved
    assert any(cb and cb.startswith('fav_toggle_tok:tokXYZ') for _, cb in flat)
    tok = 'tokXYZ'
    assert ctx.user_data.get('fav_tokens', {}).get(tok) == 't.py'


@pytest.mark.asyncio
async def test_view_direct_file_includes_favorites_button_with_id(monkeypatch):
    # Fake DB: get_latest_version returns file with _id
    class _DB:
        def get_latest_version(self, uid, name):
            return {
                '_id': 'ID789',
                'file_name': name,
                'code': 'print(1)',
                'programming_language': 'python',
                'version': 1,
            }
        def is_favorite(self, uid, name):
            return True

    fake_db_mod = types.SimpleNamespace(db=_DB())
    monkeypatch.setitem(sys.modules, 'database', fake_db_mod)

    import handlers.file_view as fv
    monkeypatch.setattr(fv, 'InlineKeyboardButton', _Btn, raising=True)
    monkeypatch.setattr(fv, 'InlineKeyboardMarkup', _Markup, raising=True)

    captured = {}
    async def _safe_edit(query, text, reply_markup=None, parse_mode=None):
        captured['reply_markup'] = reply_markup
    monkeypatch.setattr(fv.TelegramUtils, 'safe_edit_message_text', _safe_edit, raising=True)

    ctx = _Ctx()
    upd = _Update('view_direct_a.py')

    await fv.handle_view_direct_file(upd, ctx)

    rm = captured.get('reply_markup')
    assert isinstance(rm, _Markup)
    web_btn = rm.keyboard[0][0]
    assert web_btn.text == "🌐 צפייה בWebApp"
    assert web_btn.url == "https://code-keeper-webapp.onrender.com/file/ID789"
    flat = [(btn.text, btn.callback_data) for row in rm.keyboard for btn in row]
    # Should include remove-from-favorites label and id-based callback
    assert any(text.startswith('💔') for text, _ in flat)
    assert any(cb and cb.startswith('fav_toggle_id:ID789') for _, cb in flat)


@pytest.mark.asyncio
async def test_view_direct_large_file_uses_search_fallback(monkeypatch):
    class _DB:
        def get_file_by_id(self, file_id):
            return None
        def get_large_file_by_id(self, file_id):
            return {
                '_id': 'LF999',
                'file_name': 'big data.csv',
                'content': 'col1,col2',
                'programming_language': 'csv',
                'description': '',
            }
        def get_large_file(self, uid, name):
            return None
        def is_favorite(self, uid, name):
            return False

    fake_db_mod = types.SimpleNamespace(db=_DB())
    monkeypatch.setitem(sys.modules, 'database', fake_db_mod)

    import handlers.file_view as fv
    monkeypatch.setattr(fv, 'InlineKeyboardButton', _Btn, raising=True)
    monkeypatch.setattr(fv, 'InlineKeyboardMarkup', _Markup, raising=True)

    captured = {}
    async def _safe_edit(query, text, reply_markup=None, parse_mode=None):
        captured['reply_markup'] = reply_markup
    monkeypatch.setattr(fv.TelegramUtils, 'safe_edit_message_text', _safe_edit, raising=True)

    ctx = _Ctx()
    upd = _Update('view_direct_id:LF999')

    await fv.handle_view_direct_file(upd, ctx)

    rm = captured.get('reply_markup')
    assert isinstance(rm, _Markup)
    web_btn = rm.keyboard[0][0]
    assert web_btn.text == "🌐 צפייה בWebApp"
    assert web_btn.url == "https://code-keeper-webapp.onrender.com/files?q=big+data.csv#results"


@pytest.mark.asyncio
async def test_file_menu_includes_favorites_button(monkeypatch):
    # DB: set is_favorite False to display add-to-favorites
    fake_db_mod = types.SimpleNamespace(db=types.SimpleNamespace(is_favorite=lambda uid, name: False))
    monkeypatch.setitem(sys.modules, 'database', fake_db_mod)

    import handlers.file_view as fv
    monkeypatch.setattr(fv, 'InlineKeyboardButton', _Btn, raising=True)
    monkeypatch.setattr(fv, 'InlineKeyboardMarkup', _Markup, raising=True)

    captured = {}
    async def _safe_edit(query, text, reply_markup=None, parse_mode=None):
        captured['reply_markup'] = reply_markup
    monkeypatch.setattr(fv.TelegramUtils, 'safe_edit_message_text', _safe_edit, raising=True)

    # Prepare update/context for handle_file_menu
    class _Q(_Query):
        async def edit_message_text(self, text, reply_markup=None, **kwargs):
            captured['edit'] = {'text': text, 'reply_markup': reply_markup}

    class _U(_Update):
        def __init__(self, data, uid=111):
            super().__init__(data, uid)
            self.callback_query = _Q(data)

    ctx = _Ctx()
    ctx.user_data['files_cache'] = {
        '0': {
            '_id': 'XYZ',
            'file_name': 'm.py',
            'programming_language': 'python',
            'code': 'print(1)',
            'version': 1,
        }
    }
    upd = _U('file_0')

    await fv.handle_file_menu(upd, ctx)

    rm = captured.get('reply_markup') or captured.get('edit', {}).get('reply_markup')
    assert isinstance(rm, _Markup)
    flat = [(btn.text, btn.callback_data) for row in rm.keyboard for btn in row]
    assert any(text.startswith('⭐') for text, _ in flat)
    assert any(cb and cb.startswith('fav_toggle_id:XYZ') for _, cb in flat)
