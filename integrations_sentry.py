"""
Sentry integration client (API v0) – minimal, fail-open.

Environment variables:
- SENTRY_AUTH_TOKEN: required for API calls
- SENTRY_ORG or SENTRY_ORG_SLUG: organization slug
- SENTRY_PROJECT or SENTRY_PROJECT_SLUG: optional project slug (filter)
- SENTRY_API_URL: optional base (default https://sentry.io/api/0)

Notes:
- Uses aiohttp if available; otherwise, returns empty results
- All functions are best-effort and never raise
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

try:  # pragma: no cover
    import aiohttp  # type: ignore
except Exception:  # pragma: no cover
    aiohttp = None  # type: ignore


def _api_base() -> str:
    base = os.getenv("SENTRY_API_URL") or "https://sentry.io/api/0"
    return base.rstrip("/")


def is_configured() -> bool:
    token = os.getenv("SENTRY_AUTH_TOKEN")
    org = os.getenv("SENTRY_ORG") or os.getenv("SENTRY_ORG_SLUG")
    # http_async.request handles the calls when aiohttp is unavailable, so env vars are enough.
    return bool(token and org)


async def _get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    if not is_configured():
        return None
    token = os.getenv("SENTRY_AUTH_TOKEN") or ""
    url = f"{_api_base()}/{path.lstrip('/')}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    try:
        from http_async import request as async_request
        base_kwargs = {
            "headers": headers,
            "params": params or {},
        }
        attempts = (
            {**base_kwargs, "service": "sentry", "endpoint": "api_get"},
            base_kwargs,
        )
        for req_kwargs in attempts:
            try:
                async with async_request("GET", url, **req_kwargs) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.json()
            except TypeError:
                # פקודת המוקים בטסט לא מקבלת service/endpoint – ננסה בלי.
                continue
        return None
    except Exception:
        return None


async def get_recent_issues(limit: int = 10) -> List[Dict[str, Any]]:
    """Return recent issues for the configured org (optionally filtered by project).

    Best-effort: returns empty list on any failure.
    """
    if not is_configured():
        return []
    org = os.getenv("SENTRY_ORG") or os.getenv("SENTRY_ORG_SLUG") or ""
    project = os.getenv("SENTRY_PROJECT") or os.getenv("SENTRY_PROJECT_SLUG")
    params: Dict[str, Any] = {
        "limit": max(1, min(100, int(limit or 10))),
        "query": "is:unresolved",  # default filter; still returns recent when none
    }
    if project:
        params["project"] = project
    data = await _get(f"organizations/{org}/issues/", params=params)
    if not isinstance(data, list):
        return []
    results: List[Dict[str, Any]] = []
    for item in data[: params["limit"]]:
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "id": str(item.get("id") or ""),
                "shortId": str(item.get("shortId") or ""),
                "title": str(item.get("title") or item.get("culprit") or ""),
                "permalink": str(item.get("permalink") or ""),
                "lastSeen": str(item.get("lastSeen") or ""),
                "firstSeen": str(item.get("firstSeen") or ""),
            }
        )
    return results


async def search_events(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Search events across the organization using a simple query string.

    For triage by request_id, pass e.g. query='request_id:"abc123"'.
    """
    if not is_configured():
        return []
    org = os.getenv("SENTRY_ORG") or os.getenv("SENTRY_ORG_SLUG") or ""
    project = os.getenv("SENTRY_PROJECT") or os.getenv("SENTRY_PROJECT_SLUG")
    params: Dict[str, Any] = {
        "query": str(query or "").strip() or "*",
        "limit": max(1, min(100, int(limit or 20))),
        "sort": "-timestamp",
    }
    if project:
        params["project"] = project
    data = await _get(f"organizations/{org}/events/", params=params)
    # Sentry returns an object with a "data" array; support both shapes defensively
    if isinstance(data, dict):
        data = data.get("data")
    if not isinstance(data, list):
        return []
    results: List[Dict[str, Any]] = []
    for ev in data[: params["limit"]]:
        if not isinstance(ev, dict):
            continue
        message = ""
        try:
            # Sentry event payloads vary; extract a readable message/title
            message = (
                str(
                    ev.get("message")
                    or ev.get("title")
                    or ev.get("event", {}).get("message")
                    or ev.get("event", {}).get("title")
                    or ""
                )
            )
        except Exception:
            message = ""
        results.append(
            {
                "event_id": str(ev.get("eventID") or ev.get("event_id") or ""),
                "timestamp": str(ev.get("timestamp") or ev.get("dateCreated") or ""),
                "project": str(ev.get("projectSlug") or ev.get("project", {}).get("slug") or ""),
                "message": message,
                "url": str(ev.get("permalink") or ""),
            }
        )
    return results


async def get_issue_events(issue_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Return events for a given Sentry issue id (not shortId)."""
    if not is_configured():
        return []
    issue_id = str(issue_id or "").strip()
    if not issue_id:
        return []
    data = await _get(f"issues/{issue_id}/events/", params={"limit": max(1, min(100, int(limit or 20)))})
    if isinstance(data, dict):
        data = data.get("data")
    if not isinstance(data, list):
        return []
    results: List[Dict[str, Any]] = []
    for ev in data:
        if not isinstance(ev, dict):
            continue
        results.append(
            {
                "event_id": str(ev.get("eventID") or ev.get("event_id") or ""),
                "timestamp": str(ev.get("dateCreated") or ev.get("timestamp") or ""),
                "message": str(ev.get("message") or ev.get("title") or ""),
                "url": str(ev.get("permalink") or ""),
            }
        )
    return results
