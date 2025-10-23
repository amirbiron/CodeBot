import os
import types
import importlib
from datetime import datetime, timezone


def test_enabled_flags_and_fail_open(monkeypatch):
    import monitoring.silences as sil
    import importlib as _il
    # DISABLE_DB => everything fails open
    monkeypatch.setenv('DISABLE_DB', '1')
    _il.reload(sil)
    assert sil._enabled() is False  # noqa: SLF001
    assert sil.create_silence(pattern='X', duration_seconds=60, created_by=1) is None
    assert sil.is_silenced('X') == (False, None)
    assert sil.unsilence_by_id('a') is False
    assert sil.unsilence_by_pattern('X') == 0
    assert sil.list_active_silences() == []


def test_parse_duration_zero_is_invalid():
    import monitoring.silences as sil
    assert sil.parse_duration_to_seconds('0s') is None
    assert sil.parse_duration_to_seconds('0m') is None


def test_max_active_allowed_invalid_env(monkeypatch):
    import monitoring.silences as sil
    # Invalid value => default 50
    monkeypatch.setenv('SILENCES_MAX_ACTIVE', 'abc')
    assert sil._max_active_allowed() == 50  # noqa: SLF001


def test_create_silence_empty_pattern_and_no_collection(monkeypatch):
    import monitoring.silences as sil
    # Empty pattern
    assert sil.create_silence(pattern='  ', duration_seconds=10, created_by=1) is None
    # _get_collection returns None
    monkeypatch.setattr(sil, '_get_collection', lambda: None)
    # Enable DB
    monkeypatch.setenv('ALERTS_DB_ENABLED', '1')
    assert sil.create_silence(pattern='X', duration_seconds=10, created_by=1) is None


def test_create_silence_insert_failure(monkeypatch):
    import monitoring.silences as sil
    monkeypatch.setenv('ALERTS_DB_ENABLED', '1')
    class _Coll:
        def count_documents(self, q):  # noqa: ARG001
            return 0
        def insert_one(self, doc):  # noqa: ARG001
            raise RuntimeError('boom')
    monkeypatch.setattr(sil, '_get_collection', lambda: _Coll())
    assert sil.create_silence(pattern='X', duration_seconds=10, created_by=1) is None


def test_list_active_silences_error_and_disabled(monkeypatch):
    import monitoring.silences as sil
    # Disabled
    monkeypatch.setenv('DISABLE_DB', '1')
    assert sil.list_active_silences() == []
    # Error in _iter_active path
    monkeypatch.delenv('DISABLE_DB', raising=False)
    monkeypatch.setenv('ALERTS_DB_ENABLED', '1')
    class _Bad:
        def find(self, *a, **k):  # noqa: ARG001
            raise RuntimeError('x')
    # Force _get_collection to return bad coll
    monkeypatch.setattr(sil, '_get_collection', lambda: _Bad())
    # Should swallow and return [] via _iter_active except
    assert sil.list_active_silences() == []


def test_is_silenced_coll_none_and_empty(monkeypatch):
    import monitoring.silences as sil
    monkeypatch.setenv('ALERTS_DB_ENABLED', '1')
    # coll None => False
    monkeypatch.setattr(sil, '_get_collection', lambda: None)
    assert sil.is_silenced('X') == (False, None)
    # empty items => False
    def _no_items(*a, **k):  # noqa: ARG001
        return []
    monkeypatch.setattr(sil, '_get_collection', lambda: object())
    monkeypatch.setattr(sil, '_iter_active', _no_items)
    assert sil.is_silenced('X') == (False, None)


def test_unsilence_by_id_and_pattern_zero(monkeypatch):
    import monitoring.silences as sil
    monkeypatch.setenv('ALERTS_DB_ENABLED', '1')
    # coll None
    monkeypatch.setattr(sil, '_get_collection', lambda: None)
    assert sil.unsilence_by_id('a') is False
    assert sil.unsilence_by_pattern('X') == 0
    # No changes
    class _Coll:
        def update_one(self, q, u):  # noqa: ARG001
            return types.SimpleNamespace(modified_count=0, matched_count=0)
        def update_many(self, q, u):  # noqa: ARG001
            return types.SimpleNamespace(modified_count=0)
    monkeypatch.setattr(sil, '_get_collection', lambda: _Coll())
    assert sil.unsilence_by_id('a') is False
    assert sil.unsilence_by_pattern('X') == 0
