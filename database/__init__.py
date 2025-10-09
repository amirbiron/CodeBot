from .models import CodeSnippet, LargeFile
# ייבוא דינמי של מודל סימניות עבור תאימות — אינו חובה למשתמשי הספריה
try:
    from .models.bookmark import FileBookmark  # noqa: F401
except Exception:
    # אם לא קיים תת-מודול — המשך ללא כשל
    pass
from .manager import DatabaseManager

# יצירת אינסטנס גלובלי לשמירה על תאימות לאחור
db = DatabaseManager()

# לשמירה על תאימות: פונקציה שמחזירה את המנהל (כמו קודם)

def init_database() -> DatabaseManager:
    return db

