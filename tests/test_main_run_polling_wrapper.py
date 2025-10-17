import importlib


def test_main_awaits_run_polling_coroutine(monkeypatch):
    # טען מחדש את המודול כדי להתחיל מסביבה נקייה
    import main as mod
    importlib.reload(mod)

    # דגל שיאושר רק אם הקורוטינה רצה בפועל (כלומר awaited)
    called = {"done": False}

    async def _coro():
        called["done"] = True
        return "ok"

    class _FakeApp:
        def run_polling(self, *a, **k):
            # מחזיר קורוטינה כדי לבדוק שהעטיפה ב-main.main ממתינה לה
            return _coro()

    class _FakeBot:
        def __init__(self):
            self.application = _FakeApp()

    # לבידוד: נעילה ותיקון ניקוי
    monkeypatch.setattr(mod, "manage_mongo_lock", lambda: True)
    monkeypatch.setattr(mod, "cleanup_mongo_lock", lambda: True)

    # בסיס DB מינימלי
    class _DBM:
        def __init__(self):
            self.db = object()
        def close_connection(self):
            return None

    monkeypatch.setattr(mod, "DatabaseManager", _DBM)
    monkeypatch.setattr(mod, "CodeKeeperBot", _FakeBot)

    # הפעלה — אמור להריץ asyncio.run על הקורוטינה שהוחזרה
    mod.main()

    assert called["done"] is True


def test_main_run_polling_sync_fallback(monkeypatch):
    # טען מחדש את המודול כדי להשתמש ב-_MiniApp הפנימי (fallback)
    import main as mod
    importlib.reload(mod)

    # בידוד סביבת נעילות/DB
    monkeypatch.setattr(mod, "manage_mongo_lock", lambda: True)
    monkeypatch.setattr(mod, "cleanup_mongo_lock", lambda: True)

    class _DBM:
        def __init__(self):
            self.db = object()
        def close_connection(self):
            return None

    monkeypatch.setattr(mod, "DatabaseManager", _DBM)

    # הכרחת מסלול fallback: כל ניסיון ל-Application.builder יזרוק חריגה
    class _AppNS:
        def builder(self):
            raise RuntimeError("no builder in test")

    monkeypatch.setattr(mod, "Application", _AppNS())

    # יצירת בוט אמיתי מהמימוש — אמורה ליצור _MiniApp פנימי עם run_polling סינכרוני
    bot = mod.CodeKeeperBot()

    import asyncio as _asyncio
    assert not _asyncio.iscoroutinefunction(bot.application.run_polling)
    assert bot.application.run_polling() is None

    # הפעלה — אמורה לעבור במסלול שבו התוצאה אינה awaitable
    mod.main()
