"""
שירות יצירת Embeddings עבור חיפוש סמנטי.
Embedding Service for Semantic Search.
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import List, Optional

import httpx

from config import config

logger = logging.getLogger(__name__)

# ===== Constants =====
_OPENAI_API_URL = "https://api.openai.com/v1/embeddings"
_DEFAULT_MODEL = "text-embedding-3-small"
_DEFAULT_DIMENSIONS = 1536

# Observability imports (safe fallbacks)
try:
    from observability import emit_event
except Exception:  # pragma: no cover

    def emit_event(event: str, severity: str = "info", **fields):
        return None


try:
    from metrics import track_performance
except Exception:  # pragma: no cover
    from contextlib import contextmanager

    @contextmanager
    def track_performance(operation: str, labels=None):
        yield


class EmbeddingError(RuntimeError):
    """שגיאה ביצירת embedding."""


def _get_api_key() -> str:
    """קבלת API key מהקונפיג או מ-ENV."""
    return getattr(config, "OPENAI_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")


def _get_model() -> str:
    """קבלת שם המודל."""
    return getattr(config, "EMBEDDING_MODEL", _DEFAULT_MODEL) or _DEFAULT_MODEL


def _get_dimensions() -> int:
    """קבלת מספר הממדים."""
    return int(getattr(config, "EMBEDDING_DIMENSIONS", _DEFAULT_DIMENSIONS) or _DEFAULT_DIMENSIONS)


def _truncate_text(text: str, max_chars: int) -> str:
    """קיצור טקסט למקסימום תווים."""
    if not text:
        return ""
    max_chars = max(100, int(max_chars))
    if len(text) <= max_chars:
        return text
    # חיתוך חכם: נסה לחתוך בסוף משפט או שורה
    truncated = text[:max_chars]
    # מצא את הנקודה או השורה החדשה האחרונה
    for sep in ["\n\n", "\n", ". ", ".\n"]:
        last_sep = truncated.rfind(sep)
        if last_sep > max_chars * 0.7:  # לפחות 70% מהטקסט
            return truncated[: last_sep + len(sep)].strip()
    return truncated.strip()


def _prepare_text_for_embedding(
    code: str,
    file_name: str = "",
    description: str = "",
    tags: Optional[List[str]] = None,
    programming_language: str = "",
) -> str:
    """
    הכנת טקסט לשליחה ל-Embedding API.
    משלב מטא-דאטה עם הקוד לקבלת embedding עשיר יותר.
    """
    parts: List[str] = []

    # הוסף מטא-דאטה (משקל גבוה יותר לפריטים אלו)
    if file_name:
        parts.append(f"File: {file_name}")
    if programming_language:
        parts.append(f"Language: {programming_language}")
    if description:
        parts.append(f"Description: {description}")
    if tags:
        safe_tags = [str(t).strip() for t in tags if t and not str(t).startswith("repo:")]
        if safe_tags:
            parts.append(f"Tags: {', '.join(safe_tags)}")

    # הוסף את הקוד עצמו
    if code:
        # אופטימיזציה: עבור קוד ארוך, התמקד בהערות ובהתחלה
        max_code_chars = int(getattr(config, "EMBEDDING_MAX_CHARS", 2000) or 2000)
        code_truncated = _truncate_text(code, max_code_chars)
        parts.append(f"Code:\n{code_truncated}")

    return "\n".join(parts)


async def generate_embedding(
    text: str,
    *,
    timeout: float = 10.0,
) -> List[float]:
    """
    יצירת embedding vector עבור טקסט.

    Args:
        text: הטקסט ליצירת embedding.
        timeout: זמן מקסימלי לבקשה בשניות.

    Returns:
        רשימת floats (וקטור) באורך EMBEDDING_DIMENSIONS.

    Raises:
        EmbeddingError: במקרה של שגיאה.
    """
    api_key = _get_api_key()
    if not api_key:
        raise EmbeddingError("openai_api_key_missing")

    if not text or not text.strip():
        raise EmbeddingError("empty_text")

    model = _get_model()
    dimensions = _get_dimensions()

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "input": text.strip(),
        "dimensions": dimensions,
    }

    try:
        emit_event("embedding_request_start", severity="debug", model=model)
    except Exception:
        pass

    with track_performance("embedding_api_call", labels={"model": model}):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(_OPENAI_API_URL, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            logger.warning("embedding_api_timeout", extra={"model": model})
            raise EmbeddingError("embedding_timeout") from exc
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "embedding_api_http_error",
                extra={"status_code": exc.response.status_code, "model": model},
            )
            raise EmbeddingError(f"embedding_http_error_{exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            logger.warning("embedding_api_request_error", extra={"error": str(exc)})
            raise EmbeddingError("embedding_request_error") from exc

    # חילוץ הווקטור מהתגובה
    try:
        embedding = data["data"][0]["embedding"]
        if not isinstance(embedding, list) or len(embedding) != dimensions:
            raise EmbeddingError("embedding_invalid_response")

        try:
            emit_event(
                "embedding_request_done",
                severity="debug",
                model=model,
                dimensions=len(embedding),
            )
        except Exception:
            pass

        return embedding
    except (KeyError, IndexError, TypeError) as exc:
        raise EmbeddingError("embedding_parse_error") from exc


async def generate_embedding_for_file(
    code: str,
    file_name: str = "",
    description: str = "",
    tags: Optional[List[str]] = None,
    programming_language: str = "",
    **kwargs,
) -> List[float]:
    """
    יצירת embedding עבור קובץ קוד (convenience function).

    משלב את כל המטא-דאטה עם הקוד לקבלת embedding מדויק יותר.
    """
    text = _prepare_text_for_embedding(
        code=code,
        file_name=file_name,
        description=description,
        tags=tags,
        programming_language=programming_language,
    )
    return await generate_embedding(text, **kwargs)


def generate_embedding_sync(text: str, *, timeout: float = 10.0) -> List[float]:
    """
    גרסה סינכרונית ליצירת embedding (לשימוש ב-background jobs).
    """
    import asyncio

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # אם כבר יש event loop רץ, צור חדש
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, generate_embedding(text, timeout=timeout))
                return future.result(timeout=timeout + 5)
        else:
            return loop.run_until_complete(generate_embedding(text, timeout=timeout))
    except Exception:
        # Fallback לפשטות
        return asyncio.run(generate_embedding(text, timeout=timeout))


# ===== Cache helpers =====
def _hash_text(text: str) -> str:
    """יצירת hash קצר לטקסט (לצורכי cache)."""
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:32]

