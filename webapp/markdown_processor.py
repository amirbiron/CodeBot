#!/usr/bin/env python3
"""
Markdown Processor for Code Keeper WebApp
מעבד Markdown מתקדם עם תמיכה ב-GFM, Task Lists, Math, Mermaid ועוד
"""

import re
import json
import html as html_lib
from typing import Optional, Dict, Any
import hashlib
from html.parser import HTMLParser

# נסה לייבא bleach לניקוי HTML
try:
    import bleach
    from bleach.css_sanitizer import CSSSanitizer
    BLEACH_AVAILABLE = True
except ImportError:
    BLEACH_AVAILABLE = False

# נסה לייבא markdown-it-py (ספרייה מתקדמת)
try:
    import markdown_it
    from markdown_it import MarkdownIt
    from markdown_it.token import Token
    MARKDOWN_IT_AVAILABLE = True
except ImportError:
    MARKDOWN_IT_AVAILABLE = False

# נסה לייבא python-markdown כ-fallback
try:
    import markdown
    PYTHON_MARKDOWN_AVAILABLE = True
except ImportError:
    PYTHON_MARKDOWN_AVAILABLE = False


class SafeHTMLCleaner(HTMLParser):
    """HTML parser שמנקה תגיות מסוכנות"""
    
    ALLOWED_TAGS = {
        'p', 'br', 'hr', 'div', 'span',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'strong', 'b', 'em', 'i', 'u', 's', 'del', 'ins',
        'ul', 'ol', 'li',
        'a', 'img',
        'blockquote', 'q', 'cite',
        'code', 'pre',
        'table', 'thead', 'tbody', 'tr', 'th', 'td',
        'input',  # For checkboxes only
        'sup', 'sub',
    }
    
    ALLOWED_ATTRS = {
        'a': {'href', 'title', 'target', 'rel'},
        'img': {'src', 'alt', 'title', 'width', 'height'},
        'input': {'type', 'checked', 'disabled', 'data-task-id'},
        '*': {'class', 'id'},
    }
    
    def __init__(self):
        super().__init__()
        self.result = []
        self.stack = []
    
    def handle_starttag(self, tag, attrs):
        if tag not in self.ALLOWED_TAGS:
            return
            
        # Filter attributes
        filtered_attrs = []
        allowed_attrs_for_tag = self.ALLOWED_ATTRS.get(tag, set()) | self.ALLOWED_ATTRS.get('*', set())
        
        for attr_name, attr_value in attrs:
            # Skip dangerous attributes
            if attr_name.startswith('on'):  # Event handlers
                continue
            if attr_name in allowed_attrs_for_tag:
                # Clean attribute values
                if attr_name == 'href' or attr_name == 'src':
                    # Block dangerous protocols
                    if attr_value and any(attr_value.lower().startswith(p) for p in ['javascript:', 'vbscript:', 'data:text/html']):
                        continue
                filtered_attrs.append((attr_name, attr_value))
        
        # Special handling for input tags
        if tag == 'input':
            # Only allow checkboxes
            if not any(attr[0] == 'type' and attr[1] == 'checkbox' for attr in filtered_attrs):
                return
        
        # Build clean tag
        attrs_str = ' '.join(f'{name}="{html_lib.escape(value)}"' for name, value in filtered_attrs)
        if attrs_str:
            self.result.append(f'<{tag} {attrs_str}>')
        else:
            self.result.append(f'<{tag}>')
        self.stack.append(tag)
    
    def handle_endtag(self, tag):
        if tag in self.ALLOWED_TAGS and self.stack and self.stack[-1] == tag:
            self.result.append(f'</{tag}>')
            self.stack.pop()
    
    def handle_data(self, data):
        self.result.append(html_lib.escape(data))
    
    def get_clean_html(self):
        # Close any unclosed tags
        while self.stack:
            tag = self.stack.pop()
            self.result.append(f'</{tag}>')
        return ''.join(self.result)


class MarkdownProcessor:
    """מעבד Markdown מתקדם עם תמיכה מלאה ב-GFM ותוספים"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        אתחול המעבד עם קונפיגורציה
        
        config: {
            'breaks': True,        # הפיכת שורות חדשות ל-<br>
            'linkify': True,       # URLs הופכים ללינקים אוטומטיים
            'typographer': True,   # טיפוגרפיה חכמה
            'html': False,         # חסימת HTML גולמי לאבטחה
            'highlight': True,     # הדגשת תחביר בבלוקי קוד
            'mermaid': True,       # תמיכה בתרשימי Mermaid
            'math': True,          # תמיכה בנוסחאות מתמטיות
            'task_lists': True,    # תמיכה ב-Task Lists
            'emoji': True,         # תמיכה ב-emoji shortcuts
        }
        """
        self.config = config or {}
        self.config.setdefault('breaks', True)
        self.config.setdefault('linkify', True)
        self.config.setdefault('typographer', True)
        self.config.setdefault('html', False)
        self.config.setdefault('highlight', True)
        self.config.setdefault('mermaid', True)
        self.config.setdefault('math', True)
        self.config.setdefault('task_lists', True)
        self.config.setdefault('emoji', True)
        
        # אתחול המעבד
        self._init_processor()
        
    def _init_processor(self):
        """אתחול מעבד ה-Markdown"""
        if MARKDOWN_IT_AVAILABLE:
            # השתמש ב-markdown-it-py (הכי מתקדם)
            self.md = MarkdownIt('commonmark', {
                'breaks': self.config['breaks'],
                'linkify': self.config['linkify'],
                'typographer': self.config['typographer'],
                'html': self.config['html'],
            })
            
            # הפעל תוספים
            self.md.enable(['table', 'strikethrough'])
            
            # הוסף renderer מותאם אישית ל-task lists
            if self.config['task_lists']:
                self._setup_task_lists_renderer()
                
        elif PYTHON_MARKDOWN_AVAILABLE:
            # Fallback ל-python-markdown
            extensions = ['extra', 'codehilite', 'toc', 'nl2br', 'sane_lists']
            
            if self.config['task_lists']:
                # נוסיף תמיכה בסיסית ב-task lists
                extensions.append('markdown_checklist.extension')
                
            self.md = markdown.Markdown(extensions=extensions)
        else:
            # אם אין ספריות - נשתמש במעבד בסיסי
            self.md = None
    
    def _setup_task_lists_renderer(self):
        """הגדרת renderer מותאם אישית ל-task lists"""
        if not MARKDOWN_IT_AVAILABLE or not hasattr(self, 'md'):
            return
            
        # שמור את ה-renderer המקורי
        original_list_item_open = self.md.renderer.rules.get('list_item_open')
        
        def render_list_item_open(tokens, idx, options, env, renderer):
            """Renderer ל-list_item_open עם תמיכה ב-checkboxes"""
            token = tokens[idx]
            
            # בדוק אם זו task list item
            if idx + 2 < len(tokens):
                next_token = tokens[idx + 1]
                if next_token.type == 'inline' and next_token.content:
                    # בדוק אם מתחיל ב-[ ] או [x]
                    content = next_token.content
                    task_match = re.match(r'^\[([ xX])\]\s*(.*)', content)
                    if task_match:
                        checked = task_match.group(1).lower() == 'x'
                        task_text = task_match.group(2)
                        
                        # צור task ID מהטקסט הנקי (לא מהתוכן המקורי)
                        task_id = hashlib.md5(task_text.strip().encode()).hexdigest()[:8]
                        
                        # הוסף class ו-data attribute ל-li
                        token.attrSet('class', 'task-list-item')
                        token.attrSet('data-checked', 'true' if checked else 'false')
                        
                        # עדכן את התוכן להסרת ה-checkbox pattern
                        next_token.content = task_text
                        
                        # במקום לשנות את children, צור HTML מותאם אישית
                        checkbox_html = f'<input type="checkbox" class="task-list-item-checkbox" {"checked" if checked else ""} data-task-id="{task_id}">'
                        
                        # שנה את התוכן של next_token כדי לכלול את ה-checkbox
                        # נשתמש ב-HTML inline token במקום לשנות את המבנה
                        if next_token.children and len(next_token.children) > 0:
                            # אם יש children, הוסף את ה-checkbox לפני הראשון
                            first_child = next_token.children[0]
                            if first_child.type == 'text':
                                # שלב את ה-checkbox עם הטקסט
                                first_child.content = checkbox_html + ' ' + task_text
                                next_token.content = ''  # נקה את התוכן הראשי
                        else:
                            # אם אין children, פשוט החלף את התוכן
                            next_token.content = checkbox_html + ' ' + task_text
            
            # קרא ל-renderer המקורי
            if original_list_item_open:
                return original_list_item_open(tokens, idx, options, env, renderer)
            return '<li>'
        
        # החלף את ה-renderer
        self.md.renderer.rules['list_item_open'] = render_list_item_open
    
    def sanitize_html(self, html: str) -> str:
        """
        ניקוי HTML למניעת XSS
        
        Args:
            html: HTML לניקוי
            
        Returns:
            HTML מנוקה ובטוח
        """
        if BLEACH_AVAILABLE:
            # רשימת תגיות מותרות
            allowed_tags = [
                'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                'p', 'br', 'hr',
                'strong', 'b', 'em', 'i', 'del', 's', 'strike', 'code', 'pre',
                'ul', 'ol', 'li',
                'blockquote', 'q',
                'a', 'img',
                'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td',
                'div', 'span', 'section', 'article',
                'input',  # עבור checkboxes
                'sup', 'sub',  # עבור נוסחאות
            ]
            
            # רשימת attributes מותרים
            allowed_attributes = {
                '*': ['class', 'id'],
                'a': ['href', 'title', 'target', 'rel'],
                'img': ['src', 'alt', 'title', 'width', 'height'],
                'input': ['type', 'checked', 'disabled', 'data-task-id'],
                'div': ['data-mermaid', 'data-math'],
                'span': ['data-math'],
                'code': ['class'],
                'pre': ['class'],
            }
            
            # CSS sanitizer
            css_sanitizer = CSSSanitizer(allowed_css_properties=[
                'color', 'background-color', 'font-size', 'font-weight',
                'text-align', 'margin', 'padding', 'border',
                'width', 'height', 'max-width', 'max-height'
            ])
            
            # ניקוי HTML
            cleaned = bleach.clean(
                html,
                tags=allowed_tags,
                attributes=allowed_attributes,
                css_sanitizer=css_sanitizer,
                strip=True
            )
            
            # וודא שלינקים נפתחים בחלון חדש
            cleaned = bleach.linkify(
                cleaned,
                callbacks=[self._add_target_blank],
                skip_tags=['pre', 'code']
            )
            
            return cleaned
        else:
            # Fallback: ניקוי בסיסי אבל יותר בטוח
            # הסר תגיות script ו-style עם כל הווריאציות
            # תומך ב: </script>, </script >, </SCRIPT>, וכו'
            html = re.sub(r'<script[^>]*>.*?</script\s*>', '', html, flags=re.IGNORECASE | re.DOTALL)
            html = re.sub(r'<style[^>]*>.*?</style\s*>', '', html, flags=re.IGNORECASE | re.DOTALL)
            
            # הסר תגיות script/style שלא נסגרו
            html = re.sub(r'<script[^>]*>', '', html, flags=re.IGNORECASE)
            html = re.sub(r'<style[^>]*>', '', html, flags=re.IGNORECASE)
            html = re.sub(r'</script\s*>', '', html, flags=re.IGNORECASE)
            html = re.sub(r'</style\s*>', '', html, flags=re.IGNORECASE)
            
            # הסר event handlers (כל הווריאציות)
            html = re.sub(r'\s*on\w+\s*=\s*["\'][^"\']*["\']', '', html, flags=re.IGNORECASE)
            html = re.sub(r'\s*on\w+\s*=\s*[^\s>]+', '', html, flags=re.IGNORECASE)
            html = re.sub(r'\s*on\w+\s*=', '', html, flags=re.IGNORECASE)  # גם ללא ערך
            
            # הסר javascript: ו-data: URLs
            html = re.sub(r'javascript\s*:', '', html, flags=re.IGNORECASE)
            html = re.sub(r'data\s*:text/html', '', html, flags=re.IGNORECASE)
            html = re.sub(r'vbscript\s*:', '', html, flags=re.IGNORECASE)
            
            # הסר תגיות מסוכנות נוספות
            dangerous_tags = ['iframe', 'embed', 'object', 'applet', 'meta', 'link', 'base']
            for tag in dangerous_tags:
                html = re.sub(f'<{tag}[^>]*>.*?</{tag}\s*>', '', html, flags=re.IGNORECASE | re.DOTALL)
                html = re.sub(f'<{tag}[^>]*/?>', '', html, flags=re.IGNORECASE)
            
            # אם עדיין יש חשש, נשתמש ב-HTML parser לניקוי נוסף
            try:
                cleaner = SafeHTMLCleaner()
                cleaner.feed(html)
                html = cleaner.get_clean_html()
            except Exception:
                # במקרה של כישלון, נחזיר טקסט escaped
                html = html_lib.escape(html)
            
            return html
    
    def _add_target_blank(self, attrs, new=False):
        """הוסף target="_blank" לקישורים חיצוניים"""
        attrs = dict(attrs) if attrs else {}
        
        # בדוק אם זה קישור חיצוני
        href = attrs.get((None, 'href'), '')
        if href and (href.startswith('http://') or href.startswith('https://')):
            attrs[(None, 'target')] = '_blank'
            attrs[(None, 'rel')] = 'noopener noreferrer'
        
        return attrs
    
    def render(self, text: str) -> Dict[str, Any]:
        """
        עיבוד Markdown ל-HTML מעוצב
        
        מחזיר:
        {
            'html': str,           # ה-HTML המעובד
            'toc': str,            # תוכן עניינים (אם רלוונטי)
            'has_math': bool,      # האם יש נוסחאות מתמטיות
            'has_mermaid': bool,   # האם יש תרשימי Mermaid
            'has_tasks': bool,     # האם יש task lists
            'metadata': dict       # מטא-דאטה נוספת
        }
        """
        if not text:
            return {
                'html': '',
                'toc': '',
                'has_math': False,
                'has_mermaid': False,
                'has_tasks': False,
                'metadata': {}
            }
        
        # עיבוד מקדים - זיהוי תכנים מיוחדים
        has_math = self._detect_math(text)
        has_mermaid = self._detect_mermaid(text)
        has_tasks = self._detect_tasks(text)
        
        # עיבוד emoji shortcuts
        if self.config['emoji']:
            text = self._process_emoji(text)
        
        # עיבוד Markdown
        if self.md:
            if MARKDOWN_IT_AVAILABLE:
                # markdown-it-py
                html = self.md.render(text)
            elif PYTHON_MARKDOWN_AVAILABLE:
                # python-markdown
                html = self.md.convert(text)
                self.md.reset()  # נקה את המצב לעיבוד הבא
            else:
                html = self._basic_markdown_to_html(text)
        else:
            # מעבד בסיסי
            html = self._basic_markdown_to_html(text)
        
        # עיבוד נוסף
        if has_mermaid and self.config['mermaid']:
            html = self._process_mermaid_blocks(html)
        
        if has_math and self.config['math']:
            html = self._process_math_blocks(html)
        
        # נקה את ה-HTML למניעת XSS
        html = self.sanitize_html(html)
        
        # הוסף wrapper classes
        html = f'<div class="markdown-content">{html}</div>'
        
        # יצירת תוכן עניינים
        toc = self._generate_toc(html) if self._has_headers(text) else ''
        
        return {
            'html': html,
            'toc': toc,
            'has_math': has_math,
            'has_mermaid': has_mermaid,
            'has_tasks': has_tasks,
            'metadata': {
                'word_count': len(text.split()),
                'char_count': len(text),
                'line_count': len(text.splitlines())
            }
        }
    
    def _detect_math(self, text: str) -> bool:
        """זיהוי נוסחאות מתמטיות בטקסט"""
        # חפש $...$ או $$...$$ או \(...\) או \[...\]
        math_patterns = [
            r'\$[^$]+\$',           # inline math with $
            r'\$\$[^$]+\$\$',       # display math with $$
            r'\\\([^)]+\\\)',       # inline math with \( \)
            r'\\\[[^\]]+\\\]',      # display math with \[ \]
        ]
        for pattern in math_patterns:
            if re.search(pattern, text):
                return True
        return False
    
    def _detect_mermaid(self, text: str) -> bool:
        """זיהוי בלוקי Mermaid בטקסט"""
        return bool(re.search(r'```mermaid', text, re.IGNORECASE))
    
    def _detect_tasks(self, text: str) -> bool:
        """זיהוי task lists בטקסט"""
        return bool(re.search(r'^[\s\-\*]*\[[ xX]\]', text, re.MULTILINE))
    
    def _has_headers(self, text: str) -> bool:
        """בדיקה אם יש כותרות בטקסט"""
        return bool(re.search(r'^#{1,6}\s+', text, re.MULTILINE))
    
    def _process_emoji(self, text: str) -> str:
        """המרת emoji shortcuts לאמוג'י"""
        emoji_map = {
            ':smile:': '😄',
            ':laughing:': '😆',
            ':blush:': '😊',
            ':heart:': '❤️',
            ':star:': '⭐',
            ':fire:': '🔥',
            ':thumbsup:': '👍',
            ':thumbsdown:': '👎',
            ':ok_hand:': '👌',
            ':wave:': '👋',
            ':clap:': '👏',
            ':rocket:': '🚀',
            ':100:': '💯',
            ':tada:': '🎉',
            ':pray:': '🙏',
            ':thinking:': '🤔',
            ':eyes:': '👀',
            ':warning:': '⚠️',
            ':x:': '❌',
            ':white_check_mark:': '✅',
            ':heavy_check_mark:': '✔️',
            ':question:': '❓',
            ':exclamation:': '❗',
            ':bulb:': '💡',
            ':computer:': '💻',
            ':bug:': '🐛',
            ':sparkles:': '✨',
            ':zap:': '⚡',
            ':coffee:': '☕',
            ':beer:': '🍺',
            ':pizza:': '🍕',
            ':cake:': '🍰',
            ':sun:': '☀️',
            ':moon:': '🌙',
            ':cloud:': '☁️',
            ':umbrella:': '☔',
            ':snowflake:': '❄️',
            ':rainbow:': '🌈',
        }
        
        for shortcode, emoji in emoji_map.items():
            text = text.replace(shortcode, emoji)
        
        return text
    
    def _process_mermaid_blocks(self, html: str) -> str:
        """עיבוד בלוקי Mermaid"""
        # החלף בלוקי mermaid ב-div מיוחד
        pattern = r'<pre><code class="language-mermaid">(.*?)</code></pre>'
        
        def replace_mermaid(match):
            content = html_lib.unescape(match.group(1))
            return f'<div class="mermaid-diagram" data-mermaid="{html_lib.escape(content, quote=True)}">{html_lib.escape(content)}</div>'
        
        return re.sub(pattern, replace_mermaid, html, flags=re.DOTALL)
    
    def _process_math_blocks(self, html: str) -> str:
        """עיבוד בלוקי מתמטיקה"""
        # עיבוד display math ($$...$$)
        html = re.sub(
            r'\$\$([^$]+)\$\$',
            r'<div class="math-display" data-math="\1">$$\1$$</div>',
            html
        )
        
        # עיבוד inline math ($...$)
        html = re.sub(
            r'\$([^$]+)\$',
            r'<span class="math-inline" data-math="\1">$\1$</span>',
            html
        )
        
        # עיבוד LaTeX style
        html = re.sub(
            r'\\\[(.*?)\\\]',
            r'<div class="math-display" data-math="\1">\[\1\]</div>',
            html,
            flags=re.DOTALL
        )
        
        html = re.sub(
            r'\\\((.*?)\\\)',
            r'<span class="math-inline" data-math="\1">\(\1\)</span>',
            html
        )
        
        return html
    
    def _generate_toc(self, html: str) -> str:
        """יצירת תוכן עניינים מהכותרות"""
        headers = re.findall(r'<h([1-6])[^>]*>(.*?)</h\1>', html)
        if not headers:
            return ''
        
        toc_items = []
        for level, title in headers:
            # נקה HTML tags מהכותרת
            clean_title = re.sub(r'<[^>]+>', '', title)
            # צור anchor ID
            anchor_id = re.sub(r'[^\w\s-]', '', clean_title.lower())
            anchor_id = re.sub(r'[-\s]+', '-', anchor_id)
            
            indent = '  ' * (int(level) - 1)
            toc_items.append(f'{indent}- [{clean_title}](#{anchor_id})')
        
        return '\n'.join(toc_items)
    
    def _basic_markdown_to_html(self, text: str) -> str:
        """מעבד Markdown בסיסי (fallback)"""
        # Escape HTML
        text = html_lib.escape(text)
        
        # Headers
        text = re.sub(r'^######\s+(.+)$', r'<h6>\1</h6>', text, flags=re.MULTILINE)
        text = re.sub(r'^#####\s+(.+)$', r'<h5>\1</h5>', text, flags=re.MULTILINE)
        text = re.sub(r'^####\s+(.+)$', r'<h4>\1</h4>', text, flags=re.MULTILINE)
        text = re.sub(r'^###\s+(.+)$', r'<h3>\1</h3>', text, flags=re.MULTILINE)
        text = re.sub(r'^##\s+(.+)$', r'<h2>\1</h2>', text, flags=re.MULTILINE)
        text = re.sub(r'^#\s+(.+)$', r'<h1>\1</h1>', text, flags=re.MULTILINE)
        
        # Bold and italic
        text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', text)
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
        text = re.sub(r'___(.+?)___', r'<strong><em>\1</em></strong>', text)
        text = re.sub(r'__(.+?)__', r'<strong>\1</strong>', text)
        text = re.sub(r'_(.+?)_', r'<em>\1</em>', text)
        
        # Strikethrough
        text = re.sub(r'~~(.+?)~~', r'<del>\1</del>', text)
        
        # Links
        text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
        
        # Images
        text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', r'<img src="\2" alt="\1">', text)
        
        # Code blocks
        text = re.sub(r'```(\w+)?\n(.*?)```', lambda m: f'<pre><code class="language-{m.group(1) or "text"}">{html_lib.escape(m.group(2))}</code></pre>', text, flags=re.DOTALL)
        
        # Inline code
        text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
        
        # Blockquotes
        text = re.sub(r'^>\s+(.+)$', r'<blockquote>\1</blockquote>', text, flags=re.MULTILINE)
        
        # Lists (basic)
        text = re.sub(r'^\*\s+(.+)$', r'<li>\1</li>', text, flags=re.MULTILINE)
        text = re.sub(r'^-\s+(.+)$', r'<li>\1</li>', text, flags=re.MULTILINE)
        text = re.sub(r'^\d+\.\s+(.+)$', r'<li>\1</li>', text, flags=re.MULTILINE)
        
        # Task lists
        text = re.sub(r'^[\s\-\*]*\[\s\]\s+(.+)$', r'<li class="task-list-item"><input type="checkbox" class="task-list-item-checkbox"> \1</li>', text, flags=re.MULTILINE)
        text = re.sub(r'^[\s\-\*]*\[[xX]\]\s+(.+)$', r'<li class="task-list-item"><input type="checkbox" class="task-list-item-checkbox" checked> \1</li>', text, flags=re.MULTILINE)
        
        # Paragraphs and line breaks
        if self.config['breaks']:
            text = re.sub(r'\n', '<br>\n', text)
        
        # Wrap consecutive li elements in ul
        text = re.sub(r'(<li[^>]*>.*?</li>\n?)+', lambda m: f'<ul>{m.group(0)}</ul>', text, flags=re.DOTALL)
        
        # Wrap in paragraphs
        paragraphs = []
        for para in text.split('\n\n'):
            if para.strip() and not para.strip().startswith('<'):
                paragraphs.append(f'<p>{para}</p>')
            else:
                paragraphs.append(para)
        
        return '\n'.join(paragraphs)


# יצירת instance גלובלי
default_processor = MarkdownProcessor()


def render_markdown(text: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    פונקציה נוחה לעיבוד Markdown
    
    Args:
        text: טקסט Markdown לעיבוד
        config: קונפיגורציה אופציונלית
    
    Returns:
        מילון עם HTML מעובד ומטא-דאטה
    """
    if config:
        processor = MarkdownProcessor(config)
        return processor.render(text)
    else:
        return default_processor.render(text)