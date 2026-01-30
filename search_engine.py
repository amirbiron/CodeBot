"""
מנוע חיפוש מתקדם לקטעי קוד
Advanced Search Engine for Code Snippets
"""

import asyncio
import logging
import math
import re
import hashlib
from itertools import islice
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, cast

try:
    # rapidfuzz מספק API דומה אך מהיר וללא קומפילציה
    from rapidfuzz import fuzz as _rf_fuzz, process as _rf_process
    fuzz = _rf_fuzz
    process = _rf_process
except Exception:  # pragma: no cover
    # נפילה שקטה ל-fuzzywuzzy אם rapidfuzz לא מותקן, לשמירה אחורה
    from fuzzywuzzy import fuzz as _fz_fuzz, process as _fz_process
    fuzz = _fz_fuzz
    process = _fz_process

from services import code_service as code_processor
from config import config
from database import db
from database.repository import HEAVY_FIELDS_EXCLUDE_PROJECTION
from services.embedding_service import get_embedding_service

logger = logging.getLogger(__name__)

# Structured events + metrics (safe fallbacks)
try:
    from observability import emit_event
except Exception:  # pragma: no cover
    def emit_event(event: str, severity: str = "info", **fields):
        return None

try:
    from metrics import track_performance, business_events_total
except Exception:  # pragma: no cover
    business_events_total = None
    from contextlib import contextmanager
    @contextmanager
    def track_performance(operation: str, labels=None):
        yield

try:
    from observability_instrumentation import traced, set_current_span_attributes
except Exception:  # pragma: no cover
    def traced(*_a, **_k):  # type: ignore
        def _inner(f):
            return f
        return _inner

    def set_current_span_attributes(*_a, **_k):  # type: ignore
        return None


def _hash_identifier(value: Any) -> str:
    try:
        text = str(value).strip()
    except Exception:
        return ""
    if not text:
        return ""
    try:
        return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()[:16]
    except Exception:
        return ""

class SearchType(Enum):
    """סוגי חיפוש"""
    TEXT = "text"
    REGEX = "regex"
    FUZZY = "fuzzy"
    SEMANTIC = "semantic"
    FUNCTION = "function"
    CONTENT = "content"

class SortOrder(Enum):
    """סדר מיון"""
    RELEVANCE = "relevance"
    DATE_DESC = "date_desc"
    DATE_ASC = "date_asc"
    NAME_ASC = "name_asc"
    NAME_DESC = "name_desc"
    SIZE_DESC = "size_desc"
    SIZE_ASC = "size_asc"

@dataclass
class SearchFilter:
    """מסנן חיפוש"""
    languages: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    min_size: Optional[int] = None
    max_size: Optional[int] = None
    has_functions: Optional[bool] = None
    has_classes: Optional[bool] = None
    file_pattern: Optional[str] = None

@dataclass
class SearchResult:
    """תוצאת חיפוש"""
    file_name: str
    content: str
    programming_language: str
    tags: List[str]
    created_at: datetime
    updated_at: datetime
    version: int
    relevance_score: float
    snippet_id: Optional[str] = None
    matches: List[Dict[str, Any]] = field(default_factory=list)
    snippet_preview: str = ""
    highlight_ranges: List[Tuple[int, int]] = field(default_factory=list)


# RRF (Reciprocal Rank Fusion) parameters
RRF_K = 60
TEXT_WEIGHT = 1.0
VECTOR_WEIGHT = 1.2

# RRF max score ≈ (1.2 + 1.0) / (60 + 1) ≈ 0.036
MIN_RRF_SCORE = 0.005


def _get_semantic_raw_db():
    try:
        raw_db = getattr(db, "db", None)
        if raw_db is not None:
            return raw_db
    except Exception:
        pass
    try:
        from services.db_provider import get_db as _get_db  # local import
        return _get_db()
    except Exception:
        return None


async def semantic_search(
    user_id: int,
    query: str,
    limit: int = 20,
    language_filter: Optional[str] = None,
    min_score: float = MIN_RRF_SCORE,
) -> List[SearchResult]:
    """
    Hybrid semantic search (Text + Vector).
    """
    if not query or not query.strip():
        return []
    if not getattr(config, "SEMANTIC_SEARCH_ENABLED", True):
        return await _fallback_text_search(user_id, query, limit, language_filter)

    embedding_service = get_embedding_service()
    if not embedding_service.is_available():
        logger.warning("Embedding service unavailable, falling back to text search")
        return await _fallback_text_search(user_id, query, limit, language_filter)

    query_embedding = await embedding_service.generate_embedding(query)
    if not query_embedding:
        logger.warning("Failed to generate query embedding, falling back to text search")
        return await _fallback_text_search(user_id, query, limit, language_filter)

    raw_db = _get_semantic_raw_db()
    if raw_db is None:
        logger.warning("Database unavailable, falling back to text search")
        return await _fallback_text_search(user_id, query, limit, language_filter)

    chunks_collection = getattr(raw_db, "snippet_chunks", None)
    if chunks_collection is None:
        logger.warning("snippet_chunks collection unavailable, falling back to text search")
        return await _fallback_text_search(user_id, query, limit, language_filter)

    pipeline = _build_hybrid_search_pipeline(
        user_id=user_id,
        query=query,
        query_embedding=query_embedding,
        limit=limit,
        language_filter=language_filter,
    )

    try:
        def _aggregate():
            return list(chunks_collection.aggregate(pipeline))

        raw_results = await asyncio.to_thread(_aggregate)
    except Exception as exc:
        logger.error("Hybrid search failed: %s", exc)
        return await _fallback_text_search(user_id, query, limit, language_filter)

    results = await _process_hybrid_results(raw_results, query, min_score, limit)
    return results


def _build_hybrid_search_pipeline(
    user_id: int,
    query: str,
    query_embedding: List[float],
    limit: int,
    language_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Build MongoDB aggregation pipeline for hybrid search.
    """
    num_candidates = limit * 20
    base_filter: Dict[str, Any] = {"userId": user_id}
    if language_filter:
        base_filter["language"] = language_filter

    pipeline: List[Dict[str, Any]] = [
        {
            "$vectorSearch": {
                "index": "vector_index",
                "path": "chunkEmbedding",
                "queryVector": query_embedding,
                "numCandidates": num_candidates,
                "limit": limit * 2,
                "filter": base_filter,
            }
        },
        {
            "$addFields": {
                "vectorScore": {"$meta": "vectorSearchScore"},
                "searchType": "vector",
            }
        },
        {
            "$unionWith": {
                "coll": "snippet_chunks",
                "pipeline": [
                    {
                        "$search": {
                            "index": "default",
                            "compound": {
                                "must": [
                                    {
                                        "text": {
                                            "query": query,
                                            "path": "codeChunk",
                                            "fuzzy": {"maxEdits": 1},
                                        }
                                    }
                                ],
                                "filter": [
                                    {
                                        "equals": {
                                            "path": "userId",
                                            "value": user_id,
                                        }
                                    }
                                ]
                                + (
                                    [
                                        {
                                            "equals": {
                                                "path": "language",
                                                "value": language_filter,
                                            }
                                        }
                                    ]
                                    if language_filter
                                    else []
                                ),
                            },
                        }
                    },
                    {
                        "$addFields": {
                            "textScore": {"$meta": "searchScore"},
                            "searchType": "text",
                        }
                    },
                    {"$limit": limit * 2},
                ],
            }
        },
        {
            "$group": {
                "_id": {"snippetId": "$snippetId", "chunkIndex": "$chunkIndex"},
                "snippetId": {"$first": "$snippetId"},
                "userId": {"$first": "$userId"},
                "language": {"$first": "$language"},
                "codeChunk": {"$first": "$codeChunk"},
                "startLine": {"$first": "$startLine"},
                "endLine": {"$first": "$endLine"},
                "chunkIndex": {"$first": "$chunkIndex"},
                "vectorScore": {"$max": "$vectorScore"},
                "textScore": {"$max": "$textScore"},
            }
        },
        {
            "$setWindowFields": {
                "sortBy": {"vectorScore": -1},
                "output": {"vectorRank": {"$rank": {}}},
            }
        },
        {
            "$setWindowFields": {
                "sortBy": {"textScore": -1},
                "output": {"textRank": {"$rank": {}}},
            }
        },
        {
            "$addFields": {
                "rrfScore": {
                    "$add": [
                        {
                            "$cond": {
                                "if": {"$gt": ["$vectorScore", 0]},
                                "then": {
                                    "$multiply": [
                                        VECTOR_WEIGHT,
                                        {"$divide": [1, {"$add": [RRF_K, "$vectorRank"]}]},
                                    ]
                                },
                                "else": 0,
                            }
                        },
                        {
                            "$cond": {
                                "if": {"$gt": ["$textScore", 0]},
                                "then": {
                                    "$multiply": [
                                        TEXT_WEIGHT,
                                        {"$divide": [1, {"$add": [RRF_K, "$textRank"]}]},
                                    ]
                                },
                                "else": 0,
                            }
                        },
                    ]
                }
            }
        },
        {"$sort": {"rrfScore": -1}},
        {"$limit": limit},
        {
            "$lookup": {
                "from": "code_snippets",
                "let": {"snippet_id": "$snippetId"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {"$eq": ["$_id", "$$snippet_id"]},
                            "is_active": True,
                        }
                    },
                    {"$project": dict(HEAVY_FIELDS_EXCLUDE_PROJECTION)},
                ],
                "as": "snippetDetails",
            }
        },
        {
            "$unwind": {
                "path": "$snippetDetails",
                "preserveNullAndEmptyArrays": True,
            }
        },
        {"$match": {"snippetDetails": {"$ne": None}}},
        {
            "$lookup": {
                "from": "code_snippets",
                "let": {
                    "file_name": "$snippetDetails.file_name",
                    "user_id": "$snippetDetails.user_id",
                },
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$file_name", "$$file_name"]},
                                    {"$eq": ["$user_id", "$$user_id"]},
                                    {"$eq": ["$is_active", True]},
                                ]
                            }
                        }
                    },
                    {"$sort": {"version": -1, "updated_at": -1, "_id": -1}},
                    {"$limit": 1},
                    {"$project": {"_id": 1}},
                ],
                "as": "latestSnippet",
            }
        },
        {
            "$addFields": {
                "latestSnippetId": {"$arrayElemAt": ["$latestSnippet._id", 0]}
            }
        },
        {"$match": {"$expr": {"$eq": ["$snippetId", "$latestSnippetId"]}}},
        {
            "$project": {
                "snippetId": 1,
                "userId": 1,
                "language": 1,
                "codeChunk": 1,
                "startLine": 1,
                "endLine": 1,
                "chunkIndex": 1,
                "rrfScore": 1,
                "vectorScore": 1,
                "textScore": 1,
                "fileId": "$snippetDetails._id",
                "fileName": "$snippetDetails.file_name",
                "title": "$snippetDetails.file_name",
                "description": "$snippetDetails.description",
                "tags": "$snippetDetails.tags",
                "createdAt": "$snippetDetails.created_at",
                "updatedAt": "$snippetDetails.updated_at",
            }
        },
    ]

    return pipeline


async def _process_hybrid_results(
    raw_results: List[Dict[str, Any]],
    query: str,
    min_score: float,
    limit: int,
) -> List[SearchResult]:
    """
    Convert raw results into SearchResult objects.
    """
    results: List[SearchResult] = []
    seen_snippets: set = set()

    for doc in raw_results:
        snippet_id = str(doc.get("snippetId", ""))
        if snippet_id in seen_snippets:
            continue
        seen_snippets.add(snippet_id)

        score = doc.get("rrfScore", 0)
        if score < min_score:
            continue

        preview = _create_context_preview(
            code_chunk=doc.get("codeChunk", ""),
            query=query,
            context_lines=10,
        )

        results.append(
            SearchResult(
                file_name=doc.get("fileName", "unknown"),
                content="",
                programming_language=doc.get("language", "unknown"),
                tags=doc.get("tags", []) or [],
                created_at=doc.get("createdAt", datetime.now(timezone.utc)),
                updated_at=doc.get("updatedAt", datetime.now(timezone.utc)),
                version=1,
                relevance_score=score,
                snippet_id=snippet_id or None,
                snippet_preview=preview,
                matches=[
                    {
                        "startLine": doc.get("startLine", 1),
                        "endLine": doc.get("endLine", 1),
                        "chunkIndex": doc.get("chunkIndex", 0),
                    }
                ],
            )
        )

        if len(results) >= limit:
            break

    return results


def _create_context_preview(
    code_chunk: str,
    query: str,
    context_lines: int = 10,
) -> str:
    """
    Build a preview with context around query terms.
    """
    if not code_chunk:
        return ""
    lines = code_chunk.splitlines()
    query_terms = query.lower().split()

    best_line_idx = 0
    best_match_count = 0
    for idx, line in enumerate(lines):
        line_lower = line.lower()
        match_count = sum(1 for term in query_terms if term in line_lower)
        if match_count > best_match_count:
            best_match_count = match_count
            best_line_idx = idx

    start = max(0, best_line_idx - context_lines)
    end = min(len(lines), best_line_idx + context_lines + 1)
    return "\n".join(lines[start:end])


async def _fallback_text_search(
    user_id: int,
    query: str,
    limit: int,
    language_filter: Optional[str],
) -> List[SearchResult]:
    """
    Fallback to regular text search when semantic search isn't available.
    """
    def _run():
        return search_engine.search(
            user_id=user_id,
            query=query,
            search_type=SearchType.FUZZY,
            limit=limit,
            filters=SearchFilter(languages=[language_filter] if language_filter else []),
        )

    return await asyncio.to_thread(_run)

class SearchIndex:
    """אינדקס חיפוש לביצועים טובים יותר"""
    
    def __init__(self):
        self.word_index: Dict[str, Set[str]] = defaultdict(set)  # מילה -> קבצים
        self.function_index: Dict[str, Set[str]] = defaultdict(set)  # פונקציה -> קבצים
        self.language_index: Dict[str, Set[str]] = defaultdict(set)  # שפה -> קבצים
        self.tag_index: Dict[str, Set[str]] = defaultdict(set)  # תגית -> קבצים
        self.last_update = datetime.min.replace(tzinfo=timezone.utc)
        
    @traced("search.index.rebuild")
    def rebuild_index(self, user_id: int):
        """בניית האינדקס מחדש"""
        try:
            emit_event("search_index_rebuild_start", severity="info", user_id=int(user_id))
        except Exception:
            pass
        try:
            hashed = _hash_identifier(user_id)
            if hashed:
                set_current_span_attributes({"user_id_hash": hashed})
        except Exception:
            pass
        
        logger.info(f"בונה אינדקס חיפוש עבור משתמש {user_id}")
        
        # ניקוי אינדקס קיים
        self.word_index.clear()
        self.function_index.clear()
        self.language_index.clear()
        self.tag_index.clear()
        
        # קבלת כל הקבצים
        with track_performance("search_index_rebuild", labels={"repo": ""}):
            # עימוד בטוח: שליפה במנות קונפיגורביליות (ברירת מחדל 200)
            PAGE_SIZE = int(getattr(config, "SEARCH_PAGE_SIZE", 200))
            offset = 0
            while True:
                try:
                    # אינדוקס דורש את התוכן עצמו, לכן מבקשים code במפורש (include projection)
                    files = db.get_user_files(
                        user_id,
                        limit=PAGE_SIZE,
                        skip=offset,
                        projection={"file_name": 1, "programming_language": 1, "tags": 1, "code": 1},
                    )
                except TypeError:
                    # תאימות ל-stubs שלא תומכים ב-skip — קח רק עמוד ראשון ללא דילוג
                    try:
                        files = db.get_user_files(
                            user_id,
                            PAGE_SIZE,
                            projection={"file_name": 1, "programming_language": 1, "tags": 1, "code": 1},
                        )
                    except TypeError:
                        # תאימות כפולה:
                        # 1) יש stubs שלא תומכים ב-projection
                        # 2) יש מימושים ישנים שלא תומכים ב-skip אבל כן תומכים ב-projection
                        try:
                            files = db.get_user_files(
                                user_id,
                                PAGE_SIZE,
                                projection={"file_name": 1, "programming_language": 1, "tags": 1, "code": 1},
                            )
                        except TypeError:
                            files = db.get_user_files(user_id, PAGE_SIZE)
                    # אם כבר עשינו ניסיון ראשון והגענו לכאן, עצור
                    if offset > 0:
                        files = []
                if not files:
                    break
                offset += len(files)
                for file_data in files:
                    # גישה בטוחה לשדות שעלולים להיות חסרים במסמכים ישנים/חלקיים
                    file_name_value = str(file_data.get('file_name') or '').strip()
                    if not file_name_value:
                        # אין טעם לאנדקס רשומה ללא שם קובץ
                        continue

                    file_key = f"{user_id}:{file_name_value}"

                    code_text: str = str(file_data.get('code') or '')
                    content_lower = code_text.lower()

                    # אינדקס מילים
                    words = re.findall(r'\b\w+\b', content_lower)
                    for word in set(words):
                        if len(word) >= 2:
                            self.word_index[word].add(file_key)

                    # אינדקס פונקציות (best-effort)
                    try:
                        language_for_parse = str(file_data.get('programming_language') or '').strip()
                        functions = code_processor.extract_functions(code_text, language_for_parse)
                        for func in functions:
                            func_name = str(func.get('name') or '').lower()
                            if func_name:
                                self.function_index[func_name].add(file_key)
                    except Exception:
                        # אל נעצור אינדוקס בגלל שגיאה בזיהוי פונקציות
                        pass

                    # אינדקס שפות
                    language_value = str(file_data.get('programming_language') or '').strip()
                    if language_value:
                        self.language_index[language_value].add(file_key)

                    # אינדקס תגיות
                    try:
                        for tag in list(file_data.get('tags') or []):
                            tag_value = str(tag or '').lower().strip()
                            if tag_value:
                                self.tag_index[tag_value].add(file_key)
                    except Exception:
                        pass
        
        self.last_update = datetime.now(timezone.utc)
        logger.info(f"אינדקס נבנה: {len(self.word_index)} מילים, {len(self.function_index)} פונקציות")
        try:
            emit_event(
                "search_index_rebuild_done",
                severity="info",
                user_id=int(user_id),
                words=int(len(self.word_index)),
                functions=int(len(self.function_index)),
            )
        except Exception:
            pass
        try:
            set_current_span_attributes({
                "words_indexed": int(len(self.word_index)),
                "functions_indexed": int(len(self.function_index)),
            })
        except Exception:
            pass
    
    def should_rebuild(self, max_age_minutes: int = 30) -> bool:
        """בדיקה אם צריך לבנות אינדקס מחדש"""
        age = datetime.now(timezone.utc) - self.last_update
        return age.total_seconds() > (max_age_minutes * 60)

class AdvancedSearchEngine:
    """מנוע חיפוש מתקדם"""
    
    def __init__(self):
        self.indexes: Dict[int, SearchIndex] = {}
        self.stop_words = {
            'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been',
            'את', 'של', 'על', 'עם', 'אל', 'מן', 'כמו', 'לא', 'לו', 'היא', 'הוא'
        }
    
    def get_index(self, user_id: int) -> SearchIndex:
        """קבלת אינדקס למשתמש"""
        
        if user_id not in self.indexes:
            self.indexes[user_id] = SearchIndex()
        
        index = self.indexes[user_id]
        if index.should_rebuild():
            index.rebuild_index(user_id)
        
        return index
    
    @traced("search_engine.search")
    def search(self, user_id: int, query: str, search_type: SearchType = SearchType.TEXT,
               filters: Optional[SearchFilter] = None, sort_order: SortOrder = SortOrder.RELEVANCE,
               limit: int = 50) -> List[SearchResult]:
        """חיפוש מתקדם"""
        
        try:
            user_hash = _hash_identifier(user_id)
            attrs = {
                "query.length": int(len(query or "")),
                "search.type": str(search_type.value if isinstance(search_type, SearchType) else search_type),
                "limit": int(limit),
            }
            if user_hash:
                attrs["user_id_hash"] = user_hash
            if filters:
                attrs["filters.applied"] = True
            set_current_span_attributes(attrs)
        except Exception:
            pass

        try:
            try:
                emit_event(
                    "search_request",
                    severity="info",
                    user_id=int(user_id),
                    query_length=int(len(query or "")),
                    type=str(search_type.value if isinstance(search_type, SearchType) else search_type),
                )
            except Exception:
                pass
            if not query.strip():
                try:
                    set_current_span_attributes({"results_count": 0})
                except Exception:
                    pass
                return []
            
            # קבלת האינדקס
            with track_performance("search_index_get", labels={"repo": ""}):
                index = self.get_index(user_id)
            
            # ביצוע החיפוש לפי סוג
            with track_performance("search_execute", labels={"repo": ""}):
                if search_type == SearchType.TEXT:
                    candidates = self._text_search(query, index, user_id)
                elif search_type == SearchType.REGEX:
                    candidates = self._regex_search(query, user_id)
                elif search_type == SearchType.FUZZY:
                    candidates = self._fuzzy_search(query, index, user_id)
                elif search_type == SearchType.FUNCTION:
                    candidates = self._function_search(query, index, user_id)
                elif search_type == SearchType.CONTENT:
                    candidates = self._content_search(query, user_id)
                else:
                    candidates = self._text_search(query, index, user_id)
            
            # החלת מסננים
            if filters:
                with track_performance("search_filter", labels={"repo": ""}):
                    candidates = self._apply_filters(candidates, filters)
            
            # מיון
            with track_performance("search_sort", labels={"repo": ""}):
                candidates = self._sort_results(candidates, sort_order)
            
            # הגבלת תוצאות
            results = candidates[:limit]
            try:
                emit_event(
                    "search_done",
                    severity="info",
                    user_id=int(user_id),
                    results_count=int(len(results)),
                )
                if business_events_total is not None:
                    business_events_total.labels(metric="search").inc()
            except Exception:
                pass
            try:
                set_current_span_attributes({"results_count": int(len(results))})
            except Exception:
                pass
            return results
            
        except Exception as e:
            logger.error(f"שגיאה בחיפוש: {e}")
            try:
                set_current_span_attributes({"status": "error", "error_signature": type(e).__name__})
            except Exception:
                pass
            try:
                emit_event("search_error", severity="error", error=str(e))
            except Exception:
                pass
            return []
    
    def _text_search(self, query: str, index: SearchIndex, user_id: int) -> List[SearchResult]:
        """חיפוש טקסט רגיל"""
        
        # ניתוח השאילתה
        query_words = [word.lower() for word in re.findall(r'\b\w+\b', query)
                      if word.lower() not in self.stop_words and len(word) >= 2]
        
        if not query_words:
            return []
        
        # מציאת קבצים מתאימים
        file_scores: Dict[str, float] = defaultdict(float)
        
        for word in query_words:
            matching_files = index.word_index.get(word, set())
            
            # חיפוש חלקי (prefix matching)
            for indexed_word, files in index.word_index.items():
                if indexed_word.startswith(word) or word in indexed_word:
                    matching_files.update(files)
            
            # הוספת ניקוד
            for file_key in matching_files:
                if word in index.word_index and file_key in index.word_index[word]:
                    file_scores[file_key] += 2.0  # התאמה מדויקת
                else:
                    file_scores[file_key] += 1.0  # התאמה חלקית
        
        # יצירת תוצאות
        results = []
        for file_key, score in file_scores.items():
            if score > 0:
                user_id_str, file_name = file_key.split(':', 1)
                if int(user_id_str) == user_id:
                    file_data = db.get_latest_version(user_id, file_name)
                    if file_data:
                        result = self._create_search_result(file_data, query, score)
                        results.append(result)
        
        return results
    
    def _regex_search(self, pattern: str, user_id: int) -> List[SearchResult]:
        """חיפוש עם ביטויים רגולריים"""
        
        try:
            compiled_pattern = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
        except re.error as e:
            logger.error(f"דפוס regex לא תקין: {e}")
            return []
        
        # הקרנה קלה לתוכן ושדות נחוצים בלבד
        PAGE_SIZE = int(getattr(config, "SEARCH_PAGE_SIZE", 200))
        offset = 0
        results = []
        while True:
            try:
                files = db.get_user_files(
                    user_id,
                    limit=PAGE_SIZE,
                    skip=offset,
                    projection={"file_name": 1, "code": 1, "tags": 1, "programming_language": 1, "updated_at": 1},
                )
            except TypeError:
                # נסה לשמר code גם בנתיב תאימות (מימוש ישן בלי skip אבל עם projection)
                try:
                    files = db.get_user_files(
                        user_id,
                        PAGE_SIZE,
                        projection={"file_name": 1, "code": 1, "tags": 1, "programming_language": 1, "updated_at": 1},
                    )
                except TypeError:
                    files = db.get_user_files(user_id, PAGE_SIZE)
                if offset > 0:
                    files = []
            if not files:
                break
            offset += len(files)
            for file_data in files:
                content = str(file_data.get('code') or '')
                matches = list(compiled_pattern.finditer(content))
                
                if matches:
                    score = len(matches)
                    result = self._create_search_result(file_data, pattern, score)
                    
                    # הוספת מידע על ההתאמות
                    result.matches = [
                        {
                            "start": match.start(),
                            "end": match.end(),
                            "text": match.group(),
                            "line": content[:match.start()].count('\n') + 1
                        }
                        for match in matches[:10]  # מקסימום 10 התאמות
                    ]
                    
                    results.append(result)
        
        return results
    
    def _fuzzy_search(self, query: str, index: SearchIndex, user_id: int) -> List[SearchResult]:
        """חיפוש מטושטש (fuzzy)"""
        
        PAGE_SIZE = int(getattr(config, "SEARCH_PAGE_SIZE", 200))
        offset = 0
        results = []
        while True:
            try:
                files = db.get_user_files(
                    user_id,
                    limit=PAGE_SIZE,
                    skip=offset,
                    projection={"file_name": 1, "code": 1, "tags": 1, "programming_language": 1, "updated_at": 1},
                )
            except TypeError:
                try:
                    files = db.get_user_files(
                        user_id,
                        PAGE_SIZE,
                        projection={"file_name": 1, "code": 1, "tags": 1, "programming_language": 1, "updated_at": 1},
                    )
                except TypeError:
                    files = db.get_user_files(user_id, PAGE_SIZE)
                if offset > 0:
                    files = []
            if not files:
                break
            offset += len(files)
            for file_data in files:
                # חיפוש מטושטש בשם הקובץ
                name_value = str(file_data.get('file_name') or '')
                name_ratio = fuzz.partial_ratio(query.lower(), name_value.lower())
                
                # חיפוש מטושטש בתוכן
                content_value = str(file_data.get('code') or '')
                content_ratio = fuzz.partial_ratio(query.lower(), content_value.lower())
                
                # חיפוש מטושטש בתגיות
                try:
                    tags_list = [str(t or '') for t in (file_data.get('tags') or [])]
                except Exception:
                    tags_list = []
                tags_text = ' '.join(tags_list)
                tags_ratio = fuzz.partial_ratio(query.lower(), tags_text.lower())
                
                # ניקוד משולב
                max_ratio = max(name_ratio, content_ratio, tags_ratio)
                
                if max_ratio >= 60:  # סף מינימלי
                    score = max_ratio / 100.0
                    result = self._create_search_result(file_data, query, score)
                    results.append(result)
        
        return results
    
    def _function_search(self, query: str, index: SearchIndex, user_id: int) -> List[SearchResult]:
        """חיפוש פונקציות"""
        
        query_lower = query.lower()
        file_scores: Dict[str, float] = defaultdict(float)
        
        # חיפוש בשמות פונקציות
        for func_name, files in index.function_index.items():
            if query_lower in func_name:
                similarity = fuzz.ratio(query_lower, func_name) / 100.0
                for file_key in files:
                    file_scores[file_key] += similarity * 2.0
        
        # יצירת תוצאות
        results = []
        for file_key, score in file_scores.items():
            if score > 0:
                user_id_str, file_name = file_key.split(':', 1)
                if int(user_id_str) == user_id:
                    file_data = db.get_latest_version(user_id, file_name)
                    if file_data:
                        result = self._create_search_result(file_data, query, score)
                        results.append(result)
        
        return results
    
    def _content_search(self, query: str, user_id: int) -> List[SearchResult]:
        """חיפוש מלא בתוכן"""
        
        PAGE_SIZE = int(getattr(config, "SEARCH_PAGE_SIZE", 200))
        offset = 0
        results = []
        query_lower = query.lower()
        while True:
            try:
                files = db.get_user_files(
                    user_id,
                    limit=PAGE_SIZE,
                    skip=offset,
                    projection={"file_name": 1, "code": 1, "tags": 1, "programming_language": 1, "updated_at": 1},
                )
            except TypeError:
                try:
                    files = db.get_user_files(
                        user_id,
                        PAGE_SIZE,
                        projection={"file_name": 1, "code": 1, "tags": 1, "programming_language": 1, "updated_at": 1},
                    )
                except TypeError:
                    files = db.get_user_files(user_id, PAGE_SIZE)
                if offset > 0:
                    files = []
            if not files:
                break
            offset += len(files)
            for file_data in files:
                content_value = str(file_data.get('code') or '')
                content_lower = content_value.lower()
                
                # ספירת הופעות
                occurrences = content_lower.count(query_lower)
                
                if occurrences > 0:
                    # חישוב ניקוד לפי תדירות ואורך המסמך
                    denom = max(1, len(content_value))
                    score = min(occurrences / (denom / 1000), 10.0)
                    
                    result = self._create_search_result(file_data, query, score)
                    
                    # יצירת קטע תצוגה מקדימה
                    preview_start = content_lower.find(query_lower)
                    if preview_start >= 0:
                        start = max(0, preview_start - 50)
                        end = min(len(content_value), preview_start + len(query) + 50)
                        result.snippet_preview = content_value[start:end]
                        
                        # סימון המילה שנמצאה
                        relative_start = preview_start - start
                        relative_end = relative_start + len(query)
                        result.highlight_ranges = [(relative_start, relative_end)]
                    
                    results.append(result)
        
        return results
    
    def _apply_filters(self, results: List[SearchResult], filters: SearchFilter) -> List[SearchResult]:
        """החלת מסננים על התוצאות"""
        
        filtered = []
        
        for result in results:
            # מסנן שפות
            if filters.languages and result.programming_language not in filters.languages:
                continue
            
            # מסנן תגיות
            if filters.tags:
                if not any(tag in result.tags for tag in filters.tags):
                    continue
            
            # מסנן תאריך
            if filters.date_from and result.updated_at < filters.date_from:
                continue
            
            if filters.date_to and result.updated_at > filters.date_to:
                continue
            
            # מסנן גודל
            content_size = len(result.content)
            
            if filters.min_size and content_size < filters.min_size:
                continue
            
            if filters.max_size and content_size > filters.max_size:
                continue
            
            # מסנן פונקציות
            if filters.has_functions is not None:
                functions = code_processor.extract_functions(result.content, result.programming_language)
                has_functions = len(functions) > 0
                
                if filters.has_functions != has_functions:
                    continue
            
            # מסנן מחלקות
            if filters.has_classes is not None:
                has_classes = 'class ' in result.content.lower()
                
                if filters.has_classes != has_classes:
                    continue
            
            # מסנן דפוס שם קובץ
            if filters.file_pattern:
                if not re.search(filters.file_pattern, result.file_name, re.IGNORECASE):
                    continue
            
            filtered.append(result)
        
        return filtered
    
    def _sort_results(self, results: List[SearchResult], sort_order: SortOrder) -> List[SearchResult]:
        """מיון התוצאות"""
        
        if sort_order == SortOrder.RELEVANCE:
            return sorted(results, key=lambda x: x.relevance_score, reverse=True)
        
        elif sort_order == SortOrder.DATE_DESC:
            return sorted(results, key=lambda x: x.updated_at, reverse=True)
        
        elif sort_order == SortOrder.DATE_ASC:
            return sorted(results, key=lambda x: x.updated_at)
        
        elif sort_order == SortOrder.NAME_ASC:
            return sorted(results, key=lambda x: x.file_name.lower())
        
        elif sort_order == SortOrder.NAME_DESC:
            return sorted(results, key=lambda x: x.file_name.lower(), reverse=True)
        
        elif sort_order == SortOrder.SIZE_DESC:
            return sorted(results, key=lambda x: len(x.content), reverse=True)
        
        elif sort_order == SortOrder.SIZE_ASC:
            return sorted(results, key=lambda x: len(x.content))
        else:
            return results
    
    def _create_search_result(self, file_data: Dict, query: str, score: float) -> SearchResult:
        """יצירת אובייקט תוצאת חיפוש"""
        
        # נרמול בטוח של שדות בעייתיים
        raw_tags = file_data.get('tags')
        safe_tags = list(raw_tags or [])

        raw_version = file_data.get('version')
        try:
            if isinstance(raw_version, bool):  # הגן מפני True/False שמתקבלים ממונגו לעתים
                safe_version = 1
            elif isinstance(raw_version, (int, float)):
                safe_version = int(raw_version)
            elif isinstance(raw_version, str):
                v = raw_version.strip()
                if v.isdigit():
                    safe_version = int(v)
                else:
                    # נסיון lenient: המרת מחרוזת מספרית לא שלמה (למשל "1.0")
                    safe_version = int(float(v))
            else:
                safe_version = 1
        except Exception:
            safe_version = 1

        # חילוץ snippet_id מה-ObjectId של המסמך
        raw_id = file_data.get('_id')
        snippet_id_str = str(raw_id) if raw_id else None

        # יצירת preview עם הקשר מסביב לquery terms
        code_content = str(file_data.get('code') or '')
        snippet_preview = _create_context_preview(code_content, query, context_lines=10)

        return SearchResult(
            file_name=str(file_data.get('file_name') or ''),
            content=code_content,
            programming_language=str(file_data.get('programming_language') or ''),
            tags=safe_tags,
            created_at=file_data.get('created_at') or datetime.now(timezone.utc),
            updated_at=file_data.get('updated_at') or datetime.now(timezone.utc),
            version=safe_version,
            relevance_score=float(score),
            snippet_id=snippet_id_str,
            snippet_preview=snippet_preview,
        )

    def _split_query_terms(self, query: str) -> Tuple[List[str], str]:
        """פיצול שאילתה למילים מלאות ול-prefix אחרון."""
        q = str(query or "")
        tokens = [t for t in re.findall(r"\b\w+\b", q.lower()) if t]
        if not tokens:
            return [], ""
        ends_with_word = bool(re.search(r"\w$", q))
        if ends_with_word:
            return tokens[:-1], tokens[-1]
        return tokens, ""

    def _add_suggestions_from_row(self, suggestions: Set[str], row: Dict[str, Any], prefix: str) -> None:
        if not prefix:
            return
        name = str(row.get("file_name") or "").strip()
        if name and name.lower().startswith(prefix):
            suggestions.add(name)
        lang = str(row.get("programming_language") or "").strip()
        if lang and lang.lower().startswith(prefix):
            suggestions.add(lang)
        try:
            for tag in list(row.get("tags") or []):
                tag_value = str(tag or "").strip()
                if tag_value and tag_value.lower().startswith(prefix):
                    suggestions.add(f"#{tag_value}")
        except Exception:
            pass
        desc = str(row.get("description") or "").strip()
        if desc:
            for token in re.findall(r"\b\w+\b", desc.lower()):
                if token.startswith(prefix):
                    suggestions.add(token)

    def _get_ready_index(self, user_id: int, max_age_minutes: int = 120) -> Optional[SearchIndex]:
        """מחזיר אינדקס אם כבר נבנה והוא טרי מספיק (ללא rebuild כבד)."""
        try:
            index = self.indexes.get(user_id)
        except Exception:
            return None
        if index is None:
            return None
        try:
            if index.should_rebuild(max_age_minutes=max_age_minutes):
                return None
        except Exception:
            return None
        return index
    
    def _suggest_from_text_search(
        self,
        user_id: int,
        completed_terms: List[str],
        prefix: str,
        limit: int = 10
    ) -> List[str]:
        """הצעות השלמה על בסיס $text לתנאים עם מילים מלאות."""
        if not completed_terms or not prefix:
            return []
        query_text = " ".join([t for t in completed_terms if t])
        if not query_text:
            return []
        try:
            candidate_limit = min(max(int(limit or 10) * 5, 20), 100)
        except Exception:
            candidate_limit = 20
        suggestions: Set[str] = set()

        # code_snippets דרך search_code ($text)
        try:
            search_code = getattr(db, "search_code", None)
            if callable(search_code):
                rows = search_code(user_id, query_text, limit=candidate_limit)
                for row in rows or []:
                    if isinstance(row, dict):
                        self._add_suggestions_from_row(suggestions, row, prefix)
        except Exception:
            pass

        # large_files ($text) - ללא שימוש ב-Regex
        try:
            coll = getattr(db, "large_files_collection", None)
            if coll is not None:
                match = {"user_id": user_id, "is_active": True, "$text": {"$search": query_text}}
                projection = {"file_name": 1, "programming_language": 1, "tags": 1, "description": 1}
                cursor = coll.find(match, projection)
                if isinstance(cursor, list):
                    rows = list(cursor)[:candidate_limit]
                else:
                    try:
                        cursor = cursor.limit(candidate_limit)
                    except Exception:
                        pass
                    try:
                        rows = list(islice(cursor, candidate_limit))
                    except Exception:
                        rows = list(cursor)[:candidate_limit]
                for row in rows or []:
                    if isinstance(row, dict):
                        self._add_suggestions_from_row(suggestions, row, prefix)
        except Exception:
            pass

        if not suggestions:
            return []
        out = sorted(suggestions, key=len)
        return out[:limit]

    def suggest_completions(self, user_id: int, partial_query: str, limit: int = 10) -> List[str]:
        """הצעות השלמה לחיפוש"""
        
        if len(partial_query) < 2:
            return []

        completed_terms, prefix = self._split_query_terms(partial_query)
        if not prefix:
            return []

        suggestions_set: Set[str] = set()

        # מקור מהיר: קאש של שמות קבצים/תגיות/שפות (ללא DB Regex)
        try:
            from autocomplete_manager import autocomplete
            try:
                for name in autocomplete.get_user_filenames(user_id):
                    if str(name).lower().startswith(prefix):
                        suggestions_set.add(str(name))
            except Exception:
                pass
            try:
                for tag in autocomplete.get_user_tags(user_id):
                    if str(tag).lower().startswith(prefix):
                        suggestions_set.add(f"#{tag}")
            except Exception:
                pass
            try:
                for lang in autocomplete.get_user_languages(user_id):
                    if str(lang).lower().startswith(prefix):
                        suggestions_set.add(str(lang))
            except Exception:
                pass
        except Exception:
            pass

        # הרחבה עם $text רק כשיש מילים מלאות (prefix בלבד לא נתמך ב-$text)
        suggestions_set.update(
            self._suggest_from_text_search(user_id, completed_terms, prefix, limit=limit)
        )

        # שימוש באינדקס בזיכרון רק אם כבר נבנה (בלי rebuild כבד)
        index = self._get_ready_index(user_id, max_age_minutes=120)
        if index is not None:
            try:
                for word in index.word_index.keys():
                    if str(word).lower().startswith(prefix):
                        suggestions_set.add(str(word))
            except Exception:
                pass
            try:
                for func_name in index.function_index.keys():
                    if str(func_name).lower().startswith(prefix):
                        suggestions_set.add(str(func_name))
            except Exception:
                pass
            try:
                for lang in index.language_index.keys():
                    if str(lang).lower().startswith(prefix):
                        suggestions_set.add(str(lang))
            except Exception:
                pass
            try:
                for tag in index.tag_index.keys():
                    if str(tag).lower().startswith(prefix):
                        suggestions_set.add(f"#{tag}")
            except Exception:
                pass

        if not suggestions_set:
            return []
        out = sorted(suggestions_set, key=len)
        return out[:limit]
    
    def get_search_statistics(self, user_id: int) -> Dict[str, Any]:
        """סטטיסטיקות חיפוש"""
        
        index = self.get_index(user_id)
        
        return {
            "indexed_words": len(index.word_index),
            "indexed_functions": len(index.function_index),
            "indexed_languages": len(index.language_index),
            "indexed_tags": len(index.tag_index),
            "last_update": index.last_update.isoformat(),
            "most_common_words": self._get_most_common_words(index, 10),
            "most_common_languages": self._get_most_common_languages(index),
            "most_common_tags": self._get_most_common_tags(index)
        }
    
    def _get_most_common_words(self, index: SearchIndex, limit: int) -> List[Tuple[str, int]]:
        """המילים הנפוצות ביותר"""
        
        word_counts = [(word, len(files)) for word, files in index.word_index.items()]
        word_counts.sort(key=lambda x: x[1], reverse=True)
        
        return word_counts[:limit]
    
    def _get_most_common_languages(self, index: SearchIndex) -> List[Tuple[str, int]]:
        """השפות הנפוצות ביותר"""
        
        lang_counts = [(lang, len(files)) for lang, files in index.language_index.items()]
        lang_counts.sort(key=lambda x: x[1], reverse=True)
        
        return lang_counts
    
    def _get_most_common_tags(self, index: SearchIndex) -> List[Tuple[str, int]]:
        """התגיות הנפוצות ביותר"""
        
        tag_counts = [(tag, len(files)) for tag, files in index.tag_index.items()]
        tag_counts.sort(key=lambda x: x[1], reverse=True)
        
        return tag_counts[:20]

class SearchQueryParser:
    """מפרש שאילתות חיפוש מתקדמות"""
    
    def __init__(self):
        # בנייה בטוחה של מפת אופרטורים ומסננים כדי למנוע AttributeError בזמן build של RTD
        ops: Dict[str, Any] = {}
        for name, fn in [("AND", "_and_operator"), ("OR", "_or_operator"), ("NOT", "_not_operator")]:
            if hasattr(self, fn):
                ops[name] = getattr(self, fn)
        for name, fn in [
            ("lang:", "_language_filter"),
            ("tag:", "_tag_filter"),
            ("func:", "_function_filter"),
            ("size:", "_size_filter"),
            ("date:", "_date_filter"),
        ]:
            if hasattr(self, fn):
                ops[name] = getattr(self, fn)
        self.operators = ops
    
    def parse_query(self, query: str) -> Dict[str, Any]:
        """פרסור שאילתת חיפוש מתקדמת"""
        
        # דוגמאות לשאילתות:
        # "python AND api"
        # "lang:python tag:web"
        # "func:connect size:>100"
        # "date:2024 NOT test"
        
        from typing import List, cast, TypedDict
        class _Parsed(TypedDict):
            terms: List[str]
            filters: SearchFilter
            operators: List[str]
        parsed: _Parsed = {
            'terms': [],
            'filters': SearchFilter(),
            'operators': []
        }
        
        # פרסור בסיסי (לצורך ההדגמה)
        tokens = query.split()
        
        for token in tokens:
            if ':' in token:
                # זה מסנן
                key, value = token.split(':', 1)
                self._apply_filter(parsed['filters'], key, value)
            elif token.upper() in ['AND', 'OR', 'NOT']:
                parsed['operators'].append(token.upper())
            else:
                parsed['terms'].append(token)
        
        from typing import cast, Dict, Any
        return cast(Dict[str, Any], parsed)
    
    def _apply_filter(self, filters: SearchFilter, key: str, value: str):
        """החלת מסנן"""
        
        if key == 'lang':
            filters.languages.append(value)
        elif key == 'tag':
            filters.tags.append(value)
        elif key == 'size':
            # פרסור size:>100, size:<50, size:100-500
            if value.startswith('>'):
                filters.min_size = int(value[1:])
            elif value.startswith('<'):
                filters.max_size = int(value[1:])
            elif '-' in value:
                min_val, max_val = value.split('-')
                filters.min_size = int(min_val)
                filters.max_size = int(max_val)
        # ועוד מסננים...

    # ===== Stubs בטוחים לאופרטורים כדי למנוע AttributeError בזמן build =====
    def _and_operator(self, left: Any, right: Any) -> Any:
        raise NotImplementedError("_and_operator is not implemented yet")

    def _or_operator(self, left: Any, right: Any) -> Any:
        raise NotImplementedError("_or_operator is not implemented yet")

    def _not_operator(self, operand: Any) -> Any:
        raise NotImplementedError("_not_operator is not implemented yet")

    # מסננים אופציונליים (stubs) — אם ייקראו בבנייה, יעלו שגיאה ברורה
    def _language_filter(self, filters: SearchFilter, value: str) -> None:
        filters.languages.append(value)

    def _tag_filter(self, filters: SearchFilter, value: str) -> None:
        filters.tags.append(value)

    def _function_filter(self, filters: SearchFilter, value: str) -> None:
        # מסנן סמלי בלבד כרגע; אינדקס פונקציות מופעל בצד המנוע
        filters.tags.append(f"func:{value}")

    def _size_filter(self, filters: SearchFilter, value: str) -> None:
        if value.startswith('>'):
            filters.min_size = int(value[1:])
        elif value.startswith('<'):
            filters.max_size = int(value[1:])
        elif '-' in value:
            min_val, max_val = value.split('-')
            filters.min_size = int(min_val)
            filters.max_size = int(max_val)

    def _date_filter(self, filters: SearchFilter, value: str) -> None:
        # Stub: פירוש תאריך בסיסי — שומר לסינון מאוחר יותר בצד המנוע אם ימומש
        try:
            # תאריכים מוחלטים או יחסיים ימומשו בהמשך
            pass
        except Exception:
            pass

# יצירת אינסטנס גלובלי
search_engine = AdvancedSearchEngine()
query_parser = SearchQueryParser()
