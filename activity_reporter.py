"""
קובץ פשוט לדיווח פעילות - העתק את הקובץ הזה לכל בוט
"""
try:
    from pymongo import MongoClient  # type: ignore
    _HAS_PYMONGO = True
except Exception:
    MongoClient = None  # type: ignore
    _HAS_PYMONGO = False
from datetime import datetime, timezone
import atexit

# חיבור MongoDB גלובלי יחיד לכל האפליקציה
_client = None  # type: ignore
_owns_client = False  # האם המודול יצר את הלקוח בעצמו

def get_mongo_client(mongodb_uri: str):
    """החזרת מופע MongoClient יחיד (singleton) לכל האפליקציה.

    בכל קריאה מחזיר את אותו אובייקט, ויוצר רק בפעם הראשונה.
    """
    global _client
    if not _HAS_PYMONGO:
        raise RuntimeError("pymongo not available")
    if _client is None:
        # אם כבר קיים לקוח במסד הנתונים המרכזי – נמחזר אותו, כדי למנוע כפילויות
        try:
            from database import db as _db  # import דינמי כדי להימנע מייבוא מעגלי בזמן טעינה
            existing = getattr(_db, "client", None)
        except Exception:
            existing = None
        if existing is not None:
            # שימוש בלקוח קיים של המערכת (לא אנחנו יוצרים/סוגרים)
            _client = existing
            globals()["_owns_client"] = False
        else:
            # יצירת לקוח משלנו עם timezone-aware
            _client = MongoClient(mongodb_uri, tz_aware=True, tzinfo=timezone.utc)
            globals()["_owns_client"] = True
    return _client

def close_mongo_client() -> None:
    """סגירת החיבור הגלובלי בבטחה בזמן כיבוי השירות."""
    global _client
    try:
        if _client is not None and globals().get("_owns_client", False):
            _client.close()
    finally:
        _client = None

# סגירה אוטומטית ביציאה מהתהליך
atexit.register(close_mongo_client)

try:
    from metrics import note_active_user  # type: ignore
except Exception:  # pragma: no cover
    def note_active_user(user_id: int) -> None:  # type: ignore
        return None

class SimpleActivityReporter:
    def __init__(self, mongodb_uri, service_id, service_name=None):
        """
        mongodb_uri: חיבור למונגו (אותו מהבוט המרכזי)
        service_id: מזהה השירות ב-Render
        service_name: שם הבוט (אופציונלי)
        """
        try:
            if not _HAS_PYMONGO:
                raise RuntimeError("pymongo not available")
            # שימוש ב-singleton של MongoClient כדי למנוע חיבורים מרובים
            self.client = get_mongo_client(mongodb_uri)
            self.db = self.client["render_bot_monitor"]
            self.service_id = service_id
            self.service_name = service_name or service_id
            self.connected = True
        except Exception:
            self.connected = False
            # שקט בסביבת בדיקות/ללא pymongo
            pass
    
    def report_activity(self, user_id):
        """דיווח פעילות פשוט"""
        if not self.connected:
            try:
                # Even if DB is unavailable, update in-memory active users gauge if possible
                note_active_user(int(user_id))
            except Exception:
                pass
            return
        
        try:
            now = datetime.now(timezone.utc)
            
            # עדכון אינטראקציית המשתמש
            self.db.user_interactions.update_one(
                {"service_id": self.service_id, "user_id": user_id},
                {
                    "$set": {"last_interaction": now},
                    "$inc": {"interaction_count": 1},
                    "$setOnInsert": {"created_at": now}
                },
                upsert=True
            )
            
            # עדכון פעילות השירות
            self.db.service_activity.update_one(
                {"_id": self.service_id},
                {
                    "$set": {
                        "last_user_activity": now,
                        "service_name": self.service_name,
                        "updated_at": now
                    },
                    "$setOnInsert": {
                        "created_at": now,
                        "status": "active",
                        "total_users": 0,
                        "suspend_count": 0
                    }
                },
                upsert=True
            )
            # Update active users gauge
            try:
                note_active_user(int(user_id))
            except Exception:
                pass
            
        except Exception:
            # שקט - אל תיכשל את הבוט אם יש בעיה
            pass

# דוגמה לשימוש קל
def create_reporter(mongodb_uri, service_id, service_name=None):
    """יצירת reporter פשוט"""
    return SimpleActivityReporter(mongodb_uri, service_id, service_name)