# דו"ח Audit פורנזי: Data Layer

**תאריך:** 2026-01-01
**סטטוס:** 🚨 קריטי
**מחבר:** CodeBot (AI DBA)

---

## 📊 תקציר מנהלים

סריקת הקוד חשפה **שימוש נרחב בפטרנים הרסניים לביצועים**. הבעיה המרכזית היא הסתמכות על אגרגציות כבדות (Sorting + Grouping) כדי למצוא את "הגרסה האחרונה" של קובץ, במקום לשמור את המידע הזה בצורה מנורמלת או להשתמש באינדקסים יעילים.

כמו כן, קובץ `webapp/app.py` מכיל מאות קריאות ישירות ל-DB שעוקפות את ה-Repository, מה שמקשה על תחזוקה ואופטימיזציה מרכזית.

---

## 🚨 ממצאים קריטיים (P0 - Immediate Action Required)

| מיקום | קוד / פילטר | הסכנה | Explain & Analysis | המלצה |
|-------|-------------|-------|-------------------|-------|
| `webapp/app.py:7134` | `aggregate(pipeline, allowDiskUse=True)` | **Regex Scan על שדה Code**. ה-Pipeline משתמש ב-`$regexFind` על תוכן הקובץ המלא ללא פילטר סלקטיבי מספיק. | **COLLSCAN + CPU Spike**. MongoDB יסרוק את כל המסמכים (או את כולם עבור המשתמש), יעלה את ה-`code` לזיכרון ויריץ עליו Regex. ה-`allowDiskUse=True` הוא עדות לכך שהשאילתה חורגת מ-100MB RAM. | **חובה:** שימוש ב-Text Search (`$text`) או מנוע חיפוש ייעודי (Elasticsearch). אם חייבים ב-Mongo: הגבלת החיפוש רק לקבצים פעילים ושימוש ב-Trigram Index (Atlas Search). |
| `database/repository.py:2166` (`list_public_snippets`) | `$or: [{"title": /q/}, {"description": /q/}, {"code": /q/}]` | **Unanchored Regex על 3 שדות**. שימוש ב-`$or` מונע שימוש יעיל באינדקס רגיל, ו-Regex ללא `^` מחייב סריקה מלאה. | **COLLSCAN**. כל חיפוש ציבורי יסרוק את כל ספריית ה-Snippets. ככל שהספרייה תגדל, ה-Endpoint יקרוס. | **חובה:** Text Index על שלושת השדות: `createIndex({title: "text", description: "text", code: "text"})`. החלף את השאילתה ב-`$text: {$search: q}`. |
| `database/repository.py:1013` (`get_regular_files_paginated`) | `group` (latest) → `match` ($not regex) → `sort` | **פילטור אחרי אגרגציה כבדה**. השאילתה שולפת את *כל* הקבצים, מוצאת גרסה אחרונה לכולם, ורק אז מסננת לפי תגיות. | **Memory Exhaustion**. אי אפשר לאנדקס את הפילטר הזה כי הוא קורה אחרי שלב ה-Group. עבור משתמש עם 10k קבצים, המערכת תעבד את כולם לכל עמוד. | **חובה:** הוספת שדה `is_latest: true` במסמך בזמן שמירה, או שמירת "מצביע לראש" (Head Pointer). זה יאפשר שליפה ישירה: `find({user_id: ..., is_latest: true, tags: ...})`. |

---

## ⚠️ בעיות חמורות (P1 - Scalability Risks)

| מיקום | קוד / פילטר | הסכנה | Explain & Analysis | המלצה |
|-------|-------------|-------|-------------------|-------|
| `database/repository.py:839` (`get_user_files`) | `match` → `sort` → `group` (first) → `sort` (update) | **Blocking Sort + Group**. פטרן ה-"Latest Version" מחייב מיון של כל ההיסטוריה לפני הקיבוץ. | **SORT (Blocking)**. מונגו חייב למיין את כל המסמכים בזיכרון (או בדיסק) לפני ה-Grouping. איטי מאוד למשתמשים כבדים. | **אינדקס:** `createIndex({user_id: 1, is_active: 1, file_name: 1, version: -1})` יאפשר למונגו להשתמש באינדקס למיון הראשון. עדיף: שדה `is_latest` מנוהל. |
| `webapp/app.py:4523` (`active_jobs`) | `aggregate`: `match(date)` → `group(job_id)` → `sort(calc_field)` | **מיון על שדה מחושב**. המיון `last_started_at` קורה רק אחרי ה-Group. | **Memory Sort**. הנתונים מקובצים בזיכרון ואז ממוינים. אם יש הרבה ג'ובים בטווח הזמן, זה יעמיס על ה-CPU. | **אינדקס:** `createIndex({started_at: -1})` הוא המינימום. שקול שמירת `last_run` בטבלת `jobs` נפרדת (נרמול) לשליפה מהירה. |
| `database/repository.py:473` (`get_favorites`) | `match` → `sort` → `group` → `sort` | **Double Sort**. מיון לפי שם+גרסה, ואז מיון מחדש לפי תאריך הוספה למועדפים. | **Inefficient**. כמו ב-`get_user_files`, זהו פטרן יקר. | **אינדקס:** `createIndex({user_id: 1, is_favorite: 1, is_active: 1, file_name: 1, version: -1})`. |

---

## 🔸 אופטימיזציות נדרשות (P2 - Hygiene & Efficiency)

| מיקום | תיאור | המלצה |
|-------|-------|-------|
| `webapp/app.py` (כללי) | **Direct Access Chaos**. מאות קריאות `db.users.find` מפוזרות בקוד ה-Webapp. | **Refactor:** העברת כל הקריאות ל-`UserRepository`. זה יאפשר caching מרכזי וניטור. |
| `database/repository.py:891` (`search_code`) | שימוש ב-`$text` ואחריו `sort({file_name: 1})`. | מיון טקסטואלי אחרי חיפוש Text מבטל את השימוש ב-Score. אם המשתמש מחפש רלוונטיות, המיון מפריע. אם רוצים מיון, צריך לוודא שהתוצאות מוגבלות. |
| `services/query_profiler_service.py` | שליפות לוגים עם מיון `execution_time_ms`. | הוספת אינדקס `createIndex({execution_time_ms: -1})` לקולקשן הלוגים כדי שהפרופיילר עצמו לא יפיל את ה-DB. |

---

## 💡 המלצת ארכיטקטורה (The "Is Latest" Flag)

הבעיה החוזרת בכל השאילתות היא **שליפת הגרסה האחרונה**.
במקום לחשב את זה ב-Read Time עם Aggregation יקר:

1.  הוסיפו שדה `is_latest: boolean` ל-Schema.
2.  בזמן `save_code_snippet`:
    - עדכנו את הגרסה הקודמת ל-`is_latest: false`.
    - שמרו את החדשה עם `is_latest: true`.
3.  **התוצאה:** כל ה-Aggregations הכבדים הופכים ל-`find({user_id: ..., is_latest: true})` פשוט ומהיר בטירוף.

---

### רשימת אינדקסים חסרים (להרצה מיידית):

```javascript
// 1. עבור חיפוש קבצים מהיר ופתרון ה-Blocking Sort
db.code_snippets.createIndex({user_id: 1, is_active: 1, file_name: 1, version: -1});

// 2. עבור מועדפים (Covered Query פוטנציאלי)
db.code_snippets.createIndex({user_id: 1, is_favorite: 1, is_active: 1, file_name: 1, version: -1});

// 3. עבור חיפוש טקסטואלי (פותר את ה-Regex האיום)
db.snippets_collection.createIndex({title: "text", description: "text", code: "text"});

// 4. עבור הפרופיילר
db.slow_queries_log.createIndex({execution_time_ms: -1});
db.slow_queries_log.createIndex({timestamp: -1});
```
