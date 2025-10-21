import types
import pytest

import autocomplete_manager as am


def test_get_user_filenames_projection_fallback(monkeypatch):
    # DB שמקבל רק (user_id, limit) כמו בסטאבים ישנים
    class _DBLegacy:
        def get_user_files(self, user_id, limit=1000):
            return [{"file_name": "a.py"}, {"file_name": "b.py"}]

    monkeypatch.setattr(am, "db", _DBLegacy(), raising=False)

    mgr = am.AutocompleteManager()
    res = mgr.get_user_filenames(user_id=1)
    assert res == ["a.py", "b.py"]


def test_get_user_tags_projection_fallback(monkeypatch):
    class _DBLegacy:
        def get_user_files(self, user_id, limit=1000):
            return [{"tags": ["x", "y"]}, {"tags": ["y", "z"]}]

    monkeypatch.setattr(am, "db", _DBLegacy(), raising=False)

    mgr = am.AutocompleteManager()
    tags = mgr.get_user_tags(user_id=1)
    assert set(tags) == {"x", "y", "z"}
