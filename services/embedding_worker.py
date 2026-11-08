"""
Background worker for embedding processing.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from database.manager import (
    get_snippets_needing_processing,
    is_latest_active_snippet,
    save_snippet_chunks,
    update_snippet_embedding_status,
)
from services.embedding_service import (
    FAILURE_MODEL_MISSING,
    FAILURE_PERMANENT,
    FAILURE_QUOTA,
    FAILURE_TRANSIENT,
    FAILURE_UNKNOWN,
    classify_embedding_status,
    compute_content_hash,
    get_embedding_service,
    is_dimension_mismatch,
    oversized_input_detail,
    paced_batch_size,
    wait_for_throttle_gate,
)
from services.chunking_service import (
    CHUNKER_VERSION,
    CodeChunk,
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

# סוגי כשל בהטמעת צ'אנק בודד (``FAILURE_*``, מיובאים מ-``services/embedding_service.py``).
#
# ההבחנה הזו היא הליבה: עד כה **כל** כשל בצ'אנק אחד סימן את הקובץ כולו
# ב-``needs_embedding=True``, כלומר הוא נשלף שוב כל 300 שניות וכל הצ'אנקים
# שלו נשלחו מחדש — לנצח. כל עוד Gemini חתך בשקט זה כמעט לא קרה; ברגע
# שמפסיקים את החיתוך השקט, זה הופך למסלול הראשי.


def _classify_status(status: int) -> str:
    """ממפה קוד סטטוס לסוג כשל, כפי שה-worker פועל לפיו. **נקודת המיפוי היחידה בקובץ.**

    המיפוי עצמו הוא ``classify_embedding_status`` ב-``services/embedding_service.py``,
    המשותף לכל צרכני ההטמעה. מה שנקבע כאן הוא רק מה ה-worker עושה בסטטוס שאין לו
    משמעות מוגדרת שם (``FAILURE_UNKNOWN``): הוא מחזיר את הקובץ לתור, כמו בכשל זמני —
    כך הוא נהג בכל סטטוס כזה גם לפני שהמיפוי עבר, ולכן ההכרעה כתובה כאן במפורש ולא
    נשארת בענף ברירת מחדל.

    למה הכול במקום אחד ולא מפוזר: אותו נתיב (ניסיון חוזר אחרי 422) נשבר **פעמיים
    ברצף** בשתי דרכים שונות — קודם הסטטוס השני נזרק לגמרי, ואז הוא נשמר אבל
    404 בו טופל כזמני. שתי התקלות אפשריות רק כשהמיפוי חי בשני מקומות. כאן
    יש מקום אחד, ו-``_act_on_status`` הוא הפעולה היחידה שנגזרת ממנו.
    """
    failure = classify_embedding_status(status)
    if failure == FAILURE_UNKNOWN:
        return FAILURE_TRANSIENT
    return failure


class EmbeddingQuotaExhausted(Exception):
    """Gemini החזיר 429 גם אחרי מיצוי ה-retries. עוצרים את הבאץ'."""


class _RestartSnippetProcessing(Exception):
    """Internal signal: model/dim changed, restart snippet processing."""


@dataclass(frozen=True)
class _PendingChunk:
    """צ'אנק שממתין להטמעה: המקום שלו בקובץ, הצ'אנק עצמו, והטקסט שנשלח עליו.

    הטקסט והצ'אנק נוסעים יחד דרך האצוות והחציה, וכך הווקטור ה-i של אצווה מגיע תמיד לצ'אנק
    שהטקסט ה-i שלה נבנה ממנו.
    """

    position: int
    chunk: CodeChunk
    text: str


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
                # גבול הלולאה: כשל של קובץ אחד לא עוצר את האחרים, והקובץ נשאר עם הדגלים שלו
                # ונבחר שוב בסבב הבא. עם traceback, כי מאז 8.11.2026 הקריאה ל-Gemini כבר לא
                # עטופה ב-``except Exception`` שהפך כל חריגה לכשל זמני — באג מגיע לכאן.
                logger.error(
                    "Failed to process snippet %s: %s", snippet.get("_id"), exc, exc_info=True
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

        async def _embed_texts(
            texts: Sequence[str],
        ) -> Tuple[Optional[List[List[float]]], Optional[str]]:
            """קריאה אחת ל-``embed_batch``. מחזירה ``(וקטורים, None)``, או ``(None, failure_kind)``.

            ``failure_kind`` הוא אחד מ-``FAILURE_*``. הפרדת סוגי הכשל היא מה שמונע את הלולאה
            האינסופית: רק כשל זמני מחזיר את הקובץ לתור. 404 זורק ``_RestartSnippetProcessing``,
            כדי שהלולאה החיצונית תריץ self-heal ותרענן את ``settings``.

            **כל הצ'אנקים של קובץ באותן הגדרות.** המודל וגרסת ה-API קבועים לכל הניסיון
            (``settings``). המימד: אחרי 422 של מימד שונה מהמבוקש, האצווה נשלחת שוב בלי מימד
            קבוע, ומשם גם כל שאר האצוות של הקובץ (``request_dims``) — אבל רק כל עוד אף וקטור
            של הקובץ עוד לא התקבל. 422 אחרי וקטור ראשון, או וקטורים באורך אחר משלו, הם כשל זמני:
            שמירה שלהם הייתה מערבבת מימדים בתוך קובץ אחד, והקובץ חוזר לתור ומתחיל מההתחלה.
            """
            nonlocal effective_model, effective_api_version, effective_dim, effective_key
            nonlocal request_dims, established_dim
            model = str(getattr(settings, "model", "") or "")
            api_version = str(getattr(settings, "api_version", "") or "v1beta")

            vectors, status, body = await self.embedding_service.embed_batch(
                texts, model=model, api_version=api_version, dimensions=request_dims
            )
            if vectors is None and is_dimension_mismatch(status, body) and established_dim is None:
                logger.warning(
                    "Snippet %s: %s, retrying the batch and the rest of the file without a fixed dimension",
                    snippet_id, body,
                )
                request_dims = 0
                # הסטטוס של הניסיון השני עובר **בדיוק** את אותו טיפול כמו של הראשון —
                # כולל 404, שמפעיל self-heal ולא retry. מודל שנעלם בין שתי הקריאות היה
                # שולח את הקובץ לרטריי אינסופי במקום לתקן את ההגדרה.
                vectors, status, body = await self.embedding_service.embed_batch(
                    texts, model=model, api_version=api_version, dimensions=0
                )

            if vectors is not None:
                dims = {len(vector) for vector in vectors}
                expected = {established_dim} if established_dim is not None else dims
                if len(dims) != 1 or dims != expected:
                    logger.warning(
                        "Snippet %s: vectors of %s dimensions, expected %s; the file goes back to the queue",
                        snippet_id, sorted(dims), established_dim,
                    )
                    return None, FAILURE_TRANSIENT
                if established_dim is None:
                    established_dim = dims.pop()
                    effective_model = model
                    effective_api_version = api_version
                    effective_dim = established_dim
                    effective_key = make_embedding_key(
                        api_version=api_version, model=model, dimensions=established_dim
                    )
                return vectors, None

            if is_dimension_mismatch(status, body):
                logger.warning(
                    "Snippet %s: %s after the file already has %s-dimension vectors; "
                    "the file goes back to the queue",
                    snippet_id, body, established_dim,
                )
                return None, FAILURE_TRANSIENT
            return None, _act_on_status(int(status or 0))

        async def _finish(
            *,
            content_hash: str,
            chunk_count: int,
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

        # ההמתנה לשער קורית לפני הבדיקה שלמטה ולא בתוך הבקשה: אחרי אצווה גדולה של הקובץ הקודם
        # היא יכולה להיות עשרות שניות, ובתוך החלון שבין הבדיקה לכתיבה (ההערה ליד הבדיקה החוזרת)
        # היא רק הייתה מגדילה את הסיכוי שגרסה חדשה תישמר בינתיים.
        await wait_for_throttle_gate()

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
            # המימד שהאצוות של הקובץ מבקשות, והמימד שהווקטור הראשון שלו קיבל (``_embed_texts``).
            # מתאפסים בכל ניסיון, כי ניסיון אחרי restart מתחיל מהגדרות שרועננו.
            request_dims: int = int(getattr(settings, "dimensions", 0) or 768)
            established_dim: Optional[int] = None

            def _reject(chunk: CodeChunk) -> None:
                """צ'אנק שנדחה לצמיתות: נספר, ומדווח באירוע משלו. הקובץ לא נתקע בגללו."""
                nonlocal permanent_failures
                permanent_failures += 1
                emit_event(
                    "embedding_chunk_rejected",
                    severity="warn",
                    snippet_id=str(snippet_id),
                    chunk_index=int(chunk.index),
                    bytes=len(chunk.content.encode("utf-8")),
                )

            async def _embed_items(items: Sequence[_PendingChunk]) -> None:
                """מטמיע את ``items`` בקריאה אחת, ושומר וקטור לכל צ'אנק לפי הסדר.

                הספק דוחה אצווה שלמה בגלל פריט אחד (``EmbeddingService.embed_batch``), ולכן
                אחרי כשל קבוע (400) האצווה נחצית, וכל חצי נשלח לבד, עד שהצ'אנק שנדחה נשאר
                לבדו. שאר הצ'אנקים נשמרים. צ'אנק פסול אחד עולה בערך ``2·log2(n)`` בקשות
                נוספות; אצווה שכל הצ'אנקים שלה פסולים — עד ``2n - 1``. כל חציה נרשמת בלוג.
                """
                nonlocal transient_failures
                vectors, failure = await _embed_texts([item.text for item in items])
                if vectors is not None:
                    for item, vector in zip(items, vectors):
                        chunk_docs.append(
                            {
                                "chunkIndex": item.position,
                                "codeChunk": item.chunk.content,
                                "startLine": item.chunk.start_line,
                                "endLine": item.chunk.end_line,
                                "language": snippet.get("programming_language", "unknown"),
                                "chunkEmbedding": vector,
                                "embeddingModelKey": effective_key,
                                "embeddingModel": effective_model,
                                "embeddingApiVersion": effective_api_version,
                                "embeddingDim": effective_dim,
                            }
                        )
                    return
                if failure == FAILURE_QUOTA:
                    raise EmbeddingQuotaExhausted()
                if failure == FAILURE_PERMANENT:
                    if len(items) == 1:
                        _reject(items[0].chunk)
                        return
                    middle = len(items) // 2
                    logger.warning(
                        "Snippet %s: a batch of %s chunks was rejected, splitting it in two "
                        "to find the rejected chunk",
                        snippet_id, len(items),
                    )
                    await _embed_items(items[:middle])
                    await _embed_items(items[middle:])
                    return
                transient_failures += len(items)

            try:
                # ``chunkIndex`` ממוספר מחדש ברצף: הצינור בחיפוש מקבץ לפי
                # ``(snippetId, chunkIndex)``, וחורים במספור אינם מזיקים —
                # אבל מיפוי רציף שומר על ``chunkCount`` כמדד אמיתי.
                pending: List[_PendingChunk] = []
                for position, chunk in enumerate(chunks):
                    embedding_text = create_embedding_text(
                        code_chunk=chunk.content,
                        title=snippet.get("file_name"),
                        description=snippet.get("description"),
                        tags=snippet.get("tags", []),
                        language=snippet.get("programming_language"),
                    )
                    # טקסט ארוך מדי נדחה כאן, בלי לשלוח אותו: באצווה הוא היה מפיל את כולה.
                    if oversized_input_detail(embedding_text):
                        _reject(chunk)
                        continue
                    pending.append(_PendingChunk(position, chunk, embedding_text))

                # אצוות של ``paced_batch_size`` (ההסבר שם). השער מרחיק את הבקשה הבאה מרווח לכל
                # צ'אנק, ולכן הקצב הממוצע של צ'אנקים נשאר כמו כשכל צ'אנק היה בקשה.
                batch_size = paced_batch_size()
                for start in range(0, len(pending), batch_size):
                    await _embed_items(pending[start:start + batch_size])
            except _RestartSnippetProcessing:
                # Model disappeared mid-run: restart (once).
                if attempt == 0:
                    logger.info("Snippet %s: 404 during chunk processing (attempt 0), will restart", snippet_id)
                    continue
                # second failure: give up for now (leave needs_embedding True)
                logger.warning("Snippet %s: 404 during chunk processing (attempt 1), giving up", snippet_id)
                # צ'אנקים שנשארו מעיבוד קודם של הקובץ נמחקים, כדי שיתאימו ל-``chunk_count=0``
                # שנכתב מיד אחרי. עד 8.11.2026 ההערה כאן נימקה את המחיקה בצ'אנקים שנשמרו לפני
                # שהטמעת המטא-דאטה הפעילה restart; ההטמעה הזו הוסרה, ו-restart קורה עכשיו רק
                # בתוך לולאת הצ'אנקים, לפני ``save_snippet_chunks``.
                await save_snippet_chunks(user_id=user_id, snippet_id=snippet_id, chunks=[])
                await update_snippet_embedding_status(
                    snippet_id=snippet_id,
                    content_hash=current_hash,
                    chunk_count=0,
                    needs_embedding=True,
                    needs_chunking=False,
                )
                return

            # בדיקה חוזרת ממש לפני הכתיבה. החלון בין הבדיקה הראשונה לכאן הוא משך
            # ההטמעה: בקשה אחת לקובץ שנכנס באצווה אחת, וקובץ גדול יותר מחכה בין
            # האצוות שלו לשער (``paced_batch_size``). עד 8.11.2026 כל צ'אנק היה בקשה,
            # והחלון היה דקות. בזמן הזה יכולה להישמר גרסה חדשה, והניקוי שלה כבר רץ
            # ומחק את הצ'אנקים של הישנה. בלי הבדיקה הזו היינו כותבים אותם מיד אחרי,
            # וגרסה שהוחלפה הייתה חוזרת ל-``$vectorSearch``.
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

            # אין הטמעה של המטא-דאטה (שם, תיאור, תגיות ושפה בלי קוד). עד 8.11.2026 היא נשלחה
            # כבקשה נוספת אחרי הצ'אנקים ונשמרה ב-``snippetEmbedding``, ואף קוד בריפו לא קרא
            # את השדה: ה-``$vectorSearch`` היחיד על הקבצים רץ על ``chunkEmbedding``
            # (``_build_hybrid_search_pipeline`` ב-``search_engine.py``), והמטא-דאטה כבר
            # נכנסת לכל צ'אנק דרך ``create_embedding_text``. הבקשה עלתה קריאה ל-Gemini לכל
            # קובץ, וכשל זמני בה החזיר לתור קובץ שכל הצ'אנקים שלו כבר נשמרו. מסמכים שעובדו
            # לפני כן עדיין נושאים את השדה — ראו ``SNIPPET_SEMANTIC_FIELDS`` ב-
            # ``database/schemas.py``.

            # רק כשל **זמני** מחזיר את הקובץ לתור. צ'אנק שנדחה לצמיתות כבר
            # דווח באירוע משלו, וקובץ שלם לא ייתקע בגללו.
            should_retry = bool(transient_failures)
            await _finish(
                content_hash=current_hash,
                chunk_count=len(chunk_docs),
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
