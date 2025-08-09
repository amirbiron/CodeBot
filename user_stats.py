import json
import os
from datetime import datetime, timedelta
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)

class UserStats:
    def __init__(self):
        self.stats_file = "/tmp/bot_stats.json"
        self.load_stats()
    
    def load_stats(self):
        """טעינת סטטיסטיקות"""
        try:
            with open(self.stats_file, 'r') as f:
                self.stats = json.load(f)
        except:
            self.stats = {"users": {}}
    
    def save_stats(self):
        """שמירת סטטיסטיקות"""
        try:
            with open(self.stats_file, 'w') as f:
                json.dump(self.stats, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error saving stats: {e}")
    
    def log_user(self, user_id, username=None):
        """רישום משתמש"""
        user_id = str(user_id)
        today = datetime.now().strftime("%Y-%m-%d")
        
        if user_id not in self.stats["users"]:
            self.stats["users"][user_id] = {
                "username": username,
                "first_seen": today,
                "last_seen": today,
                "usage_days": [],
                "total_actions": 0
            }
        
        user_data = self.stats["users"][user_id]
        user_data["last_seen"] = today
        if username:
            user_data["username"] = username
        
        if today not in user_data["usage_days"]:
            user_data["usage_days"].append(today)
        
        user_data["total_actions"] = user_data.get("total_actions", 0) + 1
        
        self.save_stats()
    
    def get_weekly_stats(self):
        """סטטיסטיקת שבוע אחרון"""
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        today = datetime.now().strftime("%Y-%m-%d")
        active_users = []
        
        for user_id, data in self.stats["users"].items():
            if data["last_seen"] >= week_ago:
                days_active = sum(1 for day in data["usage_days"] if day >= week_ago)
                active_users.append({
                    "user_id": user_id,
                    "username": data.get("username") or f"User_{user_id[:6]}",
                    "days": days_active,
                    "last_seen": data["last_seen"],
                    "total_actions": data.get("total_actions", 0)
                })
        
        return sorted(active_users, key=lambda x: (x["days"], x["total_actions"]), reverse=True)
    
    def get_all_time_stats(self):
        """סטטיסטיקות כלליות"""
        total_users = len(self.stats["users"])
        active_today = sum(1 for user in self.stats["users"].values() 
                          if user["last_seen"] == datetime.now().strftime("%Y-%m-%d"))
        
        return {
            "total_users": total_users,
            "active_today": active_today,
            "active_week": len(self.get_weekly_stats())
        }

# יצירת אובייקט סטטיסטיקות גלובלי
user_stats = UserStats()