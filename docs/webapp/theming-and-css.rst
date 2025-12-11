========================================
מערכת ערכות נושא וטוקני CSS
========================================

.. contents:: תוכן עניינים
   :local:
   :depth: 3

סקירה כללית
===========

מסמך זה מתעד את מערכת ערכות הנושא (Theming) והטוקנים של CSS ב-WebApp של Code Keeper Bot.
הריפקטור שבוצע העביר את המערכת מצבעים "קשיחים" (Hardcoded HEX/RGB) למערכת מבוססת משתני CSS גלובליים (CSS Variables).

למה הריפקטור יצא לדרך?
-----------------------

**תקלות העבר:**

* איבוד התאמות צבעים בתמות קיימות
* "בלגן" שחור-לבן (צבעים לא תואמים בין רכיבים)
* איבוד צבעים ב-``global_search.css`` (צללים ייחודיים לתמות נעלמו)
* בעיית ניגודיות ב-Live Preview

**הצורך:**

* מערכת טוקנים אחידה לכל הרכיבים
* דרישות נגישות (WCAG AA)
* שמירה על ייחודיות כל תמה
* מניעת FOUC (Flash of Unstyled Content)

היתרונות
--------

1. **מניעת FOUC** - הטוקנים נטענים לפני כל CSS חיצוני
2. **תחזוקה פשוטה** - שינוי צבע במקום אחד משפיע על כל הרכיבים
3. **נגישות** - קל לשמור על יחסי ניגודיות
4. **עקביות** - כל 8 התמות משתמשות באותה מערכת

ארכיטקטורה - היררכיית המשתנים
==============================

המערכת בנויה בשלוש שכבות:

.. code-block:: text

   ┌─────────────────────────────────────────────────────────┐
   │  Level 1 – Primitives                                   │
   │  (קבועים לכל הערכות: --glass-blur, --bookmark-yellow)  │
   └─────────────────────────────────────────────────────────┘
                              │
                              ▼
   ┌─────────────────────────────────────────────────────────┐
   │  Level 2 – Semantic Tokens                              │
   │  (משתנים בין ערכות: --bg-primary, --text-primary)      │
   └─────────────────────────────────────────────────────────┘
                              │
                              ▼
   ┌─────────────────────────────────────────────────────────┐
   │  Level 3 – Component Tokens                             │
   │  (ספציפי לרכיבים: --search-card-shadow, --bookmarks-*)  │
   └─────────────────────────────────────────────────────────┘

Level 1 – Primitives (קבועים)
------------------------------

טוקנים שנשארים זהים בכל התמות:

.. code-block:: css

   :root {
     /* קבועים */
     --glass-blur: 10px;
     --radius-sm: 6px;
     --radius-md: 10px;
     --radius-lg: 14px;

     /* צבעי סימניות - קבועים בכל theme */
     --bookmark-yellow: #ffd700;
     --bookmark-red: #ff6b6b;
     --bookmark-green: #51cf66;
     --bookmark-blue: #4dabf7;
     --bookmark-purple: #9775fa;
     --bookmark-orange: #ffa94d;
     --bookmark-pink: #ff69b4;
   }

Level 2 – Semantic Tokens (משתנים בין ערכות)
---------------------------------------------

הטוקנים העיקריים שמגדירים את המראה של כל תמה:

**צבעי בסיס:**

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - משתנה
     - תיאור
   * - ``--primary``
     - צבע ראשי (כפתורים, קישורים)
   * - ``--primary-dark``
     - גרסה כהה יותר של הצבע הראשי
   * - ``--secondary``
     - צבע משני (גרדיאנטים)
   * - ``--success``, ``--danger``, ``--warning``, ``--info``
     - צבעי סטטוס

**רקעים:**

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - משתנה
     - תיאור
   * - ``--bg-primary``
     - רקע ראשי של הדף
   * - ``--bg-secondary``
     - רקע משני
   * - ``--bg-tertiary``
     - רקע שלישוני (אלמנטים מקוננים)
   * - ``--card-bg``
     - רקע כרטיסים
   * - ``--code-bg``
     - רקע בלוקי קוד

**טקסט:**

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - משתנה
     - תיאור
   * - ``--text-primary``
     - צבע טקסט ראשי
   * - ``--text-secondary``
     - צבע טקסט משני
   * - ``--text-muted``
     - צבע טקסט מושתק
   * - ``--text-on-warning``
     - טקסט על רקע warning

**Glass Effects:**

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - משתנה
     - תיאור
   * - ``--glass``
     - רקע שקוף עם blur
   * - ``--glass-border``
     - גבול לאפקט glass
   * - ``--glass-hover``
     - מצב hover לאלמנטים glass

**כפתורים:**

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - משתנה
     - תיאור
   * - ``--btn-primary-bg``
     - רקע כפתור ראשי
   * - ``--btn-primary-color``
     - צבע טקסט בכפתור ראשי
   * - ``--btn-primary-border``
     - גבול כפתור ראשי
   * - ``--btn-primary-shadow``
     - צל כפתור ראשי
   * - ``--btn-primary-hover-bg``
     - רקע כפתור ב-hover
   * - ``--btn-primary-hover-shadow``
     - צל כפתור ב-hover

**Markdown Preview:**

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - משתנה
     - תיאור
   * - ``--md-surface``
     - רקע תצוגה מקדימה
   * - ``--md-text``
     - צבע טקסט בתצוגה מקדימה

Level 3 – Component Tokens
---------------------------

טוקנים ספציפיים לרכיבים מורכבים, כאשר צריך התנהגות שונה מהטוקנים הסמנטיים:

**Search (``global_search.css``):**

* ``--search-card-shadow`` - צל ייחודי לכרטיסי חיפוש
* ``--search-card-shadow-hover`` - צל ב-hover
* ``--search-highlight-bg`` - רקע הדגשת חיפוש
* ``--search-highlight-text`` - צבע טקסט מודגש

**Bookmarks (``bookmarks.css``):**

* ``--bookmarks-panel-bg`` - רקע פאנל סימניות
* ``--bookmarks-panel-shadow`` - צל הפאנל
* ``--bookmarks-hover-bg`` - רקע ב-hover
* ``--bookmarks-border-color`` - צבע גבולות

ערכות הנושא (Themes)
=====================

המערכת תומכת ב-8 ערכות נושא:

.. list-table::
   :header-rows: 1
   :widths: 15 20 15 50

   * - #
     - שם
     - ``data-theme``
     - תיאור
   * - 1
     - Dark
     - ``dark``
     - ברירת מחדל - תמה כהה מודרנית
   * - 2
     - Dim
     - ``dim``
     - כהה רך יותר
   * - 3
     - Nebula
     - ``nebula``
     - גווני כחול/סגול קוסמיים
   * - 4
     - Classic
     - ``classic``
     - הגרדיאנט הסגול המקורי
   * - 5
     - Ocean
     - ``ocean``
     - גרדיאנט כחול עמוק
   * - 6
     - Forest
     - ``forest``
     - גרדיאנט ירוק יער
   * - 7
     - Rose Pine Dawn
     - ``rose-pine-dawn``
     - תמה בהירה ורודה/חמה
   * - 8
     - High Contrast
     - ``high-contrast``
     - נגישות - שחור/לבן/צהוב

.. important::
   אין ``data-theme="default"`` - ברירת המחדל היא פשוט ``:root`` ללא attribute.

פלטות צבעים - טבלת Reference
------------------------------

**צבעי בסיס לפי תמה:**

.. list-table::
   :header-rows: 1
   :widths: 18 14 14 14 14 14 14

   * - משתנה
     - Classic
     - Ocean
     - Forest
     - Dark
     - Nebula
     - Rose Pine
   * - ``--primary``
     - #667eea
     - #3182ce
     - #2f855a
     - #7c8aff
     - #777abc
     - #907aa9
   * - ``--secondary``
     - #764ba2
     - #2c5282
     - #22543d
     - #9d7aff
     - #4d6bb6
     - #d7827e
   * - ``--bg-primary``
     - #6b63ff
     - #1a365d
     - #1a4731
     - #1a1a1a
     - #151a2c
     - #faf4ed
   * - ``--text-primary``
     - #ffffff
     - #ffffff
     - #ffffff
     - #e0e0e0
     - #e6e9f8
     - #575279

High Contrast - שיקולי נגישות
------------------------------

תמת High Contrast עומדת בתקן WCAG 2.1 AA:

.. list-table::
   :header-rows: 1
   :widths: 30 20 20 15 15

   * - אלמנט
     - רקע
     - טקסט
     - יחס ניגודיות
     - תקין?
   * - טקסט רגיל
     - #000000
     - #ffffff
     - 21:1
     - ✅
   * - קישורים
     - #000000
     - #ffff00
     - 19.56:1
     - ✅
   * - קוד - keyword
     - #000000
     - #ff00ff
     - 6.96:1
     - ✅
   * - קוד - string
     - #000000
     - #00ff00
     - 15.3:1
     - ✅

**פלטת הצבעים המאושרת ל-High Contrast:**

``#ffffff``, ``#ffff00``, ``#ffcc00``, ``#ff00ff``, ``#00ff00``, ``#00ffff``, ``#ff0000``, ``#ff9900``

Markdown Preview - טיפול מיוחד
===============================

הבעיה
-----

בתמות בהירות (כמו Classic), עורך הקוד והתצוגה המקדימה צריכים להישאר כהים כדי לשמור על Syntax Highlighting תקין.

הפתרון
------

שימוש בטוקנים ייעודיים ``--md-surface`` ו-``--md-text`` שמוגדרים ככהים **גם כאשר התמה הראשית בהירה**:

.. code-block:: css

   :root[data-theme="classic"] {
     --md-surface: #15141f;  /* רקע כהה */
     --md-text: #e0e0e0;     /* טקסט בהיר */
   }

   :root[data-theme="ocean"] {
     --md-surface: #1a365d;
     --md-text: #e2e8f0;
   }

Reader Modes
------------

ב-``md_preview.html`` יש מצבי קריאה עם רקעים מיוחדים (sepia) שנשארים hardcoded בכוונה.
אלו לא חלק ממערכת התמות הגלובלית.

הנחיות למפתחים
===============

כללים בסיסיים
--------------

.. warning::
   **❌ אסור:** לכתוב צבעי HEX/RGB בקבצי CSS של קומפוננטות

.. code-block:: css

   /* ❌ שגוי */
   .my-component {
     background: #ffffff;
     color: #333333;
     border: 1px solid #e5e7eb;
   }

.. tip::
   **✅ נכון:** להשתמש תמיד ב-``var(--variable-name)``

.. code-block:: css

   /* ✅ נכון */
   .my-component {
     background: var(--card-bg);
     color: var(--text-primary);
     border: 1px solid var(--glass-border);
   }

מתי ליצור טוקן חדש?
--------------------

**Level 1 (Primitives):**
  יצירת טוקן חדש רק אם הערך חייב להישאר זהה בכל 8 התמות.

**Level 2 (Semantic):**
  יצירת טוקן חדש אם הערך מייצג מושג סמנטי (רקע, טקסט, גבול) ומשתנה בין תמות.

**Level 3 (Component):**
  יצירת טוקן חדש רק אם:

  * הצל/רקע ייחודי לתמה ולא ניתן לחשב מטוקנים קיימים
  * רכיב צריך צבעים שונים מהפלטה הגלובלית

הוספת משתנה חדש
----------------

1. הוסף את המשתנה ל-``:root`` ב-``base.html``
2. הוסף override לכל תמה שצריכה ערך שונה
3. עדכן את המסמך הזה ואת ``webapp_theme_palettes.md``

.. code-block:: css

   /* base.html */
   :root {
     --my-new-token: #default-value;
   }

   :root[data-theme="dark"] {
     --my-new-token: #dark-value;
   }

   :root[data-theme="ocean"] {
     --my-new-token: #ocean-value;
   }
   /* ... וכן הלאה לכל תמה */

Inline Styles ו-JavaScript
---------------------------

גם ב-inline styles וב-JS יש להשתמש במשתנים:

.. code-block:: javascript

   // ❌ שגוי
   element.style.color = '#667eea';

   // ✅ נכון
   element.style.color = 'var(--primary)';

   // או שימוש ב-CSS class
   element.classList.add('text-primary');

Fallbacks
---------

כשמשתמשים במשתנה, אפשר להוסיף fallback:

.. code-block:: css

   .element {
     color: var(--text-primary, #ffffff);
   }

.. note::
   עדיף להוסיף טוקן חדש מאשר לסמוך על fallbacks.

Gradients ו-Hover States
------------------------

.. code-block:: css

   /* גרדיאנטים */
   .gradient-bg {
     background: linear-gradient(135deg, var(--primary), var(--secondary));
   }

   /* Hover */
   .button:hover {
     background: var(--btn-primary-hover-bg);
     box-shadow: var(--btn-primary-hover-shadow);
   }

Theme Overrides - נושא מותאם אישית
====================================

דוגמה ל-Override ספציפי
------------------------

.. code-block:: css

   /* Override לתמה ספציפית */
   :root[data-theme="ocean"] .my-special-component {
     background: rgba(49, 130, 206, 0.2);
   }

   :root[data-theme="high-contrast"] .my-special-component {
     background: #000000;
     border: 2px solid #ffffff;
   }

Custom Theme - טוקנים חובה
---------------------------

כדי שנושא מותאם אישית ייראה סביר, חובה להגדיר:

* ``--bg-primary``, ``--bg-secondary``
* ``--text-primary``, ``--text-secondary``
* ``--primary``, ``--secondary``
* ``--glass``, ``--glass-border``
* ``--card-bg``, ``--card-border``
* ``--btn-primary-*`` (כל משתני הכפתור)

בדיקות - צ'קליסט QA
=====================

לפני כל merge של שינוי CSS/theme:

בדיקות חובה
-----------

.. code-block:: text

   [ ] מעבר על כל 8 התמות
   [ ] בדיקת עמודי עריכה/העלאה
   [ ] Live Preview - וידוא שרקע נשאר כהה
   [ ] Sticky Notes - צבעים נכונים
   [ ] Smooth Scroll Debug panel
   [ ] Login alert
   [ ] RTL - תצוגה נכונה
   [ ] Split View tabs
   [ ] טפסים ושדות input

בדיקות נגישות
--------------

.. code-block:: text

   [ ] בדיקת WCAG ב-High Contrast
   [ ] ווידוא ניגודיות מספקת בכל התמות
   [ ] פוקוס נראה בכל האלמנטים

בדיקת קוד
----------

.. code-block:: bash

   # חיפוש צבעים קשיחים בקבצי CSS
   rg -n "(#[0-9a-fA-F]{3,8}|rgba?\()" webapp/static/css/ --glob '!*.map'

קבצים מיוחדים
==============

קבצים שנשארים Hardcoded בכוונה
-------------------------------

* ``theme_preview.html`` - דף דמו עם ~50 דוגמאות צבע
* ``md_preview.html`` - Reader modes (sepia backgrounds)
* ``codemirror.local.js`` - ספריית CodeMirror (3rd party)
* ``md_preview.bundle.js`` - KaTeX (3rd party)

סדר טעינת CSS
--------------

.. code-block:: text

   1. base.html <style> ← הכי ספציפי, נטען ראשון
   2. {% block extra_css %}
   3. collections.css
   4. codemirror-custom.css
   5. markdown-enhanced.css
   6. global_search.css
   7. high-contrast.css
   8. dark-mode.css
   9. smooth-scroll.css

קישורים לפיצ'רים נוספים
========================

רכיבים שמשתמשים במשתנים:

* :doc:`./snippet-library` - ספריית הקוד
* :doc:`./bulk-actions` - פעולות בחירה מרובה
* :doc:`./markdown-folding` - Markdown מתקפל
* :doc:`./smooth-scrolling` - גלילה חלקה

נספחים
======

קישורים למסמכים נלווים
-----------------------

* ``webapp/FEATURE_SUGGESTIONS/css_refactor_plan.md`` - תכנית הריפקטור המלאה
* ``webapp/FEATURE_SUGGESTIONS/webapp_theme_palettes.md`` - פלטות צבעים מפורטות

קבצים רלוונטיים
----------------

* ``webapp/templates/base.html`` - הגדרות המשתנים
* ``webapp/static/css/dark-mode.css`` - סגנונות מצב כהה
* ``webapp/static/css/high-contrast.css`` - סגנונות נגישות
* ``webapp/static/css/global_search.css`` - דוגמה טובה לטוקנים ברמת Component
* ``webapp/static/css/bookmarks.css`` - דוגמה טובה לטוקנים ברמת Component
