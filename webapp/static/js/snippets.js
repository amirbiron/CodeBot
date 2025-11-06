(function() {
  const qs = (sel) => document.querySelector(sel);
  const qsa = (sel) => Array.from(document.querySelectorAll(sel));

  function normalizeLanguage(lang) {
    const m = String(lang || '').trim().toLowerCase();
    if (!m) return '';
    const map = {
      js: 'javascript',
      node: 'javascript',
      ts: 'typescript',
      py: 'python',
      sh: 'bash',
      shell: 'bash',
      yml: 'yaml',
      md: 'markdown',
      golang: 'go',
      html5: 'html',
      css3: 'css',
    };
    return map[m] || m;
  }

  function applySyntaxHighlight(root) {
    try {
      if (!root || !window.hljs) return;
      const blocks = root.querySelectorAll('pre code');
      blocks.forEach(el => {
        try {
          if (el.classList.contains('hljs')) return;
          const hasLang = /\blanguage-/.test(el.className || '');
          if (hasLang && typeof window.hljs.highlightElement === 'function') {
            window.hljs.highlightElement(el);
          } else if (typeof window.hljs.highlightAuto === 'function') {
            const res = window.hljs.highlightAuto(el.textContent || '');
            el.innerHTML = res.value;
            el.classList.add('hljs');
          }
        } catch (_) {}
      });
    } catch (_) {}
  }

  async function fetchSnippets(params) {
    const url = new URL(window.location.origin + '/api/snippets');
    Object.entries(params || {}).forEach(([k, v]) => {
      if (v !== undefined && v !== null && String(v).trim() !== '') {
        url.searchParams.set(k, v);
      }
    });
    const res = await fetch(url.toString(), { credentials: 'same-origin' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data || data.ok === false) {
      throw new Error((data && data.error) || 'request_failed');
    }
    return data;
  }

  function codeBlock(code, lang) {
    const pre = document.createElement('pre');
    pre.className = 'code-block';
    const btn = document.createElement('button');
    btn.className = 'btn btn-secondary btn-sm';
    btn.style.float = 'left';
    btn.textContent = 'העתק';
    btn.addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(code || ''); btn.textContent = 'הועתק'; setTimeout(()=>btn.textContent='העתק', 1200);} catch(e){}
    });
    const codeEl = document.createElement('code');
    const normalized = normalizeLanguage(lang);
    if (normalized) {
      codeEl.className = 'language-' + normalized;
    }
    codeEl.textContent = code || '';
    codeEl.setAttribute('dir', 'ltr');
    pre.appendChild(btn);
    pre.appendChild(codeEl);
    return pre;
  }

  function render(items) {
    const root = qs('#results');
    root.innerHTML = '';
    if (!items || !items.length) {
      root.innerHTML = '<div class="glass-card">לא נמצאו סניפטים</div>';
      return;
    }
    for (const it of items) {
      const card = document.createElement('div');
      card.className = 'glass-card';
      const h = document.createElement('h3');
      h.textContent = it.title || 'ללא כותרת';
      const meta = document.createElement('div');
      meta.style.opacity = '.8';
      meta.style.marginBottom = '.5rem';
      meta.textContent = (it.language || '').toString();
      const p = document.createElement('p');
      p.textContent = it.description || '';
      card.appendChild(h);
      card.appendChild(meta);
      card.appendChild(p);
      card.appendChild(codeBlock(it.code || '', it.language));
      root.appendChild(card);
      // החלת הדגשת תחביר על הקוד בתוך הכרטיס
      applySyntaxHighlight(card);
    }
  }

  function renderPager(page, perPage, total, onGo) {
    const pager = qs('#pager');
    pager.innerHTML = '';
    const totalPages = total > 0 ? Math.ceil(total / perPage) : 1;
    if (totalPages <= 1) return;
    const makeBtn = (label, target, disabled) => {
      const b = document.createElement('button');
      b.className = 'btn btn-secondary';
      b.textContent = label;
      if (disabled) b.disabled = true;
      b.addEventListener('click', () => onGo(target));
      return b;
    };
    pager.appendChild(makeBtn('⬅️ קודם', Math.max(1, page - 1), page <= 1));
    pager.appendChild(makeBtn('הבא ➡️', Math.min(totalPages, page + 1), page >= totalPages));
  }

  async function run(page) {
    const q = qs('#q').value;
    const language = qs('#language').value;
    try {
      const data = await fetchSnippets({ q, language, page: page || 1, per_page: 30 });
      render(data.items || []);
      renderPager(data.page, data.per_page, data.total, (p) => run(p));
    } catch (e) {
      qs('#results').innerHTML = '<div class="glass-card">שגיאה בטעינה</div>';
    }
  }

  qs('#searchBtn').addEventListener('click', () => run(1));
  document.addEventListener('DOMContentLoaded', () => run(1));
})();
