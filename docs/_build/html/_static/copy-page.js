(function () {
  const COPY_BUTTON_CLASS = 'doc-copy-page__button';
  const ACTIVE_CLASS = 'doc-copy-page__button--active';

  const buildControls = () => {
    const container = document.createElement('div');
    container.className = 'doc-copy-page';

    const button = document.createElement('button');
    button.type = 'button';
    button.className = COPY_BUTTON_CLASS;
    button.setAttribute('aria-live', 'polite');
    button.setAttribute('aria-label', 'העתק את תוכן הדף');
    button.textContent = 'העתק תוכן הדף';

    const status = document.createElement('span');
    status.className = 'doc-copy-page__status';
    status.setAttribute('aria-live', 'assertive');
    status.textContent = '';

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

    // Fallback ל- execCommand עבור דפדפנים ישנים
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

  const extractArticleText = (articleNode) => {
    const clone = articleNode.cloneNode(true);
    const uiElements = clone.querySelectorAll('.doc-copy-page');
    uiElements.forEach((el) => el.remove());
    return clone.innerText.trim();
  };

  const attachHandler = (article) => {
    const { container, button, status } = buildControls();
    article.insertBefore(container, article.firstChild);

    let resetHandle = null;

    const setStatus = (message, isError = false) => {
      status.textContent = message || '';
      status.classList.toggle('doc-copy-page__status--error', Boolean(isError));
    };

    const resetButton = () => {
      button.classList.remove(ACTIVE_CLASS);
      button.disabled = false;
      button.textContent = 'העתק תוכן הדף';
      button.removeAttribute('data-state');
      setStatus('');
      resetHandle = null;
    };

    button.addEventListener('click', async () => {
      if (button.getAttribute('data-state') === 'busy') {
        return;
      }

      try {
        button.setAttribute('data-state', 'busy');
        button.disabled = true;
        setStatus('מעתיק...');
        const text = extractArticleText(article);
        await copyTextToClipboard(text);
        button.classList.add(ACTIVE_CLASS);
        button.textContent = 'הועתק ✔';
        setStatus('הטקסט הועתק ללוח');
      } catch (err) {
        console.error('copy page failed', err);
        setStatus('שגיאה בהעתקה', true);
      } finally {
        if (resetHandle) {
          clearTimeout(resetHandle);
        }
        resetHandle = window.setTimeout(resetButton, 2500);
      }
    });
  };

  const init = () => {
    const article = document.querySelector('.wy-nav-content .document');
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
