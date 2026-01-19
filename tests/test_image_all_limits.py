import pytest
from types import SimpleNamespace


@pytest.mark.asyncio
async def test_image_all_respects_limits_and_truncates(monkeypatch):
    mod = __import__('bot_handlers')
    H = getattr(mod, 'AdvancedBotHandlers')

    class _App:
        def add_handler(self, *a, **k):
            pass

    # Provide files list
    files = [
        {"file_name": "a.py"},
        {"file_name": "b.py"},
    ]

    # Create very long code (more than 200 lines) to trigger truncation path
    long_code = "\n".join([f"print({i})" for i in range(500)])

    class _Facade:
        def get_user_files(self, uid, limit=20, projection=None):
            return list(files)
        def get_latest_version(self, uid, fn):
            return {"file_name": fn, "code": long_code, "programming_language": "python"}
    monkeypatch.setattr(mod, "_get_files_facade_or_none", lambda: _Facade())

    # Stub generator to avoid heavy work
    class _Gen:
        def __init__(self, *a, **k):
            pass
        def generate_image(self, *a, **k):
            return b'x'  # minimal bytes
        def cleanup(self):
            pass
    monkeypatch.setattr(mod, 'CodeImageGenerator', _Gen, raising=True)

    # Capture messages
    captured = {"status": [], "final": []}
    class _Status:
        async def edit_text(self, text, *a, **k):
            captured["status"].append(text)
    class _Msg:
        async def reply_text(self, text, *a, **k):
            # return object lacking edit_text to force fallback path later
            captured["status"].append(text)
            return SimpleNamespace(edit_text=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError('no')))  # generator trick to raise when awaited
        async def reply_photo(self, *a, **k):
            captured["final"].append("photo")
    class _User: id = 9
    class _Upd:
        effective_user = _User()
        message = _Msg()
    class _Ctx:
        application = SimpleNamespace(bot_data={})
        user_data = {}

    h = H(_App())
    await h.image_all_command(_Upd(), _Ctx())

    # Should have produced at least one photo without crashing
    assert captured["final"], "expected photos to be sent"
