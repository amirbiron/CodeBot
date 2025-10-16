import types
import setup_bookmarks as sb


def test_setup_bookmarks_emits_events(monkeypatch):
    captured = {"evts": []}

    def _emit(event: str, severity: str = "info", **fields):
        captured["evts"].append((event, severity, fields))

    # Patch emit_event
    monkeypatch.setattr(sb, "emit_event", _emit, raising=False)

    # Simulate Mongo client and DB
    class _Client:
        def __init__(self, *_a, **_k):
            pass
        def server_info(self):
            return {"ok": 1}
        def __getitem__(self, name):
            return _DB()

    class _DB:
        def list_collection_names(self):
            return []
        def create_collection(self, *_a, **_k):
            return None
        @property
        def file_bookmarks(self):
            return types.SimpleNamespace(list_indexes=lambda: [object(), object()])

    # BookmarksManager init should succeed
    class _BM:
        def __init__(self, *_a, **_k):
            pass

    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017")
    monkeypatch.setenv("DATABASE_NAME", "db")
    monkeypatch.setitem(sb.sys.modules, "pymongo", types.SimpleNamespace(MongoClient=_Client))
    monkeypatch.setitem(sb.sys.modules, "database.bookmarks_manager", types.SimpleNamespace(BookmarksManager=_BM))

    db = sb.check_mongodb_connection()
    assert db is not None
    ok = sb.setup_bookmarks_collection(db)
    assert ok is True

    evs = [e[0] for e in captured["evts"]]
    assert "bookmarks_mongodb_connected" in evs
    assert "bookmarks_collection_created" in evs
    assert "bookmarks_indexes_created" in evs
