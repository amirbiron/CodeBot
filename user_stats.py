import json
import os
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import logging
from database import db as mongodb

logger = logging.getLogger(__name__)

class UserStats:
    def __init__(self):
        # כבר לא צריך קובץ זמני - נשתמש ב-MongoDB
        pass
    
    def log_user(self, user_id, username=None):
        """רישום משתמש ב-MongoDB"""
        try:
            # שמור או עדכן משתמש ב-MongoDB
            mongodb.save_user(user_id, username)
            
            # עדכן את הזמן האחרון שהמשתמש היה פעיל
            users_collection = mongodb.db.users
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            
            # עדכון המשתמש עם פעילות אחרונה
            users_collection.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "last_seen": today,
                        "username": username if username else f"User_{user_id}",
                        "updated_at": datetime.now(timezone.utc)
                    },
                    "$inc": {
                        "total_actions": 1
                    },
                    "$addToSet": {
                        "usage_days": today
                    },
                    "$setOnInsert": {
                        "first_seen": today,
                        "created_at": datetime.now(timezone.utc)
                    }
                },
                upsert=True
            )
        except Exception as e:
            logger.error(f"Error logging user: {e}")
    
    def get_weekly_stats(self):
        """סטטיסטיקת שבוע אחרון מ-MongoDB"""
        try:
            users_collection = mongodb.db.users
            week_ago = datetime.now(timezone.utc) - timedelta(days=7)
            # השוואת ימים תתבצע לפי אובייקטי date כדי להימנע מהשוואת naive מול aware
            week_ago_date = week_ago.date()
            
            # מצא משתמשים פעילים בשבוע האחרון
            active_users = []
            
            # שאילתה למשתמשים שהיו פעילים בשבוע האחרון
            users = users_collection.find({
                "updated_at": {"$gte": week_ago}
            })
            
            for user in users:
                # חשב כמה ימים המשתמש היה פעיל
                usage_days = user.get("usage_days", [])
                # הפוך מחרוזות תאריך (YYYY-MM-DD) ל-date והשווה ל-week_ago_date
                recent_days = [
                    day for day in usage_days
                    if datetime.strptime(day, "%Y-%m-%d").date() >= week_ago_date
                ]
                
                if recent_days:
                    active_users.append({
                        "username": user.get("username", f"User_{user['user_id']}"),
                        "days": len(recent_days),
                        "total_actions": user.get("total_actions", 0)
                    })
            
            return sorted(active_users, key=lambda x: (x["days"], x["total_actions"]), reverse=True)
        except Exception as e:
            logger.error(f"Error getting weekly stats: {e}")
            return []
    
    def get_all_time_stats(self):
        """סטטיסטיקות כלליות מ-MongoDB"""
        try:
            users_collection = mongodb.db.users
            
            # סה"כ משתמשים
            total_users = users_collection.count_documents({})
            
            # פעילים היום
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            active_today = users_collection.count_documents({"last_seen": today})
            
            # פעילים השבוע
            week_ago = datetime.now(timezone.utc) - timedelta(days=7)
            active_week = users_collection.count_documents({
                "updated_at": {"$gte": week_ago}
            })
            
            return {
                "total_users": total_users,
                "active_today": active_today,
                "active_week": active_week
            }
        except Exception as e:
            logger.error(f"Error getting all time stats: {e}")
            return {
                "total_users": 0,
                "active_today": 0,
                "active_week": 0
            }

# יצירת אובייקט סטטיסטיקות גלובלי
user_stats = UserStats()