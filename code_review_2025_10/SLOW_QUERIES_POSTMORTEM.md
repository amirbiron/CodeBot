# 🐢 סיכום בעיות שאילתות איטיות ואינדקסים - PR #2506-2514

**תאריך:** 9 בינואר 2026  
**PR מקורי:** Query Performance Profiler עבור MongoDB

---

## 📋 תוכן עניינים

1. [סקירה כללית](#סקירה-כללית)
2. [בעיות שזוהו ותוקנו](#בעיות-שזוהו-ותוקנו)
3. [בעיות פתוחות שדורשות טיפול](#בעיות-פתוחות-שדורשות-טיפול)
4. [המלצות לפעולה](#המלצות-לפעולה)
5. [לוג השינויים](#לוג-השינויים)

---

## 🎯 סקירה כללית

במהלך פיתוח ה-Query Performance Profiler זוהו מספר בעיות ביצועים משמעותיות בשאילתות MongoDB. חלקן תוקנו, אך **הניתוח העדכני מראה שיש עדיין בעיות משמעותיות שדורשות טיפול**.

### סטטיסטיקה מהלוגים האחרונים (09/01/2026 18:37-19:11)

| קולקשן | כמות אירועים | זמן ממוצע (ms) | סטטוס |
|--------|-------------|---------------|-------|
| `users` | ~50+ | 240-505 | 🔴 קריטי |
| `note_reminders` | ~40+ | 215-257 | 🔴 קריטי |
| `service_metrics` | ~30+ | 223-255 | 🟡 בינוני |
| `scheduler_jobs` | ~100+ | 209-251 | 🔴 קריטי (בוט) |
| `job_trigger_requests` | ~50+ | 209-352 | 🔴 קריטי (בוט) |
| `code_snippets` | ~15+ | 236-900 | 🟡 בינוני |
| `announcements` | ~5+ | 220-254 | 🟡 בינוני |
| `shared_themes` | ~5+ | 235 | 🟡 בינוני |

---

## ✅ בעיות שזוהו ותוקנו

### 1. אינדקס `code_snippets` בסדר הפוך

**הבעיה:**  
אינדקס `active_recent_idx` נוצר עם `created_at` ראשון במקום `is_active`, מה שגרם ל-COLLSCAN.

**מה נעשה:**
- PR #2506: ניסיון ראשון - מחיקה ויצירה מחדש
- PR #2507: יצירת אינדקס חדש `active_recent_v2` עם הסדר הנכון

**תוצאה:** ✅ תוקן

```javascript
// הסדר הנכון:
{ "is_active": 1, "created_at": -1 }
```

---

### 2. דפוס `$or` שהורס ביצועי אינדקס

**הבעיה:**  
שאילתות השתמשו בדפוס שמונע שימוש יעיל באינדקס:
```javascript
"$or": [{"is_active": true}, {"is_active": {"$exists": false}}]
```

**מה נעשה:**
- PR #2508: יצירת endpoints לאבחון ומיגרציה
  - `/admin/diagnose-slow-queries` - אבחון
  - `/admin/fix-is-active?action=migrate` - מיגרציה

**תוצאה:** ✅ תוקן (לאחר הרצת המיגרציה)

---

### 3. הפרופיילר קורס על שאילתות מצונזרות

**הבעיה:**  
כשלוחצים "נתח" על שאילתה איטית, MongoDB קיבל `"$limit": "<value>"` במקום מספר.

**מה נעשה:**
- PR #2512: הוספת `_fix_pipeline_for_explain` ב-`services/query_profiler_service.py`

```python
def _fix_pipeline_for_explain(pipeline):
    # מחליף "<value>" במספרים תקינים
    # $limit → 10, $skip → 0, $sample.size → 10
```

**תוצאה:** ✅ תוקן

---

### 4. COLLSCAN על `job_trigger_requests`

**הבעיה:**  
Polling תכוף גורם ל-COLLSCAN על שדה `status`.

**מה נעשה:**
- PR #2514: יצירת אינדקס `status_idx` על `{ "status": 1 }`
- Endpoint `/admin/create-job-trigger-index` לביצוע מיידי

**תוצאה:** ⚠️ נוצר אך עדיין נראות שאילתות איטיות בלוגים

---

## 🔴 בעיות פתוחות שדורשות טיפול

### 1. קולקשן `users` - קריטי!

**דפוסי שאילתות איטיות:**
```javascript
// נראה בתכיפות גבוהה מאוד
{"user_id": "<value>"}  // find + update
```

**זמן ביצוע:** 240-505ms  
**תדירות:** עשרות פעמים בדקה

**המלצה:**
```javascript
// וודא שקיים אינדקס:
db.users.createIndex({ "user_id": 1 }, { unique: true, name: "user_id_idx" })
```

---

### 2. קולקשן `note_reminders` - קריטי!

**דפוסי שאילתות איטיות:**
```javascript
// Webapp - polling כל דקה
{
  "user_id": "<value>",
  "status": {"$in": ["pending", "snoozed"]},
  "remind_at": {"$lte": "<value>"},
  "ack_at": null
}

// Bot - push notifications
{
  "ack_at": null,
  "status": {"$in": ["pending", "snoozed"]},
  "remind_at": {"$lte": "<value>"},
  "needs_push": true
}
```

**זמן ביצוע:** 215-257ms  
**תדירות:** גבוהה מאוד

**המלצה:**
```javascript
// אינדקס מורכב לתמיכה בשני הדפוסים
db.note_reminders.createIndex({
  "user_id": 1,
  "status": 1,
  "remind_at": 1,
  "ack_at": 1
}, { name: "reminders_lookup_idx" })

// אינדקס נפרד ל-push
db.note_reminders.createIndex({
  "needs_push": 1,
  "status": 1,
  "remind_at": 1,
  "ack_at": 1
}, { name: "reminders_push_idx" })
```

---

### 3. קולקשן `scheduler_jobs` - קריטי (בוט)!

**דפוסי שאילתות איטיות:**
```javascript
{"next_run_time": {"$lte": "<value>"}}
{"next_run_time": {"$ne": null}}
```

**זמן ביצוע:** 209-251ms  
**תדירות:** כל 15 שניות!

**המלצה:**
```javascript
db.scheduler_jobs.createIndex({ "next_run_time": 1 }, { name: "next_run_idx" })
```

---

### 4. קולקשן `job_trigger_requests` - קריטי (בוט)!

**למרות שנוצר אינדקס, עדיין רואים:**
```javascript
{"status": "<value>"}  // find
{"status": "<value>", "created_at": {"$lt": "<value>"}}  // update
```

**זמן ביצוע:** 209-352ms

**המלצה:**
```javascript
// אינדקס מורכב שתומך בשני הדפוסים
db.job_trigger_requests.createIndex(
  { "status": 1, "created_at": 1 },
  { name: "status_created_idx" }
)
```

---

### 5. קולקשן `job_runs`

**דפוסי שאילתות איטיות:**
```javascript
{"run_id": "<value>"}  // update
{"status": "<value>", "started_at": {"$lt": "<value>"}, "stuck_reported_at": {"$exists": false}}
```

**המלצה:**
```javascript
db.job_runs.createIndex({ "run_id": 1 }, { unique: true, name: "run_id_idx" })
db.job_runs.createIndex(
  { "status": 1, "started_at": 1, "stuck_reported_at": 1 },
  { name: "stuck_jobs_idx" }
)
```

---

### 6. קולקשן `service_metrics`

**הבעיה:**  
Insert operations לוקחות ~224ms - זה לא קשור לאינדקסים אלא לכתיבה.

**המלצה:**
- שקול batching של מטריקות
- או כתיבה אסינכרונית לקיו

---

### 7. קולקשנים נוספים שדורשים בדיקה

| קולקשן | שאילתה | אינדקס מומלץ |
|--------|--------|-------------|
| `announcements` | `{is_active: true}` | `{ is_active: 1 }` |
| `shared_themes` | `{is_active: true}` | `{ is_active: 1 }` |
| `remember_tokens` | `{token, user_id}` | `{ token: 1, user_id: 1 }` |
| `recent_opens` | `{user_id, file_name}` | `{ user_id: 1, file_name: 1 }` |
| `markdown_images` | `{snippet_id, user_id}` | `{ snippet_id: 1, user_id: 1 }` |
| `file_bookmarks` | `{user_id, file_id}` | `{ user_id: 1, file_id: 1 }` |

---

## 📝 המלצות לפעולה

### דחיפות גבוהה (לביצוע מיידי)

1. **יצירת אינדקסים חסרים:**
   ```javascript
   // הרץ את הפקודות הבאות ב-MongoDB shell או צור endpoint admin
   
   // 1. users
   db.users.createIndex({ "user_id": 1 }, { unique: true })
   
   // 2. note_reminders
   db.note_reminders.createIndex({
     "user_id": 1, "status": 1, "remind_at": 1, "ack_at": 1
   })
   db.note_reminders.createIndex({
     "needs_push": 1, "status": 1, "remind_at": 1, "ack_at": 1
   })
   
   // 3. scheduler_jobs
   db.scheduler_jobs.createIndex({ "next_run_time": 1 })
   
   // 4. job_trigger_requests - אינדקס מורכב
   db.job_trigger_requests.createIndex({ "status": 1, "created_at": 1 })
   
   // 5. job_runs
   db.job_runs.createIndex({ "run_id": 1 }, { unique: true })
   db.job_runs.createIndex({ "status": 1, "started_at": 1 })
   ```

2. **עדכון `database/manager.py`:**
   - הוסף את כל האינדקסים ליצירה אוטומטית בהפעלה

### דחיפות בינונית

3. **אופטימיזציית Polling:**
   - הגדל את הinterval של `pending_job_triggers` מ-15 שניות ל-30 שניות
   - שקול מעבר ל-Change Streams במקום polling

4. **Batching ל-service_metrics:**
   - במקום insert יחיד, אגור מטריקות ושלח בbatch כל כמה שניות

### דחיפות נמוכה

5. **ניטור מתמשך:**
   - השתמש בדשבורד הפרופיילר למעקב אחרי שיפורים
   - הגדר התראות על שאילתות מעל 200ms

---

## 📜 לוג השינויים

| תאריך | PR | תיאור | סטטוס |
|-------|-----|-------|-------|
| 09/01/2026 | #2506 | תיקון אינדקס `code_snippets` - ניסיון 1 | ❌ נכשל |
| 09/01/2026 | #2507 | תיקון אינדקס `active_recent_v2` | ✅ הצליח |
| 09/01/2026 | #2508 | אבחון דפוס `$or` + מיגרציה | ✅ הצליח |
| 09/01/2026 | #2512 | תיקון `_fix_pipeline_for_explain` | ✅ הצליח |
| 09/01/2026 | #2514 | אינדקס `job_trigger_requests.status` | ⚠️ חלקי |

---

## 🔍 איך לאמת שהתיקונים עבדו

1. **בדוק את הלוגים:**
   ```bash
   # חפש שאילתות איטיות בקולקשן ספציפי
   grep "slow_query_detected" logs.txt | grep '"collection": "users"' | wc -l
   ```

2. **השתמש בדשבורד הפרופיילר:**
   - היכנס ל-`/admin/profiler`
   - סנן לפי קולקשן
   - לחץ "נתח" לראות את ה-Explain Plan

3. **בדוק אינדקסים קיימים:**
   ```javascript
   db.collection_name.getIndexes()
   ```

4. **הרץ explain ידני:**
   ```javascript
   db.users.find({"user_id": "test"}).explain("executionStats")
   // חפש: "stage": "IXSCAN" (טוב) vs "COLLSCAN" (רע)
   ```

---

## 📞 צוות אחראי

- **אינדקסים ו-DB:** @amirbiron
- **Query Profiler:** cursor-agent

---

*מסמך זה נוצר אוטומטית ב-09/01/2026 ויש לעדכנו לאחר ביצוע התיקונים.*
