import types
import time

import pytest

import services.google_drive_service as gds


class _Svc:
    def __init__(self, name):
        self.name = name


@pytest.mark.asyncio
async def test_get_drive_service_caches_by_user(monkeypatch):
    # Ensure build exists and returns a distinct object per invocation
    builds = {"count": 0}

    def _fake_build(*a, **k):
        builds["count"] += 1
        return _Svc(f"svc-{builds['count']}")

    # Pretend credentials are valid
    monkeypatch.setattr(gds, "build", _fake_build, raising=True)
    owners = []

    def _fake_credentials(uid, *, owner):
        owners.append(owner)
        return object()

    monkeypatch.setattr(gds, "_ensure_valid_credentials", _fake_credentials, raising=True)

    # Clear cache
    try:
        gds._SERVICE_CACHE.clear()
    except Exception:
        gds._SERVICE_CACHE = {}

    s1 = gds.get_drive_service(7, owner="bot")
    s2 = gds.get_drive_service(7, owner="bot")
    s3 = gds.get_drive_service(8, owner="bot")
    assert set(owners) == {"bot"}

    # Same user returns cached object; different user builds a new one
    assert isinstance(s1, _Svc)
    assert s1 is s2
    assert isinstance(s3, _Svc)
    assert s3 is not s1

    # build should be called twice (user 7 once, user 8 once)
    assert builds["count"] == 2

    # Expire cache by adjusting timestamp and ensure rebuild
    # Move user 7 cache time to older than 5 minutes — under the same key get_drive_service uses
    gds._SERVICE_CACHE[gds._service_cache_key(7, owner="bot")] = (s1, time.time() - 4000)
    s4 = gds.get_drive_service(7, owner="bot")
    assert s4 is not s1
    assert builds["count"] == 3
