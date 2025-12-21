# מדריך מימוש JSON Formatter

> **מתי להשתמש:** בעת מימוש פיצ'ר עיצוב ואימות JSON בוובאפ  
> **קבצים רלוונטיים:** `services/json_formatter_service.py`, `webapp/json_formatter_api.py`, `webapp/templates/json_formatter.html`, `webapp/static/js/json-formatter.js`, `webapp/static/css/json-formatter.css`

---

## 📋 סקירה כללית

### מטרת הכלי
JSON Formatter הוא כלי לעיצוב, אימות והמרת קוד JSON. הכלי מספק:
- **עיצוב (Beautify)** – הוספת הזחה ושורות חדשות לקריאות
- **דחיסה (Minify)** – הסרת רווחים מיותרים להקטנת גודל
- **אימות (Validate)** – בדיקת תקינות מבנית של JSON
- **המרה** – המרה בין JSON ל-YAML/XML/CSV
- **תצוגת עץ (Tree View)** – ניווט אינטראקטיבי במבנה הנתונים
- **חיפוש** – מציאת מפתחות וערכים בתוך ה-JSON

### קהל יעד
- מפתחים שעובדים עם APIs
- משתמשים שמנתחים logs או configurations
- כל מי שצריך לקרוא/לכתוב JSON בצורה נוחה

---

## 📦 תלויות (Dependencies)

### Python Dependencies

הוסף ל-`requirements/base.txt`:

```txt
PyYAML>=6.0.1    # נדרש להמרת JSON ל-YAML
```

### התקנה

```bash
pip install PyYAML
```

### בדיקת תלויות קיימות

לפני ההתקנה, בדוק אם PyYAML כבר מותקן:

```bash
pip show pyyaml
```

> **הערה:** אם אינך צריך את פיצ'ר ההמרה ל-YAML, ניתן לדלג על התלות הזו. הקוד יתפוס את השגיאה ויציג הודעה מתאימה למשתמש.

---

## 🏗️ ארכיטקטורה

### תרשים רכיבים

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (Browser)                        │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │  CodeMirror │  │  Tree View  │  │  Controls & Actions     │  │
│  │   Editor    │  │  Component  │  │  (Format/Minify/Copy)   │  │
│  └──────┬──────┘  └──────┬──────┘  └───────────┬─────────────┘  │
│         │                │                     │                 │
│         └────────────────┼─────────────────────┘                 │
│                          │                                       │
│                   ┌──────▼──────┐                                │
│                   │ JsonFormatter│                               │
│                   │   Module     │                               │
│                   └──────┬──────┘                                │
└──────────────────────────┼──────────────────────────────────────┘
                           │ HTTP/JSON
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                        Backend (Flask)                           │
├──────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────┐      ┌──────────────────────────────┐  │
│  │ json_formatter_api  │ ──── │  JsonFormatterService        │  │
│  │ (Blueprint)         │      │  - format_json()             │  │
│  │                     │      │  - minify_json()             │  │
│  │ POST /api/json/     │      │  - validate_json()           │  │
│  │     format          │      │  - convert_to_yaml()         │  │
│  │     minify          │      │  - convert_to_xml()          │  │
│  │     validate        │      │  - get_json_stats()          │  │
│  │     convert         │      │  - search_json()             │  │
│  └─────────────────────┘      └──────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### זרימת נתונים

1. **משתמש מזין JSON** → CodeMirror Editor
2. **לחיצה על פעולה** (Format/Minify/Validate/Convert)
3. **בקשת API** → Backend Service
4. **עיבוד ותשובה** → Frontend מעדכן את התצוגה
5. **תצוגת תוצאה** → Editor מעודכן / Tree View / הודעת שגיאה

---

## 🐍 Backend Service

### קובץ: `services/json_formatter_service.py`

```python
"""
JSON Formatter Service
======================
שירות לעיצוב, אימות והמרת JSON.
"""

import json
import re
from typing import Any, Optional
from dataclasses import dataclass


@dataclass
class JsonValidationResult:
    """תוצאת אימות JSON."""
    is_valid: bool
    error_message: Optional[str] = None
    error_line: Optional[int] = None
    error_column: Optional[int] = None


@dataclass
class JsonStats:
    """סטטיסטיקות JSON."""
    total_keys: int
    max_depth: int
    total_values: int
    string_count: int
    number_count: int
    boolean_count: int
    null_count: int
    array_count: int
    object_count: int


class JsonFormatterService:
    """שירות לעיצוב ועיבוד JSON."""

    def __init__(self):
        self.default_indent = 2

    def format_json(
        self,
        json_string: str,
        indent: int = 2,
        sort_keys: bool = False
    ) -> str:
        """
        עיצוב JSON עם הזחה.

        Args:
            json_string: מחרוזת JSON לעיצוב
            indent: מספר רווחים להזחה (ברירת מחדל: 2)
            sort_keys: האם למיין מפתחות אלפבתית

        Returns:
            JSON מעוצב

        Raises:
            json.JSONDecodeError: אם ה-JSON לא תקין
        """
        parsed = json.loads(json_string)
        return json.dumps(
            parsed,
            indent=indent,
            sort_keys=sort_keys,
            ensure_ascii=False
        )

    def minify_json(self, json_string: str) -> str:
        """
        דחיסת JSON להסרת רווחים מיותרים.

        Args:
            json_string: מחרוזת JSON לדחיסה

        Returns:
            JSON דחוס בשורה אחת
        """
        parsed = json.loads(json_string)
        return json.dumps(parsed, separators=(',', ':'), ensure_ascii=False)

    def validate_json(self, json_string: str) -> JsonValidationResult:
        """
        אימות תקינות JSON.

        Args:
            json_string: מחרוזת JSON לאימות

        Returns:
            תוצאת האימות עם פרטי שגיאה אם יש
        """
        try:
            json.loads(json_string)
            return JsonValidationResult(is_valid=True)
        except json.JSONDecodeError as e:
            return JsonValidationResult(
                is_valid=False,
                error_message=e.msg,
                error_line=e.lineno,
                error_column=e.colno
            )

    def get_json_stats(self, json_string: str) -> JsonStats:
        """
        חישוב סטטיסטיקות על מבנה ה-JSON.

        Args:
            json_string: מחרוזת JSON לניתוח

        Returns:
            סטטיסטיקות המבנה
        """
        parsed = json.loads(json_string)
        stats = {
            'total_keys': 0,
            'max_depth': 0,
            'total_values': 0,
            'string_count': 0,
            'number_count': 0,
            'boolean_count': 0,
            'null_count': 0,
            'array_count': 0,
            'object_count': 0
        }

        def analyze(obj: Any, depth: int = 0) -> None:
            stats['max_depth'] = max(stats['max_depth'], depth)

            if isinstance(obj, dict):
                stats['object_count'] += 1
                stats['total_keys'] += len(obj)
                for value in obj.values():
                    analyze(value, depth + 1)
            elif isinstance(obj, list):
                stats['array_count'] += 1
                for item in obj:
                    analyze(item, depth + 1)
            else:
                stats['total_values'] += 1
                if isinstance(obj, str):
                    stats['string_count'] += 1
                elif isinstance(obj, bool):
                    stats['boolean_count'] += 1
                elif isinstance(obj, (int, float)):
                    stats['number_count'] += 1
                elif obj is None:
                    stats['null_count'] += 1

        analyze(parsed)
        return JsonStats(**stats)

    def search_json(
        self,
        json_string: str,
        query: str,
        search_keys: bool = True,
        search_values: bool = True
    ) -> list[dict]:
        """
        חיפוש בתוך JSON.

        Args:
            json_string: מחרוזת JSON לחיפוש
            query: מחרוזת החיפוש
            search_keys: האם לחפש במפתחות
            search_values: האם לחפש בערכים

        Returns:
            רשימת תוצאות עם נתיב לכל התאמה
        """
        parsed = json.loads(json_string)
        results = []
        query_lower = query.lower()

        def search(obj: Any, path: str = '$') -> None:
            if isinstance(obj, dict):
                for key, value in obj.items():
                    current_path = f"{path}.{key}"
                    if search_keys and query_lower in str(key).lower():
                        results.append({
                            'path': current_path,
                            'type': 'key',
                            'match': key
                        })
                    search(value, current_path)
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    search(item, f"{path}[{i}]")
            else:
                if search_values and query_lower in str(obj).lower():
                    results.append({
                        'path': path,
                        'type': 'value',
                        'match': obj
                    })

        search(parsed)
        return results

    def convert_to_yaml(self, json_string: str) -> str:
        """
        המרת JSON ל-YAML.

        Args:
            json_string: מחרוזת JSON להמרה

        Returns:
            מחרוזת YAML

        Note:
            דורש התקנת pyyaml
        """
        try:
            import yaml
            parsed = json.loads(json_string)
            return yaml.dump(
                parsed,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False
            )
        except ImportError:
            raise ImportError("PyYAML is required for YAML conversion")

    def convert_to_xml(self, json_string: str, root_name: str = 'root') -> str:
        """
        המרת JSON ל-XML.

        Args:
            json_string: מחרוזת JSON להמרה
            root_name: שם אלמנט השורש

        Returns:
            מחרוזת XML

        Note:
            מפתחות JSON שאינם תקינים כתגיות XML (רווחים, מספרים בהתחלה וכו')
            יעברו סניטיזציה אוטומטית.
        """
        parsed = json.loads(json_string)

        def sanitize_tag(key: str) -> str:
            """
            ניקוי מפתח JSON להפיכתו לתגית XML חוקית.
            
            חוקי XML לשמות תגיות:
            - חייב להתחיל באות או קו תחתון
            - יכול להכיל אותיות, מספרים, מקפים, נקודות, קווים תחתונים
            - לא יכול להכיל רווחים או תווים מיוחדים
            
            דוגמאות:
            - "User Name" -> "User_Name"
            - "1st_Place" -> "_1st_Place"
            - "e-mail@address" -> "e-mail_address"
            """
            key_str = str(key)
            
            # החלפת תווים לא חוקיים בקו תחתון
            clean_key = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', key_str)
            
            # הסרת קווים תחתונים כפולים
            clean_key = re.sub(r'_+', '_', clean_key)
            
            # הסרת קו תחתון בהתחלה/סוף (אלא אם צריך)
            clean_key = clean_key.strip('_') or 'item'
            
            # תגית XML חייבת להתחיל באות או קו תחתון
            if clean_key and not clean_key[0].isalpha() and clean_key[0] != '_':
                clean_key = f'_{clean_key}'
            
            # מקרה קיצון: מחרוזת ריקה
            if not clean_key:
                clean_key = 'item'
                
            return clean_key

        def to_xml(obj: Any, tag: str) -> str:
            safe_tag = sanitize_tag(tag)
            
            if isinstance(obj, dict):
                children = ''.join(to_xml(v, k) for k, v in obj.items())
                return f'<{safe_tag}>{children}</{safe_tag}>'
            elif isinstance(obj, list):
                # במערך, כל פריט מקבל שם הורה ביחיד או 'item'
                child_tag = safe_tag.rstrip('s') if safe_tag.endswith('s') and len(safe_tag) > 1 else 'item'
                items = ''.join(to_xml(item, child_tag) for item in obj)
                return f'<{safe_tag}>{items}</{safe_tag}>'
            else:
                value = '' if obj is None else self._escape_xml(str(obj))
                return f'<{safe_tag}>{value}</{safe_tag}>'

        return f'<?xml version="1.0" encoding="UTF-8"?>\n{to_xml(parsed, sanitize_tag(root_name))}'

    def _escape_xml(self, text: str) -> str:
        """Escape special XML characters."""
        return (text
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;')
                .replace("'", '&apos;'))

    def fix_common_errors(self, json_string: str) -> tuple[str, list[str]]:
        """
        ניסיון לתקן שגיאות נפוצות ב-JSON.

        Args:
            json_string: מחרוזת JSON עם שגיאות אפשריות

        Returns:
            tuple של (JSON מתוקן, רשימת תיקונים שבוצעו)
        """
        fixes = []
        fixed = json_string

        # תיקון פסיקים מיותרים בסוף arrays/objects
        trailing_comma = re.compile(r',(\s*[\]\}])')
        if trailing_comma.search(fixed):
            fixed = trailing_comma.sub(r'\1', fixed)
            fixes.append('הוסרו פסיקים מיותרים')

        # תיקון מירכאות בודדות למירכאות כפולות
        if "'" in fixed:
            # זהירות: רק אם זה נראה כמו JSON עם מירכאות בודדות
            try:
                json.loads(fixed)
            except json.JSONDecodeError:
                fixed = fixed.replace("'", '"')
                fixes.append('הומרו מירכאות בודדות לכפולות')

        # תיקון undefined/NaN/Infinity
        replacements = [
            (r'\bundefined\b', 'null', 'הומר undefined ל-null'),
            (r'\bNaN\b', 'null', 'הומר NaN ל-null'),
            (r'\bInfinity\b', 'null', 'הומר Infinity ל-null'),
        ]
        for pattern, replacement, message in replacements:
            if re.search(pattern, fixed):
                fixed = re.sub(pattern, replacement, fixed)
                fixes.append(message)

        return fixed, fixes


# Singleton instance
_service_instance = None


def get_json_formatter_service() -> JsonFormatterService:
    """קבלת instance יחיד של השירות."""
    global _service_instance
    if _service_instance is None:
        _service_instance = JsonFormatterService()
    return _service_instance
```

---

## 🌐 API Endpoints

### קובץ: `webapp/json_formatter_api.py`

```python
"""
JSON Formatter API Blueprint
============================
נקודות קצה ל-API של כלי עיצוב JSON.
"""

from flask import Blueprint, request, jsonify
from services.json_formatter_service import get_json_formatter_service
import json

json_formatter_bp = Blueprint('json_formatter', __name__, url_prefix='/api/json')


@json_formatter_bp.route('/format', methods=['POST'])
def format_json():
    """
    עיצוב JSON עם הזחה.

    Request Body:
        {
            "content": "<json string>",
            "indent": 2,           // אופציונלי
            "sort_keys": false     // אופציונלי
        }

    Response:
        {
            "success": true,
            "result": "<formatted json>",
            "stats": { ... }
        }
    """
    data = request.get_json()
    if not data or 'content' not in data:
        return jsonify({'success': False, 'error': 'Missing content'}), 400

    service = get_json_formatter_service()

    try:
        result = service.format_json(
            data['content'],
            indent=data.get('indent', 2),
            sort_keys=data.get('sort_keys', False)
        )
        stats = service.get_json_stats(data['content'])
        return jsonify({
            'success': True,
            'result': result,
            'stats': {
                'total_keys': stats.total_keys,
                'max_depth': stats.max_depth,
                'total_values': stats.total_values
            }
        })
    except json.JSONDecodeError as e:
        return jsonify({
            'success': False,
            'error': f'Invalid JSON: {e.msg}',
            'line': e.lineno,
            'column': e.colno
        }), 400


@json_formatter_bp.route('/minify', methods=['POST'])
def minify_json():
    """
    דחיסת JSON לשורה אחת.

    Request Body:
        { "content": "<json string>" }

    Response:
        {
            "success": true,
            "result": "<minified json>",
            "original_size": 1234,
            "minified_size": 567,
            "savings_percent": 54.0
        }
    """
    data = request.get_json()
    if not data or 'content' not in data:
        return jsonify({'success': False, 'error': 'Missing content'}), 400

    service = get_json_formatter_service()

    try:
        result = service.minify_json(data['content'])
        original_size = len(data['content'].encode('utf-8'))
        minified_size = len(result.encode('utf-8'))
        savings = ((original_size - minified_size) / original_size * 100) if original_size > 0 else 0

        return jsonify({
            'success': True,
            'result': result,
            'original_size': original_size,
            'minified_size': minified_size,
            'savings_percent': round(savings, 1)
        })
    except json.JSONDecodeError as e:
        return jsonify({
            'success': False,
            'error': f'Invalid JSON: {e.msg}',
            'line': e.lineno,
            'column': e.colno
        }), 400


@json_formatter_bp.route('/validate', methods=['POST'])
def validate_json():
    """
    אימות תקינות JSON.

    Request Body:
        { "content": "<json string>" }

    Response (valid):
        {
            "success": true,
            "is_valid": true,
            "stats": { ... }
        }

    Response (invalid):
        {
            "success": true,
            "is_valid": false,
            "error": "Expecting property name",
            "line": 5,
            "column": 12
        }
    """
    data = request.get_json()
    if not data or 'content' not in data:
        return jsonify({'success': False, 'error': 'Missing content'}), 400

    service = get_json_formatter_service()
    result = service.validate_json(data['content'])

    response = {
        'success': True,
        'is_valid': result.is_valid
    }

    if result.is_valid:
        stats = service.get_json_stats(data['content'])
        response['stats'] = {
            'total_keys': stats.total_keys,
            'max_depth': stats.max_depth,
            'string_count': stats.string_count,
            'number_count': stats.number_count,
            'boolean_count': stats.boolean_count,
            'null_count': stats.null_count,
            'array_count': stats.array_count,
            'object_count': stats.object_count
        }
    else:
        response['error'] = result.error_message
        response['line'] = result.error_line
        response['column'] = result.error_column

    return jsonify(response)


@json_formatter_bp.route('/convert', methods=['POST'])
def convert_json():
    """
    המרת JSON לפורמט אחר.

    Request Body:
        {
            "content": "<json string>",
            "target_format": "yaml" | "xml"
        }

    Response:
        {
            "success": true,
            "result": "<converted content>",
            "format": "yaml"
        }
    """
    data = request.get_json()
    if not data or 'content' not in data:
        return jsonify({'success': False, 'error': 'Missing content'}), 400

    target_format = data.get('target_format', 'yaml').lower()
    service = get_json_formatter_service()

    try:
        if target_format == 'yaml':
            result = service.convert_to_yaml(data['content'])
        elif target_format == 'xml':
            result = service.convert_to_xml(data['content'])
        else:
            return jsonify({
                'success': False,
                'error': f'Unsupported format: {target_format}'
            }), 400

        return jsonify({
            'success': True,
            'result': result,
            'format': target_format
        })
    except ImportError as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    except json.JSONDecodeError as e:
        return jsonify({
            'success': False,
            'error': f'Invalid JSON: {e.msg}'
        }), 400


@json_formatter_bp.route('/search', methods=['POST'])
def search_json():
    """
    חיפוש בתוך JSON.

    Request Body:
        {
            "content": "<json string>",
            "query": "search term",
            "search_keys": true,
            "search_values": true
        }

    Response:
        {
            "success": true,
            "results": [
                { "path": "$.users[0].name", "type": "key", "match": "name" },
                { "path": "$.users[0].name", "type": "value", "match": "John" }
            ],
            "total_matches": 2
        }
    """
    data = request.get_json()
    if not data or 'content' not in data or 'query' not in data:
        return jsonify({'success': False, 'error': 'Missing content or query'}), 400

    service = get_json_formatter_service()

    try:
        results = service.search_json(
            data['content'],
            data['query'],
            search_keys=data.get('search_keys', True),
            search_values=data.get('search_values', True)
        )
        return jsonify({
            'success': True,
            'results': results,
            'total_matches': len(results)
        })
    except json.JSONDecodeError as e:
        return jsonify({
            'success': False,
            'error': f'Invalid JSON: {e.msg}'
        }), 400


@json_formatter_bp.route('/fix', methods=['POST'])
def fix_json():
    """
    ניסיון לתקן שגיאות נפוצות ב-JSON.

    Request Body:
        { "content": "<json string with errors>" }

    Response:
        {
            "success": true,
            "result": "<fixed json>",
            "fixes_applied": ["removed trailing commas", "..."]
        }
    """
    data = request.get_json()
    if not data or 'content' not in data:
        return jsonify({'success': False, 'error': 'Missing content'}), 400

    service = get_json_formatter_service()

    try:
        fixed, fixes = service.fix_common_errors(data['content'])
        # נסה לאמת את התוצאה
        json.loads(fixed)
        return jsonify({
            'success': True,
            'result': fixed,
            'fixes_applied': fixes
        })
    except json.JSONDecodeError as e:
        return jsonify({
            'success': False,
            'error': f'Could not fix JSON: {e.msg}',
            'fixes_attempted': fixes if 'fixes' in dir() else []
        }), 400
```

### רישום ה-Blueprint ב-`webapp/__init__.py`

```python
from webapp.json_formatter_api import json_formatter_bp
app.register_blueprint(json_formatter_bp)
```

---

## 🎨 WebApp UI

### קובץ Template: `webapp/templates/json_formatter.html`

```html
{% extends "base.html" %}

{% block title %}JSON Formatter{% endblock %}

{% block extra_css %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/json-formatter.css') }}">
{% endblock %}

{% block content %}
<div class="json-formatter-container">
    <!-- Header -->
    <div class="formatter-header">
        <h1>
            <span class="icon">{ }</span>
            JSON Formatter
        </h1>
        <p class="subtitle">עיצוב, אימות והמרת JSON</p>
    </div>

    <!-- Toolbar -->
    <div class="formatter-toolbar glass-card">
        <div class="toolbar-group primary-actions">
            <button id="btn-format" class="btn btn-primary" title="עיצוב (Ctrl+Shift+F)">
                <span class="btn-icon">✨</span>
                עיצוב
            </button>
            <button id="btn-minify" class="btn btn-secondary" title="דחיסה">
                <span class="btn-icon">📦</span>
                דחיסה
            </button>
            <button id="btn-validate" class="btn btn-info" title="אימות (Ctrl+Enter)">
                <span class="btn-icon">✓</span>
                אימות
            </button>
        </div>

        <div class="toolbar-group">
            <button id="btn-copy" class="btn btn-outline" title="העתקה (Ctrl+C)">
                <span class="btn-icon">📋</span>
                העתק
            </button>
            <button id="btn-clear" class="btn btn-outline" title="ניקוי">
                <span class="btn-icon">🗑️</span>
                נקה
            </button>
            <button id="btn-sample" class="btn btn-outline" title="דוגמה">
                <span class="btn-icon">📝</span>
                דוגמה
            </button>
        </div>

        <div class="toolbar-group">
            <div class="dropdown">
                <button id="btn-convert" class="btn btn-outline dropdown-toggle">
                    <span class="btn-icon">🔄</span>
                    המרה
                </button>
                <div class="dropdown-menu">
                    <button class="dropdown-item" data-format="yaml">YAML</button>
                    <button class="dropdown-item" data-format="xml">XML</button>
                </div>
            </div>
        </div>

        <div class="toolbar-group options">
            <label class="option-label">
                <input type="number" id="indent-size" value="2" min="1" max="8">
                <span>הזחה</span>
            </label>
            <label class="option-label">
                <input type="checkbox" id="sort-keys">
                <span>מיון מפתחות</span>
            </label>
        </div>
    </div>

    <!-- Main Content -->
    <div class="formatter-content">
        <!-- Editor Panel -->
        <div class="editor-panel glass-card">
            <div class="panel-header">
                <span class="panel-title">קלט JSON</span>
                <div class="panel-actions">
                    <button id="btn-upload" class="btn-icon-only" title="העלאת קובץ">
                        📁
                    </button>
                    <input type="file" id="file-upload" accept=".json,.txt" hidden>
                </div>
            </div>
            <div class="panel-body">
                <textarea id="json-input" placeholder='הדבק JSON כאן...
{
    "example": "value",
    "number": 42
}'></textarea>
            </div>
            <div class="panel-footer">
                <span id="input-stats" class="stats-text"></span>
            </div>
        </div>

        <!-- Output Panel -->
        <div class="output-panel glass-card">
            <div class="panel-header">
                <span class="panel-title">תוצאה</span>
                <div class="view-toggle">
                    <button class="view-btn active" data-view="text" title="תצוגת טקסט">
                        📄
                    </button>
                    <button class="view-btn" data-view="tree" title="תצוגת עץ">
                        🌳
                    </button>
                </div>
            </div>
            <div class="panel-body">
                <div id="text-view" class="view-content active">
                    <textarea id="json-output" readonly></textarea>
                </div>
                <div id="tree-view" class="view-content">
                    <div id="json-tree"></div>
                </div>
            </div>
            <div class="panel-footer">
                <span id="output-stats" class="stats-text"></span>
            </div>
        </div>
    </div>

    <!-- Search Bar -->
    <div class="search-bar glass-card collapsed" id="search-bar">
        <div class="search-toggle" id="search-toggle">
            <span class="icon">🔍</span>
            <span>חיפוש</span>
        </div>
        <div class="search-content">
            <input type="text" id="search-input" placeholder="חפש מפתח או ערך...">
            <label class="search-option">
                <input type="checkbox" id="search-keys" checked>
                מפתחות
            </label>
            <label class="search-option">
                <input type="checkbox" id="search-values" checked>
                ערכים
            </label>
            <button id="btn-search" class="btn btn-sm btn-primary">חפש</button>
        </div>
        <div class="search-results" id="search-results"></div>
    </div>

    <!-- Validation Message -->
    <div id="validation-message" class="validation-message hidden"></div>
</div>
{% endblock %}

{% block extra_js %}
<script src="{{ url_for('static', filename='js/json-formatter.js') }}"></script>
{% endblock %}
```

### קובץ CSS: `webapp/static/css/json-formatter.css`

```css
/**
 * JSON Formatter Styles
 * =====================
 * סגנונות לכלי עיצוב JSON
 */

/* === Layout === */
.json-formatter-container {
    max-width: 1400px;
    margin: 0 auto;
    padding: var(--spacing-lg);
    direction: rtl;
}

.formatter-header {
    text-align: center;
    margin-bottom: var(--spacing-lg);
}

.formatter-header h1 {
    font-size: 2rem;
    margin-bottom: var(--spacing-xs);
}

.formatter-header .icon {
    display: inline-block;
    font-family: monospace;
    font-weight: bold;
    color: var(--primary-color);
    margin-left: var(--spacing-sm);
}

.formatter-header .subtitle {
    color: var(--text-muted);
    font-size: 1rem;
}

/* === Toolbar === */
.formatter-toolbar {
    display: flex;
    flex-wrap: wrap;
    gap: var(--spacing-md);
    padding: var(--spacing-md);
    margin-bottom: var(--spacing-lg);
    align-items: center;
}

.toolbar-group {
    display: flex;
    gap: var(--spacing-sm);
    align-items: center;
}

.toolbar-group.primary-actions {
    flex-grow: 1;
}

.toolbar-group.options {
    margin-right: auto;
}

.option-label {
    display: flex;
    align-items: center;
    gap: var(--spacing-xs);
    font-size: 0.875rem;
    color: var(--text-secondary);
}

.option-label input[type="number"] {
    width: 50px;
    padding: var(--spacing-xs);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-sm);
    text-align: center;
}

/* === Buttons === */
.btn {
    display: inline-flex;
    align-items: center;
    gap: var(--spacing-xs);
    padding: var(--spacing-sm) var(--spacing-md);
    border: none;
    border-radius: var(--border-radius);
    font-size: 0.875rem;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s ease;
}

.btn-primary {
    background: var(--primary-gradient);
    color: white;
}

.btn-primary:hover {
    transform: translateY(-1px);
    box-shadow: var(--shadow-md);
}

.btn-secondary {
    background: var(--secondary-color);
    color: white;
}

.btn-info {
    background: var(--info-color);
    color: white;
}

.btn-outline {
    background: transparent;
    border: 1px solid var(--border-color);
    color: var(--text-primary);
}

.btn-outline:hover {
    background: var(--bg-hover);
}

.btn-icon {
    font-size: 1rem;
}

.btn-icon-only {
    background: none;
    border: none;
    font-size: 1.25rem;
    cursor: pointer;
    padding: var(--spacing-xs);
    opacity: 0.7;
    transition: opacity 0.2s;
}

.btn-icon-only:hover {
    opacity: 1;
}

/* === Dropdown === */
.dropdown {
    position: relative;
}

.dropdown-menu {
    position: absolute;
    top: 100%;
    right: 0;
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    box-shadow: var(--shadow-lg);
    min-width: 120px;
    z-index: 100;
    display: none;
}

.dropdown.open .dropdown-menu {
    display: block;
}

.dropdown-item {
    display: block;
    width: 100%;
    padding: var(--spacing-sm) var(--spacing-md);
    border: none;
    background: none;
    text-align: right;
    cursor: pointer;
    transition: background 0.2s;
}

.dropdown-item:hover {
    background: var(--bg-hover);
}

/* === Main Content Panels === */
.formatter-content {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--spacing-lg);
    margin-bottom: var(--spacing-lg);
}

@media (max-width: 992px) {
    .formatter-content {
        grid-template-columns: 1fr;
    }
}

.editor-panel,
.output-panel {
    display: flex;
    flex-direction: column;
    min-height: 500px;
}

.panel-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: var(--spacing-sm) var(--spacing-md);
    border-bottom: 1px solid var(--border-color);
}

.panel-title {
    font-weight: 600;
    color: var(--text-primary);
}

.panel-body {
    flex: 1;
    position: relative;
    min-height: 400px;
}

.panel-footer {
    padding: var(--spacing-sm) var(--spacing-md);
    border-top: 1px solid var(--border-color);
    font-size: 0.75rem;
    color: var(--text-muted);
}

/* === Textarea / Editor === */
#json-input,
#json-output {
    width: 100%;
    height: 100%;
    min-height: 400px;
    padding: var(--spacing-md);
    border: none;
    resize: none;
    font-family: 'Fira Code', 'Monaco', 'Consolas', monospace;
    font-size: 0.875rem;
    line-height: 1.5;
    background: var(--bg-input);
    color: var(--text-primary);
    direction: ltr;
    text-align: left;
}

#json-input:focus,
#json-output:focus {
    outline: none;
}

#json-output {
    background: var(--bg-secondary);
}

/* === View Toggle === */
.view-toggle {
    display: flex;
    gap: 2px;
    background: var(--bg-secondary);
    border-radius: var(--border-radius-sm);
    padding: 2px;
}

.view-btn {
    padding: var(--spacing-xs) var(--spacing-sm);
    border: none;
    background: transparent;
    cursor: pointer;
    border-radius: var(--border-radius-sm);
    opacity: 0.6;
    transition: all 0.2s;
}

.view-btn.active {
    background: var(--bg-card);
    opacity: 1;
}

.view-btn:hover {
    opacity: 1;
}

.view-content {
    display: none;
    height: 100%;
}

.view-content.active {
    display: block;
}

/* === Tree View === */
#json-tree {
    padding: var(--spacing-md);
    font-family: 'Fira Code', monospace;
    font-size: 0.875rem;
    overflow: auto;
    height: 100%;
    direction: ltr;
    text-align: left;
}

.tree-node {
    margin-right: 20px;
}

.tree-key {
    color: var(--json-key-color, #9cdcfe);
    cursor: pointer;
}

.tree-key:hover {
    text-decoration: underline;
}

.tree-value {
    margin-right: 8px;
}

.tree-value.string {
    color: var(--json-string-color, #ce9178);
}

.tree-value.number {
    color: var(--json-number-color, #b5cea8);
}

.tree-value.boolean {
    color: var(--json-boolean-color, #569cd6);
}

.tree-value.null {
    color: var(--json-null-color, #808080);
}

.tree-toggle {
    display: inline-block;
    width: 16px;
    cursor: pointer;
    user-select: none;
}

.tree-toggle::before {
    content: '▼';
    font-size: 0.75rem;
    transition: transform 0.2s;
}

.tree-node.collapsed .tree-toggle::before {
    transform: rotate(-90deg);
}

.tree-node.collapsed .tree-children {
    display: none;
}

/* === Search Bar === */
.search-bar {
    padding: var(--spacing-md);
    margin-bottom: var(--spacing-lg);
}

.search-bar.collapsed .search-content,
.search-bar.collapsed .search-results {
    display: none;
}

.search-toggle {
    display: flex;
    align-items: center;
    gap: var(--spacing-sm);
    cursor: pointer;
    user-select: none;
}

.search-content {
    display: flex;
    gap: var(--spacing-md);
    align-items: center;
    margin-top: var(--spacing-md);
    flex-wrap: wrap;
}

#search-input {
    flex: 1;
    min-width: 200px;
    padding: var(--spacing-sm) var(--spacing-md);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius);
    font-size: 0.875rem;
}

.search-option {
    display: flex;
    align-items: center;
    gap: var(--spacing-xs);
    font-size: 0.875rem;
}

.search-results {
    margin-top: var(--spacing-md);
    max-height: 200px;
    overflow-y: auto;
}

.search-result-item {
    display: flex;
    justify-content: space-between;
    padding: var(--spacing-sm);
    border-bottom: 1px solid var(--border-color);
    font-size: 0.875rem;
    cursor: pointer;
    transition: background 0.2s;
}

.search-result-item:hover {
    background: var(--bg-hover);
}

.search-result-path {
    font-family: monospace;
    color: var(--primary-color);
}

.search-result-type {
    color: var(--text-muted);
    font-size: 0.75rem;
}

/* === Validation Message === */
.validation-message {
    padding: var(--spacing-md);
    border-radius: var(--border-radius);
    margin-bottom: var(--spacing-lg);
    display: flex;
    align-items: flex-start;
    gap: var(--spacing-md);
}

.validation-message.hidden {
    display: none;
}

.validation-message.success {
    background: var(--success-bg);
    border: 1px solid var(--success-color);
    color: var(--success-color);
}

.validation-message.error {
    background: var(--error-bg);
    border: 1px solid var(--error-color);
    color: var(--error-color);
}

.validation-message .icon {
    font-size: 1.25rem;
}

.validation-message .content {
    flex: 1;
}

.validation-message .title {
    font-weight: 600;
    margin-bottom: var(--spacing-xs);
}

.validation-message .details {
    font-size: 0.875rem;
    opacity: 0.9;
}

/* === Loading State === */
.loading {
    position: relative;
    pointer-events: none;
    opacity: 0.7;
}

.loading::after {
    content: '';
    position: absolute;
    top: 50%;
    left: 50%;
    width: 24px;
    height: 24px;
    margin: -12px 0 0 -12px;
    border: 2px solid var(--border-color);
    border-top-color: var(--primary-color);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
}

@keyframes spin {
    to { transform: rotate(360deg); }
}

/* === Glass Card (משותף לפרויקט) === */
.glass-card {
    background: var(--glass-bg, rgba(255, 255, 255, 0.1));
    backdrop-filter: blur(10px);
    border: 1px solid var(--glass-border, rgba(255, 255, 255, 0.2));
    border-radius: var(--border-radius-lg, 12px);
    box-shadow: var(--shadow-lg);
}

/* === Tree View Performance & Warnings === */
.tree-warning {
    background: var(--warning-bg, rgba(255, 193, 7, 0.1));
    border: 1px solid var(--warning-color, #ffc107);
    border-radius: var(--border-radius);
    padding: var(--spacing-md);
    margin-bottom: var(--spacing-md);
    text-align: center;
}

.tree-warning .warning-icon {
    font-size: 2rem;
    display: block;
    margin-bottom: var(--spacing-sm);
}

.tree-truncated {
    color: var(--text-muted);
    font-style: italic;
    opacity: 0.7;
}

.tree-count {
    color: var(--text-muted);
    font-size: 0.75rem;
    margin-left: 4px;
}

/* === CodeMirror Error Highlight === */
.error-line {
    background: rgba(255, 0, 0, 0.15) !important;
    border-left: 3px solid var(--error-color, #dc3545);
}

/* === CodeMirror Container === */
.cm-editor {
    height: 100%;
    min-height: 400px;
    font-family: 'Fira Code', 'Monaco', 'Consolas', monospace;
    font-size: 0.875rem;
}

.cm-editor .cm-scroller {
    overflow: auto;
}

/* === CSS Variables (דוגמה) === */
:root {
    --spacing-xs: 4px;
    --spacing-sm: 8px;
    --spacing-md: 16px;
    --spacing-lg: 24px;
    --border-radius: 6px;
    --border-radius-sm: 4px;
    --border-radius-lg: 12px;
    --shadow-md: 0 4px 6px rgba(0, 0, 0, 0.1);
    --shadow-lg: 0 10px 25px rgba(0, 0, 0, 0.15);
    
    /* JSON Syntax Colors */
    --json-key-color: #9cdcfe;
    --json-string-color: #ce9178;
    --json-number-color: #b5cea8;
    --json-boolean-color: #569cd6;
    --json-null-color: #808080;
    
    /* Warning/Error Colors */
    --warning-bg: rgba(255, 193, 7, 0.1);
    --warning-color: #ffc107;
    --error-color: #dc3545;
}
```

### קובץ JavaScript: `webapp/static/js/json-formatter.js`

```javascript
/**
 * JSON Formatter Module
 * =====================
 * מודול לעיצוב, אימות והמרת JSON.
 * 
 * משתמש ב-EditorManager הקיים לאינטגרציית CodeMirror עם syntax highlighting.
 * 
 * @module JsonFormatter
 * @requires EditorManager (from editor-manager.js)
 */

(function() {
    'use strict';

    // ========== Configuration ==========
    const CONFIG = {
        TREE_MAX_DEPTH: 50,              // עומק מקסימלי ל-Tree View
        TREE_MAX_NODES: 5000,            // מספר nodes מקסימלי
        LARGE_FILE_WARNING_SIZE: 1024 * 1024,  // 1MB - אזהרה לקבצים גדולים
        TREE_INITIAL_COLLAPSE_DEPTH: 3   // קיפול אוטומטי מעומק זה
    };

    // ========== State ==========
    const state = {
        currentView: 'text',
        isLoading: false,
        lastValidJson: null,
        inputEditor: null,   // CodeMirror instance for input
        outputEditor: null,  // CodeMirror instance for output
        treeNodeCount: 0     // ספירת nodes ב-Tree View
    };

    // ========== DOM Cache ==========
    let elements = {};

    function cacheElements() {
        elements = {
            // Editor containers (for CodeMirror)
            inputContainer: document.getElementById('json-input'),
            outputContainer: document.getElementById('json-output'),
            
            // Fallback textareas (used if EditorManager not available)
            jsonInput: document.getElementById('json-input'),
            jsonOutput: document.getElementById('json-output'),
            
            // Options
            indentSize: document.getElementById('indent-size'),
            sortKeys: document.getElementById('sort-keys'),
            fileUpload: document.getElementById('file-upload'),
            searchInput: document.getElementById('search-input'),
            searchKeys: document.getElementById('search-keys'),
            searchValues: document.getElementById('search-values'),
            
            // Buttons
            btnFormat: document.getElementById('btn-format'),
            btnMinify: document.getElementById('btn-minify'),
            btnValidate: document.getElementById('btn-validate'),
            btnCopy: document.getElementById('btn-copy'),
            btnClear: document.getElementById('btn-clear'),
            btnSample: document.getElementById('btn-sample'),
            btnConvert: document.getElementById('btn-convert'),
            btnUpload: document.getElementById('btn-upload'),
            btnSearch: document.getElementById('btn-search'),
            
            // Views
            textView: document.getElementById('text-view'),
            treeView: document.getElementById('tree-view'),
            jsonTree: document.getElementById('json-tree'),
            viewButtons: document.querySelectorAll('.view-btn'),
            
            // Stats & Messages
            inputStats: document.getElementById('input-stats'),
            outputStats: document.getElementById('output-stats'),
            validationMessage: document.getElementById('validation-message'),
            
            // Search
            searchBar: document.getElementById('search-bar'),
            searchToggle: document.getElementById('search-toggle'),
            searchResults: document.getElementById('search-results'),
            
            // Dropdown
            convertDropdown: document.querySelector('.dropdown'),
            convertItems: document.querySelectorAll('.dropdown-item')
        };
    }

    // ========== CodeMirror Integration ==========
    /**
     * אתחול CodeMirror editors באמצעות EditorManager הקיים.
     * אם EditorManager לא זמין, נשתמש ב-textarea רגיל.
     */
    async function initEditors() {
        // בדיקה אם EditorManager זמין
        if (typeof window.EditorManager === 'undefined') {
            console.warn('EditorManager not available, falling back to textarea');
            return;
        }

        try {
            // אתחול editor לקלט
            if (elements.inputContainer) {
                state.inputEditor = await EditorManager.create(elements.inputContainer, {
                    language: 'json',
                    lineNumbers: true,
                    theme: 'auto',  // יתאים ל-dark mode
                    placeholder: 'הדבק JSON כאן...'
                });
                
                // האזנה לשינויים לעדכון סטטיסטיקות
                if (state.inputEditor) {
                    state.inputEditor.on('change', debounce(onInputChange, 300));
                }
            }

            // אתחול editor לפלט (read-only)
            if (elements.outputContainer) {
                state.outputEditor = await EditorManager.create(elements.outputContainer, {
                    language: 'json',
                    lineNumbers: true,
                    theme: 'auto',
                    readOnly: true
                });
            }

            console.log('CodeMirror editors initialized successfully');
        } catch (error) {
            console.error('Failed to initialize CodeMirror:', error);
            // Fallback to textarea
            state.inputEditor = null;
            state.outputEditor = null;
        }
    }

    /**
     * קבלת תוכן מה-editor (CodeMirror או textarea)
     */
    function getInputValue() {
        if (state.inputEditor && typeof state.inputEditor.getValue === 'function') {
            return state.inputEditor.getValue();
        }
        return elements.jsonInput?.value || '';
    }

    /**
     * הגדרת תוכן ב-editor הקלט
     */
    function setInputValue(value) {
        if (state.inputEditor && typeof state.inputEditor.setValue === 'function') {
            state.inputEditor.setValue(value);
        } else if (elements.jsonInput) {
            elements.jsonInput.value = value;
        }
    }

    /**
     * הגדרת תוכן ב-editor הפלט
     */
    function setOutputValue(value) {
        if (state.outputEditor && typeof state.outputEditor.setValue === 'function') {
            state.outputEditor.setValue(value);
        } else if (elements.jsonOutput) {
            elements.jsonOutput.value = value;
        }
    }

    /**
     * קבלת תוכן מה-editor הפלט
     */
    function getOutputValue() {
        if (state.outputEditor && typeof state.outputEditor.getValue === 'function') {
            return state.outputEditor.getValue();
        }
        return elements.jsonOutput?.value || '';
    }

    // ========== Event Bindings ==========
    function bindEvents() {
        // Primary actions
        elements.btnFormat.addEventListener('click', formatJson);
        elements.btnMinify.addEventListener('click', minifyJson);
        elements.btnValidate.addEventListener('click', validateJson);
        
        // Secondary actions
        elements.btnCopy.addEventListener('click', copyToClipboard);
        elements.btnClear.addEventListener('click', clearAll);
        elements.btnSample.addEventListener('click', loadSample);
        elements.btnUpload.addEventListener('click', () => elements.fileUpload.click());
        elements.fileUpload.addEventListener('change', handleFileUpload);
        
        // View toggle
        elements.viewButtons.forEach(btn => {
            btn.addEventListener('click', () => switchView(btn.dataset.view));
        });
        
        // Input change
        elements.jsonInput.addEventListener('input', debounce(onInputChange, 300));
        
        // Keyboard shortcuts
        document.addEventListener('keydown', handleKeyboard);
        
        // Convert dropdown
        elements.btnConvert.addEventListener('click', toggleDropdown);
        elements.convertItems.forEach(item => {
            item.addEventListener('click', () => convertJson(item.dataset.format));
        });
        
        // Search
        elements.searchToggle.addEventListener('click', toggleSearch);
        elements.btnSearch.addEventListener('click', searchJson);
        elements.searchInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') searchJson();
        });
        
        // Close dropdown on outside click
        document.addEventListener('click', (e) => {
            if (!elements.convertDropdown.contains(e.target)) {
                elements.convertDropdown.classList.remove('open');
            }
        });
    }

    // ========== API Calls ==========
    async function apiCall(endpoint, data) {
        state.isLoading = true;
        updateLoadingState();
        
        try {
            const response = await fetch(`/api/json/${endpoint}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            
            const result = await response.json();
            
            if (!response.ok) {
                throw new Error(result.error || 'שגיאה בבקשה');
            }
            
            return result;
        } finally {
            state.isLoading = false;
            updateLoadingState();
        }
    }

    // ========== Main Actions ==========
    async function formatJson() {
        const content = getInputValue().trim();
        if (!content) {
            showToast('אנא הזן JSON', 'warning');
            return;
        }

        // אזהרה לקבצים גדולים
        if (content.length > CONFIG.LARGE_FILE_WARNING_SIZE) {
            console.warn('Large JSON file detected, processing may take a moment');
        }
        
        try {
            const result = await apiCall('format', {
                content,
                indent: parseInt(elements.indentSize.value) || 2,
                sort_keys: elements.sortKeys.checked
            });
            
            if (result.success) {
                setOutputValue(result.result);
                state.lastValidJson = result.result;
                updateStats(result.stats);
                showValidation(true, 'JSON תקין ועוצב בהצלחה');
                
                if (state.currentView === 'tree') {
                    renderTree(result.result);
                }
            }
        } catch (error) {
            showValidation(false, error.message);
        }
    }

    async function minifyJson() {
        const content = getInputValue().trim();
        if (!content) {
            showToast('אנא הזן JSON', 'warning');
            return;
        }
        
        try {
            const result = await apiCall('minify', { content });
            
            if (result.success) {
                setOutputValue(result.result);
                const savings = `חיסכון: ${result.savings_percent}% (${formatBytes(result.original_size)} → ${formatBytes(result.minified_size)})`;
                showValidation(true, savings);
            }
        } catch (error) {
            showValidation(false, error.message);
        }
    }

    async function validateJson() {
        const content = getInputValue().trim();
        if (!content) {
            showToast('אנא הזן JSON', 'warning');
            return;
        }
        
        try {
            const result = await apiCall('validate', { content });
            
            if (result.is_valid) {
                showValidation(true, 'JSON תקין!', result.stats);
            } else {
                const details = `שורה ${result.line}, עמודה ${result.column}: ${result.error}`;
                showValidation(false, details);
                highlightError(result.line, result.column);
            }
        } catch (error) {
            showValidation(false, error.message);
        }
    }

    async function convertJson(format) {
        const content = getInputValue().trim();
        if (!content) {
            showToast('אנא הזן JSON', 'warning');
            return;
        }
        
        elements.convertDropdown.classList.remove('open');
        
        try {
            const result = await apiCall('convert', {
                content,
                target_format: format
            });
            
            if (result.success) {
                setOutputValue(result.result);
                showToast(`הומר ל-${format.toUpperCase()} בהצלחה`, 'success');
            }
        } catch (error) {
            showValidation(false, error.message);
        }
    }

    async function searchJson() {
        const content = getInputValue().trim();
        const query = elements.searchInput.value.trim();
        
        if (!content || !query) {
            showToast('אנא הזן JSON וטקסט לחיפוש', 'warning');
            return;
        }
        
        try {
            const result = await apiCall('search', {
                content,
                query,
                search_keys: elements.searchKeys.checked,
                search_values: elements.searchValues.checked
            });
            
            if (result.success) {
                renderSearchResults(result.results);
            }
        } catch (error) {
            showToast(error.message, 'error');
        }
    }

    // ========== UI Updates ==========
    function switchView(view) {
        state.currentView = view;
        
        elements.viewButtons.forEach(btn => {
            btn.classList.toggle('active', btn.dataset.view === view);
        });
        
        elements.textView.classList.toggle('active', view === 'text');
        elements.treeView.classList.toggle('active', view === 'tree');
        
        if (view === 'tree' && state.lastValidJson) {
            renderTree(state.lastValidJson);
        }
    }

    function renderTree(jsonString) {
        try {
            const data = JSON.parse(jsonString);
            
            // איפוס מונה ה-nodes
            state.treeNodeCount = 0;
            
            // בדיקת גודל ה-JSON
            const jsonSize = jsonString.length;
            if (jsonSize > CONFIG.LARGE_FILE_WARNING_SIZE) {
                elements.jsonTree.innerHTML = `
                    <div class="tree-warning">
                        <span class="warning-icon">⚠️</span>
                        <p>הקובץ גדול מדי לתצוגת עץ (${formatBytes(jsonSize)})</p>
                        <p>השתמש בתצוגת טקסט לביצועים טובים יותר</p>
                        <button class="btn btn-sm btn-outline" onclick="JsonFormatter.forceRenderTree()">
                            הצג בכל זאת (עלול להאט)
                        </button>
                    </div>
                `;
                // שמור את ה-data לשימוש עתידי
                state.pendingTreeData = data;
                return;
            }
            
            const html = buildTreeHtml(data, 'root', 0);
            
            // בדיקה אם חרגנו מהמגבלות
            if (state.treeNodeCount >= CONFIG.TREE_MAX_NODES) {
                elements.jsonTree.innerHTML = `
                    <div class="tree-warning">
                        <span class="warning-icon">⚠️</span>
                        <p>ה-JSON מכיל יותר מ-${CONFIG.TREE_MAX_NODES} אלמנטים</p>
                        <p>מוצג חלק מהתוכן בלבד</p>
                    </div>
                ` + html;
            } else {
                elements.jsonTree.innerHTML = html;
            }
            
            bindTreeEvents();
            
            // קיפול אוטומטי של עומקים גבוהים
            autoCollapseDeepNodes();
            
        } catch (e) {
            elements.jsonTree.innerHTML = '<p class="error">לא ניתן לייצר תצוגת עץ</p>';
        }
    }

    /**
     * כפה רינדור Tree View גם לקבצים גדולים
     */
    function forceRenderTree() {
        if (state.pendingTreeData) {
            state.treeNodeCount = 0;
            const html = buildTreeHtml(state.pendingTreeData, 'root', 0);
            elements.jsonTree.innerHTML = html;
            bindTreeEvents();
            autoCollapseDeepNodes();
            state.pendingTreeData = null;
        }
    }

    /**
     * קיפול אוטומטי של nodes בעומק גבוה
     */
    function autoCollapseDeepNodes() {
        elements.jsonTree.querySelectorAll('.tree-node').forEach(node => {
            const depth = getNodeDepth(node);
            if (depth >= CONFIG.TREE_INITIAL_COLLAPSE_DEPTH) {
                node.classList.add('collapsed');
            }
        });
    }

    /**
     * חישוב עומק של node בעץ
     */
    function getNodeDepth(node) {
        let depth = 0;
        let current = node;
        while (current.parentElement) {
            if (current.parentElement.classList.contains('tree-node')) {
                depth++;
            }
            current = current.parentElement;
        }
        return depth;
    }

    /**
     * בניית HTML לתצוגת עץ עם הגבלות ביצועים
     * 
     * @param {any} obj - האובייקט לרנדור
     * @param {string} key - שם המפתח
     * @param {number} depth - עומק נוכחי
     * @returns {string} HTML string
     */
    function buildTreeHtml(obj, key, depth = 0) {
        // הגבלת מספר nodes
        if (state.treeNodeCount >= CONFIG.TREE_MAX_NODES) {
            return '<span class="tree-truncated">... (יותר מדי אלמנטים)</span>';
        }
        state.treeNodeCount++;

        // הגבלת עומק
        if (depth > CONFIG.TREE_MAX_DEPTH) {
            return '<span class="tree-truncated">... (עומק מקסימלי)</span>';
        }
        
        if (obj === null) {
            return `<span class="tree-value null">null</span>`;
        }
        
        if (typeof obj !== 'object') {
            const type = typeof obj;
            // קיצור מחרוזות ארוכות
            let displayValue = obj;
            if (type === 'string' && obj.length > 500) {
                displayValue = obj.substring(0, 500) + '...';
            }
            const value = type === 'string' ? `"${escapeHtml(String(displayValue))}"` : String(obj);
            return `<span class="tree-value ${type}">${value}</span>`;
        }
        
        const isArray = Array.isArray(obj);
        const bracket = isArray ? ['[', ']'] : ['{', '}'];
        const entries = isArray ? obj.map((v, i) => [i, v]) : Object.entries(obj);
        
        if (entries.length === 0) {
            return `<span>${bracket[0]}${bracket[1]}</span>`;
        }

        // אם יש יותר מדי items, הצג רק חלק
        const maxItems = 100;
        const truncated = entries.length > maxItems;
        const displayEntries = truncated ? entries.slice(0, maxItems) : entries;
        
        // קיפול אוטומטי לעומקים גבוהים
        const autoCollapse = depth >= CONFIG.TREE_INITIAL_COLLAPSE_DEPTH;
        
        let html = `<div class="tree-node${autoCollapse ? ' collapsed' : ''}">`;
        html += `<span class="tree-toggle"></span>`;
        html += `<span class="tree-key">${escapeHtml(String(key))}</span>`;
        html += `<span class="tree-count">(${entries.length})</span>: ${bracket[0]}`;
        html += `<div class="tree-children">`;
        
        displayEntries.forEach(([k, v], i) => {
            const comma = i < displayEntries.length - 1 ? ',' : '';
            html += `<div class="tree-item">`;
            
            if (typeof v === 'object' && v !== null) {
                html += buildTreeHtml(v, k, depth + 1);
            } else {
                const keyHtml = isArray ? '' : `<span class="tree-key">${escapeHtml(String(k))}</span>: `;
                html += keyHtml + buildTreeHtml(v, k, depth + 1);
            }
            
            html += `${comma}</div>`;
        });

        // הודעה על קיצוץ
        if (truncated) {
            html += `<div class="tree-item tree-truncated">... ועוד ${entries.length - maxItems} פריטים</div>`;
        }
        
        html += `</div>${bracket[1]}</div>`;
        return html;
    }

    function bindTreeEvents() {
        elements.jsonTree.querySelectorAll('.tree-toggle').forEach(toggle => {
            toggle.addEventListener('click', (e) => {
                e.stopPropagation();
                toggle.closest('.tree-node').classList.toggle('collapsed');
            });
        });
    }

    function renderSearchResults(results) {
        if (results.length === 0) {
            elements.searchResults.innerHTML = '<p class="no-results">לא נמצאו תוצאות</p>';
            return;
        }
        
        let html = '';
        results.forEach(item => {
            html += `
                <div class="search-result-item" data-path="${escapeHtml(item.path)}">
                    <span class="search-result-path">${escapeHtml(item.path)}</span>
                    <span class="search-result-type">${item.type === 'key' ? 'מפתח' : 'ערך'}</span>
                </div>
            `;
        });
        
        elements.searchResults.innerHTML = html;
        
        // Bind click events for results
        elements.searchResults.querySelectorAll('.search-result-item').forEach(item => {
            item.addEventListener('click', () => {
                const path = item.dataset.path;
                showToast(`נתיב: ${path}`, 'info');
                // TODO: Highlight in tree view
            });
        });
    }

    function showValidation(isValid, message, stats = null) {
        const el = elements.validationMessage;
        el.classList.remove('hidden', 'success', 'error');
        el.classList.add(isValid ? 'success' : 'error');
        
        let content = `
            <span class="icon">${isValid ? '✓' : '✗'}</span>
            <div class="content">
                <div class="title">${isValid ? 'הצלחה' : 'שגיאה'}</div>
                <div class="details">${escapeHtml(message)}</div>
        `;
        
        if (stats) {
            content += `
                <div class="stats">
                    מפתחות: ${stats.total_keys} | 
                    עומק: ${stats.max_depth} | 
                    אובייקטים: ${stats.object_count || 0} | 
                    מערכים: ${stats.array_count || 0}
                </div>
            `;
        }
        
        content += `</div>`;
        el.innerHTML = content;
        
        // Auto-hide success after 5 seconds
        if (isValid) {
            setTimeout(() => el.classList.add('hidden'), 5000);
        }
    }

    /**
     * הדגשת מיקום שגיאה ב-editor
     * תומך גם ב-CodeMirror וגם ב-textarea רגיל
     */
    function highlightError(line, column) {
        // אם יש CodeMirror editor
        if (state.inputEditor && typeof state.inputEditor.setCursor === 'function') {
            // CodeMirror משתמש ב-0-based indexing
            const cmLine = line - 1;
            const cmColumn = column - 1;
            
            // מיקוד על השגיאה
            state.inputEditor.setCursor({ line: cmLine, ch: cmColumn });
            state.inputEditor.focus();
            
            // הדגשת השורה
            if (typeof state.inputEditor.addLineClass === 'function') {
                // הסרת הדגשות קודמות
                for (let i = 0; i < state.inputEditor.lineCount(); i++) {
                    state.inputEditor.removeLineClass(i, 'background', 'error-line');
                }
                state.inputEditor.addLineClass(cmLine, 'background', 'error-line');
                
                // הסרת ההדגשה אחרי 3 שניות
                setTimeout(() => {
                    state.inputEditor.removeLineClass(cmLine, 'background', 'error-line');
                }, 3000);
            }
            
            // גלילה לשורה
            state.inputEditor.scrollIntoView({ line: cmLine, ch: cmColumn }, 100);
            
        } else {
            // Fallback ל-textarea רגיל
            const textarea = elements.jsonInput;
            if (!textarea) return;
            
            const lines = textarea.value.split('\n');
            let position = 0;
            
            for (let i = 0; i < line - 1 && i < lines.length; i++) {
                position += lines[i].length + 1;
            }
            position += column - 1;
            
            textarea.focus();
            textarea.setSelectionRange(position, position + 1);
        }
    }

    function updateStats(stats) {
        if (stats) {
            elements.outputStats.textContent = 
                `מפתחות: ${stats.total_keys} | עומק: ${stats.max_depth} | ערכים: ${stats.total_values || 0}`;
        }
    }

    function updateLoadingState() {
        const buttons = [
            elements.btnFormat,
            elements.btnMinify,
            elements.btnValidate,
            elements.btnConvert
        ];
        
        buttons.forEach(btn => {
            btn.disabled = state.isLoading;
            btn.classList.toggle('loading', state.isLoading);
        });
    }

    // ========== Helper Actions ==========
    function copyToClipboard() {
        const text = getOutputValue() || getInputValue();
        if (!text) {
            showToast('אין תוכן להעתקה', 'warning');
            return;
        }
        
        navigator.clipboard.writeText(text).then(() => {
            showToast('הועתק ללוח!', 'success');
        }).catch(() => {
            showToast('שגיאה בהעתקה', 'error');
        });
    }

    function clearAll() {
        setInputValue('');
        setOutputValue('');
        elements.jsonTree.innerHTML = '';
        elements.inputStats.textContent = '';
        elements.outputStats.textContent = '';
        elements.validationMessage.classList.add('hidden');
        elements.searchResults.innerHTML = '';
        state.lastValidJson = null;
        state.pendingTreeData = null;
        state.treeNodeCount = 0;
    }

    function loadSample() {
        const sample = {
            "name": "JSON Formatter",
            "version": "1.0.0",
            "features": [
                "עיצוב",
                "דחיסה",
                "אימות",
                "המרה"
            ],
            "config": {
                "indent": 2,
                "sortKeys": false
            },
            "stats": {
                "users": 1500,
                "rating": 4.8,
                "active": true
            }
        };
        
        setInputValue(JSON.stringify(sample, null, 2));
        onInputChange();
    }

    function handleFileUpload(event) {
        const file = event.target.files[0];
        if (!file) return;

        // אזהרה לקבצים גדולים
        if (file.size > CONFIG.LARGE_FILE_WARNING_SIZE) {
            showToast(`קובץ גדול (${formatBytes(file.size)}) - הטעינה עלולה לקחת זמן`, 'warning');
        }
        
        const reader = new FileReader();
        reader.onload = (e) => {
            setInputValue(e.target.result);
            onInputChange();
            showToast(`נטען: ${file.name}`, 'success');
        };
        reader.onerror = () => {
            showToast('שגיאה בקריאת הקובץ', 'error');
        };
        reader.readAsText(file);
        
        // Reset input for re-upload
        event.target.value = '';
    }

    function onInputChange() {
        const content = getInputValue();
        const bytes = new Blob([content]).size;
        const lines = content.split('\n').length;
        elements.inputStats.textContent = `${formatBytes(bytes)} | ${lines} שורות`;

        // אזהרה על גודל קובץ
        if (bytes > CONFIG.LARGE_FILE_WARNING_SIZE) {
            elements.inputStats.textContent += ' ⚠️ קובץ גדול';
        }
    }

    function toggleDropdown(event) {
        event.stopPropagation();
        elements.convertDropdown.classList.toggle('open');
    }

    function toggleSearch() {
        elements.searchBar.classList.toggle('collapsed');
        if (!elements.searchBar.classList.contains('collapsed')) {
            elements.searchInput.focus();
        }
    }

    function handleKeyboard(event) {
        // Ctrl/Cmd + Shift + F = Format
        if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key === 'F') {
            event.preventDefault();
            formatJson();
        }
        // Ctrl/Cmd + Enter = Validate
        if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
            event.preventDefault();
            validateJson();
        }
        // Ctrl/Cmd + F = Search (when in formatter)
        if ((event.ctrlKey || event.metaKey) && event.key === 'f' && 
            document.activeElement === elements.jsonInput) {
            event.preventDefault();
            toggleSearch();
        }
    }

    // ========== Utilities ==========
    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function formatBytes(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }

    function debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }

    function showToast(message, type = 'info') {
        // שימוש במנגנון Toast קיים בפרויקט
        if (window.showToast) {
            window.showToast(message, type);
        } else {
            console.log(`[${type}] ${message}`);
        }
    }

    // ========== Initialization ==========
    async function init() {
        cacheElements();
        
        // אתחול CodeMirror editors (אסינכרוני)
        await initEditors();
        
        bindEvents();
        onInputChange();
        console.log('JSON Formatter initialized');
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Export for external use
    window.JsonFormatter = {
        format: formatJson,
        minify: minifyJson,
        validate: validateJson,
        convert: convertJson,
        search: searchJson,
        forceRenderTree: forceRenderTree,  // לכפיית רינדור Tree View לקבצים גדולים
        getConfig: () => ({ ...CONFIG })   // גישה ל-configuration
    };

})();
```

---

## 🤖 אינטגרציה עם Telegram Bot

### הוספה ל-`handlers/commands.py`

```python
from services.json_formatter_service import get_json_formatter_service

async def json_format_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    פקודה לעיצוב JSON.
    
    שימוש:
        /json_format <json>
        או שליחת JSON כתשובה לפקודה
    """
    # קבלת הטקסט
    text = None
    if context.args:
        text = ' '.join(context.args)
    elif update.message.reply_to_message:
        text = update.message.reply_to_message.text
    
    if not text:
        await update.message.reply_text(
            "📋 *JSON Formatter*\n\n"
            "שלח JSON לעיצוב:\n"
            "`/json_format {\"key\": \"value\"}`\n\n"
            "או השב על הודעה עם JSON",
            parse_mode='Markdown'
        )
        return
    
    service = get_json_formatter_service()
    
    # ניסיון לעצב
    try:
        result = service.format_json(text, indent=2)
        stats = service.get_json_stats(text)
        
        message = f"✅ *JSON תקין*\n\n"
        message += f"```json\n{result[:3500]}\n```\n\n"
        
        if len(result) > 3500:
            message += "_(הוצגו 3500 תווים ראשונים)_\n\n"
        
        message += f"📊 *סטטיסטיקות:*\n"
        message += f"• מפתחות: {stats.total_keys}\n"
        message += f"• עומק מקסימלי: {stats.max_depth}\n"
        message += f"• אובייקטים: {stats.object_count}\n"
        message += f"• מערכים: {stats.array_count}"
        
        await update.message.reply_text(message, parse_mode='Markdown')
        
    except json.JSONDecodeError as e:
        # ניסיון לתקן
        fixed, fixes = service.fix_common_errors(text)
        
        try:
            result = service.format_json(fixed)
            
            message = f"⚠️ *JSON תוקן ועוצב*\n\n"
            message += f"```json\n{result[:3000]}\n```\n\n"
            message += f"🔧 *תיקונים שבוצעו:*\n"
            for fix in fixes:
                message += f"• {fix}\n"
            
            await update.message.reply_text(message, parse_mode='Markdown')
            
        except:
            await update.message.reply_text(
                f"❌ *JSON לא תקין*\n\n"
                f"שגיאה בשורה {e.lineno}, עמודה {e.colno}:\n"
                f"`{e.msg}`",
                parse_mode='Markdown'
            )


async def json_validate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודה לאימות JSON."""
    text = ' '.join(context.args) if context.args else None
    
    if update.message.reply_to_message:
        text = update.message.reply_to_message.text
    
    if not text:
        await update.message.reply_text(
            "שלח JSON לאימות:\n`/json_validate {\"key\": \"value\"}`",
            parse_mode='Markdown'
        )
        return
    
    service = get_json_formatter_service()
    result = service.validate_json(text)
    
    if result.is_valid:
        stats = service.get_json_stats(text)
        await update.message.reply_text(
            f"✅ *JSON תקין!*\n\n"
            f"📊 מפתחות: {stats.total_keys}\n"
            f"📏 עומק: {stats.max_depth}",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            f"❌ *JSON לא תקין*\n\n"
            f"שורה {result.error_line}, עמודה {result.error_column}:\n"
            f"`{result.error_message}`",
            parse_mode='Markdown'
        )
```

### הוספת Inline Keyboard לפעולות נוספות

```python
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def get_json_keyboard():
    """מקלדת inline לפעולות JSON."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✨ עיצוב", callback_data="json_format"),
            InlineKeyboardButton("📦 דחיסה", callback_data="json_minify"),
        ],
        [
            InlineKeyboardButton("✓ אימות", callback_data="json_validate"),
            InlineKeyboardButton("🔄 YAML", callback_data="json_to_yaml"),
        ]
    ])
```

---

## 🧪 בדיקות

### קובץ: `tests/test_json_formatter_service.py`

```python
"""
Tests for JSON Formatter Service
================================
"""

import pytest
import json
from services.json_formatter_service import (
    JsonFormatterService,
    JsonValidationResult,
    JsonStats
)


@pytest.fixture
def service():
    return JsonFormatterService()


class TestFormatJson:
    """בדיקות עיצוב JSON."""
    
    def test_format_simple_object(self, service):
        input_json = '{"a":1,"b":2}'
        result = service.format_json(input_json)
        expected = '{\n  "a": 1,\n  "b": 2\n}'
        assert result == expected
    
    def test_format_with_custom_indent(self, service):
        input_json = '{"a":1}'
        result = service.format_json(input_json, indent=4)
        assert '    "a"' in result
    
    def test_format_with_sort_keys(self, service):
        input_json = '{"z":1,"a":2}'
        result = service.format_json(input_json, sort_keys=True)
        lines = result.split('\n')
        assert '"a"' in lines[1]
        assert '"z"' in lines[2]
    
    def test_format_invalid_json(self, service):
        with pytest.raises(json.JSONDecodeError):
            service.format_json('not json')
    
    def test_format_unicode(self, service):
        input_json = '{"שם":"ערך"}'
        result = service.format_json(input_json)
        assert 'שם' in result
        assert 'ערך' in result


class TestMinifyJson:
    """בדיקות דחיסת JSON."""
    
    def test_minify_simple(self, service):
        input_json = '{\n  "a": 1,\n  "b": 2\n}'
        result = service.minify_json(input_json)
        assert result == '{"a":1,"b":2}'
    
    def test_minify_removes_all_whitespace(self, service):
        input_json = '{\n    "key"   :   "value"   \n}'
        result = service.minify_json(input_json)
        assert ' ' not in result
        assert '\n' not in result


class TestValidateJson:
    """בדיקות אימות JSON."""
    
    def test_validate_valid_json(self, service):
        result = service.validate_json('{"valid": true}')
        assert result.is_valid is True
        assert result.error_message is None
    
    def test_validate_invalid_json(self, service):
        result = service.validate_json('{invalid}')
        assert result.is_valid is False
        assert result.error_message is not None
        assert result.error_line is not None
    
    def test_validate_empty_object(self, service):
        result = service.validate_json('{}')
        assert result.is_valid is True
    
    def test_validate_array(self, service):
        result = service.validate_json('[1, 2, 3]')
        assert result.is_valid is True


class TestGetJsonStats:
    """בדיקות סטטיסטיקות JSON."""
    
    def test_stats_simple_object(self, service):
        stats = service.get_json_stats('{"a": 1, "b": "text"}')
        assert stats.total_keys == 2
        assert stats.number_count == 1
        assert stats.string_count == 1
    
    def test_stats_nested_object(self, service):
        json_str = '{"outer": {"inner": {"deep": 1}}}'
        stats = service.get_json_stats(json_str)
        assert stats.max_depth == 3
        assert stats.object_count == 3
    
    def test_stats_array(self, service):
        stats = service.get_json_stats('[1, 2, 3, null, true]')
        assert stats.array_count == 1
        assert stats.number_count == 3
        assert stats.null_count == 1
        assert stats.boolean_count == 1


class TestSearchJson:
    """בדיקות חיפוש בתוך JSON."""
    
    def test_search_key(self, service):
        json_str = '{"user": {"name": "John"}}'
        results = service.search_json(json_str, 'name')
        assert len(results) >= 1
        assert any(r['type'] == 'key' for r in results)
    
    def test_search_value(self, service):
        json_str = '{"name": "John"}'
        results = service.search_json(json_str, 'John')
        assert len(results) >= 1
        assert any(r['type'] == 'value' for r in results)
    
    def test_search_case_insensitive(self, service):
        json_str = '{"Name": "JOHN"}'
        results = service.search_json(json_str, 'john')
        assert len(results) >= 1
    
    def test_search_keys_only(self, service):
        json_str = '{"test": "test"}'
        results = service.search_json(json_str, 'test', search_keys=True, search_values=False)
        assert all(r['type'] == 'key' for r in results)


class TestFixCommonErrors:
    """בדיקות תיקון שגיאות נפוצות."""
    
    def test_fix_trailing_comma(self, service):
        json_str = '{"a": 1,}'
        fixed, fixes = service.fix_common_errors(json_str)
        assert json.loads(fixed)  # Should be valid now
        assert len(fixes) > 0
    
    def test_fix_single_quotes(self, service):
        json_str = "{'a': 'value'}"
        fixed, fixes = service.fix_common_errors(json_str)
        # Should attempt to fix
        assert '"' in fixed or fixes


class TestConvertJson:
    """בדיקות המרה."""
    
    def test_convert_to_xml(self, service):
        json_str = '{"name": "test"}'
        result = service.convert_to_xml(json_str)
        assert '<?xml' in result
        assert '<name>' in result
        assert '</name>' in result
    
    def test_convert_to_xml_sanitizes_spaces(self, service):
        """מפתחות עם רווחים מומרים לקו תחתון"""
        json_str = '{"User Name": "Amir"}'
        result = service.convert_to_xml(json_str)
        assert '<User_Name>' in result
        assert '</User_Name>' in result
        assert 'User Name' not in result  # הרווח נעלם
    
    def test_convert_to_xml_sanitizes_leading_number(self, service):
        """מפתחות שמתחילים במספר מקבלים קו תחתון"""
        json_str = '{"1st_Place": true}'
        result = service.convert_to_xml(json_str)
        assert '<_1st_Place>' in result
        assert '<1st_Place>' not in result  # לא חוקי ב-XML
    
    def test_convert_to_xml_sanitizes_special_chars(self, service):
        """תווים מיוחדים מומרים"""
        json_str = '{"e-mail@address": "test@example.com"}'
        result = service.convert_to_xml(json_str)
        # @ הופך לקו תחתון, מקף נשאר
        assert '<e-mail_address>' in result
    
    def test_convert_to_xml_array_naming(self, service):
        """מערכים מקבלים שמות פריטים נכונים"""
        json_str = '{"users": ["a", "b"]}'
        result = service.convert_to_xml(json_str)
        assert '<users>' in result
        assert '<user>' in result  # יחיד של users
    
    @pytest.mark.skipif(True, reason="Requires PyYAML")
    def test_convert_to_yaml(self, service):
        json_str = '{"name": "test", "value": 42}'
        result = service.convert_to_yaml(json_str)
        assert 'name:' in result
        assert 'value:' in result
```

### קובץ: `tests/test_json_formatter_api.py`

```python
"""
Tests for JSON Formatter API
============================
"""

import pytest
from flask import Flask
from webapp.json_formatter_api import json_formatter_bp


@pytest.fixture
def app():
    app = Flask(__name__)
    app.register_blueprint(json_formatter_bp)
    app.config['TESTING'] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestFormatEndpoint:
    """בדיקות endpoint עיצוב."""
    
    def test_format_success(self, client):
        response = client.post('/api/json/format', json={
            'content': '{"a":1}'
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert '"a": 1' in data['result']
    
    def test_format_invalid_json(self, client):
        response = client.post('/api/json/format', json={
            'content': 'not json'
        })
        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
    
    def test_format_missing_content(self, client):
        response = client.post('/api/json/format', json={})
        assert response.status_code == 400


class TestValidateEndpoint:
    """בדיקות endpoint אימות."""
    
    def test_validate_valid(self, client):
        response = client.post('/api/json/validate', json={
            'content': '{"valid": true}'
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data['is_valid'] is True
        assert 'stats' in data
    
    def test_validate_invalid(self, client):
        response = client.post('/api/json/validate', json={
            'content': '{invalid}'
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data['is_valid'] is False
        assert 'error' in data
        assert 'line' in data


class TestMinifyEndpoint:
    """בדיקות endpoint דחיסה."""
    
    def test_minify_success(self, client):
        response = client.post('/api/json/minify', json={
            'content': '{\n  "a": 1\n}'
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert ' ' not in data['result']
        assert 'savings_percent' in data


class TestConvertEndpoint:
    """בדיקות endpoint המרה."""
    
    def test_convert_to_xml(self, client):
        response = client.post('/api/json/convert', json={
            'content': '{"name": "test"}',
            'target_format': 'xml'
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert '<?xml' in data['result']


class TestSearchEndpoint:
    """בדיקות endpoint חיפוש."""
    
    def test_search_found(self, client):
        response = client.post('/api/json/search', json={
            'content': '{"user": {"name": "John"}}',
            'query': 'name'
        })
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['total_matches'] >= 1
```

---

## 📋 משימות עדיפות

### P0 - חובה לפני השקה

- [ ] מימוש `JsonFormatterService` עם כל המתודות הבסיסיות
- [ ] יצירת API endpoints ורישום Blueprint
- [ ] בניית UI בסיסי עם עיצוב/דחיסה/אימות
- [ ] בדיקות יחידה ל-Service
- [ ] בדיקות אינטגרציה ל-API

### P1 - חשוב

- [ ] אינטגרציה עם CodeMirror (שימוש ב-`editor-manager.js` הקיים)
- [ ] תצוגת Tree View עם קיפול/פריסה
- [ ] חיפוש בתוך JSON
- [ ] העלאת קבצי JSON
- [ ] פקודות Telegram Bot

### P2 - שיפורים

- [ ] המרה ל-YAML/XML
- [ ] תיקון אוטומטי של שגיאות נפוצות
- [ ] השוואת שני JSON documents
- [ ] ייצוא לקובץ
- [ ] שמירת היסטוריית פעולות

### P3 - עתידי

- [ ] JSONPath queries
- [ ] Schema validation
- [ ] Diff view בין שתי גרסאות
- [ ] אינטגרציה עם הספרייה הקיימת (שמירת snippets מעוצבים)

---

## 🔗 קישורים רלוונטיים

- [CodeBot Documentation](https://amirbiron.github.io/CodeBot/)
- [FILE_COMPARISON_TOOL_IMPLEMENTATION_GUIDE.md](./FILE_COMPARISON_TOOL_IMPLEMENTATION_GUIDE.md) - מדריך דומה לכלי השוואה
- [editor-manager.js](../static/js/editor-manager.js) - אינטגרציית CodeMirror קיימת
- [compare.js](../static/js/compare.js) - דוגמה למודול JS מורכב

---

## 📝 הערות נוספות

### אינטגרציה עם CodeMirror

הפרויקט כבר משתמש ב-CodeMirror עם תמיכה ב-JSON. ניתן לשלב את ה-JSON Formatter עם ה-editor הקיים:

```javascript
// שימוש ב-EditorManager הקיים
if (window.EditorManager) {
    EditorManager.setLanguage('json');
    EditorManager.setValue(formattedJson);
}
```

### שימוש בדפוסים קיימים

הקוד ממליץ להשתמש בדפוסים מ-`compare.js`:
- מבנה IIFE למודול
- State management
- DOM caching
- Event delegation
- API error handling
- Toast notifications

### ביצועים

לפי הכללים ב-`.cursorrules`:
- אל תמשוך שדות כבדים (`content`, `code`) בשאילתות רשימה
- השתמש ב-aggregation ברמת ה-DB כשאפשר
- טען נתונים כבדים אסינכרונית (Lazy Loading)

---

## ⚠️ נקודות חשובות למימוש

### 1. אינטגרציית CodeMirror (קריטי)

המדריך מתוכנן לעבוד עם `EditorManager` הקיים בפרויקט:

```javascript
// הקוד משתמש ב-EditorManager אוטומטית אם זמין
await initEditors();

// גישה לתוכן דרך פונקציות wrapper
const content = getInputValue();  // עובד עם CodeMirror או textarea
setOutputValue(result);           // עובד עם CodeMirror או textarea
```

**יתרונות:**
- Syntax highlighting אוטומטי ל-JSON
- מספרי שורות
- התאמה ל-Dark Mode
- הדגשת שגיאות על שורה ספציפית

**Fallback:**
אם `EditorManager` לא זמין, הקוד יעבוד עם textarea רגיל.

### 2. תלויות Python

**חובה להוסיף ל-`requirements/base.txt`:**

```txt
PyYAML>=6.0.1
```

ללא זה, המרה ל-YAML תיכשל עם הודעת שגיאה ברורה.

### 3. הגבלות ביצועים ב-Tree View

המימוש כולל הגנות מפני קבצי JSON גדולים:

| הגדרה | ערך ברירת מחדל | תיאור |
|--------|----------------|--------|
| `TREE_MAX_DEPTH` | 50 | עומק מקסימלי לעץ |
| `TREE_MAX_NODES` | 5000 | מספר nodes מקסימלי |
| `LARGE_FILE_WARNING_SIZE` | 1MB | גודל לאזהרה |
| `TREE_INITIAL_COLLAPSE_DEPTH` | 3 | קיפול אוטומטי מעומק זה |

**התנהגות:**
- קבצים מעל 1MB מציגים אזהרה עם אפשרות להמשיך
- Nodes מעבר למגבלה מוצגים כ-"..."
- קיפול אוטומטי של עומקים גבוהים

### סיכום שינויים מרכזיים

| נושא | מה נוסף |
|------|---------|
| **CodeMirror** | פונקציות `getInputValue()`, `setInputValue()`, `initEditors()` |
| **תלויות** | סעיף Dependencies עם PyYAML |
| **Tree View** | קונפיגורציית CONFIG, הגבלות עומק/nodes, אזהרות גודל |
| **Error Highlight** | תמיכה ב-CodeMirror API עם fallback ל-textarea |
