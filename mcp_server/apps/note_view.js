/* תצוגת פתק בתוך Claude (MCP App) — ``mcp_server/note_view.py`` מכניס את הקובץ הזה לדף.

   **הפרוטוקול כתוב ביד, בלי ה-SDK של ext-apps.** המפרט אומר במפורש ש-SDK אינו נדרש
   ("you don't need an SDK to 'talk MCP' with the host", ``specification/2026-01-26/apps.mdx``),
   ומדריך ההגירה ל-2.x אומר שההודעות "byte-identical to 1.x" — כלומר הפרוטוקול יציב. SDK היה
   מחייב באנדל שנבנה ביד ונשמר בגיט, והבאנדל הוא בדיוק החוליה שנשכחת. כל צעד כאן מחקה את
   ``App`` של ext-apps (``src/app.ts``, ``src/message-transport.ts``, ``src/styles.ts``), ומי
   שמשנה אותו בודק קודם מה ה-SDK עושה באותה נקודה.

   **הזרימה** (המפרט, "Lifecycle"):
     1. הדף שולח ``ui/initialize`` (``appInfo``, ``appCapabilities``, ``protocolVersion``) ומחכה
        לתשובה — שבה ``hostContext``: ערכת נושא, משתני עיצוב, גופנים.
     2. אחרי התשובה: ``ui/notifications/initialized``, ומדידת גודל שמדווחת ב-
        ``ui/notifications/size-changed``.
     3. המארח שולח ``ui/notifications/tool-input`` ואחריה ``ui/notifications/tool-result`` —
        ``CallToolResult`` רגיל. הכלי שלנו מחזיר רק טקסט (JSON), כמו כל כלי בשרת, ולכן
        הפתק נקרא מבלוק הטקסט הראשון.
     4. ``ui/notifications/host-context-changed`` — עדכון חלקי של ההקשר (ערכה בהירה/כהה).

   **מקור ההודעה נבדק לפני כל דבר** (``event.source === window.parent``), בדיוק כמו
   ``PostMessageTransport`` ב-SDK. הודעה ממקור אחר נזרקת בלי קריאה בשדות שלה.

   **התוכן אינו מהימן** — סוכנים כותבים פתקים. אין כאן ``innerHTML`` בשום מקום: כל צומת
   נבנה עם ``createElement`` ו-``textContent``. וכל מה שמגיע מהמארח נבדק בצורתו לפני
   שקוראים בשדות שלו (``amir-bug-patterns``, U3).

   **שתי תקרות זמן משלנו** (``wait-without-own-deadline``). אף אחת מהן אינה מחזיקה דבר — היא
   מחליפה את "טוען…" בהודעה שאומרת מה לא הגיע, ותשובה שמגיעה אחריה עדיין מוצגת. */
(function (root) {
  'use strict';

  /** ``LATEST_PROTOCOL_VERSION`` ב-``src/spec.types.ts`` של ext-apps — הגרסה של המפרט היציב. */
  var PROTOCOL_VERSION = '2026-01-26';
  var APP_INFO = { name: 'codekeeper-note-view', version: '1.0.0' };
  /** הדף מציג פתק בתוך השיחה בלבד. המפרט מחייב להצהיר על כל מצב תצוגה שהדף תומך בו. */
  var APP_CAPABILITIES = { availableDisplayModes: ['inline'] };

  var INIT_DEADLINE_MS = 10000;
  var RESULT_DEADLINE_MS = 120000;

  /** קוד שגיאה מהשרת מוצג רק כשהוא בצורה של קוד — מילה אחת באותיות קטנות. */
  var ERROR_CODE_RE = /^[a-z][a-z0-9_]{0,63}$/;
  /** הצבע של הפתק נכנס ל-CSS, ולכן רק בצורה שהשרת מייצר (``note_color_hex``): ``#rrggbb``. */
  var HEX_COLOR_RE = /^#[0-9a-fA-F]{6}$/;

  var ERROR_TEXT = {
    not_found: 'הפתק לא נמצא, או שאין לך גישה אליו.',
    invalid_note_id: 'מזהה הפתק אינו תקין.',
    conflict: 'הפתק נערך ממש עכשיו. נסו שוב.',
    rate_limited: 'יותר מדי קריאות בדקה האחרונה. נסו שוב בעוד רגע.'
  };

  function isObject(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
  }

  function NoteView(win) {
    this.win = win;
    this.doc = win.document;
    this.nextId = 1;
    this.pending = {};
    this.initialized = false;
    this.rendered = false;
    this.lastWidth = 0;
    this.lastHeight = 0;
    this.sizeScheduled = false;
    this.initTimer = null;
    this.resultTimer = null;
    this.onMessage = this.onMessage.bind(this);
  }

  NoteView.prototype.root = function () {
    return this.doc.getElementById('ck-note-root');
  };

  NoteView.prototype.start = function () {
    var self = this;
    this.win.addEventListener('message', this.onMessage);
    // הטיימר מבוטל בתשובה, ולכן אינו צריך לשאול אם כבר התחברנו.
    this.initTimer = this.win.setTimeout(function () {
      self.showStatus('לא התקבלה תשובה מ-Claude. נסו לפתוח את הפתק שוב.', true);
    }, INIT_DEADLINE_MS);
    this.request('ui/initialize', {
      appInfo: APP_INFO,
      appCapabilities: APP_CAPABILITIES,
      protocolVersion: PROTOCOL_VERSION
    }, function (error, result) {
      self.win.clearTimeout(self.initTimer);
      if (error || !isObject(result)) {
        self.showStatus('החיבור ל-Claude נכשל, ולכן הפתק לא מוצג.', true);
        return;
      }
      self.initialized = true;
      self.applyHostContext(result.hostContext);
      self.notify('ui/notifications/initialized');
      self.watchSize();
      // **רק אם התוצאה עוד לא הגיעה.** המפרט אוסר על המארח לשלוח לפני ``initialized``, אבל
      // מארח שלא יקפיד היה מקבל כאן טיימר שדורס פתק שכבר מוצג. מכאן והלאה ``settle`` מבטל אותו.
      if (!self.rendered) {
        self.resultTimer = self.win.setTimeout(function () {
          self.showStatus('הפתק לא הגיע. נסו לבקש אותו שוב.', true);
        }, RESULT_DEADLINE_MS);
      }
    });
  };

  /** המצב הסופי — פתק, או הודעה על תשובה שאינה פתק. כל אחד מהם מבטל את תקרת הזמן. */
  NoteView.prototype.settle = function () {
    this.rendered = true;
    this.win.clearTimeout(this.resultTimer);
  };

  // -- JSON-RPC מעל postMessage ------------------------------------------------

  NoteView.prototype.post = function (message) {
    // ``"*"`` כמו ``PostMessageTransport.send``: ה-origin של המארח אינו ידוע לדף (הוא
    // יושב בתוך sandbox proxy), והאבטחה היא בבדיקת המקור בצד המקבל.
    this.win.parent.postMessage(message, '*');
  };

  NoteView.prototype.request = function (method, params, callback) {
    var id = this.nextId;
    this.nextId += 1;
    this.pending[id] = callback;
    this.post({ jsonrpc: '2.0', id: id, method: method, params: params });
  };

  NoteView.prototype.notify = function (method, params) {
    var message = { jsonrpc: '2.0', method: method };
    if (params !== undefined) message.params = params;
    this.post(message);
  };

  NoteView.prototype.respond = function (id, result) {
    this.post({ jsonrpc: '2.0', id: id, result: result });
  };

  NoteView.prototype.respondError = function (id, code, message) {
    this.post({ jsonrpc: '2.0', id: id, error: { code: code, message: message } });
  };

  NoteView.prototype.onMessage = function (event) {
    if (!event || event.source !== this.win.parent) return;
    var data = event.data;
    if (!isObject(data) || data.jsonrpc !== '2.0') return;
    var hasId = typeof data.id === 'number' || typeof data.id === 'string';
    if (typeof data.method === 'string') {
      if (hasId) this.onRequest(data);
      else this.onNotification(data.method, data.params);
      return;
    }
    if (hasId && Object.prototype.hasOwnProperty.call(this.pending, data.id)) {
      var callback = this.pending[data.id];
      delete this.pending[data.id];
      if (data.error !== undefined) callback(data.error, undefined);
      else callback(null, data.result);
    }
  };

  NoteView.prototype.onRequest = function (data) {
    // ``ping`` ו-``ui/resource-teardown`` הן הבקשות שהמארח שולח לדף; ה-SDK עונה על שתיהן
    // ``{}``. בקשה אחרת היא שיטה שהדף אינו מממש, ותשובת JSON-RPC היא -32601.
    if (data.method === 'ping' || data.method === 'ui/resource-teardown') {
      this.respond(data.id, {});
      return;
    }
    this.respondError(data.id, -32601, 'Method not found');
  };

  NoteView.prototype.onNotification = function (method, params) {
    if (method === 'ui/notifications/tool-result') {
      this.renderResult(params);
    } else if (method === 'ui/notifications/tool-cancelled') {
      // גם ביטול הוא מצב סופי: בלי ``settle`` תקרת הזמן הייתה מחליפה את "בוטלה" ב"לא הגיע".
      if (!this.rendered) {
        this.settle();
        this.showStatus('הבקשה להציג את הפתק בוטלה.', false);
      }
    } else if (method === 'ui/notifications/host-context-changed') {
      this.applyHostContext(params);
    }
    // ``tool-input`` ו-``tool-input-partial`` נושאים את הארגומנטים, והדף אינו צריך אותם:
    // מה שמוצג הוא מה שהשרת החזיר, לא מה שהמודל ביקש.
  };

  // -- ערכת נושא (``applyDocumentTheme`` / ``applyHostStyleVariables`` ב-SDK) -----------

  NoteView.prototype.applyHostContext = function (context) {
    if (!isObject(context)) return;
    var docEl = this.doc.documentElement;
    if (context.theme === 'light' || context.theme === 'dark') {
      docEl.setAttribute('data-theme', context.theme);
      docEl.style.colorScheme = context.theme;
    }
    var styles = context.styles;
    if (!isObject(styles)) return;
    if (isObject(styles.variables)) {
      var keys = Object.keys(styles.variables);
      for (var i = 0; i < keys.length; i += 1) {
        var value = styles.variables[keys[i]];
        if (keys[i].indexOf('--') === 0 && typeof value === 'string') {
          docEl.style.setProperty(keys[i], value);
        }
      }
    }
    if (isObject(styles.css) && typeof styles.css.fonts === 'string'
        && !this.doc.getElementById('ck-host-fonts')) {
      // כמו ``applyHostFonts``: פעם אחת, כ-``textContent`` של ``<style>``. הטקסט מגיע
      // מהמארח, לא מהפתק.
      var style = this.doc.createElement('style');
      style.id = 'ck-host-fonts';
      style.textContent = styles.css.fonts;
      this.doc.head.appendChild(style);
    }
  };

  // -- גודל (``setupSizeChangedNotifications`` ב-SDK) ------------------------------------

  NoteView.prototype.measureAndReport = function () {
    var docEl = this.doc.documentElement;
    // כמו ה-SDK: גובה התוכן נמדד עם ``height: max-content`` זמני — ``fit-content`` היה נחתך
    // בגובה ה-viewport — והרוחב נלקח מ-``innerWidth``, בלי למדוד רוחב תוכן.
    var original = docEl.style.height;
    docEl.style.height = 'max-content';
    var height = Math.ceil(docEl.getBoundingClientRect().height);
    docEl.style.height = original;
    var width = Math.ceil(this.win.innerWidth);
    if (width !== this.lastWidth || height !== this.lastHeight) {
      this.lastWidth = width;
      this.lastHeight = height;
      this.notify('ui/notifications/size-changed', { width: width, height: height });
    }
  };

  NoteView.prototype.scheduleSize = function () {
    var self = this;
    if (this.sizeScheduled) return;
    this.sizeScheduled = true;
    var run = function () {
      self.sizeScheduled = false;
      self.measureAndReport();
    };
    if (typeof this.win.requestAnimationFrame === 'function') this.win.requestAnimationFrame(run);
    else run();
  };

  NoteView.prototype.watchSize = function () {
    var self = this;
    this.scheduleSize();
    // **הכרעה סטטית על היעדר יכולת, לא נפילה על כשל:** בלי ``ResizeObserver`` הגודל נמדד פעם
    // אחת עכשיו ופעם אחת אחרי כל רינדור (``render``).
    if (typeof this.win.ResizeObserver === 'function') {
      var observer = new this.win.ResizeObserver(function () { self.scheduleSize(); });
      observer.observe(this.doc.documentElement);
      observer.observe(this.doc.body);
    }
  };

  // -- רינדור -------------------------------------------------------------------

  NoteView.prototype.showStatus = function (text, isError) {
    var host = this.root();
    if (!host) return;
    var p = this.doc.createElement('p');
    p.className = isError ? 'ck-status is-error' : 'ck-status';
    p.textContent = text;
    host.textContent = '';
    host.appendChild(p);
    if (this.initialized) this.scheduleSize();
  };

  /** הפתק מתוך ``CallToolResult``, או ``{error}`` — בלי לזרוק על שום צורה שמגיעה מבחוץ. */
  NoteView.prototype.readNote = function (result) {
    if (!isObject(result)) return { error: null };
    if (result.isError === true) return { error: null };
    var content = result.content;
    if (!Array.isArray(content)) return { error: null };
    var text = null;
    for (var i = 0; i < content.length; i += 1) {
      var block = content[i];
      if (isObject(block) && block.type === 'text' && typeof block.text === 'string') {
        text = block.text;
        break;
      }
    }
    if (text === null) return { error: null };
    var answer;
    try {
      answer = JSON.parse(text);
    } catch (_) {
      // תשובה שאינה JSON אינה תשובה של הכלי הזה; ההודעה הכללית אומרת את זה למשתמש.
      return { error: null };
    }
    if (!isObject(answer)) return { error: null };
    if (answer.ok !== true) {
      var code = typeof answer.error === 'string' && ERROR_CODE_RE.test(answer.error) ? answer.error : null;
      return { error: code };
    }
    if (!isObject(answer.note) || typeof answer.note.content !== 'string') return { error: null };
    return { note: answer.note };
  };

  NoteView.prototype.renderResult = function (result) {
    var read = this.readNote(result);
    if (!read.note) {
      this.settle();
      var known = read.error && Object.prototype.hasOwnProperty.call(ERROR_TEXT, read.error)
        ? ERROR_TEXT[read.error] : null;
      var message = known || ('לא הצלחתי להציג את הפתק' + (read.error ? ' (' + read.error + ').' : '.'));
      this.showStatus(message, true);
      return;
    }
    this.render(read.note);
  };

  NoteView.prototype.render = function (note) {
    var doc = this.doc;
    var host = this.root();
    if (!host) return;
    var paper = doc.createElement('article');
    paper.className = 'ck-paper';
    if (typeof note.color === 'string' && HEX_COLOR_RE.test(note.color)) {
      paper.style.backgroundColor = note.color;
      paper.className += ' has-note-color';
    }
    if (typeof note.title === 'string' && note.title.trim() !== '') {
      var title = doc.createElement('h1');
      title.className = 'ck-title';
      title.setAttribute('dir', 'auto');
      title.textContent = note.title;
      paper.appendChild(title);
    }
    var body = doc.createElement('div');
    body.className = 'ck-body';
    if (note.content === '') {
      var empty = doc.createElement('div');
      empty.className = 'ck-line ck-empty';
      empty.textContent = 'הפתק ריק.';
      body.appendChild(empty);
    } else {
      var lines = note.content.split('\n');
      for (var i = 0; i < lines.length; i += 1) {
        var row = doc.createElement('div');
        row.className = 'ck-line';
        row.setAttribute('dir', 'auto');
        // שורה ריקה נושאת רווח קשיח, כדי שתתפוס גובה של שורה כמו בפתק.
        row.textContent = lines[i] === '' ? '\u00a0' : lines[i];
        body.appendChild(row);
      }
    }
    paper.appendChild(body);
    host.textContent = '';
    host.appendChild(paper);
    this.settle();
    if (this.initialized) this.scheduleSize();
  };

  // **מתחיל תמיד, בלי לשאול אם הדף בתוך מסגרת** — כמו ``App.connect`` ב-SDK, שמתחבר ל-
  // ``window.parent`` בלי תנאי. ב-iOS וב-Android ‏Claude מציג את הדף ב-WebView ולא ב-iframe
  // (התיעוד של Claude, "Design guidelines"), ואיך ``window.parent`` נראה שם אינו מתועד. תנאי
  // כמו ``parent !== window`` היה משאיר את הדף על "טוען…" בדיוק במקום שאי אפשר לראות בו
  // קונסול. התנהגות זהה ל-SDK היא מה ש-Claude בודק מולו.
  if (root.document) {
    new NoteView(root).start();
  }
}(typeof window !== 'undefined' ? window : this));
