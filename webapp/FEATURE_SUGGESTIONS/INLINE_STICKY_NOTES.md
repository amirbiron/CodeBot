# מדריך מימוש: פתקים דביקים אינליין בתצוגת Markdown

## 📌 סקירה כללית

### מטרת הפיצ'ר
הוספת מערכת פתקים דביקים (Sticky Notes) אינליין לתצוגת Markdown (`md_preview.html`), המאפשרת למשתמשים להוסיף הערות אישיות על גבי מסמכים ללא עריכת הקובץ המקורי.

### יתרונות מרכזיים
- **רישום הערות מהיר** - ללא צורך בעריכת המסמך
- **הקשר ויזואלי** - הפתקים מעוגנים לשורות ספציפיות
- **אישי ופרטי** - כל משתמש רואה רק את הפתקים שלו
- **ממשק נוח** - גרירה, שינוי גודל ומיזעור

### מגבלות וסקופ
- **תצוגת Markdown בלבד** - לא בעורך הטקסט או בקבצי קוד
- **פר-משתמש ופר-קובץ** - ללא שיתוף בין משתמשים
- **ללא סנכרון בזמן אמת** - עדכון בטעינה מחדש
- **לא כלול בייצוא** - לא מודפס או מיוצא עם המסמך

---

## 🏗️ ארכיטקטורת המערכת

### רכיבים עיקריים

```
┌─────────────────────────────────────────────────┐
│                Frontend (Client)                 │
├─────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌─────────────┐              │
│  │ StickyNotes  │  │  NoteEditor │              │
│  │   Manager    │  │  Component  │              │
│  └──────────────┘  └─────────────┘              │
│         │                 │                      │
│         └────────┬────────┘                      │
│                  ▼                               │
│  ┌──────────────────────────────┐               │
│  │   LocalStorage / IndexedDB   │               │
│  └──────────────────────────────┘               │
└─────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────┐
│               Backend (Server)                   │
├─────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌─────────────┐              │
│  │  Notes API   │  │   Database  │              │
│  │  Endpoint    │  │   (SQLite)  │              │
│  └──────────────┘  └─────────────┘              │
└─────────────────────────────────────────────────┘
```

### מודל נתונים

```typescript
interface StickyNote {
  id: string;              // UUID
  user_id: number;         // מזהה משתמש
  file_path: string;       // נתיב הקובץ המלא
  content: string;         // תוכן הפתק
  line_start: number;      // שורת התחלה
  line_end?: number;       // שורת סיום (אופציונלי)
  position: {              // מיקום על המסך
    x: number;
    y: number;
  };
  size: {                  // גודל הפתק
    width: number;
    height: number;
  };
  color: string;           // צבע רקע (#FFFFCC)
  is_minimized: boolean;   // סטטוס מיזעור
  created_at: string;      // ISO 8601
  updated_at: string;      // ISO 8601
}
```

---

## 💾 מימוש Backend

### 1. סכמת מסד נתונים

```sql
CREATE TABLE IF NOT EXISTS sticky_notes (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    content TEXT NOT NULL,
    line_start INTEGER NOT NULL,
    line_end INTEGER,
    position_x INTEGER DEFAULT 100,
    position_y INTEGER DEFAULT 100,
    width INTEGER DEFAULT 250,
    height INTEGER DEFAULT 200,
    color TEXT DEFAULT '#FFFFCC',
    is_minimized BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    INDEX idx_user_file (user_id, file_path)
);
```

### 2. API Endpoints

```python
# webapp/api/sticky_notes.py

from flask import Blueprint, request, jsonify, g
from database import get_db
import uuid
from datetime import datetime

sticky_notes_bp = Blueprint('sticky_notes', __name__)

@sticky_notes_bp.route('/api/notes/<file_path>', methods=['GET'])
@require_auth
def get_notes(file_path):
    """קבלת כל הפתקים של המשתמש לקובץ מסוים"""
    db = get_db()
    notes = db.execute("""
        SELECT * FROM sticky_notes 
        WHERE user_id = ? AND file_path = ?
        ORDER BY line_start, created_at
    """, (g.user['id'], file_path)).fetchall()
    
    return jsonify([dict(note) for note in notes])

@sticky_notes_bp.route('/api/notes', methods=['POST'])
@require_auth
def create_note():
    """יצירת פתק חדש"""
    data = request.json
    note_id = str(uuid.uuid4())
    
    db = get_db()
    db.execute("""
        INSERT INTO sticky_notes (
            id, user_id, file_path, content, 
            line_start, line_end, position_x, position_y,
            width, height, color, is_minimized
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        note_id,
        g.user['id'],
        data['file_path'],
        data['content'],
        data['line_start'],
        data.get('line_end'),
        data.get('position', {}).get('x', 100),
        data.get('position', {}).get('y', 100),
        data.get('size', {}).get('width', 250),
        data.get('size', {}).get('height', 200),
        data.get('color', '#FFFFCC'),
        False
    ))
    db.commit()
    
    return jsonify({'id': note_id}), 201

@sticky_notes_bp.route('/api/notes/<note_id>', methods=['PUT'])
@require_auth
def update_note(note_id):
    """עדכון פתק קיים"""
    data = request.json
    db = get_db()
    
    # וידוא בעלות
    note = db.execute(
        "SELECT * FROM sticky_notes WHERE id = ? AND user_id = ?",
        (note_id, g.user['id'])
    ).fetchone()
    
    if not note:
        return jsonify({'error': 'Note not found'}), 404
    
    # עדכון השדות
    db.execute("""
        UPDATE sticky_notes 
        SET content = ?, 
            position_x = ?, 
            position_y = ?,
            width = ?, 
            height = ?,
            is_minimized = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND user_id = ?
    """, (
        data.get('content', note['content']),
        data.get('position', {}).get('x', note['position_x']),
        data.get('position', {}).get('y', note['position_y']),
        data.get('size', {}).get('width', note['width']),
        data.get('size', {}).get('height', note['height']),
        data.get('is_minimized', note['is_minimized']),
        note_id,
        g.user['id']
    ))
    db.commit()
    
    return jsonify({'success': True})

@sticky_notes_bp.route('/api/notes/<note_id>', methods=['DELETE'])
@require_auth
def delete_note(note_id):
    """מחיקת פתק"""
    db = get_db()
    
    result = db.execute(
        "DELETE FROM sticky_notes WHERE id = ? AND user_id = ?",
        (note_id, g.user['id'])
    )
    db.commit()
    
    if result.rowcount == 0:
        return jsonify({'error': 'Note not found'}), 404
    
    return jsonify({'success': True})
```

---

## 🎨 מימוש Frontend

### 1. מנהל הפתקים הראשי

```javascript
// webapp/static/js/sticky-notes.js

class StickyNotesManager {
    constructor(filePath, userId) {
        this.filePath = filePath;
        this.userId = userId;
        this.notes = new Map();
        this.activeNote = null;
        this.lineOffsets = new Map(); // מיפוי שורות למיקום בדף
        
        this.init();
    }
    
    async init() {
        // חישוב מיקומי השורות בדף
        this.calculateLineOffsets();
        
        // טעינת פתקים קיימים
        await this.loadNotes();
        
        // יצירת כפתור FAB
        this.createFAB();
        
        // האזנה לאירועי גלילה
        this.attachScrollListener();
        
        // האזנה לשינוי גודל החלון
        window.addEventListener('resize', () => this.recalculatePositions());
    }
    
    calculateLineOffsets() {
        // מציאת כל אלמנטי השורות במסמך
        const lineElements = document.querySelectorAll('[data-line-number]');
        lineElements.forEach(el => {
            const lineNum = parseInt(el.dataset.lineNumber);
            const rect = el.getBoundingClientRect();
            this.lineOffsets.set(lineNum, {
                top: rect.top + window.scrollY,
                left: rect.left,
                height: rect.height
            });
        });
    }
    
    async loadNotes() {
        try {
            const response = await fetch(`/api/notes/${encodeURIComponent(this.filePath)}`);
            const notes = await response.json();
            
            notes.forEach(noteData => {
                this.createNoteElement(noteData);
            });
        } catch (error) {
            console.error('Failed to load notes:', error);
        }
    }
    
    createFAB() {
        const fab = document.createElement('button');
        fab.className = 'sticky-note-fab';
        fab.innerHTML = '➕';
        fab.title = 'הוסף פתק דביק';
        fab.onclick = () => this.createNewNote();
        
        document.body.appendChild(fab);
    }
    
    async createNewNote() {
        // זיהוי השורה הנוכחית בהתאם לגלילה
        const currentLine = this.getCurrentVisibleLine();
        
        const noteData = {
            file_path: this.filePath,
            line_start: currentLine,
            content: '',
            position: { x: 100, y: window.scrollY + 100 },
            size: { width: 250, height: 200 },
            color: '#FFFFCC'
        };
        
        // שליחה לשרת
        const response = await fetch('/api/notes', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(noteData)
        });
        
        const result = await response.json();
        noteData.id = result.id;
        
        // יצירת האלמנט
        const noteElement = this.createNoteElement(noteData);
        noteElement.querySelector('textarea').focus();
    }
    
    createNoteElement(noteData) {
        const note = new StickyNote(noteData, this);
        this.notes.set(noteData.id, note);
        return note.element;
    }
    
    getCurrentVisibleLine() {
        const scrollTop = window.scrollY;
        const viewportHeight = window.innerHeight;
        const midPoint = scrollTop + (viewportHeight / 2);
        
        let closestLine = 1;
        let minDistance = Infinity;
        
        this.lineOffsets.forEach((offset, lineNum) => {
            const distance = Math.abs(offset.top - midPoint);
            if (distance < minDistance) {
                minDistance = distance;
                closestLine = lineNum;
            }
        });
        
        return closestLine;
    }
    
    attachScrollListener() {
        let scrollTimeout;
        window.addEventListener('scroll', () => {
            clearTimeout(scrollTimeout);
            scrollTimeout = setTimeout(() => {
                this.updateNotesVisibility();
            }, 100);
        });
    }
    
    updateNotesVisibility() {
        const scrollTop = window.scrollY;
        const viewportHeight = window.innerHeight;
        
        this.notes.forEach(note => {
            const lineOffset = this.lineOffsets.get(note.data.line_start);
            if (lineOffset) {
                const isVisible = lineOffset.top >= scrollTop && 
                                 lineOffset.top <= scrollTop + viewportHeight;
                note.setVisible(isVisible);
            }
        });
    }
    
    recalculatePositions() {
        this.calculateLineOffsets();
        this.notes.forEach(note => note.updatePosition());
    }
    
    async deleteNote(noteId) {
        if (!confirm('האם למחוק את הפתק?')) {
            return;
        }
        
        try {
            await fetch(`/api/notes/${noteId}`, { method: 'DELETE' });
            const note = this.notes.get(noteId);
            if (note) {
                note.destroy();
                this.notes.delete(noteId);
            }
        } catch (error) {
            console.error('Failed to delete note:', error);
        }
    }
}
```

### 2. מחלקת הפתק הבודד

```javascript
// webapp/static/js/sticky-note.js

class StickyNote {
    constructor(data, manager) {
        this.data = data;
        this.manager = manager;
        this.element = null;
        this.isDragging = false;
        this.isResizing = false;
        this.dragOffset = { x: 0, y: 0 };
        this.saveTimeout = null;
        
        this.create();
    }
    
    create() {
        // יצירת מבנה ה-DOM
        this.element = document.createElement('div');
        this.element.className = 'sticky-note';
        this.element.dataset.noteId = this.data.id;
        this.element.style.cssText = `
            position: absolute;
            left: ${this.data.position.x}px;
            top: ${this.data.position.y}px;
            width: ${this.data.size.width}px;
            height: ${this.data.size.height}px;
            background-color: ${this.data.color};
            box-shadow: 2px 2px 10px rgba(0,0,0,0.2);
            border: 1px solid #E6D600;
            border-radius: 3px;
            padding: 10px;
            z-index: 1000;
            display: ${this.data.is_minimized ? 'none' : 'flex'};
            flex-direction: column;
        `;
        
        // כותרת ופקדים
        const header = document.createElement('div');
        header.className = 'sticky-note-header';
        header.style.cssText = `
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 5px;
            cursor: move;
            user-select: none;
        `;
        
        const title = document.createElement('span');
        title.textContent = `שורה ${this.data.line_start}`;
        title.style.fontSize = '12px';
        title.style.color = '#666';
        
        const controls = document.createElement('div');
        controls.className = 'sticky-note-controls';
        
        // כפתור מיזעור
        const minimizeBtn = document.createElement('button');
        minimizeBtn.innerHTML = '−';
        minimizeBtn.className = 'sticky-note-btn minimize';
        minimizeBtn.onclick = () => this.toggleMinimize();
        
        // כפתור מחיקה
        const deleteBtn = document.createElement('button');
        deleteBtn.innerHTML = '×';
        deleteBtn.className = 'sticky-note-btn delete';
        deleteBtn.onclick = () => this.manager.deleteNote(this.data.id);
        
        controls.appendChild(minimizeBtn);
        controls.appendChild(deleteBtn);
        header.appendChild(title);
        header.appendChild(controls);
        
        // אזור תוכן
        const content = document.createElement('textarea');
        content.className = 'sticky-note-content';
        content.value = this.data.content;
        content.placeholder = 'הקלד הערה...';
        content.style.cssText = `
            flex: 1;
            border: none;
            background: transparent;
            resize: none;
            outline: none;
            font-family: inherit;
            font-size: 14px;
        `;
        
        // האזנה לשינויים
        content.addEventListener('input', () => this.handleContentChange());
        
        // ידית גרירת גודל
        const resizeHandle = document.createElement('div');
        resizeHandle.className = 'sticky-note-resize';
        resizeHandle.style.cssText = `
            position: absolute;
            bottom: 0;
            right: 0;
            width: 15px;
            height: 15px;
            cursor: nwse-resize;
            background: linear-gradient(135deg, transparent 50%, #ccc 50%);
        `;
        
        // הרכבת האלמנטים
        this.element.appendChild(header);
        this.element.appendChild(content);
        this.element.appendChild(resizeHandle);
        
        // הוספה למסמך
        document.body.appendChild(this.element);
        
        // אירועי גרירה
        this.attachDragEvents(header);
        this.attachResizeEvents(resizeHandle);
        
        // אם ממוזער, הצג רק כותרת
        if (this.data.is_minimized) {
            this.minimize();
        }
    }
    
    attachDragEvents(header) {
        header.addEventListener('mousedown', (e) => {
            this.isDragging = true;
            this.dragOffset = {
                x: e.clientX - this.element.offsetLeft,
                y: e.clientY - this.element.offsetTop
            };
            
            this.element.style.zIndex = '1001';
            e.preventDefault();
        });
        
        document.addEventListener('mousemove', (e) => {
            if (!this.isDragging) return;
            
            const newX = e.clientX - this.dragOffset.x;
            const newY = e.clientY - this.dragOffset.y;
            
            this.element.style.left = `${newX}px`;
            this.element.style.top = `${newY}px`;
            
            this.data.position = { x: newX, y: newY };
            this.scheduleSave();
        });
        
        document.addEventListener('mouseup', () => {
            if (this.isDragging) {
                this.isDragging = false;
                this.element.style.zIndex = '1000';
            }
        });
    }
    
    attachResizeEvents(handle) {
        handle.addEventListener('mousedown', (e) => {
            this.isResizing = true;
            this.resizeStart = {
                x: e.clientX,
                y: e.clientY,
                width: this.element.offsetWidth,
                height: this.element.offsetHeight
            };
            e.preventDefault();
            e.stopPropagation();
        });
        
        document.addEventListener('mousemove', (e) => {
            if (!this.isResizing) return;
            
            const newWidth = this.resizeStart.width + (e.clientX - this.resizeStart.x);
            const newHeight = this.resizeStart.height + (e.clientY - this.resizeStart.y);
            
            this.element.style.width = `${Math.max(150, newWidth)}px`;
            this.element.style.height = `${Math.max(100, newHeight)}px`;
            
            this.data.size = {
                width: Math.max(150, newWidth),
                height: Math.max(100, newHeight)
            };
            
            this.scheduleSave();
        });
        
        document.addEventListener('mouseup', () => {
            this.isResizing = false;
        });
    }
    
    handleContentChange() {
        const textarea = this.element.querySelector('textarea');
        this.data.content = textarea.value;
        this.scheduleSave();
    }
    
    scheduleSave() {
        clearTimeout(this.saveTimeout);
        this.saveTimeout = setTimeout(() => this.save(), 500);
    }
    
    async save() {
        try {
            await fetch(`/api/notes/${this.data.id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.data)
            });
        } catch (error) {
            console.error('Failed to save note:', error);
        }
    }
    
    toggleMinimize() {
        if (this.data.is_minimized) {
            this.expand();
        } else {
            this.minimize();
        }
    }
    
    minimize() {
        this.data.is_minimized = true;
        this.element.style.height = '30px';
        this.element.querySelector('textarea').style.display = 'none';
        this.element.querySelector('.sticky-note-resize').style.display = 'none';
        this.element.querySelector('.minimize').innerHTML = '□';
        this.scheduleSave();
    }
    
    expand() {
        this.data.is_minimized = false;
        this.element.style.height = `${this.data.size.height}px`;
        this.element.querySelector('textarea').style.display = 'block';
        this.element.querySelector('.sticky-note-resize').style.display = 'block';
        this.element.querySelector('.minimize').innerHTML = '−';
        this.scheduleSave();
    }
    
    setVisible(isVisible) {
        this.element.style.display = isVisible ? 
            (this.data.is_minimized ? 'block' : 'flex') : 'none';
    }
    
    updatePosition() {
        const lineOffset = this.manager.lineOffsets.get(this.data.line_start);
        if (lineOffset) {
            // עדכון מיקום אנכי בהתאם לשורה
            const relativeY = this.data.position.y - lineOffset.top;
            this.element.style.top = `${lineOffset.top + relativeY}px`;
        }
    }
    
    destroy() {
        this.element.remove();
    }
}
```

### 3. סגנונות CSS

```css
/* webapp/static/css/sticky-notes.css */

/* כפתור FAB ליצירת פתק */
.sticky-note-fab {
    position: fixed;
    left: 20px;
    top: 50%;
    transform: translateY(-50%);
    width: 50px;
    height: 50px;
    border-radius: 50%;
    background: #FFD700;
    color: #333;
    border: 2px solid #FFC700;
    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    font-size: 24px;
    cursor: pointer;
    transition: all 0.3s ease;
    z-index: 999;
}

.sticky-note-fab:hover {
    background: #FFC700;
    transform: translateY(-50%) scale(1.1);
    box-shadow: 0 6px 8px rgba(0,0,0,0.15);
}

/* סגנון הפתק */
.sticky-note {
    font-family: 'Segoe UI', Tahoma, sans-serif;
    transition: opacity 0.3s ease;
}

.sticky-note:hover {
    box-shadow: 3px 3px 15px rgba(0,0,0,0.3);
}

.sticky-note-header {
    border-bottom: 1px solid rgba(0,0,0,0.1);
    padding-bottom: 5px;
}

.sticky-note-controls {
    display: flex;
    gap: 5px;
}

.sticky-note-btn {
    width: 20px;
    height: 20px;
    border: none;
    background: transparent;
    cursor: pointer;
    font-size: 16px;
    line-height: 1;
    color: #666;
    transition: color 0.2s ease;
}

.sticky-note-btn:hover {
    color: #333;
}

.sticky-note-btn.delete:hover {
    color: #d32f2f;
}

.sticky-note-content {
    padding: 5px;
    line-height: 1.4;
}

.sticky-note-resize {
    opacity: 0.5;
    transition: opacity 0.2s ease;
}

.sticky-note:hover .sticky-note-resize {
    opacity: 1;
}

/* אנימציות */
@keyframes noteAppear {
    from {
        opacity: 0;
        transform: scale(0.8);
    }
    to {
        opacity: 1;
        transform: scale(1);
    }
}

.sticky-note {
    animation: noteAppear 0.3s ease-out;
}

/* תמיכה ב-Dark Mode */
@media (prefers-color-scheme: dark) {
    .sticky-note {
        background-color: #3a3a3a !important;
        border-color: #555 !important;
        color: #e0e0e0;
    }
    
    .sticky-note-btn {
        color: #aaa;
    }
    
    .sticky-note-btn:hover {
        color: #fff;
    }
    
    .sticky-note-fab {
        background: #555;
        border-color: #666;
        color: #e0e0e0;
    }
}

/* הדפסה - הסתרת פתקים */
@media print {
    .sticky-note,
    .sticky-note-fab {
        display: none !important;
    }
}
```

### 4. אתחול במסמך HTML

```html
<!-- webapp/templates/md_preview.html -->

<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{{ title }}</title>
    <link rel="stylesheet" href="/static/css/markdown.css">
    <link rel="stylesheet" href="/static/css/sticky-notes.css">
</head>
<body>
    <div id="markdown-content">
        <!-- תוכן ה-Markdown עם מספרי שורות -->
        {{ rendered_markdown|safe }}
    </div>
    
    <!-- סקריפטים -->
    <script src="/static/js/sticky-note.js"></script>
    <script src="/static/js/sticky-notes.js"></script>
    
    <script>
        // אתחול מערכת הפתקים
        document.addEventListener('DOMContentLoaded', () => {
            const filePath = '{{ file_path }}';
            const userId = {{ current_user.id }};
            
            // יצירת מנהל הפתקים
            window.stickyNotesManager = new StickyNotesManager(filePath, userId);
        });
    </script>
</body>
</html>
```

---

## 🔧 אופטימיזציות וטיפים

### 1. שמירת נתונים מקומית

```javascript
// שמירה ב-LocalStorage לביצועים משופרים
class LocalStorageCache {
    constructor(userId, filePath) {
        this.key = `sticky-notes-${userId}-${filePath}`;
    }
    
    save(notes) {
        localStorage.setItem(this.key, JSON.stringify(notes));
    }
    
    load() {
        const cached = localStorage.getItem(this.key);
        return cached ? JSON.parse(cached) : [];
    }
    
    clear() {
        localStorage.removeItem(this.key);
    }
}
```

### 2. Debouncing לשמירה

```javascript
class DebouncedSave {
    constructor(saveFunction, delay = 500) {
        this.saveFunction = saveFunction;
        this.delay = delay;
        this.timeout = null;
        this.pending = new Map();
    }
    
    schedule(noteId, data) {
        this.pending.set(noteId, data);
        
        clearTimeout(this.timeout);
        this.timeout = setTimeout(() => {
            this.flush();
        }, this.delay);
    }
    
    async flush() {
        if (this.pending.size === 0) return;
        
        const batch = Array.from(this.pending.entries());
        this.pending.clear();
        
        // שמירה בצ'אנק אחד
        await this.saveFunction(batch);
    }
}
```

### 3. מניעת התנגשויות

```javascript
// נעילה אופטימיסטית למניעת דריסות
class OptimisticLocking {
    constructor() {
        this.versions = new Map();
    }
    
    async updateNote(noteId, data) {
        const currentVersion = this.versions.get(noteId) || 0;
        
        const response = await fetch(`/api/notes/${noteId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'If-Match': currentVersion.toString()
            },
            body: JSON.stringify(data)
        });
        
        if (response.status === 409) {
            // קונפליקט - טען מחדש
            await this.reloadNote(noteId);
            throw new Error('Conflict detected, please retry');
        }
        
        const newVersion = response.headers.get('ETag');
        this.versions.set(noteId, parseInt(newVersion));
    }
}
```

---

## 🚀 הרחבות עתידיות

### 1. תמיכה ב-Markdown בתוך פתקים
```javascript
// שימוש ב-marked.js לרינדור Markdown
const renderedContent = marked.parse(noteContent);
```

### 2. תגיות וקטגוריות
```sql
ALTER TABLE sticky_notes ADD COLUMN tags TEXT;
ALTER TABLE sticky_notes ADD COLUMN category TEXT;
```

### 3. חיפוש בפתקים
```python
@sticky_notes_bp.route('/api/notes/search', methods=['GET'])
def search_notes():
    query = request.args.get('q')
    results = db.execute("""
        SELECT * FROM sticky_notes 
        WHERE user_id = ? AND content LIKE ?
    """, (g.user['id'], f'%{query}%'))
    return jsonify([dict(r) for r in results])
```

### 4. ייצוא פתקים
```javascript
function exportNotes() {
    const notes = Array.from(manager.notes.values());
    const data = notes.map(n => ({
        line: n.data.line_start,
        content: n.data.content
    }));
    
    const blob = new Blob([JSON.stringify(data, null, 2)], 
                          {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    
    const a = document.createElement('a');
    a.href = url;
    a.download = `notes-${filePath}.json`;
    a.click();
}
```

### 5. שיתוף פתקים (מחוץ לסקופ הנוכחי)
```python
# טבלת שיתוף
CREATE TABLE note_sharing (
    note_id TEXT,
    shared_with_user_id INTEGER,
    permission TEXT DEFAULT 'read',
    FOREIGN KEY (note_id) REFERENCES sticky_notes(id),
    FOREIGN KEY (shared_with_user_id) REFERENCES users(id)
);
```

---

## 🔒 אבטחה

### בדיקות חשובות

1. **אימות משתמש** - כל פעולה מוודאת זהות המשתמש
2. **בעלות על פתקים** - משתמש יכול לערוך רק פתקים שלו
3. **סניטציה** - ניקוי תוכן הפתקים מפני XSS
4. **Rate Limiting** - הגבלת כמות הפתקים והעדכונים

```python
# middleware לאימות
def require_auth(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not g.user:
            return jsonify({'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return decorated_function

# סניטציה
import bleach
def sanitize_content(content):
    return bleach.clean(content, tags=[], strip=True)
```

---

## ✅ בדיקות

### בדיקות יחידה

```python
# tests/test_sticky_notes.py

def test_create_note(client, auth):
    auth.login()
    response = client.post('/api/notes', json={
        'file_path': '/test.md',
        'content': 'Test note',
        'line_start': 10
    })
    assert response.status_code == 201
    assert 'id' in response.json

def test_unauthorized_access(client):
    response = client.get('/api/notes/test.md')
    assert response.status_code == 401

def test_note_isolation(client, auth, other_user):
    # משתמש A יוצר פתק
    auth.login()
    note_id = create_note(client)
    
    # משתמש B לא יכול לראות אותו
    auth.logout()
    other_user.login()
    response = client.get(f'/api/notes/{note_id}')
    assert response.status_code == 404
```

### בדיקות E2E

```javascript
// tests/e2e/sticky-notes.test.js

describe('Sticky Notes', () => {
    it('should create a new note on FAB click', async () => {
        await page.click('.sticky-note-fab');
        const note = await page.$('.sticky-note');
        expect(note).toBeTruthy();
    });
    
    it('should save content on blur', async () => {
        const note = await createNote();
        await note.type('textarea', 'Test content');
        await page.click('body'); // Trigger blur
        
        await page.reload();
        const content = await page.$eval('textarea', el => el.value);
        expect(content).toBe('Test content');
    });
    
    it('should drag note to new position', async () => {
        const note = await createNote();
        const initialPos = await note.boundingBox();
        
        await page.mouse.drag(
            {x: initialPos.x + 10, y: initialPos.y + 10},
            {x: initialPos.x + 100, y: initialPos.y + 100}
        );
        
        const newPos = await note.boundingBox();
        expect(newPos.x).toBeGreaterThan(initialPos.x);
    });
});
```

---

## 📋 צ'קליסט למימוש

### שלב 1: תשתית (Backend)
- [ ] יצירת טבלת `sticky_notes` במסד הנתונים
- [ ] מימוש API endpoints (GET, POST, PUT, DELETE)
- [ ] הוספת middleware לאימות
- [ ] בדיקות יחידה ל-API

### שלב 2: ממשק משתמש (Frontend)
- [ ] יצירת מחלקת `StickyNotesManager`
- [ ] יצירת מחלקת `StickyNote`
- [ ] הוספת סגנונות CSS
- [ ] אינטגרציה עם `md_preview.html`

### שלב 3: פיצ'רים בסיסיים
- [ ] יצירת פתקים חדשים
- [ ] עריכת תוכן
- [ ] גרירת פתקים
- [ ] שינוי גודל
- [ ] מיזעור/הרחבה
- [ ] מחיקת פתקים

### שלב 4: אופטימיזציות
- [ ] Debouncing לשמירה
- [ ] LocalStorage caching
- [ ] Lazy loading לפתקים
- [ ] נעילה אופטימיסטית

### שלב 5: בדיקות ו-QA
- [ ] בדיקות יחידה
- [ ] בדיקות אינטגרציה
- [ ] בדיקות E2E
- [ ] בדיקות ביצועים
- [ ] בדיקות אבטחה

### שלב 6: תיעוד ושיפורים
- [ ] תיעוד למשתמש
- [ ] תיעוד למפתחים
- [ ] ביקורת קוד
- [ ] משוב משתמשים

---

## 🎯 סיכום

מדריך זה מספק תכנון מלא למימוש פיצ'ר הפתקים הדביקים. המימוש מתמקד ב:

1. **פשטות** - ממשק אינטואיטיבי ונקי
2. **ביצועים** - שמירה חכמה ו-caching
3. **אבטחה** - בידוד מלא בין משתמשים
4. **גמישות** - אפשרות להרחבה בעתיד

הפיצ'ר מוסיף ערך משמעותי למשתמשים המעוניינים להוסיף הערות אישיות למסמכי Markdown ללא עריכת הקבצים המקוריים, תוך שמירה על חוויית משתמש חלקה ואינטואיטיבית.