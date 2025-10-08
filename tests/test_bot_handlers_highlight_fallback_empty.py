import pytest


@pytest.mark.asyncio
async def test_show_command_highlight_empty_fallback(monkeypatch):
    mod = __import__('bot_handlers')
    H = getattr(mod, 'AdvancedBotHandlers')

    # DB: short code triggers inline message path
    class _DB:
        def get_latest_version(self, user_id, file_name):
            return {"file_name": file_name, "code": "print('x')", "programming_language": "python", "updated_at": None, "tags": []}
    db_mod = __import__('database', fromlist=['db'])
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)

    # Force highlight_code to return empty string to trigger fallback path
    svc = __import__('services.code_service', fromlist=['code_service'])
    monkeypatch.setattr(svc, 'highlight_code', lambda c, l: '', raising=True)

    class _App:
        def add_handler(self, *a, **k):
            pass
    class _Msg:
        async def reply_text(self, *a, **k):
            return None
    class _User: id = 1
    class _Upd:
        effective_user = _User()
        message = _Msg()
    class _Ctx:
        args = ["x.py"]

    h = H(_App())
    await h.show_command(_Upd(), _Ctx())

