"""צורת הבקשה ל-Gemini וסיווג הכשלים שחוזרים ממנה.

הרקע (אישו #3332): ``gemini-embedding-001`` חותך בשקט קלט שחורג מ-2,048
טוקנים. בנוסף, מיצוי ה-retries על 429 החזיר סטטוס ``0`` — בדיוק כמו timeout
— ולכן ה-worker לא יכול היה להבחין בין מכסה שנגמרה לבין תקלת רשת, והמשיך
לשרוף קריאות על כל שאר הבאץ'.

הטסטים מרימים שרת HTTP מקומי אמיתי ובודקים את הבקשה שנחתה, במקום למקף את
הלקוח — כדי שבניית ה-payload והכותרות יישארו המסלול האמיתי.
"""

import asyncio
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
    batch_count_override = None

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except Exception:
            parsed = {}
        type(self).seen = {"body": parsed, "path": self.path}
        type(self).request_count += 1

        status = type(self).status_queue.pop(0) if type(self).status_queue else 200
        if status == 200 and self.path.endswith(":batchEmbedContents"):
            count = len(parsed.get("requests", []))
            if type(self).batch_count_override is not None:
                count = type(self).batch_count_override
            body = json.dumps({"embeddings": [{"values": [0.1] * 768} for _ in range(count)]}).encode()
        elif status == 200:
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
    _Recorder.batch_count_override = None
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


# ---------------------------------------------------------------------------
# ניסיון חוזר על 5xx
# ---------------------------------------------------------------------------
#
# הרקע (8.11.2026): בלוגים נראתה ריצה של ה-worker שבה 13 בקשות עברו והבקשה ה-14 קיבלה 503
# מ-Gemini. עד אז ``generate_embedding_with_status`` ניסה שוב רק אחרי 429 ו-timeout, וכל
# סטטוס אחר חזר מיד; ה-worker מסווג 5xx ככשל זמני ומחזיר את הקובץ לתור, ולכן 503 רגעי אחד
# גרם בסבב הבא לשלוח שוב את כל הצ'אנקים של הקובץ, גם את אלה שכבר הצליחו.


class _SleepRecorder:
    """עומד במקום ``asyncio`` של המודול: ``sleep`` נרשם ואינו ממתין, וכל השאר עובר ל-``asyncio``.

    ההחלפה היא רק בשם ``asyncio`` שבתוך ``services.embedding_service``, ולא ב-``asyncio.sleep``
    הגלובלי — httpx והלולאה ממשיכים לעבוד מול הפונקציה האמיתית.
    """

    def __init__(self):
        self.waits = []

    async def sleep(self, seconds):
        self.waits.append(seconds)

    def __getattr__(self, name):
        return getattr(asyncio, name)


@pytest.mark.asyncio
@pytest.mark.parametrize("server_error", [500, 502, 503, 504])
async def test_5xx_then_success_is_retried(service_factory, server_error):
    """שגיאה רגעית בצד של הספק נפתרת בתוך הקריאה, ולא חוזרת לקורא ככשל."""
    make, _mod, rec = service_factory
    rec.status_queue = [server_error, 200]

    embedding, status, _ = await make().generate_embedding_with_status(
        "hello", model="gemini-embedding-001", api_version="v1beta", dimensions=768
    )

    assert status == 200 and embedding and len(embedding) == 768
    assert rec.request_count == 2


@pytest.mark.asyncio
async def test_exhausted_5xx_reports_the_provider_status(service_factory):
    """אחרי ``MAX_RETRIES`` ניסיונות חוזר ה-5xx עצמו, ולא ``0``.

    הסטטוס הוא מה שהקורא מסווג לפיו (``classify_embedding_status``), ו-``0`` שמור לבקשה
    שלא קיבלה תשובת HTTP בכלל.
    """
    make, mod, rec = service_factory
    rec.status_queue = [503] * mod.MAX_RETRIES

    embedding, status, _ = await make().generate_embedding_with_status(
        "hello", model="gemini-embedding-001", api_version="v1beta", dimensions=768
    )

    assert embedding is None
    assert status == 503
    assert rec.request_count == mod.MAX_RETRIES


@pytest.mark.asyncio
async def test_5xx_backoff_grows_between_attempts(service_factory, monkeypatch):
    """ההמתנה בין הניסיונות גדלה, ואין המתנה אחרי הניסיון האחרון."""
    make, mod, rec = service_factory
    monkeypatch.setattr(mod, "RETRY_DELAY_SECONDS", 1.0)
    sleeps = _SleepRecorder()
    monkeypatch.setattr(mod, "asyncio", sleeps)
    rec.status_queue = [503] * mod.MAX_RETRIES

    await make().generate_embedding_with_status(
        "hello", model="gemini-embedding-001", api_version="v1beta", dimensions=768
    )

    expected = [mod._retry_backoff_seconds(a) for a in range(mod.MAX_RETRIES - 1)]
    assert sleeps.waits == expected
    assert all(later > earlier for earlier, later in zip(expected, expected[1:]))


@pytest.mark.asyncio
@pytest.mark.parametrize("client_error", [400, 401, 403, 404])
async def test_4xx_is_not_retried(service_factory, client_error):
    """אותה בקשה תקבל את אותה תשובה, ו-404 מפעיל אצל הקוראים self-heal ולא ניסיון חוזר.

    הטסט עובר גם על הקוד שלפני השינוי: הוא שומר שהניסיון החוזר נוסף ל-5xx בלבד.
    """
    make, _mod, rec = service_factory
    rec.status_queue = [client_error, 200]

    embedding, status, _ = await make().generate_embedding_with_status(
        "hello", model="gemini-embedding-001", api_version="v1beta", dimensions=768
    )

    assert embedding is None
    assert status == client_error
    assert rec.request_count == 1


@pytest.mark.asyncio
async def test_query_embedding_gives_up_after_bounded_5xx_retries(service_factory, monkeypatch):
    """החיפוש של המשתמש (``semantic_search``, דרך ``generate_embedding``) עדיין נופל לחיפוש טקסט.

    ב-5xx מתמשך הוא מקבל ``None`` אחרי ``MAX_RETRIES`` בקשות בדיוק — 5xx לא מפעיל את
    ה-fallback ל-v1 ולא את ה-self-heal, ששמורים ל-404 — וההמתנה הנוספת היא סכום
    ההמתנות של ``_retry_backoff_seconds``, בלי שום המתנה אחרת.
    """
    make, mod, rec = service_factory
    monkeypatch.setattr(mod, "RETRY_DELAY_SECONDS", 1.0)
    monkeypatch.setattr(mod, "get_embedding_settings_cached", lambda **_kw: None)
    sleeps = _SleepRecorder()
    monkeypatch.setattr(mod, "asyncio", sleeps)
    rec.status_queue = [503] * mod.MAX_RETRIES

    embedding = await make().generate_embedding("open a file")

    assert embedding is None
    assert rec.request_count == mod.MAX_RETRIES
    assert sum(sleeps.waits) == sum(
        mod._retry_backoff_seconds(a) for a in range(mod.MAX_RETRIES - 1)
    )


# ---------------------------------------------------------------------------
# אצווה אסינכרונית — ``EmbeddingService.embed_batch``
# ---------------------------------------------------------------------------
#
# הרקע (8.11.2026): ה-worker של הסניפטים עבר משליחת צ'אנק בכל בקשה לאצוות של
# ``batchEmbedContents``. הטסטים כאן בודקים את הלקוח מול שרת מקומי אמיתי; התרחישים של ה-worker
# עצמו ב-``tests/test_embedding_worker_batches.py``.


@pytest.mark.asyncio
async def test_embed_batch_sends_one_request_with_an_item_per_text(service_factory):
    make, _mod, rec = service_factory
    texts = ["alpha", "beta", "gamma"]

    vectors, status, detail = await make().embed_batch(
        texts, model="gemini-embedding-001", api_version="v1beta", dimensions=768
    )

    assert (status, detail) == (200, "")
    assert vectors is not None and len(vectors) == 3
    assert rec.request_count == 1
    assert rec.seen["path"] == "/v1beta/models/gemini-embedding-001:batchEmbedContents"
    items = rec.seen["body"]["requests"]
    assert [item["content"]["parts"][0]["text"] for item in items] == texts
    assert all(item["model"] == "models/gemini-embedding-001" for item in items)
    # ``outputDimensionality`` ברמה העליונה של כל פריט — ההערה ליד ``EMBEDDING_AUTO_TRUNCATE``.
    assert all(item["outputDimensionality"] == 768 for item in items)


@pytest.mark.asyncio
async def test_embed_batch_retries_5xx_and_succeeds(service_factory):
    make, _mod, rec = service_factory
    rec.status_queue = [503, 200]

    vectors, status, _ = await make().embed_batch(
        ["alpha", "beta"], model="gemini-embedding-001", api_version="v1beta", dimensions=768
    )

    assert status == 200 and vectors is not None and len(vectors) == 2
    assert rec.request_count == 2


@pytest.mark.asyncio
async def test_embed_batch_retries_429_and_reports_it_when_exhausted(service_factory):
    """בניגוד ל-``SyncEmbeddingClient``, שמחזיר 429 מיד: כאן אותה מדיניות כמו בבקשה בודדת."""
    make, mod, rec = service_factory
    rec.status_queue = [429] * mod.MAX_RETRIES

    vectors, status, detail = await make().embed_batch(
        ["alpha"], model="gemini-embedding-001", api_version="v1beta", dimensions=768
    )

    assert vectors is None
    assert status == 429
    assert detail.startswith("http 429")
    assert rec.request_count == mod.MAX_RETRIES


@pytest.mark.asyncio
async def test_embed_batch_returns_400_without_retrying(service_factory):
    make, _mod, rec = service_factory
    rec.status_queue = [400, 200]

    vectors, status, _ = await make().embed_batch(
        ["alpha", "beta"], model="gemini-embedding-001", api_version="v1beta", dimensions=768
    )

    assert vectors is None and status == 400
    assert rec.request_count == 1


@pytest.mark.asyncio
async def test_embed_batch_rejects_an_oversized_text_without_a_request(service_factory, monkeypatch):
    make, mod, rec = service_factory
    monkeypatch.setattr(mod, "EMBEDDING_MAX_INPUT_BYTES", 100)

    vectors, status, detail = await make().embed_batch(
        ["short", "x" * 500], model="gemini-embedding-001", api_version="v1beta", dimensions=768
    )

    assert vectors is None
    assert status == mod.EMBEDDING_STATUS_INPUT_TOO_LONG
    assert "index=1" in detail
    assert rec.request_count == 0


@pytest.mark.asyncio
async def test_embed_batch_does_not_map_a_short_answer(service_factory):
    """תשובה עם פחות וקטורים מטקסטים אינה מתפרשת כ"הראשונים" — היא כשל."""
    make, _mod, rec = service_factory
    rec.batch_count_override = 2

    vectors, status, detail = await make().embed_batch(
        ["a", "b", "c"], model="gemini-embedding-001", api_version="v1beta", dimensions=768
    )

    assert vectors is None
    assert status == 200 and detail.startswith("malformed_response")


@pytest.mark.asyncio
async def test_embed_batch_takes_an_interval_per_text_in_the_gate(service_factory, monkeypatch):
    """אצווה של N טקסטים מרחיקה את הבקשה הבאה כמו N בקשות בודדות."""
    make, mod, _rec = service_factory
    monkeypatch.setattr(mod, "EMBEDDING_MIN_INTERVAL_SECONDS", 5.0)
    monkeypatch.setattr(mod, "_next_allowed_ts", 0.0)
    import time

    before = time.monotonic()
    await make().embed_batch(
        ["a", "b", "c"], model="gemini-embedding-001", api_version="v1beta", dimensions=768
    )
    after = time.monotonic()

    assert before + 15.0 <= mod._next_allowed_ts <= after + 15.0


@pytest.mark.asyncio
async def test_a_single_request_still_takes_one_interval(service_factory, monkeypatch):
    make, mod, _rec = service_factory
    monkeypatch.setattr(mod, "EMBEDDING_MIN_INTERVAL_SECONDS", 5.0)
    monkeypatch.setattr(mod, "_next_allowed_ts", 0.0)
    import time

    before = time.monotonic()
    await make().generate_embedding_with_status(
        "a", model="gemini-embedding-001", api_version="v1beta", dimensions=768
    )
    after = time.monotonic()

    assert before + 5.0 <= mod._next_allowed_ts <= after + 5.0


@pytest.mark.parametrize(
    "interval,expected",
    [(1.2, 25), (2.0, 15), (0.0, 100), (0.1, 100), (100.0, 1)],
)
def test_paced_batch_size_is_half_a_minute_of_the_gate(monkeypatch, interval, expected):
    import services.embedding_service as mod

    monkeypatch.setattr(mod, "EMBEDDING_MIN_INTERVAL_SECONDS", interval)

    assert mod.paced_batch_size() == expected


@pytest.mark.asyncio
async def test_waiting_for_the_gate_does_not_reserve_a_slot(monkeypatch):
    """ה-worker מחכה לשער לפני שהוא בודק את הקובץ, ושומר חריץ רק בבקשה עצמה."""
    import time

    import services.embedding_service as mod

    sleeps = _SleepRecorder()
    monkeypatch.setattr(mod, "asyncio", sleeps)
    # מרווח אמיתי: עם ``0`` (ברירת המחדל בטסטים) גם שמירת חריץ לא הייתה מזיזה את השער.
    monkeypatch.setattr(mod, "EMBEDDING_MIN_INTERVAL_SECONDS", 5.0)
    busy_until = time.monotonic() + 30.0
    monkeypatch.setattr(mod, "_next_allowed_ts", busy_until)

    await mod.wait_for_throttle_gate()

    assert mod._next_allowed_ts == busy_until
    assert len(sleeps.waits) == 1 and 29.0 < sleeps.waits[0] <= 30.0
