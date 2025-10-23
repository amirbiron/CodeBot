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
  };

  async function ensureCollectionsSidebar(){
    const root = document.getElementById('collectionsSidebar');
    if (!root) return;
    root.innerHTML = '<div class="loading">טוען…</div>';
    try {
      const data = await api.listCollections();
      if (!data || !data.ok) throw new Error(data && data.error || 'שגיאה');
      const items = (data.collections||[]).map(c => `
        <button class="sidebar-item" data-id="${c.id}">
          <span class="emoji">${escapeHtml(c.icon||'📂')}</span>
          <span class="name">${escapeHtml(c.name||'ללא שם')}</span>
          <span class="count">${Number(c.items_count||0)}</span>
        </button>
      `).join('');
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
    } catch (e) {
      root.innerHTML = '<div class="error">שגיאה בטעינת האוספים</div>';
    }
  }

  function wireSidebarHandlers(root){
    const list = root.querySelector('#collectionsList');
    const search = root.querySelector('#collectionsSearch');
    const createBtn = root.querySelector('#createCollectionBtn');

    if (createBtn) createBtn.addEventListener('click', async () => {
      const name = prompt('שם האוסף:');
      if (!name) return;
      const res = await api.createCollection({name: name.slice(0,80), mode:'manual'});
      if (!res || !res.ok) return alert(res && res.error || 'שגיאה ביצירה');
      ensureCollectionsSidebar();
    });

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

  async function renderCollectionItems(cid){
    const container = document.getElementById('collectionsContent');
    if (!container) return;
    container.innerHTML = '<div class="loading">טוען…</div>';
    try {
      const data = await api.getItems(cid, 1, 50);
      if (!data || !data.ok) throw new Error(data && data.error || 'שגיאה');
      const items = (data.items||[]).map(it => `
        <div class="collection-item" draggable="true" data-source="${it.source}" data-name="${it.file_name}">
          <span class="drag">⋮⋮</span>
          <a class="file" href="#" data-open="${escapeHtml(it.file_name||'')}">${escapeHtml(it.file_name||'')}</a>
          <button class="remove" title="הסר">✕</button>
        </div>
      `).join('');
      container.innerHTML = items || '<div class="empty">אין פריטים</div>';
      wireDnd(container, cid);
      container.addEventListener('click', async (ev) => {
        const rm = ev.target.closest('.remove');
        const row = ev.target.closest('.collection-item');
        if (rm && row) {
          const source = row.getAttribute('data-source')||'regular';
          const name = row.getAttribute('data-name')||'';
          const res = await api.removeItems(cid, [{source, file_name: name}]);
          if (!res || !res.ok) return alert(res && res.error || 'שגיאה במחיקה');
          row.remove();
        }
        // פתיחת קובץ בלחיצה על שם הקובץ
        const link = ev.target.closest('a.file[data-open]');
        if (link) {
          ev.preventDefault();
          const fname = link.getAttribute('data-open') || '';
          try {
            const r = await fetch(`/api/files/resolve?name=${encodeURIComponent(fname)}`);
            const j = await r.json();
            if (j && j.ok && j.id) {
              window.location.href = `/file/${encodeURIComponent(j.id)}`;
            } else {
              alert('הקובץ לא נמצא לצפייה');
            }
          } catch(_e){ alert('שגיאה בפתיחת הקובץ'); }
        }
      });
    } catch (e) {
      container.innerHTML = '<div class="error">שגיאה בטעינת פריטים</div>';
    }
  }

  function wireDnd(container, cid){
    let dragEl = null;
    container.querySelectorAll('.collection-item').forEach(el => {
      el.addEventListener('dragstart', () => { dragEl = el; el.classList.add('dragging'); });
      el.addEventListener('dragend', async () => {
        el.classList.remove('dragging');
        // שליחת סדר חדש לשרת
        const order = Array.from(container.querySelectorAll('.collection-item')).map(x => ({
          source: x.getAttribute('data-source')||'regular',
          file_name: x.getAttribute('data-name')||''
        }));
        try{ await api.reorder(cid, order); } catch(_){ /* ignore */ }
      });
    });
    container.addEventListener('dragover', (e) => {
      e.preventDefault();
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

  // חשיפת API מינימלי לכפתור "הוסף לאוסף"
  window.CollectionsUI = {
    async addFilesToCollection(collectionId, fileNames){
      if (!Array.isArray(fileNames) || !fileNames.length) return {ok:false, error:'אין קבצים'};
      const items = fileNames.map(fn => ({source:'regular', file_name: String(fn)}));
      return api.addItems(String(collectionId), items);
    },
    refreshSidebar: ensureCollectionsSidebar,
  };

  // אתחול אוטומטי אם קיימים אזורים בעמוד
  window.addEventListener('DOMContentLoaded', () => {
    ensureCollectionsSidebar();
  });
})();
