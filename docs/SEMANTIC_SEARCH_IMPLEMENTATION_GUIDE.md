# מדריך מימוש חיפוש סמנטי - CodeBot

## סקירה כללית

מסמך זה מפרט את המימוש של חיפוש סמנטי (Semantic Search) במערכת CodeBot, המאפשר למשתמשים לחפש קטעי קוד לפי משמעות ולא רק לפי מילות מפתח.

### ארכיטקטורה בשלוש שכבות

```
┌─────────────────────────────────────────────────────────────┐
│                      SEARCH LAYER                            │
│  Flask API + Hybrid Query (Text + Vector)                   │
├─────────────────────────────────────────────────────────────┤
│                    EMBEDDING LAYER                           │
│  Gemini API (text-embedding-004) - External Service         │
├─────────────────────────────────────────────────────────────┤
│                      DATA LAYER                              │
│  MongoDB Atlas + Vector Search Indexes                       │
│  Collections: snippets, snippet_chunks                       │
└─────────────────────────────────────────────────────────────┘
```

---

## שלב 1: הגדרת Schema בבסיס הנתונים

### 1.1 עדכון Collection קיים - `snippets`

הוספת שדות סמנטיים ל-collection הקיים של הקבצים:

```python
# database/schemas.py

SNIPPET_SEMANTIC_FIELDS = {
    # Embedding של המטא-דאטה (כותרת + תיאור + תגיות)
    "snippetEmbedding": List[float],  # 768 או 1536 dimensions

    # דגלים לעיבוד רקע
    "needs_embedding": bool,      # האם צריך לחשב embedding מחדש
    "needs_chunking": bool,       # האם צריך לפצל לחלקים

    # מעקב שינויים
    "contentHash": str,           # SHA256 של התוכן - למניעת עיבוד כפול
    "embeddingUpdatedAt": datetime,

    # מספר chunks שנוצרו
    "chunkCount": int,
}
```

### 1.2 Collection חדש - `snippet_chunks`

Collection לאחסון חלקי קוד עם embeddings:

```python
# database/schemas.py

SNIPPET_CHUNK_SCHEMA = {
    "_id": ObjectId,
    "userId": int,                # מזהה משתמש (לסינון אבטחה)
    "snippetId": ObjectId,        # הפניה ל-snippet המקורי
    "language": str,              # שפת תכנות

    # תוכן החלק
    "chunkIndex": int,            # אינדקס החלק (0, 1, 2...)
    "codeChunk": str,             # הקוד עצמו (עד 220 שורות)
    "startLine": int,             # שורה התחלה בקובץ המקורי
    "endLine": int,               # שורה סיום

    # Embedding
    "chunkEmbedding": List[float],  # וקטור 768/1536 dimensions

    # מטא-דאטה
    "createdAt": datetime,
    "updatedAt": datetime,
}
```

### 1.3 יצירת Indexes ב-MongoDB Atlas

#### Text Search Index (`default`)

```json
{
  "mappings": {
    "dynamic": false,
    "fields": {
      "codeChunk": {
        "type": "string",
        "analyzer": "lucene.standard"
      },
      "userId": {
        "type": "number"
      },
      "snippetId": {
        "type": "objectId"
      },
      "language": {
        "type": "string",
        "analyzer": "lucene.keyword"
      }
    }
  }
}
```

#### Vector Search Index (`vector_index`)

```json
{
  "fields": [
    {
      "type": "vector",
      "path": "chunkEmbedding",
      "numDimensions": 768,
      "similarity": "cosine"
    },
    {
      "type": "filter",
      "path": "userId"
    },
    {
      "type": "filter",
      "path": "language"
    }
  ]
}
```

> **הערה חשובה**: יש ליצור את ה-indexes דרך ממשק MongoDB Atlas UI או Atlas CLI, לא דרך PyMongo.

---

## שלב 2: שירות Embeddings

### 2.1 יצירת קובץ השירות

```python
# services/embedding_service.py

"""
שירות יצירת Embeddings באמצעות Gemini API
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import List, Optional, Sequence

import httpx

logger = logging.getLogger(__name__)

# קונפיגורציה
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "text-embedding-004")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"
EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "768"))

# Rate limiting
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2.0
REQUEST_TIMEOUT = 30.0


class EmbeddingError(Exception):
    """שגיאה ביצירת embedding"""
    pass


class EmbeddingService:
    """שירות יצירת embeddings עבור טקסט וקוד"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or GEMINI_API_KEY
        if not self.api_key:
            logger.warning("GEMINI_API_KEY not configured - semantic search disabled")

        self._client: Optional[httpx.Client] = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=REQUEST_TIMEOUT)
        return self._client

    def is_available(self) -> bool:
        """בדיקה האם השירות זמין"""
        return bool(self.api_key)

    def generate_embedding(self, text: str) -> Optional[List[float]]:
        """
        יצירת embedding עבור טקסט בודד

        Args:
            text: הטקסט ליצירת embedding

        Returns:
            וקטור embedding או None בכישלון
        """
        if not self.is_available():
            return None

        if not text or not text.strip():
            return None

        # חיתוך טקסט ארוך מדי (Gemini limit ~10K tokens)
        text = text[:30000]

        url = f"{GEMINI_API_URL}/{GEMINI_EMBEDDING_MODEL}:embedContent"

        payload = {
            "model": f"models/{GEMINI_EMBEDDING_MODEL}",
            "content": {
                "parts": [{"text": text}]
            },
            "outputDimensionality": EMBEDDING_DIMENSIONS
        }

        for attempt in range(MAX_RETRIES):
            try:
                response = self.client.post(
                    url,
                    json=payload,
                    params={"key": self.api_key},
                    headers={"Content-Type": "application/json"}
                )

                if response.status_code == 200:
                    data = response.json()
                    embedding = data.get("embedding", {}).get("values", [])
                    if embedding:
                        return embedding
                    logger.error(f"Empty embedding in response: {data}")
                    return None

                elif response.status_code == 429:
                    # Rate limit - המתנה וניסיון חוזר
                    wait_time = RETRY_DELAY_SECONDS * (2 ** attempt)
                    logger.warning(f"Rate limited, waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue

                else:
                    logger.error(f"Gemini API error {response.status_code}: {response.text}")
                    return None

            except httpx.TimeoutException:
                logger.warning(f"Timeout on attempt {attempt + 1}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY_SECONDS)
                    continue
                return None

            except Exception as e:
                logger.error(f"Embedding generation failed: {e}")
                return None

        return None

    def generate_embeddings_batch(
        self,
        texts: Sequence[str],
        batch_size: int = 10
    ) -> List[Optional[List[float]]]:
        """
        יצירת embeddings עבור מספר טקסטים

        Args:
            texts: רשימת טקסטים
            batch_size: גודל batch (Gemini לא תומך ב-batch אמיתי, אז זה רק rate limiting)

        Returns:
            רשימת embeddings (או None עבור כל כישלון)
        """
        results: List[Optional[List[float]]] = []

        for i, text in enumerate(texts):
            embedding = self.generate_embedding(text)
            results.append(embedding)

            # Rate limiting בין בקשות
            if (i + 1) % batch_size == 0:
                time.sleep(0.5)

        return results

    def close(self):
        """סגירת החיבור"""
        if self._client:
            self._client.close()
            self._client = None


# Singleton instance
_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """קבלת instance של שירות ה-embeddings"""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service


def compute_content_hash(content: str) -> str:
    """חישוב hash של תוכן למעקב שינויים"""
    return hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()
```

### 2.2 הוספה ל-config.py

```python
# config.py - הוספת הגדרות

# Semantic Search / Embeddings
GEMINI_API_KEY: Optional[str] = Field(
    default=None,
    description="Gemini API key for embeddings"
)
EMBEDDING_DIMENSIONS: int = Field(
    default=768,
    ge=256,
    le=3072,
    description="Embedding vector dimensions (768 or 1536)"
)
SEMANTIC_SEARCH_ENABLED: bool = Field(
    default=True,
    description="Enable/disable semantic search feature"
)
CHUNK_SIZE_LINES: int = Field(
    default=220,
    description="Number of lines per code chunk"
)
CHUNK_OVERLAP_LINES: int = Field(
    default=40,
    description="Overlap between consecutive chunks"
)
```

---

## שלב 3: שירות Chunking

### 3.1 יצירת קובץ השירות

```python
# services/chunking_service.py

"""
שירות פיצול קוד לחלקים (chunks) עבור חיפוש סמנטי
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from config import config

logger = logging.getLogger(__name__)

# קונפיגורציה
CHUNK_SIZE = getattr(config, "CHUNK_SIZE_LINES", 220)
CHUNK_OVERLAP = getattr(config, "CHUNK_OVERLAP_LINES", 40)
MIN_CHUNK_SIZE = 10  # מינימום שורות לחלק


@dataclass
class CodeChunk:
    """מייצג חלק מקוד"""
    index: int
    content: str
    start_line: int
    end_line: int

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1


def split_code_to_chunks(
    code: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP
) -> List[CodeChunk]:
    """
    פיצול קוד לחלקים עם חפיפה

    האסטרטגיה:
    - כל chunk מכיל עד chunk_size שורות
    - יש חפיפה של overlap שורות בין chunks עוקבים
    - זה שומר על הקשר בין חלקי קוד

    Args:
        code: קוד מקור מלא
        chunk_size: מספר שורות מקסימלי לחלק
        overlap: מספר שורות חפיפה

    Returns:
        רשימת חלקי קוד
    """
    if not code or not code.strip():
        return []

    lines = code.splitlines()
    total_lines = len(lines)

    # קוד קצר - chunk אחד
    if total_lines <= chunk_size:
        return [CodeChunk(
            index=0,
            content=code,
            start_line=1,
            end_line=total_lines
        )]

    chunks: List[CodeChunk] = []
    step = chunk_size - overlap  # צעד בין התחלות chunks

    if step <= 0:
        step = chunk_size // 2  # fallback אם overlap גדול מדי

    chunk_index = 0
    start = 0

    while start < total_lines:
        end = min(start + chunk_size, total_lines)
        chunk_lines = lines[start:end]

        # דילוג על chunks ריקים או קטנים מדי
        if len(chunk_lines) >= MIN_CHUNK_SIZE:
            chunks.append(CodeChunk(
                index=chunk_index,
                content="\n".join(chunk_lines),
                start_line=start + 1,  # 1-indexed
                end_line=end
            ))
            chunk_index += 1

        # התקדמות לחלק הבא
        start += step

        # אם נשארו פחות שורות מ-overlap, נגמור
        if total_lines - start < MIN_CHUNK_SIZE:
            break

    logger.debug(f"Split {total_lines} lines into {len(chunks)} chunks")
    return chunks


def create_embedding_text(
    code_chunk: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[List[str]] = None,
    language: Optional[str] = None
) -> str:
    """
    יצירת טקסט משולב ל-embedding

    משלב מטא-דאטה (עברית/אנגלית) עם הקוד עצמו
    לאפשר חיפוש cross-language

    Args:
        code_chunk: חלק הקוד
        title: כותרת הקובץ
        description: תיאור
        tags: תגיות
        language: שפת תכנות

    Returns:
        טקסט משולב ל-embedding
    """
    parts: List[str] = []

    # מטא-דאטה (משקל גבוה יותר בתחילת הטקסט)
    if title:
        parts.append(f"Title: {title}")

    if description:
        parts.append(f"Description: {description}")

    if tags:
        parts.append(f"Tags: {', '.join(tags)}")

    if language:
        parts.append(f"Language: {language}")

    # הקוד עצמו
    if code_chunk:
        parts.append(f"\nCode:\n{code_chunk}")

    return "\n".join(parts)
```

---

## שלב 4: Database Manager - פונקציות חדשות

### 4.1 הוספה ל-database/manager.py

```python
# database/manager.py - הוספת פונקציות לחיפוש סמנטי

from bson import ObjectId
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.embedding_service import compute_content_hash


async def mark_snippet_for_reprocessing(
    user_id: int,
    file_name: str
) -> bool:
    """
    סימון snippet לעיבוד מחדש (לאחר עדכון תוכן)
    """
    result = await db.files.update_one(
        {"user_id": user_id, "file_name": file_name},
        {
            "$set": {
                "needs_embedding": True,
                "needs_chunking": True,
                "updatedAt": datetime.now(timezone.utc)
            }
        }
    )
    return result.modified_count > 0


async def get_snippets_needing_processing(
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    קבלת snippets שצריכים עיבוד embedding/chunking
    """
    cursor = db.files.find(
        {
            "$or": [
                {"needs_embedding": True},
                {"needs_chunking": True},
                {"contentHash": {"$exists": False}}
            ]
        },
        {
            "_id": 1,
            "user_id": 1,
            "file_name": 1,
            "content": 1,
            "description": 1,
            "tags": 1,
            "programming_language": 1,
            "contentHash": 1
        }
    ).limit(limit)

    return await cursor.to_list(length=limit)


async def save_snippet_chunks(
    user_id: int,
    snippet_id: ObjectId,
    chunks: List[Dict[str, Any]]
) -> int:
    """
    שמירת chunks של snippet

    Args:
        user_id: מזהה משתמש
        snippet_id: מזהה ה-snippet
        chunks: רשימת chunks עם embeddings

    Returns:
        מספר chunks שנשמרו
    """
    if not chunks:
        return 0

    # מחיקת chunks ישנים
    await db.snippet_chunks.delete_many({
        "userId": user_id,
        "snippetId": snippet_id
    })

    # הוספת chunks חדשים
    now = datetime.now(timezone.utc)
    documents = []

    for chunk in chunks:
        documents.append({
            "userId": user_id,
            "snippetId": snippet_id,
            "language": chunk.get("language", "unknown"),
            "chunkIndex": chunk["chunkIndex"],
            "codeChunk": chunk["codeChunk"],
            "startLine": chunk["startLine"],
            "endLine": chunk["endLine"],
            "chunkEmbedding": chunk["chunkEmbedding"],
            "createdAt": now,
            "updatedAt": now
        })

    result = await db.snippet_chunks.insert_many(documents)
    return len(result.inserted_ids)


async def update_snippet_embedding_status(
    snippet_id: ObjectId,
    content_hash: str,
    chunk_count: int,
    snippet_embedding: Optional[List[float]] = None
) -> bool:
    """
    עדכון סטטוס embedding של snippet
    """
    update_doc = {
        "$set": {
            "needs_embedding": False,
            "needs_chunking": False,
            "contentHash": content_hash,
            "chunkCount": chunk_count,
            "embeddingUpdatedAt": datetime.now(timezone.utc)
        }
    }

    if snippet_embedding:
        update_doc["$set"]["snippetEmbedding"] = snippet_embedding

    result = await db.files.update_one(
        {"_id": snippet_id},
        update_doc
    )
    return result.modified_count > 0
```

---

## שלב 5: Hybrid Search Query

### 5.1 הוספה ל-search_engine.py

```python
# search_engine.py - הוספת חיפוש סמנטי

from services.embedding_service import get_embedding_service
from typing import Tuple


# RRF (Reciprocal Rank Fusion) parameters
RRF_K = 60  # קבוע למיזוג
TEXT_WEIGHT = 1.0
VECTOR_WEIGHT = 1.2  # משקל גבוה יותר לחיפוש וקטורי


async def semantic_search(
    user_id: int,
    query: str,
    limit: int = 20,
    language_filter: Optional[str] = None,
    min_score: float = 0.5
) -> List[SearchResult]:
    """
    חיפוש סמנטי היברידי (Text + Vector)

    Args:
        user_id: מזהה משתמש (חובה לאבטחה)
        query: שאילתת חיפוש
        limit: מספר תוצאות מקסימלי
        language_filter: סינון לפי שפת תכנות
        min_score: ציון מינימלי

    Returns:
        רשימת תוצאות חיפוש ממוינות לפי רלוונטיות
    """
    embedding_service = get_embedding_service()

    if not embedding_service.is_available():
        logger.warning("Embedding service unavailable, falling back to text search")
        return await _fallback_text_search(user_id, query, limit, language_filter)

    # יצירת embedding לשאילתה
    query_embedding = embedding_service.generate_embedding(query)

    if not query_embedding:
        logger.warning("Failed to generate query embedding, falling back to text search")
        return await _fallback_text_search(user_id, query, limit, language_filter)

    # בניית pipeline היברידי
    pipeline = _build_hybrid_search_pipeline(
        user_id=user_id,
        query=query,
        query_embedding=query_embedding,
        limit=limit,
        language_filter=language_filter
    )

    # הרצת החיפוש
    try:
        cursor = db.snippet_chunks.aggregate(pipeline)
        raw_results = await cursor.to_list(length=limit * 2)
    except Exception as e:
        logger.error(f"Hybrid search failed: {e}")
        return await _fallback_text_search(user_id, query, limit, language_filter)

    # המרה לתוצאות חיפוש
    results = await _process_hybrid_results(raw_results, query, min_score, limit)

    return results


def _build_hybrid_search_pipeline(
    user_id: int,
    query: str,
    query_embedding: List[float],
    limit: int,
    language_filter: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    בניית MongoDB Aggregation Pipeline לחיפוש היברידי

    משתמש ב-$unionWith לשילוב תוצאות text ו-vector,
    ואז RRF למיזוג הדירוגים
    """
    num_candidates = limit * 20  # מומלץ על ידי MongoDB

    # פילטר בסיסי
    base_filter = {"userId": user_id}
    if language_filter:
        base_filter["language"] = language_filter

    pipeline = [
        # שלב 1: Vector Search
        {
            "$vectorSearch": {
                "index": "vector_index",
                "path": "chunkEmbedding",
                "queryVector": query_embedding,
                "numCandidates": num_candidates,
                "limit": limit * 2,
                "filter": base_filter
            }
        },

        # הוספת ציון וקטורי
        {
            "$addFields": {
                "vectorScore": {"$meta": "vectorSearchScore"},
                "searchType": "vector"
            }
        },

        # שלב 2: שילוב עם Text Search
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
                                            "fuzzy": {"maxEdits": 1}
                                        }
                                    }
                                ],
                                "filter": [
                                    {"equals": {"path": "userId", "value": user_id}}
                                ] + ([{"equals": {"path": "language", "value": language_filter}}] if language_filter else [])
                            }
                        }
                    },
                    {
                        "$addFields": {
                            "textScore": {"$meta": "searchScore"},
                            "searchType": "text"
                        }
                    },
                    {"$limit": limit * 2}
                ]
            }
        },

        # שלב 3: קיבוץ לפי snippet ומיזוג ציונים
        {
            "$group": {
                "_id": {
                    "snippetId": "$snippetId",
                    "chunkIndex": "$chunkIndex"
                },
                "snippetId": {"$first": "$snippetId"},
                "userId": {"$first": "$userId"},
                "language": {"$first": "$language"},
                "codeChunk": {"$first": "$codeChunk"},
                "startLine": {"$first": "$startLine"},
                "endLine": {"$first": "$endLine"},
                "vectorScore": {"$max": "$vectorScore"},
                "textScore": {"$max": "$textScore"}
            }
        },

        # שלב 4: חישוב RRF Score
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
                                        {"$divide": [1, {"$add": [RRF_K, {"$ifNull": ["$vectorRank", 100]}]}]}
                                    ]
                                },
                                "else": 0
                            }
                        },
                        {
                            "$cond": {
                                "if": {"$gt": ["$textScore", 0]},
                                "then": {
                                    "$multiply": [
                                        TEXT_WEIGHT,
                                        {"$divide": [1, {"$add": [RRF_K, {"$ifNull": ["$textRank", 100]}]}]}
                                    ]
                                },
                                "else": 0
                            }
                        }
                    ]
                }
            }
        },

        # שלב 5: מיון ו-limit
        {"$sort": {"rrfScore": -1}},
        {"$limit": limit},

        # שלב 6: Lookup לפרטי ה-snippet המקורי
        {
            "$lookup": {
                "from": "files",
                "localField": "snippetId",
                "foreignField": "_id",
                "as": "snippetDetails"
            }
        },
        {
            "$unwind": {
                "path": "$snippetDetails",
                "preserveNullAndEmptyArrays": True
            }
        },

        # שלב 7: פרויקציה סופית
        {
            "$project": {
                "snippetId": 1,
                "userId": 1,
                "language": 1,
                "codeChunk": 1,
                "startLine": 1,
                "endLine": 1,
                "rrfScore": 1,
                "vectorScore": 1,
                "textScore": 1,
                "fileName": "$snippetDetails.file_name",
                "title": "$snippetDetails.file_name",
                "description": "$snippetDetails.description",
                "tags": "$snippetDetails.tags",
                "fullContent": "$snippetDetails.content",
                "createdAt": "$snippetDetails.created_at",
                "updatedAt": "$snippetDetails.updated_at"
            }
        }
    ]

    return pipeline


async def _process_hybrid_results(
    raw_results: List[Dict[str, Any]],
    query: str,
    min_score: float,
    limit: int
) -> List[SearchResult]:
    """
    עיבוד תוצאות גולמיות לאובייקטי SearchResult
    """
    results: List[SearchResult] = []
    seen_snippets: set = set()

    for doc in raw_results:
        snippet_id = str(doc.get("snippetId", ""))

        # מניעת כפילויות
        if snippet_id in seen_snippets:
            continue
        seen_snippets.add(snippet_id)

        score = doc.get("rrfScore", 0)
        if score < min_score:
            continue

        # יצירת preview עם הקשר
        preview = _create_context_preview(
            code_chunk=doc.get("codeChunk", ""),
            query=query,
            context_lines=10
        )

        results.append(SearchResult(
            file_name=doc.get("fileName", "unknown"),
            content=doc.get("fullContent", ""),
            programming_language=doc.get("language", "unknown"),
            tags=doc.get("tags", []),
            created_at=doc.get("createdAt", datetime.now(timezone.utc)),
            updated_at=doc.get("updatedAt", datetime.now(timezone.utc)),
            version=1,
            relevance_score=score,
            snippet_preview=preview,
            matches=[{
                "startLine": doc.get("startLine", 1),
                "endLine": doc.get("endLine", 1),
                "chunkIndex": doc.get("chunkIndex", 0)
            }]
        ))

        if len(results) >= limit:
            break

    return results


def _create_context_preview(
    code_chunk: str,
    query: str,
    context_lines: int = 10
) -> str:
    """
    יצירת preview עם הקשר סביב מילות החיפוש
    """
    if not code_chunk:
        return ""

    lines = code_chunk.splitlines()
    query_terms = query.lower().split()

    # מציאת השורה הרלוונטית ביותר
    best_line_idx = 0
    best_match_count = 0

    for idx, line in enumerate(lines):
        line_lower = line.lower()
        match_count = sum(1 for term in query_terms if term in line_lower)
        if match_count > best_match_count:
            best_match_count = match_count
            best_line_idx = idx

    # חילוץ הקשר
    start = max(0, best_line_idx - context_lines)
    end = min(len(lines), best_line_idx + context_lines + 1)

    return "\n".join(lines[start:end])


async def _fallback_text_search(
    user_id: int,
    query: str,
    limit: int,
    language_filter: Optional[str]
) -> List[SearchResult]:
    """
    Fallback לחיפוש טקסט רגיל כאשר semantic לא זמין
    """
    # שימוש בחיפוש הקיים
    return await search_files(
        user_id=user_id,
        query=query,
        search_type=SearchType.FUZZY,
        limit=limit,
        filters=SearchFilter(
            languages=[language_filter] if language_filter else []
        )
    )
```

---

## שלב 6: Background Worker לעיבוד Embeddings

### 6.1 יצירת Worker

```python
# services/embedding_worker.py

"""
Worker לעיבוד embeddings ברקע
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId

from database import db
from database.manager import (
    get_snippets_needing_processing,
    save_snippet_chunks,
    update_snippet_embedding_status
)
from services.embedding_service import (
    get_embedding_service,
    compute_content_hash
)
from services.chunking_service import (
    split_code_to_chunks,
    create_embedding_text
)

logger = logging.getLogger(__name__)

# קונפיגורציה
BATCH_SIZE = 10
POLL_INTERVAL_SECONDS = 60
MAX_ERRORS_BEFORE_PAUSE = 5


class EmbeddingWorker:
    """Worker לעיבוד embeddings ברקע"""

    def __init__(self):
        self.embedding_service = get_embedding_service()
        self._running = False
        self._error_count = 0

    async def start(self):
        """התחלת ה-worker"""
        if not self.embedding_service.is_available():
            logger.warning("Embedding service not available, worker disabled")
            return

        self._running = True
        logger.info("Embedding worker started")

        while self._running:
            try:
                processed = await self._process_batch()

                if processed == 0:
                    # אין עבודה - המתנה ארוכה יותר
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
                else:
                    # יש עבודה - המתנה קצרה
                    await asyncio.sleep(5)
                    self._error_count = 0

            except Exception as e:
                self._error_count += 1
                logger.error(f"Worker error ({self._error_count}): {e}")

                if self._error_count >= MAX_ERRORS_BEFORE_PAUSE:
                    logger.warning("Too many errors, pausing worker for 5 minutes")
                    await asyncio.sleep(300)
                    self._error_count = 0
                else:
                    await asyncio.sleep(30)

    def stop(self):
        """עצירת ה-worker"""
        self._running = False
        logger.info("Embedding worker stopped")

    async def _process_batch(self) -> int:
        """עיבוד batch של snippets"""
        snippets = await get_snippets_needing_processing(limit=BATCH_SIZE)

        if not snippets:
            return 0

        processed = 0
        for snippet in snippets:
            try:
                await self._process_snippet(snippet)
                processed += 1
            except Exception as e:
                logger.error(f"Failed to process snippet {snippet.get('_id')}: {e}")

        logger.info(f"Processed {processed}/{len(snippets)} snippets")
        return processed

    async def _process_snippet(self, snippet: dict):
        """עיבוד snippet בודד"""
        snippet_id = snippet["_id"]
        user_id = snippet["user_id"]
        content = snippet.get("content", "")

        if not content:
            await update_snippet_embedding_status(
                snippet_id=snippet_id,
                content_hash="empty",
                chunk_count=0
            )
            return

        # בדיקה אם התוכן השתנה
        current_hash = compute_content_hash(content)
        if current_hash == snippet.get("contentHash"):
            logger.debug(f"Snippet {snippet_id} unchanged, skipping")
            return

        # פיצול לחלקים
        chunks = split_code_to_chunks(content)

        if not chunks:
            await update_snippet_embedding_status(
                snippet_id=snippet_id,
                content_hash=current_hash,
                chunk_count=0
            )
            return

        # יצירת embeddings
        chunk_docs = []
        for chunk in chunks:
            embedding_text = create_embedding_text(
                code_chunk=chunk.content,
                title=snippet.get("file_name"),
                description=snippet.get("description"),
                tags=snippet.get("tags", []),
                language=snippet.get("programming_language")
            )

            embedding = self.embedding_service.generate_embedding(embedding_text)

            if embedding:
                chunk_docs.append({
                    "chunkIndex": chunk.index,
                    "codeChunk": chunk.content,
                    "startLine": chunk.start_line,
                    "endLine": chunk.end_line,
                    "language": snippet.get("programming_language", "unknown"),
                    "chunkEmbedding": embedding
                })

        # שמירה ל-DB
        if chunk_docs:
            await save_snippet_chunks(
                user_id=user_id,
                snippet_id=snippet_id,
                chunks=chunk_docs
            )

        # יצירת embedding למטא-דאטה של ה-snippet
        metadata_text = create_embedding_text(
            code_chunk="",
            title=snippet.get("file_name"),
            description=snippet.get("description"),
            tags=snippet.get("tags", []),
            language=snippet.get("programming_language")
        )
        snippet_embedding = self.embedding_service.generate_embedding(metadata_text)

        # עדכון סטטוס
        await update_snippet_embedding_status(
            snippet_id=snippet_id,
            content_hash=current_hash,
            chunk_count=len(chunk_docs),
            snippet_embedding=snippet_embedding
        )

        logger.info(f"Processed snippet {snippet_id}: {len(chunk_docs)} chunks")


# Singleton
_worker: Optional[EmbeddingWorker] = None


def get_embedding_worker() -> EmbeddingWorker:
    global _worker
    if _worker is None:
        _worker = EmbeddingWorker()
    return _worker
```

### 6.2 הפעלת Worker ב-main.py

```python
# main.py - הוספה

import asyncio
from services.embedding_worker import get_embedding_worker

# בפונקציית האתחול
async def start_background_workers():
    """הפעלת workers ברקע"""
    worker = get_embedding_worker()
    asyncio.create_task(worker.start())

# ב-main או post_init
if config.SEMANTIC_SEARCH_ENABLED:
    asyncio.get_event_loop().run_until_complete(start_background_workers())
```

---

## שלב 7: API Endpoint

### 7.1 הוספה ל-webapp/app.py

```python
# webapp/app.py - הוספת endpoint

from search_engine import semantic_search, SearchType


@app.route("/api/search/semantic", methods=["POST"])
@require_auth
@rate_limit(requests_per_minute=30)
async def api_semantic_search():
    """
    חיפוש סמנטי בקטעי קוד

    Request Body:
    {
        "query": "חיפוש פונקציה לסינון מערך",
        "limit": 20,
        "language": "python"  // אופציונלי
    }

    Response:
    {
        "results": [...],
        "total": 15,
        "query": "...",
        "search_type": "semantic"
    }
    """
    try:
        data = request.get_json() or {}
        query = data.get("query", "").strip()

        if not query:
            return jsonify({"error": "Query is required"}), 400

        if len(query) > 500:
            return jsonify({"error": "Query too long (max 500 chars)"}), 400

        limit = min(data.get("limit", 20), 50)
        language = data.get("language")

        user_id = get_current_user_id()

        results = await semantic_search(
            user_id=user_id,
            query=query,
            limit=limit,
            language_filter=language
        )

        return jsonify({
            "results": [
                {
                    "file_name": r.file_name,
                    "language": r.programming_language,
                    "tags": r.tags,
                    "score": round(r.relevance_score, 4),
                    "preview": r.snippet_preview,
                    "matches": r.matches,
                    "updated_at": r.updated_at.isoformat()
                }
                for r in results
            ],
            "total": len(results),
            "query": query,
            "search_type": "semantic"
        })

    except Exception as e:
        logger.error(f"Semantic search error: {e}")
        return jsonify({"error": "Search failed"}), 500
```

---

## שלב 8: Migration Script

### 8.1 סקריפט להעברת נתונים קיימים

```python
# scripts/migrate_semantic_search.py

"""
סקריפט להעברת snippets קיימים לחיפוש סמנטי
הרץ פעם אחת לאחר deploy
"""

import asyncio
import logging
import sys
from datetime import datetime, timezone

from pymongo import UpdateOne

# הוספת נתיב הפרויקט
sys.path.insert(0, "/home/user/CodeBot")

from database import db
from config import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BATCH_SIZE = 100


async def migrate_snippets():
    """הוספת שדות סמנטיים ל-snippets קיימים"""

    logger.info("Starting semantic search migration...")

    # ספירת snippets
    total = await db.files.count_documents({})
    logger.info(f"Total snippets to migrate: {total}")

    # עדכון כל ה-snippets לסמן לעיבוד
    result = await db.files.update_many(
        {
            "needs_embedding": {"$exists": False}
        },
        {
            "$set": {
                "needs_embedding": True,
                "needs_chunking": True,
                "chunkCount": 0,
                "embeddingUpdatedAt": None
            }
        }
    )

    logger.info(f"Marked {result.modified_count} snippets for processing")

    # יצירת collection חדש אם לא קיים
    collections = await db.list_collection_names()
    if "snippet_chunks" not in collections:
        await db.create_collection("snippet_chunks")
        logger.info("Created snippet_chunks collection")

    # יצירת אינדקסים בסיסיים (לא vector - את זה עושים ב-Atlas UI)
    await db.snippet_chunks.create_index([
        ("userId", 1),
        ("snippetId", 1)
    ])
    await db.snippet_chunks.create_index([
        ("userId", 1),
        ("language", 1)
    ])

    logger.info("Created basic indexes on snippet_chunks")
    logger.info("Migration complete!")
    logger.info("")
    logger.info("IMPORTANT: Create the following indexes in MongoDB Atlas UI:")
    logger.info("1. Search Index 'default' on snippet_chunks")
    logger.info("2. Vector Search Index 'vector_index' on snippet_chunks")
    logger.info("")
    logger.info("The embedding worker will process snippets in the background")


async def check_migration_status():
    """בדיקת סטטוס המיגרציה"""

    total = await db.files.count_documents({})
    pending = await db.files.count_documents({"needs_embedding": True})
    processed = await db.files.count_documents({"needs_embedding": False, "chunkCount": {"$gt": 0}})
    chunks = await db.snippet_chunks.count_documents({})

    logger.info(f"Migration Status:")
    logger.info(f"  Total snippets: {total}")
    logger.info(f"  Pending processing: {pending}")
    logger.info(f"  Processed: {processed}")
    logger.info(f"  Total chunks: {chunks}")

    if pending > 0:
        logger.info(f"  Progress: {(processed/total)*100:.1f}%")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        asyncio.run(check_migration_status())
    else:
        asyncio.run(migrate_snippets())
```

---

## שלב 9: Frontend Integration

### 9.1 עדכון global_search.js

```javascript
// webapp/static/js/global_search.js - הוספות

/**
 * חיפוש סמנטי
 */
async function performSemanticSearch(query, options = {}) {
    const { limit = 20, language = null } = options;

    try {
        const response = await fetch('/api/search/semantic', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                query,
                limit,
                language
            })
        });

        if (!response.ok) {
            throw new Error(`Search failed: ${response.status}`);
        }

        const data = await response.json();
        return data.results;

    } catch (error) {
        console.error('Semantic search error:', error);
        // Fallback to regular search
        return performTextSearch(query, options);
    }
}

/**
 * עדכון ה-search handler להשתמש בחיפוש סמנטי
 */
function initSemanticSearch() {
    const searchInput = document.getElementById('global-search-input');
    const searchTypeToggle = document.getElementById('search-type-toggle');

    if (!searchInput) return;

    // Toggle בין חיפוש רגיל לסמנטי
    let useSemanticSearch = true;

    if (searchTypeToggle) {
        searchTypeToggle.addEventListener('change', (e) => {
            useSemanticSearch = e.target.checked;
            // עדכון UI
            const label = document.querySelector('[for="search-type-toggle"]');
            if (label) {
                label.textContent = useSemanticSearch ? 'חיפוש חכם' : 'חיפוש רגיל';
            }
        });
    }

    // Debounced search
    let searchTimeout;
    searchInput.addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        const query = e.target.value.trim();

        if (query.length < 2) {
            hideSearchResults();
            return;
        }

        searchTimeout = setTimeout(async () => {
            showSearchLoading();

            const results = useSemanticSearch
                ? await performSemanticSearch(query)
                : await performTextSearch(query);

            displaySearchResults(results);
        }, 300);
    });
}

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', initSemanticSearch);
```

---

## שלב 10: Environment Variables

### 10.1 הוספה ל-.env

```bash
# .env - הוספות לחיפוש סמנטי

# Gemini API
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_EMBEDDING_MODEL=text-embedding-004

# Semantic Search Config
SEMANTIC_SEARCH_ENABLED=true
EMBEDDING_DIMENSIONS=768
CHUNK_SIZE_LINES=220
CHUNK_OVERLAP_LINES=40
```

### 10.2 הוספה ל-render.yaml

```yaml
# render.yaml - הוספת env vars

envVars:
  - key: GEMINI_API_KEY
    sync: false
  - key: SEMANTIC_SEARCH_ENABLED
    value: "true"
  - key: EMBEDDING_DIMENSIONS
    value: "768"
```

---

## שלב 11: Testing

### 11.1 Unit Tests

```python
# tests/unit/services/test_embedding_service.py

import pytest
from unittest.mock import patch, MagicMock

from services.embedding_service import (
    EmbeddingService,
    compute_content_hash
)
from services.chunking_service import (
    split_code_to_chunks,
    create_embedding_text
)


class TestContentHash:
    def test_consistent_hash(self):
        content = "def hello(): pass"
        hash1 = compute_content_hash(content)
        hash2 = compute_content_hash(content)
        assert hash1 == hash2

    def test_different_content_different_hash(self):
        hash1 = compute_content_hash("def foo(): pass")
        hash2 = compute_content_hash("def bar(): pass")
        assert hash1 != hash2


class TestChunking:
    def test_short_code_single_chunk(self):
        code = "\n".join([f"line {i}" for i in range(50)])
        chunks = split_code_to_chunks(code, chunk_size=100)
        assert len(chunks) == 1

    def test_long_code_multiple_chunks(self):
        code = "\n".join([f"line {i}" for i in range(500)])
        chunks = split_code_to_chunks(code, chunk_size=100, overlap=20)
        assert len(chunks) > 1

    def test_chunk_overlap(self):
        code = "\n".join([f"line {i}" for i in range(300)])
        chunks = split_code_to_chunks(code, chunk_size=100, overlap=20)

        # בדיקה שיש חפיפה
        if len(chunks) >= 2:
            chunk1_end = chunks[0].end_line
            chunk2_start = chunks[1].start_line
            assert chunk2_start < chunk1_end  # overlap exists

    def test_empty_code(self):
        chunks = split_code_to_chunks("")
        assert len(chunks) == 0


class TestEmbeddingText:
    def test_creates_combined_text(self):
        text = create_embedding_text(
            code_chunk="def hello(): pass",
            title="hello.py",
            description="A greeting function",
            tags=["python", "utils"],
            language="python"
        )

        assert "hello.py" in text
        assert "greeting function" in text
        assert "python" in text
        assert "def hello()" in text


class TestEmbeddingService:
    @patch('services.embedding_service.httpx.Client')
    def test_generate_embedding_success(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "embedding": {"values": [0.1] * 768}
        }
        mock_client.post.return_value = mock_response

        service = EmbeddingService(api_key="test_key")
        embedding = service.generate_embedding("test text")

        assert embedding is not None
        assert len(embedding) == 768

    def test_no_api_key_returns_none(self):
        service = EmbeddingService(api_key="")
        assert service.generate_embedding("test") is None
```

---

## סיכום וצ'קליסט

### לפני Deploy

- [ ] הוספת `GEMINI_API_KEY` ל-environment variables
- [ ] יצירת Search Index ב-MongoDB Atlas
- [ ] יצירת Vector Search Index ב-MongoDB Atlas
- [ ] הרצת migration script
- [ ] בדיקת unit tests

### אחרי Deploy

- [ ] מעקב אחרי worker logs
- [ ] בדיקת סטטוס migration (`python scripts/migrate_semantic_search.py status`)
- [ ] בדיקת ה-API endpoint
- [ ] ניטור rate limits של Gemini API

### אופטימיזציות עתידיות

1. **Caching** - שמירת query embeddings ב-Redis
2. **Batch Processing** - עיבוד מקבילי של embeddings
3. **Incremental Updates** - עדכון רק chunks שהשתנו
4. **Hybrid Scoring Tuning** - כיוון משקלות RRF

---

## נספח: MongoDB Atlas Index Creation

### יצירת Search Index

1. כניסה ל-MongoDB Atlas
2. ניווט ל-Database → Browse Collections → snippet_chunks
3. לחיצה על "Search Indexes" → "Create Index"
4. בחירת "JSON Editor"
5. הדבקת הקונפיגורציה מסעיף 1.3

### יצירת Vector Search Index

1. באותו מקום, לחיצה על "Create Index"
2. בחירת "Atlas Vector Search"
3. הדבקת הקונפיגורציה מסעיף 1.3
4. שם האינדקס: `vector_index`

---

*מסמך זה נכתב עבור CodeBot ומותאם לארכיטקטורה הקיימת של הפרויקט.*
