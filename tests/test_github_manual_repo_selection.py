import types
import pytest


class _Msg:
    def __init__(self, text):
        self.text = text
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs))
        return self


class _Update:
    def __init__(self, text):
        self.message = _Msg(text)
        self.effective_user = types.SimpleNamespace(id=1)


class _Context:
    def __init__(self):
        self.user_data = {}
        self.bot_data = {}


@pytest.mark.asyncio
async def test_manual_repo_input_sets_selected_repo(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    update = _Update("https://github.com/owner/repo")
    context = _Context()
    context.user_data["waiting_for_manual_repo"] = True

    called = {"menu": 0}

    async def _fake_menu(update, context):
        called["menu"] += 1

    monkeypatch.setattr(handler, "github_menu_command", _fake_menu)

    handled = await handler.handle_text_input(update, context)

    session = handler.get_user_session(1)
    assert handled is True
    assert session["selected_repo"] == "owner/repo"
    assert context.user_data.get("waiting_for_manual_repo") is None
    assert called["menu"] == 1
