import types
import pytest
from datetime import datetime, timezone


@pytest.mark.asyncio
async def test_check_rate_limit_resources_low_timestamp(monkeypatch):
    gh = __import__('github_menu_handler')

    handler = gh.GitHubMenuHandler()

    fixed_now = 1_700_000_000.0
    monkeypatch.setattr(gh.time, "time", lambda: fixed_now)

    class _Rate:
        def __init__(self):
            self.resources = {
                "core": types.SimpleNamespace(remaining=5, limit=5000, reset=fixed_now + 600.0)
            }

    class _G:
        def get_rate_limit(self):
            return _Rate()

    calls = {"answer": []}

    class _Query:
        async def answer(self, text: str, **kwargs):
            calls["answer"].append(text)
            return None

    ok = await handler.check_rate_limit(_G(), _Query())
    assert ok is False
    assert any("נותרו רק 5" in t for t in calls["answer"])  # remaining reflected
    assert any("10" in t for t in calls["answer"])  # 10 minutes until reset


@pytest.mark.asyncio
async def test_check_rate_limit_resources_low_datetime(monkeypatch):
    gh = __import__('github_menu_handler')

    handler = gh.GitHubMenuHandler()

    fixed_now = 1_700_000_000.0
    monkeypatch.setattr(gh.time, "time", lambda: fixed_now)

    reset_dt = datetime.fromtimestamp(fixed_now + 300.0, tz=timezone.utc)

    class _Rate:
        def __init__(self):
            self.resources = {
                "core": types.SimpleNamespace(remaining=3, limit=5000, reset=reset_dt)
            }

    class _G:
        def get_rate_limit(self):
            return _Rate()

    calls = {"answer": []}

    class _Query:
        async def answer(self, text: str, **kwargs):
            calls["answer"].append(text)
            return None

    ok = await handler.check_rate_limit(_G(), _Query())
    assert ok is False
    assert any("נותרו רק 3" in t for t in calls["answer"])  # remaining reflected
    assert any("5" in t for t in calls["answer"])  # 5 minutes until reset


@pytest.mark.asyncio
async def test_show_repos_low_rate_uses_resources_no_core(monkeypatch):
    gh = __import__('github_menu_handler')

    handler = gh.GitHubMenuHandler()
    monkeypatch.setattr(handler, "get_user_token", lambda uid: "token")

    class _Rate:
        def __init__(self):
            self.resources = {
                "core": types.SimpleNamespace(remaining=5, limit=5000)
            }

    class _G:
        def __init__(self, *a, **k):
            pass
        def get_rate_limit(self):
            return _Rate()
        def get_user(self):
            raise AssertionError("get_user should not be called when low rate and no cache")

    monkeypatch.setattr(gh, "Github", _G)

    calls = {"answered": 0, "loading": 0, "low": 0, "final": 0}

    class _From: id = 7

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
            if "מגבלת API" in text:
                calls["low"] += 1
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
    assert calls["loading"] >= 1
    assert calls["low"] >= 1
    assert calls["final"] == 0
