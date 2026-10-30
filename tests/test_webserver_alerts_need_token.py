"""``POST /alerts``, ``GET /alerts`` ו-``GET /incidents`` בשרת הפנימי של הבוט דורשים את ``DB_HEALTH_TOKEN``.

**למה הקובץ הזה קיים.** השרת (``services/webserver.py``) מאזין ל-``0.0.0.0`` ועולה לפי ``ENABLE_INTERNAL_SHARE_WEB``
בלבד. עד אוקטובר 2026 הוא עלה רק אם גם ``PUBLIC_BASE_URL`` הוגדר, ובפרודקשן הדגל היה דלוק והמשתנה חסר, כך שהשרת
לא עלה. כשהמשתנה בוטל, דגל דלוק לבדו מעלה אותו — ושלושת הנתיבים האלה היו פתוחים: ``POST /alerts`` מעביר
התראות לטלגרם, כלומר כל אחד יכול לשלוח לאדמין התראות מזויפות, ו-``GET`` שלהם מחזיר את ההתראות והתקלות הפנימיות.
עכשיו הם תחת ה-middleware של הטוקן, כמו ``/api/db/``: בלי טוקן מוגדר — 403, ובלי טוקן בבקשה או עם טוקן שגוי — 401.
"""

from __future__ import annotations

import importlib
import types

import pytest


async def _call(app, method, path, headers=None, data=None):
    import aiohttp
    from aiohttp import web

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=0)
    await site.start()
    try:
        port = list(site._server.sockets)[0].getsockname()[1]
        async with aiohttp.ClientSession() as session:
            async with session.request(method, f"http://127.0.0.1:{port}{path}", headers=headers, data=data) as resp:
                return resp.status
    finally:
        await runner.cleanup()


@pytest.fixture
def forwarded(monkeypatch):
    sent = []
    monkeypatch.setitem(importlib.sys.modules, "alert_forwarder", types.SimpleNamespace(forward_alerts=sent.extend))
    return sent


_ALERT = '{"alerts": [{"status": "firing", "labels": {"alertname": "Fake"}}]}'
_ROUTES = [("POST", "/alerts"), ("GET", "/alerts"), ("GET", "/incidents")]


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", _ROUTES)
async def test_without_a_configured_token_the_route_is_closed(monkeypatch, forwarded, method, path):
    import services.webserver as ws

    monkeypatch.setattr(ws, "DB_HEALTH_TOKEN", "")

    assert await _call(ws.create_app(), method, path, data=_ALERT if method == "POST" else None) == 403
    assert forwarded == []


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", _ROUTES)
@pytest.mark.parametrize("headers", [None, {"Authorization": "Bearer wrong"}], ids=["no-token", "wrong-token"])
async def test_a_request_without_the_right_token_is_refused(monkeypatch, forwarded, method, path, headers):
    import services.webserver as ws

    monkeypatch.setattr(ws, "DB_HEALTH_TOKEN", "the-token")

    assert await _call(ws.create_app(), method, path, headers=headers, data=_ALERT if method == "POST" else None) == 401
    assert forwarded == []


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", _ROUTES)
async def test_the_right_token_still_works(monkeypatch, forwarded, method, path):
    import services.webserver as ws

    monkeypatch.setattr(ws, "DB_HEALTH_TOKEN", "the-token")

    status = await _call(
        ws.create_app(), method, path, headers={"Authorization": "Bearer the-token"},
        data=_ALERT if method == "POST" else None,
    )
    assert status == 200
    assert len(forwarded) == (1 if method == "POST" else 0)


@pytest.mark.asyncio
async def test_health_stays_open(monkeypatch):
    """ריצת הבקרה: הטוקן חל רק על הנתיבים שנמנו, ולא על השרת כולו."""
    import services.webserver as ws

    monkeypatch.setattr(ws, "DB_HEALTH_TOKEN", "")

    assert await _call(ws.create_app(), "GET", "/health") == 200
