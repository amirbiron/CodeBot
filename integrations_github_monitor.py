"""
Lightweight GitHub monitor utilities.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

try:  # aiohttp optional during tests
    import aiohttp  # type: ignore
except Exception:  # pragma: no cover
    aiohttp = None  # type: ignore


async def fetch_rate_limit(token: Optional[str] = None) -> Dict[str, Any]:
    """Fetch GitHub rate limit JSON. Returns empty dict if unavailable."""
    tok = token or os.getenv("GITHUB_TOKEN")
    if aiohttp is None or not tok:
        return {}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.github.com/rate_limit",
                headers={"Authorization": f"token {tok}"},
            ) as resp:
                return await resp.json()
    except Exception:
        return {}


def summarize_rate_limit(data: Dict[str, Any]) -> Dict[str, int]:
    core = (data.get("resources") or {}).get("core") or {}
    try:
        limit = int(core.get("limit", 0) or 0)
    except Exception:
        limit = 0
    try:
        remaining = int(core.get("remaining", 0) or 0)
    except Exception:
        remaining = 0
    used_pct = (100 - int(remaining * 100 / max(limit, 1))) if limit else 0
    return {"limit": limit, "remaining": remaining, "used_pct": used_pct}
