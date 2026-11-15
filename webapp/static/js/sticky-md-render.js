/* מנוע התצוגה של פתק — טקסט הפתק ← צמתים, שורה אחר שורה.

   **המקום האחד שמחליט איך Markdown של פתק נראה.** עד נובמבר 2026 המנוע ישב בתוך המחלקה
   ``StickyNotesManager`` ב-``sticky-notes.js``, קשור לפתק שאפשר לערוך: כל שורה נושאת
   ``data-charOffset`` כדי שלחיצה תיכנס לעריכה בשורה הנכונה, והצ'קבוקסים מסונכרנים עם הספירה של
   השרת. תצוגה של פתק במקום אחר — תגובה בשרשור, התצוגה בתוך Claude — הייתה צריכה עותק שלישי של
   הפרסר, ועותק שלישי הוא ניב שלישי. ההסבר המלא ב-``docs/dev/sticky_notes_extending_markdown.rst``
   (:ref:`sticky-notes-md-engine-module`).

   **שני מצבים, ומחלקה אחת.**
     - **הפתק:** ``mixInto(StickyNotesManager.prototype)`` מצמיד את המתודות למנהל, והוא קורא להן בדיוק
       כמו קודם (``this._parseInline``, ``this._renderMarkdownView`` ...). המתודות הועברו לכאן כמו שהן;
       ההיסטים, הצ'קבוקסים וכפתור ההעתקה (``_mdCodeCopyButton``, של המארח) נשארו אותו דבר.
     - **קריאה בלבד:** ``render(container, text)`` — מנוע עם ``readOnly``: בלי ``data-charOffset``,
       צ'קבוקס מושבת, ובלי כפתור העתקה כשאין מארח שמספק אותו.

   **אפס ``innerHTML`` על התוכן** — החוזה של המנוע (``_appendAlertIcon`` הוא החריג היחיד, על
   מחרוזת SVG קבועה מהמפה המשותפת). הקובץ נטען **לפני** ``sticky-notes.js`` בכל תבנית, ואחרי
   ``admonition-icons.js``, ``utils/file-name.js`` ו-``utils/rtl-code.js`` שהוא קורא מ-``window``;
   הבדיקה ב-``tests/sticky-notes-target.test.js`` סורקת את התבניות ואוכפת את הסדר. */
(function(){
  'use strict';

  if (typeof window === 'undefined') return;

  function createEl(tag, className, attrs){
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (attrs) Object.keys(attrs).forEach(k => el.setAttribute(k, attrs[k]));
    return el;
  }
  // **קוד בשורה: הטקסט והכיוון, דרך ``RtlCode.fillInlineCode``** (``utils/rtl-code.js``, וההסבר שם).
  // קוד רגיל מקבל ``dir="auto"``, כמו בתצוגת המסמך (``MdAutoDirPlugin``); שם קובץ עברי שהדפדפן היה
  // מציג עם הסיומת באמצע מקבל ``dir="rtl"`` והסיומת מבודדת ב-``<bdi>``. ולכן אין ל-``.sticky-md-code``
  // ב-``sticky-notes.css`` שום ``direction`` או ``unicode-bidi``: ``direction`` של המחבר גובר על
  // הכיוון שהתכונה קובעת, ו-``unicode-bidi`` על הבידוד שהדפדפן נותן לה — שניהם בשקט.
  //
  // **היעדר ``window.RtlCode`` הוא היעדר יכולת סטטי** (התבנית לא טענה את הקובץ — בדיקת החיווט ב-
  // ``tests/sticky-notes-target.test.js`` דורשת שהוא נטען לפני המודול), ולא כשל: הקוד מוצג אז כמו
  // לפני הפירוק, עם ``dir="auto"``. גם הכרטיס של פתק (``note-cards.js``) בונה קוד בשורה דרך כאן.
  function fillInlineCode(el, text){
    const rtl = window.RtlCode;
    if (rtl && typeof rtl.fillInlineCode === 'function') return rtl.fillInlineCode(el, text);
    el.setAttribute('dir', 'auto');
    el.textContent = text;
    return el;
  }
  //: טקסט שהמנוע מייצר ואינו כתוב בפתק — ראו ``_markGenerated``.
  const GENERATED_TEXT_CLASS = 'sticky-md-generated';

  const TASK_LINE_RE = /^([ \t]*[-*][ \t]\[)([ xX])(\].*)$/;
  //: מארקדאון קליל בפתקים. תת-קבוצה מוצהרת ומצומצמת — ראו
  //: docs/user/sticky_notes.rst. כל דפוס נבחר כי הוא נכנס בפתק קטן
  //: ומרונדר בשורה אחת, וכל מה שאוכל גובה או פותח משטח הזרקה נשאר בחוץ.
  const MD_HEADING_RE = /^(#{1,3})[ \t]+(.*)$/;
  const MD_QUOTE_RE   = /^[ \t]*>[ \t]?(.*)$/;
  const MD_HR_RE      = /^[ \t]*-{3,}[ \t]*$/;
  //: **הרווחים שאחרי הסמן נלכדים בקבוצה משלהם**, ולא נבלעים בכמת.
  //: מהם נגזרת עמודת התוכן של הפריט, וממנה עומק הקינון — ראו
  //: ``_listContentCol``. בלי הקבוצה הזו אין דרך לדעת היכן מתחיל הטקסט.
  const MD_OL_RE      = /^([ \t]*)(\d+)\.([ \t]+)(.*)$/;
  const MD_UL_RE      = /^([ \t]*)([-*])([ \t]+)(.*)$/;
  //: טאב מתקדם לעמודה הבאה שמתחלקת ב-4. מקור: ``markdown-it@14.1.0``,
  //: ``lib/rules_block/state_block.mjs`` — ``offset += 4 - offset % 4``.
  //: זו הספרייה שמרנדרת את תצוגת ה-Markdown בריפו, ולכן היא הצרכן
  //: שהפתק צריך להסכים איתו על מה נחשב מקונן.
  const MD_TAB_STOP = 4;
  //: **ההגדרה היחידה של "רווח מוביל".** ``MD_UL_RE``/``MD_OL_RE`` מכילים
  //: אותה קבוצה, אבל אף אחד לא קורא אותה: כל השאלות על הזחה נענות
  //: דרך ``_lineIndentCols``, כדי שלא יהיו שני חלקים שחולקים על מה
  //: נחשב הזחה — הדפוס שכבר נשך כאן בזיהוי מפריד הטבלה.
  const MD_INDENT_RE  = /^[ \t]*/;
  //: תקרת הזחה. מעליה כל הרמות מקבלות את אותו רוחב — הפתק צר, והזחה
  //: בלתי מוגבלת דוחקת את הטקסט לרצועה של תו-תו. הרמות העמוקות עדיין
  //: מוצגות; הן פשוט אינן נכנסות עוד פנימה.
  const MD_MAX_LIST_DEPTH = 5;
  //: תבליט לפי עומק, כמו רשימה מקוננת רגילה בדפדפן. **נמדד ולא הונח:**
  //: ``getComputedStyle(ul).listStyleType`` בכרומיום מחזיר ``disc`` לרמה
  //: הראשונה, ``circle`` לשנייה ו-``square`` משלישית ואילך — והרמה
  //: האחרונה חוזרת על עצמה, בדיוק כמו כאן.
  const MD_BULLETS = ['•', '◦', '▪'];
  const MD_FENCE_RE   = /^[ \t]*```/;
  //: טבלת GFM מזוהה בזוג בלבד: שורה עם ``|`` ומיד אחריה שורת מפריד
  //: שכל תאיה מקפים, עם יישור אופציונלי. בלי הזוג הזה כל שורה שמכילה
  //: מקף אנכי — נתיב, פקודה, ביטוי לוגי — הייתה נבלעת לטבלה.
  const MD_TABLE_SEP_RE = /^[ \t]*\|?[ \t]*:?-{1,}:?[ \t]*(\|[ \t]*:?-{1,}:?[ \t]*)*\|?[ \t]*$/;
  //: **מארקדאון בתוך שורה: קוד בשורה קודם, וכל השאר אחריו.** זה הסדר של
  //: ``markdown-it@14.1.0``, שמרנדר את תצוגת המסמך. ``lib/parser_inline.mjs``
  //: שלו מריץ את ``backticks`` לפני ``strikethrough``, ``emphasis`` ו-``link``,
  //: וקטע קוד שנמצא נצרך כיחידה אחת — מפריד שבתוכו אינו מפריד. את ה-``**``
  //: הוא אינו סוגר במקום: הוא מסמן אותם ומזווג רק בשלב שני
  //: (``lib/rules_inline/balance_pairs.mjs``). לכן ``**מילים עם `קוד` בתוך**``
  //: הוא מודגש שבתוכו קוד. כשכל זה היה רג'קס אחד, נבחר מה שמתחיל ראשון
  //: בשורה, וה-``**`` בלע את הגרשיים כטקסט. המדידה מול markdown-it והנימוק
  //: המלא: ``docs/dev/sticky_notes_extending_markdown.rst``, בסעיף "קוד בשורה: יחידה
  //: אחת, שקודמת לכל מפריד".
  //:
  //: **רק השלב הראשון הועתק.** הזיווג של ``**``/``*``/``~~``/``==`` נשאר הכלל
  //: שלנו: הסוגר הוא הראשון שמחוץ לקוד, ועיצוב אינו מכיל עיצוב אחר — ולכן
  //: ``==**x**==`` עדיין מציג את הכוכביות. זה נושא נפרד: מה שפותר אותו הוא
  //: ``balance_pairs``, והוא משנה הרבה יותר מקוד בשורה.
  //:
  //: הקו התחתון **אינו** נטוי, בכוונה: ``note_id`` ו-``user_id`` נפוצים מדי
  //: בכלי שכולו על קוד.
  //:
  //: רווח אחד בכל קצה של קוד בשורה נחתך, אם יש ביניהם משהו — מילה במילה
  //: מ-``lib/rules_inline/backticks.mjs``.
  const MD_CODE_TRIM_RE = /^ (.+) $/;
  //: התווים היחידים שיכולים לפתוח משהו בשורה. כל השאר טקסט, והסריקה קופצת
  //: עליו בבת אחת.
  const MD_INLINE_START_RE = /[`[*~=]/g;
  //: התו שמסיים יעד של קישור: הסוגר, או רווח — ורווח פוסל את הקישור.
  const MD_LINK_DEST_STOP_RE = /[)\s]/;
  //: מרקר אינו נצמד לרווח — ראו ``_matchInlineMark``.
  const MD_MARK_EDGE_SPACE_RE = /\s/;
  //: קישור נפתח בלשונית חדשה, ולכן רק ``http``/``https``. כל סכימה אחרת
  //: — ``javascript:``, ``data:`` — מרונדרת כטקסט, לא כקישור.
  const MD_SAFE_LINK  = /^https?:\/\//i;
  //: בלוק מכולה: ``::: note`` ... ``:::``. **התחביר אינו שלנו** — הוא של
  //: ``markdown-it-container@4.0.0``, שמרנדר את אותם בלוקים בתצוגת המסמך
  //: ובתצוגה החיה, ולכן הוא הצרכן שהפתק צריך להסכים איתו. הכללים כאן
  //: נגזרו מ-``node_modules/markdown-it-container/index.mjs`` **והורצו
  //: מולו בפועל**, לא נזכרו:
  //:
  //:  - ``min_markers = 3`` — שלוש נקודתיים לפחות.
  //:  - ה"פרמטרים" הם כל מה שאחרי רצף הנקודתיים, ולכן ``:::note`` בלי
  //:    רווח תקף בדיוק כמו ``::: note``.
  //:  - הוולידציה בשני הצרכנים היא ``^<type>\b\s*(.*)$`` על הפרמטרים
  //:    אחרי ``trim``, ומכאן שלוש התנהגויות שנמדדו: ``::: note כותרת``
  //:    נותן כותרת מותאמת; ``::: note2`` ו-``::: note_x`` **אינם** מכולה,
  //:    כי אין גבול מילה בין אות לספרה או לקו תחתון; ``::: note.x`` כן,
  //:    עם הכותרת ``.x``. **הצורה הזו חלה גם על ``details``** — היא
  //:    הייתה שם החריג היחיד (``^details\s+``), ויושרה בשני הצרכנים
  //:    כחלק מהשינוי הזה, אחרת ``::: details.x`` היה מציג בפתק ``.x``
  //:    ובמסמך את תווית ברירת המחדל.
  //:  - שורת סגירה: רצף נקודתיים ואחריו רווחים בלבד. ``::: x`` אינו סוגר.
  //:
  //: **``[A-Za-z]+\b`` ולא ``\S+``.** הכמת החמדן בולע את כל האותיות, ולכן
  //: ``noteX`` נלכד כסוג שלם שאינו קיים במפת הסוגים ונדחה — בדיוק כמו
  //: שה-``\b`` של התוסף נכשל עליו. וה-``\b`` נשאר כאן דווקא בשביל
  //: ``note2``/``note_x``: שם התו הבא הוא תו-מילה, ובלעדיו הסוג היה נחתך
  //: ל-``note`` והשורה הייתה הופכת לאלרט שהתוסף דוחה.
  const MD_CONTAINER_OPEN_RE  = /^[ \t]*(:{3,})[ \t]*([A-Za-z]+)\b[ \t]*(.*)$/;
  const MD_CONTAINER_CLOSE_RE = /^[ \t]*(:{3,})[ \t]*$/;
  //: ``details`` הוא **סוג המכולה היחיד שאינו אלרט**: אין לו אייקון, אין
  //: לו מחלקת ``admonition-<type>``, והוא מרונדר כ-``<details>`` נייטיבי.
  //: הוא נשמר כקבוע ולא כמחרוזת באתר הבדיקה כדי שהשם יופיע פעם אחת בקובץ,
  //: ומטופל **לפני** מפת האלרטים — כך שגם אם ``details`` ייכנס אי-פעם
  //: ל-``ADMONITION_TITLES`` לא ייווצר כאן מסלול שני שקט.
  const MD_DETAILS_TYPE = 'details';

  // ----- המנוע -----
  //
  // **מחלקה, ולא אובייקט של פונקציות**, כדי שהמתודות יעברו לכאן כמו שהן — עם ``this`` שלהן — ויחוברו
  // למנהל של הפתק בלי שינוי (``mixInto``). ``_mdReadOnly`` הוא הדגל היחיד שמבדיל בין המצבים, והוא
  // ``undefined`` אצל המנהל, כלומר מצב עריכה.
  class StickyMdEngine {
    constructor(opts){
      this._mdReadOnly = !!(opts && opts.readOnly);
    }

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

      /**
       * מפרק שורה למערך קטעים. טהור — לא נוגע ב-DOM, ולכן נבדק ישירות.
       *
       * ``{type:'text'|'code', text}`` הם עלים. ``bold``/``italic``/``strike``/
       * ``mark`` ו-``link`` (שנושא גם ``href``) מחזיקים ``children`` — טקסט
       * וקוד בלבד, כי עיצוב בתוך עיצוב אינו נתמך (ההערה מעל
       * ``MD_CODE_TRIM_RE``).
       *
       * הסריקה עוברת על השורה פעם אחת, מתחילתה לסופה. בכל תו שיכול לפתוח
       * משהו: רצף גרשיים נבדק ראשון ונצרך כקטע קוד שלם, ואחרת מנסים את
       * העיצוב שמתחיל בתו הזה — ``**`` לפני ``*``. ניסיון שנכשל מתקדם בתו
       * אחד, ומה שנמצא נצרך כולו והסריקה ממשיכה אחריו.
       */
      _parseInline(text){
        const src = String(text == null ? '' : text);
        const state = this._inlineScanState(src);
        const out = [];
        let i = 0, last = 0;
        while (i < src.length){
          MD_INLINE_START_RE.lastIndex = i;
          const hit = MD_INLINE_START_RE.exec(src);
          if (!hit) break;
          i = hit.index;
          let found;
          if (src[i] === '`'){
            const code = this._inlineCodeAt(state, i);
            // רצף בלי סוגר באותו אורך הוא טקסט, והסריקה ממשיכה **אחריו** —
            // כמו ב-``backticks.mjs``, שמוסיף את הרצף כולו לטקסט ומתקדם.
            if (code.text === null){ i = code.end; continue; }
            found = { end: code.end, segs: [{ type: 'code', text: code.text }] };
          } else {
            found = this._matchInlineAt(state, i);
            if (!found){ i += 1; continue; }
          }
          if (i > last) out.push({ type: 'text', text: src.slice(last, i) });
          out.push(...found.segs);
          i = last = found.end;
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

      /**
       * מה שהסריקה של שורה אחת זוכרת: כל רצפי הגרשיים, ותשובות שכבר נמצאו.
       *
       * **לכל רצף — הרצף הבא שאורכו זהה בדיוק.** זה כל הכלל של
       * ``lib/rules_inline/backticks.mjs``: רצף של N גרשיים נסגר ברצף הבא של
       * N בדיוק, בכל מקום בהמשך השורה, ורצף ארוך או קצר יותר אינו סוגר.
       * markdown-it מחפש את הסוגר מחדש מכל פותח ומחזיק מטמון כדי לא לסרוק
       * פעמיים; כאן התשובה מחושבת פעם אחת לכל השורה, מהסוף להתחלה.
       *
       * ``firsts`` ו-``destStops`` הם הזיכרון שמחזיק את הסריקה לינארית —
       * ראו ``_firstOutsideCode`` ו-``_linkDestStop``. כל אחד מהם נבנה רק
       * כשמישהו שואל אותו.
       */
      _inlineScanState(src){
        const runs = new Map();
        const ordered = [];
        for (let i = src.indexOf('`'); i !== -1; i = src.indexOf('`', i)){
          const start = i;
          while (i < src.length && src.charCodeAt(i) === 0x60) i += 1;
          const run = { start, end: i, close: null };
          runs.set(start, run);
          ordered.push(run);
        }
        const nextOfLength = new Map();
        for (let k = ordered.length - 1; k >= 0; k -= 1){
          const run = ordered[k];
          const length = run.end - run.start;
          run.close = nextOfLength.get(length) || null;
          nextOfLength.set(length, run);
        }
        return { src, runs, firsts: new Map(), destStops: null };
      }

      /**
       * רצף הגרשיים שמתחיל ב-``pos``: ``{ end, text }`` לקטע קוד, או
       * ``{ end, text: null }`` כשאין לו סוגר — ואז הרצף הוא טקסט.
       *
       * **``pos`` הוא תמיד תחילת רצף**, ולא אמצע שלו: כל מי שמגיע לכאן מגיע
       * אחרי תו שאינו גרש — תחילת השורה, מפריד, או סוף של רצף או של קטע
       * קוד, ושניהם מסתיימים בתו שאינו גרש.
       *
       * רווח אחד בכל קצה של התוכן נחתך, כמו ב-``backticks.mjs``
       * (``MD_CODE_TRIM_RE``). שם גם ירידת שורה הופכת לרווח, כי פסקה שם היא
       * כמה שורות; כאן כל קריאה היא שורה אחת, ואין ירידת שורה להחליף.
       */
      _inlineCodeAt(state, pos){
        const run = state.runs.get(pos);
        if (!run.close) return { end: run.end, text: null };
        const text = state.src.slice(run.end, run.close.start).replace(MD_CODE_TRIM_RE, '$1');
        return { end: run.close.end, text };
      }

      // היכן נגמר מה שמתחיל ברצף הגרשיים ב-``pos`` — קטע קוד או רצף שהוא
      // טקסט. מי שרק מדלג על הקוד אינו צריך את התוכן, ולכן גם לא בונה אותו.
      _inlineCodeEnd(state, pos){
        const run = state.runs.get(pos);
        return run.close ? run.close.end : run.end;
      }

      /**
       * המיקום של ``ch`` הראשון מ-``from`` והלאה שאינו בתוך קטע קוד, או -1.
       *
       * **זו הנקודה שבה קוד גובר על כל מפריד.** קטע קוד שהסריקה פוגשת נצרך
       * כולו, ולכן ``*`` או ``]`` שבתוכו אינם יכולים לסגור דבר — וזה נכון גם
       * כשהקוד ממשיך מעבר למקום שבו העיצוב היה נסגר: ב-``**א `ב** ג`` אין
       * מודגש, יש קוד.
       *
       * **התשובה נזכרת לכל נקודה שהסריקה עברה בה**, וזה מה שמחזיק את
       * הפרסר לינארי. סריקה מנקודה שאינה בתוך קוד תלויה רק בנקודה עצמה,
       * ולכן כל סריקה שמגיעה לנקודה שכבר נסרקה לוקחת את התשובה משם. בלי
       * זה שורה של ``[`א` `` חוזרת על עצמה סרקה את כל ההמשך מכל ``[``.
       */
      _firstOutsideCode(state, from, ch){
        const src = state.src;
        let memo = state.firsts.get(ch);
        if (!memo){
          memo = new Int32Array(src.length).fill(-2);
          state.firsts.set(ch, memo);
        }
        const visited = [];
        let j = from, found = -1;
        while (j < src.length){
          if (memo[j] !== -2){ found = memo[j]; break; }
          visited.push(j);
          const c = src[j];
          if (c === ch){ found = j; break; }
          if (c === '`'){ j = this._inlineCodeEnd(state, j); continue; }
          j += 1;
        }
        for (const k of visited) memo[k] = found;
        return found;
      }

      /**
       * הסוגר של עיצוב שתוכנו מתחיל ב-``from``: ה-``ch`` הראשון מחוץ לקוד,
       * ובמפריד כפול (``**``, ``~~``, ``==``) גם התו שאחריו. תו המפריד אינו
       * יכול להופיע בתוכן עצמו, ולכן ``*`` בודד בתוך ``**...**`` פוסל את
       * המודגש במקום להיבלע בו.
       */
      _inlineCloser(state, from, ch, double){
        const j = this._firstOutsideCode(state, from, ch);
        if (j < 0) return -1;
        if (double && state.src[j + 1] !== ch) return -1;
        return j;
      }

      /**
       * סוף יעד הקישור: הסוגר הראשון או הרווח הראשון מ-``from``, או -1.
       * ביעד אין קוד — הוא נצרך כטקסט יחד עם הקישור, ולכן גרש בתוך כתובת
       * אינו פותח קטע. מחושב פעם אחת לכל השורה, מהסוף להתחלה, כדי שהרבה
       * סוגריים פותחים לא יסרקו כל אחד את אותו יעד.
       */
      _linkDestStop(state, from){
        if (!state.destStops){
          const src = state.src;
          const stops = new Int32Array(src.length + 1);
          stops[src.length] = -1;
          for (let k = src.length - 1; k >= 0; k -= 1){
            stops[k] = MD_LINK_DEST_STOP_RE.test(src[k]) ? k : stops[k + 1];
          }
          state.destStops = stops;
        }
        return state.destStops[from];
      }

      /**
       * התוכן שבין ``from`` ל-``to`` כקטעי טקסט וקוד. הגבולות מגיעים תמיד
       * מ-``_inlineCloser``, ולכן אף קטע קוד אינו חוצה את ``to``.
       */
      _inlineTextAndCode(state, from, to){
        const src = state.src;
        const out = [];
        let last = from;
        for (let j = src.indexOf('`', from); j !== -1 && j < to; ){
          const code = this._inlineCodeAt(state, j);
          if (code.text !== null){
            if (j > last) out.push({ type: 'text', text: src.slice(last, j) });
            out.push({ type: 'code', text: code.text });
            last = code.end;
          }
          j = src.indexOf('`', code.end);
        }
        if (last < to) out.push({ type: 'text', text: src.slice(last, to) });
        return out;
      }

      /** העיצוב שמתחיל ב-``i``, או ``null``. ``**`` נבדק לפני ``*``. */
      _matchInlineAt(state, i){
        const c = state.src[i];
        if (c === '[') return this._matchInlineLink(state, i);
        if (c === '*') return this._matchInlinePair(state, i, '**', 'bold') || this._matchInlinePair(state, i, '*', 'italic');
        if (c === '~') return this._matchInlinePair(state, i, '~~', 'strike');
        if (c === '=') return this._matchInlineMark(state, i);
        return null;
      }

      /**
       * ``open`` + תוכן לא ריק + ``open``, כשהתוכן הוא טקסט וקוד. ``accept``
       * הוא תנאי נוסף על גבולות התוכן, אם יש; הילדים נבנים רק אחרי שהכול
       * עבר, כי ניסיון שנכשל אינו צריך אותם.
       */
      _matchInlinePair(state, i, open, type, accept){
        if (!state.src.startsWith(open, i)) return null;
        const from = i + open.length;
        const close = this._inlineCloser(state, from, open[0], open.length === 2);
        if (close <= from) return null;
        if (accept && !accept(from, close)) return null;
        return { end: close + open.length, segs: [{ type, children: this._inlineTextAndCode(state, from, close) }] };
      }

      /**
       * ``==מרקר==``. מעבר לכלל של כל זוג, **התו הצמוד למפריד אינו רווח** —
       * בשני הקצוות. בלי זה ``a == b == c``, שרשור השוואות נפוץ בפייתון, היה
       * מזהה את ``" b "`` כמרקר וצובע אותו; הדרישה מבטלת את כל המשפחה:
       * ``1 == 1 == True``, ``if x == y == z:``.
       *
       * **ו-``=`` אינו יכול להופיע בתוכן**, כי הסוגר הוא ה-``=`` הראשון אחרי
       * הפותח. זה מה ששומר על **שורת מפריד של סימני שווה**: פעם ``=====``
       * התפרק ל-``==`` ‏+ ``=`` ‏+ ``==`` וצבע תו אחד ורוד, ו-``==========``
       * צבע שניים — מפריד ASCII הוא שימוש רגיל בפתק.
       *
       * מה ש**כן** נתפס ובכוונה: ``a==b==c`` בלי רווחים, בדיוק כמו ש-``~~``
       * מתנהג — ולזה הפתרון הוא גרשיים, שגוברים על כל מפריד.
       */
      _matchInlineMark(state, i){
        const src = state.src;
        return this._matchInlinePair(state, i, '==', 'mark', (from, close) =>
          !MD_MARK_EDGE_SPACE_RE.test(src[from]) && !MD_MARK_EDGE_SPACE_RE.test(src[close - 1]));
      }

      /**
       * ``[תווית](כתובת)``. התווית יכולה להכיל קוד, ו-``]`` שבתוך קוד אינו
       * סוגר אותה — ``parseLinkLabel`` של markdown-it מדלג על קוד באותה צורה.
       * היעד הוא רצף בלי רווחים עד ה-``)`` הראשון.
       *
       * **כתובת שאינה ``http``/``https`` אינה קישור** (``MD_SAFE_LINK``), והיא
       * מוצגת כמו שהוקלדה — אבל הקוד שבתווית שלה מוצג כקוד, כמו בכל מקום
       * אחר בשורה. כך ``[`app.py`](./app.py)`` אינו מסתיר את הקוד.
       */
      _matchInlineLink(state, i){
        const src = state.src;
        const close = this._inlineCloser(state, i + 1, ']', false);
        if (close < 0 || src[close + 1] !== '(') return null;
        const destStart = close + 2;
        const stop = this._linkDestStop(state, destStart);
        if (stop <= destStart || src[stop] !== ')') return null;
        const href = src.slice(destStart, stop);
        const end = stop + 1;
        const label = this._inlineTextAndCode(state, i + 1, close);
        if (MD_SAFE_LINK.test(href)){
          // תווית ריקה מציגה את הכתובת — אחרת הקישור היה בלתי נראה.
          return { end, segs: [{ type: 'link', href, children: label.length ? label : [{ type: 'text', text: href }] }] };
        }
        return { end, segs: [{ type: 'text', text: '[' }, ...label, { type: 'text', text: src.slice(close, end) }] };
      }

      // מסווג בלוק לשורה בודדת. קוד רב-שורי מטופל בלולאה, לא כאן.
      //
      // **שורת רשימה מחזירה גם את הסמן ואת הרווחים שאחריו**, ולא רק את
      // התוכן — מהם נגזרת עמודת התוכן, וממנה עומק הקינון. הערכים מוחזרים
      // **בשדות בשם** ולא נקראים כקבוצות רג'קס אצל הקורא: זו בדיוק
      // המלכודת שנשכה ב-``MD_INLINE_RE``, הרג'קס שקרא פעם את המארקדאון
      // בשורה — הוספת חלופה באמצע הייתה מזיזה בשקט את כל אינדקסי הקבוצות
      // שאחריה.
      //
      // **ההזחה עצמה אינה מוחזרת מכאן בכוונה.** היא נענית ב-
      // ``_lineIndentCols`` על השורה הגולמית, כי גם שורת גדר צריכה אותה
      // והיא לעולם אינה מגיעה לכאן. שני יצרנים לאותו ערך היו יכולים
      // להיסחף זה מזה בשקט.
      _classifyLine(line){
        let m;
        if ((m = MD_HEADING_RE.exec(line))) return { kind: 'heading', level: m[1].length, content: m[2] };
        if ((m = MD_QUOTE_RE.exec(line)))   return { kind: 'quote', content: m[1] };
        if (MD_HR_RE.test(line))            return { kind: 'hr', content: '' };
        if ((m = MD_OL_RE.exec(line)))      return { kind: 'ol', content: m[4], marker: m[2] + '.', markerChars: m[2].length + 1, spaceRun: m[3] };
        if ((m = MD_UL_RE.exec(line)))      return { kind: 'ul', content: m[4], markerChars: 1, spaceRun: m[3] };
        return { kind: 'plain', content: line };
      }

      /**
       * רוחב הזחה בעמודות, כשטאב מתקדם לעמודה הבאה שמתחלקת ב-4.
       *
       * ``startCol`` היא העמודה שממנה מודדים. היא נדרשת כי הרווחים
       * שאחרי הסמן אינם מתחילים בעמודה 0, ומיקום הטאב בתוך השורה הוא
       * שקובע לכמה עמודות הוא שווה.
       *
       * מקור: ``markdown-it@14.1.0``, ``lib/rules_block/state_block.mjs``
       * — ``if (ch === 0x09) { offset += 4 - offset % 4 }``.
       */
      _indentCols(ws, startCol){
        let col = Number.isFinite(startCol) ? startCol : 0;
        const src = String(ws == null ? '' : ws);
        for (let i = 0; i < src.length; i += 1){
          if (src[i] === '\t') col += MD_TAB_STOP - (col % MD_TAB_STOP);
          else col += 1;
        }
        return col;
      }

      /**
       * ההזחה של שורה גולמית, בעמודות. **התשובה היחידה בקוד לשאלה הזו.**
       *
       * שורת רשימה, כותרת, ציטוט, טבלה ושורת גדר — כולן נמדדות כאן, ולכן
       * אין שתי הגדרות של "רווח מוביל" שיכולות להיסחף זו מזו.
       */
      _lineIndentCols(line){
        return this._indentCols(MD_INDENT_RE.exec(String(line == null ? '' : line))[0]);
      }

      /**
       * סוגר את כל הפריטים הפתוחים שההזחה הזו כבר אינה נמצאת בתוכם.
       *
       * **זו כל התשובה לשאלה "מה גבול בלוק עושה לרשימה".** שורה נשארת
       * בתוך פריט כל עוד ההזחה שלה מגיעה לעמודת התוכן שלו, ולכן בלוק
       * שמוזח לתוך הפריט אינו סוגר אותו ובלוק בעמודה 0 סוגר את כולם.
       * מקור: ``markdown-it@14.1.0``, ``lib/rules_block/list.mjs`` —
       * ``if (state.sCount[nextLine] < state.blkIndent) { break }``.
       *
       * הגרסה הקודמת הפרידה בין השניים: שורת רשימה סגרה לפי הזחה, וכל
       * בלוק אחר עשה ``listStack.length = 0`` — איפוס גורף שהתעלם
       * מההזחה של עצמו, בעוד שורת גדר לא נגעה במחסנית כלל. שתי
       * ההתנהגויות היו שגויות בכיוונים הפוכים: גדר בעמודה 0 השאירה
       * רשימה פתוחה, וכותרת מוזחת בתוך פריט סגרה אותו. שאלה אחת,
       * מקום אחד.
       */
      _closeListsAbove(stack, indentCols){
        while (stack.length && indentCols < stack[stack.length - 1]) stack.pop();
      }

      /**
       * עמודת התוכן של פריט רשימה — העמודה שבה מתחיל הטקסט שלו, ולכן גם
       * ההזחה שממנה ואילך שורה נחשבת **בתוך** הפריט.
       *
       * **רווחים שמעבר לארבעה נספרים כאחד.** בתקן הם בלוק קוד מוזח בתוך
       * הפריט, לא הזחה עמוקה יותר, ולכן ``-␣␣␣␣␣␣טקסט`` אינו פותח רמה.
       * מקור: ``markdown-it@14.1.0``, ``lib/rules_block/list.mjs`` —
       * ``if (indentAfterMarker > 4) { indentAfterMarker = 1 }`` ואז
       * ``const indent = initial + indentAfterMarker``.
       */
      _listContentCol(line, block){
        const afterMarker = this._lineIndentCols(line) + (block.markerChars || 0);
        const spaceCols = this._indentCols(block.spaceRun, afterMarker) - afterMarker;
        return afterMarker + (spaceCols > 4 ? 1 : spaceCols);
      }

      /**
       * עומק הקינון של שורת רשימה, ועדכון המחסנית עבור השורות הבאות.
       *
       * המחסנית מחזיקה את עמודות התוכן של הפריטים הפתוחים. שורה נשארת
       * **בתוך** פריט כל עוד ההזחה שלה מגיעה לעמודת התוכן שלו; אחרת
       * הפריט נסגר. מקור: ``markdown-it@14.1.0``,
       * ``lib/rules_block/list.mjs`` —
       * ``if (state.sCount[nextLine] < state.blkIndent) { break }``.
       *
       * זה מה שמבדיל בין "עמודת התוכן קובעת" לבין "כל הזחה = רמה":
       * ``- א`` ואחריו ``␣- ב`` (רווח אחד) הם **אחים**, כי רווח אחד אינו
       * מגיע לעמודה 2 שבה מתחיל הטקסט של הפריט הראשון. נמדד מול
       * ``markdown-it``, לא הונח.
       */
      _listDepth(stack, line, block){
        this._closeListsAbove(stack, this._lineIndentCols(line));
        const depth = stack.length;
        stack.push(this._listContentCol(line, block));
        return depth;
      }

      // האם יש מארקדאון שכדאי לרנדר — כדי לא להפוך פתק טקסט רגיל לתצוגה.
      //
      // **התשובה נגזרת מהפרסר עצמו**: יש מה לרנדר אם הוא החזיר משהו שאינו
      // טקסט. סורק שני היה יכול לחלוק עליו — לפתוח תצוגה לשורה שהפרסר
      // מציג כטקסט, או להשאיר כתיבה גולמית לשורה שיש בה קוד. קישור פסול
      // הוא טקסט, ולכן ``[x](javascript:y)`` לבדו אינו פותח את התצוגה, ו-
      // ``[x](javascript:y) **מ**`` כן — בזכות המודגש.
      _lineHasInline(content){
        return this._parseInline(content).some((seg) => seg.type !== 'text');
      }
      /**
       * סורק שורת טבלה ומחזיר ``{ cells, delimiters }``.
       *
       * **סריקה אחת מודעת-escape, ואז השמטת התאים הריקים שבקצוות** —
       * המקף האנכי המוביל והסוגר אופציונליים ב-GFM ומייצרים תא ריק בקצה.
       * אין כאן שלב שמסיר תו לפני שידוע אם הוא מוברח: גרסה קודמת חתכה
       * את המקף הסוגר ב-``replace`` לפני הסריקה, ולכן ``| a | b\\|`` איבד
       * את המקף המוברח והציג לוכסן מיותר.
       *
       * ``delimiters`` הוא הסיבה שהפונקציה מחזירה אובייקט ולא מערך:
       * ``| רק תא אחד |`` ו-``טקסט רגיל`` נותנים שניהם תא אחד, ורק ספירת
       * המפרידים מבדילה ביניהם. **זהו המקום היחיד בקוד שיודע מהו מפריד**,
       * ולכן גם השאלה "האם זו שורת טבלה" נענית מכאן.
       */
      _scanTableRow(line){
        const trimmed = String(line).trim();
        let delimiters = 0;
        const cells = [];
        let cur = '';
        let leadingDelim = false;
        let trailingDelim = false;
        for (let i = 0; i < trimmed.length; i += 1){
          const ch = trimmed[i];
          if (ch === '\\' && trimmed[i + 1] === '|'){ cur += '|'; i += 1; continue; }
          if (ch === '|'){
            delimiters += 1;
            if (cells.length === 0 && cur.trim() === '') leadingDelim = true;
            if (i === trimmed.length - 1) trailingDelim = true;
            cells.push(cur.trim());
            cur = '';
            continue;
          }
          cur += ch;
        }
        cells.push(cur.trim());
        if (trailingDelim && cells[cells.length - 1] === '') cells.pop();
        if (leadingDelim && cells[0] === '') cells.shift();
        return { cells, delimiters };
      }

      /** התאים בלבד — העטיפה הדקה שרוב הקוראים צריכים. */
      _splitTableRow(line){
        return this._scanTableRow(line).cells;
      }

      /**
       * מחזיר את היישורים אם השורות מרכיבות טבלה, ואחרת ``null``.
       *
       * **מספר התאים חייב להתאים בין הכותרת למפריד** — זה הכלל ב-GFM, והוא
       * גם מה שמונע מ-``---`` בודד שאחרי שורה עם מקף אנכי להפוך אותה לטבלה.
       */
      _tableSpec(headerLine, sepLine){
        if (!MD_TABLE_SEP_RE.test(sepLine)) return null;
        const head = this._splitTableRow(headerLine);
        const sep = this._splitTableRow(sepLine);
        // **הזיהוי נגזר מהמפצל ולא מרג'קס נפרד.** קודם היה כאן
        // ``MD_TABLE_ROW_RE`` שספר פייפים גולמיים, בעוד המפצל מודע
        // ל-escape — שני חלקים שחלוקים על מהו מפריד, וזה הפיל שלושה
        // מקרים: פייפ בורח, פייפ סוגר בלבד, ופייפ בתוך גדר.
        //
        // **שתי עמודות לפחות, בסטייה מכוונת מ-GFM.** לפי התקן ``grep foo |``
        // ואחריו ``---`` היא טבלה חוקית של עמודה אחת. בפתק זה כמעט תמיד
        // פקודה שאחריה קו מפריד, ולכן דורשים פייפ פנימי. המחיר — טבלת
        // עמודה אחת אמיתית תרונדר כטקסט — קטן בהרבה מהרווח.
        if (head.length < 2) return null;
        if (head.length !== sep.length) return null;
        const align = sep.map((c) => {
          const l = c.startsWith(':'), r = c.endsWith(':');
          if (l && r) return 'center';
          if (r) return 'right';
          if (l) return 'left';
          return '';
        });
        return { head, align };
      }

      /**
       * בונה ``<table>`` מתוך שורות המקור, ומחזיר את האינדקס האחרון שנצרך
       * ואת ההיסט להמשך.
       *
       * **כל שורת מקור של הטבלה הופכת ל-``<tr class="sticky-task-line">``
       * עם ה-``charOffset`` שלה.** זה מה ששומר על החוזה של המנוע כולו:
       * ``_enterEditFromView`` מוצא את השורה שנלחצה דרך
       * ``closest('.sticky-task-line')`` וקורא ממנה את ההיסט, ולכן לחיצה על
       * תא מחזירה לעריכה בשורה הנכונה ולא בראש הטבלה.
       *
       * שורת המפריד נצרכת ואינה מייצרת ``<tr>`` — אין לה מה להציג. ההיסט
       * מקודם עליה בכל מקרה, אחרת כל מה שאחרי הטבלה מוסט.
       */
      _appendTable(view, lines, startIndex, spec, startOffset){
        const wrap = createEl('div', 'sticky-md-table-wrap');
        const table = createEl('table', 'sticky-md-table');
        const thead = createEl('thead', '');
        const tbody = createEl('tbody', '');
        let offset = startOffset;

        const addRow = (parent, cells, isHead, lineText) => {
          const tr = createEl('tr', 'sticky-task-line');
          this._setSourceOffset(tr, offset);
          spec.align.forEach((al, ci) => {
            const cell = createEl(isHead ? 'th' : 'td', 'sticky-md-cell');
            if (isHead) cell.setAttribute('scope', 'col');
            // **``dir="auto"`` ולא זיהוי-תוכן משלנו.** הפתקים עבריים,
            // והטבלאות מערבבות עברית עם מספרים ומזהי קוד כמו
            // ``push_api.py:569``. הדפדפן מכריע לפי התו החזק הראשון
            // (אלגוריתם ה-bidi), ולכן תא עברי נשאר RTL ותא של קוד או
            // מספר מוצג LTR — בלי היוריסטיקה שלנו שתטעה במקרה הקצה הבא.
            cell.setAttribute('dir', 'auto');
            if (al) cell.style.textAlign = al;
            this._appendInline(cell, cells[ci] == null ? '' : cells[ci]);
            tr.appendChild(cell);
          });
          parent.appendChild(tr);
          offset += lineText.length + 1;
        };

        addRow(thead, spec.head, true, lines[startIndex]);
        // המפריד: נצרך, בלי שורה משלו.
        offset += lines[startIndex + 1].length + 1;

        let i = startIndex + 2;
        for (; i < lines.length; i += 1){
          const row = lines[i];
          // **שורת גוף נמדדת במפריד, לא במספר התאים.** ב-GFM שורת גוף
          // רשאית להכיל פחות תאים מהכותרת, והחסרים ריקים — ``addRow`` כבר
          // מרפד לפי ``spec.align``. דרישת שני תאים גם כאן הייתה מסיימת
          // את הטבלה על ``| רק תא אחד |`` ועל תא שמכיל מקף מוברח.
          //
          // דרישת שתי העמודות חלה על הכותרת בלבד, ושם היא מונעת זיהוי
          // שגוי; כאן ההקשר כבר נקבע, ולכן שורה עם מפריד היא שורת טבלה.
          const scan = this._scanTableRow(row);
          if (row.trim() === '' || scan.delimiters === 0) break;
          addRow(tbody, scan.cells, false, row);
        }

        table.appendChild(thead);
        table.appendChild(tbody);
        wrap.appendChild(table);
        view.appendChild(wrap);

        // **ספירת שורות המשימה שנצרכו.** הפייפ הסוגר אופציונלי, ולכן
        // ``- [ ] משימה | עמודה`` היא גם שורת משימה תקפה וגם כותרת טבלה
        // תקפה. השרת (``sticky_notes_tasks``) סופר אותה בכל מקרה, ולכן
        // גם הסידור כאן חייב להתקדם עליה — אחרת כל צ'קבוקס שאחרי הטבלה
        // נשלח עם אינדקס של משימה אחרת. זו בדיוק אותה החלטה שכבר מתועדת
        // עבור שורות משימה בתוך גדר קוד.
        let tasksConsumed = 0;
        for (let k = startIndex; k <= i - 1; k += 1){
          if (TASK_LINE_RE.test(lines[k])) tasksConsumed += 1;
        }
        return { lastIndex: i - 1, nextOffset: offset, tasksConsumed };
      }

      /**
       * מזהה שורת פתיחה של מכולה, ומחזיר ``{ markers, type, title }`` או
       * ``null``.
       *
       * **רשימת הסוגים המוכרים אינה חיה כאן.** היא ``ADMONITION_TITLES``
       * ב-``admonition-icons.js``, המקום היחיד בפרויקט שמגדיר מהו סוג
       * אלרט — אותו מקום שממנו קוראים גם תצוגת המסמך וגם התצוגה החיה.
       * סוג שאינו שם נשאר טקסט רגיל, וזו בדיוק ההתנהגות של
       * ``markdown-it-container`` על סוג שלא נרשם: נמדד, ``::: foo``
       * מרונדר כפסקה ולא כמכולה.
       *
       * ``details`` הוא היוצא מן הכלל, ו**אותו כלל בדיוק חל עליו**: הוא
       * אינו אלרט ולכן אינו במפה, אבל תווית ברירת המחדל שלו מגיעה מאותו
       * קובץ — ``DETAILS_DEFAULT_TITLE``. כשהיא חסרה (הקובץ לא נטען
       * בעמוד) השורה נשארת טקסט, בדיוק כמו סוג שאינו במפה; זו אינה
       * נפילה-לאחור למסלול גרוע אלא היעדר יכולת סטטי, ויש בדיקת חיווט
       * שמוודאת שכל תבנית טוענת את הקובץ לפני המודול.
       *
       * ``hasOwnProperty`` ולא ``titles[type]``: שם הסוג מגיע מטקסט
       * שהמשתמש הקליד, ולכן הוא **קלט חיצוני**. בלי הבדיקה הזו
       * ``::: constructor`` היה מוצא פונקציה על הפרוטוטיפ ונחשב סוג תקף.
       * מאותה סיבה גם הערך עצמו נבדק כמחרוזת לפני שהוא מוצג.
       */
      _containerSpec(line){
        const m = MD_CONTAINER_OPEN_RE.exec(line);
        if (!m) return null;
        const type = m[2].toLowerCase();
        const custom = (m[3] || '').trim();
        // ``generatedTitle``: הכותרת היא ברירת המחדל של המנוע ולא טקסט
        // שהמשתמש כתב — ראו ``_markGenerated``.
        if (type === MD_DETAILS_TYPE){
          const fallback = window.DETAILS_DEFAULT_TITLE;
          if (typeof fallback !== 'string' || !fallback) return null;
          return { markers: m[1].length, type, title: custom || fallback, generatedTitle: !custom };
        }
        const titles = window.ADMONITION_TITLES;
        if (!titles || !Object.prototype.hasOwnProperty.call(titles, type)) return null;
        const fallback = typeof titles[type] === 'string' ? titles[type] : type;
        return { markers: m[1].length, type, title: custom || fallback, generatedTitle: !custom };
      }

      /**
       * מסמן צומת שכל הטקסט בו **מיוצר על ידי המנוע** ואינו כתוב בפתק.
       *
       * למשל: התבליט של רשימה לא ממוספרת (המשתמש כתב ``-``, והמסך מציג
       * ``•``), תווית ברירת המחדל של אלרט, וכותרת ברירת המחדל של
       * ``::: details`` — כל קורא של הפונקציה הזו הוא מקרה כזה. החיפוש
       * בתוך הפתק מדלג על הצמתים האלה: חיפוש
       * "הערה" שמוצא מילה שלא כתובה בפתק מבלבל, והוא גם חוסר עקביות מול
       * חיפוש הפתקים בשרת, שמחפש במקור.
       *
       * **מה שנגזר מילה במילה מהמקור אינו מסומן:** כותרת מותאמת של אלרט
       * או של ``details``, תווית השפה של בלוק קוד (המילה הראשונה אחרי
       * הגדר), והמספר שהוקלד ברשימה ממוספרת — כל אלה כתובים בפתק.
       */
      _markGenerated(node){
        node.classList.add(GENERATED_TEXT_CLASS);
      }

      /** אורך המרקר אם השורה היא שורת סגירה של מכולה, ו-0 אחרת. */
      _containerCloseMarkers(line){
        const m = MD_CONTAINER_CLOSE_RE.exec(line);
        return m ? m[1].length : 0;
      }

      /**
       * סוגר מכולות לפי שורת סגירה באורך ``markers``, ומחזיר האם השורה
       * אכן שימשה כסגירה.
       *
       * **הכלל אינו יודע דבר על הסוג, ובכוונה.** ``markdown-it-container``
       * סוגר לפי אורך המרקר בלבד, ולכן ``::: details`` בתוך אלרט, אלרט
       * בתוך ``::: details`` ושני סדרי סגירה — כולם עוברים כאן ללא ענף
       * נוסף. נמדד מול התוסף על ארבעת הצירופים.
       *
       * **הכלל: נסגר החיצוני ביותר שאורכו קטן-או-שווה, ואיתו כל מה
       * שבתוכו.** זה אינו "סוגר את הפנימי", וההבדל נראה רק בקינון: ב-
       * ``markdown-it`` כל מכולה סורקת קדימה אחר שורת סגירה **משלה**,
       * והמכולות שבתוכה נסגרות אוטומטית בסוף ההורה. נמדד על שלוש רמות —
       * ``::::: note`` ‏/ ``:::: tip`` ‏/ ``::: info`` — ושם ``::::`` סוגר
       * את ``info`` ואת ``tip`` ומשאיר את ``note`` פתוח.
       *
       * שורה שאין מעליה אף מכולה שאורכה מתאים **אינה סגירה כלל** ונשארת
       * תוכן. גם זה נמדד: ``:::: note`` שנסגר ב-``:::`` מציג את ``:::``
       * כטקסט בתוך האלרט, והאלרט נסגר בסוף הפתק.
       */
      _closeContainersAt(stack, markers){
        for (let i = 0; i < stack.length; i += 1){
          if (stack[i].markers <= markers){ stack.length = i; return true; }
        }
        return false;
      }

      /**
       * האייקון של הסוג, מתוך ``ADMONITION_ICONS`` המשותף.
       *
       * **זה המקום היחיד בקובץ שנוגע ב-``innerHTML``, וזו החלטה ולא
       * הרגל.** הכלל בפתקים הוא על **הקלט ולא על ה-API** (ראו
       * ``docs/dev/sticky_notes_extending_markdown.rst``): טקסט לא-מהימן אסור בכל
       * דרך, ותבנית סטטית לחלוטין מותרת. המחרוזת כאן היא קבוע כתוב בקוד,
       * היא נכנסת ל-``span`` ייעודי שלעולם אינו מקבל טקסט של משתמש, ולכן
       * אין מסלול שמחבר בין השניים. אותו דפוס בדיוק כבר קיים ב-
       * ``setTitleWithIcon`` שבתצוגת המסמך.
       *
       * **בדיקת הטיפוס אינה קישוט.** ``ADMONITION_ICONS`` הוא גלובל
       * שנטען מקובץ נפרד; ערך שאינו מחרוזת היה נכתב כ-``[object Object]``.
       * חוסר בגלובל כולו פירושו שהקובץ לא נטען בעמוד — האלרט עדיין
       * מוצג, בלי אייקון, ויש טסט חיווט שמוודא שזה לא קורה.
       */
      _appendAlertIcon(host, type){
        const icons = window.ADMONITION_ICONS;
        const svg = icons ? icons[type] : null;
        if (typeof svg !== 'string' || !svg) return;
        const slot = createEl('span', 'sticky-md-alert-icon');
        slot.innerHTML = svg;
        host.appendChild(slot);
      }

      /**
       * בונה את מעטפת המכולה ומחזיר את רשומת המחסנית.
       *
       * **כאן, ורק כאן, יש ענף רינדור שני — ו``details`` הוא כל הסיבה
       * לו.** כל שאר סוגי המכולה הם אותו ``div`` עם מחלקה אחרת, ולכן עד
       * היום הקובץ כולו נבנה סביב משתנה אחד בלולאה: **לאן שורה נכתבת**.
       * ‏``details`` דורש ``<details>`` ו-``<summary>`` נייטיביים —
       * מקלדת, נגישות והדפסה מגיעים איתם בחינם, ומנגנון קיפול משלנו היה
       * מכונת מצב שנייה שנלחמת בקיפול של הפתק עצמו.
       *
       * **הענף מסתיים כאן.** שתי הצורות מחזירות את אותה רשומה בדיוק
       * (``{ markers, content }``), ולכן ``_closeContainersAt``, מחסנית
       * הרשימות, ההיסטים והצ'קבוקסים אינם יודעים שהוא קיים. מי שיוסיף
       * סוג נוסף לא צריך ענף — אלא אם הוא, כמו זה, חייב אלמנט HTML אחר.
       *
       * **המחלקות הן של רינדור המסמכים** — ``admonition``,
       * ``admonition-title``, ``admonition-content`` — ולא סט חדש. הן
       * מוגדרות ב-``markdown-enhanced.css``, שנטען ב-``base.html`` ולכן
       * זמין בכל שלושת המשטחים שמציגים פתקים (לוח, קובץ Markdown, דפדפן
       * הריפו). פלטה שנייה עם אותם צבעים הייתה נסחפת מהראשונה בדיוק כמו
       * שתי מחלקות עם אותם כללים.
       *
       * **שורת הפתיחה היא שורת הכותרת.** היא נושאת ``sticky-task-line``
       * ואת ההיסט שלה, ולכן החוזה של המנוע נשמר: כל שורת מקור היא אלמנט
       * תצוגה אחד, ולחיצה על הכותרת מחזירה לעריכה בשורת ``::: note``
       * עצמה.
       */
      _openContainer(parent, spec, charOffset, startOpen){
        if (spec.type === MD_DETAILS_TYPE){
          // **המחלקות הן של רינדור המסמכים**, בדיוק כמו אצל האלרט:
          // ``markdown-details``, ``markdown-summary`` ו-``details-content``
          // מוגדרות ב-``markdown-enhanced.css`` שנטען ב-``base.html``,
          // ולכן הבלוק בפתק נראה כמו הבלוק בתצוגת המסמך — אותו קוד.
          const box = createEl('details', 'markdown-details sticky-md-details');
          // **שורת הפתיחה היא ה-``summary``, והיא נושאת את ההיסט.** ההיסט
          // אינו קיים בשביל הקליק — הקליק כאן מקפל בלבד — אלא בשביל
          // המיפוי בין תצוגה למקור: החוזה הוא ששורת מקור אחת היא אלמנט
          // תצוגה אחד שנושא את ההיסט שלה. הסרתו יחד עם מאזין העריכה
          // הייתה מסיטה כל שורה שאחרי הבלוק.
          const summary = createEl('summary', 'markdown-summary sticky-task-line sticky-md-details-summary');
          this._setSourceOffset(summary, charOffset);
          // ``textContent`` ישירות ובלי צומת עוטף: אין כאן אייקון, ולכן
          // אין בכלל מסלול שמחבר טקסט של משתמש למחרוזת HTML. זה גם למה
          // אין כאן את ה-``span`` שהאלרט צריך.
          summary.textContent = spec.title;
          if (spec.generatedTitle) this._markGenerated(summary);
          const content = createEl('div', 'details-content');
          // **מצב הפתיחה שורד רינדור מחדש.** ההכרעה עצמה נעשית בקורא,
          // שהוא היחיד שמחזיק את מונה הבלוקים; כאן רק מחילים אותה. בלי זה
          // בלוק שנפתח היה נסגר תחת האצבע ברגע שמסמנים משימה שבתוכו, וגם
          // בכל כניסה ויציאה מעריכה.
          if (startOpen) box.open = true;
          box.appendChild(summary);
          box.appendChild(content);
          parent.appendChild(box);
          return { markers: spec.markers, content };
        }
        const box = createEl('div', 'admonition admonition-' + spec.type + ' sticky-md-alert');
        const title = createEl('div', 'admonition-title sticky-task-line');
        this._setSourceOffset(title, charOffset);
        this._appendAlertIcon(title, spec.type);
        // **הכותרת בצומת נפרד משלה, ותמיד דרך ``textContent``.** כותרת
        // מותאמת היא טקסט שהמשתמש הקליד; ההפרדה המבנית הזו היא מה שמוודא
        // שאין מסלול קוד שמחבר אותה למחרוזת HTML.
        const label = createEl('span', 'sticky-md-alert-label');
        label.textContent = spec.title;
        if (spec.generatedTitle) this._markGenerated(label);
        title.appendChild(label);
        const content = createEl('div', 'admonition-content');
        box.appendChild(title);
        box.appendChild(content);
        parent.appendChild(box);
        return { markers: spec.markers, content };
      }

      /**
       * בונה בלוק קוד מתוך שורות המקור, ומחזיר את האינדקס האחרון שנצרך,
       * את ההיסט להמשך, ואת מספר שורות המשימה שנצרכו.
       *
       * **החתימה זהה ל-``_appendTable`` בכוונה.** שני הבלוקים עונים על
       * אותה שאלה — "כמה שורות בלעתי ומה ההיסט אחריהן" — ושתי תשובות
       * בצורות שונות היו מזמינות אתר קריאה שמטפל באחת ושוכח את השנייה.
       *
       * **מה השתנה מול הגרסה הקודמת, ולמה זה לא סתם קוסמטיקה:** קודם
       * הגדר רונדרה שורה-שורה בתוך הלולאה, מאחורי הדגלים ``inFence``
       * ו-``isFenceLine``. הדגלים האלה חייבו שלושה סייגים נפרדים במקומות
       * מרוחקים בלולאה (חישוב מוקדם של ``isFenceLine``, ההבחנה בין
       * ``!inFence`` ל-``!inCode``, והחרגת שורת הסגירה) — כל אחד מהם
       * נכון, וכל אחד מהם דבר שאפשר לשכוח. עם צריכה בבת אחת **הלולאה
       * לעולם אינה נמצאת בתוך גדר**, ושלושת הסייגים נמחקים.
       *
       * **חלוקת התפקידים בין שלוש השורות:**
       *
       *  - **שורת הפתיחה היא הכותרת.** היא נושאת ``sticky-task-line``
       *    ואת ההיסט שלה, ולכן לחיצה עליה מחזירה לעריכה בשורת הגדר
       *    עצמה. בלי זה בלוק ריק (גדר ומיד גדר) היה יוצא בלי שום שורה
       *    לחיצה — מבוי סתום שאין ממנו דרך חזרה לעריכה.
       *  - **שורות התוכן** נשארות שורות תצוגה רגילות, כל אחת עם ההיסט
       *    שלה, בדיוק כמו קודם.
       *  - **שורת הסגירה נצרכת בלי אלמנט** — אין לה מה להציג — וההיסט
       *    מקודם עליה. זהו החריג היחיד כאן, והוא בדיוק זה של שורת
       *    המפריד בטבלה ושל שורת ה-``:::`` באלרט.
       *
       * ``lang`` נלקח משורת הפתיחה. בלי התווית הזו המידע היה נעלם עם
       * הגדר, וזו הייתה איבוד ולא הסתרה.
       */
      _appendCodeBlock(view, lines, startIndex, startOffset){
        const openLine = lines[startIndex];
        // מה שאחרי הגדר בשורת הפתיחה. ``markdown-it`` קורא לזה ``info``,
        // ולוקח ממנו את המילה הראשונה כשם השפה.
        const info = String(openLine).replace(MD_FENCE_RE, '').trim();
        const lang = info.split(/\s+/)[0] || '';

        const box = createEl('div', 'sticky-md-code-block');
        const head = createEl('div', 'sticky-md-code-head sticky-task-line');
        this._setSourceOffset(head, startOffset);
        const langEl = createEl('span', 'sticky-md-code-lang');
        // ``textContent`` ולא ``innerHTML``: שם השפה הוא טקסט שהמשתמש
        // הקליד אחרי הגדר, ולכן קלט לכל דבר.
        langEl.textContent = lang;
        head.appendChild(langEl);
        const body = createEl('div', 'sticky-md-code-body');

        let offset = startOffset + openLine.length + 1;
        let i = startIndex + 1;
        const codeLines = [];
        for (; i < lines.length; i += 1){
          const raw = lines[i];
          if (MD_FENCE_RE.test(raw)) break;      // שורת הסגירה
          codeLines.push(raw);
          const row = createEl('div', 'sticky-task-line sticky-md-pre');
          this._setSourceOffset(row, offset);
          // **שורה ריקה מוצגת כרווח**, אחרת ה-``div`` בגובה אפס והשורה
          // נעלמת מהתצוגה. זו גם הסיבה שכפתור ההעתקה קורא את **המקור**
          // ולא את ה-DOM: משם היה חוזר רווח במקום שורה ריקה.
          row.textContent = raw === '' ? ' ' : raw;
          body.appendChild(row);
          offset += raw.length + 1;
        }

        // גדר שלא נסגרה עד סוף הפתק היא מקרה תקין, לא שגיאה: הפתק נערך
        // ברגע זה, והשורה השנייה עוד לא הוקלדה.
        const closed = i < lines.length;
        if (closed) offset += lines[i].length + 1;

        // **הטקסט נלכד כאן, מהמקור, ולא נקרא מה-DOM בזמן הלחיצה.**
        const codeText = codeLines.join('\n');
        // **הכפתור הוא של המארח, לא של המנוע** (``_mdCodeCopyButton``): הוא נושא את מנגנון
        // הקליפבורד האחד של הפתק (``_copyText``) ואת החיווי שלו, ושניהם שייכים לממשק. מנוע
        // שרץ בלי מארח כזה — תצוגה לקריאה בלבד — בונה בלוק בלי כפתור, במקום ללחוץ על פונקציה
        // שאינה קיימת. אצל הפתק הכפתור נכנס לאותו מקום בדיוק, אחרי תווית השפה.
        if (typeof this._mdCodeCopyButton === 'function') head.appendChild(this._mdCodeCopyButton(codeText));

        // **יישור לימין לבלוק עברי בלי תג שפה** — אותו כלל שכבר פועל
        // בתצוגת המסמכים, ולכן אותה פונקציה. ``isHebrewMajority`` ב-
        // ``utils/rtl-code.js`` היא התשובה היחידה בפרויקט לשאלה "האם
        // הטקסט הזה עברי", והסף חי שם ולא כאן.
        //
        // ``applyRtlIfHebrew`` עצמה אינה שמישה: היא פותחת ב-
        // ``block.closest('pre')`` והפתק בונה ``div``-ים בלבד. גם
        // ``hasExplicitLanguage`` אינה — היא קוראת ``class="language-…"``
        // שאיננו כותבים אף פעם. לכן נקראת הצורה שמקבלת את **שם השפה
        // הגולמי**, שכבר נגזר למעלה: שורת הגדר אינה מפורסרת פעם שנייה.
        // מאותה סיבה הטקסט הוא ``codeText`` שכבר חושב לכפתור ההעתקה.
        //
        // **היעדר ``window.RtlCode`` הוא היעדר יכולת סטטי, לא נפילה-
        // לאחור למסלול גרוע** — בדיוק כמו ``ADMONITION_TITLES`` ב-
        // ``_containerSpec``, ויש בדיקת חיווט שמוודאת שכל תבנית טוענת
        // את הקובץ לפני המודול. הבדיקה כאן אינה הגנתיות: ``_syncTaskView``
        // כולו עטוף ב-``try/catch`` אחד שמוחק את התצוגה בתחילתו וחושף
        // אותה בסופו, ולכן חריגה כאן הייתה משאירה **כל פתק שיש בו גדר**
        // בלי מארקדאון כלל — בלי שגיאה ובלי לוג.
        const rtl = window.RtlCode;
        if (rtl && !rtl.hasExplicitLanguageName(lang) && rtl.isHebrewMajority(codeText)){
          box.classList.add('rtl-code');
        }

        box.appendChild(head);
        box.appendChild(body);
        view.appendChild(box);

        // **ספירת שורות המשימה שנצרכו** — אותה החלטה שכבר מתועדת עבור
        // טבלה. ``sticky_notes_tasks`` בשרת סופר כל שורת ``- [ ]``,
        // **כולל בתוך גדר**, ולכן הסידור כאן חייב להתקדם עליה גם כשהיא
        // אינה מוצגת כתיבה. אחרת כל צ'קבוקס שאחרי בלוק הקוד נשלח עם
        // אינדקס של משימה אחרת.
        let tasksConsumed = 0;
        const lastIndex = closed ? i : lines.length - 1;
        for (let k = startIndex; k <= lastIndex; k += 1){
          if (TASK_LINE_RE.test(lines[k])) tasksConsumed += 1;
        }
        return { lastIndex, nextOffset: offset, tasksConsumed };
      }

      _hasRenderableMarkdown(lines){
        for (let i = 0; i < lines.length; i += 1){
          const line = lines[i];
          if (MD_FENCE_RE.test(line)) return true;
          // **טבלה נבדקת כאן ולא ב-``_classifyLine``**, כי היא בלוק של שתי
          // שורות ואילו המסווג הוא פר-שורה. בלי הבדיקה הזו פתק שכולו טבלה
          // אינו עובר את השער והתצוגה כלל לא נפתחת — כשל שקט בדיוק במקרה
          // הנפוץ ביותר.
          if (i + 1 < lines.length && this._tableSpec(line, lines[i + 1])) return true;
          // מכולה נבדקת כאן מאותה סיבה בדיוק: ``_classifyLine`` הוא פר-שורה
          // ואינו מכיר בלוקים. בלי הבדיקה הזו פתק שכולו ``::: note`` (או
          // ``::: details``) לא היה עובר את השער והתצוגה כלל לא הייתה נפתחת.
          if (this._containerSpec(line)) return true;
          const b = this._classifyLine(line);
          if (b.kind !== 'plain') return true;
          if (this._lineHasInline(b.content)) return true;
        }
        return false;
      }

      // בונה את הקטעים לתוך ``container``, צומת אחר צומת. אפס innerHTML.
      _appendInline(container, text){
        this._appendInlineSegments(container, this._parseInline(text));
      }

      // עיצוב נבנה עם הילדים שלו — טקסט וקוד — ולא ממחרוזת אחת, ולכן קוד
      // בתוך מודגש יוצא ``strong > code`` ולא גרשיים בתוך מודגש.
      _appendInlineSegments(container, segs){
        for (const seg of segs){
          if (seg.type === 'text'){ container.appendChild(document.createTextNode(seg.text)); continue; }
          let node;
          if (seg.type === 'bold')        node = createEl('strong', 'sticky-md-bold');
          else if (seg.type === 'italic') node = createEl('em', 'sticky-md-italic');
          else if (seg.type === 'strike') node = createEl('del', 'sticky-md-strike');
          // הכיוון והתוכן של הקוד — ``fillInlineCode`` למטה, אחרי הבחירה באלמנט.
          else if (seg.type === 'code')   node = createEl('code', 'sticky-md-code');
          // ``<mark>`` ולא ``<span>``: זה האלמנט הסמנטי להדגשת רלוונטיות.
          // **בלי טענה על קוראי מסך** — רובם אינם מכריזים על ``<mark>``
          // כברירת מחדל. הבחירה היא נכונות סמנטית ותאימות לכלים שכן
          // קוראים אותו, לא נגישות שמובטחת. העיצוב נדרס ב-CSS ממילא.
          else if (seg.type === 'mark')   node = createEl('mark', 'sticky-md-mark');
          else if (seg.type === 'link'){
            node = createEl('a', 'sticky-md-link');
            // ``href`` נכתב עם setAttribute אחרי שהסכימה כבר אושרה ב-parseInline.
            try { node.setAttribute('href', seg.href); } catch(_) {}
            node.setAttribute('target', '_blank');
            node.setAttribute('rel', 'noopener noreferrer');
          }
          else node = document.createTextNode(seg.text);
          if (seg.type === 'code') fillInlineCode(node, seg.text);
          else if (node.nodeType !== 3) this._appendInlineSegments(node, seg.children);
          container.appendChild(node);
        }
      }

      /**
       * **התצוגה מטקסט, שורה אחר שורה** — כל מה שהיה בגוף ``_syncTaskView`` בין מחיקת התצוגה לחשיפתה.
       *
       * ``lines`` — שורות המקור (``content.split('\n')``). ``opts.wantMd`` — האם לפרש מארקדאון, או רק
       * צ'קבוקסים וטקסט; ``opts.openDetails`` — ``Set`` של הסידורים של בלוקי ``details`` שייפתחו
       * פתוחים (הזיכרון חי אצל הפתק, ב-``_getEntry``; כאן הוא רק נקרא). המתודה מוחקת את ``view`` ובונה
       * אותו מחדש; ההסתרה, החשיפה והחיפוש נשארים אצל הקורא.
       */
      _renderMarkdownView(view, lines, opts){
        const wantMd = !!(opts && opts.wantMd);
        const openDetails = (opts && opts.openDetails) || new Set();
        view.textContent = '';
        let taskIndex = 0;
        let charOffset = 0;
        //: סידור הבלוקים המתקפלים, לפי סדר הופעה במקור. זהו המפתח
        //: שמצב הפתיחה נשמר לפיו — ראו ההסבר בלכידה שלמעלה.
        let detailsIndex = 0;
        // **מחסנית אחת לכל הפתק** — עמודות התוכן של פריטי הרשימה
        // הפתוחים. היא חיה כאן ולא במתודה, כי עומק הקינון אינו תכונה
        // של שורה בודדת אלא של השורות שקדמו לה.
        const listStack = [];
        // **מחסנית המכולות**, ולצידה המכל הנוכחי. מכולה היא הבלוק הראשון
        // בפתק ש**מכיל** שורות אחרות במקום להיות אחת מהן, ולכן במקום
        // לולאת רינדור שנייה משתנה כאן דבר אחד: לאן שורה נכתבת. ברירת
        // המחדל היא התצוגה עצמה; בתוך מכולה זהו הגוף הפנימי ביותר.
        // כל שאר הענפים אינם יודעים על המכולה דבר וממשיכים כמו שהם —
        // וזה נכון גם ל-``::: details``, שנבדל רק באלמנט שהוא בונה.
        const containerStack = [];
        const currentParent = () => (containerStack.length ? containerStack[containerStack.length - 1].content : view);
        // **לולאה מאונדקסת ולא ``forEach``** — טבלה היא בלוק רב-שורתי,
        // והיא צריכה לצרוך כמה שורות בבת אחת ולקדם את ההיסט על כולן.
        for (let li = 0; li < lines.length; li += 1) {
          const line = lines[li];
          // **בלוק קוד נצרך ראשון ובבת אחת.**
          //
          // זה מה שמייתר את הדגלים ``inFence``/``isFenceLine`` שהיו כאן:
          // מרגע שהבלוק נצרך כיחידה, **הלולאה לעולם אינה נמצאת בתוך
          // גדר**, וכל הסייגים שנדרשו כדי לזכור את זה — חישוב מוקדם של
          // ``isFenceLine`` לפני בדיקת הטבלה, ההבחנה בין ``!inFence``
          // ל-``!inCode``, והחרגת שורת הסגירה מהמחסנית — נמחקים.
          //
          // **הבדיקה קודמת לטבלה, וזה נדרש; היא קודמת לאלרט, וזה לא.**
          // שתי ההתנהגויות נשמרות, אבל לא מאותה סיבה — נמדד בהיפוך
          // סדר בפועל:
          //
          //  - **מול הטבלה הסדר הוא ההגנה.** `````sh | x`` היא גם
          //    פותחת גדר וגם כותרת טבלה סבירה, ולכן הזזת בדיקת הטבלה
          //    לכאן מפילה בדיקה.
          //  - **מול האלרט הסדר אינו משנה דבר.** שורת גדר מתחילה
          //    בגרשיים ושורת אלרט בנקודתיים — הן זרות זו לזו, והיפוך
          //    הסדר אינו מפיל דבר. מה שמשאיר ``:::`` בתוך גדר כקוד
          //    ליטרלי הוא **הצריכה**: השורה נבלעת עם הבלוק ואינה
          //    מגיעה ללולאה כלל.
          if (wantMd && MD_FENCE_RE.test(line)) {
            const done = this._appendCodeBlock(currentParent(), lines, li, charOffset);
            li = done.lastIndex;
            charOffset = done.nextOffset;
            taskIndex += done.tasksConsumed;
            // **רק הזחת שורת הפתיחה קובעת** — התנהגות מתועדת שנשמרת
            // כאן ביט-זהה: הבלוק נצרך שלם, ולכן אין בכלל רגע שבו שורת
            // הסגירה יכולה לגעת במחסנית.
            this._closeListsAbove(listStack, this._lineIndentCols(line));
            continue;
          }
          // **אלרט נבדק אחרי בלוק הקוד**, וזה מה שמשאיר את ``:::``
          // שבתוך גדר כקוד ליטרלי — **סטייה מכוונת** מ-``markdown-it``,
          // שם הסורק של המכולה קורא שורות גולמיות ואינו מודע לגדרות
          // כלל. נמדד: ``::: note`` ואז גדר שיש בתוכה ``:::`` באמת
          // סוגרת שם את המכולה ושוברת את הגדר לשניים. זו אותה עמדה
          // שהפתק כבר נוקט בטבלה שבתוך גדר, והיא גם התוצאה השפויה
          // למשתמש. **מה שאוכף אותה הוא הצריכה ולא הסדר** — ראו את
          // ההערה על ענף בלוק הקוד, שם ההבחנה נמדדה.
          if (wantMd) {
            // **הסגירה נבדקת לפני הפתיחה, והשתיים זרות זו לזו ממילא:**
            // שורת סגירה היא נקודתיים ורווחים בלבד, ולפתיחה נדרשת אות
            // אחרי הנקודתיים. הסדר כאן הוא לקריאוּת, לא לנכונות.
            const closeMarkers = this._containerCloseMarkers(line);
            if (closeMarkers && this._closeContainersAt(containerStack, closeMarkers)) {
              // **שורת הסגירה עוברת בכלל האחיד, כמו כל גבול בלוק אחר.**
              //
              // כאן הייתה טעות של אנלוגיה: הגרסה הראשונה לא נגעה במחסנית
              // הרשימות, בנימוק שזה מה ששורת גדר סוגרת עושה. אבל שם זו
              // הוכחה ולא בחירה — **בתוך גדר שום דבר אינו נדחף למחסנית**,
              // כי התוכן ליטרלי, ולכן לסגירה אין מה לסגור. בתוך אלרט
              // התוכן עובר את המנוע המלא ו**כן** דוחף, ולכן אותה שורה
              // בדיוק אינה no-op — היא הגבול היחיד שסוגר את מה שנפתח
              // בפנים.
              //
              // בלי זה רשימה שנפתחה בתוך האלרט דלפה החוצה: ``- א`` ואז
              // ``␣␣- ב`` בתוך האלרט, ו-``␣␣- ג`` **אחריו** יצא בעומק 1
              // כבן של פריט שאינו קיים עוד. נמדד מול ``markdown-it`` על
              // 15 צירופים של רשימה × אלרט — חמישה סטו, וכולם נסגרו כאן.
              //
              // **וההזחה היא של שורת הסגירה עצמה**, לא עומק שנשמר
              // בפתיחה. גם את זה מדדתי: שמירת עומק המחסנית בפתיחה
              // ושחזורה כאן מתקנת פחות מקרים (שלושה נותרו סוטים מול
              // אחד), כי היא מתעלמת מההזחה — ולכן נשברת בדיוק כשהסגירה
              // מוזחת פנימה או החוצה ביחס לפתיחה.
              this._closeListsAbove(listStack, this._lineIndentCols(line));
              // נצרכת בלי אלמנט — אין לה מה להציג — וההיסט מקודם עליה,
              // בדיוק כמו שורת המפריד של טבלה. בלי הקידום כל מה שאחרי
              // האלרט מוסט באורך שורה שלמה, והלחיצה נוחתת בשורה אחרת.
              charOffset += line.length + 1;
              continue;
            }
            const container = this._containerSpec(line);
            if (container) {
              // המכולה היא בלוק ככל בלוק אחר, ולכן היא סוגרת פריטי רשימה
              // לפי ההזחה של **עצמה** — ולפני שהיא נפתחת, אחרת היא הייתה
              // נכנסת למכל שכבר אינו אמור להכיל אותה.
              this._closeListsAbove(listStack, this._lineIndentCols(line));
              // המונה מתקדם על בלוקים מתקפלים בלבד, ולכן אלרט שנוסף או
              // נמחק בין השניים אינו מזיז את הזהות של אף בלוק.
              const startOpen = container.type === MD_DETAILS_TYPE
                && openDetails.has(detailsIndex);
              if (container.type === MD_DETAILS_TYPE) detailsIndex += 1;
              containerStack.push(this._openContainer(currentParent(), container, charOffset, startOpen));
              charOffset += line.length + 1;
              continue;
            }
          }
          // הטבלה כבר אינה צריכה סייג של גדר: שורה בתוך גדר לעולם
          // אינה מגיעה לכאן.
          const spec = (wantMd && li + 1 < lines.length)
            ? this._tableSpec(line, lines[li + 1])
            : null;
          if (spec) {
            // מחזיר את שני הערכים במפורש ולא דרך שדה על המופע: ההיסט
            // מקודם על **כל** השורות שנצרכו, כולל שורת המפריד, ובלי זה
            // כל השורות שאחרי הטבלה מצביעות למקום שגוי.
            const done = this._appendTable(currentParent(), lines, li, spec, charOffset);
            li = done.lastIndex;
            charOffset = done.nextOffset;
            taskIndex += done.tasksConsumed;
            // טבלה היא בלוק ככל בלוק אחר, ולכן היא סוגרת פריטים לפי
            // ההזחה של **שורת הכותרת שלה**: טבלה בעמודה 0 סוגרת את
            // הרשימה, וטבלה שמוזחת לתוך פריט נשארת בתוכו. הענף הזה
            // עושה ``continue`` לפני הכלל המשותף שלמטה, ולכן הוא קורא
            // לו במפורש.
            this._closeListsAbove(listStack, this._lineIndentCols(line));
            continue;
          }
          const m = TASK_LINE_RE.exec(line);
          const row = createEl('div', 'sticky-task-line');
          // מיקום התו הראשון של השורה בתוך התוכן — כדי שלחיצה תחזיר
          // לעריכה בדיוק בשורה שנלחצה, ולא בתחילת הפתק.
          this._setSourceOffset(row, charOffset);
          // **הסידור מתקדם על כל שורת משימה, כמו השרת.**
          //
          // ``sticky_notes_tasks.toggle_task_at_index`` סופר כל שורת
          // ``- [ ]``, כולל בתוך גדר קוד — החלטה מתועדת שם ומכוסה
          // בבדיקה. לכן הסידור כאן חייב להתקדם באותה נקודה בדיוק, גם
          // כשהשורה בגדר ולא הופכת לתיבה אינטראקטיבית. אחרת האינדקס
          // שהלקוח שולח מצביע על משימה אחרת מזו שהמשתמש לחץ עליה.
          const thisTaskIndex = m ? taskIndex : -1;
          if (m) taskIndex += 1;
          // **הסיווג נעשה פעם אחת, לפני שהשורה מתפצלת לענף.**
          //
          // ``- [ ] א`` היא גם שורת משימה תקפה וגם פריט רשימה תקף, ושתי
          // השאלות — "האם זו משימה" ו"מה עומק הקינון שלה" — נשאלות על
          // אותה שורה. הסיווג ישב פעם בתוך ענף ה-``wantMd`` בלבד, ולכן
          // שורות המשימה כלל לא הזינו את מחסנית העומק: ``- [ ] א``
          // ואחריה ``  - ב`` היו יוצאות בעומק שגוי. שאלה אחת, מקום אחד.
          const b = wantMd ? this._classifyLine(line) : null;
          let depth = 0;
          // **כלל אחד לכל השורות: מי שאינו ריק מעדכן את המחסנית לפי
          // ההזחה של עצמו.**
          //
          // כאן ישב פעם ``!inFence``, שנועד להוציא את שורות הגדר מהכלל
          // ולהשאיר בו את הפותחת בלבד. הוא מיותר מרגע שהבלוק נצרך
          // שלם: שורות הגדר כלל אינן מגיעות לכאן, והפותחת קוראת
          // ל-``_closeListsAbove`` בענף שלה.
          //
          // **שורה ריקה אינה סוגרת רשימה** — נמדד מול ``markdown-it``,
          // גם שורה אחת וגם שתיים.
          //
          // הסטייה המכוונת מ-``markdown-it`` נשארת ונובעת מהכלל עצמו:
          // שם שורת טקסט או טבלה בעמודה 0 מיד אחרי פריט היא המשך
          // הפסקה שלו והרשימה ממשיכה. בפתק אין המשך פסקה — כל שורת
          // מקור היא שורת תצוגה נפרדת עם ההיסט שלה — והזחה 0 סוגרת
          // ממילא, בלי שנדרש ענף שיאמר זאת.
          if (wantMd && line.trim() !== '') {
            if (b && (b.kind === 'ul' || b.kind === 'ol')) {
              depth = this._listDepth(listStack, line, b);
              // עומק 0 אינו מקבל מחלקה: הוא חסר הזחה ממילא, ומחלקה
              // ריקה הייתה רק רעש ב-DOM.
              if (depth > 0) row.classList.add('is-depth-' + Math.min(depth, MD_MAX_LIST_DEPTH));
            } else {
              this._closeListsAbove(listStack, this._lineIndentCols(line));
            }
          }
          if (m) {
            // צ'קבוקס אינטראקטיבי. שורת משימה שבתוך גדר כלל אינה
            // מגיעה לכאן — היא נצרכה עם הבלוק — אבל **הסידור שלה כן
            // התקדם**, דרך ``tasksConsumed``.
            row.classList.add('sticky-task');
            const box = createEl('input', 'sticky-task-box');
            box.type = 'checkbox';
            box.checked = m[2].toLowerCase() === 'x';
            // **במצב קריאה בלבד הצ'קבוקס הוא סימון קבוע**: אין לו סידור לשלוח לשרת, ואין מי שמקשיב
            // ללחיצה עליו — ולכן גם אינו נראה לחיץ.
            if (this._mdReadOnly) box.disabled = true;
            else box.dataset.taskIndex = String(thisTaskIndex);
            const span = createEl('span', 'sticky-task-text');
            // גם טקסט המשימה מקבל אינליין, כשהמארקדאון דלוק.
            if (wantMd) this._appendInline(span, m[3].slice(1).trim());
            else span.textContent = m[3].slice(1).trim();
            row.appendChild(box);
            row.appendChild(span);
          } else if (wantMd) {
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
              // **ברשימה ממוספרת מוצג המספר שהוקלד, ולא מספור מחדש.**
              // התצוגה היא ראי חד-כיווני של המקור, וכל "תיקון" מספור
              // היה מציג משהו שאינו כתוב בפתק. ברשימה לא ממוספרת אין
              // מה לשקף, ולכן שם התבליט משתנה עם העומק.
              bullet.textContent = b.kind === 'ol'
                ? b.marker
                : MD_BULLETS[Math.min(depth, MD_BULLETS.length - 1)];
              if (b.kind !== 'ol') this._markGenerated(bullet);
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
          currentParent().appendChild(row);
          charOffset += line.length + 1;   // +1 עבור ה-``\n`` שהפיצול הסיר
        }
      }

      /**
       * ההיסט של שורת מקור על האלמנט שמייצג אותה — **במצב עריכה בלבד.**
       *
       * ההיסט קיים בשביל הלחיצה שנכנסת לעריכה בשורה הנכונה (``_enterEditFromView``), והחוזה של
       * המנוע — אלמנט לכל שורת מקור, עם ההיסט שלה — נשען עליו. תצוגה לקריאה בלבד אינה נכנסת
       * לעריכה, ולכן אינה כותבת אותו: מקום אחד מחליט, ולא כתיבה בכל בלוק שזוכרת לשאול.
       */
      _setSourceOffset(el, offset){
        if (!this._mdReadOnly) el.dataset.charOffset = String(offset);
      }
  }

  /**
   * **קוד בשורה בטקסט קצר — אותו כלל של הפתק.** כותרת שהגיעה מ-Markdown (שם פתק, או השורה
   * הראשונה שלו) נושאת לפעמים ``קוד`` בגרשיים הפוכים, והכרטיסים בארכיון ובעמוד הקבצים מציגים
   * אותו כקוד ולא כגרשיים גלויים (``note-cards.js``). ההכרעה מה קוד ומה טקסט היא של
   * ``_inlineScanState`` ו-``_inlineCodeAt`` — אותן שתיים שהפתק עצמו מרנדר בהן, ולא כלל שני:
   * רצף של N גרשיים נסגר ברצף הבא של N בדיוק, ורצף בלי סוגר נשאר טקסט.
   *
   * מחזיר ``[{text, code}]`` — קטעים צמודים, בסדר, שיחד מכסים את כל הטקסט מלבד הגרשיים של
   * קטעי הקוד. שתי הפונקציות טהורות (אינן נוגעות במנהל או ב-DOM), ולכן נקראות מהפרוטוטייפ.
   */
  function inlineCodeSegments(text){
    const src = String(text == null ? '' : text);
    const proto = StickyMdEngine.prototype;
    const state = proto._inlineScanState(src);
    const out = [];
    let last = 0;
    let i = src.indexOf('`');
    while (i !== -1){
      // ``i`` הוא תמיד תחילת רצף: או הגרש הראשון בטקסט, או הראשון אחרי סוף רצף או קטע קוד.
      const code = proto._inlineCodeAt(state, i);
      if (code.text !== null){
        if (i > last) out.push({ text: src.slice(last, i), code: false });
        out.push({ text: code.text, code: true });
        last = code.end;
      }
      i = src.indexOf('`', code.end);
    }
    if (last < src.length) out.push({ text: src.slice(last), code: false });
    return out;
  }

  /**
   * מצמיד את מתודות המנוע ל-``proto`` (``StickyNotesManager.prototype``).
   *
   * **מסרב לדרוס.** שם שכבר קיים על ``proto`` הוא ``Error`` מיד בטעינה: מתודה של המנהל שמתנגשת
   * בשם של המנוע הייתה נדרסת בשקט — או דורסת את המנוע — לפי סדר ההצמדה, וזו תקלה שאף בדיקה
   * אינה רואה עד שהפתק מתנהג אחרת.
   */
  function mixInto(proto){
    Object.getOwnPropertyNames(StickyMdEngine.prototype).forEach((name) => {
      if (name === 'constructor') return;
      if (Object.prototype.hasOwnProperty.call(proto, name)){
        throw new Error('StickyMdRender.mixInto: ' + name + ' already exists on the target');
      }
      Object.defineProperty(proto, name, Object.getOwnPropertyDescriptor(StickyMdEngine.prototype, name));
    });
    return proto;
  }

  /**
   * **תצוגה לקריאה בלבד** של טקסט פתק בתוך ``container`` — אותו מנוע ואותם כללים כמו בפתק.
   *
   * בלי ``data-charOffset``, צ'קבוקס מושבת, ובלי כפתור העתקה (אין כאן מארח שמספק אותו). המארקדאון
   * תמיד דלוק: אין כאן מתג של לוח. ``container`` נמחק ונבנה מחדש.
   */
  function render(container, text){
    const engine = new StickyMdEngine({ readOnly: true });
    const lines = String(text == null ? '' : text).split('\n');
    engine._renderMarkdownView(container, lines, { wantMd: true });
    return container;
  }

  window.StickyMdRender = Object.freeze({
    Engine: StickyMdEngine,
    mixInto,
    render,
    inlineCodeSegments,
    createEl,
    fillInlineCode,
    GENERATED_TEXT_CLASS,
    TASK_LINE_RE,
    MD_HR_RE,
    MD_FENCE_RE,
    MD_CONTAINER_OPEN_RE,
    MD_CONTAINER_CLOSE_RE,
    MD_DETAILS_TYPE,
    // הסכימות שקישור מותר בהן. מי שפותח קישור מחוץ למנוע — התצוגה בתוך Claude, דרך המארח — בודק
    // מולו, ולא מול עותק שלו.
    MD_SAFE_LINK,
  });
})();
