:summary: מדריך זה מכסה את כל היבטי מערכת ערכות הנושא המותאמות אישית (Custom Themes) – מייבוא VS Code themes ועד יצירה ידנית, הגדרות מתקדמות והדגשת תחביר.

ערכות נושא מותאמות אישית – מדריך מקיף
======================================

.. contents::
   :depth: 3
   :local:

מבוא וסקירה כללית
-----------------

מהי ערכת נושא מותאמת אישית?
~~~~~~~~~~~~~~~~~~~~~~~~~~~

ערכת נושא מותאמת אישית (Custom Theme) היא אוסף של משתני CSS המגדירים את המראה הוויזואלי של הממשק – צבעי רקע, טקסט, כפתורים, קוד ועוד.

**היתרונות העיקריים:**

- התאמה אישית מלאה של המראה לפי טעמכם
- ייבוא ערכות מ-VS Code בלחיצה אחת
- שמירת מספר ערכות ומעבר ביניהן
- תמיכה בהדגשת תחביר (Syntax Highlighting) ייחודית

ההבדל בין Presets לבין Custom Themes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 20 40 40

   * - 
     - Presets (ערכות מוכנות)
     - Custom Themes (ערכות מותאמות)
   * - **מקור**
     - מוגדרות מראש במערכת (Dark, Ocean, Classic...)
     - נוצרות על ידי המשתמש או מיובאות
   * - **עריכה**
     - לא ניתנות לעריכה
     - ניתנות לעריכה מלאה
   * - **הדגשת תחביר**
     - קבועה לפי הערכה
     - מיובאת מ-VS Code או ברירת מחדל
   * - **שמירה**
     - במערכת
     - ב-MongoDB לפי משתמש

יכולות המערכת
~~~~~~~~~~~~~

- **ייבוא מ-VS Code** – תמיכה מלאה בפורמט JSON/JSONC של VS Code themes
- **יצירה ידנית** – עורך צבעים מתקדם עם תצוגה מקדימה חיה
- **ערכות מוכנות** – גלריה של ערכות פופולריות (GitHub, Dracula, Nord...)
- **הדגשת תחביר** – מיפוי אוטומטי של ``tokenColors`` ל-CodeMirror

ייבוא ערכות VS Code
-------------------

פורמטים נתמכים
~~~~~~~~~~~~~~

המערכת תומכת בשני פורמטי JSON:

**JSON רגיל:**

קובץ JSON סטנדרטי ללא הערות.

**JSONC (JSON with Comments):**

פורמט מורחב שתומך בהערות – נפוץ מאוד בערכות VS Code כמו Nord, One Dark Pro ועוד:

.. code-block:: json

   {
     "name": "My Theme",
     /* זו הערה מרובת שורות */
     "type": "dark",
     "colors": {
       // זו הערה של שורה בודדת
       "editor.background": "#1a1b26",
       "editor.foreground": "#c0caf5",
       "focusBorder": "#7aa2f7"
     }
   }

סוגי הערות נתמכים:

- ``/* ... */`` – הערות מרובות שורות (multi-line)
- ``// ...`` – הערות של שורה בודדת (single-line)

.. note::

   המערכת מסירה אוטומטית את ההערות לפני פרסור ה-JSON, כך שאין צורך לערוך את הקובץ ידנית.

מבנה ערכת VS Code
~~~~~~~~~~~~~~~~~

ערכת VS Code מורכבת משלושה חלקים עיקריים:

.. code-block:: json

   {
     "name": "Theme Name",
     "type": "dark",
     "colors": {
       "editor.background": "#1e1e1e",
       "editor.foreground": "#d4d4d4",
       "button.background": "#569cd6",
       "sideBar.background": "#252526"
     },
     "tokenColors": [
       {
         "scope": "comment",
         "settings": {
           "foreground": "#6a9955",
           "fontStyle": "italic"
         }
       },
       {
         "scope": ["keyword", "storage"],
         "settings": {
           "foreground": "#569cd6"
         }
       }
     ]
   }

**הסבר השדות:**

- ``name`` – שם הערכה
- ``type`` – סוג הערכה: ``"dark"`` או ``"light"`` (משפיע על ערכי fallback)
- ``colors`` – מילון של צבעי UI (רקעים, טקסט, כפתורים)
- ``tokenColors`` – כללי הדגשת תחביר

מיפוי צבעי UI
~~~~~~~~~~~~~

המערכת ממפה אוטומטית את צבעי VS Code למשתני CSS שלנו:

.. list-table::
   :header-rows: 1
   :widths: 35 35 30

   * - VS Code Key
     - CSS Variable(s)
     - תיאור
   * - ``editor.background``
     - ``--bg-primary``, ``--md-surface``
     - רקע ראשי
   * - ``editor.foreground``
     - ``--text-primary``, ``--md-text``
     - טקסט ראשי
   * - ``sideBar.background``
     - ``--bg-secondary``
     - רקע משני
   * - ``activityBar.background``
     - ``--bg-tertiary``
     - רקע שלישוני
   * - ``button.background``
     - ``--btn-primary-bg``, ``--btn-primary-border``
     - כפתור ראשי
   * - ``button.foreground``
     - ``--btn-primary-color``
     - טקסט כפתור
   * - ``button.hoverBackground``
     - ``--btn-primary-hover-bg``
     - כפתור בריחוף
   * - ``input.background``
     - ``--input-bg``
     - רקע שדה קלט
   * - ``input.border``
     - ``--input-border``
     - גבול שדה קלט
   * - ``panel.border``
     - ``--border-color``
     - גבולות כלליים
   * - ``focusBorder``
     - ``--primary``
     - צבע ראשי
   * - ``textLink.foreground``
     - ``--link-color``
     - צבע קישורים
   * - ``terminal.background``
     - ``--code-bg``
     - רקע קוד
   * - ``terminal.foreground``
     - ``--code-text``
     - טקסט קוד
   * - ``titleBar.activeBackground``
     - ``--navbar-bg``
     - רקע ניווט
   * - ``editorWidget.background``
     - ``--card-bg``
     - רקע כרטיסים
   * - ``notificationsErrorIcon.foreground``
     - ``--error``, ``--danger-bg``
     - צבע שגיאה
   * - ``notificationsWarningIcon.foreground``
     - ``--warning``
     - צבע אזהרה
   * - ``testing.iconPassed``
     - ``--success``
     - צבע הצלחה

יצירה ידנית (Native Format)
----------------------------

מבנה הפורמט המקומי
~~~~~~~~~~~~~~~~~~

אם אתם מעדיפים ליצור ערכה מאפס, השתמשו בפורמט המקומי:

.. code-block:: json

   {
     "name": "My Custom Theme",
     "description": "ערכה מותאמת אישית",
     "variables": {
       "--bg-primary": "#1a1b26",
       "--bg-secondary": "#24283b",
       "--bg-tertiary": "#414868",
       "--text-primary": "#c0caf5",
       "--text-secondary": "#9aa5ce",
       "--text-muted": "#565f89",
       "--primary": "#7aa2f7",
       "--primary-hover": "#89b4fa",
       "--btn-primary-bg": "#7aa2f7",
       "--btn-primary-color": "#1a1b26",
       "--glass-blur": "12px"
     }
   }

משתנים חובה
~~~~~~~~~~~

הערכה חייבת לכלול לפחות את המשתנים הבאים לתפקוד תקין:

**רקעים וטקסט (Level 2):**

.. code-block:: text

   --bg-primary          רקע ראשי של הדף
   --bg-secondary        רקע משני (סיידבר, כרטיסים)
   --bg-tertiary         רקע שלישוני (אלמנטים משניים)
   --text-primary        טקסט ראשי
   --text-secondary      טקסט משני
   --text-muted          טקסט מעומעם

**צבעי מותג (Level 1):**

.. code-block:: text

   --primary             צבע ראשי (כפתורים, קישורים, focus)
   --primary-hover       צבע ראשי בריחוף
   --primary-light       גרסה בהירה של הצבע הראשי

**כפתורים (Level 2):**

.. code-block:: text

   --btn-primary-bg       רקע כפתור ראשי
   --btn-primary-color    טקסט כפתור ראשי
   --btn-primary-border   גבול כפתור ראשי

**נוספים:**

.. code-block:: text

   --border-color        צבע גבולות
   --card-bg             רקע כרטיסים
   --input-bg            רקע שדות קלט
   --code-bg             רקע קוד
   --glass-blur          טשטוש glass (בפיקסלים, למשל "12px")

רשימת משתנים מלאה (Whitelist)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. important::

   רק משתנים שנמצאים ברשימה זו נשמרים — בייבוא, ביצירה ובעדכון של ערכה אישית, ובפרסום ערכה לציבורית. משתנים שאינם ברשימה מסוננים מטעמי אבטחה.

הרשימה כאן נמשכת מהקוד, ``ALLOWED_VARIABLES_WHITELIST`` ב-``services/theme_parser_service.py``, בכל בנייה של התיעוד. עד נובמבר 2026 היא הייתה עותק ידני, וטוקני ה-Level 3 של ערכה מיובאת בהירה (:ref:`theme-variables-light-import-hooks`) חסרו בו.

.. literalinclude:: ../../services/theme_parser_service.py
   :language: python
   :start-after: # docs:theme-variables-whitelist:start
   :end-before: # docs:theme-variables-whitelist:end
   :caption: services/theme_parser_service.py – ALLOWED_VARIABLES_WHITELIST

.. _theme-variables-override-hook:

דריסת טוקן שאין לו מקבילה ב-VS Code
------------------------------------

חלק מהטוקנים אינם נגזרים משום מפתח של VS Code, כי אין להם מקבילה שם. ``--collections-link-override`` הוא כזה: הוא צובע את שמות הקבצים בדף ``/collections`` — גם בכרטיס אוסף וגם בשולחן העבודה, שני מסכים נפרדים שמרנדרים את אותו סוג קישור. בכוונה אין לו ערך ברירת מחדל בשום מקום, ולכן ה-CSS נופל לערך שנצבע היום כשהערכה אינה מצהירה עליו.

בערכה מיובאת שאינה מצהירה עליו, שמות הקבצים מקבלים את ``--primary`` של הערכה. זה נכון לרוב הערכות, אבל כרטיס האוסף נשאר לבן גם בערכות כהות — ולכן ערכה שה-``--primary`` שלה בהיר מקבלת טקסט בהיר על רקע בהיר.

כדי לפתור את זה בערכה בודדת, בלי להשפיע על שאר הערכות, אפשר להוסיף בלוק ``variables`` **לצד** ``colors`` באותו קובץ VS Code:

.. code-block:: json

   {
     "name": "Cobalt Next",
     "type": "dark",
     "colors": {
       "editor.background": "#1b2b34",
       "editor.foreground": "#d8dee9",
       "focusBorder": "#ffffff"
     },
     "tokenColors": [],
     "variables": {
       "--collections-link-override": "#2e6161"
     }
   }

הבלוק עובר את אותה ולידציה ואת אותה רשימה לבנה כמו כל שאר הטוקנים — ערך שאינו צבע תקין מוחזר עם 400 ומציין את המפתח, ולא נזרק בשקט — ומתמזג **מעל** התוצאה שנגזרה מ-``colors``. ``tokenColors`` ממשיך להיות מעובד כרגיל, ולכן הדגשת התחביר אינה נפגעת. שימו לב ש-``colors`` חייב להכיל לפחות שלושה מפתחות, אחרת הייבוא נדחה.

.. note::

   ערכה שאינה מצהירה על הטוקן מרונדרת ללא כל שינוי, בשני המצבים: ``webapp/static/css/collections.css`` נופל ל-``var(--primary)`` במצב רגיל ול-``var(--primary-dark)`` ב-``:hover`` — בדיוק הערכים שנצבעו גם קודם. זו דריסה בהצטרפות מרצון, לא שינוי גורף.

.. _theme-variables-search-suggestion-hook:

הצעות ההשלמה בחיפוש הגלובלי
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``--search-suggestion-text-override`` הוא וו מאותו סוג בדיוק, ובאותו מסלול שורש. ההצעות שקופצות מתחת לתיבת החיפוש הגלובלי מרונדרות ב-``webapp/static/js/global_search.js`` כאלמנטי ``<a>``, ולכן ``[data-theme="custom"] a`` שב-``dark-mode.css`` צובע אותן ב-``var(--primary)`` — ספציפיות שגוברת על כלל המחלקה שב-``global_search.css``. רקע התיבה, לעומת זאת, אינו של הערכה כלל: הוא ``--solid-surface-bg``, שנשאר לבן בכל ערכה. כלומר צבע הטקסט נגזר מהערכה והרקע לא, והניגודיות יוצאת מקרית — ערכה שה-``--primary`` שלה לבן מקבלת טקסט לבן על רקע לבן.

ההצהרה נראית זהה, ושני הטוקנים יכולים לחיות באותו בלוק:

.. code-block:: json

   "variables": {
     "--collections-link-override": "#2e6161",
     "--search-suggestion-text-override": "#2e6161"
   }

.. note::

   כאן יש **שלושה** מצבים ולא שניים, ולכל אחד ``var()`` משלו ב-``webapp/static/css/global_search.css``: המצב הרגיל נופל ל-``var(--primary)``, ``:hover`` נופל ל-``var(--primary-dark)``, ו-``:focus-visible`` נופל ל-``var(--suggestions-text)``. השלישי אינו טעות: ``.search-suggestion:focus-visible`` מנצח כבר היום את כלל ה-``<a>`` בזכות ספציפיות, ולכן הערך שנצבע בו היום שונה משני האחרים. ערכה שאינה מצהירה מרונדרת זהה לחלוטין בשלושת המצבים.

.. warning::

   הערך נשמר ב-MongoDB **בזמן הייבוא**. ערכה שכבר קיימת בחשבון אינה מכירה טוקן שנוסף אחריה — צריך לייבא אותה מחדש. זו הסיבה הראשונה לבדוק כשההצהרה נוספה ולא נראה שינוי.

.. _theme-variables-repo-md-code-block-hook:

בלוקי הקוד בתצוגת ה-Markdown של דפדפן הריפו
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``--repo-md-code-block-bg-override`` ו-``--repo-md-code-block-border-override`` הם שני ווים מאותו סוג, לרקע ולגבול של בלוקי הקוד בתצוגת ה-Markdown של דפדפן הריפו. בערכה מיובאת, ``webapp/static/css/markdown-preview.css`` צובע את המעטפת של התצוגה ב-``--bg-tertiary``, את הבלוק ב-``--code-bg`` ואת הגבול שלו ב-``--border-color``. ``VSCODE_TO_CSS_MAP`` גוזר כל אחד מהשלושה ממפתחות אחרים של VS Code, ולכן ערכה שבה שלושתם יוצאים באותו צבע מקבלת בלוק שאינו נבדל מהטקסט שסביבו — בלי רקע אחר ובלי גבול נראה. כך קורה ב-Cobalt Next.

הדריסה היא בשני טוקנים חדשים ולא ב-``--code-bg`` עצמו, כי ``--code-bg`` צובע גם רכיבי קוד אחרים — למשל את תצוגת הקוד ב-``/file`` ואת קטעי הקוד בחיפוש הגלובלי — ודריסה שלו בערכה הייתה משנה גם אותם. ההצהרה נראית זהה לשני הווים הקודמים, וכולם יכולים לחיות באותו בלוק:

.. code-block:: json

   "variables": {
     "--collections-link-override": "#2e6161",
     "--search-suggestion-text-override": "#2e6161",
     "--repo-md-code-block-bg-override": "#21313a",
     "--repo-md-code-block-border-override": "#374751"
   }

.. note::

   ערכה שאינה מצהירה על הטוקנים מרונדרת ללא שינוי: הרקע נופל ל-``var(--code-bg, var(--bg-secondary, #1e1e1e))`` והגבול ל-``var(--md-preview-border)`` — הטוקן של התצוגה, שקורא את ``--border-color`` של הערכה — מה שנצבע שם גם קודם. שני הטוקנים נקראים בכלל הקיים שצובע את הבלוק בערכות מיובאות ומשותפות, ולא בכלל חדש, כך שהמפל של ערכה שאינה מצהירה נשאר זהה. הגבול נקבע ב-``border-color`` בלבד, והעובי והסגנון נשארים של הכלל הכללי ``.markdown-preview-content pre``. ``tests/services/test_theme_variables_repo_md_code_block_hook.py`` נועל את החוזה הזה. וגם כאן, ערכה שכבר קיימת בחשבון מקבלת את הטוקנים רק אחרי ייבוא מחדש.

.. _theme-variables-btn-primary-text-hook:

הטקסט בכפתורי primary
~~~~~~~~~~~~~~~~~~~~~~

``--btn-primary-text-override`` הוא וו מאותו סוג, לצבע הטקסט של כפתור primary. בערכה מיובאת או משותפת הטקסט הזה נצבע ב-``--primary`` בכמה מקומות:

- כפתור שהוא קישור, ``<a class="btn btn-primary">`` — למשל הלשונית הנבחרת בעמוד הקבצים והכפתורים בעמוד ההגדרות — נצבע דרך ``[data-theme="custom"] a`` שב-``webapp/static/css/dark-mode.css``, ובריחוף דרך ``a:hover`` שם, ב-``--primary-dark``.
- "ערוך" ו"העתק קוד" בעמוד הקובץ נצבעים דרך ``.file-primary-action`` שב-``webapp/templates/view_file.html``, גם בריחוף.
- מצבי הפוקוס, הלחיצה וההשבתה של כל כפתור primary, וכל כפתור primary בערכה משותפת, נצבעים דרך כללי ה-``!important`` שבבלוק ``primary-btn-states-custom-type`` ב-``webapp/templates/base.html``.

``--primary`` נגזר ממפתחות VS Code אחרים מאלה שקובעים את רקע הכפתור (``button.background``), ולכן השניים יכולים לצאת קרובים. ב-Everforest Dark ``--primary`` הוא ``#7fbbb3`` — ``notificationsInfoIcon.foreground`` ממופה אליו אחרי ``focusBorder`` ב-``VSCODE_TO_CSS_MAP``, ולכן הוא שקובע — על רקע ``#a7c080``, כלומר ניגודיות 1.09 לפי WCAG. כפתור primary שהוא ``<button>``, כמו "חפש", אינו מושפע במצב רגיל: הוא נצבע ב-``--btn-primary-color``, שהערכה קובעת דרך ``button.foreground``.

.. code-block:: json

   {
     "name": "Everforest Dark",
     "type": "dark",
     "colors": {
       "editor.background": "#2d353b",
       "button.background": "#a7c080",
       "button.foreground": "#2d353b",
       "focusBorder": "#2d353b00",
       "notificationsInfoIcon.foreground": "#7fbbb3"
     },
     "tokenColors": [],
     "variables": {
       "--btn-primary-text-override": "#232a2e"
     }
   }

.. note::

   ערכה שאינה מצהירה על הטוקן מרונדרת ללא שינוי, בכל מצב: כל כלל נופל לערך שהוא צבע עד היום — ``var(--primary)``, ובריחוף של קישור ``var(--primary-dark)``. בכללים הקיימים הטוקן נקרא בלי לשנות את הבורר. לקישורים נוספו ב-``dark-mode.css`` שני כללים, רגיל וריחוף, עם הבוררים של כללי הקישורים עצמם ועם ``:where(.btn-primary)``: ``:where()`` אינו מוסיף ספציפיות, והכללים כתובים מיד אחרי כללי הקישורים, ולכן הם חלים בדיוק במקום שבו כללי הקישורים צובעים היום. הבורר הוא ``[data-theme="custom"]`` ולא ``[data-theme-type="custom"]``, בכוונה: ``previewTheme`` ב-``base.html`` מחליף את ``data-theme`` לערכה מובנית ומשאיר את ``data-theme-type``, וכלל שנשען עליו היה משנה את התצוגה המקדימה. ``tests/services/test_theme_variables_btn_primary_text_hook.py`` נועל את החוזה, וגם כאן ערכה שכבר קיימת בחשבון מקבלת את הטוקן רק אחרי ייבוא מחדש.

.. _theme-variables-light-import-hooks:

ערכה מיובאת בהירה: שדות טופס, הפיד והפוש בדשבורד, ושורת החיפוש ב-Markdown
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

כל ערכה מיובאת מקבלת את העיצוב של הערכות הכהות, וזה נשאר כך בכוונה. כמה רכיבים צבועים שם בצבעים קבועים לרקע כהה — לבן שקוף לגבולות ולרקעים, וטקסט כמעט לבן בתגים — ולכן בערכה מיובאת בהירה הם לא נראים. לערכות המובנות הבהירות יש להם כללים משלהן, ולערכה מיובאת אין. ווים מאותו סוג נותנים לערכה בהירה לקבוע אותם לעצמה:

- ``--form-field-border-override``, ``--form-field-bg-override`` ו-``--form-field-focus-border-override`` — הגבול, הרקע והגבול בפוקוס של השדות בעמודי העריכה וההעלאה (``.form-field`` ב-``webapp/static/css/file-editor.css``): שם הקובץ, השפה, התיאור, התגיות והקוד. שני הראשונים נקראים גם בשדות הסינון בעמוד הקבצים (החיפוש, השפה והמיון), שצבועים רק ב-``style`` שבתגית שלהם ב-``webapp/templates/files.html``.
- ``--timeline-block-bg-override`` — הרקע של הבלוקים בפיד האחרון בדשבורד: הקבוצה (``.timeline-group``) והפריט שבתוכה (``.timeline-item``), שצבועים היום באותו ערך. ``--timeline-item-border-override`` — הפס בצד של כל פריט.
- ``--timeline-badge-text-override`` — הטקסט של התג בפיד, בכל סוגי התג (``.timeline-badge-code``, ``-info``, ``-warning`` ו-``-neutral``). הרקע של כל סוג נשאר בגוון שלו.
- ``--status-pill-text-override`` — הטקסט של הבאדג' בכרטיס הגדרות הפוש ("מופעל ב-X דפדפנים"), בכל סוגי הבאדג' (``.status-success``, ``-warning``, ``-danger`` ו-``-neutral``).
- ``--md-search-capsule-border-override`` — הגבול של שורת החיפוש בתצוגת ה-Markdown (``.md-search-capsule`` ב-``webapp/templates/md_preview.html``), שהוא שקוף עד שמתחילים להקליד.

.. code-block:: json

   {
     "name": "Pen Paper Coffee UI",
     "type": "light",
     "colors": {
       "editor.background": "#f8f6f1",
       "editor.foreground": "#2b3f6a",
       "editorWidget.background": "#ebe8df"
     },
     "tokenColors": [],
     "variables": {
       "--form-field-border-override": "rgba(110, 78, 68, 0.35)",
       "--form-field-bg-override": "rgba(255, 253, 249, 0.6)",
       "--form-field-focus-border-override": "#6e4e44",
       "--timeline-block-bg-override": "rgba(110, 78, 68, 0.06)",
       "--timeline-item-border-override": "rgba(110, 78, 68, 0.35)",
       "--timeline-badge-text-override": "#2b3f6a",
       "--status-pill-text-override": "#2b3f6a",
       "--md-search-capsule-border-override": "rgba(110, 78, 68, 0.3)"
     }
   }

.. note::

   ערכה שאינה מצהירה על הטוקנים מרונדרת ללא שינוי, וכך גם התצוגה המקדימה של ערכה מובנית מתוך אשף הערכות: כל טוקן נקרא בכלל שצובע היום את הרכיב, עם fallback לערך שנצבע בו, והבורר של הכלל לא השתנה. במקומות שבהם ל-Rose Pine Dawn יש כלל משלה — השדות בעמודי העריכה וההעלאה, הפיד והפוש ושורת החיפוש — הכלל שלה ספציפי יותר וממשיך לגבור. בשורת החיפוש ה-fallback הוא ``transparent``, הגבול של הכלל הכללי, וכלל ה-``:focus-within`` ספציפי יותר מהכלל שקורא את הווו, ולכן בזמן הקלדה הגבול נשאר שלו. ``tests/services/test_theme_variables_light_import_hooks.py`` נועל את החוזה, כולל הדוגמה שלמעלה, וגם כאן ערכה שכבר קיימת בחשבון מקבלת את הטוקנים רק אחרי ייבוא מחדש. **מה נמדד ב-31.10.2026**, על הדוגמה שלמעלה עם הרקע של Pen Paper Coffee, מול הפיקסל האמיתי שמאחורי כל רכיב: הטקסט בתגים ובבאדג' עלה מניגודיות של 1.18–1.35 ל-5.75–7.18, והגבול של השדות מ-1.06 ל-1.51. בערכות שאינן מצהירות — Classic, Dark, Rose Pine Dawn, High Contrast, ערכה מיובאת כהה וערכה מיובאת בהירה — הרכיבים זהים למה שהיו לפני הווים, גם בפוקוס ובתצוגה המקדימה.

.. _theme-variables-md-document-colors-hook:

צבעי המסמך: כותרות, הדגשה, קוד בשורה וציטוט
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

בתצוגת ה-Markdown (``md_preview.html``) ובתצוגה החיה בעמודי העריכה וההעלאה, ערכה מיובאת מבדילה בין חלקי המסמך רק בשני צבעי טקסט: כותרות ורשימות ב-``--text-primary`` (מ-``editor.foreground``, ו-``input.foreground`` דורס אותו כשהוא בקובץ), ופסקאות ב-``--text-secondary`` (מ-``sideBar.foreground``). כששני המפתחות זהים בקובץ, כמו ב-morass, כל המסמך יוצא בצבע אחד.

אין לזה מקור בקובץ הערכה. התצוגה המרונדרת של VS Code עצמו צובעת כותרות והדגשה ב-``editor.foreground``, בלי מפתח משלהן; רק לקישור (``textLink.foreground``), לקוד בשורה (``textPreformat.foreground``), לציטוט (``textBlockQuote.background`` / ``textBlockQuote.border``) ולבלוק קוד (``textCodeBlock.background``) יש מפתח — נקרא ב-``microsoft/vscode@864824b4``, בקבצים ``src/vs/workbench/contrib/webview/browser/pre/index.html`` ו-``extensions/markdown-language-features/media/markdown.css``. ``markup.heading``, ``markup.bold`` ושכניהם ב-``tokenColors`` אינם צבעי המסמך: הם צובעים את מקור ה-Markdown בעורך, דרך הדקדוק של TextMate, ובמערכת שלנו הם הופכים להדגשת תחביר בבלוקי קוד (:ref:`shared-theme-syntax-css`).

לכן אלה ווים מאותו סוג של הקודמים: ערכה בודדת שרוצה מסמך צבעוני מצהירה עליהם בבלוק ``variables``, וערכה שאינה מצהירה נשארת כמו היום. הם נקראים ב-``webapp/static/css/md-content-colors.css``, בכללים שחלים רק בתוך ``#md-content`` ורק בערכה מיובאת או משותפת:

- ``--md-heading-color-override`` — כותרות H1 ו-H2. בלעדיו: ``--text-primary``.
- ``--md-subheading-color-override`` — כותרות H3 עד H6. בלעדיו: ``--text-primary``.
- ``--md-strong-color-override`` — הדגשה (``strong`` ו-``b``), גם בתוך רשימה וציטוט. בלעדיו: הצבע שההדגשה יורשת מהטקסט שסביבה.
- ``--md-inline-code-color-override`` — קוד בשורה. בלעדיו: ``--code-text`` (מ-``terminal.foreground``).
- ``--md-blockquote-border-override`` — הפס של הציטוט. בלעדיו: ``--md-blockquote-border``, צבע הטקסט בשקיפות.
- לקישור אין טוקן חדש: הוא כבר נקרא מ-``--link-color``, ובערכה שאין בה ``textLink.foreground`` אפשר להצהיר עליו באותו בלוק.

הדוגמה של morass — הצבעים שנבחרו לה מתוך הצבעים שכבר יש בקובץ שלה, וגם ``--primary`` רך יותר מה-``focusBorder`` שהמייבא גוזר:

.. code-block:: json

   "variables": {
     "--primary": "#E1C636",
     "--md-heading-color-override": "#E1C636",
     "--md-subheading-color-override": "#cfd394",
     "--md-strong-color-override": "#dcdcaa",
     "--link-color": "#7fdbca",
     "--md-inline-code-color-override": "#b5cea8",
     "--md-blockquote-border-override": "#E1C636"
   }

.. note::

   ערכה שאינה מצהירה על הטוקנים מרונדרת ללא שינוי. ההדגשה, הקוד בשורה והציטוט נקראים בכללים שצובעים אותם היום, ו-fallback של כל טוקן הוא הערך שנצבע שם. לכותרות אין במסמך כלל משלהן — היום הן נצבעות בכלל ה-Typography של ``webapp/static/css/dark-mode.css``, שחל על כל כותרת באתר — ולכן נוסף כלל שחל רק בתוך ``#md-content``, וה-fallback שלו הוא אותו ``--text-primary``. כותרות בממשק, מחוץ למסמך, לא מושפעות. ``tests/services/test_theme_variables_md_document_colors_hook.py`` נועל את החוזה, ו-``tests/test_md_document_colors_hook_browser.py`` מודד בדפדפן את שתי התצוגות, בערכה אישית ובערכה שפורסמה לציבורית. מצבי הרקע של תצוגת המסמך (ספיה ושאר הגוונים) לא חלים כאן: הם מוצעים רק בערכות מובנות בהירות (``ALLOWED_THEMES`` ב-``md_preview.html``). וכמו בכל וו, ערכה שכבר קיימת בחשבון מקבלת את הטוקנים רק אחרי ייבוא מחדש, וערכה ציבורית — אחרי פרסום מחדש.

הדגשת תחביר (Syntax Highlighting)
----------------------------------

כאשר מייבאים ערכת VS Code עם ``tokenColors``, ``parse_vscode_theme`` ממיר אותם אוטומטית ל-``syntax_css`` עם שלוש קבוצות כללים, אחת לכל מנוע צביעה: CodeMirror בעורך (``generate_codemirror_css_from_tokens``), highlight.js בבלוקי הקוד של Markdown (``generate_hljs_css_from_tokens``), ו-Pygments (``generate_pygments_css_from_tokens``). מה שעובר מהן בפרסום לציבורית — :ref:`shared-theme-syntax-css`.

ארכיטקטורה
~~~~~~~~~~

זרימת המרת צבעים מ-VS Code ל-CodeMirror:

.. code-block:: text

   tokenColors (VS Code)
        │
        ▼
   VSCODE_TO_CM_TAG מיפוי
        │
        ▼
   syntax_colors JSON
        │
        ▼
   HighlightStyle.define() (CodeMirror)

מיפוי VS Code Scopes ל-CodeMirror Tags
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 40 40 20

   * - VS Code Scope
     - CodeMirror Tag
     - הערות
   * - ``comment``
     - ``comment``
     - הערות
   * - ``comment.block.documentation``
     - ``docComment``
     - תיעוד
   * - ``string``
     - ``string``
     - מחרוזות
   * - ``string.regexp``
     - ``regexp``
     - Regex
   * - ``keyword``
     - ``keyword``
     - מילות מפתח
   * - ``keyword.control``
     - ``controlKeyword``
     - if, for, while
   * - ``keyword.control.import``
     - ``moduleKeyword``
     - import, export
   * - ``storage.type``
     - ``definitionKeyword``
     - def, class
   * - ``entity.name.function``
     - ``function(definition(variableName))``
     - הגדרת פונקציה
   * - ``meta.function-call``
     - ``function(variableName)``
     - קריאה לפונקציה
   * - ``support.function.builtin``
     - ``standard(function(variableName))``
     - פונקציות מובנות
   * - ``variable``
     - ``variableName``
     - משתנים
   * - ``variable.parameter``
     - ``local(variableName)``
     - פרמטרים
   * - ``variable.language.self``
     - ``self``
     - self, this
   * - ``constant.numeric``
     - ``number``
     - מספרים
   * - ``constant.language.boolean``
     - ``bool``
     - true, false
   * - ``entity.name.class``
     - ``definition(className)``
     - שם מחלקה
   * - ``entity.name.type``
     - ``typeName``
     - שם טיפוס
   * - ``keyword.operator``
     - ``operator``
     - אופרטורים
   * - ``entity.name.tag``
     - ``tagName``
     - תגיות HTML
   * - ``entity.other.attribute-name``
     - ``attributeName``
     - מאפיינים

מנגנון Fallback
~~~~~~~~~~~~~~~

כאשר ערכה לא מגדירה צבע לתג ספציפי, המערכת יורשת מתגים הוריים:

.. code-block:: text

   function(definition(variableName))
        │
        ├── יורש מ-definition(variableName)
        │        │
        │        └── יורש מ-variableName
        │                 │
        │                 └── יורש מ-name
        │
        └── יורש מ-function(variableName)
                 │
                 └── יורש מ-variableName

**דוגמה:**

אם הערכה מגדירה צבע רק ל-``variableName``, כל ההגדרות שיורשות ממנו יקבלו את אותו הצבע עד שתוגדר דריסה ספציפית.

CodeMirror CSS Classes
~~~~~~~~~~~~~~~~~~~~~~

מעבר ל-Tags המשמשים ב-``HighlightStyle.define()``, המערכת תומכת גם ב-CSS Classes עבור ``classHighlighter``. אלו מאפשרים דריסה ישירה ב-CSS:

**Classes בסיסיים:**

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - CSS Class
     - תיאור
   * - ``.tok-comment``
     - הערות
   * - ``.tok-string``, ``.tok-string2``
     - מחרוזות (רגילות / template)
   * - ``.tok-keyword``
     - מילות מפתח
   * - ``.tok-number``
     - מספרים
   * - ``.tok-operator``
     - אופרטורים
   * - ``.tok-punctuation``
     - סימני פיסוק
   * - ``.tok-atom``, ``.tok-bool``
     - קבועים וערכי boolean
   * - ``.tok-literal``
     - ערכים ליטרליים

**משתנים ופונקציות:**

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - CSS Class
     - תיאור
   * - ``.tok-variableName``
     - משתנים רגילים
   * - ``.tok-variableName.tok-definition``
     - הגדרות משתנים (צבע שונה)
   * - ``.tok-variableName.tok-local``
     - משתנים מקומיים (לעתים עם italic)
   * - ``.tok-variableName2``
     - משתנים מיוחדים (self, this, super)
   * - ``.tok-function``
     - פונקציות
   * - ``.tok-macroName``
     - מאקרו / decorators

**טיפוסים ומחלקות:**

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - CSS Class
     - תיאור
   * - ``.tok-className``
     - שמות מחלקות
   * - ``.tok-typeName``
     - שמות טיפוסים
   * - ``.tok-namespace``
     - namespaces / modules
   * - ``.tok-propertyName``
     - שמות properties
   * - ``.tok-propertyName.tok-definition``
     - הגדרות properties

**HTML/XML:**

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - CSS Class
     - תיאור
   * - ``.tok-tagName``
     - תגיות HTML/XML
   * - ``.tok-attributeName``
     - מאפיינים
   * - ``.tok-angleBracket``
     - סוגריים זוויתיים ``< >``

**עיצוב טקסט (Markdown):**

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - CSS Class
     - תיאור
   * - ``.tok-heading``
     - כותרות
   * - ``.tok-emphasis``
     - טקסט נטוי (italic)
   * - ``.tok-strong``
     - טקסט מודגש (bold)
   * - ``.tok-link``, ``.tok-url``
     - קישורים
   * - ``.tok-quote``
     - ציטוטים
   * - ``.tok-monospace``
     - קוד inline

**מיוחדים:**

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - CSS Class
     - תיאור
   * - ``.tok-meta``
     - מטא-דאטה
   * - ``.tok-labelName``
     - labels
   * - ``.tok-inserted``
     - שורות שנוספו (git diff)
   * - ``.tok-deleted``
     - שורות שנמחקו (git diff)
   * - ``.tok-changed``
     - שורות ששונו
   * - ``.tok-invalid``
     - קוד לא תקין

**דוגמת CSS לדריסה:**

.. code-block:: css

   /* דריסת צבע הגדרות פונקציות */
   :root[data-theme="custom"] .tok-variableName.tok-definition {
       color: #7aa2f7 !important;
       font-weight: bold !important;
   }

   /* משתנים מקומיים באיטליק */
   :root[data-theme="custom"] .tok-variableName.tok-local {
       color: #bb9af7 !important;
       font-style: italic !important;
   }

   /* self/this בצבע מיוחד */
   :root[data-theme="custom"] .tok-variableName2 {
       color: #f7768e !important;
   }

   /* שורות שנוספו בדיף */
   :root[data-theme="custom"] .tok-inserted {
       color: #9ece6a !important;
       background: rgba(158, 206, 106, 0.1);
   }

   /* שורות שנמחקו בדיף */
   :root[data-theme="custom"] .tok-deleted {
       color: #f7768e !important;
       background: rgba(247, 118, 142, 0.1);
   }

.. note::

   ה-``!important`` נדרש כדי לדרוס את ה-inline styles שמוזרקים על ידי CodeMirror themes.
   הסלקטור ``:root[data-theme="custom"]`` מבטיח שהדריסות יחולו רק כשערכה מותאמת פעילה.

אבטחה וולידציה
--------------

ולידציית צבעים
~~~~~~~~~~~~~~

המערכת מאפשרת רק פורמטים בטוחים:

**פורמטים נתמכים:**

.. code-block:: text

   #fff          Hex קצר (3 תווים)
   #ffff         Hex עם alpha (4 תווים)
   #ffffff       Hex מלא (6 תווים)
   #ffffffff     Hex עם alpha (8 תווים)
   rgb(r, g, b)  RGB (ערכים 0-255)
   rgba(r, g, b, a)  RGBA עם שקיפות (alpha 0-1)

**ערכים חסומים (אבטחה):**

.. code-block:: text

   url(...)          CSS injection
   expression(...)   IE legacy injection
   javascript:       XSS
   data:             Data URI injection
   @import           CSS import injection

סניטציה
~~~~~~~

המערכת מבצעת מספר שלבי ניקוי:

1. **הסרת הערות JSONC** – לפני פרסור ה-JSON
2. **בדיקת תקינות JSON** – וולידציה של מבנה הקובץ
3. **ולידציית צבעים** – לפי ה-Regex המגביל
4. **בדיקת whitelist** – רק משתנים מוכרים מותרים
5. **הגבלת גודל** – מניעת קבצים גדולים מדי

.. warning::

   לא כל ערך פסול מטופל באותה דרך, וההבדל חשוב:

   - **ערך פסול בבלוק** ``variables`` — הייבוא **נדחה** עם ``400``, וההודעה מציינת את המפתח.
   - **מפתח שאינו ברשימה הלבנה** — עובר את הוולידציה ואז מסונן בשקט, עם אזהרה בלוג.
   - **ערך פסול בתוך** ``colors`` — עובר את הוולידציה, והטוקן שהוא ממופה אליו נופל לערך ברירת המחדל, עם אזהרה בלוג.

   כלומר שתי הצורות האחרונות אינן מפילות את הייבוא. אם ערכה נשמרה אך צבע מסוים אינו מופיע, זו הסיבה הסבירה.

API Reference
-------------

Endpoints
~~~~~~~~~

**רשימת ערכות:**

.. code-block:: text

   GET /api/themes

מחזיר רשימת כל הערכות של המשתמש (ללא ``variables`` הכבדים).

**פרטי ערכה:**

.. code-block:: text

   GET /api/themes/<id>

מחזיר ערכה מלאה כולל ``variables`` לעריכה.

**יצירת ערכה:**

.. code-block:: text

   POST /api/themes
   Content-Type: application/json

   {
     "name": "My Theme",
     "variables": {...}
   }

**ייבוא ערכה:**

.. code-block:: text

   POST /api/themes/import
   Content-Type: application/json

   {
     "json_content": "{...JSON content...}"
   }

הפורמט מזוהה מתוך התוכן עצמו ולא נמסר כפרמטר: קובץ שיש בו מפתח ``colors`` מפורסר כערכת VS Code, וכל השאר כפורמט המקומי. לחלופין אפשר להעלות ב-``multipart/form-data`` תחת השדה ``file``, בסיומת ``.json``.

**עדכון ערכה:**

.. code-block:: text

   PUT /api/themes/<id>
   Content-Type: application/json

   {
     "name": "Updated Name",
     "variables": {...}
   }

**הפעלת ערכה:**

.. code-block:: text

   POST /api/themes/<id>/activate

מפעיל את הערכה (מכבה את כל האחרות) ומעדכן ``ui_prefs.theme="custom"``.

**ביטול הפעלה:**

.. code-block:: text

   POST /api/themes/deactivate

מבטל את כל הערכות המותאמות וחוזר ל-Classic.

**מחיקת ערכה:**

.. code-block:: text

   DELETE /api/themes/<id>

מוחק ערכה. אם הייתה פעילה – חוזרים ל-Classic.

מבנה תגובה
~~~~~~~~~~

.. code-block:: javascript

   {
     "success": true,
     "theme": {
       "id": "uuid-string",
       "name": "My Theme",
       "description": "תיאור הערכה",
       "is_active": true,
       "source": "vscode",
       "created_at": "2024-01-15T10:30:00Z",
       "updated_at": "2024-01-15T10:30:00Z",
       "variables": {
         "--bg-primary": "#1a1b26"
         // ... additional variables
       },
       "syntax_css": "/* CodeMirror CSS */",
       "syntax_colors": {
         "keyword": {"color": "#7aa2f7"}
         // ... additional colors
       }
     }
   }

פרסום ערכה לציבורית (Shared Themes)
------------------------------------

אדמינים יכולים לפרסם ערכות אישיות לכל המשתמשים.

מבנה נתונים ב-DB
~~~~~~~~~~~~~~~~

ערכות ציבוריות נשמרות ב-collection ``shared_themes``:

.. code-block:: javascript

   {
     "_id": "cyber_purple",           // slug ייחודי
     "name": "Cyber Purple",          // שם לתצוגה
     "description": "ערכה סגולה",
     "colors": {                      // CSS variables (מסונן לפי whitelist)
       "--bg-primary": "#0d0221",
       "--primary": "#7b2cbf"
     },
     "syntax_css": "...",             // CSS להדגשת תחביר, אחרי sanitize_syntax_css
     "syntax_colors": {               // מילון צבעים ל-HighlightStyle דינמי
       "keyword": {"color": "#7b2cbf"}
     },
     "created_by": 6865105071,
     "created_at": ISODate("..."),
     "is_active": true,
     "is_featured": false
   }

שמירת משתנים בפרסום
~~~~~~~~~~~~~~~~~~~

בבונה הערכות (``theme_builder.html``), הקוד שומר את המשתנים המקוריים כדי שלא יאבדו בפרסום:

.. code-block:: javascript

   // משתנים לשמירת נתונים מקוריים
   let currentThemeOriginalVariables = {};  // כל משתני CSS
   let currentThemeSyntaxCss = '';          // CSS להדגשת תחביר
   let currentThemeSyntaxColors = {};       // מילון צבעים דינמי

   // בטעינת ערכה
   currentThemeOriginalVariables = { ...theme.variables };
   currentThemeSyntaxCss = theme.syntax_css || '';
   currentThemeSyntaxColors = theme.syntax_colors || {};

   // בפרסום - מיזוג: משתנים מקוריים + ערכי טופס
   const colors = {
     ...currentThemeOriginalVariables,  // משתנים שאינם בטופס
     ...collectThemeValues(),           // ערכי הטופס (דורסים)
   };

.. tip::

   משתנים כמו ``--link-color`` ו-``--code-bg`` אינם בטופס אך נשמרים
   מהערכה המקורית, כך שצבעי קישורים וקוד לא נאבדים בפרסום.

.. _shared-theme-syntax-css:

הדגשת התחביר בפרסום
~~~~~~~~~~~~~~~~~~~~

ה-``syntax_css`` של הערכה האישית נשלח עם הפרסום, וגם בעדכון של ערכה ציבורית, ו-``SharedThemeService`` מנקה אותו ב-``sanitize_syntax_css`` לפני שמירה. הניקוי מקבל את שלוש הקבוצות ש-``parse_vscode_theme`` מייצר, כל אחת בבורר שהמחולל שלה כותב, ואת הכלל הבסיסי ``.hljs`` עם הרקע של העורך — כך שערכה ציבורית נצבעת כמו הערכה האישית שממנה פורסמה. ``tests/services/test_sanitize_syntax_css.py`` מריץ את המחוללים על כל ה-scopes שבמפות שלהם, ונכשל אם כלל שהם כותבים לא עובר.

- **כלל שלא עבר** — מערכה ישנה בפורמט קודם, או מ-CSS שנערך ביד — לא נשמר. הפרסום מצליח, והתשובה מחזירה כמה כללים לא עברו (``syntax_rules_dropped``). בונה הערכות מציג אז אזהרה במקום הודעת הצלחה, ובלוג נרשמת אזהרה.
- ``syntax_css`` **שאינו מחרוזת** ← ``400 invalid_syntax_css``, ו-``syntax_css`` **ארוך מ-**\ ``MAX_SYNTAX_CSS_LENGTH`` ← ``400 syntax_css_too_long`` עם ``max``. בשני המקרים לא נשמר דבר — לא CSS ריק ולא CSS קטוע.

עד נובמבר 2026 הפרסום עבר דרך ``sanitize_codemirror_css``, שמכיר רק את כללי CodeMirror. ערכה ציבורית איבדה בשקט את כללי highlight.js ו-Pygments, ובלוקי קוד ב-Markdown נצבעו בפלטה שנגזרת ממשתני הממשק (``md-content-colors.css``) במקום בצבעים של הערכה. ערכה ציבורית שפורסמה לפני התיקון נשארת כך עד שמפרסמים אותה מחדש מהערכה האישית: ``tokenColors`` לא נשמרים עם הערכה, ולכן אין ממה לשחזר את הכללים.

פתרון בעיות (Troubleshooting)
-----------------------------

בעיות נפוצות
~~~~~~~~~~~~

**"קובץ JSON לא תקין":**

- בדקו שאין הערות שגויות (``//`` בתוך מחרוזת)
- ודאו שכל הסוגריים מאוזנים
- בדקו שאין פסיקים מיותרים בסוף

**צבעים לא מופיעים:**

- ודאו שפורמט הצבע תקין (``#fff``, ``#ffffff``, ``rgb(...)``)
- בדקו שהמשתנה נמצא ברשימת ה-whitelist
- בדקו את לוג האזהרות בקונסול

**הדגשת תחביר לא עובדת:**

- ודאו שהערכה מיובאת מ-VS Code ומכילה ``tokenColors``
- ערכות שנוצרו ידנית לא כוללות הדגשת תחביר ייחודית
- בדקו שה-``syntax_colors`` נשמר כראוי
- בערכה ציבורית: בדקו אם בפרסום הופיעה אזהרה על כללי הדגשה שלא נשמרו (:ref:`shared-theme-syntax-css`)

**הערכה לא נשמרת:**

- ודאו שאתם מחוברים למערכת
- בדקו שלא עברתם את מגבלת 10 הערכות
- בדקו הרשאות כתיבה למסד הנתונים

דוגמה לייבוא ערכת Nord
~~~~~~~~~~~~~~~~~~~~~~

1. הורידו את קובץ ``nord-theme.json`` מהריפו הרשמי
2. פתחו את Theme Builder בהגדרות
3. לחצו "ייבוא מ-VS Code"
4. העלו את הקובץ
5. שמרו והפעילו

קישורים קשורים
--------------

.. seealso::

   - :doc:`/webapp/theming_and_css` – תיעוד ארכיטקטורת הטוקנים והערכות
   - ``GUIDES/custom_themes_guide.md`` – מדריך פנימי מורחב
   - ``services/theme_parser_service.py`` – קוד המקור של הפרסור
   - ``services/theme_presets_service.py`` – ניהול ערכות מוכנות
   - ``webapp/static/data/theme_presets.json`` – קובץ ה-Presets
