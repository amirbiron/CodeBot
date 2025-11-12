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

  function languageEmoji(lang){
    const m = normalizeLanguage(lang);
    const map = {
      python: '🐍', javascript: '📜', typescript: '📜', tsx: '📜', jsx: '📜',
      html: '🌐', css: '🎨', json: '📋', markdown: '📝', bash: '🐚', sh: '🐚', text: '📄', go: '🐹', java: '☕'
    };
    return map[m] || '📄';
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
          // Line numbers
          try {
            if (window.hljs && typeof window.hljs.lineNumbersBlock === 'function') {
              window.hljs.lineNumbersBlock(el, { singleLine: true });
            } else {
              // Fallback: עטיפה ידנית לשורות בטבלה בסגנון hljs-ln
              const html = el.innerHTML;
              const lines = String(html).split(/\n/);
              const table = document.createElement('table');
              table.className = 'hljs-ln';
              const tbody = document.createElement('tbody');
              table.appendChild(tbody);
              for (let i = 0; i < lines.length; i++) {
                const tr = document.createElement('tr');
                const tdNum = document.createElement('td');
                tdNum.className = 'hljs-ln-numbers';
                tdNum.textContent = String(i + 1);
                const tdCode = document.createElement('td');
                tdCode.className = 'hljs-ln-code';
                const span = document.createElement('span');
                span.className = 'hljs-ln-line';
                // שמירה על סימון התחביר שכבר הוזרק (innerHTML)
                span.innerHTML = lines[i] === '' ? ' ' : lines[i];
                tdCode.appendChild(span);
                tr.appendChild(tdNum);
                tr.appendChild(tdCode);
                tbody.appendChild(tr);
              }
              const pre = el.parentElement;
              if (pre && pre.tagName.toLowerCase() === 'pre') {
                // הסר את אלמנט ה-code והכנס טבלת שורות במקומו
                pre.removeChild(el);
                pre.appendChild(table);
              }
            }
          } catch(_) {}
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

      const details = document.createElement('details');
      const summary = document.createElement('summary');
      summary.className = 'snippet-summary';
      summary.style.cursor = 'pointer';
      summary.style.userSelect = 'none';

      const titleEl = document.createElement('h3');
      titleEl.className = 'snippet-title';
      titleEl.textContent = it.title || 'ללא כותרת';

      const meta = document.createElement('span');
      meta.className = 'snippet-meta';
      const lang = (it.language || '').toString();
      const emoji = languageEmoji(lang);
      const by = it.username ? (' · נוסף על ידי @' + String(it.username)) : '';
      meta.textContent = `${emoji} ${lang}${by}`;

      summary.appendChild(titleEl);
      summary.appendChild(meta);

      const body = document.createElement('div');
      body.style.marginTop = '.75rem';
      const p = document.createElement('p');
      p.textContent = it.description || '';
      const cb = codeBlock(it.code || '', it.language);
      body.appendChild(p);
      body.appendChild(cb);

      // Admin controls (Edit/Delete) when id available
      try {
        if (window.__isAdmin && it.id) {
          const actions = document.createElement('div');
          actions.style.display = 'flex';
          actions.style.gap = '.5rem';
          actions.style.marginTop = '.5rem';
          const edit = document.createElement('a'); edit.className='btn btn-secondary btn-sm'; edit.textContent='✏️ ערוך'; edit.href = '/admin/snippets/edit?id=' + encodeURIComponent(it.id);
          const del = document.createElement('button'); del.className='btn btn-secondary btn-sm'; del.textContent='🗑️ מחק';
          del.addEventListener('click', async ()=>{
            if (!confirm('למחוק את הסניפט?')) return;
            try{ const r = await fetch('/admin/snippets/delete?id='+encodeURIComponent(it.id), { method: 'POST' }); if (r.ok){ card.remove(); } }catch(_){ }
          });
          actions.appendChild(edit); actions.appendChild(del);
          body.appendChild(actions);
        }
      } catch(_) {}

      details.appendChild(summary);
      details.appendChild(body);
      card.appendChild(details);
      root.appendChild(card);

      // הדגש רק בעת פתיחה (וגם אם כבר פתוח)
      const ensureHighlight = () => applySyntaxHighlight(card);
      details.addEventListener('toggle', () => { if (details.open) ensureHighlight(); });
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

  async function loadLanguages() {
    try {
      const dl = document.getElementById('languagesList');
      if (!dl) return;
      // Avoid reloading if already populated
      if (dl.options && dl.options.length > 0) return;
      const res = await fetch('/api/snippets/languages', { credentials: 'same-origin' });
      const data = await res.json().catch(() => ({}));
      const langs = (data && Array.isArray(data.languages)) ? data.languages : [];
      dl.innerHTML = '';
      langs.forEach(l => {
        const opt = document.createElement('option');
        opt.value = l;
        dl.appendChild(opt);
      });
    } catch (_) {}
  }

  // --- Language picker overlay ---
  function openLangOverlay(langs){
    try{
      const overlay = document.getElementById('langOverlay');
      const list = document.getElementById('langList');
      if (!overlay || !list) return;
      list.innerHTML = '';
      (langs || []).forEach(l => {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'btn btn-secondary';
        b.textContent = l;
        b.addEventListener('click', () => {
          const inp = document.getElementById('language');
          if (inp) inp.value = l;
          closeLangOverlay();
          run(1);
        });
        list.appendChild(b);
      });
      overlay.style.display = 'flex';
    }catch(_){ }
  }

  function closeLangOverlay(){
    try{
      const overlay = document.getElementById('langOverlay');
      if (overlay) overlay.style.display = 'none';
    }catch(_){ }
  }

  async function showLangPicker(){
    try{
      // Fetch fresh list to ensure full coverage
      const res = await fetch('/api/snippets/languages', { credentials: 'same-origin' });
      const data = await res.json().catch(() => ({}));
      const langs = (data && Array.isArray(data.languages)) ? data.languages : [];
      openLangOverlay(langs);
    }catch(_){
      // Fallback to datalist if API fails
      try{
        const dl = document.getElementById('languagesList');
        const langs = Array.from((dl && dl.options) ? dl.options : []).map(o => o.value).filter(Boolean);
        openLangOverlay(langs);
      }catch(_){ }
    }
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
  document.addEventListener('DOMContentLoaded', () => { loadLanguages(); run(1); });
  const langInput = document.getElementById('language');
  if (langInput) {
    langInput.addEventListener('focus', loadLanguages, { once: true });
  }
  const pickBtn = document.getElementById('langPickerBtn');
  if (pickBtn) {
    pickBtn.addEventListener('click', showLangPicker);
  }
  const closeBtn = document.getElementById('langOverlayClose');
  if (closeBtn) { closeBtn.addEventListener('click', closeLangOverlay); }
  const backdrop = document.getElementById('langOverlayBackdrop');
  if (backdrop) { backdrop.addEventListener('click', closeLangOverlay); }
})();
