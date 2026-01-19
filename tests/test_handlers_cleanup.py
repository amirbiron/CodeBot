import pytest
from types import SimpleNamespace


@pytest.mark.asyncio
async def test_image_command_calls_cleanup(monkeypatch):
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

    class _Facade:
        def get_latest_version(self, uid, fn):
            return {'file_name': fn, 'code': "print('x')", 'programming_language': 'python'}
    monkeypatch.setattr(mod, "_get_files_facade_or_none", lambda: _Facade())

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

    class _Facade:
        def get_user_files(self, uid, limit=20, projection=None):
            return [{'file_name': 'a.py'}, {'file_name': 'b.py'}]
        def get_latest_version(self, uid, fn):
            return {'file_name': fn, 'code': "print('x')", 'programming_language': 'python'}
    monkeypatch.setattr(mod, "_get_files_facade_or_none", lambda: _Facade())

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


@pytest.mark.asyncio
async def test_image_all_status_edit_succeeds(monkeypatch):
    mod = __import__('bot_handlers')
    H = getattr(mod, 'AdvancedBotHandlers')

    async def _check_rate_limit(*_a, **_k):
        return True

    monkeypatch.setattr(mod, 'reporter', SimpleNamespace(report_activity=lambda *a, **k: None), raising=True)
    monkeypatch.setattr(mod.image_rate_limiter, 'check_rate_limit', _check_rate_limit, raising=True)

    class _App:
        def add_handler(self, *a, **k):
            pass

    files = [{'file_name': f'f{i}.py'} for i in range(5)]

    class _Facade:
        def get_user_files(self, _uid, limit=20, projection=None):
            return files
        def get_latest_version(self, _uid, fn):
            return {'file_name': fn, 'code': "print('x')", 'programming_language': 'python'}
    monkeypatch.setattr(mod, "_get_files_facade_or_none", lambda: _Facade())

    tracker = {'cleanup': 0}

    class _FakeGen:
        def __init__(self, *a, **k):
            tracker['inst'] = self

        def generate_image(self, *a, **k):
            return b'fake_png_data'

        def cleanup(self):
            tracker['cleanup'] += 1

    monkeypatch.setattr(mod, 'CodeImageGenerator', _FakeGen, raising=True)

    class _Status:
        def __init__(self):
            self.edits = []

        async def edit_text(self, text):
            self.edits.append(text)

    class _Msg:
        def __init__(self):
            self.status = _Status()
            self.texts = []
            self.photos = 0

        async def reply_text(self, text, *a, **k):
            self.texts.append(text)
            if len(self.texts) == 1:
                return self.status
            return None

        async def reply_photo(self, *a, **k):
            self.photos += 1

    class _Upd:
        effective_user = SimpleNamespace(id=8)
        message = _Msg()

    class _Ctx:
        args = []
        user_data = {}

    h = H(_App())
    await h.image_all_command(_Upd(), _Ctx())

    assert _Upd.message.photos == len(files)
    assert tracker['cleanup'] == 1
    assert _Upd.message.texts[0] == f"🎨 יוצר {len(files)} תמונות...\n0/{len(files)} הושלמו"
    assert _Upd.message.status.edits == [
        f"🎨 יוצר {len(files)} תמונות...\n{len(files)}/{len(files)} הושלמו",
        f"✅ הושלם! נוצרו {len(files)}/{len(files)} תמונות.",
    ]


@pytest.mark.asyncio
async def test_image_all_status_fallback_to_reply_text(monkeypatch):
    mod = __import__('bot_handlers')
    H = getattr(mod, 'AdvancedBotHandlers')

    async def _check_rate_limit(*_a, **_k):
        return True

    monkeypatch.setattr(mod, 'reporter', SimpleNamespace(report_activity=lambda *a, **k: None), raising=True)
    monkeypatch.setattr(mod.image_rate_limiter, 'check_rate_limit', _check_rate_limit, raising=True)

    class _App:
        def add_handler(self, *a, **k):
            pass

    files = [{'file_name': 'a.py'}, {'file_name': 'b.py'}]

    class _Facade:
        def get_user_files(self, _uid, limit=20, projection=None):
            return files
        def get_latest_version(self, _uid, fn):
            return {'file_name': fn, 'code': "print('x')", 'programming_language': 'python'}
    monkeypatch.setattr(mod, "_get_files_facade_or_none", lambda: _Facade())

    tracker = {'cleanup': 0}

    class _FakeGen:
        def __init__(self, *a, **k):
            tracker['inst'] = self

        def generate_image(self, *a, **k):
            return b'fake_png_data'

        def cleanup(self):
            tracker['cleanup'] += 1

    monkeypatch.setattr(mod, 'CodeImageGenerator', _FakeGen, raising=True)

    class _Msg:
        def __init__(self):
            self.texts = []
            self.photos = 0

        async def reply_text(self, text, *a, **k):
            self.texts.append(text)
            return None

        async def reply_photo(self, *a, **k):
            self.photos += 1

    class _Upd:
        effective_user = SimpleNamespace(id=9)
        message = _Msg()

    class _Ctx:
        args = []
        user_data = {}

    h = H(_App())
    await h.image_all_command(_Upd(), _Ctx())

    assert _Upd.message.photos == len(files)
    assert tracker['cleanup'] == 1
    assert _Upd.message.texts == [
        f"🎨 יוצר {len(files)} תמונות...\n0/{len(files)} הושלמו",
        f"✅ הושלם! נוצרו {len(files)}/{len(files)} תמונות.",
    ]