import types
import pytest


@pytest.mark.asyncio
async def test_show_favorites_uses_safe_reply_markup_on_not_modified(monkeypatch):
    # Arrange DB returning favorites
    fake_db = types.SimpleNamespace(get_favorites=lambda uid, limit=1000: [{"file_name": "a.py", "programming_language": "python"}])
    monkeypatch.setitem(__import__('sys').modules, 'database', types.SimpleNamespace(db=fake_db))

    import conversation_handlers as ch

    # Stub telegram.error.BadRequest and make edit_message_text raise it
    class FakeBadRequest(Exception):
        pass
    ch.telegram = types.SimpleNamespace(error=types.SimpleNamespace(BadRequest=FakeBadRequest))

    called = {"safe": False}
    from utils import TelegramUtils as TU
    async def _safe_edit_rm(query, reply_markup=None):
        called["safe"] = True
    monkeypatch.setattr(TU, 'safe_edit_message_reply_markup', _safe_edit_rm)

    class _Q:
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, *a, **k):
            raise FakeBadRequest("message is not modified")
    class _U:
        def __init__(self):
            self.callback_query = _Q()
            self.effective_user = types.SimpleNamespace(id=1)
    class _Ctx:
        def __init__(self):
            self.user_data = {}

    # Act
    await ch.show_favorites_callback(_U(), _Ctx())

    # Assert fallback used
    assert called["safe"] is True
