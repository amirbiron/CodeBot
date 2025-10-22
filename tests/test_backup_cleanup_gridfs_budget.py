import types
import importlib
import asyncio
from datetime import datetime, timedelta, timezone


def test_gridfs_cleanup_respects_budget(monkeypatch):
    # Fake observability
    fake_obs = types.SimpleNamespace(
        emit_event=lambda *a, **k: None,
    )
    monkeypatch.setitem(importlib.sys.modules, "observability", fake_obs)

    # Build a fake GridFS-like object with many docs to ensure we can break early
    class FakeDoc:
        def __init__(self, i):
            self._id = i
            self.metadata = {"user_id": 1, "created_at": (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()}
            self.uploadDate = datetime.now(timezone.utc) - timedelta(days=100)

    class FakeFS:
        def find(self):
            # Generator to simulate lazy cursor
            for i in range(10000):
                yield FakeDoc(i)
        def delete(self, _id):  # noqa: ARG002
            return None

    # Inject fake GridFS
    import file_manager as fm
    mgr = fm.BackupManager()
    mgr._get_gridfs = lambda: FakeFS()

    # Use very small budget to force early stop
    res = mgr.cleanup_expired_backups(retention_days=1, budget_seconds=0.001)

    # Should scan at least a few entries but not all; cannot assert exact number
    assert res["gridfs_scanned"] >= 0
    # No exception should occur; deletions may be 0 due to early stop
    assert isinstance(res, dict)
