Smooth Scrolling (WebApp) — מדריך תמציתי לסוכני AI
===================================================
:summary: מנגנון הגלילה החלקה של ה‑WebApp כבוי כברירת מחדל ואינו מופיע בהגדרות; העמוד מסביר למה, מה נשאר פעיל דרך CSS נייטיבי, ואיך מדליקים אותו לניפוי בלבד.

המצב הנוכחי
-----------
- ``webapp/static/js/smooth-scroll.js`` עדיין נטען גלובלית דרך ``webapp/templates/base.html``, אבל **``enabled`` הוא ``false`` כברירת מחדל**. כשהוא כבוי המודול לא רושם שום מאזין — לא ל‑``wheel``, לא למקלדת ולא לקליקים על קישורי עוגן — ואינו מאתחל את התאמות האנדרואיד.
- **הכרטיס "גלילה חלקה" הוסר ממסך ``/settings``.** אין עוד ממשק משתמש שמדליק את המנגנון.
- **ההעדפה השמורה כבר לא שולטת בהפעלה.** ``loadPreferences`` קוראת מ‑``localStorage`` (``smoothScrollPrefs``) רק את ערכי הכוונון — משך, easing, רגישויות — ומתעלמת מהמפתח ``enabled``; ``savePreferences`` אינה כותבת אותו. בלי זה "כבוי כברירת מחדל" היה נכון רק למשתמש חדש: מי שהדליק את הכרטיס בעבר היה ממשיך לקבל את המנגנון מההעדפה הישנה.
- ``POST /api/ui_prefs`` עם ``smooth_scroll`` עדיין נשלח מ‑``savePreferences`` כניסיון best‑effort, אבל ``api_ui_prefs`` ב‑``webapp/app.py`` אינו מטפל במפתח הזה ומתעלם ממנו. השרת מעולם לא שמר את ההעדפה הזו.

למה כבוי
--------
המאזין לקישורי עוגן (``onAnchorClick``) ביטל את התנהגות הדפדפן (``preventDefault``) וגלל באנימציה משלו — **בלי לכתוב את העוגן לכתובת**. התוצאה בכל עמוד: לחיצה על ``<a href="#section">`` גללה, אבל ``location.hash`` לא השתנה. לכן Back לא חזר לנקודה הקודמת, ``:target`` ב‑CSS לא נדלק, כתובת שהועתקה לא נחתה על המקטע, ו‑``hashchange`` — ש‑``base.html`` נשען עליו כדי לשמור את הכתובת האחרונה — לא ירה. הדפדפנים והמכשירים של היום נותנים גלילה חלקה בעצמם, ולכן במקום לתקן מנגנון שאין בו צורך הוא הוצא מהדרך.

מה נשאר פעיל
------------
- ``webapp/static/css/smooth-scroll.css`` נטען כרגיל. הוא מגדיר ``html { scroll-behavior: smooth }`` — גלילה חלקה **נייטיבית** של הדפדפן לעוגנים ול‑``scrollIntoView``, שכן מעדכנת את הכתובת ומכבדת ``prefers-reduced-motion`` דרך ה‑media query שבאותו קובץ.
- אותו קובץ CSS מכיל גם את כללי ה‑``.modal`` ש‑``compare.html`` נשען עליהם (``jobs_monitor.html`` ו‑``theme_builder.html`` נמנעים מהמחלקה הזו בגלל זה). **אין להסיר את הקובץ.**

הדלקה לניפוי בלבד
-----------------
ההדלקה תקפה לסשן הנוכחי של הדפדפן ואינה נשמרת:

- הוסיפו ``smooth_debug=1`` לכתובת (למשל ``/?smooth_debug=1``). נפתחת חלונית שמציגה אם ``prefers-reduced-motion`` פעיל ואם המנגנון דולק, עם כפתור הפעלה/כיבוי וכפתור למחיקת ההעדפה השמורה.
- או מהקונסול:

.. code-block:: js

   window.smoothScroll.enable();
   window.smoothScroll.updateConfig({ duration: 300, easing: 'ease-out', offset: 80 });
   window.smoothScroll.smoothScrollTo('#section-2', { duration: 400 });

``enable()`` מכבד ``prefers-reduced-motion`` — אם ההעדפה פעילה במערכת ההפעלה, המנגנון נשאר כבוי גם אחרי הקריאה.

מה המודול עדיין יודע לעשות כשמדליקים אותו
------------------------------------------
אנימציית גלילה לגלגלת, למקלדת (PageUp/Down, Home/End, חיצים) ולקישורי עוגן; התאמות אנדרואיד (מאזיני ``touch`` פסיביים, momentum ובוסטר אינרציה, התאמות Samsung Internet, ניטור FPS שמקצר אנימציה בעומס); ו‑``updateConfig`` לכוונון משך, easing, offset ורגישויות. הכוונון נשמר ב‑``localStorage`` תחת ``smoothScrollPrefs`` — בלי ``enabled``.

הנחיות לסוכני AI
-----------------
- אל תניחו שהמנגנון פעיל: ``Boolean(window.smoothScroll?.config?.enabled)`` הוא ``false`` בברירת המחדל.
- קישור עוגן חדש הוא ``<a href="#id">`` רגיל. אין צורך ב‑JavaScript, ואין לעקוף את הדפדפן: הוא מנווט, כותב את הכתובת וגולל חלק בזכות ה‑CSS.
- אם צריך גלילה תכנותית — ``element.scrollIntoView({ block: 'start' })`` מספיק; ה‑CSS הופך אותה לחלקה.
- אל תוסיפו מאזיני ``wheel``/``touch`` גלובליים ואל תדליקו את המנגנון מקוד ייצור. ההדלקה היא כלי ניפוי.

קישורים פנימיים
----------------
- קוד: ``webapp/static/js/smooth-scroll.js`` | ``webapp/static/css/smooth-scroll.css`` | ``webapp/templates/base.html``
- מוסכמות CSS וטסטי דפדפן: :doc:`theming_and_css`
