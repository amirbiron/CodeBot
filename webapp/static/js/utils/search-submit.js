/**
 * תיבת חיפוש שמחפשת רק כשלוחצים אנטר — תשובה אחת לשאלה "מתי החיפוש רץ".
 *
 * משותף לחיפוש במסמך (``md_preview.html``) ולחיפוש בקוד (``view_file.html``),
 * שבו שני מנועים — התצוגה הבסיסית ו-CodeMirror בתצוגה המתקדמת. הרשימה המלאה
 * אינה כתובה כאן: בדיקת החיווט ב-``tests/search-submit.test.js`` גוזרת אותה מהקוד.
 * לפני הקובץ הזה כל אחד משלושת המקומות החזיק את הכלל בעצמו, וכולם חיפשו בכל
 * הקלדה. בתצוגת הקוד המאזינים של אנטר ושל ▼ אף היו רשומים פעמיים, ולכן כל
 * לחיצה קידמה שתי התאמות (ממצא 1 ב-#3477).
 *
 * **הכלל:**
 * - אנטר על טקסט שעוד לא חיפשו ← חיפוש (``search``). אנטר שוב על אותו טקסט ←
 *   ההתאמה הבאה (``next``), ו-Shift+Enter ← הקודמת (``prev``).
 * - ▼ ו-▲ על טקסט שעוד לא חיפשו ← חיפוש, כמו אנטר: גם הם לחיצה מכוונת.
 * - שינוי של הטקסט אחרי חיפוש מנקה מיד את ההדגשות והמונה (``reset``) — הן שייכות
 *   לטקסט הקודם. כמו בתיבת החיפוש של דפדפן הריפו, שמסתירה תוצאות שאינן
 *   של הטקסט שבתיבה (``initSearch`` ב-``repo-browser.js``).
 * - ✕ מרוקן את התיבה ומנקה.
 * - "אותו טקסט" נקבע אחרי ``trim``: רווח בסוף אינו טקסט חדש.
 *
 * **אנטר בזמן הרכבה של מקלדת IME שייך להרכבה, ולא לחיפוש** — ``isComposing``
 * או ``keyCode === 229``, אותה בדיקה של החיפוש בתוך פתק (``sticky-notes.js``),
 * לפי MDN, ‏"Element: keydown event". אנטר כזה מאשר מילה שעוד לא הושלמה, ולכן
 * אינו מחפש ואינו נחסם (בלי ``preventDefault``).
 *
 * **ו-``submitted`` נקבע רק אחרי ש-``search`` חזר בלי חריגה.** מנוע שזרק השאיר
 * חיפוש שלא קרה, ואנטר נוסף צריך לנסות לחפש שוב — לא לעבור "להתאמה הבאה".
 *
 * הקובץ הזה אינו יודע דבר על הדגשה, ספירה או גלילה: אלה של המנוע שמועבר
 * אליו. ואין בו ``innerHTML``.
 */
(function () {
  'use strict';

  /**
   * מחבר תיבת חיפוש לכלל. מחזיר בקר עם ``submitted`` (מה שחיפשו בפועל, או
   * ``''``) ו-``rerun()`` — חיפוש מחדש של אותו טקסט, למשל אחרי שהתוכן שמוצג
   * הוחלף. ``rerun`` אינו קורא את התיבה, ולכן טקסט שהוקלד ועוד לא חיפשו לא
   * יחופש דרכו.
   *
   * @param {{input: HTMLInputElement, search: function(string), next: function(),
   *          prev: function(), reset: function(), nextBtn?: Element,
   *          prevBtn?: Element, clearBtn?: Element}} opts
   */
  function bind(opts) {
    var o = opts || {};
    ['search', 'next', 'prev', 'reset'].forEach(function (name) {
      if (typeof o[name] !== 'function') {
        throw new TypeError('SubmitSearch.bind: ' + name + ' חייב להיות פונקציה');
      }
    });
    if (!o.input || typeof o.input.addEventListener !== 'function') {
      throw new TypeError('SubmitSearch.bind: input חסר');
    }
    var input = o.input;
    var submitted = '';

    function current() {
      return String(input.value || '').trim();
    }

    function submit(term) {
      o.search(term);
      submitted = term;
    }

    function step(direction) {
      var term = current();
      if (!term) return;
      if (term !== submitted) {
        submit(term);
        return;
      }
      if (direction > 0) o.next(); else o.prev();
    }

    input.addEventListener('keydown', function (ev) {
      if (ev.key !== 'Enter') return;
      if (ev.isComposing || ev.keyCode === 229) return;
      ev.preventDefault();
      step(ev.shiftKey ? -1 : 1);
    });

    input.addEventListener('input', function () {
      if (submitted && current() !== submitted) {
        submitted = '';
        o.reset();
      }
    });

    if (o.nextBtn) o.nextBtn.addEventListener('click', function () { step(1); });
    if (o.prevBtn) o.prevBtn.addEventListener('click', function () { step(-1); });
    if (o.clearBtn) {
      o.clearBtn.addEventListener('click', function () {
        input.value = '';
        submitted = '';
        o.reset();
      });
    }

    return Object.freeze({
      get submitted() { return submitted; },
      rerun: function () {
        if (submitted) o.search(submitted); else o.reset();
      },
    });
  }

  window.SubmitSearch = Object.freeze({ bind: bind });
})();
