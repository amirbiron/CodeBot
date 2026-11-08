from __future__ import annotations

from datetime import datetime

from bson import ObjectId
from bson.binary import Binary

# Semantic fields for code snippets
SNIPPET_SEMANTIC_FIELDS = {
    # Metadata embedding (title + description + tags) — **לא נכתב יותר.** מאז
    # 8.11.2026 ה-worker (``services/embedding_worker.py``) לא שולח את בקשת
    # המטא-דאטה, כי אף קוד בריפו לא קרא את השדה: החיפוש הווקטורי רץ על
    # ``chunkEmbedding`` שלמטה. מסמכים שעובדו לפני כן עדיין נושאים אותו, ולכן
    # הוא נשאר כאן — ההיטלות ממשיכות להחריג אותו (``HEAVY_FIELDS_EXCLUDE_PROJECTION``
    # ב-``database/repository.py``), וה-MCP מנקה אותו (``_SEMANTIC_FIELDS`` ב-
    # ``mcp_server/backend.py``, שחייבת להיות שווה לרשימה הזו).
    "snippetEmbedding": Binary,  # bson.binary.Binary, float32 vector

    # Background processing flags
    "needs_embedding": bool,  # whether embeddings should be recalculated
    "needs_chunking": bool,  # whether chunking should be recalculated

    # Change tracking
    "contentHash": str,  # SHA256 of content to avoid duplicate processing
    "embeddingUpdatedAt": datetime,
    # Embedding version metadata (to avoid mixing vectors)
    "embeddingModelKey": str,  # e.g. "text-embedding-005/768"
    "embeddingModel": str,
    "embeddingApiVersion": str,  # v1beta/v1 (transport)
    "embeddingDim": int,

    # Number of chunks created
    "chunkCount": int,

    # גרסת ה-chunker שהקובץ נחתך לפיה. שדרוג הכלל מעלה את המספר
    # ב-``services/chunking_service.py``, וה-worker מזהה לבד מה צריך
    # לחתוך מחדש — בלי פקודת re-index ידנית.
    "chunkerVersion": int,
}

# Schema for semantic chunks collection
SNIPPET_CHUNK_SCHEMA = {
    "_id": ObjectId,
    "userId": int,  # user identifier (security filter)
    "snippetId": ObjectId,  # reference to the original snippet
    "language": str,

    # Chunk content
    "chunkIndex": int,  # chunk index (0, 1, 2...)
    "codeChunk": str,  # code content, capped by CHUNK_MAX_BYTES (UTF-8 bytes)
    "startLine": int,  # start line in original file
    "endLine": int,  # end line

    # Embedding. נשמר כ-BSON BinData subtype 9 (float32) ולא כמערך doubles
    # (``_to_binary_vector`` ב-``database/manager.py``): מערך שומר ערך של 8 בייט
    # לכל מספר, ועוד שם מפתח ובייט טיפוס לכל איבר — כ-9.9KB לווקטור מול ~3KB
    # בבינארי. Atlas Vector Search קורא את שתי הצורות.
    "chunkEmbedding": Binary,  # bson.binary.Binary, float32 vector
    # Embedding metadata
    "embeddingModelKey": str,
    "embeddingModel": str,
    "embeddingApiVersion": str,
    "embeddingDim": int,

    # Metadata
    "createdAt": datetime,
    "updatedAt": datetime,
}
