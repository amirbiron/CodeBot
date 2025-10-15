# מדריך מימוש פעולות מרובות (Multi-select) בקבצים

## 📋 סקירה כללית
מימוש מערכת בחירה מרובה בדף הקבצים שתאפשר למשתמשים לבחור כמה קבצים ולבצע פעולות קבוצתיות עליהם.

## 📦 קבצים שנוצרו במימוש

### Frontend (JavaScript)
- **`webapp/static/js/multi-select.js`** - מנהל לוגיקת הבחירה המרובה:
  - טיפול ב-checkboxes ובחירת קבצים
  - תמיכה ב-Shift+Click לבחירת טווח
  - קיצורי מקלדת (Ctrl+A לבחירת הכל, Escape לניקוי)
  - שמירה ושחזור בחירה בין עמודים (sessionStorage)
  
- **`webapp/static/js/bulk-actions.js`** - מנהל פעולות קבוצתיות:
  - הוספה/הסרה ממועדפים
  - הוספת תגיות מרובות
  - יצירת והורדת קובץ ZIP
  - מערכת התראות (notifications)
  - דיאלוגים מודאליים אינטראקטיביים

### Frontend (CSS)
- **`webapp/static/css/multi-select.css`** - עיצוב מלא למערכת:
  - עיצוב checkboxes עם אפקטי hover
  - סגנון לכרטיסי קבצים נבחרים
  - סרגל כלים הקשרי צף
  - אנימציות חלקות (fade, slide, pulse)
  - עיצוב התראות ודיאלוגים מודאליים
  - תמיכה רספונסיבית מלאה

### Backend (Python)
endpoints חדשים שיש להוסיף ל-**`webapp/app.py`**:

#### Endpoints בסיסיים (נדרשים):
- **`/api/files/bulk-favorite`** - הוספה קבוצתית למועדפים
- **`/api/files/bulk-unfavorite`** - הסרה קבוצתית ממועדפים
- **`/api/files/bulk-tag`** - הוספת תגיות לקבצים מרובים
- **`/api/files/create-zip`** - יצירת קובץ ZIP עם הקבצים הנבחרים

#### Endpoints אופציונליים (הרחבות):
- **`/api/files/bulk-delete`** - מחיקה קבוצתית של קבצים (זהירות!)
- **`/api/files/create-share-link`** - יצירת קישור שיתוף לקבצים נבחרים

## 🎯 יעדים
- **הוספת checkboxes** לכל כרטיס קובץ
- **סרגל כלים הקשרי** שמופיע כשיש קבצים נבחרים
- **פעולות קבוצתיות**: הוספה למועדפים, תיוג, הורדת ZIP
- **פעולות אופציונליות**: מחיקה קבוצתית (Delete key), שיתוף קבצים
- **חוויית משתמש נוחה** עם shortcuts ופידבק ברור

## 🏗️ ארכיטקטורה

### 1. מבנה הקבצים
```
webapp/
├── static/
│   ├── js/
│   │   ├── multi-select.js      # לוגיקה ראשית למערכת הבחירה
│   │   └── bulk-actions.js      # טיפול בפעולות קבוצתיות
│   └── css/
│       └── multi-select.css     # עיצוב checkbox וסרגל כלים
├── templates/
│   └── files.html               # עדכון תבנית הקבצים
└── app.py                       # API endpoints חדשים
```

### 2. זרימת נתונים
```
User Selection → JavaScript State → API Call → Backend Processing → UI Update
```

## 🔧 שלבי המימוש

### שלב 1: הוספת Checkboxes לכרטיסי קבצים

#### עדכון HTML (files.html)
```html
<!-- בכל כרטיס קובץ, הוסף checkbox -->
<div class="glass-card file-card" data-file-id="{{ file.id }}">
    <div class="file-selection">
        <input type="checkbox" 
               class="file-checkbox" 
               id="select-{{ file.id }}"
               data-file-id="{{ file.id }}"
               data-file-name="{{ file.file_name }}">
        <label for="select-{{ file.id }}"></label>
    </div>
    <!-- שאר תוכן הכרטיס... -->
</div>
```

#### עיצוב CSS (multi-select.css)
```css
.file-selection {
    position: absolute;
    top: 1rem;
    left: 1rem;
    z-index: 10;
    opacity: 0;
    transition: opacity 0.3s ease;
}

.file-card:hover .file-selection,
.file-selection.has-selection {
    opacity: 1;
}

.file-checkbox {
    width: 20px;
    height: 20px;
    cursor: pointer;
    accent-color: var(--primary);
}

.file-card.selected {
    background: rgba(102, 126, 234, 0.1);
    border: 2px solid var(--primary);
}
```

### שלב 2: סרגל כלים הקשרי

#### HTML של סרגל הכלים
```html
<div id="bulkActionsToolbar" class="bulk-actions-toolbar hidden">
    <div class="toolbar-content">
        <div class="selection-info">
            <span class="selected-count">0</span> קבצים נבחרים
        </div>
        
        <div class="toolbar-actions">
            <button class="btn btn-icon" onclick="bulkAddToFavorites()">
                <i class="fas fa-star"></i>
                הוסף למועדפים
            </button>
            
            <button class="btn btn-icon" onclick="showBulkTagDialog()">
                <i class="fas fa-tags"></i>
                הוסף תגיות
            </button>
            
            <button class="btn btn-icon" onclick="bulkDownloadZip()">
                <i class="fas fa-file-archive"></i>
                הורד כ-ZIP
            </button>
            
            <!-- אופציונלי: כפתור מחיקה -->
            <!--
            <button class="btn btn-danger btn-icon" onclick="bulkDelete()">
                <i class="fas fa-trash"></i>
                מחק
            </button>
            -->
            
            <button class="btn btn-secondary btn-icon" onclick="clearSelection()">
                <i class="fas fa-times"></i>
                ביטול בחירה
            </button>
        </div>
    </div>
</div>
```

#### עיצוב הסרגל
```css
.bulk-actions-toolbar {
    position: fixed;
    bottom: 2rem;
    left: 50%;
    transform: translateX(-50%);
    background: rgba(30, 30, 50, 0.98);
    backdrop-filter: blur(20px);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 15px;
    padding: 1rem 2rem;
    box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
    z-index: 1000;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.bulk-actions-toolbar.hidden {
    opacity: 0;
    visibility: hidden;
    transform: translateX(-50%) translateY(100px);
}

.bulk-actions-toolbar.visible {
    opacity: 1;
    visibility: visible;
    transform: translateX(-50%) translateY(0);
}

.toolbar-content {
    display: flex;
    align-items: center;
    gap: 2rem;
}

.selection-info {
    font-size: 1.1rem;
    font-weight: 600;
    color: var(--primary);
}

.toolbar-actions {
    display: flex;
    gap: 0.75rem;
}
```

### שלב 3: JavaScript - ניהול הבחירה

#### multi-select.js
```javascript
class MultiSelectManager {
    constructor() {
        this.selectedFiles = new Set();
        this.toolbar = document.getElementById('bulkActionsToolbar');
        this.init();
    }
    
    init() {
        // הגדרת event listeners
        this.setupCheckboxListeners();
        this.setupKeyboardShortcuts();
        this.setupSelectAllButton();
    }
    
    setupCheckboxListeners() {
        document.addEventListener('change', (e) => {
            if (e.target.classList.contains('file-checkbox')) {
                this.handleFileSelection(e.target);
            }
        });
    }
    
    handleFileSelection(checkbox) {
        const fileId = checkbox.dataset.fileId;
        const fileName = checkbox.dataset.fileName;
        const fileCard = checkbox.closest('.file-card');
        
        if (checkbox.checked) {
            this.selectedFiles.add({
                id: fileId,
                name: fileName
            });
            fileCard.classList.add('selected');
        } else {
            this.selectedFiles.delete(
                [...this.selectedFiles].find(f => f.id === fileId)
            );
            fileCard.classList.remove('selected');
        }
        
        this.updateToolbar();
        this.persistSelection();
    }
    
    updateToolbar() {
        const count = this.selectedFiles.size;
        const countElement = this.toolbar.querySelector('.selected-count');
        
        if (count > 0) {
            countElement.textContent = count;
            this.toolbar.classList.remove('hidden');
            this.toolbar.classList.add('visible');
            
            // הוסף class לכל checkboxes להשאירם גלויים
            document.querySelectorAll('.file-selection').forEach(el => {
                el.classList.add('has-selection');
            });
        } else {
            this.toolbar.classList.remove('visible');
            this.toolbar.classList.add('hidden');
            
            // הסר class מכל checkboxes
            document.querySelectorAll('.file-selection').forEach(el => {
                el.classList.remove('has-selection');
            });
        }
    }
    
    setupKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            // Ctrl+A - בחר הכל
            if (e.ctrlKey && e.key === 'a' && !e.shiftKey) {
                e.preventDefault();
                this.selectAll();
            }
            
            // Escape - נקה בחירה
            if (e.key === 'Escape') {
                this.clearSelection();
            }
            
            // Shift+Click - בחירת טווח
            if (e.shiftKey && e.type === 'click') {
                this.handleRangeSelection(e.target);
            }
        });
    }
    
    selectAll() {
        document.querySelectorAll('.file-checkbox').forEach(checkbox => {
            if (!checkbox.checked) {
                checkbox.checked = true;
                this.handleFileSelection(checkbox);
            }
        });
    }
    
    clearSelection() {
        document.querySelectorAll('.file-checkbox:checked').forEach(checkbox => {
            checkbox.checked = false;
            this.handleFileSelection(checkbox);
        });
    }
    
    persistSelection() {
        // שמור בחירה ב-sessionStorage לשמירה בין עמודים
        const fileIds = [...this.selectedFiles].map(f => f.id);
        sessionStorage.setItem('selectedFiles', JSON.stringify(fileIds));
    }
    
    restoreSelection() {
        // שחזר בחירה אחרי מעבר עמוד
        const stored = sessionStorage.getItem('selectedFiles');
        if (stored) {
            const fileIds = JSON.parse(stored);
            fileIds.forEach(id => {
                const checkbox = document.querySelector(`[data-file-id="${id}"]`);
                if (checkbox) {
                    checkbox.checked = true;
                    this.handleFileSelection(checkbox);
                }
            });
        }
    }
}

// אתחול המערכת
document.addEventListener('DOMContentLoaded', () => {
    window.multiSelect = new MultiSelectManager();
    window.multiSelect.restoreSelection();
});
```

### שלב 4: פעולות קבוצתיות

#### bulk-actions.js
```javascript
class BulkActions {
    constructor() {
        this.processingOverlay = this.createProcessingOverlay();
    }
    
    createProcessingOverlay() {
        const overlay = document.createElement('div');
        overlay.className = 'processing-overlay hidden';
        overlay.innerHTML = `
            <div class="processing-content">
                <div class="spinner"></div>
                <div class="processing-text">מעבד...</div>
            </div>
        `;
        document.body.appendChild(overlay);
        return overlay;
    }
    
    showProcessing(text = 'מעבד...') {
        this.processingOverlay.querySelector('.processing-text').textContent = text;
        this.processingOverlay.classList.remove('hidden');
    }
    
    hideProcessing() {
        this.processingOverlay.classList.add('hidden');
    }
    
    async addToFavorites() {
        const fileIds = [...window.multiSelect.selectedFiles].map(f => f.id);
        
        if (fileIds.length === 0) {
            this.showNotification('לא נבחרו קבצים', 'warning');
            return;
        }
        
        this.showProcessing(`מוסיף ${fileIds.length} קבצים למועדפים...`);
        
        try {
            const response = await fetch('/api/files/bulk-favorite', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ file_ids: fileIds })
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.showNotification(`${result.updated} קבצים נוספו למועדפים`, 'success');
                window.multiSelect.clearSelection();
                
                // עדכן UI - הוסף כוכב למועדפים
                fileIds.forEach(id => {
                    const card = document.querySelector(`[data-file-id="${id}"]`);
                    if (card) {
                        card.classList.add('is-favorite');
                    }
                });
            } else {
                throw new Error(result.error || 'שגיאה בהוספה למועדפים');
            }
        } catch (error) {
            console.error('Error adding to favorites:', error);
            this.showNotification('שגיאה בהוספה למועדפים', 'error');
        } finally {
            this.hideProcessing();
        }
    }
    
    async addTags() {
        const fileIds = [...window.multiSelect.selectedFiles].map(f => f.id);
        
        if (fileIds.length === 0) {
            this.showNotification('לא נבחרו קבצים', 'warning');
            return;
        }
        
        // הצג דיאלוג להזנת תגיות
        const tags = await this.showTagDialog();
        if (!tags) return;
        
        this.showProcessing(`מוסיף תגיות ל-${fileIds.length} קבצים...`);
        
        try {
            const response = await fetch('/api/files/bulk-tag', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ 
                    file_ids: fileIds,
                    tags: tags
                })
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.showNotification(`תגיות נוספו ל-${result.updated} קבצים`, 'success');
                window.multiSelect.clearSelection();
                
                // רענן את העמוד או עדכן את התגיות בUI
                if (result.updated > 0) {
                    setTimeout(() => location.reload(), 1500);
                }
            }
        } catch (error) {
            console.error('Error adding tags:', error);
            this.showNotification('שגיאה בהוספת תגיות', 'error');
        } finally {
            this.hideProcessing();
        }
    }
    
    async downloadZip() {
        const fileIds = [...window.multiSelect.selectedFiles].map(f => f.id);
        
        if (fileIds.length === 0) {
            this.showNotification('לא נבחרו קבצים', 'warning');
            return;
        }
        
        this.showProcessing(`יוצר ZIP עם ${fileIds.length} קבצים...`);
        
        try {
            const response = await fetch('/api/files/create-zip', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ file_ids: fileIds })
            });
            
            if (!response.ok) {
                throw new Error('Failed to create ZIP');
            }
            
            // קבל את ה-blob
            const blob = await response.blob();
            
            // יצירת לינק להורדה
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.style.display = 'none';
            a.href = url;
            a.download = `code_files_${new Date().getTime()}.zip`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            
            this.showNotification('הקובץ הורד בהצלחה', 'success');
            window.multiSelect.clearSelection();
            
        } catch (error) {
            console.error('Error downloading ZIP:', error);
            this.showNotification('שגיאה ביצירת קובץ ZIP', 'error');
        } finally {
            this.hideProcessing();
        }
    }
    
    async showTagDialog() {
        return new Promise((resolve) => {
            const dialog = document.createElement('div');
            dialog.className = 'modal-overlay';
            dialog.innerHTML = `
                <div class="modal-content">
                    <h3>הוסף תגיות</h3>
                    <p>הזן תגיות מופרדות בפסיקים:</p>
                    <input type="text" 
                           id="tagInput" 
                           class="tag-input" 
                           placeholder="למשל: python, utils, important"
                           autofocus>
                    <div class="modal-actions">
                        <button class="btn btn-primary" onclick="confirmTags()">
                            <i class="fas fa-check"></i> אישור
                        </button>
                        <button class="btn btn-secondary" onclick="cancelTags()">
                            <i class="fas fa-times"></i> ביטול
                        </button>
                    </div>
                </div>
            `;
            
            window.confirmTags = () => {
                const input = document.getElementById('tagInput');
                const tags = input.value
                    .split(',')
                    .map(t => t.trim())
                    .filter(t => t.length > 0);
                document.body.removeChild(dialog);
                resolve(tags);
            };
            
            window.cancelTags = () => {
                document.body.removeChild(dialog);
                resolve(null);
            };
            
            document.body.appendChild(dialog);
            document.getElementById('tagInput').focus();
            
            // Enter לאישור
            document.getElementById('tagInput').addEventListener('keyup', (e) => {
                if (e.key === 'Enter') {
                    window.confirmTags();
                }
            });
        });
    }
    
    showNotification(message, type = 'info') {
        const notification = document.createElement('div');
        notification.className = `notification ${type}`;
        notification.innerHTML = `
            <div class="notification-content">
                <i class="fas fa-${type === 'success' ? 'check-circle' : 
                                   type === 'error' ? 'exclamation-circle' : 
                                   type === 'warning' ? 'exclamation-triangle' : 
                                   'info-circle'}"></i>
                <span>${message}</span>
            </div>
        `;
        
        document.body.appendChild(notification);
        
        // אנימציית כניסה
        setTimeout(() => notification.classList.add('show'), 100);
        
        // הסרה אוטומטית
        setTimeout(() => {
            notification.classList.remove('show');
            setTimeout(() => document.body.removeChild(notification), 300);
        }, 3000);
    }
}

// יצירת instance גלובלי
window.bulkActions = new BulkActions();

// חיבור לכפתורים
window.bulkAddToFavorites = () => window.bulkActions.addToFavorites();
window.showBulkTagDialog = () => window.bulkActions.addTags();
window.bulkDownloadZip = () => window.bulkActions.downloadZip();
window.clearSelection = () => window.multiSelect.clearSelection();
```

### שלב 5: Backend API Endpoints

#### app.py - הוספת endpoints
```python
@app.route('/api/files/bulk-favorite', methods=['POST'])
@login_required
def bulk_add_to_favorites():
    """הוסף קבצים מרובים למועדפים"""
    try:
        data = request.json
        file_ids = data.get('file_ids', [])
        
        if not file_ids:
            return jsonify({'success': False, 'error': 'No files selected'}), 400
        
        db = get_db()
        user_id = session['user_id']
        
        # המר string IDs ל-ObjectIds
        object_ids = [ObjectId(fid) for fid in file_ids]
        
        # עדכן את כל הקבצים
        result = db.code_snippets.update_many(
            {
                '_id': {'$in': object_ids},
                'user_id': user_id
            },
            {
                '$addToSet': {'tags': 'favorite'},
                '$set': {'is_favorite': True}
            }
        )
        
        return jsonify({
            'success': True,
            'updated': result.modified_count
        })
        
    except Exception as e:
        app.logger.error(f"Error in bulk favorite: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/files/bulk-unfavorite', methods=['POST'])
@login_required
def bulk_remove_from_favorites():
    """הסר קבצים מרובים ממועדפים"""
    try:
        data = request.json
        file_ids = data.get('file_ids', [])
        
        if not file_ids:
            return jsonify({'success': False, 'error': 'No files selected'}), 400
        
        db = get_db()
        user_id = session['user_id']
        
        # המר string IDs ל-ObjectIds
        object_ids = [ObjectId(fid) for fid in file_ids]
        
        # הסר מהמועדפים
        result = db.code_snippets.update_many(
            {
                '_id': {'$in': object_ids},
                'user_id': user_id
            },
            {
                '$pull': {'tags': 'favorite'},
                '$set': {'is_favorite': False}
            }
        )
        
        return jsonify({
            'success': True,
            'updated': result.modified_count
        })
        
    except Exception as e:
        app.logger.error(f"Error removing from favorites: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/files/bulk-tag', methods=['POST'])
@login_required
def bulk_add_tags():
    """הוסף תגיות לקבצים מרובים"""
    try:
        data = request.json
        file_ids = data.get('file_ids', [])
        tags = data.get('tags', [])
        
        if not file_ids or not tags:
            return jsonify({'success': False, 'error': 'Missing data'}), 400
        
        db = get_db()
        user_id = session['user_id']
        
        object_ids = [ObjectId(fid) for fid in file_ids]
        
        # עדכן תגיות
        result = db.code_snippets.update_many(
            {
                '_id': {'$in': object_ids},
                'user_id': user_id
            },
            {
                '$addToSet': {'tags': {'$each': tags}}
            }
        )
        
        return jsonify({
            'success': True,
            'updated': result.modified_count
        })
        
    except Exception as e:
        app.logger.error(f"Error in bulk tag: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

### Endpoints אופציונליים (לא חובה):

@app.route('/api/files/bulk-delete', methods=['POST'])
@login_required
def bulk_delete_files():
    """מחיקה קבוצתית של קבצים - אופציונלי, השתמש בזהירות!"""
    try:
        data = request.json
        file_ids = data.get('file_ids', [])
        
        if not file_ids:
            return jsonify({'success': False, 'error': 'No files selected'}), 400
        
        db = get_db()
        user_id = session['user_id']
        
        # המר string IDs ל-ObjectIds
        object_ids = [ObjectId(fid) for fid in file_ids]
        
        # מחק את הקבצים (רק של המשתמש הנוכחי)
        result = db.code_snippets.delete_many({
            '_id': {'$in': object_ids},
            'user_id': user_id
        })
        
        return jsonify({
            'success': True,
            'deleted': result.deleted_count
        })
        
    except Exception as e:
        app.logger.error(f"Error in bulk delete: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/files/create-zip', methods=['POST'])
@login_required
def create_zip_file():
    """יצירת קובץ ZIP עם קבצים נבחרים"""
    try:
        import zipfile
        import tempfile
        from io import BytesIO
        
        data = request.json
        file_ids = data.get('file_ids', [])
        
        if not file_ids:
            return jsonify({'success': False, 'error': 'No files selected'}), 400
        
        db = get_db()
        user_id = session['user_id']
        
        object_ids = [ObjectId(fid) for fid in file_ids]
        
        # שלוף את הקבצים
        files = db.code_snippets.find({
            '_id': {'$in': object_ids},
            'user_id': user_id
        })
        
        # יצירת ZIP בזיכרון
        zip_buffer = BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for file in files:
                # שם קובץ ייחודי
                filename = file.get('file_name', f"file_{file['_id']}.txt")
                content = file.get('code', '')
                
                # הוסף לZIP
                zip_file.writestr(filename, content)
        
        # החזר את הקובץ
        zip_buffer.seek(0)
        
        return send_file(
            zip_buffer,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f'code_files_{int(time.time())}.zip'
        )
        
    except Exception as e:
        app.logger.error(f"Error creating ZIP: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/files/create-share-link', methods=['POST'])
@login_required
def create_share_link():
    """יצירת קישור שיתוף לקבצים נבחרים"""
    try:
        import secrets
        from datetime import datetime, timedelta
        
        data = request.json
        file_ids = data.get('file_ids', [])
        
        if not file_ids:
            return jsonify({'success': False, 'error': 'No files selected'}), 400
        
        db = get_db()
        user_id = session['user_id']
        
        # המר string IDs ל-ObjectIds
        object_ids = [ObjectId(fid) for fid in file_ids]
        
        # וודא שהקבצים שייכים למשתמש
        files_count = db.code_snippets.count_documents({
            '_id': {'$in': object_ids},
            'user_id': user_id
        })
        
        if files_count != len(file_ids):
            return jsonify({'success': False, 'error': 'Some files not found'}), 404
        
        # יצירת token ייחודי לשיתוף
        share_token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(days=7)  # תוקף ל-7 ימים
        
        # שמירת השיתוף במסד הנתונים
        share_doc = {
            'token': share_token,
            'file_ids': object_ids,
            'user_id': user_id,
            'created_at': datetime.utcnow(),
            'expires_at': expires_at,
            'view_count': 0
        }
        
        db.share_links.insert_one(share_doc)
        
        # יצירת URL לשיתוף
        base_url = os.getenv('WEBAPP_URL', request.host_url.rstrip('/'))
        share_url = f"{base_url}/shared/{share_token}"
        
        return jsonify({
            'success': True,
            'share_url': share_url,
            'expires_at': expires_at.isoformat(),
            'token': share_token
        })
        
    except Exception as e:
        app.logger.error(f"Error creating share link: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
```

### שלב 6: עיצוב נוסף

#### CSS לאנימציות ו-hover effects
```css
/* אנימציות */
@keyframes slideUp {
    from {
        transform: translateX(-50%) translateY(100px);
        opacity: 0;
    }
    to {
        transform: translateX(-50%) translateY(0);
        opacity: 1;
    }
}

@keyframes pulse {
    0% { transform: scale(1); }
    50% { transform: scale(1.05); }
    100% { transform: scale(1); }
}

/* Processing overlay */
.processing-overlay {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.7);
    backdrop-filter: blur(5px);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 10000;
    transition: opacity 0.3s ease;
}

.processing-overlay.hidden {
    opacity: 0;
    visibility: hidden;
}

.processing-content {
    background: rgba(30, 30, 50, 0.95);
    padding: 2rem;
    border-radius: 15px;
    text-align: center;
}

.spinner {
    width: 40px;
    height: 40px;
    margin: 0 auto 1rem;
    border: 3px solid rgba(255, 255, 255, 0.2);
    border-top-color: var(--primary);
    border-radius: 50%;
    animation: spin 1s linear infinite;
}

@keyframes spin {
    to { transform: rotate(360deg); }
}

/* Notifications */
.notification {
    position: fixed;
    top: 2rem;
    right: 2rem;
    background: rgba(30, 30, 50, 0.95);
    padding: 1rem 1.5rem;
    border-radius: 10px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
    z-index: 10001;
    transform: translateX(400px);
    transition: transform 0.3s ease;
}

.notification.show {
    transform: translateX(0);
}

.notification.success {
    border-left: 4px solid #4caf50;
}

.notification.error {
    border-left: 4px solid #f44336;
}

.notification.warning {
    border-left: 4px solid #ff9800;
}

.notification-content {
    display: flex;
    align-items: center;
    gap: 1rem;
}

/* Modal dialog */
.modal-overlay {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.7);
    backdrop-filter: blur(5px);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 10000;
    animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
}

.modal-content {
    background: rgba(30, 30, 50, 0.98);
    padding: 2rem;
    border-radius: 15px;
    width: 90%;
    max-width: 400px;
    box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
    animation: slideUp 0.3s ease;
}

.modal-content h3 {
    margin: 0 0 1rem;
    color: var(--primary);
}

.tag-input {
    width: 100%;
    padding: 0.75rem;
    margin: 1rem 0;
    border: 1px solid rgba(255, 255, 255, 0.2);
    background: rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    color: white;
    font-size: 1rem;
}

.modal-actions {
    display: flex;
    gap: 1rem;
    justify-content: flex-end;
    margin-top: 1.5rem;
}

/* Responsive */
@media (max-width: 768px) {
    .bulk-actions-toolbar {
        left: 1rem;
        right: 1rem;
        bottom: 1rem;
        transform: none;
    }
    
    .bulk-actions-toolbar.hidden {
        transform: translateY(150px);
    }
    
    .bulk-actions-toolbar.visible {
        transform: translateY(0);
    }
    
    .toolbar-content {
        flex-direction: column;
        gap: 1rem;
        text-align: center;
    }
    
    .toolbar-actions {
        width: 100%;
        justify-content: center;
    }
}
```

## 🔌 אינטגרציה

### הוספת הסקריפטים לדף
```html
<!-- בתחתית files.html -->
<script src="{{ url_for('static', filename='js/multi-select.js') }}"></script>
<script src="{{ url_for('static', filename='js/bulk-actions.js') }}"></script>
<link rel="stylesheet" href="{{ url_for('static', filename='css/multi-select.css') }}">
```

## ✅ בדיקות

### רשימת בדיקות למימוש:
- [ ] Checkboxes מופיעים ב-hover
- [ ] בחירת קובץ בודד עובדת
- [ ] בחירת מרובה עובדת
- [ ] סרגל כלים מופיע/נעלם כראוי
- [ ] ספירת קבצים נכונה
- [ ] Ctrl+A בוחר הכל
- [ ] Escape מנקה בחירה
- [ ] הוספה למועדפים עובדת
- [ ] הוספת תגיות עובדת
- [ ] הורדת ZIP עובדת
- [ ] Notifications מוצגות כראוי
- [ ] בחירה נשמרת בין עמודים
- [ ] עיצוב רספונסיבי במובייל
- [ ] אין שגיאות בקונסול
- [ ] ביצועים טובים עם הרבה קבצים

## 🚀 שיפורים עתידיים

### רעיונות להרחבה:
1. **פעולות נוספות**: מחיקה, העברה לתיקיה, שיתוף
2. **פילטר חכם**: הצג רק קבצים לא מתויגים
3. **Undo**: אפשרות לביטול פעולה אחרונה
4. **Drag & Drop**: גרירת קבצים לתיקיות
5. **קיצורי מקלדת נוספים**: 1-9 לבחירה מהירה
6. **ייצוא לפורמטים נוספים**: PDF, Markdown
7. **עיבוד אצווה**: שינוי שם לכמה קבצים
8. **השוואת קבצים**: diff בין קבצים נבחרים

## 📝 הערות

- יש להקפיד על **אבטחה** - לוודא שהמשתמש יכול לפעול רק על הקבצים שלו
- **ביצועים** - להימנע מעיבוד יותר מ-100 קבצים בבת אחת
- **נגישות** - לוודא תמיכה בקוראי מסך ומקלדת בלבד
- **גיבוי** - מומלץ להוסיף אישור לפעולות הרסניות

## 🔗 קישורים רלוונטיים

- [Issue #747](https://github.com/amirbiron/CodeBot/issues/747#issue-3514977475) - הדרישה המקורית
- [Flask Documentation](https://flask.palletsprojects.com/)
- [MongoDB Bulk Operations](https://docs.mongodb.com/manual/core/bulk-write-operations/)