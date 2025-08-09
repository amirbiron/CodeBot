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
    
    # הגדרות GitHub Gist
    GITHUB_TOKEN: Optional[str] = None
    
    # הגדרות Pastebin
    PASTEBIN_API_KEY: Optional[str] = None
    
    # הגדרות כלליות
    MAX_CODE_SIZE: int = 100000  # מקסימום 100KB לקטע קוד
    MAX_FILES_PER_USER: int = 1000
    SUPPORTED_LANGUAGES: list = None
    
    # הגדרות syntax highlighting
    HIGHLIGHT_THEME: str = "github-dark"
    
    # רשימת מנהלים (Telegram user IDs)
    ADMIN_IDS: list = None
    
    def __post_init__(self):
        if self.SUPPORTED_LANGUAGES is None:
            self.SUPPORTED_LANGUAGES = [
                'python', 'javascript', 'html', 'css', 'java', 'cpp', 'c',
                'php', 'ruby', 'go', 'rust', 'typescript', 'sql', 'bash',
                'json', 'xml', 'yaml', 'markdown', 'dockerfile', 'nginx'
            ]
        
        # טען רשימת מנהלים ממשתנה סביבה
        if self.ADMIN_IDS is None:
            admin_ids_str = os.getenv('ADMIN_IDS', '')
            if admin_ids_str:
                try:
                    self.ADMIN_IDS = [int(id.strip()) for id in admin_ids_str.split(',') if id.strip()]
                except ValueError:
                    self.ADMIN_IDS = []
            else:
                self.ADMIN_IDS = []

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
        GITHUB_TOKEN=os.getenv('GITHUB_TOKEN'),
        PASTEBIN_API_KEY=os.getenv('PASTEBIN_API_KEY'),
        MAX_CODE_SIZE=int(os.getenv('MAX_CODE_SIZE', '100000')),
        MAX_FILES_PER_USER=int(os.getenv('MAX_FILES_PER_USER', '1000')),
        HIGHLIGHT_THEME=os.getenv('HIGHLIGHT_THEME', 'github-dark')
    )

# יצירת אינסטנס גלובלי של הקונפיגורציה
config = load_config()
