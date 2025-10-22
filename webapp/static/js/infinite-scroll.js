// Infinite scroll + simple virtualization for files list
(function(){
  const CONFIG = {
    pageParam: 'page',
    cursorParam: 'cursor',
    limit: 20,
    thresholdPx: 800, // start fetching next page when within 800px of bottom
    virtualizationBuffer: 8, // render +/- N items around viewport
  };

  let nextPageUrl = null;
  let loading = false;
  let reachedEnd = false;
  let totalCount = 0;

  const state = {
    items: [], // DOM elements of .file-card
    heights: [], // cached heights
    container: null,
    sentinel: null,
    paginationEl: null,
  };

  function init(){
    state.container = document.getElementById('filesGrid');
    if (!state.container) return;
    state.paginationEl = document.getElementById('paginationControls');

    totalCount = parseInt(state.container.getAttribute('data-total-count') || '0', 10) || 0;

    // Determine next page URL from pagination controls or query params
    nextPageUrl = computeNextPageFromDom() || computeNextPageFromQuery();

    // Hide legacy pagination if infinite scroll will be active
    if (nextPageUrl) hidePagination();

    // Collect initial items
    collectItems();

    // Setup scroll handler (throttled)
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll, { passive: true });
    onScroll();
  }

  function computeNextPageFromDom(){
    const nextLink = state.paginationEl?.querySelector('a[href*="cursor="], a[href*="page="]');
    return nextLink ? nextLink.getAttribute('href') : null;
  }

  function computeNextPageFromQuery(){
    const url = new URL(location.href);
    const page = parseInt(url.searchParams.get('page') || '1', 10);
    const per = 20;
    if ((page * per) >= totalCount) return null;
    const np = page + 1;
    url.searchParams.set('page', String(np));
    url.hash = '#bottom';
    return url.pathname + url.search + url.hash;
  }

  function hidePagination(){
    if (state.paginationEl) state.paginationEl.style.display = 'none';
  }

  function collectItems(){
    state.items = Array.from(state.container.querySelectorAll('.file-card'));
    state.heights = state.items.map(el => el.getBoundingClientRect().height || 180);
  }

  function onScroll(){
    if (!state.container) return;
    maybeFetchMore();
    virtualize();
  }

  function bottomDistance(){
    const scrollY = window.scrollY || window.pageYOffset;
    const vh = window.innerHeight || document.documentElement.clientHeight;
    const docH = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
    return docH - (scrollY + vh);
  }

  async function maybeFetchMore(){
    if (loading || reachedEnd || !nextPageUrl) return;
    if (bottomDistance() > CONFIG.thresholdPx) return;
    loading = true;
    try {
      const url = new URL(nextPageUrl, location.origin);
      // Fetch full HTML of the next page and extract the file cards
      const res = await fetch(url.toString(), { credentials: 'same-origin' });
      if (res.status === 401 || res.redirected) {
        location.href = '/login?next=' + encodeURIComponent(location.pathname + location.search + location.hash);
        return;
      }
      const html = await res.text();
      const dom = new DOMParser().parseFromString(html, 'text/html');
      const grid = dom.getElementById('filesGrid');
      const newCards = grid ? Array.from(grid.querySelectorAll('.file-card')) : [];
      const newTotal = grid ? parseInt(grid.getAttribute('data-total-count') || '0', 10) : totalCount;
      totalCount = newTotal || totalCount;

      if (newCards.length === 0) {
        reachedEnd = true; nextPageUrl = null; return;
      }

      // Append and rebind (ensure selection system sees new checkboxes)
      const frag = document.createDocumentFragment();
      newCards.forEach(card => {
        frag.appendChild(card);
      });
      state.container.appendChild(frag);
      try { window.multiSelect?.restoreSelection?.(); } catch(_){ }

      // Update count text
      updateResultsCount();

      // Re-collect items and ensure multi-select listeners will work via delegation
      collectItems();

      // Compute next page from that DOM's pagination
      const theirPagination = dom.getElementById('paginationControls');
      const nextLink = theirPagination?.querySelector('a[href*="page="], a[href*="cursor="]');
      nextPageUrl = nextLink ? nextLink.getAttribute('href') : null;
      if (!nextPageUrl) reachedEnd = true;
    } catch (e) {
      console.error('infinite-scroll fetch error', e);
      reachedEnd = true;
    } finally {
      loading = false;
    }
  }

  function updateResultsCount(){
    try {
      const countEl = document.getElementById('resultsCount');
      if (!countEl) return;
      const shown = state.container.querySelectorAll('.file-card').length;
      countEl.textContent = `מציג ${shown} מתוך ${totalCount} קבצים`;
    } catch (_){ }
  }

  // Simple virtualization: hide far-away cards to keep DOM light
  function virtualize(){
    const viewportTop = window.scrollY || window.pageYOffset;
    const viewportBottom = viewportTop + (window.innerHeight || document.documentElement.clientHeight);

    const items = state.items;
    for (let i = 0; i < items.length; i++){
      const el = items[i];
      const rect = el.getBoundingClientRect();
      const top = rect.top + window.scrollY;
      const bottom = top + rect.height;
      const buffer = rect.height * CONFIG.virtualizationBuffer;
      const visible = (bottom >= viewportTop - buffer) && (top <= viewportBottom + buffer);
      el.style.visibility = visible ? 'visible' : 'hidden';
      el.style.pointerEvents = visible ? '' : 'none';
    }
  }

  document.addEventListener('DOMContentLoaded', init);
})();
