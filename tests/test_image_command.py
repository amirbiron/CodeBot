import pytest
from types import SimpleNamespace


@pytest.mark.asyncio
async def test_image_command_no_args(monkeypatch):
    mod = __import__('bot_handlers')
    H = getattr(mod, 'AdvancedBotHandlers')

    class _App:
        def add_handler(self, *a, **k):
            pass

    # Stub facade
    class _Facade:
        def get_latest_version(self, uid, fn):
            return None
    monkeypatch.setattr(mod, "_get_files_facade_or_none", lambda: _Facade())

    sent = {}
    class _Msg:
        async def reply_text(self, *a, **k):
            sent['reply_text'] = (a, k)
        async def reply_photo(self, *a, **k):
            sent['reply_photo'] = (a, k)
    class _User: id = 1
    class _Upd:
        effective_user = _User()
        message = _Msg()
    class _Ctx:
        args = []

    h = H(_App())
    await h.image_command(_Upd(), _Ctx())
    assert 'reply_text' in sent


@pytest.mark.asyncio
async def test_image_command_file_not_found(monkeypatch):
    mod = __import__('bot_handlers')
    H = getattr(mod, 'AdvancedBotHandlers')

    class _App:
        def add_handler(self, *a, **k):
            pass

    # Facade returns None
    class _Facade:
        def get_latest_version(self, uid, fn):
            return None
    monkeypatch.setattr(mod, "_get_files_facade_or_none", lambda: _Facade())

    captured = {}
    class _Msg:
        async def reply_text(self, *a, **k):
            captured['text'] = (a, k)
        async def reply_photo(self, *a, **k):
            captured['photo'] = (a, k)
    class _User: id = 2
    class _Upd:
        effective_user = _User()
        message = _Msg()
    class _Ctx:
        args = ['missing.py']

    h = H(_App())
    await h.image_command(_Upd(), _Ctx())
    assert 'text' in captured


@pytest.mark.asyncio
async def test_image_command_success(monkeypatch):
    mod = __import__('bot_handlers')
    H = getattr(mod, 'AdvancedBotHandlers')

    class _App:
        def add_handler(self, *a, **k):
            pass

    # Facade returns code
    class _Facade:
        def get_latest_version(self, uid, fn):
            return {'file_name': fn, 'code': "print('x')", 'programming_language': 'python'}
    monkeypatch.setattr(mod, "_get_files_facade_or_none", lambda: _Facade())

    # Stub image generator to avoid heavy work
    class _FakeGen:
        def __init__(self, *a, **k):
            pass
        def generate_image(self, *a, **k):
            return b'fake_png_data'
    monkeypatch.setattr(mod, 'CodeImageGenerator', _FakeGen, raising=True)

    captured = {}
    class _Msg:
        async def reply_text(self, *a, **k):
            captured['text'] = (a, k)
        async def reply_photo(self, *a, **k):
            captured['photo'] = (a, k)
    class _User: id = 3
    class _Upd:
        effective_user = _User()
        message = _Msg()
    class _Ctx:
        args = ['test.py']

    h = H(_App())
    await h.image_command(_Upd(), _Ctx())
    assert 'photo' in captured


@pytest.mark.asyncio
async def test_image_command_with_note(monkeypatch):
    mod = __import__('bot_handlers')
    H = getattr(mod, 'AdvancedBotHandlers')

    class _App:
        def add_handler(self, *a, **k):
            pass

    def _get_latest_version(uid, fn):
        return {'file_name': fn, 'code': "print('x')", 'programming_language': 'python'}

    class _Facade:
        def get_latest_version(self, uid, fn):
            return {'file_name': fn, 'code': "print('x')", 'programming_language': 'python'}
    monkeypatch.setattr(mod, "_get_files_facade_or_none", lambda: _Facade())

    captured_note = {}

    class _FakeGen:
        def __init__(self, *a, **k):
            pass

        def generate_image(self, *a, **k):
            captured_note['note'] = k.get('note')
            return b'fake_png_data'

    monkeypatch.setattr(mod, 'CodeImageGenerator', _FakeGen, raising=True)

    class _Msg:
        async def reply_text(self, *a, **k):
            pass

        async def reply_photo(self, *a, **k):
            pass

    class _User:
        id = 4

    class _Upd:
        effective_user = _User()
        message = _Msg()

    class _Ctx:
        args = ['note.py', '--note', 'בדיקה', 'חשובה']
        user_data = {}

    h = H(_App())
    await h.image_command(_Upd(), _Ctx())
    assert captured_note['note'] == "בדיקה חשובה"
