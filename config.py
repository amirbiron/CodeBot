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
    
    # הגדרות syntax highlighting
    HIGHLIGHT_THEME: str = "github-dark"

    # קידומת לשם נקודת שמירה ב-Git (ל-tags ולענפים בגיבוי)
    GIT_CHECKPOINT_PREFIX: str = "checkpoint"
    
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
    )

# יצירת אינסטנס גלובלי של הקונפיגורציה
config = load_config()
