# CSS Color System – Quick Reference

מסמך זה משמש כשכבת חיבור בין מסמכי האפיון העסקיים בתיקיית `webapp/FEATURE_SUGGESTIONS/` לבין התיעוד הרשמי ב‑Docs.  
אם אתם נדרשים לרענן את תוכנית הריפקטור או להצליב החלטות עיצוביות, התחילו כאן ואז המשיכו למסמכים המלאים.

> **מקורות חובה:**  
> - מדריך היישום: [`docs/webapp/theming_and_css.rst`](../docs/webapp/theming_and_css.rst) – שכבות טוקנים, בדיקות, חריגים ודוגמאות קוד.  
> - ניתוח מפורט: [`webapp/FEATURE_SUGGESTIONS/css_refactor_plan.md`](../webapp/FEATURE_SUGGESTIONS/css_refactor_plan.md) – טבלאות מלאי, בעיות נגישות ותוכנית עבודה לפי קבצים.

## מה נשמר כאן?

1. **החלטות מוצר** – למה עברנו למערכת `data-theme` + CSS Variables, אילו תקלות היסטוריות חזרו שוב ושוב (FOUC, High Contrast, `global_search.css`).
2. **עקרונות תיעדוף** – Ocean/Forest/Classic חייבות Overrides מלאים; Split View ו‑Markdown נשארים כהים באמצעות `--md-*`; High Contrast נשען על צבעים מוחלטים.
3. **בדיקות חתימה** – מעבר בין 8 ערכות, Live Preview, Sticky Notes, Smooth Scroll Debug, Login alert, RTL, בדיקות WCAG.

## כאשר מבצעים שינוי Theme

- סמנו את השינוי גם במדריך התמות וגם במסמך האפיון הזה כדי לשמור על קישורים הדדיים.
- אם מגדירים טוקן חדש: עדכנו את הטבלה ב‑Docs, הוסיפו אותו ל‑`:root` ב‑`base.html`, ופתחו משימה נלווית ב‑plan מפורט לפי הקובץ/הרכיב.
- לכל שינוי ברכיבים רגישים (Split View, Markdown Viewer, Collections) יש להוסיף צ'ק בבדיקות.

## שאלות?

- דיונים אסטרטגיים → פותחים הערה במסמך זה.
- החלטות יישום וקוד → מתועדות ב‑[`docs/webapp/theming_and_css.rst`](../docs/webapp/theming_and_css.rst) וב‑PR הרלוונטי.
