import types


def _cap_emit(mod):
    captured = {"events": []}
    def _emit(event, severity="info", **fields):
        captured["events"].append((event, severity, fields))
    return captured, _emit


def test_manager_indexes_conflict_update_failed_emits(monkeypatch):
    import database.manager as m
    cap, _emit = _cap_emit(m)
    monkeypatch.setattr(m, "emit_event", _emit, raising=False)

    # Stub a manager with collections that cause IndexOptionsConflict branch then inner failure
    class _Idx:
        def __init__(self, name):
            self.name = name
        def get(self, k, d=None):
            return {"name": self.name}.get(k, d)
    class _Coll:
        def create_indexes(self, *a, **k):
            raise RuntimeError("IndexOptionsConflict")
        def list_indexes(self):
            # Return indexes that will be iterated and dropped
            return [{"name": "full_text_search_idx"}, {"name": "user_lang_date_idx"}]
        def drop_index(self, *a, **k):
            # Make drop_index raise so inner except emits db_indexes_conflict_update_failed
            raise RuntimeError("drop fail")
    dm = m.DatabaseManager.__new__(m.DatabaseManager)
    dm.collection = _Coll()
    dm.large_files_collection = _Coll()
    dm.backup_ratings_collection = _Coll()

    try:
        dm._create_indexes()
    except Exception:
        pass

    assert any(e[0] == "db_indexes_conflict_update_failed" for e in cap["events"])  # event emitted
