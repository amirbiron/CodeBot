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
        const saved = localStorage.getItem('preferredEditor');
        if (saved === 'codemirror' || saved === 'simple') return saved;
      } catch(_) {}
      // ברירת מחדל: עורך רגיל (textarea)
      return 'simple';
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

      if (this.currentEditor === 'codemirror') {
        await this.initCodeMirror(container, { language, value, theme });
      } else {
        this.initSimpleEditor(container, { value });
      }
      this.addSwitcherButton(container);
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
            await this.withTimeout(this.loadCodeMirror(), 12000, 'codemirror_core_load');
          }
          const { EditorState, EditorView, basicSetup, Compartment, languageCompartment, themeCompartment } = window.CodeMirror6;

          const langSupport = await this.withTimeout(this.getLanguageSupport(language), 6000, 'codemirror_lang_load');
          const themeExt = await this.withTimeout(this.getTheme(theme), 6000, 'codemirror_theme_load');

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
      // בוחרים CDN אחד לכלל המודולים כדי למנוע ערבוב מחלקות/סינגלטונים
      const cdnCandidates = [
        { name: 'jsdelivr', url: (pkg) => `https://cdn.jsdelivr.net/npm/${pkg}@6?module` },
        { name: 'unpkg',    url: (pkg) => `https://unpkg.com/${pkg}@6?module` },
        { name: 'esm',      url: (pkg) => `https://esm.sh/${pkg}@6?bundle` }
      ];

      let chosen = null;
      let stateMod, viewMod, cmdMod, langMod, searchMod, acMod;
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
            ac
          ] = await Promise.all([
            this.withTimeout(import(u('@codemirror/state')), 8000, '@codemirror/state'),
            this.withTimeout(import(u('@codemirror/view')), 8000, '@codemirror/view'),
            this.withTimeout(import(u('@codemirror/commands')), 8000, '@codemirror/commands'),
            this.withTimeout(import(u('@codemirror/language')), 8000, '@codemirror/language'),
            this.withTimeout(import(u('@codemirror/search')), 8000, '@codemirror/search'),
            this.withTimeout(import(u('@codemirror/autocomplete')), 8000, '@codemirror/autocomplete')
          ]);
          stateMod = state; viewMod = view; cmdMod = cmd; langMod = lang; searchMod = search; acMod = ac;
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
        viewMod.lineNumbers(),
        viewMod.highlightActiveLineGutter(),
        viewMod.highlightSpecialChars(),
        cmdMod.history(),
        langMod.foldGutter(),
        viewMod.drawSelection(),
        viewMod.dropCursor(),
        stateMod.EditorState.allowMultipleSelections.of(true),
        langMod.bracketMatching(),
        acMod.closeBrackets(),
        acMod.autocompletion(),
        viewMod.rectangularSelection(),
        viewMod.crosshairCursor(),
        viewMod.highlightActiveLine(),
        searchMod.highlightSelectionMatches(),
        viewMod.keymap.of([
          ...acMod.closeBracketsKeymap,
          ...cmdMod.defaultKeymap,
          ...searchMod.searchKeymap,
          ...cmdMod.historyKeymap,
          ...langMod.foldKeymap,
          ...acMod.completionKeymap
        ])
      ];

      window.CodeMirror6 = {
        EditorState: stateMod.EditorState,
        EditorView: viewMod.EditorView,
        basicSetup,
        keymap: viewMod.keymap,
        Compartment: stateMod.Compartment,
        languageCompartment: new stateMod.Compartment(),
        themeCompartment: new stateMod.Compartment(),
        _cdnUrl: this._cdnUrl
      };
    }

    async getLanguageSupport(lang) {
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
      } catch(_) { return []; }
    }

    async getTheme(name) {
      if (name === 'dark') {
        const gen = this._cdnUrl || ((pkg) => `https://cdn.jsdelivr.net/npm/${pkg}@6?module`);
        try { const mod = await import(gen('@codemirror/theme-one-dark')); return mod.oneDark || []; } catch(_) { return []; }
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
