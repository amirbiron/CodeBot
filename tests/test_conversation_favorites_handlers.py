import sys
import types
import pytest

# Stubs for telegram inline keyboard items
class _Btn:
    def __init__(self, text, callback_data=None):
        self.text = text
        self.callback_data = callback_data

class _Markup:
    def __init__(self, keyboard):
        self.keyboard = keyboard

class _User:
    def __init__(self, user_id=123):
        self.id = user_id
        self.username = "tester"

class _Msg:
    def __init__(self):
        self.edits = []
        self.replies = []
    async def reply_text(self, text, reply_markup=None, **kwargs):
        self.replies.append({"text": text, "reply_markup": reply_markup, **kwargs})

class _Query:
    def __init__(self, data=""):
        self._answered = False
        self.edits = []
        self.message = _Msg()
        self.data = data
    async def answer(self):
        self._answered = True
    async def edit_message_text(self, text, reply_markup=None, **kwargs):
        self.edits.append({"text": text, "reply_markup": reply_markup, **kwargs})

class _Update:
    def __init__(self, data=""):
        self.callback_query = _Query(data=data)
        self.effective_user = _User()

class _Ctx:
    def __init__(self):
        self.user_data = {}

class _DBEmpty:
    def get_favorites(self, user_id, limit=1000, **kwargs):
        return []

class _DBWithItems:
    def __init__(self, n=12):
        self.n = n
    def get_favorites(self, user_id, limit=1000, **kwargs):
        items = []
        for i in range(self.n):
            items.append({"file_name": f"f{i}.py", "programming_language": "python", "_id": f"id-{i}"})
        return items

@pytest.mark.asyncio
async def test_show_favorites_callback_empty_list(monkeypatch):
    # Provide fake database module so `from database import db` works at call time
    fake_db_mod = types.SimpleNamespace(db=_DBEmpty())
    monkeypatch.setitem(sys.modules, 'database', fake_db_mod)
    
    import conversation_handlers as ch
    # Stub keyboard classes
    monkeypatch.setattr(ch, 'InlineKeyboardButton', _Btn, raising=True)
    monkeypatch.setattr(ch, 'InlineKeyboardMarkup', _Markup, raising=True)

    upd = _Update()
    ctx = _Ctx()

    res = await ch.show_favorites_callback(upd, ctx)
    assert res is ch.ConversationHandler.END

    # It should show the empty favorites message and then a back menu
    assert upd.callback_query.edits, "expected an edit_message_text call"
    assert "אין לך מועדפים" in upd.callback_query.edits[0]["text"]
    assert upd.callback_query.message.replies, "expected a reply_text call for back menu"

@pytest.mark.asyncio
async def test_show_favorites_callback_with_items_and_pagination(monkeypatch):
    # Fake database returns multiple items
    fake_db_mod = types.SimpleNamespace(db=_DBWithItems(n=12))
    monkeypatch.setitem(sys.modules, 'database', fake_db_mod)

    # Fake handlers.pagination.build_pagination_row
    handlers_mod = types.ModuleType('handlers')
    pagination_mod = types.ModuleType('handlers.pagination')
    def build_pagination_row(page, total, per_page, prefix):
        return [_Btn(f"page {page}", callback_data=f"{prefix}{page}")]
    pagination_mod.build_pagination_row = build_pagination_row
    monkeypatch.setitem(sys.modules, 'handlers', handlers_mod)
    monkeypatch.setitem(sys.modules, 'handlers.pagination', pagination_mod)

    import conversation_handlers as ch
    monkeypatch.setattr(ch, 'InlineKeyboardButton', _Btn, raising=True)
    monkeypatch.setattr(ch, 'InlineKeyboardMarkup', _Markup, raising=True)

    upd = _Update()
    ctx = _Ctx()

    res = await ch.show_favorites_callback(upd, ctx)
    assert res is ch.ConversationHandler.END

    # Verify header edit happened and keyboard contains pagination row and back row
    assert upd.callback_query.edits, "expected edit_message_text to be called"
    last_edit = upd.callback_query.edits[-1]
    markup = last_edit["reply_markup"]
    assert isinstance(markup, _Markup)
    flat_texts = [btn.text for row in markup.keyboard for btn in row]
    assert any(t.startswith("page 1") for t in flat_texts)
    assert any("חזור" in t for t in flat_texts)

    # Context should note favorites origin and first page
    assert ctx.user_data.get('files_origin', {}).get('type') == 'favorites'
    assert ctx.user_data.get('files_last_page') == 1
    assert ctx.user_data.get('files_cache'), "files_cache should be populated"

@pytest.mark.asyncio
async def test_show_favorites_page_callback_next_page(monkeypatch):
    fake_db_mod = types.SimpleNamespace(db=_DBWithItems(n=12))
    monkeypatch.setitem(sys.modules, 'database', fake_db_mod)

    handlers_mod = types.ModuleType('handlers')
    pagination_mod = types.ModuleType('handlers.pagination')
    def build_pagination_row(page, total, per_page, prefix):
        return [_Btn(f"page {page}", callback_data=f"{prefix}{page}")]
    pagination_mod.build_pagination_row = build_pagination_row
    monkeypatch.setitem(sys.modules, 'handlers', handlers_mod)
    monkeypatch.setitem(sys.modules, 'handlers.pagination', pagination_mod)

    import conversation_handlers as ch
    monkeypatch.setattr(ch, 'InlineKeyboardButton', _Btn, raising=True)
    monkeypatch.setattr(ch, 'InlineKeyboardMarkup', _Markup, raising=True)

    upd = _Update(data="favorites_page_2")
    ctx = _Ctx()

    res = await ch.show_favorites_page_callback(upd, ctx)
    assert res is ch.ConversationHandler.END
    assert ctx.user_data.get('files_last_page') == 2
    assert ctx.user_data.get('files_origin', {}).get('type') == 'favorites'
    assert upd.callback_query.edits, "expected an edit for page 2"
    last_edit = upd.callback_query.edits[-1]
    markup = last_edit["reply_markup"]
    flat_texts = [btn.text for row in markup.keyboard for btn in row]
    assert any(t.startswith("page 2") for t in flat_texts)
