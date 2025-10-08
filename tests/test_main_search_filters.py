import types
import pytest


@pytest.mark.asyncio
async def test_search_command_with_language_and_tag_filters(monkeypatch):
    # טוען את main ומפעיל search_command עם קלט בסיסי, מוודא שאין TypeError מ-None/איחוד
    sys_modules_backup = dict(__import__('sys').modules)
    try:
        # Stub database access used by search (אם בכלל)
        db_mod = __import__('database', fromlist=['db'])
        class _DB:
            def __init__(self):
                self.db = None
        monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)

        # טען main
        sys_modules_backup.pop('main', None)
        mod = __import__('main')
        # מצא את מחלקת הבוט הראשית (AdvancedBotHandlers עדיין בשימוש)
        BotCls = getattr(mod, 'AdvancedBotHandlers')
        app_stub = types.SimpleNamespace(add_handler=lambda *a, **k: None)
        bot = BotCls(app_stub)

        # Stubs ל-Update/Context
        class _Msg:
            async def reply_text(self, *a, **k):
                return None
        class _User: id = 1; username = 'u'
        class _Upd:
            effective_user = _User()
            message = _Msg()
        class _Ctx:
            args = ["python", "#utils", "api"]

        # הפעלה — עובר בלי TypeError
        await bot.search_command(_Upd(), _Ctx())
    finally:
        __import__('sys').modules.update(sys_modules_backup)

