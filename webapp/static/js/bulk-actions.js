/**
 * Bulk Actions Handler
 * מערכת לביצוע פעולות קבוצתיות על קבצים
 */

class BulkActions {
    constructor() {
        this.processingOverlay = this.createProcessingOverlay();
        this.notificationContainer = this.createNotificationContainer();
    }
    
    createProcessingOverlay() {
        const overlay = document.createElement('div');
        overlay.className = 'processing-overlay hidden';
        overlay.innerHTML = `
            <div class="processing-content">
                <div class="spinner"></div>
                <div class="processing-text">מעבד...</div>
                <div class="processing-progress hidden">
                    <div class="progress-bar">
                        <div class="progress-fill"></div>
                    </div>
                    <div class="progress-text">0%</div>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);
        return overlay;
    }
    
    createNotificationContainer() {
        let container = document.getElementById('notificationContainer');
        if (!container) {
            container = document.createElement('div');
            container.id = 'notificationContainer';
            container.className = 'notification-container';
            document.body.appendChild(container);
        }
        return container;
    }
    
    showProcessing(text = 'מעבד...', showProgress = false) {
        this.processingOverlay.querySelector('.processing-text').textContent = text;
        const progressEl = this.processingOverlay.querySelector('.processing-progress');
        
        if (showProgress) {
            progressEl.classList.remove('hidden');
        } else {
            progressEl.classList.add('hidden');
        }
        
        this.processingOverlay.classList.remove('hidden');
    }
    
    updateProgress(percent) {
        const progressFill = this.processingOverlay.querySelector('.progress-fill');
        const progressText = this.processingOverlay.querySelector('.progress-text');
        
        if (progressFill && progressText) {
            progressFill.style.width = `${percent}%`;
            progressText.textContent = `${Math.round(percent)}%`;
        }
    }
    
    hideProcessing() {
        this.processingOverlay.classList.add('hidden');
        // איפוס progress
        this.updateProgress(0);
    }
    
    async addToFavorites() {
        const fileIds = window.multiSelect.getSelectedFiles().map(f => f.id);
        
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
                this.showNotification(
                    `${result.updated} קבצים נוספו למועדפים`,
                    'success',
                    { icon: 'star' }
                );
                
                // עדכן UI - הוסף כוכב למועדפים
                fileIds.forEach(id => {
                    const card = document.querySelector(`.file-card[data-file-id="${id}"]`);
                    if (card) {
                        card.classList.add('is-favorite');
                        // הוסף אייקון כוכב אם לא קיים
                        if (!card.querySelector('.favorite-indicator')) {
                            const star = document.createElement('span');
                            star.className = 'favorite-indicator';
                            star.innerHTML = '<i class="fas fa-star"></i>';
                            card.appendChild(star);
                        }
                    }
                });
                
                window.multiSelect.clearSelection();
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
    
    async removeFromFavorites() {
        const fileIds = window.multiSelect.getSelectedFiles().map(f => f.id);
        
        if (fileIds.length === 0) {
            this.showNotification('לא נבחרו קבצים', 'warning');
            return;
        }
        
        this.showProcessing(`מסיר ${fileIds.length} קבצים ממועדפים...`);
        
        try {
            const response = await fetch('/api/files/bulk-unfavorite', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ file_ids: fileIds })
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.showNotification(
                    `${result.updated} קבצים הוסרו ממועדפים`,
                    'success'
                );
                
                // עדכן UI
                fileIds.forEach(id => {
                    const card = document.querySelector(`.file-card[data-file-id="${id}"]`);
                    if (card) {
                        card.classList.remove('is-favorite');
                        const star = card.querySelector('.favorite-indicator');
                        if (star) star.remove();
                    }
                });
                
                window.multiSelect.clearSelection();
            }
        } catch (error) {
            console.error('Error removing from favorites:', error);
            this.showNotification('שגיאה בהסרה ממועדפים', 'error');
        } finally {
            this.hideProcessing();
        }
    }
    
    async addTags() {
        const fileIds = window.multiSelect.getSelectedFiles().map(f => f.id);
        
        if (fileIds.length === 0) {
            this.showNotification('לא נבחרו קבצים', 'warning');
            return;
        }
        
        // הצג דיאלוג להזנת תגיות
        const tags = await this.showTagDialog();
        if (!tags || tags.length === 0) return;
        
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
                this.showNotification(
                    `תגיות נוספו ל-${result.updated} קבצים`,
                    'success',
                    { icon: 'tags' }
                );
                
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
        const files = window.multiSelect.getSelectedFiles();
        
        if (files.length === 0) {
            this.showNotification('לא נבחרו קבצים', 'warning');
            return;
        }
        
        const fileIds = files.map(f => f.id);
        const totalSize = files.length;
        
        this.showProcessing(`יוצר ZIP עם ${totalSize} קבצים...`, true);
        
        try {
            // סימולציית התקדמות בזמן היצירה
            let progress = 0;
            const progressInterval = setInterval(() => {
                progress += Math.random() * 15;
                if (progress > 90) progress = 90;
                this.updateProgress(progress);
            }, 200);
            
            const response = await fetch('/api/files/create-zip', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ file_ids: fileIds })
            });
            
            clearInterval(progressInterval);
            this.updateProgress(100);
            
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
            
            // שם קובץ עם תאריך ושעה
            const now = new Date();
            const timestamp = now.toISOString().replace(/[:.]/g, '-').slice(0, -5);
            a.download = `code_files_${timestamp}.zip`;
            
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
            
            this.showNotification(
                'קובץ ZIP הורד בהצלחה',
                'success',
                { icon: 'download', duration: 5000 }
            );
            
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
            
            // פונקציות מקומיות - לא על window!
            const cleanup = () => {
                // הסר event listeners
                if (input) {
                    input.removeEventListener('keyup', handleKeyup);
                }
                dialog.removeEventListener('click', handleOverlayClick);
                
                // הסר את הדיאלוג מה-DOM
                if (dialog.parentNode) {
                    dialog.parentNode.removeChild(dialog);
                }
            };
            
            const addSuggestedTag = (tag) => {
                const input = dialog.querySelector('#tagInput');
                if (!input) return;
                
                const currentTags = input.value.split(',').map(t => t.trim()).filter(t => t);
                if (!currentTags.includes(tag)) {
                    if (input.value && !input.value.endsWith(',')) {
                        input.value += ', ';
                    }
                    input.value += tag;
                    input.focus();
                }
            };
            
            const confirmTags = () => {
                const input = dialog.querySelector('#tagInput');
                const tags = input ? input.value
                    .split(',')
                    .map(t => t.trim())
                    .filter(t => t.length > 0) : [];
                cleanup();
                resolve(tags);
            };
            
            const cancelTags = () => {
                cleanup();
                resolve(null);
            };
            
            // Event handlers
            const handleKeyup = (e) => {
                if (e.key === 'Enter') {
                    confirmTags();
                } else if (e.key === 'Escape') {
                    cancelTags();
                }
            };
            
            const handleOverlayClick = (e) => {
                if (e.target === dialog) {
                    cancelTags();
                }
            };
            
            // בניית ה-HTML
            dialog.innerHTML = `
                <div class="modal-content">
                    <div class="modal-header">
                        <h3><i class="fas fa-tags"></i> הוסף תגיות</h3>
                        <button class="modal-close" data-action="cancel">
                            <i class="fas fa-times"></i>
                        </button>
                    </div>
                    
                    <div class="modal-body">
                        <p>הזן תגיות מופרדות בפסיקים:</p>
                        <input type="text" 
                               id="tagInput" 
                               class="tag-input" 
                               placeholder="למשל: python, utils, important"
                               autofocus>
                        
                        <div class="tag-suggestions">
                            <span class="suggestion-label">הצעות:</span>
                            <button class="tag-suggestion" data-tag="important">important</button>
                            <button class="tag-suggestion" data-tag="todo">todo</button>
                            <button class="tag-suggestion" data-tag="refactor">refactor</button>
                            <button class="tag-suggestion" data-tag="test">test</button>
                            <button class="tag-suggestion" data-tag="docs">docs</button>
                        </div>
                    </div>
                    
                    <div class="modal-footer">
                        <button class="btn btn-primary" data-action="confirm">
                            <i class="fas fa-check"></i> אישור
                        </button>
                        <button class="btn btn-secondary" data-action="cancel">
                            <i class="fas fa-times"></i> ביטול
                        </button>
                    </div>
                </div>
            `;
            
            // חיבור event delegation לכפתורים
            dialog.addEventListener('click', (e) => {
                const action = e.target.closest('[data-action]');
                if (action) {
                    const actionType = action.dataset.action;
                    if (actionType === 'confirm') {
                        confirmTags();
                    } else if (actionType === 'cancel') {
                        cancelTags();
                    }
                }
                
                const tagBtn = e.target.closest('[data-tag]');
                if (tagBtn) {
                    addSuggestedTag(tagBtn.dataset.tag);
                }
            });
            
            document.body.appendChild(dialog);
            
            // קבלת reference ל-input
            const input = dialog.querySelector('#tagInput');
            if (input) {
                input.focus();
                input.addEventListener('keyup', handleKeyup);
            }
            
            // סגירה בלחיצה על הרקע
            dialog.addEventListener('click', handleOverlayClick);
        });
    }
    
    showNotification(message, type = 'info', options = {}) {
        const notification = document.createElement('div');
        notification.className = `notification ${type}`;
        
        // בחר אייקון לפי סוג
        let icon = 'info-circle';
        if (type === 'success') icon = options.icon || 'check-circle';
        else if (type === 'error') icon = 'exclamation-circle';
        else if (type === 'warning') icon = 'exclamation-triangle';
        
        notification.innerHTML = `
            <div class="notification-content">
                <i class="fas fa-${icon}"></i>
                <span>${message}</span>
            </div>
            <button class="notification-close">
                <i class="fas fa-times"></i>
            </button>
        `;
        
        // כפתור סגירה
        const closeBtn = notification.querySelector('.notification-close');
        closeBtn.addEventListener('click', () => {
            notification.classList.add('fade-out');
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.parentNode.removeChild(notification);
                }
            }, 300);
        });
        
        this.notificationContainer.appendChild(notification);
        
        // אנימציית כניסה
        setTimeout(() => notification.classList.add('show'), 10);
        
        // הסרה אוטומטית
        const duration = options.duration || 3000;
        setTimeout(() => {
            if (notification.parentNode) {
                notification.classList.add('fade-out');
                setTimeout(() => {
                    if (notification.parentNode) {
                        notification.parentNode.removeChild(notification);
                    }
                }, 300);
            }
        }, duration);
    }
    
    async shareFiles() {
        const fileIds = window.multiSelect.getSelectedFiles().map(f => f.id);
        
        if (fileIds.length === 0) {
            this.showNotification('לא נבחרו קבצים', 'warning');
            return;
        }
        
        this.showProcessing('יוצר קישור שיתוף...');
        
        try {
            const response = await fetch('/api/files/create-share-link', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ file_ids: fileIds })
            });
            
            const result = await response.json();
            
            if (result.success && result.share_url) {
                // העתק לקליפבורד
                await navigator.clipboard.writeText(result.share_url);
                
                this.showNotification(
                    'קישור השיתוף הועתק ללוח',
                    'success',
                    { icon: 'share-alt', duration: 5000 }
                );
                
                // הצג את הקישור בדיאלוג
                this.showShareDialog(result.share_url, result.expires_at);
            }
        } catch (error) {
            console.error('Error creating share link:', error);
            this.showNotification('שגיאה ביצירת קישור שיתוף', 'error');
        } finally {
            this.hideProcessing();
        }
    }
    
    showShareDialog(shareUrl, expiresAt) {
        const dialog = document.createElement('div');
        dialog.className = 'modal-overlay';
        dialog.innerHTML = `
            <div class="modal-content">
                <div class="modal-header">
                    <h3><i class="fas fa-share-alt"></i> קישור שיתוף נוצר</h3>
                </div>
                
                <div class="modal-body">
                    <p>הקישור הועתק ללוח:</p>
                    <div class="share-link-container">
                        <input type="text" 
                               value="${shareUrl}" 
                               class="share-link-input" 
                               readonly>
                        <button class="btn btn-icon" onclick="navigator.clipboard.writeText('${shareUrl}')">
                            <i class="fas fa-copy"></i>
                        </button>
                    </div>
                    ${expiresAt ? `<p class="expiry-note">הקישור יפוג ב: ${new Date(expiresAt).toLocaleDateString('he-IL')}</p>` : ''}
                </div>
                
                <div class="modal-footer">
                    <button class="btn btn-primary" onclick="this.parentElement.parentElement.parentElement.remove()">
                        <i class="fas fa-check"></i> סגור
                    </button>
                </div>
            </div>
        `;
        
        document.body.appendChild(dialog);
        
        // סגירה בלחיצה מחוץ
        dialog.addEventListener('click', (e) => {
            if (e.target === dialog) {
                dialog.remove();
            }
        });
    }
}

// יצירת instance גלובלי
window.bulkActions = new BulkActions();

// חיבור לכפתורים בסרגל הכלים
window.bulkAddToFavorites = () => window.bulkActions.addToFavorites();
window.bulkRemoveFromFavorites = () => window.bulkActions.removeFromFavorites();
window.showBulkTagDialog = () => window.bulkActions.addTags();
window.bulkDownloadZip = () => window.bulkActions.downloadZip();
window.bulkShareFiles = () => window.bulkActions.shareFiles();
window.clearSelection = () => window.multiSelect?.clearSelection();