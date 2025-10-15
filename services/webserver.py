import logging
from typing import Optional

from aiohttp import web
try:
    from metrics import metrics_endpoint_bytes, metrics_content_type
except Exception:  # pragma: no cover
    metrics_endpoint_bytes = lambda: b""  # type: ignore
    metrics_content_type = lambda: "text/plain; charset=utf-8"  # type: ignore
try:
    from metrics import metrics_endpoint_bytes, metrics_content_type
except Exception:  # pragma: no cover
    metrics_endpoint_bytes = lambda: b""  # type: ignore
    metrics_content_type = lambda: "text/plain; charset=utf-8"  # type: ignore
from html import escape as html_escape

from integrations import code_sharing

logger = logging.getLogger(__name__)


def create_app() -> web.Application:
    app = web.Application()

    async def health(request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def metrics_view(request: web.Request) -> web.Response:
        try:
            payload = metrics_endpoint_bytes()
            return web.Response(body=payload, headers={"Content-Type": metrics_content_type()})
        except Exception as e:
            logger.error(f"metrics_view error: {e}")
            return web.Response(status=500, text="metrics error")

    async def metrics_view(request: web.Request) -> web.Response:
        try:
            payload = metrics_endpoint_bytes()
            return web.Response(body=payload, headers={"Content-Type": metrics_content_type()})
        except Exception as e:
            logger.error(f"metrics_view error: {e}")
            return web.Response(status=500, text="metrics error")

    async def share_view(request: web.Request) -> web.Response:
        share_id = request.match_info.get("share_id", "")
        try:
            data = code_sharing.get_internal_share(share_id)
        except Exception as e:
            logger.error(f"share_view error: {e}")
            data = None
        if not data:
            return web.Response(status=404, text="Share not found or expired")

        # החזר HTML פשוט לצפייה נוחה
        code = data.get("code", "")
        file_name = data.get("file_name", "snippet.txt")
        language = data.get("language", "text")
        html = f"""
<!DOCTYPE html>
<html lang="he">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Share: {file_name}</title>
  <style>
    body {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; margin: 24px; }}
    pre {{ white-space: pre-wrap; word-wrap: break-word; background: #0d1117; color: #c9d1d9; padding: 16px; border-radius: 8px; overflow: auto; }}
    h1 {{ font-size: 18px; }}
    .meta {{ color: #57606a; margin-bottom: 8px; }}
    a {{ color: #58a6ff; }}
  </style>
  </head>
  <body>
    <h1>📄 {file_name}</h1>
    <div class="meta">שפה: {language}</div>
    <pre>{html_escape(code)}</pre>
  </body>
</html>
"""
        return web.Response(text=html, content_type="text/html")

    app.router.add_get("/health", health)
    app.router.add_get("/metrics", metrics_view)
    app.router.add_get("/metrics", metrics_view)
    app.router.add_get("/share/{share_id}", share_view)

    return app


def run(host: str = "0.0.0.0", port: int = 10000) -> None:
    app = create_app()
    web.run_app(app, host=host, port=port)

