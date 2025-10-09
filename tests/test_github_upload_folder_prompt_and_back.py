import types
import pytest
import asyncio


@pytest.mark.asyncio
async def test_upload_folder_create_prompts_and_back(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()

    class _Msg:
        def __init__(self):
            self.texts = []
        async def reply_text(self, text, **kwargs):
            self.texts.append(text)
            return self
    class _Q:
        def __init__(self):
            self.data = "upload_folder_create"
            self.from_user = types.SimpleNamespace(id=13)
            self.message = _Msg()
        async def edit_message_text(self, text, reply_markup=None, parse_mode=None):
            self.message.texts.append(text)
            return self.message
        async def answer(self, *a, **k):
            return None
    class _U:
        def __init__(self):
            self.callback_query = _Q()
            self.effective_user = types.SimpleNamespace(id=13)
            self.message = types.SimpleNamespace(text=None, from_user=types.SimpleNamespace(id=13))
    ctx = types.SimpleNamespace(user_data={}, bot_data={})

    await asyncio.wait_for(handler.handle_menu_callback(_U(), ctx), timeout=2.0)
    # Waiting flag should be set
    assert ctx.user_data.get("waiting_for_new_folder_path") is True
