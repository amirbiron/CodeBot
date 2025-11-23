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
- אנדרואיד (בסיס):
  - מאזיני ``touch`` ב‑``{passive: true}``
  - Momentum עדין לאחר שחרור האצבע (רק אם אין אינרציה נייטיבית)
  - התאמות Samsung Internet (מניעת ``scroll-behavior`` כפול)
  - כוונון משך האנימציה בעת FPS נמוך (מניעת jank)

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
- Passive touch listeners
- Momentum עדין (רק אם אין אינרציה נייטיבית)
- התאמות Samsung Internet למניעת כפילות גלילה חלקה
- ניטור FPS קליל המכוון משך/אופי אנימציה בזמן ריצה

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
  - ודאו שהקריאה היא דרך ``updateConfig`` ושקיים ``window.smoothScroll``.
- “משתמש עם Reduced Motion עדיין רואה אנימציות”:
  - בדקו את העדפת המערכת (DevTools > Rendering > Emulate CSS prefers-reduced-motion).

תוכנית המשך (Roadmap מקוצר)
---------------------------
- CodeMirror: גלילה חלקה בתוך העורך ו‑Jump to line
- TOC חכם: שימוש ב‑offset, Smart Scrolling, Active item
- UI מודאל להגדרות משתמש (מהירות/easing/רגישות)
- ניטור מתקדם (PerformanceObserver + Analytics)
- אופטימיזציות WebView ו‑Virtual Scrolling לרשימות ארוכות

קישורים פנימיים
----------------
- קוד: ``webapp/static/js/smooth-scroll.js`` | ``webapp/static/css/smooth-scroll.css`` | ``webapp/templates/base.html``
- API: ``POST /api/ui_prefs`` (עדכון העדפות UI, Best‑effort בלבד)

