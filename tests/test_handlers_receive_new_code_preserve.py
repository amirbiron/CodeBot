import types
import sys
import pytest


@pytest.mark.asyncio
async def test_receive_new_code_uses_preserve(monkeypatch):
    # Stub TelegramUtils.extract_message_text_preserve_markdown to observe usage
    import handlers.file_view as fv

    captured = {}

    def fake_extract(msg, reconstruct_from_entities=True):
        captured['called'] = True
        # חיקוי הודעת משתמש עם __main__
        return "print('__main__')\n"

    monkeypatch.setattr(fv.TelegramUtils, 'extract_message_text_preserve_markdown', fake_extract)

    # Stub database
    class _DB:
        @staticmethod
        def save_large_file(*a, **k):
            return False
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

    class Q:
        def __init__(self):
            self.captured = None
        async def reply_text(self, *a, **k):
            self.captured = a[0] if a else None

    upd = types.SimpleNamespace(message=types.SimpleNamespace(text="main", reply_text=Q().reply_text), effective_user=types.SimpleNamespace(id=1))

    await fv.receive_new_code(upd, ctx)

    assert captured.get('called') is True
