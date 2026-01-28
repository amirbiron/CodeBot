ערכות נושא מותאמות אישית – מדריך מקיף
======================================

מדריך זה מכסה את כל היבטי מערכת ערכות הנושא המותאמות אישית (Custom Themes) – מייבוא VS Code themes ועד יצירה ידנית, הגדרות מתקדמות והדגשת תחביר.

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
       "editor.background": "#1a1b26"
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

   רק משתנים שנמצאים ברשימה זו יישמרו בעת פרסום ערכה לציבורית.
   משתנים שאינם ברשימה יסוננו אוטומטית מטעמי אבטחה.
   הרשימה מוגדרת ב-``services/theme_parser_service.py`` (``ALLOWED_VARIABLES_WHITELIST``).

.. code-block:: text

   # Level 1 - Primitives
   --primary, --primary-hover, --primary-light
   --secondary
   --success, --warning, --error
   --danger-bg, --danger-border, --text-on-warning
   --glass, --glass-blur, --glass-border, --glass-hover

   # Level 2 - Semantic Tokens
   --bg-primary, --bg-secondary, --bg-tertiary
   --text-primary, --text-secondary, --text-muted
   --border-color, --shadow-color
   --card-bg, --card-border
   --navbar-bg
   --input-bg, --input-border
   --link-color
   --code-bg, --code-text, --code-border
   --btn-primary-bg, --btn-primary-color, --btn-primary-border
   --btn-primary-shadow, --btn-primary-hover-bg, --btn-primary-hover-color
   --md-surface, --md-text
   --split-preview-bg, --split-preview-meta, --split-preview-placeholder

   # Level 2 - Markdown Enhanced (inline code, tables, mermaid)
   --md-inline-code-bg, --md-inline-code-border, --md-inline-code-color
   --md-table-bg, --md-table-border, --md-table-header-bg
   --md-mermaid-bg

הדגשת תחביר (Syntax Highlighting)
----------------------------------

כאשר מייבאים ערכת VS Code עם ``tokenColors``, המערכת ממירה אותם אוטומטית להדגשת תחביר עבור CodeMirror ו-Pygments.

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

   ערכים שלא עוברים ולידציה נמחקים בשקט ומוחלפים בערכי ברירת מחדל.
   לוג אזהרה נרשם לצורכי דיבוג.

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
     "source": "vscode",
     "content": "{...JSON content...}"
   }

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
     "syntax_css": "/* CodeMirror */", // CSS להדגשת תחביר
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
