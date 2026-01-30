"""
Migration script for semantic search.

Run once after deploy to mark snippets for processing and create base indexes.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from motor.motor_asyncio import AsyncIOMotorClient

# Add project root to sys.path
ROOT_DIR = str(Path(__file__).resolve().parents[1])
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from config import config  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BATCH_SIZE = 100


def _get_db():
    mongo_url = getattr(config, "MONGODB_URL", None) or os.getenv("MONGODB_URL")
    db_name = getattr(config, "DATABASE_NAME", None) or os.getenv(
        "DATABASE_NAME", "code_keeper_bot"
    )
    if not mongo_url:
        raise RuntimeError("MONGODB_URL is not configured")
    client = AsyncIOMotorClient(mongo_url)
    return client[db_name]


async def _get_files_collection(db):
    collections = await db.list_collection_names()
    if "code_snippets" in collections:
        return db.code_snippets
    if "files" in collections:
        return db.files
    return db.code_snippets


async def migrate_snippets():
    """Mark existing snippets for semantic processing."""
    logger.info("Starting semantic search migration...")
    db = _get_db()
    files_collection = await _get_files_collection(db)

    total = await files_collection.count_documents({})
    logger.info("Total snippets to migrate: %s", total)

    result = await files_collection.update_many(
        {"needs_embedding": {"$exists": False}},
        {
            "$set": {
                "needs_embedding": True,
                "needs_chunking": True,
                "chunkCount": 0,
                "embeddingUpdatedAt": None,
            }
        },
    )
    logger.info("Marked %s snippets for processing", result.modified_count)

    collections = await db.list_collection_names()
    if "snippet_chunks" not in collections:
        await db.create_collection("snippet_chunks")
        logger.info("Created snippet_chunks collection")

    await db.snippet_chunks.create_index([("userId", 1), ("snippetId", 1)])
    await db.snippet_chunks.create_index([("userId", 1), ("language", 1)])

    logger.info("Created basic indexes on snippet_chunks")
    logger.info("Migration complete!")
    logger.info("")
    logger.info("IMPORTANT: Create the following indexes in MongoDB Atlas UI:")
    logger.info("1. Search Index 'default' on snippet_chunks")
    logger.info("2. Vector Search Index 'vector_index' on snippet_chunks")
    logger.info("")
    logger.info("The embedding worker will process snippets in the background")


async def check_migration_status():
    """Check migration status."""
    db = _get_db()
    files_collection = await _get_files_collection(db)

    total = await files_collection.count_documents({})
    pending = await files_collection.count_documents({"needs_embedding": True})
    processed = await files_collection.count_documents(
        {"needs_embedding": False, "chunkCount": {"$gt": 0}}
    )
    chunks = await db.snippet_chunks.count_documents({})

    logger.info("Migration Status:")
    logger.info("  Total snippets: %s", total)
    logger.info("  Pending processing: %s", pending)
    logger.info("  Processed: %s", processed)
    logger.info("  Total chunks: %s", chunks)

    if total and pending > 0:
        logger.info("  Progress: %.1f%%", (processed / total) * 100)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        asyncio.run(check_migration_status())
    else:
        asyncio.run(migrate_snippets())
