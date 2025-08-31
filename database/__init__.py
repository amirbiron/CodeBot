from .models import CodeSnippet, LargeFile
from .manager import DatabaseManager
from .repository import Repository

# יצירת אינסטנס גלובלי לשמירה על תאימות לאחור
db = DatabaseManager()

# לשמירה על תאימות: פונקציה שמחזירה את המנהל (כמו קודם)

def init_database() -> DatabaseManager:
    return db

