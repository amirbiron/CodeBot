from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

import httpx

logger = logging.getLogger(__name__)

_ANTHROPIC_API_URL = os.getenv("ANTHROPIC_API_URL", "https://api.anthropic.com/v1/messages")
_ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY") or ""
_PROVIDER_MODEL = (
    os.getenv("OBS_AI_EXPLAIN_MODEL")
    or os.getenv("CLAUDE_MODEL")
    or "claude-3-5-sonnet-20241022"
)
_PROVIDER_LABEL = os.getenv("OBS_AI_PROVIDER_LABEL") or "claude-sonnet-4.5"

try:
    _MAX_OUTPUT_TOKENS = max(200, min(2000, int(os.getenv("OBS_AI_EXPLAIN_MAX_TOKENS", "800"))))
except ValueError:
    _MAX_OUTPUT_TOKENS = 800

try:
    _TEMPERATURE = max(0.0, min(1.0, float(os.getenv("OBS_AI_EXPLAIN_TEMPERATURE", "0.2"))))
except ValueError:
    _TEMPERATURE = 0.2

try:
    _REQUEST_TIMEOUT = max(5.0, min(20.0, float(os.getenv("OBS_AI_EXPLAIN_TIMEOUT", "10"))))
except ValueError:
    _REQUEST_TIMEOUT = 10.0

_DEFAULT_SECTIONS: Sequence[str] = ("root_cause", "actions", "signals")
_SECRET_KEY_VALUE_RE = re.compile(
    r"(?i)(password|secret|token|api[_-]?key|session|authorization)\s*[:=]\s*([^\s,;]+)"
)
_SECRET_VALUE_RE = re.compile(r"(?i)(sk-[a-z0-9]{20,}|ya29\.[\w-]+|AIza[0-9A-Za-z-_]{35})")
_HEX_FINGERPRINT_RE = re.compile(r"\b[0-9a-f]{16,}\b", re.IGNORECASE)
_LONG_DIGIT_RE = re.compile(r"\b\d{12,}\b")
_SENSITIVE_KEYS = {
    "password",
    "secret",
    "token",
    "api_key",
    "api-key",
    "apikey",
    "authorization",
    "auth_token",
}

_MAX_STRING = 800
_MAX_LOG_CHARS = 4000
_MAX_METADATA_ITEMS = 40
_MAX_CHILD_ITEMS = 8

_SYSTEM_PROMPT = (
    "אתה מסייע לצוות ה-SRE של CodeBot לנתח התראות Observability. "
    "ענה בעברית פשוטה ושמור על טון עובדתי. "
    "אסור להוסיף טקסט חופשי מחוץ ל-JSON חוקי. "
    "אם חסר מידע, ציין זאת במפורש בתוך התשובה."
)


class AiExplainError(RuntimeError):
    """Logical/transport errors while generating AI explanations."""


def _truncate(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    safe = max(10, limit - 3)
    return f"{text[:safe]}..."


def _mask_sensitive(text: str) -> str:
    if not text:
        return ""

    def _kv_replacer(match: re.Match[str]) -> str:
        key = match.group(1)
        return f"{key}=<redacted>"

    sanitized = _SECRET_KEY_VALUE_RE.sub(_kv_replacer, text)
    sanitized = _SECRET_VALUE_RE.sub("<secret>", sanitized)
    sanitized = _HEX_FINGERPRINT_RE.sub("<hash>", sanitized)
    sanitized = _LONG_DIGIT_RE.sub("<id>", sanitized)
    return sanitized


def _sanitize_value(value: Any, depth: int = 0, max_items: int = _MAX_CHILD_ITEMS) -> Any:
    if depth > 3:
        return "..."
    if isinstance(value, dict):
        sanitized: Dict[str, Any] = {}
        for idx, (key, child) in enumerate(value.items()):
            if idx >= max_items:
                break
            key_str = str(key)
            if key_str.lower() in _SENSITIVE_KEYS:
                sanitized[key_str] = "<redacted>"
                continue
            sanitized[key_str] = _sanitize_value(child, depth + 1)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_value(item, depth + 1) for item in value[:max_items]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    text = str(value).strip()
    return _truncate(_mask_sensitive(text), _MAX_STRING if depth == 0 else 400)


def _sanitize_context(context: Dict[str, Any]) -> Dict[str, Any]:
    sanitized: Dict[str, Any] = {}
    for key, value in context.items():
        if key == "metadata" and isinstance(value, dict):
            snip: Dict[str, Any] = {}
            for idx, (meta_key, meta_val) in enumerate(value.items()):
                if idx >= _MAX_METADATA_ITEMS:
                    break
                meta_key_str = str(meta_key)
                if meta_key_str.lower() in _SENSITIVE_KEYS:
                    snip[meta_key_str] = "<redacted>"
                    continue
                snip[meta_key_str] = _sanitize_value(meta_val, depth=1)
            sanitized[key] = snip
            continue
        if key == "log_excerpt" and isinstance(value, str):
            sanitized[key] = _truncate(_mask_sensitive(value), _MAX_LOG_CHARS)
            continue
        if key in {"auto_actions", "quick_fixes"} and isinstance(value, list):
            sanitized[key] = _sanitize_value(value, depth=0, max_items=4)
            continue
        sanitized[key] = _sanitize_value(value, depth=0)

    # Normalize important attributes
    alert_name = sanitized.get("alert_name") or sanitized.get("alert_type") or context.get("alert_type")
    if not alert_name:
        alert_name = "Alert"
    sanitized["alert_name"] = str(alert_name)
    sanitized["severity"] = str(sanitized.get("severity") or context.get("severity") or "info").lower()
    if "alert_uid" in sanitized and sanitized["alert_uid"]:
        sanitized["alert_uid"] = str(sanitized["alert_uid"])[:64]
    return sanitized


def _fallback_root_cause(context: Dict[str, Any]) -> str:
    severity = str(context.get("severity") or "info").upper()
    name = context.get("alert_name") or "Alert"
    summary = context.get("summary") or ""
    endpoint = context.get("endpoint") or (context.get("metadata") or {}).get("endpoint")
    parts = [f"התראה [{severity}] בשם {name}"]
    if endpoint:
        parts.append(f"במסלול {endpoint}")
    if summary:
        parts.append(f"— {summary}")
    return " ".join(parts).strip()


def _fallback_actions(context: Dict[str, Any]) -> List[str]:
    actions: List[str] = []
    endpoint = context.get("endpoint")
    if endpoint:
        actions.append(f"נתח גרפים ולוגים עבור {endpoint} סביב זמן ההתראה.")
    if context.get("auto_actions"):
        actions.append("בחן את תוצאות פעולות ה-ChatOps שכבר הופעלו.")
    if context.get("quick_fixes"):
        actions.append("שקול הפעלה חוזרת של Quick Fix רק לאחר אימות ידני.")
    actions.append("עדכן את צוות ה-SRE והוסף ממצאים ל-Incident Story.")
    return actions[:4]


def _fallback_signals(context: Dict[str, Any]) -> List[str]:
    signals: List[str] = []
    severity = context.get("severity")
    if severity:
        signals.append(f"חומרה: {severity}")
    for key in ("endpoint", "region", "service", "deployment_id"):
        value = (context.get("metadata") or {}).get(key) or context.get(key)
        if value:
            signals.append(f"{key}: {value}")
    log_excerpt = context.get("log_excerpt")
    if log_excerpt:
        first_line = log_excerpt.splitlines()[0]
        if first_line:
            signals.append(f"מדגמי לוגים: {first_line}")
    if not signals:
        signals.append("אין אותות נוספים מעבר למה שסופק במידע הגולמי.")
    return signals[:4]


def _select_sections(expected_sections: Optional[Sequence[str]]) -> List[str]:
    if not expected_sections:
        return list(_DEFAULT_SECTIONS)
    normalized: List[str] = []
    for section in expected_sections:
        name = str(section or "").strip().lower()
        if name in _DEFAULT_SECTIONS and name not in normalized:
            normalized.append(name)
    return normalized or list(_DEFAULT_SECTIONS)


def _build_prompt(context: Dict[str, Any], sections: Sequence[str]) -> str:
    context_json = json.dumps(context, ensure_ascii=False, sort_keys=True)
    sections_text = ", ".join(sections)
    return (
        "קיבלת הקשר התראה מסונן (PII כבר טופל). "
        "עליך להחזיר JSON קצר וחוקי בלבד ללא הקדמות. "
        f"השדות הנדרשים: {sections_text}. "
        "root_cause היא מחרוזת אחת, actions/signals הם מערכים של עד 4 פריטים. "
        "הימנע מהמצאת נתונים שלא מופיעים בהקשר.\n"
        f"הקשר:\n{context_json}"
    )


async def _call_anthropic(prompt: str, *, timeout: float) -> Dict[str, Any]:
    if not _ANTHROPIC_API_KEY:
        raise AiExplainError("anthropic_api_key_missing")
    headers = {
        "x-api-key": _ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": _PROVIDER_MODEL,
        "max_tokens": _MAX_OUTPUT_TOKENS,
        "temperature": _TEMPERATURE,
        "system": _SYSTEM_PROMPT,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
    }
    http_timeout = httpx.Timeout(timeout, connect=min(3.0, timeout / 2), read=timeout, write=timeout / 2)
    async with httpx.AsyncClient(timeout=http_timeout) as client:
        response = await client.post(_ANTHROPIC_API_URL, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()


def _extract_text_block(provider_response: Dict[str, Any]) -> str:
    content = provider_response.get("content")
    if isinstance(content, list):
        texts: List[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
                texts.append(str(item["text"]))
        if texts:
            return "".join(texts).strip()
    if isinstance(provider_response.get("output_text"), str):
        return provider_response["output_text"].strip()
    return ""


def _parse_json_payload(raw_text: str) -> Dict[str, Any]:
    candidate = raw_text.strip()
    if not candidate:
        raise AiExplainError("provider_empty_response")
    if not candidate.startswith("{"):
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = candidate[start : end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise AiExplainError("provider_invalid_json") from exc


def _ensure_list_of_strings(values: Any, limit: int = 4) -> List[str]:
    result: List[str] = []
    if isinstance(values, str):
        values = [values]
    if isinstance(values, Iterable) and not isinstance(values, (bytes, bytearray)):
        for item in values:
            text = str(item).strip()
            if not text:
                continue
            result.append(_truncate(_mask_sensitive(text), _MAX_STRING // 2))
            if len(result) >= limit:
                break
    return result


def _normalize_payload(
    provider_payload: Dict[str, Any],
    context: Dict[str, Any],
    sections: Sequence[str],
) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    raw_root = str(provider_payload.get("root_cause") or provider_payload.get("rootCause") or "").strip()
    root_cause = _truncate(_mask_sensitive(raw_root), _MAX_STRING) if raw_root else _fallback_root_cause(context)
    actions = _ensure_list_of_strings(
        provider_payload.get("actions") or provider_payload.get("recommendations"), limit=4
    )
    if not actions:
        actions = _fallback_actions(context)
    signals = _ensure_list_of_strings(
        provider_payload.get("signals") or provider_payload.get("notable_signals"), limit=4
    )
    if not signals:
        signals = _fallback_signals(context)

    normalized["root_cause"] = root_cause
    normalized["actions"] = actions
    normalized["signals"] = signals

    now = datetime.now(timezone.utc).isoformat()
    normalized["provider"] = _PROVIDER_LABEL or _PROVIDER_MODEL
    normalized["model"] = _PROVIDER_MODEL
    normalized["generated_at"] = now
    normalized["cached"] = False

    missing = [section for section in sections if section not in normalized]
    for section in missing:
        normalized[section] = "" if section == "root_cause" else []
    return normalized


async def generate_ai_explanation(
    context: Dict[str, Any],
    *,
    expected_sections: Optional[Sequence[str]] = None,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build a prompt from the incoming alert context and fetch an AI explanation.

    Args:
        context: Alert context payload (already masked by the dashboard layer).
        expected_sections: Optional override for required sections.
        request_id: Optional correlation ID for logging.
    """

    if not isinstance(context, dict):
        raise AiExplainError("invalid_context")

    sections = _select_sections(expected_sections)
    sanitized_context = _sanitize_context(context)
    prompt = _build_prompt(sanitized_context, sections)

    try:
        provider_response = await _call_anthropic(prompt, timeout=_REQUEST_TIMEOUT)
    except httpx.TimeoutException as exc:  # pragma: no cover - network behavior
        logger.warning(
            "ai_explain_provider_timeout",
            extra={"request_id": request_id, "provider": _PROVIDER_MODEL},
        )
        raise AiExplainError("provider_timeout") from exc
    except httpx.HTTPStatusError as exc:  # pragma: no cover - network behavior
        logger.warning(
            "ai_explain_provider_http_error",
            extra={
                "status_code": exc.response.status_code,
                "request_id": request_id,
                "provider": _PROVIDER_MODEL,
            },
        )
        raise AiExplainError("provider_http_error") from exc
    except httpx.RequestError as exc:  # pragma: no cover - network behavior
        logger.warning(
            "ai_explain_provider_request_error",
            extra={"error": str(exc), "request_id": request_id, "provider": _PROVIDER_MODEL},
        )
        raise AiExplainError("provider_request_error") from exc

    text_block = _extract_text_block(provider_response)
    payload = _parse_json_payload(text_block)
    normalized = _normalize_payload(payload, sanitized_context, sections)
    normalized.update(
        {
            "alert_uid": sanitized_context.get("alert_uid"),
            "alert_name": sanitized_context.get("alert_name"),
            "severity": sanitized_context.get("severity"),
        }
    )
    return normalized
