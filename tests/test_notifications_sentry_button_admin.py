import types
import pytest
import sys


class _Msg:
    async def edit_text(self, *a, **k):
        return self


class _Query:
    def __init__(self, uid):
        self.from_user = types.SimpleNamespace(id=uid)
        self.message = _Msg()
        self.answered = []

    async def answer(self, text=None, show_alert=False):
        self.answered.append((text, show_alert))

    async def edit_message_text(self, text, **kwargs):
        return await self.message.edit_text(text, **kwargs)


class _Update:
    def __init__(self, uid):
        self.callback_query = _Query(uid)
        self.effective_user = types.SimpleNamespace(id=uid)


@pytest.mark.asyncio
async def test_notifications_sentry_test_admin_logs_and_returns(monkeypatch):
    # Minimal stubs to satisfy imports in http_sync and github
    requests_mod = types.SimpleNamespace(
        Session=lambda: types.SimpleNamespace(request=lambda *a, **k: types.SimpleNamespace(status_code=200))
    )
    requests_adapters = types.SimpleNamespace(HTTPAdapter=object)
    sys.modules.setdefault("requests", requests_mod)
    sys.modules.setdefault("requests.adapters", requests_adapters)

    class _DummyGithub:
        def __init__(self, *a, **k):
            pass
    gh_pkg = types.ModuleType("github")
    gh_pkg.Github = _DummyGithub
    gh_pkg.GithubException = Exception
    sys.modules["github"] = gh_pkg
    ige_mod = types.ModuleType("github.InputGitTreeElement")
    class _IGE:
        pass
    ige_mod.InputGitTreeElement = _IGE
    sys.modules["github.InputGitTreeElement"] = ige_mod

    # Stub config.config to avoid pydantic dependency and enable feature flag
    cfg_mod = types.ModuleType("config")
    cfg_mod.config = types.SimpleNamespace(ADMIN_USER_IDS=[], SENTRY_TEST_BUTTON_ENABLED=True)
    sys.modules["config"] = cfg_mod

    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()

    # Make user admin by setting imported object's list and ensure feature flag
    gh.config.ADMIN_USER_IDS = [999]
    gh.config.SENTRY_TEST_BUTTON_ENABLED = True

    # Avoid full menu rendering
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(handler, "show_notifications_menu", _noop)

    # Capture logger.exception call explicitly
    called = {"exc": 0}
    class _LoggerStub:
        def exception(self, *a, **k):
            called["exc"] += 1
    monkeypatch.setattr(gh, "logger", _LoggerStub(), raising=False)

    # Preconditions sanity
    assert getattr(gh, "config", None) is not None
    assert getattr(gh.config, "ADMIN_USER_IDS", None) == [999]

    upd = _Update(999)
    ctx = types.SimpleNamespace()

    await handler.notifications_sentry_test(upd, ctx)

    # Ensure an exception was logged via logger.exception
    assert called["exc"] >= 1

    # Ensure user got a confirmation answer at least once
    assert upd.callback_query.answered, "Expected query.answer to be called"
