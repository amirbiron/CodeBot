/* global fetch */

(function () {
  const STORAGE_KEY = 'code_tools_prefs_v1';

  function safeJsonParse(raw) {
    if (!raw || typeof raw !== 'string') return null;
    try {
      return JSON.parse(raw);
    } catch (_) {
      return null;
    }
  }

  function loadPrefs() {
    const parsed = safeJsonParse(localStorage.getItem(STORAGE_KEY));
    const tool = parsed && typeof parsed.tool === 'string' ? parsed.tool : 'black';
    const lineLength =
      parsed && typeof parsed.lineLength === 'number' && Number.isFinite(parsed.lineLength) ? parsed.lineLength : 88;
    return { tool, lineLength };
  }

  function savePrefs(next) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next || {}));
    } catch (_) {}
  }

  function showStatus(message, type = 'info') {
    const bar = document.getElementById('status-bar');
    const msg = bar ? bar.querySelector('.status-message') : null;
    if (!bar || !msg) return;
    msg.textContent = message || '';
    bar.classList.toggle('hidden', !message);
    bar.dataset.type = type;
  }

  async function ensureCodeMirrorLoaded() {
    if (
      window.CodeMirror6 &&
      window.CodeMirror6.EditorView &&
      window.CodeMirror6.EditorState &&
      typeof window.CodeMirror6.getLanguageSupport === 'function' &&
      window.CodeMirror6.MergeView
    ) {
      return;
    }

    // טעינה מקומית (bundle) — כמו EditorManager, אבל מינימלי לדף הזה
    await new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = `/static/js/codemirror.local.js?v=${Date.now()}`;
      s.onload = () => resolve();
      s.onerror = () => reject(new Error('codemirror.local.js failed to load'));
      document.head.appendChild(s);
    });

    // המתנה קצרה עד שה-API יופיע
    const started = Date.now();
    while (
      (!window.CodeMirror6 ||
        !window.CodeMirror6.EditorView ||
        !window.CodeMirror6.EditorState ||
        !window.CodeMirror6.MergeView) &&
      Date.now() - started < 2000
    ) {
      // eslint-disable-next-line no-await-in-loop
      await new Promise((r) => setTimeout(r, 50));
    }
  }

  function createEditor(parentEl, initialDoc) {
    if (!parentEl || !window.CodeMirror6 || !window.CodeMirror6.EditorView || !window.CodeMirror6.EditorState) {
      return null;
    }
    try {
      const { EditorState, EditorView, basicSetup, getLanguageSupport, getTheme } = window.CodeMirror6;
      const languageExt = getLanguageSupport('python') || [];
      // 🎨 Custom themes: בדיקת data-theme כדי לא לטעון oneDark כשיש ערכה מותאמת
      const htmlTheme = document && document.documentElement ? document.documentElement.getAttribute('data-theme') : '';
      const effectiveTheme = (htmlTheme === 'custom') ? 'custom' : 'dark';
      const themeExt = getTheme(effectiveTheme) || [];
      const state = EditorState.create({
        doc: typeof initialDoc === 'string' ? initialDoc : '',
        extensions: [...basicSetup, languageExt, themeExt],
      });
      return new EditorView({ state, parent: parentEl });
    } catch (_) {
      return null;
    }
  }

  function getDoc(view) {
    try {
      return view && view.state ? view.state.doc.toString() : '';
    } catch (_) {
      return '';
    }
  }

  function setDoc(view, next) {
    const value = typeof next === 'string' ? next : '';
    try {
      const curLen = view.state.doc.length;
      view.dispatch({
        changes: { from: 0, to: curLen, insert: value },
        selection: { anchor: Math.min(value.length, value.length) },
      });
    } catch (_) {}
  }

  function updateStats(view, targetEl) {
    if (!targetEl) return;
    const code = getDoc(view);
    const bytes = new TextEncoder().encode(code).length;
    const lines = code ? code.split('\n').length : 0;
    targetEl.textContent = `${lines} שורות · ${Math.round(bytes / 1024)}KB`;
  }

  async function postJson(url, body) {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) {
      const msg = data && (data.error || data.message) ? String(data.error || data.message) : 'שגיאת שרת';
      throw new Error(msg);
    }
    return data;
  }

  async function getJson(url) {
    const res = await fetch(url, { method: 'GET' });
    const data = await res.json().catch(() => null);
    if (!res.ok) {
      const msg = data && (data.error || data.message) ? String(data.error || data.message) : 'שגיאת שרת';
      throw new Error(msg);
    }
    return data;
  }

  function setViewMode(mode) {
    const viewButtons = Array.from(document.querySelectorAll('.view-btn[data-view]'));
    const views = ['code', 'diff', 'issues'];
    views.forEach((v) => {
      const el = document.getElementById(`${v}-view`);
      if (el) el.classList.toggle('active', v === mode);
    });
    viewButtons.forEach((btn) => btn.classList.toggle('active', btn.dataset.view === mode));
  }

  let mergeViewInstance = null;
  function renderProfessionalDiff(original, modified) {
    const host = document.getElementById('diff-merge');
    if (!host) return;
    host.innerHTML = '';
    mergeViewInstance = null;

    if (!window.CodeMirror6 || !window.CodeMirror6.MergeView) {
      host.textContent = 'CodeMirror לא נטען - לא ניתן להציג Diff.';
      return;
    }

    try {
      const { MergeView, basicSetup, getLanguageSupport, getTheme } = window.CodeMirror6;
      const languageExt = getLanguageSupport('python') || [];
      // 🎨 Custom themes: בדיקת data-theme כדי לא לטעון oneDark כשיש ערכה מותאמת
      const htmlTheme = document && document.documentElement ? document.documentElement.getAttribute('data-theme') : '';
      const effectiveTheme = (htmlTheme === 'custom') ? 'custom' : 'dark';
      const themeExt = getTheme(effectiveTheme) || [];

      mergeViewInstance = new MergeView({
        a: { doc: original || '', extensions: [...basicSetup, languageExt, themeExt] },
        b: { doc: modified || '', extensions: [...basicSetup, languageExt, themeExt] },
        parent: host,
        highlightChanges: true,
        gutter: true,
      });
    } catch (_) {
      host.textContent = 'לא הצלחנו להציג Diff מקצועי.';
    }
  }

  function renderIssues(result) {
    const issuesRoot = document.getElementById('issues-list');
    const scoreEl = document.getElementById('lint-score');
    if (!issuesRoot || !scoreEl) return;

    const score = typeof result.score === 'number' ? result.score : null;
    const issues = Array.isArray(result.issues) ? result.issues : [];
    const fixableCount = typeof result.fixable_count === 'number' ? result.fixable_count : 0;

    scoreEl.textContent = score !== null ? `ציון: ${score}/10` : '';

    if (!issues.length) {
      issuesRoot.innerHTML = '<div>✅ לא נמצאו בעיות</div>';
      return;
    }

    let html = `<div>${issues.length} בעיות נמצאו${fixableCount ? ` (${fixableCount} ניתנות לתיקון)` : ''}</div>`;
    html += '<ul class="issues-list">';
    for (const issue of issues.slice(0, 200)) {
      const sev = issue.severity || 'warning';
      const line = issue.line || 0;
      const col = issue.column || 0;
      const code = issue.code || '';
      const msg = issue.message || '';
      html += `
        <li class="issue-item ${sev}">
          <span class="issue-location">שורה ${line}:${col}</span>
          <span class="issue-code">${code}</span>
          <span class="issue-message">${msg}</span>
        </li>
      `;
    }
    html += '</ul>';
    issuesRoot.innerHTML = html;
  }

  function normalizeLineLength(raw) {
    const n = parseInt(String(raw || ''), 10);
    if (!Number.isFinite(n)) return 88;
    return Math.max(40, Math.min(200, n));
  }

  async function init() {
    try {
      await ensureCodeMirrorLoaded();
    } catch (_) {
      showStatus('לא הצלחנו לטעון את CodeMirror.', 'error');
      return;
    }

    const prefs = loadPrefs();

    const inputHost = document.getElementById('input-editor');
    const outputHost = document.getElementById('output-editor');
    const inputStats = document.getElementById('input-stats');
    const toolSelect = document.getElementById('format-tool');
    const lineLengthInput = document.getElementById('line-length');
    const toolsInfo = document.getElementById('tools-info');

    if (!inputHost || !outputHost) {
      return;
    }

    if (toolSelect) toolSelect.value = prefs.tool;
    if (lineLengthInput) lineLengthInput.value = String(prefs.lineLength);

    const inputEditor = createEditor(inputHost, 'x=1+   2\n');
    const outputEditor = createEditor(outputHost, '');

    updateStats(inputEditor, inputStats);

    // View toggle
    Array.from(document.querySelectorAll('.view-btn[data-view]')).forEach((btn) => {
      btn.addEventListener('click', () => {
        const mode = btn.dataset.view;
        setViewMode(mode);
        if (mode === 'diff') {
          renderProfessionalDiff(getDoc(inputEditor), getDoc(outputEditor));
        }
      });
    });

    // Preferences
    toolSelect?.addEventListener('change', () => {
      const next = { tool: toolSelect.value, lineLength: normalizeLineLength(lineLengthInput?.value) };
      savePrefs(next);
    });
    lineLengthInput?.addEventListener('change', () => {
      const next = { tool: toolSelect?.value || 'black', lineLength: normalizeLineLength(lineLengthInput.value) };
      lineLengthInput.value = String(next.lineLength);
      savePrefs(next);
    });

    const btnFormat = document.getElementById('btn-format');
    const btnLint = document.getElementById('btn-lint');
    const btnApply = document.getElementById('btn-apply');

    async function runFormat() {
      const code = getDoc(inputEditor);
      if (!code.trim()) {
        showStatus('אין קוד לעיצוב', 'warning');
        return;
      }

      const tool = toolSelect?.value || 'black';
      const lineLength = normalizeLineLength(lineLengthInput?.value);
      savePrefs({ tool, lineLength });

      showStatus('מעצב...', 'loading');
      try {
        const result = await postJson('/api/code/format', {
          code,
          language: 'python',
          tool,
          options: { line_length: lineLength },
        });
        if (result && result.success) {
          setDoc(outputEditor, result.formatted_code || '');
          btnApply && (btnApply.disabled = !result.has_changes);
          showStatus(result.has_changes ? `עיצוב הסתיים (${result.lines_changed} שורות)` : 'הקוד כבר מעוצב', 'success');
          updateStats(inputEditor, inputStats);
          if (document.getElementById('diff-view')?.classList.contains('active')) {
            renderProfessionalDiff(getDoc(inputEditor), getDoc(outputEditor));
          }
        } else {
          showStatus((result && result.error) || 'שגיאה בעיצוב', 'error');
        }
      } catch (e) {
        showStatus(e.message || 'שגיאה בעיצוב', 'error');
      }
    }

    async function runLint() {
      const code = getDoc(inputEditor);
      if (!code.trim()) {
        showStatus('אין קוד לבדיקה', 'warning');
        return;
      }

      showStatus('בודק...', 'loading');
      try {
        const result = await postJson('/api/code/lint', { code, language: 'python' });
        if (result && result.success) {
          renderIssues(result);
          setViewMode('issues');
          showStatus('בדיקת Lint הסתיימה', 'success');
        } else {
          showStatus((result && result.error) || 'שגיאה בבדיקה', 'error');
        }
      } catch (e) {
        showStatus(e.message || 'שגיאה בבדיקה', 'error');
      }
    }

    async function runFix(level) {
      const code = getDoc(inputEditor);
      if (!code.trim()) {
        showStatus('אין קוד לתיקון', 'warning');
        return;
      }

      showStatus('מתקן...', 'loading');
      try {
        const result = await postJson('/api/code/fix', { code, language: 'python', level: level || 'safe' });
        if (result && result.success) {
          setDoc(outputEditor, result.fixed_code || '');
          btnApply && (btnApply.disabled = !(result.fixed_code && result.fixed_code !== code));
          showStatus(
            result.fixes_applied && result.fixes_applied.length ? `תוקן: ${result.fixes_applied.join(', ')}` : 'אין תיקונים נדרשים',
            'success'
          );
          if (document.getElementById('diff-view')?.classList.contains('active')) {
            renderProfessionalDiff(getDoc(inputEditor), getDoc(outputEditor));
          }
        } else {
          showStatus((result && result.error) || 'שגיאה בתיקון', 'error');
        }
      } catch (e) {
        showStatus(e.message || 'שגיאה בתיקון', 'error');
      }
    }

    btnFormat?.addEventListener('click', runFormat);
    btnLint?.addEventListener('click', runLint);

    // Copy output to clipboard
    const btnCopy = document.getElementById('btn-copy-output');
    btnCopy?.addEventListener('click', async () => {
      const code = getDoc(outputEditor);
      if (!code.trim()) {
        showStatus('אין קוד להעתקה', 'warning');
        return;
      }

      try {
        await navigator.clipboard.writeText(code);
        btnCopy.classList.add('copied');
        const iconEl = btnCopy.querySelector('.copy-icon');
        const textEl = btnCopy.querySelector('.copy-text');
        if (iconEl) iconEl.textContent = '✓';
        if (textEl) textEl.textContent = 'הועתק!';
        showStatus('הקוד הועתק ללוח', 'success');

        setTimeout(() => {
          btnCopy.classList.remove('copied');
          if (iconEl) iconEl.textContent = '📋';
          if (textEl) textEl.textContent = 'העתק';
        }, 2000);
      } catch (e) {
        showStatus('לא הצלחנו להעתיק', 'error');
      }
    });

    document.querySelectorAll('.dropdown-item[data-level]').forEach((btn) => {
      btn.addEventListener('click', () => runFix(btn.dataset.level));
    });

    btnApply?.addEventListener('click', () => {
      const result = getDoc(outputEditor);
      if (!result.trim()) return;
      setDoc(inputEditor, result);
      btnApply.disabled = true;
      showStatus('הוחלו השינויים על קוד המקור', 'success');
      updateStats(inputEditor, inputStats);
      if (document.getElementById('diff-view')?.classList.contains('active')) {
        renderProfessionalDiff(getDoc(inputEditor), getDoc(outputEditor));
      }
    });

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey) {
        if (e.key === 'F') {
          e.preventDefault();
          runFormat();
        } else if (e.key === 'L') {
          e.preventDefault();
          runLint();
        }
      }
    });

    // Tools availability (optional)
    (async () => {
      try {
        const tools = await getJson('/api/code/tools');
        if (toolsInfo && tools && tools.tools) {
          const t = tools.tools;
          toolsInfo.textContent = `כלים: black=${!!t.black ? '✓' : '✗'} flake8=${!!t.flake8 ? '✓' : '✗'} isort=${
            !!t.isort ? '✓' : '✗'
          } autopep8=${!!t.autopep8 ? '✓' : '✗'}`;
        }
      } catch (_) {}
    })();
  }

  document.addEventListener('DOMContentLoaded', init);
})();

