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

    monkeypatch.setattr(ch.code_service, 'validate_code_input', lambda code, file_name, user_id: (True, code, ""))
    monkeypatch.setattr(ch.code_service, 'detect_language', lambda code, file_name: 'python')

    # Stub code_processor module so `from code_processor import code_processor` works
    class _CP:
        @staticmethod
        def validate_code_input(code, file_name=None, user_id=None):
            return True, code, ""
        @staticmethod
        def detect_language(code, file_name=None):
            return 'python'

    cp_mod = types.ModuleType('code_processor')
    cp_mod.code_processor = _CP()
    monkeypatch.setitem(sys.modules, 'code_processor', cp_mod)

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


@pytest.mark.asyncio
async def test_conv_receive_new_code_fallback_on_extract_failure(monkeypatch):
    import conversation_handlers as ch

    def boom(msg, reconstruct_from_entities=True):
        raise RuntimeError('boom')

    monkeypatch.setattr(ch.TelegramUtils, 'extract_message_text_preserve_markdown', boom)

    monkeypatch.setattr(ch.code_service, 'validate_code_input', lambda code, file_name, user_id: (True, code, ""))
    monkeypatch.setattr(ch.code_service, 'detect_language', lambda code, file_name: 'python')

    # Stub database to assert fallback raw content is used
    class _DB:
        @staticmethod
        def save_file(user_id, file_name, content, detected_language):
            assert content == 'raw'
            return True
        @staticmethod
        def get_latest_version(user_id, file_name):
            return {'version': 1}

    db_mod = types.ModuleType('database')
    db_mod.db = _DB()
    monkeypatch.setitem(sys.modules, 'database', db_mod)

    ctx = types.SimpleNamespace(user_data={
        'editing_file_data': {'file_name': 't.py', 'code': '', 'programming_language': 'python'},
        'editing_file_index': '1',
    })

    class Msg:
        def __init__(self):
            self.text = 'raw'
        async def reply_text(self, *a, **k):
            return None

    upd = types.SimpleNamespace(message=Msg(), effective_user=types.SimpleNamespace(id=1))

    await ch.receive_new_code(upd, ctx)


@pytest.mark.asyncio
async def test_conv_receive_new_code_md_uses_domain_detector(monkeypatch):
    import conversation_handlers as ch

    captured = {}

    md_code = "import os, asyncio\n\n\ndef main():\n    print('hi')\n"

    monkeypatch.setattr(ch.TelegramUtils, 'extract_message_text_preserve_markdown', lambda msg, reconstruct_from_entities=True: md_code)

    def fake_validate(code, file_name, user_id):
        assert file_name == 'block.md'
        return True, code, ""

    def fake_detect(code, file_name):
        captured['detected_for'] = file_name
        captured['code'] = code
        return 'python'

    monkeypatch.setattr(ch.code_service, 'validate_code_input', fake_validate)
    monkeypatch.setattr(ch.code_service, 'detect_language', fake_detect)

    class _DB:
        @staticmethod
        def save_file(user_id, file_name, content, detected_language):
            captured['saved_lang'] = detected_language
            captured['saved_name'] = file_name
            captured['saved_code'] = content
            return True

        @staticmethod
        def get_latest_version(user_id, file_name):
            return {'version': 2}

    db_mod = types.ModuleType('database')
    db_mod.db = _DB()
    monkeypatch.setitem(sys.modules, 'database', db_mod)

    ctx = types.SimpleNamespace(user_data={
        'editing_file_data': {'file_name': 'block.md', 'code': '', 'programming_language': 'markdown'},
        'editing_file_index': '5',
    })

    class Msg:
        text = md_code

        async def reply_text(self, *a, **k):
            return None

    upd = types.SimpleNamespace(message=Msg(), effective_user=types.SimpleNamespace(id=42))

    await ch.receive_new_code(upd, ctx)

    assert captured['detected_for'] == 'block.md'
    assert captured['saved_lang'] == 'python'
