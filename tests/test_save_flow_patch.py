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


# --- New tests to cover early normalization in save_flow ---

def _has_invisibles(s: str) -> bool:
    """Helper: detect zero-width and bidi marks in string."""
    invis = [
        "\u200b", "\u200c", "\u200d", "\u2060", "\ufeff",  # zero-width/BOM/WJ
        "\u200e", "\u200f",  # LRM/RLM
        "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",  # LRE/RLE/PDF/LRO/RLO
        "\u2066", "\u2067", "\u2068", "\u2069",  # LRI/RLI/FSI/PDI
    ]
    return any(c in s for c in invis)


def test_get_code_normalizes_zero_width():
    import asyncio
    from handlers.save_flow import get_code

    class _Msg:
        def __init__(self, text: str):
            self.text = text
            # שדה document נדרש בענף לוגיקה של long_collect_receive
            self.document = None

        async def reply_text(self, *args, **kwargs):
            pass

    class _Update:
        def __init__(self, text: str):
            self.message = _Msg(text)

    class _Ctx:
        def __init__(self):
            self.user_data = {}

    u = _Update("A\u200bB\u200fC\u200d")
    c = _Ctx()
    asyncio.run(get_code(u, c))
    cleaned = c.user_data.get('code_to_save', '')
    assert cleaned and not _has_invisibles(cleaned)


def test_long_collect_receive_normalizes_text():
    import asyncio
    from handlers.save_flow import long_collect_receive

    class _Msg:
        def __init__(self, text: str):
            self.text = text
            # נדרש עבור הענף הבודק קבצים ב-long_collect_receive
            self.document = None

        async def reply_text(self, *args, **kwargs):
            pass

    class _Update:
        def __init__(self, text: str):
            self.message = _Msg(text)
            self.effective_chat = types.SimpleNamespace(id=111)
            self.effective_user = types.SimpleNamespace(id=222)

    class _Job:
        pass

    class _JobQueue:
        def run_once(self, *args, **kwargs):
            return _Job()

    class _Ctx:
        def __init__(self):
            self.user_data = {}
            self.job_queue = _JobQueue()

    u = _Update("x\u200b y\u202e z\u2060")
    c = _Ctx()
    asyncio.run(long_collect_receive(u, c))
    parts = c.user_data.get('long_collect_parts') or []
    assert parts and all(not _has_invisibles(p) for p in parts)


def test_long_collect_done_normalizes_combined():
    import asyncio
    from handlers.save_flow import long_collect_done

    class _Msg:
        async def reply_text(self, *args, **kwargs):
            pass

    class _Update:
        def __init__(self):
            self.message = _Msg()

    class _Ctx:
        def __init__(self):
            self.user_data = {
                'long_collect_parts': [
                    "a\u200b\u200f\u200d",
                    "b\u202a\u202b\u202c\u202d\u202e",
                    "c\u2066\u2067\u2068\u2069\u2060",
                ]
            }

    u = _Update()
    c = _Ctx()
    asyncio.run(long_collect_done(u, c))
    combined = c.user_data.get('code_to_save', '')
    assert combined and not _has_invisibles(combined)


def test_save_file_final_normalizes_code_content(monkeypatch):
    # Stub telegram keyboard classes used in save_flow to keep test lightweight
    import handlers.save_flow as sf
    sf.InlineKeyboardButton = lambda *a, **k: ('btn', a, k)
    sf.InlineKeyboardMarkup = lambda rows: ('kb', rows)

    # Stub services.code_service.detect_language
    monkeypatch.setattr(sf.code_service, 'detect_language', lambda code, fn: 'python')

    # Provide a lightweight 'database' module with db & CodeSnippet capturing snippet
    db_mod = types.ModuleType('database')

    class _DB:
        def __init__(self):
            self.last_snip = None

        def save_code_snippet(self, snip):
            self.last_snip = snip
            return True

        def get_latest_version(self, user_id, filename):
            return {'_id': 'xyz'}

    class _CodeSnippet:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    db_mod.db = _DB()
    db_mod.CodeSnippet = _CodeSnippet
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
                'code_to_save': 'print(1)\u200b\u200f',
                'note_to_save': 'ok'
            }

    u = _Update()
    c = _Ctx()

    import asyncio
    asyncio.run(sf.save_file_final(u, c, filename='a.py', user_id=1))

    saved = db_mod.db.last_snip.kwargs['code']
    assert saved and not _has_invisibles(saved)
