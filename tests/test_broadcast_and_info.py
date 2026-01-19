import types
import asyncio
import pytest


@pytest.mark.asyncio
async def test_broadcast_counts_and_summary(monkeypatch):
    # Import module under test
    import bot_handlers as bh

    # Ensure admin
    monkeypatch.setenv("ADMIN_USER_IDS", "999")

    removed_updates = {}
    class _Facade:
        def list_active_user_ids(self):
            return [111, 222, 333, 444]

        def mark_users_blocked(self, user_ids):
            removed_updates["ids"] = list(user_ids or [])
            return len(removed_updates["ids"])

    facade = _Facade()
    monkeypatch.setattr(bh, "_get_files_facade_or_none", lambda: facade)

    # Stub reporter to avoid external IO
    monkeypatch.setattr(bh.reporter, "report_activity", lambda *a, **k: None, raising=False)

    # Context/bot stubs
    state = {"222_retry": True}

    async def send_message(chat_id, text, parse_mode=None):
        # Import exceptions from the loaded module namespace
        err = bh.telegram.error
        if chat_id == 111:
            return None
        if chat_id == 222:
            if state["222_retry"]:
                state["222_retry"] = False
                raise err.RetryAfter(0.01)
            return None
        if chat_id == 333:
            raise err.Forbidden("blocked")
        if chat_id == 444:
            raise err.BadRequest("Chat not found")
        return None

    class DummyMessage:
        def __init__(self):
            self.calls = []
        async def reply_text(self, text, **kwargs):
            self.calls.append((text, kwargs))
            return None

    class DummyUpdate:
        def __init__(self):
            self.message = DummyMessage()
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=999)

    class DummyContext:
        def __init__(self):
            self.user_data = {}
            self.bot = types.SimpleNamespace(send_message=send_message)
            self.args = ["hello everyone"]

    # Patch RetryAfter in module to simple exception with attribute
    class _RetryAfter(Exception):
        def __init__(self, retry_after):
            super().__init__("retry")
            self.retry_after = retry_after
    monkeypatch.setattr(bh.telegram.error, "RetryAfter", _RetryAfter, raising=False)

    # Init handlers with a no-op application
    class _App:
        def __init__(self):
            self.handlers = []
        def add_handler(self, h, group=None):
            self.handlers.append((h, group))

    app = _App()
    adv = bh.AdvancedBotHandlers(app)

    u = DummyUpdate()
    c = DummyContext()
    await adv.broadcast_command(u, c)

    # Assert summary
    summary, kwargs = u.message.calls[-1]
    assert "נמענים: 4" in summary
    assert "הצלחות: 2" in summary
    assert "כשלים: 2" in summary
    assert "סומנו כחסומים/לא זמינים" in summary


@pytest.mark.asyncio
async def test_broadcast_db_failure_shows_error(monkeypatch):
    import bot_handlers as bh

    monkeypatch.setenv("ADMIN_USER_IDS", "999")
    monkeypatch.setattr(bh.reporter, "report_activity", lambda *a, **k: None, raising=False)

    # Force no facade (simulate DB connectivity issue / missing wiring)
    monkeypatch.setattr(bh, "_get_files_facade_or_none", lambda: None, raising=True)

    class DummyMessage:
        def __init__(self):
            self.calls = []
        async def reply_text(self, text, **kwargs):
            self.calls.append((text, kwargs))
            return None

    class DummyUpdate:
        def __init__(self):
            self.message = DummyMessage()
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=999)

    class DummyContext:
        def __init__(self):
            self.args = ["hello"]
            self.bot = types.SimpleNamespace(send_message=lambda **_: None)

    adv = bh.AdvancedBotHandlers(type("_A", (), {"add_handler": lambda *_: None})())
    u = DummyUpdate()
    c = DummyContext()
    await adv.broadcast_command(u, c)

    text, _kw = u.message.calls[-1]
    assert "לא ניתן לטעון רשימת משתמשים" in text or "שגיאה בטעינת רשימת נמענים" in text


@pytest.mark.asyncio
async def test_recent_uses_html_and_escapes(monkeypatch):
    import bot_handlers as bh

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    def _get_user_files(user_id, limit=50):
        return [{
            'file_name': 'hello`world.py',
            'programming_language': 'py<th>',
            'updated_at': now
        }]

    monkeypatch.setattr(
        bh,
        "_get_files_facade_or_none",
        lambda: types.SimpleNamespace(get_user_files=_get_user_files),
        raising=True,
    )
    monkeypatch.setattr(bh.reporter, "report_activity", lambda *a, **k: None, raising=False)

    class Msg:
        def __init__(self):
            self.kw = None
            self.text = None
        async def reply_text(self, text, **kwargs):
            self.text = text
            self.kw = kwargs

    class Upd:
        def __init__(self):
            self.message = Msg()
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=1)

    class Ctx:
        def __init__(self):
            self.args = []

    adv = bh.AdvancedBotHandlers(type("_A", (), {"add_handler": lambda *_: None})())
    u = Upd()
    c = Ctx()
    await adv.recent_command(u, c)

    assert u.message.kw.get('parse_mode') == 'HTML'
    assert '<code>hello`world.py</code>' in u.message.text
    assert 'py&lt;th&gt;' in u.message.text


@pytest.mark.asyncio
async def test_info_uses_html(monkeypatch):
    import bot_handlers as bh

    monkeypatch.setattr(bh.reporter, "report_activity", lambda *a, **k: None, raising=False)

    def _get_latest_version(user_id, file_name):
        from datetime import datetime
        return {
            'file_name': file_name,
            'programming_language': 'python',
            'code': 'print(1)',
            'updated_at': datetime.now()
        }

    monkeypatch.setattr(
        bh,
        "_get_files_facade_or_none",
        lambda: types.SimpleNamespace(get_latest_version=_get_latest_version),
        raising=True,
    )

    class Msg:
        def __init__(self):
            self.kw = None
            self.text = None
        async def reply_text(self, text, **kwargs):
            self.text = text
            self.kw = kwargs

    class Upd:
        def __init__(self):
            self.message = Msg()
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=1)

    class Ctx:
        def __init__(self):
            self.args = ["sample.py"]

    adv = bh.AdvancedBotHandlers(type("_A", (), {"add_handler": lambda *_: None})())
    u = Upd()
    c = Ctx()
    await adv.info_command(u, c)

    assert u.message.kw.get('parse_mode') == 'HTML'
    assert '<code>sample.py</code>' in u.message.text


def test_cache_manager_disabled_without_redis(monkeypatch):
    import cache_manager as cm
    # Simulate redis package missing
    monkeypatch.setenv('REDIS_URL', '')
    monkeypatch.setattr(cm, 'redis', None, raising=False)

    mgr = cm.CacheManager()
    assert mgr.is_enabled is False
    assert mgr.get_stats().get('enabled') is False
    assert mgr.invalidate_user_cache(123) == 0

