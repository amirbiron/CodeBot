/* Sticky Notes frontend for Markdown preview
   - Depends on /api/sticky-notes endpoints
   - Works on md_preview.html where FILE_ID is available in scope
*/
(function(){
  'use strict';

  if (typeof window === 'undefined') return;

  function debounce(fn, wait){
    let t = null;
    let lastArgs = [];
    let lastContext = null;
    const invoke = () => {
      const ctx = lastContext;
      const args = lastArgs;
      lastArgs = [];
      lastContext = null;
      return fn.apply(ctx, args);
    };
    const debounced = function(...args){
      lastArgs = args;
      lastContext = this;
      if (t) { clearTimeout(t); }
      t = setTimeout(() => {
        t = null;
        invoke();
      }, wait);
    };
    debounced.flush = function(){
      if (!t) return undefined;
      clearTimeout(t);
      t = null;
      return invoke();
    };
    debounced.cancel = function(){
      if (t) { clearTimeout(t); t = null; }
      lastArgs = [];
      lastContext = null;
    };
    return debounced;
  }

  function createEl(tag, className, attrs){
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (attrs) Object.keys(attrs).forEach(k => el.setAttribute(k, attrs[k]));
    return el;
  }

  function clamp(n, min, max){ return Math.min(Math.max(n, min), max); }

  function getScrollOffsets(){
    if (typeof window === 'undefined') return { x: 0, y: 0 };
    const doc = window.document || {};
    const docEl = doc.documentElement || {};
    const body = doc.body || {};
    const scrollingEl = doc.scrollingElement || {};
    const vv = window.visualViewport || null;

    const pick = (values) => {
      for (const val of values) {
        if (typeof val === 'number' && Number.isFinite(val) && Math.abs(val) > 0.5) {
          return val;
        }
      }
      for (const val of values) {
        if (typeof val === 'number' && Number.isFinite(val)) {
          return val;
        }
      }
      return 0;
    };

    const xCandidates = [
      window.scrollX,
      window.pageXOffset,
      scrollingEl ? scrollingEl.scrollLeft : undefined,
      docEl ? docEl.scrollLeft : undefined,
      body ? body.scrollLeft : undefined,
      vv ? vv.pageLeft : undefined,
      vv ? vv.offsetLeft : undefined,
    ];
    const yCandidates = [
      window.scrollY,
      window.pageYOffset,
      scrollingEl ? scrollingEl.scrollTop : undefined,
      docEl ? docEl.scrollTop : undefined,
      body ? body.scrollTop : undefined,
      vv ? vv.pageTop : undefined,
      vv ? vv.offsetTop : undefined,
    ];

    return { x: pick(xCandidates), y: pick(yCandidates) };
  }
  const PIN_SENTINEL = '__pinned__';
  const AUTO_SAVE_DEBOUNCE_MS = 500;
  const AUTO_SAVE_FORCE_INTERVAL_MS = 3500;
  const CACHE_TTL_MS = 24 * 60 * 60 * 1000; // 24h

  class StickyNotesManager {
    constructor(fileId){
      this.fileId = fileId;
      this.notes = new Map();
      this._saveDebounced = debounce(this._performSaveBatch.bind(this), AUTO_SAVE_DEBOUNCE_MS);
      this._pending = new Map();
      this._inFlight = new Map();
      this._autoFlushTimer = null;
      this._autoFlushBusy = false;
      this._lineIndex = new Map(); // lineNumber -> pageY
      this._cacheKey = `sticky-notes:${String(fileId)}`;
      this._renderedFromCache = false;
      this._pendingSeq = new Map(); // noteId -> monotonic version of pending edits
      this._init();
    }

    async _init(){
      try {
        this._rebuildLineIndex();
        this._loadCacheAndRender();
        await this.loadNotes();
        this._createFab();
        window.addEventListener('resize', () => { this._rebuildLineIndex(); this._reflowWithinViewport(); this._updateAnchoredPositions(); });
        window.addEventListener('scroll', () => { this._reflowWithinViewport(); this._updateAnchoredPositions(); }, { passive: true });
        // במובייל: שינוי visual viewport (מקלדת) עלול להזיז את הפתקים – נתאים אותם לבטיחות
        if (window.visualViewport) {
          const reflow = () => this._reflowWithinViewport();
          try { window.visualViewport.addEventListener('resize', reflow, { passive: true }); } catch(_) { window.visualViewport.addEventListener('resize', reflow); }
          try { window.visualViewport.addEventListener('scroll', reflow, { passive: true }); } catch(_) { window.visualViewport.addEventListener('scroll', reflow); }
        }
        this._setupLifecycleGuards();
        this._setupDomObservers();
      } catch(e){ console.error('StickyNotes init failed', e); }
    }

    async loadNotes(){
      try {
        const url = `/api/sticky-notes/${encodeURIComponent(this.fileId)}?_=${Date.now()}`;
        const resp = await fetch(url, { cache: 'no-store', headers: { 'Cache-Control': 'no-cache' } });
        const data = await resp.json();
        if (!data || data.ok === false) return;
        // החלף תוכן מהרשימה העדכנית מהשרת
        const fresh = Array.isArray(data.notes) ? data.notes : [];
        this._clearAllNotes();
        fresh.forEach(n => this._renderNote(n));
        this._saveCache(fresh);
      } catch(e){ console.error('loadNotes error', e); }
    }

    _createFab(){
      const btn = createEl('button', 'sticky-note-fab', { title: 'הוסף פתק' });
      btn.textContent = '+';
      btn.addEventListener('click', () => this.createNote());
      document.body.appendChild(btn);
    }

    _setupLifecycleGuards(){
      if (this._didSetupLifecycleGuards) return;
      this._didSetupLifecycleGuards = true;
      const flush = () => {
        try {
          this._flushPendingKeepalive();
        } catch(err) {
          console.warn('sticky note: lifecycle keepalive flush failed', err);
        }
        try {
          this._flushDebounceTimer();
        } catch(err) {
          console.warn('sticky note: lifecycle debounce flush failed', err);
        }
      };
      try {
        window.addEventListener('beforeunload', flush, { capture: true });
      } catch(_) {
        window.addEventListener('beforeunload', flush);
      }
      try {
        window.addEventListener('pagehide', (ev) => {
          try {
            if (ev && typeof ev.persisted === 'boolean' && ev.persisted) return;
          } catch(_) {}
          flush();
        }, { capture: true });
      } catch(_) {
        window.addEventListener('pagehide', () => flush());
      }
      try {
        document.addEventListener('visibilitychange', () => {
          try {
            if (document.visibilityState === 'hidden') flush();
          } catch(_) {
            flush();
          }
        });
      } catch(_) {}
    }

    _nearestAnchor(){
      try {
        const container = document.getElementById('md-content') || document.body;
        const headers = Array.from(container.querySelectorAll('h1, h2, h3, h4, h5, h6'));
        if (!headers.length) return null;
        const scroll = getScrollOffsets();
        const targetY = scroll.y + Math.min(160, Math.round((window.innerHeight || 600) * 0.25));
        let best = null; let bestDy = Infinity;
        for (const h of headers) {
          const y = Math.round(h.getBoundingClientRect().top + scroll.y);
          const dy = Math.abs(y - targetY);
          if (dy < bestDy) { bestDy = dy; best = h; }
        }
        if (!best) return null;
        const id = best.id || '';
        const text = (best.textContent || '').trim().slice(0, 120);
        return id ? { id, text, y: Math.round(best.getBoundingClientRect().top + scroll.y) } : null;
      } catch(_) { return null; }
    }

    async createNote(){
      try {
        const isMobile = (typeof window !== 'undefined') && ((window.matchMedia && window.matchMedia('(max-width: 480px)').matches) || (window.innerWidth <= 480));
        const scroll = getScrollOffsets();
        const payload = {
          content: '',
          // הנחתה קלה למובייל כדי למנוע קפיצה עם הופעת מקלדת
          position: { x: isMobile ? 80 : 120, y: scroll.y + (isMobile ? 80 : 120) },
          size: { width: isMobile ? 200 : 260, height: isMobile ? 160 : 200 },
          color: '#FFFFCC',
          line_start: null,
          // חזרה להתנהגות הישנה: ללא עיגון לכותרות כברירת מחדל
          anchor_id: '',
          anchor_text: undefined
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
      if (note.anchor_id === PIN_SENTINEL) {
        el.dataset.pinned = 'true';
      }
        // קביעת מיקום התחלתי – אם יש עוגן נשתמש בו, אחרת לפי שמור
        let initialX = (typeof note.position?.x === 'number') ? note.position.x : null;
        if (!Number.isFinite(initialX)) {
          initialX = (typeof note.position_x === 'number') ? note.position_x : 120;
        }
        let initialY = (typeof note.position?.y === 'number') ? note.position.y : null;
        if (!Number.isFinite(initialY)) {
          if (typeof note.position_y === 'number') {
            initialY = note.position_y;
          } else {
            initialY = getScrollOffsets().y + 120;
          }
        }
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
      const isPinnedInitial = note.anchor_id === PIN_SENTINEL;
      const pinBtn = createEl('button', 'sticky-note-btn sticky-note-pin', { title: 'הצמד/בטל נעיצה', 'aria-pressed': isPinnedInitial ? 'true' : 'false' }); pinBtn.textContent = '📌';
      const minimizeBtn = createEl('button', 'sticky-note-btn', { title: 'מזער' }); minimizeBtn.textContent = '—';
      const remindBtn = createEl('button', 'sticky-note-btn', { title: 'קבע תזכורת' }); remindBtn.textContent = '🔔';
      const deleteBtn = createEl('button', 'sticky-note-btn', { title: 'מחיקה' }); deleteBtn.textContent = '×';
      actions.appendChild(pinBtn); actions.appendChild(remindBtn); actions.appendChild(minimizeBtn); actions.appendChild(deleteBtn);
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
      if (isPinnedInitial) el.classList.add('is-pinned');

      // interactions
      this._enableDrag(el, drag);
      this._enableResize(el, resizer);
      textarea.addEventListener('focus', () => {
        try {
          if (!this._isPinned(el)) {
            this._reflowWithinViewport(el);
          }
        } catch(_){ }
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
      remindBtn.addEventListener('click', (ev) => {
        try { ev.stopPropagation(); ev.preventDefault(); } catch(_) {}
        this._openReminderModal(el);
      });

      if (focus) try { textarea.focus(); } catch(_) {}
      if (note.updated_at) { try { el.dataset.updatedAt = String(note.updated_at); } catch(_) {} }
      this.notes.set(note.id, { el, data: note });
      this._applyPositionMode(el, note, { initial: true });
      this._reflowWithinViewport(el);
      this._updateAnchoredNotePosition(el, note);
      return el;
    }

    _openReminderModal(el){
      try {
        // Prevent duplicate stacked modals
        const existing = document.querySelector('.sticky-reminder-modal');
        if (existing) {
          try { existing.focus && existing.focus(); } catch(_) {}
          return;
        }
        const id = el && el.dataset ? el.dataset.noteId : '';
        if (!id) return;
        const modal = document.createElement('div');
        modal.className = 'sticky-reminder-modal';
        modal.innerHTML = (
          '<div class="sticky-reminder-backdrop"></div>'+
          '<div class="sticky-reminder-card">'+
          '  <div class="sticky-reminder-header">'+
          '    <div class="sticky-reminder-title">⏰ תזכורת לפתק</div>'+
          '    <button class="sticky-reminder-close" title="סגור">×</button>'+
          '  </div>'+
          '  <div class="sticky-reminder-body">'+
          '    <div class="sticky-reminder-section">'+
          '      <div class="sticky-reminder-subtitle">תזמון מהיר</div>'+
          '      <div class="sticky-reminder-grid">'+
          '        <button data-preset="1h" class="sr-btn">עוד שעה</button>'+
          '        <button data-preset="3h" class="sr-btn">עוד 3 שעות</button>'+
          '        <button data-preset="today-21" class="sr-btn">היום ב-21:00</button>'+
          '        <button data-preset="tomorrow-09" class="sr-btn">מחר ב-9:00</button>'+
          '        <button data-preset="24h" class="sr-btn">עוד 24 שעות</button>'+
          '        <button data-preset="1w" class="sr-btn">עוד שבוע</button>'+
          '      </div>'+
          '    </div>'+
          '    <div class="sticky-reminder-section">'+
          '      <div class="sticky-reminder-subtitle">בחירה מלוח שנה</div>'+
          '      <div class="sticky-reminder-row">'+
          '        <input type="datetime-local" class="sr-dt" />'+
          '        <button class="sr-save">שמירה</button>'+
          '      </div>'+
          '    </div>'+
          '  </div>'+
          '</div>'
        );
        const close = () => { try { modal.remove(); } catch(_) {} };
        modal.querySelector('.sticky-reminder-backdrop').addEventListener('click', close);
        modal.querySelector('.sticky-reminder-close').addEventListener('click', close);
        const tz = (Intl && Intl.DateTimeFormat && Intl.DateTimeFormat().resolvedOptions ? (Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Jerusalem') : 'Asia/Jerusalem');
        modal.querySelectorAll('.sr-btn').forEach(btn => {
          btn.addEventListener('click', async () => {
            const preset = btn.getAttribute('data-preset');
            const ok = await this._postReminder(id, { preset, tz });
            if (ok) {
              close();
              alert('✅ התזכורת נשמרה');
            }
          });
        });
        modal.querySelector('.sr-save').addEventListener('click', async () => {
          const input = modal.querySelector('.sr-dt');
          const at = input && input.value ? String(input.value) : '';
          if (!at) { alert('בחר תאריך ושעה'); return; }
          const ok = await this._postReminder(id, { at, tz });
          if (ok) {
            close();
            alert('✅ התזכורת נשמרה');
          }
        });
        document.body.appendChild(modal);
      } catch(err){ console.warn('open reminder modal failed', err); }
    }

    async _postReminder(noteId, payload){
      try {
        const url = `/api/sticky-notes/note/${encodeURIComponent(noteId)}/reminder`;
        const r = await fetch(url, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload || {}) });
        const j = await r.json().catch(()=>null);
        if (!r.ok || !j || j.ok === false) {
          alert((j && j.error) ? String(j.error) : 'שגיאה בשמירת התזכורת');
          return false;
        }
        return true;
      } catch(err){ console.warn('post reminder failed', err); }
      return false;
    }

      _notePayloadFromEl(el){
        const rect = el.getBoundingClientRect();
        const scroll = getScrollOffsets();
        const x = Math.round(rect.left + scroll.x);
        const y = Math.round(rect.top + scroll.y);
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
      pinBtn.title = active ? 'בטל נעיצה' : 'נעץ פתק למסמך';
    }

      _applyPositionMode(el, note, opts){
        try {
          if (!el || !note) return;
          const scroll = getScrollOffsets();
          const rect = el.getBoundingClientRect();
          const currentAbsX = Math.round(rect.left + scroll.x);
          const currentAbsY = Math.round(rect.top + scroll.y);
          const currentViewportX = Math.round(rect.left);
          const currentViewportY = Math.round(rect.top);
          const isPinned = note.anchor_id === PIN_SENTINEL;
          const isAnchored = !!(note.anchor_id && note.anchor_id !== PIN_SENTINEL) || (Number.isInteger(note.line_start) && note.line_start > 0);
          if (isPinned) {
            el.classList.add('is-pinned');
            el.classList.remove('is-floating');
            el.style.position = 'absolute';
            let targetX = (typeof note.position?.x === 'number') ? note.position.x : currentAbsX;
            let targetY = (typeof note.position?.y === 'number') ? note.position.y : currentAbsY;
            if (!Number.isFinite(targetX)) targetX = currentAbsX;
            if (!Number.isFinite(targetY)) targetY = currentAbsY;
            el.style.left = targetX + 'px';
            el.style.top = targetY + 'px';
            el.dataset.pinned = 'true';
            if (el.dataset && el.dataset.anchorId) { delete el.dataset.anchorId; }
            if (el.dataset && el.dataset.anchorLine) { delete el.dataset.anchorLine; }
            if (el.dataset && el.dataset.relYOffset) { delete el.dataset.relYOffset; }
          } else if (isAnchored) {
            el.classList.add('is-pinned');
            el.classList.remove('is-floating');
            el.style.position = 'absolute';
            let targetX = (typeof note.position?.x === 'number') ? note.position.x : currentAbsX;
            if (!Number.isFinite(targetX)) targetX = currentAbsX;
            el.style.left = targetX + 'px';
            if (el.dataset && el.dataset.pinned) { delete el.dataset.pinned; }
            if (note.anchor_id && note.anchor_id !== PIN_SENTINEL) {
              el.dataset.anchorId = String(note.anchor_id);
            } else if (Number.isInteger(note.line_start) && note.line_start > 0) {
              el.dataset.anchorLine = String(note.line_start);
            }
            // החישוב בפועל של top ייעשה ע"י _updateAnchoredNotePosition
          } else {
            el.classList.add('is-floating');
            el.classList.remove('is-pinned');
            el.style.position = 'fixed';
            if (el.dataset && el.dataset.pinned) { delete el.dataset.pinned; }
            const width = (typeof note.size?.width === 'number') ? note.size.width : (parseInt(el.style.width || '260', 10) || 260);
            const height = (typeof note.size?.height === 'number') ? note.size.height : (parseInt(el.style.height || '200', 10) || 200);
            let left = (typeof note.position?.x === 'number') ? note.position.x - scroll.x : currentViewportX;
            let top = (typeof note.position?.y === 'number') ? note.position.y - scroll.y : currentViewportY;
            if (!Number.isFinite(left)) left = currentViewportX;
            if (!Number.isFinite(top)) top = currentViewportY;
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
      if (anchorId === PIN_SENTINEL) return true;
      return !!(el && el.dataset && el.dataset.pinned === 'true');
    }

    _pinNote(el){
      const entry = this._getEntry(el);
      if (!entry) return;
      const payload = this._notePayloadFromEl(el);
      entry.data.position = payload.position;
      entry.data.size = payload.size;
      entry.data.anchor_id = PIN_SENTINEL;
      entry.data.anchor_text = '';
      entry.data.line_start = null;
      entry.data.line_end = null;
      if (el.dataset) {
        if (el.dataset.anchorLine) { delete el.dataset.anchorLine; }
        if (el.dataset.relYOffset) { delete el.dataset.relYOffset; }
      }
      this._applyPositionMode(el, entry.data, { reflow: false });
      const requestPayload = Object.assign({}, payload, { anchor_id: PIN_SENTINEL, anchor_text: null, line_start: null, line_end: null });
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
      entry.data.line_start = null;
      entry.data.line_end = null;
      if (el.dataset && el.dataset.pinned) { delete el.dataset.pinned; }
      if (el.dataset && el.dataset.anchorId) { delete el.dataset.anchorId; }
      if (el.dataset && el.dataset.anchorLine) { delete el.dataset.anchorLine; }
      if (el.dataset && el.dataset.relYOffset) { delete el.dataset.relYOffset; }
      this._applyPositionMode(el, entry.data, { reflow: true });
      this._queueSave(el, Object.assign({}, payload, { anchor_id: null, anchor_text: null, line_start: null, line_end: null }));
      this._flushFor(el);
    }

    _syncEntryFromFragment(id, fragment){
      const entry = this.notes.get(id);
      if (!entry || !fragment) return;
      if (Object.prototype.hasOwnProperty.call(fragment, 'content')) {
        entry.data.content = fragment.content;
      }
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
        const scroll = getScrollOffsets();
        const isAbsolute = el.classList ? el.classList.contains('is-pinned') : false;
        const fallbackLeft = Math.round(r.left + (isAbsolute ? scroll.x : 0));
        const fallbackTop = Math.round(r.top + (isAbsolute ? scroll.y : 0));
        origLeft = Number.isFinite(parsedLeft) ? parsedLeft : fallbackLeft;
        origTop = Number.isFinite(parsedTop) ? parsedTop : fallbackTop;
        startScrollX = scroll.x; startScrollY = scroll.y;
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
        const scroll = getScrollOffsets();
        const sx = scroll.x - startScrollX; const sy = scroll.y - startScrollY;
        el.style.left = Math.round(origLeft + dx + sx) + 'px';
        el.style.top = Math.round(origTop + dy + sy) + 'px';
      };
      const onUp = ()=>{
        try { clearTimeout(pressTimer); } catch(_) {}
        if (!dragging) { dragging=false; return; }
        if (longPressHandled) { dragging=false; return; }
        dragging=false;
        const payload = this._notePayloadFromEl(el);
        const wasPinned = this._isPinned(el);
        const entry = this._getEntry(el);
        if (entry) {
          entry.data.position = payload.position;
          entry.data.size = payload.size;
        }
        if (wasPinned) {
          this._queueSave(el, Object.assign({}, payload, { anchor_id: PIN_SENTINEL, anchor_text: null }));
        } else {
          this._queueSave(el, payload);
        }
        this._flushFor(el);
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
        // חזרה להתנהגות הישנה: נעיצה מיידית למיקום מוחלט
        this._pinNote(el);
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
      // advance per-note pending version to avoid dropping newer edits after batch
      try {
        const nextSeq = (this._pendingSeq.get(id) || 0) + 1;
        this._pendingSeq.set(id, nextSeq);
      } catch(_) {}
      this._saveDebounced();
      this._ensureBackgroundAutoFlush();
    }

    _flushPendingKeepalive(){
      try {
        const combined = new Map();
        try {
          if (this._pending && this._pending.size) {
            for (const [id, data] of this._pending.entries()) {
              if (data) combined.set(id, data);
            }
          }
        } catch(_) {}
        try {
          if (this._inFlight && this._inFlight.size) {
            for (const [id, info] of this._inFlight.entries()) {
              if (info && info.data && !combined.has(id)) {
                combined.set(id, info.data);
              }
            }
          }
        } catch(_) {}
        if (!combined.size) return;
        for (const [id, data] of combined.entries()){
          try {
            if (!data) continue;
            const body = JSON.stringify(data);
            if (typeof fetch === 'function') {
              try {
                fetch(`/api/sticky-notes/note/${encodeURIComponent(id)}`, {
                  method: 'PUT',
                  headers: { 'Content-Type': 'application/json' },
                  body,
                  keepalive: true,
                }).catch(()=>{});
              } catch(e) {
                console.warn('sticky note: keepalive request failed', id, e);
              }
            }
          } catch(err) {
            console.warn('sticky note: keepalive serialization failed', id, err);
          }
        }
      } catch(_) {
        return;
      }
    }

    _clonePayload(data){
      if (!data || typeof data !== 'object') return data;
      try {
        return JSON.parse(JSON.stringify(data));
      } catch(_) {
        const shallow = Object.assign({}, data);
        try {
          if (data.position && typeof data.position === 'object') {
            shallow.position = Object.assign({}, data.position);
          }
        } catch(_) {}
        try {
          if (data.size && typeof data.size === 'object') {
            shallow.size = Object.assign({}, data.size);
          }
        } catch(_) {}
        return shallow;
      }
    }

    _registerInFlight(id, data, promise){
      let snapshot = null;
      try {
        snapshot = this._clonePayload(data);
      } catch(_) {
        snapshot = data;
      }
      this._inFlight.set(id, { data: snapshot, promise });
      if (promise && typeof promise.finally === 'function') {
        promise.finally(() => {
          const current = this._inFlight.get(id);
          if (current && current.promise === promise) {
            this._inFlight.delete(id);
            if ((!this._pending || this._pending.size === 0) && (!this._inFlight || this._inFlight.size === 0)) {
              this._stopBackgroundAutoFlush();
            }
          }
        });
      }
    }

    _setNoteUpdatedAt(id, iso){
      if (!iso) return;
      const entry = this.notes.get(id);
      if (!entry) return;
      if (entry.el) {
        try { entry.el.dataset.updatedAt = String(iso); } catch(_) {}
      }
      if (entry.data && typeof entry.data === 'object') {
        try { entry.data.updated_at = iso; } catch(_) {}
      }
    }

    _mergePending(id, fragment){
      if (!id || !fragment) return;
      const existing = this._pending.get(id);
      let next;
      if (existing) {
        next = this._clonePayload(existing) || {};
        const fragmentClone = this._clonePayload(fragment) || {};
        Object.assign(next, fragmentClone);
      } else {
        next = this._clonePayload(fragment);
      }
      this._pending.set(id, next);
      this._syncEntryFromFragment(id, next);
      try { this._saveDebounced(); } catch(_) {}
      this._ensureBackgroundAutoFlush();
    }

    _sendUpdate(id, data){
      const payload = this._clonePayload(data) || {};
      const url = `/api/sticky-notes/note/${encodeURIComponent(id)}`;
      const send = async (payloadObj) => {
        const resp = await fetch(url, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payloadObj),
          keepalive: true,
        });
        let json = null;
        try { json = await resp.json(); } catch(_) {}
        return { resp, json };
      };

      const attempt = async () => {
        try {
          const { resp, json } = await send(payload);
          if (resp.status === 409) {
            console.warn('sticky note update conflict, retrying once with fresh timestamp', id);
            let serverUpdatedAt = null;
            if (json && json.updated_at) {
              serverUpdatedAt = String(json.updated_at);
              this._setNoteUpdatedAt(id, serverUpdatedAt);
            }
            if (serverUpdatedAt) {
              const retryPayload = Object.assign({}, payload, { prev_updated_at: serverUpdatedAt });
              try {
                const { resp: retryResp, json: retryJson } = await send(retryPayload);
                if (retryResp.status === 409) {
                  console.warn('sticky note update conflict persisted after retry', id);
                  if (retryJson && retryJson.updated_at) {
                    this._setNoteUpdatedAt(id, String(retryJson.updated_at));
                    this._mergePending(id, Object.assign({}, retryPayload, { prev_updated_at: String(retryJson.updated_at) }));
                  } else if (serverUpdatedAt) {
                    this._mergePending(id, Object.assign({}, retryPayload));
                  }
                  return false;
                }
                if (retryJson && retryJson.updated_at) {
                  this._setNoteUpdatedAt(id, String(retryJson.updated_at));
                }
                return true;
              } catch(retryErr) {
                console.warn('sticky note retry failed', id, retryErr);
                this._mergePending(id, Object.assign({}, retryPayload));
                return false;
              }
            }
            this._mergePending(id, Object.assign({}, payload, serverUpdatedAt ? { prev_updated_at: serverUpdatedAt } : {}));
            return false;
          }
          if (json && json.updated_at) {
            this._setNoteUpdatedAt(id, String(json.updated_at));
          }
          if (!resp.ok) {
            this._mergePending(id, Object.assign({}, payload));
          }
          return resp.ok;
        } catch(err) {
          console.warn('save note failed', id, err);
          this._mergePending(id, Object.assign({}, payload));
          return false;
        }
      };

      const promise = attempt();
      this._registerInFlight(id, payload, promise);
      return promise;
    }

    async _performSaveBatch(){
      try {
        if (!this._pending || this._pending.size === 0) {
          if (!this._inFlight || this._inFlight.size === 0) {
            this._stopBackgroundAutoFlush();
          }
          return;
        }
      } catch(_) {}
      const entries = Array.from(this._pending.entries());
      // capture snapshot with versions to avoid dropping newer edits queued during flight
      const snapshots = entries.map(([id, fragment]) => ({
        id: String(id),
        seq: (this._pendingSeq.get(String(id)) || 0),
        payload: this._clonePayload(fragment) || {}
      }));
      const batchPayload = snapshots.map(s => Object.assign({ id: s.id }, s.payload));
      const url = `/api/sticky-notes/batch`;
      let usedBatch = false;
      try {
        const resp = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ updates: batchPayload }),
          keepalive: true,
        });
        if (resp.ok) {
          const json = await resp.json().catch(() => null);
          if (json && json.ok && Array.isArray(json.results)) {
            usedBatch = true;
            for (const result of json.results) {
              const id = String(result.id || '');
              if (!id) continue;
              const snap = snapshots.find(s => s.id === id) || null;
              const currentSeq = (this._pendingSeq.get(id) || 0);
              if (result.ok) {
                if (result.updated_at) { this._setNoteUpdatedAt(id, String(result.updated_at)); }
                // clear pending only if no newer edits arrived during request
                if (snap && currentSeq === snap.seq) {
                  this._pending.delete(id);
                }
              } else if (Number(result.status) === 409) {
                // conflict – set prev_updated_at for next retry without overriding newer local edits
                const patch = {};
                if (result.updated_at) patch.prev_updated_at = String(result.updated_at);
                this._mergePending(id, patch);
              } else {
                // failure – keep pending (no-op). Ensure we still retain the last snapshot if nothing newer exists
                if (snap && currentSeq === snap.seq) {
                  this._mergePending(id, Object.assign({}, snap.payload));
                }
              }
            }
          }
        }
      } catch(err) {
        // ignore, will fallback to single updates below
      }
      if (!usedBatch) {
        // Fallback to per-note PUT
        for (const [id] of entries){
          const current = this._pending.get(id);
          if (!current) continue;
          this._pending.delete(id);
          const didSucceed = await this._sendUpdate(id, current);
          if (!didSucceed && !this._pending.has(id)) {
            // במקרה של כישלון המידע הוחזר ל-pending בתוך _sendUpdate
          }
        }
      }
      if ((!this._pending || this._pending.size === 0) && (!this._inFlight || this._inFlight.size === 0)) {
        this._stopBackgroundAutoFlush();
      }
    }

    async _flushFor(el){
      const id = el.dataset.noteId;
      const data = this._pending.get(id);
      if (!data) {
        const existingFlight = this._inFlight.get(id);
        if (existingFlight && existingFlight.promise && typeof existingFlight.promise.then === 'function') {
          try { await existingFlight.promise; } catch(_) {}
        }
        return;
      }
      this._pending.delete(id);
      await this._sendUpdate(id, data);
      if ((!this._pending || this._pending.size === 0) && (!this._inFlight || this._inFlight.size === 0)) {
        this._stopBackgroundAutoFlush();
      }
    }

    _ensureBackgroundAutoFlush(){
      try {
        if (this._autoFlushTimer) return;
        this._autoFlushTimer = setInterval(() => {
          this._runAutoFlushTick();
        }, AUTO_SAVE_FORCE_INTERVAL_MS);
      } catch(err) {
        console.warn('sticky note: failed to start auto flush interval', err);
      }
    }

      _stopBackgroundAutoFlush(){
        if (!this._autoFlushTimer) return;
        if ((this._pending && this._pending.size > 0) || (this._inFlight && this._inFlight.size > 0)) return;
      try {
        clearInterval(this._autoFlushTimer);
      } catch(_) {}
      this._autoFlushTimer = null;
      this._autoFlushBusy = false;
    }

    _flushDebounceTimer(){
      if (!this._saveDebounced) return;
      try {
        let maybePromise = null;
        if (typeof this._saveDebounced.flush === 'function') {
          maybePromise = this._saveDebounced.flush();
        }
        const isPromise = maybePromise && typeof maybePromise.then === 'function';
        if (!isPromise && this._pending && this._pending.size > 0) {
          maybePromise = this._performSaveBatch();
        }
        if (maybePromise && typeof maybePromise.then === 'function') {
          maybePromise.catch(err => console.warn('sticky note: flush promise rejected', err));
        }
      } catch(err) {
        console.warn('sticky note: debounce flush failed', err);
      }
    }

    _runAutoFlushTick(){
      try {
        if (this._autoFlushBusy) return;
        if (!this._pending || this._pending.size === 0) {
          this._stopBackgroundAutoFlush();
          return;
        }
        this._autoFlushBusy = true;
        let op = null;
        try {
          if (this._saveDebounced && typeof this._saveDebounced.flush === 'function') {
            op = this._saveDebounced.flush();
          }
          if ((!op || typeof op.then !== 'function') && this._pending && this._pending.size > 0) {
            op = this._performSaveBatch();
          }
        } catch(err) {
          console.warn('sticky note: auto flush invoke failed', err);
          this._autoFlushBusy = false;
          return;
        }
        if (op && typeof op.then === 'function') {
          op.catch(err => console.warn('sticky note: auto flush promise failed', err))
            .finally(() => {
              this._autoFlushBusy = false;
              if (!this._pending || this._pending.size === 0) {
                this._stopBackgroundAutoFlush();
              }
            });
        } else {
          this._autoFlushBusy = false;
          if (!this._pending || this._pending.size === 0) {
            this._stopBackgroundAutoFlush();
          }
        }
      } catch(err) {
        console.warn('sticky note: auto flush tick failed', err);
        this._autoFlushBusy = false;
      }
    }

    async _deleteNoteEl(el){
      const id = el.dataset.noteId;
      try { await fetch(`/api/sticky-notes/note/${encodeURIComponent(id)}`, { method: 'DELETE' }); } catch(e) { console.warn('delete failed', id, e); }
      try { el.remove(); } catch(_) {}
      this.notes.delete(id);
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

    _setupDomObservers(){
      try {
        const md = document.getElementById('md-content');
        if (!md || typeof MutationObserver === 'undefined') return;
        const obs = new MutationObserver(() => { try { this._rebuildLineIndex(); this._updateAnchoredPositions(); } catch(_) {} });
        obs.observe(md, { childList: true, subtree: true, characterData: true });
        this._domObserver = obs;
      } catch(_) {}
    }

    _rebuildLineIndex(){
      try {
        this._lineIndex = new Map();
        const md = document.getElementById('md-content') || document;
        const sel = '.highlighttable .linenos pre > span, .highlighttable .linenos pre > a, .linenodiv pre > span, .linenodiv pre > a, .linenos span, .linenos a';
        const nodes = Array.from(md.querySelectorAll(sel));
        const scroll = getScrollOffsets();
        nodes.forEach((node) => {
          const ln = this._extractLineNumberFromNode(node);
          if (!ln) return;
          const y = Math.round(node.getBoundingClientRect().top + scroll.y);
          if (!this._lineIndex.has(ln)) this._lineIndex.set(ln, y);
        });
      } catch(_) {}
    }

    _extractLineNumberFromNode(node){
      try {
        const text = (node && node.textContent ? node.textContent.trim() : '');
        let num = parseInt(text, 10);
        if (Number.isFinite(num) && num > 0) return num;
        const href = node && node.getAttribute ? node.getAttribute('href') : null;
        if (href) {
          let m = href.match(/#(?:L|line-?)(\d+)$/i);
          if (!m) m = href.match(/#(\d+)$/);
          if (m) {
            num = parseInt(m[1], 10);
            if (Number.isFinite(num) && num > 0) return num;
          }
        }
        // fallback to index in parent
        const p = node && node.parentElement;
        if (p) {
          const idx = Array.from(p.children).indexOf(node);
          if (idx >= 0) return idx + 1;
        }
      } catch(_) {}
      return null;
    }

    _getYForLine(lineNum){
      if (!Number.isInteger(lineNum) || lineNum <= 0) return null;
      if (this._lineIndex && this._lineIndex.has(lineNum)) return this._lineIndex.get(lineNum);
      try {
        const sel = `.highlighttable .linenos pre > span:nth-child(${lineNum}), .highlighttable .linenos pre > a:nth-child(${lineNum}), .linenodiv pre > span:nth-child(${lineNum}), .linenodiv pre > a:nth-child(${lineNum}), .linenos span:nth-child(${lineNum}), .linenos a:nth-child(${lineNum})`;
        const node = document.querySelector(sel);
        if (node) {
          const scroll = getScrollOffsets();
          return Math.round(node.getBoundingClientRect().top + scroll.y);
        }
      } catch(_) {}
      return null;
    }

    _getYForAnchor(anchorId){
      try {
        if (!anchorId) return null;
        const md = document.getElementById('md-content') || document;
        let el = md.querySelector(`#${CSS.escape(anchorId)}`);
        if (!el) el = document.getElementById(anchorId);
        if (el) {
          const scroll = getScrollOffsets();
          return Math.round(el.getBoundingClientRect().top + scroll.y);
        }
      } catch(_) {}
      return null;
    }

    _currentVisibleLine(){
      try {
        const md = document.getElementById('md-content') || document;
        const sel = '.highlighttable .linenos pre > span, .highlighttable .linenos pre > a, .linenodiv pre > span, .linenodiv pre > a, .linenos span, .linenos a';
        const nodes = Array.from(md.querySelectorAll(sel));
        if (!nodes.length) return null;
        const scroll = getScrollOffsets();
        const mid = scroll.y + Math.round((window.innerHeight || 600) * 0.5);
        let best = null; let bestDy = Infinity;
        nodes.forEach((node) => {
          const ln = this._extractLineNumberFromNode(node);
          if (!ln) return;
          const y = Math.round(node.getBoundingClientRect().top + scroll.y);
          const dy = Math.abs(y - mid);
          if (dy < bestDy) { bestDy = dy; best = ln; }
        });
        return best;
      } catch(_) { return null; }
    }

    _updateAnchoredNotePosition(el, note){
      try {
        const entry = this._getEntry(el);
        const data = entry ? entry.data : (note || null);
        if (!data) return;
        let anchorY = null;
        if (Number.isInteger(data.line_start) && data.line_start > 0) {
          anchorY = this._getYForLine(data.line_start);
        } else if (data.anchor_id && data.anchor_id !== PIN_SENTINEL) {
          anchorY = this._getYForAnchor(data.anchor_id);
        }
        if (anchorY == null) return;
        let rel = 0;
        try {
          if (el.dataset && typeof el.dataset.relYOffset !== 'undefined') {
            rel = parseInt(el.dataset.relYOffset || '0', 10) || 0;
          } else {
            const targetY = (typeof data.position?.y === 'number') ? data.position.y : (parseInt(el.style.top || '0', 10) || 0);
            rel = Math.round(targetY - anchorY);
            if (el.dataset) el.dataset.relYOffset = String(rel);
          }
        } catch(_) {}
        el.style.top = (anchorY + rel) + 'px';
      } catch(_) {}
    }

    _updateAnchoredPositions(){
      try {
        for (const [id, entry] of this.notes.entries()){
          if (!entry || !entry.el || !entry.data) continue;
          const d = entry.data;
          const isAnchored = (Number.isInteger(d.line_start) && d.line_start > 0) || (d.anchor_id && d.anchor_id !== PIN_SENTINEL);
          if (!isAnchored) continue;
          this._updateAnchoredNotePosition(entry.el, d);
        }
      } catch(_) {}
    }

    _clearAllNotes(){
      try {
        for (const [id, entry] of this.notes.entries()){
          try { entry && entry.el && entry.el.remove && entry.el.remove(); } catch(_) {}
        }
      } catch(_) {}
      this.notes.clear();
    }

    _loadCacheAndRender(){
      try {
        const raw = localStorage.getItem(this._cacheKey);
        if (!raw) return;
        const parsed = JSON.parse(raw);
        if (!parsed || !Array.isArray(parsed.notes)) return;
        const ts = Number(parsed.ts || 0);
        if (ts && (Date.now() - ts) > CACHE_TTL_MS) return;
        (parsed.notes || []).forEach(n => this._renderNote(n));
        this._renderedFromCache = true;
      } catch(_) {}
    }

    _saveCache(notesArray){
      try {
        const payload = { ts: Date.now(), notes: Array.isArray(notesArray) ? notesArray : [] };
        localStorage.setItem(this._cacheKey, JSON.stringify(payload));
      } catch(_) {}
    }
  }

  // Expose
  window.StickyNotesManager = StickyNotesManager;

  // Minimal styles for reminder modal (scoped)
  try {
    const style = document.createElement('style');
    style.textContent = (
      '.sticky-reminder-modal{position:fixed;inset:0;z-index:99999;display:flex;align-items:center;justify-content:center;}'+
      '.sticky-reminder-backdrop{position:absolute;inset:0;background:rgba(0,0,0,.5);backdrop-filter:blur(2px);}'+
      '.sticky-reminder-card{position:relative;background:#fff;color:#1f2933;border-radius:14px;box-shadow:0 12px 32px rgba(0,0,0,.25);width:min(420px,92vw);padding:12px;}'+
      '.sticky-reminder-header{display:flex;align-items:center;justify-content:space-between;padding:6px 8px 8px;}'+
      '.sticky-reminder-title{font-weight:700;font-size:1.05rem;}'+
      '.sticky-reminder-close{border:none;background:transparent;font-size:20px;cursor:pointer;color:#555;}'+
      '.sticky-reminder-body{display:flex;flex-direction:column;gap:12px;padding:6px 8px 10px;}'+
      '.sticky-reminder-section{display:block;}'+
      '.sticky-reminder-subtitle{font-weight:600;margin-bottom:6px;}'+
      '.sticky-reminder-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:6px;}'+
      '.sr-btn{padding:.5rem .75rem;border-radius:10px;border:1px solid rgba(0,0,0,.12);background:#f7fafc;color:#1f2933;cursor:pointer;}'+
      '.sr-btn:hover{background:#edf2f7;}'+
      '.sticky-reminder-row{display:flex;gap:8px;align-items:center;}'+
      '.sr-dt{flex:1;min-width:0;padding:.5rem .6rem;border:1px solid #ddd;border-radius:8px;}'+
      '.sr-save{padding:.5rem .75rem;border-radius:10px;border:1px solid rgba(0,0,0,.12);background:#667eea;color:#fff;cursor:pointer;}'
    );
    document.head.appendChild(style);
  } catch(_) {}

})();
