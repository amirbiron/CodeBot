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
     4. ``ui/notifications/host-context-changed`` — עדכון **חלקי** של ההקשר: ערכה, מצב תצוגה,
        גודל המסגרת. המפרט: "the View SHOULD merge received fields with its current context
        state", וה-SDK ממזג רדוד (``{ ...this._hostContext, ...params }`` ב-``src/app.ts``). הדף
        שומר את ההקשר הממוזג ב-``hostContext`` ומסדר את עצמו לפיו.

   **הגובה והגלילה.** הנוסחה של הגובה יושבת ב-``note_view.css``, וההסבר שם. כאן — מה שמזין
   אותה: ``containerDimensions`` של המארח (המפרט, "Container Dimensions": ``maxHeight`` — הדף
   קובע את הגובה עד התקרה; ``height`` — המארח קובע, והדף ממלא), השוליים הבטוחים
   (``safeAreaInsets``), והכפתורים ▲▼ שגוללים את גוף הפתק ב-``SCROLL_STEP_RATIO`` מהגובה הגלוי.
   כפתור "מסך מלא" מופיע רק כשהמארח מונה ``fullscreen`` ב-``availableDisplayModes`` וכשהדף עוד
   לא שם — "View MUST check if the requested mode is in ``availableDisplayModes`` from host
   context before requesting a mode change" (המפרט, "Display Modes").

   **דיווח הגודל אינו תלוי רק בשינוי תוכן.** ``ResizeObserver`` על ``html`` ו-``body`` רואה
   שינוי בתוכן, אבל לא מסגרת שהמארח משנה בלי שהתוכן זז: גובה התוכן נשאר כשהיה, ולכן שום אלמנט
   לא משנה גודל. נמדד בכרום לפני התיקון: המארח הציב למסגרת גובה ישן של 700px מעל תוכן של 116px,
   והדף שתק — שטח מת מתחת לפתק, כמו שנראה ב-Claude אחרי פתיחה מחדש של האפליקציה. לכן הדף מדווח
   תמיד בעלייה, ובכל ``resize`` של החלון שלו (כלומר של המסגרת) — גם כשהמספר זהה לדיווח הקודם.

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
  /** המפרט מחייב להצהיר על כל מצב תצוגה שהדף תומך בו: בתוך השיחה, ובמסך מלא (שבו המארח נותן
   *  מסגרת בגובה קבוע, והגוף נגלל בתוכה). */
  var APP_CAPABILITIES = { availableDisplayModes: ['inline', 'fullscreen'] };
  /** כל לחיצה על ▲ או ▼ מזיזה שלושה רבעים מהגובה הגלוי, ולא עמוד שלם, כדי שהשורות האחרונות
   *  שנקראו יישארו על המסך (החלטת המשתמש). */
  var SCROLL_STEP_RATIO = 0.75;
  /** השדות של ``safeAreaInsets`` במפרט — פיזיים, ולכן גם המשתנים ב-CSS. */
  var SAFE_AREA_SIDES = ['top', 'right', 'bottom', 'left'];
  /** הגודל שאלמנטי הבדיקה מבקשים — ``probeScale`` מחלק בו את הגודל המחושב. */
  var TEXT_PROBE_PX = 100;
  /** כמה רחוק מ-1 היחס שנשאר אחרי הפיצוי יכול להיות ועדיין להיחשב "בוטל". 130% כפול 76.9231% אינו
   *  יוצא 1 בדיוק בחשבון עשרוני, ולכן לא משווים בשוויון. */
  var TEXT_SCALE_EPSILON = 0.005;

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

  /** מספר מהמארח, לפני שהוא נכנס ל-CSS: מספר אמיתי, סופי, ובטווח. ``NaN`` עובר כל השוואה
   *  כ-``false``, ולכן ``isFinite`` קודם (``amir-bug-patterns`` U3, סעיף 4). */
  function isLength(value, allowZero) {
    return typeof value === 'number' && isFinite(value) && (allowZero ? value >= 0 : value > 0);
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
    // הדיווח הראשון יוצא תמיד, וכך גם הראשון אחרי כל שינוי של המסגרת — ראו ``watchSize``.
    this.forceReport = true;
    this.sizeScheduled = false;
    /** ההקשר של המארח, ממוזג מתשובת ``ui/initialize`` ומכל ``host-context-changed``. */
    this.hostContext = {};
    /** הפתק המוצג והכפתורים שלו — ``null`` כשמוצגת הודעה במקום פתק. */
    this.view = null;
    /** ההגדלה של המערכת שנמדדה אחרונה — ראו ``measureTextScale``. */
    this.textScale = 1;
    /** שני אלמנטי הבדיקה של ``probeScale``: ``raw`` מודד את ההגדלה, ``effect`` את מה שנשאר ממנה. */
    this.textProbes = { raw: null, effect: null };
    /** ``hostCapabilities`` מתשובת ``ui/initialize`` — ``openLinks`` מכריע אם קישור נפתח. */
    this.hostCapabilities = {};
    /** הצופה על הגודל (``watchSize``); הוא צופה גם בתוכן של הפתק, ולכן הוא נשמר. */
    this.sizeObserver = null;
    this.initTimer = null;
    this.resultTimer = null;
    this.onMessage = this.onMessage.bind(this);
  }

  NoteView.prototype.root = function () {
    return this.doc.getElementById('ck-note-root');
  };

  NoteView.prototype.start = function () {
    var self = this;
    // לפני כל רינדור: הגודל הנכון כבר בפתק הראשון, בלי פריסה שנייה.
    this.measureTextScale();
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
      self.hostCapabilities = isObject(result.hostCapabilities) ? result.hostCapabilities : {};
      // **``initialized`` לפני כל דבר אחר שהדף שולח** — כמו ``App.connect`` ב-SDK, ששולח אותו
      // מיד אחרי התשובה. ``applyHostContext`` מסדר את הדף לפי המסגרת ומודד גודל, ומדידה שהייתה
      // רצה לפניו הייתה שולחת ``size-changed`` למארח שעוד לא קיבל ``initialized``.
      self.notify('ui/notifications/initialized');
      self.applyHostContext(result.hostContext);
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
    // מיזוג רדוד, כמו ה-SDK: שדה שהגיע מחליף את הקודם כולו, ושדה שלא הגיע נשאר.
    var merged = {};
    var oldKeys = Object.keys(this.hostContext);
    for (var o = 0; o < oldKeys.length; o += 1) merged[oldKeys[o]] = this.hostContext[oldKeys[o]];
    var newKeys = Object.keys(context);
    for (var n = 0; n < newKeys.length; n += 1) merged[newKeys[n]] = context[newKeys[n]];
    this.hostContext = merged;
    // הודעה על מסגרת או מצב תצוגה היא שינוי של המסגרת — הדיווח הבא יוצא גם אם המספר לא זז.
    if (Object.prototype.hasOwnProperty.call(context, 'containerDimensions')
        || Object.prototype.hasOwnProperty.call(context, 'displayMode')) {
      this.forceReport = true;
    }
    this.applyTheme(context);
    this.layout();
  };

  NoteView.prototype.applyTheme = function (context) {
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

  // -- מסגרת: גובה, שוליים בטוחים, מסך מלא ---------------------------------------------

  /** מעביר ל-CSS את מה שהמארח אמר על המסגרת. אין כאן חישוב גובה — הנוסחה ב-``note_view.css``. */
  NoteView.prototype.layout = function () {
    var docEl = this.doc.documentElement;
    var ctx = this.hostContext;
    var dims = isObject(ctx.containerDimensions) ? ctx.containerDimensions : {};
    var fill = isLength(dims.height, false);
    docEl.classList.toggle('ck-fill', fill);
    // במסך מלא בלי גובה קבוע הגובה הקבוע של השיחה אינו חל — ראו ``ck-expanded`` ב-CSS.
    docEl.classList.toggle('ck-expanded', !fill && ctx.displayMode === 'fullscreen');
    if (!fill && isLength(dims.maxHeight, false)) {
      docEl.style.setProperty('--ck-host-max', dims.maxHeight + 'px');
    } else {
      docEl.style.removeProperty('--ck-host-max');
    }
    var insets = isObject(ctx.safeAreaInsets) ? ctx.safeAreaInsets : {};
    for (var i = 0; i < SAFE_AREA_SIDES.length; i += 1) {
      var side = SAFE_AREA_SIDES[i];
      if (isLength(insets[side], true)) docEl.style.setProperty('--ck-safe-' + side, insets[side] + 'px');
      else docEl.style.removeProperty('--ck-safe-' + side);
    }
    this.updateControls();
    if (this.initialized) this.scheduleSize();
  };

  NoteView.prototype.canFullscreen = function () {
    var modes = this.hostContext.availableDisplayModes;
    return Array.isArray(modes) && modes.indexOf('fullscreen') !== -1
      && this.hostContext.displayMode !== 'fullscreen';
  };

  NoteView.prototype.requestFullscreen = function () {
    if (!this.initialized || !this.canFullscreen()) return;
    var self = this;
    // **שום דבר לא מוחזק בזמן ההמתנה** — אין דגל ואין כפתור מושבת, ולכן אין צורך בתקרת זמן
    // (``wait-without-own-deadline``, ה-False positive הראשון: בקשה חד-פעמית שהמשתמש יזם).
    // Claude מסרב לבקשה בלי לחיצה טרייה בדף, ולכן היא נשלחת רק מתוך ה-``click``.
    this.request('ui/request-display-mode', { mode: 'fullscreen' }, function (error, result) {
      // סירוב או שגיאה: הדף לא זז, הכפתור נשאר, והמשתמש יכול ללחוץ שוב. אין למי לדווח —
      // המצב על המסך הוא הדיווח.
      // "Host MUST return the resulting mode (whether updated or not)", ובסירוב המארח מחזיר את
      // המצב הנוכחי. רק ``fullscreen`` משנה כאן משהו — הכפתור נעלם מיד, והגודל החדש מגיע אחר כך
      // ב-``host-context-changed``.
      if (error || !isObject(result) || result.mode !== 'fullscreen') return;
      self.applyHostContext({ displayMode: 'fullscreen' });
    });
  };

  // -- גלילה בכפתורים ------------------------------------------------------------

  /** מי מהכפתורים מוצג. ▲▼ רק כשהגוף לא נכנס בגובה שהיה לו בלי שורת הגלילה. */
  NoteView.prototype.updateControls = function () {
    var v = this.view;
    if (!v) return;
    var expandShown = this.canFullscreen();
    v.expand.hidden = !expandShown;
    // שלב 1: השורה מוצגת לפי מה שכבר ידוע. שלב 2: האם הגוף גולש, **בגובה שהיה לו בלי ▲▼** —
    // כשהשורה מוצגת רק בגללם, הגובה שלה חוזר לגוף. כך ההחלטה אינה תלויה במצב הקודם של
    // הכפתורים, ואין הבהוב בין "גולש" ל"לא גולש".
    v.bar.hidden = !(expandShown || !v.group.hidden);
    var reclaim = (!v.bar.hidden && !expandShown) ? v.bar.offsetHeight : 0;
    var overflow = v.body.scrollHeight > v.body.clientHeight + reclaim + 1;
    v.group.hidden = !overflow;
    v.bar.hidden = !(expandShown || overflow);
    this.updateScrollButtons();
  };

  NoteView.prototype.updateScrollButtons = function () {
    var v = this.view;
    if (!v) return;
    var b = v.body;
    // סובלנות של פיקסל: ``scrollTop`` שבור במסכים עם יחס פיקסלים שאינו שלם.
    v.up.disabled = b.scrollTop <= 0;
    v.down.disabled = b.scrollTop + b.clientHeight >= b.scrollHeight - 1;
  };

  NoteView.prototype.scrollStep = function (direction) {
    var v = this.view;
    if (!v) return;
    var step = Math.max(1, Math.round(v.body.clientHeight * SCROLL_STEP_RATIO));
    // בלי ``behavior``: הרכות נקבעת ב-``scroll-behavior`` של ``.ck-body`` (ב-CSS, עם החריג של
    // ``prefers-reduced-motion``). **הכרעה סטטית על היעדר יכולת:** WebView ישן בלי ``scrollBy``
    // על אלמנט מקבל את אותה גלילה דרך ``scrollTop``.
    if (typeof v.body.scrollBy === 'function') v.body.scrollBy({ top: direction * step });
    else v.body.scrollTop += direction * step;
  };

  // -- הגדלת הטקסט של המערכת ---------------------------------------------------

  /** מודד בכמה המנוע מגדיל טקסט, ומבטל את ההגדלה — דרך ``text-size-adjust`` על ``html``, ואם המנוע
   *  אינו מכבד אותו, בחלוקה של כל גופן ב-CSS (``--ck-text-scale``).
   *
   *  **למה מדידה, ומה היא מודדת.** WebView של אנדרואיד מכפיל כל גופן בגודל הגופן של המערכת
   *  (``AwSettings.java``: "By default, scale the text size by the system font scale factor"), דרך
   *  ``TextZoomFactor`` של המסגרת. ב-Blink ההכפלה נכנסת לגודל המחושב
   *  (``FontBuilder::GetComputedSizeFromSpecifiedSize``), ו-``getComputedStyle`` מחזיר את הגודל
   *  המחושב חלקי הזום של העמוד בלבד (``ComputedStyleUtils::ValueForFontSize``). לכן אלמנט שמבקש
   *  ``TEXT_PROBE_PX`` מדווח בדיוק ``TEXT_PROBE_PX`` כפול ההגדלה — בלי לנחש לפי מכשיר, ובלי שום
   *  שינוי בדסקטופ ובווב, שם היחס 1. זום של כל העמוד אינו נכנס ליחס, ובצדק: הוא מגדיל גם את הגובה.
   *
   *  **למה ``text-size-adjust`` ולא חלוקה של הגופנים.** ``em`` נגזר מהגודל **שלפני** ההגדלה:
   *  ``CSSToLengthConversionData::FontSizes`` לוקח את ``SpecifiedFontSize()``, ו-``TextZoomFactor``
   *  נכנס רק לגודל המחושב. חלוקה של ``font-size`` מחזירה את הגופן לגודל של הוובאפ, אבל מקטינה את
   *  ה-``em`` באותו יחס — וכל הריווחים של ה-Markdown (שוליים, ריפוד וגובה מינימלי של שורה, שכולם
   *  ב-``em``) יוצאים צפופים. ``text-size-adjust`` נכנס **לאותה מכפלה** כמו ``TextZoomFactor``
   *  (``zoom_factor *= builder.GetTextSizeAdjust().Multiplier()``, באותה פונקציה), ולכן ``100% / יחס``
   *  מבטל את ההגדלה בלי לגעת בגודל המבוקש — והפתק זהה לוובאפ, גופן וריווח. WebView מכבד את התכונה
   *  כברירת מחדל ("The modern approach is for CSS to always honor text-size-adjust", ``aw_settings.cc``).
   *  הקבצים של Chromium נקראו בענף main ב-15.11.2026, והשרשרת כולה נמדדת בכרום 153 על
   *  ``TextZoomFactor`` האמיתי (``test_the_system_text_zoom_is_measured_and_undone``).
   *
   *  **ואם המנוע אינו מכבד אותו** — WebView ישן, שבו התכונה חלה רק כשהאפליקציה בחרה
   *  ``TEXT_AUTOSIZING`` — הבדיקה שאחרי ההצבה מגלה שההגדלה נשארה, והדף חוזר לחלוקה: הגופן בגודל של
   *  הוובאפ, והריווחים צפופים כמו לפני השינוי הזה. זו הכרעה על היעדר יכולת של המנוע, שקבועה לאורך
   *  חיי הדף, ולא נפילה על כשל (``silent-fallback-to-worse-path``, "היעדר יכולת מול כשל").
   *
   *  נקרא בעלייה ובכל מדידת גודל. שינוי של גודל הגופן במערכת בזמן שהתצוגה פתוחה משנה את גובה
   *  התוכן, ו-``ResizeObserver`` מוביל לכאן; פתק ארוך, שגובהו נעצר בתקרה, יתעדכן במדידה הבאה. */
  NoteView.prototype.measureTextScale = function () {
    var scale = this.probeScale('raw');
    // ערך שאינו מספר חיובי אינו מגיע מדפדפן אמיתי (אלמנט מחובר תמיד מקבל גודל בפיקסלים). אם
    // בכל זאת — הפתק נשאר בגודל של הוובאפ בלי פיצוי, שהוא ברירת המחדל של התצוגה, ולא נכנס ל-CSS
    // ערך לא תקין, שהיה מחזיר את כל הגופנים לגודל ההתחלתי של הדפדפן.
    if (!isLength(scale, false) || scale === this.textScale) return;
    this.textScale = scale;
    var style = this.doc.documentElement.style;
    style.removeProperty('--ck-text-scale');
    if (scale === 1) {
      style.removeProperty('text-size-adjust');
      return;
    }
    style.setProperty('text-size-adjust', (100 / scale) + '%');
    var left = this.probeScale('effect');
    if (isLength(left, false) && Math.abs(left - 1) <= TEXT_SCALE_EPSILON) return;
    style.removeProperty('text-size-adjust');
    style.setProperty('--ck-text-scale', String(scale));
  };

  /** היחס בין הגודל המחושב של אלמנט בדיקה לגודל שהוא מבקש. ``raw`` מצהיר ``text-size-adjust: auto``,
   *  כלומר "בלי התאמה" (``FontBuilder`` מדלג על המכפיל כשהערך ``auto``), ולכן אינו יורש את הפיצוי
   *  ומודד את ההגדלה של המנוע כמו שהיא — גם אחרי שהפיצוי הוצב. ``effect`` יורש מ-``html`` ומודד מה
   *  נשאר אחרי הפיצוי. **``display: none``** — לגודל מחושב אין צורך בפריסה, ואלמנט שאינו נפרס אינו
   *  משפיע על הגובה שהדף מדווח. הגודל קבוע ואינו עובר דרך ``--ck-text-scale``, כדי שהמדידה לא
   *  תמדוד את התיקון. */
  NoteView.prototype.probeScale = function (which) {
    var probe = this.textProbes[which];
    if (!probe) {
      probe = this.doc.createElement('span');
      probe.setAttribute('aria-hidden', 'true');
      probe.style.display = 'none';
      probe.style.fontSize = TEXT_PROBE_PX + 'px';
      if (which === 'raw') probe.style.setProperty('text-size-adjust', 'auto');
      this.doc.body.appendChild(probe);
      this.textProbes[which] = probe;
    }
    return parseFloat(this.win.getComputedStyle(probe).fontSize) / TEXT_PROBE_PX;
  };

  // -- גודל (``setupSizeChangedNotifications`` ב-SDK) ------------------------------------

  NoteView.prototype.measureAndReport = function () {
    this.measureTextScale();
    this.updateControls();
    var docEl = this.doc.documentElement;
    // כמו ה-SDK: גובה התוכן נמדד עם ``height: max-content`` זמני — ``fit-content`` היה נחתך
    // בגובה ה-viewport — והרוחב נלקח מ-``innerWidth``, בלי למדוד רוחב תוכן.
    var original = docEl.style.height;
    docEl.style.height = 'max-content';
    var height = Math.ceil(docEl.getBoundingClientRect().height);
    docEl.style.height = original;
    var width = Math.ceil(this.win.innerWidth);
    var force = this.forceReport;
    this.forceReport = false;
    if (force || width !== this.lastWidth || height !== this.lastHeight) {
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
    // **כל שינוי של המסגרת מדווח, גם כשהמספר לא זז** — ראו את ההערה בראש הקובץ. אין כאן
    // לולאה: המארח מציב את הגובה שדווח, ומסגרת שכבר בגובה הזה אינה משנה גודל ואינה יורה
    // ``resize`` נוסף. גם מארח שחותך לתקרה משלו מקבל דיווח אחד נוסף, ולא יותר.
    this.win.addEventListener('resize', function () {
      self.forceReport = true;
      self.scheduleSize();
    });
    // **הכרעה סטטית על היעדר יכולת, לא נפילה על כשל:** בלי ``ResizeObserver`` הגודל נמדד פעם
    // אחת עכשיו ופעם אחת אחרי כל רינדור (``render``).
    if (typeof this.win.ResizeObserver === 'function') {
      var observer = new this.win.ResizeObserver(function () { self.scheduleSize(); });
      observer.observe(this.doc.documentElement);
      observer.observe(this.doc.body);
      this.sizeObserver = observer;
      if (this.view) observer.observe(this.view.content);
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
    this.forgetView();
    if (this.initialized) this.scheduleSize();
  };

  /** הפתק המוצג יוצא מהמסך: הצופה מפסיק לצפות בתוכן שלו, והכפתורים שלו כבר אינם. */
  NoteView.prototype.forgetView = function () {
    if (this.sizeObserver && this.view) this.sizeObserver.unobserve(this.view.content);
    this.view = null;
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
    var md = this.win.StickyMdRender;
    // **הכרעה סטטית על היעדר יכולת, במקום אחד:** ``build_note_view`` מכניס את המנוע לדף, ו-
    // ``tests/test_mcp_note_view.py`` בודק שהוא שם. דף בלעדיו הוא דף שנבנה לא נכון, והמשתמש
    // רואה את זה במילים — לא פתק ריק, ולא חריגה שמשאירה "טוען…". **כל מה שהתצוגה לוקחת מהמנוע
    // נבדק כאן:** ``render`` לבנייה, ו-``MD_SAFE_LINK`` לקישורים. והאובייקט שנבדק הוא זה שהקישורים
    // נשפטים מולו (``onLinkClick`` מקבל אותו), כך שבזמן הלחיצה אין בדיקה שנייה ואין קריאה שנייה של
    // ``window`` — מנוע שעבר את הבדיקה הזו הוא המנוע של כל מה שקורה בפתק עד הרינדור הבא.
    if (!md || typeof md.render !== 'function' || !md.MD_SAFE_LINK || typeof md.MD_SAFE_LINK.test !== 'function') {
      this.settle();
      this.showStatus('התצוגה של הפתק לא נטענה במלואה, ולכן הפתק לא מוצג.', true);
      return;
    }
    this.forgetView();
    var paper = doc.createElement('article');
    // ``sticky-note`` — כמו הפתק בוובאפ. ``sticky-md-render.css`` תוחם בו את הכללים של הקישור, האלרט
    // והבלוק המתקפל, ומצהיר עליו את הטוקנים שהתוכן קורא (הדיו של הפתק ביניהם). המחלקה אינה מביאה
    // איתה את השלד של הפתק בלוח: הוא ב-``sticky-notes.css``, שהדף הזה אינו כולל.
    paper.className = 'ck-paper sticky-note';
    if (typeof note.color === 'string' && HEX_COLOR_RE.test(note.color)) {
      paper.style.backgroundColor = note.color;
      paper.className += ' has-note-color';
    }
    if (typeof note.title === 'string' && note.title.trim() !== '') {
      var title = doc.createElement('h1');
      title.className = 'ck-title';
      title.textContent = note.title;
      paper.appendChild(title);
    }
    var body = doc.createElement('div');
    body.className = 'ck-body';
    var self = this;
    body.addEventListener('click', function (event) { self.onLinkClick(event, md); });
    // **התוכן עטוף, ובכוונה.** ``ck-body`` הוא מכל הגלילה, ובגובה הקבוע הוא אינו משנה גודל כשהתוכן
    // שבתוכו גדל — בלוק מתקפל שנפתח, גופן שנטען. ``ResizeObserver`` על ``ck-content`` רואה את
    // זה, ולכן ▲▼ מופיעים ונעלמים לפי התוכן ולא רק לפי המסגרת.
    var content = doc.createElement('div');
    content.className = 'ck-content';
    body.appendChild(content);
    if (note.content === '') {
      var empty = doc.createElement('div');
      empty.className = 'ck-empty';
      empty.textContent = 'הפתק ריק.';
      content.appendChild(empty);
    } else {
      // **אותו מנוע ואותם כללים כמו בפתק בוובאפ**, במצב קריאה בלבד: בלי היסטים, צ'קבוקס מושבת,
      // ובלי כפתור העתקה. השורות יורשות ``rtl`` מהדף, כמו בפתק, ורק קוד בשורה ותאי טבלה מכריעים
      // כיוון לפי התוכן (``dir="auto"`` במנוע). התוכן נבנה עם ``createElement`` ו-``textContent``
      // בלבד — המנוע אינו כותב טקסט של משתמש דרך HTML (העמוד של המנוע, ``sticky-notes-render-untrusted``).
      md.render(content, note.content);
      this.titleLinks(content);
    }
    paper.appendChild(body);
    paper.appendChild(this.buildControls(body));
    this.view.content = content;
    host.textContent = '';
    host.appendChild(paper);
    if (this.sizeObserver) this.sizeObserver.observe(content);
    this.settle();
    this.updateControls();
    if (this.initialized) this.scheduleSize();
  };

  // -- קישורים -------------------------------------------------------------------

  /** הכתובת של כל קישור מופיעה כשמרחפים מעליו — גם כשהמארח אינו פותח קישורים, ואז היא כל מה
   *  שהמשתמש יכול לעשות איתו. */
  NoteView.prototype.titleLinks = function (el) {
    var kids = el.children || [];
    for (var i = 0; i < kids.length; i += 1) {
      var kid = kids[i];
      if (kid.tagName === 'A' && /(^|\s)sticky-md-link(\s|$)/.test(kid.className)) {
        kid.setAttribute('title', kid.getAttribute('href') || '');
      }
      this.titleLinks(kid);
    }
  };

  NoteView.prototype.canOpenLinks = function () {
    return isObject(this.hostCapabilities.openLinks);
  };

  /** לחיצה על קישור בפתק. **הדפדפן לעולם אינו מנווט בעצמו:** ``target="_blank"`` של המנוע אינו
   *  נפתח במסגרת מבודדת, וב-WebView של המובייל ניווט היה מחליף את התצוגה עצמה. במקומו — בקשה
   *  מהמארח, ``ui/open-link`` (המפרט, "Requests"), כשהמארח מודיע שהוא תומך בה (``openLinks``).
   *  ב-Claude, בקונקטור מותאם, המשתמש מאשר בחלון לפני שהקישור נפתח (התיעוד של Claude, "Open
   *  external links from MCP Apps"). ``md`` — המנוע שבנה את הקישור, כפי ש-``render`` בדק אותו. */
  NoteView.prototype.onLinkClick = function (event, md) {
    var target = event && event.target;
    var link = target && typeof target.closest === 'function' ? target.closest('a.sticky-md-link') : null;
    if (!link) return;
    event.preventDefault();
    var url = link.getAttribute('href');
    // הכלל של המנוע עצמו (``MD_SAFE_LINK``), ולא עותק שלו: המנוע כבר יצר קישור רק לכתובת שעברה
    // אותו, והבדיקה כאן היא הגבול שלפני מה שנשלח החוצה.
    if (!this.canOpenLinks() || typeof url !== 'string' || !md.MD_SAFE_LINK.test(url)) return;
    // **שום דבר לא מוחזק בזמן ההמתנה** (``wait-without-own-deadline``, ה-False positive הראשון):
    // אין דגל ואין קישור מושבת. סירוב, ביטול של המשתמש או שגיאה — הקישור נשאר, ואפשר ללחוץ שוב.
    this.request('ui/open-link', { url: url }, function () {});
  };

  /** שורת הכפתורים בתחתית הפתק. כולם מוסתרים עד ש-``updateControls`` מחליט אחרת. */
  NoteView.prototype.buildControls = function (body) {
    var self = this;
    var doc = this.doc;
    var button = function (className, text, label) {
      var b = doc.createElement('button');
      b.setAttribute('type', 'button');
      b.className = 'ck-btn ' + className;
      b.textContent = text;
      if (label) {
        b.setAttribute('aria-label', label);
        b.setAttribute('title', label);
      }
      return b;
    };
    var bar = doc.createElement('div');
    bar.className = 'ck-controls';
    var expand = button('ck-expand', 'מסך מלא', null);
    var group = doc.createElement('span');
    group.className = 'ck-scroll-btns';
    var up = button('ck-up', '▲', 'גלילה למעלה');
    var down = button('ck-down', '▼', 'גלילה למטה');
    group.appendChild(up);
    group.appendChild(down);
    bar.appendChild(expand);
    bar.appendChild(group);
    bar.hidden = true;
    expand.hidden = true;
    group.hidden = true;
    expand.addEventListener('click', function () { self.requestFullscreen(); });
    up.addEventListener('click', function () { self.scrollStep(-1); });
    down.addEventListener('click', function () { self.scrollStep(1); });
    body.addEventListener('scroll', function () { self.updateScrollButtons(); });
    this.view = { body: body, bar: bar, expand: expand, group: group, up: up, down: down };
    return bar;
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
