import asyncio
import time
import types
import pytest

from github_menu_handler import GitHubMenuHandler


@pytest.mark.asyncio
async def test_apply_rate_limit_delay_respects_backoff(monkeypatch):
    h = GitHubMenuHandler()
    user_id = 123

    # Seed last call now
    h.last_api_call[user_id] = time.time()

    # Stub github_backoff_state.get().is_active() -> True
    class _Info:
        def is_active(self):
            return True
    class _State:
        def get(self):
            return _Info()
    # Patch services.github_backoff_state reference inside module
    import github_menu_handler as mod
    monkeypatch.setattr(mod, "github_backoff_state", _State(), raising=False)

    start = time.time()
    await h.apply_rate_limit_delay(user_id)
    elapsed = time.time() - start

    # Under backoff, delay should be ~5s minus already elapsed since last call; allow slack
    assert elapsed >= 1.0  # at least some wait was applied
