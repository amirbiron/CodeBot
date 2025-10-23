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
      const initialX = (note.position?.x ?? note.position_x ?? 120);
      const initialY = (note.position?.y ?? note.position_y ?? (window.scrollY + 120));
      el.style.left = initialX + 'px';
      el.style.top = initialY + 'px';
      el.style.width = (note.size?.width ?? note.width ?? 260) + 'px';
      el.style.height = (note.size?.height ?? note.height ?? 200) + 'px';
      if (note.color) el.style.backgroundColor = note.color;

      const header = createEl('div', 'sticky-note-header');
      const drag = createEl('div', 'sticky-note-drag');
      const actions = createEl('div', 'sticky-note-actions');
      const minimizeBtn = createEl('button', 'sticky-note-btn', { title: 'מזער' }); minimizeBtn.textContent = '—';
      const deleteBtn = createEl('button', 'sticky-note-btn', { title: 'מחיקה' }); deleteBtn.textContent = '×';
      actions.appendChild(minimizeBtn); actions.appendChild(deleteBtn);
      header.appendChild(drag); header.appendChild(actions);

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
      // אם יש עוגן – תמקם יחסית אליו כבר בהתחלה
      this._positionRelativeToAnchor(el);
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

    _enableDrag(el, handle){
      let startX=0, startY=0, origLeft=0, origTop=0, startScrollX=0, startScrollY=0, dragging=false;
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
      };
      const onMove = (e)=>{
        if (!dragging) return;
        const ev = e.touches ? e.touches[0] : e;
        const dx = ev.clientX - startX; const dy = ev.clientY - startY;
        const sx = window.scrollX - startScrollX; const sy = window.scrollY - startScrollY;
        el.style.left = Math.round(origLeft + dx + sx) + 'px';
        el.style.top = Math.round(origTop + dy + sy) + 'px';
      };
      const onUp = ()=>{
        if (!dragging) return; dragging=false;
        const payload = this._notePayloadFromEl(el);
        this._queueSave(el, payload); this._flushFor(el);
        // לאחר גרירה ידנית – ננתק עוגן אם התרחקנו משמעותית
        try {
          const anchorId = el.dataset.anchorId;
          if (anchorId) {
            const anchor = document.getElementById(anchorId);
            if (anchor) {
              const ay = Math.round(anchor.getBoundingClientRect().top + window.scrollY);
              const y = parseInt(el.style.top||'0',10) || 0;
              if (Math.abs(y - ay) > 300) { delete el.dataset.anchorId; this._queueSave(el, { anchor_id: null, anchor_text: null }); }
            }
          }
        } catch(_) {}
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
            console.warn('sticky note update conflict, changes not applied', id);
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
          console.warn('sticky note update conflict (flush), not applied', id);
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
        if (!anchorId) return;
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
      const vpLeft = vp ? Math.round(vp.offsetLeft + window.scrollX) : window.scrollX;
      const vpTop = vp ? Math.round(vp.offsetTop + window.scrollY) : window.scrollY;
      const maxX = vpLeft + vpW - 20;
      const maxY = vpTop + vpH - 20;
      items.forEach(el => {
        const rect = el.getBoundingClientRect();
        // אם יש עוגן – מצב יחסי אליו קודם
        this._positionRelativeToAnchor(el);
        let x = parseInt(el.style.left || String(Math.round(rect.left + window.scrollX)), 10) || Math.round(rect.left + window.scrollX);
        let y = parseInt(el.style.top || String(Math.round(rect.top + window.scrollY)), 10) || Math.round(rect.top + window.scrollY);
        let w = Math.round(rect.width);
        let h = Math.round(rect.height);
        x = clamp(x, vpLeft, maxX - w);
        y = clamp(y, Math.max(60, vpTop), maxY - h);
        w = clamp(w, 120, 1200); h = clamp(h, 80, 1200);
        el.style.left = x + 'px'; el.style.top = y + 'px'; el.style.width = w + 'px'; el.style.height = h + 'px';
      });
    }
  }

  // Expose
  window.StickyNotesManager = StickyNotesManager;
})();
