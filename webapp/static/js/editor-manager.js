(function(){
  try { console.log('[EditorManager] Script loaded at:', new Date().toISOString(), 'url:', (typeof import.meta !== 'undefined' && import.meta && import.meta.url) ? import.meta.url : (document.currentScript && document.currentScript.src)); } catch(_) {}
  // מפה בסיסית בין סיומות לקיצורי שפות שנתמכות ב-CodeMirror אצלנו
  const EXTENSION_LANGUAGE_MAP = {
    py: 'python',
    pyw: 'python',
    js: 'javascript',
    mjs: 'javascript',
    cjs: 'javascript',
    jsx: 'javascript',
    ts: 'typescript',
    tsx: 'typescript',
    html: 'html',
    htm: 'html',
    css: 'css',
    scss: 'css',
    less: 'css',
    sql: 'sql',
    json: 'json',
    md: 'markdown',
    markdown: 'markdown',
    yml: 'yaml',
    yaml: 'yaml',
    xml: 'xml',
    sh: 'shell',
    bash: 'shell',
    zsh: 'shell',
    ps1: 'shell',
    go: 'go',
    java: 'java',
    cs: 'csharp',
    csharp: 'csharp',
    'd.ts': 'typescript'
  };
  class EditorManager {
    constructor() {
      this.currentEditor = this.loadPreference();
      this.cmInstance = null;
      this.textarea = null;
      this.loadingElement = null;
      this.isLoading = false;
      this.loadingPromise = null;
      // נשמור CDN אחיד לכל המודולים כדי למנוע חוסר תאימות בין מחלקות
      this._cdnUrl = null;
      // מצב משותף למעבר בין עורכים: "איפה המשתמש היה" (שורה אחרונה שנצפתה)
      this._sharedLastLine = 1;
      this._textareaLineHeightCache = null;
      try { console.log('[EditorManager] Initialized with preferred editor:', this.currentEditor); } catch(_) {}
    }

    _getTextareaLineHeightPx(textareaEl) {
      // ב-Textarea, getComputedStyle(lineHeight) יכול להחזיר "normal" ולכן parseFloat נכשל.
      // כדי שחישוב שורה לפי scrollTop יהיה יציב, ננסה להפיק line-height בפיקסלים בצורה בטוחה.
      try {
        const ta = textareaEl;
        if (!ta || !window.getComputedStyle) return 19; // fallback סביר

        if (!this._textareaLineHeightCache) {
          this._textareaLineHeightCache = new WeakMap();
        }
        const cached = this._textareaLineHeightCache.get(ta);
        if (cached && typeof cached === 'number' && cached > 0) {
          return cached;
        }

        const cs = window.getComputedStyle(ta);
        const lhRaw = cs ? cs.lineHeight : '';
        const lh = parseFloat(lhRaw);
        if (lh && !Number.isNaN(lh) && lh > 0) {
          this._textareaLineHeightCache.set(ta, lh);
          return lh;
        }

        // אם line-height הוא "normal" (או משהו לא מספרי) – נמדוד בפועל באמצעות probe.
        try {
          const body = document && document.body;
          if (body) {
            const probe = document.createElement('div');
            probe.style.position = 'absolute';
            probe.style.visibility = 'hidden';
            probe.style.pointerEvents = 'none';
            probe.style.whiteSpace = 'pre';
            probe.style.padding = '0';
            probe.style.margin = '0';
            probe.style.border = '0';
            // העתקה של סטייל פונט רלוונטי
            try { probe.style.fontFamily = cs.fontFamily; } catch(_) {}
            try { probe.style.fontSize = cs.fontSize; } catch(_) {}
            try { probe.style.fontWeight = cs.fontWeight; } catch(_) {}
            try { probe.style.fontStyle = cs.fontStyle; } catch(_) {}
            try { probe.style.letterSpacing = cs.letterSpacing; } catch(_) {}
            try { probe.style.lineHeight = cs.lineHeight; } catch(_) {}

            body.appendChild(probe);
            let h1 = 0;
            let h2 = 0;
            try {
              probe.textContent = 'X';
              h1 = probe.getBoundingClientRect().height || 0;
              probe.textContent = 'X\nX';
              h2 = probe.getBoundingClientRect().height || 0;
            } finally {
              try { probe.remove(); } catch(_) {}
            }
            const measured = (h2 > 0 && h1 > 0) ? (h2 - h1) : 0;
            if (measured && measured > 0) {
              this._textareaLineHeightCache.set(ta, measured);
              return measured;
            }
            if (h2 && h2 > 0) {
              const approx = h2 / 2;
              if (approx > 0) {
                this._textareaLineHeightCache.set(ta, approx);
                return approx;
              }
            }
          }
        } catch(_) {}

        const fsRaw = cs ? cs.fontSize : '';
        const fs = parseFloat(fsRaw);
        if (fs && !Number.isNaN(fs) && fs > 0) {
          const approx = fs * 1.2; // הערכה שמרנית יותר ל-"normal"
          this._textareaLineHeightCache.set(ta, approx);
          return approx;
        }
      } catch(_) {}
      return 19;
    }

    loadPreference() {
      try {
        // קדימות: localStorage, אחר כך העדפת שרת (אם קיימת), ולבסוף ברירת מחדל codemirror
        const saved = localStorage.getItem('preferredEditor');
        if (saved === 'codemirror' || saved === 'simple') return saved;
        const serverPref = (window.__serverPreferredEditor || '').toLowerCase();
        if (serverPref === 'codemirror' || serverPref === 'simple') return serverPref;
      } catch(_) {}
      // ברירת מחדל חדשה: עורך מתקדם (CodeMirror)
      return 'codemirror';
    }

    savePreference(editorType) {
      try { localStorage.setItem('preferredEditor', editorType); } catch(_) {}
      try {
        // שולחים לשני נתיבי API תואמים לאחור; אחד מהם ייקלט בהתאם לדיפלוי
        fetch('/api/ui_prefs', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ editor: editorType })
        }).catch(()=>{});
        fetch('/api/user/preferences', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ editor_type: editorType })
        }).catch(()=>{});
      } catch(_) {}
    }

    async initEditor(container, options = {}) {
      const { language = 'text', value = '', theme = 'dark' } = options;
      try { console.log('[EditorManager] initEditor called with:', { language, theme, valueLength: (typeof value === 'string' ? value.length : 0) }); } catch(_) {}
      this.textarea = container.querySelector('textarea[name="code"]');
      if (!this.textarea) { try { console.warn('[EditorManager] Textarea not found in container'); } catch(_) {} return; }
      try { console.log('[EditorManager] Textarea found:', this.textarea); } catch(_) {}
      try {
        this.textarea.classList.add('editor-textarea');
        this.textarea.setAttribute('dir', 'ltr');
        this.textarea.style.direction = 'ltr';
        this.textarea.style.textAlign = 'left';
      } catch(_) {}

      let fallback = false;
      if (this.currentEditor === 'codemirror') {
        try {
          console.log('[EditorManager] Initializing CodeMirror editor...');
          await this.initCodeMirror(container, { language, value, theme });
        } catch (e) {
          // אם Codemirror נכשל – ניפול חזרה לפשוט ונשמור העדפה
          console.warn('Falling back to simple editor due to CM init error', e);
          this.currentEditor = 'simple';
          this.savePreference('simple');
          this.initSimpleEditor(container, { value });
          fallback = true;
        }
      } else {
        this.initSimpleEditor(container, { value });
      }
      // הוסף את כפתור המתג פעם אחת, וטקסט תואם למצב בפועל
      this.addSwitcherButton(container);
      if (fallback) {
        try {
          const btn = container.querySelector('.editor-switcher .btn-switch-editor span');
          if (btn) btn.textContent = 'עורך מתקדם';
          const switcherEl = container.querySelector('.editor-switcher');
          if (switcherEl) this.updateInfoBanner(switcherEl);
        } catch(_) {}
      }
    }

    initSimpleEditor(container, { value }) {
      try {
        if (this.cmInstance) {
          // העתקת התוכן חזרה ל-textarea והרס העורך
          try { this.textarea.value = this.cmInstance.state.doc.toString(); } catch(_) {}
          this.teardownSelectionFix();
          try { this.cmInstance.destroy(); } catch(_) {}
          this.cmInstance = null;
        }
        this.textarea.style.display = 'block';
        const existing = container.querySelector('.codemirror-container');
        if (existing) existing.remove();
        if (typeof value === 'string' && value && this.textarea.value !== value) {
          this.textarea.value = value;
        }
      } catch(_) {}
    }

    async initCodeMirror(container, { language, value, theme }) {
      // אם יש כבר טעינה פעילה, נחכה שתסתיים כדי למנוע מצב ביניים
      if (this.isLoading && this.loadingPromise) {
        await this.loadingPromise;
        if (!this.cmInstance) {
          throw new Error('codemirror_init_failed');
        }
        return;
      }

      this.loadingPromise = (async () => {
        try {
          this.isLoading = true;
          this.showLoading(container);
          try { console.log('[EditorManager] initCodeMirror called'); } catch(_) {}
          try { console.log('[EditorManager] Loading indicator shown'); } catch(_) {}
          // הסתרת textarea
          this.textarea.style.display = 'none';

          // יצירת container
          const cmWrapper = document.createElement('div');
          cmWrapper.className = 'codemirror-container';
          this.textarea.parentNode.insertBefore(cmWrapper, this.textarea.nextSibling);

          if (!window.CodeMirror6) {
            try { console.log('[EditorManager] window.CodeMirror6 not found, loading modules...'); } catch(_) {}
            // מגן נגד תקיעת טעינה שקטה של מודולים חיצוניים
            // מוגדל ל~30s כדי לאפשר כשל/ניסיון בכל CDN (8s * 3) + שוליים
            await this.withTimeout(this.loadCodeMirror(), 30000, 'codemirror_core_load');
          }

          // אימות בסיסי שהמודולים נטענו עם ה-API הצפוי
          if (!window.CodeMirror6 || !window.CodeMirror6.EditorView || !window.CodeMirror6.EditorState) {
            throw new Error('codemirror_modules_missing');
          }
          const { EditorState, EditorView, basicSetup, Compartment, languageCompartment, themeCompartment } = window.CodeMirror6;

          const langSupport = await this.withTimeout(this.getLanguageSupport(language), 12000, 'codemirror_lang_load');
          // זיהוי theme אפקטיבי מה-HTML (dark/dim => oneDark, custom => no theme)
          // 🎨 Custom themes: לא טוענים oneDark כדי לתת ל-syntax_css CSS classes לעבוד
          const htmlTheme = (typeof document !== 'undefined' && document.documentElement) ? document.documentElement.getAttribute('data-theme') : '';
          const effectiveTheme = (htmlTheme === 'custom') ? 'custom' : ((htmlTheme === 'dark' || htmlTheme === 'dim' || htmlTheme === 'nebula') ? 'dark' : theme);
          const themeExt = await this.withTimeout(this.getTheme(effectiveTheme), 12000, 'codemirror_theme_load');

          // 🎨 Custom themes: טוען dynamic syntax highlighter במקום classHighlighter
          // getSyntaxHighlighter() מחזירה syntaxHighlighting(dynamicStyle) עם צבעים מ-syntax_colors,
          // או syntaxHighlighting(classHighlighter) כ-fallback אם אין syntax_colors
          let customSyntaxHighlighter = null;
          if (htmlTheme === 'custom' && window.CodeMirror6.getSyntaxHighlighter) {
            try {
              customSyntaxHighlighter = window.CodeMirror6.getSyntaxHighlighter();
            } catch(_) {}
          }

          const debouncedSync = this.debounce((val) => {
            this.textarea.value = val;
            try { this.textarea.dispatchEvent(new Event('input', { bubbles: true })); } catch(_) {}
          }, 100);

          const state = EditorState.create({
            doc: (this.textarea.value || value || ''),
            extensions: [
              ...basicSetup,
              languageCompartment.of(langSupport || []),
              themeCompartment.of(themeExt || []),
              // 🎨 אם יש custom theme עם syntax highlighter, מוסיפים אותו כדי לדרוס את ה-classHighlighter שב-basicSetup
              ...(customSyntaxHighlighter ? [customSyntaxHighlighter] : []),
              EditorView.lineWrapping,
              EditorView.updateListener.of((update) => {
                if (update.docChanged) {
                  debouncedSync(update.state.doc.toString());
                }
              })
            ]
          });

          this.cmInstance = new EditorView({ state, parent: cmWrapper });
          try { console.log('[EditorManager] CodeMirror editor instance created'); } catch(_) {}
          this.registerSelectionFix();
        } catch (e) {
          console.error('CodeMirror init failed', e);
          this.currentEditor = 'simple';
          this.initSimpleEditor(container, { value });
          try {
            // הסרת באנרי שגיאה קודמים כדי למנוע הצטברות
            container.querySelectorAll('.editor-error-banner').forEach(el => el.remove());
            // הודעת שגיאה ידידותית למשתמש ופעולת fallback
            const errBanner = document.createElement('div');
            errBanner.className = 'editor-error-banner alert alert-error';
            errBanner.style.marginTop = '.5rem';
            errBanner.textContent = 'טעינת העורך המתקדם נכשלה (' + (e.message || 'unknown error') + '). הוחזר לעורך הפשוט.';
            container.appendChild(errBanner);
          } catch(_) {}
          throw e;
        } finally {
          this.hideLoading(container);
          this.isLoading = false;
        }
      })();

      return await this.loadingPromise;
    }

    addSwitcherButton(container) {
      if (container.querySelector('.editor-switcher')) return;
      const switcher = document.createElement('div');
      switcher.className = 'editor-switcher';
      switcher.innerHTML = `
        <div class="editor-switcher-row">
          <div class="editor-switcher-actions">
            <button type="button" class="btn-switch-editor" title="החלף עורך">
              <i class="fas fa-exchange-alt"></i>
              <span>${this.currentEditor === 'simple' ? 'עורך מתקדם' : 'עורך פשוט'}</span>
            </button>
            <div class="editor-clipboard-actions" role="group" aria-label="פעולות עריכה">
              <button type="button" class="btn-editor-clip btn-editor-select" title="בחר את כל הקוד">
                <i class="fas fa-arrows-alt"></i>
                <span>בחר הכל</span>
              </button>
              <button type="button" class="btn-editor-clip btn-editor-copy" title="העתק את הקוד">
                <i class="far fa-copy"></i>
                <span>העתק</span>
              </button>
              <button type="button" class="btn-editor-clip btn-editor-paste" title="הדבק מהלוח">
                <i class="fas fa-paste"></i>
                <span>הדבק</span>
              </button>
            </div>
          </div>
          <span class="editor-info-primary${this.currentEditor === 'codemirror' ? ' is-keyboard-hint' : ''}">${this.currentEditor === 'codemirror' ? '<i class="fas fa-keyboard"></i> קיצורי מקלדת זמינים' : '<i class="fas fa-info-circle"></i> עורך טקסט בסיסי'}</span>
        </div>
        <div class="editor-info">
          <span class="editor-info-status" aria-live="polite"></span>
        </div>
      `;
      const codeLabel = container.querySelector('label') || container;
      codeLabel.parentNode.insertBefore(switcher, codeLabel.nextSibling);

      const toggleBtn = switcher.querySelector('.btn-switch-editor');
      toggleBtn.addEventListener('click', async () => {
        // לפני החלפת עורך: נזכור את השורה האחרונה שהמשתמש "עומד עליה" (לפי גלילה/viewport)
        const lastLine = this.getCurrentVisibleLine() || 1;
        this._sharedLastLine = lastLine;
        const prev = this.currentEditor;
        this.currentEditor = prev === 'simple' ? 'codemirror' : 'simple';
        if (this.currentEditor === 'codemirror') {
          const lang = this.getSelectedLanguage() || 'text';
          try {
            await this.initCodeMirror(container, { language: lang, value: this.textarea.value, theme: 'dark' });
          } catch (e) {
            this.currentEditor = 'simple';
            this.initSimpleEditor(container, { value: this.textarea.value });
          }
        } else {
          this.initSimpleEditor(container, { value: this.cmInstance ? this.cmInstance.state.doc.toString() : this.textarea.value });
        }
        // אחרי שהעורך החדש מוכן: החזר את המשתמש לאותה שורה (מיקום משותף בין העורכים)
        try {
          const targetLine = this._sharedLastLine || lastLine || 1;
          this._scheduleRestoreLinePosition(targetLine);
        } catch(_) {}
        this.savePreference(this.currentEditor);
        try {
          const label = switcher.querySelector('.btn-switch-editor span');
          if (label) label.textContent = this.currentEditor === 'simple' ? 'עורך מתקדם' : 'עורך פשוט';
        } catch(_) {}
        this.updateInfoBanner(switcher);
      });

      const selectBtn = switcher.querySelector('.btn-editor-select');
      if (selectBtn) {
        selectBtn.addEventListener('click', () => this.handleSelectAll(switcher));
      }
      const copyBtn = switcher.querySelector('.btn-editor-copy');
      if (copyBtn) {
        copyBtn.addEventListener('click', () => this.handleClipboardCopy(switcher));
      }
      const pasteBtn = switcher.querySelector('.btn-editor-paste');
      if (pasteBtn) {
        pasteBtn.addEventListener('click', () => this.handleClipboardPaste(switcher));
      }
    }

    getSelectedLanguage() {
      try {
        const sel = document.getElementById('languageSelect') || document.getElementById('language');
        const val = sel && sel.value;
        if (typeof val === 'string' && val.trim()) return val;
      } catch(_) {}
      return null;
    }

    inferLanguageFromFilename(filename) {
      try {
        if (!filename || typeof filename !== 'string') {
          return null;
        }
        const normalized = filename.trim().toLowerCase();
        if (!normalized) {
          return null;
        }
        const sanitized = normalized.split(/[\\/]/).pop();
        if (!sanitized || sanitized.endsWith('.')) {
          return null;
        }
        const parts = sanitized.split('.');
        if (parts.length < 2) {
          return null;
        }
        if (parts.length >= 2) {
          const lastTwo = parts.slice(-2).join('.');
          if (EXTENSION_LANGUAGE_MAP[lastTwo]) {
            return EXTENSION_LANGUAGE_MAP[lastTwo];
          }
        }
        const ext = parts[parts.length - 1];
        return EXTENSION_LANGUAGE_MAP[ext] || null;
      } catch(_) {
        return null;
      }
    }

    updateInfoBanner(switcher) {
      try {
        const target = switcher ? switcher.querySelector('.editor-info-primary') : null;
        if (!target) return;
        const isCodeMirror = this.currentEditor === 'codemirror';
        target.innerHTML = isCodeMirror
          ? '<i class="fas fa-keyboard"></i> קיצורי מקלדת זמינים'
          : '<i class="fas fa-info-circle"></i> עורך טקסט בסיסי';
          
        if (isCodeMirror) {
          target.classList.add('is-keyboard-hint');
        } else {
          target.classList.remove('is-keyboard-hint');
        }
      } catch(_) {}
    }

    // --- Shared position (line) handling between editors ---
    getCurrentVisibleLine() {
      // עדיפות: שורה עליונה שנראית (viewport) כדי לשמר גלילה גם אם הסמן לא זז.
      // fallback: שורת הסמן.
      try {
        if (this.cmInstance && this.cmInstance.state) {
          const view = this.cmInstance;
          try {
            // דרך יציבה: שימוש ב-lineBlockAtHeight עם scrollTop (CM6)
            if (typeof view.lineBlockAtHeight === 'function' && view.scrollDOM && typeof view.scrollDOM.scrollTop === 'number') {
              const block = view.lineBlockAtHeight((view.scrollDOM.scrollTop || 0) + 8);
              const topLine = view.state.doc.lineAt(block.from).number;

              // אם הסמן בתוך ה-viewport – נשמור את שורת הסמן (זה מה שהמשתמש "עומד עליו")
              let cursorLine = null;
              try {
                const head = (view.state.selection && view.state.selection.main) ? view.state.selection.main.head : 0;
                cursorLine = view.state.doc.lineAt(head).number;
              } catch(_) {}

              try {
                const height = (view.scrollDOM && typeof view.scrollDOM.clientHeight === 'number') ? view.scrollDOM.clientHeight : 0;
                if (height && height > 0) {
                  const bottomBlock = view.lineBlockAtHeight((view.scrollDOM.scrollTop || 0) + height - 8);
                  const bottomLine = view.state.doc.lineAt(bottomBlock.from).number;
                  if (cursorLine && cursorLine >= topLine && cursorLine <= bottomLine) {
                    return cursorLine;
                  }
                }
              } catch(_) {}

              if (typeof topLine === 'number' && topLine > 0) return topLine;
            }
          } catch(_) {}
          try {
            // fallback: viewport (אם זמין)
            if (view.viewport && typeof view.viewport.from === 'number') {
              const topLine = view.state.doc.lineAt(view.viewport.from).number;
              if (typeof topLine === 'number' && topLine > 0) return topLine;
            }
          } catch(_) {}
          try {
            const head = (view.state.selection && view.state.selection.main) ? view.state.selection.main.head : 0;
            const ln = view.state.doc.lineAt(head).number;
            if (typeof ln === 'number' && ln > 0) return ln;
          } catch(_) {}
        }
      } catch(_) {}

      try {
        if (this.textarea) {
          const ta = this.textarea;
          const value = ta.value || '';
          const totalLines = Math.max(1, (value.split('\n').length || 1));

          // חישוב שורה של הסמן (cursor)
          let cursorLine = 1;
          try {
            const pos = (typeof ta.selectionStart === 'number') ? ta.selectionStart : 0;
            const before = value.slice(0, Math.max(0, Math.min(pos, value.length)));
            cursorLine = before.split('\n').length || 1;
            cursorLine = Math.min(totalLines, Math.max(1, cursorLine));
          } catch(_) { cursorLine = 1; }

          // חישוב לפי scrollTop/lineHeight (עם fallback בטוח ל-"normal")
          try {
            const lh = this._getTextareaLineHeightPx(ta);
            const topLine = Math.min(totalLines, Math.max(1, Math.floor((ta.scrollTop || 0) / lh) + 1));
            const visibleLines = Math.max(1, Math.floor(((ta.clientHeight || 0) * 1.0) / lh));
            const bottomLine = Math.min(totalLines, Math.max(topLine, topLine + visibleLines - 1));

            // אם הסמן נמצא בתוך ה-viewport, זה בדרך כלל "הקו הפעיל" שהמשתמש מצפה לשמור.
            if (cursorLine >= topLine && cursorLine <= bottomLine) {
              return cursorLine;
            }
            return topLine;
          } catch(_) {}
          return cursorLine || 1;
        }
      } catch(_) {}

      return 1;
    }

    _scheduleRestoreLinePosition(lineNumber) {
      // לפעמים (בעיקר ב-CodeMirror) ה-layout עוד לא הסתיים מיד אחרי init,
      // ואז scroll/selection יכולים "לקפוץ". נעשה ניסיון אחד אחרי frame,
      // ואם עדיין לא הגענו לשורה הרצויה – ניסיון נוסף קצר.
      const target = Math.max(1, parseInt(lineNumber || 1, 10) || 1);
      const attempt = () => {
        try { this.restoreLinePosition(target); } catch(_) {}
      };
      const verifyAndMaybeRetry = () => {
        try {
          const current = this.getCurrentVisibleLine() || 1;
          if (Math.abs(current - target) > 1) {
            attempt();
          }
        } catch(_) {}
      };

      try {
        if (typeof requestAnimationFrame === 'function') {
          requestAnimationFrame(() => {
            attempt();
            setTimeout(verifyAndMaybeRetry, 60);
          });
          return;
        }
      } catch(_) {}

      setTimeout(() => {
        attempt();
        setTimeout(verifyAndMaybeRetry, 60);
      }, 0);
    }

    restoreLinePosition(lineNumber) {
      const line = Math.max(1, parseInt(lineNumber || 1, 10) || 1);
      try {
        if (this.cmInstance && this.cmInstance.state) {
          const view = this.cmInstance;
          const maxLines = Math.max(1, view.state.doc.lines || 1);
          const targetLine = Math.min(maxLines, Math.max(1, line));
          const info = view.state.doc.line(targetLine);
          const pos = info ? info.from : 0;
          try { view.focus(); } catch(_) {}
          view.dispatch({
            selection: { anchor: pos },
            scrollIntoView: true
          });
          return true;
        }
      } catch(_) {}

      try {
        if (this.textarea) {
          const ta = this.textarea;
          const value = ta.value || '';
          const lines = value.split('\n');
          const maxLines = Math.max(1, lines.length || 1);
          const targetLine = Math.min(maxLines, Math.max(1, line));
          // מצא offset לתחילת השורה (1-based)
          let offset = 0;
          for (let i = 0; i < targetLine - 1; i++) {
            offset += (lines[i] || '').length + 1; // + '\n'
          }
          try { ta.focus(); } catch(_) {}
          try { ta.setSelectionRange(offset, offset); } catch(_) {}
          // נסה ליישר גלילה לשורה
          try {
            const lh = this._getTextareaLineHeightPx(ta);
            ta.scrollTop = Math.max(0, (targetLine - 1) * lh);
          } catch(_) {}
          return true;
        }
      } catch(_) {}

      return false;
    }

    getEditorContent() {
      try {
        if (this.cmInstance && this.cmInstance.state) {
          return this.cmInstance.state.doc.toString();
        }
      } catch(_) {}
      try {
        if (this.textarea) {
          return this.textarea.value || '';
        }
      } catch(_) {}
      return '';
    }

    getSelectedTextOrAll() {
      // מחזיר טקסט מסומן (אם יש) עם fallback לכל התוכן.
      // תומך גם ב-CodeMirror 6 (כולל multi-selection) וגם ב-textarea רגיל.
      try {
        if (this.cmInstance && this.cmInstance.state) {
          const view = this.cmInstance;
          const sel = view.state.selection;
          const ranges = sel && Array.isArray(sel.ranges) ? sel.ranges : [];
          const nonEmpty = ranges.filter(r => r && typeof r.from === 'number' && typeof r.to === 'number' && r.from !== r.to);
          if (nonEmpty.length > 0) {
            const parts = [];
            for (const r of nonEmpty) {
              const from = Math.max(0, Math.min(r.from, r.to));
              const to = Math.max(0, Math.max(r.from, r.to));
              try {
                parts.push(view.state.sliceDoc(from, to));
              } catch(_) {
                try {
                  parts.push(view.state.doc.sliceString(from, to));
                } catch(_) {}
              }
            }
            const text = parts.join('\n');
            if (typeof text === 'string' && text.length > 0) {
              return { text, usedSelection: true };
            }
          }
          // חשוב: אם CodeMirror פעיל אבל אין בחירה, אסור ליפול ל-textarea המוסתר
          // כי הוא עלול להכיל selectionStart/End ישנים ותוכן לא מסונכרן מיידית.
          return { text: view.state.doc.toString(), usedSelection: false };
        }
      } catch(_) {}

      try {
        if (this.textarea) {
          const ta = this.textarea;
          const value = ta.value || '';
          const start = (typeof ta.selectionStart === 'number') ? ta.selectionStart : 0;
          const end = (typeof ta.selectionEnd === 'number') ? ta.selectionEnd : start;
          const from = Math.max(0, Math.min(start, end, value.length));
          const to = Math.max(0, Math.min(Math.max(start, end), value.length));
          if (to > from) {
            const selectedText = value.substring(from, to);
            if (typeof selectedText === 'string' && selectedText.length > 0) {
              return { text: selectedText, usedSelection: true };
            }
          }
        }
      } catch(_) {}

      return { text: this.getEditorContent() || '', usedSelection: false };
    }

    getSelectionRange() {
      // מחזיר טווח בחירה/סמן נוכחי (from/to) עבור העורך הפעיל.
      // שימושי במיוחד כשפותחים prompt שעלול לגרום לאיבוד focus/selection.
      try {
        if (this.cmInstance && this.cmInstance.state) {
          const view = this.cmInstance;
          const mainSel = (view.state.selection && view.state.selection.main) ? view.state.selection.main : null;
          const from = mainSel ? Math.max(0, Math.min(mainSel.from, mainSel.to)) : view.state.doc.length;
          const to = mainSel ? Math.max(0, Math.max(mainSel.from, mainSel.to)) : view.state.doc.length;
          return { from, to };
        }
      } catch(_) {}

      try {
        if (this.textarea) {
          const ta = this.textarea;
          const value = ta.value || '';
          const start = (typeof ta.selectionStart === 'number') ? ta.selectionStart : 0;
          const end = (typeof ta.selectionEnd === 'number') ? ta.selectionEnd : start;
          const from = Math.max(0, Math.min(start, end, value.length));
          const to = Math.max(0, Math.min(Math.max(start, end), value.length));
          return { from, to };
        }
      } catch(_) {}

      return { from: 0, to: 0 };
    }

    insertTextAtRange(nextText, from, to) {
      const text = typeof nextText === 'string' ? nextText : '';
      if (!text) return false;
      const fRaw = (typeof from === 'number' && Number.isFinite(from)) ? from : 0;
      const tRaw = (typeof to === 'number' && Number.isFinite(to)) ? to : fRaw;
      const f = Math.max(0, Math.min(fRaw, tRaw));
      const t = Math.max(0, Math.max(fRaw, tRaw));

      // CodeMirror: החלפה בטווח מפורש (שומר על הטווח גם אחרי blur/prompt)
      try {
        if (this.cmInstance && this.cmInstance.state) {
          const view = this.cmInstance;
          const docLen = view.state.doc.length;
          const fromSafe = Math.max(0, Math.min(f, docLen));
          const toSafe = Math.max(0, Math.min(t, docLen));
          try { view.focus(); } catch(_) {}
          view.dispatch({
            changes: { from: fromSafe, to: toSafe, insert: text },
            selection: { anchor: fromSafe + text.length },
            scrollIntoView: true
          });
          return true;
        }
      } catch(_) {}

      // textarea: החלפה בטווח מפורש תוך שמירה על Undo/Redo
      try {
        if (this.textarea) {
          const ta = this.textarea;
          const value = ta.value || '';
          const fromSafe = Math.max(0, Math.min(f, value.length));
          const toSafe = Math.max(0, Math.min(t, value.length));
          try { ta.focus(); } catch(_) {}

          if (typeof ta.setRangeText === 'function') {
            ta.setRangeText(text, fromSafe, toSafe, 'end');
          } else if (document.execCommand && typeof document.execCommand === 'function') {
            try { ta.setSelectionRange(fromSafe, toSafe); } catch(_) {}
            document.execCommand('insertText', false, text);
          } else {
            const nextValue = value.slice(0, fromSafe) + text + value.slice(toSafe);
            ta.value = nextValue;
            const caret = fromSafe + text.length;
            try { ta.setSelectionRange(caret, caret); } catch(_) {}
          }

          try { ta.dispatchEvent(new Event('input', { bubbles: true })); } catch(_) {}
          return true;
        }
      } catch(_) {}

      return false;
    }

    setEditorContent(nextValue) {
      const value = typeof nextValue === 'string' ? nextValue : '';
      try {
        if (this.cmInstance && this.cmInstance.state) {
          const view = this.cmInstance;
          view.dispatch({
            changes: { from: 0, to: view.state.doc.length, insert: value },
            selection: { anchor: value.length }
          });
        }
      } catch(_) {}
      try {
        if (this.textarea) {
          this.textarea.value = value;
          this.textarea.dispatchEvent(new Event('input', { bubbles: true }));
        }
      } catch(_) {}
    }

    insertTextAtCursor(nextText) {
      const text = typeof nextText === 'string' ? nextText : '';
      if (!text) return false;

      // CodeMirror: החלף בחירה/הדבק בנקודת הסמן
      try {
        if (this.cmInstance && this.cmInstance.state) {
          const view = this.cmInstance;
          const mainSel = (view.state.selection && view.state.selection.main) ? view.state.selection.main : null;
          const from = mainSel ? mainSel.from : view.state.doc.length;
          const to = mainSel ? mainSel.to : view.state.doc.length;
          try { view.focus(); } catch(_) {}
          view.dispatch({
            changes: { from, to, insert: text },
            selection: { anchor: from + text.length },
            scrollIntoView: true
          });
          return true;
        }
      } catch(_) {}

      // עורך פשוט (textarea): החלף בחירה/הדבק בנקודת הסמן
      try {
        if (this.textarea) {
          const ta = this.textarea;
          const value = ta.value || '';
          const start = (typeof ta.selectionStart === 'number') ? ta.selectionStart : value.length;
          const end = (typeof ta.selectionEnd === 'number') ? ta.selectionEnd : start;
          try { ta.focus(); } catch(_) {}

          // חשוב: להימנע משינוי ישיר של value כדי לשמור Undo/Redo
          if (typeof ta.setRangeText === 'function') {
            ta.setRangeText(text, start, end, 'end');
          } else if (document.execCommand && typeof document.execCommand === 'function') {
            try { ta.setSelectionRange(start, end); } catch(_) {}
            document.execCommand('insertText', false, text);
          } else {
            // fallback אחרון - עלול לשבור Undo/Redo
            const nextValue = value.slice(0, start) + text + value.slice(end);
            ta.value = nextValue;
            const caret = start + text.length;
            try { ta.setSelectionRange(caret, caret); } catch(_) {}
          }

          try { ta.dispatchEvent(new Event('input', { bubbles: true })); } catch(_) {}
          return true;
        }
      } catch(_) {}

      return false;
    }

    async handleClipboardCopy(switcher) {
      const { text: content, usedSelection } = this.getSelectedTextOrAll();
      let success = false;
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(content);
          success = true;
        }
      } catch (err) {
        console.warn('clipboard write failed', err);
      }
      if (!success) {
        try {
          const helper = document.createElement('textarea');
          helper.value = content;
          helper.setAttribute('readonly', '');
          helper.style.position = 'fixed';
          helper.style.opacity = '0';
          helper.style.pointerEvents = 'none';
          document.body.appendChild(helper);
          helper.focus();
          helper.select();
          helper.setSelectionRange(0, helper.value.length);
          success = document.execCommand('copy');
          helper.remove();
        } catch (err) {
          console.warn('execCommand copy failed', err);
          success = false;
        }
      }
      this.showClipboardNotice(
        switcher,
        success ? (usedSelection ? 'הקטע הנבחר הועתק' : 'כל הקוד הועתק') : 'נכשלה העתקה'
      );
    }

    async handleClipboardPaste(switcher) {
      let text = '';
      let usedPrompt = false;
      try {
        if (navigator.clipboard && navigator.clipboard.readText) {
          text = await navigator.clipboard.readText();
        } else {
          usedPrompt = true;
          text = window.prompt('הדבק כאן את הקוד שברצונך להכניס לעורך:') || '';
        }
      } catch (err) {
        console.warn('clipboard read failed', err);
        usedPrompt = true;
        text = window.prompt('הדבק כאן את הקוד שברצונך להכניס לעורך:') || '';
      }
      if (!text) {
        this.showClipboardNotice(switcher, usedPrompt ? 'לא הוזן טקסט' : 'הלוח ריק');
        return;
      }
      // התנהגות רצויה: הדבקה במיקום הסמן בלבד (או החלפה אם מסומן טקסט)
      const ok = this.insertTextAtCursor(text);
      if (!ok) {
        // fallback נדיר: אם לא הצלחנו לזהות סמן/בחירה, לא נחסום את המשתמש
        this.setEditorContent(text);
      }
      this.showClipboardNotice(switcher, 'הטקסט הודבק');
    }

    showClipboardNotice(switcher, message) {
      if (!switcher) return;
      try {
        const status = switcher.querySelector('.editor-info-status');
        if (!status) return;
        status.textContent = message || '';
        if (!this._statusTimers) {
          this._statusTimers = new WeakMap();
        }
        const prevTimer = this._statusTimers.get(status);
        if (prevTimer) clearTimeout(prevTimer);
        if (!message) return;
        const timer = setTimeout(() => {
          status.textContent = '';
          this._statusTimers.delete(status);
        }, 2500);
        this._statusTimers.set(status, timer);
      } catch(_) {}
    }

    handleSelectAll(switcher) {
      const success = this.selectAllContent({ scrollIntoView: true });
      this.showClipboardNotice(switcher, success ? 'כל הקוד סומן' : 'לא היה מה לסמן');
    }

    registerSelectionFix() {
      try {
        this.teardownSelectionFix();
        if (!this.cmInstance || !this.cmInstance.contentDOM) return;
        const handler = (event) => {
          const key = (event.key || '').toLowerCase();
          if (key === 'a' && (event.metaKey || event.ctrlKey)) {
            event.preventDefault();
            this.selectAllContent({ scrollIntoView: true, silent: true });
          }
        };
        this.cmInstance.contentDOM.addEventListener('keydown', handler);
        this._selectionFixHandler = handler;
      } catch(_) {}
    }

    teardownSelectionFix() {
      try {
        if (this._selectionFixHandler && this.cmInstance && this.cmInstance.contentDOM) {
          this.cmInstance.contentDOM.removeEventListener('keydown', this._selectionFixHandler);
        }
      } catch(_) {}
      this._selectionFixHandler = null;
    }

    unfoldAllSections() {
      try {
        if (!this.cmInstance) return;
        const mods = (window.CodeMirror6 && window.CodeMirror6._mods) || {};
        if (mods.langMod && typeof mods.langMod.unfoldAll === 'function') {
          mods.langMod.unfoldAll(this.cmInstance);
          return;
        }
        if (mods.foldMod && typeof mods.foldMod.unfoldAll === 'function') {
          mods.foldMod.unfoldAll(this.cmInstance);
        }
      } catch(_) {}
    }

    selectAllContent({ scrollIntoView = false, silent = false } = {}) {
      try {
        if (this.cmInstance && this.cmInstance.state) {
          this.unfoldAllSections();
          this.cmInstance.focus();
          const docLength = this.cmInstance.state.doc.length;
          this.cmInstance.dispatch({
            selection: { anchor: 0, head: docLength },
            scrollIntoView
          });
          return docLength > 0 || !silent;
        }
        if (this.textarea) {
          this.textarea.focus();
          this.textarea.select();
          return this.textarea.value && this.textarea.value.length > 0;
        }
      } catch(_) {}
      return false;
    }

    async updateLanguage(lang) {
      if (!this.cmInstance || !window.CodeMirror6) return;
      try {
        const { languageCompartment } = window.CodeMirror6;
        const support = await this.getLanguageSupport(lang);
        this.cmInstance.dispatch({ effects: languageCompartment.reconfigure(support || []) });
      } catch(e) { console.warn('updateLanguage failed', e); }
    }

    async updateTheme(themeName) {
      if (!this.cmInstance || !window.CodeMirror6) return;
      try {
        const { themeCompartment } = window.CodeMirror6;
        const themeExt = await this.getTheme(themeName);
        this.cmInstance.dispatch({ effects: themeCompartment.reconfigure(themeExt || []) });
      } catch(e) { console.warn('updateTheme failed', e); }
    }

    async loadCodeMirror() {
      // נסה קודם טעינה מקומית (bundle) כדי לעבוד גם ללא CDN
      try {
        let localUrl;
        try {
           // שימוש בנתיב אבסולוטי מפורש כפי שנדרש
           const baseUrl = window.location.origin;
           // הוספת cache buster כדי לוודא שלא טוענים גרסה ישנה מהמטמון
           const cacheBuster = `?v=${new Date().getTime()}`;
           localUrl = `${baseUrl}/static/js/codemirror.local.js${cacheBuster}`;
        } catch(_) {
           // Fallback logic
           localUrl = '/static/js/codemirror.local.js?v=' + new Date().getTime();
        }

        try { console.log('[EditorManager] Attempting to load local CodeMirror bundle from:', localUrl); } catch(_) {}
        
        // טעינה באמצעות תגית script רגילה (יותר אמין מ-dynamic import בסביבות מסוימות)
        await new Promise((resolve, reject) => {
            const s = document.createElement('script');
            // הערה: הסרנו את type="module" כי ה-build עבר לפורמט IIFE
            // s.type = 'module'; 
            s.src = localUrl;
            s.onload = () => {
                try { console.log('[EditorManager] Script tag loaded successfully'); } catch(_) {}
                resolve();
            };
            s.onerror = (e) => {
                try { console.error('[EditorManager] Script tag failed to load', e); } catch(_) {}
                reject(new Error('Script tag load failed'));
            };
            document.head.appendChild(s);
        });

        // בדיקה האם ה-API זמין (ה-bundle אמור להגדיר את window.CodeMirror6)
        if (window.CodeMirror6 && window.CodeMirror6.EditorView && window.CodeMirror6.EditorState) {
          this._cdnUrl = null;
          try { console.log('[EditorManager] Local CodeMirror bundle loaded successfully (immediate check)'); } catch(_) {}
          return;
        } else {
             try { console.warn('[EditorManager] Local script loaded but CodeMirror6 missing. keys:', window.CodeMirror6 ? Object.keys(window.CodeMirror6) : 'undefined'); } catch(_) {}
        }

        // המתנה קצרה (עד ~2000ms) למקרה שה-bundle מגדיר את window.CodeMirror6 באיחור קצר
        // הוגדל מ-500ms ל-2000ms ליתר ביטחון
        {
          let attempts = 0;
          while (
            (!window.CodeMirror6 ||
             !window.CodeMirror6.EditorView ||
             !window.CodeMirror6.EditorState) &&
            attempts < 40
          ) {
            await new Promise((resolve) => setTimeout(resolve, 50));
            attempts++;
          }
        }

        if (window.CodeMirror6 && window.CodeMirror6.EditorView && window.CodeMirror6.EditorState) {
          this._cdnUrl = null;
          try { console.log('[EditorManager] Local CodeMirror bundle attached on window'); } catch(_) {}
          return;
        }

        console.warn('codemirror.local.js נטען אבל window.CodeMirror6 חסר או לא תקין');
      } catch (e) {
        console.error('אי אפשר לטעון את bundle המקומי של CodeMirror:', e);
        /* נמשיך ל-CDN אם אין bundle מקומי או כשהנתיב המקומי לא זמין */
      }

      // בוחרים CDN אחד לכלל המודולים כדי למנוע ערבוב מחלקות/סינגלטונים
      const cdnCandidates = [
        { name: 'jsdelivr', url: (pkg) => `https://cdn.jsdelivr.net/npm/${pkg}@6?module` },
        { name: 'unpkg',    url: (pkg) => `https://unpkg.com/${pkg}@6?module` },
        // fallback אחרון: שימוש ב-esm.sh תוך הצבעה לגרסת משנה יציבה יותר במידת האפשר
        { name: 'esm',      url: (pkg) => `https://esm.sh/${pkg}@6?bundle` }
      ];

      let chosen = null;
      let stateMod, viewMod, cmdMod, langMod, searchMod, acMod, gutterMod, cbMod, mbMod, foldMod;
      let lastErr;
      for (const cdn of cdnCandidates) {
        try {
          const u = cdn.url;
          // טוענים את כל מודולי הבסיס במקביל עם timeout הגיוני
          const [
            state,
            view,
            cmd,
            lang,
            search,
            ac,
            gutter,
            closebrackets,
            matchbrackets,
            fold
          ] = await Promise.all([
            this.withTimeout(import(u('@codemirror/state')), 12000, '@codemirror/state'),
            this.withTimeout(import(u('@codemirror/view')), 12000, '@codemirror/view'),
            this.withTimeout(import(u('@codemirror/commands')), 12000, '@codemirror/commands'),
            this.withTimeout(import(u('@codemirror/language')), 12000, '@codemirror/language'),
            this.withTimeout(import(u('@codemirror/search')), 12000, '@codemirror/search'),
            this.withTimeout(import(u('@codemirror/autocomplete')), 12000, '@codemirror/autocomplete'),
            this.withTimeout(import(u('@codemirror/gutter')), 12000, '@codemirror/gutter'),
            this.withTimeout(import(u('@codemirror/closebrackets')), 12000, '@codemirror/closebrackets'),
            this.withTimeout(import(u('@codemirror/matchbrackets')), 12000, '@codemirror/matchbrackets'),
            this.withTimeout(import(u('@codemirror/fold')), 12000, '@codemirror/fold')
          ]);
          stateMod = state; viewMod = view; cmdMod = cmd; langMod = lang; searchMod = search; acMod = ac; gutterMod = gutter; cbMod = closebrackets; mbMod = matchbrackets; foldMod = fold;
          chosen = cdn;
          break;
        } catch (e) {
          lastErr = e;
          // ננסה את ה-CDN הבא
        }
      }
      if (!chosen) throw lastErr || new Error('codemirror_core_import_failed');
      try { console.log('[EditorManager] CDN selected:', chosen.name); } catch(_) {}

      // שמירת ה-CDN הנבחר לשימוש בהמשך (שפות/נושא)
      this._cdnUrl = chosen.url;

      const basicSetup = [
        (gutterMod && typeof gutterMod.lineNumbers === 'function') ? gutterMod.lineNumbers() : [],
        (viewMod && typeof viewMod.highlightActiveLineGutter === 'function') ? viewMod.highlightActiveLineGutter() : [],
        (viewMod && typeof viewMod.highlightSpecialChars === 'function') ? viewMod.highlightSpecialChars() : [],
        (cmdMod && typeof cmdMod.history === 'function') ? cmdMod.history() : [],
        (foldMod && typeof foldMod.foldGutter === 'function') ? foldMod.foldGutter() : (langMod && typeof langMod.foldGutter === 'function') ? langMod.foldGutter() : [],
        (viewMod && typeof viewMod.drawSelection === 'function') ? viewMod.drawSelection() : [],
        (viewMod && typeof viewMod.dropCursor === 'function') ? viewMod.dropCursor() : [],
        stateMod.EditorState.allowMultipleSelections.of(true),
        (mbMod && typeof mbMod.bracketMatching === 'function') ? mbMod.bracketMatching() : (langMod && typeof langMod.bracketMatching === 'function') ? langMod.bracketMatching() : [],
        (cbMod && typeof cbMod.closeBrackets === 'function') ? cbMod.closeBrackets() : [],
        (acMod && typeof acMod.autocompletion === 'function') ? acMod.autocompletion() : [],
        (viewMod && typeof viewMod.rectangularSelection === 'function') ? viewMod.rectangularSelection() : [],
        (viewMod && typeof viewMod.crosshairCursor === 'function') ? viewMod.crosshairCursor() : [],
        (viewMod && typeof viewMod.highlightActiveLine === 'function') ? viewMod.highlightActiveLine() : [],
        (searchMod && typeof searchMod.highlightSelectionMatches === 'function') ? searchMod.highlightSelectionMatches() : [],
        (viewMod && typeof viewMod.keymap === 'object' && typeof viewMod.keymap.of === 'function') ? viewMod.keymap.of([
          ...(cbMod && Array.isArray(cbMod.closeBracketsKeymap) ? cbMod.closeBracketsKeymap : (acMod && Array.isArray(acMod.closeBracketsKeymap) ? acMod.closeBracketsKeymap : [])),
          ...(Array.isArray(cmdMod?.defaultKeymap) ? cmdMod.defaultKeymap : []),
          ...(Array.isArray(searchMod?.searchKeymap) ? searchMod.searchKeymap : []),
          ...(Array.isArray(cmdMod?.historyKeymap) ? cmdMod.historyKeymap : []),
          ...(Array.isArray(foldMod?.foldKeymap) ? foldMod.foldKeymap : (Array.isArray(langMod?.foldKeymap) ? langMod.foldKeymap : [])),
          ...(Array.isArray(acMod?.completionKeymap) ? acMod.completionKeymap : [])
        ]) : []
      ];

      try { console.log('[EditorManager] CodeMirror core modules loaded'); } catch(_) {}
      window.CodeMirror6 = {
        EditorState: stateMod.EditorState,
        EditorView: viewMod.EditorView,
        basicSetup,
        keymap: viewMod.keymap,
        Compartment: stateMod.Compartment,
        languageCompartment: new stateMod.Compartment(),
        themeCompartment: new stateMod.Compartment(),
        _cdnUrl: this._cdnUrl,
        // Expose modules for diagnostics
        _mods: { stateMod, viewMod, cmdMod, langMod, searchMod, acMod, gutterMod, cbMod, mbMod, foldMod }
      };
    }

    async getLanguageSupport(lang) {
      // אם bundle מקומי זמין – נשתמש בו
      try {
        if (window.CodeMirror6 && typeof window.CodeMirror6.getLanguageSupport === 'function') {
          return window.CodeMirror6.getLanguageSupport(lang);
        }
      } catch(_) {}
      const gen = this._cdnUrl || ((pkg) => `https://cdn.jsdelivr.net/npm/${pkg}@6?module`);
      const key = String(lang || '').toLowerCase();
      try {
        switch (key) {
          case 'text':
          case 'plain':
            return [];
          case 'python': {
            const m = await import(gen('@codemirror/lang-python')); return m.python();
          }
          case 'javascript': {
            const m = await import(gen('@codemirror/lang-javascript')); return m.javascript();
          }
          case 'typescript': {
            const m = await import(gen('@codemirror/lang-javascript')); return m.javascript({ typescript: true });
          }
          case 'html': {
            const m = await import(gen('@codemirror/lang-html')); return m.html();
          }
          case 'css': {
            const m = await import(gen('@codemirror/lang-css')); return m.css();
          }
          case 'sql': {
            const m = await import(gen('@codemirror/lang-sql')); return m.sql();
          }
          case 'json': {
            const m = await import(gen('@codemirror/lang-json')); return m.json();
          }
          case 'markdown': {
            const m = await import(gen('@codemirror/lang-markdown')); return m.markdown();
          }
          case 'xml': {
            const m = await import(gen('@codemirror/lang-xml')); return m.xml();
          }
          case 'bash':
          case 'shell': {
            const m = await import(gen('@codemirror/lang-shell')); return m.shell();
          }
          case 'go': {
            const m = await import(gen('@codemirror/lang-go')); return m.go();
          }
          case 'java': {
            const m = await import(gen('@codemirror/lang-java')); return m.java();
          }
          case 'yaml': {
            const m = await import(gen('@codemirror/lang-yaml')); return m.yaml();
          }
          case 'csharp': {
            try {
              const langMod = await import(gen('@codemirror/language'));
              const legacy = await import(gen('@codemirror/legacy-modes/mode/clike'));
              if (langMod && legacy && legacy.csharp && langMod.StreamLanguage && typeof langMod.StreamLanguage.define === 'function') {
                return langMod.StreamLanguage.define(legacy.csharp);
              }
            } catch (err) {
              console.warn('C# language load failed, continuing without language support', err);
            }
            return [];
          }
          default:
            return [];
        }
      } catch(err) {
        console.warn('Language load failed, continuing without language support', err);
        return [];
      }
    }

    async getTheme(name) {
      try {
        if (window.CodeMirror6 && typeof window.CodeMirror6.getTheme === 'function') {
          return window.CodeMirror6.getTheme(name);
        }
      } catch(_) {}
      if (name === 'dark') {
        const gen = this._cdnUrl || ((pkg) => `https://cdn.jsdelivr.net/npm/${pkg}@6?module`);
        try { const mod = await import(gen('@codemirror/theme-one-dark')); return mod.oneDark || []; } catch(err) { console.warn('Theme load failed, using default theme', err); return []; }
      }
      return [];
    }

    debounce(fn, wait) {
      let t;
      return (...args) => {
        clearTimeout(t);
        t = setTimeout(() => fn(...args), wait);
      };
    }

    // מגן כללי ל-async שמונע תקיעות שקטות ומדווח הקשר לשגיאה
    withTimeout(promise, ms, label) {
      return new Promise((resolve, reject) => {
        let settled = false;
        const id = setTimeout(() => {
          if (settled) return;
          settled = true;
          const err = new Error(`timeout_${label || 'operation'}`);
          err.code = 'ETIMEOUT';
          reject(err);
        }, ms);
        Promise.resolve(promise).then(
          (val) => { if (!settled) { settled = true; clearTimeout(id); resolve(val); } },
          (err) => { if (!settled) { settled = true; clearTimeout(id); reject(err); } }
        );
      });
    }

    showLoading(container){
      if (container.querySelector('.editor-loading')) return;
      const el = document.createElement('div');
      el.className = 'editor-loading';
      el.innerHTML = '<div class="spinner"><i class="fas fa-spinner fa-spin"></i> טוען עורך...</div>';
      container.classList.add('editor-transitioning');
      container.appendChild(el);
      try {
        const btn = container.querySelector('.btn-switch-editor');
        if (btn) { btn.disabled = true; btn.classList.add('is-loading'); }
      } catch(_) {}
    }
    hideLoading(container){
      const el = container.querySelector('.editor-loading');
      if (el) el.remove();
      container.classList.remove('editor-transitioning');
      try {
        const btn = container.querySelector('.btn-switch-editor');
        if (btn) { btn.disabled = false; btn.classList.remove('is-loading'); }
      } catch(_) {}
    }
  }

  window.editorManager = new EditorManager();
  try { console.log('[EditorManager] Assigned window.editorManager instance'); } catch(_) {}
})();
