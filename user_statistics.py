"""
מערכת סטטיסטיקות למעקב אחר שימוש בבוט
User Statistics System for Bot Usage Tracking
"""

import json
from datetime import datetime, timedelta
from collections import defaultdict
import os
import logging

logger = logging.getLogger(__name__)

class UserStatistics:
    def __init__(self, stats_file="/tmp/bot_usage_stats.json"):
        self.stats_file = stats_file
        self.stats = self.load_stats()
    
    def load_stats(self):
        """טעינת סטטיסטיקות משמורות"""
        if os.path.exists(self.stats_file):
            try:
                with open(self.stats_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading stats: {e}")
                return {"users": {}, "daily_stats": {}}
        return {"users": {}, "daily_stats": {}}
    
    def save_stats(self):
        """שמירת סטטיסטיקות"""
        try:
            with open(self.stats_file, 'w') as f:
                json.dump(self.stats, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error saving stats: {e}")
    
    def log_user_activity(self, user_id, username=None, action="command"):
        """רישום פעילות משתמש"""
        user_id = str(user_id)
        today = datetime.now().strftime("%Y-%m-%d")
        now = datetime.now().isoformat()
        
        # עדכון נתוני משתמש
        if user_id not in self.stats["users"]:
            self.stats["users"][user_id] = {
                "username": username,
                "first_seen": now,
                "last_seen": now,
                "total_actions": 0,
                "daily_actions": {},
                "action_types": {}
            }
        
        user_stats = self.stats["users"][user_id]
        user_stats["last_seen"] = now
        if username:
            user_stats["username"] = username
        user_stats["total_actions"] += 1
        
        # עדכון פעולות יומיות
        if today not in user_stats["daily_actions"]:
            user_stats["daily_actions"][today] = 0
        user_stats["daily_actions"][today] += 1
        
        # עדכון סוגי פעולות
        if action not in user_stats["action_types"]:
            user_stats["action_types"][action] = 0
        user_stats["action_types"][action] += 1
        
        # עדכון סטטיסטיקה יומית כללית
        if today not in self.stats["daily_stats"]:
            self.stats["daily_stats"][today] = {"users": [], "total_actions": 0, "action_types": {}}
        
        if user_id not in self.stats["daily_stats"][today]["users"]:
            self.stats["daily_stats"][today]["users"].append(user_id)
        self.stats["daily_stats"][today]["total_actions"] += 1
        
        if action not in self.stats["daily_stats"][today]["action_types"]:
            self.stats["daily_stats"][today]["action_types"][action] = 0
        self.stats["daily_stats"][today]["action_types"][action] += 1
        
        self.save_stats()
    
    def get_weekly_stats(self, offset=0):
        """קבלת סטטיסטיקת שבוע (עם אפשרות להסטה)"""
        start_date = datetime.now() - timedelta(days=7 + offset)
        end_date = datetime.now() - timedelta(days=offset)
        
        active_users = {}
        total_actions = 0
        daily_breakdown = {}
        action_types = defaultdict(int)
        
        for user_id, user_data in self.stats["users"].items():
            last_seen = datetime.fromisoformat(user_data["last_seen"])
            
            if start_date <= last_seen <= end_date:
                # ספור פעולות בטווח הזמן
                week_actions = 0
                for date_str, actions in user_data["daily_actions"].items():
                    date = datetime.strptime(date_str, "%Y-%m-%d")
                    if start_date.date() <= date.date() <= end_date.date():
                        week_actions += actions
                        total_actions += actions
                        
                        # הוסף לפירוט יומי
                        if date_str not in daily_breakdown:
                            daily_breakdown[date_str] = {"users": 0, "actions": 0}
                        daily_breakdown[date_str]["users"] += 1
                        daily_breakdown[date_str]["actions"] += actions
                
                if week_actions > 0:
                    active_users[user_id] = {
                        "username": user_data.get("username"),
                        "actions": week_actions,
                        "last_seen": user_data["last_seen"],
                        "action_types": user_data.get("action_types", {})
                    }
                    
                    # סכום סוגי פעולות
                    for action_type, count in user_data.get("action_types", {}).items():
                        action_types[action_type] += count
        
        return {
            "active_users": active_users,
            "total_users": len(active_users),
            "total_actions": total_actions,
            "daily_breakdown": daily_breakdown,
            "action_types": dict(action_types),
            "start_date": start_date,
            "end_date": end_date
        }
    
    def format_weekly_report(self):
        """יצירת דוח שבועי מעוצב"""
        stats = self.get_weekly_stats()
        
        report = "📊 **סטטיסטיקת שימוש - 7 ימים אחרונים**\n"
        report += "=" * 40 + "\n\n"
        
        report += f"👥 **סה״כ משתמשים פעילים:** {stats['total_users']}\n"
        report += f"⚡ **סה״כ פעולות:** {stats['total_actions']}\n\n"
        
        if stats['total_users'] > 0:
            avg_actions = stats['total_actions'] / stats['total_users']
            report += f"📈 **ממוצע פעולות למשתמש:** {avg_actions:.1f}\n\n"
        
        # רשימת משתמשים פעילים
        report += "👤 **משתמשים פעילים:**\n"
        sorted_users = sorted(stats['active_users'].items(), 
                            key=lambda x: x[1]['actions'], reverse=True)
        
        for i, (user_id, data) in enumerate(sorted_users[:10], 1):
            username = data['username'] or f"User_{user_id[:6]}"
            report += f"{i}. @{username} - {data['actions']} פעולות\n"
        
        if len(sorted_users) > 10:
            report += f"... ועוד {len(sorted_users) - 10} משתמשים\n"
        
        # פירוט יומי
        report += "\n📅 **פעילות יומית:**\n"
        sorted_days = sorted(stats['daily_breakdown'].items())
        for date_str, day_stats in sorted_days[-7:]:
            date = datetime.strptime(date_str, "%Y-%m-%d")
            day_name = date.strftime("%A")[:3]
            report += f"• {date_str} ({day_name}): "
            report += f"{day_stats['users']} משתמשים, {day_stats['actions']} פעולות\n"
        
        # גרף פעילות
        report += "\n" + self.create_activity_graph(stats['daily_breakdown'])
        
        # השוואה לשבוע קודם
        report += "\n" + self.compare_to_last_week()
        
        return report
    
    def create_activity_graph(self, daily_stats):
        """יצירת גרף ASCII של פעילות"""
        if not daily_stats:
            return ""
            
        sorted_days = sorted(daily_stats.items())[-7:]
        if not sorted_days:
            return ""
            
        max_actions = max(d['actions'] for _, d in sorted_days)
        if max_actions == 0:
            return ""
            
        graph = "📊 **גרף פעילות יומית:**\n"
        for date_str, data in sorted_days:
            bar_length = int((data['actions'] / max_actions) * 20)
            bar = "█" * bar_length
            date_short = date_str[-5:]  # MM-DD
            graph += f"{date_short}: {bar} {data['actions']}\n"
        return graph
    
    def compare_to_last_week(self):
        """השוואה לשבוע הקודם"""
        this_week = self.get_weekly_stats()
        last_week = self.get_weekly_stats(offset=7)
        
        if last_week['total_actions'] == 0:
            return "📈 **השוואה לשבוע קודם:** אין נתונים"
        
        action_change = ((this_week['total_actions'] - last_week['total_actions']) 
                        / last_week['total_actions'] * 100)
        user_change = ((this_week['total_users'] - last_week['total_users']) 
                      / max(last_week['total_users'], 1) * 100)
        
        comparison = "📈 **השוואה לשבוע קודם:**\n"
        
        # פעולות
        if action_change > 0:
            comparison += f"• פעולות: ⬆️ +{action_change:.1f}%\n"
        elif action_change < 0:
            comparison += f"• פעולות: ⬇️ {action_change:.1f}%\n"
        else:
            comparison += "• פעולות: ➡️ ללא שינוי\n"
        
        # משתמשים
        if user_change > 0:
            comparison += f"• משתמשים: ⬆️ +{user_change:.1f}%\n"
        elif user_change < 0:
            comparison += f"• משתמשים: ⬇️ {user_change:.1f}%\n"
        else:
            comparison += "• משתמשים: ➡️ ללא שינוי\n"
        
        return comparison
    
    def get_user_stats(self, user_id):
        """קבלת סטטיסטיקה למשתמש ספציפי"""
        user_id = str(user_id)
        if user_id not in self.stats["users"]:
            return None
            
        user_data = self.stats["users"][user_id]
        return {
            "username": user_data.get("username"),
            "first_seen": user_data.get("first_seen"),
            "last_seen": user_data.get("last_seen"),
            "total_actions": user_data.get("total_actions", 0),
            "action_types": user_data.get("action_types", {}),
            "recent_activity": self._get_recent_activity(user_data)
        }
    
    def _get_recent_activity(self, user_data, days=7):
        """קבלת פעילות אחרונה של משתמש"""
        recent = {}
        cutoff_date = datetime.now() - timedelta(days=days)
        
        for date_str, actions in user_data.get("daily_actions", {}).items():
            date = datetime.strptime(date_str, "%Y-%m-%d")
            if date >= cutoff_date:
                recent[date_str] = actions
                
        return recent
    
    def cleanup_old_data(self, days_to_keep=30):
        """ניקוי נתונים ישנים"""
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        cutoff_str = cutoff_date.strftime("%Y-%m-%d")
        
        # נקה נתונים יומיים ישנים
        dates_to_remove = []
        for date_str in self.stats["daily_stats"]:
            if date_str < cutoff_str:
                dates_to_remove.append(date_str)
        
        for date_str in dates_to_remove:
            del self.stats["daily_stats"][date_str]
        
        # נקה נתוני משתמשים ישנים
        for user_id, user_data in self.stats["users"].items():
            dates_to_remove = []
            for date_str in user_data.get("daily_actions", {}):
                if date_str < cutoff_str:
                    dates_to_remove.append(date_str)
            
            for date_str in dates_to_remove:
                del user_data["daily_actions"][date_str]
        
        self.save_stats()
        logger.info(f"Cleaned up data older than {days_to_keep} days")

# יצירת instance גלובלי
user_stats = UserStatistics()