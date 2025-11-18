import types
import asyncio


def test_layered_flow_fallback_detects_markdown_for_md(monkeypatch):
    # Enable layered flow
    monkeypatch.setenv('USE_NEW_SAVE_FLOW', '1')

    import handlers.save_flow as sf

    # Stub layered service: create_snippet returns object with language='text'
    class _Saved:
        language = 'text'

    class _DummyService:
        async def create_snippet(self, dto):
            return _Saved()

        async def get_snippet(self, user_id, filename):  # not used here
            return None

    monkeypatch.setattr(sf, '_build_layered_snippet_service', lambda: _DummyService())

    # Stub db and code_service fallback
    db_mod = types.ModuleType('database')

    class _DB:
        def get_latest_version(self, user_id, filename):
            return {'_id': 'abc'}

    db_mod.db = _DB()
    monkeypatch.setitem(__import__('sys').modules, 'database', db_mod)

    monkeypatch.setattr(sf.code_service, 'detect_language', lambda code, fn: 'markdown')

    # Capture _send_save_success inputs without touching telegram
    captured = {}
    sf.InlineKeyboardButton = lambda *a, **k: ('btn', a, k)
    sf.InlineKeyboardMarkup = lambda rows: ('kb', rows)

    async def _capture_send(update, context, filename, detected_language, note, fid):
        captured['filename'] = filename
        captured['language'] = detected_language
        captured['note'] = note
        captured['fid'] = fid

    monkeypatch.setattr(sf, '_send_save_success', _capture_send)

    class _Msg:
        async def reply_text(self, *a, **k):
            pass

    class _Update:
        def __init__(self):
            self.message = _Msg()

    class _Ctx:
        def __init__(self):
            self.user_data = {'code_to_save': '# כותרת\n\n- רשימה', 'note_to_save': ''}

    u = _Update()
    c = _Ctx()

    result = asyncio.run(sf.save_file_final(u, c, filename='doc.md', user_id=1))

    assert result == sf.ConversationHandler.END
    assert captured.get('filename') == 'doc.md'
    assert captured.get('language') == 'markdown'
