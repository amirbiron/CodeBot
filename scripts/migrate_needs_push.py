#!/usr/bin/env python3
"""
Migration script: Add needs_push field to existing note_reminders.

This script updates all existing documents in note_reminders collection
to add the needs_push field based on the old timestamp logic:
- needs_push: False if last_push_success_at >= remind_at (already pushed)
- needs_push: True otherwise (needs to be pushed)

Run this script AFTER deployment to speed up queries by eliminating
the backward-compatibility $expr clause for old documents.

Usage:
    python scripts/migrate_needs_push.py [--dry-run]

Options:
    --dry-run    Show what would be updated without making changes
"""
import os
import sys

def main():
    dry_run = "--dry-run" in sys.argv
    
    # Load environment
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    
    try:
        from services.db_provider import get_db
    except ImportError as e:
        print(f"❌ חסרות תלויות: {e}")
        print("\nהרץ מתוך תיקיית הפרויקט:")
        print("  cd /path/to/project && python scripts/migrate_needs_push.py")
        sys.exit(1)
    
    db = get_db()
    try:
        if getattr(db, "name", "") == "noop_db":
            raise RuntimeError("noop_db")
    except Exception:
        print("❌ לא ניתן להתחבר ל-MongoDB (קיבלתי noop DB).")
        print("   ודא ש-MONGODB_URL מוגדר בסביבה וש-DISABLE_DB לא פעיל")
        sys.exit(1)
    
    collection = db.note_reminders
    
    # Count documents without needs_push
    filter_no_field = {"needs_push": {"$exists": False}}
    total = collection.count_documents(filter_no_field)
    
    if total == 0:
        print("✅ כל המסמכים כבר מכילים needs_push - אין צורך במיגרציה")
        return
    
    print(f"📊 נמצאו {total} מסמכים ללא needs_push")
    
    if dry_run:
        print("\n🔍 מצב dry-run - לא מבצע שינויים")
        
        # Show sample of what would be updated
        sample = list(collection.find(filter_no_field).limit(5))
        for doc in sample:
            remind_at = doc.get("remind_at")
            last_push = doc.get("last_push_success_at")
            
            if last_push and remind_at and last_push >= remind_at:
                new_value = False
            else:
                new_value = True
            
            print(f"  - {doc.get('_id')}: remind_at={remind_at}, last_push={last_push} → needs_push={new_value}")
        
        if total > 5:
            print(f"  ... ועוד {total - 5} מסמכים")
        
        print("\nלהרצה אמיתית, הרץ ללא --dry-run")
        return
    
    # Perform migration in two steps:
    # 1. Set needs_push: False for documents where last_push_success_at >= remind_at
    # 2. Set needs_push: True for all remaining documents without needs_push
    
    print("\n🔄 שלב 1: סימון מסמכים שכבר נשלחו (needs_push: false)...")
    
    # Documents that were already pushed successfully
    result1 = collection.update_many(
        {
            "needs_push": {"$exists": False},
            "last_push_success_at": {"$type": "date"},
            "$expr": {"$gte": ["$last_push_success_at", "$remind_at"]},
        },
        {"$set": {"needs_push": False}}
    )
    print(f"   עודכנו {result1.modified_count} מסמכים עם needs_push: false")
    
    print("\n🔄 שלב 2: סימון מסמכים שצריך לשלוח (needs_push: true)...")
    
    # All remaining documents without needs_push
    result2 = collection.update_many(
        {"needs_push": {"$exists": False}},
        {"$set": {"needs_push": True}}
    )
    print(f"   עודכנו {result2.modified_count} מסמכים עם needs_push: true")
    
    # Verify
    remaining = collection.count_documents(filter_no_field)
    if remaining == 0:
        print(f"\n✅ מיגרציה הושלמה בהצלחה! עודכנו {result1.modified_count + result2.modified_count} מסמכים")
    else:
        print(f"\n⚠️ נותרו {remaining} מסמכים ללא needs_push")


if __name__ == "__main__":
    main()
