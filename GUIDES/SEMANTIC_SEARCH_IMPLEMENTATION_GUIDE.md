# 🚀 מדריך מימוש: Smart Semantic Search (AI Embeddings)

> **מטרת המסמך:** מדריך צעד-אחר-צעד למימוש חיפוש סמנטי חכם ב-CodeBot, תואם לקוד הקיים.  
> **קהל יעד:** מפתחים שעובדים על הפרויקט.  
> **תאריך:** דצמבר 2025

---

## 📋 תוכן עניינים

1. [סקירה כללית](#-סקירה-כללית)
2. [שלב 1: הגדרת תשתית](#-שלב-1-הגדרת-תשתית)
3. [שלב 2: יצירת שירות Embeddings](#-שלב-2-יצירת-שירות-embeddings)
4. [שלב 3: עדכון המודלים ב-Database](#-שלב-3-עדכון-המודלים-ב-database)
5. [שלב 4: יצירת Vector Index ב-MongoDB](#-שלב-4-יצירת-vector-index-ב-mongodb)
6. [שלב 5: אינדוקס קבצים קיימים](#-שלב-5-אינדוקס-קבצים-קיימים)
7. [שלב 6: עדכון מנוע החיפוש](#-שלב-6-עדכון-מנוע-החיפוש)
8. [שלב 7: עדכון ה-API](#-שלב-7-עדכון-ה-api)
9. [שלב 8: עדכון ה-Frontend](#-שלב-8-עדכון-ה-frontend)
10. [שיפורים מומלצים (Nice to Have)](#-שיפורים-מומלצים-nice-to-have)
11. [בדיקות](#-בדיקות)
12. [נספחים](#-נספחים)

---

## 🎯 סקירה כללית

### מה נבנה?

מערכת חיפוש חכמה שמאפשרת למצוא קבצים **לפי משמעות** ולא רק לפי מילים מדויקות.

### דוגמה

| חיפוש המשתמש | תוצאה שתימצא |
|--------------|--------------|
| `"תיקון הבהוב בכפתור"` | `theme.css` עם `/* prevent white flash on click */` |
| `"validate email"` | קובץ עם פונקציה `is_valid_email_address()` |
| `"handle errors"` | קובץ עם `try/except` או `catch` |

### ארכיטקטורה ברמה גבוהה

```
┌──────────────┐    ┌────────────────┐    ┌─────────────────┐
│  User Query  │───▶│ Embedding API  │───▶│ Vector (1536d)  │
└──────────────┘    │  (OpenAI)      │    └────────┬────────┘
                    └────────────────┘             │
                                                   ▼
┌──────────────┐    ┌────────────────┐    ┌─────────────────┐
│  Results     │◀───│ MongoDB Atlas  │◀───│ $vectorSearch   │
│  (ranked)    │    │ Vector Search  │    │                 │
└──────────────┘    └────────────────┘    └─────────────────┘
```

---

## 🔧 שלב 1: הגדרת תשתית

### 1.1 הוספת משתני סביבה

הוסף לקובץ `.env` (או ל-secrets):

```bash
# Embeddings API
OPENAI_API_KEY=sk-...your-key...
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536  # or 512 for smaller index

# Feature flags
SEMANTIC_SEARCH_ENABLED=true
SEMANTIC_SEARCH_INDEX_ON_SAVE=true
```

### 1.2 עדכון `config.py`

מצא את הקובץ `config.py` והוסף את ההגדרות הבאות (ליד ההגדרות הקיימות):

```python
# === Semantic Search ===
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIMENSIONS: int = int(os.getenv("EMBEDDING_DIMENSIONS", "1536"))
SEMANTIC_SEARCH_ENABLED: bool = os.getenv("SEMANTIC_SEARCH_ENABLED", "false").lower() == "true"
SEMANTIC_SEARCH_INDEX_ON_SAVE: bool = os.getenv("SEMANTIC_SEARCH_INDEX_ON_SAVE", "false").lower() == "true"
# מספר תווים מקסימלי לשליחה ל-Embedding API (חיסכון בעלויות)
EMBEDDING_MAX_CHARS: int = int(os.getenv("EMBEDDING_MAX_CHARS", "2000"))
```

### 1.3 הוספת dependencies

הוסף ל-`requirements/base.txt`:

```
openai>=1.0.0
tiktoken>=0.5.0  # לספירת tokens (אופציונלי)
```

---

## 🤖 שלב 2: יצירת שירות Embeddings

### 2.1 יצירת `services/embedding_service.py`

צור קובץ חדש:

```python
"""
שירות יצירת Embeddings עבור חיפוש סמנטי.
Embedding Service for Semantic Search.
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any, Dict, List, Optional

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
except Exception:
    def emit_event(event: str, severity: str = "info", **fields):
        return None

try:
    from metrics import track_performance
except Exception:
    from contextlib import contextmanager
    @contextmanager
    def track_performance(operation: str, labels=None):
        yield


class EmbeddingError(RuntimeError):
    """שגיאה ביצירת embedding."""
    pass


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
            return truncated[:last_sep + len(sep)].strip()
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
                extra={"status_code": exc.response.status_code, "model": model}
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
```

### 2.2 עדכון `services/__init__.py`

הוסף ייבוא לשירות החדש:

```python
# בתחתית הקובץ, הוסף:
try:
    from .embedding_service import (
        generate_embedding,
        generate_embedding_for_file,
        generate_embedding_sync,
        EmbeddingError,
    )
except ImportError:
    pass  # Optional dependency
```

---

## 📊 שלב 3: עדכון המודלים ב-Database

### 3.1 עדכון `database/models.py`

מצא את ה-dataclass `CodeSnippet` והוסף את השדות הבאים:

```python
@dataclass
class CodeSnippet:
    """ייצוג קטע קוד הנשמר במסד הנתונים."""
    user_id: int
    file_name: str
    code: str
    programming_language: str
    # שדות מועדפים
    is_favorite: bool = False
    favorited_at: Optional[datetime] = None
    description: str = ""
    tags: Optional[List[str]] = None
    version: int = 1
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_active: bool = True
    # שדות סל מיחזור
    deleted_at: Optional[datetime] = None
    deleted_expires_at: Optional[datetime] = None
    
    # ===== שדות חדשים לחיפוש סמנטי =====
    embedding: Optional[List[float]] = None  # וקטור ה-embedding (1536 floats)
    embedding_model: Optional[str] = None    # שם המודל שיצר את ה-embedding
    embedding_updated_at: Optional[datetime] = None  # מתי עודכן ה-embedding
    needs_embedding_update: bool = True  # האם צריך לעדכן את ה-embedding
    
    def __post_init__(self) -> None:
        if self.tags is None:
            self.tags = []
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)
        if self.updated_at is None:
            self.updated_at = datetime.now(timezone.utc)
```

### 3.2 עדכון `HEAVY_FIELDS_EXCLUDE_PROJECTION` ב-`database/repository.py`

מצא את ההגדרה של `_HEAVY_FIELDS_EXCLUDE_PROJECTION` ועדכן:

```python
_HEAVY_FIELDS_EXCLUDE_PROJECTION: Dict[str, int] = {
    "code": 0,        # CodeSnippet
    "content": 0,     # LargeFile
    "raw_data": 0,    # future-proof
    "raw_content": 0, # future-proof
    "embedding": 0,   # ⬅️ חדש! לא להחזיר את הוקטור ברשימות
}
```

### 3.3 עדכון `save_code_snippet` ב-`database/repository.py`

מצא את הפונקציה `save_code_snippet` והוסף את ההיגיון לסימון צורך בעדכון embedding:

> ⚠️ **חשוב:** יש לבדוק שינוי בכל השדות שמרכיבים את ה-Embedding (לא רק `code`!).  
> ה-Embedding נבנה מ: `code` + `description` + `tags` + `programming_language`.  
> אם נבדוק רק את `code`, שינוי בתיאור או בתגיות לא יעדכן את ה-Embedding והחיפוש לא ימצא את הקובץ לפי המידע החדש.

```python
@_instrument_db("db.save_code_snippet")
def save_code_snippet(self, snippet: CodeSnippet) -> bool:
    try:
        # Normalize code before persisting
        try:
            if config.NORMALIZE_CODE_ON_SAVE:
                snippet.code = normalize_code(snippet.code)
        except Exception:
            pass
        
        existing = self.get_latest_version(snippet.user_id, snippet.file_name)
        if existing:
            snippet.version = existing['version'] + 1
            # ... (קוד קיים לשמירת מועדפים)
            
            # ===== בדיקה אם צריך לעדכן embedding =====
            # חשוב: בודקים שינוי בכל השדות שמרכיבים את ה-Embedding!
            # ה-Embedding נבנה מ: code + description + tags + programming_language
            
            old_code = existing.get('code', '')
            old_description = existing.get('description', '')
            old_tags = existing.get('tags') or []
            old_language = existing.get('programming_language', '')
            
            # השוואה בטוחה של tags (רשימות)
            def _normalize_tags(tags):
                if not tags:
                    return []
                return sorted([str(t).strip().lower() for t in tags if t])
            
            embedding_content_changed = (
                old_code != snippet.code or
                old_description != (snippet.description or '') or
                _normalize_tags(old_tags) != _normalize_tags(snippet.tags) or
                old_language != (snippet.programming_language or '')
            )
            
            if embedding_content_changed:
                snippet.needs_embedding_update = True
                snippet.embedding = None  # נקה embedding ישן
            else:
                # שמור על ה-embedding הקיים אם התוכן לא השתנה
                snippet.embedding = existing.get('embedding')
                snippet.embedding_model = existing.get('embedding_model')
                snippet.embedding_updated_at = existing.get('embedding_updated_at')
                snippet.needs_embedding_update = existing.get('needs_embedding_update', True)
        
        snippet.updated_at = datetime.now(timezone.utc)
        # ... (המשך הקוד הקיים)
```

---

## 🔍 שלב 4: יצירת Vector Index ב-MongoDB

### 4.1 יצירת האינדקס ב-MongoDB Atlas

**חשוב:** Vector Search זמין רק ב-MongoDB Atlas (לא ב-Community Edition).

היכנס ל-MongoDB Atlas Console וצור Search Index חדש:

1. לך ל-**Database** → **Search** → **Create Search Index**
2. בחר **JSON Editor**
3. הזן את ההגדרה הבאה:

```json
{
  "name": "code_snippets_vector_index",
  "type": "vectorSearch",
  "definition": {
    "fields": [
      {
        "type": "vector",
        "path": "embedding",
        "numDimensions": 1536,
        "similarity": "cosine"
      },
      {
        "type": "filter",
        "path": "user_id"
      },
      {
        "type": "filter",
        "path": "is_active"
      },
      {
        "type": "filter",
        "path": "programming_language"
      }
    ]
  }
}
```

### 4.2 יצירת סקריפט ליצירת האינדקס (אופציונלי)

צור קובץ `scripts/create_vector_index.py`:

```python
"""
סקריפט ליצירת Vector Index ב-MongoDB Atlas.
"""

import os
import sys

# הוסף את ה-root לנתיב
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import MongoClient
from config import config

def create_vector_index():
    """יצירת Vector Search Index."""
    client = MongoClient(config.MONGODB_URI)
    db = client[config.MONGODB_DB_NAME]
    collection = db.code_snippets
    
    # הגדרת האינדקס
    index_definition = {
        "name": "code_snippets_vector_index",
        "type": "vectorSearch",
        "definition": {
            "fields": [
                {
                    "type": "vector",
                    "path": "embedding",
                    "numDimensions": int(os.getenv("EMBEDDING_DIMENSIONS", "1536")),
                    "similarity": "cosine"
                },
                {"type": "filter", "path": "user_id"},
                {"type": "filter", "path": "is_active"},
                {"type": "filter", "path": "programming_language"},
            ]
        }
    }
    
    print("Creating vector index...")
    print("Note: This must be done via Atlas UI or Atlas Admin API")
    print("Index definition:")
    import json
    print(json.dumps(index_definition, indent=2))

if __name__ == "__main__":
    create_vector_index()
```

---

## 📥 שלב 5: אינדוקס קבצים קיימים

### 5.1 יצירת Background Job לאינדוקס

צור קובץ `scripts/index_embeddings.py`:

```python
"""
סקריפט לאינדוקס embeddings עבור קבצים קיימים.
Batch Indexing Script for Existing Files.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# הוסף את ה-root לנתיב
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Constants
BATCH_SIZE = 50  # מספר קבצים לעיבוד בכל batch
RATE_LIMIT_DELAY = 0.1  # השהיה בין בקשות (שניות)
MAX_RETRIES = 3


async def process_batch(
    files: List[Dict[str, Any]],
    repository,
    stats: Dict[str, int],
) -> None:
    """עיבוד batch של קבצים."""
    from services.embedding_service import (
        generate_embedding_for_file,
        EmbeddingError,
    )
    
    for file_data in files:
        file_id = str(file_data.get("_id", ""))
        file_name = file_data.get("file_name", "unknown")
        user_id = file_data.get("user_id")
        
        try:
            # הכן את הטקסט
            code = file_data.get("code", "")
            if not code:
                stats["skipped_empty"] += 1
                continue
            
            # יצירת embedding
            embedding = await generate_embedding_for_file(
                code=code,
                file_name=file_name,
                description=file_data.get("description", ""),
                tags=file_data.get("tags"),
                programming_language=file_data.get("programming_language", ""),
            )
            
            # עדכון ב-DB
            now = datetime.now(timezone.utc)
            update_result = repository.manager.collection.update_one(
                {"_id": file_data["_id"]},
                {
                    "$set": {
                        "embedding": embedding,
                        "embedding_model": config.EMBEDDING_MODEL,
                        "embedding_updated_at": now,
                        "needs_embedding_update": False,
                    }
                }
            )
            
            if update_result.modified_count > 0:
                stats["indexed"] += 1
                logger.debug(f"Indexed: {file_name}")
            else:
                stats["unchanged"] += 1
            
            # Rate limiting
            await asyncio.sleep(RATE_LIMIT_DELAY)
            
        except EmbeddingError as e:
            stats["errors"] += 1
            logger.warning(f"Embedding error for {file_name}: {e}")
        except Exception as e:
            stats["errors"] += 1
            logger.error(f"Unexpected error for {file_name}: {e}")


async def index_all_files(dry_run: bool = False) -> Dict[str, int]:
    """אינדוקס כל הקבצים שצריכים embedding."""
    from database import db
    
    stats = {
        "total": 0,
        "indexed": 0,
        "skipped_empty": 0,
        "unchanged": 0,
        "errors": 0,
    }
    
    logger.info("Starting embedding indexing...")
    
    # שאילתה לכל הקבצים שצריכים embedding
    query = {
        "$or": [
            {"embedding": {"$exists": False}},
            {"embedding": None},
            {"needs_embedding_update": True},
        ],
        "is_active": {"$ne": False},
    }
    
    # ספירה
    try:
        total = db.manager.collection.count_documents(query)
        stats["total"] = total
        logger.info(f"Found {total} files to index")
    except Exception as e:
        logger.error(f"Failed to count documents: {e}")
        return stats
    
    if dry_run:
        logger.info("Dry run - not making changes")
        return stats
    
    # עיבוד ב-batches
    cursor = db.manager.collection.find(
        query,
        # Include code for embedding, but exclude heavy fields we don't need
        projection={
            "_id": 1,
            "user_id": 1,
            "file_name": 1,
            "code": 1,
            "description": 1,
            "tags": 1,
            "programming_language": 1,
        }
    ).batch_size(BATCH_SIZE)
    
    batch: List[Dict[str, Any]] = []
    batch_num = 0
    
    for doc in cursor:
        batch.append(doc)
        
        if len(batch) >= BATCH_SIZE:
            batch_num += 1
            logger.info(f"Processing batch {batch_num} ({len(batch)} files)...")
            await process_batch(batch, db, stats)
            batch = []
    
    # עיבוד batch אחרון
    if batch:
        batch_num += 1
        logger.info(f"Processing final batch {batch_num} ({len(batch)} files)...")
        await process_batch(batch, db, stats)
    
    logger.info(
        f"Indexing complete. "
        f"Total: {stats['total']}, "
        f"Indexed: {stats['indexed']}, "
        f"Errors: {stats['errors']}"
    )
    
    return stats


def main():
    """Entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Index embeddings for existing files")
    parser.add_argument("--dry-run", action="store_true", help="Don't make changes")
    args = parser.parse_args()
    
    # בדיקת API key
    if not os.getenv("OPENAI_API_KEY") and not getattr(config, "OPENAI_API_KEY", ""):
        logger.error("OPENAI_API_KEY not set!")
        sys.exit(1)
    
    # הרצה
    stats = asyncio.run(index_all_files(dry_run=args.dry_run))
    
    # Exit code לפי הצלחה
    if stats["errors"] > stats["indexed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
```

### 5.2 הוספת Hook לאינדוקס אוטומטי בשמירה

עדכן את `save_code_snippet` ב-`database/repository.py` להוספת אינדוקס אסינכרוני:

```python
# בסוף הפונקציה save_code_snippet, אחרי ה-insert הצליח:

if result.inserted_id:
    # ... (קוד cache invalidation קיים)
    
    # ===== אינדוקס embedding אסינכרוני =====
    if getattr(config, "SEMANTIC_SEARCH_INDEX_ON_SAVE", False):
        try:
            self._schedule_embedding_update(snippet)
        except Exception:
            pass  # לא נכשיל שמירה בגלל embedding
    
    return True

def _schedule_embedding_update(self, snippet: CodeSnippet) -> None:
    """תזמון עדכון embedding ברקע."""
    import threading
    
    def _worker():
        try:
            from services.embedding_service import generate_embedding_sync
            
            text = f"File: {snippet.file_name}\n"
            if snippet.programming_language:
                text += f"Language: {snippet.programming_language}\n"
            if snippet.description:
                text += f"Description: {snippet.description}\n"
            text += f"Code:\n{snippet.code[:2000]}"
            
            embedding = generate_embedding_sync(text)
            
            # עדכון ב-DB
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            
            self.manager.collection.update_one(
                {"user_id": snippet.user_id, "file_name": snippet.file_name},
                {
                    "$set": {
                        "embedding": embedding,
                        "embedding_model": getattr(config, "EMBEDDING_MODEL", "text-embedding-3-small"),
                        "embedding_updated_at": now,
                        "needs_embedding_update": False,
                    }
                },
                sort=[("version", -1)],
            )
        except Exception as e:
            logger.debug(f"Background embedding update failed: {e}")
    
    threading.Thread(target=_worker, daemon=True).start()
```

---

## 🔎 שלב 6: עדכון מנוע החיפוש

### 6.1 הוספת חיפוש סמנטי ל-`search_engine.py`

מצא את הקובץ `search_engine.py` והוסף את המתודה `_semantic_search`:

```python
# הוסף import בראש הקובץ:
from typing import Any, Dict, List, Optional, Set, Tuple, cast

# מצא את הפונקציה search ועדכן את ה-elif:
# (בתוך המתודה search של AdvancedSearchEngine)

elif search_type == SearchType.SEMANTIC:
    candidates = self._semantic_search(query, user_id, limit)

# הוסף את המתודה החדשה:
def _semantic_search(
    self,
    query: str,
    user_id: int,
    limit: int = 50,
) -> List[SearchResult]:
    """חיפוש סמנטי באמצעות embeddings."""
    from config import config
    
    # בדיקה שהפיצ'ר מופעל
    if not getattr(config, "SEMANTIC_SEARCH_ENABLED", False):
        logger.warning("Semantic search is disabled, falling back to text search")
        index = self.get_index(user_id)
        return self._text_search(query, index, user_id)
    
    try:
        # יצירת embedding לשאילתה
        import asyncio
        from services.embedding_service import generate_embedding
        
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, generate_embedding(query))
                    query_embedding = future.result(timeout=15)
            else:
                query_embedding = loop.run_until_complete(generate_embedding(query))
        except Exception:
            query_embedding = asyncio.run(generate_embedding(query))
        
        # הרצת Vector Search ב-MongoDB
        pipeline = [
            {
                "$vectorSearch": {
                    "index": "code_snippets_vector_index",
                    "path": "embedding",
                    "queryVector": query_embedding,
                    "numCandidates": limit * 10,  # יותר candidates לדיוק טוב יותר
                    "limit": limit,
                    "filter": {
                        "user_id": user_id,
                        "is_active": {"$ne": False},
                    }
                }
            },
            {
                "$project": {
                    "_id": 1,
                    "file_name": 1,
                    "code": 1,
                    "programming_language": 1,
                    "tags": 1,
                    "description": 1,
                    "created_at": 1,
                    "updated_at": 1,
                    "version": 1,
                    "score": {"$meta": "vectorSearchScore"},
                }
            }
        ]
        
        results_raw = list(db.manager.collection.aggregate(pipeline))
        
        # המרה ל-SearchResult
        results: List[SearchResult] = []
        for doc in results_raw:
            score = float(doc.get("score", 0))
            result = self._create_search_result(doc, query, score)
            results.append(result)
        
        try:
            emit_event(
                "semantic_search_done",
                severity="info",
                user_id=int(user_id),
                results_count=int(len(results)),
            )
        except Exception:
            pass
        
        return results
        
    except Exception as e:
        logger.error(f"Semantic search failed: {e}, falling back to fuzzy search")
        try:
            emit_event("semantic_search_error", severity="error", error=str(e))
        except Exception:
            pass
        
        # Fallback לחיפוש fuzzy
        index = self.get_index(user_id)
        return self._fuzzy_search(query, index, user_id)
```

### 6.2 הוספת פונקציית עזר לחיפוש סמנטי ב-repository

הוסף לקובץ `database/repository.py`:

```python
def semantic_search(
    self,
    user_id: int,
    query_embedding: List[float],
    limit: int = 20,
    programming_language: Optional[str] = None,
) -> List[Dict]:
    """
    חיפוש סמנטי באמצעות Vector Search.
    
    Args:
        user_id: מזהה המשתמש
        query_embedding: וקטור ה-embedding של השאילתה
        limit: מספר תוצאות מקסימלי
        programming_language: סינון לפי שפה (אופציונלי)
    
    Returns:
        רשימת מסמכים ממויינים לפי similarity score
    """
    try:
        # בניית הפילטר
        filter_conditions: Dict[str, Any] = {
            "user_id": user_id,
            "is_active": {"$ne": False},
        }
        if programming_language:
            filter_conditions["programming_language"] = programming_language
        
        pipeline = [
            {
                "$vectorSearch": {
                    "index": "code_snippets_vector_index",
                    "path": "embedding",
                    "queryVector": query_embedding,
                    "numCandidates": limit * 10,
                    "limit": limit,
                    "filter": filter_conditions,
                }
            },
            {
                "$project": {
                    "_id": 1,
                    "file_name": 1,
                    "programming_language": 1,
                    "tags": 1,
                    "description": 1,
                    "updated_at": 1,
                    "version": 1,
                    "score": {"$meta": "vectorSearchScore"},
                    # לא מחזירים code ו-embedding - שדות כבדים
                }
            }
        ]
        
        with track_performance("db_semantic_search"):
            results = list(self.manager.collection.aggregate(pipeline, allowDiskUse=True))
        
        return results
        
    except Exception as e:
        emit_event("db_semantic_search_error", severity="error", error=str(e))
        return []
```

---

## 🌐 שלב 7: עדכון ה-API

### 7.1 יצירת Blueprint חדש או עדכון קיים

צור קובץ `webapp/search_api.py`:

```python
"""
API endpoints לחיפוש (כולל סמנטי).
Search API Blueprint.
"""

from __future__ import annotations

import logging
from flask import Blueprint, jsonify, request, session
from typing import Any, Dict, List, Optional

from config import config

logger = logging.getLogger(__name__)

search_bp = Blueprint('search_api', __name__, url_prefix='/api/search')


def _parse_int(val: Optional[str], default: int, lo: int, hi: int) -> int:
    """Parse integer with bounds."""
    try:
        v = int(val) if val not in (None, "") else default
        return max(lo, min(hi, v))
    except Exception:
        return default


@search_bp.route('', methods=['GET'])
def search_files():
    """
    חיפוש קבצים.
    
    Query params:
        q: שאילתת החיפוש
        type: סוג החיפוש (text, fuzzy, regex, semantic) - ברירת מחדל: text
        language: סינון לפי שפת תכנות
        limit: מספר תוצאות מקסימלי (ברירת מחדל: 20)
    
    Returns:
        JSON עם תוצאות החיפוש
    """
    try:
        user_id = int(session.get('user_id') or 0)
    except Exception:
        user_id = 0
    
    if user_id <= 0:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    
    # פרמטרים
    query = request.args.get('q', '').strip()
    search_type = request.args.get('type', 'text').lower()
    language = request.args.get('language')
    limit = _parse_int(request.args.get('limit'), 20, 1, 100)
    
    if not query:
        return jsonify({"ok": True, "items": [], "total": 0})
    
    try:
        from search_engine import search_engine, SearchType, SearchFilter
        
        # מיפוי סוג חיפוש
        type_map = {
            'text': SearchType.TEXT,
            'fuzzy': SearchType.FUZZY,
            'regex': SearchType.REGEX,
            'semantic': SearchType.SEMANTIC,
            'function': SearchType.FUNCTION,
            'content': SearchType.CONTENT,
        }
        
        st = type_map.get(search_type, SearchType.TEXT)
        
        # בדיקה שסמנטי מופעל
        if st == SearchType.SEMANTIC and not getattr(config, "SEMANTIC_SEARCH_ENABLED", False):
            # Fallback לחיפוש רגיל
            st = SearchType.FUZZY
        
        # הכנת פילטרים
        filters = None
        if language:
            filters = SearchFilter(languages=[language])
        
        # ביצוע החיפוש
        results = search_engine.search(
            user_id=user_id,
            query=query,
            search_type=st,
            filters=filters,
            limit=limit,
        )
        
        # המרה ל-JSON-serializable
        items = []
        for r in results:
            items.append({
                "file_name": r.file_name,
                "programming_language": r.programming_language,
                "tags": r.tags,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                "score": round(r.relevance_score, 4),
                "snippet_preview": r.snippet_preview[:200] if r.snippet_preview else None,
                "is_semantic": st == SearchType.SEMANTIC,
            })
        
        return jsonify({
            "ok": True,
            "items": items,
            "total": len(items),
            "search_type": search_type,
            "semantic_enabled": getattr(config, "SEMANTIC_SEARCH_ENABLED", False),
        })
        
    except Exception as e:
        logger.error(f"Search API error: {e}", exc_info=True)
        return jsonify({"ok": False, "error": "search_failed"}), 500


@search_bp.route('/suggest', methods=['GET'])
def search_suggestions():
    """הצעות להשלמת חיפוש."""
    try:
        user_id = int(session.get('user_id') or 0)
    except Exception:
        user_id = 0
    
    if user_id <= 0:
        return jsonify({"ok": False, "suggestions": []})
    
    partial = request.args.get('q', '').strip()
    limit = _parse_int(request.args.get('limit'), 10, 1, 20)
    
    if len(partial) < 2:
        return jsonify({"ok": True, "suggestions": []})
    
    try:
        from search_engine import search_engine
        suggestions = search_engine.suggest_completions(user_id, partial, limit)
        return jsonify({"ok": True, "suggestions": suggestions})
    except Exception as e:
        logger.error(f"Suggestions error: {e}")
        return jsonify({"ok": True, "suggestions": []})


@search_bp.route('/status', methods=['GET'])
def search_status():
    """סטטוס מערכת החיפוש הסמנטי."""
    try:
        user_id = int(session.get('user_id') or 0)
    except Exception:
        user_id = 0
    
    if user_id <= 0:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    
    from database import db
    
    # ספירת קבצים עם/בלי embedding
    try:
        total = db.manager.collection.count_documents({
            "user_id": user_id,
            "is_active": {"$ne": False},
        })
        indexed = db.manager.collection.count_documents({
            "user_id": user_id,
            "is_active": {"$ne": False},
            "embedding": {"$exists": True, "$ne": None},
        })
    except Exception:
        total, indexed = 0, 0
    
    return jsonify({
        "ok": True,
        "semantic_enabled": getattr(config, "SEMANTIC_SEARCH_ENABLED", False),
        "total_files": total,
        "indexed_files": indexed,
        "indexing_progress": round(indexed / total * 100, 1) if total > 0 else 0,
    })
```

### 7.2 רישום ה-Blueprint ב-`webapp/app.py`

מצא את הקטע שמרשם blueprints והוסף:

```python
# הוסף את ה-import:
from webapp.search_api import search_bp

# ורשום את ה-Blueprint:
app.register_blueprint(search_bp)
```

---

## 🎨 שלב 8: עדכון ה-Frontend

### 8.1 הוספת Toggle לחיפוש סמנטי

עדכן את תבנית החיפוש (למשל `webapp/templates/files.html` או `dashboard.html`):

```html
<!-- בתוך טופס החיפוש -->
<div class="search-container">
    <input type="text" 
           id="search-input" 
           class="search-input" 
           placeholder="חיפוש קבצים..."
           autocomplete="off">
    
    <!-- Toggle חיפוש סמנטי -->
    <div class="semantic-toggle" id="semantic-toggle">
        <label class="toggle-label">
            <input type="checkbox" 
                   id="semantic-checkbox" 
                   {% if semantic_enabled %}{% else %}disabled{% endif %}>
            <span class="toggle-slider"></span>
            <span class="toggle-text">🤖 חיפוש חכם</span>
        </label>
        {% if not semantic_enabled %}
        <span class="toggle-hint">(לא זמין)</span>
        {% endif %}
    </div>
    
    <button type="submit" class="search-button">🔍</button>
</div>

<!-- CSS -->
<style>
.semantic-toggle {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-left: 12px;
}

.toggle-label {
    display: flex;
    align-items: center;
    cursor: pointer;
    gap: 6px;
}

.toggle-label input {
    display: none;
}

.toggle-slider {
    width: 36px;
    height: 20px;
    background: #ccc;
    border-radius: 10px;
    position: relative;
    transition: background 0.3s;
}

.toggle-slider::after {
    content: '';
    width: 16px;
    height: 16px;
    background: white;
    border-radius: 50%;
    position: absolute;
    top: 2px;
    left: 2px;
    transition: transform 0.3s;
}

.toggle-label input:checked + .toggle-slider {
    background: #4CAF50;
}

.toggle-label input:checked + .toggle-slider::after {
    transform: translateX(16px);
}

.toggle-text {
    font-size: 0.9em;
    color: #666;
}

.toggle-hint {
    font-size: 0.75em;
    color: #999;
}

/* סימון תוצאות סמנטיות */
.search-result.semantic::before {
    content: '🧠';
    margin-left: 4px;
}
</style>
```

### 8.2 JavaScript לחיפוש

```javascript
// search.js או בתוך התבנית

document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('search-input');
    const semanticCheckbox = document.getElementById('semantic-checkbox');
    const resultsContainer = document.getElementById('search-results');
    
    let searchTimeout = null;
    
    // חיפוש עם debounce
    searchInput.addEventListener('input', function() {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => performSearch(), 300);
    });
    
    async function performSearch() {
        const query = searchInput.value.trim();
        if (!query) {
            resultsContainer.innerHTML = '';
            return;
        }
        
        const searchType = semanticCheckbox?.checked ? 'semantic' : 'text';
        
        try {
            const response = await fetch(
                `/api/search?q=${encodeURIComponent(query)}&type=${searchType}&limit=20`
            );
            const data = await response.json();
            
            if (data.ok) {
                renderResults(data.items, searchType === 'semantic');
            }
        } catch (error) {
            console.error('Search error:', error);
        }
    }
    
    function renderResults(items, isSemantic) {
        if (!items.length) {
            resultsContainer.innerHTML = '<p class="no-results">לא נמצאו תוצאות</p>';
            return;
        }
        
        const html = items.map(item => `
            <div class="search-result ${isSemantic ? 'semantic' : ''}">
                <a href="/file/${encodeURIComponent(item.file_name)}">
                    ${escapeHtml(item.file_name)}
                </a>
                <span class="result-meta">
                    ${item.programming_language || ''}
                    ${item.score ? `(${(item.score * 100).toFixed(0)}%)` : ''}
                </span>
                ${item.snippet_preview ? `
                    <div class="snippet-preview">${escapeHtml(item.snippet_preview)}</div>
                ` : ''}
            </div>
        `).join('');
        
        resultsContainer.innerHTML = html;
    }
    
    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }
});
```

---

## 💡 שיפורים מומלצים (Nice to Have)

### 9.1 Hybrid Search (חיפוש היברידי)

במקום Toggle בין חיפוש טקסטואלי לסמנטי, ניתן להריץ את שניהם ולשלב תוצאות:

```python
def _hybrid_search(
    self,
    query: str,
    user_id: int,
    limit: int = 50,
    semantic_weight: float = 0.6,  # משקל לתוצאות סמנטיות
) -> List[SearchResult]:
    """
    חיפוש היברידי: שילוב תוצאות טקסטואליות וסמנטיות.
    מחזיר תוצאות טובות יותר משתי השיטות בנפרד.
    """
    index = self.get_index(user_id)
    
    # הרצת שני סוגי החיפוש
    text_results = self._text_search(query, index, user_id)
    semantic_results = self._semantic_search(query, user_id, limit * 2)
    
    # נרמול ציונים לטווח 0-1
    def _normalize_scores(results: List[SearchResult]) -> Dict[str, float]:
        if not results:
            return {}
        scores = [r.relevance_score for r in results]
        min_score, max_score = min(scores), max(scores)
        score_range = max_score - min_score if max_score > min_score else 1.0
        return {
            r.file_name: (r.relevance_score - min_score) / score_range
            for r in results
        }
    
    text_scores = _normalize_scores(text_results)
    semantic_scores = _normalize_scores(semantic_results)
    
    # שילוב ציונים עם משקלות
    text_weight = 1.0 - semantic_weight
    combined_scores: Dict[str, float] = {}
    all_files = set(text_scores.keys()) | set(semantic_scores.keys())
    
    for file_name in all_files:
        text_score = text_scores.get(file_name, 0.0)
        semantic_score = semantic_scores.get(file_name, 0.0)
        combined_scores[file_name] = (
            text_weight * text_score + 
            semantic_weight * semantic_score
        )
    
    # מיון לפי ציון משולב
    sorted_files = sorted(combined_scores.items(), key=lambda x: x[1], reverse=True)
    
    # בניית תוצאות
    results_map = {r.file_name: r for r in text_results + semantic_results}
    final_results = []
    for file_name, score in sorted_files[:limit]:
        if file_name in results_map:
            result = results_map[file_name]
            result.relevance_score = score
            final_results.append(result)
    
    return final_results
```

**יתרונות:**
- מוצא תוצאות גם לפי מילים מדויקות וגם לפי משמעות
- מפחית False Negatives
- חווית משתמש טובה יותר

### 9.2 חיתוך לפי Tokens (TikToken)

במקום לחתוך לפי תווים (שעלול להיות אגרסיבי מדי בעברית), השתמש ב-tiktoken:

```python
# הוסף ל-embedding_service.py

try:
    import tiktoken
    _TOKENIZER = tiktoken.encoding_for_model("text-embedding-3-small")
except Exception:
    _TOKENIZER = None


def _truncate_by_tokens(text: str, max_tokens: int = 8000) -> str:
    """
    חיתוך טקסט לפי מספר tokens (לא תווים).
    מדויק יותר ומונע חיתוך אגרסיבי מדי.
    
    הערה: text-embedding-3-small מקבל עד 8191 tokens.
    """
    if _TOKENIZER is None:
        # Fallback לחיתוך לפי תווים (פחות מדויק)
        return _truncate_text(text, max_tokens * 4)  # ~4 chars/token average
    
    try:
        tokens = _TOKENIZER.encode(text)
        if len(tokens) <= max_tokens:
            return text
        
        # חיתוך וניסיון לסיים במילה שלמה
        truncated_tokens = tokens[:max_tokens]
        truncated_text = _TOKENIZER.decode(truncated_tokens)
        
        # נסה לחתוך בסוף משפט
        for sep in ["\n\n", "\n", ". "]:
            last_sep = truncated_text.rfind(sep)
            if last_sep > len(truncated_text) * 0.7:
                return truncated_text[:last_sep + len(sep)].strip()
        
        return truncated_text.strip()
        
    except Exception:
        return _truncate_text(text, max_tokens * 4)


# שימוש ב-_prepare_text_for_embedding:
def _prepare_text_for_embedding(...) -> str:
    # ... בניית parts ...
    
    full_text = "\n".join(parts)
    
    # חיתוך לפי tokens (לא תווים!)
    max_tokens = int(getattr(config, "EMBEDDING_MAX_TOKENS", 7500) or 7500)
    return _truncate_by_tokens(full_text, max_tokens)
```

**למה זה חשוב?**
- 2000 תווים בעברית ≈ 4000+ tokens (כל אות עברית = ~2 tokens)
- 2000 תווים באנגלית ≈ 500 tokens
- חיתוך לפי תווים עלול לחתוך יותר מדי מתוכן באנגלית

### 9.3 Message Queue לאינדוקס (Production)

לסביבות Production עמוסות, החלף את ה-Thread ב-Task Queue:

```python
# אופציה 1: Redis Queue (פשוט)
# requirements: rq, redis

from rq import Queue
from redis import Redis

redis_conn = Redis()
embedding_queue = Queue('embeddings', connection=redis_conn)

def _schedule_embedding_update(self, snippet: CodeSnippet) -> None:
    """תזמון עדכון embedding דרך Redis Queue."""
    from tasks.embedding_tasks import update_embedding_task
    
    embedding_queue.enqueue(
        update_embedding_task,
        snippet.user_id,
        snippet.file_name,
        job_timeout='5m',
        retry=3,
    )


# tasks/embedding_tasks.py
def update_embedding_task(user_id: int, file_name: str) -> bool:
    """Task לעדכון embedding של קובץ."""
    from database import db
    from services.embedding_service import generate_embedding_sync
    
    file_data = db.get_latest_version(user_id, file_name)
    if not file_data:
        return False
    
    # ... לוגיקת יצירת embedding ושמירה ...
    return True
```

**מתי להשתמש ב-Queue?**
- יותר מ-100 שמירות בדקה
- Gunicorn עם workers רבים
- צורך ב-retries אמינים
- ניטור ודשבורד של משימות

### 9.4 Batch Embedding API

לאינדוקס מסיבי, השתמש ב-Batch API של OpenAI (חוסך עד 50% בעלויות):

```python
async def generate_embeddings_batch(
    texts: List[str],
    *,
    timeout: float = 30.0,
) -> List[List[float]]:
    """
    יצירת embeddings ל-batch של טקסטים.
    יעיל יותר מקריאות בודדות (עד 2048 טקסטים בבקשה אחת).
    """
    api_key = _get_api_key()
    model = _get_model()
    dimensions = _get_dimensions()
    
    # OpenAI מאפשר עד 2048 inputs בבקשה אחת
    MAX_BATCH = 2048
    
    all_embeddings: List[List[float]] = []
    
    for i in range(0, len(texts), MAX_BATCH):
        batch = texts[i:i + MAX_BATCH]
        
        payload = {
            "model": model,
            "input": [t.strip() for t in batch],
            "dimensions": dimensions,
        }
        
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                _OPENAI_API_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        
        # שמירה על סדר (OpenAI מחזיר index)
        batch_embeddings = [None] * len(batch)
        for item in data["data"]:
            batch_embeddings[item["index"]] = item["embedding"]
        
        all_embeddings.extend(batch_embeddings)
    
    return all_embeddings
```

---

## 🧪 בדיקות

### 9.1 יצירת טסטים לשירות Embeddings

צור קובץ `tests/test_embedding_service.py`:

```python
"""
בדיקות לשירות Embeddings.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import asyncio


@pytest.fixture
def mock_openai_response():
    """Mock response from OpenAI API."""
    return {
        "data": [
            {
                "embedding": [0.1] * 1536,
                "index": 0,
            }
        ],
        "model": "text-embedding-3-small",
        "usage": {"prompt_tokens": 10, "total_tokens": 10},
    }


class TestEmbeddingService:
    """בדיקות לשירות Embeddings."""
    
    @pytest.mark.asyncio
    async def test_generate_embedding_success(self, mock_openai_response):
        """בדיקת יצירת embedding בהצלחה."""
        with patch("services.embedding_service._get_api_key", return_value="test-key"):
            with patch("httpx.AsyncClient") as mock_client:
                mock_response = MagicMock()
                mock_response.json.return_value = mock_openai_response
                mock_response.raise_for_status = MagicMock()
                
                mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                    return_value=mock_response
                )
                
                from services.embedding_service import generate_embedding
                
                result = await generate_embedding("test text")
                
                assert isinstance(result, list)
                assert len(result) == 1536
                assert all(isinstance(x, float) for x in result)
    
    @pytest.mark.asyncio
    async def test_generate_embedding_empty_text(self):
        """בדיקת שגיאה על טקסט ריק."""
        from services.embedding_service import generate_embedding, EmbeddingError
        
        with pytest.raises(EmbeddingError, match="empty_text"):
            await generate_embedding("")
    
    @pytest.mark.asyncio
    async def test_generate_embedding_no_api_key(self):
        """בדיקת שגיאה כשאין API key."""
        with patch("services.embedding_service._get_api_key", return_value=""):
            from services.embedding_service import generate_embedding, EmbeddingError
            
            with pytest.raises(EmbeddingError, match="api_key_missing"):
                await generate_embedding("test")
    
    def test_prepare_text_truncation(self):
        """בדיקת קיצור טקסט ארוך."""
        from services.embedding_service import _truncate_text
        
        long_text = "x" * 5000
        result = _truncate_text(long_text, 2000)
        
        assert len(result) <= 2000
    
    def test_prepare_text_for_embedding(self):
        """בדיקת הכנת טקסט עם מטא-דאטה."""
        from services.embedding_service import _prepare_text_for_embedding
        
        result = _prepare_text_for_embedding(
            code="print('hello')",
            file_name="test.py",
            description="A test file",
            tags=["python", "test"],
            programming_language="python",
        )
        
        assert "File: test.py" in result
        assert "Language: python" in result
        assert "Description: A test file" in result
        assert "print('hello')" in result
```

### 9.2 בדיקות אינטגרציה

צור קובץ `tests/test_semantic_search_integration.py`:

```python
"""
בדיקות אינטגרציה לחיפוש סמנטי.
"""

import pytest
from unittest.mock import patch, MagicMock


class TestSemanticSearchIntegration:
    """בדיקות אינטגרציה לחיפוש סמנטי."""
    
    @pytest.fixture
    def mock_embedding(self):
        """Mock embedding vector."""
        return [0.1] * 1536
    
    def test_search_api_semantic_type(self, client, mock_embedding):
        """בדיקת API עם סוג חיפוש סמנטי."""
        with patch("search_engine.search_engine.search") as mock_search:
            mock_search.return_value = []
            
            response = client.get("/api/search?q=test&type=semantic")
            
            assert response.status_code in (200, 401)  # תלוי באימות
    
    def test_semantic_search_fallback(self, mock_embedding):
        """בדיקת fallback כשסמנטי מושבת."""
        with patch("config.config.SEMANTIC_SEARCH_ENABLED", False):
            from search_engine import search_engine, SearchType
            
            # צריך לעשות fallback לחיפוש אחר
            # (הבדיקה המלאה תלויה במימוש)
    
    def test_embedding_stored_on_save(self, db_fixture, mock_embedding):
        """בדיקה שembedding נשמר בעת שמירת קובץ."""
        with patch("services.embedding_service.generate_embedding_sync", return_value=mock_embedding):
            with patch("config.config.SEMANTIC_SEARCH_INDEX_ON_SAVE", True):
                # שמירת קובץ
                # בדיקה שה-embedding נשמר
                pass
```

---

## 📚 נספחים

### נספח א': עלויות משוערות

| פעולה | עלות משוערת (OpenAI) |
|-------|---------------------|
| אינדוקס 1,000 קבצים | ~$0.02 |
| אינדוקס 10,000 קבצים | ~$0.20 |
| חיפוש יחיד | ~$0.00001 |
| 1,000 חיפושים | ~$0.01 |

**הערה:** העלויות מבוססות על `text-embedding-3-small` במחירי דצמבר 2025.

### נספח ב': מודלים חלופיים

| מודל | מימדים | יתרונות | חסרונות |
|------|--------|---------|---------|
| `text-embedding-3-small` | 1536 | זול, מהיר | דיוק בינוני |
| `text-embedding-3-large` | 3072 | דיוק גבוה | יקר יותר |
| `text-embedding-ada-002` | 1536 | יציב | דור קודם |

### נספח ג': Troubleshooting

| בעיה | פתרון |
|------|-------|
| "vectorSearch index not found" | צור את האינדקס דרך Atlas UI |
| חיפוש סמנטי לא מחזיר תוצאות | בדוק ש-embeddings קיימים ב-DB |
| שגיאת timeout | הגדל את `EMBEDDING_TIMEOUT` |
| "api_key_missing" | הגדר `OPENAI_API_KEY` ב-ENV |
| קובץ שנמחק עדיין מופיע בחיפוש | ודא שהפילטר `is_active: {$ne: False}` קיים |
| עדכון תיאור/תגיות לא משנה תוצאות | ודא שהתיקון בסעיף 3.3 מיושם (בדיקת כל השדות) |

### נספח ד': מחיקת קבצים ו-Embedding

כאשר קובץ נמחק (soft delete), ה-Embedding שלו נשאר ב-DB אך לא מוחזר בחיפוש בזכות הפילטר:

```python
# בשאילתת vectorSearch:
"filter": {
    "user_id": user_id,
    "is_active": {"$ne": False},  # ⬅️ מסנן קבצים מחוקים
}
```

**אימות:** הקוד הקיים ב-`repository.py` כבר משתמש ב-`is_active: False` למחיקה רכה, והפילטר בחיפוש הסמנטי מכסה את זה.

**אופציונלי - ניקוי Embeddings ישנים:**
```python
# scripts/cleanup_deleted_embeddings.py
def cleanup_old_embeddings():
    """מחיקת embeddings של קבצים שנמחקו לפני יותר מ-30 יום."""
    from datetime import datetime, timedelta, timezone
    
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    
    result = db.manager.collection.update_many(
        {
            "is_active": False,
            "deleted_at": {"$lt": cutoff},
            "embedding": {"$exists": True},
        },
        {
            "$unset": {"embedding": "", "embedding_model": "", "embedding_updated_at": ""}
        }
    )
    
    print(f"Cleaned {result.modified_count} old embeddings")
```

### נספח ד': קבצים שנוצרו/עודכנו

**קבצים חדשים:**
- `services/embedding_service.py`
- `webapp/search_api.py`
- `scripts/index_embeddings.py`
- `scripts/create_vector_index.py`
- `tests/test_embedding_service.py`
- `tests/test_semantic_search_integration.py`

**קבצים מעודכנים:**
- `config.py` - הוספת הגדרות
- `database/models.py` - הוספת שדות embedding
- `database/repository.py` - עדכון projection והוספת semantic_search
- `search_engine.py` - הוספת _semantic_search
- `webapp/app.py` - רישום search_bp
- `requirements/base.txt` - הוספת openai

---

## ✅ Checklist למימוש

### שלב בסיסי (MVP)
- [ ] הגדרת `OPENAI_API_KEY` ב-ENV
- [ ] הוספת הגדרות ל-`config.py`
- [ ] יצירת `services/embedding_service.py`
- [ ] עדכון `database/models.py` עם שדות embedding
- [ ] עדכון `database/repository.py` **(כולל בדיקת שינוי בכל השדות!)**
- [ ] יצירת Vector Index ב-MongoDB Atlas
- [ ] הוספת `_semantic_search` ל-`search_engine.py`
- [ ] יצירת `webapp/search_api.py`
- [ ] עדכון Frontend עם toggle
- [ ] הרצת `scripts/index_embeddings.py` לאינדוקס קבצים קיימים
- [ ] כתיבת טסטים
- [ ] בדיקת E2E

### שיפורים מומלצים (אחרי MVP)
- [ ] 🔀 Hybrid Search - שילוב תוצאות טקסט + סמנטי
- [ ] 📊 TikToken - חיתוך לפי tokens במקום תווים
- [ ] 📦 Batch Embedding - אינדוקס יעיל יותר
- [ ] 🔄 Message Queue - לסביבות Production עמוסות
- [ ] 🧹 Cleanup Job - ניקוי embeddings של קבצים מחוקים

---

**נכתב ע"י:** CodeBot Assistant  
**תאריך עדכון אחרון:** דצמבר 2025
