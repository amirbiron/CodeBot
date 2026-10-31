:summary: ארכיטקטורת הצבעים, משתני ה-CSS והבדיקות שנדרשות לשימור חוויית הממשק בכל ערכות הנושא. מקור האמת לכל שינוי ב-CSS של ה-WebApp.

מערכת ערכות הנושא והטוקנים החדשה
=================================

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

**Level 1 – Primitives (:root ב‑``webapp/templates/base.html``)**  
קבועים לכולם, ומרוכזים בבלוק ה‑``<style>`` שבתוך ``webapp/templates/base.html``, בכלל ה‑``:root`` הגלובלי — זה שפותח ב‑``--primary``. (יש בקובץ ``:root`` שני, בתוך media query של פס הגלילה, שקובע רק את ``--scrollbar-width``; הוא אינו זה.) כאן מגדירים צבעי מותג (`--primary`, `--secondary`), צבעי מצב (`--success` וכו'), טוקני סכנה (`--danger-bg`, `--danger-border`, `--text-on-warning`), ערכי markdown (`--md-surface`, `--md-text`), הגדרות כפתור ברירת מחדל וערכי גלאס (`--glass*`). אין להשתמש ב‑HEX מחוץ לקטע זה.

.. note::

   **המיקום הזה אינו מה שתוכנן.** ``webapp/FEATURE_SUGGESTIONS/css_refactor_plan.md`` תכנן לרכז את הטוקנים בקובץ ייעודי בשם ``variables.css``, והמימוש הזריק אותם ישירות לתבנית. **הקובץ ההוא אינו קיים בריפו**, ואין קוד שמנסה לטעון אותו. העמוד הזה מתאר את מה שקיים בפועל.

**Level 2 – Semantic Tokens per Theme**  
בלוקים של ``:root[data-theme="..."]`` ב‑``webapp/templates/base.html`` קובעים רקעים (`--bg-*`), טקסט (`--text-*`), כרטיסים (`--card-*`), צבעי קוד, כפתורים (`--btn-primary-*`) וטוקנים ל‑Split View (`--split-preview-*`). הבלוקים הקיימים שם הם ``classic``, ``ocean``, ``rose-pine-dawn``, ``dark``, ``dim``, ``nebula`` ו‑``custom``. **ל‑High Contrast אין בלוק שם** — ראו את הסעיף הייעודי למטה. Dark/Dim/Nebula נשענים גם על ``static/css/dark-mode.css``, שמשתמש באותם ערכים גלובליים.

**Level 3 – Component Tokens**  
נוצר רק כשיש צורכי עיצוב ייחודיים: `--search-card-shadow` ב‑``global_search.css``, `--bookmarks-panel-bg` ב‑``bookmarks.css``, משפחת `--split-*` ב‑``split-view.css``. את ערכי ברירת המחדל מגדירים ברכיב עצמו, אך מומלץ להוסיף הפניה לטוקן סמנטי מ‑``base.html`` (או ל‑`:root[data-theme]`) כאשר הרכיב חוצה דפים, כדי למנוע חזרה לצבעים קשיחים.

**טעינת המערכת**  
``base.html`` קובע ``data-theme`` על `<html>` מתוך `localStorage` כבר ב‑`<head>` כדי למנוע FOUC, והטוקנים עצמם יושבים בבלוק ``<style>`` באותה תבנית. כך הם זמינים מיד, עוד לפני טעינת ``dark-mode.css`` / ``high-contrast.css`` / קבצים ייעודיים. Theme Wizard ו‑Theme Builder מזריקים Overrides דינמיים ל‑``<style id="user-custom-theme">`` (נוצר בעת שמירת Theme מותאם) ומגדירים `data-theme="custom"` או Override ל‑Theme קיים. על כל סקריפט שמשנה Theme לעדכן גם את ``localStorage`` באותה צורה.

תרשים זרימת היררכיית טוקנים
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. mermaid::

   graph TD
       subgraph "Global Scope (base.html)"
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
     - ``webapp/templates/base.html`` — בלוק ה‑``<style>``: ``:root`` + ``:root[data-theme]``
   * - ``--bg-primary/secondary/tertiary``
     - Level 2
     - רקעים לגוף, למודלים ולכרטיסים
     - ``webapp/templates/base.html`` בתוך ``:root[data-theme]``; חובה בכל Theme (Ocean מקבל ערכי כחול ייעודיים)
   * - ``--text-primary/secondary/muted``
     - Level 2
     - משפחת צבעי טקסט לכל הרכיבים
     - ``webapp/templates/base.html`` (``:root[data-theme]``) + בדיקת ניגודיות ב‑High Contrast
   * - ``--card-bg`` / ``--card-border``
     - Level 2
     - כרטיסים, מודלים, dropdowns
     - ``webapp/templates/base.html`` (``:root[data-theme]``) + שימוש חוזר ב‑``static/css/dark-mode.css``
   * - ``--glass`` / ``--glass-border`` / ``--glass-hover``
     - Level 1
     - בסיס ל‑Glassmorphism navbar, badges, מודלים
     - ``webapp/templates/base.html`` (קטע ``:root``) + Overrides ב‑תמות בהירות
   * - ``--scrollbar-width-base`` / ``--scrollbar-width``
     - Level 1
     - רוחב פס גלילה גלובלי לפי מכשיר (מובייל שליש, טאבלט/דסקטופ חצי)
     - ``webapp/templates/base.html`` (בלוק ``:root`` + media query)
   * - ``--btn-primary-bg`` / ``--btn-primary-color`` / ``--btn-primary-border`` / ``--btn-primary-shadow``
     - Level 2
     - כל כפתור ראשי, כולל מצבי hover (`--btn-primary-hover-*`)
     - ``webapp/templates/base.html`` (``:root[data-theme]``) + הרחבה עבור Classic/Ocean/Rose
   * - ``--danger-bg`` / ``--danger-border`` / ``--text-on-warning``
     - Level 1
     - שימשו לטיפול Banner Login, Inline Alerts, Sticky Notes
     - ``webapp/templates/base.html`` (קטע ``:root`` בלבד; אין Overrides לכל Theme)
   * - ``--md-surface`` / ``--md-text``
     - Level 1 + Level 2
     - משטח כהה גם בתמות בהירות, לעמודים שקוראים אותו (בונה הערכות, גלריית הערכות, אינדקס התיעוד לאדמין), ורקע התצוגה החיה במצבי קוד ו‑HTML. הנייר של מסמך Markdown אינו הוא — ראו ``--md-paper-*``
     - ``webapp/templates/base.html`` (ערך כהה ב‑``:root`` + Overrides ספציפיים ב‑Classic/Ocean)
   * - ``--md-paper-bg`` / ``--md-paper-text``
     - Level 3
     - הנייר של מסמך Markdown: הרקע והטקסט של ``#md-content`` בתצוגת המסמך, ושל כל אזור התצוגה החיה במצב Markdown. בערכה מותאמת או משותפת הוא נגזר מ‑``--bg-primary`` ו‑``--text-primary`` (``editor.background`` / ``editor.foreground`` בקובץ VS Code), ולכן אינו ברשימה הלבנה (``ALLOWED_VARIABLES_WHITELIST``) בכוונה: הערכה כבר קובעת אותו דרכם
     - ``webapp/static/css/md-content-colors.css`` (``:root`` לבן, ובלוקים לערכות הכהות ולמותאמת/משותפת)
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
     - ``webapp/templates/base.html`` (``:root[data-theme]``) + קבצי Markdown (`markdown-enhanced.css`)
   * - ``--link-color``
     - Level 2
     - צבע הקישורים במסמך Markdown (``#md-content a`` ב‑``md-content-colors.css``, שחל גם בתצוגה החיה) ובתצוגה המקדימה של גלריית הערכות (``.preview-nav-links a``). בערכה מיובאת הוא ``textLink.foreground``. הריחוף במסמך קורא קודם ``--primary-hover`` (``textLink.activeForeground``), ובערכה שלא מצהירה עליו הקישור שומר על צבעו
     - ``webapp/templates/base.html`` (``:root`` + הבלוק של כל ערכה מובנית) + ``static/css/high-contrast.css``. ``tests/test_md_preview_link_color.py`` דורש הצהרה בכל ערכה שבוחר הערכות מציע
   * - ``--collections-link-override``
     - Level 3
     - שמות הקבצים בכרטיס אוסף ובשולחן העבודה. ברשימה הלבנה, ובכוונה **ללא** ערך ברירת מחדל — כך ערכה בודדת דורסת אותו לעצמה בלי להשפיע על אחרות
     - ``webapp/static/css/collections.css`` (וו דריסה לערכות מיובאות)
   * - ``--search-suggestion-text-override``
     - Level 3
     - הטקסט בהצעות ההשלמה של החיפוש הגלובלי. אותו מבנה בדיוק: ברשימה הלבנה, ובכוונה **ללא** ערך ברירת מחדל
     - ``webapp/static/css/global_search.css`` (וו דריסה לערכות מיובאות)
   * - ``--in-file-search-hit-bg`` / ``--in-file-search-hit-active-bg`` / ``--in-file-search-hit-text`` / ``--in-file-search-hit-halo``
     - Level 3
     - ההתאמות של החיפוש בתוך קובץ בתצוגה המרונדרת של דפדפן הריפו (:ref:`code-browser-rendered-search`): צהוב וטקסט שחור כמו שאר הדגשות החיפוש בדפדפן הריפו, והפעילה כתומה. אותו ערך בכל הערכות, ולכן **לא** ברשימה הלבנה. **הטבעת של הפעילה בשני צבעים בכוונה** — שחורה (``-text``) צמודה ולבנה (``-halo``) סביבה: אין צבע אחד שבולט על הרקע של התצוגה בכל ערכה (``--accent-blue`` נמדד 1.58:1 ב-rose-pine-dawn, ושחור 1.12:1 ב-high-contrast), ולכל רקע אחד משני הצבעים עומד ב-3:1 לפחות. ``test_the_active_ring_stands_out_in_every_theme`` מודד את זה בכל ערכה
     - ``webapp/static/css/repo-browser.css`` (הפלטה שב-``:root``)
   * - ``--first-steps-done`` / ``--first-steps-track`` / ``--first-steps-item-bg`` / ``--first-steps-item-border`` / ``--first-steps-muted-opacity``
     - Level 3
     - הצ'קליסט "צעדים ראשונים" בדשבורד (:ref:`webapp-first-steps`): הוי, מילוי פס ההתקדמות והפס של הצעד הבא, המסלול של הפס, והרקע והמסגרת של כל צעד. נגזרים מ-``--success``, ``--glass-hover``, ``--glass`` ו-``--glass-border`` של הערכה, ולכן **לא** ברשימה הלבנה. ל-High Contrast בלוק משלו: צהוב, שחור ולבן, ובלי שקיפות
     - ``webapp/templates/dashboard.html`` (בלוק ה-``<style>`` של הדשבורד: ``:root`` ו-``:root[data-theme="high-contrast"]``)
   * - ``--repo-md-code-block-bg-override`` / ``--repo-md-code-block-border-override``
     - Level 3
     - הרקע והגבול של בלוקי הקוד בתצוגת ה-Markdown של דפדפן הריפו. אותו מבנה: ברשימה הלבנה, ובכוונה **ללא** ערך ברירת מחדל
     - ``webapp/static/css/markdown-preview.css`` (וו דריסה לערכות מיובאות)
   * - ``--btn-primary-text-override``
     - Level 3
     - הטקסט של כפתור primary בכל מקום שבו ערכה מיובאת או משותפת צובעת אותו ב-``--primary``: כפתור שהוא קישור, "ערוך" ו"העתק קוד" בעמוד הקובץ, ומצבי פוקוס ולחיצה. אותו מבנה: ברשימה הלבנה, ובכוונה **ללא** ערך ברירת מחדל
     - ``webapp/static/css/dark-mode.css``, ``webapp/templates/base.html`` (``primary-btn-states-custom-type``), ``webapp/templates/view_file.html`` (וו דריסה לערכות מיובאות)

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
     - **אין לה בלוק ב‑**\ ``base.html``. הטוקנים מוגדרים ב‑``static/css/high-contrast.css`` ומושלמים ברמת הרכיב בשישה קבצים נוספים — ראו את ההערה מתחת לטבלה. אין גרדיאנטים

.. figure:: ../images/theme-classic-preview.svg
   :alt: סקיצה של ערכת Classic
   :width: 640px

   ערכת Classic מציגה כפתור ראשי לבן, רקע גרדיאנטי, ומסמך Markdown — בתצוגת המסמך ובתצוגה החיה — על נייר לבן (``--md-paper-bg``).

.. figure:: ../images/theme-high-contrast-preview.svg
   :alt: סקיצה של ערכת High Contrast
   :width: 640px

   ערכת High Contrast משתמשת רק בשחור, לבן וצהוב לפי WCAG 2.1 AA. כל שינוי חייב לשמור על יחס ניגודיות 4.5:1 לטקסט רגיל.

.. note::

   **High Contrast מתנהגת אחרת מכל שאר הערכות, וזה משפיע ישירות על כל רכיב חדש.**

   ``base.html`` **אינו** מגדיר לה טוקנים. ``static/css/high-contrast.css`` (נטען גלובלית) מגדיר בבלוק ``:root[data-theme="high-contrast"]`` רק את הטוקנים ``--primary``, ``--secondary``, ``--glass``, ``--glass-border``, ``--md-surface``, ``--md-text`` ו‑``--link-color`` — ואת השאר משלימים ברמת הרכיב: ``bookmarks.css``, ``collections.css``, ``global_search.css``, ``lang-badge.css``, ``markdown-enhanced.css`` ו‑``split-view.css``.

   **המשמעות המעשית:** ``--card-bg``, ``--card-border`` ו‑``--text-primary`` **אינם מוגדרים** בערכה הזו. רכיב שנשען עליהם מקבל את ה‑fallback שלו, ובעמוד שאינו טוען אחד מששת הקבצים לעיל התוצאה עלולה להיות בלתי קריאה — למשל כרטיס לבן עם גבול לבן. רכיב חדש שאמור לעבוד ב‑High Contrast צריך בלוק ``:root[data-theme="high-contrast"]`` משלו, בדיוק כפי שששת הקבצים האלה עושים.

Markdown Viewer ו‑Split View
----------------------------

- **הנייר והדיו של מסמך Markdown — עותק אחד, לתצוגת המסמך ולתצוגה החיה.** הצבעים של המסמך יושבים ב‑``webapp/static/css/md-content-colors.css``: הנייר (``--md-paper-bg`` ו‑``--md-paper-text`` על ``:root``), הטוקנים של כל ערכה על ``#md-content`` (קוד בשורה, בלוק קוד וצבעי התחביר, ציטוט, טבלה, סימון, Mermaid), והכללים שצובעים בהם את מה ש‑markdown-it מייצר, כולל הקישורים. ``md_preview.html`` טוען אותו בראש ``extra_css``, ו‑``_live_preview_styles.html`` טוען אותו בעמודי העריכה וההעלאה. במצב Markdown, ``setMarkdownContext`` ב‑``live-preview.js`` נותן ל‑canvas את ``id="md-content"`` — ולכן אותם כללים חלים עליו — ולמכל ``data-mode="markdown"``, שבו ``split-view.css`` צובע את כל אזור התצוגה בנייר. הפריסה של אותם אלמנטים משותפת באותה דרך, ב‑``md-content-layout.css`` (בבולט על הפריסה, בהמשך). ב‑``md_preview.html`` נשאר מה שרק תצוגת המסמך בונה או מציגה, וההערה בראש ``md-content-layout.css`` מפרטת מה. **למה עד אוקטובר 2026 התצוגה החיה הייתה כהה בכל ערכה:** ‏PR 2015 הציב על המכל ``data-theme="dark"``, וזה הכניס לתצוגה את כללי הטקסט של הערכות הכהות ב‑``dark-mode.css`` עם צבעי הטקסט של העמוד — ב‑Classic וב‑Ocean לבן — ו‑PR 2087 פתר את הלבן‑על‑לבן ברקע כהה קבוע (``--md-surface``). התווית הוסרה, והצבעים של המסמך משותפים: בלי זה, על נייר לבן הדיו של התצוגה החיה לא היה קריא (המדידה ב‑:doc:`/whats-new`, 2026-10-31). ``tests/test_live_preview_paper_browser.py`` משווה בדפדפן את התצוגה החיה לתצוגת המסמך בכל ערכה, כולל ערכה מיובאת בהירה.
- ``--md-surface`` ו‑``--md-text`` נשארים כהים גם בערכות בהירות, ואסור לרוקן אותם ב‑`:root`: בונה הערכות, גלריית הערכות ואינדקס התיעוד לאדמין קוראים אותם, והתצוגה החיה צובעת בהם את הרקע במצבי קוד ו‑HTML (``--split-preview-bg``).
- כפתור "רקע לבן" ב‑``md_preview.html`` פשוט מסיר מחלקות ``bg-sepia/light/medium/dark``. השתמשו בטוקנים כשהדבר מתאפשר, אך שמרו על Presets לפי `COLORS` בסקריפט – אלו חריגים שהוגדרו בכוונה.
- Live Preview (`split-view.css`) משתמש ב‑``--split-preview-*`` למסגרת, לשורות הסטטוס ולמצבי קוד ו‑HTML; במצב Markdown הוא על הנייר של המסמך (ראו למעלה). בורר הרקע (``bg-sepia`` ודומיו) קיים רק בתצוגת המסמך, ולכן מי שבחר בו רואה תצוגה חיה בנייר של הערכה. הוספת preset חדש, או הבאת הבורר לתצוגה החיה, מחייבת:
  1. הוספת המחלקה בקובץ התבנית.
  2. יצירת טוקן חדש ברמת Level 3 (``--split-sepia-bg``) אם נדרש.
  3. בדיקות ניגודיות ב‑High Contrast.
- **הפריסה של מסמך Markdown — עותק אחד, לתצוגת המסמך ולתצוגה החיה.** ריווח, כותרות, רשימות, ציטוט, טבלאות, תמונות, קוד בשורה ובלוק הקוד עם פס הכותרת שלו יושבים ב‑``webapp/static/css/md-content-layout.css``, שנטען באותם שני מקומות כמו ``md-content-colors.css`` ועובד באותה דרך: הכללים כתובים על ``#md-content``, וה‑canvas של התצוגה החיה מקבל את המזהה הזה במצב Markdown. בורר המזהה הוא גם מה שגובר על כלל האיפוס ``*`` שבבלוק ה‑``<style>`` של ``base.html``, שמוחק את ה‑margin וה‑padding — בלי זה ציטוט נראה כמו פסקה רגילה, ורשימה בלי תבליטים. ובאותה ספציפיות הכללים האלה גוברים גם על כללים של קבצים אחרים שחלים על אותם אלמנטים, למשל של האדמוניציות ב‑``markdown-enhanced.css``: הריווח מעל הפסקה הראשונה באדמוניציה הוא של ``#md-content p`` ולא של ``.admonition-content > *:first-child``, בשתי התצוגות. **למה עד אוקטובר 2026 התצוגה החיה נראתה אחרת מהמסמך:** הכללים ישבו ב‑``<style>`` של ``md_preview.html``, שאינו נטען בעמודי העריכה, ול‑``split-view.css`` היה בלוק תוכן משלו, עטוף ב‑``:where()``. שני העותקים נסחפו: בתצוגה החיה קוד בשורה קיבל ``word-break: break-word``, ובטבלה עמודה עם קוד בשורה נשברה כל אות או שתיים, בזמן שבתצוגת המסמך אותו קוד נשאר בשורה אחת והטבלה נגללת לרוחב; ובלוק קוד נראה שם כמו בדפדפן הריפו. הבלוק נמחק מ‑``split-view.css``, יחד עם הטוקנים ``--split-preview-code-bg`` ו‑``--split-preview-code-text`` שרק הוא קרא. ``tests/test_live_preview_paper_browser.py`` משווה בדפדפן, בכל ערכה, את הצבעים ואת הפריסה של האלמנטים שברשימת ``SELECTORS`` שבו בין התצוגה החיה לתצוגת המסמך, ובודק שקוד בשורה בתוך תא בטבלה נשאר בשורה אחת. ``tests/test_live_preview_blockquote_browser.py`` מודד את הפריסה בשני העמודים, בכל ערכה שברשימת ``THEMES`` שבו.
- **בלוק קוד — אותו בלוק בשתי התצוגות, והתלויות שעמודי העריכה מספקים לו.** ``webapp/static/js/md-code-blocks.js`` (``window.MdCodeBlocks.enhance``) עוטף כל ``pre`` ב‑``div.code-block`` ומוסיף מעליו פס כותרת (``.md-code-header``) עם שם השפה (``.md-code-lang``) וכפתור העתקה (``.md-copy-btn``), שהאייקונים שלו SVG בתוך הכפתור. ``md_preview.html`` קורא לו אחרי רינדור ה‑Mermaid, והתצוגה החיה קוראת לו מ‑``MarkdownLiveRenderer.enhance`` ב‑``live-preview.js``, כשהאפשרות ``documentCodeBlocks`` דלוקה, באותו סדר. רק ``LivePreviewController`` מדליק אותה: ``MarkdownLiveRenderer.enhance`` משמש גם את התצוגה המרונדרת בדפדפן הריפו ואת כרטיסי החיפוש בתיעוד, ושם נשאר הכפתור הקטן בפינת ה‑``pre`` (``.code-copy-btn`` עם ``bi-clipboard``), שמעוצב ב‑``markdown-preview.css``. כשהאפשרות דלוקה, ``highlightBlocks`` רק מדגיש ואינו בונה את הכפתור הקטן. עד אוקטובר 2026 הבלוק נבנה בתוך ``md_preview.html`` (``addCopyButtons``), והתצוגה החיה הציגה את הכפתור הקטן, כמו בדפדפן הריפו. את התלויות העמוד צריך לספק, ובעמוד העריכה ובעמוד ההעלאה הן מגיעות משני partials, ``_live_preview_styles.html`` ו‑``_live_preview_scripts.html``, ולא מרשימה שכל עמוד מחזיק לעצמו: שתי הרשימות שהיו שם חסרו את אותם דברים, בלי שום שגיאה — הקוד נראה כמו טקסט רגיל בגופן מונו, בלי צבעים, והכפתור יצא ריבוע ריק מתחת לקוד. התלויות: ``utils/safe-highlight.js`` (``highlightBlocks`` מדגיש רק דרך ``window.SafeHighlight``), ``md-code-blocks.js`` לפני ``live-preview.js`` (בלעדיו התצוגה החיה כותבת אזהרה לקונסול, והבלוק נשאר בלי מסגרת ובלי כפתור), ו‑``md-content-colors.css`` עם ``md-content-layout.css``. האייקונים של Bootstrap כבר לא נטענים בעמודים האלה: הם שימשו בתצוגה החיה רק את הכפתור הקטן. ``tests/sticky-notes-target.test.js`` בודק שכל עמוד שטוען את ``live-preview.js`` מספק את ההדגשה (אחרי פתרון ה‑``{% include %}``); שעמוד עם ``#livePreviewRoot`` טוען את ``md-code-blocks.js`` לפני ``live-preview.js``, ועמוד אחר שטוען את ``live-preview.js`` טוען את האייקונים; שכל עמוד עם ``#livePreviewRoot`` כולל את שני ה‑partials; ושתצוגת המסמך בונה את הבלוק מ‑``md-code-blocks.js`` ולא מעותק בתבנית. צבעי התחביר הם של המסמך: ``#md-content .hljs-*`` ב‑``md-content-colors.css`` קוראים את ``--hljs-*`` של כל ערכה, וגוברים בספציפיות על הצבעים של הבאנדל (``md_preview.bundle.css``, הערכה github-dark-dimmed של highlight.js); ערכה מיובאת מקבלת את צבעי התחביר שלה מה‑``syntax_css`` שלה, כמו בתצוגת המסמך. גם הרקע והמסגרת של הבלוק, של פס הכותרת ושל הכפתור הם הטוקנים של המסמך (``--md-code-*``). הבלוק כולו כתוב משמאל לימין (``direction: ltr`` על ``#md-content .code-block``), ולכן הכפתור בצד ימין של הפס גם בבלוק עברי, שרק ה‑``pre`` שלו מקבל ``rtl-code``. שורה ארוכה נגללת לרוחב בתוך הבלוק, מתחת לפס, והפס והכפתור לא זזים איתה. ``tests/test_live_preview_blockquote_browser.py`` מודד את הבלוק, את פס הכותרת ואת הכפתור בשני העמודים, בכל ערכה שברשימת ``THEMES`` שבו.
- **הקישורים במסמך, ובפרט ב‑High Contrast.** הכללים של ``#md-content a`` ב‑``md-content-colors.css`` — שחלים גם בתצוגה החיה — קוראים את ``--link-color`` (ראו בטבלת הטוקנים), וקו ה‑``::after`` שמתרחב בריחוף צבוע ב‑``currentColor``, כלומר בצבע הקישור. ב‑High Contrast זה לא מספיק: ``[data-theme="high-contrast"] a``, ``a:hover`` ו‑``a:focus`` ב‑``high-contrast.css`` הם ``!important``, בצבע שנבחר לרקע השחור של הערכה, והדף של המסמך נשאר לבן גם בה — כך שהכללים הרגילים הפסידו והקישור כמעט לא נראה. לכן ל‑``[data-theme="high-contrast"] #md-content a`` יש כלל ``!important`` משלו, עם קו תחתון. בין שתי הצהרות ``!important`` מכריעה הספציפיות, ובורר המזהה גובר על שלושתם, גם בריחוף ובפוקוס — אותו מנגנון של הקישורים בפתקים (ראו בהמשך). הכלל יושב ב‑``md-content-colors.css`` ולא ב‑``high-contrast.css``: ``tests/test_sticky_notes_link_color.py`` מתייחס לכל כלל ``a`` בקובץ ההוא ככלל שחל על כל העמוד, גם על הפתקים, שאינם בתוך ``#md-content``. ``tests/test_md_preview_link_color.py`` גוזר את היריבים מקבצי הערכות.
- ``theme_preview.html`` ו‑Reader modes ב‑``md_preview.html`` נשארים Hardcoded לצורכי תצוגת פלטות – אין להמיר אותם ל‑`var()` כדי לשמור על נאמנות ל‑brand colors.

הנחיות למפתחים (Best Practices)
--------------------------------

- ❌ אין לציין HEX בקבצי רכיבים (למעט חריגים מתועדים).  
  ✅ תמיד להשתמש ב‑``var(--token-name)`` ולוודא שהטוקן עלה לטבלת הרפרנס.
- כשצריך פס גלילה צר ברכיב מקומי:  
  - הגדירו ``::-webkit-scrollbar`` עם ``width``/``height`` על בסיס ``var(--scrollbar-width)``.  
  - הוסיפו ``scrollbar-width: thin`` כדי לכסות גם Firefox.
- כלל אצבע:  
  - צריך צבע שחוזר בכמה קומפוננטות → טוקן סמנטי (Level 2).  
  - צריך גוון שמזוהה עם רכיב מסוים (צלחמת חיפוש, טאב מסוים) → טוקן רכיב (Level 3) + Overrides.  
- Inline styles ב‑HTML/JS: צרו מחלקה ב‑CSS שמפנה ל‑``var()``. אם חייבים Inject דינמי (למשל Sticky Notes) – חשבו צבעים דרך טוקנים קיימים (`--text-on-primary`, `--danger-bg`).
- `color-mix()` (אופציונלי): עדיף על שקיפות ידנית כאשר צריך לשלב צבעים קיימים.
- ``[data-theme="..."]`` הוא הסלקטור היחיד לשינוי Theme. אין להשתמש שוב ב‑``prefers-color-scheme`` מלבד בקוד Legacy שכבר קיים ב‑``markdown-enhanced.css`` (TODO לעדכן).

.. important::

   **Whitelist חיוני לכל ערכה — אישית וציבורית כאחת**

   ``ALLOWED_VARIABLES_WHITELIST`` (ב-``services/theme_parser_service.py``) מסנן את הטוקנים
   בכל המסלולים: ייבוא ערכה אישית, עדכון ערכה קיימת ופרסום ערכה ציבורית. טוקן שאינו ברשימה
   נזרק בשקט, ונרשמת אזהרה בלוג.

   אם מוסיפים טוקן חדש שערכה אמורה להיות מסוגלת לקבוע — יש לעדכן גם את ה-whitelist,
   וגם את הרשימה ב-:doc:`/webapp/custom_themes_guide`.

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
  1. הוסיפו ערך ברירת מחדל ל‑``:root`` בתוך בלוק ה‑``<style>`` שב‑``webapp/templates/base.html``.
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

בדיקות חובה לפני Merge
----------------------

- מעבר ידני על כל 8 הערכות דרך Theme Wizard + בדיקה מהירה של `localStorage`.
- בדיקת Split View + Markdown Preview (כולל לחצן "רקע לבן", מצבי Reader).
- בדיקת Live Preview / Sticky Notes / Login alert / RTL. הגלילה החלקה כבויה כברירת מחדל (ראו :doc:`smooth-scrolling`); לבדיקה נקודתית שלה מוסיפים ``?smooth_debug=1`` לכתובת.
- בדיקת Collections, Bookmarks, אוספים משותפים וה‑Glass badges.
- בדיקת נגישות ב‑High Contrast (יחס ניגודיות 4.5:1, focus outline, קישורים).
- עוגנים לטסטי דפדפן: אלמנט שטסט צריך לזהות מקבל ``data-testid`` שמתאר את **המצב שרונדר** (למשל ``agg-time-not-measured``), לא את הניסוח. הטסט נתלה בו ולא במחרוזת UI בעברית — שינוי ניסוח לא מפיל טסט, רינדור של הענף הלא נכון כן. ``data-testid`` אינו hook ל‑CSS ואין לעצב לפיו. כשלאלמנט כבר יש חוזה סמנטי יציב (``href``, ``id``, ``name``) — משתמשים בו ולא מוסיפים ``data-testid``. תקדים: ``webapp/templates/profiler_dashboard.html``.
- בדיקת שאין HEX קשיחים בקבצים שנגעתם בהם (`rg "#[0-9a-fA-F]{3,6}" webapp/static/css/<file>.css`).
- בדיקת WCAG ל‑Markdown Viewer (``bg-sepia`` ועוד) + ווידוא ש‑`--md-surface` לא הוחלף בטעות.
- מעבר בין Themes בזמן Live Preview כדי לוודא שאין FOUC (שימרו על setAttribute מוקדם).

שימושים נוספים וחריגים
----------------------

.. warning::

   ⚠️ **שים לב:** Sticky Notes, Reader Modes (`md_preview.html`) והקובץ ``theme_preview.html`` נשארים Hardcoded בכוונה לצורכי Preset/Brand. אין להמיר אותם ל‑``var()`` עד שתתועד חלופה רשמית, אחרת נשבור תצוגות קיימות.

- Collections (`webapp/static/css/collections.css`) עדיין מכיל צבעים קשיחים ישנים – כל שינוי חייב להמיר ל‑`var()` לפי טבלת הטוקנים.
- **וו דריסה לערכה בודדת (Collections).** שם הקובץ בכרטיס אוסף הוא ``<a>``, ולכן ``dark-mode.css`` צובע אותו ב-``var(--primary)`` דרך ``[data-theme="custom"] a`` — ספציפיות שגוברת על כלל המחלקה שב-``collections.css``. כרטיס האוסף נשאר לבן גם בערכה כהה, כך שערכה שה-``--primary`` שלה בהיר מקבלת שם קובץ בלתי קריא. הפתרון אינו דריסה גורפת אלא **וו בהצטרפות מרצון**: שני כללים על ``.collection-card__link`` ועל ``.workspace-card__link`` — שני המסכים שמציגים שמות קבצים — קוראים ``var(--collections-link-override, <הערך שנצבע היום>)`` — ``--primary`` במצב רגיל, ``--primary-dark`` ב-``:hover``. **הטוקן חייב להישאר ללא ערך ברירת מחדל בשום מקום**, אחרת ה-fallback לא נכנס לפעולה וכל ערכה מושפעת. זה בדיוק מה שקרה בניסיון הראשון: ברירת מחדל שנקבעה ב-``:root[data-theme-type="custom"]`` שינתה את ה-``:hover`` גם בערכות שלא הצהירו, והורידה אותן מניגודיות 4.81 ל-1.00. ל-``:hover`` נדרש כלל נפרד כי ``[data-theme="custom"] a:hover`` ספציפי יותר. ראו :ref:`theme-variables-override-hook`.
- **וו דריסה לערכה בודדת (הצעות החיפוש הגלובלי).** אותו שורש, ברכיב אחר: ההצעות מרונדרות ב-``global_search.js`` כאלמנטי ``<a>``, ורקע התיבה הוא ``--solid-surface-bg`` שנשאר לבן בכל ערכה — ולכן ``[data-theme="custom"] a`` צובע טקסט בצבע המותג של הערכה על רקע שאינו שלה. נמדד בדפדפן על הדף המרונדר: ערכה שה-``--primary`` שלה לבן מקבלת ניגודיות 1.00, כלומר טקסט בלתי נראה עד שמעבירים עליו עכבר. הווו נבנה באותה צורה בדיוק — ``var(--search-suggestion-text-override, <הערך שנצבע היום>)`` — אבל כאן **שלושה** כללים ולא שניים, כי ל-``:focus-visible`` יש ערך משלו: ``.search-suggestion:focus-visible`` הוא (0,2,0) ומנצח כבר היום את כלל ה-``<a>`` שהוא (0,1,1), ולכן נצבע ב-``--suggestions-text`` ולא ב-``--primary``. **סדר הכללים אינו שרירותי:** ``:hover`` ו-``:focus-visible`` שווים בספציפיות (0,3,0), ולכן כלל ה-``:hover`` נכתב אחרון — כך המצב המשולב נשאר ``--primary-dark``, מה שנצבע שם היום. ``tests/services/test_theme_variables_search_suggestion_hook.py`` נועל את הסדר הזה. ראו :ref:`theme-variables-search-suggestion-hook`.
- **וו דריסה לערכה בודדת (בלוקי הקוד בדפדפן הריפו).** בערכה מיובאת, ``markdown-preview.css`` צובע את המעטפת של תצוגת ה-Markdown ב-``--bg-tertiary``, את בלוק הקוד ב-``--code-bg`` ואת הגבול שלו ב-``--border-color`` (דרך ``--md-preview-border``, ראו בהמשך). כל אחד מהם נגזר ממפתח אחר של VS Code, וכשהשלושה יוצאים באותו צבע — כמו ב-Cobalt Next — הבלוק נבלע בטקסט שסביבו. ``--code-bg`` עצמו לא נדרס, כי הוא צובע גם רכיבי קוד אחרים; במקומו שני טוקנים חדשים, ``--repo-md-code-block-bg-override`` ו-``--repo-md-code-block-border-override``. **הם נקראים בכלל הקיים** ``[data-theme="custom"] .markdown-preview-content pre`` (ו-``shared:``), ולא בכלל חדש עם ``[data-theme-type="custom"]``: זה הכלל שצובע היום את הבלוק בערכה מיובאת, (0,2,1) מול (0,1,1) של הכלל הכללי, ובורר זהה פירושו מפל זהה לערכה שאינה מצהירה. הגבול נקבע ב-``border-color`` ולא ב-``border``, והעובי והסגנון נשארים של הכלל הכללי. ראו :ref:`theme-variables-repo-md-code-block-hook`.
- **וו דריסה לערכה בודדת (הטקסט בכפתורי primary).** כפתור primary שהוא ``<a>`` נצבע בערכה מיובאת דרך ``[data-theme="custom"] a`` שב-``dark-mode.css``, אותו שורש של ווי האוספים והחיפוש שמעל. בנוסף, ``.file-primary-action`` ב-``view_file.html`` צובע ב-``--primary`` את "ערוך" ו"העתק קוד", ובלוק ``primary-btn-states-custom-type`` ב-``base.html`` צובע בו, ב-``!important``, את מצבי הפוקוס, הלחיצה וההשבתה של כל כפתור primary, ואת כל כפתורי ה-primary בערכה משותפת. ``--btn-primary-text-override`` נקרא בכל אחד מהם, עם fallback לערך שהוא צבע עד היום. בכללים הקיימים הטוקן נקרא בלי לשנות את הבורר. לקישורים נוספו ב-``dark-mode.css`` שני כללים, רגיל ו-``:hover``, והבוררים שלהם הם הבוררים של כללי הקישורים עצמם עם ``:where(.btn-primary)``. ``:where()`` אינו מוסיף ספציפיות, והכללים כתובים מיד אחרי כללי הקישורים, ולכן הם חלים בדיוק במקום שבו כללי הקישורים צובעים היום, וכלל ספציפי יותר ממשיך לנצח. **לא** ``[data-theme-type="custom"]``, בכוונה: ``previewTheme`` ב-``base.html`` מחליף את ``data-theme`` לערכה מובנית ומשאיר את ``data-theme-type``, וכלל שנשען עליו היה חל גם על התצוגה המקדימה הזו. ``tests/services/test_theme_variables_btn_primary_text_hook.py`` נועל את החוזה. ראו :ref:`theme-variables-btn-primary-text-hook`.
- **הקובץ המשותף של תצוגת ה-Markdown, וטוקני הרכיב שלו.** ``markdown-preview.css`` נטען בדפדפן הקוד וגם בעמוד הקבצים לאדמין, בכרטיסי החיפוש בתיעוד (:ref:`global-search-docs`). כל עמוד שטוען אותו יורש מ-``base.html``, אבל רק דפדפן הקוד טוען את ``repo-browser.css``, ורק שם מוגדרים ``--border-color`` ו-``--accent-blue``, בפלטה שב-``:root`` שלו. כלל משותף שקרא אותם ישירות נראה תקין בדפדפן הקוד בלבד: בעמוד הקבצים הקישורים יצאו בצבע הטקסט והגבולות ב-``currentColor`` (נמדד בדפדפן). לכן הקובץ מצהיר על ``.markdown-preview-container`` על טוקנים של הרכיב, ``--md-preview-border`` ו-``--md-preview-accent``, שקוראים את השניים עם fallback של אותה פלטה, והכללים המשותפים קוראים רק אותם. ההכרעה היא ירושה, כמו בתקדים של ``sticky-notes.css`` שבהמשך: ``--border-color`` של ערכה מיובאת גובר בכל עמוד, ובעמוד שלא מגדיר אותו נכנסת הפלטה של דפדפן הקוד. **זה חריג מתועד לאיסור על HEX בקבצי רכיבים:** ה-fallback הוא עותק של הפלטה, ו-``tests/test_markdown_preview_tokens.py`` שומר שהוא שווה לערך שב-``:root`` של ``repo-browser.css``, ושכל טוקן שכלל משותף קורא מוגדר בכל עמוד שטוען את הקובץ — ב-``base.html`` או בקובץ עצמו. וו דריסה (``--*-override``) אינו מוגדר בשום מקום בכוונה, ולכן נקרא תמיד עם fallback. **מה נמדד ב-7.10.2026:** בדפדפן הקוד אין אף הבדל לפני ואחרי, בכל הערכות; ובערכה מיובאת אמיתית הכרטיס זהה לדפדפן הקוד, גם בדגימת פיקסל של המשטח.
- Split View ו‑Markdown Enhanced משתמשים ב‑``--split-*`` ו‑``--md-*`` בהתאמה – הוסיפו טוקן לפני שמוסיפים Class חדש.  
- Sticky Notes, Reader Modes (`md_preview.html`) וה‑``theme_preview.html`` הם חריגים שנשארים Hardcoded כדי לשמור על תצוגת Preset.  
- **הכיוון ההפוך, וזה מה שהסעיף הזה לא אמר עד היום: משטח קשיח לא רק נמנע מ-**\ ``var()``\ **— הוא חייב לספק ערך לכל טוקן שכל רכיב שמוצג בתוכו קורא.** האיסור למעלה מכסה את מה שהמשטח עצמו מצהיר, ולא את מה שיושב בתוכו. רכיב משותף שמרונדר על משטח קשיח ממשיך לקרוא טוקני ערכה — והם נבחרו לרקע אחר לגמרי, כלומר צבע שגוי בדיוק במידה שהרקע לא השתנה. **קובץ CSS משותף אינו מספיק כאן**, וההיסק "זה אותו קוד ולכן זה נראה אותו דבר" נכון למבנה ולמידות ושגוי לצבע.

  התקדים: ``sticky-notes.css`` מצהיר על ``--sticky-mark-bg``/``--sticky-mark-line`` עבור ``.sticky-md-mark``, ועל ששת הטוקנים של הבלוק המתקפל — ``--details-bg``, ``--details-border``, ``--details-hover``, ``--summary-bg``, ``--summary-color``, ``--summary-arrow-color`` — שכולם בבעלות ``markdown-enhanced.css``. ההצהרות יושבות על ``.sticky-note``, וההכרעה היא **ירושה ולא ספציפיות**: הצהרת הערכה יושבת על ``<html>``, ולכן האב הקרוב מנצח בתת-העץ ואין צורך ב-``!important``. (‏``.sticky-md-mark`` כן צריך אותו, אבל מסיבה אחרת לגמרי — שם קיימים כללי ערכה שמכוונים ל-``mark`` **כאלמנט**.)

  **ומה שנמדד, כי בלי מדידה זה נראה תקין:** לפני התיקון יצא הטקסט בגוף הבלוק בניגוד של 1.09:1 בערכה מיובאת כהה, והחץ 2.09:1 **גם בערכה בהירה**. ‏``--summary-bg`` הוא גרדיאנט, ולכן הוא נוחת ב-``background-image`` ו-``background-color`` נשאר ``transparent`` — כלומר בדיקה שמודדת רק ``background-color`` עוברת גם על הקוד השבור. **צבע על משטח כזה נמדד בדגימת פיקסל.**

  **ומקרה שני של כללי ערכה שמכוונים לאלמנט — הקישור, ושם** ``!important`` **לבדו אינו מספיק.** קישור בפתק (``.sticky-md-link``) צבוע ב-``--note-link``, שמוצהר על ``.sticky-note`` כמו הדיו. היריבים הם ``[data-theme="…"] a`` ו-``a:hover`` ב-``dark-mode.css``, ו-``[data-theme="high-contrast"] a``, ``a:hover`` ו-``a:focus`` ב-``high-contrast.css`` — והאחרונים הם ``!important`` בעצמם. בין שתי הצהרות ``!important`` מאותו מקור מכריעה הספציפיות (CSS Cascade 5, סעיף 6.1), ולכן הפתרון של ``.sticky-md-mark`` — ``!important`` על מחלקה אחת, (0,1,0) — מנצח את כללי ``dark-mode.css`` ומפסיד ל-(0,1,1) של High Contrast: בבדיקה חד-פעמית ב-12.10.2026 נקרא ``getComputedStyle`` של קישור כזה בכרומיום 141, והוא נשאר צהוב. לכן הכלל בפתק כותב ``.sticky-note`` לפני המחלקה, ול-``:hover`` ול-``:focus`` יש בורר משלהם, כדי לעלות על (0,2,1) **ממש, ולא בשוויון**: ``note_board.html`` ו-``repo/base_repo.html`` טוענים את ``sticky-notes.css`` לפני קבצי הערכות, ו-``md_preview.html`` אחריהם, כך שבספציפיות שווה התוצאה הייתה תלויה במשטח. באותה בדיקה עלו גם שתי דליפות של מצב הריחוף שאינן ``color``: ``a:hover`` של ``dark-mode.css`` מוריד את ה-``opacity``, ו-``text-decoration`` של High Contrast הוא קיצור ``!important`` שמאפס גם את ``text-decoration-thickness`` — ולכן הקו המתעבה בריחוף צריך ``!important`` משלו. ``tests/test_sticky_notes_link_color.py`` גוזר את כללי ה-``a`` מקבצי הערכות ודורש שכל אחד מהם יפסיד בפתק, בחשיבות ובספציפיות.
- **מלכודת ספציפיות ב-**\ ``transition``\ **, שכל רכיב חדש נתקל בה.** ``dark-mode.css`` מגדיר ``transition`` על ``[data-theme="dark"] *`` (וכן ``dim``, ``nebula``, ``custom`` ו-``shared:``). הספציפיות של ``[attr] *`` שווה לזו של מחלקה יחידה, והקובץ נטען אחרי בלוק ``extra_css`` שבתבנית — ולכן כלל ``transition`` שנכתב על מחלקה אחת בקובץ רכיב **נדרס בשקט בכל הערכות הכהות**, וההנפשה פשוט לא רצה. הכשל שקט לחלוטין: אין שגיאה, ובדיקה בערכה בהירה עוברת. הפתרון שבשימוש ב-``toast.css`` הוא חזרה על שם המחלקה (``.ck-toast.ck-toast``), שמעלה את הספציפיות בלי ``!important``. אותו טיפול נדרש גם לכלל ה-``prefers-reduced-motion`` של הרכיב, שאחרת נדרס באותה דרך.
- **מלכודת קופסת גלילה ב-**\ ``overflow-x: hidden``\ **, שמשביתה כל אלמנט צמוד.** למניעת גלילה לרוחב כותבים ``overflow-x: clip``, ולא ``hidden``. לפי CSS Overflow 3, ``hidden`` בציר אחד הופך את הציר השני ל-``auto``, ולכן המיכל נעשה קופסת גלילה גם כשהוא אף פעם לא גולל, כי הגובה שלו הוא גובה התוכן. לפי CSS Position 3, ``position: sticky`` נצמד לקופסת הגלילה הקרובה, ולכן אלמנט צמוד בתוך מיכל כזה נגלל עם העמוד ולא נצמד — בלי שום שגיאה. ``clip`` חותך לרוחב בדיוק אותו דבר בלי להפוך את המיכל לקופסת גלילה, ואת ``hidden`` כותבים לפניו כנפילה-לאחור לדפדפן שאינו מכיר ``clip``. כך היו שבורים הסרגלים הצמודים בתצוגת קובץ, בתצוגת Markdown ובבונה הערכות, בגלל ``.main-content, .container`` ב-``base.html``; ומאותה סיבה ``global_search.css`` כותב ``clip`` ב-``.search-and-filters .filters-row``. **ושני דברים שבאים עם אלמנט שבאמת נצמד:** יעד שגוללים אליו עם ``block: 'start'`` — עוגן, תוכן עניינים — צריך ``scroll-margin-top`` בגובה הסרגל בזמן שהסרגל צמוד, אחרת הוא נוחת מתחתיו (ב-``md_preview.html`` הגובה נמדד ומפורסם כ-``--md-toolbar-h``, כי בטלפון הסרגל נשבר לכמה שורות, והרווח חל רק באותו תנאי שבו הסרגל נצמד — ראו בהמשך, הצמדה רק בזמן חיפוש); ופריט grid צמוד נע — נמדד בכרומיום — בתוך כל מיכל ה-grid ולא רק בתוך התא שלו, ולכן כשהעמודות נערמות הוא עלול לגלוש על הפריט שמתחתיו (ב-``theme_builder.html`` ההצמדה מבוטלת ב-``@media`` שבו הפריסה נערמת). ואת העמוד עצמו גולל ``body`` ולא החלון, וקוד שמניח אחרת לא עושה כלום — ראו Issue #3534. **והמעבר ל-**\ ``clip``\ **משחרר גם את מה שהמיכל חתך עד אז, ולא רק אלמנטים צמודים:** החלוניות של התפריטים בסרגל העליון נחתכו עד אז בתוך ``.navbar > .container``, ואחרי המעבר יצאו מתחת לסרגל אל מעל התוכן — ונפלו לשכבה שמתחת לתוכן (ראו בהמשך, ``z-index`` על אלמנט שאינו ממוקם). לכן אחרי שינוי כזה בודקים גם רכיבים צפים שבתוך המיכל, לא רק את מה שצמוד.
- ``z-index`` **על אלמנט שאינו ממוקם — מת; והורה שיוצר הקשר ערימה כולא בתוכו את ה-**\ ``z-index``\ **של הילדים.** לפי MDN, ``z-index`` חל על אלמנט ממוקם (``position`` שאינו ``static``) ועל פריטי flex ו-grid, ו-``transform`` או ``backdrop-filter`` שאינם ``none`` יוצרים הקשר ערימה, שרק בתוכו יש משמעות ל-``z-index`` של הצאצאים. ``.navbar`` שילב את שלושתם: ה-``z-index`` נשאר עליו מהימים שבהם היה צמוד (#559 הסיר את ההצמדה), ומאז שהוא ``static`` הערך מת; וה-``transform`` וה-``backdrop-filter`` שלו כלאו בתוכו את חלוניות הקיצורים והאפקטים. ``.main-content`` ממוקם עם ``z-index`` משלו ולכן מצויר מעל הסרגל, וכל חלק של חלונית שיצא מתחת לסרגל נראה — אבל הנגיעה בו הלכה לתוכן. **הפתרון אינו להרים את הסרגל לתמיד:** כפתורים וחלונות צפים שבתוך ``.main-content`` — ``#toggleBookmarksBtn`` בתצוגת קובץ, וחלונות שנפתחים על כל המסך — נשענים על כך שהסרגל מתחתם, ונמדד שהרמה קבועה מסתירה אותם בראש העמוד. במקום זה הסרגל עולה רק בזמן שאחד התפריטים שלו פתוח (``.navbar:has(...)`` ב-``base.html``), והמצב נקרא מה-``.active`` שמציג את התפריט ולא מדגל נפרד. תפריט צף חדש בסרגל נכנס לרשימה שם, ו-``tests/test_navbar_and_search_bars_css.py`` שומר עליה. ובאותו תיקון: חלונית האפקטים מעוגנת ב-``left`` ולא ב-``inset-inline-end``, כי ל-``.fun-mode-dropdown`` יש ``direction: ltr`` משלו, וצד לוגי מתורגם לפי הכיוון של האלמנט עצמו — כלומר ל-``right``, שפתח אותה אל מחוץ למסך.
- **הצמדה רק בזמן חיפוש.** הכלי הוא ``:has()`` עם ``:placeholder-shown``. סרגל חיפוש שצמוד תמיד מסתיר את ראש התוכן לאורך כל הגלילה, וחיפוש אינו שכיח מספיק כדי להצדיק את זה. לכן ``.editor-toolbar`` נצמד רק תחת ``.editor-toolbar:has(#codeSearchInput:not(:placeholder-shown))`` (ב-``view_file.html``), ו-``.md-editor-toolbar`` באותה צורה עם ``#mdSearchInput`` (ב-``md_preview.html``) — כלומר רק כשיש טקסט בתיבה — ובלי חיפוש הם נגללים עם העמוד. שני דברים שהתנאי נשען עליהם: לתיבה חייב להיות ``placeholder``, כי בלעדיו ``:placeholder-shown`` לעולם לא מתקיים והסרגל היה נצמד תמיד; ו-``:placeholder-shown`` מתעדכן גם כשהקוד מרוקן את התיבה (``input.value = ''``) — נמדד, ולכן ✕ משחרר את הסרגל בשתי התצוגות. דפדפן שאינו מכיר ``:has()`` מדלג על הכלל כולו, והסרגל פשוט לא נצמד.
- ``toast.css`` מגדיר את משפחת ``--ck-toast-*`` (Level 3), ונטען רק בעמודים שמציגים טוסט (``window.ckToast`` מ-``toast.js``) — ולא ב-``base.html``. מרחב השמות שלו נפרד מ-``.notification`` בכוונה: ``bookmarks.css`` ו-``multi-select.css`` מגדירים את הסלקטור ההוא בשניהם, עם ערכים סותרים. את ערכי הרקע והטקסט הוא מעתיק מ-``bookmarks.css`` במקום לגזור אותם מ-``--bg-secondary``; הגזירה נבדקה ונפסלה כי ב-Classic היא יורדת מתחת ליחס הניגודיות הנדרש.
- `global_search.css` הינו דוגמה מצוינת לרכיב Component Tokens – כאשר מוסיפים תכונה חדשה (למשל badge נוסף) המשיכו את התבנית שם.  
- Collections / Split View / Markdown Enhanced מוזכרים בדף זה כדי שמפתחים ידעו להצליב בין הרכיבים ולזהות אילו טוקנים משותפים.

קישורים ונספחים
----------------

.. seealso::

   - ``webapp/FEATURE_SUGGESTIONS/css_refactor_plan.md`` – רשימות טוקנים מלאות לפי קובץ.
   - ``FEATURE_SUGGESTIONS/css_refactor_plan.md`` – תקציר עסקי ובדיקות QA.
   - ``FEATURE_SUGGESTIONS/theme_matrix.md`` – טבלת כיסוי טוקנים מקוצרת.
   - ``webapp/FEATURE_SUGGESTIONS/webapp_theme_palettes.md`` – פירוט צבעים וערכי Markdown.
   - ``webapp/templates/base.html`` – בלוק ה‑``<style>``: מקור כל ה‑Primitives ו‑``:root[data-theme]``, קביעת ``data-theme`` מוקדמת, וה‑Theme Wizard.
   - ``webapp/static/css/dark-mode.css`` – שימוש בטוקנים עבור רכיבי Dark/Dim/Nebula.
   - ``webapp/static/css/high-contrast.css`` – טוקני הבסיס של High Contrast, ובנוסף התאמות פוקוס/Outline. שאר הטוקנים שלה מושלמים ברמת הרכיב.
   - ``webapp/static/css/global_search.css``, ``split-view.css``, ``bookmarks.css``, ``collections.css``, ``toast.css`` – דוגמאות מעשיות לטוקנים.
   - Issue #2097 – מפרט Theme Builder (טוקנים במיקוד, UI/Backend/API, נגישות ו‑Reset flow).

לשאלות תיעוד/Testing יש לפנות לערוץ Frontend או לפתוח Issue חדש עם קישור לדף זה. הקפידו לעיין גם ב‑`FEATURE_SUGGESTIONS/css_refactor_plan.md` לפני שינויים רוחביים בקוד.
