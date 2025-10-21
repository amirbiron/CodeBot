import os
import types
import pytest

import integrations_sentry as sc


class _Resp:
    def __init__(self, status: int, data):
        self.status = status
        self._data = data
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc, tb):
        return False
    async def json(self):
        return self._data


class _Session:
    def __init__(self, *a, **k):
        pass
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc, tb):
        return False
    def get(self, url, headers=None, params=None):
        # Route based on URL path for test coverage
        if "organizations/org1/issues" in url:
            return _Resp(200, [
                {"id": "1", "shortId": "S-1", "title": "Boom", "permalink": "https://s/1", "lastSeen": "2025-01-01", "firstSeen": "2025-01-01"}
            ])
        if "organizations/org1/events" in url:
            # New behavior expects an object with data array
            return _Resp(200, {
                "data": [
                    {"eventID": "e1", "timestamp": "2025-01-01T00:00:00Z", "projectSlug": "proj", "message": "Err msg", "permalink": "https://s/e1"}
                ],
                "meta": {"count": 1}
            })
        if "/issues/123/events" in url:
            return _Resp(200, {
                "data": [
                    {"eventID": "e1", "dateCreated": "2025-01-01T00:00:00Z", "message": "Hello", "permalink": "https://s/e1"}
                ]
            })
        return _Resp(404, {})


class _Aiohttp:
    class ClientTimeout:
        def __init__(self, total=None):
            self.total = total
    class TCPConnector:
        def __init__(self, limit=None):
            self.limit = limit
    ClientSession = _Session


@pytest.mark.asyncio
async def test_is_configured_and_fallback(monkeypatch):
    # No env and no aiohttp → not configured, empty results
    monkeypatch.delenv("SENTRY_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("SENTRY_ORG", raising=False)
    monkeypatch.setattr(sc, "aiohttp", None, raising=False)
    assert sc.is_configured() is False
    assert await sc.get_recent_issues(5) == []
    assert await sc.search_events("test") == []


@pytest.mark.asyncio
async def test_get_recent_issues_and_search_and_issue_events(monkeypatch):
    # Configure env and stub aiohttp
    monkeypatch.setenv("SENTRY_AUTH_TOKEN", "t")
    monkeypatch.setenv("SENTRY_ORG", "org1")
    monkeypatch.setattr(sc, "aiohttp", _Aiohttp, raising=False)

    issues = await sc.get_recent_issues(limit=5)
    assert issues and issues[0]["shortId"] == "S-1"

    events = await sc.search_events("request_id:abc", limit=10)
    assert events and events[0]["event_id"] == "e1" and "Err" in events[0]["message"]

    evs = await sc.get_issue_events("123", limit=5)
    assert evs and evs[0]["event_id"] == "e1" and "Hello" in evs[0]["message"]
