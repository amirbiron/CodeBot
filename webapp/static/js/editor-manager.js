(function(){
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
      this.textarea = container.querySelector('textarea[name="code"]');
      if (!this.textarea) return;

      let fallback = false;
      if (this.currentEditor === 'codemirror') {
        try {
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
          const info = container.querySelector('.editor-switcher .editor-info');
          if (info) info.innerHTML = '<span><i class="fas fa-info-circle"></i> עורך טקסט בסיסי</span>';
        } catch(_) {}
      }
    }

    initSimpleEditor(container, { value }) {
      try {
        if (this.cmInstance) {
          // העתקת התוכן חזרה ל-textarea והרס העורך
          try { this.textarea.value = this.cmInstance.state.doc.toString(); } catch(_) {}
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
          // הסתרת textarea
          this.textarea.style.display = 'none';

          // יצירת container
          const cmWrapper = document.createElement('div');
          cmWrapper.className = 'codemirror-container';
          this.textarea.parentNode.insertBefore(cmWrapper, this.textarea.nextSibling);

          if (!window.CodeMirror6) {
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
          const themeExt = await this.withTimeout(this.getTheme(theme), 12000, 'codemirror_theme_load');

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
              EditorView.lineWrapping,
              EditorView.updateListener.of((update) => {
                if (update.docChanged) {
                  debouncedSync(update.state.doc.toString());
                }
              })
            ]
          });

          this.cmInstance = new EditorView({ state, parent: cmWrapper });
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
            errBanner.textContent = 'טעינת העורך המתקדם נכשלה. הוחזר לעורך הפשוט.';
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
        <button type="button" class="btn-switch-editor" title="החלף עורך">
          <i class="fas fa-exchange-alt"></i>
          <span>${this.currentEditor === 'simple' ? 'עורך מתקדם' : 'עורך פשוט'}</span>
        </button>
        <div class="editor-info">
          ${this.currentEditor === 'codemirror' ? '<span><i class="fas fa-keyboard"></i> קיצורי מקלדת זמינים</span>' : '<span><i class="fas fa-info-circle"></i> עורך טקסט בסיסי</span>'}
        </div>
      `;
      const codeLabel = container.querySelector('label') || container;
      codeLabel.parentNode.insertBefore(switcher, codeLabel.nextSibling);

      switcher.querySelector('.btn-switch-editor').addEventListener('click', async () => {
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
        this.savePreference(this.currentEditor);
        try { switcher.querySelector('span').textContent = this.currentEditor === 'simple' ? 'עורך מתקדם' : 'עורך פשוט'; } catch(_) {}
      });
    }

    getSelectedLanguage() {
      try {
        const sel = document.getElementById('languageSelect');
        const val = sel && sel.value;
        if (typeof val === 'string' && val.trim()) return val;
      } catch(_) {}
      return null;
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
        await this.withTimeout(import('/static/js/codemirror.local.js'), 8000, 'codemirror_local_import');
        if (window.CodeMirror6 && window.CodeMirror6.EditorView && window.CodeMirror6.EditorState) {
          this._cdnUrl = null;
          return;
        }
      } catch (_) { /* נמשיך ל-CDN אם אין bundle מקומי */ }

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
      const pkgMap = {
        python: '@codemirror/lang-python',
        javascript: '@codemirror/lang-javascript',
        html: '@codemirror/lang-html',
        css: '@codemirror/lang-css',
        sql: '@codemirror/lang-sql',
        json: '@codemirror/lang-json',
        markdown: '@codemirror/lang-markdown',
        xml: '@codemirror/lang-xml'
      };
      const pkg = pkgMap[lang];
      if (!pkg) return [];
      try {
        const mod = await import(gen(pkg));
        switch (lang) {
          case 'python': return mod.python();
          case 'javascript': return mod.javascript();
          case 'html': return mod.html();
          case 'css': return mod.css();
          case 'sql': return mod.sql();
          case 'json': return mod.json();
          case 'markdown': return mod.markdown();
          case 'xml': return mod.xml();
          default: return [];
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
})();
