import types
import pytest


@pytest.mark.asyncio
async def test_show_repos_ack_and_loading(monkeypatch):
    gh = __import__('github_menu_handler')

    handler = gh.GitHubMenuHandler()

    # Force token present so flow proceeds
    monkeypatch.setattr(handler, "get_user_token", lambda uid: "token")

    # Stub Github client to avoid network and be fast
    class _RateCore:
        remaining = 5000
        limit = 5000
    class _Rate:
        core = _RateCore()
    class _User:
        login = "tester"
        def get_repos(self):
            # minimal repo objects with fields used by UI
            return [types.SimpleNamespace(name="repo1", full_name="owner/repo1")]
    class _G:
        def __init__(self, *a, **k):
            pass
        def get_rate_limit(self):
            return _Rate()
        def get_user(self):
            return _User()

    monkeypatch.setattr(gh, "Github", _G)

    # Capture calls on the query object
    calls = {"answered": 0, "loading": 0, "final": 0}

    class _From: id = 123

    class _Query:
        data = "select_repo"
        from_user = _From()
        # show_repo_selection passes query.message as update, it's unused in our path
        message = object()
        async def answer(self, *a, **k):
            calls["answered"] += 1
            return None
        async def edit_message_text(self, text: str, **kwargs):
            if "טוען" in text or "⏳" in text:
                calls["loading"] += 1
            if "בחר ריפוזיטורי" in text:
                calls["final"] += 1
            return None

    class _Ctx:
        def __init__(self):
            self.user_data = {}
            self.bot_data = {}

    query = _Query()
    ctx = _Ctx()

    # Call through the public entry which delegates into show_repos
    await handler.show_repo_selection(query, ctx)

    # We expect immediate ack and a loading message before the final list
    assert calls["answered"] >= 1
    assert calls["loading"] >= 1
    assert calls["final"] >= 1
