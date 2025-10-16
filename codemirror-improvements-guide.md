# 🚀 שיפורים מומלצים למדריך עורך CodeMirror

## 📋 תוכן עניינים
1. [שיפורי נגישות (Accessibility)](#accessibility)
2. [תמיכה במובייל](#mobile-support)
3. [טיפול בשגיאות משופר](#error-handling)
4. [ניהול ביצועים](#performance)
5. [אבטחה מתקדמת](#security)
6. [שמירה אוטומטית](#auto-save)
7. [בדיקות מקיפות](#testing)
8. [תכונות נוספות](#additional-features)

---

## 1. שיפורי נגישות (Accessibility) {#accessibility}

### הוספת תמיכה מלאה בקוראי מסך

```javascript
// accessibility-extensions.js
import { EditorView } from '@codemirror/view';

export const accessibilityExtensions = () => {
  return [
    // הכרזות לקורא מסך
    EditorView.announce.of((view, change) => {
      if (!change) return null;
      
      const announcements = {
        'delete': 'תו נמחק',
        'insert': 'תו הוכנס',
        'select': 'טקסט נבחר',
        'paste': 'טקסט הודבק',
        'cut': 'טקסט נגזר',
        'undo': 'פעולה בוטלה',
        'redo': 'פעולה שוחזרה'
      };
      
      return announcements[change.type] || null;
    }),
    
    // תמיכה בניווט עם מקלדת בלבד
    EditorView.theme({
      '&.cm-focused': {
        outline: '2px solid #4A90E2',
        outlineOffset: '3px'
      },
      '.cm-selectionBackground': {
        backgroundColor: 'rgba(74, 144, 226, 0.3)'
      },
      '.cm-cursor': {
        borderLeftWidth: '3px'
      }
    }),
    
    // הוספת ARIA attributes
    EditorView.contentAttributes.of({
      'role': 'textbox',
      'aria-multiline': 'true',
      'aria-label': 'עורך קוד',
      'aria-describedby': 'editor-help-text'
    })
  ];
};

// קיצורי מקלדת נוספים לנגישות
export const accessibilityKeymap = [
  { key: 'Alt-F1', run: showKeyboardShortcuts },
  { key: 'Alt-G', run: gotoLine },
  { key: 'Alt-J', run: jumpToDefinition },
  { key: 'Alt-B', run: toggleBlockSelection },
  { key: 'Escape', run: clearSelection }
];

// פונקציה להצגת עזרה
function showKeyboardShortcuts(view) {
  const modal = document.createElement('div');
  modal.className = 'shortcuts-modal';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-label', 'קיצורי מקלדת');
  
  modal.innerHTML = `
    <div class="modal-content">
      <h2>קיצורי מקלדת</h2>
      <button class="close-btn" aria-label="סגור">×</button>
      <table role="table">
        <thead>
          <tr>
            <th>קיצור</th>
            <th>פעולה</th>
          </tr>
        </thead>
        <tbody>
          <tr><td>Ctrl+S</td><td>שמירה</td></tr>
          <tr><td>Ctrl+F</td><td>חיפוש</td></tr>
          <tr><td>Ctrl+H</td><td>חיפוש והחלפה</td></tr>
          <tr><td>Ctrl+Space</td><td>השלמה אוטומטית</td></tr>
          <tr><td>Alt+Up/Down</td><td>הזזת שורה</td></tr>
          <tr><td>Ctrl+/</td><td>הערה/ביטול הערה</td></tr>
          <tr><td>F11</td><td>מסך מלא</td></tr>
          <tr><td>Escape</td><td>יציאה ממצב מיוחד</td></tr>
        </tbody>
      </table>
    </div>
  `;
  
  document.body.appendChild(modal);
  modal.querySelector('.close-btn').focus();
  return true;
}
```

---

## 2. תמיכה במובייל {#mobile-support}

### זיהוי והתאמה למכשירים ניידים

```javascript
// mobile-support.js
export class MobileSupport {
  constructor() {
    this.isMobile = this.detectMobile();
    this.isTablet = this.detectTablet();
    this.touchStartY = 0;
    this.lastTap = 0; // אתחול למניעת NaN בהשוואה הראשונה
  }
  
  detectMobile() {
    return /Android|webOS|iPhone|iPod|BlackBerry|IEMobile|Opera Mini/i.test(
      navigator.userAgent
    ) || window.innerWidth < 768;
  }
  
  detectTablet() {
    return /iPad|Android(?!.*Mobile)|Tablet/i.test(navigator.userAgent) ||
      (window.innerWidth >= 768 && window.innerWidth <= 1024);
  }
  
  getMobileExtensions() {
    if (!this.isMobile && !this.isTablet) return [];
    
    return [
      // גודל גופן מותאם למובייל (מונע zoom אוטומטי)
      EditorView.theme({
        '.cm-content': {
          fontSize: '16px',
          lineHeight: '1.6',
          padding: '10px'
        },
        '.cm-line': {
          padding: '2px 0'
        },
        '.cm-gutters': {
          fontSize: '14px',
          minWidth: '35px'
        },
        // הגדלת אזורי לחיצה
        '.cm-foldGutter span': {
          padding: '5px',
          minWidth: '20px',
          minHeight: '20px'
        },
        '.cm-button': {
          minHeight: '40px',
          padding: '10px 15px'
        }
      }),
      
      // תמיכה במחוות מגע
      EditorView.domEventHandlers({
        touchstart: (e, view) => {
          this.touchStartY = e.touches[0].clientY;
          return false;
        },
        
        touchmove: (e, view) => {
          // מניעת גלילה כפולה
          if (Math.abs(e.touches[0].clientY - this.touchStartY) > 10) {
            e.preventDefault();
          }
          return false;
        },
        
        // Double tap to select word
        touchend: (e, view) => {
          const currentTime = e.timeStamp || Date.now();
          const timeSinceLastTap = currentTime - this.lastTap;
          
          if (timeSinceLastTap < 300 && timeSinceLastTap > 0) {
            // Double tap detected
            this.selectWordAtTouch(e, view);
          }
          
          this.lastTap = currentTime;
          return false;
        }
      })
    ];
  }
  
  createMobileToolbar() {
    const toolbar = document.createElement('div');
    toolbar.className = 'mobile-toolbar';
    toolbar.innerHTML = `
      <div class="toolbar-group">
        <button data-action="undo" aria-label="ביטול">
          <svg><!-- undo icon --></svg>
        </button>
        <button data-action="redo" aria-label="חזרה">
          <svg><!-- redo icon --></svg>
        </button>
      </div>
      
      <div class="toolbar-group">
        <button data-action="indent" aria-label="הזחה">
          <svg><!-- indent icon --></svg>
        </button>
        <button data-action="outdent" aria-label="הזחה לאחור">
          <svg><!-- outdent icon --></svg>
        </button>
      </div>
      
      <div class="toolbar-group">
        <button data-action="find" aria-label="חיפוש">
          <svg><!-- search icon --></svg>
        </button>
        <button data-action="replace" aria-label="החלפה">
          <svg><!-- replace icon --></svg>
        </button>
      </div>
      
      <div class="toolbar-group">
        <button data-action="comment" aria-label="הערה">
          <svg><!-- comment icon --></svg>
        </button>
        <button data-action="format" aria-label="עיצוב">
          <svg><!-- format icon --></svg>
        </button>
      </div>
    `;
    
    // הוספת event listeners
    toolbar.addEventListener('click', (e) => {
      const button = e.target.closest('button');
      if (button) {
        const action = button.dataset.action;
        this.executeMobileAction(action);
      }
    });
    
    return toolbar;
  }
  
  executeMobileAction(action) {
    const actions = {
      'undo': () => this.editor.undo(),
      'redo': () => this.editor.redo(),
      'indent': () => this.editor.indent(),
      'outdent': () => this.editor.outdent(),
      'find': () => this.editor.openSearchPanel(),
      'replace': () => this.editor.openReplacePanel(),
      'comment': () => this.editor.toggleComment(),
      'format': () => this.editor.formatCode()
    };
    
    if (actions[action]) {
      actions[action]();
    }
  }
}
```

### התאמת גובה עם VisualViewport (מקלדת וירטואלית במובייל)

```javascript
// viewport-adjust.js
export function setupViewportHeightAdjustment(rootSelector = '.codemirror-container') {
  const root = document.querySelector(rootSelector) || document.querySelector('.cm-editor');
  if (!root) return () => {};

  const vv = window.visualViewport;
  let rafId = null;

  const apply = () => {
    if (rafId) cancelAnimationFrame(rafId);
    rafId = requestAnimationFrame(() => {
      const vh = (vv && vv.height) || window.innerHeight;
      const top = root.getBoundingClientRect().top;
      const padding = 24; // מרווח תחתון קטן
      const height = Math.max(180, Math.floor(vh - top - padding));
      root.style.maxHeight = height + 'px';
      root.style.height = height + 'px';
      const scroller = root.querySelector('.cm-scroller');
      if (scroller) scroller.style.maxHeight = height + 'px';
    });
  };

  apply();

  if (vv) {
    vv.addEventListener('resize', apply);
    vv.addEventListener('scroll', apply);
  } else {
    window.addEventListener('resize', apply);
    window.addEventListener('orientationchange', apply);
  }

  return () => {
    if (vv) {
      vv.removeEventListener('resize', apply);
      vv.removeEventListener('scroll', apply);
    } else {
      window.removeEventListener('resize', apply);
      window.removeEventListener('orientationchange', apply);
    }
    if (rafId) cancelAnimationFrame(rafId);
  };
}
```

---
 
## 3. טיפול בשגיאות משופר {#error-handling}

### מערכת Error Recovery מתקדמת

```javascript
// error-recovery.js
export class ErrorRecoverySystem {
  constructor(editorManager) {
    this.editorManager = editorManager;
    this.errorCount = 0;
    this.maxRetries = 3;
    this.fallbackQueue = ['codemirror', 'simple', 'readonly'];
    this.errorLog = [];
  }
  
  async tryInitEditor(container, options) {
    let lastError = null;
    
    for (let attempt = 0; attempt < this.maxRetries; attempt++) {
      try {
        await this.initWithFallback(container, options);
        this.errorCount = 0; // איפוס מונה שגיאות
        return true;
      } catch (error) {
        lastError = error;
        this.logError(error, attempt);
        
        // נסיון תיקון אוטומטי
        await this.attemptAutoFix(error);
        
        // המתנה לפני ניסיון נוסף
        await this.delay(Math.pow(2, attempt) * 1000);
      }
    }
    
    // אם כל הניסיונות נכשלו
    this.handleCriticalFailure(lastError, container, options);
    return false;
  }
  
  async initWithFallback(container, options) {
    const currentMode = this.fallbackQueue[Math.min(this.errorCount, this.fallbackQueue.length - 1)];
    
    switch (currentMode) {
      case 'codemirror':
        return await this.initCodeMirror(container, options);
        
      case 'simple':
        return this.initSimpleEditor(container, options);
        
      case 'readonly':
        return this.initReadOnlyView(container, options);
        
      default:
        throw new Error('No fallback available');
    }
  }
  
  async attemptAutoFix(error) {
    const fixes = {
      'CDN_LOAD_FAILED': async () => {
        // נסה CDN חלופי
        const alternativeCDNs = [
          'https://cdn.jsdelivr.net',
          'https://unpkg.com',
          'https://cdnjs.cloudflare.com'
        ];
        
        for (const cdn of alternativeCDNs) {
          try {
            await this.loadFromCDN(cdn);
            return true;
          } catch (e) {
            continue;
          }
        }
        return false;
      },
      
      'MEMORY_EXHAUSTED': () => {
        // נקה זיכרון
        if (this.editorManager.cmInstance) {
          this.editorManager.cmInstance.destroy();
          this.editorManager.cmInstance = null;
        }
        
        // פינוי זיכרון
        if (global.gc) {
          global.gc();
        }
        
        return true;
      },
      
      'SYNTAX_ERROR': () => {
        // נסה לתקן syntax errors בתוכן
        const content = this.editorManager.getValue();
        const fixedContent = this.autoFixSyntax(content);
        this.editorManager.setValue(fixedContent);
        return true;
      }
    };
    
    const errorType = this.detectErrorType(error);
    if (fixes[errorType]) {
      return await fixes[errorType]();
    }
    
    return false;
  }
  
  handleCriticalFailure(error, container, options) {
    // יצירת ממשק חירום
    const emergencyUI = document.createElement('div');
    emergencyUI.className = 'emergency-editor';
    emergencyUI.innerHTML = `
      <div class="error-notification">
        <h3>⚠️ בעיה בטעינת העורך</h3>
        <p>העורך המתקדם לא זמין כרגע. אתה יכול:</p>
        <div class="emergency-actions">
          <button onclick="window.editorRecovery.useSimpleEditor()">
            השתמש בעורך פשוט
          </button>
          <button onclick="window.editorRecovery.downloadFile()">
            הורד את הקובץ
          </button>
          <button onclick="window.editorRecovery.retry()">
            נסה שוב
          </button>
        </div>
        <details>
          <summary>פרטי שגיאה</summary>
          <pre>${this.sanitizeError(error)}</pre>
        </details>
      </div>
      <textarea class="emergency-textarea">${options.value || ''}</textarea>
    `;
    
    container.innerHTML = '';
    container.appendChild(emergencyUI);
    
    // שמירת reference גלובלי לפונקציות החירום
    window.editorRecovery = {
      useSimpleEditor: () => this.switchToSimple(container, options),
      downloadFile: () => this.downloadContent(options.value),
      retry: () => this.tryInitEditor(container, options)
    };
    
    // דיווח לשרת
    this.reportCriticalError(error);
  }
  
  logError(error, attempt) {
    const errorEntry = {
      timestamp: Date.now(),
      attempt,
      message: error.message,
      stack: error.stack,
      userAgent: navigator.userAgent,
      editorState: this.editorManager.currentEditor
    };
    
    this.errorLog.push(errorEntry);
    
    // שמירה ב-localStorage לצורך דיבאג
    try {
      const logs = JSON.parse(localStorage.getItem('editorErrors') || '[]');
      logs.push(errorEntry);
      // שמירת רק 50 השגיאות האחרונות
      if (logs.length > 50) logs.shift();
      localStorage.setItem('editorErrors', JSON.stringify(logs));
    } catch (e) {
      // התעלם משגיאות localStorage
    }
  }
  
  async reportCriticalError(error) {
    try {
      await fetch('/api/editor/critical-error', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          error: {
            message: error.message,
            stack: error.stack,
            type: this.detectErrorType(error)
          },
          context: {
            errorLog: this.errorLog.slice(-10),
            browserInfo: {
              userAgent: navigator.userAgent,
              platform: navigator.platform,
              memory: performance.memory ? {
                used: performance.memory.usedJSHeapSize,
                limit: performance.memory.jsHeapSizeLimit
              } : null
            }
          }
        })
      });
    } catch (e) {
      // שגיאת דיווח לא צריכה לשבור את האפליקציה
      console.error('Failed to report critical error:', e);
    }
  }
  
  detectErrorType(error) {
    if (error.message.includes('CDN') || error.message.includes('network')) {
      return 'CDN_LOAD_FAILED';
    }
    if (error.message.includes('memory') || error.message.includes('heap')) {
      return 'MEMORY_EXHAUSTED';
    }
    if (error.message.includes('syntax') || error.message.includes('parse')) {
      return 'SYNTAX_ERROR';
    }
    return 'UNKNOWN';
  }
  
  delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
}
```

### טעינת מודולים עם Fallback ל‑CDN

```javascript
// cdn-fallback.js
export async function loadModuleWithFallback(urls) {
  let lastErr;
  for (const url of urls) {
    try { return await import(url); } catch (e) { lastErr = e; }
  }
  throw lastErr || new Error('All CDN candidates failed');
}

// דוגמה: טעינת מודול שפה ל‑CodeMirror
const mod = await loadModuleWithFallback([
  'https://cdn.jsdelivr.net/npm/@codemirror/lang-python@6/dist/index.js',
  'https://unpkg.com/@codemirror/lang-python@6/dist/index.js'
]);
const python = mod.python ? mod.python() : [];
```

---

## 4. ניהול ביצועים {#performance}

### אופטימיזציות לקבצים גדולים

```javascript
// performance-manager.js
export class PerformanceManager {
  constructor() {
    this.metrics = {
      loadTime: 0,
      renderTime: 0,
      memoryUsage: 0,
      fps: 60
    };
    this.performanceObserver = null;
    this.isLargeFile = false;
  }
  
  // Web Worker לעיבוד קבצים גדולים
  async processLargeFile(content) {
    if (content.length < 500000) return content; // פחות מ-500KB
    
    return new Promise((resolve, reject) => {
      const worker = new Worker('/static/js/file-processor-worker.js');
      
      worker.postMessage({
        action: 'process',
        content: content
      });
      
      worker.onmessage = (e) => {
        if (e.data.error) {
          reject(new Error(e.data.error));
        } else {
          resolve(e.data.result);
        }
        worker.terminate();
      };
      
      // timeout של 30 שניות
      setTimeout(() => {
        worker.terminate();
        reject(new Error('File processing timeout'));
      }, 30000);
    });
  }
  
  // Viewport Virtualization
  getVirtualizationExtension() {
    return EditorView.theme({
      '&': {
        maxHeight: '80vh',
        overflow: 'auto'
      },
      '.cm-scroller': {
        fontFamily: 'var(--editor-font, monospace)',
        fontSize: 'var(--editor-font-size, 14px)'
      },
      '.cm-content': {
        minHeight: '100%'
      }
    });
  }
  
  // Lazy Loading של הרחבות
  createLazyExtensionLoader() {
    const extensionCache = new Map();
    
    return {
      async load(extensionName) {
        if (extensionCache.has(extensionName)) {
          return extensionCache.get(extensionName);
        }
        
        const loaders = {
          'python': () => import('@codemirror/lang-python'),
          'javascript': () => import('@codemirror/lang-javascript'),
          'markdown': () => import('@codemirror/lang-markdown'),
          'sql': () => import('@codemirror/lang-sql'),
          'json': () => import('@codemirror/lang-json'),
          'xml': () => import('@codemirror/lang-xml'),
          'css': () => import('@codemirror/lang-css'),
          'html': () => import('@codemirror/lang-html')
        };
        
        if (loaders[extensionName]) {
          const extension = await loaders[extensionName]();
          extensionCache.set(extensionName, extension);
          return extension;
        }
        
        throw new Error(`Unknown extension: ${extensionName}`);
      },
      
      preload(extensions) {
        // טעינה מראש של הרחבות נפוצות
        return Promise.all(
          extensions.map(ext => this.load(ext).catch(() => null))
        );
      }
    };
  }
  
  // Memory Management
  setupMemoryManagement(editor) {
    let memoryCheckInterval;
    
    const checkMemory = () => {
      if (performance.memory) {
        const used = performance.memory.usedJSHeapSize;
        const limit = performance.memory.jsHeapSizeLimit;
        const usage = (used / limit) * 100;
        
        this.metrics.memoryUsage = usage;
        
        if (usage > 90) {
          this.handleHighMemoryUsage(editor);
        }
      }
    };
    
    // בדיקה כל 10 שניות
    memoryCheckInterval = setInterval(checkMemory, 10000);
    
    return () => clearInterval(memoryCheckInterval);
  }
  
  handleHighMemoryUsage(editor) {
    console.warn('High memory usage detected');
    
    // ניקוי undo history
    if (editor.state.undoDepth > 100) {
      editor.dispatch({
        effects: clearOldUndoHistory.of(100)
      });
    }
    
    // הקטנת cache
    this.clearUnusedCache();
    
    // התראה למשתמש
    this.showMemoryWarning();
  }
  
  // Performance Monitoring
  startPerformanceMonitoring() {
    // מדידת FPS
    let lastTime = performance.now();
    let frames = 0;
    
    const measureFPS = () => {
      frames++;
      const currentTime = performance.now();
      
      if (currentTime >= lastTime + 1000) {
        this.metrics.fps = Math.round((frames * 1000) / (currentTime - lastTime));
        frames = 0;
        lastTime = currentTime;
      }
      
      requestAnimationFrame(measureFPS);
    };
    
    measureFPS();
    
    // Performance Observer
    if ('PerformanceObserver' in window) {
      this.performanceObserver = new PerformanceObserver((entries) => {
        for (const entry of entries.getEntries()) {
          if (entry.name.includes('editor')) {
            this.logPerformance(entry);
          }
        }
      });
      
      this.performanceObserver.observe({
        entryTypes: ['measure', 'navigation', 'resource']
      });
    }
  }
  
  logPerformance(entry) {
    const data = {
      name: entry.name,
      duration: entry.duration,
      startTime: entry.startTime,
      timestamp: Date.now()
    };
    
    // שליחה לשרת לניתוח
    if (this.shouldReportPerformance()) {
      this.reportPerformance(data);
    }
  }
  
  // Debouncing & Throttling utilities
  debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
      const later = () => {
        clearTimeout(timeout);
        func(...args);
      };
      clearTimeout(timeout);
      timeout = setTimeout(later, wait);
    };
  }
  
  throttle(func, limit) {
    let inThrottle;
    return function(...args) {
      if (!inThrottle) {
        func.apply(this, args);
        inThrottle = true;
        setTimeout(() => inThrottle = false, limit);
      }
    };
  }
}

// file-processor-worker.js - Web Worker לעיבוד קבצים
self.onmessage = function(e) {
  const { action, content } = e.data;
  
  if (action === 'process') {
    try {
      // עיבוד הקובץ בחלקים
      const chunkSize = 50000; // 50KB chunks
      const chunks = [];
      
      for (let i = 0; i < content.length; i += chunkSize) {
        chunks.push(content.slice(i, i + chunkSize));
      }
      
      // ניתוח וניקוי
      const processed = chunks.map(chunk => {
        // הסרת רווחים מיותרים
        return chunk.replace(/\s+$/gm, '');
      }).join('');
      
      self.postMessage({ result: processed });
    } catch (error) {
      self.postMessage({ error: error.message });
    }
  }
};
```

---

## 5. אבטחה מתקדמת {#security}

### ⚠️ אזהרה חשובה על סניטציה
**לעולם אל תנסו לממש סניטציה של HTML בעצמכם עם Regular Expressions!**
- Regex לא יכול לטפל בכל המקרים של XSS
- יש אינספור דרכים לעקוף סניטציה פשוטה
- השתמשו רק בספריות מוכחות כמו DOMPurify

### התקנת DOMPurify (חובה!)
```bash
# NPM
npm install dompurify

# או CDN
<script src="https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js"></script>
```

### הגנה מפני XSS ו-injection attacks

```python
# צד השרת - app.py או middleware נפרד
from flask import make_response

@app.after_request
def set_security_headers(response):
    """הגדרת CSP Headers בצד השרת - החלק הקריטי לאבטחה!"""
    
    # CSP חייב להיות מוגדר בצד השרת, לא בצד הלקוח
    csp_policy = "; ".join([
        "default-src 'self'",
        "script-src 'self' https://cdn.jsdelivr.net 'sha256-...'",  # הוסף hashes ספציפיים
        "style-src 'self' https://cdn.jsdelivr.net",
        "connect-src 'self'",
        "img-src 'self' data: https:",
        "font-src 'self' https://fonts.gstatic.com",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "upgrade-insecure-requests"
    ])
    
    response.headers['Content-Security-Policy'] = csp_policy
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    
    return response

# אלטרנטיבה: הגדרה ב-nginx/Apache
# /etc/nginx/sites-available/your-site
# add_header Content-Security-Policy "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net;" always;
```

```javascript
// security-manager.js - צד הלקוח (רק לסניטציה ובדיקות, לא ל-CSP!)
export class SecurityManager {
  constructor() {
    // CSP חייב להיות מוגדר בצד השרת!
    // כאן רק מגדירים את המדיניות לצורך תיעוד/בדיקה
    this.cspPolicy = this.generateCSP();
    this.sanitizer = this.createSanitizer();
  }
  
  generateCSP() {
    return {
      'default-src': ["'self'"],
      'script-src': [
        "'self'",
        'https://cdn.jsdelivr.net',
        "'sha256-...'", // hashes ספציפיים לסקריפטים inline
      ],
      'style-src': [
        "'self'",
        'https://cdn.jsdelivr.net',
        "'unsafe-inline'" // רק אם הכרחי, עדיף להימנע
      ],
      'connect-src': ["'self'"],
      'img-src': ["'self'", 'data:', 'https:'],
      'font-src': ["'self'", 'https://fonts.gstatic.com'],
      'object-src': ["'none'"],
      'base-uri': ["'self'"],
      'form-action': ["'self'"],
      'frame-ancestors': ["'none'"],
      'upgrade-insecure-requests': []
    };
  }
  
  // CSP חייב להיות מוגדר בצד השרת, לא בצד הלקוח!
  getCSPPolicy() {
    // מחזיר את המדיניות לשימוש בצד השרת
    return Object.entries(this.cspPolicy)
      .map(([key, values]) => `${key} ${values.join(' ')}`)
      .join('; ');
  }
  
  createSanitizer() {
    // ⚠️ אזהרה: אל תנסו לממש סניטציה בעצמכם עם regex!
    // השתמשו רק בספריות מוכחות כמו DOMPurify
    
    // התקנה: npm install dompurify
    // או CDN: <script src="https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js"></script>
    
    if (typeof DOMPurify === 'undefined') {
      console.error('DOMPurify not loaded! HTML sanitization disabled.');
      // במקרה חירום - החזר טקסט פשוט בלבד
      return {
        sanitizeHTML: (html) => {
          // הסרת כל ה-HTML, השארת טקסט בלבד
          const div = document.createElement('div');
          div.textContent = html;
          return div.innerHTML;
        }
      };
    }
    
    // הגדרת DOMPurify עם קונפיגורציה בטוחה
    return {
      sanitizeHTML(html) {
        // DOMPurify עם הגדרות מחמירות
        return DOMPurify.sanitize(html, {
          ALLOWED_TAGS: ['b', 'i', 'em', 'strong', 'a', 'p', 'br', 'ul', 'li', 'ol'],
          ALLOWED_ATTR: ['href', 'title'],
          ALLOW_DATA_ATTR: false,
          USE_PROFILES: { html: true }
        });
      },
      
      
      // לבדיקת קוד - רק התראות, לא סניטציה
      detectDangerousCode(code) {
        // זו רק בדיקה להתראה, לא הגנה!
        const dangerous = [
          /eval\s*\(/,
          /new\s+Function\s*\(/,
          /document\.write/,
          /innerHTML\s*=/,
          /__proto__/,
          /constructor\s*\[/
        ];
        
        const detectedPatterns = [];
        for (const pattern of dangerous) {
          if (pattern.test(code)) {
            detectedPatterns.push(pattern.source);
          }
        }
        
        if (detectedPatterns.length > 0) {
          console.warn('Potentially dangerous patterns detected:', detectedPatterns);
          // להציג התראה למשתמש, לא לחסום אוטומטית
          return { safe: false, patterns: detectedPatterns };
        }
        
        return { safe: true };
      },
      
      // שיטה בטוחה להמרת טקסט ל-HTML בטוח
      textToSafeHTML(str) {
        // שיטה בטוחה - משתמש ב-textContent
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
      }
    };
  }
  
  // בדיקת תוכן לפני שמירה
  validateContent(content, options = {}) {
    const maxSize = options.maxSize || 10 * 1024 * 1024; // 10MB
    const allowedTypes = options.allowedTypes || ['text', 'code'];
    
    // בדיקת גודל
    if (content.length > maxSize) {
      throw new Error(`Content too large: ${content.length} bytes (max: ${maxSize})`);
    }
    
    // בדיקת תוכן בינארי
    if (this.containsBinary(content)) {
      throw new Error('Binary content not allowed');
    }
    
    // בדיקת encoding
    if (!this.isValidUTF8(content)) {
      throw new Error('Invalid UTF-8 encoding');
    }
    
    return true;
  }
  
  containsBinary(str) {
    // בדיקה לתווים בינאריים
    return /[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/.test(str);
  }
  
  isValidUTF8(str) {
    try {
      // נסיון לקודד ולפענח
      return str === decodeURIComponent(encodeURIComponent(str));
    } catch (e) {
      return false;
    }
  }
  
  // Rate Limiting
  createRateLimiter(maxRequests = 10, windowMs = 60000) {
    const requests = new Map();
    
    return function rateLimiter(key) {
      const now = Date.now();
      const userRequests = requests.get(key) || [];
      
      // הסרת בקשות ישנות
      const validRequests = userRequests.filter(
        time => now - time < windowMs
      );
      
      if (validRequests.length >= maxRequests) {
        const resetTime = Math.ceil((validRequests[0] + windowMs - now) / 1000);
        throw new Error(`Rate limit exceeded. Try again in ${resetTime} seconds`);
      }
      
      validRequests.push(now);
      requests.set(key, validRequests);
      
      return true;
    };
  }
}
```

---

## 6. שמירה אוטומטית {#auto-save}

### מערכת שמירה אוטומטית חכמה

```javascript
// auto-save-manager.js
export class AutoSaveManager {
  constructor(editor, options = {}) {
    this.editor = editor;
    this.interval = options.interval || 30000; // 30 שניות
    this.debounceTime = options.debounceTime || 5000; // 5 שניות
    this.lastSavedContent = '';
    this.lastSavedTime = Date.now();
    this.isDirty = false;
    this.saveInProgress = false;
    this.conflictResolution = options.conflictResolution || 'merge';
    
    this.setupAutoSave();
    this.setupIndicators();
  }
  
  setupAutoSave() {
    // Debounced save function
    this.debouncedSave = this.debounce(() => {
      if (this.isDirty && !this.saveInProgress) {
        this.save();
      }
    }, this.debounceTime);
    
    // שמירה אוטומטית כל X זמן
    this.intervalId = setInterval(() => {
      if (this.isDirty && !this.saveInProgress) {
        this.save();
      }
    }, this.interval);
    
    // מעקב אחרי שינויים
    this.editor.on('change', () => {
      const currentContent = this.editor.getValue();
      if (currentContent !== this.lastSavedContent) {
        this.isDirty = true;
        this.updateIndicator('unsaved');
        this.debouncedSave();
      }
    });
    
    // שמירה לפני יציאה
    this.beforeUnloadHandler = (e) => {
      if (this.isDirty) {
        // ניסיון שמירה סינכרונית
        this.saveSync();
        
        e.preventDefault();
        e.returnValue = 'יש שינויים שלא נשמרו. האם אתה בטוח שברצונך לצאת?';
        return e.returnValue;
      }
    };
    
    window.addEventListener('beforeunload', this.beforeUnloadHandler);
    
    // שמירה כשהחלון מאבד פוקוס
    document.addEventListener('visibilitychange', () => {
      if (document.hidden && this.isDirty) {
        this.save();
      }
    });
    
    // קיצור מקלדת לשמירה
    this.editor.addKeyMap({
      'Ctrl-S': () => {
        this.save();
        return true;
      },
      'Cmd-S': () => {
        this.save();
        return true;
      }
    });
  }
  
  async save() {
    if (this.saveInProgress) return;
    
    this.saveInProgress = true;
    this.updateIndicator('saving');
    
    const content = this.editor.getValue();
    const metadata = this.getMetadata();
    
    try {
      // בדיקת קונפליקטים
      const serverVersion = await this.checkServerVersion();
      if (serverVersion && serverVersion.timestamp > this.lastSavedTime) {
        await this.handleConflict(content, serverVersion);
        return;
      }
      
      // שמירה לשרת
      const response = await fetch('/api/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content,
          metadata,
          checksum: this.calculateChecksum(content),
          timestamp: Date.now()
        })
      });
      
      if (!response.ok) {
        throw new Error(`Save failed: ${response.statusText}`);
      }
      
      const result = await response.json();
      
      // עדכון מצב
      this.lastSavedContent = content;
      this.lastSavedTime = Date.now();
      this.isDirty = false;
      this.updateIndicator('saved');
      
      // שמירת גרסה ב-localStorage כגיבוי
      this.saveToLocalStorage(content);
      
      // הודעה למשתמש
      this.showNotification('נשמר בהצלחה', 'success');
      
    } catch (error) {
      console.error('Save failed:', error);
      
      // שמירה מקומית כגיבוי
      this.saveToLocalStorage(content);
      this.updateIndicator('error');
      
      // הצגת אפשרויות למשתמש
      this.showSaveError(error);
      
    } finally {
      this.saveInProgress = false;
    }
  }
  
  saveSync() {
    // שמירה סינכרונית לשימוש ב-beforeunload
    const content = this.editor.getValue();
    
    try {
      // שמירה ל-localStorage
      localStorage.setItem('editorBackup', JSON.stringify({
        content,
        timestamp: Date.now(),
        url: window.location.href
      }));
      
      // ניסיון שליחה סינכרונית (Beacon API)
      const data = new Blob([JSON.stringify({
        content,
        emergency: true
      })], { type: 'application/json' });
      
      navigator.sendBeacon('/api/save/emergency', data);
      
    } catch (error) {
      console.error('Emergency save failed:', error);
    }
  }
  
  async handleConflict(localContent, serverVersion) {
    const dialog = this.createConflictDialog(localContent, serverVersion.content);
    document.body.appendChild(dialog);
    
    const result = await this.waitForUserDecision(dialog);
    
    switch (result) {
      case 'keep-local':
        // שמירת הגרסה המקומית
        this.forceSave(localContent);
        break;
        
      case 'keep-server':
        // שימוש בגרסה מהשרת
        this.editor.setValue(serverVersion.content);
        this.lastSavedContent = serverVersion.content;
        this.isDirty = false;
        break;
        
      case 'merge':
        // מיזוג הגרסאות
        const merged = await this.mergeVersions(localContent, serverVersion.content);
        this.editor.setValue(merged);
        this.save();
        break;
        
      case 'compare':
        // הצגת השוואה
        this.showDiffView(localContent, serverVersion.content);
        break;
    }
    
    dialog.remove();
  }
  
  createConflictDialog(local, server) {
    const dialog = document.createElement('div');
    dialog.className = 'conflict-dialog';
    dialog.innerHTML = `
      <div class="dialog-content">
        <h3>⚠️ זוהה קונפליקט בשמירה</h3>
        <p>הקובץ בשרת השתנה מאז השמירה האחרונה שלך.</p>
        
        <div class="conflict-preview">
          <div class="version-preview">
            <h4>הגרסה שלך</h4>
            <pre>${this.truncatePreview(local)}</pre>
          </div>
          <div class="version-preview">
            <h4>הגרסה בשרת</h4>
            <pre>${this.truncatePreview(server)}</pre>
          </div>
        </div>
        
        <div class="conflict-actions">
          <button data-action="keep-local">שמור את הגרסה שלי</button>
          <button data-action="keep-server">השתמש בגרסה מהשרת</button>
          <button data-action="merge">מזג את הגרסאות</button>
          <button data-action="compare">השווה גרסאות</button>
        </div>
      </div>
    `;
    
    return dialog;
  }
  
  saveToLocalStorage(content) {
    try {
      const key = `autoSave_${window.location.pathname}`;
      const data = {
        content,
        timestamp: Date.now(),
        url: window.location.href
      };
      
      localStorage.setItem(key, JSON.stringify(data));
      
      // ניהול גודל localStorage
      this.cleanupLocalStorage();
      
    } catch (error) {
      if (error.name === 'QuotaExceededError') {
        // נקה ושמור שוב
        this.clearOldAutoSaves();
        try {
          localStorage.setItem(key, JSON.stringify(data));
        } catch (e) {
          console.error('LocalStorage full:', e);
        }
      }
    }
  }
  
  restoreFromLocalStorage() {
    const key = `autoSave_${window.location.pathname}`;
    const saved = localStorage.getItem(key);
    
    if (saved) {
      try {
        const data = JSON.parse(saved);
        const age = Date.now() - data.timestamp;
        
        // שחזר רק אם השמירה מהיום האחרון
        if (age < 24 * 60 * 60 * 1000) {
          if (confirm('נמצאה טיוטה שמורה. האם לשחזר אותה?')) {
            this.editor.setValue(data.content);
            this.showNotification('הטיוטה שוחזרה', 'info');
          }
        }
      } catch (error) {
        console.error('Failed to restore from localStorage:', error);
      }
    }
  }
  
  setupIndicators() {
    // יצירת אינדיקטור שמירה
    const indicator = document.createElement('div');
    indicator.className = 'save-indicator';
    indicator.innerHTML = `
      <span class="indicator-icon"></span>
      <span class="indicator-text">שמור</span>
    `;
    
    document.querySelector('.editor-toolbar').appendChild(indicator);
    this.indicator = indicator;
  }
  
  updateIndicator(status) {
    const states = {
      'saved': { icon: '✓', text: 'שמור', class: 'saved' },
      'unsaved': { icon: '●', text: 'לא שמור', class: 'unsaved' },
      'saving': { icon: '⟳', text: 'שומר...', class: 'saving' },
      'error': { icon: '⚠', text: 'שגיאה', class: 'error' }
    };
    
    const state = states[status] || states.saved;
    
    this.indicator.className = `save-indicator ${state.class}`;
    this.indicator.querySelector('.indicator-icon').textContent = state.icon;
    this.indicator.querySelector('.indicator-text').textContent = state.text;
  }
  
  calculateChecksum(content) {
    // חישוב checksum פשוט
    let hash = 0;
    for (let i = 0; i < content.length; i++) {
      const char = content.charCodeAt(i);
      hash = ((hash << 5) - hash) + char;
      hash = hash & hash; // Convert to 32-bit integer
    }
    return hash.toString(16);
  }
  
  destroy() {
    if (this.intervalId) clearInterval(this.intervalId);
    if (this.beforeUnloadHandler) {
      window.removeEventListener('beforeunload', this.beforeUnloadHandler);
    }
    if (this.isDirty) {
      this.save(); // שמירה אחרונה
    }
  }
}
```

#### Fallback קליל לשמירה מקומית (localStorage)

במידה ולא נדרש המנגנון המלא, ניתן להוסיף שכבת Auto‑Save מקומית פשוטה שתמנע אובדן קוד בקריסות/ניתוק רשת:

```javascript
// minimal-local-autosave.js
const textarea = document.querySelector('textarea[name="code"]');
const KEY = `autosaveDraft_${location.pathname}`;
setInterval(() => {
  try {
    const value = window.editorManager ? window.editorManager.getValue() : (textarea?.value || '');
    localStorage.setItem(KEY, value);
  } catch (_) {}
}, 5000);

try {
  const draft = localStorage.getItem(KEY);
  if (draft && textarea && !textarea.value) textarea.value = draft;
} catch (_) {}
```

---
 
## 7. בדיקות מקיפות {#testing}

### מערכת בדיקות אוטומטית

```javascript
// tests/editor-comprehensive.test.js
import { EditorManager } from '../editor-manager.js';
import { PerformanceManager } from '../performance-manager.js';
import { SecurityManager } from '../security-manager.js';

describe('Editor Comprehensive Tests', () => {
  let editor, container;
  
  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    editor = new EditorManager();
  });
  
  afterEach(() => {
    editor.destroy();
    container.remove();
  });
  
  describe('Basic Functionality', () => {
    test('should initialize in simple mode by default', async () => {
      await editor.initEditor(container);
      expect(editor.currentEditor).toBe('simple');
    });
    
    test('should switch between editors seamlessly', async () => {
      await editor.initEditor(container, { value: 'test content' });
      await editor.toggleEditor();
      expect(editor.getValue()).toBe('test content');
    });
    
    test('should save preferences', () => {
      editor.savePreference('codemirror');
      expect(localStorage.getItem('preferredEditor')).toBe('codemirror');
    });
  });
  
  describe('Performance Tests', () => {
    test('should handle large files efficiently', async () => {
      const largeContent = 'x'.repeat(1000000); // 1MB
      const startTime = performance.now();
      
      await editor.initEditor(container, { value: largeContent });
      
      const loadTime = performance.now() - startTime;
      expect(loadTime).toBeLessThan(3000); // תחת 3 שניות
    });
    
    test('should not leak memory', async () => {
      const initialMemory = performance.memory?.usedJSHeapSize || 0;
      
      for (let i = 0; i < 10; i++) {
        await editor.initEditor(container, { value: 'test' });
        editor.destroy();
      }
      
      const finalMemory = performance.memory?.usedJSHeapSize || 0;
      const memoryIncrease = finalMemory - initialMemory;
      
      expect(memoryIncrease).toBeLessThan(10 * 1024 * 1024); // פחות מ-10MB
    });
    
    test('should debounce frequent changes', (done) => {
      let saveCount = 0;
      editor.save = jest.fn(() => saveCount++);
      
      // 10 שינויים מהירים
      for (let i = 0; i < 10; i++) {
        editor.setValue(`test ${i}`);
      }
      
      setTimeout(() => {
        expect(saveCount).toBeLessThan(3); // לא יותר מ-3 שמירות
        done();
      }, 1000);
    });
  });
  
  describe('Error Recovery', () => {
    test('should fallback when CDN fails', async () => {
      // סימולציה של כשלון CDN
      global.fetch = jest.fn(() => Promise.reject('Network error'));
      
      await editor.initEditor(container);
      expect(editor.currentEditor).toBe('simple');
    });
    
    test('should handle corrupt content gracefully', async () => {
      const corruptContent = '\x00\x01\x02'; // תוכן בינארי
      
      await expect(
        editor.initEditor(container, { value: corruptContent })
      ).resolves.not.toThrow();
    });
    
    test('should recover from editor crash', async () => {
      await editor.initEditor(container);
      
      // סימולציה של קריסה
      editor.cmInstance = null;
      
      await expect(editor.getValue()).resolves.toBeDefined();
    });
  });
  
  describe('Security Tests', () => {
    const security = new SecurityManager();
    
    test('should sanitize HTML content', () => {
      const dangerous = '<script>alert("XSS")</script><p>Safe</p>';
      const sanitized = security.sanitizer.sanitizeHTML(dangerous);
      
      expect(sanitized).not.toContain('<script>');
      expect(sanitized).toContain('<p>Safe</p>');
    });
    
    test('should detect malicious code', () => {
      const maliciousCode = 'eval("malicious code")';
      const result = security.sanitizer.sanitizeCode(maliciousCode);
      
      expect(console.warn).toHaveBeenCalledWith(
        expect.stringContaining('dangerous code')
      );
    });
    
    test('should enforce file size limits', () => {
      const hugeContent = 'x'.repeat(11 * 1024 * 1024); // 11MB
      
      expect(() => {
        security.validateContent(hugeContent);
      }).toThrow('Content too large');
    });
  });
  
  describe('Mobile Support', () => {
    test('should detect mobile devices', () => {
      const originalUA = navigator.userAgent;
      
      Object.defineProperty(navigator, 'userAgent', {
        value: 'iPhone',
        writable: true
      });
      
      const mobile = new MobileSupport();
      expect(mobile.isMobile).toBe(true);
      
      navigator.userAgent = originalUA;
    });
    
    test('should adjust font size for mobile', async () => {
      window.innerWidth = 375; // iPhone width
      
      await editor.initEditor(container);
      const styles = getComputedStyle(container.querySelector('.cm-content'));
      
      expect(parseInt(styles.fontSize)).toBeGreaterThanOrEqual(16);
    });
  });
  
  describe('Auto-save Tests', () => {
    test('should auto-save after changes', (done) => {
      const saveSpy = jest.spyOn(editor, 'save');
      
      editor.setValue('changed content');
      
      setTimeout(() => {
        expect(saveSpy).toHaveBeenCalled();
        done();
      }, 6000); // מעל debounce time
    });
    
    test('should handle save conflicts', async () => {
      // סימולציה של קונפליקט
      global.fetch = jest.fn()
        .mockResolvedValueOnce({
          ok: true,
          json: () => ({ 
            timestamp: Date.now() + 1000,
            content: 'server version'
          })
        });
      
      const result = await editor.autoSave.handleConflict(
        'local version',
        { content: 'server version', timestamp: Date.now() }
      );
      
      expect(result).toBeDefined();
    });
    
    test('should save to localStorage on failure', async () => {
      global.fetch = jest.fn(() => Promise.reject('Network error'));
      
      await editor.autoSave.save();
      
      const saved = localStorage.getItem(`autoSave_${window.location.pathname}`);
      expect(saved).toBeDefined();
    });
  });
  
  describe('Accessibility Tests', () => {
    test('should have proper ARIA attributes', async () => {
      await editor.initEditor(container);
      
      const editorEl = container.querySelector('[role="textbox"]');
      expect(editorEl).toBeDefined();
      expect(editorEl.getAttribute('aria-multiline')).toBe('true');
    });
    
    test('should support keyboard navigation', async () => {
      await editor.initEditor(container);
      
      const event = new KeyboardEvent('keydown', {
        key: 'F1',
        altKey: true
      });
      
      container.dispatchEvent(event);
      
      const helpModal = document.querySelector('.shortcuts-modal');
      expect(helpModal).toBeDefined();
    });
  });
  
  describe('Integration Tests', () => {
    test('should work with all language modes', async () => {
      const languages = ['python', 'javascript', 'html', 'css', 'sql'];
      
      for (const lang of languages) {
        await editor.initEditor(container, { language: lang });
        expect(editor.currentLanguage).toBe(lang);
      }
    });
    
    test('should sync with server correctly', async () => {
      global.fetch = jest.fn(() => 
        Promise.resolve({
          ok: true,
          json: () => ({ success: true })
        })
      );
      
      await editor.save();
      
      expect(fetch).toHaveBeenCalledWith(
        '/api/save',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' }
        })
      );
    });
  });
});

// E2E Tests using Playwright/Puppeteer
describe('E2E Tests', () => {
  test('full user workflow', async () => {
    // פתיחת הדפדפן
    const browser = await playwright.chromium.launch();
    const page = await browser.newPage();
    
    // ניווט לעמוד
    await page.goto('http://localhost:5000/edit');
    
    // בחירת CodeMirror
    await page.click('[data-action="toggle-editor"]');
    
    // כתיבת קוד
    await page.type('.cm-content', 'def hello():\n    print("Hello, World!")');
    
    // שמירה
    await page.keyboard.press('Control+S');
    
    // בדיקה שנשמר
    await page.waitForSelector('.save-indicator.saved');
    
    // סגירת הדפדפן
    await browser.close();
  });
});
```

---

## 8. תכונות נוספות {#additional-features}

### תוספות ושיפורים נוספים

```javascript
// additional-features.js

// 1. Collaborative Editing - עריכה משותפת
export class CollaborativeEditor {
  constructor(editor, websocketUrl) {
    this.editor = editor;
    this.ws = new WebSocket(websocketUrl);
    this.clientId = this.generateClientId();
    this.cursors = new Map();
    
    this.setupWebSocket();
    this.setupChangeTracking();
  }
  
  setupWebSocket() {
    this.ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      
      switch (data.type) {
        case 'change':
          this.applyRemoteChange(data);
          break;
        case 'cursor':
          this.updateRemoteCursor(data);
          break;
        case 'user-joined':
          this.handleUserJoined(data);
          break;
        case 'user-left':
          this.handleUserLeft(data);
          break;
      }
    };
  }
  
  applyRemoteChange(data) {
    // החלת שינויים מרחוק עם Operational Transform
    const change = this.transformChange(data.change);
    this.editor.applyChange(change, { origin: 'remote' });
  }
}

// 2. AI-Powered Code Suggestions
export class AICodeAssistant {
  constructor(editor) {
    this.editor = editor;
    this.apiKey = process.env.AI_API_KEY;
    this.cache = new Map();
  }
  
  async getSuggestions(context) {
    const cacheKey = this.getCacheKey(context);
    
    if (this.cache.has(cacheKey)) {
      return this.cache.get(cacheKey);
    }
    
    try {
      const response = await fetch('/api/ai/suggestions', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${this.apiKey}`
        },
        body: JSON.stringify({
          code: context.code,
          language: context.language,
          cursor: context.cursor
        })
      });
      
      const suggestions = await response.json();
      this.cache.set(cacheKey, suggestions);
      
      return suggestions;
    } catch (error) {
      console.error('AI suggestions failed:', error);
      return [];
    }
  }
}

// 3. Git Integration
export class GitIntegration {
  constructor(editor) {
    this.editor = editor;
    this.setupGutterMarkers();
  }
  
  async showDiff() {
    const currentContent = this.editor.getValue();
    const originalContent = await this.getOriginalContent();
    
    const diff = this.computeDiff(originalContent, currentContent);
    this.displayDiff(diff);
  }
  
  setupGutterMarkers() {
    // הוספת סימנים ב-gutter לשינויים
    this.editor.on('change', () => {
      this.updateGutterMarkers();
    });
  }
  
  updateGutterMarkers() {
    const changes = this.detectChanges();
    
    changes.forEach(change => {
      const marker = document.createElement('div');
      marker.className = `git-marker git-${change.type}`;
      marker.title = change.description;
      
      this.editor.setGutterMarker(change.line, 'git', marker);
    });
  }
}

// 4. Code Minimap
export class CodeMinimap {
  constructor(editor) {
    this.editor = editor;
    this.canvas = null;
    this.ctx = null;
    this.scale = 0.1;
    
    this.init();
  }
  
  init() {
    this.createCanvas();
    this.render();
    this.setupEventHandlers();
  }
  
  createCanvas() {
    const container = document.createElement('div');
    container.className = 'minimap-container';
    
    this.canvas = document.createElement('canvas');
    this.canvas.className = 'minimap-canvas';
    container.appendChild(this.canvas);
    
    this.ctx = this.canvas.getContext('2d');
    
    this.editor.dom.appendChild(container);
  }
  
  render() {
    const lines = this.editor.state.doc.lines;
    const lineHeight = 2;
    
    this.canvas.height = lines * lineHeight;
    this.canvas.width = 100;
    
    this.ctx.fillStyle = '#f0f0f0';
    this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    
    // ציור השורות
    lines.forEach((line, index) => {
      const width = Math.min(line.length * this.scale, this.canvas.width);
      const y = index * lineHeight;
      
      this.ctx.fillStyle = this.getLineColor(line);
      this.ctx.fillRect(0, y, width, lineHeight - 1);
    });
    
    // הדגשת האזור הנוכחי
    this.highlightViewport();
  }
  
  highlightViewport() {
    const viewport = this.editor.viewport;
    const y = viewport.from * 2;
    const height = (viewport.to - viewport.from) * 2;
    
    this.ctx.strokeStyle = '#4A90E2';
    this.ctx.lineWidth = 2;
    this.ctx.strokeRect(0, y, this.canvas.width, height);
  }
}

// 5. Smart Snippets
export class SmartSnippets {
  constructor(editor) {
    this.editor = editor;
    this.snippets = this.loadSnippets();
  }
  
  loadSnippets() {
    return {
      python: {
        'def': 'def ${1:function_name}(${2:params}):\n    ${3:pass}',
        'class': 'class ${1:ClassName}:\n    def __init__(self):\n        ${2:pass}',
        'for': 'for ${1:item} in ${2:iterable}:\n    ${3:pass}',
        'if': 'if ${1:condition}:\n    ${2:pass}',
        'try': 'try:\n    ${1:pass}\nexcept ${2:Exception} as e:\n    ${3:pass}'
      },
      javascript: {
        'func': 'function ${1:name}(${2:params}) {\n    ${3}\n}',
        'arrow': 'const ${1:name} = (${2:params}) => {\n    ${3}\n}',
        'class': 'class ${1:ClassName} {\n    constructor() {\n        ${2}\n    }\n}',
        'for': 'for (let ${1:i} = 0; ${1} < ${2:length}; ${1}++) {\n    ${3}\n}',
        'if': 'if (${1:condition}) {\n    ${2}\n}'
      }
    };
  }
  
  expandSnippet(trigger) {
    const language = this.editor.getLanguage();
    const snippet = this.snippets[language]?.[trigger];
    
    if (!snippet) return false;
    
    const expanded = this.parseSnippet(snippet);
    this.insertSnippet(expanded);
    
    return true;
  }
  
  parseSnippet(snippet) {
    // פרסור של placeholders
    const placeholders = [];
    const parsed = snippet.replace(/\$\{(\d+):([^}]*)\}/g, (match, index, defaultValue) => {
      placeholders.push({ index, defaultValue });
      return defaultValue;
    });
    
    return { text: parsed, placeholders };
  }
}

// 6. Terminal Integration
export class TerminalIntegration {
  constructor(editor) {
    this.editor = editor;
    this.terminal = null;
    this.setupTerminal();
  }
  
  setupTerminal() {
    // יצירת terminal panel
    const panel = document.createElement('div');
    panel.className = 'terminal-panel';
    panel.innerHTML = `
      <div class="terminal-header">
        <span>Terminal</span>
        <button class="close-terminal">×</button>
      </div>
      <div class="terminal-content"></div>
    `;
    
    // הוספת xterm.js
    this.terminal = new Terminal({
      theme: {
        background: '#1e1e1e',
        foreground: '#d4d4d4'
      }
    });
    
    this.terminal.open(panel.querySelector('.terminal-content'));
  }
  
  runCode() {
    const code = this.editor.getSelection() || this.editor.getValue();
    const language = this.editor.getLanguage();
    
    this.executeInTerminal(code, language);
  }
  
  async executeInTerminal(code, language) {
    const commands = {
      'python': `python -c "${code}"`,
      'javascript': `node -e "${code}"`,
      'bash': code
    };
    
    const command = commands[language];
    if (command) {
      this.terminal.write(`$ ${command}\n`);
      
      // שליחה לשרת לביצוע
      const result = await this.executeOnServer(command);
      this.terminal.write(result.output);
    }
  }
}
```

---

## 📝 סיכום ההמלצות

### Priority 1 - חובה למימוש מיידי
1. ✅ **Error Recovery** - חיוני ליציבות
2. ✅ **Mobile Support** - חובה לנגישות רחבה
3. ✅ **Security Enhancements** - קריטי לאבטחה
4. ✅ **Auto-save** - חיוני לחוויית משתמש

### Priority 2 - מומלץ מאוד
5. ⭐ **Accessibility** - חשוב לנגישות
6. ⭐ **Performance Optimization** - לשיפור הביצועים
7. ⭐ **Comprehensive Testing** - לאמינות

### Priority 3 - תכונות נוספות
8. 💡 **AI Integration** - שיפור הפרודוקטיביות
9. 💡 **Collaborative Editing** - לעבודת צוות
10. 💡 **Git Integration** - לניהול גרסאות

---

## 🚀 הטמעה מומלצת

```bash
# שלב 1: הוסף את הקבצים החדשים
git add accessibility-extensions.js
git add mobile-support.js
git add error-recovery.js
git add performance-manager.js
git add security-manager.js
git add auto-save-manager.js

# שלב 2: עדכן את המדריך הקיים
# הוסף את השיפורים למדריך המקורי

# שלב 3: בצע בדיקות
npm test

# שלב 4: צור PR
git commit -m "feat: Add comprehensive improvements to CodeMirror editor

- Added full accessibility support with ARIA and keyboard navigation
- Implemented mobile-responsive design with touch gestures
- Enhanced error recovery with automatic fallbacks
- Added smart auto-save with conflict resolution
- Improved security with CSP and content sanitization
- Optimized performance for large files with Web Workers
- Added comprehensive test suite"

git push origin feature/codemirror-improvements
```

בהצלחה! 🎉