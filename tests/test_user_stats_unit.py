import types
import pytest
import importlib
from datetime import datetime, timezone, timedelta


def _make_fake_mongo(docs_holder):
    class FakeUsersCollection:
        def __init__(self):
            self._docs = docs_holder
            self.last_update = None

        def update_one(self, flt, update, upsert=False):
            self.last_update = {"filter": flt, "update": update, "upsert": upsert}
            # emulate upsert: insert doc shape (optional, not used)
            return types.SimpleNamespace(matched_count=1, modified_count=1, upserted_id=None)

        def find(self, query):
            # filter by updated_at >= ... if asked
            cond = query.get("updated_at") if isinstance(query, dict) else None
            if isinstance(cond, dict) and "$gte" in cond:
                threshold = cond["$gte"]
                return [d for d in self._docs if d.get("updated_at", datetime.now(timezone.utc)) >= threshold]
            return list(self._docs)

        def count_documents(self, query):
            if not query:
                return len(self._docs)
            if "last_seen" in query:
                val = query["last_seen"]
                return sum(1 for d in self._docs if d.get("last_seen") == val)
            if "updated_at" in query and isinstance(query["updated_at"], dict):
                threshold = query["updated_at"]["$gte"]
                return sum(1 for d in self._docs if d.get("updated_at", datetime.now(timezone.utc)) >= threshold)
            return 0

    class FakeDBTop:
        def __init__(self, users_coll):
            self.db = types.SimpleNamespace(users=users_coll)
            self.saved = []

        def save_user(self, user_id, username=None):
            self.saved.append((user_id, username))

    users = FakeUsersCollection()
    top = FakeDBTop(users)
    return top, users


@pytest.mark.asyncio
async def test_log_user_updates_and_increments(monkeypatch):
    # Arrange fake database module before import
    docs = []
    top, users = _make_fake_mongo(docs)
    mod = types.ModuleType("database")
    mod.db = top
    monkeypatch.setitem(__import__("sys").modules, "database", mod)

    # Import module under test (reload to bind our mocked database)
    us_mod = importlib.reload(importlib.import_module("user_stats"))
    stats = us_mod.UserStats()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Act
    stats.log_user(7, username="alice", weight=3)

    # Assert save_user called
    assert top.saved == [(7, "alice")]
    assert users.last_update is not None
    update = users.last_update["update"]
    assert users.last_update["upsert"] is True
    # last_seen and usage_days include today
    assert update["$set"]["last_seen"] == today
    assert today in update["$addToSet"]["usage_days"]
    # total_actions increment equals weight
    assert update["$inc"]["total_actions"] == 3


def test_get_weekly_stats_filters_and_sorts(monkeypatch):
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    # docs: a has 4 recent days, fewer actions; b has 3 days, more actions
    a_days = [(now - timedelta(days=d)).strftime("%Y-%m-%d") for d in [0, 1, 2, 3]]
    b_days = [(now - timedelta(days=d)).strftime("%Y-%m-%d") for d in [0, 1, 2]]
    docs = [
        {"user_id": 1, "username": "a", "usage_days": a_days, "total_actions": 10, "updated_at": now},
        {"user_id": 2, "username": "b", "usage_days": b_days, "total_actions": 20, "updated_at": now},
        # old user beyond week
        {"user_id": 3, "username": "c", "usage_days": [(now - timedelta(days=10)).strftime("%Y-%m-%d")], "total_actions": 30, "updated_at": now - timedelta(days=10)},
    ]
    top, users = _make_fake_mongo(docs)
    mod = types.ModuleType("database")
    mod.db = top
    monkeypatch.setitem(__import__("sys").modules, "database", mod)

    import importlib
    us_mod = importlib.reload(importlib.import_module("user_stats"))
    stats = us_mod.UserStats()

    out = stats.get_weekly_stats()
    # only a and b, sorted by (days desc, total_actions desc)
    assert [o["username"] for o in out] == ["a", "b"]


def test_get_all_time_stats_counts(monkeypatch):
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    docs = [
        {"user_id": 1, "last_seen": today, "updated_at": now},
        {"user_id": 2, "last_seen": today, "updated_at": now},
        {"user_id": 3, "last_seen": (now - timedelta(days=1)).strftime("%Y-%m-%d"), "updated_at": now - timedelta(days=8)},
    ]
    top, users = _make_fake_mongo(docs)
    mod = types.ModuleType("database")
    mod.db = top
    monkeypatch.setitem(__import__("sys").modules, "database", mod)

    us_mod = importlib.reload(importlib.import_module("user_stats"))
    stats = us_mod.UserStats()

    out = stats.get_all_time_stats()
    assert out["total_users"] == 3
    assert out["active_today"] == 2
    # Only two have updated_at within a week
    assert out["active_week"] == 2

