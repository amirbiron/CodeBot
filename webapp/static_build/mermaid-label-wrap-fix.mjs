// תוסף esbuild שמתקן בתוך הבאנדל את ההחלטה של Mermaid מתי לשבור שורה בתווית — mermaid-js/mermaid#7794.
//
// **הבאג.** ``addHtmlSpan`` ב-Mermaid (``packages/mermaid/src/rendering-util/createText.ts``) מודד תווית HTML עם
// ``max-width`` של רוחב הגלישה (``flowchart.wrappingWidth``), ועובר למצב גלישה — ``white-space: break-spaces`` ברוחב
// הזה — רק כש-``getBoundingClientRect().width`` **שווה בדיוק** לרוחב. בכרומיום עם יחס פיקסלים שאינו שלם (טאבלט
// ב-2.2, זום של הדפדפן) המדידה של תווית שנחסמה ב-``max-width`` חוזרת עם שארית של נקודה צפה — בתצוגת המסמך,
// בכרומיום עם ``--force-device-scale-factor=2.2``, נמדד 200.00010681152344 מול 200; השארית תלויה גם במקום של
// האלמנט בעמוד — השוויון נכשל, והתווית נשארת בשורה אחת ב-``nowrap``. ה-``foreignObject`` מקבל את הרוחב החסום, והטקסט שארוך
// ממנו נחתך בקצה: בעברית — האותיות האחרונות של המשפט, בצד שמאל ("לארכיו" במקום "לארכיון").
//
// **התיקון.** "המדידה נחסמה ב-max-width" נבדקת בסובלנות של פיקסל: ``bbox.width >= width - 1``. השארית שנמדדה
// קטנה בסדרי גודל מפיקסל, ותווית שבאמת צרה מהרוחב בפחות מפיקסל עוברת למצב גלישה ונשארת בשורה אחת — כי היא נכנסת
// ברוחב. זו ההצעה באישו עצמו, ושלושה PRים פתוחים שם מציעים סובלנות דומה (#8233, ‏#8242, ‏#8609); אף אחד מהם לא
// מוזג, וגם ב-``mermaid@12.3.0`` (הגרסה האחרונה בזמן הכתיבה) הבדיקה עדיין ``===``.
//
// **למה בבנייה ולא בזמן ריצה.** ``addHtmlSpan`` היא פונקציה פנימית בתוך הבאנדל, ואין לה תצורה: שום הגדרה של
// ``mermaid.initialize`` ושום CSS לא משנים את ההחלטה הזו. התיקון חל על כל מי שטוען את ``md_preview.bundle.js`` —
// תצוגת המסמך (``md_preview.html``), התצוגה החיה (``live-preview.js``: עמוד העריכה, העורך הציבורי והייצוא המעוצב).
//
// **נכשל בקול, ולא מדלג בשקט.** הטקסט שמוחלף מוגדר מילה במילה (``STRICT_WRAP_CHECK``), מתוך ``mermaid@11.12.0``.
// אם שדרוג של Mermaid ישנה אותו, או יעביר את ``addHtmlSpan`` לקובץ שהתוסף אינו רואה, הבנייה נכשלת עם הסבר — אחרת
// הבאנדל היה נבנה בלי התיקון, והתוויות היו חוזרות להיחתך בלי שאיש ישים לב. ואם Mermaid תיקן את הבדיקה בעצמו — מוחקים
// את התוסף הזה ואת השימוש בו ב-``build-md-preview.mjs``.
//
// הבדיקות: ``tests/md-preview-mermaid-label-wrap.test.js`` (התוסף, והבאנדל שבריפו) ו-
// ``tests/test_mermaid_label_wrap_browser.py`` (התוויות עצמן, בכרומיום עם יחס פיקסלים 2.2).

import fs from 'node:fs/promises';

/** הבדיקה כפי שהיא כתובה ב-``mermaid@11.12.0``, ‏``dist/chunks/mermaid.core/chunk-*.mjs``, בתוך ``addHtmlSpan``. */
export const STRICT_WRAP_CHECK = 'if (bbox.width === width) {';

/** מה שנכנס במקומה. */
export const TOLERANT_WRAP_CHECK = 'if (bbox.width >= width - 1) {';

/** הסימן שהקובץ הזה הוא זה שמגדיר את ``addHtmlSpan`` — רק בו מחפשים את הבדיקה. */
const ADD_HTML_SPAN_DEFINITION = 'async function addHtmlSpan(';

/** קובצי ה-ESM של Mermaid, שמהם esbuild בונה את הבאנדל (``exports`` של החבילה מפנה ל-``dist/mermaid.core.mjs``). */
const MERMAID_DIST_MODULE = /[\\/]node_modules[\\/]mermaid[\\/]dist[\\/].+\.mjs$/;

const WHAT_TO_DO =
  'בדקו את addHtmlSpan ב-node_modules/mermaid: אם Mermaid כבר בודק שם בסובלנות (mermaid-js/mermaid#7794), ' +
  'מחקו את התוסף מ-build-md-preview.mjs; אחרת עדכנו את STRICT_WRAP_CHECK לנוסח החדש.';

export function mermaidLabelWrapFix() {
  return {
    name: 'mermaid-label-wrap-fix',
    setup(build) {
      let patchedFiles = 0;
      build.onStart(() => {
        patchedFiles = 0;
      });
      build.onLoad({ filter: MERMAID_DIST_MODULE }, async (args) => {
        const source = await fs.readFile(args.path, 'utf8');
        if (!source.includes(ADD_HTML_SPAN_DEFINITION)) {
          // קובץ אחר של Mermaid: esbuild טוען אותו מהדיסק כרגיל.
          return undefined;
        }
        const occurrences = source.split(STRICT_WRAP_CHECK).length - 1;
        if (occurrences !== 1) {
          return {
            errors: [{
              text: `mermaid-label-wrap-fix: הבדיקה "${STRICT_WRAP_CHECK}" נמצאה ${occurrences} פעמים ` +
                `בקובץ של addHtmlSpan (${args.path}), ולא פעם אחת. ${WHAT_TO_DO}`,
            }],
          };
        }
        patchedFiles += 1;
        return { contents: source.replace(STRICT_WRAP_CHECK, TOLERANT_WRAP_CHECK), loader: 'js' };
      });
      build.onEnd((result) => {
        if (result.errors.length > 0 || patchedFiles > 0) {
          return undefined;
        }
        return {
          errors: [{
            text: 'mermaid-label-wrap-fix: הבנייה לא טענה אף קובץ של Mermaid שמגדיר את addHtmlSpan, ולכן התיקון ' +
              `לא נכנס לבאנדל. ${WHAT_TO_DO}`,
          }],
        };
      });
    },
  };
}
