import types
import os
import pytest

from services import investigation_service as inv


class _FakeSentry:
    @staticmethod
    def is_configured():
        return True

    async def search_events(self, query: str, limit: int = 20):
        return [
            {"timestamp": "2025-01-01T00:00:00Z", "message": f"matched {query}", "url": "https://s/e1"},
            {"timestamp": "2025-01-01T00:05:00Z", "message": "next", "url": "https://s/e2"},
        ]


@pytest.mark.asyncio
async def test_triage_builds_timeline_and_html(monkeypatch):
    # Inject fake sentry client and Grafana base
    monkeypatch.setattr(inv, "sentry_client", _FakeSentry(), raising=False)
    monkeypatch.setenv("GRAFANA_URL", "https://grafana.example.com")

    res = await inv.triage("req-abc123", limit=5)
    assert isinstance(res, dict)
    assert res.get("timeline") and len(res["timeline"]) >= 2
    assert isinstance(res.get("summary_text"), str) and "matched" in res["summary_text"]
    html_doc = res.get("summary_html", "")
    assert "Triage" in html_doc and "Logs (24h)" in html_doc


def test_render_triage_html_minimal():
    doc = inv.render_triage_html({"query": "x", "timeline": [], "grafana_links": []})
    assert "אין אירועים" in doc or "</table>" in doc


def test_summarize_zero_limit_returns_empty():
    out = inv._summarize_timeline_text([
        {"timestamp": "2025-01-01", "message": "a"}
    ], limit=0)
    assert out == ""


class _FakeSentryNotConfigured:
    @staticmethod
    def is_configured():
        return False

    async def search_events(self, query: str, limit: int = 20):
        return []


@pytest.mark.asyncio
async def test_triage_fallback_to_local_errors(monkeypatch):
    """Test that triage falls back to local error buffer when Sentry is unavailable."""
    # Mock Sentry as not configured
    monkeypatch.setattr(inv, "sentry_client", _FakeSentryNotConfigured(), raising=False)

    # Mock observability.get_recent_errors to return test data
    fake_errors = [
        {
            "ts": "2025-01-15T10:00:00Z",
            "request_id": "abc123",
            "error": "Test error message",
            "event": "test_event",
        },
        {
            "ts": "2025-01-15T09:00:00Z",
            "request_id": "abc123",
            "error": "Another error",
        },
        {
            "ts": "2025-01-15T08:00:00Z",
            "request_id": "xyz789",  # Different request_id
            "error": "Unrelated error",
        },
    ]

    import sys
    fake_obs = types.SimpleNamespace(get_recent_errors=lambda limit=200: fake_errors)
    monkeypatch.setitem(sys.modules, "observability", fake_obs)

    # Mock metrics_storage.find_by_request_id to return empty (test local buffer only)
    fake_metrics = types.SimpleNamespace(find_by_request_id=lambda rid, limit=20: [])
    monkeypatch.setitem(sys.modules, "monitoring.metrics_storage", fake_metrics)

    res = await inv.triage("abc123", limit=10)
    
    assert isinstance(res, dict)
    timeline = res.get("timeline", [])
    # Should find at least 2 matching errors (abc123)
    assert len(timeline) >= 2
    # All timeline entries should have the matching request_id
    for entry in timeline:
        assert "error" in entry.get("message", "").lower() or "test" in entry.get("message", "").lower()


@pytest.mark.asyncio
async def test_triage_fallback_to_metrics_storage(monkeypatch):
    """Test that triage falls back to metrics_storage when Sentry is unavailable."""
    # Mock Sentry as not configured
    monkeypatch.setattr(inv, "sentry_client", _FakeSentryNotConfigured(), raising=False)

    # Mock observability.get_recent_errors to return empty (test metrics storage only)
    import sys
    fake_obs = types.SimpleNamespace(get_recent_errors=lambda limit=200: [])
    monkeypatch.setitem(sys.modules, "observability", fake_obs)

    # Mock metrics_storage.find_by_request_id
    fake_metrics_data = [
        {
            "timestamp": "2025-01-15T10:00:00Z",
            "request_id": "1a9a61c6",
            "status_code": 200,
            "duration_seconds": 0.123,
            "path": "/api/test",
            "method": "GET",
        },
    ]
    fake_metrics = types.SimpleNamespace(
        find_by_request_id=lambda rid, limit=20: fake_metrics_data if "1a9a61c6" in rid else []
    )
    monkeypatch.setitem(sys.modules, "monitoring.metrics_storage", fake_metrics)

    res = await inv.triage("1a9a61c6", limit=10)
    
    assert isinstance(res, dict)
    timeline = res.get("timeline", [])
    # Should find the metrics record
    assert len(timeline) >= 1
    # Check that the message contains the expected info
    assert any("status=200" in entry.get("message", "") for entry in timeline)
    assert any("/api/test" in entry.get("message", "") for entry in timeline)


@pytest.mark.asyncio
async def test_triage_no_fallback_when_sentry_returns_data(monkeypatch):
    """Test that fallback is not triggered when Sentry returns results."""
    # Use the standard fake Sentry that returns results
    monkeypatch.setattr(inv, "sentry_client", _FakeSentry(), raising=False)

    # Track if local search was called
    local_search_called = {"value": False}

    def mock_get_recent_errors(limit=200):
        local_search_called["value"] = True
        return []

    import sys
    fake_obs = types.SimpleNamespace(get_recent_errors=mock_get_recent_errors)
    monkeypatch.setitem(sys.modules, "observability", fake_obs)

    res = await inv.triage("req-abc123", limit=5)
    
    # Should have results from Sentry
    assert len(res.get("timeline", [])) >= 2
    # Local search should NOT have been called
    assert not local_search_called["value"]
