"""
scripts/migrate_custom_themes.py
מיגרציה מ-custom_theme (אובייקט) ל-custom_themes (מערך)
"""

import uuid
from datetime import datetime, timezone

from pymongo import MongoClient

# התחבר ל-DB
client = MongoClient("mongodb://localhost:27017")
db = client.codebot  # שנה לשם ה-DB שלך


def migrate_single_theme_to_array():
    """העבר משתמשים עם custom_theme בודד למבנה המערך החדש."""

    # מצא משתמשים עם המבנה הישן
    users_to_migrate = db.users.find(
        {
            "custom_theme": {"$exists": True},
            "custom_themes": {"$exists": False},
        },
        {"user_id": 1, "custom_theme": 1},
    )

    migrated = 0
    errors = 0

    for user in users_to_migrate:
        try:
            old_theme = user.get("custom_theme")
            if not old_theme:
                continue

            # בנה ערכה חדשה במבנה המערך
            now = datetime.now(timezone.utc)
            new_theme = {
                "id": str(uuid.uuid4()),
                "name": old_theme.get("name", "הערכה שלי"),
                "description": old_theme.get("description", ""),
                "is_active": old_theme.get("is_active", True),
                "created_at": old_theme.get("updated_at", now),
                "updated_at": old_theme.get("updated_at", now),
                "variables": old_theme.get("variables", {}),
            }

            # עדכן את המשתמש
            db.users.update_one(
                {"user_id": user.get("user_id")},
                {
                    "$set": {"custom_themes": [new_theme]},
                    "$unset": {"custom_theme": ""},
                },
            )

            migrated += 1
            print(f"✓ Migrated user {user.get('user_id')}")

        except Exception as e:
            errors += 1
            print(f"✗ Error migrating user {user.get('user_id')}: {e}")

    print("\n=== Migration Complete ===")
    print(f"Migrated: {migrated}")
    print(f"Errors: {errors}")


def verify_migration():
    """בדוק שהמיגרציה הצליחה."""

    # ספור משתמשים עם המבנה הישן
    old_count = db.users.count_documents({"custom_theme": {"$exists": True}})

    # ספור משתמשים עם המבנה החדש
    new_count = db.users.count_documents({"custom_themes": {"$exists": True}})

    print(f"Users with old schema (custom_theme): {old_count}")
    print(f"Users with new schema (custom_themes): {new_count}")

    if old_count == 0:
        print("✓ All users migrated successfully!")
    else:
        print(f"⚠ {old_count} users still need migration")


if __name__ == "__main__":
    print("=== Theme Migration Script ===\n")

    # הרץ מיגרציה
    migrate_single_theme_to_array()

    # אמת
    verify_migration()

