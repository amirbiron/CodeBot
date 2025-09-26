/**
 * Markdown Enhancements for Code Keeper WebApp
 * תוספות ושיפורים לתצוגת Markdown
 */

// === Task Lists Sync with Database ===
class TaskListsSync {
    constructor(fileId) {
        this.fileId = fileId;
        this.syncing = false;
        this.pendingUpdates = [];
        this.syncTimer = null;
    }

    /**
     * טעינת מצב tasks מהשרת
     */
    async loadStates() {
        try {
            const response = await fetch(`/api/task_lists/${this.fileId}`, {
                method: 'GET',
                credentials: 'same-origin'
            });
            
            if (response.ok) {
                const data = await response.json();
                return data.states || {};
            }
        } catch (error) {
            console.error('Error loading task states:', error);
        }
        return {};
    }

    /**
     * עדכון מצב task בשרת
     */
    async updateTask(taskId, checked, text = '') {
        // הוסף לתור העדכונים
        this.pendingUpdates.push({ task_id: taskId, checked, text });
        
        // בטל טיימר קיים
        if (this.syncTimer) {
            clearTimeout(this.syncTimer);
        }
        
        // קבע טיימר חדש לסנכרון
        this.syncTimer = setTimeout(() => this.syncBatch(), 500);
    }

    /**
     * סנכרון אצווה של עדכונים
     */
    async syncBatch() {
        if (this.syncing || this.pendingUpdates.length === 0) {
            return;
        }
        
        this.syncing = true;
        const updates = [...this.pendingUpdates];
        this.pendingUpdates = [];
        
        try {
            const response = await fetch(`/api/task_lists/${this.fileId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'same-origin',
                body: JSON.stringify({ tasks: updates })
            });
            
            if (!response.ok) {
                // החזר את העדכונים לתור במקרה של כישלון
                this.pendingUpdates = updates.concat(this.pendingUpdates);
            }
        } catch (error) {
            console.error('Error syncing tasks:', error);
            // החזר את העדכונים לתור
            this.pendingUpdates = updates.concat(this.pendingUpdates);
        } finally {
            this.syncing = false;
        }
    }

    /**
     * אתחול task lists בדף
     */
    async initialize() {
        const states = await this.loadStates();
        
        document.querySelectorAll('.task-list-item-checkbox').forEach(checkbox => {
            const taskId = checkbox.getAttribute('data-task-id');
            if (taskId && taskId in states) {
                checkbox.checked = states[taskId];
            }
            
            // הוסף event listener
            checkbox.addEventListener('change', () => {
                const text = checkbox.parentElement.textContent.trim();
                this.updateTask(taskId, checkbox.checked, text);
            });
        });
    }
}

// === Code Copy Buttons ===
function addCopyButtonsToCodeBlocks() {
    document.querySelectorAll('pre').forEach(pre => {
        // בדוק אם כבר יש כפתור
        if (pre.querySelector('.code-copy-btn')) {
            return;
        }
        
        // צור wrapper
        const wrapper = document.createElement('div');
        wrapper.className = 'code-block-wrapper';
        pre.parentNode.insertBefore(wrapper, pre);
        wrapper.appendChild(pre);
        
        // צור כפתור העתקה
        const copyBtn = document.createElement('button');
        copyBtn.className = 'code-copy-btn';
        copyBtn.innerHTML = '📋';
        copyBtn.title = 'העתק קוד';
        
        copyBtn.addEventListener('click', async () => {
            const code = pre.textContent || pre.innerText;
            
            try {
                await navigator.clipboard.writeText(code);
                copyBtn.innerHTML = '✅';
                copyBtn.classList.add('copied');
                
                setTimeout(() => {
                    copyBtn.innerHTML = '📋';
                    copyBtn.classList.remove('copied');
                }, 2000);
            } catch (err) {
                console.error('Failed to copy:', err);
                copyBtn.innerHTML = '❌';
                setTimeout(() => {
                    copyBtn.innerHTML = '📋';
                }, 2000);
            }
        });
        
        wrapper.appendChild(copyBtn);
    });
}

// === Theme Support ===
class ThemeManager {
    constructor() {
        this.currentTheme = this.detectTheme();
        this.applyTheme();
        this.watchThemeChanges();
    }

    detectTheme() {
        // בדוק העדפת משתמש
        const savedTheme = localStorage.getItem('ui_theme');
        if (savedTheme) {
            return savedTheme;
        }
        
        // בדוק העדפת מערכת
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            return 'dark';
        }
        
        return 'light';
    }

    applyTheme() {
        document.documentElement.setAttribute('data-theme', this.currentTheme);
        
        // עדכן סגנונות Markdown
        const markdownContent = document.querySelector('.markdown-content');
        if (markdownContent) {
            markdownContent.classList.toggle('dark-theme', this.currentTheme === 'dark');
            markdownContent.classList.toggle('light-theme', this.currentTheme === 'light');
        }
        
        // עדכן Prism theme
        const prismLink = document.querySelector('link[href*="prism"]');
        if (prismLink) {
            if (this.currentTheme === 'dark') {
                prismLink.href = 'https://cdn.jsdelivr.net/npm/prismjs@1.29.0/themes/prism-tomorrow.min.css';
            } else {
                prismLink.href = 'https://cdn.jsdelivr.net/npm/prismjs@1.29.0/themes/prism.min.css';
            }
        }
    }

    watchThemeChanges() {
        // האזן לשינויים בהעדפת מערכת
        if (window.matchMedia) {
            window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', e => {
                this.currentTheme = e.matches ? 'dark' : 'light';
                this.applyTheme();
            });
        }
        
        // האזן לשינויים ב-localStorage
        window.addEventListener('storage', e => {
            if (e.key === 'ui_theme') {
                this.currentTheme = e.newValue || 'light';
                this.applyTheme();
            }
        });
    }

    toggleTheme() {
        this.currentTheme = this.currentTheme === 'dark' ? 'light' : 'dark';
        localStorage.setItem('ui_theme', this.currentTheme);
        this.applyTheme();
    }
}

// === Error Handling ===
class ErrorHandler {
    static showError(message, element) {
        const errorDiv = document.createElement('div');
        errorDiv.className = 'markdown-error';
        errorDiv.innerHTML = `
            <div class="error-icon">⚠️</div>
            <div class="error-message">${this.escapeHtml(message)}</div>
            <button class="error-retry" onclick="location.reload()">🔄 נסה שוב</button>
        `;
        
        if (element) {
            element.innerHTML = '';
            element.appendChild(errorDiv);
        } else {
            document.body.appendChild(errorDiv);
        }
    }

    static escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    static handleApiError(response, element) {
        if (response.status === 404) {
            this.showError('הקובץ לא נמצא או אין לך הרשאות לצפות בו', element);
        } else if (response.status === 400) {
            this.showError('הבקשה לא תקינה. אנא רענן את הדף ונסה שוב', element);
        } else if (response.status === 500) {
            this.showError('שגיאת שרת. אנא נסה שוב מאוחר יותר', element);
        } else if (response.status === 503) {
            this.showError('השירות לא זמין כרגע. אנא נסה שוב מאוחר יותר', element);
        } else {
            this.showError(`שגיאה לא צפויה (${response.status}). אנא צור קשר עם התמיכה`, element);
        }
    }
}

// === Sanitization Helper ===
class Sanitizer {
    static sanitizeHtml(html) {
        // אם DOMPurify זמין, השתמש בו
        if (typeof DOMPurify !== 'undefined') {
            return DOMPurify.sanitize(html, {
                ALLOWED_TAGS: [
                    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                    'p', 'br', 'hr',
                    'strong', 'b', 'em', 'i', 'del', 's', 'code', 'pre',
                    'ul', 'ol', 'li',
                    'blockquote',
                    'a', 'img',
                    'table', 'thead', 'tbody', 'tr', 'th', 'td',
                    'div', 'span',
                    'input' // for checkboxes
                ],
                ALLOWED_ATTR: [
                    'href', 'src', 'alt', 'title', 'class', 'id',
                    'type', 'checked', 'data-task-id', 'data-mermaid', 'data-math'
                ],
                ALLOW_DATA_ATTR: true
            });
        }
        
        // Fallback: basic sanitization
        return html
            .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
            .replace(/on\w+\s*=\s*"[^"]*"/gi, '')
            .replace(/on\w+\s*=\s*'[^']*'/gi, '')
            .replace(/javascript:/gi, '');
    }
}

// === Initialize Everything ===
document.addEventListener('DOMContentLoaded', function() {
    // אתחול Theme Manager
    const themeManager = new ThemeManager();
    
    // הוסף כפתורי העתקה לבלוקי קוד
    addCopyButtonsToCodeBlocks();
    
    // אתחול סנכרון Task Lists אם יש file ID
    const fileIdElement = document.querySelector('[data-file-id]');
    if (fileIdElement) {
        const fileId = fileIdElement.getAttribute('data-file-id');
        const taskSync = new TaskListsSync(fileId);
        taskSync.initialize();
    }
    
    // הוסף כפתור החלפת theme
    const themeToggle = document.createElement('button');
    themeToggle.className = 'theme-toggle-btn';
    themeToggle.innerHTML = themeManager.currentTheme === 'dark' ? '☀️' : '🌙';
    themeToggle.title = 'החלף ערכת נושא';
    themeToggle.onclick = () => {
        themeManager.toggleTheme();
        themeToggle.innerHTML = themeManager.currentTheme === 'dark' ? '☀️' : '🌙';
    };
    document.body.appendChild(themeToggle);
});

// === Export for use in other scripts ===
window.MarkdownEnhancements = {
    TaskListsSync,
    ThemeManager,
    ErrorHandler,
    Sanitizer,
    addCopyButtonsToCodeBlocks
};