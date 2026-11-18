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
   מחליפה את "טוען…" בהודעה שאומרת מה לא הגיע, ותשובה שמגיעה אחריה עדיין מוצגת.

   **עריכה, במסך מלא.** לחיצה על שורה, או על ✎ ("עריכה"), פותחת את הטקסט הגולמי בתיבת טקסט, והסמן
   בשורה שנלחצה. השמירה עוברת דרך ``codekeeper_note_view_save`` — כלי שרק הדף מפעיל, בקשת
   ``tools/call`` שהמארח מעביר לשרת (המפרט, "Standard MCP Messages") — עם ה-``content_sha256``
   שהעריכה נבנתה עליו. כל צעד שמחכה למארח ומחזיק משהו (פתיחת העריכה, שמירה, בדיקת התנגשות) נושא
   תקרת זמן משלו, ``TOOL_DEADLINE_MS``. אחרי שמירה הדף מעדכן את המודל (``ui/update-model-context``),
   כי התוצאה שהכלי החזיר קודם, ושהמודל מחזיק, כבר אינה הפתק. **התשובה על שמירה שייכת לדף ולא לעורך
   ששלח אותה:** העורך יכול להיסגר בזמן שהבקשה בדרך (יציאה ממסך מלא של המארח), והשמירה עדיין נוחתת
   בשרת. הפירוט ליד ``beginEdit`` וליד ``save``.

   **המקלדת.** בזמן עריכה במסגרת קבועה הפתק מוצמד לשטח הגלוי (``visualViewport``), ורק תיבת הטקסט
   נגללת — ``syncVisibleArea``. באפליקציה של Claude המקלדת מגיעה דווקא ב-``safeAreaInsets.bottom``,
   והפתק נגמר בתחילת בלוק ההקלדה — ``syncEditBottom``. אנדרואיד דוחף את המסגרת כשהמקלדת נפתחת מעל
   הסמן, ולכן במסך מגע שורת הסמן עולה לראש התיבה לפני הפוקוס — ``beginKeyboardWait``. במסך שהצלע
   הקצרה שלו צרה (טלפון) אין עריכה — ``screenAllowsEditing``.
   ו-``layout_debug`` מהכלי מציג מספרים חיים על הפריסה, לבדיקה במכשיר — ``updateDebug``. */
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
  /** תקרת הזמן של כל צעד בעריכה שמחכה למארח — קריאה טרייה, שמירה, בדיקת התנגשות. בזמן ההמתנה
   *  משהו מוחזק (הכפתור "שמור" מושבת, או שהעריכה "נפתחת"), ולכן ההמתנה חייבת סוף משלה
   *  (``wait-without-own-deadline``). */
  var TOOL_DEADLINE_MS = 20000;
  /** תקרת הזמן של הריפוד הזמני בכניסה לעריכה (``beginKeyboardWait``): הוא מוחזק עד שהמארח מדווח על
   *  המקלדת, ובלי מקלדת על המסך (מקלדת פיזית, מקלדת שלא נפתחה) הדיווח לא מגיע — ולכן להמתנה יש סוף
   *  משלה (``wait-without-own-deadline``). המספר הוא מרווח שנבחר, לא מדידה: הזמן בפועל מהפוקוס ועד
   *  הדיווח מוצג במצב המדידה (``kb=``), כדי שהתקרה תיקבע לפיו. */
  var KEYBOARD_REPORT_DEADLINE_MS = 1500;
  /** הכלי שהתצוגה מציגה, והכלי שהיא שומרת דרכו (``mcp_server/server.py``). */
  var READ_TOOL = 'codekeeper_show_note';
  var SAVE_TOOL = 'codekeeper_note_view_save';
  /** הצלע הקצרה של המסך, בפיקסלים של הדף, שמתחתיה אין עריכה — הסף של אנדרואיד בין טלפון לטאבלט
   *  (``sw600dp``: "600dp: 7” tablet", "For phones (smaller than 600dp smallest width)", ב-
   *  "Responsive/adaptive design with views" של Android Developers). ראו ``screenAllowsEditing``. */
  var EDIT_MIN_SCREEN_SIDE_PX = 600;
  /** האייקון של "מסך מלא": ``maximize-2`` של Lucide ‏1.73.0 (``icons/maximize-2.svg`` ב-
   *  ``github.com/lucide-icons/lucide``), הצורות מילה במילה — אותה משפחה כמו אייקוני הפתק בוובאפ
   *  (``LINK_ICON_SHAPES`` ב-``sticky-notes.js``), ונבנה באותה פונקציה של המנוע (``buildStrokeIcon``). */
  var MAXIMIZE_ICON_SHAPES = [
    ['path', { d: 'M15 3h6v6' }],
    ['path', { d: 'm21 3-7 7' }],
    ['path', { d: 'm3 21 7-7' }],
    ['path', { d: 'M9 21H3v-6' }]
  ];
  /** "עריכה" — ``✎``, התו של כפתור עריכת השם בפתק בוובאפ (``editBtn`` ב-``sticky-notes.js``). תו טקסט
   *  ולא אימוג'י, ולכן הוא מקבל את ה-``color`` של הכפתור. */
  var EDIT_GLYPH = '\u270E';
  var MODEL_STALE_TEXT = 'Claude לא עודכן על השינוי האחרון. כדי שיעבוד על הגרסה השמורה, בקשו ממנו לקרוא את הפתק מחדש.';

  /** קוד שגיאה מהשרת מוצג רק כשהוא בצורה של קוד — מילה אחת באותיות קטנות. */
  var ERROR_CODE_RE = /^[a-z][a-z0-9_]{0,63}$/;
  /** הצבע של הפתק נכנס ל-CSS, ולכן רק בצורה שהשרת מייצר (``note_color_hex``): ``#rrggbb``. */
  var HEX_COLOR_RE = /^#[0-9a-fA-F]{6}$/;

  var ERROR_TEXT = {
    not_found: 'הפתק לא נמצא, או שאין לך גישה אליו.',
    invalid_note_id: 'מזהה הפתק אינו תקין.',
    conflict: 'הפתק נערך ממש עכשיו. נסו שוב.',
    rate_limited: 'יותר מדי קריאות בדקה האחרונה. נסו שוב בעוד רגע.',
    empty_content: 'אי אפשר לשמור פתק ריק.',
    content_too_long: 'הפתק ארוך מדי לשמירה.',
    insufficient_scope: 'לחיבור הזה אין הרשאת כתיבה, ולכן אי אפשר לשמור. אפשר לחבר את CodeKeeper מחדש עם הרשאת כתיבה.'
  };

  function isObject(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
  }

  /** מספר מהמארח, לפני שהוא נכנס ל-CSS: מספר אמיתי, סופי, ובטווח. ``NaN`` עובר כל השוואה
   *  כ-``false``, ולכן ``isFinite`` קודם (``amir-bug-patterns`` U3, סעיף 4). */
  /** האם שתי הודעות ``containerDimensions`` מתארות אותה מסגרת. ארבעת השדות של המפרט ("Specify either
   *  width or maxWidth, and either height or maxHeight", ``HostContext`` ב-``apps.mdx``). */
  function sameDimensions(a, b) {
    var x = isObject(a) ? a : {};
    var y = isObject(b) ? b : {};
    return x.width === y.width && x.maxWidth === y.maxWidth && x.height === y.height && x.maxHeight === y.maxHeight;
  }

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
    /** הפתק המוצג, ``editable`` של החיבור — ``{note, editable}`` — או ``null``. */
    this.current = null;
    /** העורך הפתוח (``openEditor``), או ``null``. */
    this.editor = null;
    /** פתיחה של עריכה שעוד מחכה למסך מלא ולקריאה הטרייה (``beginEdit``), או ``null``. */
    this.pendingEdit = null;
    /** ההודעה הקטנה שמתחת לפתק — "נשמר.", או למה העריכה לא נפתחה. */
    this.noticeText = null;
    this.noticeError = false;
    /** האם הגרסה האחרונה שנשמרה כאן לא הגיעה למודל (``updateModelContext``). מצב, ולא הודעה: הוא
     *  נשאר על המסך עד שעדכון מאוחר יותר מגיע, גם כשהודעות אחרות מתחלפות. */
    this.modelStale = false;
    /** מונה העדכונים למודל — רק התשובה לעדכון האחרון קובעת את ``modelStale``. */
    this.modelSeq = 0;
    /** מצב מדידה — ``layout_debug: true`` בתוצאת הכלי (``updateDebug``). */
    this.layoutDebug = false;
    /** העותק הנסתר של תיבת הטקסט שבו נמדד מקום הסמן (``revealCaret``), או ``null``. */
    this.caretMirror = null;
    this.revealScheduled = false;
    // השוליים התחתונים הגדולים ביותר מאז שהעורך נפתח (``syncEditBottom``), ההמתנה לדיווח על המקלדת
    // (``beginKeyboardWait``), ומה שקרה בהמתנה האחרונה — למצב המדידה.
    this.editBottom = null;
    this.editBottomStale = false;
    this.keyboardWait = null;
    this.keyboardReport = null;
    /** השמירה שבדרך — ``{ed, sent, base}`` — כולל הקריאה שמכריעה עליה, או ``null``. **של הדף ולא של
     *  העורך:** העורך יכול להיסגר בזמן שהיא בדרך, והתשובה עליה עדיין מעדכנת את הדף (``finishSave``). */
    this.saving = null;
    /** שמירה שהתשובה עליה לא הגיעה, ושהקריאה שאחריה לא הכריעה — ``{sent, baseSha}``, או ``null``.
     *  ראו ``decideUnconfirmed``. */
    this.unconfirmed = null;
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
    var oldDims = this.hostContext.containerDimensions;
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
    // **מסגרת בגודל אחר (סיבוב של המכשיר) — המקלדת שנזכרה כבר אינה בגובה הזה.** ההשוואה היא בערכים
    // ולא בעצם ההודעה: מארח ששולח את אותה מסגרת יחד עם שוליים חדשים אינו מאפס את מה שנזכר. **ושוליים
    // שלא הגיעו עם המסגרת החדשה הם של הקודמת:** הם ממשיכים לשמש לפריסה, אבל הדיווח הבא מחליף אותם — גם
    // כשהוא קטן מהם — ורק ממנו הזיכרון מתחיל שוב (``editBottomStale``, ``syncEditBottom``).
    var insetsArrived = Object.prototype.hasOwnProperty.call(context, 'safeAreaInsets');
    if (Object.prototype.hasOwnProperty.call(context, 'containerDimensions')
        && !sameDimensions(oldDims, merged.containerDimensions)) {
      this.editBottom = null;
      this.editBottomStale = !insetsArrived;
    } else if (insetsArrived && this.editBottomStale) {
      this.editBottom = null;
      this.editBottomStale = false;
    }
    this.applyTheme(context);
    this.layout();
    if (Object.prototype.hasOwnProperty.call(context, 'displayMode')) this.syncEditMode();
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
    this.syncEditBottom();
    this.updateControls();
    if (this.initialized) this.scheduleSize();
    // **המסגרת או השוליים השתנו — הסמן חוזר לתצוגה.** באפליקציה של Claude המקלדת מגיעה כאן, ב-
    // ``safeAreaInsets.bottom``, ולא כשינוי של השטח הגלוי: התיבה מתקצרת מתחת לסמן, ושום דבר אחר אינו
    // גולל אליו (``revealCaret`` חוזר מיד כשאין עורך בפוקוס).
    this.scheduleReveal();
  };

  /** השוליים התחתונים בזמן עריכה — **הגדולים ביותר מאז שהעורך נפתח**, ב-``--ck-edit-bottom`` (הנוסחה
   *  ב-``note_view.css``, ``html.ck-fill.ck-editing #ck-note-root``). כשהמקלדת נסגרת באמצע עריכה
   *  (כפתור "חזור" של אנדרואיד) השוליים קטנים, אבל הקו התחתון נשאר בגובה שלה: אחרת התיבה הייתה
   *  מתארכת אל השטח שהמקלדת תכסה, לחיצה על שורה נמוכה הייתה פותחת אותה עם הסמן שם, ואנדרואיד היה דוחף
   *  את המסגרת. ``editBottom`` מתאפס ביציאה מהעריכה ובמסגרת בגודל אחר (``applyHostContext``); כשההודעה
   *  על המסגרת החדשה אינה נושאת שוליים, הישנים נכנסים רק לפריסה (``editBottomStale``), והדיווח הבא מחליף
   *  אותם גם כשהוא קטן מהם.
   *  שוליים שגדלו בזמן ההמתנה לדיווח על המקלדת — הם הדיווח (``endKeyboardWait``). */
  NoteView.prototype.syncEditBottom = function () {
    var style = this.doc.documentElement.style;
    if (!this.editor) {
      this.editBottom = null;
      this.editBottomStale = false;
      style.removeProperty('--ck-edit-bottom');
      return;
    }
    var bottom = this.safeBottom();
    if (this.editBottom !== null && bottom <= this.editBottom) return;
    var grew = this.editBottom !== null;
    this.editBottom = bottom;
    style.setProperty('--ck-edit-bottom', bottom + 'px');
    if (grew && this.keyboardWait) this.endKeyboardWait('reported');
  };

  /** השוליים התחתונים שהמארח מסר עכשיו — 0 כשהם חסרים או אינם אורך תקין, כמו ב-``layout``. */
  NoteView.prototype.safeBottom = function () {
    var insets = isObject(this.hostContext.safeAreaInsets) ? this.hostContext.safeAreaInsets : {};
    return isLength(insets.bottom, true) ? insets.bottom : 0;
  };

  NoteView.prototype.canFullscreen = function () {
    var modes = this.hostContext.availableDisplayModes;
    return Array.isArray(modes) && modes.indexOf('fullscreen') !== -1
      && this.hostContext.displayMode !== 'fullscreen';
  };

  NoteView.prototype.requestFullscreen = function (then) {
    var done = typeof then === 'function' ? then : function () {};
    if (this.initialized && this.hostContext.displayMode === 'fullscreen') {
      done(true);
      return;
    }
    if (!this.initialized || !this.canFullscreen()) {
      done(false);
      return;
    }
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
      if (error || !isObject(result) || result.mode !== 'fullscreen') {
        done(false);
        return;
      }
      self.applyHostContext({ displayMode: 'fullscreen' });
      done(true);
    });
  };

  // -- גלילה בכפתורים ------------------------------------------------------------

  /** מי מהכפתורים מוצג. ▲▼ רק כשהגוף לא נכנס בגובה שהיה לו בלי שורת הגלילה. */
  NoteView.prototype.updateControls = function () {
    var v = this.view;
    if (!v) return;
    // כשהעורך מוצג, הגוף והשורה שלו מוסתרים (``syncEditMode``), ואין מה להחליט.
    if (this.editorShown()) {
      v.bar.hidden = true;
      return;
    }
    // **במסך מלא אין שורת כפתורים** (החלטת המשתמש): הגוף נגלל באצבע או בגלגלת, "מסך מלא" כבר אינו
    // רלוונטי, ועריכה נפתחת בלחיצה על שורה. הפתק מקבל את כל הגובה.
    if (this.hostContext.displayMode === 'fullscreen') {
      v.bar.hidden = true;
      v.expand.hidden = true;
      v.edit.hidden = true;
      v.group.hidden = true;
      return;
    }
    v.expand.hidden = !this.canFullscreen();
    v.edit.hidden = !(this.canEdit() && !this.editor && !this.pendingEdit && !this.saving);
    var actionShown = !v.expand.hidden || !v.edit.hidden;
    // שלב 1: השורה מוצגת לפי מה שכבר ידוע. שלב 2: האם הגוף גולש, **בגובה שהיה לו בלי ▲▼** —
    // כשהשורה מוצגת רק בגללם, הגובה שלה חוזר לגוף. כך ההחלטה אינה תלויה במצב הקודם של
    // הכפתורים, ואין הבהוב בין "גולש" ל"לא גולש".
    v.bar.hidden = !(actionShown || !v.group.hidden);
    var reclaim = (!v.bar.hidden && !actionShown) ? v.bar.offsetHeight : 0;
    var overflow = v.body.scrollHeight > v.body.clientHeight + reclaim + 1;
    v.group.hidden = !overflow;
    v.bar.hidden = !(actionShown || overflow);
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
    this.updateDebug();
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
      self.syncVisibleArea();
    });
    // **השטח הגלוי** (``visualViewport``): "User-interface features like the on-screen keyboard (OSK)
    // can shrink the visual viewport without affecting the layout viewport" (MDN, VisualViewport), ו-
    // ``resize`` / ``scroll`` שלו יורים כשהוא משתנה או זז. **הכרעה סטטית על היעדר יכולת:** בלעדיו
    // המשתנים אינם מוצבים, והעורך ממלא את המסגרת כמו קודם.
    var vv = this.win.visualViewport;
    if (vv && typeof vv.addEventListener === 'function') {
      var onVisibleArea = function () { self.syncVisibleArea(); };
      vv.addEventListener('resize', onVisibleArea);
      vv.addEventListener('scroll', onVisibleArea);
    }
    this.syncVisibleArea();
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

  // -- השטח הגלוי והסמן -----------------------------------------------------------

  /** **מעביר ל-CSS את השטח הגלוי** — הגובה שלו (``--ck-vv-height``) והמרחק שלו מראש הפריסה
   *  (``--ck-vv-top``), שניהם בפיקסלים של הדף ("in CSS pixels", MDN). **הנוסחה ב-``note_view.css``,
   *  לא כאן** (``amir-bug-patterns`` H7, "שתי נוסחאות לאותו מימד"), כמו התקרה של המארח ב-``layout``:
   *  בזמן עריכה במסגרת קבועה הפתק מוצמד לשטח הזה, כך שהכותרת ו"שמור"/"בטל" בראשו, ותיבת הטקסט היא
   *  היחידה שנגללת — במקום שהדפדפן יגלול את הדף כולו כדי להראות את הסמן מעל המקלדת.
   *
   *  **למה זה מספיק גם כשהמקלדת משנה את הפריסה עצמה:** אז גם הגובה הגלוי קטן, והמרחק נשאר 0. **ולמה
   *  באפליקציה של Claude זה לא משנה דבר:** השינוי שבו המקלדת מקטינה רק את השטח הגלוי "do not affect
   *  WebView" (Chrome for Developers, "Prepare for viewport resize behavior changes"), ונמדד בטאבלט
   *  (מצב המדידה, ``updateDebug``, 18.11.2026): השטח הגלוי והחלון נשארים בגובה המסגרת גם כשהמקלדת
   *  פתוחה. שם המקלדת מגיעה מהמארח, ב-``safeAreaInsets.bottom`` — ראו ``layout`` ו-``syncEditBottom``.
   *  מספר שאינו אורך תקין אינו נכנס ל-CSS. */
  NoteView.prototype.syncVisibleArea = function () {
    var vv = this.win.visualViewport;
    var style = this.doc.documentElement.style;
    if (vv && isLength(vv.height, false) && isLength(vv.offsetTop, true)) {
      style.setProperty('--ck-vv-height', vv.height + 'px');
      style.setProperty('--ck-vv-top', vv.offsetTop + 'px');
    } else {
      style.removeProperty('--ck-vv-height');
      style.removeProperty('--ck-vv-top');
    }
    this.scheduleReveal();
    this.updateDebug();
  };

  NoteView.prototype.scheduleReveal = function () {
    var self = this;
    if (this.revealScheduled) return;
    this.revealScheduled = true;
    var run = function () {
      self.revealScheduled = false;
      self.revealCaret();
    };
    if (typeof this.win.requestAnimationFrame === 'function') this.win.requestAnimationFrame(run);
    else run();
  };

  /** **מחזיר את הסמן לתוך תיבת הטקסט** אחרי שהיא התכווצה — המקלדת נפתחה, השטח הגלוי זז. נמדד בכרום:
   *  ``setSelectionRange`` על תיבה שבפוקוס אינו גולל אליו, ו-``focus()`` גולל אליו רק כשהתיבה מקבלת
   *  פוקוס (ו-``blur`` + ``focus`` היו סוגרים ופותחים את המקלדת במובייל). לכן המקום של הסמן נמדד:
   *  ``caretTop`` בונה עותק נסתר של התיבה, עם הסגנון המחושב שלה, ומודד את הגובה של הטקסט שלפני הסמן.
   *  רק גלילה אנכית של התיבה עצמה — שום מיקום אופקי אינו מחושב כאן. התיבה כולה גלויה: בזמן עריכה
   *  היא נגמרת מעל השוליים של המארח (``syncEditBottom``). */
  NoteView.prototype.revealCaret = function () {
    var ed = this.editor;
    if (!ed || !this.editorShown() || this.doc.activeElement !== ed.textarea) return;
    var ta = ed.textarea;
    var caret = this.caretTop(ta);
    if (!caret) return;
    if (caret.top < ta.scrollTop) ta.scrollTop = caret.top;
    else if (caret.top + caret.line > ta.scrollTop + ta.clientHeight) ta.scrollTop = caret.top + caret.line - ta.clientHeight;
  };

  /** **האם כניסה לעריכה תפתח מקלדת שעלולה לדחוף את המסגרת** — מסגרת בגובה קבוע (``ck-fill``, המסך
   *  המלא של Claude) ומסך מגע. ``(pointer: coarse)``: "The primary input mechanism includes a pointing
   *  device of limited accuracy, such as a finger on a touchscreen" (MDN). הכרעה סטטית על היכולת של
   *  המכשיר — דפדפן בלי ``matchMedia`` נחשב בלי מגע, כלומר העורך נפתח כמו במחשב. */
  NoteView.prototype.keyboardMayPush = function () {
    if (!this.doc.documentElement.classList.contains('ck-fill')) return false;
    return typeof this.win.matchMedia === 'function' && this.win.matchMedia('(pointer: coarse)').matches === true;
  };

  /** **הכניסה לעריכה בלי דחיפה.** אנדרואיד מזיז את כל החלון כשהמקלדת נפתחת, כדי שהסמן לא יוסתר — נמדד
   *  במכשיר: כניסה מהשורה הראשונה, המסגרת לא זזה; מהשורה התחתונה, נדחפה, והדף אינו רואה את ההזזה. לכן,
   *  **לפני** ``focus()``, שורת הסמן נגללת לראש התיבה (עם שורה אחת מעליה): זה המקום היחיד שבטוח יישאר
   *  גלוי לפני שגובה המקלדת ידוע. לשורות האחרונות אין מתחתן טקסט לגלול, ולכן ``ck-opening`` נותן לתיבה
   *  ריפוד זמני (``note_view.css``). נמדד בכרום: ``focus()`` אינו משנה גלילה שהוצבה לפניו, כשהסמן
   *  כבר בתוך התיבה. הריפוד יורד כשהמארח מדווח על המקלדת, בתקרת הזמן, או ביציאה מהעריכה
   *  (``endKeyboardWait``). */
  NoteView.prototype.beginKeyboardWait = function (ta) {
    var self = this;
    this.endKeyboardWait('restarted');
    ta.classList.toggle('ck-opening', true);
    var caret = this.caretTop(ta);
    if (caret) ta.scrollTop = Math.max(0, caret.top - caret.line);
    this.keyboardWait = {
      ta: ta,
      startedAt: Date.now(),
      timer: this.win.setTimeout(function () { self.endKeyboardWait('deadline'); }, KEYBOARD_REPORT_DEADLINE_MS)
    };
  };

  /** סוף ההמתנה לדיווח על המקלדת: הריפוד הזמני יורד, והסמן חוזר לתצוגה אם הגלילה זזה בגלל זה.
   *  ``how`` נשמר למצב המדידה — ``reported`` עם הזמן מהפוקוס, ``deadline``, ``closed`` או ``restarted``. */
  NoteView.prototype.endKeyboardWait = function (how) {
    var wait = this.keyboardWait;
    if (!wait) return;
    this.keyboardWait = null;
    this.win.clearTimeout(wait.timer);
    wait.ta.classList.toggle('ck-opening', false);
    this.keyboardReport = { how: how, ms: how === 'reported' ? Date.now() - wait.startedAt : null };
    this.scheduleReveal();
    this.updateDebug();
  };

  /** המרחק של הסמן מראש התוכן של התיבה, וגובה שורה — ``{top, line}``, או ``null`` כשאין למדוד. העותק
   *  מקבל את כל מה שקובע איפה שורה נשברת: הגופן, הריווח, הכיוון והריפוד, מהסגנון המחושב של התיבה, ו-
   *  ``clientWidth`` שלה — בלי פס הגלילה. אחרי המדידה הוא יוצא מהדף. */
  NoteView.prototype.caretTop = function (ta) {
    var cs = this.win.getComputedStyle(ta);
    var line = parseFloat(cs.lineHeight);
    var padInline = parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight);
    if (!isLength(line, false) || !isLength(ta.clientWidth, false)) return null;
    var mirror = this.caretMirror || this.doc.createElement('div');
    this.caretMirror = mirror;
    var props = ['fontFamily', 'fontSize', 'fontWeight', 'fontStyle', 'fontVariant', 'fontStretch', 'letterSpacing',
      'wordSpacing', 'lineHeight', 'textIndent', 'textTransform', 'tabSize', 'direction', 'overflowWrap', 'wordBreak',
      'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft'];
    for (var i = 0; i < props.length; i += 1) mirror.style[props[i]] = cs[props[i]];
    mirror.style.position = 'absolute';
    mirror.style.visibility = 'hidden';
    mirror.style.top = '0';
    mirror.style.boxSizing = 'content-box';
    mirror.style.whiteSpace = 'pre-wrap';
    mirror.style.border = '0';
    mirror.style.width = Math.max(0, ta.clientWidth - (isFinite(padInline) ? padInline : 0)) + 'px';
    mirror.textContent = ta.value.slice(0, ta.selectionStart);
    var marker = this.doc.createElement('span');
    marker.textContent = ta.value.slice(ta.selectionStart) || '.';
    mirror.appendChild(marker);
    this.doc.body.appendChild(mirror);
    var top = marker.offsetTop;
    this.doc.body.removeChild(mirror);
    return isLength(top, true) ? { top: top, line: line } : null;
  };

  // -- מצב מדידה ----------------------------------------------------------------------

  /** **מצב מדידה** (``layout_debug: true`` בתוצאת הכלי): מספרים חיים על הפריסה, כדי שבדיקה במכשיר —
   *  שאין בו כלי פיתוח — תתבסס על מדידה ולא על ניחוש: השטח הגלוי, החלון, המסך, מה שהמארח מסר על
   *  המסגרת ועל השוליים, ואיפה הנייר ותיבת הטקסט. **טקסט בלבד, מספרים בלבד** — בלי תוכן הפתק — ושום
   *  דבר אינו נשלח לשום מקום. */
  NoteView.prototype.updateDebug = function () {
    var v = this.view;
    if (!v || !v.debug) return;
    var w = this.win;
    var vv = w.visualViewport;
    var sc = w.screen;
    var ctx = this.hostContext;
    var num = function (n) { return typeof n === 'number' && isFinite(n) ? String(Math.round(n * 10) / 10) : '—'; };
    var box = function (el) {
      if (!el || typeof el.getBoundingClientRect !== 'function') return '—';
      var b = el.getBoundingClientRect();
      return num(b.top) + '..' + num(b.bottom) + ' (' + num(b.height) + ')';
    };
    var scroller = this.doc.scrollingElement || this.doc.documentElement;
    var lines = [
      'vv h=' + (vv ? num(vv.height) : '—') + ' top=' + (vv ? num(vv.offsetTop) : '—') + ' pageTop=' + (vv ? num(vv.pageTop) : '—')
        + ' scale=' + (vv ? num(vv.scale) : '—'),
      'inner ' + num(w.innerWidth) + 'x' + num(w.innerHeight) + ' scrollY=' + num(scroller.scrollTop) + ' dpr=' + num(w.devicePixelRatio),
      'screen ' + (sc ? num(sc.width) + 'x' + num(sc.height) : '—') + ' edit=' + this.screenAllowsEditing(),
      'mode=' + String(ctx.displayMode) + ' dims=' + JSON.stringify(isObject(ctx.containerDimensions) ? ctx.containerDimensions : null)
        + ' safe=' + JSON.stringify(isObject(ctx.safeAreaInsets) ? ctx.safeAreaInsets : null),
      'root ' + box(this.root()) + ' paper ' + box(v.paper)
    ];
    if (this.editor) {
      var ta = this.editor.textarea;
      lines.push('editor ' + box(ta) + ' scrollTop=' + num(ta.scrollTop) + ' focus=' + (this.doc.activeElement === ta));
      // הקו התחתון של העריכה, וההמתנה לדיווח על המקלדת: ``kb=reported 420ms`` הוא הזמן מהפוקוס ועד
      // שהשוליים גדלו — המספר שתקרת הזמן (``KEYBOARD_REPORT_DEADLINE_MS``) נקבעת לפיו.
      var report = this.keyboardReport;
      lines.push('edit-bottom=' + (this.editBottom === null ? '—' : num(this.editBottom))
        + ' opening=' + (this.keyboardWait ? 'on' : 'off')
        + ' kb=' + (report ? report.how + (report.ms === null ? '' : ' ' + num(report.ms) + 'ms') : '—'));
    }
    var text = lines.join('\n');
    if (v.debug.textContent !== text) v.debug.textContent = text;
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
    var content = result.content;
    if (result.isError === true) {
      // שגיאת כלי (``isError``) נושאת טקסט ולא JSON. הסירוב היחיד שהדף מזהה בה הוא חיבור בלי הרשאת
      // כתיבה (``auth.require_write``), כדי לומר למשתמש מה לעשות; כל השאר — הודעה כללית.
      var first = Array.isArray(content) && isObject(content[0]) && typeof content[0].text === 'string' ? content[0].text : '';
      return { error: /\binsufficient_scope\b/.test(first) ? 'insufficient_scope' : null };
    }
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
      return { error: code, max: isLength(answer.max, false) ? answer.max : null };
    }
    if (!isObject(answer.note) || typeof answer.note.content !== 'string') return { error: null };
    return { note: answer.note, editable: answer.editable === true, layoutDebug: answer.layout_debug === true };
  };

  /** הודעה למשתמש על סירוב מהשרת — הטקסט הידוע לקוד, או קוד השגיאה עצמו. */
  NoteView.prototype.errorText = function (read, fallback) {
    if (read.timeout) return 'לא התקבלה תשובה מ-Claude. נסו שוב.';
    var text = read.error && Object.prototype.hasOwnProperty.call(ERROR_TEXT, read.error) ? ERROR_TEXT[read.error] : null;
    if (read.error === 'content_too_long' && read.max) text = 'הפתק ארוך מדי לשמירה: עד ' + read.max + ' תווים.';
    return text || (fallback + (read.error ? ' (' + read.error + ').' : '.'));
  };

  NoteView.prototype.renderResult = function (result) {
    // **בזמן עריכה התוצאה אינה דורסת את העורך.** המארח שולח את תוצאת הכלי פעם אחת לכל תצוגה; תוצאה
    // נוספת בזמן שתיבת הטקסט פתוחה הייתה בונה את הפתק מחדש ומוחקת את מה שהוקלד.
    if (this.editor) return;
    var read = this.readNote(result);
    if (!read.note) {
      this.settle();
      var known = read.error && Object.prototype.hasOwnProperty.call(ERROR_TEXT, read.error)
        ? ERROR_TEXT[read.error] : null;
      var message = known || ('לא הצלחתי להציג את הפתק' + (read.error ? ' (' + read.error + ').' : '.'));
      this.showStatus(message, true);
      return;
    }
    this.current = { note: read.note, editable: read.editable === true };
    // מצב המדידה נקבע מהקריאה של המודל בלבד — הקריאות הטריות של העריכה אינן מבקשות אותו.
    this.layoutDebug = read.layoutDebug === true;
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
    // ``window`` — מנוע שעבר את הבדיקה הזו הוא המנוע של כל מה שקורה בפתק עד הרינדור הבא. גם
    // ``isViewControl`` ו-``sourceOffsetAt`` — מה לחיצה בגוף הפתק פוגעת בו (``onBodyClick``) — ו-
    // ``buildStrokeIcon`` לאייקונים של הכפתורים.
    if (!md || typeof md.render !== 'function' || !md.MD_SAFE_LINK || typeof md.MD_SAFE_LINK.test !== 'function'
        || typeof md.isViewControl !== 'function' || typeof md.sourceOffsetAt !== 'function'
        || typeof md.buildStrokeIcon !== 'function') {
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
    // **שורת הראש:** הכותרת (``paint``), ובזמן עריכה גם "שמור" ו"בטל" (``openEditor``) — שורה אחת.
    var head = doc.createElement('div');
    head.className = 'ck-head';
    paper.appendChild(head);
    var debug = null;
    if (this.layoutDebug) {
      debug = doc.createElement('div');
      debug.className = 'ck-debug';
      debug.setAttribute('dir', 'ltr');
      paper.appendChild(debug);
    }
    var body = doc.createElement('div');
    body.className = 'ck-body';
    var self = this;
    body.addEventListener('click', function (event) { self.onBodyClick(event, md); });
    // **התוכן עטוף, ובכוונה.** ``ck-body`` הוא מכל הגלילה, ובגובה הקבוע הוא אינו משנה גודל כשהתוכן
    // שבתוכו גדל — בלוק מתקפל שנפתח, גופן שנטען. ``ResizeObserver`` על ``ck-content`` רואה את
    // זה, ולכן ▲▼ מופיעים ונעלמים לפי התוכן ולא רק לפי המסגרת.
    var content = doc.createElement('div');
    content.className = 'ck-content';
    body.appendChild(content);
    paper.appendChild(body);
    paper.appendChild(this.buildControls(body, md));
    var notice = doc.createElement('p');
    notice.className = 'ck-notice';
    notice.setAttribute('role', 'status');
    paper.appendChild(notice);
    this.view.content = content;
    this.view.paper = paper;
    this.view.notice = notice;
    this.view.md = md;
    this.view.head = head;
    this.view.debug = debug;
    this.view.title = null;
    this.paint(note);
    this.syncNotice();
    host.textContent = '';
    host.appendChild(paper);
    if (this.sizeObserver) this.sizeObserver.observe(content);
    this.settle();
    this.updateControls();
    this.updateDebug();
    if (this.initialized) this.scheduleSize();
  };

  /** **מצייר את הפתק בתוך הנייר הקיים:** צבע, כותרת ותוכן. ``render`` בונה את הנייר וקורא לה; בזמן
   *  שעורך פתוח היא נקראת לבד, כי ``render`` היה בונה נייר חדש ומעלים את העורך שבתוכו. כך הפתק שמאחורי
   *  העורך — מה שמוצג בתוך השיחה כשיש שינוי שלא נשמר — הוא תמיד ``current``, הגרסה האחרונה שהדף יודע
   *  עליה, ולא הגרסה שהעריכה נפתחה עליה. ``md`` הוא המנוע ש-``render`` בדק. */
  NoteView.prototype.paint = function (note) {
    var v = this.view;
    if (!v) return;
    var paper = v.paper;
    var colored = typeof note.color === 'string' && HEX_COLOR_RE.test(note.color);
    paper.style.backgroundColor = colored ? note.color : '';
    paper.classList.toggle('has-note-color', colored);
    var hasTitle = typeof note.title === 'string' && note.title.trim() !== '';
    if (hasTitle && !v.title) {
      v.title = this.doc.createElement('h1');
      v.title.className = 'ck-title';
      v.head.insertBefore(v.title, v.head.firstChild);
    } else if (!hasTitle && v.title) {
      v.head.removeChild(v.title);
      v.title = null;
    }
    if (v.title) v.title.textContent = note.title;
    v.content.textContent = '';
    if (note.content === '') {
      var empty = this.doc.createElement('div');
      empty.className = 'ck-empty';
      empty.textContent = 'הפתק ריק.';
      v.content.appendChild(empty);
    } else {
      // **אותו מנוע ואותם כללים כמו בפתק בוובאפ**, במצב קריאה בלבד: צ'קבוקס מושבת, ובלי כפתור העתקה.
      // השורות יורשות ``rtl`` מהדף, כמו בפתק, ורק קוד בשורה ותאי טבלה מכריעים כיוון לפי התוכן
      // (``dir="auto"`` במנוע). התוכן נבנה עם ``createElement`` ו-``textContent`` בלבד — המנוע אינו כותב
      // טקסט של משתמש דרך HTML (העמוד של המנוע, ``sticky-notes-render-untrusted``). ``sourceOffsets`` —
      // ההיסט של כל שורה, כדי שלחיצה תפתח את העורך בשורה שנלחצה (``onBodyClick``).
      v.md.render(v.content, note.content, { sourceOffsets: true });
      this.titleLinks(v.content);
    }
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
    if (!link) return false;
    event.preventDefault();
    var url = link.getAttribute('href');
    // הכלל של המנוע עצמו (``MD_SAFE_LINK``), ולא עותק שלו: המנוע כבר יצר קישור רק לכתובת שעברה
    // אותו, והבדיקה כאן היא הגבול שלפני מה שנשלח החוצה.
    if (!this.canOpenLinks() || typeof url !== 'string' || !md.MD_SAFE_LINK.test(url)) return true;
    // **שום דבר לא מוחזק בזמן ההמתנה** (``wait-without-own-deadline``, ה-False positive הראשון):
    // אין דגל ואין קישור מושבת. סירוב, ביטול של המשתמש או שגיאה — הקישור נשאר, ואפשר ללחוץ שוב.
    this.request('ui/open-link', { url: url }, function () {});
    return true;
  };

  /** לחיצה בגוף הפתק: קישור נפתח דרך המארח, פקד אחר של המנוע עושה את שלו (כותרת של בלוק מתקפל
   *  מקפלת), וכל לחיצה אחרת פותחת עריכה בשורה שנלחצה — כמו ``_enterEditFromView`` בוובאפ, ועם אותן
   *  שתי תשובות של המנוע: ``isViewControl`` (מה אינו פותח עריכה) ו-``sourceOffsetAt`` (תחילת השורה
   *  במקור). */
  NoteView.prototype.onBodyClick = function (event, md) {
    if (this.onLinkClick(event, md)) return;
    var target = event && event.target;
    if (!target || md.isViewControl(target) || !this.canEdit()) return;
    this.beginEdit(md.sourceOffsetAt(target));
  };

  /** שורת הכפתורים בתחתית הפתק — **אייקונים בלבד**, והשם שלהם ב-``aria-label`` וב-``title``. כולם
   *  מוסתרים עד ש-``updateControls`` מחליט אחרת. ``md`` — המנוע ש-``render`` בדק. */
  NoteView.prototype.buildControls = function (body, md) {
    var self = this;
    var doc = this.doc;
    var button = function (className, label) {
      var b = doc.createElement('button');
      b.setAttribute('type', 'button');
      b.className = 'ck-btn ck-icon ' + className;
      b.setAttribute('aria-label', label);
      b.setAttribute('title', label);
      return b;
    };
    var bar = doc.createElement('div');
    bar.className = 'ck-controls';
    var expand = button('ck-expand', 'מסך מלא');
    expand.appendChild(md.buildStrokeIcon(MAXIMIZE_ICON_SHAPES));
    var edit = button('ck-edit', 'עריכה');
    edit.textContent = EDIT_GLYPH;
    var group = doc.createElement('span');
    group.className = 'ck-scroll-btns';
    var up = button('ck-up', 'גלילה למעלה');
    up.textContent = '▲';
    var down = button('ck-down', 'גלילה למטה');
    down.textContent = '▼';
    group.appendChild(up);
    group.appendChild(down);
    bar.appendChild(expand);
    bar.appendChild(edit);
    bar.appendChild(group);
    bar.hidden = true;
    expand.hidden = true;
    edit.hidden = true;
    group.hidden = true;
    expand.addEventListener('click', function () { self.requestFullscreen(); });
    edit.addEventListener('click', function () { self.beginEdit(null); });
    up.addEventListener('click', function () { self.scrollStep(-1); });
    down.addEventListener('click', function () { self.scrollStep(1); });
    body.addEventListener('scroll', function () { self.updateScrollButtons(); });
    this.view = { body: body, bar: bar, expand: expand, edit: edit, group: group, up: up, down: down };
    return bar;
  };

  // -- עריכה -----------------------------------------------------------------------

  /** האם להציע עריכה. **כל התנאים, במקום אחד:** החיבור יכול לשמור (``editable`` מהשרת), לפתק יש
   *  מזהה ו-hash שהשמירה תיבנה עליו, המארח מעביר קריאות לכלים של השרת (``serverTools`` — "Host
   *  can proxy tool calls to the MCP server", המפרט), המארח מציע מסך מלא — העריכה, בשלב הזה,
   *  נפתחת רק שם — והמסך אינו של טלפון (``screenAllowsEditing``). כשאחד מאלה חסר אין כפתור, ולחיצה
   *  על שורה אינה עושה דבר. */
  NoteView.prototype.canEdit = function () {
    var cur = this.current;
    var modes = this.hostContext.availableDisplayModes;
    return !!cur && cur.editable === true && typeof cur.note.id === 'string'
      && typeof cur.note.content_sha256 === 'string'
      && isObject(this.hostCapabilities.serverTools)
      && Array.isArray(modes) && modes.indexOf('fullscreen') !== -1
      && this.screenAllowsEditing();
  };

  /** **טלפון: תצוגה בלבד** (החלטת המשתמש) — גם אחרי שהעורך נבנה לפי השטח הגלוי, מעל המקלדת נשארות
   *  שורה או שתיים. הקריטריון הוא **הצלע הקצרה של המסך**, ``Math.min(screen.width, screen.height)`` —
   *  "returns the width of the screen in CSS pixels" (MDN, Screen.width) — מול
   *  ``EDIT_MIN_SCREEN_SIDE_PX``. **לא הרוחב:** טלפון שמוחזק לרוחב רחב מטאבלט שמוחזק לאורך, ומה שמגביל
   *  את העריכה הוא הגובה שנשאר מעל המקלדת — כלומר הצלע הקצרה. **ולא המסגרת:** בתוך השיחה היא נמוכה,
   *  ובחלונית הצד צרה, בלי קשר למכשיר. מסך שאינו נמדד (ערך שאינו אורך) — אין עריכה: מה שלא נמדד אינו
   *  מוצע. */
  NoteView.prototype.screenAllowsEditing = function () {
    var sc = this.win.screen;
    if (!sc) return false;
    var side = Math.min(sc.width, sc.height);
    return isLength(side, false) && side >= EDIT_MIN_SCREEN_SIDE_PX;
  };

  /** קריאה לכלי של השרת דרך המארח (``tools/call``), עם תקרת זמן משלה. ``done`` מקבל את מה ש-
   *  ``readNote`` מחזיר, או ``{timeout: true}``. תשובה שמגיעה אחרי התקרה נזרקת — מי שחיכה כבר
   *  קיבל ``timeout`` והמשיך — ובשמירה, ``timeout`` עובר לקריאה שמכריעה אם היא נחתה (``reconcile``). */
  NoteView.prototype.callTool = function (name, args, done) {
    var self = this;
    var finished = false;
    var timer = this.win.setTimeout(function () {
      if (finished) return;
      finished = true;
      done({ timeout: true, error: null });
    }, TOOL_DEADLINE_MS);
    this.request('tools/call', { name: name, arguments: args }, function (error, result) {
      if (finished) return;
      finished = true;
      self.win.clearTimeout(timer);
      done(error ? { error: null } : self.readNote(result));
    });
  };

  /** הודעה קטנה מתחת לפתק. נשמרת על הדף ולא על הנייר, כי שמירה בונה את הנייר מחדש. */
  NoteView.prototype.setNotice = function (text, isError) {
    this.noticeText = text;
    this.noticeError = !!isError;
    this.syncNotice();
  };

  /** ההודעה על המסך: ההודעה האחרונה, ואחריה — כל עוד ``modelStale`` — שהמודל לא עודכן. */
  NoteView.prototype.syncNotice = function () {
    var v = this.view;
    if (!v || !v.notice) return;
    var parts = [];
    if (this.noticeText) parts.push(this.noticeText);
    if (this.modelStale) parts.push(MODEL_STALE_TEXT);
    v.notice.textContent = parts.join(' ');
    v.notice.hidden = parts.length === 0;
    v.notice.className = this.noticeError ? 'ck-notice is-error' : 'ck-notice';
    if (this.initialized) this.scheduleSize();
  };

  /** **פותח עריכה.** שני דברים לפני שהעורך נפתח, במקביל:
   *
   *  1. **מסך מלא** (``ui/request-display-mode``), מתוך הלחיצה — Claude מסרב לבקשה בלי לחיצה טרייה.
   *     בתוך השיחה, במגע, גרירה אנכית בתוך התצוגה גוללת את השיחה ולא את תיבת הטקסט (התיעוד של
   *     Claude, "Scrolling and gestures"), ולכן העריכה נפתחת שם.
   *  2. **קריאה טרייה** של הפתק (``codekeeper_show_note`` דרך ``tools/call``). התוצאה שהתצוגה קיבלה
   *     שמורה בשיחה, ויכולה להיות בת ימים; עריכה שנבנתה עליה הייתה נתקלת בהתנגשות רק בשמירה, אחרי
   *     שהמשתמש כבר הקליד. אם הפתק השתנה, התצוגה מתעדכנת קודם, והסמן מתחיל בראש הטקסט — ההיסט
   *     שנלחץ שייך לטקסט הישן.
   *
   *  **שום דבר לא נשאר מחכה לנצח:** ``pendingEdit`` מונע פתיחה כפולה, ולכן כל הפתיחה נושאת תקרת זמן
   *  אחת, ``TOOL_DEADLINE_MS`` — גם אם המארח לא עונה על בקשת המסך המלא.
   *
   *  **ולא בזמן ששמירה בדרך** (``saving``) — עורך שנסגר באמצע שמירה משאיר אותה בדרך. עורך חדש היה נבנה
   *  על גרסה שהשמירה עומדת להחליף; ההמתנה חסומה בתקרות הזמן של השמירה. */
  NoteView.prototype.beginEdit = function (offset) {
    if (!this.canEdit() || this.editor || this.pendingEdit) return;
    if (this.saving) {
      this.setNotice('השמירה הקודמת עוד בדרך. נסו שוב בעוד רגע.', false);
      return;
    }
    var self = this;
    var job = { offset: offset, fullscreen: null, fresh: null, timer: null };
    this.pendingEdit = job;
    this.setNotice('פותח לעריכה…', false);
    this.updateControls();
    job.timer = this.win.setTimeout(function () {
      if (self.pendingEdit !== job) return;
      self.pendingEdit = null;
      self.setNotice('לא התקבלה תשובה מ-Claude, ולכן העריכה לא נפתחה. נסו שוב.', true);
      self.updateControls();
    }, TOOL_DEADLINE_MS);
    this.requestFullscreen(function (ok) {
      job.fullscreen = ok;
      self.continueEdit(job);
    });
    this.callTool(READ_TOOL, { note_id: this.current.note.id }, function (read) {
      job.fresh = read;
      self.continueEdit(job);
    });
  };

  NoteView.prototype.continueEdit = function (job) {
    if (this.pendingEdit !== job || job.fullscreen === null || job.fresh === null) return;
    this.pendingEdit = null;
    this.win.clearTimeout(job.timer);
    var read = job.fresh;
    // הגרסה הטרייה נכנסת לתצוגה לפני כל הכרעה אחרת — גם כשהעריכה לא תיפתח, מה שעל המסך עדכני.
    var changed = false;
    if (read.note) {
      changed = read.note.content_sha256 !== this.current.note.content_sha256;
      this.current = { note: read.note, editable: read.editable === true };
      if (this.decideUnconfirmed(read.note)) this.updateModelContext(read.note);
      if (changed) this.render(read.note);
    }
    if (!job.fullscreen) {
      this.setNotice('העריכה נפתחת במסך מלא, ו-Claude לא פתח אותו. נסו שוב.', true);
      this.updateControls();
      return;
    }
    if (!read.note) {
      this.setNotice(this.errorText(read, 'לא הצלחתי לקרוא את הגרסה העדכנית של הפתק, ולכן העריכה לא נפתחה'), true);
      this.updateControls();
      return;
    }
    if (!this.current.editable) {
      this.setNotice(ERROR_TEXT.insufficient_scope, true);
      this.updateControls();
      return;
    }
    this.setNotice(null, false);
    this.openEditor(changed ? null : job.offset);
  };

  /** בונה את העורך בתוך הנייר: שורת פעולות למעלה (שמור, בטל — למעלה, כי במובייל המקלדת ושדה
   *  ההודעה של Claude מכסים את התחתית), שורות להתנגשות ולביטול, ותיבת הטקסט. ``base`` הוא הפתק
   *  שהעריכה נבנית עליו — הגוף וה-hash שהשמירה שולחת כ-``expected_content_sha256``. */
  NoteView.prototype.openEditor = function (offset) {
    var v = this.view;
    if (!v || !v.paper) return;
    var self = this;
    var doc = this.doc;
    var note = this.current.note;
    var button = function (className, text) {
      var b = doc.createElement('button');
      b.setAttribute('type', 'button');
      b.className = 'ck-btn ' + className;
      b.textContent = text;
      return b;
    };
    var row = function (className) {
      var el = doc.createElement('div');
      el.className = className;
      return el;
    };
    // "שמור" ו"בטל" **בשורת הראש, עם הכותרת**, בקצה השמאלי שלה: הבאנר של Claude יושב באמצע ראש המסך,
    // וכפתור הסגירה שלו מימין. הסטטוס בשורה משלו, ומוצג רק כשיש בו משהו (``setEditStatus``).
    var bar = row('ck-edit-bar');
    var save = button('ck-save', 'שמור');
    var cancel = button('ck-cancel', 'בטל');
    var restore = button('ck-restore', 'החזר את הטקסט שלי');
    bar.appendChild(save);
    bar.appendChild(cancel);
    bar.appendChild(restore);
    var status = doc.createElement('p');
    status.className = 'ck-edit-status';
    status.setAttribute('role', 'status');
    var conflict = row('ck-conflict');
    var conflictText = doc.createElement('span');
    conflictText.textContent = 'הפתק השתנה מאז שהתחלת לערוך — בוובאפ או על ידי סוכן.';
    var accept = button('ck-accept', 'עדכן');
    var overwrite = button('ck-overwrite', 'שמור בכל זאת');
    conflict.appendChild(conflictText);
    conflict.appendChild(accept);
    conflict.appendChild(overwrite);
    var confirm = row('ck-confirm');
    var confirmText = doc.createElement('span');
    confirmText.textContent = 'לבטל את השינויים?';
    var discard = button('ck-discard', 'כן, לבטל');
    var keep = button('ck-keep', 'להמשיך לערוך');
    confirm.appendChild(confirmText);
    confirm.appendChild(discard);
    confirm.appendChild(keep);
    var textarea = doc.createElement('textarea');
    textarea.className = 'ck-editor';
    textarea.setAttribute('aria-label', 'תוכן הפתק');
    textarea.value = note.content;
    var unsaved = row('ck-unsaved');
    var unsavedText = doc.createElement('span');
    unsavedText.textContent = 'יש שינוי שלא נשמר.';
    var resume = button('ck-resume', 'המשך עריכה');
    var drop = button('ck-drop', 'בטל שינויים');
    unsaved.appendChild(unsavedText);
    unsaved.appendChild(resume);
    unsaved.appendChild(drop);
    v.head.appendChild(bar);
    var anchor = v.head.nextSibling;
    v.paper.insertBefore(status, anchor);
    v.paper.insertBefore(conflict, anchor);
    v.paper.insertBefore(confirm, anchor);
    v.paper.insertBefore(textarea, v.bar);
    v.paper.appendChild(unsaved);
    status.hidden = true;
    conflict.hidden = true;
    confirm.hidden = true;
    restore.hidden = true;
    this.editor = {
      base: { content: note.content, sha: note.content_sha256 },
      mine: null, server: null,
      bar: bar, save: save, cancel: cancel, restore: restore, status: status,
      conflict: conflict, confirm: confirm, textarea: textarea, unsaved: unsaved, drop: drop
    };
    this.editBottom = null;
    this.editBottomStale = false;
    this.syncEditBottom();
    save.addEventListener('click', function () { self.save(); });
    cancel.addEventListener('click', function () { self.askCancel(); });
    restore.addEventListener('click', function () { self.restoreMine(); });
    accept.addEventListener('click', function () { self.acceptServer(); });
    overwrite.addEventListener('click', function () { self.overwriteServer(); });
    discard.addEventListener('click', function () { self.discardEdit(); });
    keep.addEventListener('click', function () {
      self.editor.confirm.hidden = true;
      self.editor.textarea.focus();
    });
    resume.addEventListener('click', function () {
      self.requestFullscreen(function (ok) {
        if (!ok) self.setNotice('העריכה נפתחת במסך מלא, ו-Claude לא פתח אותו. נסו שוב.', true);
        else if (self.editor) self.editor.textarea.focus();
      });
    });
    drop.addEventListener('click', function () { self.discardEdit(); });
    // Ctrl/Cmd+S שומר, כמו בכל עורך — ולא שומר את הדף.
    textarea.addEventListener('keydown', function (event) {
      if ((event.ctrlKey || event.metaKey) && (event.key === 's' || event.key === 'S')) {
        event.preventDefault();
        self.save();
      }
    });
    textarea.addEventListener('scroll', function () { self.updateDebug(); });
    this.syncEditMode();
    // אחרי ``syncEditMode``: אלמנט מוסתר אינו מקבל פוקוס. הסמן בתחילת השורה שנלחצה — אותו מקום של
    // ``_enterEditAt`` בוובאפ. **הסמן קודם, הפוקוס אחריו:** נמדד בכרום ש-``focus()`` גולל את התיבה
    // אל הסמן, ו-``setSelectionRange`` על תיבה שכבר בפוקוס — לא. בסדר ההפוך, בפתק ארוך, התיבה הציגה
    // את המקום שבו הסמן היה לפני ההצבה, והסמן עצמו נשאר מחוץ לתיבה. **ובמסך מגע — שורת הסמן בראש
    // התיבה, לפני הפוקוס**, כדי שהמקלדת לא תדחוף את המסגרת (``beginKeyboardWait``).
    var pos = offset === null || !isFinite(offset) ? 0 : Math.max(0, Math.min(offset, textarea.value.length));
    textarea.setSelectionRange(pos, pos);
    if (this.keyboardMayPush()) this.beginKeyboardWait(textarea);
    textarea.focus();
    this.scheduleReveal();
    this.updateControls();
  };

  /** העורך מוצג רק במסך מלא. בתוך השיחה — הפתק, ואם יש שינוי שלא נשמר, שורה שאומרת את זה; בלי
   *  שינוי, יציאה ממסך מלא סוגרת את העריכה. */
  NoteView.prototype.syncEditMode = function () {
    var ed = this.editor;
    var v = this.view;
    if (!ed || !v) return;
    var shown = this.hostContext.displayMode === 'fullscreen';
    if (!shown && !this.isDirty()) {
      this.closeEditor();
      return;
    }
    ed.bar.hidden = !shown;
    ed.textarea.hidden = !shown;
    ed.status.hidden = !shown || !ed.status.textContent;
    if (!shown) {
      ed.conflict.hidden = true;
      ed.confirm.hidden = true;
    }
    ed.unsaved.hidden = shown;
    v.body.hidden = shown;
    // ``ck-editing`` — הכללים של העורך ב-CSS: שוליים קטנים, כותרת בשורה אחת, והצמדה לשטח הגלוי.
    this.doc.documentElement.classList.toggle('ck-editing', shown);
    this.updateControls();
    this.scheduleReveal();
    if (this.initialized) this.scheduleSize();
  };

  /** האם תיבת הטקסט היא מה שעל המסך — עורך פתוח, במסך מלא. */
  NoteView.prototype.editorShown = function () {
    return !!this.editor && this.hostContext.displayMode === 'fullscreen';
  };

  NoteView.prototype.isDirty = function () {
    var ed = this.editor;
    return !!ed && ed.textarea.value !== ed.base.content;
  };

  /** סוגר את העורך ומציג את הפתק — ``current``, הגרסה האחרונה שהדף יודע עליה. */
  NoteView.prototype.closeEditor = function () {
    var ed = this.editor;
    if (!ed) return;
    this.endKeyboardWait('closed');
    this.editor = null;
    this.syncEditBottom();
    this.doc.documentElement.classList.toggle('ck-editing', false);
    var parts = [ed.bar, ed.status, ed.conflict, ed.confirm, ed.textarea, ed.unsaved];
    for (var i = 0; i < parts.length; i += 1) {
      if (parts[i].parentNode) parts[i].parentNode.removeChild(parts[i]);
    }
    this.render(this.current.note);
  };

  NoteView.prototype.setEditStatus = function (text, isError) {
    var ed = this.editor;
    if (!ed) return;
    ed.status.textContent = text || '';
    ed.status.className = isError ? 'ck-edit-status is-error' : 'ck-edit-status';
    ed.status.hidden = !text || !this.editorShown();
  };

  /** בזמן ששמירה בדרך, הכפתורים שמשנים או סוגרים את העריכה מושבתים — "שמור", "בטל", ו"בטל שינויים"
   *  בשורה שבתוך השיחה — וכך גם "עריכה" (``updateControls``). **זה אינו מה ששומר על התשובה:** יציאה
   *  ממסך מלא של המארח סוגרת עורך נקי גם עכשיו, והתשובה מגיעה לדף בכל מקרה (``finishSave``). */
  NoteView.prototype.syncSaving = function () {
    var ed = this.editor;
    var busy = !!this.saving;
    if (ed) {
      ed.save.disabled = busy;
      ed.cancel.disabled = busy;
      ed.drop.disabled = busy;
    }
    this.updateControls();
  };

  /** **שמירה.** הגוף כולו, עם ה-hash שהעריכה נבנתה עליו (``expected_content_sha256``).
   *
   *  **התשובה שייכת לדף, ולא לעורך ששלח את הבקשה.** בזמן שהבקשה בדרך העורך יכול להיסגר — יציאה ממסך
   *  מלא של המארח סוגרת עורך שאין בו שינוי, גם כשהמשתמש החזיר את הטקסט למקור אחרי "שמור" — והשמירה
   *  עדיין נוחתת בשרת. תשובה שהייתה נזרקת כשהעורך כבר אינו פתוח הייתה משאירה בדף ובמודל את הגוף הישן,
   *  בזמן שבשרת יושב החדש. לכן כל תשובה עוברת ב-``finishSave`` / ``reconcile`` / ``failSave``, שמעדכנות
   *  קודם את הדף (``current``, המודל, ההודעה), ורק אחר כך את העורך — אם הוא עדיין העורך ששלח.
   *
   *  **שמירה אחת בכל פעם** (``saving``). תקרה שעברה אינה ראיה שהשמירה לא קרתה, ולכן היא, כמו
   *  ``conflict``, עוברת לקריאה שמכריעה (``reconcile``). */
  NoteView.prototype.save = function () {
    var ed = this.editor;
    if (!ed || this.saving) return;
    var self = this;
    var job = { ed: ed, sent: ed.textarea.value, base: ed.base };
    ed.confirm.hidden = true;
    this.saving = job;
    this.syncSaving();
    this.setEditStatus('שומר…', false);
    this.callTool(SAVE_TOOL, {
      note_id: this.current.note.id, content: job.sent, expected_content_sha256: job.base.sha
    }, function (read) {
      if (read.note) self.finishSave(job, read.note);
      else if (read.error === 'conflict') self.reconcile(job, false);
      else if (read.timeout) self.reconcile(job, true);
      else self.failSave(job, self.errorText(read, 'השמירה לא עברה'));
    });
  };

  /** שמירה שנחתה: הגרסה החדשה היא ``current``, והמודל לומד עליה. */
  NoteView.prototype.applySaved = function (note) {
    this.current = { note: note, editable: true };
    this.updateModelContext(note);
  };

  /** **שמירה שעברה** — מהתשובה, או מקריאה שהראתה בדיוק את מה שנשלח. הדף מתעדכן תמיד. העורך ששלח, אם
   *  הוא עדיין פתוח: נסגר — או, אם המשתמש המשיך להקליד בזמן השמירה, נשאר ונבנה מעכשיו על מה שנשמר,
   *  כדי שהשמירה הבאה לא תיתקל בעצמה. העורך כבר נסגר — הפתק מוצג מהגרסה השמורה. */
  NoteView.prototype.finishSave = function (job, note) {
    this.saving = null;
    this.decideUnconfirmed(note);
    this.applySaved(note);
    var ed = this.editor;
    if (ed === job.ed && ed.textarea.value !== job.sent) {
      ed.base = { content: note.content, sha: note.content_sha256 };
      ed.mine = null;
      ed.restore.hidden = true;
      this.paint(note);
      this.setEditStatus('נשמר. מה שהוקלד בזמן השמירה עוד לא נשמר.', false);
      this.syncSaving();
      return;
    }
    if (ed === job.ed) this.closeEditor();
    else this.render(note);
    this.setNotice('נשמר.', false);
    this.syncSaving();
  };

  /** **שמירה שלא עברה בוודאות** — סירוב שאינו התנגשות, או קריאה שלא הצליחה להכריע. */
  NoteView.prototype.failSave = function (job, text) {
    this.saving = null;
    if (this.editor === job.ed) this.setEditStatus(text, true);
    else this.setNotice(text, true);
    this.syncSaving();
  };

  /** ``unconfirmed`` — שמירה שהתשובה עליה לא הגיעה, ושהקריאה שאחריה לא הכריעה: ``{sent, baseSha}``.
   *  **היא יכולה עוד לנחות רק כל עוד הגוף שבשרת הוא הגוף שהיא נבנתה עליה** — השרת דוחה hash ישן
   *  (``conflict``), והדריסה שלו מותנית בגוף שנקרא. לכן כל גרסה שהדף רואה מכריעה עליה: הגוף שלה — היא
   *  נחתה; hash אחר מזה שהיא נבנתה עליו — היא כבר לא תנחת. מחזיר ``true`` כשהיא נחתה. */
  NoteView.prototype.decideUnconfirmed = function (fresh) {
    var u = this.unconfirmed;
    if (!u) return false;
    var landed = fresh.content === u.sent;
    if (landed || fresh.content_sha256 !== u.baseSha) this.unconfirmed = null;
    return landed;
  };

  /** **מכריע מה קרה לשמירה** — אחרי ``conflict``, או אחרי תקרה שעברה (``afterTimeout``) — לפי קריאה
   *  טרייה של הפתק:
   *
   *  - **הגוף שבשרת הוא בדיוק מה שנשלח** — השמירה נחתה (תשובה שהלכה לאיבוד, תקרה שעברה). הצלחה.
   *  - **הגוף שבשרת הוא מה ששמירה קודמת שלחה, שלא הוכרעה** (``unconfirmed``) — שמירה של הדף, ולא
   *    שינוי של מישהו אחר. העריכה נבנית עליה, והשמירה הנוכחית יוצאת שוב; ``unconfirmed`` מתאפס לפני
   *    כן, ולכן זה קורה פעם אחת לכל היותר.
   *  - **אחרי תקרה, והפתק לא השתנה** — ייתכן שהשמירה עוד בדרך. היא נרשמת כ-``unconfirmed``, והמשתמש
   *    יכול לשמור שוב.
   *  - **אחרת — מישהו אחר שינה.** הטקסט נשאר בעורך, ושורה מציעה "עדכן" או "שמור בכל זאת", כמו הפס
   *    בוובאפ.
   *
   *  בכל המקרים הגרסה הטרייה היא ``current``, ומה שמוצג מאחורי העורך מתעדכן אליה. עורך שכבר נסגר —
   *  הפתק מוצג מהגרסה הטרייה, וההודעה אומרת מה קרה לשמירה. */
  NoteView.prototype.reconcile = function (job, afterTimeout) {
    var self = this;
    if (this.editor === job.ed) {
      this.setEditStatus(afterTimeout ? 'לא התקבלה תשובה על השמירה. בודק אם היא עברה…'
        : 'הפתק השתנה מאז שהתחלת לערוך. בודק מה השתנה…', false);
    }
    this.callTool(READ_TOOL, { note_id: this.current.note.id }, function (read) {
      var fresh = read.note;
      if (!fresh) {
        if (afterTimeout) self.unconfirmed = { sent: job.sent, baseSha: job.base.sha };
        self.failSave(job, afterTimeout
          ? 'לא התקבלה תשובה על השמירה, ולא הצלחתי לבדוק אם היא עברה. לחיצה נוספת על "שמור" תבדוק.'
          : self.errorText(read, 'השמירה נדחתה כי הפתק השתנה, ולא הצלחתי לקרוא את הגרסה החדשה. נסו שוב'));
        return;
      }
      if (fresh.content === job.sent) {
        self.finishSave(job, fresh);
        return;
      }
      var earlierLanded = self.decideUnconfirmed(fresh);
      var unchanged = fresh.content_sha256 === job.base.sha;
      if (afterTimeout && unchanged) self.unconfirmed = { sent: job.sent, baseSha: job.base.sha };
      self.current = { note: fresh, editable: read.editable === true };
      self.saving = null;
      if (earlierLanded) self.updateModelContext(fresh);
      var ed = self.editor;
      if (ed !== job.ed) {
        self.render(fresh);
        self.setNotice(afterTimeout && unchanged ? 'לא התקבלה תשובה על השמירה. ייתכן שהיא עוד בדרך.'
          : 'השמירה לא עברה: הפתק השתנה בינתיים. מוצגת הגרסה העדכנית.', true);
        self.syncSaving();
        return;
      }
      self.paint(fresh);
      if (earlierLanded) {
        ed.base = { content: fresh.content, sha: fresh.content_sha256 };
        self.save();
        return;
      }
      if (unchanged) {
        self.setEditStatus('לא התקבלה תשובה על השמירה, והפתק עוד לא השתנה — ייתכן שהיא עוד בדרך. לחיצה נוספת על "שמור" תשלח שוב.', true);
      } else {
        ed.server = fresh;
        ed.conflict.hidden = false;
        self.setEditStatus('', false);
      }
      self.syncSaving();
      if (self.initialized) self.scheduleSize();
    });
  };

  /** "עדכן": הגרסה שבשרת נכנסת לעורך, והטקסט שלי נשמר בצד — כפתור אחד מחזיר אותו. כתיבה ל-
   *  ``value`` מוחקת את הביטול של הדפדפן, ולכן הכפתור, ולא Ctrl+Z. */
  NoteView.prototype.acceptServer = function () {
    var ed = this.editor;
    if (!ed || !ed.server) return;
    ed.mine = ed.textarea.value;
    ed.textarea.value = ed.server.content;
    ed.base = { content: ed.server.content, sha: ed.server.content_sha256 };
    ed.server = null;
    ed.conflict.hidden = true;
    ed.restore.hidden = false;
    this.setEditStatus('נטענה הגרסה העדכנית.', false);
    ed.textarea.focus();
  };

  /** "שמור בכל זאת": הטקסט שלי נשמר מעל הגרסה שבשרת — מעל **אותה** גרסה. אם היא השתנתה שוב בינתיים,
   *  השמירה נתקלת בהתנגשות חדשה, כמו "התעלם" בוובאפ. */
  NoteView.prototype.overwriteServer = function () {
    var ed = this.editor;
    if (!ed || !ed.server) return;
    ed.base = { content: ed.server.content, sha: ed.server.content_sha256 };
    ed.server = null;
    ed.conflict.hidden = true;
    this.save();
  };

  NoteView.prototype.restoreMine = function () {
    var ed = this.editor;
    if (!ed || ed.mine === null) return;
    ed.textarea.value = ed.mine;
    ed.mine = null;
    ed.restore.hidden = true;
    this.setEditStatus('', false);
    ed.textarea.focus();
  };

  /** "בטל": בלי שינוי — סוגר. עם שינוי — שואל בתוך הדף; חלון אישור של הדפדפן אינו נפתח במסגרת
   *  מבודדת בלי ``allow-modals``. */
  NoteView.prototype.askCancel = function () {
    var ed = this.editor;
    if (!ed || this.saving) return;
    if (!this.isDirty()) {
      this.closeEditor();
      return;
    }
    ed.confirm.hidden = false;
    if (this.initialized) this.scheduleSize();
  };

  NoteView.prototype.discardEdit = function () {
    if (!this.editor || this.saving) return;
    this.closeEditor();
  };

  /** **המודל לומד מה נשמר** (``ui/update-model-context``): "This context will be used in future
   *  turns. Each request overwrites the previous context sent by the View" (המפרט). בלי זה המודל
   *  עובד על הגוף שהכלי החזיר לפני העריכה. הצורה — frontmatter ואחריו הגוף — היא של הדוגמה ב-
   *  ``docs/patterns.md`` של ext-apps. הבקשה נשלחת גם כשהמארח אינו מצהיר על ``updateModelContext``
   *  (ה-SDK אינו בודק את היכולת לפני שהוא שולח), וההכרעה היא לפי התשובה: סירוב או שגיאה —
   *  ``modelStale``, וההודעה שמתחת לפתק אומרת שהמודל לא עודכן, כדי שהמשתמש ידע לבקש ממנו לקרוא את
   *  הפתק מחדש. **רק התשובה לעדכון האחרון קובעת:** כל עדכון מחליף את הקודם, ולכן תשובה מאוחרת לעדכון
   *  ישן אינה אומרת דבר על מה שהמודל מחזיק עכשיו. שום דבר לא מוחזק בזמן ההמתנה, ולכן אין תקרת זמן. */
  NoteView.prototype.updateModelContext = function (note) {
    var self = this;
    this.modelSeq += 1;
    var seq = this.modelSeq;
    var lines = ['---', 'note_id: ' + note.id, 'content_sha256: ' + note.content_sha256];
    if (typeof note.title === 'string' && note.title !== '') lines.push('title: ' + JSON.stringify(note.title));
    lines.push('---', '',
      'The user edited this sticky note in the note view and saved it. Its current content is below; it '
      + 'replaces the content in the earlier codekeeper_show_note result.', '', note.content);
    this.request('ui/update-model-context', { content: [{ type: 'text', text: lines.join('\n') }] }, function (error) {
      if (seq !== self.modelSeq) return;
      self.modelStale = !!error;
      self.syncNotice();
    });
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
