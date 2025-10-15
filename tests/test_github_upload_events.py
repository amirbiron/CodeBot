import types
import pytest

import github_menu_handler as gh


@pytest.mark.asyncio
async def test_emit_event_on_direct_upload_start(monkeypatch):
    handler = gh.GitHubMenuHandler()

    # stub session
    handler.get_user_session = lambda uid: {"selected_repo": "owner/repo"}

    # captured events
    captured = {"events": []}
    def _emit(evt, severity="info", **fields):
        captured["events"].append((evt, severity, fields))

    # patch emit_event inside module
    monkeypatch.setattr(gh, "emit_event", _emit, raising=False)

    # minimal context/update stubs
    class _Msg:
        document = types.SimpleNamespace(file_name="file.txt")
        from_user = types.SimpleNamespace(id=1)
        async def reply_text(self, *a, **k):
            return None
    class _Bot:
        async def get_file(self, file_id):
            class _F:
                async def download_as_bytearray(self):
                    return bytearray(b"content")
            return _F()
    class _Update:
        message = _Msg()
        effective_user = types.SimpleNamespace(id=1)
    class _Ctx:
        bot = _Bot()
        user_data = {"waiting_for_github_upload": True, "target_repo": "owner/repo"}

    await handler.handle_file_upload(_Update(), _Ctx())

    assert any(e[0] == "github_upload_start" for e in captured["events"])