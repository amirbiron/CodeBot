// Global search client-side logic
(function(){
  let currentSearchQuery = '';
  let currentSearchPage = 1;
  let suggestionsTimeout = null;

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
  });

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
                ' <span class="badge badge-secondary ml-2">' + escapeHtml(r.language || '') + '</span>' +
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
    const map = { python:'🐍', javascript:'📜', java:'☕', cpp:'⚙️', html:'🌐', css:'🎨', sql:'🗄️', json:'📋', xml:'📄', markdown:'📝' };
    return map[m] || '📄';
  }
  function humanSize(bytes){ if (bytes < 1024) return bytes + ' B'; if (bytes < 1024*1024) return (bytes/1024).toFixed(1)+' KB'; return (bytes/(1024*1024)).toFixed(1)+' MB'; }
  function formatDate(s){ try{ const d=new Date(s); return d.toLocaleString('he-IL'); }catch(e){ return ''; } }
  function escapeHtml(t){ const d=document.createElement('div'); d.textContent=String(t||''); return d.innerHTML; }
})();
