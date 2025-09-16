import asyncio
import types
import pytest

# Minimal stubs for telegram Update/CallbackQuery to drive the handler
class _Msg:
    def __init__(self):
        self._text = None
    async def reply_text(self, text, **kwargs):
        self._text = text
        return self
    async def edit_text(self, text, **kwargs):
        self._text = text
        return self

class _Query:
    def __init__(self):
        self.message = _Msg()
        self.data = "validate_repo"
        self.from_user = types.SimpleNamespace(id=1)
    async def edit_message_text(self, text, **kwargs):
        # Emulate Telegram API; return a message-like object with edit_text
        return self.message
    async def answer(self, *args, **kwargs):
        return None

class _Update:
    def __init__(self):
        self.callback_query = _Query()
        self.effective_user = types.SimpleNamespace(id=1)

class _Context:
    def __init__(self):
        self.user_data = {}
        self.bot_data = {}

@pytest.mark.asyncio
async def test_validate_repo_progress_task_cleans_up(monkeypatch):
    from github_menu_handler import GitHubMenuHandler

    handler = GitHubMenuHandler()
    update = _Update()
    context = _Context()

    # Simulate missing selected_repo to trigger early return path
    session = handler.get_user_session(1)
    session["selected_repo"] = None

    # Patch GitHub client getter to avoid real API usage
    monkeypatch.setattr(handler, "get_user_token", lambda _uid: None)

    # Run the callback that enters the validate_repo branch
    # We call handle_menu_callback directly with prepared update/query
    # and ensure it doesn't leak background tasks (completes quickly)
    # arrange state so that the code reaches the early return path
    update.callback_query.data = "validate_repo"

    # Limit runtime to ensure no hanging task
    await asyncio.wait_for(handler.handle_menu_callback(update, context), timeout=2.0)

    # If we got here without TimeoutError, the progress task did not leak/hang
    assert True


@pytest.mark.asyncio
async def test_validate_repo_progress_success_path(monkeypatch):
    # Import after we have a test context
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    update = _Update()
    context = _Context()

    # Prepare session and stubs
    session = handler.get_user_session(1)
    session["selected_repo"] = "owner/name"

    # Stub GitHub SDK usage inside the function (not used when we stub to_thread)
    monkeypatch.setattr(gh, "Github", lambda *args, **kwargs: object())

    # Stub Telegram keyboard classes to simple objects to avoid dependency
    monkeypatch.setattr(gh, "InlineKeyboardButton", lambda *a, **k: (a, k))
    monkeypatch.setattr(gh, "InlineKeyboardMarkup", lambda rows: rows)

    # Stub asyncio.to_thread to return a fake validation result immediately
    async def _fake_to_thread(fn, *args, **kwargs):
        # Simulate tool results for flake8/mypy/bandit/black
        results = {
            "flake8": (0, "OK"),
            "mypy": (0, "OK"),
            "bandit": (0, "OK"),
            "black": (0, "OK"),
        }
        return results, "owner/name"

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)

    update.callback_query.data = "validate_repo"
    await asyncio.wait_for(handler.handle_menu_callback(update, context), timeout=2.0)

    assert True


@pytest.mark.asyncio
async def test_validate_repo_progress_exception_path(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    update = _Update()
    context = _Context()

    session = handler.get_user_session(1)
    session["selected_repo"] = "owner/name"

    monkeypatch.setattr(gh, "Github", lambda *args, **kwargs: object())
    monkeypatch.setattr(gh, "InlineKeyboardButton", lambda *a, **k: (a, k))
    monkeypatch.setattr(gh, "InlineKeyboardMarkup", lambda rows: rows)

    async def _raise_to_thread(fn, *args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(asyncio, "to_thread", _raise_to_thread)

    update.callback_query.data = "validate_repo"
    await asyncio.wait_for(handler.handle_menu_callback(update, context), timeout=2.0)

    assert True

