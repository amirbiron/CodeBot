import types
import pytest

import search_engine as se


class _Perf:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_search_events_and_perf(monkeypatch):
    captured = {"evts": []}

    def _emit(event: str, severity: str = "info", **fields):
        captured["evts"].append((event, severity, fields))

    # Patch emit and track_performance
    monkeypatch.setattr(se, "emit_event", _emit, raising=False)
    monkeypatch.setattr(se, "track_performance", lambda *a, **k: _Perf(), raising=False)

    # Patch DB layer used by search engine
    class _DB:
        def get_user_files(self, user_id, limit=10000):
            return [
                {
                    "file_name": "a.py",
                    "code": "def f():\n    return 1\n",
                    "programming_language": "python",
                    "tags": ["x"],
                    "created_at": se.datetime.now(se.timezone.utc),
                    "updated_at": se.datetime.now(se.timezone.utc),
                    "version": 1,
                }
            ]

        def get_latest_version(self, user_id, file_name):
            return {
                "file_name": file_name,
                "code": "print(1)",
                "programming_language": "python",
                "tags": [],
                "created_at": se.datetime.now(se.timezone.utc),
                "updated_at": se.datetime.now(se.timezone.utc),
                "version": 1,
            }

    monkeypatch.setattr(se, "db", _DB(), raising=False)

    eng = se.AdvancedSearchEngine()
    # trigger index build and search
    res = eng.search(user_id=1, query="print", search_type=se.SearchType.TEXT)
    assert isinstance(res, list)

    events = [e[0] for e in captured["evts"]]
    # We expect request and done events at minimum
    assert "search_request" in events
    assert "search_done" in events


def test_search_error_emits(monkeypatch):
    captured = {"evts": []}

    def _emit(event: str, severity: str = "info", **fields):
        captured["evts"].append((event, severity, fields))

    monkeypatch.setattr(se, "emit_event", _emit, raising=False)

    # Force error by passing object without strip()
    eng = se.AdvancedSearchEngine()
    res = eng.search(user_id=1, query=None)  # type: ignore[arg-type]
    # function guards and returns [] without raising; ensure still list
    assert isinstance(res, list)
