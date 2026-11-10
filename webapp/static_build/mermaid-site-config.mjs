// התצורה של Mermaid באתר — מקור יחיד לכל מי שמצייר תרשים מהבאנדל.
//
// ``md-preview-entry.js`` חושף את ``mermaidSiteConfig`` כ-``window.mermaidSiteConfig``, ליד ``window.mermaid``, ושני
// המקומות שמציירים תרשימים קוראים ממנו: תצוגת המסמך (``md_preview.html``) והתצוגה החיה (``live-preview.js``: עמוד
// העריכה, העורך הציבורי והייצוא המעוצב). כל מי שיש לו ``window.mermaid`` יש לו גם את התצורה, כי שניהם באים מאותו
// קובץ. עד נובמבר 2026 כל אחד מהם כתב את ``startOnLoad`` ואת ``securityLevel`` בעצמו.
//
// **למה בכל קריאה ל-``initialize`` ולא פעם אחת.** ב-``mermaid@11.12.0`` ‏``initialize`` מחליף את כל התצורה:
// ``setSiteConfig`` (``src/config.ts``) מתחיל כל פעם מברירות המחדל של Mermaid ומחיל עליהן רק את מה שהועבר. הגדרה
// חד-פעמית הייתה נמחקת ב-``initialize`` הבא, למשל כשהייצוא מרנדר בערכה אחרת.
//
// **תרשים בודד יכול לשנות את זה.** ``render`` מאפס את ההנחיות של התרשים הקודם ומחיל את של התרשים הנוכחי מעל התצורה
// הזו (``processAndSetConfigs``), ו-``flowchart`` אינו ברשימת המפתחות המוגנים (``secure``). לכן
// ``%%{init: {"flowchart": {"wrappingWidth": 250}}}%%`` בראש התרשים גובר על ``MERMAID_WRAPPING_WIDTH``, לתרשים
// ההוא בלבד. ‏``securityLevel`` כן מוגן, ותרשים אינו יכול לשנות אותו.
//
// הבדיקות: ``tests/md-preview-mermaid-site-config.test.js`` (התצורה, השימוש בה, והבאנדל שבריפו) ו-
// ``tests/test_mermaid_label_wrap_browser.py`` (התוויות בדפדפן, כולל הנחיה של תרשים).

/**
 * רוחב הגלישה של תוויות ב-flowchart, בפיקסלים: תווית רחבה ממנו נשברת לשורות ברוחב הזה, וצרה ממנו נשארת בשורה אחת.
 * ברירת המחדל של Mermaid היא 200 (``flowchart.wrappingWidth`` ב-``defaultConfig``). Mermaid קורא את הערך הזה גם
 * בצורות המשותפות שלו, ולכן הוא חל גם על תוויות בתרשימים אחרים שמשתמשים בהן.
 */
export const MERMAID_WRAPPING_WIDTH = 400;

/**
 * התצורה ל-``mermaid.initialize``, בערכה הנתונה (``'dark'`` / ``'default'`` — כל מקום מחליט לפי העמוד או לפי ערכת
 * הקובץ). אובייקט חדש בכל קריאה: Mermaid מעתיק אותו, ואין סיבה שקורא אחד ישנה את מה שקורא אחר יקבל.
 */
export function mermaidSiteConfig(theme) {
  return {
    startOnLoad: false,
    securityLevel: 'strict',
    theme,
    flowchart: { wrappingWidth: MERMAID_WRAPPING_WIDTH },
  };
}
