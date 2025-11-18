import pytest
from types import SimpleNamespace


@pytest.mark.asyncio
async def test_image_command_keyboard_labels(monkeypatch):
    mod = __import__('bot_handlers')
    H = getattr(mod, 'AdvancedBotHandlers')

    class _App:
        def add_handler(self, *a, **k):
            pass

    # DB returns code
    def _get_latest_version(uid, fn):
        return {'file_name': fn, 'code': "print('x')", 'programming_language': 'python'}
    db_mod = __import__('database', fromlist=['db'])
    monkeypatch.setattr(db_mod, 'db', SimpleNamespace(get_latest_version=_get_latest_version), raising=True)
    monkeypatch.setattr(mod, 'db', SimpleNamespace(get_latest_version=_get_latest_version), raising=True)

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
    # Verify keyboard labels contain the updated Hebrew labels
    kb = captured['photo'][1].get('reply_markup')
    assert kb is not None
    labels = [btn.text for row in getattr(kb, 'inline_keyboard', []) for btn in row]
    assert any('צור מחדש' in t for t in labels)
    assert any('ערוך הגדרות' in t for t in labels)
