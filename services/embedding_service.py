"""
Embedding service using the Gemini API (async).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx

logger = logging.getLogger(__name__)
# חשוב: httpx יכול להדפיס URL מלא (כולל API key בפרמטרים).
# כדי למנוע דליפת סודות בלוגים, נוריד את הלוגר שלו ל-WARNING כברירת מחדל.
try:
    logging.getLogger("httpx").setLevel(logging.WARNING)
except Exception:
    pass

# Self-heal throttling (avoid thundering herd on 404)
# None means "never ran" (avoid blocking first attempt).
_LAST_SELF_HEAL_TS: Optional[float] = None
_SELF_HEAL_COOLDOWN_SECONDS = float(os.getenv("EMBEDDING_SELF_HEAL_COOLDOWN_SECONDS", "60") or 60)

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
        }
        # outputDimensionality optional. If <=0, omit and accept provider default dimension.
        if int(dim or 0) > 0:
            payload["outputDimensionality"] = int(dim)

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
                            if int(dim or 0) > 0 and len(embedding) != int(dim):
                                logger.warning(
                                    "Embedding dimensions mismatch: expected=%s actual=%s model=%s api=%s",
                                    int(dim),
                                    int(len(embedding)),
                                    model_n,
                                    str(api_version),
                                )
                                # Use internal status code to allow upgrade logic to react.
                                return None, 422, f"dimension_mismatch expected={int(dim)} actual={int(len(embedding))}"
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

    async def list_models_detailed(self, *, api_version: str) -> List[Dict[str, Any]]:
        """
        Best-effort list of available models with metadata (e.g. supportedGenerationMethods).
        Returns raw dicts with normalized name (no "models/" prefix) when possible.
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
        out: List[Dict[str, Any]] = []
        for m in models:
            if not isinstance(m, dict):
                continue
            try:
                name = str(m.get("name") or "").strip()
            except Exception:
                name = ""
            if name.startswith("models/"):
                name = name[len("models/") :]
            if not name:
                continue
            item = dict(m)
            item["name"] = name
            out.append(item)
        return out

    def _model_supports_embed_content(self, model_doc: Dict[str, Any]) -> bool:
        try:
            methods = model_doc.get("supportedGenerationMethods")
        except Exception:
            methods = None
        if not isinstance(methods, list):
            return False
        try:
            return any(str(m).strip() == "embedContent" for m in methods)
        except Exception:
            return False

    async def _self_heal_on_404(
        self,
        *,
        text: str,
        preferred_dimensions: int,
        preferred_allowlist: Optional[List[str]] = None,
        existing_legacy_key: Optional[str] = None,
        existing_active_key: Optional[str] = None,
    ) -> Optional[List[float]]:
        """
        If current model is 404, attempt to auto-select a working embedding model from ListModels
        and use it immediately. Best-effort persist to DB.
        """
        global _LAST_SELF_HEAL_TS
        try:
            now = float(time.monotonic())
        except Exception:
            now = 0.0
        try:
            if (
                _LAST_SELF_HEAL_TS is not None
                and now
                and (now - float(_LAST_SELF_HEAL_TS)) < float(_SELF_HEAL_COOLDOWN_SECONDS)
            ):
                return None
        except Exception:
            pass
        _LAST_SELF_HEAL_TS = now if now else _LAST_SELF_HEAL_TS

        allow = [normalize_model_name(x) for x in (preferred_allowlist or []) if str(x).strip()]
        legacy_to_keep = (str(existing_legacy_key or "").strip()) or (str(existing_active_key or "").strip())
        # list models (try v1beta then v1)
        for api_version in ["v1beta", "v1"]:
            models = await self.list_models_detailed(api_version=api_version)
            if not models:
                continue
            # candidates: embedContent-capable + contains "embedding"
            embed_models: List[str] = []
            for m in models:
                if not isinstance(m, dict):
                    continue
                if not self._model_supports_embed_content(m):
                    continue
                name = normalize_model_name(str(m.get("name") or ""))
                if not name:
                    continue
                if "embedding" not in name.lower():
                    continue
                embed_models.append(name)
            # order: allowlist intersection first, else provider order
            if allow:
                ordered = [m for m in allow if m in set(embed_models)]
            else:
                ordered = []
            if not ordered:
                ordered = embed_models
            # probe using the real text (already trimmed in generate_embedding_with_status)
            for candidate in ordered[:20]:
                emb, status, body = await self.generate_embedding_with_status(
                    text,
                    model=candidate,
                    api_version=api_version,
                    dimensions=int(preferred_dimensions or 0),
                )
                # If candidate exists but dimensionality differs, retry without requesting a fixed dimension.
                if (not emb) and int(status or 0) == 422 and "dimension_mismatch" in str(body or ""):
                    emb2, status_b, body_b = await self.generate_embedding_with_status(
                        text,
                        model=candidate,
                        api_version=api_version,
                        dimensions=0,
                    )
                    _ = status_b
                    _ = body_b
                    if emb2:
                        emb = emb2
                if emb:
                    # Persist best-effort so future calls don't need self-heal
                    try:
                        from services.semantic_embedding_settings import upsert_embedding_settings  # type: ignore

                        upsert_embedding_settings(
                            api_version=api_version,
                            model=candidate,
                            # Prefer the actual returned dimension (safe) over the old preferred dimension.
                            dimensions=int(len(emb) or 0),
                            allowlist=allow or None,
                            # חשוב: לא לדרוס legacy_key - נשמור את הערך הקיים כדי לא לאבד מעקב על embeddings ישנים.
                            legacy_key=legacy_to_keep or None,
                            active_key=None,
                            reason="self_heal_404",
                            extra={"lastSelfHealAt": datetime.now(timezone.utc)},
                        )
                    except Exception:
                        pass
                    return emb
                _ = status
                _ = body
        return None

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
            allowlist = list(getattr(settings, "allowlist", []) or [])
        else:
            model = GEMINI_EMBEDDING_MODEL
            api_version = GEMINI_API_VERSION
            dimensions = EMBEDDING_DIMENSIONS
            allowlist = []

        embedding, status1, _body1 = await self.generate_embedding_with_status(
            text,
            model=str(model),
            api_version=str(api_version),
            dimensions=int(dimensions),
        )
        # Fail-open fallback: אם הוגדר v1beta אבל המודל לא קיים שם (404),
        # נסה פעם אחת v1 (גם אם עדכון קונפיג ב-DB נכשל).
        status2 = None
        try:
            if embedding is None and int(status1 or 0) == 404 and str(api_version or "").strip() != "v1":
                embedding2, status2, _body2 = await self.generate_embedding_with_status(
                    text,
                    model=str(model),
                    api_version="v1",
                    dimensions=int(dimensions),
                )
                if embedding2:
                    return embedding2
        except Exception:
            pass
        # Self-heal: if still 404, try to pick a working model from ListModels automatically.
        try:
            if embedding is None and int(status1 or 0) == 404 and (status2 is None or int(status2 or 0) == 404):
                healed = await self._self_heal_on_404(
                    text=text,
                    preferred_dimensions=int(dimensions),
                    preferred_allowlist=allowlist,
                    existing_legacy_key=str(getattr(settings, "legacy_key", "") or "") if settings is not None else "",
                    existing_active_key=str(getattr(settings, "active_key", "") or "") if settings is not None else "",
                )
                if healed:
                    return healed
        except Exception:
            pass
        # Keep old behavior: just return embedding or None.
        # Special case: if model is missing (404), callers may run startup health check to auto-upgrade.
        _ = status1
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
