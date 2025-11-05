from __future__ import annotations

import sys
import types
import pytest


def _install_telegram_stubs():
    """Install minimal telegram stubs to allow importing main without heavy deps."""
    if 'telegram' in sys.modules:
        return
    telegram = types.SimpleNamespace()
    # Submodules
    telegram.constants = types.SimpleNamespace(ParseMode=types.SimpleNamespace())
    telegram.ext = types.SimpleNamespace(
        Application=object,
        CommandHandler=object,
        ContextTypes=types.SimpleNamespace(DEFAULT_TYPE=object),
        MessageHandler=object,
        filters=types.SimpleNamespace(),
        Defaults=object,
        ConversationHandler=object,
        CallbackQueryHandler=object,
        PicklePersistence=object,
        InlineQueryHandler=object,
        ApplicationHandlerStop=Exception,
        TypeHandler=object,
    )
    telegram.Update = object
    telegram.ReplyKeyboardMarkup = object
    telegram.InlineKeyboardButton = object
    telegram.InlineKeyboardMarkup = object
    telegram.BotCommand = object
    telegram.BotCommandScopeChat = object
    sys.modules['telegram'] = telegram
    sys.modules['telegram.constants'] = telegram.constants
    sys.modules['telegram.ext'] = telegram.ext
    # Also stub lightweight config module to avoid pydantic dependency during import
    if 'config' not in sys.modules:
        mod = types.ModuleType('config')
        mod.config = types.SimpleNamespace(
            SENTRY_DSN="",
            ENVIRONMENT="test",
            RECYCLE_TTL_DAYS=7,
            MAX_CODE_SIZE=100_000,
        )
        sys.modules['config'] = mod
    # Stub github_menu_handler to avoid importing PyGithub submodules
    if 'github_menu_handler' not in sys.modules:
        gm = types.ModuleType('github_menu_handler')
        class GitHubMenuHandler:  # minimal placeholder used by main
            pass
        gm.GitHubMenuHandler = GitHubMenuHandler
        sys.modules['github_menu_handler'] = gm


def test_get_admin_ids_parsing(monkeypatch):
    _install_telegram_stubs()
    # Ensure our tests/ stubs are importable before workspace root
    monkeypatch.syspath_prepend('tests')
    import main

    monkeypatch.setenv("ADMIN_USER_IDS", "123, 456 , x , 789")
    assert main.get_admin_ids() == [123, 456, 789]


def test_register_catch_all_callback_fallback(monkeypatch):
    _install_telegram_stubs()
    monkeypatch.syspath_prepend('tests')
    import main

    called = {"without_group": False}

    class App:
        def add_handler(self, handler, group=None):
            # Simulate an environment that raises on 'group' param
            if group is not None:
                raise TypeError("group not supported")
            called["without_group"] = True

    def dummy_callback(*a, **k):
        return None

    main._register_catch_all_callback(App(), dummy_callback)
    assert called["without_group"] is True


@pytest.mark.asyncio
async def test_log_user_activity_records(monkeypatch):
    _install_telegram_stubs()
    monkeypatch.syspath_prepend('tests')
    import main

    # Force sampling to always pass
    monkeypatch.setattr("random.random", lambda: 0.0, raising=False)

    # Capture user_stats.log_user calls
    calls = []

    def fake_log_user(user_id, username, weight=None):
        calls.append((user_id, username, weight))

    monkeypatch.setattr(main.user_stats, "log_user", fake_log_user, raising=False)

    class _User:
        def __init__(self):
            self.id = 42
            self.username = "tester"

    class _Update:
        def __init__(self):
            self.effective_user = _User()

    class _Context:
        pass

    await main.log_user_activity(_Update(), _Context())
    # At least one call with our user; weight may be provided (4) or omitted depending on signature
    assert any(c[0] == 42 and c[1] == "tester" for c in calls)
