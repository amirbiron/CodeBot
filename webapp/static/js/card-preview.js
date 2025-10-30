/**
 * Expanded Card Preview – מציג 20 שורות קוד בתוך כרטיס בעמוד הקבצים
 */
(function () {
  'use strict';

  const expandedCards = new Set();

  function findOrCreateWrapper(cardElement) {
    let wrapper = cardElement.querySelector('.card-code-preview-wrapper');
    if (!wrapper) {
      wrapper = document.createElement('div');
      wrapper.className = 'card-code-preview-wrapper';
      cardElement.appendChild(wrapper);
    }
    return wrapper;
  }

  async function expandCard(fileId, cardElement) {
    if (!cardElement) return;

    // אם כבר פתוח – קפל
    if (expandedCards.has(fileId)) {
      collapseCard(fileId, cardElement);
      return;
    }

    // חסימת לחיצות כפולות
    if (cardElement.classList.contains('card-preview-expanding')) return;

    cardElement.classList.add('card-preview-expanding');
    const wrapper = findOrCreateWrapper(cardElement);
    wrapper.innerHTML = '\n      <div class="preview-spinner">\n        <i class="fas fa-circle-notch"></i>\n        <span>טוען תצוגה מקדימה...</span>\n      </div>\n    ';

    try {
      const res = await fetch(`/api/file/${encodeURIComponent(fileId)}/preview`, {
        headers: { 'Accept': 'application/json' },
        credentials: 'same-origin'
      });

      if (res.status === 401 || res.status === 302) {
        window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname + window.location.search + window.location.hash);
        return;
      }

      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data || data.ok === false) {
        const msg = (data && data.error) ? data.error : 'שגיאה בטעינת תצוגה מקדימה';
        wrapper.innerHTML = `<div class="preview-error"><i class="fas fa-exclamation-triangle"></i> ${msg}</div>`;
        return;
      }

      injectSyntaxCSS(data.syntax_css);
      wrapper.innerHTML = buildPreviewHTML(data, fileId);
      cardElement.classList.add('card-preview-expanded');
      expandedCards.add(fileId);
    } catch (err) {
      console.error('preview load failed', err);
      wrapper.innerHTML = '<div class="preview-error">אירעה שגיאה בעת הטעינה</div>';
    } finally {
      cardElement.classList.remove('card-preview-expanding');
    }
  }

  function collapseCard(fileId, cardElement) {
    if (!cardElement) return;
    const wrapper = cardElement.querySelector('.card-code-preview-wrapper');
    if (wrapper) wrapper.innerHTML = '';
    cardElement.classList.remove('card-preview-expanded');
    cardElement.classList.remove('card-preview-expanding');
    expandedCards.delete(fileId);
  }

  function buildPreviewHTML(data, fileId) {
    const moreIndicator = data.has_more
      ? `<p style="opacity:0.7; font-size:0.9rem; margin-top:1rem;">\n           <i class="fas fa-info-circle"></i> מציג ${data.preview_lines} מתוך ${data.total_lines} שורות\n         </p>`
      : '';

    return `
      <div class="card-code-preview">${data.highlighted_html}</div>
      ${moreIndicator}
      <div class="preview-actions">
        <button class="btn btn-primary btn-icon" onclick="window.location.href='/file/${fileId}'">
          <i class="fas fa-expand-alt"></i>
          <span class="btn-text">פתח דף מלא</span>
        </button>
        <button class="btn btn-secondary btn-icon" onclick="window.cardPreview.copyPreviewCode(this)">
          <i class="fas fa-copy"></i>
          <span class="btn-text">העתק</span>
        </button>
        <button class="btn btn-secondary btn-icon" onclick="window.cardPreview.collapse('${fileId}', this.closest('.file-card'))">
          <i class="fas fa-times"></i>
          <span class="btn-text">סגור</span>
        </button>
      </div>`;
  }

  function injectSyntaxCSS(css) {
    if (!css) return;
    if (document.getElementById('preview-syntax-css')) return;
    const styleEl = document.createElement('style');
    styleEl.id = 'preview-syntax-css';
    styleEl.textContent = css;
    document.head.appendChild(styleEl);
  }

  function copyPreviewCode(buttonEl) {
    const wrapper = buttonEl.closest('.card-code-preview-wrapper');
    const codeEl = wrapper && wrapper.querySelector('.card-code-preview pre');
    if (!codeEl) {
      alert('לא נמצא קוד להעתקה');
      return;
    }
    const code = codeEl.textContent || '';
    navigator.clipboard.writeText(code).then(() => {
      const orig = buttonEl.innerHTML;
      buttonEl.innerHTML = '<i class="fas fa-check"></i> הועתק!';
      buttonEl.classList.add('btn-success');
      setTimeout(() => {
        buttonEl.innerHTML = orig;
        buttonEl.classList.remove('btn-success');
      }, 1800);
    }).catch(() => alert('נכשלה העתקת הקוד'));
  }

  // חשיפת API
  window.cardPreview = {
    expand: expandCard,
    collapse: collapseCard,
    copyPreviewCode
  };

  // קיצור מקלדת אופציונלי: Ctrl/Cmd+E לכרטיס תחת העכבר
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'e') {
      const hovered = document.querySelector('.file-card:hover');
      if (hovered) {
        const id = hovered.getAttribute('data-file-id');
        if (id) expandCard(id, hovered);
      }
    }
  });

  console.log('✅ Card preview script loaded');
})();
