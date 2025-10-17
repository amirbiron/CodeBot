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
