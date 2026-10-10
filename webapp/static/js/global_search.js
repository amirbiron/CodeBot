// Global search client-side logic
(function(){
  // מספר התוצאות שנשלח כשאין בחירה מפורשת. שלושה מקומות חייבים להסכים
  // על הערך הזה: ה-``selected`` שב-``webapp/templates/files.html``, הקבוע
  // הזה, וברירת המחדל של ``/api/search/global`` ב-``webapp/app.py``.
  // הם בשלוש שפות ואי אפשר לחלוק ביניהם קבוע, ולכן ההערה הזו היא הקישור.
  const DEFAULT_RESULTS_PER_PAGE = '10';

  // החיפוש בתיעוד (``POST /api/search/docs``, אדמין בלבד). השרת מגביל כל שלב משלו: שני החלקים
  // מול המסד (``SEARCH_DB_TIMEOUT_SECONDS`` כל אחד) והטמעת השאלה (``QUERY_EMBED_DEADLINE_SECONDS``),
  // ב-``services/docs_search_service.py``. הדדליין כאן ארוך מסכומם, כדי שיעצור רק בקשה שנתקעה
  // בדרך ולא חיפוש שהשרת עוד עונה עליו. ``tests/test_docs_search_files_page.py`` משווה ביניהם.
  const DOCS_SEARCH_DEADLINE_MS = 30000;

  let currentSearchQuery = '';
  let currentSearchPage = 1;
  let suggestionsTimeout = null;
  let shortcutCatalog = null;
  let shortcutCatalogPromise = null;
  let lastShortcutQuery = '';
  // מונה החיפושים: רק החיפוש האחרון מציג תוצאות ומחזיר את הכפתור למצבו. חיפוש בתיעוד נמשך
  // כמה שניות, ו-Enter, הצעה או מעבר עמוד מתחילים חיפוש חדש גם כשהכפתור מושבת. בלי המונה,
  // התשובה שמגיעה אחרונה הייתה נכתבת, גם כשהיא של החיפוש הישן.
  let searchSeq = 0;
  let searchButtonHtml = null;
  // הסעיפים של החיפוש האחרון בתיעוד. "העתק כמארקדאון" מפנה לכאן לפי מספר הכרטיס.
  let docsResults = [];
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
      copyToClipboard(text, copyBtn, 'לא הצלחתי להעתיק את הפקודה ללוח');
    });
    document.addEventListener('click', function(e){
      const copyBtn = e.target.closest('button[data-docs-copy]');
      if (!copyBtn) return;
      e.preventDefault();
      const result = docsResults[Number(copyBtn.getAttribute('data-docs-copy'))];
      if (result) copyToClipboard(result.markdown, copyBtn, 'לא הצלחתי להעתיק את הסעיף ללוח');
    });
    document.addEventListener('click', function(e){
      const expandBtn = e.target.closest('button[data-docs-expand]');
      if (!expandBtn) return;
      e.preventDefault();
      const card = expandBtn.closest('.search-result-card--docs');
      const clip = card ? card.querySelector('[data-docs-clip]') : null;
      if (!clip) return;
      const collapsed = clip.classList.toggle('is-collapsed');
      syncDocsExpandButton(expandBtn, clip);
      // הסעיף התקצר מעל הכפתור, והגלילה זזה רק בחלק מהקיצור, ולכן ראש הכרטיס נשאר הרבה מעל המסך. המסך
      // חוזר לראש הכרטיס — קובץ המקור והכותרת — גם כשהכרטיס המכווץ גבוה מהמסך, שם ``nearest`` היה מיישר
      // את התחתית וחותך את הראש. כרטיס שראשו על המסך לא זז. ``scrollIntoView`` גולל את מי שבאמת מחזיק את
      // הכרטיס, ובעמוד הזה זה ``body`` ולא החלון (Issue #3534, ``theming_and_css``).
      if (collapsed && card.getBoundingClientRect().top < 0) card.scrollIntoView({ block: 'start' });
    });
    const typeSelect = $('searchType');
    if (typeSelect) typeSelect.addEventListener('change', syncFiltersWithSearchType);
    syncFiltersWithSearchType();
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
      if (suggestions) { suggestions.hidden = true; suggestions.innerHTML = ''; }
      if (clearBtn) { clearBtn.style.display = 'none'; }

      // אפס סלקטים לערכי ברירת המחדל (תוכן / 10 / רלוונטיות).
      // ``DEFAULT_RESULTS_PER_PAGE`` חייב להישאר תואם ל-``selected`` שב-
      // ``files.html`` ולברירת המחדל של ``/api/search/global`` ב-``app.py``.
      try { const el = document.getElementById('searchType'); if (el) el.value = 'content'; } catch(_){}
      try { const el = document.getElementById('resultsPerPage'); if (el) el.value = DEFAULT_RESULTS_PER_PAGE; } catch(_){}
      try { const el = document.getElementById('sortOrder'); if (el) el.value = 'relevance'; } catch(_){}
      // שינוי ``value`` בקוד אינו שולח ``change``, ולכן הסינון מוחזר כאן במפורש.
      syncFiltersWithSearchType();

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
      docsResults = [];
      // חיפוש שעוד באוויר לא יכתוב תוצאות אחרי הניקוי. הוא גם לא יחזיר את הכפתור, ולכן כאן.
      searchSeq += 1;
      resetSearchButton();
    } catch (e) {
      // לא להשתיק, אבל לא להפיל את הדף
      try { console.warn('clearSearch failed', e); } catch(_) {}
    }
  }
  window.clearSearch = clearSearch;

  async function performSemanticSearch(query, options = {}){
    const { limit = 20, language = null } = options;
    const response = await fetch('/api/search/semantic', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ query, limit, language })
    });
    if (!response.ok) {
      throw new Error('Semantic search failed: ' + response.status);
    }
    return await response.json();
  }

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

    const seq = ++searchSeq;
    // הכפתור נשמר כשהוא במנוחה. חיפוש שמתחיל בזמן שאחר באוויר היה שומר את "מחפש..." ומחזיר אותו.
    if (searchButtonHtml === null) searchButtonHtml = btn.innerHTML;
    btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> מחפש...';
    try{
      // ענף משלו, בלי נפילה לחיפוש בקבצים: ``/api/search/global`` הופך סוג שאינו מכיר ל"תוכן",
      // ותוצאות של קבצים היו מוצגות כאילו הן תשובה על התיעוד.
      if (($('searchType')?.value || 'content') === 'docs') {
        await performDocsSearch(q, seq);
        return;
      }
      const payload = {
        query: q,
        search_type: ($('searchType')?.value || 'content'),
        page: page,
        limit: parseInt($('resultsPerPage')?.value || DEFAULT_RESULTS_PER_PAGE, 10),
        sort: ($('sortOrder')?.value || 'relevance'),
        filters: { languages: getSelectedLanguages() }
      };
      if (!payload.filters.languages || payload.filters.languages.length === 0) delete payload.filters;

      if (payload.search_type === 'semantic') {
        const perPage = Math.max(1, payload.limit || 20);
        const totalLimit = Math.min(50, perPage * page);
        const languages = (payload.filters && payload.filters.languages) ? payload.filters.languages : [];
        const language = (languages && languages.length) ? languages[0] : null;
        try {
          const semanticData = await performSemanticSearch(q, { limit: totalLimit, language });
          if (seq !== searchSeq) return;
          const semanticResults = Array.isArray(semanticData.results) ? semanticData.results : [];
          const startIdx = (page - 1) * perPage;
          const endIdx = startIdx + perPage;
          const mappedResults = semanticResults.map(r => ({
            file_id: r.file_id || '',
            file_name: r.file_name || '',
            language: r.language || '',
            tags: Array.isArray(r.tags) ? r.tags : [],
            score: typeof r.score === 'number' ? r.score : 0,
            snippet: r.preview || '',
            highlights: [],
            matches: Array.isArray(r.matches) ? r.matches : [],
            updated_at: r.updated_at || ''
          }));
          displayResults({
            success: true,
            query: q,
            total_results: semanticData.total || mappedResults.length,
            page: page,
            per_page: perPage,
            results: mappedResults.slice(startIdx, endIdx)
          });
          return;
        } catch (err) {
          if (seq !== searchSeq) return;
          console.error('Semantic search error:', err);
          // fallback to standard search
        }
      }

      const res = await fetch('/api/search/global', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify(payload)
      });
      if (seq !== searchSeq) return;

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
      if (seq !== searchSeq) return;
      if (res.ok && data && data.success){
        displayResults(data);
      } else {
        alert(data.error || 'אירעה שגיאה בחיפוש');
      }
    } catch (e){
      if (seq !== searchSeq) return;
      console.error('search error', e);
      alert('אירעה שגיאה בחיפוש');
    } finally {
      if (seq === searchSeq) { resetSearchButton(); hideSuggestions(); }
    }
  }
  window.performGlobalSearch = performGlobalSearch;

  function resetSearchButton(){
    const btn = $('searchBtn');
    if (!btn || searchButtonHtml === null) return;
    btn.disabled = false;
    btn.innerHTML = searchButtonHtml;
  }

  // החיפוש בתיעוד מחזיר את הסעיפים המובילים: בלי עמודים, בלי מיון ובלי סינון לפי שפה. הפקדים
  // האלה מושבתים כשהוא נבחר, כדי שבחירה בהם לא תיראה כאילו השפיעה.
  function syncFiltersWithSearchType(){
    const isDocs = ($('searchType')?.value === 'docs');
    ['resultsPerPage', 'sortOrder', 'languageFilterBtn'].forEach(function(id){
      const el = $(id);
      if (el) el.disabled = isDocs;
    });
  }

  // ── חיפוש בתיעוד ─────────────────────────────────────────────────────────

  // הסיבות של ``index_unavailable`` (``services/docs_search_service.py``). לכל אחת מהן יש מה לעשות
  // בעמוד הניהול של האינדקס, ולכן ההודעה מקשרת אליו.
  const DOCS_INDEX_PROBLEMS = {
    not_indexed: 'האינדקס של התיעוד עוד לא נבנה.',
    vector_search_unavailable: 'המסד לא תומך בחיפוש וקטורי.',
    vector_index_missing: 'האינדקס הווקטורי של התיעוד לא קיים ב-Atlas.',
    vector_index_error: 'האינדקס הווקטורי של התיעוד במצב שגיאה ב-Atlas.',
    vector_index_not_queryable: 'האינדקס הווקטורי של התיעוד עוד לא מוכן לחיפוש.',
    vector_index_dimensions_mismatch: 'המימד של האינדקס הווקטורי שונה מהמימד שהתיעוד הוטמע בו.'
  };

  const DOCS_SEARCH_PROBLEMS = {
    embedding_unavailable: 'אין מפתח ל-Gemini, ולכן אי אפשר להטמיע את השאלה.',
    embedding_timeout: 'הטמעת השאלה לקחה יותר מדי זמן. נסו שוב.',
    embedding_quota: 'Gemini הגביל את קצב הבקשות. נסו שוב בעוד רגע.',
    embedding_failed: 'הטמעת השאלה נכשלה.',
    search_timeout: 'החיפוש במסד לקח יותר מדי זמן. נסו שוב.',
    search_failed: 'החיפוש הווקטורי נכשל.',
    database_unavailable: 'המסד לא זמין כרגע.',
    empty_query: 'נא להזין שאלה.',
    query_too_long: 'השאלה ארוכה מדי.',
    admin_only: 'החיפוש בתיעוד זמין לאדמינים בלבד.',
    impersonation_active: 'החיפוש בתיעוד לא זמין בזמן התחזות.',
    timeout: 'החיפוש לא הסתיים בזמן. נסו שוב.',
    network: 'לא הצלחתי להגיע לשרת.'
  };

  function docsOption(){
    const select = $('searchType');
    return select ? select.querySelector('option[value="docs"]') : null;
  }

  async function performDocsSearch(query, seq){
    const option = docsOption();
    const searchUrl = option ? option.dataset.searchUrl : '';
    const adminUrl = option ? option.dataset.adminUrl : '';
    let res;
    let data = null;
    try {
      res = await fetch(searchUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ query }),
        signal: AbortSignal.timeout(DOCS_SEARCH_DEADLINE_MS)
      });
      if (res.status === 401 || res.redirected) {
        window.location.href = '/login?next=' + encodeURIComponent(location.pathname + location.search + location.hash);
        return;
      }
      if ((res.headers.get('content-type') || '').includes('application/json')) {
        data = await res.json();
      }
    } catch (err) {
      if (seq !== searchSeq) return;
      console.warn('docs search failed', err);
      // ``AbortSignal.timeout`` מבטל עם ``DOMException`` בשם ``TimeoutError``
      // (https://developer.mozilla.org/en-US/docs/Web/API/AbortSignal/timeout_static).
      showDocsProblem(err && err.name === 'TimeoutError' ? 'timeout' : 'network', '', adminUrl);
      return;
    }
    if (seq !== searchSeq) return;
    if (!res.ok || !data || data.ok !== true || !Array.isArray(data.results)) {
      const code = data && typeof data.error === 'string' ? data.error : 'http_' + res.status;
      const reason = data && typeof data.reason === 'string' ? data.reason : '';
      showDocsProblem(code, reason, adminUrl);
      return;
    }
    await renderDocsResults(query, data, adminUrl, seq);
  }

  function adminLinkHtml(adminUrl){
    return adminUrl ? ' <a href="' + escapeHtml(adminUrl) + '">לעמוד הניהול של האינדקס</a>' : '';
  }

  function showDocsProblem(code, reason, adminUrl){
    const container = $('searchResultsContainer');
    const info = $('searchInfo');
    const results = $('searchResults');
    const pagination = $('searchPagination');
    if (!container || !info || !results || !pagination) return;
    const indexProblem = code === 'index_unavailable';
    const message = indexProblem
      ? (DOCS_INDEX_PROBLEMS[reason] || 'האינדקס של התיעוד לא זמין.')
      : (DOCS_SEARCH_PROBLEMS[code] || 'החיפוש בתיעוד נכשל.');
    const detail = escapeHtml(indexProblem && reason ? reason : code);
    info.innerHTML = '<div class="alert alert-warning" data-testid="docs-search-problem">' +
      escapeHtml(message) + ' <code>' + detail + '</code>' + (indexProblem ? adminLinkHtml(adminUrl) : '') +
      '</div>';
    renderCommandShortcuts('');
    results.innerHTML = '';
    pagination.innerHTML = '';
    docsResults = [];
    container.style.display = 'block';
  }

  function docsStatusHtml(query, count, data, adminUrl){
    const commit = typeof data.source_commit === 'string' && data.source_commit
      ? 'האינדקס נכון לקומיט <code>' + escapeHtml(data.source_commit.slice(0, 7)) + '</code>.'
      : 'אין קומיט שהאינדקס הושלם עבורו.';
    const complete = data.index_complete === true;
    return '<div class="alert ' + (complete ? 'alert-info' : 'alert-warning') + '" data-testid="docs-search-status">' +
      'נמצאו <strong>' + count + '</strong> סעיפים בתיעוד עבור "' + escapeHtml(query) + '". ' + commit +
      (complete ? '' : ' האינדקס לא מעודכן לפריסה האחרונה של האתר, וייתכן שחסרים בו סעיפים.') +
      adminLinkHtml(adminUrl) +
      '</div>';
  }

  // כתובת הסעיף באתר נבנית בשרת מחלקים שנבדקו (``section_url`` ב-``services/docs_search_contract.py``).
  // כאן רק מוודאים שהיא https לפני שהיא נכנסת ל-``href``, בלי לסמוך על צורת המחרוזת.
  function docsSiteUrl(value){
    try {
      const url = new URL(String(value || ''));
      return url.protocol === 'https:' ? url.href : '';
    } catch (_) {
      // לא כתובת מלאה: הכרטיס יוצג בלי כפתור לאתר.
      return '';
    }
  }

  function renderDocsCard(r, index){
    const trail = Array.isArray(r.breadcrumb) ? r.breadcrumb.filter(function(part){ return typeof part === 'string'; }) : [];
    const path = trail.slice(0, -1);
    const title = typeof r.title === 'string' && r.title ? r.title : (trail[trail.length - 1] || '');
    const sourcePath = typeof r.source_path === 'string' ? r.source_path : '';
    const score = typeof r.score === 'number' && isFinite(r.score) ? r.score.toFixed(2) : '—';
    const siteUrl = docsSiteUrl(r.url);
    return (
      '<article class="search-result-card search-result-card--docs glass-card" role="listitem" dir="rtl" data-testid="docs-result">' +
        '<div class="result-card-header">' +
          '<div class="docs-result-heading">' +
            // נתיב נקרא משמאל לימין גם בכרטיס מימין לשמאל, כמו ``.file-path`` בדפדפן הריפו.
            (sourcePath ? '<div class="docs-result-file"><span dir="ltr">' + escapeHtml(sourcePath) + '</span></div>' : '') +
            (path.length ? '<div class="docs-result-trail">' + path.map(escapeHtml).join(' ← ') + '</div>' : '') +
            '<div class="docs-result-title">' + escapeHtml(title) + '</div>' +
          '</div>' +
          '<div class="meta-item docs-result-score">' + META_ICONS.score + '<span>ציון: ' + score + '</span></div>' +
        '</div>' +
        '<div class="markdown-preview-container docs-result-surface">' +
          '<div class="docs-result-clip is-collapsed" data-docs-clip>' +
            '<div class="markdown-preview-content markdown-body" data-docs-body="' + index + '"></div>' +
          '</div>' +
        '</div>' +
        '<div class="result-card-footer docs-result-actions">' +
          // התוכן והמצב נקבעים ב-``syncDocsExpandButton`` כשהכפתור נחשף.
          '<button type="button" class="btn btn-secondary btn-icon" data-docs-expand hidden></button>' +
          (siteUrl
            ? '<a class="btn btn-primary btn-icon" href="' + escapeHtml(siteUrl) + '" target="_blank" rel="noopener">' +
                '<i class="fas fa-book-open"></i><span class="btn-text"> פתח באתר התיעוד</span>' +
              '</a>'
            : '') +
          '<button type="button" class="btn btn-secondary btn-icon" data-docs-copy="' + index + '">' +
            '<i class="fas fa-copy"></i><span class="btn-text"> העתק כמארקדאון</span>' +
          '</button>' +
        '</div>' +
      '</article>'
    );
  }

  async function renderDocsResults(query, data, adminUrl, seq){
    const container = $('searchResultsContainer');
    const info = $('searchInfo');
    const results = $('searchResults');
    const pagination = $('searchPagination');
    if (!container || !info || !results || !pagination) return;

    docsResults = data.results.map(function(r){
      return Object.assign({}, r, { markdown: typeof r.markdown === 'string' ? r.markdown : '' });
    });
    info.innerHTML = docsStatusHtml(query, docsResults.length, data, adminUrl);
    renderCommandShortcuts('');
    pagination.innerHTML = '';
    if (!docsResults.length) {
      results.innerHTML = '<p class="text-muted">לא נמצאו סעיפים</p>';
      container.style.display = 'block';
      return;
    }
    results.innerHTML = '<div class="results-container"><div class="global-search-results stagger-feed" role="list">' +
      docsResults.map(renderDocsCard).join('') + '</div></div>';
    container.style.display = 'block';
    container.scrollIntoView({ behavior: 'smooth', block: 'start' });

    let renderer = null;
    try {
      if (typeof window.loadMarkdownDependencies !== 'function' || typeof window.MarkdownLiveRenderer === 'undefined') {
        throw new Error('markdown_scripts_missing');
      }
      await window.loadMarkdownDependencies();
      if (!window.MarkdownLiveRenderer.isSupported()) throw new Error('markdown_renderer_unsupported');
      renderer = window.MarkdownLiveRenderer;
    } catch (err) {
      console.warn('Markdown dependencies failed to load', err);
    }
    if (seq !== searchSeq) return;

    const bodies = results.querySelectorAll('[data-docs-body]');
    for (let i = 0; i < bodies.length; i += 1) {
      await renderDocsBody(bodies[i], docsResults[i].markdown, i, renderer);
      if (seq !== searchSeq) return;
    }
  }

  // סעיף אחד: אותו רינדור כמו בדפדפן הריפו (``renderWithAnchors`` ואז ``enhance``). כשהרינדור לא
  // זמין, מוצג המקור עם הודעה גלויה, ולא כרטיס ריק או רינדור חלקי שנראה תקין.
  async function renderDocsBody(body, markdown, index, renderer){
    if (renderer) {
      try {
        const rendered = await renderer.renderWithAnchors(markdown);
        body.innerHTML = rendered.html;
        scopeIds(body, 'docs-result-' + index + '-');
        await renderer.enhance(body, rendered.anchors);
      } catch (err) {
        console.warn('docs section render failed', err);
        renderer = null;
      }
    }
    if (!renderer) {
      body.innerHTML = '<p class="docs-result-render-note">התצוגה המעוצבת לא נטענה, ולכן מוצג המקור.</p>' +
        '<pre class="docs-result-source" dir="auto">' + escapeHtml(markdown) + '</pre>';
    }
    const clip = body.closest('[data-docs-clip]');
    const card = body.closest('.search-result-card--docs');
    const expandBtn = card ? card.querySelector('[data-docs-expand]') : null;
    if (!clip || !expandBtn) return;
    if (clip.scrollHeight > clip.clientHeight) {
      syncDocsExpandButton(expandBtn, clip);
      expandBtn.hidden = false;
    } else {
      clip.classList.remove('is-collapsed');
    }
  }

  // המצב של סעיף בכרטיס הוא ``is-collapsed`` על החלון שלו, וכל מה שכפתור ההרחבה מראה נגזר ממנו כאן,
  // ביחד: הטקסט, האייקון ו-``aria-expanded``. כשהלחיצה עדכנה רק את הטקסט ואת ``aria-expanded``, האייקון
  // נשאר "הרחב" גם אחרי שהסעיף נפתח — והאייקון הוא מה שרואים, כי ``.btn .btn-text`` ב-``base.html``
  // מסתיר את הטקסט כשהאייקונים נטענו. שני האייקונים מוגדרים ב-``all.min.css`` של Font Awesome 6.4.0,
  // שנטען ב-``base.html``.
  function syncDocsExpandButton(button, clip){
    const expanded = !clip.classList.contains('is-collapsed');
    button.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    button.innerHTML = expanded
      ? '<i class="fas fa-down-left-and-up-right-to-center"></i><span class="btn-text"> כווץ את הסעיף</span>'
      : '<i class="fas fa-up-right-and-down-left-from-center"></i><span class="btn-text"> הצג את כל הסעיף</span>';
  }

  // מזהים בתוך כרטיס מקבלים קידומת משלו. שני סעיפים עם אותה כותרת היו נותנים אותו ``id``, וקישור
  // ¶ או הערת שוליים בכרטיס אחד היו קופצים לכרטיס אחר. רץ לפני ``enhance``, כי התרשימים של
  // Mermaid נשענים על המזהים שהם יוצרים בעצמם.
  function scopeIds(root, prefix){
    root.querySelectorAll('[id]').forEach(function(el){ el.id = prefix + el.id; });
    root.querySelectorAll('a[href^="#"]').forEach(function(a){
      const target = a.getAttribute('href').slice(1);
      if (target && root.querySelector('[id="' + CSS.escape(prefix + target) + '"]')) {
        a.setAttribute('href', '#' + prefix + target);
      }
    });
  }

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
      const cardsHtml = data.results.map(renderCard).join('');
      results.innerHTML = '<div class="results-container"><div class="global-search-results stagger-feed" role="list">' + cardsHtml + '</div></div>';
    }

    renderPagination(pagination, data);
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
      // מחלקה של הפרויקט, לא של Bootstrap: הוובאפ אינו טוען את ה-CSS של
      // Bootstrap, ולכן list-group-item לא עיצב כאן דבר וההצעות נדבקו זו לזו.
      a.className = 'search-suggestion';
      a.setAttribute('role', 'option');
      a.textContent = String(s || '');
      a.addEventListener('click', function(e){
        e.preventDefault();
        input.value = String(s || '');
        hideSuggestions();
        performGlobalSearch();
      });
      box.appendChild(a);
    });
    box.hidden = false;
  }
  function hideSuggestions(){ const box = $('searchSuggestions'); if (box) box.hidden = true; }

  // אייקון השפה מגיע מ-window.langIcon (base.html) — מקור אמת אחד לכל האפליקציה
  function fileIcon(lang){
    const sizes = (window.LANG_ICON_DATA && window.LANG_ICON_DATA.sizes) || {};
    return window.langIcon ? window.langIcon(lang, sizes.search || 28) : '';
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
  // הכלל ב-``utils/size-format.js``. המימוש הקודם נעצר ב-MB, ולכן קובץ של
  // 2 ג'יגה הוצג כ-"2048 MB".
  function humanSize(bytes){ return window.SizeFormat.formatFileSize(bytes); }
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

  // משותף לכפתור ההעתקה של קיצורי הפקודות ול"העתק כמארקדאון" בכרטיסי התיעוד. רק ההודעה בכשל שונה.
  async function copyToClipboard(text, btn, failureMessage){
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
        alert(failureMessage);
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
