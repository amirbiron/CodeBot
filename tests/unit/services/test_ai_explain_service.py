import json
import pytest

from services import ai_explain_service as svc


@pytest.mark.asyncio
async def test_generate_ai_explanation_normalizes_and_respects_sanitization(monkeypatch):
    monkeypatch.setattr(svc, "_ANTHROPIC_API_KEY", "test-key")

    captured_prompt: dict = {}

    async def fake_call(prompt: str, *, timeout: float) -> dict:
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
        return payload

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

    async def fake_call(prompt: str, *, timeout: float) -> dict:  # noqa: ARG001
        return {"content": [{"type": "text", "text": "{}"}]}

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
async def test_generate_ai_explanation_requires_context_dict(monkeypatch):
    monkeypatch.setattr(svc, "_ANTHROPIC_API_KEY", "test-key")

    async def fake_call(prompt: str, *, timeout: float) -> dict:  # noqa: ARG001
        return {"content": [{"type": "text", "text": "{}"}]}

    monkeypatch.setattr(svc, "_call_anthropic", fake_call)

    with pytest.raises(svc.AiExplainError):
        await svc.generate_ai_explanation("not-a-dict")  # type: ignore[arg-type]
