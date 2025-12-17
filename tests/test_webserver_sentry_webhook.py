import json
import os
import pytest

from services.webserver import create_app


@pytest.mark.asyncio
async def test_sentry_webhook_accepts_without_secret_and_emits_internal_alert(monkeypatch):
    from aiohttp import web

    # Ensure no secret is required
    monkeypatch.delenv("SENTRY_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)

    captured = []

    def fake_emit_internal_alert(name: str, severity: str = "info", summary: str = "", **details):
        captured.append({"name": name, "severity": severity, "summary": summary, "details": details})

    import types
    import importlib
    monkeypatch.setitem(importlib.sys.modules, "internal_alerts", types.SimpleNamespace(emit_internal_alert=fake_emit_internal_alert))

    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=0)
    await site.start()
    try:
        port = list(site._server.sockets)[0].getsockname()[1]
        import aiohttp
        async with aiohttp.ClientSession() as session:
            payload = {
                "action": "triggered",
                "data": {
                    "issue": {"id": "123", "shortId": "ABC-9", "title": "Boom", "permalink": "https://sentry.io/issue/123"},
                    "event": {"level": "error"},
                    "project": {"slug": "codebot"},
                },
            }
            async with session.post(f"http://127.0.0.1:{port}/webhooks/sentry", data=json.dumps(payload)) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data.get("ok") is True
    finally:
        await runner.cleanup()

    assert captured, "expected internal alert emission"
    assert captured[0]["severity"] in {"error", "critical", "warning", "info"}
    assert captured[0]["details"].get("alert_type") == "sentry_issue"


@pytest.mark.asyncio
async def test_sentry_webhook_rejects_when_secret_set_and_no_auth(monkeypatch):
    from aiohttp import web

    monkeypatch.setenv("SENTRY_WEBHOOK_SECRET", "secret123")

    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=0)
    await site.start()
    try:
        port = list(site._server.sockets)[0].getsockname()[1]
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(f"http://127.0.0.1:{port}/webhooks/sentry", data="{}") as resp:
                assert resp.status == 401
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_sentry_webhook_accepts_with_token_query_when_secret_set(monkeypatch):
    from aiohttp import web

    monkeypatch.setenv("SENTRY_WEBHOOK_SECRET", "secret123")

    captured = []

    def fake_emit_internal_alert(name: str, severity: str = "info", summary: str = "", **details):
        captured.append((name, severity, summary, details))

    import types
    import importlib
    monkeypatch.setitem(importlib.sys.modules, "internal_alerts", types.SimpleNamespace(emit_internal_alert=fake_emit_internal_alert))

    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=0)
    await site.start()
    try:
        port = list(site._server.sockets)[0].getsockname()[1]
        import aiohttp
        async with aiohttp.ClientSession() as session:
            payload = {"data": {"issue": {"shortId": "ABC-1", "title": "Err"}}}
            async with session.post(
                f"http://127.0.0.1:{port}/webhooks/sentry?token=secret123",
                data=json.dumps(payload),
            ) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data.get("ok") is True
    finally:
        await runner.cleanup()

    assert captured


@pytest.mark.asyncio
async def test_sentry_webhook_resolved_operationcancelled_stays_info(monkeypatch):
    from aiohttp import web

    monkeypatch.delenv("SENTRY_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)

    captured = []

    def fake_emit_internal_alert(name: str, severity: str = "info", summary: str = "", **details):
        captured.append({"name": name, "severity": severity, "summary": summary, "details": details})

    import types
    import importlib
    monkeypatch.setitem(importlib.sys.modules, "internal_alerts", types.SimpleNamespace(emit_internal_alert=fake_emit_internal_alert))

    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=0)
    await site.start()
    try:
        port = list(site._server.sockets)[0].getsockname()[1]
        import aiohttp
        async with aiohttp.ClientSession() as session:
            payload = {
                "action": "resolved",
                "data": {
                    "issue": {
                        "id": "999",
                        "shortId": "PYTHON-1A",
                        "title": "_OperationCancelled: operation cancelled",
                        "permalink": "https://sentry.io/issue/999",
                    },
                    "event": {"level": "error"},
                    "project": {"slug": "codebot"},
                },
            }
            async with session.post(f"http://127.0.0.1:{port}/webhooks/sentry", data=json.dumps(payload)) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data.get("ok") is True
    finally:
        await runner.cleanup()

    assert captured, "expected internal alert emission"
    assert captured[0]["severity"] == "info"

