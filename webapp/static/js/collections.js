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
      // התאמת טקסט דינמית לשמות אוספים ארוכים בסיידבר
      autoFitText('#collectionsSidebar .sidebar-item .name', { minPx: 12, maxPx: 16 });
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

      // התאמת טקסט דינמית לשמות קבצים ארוכים
      autoFitText('#collectionItems .file', { minPx: 12, maxPx: 16 });

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
        if (!confirm('למחוק את האוסף? הפעולה תסיר את האוסף ואת הקישורים שבו, אבל הקבצים עצמם יישארו זמינים בבוט ובקבצים.')) return;
        const res = await api.deleteCollection(cid);
        if (!res || !res.ok) return alert((res && res.error) || 'שגיאה במחיקה');
        ensureCollectionsSidebar();
        container.innerHTML = '<div class="empty">האוסף נמחק. הקבצים נשארים זמינים בבוט ובמסך הקבצים.</div>';
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
          if (!confirm('להסיר את הפריט מהאוסף? הקובץ עצמו יישאר זמין בבוט ובמסך הקבצים.')) return;
          const res = await api.removeItems(cid, [{source, file_name: name}]);
          if (!res || !res.ok) return alert((res && res.error) || 'שגיאה במחיקה');
          row.remove();
          if (!itemsContainer.querySelector('.collection-item')) {
            itemsContainer.innerHTML = '<div class="empty">אין פריטים</div>';
          }
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

      // --- Fallback לתמיכת מסכי מגע באמצעות Pointer Events ---
      // HTML5 Drag & Drop אינו נתמך היטב במכשירי מגע. נשתמש ב-pointer events כדי לאפשר סידור.
      const supportsPointer = 'PointerEvent' in window;
      if (supportsPointer) {
        let pointerDragging = false;
        let moveHandler = null;
        let upHandler = null;
        let activePointerId = null;

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

            // שליחת סדר חדש לשרת
            const order = Array.from(container.querySelectorAll('.collection-item')).map(x => ({
              source: x.getAttribute('data-source')||'regular',
              file_name: x.getAttribute('data-name')||''
            }));
            try { await api.reorder(cid, order); } catch(_) { /* ignore */ }

            // ניקוי מאזינים
            activePointerId = null;
            window.removeEventListener('pointermove', moveHandler);
            window.removeEventListener('pointerup', upHandler);
            window.removeEventListener('pointercancel', upHandler);
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
          };
          endHandler = async (e) => {
            if (!touchDragging) return;
            // נסיים רק כשאותו מזהה מגע השתחרר
            let endedActive = false;
            const cl = e.changedTouches || [];
            for (let i = 0; i < cl.length; i++) {
              if (cl[i].identifier === activeTouchId) { endedActive = true; break; }
            }
            if (!endedActive) return;
            touchDragging = false;
            el.classList.remove('dragging');
            document.body.style.userSelect = document.body.dataset.prevUserSelect || '';
            delete document.body.dataset.prevUserSelect;

            const order = Array.from(container.querySelectorAll('.collection-item')).map(x => ({
              source: x.getAttribute('data-source')||'regular',
              file_name: x.getAttribute('data-name')||''
            }));
            try { await api.reorder(cid, order); } catch(_) { /* ignore */ }

            activeTouchId = null;
            window.removeEventListener('touchmove', moveHandler);
            window.removeEventListener('touchend', endHandler);
            window.removeEventListener('touchcancel', endHandler);
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

  // אתחול אוטומטי אם קיימים אזורים בעמוד
  window.addEventListener('DOMContentLoaded', () => {
    ensureCollectionsSidebar();
  });
})();
