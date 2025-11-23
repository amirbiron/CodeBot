Smooth Scrolling (WebApp) — מדריך תמציתי לסוכני AI
===================================================

מדריך זה מסביר את יכולות הגלילה החלקה שהוטמעו ב‑WebApp, כיצד להשתמש בהן באופן בטוח, ומה הדגשים לסוכני AI כדי לשמור על נגישות וביצועים.

מה פעיל כבר
-----------
- טעינה גלובלית של רכיבי הגלילה:
  - ``webapp/static/js/smooth-scroll.js`` (מנגנון JS)
  - ``webapp/static/css/smooth-scroll.css`` (סגנונות בסיס + נגישות)
  - משולב אוטומטית דרך ``webapp/templates/base.html``
- תמיכה בכניסות קלט:
  - Wheel/Trackpad (גלגלת) עם אנימציה חלקה
  - מקלדת: PageUp/Down, Home/End, חיצים
  - קישורי עוגן (Anchor Links) עם גלילה חלקה
- נגישות:
  - כיבוד ``prefers-reduced-motion: reduce`` — אנימציות מקוצרות/מכובות
  - Fallback של ``scroll-behavior: smooth`` כאשר JS לא זמין
- אנדרואיד (מורחב):
  - מאזיני ``touch`` ב‑``{passive: true}`` + דגימת מהירות בזמן אמת
  - Momentum משופר + בוסטר אינרציה כאשר אין אינרציה נייטיבית
  - הזרקת מחלקות ``android-optimized`` / ``android-no-bounce`` לאיפוס overscroll
  - התאמות Samsung Internet (מניעת ``scroll-behavior`` כפול)
  - ניטור FPS שמקצר משך אנימציה בעת עומס
  - כרטיס "גלילה חלקה" במסך ההגדרות מאפשר לכוון משך, easing ורגישות (וקיים בכל פלטפורמה)

API לשימוש קליינט
------------------
- הפעלה/כיבוי:

.. code-block:: js

   window.smoothScroll.enable();
   window.smoothScroll.disable();

- עדכון הגדרות בזמן ריצה:

.. code-block:: js

   window.smoothScroll.updateConfig({
     duration: 300,              // ms
     easing: 'ease-out',         // 'linear' | 'ease-in' | 'ease-out' | 'ease-in-out'
     offset: 80,                 // px, למשל Sticky Header
     wheelSensitivity: 1.0,      // 0.1–3
     keyboardSensitivity: 1.5    // 0.5–3
   });

- גלילה לאלמנט/סלקטור:

.. code-block:: js

   window.smoothScroll.smoothScrollTo('#section-2', {
     offset: 80,
     duration: 400,
     easing: 'ease-in-out'
   });

שמירת העדפות
-------------
- השמירה מתבצעת ל‑``localStorage`` תחת ``smoothScrollPrefs``.
- ניסוי שליחה עדינה לשרת (אם קיים API): ``POST /api/ui_prefs`` עם ``{ smooth_scroll: {...} }``.
- כישלון שרת אינו חוסם — אין תלות בבקשת ה‑POST.

- ממשק הגדרות מובנה
-------------------
- במסך ``/settings`` קיים כרטיס **גלילה חלקה** עם הטפסים הבאים:
  - Toggle הפעלה/כיבוי
  - סליידר משך (150‑1200ms) + בחירת ``easing``
  - רגישות גלגלת/מקלדת (0.5‑3x)
  - סליידר אינרציה לאנדרואיד (10‑60x)
  - כפתורי בדיקה/איפוס/שמירה
- ניתן עדיין לפתוח חלונית debug באמצעות הוספת ``smooth_debug=1`` ל‑URL לצורך ניטור מהיר.
- שליטה תכנותית קיימת דרך הקונסול באמצעות ``updateConfig``:

.. code-block:: js

   window.smoothScroll.updateConfig({
       duration: 350,
       wheelSensitivity: 1.2
   });

הנחיות לסוכני AI
-----------------
- זיהוי מהיר של זמינות:

.. code-block:: js

   const supported = Boolean(window.smoothScroll?.config?.enabled);

- הימנעו מאזיני ``wheel/touch`` כפולים: המערכת מאזינה גלובלית כברירת מחדל.
- כבדו נגישות: אם ``prefers-reduced-motion`` פעיל — אל תוסיפו אנימציות ידניות.
- לכוונון — השתמשו ב‑``updateConfig`` ולא בכתיבה ישירה ל‑``localStorage``.
- שמרו על ביצועים: אל תוסיפו לולאות polling/``setInterval`` כבדות; העדיפו ``requestAnimationFrame``.

אנדרואיד — מה יש ומה לא
------------------------
הוטמעו:
- Passive touch listeners + דגימת מהירות
- Momentum יזום עם בוסטר אינרציה וכיול ``friction``/``threshold``
- התאמות Samsung Internet ו‑overscroll (``android-optimized``)
- ניטור FPS שמכוונן משך/עקומת אנימציה
- UI מובנה לקביעת עוצמת אינרציה ומשך

לא הוטמעו (ייעשה בשלבים הבאים):
- אופטימיזציות WebView מתקדמות (lazy, IntersectionObserver מותאם)
- A/B test לניהול פרופילי ביצועים ספציפיים לדפדפנים

נגישות וביצועים
----------------
- נגישות:
  - ``prefers-reduced-motion: reduce`` מבטל/מקצר אנימציה.
  - גלילה לעוגנים מכבדת ``offset`` לכותרות ``sticky``.
- ביצועים:
  - Throttle ל‑``wheel`` סביב 16ms
  - שימוש ב‑``requestAnimationFrame`` לכל האנימציות
  - ב‑Android, קיצור משך אנימציה אם FPS ירוד

פתרון תקלות
------------
- “גלילה עדיין קופצת ב‑Samsung”:
  - נבדק UA לזיהוי Samsung; מוודאים ש‑``document.documentElement.style.scrollBehavior = 'auto'`` הופעל.
- “אין השפעה לשינוי הגדרות”:
  - ודאו שהקריאה היא דרך ``updateConfig`` / כרטיס ההגדרות ב‑``/settings`` ושקיים ``window.smoothScroll``.
- “משתמש עם Reduced Motion עדיין רואה אנימציות”:
  - בדקו את העדפת המערכת (DevTools > Rendering > Emulate CSS prefers-reduced-motion).
- “אני לא בטוח אם הפיצ'ר פועל”:
  - הוסיפו ל‑URL את הפרמטר ``smooth_debug=1`` (למשל ``/?smooth_debug=1`` או ``&smooth_debug=1``) כדי לפתוח חלונית בדיקה.
  - החלונית מציגה אם הדפדפן מסמן ``prefers-reduced-motion``, אם המנגנון פעיל, ומאפשרת להפעיל/לכבות או למחוק את ההעדפה שנשמרה ב‑``localStorage``.

תוכנית המשך (Roadmap מקוצר)
---------------------------
- CodeMirror: גלילה חלקה בתוך העורך ו‑Jump to line
- TOC חכם: שימוש ב‑offset, Smart Scrolling, Active item
- ניטור מתקדם (PerformanceObserver + Analytics)
- אופטימיזציות WebView ו‑Virtual Scrolling לרשימות ארוכות

קישורים פנימיים
----------------
- קוד: ``webapp/static/js/smooth-scroll.js`` | ``webapp/static/css/smooth-scroll.css`` | ``webapp/templates/base.html``
- API: ``POST /api/ui_prefs`` (עדכון העדפות UI, Best‑effort בלבד)

