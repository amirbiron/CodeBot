import types
import sys
import pytest


@pytest.mark.asyncio
async def test_conv_receive_new_code_uses_preserve(monkeypatch):
    import conversation_handlers as ch

    called = {}

    def fake_extract(msg, reconstruct_from_entities=True):
        called['ok'] = True
        return "print('__main__')\n"

    # Patch the TelegramUtils method inside conversation_handlers
    monkeypatch.setattr(ch.TelegramUtils, 'extract_message_text_preserve_markdown', fake_extract)

    # Stub code_processor used by conversation_handlers
    class _CP:
        @staticmethod
        def validate_code_input(code, file_name=None, user_id=None):
            return True, code, ""
        @staticmethod
        def detect_language(code, file_name=None):
            return 'python'

    monkeypatch.setattr(ch, 'code_processor', _CP())

    # Stub database module
    class _DB:
        @staticmethod
        def save_file(user_id, file_name, content, detected_language):
            return True
        @staticmethod
        def get_latest_version(user_id, file_name):
            return {'version': 1}

    db_mod = types.ModuleType('database')
    db_mod.db = _DB()
    monkeypatch.setitem(sys.modules, 'database', db_mod)

    # prepare context and update
    ctx = types.SimpleNamespace(user_data={
        'editing_file_data': {'file_name': 't.py', 'code': '', 'programming_language': 'python'},
        'editing_file_index': '1',
    })

    class Msg:
        def __init__(self):
            self.text = 'main'
        async def reply_text(self, *a, **k):
            return None

    upd = types.SimpleNamespace(message=Msg(), effective_user=types.SimpleNamespace(id=1))

    await ch.receive_new_code(upd, ctx)

    assert called.get('ok') is True

