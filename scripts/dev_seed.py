#!/usr/bin/env python3
"""
Seed deterministic data for local development.
- Creates a demo user and several code_snippets with various languages
- Prints IDs to stdout so agents can plug into Postman env

Safety: Only runs against MongoDB pointed by env vars; refuses to run if not localhost unless --allow-nonlocal passed.
"""
import os
import sys
from datetime import datetime, timezone
from pymongo import MongoClient

ALLOWED_PREFIXES = ("mongodb://localhost", "mongodb://127.0.0.1", "mongodb+srv://localhost")


def is_local_mongo(url: str) -> bool:
    if not url:
        return False
    return url.startswith(ALLOWED_PREFIXES) or "localhost" in url or "127.0.0.1" in url


def main():
    allow_nonlocal = "--allow-nonlocal" in sys.argv
    mongo_url = os.getenv("MONGODB_URL", "mongodb://localhost:27017/code_keeper")
    db_name = os.getenv("DATABASE_NAME", "code_keeper_bot")

    if not allow_nonlocal and not is_local_mongo(mongo_url):
        print("Refusing to seed non-local MongoDB. Pass --allow-nonlocal to override.")
        sys.exit(1)

    client = MongoClient(mongo_url, serverSelectionTimeoutMS=5000, tz_aware=True)
    client.server_info()
    db = client[db_name]

    # Demo user
    user_id = 123456
    db.users.update_one(
        {"user_id": user_id},
        {"$set": {
            "user_id": user_id,
            "username": "demo_user",
            "first_name": "Demo",
            "last_name": "User",
            "ui_prefs": {"font_scale": 1.0, "theme": "classic"},
            "updated_at": datetime.now(timezone.utc)
        }, "$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
        upsert=True
    )

    samples = [
        ("hello.py", "python", "def hello():\n    return 'world'\n"),
        ("index.html", "html", "<html><body><h1>Hello</h1></body></html>\n"),
        ("README.md", "markdown", "# Demo\n\n- item 1\n- item 2\n"),
        ("app.js", "javascript", "export function sum(a,b){ return a+b }\n"),
    ]

    inserted_ids = []
    for name, lang, code in samples:
        now = datetime.now(timezone.utc)
        doc = {
            "user_id": user_id,
            "file_name": name,
            "programming_language": lang,
            "code": code,
            "description": f"Seeded example for {name}",
            "tags": ["seed", lang],
            "created_at": now,
            "updated_at": now,
            "is_active": True,
        }
        res = db.code_snippets.insert_one(doc)
        inserted_ids.append(str(res.inserted_id))

    print("Seed completed.")
    print("user_id=", user_id)
    for i, _id in enumerate(inserted_ids, 1):
        print(f"file_id_{i}= {_id}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("Seed failed:", e)
        sys.exit(1)
