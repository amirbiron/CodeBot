/* Sticky Notes frontend for Markdown preview
   - Depends on /api/sticky-notes endpoints
   - Works on md_preview.html where FILE_ID is available in scope
*/
(function(){
  'use strict';

  if (typeof window === 'undefined') return;

  function encodeUtf8ToB64(input){
    const s = String(input == null ? '' : input);
    if (!s) return '';
    try {
      if (typeof TextEncoder !== 'undefined') {
        const bytes = new TextEncoder().encode(s);
        let binary = '';
        const chunk = 0x8000;
        for (let i = 0; i < bytes.length; i += chunk) {
          binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
        }
        return btoa(binary);
      }
    } catch(_) {}
    // fallback for older browsers
    try { return btoa(unescape(encodeURIComponent(s))); } catch(_) { return null; }
  }

  function withContentB64(payload){
    if (!payload || typeof payload !== 'object') return payload;
    // If we have `content`, always (re)derive `content_b64` from it.
    // This prevents stale content_b64 from a failed attempt causing silent data loss.
    if (!Object.prototype.hasOwnProperty.call(payload, 'content')) return payload;
    const next = Object.assign({}, payload);
    const content = next.content == null ? '' : String(next.content);
    const b64 = encodeUtf8ToB64(content);
    // If encoding failed, keep plain `content` and drop any existing content_b64
    // to avoid sending stale/empty base64 that would override server-side content.
    if (b64 === null) {
      try { delete next.content_b64; } catch(_) { next.content_b64 = undefined; }
      return next;
    }
    next.content_b64 = b64;
    try { delete next.content; } catch(_) { next.content = undefined; }
    return next;
  }

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
  // מסמן פתק שהמשתמש ביטל לו את הנעיצה/העיגון במפורש – כדי להבדיל בינו
  // לבין פתק ישן שעדיין לא עבר מיגרציה ל־[data-source-line].
  const FLOATING_SENTINEL = '__floating__';
  const AUTO_SAVE_DEBOUNCE_MS = 500;
  // תקרת התוכן מגיעה **מהשרת**, דרך ``window.STICKY_NOTE_MAX_CHARS``
  // שהתבנית מזריקה מ-``sticky_notes_target.MAX_NOTE_CHARS``.
  //
  // אין כאן מספר מוקלד בכוונה: מספר בצד הלקוח היה מקור אמת שני, ופער
  // בינו לבין השרת נראה למשתמש כחיתוך בלי הסבר. אם השרת לא סיפק ערך —
  // פשוט לא מזהירים, במקום להזהיר לפי מספר שאולי כבר לא נכון.
  function maxNoteChars(){
    try {
      const v = Number(window.STICKY_NOTE_MAX_CHARS);
      return (Number.isFinite(v) && v > 0) ? v : 0;
    } catch(_) { return 0; }
  }
  //: שורת משימה: ``- [ ] טקסט`` או ``* [x] טקסט``, עם הזחה כלשהי.
  //: אותה תבנית בדיוק כמו ``_TASK_RE`` ב-``sticky_notes_tasks.py`` — שם
  //: מתבצעת הכתיבה, וכאן רק התצוגה. סטייה ביניהן הייתה מזיזה סידורים.
  //: כמה זמן של חוסר-הקלדה סוגר "התפרצות" והופך אותה לצעד אחד לביטול.
  const UNDO_BURST_MS = 600;
  //: עומק מחסנית הביטול לכל פתק. בזיכרון בלבד.
  const UNDO_MAX_STEPS = 50;
  //: מרווח פנוי מתחת לפתק האחרון במצב אינסופי — תמיד יש לאן לגרור.
  const INFINITE_PAD = 700;
  //: ובכיבוי, רק נשימה קטנה מתחת לפתק האחרון.
  const SURFACE_TAIL_PAD = 24;
  const TASK_LINE_RE = /^([ \t]*[-*][ \t]\[)([ xX])(\].*)$/;
  //: מארקדאון קליל בפתקים. תת-קבוצה מוצהרת ומצומצמת — ראו
  //: docs/user/sticky_notes.rst. כל דפוס נבחר כי הוא נכנס בפתק קטן
  //: ומרונדר בשורה אחת, וכל מה שאוכל גובה או פותח משטח הזרקה נשאר בחוץ.
  const MD_HEADING_RE = /^(#{1,3})[ \t]+(.*)$/;
  const MD_QUOTE_RE   = /^[ \t]*>[ \t]?(.*)$/;
  const MD_HR_RE      = /^[ \t]*-{3,}[ \t]*$/;
  const MD_OL_RE      = /^([ \t]*)(\d+)\.[ \t]+(.*)$/;
  const MD_UL_RE      = /^([ \t]*)[-*][ \t]+(.*)$/;
  const MD_FENCE_RE   = /^[ \t]*```/;
  //: סדר החלופות = עדיפות במיקום נתון: קוד (תוכנו ליטרלי) ← קישור ←
  //: מודגש ← חוצה ← נטוי. הקו התחתון **אינו** נטוי, בכוונה: ``note_id``
  //: ו-``user_id`` נפוצים מדי בכלי שכולו על קוד.
  const MD_INLINE_RE  = /(`+)([\s\S]+?)\1|\[([^\]\n]*?)\]\(([^)\s]+?)\)|\*\*([^*\n]+?)\*\*|~~([^~\n]+?)~~|\*([^*\n]+?)\*/g;
  //: קישור נפתח בלשונית חדשה, ולכן רק ``http``/``https``. כל סכימה אחרת
  //: — ``javascript:``, ``data:`` — מרונדרת כטקסט, לא כקישור.
  const MD_SAFE_LINK  = /^https?:\/\//i;
  const AUTO_SAVE_FORCE_INTERVAL_MS = 3500;
  const CACHE_TTL_MS = 24 * 60 * 60 * 1000; // 24h

  class StickyNotesManager {
    // מקבל או מזהה קובץ (הצורה ההיסטורית, שנשארת עובדת ביט-זהה), או אובייקט
    // תצורה עבור לוח:
    //   new StickyNotesManager('<file_id>')
    //   new StickyNotesManager({ board: '<board_id>', container: el })
    //
    // התאימות לאחור אינה נוחות — היא מה שמגן על מסלול הקובץ מרגרסיה.
    // md_preview.html קורא בצורה הראשונה ולא משתנה כלל.
    constructor(fileIdOrOptions){
      const opts = (typeof fileIdOrOptions === 'string' || fileIdOrOptions == null)
        ? { file: fileIdOrOptions }
        : (fileIdOrOptions || {});

      this.boardId = opts.board ? String(opts.board) : null;
      this.fileId = this.boardId ? null : (opts.file != null ? opts.file : null);
      if (!this.boardId && this.fileId == null) {
        throw new Error('StickyNotesManager: חסר יעד — file או board');
      }

      // הפתקים נכנסים לקונטיינר הזה. בקובץ זה ה-body, כפי שהיה; בלוח זה
      // משטח הלוח, כי פתק "מעוגן ללוח" הוא absolute יחסית אליו ולא למסמך.
      this.container = opts.container || document.body;
      // המקור שממנו נגזרות שורות המקור לעיגון. בלוח אין כזה, וכל מסלול
      // ה-anchored מנוטרל — במקום ליפול על null בשקט בשמונה מקומות.
      // בקובץ ברירת המחדל היא ``#md-content``, כפי שהיה לפני
      // הפרמטריזציה. בלוח אין שורות מקור כלל, ולכן ברירת המחדל היא ריקה
      // — גם אם במקרה קיים ``#md-content`` בעמוד.
      //
      // (השורה הזו התרוקנה פעם בהחלפה גורפת של getElementById, ופתקי
      // קובץ איבדו את העיגון כולו, בשקט. יש עליה בדיקה.)
      this._anchorHost = ('anchorHost' in opts)
        ? opts.anchorHost
        : (this.boardId ? null : document.getElementById('md-content'));
      this._scopeUrl = this.boardId
        ? `/api/sticky-notes/board/${encodeURIComponent(this.boardId)}`
        : `/api/sticky-notes/${encodeURIComponent(this.fileId)}`;

      this.notes = new Map();
      this._saveDebounced = debounce(this._performSaveBatch.bind(this), AUTO_SAVE_DEBOUNCE_MS);
      this._pending = new Map();
      this._inFlight = new Map();
      this._autoFlushTimer = null;
      this._autoFlushBusy = false;
      this._lineIndex = new Map(); // lineNumber -> pageY
      // מפתח נפרד ללוח: בלעדיו לוח וקובץ עם אותה מחרוזת מזהה היו חולקים
      // את אותו קאש ב-localStorage ומרנדרים זה את הפתקים של זה.
      this._cacheKey = this.boardId
        ? `sticky-notes:board:${this.boardId}`
        : `sticky-notes:${String(this.fileId)}`;
      // גלילה אינסופית: כמה מקום פנוי מתחת לפתק האחרון. הלוח **תמיד**
      // נמדד עד הפתק הרחוק ביותר; הכיבוי רק מפסיק להוסיף מרווח מעבר לו,
      // ולעולם אינו מקצר את הלוח מתחת לתוכן שכבר עליו — כלומר אף פתק לא
      // "מתכווץ פנימה" ואף מיקום לא הולך לאיבוד.
      this.infiniteScroll = ('infiniteScroll' in opts) ? !!opts.infiniteScroll : false;
      // מארקדאון מרונדר כברירת מחדל (אופציה ג'), עם מתג לכיבוי במודאל
      // הגדרות הלוח. צ'קבוקסים אינם תלויים בדגל הזה — הם מרונדרים תמיד,
      // כי הם כתיבה למסד ולא רק תצוגה.
      this.markdown = ('markdown' in opts) ? !!opts.markdown : true;
      this._renderedFromCache = false;
      this._pendingSeq = new Map(); // noteId -> monotonic version of pending edits
      this._init();
    }

    // האם מסלול העיגון לשורת מקור רלוונטי בכלל. בלוח — לא.
    get _hasAnchorHost(){ return !!this._anchorHost; }

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
        // אם התבצע ניווט עמוק לפתק מסוים – גלול אליו כעת
        this._maybeScrollToNoteFromUrl();
      } catch(e){ console.error('StickyNotes init failed', e); }
    }

    async loadNotes(){
      try {
        const url = `${this._scopeUrl}?_=${Date.now()}`;
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
      this.container.appendChild(btn);
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
        const container = (this._anchorHost || document.body);
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
        const noteX = isMobile ? 80 : 120;
        const noteY = scroll.y + (isMobile ? 80 : 120);

        const payload = this.boardId ? {
          content: '',
          position: { x: noteX, y: noteY },
          size: { width: isMobile ? 200 : 260, height: isMobile ? 160 : 200 },
          color: '#FFFFCC',
          // ברירת המחדל בלוח: מוצמד למשטח. הלוח *הוא* המשטח.
          mode: 'surface'
        } : {
          content: '',
          // הנחתה קלה למובייל כדי למנוע קפיצה עם הופעת מקלדת
          position: { x: noteX, y: noteY },
          size: { width: isMobile ? 200 : 260, height: isMobile ? 160 : 200 },
          color: '#FFFFCC',
          // **פתק חדש צף עם המשתמש.** זו זרימת העבודה: כותבים פתק תוך עיון
          // בקובץ, גוללים למטה, וממשיכים לכתוב — ורק בסוף נועצים אותו במקום
          // שמתאים.
          //
          // עד כאן ``line_start`` נקבע אוטומטית לשורת המקור הקרובה, וזה
          // הספיק כדי ש-``_resolveMode`` יחזיר ``anchored`` — כלומר
          // ``position: absolute``, שנשאר במקומו במסמך ולא ממשיך עם המסך.
          // נמדד: פתק חדש זז ‎-900px‎ בגלילה של 900, ורק ``pin`` ואז ``unpin``
          // הפכו אותו לצף. ההערה שהייתה כאן כבר הצהירה "ללא עיגון כברירת
          // מחדל" — בוטל רק העיגון לכותרות, ועיגון השורה נשאר.
          line_start: null,
          // הסנטינל המפורש הכרחי: בלעדיו המיגרציה הרכה ב-``_renderNote``
          // הייתה מעגנת את הפתק מחדש בטעינה הבאה ומחזירה את הבאג.
          anchor_id: FLOATING_SENTINEL,
          anchor_text: undefined
        };
        const resp = await fetch(this._scopeUrl, {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(withContentB64(payload))
        });
        const data = await resp.json();
        if (!data || data.ok === false) return;
        const target = this.boardId ? { board_id: this.boardId } : { file_id: this.fileId };
        const note = Object.assign({ id: data.id }, target, payload, { is_minimized: false, created_at: null, updated_at: null });
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
      // שם הפתק, בצד השני של שורת הכפתורים. הוא נשאר גלוי גם כשהפתק
      // ממוזער — וזה כל הרעיון: השורה הריקה של הכותרת מקבלת משמעות.
      // **נוצר נעול.** ``_setTitleEditing`` פועלת דרך ``el.querySelector``,
      // וברינדור היא רצה לפני ש-``header`` צורף ל-``el`` — כלומר לא מצאה
      // כלום והמצב ההתחלתי נשאר פתוח. נתפס באימות: ``readonly=false``
      // בטעינה, כלומר נגיעה בשם עדיין פתחה מקלדת. המצב נקבע כאן, בבנייה,
      // ולא תלוי בסדר צירוף.
      const titleInput = createEl('input', 'sticky-note-title', {
        type: 'text', placeholder: 'שם', 'aria-label': 'שם הפתק', maxlength: '80',
        readonly: 'readonly', tabindex: '-1'
      });
      titleInput.value = String(note.title || '');
      const drag = createEl('div', 'sticky-note-drag');
      const actions = createEl('div', 'sticky-note-actions');
      const isPinnedInitial = note.anchor_id === PIN_SENTINEL;
      const pinBtn = createEl('button', 'sticky-note-btn sticky-note-pin', { title: 'הצמד/בטל נעיצה', 'aria-pressed': isPinnedInitial ? 'true' : 'false' }); pinBtn.textContent = '📌';
      const minimizeBtn = createEl('button', 'sticky-note-btn', { title: 'מזער' }); minimizeBtn.textContent = '—';
      const remindBtn = createEl('button', 'sticky-note-btn', { title: 'קבע תזכורת' }); remindBtn.textContent = '🔔';
      const deleteBtn = createEl('button', 'sticky-note-btn', { title: 'מחיקה' }); deleteBtn.textContent = '×';
      // ביטול פעולה. אין לפתקים היסטוריית גרסאות, ולכן בחירת-הכל ואז הדבקה
      // בטעות מוחקת הכל בלי דרך חזרה. הכפתור מושבת כשאין מה לבטל — כפתור
      // שנראה זמין ולא עושה כלום הוא בדיוק סוג השקר שאנחנו נמנעים ממנו.
      const undoBtn = createEl('button', 'sticky-note-btn sticky-note-undo', { title: 'אין מה לבטל' });
      undoBtn.textContent = '↶';
      undoBtn.disabled = true;
      const copyBtn = createEl('button', 'sticky-note-btn sticky-note-copy', { title: 'העתק את תוכן הפתק' });
      copyBtn.textContent = '⧉';
      actions.appendChild(pinBtn); actions.appendChild(remindBtn); actions.appendChild(undoBtn);
      actions.appendChild(copyBtn); actions.appendChild(minimizeBtn); actions.appendChild(deleteBtn);
      // **השם יושב בתוך ידית הגרירה, ולא לצידה.**
      //
      // נמדד לפני: שדה השם תפס 218px מהכותרת בפתק ברירת מחדל ו-635px
      // בפתק מוגדל, וידית הגרירה נשארה 24px — כלומר 1%-3% מהכותרת נגררו
      // בפועל, בעוד ש-``cursor: move`` הבטיח גרירה על כולה. נגיעה בכל
      // מקום למעלה פתחה עריכת שם, ולא נשאר במה לאחוז.
      //
      // עכשיו: כשהשם נעול הוא ``pointer-events: none`` והאירועים נופלים
      // דרכו אל הידית שמתחתיו — כלומר כל רוחב הכותרת נגרר. העיפרון הוא
      // הדרך היחידה להיכנס לעריכה.
      const editBtn = createEl('button', 'sticky-note-btn sticky-note-edit-title', {
        type: 'button', 'aria-label': 'עריכת שם הפתק', 'aria-pressed': 'false'
      });
      editBtn.textContent = '✎';
      drag.appendChild(editBtn);
      drag.appendChild(titleInput);
      header.appendChild(actions); header.appendChild(drag);

      editBtn.addEventListener('click', (ev) => {
        try { ev.stopPropagation(); ev.preventDefault(); } catch(_) {}
        this._setTitleEditing(el, !el.classList.contains('is-editing-title'));
      });
      // גרירה על העיפרון עצמו לא אמורה להתחיל — הוא כפתור.
      //
      // ``preventDefault`` על ה-mousedown הוא מה שמונע העברת מיקוד, ולכן
      // גם את ה-``blur`` של השדה. בלעדיו נוצר מרוץ סדר: ה-blur היה רץ
      // **לפני** ה-click, סוגר את מצב העריכה, ואז ה-click היה מוצא מצב
      // סגור ומדליק אותו בחזרה — כלומר ה-✔ לא סוגר כלום. נתפס באימות
      // מקצה לקצה: ``editing=True`` אחרי לחיצה על ✔, והפתק נשאר לא נגרר.
      editBtn.addEventListener('mousedown', (ev) => {
        try { ev.stopPropagation(); ev.preventDefault(); } catch(_) {}
      });
      editBtn.addEventListener('touchstart', (ev) => { try { ev.stopPropagation(); } catch(_) {} }, { passive: true });
      // **ואותו דבר לשדה עצמו.** הוא יושב בתוך ידית הגרירה, ולכן בזמן
      // עריכה — כשהוא כבר מקבל אירועים — לחיצה בתוכו בועה אל הידית
      // ומתחילה גרירה במקום למקם סמן. נמדד: סימון טקסט בשם הזיז את הפתק
      // מ-20px ל-0px, ובחר מחרוזת ריקה. כשהשדה נעול ה-``pointer-events``
      // ממילא לא מביא אותנו לכאן.
      titleInput.addEventListener('mousedown', (ev) => { try { ev.stopPropagation(); } catch(_) {} });
      titleInput.addEventListener('touchstart', (ev) => { try { ev.stopPropagation(); } catch(_) {} }, { passive: true });

      titleInput.addEventListener('input', () => {
        // שם חדש הוא ניסיון חדש. הסימון הישן שייך לערך שכבר לא בשדה,
        // והשארתו הייתה מציגה שגיאה על טקסט שטרם נבדק.
        this._markTitleConflict(el.dataset.noteId, false);
        this._queueSave(el, { title: titleInput.value });
      });
      // 409 מהשרת פירושו שהשם תפוס בלוח הזה. חיווי גלוי — לא כתיבה
      // שנראית שנשמרה ולא נשמרה.
      titleInput.addEventListener('blur', async () => {
        // **הנעילה קודמת להמתנה, לא אחריה.** ``_flushFor`` ממתין לרשת,
        // ורשת יכולה להיתקע. אם השחרור היה אחריו, הפתק היה נשאר במצב
        // עריכה — כלומר בלתי ניתן לגרירה — עד שהבקשה תחזור.
        this._setTitleEditing(el, false);
        try { await this._flushFor(el); } catch(_) {}
        this._syncTitleConflict(el);
      });
      titleInput.addEventListener('keydown', (ev) => {
        if (ev.key !== 'Enter' && ev.key !== 'Escape') return;
        try { ev.preventDefault(); } catch(_) {}
        this._setTitleEditing(el, false);
      });

      undoBtn.addEventListener('click', (ev) => {
        try { ev.stopPropagation(); ev.preventDefault(); } catch(_) {}
        this._undoLastChange(el);
      });
      copyBtn.addEventListener('click', (ev) => {
        try { ev.stopPropagation(); ev.preventDefault(); } catch(_) {}
        this._copyNoteContent(el);
      });
      pinBtn.addEventListener('click', (ev) => {
        try { ev.stopPropagation(); ev.preventDefault(); } catch(_) {}
        this._toggleAnchor(el);
      });

      const textarea = createEl('textarea', 'sticky-note-content');
      textarea.value = note.content || '';
      textarea.addEventListener('focus', () => this._syncTaskView(el, { editing: true }));
      textarea.addEventListener('blur', () => this._syncTaskView(el));

      const resizer = createEl('div', 'sticky-note-resize');

      // תצוגת המשימות. מוצגת רק כשיש צ'קבוקסים בתוכן ורק כשה-textarea
      // אינו בפוקוס — כך שהעריכה נשארת בדיוק כפי שהייתה.
      const taskView = createEl('div', 'sticky-note-tasks');
      taskView.addEventListener('change', (ev) => {
        const box = ev.target;
        if (box && box.type === 'checkbox') this._onTaskToggle(el, box);
      });
      // לחיצה בכל מקום בתצוגה שאינו התיבה עצמה מחזירה לעריכה, בשורה
      // שנלחצה. זו הדרך היחידה החוצה מהתצוגה — בלעדיה פתק עם צ'קבוקס
      // אחד הופך לקריאה-בלבד לתמיד.
      const enterFromEvent = (ev) => {
        const t = ev.target;
        if (t && t.classList && t.classList.contains('sticky-task-box')) return false;
        const row = (t && t.closest) ? t.closest('.sticky-task-line') : null;
        const offset = row ? parseInt(row.dataset.charOffset, 10) : NaN;
        this._enterEditAt(el, Number.isFinite(offset) ? offset : null);
        return true;
      };
      taskView.addEventListener('click', enterFromEvent);
      // נתיב מקלדת. בלעדיו התצוגה היא מלכודת למי שאינו משתמש בעכבר:
      // ה-textarea מוסתר, התצוגה לא הייתה ניתנת למיקוד, והמאזין היחיד
      // היה click — כלומר אין שום דרך לחזור לעריכה.
      taskView.setAttribute('tabindex', '0');
      taskView.setAttribute('role', 'group');
      taskView.setAttribute('aria-label', 'תוכן הפתק — הקישו Enter כדי לערוך');
      taskView.addEventListener('keydown', (ev) => {
        if (ev.key !== 'Enter' && ev.key !== ' ' && ev.key !== 'Spacebar') return;
        // רווח על תיבת סימון הוא סימון, לא כניסה לעריכה
        const t = ev.target;
        if (t && t.classList && t.classList.contains('sticky-task-box')) return;
        ev.preventDefault();
        if (enterFromEvent(ev) === false) return;
      });

      el.appendChild(header);
      el.appendChild(textarea);
      el.appendChild(taskView);
      el.appendChild(resizer);
      this.container.appendChild(el);

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
        this._recordUndoBurst(el, textarea);
        this._checkContentLength(el, textarea.value);
        this._queueSave(el, { content: textarea.value });
      });
      textarea.addEventListener('keydown', (ev) => {
        try {
          // תמיכה במקלדות מובייל/טלגרם שמשדרות key=Unidentified במקום Enter
          if ((ev.key === 'Enter' || ev.keyCode === 13) && !ev.shiftKey && !ev.ctrlKey && !ev.metaKey) {
            // צילום **לפני** השינוי. המשך הרשימה כותב ל-``textarea.value``
            // ישירות, וכתיבה תכנותית אינה משדרת ``input`` — כלומר הביטול
            // לא ראה את השינוי הזה כלל, והצעד היה בלתי הפיך.
            const beforeChange = textarea.value;
            const result = this._handleListContinuation(textarea);
            if (result === false) {
              // כפול אנטר → יציאה מרשימה, הטקסטריה כבר עודכנה
              ev.preventDefault();
              this._noteProgrammaticEdit(el, textarea, beforeChange);
              this._queueSave(el, { content: textarea.value });
            } else if (typeof result === 'string') {
              ev.preventDefault();
              const start = textarea.selectionStart;
              const before = textarea.value.slice(0, start);
              const after = textarea.value.slice(textarea.selectionEnd ?? start);
              textarea.value = before + result + after;
              const newPos = start + result.length;
              textarea.selectionStart = textarea.selectionEnd = newPos;
              this._noteProgrammaticEdit(el, textarea, beforeChange);
              this._queueSave(el, { content: textarea.value });
            }
          }
        } catch (_) { /* list continuation error – silent */ }
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
      // תצוגת המשימות נבנית מהתוכן שנטען. אם אין צ'קבוקסים היא נשארת מוסתרת
      // וה-textarea מוצג כרגיל — כלומר פתק רגיל אינו משתנה כלל.
      this._syncTaskView(el);
      this._undoState(el);          // מצלם את נקודת המוצא כבר עכשיו
      this._syncUndoButton(el);
      this._applyPositionMode(el, note, { initial: true });
      this._reflowWithinViewport(el);
      this._updateAnchoredNotePosition(el, note);
      this._updateSurfaceExtent();

      // ── מיגרציה רכה לפתקים ישנים ב־MD preview ──
      // פתקים שנוצרו לפני תמיכת ה־[data-source-line] נשמרו בלי עוגן וחיו כ־
      // position:fixed. עכשיו אנחנו מעגנים אותם אוטומטית לאלמנט הקרוב, שומרים את
      // ה־line_start ב־DB דרך _queueSave (debounced, לא חוסם את הרינדור), ומפעילים
      // מחדש את מצב המיקום כך שהפתק יהפוך ל־anchored וישמור על מיקום יציב מול התוכן.
      try {
        const isPinnedNote = note.anchor_id === PIN_SENTINEL;
        // פתק שסומן במפורש כ־floating (המשתמש ביטל עיגון/נעיצה) לא עובר
        // מיגרציה — אחרת היינו דורסים את הבחירה המפורשת שלו בכל טעינת דף.
        const isExplicitFloating = note.anchor_id === FLOATING_SENTINEL;
        const hasAnchor = isPinnedNote
          || isExplicitFloating
          || (Number.isInteger(note.line_start) && note.line_start > 0)
          || (note.anchor_id && note.anchor_id !== '');
        if (!hasAnchor) {
          const mdEl = this._anchorHost;
          if (mdEl && mdEl.querySelector('[data-source-line]')) {
            const targetY = (typeof note.position?.y === 'number') ? note.position.y : null;
            if (Number.isFinite(targetY)) {
              const nearest = this._findNearestSourceLineElement(targetY);
              if (nearest) {
                const raw = parseInt(nearest.getAttribute('data-source-line'), 10);
                if (Number.isFinite(raw) && raw >= 0) {
                  const newLineStart = raw + 1;
                  note.line_start = newLineStart;
                  const entry = this.notes.get(note.id);
                  if (entry && entry.data) entry.data.line_start = newLineStart;
                  this._queueSave(el, { line_start: newLineStart });
                  // החלפת מצב: floating → anchored. מחייב ניקוי relYOffset שנוצר קודם.
                  try { if (el.dataset && el.dataset.relYOffset) { delete el.dataset.relYOffset; } } catch(_) {}
                  this._applyPositionMode(el, note, { initial: false, reflow: false });
                  this._updateAnchoredNotePosition(el, note);
                }
              }
            }
          }
        }
      } catch(_) {}

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

      // הנקודה שממנה נמדדים ``position.x/y`` של פתק, בקואורדינטות של אזור
      // התצוגה.
      //
      // **זה שורש הבאג "הפתק זז קצת למטה בכל רענון".** השמירה חישבה תמיד
      // קואורדינטות של המסמך (``rect + scroll``), אבל פתק במצב ``surface``
      // ממוקם ``absolute`` בתוך הקונטיינר — כלומר הדפדפן קורא בדיוק את
      // אותם מספרים ביחס למשטח הלוח. בקובץ שני המרחבים חופפים, כי
      // הקונטיינר הוא ה-body והוא לא ממוקם; בלוח המשטח מתחיל כמה מאות
      // פיקסלים מתחת לראש המסמך, והפתק ירד בדיוק בהפרש הזה בכל שמירה.
      //
      // מסלול הקובץ יוצא ביט-זהה: כל ענף שאינו קונטיינר ממוקם מחזיר
      // ``-scroll``, ואז ``rect.left - (-scroll.x)`` הוא בדיוק החישוב הישן.
      _positionOrigin(el, mode){
        const scroll = getScrollOffsets();
        const docOrigin = { x: -scroll.x, y: -scroll.y };
        let resolved = mode;
        if (!resolved) {
          const entry = this._getEntry(el);
          resolved = this._resolveMode(entry ? entry.data : null);
        }
        // ``screen`` הוא ``position: fixed`` ונשמר במרחב המסמך, כפי שהיה.
        if (resolved === 'screen') return docOrigin;
        const parent = this.container;
        if (!parent || parent === document.body || parent === document.documentElement) return docOrigin;
        try {
          const r = parent.getBoundingClientRect();
          // קופסת ה-padding של האב הממוקם, לפני הגלילה הפנימית שלו —
          // בדיוק המרחב ש-``left``/``top`` של ילד ``absolute`` נמדדים בו.
          return {
            x: r.left + (parent.clientLeft || 0) - (parent.scrollLeft || 0),
            y: r.top + (parent.clientTop || 0) - (parent.scrollTop || 0)
          };
        } catch(_) { return docOrigin; }
      }

      // פתק לא יוצא מגבולות המשטח.
      //
      // בלי זה החלק העליון של הפתק — שהוא גם ידית הגרירה — יכול לעלות מעל
      // הקצה, ואז אין שום דרך להחזיר אותו: הגרירה היא לחיצה על הכותרת,
      // והכותרת מחוץ למסך.
      // פתק צף (``position: fixed``) נמדד מול אזור התצוגה ולא מול המשטח.
      //
      // בלי זה אפשר היה לגרור אותו כך שהכותרת — שהיא ידית הגרירה — יוצאת
      // מחוץ למסך. הוא אמנם חזר לגבולות בלחיצה הבאה, בזכות
      // ``_reflowWithinViewport`` שרץ בפוקוס, אבל "נעלם ואז חוזר" הוא לא
      // התנהגות, הוא תיקון שקורה במקרה.
      _clampToViewport(el, x, y){
        try {
          const vp = window.visualViewport;
          const vpW = Math.max(100, (vp ? vp.width : window.innerWidth) || window.innerWidth || 320);
          const vpH = Math.max(100, (vp ? vp.height : window.innerHeight) || window.innerHeight || 320);
          const r = el.getBoundingClientRect();
          const w = Math.round(r.width) || 260;
          const h = Math.round(r.height) || 200;
          return {
            x: clamp(Math.round(x), 12, Math.max(12, vpW - w - 12)),
            y: clamp(Math.round(y), 60, Math.max(60, vpH - h - 20))
          };
        } catch(_) { return { x, y }; }
      }

      // גובה המשטח נגזר מהתוכן שעליו, ולא ממספר קבוע.
      //
      // ``INFINITE_PAD`` הוא המרווח שנשאר פנוי מתחת לפתק האחרון כשהמצב
      // האינסופי דלוק — כך תמיד יש לאן לגרור. בכיבוי המרווח מתאפס, אבל
      // הגובה עדיין נמדד עד הפתק הרחוק ביותר.
      // מדידה אחת לכל פריים, ולא אחת לכל פתק.
      //
      // ``_renderNote`` קורא לכאן על כל פתק, והמדידה עצמה עוברת על **כל**
      // הפתקים עם ``getBoundingClientRect`` — כלומר טעינה היא ריבועית, וכל
      // קריאה כזו מכריחה את הדפדפן לחשב פריסה מחדש. נמדד בכרומיום לפני
      // האיחוד: 10 פתקים → 65 קריאות, 30 → 495, 60 → 1,890. אחרי: 20, 60,
      // 120 — עם אותו ``min-height`` בדיוק. בתקרת הלוח (200 פתקים) ההפרש
      // הוא בין מאות לעשרות אלפים.
      _updateSurfaceExtent(){
        if (typeof requestAnimationFrame !== 'function') {
          // סביבת בדיקה בלי דפדפן — מודדים מיד, כדי שההתנהגות תישאר
          // ניתנת לבדיקה סינכרונית.
          this._applySurfaceExtent();
          return;
        }
        if (this._extentFrame) return;
        this._extentFrame = requestAnimationFrame(() => {
          this._extentFrame = null;
          this._applySurfaceExtent();
        });
      }

      _applySurfaceExtent(){
        try {
          const surface = this.container;
          if (!this.boardId || !surface || !surface.style) return;
          let bottom = 0;
          this.notes.forEach((entry) => {
            const el = entry && entry.el;
            if (!el || !el.classList || !el.classList.contains('is-pinned')) return;
            const top = parseInt(el.style.top || '0', 10) || 0;
            const h = Math.round(el.getBoundingClientRect().height) || 0;
            if (top + h > bottom) bottom = top + h;
          });
          const pad = this.infiniteScroll ? INFINITE_PAD : SURFACE_TAIL_PAD;
          const needed = bottom + pad;
          // ``min-height`` ולא ``height``: הכלל ב-CSS ממלא את המסך, וכאן
          // רק מרחיבים מעבר לו. הקטן מביניהם לא מקצר את הלוח.
          surface.style.minHeight = needed > 0 ? `max(var(--board-fill, 0px), ${needed}px)` : '';
        } catch(_) {}
      }

      setInfiniteScroll(on){
        this.infiniteScroll = !!on;
        this._updateSurfaceExtent();
      }

      _clampToSurface(el, x, y, note){
        try {
          const parent = this.container;
          if (!parent || typeof parent.clientWidth !== 'number' || parent.clientWidth <= 0) {
            return { x, y };
          }
          let w = (note && note.size && typeof note.size.width === 'number') ? note.size.width : 0;
          if (!w) { try { w = Math.round(el.getBoundingClientRect().width) || 0; } catch(_) { w = 0; } }
          if (!w) w = 260;
          const maxX = Math.max(0, parent.clientWidth - w);
          // ציר ה-Y נחסם מלמטה בלבד: המשטח גליל, וגרירה כלפי מטה מגדילה
          // אותו — כלומר פתק "רחוק" עדיין נגיש, בניגוד לפתק מעל הקצה.
          return { x: clamp(Math.round(x), 0, maxX), y: Math.max(0, Math.round(y)) };
        } catch(_) { return { x, y }; }
      }

      _notePayloadFromEl(el, mode){
        const rect = el.getBoundingClientRect();
        const origin = this._positionOrigin(el, mode);
        const x = Math.round(rect.left - origin.x);
        const y = Math.round(rect.top - origin.y);
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

    _updatePinButtonState(el, isActive){
      const pinBtn = el ? el.querySelector('.sticky-note-pin') : null;
      if (!pinBtn) return;
      const active = !!isActive;
      pinBtn.classList.toggle('is-active', active);
      pinBtn.setAttribute('aria-pressed', active ? 'true' : 'false');
      // אותה משמעות, אותו צבע, בשני המשטחים
      const anchor = this.boardId ? 'ללוח' : 'למסמך';
      pinBtn.title = active ? `הפתק מוצמד ${anchor} — לחצו כדי לשחרר` : `הצמידו את הפתק ${anchor}`;
    }

      // ----- צ'קבוקסים -----
      //
      // שורה בצורת ``- [ ] טקסט`` היא משימה. לחיצה על התיבה היא **כתיבה
      // למסד**, לא שינוי תצוגה — ולכן כל הזרימה כאן בנויה סביב זה
      // שהתצוגה לא תשקר: אם הכתיבה לא נקלטה, הסימון חוזר אחורה ומוצגת
      // שגיאה. כשל שקט הוא בדיוק מה שהאפיון אוסר.

      // בונה את התצוגה מ**כל** השורות, לא רק משורות המשימה.
      //
      // הגרסה הראשונה רינדרה רק את שורות הצ'קבוקס והסתירה את ה-textarea.
      // התוצאה: פתק עם 400 שורות ושורת משימה אחת נראה כאילו נמחק — כל השאר
      // פשוט לא הוצג, ולא הייתה שום דרך לחזור לעריכה. התוכן היה בטקסטאריה
      // כל הזמן (נמדד בדפדפן: 5,509 תווים לפני ואחרי, אפס בקשות כתיבה),
      // אבל מבחינת המשתמש זה אובדן מידע — ומבחינת התוצאה זה נכון.
      //
      // **החוק שמעל הפונקציה הזו: רינדור הוא חד-כיווני.** ``content →
      // HTML``, לעולם לא חזרה. היחידים שרשאים לכתוב ל-``content`` הם
      // ה-textarea עצמו וראוט ``/task`` (סידורי + מצב). על הכלל הזה יש
      // בדיקה — ראו ``tests/sticky-notes-target.test.js``.
      // ----- פרסר מארקדאון קליל -----
      //
      // **החוזה השלישי, הקדוש:** אפס ``innerHTML``. כל צומת נבנה עם
      // ``createElement`` ו-``textContent``/``createTextNode``, ולכן טקסט
      // של משתמש — או של סוכן, דרך ``codekeeper_create_note`` ב-MCP —
      // אינו יכול להפוך לתגית בשום מצב. זה מה שהופך רינדור של תוכן שנכתב
      // מרחוק לבטוח, ולכן אין כאן ספרייה שפולטת מחרוזת HTML.

      // מפרק שורה למערך קטעים: {type,text} או {type:'link',text,href}.
      // טהור — לא נוגע ב-DOM, ולכן נבדק ישירות.
      _parseInline(text){
        const src = String(text == null ? '' : text);
        const out = [];
        let last = 0, m;
        MD_INLINE_RE.lastIndex = 0;
        while ((m = MD_INLINE_RE.exec(src)) !== null){
          if (m.index > last) out.push({ type: 'text', text: src.slice(last, m.index) });
          if (m[1] !== undefined)      out.push({ type: 'code', text: m[2] });
          else if (m[3] !== undefined) {
            if (MD_SAFE_LINK.test(m[4])) out.push({ type: 'link', text: m[3] || m[4], href: m[4] });
            else out.push({ type: 'text', text: m[0] });
          }
          else if (m[5] !== undefined) out.push({ type: 'bold', text: m[5] });
          else if (m[6] !== undefined) out.push({ type: 'strike', text: m[6] });
          else if (m[7] !== undefined) out.push({ type: 'italic', text: m[7] });
          last = MD_INLINE_RE.lastIndex;
        }
        if (last < src.length) out.push({ type: 'text', text: src.slice(last) });
        // איחוד קטעי טקסט צמודים — קישור שנדחה מותיר ליטרל מפוצל.
        const merged = [];
        for (const seg of out){
          const prev = merged[merged.length - 1];
          if (seg.type === 'text' && prev && prev.type === 'text') prev.text += seg.text;
          else merged.push(seg);
        }
        if (merged.length === 0) merged.push({ type: 'text', text: '' });
        return merged;
      }

      // מסווג בלוק לשורה בודדת. קוד רב-שורי מטופל בלולאה, לא כאן.
      _classifyLine(line){
        let m;
        if ((m = MD_HEADING_RE.exec(line))) return { kind: 'heading', level: m[1].length, content: m[2] };
        if ((m = MD_QUOTE_RE.exec(line)))   return { kind: 'quote', content: m[1] };
        if (MD_HR_RE.test(line))            return { kind: 'hr', content: '' };
        if ((m = MD_OL_RE.exec(line)))      return { kind: 'ol', content: m[3], marker: m[2] + '.' };
        if ((m = MD_UL_RE.exec(line)))      return { kind: 'ul', content: m[2] };
        return { kind: 'plain', content: line };
      }

      // האם יש מארקדאון שכדאי לרנדר — כדי לא להפוך פתק טקסט רגיל לתצוגה.
      _lineHasInline(content){
        MD_INLINE_RE.lastIndex = 0;
        const m = MD_INLINE_RE.exec(content);
        if (!m) return false;
        if (m[3] !== undefined && !MD_SAFE_LINK.test(m[4])) return false;
        return true;
      }
      _hasRenderableMarkdown(lines){
        for (const line of lines){
          if (MD_FENCE_RE.test(line)) return true;
          const b = this._classifyLine(line);
          if (b.kind !== 'plain') return true;
          if (this._lineHasInline(b.content)) return true;
        }
        return false;
      }

      // בונה את הקטעים לתוך ``container``, צומת אחר צומת. אפס innerHTML.
      _appendInline(container, text){
        for (const seg of this._parseInline(text)){
          if (seg.type === 'text'){ container.appendChild(document.createTextNode(seg.text)); continue; }
          let node;
          if (seg.type === 'bold')        node = createEl('strong', 'sticky-md-bold');
          else if (seg.type === 'italic') node = createEl('em', 'sticky-md-italic');
          else if (seg.type === 'strike') node = createEl('del', 'sticky-md-strike');
          else if (seg.type === 'code')   node = createEl('code', 'sticky-md-code');
          else if (seg.type === 'link'){
            node = createEl('a', 'sticky-md-link');
            // ``href`` נכתב עם setAttribute אחרי שהסכימה כבר אושרה ב-parseInline.
            try { node.setAttribute('href', seg.href); } catch(_) {}
            node.setAttribute('target', '_blank');
            node.setAttribute('rel', 'noopener noreferrer');
          }
          else node = document.createTextNode(seg.text);
          if (node.nodeType !== 3) node.textContent = seg.text;
          container.appendChild(node);
        }
      }

      // מחליף את מצב המארקדאון ומרנדר מחדש את כל הפתקים על המשטח.
      setMarkdown(on){
        this.markdown = !!on;
        try { this.notes.forEach((entry) => { if (entry && entry.el) this._syncTaskView(entry.el); }); } catch(_) {}
      }

      _syncTaskView(el, opts){
        try {
          const view = el.querySelector('.sticky-note-tasks');
          const textarea = el.querySelector('.sticky-note-content');
          if (!view || !textarea) return;
          const editing = !!(opts && opts.editing);
          const lines = String(textarea.value == null ? '' : textarea.value).split('\n');
          const hasTask = lines.some((line) => TASK_LINE_RE.test(line));
          // התצוגה נפתחת אם יש צ'קבוקס (תמיד), או אם המארקדאון דלוק ויש בו
          // מבנה כלשהו. פתק טקסט רגיל נשאר textarea ולא משתנה בכלל.
          const wantMd = this.markdown && this._hasRenderableMarkdown(lines);
          if (editing || (!hasTask && !wantMd)) {
            view.hidden = true;
            textarea.hidden = false;
            // מנקים את התצוגה גם ביציאה: אחרת צמתים שרונדרו קודם — כותרות,
            // קישורים — שורדים בתוך ה-view המוסתר. בלתי נראים למשתמש, אבל
            // עדיין ב-DOM. נתפס באימות: אחרי כיבוי המארקדאון, ``.sticky-md-h1``
            // עדיין נמצא בשאילתה.
            view.textContent = '';
            return;
          }
          view.textContent = '';
          let taskIndex = 0;
          let charOffset = 0;
          let inFence = false;
          lines.forEach((line) => {
            const m = TASK_LINE_RE.exec(line);
            const row = createEl('div', 'sticky-task-line');
            // מיקום התו הראשון של השורה בתוך התוכן — כדי שלחיצה תחזיר
            // לעריכה בדיוק בשורה שנלחצה, ולא בתחילת הפתק.
            row.dataset.charOffset = String(charOffset);
            const isFenceLine = wantMd && MD_FENCE_RE.test(line);
            if (m) {
              // צ'קבוקס — מסלול קיים, לא תלוי במארקדאון.
              row.classList.add('sticky-task');
              const box = createEl('input', 'sticky-task-box');
              box.type = 'checkbox';
              box.checked = m[2].toLowerCase() === 'x';
              box.dataset.taskIndex = String(taskIndex);
              taskIndex += 1;
              const span = createEl('span', 'sticky-task-text');
              // גם טקסט המשימה מקבל אינליין, כשהמארקדאון דלוק.
              if (wantMd) this._appendInline(span, m[3].slice(1).trim());
              else span.textContent = m[3].slice(1).trim();
              row.appendChild(box);
              row.appendChild(span);
            } else if (inFence || isFenceLine) {
              // בתוך גדר קוד — כל שורה ליטרלית, בלי אינליין. הגדר עצמה
              // נשארת גלויה: כל שורת מקור היא שורת תצוגה אחת עם charOffset
              // משלה, וזה מה ששומר על חזרה-לעריכה מדויקת.
              row.classList.add('sticky-md-pre');
              if (isFenceLine) row.classList.add('is-fence');
              row.textContent = line === '' ? ' ' : line;
              if (isFenceLine) inFence = !inFence;
            } else if (wantMd) {
              const b = this._classifyLine(line);
              if (b.kind === 'heading'){
                row.classList.add('sticky-md-h', 'sticky-md-h' + b.level);
                this._appendInline(row, b.content);
              } else if (b.kind === 'quote'){
                row.classList.add('sticky-md-quote');
                this._appendInline(row, b.content || ' ');
              } else if (b.kind === 'hr'){
                row.classList.add('sticky-md-hr');
                row.appendChild(createEl('hr', 'sticky-md-rule'));
              } else if (b.kind === 'ul' || b.kind === 'ol'){
                row.classList.add('sticky-md-li', b.kind === 'ol' ? 'is-ol' : 'is-ul');
                const bullet = createEl('span', 'sticky-md-bullet');
                bullet.textContent = b.kind === 'ol' ? b.marker : '•';
                const body = createEl('span', 'sticky-md-li-body');
                this._appendInline(body, b.content);
                row.appendChild(bullet);
                row.appendChild(body);
              } else {
                row.classList.add('is-text');
                if (line === '') row.textContent = ' ';
                else this._appendInline(row, line);
              }
            } else {
              // מארקדאון כבוי — התנהגות היום בדיוק: טקסט גולמי.
              row.classList.add('is-text');
              row.textContent = line === '' ? ' ' : line;
            }
            view.appendChild(row);
            charOffset += line.length + 1;   // +1 עבור ה-``\n`` שהפיצול הסיר
          });
          view.hidden = false;
          textarea.hidden = true;
        } catch(_) {}
      }

      // חזרה לעריכה מתוך התצוגה.
      //
      // בלי זה התצוגה היא דלת חד-כיוונית: מרגע שנכתב צ'קבוקס אחד, אי אפשר
      // היה להוסיף או למחוק טקסט בפתק — ה-textarea מוסתר ואין מה שיחזיר
      // אליו את הפוקוס.
      _enterEditAt(el, charOffset){
        try {
          const textarea = el.querySelector('.sticky-note-content');
          if (!textarea) return;
          // חייב לרוץ לפני ה-focus: אי אפשר למקד אלמנט מוסתר.
          this._syncTaskView(el, { editing: true });
          textarea.focus();
          if (Number.isFinite(charOffset)) {
            const pos = clamp(Math.round(charOffset), 0, textarea.value.length);
            try { textarea.selectionStart = textarea.selectionEnd = pos; } catch(_) {}
          }
        } catch(_) {}
      }

      // שם תפוס — מסומן על השדה עצמו, לפי **קוד השגיאה מהשרת** בלבד.
      //
      // הגרסה הראשונה הסיקה את זה מ-``has-save-error``, שהוא סימון גנרי:
      // כל כשל שמירה — חריגת מכסה, נפילת רשת, 500 — היה מסמן את השם
      // כתפוס. וגם ההפך: מסלול ה-409 אינו מסמן ``has-save-error`` כלל,
      // ולכן התנגשות שם אמיתית לא הופיעה אף פעם. סימון שמופיע בכל מצב
      // חוץ מהנכון הוא גרוע מאין סימון.
      // מצב עריכת השם: נעול (נגרר) מול פתוח (מקליד).
      //
      // ``pointer-events`` הוא מה שמעביר את האירועים לידית שמתחת, ולכן
      // הוא הדבר שבאמת מחזיר את שטח הגרירה. ``readonly`` ו-``tabindex``
      // נלווים אליו כדי שגם מקלדת וקורא-מסך יראו את אותו מצב.
      _setTitleEditing(el, on){
        try {
          const input = el.querySelector('.sticky-note-title');
          const btn = el.querySelector('.sticky-note-edit-title');
          const editing = !!on;
          el.classList.toggle('is-editing-title', editing);
          if (btn) {
            const label = editing ? 'סיום עריכת השם' : 'עריכת שם הפתק';
            btn.textContent = editing ? '✔' : '✎';
            btn.title = label;
            // ``aria-label`` נקבע פעם אחת בבנייה, ולכן קורא מסך היה מכריז
            // "עריכת שם" גם על הכפתור שסוגר אותה. מתחלף יחד עם השאר.
            btn.setAttribute('aria-label', label);
            btn.setAttribute('aria-pressed', editing ? 'true' : 'false');
          }
          if (!input) return;
          if (editing) {
            input.removeAttribute('readonly');
            input.setAttribute('tabindex', '0');
            try { input.focus(); input.select(); } catch(_) {}
          } else {
            input.setAttribute('readonly', 'readonly');
            input.setAttribute('tabindex', '-1');
            try { if (document.activeElement === input) input.blur(); } catch(_) {}
          }
        } catch(_) {}
      }

      _markTitleConflict(id, on){
        try {
          const entry = this.notes.get(String(id));
          if (!entry || !entry.el) return;
          entry.titleConflict = !!on;
          this._syncTitleConflict(entry.el);
        } catch(_) {}
      }

      _syncTitleConflict(el){
        try {
          const input = el.querySelector('.sticky-note-title');
          if (!input) return;
          const entry = this._getEntry(el);
          const conflicted = !!(entry && entry.titleConflict);
          input.classList.toggle('is-duplicate', conflicted);
          input.title = conflicted ? 'שם כזה כבר קיים בלוח הזה' : 'שם הפתק';
        } catch(_) {}
      }

      // ----- ביטול פעולה -----
      //
      // לפתקים אין היסטוריית גרסאות בשרת. התרחיש שזה מגן מפניו הוא ממשי:
      // בוחרים את כל הטקסט כדי להעתיק, ולוחצים "הדבק" במקום "העתק" — וכל
      // הפתק נמחק. בלי מנגנון כזה אין שום דרך חזרה.
      //
      // **טווח מכוון: הסשן הנוכחי.** המחסנית חיה בזיכרון ולא שורדת רענון.
      // התרחיש שהיא מכסה מתגלה מיד, ואחסון מקומי של עשרות גרסאות בנות
      // 20,000 תווים היה אוכל את מכסת הדפדפן.

      _undoState(el){
        const entry = this._getEntry(el);
        if (!entry) return null;
        if (!entry.undo) {
          // ``last`` מאותחל לתוכן **שלפני** השינוי, ולא ל-null.
          //
          // באתחול ל-null, הקריאה הראשונה הייתה קובעת ``last`` לערך שכבר
          // השתנה — ואז "המצב הקודם" היה זהה לחדש ושום דבר לא נדחף
          // למחסנית. כלומר בדיוק התרחיש שהפיצ'ר נועד לו — בחירת-הכל
          // והדבקה — לא היה ניתן לביטול. נתפס בבדיקה: 21 תווים אחרי
          // ביטול במקום המקור המלא.
          const seed = (entry.data && typeof entry.data.content === 'string') ? entry.data.content : '';
          entry.undo = { stack: [], burstFrom: null, timer: null, last: seed };
        }
        return entry.undo;
      }

      // הקלדה רצופה היא פעולה אחת, לא מאה. צילום המצב נלקח **לפני** תחילת
      // ההתפרצות, ונדחף למחסנית רק אחרי שהמשתמש עצר — כך שהדבקה בודדת היא
      // בדיוק צעד אחד לבטל.
      _recordUndoBurst(el, textarea){
        try {
          const st = this._undoState(el);
          if (!st) return;
          const current = String(textarea.value == null ? '' : textarea.value);
          if (st.burstFrom === null) st.burstFrom = st.last;
          st.last = current;
          try { clearTimeout(st.timer); } catch(_) {}
          st.timer = setTimeout(() => {
            const from = st.burstFrom;
            st.burstFrom = null;
            st.timer = null;
            if (from !== null && from !== st.last) this._pushUndo(el, from);
            this._syncUndoButton(el);
          }, UNDO_BURST_MS);
          // הכפתור מתעורר כבר עכשיו, ולא בעוד 600 מילישניות
          this._syncUndoButton(el);
        } catch(_) {}
      }

      // כתיבה תכנותית ל-textarea (המשך רשימה, וכל מה שיבוא אחריו).
      //
      // ``input`` נורה רק על הקלדה של אדם. שינוי שנעשה בקוד חייב להירשם
      // בעצמו, אחרת המחסנית מפספסת אותו ו-``last`` נשאר על ערך שכבר לא
      // בשדה — מה שהופך את הביטול הבא לשחזור של טקסט שגוי.
      _noteProgrammaticEdit(el, textarea, before){
        try {
          const st = this._undoState(el);
          if (!st) return;
          const after = String(textarea.value == null ? '' : textarea.value);
          if (after === before) return;
          // סוגרים התפרצות פתוחה כדי שהצעד הזה לא ייבלע לתוכה
          try { clearTimeout(st.timer); } catch(_) {}
          st.timer = null;
          const from = (st.burstFrom !== null) ? st.burstFrom : before;
          st.burstFrom = null;
          st.last = after;
          if (from !== after) this._pushUndo(el, from);
          this._syncUndoButton(el);
        } catch(_) {}
      }

      // תוכן סמכותי מהשרת מאפס את נקודת ההשוואה.
      //
      // בלי זה ``st.last`` נשאר על התוכן שלפני הסימון, העריכה הבאה דוחפת
      // אותו למחסנית, וביטול אחד היה מוחק את הסימון שהשרת אישר — כלומר
      // דורס כתיבה מאומתת בתוכן ישן.
      _resetUndoBaseline(el, content){
        try {
          const st = this._undoState(el);
          if (!st) return;
          try { clearTimeout(st.timer); } catch(_) {}
          st.timer = null;
          st.burstFrom = null;
          st.last = String(content == null ? '' : content);
          // ההתפרצות הממתינה נסגרה, ולכן העומק ירד. בלי הסנכרון הזה
          // הכפתור נשאר דלוק על מחסנית ריקה — לחיצה עליו לא עושה כלום,
          // וזה בדיוק סוג השקר שהכפתור הזה נבנה כדי לא לספר.
          this._syncUndoButton(el);
        } catch(_) {}
      }

      _pushUndo(el, snapshot){
        try {
          const st = this._undoState(el);
          if (!st) return;
          if (st.stack.length && st.stack[st.stack.length - 1] === snapshot) return;
          st.stack.push(snapshot);
          if (st.stack.length > UNDO_MAX_STEPS) st.stack.shift();
          this._syncUndoButton(el);
        } catch(_) {}
      }

      // האם יש התפרצות פתוחה שטרם נדחפה למחסנית.
      //
      // זה מה שהופך את התרחיש המרכזי לעביד: מיד אחרי הדבקה המחסנית עדיין
      // ריקה — הצילום ממתין ל-600 מילישניות של שקט — והכפתור היה מושבת
      // בדיוק ברגע שבו הוא הכי נחוץ.
      _hasPendingUndoBurst(st){
        return !!(st && st.burstFrom !== null && st.burstFrom !== st.last);
      }

      _syncUndoButton(el){
        try {
          const btn = el.querySelector('.sticky-note-undo');
          if (!btn) return;
          const st = this._undoState(el);
          const depth = st ? st.stack.length : 0;
          const pending = this._hasPendingUndoBurst(st) ? 1 : 0;
          btn.disabled = (depth + pending) === 0;
          btn.title = (depth + pending)
            ? `בטל שינוי אחרון (${depth + pending} צעדים שמורים)`
            : 'אין מה לבטל';
        } catch(_) {}
      }

      _undoLastChange(el){
        try {
          const st = this._undoState(el);
          const textarea = el.querySelector('.sticky-note-content');
          if (!st || !textarea) return;
          // ההתפרצות הממתינה נסגרת **לפני** בדיקת המחסנית הריקה, לא אחריה:
          // מיד אחרי הדבקה היא כל מה שיש, והיציאה המוקדמת הייתה בולעת בדיוק
          // את התרחיש שהפיצ'ר נבנה בשבילו.
          try { clearTimeout(st.timer); } catch(_) {}
          st.timer = null;
          if (this._hasPendingUndoBurst(st)) {
            st.stack.push(st.burstFrom);
            if (st.stack.length > UNDO_MAX_STEPS) st.stack.shift();
          }
          st.burstFrom = null;
          if (!st.stack.length) return;

          const restored = st.stack.pop();
          textarea.value = restored;
          st.last = restored;
          const entry = this._getEntry(el);
          if (entry && entry.data) entry.data.content = restored;
          this._checkContentLength(el, restored);
          this._queueSave(el, { content: restored });
          this._syncTaskView(el);
          this._syncUndoButton(el);
        } catch(e) { console.warn('sticky note: undo failed', e); }
      }

      // ----- העתקה -----
      //
      // ``navigator.clipboard`` אינו זמין בהקשר לא-מאובטח ועלול להיחסם
      // בהרשאות. יש נפילה חיננית, ובכל מקרה **חיווי גלוי** — כפתור שנלחץ
      // ולא קורה כלום הוא בדיוק הכשל השקט שהפיצ'ר הזה לא מרשה לעצמו.
      async _copyNoteContent(el){
        const textarea = el.querySelector('.sticky-note-content');
        const text = textarea ? String(textarea.value == null ? '' : textarea.value) : '';
        let ok = false;
        try {
          if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(text);
            ok = true;
          }
        } catch(_) { ok = false; }
        if (!ok) ok = this._copyViaFallback(text);
        this._flashCopyResult(el, ok);
      }

      _copyViaFallback(text){
        try {
          const tmp = document.createElement('textarea');
          tmp.value = text;
          tmp.setAttribute('readonly', '');
          tmp.style.position = 'fixed';
          tmp.style.opacity = '0';
          document.body.appendChild(tmp);
          tmp.select();
          const ok = document.execCommand && document.execCommand('copy');
          document.body.removeChild(tmp);
          return !!ok;
        } catch(_) { return false; }
      }

      _flashCopyResult(el, ok){
        try {
          // מחלקה יציבה ולא ה-title, שאותו הפונקציה הזו עצמה משנה
          const target = el.querySelector('.sticky-note-copy') || el;
          const cls = ok ? 'is-copy-done' : 'is-copy-fail';
          target.classList.add(cls);
          if (!ok) target.title = 'ההעתקה נחסמה בדפדפן — סמנו והעתיקו ידנית';
          setTimeout(() => {
            try {
              target.classList.remove(cls);
              if (!ok) target.title = 'העתק את תוכן הפתק';
            } catch(_) {}
          }, 1800);
        } catch(_) {}
      }

      // חיווי אורך. השרת דוחה תוכן שחורג מהתקרה ב-``content_too_long``,
      // אבל דחייה שמגיעה רק אחרי ניסיון שמירה היא מאוחרת מדי — המשתמש
      // כבר הדביק והמשיך. כאן זה נראה בזמן ההקלדה.
      _checkContentLength(el, text){
        try {
          const cap = maxNoteChars();
          // ``String.length`` סופר יחידות UTF-16, והשרת סופר תווי Unicode.
          // אימוג'י הוא יחידה אחת בפייתון ושתיים ב-JS, ולכן 10,001 אימוג'ים
          // קיבלו אזהרת חריגה על תוכן שהשרת מקבל בלי בעיה — פי שניים.
          // ``Array.from`` מפצל לקוד-פוינטים, וזו בדיוק הספירה של פייתון.
          const len = Array.from(String(text == null ? '' : text)).length;
          let warn = el.querySelector('.sticky-note-warn');
          if (!cap || len <= cap) {
            if (warn && warn.remove) warn.remove();
            el.classList.remove('has-length-error');
            return false;
          }
          if (!warn) {
            warn = createEl('div', 'sticky-note-warn');
            el.appendChild(warn);
          }
          // הניסוח מדויק לחוזה השרת: העדכון כולו נדחה, לא רק הזנב
          warn.textContent = `הפתק ארוך מהמותר: ${len} מתוך ${cap} תווים. יש לקצר אותו כדי שיישמר.`;
          el.classList.add('has-length-error');
          return true;
        } catch(_) { return false; }
      }

      async _onTaskToggle(el, box){
        const noteId = el.dataset.noteId;
        const entry = this.notes.get(noteId);
        if (!entry) return;
        const index = parseInt(box.dataset.taskIndex, 10);
        const desired = !!box.checked;

        // לפני הכול: לרוקן שמירה תלויה. בלי זה, ``_queueSave`` שממתין
        // ב-debounce של חצי שנייה היה נוחת **אחרי** ה-toggle וכותב תוכן
        // ישן — כלומר מבטל אותו. באג סדר אמיתי, ושורה אחת מונעת אותו.
        try { await this._flushFor(el); } catch(_) {}

        box.disabled = true;
        el.classList.add('is-task-pending');
        try {
          const resp = await fetch(`/api/sticky-notes/note/${encodeURIComponent(noteId)}/task`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ index, checked: desired, prev_updated_at: el.dataset.updatedAt || undefined })
          });
          const data = await resp.json().catch(() => null);

          if (resp.ok && data && data.ok) {
            // מרנדרים מחדש **מהתוכן שהשרת החזיר**, לא מהמצב שבמסך. כך
            // מיושרות גם סטיות אחרות שנוצרו בינתיים.
            this._applyServerContent(el, entry, data.content, data.updated_at);
            return;
          }

          // כשל. אמת השרת עדיפה על היפוך נאיבי: אם חזר תוכן — מרנדרים
          // ממנו. אחרת מחזירים את התיבה למצב הקודם.
          if (data && typeof data.content === 'string') {
            this._applyServerContent(el, entry, data.content, data.updated_at);
          } else {
            box.checked = !desired;
          }
          this._showTaskError(el);
        } catch(_) {
          box.checked = !desired;
          this._showTaskError(el);
        } finally {
          box.disabled = false;
          el.classList.remove('is-task-pending');
        }
      }

      _applyServerContent(el, entry, content, updatedAt){
        if (typeof content !== 'string') return;
        const textarea = el.querySelector('.sticky-note-content');
        // התוכן שלפני — **לפני** שהוא נדרס. הוא הצעד שהמשתמש עשוי לרצות
        // לבטל, וההערה הקודמת כאן טענה שהמחסנית כבר שומרת אותו. היא לא:
        // סימון צ'קבוקס בפתק שלא נערך משאיר את המחסנית ריקה לגמרי, ואז
        // אין שום דרך לחזור מהסימון דרך כפתור הביטול.
        const before = textarea ? String(textarea.value == null ? '' : textarea.value) : null;
        // התפרצות הקלדה שעדיין פתוחה — הצילום שלה נלקח **לפני** ההקלדה,
        // ו-``_resetUndoBaseline`` עומד למחוק אותו. בלי לשמור אותו כאן,
        // תוכן שמגיע מהשרת באמצע הקלדה היה מוחק את נקודת הפתיחה, וביטול
        // היה מחזיר לסוף ההתפרצות במקום לתחילתה — כלומר ההקלדה כולה אבודה.
        const st = this._undoState(el);
        const burstFrom = this._hasPendingUndoBurst(st) ? st.burstFrom : null;
        if (textarea) textarea.value = content;
        if (entry && entry.data) entry.data.content = content;
        if (updatedAt) el.dataset.updatedAt = updatedAt;
        // נקודת ההשוואה עוברת לתוכן הסמכותי, אחרת העריכה הבאה הייתה דוחפת
        // את התוכן הישן למחסנית וביטול היה מוחק כתיבה שהשרת אישר.
        this._resetUndoBaseline(el, content);
        // שני צעדים נפרדים, כי באמת קרו שני דברים: המשתמש הקליד, ואז
        // השרת שינה. הסדר הוא LIFO — הביטול הראשון מחזיר למה שהוקלד,
        // והשני למה שהיה לפני ההקלדה.
        if (burstFrom !== null && burstFrom !== before) this._pushUndo(el, burstFrom);
        if (before !== null && before !== content) this._pushUndo(el, before);
        this._syncTaskView(el);
      }

      // כשל שמירה חייב להיראות. עד היום הוא נכתב ל-``console`` בלבד, והפתק
      // המשיך להיראות שמור לגמרי — כולל במקרה שבו התוכן נדחה בגלל אורך.
      // כשל סופי מול כשל זמני.
      //
      // עד היום כל ``!resp.ok`` הוחזר ל-``pending``, וה-auto-flush ניסה
      // שוב לנצח. תוכן שנדחה ב-400 (ארוך מדי, b64 פגום) לא הופך לתקין
      // בניסיון הבא — זו לולאה חמה שגם מסתירה את הכשל מהמשתמש. 409 הוא
      // היוצא מן הכלל: הוא נפתר עם חותמת זמן טרייה, ולכן כן חוזר לתור.
      _isPermanentFailure(status){
        const code = Number(status);
        return Number.isFinite(code) && code >= 400 && code < 500 && code !== 409 && code !== 408 && code !== 429;
      }

      _markSaveFailed(id){
        try {
          const entry = this.notes.get(String(id));
          if (entry && entry.el && entry.el.classList) entry.el.classList.add('has-save-error');
        } catch(_) {}
      }

      _clearSaveFailed(id){
        try {
          const entry = this.notes.get(String(id));
          if (entry && entry.el && entry.el.classList) entry.el.classList.remove('has-save-error');
        } catch(_) {}
      }

      _showTaskError(el){
        try {
          el.classList.add('has-task-error');
          setTimeout(() => { try { el.classList.remove('has-task-error'); } catch(_) {} }, 2500);
        } catch(_) {}
      }

      // מצב המיקום של פתק, כערך אחד: 'surface' | 'anchored' | 'screen'.
      //
      // בפתק לוח השדה ``mode`` מגיע מהשרת ומנצח. בפתק קובץ אין שדה כזה,
      // והמצב נגזר מהסנטינלים בדיוק כמו קודם — ולכן מסלול הקובץ יוצא
      // ביט-זהה.
      //
      // למה בכלל שדה אמיתי ללוח: התנאי לזיהוי anchored מפיל לשם **כל**
      // מחרוזת שאינה סנטינל. בקובץ יש לזה משמעות; בלוח ``anchor_id`` הוא
      // שדה חסר-פשר, וכל ערך שיזלוג לשם — מגיבוי, מ-MCP, מבאג — היה
      // מעביר את הפתק למצב שבו ``_updateAnchoredNotePosition`` מחשב top
      // מעוגן ל-null. פתק שנעלם.
      _resolveMode(note){
        if (!note) return 'screen';
        if (note.mode === 'surface' || note.mode === 'screen' || note.mode === 'anchored') {
          // 'anchored' דורש מקור שורות; בלעדיו אין למה להיצמד.
          if (note.mode === 'anchored' && !this._hasAnchorHost) return 'surface';
          return note.mode;
        }
        if (note.anchor_id === PIN_SENTINEL) return 'surface';
        const hasAnchor = !!(note.anchor_id && note.anchor_id !== PIN_SENTINEL && note.anchor_id !== FLOATING_SENTINEL);
        const hasLine = Number.isInteger(note.line_start) && note.line_start > 0;
        // התנאי מותנה ב-``!this.boardId`` ולא ב-``_hasAnchorHost`` בכוונה:
        // כך מסלול הקובץ יוצא זהה בדיוק לקוד הקודם, גם במקרה הקצה שבו
        // ``#md-content`` חסר. בלוח פשוט אין מצב anchored.
        if ((hasAnchor || hasLine) && !this.boardId) return 'anchored';
        return 'screen';
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
          const resolved = this._resolveMode(note);
          const isPinned = resolved === 'surface';
          const isAnchored = resolved === 'anchored';
          if (isPinned) {
            el.classList.add('is-pinned');
            el.classList.remove('is-floating');
            el.style.position = 'absolute';
            let targetX = (typeof note.position?.x === 'number') ? note.position.x : currentAbsX;
            let targetY = (typeof note.position?.y === 'number') ? note.position.y : currentAbsY;
            if (!Number.isFinite(targetX)) targetX = currentAbsX;
            if (!Number.isFinite(targetY)) targetY = currentAbsY;
            if (this.boardId) {
              const clamped = this._clampToSurface(el, targetX, targetY, note);
              targetX = clamped.x; targetY = clamped.y;
            }
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
            if (note.anchor_id && note.anchor_id !== PIN_SENTINEL && note.anchor_id !== FLOATING_SENTINEL) {
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
          // **ורוד = מוצמד למשטח שמתחתיו**, בקובץ ובלוח כאחד. בקובץ זה
          // המסמך, בלוח זה הלוח. שני סימנים שונים לאותה משמעות באותה
          // מערכת הם באג בפני עצמו.
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
      // מסמנים את הפתק כ־floating מפורש, כדי שבטעינה הבאה המיגרציה הרכה
      // ב־_renderNote לא תעגן אותו מחדש ותדרוס את הבחירה של המשתמש.
      entry.data.anchor_id = FLOATING_SENTINEL;
      entry.data.anchor_text = '';
      entry.data.line_start = null;
      entry.data.line_end = null;
      if (el.dataset && el.dataset.pinned) { delete el.dataset.pinned; }
      if (el.dataset && el.dataset.anchorId) { delete el.dataset.anchorId; }
      if (el.dataset && el.dataset.anchorLine) { delete el.dataset.anchorLine; }
      if (el.dataset && el.dataset.relYOffset) { delete el.dataset.relYOffset; }
      this._applyPositionMode(el, entry.data, { reflow: true });
      this._queueSave(el, Object.assign({}, payload, { anchor_id: FLOATING_SENTINEL, anchor_text: null, line_start: null, line_end: null }));
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

    _handleListContinuation(textarea){
      try {
        const val = textarea.value;
        const cur = textarea.selectionStart;
        const lineStart = val.lastIndexOf('\n', cur - 1) + 1;
        const line = val.slice(lineStart, cur);
        // תבניות: - [ ] , - [x] , - [X] , - , * , • , 1. , >
        const patterns = [
          { re: /^(\s*)- \[[ xX]\]\s*/, next: (m) => m[1] + '- [ ] ' },
          { re: /^(\s*)([-*])\s*/, next: (m) => m[1] + m[2] + ' ' },
          { re: /^(\s*)•\s*/, next: (m) => m[1] + '• ' },
          { re: /^(\s*)(\d+)\.\s*/, next: (m) => m[1] + (parseInt(m[2], 10) + 1) + '. ' },
          { re: /^(\s*)>\s*/, next: (m) => m[1] + '> ' },
        ];
        for (const p of patterns) {
          const match = line.match(p.re);
          if (match) {
            const textAfterMarker = line.slice(match[0].length);
            if (textAfterMarker.trim() === '') {
              // כפול אנטר → מחק את שורת הסמן הריקה ויוצא מהרשימה
              textarea.value = val.slice(0, lineStart) + val.slice(cur);
              textarea.selectionStart = textarea.selectionEnd = lineStart;
              return false;
            }
            return '\n' + p.next(match);
          }
        }
        return null;
      } catch (_) {
        return null;
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
        // אותו מרחב קואורדינטות שבו נשמר ``position`` — אחרת נפילה לערך
        // הזה הייתה מקפיצה את הפתק בדיוק בהפרש בין המרחבים.
        const origin = isAbsolute ? this._positionOrigin(el) : { x: 0, y: 0 };
        const fallbackLeft = Math.round(r.left - origin.x);
        const fallbackTop = Math.round(r.top - origin.y);
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
        let nx = Math.round(origLeft + dx + sx);
        let ny = Math.round(origTop + dy + sy);
        // חסימה כבר בזמן הגרירה, ולא רק בשמירה: אחרת אפשר לגרור את
        // הכותרת אל מעל קצה המשטח, ומשם אין דרך חזרה — הכותרת *היא*
        // ידית הגרירה.
        // שני המצבים נחסמים — כל אחד מול מסגרת הייחוס שלו.
        const floating = el.classList && el.classList.contains('is-floating');
        if (floating) {
          const c = this._clampToViewport(el, nx, ny);
          nx = c.x; ny = c.y;
        } else if (this.boardId && el.classList && el.classList.contains('is-pinned')) {
          const c = this._clampToSurface(el, nx, ny, null);
          nx = c.x; ny = c.y;
        }
        el.style.left = nx + 'px';
        el.style.top = ny + 'px';
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
        this._updateSurfaceExtent();
      };
      // ``touch-action`` מוצהר ב-CSS על ``.sticky-note-drag``, ולא כאן.
      //
      // סגנון inline גובר על גיליון סגנונות, ולכן ההצבה שהייתה כאן ביטלה
      // בשקט את ``.is-editing-title .sticky-note-drag { touch-action: auto }``
      // — הכלל שאמור להחזיר מגע לשדה השם בזמן עריכה. נמדד בכרומיום:
      // הערך נשאר ``none`` גם אחרי הוספת המחלקה. הצהרה אחת, במקום אחד.
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
        if (this.boardId) { this._toggleBoardMode(el); return; }
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

    // בלוח, 📌 מחליף בין ``surface`` (יושב על הלוח וזז איתו) לבין ``screen``
    // (צף מול המסך ונשאר גלוי בגלילה).
    //
    // **זה שורש הבאג "הכפתור שבור".** ``_pinNote`` כותב סנטינל ל-
    // ``anchor_id``, אבל ``_resolveMode`` קורא את ``mode`` **ראשון** — ולכן
    // בפתק לוח הסנטינל לא שינה כלום. מה שכן קרה זה שהמיקום נשמר מחדש,
    // כלומר הפתק זז ולא נעץ. בדיוק מה שנצפה.
    _toggleBoardMode(el){
      const entry = this._getEntry(el);
      if (!entry || !entry.data) return;
      const current = this._resolveMode(entry.data);
      const next = current === 'screen' ? 'surface' : 'screen';
      // המיקום נמדד במרחב **היעד**: ``surface`` נמדד מול המשטח ו-``screen``
      // מול המסמך. מדידה במרחב המקור הייתה מקפיצה את הפתק בדיוק בהפרש.
      const payload = this._notePayloadFromEl(el, next);
      entry.data.mode = next;
      entry.data.position = payload.position;
      entry.data.size = payload.size;
      this._applyPositionMode(el, entry.data, { reflow: next === 'screen' });
      this._queueSave(el, Object.assign({}, payload, { mode: next }));
      this._flushFor(el);
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
        // פתק שגדל כלפי מטה מאריך את המשטח, בדיוק כמו פתק שנגרר לשם
        this._updateSurfaceExtent();
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
            const body = JSON.stringify(withContentB64(data));
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

    // מיזוג שבו ה**חדש** מנצח: מידע טרי מהשרת (``prev_updated_at``) שחייב
    // לדרוס את מה שבתור.
    // החזרת מטען **ישן** לתור אחרי כשל — וכאן ה**קיים** מנצח.
    //
    // זה השורש של אובדן תוכן שנמדד: ``_flushFor`` מוציא את המטען מהתור
    // לפני שהוא ממתין לרשת, ואם המשתמש הקליד בזמן ההמתנה נוצרה רשומה
    // חדשה. ``_mergePending`` היה עושה ``Object.assign(חדש, ישן)`` —
    // כלומר הישן דרס את מה שהמשתמש בדיוק כתב.
    //
    // אותה פונקציה שירתה שתי כוונות הפוכות: "החזר מטען שנכשל" ו"עדכן
    // מידע טרי מהשרת". הפרדה ביניהן היא התיקון, לא סדר הפרמטרים.
    _restorePending(id, payload){
      if (!id || !payload) return;
      const restored = this._clonePayload(payload) || {};
      const existing = this._pending.get(id);
      // שדות מהעריכה החדשה גוברים; הישן רק ממלא מה שחסר
      const next = existing
        ? Object.assign(restored, this._clonePayload(existing) || {})
        : restored;
      this._pending.set(id, next);
      this._syncEntryFromFragment(id, next);
      try { this._saveDebounced(); } catch(_) {}
      this._ensureBackgroundAutoFlush();
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

    _sendUpdate(id, data, seqAtSend){
      const original = this._clonePayload(data) || {};
      const payload = withContentB64(original);
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
          // 409 נושא שני מובנים שונים לגמרי, ורק ``error`` מבדיל ביניהם.
          // התנגשות גרסה נפתרת בניסיון חוזר עם חותמת טרייה; שם תפוס לא
          // ייפתר לעולם בניסיון חוזר — הוא דורש שהמשתמש יבחר שם אחר.
          // בלי ההבחנה הזו כל הקלדה של שם קיים נכנסה ללולאת ניסיונות
          // אינסופית, ובלי שום חיווי: מסלול ה-409 אינו מסמן כשל.
          if (resp.status === 409 && json && json.error === 'duplicate_title') {
            this._markTitleConflict(id, true);
            if ((this._pendingSeq.get(String(id)) || 0) === (seqAtSend || 0)) {
              this._pending.delete(String(id));
            }
            return false;
          }
          if (resp.status === 409) {
            console.warn('sticky note update conflict, retrying once with fresh timestamp', id);
            let serverUpdatedAt = null;
            if (json && json.updated_at) {
              serverUpdatedAt = String(json.updated_at);
              this._setNoteUpdatedAt(id, serverUpdatedAt);
            }
            if (serverUpdatedAt) {
              const retryOriginal = Object.assign({}, original, { prev_updated_at: serverUpdatedAt });
              const retryPayload = withContentB64(retryOriginal);
              try {
                const { resp: retryResp, json: retryJson } = await send(retryPayload);
                if (retryResp.status === 409 && retryJson && retryJson.error === 'duplicate_title') {
                  this._markTitleConflict(id, true);
                  if ((this._pendingSeq.get(String(id)) || 0) === (seqAtSend || 0)) {
                    this._pending.delete(String(id));
                  }
                  return false;
                }
                if (retryResp.status === 409) {
                  console.warn('sticky note update conflict persisted after retry', id);
                  if (retryJson && retryJson.updated_at) {
                    this._setNoteUpdatedAt(id, String(retryJson.updated_at));
                    this._restorePending(id, retryOriginal);
                    this._mergePending(id, { prev_updated_at: String(retryJson.updated_at) });
                  } else if (serverUpdatedAt) {
                    this._restorePending(id, retryOriginal);
                  }
                  return false;
                }
                if (retryJson && retryJson.updated_at) {
                  this._setNoteUpdatedAt(id, String(retryJson.updated_at));
                }
                return true;
              } catch(retryErr) {
                console.warn('sticky note retry failed', id, retryErr);
                this._restorePending(id, retryOriginal);
                return false;
              }
            }
            this._restorePending(id, original);
            if (serverUpdatedAt) this._mergePending(id, { prev_updated_at: serverUpdatedAt });
            return false;
          }
          if (json && json.updated_at) {
            this._setNoteUpdatedAt(id, String(json.updated_at));
          }
          if (!resp.ok) {
            this._markSaveFailed(id);
            if (!this._isPermanentFailure(resp.status)) {
              // כשל זמני — מחזירים לתור, אבל בלי לדרוס עריכה חדשה יותר
              this._restorePending(id, original);
            } else if ((this._pendingSeq.get(String(id)) || 0) === (seqAtSend || 0)) {
              // כשל סופי לא ינוסה שוב — אבל רק אם לא הוקלד משהו חדש
              // בינתיים. מחיקה עיוורת כאן מוחקת בדיוק את מה שהמשתמש כתב.
              this._pending.delete(String(id));
            }
          } else {
            this._clearSaveFailed(id);
            // רק אם השם עצמו הוא מה שנשמר. שמירה מוצלחת של גרירה או שינוי
            // גודל אינה אומרת דבר על השם — הוא נשאר תפוס בשרת — וניקוי
            // הסימון כאן היה מציג "נשמר" על שדה שהשרת לא קיבל.
            if ('title' in original) this._markTitleConflict(id, false);
          }
          return resp.ok;
        } catch(err) {
          console.warn('save note failed', id, err);
          this._markSaveFailed(id);
          this._restorePending(id, original);
          return false;
        }
      };

      const promise = attempt();
      this._registerInFlight(id, original, promise);
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
      const batchPayload = snapshots.map(s => Object.assign({ id: s.id }, withContentB64(s.payload)));
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
                this._clearSaveFailed(id);
                // כמו במסלול הבודד: רק שמירה שכללה שם מנקה את הסימון
                if (snap && snap.payload && 'title' in snap.payload) this._markTitleConflict(id, false);
                // clear pending only if no newer edits arrived during request
                if (snap && currentSeq === snap.seq) {
                  this._pending.delete(id);
                }
              } else if (Number(result.status) === 409 && result.error === 'duplicate_title') {
                // שם תפוס — לא התנגשות גרסה, ולכן לא חוזר לתור
                this._markTitleConflict(id, true);
                if (snap && currentSeq === snap.seq) this._pending.delete(id);
              } else if (Number(result.status) === 409) {
                // conflict – set prev_updated_at for next retry without overriding newer local edits
                const patch = {};
                if (result.updated_at) patch.prev_updated_at = String(result.updated_at);
                this._mergePending(id, patch);
              } else {
                this._markSaveFailed(id);
                if (this._isPermanentFailure(result.status)) {
                  // 400 לא יתוקן בניסיון חוזר. מפסיקים לנסות ומשאירים את
                  // הסימון הגלוי — אבל רק אם לא הוקלד משהו חדש בינתיים,
                  // בדיוק כמו במסלול ההצלחה.
                  if (snap && currentSeq === snap.seq) {
                    this._pending.delete(id);
                  }
                } else if (snap) {
                  // כשל זמני – מחזירים את התמונה, בלי לדרוס עריכה חדשה
                  this._restorePending(id, snap.payload);
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
          // גרסת התור נלקחת **לפני** המחיקה, ומועברת הלאה — בדיוק כמו
          // ב-``_flushFor``. בלעדיה ``seqAtSend`` היה ``undefined``, כל
          // ההשוואות בענפי הכשל נפלו על 0, והשומר "אל תמחק עריכה חדשה
          // יותר" לא היה יכול להתאים לעולם.
          const seqAtSend = this._pendingSeq.get(id) || 0;
          this._pending.delete(id);
          await this._sendUpdate(id, current, seqAtSend);
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
      // גרסת התור ברגע השליחה. כל עריכה נוספת מקדמת אותה, וכך אפשר
      // לדעת בכשל אם מה שבתור הוא עדיין מה ששלחנו או משהו חדש יותר.
      const seqAtSend = this._pendingSeq.get(id) || 0;
      this._pending.delete(id);
      await this._sendUpdate(id, data, seqAtSend);
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
      // טיימר ההתפרצות מחזיק הפניה ל-``el`` ול-``entry``. בלי הניקוי הזה
      // הוא ימשיך לרוץ אחרי שהפתק ירד מה-DOM.
      this._clearUndoTimer(el);
      try { el.remove(); } catch(_) {}
      this.notes.delete(id);
      // אורך המשטח נגזר מהפתקים שעליו. בלי הקריאה הזו מחיקת הפתק התחתון
      // משאירה ``min-height`` שמתאר מצב שכבר לא קיים.
      this._updateSurfaceExtent();
    }

    _clearUndoTimer(el){
      try {
        const entry = this._getEntry(el);
        const st = entry && entry.undo;
        if (!st || !st.timer) return;
        try { clearTimeout(st.timer); } catch(_) {}
        st.timer = null;
      } catch(_) {}
    }

    _reflowWithinViewport(target){
      const items = target ? [target] : Array.from(this.container.querySelectorAll('.sticky-note'));
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
        const md = this._anchorHost;
        if (!md) return;

        // MutationObserver – שינויים מבניים ב־DOM (תוכן חדש/מוסר). משפיע על אינדקס
        // העוגנים עצמו ולכן מחייב rebuild + reposition.
        if (typeof MutationObserver !== 'undefined') {
          const mObs = new MutationObserver(() => {
            try { this._rebuildLineIndex(); this._updateAnchoredPositions(); } catch(_) {}
          });
          mObs.observe(md, { childList: true, subtree: true, characterData: true });
          this._domObserver = mObs;
        }

        // ResizeObserver – שינויי גובה/פריסה (פתיחת ::: details, טעינת תמונות, resize).
        // חשוב: קורא *רק* ל־_updateAnchoredPositions, לא ל־rebuild, כדי לא לסרוק את כל
        // האלמנטים עם [data-source-line] במסמכים ארוכים בכל פריים של אנימציה.
        // ה־_updateAnchoredPositions עובר רק על פתקים מעוגנים וקורא את ה־rect של העוגן
        // הספציפי שלהם on-the-fly, כך שהעלות פרופורציונלית למספר הפתקים בלבד.
        if (typeof ResizeObserver !== 'undefined') {
          let pending = false;
          const rObs = new ResizeObserver(() => {
            if (pending) return;
            pending = true;
            const run = () => {
              pending = false;
              try { this._updateAnchoredPositions(); } catch(_) {}
            };
            try { requestAnimationFrame(run); } catch(_) { run(); }
          });
          try { rObs.observe(md); } catch(_) {}
          this._resizeObserver = rObs;
        }
      } catch(_) {}
    }

    _rebuildLineIndex(){
      try {
        // סמנטיקה חדשה: Map<lineNumber, Element> במקום Map<lineNumber, Y>.
        // שמירת רפרנס בלבד – חישוב ה־Y נעשה on-demand דרך _getYForLine,
        // כדי להימנע מ־Layout Thrashing בזמן אנימציות resize.
        this._lineIndex = new Map();
        const md = (this._anchorHost || document);

        // ── MD preview: אלמנטים עם data-source-line מתוך ה־Source Mapping Plugin ──
        // ה־value של data-source-line הוא 0-based (מתוך token.map[0] של markdown-it).
        // אנחנו שומרים כמפתח את הערך +1 כדי לשמור על הקונבנציה 1-indexed שקיימת
        // בשאר הקוד (הבדיקות `line_start > 0`).
        const sourceLineNodes = md.querySelectorAll('[data-source-line]');
        sourceLineNodes.forEach((node) => {
          const raw = parseInt(node.getAttribute('data-source-line'), 10);
          if (!Number.isFinite(raw) || raw < 0) return;
          const key = raw + 1;
          if (!this._lineIndex.has(key)) this._lineIndex.set(key, node);
        });

        // ── Fallback: Pygments .linenos (לא בשימוש ב־MD preview, נשמר לתאימות) ──
        if (this._lineIndex.size === 0) {
          const sel = '.highlighttable .linenos pre > span, .highlighttable .linenos pre > a, .linenodiv pre > span, .linenodiv pre > a, .linenos span, .linenos a';
          const nodes = md.querySelectorAll(sel);
          nodes.forEach((node) => {
            const ln = this._extractLineNumberFromNode(node);
            if (!ln) return;
            if (!this._lineIndex.has(ln)) this._lineIndex.set(ln, node);
          });
        }
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
      try {
        // קבל רפרנס מה־index; אם האלמנט התנתק מה־DOM, נרענן חיפוש טרי
        let node = this._lineIndex ? this._lineIndex.get(lineNum) : null;
        if (node && !node.isConnected) node = null;
        if (!node) {
          const md = (this._anchorHost || document);
          // MD preview: data-source-line הוא 0-based ולכן נחסר 1
          const sourceVal = lineNum - 1;
          if (sourceVal >= 0) {
            node = md.querySelector(`[data-source-line="${sourceVal}"]`);
          }
          if (!node) {
            // Fallback: Pygments linenos
            const sel = `.highlighttable .linenos pre > span:nth-child(${lineNum}), .highlighttable .linenos pre > a:nth-child(${lineNum}), .linenodiv pre > span:nth-child(${lineNum}), .linenodiv pre > a:nth-child(${lineNum}), .linenos span:nth-child(${lineNum}), .linenos a:nth-child(${lineNum})`;
            node = document.querySelector(sel);
          }
          if (node && this._lineIndex) this._lineIndex.set(lineNum, node);
        }
        if (node) {
          const scroll = getScrollOffsets();
          return Math.round(node.getBoundingClientRect().top + scroll.y);
        }
      } catch(_) {}
      return null;
    }

    _findNearestSourceLineElement(targetDocY){
      // מחזיר את האלמנט עם [data-source-line] שה־doc-Y שלו הכי קרוב ל־targetDocY.
      // בשימוש ל: (א) עיגון אוטומטי של פתקים חדשים; (ב) מיגרציה רכה של פתקים ישנים.
      try {
        const md = this._anchorHost;
        if (!md || !Number.isFinite(targetDocY)) return null;
        const nodes = md.querySelectorAll('[data-source-line]');
        if (!nodes.length) return null;
        const scroll = getScrollOffsets();
        let best = null;
        let bestDy = Infinity;
        nodes.forEach((node) => {
          const y = node.getBoundingClientRect().top + scroll.y;
          const dy = Math.abs(y - targetDocY);
          if (dy < bestDy) { bestDy = dy; best = node; }
        });
        return best;
      } catch(_) { return null; }
    }

    _getYForAnchor(anchorId){
      try {
        if (!anchorId) return null;
        const md = (this._anchorHost || document);
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
        const md = (this._anchorHost || document);
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
        } else if (data.anchor_id && data.anchor_id !== PIN_SENTINEL && data.anchor_id !== FLOATING_SENTINEL) {
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
          const isAnchored = (Number.isInteger(d.line_start) && d.line_start > 0) || (d.anchor_id && d.anchor_id !== PIN_SENTINEL && d.anchor_id !== FLOATING_SENTINEL);
          if (!isAnchored) continue;
          this._updateAnchoredNotePosition(entry.el, d);
        }
      } catch(_) {}
    }

    _parseNoteIdFromUrl(){
      try {
        const u = new URL(window.location.href);
        const q = (u.searchParams.get('note') || u.searchParams.get('note_id') || '').trim();
        if (q) return q;
        // hash formats: #note=ID or #note:ID
        const h = (u.hash || '').replace(/^#/, '');
        if (!h) return '';
        const m = h.match(/^note[:=](.+)$/i);
        return m ? decodeURIComponent(m[1]) : '';
      } catch(_) { return ''; }
    }

    _maybeScrollToNoteFromUrl(){
      const id = this._parseNoteIdFromUrl();
      if (!id) return;
      // נסה מייד, ואם טרם נטען – נסה שוב לאחר דיליי קצר
      const attempt = (triesLeft) => {
        try {
          const entry = this.notes.get(id);
          if (entry && entry.data) {
            this.scrollToNote(id);
            return;
          }
        } catch(_) {}
        if (triesLeft > 0) {
          setTimeout(() => attempt(triesLeft - 1), 200);
        }
      };
      attempt(8);
    }

    scrollToNote(noteId){
      try {
        const entry = this.notes.get(String(noteId));
        if (!entry || !entry.el || !entry.data) return;
        const data = entry.data;
        // אם יש עוגן – גלול לעוגן, אחרת ל-top של הפתק עצמו
        let top = null;
        if (data.anchor_id && data.anchor_id !== PIN_SENTINEL && data.anchor_id !== FLOATING_SENTINEL) {
          top = this._getYForAnchor(String(data.anchor_id));
        }
        if (top == null && Number.isInteger(data.line_start) && data.line_start > 0) {
          top = this._getYForLine(Number(data.line_start));
        }
        if (top == null) {
          // ודא שמיקום הפתק מעודכן ואז גלול לפתק
          this._updateAnchoredNotePosition(entry.el, data);
          const scroll = getScrollOffsets();
          top = Math.max(0, Math.round(entry.el.getBoundingClientRect().top + scroll.y) - 100);
        } else {
          top = Math.max(0, Number(top) - 100);
        }
        try { window.scrollTo({ top, behavior: 'smooth' }); } catch(_) { window.scrollTo(0, top); }
        // הדגשה קצרה להפניית תשומת לב
        try {
          entry.el.style.transition = 'box-shadow .2s ease';
          const old = entry.el.style.boxShadow;
          entry.el.style.boxShadow = '0 0 0 3px rgba(236, 72, 153, .6)';
          setTimeout(() => { entry.el.style.boxShadow = old || ''; }, 1200);
        } catch(_) {}
      } catch(_) {}
    }

    _clearAllNotes(){
      try {
        for (const [id, entry] of this.notes.entries()){
          // אותו נימוק כמו במחיקת פתק בודד: טיימר ההתפרצות מחזיק הפניה
          // ל-``entry``, והוא ימשיך לרוץ אחרי שהאלמנט ירד מה-DOM.
          try { if (entry && entry.el) this._clearUndoTimer(entry.el); } catch(_) {}
          try { entry && entry.el && entry.el.remove && entry.el.remove(); } catch(_) {}
        }
      } catch(_) {}
      this.notes.clear();
      this._updateSurfaceExtent();
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
      '.sticky-reminder-card{position:relative;background:var(--card-bg,rgba(255,255,255,0.95));color:var(--text-primary,#1f2933);border-radius:14px;box-shadow:0 12px 32px rgba(0,0,0,.25);width:min(420px,92vw);padding:12px;}'+
      '.sticky-reminder-header{display:flex;align-items:center;justify-content:space-between;padding:6px 8px 8px;}'+
      '.sticky-reminder-title{font-weight:700;font-size:1.05rem;}'+
      '.sticky-reminder-close{border:none;background:transparent;font-size:20px;cursor:pointer;color:var(--text-muted,#555);}'+
      '.sticky-reminder-body{display:flex;flex-direction:column;gap:12px;padding:6px 8px 10px;}'+
      '.sticky-reminder-section{display:block;}'+
      '.sticky-reminder-subtitle{font-weight:600;margin-bottom:6px;}'+
      '.sticky-reminder-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:6px;}'+
      '.sr-btn{padding:.5rem .75rem;border-radius:10px;border:1px solid var(--glass-border,rgba(0,0,0,.12));background:var(--bg-secondary,#f7fafc);color:var(--text-primary,#1f2933);cursor:pointer;}'+
      '.sr-btn:hover{background:var(--bg-tertiary,#edf2f7);}'+
      '.sticky-reminder-row{display:flex;gap:8px;align-items:center;}'+
      '.sr-dt{flex:1;min-width:0;padding:.5rem .6rem;border:1px solid var(--glass-border,#ddd);border-radius:8px;background:var(--bg-primary,#fff);color:var(--text-primary,inherit);}'+
      '.sr-save{padding:.5rem .75rem;border-radius:10px;border:1px solid var(--glass-border,rgba(0,0,0,.12));background:var(--primary,#667eea);color:var(--text-on-primary,#fff);cursor:pointer;}'
    );
    document.head.appendChild(style);
  } catch(_) {}

})();
