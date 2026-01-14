import pytest


def test_lock_heartbeat_ownership_loss_exits(monkeypatch):
    import main as mod

    class _Res:
        matched_count = 0

    class _Coll:
        def update_one(self, *a, **k):  # noqa: ANN001
            return _Res()

    hb = mod._MongoLockHeartbeat(  # type: ignore[attr-defined]
        lock_collection=_Coll(),
        service_id="svc",
        owner_id="owner-1",
        host_label="host",
        lease_seconds=60,
        interval_seconds=5.0,
    )

    class ExitNow(BaseException):
        pass

    monkeypatch.setattr(mod.os, "_exit", lambda _code=0: (_ for _ in ()).throw(ExitNow()))

    with pytest.raises(ExitNow):
        hb._tick_once()  # type: ignore[attr-defined]


def test_manage_mongo_lock_active_wait_times_out(monkeypatch):
    import main as mod

    # deterministic time progression without real sleeping
    t = {"v": 0.0}

    def _mono():
        t["v"] += 0.6
        return t["v"]

    monkeypatch.setattr(mod.time, "monotonic", _mono)
    monkeypatch.setattr(mod.time, "sleep", lambda *_a, **_k: None)

    monkeypatch.setenv("LOCK_WAIT_FOR_ACQUIRE", "true")
    monkeypatch.setenv("LOCK_ACQUIRE_MAX_WAIT", "1")
    monkeypatch.setenv("LOCK_WAIT_HEALTH_SERVER_ENABLED", "false")  # avoid binding a port in tests

    monkeypatch.setattr(mod, "ensure_lock_indexes", lambda: None, raising=False)

    class _Coll:
        def insert_one(self, *a, **k):  # noqa: ANN001
            raise mod.DuplicateKeyError("dup")

        def find_one_and_update(self, *a, **k):  # noqa: ANN001
            return None

    monkeypatch.setattr(mod, "get_lock_collection", lambda: _Coll(), raising=False)

    ok = mod.manage_mongo_lock()
    assert ok is False


def test_passive_wait_jitter_deterministic_when_uniform_patched(monkeypatch):
    import main as mod

    monkeypatch.setattr(mod.random, "uniform", lambda a, b: 23.5)  # noqa: ARG005
    assert mod._compute_passive_wait_seconds(15.0, 45.0) == 23.5

