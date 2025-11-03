import sys
import types
import pytest


@pytest.mark.asyncio
async def test_regular_files_toggle_multi_delete(monkeypatch):
    # DB stub returns a single page of items
    mod = types.ModuleType("database")
    class _CodeSnippet: pass
    class _LargeFile: pass
    class _DatabaseManager: pass
    mod.CodeSnippet = _CodeSnippet
    mod.LargeFile = _LargeFile
    mod.DatabaseManager = _DatabaseManager

    items = [{"_id": f"i{n}", "file_name": f"m{n}.py", "programming_language": "python"} for n in range(10)]
    mod.db = types.SimpleNamespace(get_regular_files_paginated=lambda uid, page, per_page: (items, len(items)))
    monkeypatch.setitem(__import__('sys').modules, "database", mod)

    from conversation_handlers import handle_callback_query

    class Q:
        def __init__(self, data):
            self.data = data
            self.captured = None
        async def answer(self):
            return None
        async def edit_message_text(self, *_a, **kw):
            self.captured = kw.get("reply_markup")
    class U:
        def __init__(self, data):
            self.callback_query = Q(data)
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=1)

    ctx = types.SimpleNamespace(user_data={})
    # open regular files
    await handle_callback_query(U("show_regular_files"), ctx)
    # enter multi-delete mode
    await handle_callback_query(U("rf_multi_start"), ctx)
    # toggle one id (simulate an id value)
    await handle_callback_query(U("rf_toggle:1:i5"), ctx)
    # cancel multi-delete
    await handle_callback_query(U("rf_multi_cancel"), ctx)
    assert 'rf_multi_delete' in ctx.user_data


@pytest.mark.asyncio
async def test_regular_files_multi_delete_complete_flow(monkeypatch):
    # cover double confirm -> delete path with empty selection guard and with selection
    mod = types.ModuleType("database")
    class _CodeSnippet: pass
    class _LargeFile: pass
    class _DatabaseManager: pass
    mod.CodeSnippet = _CodeSnippet
    mod.LargeFile = _LargeFile
    mod.DatabaseManager = _DatabaseManager
    # minimal stub functions used in the flow
    class Repo:
        def delete_file_by_id(self, fid):
            return True
    class DB:
        def __init__(self):
            self._repo = Repo()
        def _get_repo(self):
            return self._repo
        def get_regular_files_paginated(self, uid, page, per_page):
            return ([{"_id": "i1", "file_name": "a.py", "programming_language": "python"}], 1)
    mod.db = DB()
    monkeypatch.setitem(__import__('sys').modules, "database", mod)

    from conversation_handlers import handle_callback_query

    class Q:
        def __init__(self, data):
            self.data = data
            self.captured = None
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, *a, **kw):
            self.captured = kw
    class U:
        def __init__(self, data):
            self.callback_query = Q(data)
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=1)

    ctx = types.SimpleNamespace(user_data={"files_last_page": 1})
    # open regular files to init state
    await handle_callback_query(U("show_regular_files"), ctx)
    # try delete confirm with no selection -> alert path ends early
    await handle_callback_query(U("rf_delete_confirm"), ctx)
    # select and go through both confirms
    ctx.user_data["rf_selected_ids"] = ["i1"]
    await handle_callback_query(U("rf_delete_confirm"), ctx)
    await handle_callback_query(U("rf_delete_double_confirm"), ctx)
    assert isinstance(ctx.user_data.get('files_last_page'), int)


class _Btn:
    def __init__(self, text, callback_data=None, url=None, **_):
        self.text = text
        self.callback_data = callback_data
        self.url = url


class _Markup:
    def __init__(self, keyboard):
        self.keyboard = keyboard


@pytest.mark.asyncio
async def test_file_menu_includes_webapp_button(monkeypatch):
    fake_db_mod = types.SimpleNamespace(db=types.SimpleNamespace(is_favorite=lambda uid, name: False))
    monkeypatch.setitem(sys.modules, 'database', fake_db_mod)

    import conversation_handlers as ch
    monkeypatch.setattr(ch, 'InlineKeyboardButton', _Btn, raising=True)
    monkeypatch.setattr(ch, 'InlineKeyboardMarkup', _Markup, raising=True)

    captured = {}
    async def fake_safe_edit(query, text, reply_markup=None, parse_mode=None):
        captured['reply_markup'] = reply_markup
    monkeypatch.setattr(ch.TelegramUtils, 'safe_edit_message_text', fake_safe_edit, raising=True)

    class Q:
        data = 'file_0'
        async def answer(self):
            return None

    ctx = types.SimpleNamespace(user_data={'files_cache': {'0': {
        '_id': 'OID42',
        'file_name': 'demo.py',
        'programming_language': 'python',
        'description': '',
    }}})
    upd = types.SimpleNamespace(callback_query=Q(), effective_user=types.SimpleNamespace(id=1))

    await ch.handle_file_menu(upd, ctx)

    rm = captured.get('reply_markup')
    assert isinstance(rm, _Markup)
    web_btn = rm.keyboard[1][0]
    assert web_btn.text == "?? ????? ?WebApp"
    assert web_btn.url == "https://code-keeper-webapp.onrender.com/file/OID42"


@pytest.mark.asyncio
async def test_file_menu_webapp_button_search_fallback(monkeypatch):
    fake_db_mod = types.SimpleNamespace(db=types.SimpleNamespace(is_favorite=lambda uid, name: False))
    monkeypatch.setitem(sys.modules, 'database', fake_db_mod)

    import conversation_handlers as ch
    monkeypatch.setattr(ch, 'InlineKeyboardButton', _Btn, raising=True)
    monkeypatch.setattr(ch, 'InlineKeyboardMarkup', _Markup, raising=True)

    captured = {}
    async def fake_safe_edit(query, text, reply_markup=None, parse_mode=None):
        captured['reply_markup'] = reply_markup
    monkeypatch.setattr(ch.TelegramUtils, 'safe_edit_message_text', fake_safe_edit, raising=True)

    class Q:
        data = 'file_0'
        async def answer(self):
            return None

    ctx = types.SimpleNamespace(user_data={'files_cache': {'0': {
        'file_name': 'noid.txt',
        'programming_language': 'text',
        'description': '',
    }}})
    upd = types.SimpleNamespace(callback_query=Q(), effective_user=types.SimpleNamespace(id=1))

    await ch.handle_file_menu(upd, ctx)

    rm = captured.get('reply_markup')
    assert isinstance(rm, _Markup)
    web_btn = rm.keyboard[1][0]
    assert web_btn.text == "?? ????? ?WebApp"
    assert web_btn.url == "https://code-keeper-webapp.onrender.com/files?q=noid.txt#results"
