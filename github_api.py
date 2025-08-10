"""
GitHub API Operations
מודול לפעולות API של GitHub
"""

import logging
import time
from typing import Dict, Any
from github import Github
from telegram import Update
from telegram.ext import ContextTypes
import asyncio

logger = logging.getLogger(__name__)

class GitHubAPI:
    """מנהל API calls ו-rate limiting לGitHub"""
    
    def __init__(self):
        self.last_api_call: Dict[int, float] = {}
        self.rate_limit_delay = 1.0  # שנייה בין קריאות API
    
    async def check_rate_limit(self, github_client: Github, update_or_query) -> bool:
        """בדיקת rate limit של GitHub API"""
        try:
            rate_limit = github_client.get_rate_limit()
            core_limit = rate_limit.core
            
            if core_limit.remaining < 10:
                reset_time = core_limit.reset.strftime('%H:%M:%S')
                warning_message = (
                    f"⚠️ <b>GitHub API Rate Limit נמוך!</b>\n\n"
                    f"🔄 נותרו: {core_limit.remaining}/{core_limit.limit} קריאות\n"
                    f"⏰ איפוס: {reset_time}\n\n"
                    f"💡 המתן מעט לפני פעולות נוספות"
                )
                
                if hasattr(update_or_query, 'callback_query'):
                    await update_or_query.callback_query.answer(
                        "⚠️ Rate limit נמוך - המתן מעט", 
                        show_alert=True
                    )
                elif hasattr(update_or_query, 'message'):
                    await update_or_query.message.reply_text(
                        warning_message, 
                        parse_mode='HTML'
                    )
                
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"שגיאה בבדיקת rate limit: {e}")
            return True  # המשך בכל מקרה
    
    async def apply_rate_limit_delay(self, user_id: int):
        """הפעלת delay בין קריאות API"""
        current_time = time.time()
        last_call = self.last_api_call.get(user_id, 0)
        
        if current_time - last_call < self.rate_limit_delay:
            delay = self.rate_limit_delay - (current_time - last_call)
            await asyncio.sleep(delay)
        
        self.last_api_call[user_id] = time.time()
    
    def get_user_token(self, user_id: int) -> str:
        """קבלת GitHub token של משתמש"""
        from database import db
        
        try:
            user_data = db.get_user_data(user_id)
            if user_data and 'github_token' in user_data:
                return user_data['github_token']
        except Exception as e:
            logger.error(f"שגיאה בקבלת GitHub token: {e}")
        
        # ברירת מחדל - token גלובלי
        from config import config
        return config.GITHUB_TOKEN or ""
    
    def create_github_client(self, user_id: int) -> Github:
        """יצירת GitHub client עם token המתאים"""
        token = self.get_user_token(user_id)
        
        if not token:
            raise ValueError("GitHub token לא זמין")
        
        return Github(token)

# יצירת instance גלובלי
github_api = GitHubAPI()