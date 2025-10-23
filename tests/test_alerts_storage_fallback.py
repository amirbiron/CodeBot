import types
import importlib


def test_record_alert_insert_fallback(monkeypatch):
    # Enable storage
    monkeypatch.setenv('ALERTS_DB_ENABLED', '1')

    class _Coll:
        def update_one(self, q, u, upsert=False):  # noqa: ARG001
            raise RuntimeError('dup')
        def insert_one(self, doc):
            test_record_alert_insert_fallback.captured = doc  # type: ignore[attr-defined]
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

    s.record_alert(alert_id=None, name='X', severity='warn', summary='y', source='z', silenced=False)
    doc = getattr(test_record_alert_insert_fallback, 'captured', None)  # type: ignore[attr-defined]
    assert doc is not None and doc.get('name') == 'X'
