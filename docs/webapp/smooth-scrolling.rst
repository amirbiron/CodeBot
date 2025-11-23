=====================================
Smooth Scrolling - גלילה חלקה
=====================================

.. contents:: תוכן עניינים
   :local:
   :depth: 2

סקירה כללית
============

תכונת הגלילה החלקה (Smooth Scrolling) מספקת חווית משתמש נעימה ומודרנית בעת ניווט במסמכים ועריכת קוד.
התכונה כוללת אנימציות עדינות, תמיכה במגוון התקני קלט, ואפשרויות התאמה אישית נרחבות.

תכונות עיקריות
==============

גלילה בסיסית
------------

* **גלגלת עכבר**: אנימציה חלקה במקום קפיצות
* **Trackpad**: תמיכה ב-two-finger scroll עם momentum
* **מקלדת**: Page Up/Down, Home/End עם אנימציות
* **קישורי עוגן**: גלילה חלקה לקטעים בעמוד

תכונות מתקדמות
--------------

* **Jump to Line**: גלילה מונפשת בעורך הקוד
* **Smart Scrolling**: התאמת מהירות אוטומטית למצב קריאה
* **TOC Navigation**: גלילה חכמה בתפריט הניווט
* **Overscroll Bounce**: אפקט iOS-style בקצוות העמוד

הגדרות משתמש
============

פתיחת חלון ההגדרות
------------------

.. code-block:: javascript

   // לחיצה על כפתור ההגדרות בסרגל הכלים
   document.getElementById('scrollSettingsBtn').click();
   
   // או קריאה ישירה לפונקציה
   openScrollSettings();

אפשרויות הגדרה
-------------

.. list-table:: הגדרות זמינות
   :header-rows: 1
   :widths: 20 30 50

   * - הגדרה
     - ערכים
     - תיאור
   * - הפעלה
     - on/off
     - הפעלה או כיבוי של התכונה
   * - מהירות
     - 200-800ms
     - משך האנימציה
   * - Easing
     - linear/ease-in-out/elastic
     - סוג האנימציה
   * - רגישות עכבר
     - 0.1-3.0
     - מכפיל למהירות גלילה
   * - רגישות מקלדת
     - 0.5-3.0
     - מכפיל לקפיצות מקלדת

שמירת העדפות
------------

ההעדפות נשמרות אוטומטית ב:

1. **localStorage**: לטעינה מהירה
2. **Server API**: לסנכרון בין מכשירים

.. code-block:: javascript

   // העדפות נשמרות אוטומטית בשינוי
   window.smoothScroll.updateConfig({
     duration: 500,
     easing: 'ease-in-out'
   });

API למפתחים
===========

אובייקט SmoothScrollManager
-------------------------

.. code-block:: javascript

   // אובייקט גלובלי זמין
   window.smoothScroll
   
   // Methods
   smoothScroll.enable()                    // הפעלה
   smoothScroll.disable()                   // כיבוי
   smoothScroll.smoothScrollTo(target)      // גלילה לאלמנט
   smoothScroll.smoothScrollBy(distance)    // גלילה לפי מרחק
   smoothScroll.updateConfig(config)        // עדכון הגדרות

גלילה לאלמנט ספציפי
-------------------

.. code-block:: javascript

   // גלילה לאלמנט עם ID
   window.smoothScroll.smoothScrollTo('#section-2', {
     offset: 80,        // הזחה מהחלק העליון
     duration: 500,     // משך האנימציה
     easing: 'ease-out', // סוג אנימציה
     callback: () => {   // פונקציה לאחר סיום
       console.log('Scroll completed');
     }
   });
   
   // גלילה לאלמנט DOM
   const element = document.querySelector('.target');
   window.smoothScroll.smoothScrollTo(element);

אינטגרציה עם CodeMirror
-----------------------

.. code-block:: javascript

   // Jump to line עם אנימציה
   window.CodeMirrorSmoothScroll.jumpToLine(view, 150);
   
   // הוספת extension לעורך חדש
   const extensions = [
     ...basicSetup,
     ...setupCodeMirrorSmoothScroll(view)
   ];

קיצורי מקלדת
============

.. list-table:: קיצורי מקלדת נתמכים
   :header-rows: 1

   * - קיצור
     - פעולה
   * - Page Up
     - עמוד אחד למעלה
   * - Page Down
     - עמוד אחד למטה
   * - Home
     - תחילת העמוד
   * - End
     - סוף העמוד
   * - Space
     - עמוד למטה (Shift+Space למעלה)
   * - Arrow Up/Down
     - גלילה עדינה

נגישות
======

תמיכה ב-Screen Readers
---------------------

* הודעות ARIA על מיקום גלילה
* תמיכה ב-``role="status"`` להודעות
* שמירת פוקוס לאחר גלילה

Reduced Motion
-------------

משתמשים עם העדפת ``prefers-reduced-motion`` יקבלו:

* ביטול אוטומטי של אנימציות
* גלילה מיידית ללא השהייה
* שמירת פונקציונליות מלאה

.. code-block:: css

   @media (prefers-reduced-motion: reduce) {
     * {
       scroll-behavior: auto !important;
       transition-duration: 0.01ms !important;
     }
   }

ביצועים
=======

אופטימיזציות
-----------

1. **GPU Acceleration**: שימוש ב-transform ו-will-change
2. **Throttling**: הגבלת events ל-60fps
3. **Passive Listeners**: לשיפור ביצועים ב-touch
4. **Virtual Scrolling**: לרשימות ארוכות

מדדי ביצועים
-----------

* **FPS**: יעד של 60fps קבוע
* **Input Latency**: < 50ms
* **Jank**: < 5% מהפריימים
* **Battery**: < 5% עלייה בצריכה

פתרון בעיות
===========

בעיות נפוצות
-----------

.. list-table:: 
   :header-rows: 1

   * - בעיה
     - פתרון
   * - גלילה לא חלקה
     - בדוק הגדרות GPU בדפדפן
   * - אנימציה איטית
     - הקטן את ערך duration
   * - התנגשות עם ספריות אחרות
     - כבה את התכונה זמנית
   * - לא שומר העדפות
     - בדוק הרשאות localStorage

Debug Mode
---------

.. code-block:: javascript

   // הפעלת מצב דיבאג
   window.smoothScroll.debug = true;
   
   // יציג בקונסול:
   // - זמני אנימציה
   // - ערכי גלילה
   // - אירועי input

דוגמאות קוד
==========

גלילה מותאמת אישית
------------------

.. code-block:: javascript

   // יצירת מנהל גלילה עם הגדרות מותאמות
   const customScroller = new SmoothScrollManager({
     duration: 600,
     easing: 'cubic-bezier',
     wheelSensitivity: 0.5,
     enabled: true
   });
   
   // גלילה לקטע ספציפי
   document.querySelectorAll('.section-link').forEach(link => {
     link.addEventListener('click', (e) => {
       e.preventDefault();
       const target = e.target.getAttribute('href');
       customScroller.smoothScrollTo(target, {
         offset: 100,
         callback: () => {
           // עדכון URL
           history.pushState(null, null, target);
         }
       });
     });
   });

אינדיקטור התקדמות
----------------

.. code-block:: javascript

   // הוספת אינדיקטור התקדמות גלילה
   function updateScrollProgress() {
     const scrolled = window.pageYOffset;
     const maxScroll = document.documentElement.scrollHeight - window.innerHeight;
     const progress = (scrolled / maxScroll) * 100;
     
     document.querySelector('.scroll-progress').style.transform = 
       `scaleX(${progress / 100})`;
   }
   
   // עדכון בזמן גלילה
   window.addEventListener('scroll', 
     window.smoothScroll.throttle(updateScrollProgress, 16)
   );

תמיכה באנדרואיד
===============

שיפורים ספציפיים למכשירי אנדרואיד
--------------------------------

התכונה כוללת אופטימיזציות מיוחדות למכשירי אנדרואיד:

**בעיות שנפתרות:**

* גלילה מקוטעת (Jittery scrolling)
* השהיית מגע (Touch lag)
* בעיות אינרציה (Momentum issues)
* ביצועי WebView גרועים
* Overscroll bounce לא רצוי

**אופטימיזציות אוטומטיות:**

.. code-block:: javascript

   // המערכת מזהה אנדרואיד אוטומטית
   if (isAndroid) {
     // Hardware acceleration
     // Passive touch listeners
     // Optimized momentum scrolling
     // Transform-based animations
   }

**דפדפנים נתמכים באנדרואיד:**

.. list-table::
   :header-rows: 1

   * - דפדפן
     - תמיכה
     - הערות
   * - Chrome
     - מלאה ✅
     - ביצועים מיטביים
   * - Firefox
     - טובה ✅
     - מעט איטי מ-Chrome
   * - Samsung Internet
     - מותאמת ✅
     - אופטימיזציות מיוחדות
   * - WebView
     - בסיסית ✅
     - Virtual scrolling אוטומטי
   * - Opera
     - טובה ✅
     - דומה ל-Chrome

**הגדרות מומלצות לאנדרואיד:**

* מהירות גלילה: 300ms (מהירה יותר)
* Easing: ease-out (חלק יותר)
* רגישות מגע: 1.2x (גבוהה יותר)
* Momentum: מופעל
* Overscroll bounce: מכובה

מגבלות ידועות
============

* **Safari iOS**: תמיכה חלקית ב-smooth behavior
* **Firefox Android < 68**: ביצועים מופחתים
* **IE11**: אין תמיכה (fallback ל-גלילה רגילה)
* **Android 4.x**: תמיכה בסיסית בלבד

עדכונים עתידיים
==============

* תמיכה ב-horizontal scrolling
* Parallax effects
* Scroll-triggered animations
* Custom easing functions editor
* A/B testing framework

תמיכה
=====

* **Issues**: דווח בעיות ב-GitHub
* **תיעוד מלא**: ראה ``/webapp/FEATURE_SUGGESTIONS/SMOOTH_SCROLLING_GUIDE.md``
* **צוות פיתוח**: webapp-team@codebot.com

.. note::
   
   התכונה נמצאת בפיתוח פעיל. עדכונים ושיפורים מתפרסמים באופן קבוע.

.. warning::
   
   ביטול התכונה עלול להשפיע על תכונות אחרות התלויות בה (כמו TOC navigation).