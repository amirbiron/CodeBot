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
        this.defaultColor = 'yellow';
        
        this.init();
    }
    
    async init() {
        try {
            // טען העדפות משתמש (צבע ברירת מחדל)
            try {
                const prefs = await this.api.retryableRequest('GET', `/prefs`);
                if (prefs && prefs.ok && prefs.default_color) {
                    this.defaultColor = prefs.default_color;
                }
            } catch (_e) {}
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
            codeContainer.addEventListener('contextmenu', (e) => this.handleCodeClick(e));
            codeContainer.addEventListener('mouseover', (e) => this.handleCodeHover(e));
        }
        // תמיכה בתצוגת Markdown: הוספת סימנייה על כותרות עם id
        const mdContainer = document.getElementById('md-content');
        if (mdContainer) {
            mdContainer.addEventListener('click', (e) => this.handleMarkdownClick(e));
            mdContainer.addEventListener('contextmenu', (e) => this.handleMarkdownClick(e));
        }
        
        // Event delegation לפאנל
        const panel = document.getElementById('bookmarksPanel');
        if (panel) {
            panel.addEventListener('click', (e) => this.handlePanelClick(e));
        }
        // שינוי צבע ברירת מחדל מהכותרת
        const headerPicker = document.querySelector('.bookmarks-panel-header .color-picker');
        if (headerPicker) {
            headerPicker.addEventListener('click', async (e) => {
                const btn = e.target.closest('[data-default-color]');
                if (!btn) return;
                const color = btn.getAttribute('data-default-color');
                try {
                    await this.api.retryableRequest('PUT', `/prefs`, { default_color: color });
                    this.defaultColor = color;
                    this.ui.showNotification('צבע ברירת מחדל עודכן', 'success');
                } catch (_) {
                    this.ui.showError('שגיאה בעדכון ברירת מחדל');
                }
            });
        }
        
        // כפתור toggle פאנל
        const toggleBtn = document.getElementById('toggleBookmarksBtn');
        if (toggleBtn) {
            // לחיצה רגילה – פתח/סגור פאנל
            toggleBtn.addEventListener('click', (e) => {
                if (this.ui.isDraggingToggle) { e.preventDefault(); e.stopPropagation(); return; }
                if (this.ui.justFinishedDrag) { e.preventDefault(); e.stopPropagation(); this.ui.justFinishedDrag = false; return; }
                // לחיצה רגילה משחזרת מגודל mini לגודל רגיל (אם קיים) ופותחת/סוגרת פאנל
                this.ui.setToggleMini(false);
                this.ui.togglePanel();
            });

            // תמיכה בגרירה בלחיצה ממושכת
            this.ui.enableToggleDrag(toggleBtn);
        }

        // כפתור הצגה/הסתרה של כפתור הסימנייה מתוך הפאנל
        const visibilityBtn = document.getElementById('toggleBtnVisibility');
        if (visibilityBtn) {
            const updateLabel = () => this.ui.updateVisibilityControlLabel();
            visibilityBtn.addEventListener('click', () => {
                this.ui.toggleToggleButtonVisibility();
                updateLabel();
            });
            // סנכרון מצב התווית בעת הטעינה
            updateLabel();
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
        // קליק ימני/תפריט הקשר: בחר צבע
        else if (event.button === 2 || event.type === 'contextmenu') {
            event.preventDefault();
            this.ui.showInlineColorMenu(lineNumEl, (color) => {
                // אם אין סימנייה – צור אותה עם הצבע שנבחר, באותה בקשה
                if (!this.bookmarks.has(lineNumber)) {
                    this.ui.showLineLoading(lineNumber, true);
                    const lineText = this.getLineText(lineNumber);
                    this.api.toggleBookmark(lineNumber, lineText, '', color)
                        .then((result) => {
                            if (result && result.ok && result.action === 'added') {
                                this.bookmarks.set(lineNumber, result.bookmark);
                                this.ui.addBookmarkIndicator(lineNumber, color);
                                this.ui.updateCount(this.bookmarks.size);
                                this.ui.refreshPanel(Array.from(this.bookmarks.values()));
                                this.ui.showNotification('סימנייה נוספה', 'success');
                            } else if (result && result.error) {
                                this.ui.showError(result.error);
                            }
                        })
                        .catch(() => this.ui.showError('שגיאה בשמירת הסימנייה'))
                        .finally(() => this.ui.showLineLoading(lineNumber, false));
                } else {
                    // אחרת, עדכן צבע בבקשה יעודית
                    this.api.updateColor(lineNumber, color)
                        .then(() => {
                            const bm = this.bookmarks.get(lineNumber);
                            if (bm) { bm.color = color; this.ui.setBookmarkColor(lineNumber, color); }
                            this.ui.refreshPanel(Array.from(this.bookmarks.values()));
                            this.ui.showNotification('הצבע עודכן', 'success');
                        })
                        .catch(() => this.ui.showError('שגיאה בעדכון צבע'));
                }
            });
        }
        // Click רגיל = toggle
        else {
            await this.toggleBookmark(lineNumber);
        }
    }

    async handleMarkdownClick(event) {
        // אם המשתמש כבר סימן טקסט – אל תפריע לתפריט המובנה (העתק/בחר הכל)
        try {
            const sel = window.getSelection && window.getSelection();
            if (sel && typeof sel.toString === 'function' && sel.toString().trim().length > 0) {
                return; // אפשר לתפריט/התנהגות ברירת מחדל לפעול
            }
        } catch (_) {}

        // לחיצה על כותרת H1..H6 בעלת id — סימון עוגן
        const heading = event.target.closest('#md-content h1[id], #md-content h2[id], #md-content h3[id], #md-content h4[id], #md-content h5[id], #md-content h6[id]');
        if (!heading) return;
        // נבלום ברירת מחדל רק כאשר אנו מבצעים פעולה ייעודית
        event.preventDefault();
        event.stopPropagation();
        const anchorId = heading.id || '';
        if (!anchorId) return;
        const anchorText = (heading.textContent || '').trim().substring(0, 200);
        const lineNumber = 0; // עוגן אינו תלוי מספר שורה

        // בחירת צבע דרך קליק ימני
        if (event.button === 2 || event.type === 'contextmenu') {
            // אם יש טקסט מסומן – אל תחליף את תפריט ההקשר
            try {
                const sel = window.getSelection && window.getSelection();
                if (sel && typeof sel.toString === 'function' && sel.toString().trim().length > 0) {
                    return;
                }
            } catch(_) {}
            this.ui.showInlineColorMenu(heading, (color) => {
                this.api.toggleBookmarkAnchor(anchorId, anchorText, 'md_heading', color)
                    .then((result) => {
                        if (result && result.ok) {
                            // עדכון מפה וזיהוי UI
                            const key = `a:${anchorId}`;
                            if (result.action === 'added') {
                                const bm = Object.assign({}, result.bookmark, { line_number: 0 });
                                this.bookmarks.set(key, bm);
                                this.ui.addAnchorIndicator(heading, color);
                                this.ui.showNotification('סימנייה נוספה לכותרת', 'success');
                            } else if (result.action === 'removed') {
                                this.bookmarks.delete(key);
                                this.ui.removeAnchorIndicator(heading);
                                this.ui.showNotification('סימנייה הוסרה', 'info');
                            }
                            this.ui.updateCount(this.getBookmarkCount());
                            this.ui.refreshPanel(Array.from(this.bookmarks.values()));
                        } else if (result && result.error) {
                            this.ui.showError(result.error);
                        }
                    })
                    .catch(() => this.ui.showError('שגיאה בשמירת הסימנייה'));
            });
            return;
        }

        // Shift+Click – הערה על העוגן
        if (event.shiftKey) {
            const note = prompt('הוסף/ערוך הערה לסימנייה (כותרת):', '');
            if (note === null) return;
            try {
                const result = await this.api.toggleBookmarkAnchor(anchorId, anchorText, 'md_heading', this.defaultColor, note);
                if (result.ok) {
                    const key = `a:${anchorId}`;
                    if (result.action === 'added') {
                        const bm = Object.assign({}, result.bookmark, { line_number: 0 });
                        this.bookmarks.set(key, bm);
                        this.ui.addAnchorIndicator(heading, result.bookmark?.color || this.defaultColor);
                    } else if (result.action === 'removed') {
                        this.bookmarks.delete(key);
                        this.ui.removeAnchorIndicator(heading);
                    }
                    this.ui.updateCount(this.getBookmarkCount());
                    this.ui.refreshPanel(Array.from(this.bookmarks.values()));
                } else {
                    this.ui.showError(result.error || 'שגיאה בשמירת הסימנייה');
                }
            } catch (_) {
                this.ui.showError('שגיאה בשמירת הסימנייה');
            }
            return;
        }

        // קליק רגיל – toggle עוגן
        try {
            const result = await this.api.toggleBookmarkAnchor(anchorId, anchorText, 'md_heading', this.defaultColor);
            const key = `a:${anchorId}`;
            if (result.ok) {
                if (result.action === 'added') {
                    const bm = Object.assign({}, result.bookmark, { line_number: 0 });
                    this.bookmarks.set(key, bm);
                    this.ui.addAnchorIndicator(heading, result.bookmark?.color || this.defaultColor);
                    this.ui.showNotification('סימנייה נוספה לכותרת', 'success');
                } else if (result.action === 'removed') {
                    this.bookmarks.delete(key);
                    this.ui.removeAnchorIndicator(heading);
                    this.ui.showNotification('סימנייה הוסרה', 'info');
                }
                this.ui.updateCount(this.getBookmarkCount());
                this.ui.refreshPanel(Array.from(this.bookmarks.values()));
            } else {
                this.ui.showError(result.error || 'שגיאה בשמירת הסימנייה');
            }
        } catch (e) {
            this.ui.showError('שגיאה בשמירת הסימנייה');
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
            const anchorId = bookmarkItem.dataset.anchorId || '';
            const lineNumber = parseInt(bookmarkItem.dataset.lineNumber || '0');
            // בחירת צבע
            const swatch = event.target.closest('.color-swatch');
            if (swatch) {
                event.stopPropagation();
                const color = swatch.dataset.color;
                try {
                    // Optimistic UI: עדכן מיד
                    if (anchorId) {
                        this.ui.setAnchorColor(anchorId, color);
                    } else {
                        this.ui.setBookmarkColor(lineNumber, color);
                    }
                    const result = anchorId
                        ? await this.api.updateColorAnchor(anchorId, color)
                        : await this.api.updateColor(lineNumber, color);
                    if (result.ok) {
                        const key = anchorId ? `a:${anchorId}` : lineNumber;
                        const bm = this.bookmarks.get(key);
                        if (bm) {
                            bm.color = color;
                            this.bookmarks.set(key, bm);
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
                if (anchorId) {
                    const result = await this.api.deleteBookmarkAnchor(anchorId);
                    if (result && result.ok) {
                        this.bookmarks.delete(`a:${anchorId}`);
                        this.ui.removeAnchorIndicatorById(anchorId);
                        this.ui.updateCount(this.getBookmarkCount());
                        this.ui.refreshPanel(Array.from(this.bookmarks.values()));
                        this.ui.showNotification('סימנייה נמחקה', 'info');
                    } else {
                        this.ui.showError('שגיאה במחיקת הסימנייה');
                    }
                } else {
                    await this.deleteBookmark(lineNumber);
                }
                return;
            }
            
            // לחיצה על כפתור עריכה
            if (event.target.closest('.edit-btn')) {
                event.stopPropagation();
                if (anchorId) {
                    const existingNote = (this.bookmarks.get(`a:${anchorId}`)?.note) || '';
                    const note = prompt('הוסף/ערוך הערה לסימנייה:', existingNote);
                    if (note === null) return;
                    try {
                        const result = await this.api.updateNoteAnchor(anchorId, note);
                        if (result && result.ok) {
                            const key = `a:${anchorId}`;
                            const bm = this.bookmarks.get(key);
                            if (bm) { bm.note = note; this.bookmarks.set(key, bm); }
                            this.ui.refreshPanel(Array.from(this.bookmarks.values()));
                            this.ui.showNotification('ההערה נשמרה', 'success');
                        } else {
                            this.ui.showError('שגיאה בשמירת ההערה');
                        }
                    } catch(_){ this.ui.showError('שגיאה בשמירת ההערה'); }
                } else {
                    await this.promptForNote(lineNumber);
                }
                return;
            }
            
            // לחיצה על הסימנייה - גלול לשורה/עוגן
            if (anchorId) {
                // נסה בעמוד הנוכחי (תצוגת MD) ע"פ anchorId
                let el = document.getElementById(anchorId);
                if (!el) {
                    // תצוגות ישנות/עוגנים לא תואמים – נסה למצוא לפי טקסט הכותרת
                    try {
                        const anchorText = bookmarkItem.dataset.anchorText || '';
                        if (anchorText) {
                            const normalize = (s) => (s || '').replace(/\u00b6|¶/g, '').replace(/\s+/g, ' ').trim().toLowerCase();
                            const targetText = normalize(anchorText);
                            const mdRoot = document.getElementById('md-content');
                            if (mdRoot) {
                                const candidates = Array.from(mdRoot.querySelectorAll('h1, h2, h3, h4, h5, h6'));
                                el = candidates.find(h => {
                                    const ht = normalize(h.textContent || '');
                                    return ht === targetText || ht.includes(targetText) || targetText.includes(ht);
                                }) || null;
                            }
                        }
                    } catch(_) {}
                }
                if (el) {
                    el.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    this.ui.addAnchorIndicator(el);
                } else {
                    // נסיון אחרון – בתוך iframe של תצוגות אחרות
                    try {
                        const frame = document.getElementById('previewFrame');
                        const doc = frame && (frame.contentDocument || frame.contentWindow?.document);
                        const inside = doc && doc.getElementById(anchorId);
                        if (inside) inside.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    } catch(_) {}
                }
            } else {
                this.scrollToLine(lineNumber);
            }
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
                this.ui.addBookmarkIndicator(lineNumber, this.defaultColor);
            } else {
                this.ui.removeBookmarkIndicator(lineNumber);
            }

            // שלח לשרת עם צבע ברירת המחדל כדי לשמר העדפה משתמש
            const result = await this.api.toggleBookmark(lineNumber, lineText, '', this.defaultColor);

            if (result.ok) {
                if (result.action === 'added') {
                    this.bookmarks.set(lineNumber, result.bookmark);
                    this.ui.addBookmarkIndicator(lineNumber, result.bookmark?.color || this.defaultColor);
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
                    const prevColor = (this.bookmarks.get(lineNumber)?.color) || this.defaultColor;
                    this.ui.addBookmarkIndicator(lineNumber, prevColor);
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
                    const key = (bm.anchor_id ? `a:${bm.anchor_id}` : bm.line_number);
                    this.bookmarks.set(key, bm);
                    if (bm.anchor_id) {
                        this.ui.addAnchorIndicatorById(bm.anchor_id, bm.color || this.defaultColor);
                    } else {
                        this.ui.addBookmarkIndicator(bm.line_number, bm.color || 'yellow');
                    }
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
                    const key = (bm.anchor_id ? `a:${bm.anchor_id}` : bm.line_number);
                    this.bookmarks.set(key, bm);
                    if (bm.anchor_id) {
                        this.ui.addAnchorIndicatorById(bm.anchor_id, bm.color || this.defaultColor);
                    } else {
                        this.ui.addBookmarkIndicator(bm.line_number, bm.color || this.defaultColor);
                    }
                });

                this.ui.updateCount(this.bookmarks.size);
                this.ui.refreshPanel(Array.from(this.bookmarks.values()));
                this.ui.showNotification('טעינה ממטמון מקומי', 'warning');
            }
        }
    }

    getBookmarkCount() {
        return this.bookmarks.size;
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
        // עדיפות ראשונה: raw code מהשרת (הכי אמין למיפוי מספרי שורות)
        try {
            const rawArea = document.getElementById('rawCode');
            if (rawArea && typeof rawArea.value === 'string' && rawArea.value.length > 0) {
                const rawLines = rawArea.value.split('\n');
                const idx = Math.max(0, lineNumber - 1);
                const rawLine = rawLines[idx] || '';
                return (rawLine || '').trim().substring(0, 100);
            }
        } catch (_) {}

        // עדיפות שניה: טקסט מלא של תא הקוד ב-highlighttable (ללא עמודת מספרי השורות)
        try {
            const codePre = document.querySelector('.highlighttable td.code pre')
                || document.querySelector('.source .highlight pre')
                || document.querySelector('.highlight pre');
            if (codePre) {
                const fullText = codePre.textContent || '';
                const lines = fullText.split('\n');
                const idx = Math.max(0, lineNumber - 1);
                let lineText = lines[idx] || '';
                // סילוק אפשרי של מספרי שורות שמוחדרים בטעות לטקסט
                lineText = lineText.replace(/^\s*\d+\s*/, '');
                return lineText.trim().substring(0, 100);
            }
        } catch (_) {}

        // נפילה לאחור: רינדור שגוי עם span-ים – נסה לגשת ישירות לפי nth-child
        try {
            const fallback = document.querySelector(`.source .highlight pre > span:nth-child(${lineNumber}), .highlight pre > span:nth-child(${lineNumber})`);
            if (fallback) {
                return (fallback.textContent || '').trim().substring(0, 100);
            }
        } catch (_) {}

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
    
    async toggleBookmark(lineNumber, lineText = '', note = '', color = undefined) {
        const body = {
            line_number: lineNumber,
            line_text: lineText,
            note: note
        };
        if (color) body.color = color;
        return this.retryableRequest('POST', `/${this.fileId}/toggle`, body);
    }

    async toggleBookmarkAnchor(anchorId, anchorText = '', anchorType = 'md_heading', color = undefined, note = '') {
        const body = {
            line_number: 0,
            anchor_id: anchorId,
            anchor_text: anchorText,
            anchor_type: anchorType,
            note: note
        };
        if (color) body.color = color;
        return this.retryableRequest('POST', `/${this.fileId}/toggle`, body);
    }
    
    async getFileBookmarks() {
        return this.retryableRequest('GET', `/${this.fileId}`);
    }
    
    async updateNote(lineNumber, note) {
        return this.retryableRequest('PUT', `/${this.fileId}/${lineNumber}/note`, {
            note: note
        });
    }
    async updateNoteAnchor(anchorId, note) {
        return this.retryableRequest('PUT', `/${this.fileId}/0/note`, {
            note: note,
            anchor_id: anchorId
        });
    }
    
    async updateColor(lineNumber, color) {
        return this.retryableRequest('PUT', `/${this.fileId}/${lineNumber}/color`, {
            color
        });
    }
    async updateColorAnchor(anchorId, color) {
        return this.retryableRequest('PUT', `/${this.fileId}/0/color`, {
            color,
            anchor_id: anchorId
        });
    }
    
    async deleteBookmark(lineNumber) {
        return this.retryableRequest('DELETE', `/${this.fileId}/${lineNumber}`);
    }
    async deleteBookmarkAnchor(anchorId) {
        // שימוש בפרמטר שאילתה כדי להבדיל
        const path = `/${this.fileId}/0?anchor_id=${encodeURIComponent(anchorId)}`;
        return this.retryableRequest('DELETE', path);
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
        this.TOGGLE_VISIBILITY_KEY = 'bookmarks_toggle_btn_visible';
        this.TOGGLE_POS_KEY = 'bookmarks_toggle_btn_position';
        this.TOGGLE_MINI_KEY = 'bookmarks_toggle_btn_mini';
        this.isDraggingToggle = false;
        this.ensureToggleButtonVisibilityRestored();
        this.restoreTogglePosition();
        this.restoreToggleMiniState();
        this.initInfoModal();
        // ביטול טיפ אוטומטי כברירת מחדל כדי לא להפריע במסכים קטנים
        // אם תרצה להחזיר: קבע דגל והפעל this.maybeShowFirstRunHint()
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

    ensureToggleButtonVisibilityRestored() {
        try {
            const visible = localStorage.getItem(this.TOGGLE_VISIBILITY_KEY);
            if (visible === '0') {
                this.setToggleButtonVisible(false);
            } else {
                this.setToggleButtonVisible(true);
            }
            this.updateVisibilityControlLabel();
        } catch (_) {
            // ignore
        }
    }

    setToggleButtonVisible(show) {
        const btn = document.getElementById('toggleBookmarksBtn');
        if (btn) {
            btn.style.display = show ? 'flex' : 'none';
        }
        try {
            localStorage.setItem(this.TOGGLE_VISIBILITY_KEY, show ? '1' : '0');
        } catch (_) {}
        this.updateVisibilityControlLabel();
    }

    toggleToggleButtonVisibility() {
        const btn = document.getElementById('toggleBookmarksBtn');
        const nowVisible = !btn || btn.style.display !== 'none';
        this.setToggleButtonVisible(!nowVisible);
    }

    updateVisibilityControlLabel() {
        const control = document.getElementById('toggleBtnVisibility');
        if (!control) return;
        const btn = document.getElementById('toggleBookmarksBtn');
        const visible = !btn || btn.style.display !== 'none';
        // תווית קצרה וברורה: 'הסתרה' כשהכפתור מוצג, 'הצגה' כשהוא מוסתר
        control.textContent = visible ? 'הסתרה' : 'הצגה';
        control.setAttribute('aria-pressed', String(visible));
        control.setAttribute('title', visible ? 'הסתר כפתור סימנייה' : 'הצג כפתור סימנייה');
    }

    enableToggleDrag(btn) {
        const isTouch = () => ('ontouchstart' in window) || navigator.maxTouchPoints > 0;
        let dragStartX = 0, dragStartY = 0;
        let startLeft = 0, startTop = 0;
        let dragging = false;
        let longPressTimer = null;

        const getEvtPoint = (ev) => {
            if (ev.touches && ev.touches[0]) return { x: ev.touches[0].clientX, y: ev.touches[0].clientY };
            return { x: ev.clientX, y: ev.clientY };
        };

        const onLongPress = (ev) => {
            // לחיצה ממושכת: נעל מצב mini עד לחיצה רגילה
            this.setToggleMini(true);
            dragging = true;
            this.isDraggingToggle = true;
            btn.style.transition = 'none';
            const rect = btn.getBoundingClientRect();
            startLeft = rect.left;
            startTop = rect.top;
            const p = getEvtPoint(ev);
            dragStartX = p.x;
            dragStartY = p.y;
            ev.preventDefault();
        };

        const start = (ev) => {
            clearTimeout(longPressTimer);
            longPressTimer = setTimeout(() => onLongPress(ev), 350);
        };
        const move = (ev) => {
            if (!dragging) return;
            const p = getEvtPoint(ev);
            const dx = p.x - dragStartX;
            const dy = p.y - dragStartY;
            const left = startLeft + dx;
            const top = startTop + dy;
            this.positionToggleAt(btn, left, top);
        };
        const end = () => {
            clearTimeout(longPressTimer);
            if (!dragging) return;
            dragging = false;
        this.isDraggingToggle = false;
        // דחה מעט כדי שה-click שלאחר השחרור לא יופעל
        this.justFinishedDrag = true;
        setTimeout(() => { this.justFinishedDrag = false; }, 120);
            btn.style.transition = '';
            this.persistTogglePosition(btn);
        };

        const opts = { passive: false };
        btn.addEventListener('mousedown', start, opts);
        document.addEventListener('mousemove', move, opts);
        document.addEventListener('mouseup', end, opts);
        btn.addEventListener('touchstart', start, opts);
        document.addEventListener('touchmove', move, opts);
        document.addEventListener('touchend', end, opts);
        document.addEventListener('touchcancel', end, opts);
    }

    positionToggleAt(btn, leftPx, topPx) {
        // הגבלת תנועה לשטח החלון
        const vw = window.innerWidth, vh = window.innerHeight;
        const r = btn.getBoundingClientRect();
        const left = Math.min(Math.max(0, leftPx), vw - r.width);
        const top = Math.min(Math.max(0, topPx), vh - r.height);
        btn.style.left = left + 'px';
        btn.style.top = top + 'px';
        btn.style.right = 'auto';
        btn.style.bottom = 'auto';
        btn.style.position = 'fixed';
    }

    persistTogglePosition(btn) {
        try {
            const r = btn.getBoundingClientRect();
            const data = { left: r.left, top: r.top };
            localStorage.setItem(this.TOGGLE_POS_KEY, JSON.stringify(data));
        } catch (_) {}
    }

    restoreTogglePosition() {
        try {
            const raw = localStorage.getItem(this.TOGGLE_POS_KEY);
            if (!raw) return;
            const data = JSON.parse(raw);
            const btn = document.getElementById('toggleBookmarksBtn');
            if (!btn || typeof data.left !== 'number' || typeof data.top !== 'number') return;
            this.positionToggleAt(btn, data.left, data.top);
        } catch (_) {}
    }

    setToggleMini(mini) {
        const btn = document.getElementById('toggleBookmarksBtn');
        if (!btn) return;
        btn.classList.toggle('mini', !!mini);
        try { localStorage.setItem(this.TOGGLE_MINI_KEY, mini ? '1' : '0'); } catch(_) {}
    }

    restoreToggleMiniState() {
        try {
            const raw = localStorage.getItem(this.TOGGLE_MINI_KEY);
            const shouldMini = raw === '1';
            const btn = document.getElementById('toggleBookmarksBtn');
            if (btn) btn.classList.toggle('mini', shouldMini);
        } catch(_) {}
        // במסך מלא – ברירת מחדל mini כאשר הכרטיס במסך מלא
        document.addEventListener('fullscreenchange', () => {
            const btn = document.getElementById('toggleBookmarksBtn');
            const card = document.getElementById('codeCard');
            if (!btn) return;
            if (document.fullscreenElement && card && document.fullscreenElement === card) {
                btn.classList.add('mini');
            } else {
                // שחזור מצב mini לפי localStorage
                try {
                    const raw = localStorage.getItem(this.TOGGLE_MINI_KEY);
                    const shouldMini = raw === '1';
                    btn.classList.toggle('mini', shouldMini);
                } catch(_) {}
            }
        });
    }

    initInfoModal() {
        try {
            const infoBtn = document.getElementById('bookmarksInfoBtn');
            const dlg = document.getElementById('bookmarksInfoModal');
            const closeBtn = document.getElementById('bookmarksInfoClose');
            if (!infoBtn || !dlg) return;
            const open = () => { try { dlg.showModal ? dlg.showModal() : (dlg.open = true); } catch(_) { dlg.open = true; } };
            const close = () => { try { dlg.close ? dlg.close() : (dlg.open = false); } catch(_) { dlg.open = false; } };
            infoBtn.addEventListener('click', (e) => { e.preventDefault(); open(); });
            if (closeBtn) closeBtn.addEventListener('click', (e) => { e.preventDefault(); close(); });
            dlg.addEventListener('click', (e) => { if (e.target === dlg) close(); });
        } catch(_) {}
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

    addAnchorIndicator(element, color = 'yellow') {
        try {
            element.classList.add('bookmarked');
            element.setAttribute('data-bookmark-color', color);
            if (!element.querySelector('.bookmark-icon')) {
                const icon = document.createElement('span');
                icon.className = 'bookmark-icon';
                icon.innerHTML = '🔖';
                // הצמדת האייקון לימין הכותרת
                icon.style.marginInlineStart = '8px';
                element.appendChild(icon);
            }
        } catch (_) {}
    }

    removeAnchorIndicator(element) {
        try {
            element.classList.remove('bookmarked');
            element.removeAttribute('data-bookmark-color');
            const icon = element.querySelector('.bookmark-icon');
            if (icon) icon.remove();
        } catch (_) {}
    }

    addAnchorIndicatorById(anchorId, color = 'yellow') {
        try {
            const el = document.getElementById(anchorId);
            if (el) { this.addAnchorIndicator(el, color); return; }
            const frame = document.getElementById('previewFrame');
            const doc = frame && (frame.contentDocument || frame.contentWindow?.document);
            const inside = doc && doc.getElementById(anchorId);
            if (inside) {
                // הוסף מחלקה ואייקון בתוך ה-iframe
                inside.classList.add('bookmarked');
                // אייקון זעיר בצד ימין של האלמנט (פשוט)
                if (!inside.querySelector('.bookmark-icon')) {
                    const icon = doc.createElement('span');
                    icon.className = 'bookmark-icon';
                    icon.textContent = '🔖';
                    inside.appendChild(icon);
                }
            }
        } catch(_) {}
    }

    removeAnchorIndicatorById(anchorId) {
        try {
            const el = document.getElementById(anchorId);
            if (el) this.removeAnchorIndicator(el);
            const frame = document.getElementById('previewFrame');
            const doc = frame && (frame.contentDocument || frame.contentWindow?.document);
            const inside = doc && doc.getElementById(anchorId);
            if (inside) {
                inside.classList.remove('bookmarked');
                const icon = inside.querySelector('.bookmark-icon');
                if (icon) icon.remove();
            }
        } catch(_) {}
    }

    setAnchorColor(anchorId, color) {
        try {
            const el = document.getElementById(anchorId);
            if (el) el.setAttribute('data-bookmark-color', color);
            const frame = document.getElementById('previewFrame');
            const doc = frame && (frame.contentDocument || frame.contentWindow?.document);
            const inside = doc && doc.getElementById(anchorId);
            if (inside) inside.setAttribute('data-bookmark-color', color);
        } catch(_) {}
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
        
        // מיין לפי מספר שורה (anchors עם שורה סינתטית ענקית יהיו בסוף)
        bookmarks.sort((a, b) => (a.line_number || 0) - (b.line_number || 0));
        
        listContainer.innerHTML = bookmarks.map(bm => {
            const isAnchor = !!(bm.anchor_id);
            const title = isAnchor ? (bm.anchor_text || `#${bm.anchor_id}`) : `שורה ${bm.line_number}`;
            const subtitle = isAnchor ? (bm.line_text_preview || '') : (bm.line_text_preview || '');
            const attrs = isAnchor
                ? `data-anchor-id="${this.escapeHtml(bm.anchor_id)}" data-anchor-text="${this.escapeHtml(bm.anchor_text || '')}"`
                : `data-line-number="${bm.line_number}"`;
            return `
            <div class="bookmark-item" ${attrs} data-color="${bm.color || 'yellow'}">
                <div class="bookmark-content">
                    <span class="line-number">${this.escapeHtml(title)}</span>
                    <span class="line-preview">${this.escapeHtml(subtitle)}</span>
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
            </div>`;
        }).join('');
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
    
    openPanel() {
        if (this.panel && !this.panel.classList.contains('open')) {
            this.panel.classList.add('open');
            const toggleBtn = document.getElementById('toggleBookmarksBtn');
            if (toggleBtn) toggleBtn.setAttribute('aria-expanded', 'true');
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
    
    showInlineColorMenu(anchorEl, onPick) {
        // צור תפריט קטן ליד מספר השורה
        const id = 'bookmark-color-menu';
        let menu = document.getElementById(id);
        if (menu) menu.remove();
        menu = document.createElement('div');
        menu.id = id;
        menu.style.position = 'absolute';
        menu.style.background = 'white';
        menu.style.border = '1px solid #ddd';
        menu.style.borderRadius = '6px';
        menu.style.boxShadow = '0 4px 12px rgba(0,0,0,0.15)';
        menu.style.padding = '6px';
        menu.style.display = 'flex';
        menu.style.gap = '6px';
        menu.style.zIndex = '10001';
        const colors = ['yellow','red','green','blue','purple','orange','pink'];
        colors.forEach(c => {
            const b = document.createElement('button');
            b.type = 'button';
            b.style.width = '16px';
            b.style.height = '16px';
            b.style.borderRadius = '50%';
            b.style.border = '1px solid rgba(0,0,0,0.2)';
            b.style.background = getComputedStyle(document.documentElement).getPropertyValue(`--bookmark-${c}`) || c;
            b.addEventListener('click', (e) => {
                e.stopPropagation();
                document.body.removeChild(menu);
                onPick && onPick(c);
            });
            menu.appendChild(b);
        });
        document.body.appendChild(menu);
        const rect = anchorEl.getBoundingClientRect();
        menu.style.left = rect.right + 8 + 'px';
        menu.style.top = rect.top + 'px';
        const close = () => { try { menu.remove(); } catch (_) {} };
        setTimeout(() => {
            document.addEventListener('click', close, { once: true });
        }, 0);
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
