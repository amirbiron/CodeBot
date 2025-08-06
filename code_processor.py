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

logger = logging.getLogger(__name__)

# קביעת זרע לשחזור תוצאות זיהוי שפה
DetectorFactory.seed = 0

class CodeProcessor:
    """מחלקה לעיבוד קטעי קוד"""
    
    def __init__(self):
        self.language_patterns = self._init_language_patterns()
        self.common_extensions = self._init_extensions()
        self.style = get_style_by_name(config.HIGHLIGHT_THEME)
        
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
                matches = re.findall(pattern, code, re.MULTILINE | re.IGNORECASE)
                score += len(matches)
            
            if score > 0:
                language_scores[language] = score
        
        if language_scores:
            detected = max(language_scores, key=language_scores.get)
            logger.info(f"זוהתה שפה לפי דפוסים: {detected} (ניקוד: {language_scores[detected]})")
            return detected
        
        # בדיקה שלישית - באמצעות Pygments
        try:
            lexer = guess_lexer(code)
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
        detected = self._analyze_code_structure(code)
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
    
    def highlight_code(self, code: str, programming_language: str, output_format: str = 'html') -> str:
        """הדגשת תחביר של קוד"""
        
        try:
            # קבלת הלקסר המתאים
            if programming_language == 'text':
                lexer = get_lexer_by_name('text', stripnl=False)
            else:
                try:
                    lexer = get_lexer_by_name(programming_language, stripnl=False)
                except ClassNotFound:
                    lexer = get_lexer_by_name('text', stripnl=False)
            
            # בחירת פורמטר
            if output_format == 'html':
                formatter = HtmlFormatter(
                    style=config.HIGHLIGHT_THEME,
                    linenos=True,
                    cssclass="highlight",
                    noclasses=True
                )
            elif output_format == 'terminal':
                formatter = TerminalFormatter()
            else:
                formatter = HtmlFormatter(style=config.HIGHLIGHT_THEME)
            
            # יצירת הקוד המודגש
            highlighted = highlight(code, lexer, formatter)
            
            logger.info(f"הודגש קוד בשפה {programming_language} בפורמט {output_format}")
            return highlighted
            
        except Exception as e:
            logger.error(f"שגיאה בהדגשת קוד: {e}")
            return f"<pre><code>{code}</code></pre>"
    
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
                    corresponding = {')', ']', '}'}[ord(char) - ord('(')]
                    if brackets_balance[corresponding] > 0:
                        brackets_balance[corresponding] -= 1
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

# יצירת אינסטנס גלובלי
code_processor = CodeProcessor()
