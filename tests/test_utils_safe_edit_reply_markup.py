import sys
import types
import pytest


def _stub_telegram_if_missing():
    try:
        import telegram  # type: ignore
        import telegram.error  # type: ignore
        import telegram.constants  # type: ignore
        import telegram.ext  # type: ignore
    except Exception:
        telegram = types.ModuleType('telegram')
        sys.modules['telegram'] = telegram

        error_mod = types.ModuleType('telegram.error')
        class _BadRequest(Exception):
            pass
        error_mod.BadRequest = _BadRequest
        sys.modules['telegram.error'] = error_mod

        consts = types.ModuleType('telegram.constants')
        consts.ChatAction = None
        consts.ParseMode = None
        sys.modules['telegram.constants'] = consts

        ext = types.ModuleType('telegram.ext')
        class _ContextTypes:
            DEFAULT_TYPE = object
        ext.ContextTypes = _ContextTypes
        sys.modules['telegram.ext'] = ext


# התקן סטאבים אם הספרייה לא קיימת לפני ייבוא utils
_stub_telegram_if_missing()


@pytest.mark.asyncio
async def test_safe_edit_message_reply_markup_ignores_not_modified(monkeypatch):
    import utils as um
    from utils import TelegramUtils

    class FakeBadRequest(Exception):
        pass

    # ספק אובייקט telegram מינימלי עם BadRequest עבור utils
    um.telegram = types.SimpleNamespace(error=types.SimpleNamespace(BadRequest=FakeBadRequest))

    class Q:
        async def edit_message_reply_markup(self, *args, **kwargs):
            raise FakeBadRequest("Message is not modified")

    # לא אמור לזרוק חריגה
    await TelegramUtils.safe_edit_message_reply_markup(Q(), reply_markup=None)


@pytest.mark.asyncio
async def test_safe_edit_message_reply_markup_raises_other_badrequest(monkeypatch):
    import utils as um
    from utils import TelegramUtils

    class FakeBadRequest(Exception):
        pass

    um.telegram = types.SimpleNamespace(error=types.SimpleNamespace(BadRequest=FakeBadRequest))

    class Q:
        async def edit_message_reply_markup(self, *args, **kwargs):
            raise FakeBadRequest("some other error")

    with pytest.raises(FakeBadRequest):
        await TelegramUtils.safe_edit_message_reply_markup(Q(), reply_markup=None)

