/**
 * הפתקים הנעוצים בראש עמוד הקבצים — "הבא בתור".
 *
 * **מה כאן:** הכרטיסים בשורה שליד הכותרת "הקבצים שלי" — כמה שנכנסים בשורה אחת, ומה שלא נכנס
 * מאחורי "+N" — ופתק אחד שנפתח מעליהם. הכרטיסים נבנים ברכיב המשותף עם הארכיון
 * (``note-cards.js``), והפתק הפתוח הוא אותו רכיב פתק של כל משטח: ``StickyNotesManager`` במצב
 * ``filesPage`` (``sticky-notes.js``). העמוד רק מביא את הרשימה (``GET /api/sticky-notes/files-page``)
 * ואת הפתק (``GET /api/sticky-notes/files-page/<id>``) ומוסר.
 *
 * **הנתונים נטענים כאן ולא ברינדור של השרת**, כי ה-HTML של עמוד הקבצים נשמר בקאש לכל משתמש
 * (``files_cache_key`` ב-``webapp/app.py``): כרטיס שמרונדר בשרת היה מחייב למחוק את הקאש בכל
 * נעיצה, בכל מסלול שנועץ.
 *
 * **שני מצבי תצוגה, והרוחב אינו מחליף ביניהם.** כרטיסים מלאים, כמה שנכנסים; ו**פס כותרות** —
 * רק כשאין מספיק **גובה** לכרטיסים (``MIN_VIEWPORT_H_FOR_CARDS``), או כשמוצגת הכרזה בראש העמוד
 * (``#announcementBanner`` ב-``base.html``), שתופסת את אותו שטח. בשני המצבים — שורה אחת, ו-"+N".
 *
 * **טעינה שנכשלה אינה "אין נעוצים".** בלי נעוצים האזור פשוט אינו מוצג; בטעינה שנכשלה מוצגת
 * הודעה עם "נסו שוב".
 */
(function () {
  'use strict';

  var region = document.getElementById('filesPageNotes');
  var row = document.getElementById('filesPageCards');
  var errorBox = document.getElementById('filesPageNotesError');
  var retryBtn = document.getElementById('filesPageNotesRetry');
  var pageMain = document.querySelector('main.main-content');
  var Cards = window.NoteCards;
  var Layout = window.StickyNotesFilesPage;
  if (!region || !row || !errorBox || !retryBtn || !pageMain || !window.StickyNotesManager || !Cards || !Layout) {
    return;
  }

  /**
   * גובה הכרטיס בעמוד הקבצים, בפיקסלים — מוצב על השורה כמשתנה CSS (``--files-page-card-h``), ולכן
   * אין לו עותק ב-``note-cards.css``. הרוחב והמרווח באים מ-``sticky-notes.js`` (``Layout``), כי גם
   * עמוד הלוח מחשב לפיהם כמה כרטיסים נכנסים כשנועצים; הגובה הוא של העמוד הזה בלבד.
   */
  var CARD_H = 96;
  /**
   * **מתחת לגובה הזה של החלון — פס כותרות ולא כרטיסים.** שורת הכרטיסים תופסת לכל היותר חמישית
   * מהגובה שרואים: בטלפון לרוחב (גובה של כ-390) הכרטיסים היו דוחפים את החיפוש מתחת לקצה המסך,
   * ובטלפון לאורך, בטאבלט ובמחשב יש מקום. נגזר מגובה הכרטיס ולא מוקלד, כדי ששינוי שלו יזיז גם
   * את הסף.
   */
  var MIN_VIEWPORT_H_FOR_CARDS = CARD_H * 5;
  /** פריט בפס הכותרות: אותו כרטיס, בווריאנט של שורה אחת (``files-page-chip``), ברוחב קבוע. */
  var CHIP_W = 150, CHIP_H = 34, CHIP_GAP = 8;

  var notify = function (message, type) {
    if (typeof window.ckToast === 'function' && window.ckToast(message, type, { key: 'files-page-notes' })) return;
    window.alert(message);
  };

  /** הכרטיסים מהשרת, בסדר הנעיצה. ``null`` — עוד לא נטענו (או שהטעינה נכשלה). */
  var notes = null;
  /** הכרטיס (או "+N") שהפתק הפתוח יצא ממנו — המיקוד חוזר אליו, והפתק מתכווץ אליו. */
  var openFrom = null;
  /** הרשימה של "+N" כשהיא פתוחה: ``{ list, button }``. */
  var moreMenu = null;
  var layoutFrame = 0;
  /** הרוחב שהשורה נפרשה לפיו בפעם האחרונה — כדי לפרוש מחדש רק כשהוא באמת השתנה. */
  var laidOutWidth = -1;

  // ---- השכבה של הפתק הפתוח ----
  //
  // **מחוץ ל-``main``**, כדי שהעמוד יוכל לסמן את התוכן ``inert`` בזמן שפתק פתוח בלי לנטרל גם את
  // הפתק. הרקע הוא **אח** של הפתק ולא אב: ``backdrop-filter`` הופך אלמנט ל-containing block של
  // צאצאים ``fixed``, ופתק במצב ``screen`` היה נמדד מולו במקום מול המסך.
  var overlay = document.createElement('div');
  overlay.className = 'note-overlay';
  overlay.id = 'filesPageNoteOverlay';
  overlay.hidden = true;
  var backdrop = document.createElement('div');
  backdrop.className = 'note-overlay-backdrop';
  overlay.appendChild(backdrop);
  document.body.appendChild(overlay);

  var manager = new window.StickyNotesManager({
    filesPage: true,
    container: overlay,
    anchorHost: null,
    // הפתק נסגר. התווית בכרטיס נגזרת בשרת (``note_label``: השם, ובלעדיו השורה הראשונה), ולכן
    // הרשימה נטענת שוב — ולא מחושבת כאן בעותק שני של הכלל. כשל בטעינה משאיר את הכרטיסים כמו שהם.
    onOverlayNoteClosed: function (summary) {
      hideOverlay(cardFor(summary && summary.id));
      load({ quiet: true });
    },
    // הפתק עזב את עמוד הקבצים — נמחק, הועבר לארכיון או הוסר מהנעיצה — והשרת אישר.
    //
    // **המיקוד עובר לשכן לפי המזהה שלו, ולא לפי האלמנט.** ``removeNote`` בונה את השורה מאפס,
    // ולכן אלמנט השכן שנשמר לפני ההסרה כבר אינו ב-DOM אחריה — ומיקוד שמכוון אליו נופל ל-``body``.
    onOverlayNoteGone: function (id) {
      var gone = cardFor(id);
      var neighbor = gone ? (gone.previousElementSibling || gone.nextElementSibling) : null;
      var neighborId = neighbor ? neighbor.getAttribute('data-note-id') : null;
      removeNote(id);
      hideOverlay(focusAfterRemoval(neighborId));
    },
  });

  /**
   * לאן המיקוד הולך אחרי שכרטיס ירד, **בשורה שכבר נבנתה מחדש**: לשכן אם הוא עדיין בשורה; ל-"+N"
   * אם השכן היה "+N", או עבר אל מאחוריו, או שהפתק נפתח מהרשימה שלו; ואחרת לכרטיס הראשון.
   * ``null`` — אין יותר כרטיסים, והאזור כולו ירד.
   */
  function focusAfterRemoval(neighborId) {
    return (neighborId && cardFor(neighborId))
      || row.querySelector('.files-page-more')
      || row.querySelector('[data-note-id]');
  }

  function showOverlay() {
    overlay.hidden = false;
    // ``inert``: תוכן העמוד אינו ניתן למיקוד, ללחיצה ולקורא מסך בזמן שהפתק פתוח מעליו (HTML
    // Standard). השכבה יושבת מחוץ ל-``main``, ולכן אינה מושפעת.
    pageMain.inert = true;
  }

  function hideOverlay(focusTo) {
    overlay.hidden = true;
    pageMain.inert = false;
    var target = focusTo || openFrom;
    openFrom = null;
    if (target && target.isConnected && typeof target.focus === 'function') target.focus({ preventScroll: true });
  }

  function cardFor(id) {
    if (!id) return null;
    var all = row.querySelectorAll('[data-note-id]');
    for (var i = 0; i < all.length; i++) {
      if (all[i].getAttribute('data-note-id') === String(id)) return all[i];
    }
    return null;
  }

  function removeNote(id) {
    if (!notes) return;
    notes = notes.filter(function (n) { return String(n.id) !== String(id); });
    render();
  }

  // ---- מצבים ----

  function showError() {
    region.hidden = false;
    errorBox.hidden = false;
    row.hidden = true;
    row.textContent = '';
  }

  function showNotes() {
    errorBox.hidden = true;
    if (!notes || !notes.length) {
      region.hidden = true;
      row.textContent = '';
      return;
    }
    region.hidden = false;
    row.hidden = false;
  }

  /** האם מוצגת הכרזה בראש העמוד — ``base.html`` מציג אותה ב-``show()`` עם ``aria-hidden="false"``. */
  function bannerShown() {
    var banner = document.getElementById('announcementBanner');
    return !!(banner && banner.getAttribute('aria-hidden') === 'false' && banner.style.display !== 'none');
  }

  /** ``cards`` או ``strip`` — לפי הגובה שרואים ולפי ההכרזה, ולעולם לא לפי הרוחב. */
  function displayMode() {
    var h = window.innerHeight;
    if (bannerShown()) return 'strip';
    if (Number.isFinite(h) && h > 0 && h < MIN_VIEWPORT_H_FOR_CARDS) return 'strip';
    return 'cards';
  }

  // ---- הפריסה ----

  function closeMoreMenu(opts) {
    if (!moreMenu) return;
    var mm = moreMenu;
    moreMenu = null;
    mm.list.remove();
    mm.button.setAttribute('aria-expanded', 'false');
    if (opts && opts.returnFocus) mm.button.focus({ preventScroll: true });
  }

  function buildItem(note, mode) {
    return Cards.buildCard({ id: note.id, title: note.label, color: note.color }, {
      variant: mode === 'strip' ? 'files-page-chip' : 'files-page-card',
      onOpen: function (el) { openNote(note.id, el); },
    });
  }

  /**
   * "+N" — הפתקים שלא נכנסו לשורה. **בלחיצה נפתחת רשימה שלהם**, ומשם נפתח כל אחד מהם: בלי זה
   * פתק שננעץ במסך רחב לא היה נגיש בכלל במסך צר — אפילו לא כדי להסיר אותו מהנעיצה.
   */
  function buildMore(hidden, mode) {
    var wrap = document.createElement('div');
    wrap.className = 'files-page-more-wrap';
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'files-page-more' + (mode === 'strip' ? ' is-strip' : '');
    // ``dir="ltr"``: בפסקה RTL ה-``+`` הוא תו ניטרלי ונוחת בצד השני של המספר ("3+") — נמדד
    // בכרומיום. השם הנגיש (``aria-label``) נשאר בעברית.
    button.setAttribute('dir', 'ltr');
    button.textContent = '+' + hidden.length;
    button.setAttribute('aria-haspopup', 'true');
    button.setAttribute('aria-expanded', 'false');
    button.setAttribute('aria-label', 'עוד ' + hidden.length + ' פתקים נעוצים');
    button.setAttribute('title', 'עוד ' + hidden.length + ' פתקים נעוצים');
    button.addEventListener('click', function (ev) {
      ev.stopPropagation();
      if (moreMenu) { closeMoreMenu({ returnFocus: true }); return; }
      var list = document.createElement('div');
      list.className = 'files-page-more-list note-cards';
      list.setAttribute('role', 'group');
      list.setAttribute('aria-label', 'פתקים נעוצים שלא נכנסו לשורה');
      hidden.forEach(function (note) {
        var item = Cards.buildCard({ id: note.id, title: note.label, color: note.color }, {
          variant: 'files-page-chip',
          onOpen: function () { closeMoreMenu(); openNote(note.id, button); },
        });
        list.appendChild(item);
      });
      list.addEventListener('keydown', function (kev) {
        if (kev.key === 'Escape') { kev.preventDefault(); kev.stopPropagation(); closeMoreMenu({ returnFocus: true }); }
      });
      wrap.appendChild(list);
      moreMenu = { list: list, button: button };
      button.setAttribute('aria-expanded', 'true');
      var first = list.querySelector('button');
      if (first) first.focus({ preventScroll: true });
    });
    wrap.appendChild(button);
    return wrap;
  }

  /**
   * בונה את השורה מחדש מ-``notes``, לפי הרוחב שיש לה עכשיו.
   *
   * **כמה נכנסים — חשבון על רוחב שנמדד, ולא ניחוש:** פריטים ברוחב קבוע ``w`` ומרווח ``gap``
   * (``Layout.cardsThatFit``). כשלא כולם נכנסים, גם "+N" צריך מקום, ולכן נמדד הרוחב שלו בפועל
   * וממנו נגזר כמה פריטים נשארים לצידו: ``k·(w+gap) + plus ≤ row``. השורה אינה חותכת (אין
   * ``overflow: hidden``): טעות בחשבון הייתה נראית כגלישה, ולא נבלעת בשקט (H7).
   *
   * **במצב כרטיסים נשמר רוחב השורה** (``Layout.recordRowWidth``) — עמוד הלוח קורא אותו כדי לא
   * לאפשר נעיצה של פתק שבמסך הזה היה מוצג רק כ-"+N".
   */
  function render() {
    // **המיקוד שורד את הבנייה מחדש.** אחרי סגירת פתק הרשימה נטענת שוב (``onOverlayNoteClosed``)
    // והשורה נבנית מאפס — והכרטיס שהמיקוד חזר אליו יורד מה-DOM יחד עם המיקוד. נמדד בכרומיום:
    // אחרי ``Escape`` המיקוד נפל ל-``body``. לכן זוכרים על מה הוא עמד, ומחזירים אליו בסוף.
    var active = document.activeElement;
    var focusedId = (active && row.contains(active)) ? active.getAttribute('data-note-id') : null;
    var focusedMore = !!(active && row.contains(active) && active.classList.contains('files-page-more'));
    closeMoreMenu();
    showNotes();
    if (!notes || !notes.length) return;
    var mode = displayMode();
    region.setAttribute('data-mode', mode);
    row.style.setProperty('--files-page-card-w', Layout.CARD_W + 'px');
    row.style.setProperty('--files-page-card-h', CARD_H + 'px');
    row.style.setProperty('--files-page-card-gap', Layout.CARD_GAP + 'px');
    row.style.setProperty('--files-page-chip-w', CHIP_W + 'px');
    row.style.setProperty('--files-page-chip-h', CHIP_H + 'px');
    row.style.setProperty('--files-page-chip-gap', CHIP_GAP + 'px');
    row.textContent = '';
    var itemW = mode === 'strip' ? CHIP_W : Layout.CARD_W;
    var gap = mode === 'strip' ? CHIP_GAP : Layout.CARD_GAP;
    var width = row.getBoundingClientRect().width;
    laidOutWidth = width;
    if (mode === 'cards') Layout.recordRowWidth(width);
    var fit = Layout.cardsThatFit(width, itemW, gap);
    var shown = notes.length;
    var more = null;
    if (notes.length > fit) {
      more = buildMore(notes, mode);
      row.appendChild(more);
      var plusW = more.getBoundingClientRect().width;
      row.removeChild(more);
      shown = Math.max(0, Math.floor((width - plusW) / (itemW + gap)));
      more = buildMore(notes.slice(shown), mode);
    }
    for (var i = 0; i < shown; i++) row.appendChild(buildItem(notes[i], mode));
    if (more) row.appendChild(more);
    if (focusedId || focusedMore) {
      // הכרטיס עצמו אם הוא עדיין בשורה; אם הוא עבר אל מאחורי "+N" — ל-"+N".
      var target = focusedId ? cardFor(focusedId) : null;
      if (!target && more) target = more.querySelector('.files-page-more');
      if (target) target.focus({ preventScroll: true });
    }
  }

  function scheduleRender() {
    if (layoutFrame) return;
    layoutFrame = window.requestAnimationFrame(function () {
      layoutFrame = 0;
      if (notes && overlay.hidden) render();
    });
  }

  // ---- הטעינה והפתיחה ----

  async function load(opts) {
    var quiet = !!(opts && opts.quiet);
    var data = null;
    try {
      var resp = await fetch('/api/sticky-notes/files-page', { cache: 'no-store', credentials: 'same-origin' });
      data = await resp.json();
      if (!resp.ok || !data || data.ok !== true || !Array.isArray(data.notes)) data = null;
    } catch (err) {
      console.warn('files page notes: loading failed', err);
      data = null;
    }
    if (!data) {
      // טעינה חוזרת שקטה (אחרי סגירת פתק) שנכשלה — הכרטיסים שכבר מוצגים נשארים.
      if (quiet && notes) return;
      notes = null;
      showError();
      return;
    }
    notes = data.notes.filter(function (n) { return n && typeof n.id === 'string' && n.id; });
    // שמות הכרטיסים בכתב יד תמיד (``.archive-card-title`` ב-``note-cards.css``). הגופן נטען רק
    // כשיש מה להציג בו — עמוד בלי נעוצים אינו מוריד אותו בכלל.
    if (notes.length && typeof window.ensureHandwritingFont === 'function') window.ensureHandwritingFont();
    render();
  }

  async function openNote(id, fromEl) {
    var data = null;
    try {
      var resp = await fetch('/api/sticky-notes/files-page/' + encodeURIComponent(id), { cache: 'no-store', credentials: 'same-origin' });
      data = await resp.json();
      if (resp.status === 404) {
        // הפתק כבר אינו נעוץ — הוסר, נמחק או הועבר לארכיון ממכשיר אחר. הכרטיס יורד.
        removeNote(id);
        notify('הפתק כבר לא נעוץ לעמוד הקבצים.', 'info');
        return;
      }
      if (!resp.ok || !data || data.ok !== true || !data.note) data = null;
    } catch (err) {
      console.warn('files page notes: opening a note failed', id, err);
      data = null;
    }
    if (!data) { notify('לא הצלחתי לפתוח את הפתק. נסו שוב.', 'error'); return; }
    openFrom = fromEl || cardFor(id) || null;
    showOverlay();
    var el = manager.openOverlayNote(data.note, { threadsUnavailable: data.threads_unavailable === true });
    if (!el) hideOverlay();
  }

  function closeNote() {
    manager.closeOverlayNote({
      toRect: function (id) {
        var card = cardFor(id);
        return card ? card.getBoundingClientRect() : null;
      }
    });
  }

  backdrop.addEventListener('click', closeNote);
  // ``Escape`` סוגר את הפתק — אלא אם רכיב בתוכו כבר טיפל בו (חיפוש בפתק, עריכת שם, תפריט, חלון):
  // הם מבטלים את ברירת המחדל או עוצרים את האירוע, ואז הוא אינו של העמוד. ובלי פתק פתוח — את
  // הרשימה של "+N".
  document.addEventListener('keydown', function (ev) {
    if (ev.key !== 'Escape' || ev.defaultPrevented) return;
    if (!overlay.hidden) { ev.preventDefault(); closeNote(); return; }
    if (moreMenu) { ev.preventDefault(); closeMoreMenu({ returnFocus: true }); }
  });
  // לחיצה מחוץ לרשימה של "+N" סוגרת אותה — בשלב הלכידה, כמו התפריט ⋮ של הפתק.
  document.addEventListener('pointerdown', function (ev) {
    if (!moreMenu) return;
    var t = ev.target;
    if (t && (moreMenu.list.contains(t) || moreMenu.button.contains(t))) return;
    closeMoreMenu();
  }, true);
  retryBtn.addEventListener('click', function () { load(); });
  // גובה החלון משתנה בסיבוב ובשינוי גודל; ההכרזה מוצגת אחרי בקשה משלה.
  window.addEventListener('resize', scheduleRender);
  // **ורוחב השורה משתנה גם בלי ``resize``** — נמדד: כשהעמוד מסיים להיטען ופס הגלילה של
  // ``body`` מופיע או נעלם, השורה זזה בכמה פיקסלים, ו-``resize`` של החלון אינו נורה. המעקב הוא
  // על האזור, שרוחבו אינו תלוי בכרטיסים שבתוכו (``files-page-notes.css``), ולכן פריסה מחדש אינה
  // משנה אותו ואינה מזינה את עצמה; וגם כך — רק כשהרוחב באמת שונה ממה שנפרש.
  if (typeof ResizeObserver === 'function') {
    new ResizeObserver(function () {
      if (region.hidden || !notes) return;
      if (Math.abs(row.getBoundingClientRect().width - laidOutWidth) >= 1) scheduleRender();
    }).observe(region);
  }
  var banner = document.getElementById('announcementBanner');
  if (banner && typeof MutationObserver === 'function') {
    new MutationObserver(scheduleRender).observe(banner, { attributes: true, attributeFilter: ['style', 'aria-hidden'] });
  }

  load();
})();
