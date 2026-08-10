#!/usr/bin/env python3
"""
דוגמה מפורטת לפירוק github_menu_handler.py

קובץ זה מדגים איך לפצל את github_menu_handler.py למודולים קטנים.
"""

import ast
import os
from pathlib import Path
from typing import Dict, List, Set

def extract_method_categories() -> Dict[str, List[str]]:
    """
    מחזיר מיפוי של מתודות לקטגוריות שלהן.
    
    הקטגוריות נקבעו לפי הלוגיקה העסקית של כל מתודה.
    """
    return {
        'base': [
            '__init__',
            'get_user_session',
            'get_user_token',
            'check_rate_limit', 
            'apply_rate_limit_delay',
            '_to_utc_aware',
            '_mk_cb',
            '_get_path_from_cb',
            '_send_or_edit_message',
        ],
        
        'browser': [
            'show_repo_browser',
            'show_browse_ref_menu',
            'show_browse_search_results',
            '_render_file_view',
            'show_repo_selection',
            'show_repos',
        ],
        
        'upload': [
            'handle_file_upload',
            'handle_text_input',
            'show_upload_branch_menu',
            'show_upload_folder_menu',
            'ask_upload_folder',
            'show_upload_other_files',
            'show_upload_repos',
            'show_upload_repo_files',
            'upload_large_files_menu',
            'handle_large_file_upload',
            'handle_saved_file_upload',
            'show_pre_upload_check',
            'confirm_saved_upload',
            'refresh_saved_checks',
        ],
        
        'download': [
            'show_download_file_menu',
            'download_analysis_json',
        ],
        
        'analyzer': [
            'analyze_repository',
            '_create_analysis_summary',
            'show_analyze_repo_menu',
            'request_repo_url',
            'analyze_another_repo',
            'show_improvement_suggestions',
            'show_suggestion_details',
            'show_full_analysis',
            'show_analyze_results_menu',
            'handle_repo_url_input',
        ],
        
        'pr_manager': [
            'show_pr_menu',
            'show_create_pr_menu',
            'show_confirm_create_pr',
            'confirm_create_pr',
            'show_merge_pr_menu',
            'show_confirm_merge_pr',
            'confirm_merge_pr',
            'open_pr_from_branch',
            'create_revert_pr_from_tag',
        ],
        
        'delete_manager': [
            'show_delete_file_menu',
            'show_delete_repo_menu',
            'confirm_delete_file',
            'confirm_delete_repo_step1',
            'confirm_delete_repo',
            'show_danger_delete_menu',
        ],
        
        'notifications': [
            'show_notifications_menu',
            'toggle_notifications',
            'toggle_notifications_pr',
            'toggle_notifications_issues',
            'set_notifications_interval',
            'notifications_check_now',
            '_notifications_job',
        ],
        
        'backup_restore': [
            'show_github_backup_menu',
            'restore_zip_file_to_repo',
            'show_restore_checkpoint_menu',
            'show_restore_tag_actions',
            'create_branch_from_tag',
        ],
        
        'import_export': [
            'show_import_branch_menu',
            '_confirm_import_repo',
            'import_repo_from_zip',
            'start_repo_zip_import',
            'start_zip_create_flow',
        ],
        
        'checkpoints': [
            'git_checkpoint',
            'create_checkpoint_doc',
        ],
        
        'menu_handlers': [
            'github_menu_command',
            'handle_menu_callback',
            'handle_inline_query',
            'handle_callback_query',
        ],
    }

def create_module_template(module_name: str, methods: List[str]) -> str:
    """
    יוצר תבנית למודול חדש.
    """
    template = f'''"""
GitHub {module_name} module.

מודול זה מטפל ב{module_name} של GitHub.
"""

from typing import Any, Dict, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from github import Github
import logging

from .base import GitHubMenuHandlerBase
from .utils import safe_html_escape, format_bytes
from .constants import *

logger = logging.getLogger(__name__)


class GitHub{module_name.title().replace("_", "")}(GitHubMenuHandlerBase):
    """
    טיפול ב-{module_name} של GitHub.
    """
    
'''
    
    for method in methods:
        if method != '__init__':  # לא צריך __init__ במודולים שיורשים
            template += f'''    async def {method}(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        TODO: העבר את הקוד של {method} מהקובץ המקורי.
        """
        pass
    
'''
    
    return template

def create_init_file() -> str:
    """
    יוצר קובץ __init__.py שמאחד את כל המודולים.
    """
    categories = extract_method_categories()
    
    imports = []
    classes = []
    
    for module_name in categories.keys():
        if module_name == 'base':
            continue
        class_name = f'GitHub{module_name.title().replace("_", "")}'
        imports.append(f'from .{module_name} import {class_name}')
        classes.append(class_name)
    
    template = f'''"""
GitHub menu handler - מודול מאוחד.

מודול זה מאחד את כל המודולים של GitHub handler.
"""

from .base import GitHubMenuHandlerBase
{chr(10).join(imports)}


class GitHubMenuHandler(
    {(','+chr(10)+'    ').join(classes)}
):
    """
    Facade class שמאחדת את כל המודולים של GitHub.
    
    מחלקה זו משתמשת בירושה מרובה כדי לאחד את כל הפונקציונליות
    ממודולים נפרדים תחת ממשק אחד.
    """
    pass


# ייצוא להתאמה אחורית
__all__ = ['GitHubMenuHandler']
'''
    
    return template

def create_utils_module() -> str:
    """
    יוצר מודול utils עם פונקציות עזר.
    """
    return '''"""
פונקציות עזר ל-GitHub handler.
"""

import os
import re
import shutil
from html import escape
from typing import Optional
from datetime import datetime, timezone

def _safe_rmtree_tmp(target_path: str) -> None:
    """
    מחיקה בטוחה של תיקייה תחת /tmp בלבד, עם סורגי בטיחות.
    
    Args:
        target_path: נתיב לתיקייה למחיקה
        
    Raises:
        RuntimeError: אם הנתיב אינו תחת /tmp או שגוי
    """
    try:
        if not target_path:
            return
        rp_target = os.path.realpath(target_path)
        rp_base = os.path.realpath("/tmp")
        if not rp_target.startswith(rp_base + os.sep):
            raise RuntimeError(f"Refusing to delete non-tmp path: {rp_target}")
        if rp_target in {"/", os.path.expanduser("~"), os.getcwd()}:
            raise RuntimeError(f"Refusing to delete unsafe path: {rp_target}")
        shutil.rmtree(rp_target, ignore_errors=True)
    except Exception:
        # לא מפסיק את הזרימה במקרה של שגיאה בניקוי
        pass


def safe_html_escape(text) -> str:
    """
    Escape text for Telegram HTML; preserves \n/\r\t and keeps existing HTML entities.
    
    מרחיב ניקוי תווים בלתי נראים: ZWSP/ZWNJ/ZWJ, BOM/ZWNBSP, ותווי כיווניות.
    
    Args:
        text: טקסט לניקוי
        
    Returns:
        טקסט מנוקה ובטוח ל-HTML
    """
    if text is None:
        return ""
    s = escape(str(text))
    # נקה תווים בלתי נראים (Zero-width) + BOM
    s = re.sub(r"[\u200b\u200c\u200d\u2060\ufeff]", "", s)
    # נקה סימוני כיווניות (Cf) נפוצים שגורמים לבלבול בהצגה
    s = re.sub(r"[\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069]", "", s)
    # נקה תווי בקרה אך השאר \n, \r, \t
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", s)
    return s


def format_bytes(num: int) -> str:
    """
    פורמט נחמד לגודל קובץ.
    
    Args:
        num: גודל בבייטים
        
    Returns:
        מחרוזת עם יחידות מתאימות
        
    Examples:
        >>> format_bytes(1024)
        '1.0 KB'
        >>> format_bytes(1048576)
        '1.0 MB'
    """
    try:
        for unit in ["B", "KB", "MB", "GB"]:
            if num < 1024.0 or unit == "GB":
                return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} {unit}"
            num /= 1024.0
    except Exception:
        return str(num)
    return str(num)


def _to_utc_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """
    Normalize datetime to timezone-aware UTC to avoid comparison errors.
    
    PyGithub often returns naive UTC datetimes. We must not compare
    naive and aware datetimes, so we coerce to aware UTC.
    
    Args:
        dt: datetime object (naive or aware)
        
    Returns:
        timezone-aware UTC datetime or None
    """
    if dt is None:
        return None
    try:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        # Fallback: return as-is if unexpected type
        return dt
'''

def create_constants_module() -> str:
    """
    יוצר מודול constants עם קבועים.
    """
    return '''"""
קבועי GitHub handler.
"""

# מצבי שיחה
REPO_SELECT, FILE_UPLOAD, FOLDER_SELECT = range(3)

# מגבלות קבצים גדולים
MAX_INLINE_FILE_BYTES = 5 * 1024 * 1024  # 5MB לשליחה ישירה בבוט
MAX_ZIP_TOTAL_BYTES = 50 * 1024 * 1024  # 50MB לקובץ ZIP אחד
MAX_ZIP_FILES = 500  # מקסימום קבצים ב-ZIP אחד

# מגבלות ייבוא ריפו (ייבוא תוכן, לא גיבוי)
IMPORT_MAX_FILE_BYTES = 1 * 1024 * 1024  # 1MB לקובץ יחיד
IMPORT_MAX_TOTAL_BYTES = 20 * 1024 * 1024  # 20MB לכל הייבוא
IMPORT_MAX_FILES = 2000  # הגבלה סבירה למספר קבצים

# הרחבת רשימת תיקיות כבדות לדילוג בכל עומק עץ
IMPORT_SKIP_DIRS = {
    ".git", ".github", "__pycache__", "node_modules", "dist", "build",
    "_build", "_static", "_images",  # תבניות שנפוצות תחת docs/
    ".venv", "venv", ".tox"
}

# מגבלות עזר לשליפת תאריכי ענפים למיון
MAX_BRANCH_DATE_FETCH = 120  # אם יש יותר מזה — נוותר על מיון לפי תאריך

# תצוגת קובץ חלקית
VIEW_LINES_PER_PAGE = 80

# GitHub API endpoints
GITHUB_API_BASE = "https://api.github.com"
GITHUB_RAW_BASE = "https://raw.githubusercontent.com"

# Rate limiting
RATE_LIMIT_DELAY = 1.0  # שניות בין קריאות API
MAX_RETRIES = 3  # מספר ניסיונות חוזרים במקרה של כשלון

# Telegram limits
TELEGRAM_MESSAGE_LIMIT = 4096  # תווים
TELEGRAM_CAPTION_LIMIT = 1024  # תווים
'''

def create_base_module() -> str:
    """
    יוצר את המודול הבסיסי.
    """
    return '''"""
מחלקת בסיס ל-GitHub menu handler.
"""

from typing import Any, Dict, Optional
import time
import logging

logger = logging.getLogger(__name__)


class GitHubMenuHandlerBase:
    """
    מחלקת בסיס לטיפול בתפריט GitHub.
    
    מחלקה זו מספקת פונקציונליות בסיסית שמשותפת לכל המודולים,
    כולל ניהול סשנים, טוקנים ו-rate limiting.
    """
    
    def __init__(self):
        """אתחול המחלקה."""
        self.user_sessions: Dict[int, Dict[str, Any]] = {}
        self.last_api_call: Dict[int, float] = {}
    
    def get_user_session(self, user_id: int) -> Dict[str, Any]:
        """
        מחזיר או יוצר סשן משתמש בזיכרון.
        
        Args:
            user_id: מזהה המשתמש בטלגרם
            
        Returns:
            מילון עם נתוני הסשן של המשתמש
        """
        if user_id not in self.user_sessions:
            # נסה לטעון ריפו מועדף מהמסד, עם נפילה בטוחה בסביבת בדיקות/CI
            selected_repo = None
            try:
                from database import db  # type: ignore
                try:
                    selected_repo = db.get_selected_repo(user_id)
                except Exception:
                    selected_repo = None
            except Exception:
                selected_repo = None
            
            self.user_sessions[user_id] = {
                "selected_repo": selected_repo,
                "selected_folder": None,  # None = root של הריפו
                "github_token": None,
            }
        return self.user_sessions[user_id]
    
    def get_user_token(self, user_id: int) -> Optional[str]:
        """
        מחזיר טוקן GitHub של המשתמש.
        
        Args:
            user_id: מזהה המשתמש
            
        Returns:
            טוקן GitHub או None אם לא קיים
        """
        session = self.get_user_session(user_id)
        token = session.get("github_token")
        
        if not token:
            # נסה לטעון מהמסד
            try:
                from database import db  # type: ignore
                token = db.get_github_token(user_id)
                if token:
                    session["github_token"] = token
            except Exception:
                pass
        
        return token
    
    async def check_rate_limit(self, github_client, update_or_query) -> bool:
        """
        בדיקת מגבלת קריאות API של GitHub.
        
        Args:
            github_client: אובייקט Github client
            update_or_query: Update או CallbackQuery
            
        Returns:
            True אם אפשר להמשיך, False אם הגענו למגבלה
        """
        try:
            rate = github_client.get_rate_limit().core
            if rate.remaining < 10:
                reset_time = rate.reset
                wait_minutes = (reset_time - datetime.utcnow()).seconds // 60
                
                message = f"⚠️ הגעת למגבלת API של GitHub\\n"
                message += f"נותרו {rate.remaining} קריאות\\n"
                message += f"המגבלה תתאפס בעוד {wait_minutes} דקות"
                
                if hasattr(update_or_query, 'edit_message_text'):
                    await update_or_query.edit_message_text(message)
                else:
                    await update_or_query.message.reply_text(message)
                
                return False
        except Exception as e:
            logger.warning(f"Failed to check rate limit: {e}")
        
        return True
    
    async def apply_rate_limit_delay(self, user_id: int):
        """
        מחיל השהיית rate limit בין קריאות API.
        
        Args:
            user_id: מזהה המשתמש
        """
        now = time.time()
        last_call = self.last_api_call.get(user_id, 0)
        elapsed = now - last_call
        
        if elapsed < 1.0:  # מינימום שנייה בין קריאות
            await asyncio.sleep(1.0 - elapsed)
        
        self.last_api_call[user_id] = time.time()
'''

def generate_refactored_structure():
    """
    יוצר את כל הקבצים למבנה החדש.
    """
    github_dir = Path('github')
    github_dir.mkdir(exist_ok=True)
    
    # יצירת קבצי תשתית
    (github_dir / 'utils.py').write_text(create_utils_module(), encoding='utf-8')
    (github_dir / 'constants.py').write_text(create_constants_module(), encoding='utf-8')
    (github_dir / 'base.py').write_text(create_base_module(), encoding='utf-8')
    
    # יצירת מודולים לפי קטגוריות
    categories = extract_method_categories()
    for module_name, methods in categories.items():
        if module_name == 'base':
            continue  # כבר יצרנו אותו
        
        module_content = create_module_template(module_name, methods)
        (github_dir / f'{module_name}.py').write_text(module_content, encoding='utf-8')
        print(f"✅ נוצר: github/{module_name}.py ({len(methods)} מתודות)")
    
    # יצירת __init__.py
    init_content = create_init_file()
    (github_dir / '__init__.py').write_text(init_content, encoding='utf-8')
    print(f"✅ נוצר: github/__init__.py")
    
    # יצירת קובץ wrapper להתאמה אחורית
    wrapper_content = '''"""
GitHub menu handler - נקודת כניסה ראשית.

קובץ זה שומר על תאימות אחורית עם הקוד הקיים.
"""

# שמירה על תאימות אחורית - ייבוא מהמבנה החדש
from github import GitHubMenuHandler

__all__ = ['GitHubMenuHandler']
'''
    
    Path('github_menu_handler_new.py').write_text(wrapper_content, encoding='utf-8')
    print(f"✅ נוצר: github_menu_handler_new.py (wrapper להתאמה אחורית)")

if __name__ == '__main__':
    import sys
    
    print("דוגמה לפירוק github_menu_handler.py")
    print("="*60)
    
    # הצג את הקטגוריות והמתודות שלהן
    categories = extract_method_categories()
    total_methods = sum(len(methods) for methods in categories.values())
    
    print(f"\nסה\"כ {total_methods} מתודות מחולקות ל-{len(categories)} מודולים:\n")
    
    for module_name, methods in categories.items():
        print(f"📦 {module_name}.py ({len(methods)} מתודות)")
        for method in methods[:5]:  # הצג רק 5 ראשונות
            print(f"   • {method}")
        if len(methods) > 5:
            print(f"   ... ועוד {len(methods)-5} מתודות")
        print()
    
    # בדוק אם יש פרמטר להרצה אוטומטית
    if len(sys.argv) > 1 and sys.argv[1] == '--create':
        print("\nיוצר את מבנה הקבצים...")
        generate_refactored_structure()
        print("\n✅ המבנה נוצר בהצלחה!")
        print("\nהשלבים הבאים:")
        print("1. העבר את הקוד מהקובץ המקורי למודולים החדשים")
        print("2. עדכן את הייבואים בקבצים אחרים")
        print("3. הרץ את הבדיקות")
        print("4. מחק את הקבצים הישנים")
    else:
        print("\nכדי ליצור את המבנה, הרץ:")
        print("  python3 example_github_refactor.py --create")