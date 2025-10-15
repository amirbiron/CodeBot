/**
 * Multi-Select Manager for Code Files
 * מערכת בחירה מרובה לקבצים בווב אפ
 */

class MultiSelectManager {
    constructor() {
        // שימוש ב-Map במקום Set כדי למנוע כפילויות
        // Key: fileId, Value: {id, name}
        this.selectedFiles = new Map();
        this.toolbar = document.getElementById('bulkActionsToolbar');
        this.lastSelectedIndex = -1;
        this.init();
    }
    
    init() {
        // הגדרת event listeners
        this.setupCheckboxListeners();
        this.setupKeyboardShortcuts();
        this.setupSelectAllButton();
        this.restoreSelection();
        
        console.log('MultiSelectManager initialized');
    }
    
    setupCheckboxListeners() {
        // Event delegation לכל השינויים ב-checkboxes
        document.addEventListener('change', (e) => {
            if (e.target.classList.contains('file-checkbox')) {
                this.handleFileSelection(e.target);
            }
        });
        
        // תמיכה ב-Shift+Click לבחירת טווח
        document.addEventListener('click', (e) => {
            if (e.target.classList.contains('file-checkbox') && e.shiftKey) {
                e.preventDefault();
                this.handleRangeSelection(e.target);
            }
        });
    }
    
    handleFileSelection(checkbox) {
        const fileId = checkbox.dataset.fileId;
        const fileName = checkbox.dataset.fileName;
        const fileCard = checkbox.closest('.file-card');
        
        if (checkbox.checked) {
            // שימוש ב-Map.set מבטיח שאין כפילויות - מחליף ערך קיים
            this.selectedFiles.set(fileId, {
                id: fileId,
                name: fileName
            });
            fileCard.classList.add('selected');
        } else {
            // מחיקה לפי key (fileId) - פשוט ויעיל
            this.selectedFiles.delete(fileId);
            fileCard.classList.remove('selected');
        }
        
        // שמור אינדקס אחרון שנבחר
        const allCheckboxes = Array.from(document.querySelectorAll('.file-checkbox'));
        this.lastSelectedIndex = allCheckboxes.indexOf(checkbox);
        
        this.updateToolbar();
        this.persistSelection();
    }
    
    handleRangeSelection(checkbox) {
        const allCheckboxes = Array.from(document.querySelectorAll('.file-checkbox'));
        const currentIndex = allCheckboxes.indexOf(checkbox);
        
        if (this.lastSelectedIndex === -1) {
            this.lastSelectedIndex = currentIndex;
            return;
        }
        
        const start = Math.min(this.lastSelectedIndex, currentIndex);
        const end = Math.max(this.lastSelectedIndex, currentIndex);
        
        // בחר/בטל בחירה של כל הקבצים בטווח
        for (let i = start; i <= end; i++) {
            const cb = allCheckboxes[i];
            if (!cb.checked) {
                cb.checked = true;
                this.handleFileSelection(cb);
            }
        }
    }
    
    updateToolbar() {
        // Map.size נותן את המספר הנכון של קבצים ייחודיים
        const count = this.selectedFiles.size;
        
        if (!this.toolbar) {
            console.warn('Toolbar element not found');
            return;
        }
        
        const countElement = this.toolbar.querySelector('.selected-count');
        
        if (count > 0) {
            if (countElement) {
                countElement.textContent = count;
            }
            
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
            // Ctrl+A או Cmd+A - בחר הכל
            if ((e.ctrlKey || e.metaKey) && e.key === 'a') {
                // רק אם לא בתוך input או textarea
                if (e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA') {
                    e.preventDefault();
                    this.selectAll();
                }
            }
            
            // Escape - נקה בחירה
            if (e.key === 'Escape') {
                this.clearSelection();
            }
            
            // Delete - מחק קבצים נבחרים (אופציונלי - לא מופעל כברירת מחדל)
            // כדי להפעיל, הסר את ההערות והוסף את ה-endpoint בbackend
            /*
            if (e.key === 'Delete' && this.selectedFiles.size > 0) {
                if (confirm(`האם למחוק ${this.selectedFiles.size} קבצים?`)) {
                    this.deleteSelected();
                }
            }
            */
        });
    }
    
    setupSelectAllButton() {
        // הוסף כפתור "בחר הכל" אם לא קיים
        const filtersSection = document.querySelector('.filters-section');
        if (filtersSection && !document.getElementById('selectAllBtn')) {
            const selectAllBtn = document.createElement('button');
            selectAllBtn.id = 'selectAllBtn';
            selectAllBtn.className = 'btn btn-secondary btn-icon';
            selectAllBtn.innerHTML = '<i class="fas fa-check-square"></i> בחר הכל';
            selectAllBtn.onclick = () => this.selectAll();
            
            filtersSection.appendChild(selectAllBtn);
        }
    }
    
    selectAll() {
        const checkboxes = document.querySelectorAll('.file-checkbox');
        const allChecked = this.selectedFiles.size === checkboxes.length;
        
        checkboxes.forEach(checkbox => {
            // אם הכל מסומן - בטל סימון, אחרת סמן הכל
            checkbox.checked = !allChecked;
            this.handleFileSelection(checkbox);
        });
    }
    
    clearSelection() {
        document.querySelectorAll('.file-checkbox:checked').forEach(checkbox => {
            checkbox.checked = false;
            this.handleFileSelection(checkbox);
        });
    }
    
    // פונקציה אופציונלית למחיקה קבוצתית
    // כדי להפעיל: הסר את ההערה מכל הפונקציה ומה-Delete key handler למעלה
    // והוסף את ה-endpoint /api/files/bulk-delete בbackend
    /*
    deleteSelected() {
        // עם Map, מחלצים את ה-IDs מה-values
        const fileIds = Array.from(this.selectedFiles.values()).map(f => f.id);
        
        if (fileIds.length === 0) return;
        
        // הצג אנימציית עיבוד
        window.bulkActions?.showProcessing(`מוחק ${fileIds.length} קבצים...`);
        
        fetch('/api/files/bulk-delete', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ file_ids: fileIds })
        })
        .then(response => response.json())
        .then(result => {
            if (result.success) {
                window.bulkActions?.showNotification(`${result.deleted} קבצים נמחקו`, 'success');
                
                // הסר את הכרטיסים מה-DOM
                fileIds.forEach(id => {
                    const card = document.querySelector(`[data-file-id="${id}"]`);
                    if (card) {
                        card.style.transition = 'opacity 0.3s, transform 0.3s';
                        card.style.opacity = '0';
                        card.style.transform = 'scale(0.9)';
                        setTimeout(() => card.remove(), 300);
                    }
                });
                
                this.clearSelection();
            } else {
                throw new Error(result.error || 'שגיאה במחיקה');
            }
        })
        .catch(error => {
            console.error('Error deleting files:', error);
            window.bulkActions?.showNotification('שגיאה במחיקת הקבצים', 'error');
        })
        .finally(() => {
            window.bulkActions?.hideProcessing();
        });
    }
    */
    
    persistSelection() {
        // שמור בחירה ב-sessionStorage לשמירה בין עמודים
        // עם Map, שומרים רק את ה-keys (file IDs)
        const fileIds = Array.from(this.selectedFiles.keys());
        sessionStorage.setItem('selectedFiles', JSON.stringify(fileIds));
    }
    
    restoreSelection() {
        // שחזר בחירה אחרי מעבר עמוד או רענון
        const stored = sessionStorage.getItem('selectedFiles');
        if (stored) {
            try {
                const fileIds = JSON.parse(stored);
                fileIds.forEach(id => {
                    const checkbox = document.querySelector(`.file-checkbox[data-file-id="${id}"]`);
                    if (checkbox) {
                        checkbox.checked = true;
                        this.handleFileSelection(checkbox);
                    }
                });
            } catch (e) {
                console.error('Error restoring selection:', e);
                sessionStorage.removeItem('selectedFiles');
            }
        }
    }
    
    // API Methods
    getSelectedFiles() {
        // החזר את כל הערכים מה-Map כמערך
        return Array.from(this.selectedFiles.values());
    }
    
    getSelectedCount() {
        return this.selectedFiles.size;
    }
    
    addToSelection(fileId, fileName) {
        // Map.set מבטיח ייחודיות אוטומטית
        this.selectedFiles.set(fileId, { id: fileId, name: fileName });
        this.updateToolbar();
        this.persistSelection();
    }
    
    removeFromSelection(fileId) {
        // מחיקה פשוטה לפי key
        if (this.selectedFiles.delete(fileId)) {
            this.updateToolbar();
            this.persistSelection();
        }
    }
}

// אתחול המערכת כשהדף נטען
document.addEventListener('DOMContentLoaded', () => {
    // בדוק אם אנחנו בדף הקבצים
    if (document.querySelector('.files-grid') || document.querySelector('.file-card')) {
        window.multiSelect = new MultiSelectManager();
        console.log('Multi-select system initialized');
    }
});