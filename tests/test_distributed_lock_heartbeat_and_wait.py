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


def test_lock_heartbeat_does_not_extend_local_expiry_on_failure(monkeypatch):
    import main as mod

    class _Coll:
        def update_one(self, *a, **k):  # noqa: ANN001
            raise RuntimeError("network blip")

    hb = mod._MongoLockHeartbeat(  # type: ignore[attr-defined]
        lock_collection=_Coll(),
        service_id="svc",
        owner_id="owner-1",
        host_label="host",
        lease_seconds=60,
        interval_seconds=5.0,
    )

    # simulate already-expired local lease (last successful refresh was long ago)
    hb._local_expires_at = mod._utcnow() - mod.timedelta(seconds=5)  # type: ignore[attr-defined]

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


def test_heartbeat_sleep_shortens_near_expiry(monkeypatch):
    import main as mod

    class _Coll:
        def update_one(self, *a, **k):  # noqa: ANN001
            raise RuntimeError("unused")

    hb = mod._MongoLockHeartbeat(  # type: ignore[attr-defined]
        lock_collection=_Coll(),
        service_id="svc",
        owner_id="owner-1",
        host_label="host",
        lease_seconds=60,
        interval_seconds=24.0,
    )

    base = mod.datetime(2026, 1, 1, tzinfo=mod.timezone.utc)
    hb._local_expires_at = base + mod.timedelta(seconds=12)  # type: ignore[attr-defined]

    # remaining=12s, guard=2s => should sleep ~10s (not 24s)
    assert hb._compute_next_sleep_seconds(now=base) == 10.0  # type: ignore[attr-defined]

    # far from expiry => sleep interval
    hb._local_expires_at = base + mod.timedelta(seconds=120)  # type: ignore[attr-defined]
    assert hb._compute_next_sleep_seconds(now=base) == 24.0  # type: ignore[attr-defined]

    # at/after guard window => should request exit
    hb._local_expires_at = base + mod.timedelta(seconds=1)  # type: ignore[attr-defined]
    assert hb._should_exit_due_to_local_expiry(now=base) is True  # type: ignore[attr-defined]

