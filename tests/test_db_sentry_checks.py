import os
import types
import sys
import pytest

import bot_handlers as bh


@pytest.mark.asyncio
async def test_check_db_connection_returns_false_when_uri_missing(monkeypatch):
    monkeypatch.delenv('MONGODB_URL', raising=False)
    monkeypatch.delenv('REPORTER_MONGODB_URL', raising=False)
    monkeypatch.delenv('REPORTER_MONGODB_URI', raising=False)
    assert await bh.check_db_connection() is False


@pytest.mark.asyncio
async def test_check_db_connection_motor_success(monkeypatch):
    # Provide fake motor that succeeds
    os.environ['MONGODB_URL'] = 'mongodb://example'

    motor_pkg = types.ModuleType('motor')
    motor_pkg.__path__ = []  # mark as package
    motor_asyncio_mod = types.ModuleType('motor.motor_asyncio')

    class _Admin:
        async def command(self, cmd):
            return {"ok": 1}

    class _Client:
        def __init__(self, *a, **k):
            self.admin = _Admin()
        def close(self):
            pass

    motor_asyncio_mod.AsyncIOMotorClient = _Client
    monkeypatch.setitem(sys.modules, 'motor', motor_pkg)
    monkeypatch.setitem(sys.modules, 'motor.motor_asyncio', motor_asyncio_mod)
    # Ensure no pymongo fallback is hit accidentally
    monkeypatch.setitem(sys.modules, 'pymongo', types.ModuleType('pymongo'))

    assert await bh.check_db_connection() is True


@pytest.mark.asyncio
async def test_check_db_connection_motor_fails_pymongo_succeeds(monkeypatch):
    os.environ['MONGODB_URL'] = 'mongodb://example'

    # Motor that fails on client init
    motor_pkg = types.ModuleType('motor')
    motor_pkg.__path__ = []
    motor_asyncio_mod = types.ModuleType('motor.motor_asyncio')

    class _FailClient:
        def __init__(self, *a, **k):
            raise RuntimeError('motor boom')

    motor_asyncio_mod.AsyncIOMotorClient = _FailClient
    monkeypatch.setitem(sys.modules, 'motor', motor_pkg)
    monkeypatch.setitem(sys.modules, 'motor.motor_asyncio', motor_asyncio_mod)

    # PyMongo that succeeds
    pym_mod = types.ModuleType('pymongo')

    class _Admin:
        def command(self, cmd):
            return {"ok": 1}

    class MongoClient:
        def __init__(self, *a, **k):
            self.admin = _Admin()
        def close(self):
            pass

    pym_mod.MongoClient = MongoClient
    monkeypatch.setitem(sys.modules, 'pymongo', pym_mod)

    assert await bh.check_db_connection() is True


@pytest.mark.asyncio
async def test_check_db_connection_both_engines_fail(monkeypatch):
    os.environ['MONGODB_URL'] = 'mongodb://example'

    # Motor fails
    motor_pkg = types.ModuleType('motor')
    motor_pkg.__path__ = []
    motor_asyncio_mod = types.ModuleType('motor.motor_asyncio')
    class _FailClient:
        def __init__(self, *a, **k):
            raise RuntimeError('motor boom')
    motor_asyncio_mod.AsyncIOMotorClient = _FailClient
    monkeypatch.setitem(sys.modules, 'motor', motor_pkg)
    monkeypatch.setitem(sys.modules, 'motor.motor_asyncio', motor_asyncio_mod)

    # PyMongo fails
    pym_mod = types.ModuleType('pymongo')
    class MongoClient:
        def __init__(self, *a, **k):
            class _ADM:
                def command(self, cmd):
                    raise RuntimeError('pymongo boom')
            self.admin = _ADM()
        def close(self):
            pass
    pym_mod.MongoClient = MongoClient
    monkeypatch.setitem(sys.modules, 'pymongo', pym_mod)

    assert await bh.check_db_connection() is False


class _Msg:
    def __init__(self):
        self.texts = []
    async def reply_text(self, text, *a, **k):
        self.texts.append(text)


class _Update:
    def __init__(self):
        self.message = _Msg()
        self.effective_user = types.SimpleNamespace(id=1)


class _Context:
    def __init__(self):
        self.user_data = {}
        self.application = types.SimpleNamespace(job_queue=types.SimpleNamespace(run_once=lambda *a, **k: None))


class _App:
    def __init__(self):
        self.handlers = []
    def add_handler(self, *args, **kwargs):
        self.handlers.append((args, kwargs))


@pytest.mark.asyncio
async def test_sen_command_with_dashboard_url(monkeypatch):
    app = _App()
    adv = bh.AdvancedBotHandlers(app)
    upd = _Update()
    ctx = _Context()
    os.environ['ADMIN_USER_IDS'] = str(upd.effective_user.id)
    os.environ['SENTRY_DASHBOARD_URL'] = 'https://sentry.io/organizations/acme/issues/'
    try:
        await adv.sentry_command(upd, ctx)
        out = "\n".join(upd.message.texts)
        assert 'Sentry:' in out and 'acme' in out
    finally:
        monkeypatch.delenv('SENTRY_DASHBOARD_URL', raising=False)


@pytest.mark.asyncio
async def test_sen_command_derives_from_dsn_and_org(monkeypatch):
    app = _App()
    adv = bh.AdvancedBotHandlers(app)
    upd = _Update()
    ctx = _Context()
    os.environ['ADMIN_USER_IDS'] = str(upd.effective_user.id)
    # ודא שאין קישור דאשבורד מפורש שמאפיל על הגזירה מ-DSN/ORG
    monkeypatch.delenv('SENTRY_DASHBOARD_URL', raising=False)
    monkeypatch.delenv('SENTRY_PROJECT_URL', raising=False)
    os.environ['SENTRY_DSN'] = 'https://abc123@o123.ingest.sentry.io/1'
    os.environ['SENTRY_ORG'] = 'myorg'
    try:
        await adv.sentry_command(upd, ctx)
        out = "\n".join(upd.message.texts)
        assert 'Sentry:' in out and 'organizations/myorg' in out
    finally:
        monkeypatch.delenv('SENTRY_DSN', raising=False)
        monkeypatch.delenv('SENTRY_ORG', raising=False)


@pytest.mark.asyncio
async def test_sen_command_not_configured(monkeypatch):
    app = _App()
    adv = bh.AdvancedBotHandlers(app)
    upd = _Update()
    ctx = _Context()
    os.environ['ADMIN_USER_IDS'] = str(upd.effective_user.id)
    monkeypatch.delenv('SENTRY_DASHBOARD_URL', raising=False)
    monkeypatch.delenv('SENTRY_DSN', raising=False)
    await adv.sentry_command(upd, ctx)
    out = "\n".join(upd.message.texts)
    assert 'Sentry לא מוגדר' in out


@pytest.mark.asyncio
async def test_sen_command_requires_admin(monkeypatch):
    app = _App()
    adv = bh.AdvancedBotHandlers(app)
    upd = _Update()
    ctx = _Context()
    # Ensure non-admin
    monkeypatch.delenv('ADMIN_USER_IDS', raising=False)
    upd.message.texts.clear()
    await adv.sentry_command(upd, ctx)
    out = "\n".join(upd.message.texts)
    assert 'פקודה זמינה למנהלים בלבד' in out
