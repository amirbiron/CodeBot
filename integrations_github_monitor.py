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
        # Load configuration with sensible defaults
        try:
            from config import config  # type: ignore
            _total = int(getattr(config, "AIOHTTP_TIMEOUT_TOTAL", 10))
            _limit = int(getattr(config, "AIOHTTP_POOL_LIMIT", 50))
        except Exception:
            _total = 10
            _limit = 50

        # Build ClientSession kwargs only if supported by the provided aiohttp shim
        session_kwargs: Dict[str, Any] = {}
        try:
            if hasattr(aiohttp, "ClientTimeout"):
                session_kwargs["timeout"] = aiohttp.ClientTimeout(total=_total)  # type: ignore[attr-defined]
        except Exception:
            # Fallback: omit timeout if construction fails (e.g., in tests)
            pass
        try:
            if hasattr(aiohttp, "TCPConnector"):
                session_kwargs["connector"] = aiohttp.TCPConnector(limit=_limit)  # type: ignore[attr-defined]
        except Exception:
            # Fallback: omit connector if construction fails
            pass

        async with aiohttp.ClientSession(**session_kwargs) as session:  # type: ignore[arg-type]
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
