import sys
import time
import types
from datetime import datetime, timedelta

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


_stub_telegram_if_missing()


@pytest.mark.asyncio
async def test_callback_query_guard_should_block_async_release():
    from utils import CallbackQueryGuard

    class _Update:
        def __init__(self, uid: int, data: str = "x"):
            self.effective_user = types.SimpleNamespace(id=uid)
            self.effective_chat = types.SimpleNamespace(id=1)
            self.callback_query = types.SimpleNamespace(message=types.SimpleNamespace(message_id=1), data=data)

    class _Ctx:
        def __init__(self):
            self.user_data = {}

    u = _Update(42)
    c = _Ctx()

    # first call should not block
    assert await CallbackQueryGuard.should_block_async(u, c, window_seconds=0.05) is False
    # immediate second call should block
    assert await CallbackQueryGuard.should_block_async(u, c, window_seconds=0.05) is True
    # after window, should release
    await __import__('asyncio').sleep(0.06)
    assert await CallbackQueryGuard.should_block_async(u, c, window_seconds=0.05) is False


@pytest.mark.asyncio
async def test_async_utils_run_with_timeout():
    from utils import AsyncUtils

    async def _slow():
        await __import__('asyncio').sleep(0.05)
        return "slow"

    async def _fast():
        return "fast"

    # expect timeout returns None
    assert await AsyncUtils.run_with_timeout(_slow(), timeout=0.01) is None
    # fast returns value
    assert await AsyncUtils.run_with_timeout(_fast(), timeout=0.5) == "fast"


def test_cache_utils_set_get_and_expiry():
    from utils import CacheUtils

    CacheUtils.clear()
    CacheUtils.set("k", "v", ttl=1)
    assert CacheUtils.get("k") == "v"
    time.sleep(1.1)
    assert CacheUtils.get("k", default="d") == "d"


def test_config_utils_load_save_json(tmp_path):
    from utils import ConfigUtils

    p = tmp_path / "cfg" / "x.json"
    # load missing -> default
    assert ConfigUtils.load_json_config(str(p), default={"a": 1}) == {"a": 1}
    # save and reload
    ok = ConfigUtils.save_json_config(str(p), {"b": 2})
    assert ok is True
    assert ConfigUtils.load_json_config(str(p)) == {"b": 2}


def test_time_utils_and_validation_utils():
    from utils import TimeUtils, ValidationUtils

    # relative format (minutes)
    out = TimeUtils.format_relative_time(datetime.now() - timedelta(minutes=2))
    assert "לפני" in out

    # parse_date_string special words
    assert TimeUtils.parse_date_string("היום") is not None
    assert TimeUtils.parse_date_string("אתמול") is not None

    # filename validation
    assert ValidationUtils.is_valid_filename("ok.txt") is True
    assert ValidationUtils.is_valid_filename("in:valid?.txt") is False
    assert ValidationUtils.is_valid_filename("CON.txt") is False  # reserved


def test_sensitive_data_filter_more(capfd):
    from utils import SensitiveDataFilter
    import logging

    logger = logging.getLogger("redact-more")
    logger.handlers = []
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(SensitiveDataFilter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    logger.info("token github_pat_1234567890_ABCDEFGHIJ and Bearer ABCDEFGHIJKL012345")
    out, err = capfd.readouterr()
    assert "github_pat_***REDACTED***" in out
    assert "Bearer ***REDACTED***" in out


def test_get_language_emoji():
    from utils import get_language_emoji

    assert get_language_emoji("python") == "🐍"
    assert get_language_emoji("unknown-lang") == "📄"

