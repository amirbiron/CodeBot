# 📝 מדריך מימוש: פתקים דביקים אינליין למסמכי Markdown

מסמך זה מפרט מימוש מלא של פיצ'ר "פתקים דביקים" (Sticky Notes) עבור תצוגת Markdown ב-CodeBot WebApp, מותאם למבנה הקוד הנוכחי ולתבניות הקיימות.

---

## 🎯 מטרות וסקופ

### מה ולמה

* **מה:** הוספת "פתקים דביקים" (Sticky Notes) אינליין מעל התצוגה של Markdown בלבד (`md_preview.html`). הפתקים מעוגנים לשורה/טווח שורות בקובץ המקור, ונראים רק ליוצר שלהם (פר-משתמש ופר-קובץ).
* **למה:** לאפשר רישום הערות מהיר והקשרי (contextual) ישירות על המסמך, ללא צורך בפאנל צדדי. לספק חוויית "פתק" קלאסית שאפשר לגרור, לשנות גודל ולמזער.

### מחזור חיים ומגבלות

* **סקופ (Scope):** עמוד התצוגה `md_preview.html` בלבד. לא יופיע בעורך הטקסט, ולא בקבצי קוד שאינם Markdown.
* **נראות (Visibility):** פר-קובץ ופר-משתמש. רק בעל הפתק רואה אותו בקובץ הספציפי אליו הוא שויך.
* **לא במטרה (Out of Scope):**
    * שיתוף/שיתופיות (Collaboration) של פתקים בין משתמשים.
    * סנכרון בזמן אמת.
    * הכללת הפתקים בהדפסה או בייצוא (Export) של המסמך.

---

## 🗄️ מודל נתונים (MongoDB)

### אוסף חדש: `markdown_sticky_notes`

```python
{
    "_id": ObjectId,
    "user_id": int,                    # מזהה המשתמש (מ-session)
    "file_name": str,                  # שם הקובץ המלא (versionless key)
    "anchor_line": int,                # מספר השורה בקובץ המקור שאליה הפתק מעוגן
    "anchor_range": {                  # אופציונלי: טווח שורות
        "start": int,
        "end": int
    },
    "position": {                      # מיקום ויזואלי על המסך (pixels/%)
        "x": float,                    # מיקום אופקי (%, יחסי לקונטיינר)
        "y": float,                    # מיקום אנכי (%, יחסי לקונטיינר)
    },
    "size": {                          # גודל הפתק
        "width": int,                  # רוחב בפיקסלים (ברירת מחדל: 250)
        "height": int                  # גובה בפיקסלים (ברירת מחדל: 200)
    },
    "content": str,                    # תוכן הפתק (Plain text, עד 2000 תווים)
    "color": str,                      # צבע רקע (מתוך פלטה מוגדרת)
    "is_minimized": bool,              # האם הפתק ממוזער
    "z_index": int,                    # סדר שכבות (לפתקים חופפים)
    "created_at": datetime,
    "updated_at": datetime,
    "is_active": bool                  # למחיקה רכה (ברירת מחדל: true)
}
```

### אינדקסים מומלצים

```python
# במחלקה Repository או בסקריפט אתחול:
db.markdown_sticky_notes.create_index([
    ("user_id", 1),
    ("file_name", 1),
    ("is_active", 1)
])

db.markdown_sticky_notes.create_index([
    ("user_id", 1),
    ("file_name", 1),
    ("anchor_line", 1)
])
```

---

## 🏗️ ארכיטקטורה ומבנה קוד

### 1. Backend: Flask Blueprint חדש

יצירת קובץ חדש: `webapp/sticky_notes_api.py`

```python
"""
API endpoints for Markdown Sticky Notes feature.
Handles CRUD operations for user-specific contextual notes on Markdown files.
"""
from flask import Blueprint, request, session, jsonify
from functools import wraps
from datetime import datetime, timezone
from bson import ObjectId
import re

from database.repository import Repository
from observability.events import emit_event
from observability.logging_config import get_logger
from observability.tracing import traced
from observability.internal_alerts import internal_alerts

logger = get_logger(__name__)

sticky_notes_bp = Blueprint('sticky_notes', __name__, url_prefix='/api/sticky-notes')

# פלטת צבעים מוגדרת (Bootstrap inspired + pastels)
ALLOWED_COLORS = [
    '#fff475',  # צהוב פתק קלאסי
    '#ffb3ba',  # ורוד פסטל
    '#bae1ff',  # כחול פסטל
    '#baffc9',  # ירוק פסטל
    '#ffffba',  # צהוב בהיר
    '#e0c3fc',  # סגול פסטל
    '#ffd8b1',  # כתום פסטל
]

# גבולות וולידציה
MAX_CONTENT_LENGTH = 2000
MAX_WIDTH = 600
MAX_HEIGHT = 600
MIN_WIDTH = 150
MIN_HEIGHT = 100

def require_auth(f):
    """Decorator to require user authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            emit_event('sticky_notes_unauthorized_access', {
                'endpoint': request.endpoint,
                'ip': request.remote_addr
            })
            return jsonify({'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return decorated

def validate_color(color):
    """Validate that color is in allowed palette."""
    return color in ALLOWED_COLORS

def validate_content(content):
    """Validate note content."""
    if not isinstance(content, str):
        return False, "Content must be string"
    if len(content) > MAX_CONTENT_LENGTH:
        return False, f"Content exceeds {MAX_CONTENT_LENGTH} characters"
    return True, None

def validate_dimensions(width, height):
    """Validate note dimensions."""
    if not (MIN_WIDTH <= width <= MAX_WIDTH):
        return False, f"Width must be between {MIN_WIDTH}-{MAX_WIDTH}px"
    if not (MIN_HEIGHT <= height <= MAX_HEIGHT):
        return False, f"Height must be between {MIN_HEIGHT}-{MAX_HEIGHT}px"
    return True, None

def validate_file_name(file_name):
    """Basic validation for file_name to prevent injection."""
    if not file_name or not isinstance(file_name, str):
        return False, "Invalid file_name"
    if len(file_name) > 500:
        return False, "file_name too long"
    # אפשר רק תווים בטוחים: אותיות, ספרות, נקודה, מקף, קו תחתון, /
    if not re.match(r'^[a-zA-Z0-9._/\-\u0590-\u05FF ]+$', file_name):
        return False, "file_name contains invalid characters"
    return True, None


@sticky_notes_bp.route('/list/<path:file_name>', methods=['GET'])
@require_auth
@traced('get_sticky_notes')
def get_sticky_notes(file_name):
    """
    Get all sticky notes for a specific file and user.

    :param file_name: The markdown file name
    :return: JSON list of notes
    """
    user_id = session['user_id']

    # Validate file_name
    valid, error = validate_file_name(file_name)
    if not valid:
        logger.warning(f"Invalid file_name in get_sticky_notes: {error}", extra={'user_id': user_id})
        return jsonify({'error': error}), 400

    try:
        repo = Repository.get_instance()
        notes = list(repo.db.markdown_sticky_notes.find({
            'user_id': user_id,
            'file_name': file_name,
            'is_active': True
        }).sort('z_index', 1))

        # Convert ObjectId to string for JSON serialization
        for note in notes:
            note['_id'] = str(note['_id'])
            # Convert datetime to ISO format
            note['created_at'] = note['created_at'].isoformat()
            note['updated_at'] = note['updated_at'].isoformat()

        emit_event('sticky_notes_retrieved', {
            'user_id': user_id,
            'file_name': file_name,
            'count': len(notes)
        })

        return jsonify({'notes': notes}), 200

    except Exception as e:
        logger.error(f"Error retrieving sticky notes: {str(e)}", extra={'user_id': user_id})
        internal_alerts.send_alert(
            level='error',
            message=f'Failed to retrieve sticky notes for user {user_id}',
            context={'error': str(e), 'file_name': file_name}
        )
        return jsonify({'error': 'Failed to retrieve notes'}), 500


@sticky_notes_bp.route('/create', methods=['POST'])
@require_auth
@traced('create_sticky_note')
def create_sticky_note():
    """
    Create a new sticky note.

    Expected JSON payload:
    {
        "file_name": str,
        "anchor_line": int,
        "content": str,
        "position": {"x": float, "y": float},
        "size": {"width": int, "height": int},
        "color": str (optional)
    }
    """
    user_id = session['user_id']
    data = request.get_json()

    # Validate required fields
    required_fields = ['file_name', 'anchor_line', 'content', 'position', 'size']
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400

    # Validate file_name
    valid, error = validate_file_name(data['file_name'])
    if not valid:
        return jsonify({'error': error}), 400

    # Validate content
    valid, error = validate_content(data['content'])
    if not valid:
        return jsonify({'error': error}), 400

    # Validate dimensions
    size = data['size']
    valid, error = validate_dimensions(size.get('width', 250), size.get('height', 200))
    if not valid:
        return jsonify({'error': error}), 400

    # Validate color
    color = data.get('color', ALLOWED_COLORS[0])
    if not validate_color(color):
        color = ALLOWED_COLORS[0]

    try:
        repo = Repository.get_instance()

        # Get max z_index for this user/file to place new note on top
        max_z = repo.db.markdown_sticky_notes.find_one(
            {'user_id': user_id, 'file_name': data['file_name']},
            sort=[('z_index', -1)]
        )
        z_index = (max_z['z_index'] + 1) if max_z else 1

        note = {
            'user_id': user_id,
            'file_name': data['file_name'],
            'anchor_line': int(data['anchor_line']),
            'position': {
                'x': float(data['position']['x']),
                'y': float(data['position']['y'])
            },
            'size': {
                'width': int(size.get('width', 250)),
                'height': int(size.get('height', 200))
            },
            'content': data['content'].strip(),
            'color': color,
            'is_minimized': False,
            'z_index': z_index,
            'created_at': datetime.now(timezone.utc),
            'updated_at': datetime.now(timezone.utc),
            'is_active': True
        }

        result = repo.db.markdown_sticky_notes.insert_one(note)
        note['_id'] = str(result.inserted_id)
        note['created_at'] = note['created_at'].isoformat()
        note['updated_at'] = note['updated_at'].isoformat()

        emit_event('sticky_note_created', {
            'user_id': user_id,
            'file_name': data['file_name'],
            'note_id': str(result.inserted_id)
        })

        return jsonify({'note': note}), 201

    except Exception as e:
        logger.error(f"Error creating sticky note: {str(e)}", extra={'user_id': user_id})
        internal_alerts.send_alert(
            level='error',
            message=f'Failed to create sticky note for user {user_id}',
            context={'error': str(e)}
        )
        return jsonify({'error': 'Failed to create note'}), 500


@sticky_notes_bp.route('/update/<note_id>', methods=['PUT'])
@require_auth
@traced('update_sticky_note')
def update_sticky_note(note_id):
    """
    Update an existing sticky note.

    Allowed updates: content, position, size, color, is_minimized, z_index
    """
    user_id = session['user_id']
    data = request.get_json()

    try:
        repo = Repository.get_instance()

        # Verify note exists and belongs to user
        note = repo.db.markdown_sticky_notes.find_one({
            '_id': ObjectId(note_id),
            'user_id': user_id,
            'is_active': True
        })

        if not note:
            return jsonify({'error': 'Note not found or access denied'}), 404

        # Build update dict
        update_fields = {}

        if 'content' in data:
            valid, error = validate_content(data['content'])
            if not valid:
                return jsonify({'error': error}), 400
            update_fields['content'] = data['content'].strip()

        if 'position' in data:
            update_fields['position'] = {
                'x': float(data['position']['x']),
                'y': float(data['position']['y'])
            }

        if 'size' in data:
            width = int(data['size'].get('width', note['size']['width']))
            height = int(data['size'].get('height', note['size']['height']))
            valid, error = validate_dimensions(width, height)
            if not valid:
                return jsonify({'error': error}), 400
            update_fields['size'] = {'width': width, 'height': height}

        if 'color' in data:
            if validate_color(data['color']):
                update_fields['color'] = data['color']

        if 'is_minimized' in data:
            update_fields['is_minimized'] = bool(data['is_minimized'])

        if 'z_index' in data:
            update_fields['z_index'] = int(data['z_index'])

        update_fields['updated_at'] = datetime.now(timezone.utc)

        # Perform update
        repo.db.markdown_sticky_notes.update_one(
            {'_id': ObjectId(note_id), 'user_id': user_id},
            {'$set': update_fields}
        )

        # Fetch updated note
        updated_note = repo.db.markdown_sticky_notes.find_one({'_id': ObjectId(note_id)})
        updated_note['_id'] = str(updated_note['_id'])
        updated_note['created_at'] = updated_note['created_at'].isoformat()
        updated_note['updated_at'] = updated_note['updated_at'].isoformat()

        emit_event('sticky_note_updated', {
            'user_id': user_id,
            'note_id': note_id,
            'updated_fields': list(update_fields.keys())
        })

        return jsonify({'note': updated_note}), 200

    except Exception as e:
        logger.error(f"Error updating sticky note: {str(e)}", extra={'user_id': user_id})
        return jsonify({'error': 'Failed to update note'}), 500


@sticky_notes_bp.route('/delete/<note_id>', methods=['DELETE'])
@require_auth
@traced('delete_sticky_note')
def delete_sticky_note(note_id):
    """
    Soft-delete a sticky note (set is_active=False).
    """
    user_id = session['user_id']

    try:
        repo = Repository.get_instance()

        result = repo.db.markdown_sticky_notes.update_one(
            {
                '_id': ObjectId(note_id),
                'user_id': user_id,
                'is_active': True
            },
            {
                '$set': {
                    'is_active': False,
                    'updated_at': datetime.now(timezone.utc)
                }
            }
        )

        if result.matched_count == 0:
            return jsonify({'error': 'Note not found or already deleted'}), 404

        emit_event('sticky_note_deleted', {
            'user_id': user_id,
            'note_id': note_id
        })

        return jsonify({'message': 'Note deleted successfully'}), 200

    except Exception as e:
        logger.error(f"Error deleting sticky note: {str(e)}", extra={'user_id': user_id})
        return jsonify({'error': 'Failed to delete note'}), 500


@sticky_notes_bp.route('/bring-to-front/<note_id>', methods=['POST'])
@require_auth
@traced('bring_note_to_front')
def bring_to_front(note_id):
    """
    Bring a note to front by setting its z_index to max+1.
    """
    user_id = session['user_id']

    try:
        repo = Repository.get_instance()

        # Get the note
        note = repo.db.markdown_sticky_notes.find_one({
            '_id': ObjectId(note_id),
            'user_id': user_id,
            'is_active': True
        })

        if not note:
            return jsonify({'error': 'Note not found'}), 404

        # Get max z_index for this file
        max_z = repo.db.markdown_sticky_notes.find_one(
            {'user_id': user_id, 'file_name': note['file_name'], 'is_active': True},
            sort=[('z_index', -1)]
        )

        new_z = (max_z['z_index'] + 1) if max_z else 1

        repo.db.markdown_sticky_notes.update_one(
            {'_id': ObjectId(note_id)},
            {'$set': {'z_index': new_z, 'updated_at': datetime.now(timezone.utc)}}
        )

        return jsonify({'z_index': new_z}), 200

    except Exception as e:
        logger.error(f"Error bringing note to front: {str(e)}", extra={'user_id': user_id})
        return jsonify({'error': 'Failed to update z-index'}), 500
```

### 2. רישום ה-Blueprint ב-`app.py`

הוסף את הקטע הבא ב-`webapp/app.py` לאחר רישום blueprints אחרים:

```python
# Import sticky notes blueprint
from webapp.sticky_notes_api import sticky_notes_bp

# Register sticky notes blueprint
app.register_blueprint(sticky_notes_bp)
```

---

## 🎨 Frontend: תבנית וקוד JavaScript

### שינויים ב-`webapp/templates/md_preview.html`

#### 1. הוספת CSS לפתקים

הוסף את הסגנונות הבאים בתוך תגית `<style>` קיימת (או צור חדשה):

```css
/* ===== Sticky Notes Styles ===== */

/* כפתור יצירת פתק - FAB צף */
.sticky-notes-fab {
    position: fixed;
    left: 20px;
    top: 50%;
    transform: translateY(-50%);
    width: 56px;
    height: 56px;
    border-radius: 50%;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    border: none;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    cursor: pointer;
    z-index: 1000;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 24px;
    transition: transform 0.2s, box-shadow 0.2s;
}

.sticky-notes-fab:hover {
    transform: translateY(-50%) scale(1.1);
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.4);
}

.sticky-notes-fab:active {
    transform: translateY(-50%) scale(0.95);
}

/* קונטיינר לפתקים */
.sticky-notes-container {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    pointer-events: none; /* לא חוסם אינטראקציה עם התוכן */
    z-index: 100;
}

/* פתק בודד */
.sticky-note {
    position: absolute;
    background: #fff475;
    border-radius: 8px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    padding: 12px;
    cursor: move;
    pointer-events: auto;
    display: flex;
    flex-direction: column;
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    transition: box-shadow 0.2s, transform 0.1s;
    min-width: 150px;
    min-height: 100px;
    resize: both;
    overflow: auto;
}

.sticky-note:hover {
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.25);
}

.sticky-note.minimized {
    height: 40px !important;
    min-height: 40px;
    resize: none;
    overflow: hidden;
}

/* כותרת הפתק (drag handle + פקדים) */
.sticky-note-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
    padding-bottom: 4px;
    border-bottom: 1px solid rgba(0, 0, 0, 0.1);
    cursor: move;
}

.sticky-note.minimized .sticky-note-header {
    margin-bottom: 0;
    border-bottom: none;
}

.sticky-note-title {
    font-size: 11px;
    color: rgba(0, 0, 0, 0.5);
    font-weight: 600;
    user-select: none;
    flex: 1;
}

.sticky-note-controls {
    display: flex;
    gap: 4px;
}

.sticky-note-btn {
    background: none;
    border: none;
    cursor: pointer;
    padding: 2px 4px;
    font-size: 14px;
    color: rgba(0, 0, 0, 0.6);
    transition: color 0.2s;
}

.sticky-note-btn:hover {
    color: rgba(0, 0, 0, 0.9);
}

/* תוכן הפתק */
.sticky-note-content {
    flex: 1;
    overflow-y: auto;
    font-size: 14px;
    line-height: 1.5;
    color: #333;
    white-space: pre-wrap;
    word-wrap: break-word;
}

.sticky-note.minimized .sticky-note-content {
    display: none;
}

/* טקסטאריה לעריכה */
.sticky-note-textarea {
    width: 100%;
    height: 100%;
    border: none;
    background: transparent;
    resize: none;
    font-family: inherit;
    font-size: 14px;
    line-height: 1.5;
    color: #333;
    outline: none;
    padding: 0;
}

/* פוטר עם כפתורי שמירה/ביטול (מצב עריכה) */
.sticky-note-footer {
    display: flex;
    gap: 8px;
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid rgba(0, 0, 0, 0.1);
}

.sticky-note-footer button {
    flex: 1;
    padding: 6px 12px;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 12px;
    font-weight: 600;
    transition: opacity 0.2s;
}

.sticky-note-footer button:hover {
    opacity: 0.8;
}

.btn-save {
    background: #28a745;
    color: white;
}

.btn-cancel {
    background: #6c757d;
    color: white;
}

/* אינדיקטור אנקור (קו שמחבר לשורה) */
.sticky-note-anchor-indicator {
    position: absolute;
    background: rgba(102, 126, 234, 0.3);
    pointer-events: none;
    z-index: 50;
}

/* בורר צבעים */
.color-picker-popup {
    position: absolute;
    background: white;
    border-radius: 8px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
    padding: 12px;
    display: flex;
    gap: 8px;
    z-index: 2000;
}

.color-option {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    cursor: pointer;
    border: 2px solid transparent;
    transition: transform 0.2s, border-color 0.2s;
}

.color-option:hover {
    transform: scale(1.1);
}

.color-option.active {
    border-color: #333;
    box-shadow: 0 0 0 2px white, 0 0 0 4px #333;
}

/* RTL adjustments */
[dir="rtl"] .sticky-notes-fab {
    left: auto;
    right: 20px;
}
```

#### 2. הוספת HTML לפתקים

הוסף את הקטע הבא לפני תגית `</body>` ב-`md_preview.html`:

```html
<!-- Sticky Notes FAB Button -->
<button class="sticky-notes-fab" id="createNoteBtn" title="צור פתק דביק">
    📌
</button>

<!-- Sticky Notes Container (overlay) -->
<div class="sticky-notes-container" id="stickyNotesContainer"></div>
```

#### 3. הוספת JavaScript לניהול פתקים

הוסף את הסקריפט הבא לפני `</body>`:

```html
<script>
/**
 * Sticky Notes Manager for Markdown Preview
 * Handles creation, editing, dragging, resizing, and persistence of notes
 */
(function() {
    'use strict';

    const COLORS = [
        '#fff475', '#ffb3ba', '#bae1ff', '#baffc9',
        '#ffffba', '#e0c3fc', '#ffd8b1'
    ];

    const FILE_NAME = "{{ file.file_name }}";  // Jinja2 template variable
    const API_BASE = '/api/sticky-notes';

    let notes = [];
    let draggedNote = null;
    let dragOffset = { x: 0, y: 0 };
    let colorPickerPopup = null;

    // Initialize on page load
    document.addEventListener('DOMContentLoaded', () => {
        loadNotes();
        setupCreateButton();
    });

    // ===== API Calls =====

    async function loadNotes() {
        try {
            const response = await fetch(`${API_BASE}/list/${encodeURIComponent(FILE_NAME)}`);
            if (!response.ok) throw new Error('Failed to load notes');

            const data = await response.json();
            notes = data.notes || [];
            renderNotes();
        } catch (error) {
            console.error('Error loading sticky notes:', error);
        }
    }

    async function createNote(noteData) {
        try {
            const response = await fetch(`${API_BASE}/create`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(noteData)
            });

            if (!response.ok) throw new Error('Failed to create note');

            const data = await response.json();
            notes.push(data.note);
            renderNote(data.note);
            return data.note;
        } catch (error) {
            console.error('Error creating note:', error);
            alert('שגיאה ביצירת הפתק');
        }
    }

    async function updateNote(noteId, updates) {
        try {
            const response = await fetch(`${API_BASE}/update/${noteId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(updates)
            });

            if (!response.ok) throw new Error('Failed to update note');

            const data = await response.json();
            const index = notes.findIndex(n => n._id === noteId);
            if (index !== -1) notes[index] = data.note;
            return data.note;
        } catch (error) {
            console.error('Error updating note:', error);
            alert('שגיאה בעדכון הפתק');
        }
    }

    async function deleteNote(noteId) {
        try {
            const response = await fetch(`${API_BASE}/delete/${noteId}`, {
                method: 'DELETE'
            });

            if (!response.ok) throw new Error('Failed to delete note');

            notes = notes.filter(n => n._id !== noteId);
            const element = document.getElementById(`note-${noteId}`);
            if (element) element.remove();
        } catch (error) {
            console.error('Error deleting note:', error);
            alert('שגיאה במחיקת הפתק');
        }
    }

    async function bringToFront(noteId) {
        try {
            const response = await fetch(`${API_BASE}/bring-to-front/${noteId}`, {
                method: 'POST'
            });

            if (!response.ok) throw new Error('Failed to bring to front');

            const data = await response.json();
            const note = notes.find(n => n._id === noteId);
            if (note) {
                note.z_index = data.z_index;
                const element = document.getElementById(`note-${noteId}`);
                if (element) element.style.zIndex = data.z_index;
            }
        } catch (error) {
            console.error('Error bringing note to front:', error);
        }
    }

    // ===== Rendering =====

    function renderNotes() {
        const container = document.getElementById('stickyNotesContainer');
        container.innerHTML = '';
        notes.forEach(note => renderNote(note));
    }

    function renderNote(note) {
        const container = document.getElementById('stickyNotesContainer');

        const noteEl = document.createElement('div');
        noteEl.id = `note-${note._id}`;
        noteEl.className = `sticky-note ${note.is_minimized ? 'minimized' : ''}`;
        noteEl.style.left = `${note.position.x}%`;
        noteEl.style.top = `${note.position.y}%`;
        noteEl.style.width = `${note.size.width}px`;
        noteEl.style.height = `${note.size.height}px`;
        noteEl.style.backgroundColor = note.color;
        noteEl.style.zIndex = note.z_index;

        noteEl.innerHTML = `
            <div class="sticky-note-header">
                <span class="sticky-note-title">שורה ${note.anchor_line}</span>
                <div class="sticky-note-controls">
                    <button class="sticky-note-btn" data-action="color" title="שנה צבע">🎨</button>
                    <button class="sticky-note-btn" data-action="minimize" title="${note.is_minimized ? 'הרחב' : 'מזער'}">${note.is_minimized ? '🔽' : '🔼'}</button>
                    <button class="sticky-note-btn" data-action="edit" title="ערוך">✏️</button>
                    <button class="sticky-note-btn" data-action="delete" title="מחק">🗑️</button>
                </div>
            </div>
            <div class="sticky-note-content">${escapeHtml(note.content)}</div>
        `;

        // Event listeners
        setupNoteDragging(noteEl, note);
        setupNoteControls(noteEl, note);
        setupNoteResizing(noteEl, note);
        setupNoteFocus(noteEl, note);

        container.appendChild(noteEl);
    }

    // ===== Event Handlers =====

    function setupCreateButton() {
        const btn = document.getElementById('createNoteBtn');
        btn.addEventListener('click', () => {
            // Get current scroll position to anchor note near viewport center
            const scrollY = window.scrollY;
            const viewportHeight = window.innerHeight;
            const approxLine = Math.floor(scrollY / 20); // Rough estimate

            const noteData = {
                file_name: FILE_NAME,
                anchor_line: approxLine,
                content: 'פתק חדש...',
                position: { x: 20, y: 30 }, // 20% from left, 30% from top
                size: { width: 250, height: 200 },
                color: COLORS[0]
            };

            createNote(noteData);
        });
    }

    function setupNoteDragging(noteEl, note) {
        const header = noteEl.querySelector('.sticky-note-header');

        header.addEventListener('mousedown', (e) => {
            if (e.target.closest('.sticky-note-btn')) return;

            draggedNote = { element: noteEl, note: note };
            const rect = noteEl.getBoundingClientRect();
            const containerRect = document.getElementById('stickyNotesContainer').getBoundingClientRect();

            dragOffset.x = e.clientX - rect.left;
            dragOffset.y = e.clientY - rect.top;

            noteEl.style.cursor = 'grabbing';
            bringToFront(note._id);

            e.preventDefault();
        });
    }

    document.addEventListener('mousemove', (e) => {
        if (!draggedNote) return;

        const container = document.getElementById('stickyNotesContainer');
        const containerRect = container.getBoundingClientRect();

        let newX = e.clientX - containerRect.left - dragOffset.x;
        let newY = e.clientY - containerRect.top - dragOffset.y;

        // Keep within bounds
        newX = Math.max(0, Math.min(newX, containerRect.width - draggedNote.element.offsetWidth));
        newY = Math.max(0, Math.min(newY, containerRect.height - draggedNote.element.offsetHeight));

        // Convert to percentage
        const xPercent = (newX / containerRect.width) * 100;
        const yPercent = (newY / containerRect.height) * 100;

        draggedNote.element.style.left = `${xPercent}%`;
        draggedNote.element.style.top = `${yPercent}%`;
    });

    document.addEventListener('mouseup', () => {
        if (!draggedNote) return;

        const containerRect = document.getElementById('stickyNotesContainer').getBoundingClientRect();
        const rect = draggedNote.element.getBoundingClientRect();

        const xPercent = ((rect.left - containerRect.left) / containerRect.width) * 100;
        const yPercent = ((rect.top - containerRect.top) / containerRect.height) * 100;

        updateNote(draggedNote.note._id, {
            position: { x: xPercent, y: yPercent }
        });

        draggedNote.element.style.cursor = 'move';
        draggedNote = null;
    });

    function setupNoteControls(noteEl, note) {
        noteEl.addEventListener('click', (e) => {
            const btn = e.target.closest('.sticky-note-btn');
            if (!btn) return;

            const action = btn.dataset.action;

            switch (action) {
                case 'minimize':
                    toggleMinimize(noteEl, note);
                    break;
                case 'edit':
                    enterEditMode(noteEl, note);
                    break;
                case 'delete':
                    if (confirm('למחוק את הפתק?')) {
                        deleteNote(note._id);
                    }
                    break;
                case 'color':
                    showColorPicker(noteEl, note, btn);
                    break;
            }
        });
    }

    function setupNoteResizing(noteEl, note) {
        // Use ResizeObserver to detect when user manually resizes
        const resizeObserver = new ResizeObserver(entries => {
            for (let entry of entries) {
                const newWidth = Math.round(entry.contentRect.width);
                const newHeight = Math.round(entry.contentRect.height);

                // Update server (debounced)
                clearTimeout(noteEl._resizeTimeout);
                noteEl._resizeTimeout = setTimeout(() => {
                    updateNote(note._id, {
                        size: { width: newWidth, height: newHeight }
                    });
                }, 500);
            }
        });

        resizeObserver.observe(noteEl);
    }

    function setupNoteFocus(noteEl, note) {
        noteEl.addEventListener('mousedown', () => {
            bringToFront(note._id);
        });
    }

    function toggleMinimize(noteEl, note) {
        const isMinimized = noteEl.classList.toggle('minimized');
        updateNote(note._id, { is_minimized: isMinimized });

        const btn = noteEl.querySelector('[data-action="minimize"]');
        btn.textContent = isMinimized ? '🔽' : '🔼';
        btn.title = isMinimized ? 'הרחב' : 'מזער';
    }

    function enterEditMode(noteEl, note) {
        const contentEl = noteEl.querySelector('.sticky-note-content');
        const currentContent = note.content;

        contentEl.innerHTML = `<textarea class="sticky-note-textarea">${escapeHtml(currentContent)}</textarea>`;
        const textarea = contentEl.querySelector('textarea');
        textarea.focus();
        textarea.select();

        // Add footer with save/cancel
        const footer = document.createElement('div');
        footer.className = 'sticky-note-footer';
        footer.innerHTML = `
            <button class="btn-save">שמור</button>
            <button class="btn-cancel">ביטול</button>
        `;

        noteEl.appendChild(footer);

        footer.querySelector('.btn-save').addEventListener('click', () => {
            const newContent = textarea.value.trim();
            if (newContent) {
                updateNote(note._id, { content: newContent }).then(updatedNote => {
                    if (updatedNote) {
                        note.content = updatedNote.content;
                        exitEditMode(noteEl, note);
                    }
                });
            }
        });

        footer.querySelector('.btn-cancel').addEventListener('click', () => {
            exitEditMode(noteEl, note);
        });
    }

    function exitEditMode(noteEl, note) {
        const contentEl = noteEl.querySelector('.sticky-note-content');
        contentEl.innerHTML = escapeHtml(note.content);

        const footer = noteEl.querySelector('.sticky-note-footer');
        if (footer) footer.remove();
    }

    function showColorPicker(noteEl, note, btn) {
        // Remove existing popup
        if (colorPickerPopup) colorPickerPopup.remove();

        const popup = document.createElement('div');
        popup.className = 'color-picker-popup';
        popup.style.left = `${btn.offsetLeft}px`;
        popup.style.top = `${btn.offsetTop + btn.offsetHeight + 5}px`;

        COLORS.forEach(color => {
            const option = document.createElement('div');
            option.className = 'color-option';
            option.style.backgroundColor = color;
            if (color === note.color) option.classList.add('active');

            option.addEventListener('click', () => {
                noteEl.style.backgroundColor = color;
                updateNote(note._id, { color });
                note.color = color;
                popup.remove();
                colorPickerPopup = null;
            });

            popup.appendChild(option);
        });

        noteEl.appendChild(popup);
        colorPickerPopup = popup;

        // Close on outside click
        setTimeout(() => {
            document.addEventListener('click', function closePopup(e) {
                if (!popup.contains(e.target) && e.target !== btn) {
                    popup.remove();
                    colorPickerPopup = null;
                    document.removeEventListener('click', closePopup);
                }
            });
        }, 10);
    }

    // ===== Utilities =====

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

})();
</script>
```

---

## 🔐 אבטחה ושיקולים

### 1. אימות והרשאות
- **Session-based auth:** שימוש ב-`session['user_id']` לוודא שרק המשתמש רואה את הפתקים שלו.
- **Decorator `@require_auth`:** כל endpoint מאובטח.
- **ACL:** כל שאילתת DB מסננת לפי `user_id`.

### 2. וולידציה
- **Input validation:** בדיקת אורך תוכן, גודל פתק, שם קובץ (למניעת injection).
- **Color whitelist:** רק צבעים מאושרים.
- **Rate limiting:** מומלץ להוסיף `flask-limiter` למניעת spam.

### 3. XSS Protection
- **Frontend:** שימוש ב-`escapeHtml()` לפני הצגת תוכן מהשרת.
- **Backend:** MongoDB מטפל בescaping, אך יש לוודא שלא מוזרקים tags HTML בתוכן.

### 4. CSRF
- אם Flask מוגדר עם `flask-wtf`, יש לוודא שיש CSRF token ב-requests (או לפטור API routes).

---

## 📊 Observability & Monitoring

### Events
כל פעולה פולטת event דרך `emit_event()`:
- `sticky_notes_retrieved`
- `sticky_note_created`
- `sticky_note_updated`
- `sticky_note_deleted`
- `sticky_notes_unauthorized_access`

### Tracing
כל endpoint מסומן ב-`@traced` לטרייסינג מלא.

### Alerts
שגיאות קריטיות מדווחות דרך `internal_alerts.send_alert()`.

### Logging
שימוש ב-`get_logger(__name__)` לכל לוגים.

---

## 🚀 תהליך פריסה (Deployment)

### 1. יצירת אינדקסים ב-MongoDB

הרץ סקריפט אחד (או דרך Flask shell):

```python
from database.repository import Repository

repo = Repository.get_instance()
db = repo.db

# Create indexes
db.markdown_sticky_notes.create_index([
    ("user_id", 1),
    ("file_name", 1),
    ("is_active", 1)
])

db.markdown_sticky_notes.create_index([
    ("user_id", 1),
    ("file_name", 1),
    ("anchor_line", 1)
])

print("Indexes created successfully!")
```

### 2. בדיקות (Testing)

#### Unit Tests
צור `tests/test_sticky_notes_api.py`:

```python
import pytest
from webapp.app import app
from unittest.mock import MagicMock

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_create_note_unauthorized(client):
    """Test that creating note without auth returns 401"""
    response = client.post('/api/sticky-notes/create', json={})
    assert response.status_code == 401

def test_create_note_missing_fields(client):
    """Test validation of required fields"""
    with client.session_transaction() as sess:
        sess['user_id'] = 123

    response = client.post('/api/sticky-notes/create', json={
        'file_name': 'test.md'
        # Missing other required fields
    })
    assert response.status_code == 400

# Add more tests...
```

#### Integration Tests
בדוק ב-browser:
1. פתח קובץ Markdown
2. לחץ על FAB
3. ודא שפתק נוצר
4. נסה לגרור, לשנות גודל, לערוך
5. רענן דף – ודא שהפתק נשמר

### 3. Performance Testing

- בדוק טעינת 50+ פתקים באותו קובץ
- ודא שאין lag בגרירה
- בדוק memory leaks (Chrome DevTools)

---

## 🎨 UX ו-UI משופרים (עתידי)

### Phase 2 - שיפורים אפשריים:
1. **Rich Text:** תמיכה ב-Markdown בסיסי בתוך הפתק (bold, italic, lists).
2. **Anchor Line Highlighting:** סימון ויזואלי של השורה המקורית במסמך.
3. **Collaborative Notes:** שיתוף פתקים בין משתמשים (דורש WebSocket/SSE).
4. **Export to PDF:** הכללת פתקים בייצוא מסמך.
5. **Search in Notes:** חיפוש טקסט בכל הפתקים של משתמש.
6. **Tags & Categories:** ארגון פתקים לפי תגיות.
7. **Note Templates:** תבניות מוכנות (TODO, QUESTION, IDEA).

---

## 📚 נספחים

### קישורים רלוונטיים
- **Repository pattern:** `database/repository.py`
- **Cache manager:** `cache_manager.py`
- **Observability:** `observability/events.py`, `observability/tracing.py`
- **Bookmarks API reference:** `webapp/bookmarks_api.py` (דוגמה דומה)

### תלויות נדרשות
- Flask
- PyMongo
- Existing observability stack

### מילון מונחים
- **FAB:** Floating Action Button
- **Anchor Line:** השורה בקובץ המקור שאליה הפתק מעוגן
- **z-index:** סדר שכבות (stacking order)
- **Sticky Note:** פתק דביק

---

## ✅ Checklist למימוש

- [ ] יצירת `webapp/sticky_notes_api.py` עם כל ה-endpoints
- [ ] רישום Blueprint ב-`app.py`
- [ ] הוספת CSS ל-`md_preview.html`
- [ ] הוספת HTML (FAB + container)
- [ ] הוספת JavaScript לניהול פתקים
- [ ] יצירת אינדקסים ב-MongoDB
- [ ] כתיבת unit tests
- [ ] בדיקות integration ידניות
- [ ] בדיקות performance
- [ ] תיעוד API (Swagger/OpenAPI - אופציונלי)
- [ ] Code review
- [ ] Merge ל-main branch

---

**סיום המדריך.** בהצלחה במימוש! 🎉
