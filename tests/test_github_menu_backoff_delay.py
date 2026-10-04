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

    # ההשהיה הבסיסית מאופסת כאן במפורש, כדי שכל ההמתנה תבוא מה-backoff. כשהיא רצה
    # בברירת המחדל של הייצור, היא ארוכה מה-backoff שנקבע כאן, והטסט עבר גם כשה-backoff
    # לא הופעל בכלל (נמדד במוטציה שמבטלת אותו).
    monkeypatch.setenv("GITHUB_API_BASE_DELAY", "0")
    # Reduce backoff delay to keep test fast, while still asserting >=1s
    monkeypatch.setenv("GITHUB_BACKOFF_DELAY", "1.0")
    start = time.time()
    await h.apply_rate_limit_delay(user_id)
    elapsed = time.time() - start

    # Under backoff, the wait is GITHUB_BACKOFF_DELAY minus the time since the seeded call
    assert elapsed >= 1.0  # at least some wait was applied


@pytest.mark.asyncio
async def test_apply_rate_limit_delay_waits_the_base_delay_between_two_calls(monkeypatch):
    """שתי קריאות צמודות של אותו משתמש: הראשונה עוברת מיד, והשנייה ממתינה את ההשהיה הבסיסית.

    ``tests/conftest.py`` מאפס את ``GITHUB_API_BASE_DELAY`` לכל הטסטים, ולכן זה הטסט שעובר
    דרך ההמתנה האמיתית. הוא קובע ערך קטן משלו, ומנטרל את מצב ה-backoff הגלובלי, כדי שההמתנה
    תבוא רק מההשהיה הבסיסית.
    """
    import github_menu_handler as mod

    delay = 0.3
    monkeypatch.setattr(mod, "github_backoff_state", None, raising=False)
    monkeypatch.setenv("GITHUB_API_BASE_DELAY", str(delay))
    h = GitHubMenuHandler()

    start = time.monotonic()
    await h.apply_rate_limit_delay(7)
    first = time.monotonic() - start
    await h.apply_rate_limit_delay(7)
    second = time.monotonic() - start - first

    assert first < delay / 2, f"הקריאה הראשונה לא אמורה להמתין, והמתינה {first:.3f} שנ'"
    assert second >= delay * 0.8, f"הקריאה השנייה הייתה אמורה להמתין כ-{delay} שנ', והמתינה {second:.3f}"
