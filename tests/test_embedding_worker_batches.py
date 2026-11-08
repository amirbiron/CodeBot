"""ה-worker של הסניפטים שולח את הצ'אנקים באצוות של ``batchEmbedContents`` — מקצה לקצה.

הרקע (8.11.2026): עד כה כל צ'אנק היה בקשת ``embedContent`` נפרדת, במרווח של
``EMBEDDING_MIN_INTERVAL_SECONDS`` — קובץ של 14 צ'אנקים היה 14 בקשות וכ-15 שניות. עכשיו הצ'אנקים
של קובץ נשלחים באצוות, וקובץ גדול מ-``paced_batch_size`` מתחלק לכמה קריאות.

הטסטים מריצים את ה-worker עם הלקוח האמיתי (``EmbeddingService`` ו-httpx), מול שרת HTTP מקומי
שמתנהג כמו ``batchEmbedContents``. רק שכבת המסד מוחלפת במקליטים. הווקטור של כל טקסט נגזר מהטקסט
עצמו (``_vector_for``), ולכן כל טסט יכול לבדוק שכל צ'אנק שנשמר קיבל את הווקטור של **הטקסט שלו**
— ולא של שכנו — גם אחרי חלוקה לאצוות וגם אחרי חציה.
"""

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import services.embedding_service as svc_mod
import services.embedding_worker as worker_mod
from services.chunking_service import (
    CHUNKER_VERSION,
    create_embedding_text,
    is_low_information_chunk,
    split_code_to_chunks,
)

FAKE_KEY = "AIzaSyFAKE0000_NOT_A_REAL_KEY_000000000"
MODEL = "gemini-embedding-001"
REJECT_MARKER = "REJECT_ME_PLEASE"


def _vector_for(text, dims):
    """וקטור שנגזר מהטקסט: שני טקסטים שונים מקבלים וקטורים שונים, ואותו טקסט — אותו וקטור."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [digest[i % 32] / 255.0 + (i // 32) / 1000.0 for i in range(dims)]


class _Gemini(BaseHTTPRequestHandler):
    """שרת שמתנהג כמו ``batchEmbedContents`` ו-``embedContent``, לפי תסריט שהטסט קובע.

    * ``statuses`` — סטטוס לכל בקשת אצווה, לפי הסדר; כשנגמרים — 200.
    * אצווה שאחד הטקסטים שלה מכיל ``REJECT_MARKER`` נדחית כולה ב-400, כמו ש-Gemini דוחה אצווה
      שיש בה פריט פסול (נבדק מול ה-API החי ב-8.11.2026).
    * ``native_dims`` — כשמוגדר, הווקטורים חוזרים במימד הזה בלי קשר ל-``outputDimensionality``.
    * ``native_dims_from_request`` — מאיזו בקשת אצווה (לפי הסדר, מאחד) ``native_dims`` חל.
    * ``forced_dims`` — פונקציה ממספר בקשת האצווה (מאחד) למימד שחוזר בה, או ``None``.
    """

    batch_requests: list = []
    single_requests: list = []
    statuses: list = []
    native_dims = None
    native_dims_from_request = 1
    forced_dims = None

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        cls = type(self)
        if self.path.endswith(":batchEmbedContents"):
            requests = body.get("requests", [])
            texts = [r["content"]["parts"][0]["text"] for r in requests]
            dims = requests[0].get("outputDimensionality") if requests else None
            cls.batch_requests.append({"texts": texts, "dims": dims})
            status = cls.statuses.pop(0) if cls.statuses else 200
            if status == 200 and any(REJECT_MARKER in text for text in texts):
                status = 400
            if status != 200:
                return self._reply(status, {"error": {"code": status, "status": "TEST", "message": "test"}})
            out_dims = dims or 3072
            if cls.native_dims and len(cls.batch_requests) >= cls.native_dims_from_request:
                out_dims = cls.native_dims
            if cls.forced_dims is not None and cls.forced_dims(len(cls.batch_requests)):
                out_dims = cls.forced_dims(len(cls.batch_requests))
            return self._reply(
                200, {"embeddings": [{"values": _vector_for(text, out_dims)} for text in texts]}
            )
        if self.path.endswith(":embedContent"):
            text = body["content"]["parts"][0]["text"]
            cls.single_requests.append(text)
            dims = body.get("outputDimensionality") or 3072
            return self._reply(200, {"embedding": {"values": _vector_for(text, dims)}})
        return self._reply(404, {"error": {"code": 404, "message": "unknown path"}})

    def _reply(self, status, payload):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):  # משתיק את הלוג של http.server בפלט הטסטים
        pass


class _Settings:
    model = MODEL
    api_version = "v1beta"
    dimensions = 768
    active_key = f"{MODEL}/768"
    legacy_key = f"{MODEL}/768"


@pytest.fixture()
def gemini():
    _Gemini.batch_requests = []
    _Gemini.single_requests = []
    _Gemini.statuses = []
    _Gemini.native_dims = None
    _Gemini.native_dims_from_request = 1
    _Gemini.forced_dims = None
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Gemini)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, _Gemini
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture()
def run(gemini, monkeypatch):
    """מרכיב worker עם לקוח אמיתי מול השרת, ומחזיר ``(worker_run, recorded)``."""
    port, _server = gemini

    # בלי השהיות: השער וה-backoff נבדקים בטסטים של השירות. ``_next_allowed_ts`` מתאפס כדי
    # שטסט קודם שדחף את השער לא יגרום לטסט כאן לחכות.
    monkeypatch.setattr(svc_mod, "EMBEDDING_MIN_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(svc_mod, "EMBEDDING_RATE_LIMIT_COOLDOWN_SECONDS", 0.0)
    monkeypatch.setattr(svc_mod, "RETRY_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(svc_mod, "_next_allowed_ts", 0.0)
    monkeypatch.setattr(svc_mod, "get_embedding_settings_cached", lambda **_kw: _Settings())

    service = svc_mod.EmbeddingService(api_key=FAKE_KEY)
    # רק הבסיס מוחלף; בניית הבקשה, הלקוח, הניסיונות והפענוח נשארים המסלול האמיתי.
    service._base_url = lambda av: f"http://127.0.0.1:{port}/{av}/models"
    monkeypatch.setattr(worker_mod, "get_embedding_service", lambda: service)

    recorded = {"saved": [], "updates": [], "events": [], "order": []}

    async def _save_snippet_chunks(*, user_id, snippet_id, chunks):
        recorded["saved"].append(list(chunks))
        return len(chunks)

    async def _update_status(**kwargs):
        recorded["updates"].append(kwargs)
        return True

    async def _is_latest(user_id, file_name, snippet_id):
        recorded["order"].append("is_latest")
        return True

    async def _gate():
        recorded["order"].append("gate")

    def _emit(event, severity="info", **fields):
        recorded["events"].append((event, fields))

    monkeypatch.setattr(worker_mod, "save_snippet_chunks", _save_snippet_chunks)
    monkeypatch.setattr(worker_mod, "update_snippet_embedding_status", _update_status)
    monkeypatch.setattr(worker_mod, "is_latest_active_snippet", _is_latest)
    monkeypatch.setattr(worker_mod, "wait_for_throttle_gate", _gate)
    monkeypatch.setattr(worker_mod, "emit_event", _emit)
    monkeypatch.setattr(worker_mod, "get_embedding_settings_cached", lambda **_kw: _Settings())

    async def _run(snippet):
        worker = worker_mod.EmbeddingWorker()
        try:
            await worker._process_snippet(snippet)
        finally:
            await service.close()

    recorded["service"] = service
    return _run, recorded


def _code(lines, *, marker_line=None):
    """קוד של ``lines`` שורות שונות זו מזו; ``marker_line`` מקבלת את ``REJECT_MARKER``."""
    out = []
    for i in range(lines):
        if i == marker_line:
            out.append(f"{REJECT_MARKER} = compute_total(items, {i})")
        else:
            out.append(f"value_{i} = compute_total(items_{i}, offset={i})  # line {i}")
    return "\n".join(out) + "\n"


def _snippet(code):
    return {
        "_id": "snippet-1",
        "user_id": 42,
        "file_name": "totals.py",
        "description": "running totals",
        "code": code,
        "programming_language": "python",
        "tags": ["math"],
        "needs_embedding": True,
        "needs_chunking": True,
    }


def _expected_chunks(snippet):
    """הצ'אנקים שה-worker שולח והטקסט של כל אחד — מאותן פונקציות שהוא משתמש בהן."""
    chunks = [c for c in split_code_to_chunks(snippet["code"]) if not is_low_information_chunk(c.content)]
    return [
        (
            position,
            chunk,
            create_embedding_text(
                code_chunk=chunk.content,
                title=snippet["file_name"],
                description=snippet["description"],
                tags=snippet["tags"],
                language=snippet["programming_language"],
            ),
        )
        for position, chunk in enumerate(chunks)
    ]


def _assert_every_vector_belongs_to_its_chunk(saved_docs, snippet, dims):
    """כל צ'אנק שנשמר: המיקום, השורות והטקסט שלו, והווקטור של **הטקסט שלו**."""
    expected = {position: (chunk, text) for position, chunk, text in _expected_chunks(snippet)}
    for doc in saved_docs:
        chunk, text = expected[doc["chunkIndex"]]
        assert doc["codeChunk"] == chunk.content
        assert (doc["startLine"], doc["endLine"]) == (chunk.start_line, chunk.end_line)
        assert doc["chunkEmbedding"] == _vector_for(text, dims), (
            f"chunk {doc['chunkIndex']} got the vector of another text"
        )
        assert doc["embeddingDim"] == dims


@pytest.mark.asyncio
async def test_a_small_file_is_one_request(run, gemini):
    _port, server = gemini
    worker_run, recorded = run
    snippet = _snippet(_code(5))

    await worker_run(snippet)

    expected = _expected_chunks(snippet)
    assert len(server.batch_requests) == 1
    assert server.batch_requests[0]["texts"] == [text for _p, _c, text in expected]
    assert server.single_requests == []
    saved = recorded["saved"][-1]
    assert len(saved) == len(expected)
    _assert_every_vector_belongs_to_its_chunk(saved, snippet, 768)
    assert recorded["updates"][-1]["needs_embedding"] is False
    assert recorded["updates"][-1]["chunk_count"] == len(expected)
    assert recorded["updates"][-1]["chunker_version"] == CHUNKER_VERSION


@pytest.mark.asyncio
async def test_a_file_above_the_batch_size_is_split_into_requests(run, gemini, monkeypatch):
    _port, server = gemini
    worker_run, recorded = run
    monkeypatch.setattr(worker_mod, "paced_batch_size", lambda: 4)
    snippet = _snippet(_code(400))
    expected = _expected_chunks(snippet)
    assert len(expected) > 8, "the file must need more than two batches"

    await worker_run(snippet)

    sizes = [len(r["texts"]) for r in server.batch_requests]
    assert max(sizes) <= 4
    assert sum(sizes) == len(expected)
    assert [t for r in server.batch_requests for t in r["texts"]] == [text for _p, _c, text in expected]
    saved = recorded["saved"][-1]
    assert sorted(doc["chunkIndex"] for doc in saved) == list(range(len(expected)))
    _assert_every_vector_belongs_to_its_chunk(saved, snippet, 768)
    assert recorded["updates"][-1]["needs_embedding"] is False


@pytest.mark.asyncio
async def test_a_503_that_passes_on_retry_stores_everything(run, gemini):
    _port, server = gemini
    worker_run, recorded = run
    server.statuses = [503]
    snippet = _snippet(_code(5))

    await worker_run(snippet)

    assert len(server.batch_requests) == 2
    saved = recorded["saved"][-1]
    assert len(saved) == len(_expected_chunks(snippet))
    _assert_every_vector_belongs_to_its_chunk(saved, snippet, 768)
    assert recorded["updates"][-1]["needs_embedding"] is False


@pytest.mark.asyncio
async def test_a_400_on_one_chunk_rejects_only_that_chunk(run, gemini, monkeypatch):
    """הספק דוחה את האצווה כולה; ה-worker חוצה אותה עד שהצ'אנק הפסול נשאר לבדו."""
    _port, server = gemini
    worker_run, recorded = run
    monkeypatch.setattr(worker_mod, "paced_batch_size", lambda: 8)
    snippet = _snippet(_code(400, marker_line=170))
    expected = _expected_chunks(snippet)
    bad = [position for position, _c, text in expected if REJECT_MARKER in text]
    assert len(bad) == 1, "the marker must land in exactly one chunk"

    await worker_run(snippet)

    saved = recorded["saved"][-1]
    assert sorted(doc["chunkIndex"] for doc in saved) == [p for p, _c, _t in expected if p not in bad]
    _assert_every_vector_belongs_to_its_chunk(saved, snippet, 768)
    rejected = [fields for event, fields in recorded["events"] if event == "embedding_chunk_rejected"]
    bad_chunk = next(c for p, c, _t in expected if p == bad[0])
    assert [r["chunk_index"] for r in rejected] == [bad_chunk.index]
    assert recorded["updates"][-1]["needs_embedding"] is False, "a rejected chunk must not requeue the file"


@pytest.mark.asyncio
async def test_an_oversized_chunk_is_rejected_before_it_is_sent(run, gemini, monkeypatch):
    """טקסט מעל ``EMBEDDING_MAX_INPUT_BYTES`` נדחה בלי לשלוח אותו, ואינו מפיל את האצווה."""
    _port, server = gemini
    worker_run, recorded = run
    monkeypatch.setattr(worker_mod, "paced_batch_size", lambda: 4)
    snippet = _snippet(_code(400))
    expected = _expected_chunks(snippet)
    smallest = min(len(text.encode("utf-8")) for _p, _c, text in expected)
    largest = max(len(text.encode("utf-8")) for _p, _c, text in expected)
    assert smallest < largest
    monkeypatch.setattr(svc_mod, "EMBEDDING_MAX_INPUT_BYTES", smallest)
    handed = []
    real_embed_batch = recorded["service"].embed_batch

    async def _spy(texts, **kwargs):
        handed.append(list(texts))
        return await real_embed_batch(texts, **kwargs)

    monkeypatch.setattr(recorded["service"], "embed_batch", _spy)

    await worker_run(snippet)

    # בלי הבדיקה ב-worker התוצאה הייתה דומה — הלקוח מחזיר 413 בלי בקשה, והחציה מבודדת — אבל
    # כל אצווה עם טקסט כזה הייתה נחצית. הבדיקה היא שה-worker לא מוסר ללקוח טקסט שלא ייכנס.
    assert all(len(t.encode("utf-8")) <= smallest for batch in handed for t in batch)

    fits = [p for p, _c, text in expected if len(text.encode("utf-8")) <= smallest]
    sent = [t for r in server.batch_requests for t in r["texts"]]
    assert sent == [text for p, _c, text in expected if p in fits], "an oversized text reached the provider"
    # הבדיקה קורית לפני שהאצוות מורכבות: הן נבנות רק ממה שנכנס, ואין חציה.
    assert len(server.batch_requests) == -(-len(fits) // 4)
    saved = recorded["saved"][-1]
    assert sorted(doc["chunkIndex"] for doc in saved) == fits
    _assert_every_vector_belongs_to_its_chunk(saved, snippet, 768)
    rejected = [fields for event, fields in recorded["events"] if event == "embedding_chunk_rejected"]
    assert len(rejected) == len(expected) - len(fits)
    assert recorded["updates"][-1]["needs_embedding"] is False


@pytest.mark.asyncio
async def test_quota_stops_without_touching_stored_chunks(run, gemini):
    """429 שמוצו עליו הניסיונות: ``EmbeddingQuotaExhausted``, ושום דבר לא נמחק או נכתב."""
    _port, server = gemini
    worker_run, recorded = run
    server.statuses = [429] * svc_mod.MAX_RETRIES

    with pytest.raises(worker_mod.EmbeddingQuotaExhausted):
        await worker_run(_snippet(_code(5)))

    assert len(server.batch_requests) == svc_mod.MAX_RETRIES
    assert recorded["saved"] == []
    assert recorded["updates"] == []


@pytest.mark.asyncio
async def test_a_missing_model_self_heals_and_restarts_the_file(run, gemini, monkeypatch):
    """404 באצווה השנייה: self-heal, וכל הקובץ מתחיל מחדש — כולל האצווה שכבר הצליחה."""
    _port, server = gemini
    worker_run, recorded = run
    monkeypatch.setattr(worker_mod, "paced_batch_size", lambda: 4)
    server.statuses = [200, 404]
    snippet = _snippet(_code(200))
    expected = _expected_chunks(snippet)
    assert len(expected) > 4

    await worker_run(snippet)

    assert server.single_requests == ["healthcheck"], "self-heal did not run"
    saved = recorded["saved"][-1]
    assert sorted(doc["chunkIndex"] for doc in saved) == list(range(len(expected)))
    _assert_every_vector_belongs_to_its_chunk(saved, snippet, 768)
    assert recorded["updates"][-1]["needs_embedding"] is False


@pytest.mark.asyncio
async def test_a_dimension_mismatch_drops_the_fixed_dimension_for_the_whole_file(
    run, gemini, monkeypatch
):
    """422 (מימד שונה מהמבוקש) באצווה הראשונה: היא נשלחת שוב בלי מימד קבוע, וכך גם כל השאר."""
    _port, server = gemini
    worker_run, recorded = run
    monkeypatch.setattr(worker_mod, "paced_batch_size", lambda: 4)
    server.native_dims = 3072
    snippet = _snippet(_code(200))
    expected = _expected_chunks(snippet)

    await worker_run(snippet)

    dims_sent = [r["dims"] for r in server.batch_requests]
    assert dims_sent[0] == 768
    assert all(d is None for d in dims_sent[1:]), dims_sent
    saved = recorded["saved"][-1]
    assert len(saved) == len(expected)
    _assert_every_vector_belongs_to_its_chunk(saved, snippet, 3072)
    update = recorded["updates"][-1]
    assert update["needs_embedding"] is False
    assert (update["embedding_dim"], update["embedding_model_key"]) == (3072, f"{MODEL}/3072")


@pytest.mark.asyncio
async def test_vectors_of_two_dimensions_are_never_stored_together(run, gemini, monkeypatch):
    """האצווה הראשונה חזרה ב-768; השנייה ב-3072. השנייה היא כשל זמני, ולא וקטורים מעורבים."""
    _port, server = gemini
    worker_run, recorded = run
    monkeypatch.setattr(worker_mod, "paced_batch_size", lambda: 4)
    server.native_dims = 3072
    server.native_dims_from_request = 2
    snippet = _snippet(_code(200))

    await worker_run(snippet)

    saved = recorded["saved"][-1]
    assert saved, "the first batch should still be stored"
    assert {doc["embeddingDim"] for doc in saved} == {768}
    assert {len(doc["chunkEmbedding"]) for doc in saved} == {768}
    assert recorded["updates"][-1]["needs_embedding"] is True


@pytest.mark.asyncio
async def test_a_transient_failure_after_an_earlier_batch_keeps_what_succeeded(
    run, gemini, monkeypatch
):
    """אצווה שנכשלה זמנית אחרי שקודמתה הצליחה: מה שהצליח נשמר, והקובץ חוזר לתור.

    זה מתעד את המצב, לא מצב רצוי: בסבב הבא כל הצ'אנקים נשלחים שוב, גם אלה שנשמרו, כי
    ``save_snippet_chunks`` מוחק את כל הצ'אנקים של הקובץ לפני שהוא כותב, ואין בצ'אנק שנשמר
    שום סימן לטקסט שהווקטור שלו נבנה ממנו.
    """
    _port, server = gemini
    worker_run, recorded = run
    monkeypatch.setattr(worker_mod, "paced_batch_size", lambda: 4)
    server.statuses = [200] + [503] * svc_mod.MAX_RETRIES
    snippet = _snippet(_code(300))
    expected = _expected_chunks(snippet)
    assert len(expected) > 8

    await worker_run(snippet)

    saved = recorded["saved"][-1]
    stored = sorted(doc["chunkIndex"] for doc in saved)
    assert stored == [p for p, _c, _t in expected if not 4 <= p < 8]
    _assert_every_vector_belongs_to_its_chunk(saved, snippet, 768)
    assert recorded["updates"][-1]["needs_embedding"] is True


@pytest.mark.asyncio
async def test_the_gate_is_awaited_before_the_latest_version_check(run, gemini):
    """ההמתנה לשער לפני הבדיקה, כדי שלא תיפול בחלון שבין הבדיקה לכתיבה."""
    worker_run, recorded = run

    await worker_run(_snippet(_code(5)))

    assert recorded["order"][:2] == ["gate", "is_latest"]


@pytest.mark.asyncio
async def test_a_later_batch_in_another_dimension_is_not_stored_with_the_first(
    run, gemini, monkeypatch
):
    """אחרי שהמימד הקבוע ירד (422), אצווה מאוחרת שחוזרת במימד אחר אינה נשמרת לצד הקודמות.

    בלי מימד מבוקש, הפענוח של התשובה אינו בודק אורך — רק ה-worker יודע מה המימד של הקובץ.
    """
    _port, server = gemini
    worker_run, recorded = run
    monkeypatch.setattr(worker_mod, "paced_batch_size", lambda: 4)
    server.forced_dims = lambda n: 3072 if n <= 3 else 1536
    snippet = _snippet(_code(400))
    assert len(_expected_chunks(snippet)) > 12, "the file must reach a fourth request"

    await worker_run(snippet)

    assert [r["dims"] for r in server.batch_requests][:3] == [768, None, None]
    saved = recorded["saved"][-1]
    assert saved and {len(doc["chunkEmbedding"]) for doc in saved} == {3072}
    assert recorded["updates"][-1]["needs_embedding"] is True


# ---------------------------------------------------------------------------
# ‏400 על הבקשה כולה מול 400 על צ'אנק
# ---------------------------------------------------------------------------
#
# Gemini מחזיר ``400 INVALID_ARGUMENT`` גם על פריט פסול וגם על בקשה פסולה כולה — מפתח לא תקף,
# או ``outputDimensionality`` שהמודל לא תומך בו (נבדק מול ה-API החי ב-8.11.2026). בלי הבחנה,
# כל קובץ בתור היה נחצה עד הסוף, כל הצ'אנקים שלו נדחים והקובץ מסומן כגמור, בלי וקטורים.


@pytest.mark.asyncio
async def test_a_request_level_400_stops_without_touching_the_file(run, gemini):
    """גם בקשת הביקורת נדחתה: הבעיה בבקשה. אין חציה, אין דחייה, ואין כתיבה לקובץ."""
    _port, server = gemini
    worker_run, recorded = run
    server.statuses = [400, 400]

    with pytest.raises(worker_mod.EmbeddingRequestRejected):
        await worker_run(_snippet(_code(200)))

    assert len(server.batch_requests) == 2, [len(r["texts"]) for r in server.batch_requests]
    assert server.batch_requests[1]["texts"] == [worker_mod._CONTROL_TEXT]
    assert recorded["saved"] == [], "stored chunks were deleted because of a request-level error"
    assert recorded["updates"] == [], "the file was marked as handled"
    assert not [e for e, _f in recorded["events"] if e == "embedding_chunk_rejected"]


@pytest.mark.asyncio
async def test_a_400_in_the_first_batch_checks_the_request_once_then_splits(
    run, gemini, monkeypatch
):
    """הצ'אנק הפסול באצווה הראשונה: בקשת ביקורת אחת מראה שהבקשה תקינה, ואז החציה מבודדת אותו."""
    _port, server = gemini
    worker_run, recorded = run
    monkeypatch.setattr(worker_mod, "paced_batch_size", lambda: 8)
    snippet = _snippet(_code(400, marker_line=3))
    expected = _expected_chunks(snippet)
    bad = [position for position, _c, text in expected if REJECT_MARKER in text]
    assert bad == [0]

    await worker_run(snippet)

    controls = [r for r in server.batch_requests if r["texts"] == [worker_mod._CONTROL_TEXT]]
    assert len(controls) == 1
    saved = recorded["saved"][-1]
    assert sorted(doc["chunkIndex"] for doc in saved) == [p for p, _c, _t in expected if p != 0]
    _assert_every_vector_belongs_to_its_chunk(saved, snippet, 768)
    rejected = [fields for event, fields in recorded["events"] if event == "embedding_chunk_rejected"]
    assert len(rejected) == 1
    assert recorded["updates"][-1]["needs_embedding"] is False


@pytest.mark.asyncio
async def test_a_400_after_an_accepted_batch_needs_no_control_request(run, gemini, monkeypatch):
    """אצווה של הקובץ כבר התקבלה, ולכן 400 מאוחר יותר הוא של הצ'אנקים — בלי בקשת ביקורת."""
    _port, server = gemini
    worker_run, _recorded = run
    monkeypatch.setattr(worker_mod, "paced_batch_size", lambda: 4)
    snippet = _snippet(_code(400, marker_line=250))
    expected = _expected_chunks(snippet)
    bad = [position for position, _c, text in expected if REJECT_MARKER in text]
    assert bad and bad[0] >= 4, "the marker must not be in the first batch"

    await worker_run(snippet)

    assert not [r for r in server.batch_requests if r["texts"] == [worker_mod._CONTROL_TEXT]]


@pytest.mark.asyncio
async def test_when_the_control_request_fails_transiently_nothing_is_rejected(run, gemini):
    """הביקורת נכשלה זמנית: אי אפשר לדעת, ולכן הצ'אנקים לא נדחים והקובץ חוזר לתור."""
    _port, server = gemini
    worker_run, recorded = run
    server.statuses = [400] + [503] * svc_mod.MAX_RETRIES
    snippet = _snippet(_code(5))

    await worker_run(snippet)

    assert len(server.batch_requests) == 1 + svc_mod.MAX_RETRIES, "the batch was split anyway"
    assert not [e for e, _f in recorded["events"] if e == "embedding_chunk_rejected"]
    assert recorded["updates"][-1]["needs_embedding"] is True
