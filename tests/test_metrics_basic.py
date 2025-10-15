import asyncio
import pytest

import metrics as m


def test_metrics_helpers_are_callable():
    # Ensure helpers exist even if prometheus isn't installed
    assert callable(m.metrics_endpoint_bytes)
    assert isinstance(m.metrics_content_type(), str)


def test_track_performance_records_histogram(monkeypatch):
    observed = {"calls": 0}

    class _Hist:
        def labels(self, **kw):
            return self
        def observe(self, value):
            observed["calls"] += 1

    monkeypatch.setattr(m, "operation_latency_seconds", _Hist())

    with m.track_performance("save_file"):
        pass

    assert observed["calls"] == 1


def test_track_performance_ignores_operation_duplicate_label(monkeypatch):
    observed = {"args": None}

    class _Hist:
        _labelnames = ["operation", "env"]
        def labels(self, **kw):
            observed["args"] = kw
            return self
        def observe(self, value):
            pass

    monkeypatch.setattr(m, "operation_latency_seconds", _Hist())

    with m.track_performance("save_file", labels={"operation": "WRONG", "env": "prod", "extra": "x"}):
        pass

    # 'operation' must be forced from the function arg; 'env' passes through; 'extra' is ignored
    assert observed["args"] == {"operation": "save_file", "env": "prod"}
