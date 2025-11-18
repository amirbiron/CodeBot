# -*- coding: utf-8 -*-
import importlib


def _python_block_code() -> str:
    return '''"""
Mongo Distributed Lock - prevent telegram.error.Conflict

רעיון:
- קולקציה אחת bot_locks
- SERVICE_ID מי נועל, INSTANCE_ID מי מריץ
- לוק יש expiresAt + TTL לנעילות יתומות
"""

import os, asyncio
from datetime import datetime, timedelta
from pymongo import MongoClient, ReturnDocument

URI = os.getenv("MONGODB_URI")
SERVICE_ID = os.getenv("SERVICE_ID", "codebot-prod")
INSTANCE_ID = os.getenv("RENDER_INSTANCE_ID", "local")
LEASE = int(os.getenv("LOCK_LEASE_SECONDS", "60"))
RETRY = int(os.getenv("LOCK_RETRY_SECONDS", "20"))

col = MongoClient(URI)["codebot"]["bot_locks"]
col.create_index("expiresAt", expireAfterSeconds=0)

async def acquire_lock():
    """רכישת לוק – חוזר רק כשהאינסטנס הוא הבעלים."""
    while True:
        now = datetime.utcnow()
        exp = now + timedelta(seconds=LEASE)

        doc = col.find_one_and_update(
            {
                "_id": SERVICE_ID,
                "$or": [
                    {"expiresAt": {"$lte": now}},   # תפוס אבל פג תוקף
                    {"owner": INSTANCE_ID},           # חידוש
                ],
            },
            {"$set": {"owner": INSTANCE_ID, "expiresAt": exp, "updatedAt": now}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )

        if doc["owner"] == INSTANCE_ID:
            print(f"lock by {INSTANCE_ID} until {exp}")
            return

        print(f"held by {doc['owner']} - retry in {RETRY}s")
        await asyncio.sleep(RETRY)

async def heartbeat():
    """שמירת בעלות – רענון expiresAt. מאבד? יוצא."""
    interval = max(5, int(LEASE * 0.4))

    while True:
        await asyncio.sleep(interval)
        now = datetime.utcnow()
        exp = now + timedelta(seconds=LEASE)

        doc = col.find_one_and_update(
            {"_id": SERVICE_ID, "owner": INSTANCE_ID},
            {"$set": {"expiresAt": exp, "updatedAt": now}},
            return_document=ReturnDocument.AFTER,
        )

        if not doc:
            print("lost lock - exit")
            os._exit(0)

        print(f"heartbeat -> {exp}")

async def main():
    await acquire_lock()
    asyncio.create_task(heartbeat())

    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    await application.updater.idle()

if __name__ == "__main__":
    asyncio.run(main())
'''


def test_cp_detects_markdown_for_md_with_markdown_content():
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor
    # Markdown טיפוסי
    md_text = "# כותרת\n\n- פריט\n- נוסף\n\nקישור: [דוגמה](https://example.com)\n"
    out = cp.detect_language(md_text, filename="doc.md")
    assert out == 'markdown'


def test_cp_md_with_pure_python_content_is_not_text():
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor
    code = _python_block_code()
    out = cp.detect_language(code, filename="Block.md")
    # לפי היישום הנוכחי: סיומת גוברת → markdown; לכל הפחות לא 'text'
    assert out in {'markdown', 'python'}


def test_service_md_with_pure_python_content_is_not_text():
    svc = importlib.import_module('services.code_service')
    code = _python_block_code()
    out = svc.detect_language(code, filename="Block.md")
    assert out in {'markdown', 'python'}


def test_cp_shebang_python_without_extension():
    mod = importlib.import_module('code_processor')
    cp = mod.code_processor
    code = "#!/usr/bin/env python3\nprint('hello')\n"
    out = cp.detect_language(code, filename="run")
    assert out == 'python'
