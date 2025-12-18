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

    itemElement.addEventListener(
      'animationend',
      () => {
        itemElement.classList.remove('is-new');
      },
      { once: true }
    );
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
  } catch (_) {
    // ignore
  }
})();
