import os
import types
import importlib
from datetime import timedelta


def test_create_silence_dangerous_pattern_guard_with_db(monkeypatch):
    import monitoring.silences as sil
    monkeypatch.setenv('ALERTS_DB_ENABLED', '1')
    # Provide a minimal collection so _get_collection() succeeds
    class _Coll:
        def count_documents(self, q):  # noqa: ARG001
            return 0
        def insert_one(self, doc):  # noqa: ARG001
            return types.SimpleNamespace(inserted_id=1)
        def create_index(self, *a, **k):
            return None
    monkeypatch.setattr(sil, '_get_collection', lambda: _Coll())
    # Dangerous pattern without --force should return None
    assert sil.create_silence(pattern='.*', duration_seconds=60, created_by=1, force=False) is None


def test_create_silence_duration_capped_by_env(monkeypatch):
    import monitoring.silences as sil
    monkeypatch.setenv('ALERTS_DB_ENABLED', '1')
    monkeypatch.setenv('SILENCE_MAX_DAYS', '1')
    stored = {}
    class _Coll:
        def count_documents(self, q):  # noqa: ARG001
            return 0
        def insert_one(self, doc):
            stored['doc'] = doc
            return types.SimpleNamespace(inserted_id=1)
        def create_index(self, *a, **k):
            return None
    monkeypatch.setattr(sil, '_get_collection', lambda: _Coll())
    # Ask for 3 days explicitly in seconds (3*86400) – should cap to 1 day
    dsec = 3 * 86400
    doc = sil.create_silence(pattern='Cap', duration_seconds=dsec, created_by=42)
    assert doc is not None
    delta = stored['doc']['until_ts'] - stored['doc']['created_at']
    assert delta <= timedelta(days=1) and delta.total_seconds() > 0


def test_is_silenced_exception_continue_branch(monkeypatch):
    import monitoring.silences as sil
    monkeypatch.setenv('ALERTS_DB_ENABLED', '1')
    class BadItem:
        def get(self, *a, **k):
            raise RuntimeError('boom')
    good = {'pattern': 'OK.*', 'severity': ''}
    monkeypatch.setattr(sil, '_get_collection', lambda: object())
    monkeypatch.setattr(sil, '_iter_active', lambda c: [BadItem(), good])  # noqa: ARG005
    ok, it = sil.is_silenced('OK-name')
    assert ok is True and it is good


def test_unsilence_by_id_uses_matched_count(monkeypatch):
    import monitoring.silences as sil
    monkeypatch.setenv('ALERTS_DB_ENABLED', '1')
    class _Coll:
        def update_one(self, q, u):  # noqa: ARG001
            return types.SimpleNamespace(matched_count=1, modified_count=0)
    monkeypatch.setattr(sil, '_get_collection', lambda: _Coll())
    assert sil.unsilence_by_id('abc') is True


def test_unsilence_by_pattern_success(monkeypatch):
    import monitoring.silences as sil
    monkeypatch.setenv('ALERTS_DB_ENABLED', '1')
    class _Coll:
        def update_many(self, q, u):  # noqa: ARG001
            return types.SimpleNamespace(modified_count=3)
    monkeypatch.setattr(sil, '_get_collection', lambda: _Coll())
    assert sil.unsilence_by_pattern('P') == 3
