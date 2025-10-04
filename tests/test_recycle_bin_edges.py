import types
import pytest


@pytest.mark.asyncio
async def test_show_recycle_bin_empty_and_parse_mode(monkeypatch):
    import conversation_handlers as ch

    class DummyRepo:
        def list_deleted_files(self, user_id, page=1, per_page=10):
            return ([], 0)

    class DummyDB:
        def __init__(self, repo):
            self._repo = repo
        def _get_repo(self):
            return self._repo

    mod = types.ModuleType("database")
    mod.db = DummyDB(DummyRepo())
    monkeypatch.setitem(__import__('sys').modules, "database", mod)

    captured = {}
    async def fake_safe_edit_message_text(query, text, reply_markup=None, parse_mode=None):
        captured["text"] = text
        captured["reply_markup"] = reply_markup
        captured["parse_mode"] = parse_mode
    from utils import TelegramUtils
    monkeypatch.setattr(TelegramUtils, "safe_edit_message_text", fake_safe_edit_message_text)

    class Q:
        def __init__(self, data):
            self.data = data
        async def answer(self, *a, **k):
            return None

    class U:
        def __init__(self, data):
            self.callback_query = Q(data)
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=1)

    u = U("recycle_bin")
    await ch.show_recycle_bin(u, types.SimpleNamespace(user_data={}))

    # Assert header rendered with 0 items and HTML parse mode
    assert captured.get("parse_mode") is not None
    assert "🗑️" in (captured.get("text") or "")
    assert "0" in (captured.get("text") or "")


@pytest.mark.asyncio
async def test_show_recycle_bin_exception_path(monkeypatch):
    import conversation_handlers as ch

    class BadRepo:
        def list_deleted_files(self, *a, **k):
            raise RuntimeError("boom")

    class DummyDB:
        def __init__(self, repo):
            self._repo = repo
        def _get_repo(self):
            return self._repo

    mod = types.ModuleType("database")
    mod.db = DummyDB(BadRepo())
    monkeypatch.setitem(__import__('sys').modules, "database", mod)

    captured = {"text": None}
    async def fake_safe_edit_message_text(query, text, reply_markup=None, parse_mode=None):
        captured["text"] = text
    from utils import TelegramUtils
    monkeypatch.setattr(TelegramUtils, "safe_edit_message_text", fake_safe_edit_message_text)

    class Q:
        def __init__(self, data):
            self.data = data
        async def answer(self, *a, **k):
            return None

    class U:
        def __init__(self, data):
            self.callback_query = Q(data)
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=2)

    u = U("recycle_bin")
    await ch.show_recycle_bin(u, types.SimpleNamespace(user_data={}))
    assert "❌" in (captured.get("text") or "")


@pytest.mark.asyncio
async def test_recycle_restore_and_purge_failure_alerts(monkeypatch):
    import conversation_handlers as ch

    class Repo:
        def list_deleted_files(self, *a, **k):
            return ([], 0)
        def restore_file_by_id(self, user_id, fid):
            return False
        def purge_file_by_id(self, user_id, fid):
            return False

    class DummyDB:
        def __init__(self, repo):
            self._repo = repo
        def _get_repo(self):
            return self._repo

    mod = types.ModuleType("database")
    mod.db = DummyDB(Repo())
    monkeypatch.setitem(__import__('sys').modules, "database", mod)

    class Q:
        def __init__(self, data):
            self.data = data
            self.answers = []
        async def answer(self, *a, **k):
            self.answers.append(k)

    class U:
        def __init__(self, data):
            self.callback_query = Q(data)
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=3)

    # restore with id but repo returns False
    u1 = U("recycle_restore:someid")
    await ch.recycle_restore(u1, types.SimpleNamespace(user_data={}))
    assert any(a.get("show_alert") for a in u1.callback_query.answers)

    # purge with id but repo returns False
    u2 = U("recycle_purge:someid")
    await ch.recycle_purge(u2, types.SimpleNamespace(user_data={}))
    assert any(a.get("show_alert") for a in u2.callback_query.answers)
