import types
import pytest

import autocomplete_manager as am


def test_suggest_filenames_with_stubbed_scores(monkeypatch):
    # דמה DB
    fake_files = [
        {"file_name": "alpha.py"},
        {"file_name": "beta.py"},
        {"file_name": "notes.txt"},
    ]

    class _DB:
        def get_user_files(self, user_id, limit=1000):
            return fake_files

    monkeypatch.setattr(am, "db", _DB(), raising=False)
    # העמס מינימום ציון
    mgr = am.AutocompleteManager()
    mgr.min_similarity = 70

    # הנמך את הסף דרך החזרת ניקוד גבוה מהמנוע
    monkeypatch.setattr(am.fuzz, "partial_ratio", lambda a, b: 80, raising=False)
    # process.extract מחזיר רשימת tuples/objects; נשתמש במימוש הקיים בספרייה
    # כאן די ב-monkeypatch של scorer כדי שהדירוג יסתדר

    res = mgr.suggest_filenames(user_id=1, partial_name="alp", limit=5)
    assert isinstance(res, list)
    assert any(s["filename"] == "alpha.py" for s in res)


def test_suggest_tags_with_stubbed_scores(monkeypatch):
    # דמה DB
    fake_files = [
        {"tags": ["backend", "api"]},
        {"tags": ["frontend"]},
    ]

    class _DB:
        def get_user_files(self, user_id, limit=1000):
            return fake_files

    monkeypatch.setattr(am, "db", _DB(), raising=False)
    mgr = am.AutocompleteManager()
    mgr.min_similarity = 70

    monkeypatch.setattr(am.fuzz, "partial_ratio", lambda a, b: 85, raising=False)

    res = mgr.suggest_tags(user_id=1, partial_tag="back", limit=5)
    assert isinstance(res, list)
    assert any(s["tag"] == "backend" for s in res)
