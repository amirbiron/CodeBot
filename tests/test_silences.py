import os
import types
import importlib
from datetime import datetime, timedelta, timezone


def test_parse_duration_to_seconds_bounds():
    sil = importlib.import_module('monitoring.silences')
    parse = sil.parse_duration_to_seconds
    # valid
    assert parse('30s') == 30
    assert parse('5m') == 300
    assert parse('2h') == 7200
    assert parse('1d') == 86400
    # whitespace and case
    assert parse(' 10 M ') == 600
    # invalid
    assert parse('') is None
    assert parse('abc') is None
    assert parse('-5m') is None
    # cap to max_days
    assert parse('999d', max_days=7) == 7 * 86400


def test_create_is_silenced_and_unsilence(monkeypatch):
    # Enable DB and fake pymongo in-memory collection
    monkeypatch.setenv('ALERTS_DB_ENABLED', '1')
    # minimal stub collection
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
    class _Cli:
        def __init__(self):
            self.admin = types.SimpleNamespace(command=lambda *a, **k: {"ok": 1})
        def __getitem__(self, name):
            return {os.getenv('ALERTS_SILENCES_COLLECTION') or 'alerts_silences': _Coll()}
    # stub pymongo and MongoClient path
    fake_pymongo = types.SimpleNamespace(MongoClient=lambda *a, **k: _Cli(), ASCENDING=1)
    monkeypatch.setitem(importlib.sys.modules, 'pymongo', fake_pymongo)

    sil = importlib.import_module('monitoring.silences')
    importlib.reload(sil)

    # Create a silence
    doc = sil.create_silence(pattern='High.*', duration_seconds=60, created_by=1, reason='test', severity='critical')
    assert doc and doc.get('active') is True

    # Match by name
    ok, sdoc = sil.is_silenced(name='High Latency', severity='critical')
    assert ok and sdoc is not None

    # Unmatch by severity mismatch
    ok2, _ = sil.is_silenced(name='High Latency', severity='warn')
    assert ok2 is False

    # Unsilence by id
    sid = doc.get('_id')
    assert sil.unsilence_by_id(sid) is True
    ok3, _ = sil.is_silenced(name='High Latency', severity='critical')
    assert ok3 is False

    # Create 2 and unsilence by pattern
    sil.create_silence(pattern='Error.*', duration_seconds=60, created_by=1)
    sil.create_silence(pattern='Error.*', duration_seconds=60, created_by=1)
    n = sil.unsilence_by_pattern('Error.*')
    assert n >= 1


def test_dangerous_pattern_guard(monkeypatch):
    monkeypatch.setenv('ALERTS_DB_ENABLED', '1')
    # Force non-dangerous without --force
    import importlib as _il
    sil = _il.import_module('monitoring.silences')
    # No DB available -> returns None safely
    doc = sil.create_silence(pattern='.*', duration_seconds=60, created_by=1, force=False)
    assert doc is None
