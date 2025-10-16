#!/usr/bin/env python3
"""
Setup script for Bookmarks feature
התקנה והגדרת מערכת הסימניות
"""

import sys
import os
from pathlib import Path
import logging
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Structured events fallback
try:  # type: ignore
    from observability import emit_event  # type: ignore
except Exception:  # pragma: no cover
    def emit_event(event: str, severity: str = "info", **fields):  # type: ignore
        return None


def check_mongodb_connection():
    """בדיקת חיבור ל-MongoDB (ללא תלות ב-config.py)"""
    try:
        from pymongo import MongoClient
        # תמיכה גם בשמות מהאישוז/גיסטים וגם בקוד הפרויקט
        mongo_uri = os.getenv("MONGODB_URL") or os.getenv("MONGO_URI")
        db_name = (
            os.getenv("DATABASE_NAME")
            or os.getenv("MONGO_DB_NAME")
            or "code_keeper_bot"
        )

        if not mongo_uri:
            raise RuntimeError(
                "MONGODB_URL/MONGO_URI לא הוגדר. יש להגדיר משתני סביבה."
            )

        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        client.server_info()  # Force connection
        db = client[db_name]

        logger.info("✅ MongoDB connection successful")
        try:
            emit_event("bookmarks_mongodb_connected", severity="info")
        except Exception:
            pass
        return db
    except Exception as e:
        logger.error(f"❌ MongoDB connection failed: {e}")
        try:
            emit_event("bookmarks_mongodb_connection_failed", severity="error", error=str(e))
        except Exception:
            pass
        return None


def setup_bookmarks_collection(db):
    """יצירת collection וindexes לסימניות"""
    try:
        # יצירת collections
        if 'file_bookmarks' not in db.list_collection_names():
            db.create_collection('file_bookmarks')
            logger.info("✅ Created file_bookmarks collection")
            try:
                emit_event("bookmarks_collection_created", severity="info", name="file_bookmarks")
            except Exception:
                pass
        else:
            logger.info("ℹ️ file_bookmarks collection already exists")
        
        if 'bookmark_events' not in db.list_collection_names():
            db.create_collection('bookmark_events')
            logger.info("✅ Created bookmark_events collection")
            try:
                emit_event("bookmarks_collection_created", severity="info", name="bookmark_events")
            except Exception:
                pass
        else:
            logger.info("ℹ️ bookmark_events collection already exists")
        
        # יצירת indexes
        from database.bookmarks_manager import BookmarksManager
        bm_manager = BookmarksManager(db)
        logger.info("✅ Bookmarks indexes created")
        try:
            emit_event("bookmarks_indexes_created", severity="info")
        except Exception:
            pass
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Error setting up collections: {e}")
        try:
            emit_event("bookmarks_setup_error", severity="error", error=str(e))
        except Exception:
            pass
        return False


def verify_installation():
    """בדיקת התקנה מלאה"""
    checks = {
        'MongoDB Connection': False,
        'Collections Created': False,
        'Indexes Created': False,
        'API Module': False,
        'Frontend Files': False,
    }
    
    # בדיקת MongoDB
    db = check_mongodb_connection()
    if db:
        checks['MongoDB Connection'] = True
        
        # בדיקת collections
        if 'file_bookmarks' in db.list_collection_names():
            checks['Collections Created'] = True
            
            # בדיקת indexes
            indexes = db.file_bookmarks.list_indexes()
            if len(list(indexes)) > 1:  # More than just _id index
                checks['Indexes Created'] = True
    
    # בדיקת קבצי API
    api_file = Path(__file__).parent / 'webapp' / 'bookmarks_api.py'
    if api_file.exists():
        checks['API Module'] = True
    
    # בדיקת קבצי frontend
    js_file = Path(__file__).parent / 'webapp' / 'static' / 'js' / 'bookmarks.js'
    css_file = Path(__file__).parent / 'webapp' / 'static' / 'css' / 'bookmarks.css'
    if js_file.exists() and css_file.exists():
        checks['Frontend Files'] = True
    
    # הצגת תוצאות
    print("\n" + "="*50)
    print("📋 Installation Verification:")
    print("="*50)
    
    all_ok = True
    for check, status in checks.items():
        icon = "✅" if status else "❌"
        print(f"{icon} {check}: {'OK' if status else 'FAILED'}")
        if not status:
            all_ok = False
    
    print("="*50)
    
    if all_ok:
        print("🎉 Installation completed successfully!")
    else:
        print("⚠️ Some checks failed. Please review the logs above.")
    
    return all_ok


def main():
    """Main setup function"""
    print("="*50)
    print("🔖 Bookmarks System Setup")
    print("="*50)
    print()
    
    # Step 1: Check MongoDB
    print("Step 1: Checking MongoDB connection...")
    db = check_mongodb_connection()
    if not db:
        print("❌ Cannot continue without MongoDB connection")
        return 1
    
    # Step 2: Setup collections
    print("\nStep 2: Setting up collections and indexes...")
    if not setup_bookmarks_collection(db):
        print("❌ Failed to setup collections")
        return 1
    
    # Step 3: Verify
    print("\nStep 3: Verifying installation...")
    if verify_installation():
        print("\n✅ Setup completed successfully!")
        print("\n📝 Next steps:")
        print("1. ודא שמשתמש מחובר כדי שה-API יעבוד (session['user_id'])")
        print("2. פתח קובץ וצפה בכפתור הסימניות בצד ימין")
        print("3. בדוק POST ל- /api/bookmarks/<file_id>/toggle")
        return 0
    else:
        print("\n⚠️ Setup completed with warnings. Please check the failed items.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
