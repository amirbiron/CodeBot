import pytest
from types import SimpleNamespace
import telegram.error


class _Msg:
    def __init__(self, capture: dict):
        self.capture = capture
    async def reply_photo(self, *a, **k):
        self.capture['reply_photo'] = (a, k)
    async def reply_text(self, *a, **k):
        self.capture['reply_text'] = (a, k)

class _Query:
    def __init__(self, data: str, capture: dict, user_id: int = 1):
        self.data = data
        self._user = SimpleNamespace(id=user_id)
        self.message = _Msg(capture)
        self._capture = capture
    async def answer(self, *a, **k):
        self._capture['answer'] = (a, k)
    async def edit_message_text(self, *a, **k):
        self._capture['edit'] = (a, k)
    async def edit_message_caption(self, *a, **k):
        self._capture['caption'] = (a, k)


@pytest.mark.asyncio
async def test_img_settings_and_regenerate(monkeypatch):
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

    # Stub image generator
    class _FakeGen:
        def __init__(self, *a, **k):
            pass
        def generate_image(self, *a, **k):
            return b'fake_png_data'
    monkeypatch.setattr(mod, 'CodeImageGenerator', _FakeGen, raising=True)

    captured = {}
    h = H(_App())
    ctx = SimpleNamespace(user_data={})

    # Open settings menu
    upd = SimpleNamespace(effective_user=SimpleNamespace(id=1), callback_query=_Query('edit_image_settings_test.py', captured))
    await h.handle_callback_query(upd, ctx)
    assert 'edit' in captured  # menu shown

    # Set theme
    upd = SimpleNamespace(effective_user=SimpleNamespace(id=1), callback_query=_Query('img_set_theme:github:test.py', captured))
    await h.handle_callback_query(upd, ctx)
    assert ctx.user_data['img_settings']['test.py']['theme'] == 'github'

    # Set style
    upd = SimpleNamespace(effective_user=SimpleNamespace(id=1), callback_query=_Query('img_set_style:banner_tech:test.py', captured))
    await h.handle_callback_query(upd, ctx)
    assert ctx.user_data['img_settings']['test.py']['style'] == 'banner_tech'

    # Set width
    upd = SimpleNamespace(effective_user=SimpleNamespace(id=1), callback_query=_Query('img_set_width:1400:test.py', captured))
    await h.handle_callback_query(upd, ctx)
    assert ctx.user_data['img_settings']['test.py']['width'] == 1400

    # Regenerate
    upd = SimpleNamespace(effective_user=SimpleNamespace(id=1), callback_query=_Query('regenerate_image_test.py', captured))
    await h.handle_callback_query(upd, ctx)
    assert 'reply_photo' in captured


@pytest.mark.asyncio
async def test_save_to_drive_success(monkeypatch):
    mod = __import__('bot_handlers')
    H = getattr(mod, 'AdvancedBotHandlers')

    class _App:
        def add_handler(self, *a, **k):
            pass

    class _Facade:
        def get_latest_version(self, uid, fn):
            return {'file_name': fn, 'code': "print('x')", 'programming_language': 'python'}
    monkeypatch.setattr(mod, "_get_files_facade_or_none", lambda: _Facade())

    class _FakeGen:
        def __init__(self, *a, **k):
            pass
        def generate_image(self, *a, **k):
            return b'fake_png_data'
    monkeypatch.setattr(mod, 'CodeImageGenerator', _FakeGen, raising=True)

    # Stub drive upload without importing heavy module
    import sys, types
    fake = types.ModuleType('services.google_drive_service')
    setattr(fake, 'upload_bytes', lambda uid, filename, data, sub_path=None: 'fid123')
    sys.modules['services.google_drive_service'] = fake

    captured = {}
    h = H(_App())
    ctx = SimpleNamespace(user_data={})

    upd = SimpleNamespace(effective_user=SimpleNamespace(id=1), callback_query=_Query('save_to_drive_test.py', captured))
    await h.handle_callback_query(upd, ctx)
    # expect edit text with fid
    assert 'edit' in captured
    args, kwargs = captured['edit']
    assert 'fid123' in (args[0] if args else '') or 'fid123' in (kwargs.get('text', '') if kwargs else '')


@pytest.mark.asyncio
async def test_edit_settings_caption_fallback(monkeypatch):
    mod = __import__('bot_handlers')
    H = getattr(mod, 'AdvancedBotHandlers')

    class _App:
        def add_handler(self, *a, **k):
            pass

    captured = {}
    h = H(_App())
    ctx = SimpleNamespace(user_data={})

    class _QueryFail(_Query):
        async def edit_message_text(self, *a, **k):
            raise telegram.error.BadRequest("Message can't be edited")

    upd = SimpleNamespace(
        effective_user=SimpleNamespace(id=1),
        callback_query=_QueryFail('edit_image_settings_test.py', captured),
    )
    await h.handle_callback_query(upd, ctx)
    assert 'caption' in captured or 'reply_text' in captured
