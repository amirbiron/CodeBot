import types
import pytest

import search_engine as se


class _Perf:
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False


def test_regex_search_iterative_pages(monkeypatch):
    # 3 עמודים של 2 פריטים כל אחד
    docs = [
        {"file_name": "f1.py", "code": "hello world"},
        {"file_name": "f2.py", "code": "lorem ipsum"},
        {"file_name": "f3.py", "code": "world peace"},
        {"file_name": "f4.py", "code": "another line"},
        {"file_name": "f5.py", "code": "worldwide web"},
        {"file_name": "f6.py", "code": "no match"},
    ]
    class _DB:
        def get_user_files(self, user_id, limit=200, skip=0, projection=None):
            return docs[skip: skip + 2]
    monkeypatch.setattr(se, 'db', _DB(), raising=False)
    monkeypatch.setattr(se, 'track_performance', lambda *a, **k: _Perf(), raising=False)

    eng = se.AdvancedSearchEngine()
    res = eng._regex_search("world", user_id=1)
    # אמור למצוא f1,f3,f5
    names = sorted([r.file_name for r in res])
    assert names == ["f1.py", "f3.py", "f5.py"]


def test_content_search_iterative_pages(monkeypatch):
    docs = [
        {"file_name": "f1.py", "code": "abc def"},
        {"file_name": "f2.py", "code": "xxx abc yyy"},
        {"file_name": "f3.py", "code": "nope"},
        {"file_name": "f4.py", "code": "abc"},
    ]
    class _DB:
        def get_user_files(self, user_id, limit=200, skip=0, projection=None):
            return docs[skip: skip + 2]
    monkeypatch.setattr(se, 'db', _DB(), raising=False)
    monkeypatch.setattr(se, 'track_performance', lambda *a, **k: _Perf(), raising=False)

    eng = se.AdvancedSearchEngine()
    res = eng._content_search("abc", user_id=1)
    names = sorted([r.file_name for r in res])
    assert names == ["f1.py", "f2.py", "f4.py"]
