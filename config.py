import os
from typing import Optional

class Config:
    """הגדרות הבוט"""
    
    # טוקן הבוט מ-BotFather
    BOT_TOKEN: str = os.getenv('BOT_TOKEN', '')
    
    # נתיב מסד הנתונים
    DATABASE_PATH: str = os.getenv('DATABASE_PATH', 'save_me_bot.db')
    
    # הגדרות לוגים
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')
    
    # הגדרות תזכורות
    MAX_REMINDER_HOURS: int = int(os.getenv('MAX_REMINDER_HOURS', '168'))  # שבוע
    MIN_REMINDER_HOURS: int = int(os.getenv('MIN_REMINDER_HOURS', '1'))
    
    # הגדרות חיפוש
    MAX_SEARCH_RESULTS: int = int(os.getenv('MAX_SEARCH_RESULTS', '50'))
    
    # הגדרות ייצוא
    EXPORT_FORMAT: str = os.getenv('EXPORT_FORMAT', 'json')  # json או csv
    
    # הגדרות פיתוח
    DEBUG: bool = os.getenv('DEBUG', 'False').lower() == 'true'
    
    # הגדרות שרת (לרנדר)
    PORT: int = int(os.getenv('PORT', '8443'))
    WEBHOOK_URL: Optional[str] = os.getenv('WEBHOOK_URL')
    
    # הגדרות אבטחה
    ALLOWED_USERS: list = []  # רשימת משתמשים מורשים (ריק = כולם)
    
    @classmethod
    def validate(cls) -> bool:
        """בדיקת תקינות הגדרות"""
        if not cls.BOT_TOKEN:
            raise ValueError("BOT_TOKEN is required")
        
        if cls.MAX_REMINDER_HOURS < cls.MIN_REMINDER_HOURS:
            raise ValueError("MAX_REMINDER_HOURS must be >= MIN_REMINDER_HOURS")
        
        return True
    
    @classmethod
    def is_user_allowed(cls, user_id: int) -> bool:
        """בדיקה אם משתמש מורשה"""
        if not cls.ALLOWED_USERS:  # אם הרשימה ריקה, כולם מורשים
            return True
        return user_id in cls.ALLOWED_USERS
    
    @classmethod
    def get_webhook_info(cls) -> dict:
        """מידע על webhook לרנדר"""
        if not cls.WEBHOOK_URL:
            return {}
        
        return {
            'url': f"{cls.WEBHOOK_URL}/webhook",
            'port': cls.PORT,
            'listen': '0.0.0.0'
        }

# בדיקת הגדרות בזמן import
try:
    Config.validate()
except Exception as e:
    print(f"Configuration error: {e}")
    exit(1)
