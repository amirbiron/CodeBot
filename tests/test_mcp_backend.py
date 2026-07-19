"""Unit tests for ProductionBackend: serialization + the critical ownership check."""

from mcp_server.backend import ProductionBackend, _full


class _FakeDbManager:
    def __init__(self, files=None, by_id=None, versions=None, search=None):
        self._files = files or []
        self._by_id = by_id or {}
        self._versions = versions or []
        self._search = search or []

    def get_regular_files_paginated(self, user_id, page, per_page):
        return list(self._files), len(self._files)

    def search_code(self, user_id, query, programming_language=None, limit=20):
        return list(self._search)

    def get_file_by_id(self, file_id):
        return self._by_id.get(file_id)

    def get_latest_version(self, user_id, file_name):
        return next((f for f in self._files if f.get("file_name") == file_name), None)

    def get_version(self, user_id, file_name, version):
        return next(
            (
                v
                for v in self._versions
                if v.get("file_name") == file_name and v.get("version") == version
            ),
            None,
        )

    def get_all_versions(self, user_id, file_name):
        return [v for v in self._versions if v.get("file_name") == file_name]


def test_list_files_excludes_heavy_code_field():
    dbm = _FakeDbManager(
        files=[
            {
                "_id": "a",
                "file_name": "x.py",
                "code": "secret",
                "programming_language": "python",
                "file_size": 6,
            }
        ]
    )
    out = ProductionBackend(db_manager=dbm).list_files(7, page=1, per_page=50)
    assert out["total"] == 1
    f = out["files"][0]
    assert "code" not in f
    assert f["id"] == "a"
    assert f["file_name"] == "x.py"
    assert f["language"] == "python"


def test_search_excludes_code():
    dbm = _FakeDbManager(
        search=[{"_id": "s1", "file_name": "y.py", "programming_language": "python"}]
    )
    rows = ProductionBackend(db_manager=dbm).search_code(7, query="y")
    assert rows and "code" not in rows[0]
    assert rows[0]["id"] == "s1"


def test_get_file_by_id_enforces_ownership():
    dbm = _FakeDbManager(
        by_id={"f1": {"_id": "f1", "user_id": 999, "file_name": "o.py", "code": "x"}}
    )
    be = ProductionBackend(db_manager=dbm)
    # Requesting user is not the owner -> denied.
    assert be.get_file(7, file_id="f1") is None
    # Owner gets full content.
    got = be.get_file(999, file_id="f1")
    assert got is not None and got["code"] == "x"


def test_get_file_by_name_returns_full_content():
    dbm = _FakeDbManager(
        files=[{"_id": "a", "file_name": "x.py", "code": "print(1)", "user_id": 7}]
    )
    doc = ProductionBackend(db_manager=dbm).get_file(7, file_name="x.py")
    assert doc["code"] == "print(1)"


def test_get_specific_version():
    dbm = _FakeDbManager(
        versions=[{"_id": "v2", "file_name": "x.py", "version": 2, "code": "v2code"}]
    )
    doc = ProductionBackend(db_manager=dbm).get_file(7, file_name="x.py", version=2)
    assert doc["version"] == 2 and doc["code"] == "v2code"


def test_large_file_content_mapped_to_code():
    assert _full({"_id": "a", "content": "blob"})["code"] == "blob"


def test_collections_delegate_to_manager():
    class _FakeCM:
        def list_collections(self, user_id, limit=100):
            return {"seen": (user_id, limit)}

        def get_collection(self, user_id, collection_id):
            return {"seen": (user_id, collection_id)}

        def get_collection_items(
            self, user_id, collection_id, page=1, per_page=20, folder_filter=None
        ):
            return {"seen": (user_id, collection_id, page, per_page, folder_filter)}

    be = ProductionBackend(collections_manager=_FakeCM())
    assert be.list_collections(3, limit=50)["seen"] == (3, 50)
    assert be.get_collection(3, collection_id="c1")["seen"] == (3, "c1")
    assert be.get_collection_items(3, collection_id="c1", page=2, per_page=10, folder="f")[
        "seen"
    ] == (3, "c1", 2, 10, "f")


def test_collection_items_strip_heavy_fields():
    class _LeakyCM:
        def get_collection_items(
            self, user_id, collection_id, page=1, per_page=20, folder_filter=None
        ):
            return {
                "ok": True,
                "items": [{"id": "1", "file_name": "a.py", "code": "LEAK", "content": "LEAK2"}],
            }

    be = ProductionBackend(collections_manager=_LeakyCM())
    out = be.get_collection_items(3, collection_id="c1")
    item = out["items"][0]
    assert "code" not in item and "content" not in item
    assert item["file_name"] == "a.py"
