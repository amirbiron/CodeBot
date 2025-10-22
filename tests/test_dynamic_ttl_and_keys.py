import re
from typing import Any

import importlib


def test_build_cache_key_truncates_and_hashes_sha256():
    import cache_manager as cm
    importlib.reload(cm)

    # Build a very long key (over 200 chars) to trigger hashing
    long_part = "x" * 210
    key = cm.build_cache_key(long_part)

    # Expected format: first 150 chars + ':' + 8 hex (sha256 prefix)
    assert len(key) <= 159
    assert re.match(r"^[^:]{1,150}:[0-9a-f]{8}$", key) is not None


def test_build_cache_key_sanitizes_spaces_and_slashes():
    import cache_manager as cm
    key = cm.build_cache_key("a b", "/x")
    assert key == "a_b:-x"


def test_dynamic_ttl_context_adjustments_order_and_clamp():
    import cache_manager as cm
    # Base for user_stats is 300. Apply adjustments in documented order.
    ttl = cm.DynamicTTL.calculate_ttl(
        "user_stats",
        {
            "is_favorite": True,                 # *1.5 => 450
            "last_modified_hours_ago": 0.1,      # *0.5 => 225
            "access_frequency": "high",         # *2   => 450
            "user_tier": "premium",             # *0.7 => 315
        },
    )
    assert ttl == 315

    # Clamp to minimum 30
    ttl_min = cm.DynamicTTL.calculate_ttl(
        "settings",  # base 60
        {
            "last_modified_hours_ago": 0.5,      # 60 * 0.5 = 30
            "user_tier": "premium",             # 30 * 0.7 = 21 -> clamp to 30
        },
    )
    assert ttl_min == 30


def test_activity_based_ttl_adjustment_with_deterministic_jitter(monkeypatch):
    import cache_manager as cm

    # Make multiplier deterministic and neutral
    monkeypatch.setattr(cm.ActivityBasedTTL, "get_activity_multiplier", classmethod(lambda cls: 1.0))
    # Eliminate jitter
    monkeypatch.setattr(cm.random, "randint", lambda a, b: 0)

    assert cm.ActivityBasedTTL.adjust_ttl(100) == 100
    # Clamp low
    assert cm.ActivityBasedTTL.adjust_ttl(5) == 30
    # Clamp high
    assert cm.ActivityBasedTTL.adjust_ttl(10000) == 7200
