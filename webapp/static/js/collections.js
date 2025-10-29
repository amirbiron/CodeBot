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
      const [colRes, data] = await Promise.all([
        api.getCollection(cid),
        api.getItems(cid, 1, 200),
      ]);
      if (!data || !data.ok) throw new Error((data && data.error) || 'שגיאה');
      if (!colRes || !colRes.ok) throw new Error((colRes && colRes.error) || 'שגיאה');
      const col = colRes.collection || {};

      const itemsHtml = (data.items||[]).map(it => `
        <div class="collection-item" data-source="${it.source}" data-name="${it.file_name}">
          <span class="drag" draggable="true">⋮⋮</span>
          <a class="file" href="#" draggable="false" data-open="${escapeHtml(it.file_name||'')}">${escapeHtml(it.file_name||'')}</a>
          <button class="pin ${it.pinned ? 'pinned' : ''}" title="${it.pinned ? 'בטל הצמדה' : 'הצמד'}">📌</button>
          <button class="remove" title="הסר">✕</button>
        </div>
      `).join('');

      container.innerHTML = `
        <div class="collection-header">
          <div class="title">${escapeHtml(col.name || 'ללא שם')}</div>
          <div class="actions">
            <button class="btn btn-secondary rename">שנה שם</button>
            <button class="btn btn-danger delete">מחק</button>
          </div>
        </div>
        <div class="collection-items" id="collectionItems">${itemsHtml || '<div class="empty">אין פריטים</div>'}</div>
      `;

      const itemsContainer = container.querySelector('#collectionItems');
      wireDnd(itemsContainer, cid);

      // Header actions
      const renameBtn = container.querySelector('.collection-header .rename');
      const deleteBtn = container.querySelector('.collection-header .delete');
      if (renameBtn) renameBtn.addEventListener('click', async () => {
        const current = String(col.name || '');
        const name = prompt('שם חדש לאוסף:', current);
        if (!name) return;
        const res = await api.updateCollection(cid, { name: name.slice(0, 80) });
        if (!res || !res.ok) return alert((res && res.error) || 'שגיאה בעדכון שם');
        ensureCollectionsSidebar();
        await renderCollectionItems(cid);
      });
      if (deleteBtn) deleteBtn.addEventListener('click', async () => {
        if (!confirm('למחוק את האוסף? פעולה זו תסיר גם את הפריטים המשויכים.')) return;
        const res = await api.deleteCollection(cid);
        if (!res || !res.ok) return alert((res && res.error) || 'שגיאה במחיקה');
        ensureCollectionsSidebar();
        container.innerHTML = '<div class="empty">האוסף נמחק</div>';
      });

      // Items actions (remove, open, pin)
      itemsContainer.addEventListener('click', async (ev) => {
        const row = ev.target.closest('.collection-item');
        if (!row) return;
        const source = row.getAttribute('data-source')||'regular';
        const name = row.getAttribute('data-name')||'';

        // Remove item
        const rm = ev.target.closest('.remove');
        if (rm) {
          const res = await api.removeItems(cid, [{source, file_name: name}]);
          if (!res || !res.ok) return alert((res && res.error) || 'שגיאה במחיקה');
          row.remove();
          return;
        }

        // Pin/unpin
        const pinBtn = ev.target.closest('.pin');
        if (pinBtn) {
          const nextPinned = !pinBtn.classList.contains('pinned');
          const res = await api.addItems(cid, [{source, file_name: name, pinned: nextPinned}]);
          if (!res || !res.ok) return alert((res && res.error) || 'שגיאה בעדכון הצמדה');
          await renderCollectionItems(cid);
          return;
        }

        // Open file by clicking the name or row (except drag handle and buttons)
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
    } catch (e) {
      container.innerHTML = '<div class="error">שגיאה בטעינת פריטים</div>';
    }
  }

  // פתיחת קובץ לפי שם הקובץ (שימושי גם ללחיצה על כל השורה)
  async function openFileByName(fname){
    const name = String(fname || '').trim();
    if (!name) return;
    try {
      const r = await fetch(`/api/files/resolve?name=${encodeURIComponent(name)}`);
      const j = await r.json();
      if (j && j.ok && j.id) {
        window.location.href = `/file/${encodeURIComponent(j.id)}`;
      } else {
        alert('הקובץ לא נמצא לצפייה');
      }
    } catch(_e){
      alert('שגיאה בפתיחת הקובץ');
    }
  }

  function wireDnd(container, cid){
    let dragEl = null;
    container.querySelectorAll('.collection-item').forEach(el => {
      const handle = el.querySelector('.drag');
      if (!handle) return;
      // גרירה מותרת רק מהידית כדי לא לחסום לחיצות על שם הקובץ
      handle.addEventListener('dragstart', () => { dragEl = el; el.classList.add('dragging'); });
      handle.addEventListener('dragend', async () => {
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
