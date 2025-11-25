import types
import pytest


@pytest.mark.asyncio
async def test_commit_restore_action_buttons_under_limit(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    session = handler.get_user_session(42)
    session["selected_repo"] = "owner/repo"
    monkeypatch.setattr(handler, "get_user_token", lambda _: "tok")

    commit_sha = "a" * 40

    class _Commit:
        def __init__(self, sha):
            self.sha = sha
            self.html_url = "https://example.test/commit"
            author = types.SimpleNamespace(name="Bot", date=None)
            self.commit = types.SimpleNamespace(message="msg", author=author)

    class _Repo:
        def get_commit(self, sha):
            assert sha == commit_sha
            return _Commit(sha)

    class _Gh:
        def __init__(self, *args, **kwargs):
            pass

        def get_repo(self, full_name):
            assert full_name == "owner/repo"
            return _Repo()

    monkeypatch.setattr(gh, "Github", _Gh)

    captured = []

    def fake_button(text, **kwargs):
        data = kwargs.get("callback_data")
        if data:
            captured.append(data)
        return types.SimpleNamespace(text=text, data=data, kwargs=kwargs)

    monkeypatch.setattr(gh, "InlineKeyboardButton", fake_button)
    monkeypatch.setattr(gh, "InlineKeyboardMarkup", lambda rows: rows)

    class _Query:
        def __init__(self):
            self.from_user = types.SimpleNamespace(id=42)

        async def edit_message_text(self, *args, **kwargs):
            return None

    update = types.SimpleNamespace(callback_query=_Query())
    context = types.SimpleNamespace(user_data={})

    await handler.show_commit_restore_actions(update, context, commit_sha)

    assert captured, "callback_data entries should be collected"
    assert max(len(data) for data in captured if data) <= 64
    assert any(data.startswith(gh.CALLBACK_BRANCH_FROM_COMMIT) for data in captured)
    assert any(data.startswith(gh.CALLBACK_REVERT_PR_FROM_COMMIT) for data in captured)
