""""חלץ" בחיפוש בתיעוד — ``services/docs_extract_service.py`` ו-``POST /api/search/docs/extract``.

הסעיפים נכתבים במעבר אמיתי של האינדקס (``fill`` של ``_docs_index_harness``), והחילוץ קורא אותם מהמסד לפי
המזהים. מודל השפה הוא ``_FakeLLM``, שמקליט את הקריאה ומחזיר את מה שהטסט קבע; הצורה של הבקשה שה-SDK האמיתי
שולח נבדקת מול שרת מקומי (``test_the_request_the_sdk_sends_carries_only_the_model_and_the_messages``). תקרת
הזמן מול רשת אמיתית תחת gevent — ב-``tests/test_docs_extract_deadline_under_gevent.py``.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import gevent
import httpx2
import openai
import pytest
from openai.types.chat import ChatCompletion
from pymongo.errors import ExecutionTimeout, OperationFailure, ServerSelectionTimeoutError

# ‏``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _docs_index_harness import admin_app_for, fill, make_world, page, section
from _fake_mongo import FakeCollection, FakeDB

from services import docs_extract_service as svc
from services import docs_search_contract as contract
from services import docs_search_service as docs_search
from services.docs_search_service import DocsSearchError
from services.llm_endpoint_settings import LlmEndpoint

ENV = {
    "DOCS_EXTRACT_API_KEY": "extract-key-123",
    "DOCS_EXTRACT_BASE_URL": "https://llm.example.test/v1/",
    "DOCS_EXTRACT_MODEL": "extract-model",
}
QUERY = "איך מגבילים את זמן החילוץ?"
DEADLINE_QUOTE = "התקרה היא **שישים שניות** לקריאה כולה."
HEADLINE = "feat: כפתור חלץ."


def _pages():
    """שני סעיפים בעמוד אחד, ועדכון ביומן עדכונים — שהקישור שלו קופץ לפתיח שלו."""
    return [
        page("webapp/search.html", "docs/webapp/search.rst",
             section("search-basics", "חיפוש", "יסודות", markdown="החיפוש מחזיר סעיפים לפי דמיון."),
             section("search-deadline", "חיפוש", "תקרות זמן", markdown=f"פתיח.\n\n{DEADLINE_QUOTE}\n\nסוף.")),
        page("whats-new/2026-11.html", "docs/whats-new/2026-11.rst", section("w", "What’s New", markdown=""),
             section("id3", "What’s New", "2026-11-28", markdown=f"-   **{HEADLINE}** מחלץ קטע מהסעיפים.")),
    ]


def _completion(content, finish_reason="stop"):
    # אובייקט אמיתי של ה-SDK, כמו ב-``tests/test_advisor_service.py``: גישה לשדה שלא קיים נכשלת.
    return ChatCompletion.model_validate({
        "id": "c1", "object": "chat.completion", "created": 0, "model": "extract-model",
        "choices": [{"index": 0, "finish_reason": finish_reason,
                     "message": {"role": "assistant", "content": content}}],
    })


class _FakeLLM:
    """``openai.OpenAI`` של החילוץ, כ-``client_factory``: מקליט את הקריאה, ומחזיר תוכן, זורק חריגה, או ממתין
    (``gevent.sleep`` — נקודת החלפה, כמו קריאה מהרשת תחת gevent)."""

    def __init__(self):
        self.endpoints = []
        self.calls = []
        self.closed = 0
        self.content = json.dumps({"found": False})
        self.error = None
        self.sleep = 0.0

    def __call__(self, endpoint):
        self.endpoints.append(endpoint)
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.closed += 1
        return None

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.sleep:
            gevent.sleep(self.sleep)
        if self.error is not None:
            raise self.error
        return _completion(self.content)


#: ברירת המחדל של ``world.extract``: שני הסעיפים של ``webapp/search.html``, לפי הסדר. אובייקט ולא ``None``, כי
#: ``None`` הוא אחד הקלטים הפסולים שנבדקים.
_BOTH = object()


@pytest.fixture
def world(monkeypatch):
    db = FakeDB()
    world = make_world(monkeypatch, db)
    fill(world, pages=_pages())
    world.llm = _FakeLLM()
    world.extract_events = []
    monkeypatch.setattr(
        svc, "emit_event",
        lambda name, severity="info", **fields: world.extract_events.append((name, severity, fields)),
    )
    world.ids = {doc["anchor"]: doc["_id"] for doc in db[contract.SECTIONS_COLLECTION].find({})}

    def extract(query=QUERY, ids=_BOTH, *, environ=ENV, can_enforce_deadline=lambda: True):
        return svc.extract(
            db, query, [world.ids["search-basics"], world.ids["search-deadline"]] if ids is _BOTH else ids,
            environ=environ, client_factory=world.llm, can_enforce_deadline=can_enforce_deadline,
        )

    world.extract = extract
    return world


def _failed(world, **kwargs) -> DocsSearchError:
    with pytest.raises(DocsSearchError) as caught:
        world.extract(**kwargs)
    return caught.value


def _event(world):
    [(name, severity, fields)] = world.extract_events
    assert name == svc.EVENT
    assert isinstance(fields.pop("duration_ms"), int)
    return severity, fields


def _sections(world, *anchors):
    found = docs_search.read_sections(world.db, [world.ids[anchor] for anchor in anchors])
    return [docs_search.section_result(world.ids[anchor], found[world.ids[anchor]]) for anchor in anchors]


# ---------------------------------------------------------------------------
# נמצא / לא נמצא
# ---------------------------------------------------------------------------


def test_the_quote_comes_back_with_the_section_it_was_taken_from(world):
    world.llm.content = json.dumps({"found": True, "section": 2, "quote": DEADLINE_QUOTE})

    result = world.extract()

    assert (result["found"], result["quote"]) == (True, DEADLINE_QUOTE)
    section = result["section"]
    assert section["section_id"] == world.ids["search-deadline"]
    assert section["url"] == contract.SITE_URL + "webapp/search.html#search-deadline"
    assert (section["title"], section["breadcrumb"], section["source_path"]) == (
        "תקרות זמן", ["חיפוש", "תקרות זמן"], "docs/webapp/search.rst"
    )
    # הכרטיס כבר מציג את הסעיף כולו; התשובה נושאת את הקטע ואת מה שצריך כדי לקשר אליו.
    assert "markdown" not in section
    assert world.llm.endpoints == [LlmEndpoint("extract-key-123", "https://llm.example.test/v1/", "extract-model")]
    assert world.llm.closed == 1
    assert _event(world) == ("info", {"outcome": "found", "code": None, "model": "extract-model"})


def test_the_model_gets_the_question_and_the_sections_in_the_order_of_the_cards(world):
    world.extract(ids=[world.ids["search-deadline"], world.ids["search-basics"]])

    [call] = world.llm.calls
    assert set(call) == {"model", "messages"} and call["model"] == "extract-model"
    system, user = call["messages"]
    assert system == {"role": "system", "content": svc.SYSTEM_PROMPT}
    assert user["role"] == "user"
    text = user["content"]
    positions = [text.index(part) for part in (
        f"<question>\n{QUERY}\n</question>", '<section number="1">', "שביל: חיפוש ← תקרות זמן", DEADLINE_QUOTE,
        '<section number="2">', "שביל: חיפוש ← יסודות", "החיפוש מחזיר סעיפים לפי דמיון.",
    )]
    assert positions == sorted(positions), text


def test_the_instructions_say_that_not_found_is_a_wanted_answer():
    """"לא נמצא" לגיטימי ורצוי, וההנחיה אומרת את זה במפורש — אחרת המודל בוחר את הסעיף "הכי פחות גרוע"."""
    assert '{"found": false}' in svc.SYSTEM_PROMPT
    assert "לגיטימית ורצויה" in svc.SYSTEM_PROMPT and "הכי פחות גרוע" in svc.SYSTEM_PROMPT


def test_not_found_is_an_answer_and_not_a_failure(world):
    world.llm.content = '{"found": false}'

    assert world.extract() == {"found": False}
    assert _event(world) == ("info", {"outcome": "not_found", "code": None, "model": "extract-model"})


def test_a_quote_that_differs_a_little_from_the_section_is_shown_as_the_model_returned_it(world):
    """בלי השוואה לטקסט של הסעיף (החלטה מ-28.11.2026): הקישור לסעיף הוא המקום לקרוא מה כתוב בדיוק."""
    reworded = "התקרה היא שישים שניות לקריאה"
    world.llm.content = json.dumps({"found": True, "section": 2, "quote": reworded})

    assert world.extract()["quote"] == reworded


def test_an_answer_inside_a_code_fence_is_read(world):
    world.llm.content = "```json\n" + json.dumps({"found": True, "section": 1, "quote": " יסודות "}) + "\n```"

    result = world.extract()

    assert (result["quote"], result["section"]["section_id"]) == ("יסודות", world.ids["search-basics"])


def test_the_link_of_an_update_jumps_to_it_like_the_card(world):
    world.llm.content = json.dumps({"found": True, "section": 1, "quote": "מחלץ קטע מהסעיפים."})

    result = world.extract(ids=[world.ids["id3"]])

    assert result["section"]["url"] == (
        contract.SITE_URL + "whats-new/2026-11.html#id3" + contract.text_fragment(HEADLINE)
    )
    assert result["section"]["title"] == HEADLINE


# ---------------------------------------------------------------------------
# תשובה שלא בצורה שביקשנו
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content,reason",
    [
        (None, "empty"),
        ("", "empty"),
        ("   ", "empty"),
        ("נמצא בסעיף 2", "not_json"),
        ('{"found": tru', "not_json"),
        ('{"found": "yes"}', "found_is_not_boolean"),
        ('{"found": 1}', "found_is_not_boolean"),
        ("{}", "found_is_not_boolean"),
        ('{"found": true, "section": 0, "quote": "x"}', "no_such_section"),
        ('{"found": true, "section": 3, "quote": "x"}', "no_such_section"),
        ('{"found": true, "section": "2", "quote": "x"}', "no_such_section"),
        ('{"found": true, "section": true, "quote": "x"}', "no_such_section"),
        ('{"found": true, "section": 2.0, "quote": "x"}', "no_such_section"),
        ('{"found": true, "section": 2}', "no_quote"),
        ('{"found": true, "section": 2, "quote": "  "}', "no_quote"),
        ('{"found": true, "section": 2, "quote": 7}', "no_quote"),
    ],
)
def test_an_answer_that_is_not_in_the_asked_form_is_a_failure_with_its_reason(world, content, reason):
    world.llm.content = content

    error = _failed(world)

    assert (error.code, error.http_status, error.detail) == ("extract_bad_answer", 502, reason)
    assert _event(world) == ("warning", {"outcome": "failed", "code": "extract_bad_answer", "model": "extract-model"})


def test_a_quote_longer_than_everything_sent_is_not_a_quote(world):
    sent = svc.build_messages(QUERY, _sections(world, "search-basics", "search-deadline"))[1]["content"]
    limit = len(sent.encode("utf-8"))
    world.llm.content = json.dumps({"found": True, "section": 2, "quote": "x" * limit})
    assert world.extract()["quote"] == "x" * limit

    world.llm.content = json.dumps({"found": True, "section": 2, "quote": "x" * (limit + 1)})
    assert _failed(world).detail == "quote_longer_than_the_sections"


# ---------------------------------------------------------------------------
# תקרת הזמן והספק
# ---------------------------------------------------------------------------


def test_a_model_that_does_not_answer_in_time_is_cut_at_the_deadline(world, monkeypatch):
    monkeypatch.setattr(svc, "EXTRACT_DEADLINE_SECONDS", 0.05)
    world.llm.sleep = 5

    started = time.monotonic()
    error = _failed(world)

    assert (error.code, error.http_status) == ("extract_timeout", 504)
    assert time.monotonic() - started < 2
    assert world.llm.closed == 1


def test_a_deadline_set_by_the_caller_is_not_taken_for_the_extract_deadline(world):
    """``gevent.Timeout`` שמישהו מעלינו הציב עובר הלאה כמו שהוא — הוא לא שלנו להשתיק."""
    world.llm.sleep = 5

    with pytest.raises(gevent.Timeout) as caught:
        with gevent.Timeout(0.05) as outer:
            world.extract()

    assert caught.value is outer
    assert world.extract_events == []


def _request():
    return httpx2.Request("POST", "https://llm.example.test/v1/chat/completions")


def _response(status):
    return httpx2.Response(status, request=_request(), headers={"x-request-id": "req-77"})


@pytest.mark.parametrize(
    "error,code,status,detail",
    [
        (openai.RateLimitError(f"quota: {QUERY}", response=_response(429), body=None), "extract_quota", 429, ""),
        (openai.InternalServerError(f"boom: {QUERY}", response=_response(500), body=None),
         "extract_failed", 502, "status 500"),
        (openai.AuthenticationError("bad key", response=_response(401), body=None), "extract_failed", 502, "status 401"),
        (openai.APITimeoutError(request=_request()), "extract_timeout", 504, ""),
        (openai.APIConnectionError(request=_request()), "extract_failed", 502, "APIConnectionError"),
    ],
)
def test_a_provider_failure_has_its_own_code_and_the_log_carries_only_its_type_and_codes(
        world, caplog, error, code, status, detail):
    world.llm.error = error

    with caplog.at_level(logging.WARNING, logger=svc.__name__):
        failure = _failed(world)

    assert (failure.code, failure.http_status, failure.detail) == (code, status, detail)
    assert type(error).__name__ in caplog.text
    if isinstance(error, openai.APIStatusError):
        assert f"status={error.status_code}" in caplog.text and "request_id=req-77" in caplog.text
    assert QUERY not in caplog.text
    assert _event(world) == ("warning", {"outcome": "failed", "code": code, "model": "extract-model"})


def test_an_error_that_is_not_the_provider_s_is_not_reported_as_a_provider_failure(world):
    """באג (כאן ``KeyError``) עולה כמו שהוא, ולא מקבל את התווית "הקריאה למודל נכשלה" (R10)."""
    world.llm.error = KeyError("bug")

    with pytest.raises(KeyError):
        world.extract()
    assert world.extract_events == []


def test_the_client_has_one_attempt_and_a_network_ceiling_no_longer_than_the_deadline():
    client = svc._openai_client(LlmEndpoint("k", "https://llm.example.test/v1/", "m"))

    assert client.max_retries == 0
    assert client.timeout == svc.EXTRACT_DEADLINE_SECONDS


class _Recorder(BaseHTTPRequestHandler):
    """מקליט את הבקשה שה-SDK שלח, ועונה ב-chat completion תקין עם ``answer``."""

    seen: dict = {}
    answer = json.dumps({"found": False})

    def do_POST(self):  # noqa: N802 - השם ש-BaseHTTPRequestHandler מחפש
        length = int(self.headers.get("Content-Length") or 0)
        type(self).seen = {
            "path": self.path,
            "headers": {key.lower(): value for key, value in self.headers.items()},
            "body": json.loads(self.rfile.read(length) or b"{}"),
        }
        body = json.dumps(_completion(type(self).answer).model_dump()).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # משתיק את הלוג של http.server בפלט הטסטים
        pass


@pytest.fixture
def llm_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Recorder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1/"
    finally:
        server.shutdown()
        server.server_close()


def test_the_request_the_sdk_sends_carries_only_the_model_and_the_messages(world, llm_server, monkeypatch):
    """הלקוח האמיתי (``_openai_client``), מול שרת מקומי: הכתובת והמפתח מההגדרות של החילוץ ולא מ-``OPENAI_*``,
    ובגוף רק ``model`` ו-``messages`` — הפרמטרים שמופיעים בעמוד התאימות של Gemini."""
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key-should-not-be-used")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9/should-not-be-used/")
    _Recorder.answer = json.dumps({"found": True, "section": 2, "quote": DEADLINE_QUOTE})

    result = svc.extract(
        world.db, QUERY, [world.ids["search-basics"], world.ids["search-deadline"]],
        environ={**ENV, "DOCS_EXTRACT_BASE_URL": llm_server}, can_enforce_deadline=lambda: True,
    )

    seen = _Recorder.seen
    assert seen["path"] == "/v1/chat/completions"
    assert seen["headers"]["authorization"] == "Bearer extract-key-123"
    assert set(seen["body"]) == {"model", "messages"}
    assert seen["body"]["model"] == "extract-model"
    assert [message["role"] for message in seen["body"]["messages"]] == ["system", "user"]
    assert result["quote"] == DEADLINE_QUOTE


# ---------------------------------------------------------------------------
# ההגדרות והתהליך
# ---------------------------------------------------------------------------


def test_without_any_setting_there_is_no_extract_and_no_model_call(world):
    error = _failed(world, environ={})

    assert (error.code, error.http_status) == ("extract_not_configured", 503)
    assert world.llm.calls == []
    assert _event(world) == ("warning", {"outcome": "failed", "code": "extract_not_configured", "model": None})


@pytest.mark.parametrize(
    "override,missing",
    [
        ({"DOCS_EXTRACT_MODEL": ""}, "DOCS_EXTRACT_MODEL לא מוגדר"),
        ({"DOCS_EXTRACT_API_KEY": "extract key"}, "DOCS_EXTRACT_API_KEY חייב להיות ASCII בלי רווחים"),
        ({"DOCS_EXTRACT_BASE_URL": "llm.example.test/v1"},
         "DOCS_EXTRACT_BASE_URL חייב להיות כתובת מלאה שמתחילה ב-https://"),
    ],
)
def test_partial_settings_say_what_is_missing_without_the_values(world, override, missing):
    error = _failed(world, environ={**ENV, **override})

    assert (error.code, error.http_status, error.detail) == ("extract_misconfigured", 503, missing)
    assert "extract key" not in error.detail and "extract-key-123" not in error.detail
    assert world.llm.calls == []


def test_the_advisor_settings_do_not_turn_the_extract_on(world):
    advisor = {"ADVISOR_API_KEY": "advisor-key", "ADVISOR_BASE_URL": "https://llm.example.test/v1/",
               "ADVISOR_MODEL": "advisor-model"}

    assert _failed(world, environ=advisor).code == "extract_not_configured"
    assert svc.is_offered(advisor) is False


@pytest.mark.parametrize(
    "environ,offered",
    [({}, False), (ENV, True), ({"DOCS_EXTRACT_MODEL": "extract-model"}, True)],
    ids=["unset", "configured", "partial"],
)
def test_the_button_is_offered_unless_nothing_is_set(environ, offered):
    """הגדרות חלקיות — הכפתור מוצג, והלחיצה אומרת מה חסר (החלטה 6 בתוכנית)."""
    assert svc.is_offered(environ) is offered


def test_a_process_gevent_did_not_patch_refuses_instead_of_running_without_a_deadline(world):
    error = _failed(world, can_enforce_deadline=lambda: False)

    assert (error.code, error.http_status) == ("extract_needs_gevent", 503)
    assert world.llm.calls == []


def test_the_test_process_is_one_that_gevent_did_not_patch():
    """המצב של התהליך הזה, כפי שהבדיקה האמיתית רואה אותו. המקרה המתוקן — בתת-תהליך, ב-
    ``tests/test_docs_extract_deadline_under_gevent.py``."""
    assert svc.deadline_enforceable() is False


def test_the_settings_are_declared_in_the_config_inspector_for_the_webapp():
    from services.config_inspector_service import ConfigService

    names = {f"{svc.ENV_PREFIX}{suffix}" for suffix in ("API_KEY", "BASE_URL", "MODEL")}
    for name in names:
        assert ConfigService.CONFIG_DEFINITIONS[name].services == ("webapp",), name
    assert ConfigService.CONFIG_DEFINITIONS["DOCS_EXTRACT_API_KEY"].sensitive is True


# ---------------------------------------------------------------------------
# הקלט והסעיפים
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ids",
    [None, "a" * 64, {}, [], ["a" * 64, "a" * 64], ["A" * 64], ["a" * 63], [7], [["a" * 64]],
     [f"{n:064x}" for n in range(docs_search.MAX_LIMIT + 1)]],
    ids=["none", "string", "dict", "empty", "duplicate", "uppercase", "short", "number", "nested", "too-many"],
)
def test_section_ids_that_are_not_a_list_of_section_ids_are_refused_before_any_work(world, ids):
    error = _failed(world, ids=ids)

    assert (error.code, error.http_status) == ("invalid_section_ids", 400)
    assert world.llm.calls == []


def test_the_question_is_checked_like_the_search_checks_it(world):
    assert _failed(world, query="   ").code == "empty_query"
    assert _failed(world, query=7).code == "invalid_query"
    assert world.llm.calls == []


def test_a_section_deleted_since_the_search_is_left_out_and_the_numbers_follow_what_is_sent(world):
    world.db[contract.SECTIONS_COLLECTION].delete_many({"_id": {"$in": [world.ids["search-basics"]]}})
    world.llm.content = json.dumps({"found": True, "section": 1, "quote": "התקרה"})

    result = world.extract()

    assert result["section"]["section_id"] == world.ids["search-deadline"]
    text = world.llm.calls[0]["messages"][1]["content"]
    assert text.count("<section ") == 1 and DEADLINE_QUOTE in text


def test_when_every_section_is_gone_the_extract_says_so(world):
    world.db[contract.SECTIONS_COLLECTION].delete_many({"_id": {"$in": list(world.ids.values())}})

    error = _failed(world)

    assert (error.code, error.http_status) == ("sections_gone", 409)
    assert world.llm.calls == []


def test_sections_over_the_cap_are_refused_and_the_cap_counts_bytes(world, monkeypatch):
    """מעל התקרה — סירוב עם קוד משלו, בלי חיתוך ובלי קריאה למודל. התקרה נמדדת בבתים: בעברית אות היא שני
    בתים, ותקרה שווה למספר התווים כבר עוברת אותה (H6)."""
    markdown = "".join(section["markdown"] for section in _sections(world, "search-basics", "search-deadline"))
    size, chars = len(markdown.encode("utf-8")), len(markdown)
    assert chars < size

    monkeypatch.setattr(svc, "MAX_SECTIONS_BYTES", size - 1)
    error = _failed(world)
    assert (error.code, error.http_status) == ("sections_too_large", 422)
    monkeypatch.setattr(svc, "MAX_SECTIONS_BYTES", chars)
    assert _failed(world).code == "sections_too_large"
    assert world.llm.calls == []

    monkeypatch.setattr(svc, "MAX_SECTIONS_BYTES", size)
    world.extract()
    assert len(world.llm.calls) == 1


class _FailingSections(FakeCollection):
    def __init__(self, error):
        super().__init__()
        self.error = error

    def find(self, *args, **kwargs):
        raise self.error


@pytest.mark.parametrize(
    "error,code,status",
    [
        (ExecutionTimeout("operation exceeded time limit", code=50), "database_timeout", 504),
        (ServerSelectionTimeoutError("no primary available"), "database_unavailable", 503),
    ],
)
def test_a_database_that_is_slow_or_unreachable_has_its_own_code(world, error, code, status):
    world.db.c[contract.SECTIONS_COLLECTION] = _FailingSections(error)

    failure = _failed(world)

    assert (failure.code, failure.http_status) == (code, status)
    assert world.llm.calls == []


def test_a_database_error_that_is_a_bug_is_not_reported_as_unavailable(world):
    world.db.c[contract.SECTIONS_COLLECTION] = _FailingSections(OperationFailure("bad query", code=2))

    with pytest.raises(OperationFailure):
        world.extract()


# ---------------------------------------------------------------------------
# מה לא נרשם
# ---------------------------------------------------------------------------


def test_the_question_and_the_answer_are_not_in_the_log_or_in_the_event(world, caplog):
    question, answer = "שאלה-פרטית-123", "ציטוט-פרטי-456"
    with caplog.at_level(logging.DEBUG):
        world.llm.content = json.dumps({"found": True, "section": 2, "quote": answer})
        world.extract(query=question)
        world.llm.content = f"לא JSON, ובו {answer}"
        _failed(world, query=question)
        world.llm.error = openai.InternalServerError(f"{question} {answer}", response=_response(500), body=None)
        _failed(world, query=question)

    assert question not in caplog.text and answer not in caplog.text
    assert len(world.extract_events) == 3
    assert question not in repr(world.extract_events) and answer not in repr(world.extract_events)


# ---------------------------------------------------------------------------
# הראוט
# ---------------------------------------------------------------------------


@pytest.fixture
def app(monkeypatch, world):
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(svc, "_openai_client", world.llm)
    monkeypatch.setattr(svc, "deadline_enforceable", lambda: True)
    return admin_app_for(monkeypatch, world.db, world)


def _body(world, **overrides):
    return {"query": QUERY, "section_ids": [world.ids["search-basics"], world.ids["search-deadline"]], **overrides}


def test_the_route_returns_the_extract_as_json(app):
    app.world.llm.content = json.dumps({"found": True, "section": 2, "quote": DEADLINE_QUOTE})
    app.login(1)

    response = app.client.post("/api/search/docs/extract", json=_body(app.world))

    assert response.status_code == 200
    body = response.get_json()
    assert (body["ok"], body["found"], body["quote"]) == (True, True, DEADLINE_QUOTE)
    assert body["section"]["url"] == contract.SITE_URL + "webapp/search.html#search-deadline"
    assert [name for name, _severity, _fields in app.world.extract_events] == [svc.EVENT]


def test_the_route_answers_not_found(app):
    app.login(1)

    response = app.client.post("/api/search/docs/extract", json=_body(app.world))

    assert (response.status_code, response.get_json()) == (200, {"ok": True, "found": False})


@pytest.mark.parametrize(
    "request_kwargs,status,error",
    [
        ({"data": "query=x", "content_type": "application/x-www-form-urlencoded"}, 415, "json_required"),
        ({"data": "[1]", "content_type": "application/json"}, 400, "invalid_json"),
        ({"json": {"query": QUERY, "section_ids": "x"}}, 400, "invalid_section_ids"),
        ({"json": {}}, 400, "invalid_query"),
    ],
)
def test_the_route_refuses_bad_input_with_json(app, request_kwargs, status, error):
    app.login(1)

    response = app.client.post("/api/search/docs/extract", **request_kwargs)

    assert (response.status_code, response.get_json()["error"]) == (status, error)
    assert app.world.llm.calls == []


def test_the_route_says_when_the_extract_is_not_configured(app, monkeypatch):
    for name in ENV:
        monkeypatch.delenv(name)
    app.login(1)

    response = app.client.post("/api/search/docs/extract", json=_body(app.world))

    assert (response.status_code, response.get_json()["error"]) == (503, "extract_not_configured")


def test_the_route_answers_503_without_a_database(app, monkeypatch):
    monkeypatch.setattr(app.wa, "get_db", lambda: None)
    app.login(1)

    response = app.client.post("/api/search/docs/extract", json=_body(app.world))

    assert (response.status_code, response.get_json()["error"]) == (503, "database_unavailable")
