import importlib


def test_set_dynamic_applies_ttl_and_calls_set(monkeypatch):
    import cache_manager as cm
    importlib.reload(cm)

    mgr = cm.CacheManager()
    mgr.is_enabled = True

    captured = {"key": None, "value": None, "ttl": None}

    def _fake_set(key, value, expire_seconds=300):  # noqa: ARG001
        captured["key"] = key
        captured["value"] = value
        captured["ttl"] = expire_seconds
        return True

    # Avoid real redis client usage
    mgr.redis_client = None
    mgr.set = _fake_set  # type: ignore

    ok = mgr.set_dynamic(
        key="k",
        value={"ok": True},
        content_type="user_stats",
        context={"user_tier": "premium", "access_frequency": "high"},
    )
    assert ok is True
    assert captured["ttl"] is not None
    # TTL should be within clamp bounds
    assert 30 <= int(captured["ttl"]) <= 7200
