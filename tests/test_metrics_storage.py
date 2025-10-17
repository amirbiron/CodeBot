import importlib
import sys
import types

import pytest


def _set_env(monkeypatch, **env):
    keys = [
        "DISABLE_DB",
        "METRICS_DB_ENABLED",
        "MONGODB_URL",
        "DATABASE_NAME",
        "METRICS_COLLECTION",
        "METRICS_BATCH_SIZE",
        "METRICS_FLUSH_INTERVAL_SEC",
    ]
    for k in keys:
        if k in env and env[k] is not None:
            monkeypatch.setenv(k, str(env[k]))
        else:
            monkeypatch.delenv(k, raising=False)


def _install_observability_stub(monkeypatch, bucket):
    def _emit(event, severity="info", **fields):
        bucket.append((event, severity, fields))
    obs = types.SimpleNamespace(emit_event=_emit)
    monkeypatch.setitem(sys.modules, "observability", obs)


def _install_fake_pymongo(monkeypatch, *, fail_insert=False, calls_out=None):
    """Install a minimal pymongo stub that metrics_storage expects.

    - fail_insert=True makes insert_many raise to exercise error path
    - calls_out: list to collect insert_many payloads for assertions
    """
    calls_out = calls_out if calls_out is not None else []

    class _FakeCollection:
        def insert_many(self, items, ordered=False):  # noqa: D401
            if fail_insert:
                raise RuntimeError("boom")
            calls_out.append(list(items))
            return types.SimpleNamespace(inserted_ids=[1] * len(items))

    class _FakeDB:
        def __getitem__(self, name):
            return _FakeCollection()

    class _FakeAdmin:
        def command(self, *a, **k):
            return {"ok": 1}

    class _FakeClient:
        def __init__(self, *a, **k):
            self.admin = _FakeAdmin()
        def __getitem__(self, name):
            return _FakeDB()

    fake = types.SimpleNamespace(MongoClient=_FakeClient)
    monkeypatch.setitem(sys.modules, "pymongo", fake)
    return calls_out


def _import_fresh_metrics_storage(monkeypatch):
    sys.modules.pop("monitoring.metrics_storage", None)
    return importlib.import_module("monitoring.metrics_storage")


def test_metrics_storage_noop_when_disabled(monkeypatch):
    _set_env(monkeypatch, DISABLE_DB=None, METRICS_DB_ENABLED="false")
    events = []
    _install_observability_stub(monkeypatch, events)
    ms = _import_fresh_metrics_storage(monkeypatch)

    # Should not raise and should short-circuit when disabled
    ms.enqueue_request_metric(200, 0.123, request_id="rid")
    ms.flush(force=True)
    # No specific event required; just ensure code path executes safely
    assert isinstance(events, list)


def test_metrics_storage_emits_on_missing_pymongo(monkeypatch):
    _set_env(
        monkeypatch,
        METRICS_DB_ENABLED="true",
        MONGODB_URL="mongodb://localhost:27017/codebot",
        DATABASE_NAME="code_keeper_bot",
    )
    events = []
    _install_observability_stub(monkeypatch, events)
    # Ensure pymongo import fails inside module: provide a module without MongoClient
    monkeypatch.setitem(sys.modules, "pymongo", types.SimpleNamespace())

    ms = _import_fresh_metrics_storage(monkeypatch)
    ms.enqueue_request_metric(200, 0.111, request_id="x")
    ms.flush(force=True)

    assert any(e[0] == "metrics_db_pymongo_missing" for e in events)


def test_metrics_storage_emits_on_missing_url(monkeypatch):
    _set_env(monkeypatch, METRICS_DB_ENABLED="true", MONGODB_URL=None)
    events = []
    _install_observability_stub(monkeypatch, events)
    _install_fake_pymongo(monkeypatch)  # import succeeds but URL is missing

    ms = _import_fresh_metrics_storage(monkeypatch)
    ms.enqueue_request_metric(201, 0.222, request_id="y")
    ms.flush(force=True)

    assert any(e[0] == "metrics_db_missing_url" for e in events)


def test_metrics_storage_batch_insert_success(monkeypatch):
    _set_env(
        monkeypatch,
        METRICS_DB_ENABLED="true",
        MONGODB_URL="mongodb://localhost:27017/codebot",
        DATABASE_NAME="code_keeper_bot",
        METRICS_COLLECTION="service_metrics_test",
        METRICS_BATCH_SIZE="2",
    )
    events = []
    _install_observability_stub(monkeypatch, events)
    calls = _install_fake_pymongo(monkeypatch, fail_insert=False, calls_out=[])

    ms = _import_fresh_metrics_storage(monkeypatch)
    # First enqueue should not flush (batch size=2)
    ms.enqueue_request_metric(200, 0.100, request_id="r1")
    assert len(calls) == 0
    # Second enqueue triggers flush
    ms.enqueue_request_metric(200, 0.200, request_id="r2")
    assert len(calls) >= 1
    assert sum(len(b) for b in calls) >= 2
    # Initialized event should be emitted once
    assert any(e[0] == "metrics_db_initialized" for e in events)


def test_metrics_storage_batch_insert_failure_emits_event(monkeypatch):
    _set_env(
        monkeypatch,
        METRICS_DB_ENABLED="true",
        MONGODB_URL="mongodb://localhost:27017/codebot",
        DATABASE_NAME="code_keeper_bot",
        METRICS_BATCH_SIZE="2",
    )
    events = []
    _install_observability_stub(monkeypatch, events)
    _install_fake_pymongo(monkeypatch, fail_insert=True, calls_out=[])

    ms = _import_fresh_metrics_storage(monkeypatch)
    ms.enqueue_request_metric(500, 0.300, request_id="e1")
    ms.enqueue_request_metric(500, 0.400, request_id="e2")  # triggers flush and failure
    # Force another flush to exercise re-queue path safely
    ms.flush(force=True)

    assert any(e[0] == "metrics_db_batch_insert_error" for e in events)
