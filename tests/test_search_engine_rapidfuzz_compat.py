import types
import pytest

import search_engine as se


class _Perf:
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False


def _fake_db_single_file(text: str = "hello world", tags=None):
    tags = tags or ["t"]
    class _DB:
        def get_user_files(self, user_id, limit=10000):
            return [
                {
                    "file_name": "x.txt",
                    "code": text,
                    "programming_language": "text",
                    "tags": tags,
                    "created_at": se.datetime.now(se.timezone.utc),
                    "updated_at": se.datetime.now(se.timezone.utc),
                    "version": 1,
                }
            ]
        def get_latest_version(self, user_id, file_name):
            return {
                "file_name": file_name,
                "code": text,
                "programming_language": "text",
                "tags": tags,
                "created_at": se.datetime.now(se.timezone.utc),
                "updated_at": se.datetime.now(se.timezone.utc),
                "version": 1,
            }
    return _DB()


def test_fuzzy_search_with_stubbed_fuzz(monkeypatch):
    # מוודא שמסלול fuzzy עובד עם הממשק (rapidfuzz/fuzzywuzzy)
    monkeypatch.setattr(se, "db", _fake_db_single_file("abc def"), raising=False)
    monkeypatch.setattr(se, "track_performance", lambda *a, **k: _Perf(), raising=False)
    # החזר ערך קבוע כדי לעבור את סף 60
    monkeypatch.setattr(se.fuzz, "partial_ratio", lambda a, b: 80, raising=False)

    eng = se.AdvancedSearchEngine()
    res = eng.search(user_id=1, query="abc", search_type=se.SearchType.FUZZY)
    assert isinstance(res, list)
    assert len(res) == 1


def test_function_search_similarity_works(monkeypatch):
    # בודק שהשוואת ratio פועלת במסלול FUNCTION
    monkeypatch.setattr(se, "track_performance", lambda *a, **k: _Perf(), raising=False)
    monkeypatch.setattr(se.fuzz, "ratio", lambda a, b: 90, raising=False)

    eng = se.AdvancedSearchEngine()
    idx = se.SearchIndex()
    idx.function_index["funcname"].add("1:file.py")
    monkeypatch.setattr(eng, "get_index", lambda _uid: idx)

    # החזר אובייקט גרסה אחרונה כאשר יידרש
    monkeypatch.setattr(
        se,
        "db",
        types.SimpleNamespace(
            get_latest_version=lambda *_a, **_k: {
                "file_name": "file.py",
                "code": "def funcName():\n  pass",
                "programming_language": "python",
                "tags": [],
                "created_at": se.datetime.now(se.timezone.utc),
                "updated_at": se.datetime.now(se.timezone.utc),
                "version": 1,
            },
            get_user_files=lambda *_a, **_k: [],
        ),
        raising=False,
    )

    res = eng.search(user_id=1, query="funcName", search_type=se.SearchType.FUNCTION)
    assert isinstance(res, list)
    assert len(res) == 1
