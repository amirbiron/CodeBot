import types
import pytest


@pytest.fixture(autouse=True)
def stub_services(monkeypatch):
    # stub db
    class _DB:
        def get_latest_version(self, user_id, file_name):
            return {"file_name": file_name, "code": "print('x')", "programming_language": "python"}
    db_mod = __import__('database', fromlist=['db'])
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)

    # stub code service
    svc = __import__('services.code_service', fromlist=['code_service'])
    def _hl(code, language):
        return code
    monkeypatch.setattr(svc, 'highlight_code', _hl, raising=True)
    return True


@pytest.mark.asyncio
async def test_show_command_happy():
    mod = __import__('bot_handlers')
    H = getattr(mod, 'AdvancedBotHandlers')

    class _App:
        def __init__(self):
            self.handlers = []
        def add_handler(self, *a, **k):
            self.handlers.append((a, k))

    bh = H(_App())

    class _Msg:
        async def reply_text(self, *a, **k):
            return None
    class _User: id = 1
    class _Upd:
        effective_user = _User()
        message = _Msg()
    class _Ctx:
        args = ["main.py"]

    await bh.show_command(_Upd(), _Ctx())

