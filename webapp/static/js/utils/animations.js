/**
 * Utilities: אנימציות הוספה/מחיקה לפריטים
 * נטען גלובלית דרך base.html
 */

(function () {
  /**
   * הוספת פריט עם אנימציה
   * @param {HTMLElement} container - הקונטיינר
   * @param {HTMLElement} itemElement - הפריט החדש
   */
  function addItemWithAnimation(container, itemElement) {
    if (!container || !itemElement) {
      return;
    }

    itemElement.classList.add('is-new');
    container.insertBefore(itemElement, container.firstChild);

    let cleaned = false;
    const cleanup = () => {
      if (cleaned) {
        return;
      }
      cleaned = true;
      try {
        itemElement.classList.remove('is-new');
      } catch (_) {
        // ignore
      }
    };

    itemElement.addEventListener('animationend', cleanup, { once: true });
    setTimeout(cleanup, 800); // fallback: אם animationend לא נורה
  }

  /**
   * מחיקת פריט עם אנימציה
   * @param {HTMLElement} row - הפריט למחיקה
   * @param {Function} callback - פונקציה להרצה אחרי מחיקה (אופציונלי)
   * @returns {Promise<void>}
   */
  async function removeItemWithAnimation(row, callback) {
    if (!row) {
      if (callback) {
        try {
          callback();
        } catch (_) {
          // ignore
        }
      }
      return;
    }

    row.classList.add('is-removing');

    return new Promise((resolve) => {
      let settled = false;

      const finish = () => {
        if (settled) {
          return;
        }
        settled = true;
        if (callback) {
          try {
            callback();
          } catch (_) {
            // ignore
          }
        }
        try {
          row.remove();
        } catch (_) {
          try {
            row.parentNode && row.parentNode.removeChild(row);
          } catch (_2) {
            // ignore
          }
        }
        resolve();
      };

      row.addEventListener('animationend', finish, { once: true });
      setTimeout(finish, 400); // fallback
    });
  }

  // חשיפה ל-window כדי שסקריפטים אחרים (IIFE) יוכלו להשתמש
  try {
    window.addItemWithAnimation = addItemWithAnimation;
    window.removeItemWithAnimation = removeItemWithAnimation;
    // AnimUtils: אנימציות כלליות (כמו Fade-in) לשימוש ב-UI.
    // הערה: זה "סטנדרט" קליל ללא תלות בספריות חיצוניות.
    window.AnimUtils = window.AnimUtils || {};
    window.AnimUtils.fadeIn = function fadeIn(element, opts) {
      try {
        const el = element;
        if (!el) return;
        const options = opts || {};
        const duration = Math.max(80, Number(options.duration || 180));
        const easing = options.easing || 'ease-out';
        const fromOpacity = Number(options.fromOpacity ?? 0);
        const toOpacity = Number(options.toOpacity ?? 1);
        const fromY = Number(options.fromY ?? 6);
        const toY = Number(options.toY ?? 0);
        if (typeof el.animate === 'function') {
          el.animate(
            [
              { opacity: fromOpacity, transform: `translateY(${fromY}px)` },
              { opacity: toOpacity, transform: `translateY(${toY}px)` },
            ],
            { duration, easing, fill: 'both' }
          );
        } else {
          el.style.opacity = String(toOpacity);
          el.style.transform = `translateY(${toY}px)`;
        }
      } catch (_) {
        // ignore
      }
    };
    window.AnimUtils.fadeInChildren = function fadeInChildren(container, selector, opts) {
      try {
        const root = container;
        if (!root) return;
        const sel = selector || '[data-anim="fade-in"]';
        const nodes = Array.from(root.querySelectorAll(sel));
        nodes.forEach((node, idx) => {
          const delay = Math.min(240, idx * 35);
          setTimeout(() => window.AnimUtils.fadeIn(node, opts), delay);
        });
      } catch (_) {
        // ignore
      }
    };
  } catch (_) {
    // ignore
  }

  // ---------------------------------------------------------------------------
  // אנימציות של מעבר מצב: מיזעור פתק, תפריט ⋮ בעמוד הקובץ, קבוצה בפיד האחרון בדשבורד,
  // והחלונית "קבצים אחרונים". ההסבר המלא — docs/webapp/theming_and_css.rst, העוגן
  // ``anim-utils-state-motion``.
  //
  // **שלושה כללים שכל הפונקציות כאן שומרות:**
  //
  // 1. **המצב משתנה מיד, והאנימציה היא שכבה מעליו.** כל פונקציה מקבלת את השינוי עצמו
  //    (``mutate``) או רצה אחריו, ואינה דוחה אותו. מחלקה, ``hidden`` ושמירה קורים באותו
  //    רגע כמו בלי אנימציה, ולכן קוד שבודק את המצב — Escape, השבתת כפתורים, שמירה — לא
  //    רואה שום מצב ביניים.
  // 2. **שום דבר לא נשאר אחרי הסוף.** אין ``fill: 'forwards'``: אנימציה שהסתיימה מפסיקה
  //    להשפיע (ברירת המחדל של ``fill`` היא ``"none"`` — MDN, ``KeyframeEffect()``), ולכן
  //    קוד שמודד גאומטריה (שמירת מיקום פתק, הצמדת תפריט למסך) קורא את הערכים האמיתיים.
  //    ``fill: 'backwards'`` בלבד, כדי שפריט שמחכה לתורו יחכה במצב ההתחלה ולא יופיע לרגע.
  // 3. **Web Animations ולא ``transition`` של CSS.** ``dark-mode.css`` מגדיר ``transition``
  //    על ``[data-theme="dark"] *`` (ועל שאר הערכות הכהות), בספציפיות של מחלקה אחת ואחרי קובצי
  //    הרכיבים — כלומר ``transition`` שנכתב על מחלקה נדרס בשקט בכל הערכות הכהות. אנימציה
  //    של ``Element.animate`` אינה נוגעת בתכונה ``transition`` בכלל.
  // ---------------------------------------------------------------------------

  /**
   * התזמונים של האנימציות שרק ה-JS מריץ — המקום היחיד שבו הם כתובים. המספרים והעקומות
   * נלקחו מהפתק "אנימציות לCk" (רכיבי React: ``sidebar-collapse``, ``expand-card``,
   * ``morph-popover``). ``step`` הוא ההשהיה בין פריט לפריט, ו-``maxIndex`` עוצר את ההשהיה
   * המצטברת, כדי שרשימה ארוכה לא תיכנס במשך שניות. עקומה שה-y שלה מעל 1 היא שעושה את הקפיץ:
   * התנועה עוברת מעט את היעד וחוזרת.
   *
   * **הכניסה של פריטי תפריט (``spring-dropdown``) אינה כאן.** היא רצה גם מ-CSS (האפשרויות של
   * ה-select בחיפוש הגלובלי), ולכן התזמון שלה כתוב בטוקנים ``--motion-menu-*`` ב-``animations.css``,
   * ו-``menuMotion`` קורא אותם משם.
   */
  const MOTION = Object.freeze({
    noteFold: Object.freeze({ duration: 500, easing: 'cubic-bezier(.2, 1.3, .3, 1)' }),
    noteContent: Object.freeze({ duration: 250, easing: 'ease' }),
    groupFold: Object.freeze({ duration: 500, easing: 'cubic-bezier(.2, 1.3, .3, 1)' }),
    groupChevron: Object.freeze({ duration: 400, easing: 'cubic-bezier(.4, 0, .2, 1)' }),
    groupRow: Object.freeze({ duration: 400, easing: 'cubic-bezier(.2, 1.4, .3, 1)', step: 60, maxIndex: 7 }),
    groupRowFade: Object.freeze({ duration: 300, easing: 'ease', step: 60, maxIndex: 7 }),
    morph: Object.freeze({ duration: 500, easing: 'cubic-bezier(.2, 1.35, .3, 1)' }),
    morphContent: Object.freeze({ duration: 300, easing: 'ease', delay: 180 }),
    morphBackdrop: Object.freeze({ duration: 300, easing: 'ease' }),
  });

  /**
   * האם המשתמש ביקש פחות תנועה (``prefers-reduced-motion: reduce``).
   *
   * **צריך את זה ב-JS, ולא רק ב-CSS.** הכלל הגלובלי ב-``animations.css`` מקצר
   * ``animation-duration`` ו-``transition-duration``, אבל לא נוגע ב-``animation-delay``
   * ולא באנימציות של ``Element.animate`` — אלה אינן נשלטות מגיליון הסגנונות.
   */
  function prefersReducedMotion() {
    return typeof window.matchMedia === 'function'
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  /** אפשר להנפיש את ``el``: יש ``Element.animate``, והמשתמש לא ביקש פחות תנועה. */
  function canAnimate(el) {
    return !!el && typeof el.animate === 'function' && !prefersReducedMotion();
  }

  /**
   * ההזזה וההגדלה שמניחות את המלבן ``from`` על המלבן ``to``: מרכז אל מרכז, ויחס גדלים
   * בכל ציר. ``translate(dx, dy) scale(sx, sy)`` על אלמנט שהקופסה שלו היא ``from``, עם
   * ``transform-origin`` של ברירת המחדל (המרכז), מצייר אותו במקום ובגודל של ``to``.
   *
   * **הפרש בין שני מלבנים שנמדדו, ולא נוסחה לפי ``direction``** — ולכן נכון בעמוד שנפרש
   * מימין לשמאל ובעמוד שנפרש משמאל לימין באותה מידה (H7).
   */
  function rectDelta(from, to) {
    return {
      dx: (to.left + to.width / 2) - (from.left + from.width / 2),
      dy: (to.top + to.height / 2) - (from.top + from.height / 2),
      sx: to.width / from.width,
      sy: to.height / from.height,
    };
  }

  /**
   * מפעיל את ``keyframes`` על כל אחד מ-``nodes``, בהשהיה מדורגת: הפריט ה-i מתחיל אחרי
   * ``delay + min(i, maxIndex) × step``. מחזיר את האנימציות שהופעלו — רשימה ריקה כשאי אפשר
   * להנפיש. ``fill: 'backwards'``: בזמן ההמתנה הפריט מוצג במצב של המסגרת הראשונה.
   */
  function play(nodes, keyframes, timing) {
    const t = timing || {};
    // תזמון בלי משך — למשל טוקן CSS שלא נטען בעמוד — אינו אנימציה. בלי הבדיקה ``animate``
    // היה מקבל משך לא מוגדר, כלומר אפס, והפריט היה "מונפש" בלי לזוז.
    if (!Number.isFinite(t.duration)) return [];
    const step = Number(t.step) || 0;
    const base = Number(t.delay) || 0;
    const maxIndex = Number.isFinite(t.maxIndex) ? t.maxIndex : Infinity;
    const out = [];
    Array.from(nodes || []).forEach((node, i) => {
      if (!canAnimate(node)) return;
      out.push(node.animate(keyframes, {
        duration: t.duration,
        easing: t.easing,
        delay: base + Math.min(i, maxIndex) * step,
        fill: 'backwards',
      }));
    });
    return out;
  }

  /**
   * מילישניות מערך זמן של CSS: ``500ms`` או ``.25s``. ``NaN`` לכל דבר אחר — גם למחרוזת ריקה, שהיא
   * מה ש-``getPropertyValue`` מחזיר על טוקן שאינו מוגדר.
   */
  function cssTimeMs(value) {
    const m = /^(-?\d*\.?\d+)(ms|s)$/.exec(String(value || '').trim());
    if (!m) return NaN;
    return parseFloat(m[1]) * (m[2] === 's' ? 1000 : 1);
  }

  /**
   * התזמון של כניסת פריטי תפריט, מהטוקנים ``--motion-menu-*`` ב-``animations.css`` — כלומר מאותו
   * מקור שה-CSS נשען עליו. ``null`` כשהטוקנים לא נמצאו (עמוד שלא טען את ``animations.css``).
   *
   * **נקרא בכל קריאה, ולא פעם אחת בטעינה.** הקובץ הזה נטען עם ``defer``, וקריאה אחת בטעינה הייתה
   * תלויה בכך שגיליון הסגנונות כבר הוחל — וקריאה של כמה טוקנים בפתיחת תפריט זולה.
   */
  function menuMotion() {
    const cs = window.getComputedStyle(document.documentElement);
    const token = (name) => cs.getPropertyValue(`--motion-menu-${name}`).trim();
    const motion = {
      from: token('from'),
      duration: cssTimeMs(token('duration')),
      easing: token('ease'),
      step: cssTimeMs(token('step')),
      fadeDuration: cssTimeMs(token('fade-duration')),
      fadeEasing: token('fade-ease'),
    };
    if (!motion.from || !motion.easing || !motion.fadeEasing
        || ![motion.duration, motion.step, motion.fadeDuration].every(Number.isFinite)) {
      return null;
    }
    return Object.freeze(motion);
  }

  /**
   * כניסה של פריטי תפריט (``spring-dropdown``): כל פריט נכנס מעט מלמעלה ומוקטן ונוחת בקפיץ, ודוהה
   * פנימה בתזמון קצר משלו, בהשהיה ``step`` אחרי הקודם. הסדר הוא הסדר של ``items`` — מי שרוצה
   * שהכניסה תתחיל ליד הכפתור מסדר קודם ב-``byDistanceFrom``. מחזיר את האנימציות שהופעלו.
   */
  function cascadeMenu(items) {
    const m = menuMotion();
    if (!m) return [];
    return [
      ...play(items, [{ transform: m.from }, { transform: 'none' }],
        { duration: m.duration, easing: m.easing, step: m.step }),
      ...play(items, [{ opacity: 0 }, { opacity: 1 }],
        { duration: m.fadeDuration, easing: m.fadeEasing, step: m.step }),
    ];
  }

  /**
   * ``items`` מסודרים מהקרוב אל הרחוק ממרכז ``anchor`` — מרחק בין מרכזי מלבנים שנמדדו. כך כניסה
   * מדורגת מתחילה ליד הכפתור שפתח את התפריט, בשורה, ברשת ובתפריט שנפתח כלפי מעלה, ונכונה בעמוד
   * שנפרש מימין לשמאל ובעמוד שנפרש משמאל לימין בלי לשאול מה הכיוון (H7). שוויון במרחק נשאר בסדר
   * המקורי (``sort`` יציב).
   */
  function byDistanceFrom(anchor, items) {
    const list = Array.from(items || []);
    if (!anchor || typeof anchor.getBoundingClientRect !== 'function') return list;
    const a = anchor.getBoundingClientRect();
    const ax = a.left + a.width / 2;
    const ay = a.top + a.height / 2;
    return list
      .map((el) => {
        const r = el.getBoundingClientRect();
        return { el, d: Math.hypot(r.left + r.width / 2 - ax, r.top + r.height / 2 - ay) };
      })
      .sort((p, q) => p.d - q.d)
      .map((p) => p.el);
  }

  /**
   * כניסה של פריטי תפריט שמתחילה ליד ``anchor`` — הכפתור שפתח את התפריט — ומתרחקת ממנו:
   * ``cascadeMenu`` על ``items`` אחרי ``byDistanceFrom``.
   */
  function cascadeFrom(anchor, items) {
    return cascadeMenu(byDistanceFrom(anchor, items));
  }

  /**
   * רושם את ``anim`` כאנימציה שרצה עכשיו על ``el`` במפה ``map``, ומוחק אותה משם כשהיא נגמרת —
   * רק אם בינתיים לא נרשמה אחרת במקומה.
   *
   * ``finished`` נדחה ב-``AbortError`` כשהאנימציה מבוטלת (MDN, ``Animation.cancel()``) — וזה בדיוק
   * המקרה של לחיצה חוזרת, שכבר רשמה במקומה אנימציה חדשה. אין כאן כשל לדווח.
   */
  function remember(map, el, anim) {
    map.set(el, anim);
    const forget = () => {
      if (map.get(el) === anim) map.delete(el);
    };
    anim.finished.then(forget, forget);
    return anim;
  }

  /** אנימציית הגובה שרצה עכשיו על כל אלמנט, כדי שלחיצה חוזרת תמשיך מהגובה שרואים. */
  const heightAnims = new WeakMap();

  /**
   * מריץ את ``mutate`` — השינוי שמשנה את גובה ``el`` — ומנפיש את המעבר מהגובה הקודם לחדש.
   * מחזיר את האנימציה, או ``null`` כשאין מה להנפיש. ``mutate`` רץ תמיד, ובאותו רגע.
   *
   * **גדילה מונפשת ב-``height``, וכיווץ ב-``min-height``.** לפי סדר המפל, הצהרות של
   * אנימציה גוברות על הצהרות רגילות של העמוד ומפסידות ל-``!important`` שלו (MDN,
   * "Cascade", הטבלה "Cascading order"). פתק ממוזער נשען על ``height: auto !important``
   * (``sticky-notes.css``), ולכן אנימציה של ``height`` אינה משנה אותו כלל — נמדד בכרומיום:
   * הקופסה נשארה בגובה הכותרת לאורך כל האנימציה. ``min-height`` אינו מוצהר שם, והקופסה היא
   * הגדול מבין הגובה הטבעי ל-``min-height`` — כלומר היא יורדת מהגובה הקודם ונעצרת בדיוק
   * בגובה החדש, גם כשעקומת הקפיץ עוברת אותו.
   *
   * ``clip``: ``overflow: hidden`` רק בזמן האנימציה — תכונה בדידה עם אותו ערך בשתי
   * המסגרות מוחזקת לכל אורכה ונעלמת בסופה. בלי זה, תוכן שכבר מוצג במלואו בולט מתחת לקופסה
   * שעוד גדלה. לא בפתק: ילדים שלו יושבים מחוצה לו בכוונה (``.is-unclipped``).
   */
  function animateHeight(el, mutate, timing) {
    const t = timing || {};
    if (!el) {
      mutate();
      return null;
    }
    // המדידה כוללת אנימציה שעוד רצה, ולכן היא מה שרואים עכשיו. הביטול אחריה: אחרי
    // ``cancel`` הגובה קופץ לערך האמיתי, והמדידה של "אחרי" לא צריכה לכלול את הישנה.
    const from = el.getBoundingClientRect().height;
    const running = heightAnims.get(el);
    if (running) running.cancel();
    mutate();
    const to = el.getBoundingClientRect().height;
    if (!canAnimate(el) || !from || !to || Math.abs(to - from) < 1) return null;
    const prop = to > from ? 'height' : 'minHeight';
    const first = { [prop]: `${from}px` };
    const last = { [prop]: `${to}px` };
    if (t.clip) {
      first.overflow = 'hidden';
      last.overflow = 'hidden';
    }
    return remember(heightAnims, el, el.animate([first, last], { duration: t.duration, easing: t.easing }));
  }

  /**
   * הזווית שבה ``el`` מצויר עכשיו, במעלות. היא נקראת מה-``transform`` המחושב, ולכן כוללת סיבוב
   * שעוד רץ עליו.
   *
   * ``getComputedStyle`` מחזיר ``none`` או ``matrix()`` / ``matrix3d()``. את שני האחרונים
   * ``DOMMatrixReadOnly`` מקבל כמחרוזת (MDN, ``DOMMatrixReadOnly()``); ``none`` אינו ברשימה של
   * הפורמטים שם, ולכן הוא נבדק לפני. ``a`` ו-``b`` הם ``m11`` ו-``m12`` — הקוסינוס והסינוס של הסיבוב.
   * הטווח הוא (-90, 270]: ``atan2`` מחזיר זווית שבין 180 ל-270 כשלילית, והיא מועברת לחצי השני.
   */
  function rotationOf(el) {
    const value = window.getComputedStyle(el).transform;
    if (!value || value === 'none') return 0;
    const m = new DOMMatrixReadOnly(value);
    const deg = Math.atan2(m.b, m.a) * 180 / Math.PI;
    return deg <= -90 ? deg + 360 : deg;
  }

  /** אנימציית הסיבוב שרצה עכשיו על כל אלמנט — אותו תפקיד כמו ``heightAnims``. */
  const rotationAnims = new WeakMap();

  /**
   * מסובב את ``el`` מ-``fromDeg`` אל הזווית שה-CSS קובע לו עכשיו. מחזיר את האנימציה, או ``null``.
   *
   * **``fromDeg`` נמדד ב-``rotationOf`` לפני שינוי המצב, ולא אחריו.** אחרי השינוי הסגנון המחושב
   * כבר שווה ליעד, ואנימציה שהייתה מתחילה ממנו לא הייתה זזה בכלל — נמדד בכרומיום 153 ב-18.11.2026:
   * החץ קפץ מ-180 ל-0 בפריים אחד. והמדידה לפני השינוי כוללת סיבוב שעוד רץ, ולכן לחיצה חוזרת באמצע
   * ממשיכה מהזווית שרואים; עם שתי זוויות קבועות היא קפצה קודם לזווית ההתחלה הקבועה.
   *
   * **היעד נקרא מה-CSS ולא נכתב כאן.** הסיבוב הקודם מבוטל קודם, ואז הסגנון המחושב הוא מצב ה-CSS
   * בלבד, כך שזווית היעד כתובה פעם אחת — בכלל ה-CSS.
   */
  function rotateFrom(el, fromDeg, timing) {
    const t = timing || {};
    if (!el) return null;
    const running = rotationAnims.get(el);
    if (running) running.cancel();
    const toDeg = rotationOf(el);
    if (!canAnimate(el) || Math.abs(toDeg - fromDeg) < 0.5) return null;
    return remember(rotationAnims, el, el.animate([
      { transform: `rotate(${fromDeg}deg)` },
      { transform: `rotate(${toDeg}deg)` },
    ], { duration: t.duration, easing: t.easing }));
  }

  /**
   * ``el`` "צומח" מתוך המלבן ``fromRect`` אל המקום שבו הוא כבר נמצא: מתחיל בגודל ובמיקום
   * של ``fromRect``, בפינות של ``fromRadius``, ומגיע לקופסה ולרדיוס האמיתיים שלו. מחזיר את
   * האנימציה, או ``null`` כשאין ממה לצמוח.
   *
   * **הרדיוס מתוקן לפי ההגדלה.** ``scale`` מכווץ גם את הפינות, ולכן רדיוס שצריך להיראות
   * ``r`` כשהאלמנט מוקטן פי ``sx`` רוחבית ו-``sy`` לגובה נכתב כאליפסה ``r/sx / r/sy``.
   * הרדיוס הסופי נקרא מהפינה העליונה של ``el``: הפונקציה מניחה אלמנט שכל פינותיו שוות.
   */
  function morphFromRect(el, fromRect, fromRadius, timing) {
    const t = timing || {};
    if (!canAnimate(el) || !fromRect || !fromRect.width || !fromRect.height) return null;
    const box = el.getBoundingClientRect();
    if (!box.width || !box.height) return null;
    const d = rectDelta(box, fromRect);
    const r = Number(fromRadius) || 0;
    const finalRadius = window.getComputedStyle(el).borderTopLeftRadius;
    return el.animate([
      {
        transform: `translate(${d.dx}px, ${d.dy}px) scale(${d.sx}, ${d.sy})`,
        borderRadius: `${r / d.sx}px / ${r / d.sy}px`,
      },
      { transform: 'none', borderRadius: finalRadius },
    ], { duration: t.duration, easing: t.easing });
  }

  window.AnimUtils = window.AnimUtils || {};
  window.AnimUtils.MOTION = MOTION;
  window.AnimUtils.prefersReducedMotion = prefersReducedMotion;
  window.AnimUtils.canAnimate = canAnimate;
  window.AnimUtils.rectDelta = rectDelta;
  window.AnimUtils.play = play;
  window.AnimUtils.menuMotion = menuMotion;
  window.AnimUtils.cascadeMenu = cascadeMenu;
  window.AnimUtils.byDistanceFrom = byDistanceFrom;
  window.AnimUtils.cascadeFrom = cascadeFrom;
  window.AnimUtils.animateHeight = animateHeight;
  window.AnimUtils.rotationOf = rotationOf;
  window.AnimUtils.rotateFrom = rotateFrom;
  window.AnimUtils.morphFromRect = morphFromRect;
})();
