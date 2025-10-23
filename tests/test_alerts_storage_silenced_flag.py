import types
import importlib
from datetime import datetime, timezone


def test_record_alert_includes_silenced_flag(monkeypatch):
    # Enable storage
    monkeypatch.setenv('ALERTS_DB_ENABLED', '1')

    # Fake collection that captures inserted/updated docs
    captured = {"docs": []}
    class _Coll:
        def __init__(self):
            pass
        def update_one(self, q, u, upsert=False):  # noqa: ARG001
            doc = u.get('$setOnInsert', {})
            if doc:
                captured["docs"].append(doc)
            return types.SimpleNamespace()
        def insert_one(self, doc):
            captured["docs"].append(doc)
            return types.SimpleNamespace(inserted_id=1)
        def create_index(self, *a, **k):
            return None
    class _Cli:
        def __init__(self):
            self._db = {"alerts_log": _Coll()}
            self.admin = types.SimpleNamespace(command=lambda *a, **k: {"ok": 1})
        def __getitem__(self, name):
            return self._db
    fake_pymongo = types.SimpleNamespace(MongoClient=lambda *a, **k: _Cli(), ASCENDING=1)
    monkeypatch.setitem(importlib.sys.modules, 'pymongo', fake_pymongo)

    import monitoring.alerts_storage as s
    import importlib as _il
    _il.reload(s)

    s.record_alert(alert_id="x", name="High Latency", severity="critical", summary="t", source="ut", silenced=True)

    assert captured["docs"], "no doc recorded"
    doc = captured["docs"][0]
    assert doc.get("silenced") is True
    # sanity: required fields exist
    assert isinstance(doc.get("ts_dt"), datetime)
    assert doc.get("name") == "High Latency"
