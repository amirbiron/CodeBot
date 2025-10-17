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
from datetime import datetime
from typing import Any, Dict, List, Optional

try:  # Optional sentry integration
    import integrations_sentry as sentry_client  # type: ignore
except Exception:  # pragma: no cover
    sentry_client = None  # type: ignore


def _now_iso() -> str:
    try:
        return datetime.utcnow().isoformat()
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


def _summarize_timeline_text(timeline: List[Dict[str, Any]], limit: int = 10) -> str:
    lines: List[str] = []
    for i, item in enumerate(timeline[: max(1, limit)], 1):
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

    rows: List[str] = []
    for item in timeline[:20]:
        ts = html.escape(str(item.get("timestamp") or item.get("ts") or ""))
        msg = html.escape(str(item.get("message") or item.get("title") or ""))
        url = str(item.get("url") or item.get("permalink") or "").strip()
        if url:
            msg = f'<a href="{html.escape(url)}" target="_blank" rel="noopener">{msg}</a>'
        rows.append(f"<tr><td>{ts}</td><td>{msg}</td></tr>")

    link_tags = []
    for ln in links[:6]:
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
                    }
                )
    except Exception:
        pass

    # Grafana links (best-effort)
    grafana_links = _grafana_links_for_request(query)

    result: Dict[str, Any] = {
        "query": query,
        "request_id": query,
        "timeline": timeline,
        "summary_text": _summarize_timeline_text(timeline),
        "grafana_links": grafana_links,
    }
    result["summary_html"] = render_triage_html(result)
    return result
