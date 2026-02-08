from __future__ import annotations

from datetime import datetime
from typing import List

from bson import ObjectId

# Semantic fields for code snippets
SNIPPET_SEMANTIC_FIELDS = {
    # Metadata embedding (title + description + tags)
    "snippetEmbedding": List[float],  # 768 or 1536 dimensions

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
}

# Schema for semantic chunks collection
SNIPPET_CHUNK_SCHEMA = {
    "_id": ObjectId,
    "userId": int,  # user identifier (security filter)
    "snippetId": ObjectId,  # reference to the original snippet
    "language": str,

    # Chunk content
    "chunkIndex": int,  # chunk index (0, 1, 2...)
    "codeChunk": str,  # code content (up to ~220 lines)
    "startLine": int,  # start line in original file
    "endLine": int,  # end line

    # Embedding
    "chunkEmbedding": List[float],  # vector 768/1536 dimensions
    # Embedding metadata
    "embeddingModelKey": str,
    "embeddingModel": str,
    "embeddingApiVersion": str,
    "embeddingDim": int,

    # Metadata
    "createdAt": datetime,
    "updatedAt": datetime,
}
