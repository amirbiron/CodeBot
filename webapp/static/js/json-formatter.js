/* global fetch */

/**
 * JSON Formatter (WebApp)
 * ======================
 * עיצוב, דחיסה, אימות ותיקון אוטומטי ל-JSON.
 *
 * הערה: בפרויקט זה ה-EditorManager הקיים הוא singleton (`window.editorManager`)
 * ולא מאפשר שני מופעי עורך במקביל. לכן אנחנו משתמשים בו לטעינת CodeMirror 6
 * (bundle/theme/lang), ומרימים שני editors עצמאיים דרך window.CodeMirror6.
 */

(function () {
  'use strict';

  const state = {
    isLoading: false,
    lastValidJson: null,
    cm: {
      input: null,
      output: null,
      highlighter: null,
      clearHighlightTimer: null,
    },
  };

  let elements = {};

  function cacheElements() {
    elements = {
      root: document.querySelector('.json-formatter-container'),

      inputHost: document.getElementById('json-input-editor'),
      outputHost: document.getElementById('json-output-editor'),
      inputFallback: document.getElementById('json-input'),
      outputFallback: document.getElementById('json-output'),

      inputStats: document.getElementById('input-stats'),
      outputStats: document.getElementById('output-stats'),

      btnFormat: document.getElementById('btn-format'),
      btnMinify: document.getElementById('btn-minify'),
      btnValidate: document.getElementById('btn-validate'),
      btnMagicFix: document.getElementById('btn-magic-fix'),
      btnCopy: document.getElementById('btn-copy'),
      btnClear: document.getElementById('btn-clear'),
      btnSample: document.getElementById('btn-sample'),

      validationMessage: document.getElementById('validation-message'),
    };
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = String(text ?? '');
    return div.innerHTML;
  }

  function showToast(message, type = 'info') {
    if (window.showToast) {
      window.showToast(message, type);
      return;
    }
    // eslint-disable-next-line no-console
    console.log(`[${type}] ${message}`);
  }

  function setLoading(isLoading) {
    state.isLoading = !!isLoading;
    const btns = [
      elements.btnFormat,
      elements.btnMinify,
      elements.btnValidate,
      elements.btnMagicFix,
      elements.btnCopy,
      elements.btnClear,
      elements.btnSample,
    ].filter(Boolean);

    btns.forEach((b) => {
      b.disabled = state.isLoading;
    });
  }

  function getInputValue() {
    if (state.cm.input && state.cm.input.state) {
      return state.cm.input.state.doc.toString();
    }
    return (elements.inputFallback && elements.inputFallback.value) || '';
  }

  function getOutputValue() {
    if (state.cm.output && state.cm.output.state) {
      return state.cm.output.state.doc.toString();
    }
    return (elements.outputFallback && elements.outputFallback.value) || '';
  }

  function setTextareaValue(textarea, next) {
    if (!textarea) return;
    textarea.value = typeof next === 'string' ? next : '';
  }

  function setDoc(view, next, { focus = false } = {}) {
    const value = typeof next === 'string' ? next : '';
    if (!view || !view.state) return;
    try {
      const curLen = view.state.doc.length;
      view.dispatch({
        changes: { from: 0, to: curLen, insert: value },
        selection: { anchor: Math.min(value.length, value.length) },
      });
      if (focus) {
        try {
          view.focus();
        } catch (_) {}
      }
    } catch (_) {}
  }

  function setInputValue(next) {
    if (state.cm.input) {
      setDoc(state.cm.input, next, { focus: true });
    } else {
      setTextareaValue(elements.inputFallback, next);
      try {
        elements.inputFallback.focus();
      } catch (_) {}
    }
    updateInputStats();
  }

  function setOutputValue(next) {
    if (state.cm.output) {
      setDoc(state.cm.output, next);
    } else {
      setTextareaValue(elements.outputFallback, next);
    }
    updateOutputStats();
  }

  function formatBytes(bytes) {
    const b = typeof bytes === 'number' && Number.isFinite(bytes) ? bytes : 0;
    if (b <= 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB'];
    const i = Math.floor(Math.log(b) / Math.log(k));
    return `${parseFloat((b / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
  }

  function updateInputStats() {
    if (!elements.inputStats) return;
    const content = getInputValue();
    const bytes = new TextEncoder().encode(content).length;
    const lines = content ? content.split('\n').length : 0;
    elements.inputStats.textContent = `${lines} שורות · ${formatBytes(bytes)}`;
  }

  function updateOutputStats() {
    if (!elements.outputStats) return;
    const content = getOutputValue();
    const bytes = new TextEncoder().encode(content).length;
    const lines = content ? content.split('\n').length : 0;
    elements.outputStats.textContent = `${lines} שורות · ${formatBytes(bytes)}`;
  }

  function showValidation(type, title, details, actionsHtml) {
    const el = elements.validationMessage;
    if (!el) return;

    el.classList.remove('hidden', 'success', 'error');
    el.classList.add(type === 'success' ? 'success' : 'error');

    el.innerHTML = `
      <div class="msg-row">
        <div class="msg-icon">${type === 'success' ? '✓' : '✗'}</div>
        <div class="msg-content">
          <div class="msg-title">${escapeHtml(title || '')}</div>
          <div class="msg-details">${escapeHtml(details || '')}</div>
          ${actionsHtml ? `<div class="msg-actions">${actionsHtml}</div>` : ''}
        </div>
      </div>
    `;
  }

  function hideValidation() {
    const el = elements.validationMessage;
    if (!el) return;
    el.classList.add('hidden');
    el.classList.remove('success', 'error');
    el.innerHTML = '';
  }

  function createErrorLineHighlighter() {
    try {
      const mods = (window.CodeMirror6 && window.CodeMirror6._mods) || {};
      const stateMod = mods.stateMod;
      const viewMod = mods.viewMod;
      if (!stateMod || !viewMod) return null;

      const { StateEffect, StateField } = stateMod;
      const { Decoration, EditorView } = viewMod;
      if (!StateEffect || !StateField || !Decoration || !EditorView) return null;

      const setErrorLine = StateEffect.define();

      const errorField = StateField.define({
        create() {
          return Decoration.none;
        },
        update(deco, tr) {
          let next = deco.map(tr.changes);
          for (const e of tr.effects) {
            if (e.is(setErrorLine)) {
              const raw = e.value;
              const lineNumber = typeof raw === 'number' ? raw : parseInt(String(raw || ''), 10);
              if (!lineNumber || lineNumber < 1) {
                next = Decoration.none;
                continue;
              }
              const safeLine = Math.min(Math.max(1, lineNumber), tr.state.doc.lines || 1);
              const line = tr.state.doc.line(safeLine);
              next = Decoration.set([Decoration.line({ class: 'error-line' }).range(line.from)]);
            }
          }
          return next;
        },
        provide: (f) => EditorView.decorations.from(f),
      });

      return { setErrorLine, errorField };
    } catch (_) {
      return null;
    }
  }

  function clearErrorHighlight() {
    try {
      if (state.cm.clearHighlightTimer) {
        clearTimeout(state.cm.clearHighlightTimer);
        state.cm.clearHighlightTimer = null;
      }
    } catch (_) {}

    if (state.cm.input && state.cm.highlighter) {
      try {
        state.cm.input.dispatch({ effects: state.cm.highlighter.setErrorLine.of(0) });
      } catch (_) {}
    }
  }

  function highlightError(line, column) {
    clearErrorHighlight();

    const ln = typeof line === 'number' ? line : parseInt(String(line || ''), 10);
    const col = typeof column === 'number' ? column : parseInt(String(column || ''), 10);

    // CodeMirror 6
    if (state.cm.input && state.cm.input.state) {
      try {
        const view = state.cm.input;
        const safeLine = Math.min(Math.max(1, ln || 1), view.state.doc.lines || 1);
        const lineInfo = view.state.doc.line(safeLine);
        const safeCol = Math.max(0, (col || 1) - 1);
        const pos = Math.min(lineInfo.from + safeCol, lineInfo.to);

        const effects = [];
        if (state.cm.highlighter) {
          effects.push(state.cm.highlighter.setErrorLine.of(safeLine));
        }

        view.dispatch({
          selection: { anchor: pos },
          scrollIntoView: true,
          effects,
        });

        try {
          view.focus();
        } catch (_) {}

        state.cm.clearHighlightTimer = setTimeout(() => clearErrorHighlight(), 3000);
        return;
      } catch (_) {
        // continue to fallback
      }
    }

    // textarea fallback
    const textarea = elements.inputFallback;
    if (!textarea) return;

    try {
      const lines = textarea.value.split('\n');
      let position = 0;
      for (let i = 0; i < (ln || 1) - 1 && i < lines.length; i++) {
        position += lines[i].length + 1;
      }
      position += Math.max(0, (col || 1) - 1);
      textarea.focus();
      textarea.setSelectionRange(position, Math.min(position + 1, textarea.value.length));
    } catch (_) {}
  }

  async function waitForEditorManager(timeoutMs = 3500) {
    const started = Date.now();
    while (!window.editorManager && Date.now() - started < timeoutMs) {
      // eslint-disable-next-line no-await-in-loop
      await new Promise((r) => setTimeout(r, 50));
    }
    return window.editorManager || null;
  }

  function resolveEffectiveThemeForEditorParity() {
    try {
      const raw = document && document.documentElement ? document.documentElement.getAttribute('data-theme') : '';
      const t = String(raw || '').toLowerCase();
      if (t === 'custom') return 'custom';
      // editor pages pass theme='dark' and only special-case custom
      return 'dark';
    } catch (_) {
      return 'dark';
    }
  }

  async function ensureCodeMirrorLoaded(editorManager) {
    if (window.CodeMirror6 && window.CodeMirror6.EditorView && window.CodeMirror6.EditorState) {
      return true;
    }
    if (editorManager && typeof editorManager.loadCodeMirror === 'function') {
      try {
        await editorManager.loadCodeMirror();
      } catch (_) {}
    }
    return !!(window.CodeMirror6 && window.CodeMirror6.EditorView && window.CodeMirror6.EditorState);
  }

  async function initEditors() {
    const editorManager = await waitForEditorManager(3500);
    const ok = await ensureCodeMirrorLoaded(editorManager);
    if (!ok) {
      // נשארים על textarea
      return;
    }

    if (!elements.root || !elements.inputHost || !elements.outputHost) {
      return;
    }

    try {
      const { EditorState, EditorView, basicSetup } = window.CodeMirror6;
      const mods = (window.CodeMirror6 && window.CodeMirror6._mods) || {};
      const viewMod = mods.viewMod;
      const stateMod = mods.stateMod;
      if (!EditorState || !EditorView || !basicSetup || !viewMod || !stateMod) {
        return;
      }

      const themeName = resolveEffectiveThemeForEditorParity();

      let langSupport = [];
      let themeExt = [];
      try {
        if (editorManager && typeof editorManager.getLanguageSupport === 'function') {
          langSupport = (await editorManager.getLanguageSupport('json')) || [];
        }
      } catch (_) {
        langSupport = [];
      }
      try {
        if (editorManager && typeof editorManager.getTheme === 'function') {
          themeExt = (await editorManager.getTheme(themeName)) || [];
        }
      } catch (_) {
        themeExt = [];
      }

      // 🎨 Custom themes: dynamic syntax highlighter (כמו view-codemirror-toggle.js)
      let customSyntaxHighlighter = null;
      if (themeName === 'custom' && window.CodeMirror6.getSyntaxHighlighter) {
        try {
          customSyntaxHighlighter = window.CodeMirror6.getSyntaxHighlighter();
        } catch (_) {}
      }

      const highlighter = createErrorLineHighlighter();
      state.cm.highlighter = highlighter;

      const inputExtensions = [
        ...(basicSetup || []),
        ...(langSupport || []),
        ...(themeExt || []),
        ...(customSyntaxHighlighter ? [customSyntaxHighlighter] : []),
        EditorView.lineWrapping,
        ...(highlighter ? [highlighter.errorField] : []),
        EditorView.updateListener.of((update) => {
          if (update.docChanged) {
            updateInputStats();
            clearErrorHighlight();
          }
        }),
      ];

      const outputExtensions = [
        ...(basicSetup || []),
        ...(langSupport || []),
        ...(themeExt || []),
        ...(customSyntaxHighlighter ? [customSyntaxHighlighter] : []),
        EditorView.lineWrapping,
        EditorState.readOnly.of(true),
        (viewMod && viewMod.EditorView && viewMod.EditorView.editable)
          ? viewMod.EditorView.editable.of(false)
          : EditorView.editable.of(false),
      ];

      const initialInput = (elements.inputFallback && elements.inputFallback.value) || '';

      const inputState = EditorState.create({ doc: initialInput, extensions: inputExtensions });
      const outputState = EditorState.create({ doc: '', extensions: outputExtensions });

      state.cm.input = new EditorView({ state: inputState, parent: elements.inputHost });
      state.cm.output = new EditorView({ state: outputState, parent: elements.outputHost });

      elements.root.classList.add('cm-ready');

      updateInputStats();
      updateOutputStats();
    } catch (_) {
      // Fallback: textarea
      state.cm.input = null;
      state.cm.output = null;
      state.cm.highlighter = null;
    }
  }

  async function apiCall(endpoint, data) {
    setLoading(true);
    try {
      const response = await fetch(`/api/json/${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify(data || {}),
      });

      const result = await response.json().catch(() => null);
      if (!response.ok) {
        const msg = result && result.error ? String(result.error) : 'שגיאה בבקשה';
        const err = new Error(msg);
        err.details = result;
        throw err;
      }
      return result;
    } finally {
      setLoading(false);
    }
  }

  async function formatJson() {
    const content = getInputValue().trim();
    if (!content) {
      showToast('אנא הזן JSON', 'warning');
      return;
    }

    try {
      const result = await apiCall('format', { content, indent: 2, sort_keys: false });
      setOutputValue(result.result || '');
      state.lastValidJson = result.result || null;
      hideValidation();
      if (result && result.stats) {
        showValidation('success', 'הצלחה', `JSON תקין. מפתחות: ${result.stats.total_keys} · עומק: ${result.stats.max_depth}`);
      } else {
        showValidation('success', 'הצלחה', 'JSON תקין ועוצב בהצלחה');
      }
    } catch (e) {
      const details = e && e.details ? e.details : null;
      showValidation('error', 'שגיאה', e && e.message ? e.message : 'JSON לא תקין', '<button type="button" class="btn btn-magic" id="btn-suggest-fix">🪄 Magic Fix</button>');
      try {
        const btn = document.getElementById('btn-suggest-fix');
        if (btn) btn.addEventListener('click', magicFix, { once: true });
      } catch (_) {}
      if (details && details.line) {
        highlightError(details.line, details.column);
      }
    }
  }

  async function minifyJson() {
    const content = getInputValue().trim();
    if (!content) {
      showToast('אנא הזן JSON', 'warning');
      return;
    }

    try {
      const result = await apiCall('minify', { content });
      setOutputValue(result.result || '');
      const savings =
        result && typeof result.savings_percent === 'number'
          ? `חיסכון: ${result.savings_percent}%`
          : 'הסתיים';
      showValidation('success', 'הצלחה', savings);
    } catch (e) {
      const details = e && e.details ? e.details : null;
      showValidation('error', 'שגיאה', e && e.message ? e.message : 'JSON לא תקין', '<button type="button" class="btn btn-magic" id="btn-suggest-fix">🪄 Magic Fix</button>');
      try {
        const btn = document.getElementById('btn-suggest-fix');
        if (btn) btn.addEventListener('click', magicFix, { once: true });
      } catch (_) {}
      if (details && details.line) {
        highlightError(details.line, details.column);
      }
    }
  }

  async function validateJson() {
    const content = getInputValue().trim();
    if (!content) {
      showToast('אנא הזן JSON', 'warning');
      return;
    }

    clearErrorHighlight();

    try {
      const result = await apiCall('validate', { content });
      if (result && result.is_valid) {
        showValidation(
          'success',
          'JSON תקין',
          result.stats
            ? `מפתחות: ${result.stats.total_keys} · עומק: ${result.stats.max_depth}`
            : 'JSON תקין!'
        );
      } else {
        const msg = result
          ? `שורה ${result.line}, עמודה ${result.column}: ${result.error}`
          : 'JSON לא תקין';
        showValidation('error', 'JSON לא תקין', msg, '<button type="button" class="btn btn-magic" id="btn-suggest-fix">🪄 Magic Fix</button>');
        try {
          const btn = document.getElementById('btn-suggest-fix');
          if (btn) btn.addEventListener('click', magicFix, { once: true });
        } catch (_) {}
        highlightError(result.line, result.column);
      }
    } catch (e) {
      showValidation('error', 'שגיאה', e && e.message ? e.message : 'שגיאה באימות');
    }
  }

  async function magicFix() {
    const content = getInputValue();
    if (!content.trim()) {
      showToast('אנא הזן JSON', 'warning');
      return;
    }

    try {
      const result = await apiCall('fix', { content });
      const fixed = result && result.result ? String(result.result) : '';
      const fixes = result && Array.isArray(result.fixes_applied) ? result.fixes_applied : [];

      if (!fixed) {
        showValidation('error', 'שגיאה', 'לא הצלחנו לתקן');
        return;
      }

      setInputValue(fixed);

      if (fixes.length) {
        showValidation('success', 'תוקן', `תיקונים: ${fixes.join(', ')}`);
      } else {
        showValidation('success', 'תוקן', 'JSON תוקן (או שלא נדרשו תיקונים)');
      }

      // אחרי תיקון, ננסה לעצב כדי להציג תוצאה יפה
      try {
        await formatJson();
      } catch (_) {}
    } catch (e) {
      showValidation('error', 'לא הצלחנו לתקן', e && e.message ? e.message : 'שגיאה');
    }
  }

  async function copyToClipboard() {
    const text = getOutputValue() || getInputValue();
    if (!text.trim()) {
      showToast('אין תוכן להעתקה', 'warning');
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      showToast('הועתק ללוח', 'success');
    } catch (_) {
      showToast('לא הצלחנו להעתיק', 'error');
    }
  }

  function clearAll() {
    clearErrorHighlight();
    hideValidation();
    state.lastValidJson = null;
    setInputValue('');
    setOutputValue('');
  }

  function loadSample() {
    const sample = {
      name: 'JSON Formatter',
      version: '1.0.0',
      ok: true,
      numbers: [1, 2, 3],
      nested: { a: { b: { c: 1 } } },
    };
    setInputValue(JSON.stringify(sample, null, 2));
    hideValidation();
  }

  function bindEvents() {
    elements.btnFormat && elements.btnFormat.addEventListener('click', formatJson);
    elements.btnMinify && elements.btnMinify.addEventListener('click', minifyJson);
    elements.btnValidate && elements.btnValidate.addEventListener('click', validateJson);
    elements.btnMagicFix && elements.btnMagicFix.addEventListener('click', magicFix);
    elements.btnCopy && elements.btnCopy.addEventListener('click', copyToClipboard);
    elements.btnClear && elements.btnClear.addEventListener('click', clearAll);
    elements.btnSample && elements.btnSample.addEventListener('click', loadSample);

    // textarea fallback live stats
    if (elements.inputFallback) {
      elements.inputFallback.addEventListener('input', () => updateInputStats());
    }

    // Keyboard shortcuts
    document.addEventListener('keydown', (event) => {
      // Ctrl/Cmd + Shift + F = Format
      if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key === 'F') {
        event.preventDefault();
        formatJson();
      }
      // Ctrl/Cmd + Enter = Validate
      if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
        event.preventDefault();
        validateJson();
      }
    });
  }

  async function init() {
    cacheElements();
    bindEvents();
    updateInputStats();
    updateOutputStats();
    await initEditors();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

