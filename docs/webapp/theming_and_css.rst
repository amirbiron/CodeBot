מערכת ערכות הנושא והטוקנים החדשה
=================================

הדף מרכז את כל הידע המעשי על ארכיטקטורת הצבעים, משתני ה‑CSS והבדיקות שנדרשות לשימור חוויית הממשק בכל שמונה הערכות. זהו מקור האמת עבור כל שינוי עתידי ב‑CSS של ה‑WebApp.

.. contents::
   :depth: 2
   :local:

רקע ומוטיבציה
-------------

- בריפקטור האחרון הוסרו צבעים ייחודיים מקבצים כגון ``global_search.css`` והופיעו באגים של *black/white zebra*, איבוד גרדיאנטים ולבן מסנוור ב‑Live Preview.  
- עדכוני Theme נקודתיים בעבר חזרו לצבעים קשיחים (HEX/RGB) ולכן נשברו ב‑Classic/Ocean/Forest שנוספו מאוחר יותר.  
- מטרת המערכת החדשה: ריכוז כל המשתנים ב‑שלוש שכבות, צמצום FOUC (קביעת ``data-theme`` עוד לפני טעינת ה‑CSS), שימור נגישות וייחודיות, והגדרה ברורה של מה חייב Override בכל Theme.  
- ההנחיות כאן מחליפות קוד קשיח ותלויות מערכת הפעלה (``prefers-color-scheme``) ומייצרות תשתית אחת עבור Theme Builder, Split View, Collections, Markdown Viewer ועוד.  

שכבות משתנים וטעינת ``data-theme``
-----------------------------------

**Level 1 – Primitives (:root ב‑``variables.css``)**  
קבועים לכולם ומרוכזים כיום ב‑``webapp/static/css/variables.css`` (הקובץ נטען מתוך ``base.html`` בתחילת ה‑`<head>`). כאן מגדירים צבעי מותג (`--primary`, `--secondary`), צבעי מצב (`--success` וכו'), טוקני סכנה (`--danger-bg`, `--danger-border`, `--text-on-warning`), ערכי markdown (`--md-surface`, `--md-text`), הגדרות כפתור ברירת מחדל וערכי גלאס (`--glass*`). אין להשתמש ב‑HEX מחוץ לקטע זה.

**Level 2 – Semantic Tokens per Theme**  
בלוקים של ``:root[data-theme="..."]`` ב‑``variables.css`` קובעים רקעים (`--bg-*`), טקסט (`--text-*`), כרטיסים (`--card-*`), צבעי קוד, כפתורים (`--btn-primary-*`) וטוקנים ל‑Split View (`--split-preview-*`). Ocean/Forest/Classic/Dim/Nebula/Rose Pine Dawn/High Contrast משתמשות בכל הטוקנים; Dark/Dim/Nebula גם בעבור קבצי CSS ב־``static/css/dark-mode.css`` שנשענים על אותם ערכים גלובליים.

**Level 3 – Component Tokens**  
נוצר רק כשיש צורכי עיצוב ייחודיים: `--search-card-shadow` ב‑``global_search.css``, `--bookmarks-panel-bg` ב‑``bookmarks.css``, משפחת `--split-*` ב‑``split-view.css``. את ערכי ברירת המחדל מגדירים ברכיב עצמו, אך מומלץ להוסיף הפניה ל‑``variables.css`` (או ל‑`:root[data-theme]`) כאשר הרכיב חוצה דפים, כדי למנוע חזרה לצבעים קשיחים.

**טעינת המערכת**  
``base.html`` קובע ``data-theme`` על `<html>` מתוך `localStorage` כבר ב‑`<head>` כדי למנוע FOUC, ולאחר מכן טוען את ``webapp/static/css/variables.css`` וכל שאר קבצי הרכיבים. כך הטוקנים זמינים עוד לפני טעינת ``dark-mode.css`` / ``high-contrast.css`` / קבצים ייעודיים. Theme Wizard ו‑Theme Builder מזריקים Overrides דינמיים ל‑``<style id="user-custom-theme">`` (נוצר בעת שמירת Theme מותאם) ומגדירים `data-theme="custom"` או Override ל‑Theme קיים. על כל סקריפט שמשנה Theme לעדכן גם את ``localStorage`` באותה צורה.

תרשים זרימת היררכיית טוקנים
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. mermaid::

   graph TD
       subgraph "Global Scope (variables.css)"
           L1["<b>Level 1: Primitives</b><br/>:root<br/>--primary, --danger, --glass"]
           L2["<b>Level 2: Semantic Overrides</b><br/>:root[data-theme='...']<br/>--bg-app, --text-main, --card-bg"]
       end

       subgraph "Component Scope"
           L3_A["<b>Level 3: Global Search</b><br/>--search-highlight-bg"]
           L3_B["<b>Level 3: Split View</b><br/>--split-preview-bg"]
           L3_C["<b>Level 3: Markdown</b><br/>--md-surface"]
       end

       L4["<b>User Custom Theme</b><br/>style id='user-custom-theme'<br/>Dynamic User Overrides"]

       L1 --> L2
       L2 --> L3_A
       L2 --> L3_B
       L2 --> L3_C
       L3_A --> L4
       L3_B --> L4
       L3_C --> L4

       style L1 fill:#f9f9f9,stroke:#333,stroke-width:2px
       style L2 fill:#e1f5fe,stroke:#0277bd,stroke-width:2px
       style L4 fill:#fff3e0,stroke:#ff9800,stroke-width:2px,stroke-dasharray: 5 5

התרשים ממחיש את שרשרת ההורשה: מתחילים ב‑Primitives, עוברים לטוקנים סמנטיים לפי Theme, ממשיכים לטוקני רכיב ורק לבסוף ל‑Overrides דינמיים עבור Theme מותאם אישית.

טבלת טוקנים עיקריים
--------------------

הטבלה מציגה את הטוקנים שחובה למלא עבור כל Theme, השכבה האחראית והקובץ שבו מעדכנים.

.. list-table::
   :header-rows: 1
   :widths: 22 12 36 30

   * - טוקן
     - שכבה
     - תיאור
     - מיקום / Override חובה
   * - ``--primary`` / ``--secondary``
     - Level 1
     - צבעי מותג, משמשים גם לגרדיאנטים ו‑focus
     - ``webapp/static/css/variables.css`` (:root + ``:root[data-theme]``; ``base.html`` רק טוען את הקובץ)
   * - ``--bg-primary/secondary/tertiary``
     - Level 2
     - רקעים לגוף, למודלים ולכרטיסים
     - ``webapp/static/css/variables.css`` בתוך ``:root[data-theme]``; חובה בכל Theme (Ocean/Forest מקבלים ערכי כחול/ירוק ייעודיים)
   * - ``--text-primary/secondary/muted``
     - Level 2
     - משפחת צבעי טקסט לכל הרכיבים
     - ``webapp/static/css/variables.css`` (``:root[data-theme]``) + בדיקת ניגודיות ב‑High Contrast
   * - ``--card-bg`` / ``--card-border``
     - Level 2
     - כרטיסים, מודלים, dropdowns. **Theme Builder מייצר ``--card-border`` אוטומטית מ‑``--glass-border``** (תוקן ב‑2025-12)
     - ``webapp/static/css/variables.css`` (``:root[data-theme]``) + שימוש חוזר ב‑``static/css/dark-mode.css`` כולל ``[data-theme="custom"]``
   * - ``--glass`` / ``--glass-border`` / ``--glass-hover``
     - Level 1
     - בסיס ל‑Glassmorphism navbar, badges, מודלים. **Theme Builder מייצר אותם לפי צבע ``--card-bg`` ולא לבן קבוע** (תוקן ב‑2025-12)
     - ``webapp/static/css/variables.css`` (קטע ``:root``) + Overrides ב‑תמות בהירות + ``dark-mode.css`` עבור ``[data-theme="custom"]``
   * - ``--btn-primary-bg`` / ``--btn-primary-color`` / ``--btn-primary-border`` / ``--btn-primary-shadow``
     - Level 2
     - כל כפתור ראשי, כולל מצבי hover (`--btn-primary-hover-*`)
     - ``webapp/static/css/variables.css`` (``:root[data-theme]``) + הרחבה עבור Classic/Ocean/Forest/Rose
   * - ``--danger-bg`` / ``--danger-border`` / ``--text-on-warning``
     - Level 1
     - שימשו לטיפול Banner Login, Inline Alerts, Sticky Notes
     - ``webapp/static/css/variables.css`` (קטע ``:root`` בלבד; אין Overrides לכל Theme)
   * - ``--md-surface`` / ``--md-text``
     - Level 1 + Level 2
     - Split View / Markdown Preview נשאר כהה גם בתמות בהירות
     - ``webapp/static/css/variables.css`` (ערך כהה ב‑``:root`` + Overrides ספציפיים ב‑Classic/Ocean/Forest)
   * - ``--split-tabs-selected-color`` / ``--split-preview-*`` / ``--split-error-*``
     - Level 3
     - רכיב Split View + Live Preview
     - ``webapp/static/css/split-view.css`` (ברירת מחדל + בלוקים לכל Theme)
   * - ``--search-card-shadow`` / ``--search-highlight-*``
     - Level 3
     - UI החיפוש הגלובלי
     - ``webapp/static/css/global_search.css``
   * - ``--glass-badge`` / ``--bookmarks-panel-bg`` / ``--bookmark-*``
     - Level 3
     - רכיבי Bookmarks ו‑Glass Badges
     - ``bookmarks.css`` (כבר במצב מלא, שימרו על הפורמט)
   * - ``--split-preview-placeholder`` / ``--split-preview-meta``
     - Level 3
     - טקסט משני בתצוגת Markdown
     - ``split-view.css`` + קביעת ניגודיות
   * - ``--code-bg`` / ``--code-text`` / ``--code-border``
     - Level 2
     - CodeMirror, כרטיסי קוד, Split View
     - ``webapp/static/css/variables.css`` (``:root[data-theme]``) + קבצי Markdown (`markdown-enhanced.css`)

רשימת הטוקנים המורחבת זמינה בקובץ ``webapp/FEATURE_SUGGESTIONS/css_refactor_plan.md`` ובטבלת הפלטות ``webapp/FEATURE_SUGGESTIONS/webapp_theme_palettes.md``.

מפת ערכות הנושא (Theme Reference)
----------------------------------

.. list-table::
   :header-rows: 1
   :widths: 18 12 20 50

   * - ערכה
     - ``data-theme``
     - בסיס צבע
     - הערות / טוקנים ייחודיים
   * - Dark
     - ``dark``
     - אפור/סגול כהה
     - משמש כברירת מחדל עם ``localStorage``; חופף ל‑``dark-mode.css``
   * - Dim
     - ``dim``
     - רך יותר מדארק
     - אותם טוקנים כמו Dark עם ניגודיות נמוכה יותר
   * - Nebula
     - ``nebula``
     - כחול‑סגול קוסמי
     - ``--glass`` סגלגל, ``--btn-primary`` משתמש ב‑`color-mix`
   * - Classic
     - ``classic``
     - גרדיאנט סגול‑כחול
     - ``--btn-primary-*`` לבן, ``--md-surface`` כהה גם בערכת אור
   * - Ocean
     - ``ocean``
     - כחול עמוק
     - כל טוקן רקע/טקסט מוגדר ידנית; Split View מקבל ``--split-codehilite`` כחול
   * - Rose Pine Dawn
     - ``rose-pine-dawn``
     - ורוד‑שמנת
     - ערכת אור מלאה עם ``color-mix`` לכפתורים ו‑Split View בגווני חמרה
   * - High Contrast
     - ``high-contrast``
     - שחור/לבן/צהוב
     - Overrides מלאים ב‑``variables.css`` (`:root[data-theme="high-contrast"]`) + קובץ Legacy ``static/css/high-contrast.css`` לחיזוקי נגישות; אין גרדיאנטים

.. figure:: ../images/theme-classic-preview.svg
   :alt: סקיצה של ערכת Classic
   :width: 640px

   ערכת Classic מציגה כפתור ראשי לבן, רקע גרדיאנטי וטוקן ``--md-surface`` כהה עבור Split View.

.. figure:: ../images/theme-high-contrast-preview.svg
   :alt: סקיצה של ערכת High Contrast
   :width: 640px

   ערכת High Contrast משתמשת רק בשחור, לבן וצהוב לפי WCAG 2.1 AA. כל שינוי חייב לשמור על יחס ניגודיות 4.5:1 לטקסט רגיל.

.. note::

   ``static/css/high-contrast.css`` נשאר בקוד כ‑Legacy עבור התאמות Focus/Outline בלבד. כל הטוקנים עצמם חיים ב‑``webapp/static/css/variables.css`` וממומשים דרך ``:root[data-theme="high-contrast"]``.

Markdown Viewer ו‑Split View
----------------------------

- גם כאשר הערכה בהירה (Classic / Rose Pine Dawn) המקדימה והעורך נשארים כהים עם ``--md-surface`` ו‑``--md-text``. לכן אסור לרוקן את הערכים הללו ב‑`:root`.
- כפתור "רקע לבן" ב‑``md_preview.html`` פשוט מסיר מחלקות ``bg-sepia/light/medium/dark``. השתמשו בטוקנים כשהדבר מתאפשר, אך שמרו על Presets לפי `COLORS` בסקריפט – אלו חריגים שהוגדרו בכוונה.
- Live Preview (`split-view.css`) משתמש ב‑``--split-preview-*``. הוספת preset חדש (למשל ``bg-sepia``) מחייבת:
  1. הוספת המחלקה בקובץ התבנית.
  2. יצירת טוקן חדש ברמת Level 3 (``--split-sepia-bg``) אם נדרש.
  3. בדיקות ניגודיות ב‑High Contrast.
- ``theme_preview.html`` ו‑Reader modes ב‑``md_preview.html`` נשארים Hardcoded לצורכי תצוגת פלטות – אין להמיר אותם ל‑`var()` כדי לשמור על נאמנות ל‑brand colors.

הנחיות למפתחים (Best Practices)
--------------------------------

- ❌ אין לציין HEX בקבצי רכיבים (למעט חריגים מתועדים).  
  ✅ תמיד להשתמש ב‑``var(--token-name)`` ולוודא שהטוקן עלה לטבלת הרפרנס.
- כלל אצבע:  
  - צריך צבע שחוזר בכמה קומפוננטות → טוקן סמנטי (Level 2).  
  - צריך גוון שמזוהה עם רכיב מסוים (צלחמת חיפוש, טאב מסוים) → טוקן רכיב (Level 3) + Overrides.  
- Inline styles ב‑HTML/JS: צרו מחלקה ב‑CSS שמפנה ל‑``var()``. אם חייבים Inject דינמי (למשל Sticky Notes) – חשבו צבעים דרך טוקנים קיימים (`--text-on-primary`, `--danger-bg`).
- `color-mix()` עדיף על שקיפות ידנית; הצמידו אותו לטוקנים קיימים כדי להבטיח עקביות.
- ``[data-theme="..."]`` הוא הסלקטור היחיד לשינוי Theme. אין להשתמש שוב ב‑``prefers-color-scheme`` מלבד בקוד Legacy שכבר קיים ב‑``markdown-enhanced.css`` (TODO לעדכן).

דוגמת קוד – לא תקין לעומת תקין
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: css

   /* ❌ לא תקין – צבעים קשיחים */
   .global-search-card {
       background: #ffffff;
       color: #1c1c1c;
       box-shadow: 0 30px 60px rgba(7, 7, 31, 0.35);
   }

   /* ✅ תקין – מסתמך על טוקנים */
   .global-search-card {
       background: var(--card-bg);
       color: var(--text-primary);
       box-shadow: var(--search-card-shadow, 0 20px 40px rgba(0,0,0,0.25));
   }

Component Tokens ו‑Theme Builder
--------------------------------

.. note::

   המפרט הרשמי של Theme Builder מתועד ב‑Issue #2097 ובמדריכים שבתיקיית ``GUIDES/``.
   חלק ב' מוסיף **תמיכה בריבוי ערכות** (Multi-Theme) למשתמש מחובר.

- מטרות ה‑Builder:
  - בונה ערכה ב‑``/settings/theme-builder`` עם Live Preview מבודד שמצרוך ``var(--token)`` בלבד ולא משפיע על שאר ה‑UI עד לשמירה.
  - מעבר ממבנה ערכה אחת ל‑**מערך ערכות**: ``users.custom_themes`` (עד 10 ערכות למשתמש).
  - רק ערכה אחת יכולה להיות פעילה בכל רגע (``is_active=True``).
  - הזרקה אוטומטית של הערכה הפעילה דרך ``<style id="user-custom-theme">`` ב‑``base.html`` כאשר ``data-theme="custom"``.
  - תאימות לאחור: פונקציית ``get_custom_theme`` בודקת קודם ``custom_themes`` (מבנה חדש), ואז fallback ל‑``custom_theme`` (מבנה ישן).

- API (Multi-Theme):
  - ``GET /api/themes`` – רשימת הערכות של המשתמש **ללא** ``variables`` כבדים
  - ``POST /api/themes`` – יצירת ערכה חדשה (כולל מגבלת 10)
  - ``GET /api/themes/<id>`` – פרטי ערכה כולל ``variables`` לעריכה
  - ``PUT /api/themes/<id>`` – עדכון ערכה
  - ``POST /api/themes/<id>/activate`` – הפעלת ערכה (מכבה את השאר + מעדכן ``ui_prefs.theme="custom"``)
  - ``POST /api/themes/deactivate`` – ביטול כל הערכות וחזרה ל‑Classic
  - ``DELETE /api/themes/<id>`` – מחיקת ערכה (אם הייתה פעילה: חוזרים ל‑Classic)

- UI:
  - Sidebar "הערכות שלי" עם רשימה, אינדיקציה לערכה פעילה/נבחרת, וכפתור "ערכה חדשה".

- כאשר מוסיפים טוקן חדש:
  1. הוסיפו ערך ברירת מחדל ל‑``:root`` בתוך ``webapp/static/css/variables.css``.
  2. הוסיפו Overrides בבלוקים של כל Theme שדורש התאמה.
  3. אם הטוקן שייך לרכיב ספציפי, הגדירו אותו גם בקובץ הרכיב (למשל ``split-view.css``) כדי לא לאבד הקשר.
- Theme Builder (או Override ידני) נעשה באמצעות ``<style id="user-custom-theme">`` שמוזרק בסוף ה‑``<head>``. כך ניתן לאפשר Overrides בטוחים:

  .. code-block:: html

     <style id="user-custom-theme">
       :root[data-theme="custom"] {
         --primary: #ff6f61;
         --bg-primary: #0f1117;
         --text-primary: #f5f5f5;
         --btn-primary-bg: rgba(255,255,255,0.92);
       }
     </style>

- כאשר מבצעים Override לתמה קיימת (בידיים היום או דרך Theme Builder בעתיד), כתבו את הטוקנים בתוך ``:root[data-theme="ocean"]`` באותו `<style>` כך שהערכים הדינמיים יגברו על ברירת המחדל.
- טוקנים חובה ל‑Theme מותאם אישית (גם בעתיד כשה‑Builder יהיה פעיל): `--primary`, `--secondary`, `--bg-primary`, `--bg-secondary`, `--text-primary`, `--text-secondary`, `--btn-primary-bg`, `--btn-primary-color`, `--glass`, `--md-surface`, `--md-text`.
- **עדכון דצמבר 2025**: הוספה תמיכה מלאה ב‑``[data-theme="custom"]`` בקובץ ``dark-mode.css``. כעת כל הרכיבים (כרטיסים, כפתורים, navbar ועוד) משתמשים בטוקנים הנכונים גם עבור ערכות מותאמות. בנוסף, Theme Builder מייצר ``--glass*`` על בסיס צבע ``--card-bg`` (במקום לבן קבוע), מה שמתקן בעיות "רכיבים לבנים" בערכות בהירות.

בדיקות חובה לפני Merge
----------------------

- מעבר ידני על כל 8 הערכות דרך Theme Wizard + בדיקה מהירה של `localStorage`.
- בדיקת Split View + Markdown Preview (כולל לחצן "רקע לבן", מצבי Reader).
- בדיקת Live Preview / Sticky Notes / Smooth Scroll Debug / Login alert / RTL.
- בדיקת Collections, Bookmarks, אוספים משותפים וה‑Glass badges.
- בדיקת נגישות ב‑High Contrast (יחס ניגודיות 4.5:1, focus outline, קישורים).
- בדיקת שאין HEX קשיחים בקבצים שנגעתם בהם (`rg "#[0-9a-fA-F]{3,6}" webapp/static/css/<file>.css`).
- בדיקת WCAG ל‑Markdown Viewer (``bg-sepia`` ועוד) + ווידוא ש‑`--md-surface` לא הוחלף בטעות.
- מעבר בין Themes בזמן Live Preview כדי לוודא שאין FOUC (שימרו על setAttribute מוקדם).

שימושים נוספים וחריגים
----------------------

.. warning::

   ⚠️ **שים לב:** Sticky Notes, Reader Modes (`md_preview.html`) והקובץ ``theme_preview.html`` נשארים Hardcoded בכוונה לצורכי Preset/Brand. אין להמיר אותם ל‑``var()`` עד שתתועד חלופה רשמית, אחרת נשבור תצוגות קיימות.

- Collections (`webapp/static/css/collections.css`) עדיין מכיל צבעים קשיחים ישנים – כל שינוי חייב להמיר ל‑`var()` לפי טבלת הטוקנים.  
- Split View ו‑Markdown Enhanced משתמשים ב‑``--split-*`` ו‑``--md-*`` בהתאמה – הוסיפו טוקן לפני שמוסיפים Class חדש.  
- Sticky Notes, Reader Modes (`md_preview.html`) וה‑``theme_preview.html`` הם חריגים שנשארים Hardcoded כדי לשמור על תצוגת Preset.  
- `global_search.css` הינו דוגמה מצוינת לרכיב Component Tokens – כאשר מוסיפים תכונה חדשה (למשל badge נוסף) המשיכו את התבנית שם.  
- Collections / Split View / Markdown Enhanced מוזכרים בדף זה כדי שמפתחים ידעו להצליב בין הרכיבים ולזהות אילו טוקנים משותפים.

קישורים ונספחים
----------------

.. seealso::

   - ``webapp/FEATURE_SUGGESTIONS/css_refactor_plan.md`` – רשימות טוקנים מלאות לפי קובץ.
   - ``FEATURE_SUGGESTIONS/css_refactor_plan.md`` – תקציר עסקי ובדיקות QA.
   - ``FEATURE_SUGGESTIONS/theme_matrix.md`` – טבלת כיסוי טוקנים מקוצרת.
   - ``webapp/FEATURE_SUGGESTIONS/webapp_theme_palettes.md`` – פירוט צבעים וערכי Markdown.
   - ``webapp/static/css/variables.css`` – מקור כל ה‑Primitives ו‑``:root[data-theme]`` לפני קבצי הרכיבים.
   - ``webapp/templates/base.html`` – טעינת ``variables.css``, קביעת ``data-theme`` מוקדמת וה‑Theme Wizard.
   - ``webapp/static/css/dark-mode.css`` – שימוש בטוקנים עבור רכיבי Dark/Dim/Nebula.
   - ``webapp/static/css/high-contrast.css`` – Legacy לפוקוס/Outline; הדריסות עצמן ב‑``variables.css``.
   - ``webapp/static/css/global_search.css``, ``split-view.css``, ``bookmarks.css``, ``collections.css`` – דוגמאות מעשיות לטוקנים.
   - Issue #2097 – מפרט Theme Builder (טוקנים במיקוד, UI/Backend/API, נגישות ו‑Reset flow).

לשאלות תיעוד/Testing יש לפנות לערוץ Frontend או לפתוח Issue חדש עם קישור לדף זה. הקפידו לעיין גם ב‑`FEATURE_SUGGESTIONS/css_refactor_plan.md` לפני שינויים רוחביים בקוד.
