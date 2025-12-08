(function () {
  const ARTICLE_SELECTOR = '.wy-nav-content .document';
  const ACTIVE_CLASS = 'doc-copy-page__button--active';
  const ERROR_CLASS = 'doc-copy-page__status--error';
  const RESET_DELAY_MS = 2800;
  const BUTTON_TEXT = {
    idle: 'העתק תוכן הדף',
    busy: 'מעתיק...',
    success: 'הועתק ✔',
  };
  const STATUS_TEXT = {
    success: 'הטקסט הועתק ללוח',
    error: 'שגיאה בהעתקה',
  };
  const CLEANUP_SELECTORS = [
    '.doc-copy-page',
    '.wy-breadcrumbs',
    '.rst-breadcrumbs-buttons',
    'script',
    'style',
  ];

  const createControls = () => {
    const container = document.createElement('div');
    container.className = 'doc-copy-page';

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'doc-copy-page__button';
    button.setAttribute('aria-live', 'polite');
    button.setAttribute('data-copy-state', 'idle');
    button.textContent = BUTTON_TEXT.idle;

    const status = document.createElement('span');
    status.className = 'doc-copy-page__status';
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'assertive');

    container.appendChild(button);
    container.appendChild(status);
    return { container, button, status };
  };

  const copyTextToClipboard = async (text) => {
    if (!text) {
      throw new Error('missing text');
    }

    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }

    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.top = '-1000px';
    textarea.style.opacity = '0';
    textarea.setAttribute('readonly', 'readonly');
    document.body.appendChild(textarea);
    textarea.select();

    const success = document.execCommand('copy');
    document.body.removeChild(textarea);
    if (!success) {
      throw new Error('execCommand failed');
    }
  };

  const normalizeText = (text) =>
    text.replace(/\u00a0/g, ' ').replace(/\n{3,}/g, '\n\n').trim();

  const extractArticleText = (articleNode) => {
    const clone = articleNode.cloneNode(true);
    CLEANUP_SELECTORS.forEach((selector) => {
      clone.querySelectorAll(selector).forEach((el) => el.remove());
    });
    const rawText = clone.innerText || clone.textContent || '';
    return normalizeText(rawText);
  };

  const setState = (button, statusEl, state, statusMessage, isError) => {
    button.dataset.copyState = state;
    button.textContent = BUTTON_TEXT[state];
    button.disabled = state === 'busy';
    button.classList.toggle(ACTIVE_CLASS, state === 'success');
    statusEl.textContent = statusMessage || '';
    statusEl.classList.toggle(ERROR_CLASS, Boolean(isError));
  };

  const attachHandler = (article) => {
    if (article.dataset.copyPageAttached === 'true') {
      return;
    }
    article.dataset.copyPageAttached = 'true';

    const { container, button, status } = createControls();
    article.insertBefore(container, article.firstChild);

    let resetHandle = null;
    const resetState = () => {
      setState(button, status, 'idle', '');
      resetHandle = null;
    };

    button.addEventListener('click', async () => {
      if (button.dataset.copyState === 'busy') {
        return;
      }

      try {
        setState(button, status, 'busy', 'מעתיק...');
        const text = extractArticleText(article);
        await copyTextToClipboard(text);
        setState(button, status, 'success', STATUS_TEXT.success);
      } catch (error) {
        console.error('copy page failed', error);
        setState(button, status, 'idle', STATUS_TEXT.error, true);
      } finally {
        if (resetHandle) {
          clearTimeout(resetHandle);
        }
        resetHandle = window.setTimeout(resetState, RESET_DELAY_MS);
      }
    });
  };

  const init = () => {
    const article = document.querySelector(ARTICLE_SELECTOR);
    if (!article) {
      return;
    }
    attachHandler(article);
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
