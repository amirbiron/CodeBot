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

    async createNote(){
      try {
        const payload = {
          content: '',
          position: { x: 120, y: window.scrollY + 120 },
          size: { width: 260, height: 200 },
          color: '#FFFFCC',
          line_start: null
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
      el.style.left = (note.position?.x ?? note.position_x ?? 120) + 'px';
      el.style.top = (note.position?.y ?? note.position_y ?? (window.scrollY + 120)) + 'px';
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

      textarea.addEventListener('input', () => {
        this._queueSave(el, { content: textarea.value });
      });
      textarea.addEventListener('blur', () => this._flushFor(el));

      minimizeBtn.addEventListener('click', () => {
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
      this.notes.set(note.id, { el, data: note });
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
      let startX=0, startY=0, origX=0, origY=0, dragging=false;
      const onDown = (e)=>{
        dragging = true;
        const ev = e.touches ? e.touches[0] : e;
        startX = ev.clientX; startY = ev.clientY;
        const r = el.getBoundingClientRect();
        origX = r.left; origY = r.top;
        e.preventDefault();
      };
      const onMove = (e)=>{
        if (!dragging) return;
        const ev = e.touches ? e.touches[0] : e;
        const dx = ev.clientX - startX; const dy = ev.clientY - startY;
        el.style.left = Math.round(origX + dx + window.scrollX) + 'px';
        el.style.top = Math.round(origY + dy + window.scrollY) + 'px';
      };
      const onUp = ()=>{
        if (!dragging) return; dragging=false;
        const payload = this._notePayloadFromEl(el);
        this._queueSave(el, payload); this._flushFor(el);
      };
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
        e.preventDefault();
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
      this._pending.set(id, pending);
      this._saveDebounced();
    }

    async _performSaveBatch(){
      const entries = Array.from(this._pending.entries());
      this._pending.clear();
      for (const [id, data] of entries){
        try {
          await fetch(`/api/sticky-notes/note/${encodeURIComponent(id)}`, {
            method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data)
          });
        } catch(e){ console.warn('save note failed', id, e); }
      }
    }

    async _flushFor(el){
      const id = el.dataset.noteId;
      const data = this._pending.get(id);
      if (!data) return;
      this._pending.delete(id);
      try {
        await fetch(`/api/sticky-notes/note/${encodeURIComponent(id)}`, {
          method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data)
        });
      } catch(e){ console.warn('flush save failed', id, e); }
    }

    async _deleteNoteEl(el){
      const id = el.dataset.noteId;
      try { await fetch(`/api/sticky-notes/note/${encodeURIComponent(id)}`, { method: 'DELETE' }); } catch(e) { console.warn('delete failed', id, e); }
      try { el.remove(); } catch(_) {}
      this.notes.delete(id);
    }

    _reflowWithinViewport(target){
      const items = target ? [target] : Array.from(document.querySelectorAll('.sticky-note'));
      const maxX = Math.max(100, window.innerWidth - 40);
      const maxY = Math.max(100, window.innerHeight - 40 + window.scrollY);
      items.forEach(el => {
        const rect = el.getBoundingClientRect();
        let x = Math.round(rect.left + window.scrollX);
        let y = Math.round(rect.top + window.scrollY);
        let w = Math.round(rect.width);
        let h = Math.round(rect.height);
        x = clamp(x, 0, maxX - 20); y = clamp(y, 60, maxY - 20);
        w = clamp(w, 120, 1200); h = clamp(h, 80, 1200);
        el.style.left = x + 'px'; el.style.top = y + 'px'; el.style.width = w + 'px'; el.style.height = h + 'px';
      });
    }
  }

  // Expose
  window.StickyNotesManager = StickyNotesManager;
})();
