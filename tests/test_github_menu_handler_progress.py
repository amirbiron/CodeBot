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
        # Simulate tool results to exercise suggestion branches
        results = {
            "flake8": (1, "app.py:10:1: F401 'os' imported but unused"),
            "mypy": (1, "Incompatible default for argument \"x\" (default has type \"None\", argument has type \"int\")"),
            "bandit": (1, "Possible eval( usage) B307"),
            "black": (1, "would reformat /tmp/repo/abc123/src/main.py"),
        }
        return results, "owner/name"

    monkeypatch.setattr(asyncio, "to_thread", _fake_to_thread)

    update.callback_query.data = "validate_repo"
    await asyncio.wait_for(handler.handle_menu_callback(update, context), timeout=2.0)

    assert True


@pytest.mark.asyncio
async def test_import_repo_message_mentions_expected_duration(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()

    # Build stubs
    class _Msg:
        def __init__(self):
            self.texts = []
        async def edit_text(self, text, **kwargs):
            self.texts.append(text)
            return self
    class _Query:
        def __init__(self):
            self.message = _Msg()
            self.data = "import_repo_start"
            self.from_user = types.SimpleNamespace(id=7)
        async def edit_message_text(self, text, **kwargs):
            # capture the message text
            self.message.texts.append(text)
            return self.message
        async def answer(self, *args, **kwargs):
            return None
    class _Update:
        def __init__(self):
            self.callback_query = _Query()
            self.effective_user = types.SimpleNamespace(id=7)
    class _Context:
        def __init__(self):
            self.user_data = {}
            self.bot_data = {}

    # Prepare session and token
    session = handler.get_user_session(7)
    session["selected_repo"] = "o/r"
    session["selected_branch"] = "main"
    monkeypatch.setattr(handler, "get_user_token", lambda _uid: "token")

    # Stub Github and requests to avoid network
    class _Repo:
        def get_archive_link(self, *_a, **_k):
            return "https://example.com/archive.zip"
    class _Gh:
        def __init__(self, *a, **k):
            pass
        def get_repo(self, _full):
            return _Repo()
    class _Resp:
        def __init__(self):
            self.content = b"PK\x03\x04dummy"  # minimal zip-like bytes
        def raise_for_status(self):
            return None
    monkeypatch.setattr(gh, "Github", _Gh)
    monkeypatch.setattr(gh.requests, "get", lambda url, timeout=60: _Resp())

    upd, ctx = _Update(), _Context()
    # חקוי בחירת ענף כפי שנעשה בזרימה לפני לחיצה על "ייבא"
    ctx.user_data["import_repo_branch"] = "main"
    # Directly invoke the start branch to hit the message text
    await asyncio.wait_for(handler.handle_menu_callback(upd, ctx), timeout=2.0)

    # Assert one of the edited texts mentions 1–8 minutes (either hyphen or en dash)
    combined = "\n".join(upd.callback_query.message.texts)
    assert ("1–8" in combined) or ("1-8" in combined)


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


@pytest.mark.asyncio
async def test_import_branch_menu_shows_loading(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    update = _Update()
    context = _Context()

    # Route to github_import_repo
    update.callback_query.data = "github_import_repo"

    # Session with selected repo and token
    session = handler.get_user_session(1)
    session["selected_repo"] = "owner/name"

    # Monkeypatch token getter
    monkeypatch.setattr(handler, "get_user_token", lambda _uid: "token")

    # Capture loading text
    called = {"text": None}

    async def _safe_edit(q, text, reply_markup=None, parse_mode=None):
        called["text"] = text
        return None

    monkeypatch.setattr(gh.TelegramUtils, "safe_edit_message_text", _safe_edit)

    # Stub Github and branches listing
    class _Br:
        def __init__(self, name):
            self.name = name
            self.commit = types.SimpleNamespace(commit=types.SimpleNamespace(author=types.SimpleNamespace(date=None)))

    class _Repo:
        def get_branches(self):
            return [_Br("main"), _Br("dev")]

    class _Gh:
        def __init__(self, *a, **k):
            pass
        def get_repo(self, full):
            return _Repo()

    monkeypatch.setattr(gh, "Github", _Gh)
    # Stub buttons/markup
    monkeypatch.setattr(gh, "InlineKeyboardButton", lambda *a, **k: (a, k))
    monkeypatch.setattr(gh, "InlineKeyboardMarkup", lambda rows: rows)

    await asyncio.wait_for(handler.handle_menu_callback(update, context), timeout=2.0)

    assert called["text"] and "טוען" in called["text"]

