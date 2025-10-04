import types
from datetime import datetime, timedelta, timezone


def test_list_deleted_files_combined_sort_and_pagination(monkeypatch):
    from database.repository import Repository

    # Prepare docs with timestamps: newer should come first
    now = datetime.now(timezone.utc)
    reg_docs = [
        {"_id": "r1", "user_id": 1, "file_name": "a.py", "is_active": False, "deleted_at": now - timedelta(minutes=5)},
        {"_id": "r2", "user_id": 1, "file_name": "b.py", "is_active": False, "deleted_at": now - timedelta(minutes=10)},
    ]
    large_docs = [
        {"_id": "l1", "user_id": 1, "file_name": "big.txt", "is_active": False, "deleted_at": now - timedelta(minutes=2)},
    ]

    class Coll:
        def __init__(self, items):
            self._items = items
        def find(self, flt):
            # return only items matching user_id and is_active False
            uid = flt.get("user_id")
            active = flt.get("is_active")
            return [d for d in self._items if d.get("user_id") == uid and d.get("is_active") == active]

    class DummyManager:
        def __init__(self, reg, large):
            self.collection = Coll(reg)
            self.large_files_collection = Coll(large)

    repo = Repository(DummyManager(reg_docs, large_docs))

    # per_page small to force pagination
    page1, total = repo.list_deleted_files(1, page=1, per_page=2)
    assert total == 3
    # Expect newest first: large l1 (2m), then reg r1 (5m)
    first_names = [d.get("_id") for d in page1]
    assert first_names == ["l1", "r1"]

    page2, _ = repo.list_deleted_files(1, page=2, per_page=2)
    assert [d.get("_id") for d in page2] == ["r2"]

    # invalid inputs branch: page<1 and per_page<1 fallback
    pageX, totalX = repo.list_deleted_files(1, page=0, per_page=0)
    # Should still return first 20 (effectively page=1, per_page=20) -> all 3
    assert len(pageX) == 3 and totalX == 3
