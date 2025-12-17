(function(){
  const api = {
    async listCollections() {
      const r = await fetch('/api/collections');
      return r.json();
    },
    async createCollection(payload){
      const r = await fetch('/api/collections', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload||{})});
      return r.json();
    },
    async getCollection(id){
      const r = await fetch(`/api/collections/${encodeURIComponent(id)}`);
      return r.json();
    },
    async updateCollection(id, payload){
      const r = await fetch(`/api/collections/${encodeURIComponent(id)}`, {method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload||{})});
      return r.json();
    },
    async deleteCollection(id){
      const r = await fetch(`/api/collections/${encodeURIComponent(id)}`, {method:'DELETE'});
      return r.json();
    },
    async getItems(id, page=1, perPage=20){
      const r = await fetch(`/api/collections/${encodeURIComponent(id)}/items?page=${page}&per_page=${perPage}&include_computed=true`);
      return r.json();
    },
    async addItems(id, items){
      const r = await fetch(`/api/collections/${encodeURIComponent(id)}/items`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({items})});
      return r.json();
    },
    async removeItems(id, items){
      const r = await fetch(`/api/collections/${encodeURIComponent(id)}/items`, {method:'DELETE', headers:{'Content-Type':'application/json'}, body: JSON.stringify({items})});
      return r.json();
    },
    async reorder(id, order){
      const r = await fetch(`/api/collections/${encodeURIComponent(id)}/reorder`, {method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify({order})});
      return r.json();
    },
    async updateShare(id, payload){
      const r = await fetch(`/api/collections/${encodeURIComponent(id)}/share`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload||{})});
      return r.json();
    },
    async updateWorkspaceState(itemId, state){
      const r = await fetch(`/api/workspace/items/${encodeURIComponent(itemId)}/state`, {
        method: 'PATCH',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ state }),
      });
      let data = null;
      try {
        data = await r.json();
      } catch (_err) {
        data = null;
      }
      if (!r.ok || !data || data.ok === false) {
        const err = (data && data.error) || 'workspace_state_update_failed';
        const error = new Error(err);
        error.code = err;
        throw error;
      }
      return data;
    },
  };

  const ALLOWED_ICONS = [
    "📂","📘","🎨","🧩","🐛","⚙️","📝","🧪","💡","⭐","🔖","🚀",
    "🖥️","💼","🖱️","⌨️","📱","💻","🖨️","📊","📈","📉","🔧","🛠️"
  ];

  const resolvedFileIdCache = new Map();
  const RECYCLE_BIN_ALERT = 'הקובץ הועבר לסל מיחזור, ניתן לשחזר דרך סל מיחזור דרך הבוט';
  let currentCollectionId = '';
  let initialCollectionIdConsumed = false;
  const WORKSPACE_STATE_META = {
    todo: { label: 'לטיפול', description: 'משימות שטרם התחלת', shortcut: 'Shift+1' },
    in_progress: { label: 'בתהליך', description: 'עבודה בתהליך', shortcut: 'Shift+2' },
    done: { label: 'הושלם', description: 'סיימת לטפל', shortcut: 'Shift+3' },
  };
  const WORKSPACE_STATE_ORDER = Object.keys(WORKSPACE_STATE_META);
  let workspaceBoardCtx = null;
  let workspaceActiveCard = null;
  let activeDragContext = null;
  let workspaceDragPointer = null;
  let workspacePointerCleanup = null;
  let workspacePointerOwnerToken = null;
  let sidebarContainerEl = null;
  let sidebarShellEl = null;
  let sidebarHoverBtn = null;

  function readInitialCollectionId() {
    let value = '';
    try {
      const container = document.getElementById('collectionsContent');
      if (container && container.hasAttribute('data-default-collection-id')) {
        value = container.getAttribute('data-default-collection-id') || '';
      }
    } catch (_err) {}
    if (!value) {
      try {
        const params = new URLSearchParams(window.location.search || '');
        value = params.get('collection') || '';
      } catch (_err) {}
    }
    if (!value) {
      try {
        const match = String(window.location.pathname || '').match(/^\/collections\/([^\/?#]+)/);
        if (match && match[1]) {
          value = decodeURIComponent(match[1]);
        }
      } catch (_err) {}
    }
    return value ? String(value).trim() : '';
  }

  function consumeInitialCollectionId() {
    if (initialCollectionIdConsumed) {
      return '';
    }
    initialCollectionIdConsumed = true;
    const val = readInitialCollectionId();
    if (val) {
      try {
        const container = document.getElementById('collectionsContent');
        if (container) {
          container.removeAttribute('data-default-collection-id');
        }
      } catch (_err) {}
    }
    return val;
  }

  function markSidebarSelection(cid){
    try {
      const list = document.querySelector('#collectionsSidebar #collectionsList');
      if (!list) return;
      const desired = String(cid || '').trim();
      list.querySelectorAll('.sidebar-item').forEach(btn => {
        const id = String(btn.getAttribute('data-id') || '').trim();
        btn.classList.toggle('active', desired && id === desired);
      });
    } catch (_err) {}
  }

  async function ensureCollectionsSidebar(){
    const root = document.getElementById('collectionsSidebar');
    if (!root) return;
    root.innerHTML = '<div class="loading">טוען…</div>';
    try {
      const data = await api.listCollections();
      if (!data || !data.ok) throw new Error(data && data.error || 'שגיאה');
        const items = (data.collections || []).map((c) => {
          const iconChar = (ALLOWED_ICONS.includes(c.icon) ? c.icon : (ALLOWED_ICONS[0] || '📂')) || '📂';
          const shareActive = !!(c.share && c.share.enabled);
          const countHtml = `${shareActive ? '<span class="share-indicator" title="האוסף משותף">🔗</span>' : ''}<span class="count-number">${Number(c.items_count || 0)}</span>`;
          return `
            <button class="sidebar-item" data-id="${c.id}">
              <span class="emoji">${escapeHtml(iconChar)}</span>
              <span class="name">${escapeHtml(c.name || 'ללא שם')}</span>
              <span class="count">${countHtml}</span>
            </button>
          `;
        }).join('');
      root.innerHTML = `
        <div class="sidebar-header">
          <div class="title">האוספים שלי</div>
          <button id="createCollectionBtn" class="btn btn-secondary btn-icon" title="צור אוסף חדש">➕</button>
        </div>
        <div class="sidebar-search">
          <input id="collectionsSearch" type="text" placeholder="חפש אוספים…"/>
        </div>
        <div class="sidebar-list" id="collectionsList">${items || '<div class="empty">אין אוספים</div>'}</div>
      `;
      wireSidebarHandlers(root);
      setupSidebarDropHandlers(root);
      if (currentCollectionId) {
        markSidebarSelection(currentCollectionId);
      } else {
        const pending = readInitialCollectionId();
        if (pending) {
          markSidebarSelection(pending);
        }
      }
      // התאמת טקסט דינמית לשמות אוספים ארוכים בסיידבר
      autoFitText('#collectionsSidebar .sidebar-item .name', { minPx: 12, maxPx: 16 });
    } catch (e) {
      root.innerHTML = '<div class="error">שגיאה בטעינת האוספים</div>';
    }
  }

  function setShareControlsBusy(toggleEl, copyBtn, busy){
    if (toggleEl) toggleEl.disabled = !!busy;
    if (copyBtn) {
      const hasUrl = ((copyBtn.getAttribute('data-url') || '').trim().length > 0);
      copyBtn.disabled = !!busy || !(toggleEl && toggleEl.checked) || !hasUrl;
    }
  }

  function resolvePublicUrl(col){
    try {
      if (!col) return '';
      const share = col.share || {};
      if (!share.enabled) return '';
      const direct = (col.public_url || col.publicUrl || '').trim();
      if (direct) return String(direct);
      const token = share.token || '';
      if (!token) return '';
      const base = String(window.location.origin || '').replace(/\/$/, '');
      return `${base}/collections/shared/${encodeURIComponent(String(token))}`;
    } catch (_err) {
      return '';
    }
  }

  function buildIconGridHtml(selected){
    const fallback = ALLOWED_ICONS[0] || '📂';
    const current = ALLOWED_ICONS.includes(selected) ? selected : fallback;
    return ALLOWED_ICONS.map(icon => {
      const isActive = icon === current;
      const cls = `icon-option${isActive ? ' active' : ''}`;
      return `<button type="button" class="${cls}" data-icon="${escapeHtml(icon)}">${escapeHtml(icon)}</button>`;
    }).join('');
  }

  function openCreateCollectionDialog(){
    if (document.querySelector('.collection-modal[data-modal="create-collection"]')) {
      return;
    }
    const defaultIcon = ALLOWED_ICONS[0] || '📂';
    const overlay = document.createElement('div');
    overlay.className = 'collection-modal';
    overlay.setAttribute('data-modal', 'create-collection');
    overlay.innerHTML = `
      <div class="collection-modal__backdrop"></div>
      <div class="collection-modal__panel" role="dialog" aria-modal="true">
        <h3 class="collection-modal__title">אוסף חדש</h3>
        <div class="collection-modal__field">
          <label for="collectionNameInput">שם האוסף</label>
          <input id="collectionNameInput" type="text" maxlength="80" placeholder="לדוגמה: קטעים מועדפים">
        </div>
        <div class="collection-modal__field">
          <label>בחר אייקון</label>
          <div class="icon-grid">${buildIconGridHtml(defaultIcon)}</div>
        </div>
        <div class="collection-modal__error" aria-live="polite"></div>
        <div class="collection-modal__actions">
          <button type="button" class="btn btn-secondary cancel">בטל</button>
          <button type="button" class="btn btn-primary confirm">צור</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    const nameInput = overlay.querySelector('#collectionNameInput');
    const iconGrid = overlay.querySelector('.icon-grid');
    const errorBox = overlay.querySelector('.collection-modal__error');
    const cancelBtn = overlay.querySelector('.cancel');
    const confirmBtn = overlay.querySelector('.confirm');
    const backdrop = overlay.querySelector('.collection-modal__backdrop');
    let selectedIcon = defaultIcon;

    if (iconGrid) {
      iconGrid.addEventListener('click', (ev) => {
        const btn = ev.target.closest('.icon-option');
        if (!btn) return;
        selectedIcon = btn.getAttribute('data-icon') || defaultIcon;
        iconGrid.querySelectorAll('.icon-option').forEach(el => el.classList.toggle('active', el === btn));
      });
    }

    const showError = (msg) => {
      if (!errorBox) return;
      if (msg) {
        errorBox.textContent = msg;
        errorBox.style.display = 'block';
      } else {
        errorBox.textContent = '';
        errorBox.style.display = 'none';
      }
    };

    const cleanup = () => {
      document.removeEventListener('keydown', onKeydown);
      try { overlay.remove(); } catch (_err) {
        if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
      }
    };

    const close = () => {
      cleanup();
    };

    const onKeydown = (ev) => {
      if (ev.key === 'Escape') {
        ev.preventDefault();
        close();
      } else if (ev.key === 'Enter' && document.activeElement === nameInput) {
        ev.preventDefault();
        confirmBtn && confirmBtn.click();
      }
    };

    document.addEventListener('keydown', onKeydown);
    backdrop && backdrop.addEventListener('click', close);
    cancelBtn && cancelBtn.addEventListener('click', close);

    if (confirmBtn) {
      confirmBtn.addEventListener('click', async () => {
        const nameRaw = String(nameInput && nameInput.value ? nameInput.value : '').trim();
        if (!nameRaw) {
          showError('יש להזין שם לאוסף');
          nameInput && nameInput.focus();
          return;
        }
        showError('');
        const iconToSend = ALLOWED_ICONS.includes(selectedIcon) ? selectedIcon : defaultIcon;
        confirmBtn.disabled = true;
        const originalLabel = confirmBtn.textContent || 'צור';
        confirmBtn.textContent = 'יוצר...';
        try {
          const res = await api.createCollection({ name: nameRaw.slice(0, 80), mode: 'manual', icon: iconToSend });
          if (!res || !res.ok) {
            showError((res && res.error) || 'שגיאה ביצירת האוסף');
            confirmBtn.disabled = false;
            confirmBtn.textContent = originalLabel;
            return;
          }
          close();
          ensureCollectionsSidebar();
          if (res.collection && res.collection.id) {
            await renderCollectionItems(res.collection.id);
          }
        } catch (_err) {
          showError('שגיאה ביצירת האוסף');
          confirmBtn.disabled = false;
          confirmBtn.textContent = originalLabel;
        }
      });
    }

    requestAnimationFrame(() => {
      if (nameInput) {
        nameInput.focus();
        nameInput.select();
      }
    });
  }

  function openIconPicker(initialIcon){
    if (document.querySelector('.collection-modal[data-modal="icon-picker"]')) {
      return Promise.resolve(null);
    }
    const defaultIcon = ALLOWED_ICONS.includes(initialIcon) ? initialIcon : (ALLOWED_ICONS[0] || '📂');
    return new Promise((resolve) => {
      const overlay = document.createElement('div');
      overlay.className = 'collection-modal';
      overlay.setAttribute('data-modal', 'icon-picker');
      overlay.innerHTML = `
        <div class="collection-modal__backdrop"></div>
        <div class="collection-modal__panel" role="dialog" aria-modal="true">
          <h3 class="collection-modal__title">בחר אייקון</h3>
          <div class="collection-modal__field">
            <div class="icon-grid">${buildIconGridHtml(defaultIcon)}</div>
          </div>
          <div class="collection-modal__actions">
            <button type="button" class="btn btn-secondary cancel">בטל</button>
            <button type="button" class="btn btn-primary confirm">שמור</button>
          </div>
        </div>
      `;
      document.body.appendChild(overlay);

      const iconGrid = overlay.querySelector('.icon-grid');
      const cancelBtn = overlay.querySelector('.cancel');
      const confirmBtn = overlay.querySelector('.confirm');
      const backdrop = overlay.querySelector('.collection-modal__backdrop');
      let selectedIcon = defaultIcon;

      if (iconGrid) {
        iconGrid.addEventListener('click', (ev) => {
          const btn = ev.target.closest('.icon-option');
          if (!btn) return;
          selectedIcon = btn.getAttribute('data-icon') || defaultIcon;
          iconGrid.querySelectorAll('.icon-option').forEach(el => el.classList.toggle('active', el === btn));
        });
      }

      const cleanup = () => {
        document.removeEventListener('keydown', onKeydown);
        try { overlay.remove(); } catch (_err) {
          if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
        }
      };

      let settled = false;
      const finish = (value) => {
        if (settled) return;
        settled = true;
        cleanup();
        resolve(value);
      };

      const onKeydown = (ev) => {
        if (ev.key === 'Escape') {
          ev.preventDefault();
          finish(null);
        } else if (ev.key === 'Enter') {
          ev.preventDefault();
          confirmBtn && confirmBtn.click();
        }
      };

      document.addEventListener('keydown', onKeydown);
      backdrop && backdrop.addEventListener('click', () => finish(null));
      cancelBtn && cancelBtn.addEventListener('click', () => finish(null));
      if (confirmBtn) {
        confirmBtn.addEventListener('click', () => {
          const iconToSend = ALLOWED_ICONS.includes(selectedIcon) ? selectedIcon : defaultIcon;
          finish(iconToSend);
        });
      }

      requestAnimationFrame(() => {
        const activeBtn = overlay.querySelector('.icon-option.active');
        if (activeBtn) {
          activeBtn.focus();
        }
      });
    });
  }

    function wireSidebarHandlers(root){
      const list = root.querySelector('#collectionsList');
      const search = root.querySelector('#collectionsSearch');
      const createBtn = root.querySelector('#createCollectionBtn');
      if (createBtn) {
        createBtn.addEventListener('click', () => {
          openCreateCollectionDialog();
        });
      }

    if (search) {
      search.addEventListener('input', () => {
        const q = (search.value||'').trim().toLowerCase();
        list.querySelectorAll('.sidebar-item').forEach(btn => {
          const name = (btn.querySelector('.name')?.textContent||'').toLowerCase();
          btn.style.display = (!q || name.includes(q)) ? '' : 'none';
        });
      });
    }

    if (list) {
      list.addEventListener('click', async (ev) => {
        const btn = ev.target.closest('.sidebar-item');
        if (!btn) return;
        const cid = btn.getAttribute('data-id');
        await renderCollectionItems(cid);
      });
    }
  }

  function updateSidebarShell(root){
    sidebarContainerEl = root || document.getElementById('collectionsSidebar');
    const host = sidebarContainerEl ? sidebarContainerEl.closest('.collections-sidebar') : null;
    sidebarShellEl = host || document.querySelector('.collections-sidebar');
  }

  function resolveSidebarContainer(){
    if (!sidebarContainerEl || !sidebarContainerEl.isConnected) {
      sidebarContainerEl = document.getElementById('collectionsSidebar');
    }
    return sidebarContainerEl;
  }

  function setSidebarDragVisual(active){
    if (!sidebarShellEl || !sidebarShellEl.isConnected) {
      sidebarShellEl = document.querySelector('.collections-sidebar');
    }
    if (!sidebarShellEl) return;
    sidebarShellEl.classList.toggle('drag-active', !!active);
  }

  function setSidebarDropHover(btn, mode){
    if (sidebarHoverBtn === btn) {
      if (!btn) return;
      if (mode === 'hover') {
        btn.classList.add('sidebar-item--drop-hover');
      } else {
        btn.classList.remove('sidebar-item--drop-hover');
      }
      return;
    }
    if (sidebarHoverBtn) {
      sidebarHoverBtn.classList.remove('sidebar-item--drop-ready', 'sidebar-item--drop-hover', 'sidebar-item--drop-busy');
    }
    sidebarHoverBtn = btn && btn.isConnected ? btn : null;
    if (sidebarHoverBtn) {
      sidebarHoverBtn.classList.add('sidebar-item--drop-ready');
      if (mode === 'hover') {
        sidebarHoverBtn.classList.add('sidebar-item--drop-hover');
      }
    }
  }

  function withSidebarDropBusy(btn){
    if (!btn || !btn.classList) {
      return () => {};
    }
    btn.classList.add('sidebar-item--drop-busy');
    return () => {
      btn.classList.remove('sidebar-item--drop-busy');
    };
  }

  function canDropOnSidebar(targetId){
    if (!activeDragContext) return false;
    const desired = String(targetId || '').trim();
    if (!desired) return false;
    return desired !== String(activeDragContext.collectionId || '').trim();
  }

  function beginCollectionItemDrag(row, collectionId, listEl, origin){
    const payload = buildItemPayloadFromRow(row);
    if (!payload) return;
    const ctx = {
      element: row,
      collectionId: collectionId,
      container: listEl,
      payload,
      origin,
      dropInProgress: false,
    };
    if (origin === 'workspace') {
      ctx.workspacePointerToken = startWorkspacePointerTracking();
    }
    activeDragContext = ctx;
    setSidebarDragVisual(true);
  }

  function resetDragUi(){
    setSidebarDropHover(null);
    setSidebarDragVisual(false);
  }

  function clearActiveDragContext(){
    const ctx = activeDragContext;
    activeDragContext = null;
    resetDragUi();
    if (ctx && ctx.origin === 'workspace') {
      stopWorkspacePointerTracking(ctx.workspacePointerToken);
    }
  }

  function trackWorkspacePointer(event){
    if (!event) return;
    const { clientX, clientY } = event;
    if (typeof clientX !== 'number' || typeof clientY !== 'number') {
      return;
    }
    workspaceDragPointer = { x: clientX, y: clientY };
  }

  function consumeWorkspacePointer(){
    const point = workspaceDragPointer;
    workspaceDragPointer = null;
    return point;
  }

  function startWorkspacePointerTracking(){
    if (typeof document === 'undefined') {
      return null;
    }
    stopWorkspacePointerTracking();
    const token = Symbol('workspace-pointer');
    const handlers = [];
    const updateFromEvent = (ev) => {
      if (!ev) return;
      let pointX = null;
      let pointY = null;
      if (typeof ev.clientX === 'number' && typeof ev.clientY === 'number') {
        pointX = ev.clientX;
        pointY = ev.clientY;
      } else if (ev.touches && ev.touches[0]) {
        pointX = ev.touches[0].clientX;
        pointY = ev.touches[0].clientY;
      }
      if (typeof pointX !== 'number' || typeof pointY !== 'number') {
        return;
      }
      trackWorkspacePointer({ clientX: pointX, clientY: pointY });
      if (activeDragContext && activeDragContext.origin === 'workspace') {
        updateSidebarHoverFromPoint(pointX, pointY);
      }
    };
    const hasPointer = typeof window !== 'undefined' && 'onpointermove' in window;
    if (hasPointer) {
      const pointerHandler = (ev) => updateFromEvent(ev);
      document.addEventListener('pointermove', pointerHandler);
      handlers.push(() => {
        document.removeEventListener('pointermove', pointerHandler);
      });
    } else {
      const mouseHandler = (ev) => updateFromEvent(ev);
      const touchHandler = (ev) => updateFromEvent(ev);
      document.addEventListener('mousemove', mouseHandler);
      document.addEventListener('touchmove', touchHandler);
      handlers.push(() => {
        document.removeEventListener('mousemove', mouseHandler);
        document.removeEventListener('touchmove', touchHandler);
      });
    }
    workspacePointerCleanup = () => {
      handlers.forEach((fn) => {
        try { fn(); } catch (_err) {}
      });
      workspacePointerCleanup = null;
      workspacePointerOwnerToken = null;
    };
    workspacePointerOwnerToken = token;
    return token;
  }

  function stopWorkspacePointerTracking(token){
    if (token && workspacePointerOwnerToken && token !== workspacePointerOwnerToken) {
      return;
    }
    if (typeof workspacePointerCleanup === 'function') {
      try { workspacePointerCleanup(); } catch (_err) {}
    }
    workspacePointerCleanup = null;
    workspacePointerOwnerToken = null;
  }

  function buildItemPayloadFromRow(row){
    if (!row) return null;
    const fileName = row.getAttribute('data-name') || '';
    if (!fileName) return null;
    const payload = {
      source: row.getAttribute('data-source') || 'regular',
      file_name: fileName,
    };
    const pinnedAttr = row.getAttribute('data-pinned');
    if (pinnedAttr === '1') {
      payload.pinned = true;
    }
    return payload;
  }

  function ensureItemsContainerState(container){
    if (!container || !container.isConnected) return;
    if (container.querySelector('.collection-item')) {
      return;
    }
    container.innerHTML = '<div class="empty">אין פריטים</div>';
  }

  function findSidebarButtonFromPoint(x, y){
    if (typeof document === 'undefined') return null;
    let el = null;
    try {
      el = document.elementFromPoint(x, y);
    } catch (_err) {
      el = null;
    }
    if (el) {
      const directBtn = el.closest('#collectionsSidebar .sidebar-item');
      if (directBtn) {
        return directBtn;
      }
    }
    return findSidebarButtonByBounds(x, y);
  }

  function findSidebarButtonByBounds(x, y){
    if (typeof x !== 'number' || typeof y !== 'number') {
      return null;
    }
    const container = resolveSidebarContainer();
    if (!container) {
      return null;
    }
    const rect = container.getBoundingClientRect();
    if (!rect) {
      return null;
    }
    const padding = 16;
    const insideSidebar = (
      x >= rect.left - padding &&
      x <= rect.right + padding &&
      y >= rect.top - padding &&
      y <= rect.bottom + padding
    );
    if (!insideSidebar) {
      return null;
    }
    const buttons = container.querySelectorAll('.sidebar-item');
    let fallbackBtn = null;
    let smallestDelta = Number.POSITIVE_INFINITY;
    for (let i = 0; i < buttons.length; i += 1) {
      const btn = buttons[i];
      if (!(btn instanceof HTMLElement)) continue;
      const btnRect = btn.getBoundingClientRect();
      if (!btnRect) continue;
      const tolerance = 8;
      const withinBtn = (
        x >= btnRect.left - tolerance &&
        x <= btnRect.right + tolerance &&
        y >= btnRect.top - tolerance &&
        y <= btnRect.bottom + tolerance
      );
      if (withinBtn) {
        return btn;
      }
      const centerY = (btnRect.top + btnRect.bottom) / 2;
      const delta = Math.abs(centerY - y);
      const withinHorizontal = x >= btnRect.left - padding && x <= btnRect.right + padding;
      if (withinHorizontal && delta < smallestDelta) {
        smallestDelta = delta;
        fallbackBtn = btn;
      }
    }
    return fallbackBtn;
  }

  function updateSidebarHoverFromPoint(x, y){
    if (!activeDragContext) return;
    const btn = findSidebarButtonFromPoint(x, y);
    if (btn && canDropOnSidebar(btn.getAttribute('data-id') || '')) {
      setSidebarDropHover(btn, 'hover');
    } else {
      setSidebarDropHover(null);
    }
  }

  async function handleSidebarDropRequest(targetId, targetBtn){
    if (!canDropOnSidebar(targetId)) {
      setSidebarDropHover(null);
      return;
    }
    if (!activeDragContext || activeDragContext.dropInProgress) {
      return;
    }
    activeDragContext.dropInProgress = true;
    await moveDraggedItemToCollection(targetId, targetBtn || sidebarHoverBtn);
  }

  async function moveDraggedItemToCollection(targetCollectionId, targetBtn){
    const ctx = activeDragContext;
    if (!ctx) {
      resetDragUi();
      return;
    }
    const payload = ctx.payload;
    if (!payload || !payload.file_name) {
      ctx.dropInProgress = false;
      if (activeDragContext === ctx) {
        clearActiveDragContext();
      } else if (ctx.origin === 'workspace') {
        stopWorkspacePointerTracking(ctx.workspacePointerToken);
      }
      return;
    }
    setSidebarDropHover(targetBtn || sidebarHoverBtn, 'hover');
    const stopBusy = withSidebarDropBusy(targetBtn || sidebarHoverBtn);
    try {
      const addRes = await api.addItems(targetCollectionId, [payload]);
      if (!addRes || !addRes.ok) {
        throw new Error((addRes && addRes.error) || 'שגיאה בהעברת הפריט');
      }
      const removeRes = await api.removeItems(ctx.collectionId, [{ source: ctx.payload.source || 'regular', file_name: ctx.payload.file_name }]);
      if (!removeRes || !removeRes.ok) {
        throw new Error((removeRes && removeRes.error) || 'שגיאה בהעברת הפריט');
      }
      if (ctx.element && ctx.element.remove) {
        const listEl = (ctx.container && ctx.container.isConnected) ? ctx.container : ctx.element.parentElement;
        ctx.element.remove();
        if (listEl && typeof listEl.hasAttribute === 'function' && listEl.hasAttribute('data-state-list')) {
          if (workspaceBoardCtx) {
            updateWorkspaceEmptyStates(workspaceBoardCtx);
          }
        } else {
          ensureItemsContainerState(listEl);
        }
      }
      await ensureCollectionsSidebar();
    } catch (err) {
      alert((err && err.message) || 'שגיאה בהעברת הפריט');
      throw err;
    } finally {
      ctx.dropInProgress = false;
      stopBusy();
      if (activeDragContext === ctx) {
        clearActiveDragContext();
      } else if (ctx.origin === 'workspace') {
        stopWorkspacePointerTracking(ctx.workspacePointerToken);
      }
    }
  }

  function setupSidebarDropHandlers(root){
    updateSidebarShell(root);
    const buttons = root.querySelectorAll('.sidebar-item');
    buttons.forEach((btn) => {
      btn.addEventListener('dragenter', handleSidebarDragEnter);
      btn.addEventListener('dragover', handleSidebarDragOver);
      btn.addEventListener('dragleave', handleSidebarDragLeave);
      btn.addEventListener('drop', handleSidebarDrop);
    });
    if (activeDragContext) {
      setSidebarDragVisual(true);
    }
  }

  function handleSidebarDragEnter(ev){
    const btn = ev.currentTarget;
    if (!(btn instanceof HTMLElement)) return;
    const cid = btn.getAttribute('data-id') || '';
    if (!canDropOnSidebar(cid)) return;
    ev.preventDefault();
    setSidebarDropHover(btn, 'ready');
  }

  function handleSidebarDragOver(ev){
    const btn = ev.currentTarget;
    if (!(btn instanceof HTMLElement)) return;
    const cid = btn.getAttribute('data-id') || '';
    if (!canDropOnSidebar(cid)) return;
    ev.preventDefault();
    if (ev.dataTransfer) {
      ev.dataTransfer.dropEffect = 'move';
    }
    setSidebarDropHover(btn, 'hover');
  }

  function handleSidebarDragLeave(ev){
    const btn = ev.currentTarget;
    if (!(btn instanceof HTMLElement)) return;
    const related = ev.relatedTarget;
    if (related && btn.contains(related)) {
      return;
    }
    if (sidebarHoverBtn === btn) {
      setSidebarDropHover(null);
    }
  }

  function handleSidebarDrop(ev){
    const btn = ev.currentTarget;
    if (!(btn instanceof HTMLElement)) return;
    const cid = btn.getAttribute('data-id') || '';
    if (!canDropOnSidebar(cid)) return;
    ev.preventDefault();
    handleSidebarDropRequest(cid, btn).catch(() => {});
  }

  async function renderCollectionItems(cid){
    const container = document.getElementById('collectionsContent');
    if (!container) return;
    resetDragUi();
    activeDragContext = null;
    const collectionId = String(cid || '').trim();
    if (!collectionId) {
      container.innerHTML = '<div class="error">האוסף לא נמצא</div>';
      markSidebarSelection('');
      return;
    }
    markSidebarSelection(collectionId);
    teardownWorkspaceBoard();
    container.innerHTML = '<div class="loading">טוען…</div>';
    try {
      const [colRes, data] = await Promise.all([
        api.getCollection(collectionId),
        api.getItems(collectionId, 1, 200),
      ]);
      if (!data || !data.ok) throw new Error((data && data.error) || 'שגיאה');
      if (!colRes || !colRes.ok) throw new Error((colRes && colRes.error) || 'שגיאה');
      const col = colRes.collection || {};
      const isWorkspace = isWorkspaceCollection(col);

      const baseItems = Array.isArray(data.items) ? data.items : [];
      const iconChar = (col.icon && ALLOWED_ICONS.includes(col.icon)) ? col.icon : (ALLOWED_ICONS[0] || '📂');
      const share = col.share || {};
      const shareEnabled = !!share.enabled;
      const shareUrl = resolvePublicUrl(col);
      const headerHtml = `
        <div class="collection-header">
          <div class="title">
            <button class="collection-icon-btn" type="button" aria-label="בחר אייקון" title="בחר אייקון">${escapeHtml(iconChar)}</button>
            <div class="name" title="${escapeHtml(col.name || 'ללא שם')}">${escapeHtml(col.name || 'ללא שם')}</div>
          </div>
          <div class="share-controls" data-enabled="${shareEnabled ? '1' : '0'}">
            <label class="share-toggle">
              <input type="checkbox" class="share-enabled" ${shareEnabled ? 'checked' : ''}>
              <span class="share-toggle__text">שיתוף</span>
            </label>
            <span class="share-divider" aria-hidden="true">|</span>
            <button class="btn btn-secondary btn-sm share-copy" ${shareEnabled && shareUrl ? '' : 'disabled'} data-url="${shareUrl ? escapeHtml(shareUrl) : ''}" title="העתק קישור לשיתוף" aria-label="העתק קישור לשיתוף">
              <span class="share-copy__text">העתק</span>
            </button>
          </div>
          <div class="actions">
            <button class="btn btn-secondary rename">שנה שם</button>
            <button class="btn btn-danger delete">מחק</button>
          </div>
        </div>`;
      if (isWorkspace) {
        const boardHtml = buildWorkspaceBoardHtml(baseItems);
        container.innerHTML = `${headerHtml}${boardHtml}`;
      } else {
        const itemsHtml = baseItems.map((it) => {
          const fileName = String(it.file_name || '').trim();
          const fileNameEsc = escapeHtml(fileName);
          const mode = getDirectViewMode(fileName);
          const btnLabel = directViewTitle(mode);
          const directBtn = mode
            ? `<button class="open-view" data-view="${escapeHtml(mode)}" title="${escapeHtml(btnLabel)}" aria-label="${escapeHtml(btnLabel)}">🌐</button>`
            : '';
          return `
            <div class="collection-item" data-source="${escapeHtml(it.source || 'regular')}" data-name="${fileNameEsc}" data-file-id="${escapeHtml(it.file_id || '')}" data-pinned="${it.pinned ? '1' : '0'}">
              <span class="drag" draggable="true">⋮⋮</span>
              <a class="file" href="#" draggable="false" data-open="${fileNameEsc}">${fileNameEsc}</a>
              ${directBtn}
              <button class="preview" title="תצוגה מקדימה" aria-label="תצוגה מקדימה">🧾</button>
              <button class="remove" title="הסר">✕</button>
            </div>
          `;
        }).join('');
        container.innerHTML = `${headerHtml}<div class="collection-items" id="collectionItems">${itemsHtml || '<div class="empty">אין פריטים</div>'}</div>`;
      }

      const iconBtn = container.querySelector('.collection-icon-btn');
      if (iconBtn) {
        iconBtn.addEventListener('click', async () => {
          try {
            const nextIcon = await openIconPicker(iconChar);
            if (!nextIcon || nextIcon === iconChar) {
              return;
            }
            const res = await api.updateCollection(collectionId, { icon: nextIcon });
            if (!res || !res.ok) {
              alert((res && res.error) || 'שגיאה בעדכון האייקון');
              return;
            }
            ensureCollectionsSidebar();
            await renderCollectionItems(collectionId);
          } catch (_err) {
            alert('שגיאה בעדכון האייקון');
          }
        });
      }

      const shareControls = container.querySelector('.share-controls');
      const shareToggleEl = shareControls ? shareControls.querySelector('.share-enabled') : null;
      const shareCopyBtn = shareControls ? shareControls.querySelector('.share-copy') : null;
      const shareCopyLabel = shareCopyBtn ? shareCopyBtn.querySelector('.share-copy__text') : null;
      if (shareCopyBtn && !shareCopyBtn.dataset.label) {
        const labelText = shareCopyLabel ? shareCopyLabel.textContent : shareCopyBtn.textContent;
        shareCopyBtn.dataset.label = labelText && labelText.trim() ? labelText.trim() : 'העתק';
      }
      setShareControlsBusy(shareToggleEl, shareCopyBtn, false);

      if (shareCopyBtn) {
        shareCopyBtn.addEventListener('click', async () => {
          const url = shareCopyBtn.getAttribute('data-url') || '';
          if (!url) {
            alert('אין קישור שיתוף פעיל');
            return;
          }
          const original = shareCopyBtn.dataset.label || (shareCopyLabel ? shareCopyLabel.textContent : '') || 'העתק';
          try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
              await navigator.clipboard.writeText(url);
            } else {
              throw new Error('clipboard_unavailable');
            }
            if (shareCopyLabel) {
              shareCopyLabel.textContent = 'הועתק!';
            } else {
              shareCopyBtn.textContent = 'הועתק!';
            }
            setTimeout(() => {
              if (shareCopyLabel) {
                shareCopyLabel.textContent = original;
              } else {
                shareCopyBtn.textContent = original;
              }
            }, 1600);
          } catch (_err) {
            try {
              const manual = prompt('העתק את הקישור הבא:', url);
              if (manual !== null) {
                if (shareCopyLabel) {
                  shareCopyLabel.textContent = 'הועתק!';
                } else {
                  shareCopyBtn.textContent = 'הועתק!';
                }
                setTimeout(() => {
                  if (shareCopyLabel) {
                    shareCopyLabel.textContent = original;
                  } else {
                    shareCopyBtn.textContent = original;
                  }
                }, 1600);
              }
            } catch (_) {
              alert('לא ניתן להעתיק את הקישור אוטומטית');
            }
          }
        });
      }

      if (shareToggleEl) {
        shareToggleEl.addEventListener('change', async () => {
          const enabled = shareToggleEl.checked;
          let errorMessage = '';
          setShareControlsBusy(shareToggleEl, shareCopyBtn, true);
          try {
            const res = await api.updateShare(collectionId, { enabled });
            if (!res || !res.ok) {
              errorMessage = (res && res.error) || '';
              throw new Error(errorMessage || 'share_update_failed');
            }
          } catch (_err) {
            shareToggleEl.checked = !enabled;
            alert(errorMessage || 'שגיאה בעדכון שיתוף');
          } finally {
            setShareControlsBusy(shareToggleEl, shareCopyBtn, false);
          }
          ensureCollectionsSidebar();
          await renderCollectionItems(collectionId);
        });
      }

      let itemsContainer = null;
      if (isWorkspace) {
        hydrateWorkspaceBoard(container, collectionId, baseItems);
        autoFitText('.workspace-card__name', { minPx: 12, maxPx: 16 });
      } else {
        itemsContainer = container.querySelector('#collectionItems');
        wireDnd(itemsContainer, collectionId);
        autoFitText('#collectionItems .file', { minPx: 12, maxPx: 16 });
      }

      // Header actions
      const renameBtn = container.querySelector('.collection-header .rename');
      const deleteBtn = container.querySelector('.collection-header .delete');
      if (renameBtn) renameBtn.addEventListener('click', async () => {
        const current = String(col.name || '');
        const name = prompt('שם חדש לאוסף:', current);
        if (!name) return;
        const res = await api.updateCollection(collectionId, { name: name.slice(0, 80) });
        if (!res || !res.ok) return alert((res && res.error) || 'שגיאה בעדכון שם');
        ensureCollectionsSidebar();
        await renderCollectionItems(collectionId);
      });
      if (deleteBtn) deleteBtn.addEventListener('click', async () => {
        if (!confirm('למחוק את האוסף? הפעולה תסיר את האוסף ואת הקישורים שבו, אבל הקבצים עצמם יישארו זמינים בבוט ובקבצים.')) return;
        const res = await api.deleteCollection(collectionId);
        if (!res || !res.ok) return alert((res && res.error) || 'שגיאה במחיקה');
        ensureCollectionsSidebar();
        container.innerHTML = '<div class="empty">האוסף נמחק. הקבצים נשארים זמינים בבוט ובמסך הקבצים.</div>';
      });

      if (!isWorkspace && itemsContainer) {
        itemsContainer.addEventListener('click', async (ev) => {
          const row = ev.target.closest('.collection-item');
          if (!row) return;
          const source = row.getAttribute('data-source') || 'regular';
          const name = row.getAttribute('data-name') || '';

          const rm = ev.target.closest('.remove');
          if (rm) {
            if (!confirm('להסיר את הפריט מהאוסף? הקובץ עצמו יישאר זמין בבוט ובמסך הקבצים.')) return;
            const res = await api.removeItems(collectionId, [{ source, file_name: name }]);
            if (!res || !res.ok) return alert((res && res.error) || 'שגיאה במחיקה');
            row.remove();
            if (!itemsContainer.querySelector('.collection-item')) {
              itemsContainer.innerHTML = '<div class="empty">אין פריטים</div>';
            }
            return;
          }

          const openBtn = ev.target.closest('.open-view');
          if (openBtn) {
            ev.preventDefault();
            await handleDirectViewClick(row, openBtn, name);
            return;
          }

          const previewBtn = ev.target.closest('.preview');
          if (previewBtn) {
            ev.preventDefault();
            await handlePreviewClick(row, previewBtn, name);
            return;
          }

          if (ev.target.closest('.card-code-preview-wrapper')) {
            return;
          }
          const link = ev.target.closest('a.file[data-open]');
          if (link) {
            ev.preventDefault();
            const fname = link.getAttribute('data-open') || '';
            await openFileByName(fname);
            return;
          }
          if (!ev.target.closest('.drag') && !ev.target.closest('button')) {
            const fname = name;
            await openFileByName(fname);
          }
        });
      }

      currentCollectionId = collectionId;
    } catch (e) {
      container.innerHTML = '<div class="error">שגיאה בטעינת פריטים</div>';
    }
  }

  async function resolveFileId(name){
    const key = String(name || '').trim();
    if (!key) {
      const err = new Error('missing_name');
      err.code = 'missing_name';
      throw err;
    }
    if (resolvedFileIdCache.has(key)) {
      return resolvedFileIdCache.get(key);
    }
    let resp;
    try {
      resp = await fetch(`/api/files/resolve?name=${encodeURIComponent(key)}`);
    } catch (_networkErr) {
      const err = new Error('network_error');
      err.code = 'network_error';
      throw err;
    }
    let data = null;
    try {
      data = await resp.json();
    } catch (_jsonErr) {
      data = null;
    }
    if (!resp.ok || !data || data.ok === false || !data.id) {
      const errorCode = (data && data.error) || 'not_found';
      const err = new Error(errorCode);
      err.code = errorCode;
      err.data = data;
      throw err;
    }
    resolvedFileIdCache.set(key, data.id);
    return data.id;
  }

  function setPreviewLoading(button){
    if (!button) return () => {};
    const originalHtml = button.innerHTML;
    button.disabled = true;
    button.classList.add('preview-loading');
    button.innerHTML = '⏳';
    return () => {
      button.disabled = false;
      button.classList.remove('preview-loading');
      button.innerHTML = originalHtml;
    };
  }

  async function handlePreviewClick(row, previewBtn, rawName){
    if (!row || !previewBtn) return;
    if (!window.cardPreview || typeof window.cardPreview.expand !== 'function') {
      alert('תצוגה מקדימה אינה זמינה כרגע');
      return;
    }
    const fname = String(rawName || '').trim();
    if (!fname) {
      alert('שם הקובץ חסר');
      return;
    }
    let fileId = row.getAttribute('data-file-id') || '';
    if (!fileId) {
      const restore = setPreviewLoading(previewBtn);
      try {
        fileId = await resolveFileId(fname);
        if (fileId) {
          row.setAttribute('data-file-id', fileId);
        }
      } catch (err) {
        const code = (err && (err.code || err.message)) || 'error';
        if (code === 'in_recycle_bin') {
          alert(RECYCLE_BIN_ALERT);
        } else if (code === 'not_found') {
          alert('הקובץ לא נמצא להצגה מקדימה');
        } else if (code === 'missing_name') {
          alert('שם הקובץ חסר');
        } else {
          alert('שגיאה בפתיחת התצוגה המקדימה');
        }
        return;
      } finally {
        restore();
      }
    }
    if (!fileId) {
      alert('הקובץ לא נמצא להצגה מקדימה');
      return;
    }
    try { row.dataset.previewHost = '1'; } catch (_e) {}
    window.cardPreview.expand(fileId, row);
  }

  function getDirectViewMode(fileName){
    const lower = String(fileName || '').trim().toLowerCase();
    if (!lower) return '';
    if (lower.endsWith('.md') || lower.endsWith('.markdown')) return 'md';
    if (lower.endsWith('.html') || lower.endsWith('.htm')) return 'html';
    return '';
  }

  function directViewTitle(mode){
    if (mode === 'md') return 'פתח תצוגת Markdown';
    if (mode === 'html') return 'פתח תצוגת דפדפן';
    return 'פתח תצוגה';
  }

  async function handleDirectViewClick(row, button, rawName){
    if (!row || !button) return;
    const fname = String(rawName || '').trim();
    if (!fname) {
      alert('שם הקובץ חסר');
      return;
    }
    const mode = String(button.getAttribute('data-view') || '').trim() || getDirectViewMode(fname);
    if (!mode) {
      // אם זה לא Markdown/HTML, נפול חזרה להתנהגות הרגילה
      await openFileByName(fname);
      return;
    }

    let fileId = row.getAttribute('data-file-id') || '';
    if (!fileId) {
      const restore = setPreviewLoading(button);
      try {
        fileId = await resolveFileId(fname);
        if (fileId) {
          row.setAttribute('data-file-id', fileId);
        }
      } catch (err) {
        const code = (err && (err.code || err.message)) || 'error';
        if (code === 'in_recycle_bin') {
          alert(RECYCLE_BIN_ALERT);
        } else if (code === 'not_found') {
          alert('הקובץ לא נמצא לפתיחה');
        } else if (code === 'missing_name') {
          alert('שם הקובץ חסר');
        } else {
          alert('שגיאה בפתיחת התצוגה');
        }
        return;
      } finally {
        restore();
      }
    }
    if (!fileId) {
      alert('הקובץ לא נמצא לפתיחה');
      return;
    }

    const url = (mode === 'md')
      ? `/md/${encodeURIComponent(fileId)}`
      : `/html/${encodeURIComponent(fileId)}`;
    try {
      window.open(url, '_blank', 'noopener');
    } catch (_err) {
      window.location.href = url;
    }
  }

  // פתיחת קובץ לפי שם הקובץ (שימושי גם ללחיצה על כל השורה)
  async function openFileByName(fname){
    const name = String(fname || '').trim();
    if (!name) return;
    try {
      const fileId = await resolveFileId(name);
      if (fileId) {
        window.location.href = `/file/${encodeURIComponent(fileId)}`;
      } else {
        alert('הקובץ לא נמצא לצפייה');
      }
    } catch (err) {
      const code = (err && (err.code || err.message)) || 'error';
      if (code === 'in_recycle_bin') {
        alert(RECYCLE_BIN_ALERT);
      } else if (code === 'not_found') {
        alert('הקובץ לא נמצא לצפייה');
      } else if (code !== 'missing_name') {
        alert('שגיאה בפתיחת הקובץ');
      }
    }
  }

  function isWorkspaceCollection(col){
    if (!col) return false;
    try {
      const name = String(col.name || '').trim();
      if (name === 'שולחן עבודה') {
        return true;
      }
      const slug = String(col.slug || '').trim().toLowerCase();
      return slug === 'workspace' || slug === 'שולחן-עבודה';
    } catch (_err) {
      return false;
    }
  }

  function normalizeWorkspaceState(value){
    const key = String(value || '').trim().toLowerCase();
    if (WORKSPACE_STATE_META[key]) {
      return key;
    }
    return WORKSPACE_STATE_ORDER[0];
  }

  function workspaceStateLabel(state){
    const key = normalizeWorkspaceState(state);
    return WORKSPACE_STATE_META[key]?.label || WORKSPACE_STATE_META[WORKSPACE_STATE_ORDER[0]].label;
  }

  function buildWorkspaceBoardHtml(items){
    const groups = {};
    WORKSPACE_STATE_ORDER.forEach((state) => { groups[state] = []; });
    (items || []).forEach((item) => {
      const state = normalizeWorkspaceState(item.workspace_state);
      if (!groups[state]) {
        groups[state] = [];
      }
      groups[state].push(item);
    });
    return `
      <div class="workspace-board" data-workspace-board="1">
        <div class="workspace-board__live" aria-live="polite" aria-atomic="true"></div>
        <div class="workspace-board__helper">טיפ: גרור באמצעות הידית או השתמש בקיצורים (Shift+1/2/3)</div>
        <div class="workspace-board__grid">
          ${WORKSPACE_STATE_ORDER.map((state) => {
            const meta = WORKSPACE_STATE_META[state] || {};
            const itemsHtml = (groups[state] || []).map(renderWorkspaceCard).join('');
            const emptyAttr = itemsHtml ? '0' : '1';
            return `
              <section class="workspace-column" data-state="${state}">
                <div class="workspace-column__header">
                  <div class="workspace-column__title">
                    <span>${escapeHtml(meta.label || state)}</span>
                    <span class="workspace-column__count">${Number((groups[state] || []).length)}</span>
                  </div>
                  <div class="workspace-column__meta">
                    <span class="workspace-column__description">${escapeHtml(meta.description || '')}</span>
                    ${meta.shortcut ? `<span class="workspace-shortcut-hint">${escapeHtml(meta.shortcut)}</span>` : ''}
                  </div>
                </div>
                <div class="workspace-column__list" data-state-list="${state}" data-empty="${emptyAttr}">
                  ${itemsHtml}
                </div>
              </section>
            `;
          }).join('')}
        </div>
      </div>
    `;
  }

  function renderWorkspaceCard(item){
    const state = normalizeWorkspaceState(item.workspace_state);
    const itemId = String(item.id || item._id || item.file_name || '');
    const fileName = String(item.file_name || '').trim();
    const mode = getDirectViewMode(fileName);
    const btnLabel = directViewTitle(mode);
    const directBtn = mode
      ? `<button type="button" class="open-view" data-view="${escapeHtml(mode)}" title="${escapeHtml(btnLabel)}" aria-label="${escapeHtml(btnLabel)}">🌐</button>`
      : '';
    return `
      <article class="workspace-card" data-item-id="${escapeHtml(itemId)}" data-state="${escapeHtml(state)}" data-source="${escapeHtml(item.source || 'regular')}" data-name="${escapeHtml(item.file_name || '')}" data-file-id="${escapeHtml(item.file_id || '')}">
        <div class="workspace-card__top">
          <button class="workspace-card__drag" type="button" aria-label="גרור להזזת הפריט">⋮⋮</button>
          <div class="workspace-card__body">
            <div class="workspace-card__name">
              <a class="workspace-card__link" href="#" data-open="${escapeHtml(item.file_name || '')}">${escapeHtml(item.file_name || '')}</a>
            </div>
            <div class="workspace-card__meta">
              <span class="workspace-card__tag">
                <span class="workspace-card__status-indicator" data-state="${escapeHtml(state)}"></span>
                <span class="workspace-card__tag-text">${escapeHtml(workspaceStateLabel(state))}</span>
              </span>
              ${item.note ? `<span>📝 ${escapeHtml(item.note)}</span>` : ''}
            </div>
          </div>
        </div>
        <div class="workspace-card__actions">
          ${directBtn}
          <button type="button" class="preview" title="תצוגה מקדימה" aria-label="תצוגה מקדימה">🧾</button>
          <button type="button" class="remove" title="הסר">✕</button>
        </div>
      </article>
    `;
  }

  function hydrateWorkspaceBoard(container, collectionId, items){
    const board = container.querySelector('.workspace-board');
    if (!board) {
      return;
    }
    const lists = {};
    board.querySelectorAll('[data-state-list]').forEach((listEl) => {
      const state = listEl.getAttribute('data-state-list');
      if (!state) {
        return;
      }
      lists[state] = listEl;
      listEl.dataset.empty = listEl.querySelector('.workspace-card') ? '0' : '1';
    });
    const ctx = {
      board,
      collectionId,
      lists,
      liveRegion: board.querySelector('.workspace-board__live'),
      cleanup: null,
      keyboardHandler: null,
    };
    workspaceBoardCtx = ctx;
    bindWorkspaceCardEvents(ctx);
    setupWorkspaceSortable(ctx);
    setupWorkspaceKeyboard(ctx);
  }

  function bindWorkspaceCardEvents(ctx){
    const board = ctx.board;
    board.addEventListener('focusin', (ev) => {
      const card = ev.target.closest('.workspace-card');
      if (card) {
        workspaceActiveCard = card;
      }
    });
    board.addEventListener('click', async (ev) => {
      const card = ev.target.closest('.workspace-card');
      if (card) {
        workspaceActiveCard = card;
      }
      if (!card) return;
      const source = card.getAttribute('data-source') || 'regular';
      const name = card.getAttribute('data-name') || '';
      const itemId = card.getAttribute('data-item-id') || '';

      const removeBtn = ev.target.closest('.remove');
      if (removeBtn) {
        if (!confirm('להסיר את הפריט מהאוסף? הקובץ עצמו יישאר זמין בבוט ובמסך הקבצים.')) return;
        const res = await api.removeItems(ctx.collectionId, [{ source, file_name: name }]);
        if (!res || !res.ok) {
          alert((res && res.error) || 'שגיאה במחיקה');
          return;
        }
        card.remove();
        updateWorkspaceEmptyStates(ctx);
        return;
      }

      const openBtn = ev.target.closest('.open-view');
      if (openBtn) {
        ev.preventDefault();
        await handleDirectViewClick(card, openBtn, name);
        return;
      }

      const previewBtn = ev.target.closest('.preview');
      if (previewBtn) {
        ev.preventDefault();
        await handlePreviewClick(card, previewBtn, name);
        return;
      }

      if (ev.target.closest('.workspace-card__drag')) {
        return;
      }
      const link = ev.target.closest('a[data-open]');
      if (link) {
        ev.preventDefault();
        const fname = link.getAttribute('data-open') || '';
        await openFileByName(fname);
        return;
      }
      if (!ev.target.closest('button')) {
        await openFileByName(name);
      }
    });
  }

  function setupWorkspaceSortable(ctx){
    if (typeof Sortable === 'undefined') {
      return;
    }
    Object.values(ctx.lists || {}).forEach((listEl) => {
      new Sortable(listEl, {
        group: 'workspace-board',
        handle: '.workspace-card__drag',
        animation: 150,
        forceFallback: true,
        fallbackTolerance: 8,
        dragClass: 'workspace-card--dragging',
        ghostClass: 'workspace-card--ghost',
        onStart(evt) {
          if (!evt || !evt.item) return;
          const originContainer = evt.from || listEl;
          evt.item.__workspacePrevContainer = originContainer;
          evt.item.__workspacePrevIndex = Array.prototype.indexOf.call(originContainer ? originContainer.children : [], evt.item);
          evt.item.__workspacePrevState = evt.item.getAttribute('data-state') || '';
          beginCollectionItemDrag(evt.item, ctx.collectionId, originContainer, 'workspace');
        },
        onMove(evt, originalEvent) {
          const event = originalEvent || (evt && evt.originalEvent) || null;
          if (!event) return;
          trackWorkspacePointer(event);
          if (activeDragContext && activeDragContext.origin === 'workspace') {
            updateSidebarHoverFromPoint(event.clientX, event.clientY);
          }
        },
        async onEnd(evt) {
          const item = evt && evt.item;
          const prevContainer = item && item.__workspacePrevContainer;
          const prevIndex = (item && typeof item.__workspacePrevIndex === 'number') ? item.__workspacePrevIndex : null;
          const prevState = item ? (item.__workspacePrevState || '') : '';
          if (item) {
            delete item.__workspacePrevContainer;
            delete item.__workspacePrevIndex;
            delete item.__workspacePrevState;
          }
          const event = (evt && (evt.originalEvent || evt.event)) || null;
          if (event) {
            trackWorkspacePointer(event);
          }
          const point = consumeWorkspacePointer();
          if (point && activeDragContext && activeDragContext.origin === 'workspace') {
            const dropBtn = findSidebarButtonFromPoint(point.x, point.y);
            const dropId = dropBtn ? (dropBtn.getAttribute('data-id') || '') : '';
            if (dropBtn && canDropOnSidebar(dropId)) {
              try {
                await handleSidebarDropRequest(dropId, dropBtn);
              } catch (_err) {
                restoreWorkspaceCardPosition(prevContainer, item, prevIndex);
                if (prevState) {
                  refreshWorkspaceCardState(item, prevState);
                }
                updateWorkspaceEmptyStates(ctx);
                setSidebarDropHover(null);
              }
              return;
            }
          }
          if (activeDragContext && activeDragContext.origin === 'workspace') {
            clearActiveDragContext();
          }
          handleWorkspaceDrop(ctx, evt.item, evt.from, evt.to);
        },
      });
    });
  }

  function refreshWorkspaceCardState(card, state){
    if (!card) {
      return;
    }
    const nextState = normalizeWorkspaceState(state);
    card.setAttribute('data-state', nextState);
    const indicator = card.querySelector('.workspace-card__status-indicator');
    if (indicator) {
      indicator.setAttribute('data-state', nextState);
    }
    const labelTextEl = card.querySelector('.workspace-card__tag-text');
    if (labelTextEl) {
      labelTextEl.textContent = workspaceStateLabel(nextState);
    }
  }

  function handleWorkspaceDrop(ctx, card, _from, to){
    if (!card || !to) {
      updateWorkspaceEmptyStates(ctx);
      return;
    }
    const newState = to.getAttribute('data-state-list');
    const prevState = card.getAttribute('data-state') || '';
    if (!newState || newState === prevState) {
      updateWorkspaceEmptyStates(ctx);
      return;
    }
    const itemId = card.getAttribute('data-item-id') || '';
    if (!itemId) {
      updateWorkspaceEmptyStates(ctx);
      return;
    }
    const name = card.getAttribute('data-name') || '';
    refreshWorkspaceCardState(card, newState);
    updateWorkspaceEmptyStates(ctx);
    commitWorkspaceState(ctx, card, itemId, newState, prevState, name);
  }

  async function commitWorkspaceState(ctx, card, itemId, nextState, prevState, name){
    if (!itemId) {
      return;
    }
    card.classList.add('workspace-card--updating');
    try {
      await api.updateWorkspaceState(itemId, nextState);
      announceWorkspaceChange(ctx, name, nextState);
    } catch (err) {
      const list = ctx.lists?.[prevState];
      if (list) {
        list.appendChild(card);
      }
      refreshWorkspaceCardState(card, prevState);
      updateWorkspaceEmptyStates(ctx);
      const code = (err && err.code) || '';
      if (code === 'workspace_item_not_found') {
        alert('הפריט לא נמצא לעדכון');
      } else if (code && code !== 'workspace_state_update_failed') {
        alert(code);
      } else {
        alert('שגיאה בעדכון הסטטוס');
      }
    } finally {
      card.classList.remove('workspace-card--updating');
    }
  }

  function announceWorkspaceChange(ctx, name, state){
    if (!ctx || !ctx.liveRegion) {
      return;
    }
    const label = workspaceStateLabel(state);
    const trimmedName = String(name || '').trim();
    ctx.liveRegion.textContent = trimmedName ? `הפריט "${trimmedName}" הועבר לסטטוס ${label}` : `הסטטוס עודכן ל-${label}`;
  }

  function updateWorkspaceEmptyStates(ctx){
    Object.entries(ctx.lists || {}).forEach(([state, listEl]) => {
      const cards = listEl.querySelectorAll('.workspace-card').length;
      listEl.dataset.empty = cards ? '0' : '1';
      const column = listEl.closest('.workspace-column');
      if (column) {
        const countEl = column.querySelector('.workspace-column__count');
        if (countEl) {
          countEl.textContent = String(cards);
        }
      }
    });
  }

  function restoreWorkspaceCardPosition(container, card, index){
    if (!container || !card || !container.insertBefore) {
      return;
    }
    const children = Array.from(container.children || []).filter(el => el !== card);
    if (typeof index === 'number' && index >= 0 && index < children.length) {
      container.insertBefore(card, children[index]);
    } else {
      container.appendChild(card);
    }
  }

  function moveWorkspaceCardToState(ctx, card, targetState){
    if (!ctx || !card) return;
    const itemId = card.getAttribute('data-item-id') || '';
    if (!itemId) return;
    const prevState = card.getAttribute('data-state') || '';
    if (prevState === targetState) {
      announceWorkspaceChange(ctx, card.getAttribute('data-name') || '', targetState);
      return;
    }
    const list = ctx.lists?.[targetState];
    if (!list) return;
    list.appendChild(card);
    refreshWorkspaceCardState(card, targetState);
    updateWorkspaceEmptyStates(ctx);
    commitWorkspaceState(ctx, card, itemId, targetState, prevState, card.getAttribute('data-name') || '');
  }

  function setupWorkspaceKeyboard(ctx){
    if (ctx.cleanup) {
      try { ctx.cleanup(); } catch (_err) {}
    }
    const handler = (ev) => {
      if (!ev.shiftKey) return;
      const lookup = { '1': 'todo', '2': 'in_progress', '3': 'done' };
      const nextState = lookup[ev.key];
      if (!nextState) return;
      if (!workspaceBoardCtx || workspaceBoardCtx !== ctx) return;
      let targetCard = null;
      if (workspaceActiveCard && ctx.board.contains(workspaceActiveCard)) {
        targetCard = workspaceActiveCard;
      } else {
        targetCard = ctx.board.querySelector('.workspace-card');
      }
      if (!targetCard) return;
      ev.preventDefault();
      workspaceActiveCard = targetCard;
      moveWorkspaceCardToState(ctx, targetCard, nextState);
    };
    document.addEventListener('keydown', handler);
    ctx.keyboardHandler = handler;
    ctx.cleanup = () => {
      document.removeEventListener('keydown', handler);
    };
  }

  function teardownWorkspaceBoard(){
    if (workspaceBoardCtx && typeof workspaceBoardCtx.cleanup === 'function') {
      try { workspaceBoardCtx.cleanup(); } catch (_err) {}
    }
    workspaceBoardCtx = null;
    workspaceActiveCard = null;
  }

  function wireDnd(container, cid){
    let dragEl = null;
    container.querySelectorAll('.collection-item').forEach(el => {
      const handle = el.querySelector('.drag');
      if (!handle) return;
      // גרירה מותרת רק מהידית כדי לא לחסום לחיצות על שם הקובץ
      handle.addEventListener('dragstart', (event) => {
        dragEl = el;
        el.classList.add('dragging');
        beginCollectionItemDrag(el, cid, container, 'html');
        if (event && event.dataTransfer) {
          event.dataTransfer.effectAllowed = 'move';
          try {
            event.dataTransfer.setData('text/plain', el.getAttribute('data-name') || '');
          } catch (_err) {}
        }
      });
      handle.addEventListener('dragend', async () => {
        el.classList.remove('dragging');
        if (activeDragContext && activeDragContext.dropInProgress) {
          return;
        }
        clearActiveDragContext();
        // שליחת סדר חדש לשרת
        const order = Array.from(container.querySelectorAll('.collection-item')).map(x => ({
          source: x.getAttribute('data-source')||'regular',
          file_name: x.getAttribute('data-name')||''
        }));
        try{ await api.reorder(cid, order); } catch(_){ /* ignore */ }
      });

      // --- Fallback לתמיכת מסכי מגע באמצעות Pointer Events ---
      // HTML5 Drag & Drop אינו נתמך היטב במכשירי מגע. נשתמש ב-pointer events כדי לאפשר סידור.
      const supportsPointer = 'PointerEvent' in window;
      if (supportsPointer) {
        let pointerDragging = false;
        let moveHandler = null;
        let upHandler = null;
        let activePointerId = null;

        const cleanupPointerListeners = () => {
          window.removeEventListener('pointermove', moveHandler);
          window.removeEventListener('pointerup', upHandler);
          window.removeEventListener('pointercancel', upHandler);
        };

        const onPointerDown = (ev) => {
          // נטפל רק במגע/עט כדי לא לשבש עכבר בדסקטופ
          const type = (ev.pointerType || '').toLowerCase();
          if (type !== 'touch' && type !== 'pen') return;
          try { ev.preventDefault(); } catch(_) {}
          try { handle.setPointerCapture && handle.setPointerCapture(ev.pointerId); } catch(_) {}
          pointerDragging = true;
          activePointerId = ev.pointerId;
          dragEl = el;
          el.classList.add('dragging');
          beginCollectionItemDrag(el, cid, container, 'pointer');
          const prevUserSelect = document.body.style.userSelect;
          document.body.dataset.prevUserSelect = prevUserSelect || '';
          document.body.style.userSelect = 'none';

          moveHandler = (e) => {
            if (!pointerDragging) return;
            if (e.pointerId !== activePointerId) return;
            try { e.preventDefault(); } catch(_) {}
            const clientY = e.clientY;
            const after = getDragAfterElement(container, clientY);
            if (!after) {
              container.appendChild(dragEl);
            } else {
              container.insertBefore(dragEl, after);
            }
            updateSidebarHoverFromPoint(e.clientX, e.clientY);
          };

          upHandler = async (e) => {
            if (!pointerDragging) return;
            if (e.pointerId !== activePointerId) return;
            pointerDragging = false;
            el.classList.remove('dragging');
            try { handle.releasePointerCapture && handle.releasePointerCapture(e.pointerId); } catch(_) {}
            // שחזור בחירת טקסט
            document.body.style.userSelect = document.body.dataset.prevUserSelect || '';
            delete document.body.dataset.prevUserSelect;

            const dropBtn = findSidebarButtonFromPoint(e.clientX, e.clientY);
            const dropId = dropBtn ? (dropBtn.getAttribute('data-id') || '') : '';

            // ניקוי מאזינים
            activePointerId = null;
            cleanupPointerListeners();

            if (dropBtn && canDropOnSidebar(dropId)) {
              try {
                await handleSidebarDropRequest(dropId, dropBtn);
                return;
              } catch (_err) {
                // ניפול חזרה להמשך הלוגיקה כדי להשיב את הפריט למקום
              }
            }

            clearActiveDragContext();

            // שליחת סדר חדש לשרת
            const order = Array.from(container.querySelectorAll('.collection-item')).map(x => ({
              source: x.getAttribute('data-source')||'regular',
              file_name: x.getAttribute('data-name')||''
            }));
            try { await api.reorder(cid, order); } catch(_){ /* ignore */ }
          };

          window.addEventListener('pointermove', moveHandler, { passive: false });
          window.addEventListener('pointerup', upHandler, { passive: false });
          window.addEventListener('pointercancel', upHandler, { passive: false });
        };

        handle.addEventListener('pointerdown', onPointerDown, { passive: false });
      } else {
        // דפדפנים ישנים ללא PointerEvent: שימוש ב-Touch Events כגיבוי
        let touchDragging = false;
        let moveHandler = null;
        let endHandler = null;
        let activeTouchId = null;

        const onTouchStart = (ev) => {
          if (!ev.touches || !ev.touches.length) return;
          try { ev.preventDefault(); } catch(_) {}
          touchDragging = true;
          dragEl = el;
          el.classList.add('dragging');
          beginCollectionItemDrag(el, cid, container, 'touch');
          const prevUserSelect = document.body.style.userSelect;
          document.body.dataset.prevUserSelect = prevUserSelect || '';
          document.body.style.userSelect = 'none';
          // לנעול לזיהוי המגע הראשון שהתחיל את הגרירה
          try {
            activeTouchId = (ev.changedTouches && ev.changedTouches[0] && ev.changedTouches[0].identifier) || ev.touches[0].identifier;
          } catch(_) { activeTouchId = null; }

          moveHandler = (e) => {
            if (!touchDragging) return;
            try { e.preventDefault(); } catch(_) {}
            // מציאת המגע הרלוונטי לפי identifier
            let t = null;
            if (typeof activeTouchId === 'number' || typeof activeTouchId === 'string') {
              const list = e.touches || [];
              for (let i = 0; i < list.length; i++) {
                if (list[i].identifier === activeTouchId) { t = list[i]; break; }
              }
            }
            if (!t) return;
            const clientY = t.clientY;
            const after = getDragAfterElement(container, clientY);
            if (!after) {
              container.appendChild(dragEl);
            } else {
              container.insertBefore(dragEl, after);
            }
            updateSidebarHoverFromPoint(t.clientX, t.clientY);
          };
          endHandler = async (e) => {
            if (!touchDragging) return;
            // נסיים רק כשאותו מזהה מגע השתחרר
            let endedActive = false;
            const cl = e.changedTouches || [];
            let relevantTouch = null;
            for (let i = 0; i < cl.length; i++) {
              if (cl[i].identifier === activeTouchId) { endedActive = true; relevantTouch = cl[i]; break; }
            }
            if (!endedActive) return;
            touchDragging = false;
            el.classList.remove('dragging');
            document.body.style.userSelect = document.body.dataset.prevUserSelect || '';
            delete document.body.dataset.prevUserSelect;

            activeTouchId = null;
            window.removeEventListener('touchmove', moveHandler);
            window.removeEventListener('touchend', endHandler);
            window.removeEventListener('touchcancel', endHandler);

            const dropBtn = relevantTouch ? findSidebarButtonFromPoint(relevantTouch.clientX, relevantTouch.clientY) : null;
            const dropId = dropBtn ? (dropBtn.getAttribute('data-id') || '') : '';
            if (dropBtn && canDropOnSidebar(dropId)) {
              try {
                await handleSidebarDropRequest(dropId, dropBtn);
                return;
              } catch (_err) {
                // במקרה של כשל בהעברה נמשיך להמשך הלוגיקה כדי להשיב את הפריט
              }
            }

            clearActiveDragContext();

            const order = Array.from(container.querySelectorAll('.collection-item')).map(x => ({
              source: x.getAttribute('data-source')||'regular',
              file_name: x.getAttribute('data-name')||''
            }));
            try { await api.reorder(cid, order); } catch(_){ /* ignore */ }
          };

          window.addEventListener('touchmove', moveHandler, { passive: false });
          window.addEventListener('touchend', endHandler);
          window.addEventListener('touchcancel', endHandler);
        };
        handle.addEventListener('touchstart', onTouchStart, { passive: false });
      }
    });
    container.addEventListener('dragover', (e) => {
      e.preventDefault();
      if (!dragEl) return;
      const after = getDragAfterElement(container, e.clientY);
      if (after == null) {
        container.appendChild(dragEl);
      } else {
        container.insertBefore(dragEl, after);
      }
    });
  }

  function getDragAfterElement(container, y){
    const els = [...container.querySelectorAll('.collection-item:not(.dragging)')];
    return els.reduce((closest, child) => {
      const box = child.getBoundingClientRect();
      const offset = y - box.top - box.height / 2;
      if (offset < 0 && offset > closest.offset) {
        return { offset, element: child }
      } else {
        return closest
      }
    }, { offset: Number.NEGATIVE_INFINITY }).element;
  }

  function escapeHtml(s){ const d=document.createElement('div'); d.textContent=String(s||''); return d.innerHTML; }

  // --- התאמת טקסט דינמית לאורכים משתנים ---
  function autoFitText(selector, opts){
    try {
      const { minPx = 12, maxPx = 16 } = opts || {};
      const els = document.querySelectorAll(selector);
      if (!els || !els.length) return;
      els.forEach(el => {
        if (!(el instanceof HTMLElement)) return;
        // שחזור גודל בסיסי אם נשמר, אחרת קבע ושמור
        let base = Number(el.dataset.baseFontPx || '');
        if (!base || Number.isNaN(base)) {
          base = parseFloat(getComputedStyle(el).fontSize) || maxPx;
          el.dataset.baseFontPx = String(base);
        }
        // אפס לגודל בסיס לפני מדידה
        el.style.fontSize = base + 'px';
        // כפייה של חישוב פריסה
        const available = el.clientWidth;
        const needed = el.scrollWidth;
        if (available <= 0) return;
        if (needed <= available) {
          // תוודא שלא עברנו את maxPx
          const current = parseFloat(getComputedStyle(el).fontSize) || base;
          const target = Math.min(Math.max(current, minPx), maxPx);
          el.style.fontSize = target + 'px';
          return;
        }
        const ratio = Math.max(minPx / base, Math.min(1, available / Math.max(1, needed)));
        const next = Math.max(minPx, Math.min(maxPx, Math.floor(base * ratio)));
        el.style.fontSize = next + 'px';
      });
    } catch(_e){ /* ignore */ }
  }

  // תזמון/חסימה של ארועי resize כדי לא להציף חישובים
  function throttle(fn, wait){
    let t = null;
    return function(){
      if (t) return;
      t = setTimeout(() => { t = null; try { fn(); } catch(_){} }, wait);
    }
  }

  // עדכון אוטומטי בהתאמת חלון
  const onResize = throttle(() => {
    autoFitText('#collectionItems .file', { minPx: 12, maxPx: 16 });
    autoFitText('#collectionsSidebar .sidebar-item .name', { minPx: 12, maxPx: 16 });
  }, 150);
  window.addEventListener('resize', onResize);

  // חשיפת API מינימלי לכפתור "הוסף לאוסף"
  window.CollectionsUI = {
    async addFilesToCollection(collectionId, fileNames){
      if (!Array.isArray(fileNames) || !fileNames.length) return {ok:false, error:'אין קבצים'};
      const items = fileNames.map(fn => ({source:'regular', file_name: String(fn)}));
      return api.addItems(String(collectionId), items);
    },
    refreshSidebar: ensureCollectionsSidebar,
  };
  async function initCollectionsPage(){
    const initialId = consumeInitialCollectionId();
    // טען את הסיידבר במקביל לטעינת הפריטים כדי לא "לשרשר" שתי בקשות ברצף בתחילת העמוד.
    const sidebarPromise = ensureCollectionsSidebar().catch(() => {});
    if (!initialId) {
      await sidebarPromise;
      return;
    }
    try {
      await Promise.all([
        sidebarPromise,
        renderCollectionItems(initialId),
      ]);
    } catch (_err) {
      const container = document.getElementById('collectionsContent');
      if (container) {
        container.innerHTML = '<div class="error">האוסף שביקשת לא נמצא</div>';
      }
    }
  }

  // אתחול אוטומטי אם קיימים אזורים בעמוד
  window.addEventListener('DOMContentLoaded', () => {
    initCollectionsPage().catch(() => {});
  });
})();
