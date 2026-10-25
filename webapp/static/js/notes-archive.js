/**
 * עמוד הארכיון — רשת של כרטיסים, ופתק אחד שנפתח מעליהם.
 *
 * **מה העמוד מחזיק, ומה לא.** הכרטיסים הם של העמוד: הם נבנים מ-``GET /api/sticky-notes/archive``,
 * שמחזיר שם, צבע וזמן העברה ולא את גוף הפתק. הפתק הפתוח הוא **אותו רכיב פתק** של כל משטח —
 * ``StickyNotesManager`` במצב ``archive`` (``webapp/static/js/sticky-notes.js``) — והעמוד רק
 * מביא אותו (``GET /api/sticky-notes/archive/<id>``) ומוסר לו. כשהפתק נסגר, המנהל מחזיר את השם
 * והצבע העדכניים והכרטיס מתעדכן; כשהוא נמחק — הכרטיס יורד.
 *
 * **טעינה שנכשלה אינה "הארכיון ריק".** כל אחד משלושת המצבים — טעינה, שגיאה, ריק — מוצג בנפרד,
 * ושגיאה נושאת כפתור "נסו שוב".
 */
(function () {
  'use strict';

  /**
   * **רצף לטיני בתוך שם עברי** — מילה, נתיב (``/admin/mcp``), מזהה (``#3542``) או כמה כאלה עם
   * רווחים ביניהם. בפסקה RTL, ``/`` שבתחילת רצף כזה נשען על הרווח העברי שלפניו ונוחת בצד הלא
   * נכון (``admin/mcp/``), ולכן כל רצף כזה מבודד ככיוון LTR משלו. הביטוי לקוח מהעיצוב של העמוד
   * (``sticky_notes_Archive_design.html`` ב-Ck), שבו נבדק על שמות של פתקים אמיתיים.
   */
  var LATIN_RUN_RE = /(?:[\/.#@][A-Za-z0-9]|[A-Za-z])[\w.\/:#@+\-]*(?:\s+[\/.#@]?[A-Za-z0-9][\w.\/:#@+\-]*)*/g;
  /** סימני פיסוק בסוף רצף לטיני — שייכים למשפט, לא לרצף. */
  var TRAILING_PUNCT_RE = /[\-:.,;]+$/;
  var HEBREW_RE = /[֐-׿]/;

  /**
   * השם כרצפים — ``[{text, dir}]`` — כשכל רצף לטיני מבודד כ-``ltr`` והשאר ``rtl``.
   * הפיסוק בסוף רצף נשאר מחוצה לו (כמו בעיצוב), כדי שנקודה בסוף משפט עברי לא תצטרף לנתיב.
   */
  function titleRuns(text) {
    var src = String(text == null ? '' : text);
    var out = [];
    var at = 0;
    LATIN_RUN_RE.lastIndex = 0;
    var m;
    while ((m = LATIN_RUN_RE.exec(src)) !== null) {
      var run = m[0].replace(TRAILING_PUNCT_RE, '');
      if (!run) continue;
      if (m.index > at) out.push({ text: src.slice(at, m.index), dir: 'rtl' });
      out.push({ text: run, dir: 'ltr' });
      at = m.index + run.length;
      LATIN_RUN_RE.lastIndex = at;
    }
    if (at < src.length) out.push({ text: src.slice(at), dir: 'rtl' });
    return out;
  }

  /** כיוון הפסקה: עברית כלשהי ← ``rtl``. הרצפים הלטיניים כבר מבודדים, ולכן הם אינם משנים אותו. */
  function titleDir(text) {
    return HEBREW_RE.test(String(text == null ? '' : text)) ? 'rtl' : 'ltr';
  }

  // חשופים לבדיקות ב-node (``tests/notes-archive.test.js``), שמריצות את הקובץ עצמו.
  window.NotesArchiveText = { titleRuns: titleRuns, titleDir: titleDir };

  var grid = document.getElementById('archiveGrid');
  var main = document.getElementById('archiveMain');
  var overlay = document.getElementById('archiveOverlay');
  var backdrop = document.getElementById('archiveBackdrop');
  var errorBox = document.getElementById('archiveError');
  var retryBtn = document.getElementById('archiveRetry');
  var emptyBox = document.getElementById('archiveEmpty');
  var countEl = document.getElementById('archiveCount');
  if (!grid || !main || !overlay || !window.StickyNotesManager) return;

  /** כמה כרטיסי שלד מוצגים בזמן הטעינה. מספר קבוע — הם רק אומרים "משהו נטען". */
  var SKELETON_CARDS = 6;
  var maxNotes = null;

  /** הכרטיסים שברשת, לפי מזהה — כדי לעדכן או להוריד כרטיס בלי לחפש ב-DOM. */
  var cards = new Map();
  /** הכרטיס שהפתק הפתוח יצא ממנו — המיקוד חוזר אליו, והפתק מתכווץ אליו. */
  var openFrom = null;

  var notify = function (message, type) {
    if (typeof window.ckToast === 'function' && window.ckToast(message, type, { key: 'notes-archive' })) return;
    window.alert(message);
  };

  function setCount(n) {
    if (!countEl) return;
    countEl.textContent = (typeof maxNotes === 'number') ? (n + ' / ' + maxNotes) : String(n);
  }

  function showState(state) {
    errorBox.hidden = state !== 'error';
    emptyBox.hidden = state !== 'empty';
    grid.hidden = state === 'error' || state === 'empty';
    grid.setAttribute('aria-busy', state === 'loading' ? 'true' : 'false');
  }

  function renderSkeleton() {
    grid.textContent = '';
    for (var i = 0; i < SKELETON_CARDS; i++) {
      var s = document.createElement('div');
      s.className = 'archive-card is-skeleton';
      s.setAttribute('aria-hidden', 'true');
      grid.appendChild(s);
    }
  }

  /** ממלא את השם של כרטיס — רצף אחרי רצף, כל אחד בכיוון שלו. */
  function fillTitle(span, title) {
    span.textContent = '';
    var text = String(title || '');
    if (!text) {
      span.classList.add('is-untitled');
      span.textContent = 'ללא שם';
      span.setAttribute('dir', 'rtl');
      return;
    }
    span.classList.remove('is-untitled');
    span.setAttribute('dir', titleDir(text));
    titleRuns(text).forEach(function (run) {
      var part = document.createElement('span');
      part.className = 'archive-card-run';
      part.setAttribute('dir', run.dir);
      part.textContent = run.text;
      span.appendChild(part);
    });
  }

  function paintCard(card, note) {
    // טוקן ולא ``style.backgroundColor``: כלל ערכה ``!important`` על ``button`` גובר על סגנון
    // inline, ולכן הצבע נקרא בכלל של ``note-boards.css`` שגובר עליו (ההערה שם).
    card.style.setProperty('--archive-card-color', note.color || '');
    card.setAttribute('title', note.title || 'ללא שם');
    fillTitle(card.querySelector('.archive-card-title'), note.title);
  }

  function buildCard(note) {
    var card = document.createElement('button');
    card.type = 'button';
    card.className = 'archive-card';
    card.setAttribute('data-note-id', note.id);
    var band = document.createElement('span');
    band.className = 'archive-card-band';
    band.setAttribute('aria-hidden', 'true');
    var body = document.createElement('span');
    body.className = 'archive-card-body';
    var title = document.createElement('span');
    title.className = 'archive-card-title';
    body.appendChild(title);
    card.appendChild(band);
    card.appendChild(body);
    paintCard(card, note);
    card.addEventListener('click', function () { openNote(note.id, card); });
    return card;
  }

  function render(notes) {
    grid.textContent = '';
    cards.clear();
    notes.forEach(function (note) {
      var card = buildCard(note);
      cards.set(String(note.id), card);
      grid.appendChild(card);
    });
    setCount(notes.length);
    showState(notes.length ? 'list' : 'empty');
  }

  async function load() {
    showState('loading');
    renderSkeleton();
    var data = null;
    try {
      var resp = await fetch('/api/sticky-notes/archive', { cache: 'no-store' });
      data = await resp.json();
      if (!resp.ok || !data || data.ok !== true || !Array.isArray(data.notes)) data = null;
    } catch (err) {
      console.warn('notes archive: loading failed', err);
      data = null;
    }
    if (!data) {
      grid.textContent = '';
      showState('error');
      return false;
    }
    maxNotes = (typeof data.max === 'number') ? data.max : null;
    render(data.notes);
    return true;
  }

  var manager = new window.StickyNotesManager({
    archive: true,
    container: overlay,
    anchorHost: null,
    // ``summary`` הוא השם והצבע (``hex``) כפי שהמנהל מחזיק אותם בסגירה — כולל מה שנערך
    // בפתק עכשיו. בלי ``title`` (הפתק כבר ירד לפני הסגירה) הכרטיס נשאר כמו שהוא.
    onArchivedNoteClosed: function (summary) {
      var card = cards.get(String(summary.id));
      if (card && 'title' in summary) paintCard(card, { title: summary.title, color: summary.color });
      hideOverlay(card);
    },
    onArchivedNoteDeleted: function (id) {
      var card = cards.get(String(id));
      var next = card ? (card.nextElementSibling || card.previousElementSibling) : null;
      if (card) card.remove();
      cards.delete(String(id));
      setCount(cards.size);
      if (!cards.size) showState('empty');
      hideOverlay(next);
    },
  });

  function showOverlay() {
    overlay.hidden = false;
    // ``inert``: הרשת אינה ניתנת למיקוד, ללחיצה ולקורא מסך בזמן שהפתק פתוח מעליה (HTML
    // Standard). השכבה של הפתק יושבת מחוץ ל-``#archiveMain``, ולכן אינה מושפעת.
    main.inert = true;
  }

  function hideOverlay(focusTo) {
    overlay.hidden = true;
    main.inert = false;
    var target = focusTo || openFrom;
    openFrom = null;
    if (target && target.isConnected && typeof target.focus === 'function') target.focus({ preventScroll: true });
  }

  async function openNote(id, fromCard, threadId) {
    var data = null;
    try {
      var resp = await fetch('/api/sticky-notes/archive/' + encodeURIComponent(id), { cache: 'no-store' });
      data = await resp.json();
      if (resp.status === 404) {
        // הפתק כבר אינו בארכיון — נמחק ממכשיר אחר. הכרטיס יורד, והמשתמש יודע למה.
        var gone = cards.get(String(id));
        if (gone) { gone.remove(); cards.delete(String(id)); setCount(cards.size); if (!cards.size) showState('empty'); }
        notify('הפתק כבר לא בארכיון.', 'info');
        return;
      }
      if (!resp.ok || !data || data.ok !== true || !data.note) data = null;
    } catch (err) {
      console.warn('notes archive: opening a note failed', id, err);
      data = null;
    }
    if (!data) { notify('לא הצלחתי לפתוח את הפתק. נסו שוב.', 'error'); return; }
    openFrom = fromCard || cards.get(String(id)) || null;
    showOverlay();
    var el = manager.openArchivedNote(data.note, {
      threadsUnavailable: data.threads_unavailable === true,
      threadId: threadId || '',
    });
    if (!el) hideOverlay();
  }

  function closeNote() {
    manager.closeArchivedNote({
      toRect: function (id) {
        var card = cards.get(String(id));
        return card ? card.getBoundingClientRect() : null;
      }
    });
  }

  backdrop.addEventListener('click', closeNote);
  // ``Escape`` סוגר את הפתק — אלא אם רכיב בתוכו כבר טיפל בו (חיפוש בפתק, עריכת שם, תפריט,
  // חלון): הם מבטלים את ברירת המחדל או עוצרים את האירוע, ואז הוא אינו של העמוד.
  document.addEventListener('keydown', function (ev) {
    if (ev.key !== 'Escape' || ev.defaultPrevented || overlay.hidden) return;
    ev.preventDefault();
    closeNote();
  });
  retryBtn.addEventListener('click', loadAndFollowLink);

  /**
   * **קישור עמוק** — ``/boards/archive?note=<id>&thread=<id>``, שאליו מפנה הקישור הקבוע
   * ``/note/<id>`` (``webapp/boards_ui.note_permalink``): התראת תזכורת, תוצאת חיפוש, התראת
   * תגובה. הכוונה נצרכת פעם אחת — הפרמטרים יורדים מהכתובת אחרי הפתיחה, כדי שרענון לא יפתח
   * שוב פתק שהמשתמש כבר סגר.
   */
  async function consumeArchiveDeepLink() {
    var params;
    try { params = new URLSearchParams(window.location.search || ''); }
    catch (_) { return; /* כתובת שאי אפשר לפענח — אין כוונה לממש */ }
    var noteId = (params.get('note') || '').trim();
    if (!noteId) return;
    var threadId = (params.get('thread') || '').trim();
    try { window.history.replaceState(null, '', window.location.pathname); }
    catch (_) { /* בלי היסטוריה — הפרמטרים נשארים, והפתק ייפתח שוב ברענון */ }
    await openNote(noteId, null, threadId);
  }

  /**
   * טעינת הרשת, ואחריה הקישור העמוק — **גם אחרי "נסו שוב"**. קישור מהתראה שהטעינה הראשונה
   * נכשלה בו עדיין בכתובת (הוא יורד ממנה רק כשנצרך), ולכן נפתח כשהרשת סוף סוף נטענת, במקום
   * ללכת לאיבוד. אחרי שנצרך פעם אחת, הפעם הבאה אינה מוצאת בכתובת כלום.
   */
  function loadAndFollowLink() {
    return load().then(function (ok) { if (ok) return consumeArchiveDeepLink(); });
  }

  loadAndFollowLink();
})();
