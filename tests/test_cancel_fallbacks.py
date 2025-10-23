import importlib
import types
import sys
import os
import asyncio

import pytest

from telegram.ext import ConversationHandler as PTBConversationHandler, CommandHandler


def _install_dummy_config(monkeypatch):
    cfg = types.SimpleNamespace(
        BOT_TOKEN="dummy",
        MONGODB_URL="",
        DATABASE_NAME="test",
        MONGODB_MAX_POOL_SIZE=50,
        MONGODB_MIN_POOL_SIZE=5,
        MONGODB_MAX_IDLE_TIME_MS=30000,
        MONGODB_WAIT_QUEUE_TIMEOUT_MS=5000,
        MONGODB_SERVER_SELECTION_TIMEOUT_MS=3000,
        MONGODB_SOCKET_TIMEOUT_MS=20000,
        MONGODB_CONNECT_TIMEOUT_MS=10000,
        MONGODB_RETRY_WRITES=True,
        MONGODB_RETRY_READS=True,
        MONGODB_APPNAME=None,
        METRICS_COLLECTION="service_metrics",
        RATE_LIMIT_PER_MINUTE=30,
        RATE_LIMIT_SHADOW_MODE=False,
        MAINTENANCE_MODE=False,
    )
    monkeypatch.setitem(sys.modules, "config", types.SimpleNamespace(config=cfg))


def _install_observability_stub(monkeypatch):
    obs = types.ModuleType("observability")
    obs.setup_structlog_logging = lambda *a, **k: None
    obs.init_sentry = lambda *a, **k: None
    obs.bind_request_id = lambda *a, **k: None
    obs.generate_request_id = lambda: "req"
    obs.emit_event = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "observability", obs)


def _install_metrics_stub(monkeypatch):
    m = types.ModuleType("metrics")
    m.telegram_updates_total = None
    m.track_file_saved = None
    m.track_search_performed = None
    m.track_performance = None
    m.errors_total = None
    monkeypatch.setitem(sys.modules, "metrics", m)


def _install_drive_menu_stub(monkeypatch):
    # Provide handlers.drive.menu.GoogleDriveMenuHandler without overriding the real 'handlers' package
    import handlers as real_handlers  # noqa: F401
    drive_pkg = types.ModuleType("handlers.drive")
    menu_mod = types.ModuleType("handlers.drive.menu")

    class GoogleDriveMenuHandler:
        def handle_callback(self, *a, **k):
            return None
        async def handle_text(self, *a, **k):
            return None

    menu_mod.GoogleDriveMenuHandler = GoogleDriveMenuHandler

    monkeypatch.setitem(sys.modules, "handlers.drive", drive_pkg)
    monkeypatch.setitem(sys.modules, "handlers.drive.menu", menu_mod)


def _install_requests_stub(monkeypatch):
    req = types.ModuleType("requests")
    req.Session = object
    monkeypatch.setitem(sys.modules, "requests", req)


def _install_github_menu_handler_stubs(monkeypatch):
    # Stub pieces used by github_menu_handler to avoid heavy deps
    gm = types.ModuleType("github_menu_handler")
    class GitHubMenuHandler:
        def github_menu_command(self, *a, **k):
            return None
        def handle_menu_callback(self, *a, **k):
            return None
        async def handle_file_upload(self, *a, **k):
            return None
        async def handle_text_input(self, *a, **k):
            return None
        async def handle_inline_query(self, *a, **k):
            return None
    gm.GitHubMenuHandler = GitHubMenuHandler
    monkeypatch.setitem(sys.modules, "github_menu_handler", gm)


class _CaptureApp:
    def __init__(self):
        self.handlers = []
        self.bot_data = {}

    def add_handler(self, *args, **kwargs):
        self.handlers.append((args, kwargs))


class _ConvStub:
    END = object()
    def __init__(self, *args, **kwargs):
        self.entry_points = kwargs.get("entry_points") or (args[0] if args else [])
        self.states = kwargs.get("states") or (args[1] if len(args) > 1 else {})
        self.fallbacks = kwargs.get("fallbacks") or (args[2] if len(args) > 2 else [])


@pytest.mark.asyncio
async def test_reminders_cancel_fallback_returns_end(monkeypatch):
    monkeypatch.setenv("DISABLE_DB", "1")
    _install_dummy_config(monkeypatch)

    app = _CaptureApp()
    from database import db as _dbm
    app.bot_data["db_manager"] = _dbm

    mod = importlib.import_module("reminders.handlers")
    monkeypatch.setattr(mod, "ConversationHandler", _ConvStub, raising=True)

    mod.setup_reminder_handlers(app)

    conv = None
    for (args, _kwargs) in app.handlers:
        h = args[0] if args else None
        if isinstance(h, _ConvStub):
            conv = h
    assert isinstance(conv, _ConvStub)

    assert conv.fallbacks, "Expected at least one fallback"
    fallback_handler = conv.fallbacks[0]
    assert isinstance(fallback_handler, CommandHandler)

    expected_end = mod.ConversationHandler.END
    cb = fallback_handler.callback
    result = await cb(types.SimpleNamespace(), types.SimpleNamespace())
    assert result is expected_end


@pytest.mark.asyncio
async def test_main_upload_cancel_fallback_returns_end(monkeypatch):
    monkeypatch.setenv("DISABLE_DB", "1")
    _install_dummy_config(monkeypatch)
    _install_observability_stub(monkeypatch)
    _install_metrics_stub(monkeypatch)
    _install_drive_menu_stub(monkeypatch)
    _install_requests_stub(monkeypatch)
    _install_github_menu_handler_stubs(monkeypatch)

    class _JobQ:
        def run_once(self, *a, **k):
            return None

    class _App:
        def __init__(self):
            self.handlers = []
            self.bot_data = {}
            self.job_queue = _JobQ()
        def add_handler(self, *args, **kwargs):
            self.handlers.append((args, kwargs))

    class _Builder:
        def token(self, *_a, **_k):
            return self
        def defaults(self, *_a, **_k):
            return self
        def persistence(self, *_a, **_k):
            return self
        def post_init(self, *_a, **_k):
            return self
        def build(self):
            return _App()

    class _ApplicationStub:
        @staticmethod
        def builder():
            return _Builder()

    main = importlib.import_module("main")
    monkeypatch.setattr(main, "Application", _ApplicationStub, raising=True)
    monkeypatch.setattr(main, "ConversationHandler", _ConvStub, raising=True)

    bot = main.CodeKeeperBot()

    conv = None
    for (args, _kwargs) in bot.application.handlers:  # type: ignore[attr-defined]
        h = args[0] if args else None
        if isinstance(h, _ConvStub):
            conv = h
    assert isinstance(conv, _ConvStub)

    assert conv.fallbacks, "Expected at least one fallback in upload conv"
    fallback_handler = conv.fallbacks[0]
    assert isinstance(fallback_handler, CommandHandler)

    expected_end = main.ConversationHandler.END
    cb = fallback_handler.callback
    result = await cb(types.SimpleNamespace(), types.SimpleNamespace())
    assert result is expected_end
