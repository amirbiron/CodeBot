import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class BotConfig:
    """קונפיגורציה עיקרית של הבוט"""
    
    # טוקן הבוט
    BOT_TOKEN: str
    
    # הגדרות מסד נתונים
    MONGODB_URL: str
    DATABASE_NAME: str = "code_keeper_bot"
    
    # הגדרות Redis Cache
    REDIS_URL: Optional[str] = None
    CACHE_ENABLED: bool = True
    
    # הגדרות GitHub Gist
    GITHUB_TOKEN: Optional[str] = None
    
    # הגדרות Pastebin
    PASTEBIN_API_KEY: Optional[str] = None
    
    # הגדרות כלליות
    MAX_CODE_SIZE: int = 100000  # מקסימום 100KB לקטע קוד
    MAX_FILES_PER_USER: int = 1000
    SUPPORTED_LANGUAGES: list = None

    # סל מיחזור: כמה ימים פריט נשמר לפני מחיקה אוטומטית
    RECYCLE_TTL_DAYS: int = 7
    
    # כתובת בסיס ציבורית להצגת קישורים פנימיים (לשירות web)
    PUBLIC_BASE_URL: Optional[str] = None
    # כתובת ה-WebApp (למקרה שהבוט רץ כ-worker ללא דומיין ציבורי)
    WEBAPP_URL: Optional[str] = None
    
    # מצב תחזוקה/דיפלוי
    MAINTENANCE_MODE: bool = False
    MAINTENANCE_MESSAGE: str = "🚀 אנחנו מעלים עדכון חדש!\nהבוט יחזור לפעול ממש בקרוב (1 - 3 דקות)"
    MAINTENANCE_AUTO_WARMUP_SECS: int = 180
    
    # הגדרות syntax highlighting
    HIGHLIGHT_THEME: str = "github-dark"

    # קידומת לשם נקודת שמירה ב-Git (ל-tags ולענפים בגיבוי)
    GIT_CHECKPOINT_PREFIX: str = "checkpoint"

    # Google Drive OAuth (Desktop App / Device Flow)
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_OAUTH_SCOPES: str = "https://www.googleapis.com/auth/drive.file"
    GOOGLE_TOKEN_REFRESH_MARGIN_SECS: int = 120

    # Feature flags
    DRIVE_MENU_V2: bool = True
    DOCUMENTATION_URL: str = "https://amirbiron.github.io/CodeBot/"
    # תווית/שם לבוט לצורך שמות קבצים ידידותיים
    BOT_LABEL: str = "CodeBot"
    # הוספת hash קצר לשמות קבצים (למניעת כפילויות) — כבוי כברירת מחדל
    DRIVE_ADD_HASH: bool = False
    # נרמול קוד לפני שמירה (הסרה/ניקוי תווים נסתרים)
    NORMALIZE_CODE_ON_SAVE: bool = True
    
    def __post_init__(self):
        if self.SUPPORTED_LANGUAGES is None:
            self.SUPPORTED_LANGUAGES = [
                'python', 'javascript', 'html', 'css', 'java', 'cpp', 'c',
                'php', 'ruby', 'go', 'rust', 'typescript', 'sql', 'bash',
                'json', 'xml', 'yaml', 'markdown', 'dockerfile', 'nginx'
            ]

def load_config() -> BotConfig:
    """טוען את הקונפיגורציה ממשתני הסביבה"""
    
    bot_token = os.getenv('BOT_TOKEN')
    if not bot_token:
        raise ValueError("BOT_TOKEN לא נמצא במשתני הסביבה")
    
    mongodb_url = os.getenv('MONGODB_URL')
    if not mongodb_url:
        raise ValueError("MONGODB_URL לא נמצא במשתני הסביבה")
    
    return BotConfig(
        BOT_TOKEN=bot_token,
        MONGODB_URL=mongodb_url,
        DATABASE_NAME=os.getenv('DATABASE_NAME', 'code_keeper_bot'),
        REDIS_URL=os.getenv('REDIS_URL'),
        CACHE_ENABLED=os.getenv('CACHE_ENABLED', 'false').lower() == 'true',
        GITHUB_TOKEN=os.getenv('GITHUB_TOKEN'),
        PASTEBIN_API_KEY=os.getenv('PASTEBIN_API_KEY'),
        MAX_CODE_SIZE=int(os.getenv('MAX_CODE_SIZE', '100000')),
        MAX_FILES_PER_USER=int(os.getenv('MAX_FILES_PER_USER', '1000')),
        HIGHLIGHT_THEME=os.getenv('HIGHLIGHT_THEME', 'github-dark'),
        GIT_CHECKPOINT_PREFIX=os.getenv('GIT_CHECKPOINT_PREFIX', 'checkpoint'),
        GOOGLE_CLIENT_ID=os.getenv('GOOGLE_CLIENT_ID'),
        GOOGLE_CLIENT_SECRET=os.getenv('GOOGLE_CLIENT_SECRET'),
        GOOGLE_OAUTH_SCOPES=os.getenv('GOOGLE_OAUTH_SCOPES', 'https://www.googleapis.com/auth/drive.file'),
        GOOGLE_TOKEN_REFRESH_MARGIN_SECS=int(os.getenv('GOOGLE_TOKEN_REFRESH_MARGIN_SECS', '120')),
        DRIVE_MENU_V2=os.getenv('DRIVE_MENU_V2', 'true').lower() == 'true',
        DOCUMENTATION_URL=os.getenv('DOCUMENTATION_URL', 'https://amirbiron.github.io/CodeBot/'),
        BOT_LABEL=os.getenv('BOT_LABEL', 'CodeBot'),
        DRIVE_ADD_HASH=os.getenv('DRIVE_ADD_HASH', 'false').lower() == 'true',
        NORMALIZE_CODE_ON_SAVE=os.getenv('NORMALIZE_CODE_ON_SAVE', 'true').lower() == 'true',
        MAINTENANCE_MODE=os.getenv('MAINTENANCE_MODE', 'false').lower() == 'true',
        MAINTENANCE_MESSAGE=os.getenv('MAINTENANCE_MESSAGE', "🚀 אנחנו מעלים עדכון חדש!\nהבוט יחזור לפעול ממש בקרוב (1 - 3 דקות)"),
        MAINTENANCE_AUTO_WARMUP_SECS=int(os.getenv('MAINTENANCE_AUTO_WARMUP_SECS', '180')),
        PUBLIC_BASE_URL=os.getenv('PUBLIC_BASE_URL'),
        WEBAPP_URL=os.getenv('WEBAPP_URL'),
        RECYCLE_TTL_DAYS=int(os.getenv('RECYCLE_TTL_DAYS', '7') or '7'),
    )

# יצירת אינסטנס גלובלי של הקונפיגורציה
config = load_config()
