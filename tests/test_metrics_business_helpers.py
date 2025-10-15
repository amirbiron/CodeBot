import types

import metrics as m


def test_track_file_saved_emits_event_and_counter(monkeypatch):
    captured = {}

    def _emit(event, **fields):
        captured["event"] = event
        captured.update(fields)

    class _Counter:
        def __init__(self):
            self.count = 0
        def labels(self, **kw):
            # ensure metric label is present
            assert kw.get("metric") == "file_saved"
            return self
        def inc(self):
            self.count += 1

    ctr = _Counter()
    monkeypatch.setattr(m, "emit_event", _emit)
    monkeypatch.setattr(m, "business_events_total", ctr)

    m.track_file_saved(user_id=1, language="python", size_bytes=123)

    assert captured.get("event") == "business_metric"
    assert captured.get("metric") == "file_saved"
    assert ctr.count == 1


def test_track_search_performed_privacy_and_counter(monkeypatch):
    captured = {}

    def _emit(event, **fields):
        captured["event"] = event
        captured.update(fields)

    class _Counter:
        def __init__(self):
            self.count = 0
        def labels(self, **kw):
            assert kw.get("metric") == "search"
            return self
        def inc(self):
            self.count += 1

    ctr = _Counter()
    monkeypatch.setattr(m, "emit_event", _emit)
    monkeypatch.setattr(m, "business_events_total", ctr)

    m.track_search_performed(user_id=2, query="secret query", results_count=7)

    assert captured.get("event") == "business_metric"
    assert captured.get("metric") == "search"
    # Privacy: do not expose the raw query field
    assert "query" not in captured
    assert captured.get("query_length") == len("secret query")
    assert ctr.count == 1


def test_track_github_sync_emits_event_and_counter(monkeypatch):
    captured = {}

    def _emit(event, **fields):
        captured["event"] = event
        captured.update(fields)

    class _Counter:
        def __init__(self):
            self.count = 0
        def labels(self, **kw):
            assert kw.get("metric") == "github_sync"
            return self
        def inc(self):
            self.count += 1

    ctr = _Counter()
    monkeypatch.setattr(m, "emit_event", _emit)
    monkeypatch.setattr(m, "business_events_total", ctr)

    m.track_github_sync(user_id=3, files_count=5, success=True)

    assert captured.get("event") == "business_metric"
    assert captured.get("metric") == "github_sync"
    assert captured.get("files_count") == 5
    assert captured.get("success") is True
    assert ctr.count == 1
