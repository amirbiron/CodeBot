import importlib


def test_fetch_alerts_tags_map_uid_fallback_stringifies_id(monkeypatch):
    """
    בדיקה ממוקדת: ה-UI מחפש תגיות במפה לפי מפתח str.

    בפועל, לפעמים מגיעים מזהים מסוג int/ObjectId וכו'. לכן אנחנו מוודאים
    שהמיזוג בדשבורד ממיר ל-str (כמו ב-storage) לפני ה-lookup.
    """
    svc = importlib.import_module("services.observability_dashboard")

    # avoid cache affecting assertions
    monkeypatch.setattr(svc, "_cache_get", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(svc, "_cache_set", lambda *_a, **_k: None, raising=True)

    # provide one alert with a non-string ID
    def _fake_fetch_alerts(**_kwargs):
        return (
            [
                {
                    "id": 123,
                    "timestamp": "2025-01-01T00:00:00Z",
                    "name": "CPU High",
                    "summary": "demo",
                    "alert_type": "cpu_high",
                    "severity": "critical",
                }
            ],
            1,
        )

    monkeypatch.setattr(svc.alerts_storage, "fetch_alerts", _fake_fetch_alerts, raising=True)
    monkeypatch.setattr(svc, "_fallback_alerts", lambda **_k: ([], 0), raising=True)

    # force a non-string alert_uid to simulate upstream variability
    monkeypatch.setattr(svc, "_build_alert_uid", lambda alert: alert.get("id"), raising=True)

    # keep fetch_alerts lightweight
    monkeypatch.setattr(svc, "get_quick_fix_actions", lambda *_a, **_k: [], raising=True)
    monkeypatch.setattr(svc, "_describe_alert_graph", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(
        svc.incident_story_storage,
        "get_stories_by_alert_uids",
        lambda _uids: {},
        raising=True,
    )

    # tags map keys are strings (as produced by storage)
    monkeypatch.setattr(
        svc.alert_tags_storage,
        "get_tags_map_for_alerts",
        lambda _alerts: {"123": ["tag-a"]},
        raising=True,
    )

    payload = svc.fetch_alerts(
        start_dt=None,
        end_dt=None,
        severity=None,
        alert_type=None,
        endpoint=None,
        search=None,
        page=1,
        per_page=50,
    )

    assert payload["total"] == 1
    assert payload["alerts"][0]["tags"] == ["tag-a"]


def test_set_alert_tags_invalidates_cache(monkeypatch):
    """
    בדיקה ש-set_alert_tags מנקה את ה-cache כדי שהתגיות יופיעו מיד אחרי רענון.
    """
    svc = importlib.import_module("services.observability_dashboard")

    # Track if cache was invalidated
    invalidation_calls = []

    def track_invalidation():
        invalidation_calls.append(True)

    monkeypatch.setattr(svc, "_invalidate_alert_cache", track_invalidation, raising=True)

    # Mock the storage to return success
    monkeypatch.setattr(
        svc.alert_tags_storage,
        "set_tags_for_alert",
        lambda **_k: {"alert_uid": "test-123", "tags": ["tag-a"], "upserted": True, "modified": False},
        raising=True,
    )

    result = svc.set_alert_tags(
        alert_uid="test-123",
        alert_timestamp="2025-01-01T00:00:00Z",
        tags=["tag-a"],
        user_id=None,
    )

    assert result["ok"] is True
    assert len(invalidation_calls) == 1, "Cache should be invalidated after set_alert_tags"


def test_set_global_alert_tags_invalidates_cache(monkeypatch):
    """
    בדיקה ש-set_global_alert_tags מנקה את ה-cache כדי שתגיות גלובליות יופיעו מיד.
    """
    svc = importlib.import_module("services.observability_dashboard")

    invalidation_calls = []

    def track_invalidation():
        invalidation_calls.append(True)

    monkeypatch.setattr(svc, "_invalidate_alert_cache", track_invalidation, raising=True)

    monkeypatch.setattr(
        svc.alert_tags_storage,
        "set_global_tags_for_name",
        lambda **_k: {"alert_type_name": "cpu_high", "tags": ["infra"], "upserted": True, "modified": False},
        raising=True,
    )

    result = svc.set_global_alert_tags(
        alert_name="cpu_high",
        tags=["infra"],
        user_id=None,
    )

    assert result["ok"] is True
    assert len(invalidation_calls) == 1, "Cache should be invalidated after set_global_alert_tags"


def test_add_alert_tag_invalidates_cache(monkeypatch):
    """
    בדיקה ש-add_alert_tag מנקה את ה-cache.
    """
    svc = importlib.import_module("services.observability_dashboard")

    invalidation_calls = []

    def track_invalidation():
        invalidation_calls.append(True)

    monkeypatch.setattr(svc, "_invalidate_alert_cache", track_invalidation, raising=True)

    monkeypatch.setattr(
        svc.alert_tags_storage,
        "add_tag_to_alert",
        lambda **_k: {"alert_uid": "test-123", "tags": ["tag-a", "tag-b"], "added": "tag-b"},
        raising=True,
    )

    result = svc.add_alert_tag(
        alert_uid="test-123",
        alert_timestamp="2025-01-01T00:00:00Z",
        tag="tag-b",
        user_id=None,
    )

    assert result["ok"] is True
    assert len(invalidation_calls) == 1, "Cache should be invalidated after add_alert_tag"


def test_remove_alert_tag_invalidates_cache(monkeypatch):
    """
    בדיקה ש-remove_alert_tag מנקה את ה-cache.
    """
    svc = importlib.import_module("services.observability_dashboard")

    invalidation_calls = []

    def track_invalidation():
        invalidation_calls.append(True)

    monkeypatch.setattr(svc, "_invalidate_alert_cache", track_invalidation, raising=True)

    monkeypatch.setattr(
        svc.alert_tags_storage,
        "remove_tag_from_alert",
        lambda uid, tag: {"alert_uid": uid, "tags": [], "removed": tag, "modified": True},
        raising=True,
    )

    result = svc.remove_alert_tag(
        alert_uid="test-123",
        tag="tag-a",
    )

    assert result["ok"] is True
    assert len(invalidation_calls) == 1, "Cache should be invalidated after remove_alert_tag"

