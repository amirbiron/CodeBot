import os
import types
import importlib
from datetime import datetime, timedelta, timezone


def _install_fake_pymongo(monkeypatch, coll_obj=None):
    class _Coll:
        def __init__(self):
            self.docs = []
        def insert_one(self, doc):
            self.docs.append(doc)
            return types.SimpleNamespace(inserted_id=doc['_id'])
        def count_documents(self, q):
            now = datetime.now(timezone.utc)
            cnt = 0
            for d in self.docs:
                if q.get('active') is True and not d.get('active', False):
                    continue
                until = d.get('until_ts')
                if until and until >= now:
                    cnt += 1
            return cnt
        def find(self, q):
            now = datetime.now(timezone.utc)
            out = []
            for d in self.docs:
                if q.get('active') is True and not d.get('active', False):
                    continue
                if 'until_ts' in q:
                    until = d.get('until_ts')
                    if not until or until < q['until_ts']['$gte']:
                        continue
                out.append(d)
            return types.SimpleNamespace(sort=lambda *a, **k: out)
        def update_one(self, q, u):
            matched = 0
            for d in self.docs:
                if d.get('_id') == q.get('_id'):
                    d.update(u.get('$set', {}))
                    matched += 1
            return types.SimpleNamespace(matched_count=matched, modified_count=matched)
        def update_many(self, q, u):
            matched = 0
            for d in self.docs:
                if d.get('pattern') == q.get('pattern') and d.get('active'):
                    d.update(u.get('$set', {}))
                    matched += 1
            return types.SimpleNamespace(modified_count=matched)
        def create_index(self, *a, **k):
            return None
    coll_inst = coll_obj or _Coll()
    class _Cli:
        def __init__(self, coll):
            self._coll = coll
            self._db = {os.getenv('ALERTS_SILENCES_COLLECTION') or 'alerts_silences': self._coll}
            self.admin = types.SimpleNamespace(command=lambda *a, **k: {"ok": 1})
        def __getitem__(self, name):
            return self._db
    fake_pymongo = types.SimpleNamespace(MongoClient=lambda *a, **k: _Cli(coll_inst), ASCENDING=1)
    monkeypatch.setitem(importlib.sys.modules, 'pymongo', fake_pymongo)
    return coll_inst


def test_limits_active_silences_cap(monkeypatch):
    monkeypatch.setenv('ALERTS_DB_ENABLED', '1')
    monkeypatch.setenv('SILENCES_MAX_ACTIVE', '2')
    coll = _install_fake_pymongo(monkeypatch)
    import monitoring.silences as sil
    import importlib as _il
    _il.reload(sil)
    # Fill to cap
    assert sil.create_silence(pattern='A', duration_seconds=60, created_by=1)
    assert sil.create_silence(pattern='B', duration_seconds=60, created_by=1)
    # Next should fail due to cap
    assert sil.create_silence(pattern='C', duration_seconds=60, created_by=1) is None


def test_invalid_regex_falls_back_to_exact(monkeypatch):
    monkeypatch.setenv('ALERTS_DB_ENABLED', '1')
    _install_fake_pymongo(monkeypatch)
    import monitoring.silences as sil
    import importlib as _il
    _il.reload(sil)
    sil.create_silence(pattern='[invalid', duration_seconds=60, created_by=1)
    ok, _ = sil.is_silenced(name='[invalid')
    assert ok is True


def test_list_active_silences(monkeypatch):
    monkeypatch.setenv('ALERTS_DB_ENABLED', '1')
    coll = _install_fake_pymongo(monkeypatch)
    import monitoring.silences as sil
    import importlib as _il
    _il.reload(sil)
    sil.create_silence(pattern='X', duration_seconds=60, created_by=1, severity='critical', reason='maint')
    items = sil.list_active_silences(limit=10)
    assert items and items[0]['pattern'] == 'X'
