import types
import importlib
import pytest


class DummyColl:
    def __init__(self, raise_on_index=False, modified_at=1, modified_exp=1, raise_on_update=False):
        self.raise_on_index = raise_on_index
        self.raise_on_update = raise_on_update
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
        if self.raise_on_update:
            raise RuntimeError("update error")
        if "$set" in upd and "deleted_at" in upd["$set"]:
            return types.SimpleNamespace(modified_count=self.modified_at)
        if "$set" in upd and "deleted_expires_at" in upd["$set"]:
            return types.SimpleNamespace(modified_count=self.modified_exp)
        return types.SimpleNamespace(modified_count=0)


class DummyDB(types.SimpleNamespace):
    """דמה ל-``database.db``: הקולקציות, ``has_real_database``, והפונקציה שיוצרת
    את אינדקס ה-TTL — שהפקודה קוראת לה במקום ליצור אינדקס בעצמה."""

    def __init__(self, collection, large_files_collection, ttl_status=None, has_real_database=True):
        super().__init__(
            collection=collection,
            large_files_collection=large_files_collection,
            has_real_database=has_real_database,
        )
        if ttl_status is None:
            ttl_status = {"code_snippets": True, "large_files": True}
        self._ttl_status = ttl_status
        self.ensure_calls = 0

    def ensure_recycle_bin_ttl_indexes(self):
        self.ensure_calls += 1
        return dict(self._ttl_status)


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
    dummy_db = DummyDB(collection=coll, large_files_collection=None)

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
    assert "קבצים רגילים: אינדקס TTL ✅ | deleted_at=2, deleted_expires_at=3" in out
    assert "קבצים גדולים" in out and "דילוג" in out
    # האינדקס נוצר דרך הפונקציה של מסלול העלייה — מקום אחד למפרט — ולא כאן.
    assert dummy_db.ensure_calls == 1
    assert coll.calls["create_index"] == 0
    assert len(coll.calls["update_many"]) == 2


@pytest.mark.asyncio
async def test_recycle_backfill_reports_an_index_failure(monkeypatch):
    """עד התיקון, כשל ביצירת האינדקס נבלע ב-``except: pass`` והבדיקה הזו
    קיבעה את הבליעה — הדוח נראה תקין בזמן שהסל לא התרוקן לעולם. עכשיו
    הכשל מופיע בדוח, לכל קולקציה בנפרד."""
    monkeypatch.setenv("BOT_TOKEN", "dummy")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/test")
    monkeypatch.setenv("DISABLE_DB", "1")

    # Reload module to ensure clean state
    if "main" in __import__("sys").modules:
        importlib.reload(__import__("sys").modules["main"])  # type: ignore
    m = importlib.import_module("main")

    monkeypatch.setattr(m, "get_admin_ids", lambda: [1])
    coll_ok = DummyColl(modified_at=1, modified_exp=1)
    coll2 = DummyColl(modified_at=0, modified_exp=0)
    dummy_db = DummyDB(
        collection=coll_ok,
        large_files_collection=coll2,
        ttl_status={"code_snippets": False, "large_files": True},
    )

    mod = types.ModuleType("database")
    mod.db = dummy_db
    monkeypatch.setitem(__import__('sys').modules, "database", mod)

    upd = FakeUpdate(uid=1)
    ctx = FakeContext(args=[])

    await m.recycle_backfill_command(upd, ctx)

    out = "\n".join(upd.message.sent)
    assert "Backfill סל מיחזור" in out
    assert "קבצים רגילים: אינדקס TTL ❌" in out
    assert "קבצים גדולים: אינדקס TTL ✅" in out


@pytest.mark.asyncio
async def test_recycle_backfill_reports_a_failed_update_as_an_error_not_zero(monkeypatch):
    """``0`` אומר "לא היה מה למלא". כשל חייב להיראות אחרת."""
    monkeypatch.setenv("BOT_TOKEN", "dummy")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/test")
    monkeypatch.setenv("DISABLE_DB", "1")

    if "main" in __import__("sys").modules:
        importlib.reload(__import__("sys").modules["main"])  # type: ignore
    m = importlib.import_module("main")

    monkeypatch.setattr(m, "get_admin_ids", lambda: [1])
    dummy_db = DummyDB(collection=DummyColl(raise_on_update=True), large_files_collection=None)

    mod = types.ModuleType("database")
    mod.db = dummy_db
    monkeypatch.setitem(__import__('sys').modules, "database", mod)

    upd = FakeUpdate(uid=1)
    await m.recycle_backfill_command(upd, FakeContext(args=[]))

    out = "\n".join(upd.message.sent)
    assert "deleted_at=שגיאה, deleted_expires_at=שגיאה" in out


@pytest.mark.asyncio
async def test_recycle_backfill_refuses_without_a_database(monkeypatch):
    """במצב no-op כל קולקציה "מצליחה" בלי לעשות דבר, והדוח היה מציג ✅ ואפסים."""
    monkeypatch.setenv("BOT_TOKEN", "dummy")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/test")
    monkeypatch.setenv("DISABLE_DB", "1")

    if "main" in __import__("sys").modules:
        importlib.reload(__import__("sys").modules["main"])  # type: ignore
    m = importlib.import_module("main")

    monkeypatch.setattr(m, "get_admin_ids", lambda: [1])
    coll = DummyColl()
    dummy_db = DummyDB(collection=coll, large_files_collection=None, has_real_database=False)

    mod = types.ModuleType("database")
    mod.db = dummy_db
    monkeypatch.setitem(__import__('sys').modules, "database", mod)

    upd = FakeUpdate(uid=1)
    await m.recycle_backfill_command(upd, FakeContext(args=[]))

    assert any("אין חיבור למסד" in s for s in upd.message.sent)
    assert dummy_db.ensure_calls == 0
    assert coll.calls["update_many"] == []


@pytest.mark.asyncio
async def test_recycle_backfill_refuses_when_the_database_is_disabled_on_purpose(monkeypatch):
    """עם ``DatabaseManager`` האמיתי ב-``DISABLE_DB``, ולא עם דמה.

    בניטרול מכוון המנהל מאתחל NoOp, ו-``is_connected`` שלו ``True``. שומר שבדק
    את ``is_connected`` עבר כאן: ``safe_create_index`` "הצליח" מול NoOp, והדוח
    הציג "אינדקס TTL ✅" ואפסים בלי שנכתב דבר. הדמה שבטסט הקודם לא יכלה לתפוס
    את זה, כי היא בונה מצב שהמנהל האמיתי אינו מייצר.
    """
    monkeypatch.setenv("BOT_TOKEN", "dummy")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/test")
    monkeypatch.setenv("DISABLE_DB", "1")

    if "main" in __import__("sys").modules:
        importlib.reload(__import__("sys").modules["main"])  # type: ignore
    m = importlib.import_module("main")
    monkeypatch.setattr(m, "get_admin_ids", lambda: [1])

    from database.manager import DatabaseManager

    mod = types.ModuleType("database")
    mod.db = DatabaseManager()
    monkeypatch.setitem(__import__("sys").modules, "database", mod)

    upd = FakeUpdate(uid=1)
    await m.recycle_backfill_command(upd, FakeContext(args=[]))

    assert any("אין חיבור למסד" in s for s in upd.message.sent)
    assert not any("✅" in s for s in upd.message.sent)
