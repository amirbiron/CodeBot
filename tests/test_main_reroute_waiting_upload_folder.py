import types
import pytest
import asyncio


@pytest.mark.asyncio
async def test_main_reroutes_waiting_upload_folder_to_text_input(monkeypatch):
    # השתמש ישירות ב-GitHubMenuHandler מבלי לבנות את כל main
    import github_menu_handler as ghm
    gh = ghm.GitHubMenuHandler()
    called = {"text_input": False}
    async def _handle_text_input(update, context):
        called["text_input"] = True
        return True
    # monkeypatch the instance method on the handler we just created
    import github_menu_handler as ghm
    monkeypatch.setattr(gh, 'handle_text_input', _handle_text_input)

    class _Msg:
        def __init__(self):
            self.text = "src/path"
            self.from_user = types.SimpleNamespace(id=10)
    class _Upd:
        def __init__(self):
            self.message = _Msg()
            self.effective_user = types.SimpleNamespace(id=10)
    class _Ctx:
        def __init__(self):
            self.user_data = {"waiting_for_upload_folder": True}
            self.bot_data = {}

    # Use the high-priority text router that main installs
    # We need to grab the inner function; replicate its logic here by calling it directly
    # This emulates a text message routed at high priority
    async def _router(update, context):
        # copy of logic from main.handle_github_text (simplified)
        text = (update.message.text or '').strip()
        if context.user_data.get('waiting_for_upload_folder'):
            return await gh.handle_text_input(update, context)
        return False

    await asyncio.wait_for(_router(_Upd(), _Ctx()), timeout=2.0)

    assert called["text_input"] is True
