"""
מנהל תצוגה מקדימה של קוד
Code Preview Manager
"""

import logging
import re
from typing import Dict, List, Optional, Tuple
from html import escape as html_escape
from utils import get_language_emoji
from cache_manager import cache, cached

logger = logging.getLogger(__name__)

class CodePreviewManager:
    """מנהל תצוגה מקדימה של קוד"""
    
    def __init__(self):
        self.max_preview_lines = 15  # מקסימום שורות בתצוגה מקדימה
        self.max_line_length = 80   # מקסימום תווים בשורה
    
    def create_preview(self, code: str, file_name: str, programming_language: str) -> Dict[str, any]:
        """יוצר תצוגה מקדימה של קוד"""
        try:
            lines = code.split('\n')
            total_lines = len(lines)
            
            # קבלת השורות הראשונות
            preview_lines = lines[:self.max_preview_lines]
            
            # קיצור שורות ארוכות
            truncated_lines = []
            for line in preview_lines:
                if len(line) > self.max_line_length:
                    truncated_lines.append(line[:self.max_line_length] + "...")
                else:
                    truncated_lines.append(line)
            
            preview_text = '\n'.join(truncated_lines)
            
            # מידע נוסף על הקובץ
            file_stats = self._analyze_code_structure(code, programming_language)
            
            # יצירת תצוגה מקדימה מעוצבת
            emoji = get_language_emoji(programming_language)
            
            preview_info = {
                'preview_text': preview_text,
                'total_lines': total_lines,
                'shown_lines': len(preview_lines),
                'is_truncated': total_lines > self.max_preview_lines,
                'file_stats': file_stats,
                'emoji': emoji,
                'language': programming_language
            }
            
            return preview_info
            
        except Exception as e:
            logger.error(f"שגיאה ביצירת תצוגה מקדימה: {e}")
            return {
                'preview_text': 'שגיאה בטעינת תצוגה מקדימה',
                'total_lines': 0,
                'shown_lines': 0,
                'is_truncated': False,
                'file_stats': {},
                'emoji': '📄',
                'language': 'text'
            }
    
    def _analyze_code_structure(self, code: str, language: str) -> Dict[str, any]:
        """ניתוח מבנה הקוד לתצוגה מקדימה"""
        stats = {
            'functions': 0,
            'classes': 0,
            'imports': 0,
            'comments': 0,
            'blank_lines': 0
        }
        
        try:
            lines = code.split('\n')
            
            # תבניות לפי שפת תכנות
            patterns = self._get_language_patterns(language)
            
            for line in lines:
                line_stripped = line.strip()
                
                # שורות ריקות
                if not line_stripped:
                    stats['blank_lines'] += 1
                    continue
                
                # הערות
                if any(line_stripped.startswith(comment) for comment in patterns['comments']):
                    stats['comments'] += 1
                    continue
                
                # imports
                if any(re.match(pattern, line_stripped) for pattern in patterns['imports']):
                    stats['imports'] += 1
                
                # פונקציות
                if any(re.match(pattern, line_stripped) for pattern in patterns['functions']):
                    stats['functions'] += 1
                
                # מחלקות
                if any(re.match(pattern, line_stripped) for pattern in patterns['classes']):
                    stats['classes'] += 1
            
            return stats
            
        except Exception as e:
            logger.error(f"שגיאה בניתוח מבנה קוד: {e}")
            return stats
    
    def _get_language_patterns(self, language: str) -> Dict[str, List[str]]:
        """קבלת תבניות regex לשפות תכנות שונות"""
        patterns = {
            'python': {
                'functions': [r'^def\s+\w+', r'^async\s+def\s+\w+'],
                'classes': [r'^class\s+\w+'],
                'imports': [r'^import\s+', r'^from\s+\w+\s+import'],
                'comments': ['#']
            },
            'javascript': {
                'functions': [r'^function\s+\w+', r'^\w+\s*=\s*function', r'^\w+\s*=>\s*', r'^const\s+\w+\s*=\s*\(.*\)\s*=>'],
                'classes': [r'^class\s+\w+'],
                'imports': [r'^import\s+', r'^const\s+.*=\s*require'],
                'comments': ['//', '/*']
            },
            'java': {
                'functions': [r'^public\s+.*\s+\w+\(', r'^private\s+.*\s+\w+\(', r'^protected\s+.*\s+\w+\('],
                'classes': [r'^public\s+class\s+\w+', r'^class\s+\w+'],
                'imports': [r'^import\s+'],
                'comments': ['//', '/*']
            },
            'cpp': {
                'functions': [r'^\w+.*\w+\s*\(.*\)\s*{?$', r'^.*::\w+\('],
                'classes': [r'^class\s+\w+', r'^struct\s+\w+'],
                'imports': [r'^#include\s*<', r'^#include\s*"'],
                'comments': ['//', '/*']
            }
        }
        
        # ברירת מחדל לשפות לא מוכרות
        default_patterns = {
            'functions': [r'^def\s+', r'^function\s+', r'^\w+\s*\('],
            'classes': [r'^class\s+'],
            'imports': [r'^import\s+', r'^#include', r'^using\s+'],
            'comments': ['#', '//', '/*', '--']
        }
        
        return patterns.get(language.lower(), default_patterns)
    
    def format_preview_message(self, file_name: str, preview_info: Dict) -> str:
        """יוצר הודעה מעוצבת לתצוגה מקדימה"""
        try:
            emoji = preview_info['emoji']
            language = preview_info['language']
            preview_text = html_escape(preview_info['preview_text'])
            stats = preview_info['file_stats']
            
            # כותרת
            header = f"{emoji} <b>{html_escape(file_name)}</b> ({language})\n\n"
            
            # סטטיסטיקות מהירות
            stats_line = "📊 "
            if stats.get('functions', 0) > 0:
                stats_line += f"🔧 {stats['functions']} פונקציות "
            if stats.get('classes', 0) > 0:
                stats_line += f"🏗️ {stats['classes']} מחלקות "
            if stats.get('imports', 0) > 0:
                stats_line += f"📦 {stats['imports']} imports "
            
            stats_line += f"📏 {preview_info['total_lines']} שורות"
            
            # תצוגה מקדימה
            preview_section = f"\n\n<pre><code>{preview_text}</code></pre>\n"
            
            # אזהרה אם הקובץ קוצר
            truncation_warning = ""
            if preview_info['is_truncated']:
                remaining = preview_info['total_lines'] - preview_info['shown_lines']
                truncation_warning = f"\n⚠️ <i>מוצגות {preview_info['shown_lines']} שורות מתוך {preview_info['total_lines']} (עוד {remaining} שורות...)</i>"
            
            return header + stats_line + preview_section + truncation_warning
            
        except Exception as e:
            logger.error(f"שגיאה בפורמט הודעת תצוגה מקדימה: {e}")
            return f"❌ שגיאה בתצוגה מקדימה של {file_name}"
    
    def create_quick_info(self, file_data: Dict) -> str:
        """יוצר מידע מהיר על קובץ ללא תצוגת קוד"""
        try:
            file_name = file_data.get('file_name', 'קובץ ללא שם')
            language = file_data.get('programming_language', 'text')
            code = file_data.get('code', '')
            tags = file_data.get('tags', [])
            created_at = file_data.get('created_at')
            updated_at = file_data.get('updated_at')
            version = file_data.get('version', 1)
            
            emoji = get_language_emoji(language)
            lines_count = len(code.split('\n')) if code else 0
            chars_count = len(code) if code else 0
            
            # פורמט תאריכים
            created_str = created_at.strftime('%d/%m/%Y %H:%M') if created_at else 'לא ידוע'
            updated_str = updated_at.strftime('%d/%m/%Y %H:%M') if updated_at else 'לא ידוע'
            
            # תגיות
            tags_str = ', '.join(tags) if tags else 'ללא תגיות'
            
            info = (
                f"{emoji} <b>{html_escape(file_name)}</b>\n"
                f"💻 <b>שפה:</b> {language}\n"
                f"📏 <b>גודל:</b> {lines_count} שורות, {chars_count:,} תווים\n"
                f"🏷️ <b>תגיות:</b> {html_escape(tags_str)}\n"
                f"📅 <b>נוצר:</b> {created_str}\n"
                f"🔄 <b>עודכן:</b> {updated_str}\n"
                f"📋 <b>גרסה:</b> {version}"
            )
            
            return info
            
        except Exception as e:
            logger.error(f"שגיאה ביצירת מידע מהיר: {e}")
            return "❌ שגיאה בטעינת מידע קובץ"

# יצירת instance גלובלי
code_preview = CodePreviewManager()