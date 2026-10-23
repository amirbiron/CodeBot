"""שירות היועץ מול מודל השפה (``services/advisor_service.py``).

הפענוח, הפרומפט ומבנה הבקשה עברו מהבוט הנפרד ``codekeeper_advisor_bot`` עם
הטסטים שלהם. החדשים: ההגדרות מ-``ADVISOR_*`` ובדיקתן, תקרת הזמן הכוללת, ובקשה
אמיתית של ה-SDK מול שרת מקומי — מה שבאמת יוצא על החוט, כולל ההוכחה שמשתני
``OPENAI_*`` בסביבה אינם משנים לאן היועץ פונה.
"""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import httpx2
import openai
import pytest
from openai.types.chat import ChatCompletion

from services import advisor_service as svc

# ─── פענוח ───────────────────────────────────────────────────────────────────


def test_extract_and_strip_follow_ups():
    text = "תשובה.\n\n[שאלות_המשך: יש גיבוי? | עובד בנייד? | כמה זה עולה?]"
    assert svc.extract_follow_up_questions(text) == ["יש גיבוי?", "עובד בנייד?", "כמה זה עולה?"]
    assert svc.strip_follow_up_questions(text) == "תשובה."


def test_follow_ups_without_brackets_are_parsed_too():
    text = "תשובה.\nשאלות המשך: א | ב"
    assert svc.extract_follow_up_questions(text) == ["א", "ב"]
    assert svc.strip_follow_up_questions(text) == "תשובה."


def test_contact_marker_detected_only_at_start_but_removed_everywhere():
    assert svc.split_contact_marker("[CONTACT]\nאין לי מידע") == (True, "אין לי מידע")
    assert svc.split_contact_marker("טקסט [CONTACT] באמצע") == (False, "טקסט  באמצע")


def test_trim_to_last_sentence():
    assert svc.trim_to_last_sentence("שורה שלמה.\nשורה שנקט") == "שורה שלמה.\n…"
    assert svc.trim_to_last_sentence("משפט ראשון. משפט שני שנק") == "משפט ראשון. …"


# ─── פרומפט ──────────────────────────────────────────────────────────────────


def test_system_prompt_is_static_and_keeps_knowledge_verbatim():
    knowledge = "מסמך עם {סוגריים} ו-%s"
    first = svc.build_system_prompt(knowledge)
    assert first == svc.build_system_prompt(knowledge)  # תנאי להתאמה במטמון של הספק
    assert knowledge in first
    assert "שאלות_המשך" in first
    assert first.rstrip().endswith("── סוף מסמך הידע ──")


def test_build_messages_order():
    history = [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"}]
    msgs = svc.build_messages("PROMPT", history, "q2")
    assert [m["role"] for m in msgs] == ["developer", "user", "assistant", "user"]
    assert msgs[0]["content"] == "PROMPT" and msgs[-1]["content"] == "q2"


# ─── הגדרות ──────────────────────────────────────────────────────────────────

_VALID_ENV = {
    "ADVISOR_API_KEY": "test-key-123",
    "ADVISOR_BASE_URL": "https://llm.example.test/v1/",
    "ADVISOR_MODEL": "test-model",
}


def test_settings_absent_means_disabled_without_errors():
    assert svc.load_settings({}) == (None, [])


def test_settings_valid():
    settings, errors = svc.load_settings({**_VALID_ENV, "ADVISOR_CONTACT_URL": "tg://resolve?domain=someone"})
    assert errors == []
    assert settings == svc.AdvisorSettings(
        api_key="test-key-123",
        base_url="https://llm.example.test/v1/",
        model="test-model",
        contact_url="tg://resolve?domain=someone",
    )


@pytest.mark.parametrize(
    "override, expected_error",
    [
        ({"ADVISOR_MODEL": ""}, "ADVISOR_MODEL לא מוגדר"),
        ({"ADVISOR_API_KEY": ""}, "ADVISOR_API_KEY לא מוגדר"),
        # BASE_URL הוא חובה: בלעדיו ה-SDK היה קורא את OPENAI_BASE_URL מהסביבה
        ({"ADVISOR_BASE_URL": ""}, "ADVISOR_BASE_URL חייב להיות כתובת מלאה שמתחילה ב-https://"),
        ({"ADVISOR_BASE_URL": "llm.example.test/v1"}, "ADVISOR_BASE_URL חייב להיות כתובת מלאה שמתחילה ב-https://"),
        # תו נסתר שנכנס בהעתקה — כותרת HTTP היא ASCII
        ({"ADVISOR_API_KEY": "test-key\u200f"}, "ADVISOR_API_KEY חייב להיות ASCII בלי רווחים"),
        ({"ADVISOR_API_KEY": "test key"}, "ADVISOR_API_KEY חייב להיות ASCII בלי רווחים"),
        ({"ADVISOR_CONTACT_URL": "t.me/someone"}, "ADVISOR_CONTACT_URL חייב להתחיל ב-https:// או ב-tg://"),
    ],
)
def test_settings_errors_disable_the_advisor(override, expected_error):
    settings, errors = svc.load_settings({**_VALID_ENV, **override})
    assert settings is None
    assert errors == [expected_error]


def test_context_exchanges_default_and_override():
    settings, _ = svc.load_settings(_VALID_ENV)
    assert settings.context_exchanges == svc.DEFAULT_CONTEXT_EXCHANGES
    # ערך ריק ברנדר הוא "לא הוגדר", לא שגיאה
    settings, _ = svc.load_settings({**_VALID_ENV, "ADVISOR_CONTEXT_EXCHANGES": " "})
    assert settings.context_exchanges == svc.DEFAULT_CONTEXT_EXCHANGES
    for value in ("1", str(svc.MAX_CONTEXT_EXCHANGES), " 8 "):
        settings, errors = svc.load_settings({**_VALID_ENV, "ADVISOR_CONTEXT_EXCHANGES": value})
        assert errors == [] and settings.context_exchanges == int(value)


@pytest.mark.parametrize(
    "value",
    [
        "0",
        str(svc.MAX_CONTEXT_EXCHANGES + 1),
        "-3",
        "5.0",
        "abc",
        "1000",
        # ספרות שאינן ASCII: ``"²".isdigit()`` נכון ו-``int()`` דוחה אותה, ו-``int("٣")`` מחזיר 3
        "²",
        "٣",
    ],
)
def test_invalid_context_exchanges_disable_the_advisor(value):
    settings, errors = svc.load_settings({**_VALID_ENV, "ADVISOR_CONTEXT_EXCHANGES": value})
    assert settings is None
    assert errors == [f"ADVISOR_CONTEXT_EXCHANGES חייב להיות מספר שלם בין 1 ל-{svc.MAX_CONTEXT_EXCHANGES}"]


def test_config_inspector_shows_the_real_context_exchanges_default():
    """ה-``default`` ב-Config Inspector הוא עותק של ``DEFAULT_CONTEXT_EXCHANGES``, ועותק שונה מציג "Modified" שקרי."""
    from services.config_inspector_service import ConfigService

    definition = ConfigService.CONFIG_DEFINITIONS["ADVISOR_CONTEXT_EXCHANGES"]
    assert definition.default == str(svc.DEFAULT_CONTEXT_EXCHANGES)


# ─── generate_answer מול כפיל של הלקוח ──────────────────────────────────────


def _completion(content, finish_reason="stop", cached=0):
    # אובייקט אמיתי של ה-SDK, לא namespace — כך שגישה לשדה לא קיים נכשלת
    return ChatCompletion.model_validate({
        "id": "c1", "object": "chat.completion", "created": 0, "model": "test-model",
        "choices": [{"index": 0, "finish_reason": finish_reason,
                     "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 2000, "completion_tokens": 20, "total_tokens": 2020,
                  "prompt_tokens_details": {"cached_tokens": cached}},
    })


class StubClient:
    def __init__(self, response=None, error=None, delay=0.0):
        self.calls: list[dict] = []
        self._response, self._error, self._delay = response, error, delay
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error:
            raise self._error
        return self._response


@pytest.fixture
def use_client(monkeypatch):
    def _install(client):
        settings = svc.AdvisorSettings(
            api_key="k", base_url="https://llm.example.test/v1/", model="test-model", contact_url=""
        )
        monkeypatch.setattr(svc, "_runtime", svc._Runtime(settings=settings, system_prompt="PROMPT", client=client))
        return client

    return _install


async def test_request_uses_max_completion_tokens_and_no_optional_params(use_client):
    client = use_client(StubClient(_completion("תשובה.")))
    await svc.generate_answer([], "שאלה")
    kwargs = client.calls[0]
    assert kwargs["model"] == "test-model"
    assert "max_completion_tokens" in kwargs and "max_tokens" not in kwargs
    assert "temperature" not in kwargs and "reasoning_effort" not in kwargs


async def test_answer_with_follow_ups(use_client):
    use_client(StubClient(_completion("כן, זה מתאים.\n[שאלות_המשך: א | ב]")))
    answer = await svc.generate_answer([], "שאלה")
    assert answer == svc.Answer(text="כן, זה מתאים.", ok=True, follow_up_questions=["א", "ב"])


async def test_contact_answer_has_no_follow_ups(use_client):
    use_client(StubClient(_completion("[CONTACT]\nאין לי מידע על זה.\n[שאלות_המשך: א]")))
    answer = await svc.generate_answer([], "שאלה")
    assert answer.needs_contact and answer.ok
    assert answer.text == "אין לי מידע על זה." and answer.follow_up_questions == []


async def test_bare_contact_marker_gets_default_text(use_client):
    use_client(StubClient(_completion("[CONTACT]")))
    answer = await svc.generate_answer([], "שאלה")
    assert answer.needs_contact and answer.text == svc.CONTACT_DEFAULT_TEXT


async def test_api_error_returns_fallback_and_logs_codes_not_body(use_client, caplog):
    caplog.set_level("ERROR")
    request = httpx2.Request("POST", "https://llm.example.test/v1/chat/completions")
    response = httpx2.Response(400, request=request, headers={"x-request-id": "req-7"})
    body = {"code": "invalid_value", "message": "the user wrote: הטלפון שלי 0501234567"}
    use_client(StubClient(error=openai.BadRequestError("bad", response=response, body=body)))
    assert await svc.generate_answer([], "שאלה") == svc.Answer(text=svc.FALLBACK_ERROR, ok=False)
    assert "BadRequestError status=400 code=invalid_value request_id=req-7" in caplog.text
    assert "0501234567" not in caplog.text


async def test_timeout_error_returns_fallback(use_client):
    error = openai.APITimeoutError(request=httpx2.Request("POST", "https://llm.example.test/v1/chat/completions"))
    use_client(StubClient(error=error))
    assert await svc.generate_answer([], "שאלה") == svc.Answer(text=svc.FALLBACK_ERROR, ok=False)


async def test_deadline_covers_the_whole_call(use_client, monkeypatch):
    """תקרת הזמן חלה על הקריאה כולה — גם כשה-SDK עצמו לא נקטע."""
    monkeypatch.setattr(svc, "ANSWER_DEADLINE_SECONDS", 0.05)
    use_client(StubClient(_completion("מאוחר מדי."), delay=5))
    loop = asyncio.get_running_loop()
    started = loop.time()
    assert await svc.generate_answer([], "שאלה") == svc.Answer(text=svc.FALLBACK_ERROR, ok=False)
    assert loop.time() - started < 2


async def test_empty_content_returns_fallback(use_client):
    use_client(StubClient(_completion(None)))
    assert (await svc.generate_answer([], "שאלה")).ok is False


async def test_length_finish_reason_trims(use_client):
    use_client(StubClient(_completion("שורה שלמה.\nשורה שנקט", finish_reason="length")))
    assert (await svc.generate_answer([], "שאלה")).text == "שורה שלמה.\n…"


async def test_diag_log_has_numbers_but_no_content(use_client, caplog):
    caplog.set_level("INFO")
    use_client(StubClient(_completion("התשובה הסודית של הגולש.", cached=1920)))
    await svc.generate_answer([], "שאלה")
    assert "cached_tokens=1920" in caplog.text
    assert "הסודית" not in caplog.text


async def test_generate_answer_before_init_is_a_bug(monkeypatch):
    monkeypatch.setattr(svc, "_runtime", None)
    with pytest.raises(RuntimeError):
        await svc.generate_answer([], "שאלה")


def test_init_rejects_empty_knowledge(tmp_path, monkeypatch):
    empty = tmp_path / "k.md"
    empty.write_text("  \n", encoding="utf-8")
    monkeypatch.setattr(svc, "KNOWLEDGE_FILE", empty)
    monkeypatch.setattr(svc, "_runtime", None)
    settings, _ = svc.load_settings(_VALID_ENV)
    with pytest.raises(RuntimeError):
        svc.init_advisor(settings)
    assert svc.current_settings() is None


# ─── הבקשה האמיתית של ה-SDK, מול שרת מקומי ──────────────────────────────────


class _Recorder(BaseHTTPRequestHandler):
    """מקליט את הבקשה שנחתה, ומחזיר תשובת chat completion תקינה."""

    seen: dict = {}

    def do_POST(self):  # noqa: N802 - השם ש-BaseHTTPRequestHandler מחפש
        length = int(self.headers.get("Content-Length") or 0)
        type(self).seen = {
            "path": self.path,
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "body": json.loads(self.rfile.read(length) or b"{}"),
        }
        body = json.dumps(_completion("תשובה מהשרת.").model_dump()).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # משתיק את הלוג של http.server בפלט הטסטים
        pass


@pytest.fixture
def llm_server():
    server = HTTPServer(("127.0.0.1", 0), _Recorder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/llm/v1/"
    finally:
        server.shutdown()
        server.server_close()


async def test_real_sdk_request_goes_to_advisor_url_with_advisor_key(llm_server, monkeypatch):
    """הבקשה שנחתה בצד השני: הכתובת והמפתח של ``ADVISOR_*``, גם כש-``OPENAI_*`` מוגדרים אחרת."""
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9/never/")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key-should-not-be-used")
    monkeypatch.setattr(svc, "_runtime", None)
    settings, errors = svc.load_settings(
        {"ADVISOR_API_KEY": "advisor-key-123", "ADVISOR_BASE_URL": llm_server, "ADVISOR_MODEL": "test-model"}
    )
    assert errors == []
    svc.init_advisor(settings)

    history = [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"}]
    answer = await svc.generate_answer(history, "q2")

    assert answer == svc.Answer(text="תשובה מהשרת.", ok=True)
    seen = _Recorder.seen
    assert seen["path"] == "/llm/v1/chat/completions"
    assert seen["headers"]["authorization"] == "Bearer advisor-key-123"
    body = seen["body"]
    assert body["model"] == "test-model"
    assert body["max_completion_tokens"] == svc.LLM_MAX_COMPLETION_TOKENS
    assert "max_tokens" not in body and "temperature" not in body
    assert [m["role"] for m in body["messages"]] == ["developer", "user", "assistant", "user"]
    assert body["messages"][-1]["content"] == "q2"
    await svc._runtime.client.close()
    monkeypatch.setattr(svc, "_runtime", None)
