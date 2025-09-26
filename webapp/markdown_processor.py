#!/usr/bin/env python3
"""
Markdown Processor for Code Keeper WebApp
מעבד Markdown מתקדם עם תמיכה ב-GFM, Task Lists, Math, Mermaid ועוד
"""

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
    
    # תגיות שאסור לכלול כלל (גם לא את התוכן שלהן)
    DANGEROUS_TAGS = {
        'script', 'style', 'iframe', 'embed', 'object', 
        'applet', 'meta', 'link', 'base'
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
        self.in_dangerous_tag = None  # Track if we're inside a dangerous tag
    
    def handle_starttag(self, tag, attrs):
        # Check if this is a dangerous tag
        if tag in self.DANGEROUS_TAGS:
            self.in_dangerous_tag = tag
            return
            
        # Skip if we're inside a dangerous tag
        if self.in_dangerous_tag:
            return
            
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
        # Check if we're closing a dangerous tag
        if tag in self.DANGEROUS_TAGS and self.in_dangerous_tag == tag:
            self.in_dangerous_tag = None
            return
            
        # Skip if we're inside a dangerous tag
        if self.in_dangerous_tag:
            return
            
        if tag in self.ALLOWED_TAGS and self.stack and self.stack[-1] == tag:
            self.result.append(f'</{tag}>')
            self.stack.pop()
    
    def handle_data(self, data):
        # אל תוסיף data אם אנחנו בתוך תג מסוכן
        if self.in_dangerous_tag:
            return
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
        original_list_item_close = self.md.renderer.rules.get('list_item_close')
        
        def render_list_item_open(tokens, idx, options, env, renderer):
            """Renderer ל-list_item_open עם תמיכה ב-checkboxes"""
            token = tokens[idx]

            # בדוק אם זו task list item
            if idx + 2 < len(tokens):
                next_token = tokens[idx + 1]
                if next_token.type == 'inline' and next_token.content:
                    # בדוק אם מתחיל ב-[ ] או [x] - בטוח מפני ReDoS
                    content = next_token.content

                    # בדיקה ידנית במקום regex
                    is_task_item = False
                    is_checked = False
                    task_text = content

                    if len(content) >= 3 and content[0] == '[' and content[2] == ']':
                        check_char = content[1]
                        if check_char in ' xX':
                            is_task_item = True
                            is_checked = check_char.lower() == 'x'
                            # חלץ את הטקסט אחרי ה-checkbox
                            if len(content) > 3:
                                pos_after = 3
                                while pos_after < len(content) and content[pos_after] in ' \t':
                                    pos_after += 1
                                task_text = content[pos_after:] if pos_after < len(content) else ''
                            else:
                                task_text = ''

                    if is_task_item:
                        # צור task ID מהטקסט הנקי (לא מהתוכן המקורי)
                        task_id = hashlib.md5(task_text.strip().encode()).hexdigest()[:8]

                        # הוסף class ו-data attribute ל-li
                        token.attrSet('class', 'task-list-item')
                        token.attrSet('data-checked', 'true' if is_checked else 'false')

                        # עדכן את התוכן להסרת ה-checkbox pattern
                        next_token.content = task_text

                        # הוסף checkbox לתחילת ה-inline
                        checkbox_html = f'<input type="checkbox" class="task-list-item-checkbox" {"checked" if is_checked else ""} data-task-id="{task_id}">'
                        if next_token.children and len(next_token.children) > 0 and next_token.children[0].type == 'text':
                            first_child = next_token.children[0]
                            first_child.content = checkbox_html + ' ' + task_text
                            next_token.content = ''
                        else:
                            next_token.content = checkbox_html + ' ' + task_text

            # שמור התנהגות ברירת המחדל באמצעות renderer
            return renderer.renderToken(tokens, idx, options)

        def render_list_item_close(tokens, idx, options, env, renderer):
            """Renderer ל-list_item_close ששומר התנהגות ברירת מחדל"""
            return renderer.renderToken(tokens, idx, options)
        
        # החלף את ה-renderer
        self.md.renderer.rules['list_item_open'] = render_list_item_open
        self.md.renderer.rules['list_item_close'] = render_list_item_close
    
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
            # Fallback: ניקוי בסיסי עם HTML parser במקום regex מסוכן
            # שימוש ב-HTML parser מונע ReDoS attacks
            try:
                # ניסיון ראשון: השתמש ב-SafeHTMLCleaner שלנו
                cleaner = SafeHTMLCleaner()
                cleaner.feed(html)
                return cleaner.get_clean_html()
            except Exception:
                # אם נכשל, נעשה ניקוי מינימלי בטוח
                # במקום regex מסוכן, נעבור תו-תו בצורה בטוחה
                return self._safe_minimal_clean(html)
    
    def _safe_minimal_clean(self, html: str) -> str:
        """
        ניקוי מינימלי בטוח ללא regex מסוכן
        מונע ReDoS attacks על ידי עיבוד תו-תו
        """
        if not html:
            return ""
        
        # רשימת תגיות מסוכנות לחסימה
        dangerous_tags = {'script', 'style', 'iframe', 'embed', 'object', 'applet', 'meta', 'link', 'base'}
        
        # רשימת event handlers לחסימה
        event_handlers = {
            'onabort', 'onblur', 'onchange', 'onclick', 'ondblclick', 'onerror', 'onfocus',
            'onkeydown', 'onkeypress', 'onkeyup', 'onload', 'onmousedown', 'onmousemove',
            'onmouseout', 'onmouseover', 'onmouseup', 'onreset', 'onresize', 'onselect',
            'onsubmit', 'onunload', 'onbeforeunload', 'onhashchange', 'onmessage', 'onoffline',
            'ononline', 'onpopstate', 'onredo', 'onstorage', 'onundo', 'onunload'
        }
        
        result = []
        i = 0
        length = len(html)
        
        while i < length:
            if html[i] == '<':
                # מצאנו תחילת תג
                tag_start = i
                i += 1
                
                # דלג על רווחים
                while i < length and html[i].isspace():
                    i += 1
                
                # בדוק אם זו תגית סגירה
                is_closing = False
                if i < length and html[i] == '/':
                    is_closing = True
                    i += 1
                    while i < length and html[i].isspace():
                        i += 1
                
                # קרא את שם התג
                tag_name_start = i
                while i < length and (html[i].isalnum() or html[i] in '-_'):
                    i += 1
                tag_name = html[tag_name_start:i].lower()
                
                # בדוק אם התג מסוכן
                if tag_name in dangerous_tags:
                    # דלג על כל התג
                    while i < length and html[i] != '>':
                        i += 1
                    if i < length:
                        i += 1  # דלג על '>'
                    continue
                
                # עבור תגים בטוחים, בדוק attributes
                tag_content = html[tag_start:i]
                
                # חפש את סוף התג
                tag_end = i
                in_quotes = False
                quote_char = None
                
                while tag_end < length:
                    if not in_quotes:
                        if html[tag_end] == '>':
                            break
                        elif html[tag_end] in '"\'':
                            in_quotes = True
                            quote_char = html[tag_end]
                    else:
                        if html[tag_end] == quote_char and (tag_end == 0 or html[tag_end-1] != '\\'):
                            in_quotes = False
                            quote_char = None
                    tag_end += 1
                
                if tag_end < length:
                    tag_full = html[tag_start:tag_end+1]
                    
                    # בדוק event handlers בצורה בטוחה
                    tag_lower = tag_full.lower()
                    has_event_handler = False
                    for handler in event_handlers:
                        # חיפוש פשוט ללא regex
                        if handler in tag_lower:
                            # בדוק שזה באמת attribute ולא חלק מטקסט
                            handler_pos = tag_lower.find(handler)
                            if handler_pos > 0:
                                # בדוק שיש = אחרי ה-handler
                                next_pos = handler_pos + len(handler)
                                while next_pos < len(tag_lower) and tag_lower[next_pos].isspace():
                                    next_pos += 1
                                if next_pos < len(tag_lower) and tag_lower[next_pos] == '=':
                                    has_event_handler = True
                                    break
                    
                    # בדוק javascript: URLs
                    if 'javascript:' in tag_lower or 'vbscript:' in tag_lower or 'data:text/html' in tag_lower:
                        has_event_handler = True
                    
                    if not has_event_handler:
                        result.append(tag_full)
                    
                    i = tag_end + 1
                else:
                    i = length
            else:
                # טקסט רגיל
                text_start = i
                while i < length and html[i] != '<':
                    i += 1
                result.append(html[text_start:i])
        
        return ''.join(result)
    
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
        """זיהוי נוסחאות מתמטיות בטקסט - בטוח מפני ReDoS"""
        # בדיקה פשוטה ומהירה ללא regex
        # חפש סימנים של math
        math_indicators = [
            ('$', '$'),      # inline or display math
            ('\\(', '\\)'),  # LaTeX inline
            ('\\[', '\\]'),  # LaTeX display
        ]
        
        for start_delim, end_delim in math_indicators:
            start_pos = text.find(start_delim)
            if start_pos != -1:
                # מצאנו התחלה, חפש סוף
                end_pos = text.find(end_delim, start_pos + len(start_delim))
                if end_pos != -1:
                    # יש גם התחלה וגם סוף - כנראה יש math
                    return True
        
        return False
    
    def _detect_mermaid(self, text: str) -> bool:
        """זיהוי בלוקי Mermaid בטקסט - בטוח מפני ReDoS"""
        # בדיקה פשוטה ללא regex
        text_lower = text.lower()
        return '```mermaid' in text_lower
    
    def _detect_tasks(self, text: str) -> bool:
        """זיהוי task lists בטקסט - בטוח מפני ReDoS"""
        # בדיקה פשוטה לכל שורה
        for line in text.split('\n'):
            stripped = line.lstrip()
            # בדוק אם מתחיל עם סימן רשימה ואז checkbox
            if stripped.startswith('- [ ]') or stripped.startswith('- [x]') or stripped.startswith('- [X]'):
                return True
            if stripped.startswith('* [ ]') or stripped.startswith('* [x]') or stripped.startswith('* [X]'):
                return True
            if stripped.startswith('+ [ ]') or stripped.startswith('+ [x]') or stripped.startswith('+ [X]'):
                return True
            # בדוק גם בלי סימן רשימה
            if stripped.startswith('[ ]') or stripped.startswith('[x]') or stripped.startswith('[X]'):
                return True
        return False
    
    def _has_headers(self, text: str) -> bool:
        """בדיקה אם יש כותרות בטקסט - בטוח מפני ReDoS"""
        # בדיקה פשוטה לכל שורה
        for line in text.split('\n'):
            stripped = line.lstrip()
            # בדוק אם מתחיל עם # (1-6 פעמים)
            if stripped.startswith('#'):
                # ספור כמה #
                hash_count = 0
                for char in stripped:
                    if char == '#':
                        hash_count += 1
                    else:
                        break
                # בדוק שיש 1-6 # ואז רווח
                if 1 <= hash_count <= 6 and len(stripped) > hash_count and stripped[hash_count] == ' ':
                    return True
        return False
    
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
        """עיבוד בלוקי Mermaid - בטוח מפני ReDoS"""
        result = []
        pos = 0
        
        # חפש בלוקי mermaid בצורה בטוחה ללא regex
        start_tag = '<pre><code class="language-mermaid">'
        end_tag = '</code></pre>'
        
        while True:
            # מצא את תחילת הבלוק הבא
            start_idx = html.find(start_tag, pos)
            if start_idx == -1:
                # אין יותר בלוקים, הוסף את השארית
                result.append(html[pos:])
                break
            
            # הוסף את הטקסט לפני הבלוק
            result.append(html[pos:start_idx])
            
            # מצא את סוף הבלוק
            content_start = start_idx + len(start_tag)
            end_idx = html.find(end_tag, content_start)
            
            if end_idx == -1:
                # בלוק לא סגור, השאר כמו שהוא
                result.append(html[start_idx:])
                break
            
            # חלץ את התוכן
            content = html[content_start:end_idx]
            content_unescaped = html_lib.unescape(content)
            
            # צור את ה-div החדש
            mermaid_div = f'<div class="mermaid-diagram" data-mermaid="{html_lib.escape(content_unescaped, quote=True)}">{html_lib.escape(content_unescaped)}</div>'
            result.append(mermaid_div)
            
            # המשך מאחרי הבלוק
            pos = end_idx + len(end_tag)
        
        return ''.join(result)
    
    def _process_math_blocks(self, html: str) -> str:
        """עיבוד בלוקי מתמטיקה - בטוח מפני ReDoS"""
        
        def process_delimited_content(text: str, start_delim: str, end_delim: str, 
                                     wrapper_tag: str, css_class: str) -> str:
            """עיבוד תוכן עם delimiters בצורה בטוחה"""
            result = []
            pos = 0
            
            while True:
                # מצא את ה-delimiter הבא
                start_idx = text.find(start_delim, pos)
                if start_idx == -1:
                    result.append(text[pos:])
                    break
                
                # הוסף טקסט לפני
                result.append(text[pos:start_idx])
                
                # מצא את הסוף
                content_start = start_idx + len(start_delim)
                end_idx = text.find(end_delim, content_start)
                
                if end_idx == -1:
                    # לא נמצא סוף, השאר כמו שהוא
                    result.append(text[start_idx:])
                    break
                
                # חלץ תוכן
                content = text[content_start:end_idx]
                
                # אל תעבד אם התוכן ארוך מדי (הגנה נוספת)
                if len(content) > 10000:
                    result.append(text[start_idx:end_idx + len(end_delim)])
                else:
                    # צור את ה-wrapper
                    escaped_content = html_lib.escape(content)
                    escaped_attr = html_lib.escape(content, quote=True)
                    
                    if wrapper_tag == 'div':
                        if start_delim == '$$':
                            wrapped = f'<div class="{css_class}" data-math="{escaped_attr}">$${escaped_content}$$</div>'
                        else:  # \[
                            wrapped = f'<div class="{css_class}" data-math="{escaped_attr}">\\[{escaped_content}\\]</div>'
                    else:  # span
                        if start_delim == '$':
                            wrapped = f'<span class="{css_class}" data-math="{escaped_attr}">${escaped_content}$</span>'
                        else:  # \(
                            wrapped = f'<span class="{css_class}" data-math="{escaped_attr}">\\({escaped_content}\\)</span>'
                    
                    result.append(wrapped)
                
                pos = end_idx + len(end_delim)
            
            return ''.join(result)
        
        # עיבוד display math ($$...$$)
        html = process_delimited_content(html, '$$', '$$', 'div', 'math-display')
        
        # עיבוד LaTeX-style display math (\[...\])
        html = process_delimited_content(html, '\\[', '\\]', 'div', 'math-display')
        
        # עיבוד inline math ($...$)
        html = process_delimited_content(html, '$', '$', 'span', 'math-inline')
        
        # עיבוד LaTeX-style inline math (\(...\))
        html = process_delimited_content(html, '\\(', '\\)', 'span', 'math-inline')
        
        return html
    
    def _strip_html_tags(self, text: str) -> str:
        """הסרת תגיות HTML בצורה בטוחה"""
        result = []
        in_tag = False
        
        for char in text:
            if char == '<':
                in_tag = True
            elif char == '>':
                in_tag = False
            elif not in_tag:
                result.append(char)
        
        return ''.join(result)
    
    def _process_code_blocks_safe(self, text: str) -> str:
        """עיבוד code blocks בצורה בטוחה מפני ReDoS"""
        result = []
        pos = 0
        
        while True:
            # חפש תחילת code block
            start = text.find('```', pos)
            if start == -1:
                result.append(text[pos:])
                break
            
            # הוסף טקסט לפני
            result.append(text[pos:start])
            
            # חפש שפה (אופציונלי)
            lang_start = start + 3
            newline_pos = text.find('\n', lang_start)
            if newline_pos == -1:
                # אין newline, לא code block תקין
                result.append('```')
                pos = lang_start
                continue
            
            # חלץ שפה
            lang = text[lang_start:newline_pos].strip()
            if not lang or not lang.replace('-', '').replace('_', '').isalnum():
                lang = 'text'
            
            # חפש סוף code block
            code_start = newline_pos + 1
            end = text.find('```', code_start)
            if end == -1:
                # code block לא סגור
                result.append(text[start:])
                break
            
            # חלץ קוד
            code = text[code_start:end]
            
            # צור HTML
            escaped_code = html_lib.escape(code)
            result.append(f'<pre><code class="language-{lang}">{escaped_code}</code></pre>')
            
            pos = end + 3
        
        return ''.join(result)
    
    def _wrap_list_items_safe(self, text: str) -> str:
        """עטיפת list items ב-ul בצורה בטוחה מפני ReDoS"""
        lines = text.split('\n')
        result = []
        in_list = False
        list_items = []
        
        for line in lines:
            if line.strip().startswith('<li'):
                # זה list item
                if not in_list:
                    in_list = True
                    list_items = []
                list_items.append(line)
            else:
                # לא list item
                if in_list:
                    # סיים את הרשימה
                    result.append('<ul>')
                    result.extend(list_items)
                    result.append('</ul>')
                    in_list = False
                    list_items = []
                result.append(line)
        
        # אם נשארנו עם רשימה פתוחה
        if in_list and list_items:
            result.append('<ul>')
            result.extend(list_items)
            result.append('</ul>')
        
        return '\n'.join(result)
    
    def _process_emphasis_safe(self, text: str) -> str:
        """עיבוד bold ו-italic בצורה בטוחה מפני ReDoS"""
        
        def process_delimiter(text: str, delimiter: str, tag: str) -> str:
            """עיבוד delimiter ספציפי"""
            result = []
            parts = text.split(delimiter)
            
            # אם אין מספיק חלקים, אין מה לעבד
            if len(parts) < 3:
                return text
            
            in_emphasis = False
            for i, part in enumerate(parts):
                if i == 0:
                    result.append(part)
                elif i == len(parts) - 1:
                    if in_emphasis:
                        result.append(delimiter)
                    result.append(part)
                else:
                    if in_emphasis:
                        # סגור את התג
                        result.append(f'</{tag}>')
                        in_emphasis = False
                    else:
                        # פתח תג חדש
                        result.append(f'<{tag}>')
                        in_emphasis = True
                    result.append(part)
            
            # אם נשארנו עם תג פתוח
            if in_emphasis:
                result.append(f'</{tag}>')
            
            return ''.join(result)
        
        # עיבוד לפי סדר עדיפות
        # Bold + Italic (*** או ___)
        text = process_delimiter(text, '***', 'strong><em')
        text = text.replace('</strong><em>', '</em></strong>')
        text = process_delimiter(text, '___', 'strong><em')
        text = text.replace('</strong><em>', '</em></strong>')
        
        # Bold (** או __)
        text = process_delimiter(text, '**', 'strong')
        text = process_delimiter(text, '__', 'strong')
        
        # Italic (* או _)
        text = process_delimiter(text, '*', 'em')
        text = process_delimiter(text, '_', 'em')
        
        return text
    
    def _process_strikethrough_safe(self, text: str) -> str:
        """עיבוד strikethrough בצורה בטוחה מפני ReDoS"""
        result = []
        pos = 0
        
        while True:
            # חפש ~~
            start = text.find('~~', pos)
            if start == -1:
                result.append(text[pos:])
                break
            
            # הוסף טקסט לפני
            result.append(text[pos:start])
            
            # חפש סוף ~~
            end = text.find('~~', start + 2)
            if end == -1:
                # לא נמצא סוף
                result.append(text[start:])
                break
            
            # חלץ תוכן
            content = text[start + 2:end]
            
            # אל תעבד אם ריק או ארוך מדי
            if content and len(content) < 1000:
                result.append(f'<del>{html_lib.escape(content)}</del>')
            else:
                result.append(text[start:end + 2])
            
            pos = end + 2
        
        return ''.join(result)
    
    def _process_headers_safe(self, text: str) -> str:
        """עיבוד headers בצורה בטוחה מפני ReDoS"""
        lines = text.split('\n')
        result = []
        
        for line in lines:
            processed = False
            
            # בדוק אם זו כותרת
            if line.startswith('#'):
                hash_count = 0
                for char in line:
                    if char == '#':
                        hash_count += 1
                    else:
                        break
                
                # בדוק שיש 1-6 # ואז רווח
                if 1 <= hash_count <= 6 and len(line) > hash_count:
                    # דלג על רווחים אחרי ה-#
                    idx = hash_count
                    while idx < len(line) and line[idx] in ' \t':
                        idx += 1
                    
                    if idx < len(line):
                        # יש תוכן אחרי הרווחים
                        header_text = line[idx:]
                        result.append(f'<h{hash_count}>{header_text}</h{hash_count}>')
                        processed = True
            
            if not processed:
                result.append(line)
        
        return '\n'.join(result)
    
    def _process_links_and_images_safe(self, text: str) -> str:
        """עיבוד links ו-images בצורה בטוחה מפני ReDoS"""
        result = []
        i = 0
        
        while i < len(text):
            # חפש תחילת link או image
            if i < len(text) - 1 and text[i:i+2] == '![':
                # זה image
                end_bracket = text.find(']', i + 2)
                if end_bracket != -1 and end_bracket + 1 < len(text) and text[end_bracket + 1] == '(':
                    end_paren = text.find(')', end_bracket + 2)
                    if end_paren != -1:
                        alt_text = text[i + 2:end_bracket]
                        img_url = text[end_bracket + 2:end_paren]
                        result.append(f'<img src="{img_url}" alt="{alt_text}">')
                        i = end_paren + 1
                        continue
            elif text[i] == '[':
                # אולי זה link
                end_bracket = text.find(']', i + 1)
                if end_bracket != -1 and end_bracket + 1 < len(text) and text[end_bracket + 1] == '(':
                    end_paren = text.find(')', end_bracket + 2)
                    if end_paren != -1:
                        link_text = text[i + 1:end_bracket]
                        link_url = text[end_bracket + 2:end_paren]
                        result.append(f'<a href="{link_url}">{link_text}</a>')
                        i = end_paren + 1
                        continue
            
            # לא link/image, העתק את התו
            result.append(text[i])
            i += 1
        
        return ''.join(result)
    
    def _process_inline_code_safe(self, text: str) -> str:
        """עיבוד inline code בצורה בטוחה מפני ReDoS"""
        result = []
        i = 0
        
        while i < len(text):
            if text[i] == '`':
                # חפש את הסוף
                end = text.find('`', i + 1)
                if end != -1:
                    code = text[i + 1:end]
                    result.append(f'<code>{code}</code>')
                    i = end + 1
                else:
                    result.append(text[i])
                    i += 1
            else:
                result.append(text[i])
                i += 1
        
        return ''.join(result)
    
    def _process_blockquotes_safe(self, text: str) -> str:
        """עיבוד blockquotes בצורה בטוחה מפני ReDoS"""
        lines = text.split('\n')
        result = []
        
        for line in lines:
            # בדוק גם > רגיל וגם &gt; (escaped)
            if line.startswith('&gt;'):
                # דלג על &gt; ורווחים
                idx = 4  # אורך של '&gt;'
                while idx < len(line) and line[idx] in ' \t':
                    idx += 1
                
                if idx < len(line):
                    quote_text = line[idx:]
                    result.append(f'<blockquote>{quote_text}</blockquote>')
                else:
                    result.append('<blockquote></blockquote>')
            elif line.startswith('>'):
                # דלג על > ורווחים
                idx = 1
                while idx < len(line) and line[idx] in ' \t':
                    idx += 1
                
                if idx < len(line):
                    quote_text = line[idx:]
                    result.append(f'<blockquote>{quote_text}</blockquote>')
                else:
                    result.append('<blockquote></blockquote>')
            else:
                result.append(line)
        
        return '\n'.join(result)
    
    def _process_lists_safe(self, text: str) -> str:
        """עיבוד lists בצורה בטוחה מפני ReDoS"""
        lines = text.split('\n')
        result = []
        
        for line in lines:
            processed = False
            
            # בדוק אם זה list item
            if line.startswith('* ') or line.startswith('- '):
                # דלג על הסימן והרווח
                list_text = line[2:]
                result.append(f'<li>{list_text}</li>')
                processed = True
            elif len(line) > 0 and line[0].isdigit():
                # אולי זה numbered list
                idx = 0
                while idx < len(line) and line[idx].isdigit():
                    idx += 1
                
                if idx < len(line) and line[idx:idx+2] == '. ':
                    list_text = line[idx+2:]
                    result.append(f'<li>{list_text}</li>')
                    processed = True
            
            if not processed:
                result.append(line)
        
        return '\n'.join(result)
    
    def _process_task_lists_safe(self, text: str) -> str:
        """עיבוד task lists בצורה בטוחה מפני ReDoS"""
        lines = text.split('\n')
        result = []
        
        for line in lines:
            # נקה רווחים מההתחלה בצורה בטוחה
            stripped = line.lstrip()
            indent = len(line) - len(stripped)
            
            # בדוק אם מתחיל עם סימני רשימה
            list_prefix = ''
            if stripped.startswith('- '):
                list_prefix = '- '
                stripped = stripped[2:]
            elif stripped.startswith('* '):
                list_prefix = '* '
                stripped = stripped[2:]
            elif stripped.startswith('+ '):
                list_prefix = '+ '
                stripped = stripped[2:]
            
            # בדוק אם זה task list
            is_task = False
            is_checked = False
            task_text = stripped
            
            if stripped.startswith('[ ] '):
                is_task = True
                is_checked = False
                task_text = stripped[4:]
            elif stripped.startswith('[x] ') or stripped.startswith('[X] '):
                is_task = True
                is_checked = True
                task_text = stripped[4:]
            
            # צור את השורה החדשה
            if is_task:
                checkbox = '<input type="checkbox" class="task-list-item-checkbox"' + (' checked' if is_checked else '') + '>'
                result.append(f'{" " * indent}<li class="task-list-item">{checkbox} {html_lib.escape(task_text)}</li>')
            else:
                result.append(line)
        
        return '\n'.join(result)
    
    def _generate_toc(self, html: str) -> str:
        """יצירת תוכן עניינים מהכותרות - בטוח מפני ReDoS"""
        headers = []
        pos = 0
        
        # חפש headers בצורה בטוחה ללא regex עם backtracking
        while pos < len(html):
            # חפש תחילת header
            h_start = html.find('<h', pos)
            if h_start == -1:
                break
            
            # בדוק שזה h1-h6
            if h_start + 2 >= len(html):
                break
                
            level_char = html[h_start + 2]
            if not level_char.isdigit() or level_char not in '123456':
                pos = h_start + 1
                continue
            
            # מצא סוף התג הפותח
            tag_end = html.find('>', h_start)
            if tag_end == -1:
                break
            
            # מצא תג סגירה
            close_tag = f'</h{level_char}>'
            content_end = html.find(close_tag, tag_end)
            if content_end == -1:
                pos = tag_end + 1
                continue
            
            # חלץ תוכן
            content = html[tag_end + 1:content_end]
            headers.append((level_char, content))
            
            pos = content_end + len(close_tag)
        
        if not headers:
            return ''
        
        toc_items = []
        for level, title in headers:
            # נקה HTML tags מהכותרת בצורה בטוחה
            clean_title = self._strip_html_tags(title)
            # צור anchor ID
            # צור anchor ID בטוח
            anchor_chars = []
            for char in clean_title.lower():
                if char.isalnum() or char in ' -':
                    anchor_chars.append(char)
            anchor_id = ''.join(anchor_chars)
            
            # החלף רווחים ומקפים מרובים במקף בודד
            anchor_parts = []
            prev_was_separator = False
            for char in anchor_id:
                if char in ' -':
                    if not prev_was_separator:
                        anchor_parts.append('-')
                        prev_was_separator = True
                else:
                    anchor_parts.append(char)
                    prev_was_separator = False
            anchor_id = ''.join(anchor_parts).strip('-')
            
            indent = '  ' * (int(level) - 1)
            toc_items.append(f'{indent}- [{clean_title}](#{anchor_id})')
        
        return '\n'.join(toc_items)
    
    def _basic_markdown_to_html(self, text: str) -> str:
        """מעבד Markdown בסיסי (fallback)"""
        # Escape HTML
        text = html_lib.escape(text)
        
        # Headers - בטוח מפני ReDoS
        text = self._process_headers_safe(text)
        
        # Bold and italic - בטוח מפני ReDoS
        text = self._process_emphasis_safe(text)
        
        # Strikethrough - בטוח מפני ReDoS
        text = self._process_strikethrough_safe(text)
        
        # Links and Images - בטוח מפני ReDoS
        text = self._process_links_and_images_safe(text)
        
        # Code blocks - בטוח מפני ReDoS
        text = self._process_code_blocks_safe(text)
        
        # Inline code - בטוח מפני ReDoS
        text = self._process_inline_code_safe(text)
        
        # Blockquotes - בטוח מפני ReDoS
        text = self._process_blockquotes_safe(text)
        
        # Task lists FIRST - בטוח מפני ReDoS (חייב להיות לפני רשימות רגילות!)
        text = self._process_task_lists_safe(text)
        
        # Lists (basic) - בטוח מפני ReDoS
        text = self._process_lists_safe(text)
        
        # Paragraphs and line breaks
        if self.config['breaks']:
            # החלף line breaks בצורה בטוחה
            text = text.replace('\n', '<br>\n')
        
        # Wrap consecutive li elements in ul - בטוח מפני ReDoS
        text = self._wrap_list_items_safe(text)
        
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