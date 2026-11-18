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
   * התזמונים של כל אנימציה שעוברת כאן — המקום היחיד שבו הם כתובים. המספרים והעקומות
   * נלקחו מהפתק "אנימציות לCk" (רכיבי React: ``sidebar-collapse``, ``spring-dropdown``,
   * ``expand-card``, ``morph-popover``). ``step`` הוא ההשהיה בין פריט לפריט, ו-``maxIndex``
   * עוצר את ההשהיה המצטברת, כדי שרשימה ארוכה לא תיכנס במשך שניות. עקומה שה-y שלה מעל 1
   * היא שעושה את הקפיץ: התנועה עוברת מעט את היעד וחוזרת.
   */
  const MOTION = Object.freeze({
    noteFold: Object.freeze({ duration: 500, easing: 'cubic-bezier(.2, 1.3, .3, 1)' }),
    noteContent: Object.freeze({ duration: 250, easing: 'ease' }),
    menuItem: Object.freeze({ duration: 500, easing: 'cubic-bezier(.2, 1.5, .3, 1)', step: 55 }),
    menuItemFade: Object.freeze({ duration: 250, easing: 'ease', step: 55 }),
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
    const anim = el.animate([first, last], { duration: t.duration, easing: t.easing });
    heightAnims.set(el, anim);
    const forget = () => {
      if (heightAnims.get(el) === anim) heightAnims.delete(el);
    };
    // ``finished`` נדחה ב-``AbortError`` כשהאנימציה מבוטלת (MDN, ``Animation.cancel()``) —
    // וזה בדיוק המקרה של לחיצה חוזרת, שכבר רשמה במקומה אנימציה חדשה. אין כאן כשל לדווח.
    anim.finished.then(forget, forget);
    return anim;
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
  window.AnimUtils.animateHeight = animateHeight;
  window.AnimUtils.morphFromRect = morphFromRect;
})();
