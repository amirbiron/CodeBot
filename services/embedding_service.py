"""
Embedding service using the Gemini API (async).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from typing import List, Optional, Sequence

import httpx

logger = logging.getLogger(__name__)

# Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "text-embedding-004")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"
EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "768"))

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

    async def generate_embedding(self, text: str) -> Optional[List[float]]:
        """
        Generate an embedding for a single text (async).

        Args:
            text: input text

        Returns:
            embedding vector or None on failure
        """
        if not self.is_available():
            return None

        if not text or not text.strip():
            return None

        # Trim overly long text (Gemini limit ~10K tokens)
        text = text[:30000]

        url = f"{GEMINI_API_URL}/{GEMINI_EMBEDDING_MODEL}:embedContent"
        payload = {
            "model": f"models/{GEMINI_EMBEDDING_MODEL}",
            "content": {"parts": [{"text": text}]},
            "outputDimensionality": EMBEDDING_DIMENSIONS,
        }

        for attempt in range(MAX_RETRIES):
            try:
                response = await self.client.post(
                    url,
                    json=payload,
                    params={"key": self.api_key},
                    headers={"Content-Type": "application/json"},
                )

                if response.status_code == 200:
                    data = response.json()
                    embedding = data.get("embedding", {}).get("values", [])
                    if embedding:
                        return embedding
                    logger.error("Empty embedding in response: %s", data)
                    return None

                if response.status_code == 429:
                    wait_time = RETRY_DELAY_SECONDS * (2**attempt)
                    logger.warning("Rate limited, waiting %ss...", wait_time)
                    await asyncio.sleep(wait_time)
                    continue

                logger.error(
                    "Gemini API error %s: %s", response.status_code, response.text
                )
                return None

            except httpx.TimeoutException:
                logger.warning("Timeout on attempt %s", attempt + 1)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY_SECONDS)
                    continue
                return None

            except Exception as exc:
                logger.error("Embedding generation failed: %s", exc)
                return None

        return None

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
