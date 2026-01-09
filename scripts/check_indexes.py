#!/usr/bin/env python3
"""
סקריפט זמני לבדיקת מצב האינדקסים ב-MongoDB

הערה: ניתן להריץ את הבדיקות האלה גם דרך ה-Admin Endpoints:
- /admin/verify-indexes - בדיקה מקיפה של כל האינדקסים
- /admin/create-users-index - יצירת אינדקס על users.user_id
- /admin/create-job-trigger-index - יצירת אינדקס על job_trigger_requests.status
"""
import json
import os
import sys

def main():
    # Try to load environment variables from .env
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    try:
        from bson import json_util
        from services.db_provider import get_db
    except ImportError as e:
        print(f"❌ חסרות תלויות: {e}")
        print("\nכדי להריץ את הסקריפט, התקן את התלויות:")
        print("  pip install pymongo python-dotenv")
        print("\nאו השתמש ב-Admin Endpoints:")
        print("  /admin/verify-indexes")
        sys.exit(1)
    
    db = get_db()
    # אם קיבלנו No-Op DB (למשל בלי MONGODB_URL / DISABLE_DB) - זה לא מצב שימושי לסקריפט
    try:
        if getattr(db, "name", "") == "noop_db":
            raise RuntimeError("noop_db")
    except Exception:
        print("❌ לא התחברתי ל-MongoDB (קיבלתי noop DB).")
        print("\nודא ש-MONGODB_URL מוגדר בסביבה או בקובץ .env וש-DISABLE_DB לא פעיל")
        print("\nאו השתמש ב-Admin Endpoints מתוך האפליקציה:")
        print("  /admin/verify-indexes")
        sys.exit(1)
    
    print("=" * 60)
    print("1. בדיקת פעולות בניית אינדקסים פעילות")
    print("=" * 60)
    
    # Check for active index builds
    try:
        current_ops = db.command({
            "currentOp": 1,
            "command.createIndexes": {"$exists": True}
        })
        if current_ops.get("inprog"):
            print(f"⏳ נמצאו {len(current_ops['inprog'])} פעולות בנייה פעילות:")
            for op in current_ops["inprog"]:
                print(json.dumps(json.loads(json_util.dumps(op)), indent=2, ensure_ascii=False))
        else:
            print("✅ אין פעולות בניית אינדקסים פעילות כרגע")
    except Exception as e:
        print(f"❌ שגיאה בבדיקת currentOp: {e}")
    
    print("\n" + "=" * 60)
    print("2. אינדקסים בקולקשן users")
    print("=" * 60)
    
    try:
        users_indexes = list(db.users.list_indexes())
        print(f"נמצאו {len(users_indexes)} אינדקסים:")
        for idx in users_indexes:
            print(json.dumps(json.loads(json_util.dumps(idx)), indent=2, ensure_ascii=False))
        
        # Check specifically for user_id index
        has_user_id_idx = any("user_id" in str(idx.get("key", {})) for idx in users_indexes)
        if has_user_id_idx:
            print("\n✅ קיים אינדקס על user_id")
        else:
            print("\n⚠️ לא נמצא אינדקס על user_id!")
            print("   לתיקון: /admin/create-users-index")
    except Exception as e:
        print(f"❌ שגיאה בקריאת אינדקסים מ-users: {e}")
    
    print("\n" + "=" * 60)
    print("3. אינדקסים בקולקשן note_reminders")
    print("=" * 60)
    
    try:
        reminders_indexes = list(db.note_reminders.list_indexes())
        print(f"נמצאו {len(reminders_indexes)} אינדקסים:")
        for idx in reminders_indexes:
            print(json.dumps(json.loads(json_util.dumps(idx)), indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"❌ שגיאה בקריאת אינדקסים מ-note_reminders: {e}")
    
    print("\n" + "=" * 60)
    print("4. בונוס: אינדקסים בקולקשן job_trigger_requests")
    print("=" * 60)
    
    try:
        job_trigger_indexes = list(db.job_trigger_requests.list_indexes())
        print(f"נמצאו {len(job_trigger_indexes)} אינדקסים:")
        for idx in job_trigger_indexes:
            print(json.dumps(json.loads(json_util.dumps(idx)), indent=2, ensure_ascii=False))
        
        # Check for status index
        has_status_idx = any("status" in str(idx.get("key", {})) for idx in job_trigger_indexes)
        if has_status_idx:
            print("\n✅ קיים אינדקס על status")
        else:
            print("\n⚠️ לא נמצא אינדקס על status!")
            print("   לתיקון: /admin/create-job-trigger-index")
    except Exception as e:
        print(f"❌ שגיאה בקריאת אינדקסים מ-job_trigger_requests: {e}")
    
    print("\n" + "=" * 60)
    print("5. בונוס: אינדקסים בקולקשן code_snippets")
    print("=" * 60)
    
    try:
        snippets_indexes = list(db.code_snippets.list_indexes())
        print(f"נמצאו {len(snippets_indexes)} אינדקסים:")
        for idx in snippets_indexes:
            print(json.dumps(json.loads(json_util.dumps(idx)), indent=2, ensure_ascii=False))
        
        # Check for is_active + created_at compound index
        has_active_idx = any(
            "is_active" in str(idx.get("key", {})) and "created_at" in str(idx.get("key", {}))
            for idx in snippets_indexes
        )
        if has_active_idx:
            print("\n✅ קיים אינדקס מורכב על is_active + created_at")
        else:
            print("\n⚠️ לא נמצא אינדקס מורכב על is_active + created_at!")
            print("   לתיקון: /admin/force-index-creation")
    except Exception as e:
        print(f"❌ שגיאה בקריאת אינדקסים מ-code_snippets: {e}")


if __name__ == "__main__":
    main()
