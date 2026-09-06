"""
Background worker for embedding processing.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import List, Optional, Tuple

from database.manager import (
    get_snippets_needing_processing,
    is_latest_active_snippet,
    save_snippet_chunks,
    update_snippet_embedding_status,
)
from services.embedding_service import get_embedding_service, compute_content_hash
from services.chunking_service import (
    CHUNKER_VERSION,
    create_embedding_text,
    is_low_information_chunk,
    split_code_to_chunks,
)
from services.semantic_embedding_settings import get_embedding_settings_cached, make_embedding_key

try:  # Structured logging events
    from observability import emit_event
except Exception:  # pragma: no cover
    def emit_event(event: str, severity: str = "info", **fields):
        return None

logger = logging.getLogger(__name__)

# Configuration (overridable via env to calm Gemini rate limits)
BATCH_SIZE = int(os.getenv("EMBEDDING_WORKER_BATCH_SIZE", "5") or 5)
POLL_INTERVAL_SECONDS = int(os.getenv("EMBEDDING_WORKER_POLL_INTERVAL", "300") or 300)
BATCH_COOLDOWN_SECONDS = int(os.getenv("EMBEDDING_WORKER_BATCH_COOLDOWN", "30") or 30)
MAX_ERRORS_BEFORE_PAUSE = 5

# כשמכסת Gemini נגמרת, המשך לקובץ הבא רק שורף עוד קריאות על אותה תשובה.
# עוצרים את הבאץ' ומחכים. 15 דקות: ארוך מספיק כדי לא להתעקש על מכסה יומית
# שנגמרה, קצר מספיק כדי לא לעצור עבודה אחרי חלון קצר של rate limiting.
QUOTA_PAUSE_SECONDS = int(os.getenv("EMBEDDING_QUOTA_PAUSE_SECONDS", "900") or 900)

# סוגי כשל בהטמעת צ'אנק בודד.
#
# ההבחנה הזו היא הליבה: עד כה **כל** כשל בצ'אנק אחד סימן את הקובץ כולו
# ב-``needs_embedding=True``, כלומר הוא נשלף שוב כל 300 שניות וכל הצ'אנקים
# שלו נשלחו מחדש — לנצח. כל עוד Gemini חתך בשקט זה כמעט לא קרה; ברגע
# שמפסיקים את החיתוך השקט, זה הופך למסלול הראשי.
FAILURE_TRANSIENT = "transient"   # timeout / רשת / 5xx — כדאי לנסות שוב
FAILURE_PERMANENT = "permanent"   # 400 / קלט ארוך מדי — ניסיון חוזר לא יעזור
FAILURE_QUOTA = "quota"           # 429 אחרי מיצוי ה-retries
FAILURE_MODEL_MISSING = "model_missing"   # 404 — המודל נעלם, צריך self-heal


def _classify_status(status: int) -> str:
    """ממפה קוד סטטוס לסוג כשל. **נקודת המיפוי היחידה בקובץ.**

    * ``404`` — המודל שבקונפיג לא קיים. לא כשל של הצ'אנק אלא של ההגדרה,
      והתגובה הנכונה היא self-heal ולא retry.
    * ``400`` — הבקשה עצמה פסולה; ``413`` — הקלט חרג מהתקרה שלנו
      (``EMBEDDING_STATUS_INPUT_TOO_LONG``). בשני המקרים ניסיון חוזר יחזיר
      בדיוק את אותה תשובה.
    * ``429`` — מכסה. עוצר את הבאץ' כולו.
    * ``0`` (timeout/רשת), ``401``/``403`` (קונפיג שאפשר לתקן), ``5xx`` —
      כולם זמניים, ולכן הקובץ חוזר לתור.

    למה הכול כאן ולא מפוזר: אותו נתיב (ניסיון חוזר אחרי 422) נשבר **פעמיים
    ברצף** בשתי דרכים שונות — קודם הסטטוס השני נזרק לגמרי, ואז הוא נשמר אבל
    404 בו טופל כזמני. שתי התקלות אפשריות רק כשהמיפוי חי בשני מקומות. כאן
    יש מקום אחד, ו-``_act_on_status`` הוא הפעולה היחידה שנגזרת ממנו.
    """
    if status == 404:
        return FAILURE_MODEL_MISSING
    if status == 429:
        return FAILURE_QUOTA
    if status in (400, 413):
        return FAILURE_PERMANENT
    return FAILURE_TRANSIENT


class EmbeddingQuotaExhausted(Exception):
    """Gemini החזיר 429 גם אחרי מיצוי ה-retries. עוצרים את הבאץ'."""


class _RestartSnippetProcessing(Exception):
    """Internal signal: model/dim changed, restart snippet processing."""


class EmbeddingWorker:
    """Background worker for embeddings."""

    def __init__(self):
        self.embedding_service = get_embedding_service()
        self._running = False
        self._error_count = 0
        self._quota_hit = False

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
                if self._quota_hit:
                    self._quota_hit = False
                    logger.warning(
                        "Embedding quota exhausted, pausing worker for %ss",
                        QUOTA_PAUSE_SECONDS,
                    )
                    await asyncio.sleep(QUOTA_PAUSE_SECONDS)
                elif processed == 0:
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
                else:
                    await asyncio.sleep(BATCH_COOLDOWN_SECONDS)
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
            except EmbeddingQuotaExhausted:
                # שאר הבאץ' ייתקל באותה תשובה בדיוק. הקובץ הנוכחי נשאר עם
                # הדגלים שלו ועם הצ'אנקים הישנים שלו — ``save_snippet_chunks``
                # לא נקרא, ולכן שום דבר לא נמחק — והוא ייבחר שוב בסבב הבא.
                self._quota_hit = True
                emit_event(
                    "embedding_quota_exhausted",
                    severity="warn",
                    remaining_in_batch=len(snippets) - processed,
                )
                break
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

        async def _embed_with_settings(
            text: str,
        ) -> Tuple[Optional[List[float]], Optional[str]]:
            """מחזירה ``(embedding, failure_kind)``.

            ``failure_kind`` הוא אחד מ-``FAILURE_*`` או ``None`` בהצלחה.
            הפרדת סוגי הכשל היא מה שמונע את הלולאה האינסופית: רק כשל זמני
            מחזיר את הקובץ לתור.

            If the model is missing (404), we signal a restart so the outer loop
            can self-heal (ListModels pick) and refresh `settings`.
            """
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
                return None, FAILURE_TRANSIENT

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
                return embedding, None

            status = int(status or 0)

            def _act_on_status(code: int) -> str:
                """מסווג, ומטפל ב-404 באותו אופן בכל אתר קריאה.

                Model missing mid-processing: לא עושים self-heal במקום (זה היה
                מערבב וקטורים משתי הגדרות בתוך אותו סניפט), אלא מסמנים ללולאה
                החיצונית להתחיל את הסניפט מחדש אחרי שה-self-heal עדכן קונפיג.
                """
                failure = _classify_status(int(code or 0))
                if failure == FAILURE_MODEL_MISSING:
                    logger.warning(
                        "Snippet %s: model returned 404 (status=%s), signalling restart",
                        snippet_id, code,
                    )
                    raise _RestartSnippetProcessing()
                return failure

            failure = _act_on_status(status)
            if failure == FAILURE_QUOTA:
                return None, FAILURE_QUOTA

            # Dimension mismatch (best-effort): retry without fixed dimensionality.
            if status == 422 and "dimension_mismatch" in str(body or ""):
                try:
                    emb2, status2, _b2 = await self.embedding_service.generate_embedding_with_status(
                        text,
                        model=model,
                        api_version=api_version,
                        dimensions=0,
                    )
                except Exception:
                    emb2, status2 = None, 0
                if emb2:
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
                    return emb2, None
                # הסטטוס של הניסיון השני עובר **בדיוק** את אותו טיפול כמו של
                # הראשון — כולל 404, שמפעיל self-heal ולא retry. מודל שנעלם בין
                # שתי הקריאות היה שולח את הקובץ לרטריי אינסופי במקום לתקן את
                # ההגדרה.
                return None, _act_on_status(int(status2 or 0))

            return None, failure

        async def _finish(
            *,
            content_hash: str,
            chunk_count: int,
            snippet_embedding: Optional[List[float]] = None,
            needs_embedding: Optional[bool] = None,
            needs_chunking: Optional[bool] = None,
        ) -> None:
            """מסיים טיפול במסמך — תמיד עם ``chunkerVersion``.

            כל נתיב שמסתיים כאן הוא נתיב שבו באמת החלטנו מה לעשות עם המסמך.
            אם ``chunkerVersion`` לא ייכתב, המסמך יישלף שוב בכל סבב ויתפוס
            מקום בבאץ' של חמישה — ועבודה אמיתית לא תתוזמן לעולם.
            """
            await update_snippet_embedding_status(
                snippet_id=snippet_id,
                content_hash=content_hash,
                chunk_count=chunk_count,
                snippet_embedding=snippet_embedding,
                needs_embedding=needs_embedding,
                needs_chunking=needs_chunking,
                embedding_model_key=effective_key,
                embedding_model=effective_model,
                embedding_api_version=effective_api_version,
                embedding_dim=effective_dim,
                chunker_version=CHUNKER_VERSION,
            )

        if not content:
            await save_snippet_chunks(user_id=user_id, snippet_id=snippet_id, chunks=[])
            await _finish(content_hash="empty", chunk_count=0)
            return

        current_hash = compute_content_hash(content)
        try:
            # מסמך עם ערך פגום בשדה לא רשאי להפיל את העיבוד: ``_process_batch``
            # היה בולע את החריגה, והמסמך היה חוזר בכל סבב בלי שאיש יראה למה.
            chunker_is_current = int(snippet.get("chunkerVersion") or 0) == CHUNKER_VERSION
        except (TypeError, ValueError):
            chunker_is_current = False
        needs_processing = bool(
            snippet.get("needs_embedding")
            or snippet.get("needs_chunking")
            or not chunker_is_current
        )
        if current_hash == snippet.get("contentHash") and not needs_processing:
            logger.debug("Snippet %s unchanged, clearing flags", snippet_id)
            await _finish(
                content_hash=current_hash,
                chunk_count=int(snippet.get("chunkCount", 0) or 0),
            )
            return

        # גרסה שאינה האחרונה לא תופיע בתוצאות חיפוש בשום מקרה — הצינור מסנן
        # אותה. אין טעם לשלם עליה קריאות ל-Gemini, ואת הצ'אנקים שלה מנקים.
        is_latest = await is_latest_active_snippet(
            user_id, str(snippet.get("file_name") or ""), snippet_id
        )
        if not is_latest:
            await save_snippet_chunks(user_id=user_id, snippet_id=snippet_id, chunks=[])
            await _finish(content_hash=current_hash, chunk_count=0)
            logger.debug("Snippet %s is a superseded version, skipped", snippet_id)
            return

        # Protect against mid-processing model switches: allow one restart per snippet.
        chunk_docs: List[dict] = []
        for attempt in range(2):
            if attempt > 0:
                # Trigger self-heal once, then refresh settings snapshot.
                logger.info("Snippet %s: retry attempt %d - triggering self-heal",
                            snippet_id, attempt)
                try:
                    heal_result = await self.embedding_service.generate_embedding("healthcheck")
                    if heal_result:
                        logger.info("Snippet %s: self-heal produced embedding, refreshing settings", snippet_id)
                    else:
                        logger.warning(
                            "Snippet %s: self-heal returned None, retrying anyway",
                            snippet_id)
                except Exception as exc:
                    logger.warning("Snippet %s: self-heal raised exception: %s", snippet_id, exc)
                settings = get_embedding_settings_cached(allow_db=True)
                effective_model = str(getattr(settings, "model", "") or "")
                effective_api_version = str(getattr(settings, "api_version", "") or "v1beta")
                effective_dim = int(getattr(settings, "dimensions", 0) or 0) or 768
                effective_key = str(getattr(settings, "active_key", "") or "") or make_embedding_key(
                    api_version=effective_api_version,
                    model=effective_model,
                    dimensions=effective_dim,
                )
                logger.info("Snippet %s: retry using model=%s api=%s dim=%d key=%s",
                            snippet_id, effective_model, effective_api_version, effective_dim, effective_key)

            all_chunks = split_code_to_chunks(content)

            # סינון צ'אנקים חסרי משמעות **לפני** הלולאה, ולא בתוכה: כך
            # ``len(chunks)`` הוא מספר הניסיונות בפועל, ודילוג אינו נראה כמו
            # כשל. אילו היינו מסננים בתוך הלולאה, כל קובץ עם dump היה חוזר
            # לתור לנצח.
            chunks = []
            skipped_low_information = 0
            for chunk in all_chunks:
                if is_low_information_chunk(chunk.content):
                    skipped_low_information += 1
                    emit_event(
                        "embedding_chunk_skipped_low_information",
                        snippet_id=str(snippet_id),
                        chunk_index=int(chunk.index),
                        bytes=len(chunk.content.encode("utf-8")),
                    )
                    continue
                chunks.append(chunk)

            if not chunks:
                await save_snippet_chunks(user_id=user_id, snippet_id=snippet_id, chunks=[])
                await _finish(content_hash=current_hash, chunk_count=0)
                return

            chunk_docs = []
            transient_failures = 0
            permanent_failures = 0
            try:
                # ``chunkIndex`` ממוספר מחדש ברצף: הצינור בחיפוש מקבץ לפי
                # ``(snippetId, chunkIndex)``, וחורים במספור אינם מזיקים —
                # אבל מיפוי רציף שומר על ``chunkCount`` כמדד אמיתי.
                for position, chunk in enumerate(chunks):
                    embedding_text = create_embedding_text(
                        code_chunk=chunk.content,
                        title=snippet.get("file_name"),
                        description=snippet.get("description"),
                        tags=snippet.get("tags", []),
                        language=snippet.get("programming_language"),
                    )

                    embedding, failure = await _embed_with_settings(embedding_text)
                    if failure == FAILURE_QUOTA:
                        raise EmbeddingQuotaExhausted()
                    if embedding:
                        chunk_docs.append(
                            {
                                "chunkIndex": position,
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
                    elif failure == FAILURE_PERMANENT:
                        permanent_failures += 1
                        emit_event(
                            "embedding_chunk_rejected",
                            severity="warn",
                            snippet_id=str(snippet_id),
                            chunk_index=int(chunk.index),
                            bytes=len(chunk.content.encode("utf-8")),
                        )
                    else:
                        transient_failures += 1
            except _RestartSnippetProcessing:
                # Model disappeared mid-run: restart (once).
                if attempt == 0:
                    logger.info("Snippet %s: 404 during chunk processing (attempt 0), will restart", snippet_id)
                    continue
                # second failure: give up for now (leave needs_embedding True)
                logger.warning("Snippet %s: 404 during chunk processing (attempt 1), giving up", snippet_id)
                # Clear any orphaned chunks from a previous attempt that may have saved chunks
                # before the metadata embedding triggered a restart.
                await save_snippet_chunks(user_id=user_id, snippet_id=snippet_id, chunks=[])
                await update_snippet_embedding_status(
                    snippet_id=snippet_id,
                    content_hash=current_hash,
                    chunk_count=0,
                    needs_embedding=True,
                    needs_chunking=False,
                )
                return

            # בדיקה חוזרת ממש לפני הכתיבה. החלון בין הבדיקה הראשונה לכאן
            # הוא כל משך ההטמעה — דקות, בקצב של 1.2 שניות לצ'אנק. בזמן הזה
            # יכולה להישמר גרסה חדשה, והניקוי שלה כבר רץ ומחק את הצ'אנקים
            # של הישנה. בלי הבדיקה הזו היינו כותבים אותם מיד אחרי, וגרסה
            # שהוחלפה הייתה חוזרת ל-``$vectorSearch``.
            if not await is_latest_active_snippet(
                user_id, str(snippet.get("file_name") or ""), snippet_id
            ):
                await save_snippet_chunks(user_id=user_id, snippet_id=snippet_id, chunks=[])
                await _finish(content_hash=current_hash, chunk_count=0)
                logger.info(
                    "Snippet %s was superseded while embedding; chunks discarded",
                    snippet_id,
                )
                return

            await save_snippet_chunks(user_id=user_id, snippet_id=snippet_id, chunks=chunk_docs)

            metadata_text = create_embedding_text(
                code_chunk="",
                title=snippet.get("file_name"),
                description=snippet.get("description"),
                tags=snippet.get("tags", []),
                language=snippet.get("programming_language"),
            )
            snippet_embedding: Optional[List[float]] = None
            metadata_failure: Optional[str] = None
            if metadata_text.strip():
                try:
                    snippet_embedding, metadata_failure = await _embed_with_settings(metadata_text)
                except _RestartSnippetProcessing:
                    if attempt == 0:
                        logger.info(
                            "Snippet %s: 404 during metadata embed (attempt 0), restart",
                            snippet_id)
                        continue
                    logger.warning(
                        "Snippet %s: 404 during metadata embed (attempt 1), skipping",
                        snippet_id)
                    snippet_embedding = None
                if metadata_failure == FAILURE_QUOTA:
                    raise EmbeddingQuotaExhausted()
            # מטא-דאטה ריקה (קובץ בלי שם/תיאור/תגיות/שפה) אינה כשל: אין מה
            # להטמיע. עד כה היא נספרה ככשל והחזירה את הקובץ לתור בלי סוף.
            #
            # וגם 404 מתמשך על המטא-דאטה (אחרי ה-restart) אינו מחזיר את הקובץ
            # לתור, בכוונה. ``snippetEmbedding`` הוא **write-only**: הוא נכתב
            # ב-``update_snippet_embedding_status``, מוחרג מכל היטלה
            # (``_HEAVY_FIELDS_EXCLUDE_PROJECTION``, ``webapp/app.py``), ומנופה
            # ב-``mcp_server/backend.py`` — ואין בריפו אף קורא שלו. ה-
            # ``$vectorSearch`` היחיד רץ על ``chunkEmbedding``. לכן 404 כאן
            # (בפועל: שם מודל שגוי בקונפיג) לא פוגע בשום תוצאת חיפוש, ואילו
            # החזרה לתור הייתה יוצרת לולאה אינסופית על משהו חסר השפעה. הכשל
            # מדווח בלוג ובאירוע, ושם הוא נראה.

            # רק כשל **זמני** מחזיר את הקובץ לתור. צ'אנק שנדחה לצמיתות כבר
            # דווח באירוע משלו, וקובץ שלם לא ייתקע בגללו.
            should_retry = bool(transient_failures) or metadata_failure == FAILURE_TRANSIENT
            await _finish(
                content_hash=current_hash,
                chunk_count=len(chunk_docs),
                snippet_embedding=snippet_embedding,
                needs_embedding=should_retry,
                needs_chunking=False,
            )
            if permanent_failures or skipped_low_information:
                logger.info(
                    "Snippet %s: %s chunks stored, %s rejected permanently, %s skipped as low-information",
                    snippet_id, len(chunk_docs), permanent_failures, skipped_low_information,
                )
            break

        logger.info("Processed snippet %s: %s chunks", snippet_id, len(chunk_docs))


_worker: Optional[EmbeddingWorker] = None


def get_embedding_worker() -> EmbeddingWorker:
    global _worker
    if _worker is None:
        _worker = EmbeddingWorker()
    return _worker
