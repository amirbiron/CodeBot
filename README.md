[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://python.org)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-blue.svg)](https://t.me/my_code_keeper_bot)
[![WebApp](https://img.shields.io/badge/WebApp-Visit-blueviolet.svg)](https://code-keeper-webapp.onrender.com)
[![MongoDB](https://img.shields.io/badge/MongoDB-Database-green.svg)](https://mongodb.com)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Docs](https://img.shields.io/badge/Docs-Website-blueviolet.svg)](https://amirbiron.github.io/CodeBot/)

<!-- CI/CD Badges -->
[![CI](https://github.com/amirbiron/CodeBot/actions/workflows/ci.yml/badge.svg)](https://github.com/amirbiron/CodeBot/actions/workflows/ci.yml)
[![Deploy](https://github.com/amirbiron/CodeBot/actions/workflows/deploy.yml/badge.svg)](https://github.com/amirbiron/CodeBot/actions/workflows/deploy.yml)
[![Security Scan](https://github.com/amirbiron/CodeBot/actions/workflows/security-scan.yml/badge.svg)](https://github.com/amirbiron/CodeBot/actions/workflows/security-scan.yml)
[![Performance Tests](https://github.com/amirbiron/CodeBot/actions/workflows/performance-tests.yml/badge.svg)](https://github.com/amirbiron/CodeBot/actions/workflows/performance-tests.yml)

[![Coverage](https://img.shields.io/codecov/c/github/amirbiron/CodeBot?branch=main)](https://app.codecov.io/gh/amirbiron/CodeBot/branch/main)

# CodeKeeper 💫

**המקום לשמור את הקוד, את מסמכי התיעוד ואת הרעיונות שלך, ולתת לסוכן ה-AI שלך לעבוד איתם.**

🌐 [לוובאפ](https://code-keeper-webapp.onrender.com) · 🤖 [לבוט בטלגרם](https://t.me/my_code_keeper_bot) · 📚 [לאתר התיעוד](https://amirbiron.github.io/CodeBot/)

---

## הבעיה: זיכרון מהסשן הקודם לא מספיק

זיכרון מתמשך לסוכני AI הוא נושא חם היום. אבל בפרויקט אמיתי, סשנים שבאים אחד אחרי השני בדרך כלל לא קשורים זה לזה: סשן אחד בונה פיצ'ר בממשק, הבא מתקן באג בשכבה אחרת, והשלישי נוגע במסד הנתונים. לכן זיכרון של "מה קרה בסשן הקודם" לא בהכרח עוזר לסשן הבא.

מה שכן חשוב הוא ממצא שהתגלה היום, ושיהיה נחוץ לסשן כלשהו בעתיד. לא בהכרח לסשן הבא, אלא לזה שימשיך לבנות באותו נושא, אולי בעוד שבוע ואולי בעוד חודשיים, ושההחלטות שלו צריכות להישען על מה שכבר נלמד.

## הפתרון: מסמך חי לכל נושא מורכב

**מה מתעדים?** ממצאים שכנראה יהיו חשובים לסשנים עתידיים: החלטות והסיבות להן, ארכיטקטורה, מגבלות ומלכודות שכבר נתקלתם בהן.

**איפה?** במסמך ב-CodeKeeper. הסוכן מחובר אליו, ולכן הוא יכול לקרוא את המסמך ולעדכן אותו בעצמו.

**מה השיטה?** לכל נושא מורכב בפרויקט, שהמידע ההיסטורי עליו ישנה החלטות במימוש של פיצ'רים עתידיים, פותחים מסמך משלו. ואז נותנים ל-Claude Code הנחיה קבועה:

> בכל סשן שבו מצאת ממצאים חשובים על נושא X, בסוף הסשן עדכן את מסמך X עם כל הממצאים האלה.

ומגדירים לו מה נחשב חשוב ומה לא, כדי שהמסמך יישאר ממוקד ולא יתמלא ברעש.

**מה מרוויחים?** מסמך חי לכל נושא שמצריך תיעוד, שמתעדכן בכל פעם שעולה משהו חדש. כשסשן עתידי ממשיך לבנות בנושא, מפנים אותו לקרוא את המסמך, והוא מתחיל עם כל מה שכבר נלמד. ואת אותו מסמך אפשר לשלוח לכל סוכן: כשרוצים להתייעץ על המשך הפיתוח, או כשרוצים בריף איכותי באמת, שנשען על כל ממצאי העבר הרלוונטיים, כדי לשלוח אותו ל-Claude Code למימוש.

---

## מה יש ב-Webapp

### 🗒️ קבצי קוד ומסמכי תיעוד

שמירת קטעי קוד ומסמכי מארקדאון עם תצוגה נוחה לקריאה, עם היסטוריית גירסאות, הדגשת תחביר, וחיפוש.

← [הקבצים שלי](https://code-keeper-webapp.onrender.com/files)

### 🗂️ "האוספים שלי"

יש עמוד עם רשימת האוספים שלך (את השמות אתה בוחר), ולכל אוסף יש עמוד משלו עם רשימת הקבצים שבו.

**מתי זה שימושי?**
- אוסף לכל פרויקט שאתה בונה, כך שכל מסמכי הפרויקט מרוכזים יחד.
- אוסף סקילים, שמרכז את כל קובצי הסקילים שלך.
- אוסף של מדריכים שימושיים שיש לך. וכן הלאה.

> 🤖 הסוכן שלך יכול לקרוא את רשימת האוספים, את רשימת הקבצים בכל אוסף ואת התוכן המלא של כל קובץ, ולעזור לך לפי מה שאתה צריך.

← [האוספים שלי](https://amirbiron.github.io/CodeBot/user/my_collections.html)


### 📝 סטיקי נוטס

> לפני הכל, כנס להגדרות הלוח ובחר פונט כתב יד לפתקים. זה נותן סטייל אישי, ביתי.

**מה עושים עם פתקים?**
הסטיקי הוא המקום לרעיונות, לאפיונים, לטיוטות, למשימות לסוכן, ולכל דבר שעולה לך לשמור. אפשר לפתוח לוח לכל נושא וליצור בו הרבה פתקים.
הפתקים תומכים ב-Markdown כמעט מלא, ויש בכל פתק מקום לעד 20,000 תווים, וזה הרבה. ואפשר לקבוע לפתק תזכורת ולקבל התראת פוש במועד. <!-- התקרה: MAX_NOTE_CHARS ב-sticky_notes_target.py -->

**ומה עם הסוכן?**
הסוכן יכול לקרוא פתק, לערוך אותו ולפתוח פתק חדש.

**מה עוד מגניב?**
- יש לך אפיון מלא עם הנחיות מימוש בתוך פתק, ואתה רוצה להוסיף הערה בלי לשנות כלום בתוכן? פותחים תגובה בשרשור על הפתק.
- בסשן הבא שתפתח, Claude Code יקבל מהשרת הנחיה כבר בתחילת הסשן לקרוא את התגובה בשרשור. אז שים לב לזה, ותחשוב מתי זה יעיל לך.
- ברגע ש-Claude Code מגיב בשרשור שלך, אתה מקבל התראת פוש בוובאפ. לוחצים על ההתראה, ומגיעים ישר לתגובה שלו.

← [סטיקי נוטס](https://amirbiron.github.io/CodeBot/user/sticky_notes.html)


### 🔍 החיפוש הסמנטי

חיפוש סמנטי בקבצים שלך ששמורים בCk: אתה לא מוצא מסמך, החיפוש הזה עובד עם ai ומחפש את המסמך לפי המשמעות ולא לפי מילים מדויקות.
> בפועל מניסיון אישי זה עובד טוב, שימושי.

← [החיפוש](https://amirbiron.github.io/CodeBot/webapp/global-search.html#global-search-smart)


### איך מחברים את הסוכן שלך

ההסבר המלא מופיע בעמוד ההגדרות בWebApp

← [איך מחברים](https://amirbiron.github.io/CodeBot/mcp-server.html#mcp-clients)

### 🔌 חיבור נוסף של הסוכן שלך

**ההנחיות לסוכן (הפריימר):** בעמוד ההגדרות יש שדה שבו כותבים הנחיות לסוכן. כל סשן חדש של Claude Code מקבל אותן אוטומטית בפתיחה, תוך עד דקה מהעריכה. זה המקום להנחיות שמתאימות לסשנים הקרובים, אבל לא שייכות ל-`CLAUDE.md` של הפרויקט, ולדברים שעדיף שלא יישבו בריפו. (דורש התקנה חד-פעמית של הוק קטן בפרויקט; ההוראות בהגדרות.) <!-- הדקה: CACHE_TTL_SECONDS ב-mcp_server/primer.py -->

← [הפריימר](https://amirbiron.github.io/CodeBot/mcp-server.html#agent-primer)


### 🛠️ כלי עזר לקוד

- **השוואה בין שני קבצים**, עם ההבדלים מודגשים. אפשר להשוות שני קבצים שמורים, או פשוט להדביק שני קטעים.
- **JSON formatter**, שמעצב קובץ JSON, בודק שהוא תקין, ומתקן את הבעיות הנפוצות: הערות, פסיקים מיותרים, מפתחות בלי מירכאות. <!-- התיקונים: fix_common_errors ב-services/json_formatter_service.py -->


### ערכות נושא
 יש כמה לבחירה, וזהירות: חלקן מהפנטות מהרגע הראשון. כל ערכה צובעת את כל הממשק וגם את הדגשת התחביר. אוהבים ערכה מסוימת ב-VS Code? אפשר לייבא אותה מקובץ ה-JSON שלה, דרך בונה ערכת הנושא בהגדרות.


### 💾 גיבויים

גיבוי של מה שיש לך בוובאפ: הקבצים, האוספים, הלוחות והפתקים. מגבים ידנית או מתזמנים גיבוי אוטומטי, מיומי ועד חודשי. הגיבוי נשמר בשרת, ב-Google Drive שלך, או יורד ישר למכשיר. ואם צריך לחזור אחורה, משחזרים בלחיצה. <!-- התזמונים: VALID_SCHEDULES ב-webapp/drive_backup_api.py -->

---

## מה יש בבוט

הבוט שומר על הריפו שלך בגיטהאב:

- **גיבוי ZIP של ריפו:** הבוט מוריד את הריפו ושומר את הגיבוי בשרת.
- **שחזור ריפו מגיבוי:** מגיבוי ששמור בשרת, או מקובץ ZIP שמעלים.
- **ריפו חדש מ-ZIP:** מעלים ZIP, והבוט יוצר ממנו ריפו חדש בגיטהאב, פרטי או ציבורי, עם אותו מבנה תיקיות.

כל הפקודות: שולחים `/help` לבוט.

---

## להרצה עצמית ולמפתחים

[התחלה מהירה](https://amirbiron.github.io/CodeBot/quickstart.html) · [התקנה](https://amirbiron.github.io/CodeBot/installation.html) · [משתני סביבה](https://amirbiron.github.io/CodeBot/environment-variables.html) · [ה-API של הוובאפ](https://amirbiron.github.io/CodeBot/webapp/api-reference.html) · [תרומה לפרויקט](https://amirbiron.github.io/CodeBot/contributing.html)

## יצירת קשר

💬 [קבוצת הטלגרם](https://t.me/+nh9skKRgTEVkZmJk) · 🐛 [פתיחת Issue בגיטהאב](https://github.com/amirbiron/CodeBot/issues)

## רישיון

MIT. ראו [LICENSE](LICENSE).
