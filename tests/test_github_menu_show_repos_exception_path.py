import pytest


@pytest.mark.asyncio
async def test_show_repos_exception_after_ack_uses_edit(monkeypatch):
    gh = __import__('github_menu_handler')

    handler = gh.GitHubMenuHandler()
    monkeypatch.setattr(handler, "get_user_token", lambda uid: "token")

    class _G:
        def __init__(self, *a, **k):
            pass
        def get_rate_limit(self):
            raise RuntimeError("explode in rate limit")

    monkeypatch.setattr(gh, "Github", _G)

    calls = {"answered": 0, "error": 0}

    class _From: id = 55

    class _Query:
        data = "select_repo"
        from_user = _From()
        message = object()
        async def answer(self, *a, **k):
            calls["answered"] += 1
            return None
        async def edit_message_text(self, text: str, **kwargs):
            if text.startswith("❌ שגיאה") or text.startswith("⏳ "):
                calls["error"] += 1
            return None

    class _Ctx:
        def __init__(self):
            self.user_data = {}
            self.bot_data = {}

    query = _Query()
    ctx = _Ctx()

    await handler.show_repo_selection(query, ctx)

    assert calls["answered"] >= 1
    assert calls["error"] >= 1
