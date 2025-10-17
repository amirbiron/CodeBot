import types
from datetime import datetime, timezone, timedelta

import pytest


class _NoopUsers:
    def __init__(self):
        self.docs = {}

    def find_one(self, q):
        _id = q.get("_id")
        return self.docs.get(_id)

    def update_one(self, q, u, upsert=False):
        _id = q.get("_id")
        doc = self.docs.get(_id) or {}
        setv = (u or {}).get("$set") or {}
        for k, v in setv.items():
            doc[k] = v
        self.docs[_id] = doc
        return types.SimpleNamespace(acknowledged=True)


@pytest.mark.asyncio
async def test_backoff_state_persist_and_reload(monkeypatch):
    import services.backoff_state as bs

    # Stub DB
    users = _NoopUsers()
    db_ns = types.SimpleNamespace(db=types.SimpleNamespace(users=users))
    monkeypatch.setattr("database", "db", db_ns, raising=False)

    st = bs.BackoffState()
    assert st.get().enabled is False

    # Enable with TTL
    info = st.enable(reason="test", ttl_minutes=1)
    assert info.enabled is True
    # Force refresh from DB and ensure it loads
    loaded = st.get(refresh=True)
    assert loaded.enabled is True and loaded.reason == "test"

    # Simulate restart by creating a new instance, must read from DB
    st2 = bs.BackoffState()
    loaded2 = st2.get(refresh=True)
    assert loaded2.enabled is True and loaded2.reason == "test"


def test_backoff_state_expiry(monkeypatch):
    import services.backoff_state as bs

    users = _NoopUsers()
    db_ns = types.SimpleNamespace(db=types.SimpleNamespace(users=users))
    monkeypatch.setattr("database", "db", db_ns, raising=False)

    st = bs.BackoffState()
    # Enable with negative TTL -> expired soon
    info = st.enable(reason="ttl", ttl_minutes=0)
    assert info.enabled is True
    # Manually set expires_at in the past
    users.docs["__global_state__"] = {
        "github": {
            "backoff": {
                "enabled": True,
                "reason": "ttl",
                "updated_at": datetime.now(timezone.utc),
                "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
            }
        }
    }
    # Refresh should auto-deactivate
    cur = st.get(refresh=True)
    assert cur.enabled is False
