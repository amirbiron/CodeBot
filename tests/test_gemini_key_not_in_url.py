"""בדיקות שמפתח ה-API של Gemini לא נכנס לכתובת הבקשה.

**למה זה נבדק מול בקשה אמיתית ולא בהשוואת מחרוזות בקוד:** הבעיה המקורית לא
הייתה בקוד שנראה שגוי — היא הייתה במה שיצא על החוט. ``params={"key": ...}``
נראה תמים, ו-httpx הוא זה שהרכיב ממנו את הכתובת. הבדיקה מרימה שרת HTTP
מקומי ובודקת את הבקשה שנחתה בצד השני, כי זה מה שהדפדפן — או Sentry —
באמת רואים.

הרקע: המפתח דלף ל-Sentry דרך ``http.query`` של span, שנרשם על ידי
אינטגרציית httpx בלי ניקוי. הכתובת היא הנשא, ולכן הבדיקה נועלת את הנשא.
"""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

pytest.importorskip("httpx")

# מפתח בדוי בצורת מפתח של Google — משמש רק כדי לוודא שהוא לא מופיע בכתובת
FAKE_KEY = "AIzaSyFAKE0000_NOT_A_REAL_KEY_000000000"


class _Recorder(BaseHTTPRequestHandler):
    """מקליט את הבקשה שנחתה, ומחזיר תשובת embedding תקינה."""

    seen: dict = {}

    def _record(self):
        type(self).seen = {
            "path": self.path,  # כולל שורת השאילתה, אם יש
            "headers": {k.lower(): v for k, v in self.headers.items()},
        }

    def do_POST(self):
        self._record()
        body = json.dumps({"embedding": {"values": [0.1] * 768}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._record()
        body = json.dumps({"models": []}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # משתיק את הלוג של http.server בפלט הטסטים
        pass


@pytest.fixture
def recording_server():
    """שרת מקומי על פורט חופשי, שנסגר בסוף הטסט."""
    _Recorder.seen = {}
    srv = HTTPServer(("127.0.0.1", 0), _Recorder)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv, _Recorder
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def _service_pointed_at(port):
    from services.embedding_service import EmbeddingService

    svc = EmbeddingService(api_key=FAKE_KEY)
    # רק הבסיס מוחלף; בניית הבקשה, הלקוח והכותרות נשארים המסלול האמיתי
    svc._base_url = lambda av: f"http://127.0.0.1:{port}/{av}/models"
    return svc


def test_embedding_request_carries_the_key_in_a_header_not_in_the_url(recording_server):
    """**זו הבדיקה שנועלת את התיקון.**

    נופלת אם מחזירים ``params={"key": self.api_key}`` לאתר הקריאה, או אם
    הכותרת יורדת מהלקוח.
    """
    srv, recorder = recording_server
    svc = _service_pointed_at(srv.server_address[1])

    asyncio.run(
        svc.generate_embedding_with_status(
            "hello", model="text-embedding-004", api_version="v1beta", dimensions=768
        )
    )

    seen = recorder.seen
    assert seen, "השרת לא קיבל בקשה"
    assert FAKE_KEY not in seen["path"], f"המפתח נמצא בכתובת: {seen['path']}"
    assert "key=" not in seen["path"], f"נשארה שורת שאילתה עם key=: {seen['path']}"
    assert seen["headers"].get("x-goog-api-key") == FAKE_KEY


def test_model_listing_request_also_keeps_the_key_out_of_the_url(recording_server):
    """גם מסלול ה-GET — התיקון על הלקוח, ולכן הוא חל על כל הקריאות.

    נופלת אם הכותרת תוחזר לאתר קריאה בודד במקום לשבת על הלקוח.
    """
    srv, recorder = recording_server
    svc = _service_pointed_at(srv.server_address[1])

    asyncio.run(svc.list_models(api_version="v1beta"))

    seen = recorder.seen
    assert seen, "השרת לא קיבל בקשה"
    assert FAKE_KEY not in seen["path"]
    assert seen["headers"].get("x-goog-api-key") == FAKE_KEY


def test_client_without_api_key_does_not_send_an_empty_header():
    """בלי מפתח לא נשלחת כותרת ריקה — שדה ריק הוא רעש, לא הזדהות."""
    from services.embedding_service import EmbeddingService

    svc = EmbeddingService(api_key="")
    assert "x-goog-api-key" not in svc.client.headers
