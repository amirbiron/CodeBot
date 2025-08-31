"""
קובץ פשוט לדיווח פעילות - העתק את הקובץ הזה לכל בוט
"""

from datetime import datetime, timezone

from pymongo import MongoClient


class SimpleActivityReporter:
    def __init__(self, mongodb_uri, service_id, service_name=None):
        """
        mongodb_uri: חיבור למונגו (אותו מהבוט המרכזי)
        service_id: מזהה השירות ב-Render
        service_name: שם הבוט (אופציונלי)
        """
        try:
            self.client = MongoClient(mongodb_uri, tz_aware=True, tzinfo=timezone.utc)
            self.db = self.client["render_bot_monitor"]
            self.service_id = service_id
            self.service_name = service_name or service_id
            self.connected = True
        except Exception:
            self.connected = False
            print("⚠️ לא ניתן להתחבר למונגו - פעילות לא תירשם")

    def report_activity(self, user_id):
        """דיווח פעילות פשוט"""
        if not self.connected:
            return

        try:
            now = datetime.now(timezone.utc)

            # עדכון אינטראקציית המשתמש
            self.db.user_interactions.update_one(
                {"service_id": self.service_id, "user_id": user_id},
                {
                    "$set": {"last_interaction": now},
                    "$inc": {"interaction_count": 1},
                    "$setOnInsert": {"created_at": now},
                },
                upsert=True,
            )

            # עדכון פעילות השירות
            self.db.service_activity.update_one(
                {"_id": self.service_id},
                {
                    "$set": {
                        "last_user_activity": now,
                        "service_name": self.service_name,
                        "updated_at": now,
                    },
                    "$setOnInsert": {
                        "created_at": now,
                        "status": "active",
                        "total_users": 0,
                        "suspend_count": 0,
                    },
                },
                upsert=True,
            )

        except Exception as e:
            # אל תעצור את הבוט, אך כן דווח בקצרה
            print(f"⚠️ שגיאה בדיווח פעילות: {e}")


# דוגמה לשימוש קל
def create_reporter(mongodb_uri, service_id, service_name=None):
    """יצירת reporter פשוט"""
    return SimpleActivityReporter(mongodb_uri, service_id, service_name)
