"""
סקריפט ליצירת Vector Index ב-MongoDB Atlas.
"""

import os
import sys

# הוסף את ה-root לנתיב
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import MongoClient  # noqa: E402
from config import config  # noqa: E402


def create_vector_index():
    """יצירת Vector Search Index."""
    client = MongoClient(config.MONGODB_URL)
    db = client[config.DATABASE_NAME]
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
                    "similarity": "cosine",
                },
                {"type": "filter", "path": "user_id"},
                {"type": "filter", "path": "is_active"},
                {"type": "filter", "path": "programming_language"},
            ]
        },
    }

    _ = collection  # keep for clarity; index is created via Atlas UI/Admin API.
    print("Creating vector index...")
    print("Note: This must be done via Atlas UI or Atlas Admin API")
    print("Index definition:")
    import json

    print(json.dumps(index_definition, indent=2))


if __name__ == "__main__":
    create_vector_index()

