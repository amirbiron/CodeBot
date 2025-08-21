"""
מעבד קטעי קוד - זיהוי שפה, הדגשת תחביר ועיבוד
Code Processor - Language detection, syntax highlighting and processing
"""

import base64
import io
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cairosvg
import textstat
# Language detection
from langdetect import DetectorFactory, detect
# Image processing
from PIL import Image, ImageDraw, ImageFont
# Syntax highlighting
from pygments import highlight
from pygments.formatters import (HtmlFormatter, ImageFormatter,
                                 TerminalFormatter)
from pygments.lexers import (get_lexer_by_name, get_lexer_for_filename,
                             guess_lexer)
from pygments.styles import get_style_by_name
from pygments.util import ClassNotFound

from config import config
from cache_manager import cache, cached

logger = logging.getLogger(__name__)

# קביעת זרע לשחזור תוצאות זיהוי שפה
DetectorFactory.seed = 0

class CodeProcessor:
    """מחלקה לעיבוד קטעי קוד"""
    
    def __init__(self):
        self.language_patterns = self._init_language_patterns()
        self.common_extensions = self._init_extensions()
        self.style = get_style_by_name(config.HIGHLIGHT_THEME)
        
        # הגדרת לוגר ייעודי לטיפול בשגיאות קוד
        self.code_logger = logging.getLogger('code_handler')
        if not self.code_logger.handlers:
            handler = logging.StreamHandler()  # שימוש ב-StreamHandler במקום FileHandler לסביבת פרודקשן
            handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
            self.code_logger.addHandler(handler)
            self.code_logger.setLevel(logging.INFO)
    
    def sanitize_code_blocks(self, text: str) -> str:
        """
        מנקה וטיפול בקטעי קוד עם סימוני markdown (```)
        מוודא שהקוד מפורמט כראוי ונקי משגיאות
        """
        try:
            if not text or not isinstance(text, str):
                self.code_logger.warning("קלט לא תקין לסניטציה")
                return text or ""
            
            # בדיקה אם יש בלוקי קוד עם סימוני ```
            if '```' in text:
                self.code_logger.info("מזוהים בלוקי קוד עם סימוני ```")
                
                # טיפול בבלוקי קוד עם שפה מוגדרת (```python, ```javascript וכו')
                pattern = r'```(\w+)?\s*([\s\S]*?)```'
                
                def replace_code_block(match):
                    language_hint = match.group(1) or ""
                    code_content = match.group(2) or ""
                    
                    # ניקוי הקוד מרווחים מיותרים
                    cleaned_code = code_content.strip()
                    
                    # רישום הפעולה
                    self.code_logger.info(f"מעבד בלוק קוד: {language_hint}, אורך: {len(cleaned_code)}")
                    
                    # החזרת הקוד הנקי בלבד (ללא סימוני ```)
                    return cleaned_code
                
                # החלפת כל בלוקי הקוד
                processed_text = re.sub(pattern, replace_code_block, text, flags=re.DOTALL)
                
                # אם לא נמצאו התאמות עם שפה, נסה בלי שפה
                if processed_text == text:
                    simple_pattern = r'```([\s\S]*?)```'
                    processed_text = re.sub(simple_pattern, lambda m: m.group(1).strip(), text, flags=re.DOTALL)
                
                self.code_logger.info("סניטציית קוד הושלמה בהצלחה")
                return processed_text
            
            # אם אין בלוקי קוד, החזר את הטקסט כמו שהוא
            return text
            
        except Exception as e:
            self.code_logger.error(f"שגיאה בסניטציית קוד: {str(e)}")
            # במקרה של שגיאה, החזר את הטקסט המקורי
            return text
    
    def validate_code_input(self, code: str, filename: str = None, user_id: int = None, *, skip_size_check: bool = False) -> Tuple[bool, str, str]:
        """
        מאמת קלט קוד ומחזיר תוקף, קוד מנוקה והודעת שגיאה אם יש
        """
        try:
            if not code or not isinstance(code, str):
                if user_id:
                    from utils import code_error_logger
                    code_error_logger.log_validation_failure(user_id, 0, "קלט קוד לא תקין או ריק")
                return False, "", "קלט קוד לא תקין או ריק"
            
            original_length = len(code)
            
            # סניטציה ראשונית
            cleaned_code = self.sanitize_code_blocks(code)
            cleaned_length = len(cleaned_code)
            
            # רישום הצלחת סניטציה
            if user_id and original_length != cleaned_length:
                from utils import code_error_logger
                code_error_logger.log_sanitization_success(user_id, original_length, cleaned_length)
            
            # בדיקות נוספות
            if len(cleaned_code.strip()) == 0:
                if user_id:
                    from utils import code_error_logger
                    code_error_logger.log_validation_failure(user_id, original_length, "הקוד ריק לאחר עיבוד")
                return False, "", "הקוד ריק לאחר עיבוד"
            
            # בדיקה אם הקוד ארוך מדי (ניתן לדלג ב- Batch)
            if not skip_size_check and len(cleaned_code) > int(getattr(config, 'MAX_CODE_SIZE', 100000)):
                if user_id:
                    from utils import code_error_logger
                    # שימוש בערך מהקונפיגורציה להודעה
                    try:
                        limit_kb = int(getattr(config, 'MAX_CODE_SIZE', 100000)) // 1024
                    except Exception:
                        limit_kb = 50
                    code_error_logger.log_validation_failure(user_id, cleaned_length, f"הקוד ארוך מדי (מעל {limit_kb}KB)")
                return False, "", f"הקוד ארוך מדי (מעל {int(getattr(config, 'MAX_CODE_SIZE', 100000)) // 1024}KB)"
            
            # בדיקה לתווים לא חוקיים
            try:
                cleaned_code.encode('utf-8')
            except UnicodeEncodeError:
                if user_id:
                    from utils import code_error_logger
                    code_error_logger.log_validation_failure(user_id, cleaned_length, "הקוד מכיל תווים לא חוקיים")
                return False, "", "הקוד מכיל תווים לא חוקיים"
            
            # רישום הצלחה
            self.code_logger.info(f"אימות קוד הצליח, אורך: {len(cleaned_code)}")
            if user_id:
                from utils import code_error_logger
                code_error_logger.log_code_activity(user_id, "validation_success", {
                    "original_length": original_length,
                    "cleaned_length": cleaned_length,
                    "filename": filename
                })
            
            return True, cleaned_code, ""
            
        except Exception as e:
            error_msg = f"שגיאה באימות קוד: {str(e)}"
            self.code_logger.error(error_msg)
            if user_id:
                from utils import code_error_logger
                code_error_logger.log_code_processing_error(user_id, "validation_exception", str(e))
            return False, "", error_msg
        
    def _init_language_patterns(self) -> Dict[str, List[str]]:
        """אתחול דפוסי זיהוי שפות תכנות"""
        return {
            'python': [
                r'\bdef\s+\w+\s*\(',
                r'\bimport\s+\w+',
                r'\bfrom\s+\w+\s+import',
                r'\bclass\s+\w+\s*\(',
                r'\bif\s+__name__\s*==\s*["\']__main__["\']',
                r'\bprint\s*\(',
                r'\belif\b',
                r'\btry\s*:',
                r'\bexcept\b',
                r'#.*$'
            ],
            'javascript': [
                r'\bfunction\s+\w+\s*\(',
                r'\bvar\s+\w+',
                r'\blet\s+\w+',
                r'\bconst\s+\w+',
                r'\bconsole\.log\s*\(',
                r'\b=>\s*{',
                r'\brequire\s*\(',
                r'\bexport\s+',
                r'//.*$',
                r'/\*.*?\*/'
            ],
            'java': [
                r'\bpublic\s+class\s+\w+',
                r'\bpublic\s+static\s+void\s+main',
                r'\bSystem\.out\.println\s*\(',
                r'\bprivate\s+\w+',
                r'\bprotected\s+\w+',
                r'\bimport\s+java\.',
                r'\b@\w+',
                r'\bthrows\s+\w+'
            ],
            'cpp': [
                r'#include\s*<.*>',
                r'\bstd::\w+',
                r'\busing\s+namespace\s+std',
                r'\bint\s+main\s*\(',
                r'\bcout\s*<<',
                r'\bcin\s*>>',
                r'\bclass\s+\w+\s*{',
                r'\btemplate\s*<'
            ],
            'c': [
                r'#include\s*<.*\.h>',
                r'\bint\s+main\s*\(',
                r'\bprintf\s*\(',
                r'\bscanf\s*\(',
                r'\bmalloc\s*\(',
                r'\bfree\s*\(',
                r'\bstruct\s+\w+\s*{',
                r'\btypedef\s+'
            ],
            'php': [
                r'<\?php',
                r'\$\w+',
                r'\becho\s+',
                r'\bprint\s+',
                r'\bfunction\s+\w+\s*\(',
                r'\bclass\s+\w+\s*{',
                r'\b->\w+',
                r'\brequire_once\s*\('
            ],
            'html': [
                r'<!DOCTYPE\s+html>',
                r'<html.*?>',
                r'<head.*?>',
                r'<body.*?>',
                r'<div.*?>',
                r'<p.*?>',
                r'<script.*?>',
                r'<style.*?>'
            ],
            'css': [
                r'\w+\s*{[^}]*}',
                r'@media\s+',
                r'@import\s+',
                r'@font-face\s*{',
                r':\s*\w+\s*;',
                r'#\w+\s*{',
                r'\.\w+\s*{'
            ],
            'sql': [
                r'\bSELECT\s+',
                r'\bFROM\s+\w+',
                r'\bWHERE\s+',
                r'\bINSERT\s+INTO',
                r'\bUPDATE\s+\w+',
                r'\bDELETE\s+FROM',
                r'\bCREATE\s+TABLE',
                r'\bALTER\s+TABLE'
            ],
            'bash': [
                r'#!/bin/bash',
                r'#!/bin/sh',
                r'\becho\s+',
                r'\bif\s*\[.*\]',
                r'\bfor\s+\w+\s+in',
                r'\bwhile\s*\[.*\]',
                r'\$\{\w+\}',
                r'\$\w+'
            ],
            'json': [
                r'^\s*{',
                r'^\s*\[',
                r'"\w+"\s*:',
                r':\s*"[^"]*"',
                r':\s*\d+',
                r':\s*true|false|null'
            ],
            'xml': [
                r'<\?xml\s+version',
                r'<\w+.*?/>',
                r'<\w+.*?>.*?</\w+>',
                r'<!--.*?-->',
                r'\sxmlns\s*='
            ],
            'yaml': [
                r'^\s*\w+\s*:',
                r'^\s*-\s+\w+',
                r'---\s*$',
                r'^\s*#.*$'
            ],
            'markdown': [
                r'^#.*$',
                r'^\*.*\*$',
                r'^```.*$',
                r'^\[.*\]\(.*\)$',
                r'^!\[.*\]\(.*\)$'
            ]
        }
    
    def _init_extensions(self) -> Dict[str, str]:
        """מיפוי סיומות קבצים לשפות"""
        return {
            '.py': 'python',
            '.js': 'javascript',
            '.jsx': 'javascript',
            '.ts': 'typescript',
            '.tsx': 'typescript',
            '.java': 'java',
            '.cpp': 'cpp',
            '.cxx': 'cpp',
            '.cc': 'cpp',
            '.c': 'c',
            '.h': 'c',
            '.hpp': 'cpp',
            '.php': 'php',
            '.html': 'html',
            '.htm': 'html',
            '.css': 'css',
            '.scss': 'scss',
            '.sass': 'sass',
            '.less': 'less',
            '.sql': 'sql',
            '.sh': 'bash',
            '.bash': 'bash',
            '.zsh': 'bash',
            '.fish': 'fish',
            '.ps1': 'powershell',
            '.json': 'json',
            '.xml': 'xml',
            '.yaml': 'yaml',
            '.yml': 'yaml',
            '.md': 'markdown',
            '.rst': 'rst',
            '.go': 'go',
            '.rs': 'rust',
            '.rb': 'ruby',
            '.pl': 'perl',
            '.r': 'r',
            '.m': 'matlab',
            '.swift': 'swift',
            '.kt': 'kotlin',
            '.scala': 'scala',
            '.cs': 'csharp',
            '.vb': 'vbnet',
            '.lua': 'lua',
            '.dart': 'dart',
            '.dockerfile': 'dockerfile',
            '.tf': 'hcl',
            '.hcl': 'hcl'
        }
    
    def detect_language(self, code: str, filename: str = None) -> str:
        """זיהוי שפת התכנות של הקוד"""
        
        # סניטציה ראשונית של הקוד
        try:
            sanitized_code = self.sanitize_code_blocks(code)
            self.code_logger.info(f"קוד סונטז לזיהוי שפה, אורך מקורי: {len(code)}, אורך מנוקה: {len(sanitized_code)}")
        except Exception as e:
            self.code_logger.error(f"שגיאה בסניטציה לזיהוי שפה: {e}")
            sanitized_code = code
        
        # בדיקה ראשונה - לפי סיומת הקובץ
        if filename:
            ext = Path(filename).suffix.lower()
            if ext in self.common_extensions:
                detected = self.common_extensions[ext]
                logger.info(f"זוהתה שפה לפי סיומת: {detected}")
                return detected
        
        # בדיקה שנייה - לפי דפוסי קוד
        language_scores = {}
        
        for language, patterns in self.language_patterns.items():
            score = 0
            for pattern in patterns:
                matches = re.findall(pattern, sanitized_code, re.MULTILINE | re.IGNORECASE)
                score += len(matches)
            
            if score > 0:
                language_scores[language] = score
        
        if language_scores:
            detected = max(language_scores, key=language_scores.get)
            logger.info(f"זוהתה שפה לפי דפוסים: {detected} (ניקוד: {language_scores[detected]})")
            return detected
        
        # בדיקה שלישית - באמצעות Pygments
        try:
            lexer = guess_lexer(sanitized_code)
            detected = lexer.name.lower()
            
            # נרמול שמות שפות
            if 'python' in detected:
                return 'python'
            elif 'javascript' in detected or 'js' in detected:
                return 'javascript'
            elif 'java' in detected:
                return 'java'
            elif 'html' in detected:
                return 'html'
            elif 'css' in detected:
                return 'css'
            elif 'sql' in detected:
                return 'sql'
            elif 'bash' in detected or 'shell' in detected:
                return 'bash'
            
            logger.info(f"זוהתה שפה באמצעות Pygments: {detected}")
            return detected
            
        except ClassNotFound:
            logger.warning("לא הצלחתי לזהות שפה באמצעות Pygments")
        
        # בדיקה רביעית - ניתוח כללי של הטקסט
        detected = self._analyze_code_structure(sanitized_code)
        if detected != 'text':
            logger.info(f"זוהתה שפה לפי מבנה: {detected}")
            return detected
        
        # ברירת מחדל
        logger.info("לא הצלחתי לזהות שפה, משתמש ב-text")
        return 'text'
    
    def _analyze_code_structure(self, code: str) -> str:
        """ניתוח מבנה הקוד לזיהוי שפה"""
        
        # ספירת סימנים מיוחדים
        braces = code.count('{') + code.count('}')
        brackets = code.count('[') + code.count(']')
        parens = code.count('(') + code.count(')')
        semicolons = code.count(';')
        colons = code.count(':')
        indentation_lines = len([line for line in code.split('\n') if line.startswith('    ') or line.startswith('\t')])
        
        total_lines = len(code.split('\n'))
        
        # חישוב יחסים
        if total_lines > 0:
            brace_ratio = braces / total_lines
            semicolon_ratio = semicolons / total_lines
            indent_ratio = indentation_lines / total_lines
            
            # כללי זיהוי
            if indent_ratio > 0.3 and brace_ratio < 0.1:
                return 'python'
            elif brace_ratio > 0.2 and semicolon_ratio > 0.2:
                return 'javascript'
            elif '<' in code and '>' in code and 'html' in code.lower():
                return 'html'
            elif code.strip().startswith('{') or code.strip().startswith('['):
                return 'json'
        
        return 'text'
    
    @cached(expire_seconds=1800, key_prefix="syntax_highlight")  # cache ל-30 דקות
    def highlight_code(self, code: str, programming_language: str, output_format: str = 'html') -> str:
        """הדגשת תחביר מתקדמת עם caching"""
        try:
            # אם הקוד ריק או קצר מדי, אל תבצע highlighting
            if not code or len(code.strip()) < 10:
                return code
            
            # בחירת lexer מתאים
            lexer = None
            try:
                # נסה לפי שפה
                if programming_language and programming_language != 'text':
                    lexer = get_lexer_by_name(programming_language)
            except ClassNotFound:
                try:
                    # נסה לפי תוכן
                    lexer = guess_lexer(code)
                except ClassNotFound:
                    # ברירת מחדל
                    lexer = get_lexer_by_name('text')
            
            if not lexer:
                return code
            
            # בחירת formatter
            if output_format == 'html':
                formatter = HtmlFormatter(
                    style=self.style,
                    noclasses=True,
                    nowrap=True,
                    linenos=False
                )
            elif output_format == 'terminal':
                formatter = TerminalFormatter()
            else:
                return code  # פורמט לא נתמך
            
            # ביצוע highlighting
            highlighted = highlight(code, lexer, formatter)
            
            # ניקוי HTML אם נדרש
            if output_format == 'html':
                # הסרת tags מיותרים שעלולים לגרום לבעיות בטלגרם
                highlighted = self._clean_html_for_telegram(highlighted)
            
            return highlighted
            
        except Exception as e:
            logger.error(f"שגיאה בהדגשת תחביר: {e}")
            # במקרה של שגיאה, החזר את הקוד המקורי
            return code
    
    def _clean_html_for_telegram(self, html_code: str) -> str:
        """ניקוי HTML לתאימות עם Telegram"""
        try:
            # הסרת attributes מיותרים
            import re
            
            # שמירה על tags בסיסיים בלבד
            allowed_tags = ['b', 'i', 'u', 'code', 'pre', 'em', 'strong']
            
            # הסרת style attributes
            html_code = re.sub(r'\s+style="[^"]*"', '', html_code)
            
            # הסרת class attributes
            html_code = re.sub(r'\s+class="[^"]*"', '', html_code)
            
            # החלפת span tags ב-code tags
            html_code = re.sub(r'<span[^>]*>', '<code>', html_code)
            html_code = re.sub(r'</span>', '</code>', html_code)
            
            return html_code
            
        except Exception as e:
            logger.error(f"שגיאה בניקוי HTML: {e}")
            return html_code
    
    def create_code_image(self, code: str, programming_language: str, 
                         width: int = 800, font_size: int = 12) -> bytes:
        """יצירת תמונה של קוד עם הדגשת תחביר"""
        
        try:
            # הדגשת הקוד
            highlighted_html = self.highlight_code(code, programming_language, 'html')
            
            # יצירת HTML מלא
            full_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <style>
                    body {{
                        font-family: 'Courier New', monospace;
                        font-size: {font_size}px;
                        margin: 20px;
                        background-color: #f8f8f8;
                        line-height: 1.4;
                    }}
                    .highlight {{
                        background-color: white;
                        border: 1px solid #ddd;
                        border-radius: 5px;
                        padding: 15px;
                        overflow: auto;
                    }}
                </style>
            </head>
            <body>
                {highlighted_html}
            </body>
            </html>
            """
            
            # המרה לתמונה (זה ידרוש התקנת wkhtmltopdf או כלי דומה)
            # כרגע נחזיר placeholder
            
            # יצירת תמונה פשוטה עם הקוד
            img = Image.new('RGB', (width, max(400, len(code.split('\n')) * 20)), 'white')
            draw = ImageDraw.Draw(img)
            
            try:
                font = ImageFont.truetype("DejaVuSansMono.ttf", font_size)
            except:
                font = ImageFont.load_default()
            
            # כתיבת הקוד
            y_position = 10
            for line in code.split('\n'):
                draw.text((10, y_position), line, fill='black', font=font)
                y_position += font_size + 2
            
            # המרה לבייטים
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='PNG')
            img_byte_arr = img_byte_arr.getvalue()
            
            logger.info(f"נוצרה תמונת קוד בגודל {width}px")
            return img_byte_arr
            
        except Exception as e:
            logger.error(f"שגיאה ביצירת תמונת קוד: {e}")
            return None
    
    def get_code_stats(self, code: str) -> Dict[str, Any]:
        """חישוב סטטיסטיקות קוד"""
        
        lines = code.split('\n')
        
        stats = {
            'total_lines': len(lines),
            'non_empty_lines': len([line for line in lines if line.strip()]),
            'comment_lines': 0,
            'code_lines': 0,
            'blank_lines': 0,
            'characters': len(code),
            'characters_no_spaces': len(code.replace(' ', '').replace('\t', '').replace('\n', '')),
            'words': len(code.split()),
            'functions': 0,
            'classes': 0,
            'complexity_score': 0
        }
        
        # ספירת סוגי שורות
        for line in lines:
            stripped = line.strip()
            if not stripped:
                stats['blank_lines'] += 1
            elif stripped.startswith('#') or stripped.startswith('//') or stripped.startswith('/*'):
                stats['comment_lines'] += 1
            else:
                stats['code_lines'] += 1
        
        # זיהוי פונקציות ומחלקות
        stats['functions'] = len(re.findall(r'\bdef\s+\w+\s*\(|\bfunction\s+\w+\s*\(', code, re.IGNORECASE))
        stats['classes'] = len(re.findall(r'\bclass\s+\w+\s*[:\{]', code, re.IGNORECASE))
        
        # חישוב מורכבות בסיסית
        complexity_indicators = [
            'if ', 'elif ', 'else:', 'for ', 'while ', 'try:', 'except:', 'catch',
            'switch', 'case:', 'break', 'continue', 'return', '&&', '||', '?:'
        ]
        
        for indicator in complexity_indicators:
            stats['complexity_score'] += code.lower().count(indicator.lower())
        
        # ניקוד קריאות (באמצעות textstat)
        try:
            stats['readability_score'] = textstat.flesch_reading_ease(code)
        except:
            stats['readability_score'] = 0
        
        logger.info(f"חושבו סטטיסטיקות לקוד: {stats['total_lines']} שורות, {stats['characters']} תווים")
        return stats

    def analyze_code(self, code: str, programming_language: str) -> Dict[str, Any]:
        """ניתוח קוד מהיר אך משמעותי לכל שפה

        מחזיר מדדים כמו ציון איכות, מורכבות, בעיות נפוצות, שורות ארוכות ועוד.
        """
        try:
            language = (programming_language or 'text')
            stats = self.get_code_stats(code)

            # בסיס לציון איכות: מתחיל ב-100 ויורד לפי כשלים/מורכבות
            quality_score = 100

            # עונשים על מורכבות גבוהה
            complexity = int(stats.get('complexity_score', 0) or 0)
            if complexity > 80:
                quality_score -= 30
            elif complexity > 40:
                quality_score -= 20
            elif complexity > 20:
                quality_score -= 10

            # שורות ארוכות
            long_line_limit = 120
            lines = code.split('\n')
            long_lines = [i + 1 for i, ln in enumerate(lines) if len(ln) > long_line_limit]
            quality_score -= min(len(long_lines), 20)  # עד 20 נק'

            # הערות TODO/FIXME
            todo_count = sum(1 for ln in lines if ('TODO' in ln or 'FIXME' in ln))
            quality_score -= min(todo_count * 2, 10)

            # יחס הערות נמוך מאוד (אם כמעט ואין הערות)
            comment_lines = int(stats.get('comment_lines', 0))
            total_lines = max(1, int(stats.get('total_lines', 1)))
            if total_lines >= 50 and comment_lines / total_lines < 0.02:
                quality_score -= 5

            # בדיקות תוכן בסיסיות לפי שפה
            code_smells: List[str] = []
            low = code.lower()
            if language.lower() == 'python':
                if 'eval(' in low:
                    code_smells.append('eval שימוש מסוכן')
                    quality_score -= 10
                if 'exec(' in low:
                    code_smells.append('exec שימוש מסוכן')
                    quality_score -= 10
                if 'subprocess.Popen' in code or 'os.system(' in low:
                    code_smells.append('הרצת פקודות מערכת')
                    quality_score -= 5
                # בדיקת תחביר מהירה
                syntax = self.validate_syntax(code, 'python')
                if not syntax.get('is_valid', True):
                    code_smells.append('שגיאות תחביר')
                    quality_score -= 15
            elif language.lower() in ('javascript', 'typescript'):
                if 'eval(' in low:
                    code_smells.append('eval שימוש מסוכן')
                    quality_score -= 10
                if 'document.write(' in low:
                    code_smells.append('document.write עלול להיות לא בטוח')
                    quality_score -= 5
            elif language.lower() == 'sql':
                if 'select *' in low:
                    code_smells.append('SELECT * — מומלץ לציין עמודות')
                    quality_score -= 3
            elif language.lower() in ('bash', 'sh'):
                if 'curl' in low and '| sh' in low:
                    code_smells.append('צינור curl ל-shell עלול להיות מסוכן')
                    quality_score -= 10

            # ניקוד סופי בגבולות [0, 100]
            quality_score = max(0, min(100, quality_score))

            return {
                'quality_score': quality_score,
                'complexity': complexity,
                'long_lines': long_lines,
                'readability': stats.get('readability_score', 0),
                'summary': {
                    'total_lines': stats.get('total_lines', 0),
                    'functions': stats.get('functions', 0),
                    'classes': stats.get('classes', 0),
                },
                'code_smells': code_smells,
            }
        except Exception as e:
            logger.error(f"שגיאה בניתוח קוד: {e}")
            return {'error': str(e)}
    
    def extract_functions(self, code: str, programming_language: str) -> List[Dict[str, str]]:
        """חילוץ רשימת פונקציות מהקוד"""
        
        functions = []
        
        patterns = {
            'python': r'def\s+(\w+)\s*\([^)]*\)\s*:',
            'javascript': r'function\s+(\w+)\s*\([^)]*\)\s*{',
            'java': r'(?:public|private|protected)?\s*(?:static)?\s*\w+\s+(\w+)\s*\([^)]*\)\s*{',
            'cpp': r'\w+\s+(\w+)\s*\([^)]*\)\s*{',
            'c': r'\w+\s+(\w+)\s*\([^)]*\)\s*{',
            'php': r'function\s+(\w+)\s*\([^)]*\)\s*{'
        }
        
        if programming_language in patterns:
            matches = re.finditer(patterns[programming_language], code, re.MULTILINE)
            
            for match in matches:
                func_name = match.group(1)
                start_pos = match.start()
                
                # מצא את השורה
                lines_before = code[:start_pos].split('\n')
                line_number = len(lines_before)
                
                functions.append({
                    'name': func_name,
                    'line': line_number,
                    'signature': match.group(0)
                })
        
        logger.info(f"נמצאו {len(functions)} פונקציות בקוד")
        return functions
    
    def validate_syntax(self, code: str, programming_language: str) -> Dict[str, Any]:
        """בדיקת תחביר של הקוד"""
        
        result = {
            'is_valid': True,
            'errors': [],
            'warnings': [],
            'suggestions': []
        }
        
        # בדיקות בסיסיות לפי שפה
        if programming_language == 'python':
            try:
                compile(code, '<string>', 'exec')
            except SyntaxError as e:
                result['is_valid'] = False
                result['errors'].append({
                    'line': e.lineno,
                    'message': str(e),
                    'type': 'SyntaxError'
                })
        
        elif programming_language == 'json':
            try:
                import json
                json.loads(code)
            except json.JSONDecodeError as e:
                result['is_valid'] = False
                result['errors'].append({
                    'line': e.lineno,
                    'message': str(e),
                    'type': 'JSONDecodeError'
                })
        
        # בדיקות כלליות
        lines = code.split('\n')
        
        # בדיקת סוגריים מאוזנים
        brackets_balance = {'(': 0, '[': 0, '{': 0}
        for i, line in enumerate(lines, 1):
            for char in line:
                if char in '([{':
                    brackets_balance[char] += 1
                elif char in ')]}':
                    opening_map = {')': '(', ']': '[', '}': '{'}
                    opening_bracket = opening_map.get(char)
                    if opening_bracket and brackets_balance[opening_bracket] > 0:
                        brackets_balance[opening_bracket] -= 1
                    else:
                        result['warnings'].append({
                            'line': i,
                            'message': f'סוגריים לא מאוזנים: {char}',
                            'type': 'UnbalancedBrackets'
                        })
        
        # בדיקה אם נותרו סוגריים פתוחים
        for bracket, count in brackets_balance.items():
            if count > 0:
                result['warnings'].append({
                    'line': len(lines),
                    'message': f'סוגריים לא סגורים: {bracket}',
                    'type': 'UnclosedBrackets'
                })
        
        # הצעות לשיפור
        if programming_language == 'python':
            # בדיקת import לא בשימוש
            imports = re.findall(r'import\s+(\w+)', code)
            for imp in imports:
                if code.count(imp) == 1:  # מופיע רק ב-import
                    result['suggestions'].append({
                        'message': f'ייבוא לא בשימוש: {imp}',
                        'type': 'UnusedImport'
                    })
        
        logger.info(f"נבדק תחביר עבור {programming_language}: {'תקין' if result['is_valid'] else 'לא תקין'}")
        return result
    
    def minify_code(self, code: str, programming_language: str) -> str:
        """דחיסת קוד (הסרת רווחים מיותרים והערות)"""
        
        if programming_language == 'javascript':
            # הסרת הערות חד-שורתיות
            code = re.sub(r'//.*$', '', code, flags=re.MULTILINE)
            # הסרת הערות רב-שורתיות
            code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
            # הסרת רווחים מיותרים
            code = re.sub(r'\s+', ' ', code)
            
        elif programming_language == 'python':
            lines = code.split('\n')
            minified_lines = []
            
            for line in lines:
                # הסרת הערות
                if '#' in line:
                    line = line[:line.index('#')]
                
                stripped = line.strip()
                if stripped:  # רק שורות לא ריקות
                    minified_lines.append(stripped)
            
            code = '\n'.join(minified_lines)
        
        elif programming_language == 'css':
            # הסרת הערות
            code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
            # הסרת רווחים מיותרים
            code = re.sub(r'\s+', ' ', code)
            # הסרת רווחים סביב סימנים
            code = re.sub(r'\s*([{}:;,])\s*', r'\1', code)
        
        logger.info(f"דחוס קוד בשפה {programming_language}")
        return code.strip()
    
    @cached(expire_seconds=900, key_prefix="batch_highlight")  # cache ל-15 דקות
    def highlight_code_batch(self, codes_data: List[Dict[str, str]], output_format: str = 'html') -> Dict[str, str]:
        """הדגשת תחביר לmultiple קבצים בו-זמנית"""
        try:
            results = {}
            
            for code_data in codes_data:
                file_name = code_data.get('file_name', 'unknown')
                code = code_data.get('code', '')
                language = code_data.get('programming_language', 'text')
                
                try:
                    highlighted = self.highlight_code(code, language, output_format)
                    results[file_name] = highlighted
                except Exception as e:
                    logger.error(f"שגיאה בהדגשת {file_name}: {e}")
                    results[file_name] = code  # החזר קוד מקורי במקרה של שגיאה
            
            return results
            
        except Exception as e:
            logger.error(f"שגיאה בהדגשת batch: {e}")
            return {}
    
    @cached(expire_seconds=600, key_prefix="batch_analyze")  # cache ל-10 דקות
    def analyze_code_batch(self, codes_data: List[Dict[str, str]]) -> Dict[str, Dict]:
        """ניתוח batch של קבצים"""
        try:
            results = {}
            
            for code_data in codes_data:
                file_name = code_data.get('file_name', 'unknown')
                code = code_data.get('code', '')
                language = code_data.get('programming_language', 'text')
                
                try:
                    analysis = self.analyze_code(code, language)
                    results[file_name] = analysis
                except Exception as e:
                    logger.error(f"שגיאה בניתוח {file_name}: {e}")
                    results[file_name] = {'error': str(e)}
            
            return results
            
        except Exception as e:
            logger.error(f"שגיאה בניתוח batch: {e}")
            return {}

# יצירת אינסטנס גלובלי
code_processor = CodeProcessor()
