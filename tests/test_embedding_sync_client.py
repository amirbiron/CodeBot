"""הלקוח הסינכרוני להטמעות (``SyncEmbeddingClient``) והסיווג המשותף של סטטוסים.

הלקוח רץ בוובאפ (מעבר האינדוקס של התיעוד), ולכן הוא נבדק כמו שהוא יוצא לרשת: התעבורה
מוחלפת ב-``httpx.MockTransport``, שמקבל את הבקשה אחרי ש-httpx בנה אותה — כתובת, כותרות
וגוף בדיוק כמו שהיו נשלחים. מה שנבדק: המפתח בכותרת ולא בכתובת, ``outputDimensionality``
ברמה העליונה, 429 שחוזר מיד ודוחף את השער המשותף, ניסיון חוזר רק לכשל זמני, דדליין
שנבדק לפני כל ניסיון, ותשובה שאינה בצורה הצפויה שאינה הופכת לווקטורים.
"""

from __future__ import annotations

import json
import math
import threading
import time

import httpx
import pytest

import services.embedding_service as svc
import services.embedding_worker as worker

FAKE_KEY = "AIzaSyFAKE0000_NOT_A_REAL_KEY_000000000"
MODEL = "gemini-embedding-001"
GOOGLE_BATCH_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:batchEmbedContents"
)


@pytest.fixture(autouse=True)
def _no_real_waiting(monkeypatch):
    """השער המשותף מתחיל פתוח, וההמתנה בין ניסיונות אפס — אלא אם טסט קובע אחרת."""
    monkeypatch.setattr(svc, "EMBEDDING_MIN_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(svc, "EMBEDDING_RATE_LIMIT_COOLDOWN_SECONDS", 0.0)
    monkeypatch.setattr(svc, "RETRY_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(svc, "_next_allowed_ts", 0.0)


def _embeddings(count: int, dim: int = 768) -> dict:
    return {"embeddings": [{"values": [float(i)] * dim} for i in range(count)]}


def _client(responses, *, api_key: str = FAKE_KEY):
    """לקוח שהתעבורה שלו עונה מהרשימה לפי הסדר, ורושם כל בקשה."""
    seen: list[httpx.Request] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        answer = queue.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        status, body = answer
        if isinstance(body, (dict, list)):
            return httpx.Response(status, json=body)
        return httpx.Response(status, text=body)

    client = svc.SyncEmbeddingClient(api_key=api_key, transport=httpx.MockTransport(handler))
    return client, seen


def _embed(client, texts, *, dimensions: int = 768, deadline: float | None = None):
    return client.embed_batch(
        texts,
        model=f"models/{MODEL}",
        api_version="v1beta",
        dimensions=dimensions,
        deadline=time.monotonic() + 60 if deadline is None else deadline,
    )


# ---------------------------------------------------------------------------
# צורת הבקשה
# ---------------------------------------------------------------------------


def test_the_key_rides_in_a_header_and_dimensions_sit_at_the_top_of_each_request(monkeypatch):
    monkeypatch.setattr(svc, "EMBEDDING_AUTO_TRUNCATE", True)
    client, seen = _client([(200, _embeddings(2))])

    vectors, status, detail = _embed(client, ["אחד", "שתיים"])

    assert (status, detail) == (200, "")
    assert len(vectors) == 2
    [request] = seen
    assert str(request.url) == GOOGLE_BATCH_URL
    assert request.url.query == b""
    assert FAKE_KEY not in str(request.url)
    assert request.headers["x-goog-api-key"] == FAKE_KEY
    body = json.loads(request.content)
    assert body == {
        "requests": [
            {
                "model": f"models/{MODEL}",
                "content": {"parts": [{"text": text}]},
                "outputDimensionality": 768,
            }
            for text in ("אחד", "שתיים")
        ]
    }


def test_auto_truncate_off_adds_the_config_block_and_keeps_dimensions_at_the_top(monkeypatch):
    monkeypatch.setattr(svc, "EMBEDDING_AUTO_TRUNCATE", False)
    client, seen = _client([(200, _embeddings(1))])

    _embed(client, ["טקסט"])

    [item] = json.loads(seen[0].content)["requests"]
    assert item["embedContentConfig"] == {"autoTruncate": False}
    assert item["outputDimensionality"] == 768
    assert "outputDimensionality" not in item["embedContentConfig"]


def test_the_async_service_builds_the_same_request():
    """שני הלקוחות בונים את הבקשה באותה פונקציה, ולכן אין צורה שנייה שתיסחף."""
    assert svc.build_embed_content_request("x", model=f"models/{MODEL}", dimensions=768) == {
        "model": f"models/{MODEL}",
        "content": {"parts": [{"text": "x"}]},
        "outputDimensionality": 768,
        **({} if svc.EMBEDDING_AUTO_TRUNCATE else {"embedContentConfig": {"autoTruncate": False}}),
    }


def test_vectors_come_back_in_the_order_of_the_texts():
    client, _seen = _client([(200, _embeddings(3, dim=4))])

    vectors, status, _ = _embed(client, ["a", "b", "c"], dimensions=4)

    assert status == 200
    assert [vector[0] for vector in vectors] == [0.0, 1.0, 2.0]


def test_a_client_without_a_key_sends_nothing():
    client, seen = _client([], api_key="")

    assert _embed(client, ["x"]) == (None, 0, "missing_api_key")
    assert seen == []


@pytest.mark.parametrize("count", [0, svc.GEMINI_MAX_BATCH_REQUESTS + 1])
def test_a_batch_outside_the_limit_is_a_caller_bug(count):
    client, seen = _client([])
    with pytest.raises(ValueError):
        _embed(client, ["x"] * count)
    assert seen == []


def test_an_empty_text_is_a_caller_bug():
    client, seen = _client([])
    with pytest.raises(ValueError):
        _embed(client, ["x", "  "])
    assert seen == []


def test_an_oversized_text_is_refused_before_anything_is_sent(monkeypatch):
    monkeypatch.setattr(svc, "EMBEDDING_MAX_INPUT_BYTES", 10)
    client, seen = _client([])

    vectors, status, detail = _embed(client, ["short", "ש" * 6])

    assert (vectors, status) == (None, svc.EMBEDDING_STATUS_INPUT_TOO_LONG)
    assert "index=1" in detail and "bytes=12" in detail
    assert seen == []


# ---------------------------------------------------------------------------
# כשלים: 429, זמני, קבוע, ושלא ידוע
# ---------------------------------------------------------------------------


def test_429_returns_at_once_and_pushes_the_shared_gate(monkeypatch):
    monkeypatch.setattr(svc, "EMBEDDING_RATE_LIMIT_COOLDOWN_SECONDS", 30.0)
    quota = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "quota"}}
    client, seen = _client([(429, quota)] * 3)

    before = time.monotonic()
    vectors, status, detail = _embed(client, ["x"])

    assert (vectors, status) == (None, 429)
    assert detail == "http 429: RESOURCE_EXHAUSTED: quota"
    assert len(seen) == 1, "a 429 was retried inside the client"
    # כל קורא אחר — כולל השירות האסינכרוני — יחכה עכשיו לפחות את ה-cooldown.
    assert svc._next_allowed_ts >= before + 30.0


def test_a_server_error_is_retried_and_can_still_succeed():
    client, seen = _client([(500, "boom"), (503, "busy"), (200, _embeddings(1))])

    vectors, status, _ = _embed(client, ["x"])

    assert status == 200 and vectors
    assert len(seen) == 3


def test_a_server_error_that_does_not_go_away_is_reported():
    client, seen = _client([(500, "boom")] * svc.MAX_RETRIES)

    vectors, status, detail = _embed(client, ["x"])

    assert (vectors, status, detail) == (None, 500, "http 500")
    assert len(seen) == svc.MAX_RETRIES


@pytest.mark.parametrize("status", [400, 404, 409])
def test_a_permanent_or_unknown_status_is_not_retried(status):
    client, seen = _client([(status, {"error": {"message": "no"}})] * svc.MAX_RETRIES)

    vectors, returned, _ = _embed(client, ["x"])

    assert (vectors, returned) == (None, status)
    assert len(seen) == 1


def test_transport_errors_are_retried_then_reported():
    failure = httpx.ConnectError("refused")
    client, seen = _client([failure] * svc.MAX_RETRIES)

    assert _embed(client, ["x"]) == (None, 0, "transport_error: ConnectError")
    assert len(seen) == svc.MAX_RETRIES


def test_an_exception_outside_the_transport_is_not_swallowed():
    """רק תת-העץ של התעבורה נתפס. חריגה אחרת היא באג, ועולה."""
    client, _seen = _client([RuntimeError("bug")])

    with pytest.raises(RuntimeError, match="bug"):
        _embed(client, ["x"])


def test_the_error_summary_carries_no_headers_and_no_key():
    denied = {"error": {"code": 403, "status": "PERMISSION_DENIED", "message": "API key not valid"}}
    client, _seen = _client([(403, denied)] * svc.MAX_RETRIES)

    _vectors, status, detail = _embed(client, ["x"])

    assert status == 403
    assert detail == "http 403: PERMISSION_DENIED: API key not valid"
    assert FAKE_KEY not in detail


# ---------------------------------------------------------------------------
# דדליין
# ---------------------------------------------------------------------------


def test_a_deadline_that_already_passed_sends_nothing():
    client, seen = _client([(200, _embeddings(1))])

    assert _embed(client, ["x"], deadline=time.monotonic() - 1) == (None, 0, "deadline_exceeded")
    assert seen == []


def test_waiting_for_the_gate_past_the_deadline_sends_nothing(monkeypatch):
    monkeypatch.setattr(svc, "_next_allowed_ts", time.monotonic() + 120)
    client, seen = _client([(200, _embeddings(1))])

    started = time.monotonic()
    result = _embed(client, ["x"], deadline=time.monotonic() + 1)

    assert result == (None, 0, "deadline_exceeded")
    assert seen == []
    assert time.monotonic() - started < 1, "the client slept before refusing"


def test_each_request_gets_only_the_time_left_until_the_deadline():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["timeout"] = request.extensions["timeout"]
        return httpx.Response(200, json=_embeddings(1))

    client = svc.SyncEmbeddingClient(api_key=FAKE_KEY, transport=httpx.MockTransport(handler))
    client.embed_batch(
        ["x"], model=MODEL, api_version="v1beta", dimensions=768, deadline=time.monotonic() + 5
    )

    assert all(0 < value <= 5 for value in captured["timeout"].values())


# ---------------------------------------------------------------------------
# תשובה שאינה בצורה הצפויה
# ---------------------------------------------------------------------------


def test_a_vector_of_the_wrong_size_is_a_dimension_mismatch():
    client, _seen = _client([(200, _embeddings(1, dim=3072))])

    assert _embed(client, ["x"]) == (None, 422, "dimension_mismatch expected=768 actual=3072")


@pytest.mark.parametrize(
    "body",
    [
        "not json",
        {"embeddings": "nope"},
        {"embeddings": [{"values": [0.1] * 768}]},  # אחד במקום שניים
        {"embeddings": [{"values": [0.1] * 768}, {"values": []}]},
        {"embeddings": [{"values": [0.1] * 768}, {"values": [True] * 768}]},
        {"embeddings": [{"values": [0.1] * 768}, {"values": ["0.1"] * 768}]},
        {"embeddings": [{"values": [0.1] * 768}, {"vals": [0.1] * 768}]},
        [{"values": [0.1] * 768}],
    ],
)
def test_a_malformed_answer_does_not_become_vectors(body):
    client, _seen = _client([(200, body)])

    vectors, status, detail = _embed(client, ["x", "y"])

    assert (vectors, status) == (None, 200)
    assert detail.startswith("malformed_response")


def test_a_non_finite_number_does_not_become_a_vector():
    nan_body = '{"embeddings": [{"values": [NaN, 0.1]}]}'
    client, _seen = _client([(200, nan_body)])

    vectors, status, detail = _embed(client, ["x"], dimensions=2)

    assert (vectors, status, detail) == (None, 200, "malformed_response: embedding 0")
    assert math.isnan(json.loads(nan_body)["embeddings"][0]["values"][0])


# ---------------------------------------------------------------------------
# השער המשותף, והסיווג המשותף
# ---------------------------------------------------------------------------


def test_the_gate_gives_threads_distinct_slots(monkeypatch):
    """השער הוא נעילה של threads: קוראים מקבילים מקבלים חריצים שונים, במרווח הקבוע."""
    monkeypatch.setattr(svc, "EMBEDDING_MIN_INTERVAL_SECONDS", 0.5)
    callers = 8
    barrier = threading.Barrier(callers)
    starts: list[float] = []
    guard = threading.Lock()

    def reserve():
        barrier.wait()
        now = time.monotonic()
        wait = svc._reserve_throttle_slot()
        with guard:
            starts.append(now + wait)

    threads = [threading.Thread(target=reserve) for _ in range(callers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    starts.sort()
    gaps = [later - earlier for earlier, later in zip(starts, starts[1:])]
    assert len(starts) == callers
    assert all(gap > 0.45 for gap in gaps), gaps


@pytest.mark.parametrize(
    "status,expected",
    [
        (404, svc.FAILURE_MODEL_MISSING),
        (429, svc.FAILURE_QUOTA),
        (400, svc.FAILURE_PERMANENT),
        (413, svc.FAILURE_PERMANENT),
        (0, svc.FAILURE_TRANSIENT),
        (401, svc.FAILURE_TRANSIENT),
        (403, svc.FAILURE_TRANSIENT),
        (408, svc.FAILURE_TRANSIENT),
        (500, svc.FAILURE_TRANSIENT),
        (599, svc.FAILURE_TRANSIENT),
        (200, svc.FAILURE_UNKNOWN),
        (409, svc.FAILURE_UNKNOWN),
        (422, svc.FAILURE_UNKNOWN),
    ],
)
def test_every_status_has_one_shared_meaning(status, expected):
    assert svc.classify_embedding_status(status) == expected


@pytest.mark.parametrize("status", [200, 409, 422])
def test_the_snippet_worker_still_requeues_a_status_it_does_not_know(status):
    """ה-worker מחזיר לתור גם סטטוס לא ידוע, כמו לפני שהמיפוי עבר — עכשיו כהכרעה כתובה."""
    assert worker._classify_status(status) == worker.FAILURE_TRANSIENT
