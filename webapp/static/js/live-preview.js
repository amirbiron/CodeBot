(function () {
  const STATUS = {
    IDLE: 'idle',
    EMPTY: 'empty',
    LOADING: 'loading',
    READY: 'ready',
    ERROR: 'error',
  };

  class LivePreviewController {
    constructor(root) {
      this.root = root;
      this.toggleBtn = root ? root.querySelector('[data-action="toggle-live-preview"]') : null;
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
      };
      this.init();
    }

    init() {
      if (!this.root || !this.toggleBtn || !this.textarea || !this.previewContent || !this.previewCanvas) {
        return;
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
        });
      }
      if (this.fileNameInput) {
        this.fileNameInput.addEventListener('blur', () => {
          if (this.state.enabled) {
            this.scheduleUpdate();
          }
        });
      }
      this.setupTabs();
      this.setupResizer();
      this.setStatus(STATUS.IDLE);
    }

    toggle() {
      this.state.enabled = !this.state.enabled;
      this.toggleBtn.setAttribute('aria-pressed', this.state.enabled ? 'true' : 'false');
      this.root.classList.toggle('is-active', this.state.enabled);
      if (this.state.enabled) {
        this.scheduleUpdate(true);
      } else {
        this.cancelPending();
        this.state.lastRenderedHash = null;
        this.state.inflightHash = null;
        this.setStatus(STATUS.IDLE, 'תצוגה חיה כבויה');
        this.previewCanvas.innerHTML = '';
        this.previewMeta.textContent = '';
        if (this.styleEl) {
          this.styleEl.textContent = '';
        }
      }
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
      const payloadHash = JSON.stringify(payload);
      this.cancelPending();
      if (
        payloadHash === this.state.lastRenderedHash ||
        payloadHash === this.state.inflightHash
      ) {
        return;
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
        this.renderPreview(data);
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
      this.updateMeta(data.meta);
      this.setStatus(STATUS.READY);
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
  }

  document.addEventListener('DOMContentLoaded', () => {
    const root = document.getElementById('livePreviewRoot');
    if (root) {
      window.livePreviewController = new LivePreviewController(root);
    }
  });
})();
