import types
import pytest


@pytest.mark.asyncio
async def test_view_direct_favorites_button_appears_even_with_long_id(monkeypatch):
    # Ensure very long ObjectId-like string does not break fav button callback
    from handlers import file_view as fv

    class _Btn:
        def __init__(self, text, callback_data=None):
            self.text = text
            self.callback_data = callback_data
    class _Markup:
        def __init__(self, keyboard):
            self.keyboard = keyboard
    class _Q:
        def __init__(self, data):
            self.data = data
            self.edits = []
            self.message = types.SimpleNamespace(reply_document=lambda **k: None)
        async def answer(self):
            return None
        async def edit_message_text(self, text, reply_markup=None, **kwargs):
            self.edits.append({"text": text, "reply_markup": reply_markup})
    class _U:
        def __init__(self, data):
            self.callback_query = _Q(data)
            self.effective_user = types.SimpleNamespace(id=1)
    class _Ctx:
        def __init__(self):
            self.user_data = {}

    # Stub DB
    class _DB:
        def get_latest_version(self, uid, name):
            return {
                "_id": "X" * 120,  # overly long id
                "file_name": name,
                "code": "print(1)",
                "programming_language": "python",
                "version": 1,
            }
        def is_favorite(self, uid, name):
            return False
    monkeypatch.setitem(__import__('sys').modules, 'database', types.SimpleNamespace(db=_DB()))

    monkeypatch.setattr(fv, 'InlineKeyboardButton', _Btn, raising=True)
    monkeypatch.setattr(fv, 'InlineKeyboardMarkup', _Markup, raising=True)

    upd = _U('view_direct_a.py')
    ctx = _Ctx()

    await fv.handle_view_direct_file(upd, ctx)

    # Extract callbacks
    rm = upd.callback_query.edits[-1]["reply_markup"]
    callbacks = [btn.callback_data for row in rm.keyboard for btn in row]
    assert any(cb and str(cb).startswith("fav_toggle_") for cb in callbacks)
