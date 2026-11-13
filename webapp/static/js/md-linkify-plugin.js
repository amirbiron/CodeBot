/**
 * md-linkify-plugin.js — תוסף markdown-it: קישור אוטומטי נוצר רק מכתובת שנכתבה עם פרוטוקול, ולא מכל "שם.סיומת".
 *
 * **מה היה שבור.** הרנדררים של markdown-it בוובאפ נוצרים עם ``linkify: true``, כדי שכתובת שהודבקה
 * לטקסט תהפוך לקישור. הזיהוי עצמו נעשה ב-linkify-it, שגם **מנחש** כתובות בלי ``http://`` — האפשרות ``fuzzyLink``,
 * שדולקת אצלו כברירת מחדל (``defaultOptions`` ב-``node_modules/linkify-it/index.mjs``). הניחוש מקבל כל ``מילה.XX``
 * שבה XX הוא קוד מדינה בשתי אותיות (``tlds_2ch_src_re`` באותו קובץ), ועוד רשימה קצרה של סיומות כמו ``com`` ו-``org``.
 * באפליקציה ששומרת קבצים זה פוגע בדיוק בתוכן הנפוץ: ``readme.md`` (מולדובה), ``app.py`` (פרגוואי), ``run.sh``,
 * ``main.rs``, ``notes.org`` — כולם הוצגו כקישור (``readme.md`` ל-``http://readme.md``), והלחיצה הובילה לדף שגיאה של הדפדפן. שם קובץ
 * בעברית אף הומר לכתובת מקודדת (``xn--...``). ``.js``, ``.json`` ו-``.yaml`` לא נפגעו רק כי הן אינן סיומות של אתרים.
 *
 * **למה לא רשימת סיומות.** להוציא את ``md`` ו-``py`` מהרשימה היה טלאי: ``.org``, ``.com``, ``.pro`` ו-``.info`` הן גם
 * סיומות של קבצים וגם של אתרים, ואין דרך לדעת מהטקסט לבד למה הכותב התכוון. לכן התוסף מכבה את הניחוש כולו.
 *
 * **מה עדיין הופך לקישור.** כל מה שהכותב סימן בעצמו: כתובת עם פרוטוקול שיש לו כלל ב-``defaultSchemas`` של linkify-it
 * (``http:``, ``https:``, ``ftp:``, ``mailto:`` ו-``//``), כתובת מייל (``fuzzyEmail``, שנשאר דולק), ו-``[טקסט](כתובת)``,
 * שאינו תלוי ב-linkify בכלל. ``www.example.com`` ו-``example.com`` בלי פרוטוקול נשארים טקסט — החלטת המשתמש (נובמבר 2026):
 * כלל אחד וברור, ולא כלל נוסף ל-``www.`` כמו בגיטהאב.
 *
 * **למה קובץ משותף.** המקומות שיוצרים את markdown-it עם ``linkify: true`` — ``md_preview.html``, ``live-preview.js``
 * (``ensureRenderer``) ומסלול הגיבוי ב-``repo-browser.js`` (``renderMarkdownFallback``) — מתקינים את הקובץ הזה, ולכן
 * ההחלטה וההסבר כתובים פעם אחת. ``tests/md-linkify-plugin.test.js`` בודק שכל מקום שמדליק ``linkify`` מתקין את התוסף, ושכל
 * תבנית שמארחת רנדרר טוענת אותו.
 *
 * **איך.** ``md.linkify`` הוא מופע ה-linkify-it של אותו markdown-it — כל ``new MarkdownIt()`` יוצר מופע משלו (``this.linkify``
 * ב-``node_modules/markdown-it/lib/index.mjs``), ולכן ההגדרה לא דולפת לרנדררים אחרים בעמוד. ``set`` ממזג את האפשרויות
 * לתוך ``__opts__``, ו-``test`` קורא את ``fuzzyLink`` משם בכל קריאה, בלי מטמון שצריך לבנות מחדש. ההתנהגות מקובעת
 * ב-``tests/md-linkify-plugin.test.js``, כך ששדרוג של הספרייה שמשנה אותה יפיל את ה-CI.
 *
 * שימוש:
 *     md.use(window.MdLinkifyPlugin);
 * הבדיקות טוענות את הקובץ כמו הדפדפן, כ-script קלאסי בתוך ``vm``: ``package.json`` מוגדר ``"type": "module"``, ולכן
 * ``require`` לא היה עובד עליו.
 *
 * מקור לכל מה שכתוב כאן: linkify-it@5.0.0 ו-markdown-it@14.1.0 (``package-lock.json``), הקבצים שצוינו למעלה.
 */
(function (root) {
  'use strict';

  function linkifyPlugin(md) {
    md.linkify.set({ fuzzyLink: false });
  }

  if (root) {
    root.MdLinkifyPlugin = linkifyPlugin;
  }
})(typeof window !== 'undefined' ? window : null);
