import pytest


@pytest.mark.asyncio
async def test_show_command_long_code_html(monkeypatch):
    mod = __import__('bot_handlers')
    H = getattr(mod, 'AdvancedBotHandlers')

    # Stub DB to return long code (>500) to trigger HTML file branch
    class _DB:
        def get_latest_version(self, user_id, file_name):
            long = "print('x')\n" * 600
            return {"file_name": file_name, "code": long, "programming_language": "python", "updated_at": None}
    db_mod = __import__('database', fromlist=['db'])
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)

    # Stub code service to return highlighted code as-is
    svc = __import__('services.code_service', fromlist=['code_service'])
    monkeypatch.setattr(svc, 'highlight_code', lambda c, l: c, raising=True)

    # Stubs for telegram
    class _App:
        def add_handler(self, *a, **k):
            pass
    class _Msg:
        async def reply_text(self, *a, **k):
            return None
        async def reply_document(self, *a, **k):
            return None
    class _User: id = 1
    class _Upd:
        effective_user = _User()
        message = _Msg()
    class _Ctx:
        args = ["long.py"]

    h = H(_App())
    await h.show_command(_Upd(), _Ctx())

