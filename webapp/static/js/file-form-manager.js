(function () {
  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async function waitFor(fn, { timeoutMs = 3500, intervalMs = 100 } = {}) {
    const started = Date.now();
    // eslint-disable-next-line no-constant-condition
    while (true) {
      try {
        const value = fn();
        if (value) {
          return value;
        }
      } catch (_) {}
      if (Date.now() - started > timeoutMs) {
        return null;
      }
      // eslint-disable-next-line no-await-in-loop
      await sleep(intervalMs);
    }
  }

  function safeJsonParse(raw) {
    if (!raw || typeof raw !== 'string') {
      return null;
    }
    try {
      return JSON.parse(raw);
    } catch (_) {
      return null;
    }
  }

  function normalizeMode(mode) {
    const m = String(mode || '').toLowerCase();
    return m === 'edit' ? 'edit' : 'create';
  }

  function isMarkdownLanguage(value) {
    const v = String(value || '').trim().toLowerCase();
    return v === 'markdown' || v === 'md';
  }

  function isMarkdownFilename(name) {
    const n = String(name || '').trim().toLowerCase();
    return /\.(md|markdown)$/i.test(n);
  }

  class SourceUrlManager {
    constructor({ container }) {
      this.container = container;
      this.toggleBtn = null;
      this.field = null;
      this.input = null;
      this.touchedInput = null;
    }

    init() {
      if (!this.container) {
        return;
      }
      // תואם לאחור: עדיין עובדים עם ה-IDs הקיימים אם יש
      this.toggleBtn =
        this.container.querySelector('[data-action="toggle-source-url"]') ||
        this.container.querySelector('#sourceUrlToggle');
      this.field =
        this.container.querySelector('[data-role="source-url-field"]') ||
        this.container.querySelector('#sourceUrlField');
      this.input =
        this.container.querySelector('[data-role="source-url-input"]') ||
        this.container.querySelector('#sourceUrlInput');
      this.touchedInput =
        this.container.querySelector('[data-role="source-url-touched"]') ||
        this.container.querySelector('#sourceUrlTouched');

      if (!this.toggleBtn || !this.field || !this.input) {
        return;
      }

      const defaultOpen = this.field.dataset.open === '1' || this.field.classList.contains('is-open');
      this.setOpen(defaultOpen, { focus: false, markTouched: false });

      this.toggleBtn.addEventListener('click', () => {
        const next = !this.field.classList.contains('is-open');
        this.setOpen(next, { focus: next, markTouched: false });
      });

      this.input.addEventListener('input', () => this.markTouched());
    }

    markTouched() {
      if (this.touchedInput) {
        this.touchedInput.value = 'edited';
      }
    }

    setOpen(isOpen, { focus = false, markTouched = false } = {}) {
      if (!this.toggleBtn || !this.field) {
        return;
      }
      this.field.classList.toggle('is-open', !!isOpen);
      this.field.dataset.open = isOpen ? '1' : '0';
      this.toggleBtn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');

      const openLabel = this.toggleBtn.dataset.openLabel || 'הסתר קישור למקור';
      const closedLabel = this.toggleBtn.dataset.closedLabel || 'הוסף קישור למקור';
      const textNode = this.toggleBtn.querySelector('.source-url-toggle__text');
      const label = isOpen ? openLabel : closedLabel;
      if (textNode) {
        textNode.textContent = label;
      } else {
        this.toggleBtn.textContent = label;
      }

      if (markTouched) {
        this.markTouched();
      }

      if (focus && this.input) {
        setTimeout(() => {
          try {
            this.input.focus();
          } catch (_) {}
        }, 80);
      }
    }
  }

  class LanguageDetector {
    constructor({ filenameInput, languageSelect, editorManager, onChange }) {
      this.filenameInput = filenameInput;
      this.languageSelect = languageSelect;
      this.editorManager = editorManager;
      this.onChange = typeof onChange === 'function' ? onChange : null;
      this.touched = false;
    }

    init() {
      if (!this.languageSelect) {
        return;
      }

      this.languageSelect.addEventListener('change', async (e) => {
        try {
          if (e && e.isTrusted) {
            this.touched = true;
          }
        } catch (_) {}

        const value = this.languageSelect.value;
        try {
          if (this.editorManager && typeof this.editorManager.updateLanguage === 'function') {
            await this.editorManager.updateLanguage(value);
          }
        } catch (_) {}

        try {
          if (this.onChange) {
            this.onChange({ language: value });
          }
        } catch (_) {}
      });

      if (this.filenameInput) {
        this.filenameInput.addEventListener('input', () => this.autoDetect('input'));
        this.filenameInput.addEventListener('blur', () => this.autoDetect('blur'));
      }

      // initial
      this.autoDetect('initial');
    }

    languageOptionExists(value) {
      if (!this.languageSelect) {
        return false;
      }
      const target = String(value || '').toLowerCase();
      if (!target) {
        return false;
      }
      return !!Array.from(this.languageSelect.options || []).find((opt) => {
        const optValue = opt && typeof opt.value === 'string' ? opt.value.toLowerCase() : '';
        return optValue === target;
      });
    }

    autoDetect(triggerSource) {
      if (!this.filenameInput || !this.languageSelect) {
        return;
      }

      // אל תדרוס בחירה קיימת בטעינה הראשונה אם המשתמש כבר על שפה ספציפית
      if (triggerSource === 'initial' && this.languageSelect.value !== 'text') {
        // עדיין צריך לעדכן UI שתלוי בשם הקובץ (למשל רכיב התמונות)
        try {
          if (this.onChange) {
            this.onChange({ language: this.languageSelect.value });
          }
        } catch (_) {}
        return;
      }

      const filename = this.filenameInput.value || '';
      let detected = null;
      try {
        if (this.editorManager && typeof this.editorManager.inferLanguageFromFilename === 'function') {
          detected = this.editorManager.inferLanguageFromFilename(filename);
        }
      } catch (_) {
        detected = null;
      }

      const manualLocked = this.touched && this.languageSelect.value !== 'text';

      if (!manualLocked) {
        // רק אם לא נעול - משנים את ה-Dropdown
        if (detected && this.languageOptionExists(detected) && this.languageSelect.value !== detected) {
          this.languageSelect.value = detected;
          try {
            this.languageSelect.dispatchEvent(new Event('change', { bubbles: true }));
          } catch (_) {}
        }
      }

      // תמיד קוראים ל-onChange כדי לעדכן UI שתלוי בשם הקובץ (כמו כפתור/רכיב התמונות)
      try {
        if (this.onChange) {
          this.onChange({ language: this.languageSelect.value });
        }
      } catch (_) {}
    }
  }

  class ImageManager {
    constructor({ widget, form, filenameInput, languageSelect, mode }) {
      this.widget = widget;
      this.form = form;
      this.filenameInput = filenameInput;
      this.languageSelect = languageSelect;
      this.mode = normalizeMode(mode);

      this.addBtn = null;
      this.fileInput = null;
      this.previews = null;
      this.statusEl = null;
      this.errorEl = null;

      this.newImages = [];
      this.deletedExistingIds = new Set();
      this.fullscreen = null;
      this.fullscreenImg = null;
      this.fullscreenCaption = null;
      this.prevBodyOverflow = '';

      this.MARKDOWN_IMAGE_LIMIT = 6;
      this.MARKDOWN_IMAGE_MAX_BYTES = 2 * 1024 * 1024;
      this.MARKDOWN_ALLOWED_TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/gif'];
    }

    init() {
      if (!this.widget) {
        return;
      }

      this.addBtn = this.widget.querySelector('[data-action="add-image"]');
      this.fileInput = this.widget.querySelector('[data-role="file-input"]') || this.widget.querySelector('input[type="file"]');
      this.previews = this.widget.querySelector('[data-role="previews"]') || this.widget.querySelector('.previews-container');
      this.statusEl = this.widget.querySelector('[data-role="image-status"]');
      this.errorEl = this.widget.querySelector('[data-role="image-error"]');

      if (this.addBtn && this.fileInput) {
        this.addBtn.addEventListener('click', () => {
          try {
            this.fileInput.click();
          } catch (_) {}
        });
      }

      if (this.fileInput) {
        this.fileInput.addEventListener('change', (event) => {
          try {
            const files = event && event.target ? event.target.files : null;
            this.handleFiles(files);
          } finally {
            // כדי לאפשר לבחור אותה תמונה שוב
            try {
              event.target.value = '';
            } catch (_) {}
          }
        });
      }

      if (this.previews) {
        this.previews.addEventListener('click', (event) => {
          const deleteBtn = event.target && event.target.closest ? event.target.closest('[data-action="delete-image"]') : null;
          if (deleteBtn) {
            const node = deleteBtn.closest('.image-preview');
            const id = node ? node.getAttribute('data-image-id') : '';
            const origin = node ? node.getAttribute('data-origin') : '';
            this.removeImage(id, origin, node);
            return;
          }
          const img = event.target && event.target.closest ? event.target.closest('.image-preview img') : null;
          if (!img) {
            return;
          }
          const node = img.closest('.image-preview');
          const id = node ? node.getAttribute('data-image-id') : '';
          const name = (node && node.getAttribute('data-image-name')) || img.getAttribute('alt') || 'image';
          const url = img.getAttribute('src') || '';
          this.openFullscreen({ id, name, url });
        });
      }

      window.addEventListener('beforeunload', () => this.revokeAllObjectUrls());
      document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && this.fullscreen && this.fullscreen.classList.contains('is-open')) {
          this.closeFullscreen();
        }
      });

      if (this.form) {
        this.form.addEventListener('formdata', (event) => this.onFormData(event));
      }

      this.updateForContextChange();
      this.updateStatus();
      this.updateEmptyState();
    }

    isMarkdownContext() {
      const name = this.filenameInput ? this.filenameInput.value : '';
      // תואם לשרת: תמונות נשמרות רק לקבצים עם סיומת .md/.markdown
      return isMarkdownFilename(name);
    }

    updateForContextChange() {
      if (!this.widget) {
        return;
      }
      const isMarkdown = this.isMarkdownContext();
      this.widget.classList.toggle('is-hidden', !isMarkdown);

      if (!isMarkdown) {
        // אם יצאנו מ-Markdown: ננקה רק תמונות חדשות שהועלו עכשיו.
        // חשוב: לא לנקות deletedExistingIds כדי לא לאבד מחיקות אם המשתמש יחזור ל-.md לפני שמירה.
        this.resetNewImages();
        this.setError('');
      }

      this.updateStatus();
      this.updateEmptyState();
    }

    setError(message) {
      if (!this.errorEl) {
        return;
      }
      this.errorEl.textContent = message || '';
    }

    updateStatus() {
      if (!this.statusEl) {
        return;
      }
      if (!this.isMarkdownContext()) {
        this.statusEl.textContent = 'רכיב התמונות פעיל רק ל-Markdown';
        return;
      }
      const existingCount = this.countExistingVisible();
      const newCount = this.newImages.length;
      const total = existingCount + newCount;
      if (!total) {
        this.statusEl.textContent = 'לא נבחרו תמונות';
        return;
      }
      this.statusEl.textContent = `${total}/${this.MARKDOWN_IMAGE_LIMIT} תמונות`;
    }

    updateEmptyState() {
      if (!this.previews) {
        return;
      }
      const total = this.countExistingVisible() + this.newImages.length;
      this.previews.classList.toggle('is-empty', total === 0);
    }

    countExistingVisible() {
      if (!this.previews) {
        return 0;
      }
      const nodes = Array.from(this.previews.querySelectorAll('.image-preview[data-origin="existing"]'));
      return nodes.length;
    }

    handleFiles(fileList) {
      if (!fileList || !fileList.length) {
        return;
      }
      if (!this.isMarkdownContext()) {
        this.setError('כדי לצרף תמונות יש לבחור קובץ/שפה Markdown (.md)');
        return;
      }

      const incoming = Array.from(fileList);
      const errors = [];

      // מגבלת כמות כוללת: קיימות + חדשות
      const existingCount = this.countExistingVisible();
      let remainingSlots = Math.max(0, this.MARKDOWN_IMAGE_LIMIT - (existingCount + this.newImages.length));
      if (remainingSlots <= 0) {
        this.setError(`ניתן לצרף עד ${this.MARKDOWN_IMAGE_LIMIT} תמונות בלבד.`);
        return;
      }

      const toAdd = [];
      for (const file of incoming) {
        if (remainingSlots <= 0) {
          errors.push(`ניתן לצרף עד ${this.MARKDOWN_IMAGE_LIMIT} תמונות בלבד.`);
          break;
        }
        if (!this.MARKDOWN_ALLOWED_TYPES.includes(file.type)) {
          errors.push(`${file.name} אינו בפורמט תמונה נתמך.`);
          continue;
        }
        if (file.size > this.MARKDOWN_IMAGE_MAX_BYTES) {
          errors.push(`${file.name} גדול מדי (מקסימום ${this.humanFileSize(this.MARKDOWN_IMAGE_MAX_BYTES)}).`);
          continue;
        }
        const duplicate = this.newImages.some((item) => item.file && item.file.name === file.name && item.file.size === file.size);
        if (duplicate) {
          errors.push(`${file.name} כבר נבחרה.`);
          continue;
        }
        const id = `md-new-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
        const url = URL.createObjectURL(file);
        toAdd.push({ id, file, url });
        remainingSlots -= 1;
      }

      if (errors.length) {
        this.setError(errors.join(' '));
      } else {
        this.setError('');
      }

      if (!toAdd.length) {
        this.updateStatus();
        this.updateEmptyState();
        return;
      }

      this.newImages = [...this.newImages, ...toAdd];
      this.renderNewPreviews(toAdd);
      this.updateStatus();
      this.updateEmptyState();
    }

    renderNewPreviews(items) {
      if (!this.previews) {
        return;
      }
      items.forEach((item) => {
        const wrap = document.createElement('div');
        wrap.className = 'image-preview';
        wrap.dataset.imageId = item.id;
        wrap.dataset.origin = 'new';
        wrap.dataset.imageName = item.file ? item.file.name : 'image';

        const img = document.createElement('img');
        img.src = item.url;
        img.alt = item.file ? item.file.name : 'image';
        img.loading = 'lazy';

        const del = document.createElement('button');
        del.type = 'button';
        del.className = 'image-preview__delete';
        del.dataset.action = 'delete-image';
        del.setAttribute('aria-label', `מחק ${img.alt}`);
        del.textContent = '🗑️';

        wrap.appendChild(img);
        wrap.appendChild(del);
        this.previews.appendChild(wrap);
      });
    }

    ensureDeletedImagesInput() {
      if (!this.form) {
        return null;
      }
      let input = this.form.querySelector('input[name="deleted_images"]');
      if (!input) {
        input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'deleted_images';
        input.value = '[]';
        this.form.appendChild(input);
      }
      return input;
    }

    writeDeletedImagesInput() {
      const input = this.ensureDeletedImagesInput();
      if (!input) {
        return;
      }
      const arr = Array.from(this.deletedExistingIds);
      input.value = JSON.stringify(arr);
    }

    removeImage(id, origin, node) {
      const imageId = String(id || '').trim();
      if (!imageId) {
        return;
      }
      const src = String(origin || '').toLowerCase();

      if (src === 'existing') {
        this.deletedExistingIds.add(imageId);
        this.writeDeletedImagesInput();
        try {
          if (node) {
            node.remove();
          }
        } catch (_) {}
      } else {
        const idx = this.newImages.findIndex((x) => x.id === imageId);
        if (idx >= 0) {
          const removed = this.newImages.splice(idx, 1)[0];
          if (removed && removed.url) {
            try {
              URL.revokeObjectURL(removed.url);
            } catch (_) {}
          }
        }
        try {
          if (node) {
            node.remove();
          }
        } catch (_) {}
      }

      if (this.fullscreen && this.fullscreen.dataset.activeImageId === imageId) {
        this.closeFullscreen();
      }
      this.updateStatus();
      this.updateEmptyState();
      if (!this.newImages.length && this.countExistingVisible() === 0) {
        this.setError('');
      }
    }

    onFormData(event) {
      if (!event || !event.formData) {
        return;
      }

      if (!this.isMarkdownContext()) {
        try {
          event.formData.delete('md_images');
        } catch (_) {}
        // לא שולחים "מחיקות" אם לא במצב Markdown
        this.deletedExistingIds.clear();
        this.writeDeletedImagesInput();
        return;
      }

      try {
        event.formData.delete('md_images');
      } catch (_) {}

      this.newImages.forEach((item) => {
        if (!item || !item.file) {
          return;
        }
        try {
          event.formData.append('md_images', item.file, item.file.name);
        } catch (_) {
          try {
            event.formData.append('md_images', item.file);
          } catch (_) {}
        }
      });
    }

    ensureFullscreen() {
      if (this.fullscreen) {
        return;
      }
      const overlay = document.createElement('div');
      overlay.className = 'markdown-image-fullscreen';
      overlay.setAttribute('aria-hidden', 'true');
      overlay.innerHTML = `
        <button type="button" data-action="close-fullscreen">✕ סגירה</button>
        <img alt="תמונה במלוא הגודל">
        <div class="markdown-image-fullscreen-caption"></div>
      `;
      document.body.appendChild(overlay);

      this.fullscreen = overlay;
      this.fullscreenImg = overlay.querySelector('img');
      this.fullscreenCaption = overlay.querySelector('.markdown-image-fullscreen-caption');

      overlay.addEventListener('click', (e) => {
        if (e.target === overlay) {
          this.closeFullscreen();
        }
      });
      const closeBtn = overlay.querySelector('[data-action="close-fullscreen"]');
      if (closeBtn) {
        closeBtn.addEventListener('click', () => this.closeFullscreen());
      }
    }

    openFullscreen({ id, name, url }) {
      if (!url) {
        return;
      }
      this.ensureFullscreen();
      if (!this.fullscreen || !this.fullscreenImg) {
        return;
      }
      this.fullscreenImg.src = url;
      this.fullscreenImg.alt = name || 'image';
      if (this.fullscreenCaption) {
        this.fullscreenCaption.textContent = name || '';
      }
      this.fullscreen.dataset.activeImageId = id || '';
      this.fullscreen.classList.add('is-open');
      this.fullscreen.setAttribute('aria-hidden', 'false');
      this.prevBodyOverflow = document.body.style.overflow || '';
      document.body.style.overflow = 'hidden';
    }

    closeFullscreen() {
      if (!this.fullscreen || !this.fullscreenImg) {
        return;
      }
      this.fullscreen.classList.remove('is-open');
      this.fullscreen.setAttribute('aria-hidden', 'true');
      this.fullscreenImg.removeAttribute('src');
      this.fullscreenImg.removeAttribute('alt');
      if (this.fullscreenCaption) {
        this.fullscreenCaption.textContent = '';
      }
      try {
        delete this.fullscreen.dataset.activeImageId;
      } catch (_) {}
      document.body.style.overflow = this.prevBodyOverflow || '';
    }

    revokeAllObjectUrls() {
      this.newImages.forEach((item) => {
        if (item && item.url) {
          try {
            URL.revokeObjectURL(item.url);
          } catch (_) {}
        }
      });
    }

    resetNewImages() {
      this.revokeAllObjectUrls();
      this.newImages = [];
      if (this.previews) {
        // הסר רק פריטים חדשים
        Array.from(this.previews.querySelectorAll('.image-preview[data-origin="new"]')).forEach((node) => {
          try {
            node.remove();
          } catch (_) {}
        });
      }
      this.closeFullscreen();
    }

    humanFileSize(bytes) {
      const units = ['B', 'KB', 'MB'];
      let size = Number(bytes || 0);
      let unit = 0;
      while (size >= 1024 && unit < units.length - 1) {
        size /= 1024;
        unit += 1;
      }
      return `${Math.round(size * 10) / 10}${units[unit]}`;
    }
  }

  class FileFormManager {
    constructor(config) {
      this.config = config || {};
      this.mode = normalizeMode(this.config.mode);
      this.selectors = (this.config && this.config.selectors) || {};
      this.initialData = (this.config && this.config.initialData) || {};
      this.form = null;
      this.editorContainer = null;
      this.languageSelect = null;
      this.filenameInput = null;
      this.imageWidget = null;
      this.sourceUrlContainer = null;

      this.editorManager = null;
      this.sourceUrlManager = null;
      this.languageDetector = null;
      this.imageManager = null;
    }

    async init() {
      this.form = document.querySelector(this.selectors.form || '');
      this.editorContainer = document.querySelector(this.selectors.editorContainer || '');
      this.languageSelect = document.querySelector(this.selectors.languageSelect || '');
      this.filenameInput = document.querySelector(this.selectors.filenameInput || '');
      this.imageWidget = document.querySelector(this.selectors.imageUploadContainer || '');
      this.sourceUrlContainer = document.querySelector(this.selectors.sourceUrlContainer || '');

      this.editorManager = await waitFor(() => window.editorManager, { timeoutMs: 3500, intervalMs: 100 });

      // init editor
      if (this.editorContainer && this.editorManager && typeof this.editorManager.initEditor === 'function') {
        try {
          const value = this.getInitialEditorValue();
          const language = (this.languageSelect && this.languageSelect.value) || (this.initialData && this.initialData.language) || 'text';
          await this.editorManager.initEditor(this.editorContainer, { language, value, theme: 'dark' });
        } catch (e) {
          try {
            // eslint-disable-next-line no-console
            console.error('[file-form-manager] initEditor failed', e);
          } catch (_) {}
        }
      }

      this.sourceUrlManager = new SourceUrlManager({ container: this.sourceUrlContainer });
      this.sourceUrlManager.init();

      this.languageDetector = new LanguageDetector({
        filenameInput: this.filenameInput,
        languageSelect: this.languageSelect,
        editorManager: this.editorManager,
        onChange: () => {
          try {
            if (this.imageManager) {
              this.imageManager.updateForContextChange();
            }
          } catch (_) {}
        },
      });
      this.languageDetector.init();

      this.imageManager = new ImageManager({
        widget: this.imageWidget,
        form: this.form,
        filenameInput: this.filenameInput,
        languageSelect: this.languageSelect,
        mode: this.mode,
      });
      this.imageManager.init();

      // אם יש source_url קיים (בעיקר בעריכה/טיוטה) – נפתח אותו בתחילת הדרך
      try {
        const input = this.sourceUrlContainer
          ? this.sourceUrlContainer.querySelector('#sourceUrlInput, [data-role="source-url-input"]')
          : null;
        const hasValue = input && String(input.value || '').trim().length > 0;
        if (hasValue) {
          this.sourceUrlManager.setOpen(true, { focus: false, markTouched: false });
        }
      } catch (_) {}

      return this;
    }

    getInitialEditorValue() {
      try {
        if (!this.editorContainer) {
          return '';
        }
        const ta = this.editorContainer.querySelector('textarea[name="code"]');
        return (ta && ta.value) || '';
      } catch (_) {
        return '';
      }
    }
  }

  function autoInit() {
    const forms = Array.from(document.querySelectorAll('form[data-file-form-config]'));
    forms.forEach(async (form) => {
      const raw = form.getAttribute('data-file-form-config') || '';
      const config = safeJsonParse(raw);
      if (!config || !config.selectors || !config.selectors.form) {
        return;
      }
      // הגנה: ודא שהקונפיג מתאים לאותו form
      try {
        const resolved = document.querySelector(config.selectors.form);
        if (resolved !== form) {
          return;
        }
      } catch (_) {}

      const mgr = new FileFormManager(config);
      await mgr.init();
      try {
        form.__fileFormManager = mgr;
      } catch (_) {}
      // לנוחות: דף יחיד בדרך כלל
      try {
        window.fileFormManager = mgr;
      } catch (_) {}
    });
  }

  document.addEventListener('DOMContentLoaded', autoInit);
  window.FileFormManager = FileFormManager;
})();

