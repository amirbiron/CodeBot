/* Sticky Notes frontend for Markdown preview
   - Depends on /api/sticky-notes endpoints
   - Works on md_preview.html where FILE_ID is available in scope
*/
(function(){
  'use strict';

  if (typeof window === 'undefined') return;

  function debounce(fn, wait){
    let t; return function(){ const ctx = this, args = arguments; clearTimeout(t); t = setTimeout(()=>fn.apply(ctx, args), wait); };
  }

  function createEl(tag, className, attrs){
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (attrs) Object.keys(attrs).forEach(k => el.setAttribute(k, attrs[k]));
    return el;
  }

  function clamp(n, min, max){ return Math.min(Math.max(n, min), max); }

  class StickyNotesManager {
    constructor(fileId){
      this.fileId = fileId;
      this.notes = new Map();
      this._saveDebounced = debounce(this._performSaveBatch.bind(this), 400);
      this._pending = new Map();
      this._init();
    }

    async _init(){
      try {
        await this.loadNotes();
        this._createFab();
        window.addEventListener('resize', () => this._reflowWithinViewport());
        window.addEventListener('scroll', () => this._reflowWithinViewport(), { passive: true });
        // במובייל: שינוי visual viewport (מקלדת) עלול להזיז את הפתקים – נתאים אותם לבטיחות
        if (window.visualViewport) {
          const reflow = () => this._reflowWithinViewport();
          try { window.visualViewport.addEventListener('resize', reflow, { passive: true }); } catch(_) { window.visualViewport.addEventListener('resize', reflow); }
          try { window.visualViewport.addEventListener('scroll', reflow, { passive: true }); } catch(_) { window.visualViewport.addEventListener('scroll', reflow); }
        }
      } catch(e){ console.error('StickyNotes init failed', e); }
    }

    async loadNotes(){
      try {
        const resp = await fetch(`/api/sticky-notes/${encodeURIComponent(this.fileId)}`);
        const data = await resp.json();
        if (!data || data.ok === false) return;
        (data.notes || []).forEach(n => this._renderNote(n));
      } catch(e){ console.error('loadNotes error', e); }
    }

    _createFab(){
      const btn = createEl('button', 'sticky-note-fab', { title: 'הוסף פתק' });
      btn.textContent = '+';
      btn.addEventListener('click', () => this.createNote());
      document.body.appendChild(btn);
    }

    _nearestAnchor(){
      try {
        const container = document.getElementById('md-content') || document.body;
        const headers = Array.from(container.querySelectorAll('h1, h2, h3, h4, h5, h6'));
        if (!headers.length) return null;
        const targetY = window.scrollY + Math.min(160, Math.round((window.innerHeight || 600) * 0.25));
        let best = null; let bestDy = Infinity;
        for (const h of headers) {
          const y = Math.round(h.getBoundingClientRect().top + window.scrollY);
          const dy = Math.abs(y - targetY);
          if (dy < bestDy) { bestDy = dy; best = h; }
        }
        if (!best) return null;
        const id = best.id || '';
        const text = (best.textContent || '').trim().slice(0, 120);
        return id ? { id, text, y: Math.round(best.getBoundingClientRect().top + window.scrollY) } : null;
      } catch(_) { return null; }
    }

    async createNote(){
      try {
        const isMobile = (typeof window !== 'undefined') && ((window.matchMedia && window.matchMedia('(max-width: 480px)').matches) || (window.innerWidth <= 480));
        const anchor = this._nearestAnchor();
        const payload = {
          content: '',
          // הנחתה קלה למובייל כדי למנוע קפיצה עם הופעת מקלדת
          position: { x: isMobile ? 80 : 120, y: window.scrollY + (isMobile ? 80 : 120) },
          size: { width: isMobile ? 200 : 260, height: isMobile ? 160 : 200 },
          color: '#FFFFCC',
          line_start: null,
          anchor_id: anchor ? anchor.id : undefined,
          anchor_text: anchor ? anchor.text : undefined
        };
        const resp = await fetch(`/api/sticky-notes/${encodeURIComponent(this.fileId)}`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
        });
        const data = await resp.json();
        if (!data || data.ok === false) return;
        const note = Object.assign({ id: data.id, file_id: this.fileId }, payload, { is_minimized: false, created_at: null, updated_at: null });
        this._renderNote(note, true);
      } catch(e){ console.error('createNote error', e); }
    }

    _renderNote(note, focus){
      const el = createEl('div', 'sticky-note');
      el.dataset.noteId = note.id;
      if (note.anchor_id) el.dataset.anchorId = String(note.anchor_id);
      // קביעת מיקום התחלתי – אם יש עוגן נשתמש בו, אחרת לפי שמור
      const initialX = (typeof note.position?.x === 'number') ? note.position.x : (note.position_x ?? 120);
      const initialY = (typeof note.position?.y === 'number') ? note.position.y : (note.position_y ?? (window.scrollY + 120));
      note.position = note.position && typeof note.position === 'object' ? note.position : {};
      if (typeof note.position.x !== 'number') note.position.x = initialX;
      if (typeof note.position.y !== 'number') note.position.y = initialY;
      note.size = note.size && typeof note.size === 'object' ? note.size : {};
      if (typeof note.size.width !== 'number') note.size.width = note.width ?? 260;
      if (typeof note.size.height !== 'number') note.size.height = note.height ?? 200;
      el.style.left = note.position.x + 'px';
      el.style.top = note.position.y + 'px';
      el.style.width = note.size.width + 'px';
      el.style.height = note.size.height + 'px';
      if (note.color) el.style.backgroundColor = note.color;

      const header = createEl('div', 'sticky-note-header');
      const drag = createEl('div', 'sticky-note-drag');
      const actions = createEl('div', 'sticky-note-actions');
      const pinBtn = createEl('button', 'sticky-note-btn sticky-note-pin', { title: 'הצמד/בטל עיגון לכותרת', 'aria-pressed': note.anchor_id ? 'true' : 'false' }); pinBtn.textContent = '📌';
      const minimizeBtn = createEl('button', 'sticky-note-btn', { title: 'מזער' }); minimizeBtn.textContent = '—';
      const deleteBtn = createEl('button', 'sticky-note-btn', { title: 'מחיקה' }); deleteBtn.textContent = '×';
      actions.appendChild(pinBtn); actions.appendChild(minimizeBtn); actions.appendChild(deleteBtn);
      header.appendChild(drag); header.appendChild(actions);
      pinBtn.addEventListener('click', (ev) => {
        try { ev.stopPropagation(); ev.preventDefault(); } catch(_) {}
        this._toggleAnchor(el);
      });

      const textarea = createEl('textarea', 'sticky-note-content');
      textarea.value = note.content || '';

      const resizer = createEl('div', 'sticky-note-resize');

      el.appendChild(header);
      el.appendChild(textarea);
      el.appendChild(resizer);
      document.body.appendChild(el);

      if (note.is_minimized) el.classList.add('is-minimized');

      // interactions
      this._enableDrag(el, drag);
      this._enableResize(el, resizer);
      // בעת פוקוס, הצמד לעוגן (במיוחד במובייל בעת הופעת מקלדת)
      textarea.addEventListener('focus', () => {
        try { this._positionRelativeToAnchor(el); this._reflowWithinViewport(el); } catch(_){ }
      });

      textarea.addEventListener('input', () => {
        this._queueSave(el, { content: textarea.value });
      });
      textarea.addEventListener('blur', () => this._flushFor(el));

      minimizeBtn.addEventListener('click', (ev) => {
        try { ev.stopPropagation(); ev.preventDefault(); } catch(_) {}
        const nowMin = !el.classList.contains('is-minimized');
        el.classList.toggle('is-minimized');
        this._queueSave(el, { is_minimized: nowMin });
        this._flushFor(el);
      });
      deleteBtn.addEventListener('click', async () => {
        if (!confirm('למחוק את הפתק?')) return;
        await this._deleteNoteEl(el);
      });

      if (focus) try { textarea.focus(); } catch(_) {}
      if (note.updated_at) { try { el.dataset.updatedAt = String(note.updated_at); } catch(_) {} }
      this.notes.set(note.id, { el, data: note });
      this._applyPositionMode(el, note, { initial: true });
      this._reflowWithinViewport(el);
      return el;
    }

    _notePayloadFromEl(el){
      const rect = el.getBoundingClientRect();
      const x = Math.round(rect.left + window.scrollX);
      const y = Math.round(rect.top + window.scrollY);
      const w = Math.round(rect.width);
      const h = Math.round(rect.height);
      const payload = { position: { x, y }, size: { width: w, height: h } };
      return payload;
    }

    _getEntry(el){
      if (!el || !el.dataset) return null;
      const id = el.dataset.noteId;
      if (!id) return null;
      return this.notes.get(id) || null;
    }

    _updatePinButtonState(el, isPinned){
      const pinBtn = el ? el.querySelector('.sticky-note-pin') : null;
      if (!pinBtn) return;
      const active = !!isPinned;
      pinBtn.classList.toggle('is-active', active);
      pinBtn.setAttribute('aria-pressed', active ? 'true' : 'false');
      pinBtn.title = active ? 'בטל נעיצה' : 'הצמד לכותרת';
    }

    _applyPositionMode(el, note, opts){
      try {
        if (!el || !note) return;
        const isPinned = !!(note.anchor_id);
        if (isPinned) {
          el.classList.add('is-pinned');
          el.classList.remove('is-floating');
          el.style.position = 'absolute';
          const targetX = (typeof note.position?.x === 'number') ? note.position.x : parseInt(el.style.left || '120', 10) || 120;
          const targetY = (typeof note.position?.y === 'number') ? note.position.y : parseInt(el.style.top || String(window.scrollY + 120), 10) || (window.scrollY + 120);
          el.style.left = targetX + 'px';
          el.style.top = targetY + 'px';
          if (note.anchor_id) {
            el.dataset.anchorId = String(note.anchor_id);
          }
          if (!(opts && opts.skipAnchorSnap)) {
            this._positionRelativeToAnchor(el);
          }
        } else {
          el.classList.add('is-floating');
          el.classList.remove('is-pinned');
          el.style.position = 'fixed';
          if (el.dataset && el.dataset.anchorId) { delete el.dataset.anchorId; }
          const width = (typeof note.size?.width === 'number') ? note.size.width : (parseInt(el.style.width || '260', 10) || 260);
          const height = (typeof note.size?.height === 'number') ? note.size.height : (parseInt(el.style.height || '200', 10) || 200);
          let left = (typeof note.position?.x === 'number') ? note.position.x - window.scrollX : parseInt(el.style.left || '120', 10) || 120;
          let top = (typeof note.position?.y === 'number') ? note.position.y - window.scrollY : parseInt(el.style.top || String(window.scrollY + 120), 10) || (window.scrollY + 120);
          const vp = window.visualViewport;
          const vpW = Math.max(100, (vp ? vp.width : window.innerWidth) || window.innerWidth || 320);
          const vpH = Math.max(100, (vp ? vp.height : window.innerHeight) || window.innerHeight || 320);
          const maxLeft = Math.max(12, vpW - width - 12);
          const maxTop = Math.max(60, vpH - height - 20);
          left = clamp(Math.round(left), 12, maxLeft);
          top = clamp(Math.round(top), 60, maxTop);
          el.style.left = left + 'px';
          el.style.top = top + 'px';
          if (!opts || opts.reflow !== false) {
            this._reflowWithinViewport(el);
          }
        }
        this._updatePinButtonState(el, isPinned);
      } catch(e) {
        console.warn('sticky note: applyPositionMode failed', e);
      }
    }

    _isPinned(el){
      const entry = this._getEntry(el);
      const anchorId = entry && entry.data ? (entry.data.anchor_id || '') : '';
      const ds = el && el.dataset ? (el.dataset.anchorId || '') : '';
      return !!(ds || anchorId);
    }

    _pinNote(el, anchor){
      const entry = this._getEntry(el);
      if (!entry) return;
      const payload = this._notePayloadFromEl(el);
      entry.data.position = payload.position;
      entry.data.size = payload.size;
      const anchorId = (anchor && anchor.id) ? anchor.id : '__manual__';
      const anchorText = (anchor && anchor.text) ? anchor.text : '';
      entry.data.anchor_id = anchorId;
      entry.data.anchor_text = anchorText;
      el.dataset.anchorId = anchorId;
      this._applyPositionMode(el, entry.data, { reflow: false, skipAnchorSnap: true });
      const requestPayload = Object.assign({}, payload, { anchor_id: anchorId, anchor_text: anchorText || null });
      this._queueSave(el, requestPayload);
      this._flushFor(el);
    }

    _unpinNote(el){
      const entry = this._getEntry(el);
      if (!entry) return;
      const payload = this._notePayloadFromEl(el);
      entry.data.position = payload.position;
      entry.data.size = payload.size;
      entry.data.anchor_id = '';
      entry.data.anchor_text = '';
      if (el.dataset && el.dataset.anchorId) { delete el.dataset.anchorId; }
      this._applyPositionMode(el, entry.data, { reflow: true });
      this._queueSave(el, Object.assign({}, payload, { anchor_id: null, anchor_text: null }));
      this._flushFor(el);
    }

    _syncEntryFromFragment(id, fragment){
      const entry = this.notes.get(id);
      if (!entry || !fragment) return;
      if (fragment.position && typeof fragment.position === 'object') {
        entry.data.position = Object.assign({}, entry.data.position || {}, fragment.position);
      }
      if (fragment.size && typeof fragment.size === 'object') {
        entry.data.size = Object.assign({}, entry.data.size || {}, fragment.size);
      }
      if (Object.prototype.hasOwnProperty.call(fragment, 'anchor_id')) {
        const val = fragment.anchor_id;
        entry.data.anchor_id = (val === null || val === undefined || val === '') ? '' : String(val);
      }
      if (Object.prototype.hasOwnProperty.call(fragment, 'anchor_text')) {
        const val = fragment.anchor_text;
        entry.data.anchor_text = val ? String(val) : '';
      }
      if (Object.prototype.hasOwnProperty.call(fragment, 'is_minimized')) {
        entry.data.is_minimized = !!fragment.is_minimized;
      }
    }

    _enableDrag(el, handle){
      let startX=0, startY=0, origLeft=0, origTop=0, startScrollX=0, startScrollY=0, dragging=false;
      let pressTimer=null, longPressHandled=false;
      const LONG_PRESS_MS = 450;
      const onDown = (e)=>{
        dragging = true;
        const ev = e.touches ? e.touches[0] : e;
        startX = ev.clientX; startY = ev.clientY;
        const r = el.getBoundingClientRect();
        // חשב מיקום מוחלט בדף בעת התחלת גרירה כדי למנוע "קפיצה" במובייל
        const parsedLeft = parseInt(el.style.left || '', 10);
        const parsedTop = parseInt(el.style.top || '', 10);
        origLeft = Number.isFinite(parsedLeft) ? parsedLeft : Math.round(r.left + window.scrollX);
        origTop = Number.isFinite(parsedTop) ? parsedTop : Math.round(r.top + window.scrollY);
        startScrollX = window.scrollX; startScrollY = window.scrollY;
        try { e.preventDefault(); } catch(_) {}
        longPressHandled = false;
        try { clearTimeout(pressTimer); } catch(_) {}
        pressTimer = setTimeout(() => {
          longPressHandled = true;
          // Toggle anchor on long-press without starting a drag
          this._toggleAnchor(el);
          dragging = false;
        }, LONG_PRESS_MS);
      };
      const onMove = (e)=>{
        if (!dragging) return;
        const ev = e.touches ? e.touches[0] : e;
        const dx = ev.clientX - startX; const dy = ev.clientY - startY;
        if (Math.abs(dx) > 6 || Math.abs(dy) > 6) { try { clearTimeout(pressTimer); } catch(_) {} }
        const sx = window.scrollX - startScrollX; const sy = window.scrollY - startScrollY;
        el.style.left = Math.round(origLeft + dx + sx) + 'px';
        el.style.top = Math.round(origTop + dy + sy) + 'px';
      };
      const onUp = ()=>{
        try { clearTimeout(pressTimer); } catch(_) {}
        if (!dragging) { dragging=false; return; }
        if (longPressHandled) { dragging=false; return; }
        dragging=false;
        const payload = this._notePayloadFromEl(el);
        let handled = false;
        try {
          const anchorId = el.dataset.anchorId;
          if (anchorId && anchorId !== '__manual__') {
            const anchor = document.getElementById(anchorId);
            if (anchor) {
              const ay = Math.round(anchor.getBoundingClientRect().top + window.scrollY);
              if (Math.abs(payload.position.y - ay) > 300) {
                this._unpinNote(el);
                handled = true;
              }
            }
          }
        } catch(_) {}
        if (!handled) {
          this._queueSave(el, payload);
          this._flushFor(el);
        }
      };
      // מניעת מחוות ברירת מחדל במובייל
      try { handle.style.touchAction = 'none'; } catch(_) {}
      handle.addEventListener('mousedown', onDown);
      window.addEventListener('mousemove', onMove, { passive: false });
      window.addEventListener('mouseup', onUp);
      handle.addEventListener('touchstart', onDown, { passive: false });
      window.addEventListener('touchmove', onMove, { passive: false });
      window.addEventListener('touchend', onUp);
    }
    _toggleAnchor(el){
      try {
        if (!el) return;
        if (this._isPinned(el)) {
          this._unpinNote(el);
          return;
        }
        const anchor = this._nearestAnchor();
        this._pinNote(el, anchor);
      } catch(e) {
        console.warn('sticky note: toggle pin failed', e);
      }
    }

    _enableResize(el, handle){
      let startX=0, startY=0, startW=0, startH=0, resizing=false;
      const onDown = (e)=>{
        resizing = true;
        const ev = e.touches ? e.touches[0] : e;
        startX = ev.clientX; startY = ev.clientY;
        const r = el.getBoundingClientRect();
        startW = r.width; startH = r.height;
        try { e.preventDefault(); } catch(_) {}
      };
      const onMove = (e)=>{
        if (!resizing) return;
        const ev = e.touches ? e.touches[0] : e;
        const dw = ev.clientX - startX; const dh = ev.clientY - startY;
        const nw = clamp(Math.round(startW + dw), 120, 1200);
        const nh = clamp(Math.round(startH + dh), 80, 1200);
        el.style.width = nw + 'px'; el.style.height = nh + 'px';
      };
      const onUp = ()=>{
        if (!resizing) return; resizing=false;
        const payload = this._notePayloadFromEl(el);
        this._queueSave(el, payload); this._flushFor(el);
      };
      try { handle.style.touchAction = 'none'; } catch(_) {}
      handle.addEventListener('mousedown', onDown);
      window.addEventListener('mousemove', onMove, { passive: false });
      window.addEventListener('mouseup', onUp);
      handle.addEventListener('touchstart', onDown, { passive: false });
      window.addEventListener('touchmove', onMove, { passive: false });
      window.addEventListener('touchend', onUp);
    }

    _queueSave(el, fragment){
      const id = el.dataset.noteId;
      const pending = Object.assign({}, this._pending.get(id) || {}, fragment || {});
      // צירוף חותמת זמן קודמת למניעת דריסת שינויים בין מכשירים
      try {
        if (!('prev_updated_at' in pending)) {
          const prev = el.dataset.updatedAt;
          if (prev) pending.prev_updated_at = prev;
        }
      } catch(_) {}
      this._pending.set(id, pending);
      this._syncEntryFromFragment(id, pending);
      this._saveDebounced();
    }

    async _performSaveBatch(){
      const entries = Array.from(this._pending.entries());
      this._pending.clear();
      for (const [id, data] of entries){
        try {
          const resp = await fetch(`/api/sticky-notes/note/${encodeURIComponent(id)}`, {
            method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data)
          });
          let j = null; try { j = await resp.json(); } catch(_) {}
          if (resp.status === 409) {
            console.warn('sticky note update conflict, retrying once with fresh timestamp', id);
            // עדכן חותמת זמן אחרונה שהשרת החזיר, ונסה עוד פעם אחת
            if (j && j.updated_at) {
              const item = this.notes.get(id);
              if (item && item.el) { try { item.el.dataset.updatedAt = String(j.updated_at); } catch(_) {} }
              try {
                const retryPayload = Object.assign({}, data, { prev_updated_at: String(j.updated_at) });
                const retryResp = await fetch(`/api/sticky-notes/note/${encodeURIComponent(id)}`, {
                  method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(retryPayload)
                });
                let rj = null; try { rj = await retryResp.json(); } catch(_) {}
                if (retryResp.status === 409) {
                  console.warn('sticky note update conflict persisted after retry', id);
                } else if (rj && rj.updated_at) {
                  if (item && item.el) { try { item.el.dataset.updatedAt = String(rj.updated_at); } catch(_) {} }
                }
              } catch(e) { console.warn('sticky note retry failed', id, e); }
            }
            continue;
          }
          if (j && j.updated_at) {
            const item = this.notes.get(id);
            if (item && item.el) { try { item.el.dataset.updatedAt = String(j.updated_at); } catch(_) {} }
          }
        } catch(e){ console.warn('save note failed', id, e); }
      }
    }

    async _flushFor(el){
      const id = el.dataset.noteId;
      const data = this._pending.get(id);
      if (!data) return;
      this._pending.delete(id);
      try {
        const resp = await fetch(`/api/sticky-notes/note/${encodeURIComponent(id)}`, {
          method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data)
        });
        let j = null; try { j = await resp.json(); } catch(_) {}
        if (resp.status === 409) {
          console.warn('sticky note update conflict (flush) – retrying once', id);
          if (j && j.updated_at) { try { el.dataset.updatedAt = String(j.updated_at); } catch(_) {} }
          // נסה מיד עוד פעם אחת עם חותמת זמן מעודכנת
          try {
            const retryPayload = Object.assign({}, data, { prev_updated_at: (j && j.updated_at) ? String(j.updated_at) : (el.dataset.updatedAt || undefined) });
            const retryResp = await fetch(`/api/sticky-notes/note/${encodeURIComponent(id)}`, {
              method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(retryPayload)
            });
            let rj = null; try { rj = await retryResp.json(); } catch(_) {}
            if (retryResp.status === 409) {
              console.warn('sticky note update conflict persisted after flush retry', id);
              return;
            }
            if (rj && rj.updated_at) { try { el.dataset.updatedAt = String(rj.updated_at); } catch(_) {} }
          } catch(e) {
            console.warn('flush retry failed', id, e);
          }
          return;
        }
        if (j && j.updated_at) { try { el.dataset.updatedAt = String(j.updated_at); } catch(_) {} }
      } catch(e){ console.warn('flush save failed', id, e); }
    }

    async _deleteNoteEl(el){
      const id = el.dataset.noteId;
      try { await fetch(`/api/sticky-notes/note/${encodeURIComponent(id)}`, { method: 'DELETE' }); } catch(e) { console.warn('delete failed', id, e); }
      try { el.remove(); } catch(_) {}
      this.notes.delete(id);
    }

    _positionRelativeToAnchor(el){
      try {
        const anchorId = el?.dataset?.anchorId;
        if (!anchorId || anchorId === '__manual__') return;
        if (!el.classList || !el.classList.contains('is-pinned')) return;
        const anchor = document.getElementById(anchorId);
        if (!anchor) return;
        const rect = anchor.getBoundingClientRect();
        const anchorTop = Math.round(rect.top + window.scrollY);
        const desiredTop = clamp(anchorTop + 12, 60, Math.max(100, (window.visualViewport ? window.visualViewport.height : window.innerHeight) - 20) + window.scrollY);
        // שמור X קיים אבל הגבל בתוך viewport הנוכחי
        const currentLeft = parseInt(el.style.left || '120', 10) || 120;
        el.style.top = desiredTop + 'px';
        el.style.left = currentLeft + 'px';
      } catch(_) { }
    }

    _reflowWithinViewport(target){
      const items = target ? [target] : Array.from(document.querySelectorAll('.sticky-note'));
      const vp = window.visualViewport;
      const vpW = Math.max(100, (vp ? vp.width : window.innerWidth) || window.innerWidth || 320);
      const vpH = Math.max(100, (vp ? vp.height : window.innerHeight) || window.innerHeight || 320);
      const minLeft = 12;
      const minTop = 60;
      items.forEach(el => {
        if (!el || !(el instanceof HTMLElement)) return;
        if (el.classList.contains('is-pinned')) {
          this._positionRelativeToAnchor(el);
          return;
        }
        const rect = el.getBoundingClientRect();
        let x = parseInt(el.style.left || String(Math.round(rect.left)), 10);
        if (!Number.isFinite(x)) x = Math.round(rect.left);
        let y = parseInt(el.style.top || String(Math.round(rect.top)), 10);
        if (!Number.isFinite(y)) y = Math.round(rect.top);
        let w = Math.round(rect.width);
        let h = Math.round(rect.height);
        const maxLeft = Math.max(minLeft, vpW - w - minLeft);
        const maxTop = Math.max(minTop, vpH - h - 20);
        x = clamp(x, minLeft, maxLeft);
        y = clamp(y, minTop, maxTop);
        w = clamp(w, 120, 1200); h = clamp(h, 80, 1200);
        el.style.left = x + 'px';
        el.style.top = y + 'px';
        el.style.width = w + 'px';
        el.style.height = h + 'px';
      });
    }
  }

  // Expose
  window.StickyNotesManager = StickyNotesManager;
})();
