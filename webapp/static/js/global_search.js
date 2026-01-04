// Global search client-side logic
(function(){
  let currentSearchQuery = '';
  let currentSearchPage = 1;
  let suggestionsTimeout = null;
  let shortcutCatalog = null;
  let shortcutCatalogPromise = null;
  let lastShortcutQuery = '';
  const META_ICONS = {
    score: '<svg fill="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>',
    size: '<svg fill="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path d="M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z"/></svg>',
    time: '<svg fill="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm.5-13H11v6l5.25 3.15.75-1.23-4.5-2.67z"/></svg>'
  };

  const LANGUAGE_BADGE_MAP = {
    javascript: { className: 'lang-js', label: 'JavaScript' },
    js: { className: 'lang-js', label: 'JavaScript' },
    typescript: { className: 'lang-ts', label: 'TypeScript' },
    ts: { className: 'lang-ts', label: 'TypeScript' },
    python: { className: 'lang-python', label: 'Python' },
    py: { className: 'lang-python', label: 'Python' },
    react: { className: 'lang-react', label: 'React (JSX)' },
    'react (jsx)': { className: 'lang-react', label: 'React (JSX)' },
    jsx: { className: 'lang-react', label: 'React (JSX)' },
    'react.js': { className: 'lang-react', label: 'React (JSX)' },
    'react js': { className: 'lang-react', label: 'React (JSX)' },
    vue: { className: 'lang-vue', label: 'Vue' },
    'vue.js': { className: 'lang-vue', label: 'Vue' },
    'vue js': { className: 'lang-vue', label: 'Vue' },
    html: { className: 'lang-html', label: 'HTML' },
    htm: { className: 'lang-html', label: 'HTML' },
    css: { className: 'lang-css', label: 'CSS' },
    java: { className: 'lang-java', label: 'Java' },
    csharp: { className: 'lang-csharp', label: 'C#' },
    'c#': { className: 'lang-csharp', label: 'C#' },
    cpp: { className: 'lang-cpp', label: 'C++' },
    'c++': { className: 'lang-cpp', label: 'C++' },
    go: { className: 'lang-go', label: 'Go' },
    golang: { className: 'lang-go', label: 'Go' },
    php: { className: 'lang-php', label: 'PHP' },
    ruby: { className: 'lang-ruby', label: 'Ruby' },
    rb: { className: 'lang-ruby', label: 'Ruby' },
    rust: { className: 'lang-rust', label: 'Rust' },
    json: { className: 'lang-json', label: 'JSON' },
    sql: { className: 'lang-sql', label: 'SQL' },
    yaml: { className: 'lang-yaml', label: 'YAML' },
    yml: { className: 'lang-yaml', label: 'YAML' },
    markdown: { className: 'lang-markdown', label: 'Markdown' },
    md: { className: 'lang-markdown', label: 'Markdown' },
    shell: { className: 'lang-shell', label: 'Shell' },
    bash: { className: 'lang-shell', label: 'Shell' },
    sh: { className: 'lang-shell', label: 'Shell' },
    text: { className: 'lang-unknown', label: 'Text' }
  };

  const MARKDOWN_EXTENSIONS = new Set(['md','markdown']);

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
      const searchType = ($('searchType')?.value || 'content');
      const limit = parseInt($('resultsPerPage')?.value || '20', 10);

      // במימוש החדש (/api/search) יש סינון language יחיד בלבד.
      // נשמור תאימות ל-UI הקיים: אם נבחרו כמה שפות, ניקח את הראשונה.
      const langs = getSelectedLanguages();
      const language = (langs && langs.length) ? String(langs[0] || '') : '';

      const url = new URL('/api/search', window.location.origin);
      url.searchParams.set('q', q);
      url.searchParams.set('type', searchType);
      url.searchParams.set('limit', String(limit));
      if (language) url.searchParams.set('language', language);

      const res = await fetch(url.toString(), {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
        credentials: 'same-origin'
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
      // תאימות: חלק מהמסכים/גרסאות מחזירים success/results במקום ok/items
      const normalizedItems = (data && Array.isArray(data.items))
        ? data.items
        : ((data && Array.isArray(data.results)) ? data.results : []);
      const isOk = !!(data && (data.ok === true || data.success === true));

      if (res.ok && (isOk || normalizedItems.length)){
        // נורמליזציה כדי ש-displayResults תמיד יעבוד מול data.items
        if (data && !Array.isArray(data.items)) data.items = normalizedItems;
        displayResults(data || { items: normalizedItems, ok: isOk }, q, limit);
      } else {
        alert((data && data.error) || 'אירעה שגיאה בחיפוש');
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

  function displayResults(data, query, perPage){
    const container = $('searchResultsContainer');
    const info = $('searchInfo');
    const results = $('searchResults');
    const pagination = $('searchPagination');
    if (!container || !info || !results || !pagination) return;

    const itemsRaw = (data && Array.isArray(data.items)) ? data.items : [];
    const total = itemsRaw.length;
    const q = String(query || currentSearchQuery || '');
    info.innerHTML = '<div class="alert alert-info">נמצאו <strong>' + total + '</strong> תוצאות עבור "' + escapeHtml(q) + '"</div>';
    renderCommandShortcuts(q);

    if (!itemsRaw.length){
      results.innerHTML = '<p class="text-muted">לא נמצאו תוצאות</p>';
    } else {
      // התאמה למבנה הקיים של renderCard
      const mapped = itemsRaw.map(function(it){
        it = it || {};
        const rawHighlights = it.highlights || it.highlight_ranges || it.highlightRanges || it.highlight_ranges_list || [];
        const highlights = normalizeHighlights(rawHighlights);
        const snippetText = normalizeSnippet(
          it.snippet_preview,
          it.snippet,
          it.preview,
          it.content
        );
        return {
          file_id: it.file_id || it.id || it._id || '',
          file_name: it.file_name || it.name || '',
          language: it.programming_language || it.language || '',
          tags: it.tags || [],
          score: (typeof it.score === 'number') ? it.score : 0,
          // חשוב: גם אם highlights ריק (כמו בחיפוש סמנטי) עדיין מציגים snippet_preview
          snippet: snippetText,
          highlights: highlights,
          updated_at: it.updated_at || null,
          size: it.file_size || it.size || 0,
          lines_count: it.lines_count || it.lines || 0
        };
      });
      const cardsHtml = mapped.map(function(r){
        try {
          return renderCard(r);
        } catch (e) {
          // לא להפיל את כל התוצאות בגלל פריט בעייתי
          try { console.warn('renderCard failed', e, r); } catch(_) {}
          const safeName = escapeHtml((r && r.file_name) || 'קובץ');
          const safeSnippet = escapeHtml((r && r.snippet) || '');
          return (
            '<article class="search-result-card glass-card" role="listitem">' +
              '<div class="result-card-header"><div class="file-info"><span class="file-icon" aria-hidden="true">📄</span>' +
                '<span class="file-name">' + safeName + '</span>' +
              '</div></div>' +
              (safeSnippet ? ('<div class="result-card-snippet"><pre class="mb-0" dir="ltr"><code>' + safeSnippet + '</code></pre></div>') : '') +
            '</article>'
          );
        }
      }).join('');
      results.innerHTML = '<div class="results-container"><div class="global-search-results stagger-feed" role="list">' + cardsHtml + '</div></div>';
    }

    // לפי המדריך: אין דפדוף כרגע ב-API החדש. נשאיר ריק.
    pagination.innerHTML = '';
    container.style.display = 'block';
    container.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function renderCard(r) {
    const highlighted = highlightSnippet(r.snippet, r.highlights);
    const icon = fileIcon(r.language || '');
    const badgeMeta = languageBadgeMeta(r.language, r.file_name);
    const badgeHtml = '<span class="global-search-lang-badge badge ' + badgeMeta.className + '" title="שפת הקובץ">' + escapeHtml(badgeMeta.label.toUpperCase()) + '</span>';
    const scoreValue = typeof r.score === 'number' ? r.score.toFixed(2) : '—';
    const sizeValue = humanSize(r.size || 0);
    const updatedValue = formatDate(r.updated_at) || '—';

    return (
      '<article class="search-result-card glass-card" role="listitem">' +
        '<div class="result-card-header">' +
          '<div class="file-info">' +
            '<span class="file-icon" aria-hidden="true">' + icon + '</span>' +
            '<a href="/file/' + r.file_id + '" target="_blank" class="file-name" title="' + escapeHtml(r.file_name || '') + '">' +
              escapeHtml(r.file_name || '') +
            '</a>' +
          '</div>' +
          badgeHtml +
        '</div>' +
        '<div class="result-card-snippet">' +
          '<pre class="mb-0" dir="ltr"><code>' + highlighted + '</code></pre>' +
        '</div>' +
        '<div class="result-card-footer">' +
          '<div class="meta-item">' + META_ICONS.score + '<span>ציון: ' + scoreValue + '</span></div>' +
          '<div class="meta-item">' + META_ICONS.size + '<span>' + escapeHtml(sizeValue) + '</span></div>' +
          '<div class="meta-item">' + META_ICONS.time + '<span>' + escapeHtml(updatedValue) + '</span></div>' +
        '</div>' +
      '</article>'
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
      out += '<span class="global-search-highlight">' + escapeHtml(text.slice(s, e)) + '</span>';
      last = e;
    }
    out += escapeHtml(text.slice(last));
    return out;
  }

  function normalizeSnippet(){
    // מקבל רשימת מועמדים (snippet_preview וכו') ומחזיר טקסט לא ריק
    for (let i = 0; i < arguments.length; i++){
      const v = arguments[i];
      if (v === null || v === undefined) continue;
      const s = String(v);
      if (s.trim().length) return s;
    }
    // fallback: לא להשאיר כרטיס ריק
    return '(אין תצוגה מקדימה)';
  }

  function normalizeHighlights(raw){
    // חיפוש סמנטי לרוב מחזיר [], ועדיין צריך להציג את snippet_preview.
    // בנוסף, ננקה פורמטים לא צפויים כדי שלא יפיל את highlightSnippet.
    if (!raw) return [];
    if (!Array.isArray(raw)) return [];
    const out = [];
    for (const item of raw){
      if (!item) continue;
      // פורמט צפוי: [start, end]
      if (Array.isArray(item) && item.length >= 2){
        const s = Number(item[0]);
        const e = Number(item[1]);
        if (Number.isFinite(s) && Number.isFinite(e) && e > s && s >= 0){
          out.push([s, e]);
        }
        continue;
      }
      // פורמט אפשרי: {start, end}
      if (typeof item === 'object' && item.start !== undefined && item.end !== undefined){
        const s = Number(item.start);
        const e = Number(item.end);
        if (Number.isFinite(s) && Number.isFinite(e) && e > s && s >= 0){
          out.push([s, e]);
        }
      }
    }
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
      const res = await fetch('/api/search/suggest?q=' + encodeURIComponent(q), {
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
      yaml:'📘',
      yml:'📘',
      shell:'💻',
      bash:'💻'
    };
    return map[m] || '📄';
  }

  function languageBadgeMeta(lang, fileName){
    const normalized = String(lang || '').trim().toLowerCase();
    const extension = getFileExtension(fileName);
    if (normalized === 'text' && MARKDOWN_EXTENSIONS.has(extension)) {
      return LANGUAGE_BADGE_MAP.markdown;
    }
    const direct = normalized ? LANGUAGE_BADGE_MAP[normalized] : null;
    if (direct) return direct;
    if (extension && LANGUAGE_BADGE_MAP[extension]) {
      return LANGUAGE_BADGE_MAP[extension];
    }
    return { className: 'lang-unknown', label: lang ? String(lang) : 'לא ידוע' };
  }

  function getFileExtension(name){
    if (!name || typeof name !== 'string') return '';
    const lastDot = name.lastIndexOf('.');
    if (lastDot === -1) return '';
    return name.slice(lastDot + 1).toLowerCase();
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
