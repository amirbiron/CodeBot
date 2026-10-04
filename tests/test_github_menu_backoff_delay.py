import asyncio
import time
import types
import pytest

# הטסטים כאן משנים את ``github_backoff_state`` במודול, ולכן בונים את ``GitHubMenuHandler``
# מאותו אובייקט מודול שהם משנים, ולא ממחלקה שיובאה בזמן האיסוף. טסט שמייבא את
# ``github_menu_handler`` מחדש ולא מחזיר את הקודם משאיר ב-``sys.modules`` מודול אחר, והשינוי
# נוחת אז במודול שהקוד שרץ לא קורא ממנו. כך היה עם ``tests/test_error_recovery_db_and_telegram.py``
# עד PR #3524.


@pytest.mark.asyncio
async def test_apply_rate_limit_delay_respects_backoff(monkeypatch):
    import github_menu_handler as mod

    h = mod.GitHubMenuHandler()
    user_id = 123

    # Seed last call now
    seeded = time.time()
    h.last_api_call[user_id] = seeded

    # Stub github_backoff_state.get().is_active() -> True
    class _Info:
        def is_active(self):
            return True
    class _State:
        def get(self):
            return _Info()
    # Patch services.github_backoff_state reference inside module
    monkeypatch.setattr(mod, "github_backoff_state", _State(), raising=False)

    # ההשהיה הבסיסית מאופסת כאן במפורש, כדי שכל ההמתנה תבוא מה-backoff. כשהיא רצה
    # בברירת המחדל של הייצור, היא ארוכה מה-backoff שנקבע כאן, והטסט עבר גם כשה-backoff
    # לא הופעל בכלל (נמדד במוטציה שמבטלת אותו).
    monkeypatch.setenv("GITHUB_API_BASE_DELAY", "0")
    # Reduce backoff delay to keep test fast, while still asserting >=1s
    monkeypatch.setenv("GITHUB_BACKOFF_DELAY", "1.0")
    await h.apply_rate_limit_delay(user_id)
    since_seed = time.time() - seeded

    # תחת backoff הקריאה חוזרת רק אחרי ש-GITHUB_BACKOFF_DELAY עבר מהקריאה הקודמת, כלומר מהרגע
    # שנזרע כאן, ולכן מודדים ממנו. מדידה מתחילת הקריאה מפספסת את הזמן שעבר מאז הזריעה, ובמכונה
    # איטית, או בעצירה של GC באמצע, היא יוצאת קצרה משנייה גם כשההמתנה נכונה.
    assert since_seed >= 1.0, f"הקריאה הייתה אמורה לחזור שנייה אחרי הקריאה הקודמת, וחזרה אחרי {since_seed:.3f} שנ'"


@pytest.mark.asyncio
async def test_apply_rate_limit_delay_waits_the_base_delay_between_two_calls(monkeypatch):
    """שתי קריאות צמודות של אותו משתמש: הראשונה עוברת מיד, והשנייה ממתינה את ההשהיה הבסיסית.

    ``tests/conftest.py`` מאפס את ``GITHUB_API_BASE_DELAY`` לכל הטסטים, ולכן הטסט הזה קובע ערך
    קטן משלו, כדי לעבור דרך ההמתנה האמיתית. הוא גם מנטרל את מצב ה-backoff הגלובלי, כדי שההמתנה
    תבוא רק מההשהיה הבסיסית.
    """
    import github_menu_handler as mod

    delay = 0.3
    monkeypatch.setattr(mod, "github_backoff_state", None, raising=False)
    monkeypatch.setenv("GITHUB_API_BASE_DELAY", str(delay))
    h = mod.GitHubMenuHandler()

    start = time.monotonic()
    await h.apply_rate_limit_delay(7)
    first = time.monotonic() - start
    await h.apply_rate_limit_delay(7)
    second = time.monotonic() - start - first

    # סף אחד בין "המתינה" ל"לא המתינה": קריאה שממתינה את ההשהיה עוברת אותו, וקריאה שלא
    # ממתינה נשארת רחוק מתחתיו גם במכונה עמוסה.
    waited = delay * 0.8
    assert first < waited, f"הקריאה הראשונה לא אמורה להמתין, והמתינה {first:.3f} שנ'"
    assert second >= waited, f"הקריאה השנייה הייתה אמורה להמתין כ-{delay} שנ', והמתינה {second:.3f}"
