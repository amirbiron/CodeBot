"""צורת הבקשה ל-Gemini וסיווג הכשלים שחוזרים ממנה.

הרקע (אישו #3332): ``gemini-embedding-001`` חותך בשקט קלט שחורג מ-2,048
טוקנים. בנוסף, מיצוי ה-retries על 429 החזיר סטטוס ``0`` — בדיוק כמו timeout
— ולכן ה-worker לא יכול היה להבחין בין מכסה שנגמרה לבין תקלת רשת, והמשיך
לשרוף קריאות על כל שאר הבאץ'.

הטסטים מרימים שרת HTTP מקומי אמיתי ובודקים את הבקשה שנחתה, במקום למקף את
הלקוח — כדי שבניית ה-payload והכותרות יישארו המסלול האמיתי.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

FAKE_KEY = "AIzaSyFAKE0000_NOT_A_REAL_KEY_000000000"


class _Recorder(BaseHTTPRequestHandler):
    """מקליט את גוף הבקשה, ומחזיר תשובה לפי ``status_queue``."""

    seen: dict = {}
    status_queue: list = []
    request_count: int = 0

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except Exception:
            parsed = {}
        type(self).seen = {"body": parsed}
        type(self).request_count += 1

        status = type(self).status_queue.pop(0) if type(self).status_queue else 200
        if status == 200:
            body = json.dumps({"embedding": {"values": [0.1] * 768}}).encode()
        else:
            body = json.dumps({"error": {"code": status, "message": "test"}}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # משתיק את הלוג של http.server בפלט הטסטים
        pass


@pytest.fixture()
def recorder():
    _Recorder.seen = {}
    _Recorder.status_queue = []
    _Recorder.request_count = 0
    server = HTTPServer(("127.0.0.1", 0), _Recorder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, _Recorder
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture()
def service_factory(recorder, monkeypatch):
    port, rec = recorder
    import services.embedding_service as mod

    # אין השהיות בטסט: השער הגלובלי וה-backoff אינם מה שנבדק כאן.
    monkeypatch.setattr(mod, "EMBEDDING_MIN_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(mod, "EMBEDDING_RATE_LIMIT_COOLDOWN_SECONDS", 0.0)
    monkeypatch.setattr(mod, "RETRY_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(mod, "_next_allowed_ts", 0.0)

    def _make():
        svc = mod.EmbeddingService(api_key=FAKE_KEY)
        # רק הבסיס מוחלף; בניית הבקשה, הלקוח והכותרות נשארים המסלול האמיתי.
        svc._base_url = lambda av: f"http://127.0.0.1:{port}/{av}/models"
        return svc

    return _make, mod, rec


@pytest.mark.asyncio
async def test_auto_truncate_off_is_sent_in_embed_content_config(service_factory, monkeypatch):
    """מקור: https://ai.google.dev/api/embeddings — ``EmbedContentConfig.autoTruncate``."""
    make, mod, rec = service_factory
    monkeypatch.setattr(mod, "EMBEDDING_AUTO_TRUNCATE", False)

    embedding, status, _ = await make().generate_embedding_with_status(
        "hello", model="gemini-embedding-001", api_version="v1beta", dimensions=768
    )

    assert status == 200 and embedding
    body = rec.seen["body"]
    assert body["embedContentConfig"] == {"autoTruncate": False}
    # ``outputDimensionality`` נשאר ברמה העליונה — הזזתו היא שינוי התנהגות
    # שלא נדרש כאן, והיא עובדת שם היום.
    assert body["outputDimensionality"] == 768


@pytest.mark.asyncio
async def test_auto_truncate_on_sends_no_config_block(service_factory, monkeypatch):
    """ברירת המחדל היא ההתנהגות הקיימת, עד שהשדה יאומת מול ה-API החי."""
    make, mod, rec = service_factory
    monkeypatch.setattr(mod, "EMBEDDING_AUTO_TRUNCATE", True)

    await make().generate_embedding_with_status(
        "hello", model="gemini-embedding-001", api_version="v1beta", dimensions=768
    )

    assert "embedContentConfig" not in rec.seen["body"]


@pytest.mark.asyncio
async def test_exhausted_429_reports_429_not_zero(service_factory):
    """מכסה שנגמרה חייבת להיראות שונה מ-timeout.

    לפני התיקון, מיצוי ה-retries נפל לשורת ה-``return None, 0`` שבסוף
    הפונקציה — ולכן ה-worker התייחס למכסה שנגמרה ככשל זמני רגיל, המשיך
    לקובץ הבא, ושרף עליו עוד שלוש קריאות באותה שנייה.
    """
    make, mod, rec = service_factory
    rec.status_queue = [429, 429, 429]

    embedding, status, _ = await make().generate_embedding_with_status(
        "hello", model="gemini-embedding-001", api_version="v1beta", dimensions=768
    )

    assert embedding is None
    assert status == 429, f"exhausted quota reported as {status}, indistinguishable from a timeout"
    assert rec.request_count == mod.MAX_RETRIES


@pytest.mark.asyncio
async def test_429_then_success_still_succeeds(service_factory):
    """rate limiting חולף עדיין נפתר ב-retry — לא הפכנו כל 429 לכשל."""
    make, _mod, rec = service_factory
    rec.status_queue = [429, 200]

    embedding, status, _ = await make().generate_embedding_with_status(
        "hello", model="gemini-embedding-001", api_version="v1beta", dimensions=768
    )

    assert status == 200 and embedding and len(embedding) == 768


@pytest.mark.asyncio
async def test_oversized_input_is_rejected_not_silently_truncated(service_factory, monkeypatch):
    """הקוד הישן עשה ``text = text[:30000]`` — חיתוך שקט משלנו.

    מעכשיו ה-chunker אחראי לגודל, וחריגה היא כשל גלוי שלא יוצא לרשת בכלל.
    """
    make, mod, rec = service_factory
    monkeypatch.setattr(mod, "EMBEDDING_MAX_INPUT_BYTES", 1000)

    embedding, status, body = await make().generate_embedding_with_status(
        "x" * 5000, model="gemini-embedding-001", api_version="v1beta", dimensions=768
    )

    assert embedding is None
    assert status == mod.EMBEDDING_STATUS_INPUT_TOO_LONG
    assert "input_too_long" in body
    assert rec.request_count == 0, "oversized input still reached the provider"


@pytest.mark.asyncio
async def test_input_within_budget_is_sent_whole(service_factory, monkeypatch):
    make, mod, rec = service_factory
    monkeypatch.setattr(mod, "EMBEDDING_MAX_INPUT_BYTES", 1000)
    text = "y" * 900

    await make().generate_embedding_with_status(
        text, model="gemini-embedding-001", api_version="v1beta", dimensions=768
    )

    assert rec.seen["body"]["content"]["parts"][0]["text"] == text
