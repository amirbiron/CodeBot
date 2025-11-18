import types
import asyncio


async def _run(coro):
    return await coro


def test_save_file_final_skips_empty_duplicate_after_recent_success(monkeypatch):
    import time
    from handlers import save_flow as sf

    # Stub database to ensure it is NOT called
    db_mod = types.ModuleType('database')

    class _DB:
        def save_code_snippet(self, *args, **kwargs):  # pragma: no cover - should not be called
            raise AssertionError("save_code_snippet must not be called on empty duplicate")

    db_mod.db = _DB()
    monkeypatch.setitem(__import__('sys').modules, 'database', db_mod)

    # Prepare update/context
    class _Update:
        # Not used on early-guard path
        message = None

    class _Ctx:
        def __init__(self):
            self.user_data = {
                'code_to_save': '   ',  # empty after strip
                'last_save_success': {
                    'file_name': 'a.py',
                    'saved_at_epoch': int(time.time()),
                },
                'last_save_success_ts': int(time.time()),
            }

    u = _Update()
    c = _Ctx()

    result = asyncio.run(_run(sf.save_file_final(u, c, filename='a.py', user_id=1)))

    assert result == sf.ConversationHandler.END
    # State keys of the save-flow should be cleaned
    assert 'code_to_save' not in c.user_data


def test_send_save_success_sets_timestamp(monkeypatch):
    # Avoid depending on telegram classes
    import handlers.save_flow as sf

    sf.InlineKeyboardButton = lambda *a, **k: ('btn', a, k)
    sf.InlineKeyboardMarkup = lambda rows: ('kb', rows)

    calls = {}

    class _Msg:
        async def reply_text(self, text, **kwargs):  # pragma: no cover (I/O)
            calls['text'] = text
            calls['kwargs'] = kwargs

    class _Update:
        def __init__(self):
            self.message = _Msg()

    class _Ctx:
        def __init__(self):
            self.user_data = {}

    u = _Update()
    c = _Ctx()

    asyncio.run(sf._send_save_success(u, c, filename='doc.md', detected_language='markdown', note='', fid='id1'))

    assert 'last_save_success' in c.user_data
    assert 'last_save_success_ts' in c.user_data
    meta = c.user_data['last_save_success']
    assert meta.get('file_name') == 'doc.md'
    assert isinstance(meta.get('saved_at_epoch'), int)
