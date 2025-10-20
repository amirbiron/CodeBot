(function(){
  class EditorManager {
    constructor() {
      this.currentEditor = this.loadPreference();
      this.cmInstance = null;
      this.textarea = null;
      this.loadingElement = null;
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
      try {
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
      } finally {
        this.hideLoading(container);
      }
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
          await this.initCodeMirror(container, { language: lang, value: this.textarea.value, theme: 'dark' });
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
      // טעינה דינמית של מודולים מצדי ה-CDN והגדרת חלון גלובלי יחיד
      const stateMod = await import('https://cdn.jsdelivr.net/npm/@codemirror/state@6/dist/index.js');
      const viewMod = await import('https://cdn.jsdelivr.net/npm/@codemirror/view@6/dist/index.js');
      const cmdMod = await import('https://cdn.jsdelivr.net/npm/@codemirror/commands@6/dist/index.js');
      const langMod = await import('https://cdn.jsdelivr.net/npm/@codemirror/language@6/dist/index.js');
      const searchMod = await import('https://cdn.jsdelivr.net/npm/@codemirror/search@6/dist/index.js');
      const acMod = await import('https://cdn.jsdelivr.net/npm/@codemirror/autocomplete@6/dist/index.js');

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
      const map = {
        python: ['https://cdn.jsdelivr.net/npm/@codemirror/lang-python@6/dist/index.js'],
        javascript: ['https://cdn.jsdelivr.net/npm/@codemirror/lang-javascript@6/dist/index.js'],
        html: ['https://cdn.jsdelivr.net/npm/@codemirror/lang-html@6/dist/index.js'],
        css: ['https://cdn.jsdelivr.net/npm/@codemirror/lang-css@6/dist/index.js'],
        sql: ['https://cdn.jsdelivr.net/npm/@codemirror/lang-sql@6/dist/index.js'],
        json: ['https://cdn.jsdelivr.net/npm/@codemirror/lang-json@6/dist/index.js'],
        markdown: ['https://cdn.jsdelivr.net/npm/@codemirror/lang-markdown@6/dist/index.js'],
        xml: ['https://cdn.jsdelivr.net/npm/@codemirror/lang-xml@6/dist/index.js']
      };
      const urls = map[lang];
      if (!urls) return [];
      try {
        const mod = await import(urls[0]);
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
        try {
          const mod = await import('https://cdn.jsdelivr.net/npm/@codemirror/theme-one-dark@6/dist/index.js');
          return mod.oneDark;
        } catch(_) { return []; }
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
    }
    hideLoading(container){
      const el = container.querySelector('.editor-loading');
      if (el) el.remove();
      container.classList.remove('editor-transitioning');
    }
  }

  window.editorManager = new EditorManager();
})();
