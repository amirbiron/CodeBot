#!/usr/bin/env python3
"""
סקריפט עזר לפירוק קבצים גדולים - Issue #919

שימוש:
    python refactor_large_files.py analyze    # ניתוח הקבצים
    python refactor_large_files.py prepare    # הכנת מבנה תיקיות
    python refactor_large_files.py backup     # גיבוי קבצים מקוריים
    python refactor_large_files.py split      # ביצוע הפירוק (אינטראקטיבי)
    python refactor_large_files.py verify     # אימות שהכל עובד
"""

import os
import sys
import ast
import shutil
import json
from pathlib import Path
from typing import Dict, List, Set, Tuple
from collections import defaultdict
import argparse

# צבעים לפלט
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def print_header(text: str):
    """הדפסת כותרת."""
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{text}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.ENDC}\n")

def print_success(text: str):
    """הדפסת הודעת הצלחה."""
    print(f"{Colors.OKGREEN}✅ {text}{Colors.ENDC}")

def print_warning(text: str):
    """הדפסת אזהרה."""
    print(f"{Colors.WARNING}⚠️  {text}{Colors.ENDC}")

def print_error(text: str):
    """הדפסת שגיאה."""
    print(f"{Colors.FAIL}❌ {text}{Colors.ENDC}")

def print_info(text: str):
    """הדפסת מידע."""
    print(f"{Colors.OKCYAN}ℹ️  {text}{Colors.ENDC}")

class FileAnalyzer:
    """מנתח קבצי Python."""
    
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.tree = None
        self.classes = {}
        self.functions = {}
        self.imports = []
        self.line_count = 0
        
    def analyze(self):
        """מנתח את הקובץ."""
        with open(self.filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            self.line_count = len(content.splitlines())
            self.tree = ast.parse(content)
        
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ClassDef):
                self.classes[node.name] = {
                    'line': node.lineno,
                    'methods': self._get_methods(node)
                }
            elif isinstance(node, ast.FunctionDef) and node.col_offset == 0:
                self.functions[node.name] = {
                    'line': node.lineno,
                    'async': isinstance(node, ast.AsyncFunctionDef)
                }
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    self.imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    self.imports.append(node.module)
    
    def _get_methods(self, class_node) -> Dict:
        """מחזיר את המתודות של מחלקה."""
        methods = {}
        for node in class_node.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods[node.name] = {
                    'line': node.lineno,
                    'async': isinstance(node, ast.AsyncFunctionDef)
                }
        return methods
    
    def get_summary(self) -> Dict:
        """מחזיר סיכום של הניתוח."""
        return {
            'file': self.filepath,
            'lines': self.line_count,
            'classes': len(self.classes),
            'functions': len(self.functions),
            'total_methods': sum(len(c['methods']) for c in self.classes.values()),
            'imports': len(set(self.imports))
        }

class RefactorManager:
    """מנהל את תהליך הפירוק."""
    
    def __init__(self):
        self.target_files = [
            'github_menu_handler.py',
            'main.py',
            'conversation_handlers.py'
        ]
        self.backup_dir = Path('.refactor_backup')
        
    def analyze_files(self):
        """מנתח את הקבצים שצריכים פירוק."""
        print_header("ניתוח קבצים")
        
        total_lines = 0
        for filepath in self.target_files:
            if not os.path.exists(filepath):
                print_warning(f"קובץ לא נמצא: {filepath}")
                continue
                
            analyzer = FileAnalyzer(filepath)
            analyzer.analyze()
            summary = analyzer.get_summary()
            
            print(f"\n{Colors.BOLD}{filepath}:{Colors.ENDC}")
            print(f"  📏 שורות: {summary['lines']:,}")
            print(f"  🏛️  מחלקות: {summary['classes']}")
            print(f"  🔧 פונקציות: {summary['functions']}")
            print(f"  📦 מתודות: {summary['total_methods']}")
            print(f"  📥 ייבואים: {summary['imports']}")
            
            total_lines += summary['lines']
            
            # המלצות לפירוק
            if summary['lines'] > 1000:
                print_warning(f"  מומלץ לפצל ל-{summary['lines'] // 500} מודולים לפחות")
        
        print(f"\n{Colors.BOLD}סה\"כ שורות: {total_lines:,}{Colors.ENDC}")
        
    def prepare_structure(self):
        """יוצר את מבנה התיקיות החדש."""
        print_header("הכנת מבנה תיקיות")
        
        structures = {
            'github': [
                'github/__init__.py',
                'github/base.py',
                'github/browser.py',
                'github/upload.py',
                'github/download.py',
                'github/analyzer.py',
                'github/pr_manager.py',
                'github/delete_manager.py',
                'github/notifications.py',
                'github/backup_restore.py',
                'github/import_export.py',
                'github/checkpoints.py',
                'github/utils.py',
                'github/constants.py'
            ],
            'bot': [
                'bot/__init__.py',
                'bot/app.py',
                'bot/handlers/__init__.py',
                'bot/handlers/basic.py',
                'bot/handlers/file.py',
                'bot/handlers/search.py',
                'bot/handlers/admin.py',
                'bot/handlers/registration.py',
                'bot/middleware/__init__.py',
                'bot/middleware/auth.py',
                'bot/middleware/logging.py',
                'bot/middleware/error.py',
                'bot/jobs/__init__.py',
                'bot/jobs/scheduler.py',
                'bot/jobs/cleanup.py',
                'bot/jobs/notifications.py',
                'bot/database/__init__.py',
                'bot/database/locks.py'
            ],
            'conversations': [
                'conversations/__init__.py',
                'conversations/base.py',
                'conversations/states.py',
                'conversations/main_menu.py',
                'conversations/file_manager/__init__.py',
                'conversations/file_manager/save.py',
                'conversations/file_manager/edit.py',
                'conversations/file_manager/view.py',
                'conversations/file_manager/delete.py',
                'conversations/file_manager/info.py',
                'conversations/favorites.py',
                'conversations/recycle_bin.py',
                'conversations/batch_operations.py',
                'conversations/repo_browser.py',
                'conversations/versions.py',
                'conversations/handler.py'
            ]
        }
        
        for module_name, paths in structures.items():
            print(f"\n{Colors.BOLD}יוצר מבנה {module_name}:{Colors.ENDC}")
            for path in paths:
                filepath = Path(path)
                filepath.parent.mkdir(parents=True, exist_ok=True)
                
                if not filepath.exists():
                    filepath.touch()
                    print_success(f"נוצר: {path}")
                else:
                    print_info(f"קיים: {path}")
                    
                # הוסף תיעוד בסיסי
                if filepath.name == '__init__.py' and filepath.stat().st_size == 0:
                    module_doc = f'"""{module_name.capitalize()} module."""\n\n'
                    filepath.write_text(module_doc, encoding='utf-8')
    
    def backup_files(self):
        """יוצר גיבוי של הקבצים המקוריים."""
        print_header("גיבוי קבצים מקוריים")
        
        # יצירת תיקיית גיבוי
        self.backup_dir.mkdir(exist_ok=True)
        backup_info = {
            'timestamp': str(Path.cwd()),
            'files': []
        }
        
        for filepath in self.target_files:
            if not os.path.exists(filepath):
                print_warning(f"קובץ לא נמצא: {filepath}")
                continue
                
            backup_path = self.backup_dir / f"{filepath}.backup"
            shutil.copy2(filepath, backup_path)
            print_success(f"גובה: {filepath} -> {backup_path}")
            
            backup_info['files'].append({
                'original': filepath,
                'backup': str(backup_path)
            })
        
        # שמירת מידע על הגיבוי
        info_path = self.backup_dir / 'backup_info.json'
        with open(info_path, 'w') as f:
            json.dump(backup_info, f, indent=2)
        print_success(f"מידע גיבוי נשמר ב: {info_path}")
    
    def verify_refactoring(self):
        """מאמת שהפירוק עובד כשורה."""
        print_header("אימות הפירוק")
        
        tests = [
            # בדיקת ייבואים ראשיים
            ("from github_menu_handler import GitHubMenuHandler", "GitHub handler"),
            ("from main import main", "Main function"),
            ("from conversation_handlers import get_save_conversation_handler", "Conversation handler"),
            
            # בדיקת מודולים חדשים
            ("from github.base import GitHubMenuHandlerBase", "GitHub base class"),
            ("from bot.app import CodeKeeperBot", "Bot app class"),
            ("from conversations.handler import get_main_conversation_handler", "Main conversation handler"),
        ]
        
        success_count = 0
        failed_count = 0
        
        for import_stmt, description in tests:
            try:
                exec(import_stmt)
                print_success(f"{description}: {import_stmt}")
                success_count += 1
            except ImportError as e:
                print_error(f"{description}: {e}")
                failed_count += 1
        
        print(f"\n{Colors.BOLD}תוצאות:{Colors.ENDC}")
        print(f"  ✅ הצליחו: {success_count}")
        print(f"  ❌ נכשלו: {failed_count}")
        
        if failed_count == 0:
            print_success("כל הבדיקות עברו בהצלחה!")
            return True
        else:
            print_error("חלק מהבדיקות נכשלו. בדוק את הייבואים.")
            return False
    
    def interactive_split(self):
        """תהליך פירוק אינטראקטיבי."""
        print_header("פירוק אינטראקטיבי")
        
        print("בחר קובץ לפירוק:")
        for i, filepath in enumerate(self.target_files, 1):
            print(f"  {i}. {filepath}")
        print("  0. יציאה")
        
        choice = input("\nבחירה: ").strip()
        
        if choice == '0':
            return
        
        try:
            file_index = int(choice) - 1
            if 0 <= file_index < len(self.target_files):
                filepath = self.target_files[file_index]
                self._split_file_interactive(filepath)
            else:
                print_error("בחירה לא תקינה")
        except ValueError:
            print_error("יש להזין מספר")
    
    def _split_file_interactive(self, filepath: str):
        """פירוק קובץ בודד באופן אינטראקטיבי."""
        print_header(f"פירוק {filepath}")
        
        if not os.path.exists(filepath):
            print_error(f"קובץ לא נמצא: {filepath}")
            return
        
        # ניתוח הקובץ
        analyzer = FileAnalyzer(filepath)
        analyzer.analyze()
        
        print("\nמחלקות בקובץ:")
        for class_name, class_info in analyzer.classes.items():
            print(f"  • {class_name} (שורה {class_info['line']}, {len(class_info['methods'])} מתודות)")
        
        print("\nפונקציות בקובץ:")
        for func_name, func_info in analyzer.functions.items():
            async_str = " (async)" if func_info['async'] else ""
            print(f"  • {func_name}{async_str} (שורה {func_info['line']})")
        
        print("\nאפשרויות:")
        print("  1. פצל אוטומטית לפי ההמלצות")
        print("  2. פצל ידנית (בחר מה להעביר לכל מודול)")
        print("  3. צור רק את המבנה (ללא העברת קוד)")
        print("  0. חזרה")
        
        choice = input("\nבחירה: ").strip()
        
        if choice == '1':
            self._auto_split(filepath, analyzer)
        elif choice == '2':
            self._manual_split(filepath, analyzer)
        elif choice == '3':
            self._create_structure_only(filepath)
        
    def _auto_split(self, filepath: str, analyzer: FileAnalyzer):
        """פיצול אוטומטי לפי המלצות."""
        print_info("פיצול אוטומטי בתהליך...")
        
        # כאן תהיה הלוגיקה לפיצול אוטומטי
        # לדוגמה, פיצול לפי קטגוריות של מתודות
        
        if filepath == 'github_menu_handler.py':
            categories = {
                'browser': ['show_repo_browser', 'show_browse_ref_menu', 'show_browse_search_results'],
                'upload': ['handle_file_upload', 'handle_text_input', 'show_upload_branch_menu'],
                'download': ['show_download_file_menu', 'download_analysis_json'],
                # ... ועוד קטגוריות
            }
            
            print_success("הקובץ פוצל לקטגוריות:")
            for category, methods in categories.items():
                print(f"  • github/{category}.py: {len(methods)} מתודות")
        
        print_info("יש להשלים את הפיצול ידנית")
        
    def _manual_split(self, filepath: str, analyzer: FileAnalyzer):
        """פיצול ידני - המשתמש בוחר מה להעביר."""
        print_info("פיצול ידני - בפיתוח...")
        # כאן תהיה ממשק אינטראקטיבי לבחירת מתודות למודולים
        
    def _create_structure_only(self, filepath: str):
        """יצירת מבנה בלבד ללא העברת קוד."""
        print_info("יוצר מבנה בלבד...")
        self.prepare_structure()

def main():
    """פונקציה ראשית."""
    parser = argparse.ArgumentParser(
        description='סקריפט עזר לפירוק קבצים גדולים - Issue #919',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
דוגמאות שימוש:
  python refactor_large_files.py analyze    # ניתוח הקבצים
  python refactor_large_files.py prepare    # הכנת מבנה תיקיות
  python refactor_large_files.py backup     # גיבוי קבצים מקוריים
  python refactor_large_files.py split      # ביצוע הפירוק
  python refactor_large_files.py verify     # אימות שהכל עובד
  python refactor_large_files.py all        # הרצת כל השלבים
        """
    )
    
    parser.add_argument(
        'action',
        choices=['analyze', 'prepare', 'backup', 'split', 'verify', 'all'],
        help='הפעולה לביצוע'
    )
    
    args = parser.parse_args()
    
    manager = RefactorManager()
    
    if args.action == 'analyze':
        manager.analyze_files()
    elif args.action == 'prepare':
        manager.prepare_structure()
    elif args.action == 'backup':
        manager.backup_files()
    elif args.action == 'split':
        manager.interactive_split()
    elif args.action == 'verify':
        manager.verify_refactoring()
    elif args.action == 'all':
        print_header("הרצת כל השלבים")
        manager.analyze_files()
        
        print("\nהאם להמשיך להכנת המבנה? (y/n): ", end='')
        if input().lower() == 'y':
            manager.backup_files()
            manager.prepare_structure()
            manager.interactive_split()
            manager.verify_refactoring()
        else:
            print_info("בוטל על ידי המשתמש")

if __name__ == '__main__':
    main()