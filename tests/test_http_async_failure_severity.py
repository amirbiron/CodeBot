"""``failure_severity`` של ``http_async.request``: החומרה של ``external_request_failure`` כשהבקשה נכשלה סופית.

הבקשות יוצאות לשרת HTTP אמיתי על ``127.0.0.1`` (``aiohttp.test_utils.TestServer``), דרך הסשן והניסיונות החוזרים
האמיתיים של ``http_async`` — כך שהטסט עובר באותו מסלול כמו הסמפלר של הבוט, ולא בדמה של ``session.request``.
"""

from __future__ import annotations

import socket

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

import http_async
import resilience


@pytest.fixture
def captured_events(monkeypatch):
    """האירועים ש-``http_async`` שולח, במקום ``observability.emit_event``; ומעגלים נקיים לכל טסט."""
    events: list[dict] = []

    def _capture(event, **fields):
        events.append({"event": event, **fields})

    monkeypatch.setattr(http_async, "_emit_event", _capture)
    # המעגלים נשמרים במילון ברמת המודול. מילון חדש לכל טסט, כדי שכישלונות של טסט אחד לא יפתחו מעגל לטסט הבא.
    monkeypatch.setattr(resilience, "_CIRCUITS", {})
    return events


@pytest.fixture
async def server_503():
    async def _handler(_request):
        return web.Response(status=503, text="down")

    app = web.Application()
    app.router.add_get("/metrics", _handler)
    server = TestServer(app, host="127.0.0.1")
    await server.start_server()
    try:
        yield server
    finally:
        await server.close()


def _closed_port() -> int:
    """פורט שאף אחד לא מאזין עליו: נתפס ומשוחרר מיד, ולכן חיבור אליו נדחה."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _failures(events: list[dict]) -> list[dict]:
    return [e for e in events if e["event"] == "external_request_failure"]


async def test_default_failure_severity_is_still_error(captured_events, server_503):
    """קורא שלא העביר את הפרמטר מקבל בדיוק את מה שקיבל עד היום."""
    url = str(server_503.make_url("/metrics"))
    async with http_async.request("GET", url, service="webapp", endpoint="/metrics") as resp:
        assert resp.status == 503

    failures = _failures(captured_events)
    assert len(failures) == 1
    assert failures[0]["severity"] == "error"
    assert failures[0]["error_signature"] == "HTTPStatus"


async def test_warning_on_retryable_status(captured_events, server_503):
    url = str(server_503.make_url("/metrics"))
    async with http_async.request(
        "GET", url, service="webapp", endpoint="/metrics", failure_severity="warning"
    ) as resp:
        assert resp.status == 503

    failures = _failures(captured_events)
    assert len(failures) == 1
    assert failures[0]["severity"] == "warning"
    assert failures[0]["error_signature"] == "HTTPStatus"


async def test_warning_on_transport_exception(captured_events):
    """חיבור שנדחה: המסלול של חריגה, ולא של סטטוס."""
    url = f"http://127.0.0.1:{_closed_port()}/metrics"
    with pytest.raises(Exception) as excinfo:
        async with http_async.request(
            "GET", url, service="webapp", endpoint="/metrics", failure_severity="warning"
        ):
            pass

    assert http_async.is_transport_error(excinfo.value)
    failures = _failures(captured_events)
    assert len(failures) == 1
    assert failures[0]["severity"] == "warning"
    assert failures[0]["error_signature"] == type(excinfo.value).__name__


@pytest.mark.parametrize("bad", ["warn", "info", "", 3, ["error"], None])
def test_unknown_failure_severity_is_rejected_before_any_request(bad):
    """ערך לא מוכר זורק מיד. רשימה (לא hashable) נדחית כ-ValueError ולא נופלת ב-TypeError של ה-frozenset."""
    with pytest.raises(ValueError, match="failure_severity"):
        http_async.request("GET", "http://127.0.0.1:9/metrics", failure_severity=bad)


def test_is_transport_error_rejects_bugs():
    """באג אצלנו אינו "הצד השני לא ענה"."""
    assert not http_async.is_transport_error(TypeError("boom"))
    assert not http_async.is_transport_error(AttributeError("boom"))
    assert not http_async.is_transport_error(KeyboardInterrupt())
    assert http_async.is_transport_error(http_async.CircuitOpenError("webapp", "/metrics"))
    assert http_async.is_transport_error(TimeoutError())
