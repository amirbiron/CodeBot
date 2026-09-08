מדריך סגנונות וארכיטקטורת Markdown
==================================
:summary: המסמך הזה הוא Source of Truth לעיצוב וארכיטקטורת Markdown בפרויקט. הוא מיועד למפתחים ול‑QA ויזואלי.

המסמך הזה הוא **Source of Truth** לעיצוב וארכיטקטורת Markdown בפרויקט.
הוא מיועד למפתחים ול‑QA ויזואלי.

.. note::
   רינדור Reader Mode מתבצע בצד השרת ע״י Python‑Markdown, ובצד הלקוח נטענים
   סגנונות CSS (וגם Mermaid). בתצוגת ``md_preview`` יש גם רינדור צד‑לקוח,
   אבל ה‑Reader הוא בסיס הייחוס היציב לבדיקה ויזואלית.

1. סקירה טכנית (Architecture)
------------------------------

**Pipeline קצר:**

1. Markdown Text
2. Python‑Markdown (Extensions)
3. HTML
4. CSS Styling (Variables + Components)
5. User Display

**Mermaid Diagram (תהליך הרינדור):**

.. code-block:: text

   flowchart LR
     A[Markdown Text] --> B[Python Renderer (Extensions)]
     B --> C[HTML]
     C --> D[CSS Styling (Variables)]
     D --> E[User Display]

.. note::
   הדיאגרמה כתובה ב‑Mermaid אך מוצגת כטקסט כדי למנוע אזהרות Pygments ב‑RTD.
   אם רוצים רינדור ויזואלי, אפשר להוסיף תוסף Mermaid לתיעוד.

**Extensions פעילים (מקור אמת: `app.py`):**

.. list-table:: Python‑Markdown Extensions
   :header-rows: 1

   * - Extension
     - תפקיד
   * - ``extra``
     - חבילת הרחבות בסיסיות (למשל fenced code, attr_list, def_list). נותנת תשתית רחבה לפיצ׳רים נפוצים.
   * - ``codehilite``
     - הדגשת קוד בעזרת Pygments ועטיפה ב‑``.codehilite``.
   * - ``tables``
     - טבלאות בסגנון Markdown.
   * - ``sane_lists``
     - תיקון התנהגות רשימות (מונע שבירה בין פסקאות).
   * - ``toc``
     - יצירת תוכן עניינים (anchors לכותרות).
   * - ``admonition``
     - תיבות הודעה בסגנון ``!!! note``.

**Highlighting:**

- המנוע: **Pygments**
- קלאס יעד: ``.codehilite``
- סגנון פעיל: ``friendly`` (הזרקה דרך Python)

2. מערכת הצבעים (Reader Mode)
------------------------------

**משתני רקע חדשים (Reader Mode):**

- ``--reader-bg-light``: ``#f5e6d3``
- ``--reader-bg-medium``: ``#e8d4b0``
- ``--reader-bg-dark``: ``#d4b896``

**רקע בסיסי (Sepia):**

- ``#fdf6e3`` (משמש גם ל־``reader-bg-sepia``)

**Highlighter (Pygments):**

- סגנון: ``friendly``
- מקור אמת: ``app.py`` (`_PYGMENTS_PREVIEW_FORMATTER`)

3. קטלוג רכיבים (Component Gallery)
------------------------------------

Admonitions
^^^^^^^^^^^

**דוגמה (Markdown):**

.. code-block:: markdown

   !!! note
       זו הודעת Note.

   !!! tip
       טיפ קצר.

   !!! warning
       אזהרה חשובה.

   !!! danger
       הודעת Danger.

**CSS מקור:** ``webapp/static/css/markdown-enhanced.css``

Tables
^^^^^^

**דוגמה (Markdown):**

.. code-block:: markdown

   | Feature | Status |
   |---------|--------|
   | Reader  | ✅     |
   | Export  | ⏳     |

.. warning::
   נכון לעכשיו אין Zebra Rows מובנה. אם צריך פסי זברה, יש להוסיף
   ב‑``reader.css`` (למשל ``tbody tr:nth-child(even)``).

**CSS מקור:** ``webapp/templates/md_preview.html`` (חלק ה‑Table Styles)

Task Lists
^^^^^^^^^^

**דוגמה (Markdown):**

.. code-block:: markdown

   - [x] משימה שהושלמה
   - [ ] משימה פתוחה

.. note::
   ב‑Reader Mode הרינדור נעשה בצד השרת, ולכן תיבות משימה דורשות
   הרחבה ייעודית אם רוצים להמיר ל‑checkbox אמיתי.

Mermaid
^^^^^^^

**דוגמה (Markdown):**

.. code-block:: markdown

   ```mermaid
   flowchart LR
     A --> B
   ```

.. warning::
   Mermaid צריך theme ניטרלי על רקעים בהירים. ב‑Reader Mode
   האתחול הוא ``theme: 'neutral'`` + Overrides ב‑``reader.css``
   כדי לשמור על קווים וטקסט כהים.

Details / Summary
^^^^^^^^^^^^^^^^^

**דוגמה (HTML בתוך Markdown):**

.. code-block:: html

   <details class="markdown-details">
     <summary class="markdown-summary">לחץ לפתיחה</summary>
     <div class="details-content">תוכן מוסתר</div>
   </details>

**CSS מקור:** ``webapp/static/css/markdown-enhanced.css``

Code Blocks
^^^^^^^^^^^

**דוגמה (Markdown):**

.. code-block:: markdown

   ```python
   def hello():
       return "שלום"
   ```

**CSS מקור:** ``reader.css`` + ה‑CSS של Pygments (``friendly``).

Highlight (``==מארקר==``)
^^^^^^^^^^^^^^^^^^^^^^^^^

**דוגמה (Markdown):**

.. code-block:: markdown

   טקסט עם ==הדגשת מארקר== באמצע המשפט.

הרכיב הזה קיים **רק בצד הלקוח**, ולכן הוא היוצא מן הכלל היחיד בעמוד הזה שאין לו
מקבילה ב‑Reader Mode. ל‑Python‑Markdown לא נטען ``pymdownx.mark``, ולכן שם
``==טקסט==`` מוצג כטקסט גולמי. מי שבודק ויזואלית צריך לדעת את זה מראש: פער בין
התצוגות כאן אינו באג ברינדור.

**מקור:** ``webapp/static/js/md-mark-plugin.js`` — תוסף ``markdown-it`` יחיד, משותף
לתצוגת המסמך (``md_preview.html``) ול‑Live Preview (``live-preview.js``). כל תבנית
שטוענת אחד משניהם חייבת לטעון גם אותו, לפניו.

.. warning::
   התוסף בנוי על מנגנון הדלימיטרים התקני של ``markdown-it`` — ``scanDelims``,
   ``state.delimiters`` ו‑``postProcess`` שרשום על ``ruler2`` — במבנה של
   ``rules_inline/strikethrough.mjs`` שבספרייה. **אין לקרוא ל**\ ``inline.parse``
   **מתוך כלל inline**: היא מריצה את שלבי הסיום על מערך הטוקנים המשותף ומקצרת אותו,
   והאינדקסים של דלימיטרים חיצוניים (``**``) מצביעים אז מעבר לסופו. הגרסה הקודמת
   עשתה בדיוק את זה, והפילה את כל התצוגה על כל מסמך שהכיל הדגשה ואחריה מארקר באותה
   פסקה. ``tests/md-mark-plugin.test.js`` שומר על ההתנהגות.

4. הנחיות למפתחים (Best Practices)
-----------------------------------

- **לא להשתמש ב‑Inline Styles בתוך Markdown.**
- שינוי צבעים/רקעים נעשה ב‑``reader.css`` או ``markdown-enhanced.css`` בלבד.
- שמרו על התאמה בין Reader Mode ל‑Classic Theme כדי לשמר עקביות ויזואלית.

.. note::
   אם מוסיפים רכיב חדש, חובה לעדכן גם את מסמך ה‑Source of Truth הזה
   כדי ש‑QA ידע בדיוק מה אמור להופיע ובאילו קבצים.
