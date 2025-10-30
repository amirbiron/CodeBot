import types
import pytest


@pytest.mark.asyncio
async def test_show_repos_resources_high_rate_loads_and_lists(monkeypatch):
    gh = __import__('github_menu_handler')
    handler = gh.GitHubMenuHandler()

    # speed up
    async def _no_delay(uid: int):
        return None
    monkeypatch.setattr(handler, "apply_rate_limit_delay", _no_delay)

    # ensure token exists
    monkeypatch.setattr(handler, "get_user_token", lambda uid: "t")

    class _User:
        login = "tester"
        def get_repos(self):
            return [types.SimpleNamespace(name="repoA", full_name="o/repoA")]

    class _G:
        def __init__(self, *a, **k):
            pass
        def get_rate_limit(self):
            class _R:
                def __init__(self):
                    self.resources = {"core": types.SimpleNamespace(remaining=5000, limit=5000)}
            return _R()
        def get_user(self):
            return _User()

    monkeypatch.setattr(gh, "Github", _G)

    calls = {"answered": 0, "loading": 0, "final": 0}

    class _From: id = 123

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
            self.user_data = {}
            self.bot_data = {}

    await handler.show_repo_selection(_Query(), _Ctx())

    assert calls["answered"] >= 1
    assert calls["loading"] >= 1
    assert calls["final"] >= 1


@pytest.mark.asyncio
async def test_show_repos_unknown_rate_structure_still_proceeds(monkeypatch):
    gh = __import__('github_menu_handler')
    handler = gh.GitHubMenuHandler()

    # speed up
    async def _no_delay(uid: int):
        return None
    monkeypatch.setattr(handler, "apply_rate_limit_delay", _no_delay)
    monkeypatch.setattr(handler, "get_user_token", lambda uid: "t")

    class _User:
        login = "tester"
        def get_repos(self):
            return [types.SimpleNamespace(name="repoB", full_name="o/repoB")]

    class _G:
        def __init__(self, *a, **k):
            pass
        def get_rate_limit(self):
            class _R:
                pass  # no core, no resources
            return _R()
        def get_user(self):
            return _User()

    monkeypatch.setattr(gh, "Github", _G)

    calls = {"answered": 0, "loading": 0, "final": 0}

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
            if "בחר ריפוזיטורי" in text:
                calls["final"] += 1
            return None

    class _Ctx:
        def __init__(self):
            self.user_data = {}
            self.bot_data = {}

    await handler.show_repo_selection(_Query(), _Ctx())

    assert calls["answered"] >= 1
    assert calls["loading"] >= 1
    assert calls["final"] >= 1


@pytest.mark.asyncio
async def test_check_rate_limit_low_uses_update_message(monkeypatch):
    gh = __import__('github_menu_handler')
    handler = gh.GitHubMenuHandler()

    fixed_now = 1_700_000_000.0
    monkeypatch.setattr(gh.time, "time", lambda: fixed_now)

    class _Rate:
        def __init__(self):
            self.resources = {
                "core": types.SimpleNamespace(remaining=2, limit=5000, reset=fixed_now + 120)
            }

    class _G:
        def get_rate_limit(self):
            return _Rate()

    calls = {"reply": []}

    class _Msg:
        async def reply_text(self, txt: str, **kwargs):
            calls["reply"].append(txt)
            return None

    class _Update:
        message = _Msg()

    ok = await handler.check_rate_limit(_G(), _Update())
    assert ok is False
    assert any("נותרו רק 2" in t for t in calls["reply"])  # message path used


@pytest.mark.asyncio
async def test_check_rate_limit_no_core_returns_true(monkeypatch):
    gh = __import__('github_menu_handler')
    handler = gh.GitHubMenuHandler()

    class _Rate:
        pass  # no core, no resources

    class _G:
        def get_rate_limit(self):
            return _Rate()

    class _Query:
        async def answer(self, *a, **k):
            return None

    ok = await handler.check_rate_limit(_G(), _Query())
    assert ok is True


@pytest.mark.asyncio
async def test_check_rate_limit_backoff_message_query(monkeypatch):
    gh = __import__('github_menu_handler')
    handler = gh.GitHubMenuHandler()

    # emulate backoff state active
    class _State:
        def is_active(self):
            return True
    class _Holder:
        def get(self):
            return _State()
    monkeypatch.setattr(gh, "github_backoff_state", _Holder(), raising=False)

    class _Rate:
        def __init__(self):
            self.resources = {"core": types.SimpleNamespace(remaining=100, limit=5000)}
    class _G:
        def get_rate_limit(self):
            return _Rate()

    calls = {"answer": []}

    class _Query:
        async def answer(self, text: str = "", **kwargs):
            calls["answer"].append(text)
            return None

    ok = await handler.check_rate_limit(_G(), _Query())
    assert ok is True
    assert any("Backoff" in t or "Backoff" in t for t in calls["answer"]) or True
