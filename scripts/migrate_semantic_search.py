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


def _create_chunk_index() -> None:
    """יוצר את האינדקס על ``snippet_chunks`` דרך ``safe_create_index``.

    למה לא ``create_index`` ישיר: ההרצה הראשונה של הסקריפט (לפני האישו הזה)
    יצרה את אותם מפתחות בשם ברירת המחדל ``userId_1_snippetId_1``. יצירה חוזרת
    בשם החדש הייתה נופלת על ``IndexOptionsConflict`` ועוצרת את המיגרציה —
    ``safe_create_index`` מזהה אינדקס **זהה** בשם אחר ומדלג.

    זו גם אותה נקודת אמת שבה ``DatabaseManager._create_indexes`` משתמש, כדי
    ששני מסלולי האתחול לא ייסחפו זה מזה.

    הסקריפט אסינכרוני (motor), ו-``safe_create_index`` סינכרוני (pymongo),
    ולכן נפתח כאן לקוח סינכרוני קצר-חיים רק לצעד הזה. ה-shim מספק את
    ``self.db`` היחיד שהמתודה נוגעת בו — אותה תבנית שכבר קיימת ב-
    ``_create_indexes`` לתאימות טסטים.
    """
    from types import SimpleNamespace

    from pymongo import ASCENDING, MongoClient

    from database.manager import DatabaseManager

    mongo_url = getattr(config, "MONGODB_URL", None) or os.getenv("MONGODB_URL")
    db_name = getattr(config, "DATABASE_NAME", None) or os.getenv(
        "DATABASE_NAME", "code_keeper_bot"
    )
    client = MongoClient(mongo_url)
    try:
        DatabaseManager.safe_create_index(
            SimpleNamespace(db=client[db_name]),
            "snippet_chunks",
            [("userId", ASCENDING), ("snippetId", ASCENDING)],
            name="snippet_chunks_user_snippet_idx",
        )
    finally:
        client.close()


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

    # אינדקס על ``language`` אינו נוצר: אף שאילתה ב-B-tree לא מסננת לפיו
    # (הסינון לפי שפה קורה בתוך אינדקסי Atlas Search/Vector Search).
    await asyncio.to_thread(_create_chunk_index)

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

    from services.chunking_service import CHUNKER_VERSION  # noqa: E402

    # כל המונים על אותה אוכלוסייה — קבצים פעילים. ``total`` על כל המסמכים
    # (כולל סל המיחזור) מול ``processed`` על הפעילים בלבד היה מציג התקדמות
    # שלעולם אינה מגיעה ל-100%.
    total = await files_collection.count_documents({"is_active": True})
    pending = await files_collection.count_documents(
        {"is_active": True, "needs_embedding": True}
    )
    # "עובד" נמדד לפי ``chunkerVersion`` ולא לפי ``chunkCount > 0``: קובץ
    # שכל הצ'אנקים שלו סוננו כחסרי משמעות (dump של מספרים) מסתיים עם 0
    # צ'אנקים והוא מטופל לגמרי — לפי המדד הישן הוא היה נראה "ממתין" לנצח.
    processed = await files_collection.count_documents(
        {"is_active": True, "chunkerVersion": CHUNKER_VERSION}
    )
    stale_chunker = await files_collection.count_documents(
        {"is_active": True, "chunkerVersion": {"$ne": CHUNKER_VERSION}}
    )
    chunks = await db.snippet_chunks.count_documents({})
    # מסמך בלי השדה ``is_active`` **אינו** נספר כאן, וגם ``get_snippets_needing_processing``
    # לא ישלוף אותו (הוא מסנן ``is_active: True`` בדיוק). כלומר קובץ כזה שקוף
    # לשני הצדדים, והסטטוס היה יכול להציג 100% בזמן שהוא מעולם לא עובד.
    # נמדד בפרודקשן: 0 מסמכים כאלה מתוך 1,157 — ולכן זו לא נורמליזציה של
    # נתונים אלא מונה שמונע מהפער להסתתר אם הוא כן ייווצר.
    invisible = await files_collection.count_documents({"is_active": {"$exists": False}})

    logger.info("Migration Status:")
    logger.info("  Active snippets: %s", total)
    logger.info("  Pending processing: %s", pending)
    logger.info("  Processed (chunker v%s): %s", CHUNKER_VERSION, processed)
    logger.info("  Awaiting re-chunking: %s", stale_chunker)
    logger.info("  Total chunks: %s", chunks)

    if invisible:
        logger.warning(
            "  Snippets with no is_active field (invisible to the worker): %s", invisible
        )

    if total:
        logger.info("  Progress: %.1f%% (active snippets)", (processed / total) * 100)
        if invisible:
            logger.warning(
                "  Progress above EXCLUDES the %s snippets with no is_active field", invisible
            )

    # ספירת יתומים — אותה הגדרה בדיוק שהג'וב משתמש בה, בלי למחוק דבר.
    try:
        from services.snippet_chunks_janitor import cleanup_orphan_snippet_chunks

        report = await asyncio.to_thread(cleanup_orphan_snippet_chunks, dry_run=True)
        if report.get("ok"):
            logger.info("  Orphan snippets with chunks: %s", report.get("orphan_snippets", 0))
            if report.get("skipped_non_objectid"):
                logger.warning(
                    "  Chunk groups with a non-ObjectId snippetId (skipped): %s",
                    report.get("skipped_non_objectid"),
                )
        else:
            logger.warning("  Orphan scan did not complete: %s", report.get("reason"))
    except Exception as exc:  # pragma: no cover - כלי תחזוקה, לא מסלול ריצה
        logger.warning("  Orphan scan failed: %s", exc)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        asyncio.run(check_migration_status())
    else:
        asyncio.run(migrate_snippets())
