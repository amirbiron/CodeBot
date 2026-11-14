/**
 * **שרשרת דגימה של לשונית גלויה — מקום אחד לכל העקרונות.**
 *
 * שתי דגימות בוובאפ שואלות את השרת שוב ושוב: בועת התזכורות (``initStickyRemindersIndicator``
 * ב-``base.html``) והעדכון בזמן אמת של הפתקים (``sticky-notes.js``). העקרונות שלהן זהים, והם
 * נולדו בבועת התזכורות מתקלות אמיתיות (``docs/dev/sticky_notes_extending_backend.rst``, "הדגימה:
 * כשל אינו 'אין', ו-401 אינו כשל"); עותק שני שלהם בפתקים היה נסחף מהראשון בתיקון הבא (R6), ולכן
 * הם כאן, ושני הצרכנים קוראים ל-``VisiblePoll.create``. מה שנשאר אצל כל צרכן הוא רק התוכן:
 * מה שואלים, ומה עושים עם התשובה (``run``).
 *
 * מה השרשרת מבטיחה:
 *
 * - **בקשה אחת בכל רגע** (``inFlight``), והדגל נכבה ב-``finally`` — גם כשהבקשה נכשלה או נתקעה.
 * - **לכל בקשה תקרת זמן משלה** (``fetchOptions``), כי בשרת אין אחת: worker של gevent מודד את
 *   השתיקה של ה-worker ולא את אורך הבקשה, וחיבור half-open אינו מחזיר שום חבילה.
 *   ``AbortSignal.timeout`` נדחה עם ``TimeoutError`` ונופל לאותו מסלול כשל; דפדפן שאינו מכיר אותו
 *   מקבל את אותה תקרה מ-``AbortController`` — נפילה-לאחור על היעדר יכולת, לא על כשל.
 * - **כל כשל הוא "לא ידוע"**, לכולם מונה אחד ו-backoff אחד שמכפיל את עצמו מ-``minMs`` עד
 *   ``maxMs``, וכל כשל נרשם בקונסול עם המספר, ההמתנה והסיבה. הצלחה מאפסת את המונה.
 * - **429 אינו כשל**: השרת נוקב בהמתנה (``Retry-After``), היא נכתבת לחלון ה-backoff, והמונה אינו זז.
 * - **401 עוצר את השרשרת**, והניסיון הבא הוא החזרה הבאה ללשונית — בלי הרצפה, שנועדה לשרשרת חיה.
 * - **חזרה ללשונית מפעילה בדיקה**, אבל לא יותר מפעם ב-``visibilityFloorMs`` (במכשיר נייד כל מעבר
 *   בין אפליקציות הוא ``visibilitychange``). החותמת נכתבת **לפני** הבקשה, כדי שבקשה תקועה או
 *   שנכשלה לא תשאיר אותה באפס.
 * - **לשונית מוסתרת אינה שואלת**: הניסיון נדחה לתקרה, והחזרה ללשונית מקדימה אותו.
 * - **תשובה שחזרה אחרי עצירה נזרקת** (דור השרשרת): היא אינה מחייה את השרשרת ואינה דורכת טיימר. וחזרה
 *   ללשונית שהגיעה אחרי העצירה, בזמן שהניסיון ההוא עוד היה באוויר, אינה נבלעת: היא רצה כשהוא נגמר.
 *
 * ``run(ctx)`` מחזיר את מספר המילישניות עד הבדיקה הבאה (נתחם בין ``minMs`` ל-``maxMs``), או
 * ``VisiblePoll.STOP``. חריגה שעולה ממנו היא כשל ("לא ידוע"); צרכן שיש לו עבודה שאינה הבקשה —
 * החלת התשובה על המסך — תופס אותה בעצמו, כדי שבאג שם לא ייקרא "השרת לא ענה" (R10).
 *
 * הקובץ מגדיר בלבד: שום דבר אינו רץ בטעינה, ושרשרת מתחילה רק ב-``start()``.
 */
(function () {
  'use strict';

  if (typeof window === 'undefined') return;

  // לא מספר, בכוונה: ``schedule`` תוחם מספרים לרצפה, ואת זה אסור לו לתחום.
  const STOP = Symbol('visible-poll-stop');

  function finite(value, fallback) {
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
  }

  /**
   * שרשרת חדשה. ``opts``:
   *
   * - ``name`` — הקידומת של שורות הקונסול (``[name] poll failed …``).
   * - ``minMs``/``maxMs`` — הרצפה והתקרה של ההמתנה, וגם הבסיס והתקרה של ה-backoff.
   * - ``fetchTimeoutMs`` — תקרת הזמן של כל בקשה.
   * - ``visibilityFloorMs`` — הזמן המינימלי בין ניסיונות כשחוזרים ללשונית (ברירת מחדל: ``minMs``).
   * - ``windowFocus`` — גם ``focus`` של החלון מפעיל בדיקה, עם אותה רצפה. חלון שחוזרים אליו
   *   משולחן העבודה לא תמיד מחליף ``visibilityState``.
   * - ``run(ctx)`` — הבקשה עצמה. ראו ``makeCtx``.
   */
  function create(opts) {
    const name = String((opts && opts.name) || 'visible-poll');
    const minMs = finite(opts && opts.minMs, 60 * 1000);
    const maxMs = finite(opts && opts.maxMs, 30 * 60 * 1000);
    const fetchTimeoutMs = finite(opts && opts.fetchTimeoutMs, 15 * 1000);
    const floorMs = finite(opts && opts.visibilityFloorMs, minMs);
    const windowFocus = !!(opts && opts.windowFocus);
    const run = opts && opts.run;
    if (typeof run !== 'function') throw new TypeError('VisiblePoll.create: run חייב להיות פונקציה');

    let pollTimer = null;
    let lastPollAt = 0;
    let inFlight = false;
    let consecutiveFailures = 0;
    // השרשרת עצורה: הסשן נגמר (401). אין טיימר, והפוקוס הבא הוא המסלול היחיד חזרה — ולכן הרצפה
    // של החזרה ללשונית אינה חלה עליה.
    let stopped = false;
    // אחרי ``destroy`` השרשרת מתה: אין טיימר, אין מאזינים, ותשובה שבאוויר נזרקת.
    let destroyed = false;
    // דור השרשרת: עולה בכל עצירה. ניסיון שהיה באוויר כשהשרשרת נעצרה משווה אותו אחרי כל ``await``,
    // ותשובה ישנה נזרקת. JS חד-חוטי; ההשוואה אחרי ה-``await`` היא הגבול.
    let chainGen = 0;
    // חלון ה-backoff — של כשלים ושל 429 כאחד. החזרה ללשונית מכבדת אותו בלי לדעת למה הוא נקבע.
    let backoffUntil = 0;
    let started = false;
    // **בקשת חידוש שנדחתה כי ניסיון היה באוויר, בזמן שהשרשרת עצורה** (חזרה ללשונית, ``pollNow``). אחרי
    // ``stop()`` התשובה של הניסיון ההוא נזרקת — ובלי לזכור את הבקשה, החזרה ללשונית שהגיעה בזמן הזה הייתה
    // נבלעת, והשרשרת נשארת עצורה עד הפוקוס הבא. בקשה שהגיעה כשהשרשרת חיה אינה נזכרת: הניסיון שבאוויר עונה
    // עליה. ו-``stop()`` בלי בקשה כזו נשאר עצור.
    let renewalRequested = false;

    function fetchOptions() {
      const o = { cache: 'no-store', credentials: 'same-origin' };
      // דפדפן שאינו מכיר AbortSignal.timeout מקבל את אותה תקרה מ-AbortController — נפילה-לאחור על
      // היעדר יכולת סטטי, לא על כשל בזמן ריצה, ובלי מסלול גרוע יותר. בלי סיגנל בכלל, בקשה תקועה
      // השאירה את inFlight דלוק לנצח והפוקוס לא הציל: הגארד אינו יכול לחיות יותר מהבקשה שהוא שומר.
      if (typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function') {
        o.signal = AbortSignal.timeout(fetchTimeoutMs);
      } else if (typeof AbortController === 'function') {
        const c = new AbortController();
        setTimeout(() => c.abort(), fetchTimeoutMs);
        o.signal = c.signal;
      }
      return o;
    }

    // כשל אינו "אין" — הוא "לא ידוע". מונה אחד ו-backoff אחד: הרצפה, ואז כפול בכל כשל רצוף עד
    // התקרה. וכל כשל נרשם — המספר, ההמתנה הבאה והסיבה — כי כשל שקט נראה בדיוק כמו "אין".
    function failAndBackOff(reason) {
      consecutiveFailures += 1;
      const backoffMs = Math.min(maxMs, minMs * 2 ** (consecutiveFailures - 1));
      backoffUntil = Date.now() + backoffMs;
      console.warn(`[${name}] poll failed (#${consecutiveFailures}) — retry in ${backoffMs} ms:`, reason);
      return backoffMs;
    }

    // עוצרת את השרשרת. מבטלת את הטיימר התלוי ולא רק את הידית: 401 שהגיע בפוקוס, בזמן שטיימר
    // מהניסיון הקודם תלוי, השאיר אותו יורה ושולח עוד בקשה.
    function stopChain() {
      stopped = true;
      chainGen += 1;
      try { if (pollTimer) { clearTimeout(pollTimer); } } catch (_) { /* ידית שכבר פקעה — אין מה לבטל */ }
      pollTimer = null;
    }

    function staleAfterStop() {
      console.warn(`[${name}] poll outlived a stop; its outcome is ignored`);
      return STOP;
    }

    function schedule(ms) {
      try { if (pollTimer) { clearTimeout(pollTimer); } } catch (_) { /* ידית שכבר פקעה — אין מה לבטל */ }
      const requested = Number(ms);
      const safe = Number.isFinite(requested) ? requested : maxMs;
      // התקרה היא גם מה שמונע overflow של setTimeout: ההשהיה מומרת ל-int32 חתום, וכל ערך מעל
      // 2,147,483,647ms גולש (MDN, Window.setTimeout, "Maximum delay value").
      const delay = Math.min(maxMs, Math.max(minMs, safe));
      try { pollTimer = setTimeout(pollAndReschedule, delay); } catch (_) { pollTimer = null; }
    }

    /** מה ש-``run`` מקבל. ``gen`` הוא הדור שבו הניסיון התחיל. */
    function makeCtx(gen) {
      return {
        fetchOptions,
        /** האם הניסיון עדיין של השרשרת החיה — לבדוק אחרי כל ``await``. */
        isCurrent: () => gen === chainGen && !destroyed,
        /** ניסיון שחזר אחרי עצירה: נזרק, ולא דורך טיימר. */
        stale: staleAfterStop,
        /** כשל — "לא ידוע". מחזיר את ההמתנה עד הניסיון הבא. */
        fail: failAndBackOff,
        /** הצלחה — מאפסת את מונה הכשלים. */
        succeeded: () => { consecutiveFailures = 0; },
        /**
         * 429: השרת נוקב בהמתנה בעצמו. היא נכתבת לחלון ה-backoff, המונה אינו זז, וההמתנה היא
         * לפחות ``minWaitMs`` — מה שהצרכן יודע על התקרה שלו.
         */
        rateLimited: (response, minWaitMs) => {
          let backoffMs = finite(minWaitMs, minMs);
          try {
            const ra = parseInt((response && response.headers && response.headers.get('Retry-After')) || '', 10);
            if (Number.isFinite(ra) && ra > 0) backoffMs = Math.max(backoffMs, ra * 1000);
          } catch (_) { /* בלי כותרת קריאה — נשארים על המינימום */ }
          backoffUntil = Date.now() + backoffMs;
          return backoffMs;
        },
        /**
         * 401: הסשן נגמר. השרשרת נעצרת, ולנסות שוב בכל פעם זה רק להציף את השרת ב-401; החזרה
         * הבאה ללשונית מנסה מיד, כך שהתחברות בלשונית אחרת מחיה את השרשרת בלי רענון.
         */
        sessionEnded: () => {
          console.warn(`[${name}] session ended (401); polling stops until the next tab focus`);
          return STOP;
        },
      };
    }

    // מחזירה כמה מילישניות להמתין עד הניסיון הבא, או STOP.
    async function attempt() {
      const gen = chainGen;
      try {
        if (document.visibilityState && document.visibilityState !== 'visible') { return maxMs; }
        if (backoffUntil && Date.now() < backoffUntil) { return backoffUntil - Date.now(); }
        // החותמת לפני הבקשה, לא אחריה: הרצפה של החזרה ללשונית נמדדת מתחילת הניסיון, גם כשהוא
        // נכשל או תקוע. כשהיא נכתבה אחרי ה-await, רשת מנותקת הותירה אותה ב-0, וכל מעבר בין
        // אפליקציות בנייד שלח בקשה נוספת.
        lastPollAt = Date.now();
        return await run(makeCtx(gen));
      } catch (e) { if (gen !== chainGen || destroyed) { return staleAfterStop(); } return failAndBackOff(e); }
    }

    async function pollAndReschedule() {
      if (destroyed) { return; }
      // גארד: JS חד-חוטי ואין await בין הבדיקה להצבה, ולכן זה אטומי. בלעדיו חזרה ללשונית באמצע
      // בקשה שלחה בקשה שנייה, והתשובה שהגיעה אחרונה ניצחה.
      if (inFlight) {
        if (stopped) { renewalRequested = true; }
        return;
      }
      inFlight = true;
      renewalRequested = false;
      // הדור שבו הניסיון התחיל. ``stop()`` מבחוץ בזמן שהוא באוויר מעלה את הדור, ואז תוצאת הניסיון —
      // גם הצלחה רגילה — אינה מחייה את השרשרת ואינה דורכת טיימר. השרשרת אוכפת את זה בעצמה, ולא
      // סומכת על כך שכל ``run`` בודק ``isCurrent`` אחרי כל ``await``.
      const gen = chainGen;
      let nextMs = maxMs;
      try { nextMs = await attempt(); } catch (e) { nextMs = failAndBackOff(e); } finally { inFlight = false; }
      if (destroyed) { return; }
      if (gen !== chainGen) {
        // התשובה נזרקת (נעצרה בזמן שהייתה באוויר). חידוש שהתבקש אחרי העצירה רץ עכשיו; בלעדיו — נשארים עצורים.
        if (renewalRequested) { renewalRequested = false; pollAndReschedule(); }
        return;
      }
      renewalRequested = false;
      // 401: אין טיימר. הניסיון הבא הוא החזרה הבאה ללשונית.
      if (nextMs === STOP) { stopChain(); return; }
      stopped = false;
      schedule(nextMs);
    }

    // חזרה ללשונית מפעילה בדיקה — אבל לא בכל פעם. במצב עצור אין שרשרת שהרצפה שומרת עליה, והפוקוס
    // הוא הדרך היחידה חזרה — לכן שם היא לא חלה; inFlight והשער של ה-backoff ב-attempt ממשיכים לחול.
    function onReturn() {
      if (destroyed) { return; }
      if (document.visibilityState && document.visibilityState !== 'visible') { return; }
      if (!stopped && Date.now() - lastPollAt < floorMs) { return; }
      pollAndReschedule();
    }

    const chain = {
      /** מפעיל את השרשרת: ניסיון ראשון מיד, ומאזינים לחזרה ללשונית. פעם אחת בלבד. */
      start() {
        if (started || destroyed) { return; }
        started = true;
        document.addEventListener('visibilitychange', onReturn);
        if (windowFocus) { window.addEventListener('focus', onReturn); }
        pollAndReschedule();
      },
      /** ניסיון עכשיו (לא אם אחד כבר באוויר). */
      pollNow() { pollAndReschedule(); },
      /**
       * אפשרויות ה-``fetch`` של השרשרת, עם אותה תקרת זמן — לבקשה של הצרכן שאינה הדגימה עצמה (למשל
       * הרשימה שנפתחת בלחיצה על הבועה), כדי שגם היא לא תיתלה לנצח.
       */
      fetchOptions,
      /** עוצר את השרשרת מבחוץ — למשל 401 שהגיע בבקשה אחרת. החזרה ללשונית מחיה אותה. */
      stop() { stopChain(); },
      /** מפרק: בלי טיימר, בלי מאזינים, ותשובה שבאוויר נזרקת. */
      destroy() {
        destroyed = true;
        stopChain();
        document.removeEventListener('visibilitychange', onReturn);
        if (windowFocus) { window.removeEventListener('focus', onReturn); }
      },
      /** חלון ה-backoff (חותמת זמן במילישניות) — לקריאה ולדיבאג. */
      get backoffUntil() { return backoffUntil; },
      set backoffUntil(value) { backoffUntil = finite(value, 0); },
      get stopped() { return stopped; },
    };
    return chain;
  }

  window.VisiblePoll = Object.freeze({ create, STOP });
})();
