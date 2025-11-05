import types
import pytest


@pytest.mark.asyncio
async def test_show_repos_loading_edit_raises_then_final_succeeds(monkeypatch):
    gh = __import__('github_menu_handler')

    handler = gh.GitHubMenuHandler()
    monkeypatch.setattr(handler, "get_user_token", lambda uid: "token")

    # avoid real delay
    async def _no_delay(user_id: int):
        return None
    monkeypatch.setattr(handler, "apply_rate_limit_delay", _no_delay)

    class _RateCore:
        remaining = 5000
        limit = 5000
    class _Rate:
        core = _RateCore()
    class _User:
        login = "tester"
        def get_repos(self):
            return [types.SimpleNamespace(name="r1", full_name="o/r1")]
    class _G:
        def __init__(self, *a, **k):
            pass
        def get_rate_limit(self):
            return _Rate()
        def get_user(self):
            return _User()

    monkeypatch.setattr(gh, "Github", _G)

    calls = {"answered": 0, "loading_raised": 0, "final": 0}

    class _From: id = 1

    class _Query:
        data = "select_repo"
        from_user = _From()
        message = object()
        async def answer(self, *a, **k):
            calls["answered"] += 1
            return None
        async def edit_message_text(self, text: str, **kwargs):
            if "טוען" in text:
                calls["loading_raised"] += 1
                raise RuntimeError("cannot edit loading")
            if "בחר ריפוזיטורי" in text:
                calls["final"] += 1
            return None

    class _Ctx:
        def __init__(self):
            self.user_data = {}
            self.bot_data = {}

    query = _Query()
    ctx = _Ctx()

    await handler.show_repo_selection(query, ctx)

    assert calls["answered"] >= 1
    assert calls["loading_raised"] >= 1
    assert calls["final"] >= 1
