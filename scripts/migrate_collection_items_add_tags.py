"""
Migration: add empty tags field to existing collection_items.
"""
from __future__ import annotations

from services.db_provider import get_db
from database.collections_manager import CollectionsManager


def migrate_existing_items_add_tags_field() -> None:
    """הוספת שדה tags ריק לפריטים קיימים."""
    mgr = CollectionsManager(get_db())
    result = mgr.db.collection_items.update_many(  # type: ignore[attr-defined]
        {"tags": {"$exists": False}},
        {"$set": {"tags": []}},
    )
    updated = int(getattr(result, "modified_count", 0) or 0)
    print(f"Updated {updated} items with empty tags field")


if __name__ == "__main__":
    migrate_existing_items_add_tags_field()
