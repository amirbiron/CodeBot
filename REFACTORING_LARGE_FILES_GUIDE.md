# 📚 מדריך פירוק קבצים גדולים - Issue #919

## 🎯 מטרת הפירוק

פירוק 3 קבצים גדולים לקבצים קטנים וממוקדים כדי לשפר:
- **קריאות הקוד** - קל יותר להבין ולתחזק
- **Code Review** - סקירות קוד מהירות ויעילות יותר
- **מניעת קונפליקטים** - הפחתת Merge Conflicts
- **מודולריות** - הפרדת אחריויות ברורה

## 📊 סטטוס נוכחי

| קובץ | שורות | תיאור |
|------|--------|--------|
| `github_menu_handler.py` | 6,697 | טיפול בכל פעולות GitHub |
| `main.py` | 3,131 | אתחול והגדרת הבוט |
| `conversation_handlers.py` | 3,633 | טיפול בשיחות ודיאלוגים |
| **סה"כ** | **13,461** | **שורות קוד** |

---

## 📁 1. פירוק `github_menu_handler.py`

### 🔍 ניתוח הקובץ הנוכחי

הקובץ מכיל class יחיד `GitHubMenuHandler` עם 78 מתודות שמטפלות ב:
- דפדוף בריפוזיטורים וקבצים
- העלאת קבצים ל-GitHub  
- הורדת קבצים מ-GitHub
- ניתוח ריפוזיטורים
- ניהול Pull Requests
- מחיקת קבצים וריפוזיטורים
- התראות GitHub
- גיבוי ושחזור
- ייבוא וייצוא ZIP

### 🏗️ מבנה מוצע לפירוק

```
github/
├── __init__.py
├── base.py              # GitHubMenuHandler base class + session management
├── browser.py           # דפדוף בריפו וקבצים (show_repo_browser, show_browse_*)
├── upload.py            # העלאות (handle_file_upload, handle_text_input, upload_*)
├── download.py          # הורדות (show_download_*, download_analysis_json)
├── analyzer.py          # ניתוח ריפוזיטורים (analyze_repository, show_analyze_*)
├── pr_manager.py        # ניהול PRs (show_pr_menu, create_pr, merge_pr)
├── delete_manager.py    # מחיקות (show_delete_*, confirm_delete_*)
├── notifications.py     # התראות (show_notifications_menu, _notifications_job)
├── backup_restore.py    # גיבוי ושחזור (show_github_backup_menu, restore_*)
├── import_export.py     # ייבוא/ייצוא ZIP (import_repo_from_zip, show_import_*)
├── checkpoints.py       # ניהול checkpoints (git_checkpoint, create_checkpoint_doc)
├── utils.py            # פונקציות עזר (_safe_rmtree_tmp, safe_html_escape, format_bytes)
└── constants.py        # קבועים (MAX_INLINE_FILE_BYTES, IMPORT_SKIP_DIRS וכו')
```

### 📝 תהליך הפירוק - שלב אחר שלב

#### שלב 1: יצירת תשתית בסיסית
```bash
# יצירת מבנה התיקיות
mkdir -p github
touch github/__init__.py

# העתקת הקובץ המקורי לגיבוי
cp github_menu_handler.py github_menu_handler.py.backup
```

#### שלב 2: יצירת `github/constants.py`
```python
# github/constants.py
"""קבועי GitHub - גבולות ומגבלות."""

# מצבי שיחה
REPO_SELECT, FILE_UPLOAD, FOLDER_SELECT = range(3)

# מגבלות קבצים
MAX_INLINE_FILE_BYTES = 5 * 1024 * 1024  # 5MB
MAX_ZIP_TOTAL_BYTES = 50 * 1024 * 1024  # 50MB
MAX_ZIP_FILES = 500

# מגבלות ייבוא
IMPORT_MAX_FILE_BYTES = 1 * 1024 * 1024  # 1MB
IMPORT_MAX_TOTAL_BYTES = 20 * 1024 * 1024  # 20MB
IMPORT_MAX_FILES = 2000

# תיקיות לדילוג
IMPORT_SKIP_DIRS = {
    ".git", ".github", "__pycache__", "node_modules", 
    "dist", "build", "_build", "_static", "_images",
    ".venv", "venv", ".tox"
}

# הגדרות תצוגה
MAX_BRANCH_DATE_FETCH = 120
VIEW_LINES_PER_PAGE = 80
```

#### שלב 3: יצירת `github/utils.py`
```python
# github/utils.py
"""פונקציות עזר ל-GitHub."""

import os
import re
import shutil
from html import escape
from typing import Optional
from datetime import datetime, timezone

def _safe_rmtree_tmp(target_path: str) -> None:
    """מחיקה בטוחה של תיקייה תחת /tmp בלבד."""
    # ... (העבר את הקוד מהקובץ המקורי)

def safe_html_escape(text):
    """Escape text for Telegram HTML."""
    # ... (העבר את הקוד מהקובץ המקורי)

def format_bytes(num: int) -> str:
    """פורמט נחמד לגודל קובץ."""
    # ... (העבר את הקוד מהקובץ המקורי)

def _to_utc_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalize datetime to timezone-aware UTC."""
    # ... (העבר את הקוד מהקובץ המקורי)
```

#### שלב 4: יצירת `github/base.py`
```python
# github/base.py
"""מחלקת בסיס ל-GitHub menu handler."""

from typing import Any, Dict, Optional
import logging

logger = logging.getLogger(__name__)

class GitHubMenuHandlerBase:
    """מחלקת בסיס לטיפול בתפריט GitHub."""
    
    def __init__(self):
        self.user_sessions: Dict[int, Dict[str, Any]] = {}
        self.last_api_call: Dict[int, float] = {}
    
    def get_user_session(self, user_id: int) -> Dict[str, Any]:
        """מחזיר או יוצר סשן משתמש."""
        # ... (העבר את הקוד מהקובץ המקורי)
    
    def get_user_token(self, user_id: int) -> Optional[str]:
        """מחזיר טוקן GitHub של המשתמש."""
        # ... (העבר את הקוד מהקובץ המקורי)
    
    async def check_rate_limit(self, github_client, update_or_query) -> bool:
        """בדיקת מגבלת קריאות API."""
        # ... (העבר את הקוד מהקובץ המקורי)
    
    async def apply_rate_limit_delay(self, user_id: int):
        """החלת השהיית rate limit."""
        # ... (העבר את הקוד מהקובץ המקורי)
```

#### שלב 5: יצירת מודולים ספציפיים

**`github/browser.py`** - דפדוף בריפו:
```python
# github/browser.py
"""טיפול בדפדוף בריפוזיטורים וקבצים."""

from .base import GitHubMenuHandlerBase
from .utils import safe_html_escape, format_bytes

class GitHubBrowser(GitHubMenuHandlerBase):
    """טיפול בדפדוף GitHub."""
    
    async def show_repo_browser(self, update, context, only_keyboard=False):
        """הצגת דפדפן הריפו."""
        # ... (העבר מתודות רלוונטיות)
    
    async def show_browse_ref_menu(self, update, context):
        """תפריט בחירת ref (ענף/תג)."""
        # ... 
    
    async def show_browse_search_results(self, update, context):
        """הצגת תוצאות חיפוש."""
        # ...
```

**`github/upload.py`** - העלאות:
```python
# github/upload.py
"""טיפול בהעלאות קבצים ל-GitHub."""

from .base import GitHubMenuHandlerBase
from .constants import MAX_INLINE_FILE_BYTES

class GitHubUploader(GitHubMenuHandlerBase):
    """טיפול בהעלאות ל-GitHub."""
    
    async def handle_file_upload(self, update, context):
        """טיפול בהעלאת קובץ."""
        # ...
    
    async def handle_text_input(self, update, context):
        """טיפול בהעלאת טקסט."""
        # ...
    
    async def show_upload_branch_menu(self, update, context):
        """תפריט בחירת ענף להעלאה."""
        # ...
```

#### שלב 6: יצירת `github/__init__.py` עם facade
```python
# github/__init__.py
"""GitHub menu handler מודולרי."""

from .browser import GitHubBrowser
from .upload import GitHubUploader
from .download import GitHubDownloader
from .analyzer import GitHubAnalyzer
from .pr_manager import GitHubPRManager
from .delete_manager import GitHubDeleteManager
from .notifications import GitHubNotifications
from .backup_restore import GitHubBackupRestore
from .import_export import GitHubImportExport
from .checkpoints import GitHubCheckpoints

class GitHubMenuHandler(
    GitHubBrowser,
    GitHubUploader,
    GitHubDownloader,
    GitHubAnalyzer,
    GitHubPRManager,
    GitHubDeleteManager,
    GitHubNotifications,
    GitHubBackupRestore,
    GitHubImportExport,
    GitHubCheckpoints
):
    """Facade class שמאחדת את כל המודולים."""
    pass

# ייצוא להתאמה אחורית
__all__ = ['GitHubMenuHandler']
```

#### שלב 7: עדכון הקובץ הראשי
```python
# github_menu_handler.py (גרסה חדשה)
"""GitHub menu handler - נקודת כניסה ראשית."""

# שמירה על תאימות אחורית
from github import GitHubMenuHandler

__all__ = ['GitHubMenuHandler']
```

### ✅ בדיקות לאחר הפירוק

1. **בדיקת ייבוא**: ודא שכל הייבואים עובדים
   ```python
   from github_menu_handler import GitHubMenuHandler
   handler = GitHubMenuHandler()
   ```

2. **בדיקת פונקציונליות**: הרץ את הבדיקות הקיימות
   ```bash
   pytest tests/test_github_menu.py -v
   ```

3. **בדיקת תלויות צולבות**: ודא שאין תלויות מעגליות

---

## 📁 2. פירוק `main.py`

### 🔍 ניתוח הקובץ הנוכחי

הקובץ מכיל:
- Class `CodeKeeperBot` עם 122 מתודות
- פונקציות אתחול (setup_handlers, main)
- ניהול MongoDB locks
- רישום handlers
- ניהול jobs
- פונקציות עזר

### 🏗️ מבנה מוצע לפירוק

```
bot/
├── __init__.py
├── app.py               # CodeKeeperBot class (אתחול בסיסי)
├── handlers/            
│   ├── __init__.py
│   ├── basic.py        # start, help, status, stats
│   ├── file.py         # save_code, view_code, delete_code
│   ├── search.py       # search, inline_search
│   ├── admin.py        # admin commands (broadcast, logs, etc)
│   └── registration.py # רישום כל ה-handlers
├── middleware/
│   ├── __init__.py
│   ├── auth.py         # אימות משתמשים
│   ├── logging.py      # log_user_activity
│   └── error.py        # error_handler
├── jobs/
│   ├── __init__.py
│   ├── scheduler.py    # ניהול job queue
│   ├── cleanup.py      # cleanup_old_files
│   └── notifications.py # send_notifications
├── database/
│   ├── __init__.py
│   └── locks.py        # MongoDB lock management
└── main.py             # נקודת כניסה ראשית (מופשטת)
```

### 📝 תהליך הפירוק

#### שלב 1: יצירת מבנה תיקיות
```bash
mkdir -p bot/{handlers,middleware,jobs,database}
touch bot/__init__.py
touch bot/handlers/__init__.py
touch bot/middleware/__init__.py
touch bot/jobs/__init__.py
touch bot/database/__init__.py
```

#### שלב 2: יצירת `bot/database/locks.py`
```python
# bot/database/locks.py
"""ניהול MongoDB locks."""

import os
import time
import logging
from pymongo import MongoClient
from typing import Optional

logger = logging.getLogger(__name__)

def get_lock_collection():
    """מחזיר את collection של ה-locks."""
    # ... (העבר את הקוד מ-main.py)

def ensure_lock_indexes() -> None:
    """יוצר אינדקסים ל-lock collection."""
    # ... 

def cleanup_mongo_lock() -> bool:
    """מנקה locks ישנים."""
    # ...

def manage_mongo_lock():
    """מנהל MongoDB lock עם context manager."""
    # ...
```

#### שלב 3: יצירת `bot/handlers/basic.py`
```python
# bot/handlers/basic.py
"""Handlers בסיסיים של הבוט."""

from telegram import Update
from telegram.ext import ContextTypes
import logging

logger = logging.getLogger(__name__)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודת /start."""
    # ... (העבר מ-main.py)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודת /help."""
    # ...

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודת /status."""
    # ...
```

#### שלב 4: יצירת `bot/handlers/registration.py`
```python
# bot/handlers/registration.py
"""רישום כל ה-handlers לאפליקציה."""

from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler
from .basic import start_command, help_command, status_command
from .file import save_code_command, view_code_command
from .search import search_command, inline_search_handler
from .admin import broadcast_command, show_logs_command

def register_handlers(application: Application):
    """רושם את כל ה-handlers לאפליקציה."""
    
    # פקודות בסיסיות
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    
    # פקודות קבצים
    application.add_handler(CommandHandler("save", save_code_command))
    application.add_handler(CommandHandler("view", view_code_command))
    
    # ... (כל שאר ה-handlers)
```

#### שלב 5: יצירת `bot/app.py`
```python
# bot/app.py
"""מחלקת הבוט הראשית."""

from telegram.ext import Application
import logging
from .handlers.registration import register_handlers
from .middleware import setup_middleware
from .jobs import setup_jobs

logger = logging.getLogger(__name__)

class CodeKeeperBot:
    """מחלקת הבוט הראשית."""
    
    def __init__(self, token: str, db_manager):
        self.token = token
        self.db_manager = db_manager
        self.application = None
    
    async def initialize(self):
        """אתחול הבוט."""
        # יצירת אפליקציה
        self.application = Application.builder().token(self.token).build()
        
        # רישום handlers
        register_handlers(self.application)
        
        # הגדרת middleware
        setup_middleware(self.application)
        
        # הגדרת jobs
        setup_jobs(self.application.job_queue)
        
        # אתחול נתוני בוט
        await self._setup_bot_data()
    
    async def start(self):
        """הפעלת הבוט."""
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
    
    async def stop(self):
        """עצירת הבוט."""
        await self.application.updater.stop()
        await self.application.stop()
```

#### שלב 6: עדכון `main.py`
```python
# main.py (גרסה חדשה)
"""נקודת כניסה ראשית לבוט."""

import asyncio
import logging
import os
from bot.app import CodeKeeperBot
from bot.database.locks import manage_mongo_lock
from database import DatabaseManager
from config import config

# הגדרת logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def main():
    """פונקציה ראשית."""
    
    # ניהול MongoDB lock
    with manage_mongo_lock():
        # יצירת מנהל מסד נתונים
        db_manager = DatabaseManager()
        
        # יצירת הבוט
        bot = CodeKeeperBot(
            token=config.TELEGRAM_BOT_TOKEN,
            db_manager=db_manager
        )
        
        # הרצת הבוט
        asyncio.run(run_bot(bot))

async def run_bot(bot: CodeKeeperBot):
    """הרצת הבוט באופן אסינכרוני."""
    try:
        await bot.initialize()
        await bot.start()
        
        # המתנה לסיגנל עצירה
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await bot.stop()

if __name__ == '__main__':
    main()
```

### ✅ בדיקות לאחר הפירוק

1. **בדיקת הרצה**:
   ```bash
   python main.py
   ```

2. **בדיקת כל הפקודות**:
   - `/start`
   - `/help`
   - `/save`
   - `/search`

3. **בדיקת jobs**:
   - ודא שה-jobs רצים כצפוי

---

## 📁 3. פירוק `conversation_handlers.py`

### 🔍 ניתוח הקובץ הנוכחי

הקובץ מכיל:
- 49 פונקציות לטיפול בשיחות
- ConversationHandler ראשי
- טיפול בקבצים (שמירה, עריכה, מחיקה)
- טיפול במועדפים
- טיפול בסל מיחזור
- תפריטי batch

### 🏗️ מבנה מוצע לפירוק

```
conversations/
├── __init__.py
├── base.py              # פונקציות עזר בסיסיות
├── states.py            # הגדרת מצבי שיחה (constants)
├── main_menu.py         # start_command, show_help_page
├── file_manager/
│   ├── __init__.py
│   ├── save.py         # שמירת קבצים
│   ├── edit.py         # עריכת קבצים
│   ├── view.py         # צפייה בקבצים
│   ├── delete.py       # מחיקת קבצים
│   └── info.py         # מידע על קבצים
├── favorites.py         # טיפול במועדפים
├── recycle_bin.py      # סל מיחזור
├── batch_operations.py # פעולות batch
├── repo_browser.py     # דפדוף לפי ריפו
├── versions.py         # ניהול גרסאות
└── handler.py          # ConversationHandler ראשי
```

### 📝 תהליך הפירוק

#### שלב 1: יצירת מבנה תיקיות
```bash
mkdir -p conversations/file_manager
touch conversations/__init__.py
touch conversations/file_manager/__init__.py
```

#### שלב 2: יצירת `conversations/states.py`
```python
# conversations/states.py
"""הגדרת מצבי שיחה."""

# מצבים ראשיים
(
    MAIN_MENU,
    FILE_MENU,
    EDIT_CODE,
    EDIT_NAME,
    EDIT_NOTE,
    DELETE_CONFIRM,
    VIEW_FILE,
    SAVE_FILE,
    BATCH_MENU,
    FAVORITES_MENU,
    RECYCLE_BIN
) = range(11)

# מצבי משנה
(
    WAITING_FOR_CODE,
    WAITING_FOR_NAME,
    WAITING_FOR_NOTE,
    WAITING_FOR_REPO_URL
) = range(100, 104)
```

#### שלב 3: יצירת `conversations/base.py`
```python
# conversations/base.py
"""פונקציות עזר בסיסיות לשיחות."""

from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest
import logging

logger = logging.getLogger(__name__)

async def _safe_edit_message_text(query, text: str, reply_markup=None, parse_mode=None):
    """עריכה בטוחה של הודעה."""
    try:
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except BadRequest as e:
        if "message is not modified" in str(e).lower():
            return
        raise

def _truncate_middle(text: str, max_len: int) -> str:
    """חיתוך טקסט באמצע."""
    if len(text) <= max_len:
        return text
    side_len = (max_len - 3) // 2
    return f"{text[:side_len]}...{text[-side_len:]}"

def _format_bytes(num: int) -> str:
    """פורמט גודל קובץ."""
    # ... (העבר מהקובץ המקורי)
```

#### שלב 4: יצירת `conversations/main_menu.py`
```python
# conversations/main_menu.py
"""תפריט ראשי ופקודות בסיסיות."""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from .states import MAIN_MENU, FILE_MENU
from .base import _safe_edit_message_text
import logging

logger = logging.getLogger(__name__)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """פקודת /start - תפריט ראשי."""
    # ... (העבר מהקובץ המקורי)
    return MAIN_MENU

async def show_help_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1) -> int:
    """הצגת עמוד עזרה."""
    # ... (העבר מהקובץ המקורי)
    return MAIN_MENU
```

#### שלב 5: יצירת מודולי file_manager

**`conversations/file_manager/save.py`**:
```python
# conversations/file_manager/save.py
"""טיפול בשמירת קבצים."""

from telegram import Update
from telegram.ext import ContextTypes
from ..states import SAVE_FILE, WAITING_FOR_CODE
from ..base import _safe_edit_message_text

async def start_save_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """התחלת תהליך שמירת קובץ."""
    # ...
    return WAITING_FOR_CODE

async def receive_code_for_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """קבלת קוד לשמירה."""
    # ...
    return SAVE_FILE
```

**`conversations/file_manager/edit.py`**:
```python
# conversations/file_manager/edit.py
"""טיפול בעריכת קבצים."""

from telegram import Update
from telegram.ext import ContextTypes
from ..states import EDIT_CODE, EDIT_NAME, EDIT_NOTE

async def handle_edit_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """עריכת קוד קובץ."""
    # ...
    return EDIT_CODE

async def handle_edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """עריכת שם קובץ."""
    # ...
    return EDIT_NAME
```

#### שלב 6: יצירת `conversations/handler.py`
```python
# conversations/handler.py
"""ConversationHandler ראשי."""

from telegram.ext import (
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters
)
from .states import *
from .main_menu import start_command, show_help_page
from .file_manager import (
    save, edit, view, delete, info
)
from .favorites import show_favorites_callback
from .recycle_bin import show_recycle_bin
from .batch_operations import show_batch_menu

def get_main_conversation_handler(db_manager):
    """יוצר את ה-ConversationHandler הראשי."""
    
    return ConversationHandler(
        entry_points=[
            CommandHandler("start", start_command),
            CommandHandler("menu", start_command),
        ],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(show_all_files, pattern="^all_files$"),
                CallbackQueryHandler(show_favorites_callback, pattern="^favorites$"),
                CallbackQueryHandler(show_recycle_bin, pattern="^recycle_bin$"),
                CallbackQueryHandler(show_batch_menu, pattern="^batch_menu$"),
                CallbackQueryHandler(show_help_page, pattern="^help$"),
            ],
            FILE_MENU: [
                CallbackQueryHandler(view.handle_view_file, pattern="^view_"),
                CallbackQueryHandler(edit.handle_edit_code, pattern="^edit_code_"),
                CallbackQueryHandler(edit.handle_edit_name, pattern="^edit_name_"),
                CallbackQueryHandler(delete.handle_delete_confirmation, pattern="^delete_"),
            ],
            EDIT_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit.receive_new_code),
            ],
            # ... (שאר המצבים)
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", start_command),
        ],
        allow_reentry=True,
        name="main_conversation"
    )
```

#### שלב 7: עדכון `conversation_handlers.py`
```python
# conversation_handlers.py (גרסה חדשה)
"""Conversation handlers - נקודת כניסה ראשית."""

# שמירה על תאימות אחורית
from conversations.handler import get_main_conversation_handler
from conversations.main_menu import start_command
from conversations.file_manager import *
from conversations.favorites import *
from conversations.recycle_bin import *

# ייצוא להתאמה אחורית
__all__ = [
    'get_main_conversation_handler',
    'start_command',
    # ... (כל הפונקציות שיוצאו קודם)
]

# תאימות אחורית - alias לפונקציה הראשית
get_save_conversation_handler = get_main_conversation_handler
```

### ✅ בדיקות לאחר הפירוק

1. **בדיקת conversation flow**:
   - התחל שיחה עם `/start`
   - נווט בתפריטים
   - שמור קובץ חדש
   - ערוך קובץ קיים

2. **בדיקת תלויות**:
   ```python
   from conversation_handlers import get_main_conversation_handler
   handler = get_main_conversation_handler(db_manager)
   ```

3. **בדיקות אוטומטיות**:
   ```bash
   pytest tests/test_conversations.py -v
   ```

---

## 🔧 כלי עזר לפירוק

### 1. סקריפט לניתוח תלויות
```python
# analyze_dependencies.py
"""ניתוח תלויות בין פונקציות."""

import ast
import sys

def analyze_file(filename):
    """מנתח קובץ Python ומוצא תלויות."""
    with open(filename, 'r') as f:
        tree = ast.parse(f.read())
    
    # מצא את כל הפונקציות
    functions = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            functions[node.name] = node
    
    # מצא קריאות בין פונקציות
    dependencies = {}
    for name, func_node in functions.items():
        calls = set()
        for node in ast.walk(func_node):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    calls.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    calls.add(node.func.attr)
        dependencies[name] = calls
    
    return dependencies

if __name__ == "__main__":
    deps = analyze_file(sys.argv[1])
    for func, calls in deps.items():
        print(f"{func}: {', '.join(calls)}")
```

### 2. סקריפט לבדיקת ייבואים
```python
# check_imports.py
"""בדיקת ייבואים אחרי הפירוק."""

def check_module_imports(module_name):
    """בודק שכל הייבואים עובדים."""
    try:
        module = __import__(module_name)
        print(f"✅ {module_name} imported successfully")
        
        # בדוק את כל ה-exports
        if hasattr(module, '__all__'):
            for export in module.__all__:
                if not hasattr(module, export):
                    print(f"❌ Missing export: {export}")
        return True
    except ImportError as e:
        print(f"❌ Failed to import {module_name}: {e}")
        return False

# בדיקת כל המודולים החדשים
modules = [
    'github_menu_handler',
    'main',
    'conversation_handlers',
    'github.base',
    'github.browser',
    'bot.app',
    'conversations.handler'
]

for mod in modules:
    check_module_imports(mod)
```

---

## 📋 צ'קליסט לביצוע

### Phase 1: הכנה
- [ ] יצירת branch חדש: `refactor/split-large-files-919`
- [ ] גיבוי הקבצים המקוריים
- [ ] יצירת מבנה תיקיות חדש
- [ ] הרצת בדיקות לפני השינוי (baseline)

### Phase 2: פירוק `github_menu_handler.py`
- [ ] יצירת תיקיית `github/`
- [ ] פירוק לפי מודולים (browser, upload, download, etc.)
- [ ] יצירת facade class
- [ ] עדכון ייבואים
- [ ] הרצת בדיקות
- [ ] commit: `refactor(github): split github_menu_handler into modules`

### Phase 3: פירוק `main.py`
- [ ] יצירת תיקיית `bot/`
- [ ] הפרדת handlers, middleware, jobs
- [ ] יצירת CodeKeeperBot class מופשטת
- [ ] עדכון נקודת כניסה
- [ ] הרצת בדיקות
- [ ] commit: `refactor(main): split main.py into bot modules`

### Phase 4: פירוק `conversation_handlers.py`
- [ ] יצירת תיקיית `conversations/`
- [ ] פירוק לפי flow (file_manager, favorites, etc.)
- [ ] יצירת handler מרכזי
- [ ] עדכון ייבואים
- [ ] הרצת בדיקות
- [ ] commit: `refactor(conversations): split conversation_handlers into modules`

### Phase 5: בדיקות וקלינאפ
- [ ] הרצת כל הבדיקות
- [ ] בדיקת ביצועים (אין regression)
- [ ] עדכון תיעוד
- [ ] מחיקת קבצי גיבוי
- [ ] commit: `chore: cleanup after refactoring`

### Phase 6: הגשה
- [ ] יצירת PR עם תיאור מפורט
- [ ] הוספת before/after בתיאור
- [ ] סימון Issue #919
- [ ] המתנה ל-code review

---

## 🎯 יעדי הצלחה

### מדדים כמותיים
- ✅ אף קובץ לא עולה על 1,000 שורות (אידיאלי: 500)
- ✅ כל מודול ממוקד באחריות אחת
- ✅ אין תלויות מעגליות
- ✅ כל הבדיקות עוברות

### מדדים איכותיים
- ✅ קוד קריא וברור יותר
- ✅ קל יותר למצוא פונקציונליות
- ✅ קל יותר להוסיף פיצ'רים חדשים
- ✅ Code review מהיר יותר

---

## 💡 טיפים וטריקים

### 1. שימוש ב-git למעקב
```bash
# לפני כל שינוי גדול
git add -A && git commit -m "checkpoint: before splitting X"

# אחרי כל שלב מוצלח
git add -A && git commit -m "refactor: completed X module split"
```

### 2. בדיקה מהירה של ייבואים
```bash
# בדוק שכל הייבואים עובדים
python -c "from github_menu_handler import GitHubMenuHandler; print('✅')"
python -c "from main import main; print('✅')"
python -c "from conversation_handlers import get_save_conversation_handler; print('✅')"
```

### 3. שימוש ב-IDE refactoring
- השתמש ב-"Extract Method" של ה-IDE
- השתמש ב-"Move to Module"
- הרץ "Optimize Imports" אחרי כל העברה

### 4. תיעוד תוך כדי
- הוסף docstring לכל מודול חדש
- תעד את המטרה של כל מודול
- הוסף type hints היכן שחסר

---

## 📚 מקורות והפניות

- [Python Module Best Practices](https://docs.python.org/3/tutorial/modules.html)
- [Refactoring Large Python Codebases](https://realpython.com/python-refactoring/)
- [SOLID Principles in Python](https://realpython.com/solid-principles-python/)
- [Issue #919 ב-GitHub](https://github.com/amirbiron/CodeBot/issues/919)

---

## 🆘 פתרון בעיות נפוצות

### בעיה: ImportError אחרי הפירוק
**פתרון**: בדוק את ה-`__init__.py` בתיקיות החדשות ווודא שיש ייצוא נכון

### בעיה: תלויות מעגליות
**פתרון**: הוצא פונקציות משותפות למודול `utils` או `base`

### בעיה: בדיקות נכשלות
**פתרון**: ודא שהייבואים בקבצי הבדיקה מעודכנים

### בעיה: הבוט לא עולה
**פתרון**: בדוק את ה-logs, ייתכן שחסר handler או import

---

## ✨ סיכום

פירוק הקבצים הגדולים הוא משימה חשובה שתשפר משמעותית את איכות הקוד והתחזוקה שלו. 
המדריך הזה מספק roadmap מלא לביצוע הפירוק בצורה מסודרת ובטוחה.

**זכור**: 
- בצע שינויים קטנים ומדודים
- בדוק אחרי כל שלב
- שמור גיבויים
- תעד את השינויים

בהצלחה! 🚀