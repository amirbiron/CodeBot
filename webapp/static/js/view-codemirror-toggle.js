// View Mode: toggle between basic (Pygments) and advanced (CodeMirror) rendering.
// Requirements:
// - Read-only CodeMirror with folding support (same bundle/theme as edit page)
// - Toggle button (⚡ מתקדם / 📄 בסיסי)
// - Persist preference in localStorage

(function () {
  const STORAGE_KEY = 'ck_view_mode';
  const MODE_BASIC = 'basic';
  const MODE_ADVANCED = 'advanced';

  function getSavedMode() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      return raw === MODE_ADVANCED ? MODE_ADVANCED : MODE_BASIC;
    } catch (_) {
      return MODE_BASIC;
    }
  }

  function saveMode(mode) {
    try {
      localStorage.setItem(STORAGE_KEY, mode);
    } catch (_) {}
  }

  function ready(fn) {
    // חשוב: base.html טוען editor-manager.js כ-<script type="module" defer>.
    // לפי הספציפיקציה, classic deferred scripts רצים לפני module deferred scripts.
    // אם נרוץ ב-readyState=interactive, ייתכן ש-window.editorManager עדיין לא קיים,
    // ואז מצב "מתקדם" שנשמר ב-localStorage ייכשל שקט ויתעלם בהטענה הראשונה.
    //
    // לכן: נרוץ רק אחרי DOMContentLoaded (או מיידית אם כבר complete).
    if (document.readyState === 'complete') {
      fn();
      return;
    }
    document.addEventListener('DOMContentLoaded', fn, { once: true });
  }

  function resolveLanguage(metaEl) {
    try {
      const raw = metaEl ? (metaEl.getAttribute('data-language') || '') : '';
      const lang = normalizeLanguage(raw);
      if (lang && lang !== 'text' && lang !== 'plain') return lang;
    } catch (_) {}

    // Fallback: infer from filename (EditorManager already has this map)
    try {
      const fileName = metaEl ? (metaEl.getAttribute('data-file-name') || '') : '';
      if (window.editorManager && typeof window.editorManager.inferLanguageFromFilename === 'function') {
        return window.editorManager.inferLanguageFromFilename(fileName) || 'text';
      }
    } catch (_) {}

    return 'text';
  }

  function normalizeLanguage(raw) {
    const s = String(raw || '').trim().toLowerCase();
    if (!s) return '';
    // Strip details like "Python (3.11)" / "Python 3"
    const noParens = s.replace(/\(.*?\)/g, '').trim();
    const compact = noParens.replace(/[_]+/g, ' ').trim();
    if (!compact) return '';

    // Common aliases
    if (compact === 'js' || compact.startsWith('javascript')) return 'javascript';
    if (compact === 'ts' || compact.startsWith('typescript')) return 'typescript';
    if (compact === 'md' || compact.startsWith('markdown')) return 'markdown';
    if (compact === 'py' || compact.startsWith('python')) return 'python';
    if (compact === 'yml' || compact.startsWith('yaml')) return 'yaml';
    if (compact === 'sh' || compact === 'bash' || compact.startsWith('shell')) return 'shell';
    if (compact === 'golang' || compact === 'go') return 'go';
    if (compact === 'c#' || compact === 'csharp' || compact === 'c sharp') return 'csharp';
    if (compact === 'plain text' || compact === 'plaintext' || compact === 'plain' || compact === 'text') return 'text';

    // First token fallback (keeps things like "html", "css", "json")
    return compact.split(/\s+/)[0] || '';
  }

  function resolveEffectiveThemeForEditorParity() {
    // Important: editor pages always pass theme: 'dark' into EditorManager,
    // and only override it to 'dark' again when UI theme is dark/dim/nebula.
    // To keep view-mode 1:1 with the editor, we stick to 'dark' here as well.
    //
    // 🎨 Exception: custom themes use CSS classes (tok-*) from syntax_css,
    // so we return 'custom' to avoid loading oneDark which would override the CSS.
    try {
      const htmlTheme = document && document.documentElement ? (document.documentElement.getAttribute('data-theme') || '') : '';
      const t = String(htmlTheme || '').toLowerCase();
      // Custom theme: don't load oneDark, let syntax_css CSS classes work
      if (t === 'custom') return 'custom';
      // Same logic as editor-manager.js (dark/dim/nebula => oneDark)
      if (t === 'dark' || t === 'dim' || t === 'nebula') return 'dark';
    } catch (_) {}
    return 'dark';
  }

  async function ensureCodeMirrorLoaded() {
    if (window.CodeMirror6 && window.CodeMirror6.EditorView && window.CodeMirror6.EditorState) {
      return true;
    }
    if (!window.editorManager || typeof window.editorManager.loadCodeMirror !== 'function') {
      return false;
    }
    try {
      await window.editorManager.loadCodeMirror();
    } catch (_) {
      return false;
    }
    return !!(window.CodeMirror6 && window.CodeMirror6.EditorView && window.CodeMirror6.EditorState);
  }

  async function createReadOnlyCodeMirror({ mountEl, docText, language }) {
    const ok = await ensureCodeMirrorLoaded();
    if (!ok) {
      throw new Error('codemirror_not_available');
    }

    const { EditorState, EditorView, languageCompartment, themeCompartment } = window.CodeMirror6;
    const mods = (window.CodeMirror6 && window.CodeMirror6._mods) || {};
    const viewMod = mods.viewMod;

    const themeName = resolveEffectiveThemeForEditorParity();
    let langSupport = [];
    let themeExt = [];
    try {
      if (window.editorManager && typeof window.editorManager.getLanguageSupport === 'function') {
        langSupport = (await window.editorManager.getLanguageSupport(language)) || [];
      }
    } catch (_) {
      langSupport = [];
    }
    try {
      if (window.editorManager && typeof window.editorManager.getTheme === 'function') {
        themeExt = (await window.editorManager.getTheme(themeName)) || [];
      }
    } catch (_) {
      themeExt = [];
    }

    // 🎨 Custom themes: טוען dynamic syntax highlighter עם צבעים מ-syntax_colors
    // getSyntaxHighlighter() מחזירה syntaxHighlighting(dynamicStyle) אם theme="custom",
    // או syntaxHighlighting(classHighlighter) כ-fallback
    let customSyntaxHighlighter = null;
    if (themeName === 'custom' && window.CodeMirror6.getSyntaxHighlighter) {
      try {
        customSyntaxHighlighter = window.CodeMirror6.getSyntaxHighlighter();
      } catch (_) {}
    }

    const extensions = [
      ...(window.CodeMirror6.basicSetup || []),
      languageCompartment ? languageCompartment.of(langSupport || []) : (langSupport || []),
      themeCompartment ? themeCompartment.of(themeExt || []) : (themeExt || []),
      // 🎨 אם יש custom theme עם syntax highlighter, מוסיפים אותו כדי לדרוס את ה-classHighlighter שב-basicSetup
      ...(customSyntaxHighlighter ? [customSyntaxHighlighter] : []),
      // Keep wrapping consistent with editor
      EditorView.lineWrapping,
      // Read-only but still interactive (selection/folding)
      EditorState.readOnly.of(true),
      (viewMod && viewMod.EditorView && viewMod.EditorView.editable) ? viewMod.EditorView.editable.of(false) : EditorView.editable.of(false),
    ];

    const state = EditorState.create({
      doc: docText || '',
      extensions,
    });

    return new EditorView({ state, parent: mountEl });
  }

  function setToggleLabel(btn, mode) {
    if (!btn) return;
    // Requirement:
    // - basic (static) => show "⚡ מתקדם"
    // - advanced (cm)  => show "📄 בסיסי"
    btn.textContent = mode === MODE_ADVANCED ? '📄 בסיסי' : '⚡ מתקדם';
    btn.setAttribute('aria-pressed', mode === MODE_ADVANCED ? 'true' : 'false');
  }

  ready(function init() {
    const btn = document.getElementById('viewModeToggleBtn');
    const codeCard = document.getElementById('codeCard');
    const basicEl = document.getElementById('codeBasicContainer');
    const advancedEl = document.getElementById('codeMirrorContainer');
    const rawEl = document.getElementById('rawCode');
    const metaEl = document.getElementById('fileMeta');
    const searchInput = document.getElementById('codeSearchInput');
    const searchCount = document.getElementById('searchCount');
    const nextBtn = document.getElementById('nextMatchBtn');
    const prevBtn = document.getElementById('prevMatchBtn');
    const clearBtn = document.getElementById('closeSearchBtn');

    if (!btn || !codeCard || !basicEl || !advancedEl) {
      return;
    }

    const hasRaw = !!(rawEl && typeof rawEl.value === 'string');
    if (!hasRaw) {
      try {
        btn.disabled = true;
        btn.title = 'תצוגה מתקדמת לא זמינה לקובץ הזה';
        btn.setAttribute('aria-disabled', 'true');
      } catch (_) {}
      return;
    }

    let viewInstance = null;
    let currentMode = MODE_BASIC;

    function isAdvancedActive() {
      return !!advancedEl && !advancedEl.hidden;
    }

    // --- CodeMirror search adapter (keeps existing UI working in advanced mode) ---
    let cmTerm = '';
    let cmMatches = [];
    let cmActiveIndex = -1;

    function setSearchCountText(text) {
      if (!searchCount) return;
      searchCount.textContent = text || '';
    }

    function updateCmCount() {
      if (!cmTerm) {
        setSearchCountText('');
        return;
      }
      if (!cmMatches.length) {
        setSearchCountText('אין תוצאות');
        return;
      }
      const idx = cmActiveIndex >= 0 ? (cmActiveIndex + 1) : 0;
      setSearchCountText(idx ? `${idx}/${cmMatches.length}` : `${cmMatches.length} תוצאות`);
    }

    function cmFocusIndex(index) {
      if (!viewInstance || !cmMatches.length) return;
      const i = ((index % cmMatches.length) + cmMatches.length) % cmMatches.length;
      cmActiveIndex = i;
      const m = cmMatches[i];
      if (!m) return;
      try {
        viewInstance.focus();
      } catch (_) {}
      try {
        viewInstance.dispatch({
          selection: { anchor: m.from, head: m.to },
          scrollIntoView: true,
        });
      } catch (_) {}
      updateCmCount();
    }

    function cmClearSelection() {
      if (!viewInstance) return;
      try {
        const head = viewInstance.state.selection && viewInstance.state.selection.main ? viewInstance.state.selection.main.head : 0;
        viewInstance.dispatch({ selection: { anchor: head, head }, scrollIntoView: false });
      } catch (_) {}
    }

    async function cmRecompute(term) {
      cmTerm = String(term || '').trim();
      cmMatches = [];
      cmActiveIndex = -1;

      if (!cmTerm) {
        updateCmCount();
        cmClearSelection();
        return;
      }

      if (!viewInstance) {
        try {
          await ensureView();
        } catch (_) {
          updateCmCount();
          return;
        }
      }

      const needle = cmTerm.toLowerCase();
      const doc = (viewInstance && viewInstance.state && viewInstance.state.doc) ? viewInstance.state.doc.toString() : '';
      const hay = String(doc || '').toLowerCase();
      if (!needle) {
        updateCmCount();
        return;
      }

      let idx = 0;
      const maxMatches = 5000; // guard to avoid locking UI on very repetitive files
      while (idx >= 0 && idx < hay.length && cmMatches.length < maxMatches) {
        const found = hay.indexOf(needle, idx);
        if (found === -1) break;
        cmMatches.push({ from: found, to: found + needle.length });
        idx = found + needle.length;
        if (needle.length === 0) idx = found + 1;
      }

      if (cmMatches.length) {
        cmFocusIndex(0);
      } else {
        updateCmCount();
        cmClearSelection();
      }
    }

    async function ensureView() {
      if (viewInstance) return viewInstance;
      const language = resolveLanguage(metaEl);
      const docText = rawEl.value || '';
      advancedEl.innerHTML = '';
      viewInstance = await createReadOnlyCodeMirror({ mountEl: advancedEl, docText, language });
      // Expose for search integration (if needed)
      window.__ck_view_cm_view = viewInstance;
      return viewInstance;
    }

    async function applyMode(nextMode, { persist = true } = {}) {
      const mode = nextMode === MODE_ADVANCED ? MODE_ADVANCED : MODE_BASIC;
      currentMode = mode;

      if (mode === MODE_ADVANCED) {
        try {
          await ensureView();
        } catch (e) {
          // Fallback to basic if CM init fails
          currentMode = MODE_BASIC;
        }
      }

      const isAdvanced = currentMode === MODE_ADVANCED;
      basicEl.hidden = isAdvanced;
      advancedEl.hidden = !isAdvanced;

      try {
        codeCard.classList.toggle('is-advanced', isAdvanced);
      } catch (_) {}

      setToggleLabel(btn, currentMode);
      if (persist) saveMode(currentMode);

      // When showing CM, request a measure to fix layout after display:none -> block
      if (isAdvanced) {
        try {
          if (viewInstance && typeof viewInstance.requestMeasure === 'function') {
            viewInstance.requestMeasure();
          }
        } catch (_) {}
        try {
          // Keep search UI consistent if user already typed something
          if (searchInput) {
            await cmRecompute(searchInput.value || '');
          }
        } catch (_) {}
      } else {
        // Re-run existing Pygments search highlighting when returning to basic mode
        try {
          if (searchInput) {
            searchInput.dispatchEvent(new Event('input', { bubbles: true }));
          }
        } catch (_) {}
      }
    }

    btn.addEventListener('click', function () {
      const next = currentMode === MODE_ADVANCED ? MODE_BASIC : MODE_ADVANCED;
      applyMode(next, { persist: true }).catch(function () {});
    });

    // Initial state from localStorage (default: basic)
    const saved = getSavedMode();
    applyMode(saved, { persist: false }).catch(function () {});

    // Intercept existing Pygments search listeners when advanced view is active.
    // We use capture + stopImmediatePropagation to override without editing the old script.
    if (searchInput) {
      searchInput.addEventListener(
        'input',
        function (ev) {
          if (!isAdvancedActive()) return;
          try {
            ev.stopImmediatePropagation();
          } catch (_) {}
          cmRecompute(searchInput.value || '').catch(function () {});
        },
        true
      );

      searchInput.addEventListener(
        'keydown',
        function (ev) {
          if (!isAdvancedActive()) return;
          const key = ev && ev.key ? String(ev.key) : '';
          if (key !== 'Enter') return;
          try {
            ev.preventDefault();
            ev.stopImmediatePropagation();
          } catch (_) {}
          if (!cmTerm || !cmMatches.length) {
            cmRecompute(searchInput.value || '').catch(function () {});
            return;
          }
          if (ev.shiftKey) {
            cmFocusIndex((cmActiveIndex >= 0 ? cmActiveIndex : 0) - 1);
          } else {
            cmFocusIndex((cmActiveIndex >= 0 ? cmActiveIndex : -1) + 1);
          }
        },
        true
      );
    }

    if (nextBtn) {
      nextBtn.addEventListener(
        'click',
        function (ev) {
          if (!isAdvancedActive()) return;
          try {
            ev.preventDefault();
            ev.stopImmediatePropagation();
          } catch (_) {}
          if (!cmTerm) {
            cmRecompute(searchInput ? (searchInput.value || '') : '').catch(function () {});
            return;
          }
          cmFocusIndex((cmActiveIndex >= 0 ? cmActiveIndex : -1) + 1);
        },
        true
      );
    }

    if (prevBtn) {
      prevBtn.addEventListener(
        'click',
        function (ev) {
          if (!isAdvancedActive()) return;
          try {
            ev.preventDefault();
            ev.stopImmediatePropagation();
          } catch (_) {}
          if (!cmTerm) {
            cmRecompute(searchInput ? (searchInput.value || '') : '').catch(function () {});
            return;
          }
          cmFocusIndex((cmActiveIndex >= 0 ? cmActiveIndex : 0) - 1);
        },
        true
      );
    }

    if (clearBtn) {
      clearBtn.addEventListener(
        'click',
        function (ev) {
          if (!isAdvancedActive()) return;
          try {
            ev.preventDefault();
            ev.stopImmediatePropagation();
          } catch (_) {}
          try {
            if (searchInput) searchInput.value = '';
          } catch (_) {}
          cmTerm = '';
          cmMatches = [];
          cmActiveIndex = -1;
          updateCmCount();
          cmClearSelection();
        },
        true
      );
    }
  });
})();

