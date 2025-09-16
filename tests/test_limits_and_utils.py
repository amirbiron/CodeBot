import os
import re
import io
import sys
import types
import logging

import pytest

# Note: We avoid importing heavy modules (like main/database) to keep tests fast and isolated.


def _stub_telegram_if_missing():
    """Provide minimal stubs for telegram modules if not installed."""
    try:
        import telegram  # type: ignore
        import telegram.constants  # type: ignore
        import telegram.ext  # type: ignore
    except Exception:
        telegram = types.ModuleType('telegram')
        telegram.Message = type('Message', (), {})
        telegram.Update = type('Update', (), {})
        telegram.User = type('User', (), {})
        sys.modules['telegram'] = telegram

        # telegram.error submodule with BadRequest
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


# Install stubs upfront if needed
_stub_telegram_if_missing()


def read_file_text(path: str) -> str:
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def test_upload_limit_threshold_in_source():
    """Ensure the 20MB guard exists in main.py and user message mentions 20MB."""
    src = read_file_text(os.path.join(os.path.dirname(__file__), '..', 'main.py'))
    assert 'if document.file_size > 20 * 1024 * 1024' in src
    assert '20MB' in src


def test_textutils_format_file_size():
    from utils import TextUtils

    assert TextUtils.format_file_size(0) == "0 B"
    assert TextUtils.format_file_size(1) == "1 B"
    assert TextUtils.format_file_size(1023) == "1023 B"
    assert TextUtils.format_file_size(1024) == "1.0 KB"
    assert TextUtils.format_file_size(1024 * 1024) == "1.0 MB"
    assert TextUtils.format_file_size(5 * 1024 * 1024) == "5.0 MB"
    assert TextUtils.format_file_size(3 * 1024 * 1024 * 1024) == "3.0 GB"


def test_textutils_clean_filename():
    from utils import TextUtils

    assert TextUtils.clean_filename("a.txt") == "a.txt"
    assert TextUtils.clean_filename("in valid:name?.txt") == "in_valid_name_.txt"
    assert TextUtils.clean_filename(" spaced   name .log") == "spaced_name_.log"
    # Ensure trimming of leading/trailing dots/underscores
    assert TextUtils.clean_filename(".__my..file__.") == "my.file"


def test_textutils_escape_markdown_v2():
    from utils import TextUtils

    raw = "_hello[world](url)!"
    escaped = TextUtils.escape_markdown(raw, version=2)
    # All special characters should be escaped with backslashes
    assert escaped == "\\_hello\\[world\\]\\(url\\)\\!"


def test_callback_query_guard_should_block_and_release(monkeypatch):
    from utils import CallbackQueryGuard

    class _Update:
        def __init__(self, uid: int, data: str = "x"):
            self.effective_user = types.SimpleNamespace(id=uid)
            self.effective_chat = types.SimpleNamespace(id=1)
            self.callback_query = types.SimpleNamespace(message=types.SimpleNamespace(message_id=1), data=data)

    class _Ctx:
        def __init__(self):
            self.user_data = {}

    u = _Update(1)
    c = _Ctx()

    # First press should not block
    assert CallbackQueryGuard.should_block(u, c) is False
    # Immediate second press should block
    assert CallbackQueryGuard.should_block(u, c) is True


def test_safe_edit_message_text_ignores_not_modified(monkeypatch):
    import types as _t
    from utils import TelegramUtils
    import telegram.error as tgerr

    class _Q:
        def __init__(self):
            self.called = 0
        async def edit_message_text(self, *a, **k):
            self.called += 1
            raise tgerr.BadRequest("Message is not modified")

    q = _Q()

    # Should not raise
    import asyncio
    asyncio.run(TelegramUtils.safe_edit_message_text(q, "hi"))
    assert q.called == 1


def test_sensitive_data_filter_redacts_tokens(capfd):
    from utils import SensitiveDataFilter

    logger = logging.getLogger("redact-test")
    logger.handlers = []
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(SensitiveDataFilter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    token = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"
    logger.info("token=%s", token)
    out, err = capfd.readouterr()
    assert "ghp_***REDACTED***" in out


def test_detect_language_from_filename():
    from utils import detect_language_from_filename

    assert detect_language_from_filename("script.py") == "python"
    assert detect_language_from_filename("app.tsx") == "typescript"
    assert detect_language_from_filename("index.html") == "html"
    assert detect_language_from_filename("styles.css") == "css"
    assert detect_language_from_filename("Dockerfile") == "dockerfile"
    assert detect_language_from_filename("unknown.ext") == "text"