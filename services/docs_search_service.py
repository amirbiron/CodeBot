"""חיפוש בתיעוד: שאלה בשפה חופשית ← הסעיפים הקרובים אליה באינדקס של אתר התיעוד.

הקורא הוא ``POST /api/search/docs`` ב-``webapp/app.py`` (לאדמין). את האינדקס כותב
``services/docs_index_service.py``, והחוזה ביניהם — האוספים, השדות והאינדקס הווקטורי — ב-
``services/docs_search_contract.py``.

**השאלה מוטמעת במודל שהאינדקס נבנה בו** (``indexed_model_key`` במסמך המצב), ולא בהגדרות הפעילות.
אחרי החלפת מודל, עד שמעבר חדש מסיים, הנתחים שבמסד עדיין מהמודל הקודם, ושאלה במודל החדש הייתה
נמדדת מול וקטורים ממרחב אחר. הנתחים הוטמעו בלי ``taskType``, ולכן גם השאלה.

**אין חלופה שקטה** (``silent-fallback-to-worse-path``): כשאין אינדקס שאפשר לחפש בו, התשובה היא
``index_unavailable`` עם הסיבה — לא "אפס תוצאות", ולא חיפוש טקסט. מצב האינדקס ב-Atlas נבדק לפני
החיפוש, כך שלא שואלים אינדקס שחסר או שעוד לא נבנה.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import pymongo
from pymongo.errors import OperationFailure, PyMongoError, ServerSelectionTimeoutError

from services import docs_index_service as docs_index
from services import docs_search_contract as contract
from services.chunking_service import CHUNK_MAX_BYTES
from services.embedding_service import (
    EMBEDDING_DETAIL_DEADLINE_EXCEEDED,
    EMBEDDING_DETAIL_MISSING_API_KEY,
    SyncEmbeddingClient,
)
from services.semantic_embedding_settings import get_embedding_settings, make_embedding_key

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 5
MAX_LIMIT = 10

#: אורך השאלה, בבתים של UTF-8: אותו תקציב כמו נתח של התיעוד, שנמדד מתחת לתקרת הקלט של המודל
#: (``scripts/probe_embedding_limits.py``).
QUERY_MAX_BYTES = CHUNK_MAX_BYTES

#: הדדליין להטמעת השאלה, כולל ההמתנה בשער הקצב של התהליך (``services/embedding_service.py``).
QUERY_EMBED_DEADLINE_SECONDS = 10.0

#: התקרה על כל אחד משני חלקי העבודה מול המסד: לפני ההטמעה (מצב האינדקס) ואחריה (``$vectorSearch``
#: ושליפת הסעיפים). נאכפת בצד הלקוח ב-``pymongo.timeout``, כמו ב-``services/query_profiler_service.py``,
#: כי התיעוד של ``$vectorSearch`` לא אומר אם ``maxTimeMS`` חל עליו.
SEARCH_DB_TIMEOUT_SECONDS = 5.0

#: המכסה של הסבב הראשון: כמה נתחים לבקש לכל סעיף שמוחזר. סעיף ארוך מחולק לכמה נתחים, והנתחים
#: המובילים מתקבצים לעתים באותו סעיף; כשהם נופלים בפחות סעיפים ממה שהתבקש, ``_ranked_section_ids``
#: מכפיל את המכסה.
CHUNKS_PER_RESULT = 5

#: ההמלצה בתיעוד של ``$vectorSearch``: ``numCandidates`` פי 20 לפחות מ-``limit``
#: (https://www.mongodb.com/docs/atlas/atlas-vector-search/vector-search-stage/).
NUM_CANDIDATES_FACTOR = 20

#: התקרה של Atlas על ``numCandidates`` — "Value must be less than or equal to (``<=``) ``10000``" — ו-``limit``
#: "can't exceed the value of ``numCandidates``"
#: (https://www.mongodb.com/docs/vector-search/query/aggregation-stages/vector-search-stage/). לכן זו גם התקרה
#: על מכסת הנתחים. זה עותק שני, מוצהר, של ``SEMANTIC_NUM_CANDIDATES_HARD_MAX`` ב-``search_engine.py``, שנמדד
#: שם מול האשכול: ייבוא משם היה מושך את כל מנוע החיפוש של הסניפטים, עם המופע שהוא בונה ברמת המודול.
#: ``tests/test_docs_search_service.py`` משווה בין השניים.
MAX_NUM_CANDIDATES = 10_000

_SECTION_FIELDS = {
    "page_path": 1, "source_path": 1, "page_title": 1, "anchor": 1, "title": 1, "breadcrumb": 1, "markdown": 1,
}


class DocsSearchError(Exception):
    """כשל עם קוד יציב ל-API ולממשק. ``reason`` מפרט את ``index_unavailable``; ``detail`` הוא לאבחון."""

    def __init__(self, code: str, http_status: int, *, reason: str = "", detail: str = "") -> None:
        super().__init__(f"{code}:{reason}" if reason else code)
        self.code = code
        self.http_status = http_status
        self.reason = reason
        self.detail = detail

    def payload(self) -> Dict[str, Any]:
        body: Dict[str, Any] = {"ok": False, "error": self.code}
        if self.reason:
            body["reason"] = self.reason
        if self.detail:
            body["detail"] = self.detail
        return body


def _unavailable(reason: str, detail: str = "") -> DocsSearchError:
    return DocsSearchError("index_unavailable", 503, reason=reason, detail=detail)


def validated_query(query: object) -> str:
    """השאלה אחרי ``strip``, או ``DocsSearchError`` עם ``400``. האורך נמדד בבתים, כמו התקרה."""
    if not isinstance(query, str):
        raise DocsSearchError("invalid_query", 400)
    text = query.strip()
    if not text:
        raise DocsSearchError("empty_query", 400)
    try:
        size = len(text.encode("utf-8"))
    except UnicodeEncodeError as exc:  # surrogate בודד שהגיע ב-JSON — אין לו קידוד, וגם Gemini לא יקבל אותו
        raise DocsSearchError("invalid_query", 400) from exc
    if size > QUERY_MAX_BYTES:
        raise DocsSearchError("query_too_long", 400, detail=f"max {QUERY_MAX_BYTES} bytes")
    return text


def validated_limit(limit: object) -> int:
    """מספר הסעיפים להחזיר: מספר שלם בין 1 ל-:data:`MAX_LIMIT`, או ``DocsSearchError`` עם ``400``."""
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        raise DocsSearchError("invalid_limit", 400, detail=f"1..{MAX_LIMIT}")
    return limit


def _index_model(db: Any) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """מסמך המצב, והמודל שהאינדקס נבנה בו כפי שנתח שלו שומר אותו — מודל, גרסת API ומימד."""
    state = docs_index.read_state(db) or {}
    model_key = state.get("indexed_model_key")
    if not isinstance(model_key, str) or not model_key:
        raise _unavailable("not_indexed")
    chunk = db[contract.CHUNKS_COLLECTION].find_one(
        {contract.MODEL_KEY_FIELD: model_key},
        {"_id": 0, "embeddingModel": 1, "embeddingApiVersion": 1, "embeddingDim": 1},
    )
    if chunk is None:
        raise _unavailable("not_indexed", detail=f"no chunk with {model_key}")
    model, api_version, dimensions = (
        chunk.get("embeddingModel"), chunk.get("embeddingApiVersion"), chunk.get("embeddingDim")
    )
    if not (isinstance(model, str) and model and isinstance(api_version, str) and api_version
            and type(dimensions) is int and dimensions > 0):
        raise _unavailable("not_indexed", detail="the chunk does not name its model")
    return state, {"key": model_key, "model": model, "api_version": api_version, "dimensions": dimensions}


def _require_queryable_vector_index(db: Any, dimensions: int) -> None:
    """``index_unavailable`` אם האינדקס הווקטורי ב-Atlas חסר, לא שמיש, או נבנה למימד אחר."""
    report = docs_index.vector_index_status(db, dimensions)
    status = report.get("status")
    if status == "unknown":
        raise _unavailable("vector_search_unavailable")
    if status == "missing":
        raise _unavailable("vector_index_missing")
    if status == "error":
        raise _unavailable("vector_index_error", detail=str(report.get("detail") or ""))
    if report.get("queryable") is not True:
        raise _unavailable("vector_index_not_queryable", detail=str(status))
    if report.get("dimensions_match") is False:
        raise _unavailable(
            "vector_index_dimensions_mismatch", detail=f"index {report.get('dimensions')}, model {dimensions}"
        )


def _embed_query(
    text: str, model: Dict[str, Any], client_factory: Callable[[], Any], clock: Callable[[], float]
) -> List[float]:
    deadline = clock() + QUERY_EMBED_DEADLINE_SECONDS
    with client_factory() as client:
        vectors, status, detail = client.embed_batch(
            [text], model=model["model"], api_version=model["api_version"],
            dimensions=model["dimensions"], deadline=deadline,
        )
    if vectors:
        return vectors[0]
    if detail == EMBEDDING_DETAIL_MISSING_API_KEY:
        raise DocsSearchError("embedding_unavailable", 503, detail=detail)
    if detail == EMBEDDING_DETAIL_DEADLINE_EXCEEDED:
        raise DocsSearchError("embedding_timeout", 504)
    # התיאור של Gemini נרשם בלוג ולא חוזר ללקוח; השאלה עצמה לא נרשמת.
    logger.warning("docs search: embedding the query failed (status %s): %s", status, detail)
    if status == 429:
        raise DocsSearchError("embedding_quota", 429)
    raise DocsSearchError("embedding_failed", 502, detail=f"status {status}")


def _ranked_section_ids(db: Any, vector: List[float], model_key: str, limit: int) -> List[Tuple[str, float]]:
    """עד ``limit`` הסעיפים של הנתחים הקרובים לשאלה, עם הציון של הנתח הטוב בכל סעיף, מהגבוה לנמוך.

    ``$vectorSearch`` מחזיר נתחים, והתשובה היא סעיפים — וסעיף ארוך יכול למלא לבדו את מכסת הנתחים
    ולהשאיר פחות סעיפים מ-``limit``, גם כשבאינדקס יש עוד. לכן הסבב הראשון מבקש
    ``limit * CHUNKS_PER_RESULT`` נתחים, וכל עוד הם נופלים בפחות מ-``limit`` סעיפים והחיפוש מילא את המכסה,
    המכסה מוכפלת: עד שיש ``limit`` סעיפים, עד שהחיפוש מחזיר פחות נתחים ממה שביקשנו (אין עוד מועמדים), או
    עד ``MAX_NUM_CANDIDATES``. הסעיפים שנמצאים כך הם ה-``limit`` המובילים, בגבולות הקירוב של ANN: הנתח הטוב
    של סעיף שאין לו אף נתח בתוך המכסה נמוך מכל נתח שבתוכה. כל הסבבים רצים בתוך
    ``pymongo.timeout(SEARCH_DB_TIMEOUT_SECONDS)`` של ``search_docs``, שהוא דדליין אחד לבלוק כולו.
    """
    chunk_limit = min(limit * CHUNKS_PER_RESULT, MAX_NUM_CANDIDATES)
    while True:
        ranked, groups, chunks = _ranked_round(db, vector, model_key, limit, chunk_limit)
        # פחות מ-``limit`` קבוצות פירושו ש-``$limit`` לא חתך דבר, ולכן ``chunks`` הוא כל מה שהחיפוש החזיר.
        if groups >= limit or chunks < chunk_limit:
            return ranked
        if chunk_limit >= MAX_NUM_CANDIDATES:
            logger.warning(
                "docs search: %d chunks at the Atlas ceiling fell in %d sections, fewer than the %d asked",
                chunk_limit, groups, limit,
            )
            return ranked
        chunk_limit = min(chunk_limit * 2, MAX_NUM_CANDIDATES)


def _ranked_round(
    db: Any, vector: List[float], model_key: str, limit: int, chunk_limit: int
) -> Tuple[List[Tuple[str, float]], int, int]:
    """סבב אחד: ``chunk_limit`` הנתחים הקרובים, מקובצים לסעיפים. מחזיר את הסעיפים התקינים, כמה קבוצות חזרו,
    וכמה נתחים היו בהן.

    הווקטור והטקסט של הנתח לא יוצאים מהשלב הראשון: ``$project`` מיד אחריו (``mongodb.md``,
    "השדות הכבדים נגררים דרך המיון").
    """
    pipeline = [
        {
            "$vectorSearch": {
                "index": contract.VECTOR_INDEX_NAME,
                "path": contract.VECTOR_FIELD,
                "queryVector": vector,
                "numCandidates": min(chunk_limit * NUM_CANDIDATES_FACTOR, MAX_NUM_CANDIDATES),
                "limit": chunk_limit,
                "filter": {contract.MODEL_KEY_FIELD: model_key},
            }
        },
        {"$project": {"_id": 0, "section_id": 1, "score": {"$meta": "vectorSearchScore"}}},
        {"$group": {"_id": "$section_id", "score": {"$max": "$score"}, "chunks": {"$sum": 1}}},
        {"$sort": {"score": -1, "_id": 1}},
        {"$limit": limit},
    ]
    ranked: List[Tuple[str, float]] = []
    groups = chunks = 0
    for row in db[contract.CHUNKS_COLLECTION].aggregate(pipeline):
        groups += 1
        count = row.get("chunks")
        if isinstance(count, int) and not isinstance(count, bool):
            chunks += count
        section_id, score = row.get("_id"), row.get("score")
        if isinstance(section_id, str) and isinstance(score, (int, float)) and not isinstance(score, bool):
            ranked.append((section_id, float(score)))
    return ranked, groups, chunks


def _results(db: Any, ranked: List[Tuple[str, float]]) -> List[Dict[str, Any]]:
    """הסעיפים עצמם, בסדר של הציון. סעיף שנמחק בין שתי הקריאות (מעבר שרץ עכשיו) לא מוחזר."""
    ids = [section_id for section_id, _score in ranked]
    found = {
        doc["_id"]: doc
        for doc in db[contract.SECTIONS_COLLECTION].find({"_id": {"$in": ids}}, _SECTION_FIELDS)
    }
    results: List[Dict[str, Any]] = []
    for section_id, score in ranked:
        doc = found.get(section_id)
        if doc is None:
            continue
        try:
            url = contract.section_url(doc.get("page_path"), doc.get("anchor"))
        except ValueError:
            # המעבר בודק את שניהם לפני שהוא שומר — ערך כזה הגיע ממקור אחר, ואסור לו להיכנס לקישור.
            logger.warning("docs search: section %s has no valid page path or anchor; skipped", section_id)
            continue
        breadcrumb = doc.get("breadcrumb")
        results.append(
            {
                "section_id": section_id,
                "title": doc.get("title") if isinstance(doc.get("title"), str) else "",
                "breadcrumb": [part for part in breadcrumb if isinstance(part, str)]
                if isinstance(breadcrumb, list) else [],
                "page_title": doc.get("page_title") if isinstance(doc.get("page_title"), str) else "",
                "page_path": doc["page_path"],
                # קובץ המקור בריפו (``docs/webapp/search.rst``), שהכרטיס מציג. הוא נבדק מול
                # ``SOURCE_PATH_RE`` כשקובץ הייצוא של האתר נקרא, ונכנס לכרטיס כטקסט בלבד ולא לקישור.
                "source_path": doc.get("source_path") if isinstance(doc.get("source_path"), str) else "",
                "anchor": doc["anchor"],
                "url": url,
                "markdown": doc.get("markdown") if isinstance(doc.get("markdown"), str) else "",
                "score": round(score, 4),
            }
        )
    return results


def _ran_out_of_time(exc: PyMongoError) -> bool:
    """חריגת זמן של שאילתה. שרת שלא נמצא בכלל (``ServerSelectionTimeoutError``, גם הוא ``timeout``)
    הוא מסד שאינו זמין, ולא חיפוש איטי — הוא עולה לראוט, שמחזיר ``database_unavailable``."""
    return bool(exc.timeout) and not isinstance(exc, ServerSelectionTimeoutError)


def search_docs(
    db: Any,
    query: object,
    *,
    limit: object = DEFAULT_LIMIT,
    embed_client_factory: Optional[Callable[[], Any]] = None,
    clock: Callable[[], float] = time.monotonic,
) -> Dict[str, Any]:
    """הסעיפים הקרובים לשאלה, ומצב האינדקס שהם באו ממנו.

    ``DocsSearchError`` לכל כשל צפוי, עם קוד יציב. ``PyMongoError`` שאינו חריגת זמן עולה — הראוט
    מחזיר עליו ``database_unavailable``. בלי ``embed_client_factory`` — ``SyncEmbeddingClient``, כפי
    שהוא במודול בזמן הקריאה.
    """
    if embed_client_factory is None:
        embed_client_factory = SyncEmbeddingClient
    text = validated_query(query)
    count = validated_limit(limit)
    try:
        with pymongo.timeout(SEARCH_DB_TIMEOUT_SECONDS):
            state, model = _index_model(db)
            _require_queryable_vector_index(db, model["dimensions"])
            settings = get_embedding_settings(db)
    except PyMongoError as exc:
        if _ran_out_of_time(exc):
            raise DocsSearchError("search_timeout", 504) from exc
        raise

    vector = _embed_query(text, model, embed_client_factory, clock)

    try:
        with pymongo.timeout(SEARCH_DB_TIMEOUT_SECONDS):
            ranked = _ranked_section_ids(db, vector, model["key"], count)
            results = _results(db, ranked)
    except PyMongoError as exc:
        if _ran_out_of_time(exc):
            raise DocsSearchError("search_timeout", 504) from exc
        if isinstance(exc, OperationFailure):
            if exc.code == docs_index.SEARCH_NOT_ENABLED_CODE:
                raise _unavailable("vector_search_unavailable") from exc
            logger.warning("docs search: $vectorSearch was refused (code %s)", exc.code)
            raise DocsSearchError("search_failed", 502, detail=f"OperationFailure code {exc.code}") from exc
        raise

    settings_key = make_embedding_key(
        api_version=settings.api_version, model=settings.model, dimensions=int(settings.dimensions)
    )
    return {
        "results": results,
        "source_commit": state.get("indexed_source_commit"),
        "index_complete": docs_index.is_index_complete(state, settings_key),
    }
