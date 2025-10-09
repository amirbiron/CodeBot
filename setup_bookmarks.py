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


def check_mongodb_connection():
    """בדיקת חיבור ל-MongoDB"""
    try:
        from pymongo import MongoClient
        from config import MONGO_URI, MONGO_DB_NAME
        
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.server_info()  # Force connection
        db = client[MONGO_DB_NAME]
        
        logger.info("✅ MongoDB connection successful")
        return db
    except Exception as e:
        logger.error(f"❌ MongoDB connection failed: {e}")
        return None


def setup_bookmarks_collection(db):
    """יצירת collection וindexes לסימניות"""
    try:
        # יצירת collections
        if 'file_bookmarks' not in db.list_collection_names():
            db.create_collection('file_bookmarks')
            logger.info("✅ Created file_bookmarks collection")
        else:
            logger.info("ℹ️ file_bookmarks collection already exists")
        
        if 'bookmark_events' not in db.list_collection_names():
            db.create_collection('bookmark_events')
            logger.info("✅ Created bookmark_events collection")
        else:
            logger.info("ℹ️ bookmark_events collection already exists")
        
        # יצירת indexes
        from database.bookmarks_manager import BookmarksManager
        bm_manager = BookmarksManager(db)
        logger.info("✅ Bookmarks indexes created")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Error setting up collections: {e}")
        return False


def update_webapp_routes():
    """הוספת routes לאפליקציה"""
    webapp_file = Path(__file__).parent / 'webapp' / 'app.py'
    
    if not webapp_file.exists():
        logger.warning("⚠️ webapp/app.py not found - please add routes manually")
        print("""
Please add the following to your webapp/app.py file:

from webapp.bookmarks_api import bookmarks_bp

# Register bookmarks blueprint
app.register_blueprint(bookmarks_bp)

# Add to your get_database_connection function:
def get_database_connection():
    from pymongo import MongoClient
    from config import MONGO_URI, MONGO_DB_NAME
    client = MongoClient(MONGO_URI)
    return client[MONGO_DB_NAME]
        """)
        return False
    
    logger.info("✅ Please add bookmarks blueprint to webapp/app.py manually")
    return True


def update_view_file_template():
    """עדכון template של view_file"""
    template_path = Path(__file__).parent / 'webapp' / 'templates' / 'view_file.html'
    
    if not template_path.exists():
        logger.warning("⚠️ view_file.html not found - please add snippet manually")
        print("""
Please add the following to your view_file.html template:

{% include 'bookmarks_snippet.html' %}

Add it before the closing </body> tag.
        """)
        return False
    
    logger.info("✅ Please add bookmarks snippet to view_file.html manually")
    return True


def create_test_data(db):
    """יצירת נתוני בדיקה"""
    try:
        from database.bookmarks_manager import BookmarksManager
        from bson import ObjectId
        
        bm_manager = BookmarksManager(db)
        
        # יצירת סימניות לדוגמה
        test_user_id = 123456789
        test_file_id = str(ObjectId())
        
        result1 = bm_manager.toggle_bookmark(
            user_id=test_user_id,
            file_id=test_file_id,
            file_name="test_file.py",
            file_path="/test/test_file.py",
            line_number=42,
            line_text="def test_function():",
            note="פונקציית בדיקה חשובה"
        )
        
        result2 = bm_manager.toggle_bookmark(
            user_id=test_user_id,
            file_id=test_file_id,
            file_name="test_file.py",
            file_path="/test/test_file.py",
            line_number=100,
            line_text="return result",
            note="החזרת תוצאה"
        )
        
        if result1['ok'] and result2['ok']:
            logger.info("✅ Test bookmarks created successfully")
            logger.info(f"   Test user ID: {test_user_id}")
            logger.info(f"   Test file ID: {test_file_id}")
            return True
        else:
            logger.error("❌ Failed to create test bookmarks")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error creating test data: {e}")
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
    
    # Step 3: Create test data
    print("\nStep 3: Creating test data...")
    create_test = input("Create test bookmarks? (y/n): ").lower() == 'y'
    if create_test:
        create_test_data(db)
    
    # Step 4: Manual steps
    print("\nStep 4: Manual integration steps:")
    print("-"*40)
    update_webapp_routes()
    update_view_file_template()
    
    # Step 5: Verify
    print("\nStep 5: Verifying installation...")
    if verify_installation():
        print("\n✅ Setup completed successfully!")
        print("\n📝 Next steps:")
        print("1. Add bookmarks blueprint to webapp/app.py")
        print("2. Add bookmarks snippet to view_file.html")
        print("3. Restart the Flask application")
        print("4. Test the bookmarks feature in the browser")
        return 0
    else:
        print("\n⚠️ Setup completed with warnings. Please check the failed items.")
        return 1


if __name__ == "__main__":
    sys.exit(main())