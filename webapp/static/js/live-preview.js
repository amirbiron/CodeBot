(function () {
  const STATUS = {
    IDLE: 'idle',
    EMPTY: 'empty',
    LOADING: 'loading',
    READY: 'ready',
    ERROR: 'error',
  };

  const MARKDOWN_DEFAULT_TITLES = {
    note: 'הערה',
    tip: 'טיפ',
    warning: 'אזהרה',
    danger: 'סכנה',
    info: 'מידע',
    success: 'הצלחה',
    question: 'שאלה',
    example: 'דוגמה',
    quote: 'ציטוט',
    experimental: 'ניסוי',
    deprecated: 'לא מומלץ',
    todo: 'לעשות',
    abstract: 'תקציר',
  };

  function slugifyHeadingId(rawText) {
    try {
      let slug = (rawText || '')
        .toString()
        .trim()
        .toLowerCase()
        .normalize('NFKD')
        .replace(/[\u200B-\u200D\uFEFF]/g, '')
        .replace(/\p{M}+/gu, '')
        .replace(/[^\p{L}\p{N}\s-]+/gu, '')
        .replace(/\s+/g, '-')
        .replace(/-{2,}/g, '-')
        .replace(/^-+|-+$/g, '');
      if (!slug) {
        slug = 'section';
      }
      return slug;
    } catch (_) {
      const fallback = (rawText || '')
        .toString()
        .trim()
        .toLowerCase()
        .replace(/\s+/g, '-')
        .replace(/[^a-z0-9-]/g, '');
      return fallback || 'section';
    }
  }

  function getFileExtension(name = '') {
    const parts = (name || '').trim().toLowerCase().split('.');
    if (parts.length < 2) {
      return '';
    }
    return parts.pop();
  }

  const isMarkdownLanguage = (value = '') => {
    const normalized = value.toString().trim().toLowerCase();
    return normalized === 'markdown' || normalized === 'md';
  };

  const isHtmlLanguage = (value = '') => {
    const normalized = value.toString().trim().toLowerCase();
    return normalized === 'html' || normalized === 'htm';
  };

  const isMarkdownExtension = (value = '') => {
    const ext = getFileExtension(value);
    return ext === 'md' || ext === 'markdown';
  };

  const isHtmlExtension = (value = '') => {
    const ext = getFileExtension(value);
    return ext === 'html' || ext === 'htm';
  };

  function resolvePreviewMode(language, fileName) {
    const lang = (language || '').trim().toLowerCase();
    const hasExplicitLanguage = lang && lang !== 'text';
    if (hasExplicitLanguage) {
      if (isMarkdownLanguage(lang)) {
        return 'markdown';
      }
      if (isHtmlLanguage(lang)) {
        return 'html';
      }
      return 'code';
    }
    if (isMarkdownExtension(fileName || '')) {
      return 'markdown';
    }
    if (isHtmlExtension(fileName || '')) {
      return 'html';
    }
    return 'code';
  }

  const MarkdownLiveRenderer = (() => {
    let renderer = null;
    const containerTypes = [
      'details',
      'note',
      'tip',
      'warning',
      'danger',
      'info',
      'success',
      'question',
      'example',
      'quote',
      'experimental',
      'deprecated',
      'todo',
      'abstract',
    ];

    function ensureRenderer() {
      if (renderer) {
        return renderer;
      }
      if (typeof window === 'undefined' || typeof window.markdownit !== 'function') {
        return null;
      }
      const md = window.markdownit({
        breaks: true,
        linkify: true,
        typographer: true,
        html: false,
        highlight: function () {
          return '';
        },
      });
      const defaultInlineCode = md.renderer.rules.code_inline;
      const escapeHtml = (str) => {
        if (md.utils && typeof md.utils.escapeHtml === 'function') {
          return md.utils.escapeHtml(str);
        }
        return (str || '')
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/"/g, '&quot;')
          .replace(/'/g, '&#39;');
      };
      md.renderer.rules.code_inline = (tokens, idx, options, env, slf) => {
        try {
          const content = tokens[idx] && typeof tokens[idx].content === 'string' ? tokens[idx].content : '';
          const escaped = escapeHtml(content);
          return `<code class="inline-code">${escaped}</code>`;
        } catch (_) {
          return defaultInlineCode ? defaultInlineCode(tokens, idx, options, env, slf) : '';
        }
      };
      if (window.markdownitEmoji) {
        md.use(window.markdownitEmoji);
      }
      if (window.markdownitTaskLists) {
        md.use(window.markdownitTaskLists, { label: true, enabled: true });
      }
      if (window.markdownitAnchor) {
        const anchorOptions = { permalink: true, permalinkSymbol: '¶', slugify: slugifyHeadingId };
        try {
          md.use(window.markdownitAnchor, anchorOptions);
        } catch (_) {
          try {
            md.use(window.markdownitAnchor, { slugify: slugifyHeadingId });
          } catch (err) {
            console.warn('markdown-it-anchor failed', err);
          }
        }
      }
      if (window.markdownitFootnote) {
        md.use(window.markdownitFootnote);
      }
      if (window.markdownitAdmonition) {
        try {
          md.use(window.markdownitAdmonition, { types: containerTypes.filter((t) => t !== 'details') });
        } catch (err) {
          console.warn('markdown-it-admonition failed', err);
        }
      }
      if (window.markdownitContainer) {
        const containerPlugin = window.markdownitContainer;
        try {
          md.use(containerPlugin, 'details', {
            validate(params) {
              return /^details\b/i.test((params || '').trim());
            },
            render(tokens, idx) {
              const info = (tokens[idx].info || '').trim();
              const match = info.match(/^details\s+(.*)$/i);
              const title = (match && match[1] && match[1].trim()) || 'לחץ להצגה';
              if (tokens[idx].nesting === 1) {
                return `<details class="markdown-details"><summary class="markdown-summary">${md.utils.escapeHtml(
                  title
                )}</summary><div class="details-content">`;
              }
              return '</div></details>\n';
            },
          });
          containerTypes
            .filter((type) => type !== 'details')
            .forEach((type) => {
              const rxOpen = new RegExp(`^${type}\\b\\s*(.*)$`, 'i');
              md.use(containerPlugin, type, {
                validate(params) {
                  return rxOpen.test((params || '').trim());
                },
                render(tokens, idx) {
                  const info = (tokens[idx].info || '').trim();
                  const match = info.match(rxOpen);
                  const title = (match && match[1] && match[1].trim()) || MARKDOWN_DEFAULT_TITLES[type] || type;
                  if (tokens[idx].nesting === 1) {
                    return `<div class="admonition admonition-${type}"><div class="admonition-title">${md.utils.escapeHtml(
                      title
                    )}</div><div class="admonition-content">`;
                  }
                  return '</div></div>\n';
                },
              });
            });
        } catch (err) {
          console.warn('markdown-it-container failed', err);
        }
      }
      if (window.markdownitTocDoneRight) {
        try {
          md.use(window.markdownitTocDoneRight, { slugify: slugifyHeadingId });
        } catch (err) {
          console.warn('markdown-it-toc-done-right failed', err);
        }
      }
      renderer = md;
      return renderer;
    }

    function highlightBlocks(root) {
      if (!root || typeof window === 'undefined' || !window.hljs) {
        return;
      }
      root.querySelectorAll('pre code').forEach((block) => {
        try {
          window.hljs.highlightElement(block);
          const parent = block.closest('pre');
          if (parent) {
            parent.style.direction = 'ltr';
            parent.style.textAlign = 'left';
          }
        } catch (err) {
          console.warn('hljs highlight failed', err);
        }
      });
    }

    function enhanceTaskLists(root) {
      if (!root) {
        return;
      }
      root.querySelectorAll('input[type="checkbox"]').forEach((input) => {
        input.setAttribute('disabled', 'true');
        input.setAttribute('role', 'checkbox');
      });
    }

    function lazyLoadImages(root) {
      if (!root) {
        return;
      }
      root.querySelectorAll('img').forEach((img) => {
        if (!img.hasAttribute('loading')) {
          img.loading = 'lazy';
        }
        img.decoding = 'async';
        img.referrerPolicy = img.referrerPolicy || 'no-referrer';
      });
    }

    function renderMath(root) {
      if (!root || typeof window === 'undefined' || typeof window.renderMathInElement !== 'function') {
        return;
      }
      try {
        window.renderMathInElement(root, {
          delimiters: [
            { left: '$$', right: '$$', display: true },
            { left: '$', right: '$', display: false },
          ],
        });
      } catch (err) {
        console.warn('katex render failed', err);
      }
    }

    async function renderMermaid(root) {
      if (!root || typeof window === 'undefined' || typeof window.mermaid === 'undefined') {
        return;
      }
      const blocks = root.querySelectorAll('code.language-mermaid, pre code.language-mermaid');
      if (!blocks.length) {
        return;
      }
      try {
        window.mermaid.initialize({ startOnLoad: false, securityLevel: 'strict' });
      } catch (err) {
        console.warn('mermaid initialize failed', err);
      }
      let counter = 0;
      for (const block of blocks) {
        const code = block.textContent || '';
        const parent = block.closest('pre') || block.parentElement;
        const wrapper = document.createElement('div');
        wrapper.className = 'mermaid-diagram';
        if (parent && parent.parentNode) {
          parent.parentNode.replaceChild(wrapper, parent);
        } else if (parent) {
          parent.replaceWith(wrapper);
        } else {
          block.replaceWith(wrapper);
        }
        try {
          const { svg } = await window.mermaid.render(`mmd_live_${Date.now()}_${counter++}`, code);
          wrapper.innerHTML = svg;
        } catch (err) {
          wrapper.innerHTML = '<div class="alert alert-warning">Mermaid render failed</div>';
          console.warn('mermaid render failed', err);
        }
      }
    }

    async function enhance(root) {
      highlightBlocks(root);
      enhanceTaskLists(root);
      lazyLoadImages(root);
      renderMath(root);
      await renderMermaid(root);
    }

    return {
      isSupported() {
        return !!ensureRenderer();
      },
      async render(text) {
        const md = ensureRenderer();
        if (!md) {
          throw new Error('markdown_renderer_missing');
        }
        return md.render(text || '');
      },
      enhance,
    };
  })();

  class LivePreviewController {
    constructor(root) {
      this.root = root;
      this.toggleBtn = root ? root.querySelector('[data-action="toggle-live-preview"]') : null;
      this.shortcutHint = root ? root.querySelector('.split-toolbar-hint') : null;
      this.textarea = document.querySelector('textarea[name="code"]');
      this.languageSelect = document.getElementById('languageSelect');
      this.fileNameInput = document.querySelector('input[name="file_name"]');
      this.previewContent = root ? root.querySelector('[data-preview-content]') : null;
      this.previewCanvas = root ? root.querySelector('[data-preview-canvas]') : null;
      this.previewMeta = root ? root.querySelector('[data-preview-meta]') : null;
      this.statusEl = root ? root.querySelector('[data-preview-status]') : null;
      this.styleEl = null;
      this.abortController = null;
      this.state = {
        enabled: false,
        layoutPanel: 'editor',
        debounceTimer: null,
        lastRenderedHash: null,
        inflightHash: null,
        previewAllowed: false,
      };
      this.init();
    }

    init() {
      if (!this.root || !this.toggleBtn || !this.textarea || !this.previewContent || !this.previewCanvas) {
        return;
      }
      this.root.classList.remove('is-active');
      if (this.toggleBtn) {
        this.toggleBtn.setAttribute('aria-pressed', 'false');
      }

      this.toggleBtn.addEventListener('click', () => this.toggle());
      document.addEventListener('keydown', (event) => {
        const key = (event.key || '').toLowerCase();
        if (key === 'enter' && event.shiftKey && (event.ctrlKey || event.metaKey)) {
          event.preventDefault();
          this.toggle();
        }
      });
      this.textarea.addEventListener('input', () => {
        if (this.state.enabled) {
          this.scheduleUpdate();
        } else {
          this.setStatus(STATUS.IDLE);
        }
      });
      if (this.languageSelect) {
        this.languageSelect.addEventListener('change', () => {
          if (this.state.enabled) {
            this.scheduleUpdate();
          }
          this.updatePreviewAvailability();
        });
      }
      if (this.fileNameInput) {
        ['input', 'change', 'blur'].forEach((evt) => {
          this.fileNameInput.addEventListener(evt, () => {
            this.updatePreviewAvailability();
            if (this.state.enabled) {
              this.scheduleUpdate(true);
            }
          });
        });
      }
      this.setupTabs();
      this.setupResizer();
      this.updatePreviewAvailability({ silentDisable: true });
      this.setStatus(STATUS.IDLE);
    }

    toggle() {
      const nextState = !this.state.enabled;
      if (nextState && !this.isPreviewEligible()) {
        this.disablePreview('Live Preview זמין רק לקבצי Markdown/HTML');
        return;
      }
      const caretState = this.captureEditorState();
      if (nextState) {
        this.enablePreview();
        this.scheduleUpdate(true);
      } else {
        this.disablePreview('תצוגה חיה כבויה');
      }
      this.deferRestoreEditorState(caretState);
    }

    scheduleUpdate(immediate = false) {
      if (!this.state.enabled) {
        return;
      }
      if (this.state.debounceTimer) {
        clearTimeout(this.state.debounceTimer);
      }
      if (immediate) {
        this.fetchPreview();
        return;
      }
      this.state.debounceTimer = setTimeout(() => this.fetchPreview(), 500);
    }

    cancelPending() {
      if (this.abortController) {
        this.abortController.abort();
        this.abortController = null;
      }
      if (this.state.debounceTimer) {
        clearTimeout(this.state.debounceTimer);
        this.state.debounceTimer = null;
      }
      this.state.inflightHash = null;
    }

    async fetchPreview() {
      if (!this.textarea) {
        return;
      }
      const payload = {
        content: this.textarea.value || '',
        language: this.languageSelect ? this.languageSelect.value : '',
        file_name: this.fileNameInput ? this.fileNameInput.value : '',
      };
      payload.mode = resolvePreviewMode(payload.language, payload.file_name);
      const payloadHash = JSON.stringify(payload);
      this.cancelPending();
      if (
        payloadHash === this.state.lastRenderedHash ||
        payloadHash === this.state.inflightHash
      ) {
        return;
      }
      const preferClientMarkdown = payload.mode === 'markdown' && MarkdownLiveRenderer.isSupported();
      if (preferClientMarkdown) {
        try {
          await this.renderClientMarkdown(payload, payloadHash);
          return;
        } catch (err) {
          console.warn('Falling back to server preview after client Markdown failure', err);
        }
      }
      this.state.inflightHash = payloadHash;
      this.abortController = new AbortController();
      this.setStatus(STATUS.LOADING);
      try {
        const resp = await fetch('/api/preview/live', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
          signal: this.abortController.signal,
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || !data.ok) {
          const message = (data && data.error) || 'preview_failed';
          throw new Error(message);
        }
        this.renderPreview({ ...data, mode: data.mode || payload.mode });
        this.state.lastRenderedHash = payloadHash;
      } catch (err) {
        if (err.name === 'AbortError') {
          return;
        }
        console.warn('Live preview failed', err);
        this.setStatus(STATUS.ERROR, this.translateError(err.message));
      } finally {
        this.abortController = null;
        if (this.state.inflightHash === payloadHash) {
          this.state.inflightHash = null;
        }
      }
    }

    renderPreview(data) {
      if (!data) {
        this.setStatus(STATUS.ERROR, 'תגובה ריקה מהשרת');
        return;
      }
      const html = data.html || '';
      const presentation = data.presentation || 'fragment';
      const mode = data.mode || 'code';
      this.setMarkdownContext(mode === 'markdown' && presentation !== 'iframe');
      this.applyPreviewTheme(mode);
      if (presentation === 'iframe') {
        const iframe = document.createElement('iframe');
        iframe.setAttribute('sandbox', '');
        iframe.setAttribute('aria-label', 'תצוגה מקדימה ל-HTML');
        iframe.srcdoc = html;
        this.previewCanvas.replaceChildren(iframe);
      } else {
        this.previewCanvas.innerHTML = html || '<p>אין תוכן להצגה.</p>';
      }
      const metaStyles = data.meta && Array.isArray(data.meta.styles) ? data.meta.styles : null;
      const styles = metaStyles ? metaStyles.join('\n') : '';
      if (styles) {
        if (!this.styleEl) {
          this.styleEl = document.createElement('style');
          this.styleEl.dataset.previewStyle = 'live';
          this.previewContent.appendChild(this.styleEl);
        }
        this.styleEl.textContent = styles;
      } else if (this.styleEl) {
        this.styleEl.textContent = '';
      }
      this.updateMeta({ ...data.meta, mode });
      this.setStatus(STATUS.READY);
    }

    async renderClientMarkdown(payload, payloadHash) {
      if (!this.previewCanvas) {
        return;
      }
      const content = payload.content || '';
      const trimmed = content.trim();
      if (!trimmed) {
        this.setMarkdownContext(true);
        this.previewCanvas.innerHTML = '<p>אין תוכן להצגה.</p>';
        this.applyPreviewTheme('markdown');
        this.updateMeta({ language: 'markdown', mode: 'markdown', bytes: 0, characters: 0, duration_ms: 0 });
        this.setStatus(STATUS.EMPTY, 'אין טקסט להצגה.');
        this.state.lastRenderedHash = payloadHash;
        return;
      }
      const started = typeof performance !== 'undefined' && typeof performance.now === 'function' ? performance.now() : Date.now();
      this.state.inflightHash = payloadHash;
      this.setStatus(STATUS.LOADING);
      try {
        const html = await MarkdownLiveRenderer.render(content);
        this.setMarkdownContext(true);
        this.previewCanvas.innerHTML = html || '<p>אין תוכן להצגה.</p>';
        if (this.styleEl) {
          this.styleEl.textContent = '';
        }
        await MarkdownLiveRenderer.enhance(this.previewCanvas);
        this.applyPreviewTheme('markdown');
        const duration = typeof performance !== 'undefined' && typeof performance.now === 'function'
          ? Math.max(1, Math.round(performance.now() - started))
          : 0;
        const meta = {
          language: 'markdown',
          mode: 'markdown',
          bytes: this.bytesFromString(content),
          characters: content.length,
          duration_ms: duration,
        };
        this.updateMeta(meta);
        this.setStatus(STATUS.READY);
        this.state.lastRenderedHash = payloadHash;
      } finally {
        if (this.state.inflightHash === payloadHash) {
          this.state.inflightHash = null;
        }
      }
    }

    applyPreviewTheme(mode) {
      if (!this.previewContent) {
        return;
      }
      if (mode === 'markdown') {
        const docTheme = (document.documentElement && document.documentElement.dataset && document.documentElement.dataset.theme) || '';
        const prefersLight = docTheme && docTheme.toLowerCase().includes('dawn');
        this.previewContent.dataset.theme = prefersLight ? 'light' : 'dark';
      } else {
        this.previewContent.dataset.theme = 'light';
      }
    }

    setMarkdownContext(isMarkdown) {
      if (!this.previewCanvas) {
        return;
      }
      if (isMarkdown) {
        this.previewCanvas.setAttribute('id', 'md-content');
        this.previewCanvas.dataset.mode = 'markdown';
      } else {
        if (this.previewCanvas.id === 'md-content') {
          this.previewCanvas.removeAttribute('id');
        }
        this.previewCanvas.removeAttribute('data-mode');
      }
    }

    bytesFromString(value) {
      try {
        return new TextEncoder().encode(value || '').length;
      } catch (_) {
        return (value || '').length;
      }
    }

    updateMeta(meta = {}) {
      if (!this.previewMeta) return;
      const language = meta.language || '';
      const duration = typeof meta.duration_ms === 'number' ? `${meta.duration_ms}ms` : '';
      const size = typeof meta.bytes === 'number' ? `${(meta.bytes / 1024).toFixed(1)}KB` : '';
      this.previewMeta.textContent = [language, size, duration].filter(Boolean).join(' • ');
    }

    translateError(code) {
      switch (code) {
        case 'missing_content':
        case 'empty_content':
          return 'אין טקסט להצגה.';
        case 'content_too_large':
          return 'התוכן גדול מדי לתצוגה חיה.';
        case 'markdown_renderer_missing':
          return 'ספריית Markdown טרם נטענה.';
        case 'render_failed':
        default:
          return 'שגיאה ברינדור התצוגה.';
      }
    }

    setStatus(state, message) {
      if (!this.previewContent || !this.statusEl) {
        return;
      }
      this.previewContent.classList.toggle('is-loading', state === STATUS.LOADING);
      this.statusEl.textContent = message || this.defaultMessage(state);
      this.statusEl.dataset.state = state;
    }

    defaultMessage(state) {
      switch (state) {
        case STATUS.LOADING:
          return 'מרענן תצוגה...';
        case STATUS.ERROR:
          return 'שגיאה ברענון התצוגה.';
        case STATUS.READY:
          return 'התצוגה מעודכנת.';
        case STATUS.EMPTY:
          return 'אין טקסט להצגה.';
        case STATUS.IDLE:
        default:
          return 'הפעל את Live Preview כדי לראות עדכון בזמן אמת.';
      }
    }

    setupTabs() {
      const tabs = Array.from(this.root.querySelectorAll('[data-panel-target]'));
      if (!tabs.length) return;
      tabs.forEach((btn) => {
        btn.addEventListener('click', () => {
          const target = btn.dataset.panelTarget || 'editor';
          this.state.layoutPanel = target;
          this.root.dataset.activePanel = target;
          tabs.forEach((el) => {
            el.setAttribute('aria-selected', el === btn ? 'true' : 'false');
          });
        });
      });
    }

    setupResizer() {
      const resizer = this.root.querySelector('.split-resizer');
      if (!resizer) return;
      const panels = this.root.querySelector('.split-panels');
      const onPointerMove = (event, rect) => {
        const clamp = (value, min, max) => Math.min(Math.max(value, min), max);
        let ratio = (event.clientX - rect.left) / rect.width;
        if (document.documentElement.dir === 'rtl') {
          ratio = 1 - ratio;
        }
        ratio = clamp(ratio, 0.25, 0.75);
        this.root.style.setProperty('--split-editor-ratio', ratio.toFixed(2));
      };
      const startDrag = (event) => {
        if (!panels) return;
        event.preventDefault();
        const rect = panels.getBoundingClientRect();
        resizer.classList.add('is-dragging');
        const moveHandler = (e) => onPointerMove(e, rect);
        const upHandler = () => {
          document.removeEventListener('pointermove', moveHandler);
          document.removeEventListener('pointerup', upHandler);
          resizer.classList.remove('is-dragging');
        };
        document.addEventListener('pointermove', moveHandler);
        document.addEventListener('pointerup', upHandler, { once: true });
      };
      resizer.addEventListener('pointerdown', startDrag);
    }

    isPreviewEligible() {
      const languageRaw = this.languageSelect ? this.languageSelect.value : '';
      const lang = (languageRaw || '').trim().toLowerCase();
      const hasExplicitLanguage = lang && lang !== 'text';
      if (hasExplicitLanguage) {
        return isMarkdownLanguage(lang) || isHtmlLanguage(lang);
      }
      const fileName = this.fileNameInput ? this.fileNameInput.value : '';
      if (!fileName) {
        return false;
      }
      return isMarkdownExtension(fileName) || isHtmlExtension(fileName);
    }

    updatePreviewAvailability(options = {}) {
      const allowed = this.isPreviewEligible();
      this.state.previewAllowed = allowed;
      this.root.classList.toggle('preview-enabled', allowed);
      if (this.toggleBtn) {
        this.toggleBtn.hidden = !allowed;
        this.toggleBtn.tabIndex = allowed ? 0 : -1;
        this.toggleBtn.setAttribute('aria-disabled', allowed ? 'false' : 'true');
      }
      if (this.shortcutHint) {
        this.shortcutHint.hidden = !allowed;
      }
      if (!allowed && this.state.enabled) {
        const caretState = this.captureEditorState();
        this.disablePreview(options.silentDisable ? undefined : 'Live Preview זמין רק לקבצי Markdown/HTML');
        this.deferRestoreEditorState(caretState);
      }
    }

    enablePreview() {
      this.state.enabled = true;
      if (this.toggleBtn) {
        this.toggleBtn.setAttribute('aria-pressed', 'true');
      }
      this.root.classList.add('is-active');
    }

    disablePreview(message) {
      this.state.enabled = false;
      this.cancelPending();
      this.state.lastRenderedHash = null;
      this.state.inflightHash = null;
      if (this.toggleBtn) {
        this.toggleBtn.setAttribute('aria-pressed', 'false');
      }
      this.root.classList.remove('is-active');
      this.root.dataset.activePanel = 'editor';
      const tabs = this.root.querySelectorAll('[data-panel-target]');
      if (tabs && tabs.length) {
        tabs.forEach((el) => {
          const target = el.dataset.panelTarget || 'editor';
          el.setAttribute('aria-selected', target === 'editor' ? 'true' : 'false');
        });
      }
      try {
        this.root.style.removeProperty('--split-editor-ratio');
      } catch (_) {}
      this.setStatus(STATUS.IDLE, message || this.defaultMessage(STATUS.IDLE));
      if (this.previewCanvas) {
        this.previewCanvas.innerHTML = '<div class="split-preview-placeholder"><p>תצוגה חיה תופיע כאן</p><small>הפעל את Live Preview כדי לרענן בזמן אמת</small></div>';
      }
      if (this.previewMeta) {
        this.previewMeta.textContent = '';
      }
      this.setMarkdownContext(false);
      if (this.previewContent) {
        this.previewContent.removeAttribute('data-theme');
      }
      if (this.styleEl) {
        this.styleEl.textContent = '';
      }
    }

    captureEditorState() {
      try {
        if (window.editorManager && typeof window.editorManager.captureSelection === 'function') {
          const snapshot = window.editorManager.captureSelection();
          if (snapshot && typeof snapshot === 'object') {
            return { ...snapshot };
          }
        }
      } catch (_) {}
      if (this.textarea) {
        const el = this.textarea;
        const valueLen = (el.value || '').length;
        const anchor = typeof el.selectionStart === 'number' ? el.selectionStart : valueLen;
        const head = typeof el.selectionEnd === 'number' ? el.selectionEnd : anchor;
        return {
          anchor,
          head,
          scrollTop: typeof el.scrollTop === 'number' ? el.scrollTop : 0,
        };
      }
      return null;
    }

    restoreEditorState(state) {
      if (!state) {
        return;
      }
      try {
        if (window.editorManager && typeof window.editorManager.restoreSelection === 'function') {
          window.editorManager.restoreSelection(state);
          return;
        }
      } catch (_) {}
      if (this.textarea) {
        const el = this.textarea;
        const startRaw = typeof state.anchor === 'number' ? state.anchor : 0;
        const endRaw = typeof state.head === 'number' ? state.head : startRaw;
        const start = Math.max(0, Math.min(startRaw, endRaw));
        const end = Math.max(start, Math.max(startRaw, endRaw));
        if (typeof el.setSelectionRange === 'function') {
          try {
            el.setSelectionRange(start, end);
          } catch (_) {}
        }
        if (typeof state.scrollTop === 'number') {
          try {
            el.scrollTop = state.scrollTop;
          } catch (_) {}
        }
        try {
          el.focus();
        } catch (_) {}
      }
    }

    deferRestoreEditorState(state) {
      if (!state) {
        return;
      }
      const restore = () => this.restoreEditorState(state);
      if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
        window.requestAnimationFrame(restore);
      } else {
        setTimeout(restore, 0);
      }
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    const root = document.getElementById('livePreviewRoot');
    if (root) {
      window.livePreviewController = new LivePreviewController(root);
    }
  });
})();
