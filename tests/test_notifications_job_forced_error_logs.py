import types
import pytest
import logging
import sys


@pytest.mark.asyncio
async def test_notifications_job_forced_error_logs(monkeypatch, caplog):
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

    # Ensure env flag triggers the forced error branch at function start
    monkeypatch.setenv("SENTRY_TEST_NOTIFICATIONS_JOB", "1")

    # Minimal context; bot not needed for this path
    ctx = types.SimpleNamespace(application=types.SimpleNamespace(user_data={}), user_data={})

    caplog.set_level(logging.ERROR)

    # Should not raise; error is handled and logged
    await handler._notifications_job(ctx, user_id=777, force=True)

    # Validate full stacktrace logging via logger.exception
    assert any("notifications job error" in rec.getMessage() for rec in caplog.records)
