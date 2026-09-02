"""בדיקות לשכבת ה-Retry הכפולה ב-``http_sync``.

``http_sync`` נושא שתי שכבות retry שמוכפלות זו בזו: הלולאה ב-``request``
ו-``urllib3.Retry`` שמורכב על ה-adapter של ה-Session. ``max_attempts``
נוגע רק בראשונה, ולכן הוא **אינו** מספר הבקשות שיישלחו — ``max_attempts=2``
מייצר שש בקשות רשת.

הקובץ הזה מודד את שתי ההתנהגויות: שהדגל החדש מתקן, ושהמסלול הקיים לא זז.
הבדיקה השנייה חשובה לא פחות — ``http_sync`` הוא תשתית משותפת עם הבוט ועם
שכבת ה-DB, ו"additive בלבד" בלי טסט הוא הצהרה ולא ראיה.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import http_sync


class _CountingHandler(BaseHTTPRequestHandler):
    """מחזיר 503 — סטטוס שנמצא ב-``status_forcelist`` של שתי השכבות."""

    def do_POST(self):  # noqa: N802 — חתימה של BaseHTTPRequestHandler
        self.server.hit_count += 1
        body = b'{"code":"query_capacity"}'
        self.send_response(503)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def failing_server():
    server = HTTPServer(("127.0.0.1", 0), _CountingHandler)
    server.hit_count = 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(autouse=True)
def _fresh_sessions():
    """ה-Sessions נשמרים ב-thread-local ושורדים בין טסטים."""
    for attr in ("session", "session_no_adapter_retries"):
        if hasattr(http_sync._local, attr):
            delattr(http_sync._local, attr)
    yield
    for attr in ("session", "session_no_adapter_retries"):
        if hasattr(http_sync._local, attr):
            delattr(http_sync._local, attr)


def _post(server, **kwargs):
    url = f"http://127.0.0.1:{server.server_port}/x"
    try:
        http_sync.request("POST", url, json={}, timeout=2, **kwargs)
    except Exception:
        pass
    return server.hit_count


def test_adapter_retries_false_makes_max_attempts_the_real_request_count(failing_server):
    hits = _post(
        failing_server,
        max_attempts=2,
        adapter_retries=False,
        service="test",
        endpoint="test.fixed",
    )

    assert hits == 2, f"ביקשנו שני ניסיונות וקיבלנו {hits} בקשות"


def test_the_existing_path_is_untouched(failing_server, monkeypatch):
    """הבדיקה שהופכת את "additive בלבד" מהצהרה לראיה.

    שלושה קוראים אחרים בריפו מעבירים ``max_attempts`` בלי הדגל החדש, ואסור
    שההתנהגות שלהם תזוז. המספר הצפוי נגזר מ-``REQUESTS_RETRIES`` ולא מועתק.
    """
    expected_inner = http_sync._to_int("REQUESTS_RETRIES", 2)
    hits = _post(failing_server, max_attempts=2, service="test", endpoint="test.legacy")

    assert hits == 2 * (1 + expected_inner)
    assert hits > 2, "אם זה שווה ל-max_attempts, ברירת המחדל השתנתה"


def test_the_two_sessions_are_distinct_and_carry_different_adapters():
    with_retries = http_sync.get_session(adapter_retries=True)
    without = http_sync.get_session(adapter_retries=False)

    assert with_retries is not without
    assert http_sync.get_session(adapter_retries=True) is with_retries, "לא נשמר ב-thread-local"

    inner = with_retries.get_adapter("http://x").max_retries
    disabled = without.get_adapter("http://x").max_retries

    assert getattr(inner, "total", inner) == http_sync._to_int("REQUESTS_RETRIES", 2)
    assert getattr(disabled, "total", disabled) == 0


def test_the_circuit_breaker_still_sees_failures_without_adapter_retries(failing_server):
    """המפסק והמדדים חיים בלולאה החיצונית ולא ב-adapter, ולכן הדגל אינו נוגע בהם."""
    from resilience import CircuitBreakerPolicy

    url = f"http://127.0.0.1:{failing_server.server_port}/x"
    policy = CircuitBreakerPolicy(failure_threshold=2, recovery_seconds=30.0)

    for _ in range(3):
        try:
            http_sync.request(
                "POST", url, json={}, timeout=2, max_attempts=1, adapter_retries=False,
                service="breaker_probe", endpoint="breaker_probe.ep", circuit_policy=policy,
            )
        except Exception:
            pass

    with pytest.raises(http_sync.CircuitOpenError):
        http_sync.request(
            "POST", url, json={}, timeout=2, max_attempts=1, adapter_retries=False,
            service="breaker_probe", endpoint="breaker_probe.ep", circuit_policy=policy,
        )


def test_a_tuple_timeout_does_not_break_the_span_attributes(failing_server):
    """``requests`` מקבל ``(connect, read)``, ולכן ``http_sync`` חייב לקבל גם.

    זה נתפס רק כשטסט קרא דרך ``http_sync`` האמיתי: כל הטסטים שמזייפים את
    ``request`` עברו, והקוד היה זורק ``TypeError`` על ``float(tuple)``
    ברגע שבקשה אמיתית נשלחת.
    """
    url = f"http://127.0.0.1:{failing_server.server_port}/x"

    try:
        http_sync.request(
            "POST", url, json={}, timeout=(1.0, 2.0), max_attempts=1,
            adapter_retries=False, service="tuple_timeout", endpoint="tuple_timeout.ep",
        )
    except TypeError as exc:  # pragma: no cover
        pytest.fail(f"טאפל timeout הפיל את http_sync: {exc}")
    except Exception:
        pass  # 503 צפוי; מה שנבדק הוא שלא נזרק TypeError

    assert failing_server.hit_count == 1


@pytest.mark.parametrize(
    ("value", "expected"),
    [(3.0, 3.0), ((2.0, 4.0), 6.0), ([1.0, 2.0], 3.0), ((None, 5.0), 5.0), ("bad", 0.0)],
)
def test_timeout_for_span_collapses_both_windows(value, expected):
    """הסכום הוא התקרה האמיתית — גם לערך סקלרי, שמתפרק לשני חלונות."""
    assert http_sync._timeout_for_span(value) == expected


def test_a_scalar_timeout_is_two_windows_not_one():
    """הבסיס לכך שהתקציב ב-``mcp_analytics_service`` משתמש בטאפל.

    ``requests`` ממיר ערך סקלרי ל-``connect`` *ו*-``read`` נפרדים, ו-urllib3
    מקבל ``total=None`` — כלומר אין חסם על הסכום, וערך שנראה כתקרה אחת
    מתיר בפועל את כפליו.
    """
    from urllib3.util import Timeout

    scalar = Timeout(connect=3.0, read=3.0)

    assert scalar.total is None
    assert scalar.connect_timeout + scalar.read_timeout == 6.0
