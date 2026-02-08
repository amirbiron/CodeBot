"""
Embedding service using the Gemini API (async).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx

logger = logging.getLogger(__name__)

# Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "text-embedding-004")  # fallback only
GEMINI_API_VERSION = os.getenv("GEMINI_API_VERSION", "v1beta")  # fallback only
EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "768"))  # fallback only

# Best-effort dynamic config (DB-backed). Fail-open.
try:
    from services.semantic_embedding_settings import get_embedding_settings_cached, normalize_model_name  # type: ignore
except Exception:  # pragma: no cover
    def get_embedding_settings_cached(*, allow_db: bool = True):  # type: ignore
        return None

    def normalize_model_name(model: str) -> str:  # type: ignore
        m = str(model or "").strip()
        return m[len("models/") :].strip() if m.startswith("models/") else m

# Rate limiting
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2.0
REQUEST_TIMEOUT = 30.0


class EmbeddingError(Exception):
    """Embedding generation error."""


class EmbeddingService:
    """Async embedding generation service."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or GEMINI_API_KEY
        if not self.api_key:
            logger.warning("GEMINI_API_KEY not configured - semantic search disabled")
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Lazy initialization of the AsyncClient."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)
        return self._client

    def is_available(self) -> bool:
        """Check if the service is available."""
        return bool(self.api_key)

    def _base_url(self, api_version: str) -> str:
        av = str(api_version or "").strip().lstrip("/") or "v1beta"
        if av not in {"v1", "v1beta"}:
            av = "v1beta"
        return f"https://generativelanguage.googleapis.com/{av}/models"

    async def generate_embedding_with_status(
        self,
        text: str,
        *,
        model: str,
        api_version: str,
        dimensions: int,
    ) -> Tuple[Optional[List[float]], int, str]:
        """
        Embed text with an explicit (model, api_version, dimensions) and return (embedding, status, body).
        Intended for health-check / upgrade logic.
        """
        if not self.is_available():
            return None, 0, "missing_api_key"

        if not text or not text.strip():
            return None, 0, "empty_text"

        # Trim overly long text (Gemini limit ~10K tokens)
        text = text[:30000]

        model_n = normalize_model_name(model)
        try:
            dim = int(dimensions)
        except Exception:
            dim = EMBEDDING_DIMENSIONS

        base_url = self._base_url(api_version)
        url = f"{base_url}/{model_n}:embedContent"
        payload: Dict[str, Any] = {
            "model": f"models/{model_n}",
            "content": {"parts": [{"text": text}]},
            "outputDimensionality": dim,
        }

        last_body = ""
        for attempt in range(MAX_RETRIES):
            try:
                response = await self.client.post(
                    url,
                    json=payload,
                    params={"key": self.api_key},
                    headers={"Content-Type": "application/json"},
                )
                try:
                    last_body = response.text
                except Exception:
                    last_body = ""

                if response.status_code == 200:
                    try:
                        data = response.json()
                    except Exception:
                        return None, 200, last_body
                    embedding = data.get("embedding", {}).get("values", [])
                    if embedding and isinstance(embedding, list):
                        # Ensure expected dim (fail-safe)
                        try:
                            if dim and len(embedding) != int(dim):
                                logger.warning(
                                    "Embedding dimensions mismatch: expected=%s actual=%s model=%s api=%s",
                                    int(dim),
                                    int(len(embedding)),
                                    model_n,
                                    str(api_version),
                                )
                                return None, 200, last_body
                        except Exception:
                            pass
                        return embedding, 200, last_body
                    logger.error("Empty embedding in response: %s", data)
                    return None, 200, last_body

                if response.status_code == 429:
                    wait_time = RETRY_DELAY_SECONDS * (2**attempt)
                    logger.warning("Rate limited, waiting %ss...", wait_time)
                    await asyncio.sleep(wait_time)
                    continue

                # 404 is handled by callers (upgrade logic). Others: just return.
                logger.error(
                    "Gemini API error %s: %s", response.status_code, last_body
                )
                return None, int(response.status_code), last_body

            except httpx.TimeoutException:
                logger.warning("Timeout on attempt %s", attempt + 1)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY_SECONDS)
                    continue
                return None, 0, "timeout"

            except Exception as exc:
                logger.error("Embedding generation failed: %s", exc)
                return None, 0, str(exc)

        return None, 0, last_body

    async def list_models(self, *, api_version: str) -> List[str]:
        """
        Best-effort list of available models via REST (similar to genai.list_models()).
        Returns model names without the "models/" prefix.
        """
        if not self.is_available():
            return []
        base_url = self._base_url(api_version)
        try:
            resp = await self.client.get(
                base_url,
                params={"key": self.api_key},
                headers={"Content-Type": "application/json"},
            )
        except Exception:
            return []
        if int(getattr(resp, "status_code", 0) or 0) != 200:
            return []
        try:
            data = resp.json()
        except Exception:
            return []
        models = data.get("models")
        if not isinstance(models, list):
            return []
        out: List[str] = []
        for m in models:
            if not isinstance(m, dict):
                continue
            name = str(m.get("name") or "").strip()
            if not name:
                continue
            # name is usually "models/xyz"
            if name.startswith("models/"):
                name = name[len("models/") :]
            out.append(name)
        # Dedup (stable)
        seen = set()
        deduped: List[str] = []
        for x in out:
            if x in seen:
                continue
            seen.add(x)
            deduped.append(x)
        return deduped

    async def generate_embedding(self, text: str) -> Optional[List[float]]:
        """
        Generate an embedding for a single text (async).

        Args:
            text: input text

        Returns:
            embedding vector or None on failure
        """
        # Pull dynamic settings (DB-backed) if available; fallback to ENV constants.
        settings = None
        try:
            settings = get_embedding_settings_cached(allow_db=True)
        except Exception:
            settings = None

        if settings is not None:
            model = getattr(settings, "model", "") or GEMINI_EMBEDDING_MODEL
            api_version = getattr(settings, "api_version", "") or GEMINI_API_VERSION
            dimensions = int(getattr(settings, "dimensions", 0) or EMBEDDING_DIMENSIONS)
        else:
            model = GEMINI_EMBEDDING_MODEL
            api_version = GEMINI_API_VERSION
            dimensions = EMBEDDING_DIMENSIONS

        embedding, status, _body = await self.generate_embedding_with_status(
            text,
            model=str(model),
            api_version=str(api_version),
            dimensions=int(dimensions),
        )
        # Keep old behavior: just return embedding or None.
        # Special case: if model is missing (404), callers may run startup health check to auto-upgrade.
        _ = status
        return embedding

    async def generate_embeddings_batch(
        self,
        texts: Sequence[str],
        batch_size: int = 10,
    ) -> List[Optional[List[float]]]:
        """
        Generate embeddings for multiple texts (async).

        Args:
            texts: list of texts
            batch_size: batch size (rate limiting)

        Returns:
            list of embeddings (None for failures)
        """
        results: List[Optional[List[float]]] = []

        for i, text in enumerate(texts):
            embedding = await self.generate_embedding(text)
            results.append(embedding)

            # Rate limiting between requests
            if (i + 1) % batch_size == 0:
                await asyncio.sleep(0.5)

        return results

    async def close(self) -> None:
        """Close the client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


# Singleton instance
_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """Get a singleton instance of the embedding service."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service


def compute_content_hash(content: str) -> str:
    """Compute a hash of content for change tracking."""
    return hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()
