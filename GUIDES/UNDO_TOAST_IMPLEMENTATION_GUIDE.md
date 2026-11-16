# מדריך מימוש Toast עם כפתור "בטל" לפעולות Bulk

> **מתי להשתמש:** בעת מימוש פעולות Bulk (מחיקה, תיוג, העברה) שדורשות אפשרות ביטול מהיר

---

## 🎯 סקירה כללית

מדריך זה מסביר כיצד לממש **Toast עם כפתור "בטל"** שמופיע לאחר פעולות Bulk כמו:
- **Bulk Delete** - מחיקת קבצים מרובים
- **Bulk Tag** - הוספת/הסרת תגיות
- **Bulk Move** - העברה לתיקייה/אוסף
- **Bulk Favorite** - הוספה/הסרה ממועדפים

הרעיון: במקום לבצע פעולה סופית מיד, **נעכב** את הביצוע הסופי למספר שניות ונאפשר למשתמש לבטל.

---

## 📐 ארכיטקטורה

### אסטרטגיות מימוש

#### אסטרטגיה 1: Soft Delete עם TTL (מומלץ למחיקה)

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  User Action    │────▶│  Mark Deleted   │────▶│  Toast + Undo   │
│  (Bulk Delete)  │     │  (soft_delete)  │     │  Button (5s)    │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                                        │
                        ┌───────────────────────────────┤
                        │                               │
                        ▼                               ▼
               ┌─────────────────┐             ┌─────────────────┐
               │  Undo Clicked   │             │  Time Expired   │
               │  → Restore      │             │  → Keep Deleted │
               └─────────────────┘             └─────────────────┘
```

#### אסטרטגיה 2: Deferred Action עם Timeout (מומלץ לתיוג/העברה)

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  User Action    │────▶│  Save to Queue  │────▶│  Toast + Undo   │
│  (Bulk Tag)     │     │  (pending_ops)  │     │  Button (5s)    │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                                        │
                        ┌───────────────────────────────┤
                        │                               │
                        ▼                               ▼
               ┌─────────────────┐             ┌─────────────────┐
               │  Undo Clicked   │             │  Time Expired   │
               │  → Cancel Op    │             │  → Execute Op   │
               └─────────────────┘             └─────────────────┘
```

---

## 🎨 Frontend Implementation

### 1. הרחבת מחלקת BulkActions

הוסף את הקוד הבא ל-`webapp/static/js/bulk-actions.js`:

```javascript
/**
 * Undo Toast System
 * מערכת Toast עם אפשרות ביטול לפעולות Bulk
 */

class UndoToastManager {
    constructor() {
        this.activeToasts = new Map(); // operationId -> { element, timeout, onUndo, cleanupTimeouts }
        this.container = this.createContainer();
    }

    createContainer() {
        let container = document.getElementById('undoToastContainer');
        if (!container) {
            container = document.createElement('div');
            container.id = 'undoToastContainer';
            container.className = 'undo-toast-container';
            document.body.appendChild(container);
        }
        return container;
    }

    /**
     * Escape HTML למניעת XSS
     */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * Sanitize icon name - רק אותיות, מספרים ומקפים
     */
    sanitizeIconName(icon) {
        return String(icon || 'check').replace(/[^a-zA-Z0-9-]/g, '');
    }

    /**
     * יצירת מזהה ייחודי לפעולה (helper משותף)
     */
    static generateOperationId(prefix = 'op') {
        return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`;
    }

    /**
     * הצגת Toast עם כפתור ביטול
     * @param {Object} options - אפשרויות
     * @param {string} options.operationId - מזהה ייחודי לפעולה
     * @param {string} options.message - הודעה להצגה
     * @param {number} options.duration - זמן בmilliseconds (ברירת מחדל: 5000)
     * @param {Function} options.onUndo - callback לביטול
     * @param {Function} options.onExpire - callback כשהזמן נגמר
     * @param {string} options.icon - אייקון FontAwesome (ברירת מחדל: 'check')
     */
    show(options) {
        // וידוא שהפרמטר קיים
        if (!options || typeof options !== 'object') {
            console.error('UndoToastManager.show: options parameter is required');
            return null;
        }

        const {
            operationId,
            message,
            duration = 5000,
            onUndo,
            onExpire,
            icon = 'check'
        } = options;

        // וידוא פרמטרים חובה
        if (!operationId || !message) {
            console.error('UndoToastManager.show: operationId and message are required');
            return null;
        }

        // אם יש Toast קודם לאותה פעולה - הסר אותו
        if (this.activeToasts.has(operationId)) {
            this.dismiss(operationId, false);
        }

        const toast = document.createElement('div');
        toast.className = 'undo-toast';
        toast.setAttribute('role', 'alert');
        toast.setAttribute('aria-live', 'polite');
        toast.dataset.operationId = operationId;

        // Progress bar לספירה לאחור
        const progressPercent = 100;

        // Sanitize inputs למניעת XSS
        const safeIcon = this.sanitizeIconName(icon);
        const safeMessage = this.escapeHtml(message);
        
        toast.innerHTML = `
            <div class="undo-toast-content">
                <i class="fas fa-${safeIcon} undo-toast-icon"></i>
                <span class="undo-toast-message">${safeMessage}</span>
            </div>
            <button class="undo-toast-button" type="button" aria-label="בטל פעולה">
                <i class="fas fa-undo"></i>
                <span>בטל</span>
            </button>
            <button class="undo-toast-close" type="button" aria-label="סגור">
                <i class="fas fa-times"></i>
            </button>
            <div class="undo-toast-progress">
                <div class="undo-toast-progress-bar" style="width: ${progressPercent}%"></div>
            </div>
        `;

        // Event Listeners
        const undoBtn = toast.querySelector('.undo-toast-button');
        const closeBtn = toast.querySelector('.undo-toast-close');
        const progressBar = toast.querySelector('.undo-toast-progress-bar');

        undoBtn.addEventListener('click', () => {
            this.handleUndo(operationId);
        });

        closeBtn.addEventListener('click', () => {
            this.dismiss(operationId, true);
        });

        // הוסף לcontainer
        this.container.appendChild(toast);

        // אנימציית כניסה
        requestAnimationFrame(() => {
            toast.classList.add('show');
        });

        // אנימציית Progress Bar
        progressBar.style.transition = `width ${duration}ms linear`;
        requestAnimationFrame(() => {
            progressBar.style.width = '0%';
        });

        // Timeout לסגירה אוטומטית
        const timeout = setTimeout(() => {
            this.dismiss(operationId, true);
        }, duration);

        // שמור reference
        this.activeToasts.set(operationId, {
            element: toast,
            timeout,
            onUndo,
            onExpire,
            isUndoing: false  // דגל למניעת קריאת onExpire בזמן undo
        });

        return operationId;
    }

    /**
     * עדכון טקסט ההודעה בצורה בטוחה
     */
    updateMessage(element, text) {
        const messageEl = element?.querySelector('.undo-toast-message');
        if (messageEl) {
            messageEl.textContent = text;
        }
    }

    /**
     * טיפול בלחיצה על "בטל"
     */
    async handleUndo(operationId) {
        const toastData = this.activeToasts.get(operationId);
        if (!toastData) return;

        // מנע לחיצות כפולות - בדוק אם כבר בתהליך ביטול
        if (toastData.isUndoing) {
            return;
        }

        const { element, timeout, onUndo } = toastData;

        // סמן שהפעולה בתהליך ביטול (למניעת קריאת onExpire ולחיצות כפולות)
        toastData.isUndoing = true;

        // עצור את הטיימר הראשי
        clearTimeout(timeout);

        // עדכן UI - הצג טוען
        element.classList.add('undoing');
        this.updateMessage(element, 'מבטל...');

        try {
            // הפעל callback
            if (typeof onUndo === 'function') {
                await onUndo();
            }

            // הצג הצלחה
            this.updateMessage(element, 'הפעולה בוטלה בהצלחה');
            element.classList.remove('undoing');
            element.classList.add('undone');

            // סגור אחרי שנייה - שמור reference ל-timeout
            const cleanupTimeout = setTimeout(() => {
                this.remove(operationId);
            }, 1500);
            toastData.cleanupTimeout = cleanupTimeout;

        } catch (error) {
            console.error('Undo failed:', error);
            this.updateMessage(element, 'שגיאה בביטול הפעולה');
            element.classList.remove('undoing');
            element.classList.add('error');

            // שמור reference ל-timeout
            const cleanupTimeout = setTimeout(() => {
                this.remove(operationId);
            }, 2000);
            toastData.cleanupTimeout = cleanupTimeout;
        }
    }

    /**
     * סגירת Toast (עם או בלי הפעלת onExpire)
     */
    dismiss(operationId, triggerExpire = true) {
        const toastData = this.activeToasts.get(operationId);
        if (!toastData) return;

        const { timeout, onExpire, isUndoing, cleanupTimeout } = toastData;
        clearTimeout(timeout);
        
        // בטל גם cleanup timeout אם קיים
        if (cleanupTimeout) {
            clearTimeout(cleanupTimeout);
        }

        // אל תקרא onExpire אם הפעולה בתהליך ביטול או כבר בוטלה
        if (triggerExpire && !isUndoing && typeof onExpire === 'function') {
            try {
                onExpire();
            } catch (error) {
                console.error('onExpire callback failed:', error);
            }
        }

        this.remove(operationId);
    }

    /**
     * הסרת Toast מה-DOM
     */
    remove(operationId) {
        const toastData = this.activeToasts.get(operationId);
        if (!toastData) return;

        const { element, timeout, cleanupTimeout, fallbackTimeout } = toastData;
        
        // בטל כל ה-timeouts הפעילים
        clearTimeout(timeout);
        if (cleanupTimeout) clearTimeout(cleanupTimeout);
        if (fallbackTimeout) clearTimeout(fallbackTimeout);

        // מחק מהמפה קודם כדי למנוע קריאות כפולות
        this.activeToasts.delete(operationId);

        element.classList.add('hiding');
        element.addEventListener('animationend', () => {
            if (element.parentNode) {
                element.remove();
            }
        }, { once: true });

        // Fallback אם אנימציה לא רצה - שמור reference (לא נשמר כי כבר מחקנו מהמפה)
        setTimeout(() => {
            if (element.parentNode) {
                element.remove();
            }
        }, 400);
    }

    /**
     * סגירת כל ה-Toasts
     */
    dismissAll() {
        for (const operationId of this.activeToasts.keys()) {
            this.dismiss(operationId, true);
        }
    }
}

// יצירת instance גלובלי
window.undoToast = new UndoToastManager();
```

### 2. עדכון פונקציית המחיקה

עדכן את `deleteSelected` ב-`bulk-actions.js`:

```javascript
async deleteSelected() {
    const files = window.multiSelect?.getSelectedFiles?.() || [];
    const count = files.length;
    
    if (count === 0) {
        this.showNotification('לא נבחרו קבצים', 'warning');
        return;
    }

    const fileIds = files.map(f => f.id);
    
    // יצירת מזהה ייחודי לפעולה (שימוש ב-helper משותף)
    const operationId = UndoToastManager.generateOperationId('delete');
    
    this.showProcessing(`מעביר ${count} קבצים לסל...`);
    
    try {
        // שלב 1: בצע Soft Delete
        const response = await fetch('/api/files/bulk-delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                file_ids: fileIds,
                operation_id: operationId  // לזיהוי הפעולה בביטול
            })
        });
        
        // בדוק סטטוס HTTP קודם
        if (!response.ok) {
            throw new Error(`שגיאת שרת: ${response.status} ${response.statusText}`);
        }
        
        let result;
        try {
            result = await response.json();
        } catch (parseError) {
            throw new Error('שגיאה בפענוח תשובת השרת');
        }
        
        if (!result.success) {
            throw new Error(result.error || 'שגיאה במחיקה');
        }
        
        this.hideProcessing();
        
        // שלב 2: הסתר קבצים מה-UI (אופטימיסטי)
        this.hideFilesFromUI(fileIds);
        
        // שלב 3: הצג Toast עם אפשרות ביטול
        window.undoToast.show({
            operationId,
            message: `${result.deleted} קבצים הועברו לסל המחזור`,
            duration: 7000,  // 7 שניות לביטול
            icon: 'trash',
            onUndo: async () => {
                // שחזר את הקבצים
                await this.undoDelete(operationId, fileIds);
            },
            onExpire: () => {
                // הזמן נגמר - המחיקה נשארת
                console.log('Delete operation finalized:', operationId);
            }
        });
        
        // נקה בחירה
        window.multiSelect?.clearSelection();
        
    } catch (error) {
        this.hideProcessing();
        console.error('Delete failed:', error);
        this.showNotification(error.message || 'שגיאה במחיקה', 'error');
    }
}

/**
 * הסתרת קבצים מה-UI באופן אופטימיסטי
 */
hideFilesFromUI(fileIds) {
    // אתחול מפת timeouts אם לא קיימת
    if (!this._hideTimeouts) {
        this._hideTimeouts = new Map();
    }
    
    fileIds.forEach(id => {
        const card = document.querySelector(`.file-card[data-file-id="${id}"]`);
        if (card) {
            // בטל timeout קודם אם קיים (מונע timeout leak)
            if (this._hideTimeouts.has(id)) {
                clearTimeout(this._hideTimeouts.get(id));
            }
            
            // סמן מיד שהקובץ בתהליך מחיקה (לפני האנימציה)
            card.dataset.pendingDelete = 'true';
            
            card.style.transition = 'opacity 0.3s, transform 0.3s';
            card.style.opacity = '0';
            card.style.transform = 'scale(0.9)';
            
            // שמור את ה-timeout כדי שנוכל לבטל אותו
            const timeoutId = setTimeout(() => {
                card.style.display = 'none';
                card.dataset.hiddenByDelete = 'true';
                card.dataset.pendingDelete = '';
                this._hideTimeouts.delete(id);
            }, 300);
            
            this._hideTimeouts.set(id, timeoutId);
        }
    });
}

/**
 * שחזור קבצים ל-UI
 * מטפל גם במקרה שהשחזור נקרא תוך כדי אנימציית ההסתרה
 */
restoreFilesToUI(fileIds) {
    fileIds.forEach(id => {
        const card = document.querySelector(`.file-card[data-file-id="${id}"]`);
        if (!card) return;
        
        // בטל timeout של הסתרה אם עדיין פעיל (race condition fix)
        if (this._hideTimeouts?.has(id)) {
            clearTimeout(this._hideTimeouts.get(id));
            this._hideTimeouts.delete(id);
        }
        
        // שחזר אם הקובץ מוסתר או בתהליך הסתרה
        const isHidden = card.dataset.hiddenByDelete === 'true';
        const isPending = card.dataset.pendingDelete === 'true';
        
        if (isHidden || isPending) {
            // נקה דגלים
            card.dataset.hiddenByDelete = '';
            card.dataset.pendingDelete = '';
            
            // שחזר תצוגה
            card.style.display = '';
            requestAnimationFrame(() => {
                card.style.opacity = '1';
                card.style.transform = 'scale(1)';
            });
        }
    });
}

/**
 * ביטול מחיקה
 */
async undoDelete(operationId, fileIds) {
    // בדוק סטטוס HTTP קודם
    const response = await fetch('/api/files/bulk-restore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
            file_ids: fileIds,
            operation_id: operationId
        })
    });
    
    if (!response.ok) {
        throw new Error(`שגיאת שרת: ${response.status} ${response.statusText}`);
    }
    
    let result;
    try {
        result = await response.json();
    } catch (parseError) {
        throw new Error('שגיאה בפענוח תשובת השרת');
    }
    
    if (!result.success) {
        throw new Error(result.error || 'שגיאה בשחזור');
    }
    
    // שחזר ב-UI רק את הקבצים שהצליחו (טיפול בהצלחה חלקית)
    if (result.restored === fileIds.length) {
        // כל הקבצים שוחזרו
        this.restoreFilesToUI(fileIds);
    } else if (result.restored > 0) {
        // הצלחה חלקית - שחזר הכל ב-UI והודע למשתמש
        this.restoreFilesToUI(fileIds);
        console.warn(`Partial restore: ${result.restored}/${result.total} files restored`);
    }
    // אם restored === 0 לא נשחזר כלום ב-UI
    
    return result;
}
```

### 3. עדכון פונקציית התיוג עם Undo

```javascript
async addTags() {
    const files = window.multiSelect?.getSelectedFiles?.() || [];
    const fileIds = files.map(f => f.id);
    
    if (fileIds.length === 0) {
        this.showNotification('לא נבחרו קבצים', 'warning');
        return;
    }
    
    // הצג דיאלוג להזנת תגיות
    const newTags = await this.showTagDialog();
    if (!newTags || newTags.length === 0) return;
    
    // יצירת מזהה ייחודי לפעולה (שימוש ב-helper משותף)
    const operationId = UndoToastManager.generateOperationId('tag');
    
    this.showProcessing(`מוסיף תגיות ל-${fileIds.length} קבצים...`);
    
    try {
        // שמור מצב קודם (לביטול) - חשוב לטפל בשגיאות כאן
        let previousState;
        try {
            previousState = await this.getFilesTags(fileIds);
        } catch (err) {
            console.warn('Failed to save previous tags state:', err);
            // נמשיך בלי אפשרות ביטול אם לא הצלחנו לשמור את המצב הקודם
            previousState = null;
        }
        
        const response = await fetch('/api/files/bulk-tag', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                file_ids: fileIds,
                tags: newTags,
                operation_id: operationId
            })
        });
        
        // בדוק סטטוס HTTP קודם
        if (!response.ok) {
            throw new Error(`שגיאת שרת: ${response.status} ${response.statusText}`);
        }
        
        let result;
        try {
            result = await response.json();
        } catch (parseError) {
            throw new Error('שגיאה בפענוח תשובת השרת');
        }
        
        if (!result.success) {
            throw new Error(result.error || 'שגיאה בהוספת תגיות');
        }
        
        this.hideProcessing();
        
        // עדכן UI אופטימיסטי
        this.updateTagsInUI(fileIds, newTags, 'add');
        
        // הצג Toast - עם או בלי אפשרות ביטול
        if (previousState && Object.keys(previousState).length > 0) {
            // יש מצב קודם - אפשר לבטל
            window.undoToast.show({
                operationId,
                message: `תגיות נוספו ל-${result.updated} קבצים`,
                duration: 5000,
                icon: 'tags',
                onUndo: async () => {
                    await this.undoTagChange(fileIds, previousState);
                }
            });
        } else {
            // אין מצב קודם - הצג notification רגיל בלי undo
            this.showNotification(`תגיות נוספו ל-${result.updated} קבצים`, 'success');
        }
        
        window.multiSelect?.clearSelection();
        
    } catch (error) {
        this.hideProcessing();
        console.error('Tag operation failed:', error);
        this.showNotification(error.message || 'שגיאה בהוספת תגיות', 'error');
    }
}

/**
 * קבלת תגיות נוכחיות של קבצים (לשמירת מצב קודם)
 * @throws {Error} אם הבקשה נכשלת
 */
async getFilesTags(fileIds) {
    const response = await fetch('/api/files/get-tags', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_ids: fileIds })
    });
    
    // בדוק סטטוס HTTP קודם - לפני ניסיון לפרסר JSON
    if (!response.ok) {
        throw new Error(`שגיאת שרת: ${response.status} ${response.statusText}`);
    }
    
    // רק אחרי בדיקת הסטטוס - נסה לפרסר JSON
    let result;
    try {
        result = await response.json();
    } catch (parseError) {
        throw new Error('שגיאה בפענוח תשובת השרת');
    }
    
    // בדוק שהפעולה הצליחה
    if (!result.success) {
        throw new Error(result.error || 'שגיאה בקבלת תגיות קיימות');
    }
    
    return result.tags;
}

/**
 * ביטול שינוי תגיות
 */
async undoTagChange(fileIds, previousState) {
    const response = await fetch('/api/files/bulk-set-tags', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
            files_tags: previousState  // { file_id: [tags], ... }
        })
    });
    
    // בדוק סטטוס HTTP קודם
    if (!response.ok) {
        throw new Error(`שגיאת שרת: ${response.status} ${response.statusText}`);
    }
    
    let result;
    try {
        result = await response.json();
    } catch (parseError) {
        throw new Error('שגיאה בפענוח תשובת השרת');
    }
    
    if (!result.success) {
        throw new Error(result.error || 'שגיאה בשחזור תגיות');
    }
    
    // רענן UI
    location.reload();
}
```

---

## 🎨 CSS Styles

הוסף את הסטיילים הבאים ל-`webapp/static/css/multi-select.css`:

```css
/* ===============================================
   Undo Toast Container
   =============================================== */
.undo-toast-container {
    position: fixed;
    bottom: 24px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 10000;
    display: flex;
    flex-direction: column-reverse;
    gap: 12px;
    pointer-events: none;
    max-width: 90vw;
}

/* ===============================================
   Undo Toast
   =============================================== */
.undo-toast {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 16px;
    background: var(--undo-toast-bg, rgba(30, 30, 50, 0.95));
    color: var(--undo-toast-color, #fff);
    border-radius: 12px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
    pointer-events: auto;
    opacity: 0;
    transform: translateY(20px) scale(0.95);
    transition: opacity 0.3s ease, transform 0.3s ease;
    position: relative;
    overflow: hidden;
    min-width: 300px;
    max-width: 500px;
    backdrop-filter: blur(12px);
}

.undo-toast.show {
    opacity: 1;
    transform: translateY(0) scale(1);
}

.undo-toast.hiding {
    animation: toastSlideOut 0.3s ease forwards;
}

@keyframes toastSlideOut {
    to {
        opacity: 0;
        transform: translateY(20px) scale(0.95);
    }
}

/* Content */
.undo-toast-content {
    display: flex;
    align-items: center;
    gap: 10px;
    flex: 1;
    min-width: 0;
}

.undo-toast-icon {
    font-size: 1.1rem;
    color: var(--undo-toast-icon-color, #4ade80);
    flex-shrink: 0;
}

.undo-toast-message {
    font-size: 0.95rem;
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

/* Undo Button */
.undo-toast-button {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 14px;
    background: var(--undo-toast-btn-bg, rgba(255, 255, 255, 0.15));
    color: var(--undo-toast-btn-color, #fff);
    border: 1px solid var(--undo-toast-btn-border, rgba(255, 255, 255, 0.2));
    border-radius: 8px;
    font-size: 0.9rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s ease;
    flex-shrink: 0;
}

.undo-toast-button:hover {
    background: var(--undo-toast-btn-hover-bg, rgba(255, 255, 255, 0.25));
    transform: scale(1.02);
}

.undo-toast-button:active {
    transform: scale(0.98);
}

.undo-toast-button i {
    font-size: 0.85rem;
}

/* Close Button */
.undo-toast-close {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    background: transparent;
    color: var(--undo-toast-close-color, rgba(255, 255, 255, 0.5));
    border: none;
    border-radius: 6px;
    cursor: pointer;
    transition: all 0.2s ease;
    flex-shrink: 0;
}

.undo-toast-close:hover {
    background: rgba(255, 255, 255, 0.1);
    color: #fff;
}

/* Progress Bar */
.undo-toast-progress {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    height: 3px;
    background: rgba(255, 255, 255, 0.1);
    overflow: hidden;
}

.undo-toast-progress-bar {
    height: 100%;
    background: var(--undo-toast-progress-color, #4ade80);
    transition: width 0.1s linear;
}

/* States */
.undo-toast.undoing {
    pointer-events: none;
}

.undo-toast.undoing .undo-toast-button {
    opacity: 0.5;
}

.undo-toast.undoing .undo-toast-icon {
    animation: spin 1s linear infinite;
}

@keyframes spin {
    to { transform: rotate(360deg); }
}

.undo-toast.undone .undo-toast-icon {
    color: #22c55e;
}

.undo-toast.undone .undo-toast-progress-bar {
    background: #22c55e;
    width: 100% !important;
}

.undo-toast.error .undo-toast-icon {
    color: #ef4444;
}

.undo-toast.error .undo-toast-progress-bar {
    background: #ef4444;
}

/* ===============================================
   Theme Variants
   =============================================== */

/* Light Theme */
:root[data-theme="light"] .undo-toast,
:root[data-theme="github-light"] .undo-toast {
    --undo-toast-bg: rgba(255, 255, 255, 0.98);
    --undo-toast-color: #1f2937;
    --undo-toast-icon-color: #059669;
    --undo-toast-btn-bg: rgba(0, 0, 0, 0.08);
    --undo-toast-btn-color: #1f2937;
    --undo-toast-btn-border: rgba(0, 0, 0, 0.1);
    --undo-toast-btn-hover-bg: rgba(0, 0, 0, 0.12);
    --undo-toast-close-color: rgba(0, 0, 0, 0.4);
    --undo-toast-progress-color: #059669;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
}

/* Dark Blue Theme */
:root[data-theme="dark-blue"] .undo-toast {
    --undo-toast-bg: rgba(30, 41, 59, 0.98);
    --undo-toast-progress-color: #60a5fa;
    --undo-toast-icon-color: #60a5fa;
}

/* Rose Pine */
:root[data-theme="rose-pine"] .undo-toast {
    --undo-toast-bg: rgba(35, 33, 54, 0.98);
    --undo-toast-progress-color: #c4a7e7;
    --undo-toast-icon-color: #c4a7e7;
}

/* ===============================================
   RTL Support
   =============================================== */
[dir="rtl"] .undo-toast-container,
:root[dir="rtl"] .undo-toast-container {
    direction: rtl;
}

[dir="rtl"] .undo-toast-content,
:root[dir="rtl"] .undo-toast-content {
    flex-direction: row-reverse;
}

[dir="rtl"] .undo-toast-button i,
:root[dir="rtl"] .undo-toast-button i {
    transform: scaleX(-1);
}

/* ===============================================
   Mobile Responsive
   =============================================== */
@media (max-width: 640px) {
    .undo-toast-container {
        bottom: 16px;
        left: 16px;
        right: 16px;
        transform: none;
        max-width: none;
    }
    
    .undo-toast {
        min-width: auto;
        width: 100%;
        padding: 10px 14px;
        flex-wrap: wrap;
    }
    
    .undo-toast-content {
        flex: 1 1 100%;
        margin-bottom: 8px;
    }
    
    .undo-toast-button {
        flex: 1;
        justify-content: center;
    }
    
    .undo-toast-close {
        position: absolute;
        top: 8px;
        /* תמיכה ב-RTL למובייל */
        left: 8px;
        right: auto;
    }
    
    /* RTL support for mobile close button */
    [dir="rtl"] .undo-toast-close,
    :root[dir="rtl"] .undo-toast-close {
        left: auto;
        right: 8px;
    }
}
```

---

## 🖥️ Backend Implementation

### 1. API לשחזור קבצים

הוסף ל-`webapp/app.py`:

> **הערה:** וודא שיש לך את ה-import הבא בראש הקובץ:
> ```python
> from bson.errors import InvalidId
> ```

```python
@app.route('/api/files/bulk-restore', methods=['POST'])
@login_required
@traced("files.bulk_restore")
def api_files_bulk_restore():
    """שחזור קבצים שנמחקו (ביטול מחיקה)"""
    try:
        data = request.get_json() or {}
        file_ids = data.get('file_ids', [])
        operation_id = data.get('operation_id')
        
        # וידוא שfile_ids הוא רשימה
        if not isinstance(file_ids, list):
            return jsonify({"success": False, "error": "file_ids חייב להיות רשימה"}), 400
        
        if not file_ids:
            return jsonify({"success": False, "error": "לא סופקו מזהי קבצים"}), 400
        
        user_id = str(current_user.id)
        restored_count = 0
        
        for file_id in file_ids:
            try:
                # שחזר רק קבצים של המשתמש הנוכחי
                result = db_manager.code_snippets.update_one(
                    {
                        "_id": ObjectId(file_id),
                        "user_id": user_id,
                        "is_deleted": True
                    },
                    {
                        "$set": {"is_deleted": False},
                        "$unset": {"deleted_at": "", "delete_ttl": ""}
                    }
                )
                if result.modified_count > 0:
                    restored_count += 1
            except (ValueError, TypeError, InvalidId) as e:
                app.logger.warning(f"Invalid file_id {file_id}: {e}")
                continue
            except Exception as e:
                app.logger.warning(f"Failed to restore file {file_id}: {e}")
                continue
        
        app.logger.info(
            f"Bulk restore: user={user_id}, restored={restored_count}/{len(file_ids)}, "
            f"operation_id={operation_id}"
        )
        
        return jsonify({
            "success": True,
            "restored": restored_count,
            "total": len(file_ids)
        })
        
    except Exception as e:
        app.logger.error(f"Error in bulk restore: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/files/get-tags', methods=['POST'])
@login_required
@traced("files.get_tags")
def api_files_get_tags():
    """קבלת תגיות נוכחיות של קבצים (לשמירת מצב לפני שינוי)"""
    try:
        data = request.get_json() or {}
        file_ids = data.get('file_ids', [])
        
        # וידוא שfile_ids הוא רשימה
        if not isinstance(file_ids, list):
            return jsonify({"success": False, "error": "file_ids חייב להיות רשימה"}), 400
        
        if not file_ids:
            return jsonify({"success": True, "tags": {}}), 200
        
        user_id = str(current_user.id)
        result = {}
        
        for file_id in file_ids:
            try:
                doc = db_manager.code_snippets.find_one(
                    {"_id": ObjectId(file_id), "user_id": user_id},
                    {"tags": 1}
                )
                if doc:
                    result[file_id] = doc.get("tags", [])
            except (ValueError, TypeError, InvalidId) as e:
                app.logger.debug(f"Invalid file_id {file_id}: {e}")
                continue
        
        return jsonify({"success": True, "tags": result})
        
    except Exception as e:
        app.logger.error(f"Error getting tags: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/files/bulk-set-tags', methods=['POST'])
@login_required
@traced("files.bulk_set_tags")
def api_files_bulk_set_tags():
    """הגדרת תגיות ספציפיות לקבצים (לביטול שינוי תגיות)"""
    try:
        data = request.get_json() or {}
        files_tags = data.get('files_tags', {})  # { file_id: [tags], ... }
        
        # וידוא שfiles_tags הוא dict
        if not isinstance(files_tags, dict):
            return jsonify({"success": False, "error": "files_tags חייב להיות אובייקט"}), 400
        
        if not files_tags:
            return jsonify({"success": True, "updated": 0})
        
        user_id = str(current_user.id)
        updated_count = 0
        
        for file_id, tags in files_tags.items():
            try:
                # וידוא שtags הוא רשימה
                if not isinstance(tags, list):
                    app.logger.warning(f"Invalid tags format for {file_id}")
                    continue
                    
                result = db_manager.code_snippets.update_one(
                    {"_id": ObjectId(file_id), "user_id": user_id},
                    {"$set": {"tags": tags}}
                )
                if result.modified_count > 0:
                    updated_count += 1
            except (ValueError, TypeError, InvalidId) as e:
                app.logger.debug(f"Invalid file_id {file_id}: {e}")
                continue
            except Exception as e:
                app.logger.warning(f"Failed to set tags for {file_id}: {e}")
                continue
        
        return jsonify({
            "success": True,
            "updated": updated_count
        })
        
    except Exception as e:
        app.logger.error(f"Error setting tags: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
```

---

## ⚙️ Configuration

### משתני סביבה מומלצים

```bash
# זמן ברירת מחדל לביטול (milliseconds)
UNDO_TOAST_DURATION=7000

# זמן שמירת קבצים מחוקים לפני מחיקה סופית (שניות)
SOFT_DELETE_TTL=604800  # 7 ימים
```

---

## 🧪 Testing

### Unit Tests (JavaScript)

```javascript
describe('UndoToastManager', () => {
    let manager;
    
    beforeEach(() => {
        document.body.innerHTML = '';
        manager = new UndoToastManager();
    });
    
    afterEach(() => {
        manager.dismissAll();
    });
    
    test('should show toast with undo button', () => {
        manager.show({
            operationId: 'test_1',
            message: 'Test message',
            duration: 5000,
            onUndo: jest.fn()
        });
        
        const toast = document.querySelector('.undo-toast');
        expect(toast).not.toBeNull();
        expect(toast.textContent).toContain('Test message');
        expect(toast.querySelector('.undo-toast-button')).not.toBeNull();
    });
    
    test('should call onUndo when button clicked', async () => {
        const onUndo = jest.fn().mockResolvedValue();
        
        manager.show({
            operationId: 'test_2',
            message: 'Test',
            onUndo
        });
        
        const button = document.querySelector('.undo-toast-button');
        button.click();
        
        await new Promise(r => setTimeout(r, 100));
        expect(onUndo).toHaveBeenCalled();
    });
    
    test('should call onExpire when time runs out', async () => {
        const onExpire = jest.fn();
        
        manager.show({
            operationId: 'test_3',
            message: 'Test',
            duration: 100,
            onExpire
        });
        
        await new Promise(r => setTimeout(r, 200));
        expect(onExpire).toHaveBeenCalled();
    });
});
```

### Integration Test (Python)

```python
def test_bulk_restore_after_delete(client, auth_headers, test_files):
    """בדיקת שחזור קבצים אחרי מחיקה"""
    file_ids = [str(f['_id']) for f in test_files]
    
    # מחיקה
    delete_resp = client.post(
        '/api/files/bulk-delete',
        json={'file_ids': file_ids},
        headers=auth_headers
    )
    assert delete_resp.json['success']
    
    # שחזור
    restore_resp = client.post(
        '/api/files/bulk-restore',
        json={'file_ids': file_ids},
        headers=auth_headers
    )
    assert restore_resp.json['success']
    assert restore_resp.json['restored'] == len(file_ids)
    
    # וידוא שהקבצים חזרו
    for file_id in file_ids:
        doc = db.code_snippets.find_one({'_id': ObjectId(file_id)})
        assert doc['is_deleted'] == False
```

---

## 📋 Checklist למימוש

- [ ] הוספת `UndoToastManager` ל-`bulk-actions.js`
- [ ] עדכון CSS ב-`multi-select.css`
- [ ] הוספת API `/api/files/bulk-restore`
- [ ] הוספת API `/api/files/get-tags`
- [ ] הוספת API `/api/files/bulk-set-tags`
- [ ] עדכון פונקציות Bulk הקיימות להשתמש ב-Undo Toast
- [ ] הוספת טסטים
- [ ] בדיקת תמיכה ב-RTL
- [ ] בדיקת תצוגה במובייל
- [ ] בדיקת תמיכה בערכות נושא שונות

---

## 🔗 קישורים רלוונטיים

- [Multi-Select Implementation Guide](./MULTI_SELECT_IMPLEMENTATION_GUIDE.md)
- [Bulk Actions Source](../webapp/static/js/bulk-actions.js)
- [CodeBot Documentation](https://amirbiron.github.io/CodeBot/)

---

## 📝 הערות נוספות

### שיקולי UX

1. **משך זמן מומלץ:** 5-7 שניות הוא הזמן האופטימלי - מספיק ללחוץ "בטל" אבל לא ארוך מדי
2. **Progress Bar:** מאפשר למשתמש לראות כמה זמן נשאר
3. **מיקום:** מרכז-תחתון הוא המיקום הסטנדרטי ל-Toast
4. **ריבוי Toasts:** תמיכה במספר פעולות במקביל

### שיקולי ביצועים

1. **Optimistic UI:** הסתרת קבצים מיידית ב-UI לפני אישור מהשרת
2. **Soft Delete:** שימוש ב-flag במקום מחיקה אמיתית מאפשר שחזור מהיר
3. **Batching:** שליחת כל מזהי הקבצים בקריאת API אחת

### שיקולי אבטחה

1. **User Validation:** תמיד לוודא שהקבצים שייכים למשתמש הנוכחי
2. **Operation ID:** מזהה ייחודי מונע שחזור כפול או לא מורשה
3. **Rate Limiting:** הגבלת קריאות API למניעת שימוש לרעה
