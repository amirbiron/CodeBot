import types
import importlib
import pytest


class DummyColl:
    def __init__(self, raise_on_index=False, modified_at=1, modified_exp=1):
        self.raise_on_index = raise_on_index
        self.calls = {"create_index": 0, "update_many": []}
        self.modified_at = modified_at
        self.modified_exp = modified_exp

    def create_index(self, *a, **k):
        self.calls["create_index"] += 1
        if self.raise_on_index:
            raise RuntimeError("index error")
        return None

    def update_many(self, flt, upd):
        self.calls["update_many"].append((flt, upd))
        if "$set" in upd and "deleted_at" in upd["$set"]:
            return types.SimpleNamespace(modified_count=self.modified_at)
        if "$set" in upd and "deleted_expires_at" in upd["$set"]:
            return types.SimpleNamespace(modified_count=self.modified_exp)
        return types.SimpleNamespace(modified_count=0)


class FakeMessage:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text):
        self.sent.append(text)


class FakeUser:
    def __init__(self, uid):
        self.id = uid


class FakeUpdate:
    def __init__(self, uid=0):
        self.effective_user = FakeUser(uid)
        self.message = FakeMessage()


class FakeContext:
    def __init__(self, args=None):
        self.args = args or []


@pytest.mark.asyncio
async def test_recycle_backfill_denied_for_non_admin(monkeypatch):
    # Ensure required env for importing main/config
    monkeypatch.setenv("BOT_TOKEN", "dummy")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/test")
    monkeypatch.setenv("DISABLE_DB", "1")

    # Import fresh module
    m = importlib.import_module("main")
    # Force no admins
    monkeypatch.setattr(m, "get_admin_ids", lambda: [])

    upd = FakeUpdate(uid=111)
    ctx = FakeContext()

    await m.recycle_backfill_command(upd, ctx)

    assert any("למנהלים בלבד" in s for s in upd.message.sent)


@pytest.mark.asyncio
async def test_recycle_backfill_backfills_and_reports(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "dummy")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/test")
    monkeypatch.setenv("DISABLE_DB", "1")

    # Reload module to ensure clean state
    if "main" in __import__("sys").modules:
        importlib.reload(__import__("sys").modules["main"])  # type: ignore
    m = importlib.import_module("main")
    # Make current user admin
    monkeypatch.setattr(m, "get_admin_ids", lambda: [999])

    # Provide dummy db with one real collection and one missing
    coll = DummyColl(raise_on_index=False, modified_at=2, modified_exp=3)
    dummy_db = types.SimpleNamespace(collection=coll, large_files_collection=None)

    # Inject database module that main imports inside the function
    mod = types.ModuleType("database")
    mod.db = dummy_db
    monkeypatch.setitem(__import__('sys').modules, "database", mod)

    upd = FakeUpdate(uid=999)
    ctx = FakeContext(args=["5"])  # TTL days override

    await m.recycle_backfill_command(upd, ctx)

    # Verify report contains our TTL and counts, and mentions missing collection
    out = "\n".join(upd.message.sent)
    assert "TTL=5" in out
    assert "deleted_at=2, deleted_expires_at=3" in out
    assert "קבצים גדולים" in out and "דילוג" in out
    # Ensure index ensured and two updates executed
    assert coll.calls["create_index"] == 1
    assert len(coll.calls["update_many"]) == 2


@pytest.mark.asyncio
async def test_recycle_backfill_handles_index_errors(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "dummy")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/test")
    monkeypatch.setenv("DISABLE_DB", "1")

    # Reload module to ensure clean state
    if "main" in __import__("sys").modules:
        importlib.reload(__import__("sys").modules["main"])  # type: ignore
    m = importlib.import_module("main")

    monkeypatch.setattr(m, "get_admin_ids", lambda: [1])
    coll_ok = DummyColl(raise_on_index=True, modified_at=1, modified_exp=1)
    coll2 = DummyColl(raise_on_index=False, modified_at=0, modified_exp=0)
    dummy_db = types.SimpleNamespace(collection=coll_ok, large_files_collection=coll2)

    mod = types.ModuleType("database")
    mod.db = dummy_db
    monkeypatch.setitem(__import__('sys').modules, "database", mod)

    upd = FakeUpdate(uid=1)
    ctx = FakeContext(args=[])

    await m.recycle_backfill_command(upd, ctx)

    out = "\n".join(upd.message.sent)
    # Both collections reported, counts present (may be zeros on second)
    assert "Backfill סל מיחזור" in out
    assert "deleted_at=" in out and "deleted_expires_at=" in out
