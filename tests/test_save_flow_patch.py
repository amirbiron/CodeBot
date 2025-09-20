import types
import sys


def test_schedule_long_collect_timeout_sets_id_and_replace_existing(monkeypatch):
    from handlers.save_flow import _schedule_long_collect_timeout

    class _Job:
        pass

    class _JobQueue:
        def __init__(self):
            self.captured = None

        def run_once(self, callback, when, data=None, name=None, job_kwargs=None):
            self.captured = {
                'callback': callback,
                'when': when,
                'data': data,
                'name': name,
                'job_kwargs': job_kwargs,
            }
            return _Job()

    class _Update:
        def __init__(self):
            self.effective_chat = types.SimpleNamespace(id=111)
            self.effective_user = types.SimpleNamespace(id=222)

    class _Ctx:
        def __init__(self):
            self.job_queue = _JobQueue()
            self.user_data = {}

    u = _Update()
    c = _Ctx()

    _schedule_long_collect_timeout(u, c)

    jid = 'long_collect_timeout:222'
    assert c.job_queue.captured is not None
    assert c.job_queue.captured['name'] == jid
    assert c.job_queue.captured['job_kwargs']['id'] == jid
    assert c.job_queue.captured['job_kwargs']['replace_existing'] is True
    assert isinstance(c.user_data.get('long_collect_job'), _Job)


def test_save_file_final_escapes_note_markdown(monkeypatch):
    # Stub telegram keyboard classes used in save_flow to keep test lightweight
    import handlers.save_flow as sf
    sf.InlineKeyboardButton = lambda *a, **k: ('btn', a, k)
    sf.InlineKeyboardMarkup = lambda rows: ('kb', rows)

    # Stub services.code_service.detect_language
    monkeypatch.setattr(sf.code_service, 'detect_language', lambda code, fn: 'python')

    # Provide a lightweight 'database' module with db & CodeSnippet
    db_mod = types.ModuleType('database')

    class _DB:
        def save_code_snippet(self, snip):
            return True

        def get_latest_version(self, user_id, filename):
            return {'_id': 'xyz'}

    class _CodeSnippet:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    db_mod.db = _DB()
    db_mod.CodeSnippet = _CodeSnippet
    # רשום את המודול הזמני רק לטווח הטסט
    monkeypatch.setitem(sys.modules, 'database', db_mod)

    # Build update/context stubs
    calls = {}

    class _Msg:
        async def reply_text(self, text, **kwargs):
            calls['text'] = text
            calls['kwargs'] = kwargs

    class _Update:
        def __init__(self):
            self.message = _Msg()

    class _Ctx:
        def __init__(self):
            self.user_data = {
                'code_to_save': 'print(1)',
                'note_to_save': 'note_with_[special]_(chars)'
            }

    u = _Update()
    c = _Ctx()

    from utils import TextUtils
    import asyncio
    asyncio.run(sf.save_file_final(u, c, filename='a.py', user_id=1))

    # Ensure Markdown escape was applied inside the success message
    expected = TextUtils.escape_markdown('note_with_[special]_(chars)', version=1)
    assert expected in calls['text']
    assert calls['kwargs'].get('parse_mode') == 'Markdown'

