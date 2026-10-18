(function () {
  'use strict';

  // התפריט עוקב אחרי הסעיף שקוראים בו. כשכותרת של סעיף עוברת את קו הקריאה, הפריט
  // שלו בתפריט מסומן. כל עוד הפריט המסומן נראה בתפריט, התפריט לא זז. כשהוא יוצא
  // מהתצוגה, רק התפריט נגלל, כך שהפריט יהיה באמצע.
  // זו ההתנהגות של תוכן העניינים הצף ב-WebApp (updateActiveItem ב-
  // webapp/templates/md_preview.html). העותק כאן הכרחי, כי אתר התיעוד לא טוען קוד
  // של ה-WebApp. ההבדלים ממנו:
  // - במקום scrollIntoView משנים את scrollTop של התפריט. scrollIntoView גולל כל אב שאפשר
  //   לגלול, ומה שהוא עושה תלוי בפריסה. בערכה הזו התפריט קבוע במסך, ולכן גם הוא לא היה
  //   מזיז את העמוד (18.10.2026: מוטציה כזו עוברת את tests/test_docs_nav_follow_browser.py),
  //   אבל scrollTop לא תלוי בזה.
  // - התפריט קופץ מיד, בלי גלילה חלקה: scrollDelta בודק איפה הפריט עכשיו, ובאמצע אנימציה
  //   התשובה היא מקום שהתפריט עוד עובר בו.
  // - בסוף העמוד קו הקריאה יורד (readLine). בלי זה הסעיפים האחרונים בעמוד לא מסומנים אף
  //   פעם, כי העמוד נגמר לפני שהכותרת שלהם מגיעה לקו.
  // sticky_navigation של הערכה כבוי ב-docs/conf.py, וההסבר שם.

  const MENU_SELECTOR = '.wy-menu-vertical';
  const SCROLLER_SELECTOR = '.wy-side-scroll';
  const ACTIVE_CLASS = 'doc-nav-active';
  // כותרת נחשבת "נקראת" מרגע שהיא עוברת את החמישית העליונה של המסך: הקצה העליון של
  // הרצועה ב-CONFIG.INTERSECTION_MARGIN של תוכן העניינים ב-md_preview.html.
  // tests/docs-nav-follow.test.js נכשל כששני הערכים נפרדים.
  const READ_LINE_RATIO = 0.2;

  /**
   * האינדקס של הסעיף שקוראים בו: מבין הסעיפים שהכותרת שלהם כבר עברה את הקו, זה
   * שהכי קרוב אליו. סעיף מקונן מתחיל אחרי ההורה שלו, ולכן הוא מנצח אותו. ‎-1 כשאף
   * סעיף לא עבר את הקו, למשל בראש העמוד, לפני תת-הסעיף הראשון.
   */
  const pickActive = (tops, line) => {
    let best = -1;
    for (let i = 0; i < tops.length; i += 1) {
      if (tops[i] <= line && (best === -1 || tops[i] > tops[best])) {
        best = i;
      }
    }
    return best;
  };

  /**
   * קו הקריאה, בפיקסלים מראש המסך. ברוב העמוד הוא בחמישית העליונה. בקטע האחרון של
   * הגלילה, באורך החלק של המסך שמתחת לקו, הוא יורד בהדרגה עד תחתית המסך: הכותרות שם לא
   * יכולות לעלות עד החמישית העליונה, כי העמוד נגמר לפני כן, וכך הן עוברות את הקו אחת
   * אחרי השנייה, לפי הסדר. בתחתית העמוד כל כותרת שעל המסך כבר עברה אותו.
   * maxScroll הוא כמה אפשר לגלול את העמוד בסך הכול, ו-scrolled כמה כבר נגלל.
   */
  const readLine = (viewHeight, maxScroll, scrolled) => {
    const base = viewHeight * READ_LINE_RATIO;
    const stretch = Math.min(viewHeight - base, maxScroll);
    const remaining = Math.max(maxScroll - scrolled, 0);
    if (stretch <= 0 || remaining >= stretch) {
      return base;
    }
    return base + (viewHeight - base) * (1 - remaining / stretch);
  };

  /**
   * בכמה לגלול את התפריט כדי שהפריט יהיה באמצע, או ``null`` כשהפריט כבר נראה
   * בשלמותו. שני המלבנים נמדדים יחסית למסך, ולכן ההפרש נכון בלי קשר לגלילה.
   */
  const scrollDelta = (item, box) => {
    if (item.top >= box.top && item.bottom <= box.bottom) {
      return null;
    }
    return item.top - box.top - (box.height - item.height) / 2;
  };

  const isShown = (element) => element.getClientRects().length > 0;

  // פריט בתת-עץ מקופל אינו מוצג: הערכה מציגה את תתי-הסעיפים רק של פריט שנבחר
  // (.toctree-l1.current .toctree-l2 > ul ב-theme.css). אז מסמנים את הפריט המוצג הקרוב
  // שמעליו בעץ.
  const shownLink = (link) => {
    let current = link;
    while (current && !isShown(current)) {
      const item = current.closest('li');
      const parentItem = item && item.parentElement ? item.parentElement.closest('li') : null;
      current = parentItem ? parentItem.querySelector(':scope > a') : null;
    }
    return current;
  };

  const init = () => {
    const menu = document.querySelector(MENU_SELECTOR);
    const scroller = document.querySelector(SCROLLER_SELECTOR);
    if (!menu || !scroller) {
      return;
    }
    // הסעיפים של העמוד הזה הם הקישורים המקומיים בתפריט (#id). קישור לעמוד אחר
    // (page.html#id) אינו סעיף בעמוד הזה.
    const targets = [];
    menu.querySelectorAll('a[href^="#"]').forEach((link) => {
      const section = document.getElementById(link.getAttribute('href').slice(1));
      if (section) {
        targets.push({ link, section });
      }
    });
    if (!targets.length) {
      return;
    }

    let active = null;
    let scheduled = false;
    const update = () => {
      scheduled = false;
      const index = pickActive(
        targets.map((target) => target.section.getBoundingClientRect().top),
        readLine(window.innerHeight, document.documentElement.scrollHeight - window.innerHeight, window.scrollY),
      );
      const link = index === -1 ? null : shownLink(targets[index].link);
      if (link === active) {
        // אותו פריט: התפריט לא זז, גם אם גללו אותו ביד בינתיים
        return;
      }
      if (active) {
        active.classList.remove(ACTIVE_CLASS);
      }
      active = link;
      if (!active) {
        return;
      }
      active.classList.add(ACTIVE_CLASS);
      const delta = scrollDelta(active.getBoundingClientRect(), scroller.getBoundingClientRect());
      if (delta !== null) {
        scroller.scrollTop += delta;
      }
    };
    const schedule = () => {
      if (!scheduled) {
        scheduled = true;
        window.requestAnimationFrame(update);
      }
    };
    window.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', schedule);
    update();
  };

  // לבדיקות: ההחלטות, בלי DOM (tests/docs-nav-follow.test.js). קו הקריאה משמש גם את
  // tests/test_docs_nav_follow_browser.py, שמחשב ממנו את הסעיף שצריך להיות מסומן.
  window.DocNavFollow = { pickActive, scrollDelta, readLine, READ_LINE_RATIO };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
