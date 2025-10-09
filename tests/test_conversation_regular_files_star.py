import sys
import types
import pytest

class _Btn:
    def __init__(self, text, callback_data=None):
        self.text = text
        self.callback_data = callback_data

class _Markup:
    def __init__(self, keyboard):
        self.keyboard = keyboard

class _Msg:
    def __init__(self):
        self.edits = []
        self.replies = []
    async def reply_text(self, text, reply_markup=None, **kwargs):
        self.replies.append({"text": text, "reply_markup": reply_markup, **kwargs})

class _User:
    def __init__(self, uid=77):
        self.id = uid
        self.username = "u"

class _Query:
    def __init__(self, data):
        self.data = data
        self.message = _Msg()
        self._answered = False
        self.edits = []
    async def answer(self):
        self._answered = True
    async def edit_message_text(self, text, reply_markup=None, **kwargs):
        self.edits.append({"text": text, "reply_markup": reply_markup, **kwargs})

class _Update:
    def __init__(self, data):
        self.callback_query = _Query(data)
        self.effective_user = _User()

class _Ctx:
    def __init__(self):
        self.user_data = {}

class _DB:
    def __init__(self):
        self.calls = []
    def get_regular_files_paginated(self, user_id, page=1, per_page=10):
        # one short file name to trigger star visibility rule (<=35 chars)
        files = [{"_id": "1", "file_name": "short.py", "programming_language": "python", "is_active": True}]
        return files, len(files)
    def is_favorite(self, user_id, file_name):
        return file_name == "short.py"

@pytest.mark.asyncio
async def test_regular_files_page_shows_star_for_favorites(monkeypatch):
    fake_db_mod = types.SimpleNamespace(db=_DB())
    monkeypatch.setitem(sys.modules, 'database', fake_db_mod)

    import conversation_handlers as ch
    # stub UI helpers
    monkeypatch.setattr(ch, 'InlineKeyboardButton', _Btn, raising=True)
    monkeypatch.setattr(ch, 'InlineKeyboardMarkup', _Markup, raising=True)
    # ensure emoji function exists and returns deterministic symbol
    monkeypatch.setattr(ch, 'get_file_emoji', lambda lang: "🐍", raising=True)

    upd = _Update("files_page_1")
    ctx = _Ctx()

    res = await ch.show_regular_files_page_callback(upd, ctx)
    assert res is ch.ConversationHandler.END

    # validate star indicator
    edit = upd.callback_query.edits[-1]
    texts = [btn.text for row in edit["reply_markup"].keyboard for btn in row]
    assert any(t.startswith("⭐ ") for t in texts), f"expected star in buttons, got: {texts}"
