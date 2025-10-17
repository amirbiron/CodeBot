# 🔖 מדריך מימוש: סימניות בתוך קבצים ב-WebApp

## 📋 סקירה כללית

מדריך זה מתאר כיצד להוסיף פיצ'ר סימניות (bookmarks) לשורות ספציפיות בתוך קבצים ב-WebApp של CodeBot. הפיצ'ר מאפשר למשתמשים לסמן שורות חשובות בקוד לגישה מהירה.

## 🎯 יעדי הפיצ'ר

1. **סימון שורות**: לחיצה על שורת קוד תוסיף/תסיר סימנייה
2. **ניווט מהיר**: קפיצה מהירה בין הסימניות בקובץ
3. **הערות**: הוספת הערה לכל סימנייה (אופציונלי)
4. **פאנל צד**: רשימת כל הסימניות בקובץ הנוכחי
5. **שמירה**: שמירת סימניות ב-DB לפי משתמש וקובץ

---

## 🗄️ שכבת Database

### 1. מודל נתונים חדש

צור קולקשן חדשה `file_bookmarks` ב-MongoDB:

```python
# database/models.py - הוסף מחלקה חדשה

from dataclasses import dataclass
from typing import Optional

@dataclass
class FileBookmark:
    """סימנייה לשורה בקובץ"""
    user_id: int
    file_id: str  # ObjectId של הקובץ
    file_name: str  # שם הקובץ לצורך חיפוש
    line_number: int  # מספר השורה (1-based)
    note: str = ""  # הערה אופציונלית
    created_at: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)
```

### 2. פונקציות Database

הוסף ל-`database/manager.py` או צור `database/bookmarks_manager.py`:

```python
class BookmarksManager:
    """מנהל סימניות בקבצים"""
    
    def __init__(self, db):
        self.collection = db.file_bookmarks
        self._ensure_indexes()
    
    def _ensure_indexes(self):
        """יצירת אינדקסים למהירות"""
        try:
            # אינדקס ייחודי למשתמש+קובץ+שורה (מונע כפילויות)
            self.collection.create_index([
                ("user_id", 1),
                ("file_id", 1),
                ("line_number", 1)
            ], unique=True, name="user_file_line_unique")
            
            # אינדקס לחיפוש מהיר לפי קובץ (ללא line_number)
            self.collection.create_index([
                ("user_id", 1),
                ("file_id", 1)
            ], name="user_file_idx")
        except Exception as e:
            logger.warning(f"Failed to create bookmarks indexes: {e}")
    
    def toggle_bookmark(self, user_id: int, file_id: str, file_name: str, 
                       line_number: int, note: str = "") -> dict:
        """
        הוספה/הסרה של סימנייה
        
        Returns:
            dict עם המפתחות: added (bool), bookmark (dict או None)
        """
        try:
            # בדיקה אם כבר קיימת
            existing = self.collection.find_one({
                "user_id": user_id,
                "file_id": file_id,
                "line_number": line_number
            })
            
            if existing:
                # הסרת סימנייה קיימת
                self.collection.delete_one({"_id": existing["_id"]})
                return {"added": False, "bookmark": None}
            else:
                # הוספת סימנייה חדשה
                bookmark = {
                    "user_id": user_id,
                    "file_id": file_id,
                    "file_name": file_name,
                    "line_number": line_number,
                    "note": note,
                    "created_at": datetime.now(timezone.utc)
                }
                result = self.collection.insert_one(bookmark)
                bookmark["_id"] = result.inserted_id
                return {"added": True, "bookmark": bookmark}
        
        except Exception as e:
            logger.error(f"Error toggling bookmark: {e}")
            return {"added": False, "bookmark": None}
    
    def get_file_bookmarks(self, user_id: int, file_id: str) -> list:
        """קבלת כל הסימניות של קובץ, ממוינות לפי מספר שורה"""
        try:
            bookmarks = list(self.collection.find({
                "user_id": user_id,
                "file_id": file_id
            }).sort("line_number", 1))
            return bookmarks
        except Exception as e:
            logger.error(f"Error getting bookmarks: {e}")
            return []
    
    def update_bookmark_note(self, user_id: int, file_id: str, 
                            line_number: int, note: str) -> bool:
        """עדכון הערה לסימנייה קיימת"""
        try:
            result = self.collection.update_one(
                {
                    "user_id": user_id,
                    "file_id": file_id,
                    "line_number": line_number
                },
                {"$set": {"note": note}}
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Error updating bookmark note: {e}")
            return False
    
    def delete_bookmark(self, user_id: int, file_id: str, line_number: int) -> bool:
        """מחיקת סימנייה"""
        try:
            result = self.collection.delete_one({
                "user_id": user_id,
                "file_id": file_id,
                "line_number": line_number
            })
            return result.deleted_count > 0
        except Exception as e:
            logger.error(f"Error deleting bookmark: {e}")
            return False
    
    def get_all_user_bookmarks(self, user_id: int, limit: int = 100) -> list:
        """קבלת כל הסימניות של משתמש (לכל הקבצים)"""
        try:
            bookmarks = list(self.collection.find({
                "user_id": user_id
            }).sort("created_at", -1).limit(limit))
            return bookmarks
        except Exception as e:
            logger.error(f"Error getting user bookmarks: {e}")
            return []
```

---

## 🎨 ממשק משתמש (Frontend)

### 1. עדכון תבנית view_file.html

הוסף סגנונות CSS לסימניות:

```html
<!-- webapp/templates/view_file.html - הוסף ל-<style> -->

/* סימנייה בשורת קוד */
.bookmark-indicator {
    position: absolute;
    right: 5px;
    top: 50%;
    transform: translateY(-50%);
    font-size: 1.2rem;
    color: #ffd700;
    cursor: pointer;
    opacity: 0;
    transition: opacity 0.2s;
}

.linenos:hover .bookmark-indicator,
.bookmark-indicator.active {
    opacity: 1;
}

.bookmark-indicator.active {
    opacity: 1 !important;
}

/* שורה מסומנת */
.code-line.bookmarked {
    background: rgba(255, 215, 0, 0.1) !important;
    border-right: 3px solid #ffd700;
}

/* פאנל סימניות צד */
.bookmarks-panel {
    position: fixed;
    left: 0;
    top: 80px;
    bottom: 0;
    width: 320px;
    background: linear-gradient(135deg, #1a2332 0%, #2d3e50 100%);
    border-left: 1px solid rgba(255, 255, 255, 0.1);
    transform: translateX(-100%);
    transition: transform 0.3s ease;
    z-index: 1000;
    overflow-y: auto;
    box-shadow: 2px 0 10px rgba(0, 0, 0, 0.3);
}

.bookmarks-panel.open {
    transform: translateX(0);
}

.bookmarks-panel-header {
    padding: 1.5rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: rgba(0, 0, 0, 0.2);
}

.bookmarks-panel-title {
    font-size: 1.2rem;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.bookmarks-list {
    padding: 1rem;
}

.bookmark-item {
    background: rgba(255, 255, 255, 0.05);
    border-radius: 8px;
    padding: 1rem;
    margin-bottom: 0.75rem;
    cursor: pointer;
    transition: all 0.2s;
    border-right: 3px solid #ffd700;
}

.bookmark-item:hover {
    background: rgba(255, 255, 255, 0.1);
    transform: translateX(-3px);
}

.bookmark-line {
    font-size: 0.9rem;
    color: #ffd700;
    font-weight: 600;
    margin-bottom: 0.5rem;
}

.bookmark-code-preview {
    font-family: 'Fira Code', monospace;
    font-size: 0.85rem;
    color: rgba(255, 255, 255, 0.8);
    background: rgba(0, 0, 0, 0.3);
    padding: 0.5rem;
    border-radius: 4px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    direction: ltr;
    text-align: left;
}

.bookmark-note {
    font-size: 0.85rem;
    color: rgba(255, 255, 255, 0.7);
    margin-top: 0.5rem;
    font-style: italic;
}

.bookmark-actions {
    display: flex;
    gap: 0.5rem;
    margin-top: 0.75rem;
}

.bookmark-actions button {
    padding: 0.3rem 0.6rem;
    font-size: 0.8rem;
    background: rgba(255, 255, 255, 0.1);
    border: 1px solid rgba(255, 255, 255, 0.2);
    border-radius: 4px;
    color: white;
    cursor: pointer;
    transition: all 0.2s;
}

.bookmark-actions button:hover {
    background: rgba(255, 255, 255, 0.2);
}

/* כפתור פתיחת פאנל */
.toggle-bookmarks-btn {
    position: fixed;
    left: 0;
    top: 50%;
    transform: translateY(-50%);
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    border: none;
    padding: 0.8rem 0.4rem;
    cursor: pointer;
    border-radius: 0 8px 8px 0;
    font-size: 1.1rem;
    z-index: 999;
    transition: all 0.3s;
    box-shadow: 2px 0 8px rgba(0, 0, 0, 0.3);
}

.toggle-bookmarks-btn:hover {
    padding-left: 0.8rem;
}

.toggle-bookmarks-btn .bookmark-count {
    display: block;
    font-size: 0.75rem;
    margin-top: 0.2rem;
    opacity: 0.9;
}

/* מודל הערה */
.bookmark-note-modal {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.7);
    display: none;
    align-items: center;
    justify-content: center;
    z-index: 2000;
}

.bookmark-note-modal.show {
    display: flex;
}

.bookmark-note-modal-content {
    background: linear-gradient(135deg, #2d4a7c 0%, #3d5a8c 100%);
    padding: 2rem;
    border-radius: 12px;
    max-width: 500px;
    width: 90%;
    box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
}

.bookmark-note-modal h3 {
    margin-top: 0;
    margin-bottom: 1.5rem;
    color: #ffd700;
}

.bookmark-note-modal textarea {
    width: 100%;
    min-height: 100px;
    background: rgba(255, 255, 255, 0.1);
    border: 1px solid rgba(255, 255, 255, 0.2);
    border-radius: 8px;
    padding: 0.8rem;
    color: white;
    font-family: inherit;
    resize: vertical;
    margin-bottom: 1rem;
}

.bookmark-note-modal-actions {
    display: flex;
    gap: 0.75rem;
    justify-content: flex-end;
}

/* שורות ניתנות לסימון */
.highlighttable .linenos pre > span,
.linenodiv pre > span {
    position: relative;
    display: block;
    padding-left: 1.5rem;
    cursor: pointer;
    transition: background 0.2s;
}

.highlighttable .linenos pre > span:hover,
.linenodiv pre > span:hover {
    background: rgba(255, 255, 255, 0.05);
}
```

### 2. הוספת HTML של הפאנל

הוסף לתבנית `view_file.html` לפני `{% endblock %}`:

```html
<!-- פאנל סימניות -->
<div class="bookmarks-panel" id="bookmarksPanel">
    <div class="bookmarks-panel-header">
        <div class="bookmarks-panel-title">
            🔖 סימניות
        </div>
        <button onclick="toggleBookmarksPanel()" class="btn btn-secondary btn-icon" style="padding: 0.5rem;">
            ✕
        </button>
    </div>
    <div class="bookmarks-list" id="bookmarksList">
        <p style="text-align: center; opacity: 0.6; padding: 2rem;">
            אין סימניות בקובץ זה
        </p>
    </div>
</div>

<!-- כפתור פתיחת פאנל -->
<button class="toggle-bookmarks-btn" id="toggleBookmarksBtn" onclick="toggleBookmarksPanel()">
    🔖
    <span class="bookmark-count" id="bookmarkCount">0</span>
</button>

<!-- מודל הוספת הערה -->
<div class="bookmark-note-modal" id="bookmarkNoteModal">
    <div class="bookmark-note-modal-content">
        <h3>✏️ הערה לסימנייה</h3>
        <textarea id="bookmarkNoteInput" placeholder="הוסף הערה (אופציונלי)..."></textarea>
        <div class="bookmark-note-modal-actions">
            <button onclick="closeNoteModal()" class="btn btn-secondary">ביטול</button>
            <button onclick="saveBookmarkNote()" class="btn btn-primary">שמור</button>
        </div>
    </div>
</div>
```

### 3. JavaScript לניהול סימניות

הוסף בסוף `view_file.html`:

```javascript
<script>
// ניהול סימניות
(function() {
    const fileId = '{{ file.id }}';
    let bookmarks = [];
    let currentEditingBookmark = null;
    let isEditingExistingBookmark = false;  // האם עורכים סימנייה קיימת או יוצרים חדשה
    
    // טעינת סימניות בעת טעינת הדף
    async function loadBookmarks() {
        try {
            const response = await fetch(`/api/bookmarks/${fileId}`);
            const data = await response.json();
            if (data.ok) {
                bookmarks = data.bookmarks || [];
                renderBookmarks();
                updateBookmarkIndicators();
                updateBookmarkCount();
            }
        } catch (error) {
            console.error('Error loading bookmarks:', error);
        }
    }
    
    // הוספת/הסרת סימנייה
    async function toggleBookmark(lineNumber, note = '') {
        try {
            const response = await fetch(`/api/bookmarks/${fileId}/toggle`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ line_number: lineNumber, note: note })
            });
            
            const data = await response.json();
            if (data.ok) {
                await loadBookmarks();
                
                // הודעת הצלחה
                const action = data.added ? 'נוספה' : 'הוסרה';
                showNotification(`סימנייה ${action} בשורה ${lineNumber}`);
            }
        } catch (error) {
            console.error('Error toggling bookmark:', error);
            showNotification('שגיאה בשמירת סימנייה', 'error');
        }
    }
    
    // רינדור רשימת סימניות
    function renderBookmarks() {
        const listEl = document.getElementById('bookmarksList');
        
        if (bookmarks.length === 0) {
            listEl.innerHTML = '<p style="text-align: center; opacity: 0.6; padding: 2rem;">אין סימניות בקובץ זה</p>';
            return;
        }
        
        // ניקוי רשימה קיימת
        listEl.innerHTML = '';
        
        // יצירת אלמנטים באופן דינמי (בטוח יותר מ-innerHTML)
        bookmarks.forEach(bookmark => {
            const lineText = getLineText(bookmark.line_number);
            
            // יצירת מיכל הסימנייה
            const itemDiv = document.createElement('div');
            itemDiv.className = 'bookmark-item';
            itemDiv.onclick = () => scrollToLine(bookmark.line_number);
            
            // שורה
            const lineDiv = document.createElement('div');
            lineDiv.className = 'bookmark-line';
            lineDiv.textContent = `שורה ${bookmark.line_number}`;
            itemDiv.appendChild(lineDiv);
            
            // תצוגת הקוד
            const previewDiv = document.createElement('div');
            previewDiv.className = 'bookmark-code-preview';
            previewDiv.textContent = lineText;
            itemDiv.appendChild(previewDiv);
            
            // הערה (אם קיימת)
            if (bookmark.note) {
                const noteDiv = document.createElement('div');
                noteDiv.className = 'bookmark-note';
                noteDiv.textContent = `📝 ${bookmark.note}`;
                itemDiv.appendChild(noteDiv);
            }
            
            // כפתורי פעולה
            const actionsDiv = document.createElement('div');
            actionsDiv.className = 'bookmark-actions';
            
            // כפתור עריכה
            const editBtn = document.createElement('button');
            editBtn.textContent = '✏️ ערוך הערה';
            editBtn.onclick = (e) => {
                e.stopPropagation();
                editBookmarkNote(bookmark.line_number, bookmark.note || '');
            };
            actionsDiv.appendChild(editBtn);
            
            // כפתור מחיקה
            const deleteBtn = document.createElement('button');
            deleteBtn.textContent = '🗑️ מחק';
            deleteBtn.onclick = (e) => {
                e.stopPropagation();
                deleteBookmark(bookmark.line_number);
            };
            actionsDiv.appendChild(deleteBtn);
            
            itemDiv.appendChild(actionsDiv);
            listEl.appendChild(itemDiv);
        });
    }
    
    // עדכון אינדיקטורים בשורות הקוד
    function updateBookmarkIndicators() {
        // הסרת כל האינדיקטורים הקיימים
        document.querySelectorAll('.bookmark-indicator').forEach(el => el.remove());
        document.querySelectorAll('.bookmarked').forEach(el => el.classList.remove('bookmarked'));
        
        // הוספת אינדיקטורים לשורות מסומנות
        bookmarks.forEach(bookmark => {
            const lineEl = getLineElement(bookmark.line_number);
            if (lineEl) {
                lineEl.classList.add('bookmarked');
                
                // הוספת אייקון סימנייה
                const indicator = document.createElement('span');
                indicator.className = 'bookmark-indicator active';
                indicator.innerHTML = '🔖';
                indicator.title = bookmark.note || 'סימנייה';
                indicator.onclick = (e) => {
                    e.stopPropagation();
                    toggleBookmark(bookmark.line_number);
                };
                
                lineEl.style.position = 'relative';
                lineEl.appendChild(indicator);
            }
        });
        
        // הוספת אפשרות הוספת סימנייה לכל שורה
        addBookmarkHandlers();
    }
    
    // הוספת מאזינים לשורות קוד
    function addBookmarkHandlers() {
        const lineElements = document.querySelectorAll('.highlighttable .linenos pre > span, .linenodiv pre > span');
        
        lineElements.forEach((lineEl, index) => {
            const lineNumber = index + 1;
            
            // אם אין כבר אינדיקטור
            if (!lineEl.querySelector('.bookmark-indicator')) {
                lineEl.style.position = 'relative';
                
                // לחיצה על השורה
                lineEl.onclick = () => {
                    const isBookmarked = bookmarks.some(b => b.line_number === lineNumber);
                    if (isBookmarked) {
                        toggleBookmark(lineNumber);
                    } else {
                        // פתיחת מודל הערה
                        openNoteModal(lineNumber);
                    }
                };
            }
        });
    }
    
    // קבלת טקסט השורה
    function getLineText(lineNumber) {
        // בדיקת תקינות lineNumber
        if (!lineNumber || lineNumber < 1) {
            return 'קוד...';
        }
        
        const codeLines = document.querySelectorAll('.highlighttable td.code pre > span, .source pre > span');
        const index = lineNumber - 1;
        
        // בדיקת גבולות מערך
        if (index >= 0 && index < codeLines.length && codeLines[index]) {
            return codeLines[index].textContent.trim().substring(0, 60);
        }
        
        return 'קוד...';
    }
    
    // קבלת אלמנט השורה
    function getLineElement(lineNumber) {
        // בדיקת תקינות lineNumber
        if (!lineNumber || lineNumber < 1) {
            return null;
        }
        
        const lineElements = document.querySelectorAll('.highlighttable .linenos pre > span, .linenodiv pre > span');
        const index = lineNumber - 1;
        
        // בדיקת גבולות מערך
        if (index >= 0 && index < lineElements.length) {
            return lineElements[index] || null;
        }
        
        return null;
    }
    
    // גלילה לשורה
    function scrollToLine(lineNumber) {
        const lineEl = getLineElement(lineNumber);
        if (lineEl) {
            lineEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
            
            // הדגשה זמנית
            lineEl.style.background = 'rgba(255, 215, 0, 0.3)';
            setTimeout(() => {
                lineEl.style.background = '';
            }, 1000);
        }
    }
    
    // עדכון מונה סימניות
    function updateBookmarkCount() {
        const countEl = document.getElementById('bookmarkCount');
        if (countEl) {
            countEl.textContent = bookmarks.length;
        }
    }
    
    // פתיחת/סגירת פאנל
    window.toggleBookmarksPanel = function() {
        const panel = document.getElementById('bookmarksPanel');
        panel.classList.toggle('open');
    };
    
    // מודל הערה
    window.openNoteModal = function(lineNumber) {
        currentEditingBookmark = lineNumber;
        isEditingExistingBookmark = false;  // יצירת סימנייה חדשה
        document.getElementById('bookmarkNoteInput').value = '';
        document.getElementById('bookmarkNoteModal').classList.add('show');
    };
    
    window.closeNoteModal = function() {
        document.getElementById('bookmarkNoteModal').classList.remove('show');
        currentEditingBookmark = null;
        isEditingExistingBookmark = false;
    };
    
    window.saveBookmarkNote = async function() {
        const note = document.getElementById('bookmarkNoteInput').value.trim();
        if (!currentEditingBookmark) return;
        
        try {
            if (isEditingExistingBookmark) {
                // עדכון הערה של סימנייה קיימת
                const response = await fetch(`/api/bookmarks/${fileId}/${currentEditingBookmark}/note`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ note: note })
                });
                
                const data = await response.json();
                if (data.ok) {
                    await loadBookmarks();
                    showNotification('ההערה עודכנה בהצלחה');
                } else {
                    showNotification('שגיאה בעדכון הערה', 'error');
                }
            } else {
                // יצירת סימנייה חדשה
                await toggleBookmark(currentEditingBookmark, note);
            }
            closeNoteModal();
        } catch (error) {
            console.error('Error saving note:', error);
            showNotification('שגיאה בשמירת הערה', 'error');
        }
    };
    
    window.editBookmarkNote = function(lineNumber, currentNote) {
        currentEditingBookmark = lineNumber;
        isEditingExistingBookmark = true;  // עדכון סימנייה קיימת
        document.getElementById('bookmarkNoteInput').value = currentNote;
        document.getElementById('bookmarkNoteModal').classList.add('show');
    };
    
    window.deleteBookmark = async function(lineNumber) {
        if (confirm(`למחוק סימנייה בשורה ${lineNumber}?`)) {
            await toggleBookmark(lineNumber);
        }
    };
    
    // פונקציות עזר
    function escapeHtml(text) {
        const map = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;'
        };
        return (text || '').replace(/[&<>"']/g, m => map[m]);
    }
    
    function showNotification(message, type = 'success') {
        // הצגת התראה פשוטה (ניתן להחליף ב-toast library)
        const notification = document.createElement('div');
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: ${type === 'error' ? '#e74c3c' : '#27ae60'};
            color: white;
            padding: 1rem 1.5rem;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            z-index: 10000;
            animation: slideIn 0.3s ease;
        `;
        notification.textContent = message;
        document.body.appendChild(notification);
        
        setTimeout(() => {
            notification.style.animation = 'slideOut 0.3s ease';
            setTimeout(() => notification.remove(), 300);
        }, 3000);
    }
    
    // טעינה ראשונית
    loadBookmarks();
    
    // קיצורי מקלדת
    document.addEventListener('keydown', (e) => {
        // Ctrl/Cmd + B - פתיחת פאנל סימניות
        if ((e.ctrlKey || e.metaKey) && e.key === 'b') {
            e.preventDefault();
            toggleBookmarksPanel();
        }
    });
})();
</script>
```

---

## 🔌 API Endpoints (Backend)

### הוסף ל-`webapp/app.py`:

```python
# יצירת מופע BookmarksManager
from database.bookmarks_manager import BookmarksManager

bookmarks_manager = None

def get_bookmarks_manager():
    global bookmarks_manager
    if bookmarks_manager is None:
        db = get_db()
        bookmarks_manager = BookmarksManager(db)
    return bookmarks_manager


@app.route('/api/bookmarks/<file_id>', methods=['GET'])
def get_file_bookmarks(file_id):
    """קבלת כל הסימניות של קובץ"""
    if 'user_id' not in session:
        return jsonify({'ok': False, 'error': 'Unauthorized'}), 401
    
    try:
        user_id = session['user_id']
        bm_manager = get_bookmarks_manager()
        bookmarks = bm_manager.get_file_bookmarks(user_id, file_id)
        
        # המרה לפורמט JSON ידידותי
        bookmarks_data = []
        for bm in bookmarks:
            # המרה בטוחה של created_at
            created_at_str = None
            created_at = bm.get('created_at')
            if created_at:
                try:
                    created_at_str = created_at.isoformat() if hasattr(created_at, 'isoformat') else str(created_at)
                except Exception:
                    created_at_str = None
            
            bookmarks_data.append({
                'line_number': bm.get('line_number'),
                'note': bm.get('note', ''),
                'created_at': created_at_str
            })
        
        return jsonify({
            'ok': True,
            'bookmarks': bookmarks_data
        })
    
    except Exception as e:
        logger.error(f"Error getting bookmarks: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/bookmarks/<file_id>/toggle', methods=['POST'])
def toggle_bookmark(file_id):
    """הוספה/הסרה של סימנייה"""
    if 'user_id' not in session:
        return jsonify({'ok': False, 'error': 'Unauthorized'}), 401
    
    try:
        user_id = session['user_id']
        data = request.get_json()
        
        # המרה בטוחה למספר שלם
        try:
            line_number = int(data.get('line_number', 0))
        except (ValueError, TypeError):
            return jsonify({'ok': False, 'error': 'Invalid line number format'}), 400
        
        note = data.get('note', '')
        
        if line_number <= 0:
            return jsonify({'ok': False, 'error': 'Invalid line number'}), 400
        
        # קבלת שם הקובץ
        db = get_db()
        file_doc = db.code_snippets.find_one({'_id': ObjectId(file_id)})
        if not file_doc:
            return jsonify({'ok': False, 'error': 'File not found'}), 404
        
        file_name = file_doc.get('file_name', '')
        
        # טוגל סימנייה
        bm_manager = get_bookmarks_manager()
        result = bm_manager.toggle_bookmark(
            user_id=user_id,
            file_id=file_id,
            file_name=file_name,
            line_number=line_number,
            note=note
        )
        
        # המרה בטוחה ל-JSON (ללא ObjectId)
        bookmark_data = None
        if result['bookmark']:
            # המרה בטוחה של created_at
            created_at_str = None
            created_at = result['bookmark'].get('created_at')
            if created_at:
                try:
                    created_at_str = created_at.isoformat() if hasattr(created_at, 'isoformat') else str(created_at)
                except Exception:
                    created_at_str = None
            
            bookmark_data = {
                'line_number': result['bookmark'].get('line_number'),
                'note': result['bookmark'].get('note', ''),
                'created_at': created_at_str
            }
        
        return jsonify({
            'ok': True,
            'added': result['added'],
            'bookmark': bookmark_data
        })
    
    except Exception as e:
        logger.error(f"Error toggling bookmark: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/bookmarks/<file_id>/<int:line_number>/note', methods=['PUT'])
def update_bookmark_note(file_id, line_number):
    """עדכון הערה של סימנייה"""
    if 'user_id' not in session:
        return jsonify({'ok': False, 'error': 'Unauthorized'}), 401
    
    try:
        user_id = session['user_id']
        data = request.get_json()
        note = data.get('note', '')
        
        bm_manager = get_bookmarks_manager()
        success = bm_manager.update_bookmark_note(
            user_id=user_id,
            file_id=file_id,
            line_number=line_number,
            note=note
        )
        
        return jsonify({'ok': success})
    
    except Exception as e:
        logger.error(f"Error updating bookmark note: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/bookmarks/all', methods=['GET'])
def get_all_user_bookmarks():
    """קבלת כל הסימניות של משתמש (לכל הקבצים)"""
    if 'user_id' not in session:
        return jsonify({'ok': False, 'error': 'Unauthorized'}), 401
    
    try:
        user_id = session['user_id']
        bm_manager = get_bookmarks_manager()
        bookmarks = bm_manager.get_all_user_bookmarks(user_id, limit=100)
        
        # קיבוץ לפי קבצים
        files_bookmarks = {}
        for bm in bookmarks:
            file_id = str(bm.get('file_id'))
            if file_id not in files_bookmarks:
                files_bookmarks[file_id] = {
                    'file_id': file_id,
                    'file_name': bm.get('file_name', ''),
                    'bookmarks': []
                }
            files_bookmarks[file_id]['bookmarks'].append({
                'line_number': bm.get('line_number'),
                'note': bm.get('note', '')
            })
        
        return jsonify({
            'ok': True,
            'files': list(files_bookmarks.values())
        })
    
    except Exception as e:
        logger.error(f"Error getting all bookmarks: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500
```

---

## ✅ רשימת משימות למימוש

### שלב 1: Database ✓
- [ ] יצירת `database/bookmarks_manager.py`
- [ ] הוספת `FileBookmark` ל-`database/models.py`
- [ ] יצירת אינדקסים ב-MongoDB
- [ ] טסטים ל-BookmarksManager

### שלב 2: Backend API ✓
- [ ] הוספת endpoints ל-`webapp/app.py`
- [ ] אימות והרשאות
- [ ] טיפול בשגיאות
- [ ] לוגים

### שלב 3: Frontend ✓
- [ ] עדכון CSS ב-`view_file.html`
- [ ] הוספת HTML של פאנל סימניות
- [ ] JavaScript לניהול סימניות
- [ ] אינדיקטורים בשורות קוד

### שלב 4: UX/UI ✓
- [ ] אנימציות חלקות
- [ ] התראות (notifications)
- [ ] קיצורי מקלדת
- [ ] תמיכה במובייל

### שלב 5: פיצ'רים מתקדמים (אופציונלי)
- [ ] ייצוא סימניות (JSON/CSV)
- [ ] סינכרון עם GitHub (כ-TODO comments)
- [ ] שיתוף סימניות בין משתמשים
- [ ] חיפוש בסימניות

---

## 🧪 דוגמאות שימוש

### תרחיש 1: הוספת סימנייה פשוטה
```
1. משתמש פותח קובץ Python
2. לוחץ על שורה 42 (פונקציה חשובה)
3. מופיע מודל "הוסף הערה" (אופציונלי)
4. שומר "נקודת כניסה ראשית"
5. סימנייה מופיעה עם 🔖 בשורה
```

### תרחיש 2: ניווט בסימניות
```
1. משתמש לוחץ על כפתור "🔖 5" בצד השמאלי
2. נפתח פאנל עם רשימת 5 סימניות
3. לוחץ על "שורה 42 - נקודת כניסה ראשית"
4. הדף גולל אוטומטית לשורה 42
5. השורה מודגשת זמנית בצהוב
```

### תרחיש 3: עריכת הערה
```
1. פאנל סימניות פתוח
2. לוחץ על "✏️ ערוך הערה" ליד סימנייה
3. מופיע מודל עם הטקסט הנוכחי
4. משנה ל-"TODO: לבדוק edge cases"
5. שומר - ההערה מתעדכנת
```

---

## 🔧 שיקולים טכניים

### ביצועים
- **אינדקסים**: אינדקס מורכב על `(user_id, file_id, line_number)` למהירות מרבית
- **Cache**: שמירת סימניות ב-localStorage למניעת טעינות מיותרות
- **Lazy Loading**: טעינת סימניות רק בעמוד view_file

### אבטחה
- **הרשאות**: בדיקת `session['user_id']` בכל API call
- **Validation**: בדיקת `line_number > 0` ו-`file_id` תקין
- **Sanitization**: escape של `note` להימנע מ-XSS

### תאימות
- **מספרי שורות**: תמיד 1-based (כמו ברוב עורכי הקוד)
- **שורות שנמחקו**: סימניות נשארות גם אם הקוד השתנה
- **עדכון קוד**: אפשר להוסיף warning אם מספר שורות השתנה

### הרחבות עתידיות
1. **Code Lens**: הצגת מידע נוסף על הסימנייה (כמו ב-VSCode)
2. **Bookmarks Groups**: קטגוריות סימניות (bugs, todos, important)
3. **Smart Bookmarks**: סימניות שעוקבות אחר פונקציה גם אם השורה משתנה
4. **Collaborative**: שיתוף סימניות במסגרת צוות

---

## 📚 קישורים ומקורות

- [Flask Documentation](https://flask.palletsprojects.com/)
- [MongoDB Indexes](https://docs.mongodb.com/manual/indexes/)
- [Pygments Highlight](https://pygments.org/)
- [WebApp Architecture](/workspace/webapp/README.md)

---

## 📝 הערות לסיום

- יש לוודא שה-CSS תואם לנושאים (themes) הקיימים: classic, ocean, forest
- מומלץ להוסיף analytics למעקב אחר שימוש בפיצ'ר
- שקלו להוסיף onboarding tooltip בפעם הראשונה שמשתמש פותח קובץ
- תיעדו ב-README.md של WebApp את הפיצ'ר החדש

**בהצלחה במימוש! 🚀**
