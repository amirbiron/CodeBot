import types
import pytest
import sys


@pytest.mark.asyncio
async def test_notifications_job_returns_early_when_disabled(monkeypatch):
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

    # Stub config.config to avoid pydantic dependency
    cfg_mod = types.ModuleType("config")
    cfg_mod.config = types.SimpleNamespace(ADMIN_USER_IDS=[])
    sys.modules["config"] = cfg_mod

    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    uid = 42

    # Provide token and selected repo to reach the settings guard
    session = handler.get_user_session(uid)
    session["selected_repo"] = "owner/name"
    session["github_token"] = "t0ken"

    # No notifications settings present (disabled by default)
    app = types.SimpleNamespace(user_data={})
    ctx = types.SimpleNamespace(application=app, user_data={})

    # Ensure Github client is NOT called due to early return
    def _should_not_be_called(*a, **k):
        raise AssertionError("Github should not be instantiated when notifications are disabled")

    monkeypatch.setattr(gh, "Github", _should_not_be_called)

    # force=False by default -> should return early without touching Github
    await handler._notifications_job(ctx, user_id=uid, force=False)

    # If no assertion raised, early return succeeded
    assert True
