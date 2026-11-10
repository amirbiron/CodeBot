/**
 * כרטיס של פתק — הרכיב שעמוד הארכיון ועמוד הקבצים מציגים בו פתק סגור.
 *
 * **רכיב אחד, ולא עותק לכל עמוד.** עד נובמבר 2026 הכרטיס חי בתוך ``notes-archive.js``; כשעמוד
 * הקבצים קיבל כרטיסים של פתקים נעוצים, הבנייה, חלוקת השם לרצפים והצבע עברו לכאן, וכל עמוד
 * מוסיף רק את מה ששונה אצלו — מחלקה של וריאנט (``files-page-card``, נמוך יותר וחותך אחרי שתי
 * שורות) ומה קורה בלחיצה. הסגנון — ``note-cards.css``.
 *
 * **הכרטיס הוא נייר של פתק:** הצבע שלו הוא צבע הפתק, כטוקן (``--archive-card-color``) ולא
 * כ-``style.backgroundColor`` — כלל ערכה ``!important`` על ``button`` גובר על סגנון inline, ולכן
 * הצבע נקרא בכלל של ``note-cards.css`` שגובר עליו.
 */
(function () {
  'use strict';

  /**
   * **רצף לטיני בתוך שם עברי** — מילה, נתיב (``/admin/mcp``), מזהה (``#3542``) או כמה כאלה עם
   * רווחים ביניהם. בפסקה RTL, ``/`` שבתחילת רצף כזה נשען על הרווח העברי שלפניו ונוחת בצד הלא
   * נכון (``admin/mcp/``), ולכן כל רצף כזה מבודד ככיוון LTR משלו. הביטוי לקוח מהעיצוב של עמוד
   * הארכיון (``sticky_notes_Archive_design.html`` ב-Ck), שבו נבדק על שמות של פתקים אמיתיים.
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

  /**
   * השם כקטעים של טקסט וקוד — ``[{text, code}]``. **הכלל הוא של הפתק** (``inlineCodeSegments``
   * ב-``sticky-notes.js``), ששני העמודים טוענים לפני הקובץ הזה: שם שהגיע מכותרת Markdown נושא
   * לפעמים ``קוד`` בגרשיים, והכרטיס מציג אותו כקוד, בלי הגרשיים הגלויים.
   *
   * **בלי ``sticky-notes.js`` השם מוצג כמו שהוא**, עם הגרשיים — היעדר יכולת קבוע של עמוד שלא
   * טען את הקובץ, ולא כשל בזמן ריצה. נרשם בקונסול פעם אחת, כדי שלא ייראה כמו באג בכלל עצמו.
   */
  var warnedNoCodeRule = false;
  function codeSegments(text) {
    var api = window.StickyNotesText;
    if (api && typeof api.inlineCodeSegments === 'function') return api.inlineCodeSegments(text);
    if (!warnedNoCodeRule) {
      warnedNoCodeRule = true;
      console.warn('note cards: sticky-notes.js is not loaded; inline code in card titles is shown as typed');
    }
    return [{ text: String(text == null ? '' : text), code: false }];
  }

  /**
   * ממלא את השם של כרטיס — קטע אחרי קטע. טקסט מתחלק לרצפים, כל אחד בכיוון שלו; קוד הוא
   * ``<code>`` מבודד בכיוון LTR, כמו קוד בשורה בפתק עצמו. ``fallback`` — מה שמוצג כשאין שם.
   */
  function fillTitle(span, title, fallback) {
    span.textContent = '';
    var text = String(title || '');
    if (!text) {
      span.classList.add('is-untitled');
      span.textContent = fallback || 'ללא שם';
      span.setAttribute('dir', 'rtl');
      return;
    }
    span.classList.remove('is-untitled');
    span.setAttribute('dir', titleDir(text));
    codeSegments(text).forEach(function (seg) {
      if (seg.code) {
        var code = document.createElement('code');
        code.className = 'archive-card-code';
        code.setAttribute('dir', 'ltr');
        code.textContent = seg.text;
        span.appendChild(code);
        return;
      }
      titleRuns(seg.text).forEach(function (run) {
        var part = document.createElement('span');
        part.className = 'archive-card-run';
        part.setAttribute('dir', run.dir);
        part.textContent = run.text;
        span.appendChild(part);
      });
    });
  }

  /** צובע את הכרטיס ושם בו את השם. ``note`` הוא ``{title, color}``; ``color`` הוא ``hex``. */
  function paintCard(card, note, fallback) {
    card.style.setProperty('--archive-card-color', note.color || '');
    card.setAttribute('title', note.title || fallback || 'ללא שם');
    fillTitle(card.querySelector('.archive-card-title'), note.title, fallback);
  }

  /**
   * בונה כרטיס — ``<button>``, כדי שיהיה נגיש במקלדת. ``opts.variant`` הוא מחלקה נוספת
   * (``files-page-card`` בעמוד הקבצים), ``opts.onOpen`` נקרא בלחיצה עם הכרטיס עצמו, ו-
   * ``opts.fallback`` הוא מה שמוצג במקום שם ריק.
   */
  function buildCard(note, opts) {
    var options = opts || {};
    var card = document.createElement('button');
    card.type = 'button';
    card.className = options.variant ? 'archive-card ' + options.variant : 'archive-card';
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
    paintCard(card, note, options.fallback);
    if (typeof options.onOpen === 'function') {
      card.addEventListener('click', function () { options.onOpen(card); });
    }
    return card;
  }

  window.NoteCards = {
    titleRuns: titleRuns,
    titleDir: titleDir,
    fillTitle: fillTitle,
    paintCard: paintCard,
    buildCard: buildCard,
  };
})();
