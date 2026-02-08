"""
Background worker for embedding processing.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from database.manager import (
    get_snippets_needing_processing,
    save_snippet_chunks,
    update_snippet_embedding_status,
)
from services.embedding_service import get_embedding_service, compute_content_hash
from services.chunking_service import split_code_to_chunks, create_embedding_text
from services.semantic_embedding_settings import get_embedding_settings_cached, make_embedding_key

logger = logging.getLogger(__name__)

# Configuration
BATCH_SIZE = 10
POLL_INTERVAL_SECONDS = 60
MAX_ERRORS_BEFORE_PAUSE = 5


class EmbeddingWorker:
    """Background worker for embeddings."""

    def __init__(self):
        self.embedding_service = get_embedding_service()
        self._running = False
        self._error_count = 0

    async def start(self):
        """Start the worker."""
        if not self.embedding_service.is_available():
            logger.warning("Embedding service not available, worker disabled")
            return

        self._running = True
        logger.info("Embedding worker started")

        while self._running:
            try:
                processed = await self._process_batch()
                if processed == 0:
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
                else:
                    await asyncio.sleep(5)
                    self._error_count = 0
            except Exception as exc:
                self._error_count += 1
                logger.error("Worker error (%s): %s", self._error_count, exc)
                if self._error_count >= MAX_ERRORS_BEFORE_PAUSE:
                    logger.warning("Too many errors, pausing worker for 5 minutes")
                    await asyncio.sleep(300)
                    self._error_count = 0
                else:
                    await asyncio.sleep(30)

    def stop(self):
        """Stop the worker."""
        self._running = False
        logger.info("Embedding worker stopped")

    async def _process_batch(self) -> int:
        """Process a batch of snippets."""
        snippets = await get_snippets_needing_processing(limit=BATCH_SIZE)
        if not snippets:
            return 0

        processed = 0
        for snippet in snippets:
            try:
                await self._process_snippet(snippet)
                processed += 1
            except Exception as exc:
                logger.error(
                    "Failed to process snippet %s: %s", snippet.get("_id"), exc
                )

        logger.info("Processed %s/%s snippets", processed, len(snippets))
        return processed

    async def _process_snippet(self, snippet: dict) -> None:
        """Process a single snippet."""
        snippet_id = snippet["_id"]
        user_id = snippet["user_id"]
        content = snippet.get("code") or snippet.get("content") or ""
        settings = get_embedding_settings_cached(allow_db=True)
        # Keep an "effective" metadata snapshot for this snippet processing.
        effective_model = str(getattr(settings, "model", "") or "")
        effective_api_version = str(getattr(settings, "api_version", "") or "v1beta")
        effective_dim = int(getattr(settings, "dimensions", 0) or 768)
        effective_key = str(getattr(settings, "active_key", "") or "") or make_embedding_key(
            api_version=effective_api_version,
            model=effective_model,
            dimensions=effective_dim,
        )

        async def _embed_with_settings(text: str) -> Optional[list[float]]:
            """
            Embed using the *current* settings snapshot for consistency of metadata.

            If the model is missing (404), we trigger EmbeddingService.generate_embedding() which
            includes self-heal (ListModels pick) and persistence. After it returns an embedding,
            we refresh `settings` so metadata matches the actual model going forward.
            """
            nonlocal settings
            nonlocal effective_model, effective_api_version, effective_dim, effective_key
            model = str(getattr(settings, "model", "") or "")
            api_version = str(getattr(settings, "api_version", "") or "v1beta")
            dimensions = int(getattr(settings, "dimensions", 0) or 768)

            try:
                embedding, status, body = await self.embedding_service.generate_embedding_with_status(
                    text,
                    model=model,
                    api_version=api_version,
                    dimensions=dimensions,
                )
            except Exception:
                return None

            if embedding:
                # Ensure effective metadata matches actual settings used.
                try:
                    effective_model = model
                    effective_api_version = api_version
                    effective_dim = int(len(embedding) or dimensions or 0) or int(dimensions or 0) or 768
                    effective_key = make_embedding_key(
                        api_version=effective_api_version,
                        model=effective_model,
                        dimensions=effective_dim,
                    )
                except Exception:
                    pass
                return embedding

            # Only if model is missing: trigger self-heal via the standard API.
            if int(status or 0) == 404:
                try:
                    healed = await self.embedding_service.generate_embedding(text)
                except Exception:
                    healed = None
                if healed:
                    # Refresh settings so metadata reflects the working model.
                    try:
                        settings = get_embedding_settings_cached(allow_db=True)
                        effective_model = str(getattr(settings, "model", "") or effective_model)
                        effective_api_version = str(
                            getattr(settings, "api_version", "") or effective_api_version
                        )
                        effective_dim = int(getattr(settings, "dimensions", 0) or len(healed) or effective_dim)
                        effective_key = str(getattr(settings, "active_key", "") or "") or make_embedding_key(
                            api_version=effective_api_version,
                            model=effective_model,
                            dimensions=effective_dim,
                        )
                    except Exception:
                        pass
                    return healed

            # Dimension mismatch (best-effort): retry without fixed dimensionality.
            try:
                if int(status or 0) == 422 and "dimension_mismatch" in str(body or ""):
                    emb2, st2, _b2 = await self.embedding_service.generate_embedding_with_status(
                        text,
                        model=model,
                        api_version=api_version,
                        dimensions=0,
                    )
                    _ = st2
                    if emb2:
                        # Update effective metadata to match the actual returned dimension.
                        try:
                            effective_model = model
                            effective_api_version = api_version
                            effective_dim = int(len(emb2) or 0) or effective_dim
                            effective_key = make_embedding_key(
                                api_version=effective_api_version,
                                model=effective_model,
                                dimensions=effective_dim,
                            )
                        except Exception:
                            pass
                        return emb2
            except Exception:
                pass

            return None

        if not content:
            await save_snippet_chunks(
                user_id=user_id,
                snippet_id=snippet_id,
                chunks=[],
            )
            await update_snippet_embedding_status(
                snippet_id=snippet_id,
                content_hash="empty",
                chunk_count=0,
                embedding_model_key=effective_key,
                embedding_model=effective_model,
                embedding_api_version=effective_api_version,
                embedding_dim=effective_dim,
            )
            return

        current_hash = compute_content_hash(content)
        needs_processing = bool(
            snippet.get("needs_embedding") or snippet.get("needs_chunking")
        )
        if current_hash == snippet.get("contentHash") and not needs_processing:
            logger.debug("Snippet %s unchanged, clearing flags", snippet_id)
            await update_snippet_embedding_status(
                snippet_id=snippet_id,
                content_hash=current_hash,
                chunk_count=int(snippet.get("chunkCount", 0) or 0),
            )
            return

        chunks = split_code_to_chunks(content)
        if not chunks:
            await update_snippet_embedding_status(
                snippet_id=snippet_id,
                content_hash=current_hash,
                chunk_count=0,
                embedding_model_key=effective_key,
                embedding_model=effective_model,
                embedding_api_version=effective_api_version,
                embedding_dim=effective_dim,
            )
            return

        chunk_docs = []
        for chunk in chunks:
            embedding_text = create_embedding_text(
                code_chunk=chunk.content,
                title=snippet.get("file_name"),
                description=snippet.get("description"),
                tags=snippet.get("tags", []),
                language=snippet.get("programming_language"),
            )

            embedding = await _embed_with_settings(embedding_text)
            if embedding:
                chunk_docs.append(
                    {
                        "chunkIndex": chunk.index,
                        "codeChunk": chunk.content,
                        "startLine": chunk.start_line,
                        "endLine": chunk.end_line,
                        "language": snippet.get("programming_language", "unknown"),
                        "chunkEmbedding": embedding,
                        "embeddingModelKey": effective_key,
                        "embeddingModel": effective_model,
                        "embeddingApiVersion": effective_api_version,
                        "embeddingDim": effective_dim,
                    }
                )

        await save_snippet_chunks(
            user_id=user_id,
            snippet_id=snippet_id,
            chunks=chunk_docs,
        )

        metadata_text = create_embedding_text(
            code_chunk="",
            title=snippet.get("file_name"),
            description=snippet.get("description"),
            tags=snippet.get("tags", []),
            language=snippet.get("programming_language"),
        )
        snippet_embedding = await _embed_with_settings(metadata_text)

        should_retry = len(chunk_docs) < len(chunks) or snippet_embedding is None
        await update_snippet_embedding_status(
            snippet_id=snippet_id,
            content_hash=current_hash,
            chunk_count=len(chunk_docs),
            snippet_embedding=snippet_embedding,
            needs_embedding=should_retry,
            needs_chunking=False,
            embedding_model_key=effective_key,
            embedding_model=effective_model,
            embedding_api_version=effective_api_version,
            embedding_dim=effective_dim,
        )

        logger.info("Processed snippet %s: %s chunks", snippet_id, len(chunk_docs))


_worker: Optional[EmbeddingWorker] = None


def get_embedding_worker() -> EmbeddingWorker:
    global _worker
    if _worker is None:
        _worker = EmbeddingWorker()
    return _worker
