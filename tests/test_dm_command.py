import types
import asyncio
import pytest


@pytest.mark.asyncio
async def test_dm_requires_admin(monkeypatch):
    import bot_handlers as bh

    # No admins
    monkeypatch.delenv("ADMIN_USER_IDS", raising=False)

    # Stub reporter
    monkeypatch.setattr(bh.reporter, "report_activity", lambda *a, **k: None, raising=False)

    class Msg:
        def __init__(self):
            self.calls = []
            self.text = "/dm 1 hi"
        async def reply_text(self, text, **kwargs):
            self.calls.append(text)

    class Upd:
        def __init__(self):
            self.message = Msg()
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=111)

    class Ctx:
        def __init__(self):
            self.bot = types.SimpleNamespace(send_message=lambda **_: None)

    adv = bh.AdvancedBotHandlers(type("_A", (), {"add_handler": lambda *_: None})())
    u = Upd()
    c = Ctx()
    await adv.dm_command(u, c)
    assert any("פקודה זמינה רק למנהלים" in s for s in u.message.calls)


@pytest.mark.asyncio
async def test_dm_usage_hint_when_missing_args(monkeypatch):
    import bot_handlers as bh
    monkeypatch.setenv("ADMIN_USER_IDS", "999")
    monkeypatch.setattr(bh.reporter, "report_activity", lambda *a, **k: None, raising=False)

    class Msg:
        def __init__(self, text):
            self.text = text
            self.calls = []
        async def reply_text(self, text, **kwargs):
            self.calls.append(text)

    class Upd:
        def __init__(self, text):
            self.message = Msg(text)
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=999)

    class Ctx:
        def __init__(self):
            self.bot = types.SimpleNamespace(send_message=lambda **_: None)

    adv = bh.AdvancedBotHandlers(type("_A", (), {"add_handler": lambda *_: None})())
    for bad in ["/dm", "/dm 123", "/dm@Bot 123"]:
        u = Upd(bad)
        c = Ctx()
        await adv.dm_command(u, c)
        assert any("שימוש: /dm" in s for s in u.message.calls)


@pytest.mark.asyncio
async def test_dm_success_user_id_preserves_whitespace(monkeypatch):
    import bot_handlers as bh
    monkeypatch.setenv("ADMIN_USER_IDS", "999")
    monkeypatch.setattr(bh.reporter, "report_activity", lambda *a, **k: None, raising=False)

    sent = {}
    async def send_message(chat_id, text, parse_mode=None, disable_web_page_preview=None):
        sent.update({
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
        })

    class Msg:
        def __init__(self):
            self.text = "/dm 123456 A\nB\nC"
            self.calls = []
        async def reply_text(self, text, **kwargs):
            self.calls.append(text)

    class Upd:
        def __init__(self):
            self.message = Msg()
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=999)

    class Ctx:
        def __init__(self):
            self.bot = types.SimpleNamespace(send_message=send_message)

    adv = bh.AdvancedBotHandlers(type("_A", (), {"add_handler": lambda *_: None})())
    u = Upd()
    c = Ctx()
    await adv.dm_command(u, c)

    assert sent["chat_id"] == 123456
    assert sent["parse_mode"] == bh.ParseMode.HTML
    assert sent["disable_web_page_preview"] is True
    assert sent["text"].startswith("<pre>") and sent["text"].endswith("</pre>")
    # Feedback to caller
    assert any("ההודעה נשלחה" in s for s in u.message.calls)


@pytest.mark.asyncio
async def test_dm_retryafter_then_success(monkeypatch):
    import bot_handlers as bh
    monkeypatch.setenv("ADMIN_USER_IDS", "999")
    monkeypatch.setattr(bh.reporter, "report_activity", lambda *a, **k: None, raising=False)

    # Patch RetryAfter to simple exception with retry_after
    class _RetryAfter(Exception):
        def __init__(self, retry_after):
            super().__init__("retry")
            self.retry_after = retry_after
    monkeypatch.setattr(bh.telegram.error, "RetryAfter", _RetryAfter, raising=False)

    state = {"first": True}
    async def send_message(chat_id, text, parse_mode=None, disable_web_page_preview=None):
        if state["first"]:
            state["first"] = False
            raise _RetryAfter(0.01)
        return None

    class Msg:
        def __init__(self):
            self.text = "/dm 5 hello"
            self.calls = []
        async def reply_text(self, text, **kwargs):
            self.calls.append(text)

    class Upd:
        def __init__(self):
            self.message = Msg()
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=999)

    class Ctx:
        def __init__(self):
            self.bot = types.SimpleNamespace(send_message=send_message)

    adv = bh.AdvancedBotHandlers(type("_A", (), {"add_handler": lambda *_: None})())
    u = Upd()
    c = Ctx()
    await adv.dm_command(u, c)

    assert any("לאחר המתנה" in s for s in u.message.calls)


@pytest.mark.asyncio
async def test_dm_forbidden_marks_blocked(monkeypatch):
    import bot_handlers as bh
    monkeypatch.setenv("ADMIN_USER_IDS", "999")
    monkeypatch.setattr(bh.reporter, "report_activity", lambda *a, **k: None, raising=False)

    async def send_message(chat_id, text, **kwargs):
        raise bh.telegram.error.Forbidden("blocked")

    updated = {}
    class _Users:
        def update_one(self, query, update):
            updated["query"] = query
            updated["update"] = update
            return types.SimpleNamespace(modified_count=1)

    class _DB:
        users = _Users()

    monkeypatch.setattr(bh, "db", types.SimpleNamespace(db=_DB()))

    class Msg:
        def __init__(self):
            self.text = "/dm 7 hi"
            self.calls = []
        async def reply_text(self, text, **kwargs):
            self.calls.append(text)

    class Upd:
        def __init__(self):
            self.message = Msg()
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=999)

    class Ctx:
        def __init__(self):
            self.bot = types.SimpleNamespace(send_message=send_message)

    adv = bh.AdvancedBotHandlers(type("_A", (), {"add_handler": lambda *_: None})())
    u = Upd()
    c = Ctx()
    await adv.dm_command(u, c)

    assert updated.get("query", {}).get("user_id") == 7
    assert updated.get("update", {}).get("$set", {}).get("blocked") is True
    assert any("סומן כ-blocked" in s for s in u.message.calls)


@pytest.mark.asyncio
async def test_dm_username_resolution(monkeypatch):
    import bot_handlers as bh
    monkeypatch.setenv("ADMIN_USER_IDS", "999")
    monkeypatch.setattr(bh.reporter, "report_activity", lambda *a, **k: None, raising=False)

    captured = {}
    async def send_message(chat_id, text, **kwargs):
        captured["chat_id"] = chat_id

    class _Users:
        def find_one(self, query):
            # Support both exact/lowercase attempts
            if query.get("username") in {"USERA", "usera"}:
                return {"user_id": 555}
            return None

    monkeypatch.setattr(bh, "db", types.SimpleNamespace(db=types.SimpleNamespace(users=_Users())))

    class Msg:
        def __init__(self):
            self.text = "/dm @UserA hi"
            self.calls = []
        async def reply_text(self, text, **kwargs):
            self.calls.append(text)

    class Upd:
        def __init__(self):
            self.message = Msg()
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=999)

    class Ctx:
        def __init__(self):
            self.bot = types.SimpleNamespace(send_message=send_message)

    adv = bh.AdvancedBotHandlers(type("_A", (), {"add_handler": lambda *_: None})())
    u = Upd()
    c = Ctx()
    await adv.dm_command(u, c)
    assert captured.get("chat_id") == 555
