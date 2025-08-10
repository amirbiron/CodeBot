"""
מנהל Lazy Loading לקבצים גדולים
Lazy Loading Manager for Large Files
"""

import logging
import asyncio
from typing import Dict, List, Optional, Generator, Tuple
from dataclasses import dataclass
from database import db
from cache_manager import cache, cached
from html import escape as html_escape

logger = logging.getLogger(__name__)

@dataclass
class FileChunk:
    """חלק מקובץ גדול"""
    file_name: str
    chunk_index: int
    start_line: int
    end_line: int
    content: str
    total_chunks: int
    total_lines: int

class LazyLoader:
    """מנהל Lazy Loading לקבצים גדולים"""
    
    def __init__(self):
        self.chunk_size = 50  # מספר שורות בכל chunk
        self.max_file_size = 5000  # מעל 5000 שורות = קובץ גדול
        self.preview_lines = 20  # שורות לתצוגה מקדימה
    
    def is_large_file(self, code: str) -> bool:
        """בדיקה אם קובץ נחשב גדול"""
        lines_count = len(code.split('\n'))
        return lines_count > self.max_file_size
    
    def create_chunks(self, code: str, file_name: str) -> List[FileChunk]:
        """חלוקת קובץ גדול לchunks"""
        try:
            lines = code.split('\n')
            total_lines = len(lines)
            chunks = []
            
            # חישוב מספר chunks
            total_chunks = (total_lines + self.chunk_size - 1) // self.chunk_size
            
            for i in range(total_chunks):
                start_line = i * self.chunk_size
                end_line = min(start_line + self.chunk_size, total_lines)
                
                chunk_content = '\n'.join(lines[start_line:end_line])
                
                chunk = FileChunk(
                    file_name=file_name,
                    chunk_index=i,
                    start_line=start_line + 1,  # 1-based indexing למשתמש
                    end_line=end_line,
                    content=chunk_content,
                    total_chunks=total_chunks,
                    total_lines=total_lines
                )
                
                chunks.append(chunk)
            
            logger.info(f"קובץ {file_name} חולק ל-{total_chunks} chunks ({total_lines} שורות)")
            return chunks
            
        except Exception as e:
            logger.error(f"שגיאה בחלוקת קובץ לchunks: {e}")
            return []
    
    @cached(expire_seconds=600, key_prefix="file_chunks")  # cache ל-10 דקות
    def get_file_chunk(self, user_id: int, file_name: str, chunk_index: int) -> Optional[FileChunk]:
        """קבלת chunk ספציפי מקובץ"""
        try:
            file_data = db.get_latest_version(user_id, file_name)
            if not file_data:
                return None
            
            code = file_data['code']
            chunks = self.create_chunks(code, file_name)
            
            if 0 <= chunk_index < len(chunks):
                return chunks[chunk_index]
            
            return None
            
        except Exception as e:
            logger.error(f"שגיאה בקבלת chunk: {e}")
            return None
    
    def get_file_summary(self, code: str, file_name: str, programming_language: str) -> Dict[str, any]:
        """יוצר סיכום של קובץ גדול"""
        try:
            lines = code.split('\n')
            total_lines = len(lines)
            
            # ניתוח מבנה הקוד
            structure = self._analyze_file_structure(code, programming_language)
            
            # יצירת סיכום
            summary = {
                'file_name': file_name,
                'language': programming_language,
                'total_lines': total_lines,
                'total_chunks': (total_lines + self.chunk_size - 1) // self.chunk_size,
                'structure': structure,
                'preview_lines': min(self.preview_lines, total_lines),
                'is_large': self.is_large_file(code)
            }
            
            return summary
            
        except Exception as e:
            logger.error(f"שגיאה ביצירת סיכום קובץ: {e}")
            return {}
    
    def _analyze_file_structure(self, code: str, language: str) -> Dict[str, any]:
        """ניתוח מבנה מתקדם של קובץ גדול"""
        structure = {
            'functions': [],
            'classes': [],
            'imports': [],
            'main_sections': []
        }
        
        try:
            lines = code.split('\n')
            current_section = None
            section_start = 0
            
            for i, line in enumerate(lines, 1):
                line_stripped = line.strip()
                
                if not line_stripped:
                    continue
                
                # זיהוי פונקציות (Python)
                if language.lower() == 'python':
                    if line_stripped.startswith('def ') or line_stripped.startswith('async def '):
                        func_name = line_stripped.split('(')[0].replace('def ', '').replace('async def ', '').strip()
                        structure['functions'].append({
                            'name': func_name,
                            'line': i,
                            'type': 'async' if 'async' in line_stripped else 'sync'
                        })
                    
                    elif line_stripped.startswith('class '):
                        class_name = line_stripped.split('(')[0].replace('class ', '').replace(':', '').strip()
                        structure['classes'].append({
                            'name': class_name,
                            'line': i
                        })
                    
                    elif line_stripped.startswith('import ') or line_stripped.startswith('from '):
                        structure['imports'].append({
                            'statement': line_stripped,
                            'line': i
                        })
                
                # זיהוי sections עיקריים (הערות גדולות, docstrings)
                if line_stripped.startswith('"""') or line_stripped.startswith("'''"):
                    if current_section is None:
                        current_section = {
                            'start': i,
                            'type': 'docstring'
                        }
                    else:
                        current_section['end'] = i
                        structure['main_sections'].append(current_section)
                        current_section = None
                
                elif line_stripped.startswith('#' * 3):  # ### או יותר
                    structure['main_sections'].append({
                        'start': i,
                        'end': i,
                        'type': 'section_header',
                        'title': line_stripped.replace('#', '').strip()
                    })
            
            return structure
            
        except Exception as e:
            logger.error(f"שגיאה בניתוח מבנה קובץ: {e}")
            return structure
    
    def format_chunk_message(self, chunk: FileChunk, programming_language: str) -> str:
        """פורמט הודעה לchunk"""
        try:
            from utils import get_language_emoji
            emoji = get_language_emoji(programming_language)
            
            header = (
                f"{emoji} <b>{html_escape(chunk.file_name)}</b>\n"
                f"📄 <b>חלק {chunk.chunk_index + 1}/{chunk.total_chunks}</b> "
                f"(שורות {chunk.start_line}-{chunk.end_line} מתוך {chunk.total_lines})\n\n"
            )
            
            code_content = f"<pre><code>{html_escape(chunk.content)}</code></pre>"
            
            return header + code_content
            
        except Exception as e:
            logger.error(f"שגיאה בפורמט chunk: {e}")
            return f"❌ שגיאה בהצגת חלק מהקובץ {chunk.file_name}"
    
    def get_navigation_keyboard(self, chunk: FileChunk, user_id: int):
        """יוצר מקלדת ניווט לchunks"""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        
        keyboard = []
        
        # שורה ראשונה - ניווט
        nav_row = []
        if chunk.chunk_index > 0:
            nav_row.append(InlineKeyboardButton(
                "⬅️ קודם", 
                callback_data=f"chunk:{chunk.file_name}:{chunk.chunk_index - 1}"
            ))
        
        nav_row.append(InlineKeyboardButton(
            f"{chunk.chunk_index + 1}/{chunk.total_chunks}",
            callback_data=f"chunk_info:{chunk.file_name}"
        ))
        
        if chunk.chunk_index < chunk.total_chunks - 1:
            nav_row.append(InlineKeyboardButton(
                "➡️ הבא", 
                callback_data=f"chunk:{chunk.file_name}:{chunk.chunk_index + 1}"
            ))
        
        keyboard.append(nav_row)
        
        # שורה שנייה - פעולות
        actions_row = [
            InlineKeyboardButton("📖 הצג מלא", callback_data=f"show_full:{chunk.file_name}"),
            InlineKeyboardButton("✏️ ערוך", callback_data=f"edit_file:{chunk.file_name}")
        ]
        keyboard.append(actions_row)
        
        # שורה שלישית - חזרה
        keyboard.append([
            InlineKeyboardButton("🏠 תפריט ראשי", callback_data="main_menu")
        ])
        
        return InlineKeyboardMarkup(keyboard)
    
    async def show_large_file_lazy(self, update, user_id: int, file_name: str, chunk_index: int = 0):
        """הצגת קובץ גדול עם lazy loading"""
        try:
            chunk = self.get_file_chunk(user_id, file_name, chunk_index)
            
            if not chunk:
                await update.message.reply_text(
                    f"❌ לא ניתן לטעון את הקובץ '{html_escape(file_name)}'",
                    parse_mode='HTML'
                )
                return
            
            # קבלת מידע על הקובץ
            file_data = db.get_latest_version(user_id, file_name)
            programming_language = file_data.get('programming_language', 'text') if file_data else 'text'
            
            # פורמט ההודעה
            message = self.format_chunk_message(chunk, programming_language)
            
            # מקלדת ניווט
            keyboard = self.get_navigation_keyboard(chunk, user_id)
            
            # שליחה או עדכון הודעה
            if hasattr(update, 'callback_query') and update.callback_query:
                await update.callback_query.edit_message_text(
                    message,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
            else:
                await update.message.reply_text(
                    message,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
                
        except Exception as e:
            logger.error(f"שגיאה בהצגת קובץ גדול: {e}")
            await update.message.reply_text("❌ שגיאה בטעינת הקובץ")

# יצירת instance גלובלי
lazy_loader = LazyLoader()