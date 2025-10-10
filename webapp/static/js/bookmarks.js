/**
 * Bookmarks Manager for WebApp
 * מערכת ניהול סימניות מלאה לקבצי קוד
 */

class BookmarkManager {
    constructor(fileId) {
        this.fileId = fileId;
        this.bookmarks = new Map();
        this.api = new BookmarkAPI(fileId);
        this.ui = new BookmarkUI();
        this.offline = new OfflineBookmarkManager();
        this.syncChecker = new SyncChecker(fileId);
        
        this.init();
    }
    
    async init() {
        try {
            // טען סימניות קיימות
            await this.loadBookmarks();
            
            // הגדר event delegation
            this.setupEventDelegation();
            
            // הגדר keyboard shortcuts
            this.setupKeyboardShortcuts();
            
            // התחל בדיקת סנכרון
            this.syncChecker.startMonitoring();
            
            // סנכרן offline bookmarks
            await this.offline.syncPending();
            
            console.log('BookmarkManager initialized successfully');
            
        } catch (error) {
            console.error('Error initializing BookmarkManager:', error);
            this.ui.showError('שגיאה באתחול מערכת הסימניות');
        }
    }
    
    setupEventDelegation() {
        // Event delegation לקוד – מאזינים למכולה העוטפת את כל ה-highlight
        // כך שנתפוס גם קליקים על מספרי שורות (שהם לעתים אחים של הקוד ולא צאצאים שלו)
        const codeContainer = document.querySelector('#codeCard .code-container')
            || document.querySelector('.highlighttable')
            || document.querySelector('.highlight');
        if (codeContainer) {
            codeContainer.addEventListener('click', (e) => this.handleCodeClick(e));
            codeContainer.addEventListener('mouseover', (e) => this.handleCodeHover(e));
        }
        
        // Event delegation לפאנל
        const panel = document.getElementById('bookmarksPanel');
        if (panel) {
            panel.addEventListener('click', (e) => this.handlePanelClick(e));
        }
        
        // כפתור toggle פאנל
        const toggleBtn = document.getElementById('toggleBookmarksBtn');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', () => this.ui.togglePanel());
        }
    }
    
    setupKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            // Ctrl/Cmd + B - toggle bookmark
            if ((e.ctrlKey || e.metaKey) && e.key === 'b') {
                e.preventDefault();
                const currentLine = this.getCurrentLineFromSelection();
                if (currentLine) {
                    this.toggleBookmark(currentLine);
                }
            }
            
            // Ctrl/Cmd + Shift + B - toggle panel
            if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'B') {
                e.preventDefault();
                this.ui.togglePanel();
            }
            
            // Escape - סגור פאנל
            if (e.key === 'Escape' && this.ui.isPanelOpen()) {
                this.ui.closePanel();
            }
        });
    }
    
    async handleCodeClick(event) {
        // תמיכה בשני פורמטי Pygments: highlighttable (td.linenos) ו-linenodiv
        const lineNumEl = event.target.closest(
            '.highlighttable .linenos pre > span, .linenodiv pre > span, .linenos a, .linenodiv a, .linenos span'
        );
        if (!lineNumEl) return;
        
        event.preventDefault();
        event.stopPropagation();
        
        const lineNumber = this.extractLineNumber(lineNumEl);
        if (!lineNumber) return;
        
        // Shift+Click = הוסף/ערוך הערה
        if (event.shiftKey) {
            await this.promptForNote(lineNumber);
        }
        // Ctrl/Cmd+Click = מחק סימנייה
        else if (event.ctrlKey || event.metaKey) {
            if (this.bookmarks.has(lineNumber)) {
                await this.deleteBookmark(lineNumber);
            }
        }
        // Click רגיל = toggle
        else {
            await this.toggleBookmark(lineNumber);
        }
    }
    
    handleCodeHover(event) {
        const lineNumEl = event.target.closest(
            '.highlighttable .linenos pre > span, .linenodiv pre > span, .linenos a, .linenodiv a, .linenos span'
        );
        if (!lineNumEl) return;
        
        const lineNumber = this.extractLineNumber(lineNumEl);
        if (!lineNumber) return;
        
        // הצג tooltip אם יש סימנייה
        if (this.bookmarks.has(lineNumber)) {
            const bookmark = this.bookmarks.get(lineNumber);
            if (bookmark.note) {
                this.ui.showTooltip(lineNumEl, bookmark.note);
            }
        }
    }
    
    async handlePanelClick(event) {
        // לחיצה על סימנייה
        const bookmarkItem = event.target.closest('.bookmark-item');
        if (bookmarkItem) {
            const lineNumber = parseInt(bookmarkItem.dataset.lineNumber);
            // בחירת צבע
            const swatch = event.target.closest('.color-swatch');
            if (swatch) {
                event.stopPropagation();
                const color = swatch.dataset.color;
                try {
                    // Optimistic UI: עדכן מיד
                    this.ui.setBookmarkColor(lineNumber, color);
                    const result = await this.api.updateColor(lineNumber, color);
                    if (result.ok) {
                        const bm = this.bookmarks.get(lineNumber);
                        if (bm) {
                            bm.color = color;
                            this.bookmarks.set(lineNumber, bm);
                        }
                        this.ui.refreshPanel(Array.from(this.bookmarks.values()));
                        this.ui.showNotification('הצבע עודכן', 'success');
                    } else {
                        throw new Error(result.error || 'שגיאה בעדכון צבע');
                    }
                } catch (e) {
                    this.ui.showError('שגיאה בעדכון צבע');
                }
                return;
            }
            
            // לחיצה על כפתור מחיקה
            if (event.target.closest('.delete-btn')) {
                event.stopPropagation();
                await this.deleteBookmark(lineNumber);
                return;
            }
            
            // לחיצה על כפתור עריכה
            if (event.target.closest('.edit-btn')) {
                event.stopPropagation();
                await this.promptForNote(lineNumber);
                return;
            }
            
            // לחיצה על הסימנייה - גלול לשורה
            this.scrollToLine(lineNumber);
        }
        
        // כפתור ניקוי כל הסימניות
        if (event.target.closest('#clearAllBookmarks')) {
            if (confirm('האם למחוק את כל הסימניות בקובץ זה?')) {
                await this.clearAllBookmarks();
            }
        }
        
        // כפתור ייצוא
        if (event.target.closest('#exportBookmarks')) {
            this.exportBookmarks();
        }
    }
    
    async toggleBookmark(lineNumber) {
        try {
            // הצג loading ו-Optimistic UI
            this.ui.showLineLoading(lineNumber, true);
            const lineText = this.getLineText(lineNumber);

            const currentlyBookmarked = this.bookmarks.has(lineNumber);
            if (!currentlyBookmarked) {
                this.ui.addBookmarkIndicator(lineNumber);
            } else {
                this.ui.removeBookmarkIndicator(lineNumber);
            }

            // שלח לשרת
            const result = await this.api.toggleBookmark(lineNumber, lineText);

            if (result.ok) {
                if (result.action === 'added') {
                    this.bookmarks.set(lineNumber, result.bookmark);
                    this.ui.addBookmarkIndicator(lineNumber, result.bookmark?.color);
                    this.ui.showNotification('סימנייה נוספה', 'success');
                } else if (result.action === 'removed') {
                    this.bookmarks.delete(lineNumber);
                    this.ui.showNotification('סימנייה הוסרה', 'info');
                }
                this.ui.updateCount(this.bookmarks.size);
                this.ui.refreshPanel(Array.from(this.bookmarks.values()));
            } else {
                // החזר מצב במקרה של כשל
                if (!currentlyBookmarked) {
                    this.ui.removeBookmarkIndicator(lineNumber);
                } else {
                    this.ui.addBookmarkIndicator(lineNumber);
                }
                throw new Error(result.error || 'שגיאה בשמירת הסימנייה');
            }
            
        } catch (error) {
            console.error('Toggle bookmark error:', error);
            
            // נסה offline
            if (!navigator.onLine) {
                await this.offline.saveBookmark(this.fileId, lineNumber);
                this.ui.showNotification('שמור מקומית - יסונכרן מאוחר יותר', 'warning');
            } else {
                this.ui.showError(error.message);
            }
            
        } finally {
            this.ui.showLineLoading(lineNumber, false);
        }
    }
    
    async deleteBookmark(lineNumber) {
        try {
            const result = await this.api.deleteBookmark(lineNumber);
            
            if (result.ok) {
                this.bookmarks.delete(lineNumber);
                this.ui.removeBookmarkIndicator(lineNumber);
                this.ui.updateCount(this.bookmarks.size);
                this.ui.refreshPanel(Array.from(this.bookmarks.values()));
                this.ui.showNotification('סימנייה נמחקה', 'info');
            }
            
        } catch (error) {
            this.ui.showError('שגיאה במחיקת הסימנייה');
        }
    }
    
    async promptForNote(lineNumber) {
        const existingNote = this.bookmarks.get(lineNumber)?.note || '';
        const note = prompt('הוסף/ערוך הערה לסימנייה:', existingNote);
        
        if (note === null) return; // ביטול
        
        try {
            if (!this.bookmarks.has(lineNumber)) {
                // צור סימנייה חדשה עם הערה
                const lineText = this.getLineText(lineNumber);
                const result = await this.api.toggleBookmark(lineNumber, lineText, note);
                
                if (result.ok && result.action === 'added') {
                    this.bookmarks.set(lineNumber, result.bookmark);
                    this.ui.addBookmarkIndicator(lineNumber, result.bookmark?.color);
                }
            } else {
                // עדכן הערה קיימת
                const result = await this.api.updateNote(lineNumber, note);
                
                if (result.ok) {
                    const bookmark = this.bookmarks.get(lineNumber);
                    bookmark.note = note;
                    this.bookmarks.set(lineNumber, bookmark);
                }
            }
            
            this.ui.refreshPanel(Array.from(this.bookmarks.values()));
            this.ui.showNotification('ההערה נשמרה', 'success');
            
        } catch (error) {
            this.ui.showError('שגיאה בשמירת ההערה');
        }
    }
    
    async clearAllBookmarks() {
        try {
            const result = await this.api.clearFileBookmarks();
            
            if (result.ok) {
                this.bookmarks.clear();
                this.ui.clearAllIndicators();
                this.ui.updateCount(0);
                this.ui.refreshPanel([]);
                this.ui.showNotification(`${result.deleted} סימניות נמחקו`, 'info');
            }
            
        } catch (error) {
            this.ui.showError('שגיאה במחיקת הסימניות');
        }
    }
    
    async loadBookmarks() {
        try {
            const result = await this.api.getFileBookmarks();
            
            if (result.ok) {
                result.bookmarks.forEach(bm => {
                    this.bookmarks.set(bm.line_number, bm);
                    this.ui.addBookmarkIndicator(bm.line_number, bm.color || 'yellow');
                });
                
                this.ui.updateCount(this.bookmarks.size);
                this.ui.refreshPanel(result.bookmarks);
            }
            
        } catch (error) {
            console.error('Error loading bookmarks:', error);
            
            // טען מ-cache אם יש
            const cached = this.offline.getCachedBookmarks(this.fileId);
            if (cached.length > 0) {
                cached.forEach(bm => {
                    this.bookmarks.set(bm.line_number, bm);
                    this.ui.addBookmarkIndicator(bm.line_number);
                });
                
                this.ui.showNotification('טעינה ממטמון מקומי', 'warning');
            }
        }
    }
    
    scrollToLine(lineNumber) {
        const lineElement = document.querySelector(
            `.highlighttable .linenos pre > span:nth-child(${lineNumber}), .highlighttable .linenos pre > a:nth-child(${lineNumber}), .linenodiv pre > span:nth-child(${lineNumber}), .linenodiv pre > a:nth-child(${lineNumber}), .linenos span:nth-child(${lineNumber}), .linenos a:nth-child(${lineNumber})`
        );
        
        if (lineElement) {
            lineElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
            
            // הדגש את השורה
            this.ui.highlightLine(lineNumber);
        }
    }
    
    getLineText(lineNumber) {
        const codeLines = document.querySelectorAll('.code pre > span, .highlight pre > span');
        
        if (codeLines[lineNumber - 1]) {
            return codeLines[lineNumber - 1].textContent.trim().substring(0, 100);
        }
        
        return '';
    }
    
    extractLineNumber(element) {
        // נסה לקבל מ-text content
        const text = element.textContent.trim();
        const num = parseInt(text);
        if (num > 0) return num;
        
        // נסה לקבל מ-href (לפורמט #L123)
        const href = element.getAttribute('href');
        if (href) {
            // נזהר מהתאמות-יתר: נוודא שהמספר מופיע בסוף העוגן או אחרי קידומת ידועה
            // תחילה: #L123 או #line-123/#line123
            let m = href.match(/#(?:L|line-?)(\d+)$/i);
            // תאימות לאחור: #123 כשהוא בסוף (ולא #version2 וכד')
            if (!m) m = href.match(/#(\d+)$/);
            if (m) return parseInt(m[1]);
        }
        
        // נסה לקבל מ-index
        const parent = element.parentElement;
        if (parent) {
            const index = Array.from(parent.children).indexOf(element);
            if (index >= 0) return index + 1;
        }
        
        return null;
    }
    
    getCurrentLineFromSelection() {
        const selection = window.getSelection();
        if (!selection.rangeCount) return null;
        
        const range = selection.getRangeAt(0);
        const container = range.commonAncestorContainer;
        
        // חפש את השורה הקרובה ביותר
        let element = container.nodeType === 3 ? container.parentElement : container;
        
        while (element) {
            const lineNum = element.querySelector('.linenos span, .linenodiv a');
            if (lineNum) {
                return this.extractLineNumber(lineNum);
            }
            element = element.parentElement;
        }
        
        return null;
    }
    
    exportBookmarks() {
        const data = {
            file_id: this.fileId,
            file_name: document.title,
            bookmarks: Array.from(this.bookmarks.values()),
            exported_at: new Date().toISOString()
        };
        
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        
        const a = document.createElement('a');
        a.href = url;
        a.download = `bookmarks_${this.fileId}_${Date.now()}.json`;
        a.click();
        
        URL.revokeObjectURL(url);
        this.ui.showNotification('הסימניות יוצאו בהצלחה', 'success');
    }
}

// ==================== BookmarkAPI Class ====================

class BookmarkAPI {
    constructor(fileId) {
        this.fileId = fileId;
        this.baseUrl = '/api/bookmarks';
        this.maxRetries = 3;
        this.retryDelay = 1000;
    }
    
    async toggleBookmark(lineNumber, lineText = '', note = '') {
        return this.retryableRequest('POST', `/${this.fileId}/toggle`, {
            line_number: lineNumber,
            line_text: lineText,
            note: note
        });
    }
    
    async getFileBookmarks() {
        return this.retryableRequest('GET', `/${this.fileId}`);
    }
    
    async updateNote(lineNumber, note) {
        return this.retryableRequest('PUT', `/${this.fileId}/${lineNumber}/note`, {
            note: note
        });
    }
    
    async updateColor(lineNumber, color) {
        return this.retryableRequest('PUT', `/${this.fileId}/${lineNumber}/color`, {
            color
        });
    }
    
    async deleteBookmark(lineNumber) {
        return this.retryableRequest('DELETE', `/${this.fileId}/${lineNumber}`);
    }
    
    async clearFileBookmarks() {
        return this.retryableRequest('DELETE', `/${this.fileId}/clear`);
    }
    
    async retryableRequest(method, path, body = null) {
        let lastError;
        
        for (let attempt = 1; attempt <= this.maxRetries; attempt++) {
            try {
                const options = {
                    method: method,
                    headers: {
                        'Content-Type': 'application/json'
                    }
                };
                
                if (body && method !== 'GET') {
                    options.body = JSON.stringify(body);
                }
                
                const response = await fetch(this.baseUrl + path, options);
                
                if (!response.ok) {
                    if (response.status === 429) {
                        // Rate limiting
                        const retryAfter = response.headers.get('Retry-After') || 60;
                        throw new Error(`Rate limited. Try again in ${retryAfter} seconds`);
                    }
                    
                    if (response.status >= 500 && attempt < this.maxRetries) {
                        // Server error - retry
                        await this.sleep(this.retryDelay * attempt);
                        continue;
                    }
                    
                    const errorData = await response.json();
                    throw new Error(errorData.error || 'Request failed');
                }
                
                return await response.json();
                
            } catch (error) {
                lastError = error;
                
                if (attempt < this.maxRetries && !error.message.includes('Rate limited')) {
                    await this.sleep(this.retryDelay * attempt);
                    continue;
                }
            }
        }
        
        throw lastError || new Error('Request failed after retries');
    }
    
    sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
}

// ==================== BookmarkUI Class ====================

class BookmarkUI {
    constructor() {
        this.panel = document.getElementById('bookmarksPanel');
        this.countBadge = document.getElementById('bookmarkCount');
        this.notificationContainer = this.createNotificationContainer();
        this.maybeShowFirstRunHint();
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
    
    showNotification(message, type = 'info') {
        const notification = document.createElement('div');
        notification.className = `notification notification-${type}`;
        notification.innerHTML = `
            <span class="notification-icon">${this.getNotificationIcon(type)}</span>
            <span class="notification-message">${this.escapeHtml(message)}</span>
        `;
        
        this.notificationContainer.appendChild(notification);
        
        // אנימציית כניסה
        setTimeout(() => notification.classList.add('show'), 10);
        
        // הסרה אוטומטית (4 שניות)
        setTimeout(() => {
            notification.classList.remove('show');
            setTimeout(() => notification.remove(), 300);
        }, 4000);
    }
    
    showError(message) {
        this.showNotification(message, 'error');
    }

    maybeShowFirstRunHint() {
        try {
            const KEY = 'bookmarks_first_run_hint_shown';
            if (localStorage.getItem(KEY) === '1') return;
            this.showNotification('טיפ: לחץ על מספר שורה כדי להוסיף סימנייה. לחץ שוב להסרה.', 'info');
            localStorage.setItem(KEY, '1');
        } catch (_) {
            // ignore storage errors
        }
    }
    
    getNotificationIcon(type) {
        const icons = {
            'success': '✓',
            'error': '✕',
            'warning': '⚠',
            'info': 'ℹ'
        };
        return icons[type] || icons['info'];
    }
    
    addBookmarkIndicator(lineNumber, color = 'yellow') {
        const lineElement = document.querySelector(
            `.highlighttable .linenos pre > span:nth-child(${lineNumber}), .highlighttable .linenos pre > a:nth-child(${lineNumber}), .linenodiv pre > span:nth-child(${lineNumber}), .linenodiv pre > a:nth-child(${lineNumber}), .linenos span:nth-child(${lineNumber}), .linenos a:nth-child(${lineNumber})`
        );
        
        if (!lineElement) return;
        lineElement.classList.add('bookmarked');
        lineElement.setAttribute('data-bookmark-color', color);
        
        // הוסף אייקון אם חסר
        if (!lineElement.querySelector('.bookmark-icon')) {
            const icon = document.createElement('span');
            icon.className = 'bookmark-icon';
            icon.innerHTML = '🔖';
            lineElement.appendChild(icon);
        }
    }
    
    removeBookmarkIndicator(lineNumber) {
        const lineElement = document.querySelector(
            `.highlighttable .linenos pre > span:nth-child(${lineNumber}), .highlighttable .linenos pre > a:nth-child(${lineNumber}), .linenodiv pre > span:nth-child(${lineNumber}), .linenodiv pre > a:nth-child(${lineNumber}), .linenos span:nth-child(${lineNumber}), .linenos a:nth-child(${lineNumber})`
        );
        
        if (lineElement) {
            lineElement.classList.remove('bookmarked');
            lineElement.removeAttribute('data-bookmark-color');
            const icon = lineElement.querySelector('.bookmark-icon');
            if (icon) icon.remove();
        }
    }
    
    clearAllIndicators() {
        document.querySelectorAll('.bookmarked').forEach(el => {
            el.classList.remove('bookmarked');
            el.removeAttribute('data-bookmark-color');
            const icon = el.querySelector('.bookmark-icon');
            if (icon) icon.remove();
        });
    }
    
    updateCount(count) {
        if (this.countBadge) {
            this.countBadge.textContent = count;
            this.countBadge.style.display = count > 0 ? 'inline-block' : 'none';
        }
    }
    
    refreshPanel(bookmarks) {
        if (!this.panel) return;
        
        const listContainer = this.panel.querySelector('.bookmarks-list');
        if (!listContainer) return;
        
        if (bookmarks.length === 0) {
            listContainer.innerHTML = `
                <div class="empty-state">
                    <p>אין סימניות בקובץ זה</p>
                    <p>לחץ על מספר שורה כדי להוסיף סימנייה</p>
                </div>
            `;
            return;
        }
        
        // מיין לפי מספר שורה
        bookmarks.sort((a, b) => a.line_number - b.line_number);
        
        listContainer.innerHTML = bookmarks.map(bm => `
            <div class="bookmark-item" data-line-number="${bm.line_number}" data-color="${bm.color || 'yellow'}">
                <div class="bookmark-content">
                    <span class="line-number">שורה ${bm.line_number}</span>
                    <span class="line-preview">${this.escapeHtml(bm.line_text_preview || '')}</span>
                    ${bm.note ? `<span class="bookmark-note">${this.escapeHtml(bm.note)}</span>` : ''}
                </div>
                <div class="bookmark-actions">
                    <div class="color-picker" title="בחר צבע" aria-label="בחר צבע" style="display: inline-flex; gap: 4px; align-items: center; margin-inline-end: 6px;">
                        ${['yellow','red','green','blue','purple','orange','pink'].map(c => `
                            <button class="color-swatch" data-color="${c}" title="${c}" style="width:14px;height:14px;border-radius:50%;border:1px solid rgba(0,0,0,0.2);background: var(--bookmark-${c}); padding:0;"></button>
                        `).join('')}
                    </div>
                    <button class="edit-btn" title="ערוך הערה">✏️</button>
                    <button class="delete-btn" title="מחק סימנייה">🗑️</button>
                </div>
            </div>
        `).join('');
    }
    
    togglePanel() {
        if (this.panel) {
            this.panel.classList.toggle('open');
            
            // עדכן ARIA
            const toggleBtn = document.getElementById('toggleBookmarksBtn');
            if (toggleBtn) {
                const isOpen = this.panel.classList.contains('open');
                toggleBtn.setAttribute('aria-expanded', isOpen);
            }
        }
    }
    
    closePanel() {
        if (this.panel) {
            this.panel.classList.remove('open');
        }
    }
    
    isPanelOpen() {
        return this.panel && this.panel.classList.contains('open');
    }
    
    showLineLoading(lineNumber, show) {
        const lineElement = document.querySelector(
            `.highlighttable .linenos pre > span:nth-child(${lineNumber}), .highlighttable .linenos pre > a:nth-child(${lineNumber}), .linenodiv pre > span:nth-child(${lineNumber}), .linenodiv pre > a:nth-child(${lineNumber}), .linenos span:nth-child(${lineNumber}), .linenos a:nth-child(${lineNumber})`
        );
        
        if (lineElement) {
            if (show) {
                lineElement.classList.add('loading');
            } else {
                lineElement.classList.remove('loading');
            }
        }
    }
    
    highlightLine(lineNumber) {
        // הסר הדגשות קודמות
        document.querySelectorAll('.line-highlighted').forEach(el => {
            el.classList.remove('line-highlighted');
        });
        
        // הדגש את השורה החדשה
        const lineElement = document.querySelector(
            `.code pre > span:nth-child(${lineNumber}), .highlight pre > span:nth-child(${lineNumber})`
        );
        
        if (lineElement) {
            lineElement.classList.add('line-highlighted');
            
            // הסר הדגשה אחרי 2 שניות
            setTimeout(() => {
                lineElement.classList.remove('line-highlighted');
            }, 2000);
        }
    }

    setBookmarkColor(lineNumber, color) {
        const lineElement = document.querySelector(
            `.highlighttable .linenos pre > span:nth-child(${lineNumber}), .highlighttable .linenos pre > a:nth-child(${lineNumber}), .linenodiv pre > span:nth-child(${lineNumber}), .linenodiv pre > a:nth-child(${lineNumber}), .linenos span:nth-child(${lineNumber}), .linenos a:nth-child(${lineNumber})`
        );
        if (lineElement) {
            lineElement.setAttribute('data-bookmark-color', color);
        }
    }
    
    showTooltip(element, text) {
        // יצירת tooltip
        let tooltip = document.getElementById('bookmark-tooltip');
        if (!tooltip) {
            tooltip = document.createElement('div');
            tooltip.id = 'bookmark-tooltip';
            tooltip.className = 'bookmark-tooltip';
            document.body.appendChild(tooltip);
        }
        
        tooltip.textContent = text;
        tooltip.style.display = 'block';
        
        // מיקום
        const rect = element.getBoundingClientRect();
        tooltip.style.left = rect.right + 10 + 'px';
        tooltip.style.top = rect.top + 'px';
        
        // הסתרה בעזיבה
        element.addEventListener('mouseleave', () => {
            tooltip.style.display = 'none';
        }, { once: true });
    }
    
    escapeHtml(text) {
        const map = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;',
            '/': '&#x2F;'
        };
        return (text || '').replace(/[&<>"'/]/g, m => map[m]);
    }
}

// ==================== OfflineBookmarkManager Class ====================

class OfflineBookmarkManager {
    constructor() {
        this.STORAGE_KEY = 'pending_bookmarks';
        this.CACHE_KEY = 'cached_bookmarks';
        
        // סנכרן כשחוזרים online
        window.addEventListener('online', () => this.syncPending());
    }
    
    async saveBookmark(fileId, lineNumber, note = '') {
        const pending = this.getPending();
        const id = `${fileId}_${lineNumber}_${Date.now()}`;
        
        pending[id] = {
            fileId,
            lineNumber,
            note,
            timestamp: Date.now()
        };
        
        localStorage.setItem(this.STORAGE_KEY, JSON.stringify(pending));
        return true;
    }
    
    async syncPending() {
        if (!navigator.onLine) return;
        
        const pending = this.getPending();
        const failed = {};
        
        for (const [id, bookmark] of Object.entries(pending)) {
            try {
                const api = new BookmarkAPI(bookmark.fileId);
                await api.toggleBookmark(bookmark.lineNumber, '', bookmark.note);
                console.log(`Synced offline bookmark: ${id}`);
            } catch (error) {
                console.error(`Failed to sync ${id}:`, error);
                failed[id] = bookmark;
            }
        }
        
        // שמור רק את מה שנכשל
        if (Object.keys(failed).length > 0) {
            localStorage.setItem(this.STORAGE_KEY, JSON.stringify(failed));
        } else {
            localStorage.removeItem(this.STORAGE_KEY);
        }
    }
    
    getPending() {
        const stored = localStorage.getItem(this.STORAGE_KEY);
        return stored ? JSON.parse(stored) : {};
    }
    
    cacheBookmarks(fileId, bookmarks) {
        const cache = this.getCache();
        cache[fileId] = {
            bookmarks,
            timestamp: Date.now()
        };
        localStorage.setItem(this.CACHE_KEY, JSON.stringify(cache));
    }
    
    getCachedBookmarks(fileId) {
        const cache = this.getCache();
        const fileCache = cache[fileId];
        
        if (fileCache) {
            // בדוק אם המטמון לא ישן מדי (24 שעות)
            const age = Date.now() - fileCache.timestamp;
            if (age < 24 * 60 * 60 * 1000) {
                return fileCache.bookmarks;
            }
        }
        
        return [];
    }
    
    getCache() {
        const stored = localStorage.getItem(this.CACHE_KEY);
        return stored ? JSON.parse(stored) : {};
    }
}

// ==================== SyncChecker Class ====================

class SyncChecker {
    constructor(fileId) {
        this.fileId = fileId;
        this.checkInterval = 60000; // דקה
        this.intervalId = null;
    }
    
    startMonitoring() {
        // בדוק כל דקה אם הקובץ השתנה
        this.intervalId = setInterval(() => this.checkSync(), this.checkInterval);
    }
    
    stopMonitoring() {
        if (this.intervalId) {
            clearInterval(this.intervalId);
            this.intervalId = null;
        }
    }
    
    async checkSync() {
        // TODO: implement sync checking with server
        // This would check if the file content changed and update bookmarks accordingly
    }
}

// ==================== אתחול ====================

document.addEventListener('DOMContentLoaded', () => {
    // קבל את ה-file ID
    const fileIdElement = document.getElementById('fileId');
    const fileId = fileIdElement ? fileIdElement.value : null;
    
    if (fileId) {
        // צור את מנהל הסימניות
        window.bookmarkManager = new BookmarkManager(fileId);
        console.log('Bookmarks system initialized for file:', fileId);
    } else {
        console.warn('No file ID found, bookmarks system not initialized');
    }
});
