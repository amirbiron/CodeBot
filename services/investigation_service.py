"""
Investigation/Triage service – collects data for /triage.

Design:
- Sentry-first: search events by request_id or free-text query
- Fallback: empty timeline when Sentry not configured
- Grafana links: best-effort using GRAFANA_URL env
- HTML rendering: minimal, self-contained and safe (escapes content)

Env:
- GRAFANA_URL: base URL of Grafana, e.g. https://grafana.example.com
- PUBLIC_BASE_URL/WEBAPP_URL: used for building absolute links when relevant (optional)
"""
from __future__ import annotations

import os
import html
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urlparse

try:  # Optional sentry integration
    import integrations_sentry as sentry_client  # type: ignore
except Exception:  # pragma: no cover
    sentry_client = None  # type: ignore


def _now_iso() -> str:
    try:
        return datetime.now(timezone.utc).isoformat()
    except Exception:
        return ""


def _grafana_links_for_request(request_id: str) -> List[Dict[str, str]]:
    base = (os.getenv("GRAFANA_URL") or "").rstrip("/")
    if not base:
        return []
    rid = html.escape(str(request_id or ""))
    # Best-effort panels; actual dashboards may differ between deployments
    return [
        {"name": "Logs (24h)", "url": f"{base}/explore?orgId=1&query=\"request_id:{rid}\""},
        {"name": "Latency (5m)", "url": f"{base}/d/lZcyP/latency?orgId=1&var_request_id={rid}&from=now-5m&to=now"},
        {"name": "Errors (24h)", "url": f"{base}/d/err01/errors?orgId=1&var_request_id={rid}&from=now-24h&to=now"},
    ]


def _sentry_ui_base() -> Optional[str]:
    """Best-effort Sentry UI base URL (e.g., https://sentry.io).

    Prefer deriving from SENTRY_DSN; fallback to https://sentry.io.
    """
    try:
        dsn = os.getenv("SENTRY_DSN") or ""
        if dsn:
            try:
                parsed = urlparse(dsn)
                host = parsed.hostname or ""
            except Exception:
                host = ""
            if host:
                # Common DSN hosts: o123.ingest.sentry.io, ingest.sentry.io, sentry.io, self-hosted domains
                if host.endswith(".sentry.io") or host == "sentry.io":
                    return "https://sentry.io"
                if host.startswith("ingest."):
                    return f"https://{host[len('ingest.'):]}"
                return f"https://{host}"
    except Exception:
        pass
    return "https://sentry.io"


def _sentry_links_for_request(request_id: str) -> List[Dict[str, str]]:
    """Construct Sentry UI links for triage.

    Heuristic:
    - If the input looks like a bare token (no ':'/'='/space), treat it as request_id
      and search by request_id:"<token>".
    - Otherwise, treat the input as a raw Sentry query (e.g., endpoint=v2/getMonitors)
      and pass it through as-is.
    """
    rid = str(request_id or "").strip()
    if not rid:
        return []
    base = _sentry_ui_base()
    org = os.getenv("SENTRY_ORG") or os.getenv("SENTRY_ORG_SLUG")
    if not org:
        return []

    try:
        # Align with the search heuristic used in triage():
        if (":" not in rid) and ("=" not in rid) and (" " not in rid):
            query_expr = f'request_id:"{rid}"'
        else:
            query_expr = rid
    except Exception:
        query_expr = rid

    q = quote_plus(query_expr)
    # Issues search (24h) is the most universally supported view
    issues = f"{base}/organizations/{org}/issues/?query={q}&statsPeriod=24h"
    # Discover results (if enabled) – optional but useful
    discover = f"{base}/organizations/{org}/discover/results/?query={q}&sort=-timestamp"
    return [
        {"name": "Sentry Issues (24h)", "url": issues},
        {"name": "Sentry Discover", "url": discover},
    ]


def _summarize_timeline_text(timeline: List[Dict[str, Any]], limit: int = 10) -> str:
    lines: List[str] = []
    # כבד במדויק את ה-limit, כולל מקרה של 0
    if limit <= 0:
        return ""
    for i, item in enumerate(timeline[: limit], 1):
        ts = str(item.get("timestamp") or item.get("ts") or "")
        message = str(item.get("message") or item.get("title") or "")
        lines.append(f"{i}. {ts} – {message}")
    return "\n".join(lines)


def render_triage_html(result: Dict[str, Any]) -> str:
    """Render a compact triage HTML report.

    The HTML is intentionally simple and self-contained.
    """
    rid = html.escape(str(result.get("request_id") or result.get("query") or ""))
    timeline: List[Dict[str, Any]] = list(result.get("timeline") or [])
    links: List[Dict[str, str]] = list(result.get("grafana_links") or [])
    sentry_links: List[Dict[str, str]] = list(result.get("sentry_links") or [])

    rows: List[str] = []
    for item in timeline[:20]:
        ts = html.escape(str(item.get("timestamp") or item.get("ts") or ""))
        msg = html.escape(str(item.get("message") or item.get("title") or ""))
        url = str(item.get("url") or item.get("permalink") or "").strip()
        if url:
            msg = f'<a href="{html.escape(url)}" target="_blank" rel="noopener">{msg}</a>'
        rows.append(f"<tr><td>{ts}</td><td>{msg}</td></tr>")

    link_tags = []
    for ln in (sentry_links + links)[:6]:
        name = html.escape(str(ln.get("name") or "Link"))
        url = html.escape(str(ln.get("url") or ""))
        if url:
            link_tags.append(f'<a href="{url}" target="_blank" rel="noopener">{name}</a>')

    html_out = f"""
<!doctype html>
<meta charset="utf-8" />
<title>/triage – {rid}</title>
<style>
  body {{ font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, "Helvetica Neue", Arial; padding: 12px; }}
  h1 {{ font-size: 18px; margin: 0 0 8px; }}
  .meta {{ color: #6b7280; font-size: 12px; margin-bottom: 10px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ text-align: left; border-bottom: 1px solid #eee; padding: 6px 4px; font-size: 13px; }}
  .links a {{ margin-right: 12px; color: #2563eb; text-decoration: none; }}
</style>
<h1>🔎 Triage: {rid}</h1>
<div class="meta">נוצר: {_now_iso()}</div>
<div class="links">{' '.join(link_tags)}</div>
<table>
  <thead><tr><th>זמן</th><th>אירוע</th></tr></thead>
  <tbody>
    {''.join(rows) or '<tr><td colspan="2">אין אירועים.</td></tr>'}
  </tbody>
</table>
"""
    return html_out


def _search_local_errors(request_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Search in-memory error buffer for matching request_id (fallback).

    Returns list of timeline events (best-effort, fail-open).
    """
    results: List[Dict[str, Any]] = []
    try:
        from observability import get_recent_errors  # type: ignore
        errors = get_recent_errors(limit=200)
        rid = str(request_id or "").strip().lower()
        if not rid:
            return []
        for err in errors:
            try:
                err_rid = str(err.get("request_id") or "").strip().lower()
                # Match exact or prefix
                if err_rid and (err_rid == rid or err_rid.startswith(rid) or rid in err_rid):
                    results.append({
                        "timestamp": str(err.get("ts") or err.get("timestamp") or ""),
                        "message": str(err.get("error") or err.get("message") or err.get("event") or ""),
                        "url": "",
                        "source": "local_buffer",
                    })
            except Exception:
                continue
    except Exception:
        pass
    return results[:limit]


def _search_metrics_storage(request_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Search DB-backed metrics storage for matching request_id (fallback).

    Returns list of timeline events (best-effort, fail-open).
    """
    results: List[Dict[str, Any]] = []
    try:
        from monitoring.metrics_storage import find_by_request_id  # type: ignore
        records = find_by_request_id(request_id, limit=limit)
        for rec in records:
            try:
                status = int(rec.get("status_code", 0) or 0)
                duration = float(rec.get("duration_seconds", 0.0) or 0.0)
                path = str(rec.get("path") or "")
                method = str(rec.get("method") or "")
                msg_parts = []
                if method:
                    msg_parts.append(method)
                if path:
                    msg_parts.append(path)
                msg_parts.append(f"status={status}")
                msg_parts.append(f"duration={duration:.3f}s")
                results.append({
                    "timestamp": str(rec.get("timestamp") or ""),
                    "message": " ".join(msg_parts),
                    "url": "",
                    "source": "metrics_db",
                })
            except Exception:
                continue
    except Exception:
        pass
    return results[:limit]


async def triage(query_or_request_id: str, limit: int = 20) -> Dict[str, Any]:
    query = str(query_or_request_id or "").strip()
    timeline: List[Dict[str, Any]] = []

    # Sentry-first search
    try:
        if sentry_client and sentry_client.is_configured():  # type: ignore[attr-defined]
            # If query looks like a bare token, search by request_id field
            if ":" not in query and "=" not in query and " " not in query:
                squery = f'request_id:"{query}"'
            else:
                squery = query
            events = await sentry_client.search_events(squery, limit=limit)  # type: ignore[attr-defined]
            # Normalize fields for rendering
            for ev in events:
                timeline.append(
                    {
                        "timestamp": ev.get("timestamp") or "",
                        "message": ev.get("message") or "",
                        "url": ev.get("url") or "",
                        "source": "sentry",
                    }
                )
    except Exception:
        pass

    # Fallback: search local sources when Sentry returns nothing
    # This handles cases where:
    # 1. Sentry is not configured
    # 2. The request was successful (status 200) and not sent to Sentry
    # 3. The event hasn't been indexed in Sentry yet
    if not timeline:
        try:
            # Check if query looks like a request_id (bare token)
            if ":" not in query and "=" not in query and " " not in query:
                # 1. Search in-memory error buffer
                local_errors = _search_local_errors(query, limit=limit)
                timeline.extend(local_errors)

                # 2. Search DB-backed metrics storage
                metrics_records = _search_metrics_storage(query, limit=limit)
                timeline.extend(metrics_records)

                # Sort by timestamp (newest first) and deduplicate
                try:
                    timeline.sort(key=lambda x: str(x.get("timestamp") or ""), reverse=True)
                except Exception:
                    pass
        except Exception:
            pass

    # Links (best-effort)
    grafana_links = _grafana_links_for_request(query)
    sentry_links = _sentry_links_for_request(query)

    result: Dict[str, Any] = {
        "query": query,
        "request_id": query,
        "timeline": timeline,
        "summary_text": _summarize_timeline_text(timeline),
        "grafana_links": grafana_links,
        "sentry_links": sentry_links,
    }
    result["summary_html"] = render_triage_html(result)
    return result
