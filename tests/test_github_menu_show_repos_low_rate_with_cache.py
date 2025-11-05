import types
import pytest


@pytest.mark.asyncio
async def test_show_repos_low_rate_uses_stale_cache(monkeypatch):
    gh = __import__('github_menu_handler')

    handler = gh.GitHubMenuHandler()
    monkeypatch.setattr(handler, "get_user_token", lambda uid: "token")

    class _RateCore:
        remaining = 3
        limit = 5000
    class _Rate:
        core = _RateCore()
    class _G:
        def __init__(self, *a, **k):
            pass
        def get_rate_limit(self):
            return _Rate()
        def get_user(self):
            raise AssertionError("should not fetch user when using stale cache")

    monkeypatch.setattr(gh, "Github", _G)

    calls = {"answered": 0, "loading": 0, "final": 0}

    class _From: id = 99

    class _Query:
        data = "select_repo"
        from_user = _From()
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
            self.user_data = {
                "repos": [types.SimpleNamespace(name="cached", full_name="o/cached")],
                "repos_cache_time": 0,
            }
            self.bot_data = {}

    query = _Query()
    ctx = _Ctx()

    await handler.show_repo_selection(query, ctx)

    assert calls["answered"] >= 1
    assert calls["loading"] >= 1  # loading may appear before deciding to use stale cache
    assert calls["final"] >= 1  # final list shown from stale cache
