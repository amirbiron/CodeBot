// Global search client-side logic
(function(){
  let currentSearchQuery = '';
  let currentSearchPage = 1;
  let suggestionsTimeout = null;
  let shortcutCatalog = null;
  let shortcutCatalogPromise = null;
  let lastShortcutQuery = '';

  function $(id){ return document.getElementById(id); }

  document.addEventListener('DOMContentLoaded', function(){
    const input = $('globalSearchInput');
    const btn = $('searchBtn');
    const clearBtn = document.getElementById('clearSearchInputBtn');
    if (!input || !btn) return;

    input.addEventListener('keypress', function(e){
      if (e.key === 'Enter') performGlobalSearch();
    });
    input.addEventListener('input', function(e){
      const q = (e.target.value || '').trim();
      try { if (clearBtn) clearBtn.style.display = q.length ? 'inline-flex' : 'none'; } catch(_) {}
      if (suggestionsTimeout) clearTimeout(suggestionsTimeout);
      if (q.length >= 2){
        suggestionsTimeout = setTimeout(function(){ fetchSuggestions(q); }, 250);
      } else {
        hideSuggestions();
      }
    });

    document.addEventListener('click', function(e){
      const inBox = e.target.closest('.search-box-wrapper');
      const inSug = e.target.closest('#searchSuggestions');
      if (!inBox && !inSug) hideSuggestions();
    });
    document.addEventListener('click', function(e){
      const copyBtn = e.target.closest('button[data-command-copy]');
      if (!copyBtn) return;
      e.preventDefault();
      const text = copyBtn.getAttribute('data-command-copy') || '';
      copyCommandShortcut(text, copyBtn);
    });
    // Initialize clear button visibility + behavior
    try { if (clearBtn) clearBtn.style.display = (input.value && input.value.trim().length) ? 'inline-flex' : 'none'; } catch(_) {}
    if (clearBtn) {
      clearBtn.addEventListener('click', function(){
        try { input.value = ''; } catch(_) {}
        try { input.focus(); } catch(_) {}
        try { hideSuggestions(); } catch(_) {}
        try { clearBtn.style.display = 'none'; } catch(_) {}
      });
    }
    ensureCommandCatalog().catch(()=>{});
  });

  // איפוס חיפוש גלובלי: שדות, פילטרים ותוצאות
  function clearSearch(){
    try {
      const input = document.getElementById('globalSearchInput');
      const suggestions = document.getElementById('searchSuggestions');
      const clearBtn = document.getElementById('clearSearchInputBtn');
      const container = document.getElementById('searchResultsContainer');
      const info = document.getElementById('searchInfo');
      const results = document.getElementById('searchResults');
      const pagination = document.getElementById('searchPagination');

      if (input) { input.value = ''; input.focus(); }
      if (suggestions) { suggestions.style.display = 'none'; suggestions.innerHTML = ''; }
      if (clearBtn) { clearBtn.style.display = 'none'; }

      // אפס סלקטים לערכי ברירת המחדל (תוכן / 20 / רלוונטיות)
      try { const el = document.getElementById('searchType'); if (el) el.value = 'content'; } catch(_){}
      try { const el = document.getElementById('resultsPerPage'); if (el) el.value = '20'; } catch(_){}
      try { const el = document.getElementById('sortOrder'); if (el) el.value = 'relevance'; } catch(_){}

      // נקה פילטרי שפה (UI חדש עם צ'קבוקסים + badge)
      try {
        const dd = document.getElementById('languageFilterDropdown');
        if (dd) {
          dd.querySelectorAll('input.lang-checkbox:checked').forEach(cb => { cb.checked = false; });
        }
        const countEl = document.getElementById('languageSelectedCount');
        if (countEl) { countEl.style.display = 'none'; countEl.textContent = '0'; }
      } catch(_){}

      // תאימות לאחור: select#filterLanguages
      try {
        const sel = document.getElementById('filterLanguages');
        if (sel) { Array.from(sel.options).forEach(o => { o.selected = false; }); }
      } catch(_){}

      // נקה תוצאות
      if (info) info.innerHTML = '';
      if (results) results.innerHTML = '';
      if (pagination) pagination.innerHTML = '';
      if (container) container.style.display = 'none';

      // עדכן מצב פנימי
      currentSearchQuery = '';
      currentSearchPage = 1;
    } catch (e) {
      // לא להשתיק, אבל לא להפיל את הדף
      try { console.warn('clearSearch failed', e); } catch(_) {}
    }
  }
  window.clearSearch = clearSearch;

  async function performGlobalSearch(page){
    page = page || 1;
    const input = $('globalSearchInput');
    const btn = $('searchBtn');
    if (!input || !btn) return;
    const q = (input.value || '').trim();
    if (!q){
      alert('נא להזין טקסט לחיפוש');
      return;
    }
    currentSearchQuery = q;
    currentSearchPage = page;

    const original = btn.innerHTML; btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> מחפש...';
    try{
      const payload = {
        query: q,
        search_type: ($('searchType')?.value || 'content'),
        page: page,
        limit: parseInt($('resultsPerPage')?.value || '20', 10),
        sort: ($('sortOrder')?.value || 'relevance'),
        filters: { languages: getSelectedLanguages() }
      };
      if (!payload.filters.languages || payload.filters.languages.length === 0) delete payload.filters;
      const res = await fetch('/api/search/global', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify(payload)
      });

      if (res.status === 401 || res.redirected) {
        window.location.href = '/login?next=' + encodeURIComponent(location.pathname + location.search + location.hash);
        return;
      }

      const contentType = res.headers.get('content-type') || '';
      if (!contentType.includes('application/json')) {
        const text = await res.text();
        if (/<html[\s\S]*<\/html>/i.test(text)) {
          window.location.href = '/login?next=' + encodeURIComponent(location.pathname + location.search + location.hash);
          return;
        }
        throw new Error('Unexpected response from server');
      }

      const data = await res.json();
      if (res.ok && data && data.success){
        displayResults(data);
      } else {
        alert(data.error || 'אירעה שגיאה בחיפוש');
      }
    } catch (e){
      console.error('search error', e);
      alert('אירעה שגיאה בחיפוש');
    } finally {
      btn.disabled = false; btn.innerHTML = original; hideSuggestions();
    }
  }
  window.performGlobalSearch = performGlobalSearch;

  function getSelectedLanguages(){
    // תמיכה ב־UI חדש: תפריט קטן שנפתח עם צ'קבוקסים
    const dropdown = document.getElementById('languageFilterDropdown');
    if (dropdown) {
      const checked = dropdown.querySelectorAll('input.lang-checkbox:checked');
      if (checked && checked.length) {
        return Array.from(checked).map(cb => cb.value);
      }
    }
    // תאימות לאחור: select#filterLanguages
    const sel = $('filterLanguages');
    if (!sel) return [];
    return Array.from(sel.selectedOptions || []).map(o => o.value);
  }

  function displayResults(data){
    const container = $('searchResultsContainer');
    const info = $('searchInfo');
    const results = $('searchResults');
    const pagination = $('searchPagination');
    if (!container || !info || !results || !pagination) return;

    info.innerHTML = '<div class="alert alert-info">נמצאו <strong>' + (data.total_results||0) + '</strong> תוצאות עבור "' + escapeHtml(data.query||'') + '" (מציג ' + (data.results?.length||0) + ')</div>';
    renderCommandShortcuts(data.query || currentSearchQuery || '');

    if (!data.results || data.results.length === 0){
      results.innerHTML = '<p class="text-muted">לא נמצאו תוצאות</p>';
    } else {
      results.innerHTML = data.results.map(renderCard).join('');
    }

    renderPagination(pagination, data);
    container.style.display = 'block';
    container.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function renderCard(r) {
    const highlighted = highlightSnippet(r.snippet, r.highlights);
    const icon = fileIcon(r.language || '');
    const badgeClass = languageBadgeClass(r.language);
    const badgeHtml = '<span class="global-search-lang-badge badge ' + badgeClass + '">' + escapeHtml(r.language || 'לא ידוע') + '</span>';

    // מבנה כרטיס מעודכן – ממורכז ורספונסיבי, עם טיפול בגלישת טקסט
    return (
      '<div class="search-result-card glass-card">' +
        '<div class="card-body">' +
          '<div class="result-header d-flex justify-content-between align-items-start">' +
            '<div class="result-content flex-grow-1" style="min-width: 0;">' +
              '<h6 class="result-title mb-2">' +
                icon + ' <a href="/file/' + r.file_id + '" target="_blank" class="text-truncate d-inline-block" style="max-width: calc(100% - 50px);">' +
                escapeHtml(r.file_name || '') +
                '</a>' +
                ' ' + badgeHtml +
              '</h6>' +
              '<div class="code-snippet-wrapper">' +
                '<div class="code-snippet bg-light p-3 rounded">' +
                  '<pre class="mb-0"><code>' + highlighted + '</code></pre>' +
                '</div>' +
              '</div>' +
            '</div>' +
            '<div class="result-meta text-right ml-3 flex-shrink-0">' +
              '<div class="small text-muted">' +
                '<div>ציון: ' + (r.score ?? 0).toFixed(2) + '</div>' +
                '<div>גודל: ' + humanSize(r.size || 0) + '</div>' +
                '<div>עדכון: ' + formatDate(r.updated_at) + '</div>' +
              '</div>' +
            '</div>' +
          '</div>' +
        '</div>' +
      '</div>'
    );
  }

  function highlightSnippet(text, ranges){
    text = String(text || '');
    if (!ranges || !ranges.length) return escapeHtml(text);
    const items = ranges.slice().sort((a,b)=> (a[0]-b[0]));
    let out = '', last = 0;
    for (const [s,e] of items){
      if (s < last) continue;
      out += escapeHtml(text.slice(last, s));
      out += '<mark class="bg-warning">' + escapeHtml(text.slice(s, e)) + '</mark>';
      last = e;
    }
    out += escapeHtml(text.slice(last));
    return out;
  }

  function renderPagination(container, data){
    const total = Math.max(0, parseInt(data.total_results || 0, 10));
    const per = Math.max(1, parseInt(data.per_page || 20, 10));
    const page = Math.max(1, parseInt(data.page || 1, 10));
    const pages = Math.max(1, Math.ceil(total / per));
    if (pages <= 1){ container.innerHTML=''; return; }
    let html = '<nav><ul class="pagination justify-content-center">';
    html += '<li class="page-item ' + (page===1?'disabled':'') + '"><a class="page-link" href="#" onclick="performGlobalSearch(' + (page-1) + ');return false;"><i class="fas fa-chevron-right"></i></a></li>';
    const start = Math.max(1, page-2), end = Math.min(pages, page+2);
    for (let i=start;i<=end;i++){
      html += '<li class="page-item ' + (i===page?'active':'') + '"><a class="page-link" href="#" onclick="performGlobalSearch(' + i + ');return false;">' + i + '</a></li>';
    }
    html += '<li class="page-item ' + (page===pages?'disabled':'') + '"><a class="page-link" href="#" onclick="performGlobalSearch(' + (page+1) + ');return false;"><i class="fas fa-chevron-left"></i></a></li>';
    html += '</ul></nav>';
    container.innerHTML = html;
  }

  async function fetchSuggestions(q){
    try{
      const res = await fetch('/api/search/suggestions?q=' + encodeURIComponent(q), {
        headers: { 'Accept': 'application/json' },
        credentials: 'same-origin'
      });

      if (res.status === 401 || res.redirected) {
        window.location.href = '/login?next=' + encodeURIComponent(location.pathname + location.search + location.hash);
        return;
      }

      const contentType = res.headers.get('content-type') || '';
      if (!contentType.includes('application/json')) { hideSuggestions(); return; }

      const data = await res.json();
      if (data && data.suggestions && data.suggestions.length){
        showSuggestions(data.suggestions);
      } else hideSuggestions();
    } catch (e){ hideSuggestions(); }
  }

  function showSuggestions(items){
    const box = $('searchSuggestions');
    const input = $('globalSearchInput');
    if (!box || !input) return;
    while (box.firstChild) box.removeChild(box.firstChild);
    items.forEach(function(s){
      const a = document.createElement('a');
      a.href = '#';
      a.className = 'list-group-item list-group-item-action';
      a.textContent = String(s || '');
      a.addEventListener('click', function(e){
        e.preventDefault();
        input.value = String(s || '');
        hideSuggestions();
        performGlobalSearch();
      });
      box.appendChild(a);
    });
    box.style.display = 'block';
  }
  function hideSuggestions(){ const box = $('searchSuggestions'); if (box) box.style.display='none'; }

  function fileIcon(lang){
    const m = String(lang||'').toLowerCase();
    const map = {
      python:'🐍',
      javascript:'📜',
      typescript:'📘',
      java:'☕',
      cpp:'⚙️',
      'c++':'⚙️',
      csharp:'💠',
      'c#':'💠',
      go:'💎',
      golang:'💎',
      html:'🌐',
      css:'🎨',
      sql:'🗄️',
      json:'📋',
      xml:'📄',
      markdown:'📝',
      md:'📝',
      ruby:'💎',
      php:'🐘',
      rust:'🦀',
      shell:'💻',
      bash:'💻'
    };
    return map[m] || '📄';
  }

  function languageBadgeClass(lang){
    const normalized = String(lang || '').trim().toLowerCase();
    if (!normalized) return 'lang-unknown';
    const map = {
      javascript: 'lang-js',
      js: 'lang-js',
      typescript: 'lang-ts',
      ts: 'lang-ts',
      python: 'lang-python',
      py: 'lang-python',
      react: 'lang-react',
      'react (jsx)': 'lang-react',
      jsx: 'lang-react',
      'react.js': 'lang-react',
      'react js': 'lang-react',
      vue: 'lang-vue',
      'vue.js': 'lang-vue',
      'vue js': 'lang-vue',
      html: 'lang-html',
      htm: 'lang-html',
      css: 'lang-css',
      java: 'lang-java',
      csharp: 'lang-csharp',
      'c#': 'lang-csharp',
      cpp: 'lang-cpp',
      'c++': 'lang-cpp',
      go: 'lang-go',
      golang: 'lang-go',
      php: 'lang-php',
      ruby: 'lang-ruby',
      rb: 'lang-ruby',
      rust: 'lang-rust',
      json: 'lang-json',
      sql: 'lang-sql',
      yaml: 'lang-yaml',
      yml: 'lang-yaml',
      markdown: 'lang-markdown',
      md: 'lang-markdown',
      shell: 'lang-shell',
      bash: 'lang-shell',
      sh: 'lang-shell'
    };
    return map[normalized] || 'lang-unknown';
  }
  function humanSize(bytes){ if (bytes < 1024) return bytes + ' B'; if (bytes < 1024*1024) return (bytes/1024).toFixed(1)+' KB'; return (bytes/(1024*1024)).toFixed(1)+' MB'; }
  function formatDate(s){ try{ const d=new Date(s); return d.toLocaleString('he-IL'); }catch(e){ return ''; } }
  function escapeHtml(t){ const d=document.createElement('div'); d.textContent=String(t||''); return d.innerHTML; }

  async function ensureCommandCatalog(){
    if (shortcutCatalog) return shortcutCatalog;
    if (shortcutCatalogPromise) return shortcutCatalogPromise;
    shortcutCatalogPromise = fetch('/static/data/commands.json', {
      headers: { 'Accept': 'application/json' },
      cache: 'no-store',
      credentials: 'same-origin'
    })
      .then(res => {
        if (!res.ok) throw new Error('failed to load commands catalog');
        return res.json();
      })
      .then(list => {
        if (!Array.isArray(list)) return [];
        shortcutCatalog = list
          .filter(item => item && item.name && item.type)
          .map(normalizeCommandRecord);
        return shortcutCatalog;
      })
      .catch(err => {
        try { console.warn('command shortcuts load failed', err); } catch(_) {}
        shortcutCatalog = [];
        return shortcutCatalog;
      });
    return shortcutCatalogPromise;
  }

  function normalizeCommandRecord(raw){
    const name = String(raw.name || '').trim();
    const type = String(raw.type || '').trim().toLowerCase();
    const description = String(raw.description || '').trim();
    const docLink = String(raw.doc_link || raw.docLink || '').trim();
    const args = Array.isArray(raw.arguments) ? raw.arguments.map(a => String(a || '').trim()).filter(Boolean) : [];
    return {
      name,
      type,
      description,
      doc_link: docLink,
      arguments: args,
      _nameLower: name.toLowerCase(),
      _descriptionLower: description.toLowerCase()
    };
  }

  function renderCommandShortcuts(query){
    const wrapper = $('commandShortcuts');
    if (!wrapper) return;
    const trimmed = String(query || '').trim();
    lastShortcutQuery = trimmed;
    if (!trimmed){
      wrapper.innerHTML = '';
      wrapper.style.display = 'none';
      return;
    }
    ensureCommandCatalog().then(() => {
      if (lastShortcutQuery !== trimmed) return;
      const matches = rankCommandShortcuts(trimmed);
      if (!matches.length){
        wrapper.innerHTML = '';
        wrapper.style.display = 'none';
        return;
      }
      wrapper.innerHTML = matches.map(renderShortcutCard).join('');
      wrapper.style.display = 'grid';
    }).catch(() => {
      if (lastShortcutQuery === trimmed){
        wrapper.innerHTML = '';
        wrapper.style.display = 'none';
      }
    });
  }

  function rankCommandShortcuts(query){
    if (!shortcutCatalog || !shortcutCatalog.length) return [];
    const lowered = String(query || '').trim().toLowerCase();
    if (!lowered) return [];
    const tokens = lowered.split(/\s+/).filter(Boolean);
    const hints = {
      preferChatOps: query.trim().startsWith('/'),
      preferCli: query.trim().startsWith('./') || query.includes('.sh'),
      preferPlaybook: lowered.includes('playbook') || lowered.includes('runbook')
    };
    return shortcutCatalog
      .map(cmd => ({ cmd, score: scoreCommandMatch(cmd, lowered, tokens, hints) }))
      .filter(item => item.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 3)
      .map(item => item.cmd);
  }

  function scoreCommandMatch(cmd, loweredQuery, tokens, hints){
    if (!loweredQuery) return 0;
    let score = 0;
    let matched = false;

    if (cmd._nameLower === loweredQuery) { score += 40; matched = true; }
    else if (cmd._nameLower.startsWith(loweredQuery)) { score += 25; matched = true; }
    else if (cmd._nameLower.includes(loweredQuery)) { score += 15; matched = true; }

    if (cmd._descriptionLower.includes(loweredQuery)) { score += 6; matched = true; }

    tokens.forEach(token => {
      if (!token) return;
      if (cmd._nameLower.includes(token)) { score += 6; matched = true; }
      else if (cmd._descriptionLower.includes(token)) { score += 2; matched = true; }
    });

    if (!matched) return 0;

    if (hints.preferChatOps && cmd.type === 'chatops') score += 4;
    if (hints.preferCli && cmd.type === 'cli') score += 4;
    if (hints.preferPlaybook && cmd.type === 'playbook') score += 4;
    if (cmd.type === 'chatops' && cmd.name.startsWith('/')) score += 2;
    if (cmd.type === 'cli' && cmd.name.startsWith('./')) score += 2;
    return score;
  }

  function renderShortcutCard(cmd){
    const meta = commandTypeMeta(cmd.type);
    return (
      '<div class="command-shortcut-card glass-card">' +
        '<div class="shortcut-topline">' +
          '<span class="shortcut-type badge badge-secondary">' + meta.icon + ' ' + meta.label + '</span>' +
        '</div>' +
        '<div class="shortcut-name">' + escapeHtml(cmd.name) + '</div>' +
        '<p class="shortcut-description">' + escapeHtml(cmd.description || '') + '</p>' +
        (cmd.arguments && cmd.arguments.length
          ? '<div class="shortcut-arguments"><span class="shortcut-arguments-label">ארגומנטים:</span> ' +
            cmd.arguments.map(a => '<code>' + escapeHtml(a) + '</code>').join(' ') +
            '</div>'
          : '') +
        '<div class="shortcut-actions">' +
          '<button type="button" class="btn btn-secondary btn-icon" data-command-copy="' + escapeHtml(cmd.name) + '">' +
            '<i class="fas fa-copy"></i><span class="btn-text"> העתק</span>' +
          '</button>' +
          (cmd.doc_link
            ? '<a class="btn btn-primary btn-icon" href="' + escapeHtml(cmd.doc_link) + '" target="_blank" rel="noopener">' +
                '<i class="fas fa-book-open"></i><span class="btn-text"> פתח תיעוד</span>' +
              '</a>'
            : '') +
        '</div>' +
      '</div>'
    );
  }

  function commandTypeMeta(type){
    const t = String(type || '').toLowerCase();
    const map = {
      chatops: { label: 'ChatOps', icon: '🤖' },
      cli: { label: 'CLI', icon: '💻' },
      playbook: { label: 'Playbook', icon: '📘' }
    };
    return map[t] || { label: 'Command', icon: '⚡' };
  }

  async function copyCommandShortcut(text, btn){
    const value = String(text || '').trim();
    if (!value) return;
    const previous = btn ? btn.innerHTML : '';
    try {
      if (navigator.clipboard && navigator.clipboard.writeText){
        await navigator.clipboard.writeText(value);
      } else {
        fallbackCopy(value);
      }
      showCopyFeedback(btn, previous);
    } catch (err){
      try {
        fallbackCopy(value);
        showCopyFeedback(btn, previous);
      } catch (copyErr){
        alert('לא הצלחתי להעתיק את הפקודה ללוח');
      }
    }
  }

  function fallbackCopy(text){
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    let success = false;
    try {
      success = document.execCommand('copy');
    } catch (err){
      throw err || new Error('document.execCommand(copy) failed');
    } finally {
      document.body.removeChild(textarea);
    }
    if (!success){
      throw new Error('document.execCommand(copy) returned false');
    }
  }

  function showCopyFeedback(btn, originalHtml){
    if (!btn) return;
    const previous = originalHtml || btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-check"></i><span class="btn-text"> הועתק</span>';
    setTimeout(function(){
      btn.disabled = false;
      btn.innerHTML = previous;
    }, 1600);
  }
})();
