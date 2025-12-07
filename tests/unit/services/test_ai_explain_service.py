import json

import httpx
import pytest

from services import ai_explain_service as svc


@pytest.mark.asyncio
async def test_generate_ai_explanation_normalizes_and_respects_sanitization(monkeypatch):
    monkeypatch.setattr(svc, "_ANTHROPIC_API_KEY", "test-key")

    captured_prompt: dict = {}

    async def fake_call(prompt: str, *, timeout: float):
        captured_prompt["text"] = prompt
        payload = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "root_cause": "DB locks detected",
                            "actions": ["restart service", "scale db"],
                            "signals": ["latency spike"],
                        }
                    ),
                }
            ]
        }
        return payload, "claude-test"

    monkeypatch.setattr(svc, "_call_anthropic", fake_call)

    context = {
        "alert_uid": "uid-1",
        "alert_name": "High Latency",
        "severity": "critical",
        "endpoint": "/checkout",
        "metadata": {"password": "secret-value"},
        "log_excerpt": "token=sk-1234567890",
    }

    result = await svc.generate_ai_explanation(context, expected_sections=["root_cause", "actions"])

    assert result["root_cause"] == "DB locks detected"
    assert result["actions"] == ["restart service", "scale db"]
    assert result["signals"] == ["latency spike"]
    assert result["alert_uid"] == "uid-1"
    assert result["provider"]
    assert result["model"]
    prompt_text = captured_prompt["text"]
    assert "secret-value" not in prompt_text
    assert "<redacted>" in prompt_text
    assert "sk-1234567890" not in prompt_text


@pytest.mark.asyncio
async def test_generate_ai_explanation_fallback_when_provider_returns_empty(monkeypatch):
    monkeypatch.setattr(svc, "_ANTHROPIC_API_KEY", "test-key")

    async def fake_call(prompt: str, *, timeout: float):  # noqa: ARG001
        return {"content": [{"type": "text", "text": "{}"}]}, "claude-default"

    monkeypatch.setattr(svc, "_call_anthropic", fake_call)

    context = {
        "alert_uid": "uid-2",
        "alert_name": "Errors",
        "severity": "warning",
        "summary": "Errors > 5%",
    }

    result = await svc.generate_ai_explanation(context)

    assert "Errors" in result["root_cause"]
    assert result["actions"]
    assert result["signals"]


@pytest.mark.asyncio
async def test_generate_ai_explanation_handles_dict_sections(monkeypatch):
    monkeypatch.setattr(svc, "_ANTHROPIC_API_KEY", "test-key")

    async def fake_call(prompt: str, *, timeout: float):  # noqa: ARG001
        payload = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "root_cause": "dict input",
                            "actions": {"step1": "do X", "step2": "do Y"},
                            "signals": {"hint1": "signal A"},
                        }
                    ),
                }
            ]
        }
        return payload, "claude-dict"

    monkeypatch.setattr(svc, "_call_anthropic", fake_call)

    context = {
        "alert_uid": "uid-3",
        "alert_name": "Dict Alert",
        "severity": "info",
    }

    result = await svc.generate_ai_explanation(context)

    assert result["root_cause"] == "dict input"
    assert result["actions"] == ["do X", "do Y"]
    assert result["signals"] == ["signal A"]


@pytest.mark.asyncio
async def test_generate_ai_explanation_requires_context_dict(monkeypatch):
    monkeypatch.setattr(svc, "_ANTHROPIC_API_KEY", "test-key")

    async def fake_call(prompt: str, *, timeout: float):  # noqa: ARG001
        return {"content": [{"type": "text", "text": "{}"}]}, "claude-error"

    monkeypatch.setattr(svc, "_call_anthropic", fake_call)

    with pytest.raises(svc.AiExplainError):
        await svc.generate_ai_explanation("not-a-dict")  # type: ignore[arg-type]


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict, text: str):
        self.status_code = status_code
        self._payload = payload
        self._text = text

    @property
    def text(self) -> str:
        return self._text

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
            raise httpx.HTTPStatusError("error", request=request, response=self)


@pytest.mark.asyncio
async def test_call_anthropic_falls_back_on_404(monkeypatch):
    monkeypatch.setattr(svc, "_ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(svc, "_MODEL_CANDIDATES", ("primary-model", "fallback-model"))

    responses = [
        _FakeResponse(404, {}, '{"error":"model_not_found"}'),
        _FakeResponse(200, {"content": [{"type": "text", "text": "{}"}]}, "{}"),
    ]

    def fake_async_client_factory(*args, **kwargs):  # noqa: ARG001
        class _Client:
            def __init__(self):
                self._iter = iter(responses)

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, *args, **kwargs):  # noqa: ARG001
                try:
                    return next(self._iter)
                except StopIteration:  # pragma: no cover - defensive
                    raise AssertionError("no more responses")

        return _Client()

    monkeypatch.setattr(svc.httpx, "AsyncClient", fake_async_client_factory)

    payload, model_used = await svc._call_anthropic("{}", timeout=5.0)

    assert model_used == "fallback-model"
    assert payload["content"][0]["text"] == "{}"
