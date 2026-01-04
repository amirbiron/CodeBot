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
from typing import Any, Dict, List

# הוסף את ה-root לנתיב
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config  # noqa: E402

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
        file_name = file_data.get("file_name", "unknown")

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
                },
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
        },
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
    _ = time.time()
    stats = asyncio.run(index_all_files(dry_run=args.dry_run))

    # Exit code לפי הצלחה
    if stats["errors"] > stats["indexed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()

