import types
import time

import pytest

import services.google_drive_service as gds


class _Svc:
    def __init__(self, name):
        self.name = name


def _creds(token="access-1", refresh="refresh-1"):
    """השדות ש-``get_drive_service`` קורא מ-``google.oauth2.credentials.Credentials``."""
    return types.SimpleNamespace(token=token, refresh_token=refresh)


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
        return _creds()

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
    # Move user 7 cache time to older than 5 minutes — under the same key get_drive_service uses, with the same fingerprint
    key = gds._service_cache_key(7, owner="bot")
    svc, _built_at, fingerprint = gds._SERVICE_CACHE[key]
    gds._SERVICE_CACHE[key] = (svc, time.time() - 4000, fingerprint)
    s4 = gds.get_drive_service(7, owner="bot")
    assert s4 is not s1
    assert builds["count"] == 3


def test_a_service_built_from_replaced_tokens_is_not_returned(monkeypatch):
    """חיבור מחדש — או רענון שנשמר — מחליף את הטוקנים במסד. שירות שנבנה מהטוקנים הקודמים לא מוחזר מהמטמון, גם בתוך חמש הדקות שלו ובלי שאיש ביטל אותו.

    זה גם המקרה שביטול ב-``save_tokens`` היה מחטיא: קריאה שטענה את הטוקנים הישנים לפני הכתיבה ושמרה את השירות שלה אחריה. כאן המטמון מחזיק שירות מהטוקנים הישנים, והטוקנים במסד כבר חדשים.
    """
    built_from = []

    def _fake_build(*_a, credentials=None, **_k):
        built_from.append(credentials)
        return _Svc(f"svc-{len(built_from)}")

    current = {"creds": _creds("access-old", "refresh-old")}
    monkeypatch.setattr(gds, "build", _fake_build, raising=True)
    monkeypatch.setattr(gds, "_ensure_valid_credentials", lambda uid, *, owner: current["creds"], raising=True)
    monkeypatch.setattr(gds, "_SERVICE_CACHE", {})

    old = gds.get_drive_service(7, owner="webapp")
    assert gds.get_drive_service(7, owner="webapp") is old

    current["creds"] = _creds("access-new", "refresh-new")
    new = gds.get_drive_service(7, owner="webapp")

    assert new is not old
    assert built_from[-1] is current["creds"]
    assert gds.get_drive_service(7, owner="webapp") is new


def test_a_new_refresh_token_alone_also_rebuilds_the_service(monkeypatch):
    """הטביעה כוללת גם את ה-refresh token, ולא רק את ה-access token: כשרק הוא הוחלף, השירות נבנה מחדש."""
    current = {"creds": _creds("access-same", "refresh-old")}
    monkeypatch.setattr(gds, "build", lambda *_a, **_k: _Svc("svc"), raising=True)
    monkeypatch.setattr(gds, "_ensure_valid_credentials", lambda uid, *, owner: current["creds"], raising=True)
    monkeypatch.setattr(gds, "_SERVICE_CACHE", {})

    old = gds.get_drive_service(9, owner="bot")
    current["creds"] = _creds("access-same", "refresh-new")
    assert gds.get_drive_service(9, owner="bot") is not old
