import pytest
from types import SimpleNamespace


@pytest.mark.asyncio
async def test_image_command_calls_cleanup(monkeypatch):
    mod = __import__('bot_handlers')
    H = getattr(mod, 'AdvancedBotHandlers')

    class _App:
        def add_handler(self, *a, **k):
            pass

    # DB returns code
    def _get_latest_version(uid, fn):
        return {'file_name': fn, 'code': "print('x')", 'programming_language': 'python'}
    monkeypatch.setattr(mod, 'db', SimpleNamespace(get_latest_version=_get_latest_version), raising=True)

    captured = {}

    class _FakeGen:
        def __init__(self, *a, **k):
            captured['inst'] = self
            self._cleanup_called = False
        def generate_image(self, *a, **k):
            return b'fake_png_data'
        def cleanup(self):
            self._cleanup_called = True
            captured['cleanup'] = True

    monkeypatch.setattr(mod, 'CodeImageGenerator', _FakeGen, raising=True)

    class _Msg:
        async def reply_text(self, *a, **k):
            captured['reply_text'] = True
        async def reply_photo(self, *a, **k):
            captured['reply_photo'] = True
    class _Upd:
        effective_user = SimpleNamespace(id=5)
        message = _Msg()
    class _Ctx:
        args = ['x.py']
        user_data = {}

    h = H(_App())
    await h.image_command(_Upd(), _Ctx())
    assert captured.get('reply_photo') is True
    assert captured.get('cleanup') is True


@pytest.mark.asyncio
async def test_preview_command_calls_cleanup(monkeypatch):
    mod = __import__('bot_handlers')
    H = getattr(mod, 'AdvancedBotHandlers')

    class _App:
        def add_handler(self, *a, **k):
            pass

    def _get_latest_version(uid, fn):
        return {'file_name': fn, 'code': "print('x')", 'programming_language': 'python'}
    monkeypatch.setattr(mod, 'db', SimpleNamespace(get_latest_version=_get_latest_version), raising=True)

    captured = {}
    class _FakeGen:
        def __init__(self, *a, **k):
            captured['inst'] = self
            self._cleanup_called = False
        def generate_image(self, *a, **k):
            return b'fake_png_data'
        def cleanup(self):
            captured['cleanup'] = True
            self._cleanup_called = True
    monkeypatch.setattr(mod, 'CodeImageGenerator', _FakeGen, raising=True)

    class _Msg:
        async def reply_text(self, *a, **k):
            captured['reply_text'] = True
        async def reply_photo(self, *a, **k):
            captured['reply_photo'] = True
    class _Upd:
        effective_user = SimpleNamespace(id=6)
        message = _Msg()
    class _Ctx:
        args = ['y.py']
        user_data = {}

    h = H(_App())
    await h.preview_command(_Upd(), _Ctx())
    assert captured.get('reply_photo') is True
    assert captured.get('cleanup') is True


@pytest.mark.asyncio
async def test_image_all_cleanup_called_once(monkeypatch):
    mod = __import__('bot_handlers')
    H = getattr(mod, 'AdvancedBotHandlers')

    class _App:
        def add_handler(self, *a, **k):
            pass

    def _get_user_files(uid, limit=20):
        return [{'file_name': 'a.py'}, {'file_name': 'b.py'}]
    def _get_latest_version(uid, fn):
        return {'file_name': fn, 'code': "print('x')", 'programming_language': 'python'}
    # Patch db APIs on module
    db_ns = SimpleNamespace(get_user_files=_get_user_files, get_latest_version=_get_latest_version)
    monkeypatch.setattr(mod, 'db', db_ns, raising=True)

    calls = {'cleanup': 0}
    class _FakeGen:
        def __init__(self, *a, **k):
            pass
        def generate_image(self, *a, **k):
            return b'fake_png_data'
        def cleanup(self):
            calls['cleanup'] += 1
    monkeypatch.setattr(mod, 'CodeImageGenerator', _FakeGen, raising=True)

    class _Msg:
        async def reply_text(self, *a, **k):
            # track edits as well
            pass
        async def reply_photo(self, *a, **k):
            pass
    class _Upd:
        effective_user = SimpleNamespace(id=7)
        message = _Msg()
    class _Ctx:
        args = []
        user_data = {}

    h = H(_App())
    await h.image_all_command(_Upd(), _Ctx())
    # cleanup is called once after loop
    assert calls['cleanup'] == 1
