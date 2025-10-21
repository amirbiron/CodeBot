(function(){
  class EditorManager {
    constructor() {
      this.currentEditor = this.loadPreference();
      this.cmInstance = null;
      this.textarea = null;
      this.loadingElement = null;
      this.isLoading = false;
      this.loadingPromise = null;
    }

    loadPreference() {
      try {
        const saved = localStorage.getItem('preferredEditor');
        if (saved === 'codemirror' || saved === 'simple') return saved;
      } catch(_) {}
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
            await this.loadCodeMirror();
          }
          const { EditorState, EditorView, basicSetup, Compartment, languageCompartment, themeCompartment } = window.CodeMirror6;

          const langSupport = await this.getLanguageSupport(language);
          const themeExt = await this.getTheme(theme);

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
      // טעינה דינמית עם נפילות (fallback) כדי למנוע שגיאות bare specifiers בדפדפנים
      const tryImports = async (urls) => {
        let lastErr;
        for (const u of urls) {
          try { return await import(u); } catch (e) { lastErr = e; }
        }
        throw lastErr || new Error('module_import_failed');
      };

      // מועמדים לכל חבילה: jsDelivr (?module), unpkg (?module), esm.sh (?bundle)
      const urls = {
        state: [
          'https://cdn.jsdelivr.net/npm/@codemirror/state@6?module',
          'https://unpkg.com/@codemirror/state@6?module',
          'https://esm.sh/@codemirror/state@6?bundle'
        ],
        view: [
          'https://cdn.jsdelivr.net/npm/@codemirror/view@6?module',
          'https://unpkg.com/@codemirror/view@6?module',
          'https://esm.sh/@codemirror/view@6?bundle'
        ],
        commands: [
          'https://cdn.jsdelivr.net/npm/@codemirror/commands@6?module',
          'https://unpkg.com/@codemirror/commands@6?module',
          'https://esm.sh/@codemirror/commands@6?bundle'
        ],
        language: [
          'https://cdn.jsdelivr.net/npm/@codemirror/language@6?module',
          'https://unpkg.com/@codemirror/language@6?module',
          'https://esm.sh/@codemirror/language@6?bundle'
        ],
        search: [
          'https://cdn.jsdelivr.net/npm/@codemirror/search@6?module',
          'https://unpkg.com/@codemirror/search@6?module',
          'https://esm.sh/@codemirror/search@6?bundle'
        ],
        autocomplete: [
          'https://cdn.jsdelivr.net/npm/@codemirror/autocomplete@6?module',
          'https://unpkg.com/@codemirror/autocomplete@6?module',
          'https://esm.sh/@codemirror/autocomplete@6?bundle'
        ]
      };

      const stateMod = await tryImports(urls.state);
      const viewMod = await tryImports(urls.view);
      const cmdMod = await tryImports(urls.commands);
      const langMod = await tryImports(urls.language);
      const searchMod = await tryImports(urls.search);
      const acMod = await tryImports(urls.autocomplete);

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
        themeCompartment: new stateMod.Compartment()
      };
    }

    async getLanguageSupport(lang) {
      const tryImports = async (urls) => {
        let lastErr;
        for (const u of urls) {
          try { return await import(u); } catch (e) { lastErr = e; }
        }
        throw lastErr || new Error('lang_import_failed');
      };
      const maps = {
        python: [
          'https://cdn.jsdelivr.net/npm/@codemirror/lang-python@6?module',
          'https://unpkg.com/@codemirror/lang-python@6?module',
          'https://esm.sh/@codemirror/lang-python@6?bundle'
        ],
        javascript: [
          'https://cdn.jsdelivr.net/npm/@codemirror/lang-javascript@6?module',
          'https://unpkg.com/@codemirror/lang-javascript@6?module',
          'https://esm.sh/@codemirror/lang-javascript@6?bundle'
        ],
        html: [
          'https://cdn.jsdelivr.net/npm/@codemirror/lang-html@6?module',
          'https://unpkg.com/@codemirror/lang-html@6?module',
          'https://esm.sh/@codemirror/lang-html@6?bundle'
        ],
        css: [
          'https://cdn.jsdelivr.net/npm/@codemirror/lang-css@6?module',
          'https://unpkg.com/@codemirror/lang-css@6?module',
          'https://esm.sh/@codemirror/lang-css@6?bundle'
        ],
        sql: [
          'https://cdn.jsdelivr.net/npm/@codemirror/lang-sql@6?module',
          'https://unpkg.com/@codemirror/lang-sql@6?module',
          'https://esm.sh/@codemirror/lang-sql@6?bundle'
        ],
        json: [
          'https://cdn.jsdelivr.net/npm/@codemirror/lang-json@6?module',
          'https://unpkg.com/@codemirror/lang-json@6?module',
          'https://esm.sh/@codemirror/lang-json@6?bundle'
        ],
        markdown: [
          'https://cdn.jsdelivr.net/npm/@codemirror/lang-markdown@6?module',
          'https://unpkg.com/@codemirror/lang-markdown@6?module',
          'https://esm.sh/@codemirror/lang-markdown@6?bundle'
        ],
        xml: [
          'https://cdn.jsdelivr.net/npm/@codemirror/lang-xml@6?module',
          'https://unpkg.com/@codemirror/lang-xml@6?module',
          'https://esm.sh/@codemirror/lang-xml@6?bundle'
        ]
      };
      const urls = maps[lang];
      if (!urls) return [];
      try {
        const mod = await tryImports(urls);
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
        const urls = [
          'https://cdn.jsdelivr.net/npm/@codemirror/theme-one-dark@6?module',
          'https://unpkg.com/@codemirror/theme-one-dark@6?module',
          'https://esm.sh/@codemirror/theme-one-dark@6?bundle'
        ];
        for (const u of urls) {
          try { const mod = await import(u); return mod.oneDark || []; } catch(_) {}
        }
        return [];
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
