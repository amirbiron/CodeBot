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
})();
