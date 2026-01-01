
## Audit פורנזי – Data Layer (MongoDB)

נוצר אוטומטית בתאריך: **2026-01-01 06:17 UTC**.

### TL;DR (מה שהכי מפחיד אותי)
- **P0: שימוש ב-`$or`/`$exists` על `is_active` (או `is_active: {$ne: False}`) במסכים “חמים”** – שובר או מחליש אינדקסים. בפרויקט יש כבר tooling שמודה בזה (`/admin/fix-is-active`).
- **P0: חיפוש ב-UI עם `$regex` לא מעוגן ולא escaped** (למשל ב-`files`): עלול לגרום ל-`COLLSCAN` וגם לחשיפת Regex DoS.
- **P0: Scheduler/Push – שימוש ב-`$expr` להשוואת שדות (`last_push_success_at < remind_at`)**: כמעט תמיד “נופל” מהאינדקסים. עדיף לשנות סכימה/לוגיקה כדי להפוך את זה ל-query indexable.
- **P0: איסוף “מחיקה”/“Recycle bin” עם pull של הכל ואז sort בפייתון** (`Repository.list_deleted_files`) – יקר למשתמשים כבדים.

### מה נכלל כאן
- מיפוי נקודות מגע DB (ישיר + wrappers)
- ניתוח query shapes מסוכנים ($or/$in/$regex/$expr/$lookup וכו’)
- הצלבה מול אינדקסים קיימים בקוד
- המלצות אינדקס + ריווח/סיכון write overhead
- Appendix: רשימה מלאה של כל call-sites שמזוהים סטטית (קובץ+שורה+snippet)

### מגבלה חשובה לגבי Explain
בסביבת העבודה פה אין חיבור MongoDB אמיתי, אז **אין לי winningPlan אמיתי** לכל שאילתה.
במקום זה אני נותן:

- **Explain (סטטי/חשד)**: מה סביר שיקרה (COLLSCAN/SORT/OR וכו’)
- **איך להוציא winningPlan אמיתי בפרודקשן/סטייג’**: עם `QueryProfilerService.get_explain_plan()` או endpoints קיימים ב-`webapp/app.py` (למשל `/admin/diagnose-slow-queries`).

---

## אינדקסים קיימים (Inventory קצר)

### `database/manager.py` (האמת המרכזית של האפליקציה)
- `code_snippets`
  - `active_recent_fixed`: `{ is_active: 1, created_at: -1 }`
  - `user_favorites_idx`: `{ user_id: 1, is_favorite: 1, favorited_at: -1 }`
  - `user_active_file_latest_idx`: `{ user_id: 1, is_active: 1, file_name: 1, version: -1 }`
  - `full_text_search_idx`: text על `code/description/file_name`
- `large_files`
  - `user_active_date_large_idx`: `{ user_id: 1, is_active: 1, created_at: -1 }`
  - `user_lang_size_idx`: `{ user_id: 1, programming_language: 1, file_size: 1 }`
- `users`
  - `user_id_unique`
  - `username_unique` (partial)
- `job_trigger_requests`: `status_created_idx`: `{ status: 1, created_at: -1 }`
- ועוד: `service_metrics` TTL, `slow_queries_log` TTL, `markdown_images`, `file_bookmarks`, `scheduler_jobs` וכו’.

### אינדקסים מקומיים נוספים
- `webapp/push_api.py`: `push_subscriptions`
  - `user_endpoint_unique`: `{ user_id: 1, endpoint: 1 }`
  - `user_created_idx`: `{ user_id: 1, created_at: 1 }`
- `webapp/sticky_notes_api.py`: `sticky_notes`, `note_reminders`
  - `sticky_notes.user_file_created`: `{ user_id: 1, file_id: 1, created_at: 1 }`
  - `note_reminders.user_status_time_idx`: `{ user_id: 1, status: 1, remind_at: 1 }`
  - `note_reminders.remind_at_idx`: `{ remind_at: 1 }`

---

## ממצאים (High-signal)

> פורמט: Location | Snippet | Filter shape | סכנה | Wrapper | תדירות/מקור | Projection | Explain | המלצת אינדקס/שינוי | חומרה

### P0-1: “קלאסיקת ה-$or” על `is_active` שגורמת ל-`OR` stage
- **מיקום**: `webapp/app.py:6285-6505`
- **הקוד**: יש אפילו endpoint שמדגים explain: `/admin/diagnose-slow-queries`
- **פילטר (איטי)**: `{ $or: [{is_active:true}, {is_active:{$exists:false}}] }`
- **הסכנה**: `OR` stage → הרבה פעמים *שובר* שימוש יעיל באינדקס גם אם יש `{is_active, created_at}`
- **Wrapper**: לא; זה UI/Admin ישיר
- **Explain**: בקוד עצמו מצוין ש-winningPlan יכול להיות `OR`
- **המלצה**:
  - **מיגרציה חובה**: להריץ `/admin/fix-is-active?action=migrate` עד ש-`missing_is_active==0`
  - **קוד**: לשנות שאילתות ל-`{is_active: true}` במקום `$or/$exists` או `{ $ne:false }`
  - **אינדקס**: כבר קיים `active_recent_fixed` + `user_active_file_latest_idx` – רק צריך שה-query יהיה index-friendly
- **חומרה**: **P0**

### P0-2: חיפוש קבצים ב-UI עם `$regex` לא escaped ולא מעוגן
- **מיקום**: `webapp/app.py:8791-8798` וגם `webapp/app.py:9046-9051`
- **Snippet**: `{'$or': [{'file_name': {'$regex': q, '$options': 'i'}}, {'description': {'$regex': q, '$options': 'i'}}, {'tags': {'$in': [q]}}]}`
- **הסכנה**:
  - `$regex` לא מעוגן → לרוב `COLLSCAN`/`FETCH` כבד
  - אין `re.escape()` → משתמש יכול להזריק regex יקר (ReDoS)
  - `$or` מחמיר שימוש באינדקס (במיוחד יחד עם regex)
- **תדירות**: endpoint “חם” (מסך files)
- **Explain (סטטי)**: חשד ל-`COLLSCAN` או `FETCH` גדול; לעיתים `OR`
- **המלצה**:
  - **בטיחות**: להחליף ל-`re.escape(search_query)` לפני בניית regex
  - **ביצועים**:
    - לשקול מעבר ל-`$text` (יש `full_text_search_idx`) כאשר `search_query` “טקסטואלי”
    - או להגביל regex ל-prefix בלבד (`^...`) אם UX מאפשר
    - אם חייב substring: לשקול Atlas Search / פתרון ייעודי (אחרת אין קסם אינדקסי)
- **חומרה**: **P0**

### P0-3: Push sender – query עם `$expr` להשוואת שדות (שובר אינדקסים)
- **מיקום**: `webapp/push_api.py:484-512`
- **Snippet**: `$match` כולל `'$expr': {'$or': [{'$eq':['$last_push_success_at',None]}, {'$lt':['$last_push_success_at','$remind_at']}]}`
- **הסכנה**: `$expr` עם השוואת שדות → כמעט תמיד לא indexable; יחד עם `$sort` על `remind_at` זה “צועק” ל-`COLLSCAN`
- **תדירות**: לולאה כל `PUSH_SEND_INTERVAL_SECONDS` (ברירת מחדל 60s)
- **Explain (סטטי)**: חשד ל-COLLSCAN + SORT
- **המלצה (שינוי לוגיקה, הכי אמין)**:
  - בכל שינוי `remind_at` (set/snooze) לקבוע `last_push_success_at = None` או שדה חדש `push_pending=true`
  - ואז השאילתה נהיית פשוט: `{status:{$in:[...]}, ack_at:null, remind_at:{$lte:now}, last_push_success_at:null}`
  - **אינדקס מומלץ** (global scan, לא לפי user):
    - `db.note_reminders.createIndex({status:1, ack_at:1, remind_at:1, last_push_success_at:1})`
    - הערת סיכון: overhead בכתיבה (עדכוני reminders), אבל זה collection קטן יחסית בדרך כלל
- **חומרה**: **P0**

### P0-4: `Repository.list_deleted_files` מושך הכל וממיין בפייתון (אין pagination ב-DB)
- **מיקום**: `database/repository.py:1368-1419`
- **סכנה**: משתמש עם הרבה מחיקות → pull ענק משתי קולקציות + sort בזיכרון + latency גבוהה
- **Projection**: יש exclude לשדות כבדים, טוב, אבל עדיין pull
- **Explain (סטטי)**: אין explain; זו בעיה לוגית של “לא עושים את העבודה ב-DB”
- **המלצה**:
  - לשנות למודל: query+sort+skip+limit בכל קולקציה, ואז merge של שני cursors כבר מוגבלים
  - **אינדקסים**: `{user_id:1, is_active:1, deleted_at:-1, updated_at:-1}` לכל אחת מ-`code_snippets` ו-`large_files`
- **חומרה**: **P0**

### P0-5: `get_users_with_active_drive_schedule` – `$or` ענק על users (סיכון ל-scan)
- **מיקום**: `database/repository.py:1878-1914`
- **Snippet**: `$or` על שדות nested שונים של `drive_prefs.schedule*`
- **הסכנה**: אין אינדקס אפקטיבי לכל הווריאציות; הפולבק אפילו עושה `drive_prefs: {$exists:true}` ואז מסנן בפייתון
- **תדירות**: ריסטארט/rescheduler
- **המלצה**:
  - נרמול סכימה: שדה קנוני יחיד `drive_prefs.schedule_key` (string)
  - אינדקס: `db.users.createIndex({'drive_prefs.schedule_key': 1})`
  - לטובת סינון פעילים בלבד: לשקול `drive_prefs.enabled` + אינדקס קומפאונד
- **חומרה**: **P0**

### P1-1: `sticky_notes_api` – `$or` על scope_id/file_id + חסר אינדקס ל-scope_id
- **מיקום**: `webapp/sticky_notes_api.py:416-446`
- **Snippet**: `query['$or'] = [{'scope_id': scope_id}, {'file_id': {'$in': related_ids}}]` ואז `.sort('created_at',1)`
- **סכנה**: בלי אינדקס על `(user_id, scope_id, created_at)` זה נוטה ל-scan
- **המלצת אינדקס**: `db.sticky_notes.createIndex({user_id:1, scope_id:1, created_at:1})`
- **חומרה**: **P1**

### P1-2: `sticky_notes_api` – N+1 בשליפת preview של reminders
- **מיקום**: `webapp/sticky_notes_api.py:792-842`
- **סכנה**: לכל reminder מבצעים `find_one` על `sticky_notes` (עד 50)
- **המלצה**: לשלוף את כל ה-note_ids בבת אחת עם `$in` ולהכין map; או `$lookup` אם בוחרים ללכת aggregation
- **חומרה**: **P1**

### P1-3: `monitoring/alerts_storage.fetch_alerts` – `$or` + `$regex` על כמה שדות ללא escape
- **מיקום**: `monitoring/alerts_storage.py:1142-1205`
- **סכנה**: regex לא escaped (אפשר ReDoS) + סביר COLLSCAN; גם `count_documents(match)` מכפיל עלות
- **המלצה**:
  - להחליף חיפוש ל-`$text` על `search_blob/name/summary` עם text index
  - או לפחות `re.escape(search)` לפני `$regex`
  - להוסיף אינדקסים: `{ts_dt:-1}`, `{alert_type:1, ts_dt:-1}`, `{severity:1, ts_dt:-1}`, `{endpoint:1, ts_dt:-1}`
- **חומרה**: **P1**

### P1-4: `monitoring/metrics_storage` – אין יצירת אינדקסים למרות שיש שאילתות
- **מיקום**: `monitoring/metrics_storage.py`
- **סכנה**: `find().sort('ts',-1)` + aggregations על `ts` בלי אינדקס/TTL = סיכון ל-scan וגידול לא חסום
- **המלצה**:
  - ליצור אינדקסים ב-init: `{ts:-1}`, `{type:1, ts:-1}`, `{request_id:1, ts:-1}`, TTL על `ts` (לפי retention)
- **חומרה**: **P1**

### P2-1: `services/rules_storage` – sort על `updated_at` שהוא ISO string
- **מיקום**: `services/rules_storage.py:111-116`
- **סכנה**: מיון לפי string + אין אינדקס על updated_at
- **המלצה**: לשמור `updated_at` כ-`datetime` ולהוסיף אינדקס `{updated_at:-1}`
- **חומרה**: **P2**

---

## איך להוציא Explain אמיתי (winningPlan)

### דרך ה-Profiler (מומלץ)
הפרויקט כולל `services/query_profiler_service.py` עם `get_explain_plan()` (ברירת מחדל `queryPlanner` – לא מריץ את השאילתה).

דוגמה (קוד):

```python
from services.query_profiler_service import QueryProfilerService
from database.manager import DatabaseManager

mgr = DatabaseManager()
prof = QueryProfilerService(mgr)
plan = await prof.get_explain_plan(
    collection='code_snippets',
    query={'user_id': 123, 'is_active': True},
    verbosity='queryPlanner',
)
# plan.winning_plan
```

### דרך endpoints קיימים ב-WebApp
- `/admin/diagnose-slow-queries` כבר מריץ explain לדוגמה של `$or` על `is_active`

---

## Appendix A: כיסוי מלא של call-sites (סטטי)

### סטטיסטיקה
- **סה"כ קריאות DB מזוהות**: 556
- **מספר קבצים**: 52

#### לפי מתודה
- `find_one`: 125
- `find`: 100
- `update_one`: 91
- `insert_one`: 66
- `aggregate`: 50
- `count_documents`: 48
- `update_many`: 33
- `delete_one`: 18
- `delete_many`: 11
- `distinct`: 11
- `insert_many`: 2
- `find_one_and_update`: 1

#### Top files (לפי כמות קריאות)
- `/webapp/app.py`: 196
- `/database/repository.py`: 80
- `/database/bookmarks_manager.py`: 28
- `/main.py`: 26
- `/webapp/sticky_notes_api.py`: 20
- `/monitoring/alert_tags_storage.py`: 16
- `/monitoring/alerts_storage.py`: 16
- `/webapp/push_api.py`: 15
- `/reminders/database.py`: 14
- `/database/collections_manager.py`: 9
- `/monitoring/incident_story_storage.py`: 9
- `/monitoring/metrics_storage.py`: 8
- `/services/community_library_service.py`: 7
- `/services/rules_storage.py`: 7
- `/services/query_profiler_service.py`: 6
- `/bot_handlers.py`: 5
- `/monitoring/silences.py`: 5
- `/tests/test_collections_manager_share_and_activity.py`: 5
- `/user_stats.py`: 5
- `/monitoring/drills_storage.py`: 4
- `/scripts/cleanup_repo_tags.py`: 4
- `/scripts/migrate_custom_themes.py`: 4
- `/tests/test_repository_favorites_count_distinct_versions.py`: 4
- `/tests/test_repository_get_favorites_count_empty_and_mixed.py`: 4
- `/webapp/bookmarks_api.py`: 4
- `/cache_commands.py`: 3
- `/integrations.py`: 3
- `/services/job_tracker.py`: 3
- `/src/infrastructure/composition/files_facade.py`: 3
- `/tests/test_repository_favorites_filter_language_limit.py`: 3

### רשימה מלאה (קובץ/שורה/מתודה/שורה מקורית)
| קובץ | שורה | מתודה | snippet |
|---|---:|---|---|
| `/activity_reporter.py` | 95 | `update_one` | `self.db.user_interactions.update_one(` |
| `/activity_reporter.py` | 106 | `update_one` | `self.db.service_activity.update_one(` |
| `/bot_handlers.py` | 4187 | `find` | `cursor = coll.find({"user_id": {"$exists": True}, "blocked": {"$ne": True}}, {"user_id": 1})` |
| `/bot_handlers.py` | 4245 | `update_many` | `coll.update_many({"user_id": {"$in": removed_ids}}, {"$set": {"blocked": True}})` |
| `/bot_handlers.py` | 4299 | `find_one` | `doc = users_coll.find_one({"username": uname}) or users_coll.find_one({"username": uname.lower()})` |
| `/bot_handlers.py` | 4299 | `find_one` | `doc = users_coll.find_one({"username": uname}) or users_coll.find_one({"username": uname.lower()})` |
| `/bot_handlers.py` | 4339 | `update_one` | `users_coll.update_one({"user_id": target_id}, {"$set": {"blocked": True}})` |
| `/cache_commands.py` | 126 | `count_documents` | `'total_files': db.code_snippets.count_documents(active_query),` |
| `/cache_commands.py` | 127 | `distinct` | `'languages': list(db.code_snippets.distinct('programming_language', active_query)),` |
| `/cache_commands.py` | 130 | `find` | `recent = db.code_snippets.find(active_query, {'file_name': 1, 'created_at': 1}).sort('created_at', -1).limit(10)` |
| `/chatops/jobs_commands.py` | 50 | `find` | `cursor = coll.find({"status": "failed"}).sort("started_at", -1).limit(10)` |
| `/conversation_handlers.py` | 431 | `insert_one` | `collection.insert_one(token_doc)` |
| `/database/bookmarks_manager.py` | 53 | `update_many` | `self.collection.update_many(` |
| `/database/bookmarks_manager.py` | 174 | `find_one` | `existing = self.collection.find_one(find_query)` |
| `/database/bookmarks_manager.py` | 178 | `delete_one` | `self.collection.delete_one({"_id": existing["_id"]})` |
| `/database/bookmarks_manager.py` | 221 | `insert_one` | `result = self.collection.insert_one(bookmark.to_dict())` |
| `/database/bookmarks_manager.py` | 272 | `find` | `bookmarks = list(self.collection.find(query).sort("line_number", 1))` |
| `/database/bookmarks_manager.py` | 277 | `update_many` | `self.collection.update_many(` |
| `/database/bookmarks_manager.py` | 322 | `aggregate` | `result = list(self.collection.aggregate(pipeline))` |
| `/database/bookmarks_manager.py` | 336 | `count_documents` | `total_count = self.collection.count_documents({"user_id": user_id})` |
| `/database/bookmarks_manager.py` | 363 | `update_one` | `result = self.collection.update_one(` |
| `/database/bookmarks_manager.py` | 398 | `update_one` | `result = self.collection.update_one(` |
| `/database/bookmarks_manager.py` | 427 | `delete_one` | `result = self.collection.delete_one({` |
| `/database/bookmarks_manager.py` | 446 | `delete_many` | `result = self.collection.delete_many({` |
| `/database/bookmarks_manager.py` | 477 | `find_one` | `file_doc = self.files_collection.find_one({"_id": ObjectId(file_id)})` |
| `/database/bookmarks_manager.py` | 498 | `update_one` | `self.files_collection.update_one(` |
| `/database/bookmarks_manager.py` | 526 | `find` | `bookmarks = list(self.collection.find({"file_id": file_id}))` |
| `/database/bookmarks_manager.py` | 669 | `update_one` | `self.collection.update_one(` |
| `/database/bookmarks_manager.py` | 680 | `count_documents` | `file_count = self.collection.count_documents({` |
| `/database/bookmarks_manager.py` | 692 | `count_documents` | `total_count = self.collection.count_documents({"user_id": user_id})` |
| `/database/bookmarks_manager.py` | 705 | `find_one` | `file_doc = self.files_collection.find_one({"_id": ObjectId(file_id)})` |
| `/database/bookmarks_manager.py` | 732 | `insert_one` | `self.events_collection.insert_one(event)` |
| `/database/bookmarks_manager.py` | 775 | `update_one` | `result = self.collection.update_one(` |
| `/database/bookmarks_manager.py` | 795 | `update_one` | `result = self.collection.update_one(` |
| `/database/bookmarks_manager.py` | 812 | `find_one` | `doc = self.collection.find_one({"user_id": user_id, "file_id": file_id, "anchor_id": anchor_id})` |
| `/database/bookmarks_manager.py` | 815 | `delete_one` | `self.collection.delete_one({"_id": doc["_id"]})` |
| `/database/bookmarks_manager.py` | 827 | `count_documents` | `total_bookmarks = self.collection.count_documents({"user_id": user_id})` |
| `/database/bookmarks_manager.py` | 840 | `aggregate` | `top_files = list(self.collection.aggregate(pipeline))` |
| `/database/bookmarks_manager.py` | 844 | `count_documents` | `recent_count = self.collection.count_documents({` |
| `/database/bookmarks_manager.py` | 865 | `delete_many` | `result = self.collection.delete_many({` |
| `/database/collections_manager.py` | 843 | `find` | `rows = coll.find(query, projection=projection)` |
| `/database/collections_manager.py` | 1073 | `aggregate` | `rows = list(self.code_snippets.aggregate(pipeline, allowDiskUse=True))` |
| `/database/collections_manager.py` | 1216 | `find_one` | `doc_found = self.code_snippets.find_one(query, projection=projection, sort=[("version", -1), ("updated_at", -1), ("_id", -1)])` |
| `/database/collections_manager.py` | 1221 | `find_one` | `doc_found = self.code_snippets.find_one(query)` |
| `/database/collections_manager.py` | 1230 | `find` | `raw = self.code_snippets.find(query, projection=projection)` |
| `/database/collections_manager.py` | 1267 | `find_one` | `doc_found = self.large_files.find_one(query, projection=projection, sort=[("updated_at", -1), ("_id", -1)])` |
| `/database/collections_manager.py` | 1272 | `find_one` | `doc_found = self.large_files.find_one(query)` |
| `/database/collections_manager.py` | 1281 | `find` | `raw = self.large_files.find(query, projection=projection)` |
| `/database/collections_manager.py` | 1500 | `insert_one` | `collection.insert_one(record)` |
| `/database/manager.py` | 928 | `aggregate` | `res = list(self.collection.aggregate(pipeline, allowDiskUse=True)) if self.collection else []` |
| `/database/repository.py` | 241 | `insert_one` | `result = self.manager.collection.insert_one(doc)` |
| `/database/repository.py` | 295 | `find_one` | `snippet = self.manager.collection.find_one(` |
| `/database/repository.py` | 325 | `find_one` | `fav_doc = self.manager.collection.find_one(fav_q, {"_id": 1})` |
| `/database/repository.py` | 327 | `find_one` | `fav_doc = self.manager.collection.find_one(fav_q)` |
| `/database/repository.py` | 356 | `update_many` | `res = self.manager.collection.update_many(query, update)` |
| `/database/repository.py` | 482 | `aggregate` | `rows = list(self.manager.collection.aggregate(pipeline, allowDiskUse=True))` |
| `/database/repository.py` | 574 | `aggregate` | `res = list(self.manager.collection.aggregate(pipeline, allowDiskUse=True))` |
| `/database/repository.py` | 604 | `aggregate` | `rows = list(self.manager.collection.aggregate(pipeline2, allowDiskUse=True))` |
| `/database/repository.py` | 640 | `find_one` | `doc = self.manager.collection.find_one(q, {"_id": 1})` |
| `/database/repository.py` | 642 | `find_one` | `doc = self.manager.collection.find_one(q)` |
| `/database/repository.py` | 768 | `find_one` | `return self.manager.collection.find_one(` |
| `/database/repository.py` | 781 | `find_one` | `return self.manager.collection.find_one(` |
| `/database/repository.py` | 792 | `find` | `return list(self.manager.collection.find(` |
| `/database/repository.py` | 802 | `find_one` | `return self.manager.collection.find_one(` |
| `/database/repository.py` | 878 | `aggregate` | `rows = list(self.manager.collection.aggregate(pipeline, allowDiskUse=True))` |
| `/database/repository.py` | 932 | `aggregate` | `rows = list(self.manager.collection.aggregate(pipeline, allowDiskUse=True))` |
| `/database/repository.py` | 980 | `aggregate` | `items = list(self.manager.collection.aggregate(items_pipeline, allowDiskUse=True))` |
| `/database/repository.py` | 989 | `aggregate` | `cnt_res = list(self.manager.collection.aggregate(count_pipeline, allowDiskUse=True))` |
| `/database/repository.py` | 1029 | `aggregate` | `cnt = list(self.manager.collection.aggregate(count_pipeline, allowDiskUse=True))` |
| `/database/repository.py` | 1063 | `aggregate` | `items = list(self.manager.collection.aggregate(items_pipeline, allowDiskUse=True))` |
| `/database/repository.py` | 1074 | `update_many` | `result = self.manager.collection.update_many(` |
| `/database/repository.py` | 1109 | `update_many` | `result = self.manager.collection.update_many(` |
| `/database/repository.py` | 1142 | `find_one` | `pre_doc = self.manager.collection.find_one({"_id": ObjectId(file_id), "is_active": True}, {"user_id": 1})` |
| `/database/repository.py` | 1147 | `update_many` | `result = self.manager.collection.update_many(` |
| `/database/repository.py` | 1174 | `find_one` | `return self.manager.collection.find_one({"_id": ObjectId(file_id)})` |
| `/database/repository.py` | 1199 | `aggregate` | `result = list(self.manager.collection.aggregate(pipeline, allowDiskUse=True))` |
| `/database/repository.py` | 1219 | `update_many` | `result = self.manager.collection.update_many(` |
| `/database/repository.py` | 1227 | `update_many` | `coll.update_many(` |
| `/database/repository.py` | 1260 | `insert_one` | `result = self.manager.large_files_collection.insert_one(asdict(large_file))` |
| `/database/repository.py` | 1268 | `find_one` | `return self.manager.large_files_collection.find_one(` |
| `/database/repository.py` | 1277 | `find_one` | `return self.manager.large_files_collection.find_one({"_id": ObjectId(file_id)})` |
| `/database/repository.py` | 1285 | `count_documents` | `total_count = self.manager.large_files_collection.count_documents({"user_id": user_id, "is_active": True})` |
| `/database/repository.py` | 1289 | `find` | `cursor = self.manager.large_files_collection.find(` |
| `/database/repository.py` | 1296 | `find` | `cursor = self.manager.large_files_collection.find(` |
| `/database/repository.py` | 1315 | `update_many` | `result = self.manager.large_files_collection.update_many(` |
| `/database/repository.py` | 1337 | `find_one` | `pre_doc = self.manager.large_files_collection.find_one({"_id": ObjectId(file_id), "is_active": True}, {"user_id": 1})` |
| `/database/repository.py` | 1342 | `update_many` | `result = self.manager.large_files_collection.update_many(` |
| `/database/repository.py` | 1375 | `find` | `reg_docs = list(self.manager.collection.find(match, dict(_HEAVY_FIELDS_EXCLUDE_PROJECTION)))` |
| `/database/repository.py` | 1377 | `find` | `reg_docs = list(self.manager.collection.find(match))` |
| `/database/repository.py` | 1387 | `find` | `large_docs = list(self.manager.large_files_collection.find(match, dict(_HEAVY_FIELDS_EXCLUDE_PROJECTION)))` |
| `/database/repository.py` | 1389 | `find` | `large_docs = list(self.manager.large_files_collection.find(match))` |
| `/database/repository.py` | 1426 | `update_many` | `res = self.manager.collection.update_many(` |
| `/database/repository.py` | 1434 | `update_many` | `res2 = self.manager.large_files_collection.update_many(` |
| `/database/repository.py` | 1455 | `delete_many` | `res = self.manager.collection.delete_many({"_id": ObjectId(file_id), "user_id": user_id, "is_active": False})` |
| `/database/repository.py` | 1458 | `delete_many` | `res2 = self.manager.large_files_collection.delete_many({"_id": ObjectId(file_id), "user_id": user_id, "is_active": False})` |
| `/database/repository.py` | 1498 | `aggregate` | `rows = list(self.manager.collection.aggregate(pipeline, allowDiskUse=True))` |
| `/database/repository.py` | 1563 | `aggregate` | `rows = list(self.manager.collection.aggregate(pipeline, allowDiskUse=True))` |
| `/database/repository.py` | 1595 | `aggregate` | `docs = list(self.manager.collection.aggregate(pipeline, allowDiskUse=True))` |
| `/database/repository.py` | 1613 | `aggregate` | `docs = list(self.manager.collection.aggregate(pipeline, allowDiskUse=True))` |
| `/database/repository.py` | 1627 | `update_one` | `result = users_collection.update_one(` |
| `/database/repository.py` | 1642 | `find_one` | `user = users_collection.find_one({"user_id": user_id})` |
| `/database/repository.py` | 1660 | `update_one` | `result = users_collection.update_one(` |
| `/database/repository.py` | 1674 | `update_one` | `result = users_collection.update_one(` |
| `/database/repository.py` | 1689 | `find_one` | `user = users_collection.find_one({"user_id": user_id})` |
| `/database/repository.py` | 1712 | `update_one` | `result = users_collection.update_one(` |
| `/database/repository.py` | 1722 | `update_one` | `result = users_collection.update_one(` |
| `/database/repository.py` | 1740 | `find_one` | `user = users_collection.find_one({"user_id": user_id})` |
| `/database/repository.py` | 1777 | `update_one` | `result = users_collection.update_one(` |
| `/database/repository.py` | 1804 | `update_one` | `result = users_collection.update_one(` |
| `/database/repository.py` | 1817 | `find_one` | `user = users_collection.find_one({"user_id": user_id})` |
| `/database/repository.py` | 1842 | `update_one` | `res = users_collection.update_one(` |
| `/database/repository.py` | 1854 | `find_one` | `existing = users_collection.find_one({"user_id": user_id}) or {}` |
| `/database/repository.py` | 1857 | `update_one` | `res = users_collection.update_one(` |
| `/database/repository.py` | 1870 | `find_one` | `user = users_collection.find_one({"user_id": user_id})` |
| `/database/repository.py` | 1899 | `find` | `results = list(users_collection.find(query, projection))` |
| `/database/repository.py` | 1908 | `find` | `wide_results = list(users_collection.find(wide_query, projection))` |
| `/database/repository.py` | 1926 | `find_one` | `existing = users_collection.find_one({"user_id": user_id}) or {}` |
| `/database/repository.py` | 1929 | `update_one` | `res = users_collection.update_one(` |
| `/database/repository.py` | 1948 | `find_one` | `user = users_collection.find_one({"user_id": user_id})` |
| `/database/repository.py` | 1977 | `update_one` | `coll.update_one(` |
| `/database/repository.py` | 1993 | `find_one` | `doc = coll.find_one({"user_id": user_id, "backup_id": backup_id})` |
| `/database/repository.py` | 2006 | `delete_many` | `res = coll.delete_many({"user_id": user_id, "backup_id": {"$in": backup_ids}})` |
| `/database/repository.py` | 2025 | `update_one` | `coll.update_one(` |
| `/database/repository.py` | 2040 | `find_one` | `doc = coll.find_one({"user_id": user_id, "backup_id": backup_id})` |
| `/database/repository.py` | 2088 | `insert_one` | `res = coll.insert_one(doc)` |
| `/database/repository.py` | 2111 | `update_one` | `res = coll.update_one(q, upd)` |
| `/database/repository.py` | 2134 | `update_one` | `res = coll.update_one(q, upd)` |
| `/database/repository.py` | 2145 | `find` | `cursor = coll.find({"status": "pending"}, sort=[("submitted_at", 1)])` |
| `/database/repository.py` | 2168 | `count_documents` | `total = int(coll.count_documents(match))` |
| `/database/repository.py` | 2173 | `find` | `cursor = coll.find(match, sort=[("approved_at", -1)])` |
| `/integrations.py` | 510 | `insert_one` | `coll.insert_one(doc)` |
| `/integrations.py` | 555 | `find_one` | `doc = coll.find_one({"share_id": share_id})` |
| `/integrations.py` | 559 | `update_one` | `coll.update_one({"_id": doc["_id"]}, {"$inc": {"views": 1}})` |
| `/main.py` | 776 | `update_many` | `r1 = coll.update_many({"is_active": False, "deleted_at": {"$exists": False}}, {"$set": {"deleted_at": now}})` |
| `/main.py` | 783 | `update_many` | `r2 = coll.update_many({"is_active": False, "deleted_expires_at": {"$exists": False}}, {"$set": {"deleted_expires_at": expires}})` |
| `/main.py` | 852 | `find_one` | `doc = users_collection.find_one({"user_id": user_id}, {"total_actions": 1, "milestones_sent": 1}) or {}` |
| `/main.py` | 866 | `update_one` | `res = users_collection.update_one(` |
| `/main.py` | 1012 | `delete_one` | `result = lock_collection.delete_one({"_id": LOCK_ID, "pid": pid})` |
| `/main.py` | 1058 | `insert_one` | `lock_collection.insert_one({"_id": LOCK_ID, "pid": pid, "expires_at": expires_at})` |
| `/main.py` | 1071 | `find_one` | `doc = lock_collection.find_one({"_id": LOCK_ID})` |
| `/main.py` | 1074 | `find_one_and_update` | `result = lock_collection.find_one_and_update(` |
| `/main.py` | 1096 | `find_one` | `doc = lock_collection.find_one({"_id": LOCK_ID})` |
| `/main.py` | 3644 | `insert_one` | `db.webapp_tokens.insert_one({` |
| `/main.py` | 3754 | `find` | `rows_obj = coll.find({}, {"user_id": 1})` |
| `/main.py` | 3861 | `find` | `cursor = coll.find(` |
| `/main.py` | 3886 | `update_one` | `coll.update_one(` |
| `/main.py` | 3959 | `update_many` | `expired_result = coll.update_many(` |
| `/main.py` | 3968 | `find` | `cursor = coll.find({` |
| `/main.py` | 3986 | `update_one` | `result = coll.update_one(` |
| `/main.py` | 4035 | `update_one` | `coll.update_one(` |
| `/main.py` | 4043 | `update_one` | `coll.update_one(` |
| `/main.py` | 4312 | `find` | `users_docs = list(users_coll.find(wide_query, {"user_id": 1, "drive_prefs": 1}))` |
| `/main.py` | 5077 | `aggregate` | `agg = list(db.code_snippets.aggregate(pipeline))` |
| `/main.py` | 5092 | `aggregate` | `tag_rows = list(db.code_snippets.aggregate(tag_pipe))` |
| `/main.py` | 5113 | `count_documents` | `"total_files": db.code_snippets.count_documents(active_q),` |
| `/main.py` | 5114 | `distinct` | `"languages": list(db.code_snippets.distinct("programming_language", active_q)),` |
| `/main.py` | 5118 | `find` | `db.code_snippets.find(active_q, {"file_name": 1, "created_at": 1})` |
| `/main.py` | 5194 | `find_one` | `user_doc = db.users.find_one({"user_id": int(uid)}) or {}` |
| `/main.py` | 5252 | `find_one` | `user_doc = db.users.find_one({"user_id": int(uid)}) or {}` |
| `/monitoring/alert_tags_storage.py` | 205 | `find_one` | `doc = coll.find_one({"alert_uid": uid})` |
| `/monitoring/alert_tags_storage.py` | 220 | `find` | `cursor = coll.find({"alert_uid": {"$in": uids}})` |
| `/monitoring/alert_tags_storage.py` | 251 | `update_one` | `result = coll.update_one(` |
| `/monitoring/alert_tags_storage.py` | 299 | `update_one` | `coll.update_one(` |
| `/monitoring/alert_tags_storage.py` | 334 | `update_one` | `result = coll.update_one(` |
| `/monitoring/alert_tags_storage.py` | 364 | `aggregate` | `return list(coll.aggregate(pipeline))` |
| `/monitoring/alert_tags_storage.py` | 393 | `aggregate` | `results = list(coll.aggregate(pipeline))` |
| `/monitoring/alert_tags_storage.py` | 477 | `find` | `cursor = coll.find(` |
| `/monitoring/alert_tags_storage.py` | 498 | `find` | `cursor = coll.find(` |
| `/monitoring/alert_tags_storage.py` | 522 | `find` | `cursor = coll.find(` |
| `/monitoring/alert_tags_storage.py` | 616 | `update_one` | `result = coll.update_one(` |
| `/monitoring/alert_tags_storage.py` | 660 | `find_one` | `doc = coll.find_one({"alert_type_name": name})` |
| `/monitoring/alert_tags_storage.py` | 679 | `delete_one` | `result = coll.delete_one({"alert_type_name": name})` |
| `/monitoring/alert_tags_storage.py` | 728 | `update_one` | `result = coll.update_one(` |
| `/monitoring/alert_tags_storage.py` | 769 | `find_one` | `doc = coll.find_one({"error_signature": sig})` |
| `/monitoring/alert_tags_storage.py` | 784 | `delete_one` | `result = coll.delete_one({"error_signature": sig})` |
| `/monitoring/alerts_storage.py` | 692 | `find_one` | `existing = collection.find_one({"signature": signature, "last_seen": {"$gte": cutoff}})` |
| `/monitoring/alerts_storage.py` | 695 | `update_one` | `collection.update_one(` |
| `/monitoring/alerts_storage.py` | 836 | `update_one` | `coll.update_one({"_key": key}, {"$setOnInsert": doc}, upsert=True)  # type: ignore[attr-defined]` |
| `/monitoring/alerts_storage.py` | 840 | `insert_one` | `coll.insert_one(doc)  # type: ignore[attr-defined]` |
| `/monitoring/alerts_storage.py` | 887 | `update_one` | `coll.update_one(` |
| `/monitoring/alerts_storage.py` | 926 | `find` | `coll.find(` |
| `/monitoring/alerts_storage.py` | 1021 | `find` | `cursor = coll.find(match, projection).sort([("ts_dt", -1)]).limit(limit_int)  # type: ignore[attr-defined]` |
| `/monitoring/alerts_storage.py` | 1057 | `count_documents` | `total = int(coll.count_documents(match))  # type: ignore[attr-defined]` |
| `/monitoring/alerts_storage.py` | 1059 | `count_documents` | `coll.count_documents(` |
| `/monitoring/alerts_storage.py` | 1094 | `find` | `coll.find({}, {"alert_id": 1, "_key": 1, "ts_dt": 1})  # type: ignore[attr-defined]` |
| `/monitoring/alerts_storage.py` | 1174 | `find` | `coll.find(match, projection)  # type: ignore[attr-defined]` |
| `/monitoring/alerts_storage.py` | 1202 | `count_documents` | `total = int(coll.count_documents(match))  # type: ignore[attr-defined]` |
| `/monitoring/alerts_storage.py` | 1262 | `aggregate` | `rows = list(coll.aggregate(pipeline))  # type: ignore[attr-defined]` |
| `/monitoring/alerts_storage.py` | 1335 | `aggregate` | `result = list(coll.aggregate(pipeline))  # type: ignore[attr-defined]` |
| `/monitoring/alerts_storage.py` | 1370 | `find` | `coll.find(match, {"ts_dt": 1})  # type: ignore[attr-defined]` |
| `/monitoring/alerts_storage.py` | 1440 | `aggregate` | `rows = list(coll.aggregate(pipeline))  # type: ignore[attr-defined]` |
| `/monitoring/drills_storage.py` | 165 | `update_one` | `coll.update_one({"drill_id": doc["drill_id"]}, {"$setOnInsert": doc}, upsert=True)  # type: ignore[attr-defined]` |
| `/monitoring/drills_storage.py` | 168 | `insert_one` | `coll.insert_one(doc)  # type: ignore[attr-defined]` |
| `/monitoring/drills_storage.py` | 185 | `find` | `coll.find({}, {"_id": 0})  # type: ignore[attr-defined]` |
| `/monitoring/drills_storage.py` | 203 | `find_one` | `doc = coll.find_one({"drill_id": key}, {"_id": 0})  # type: ignore[attr-defined]` |
| `/monitoring/incident_story_storage.py` | 251 | `find_one` | `existing = collection.find_one(lookup_filter)  # type: ignore[attr-defined]` |
| `/monitoring/incident_story_storage.py` | 261 | `update_one` | `collection.update_one({"_id": existing["_id"]}, {"$set": payload}, upsert=False)  # type: ignore[attr-defined]` |
| `/monitoring/incident_story_storage.py` | 262 | `find_one` | `stored = collection.find_one({"_id": existing["_id"]})  # type: ignore[attr-defined]` |
| `/monitoring/incident_story_storage.py` | 264 | `insert_one` | `res = collection.insert_one(payload)  # type: ignore[attr-defined]` |
| `/monitoring/incident_story_storage.py` | 265 | `find_one` | `stored = collection.find_one({"_id": res.inserted_id})  # type: ignore[attr-defined]` |
| `/monitoring/incident_story_storage.py` | 284 | `find_one` | `doc = collection.find_one({"story_id": story_id})  # type: ignore[attr-defined]` |
| `/monitoring/incident_story_storage.py` | 300 | `find_one` | `doc = collection.find_one({"alert_uid": alert_uid})  # type: ignore[attr-defined]` |
| `/monitoring/incident_story_storage.py` | 321 | `find` | `cursor = collection.find({"alert_uid": {"$in": list(normalized)}})  # type: ignore[attr-defined]` |
| `/monitoring/incident_story_storage.py` | 361 | `find` | `collection.find(query)  # type: ignore[attr-defined]` |
| `/monitoring/metrics_storage.py` | 148 | `insert_many` | `coll.insert_many(items, ordered=False)  # type: ignore[attr-defined]` |
| `/monitoring/metrics_storage.py` | 280 | `aggregate` | `rows = list(coll.aggregate(pipeline))  # type: ignore[attr-defined]` |
| `/monitoring/metrics_storage.py` | 344 | `aggregate` | `rows = list(coll.aggregate(pipeline))  # type: ignore[attr-defined]` |
| `/monitoring/metrics_storage.py` | 385 | `aggregate` | `rows = list(coll.aggregate(pipeline))  # type: ignore[attr-defined]` |
| `/monitoring/metrics_storage.py` | 426 | `aggregate` | `rows = list(coll.aggregate(pipeline))  # type: ignore[attr-defined]` |
| `/monitoring/metrics_storage.py` | 466 | `find` | `coll.find(query)  # type: ignore[attr-defined]` |
| `/monitoring/metrics_storage.py` | 537 | `aggregate` | `rows = list(coll.aggregate(pipeline))  # type: ignore[attr-defined]` |
| `/monitoring/metrics_storage.py` | 560 | `find` | `coll.find(match, {"duration_seconds": 1, "_id": 0})  # type: ignore[attr-defined]` |
| `/monitoring/silences.py` | 179 | `count_documents` | `active_count = int(coll.count_documents({"active": True, "until_ts": {"$gte": now}}))  # type: ignore[attr-defined]` |
| `/monitoring/silences.py` | 205 | `insert_one` | `coll.insert_one(doc)  # type: ignore[attr-defined]` |
| `/monitoring/silences.py` | 216 | `find` | `cursor = coll.find({"active": True, "until_ts": {"$gte": now}}).sort("until_ts", 1)  # type: ignore[attr-defined]` |
| `/monitoring/silences.py` | 262 | `update_one` | `res = coll.update_one({"_id": str(silence_id)}, {"$set": {"active": False}})  # type: ignore[attr-defined]` |
| `/monitoring/silences.py` | 278 | `update_many` | `res = coll.update_many({"pattern": str(pattern or ""), "active": True}, {"$set": {"active": False}})  # type: ignore[attr-defined]` |
| `/refactor_handlers.py` | 469 | `insert_one` | `db.collection('refactorings').insert_one({` |
| `/reminders/database.py` | 59 | `insert_one` | `res = self.reminders_collection.insert_one(reminder.to_dict())` |
| `/reminders/database.py` | 76 | `count_documents` | `return int(self.reminders_collection.count_documents(q))` |
| `/reminders/database.py` | 84 | `find` | `cursor = self.reminders_collection.find({` |
| `/reminders/database.py` | 92 | `update_one` | `r = self.reminders_collection.update_one(` |
| `/reminders/database.py` | 112 | `find` | `self.reminders_collection.find({` |
| `/reminders/database.py` | 134 | `update_one` | `self.reminders_collection.update_one(` |
| `/reminders/database.py` | 142 | `update_one` | `self.reminders_collection.update_one(` |
| `/reminders/database.py` | 150 | `update_one` | `r = self.reminders_collection.update_one(` |
| `/reminders/database.py` | 166 | `update_one` | `r = self.reminders_collection.update_one(` |
| `/reminders/database.py` | 177 | `find` | `return list(self.reminders_collection.find(q).sort("remind_at", ASCENDING).skip(int(skip)).limit(int(limit)))` |
| `/reminders/database.py` | 182 | `delete_one` | `r = self.reminders_collection.delete_one({"user_id": int(user_id), "reminder_id": reminder_id})` |
| `/reminders/database.py` | 210 | `update_one` | `r = self.reminders_collection.update_one(` |
| `/reminders/database.py` | 229 | `find` | `cursor = self.reminders_collection.find({` |
| `/reminders/database.py` | 250 | `insert_one` | `self.reminders_collection.insert_one(new_doc)` |
| `/reminders/handlers.py` | 372 | `find_one` | `doc = self.db.reminders_collection.find_one({"reminder_id": rid})` |
| `/reminders/handlers.py` | 459 | `find_one` | `doc = self.db.reminders_collection.find_one({"reminder_id": rid})` |
| `/scripts/cleanup_repo_tags.py` | 95 | `find` | `cursor = coll.find(q, projection={'file_name': 1, 'tags': 1, 'updated_at': 1})` |
| `/scripts/cleanup_repo_tags.py` | 114 | `update_one` | `coll.update_one({'_id': doc['_id']}, {'$set': {'tags': new_tags, 'updated_at': datetime.now(timezone.utc)}})` |
| `/scripts/cleanup_repo_tags.py` | 119 | `update_many` | `res = coll.update_many(` |
| `/scripts/cleanup_repo_tags.py` | 125 | `count_documents` | `backfilled = coll.count_documents({"is_favorite": {"$exists": False}})` |
| `/scripts/dev_seed.py` | 76 | `update_one` | `coll.update_one(` |
| `/scripts/import_snippets_from_markdown.py` | 207 | `find_one` | `doc = coll.find_one(q)` |
| `/scripts/migrate_custom_themes.py` | 20 | `find` | `users_to_migrate = db.users.find(` |
| `/scripts/migrate_custom_themes.py` | 50 | `update_one` | `db.users.update_one(` |
| `/scripts/migrate_custom_themes.py` | 74 | `count_documents` | `old_count = db.users.count_documents({"custom_theme": {"$exists": True}})` |
| `/scripts/migrate_custom_themes.py` | 77 | `count_documents` | `new_count = db.users.count_documents({"custom_themes": {"$exists": True}})` |
| `/scripts/migrate_workspace_collections.py` | 31 | `find` | `users_cursor = db.users.find({}, {"user_id": 1})  # type: ignore[attr-defined]` |
| `/scripts/migrate_workspace_collections.py` | 41 | `find_one` | `existing = db.user_collections.find_one({  # type: ignore[attr-defined]` |
| `/services/backoff_state.py` | 53 | `find_one` | `doc = users.find_one({"_id": "__global_state__"})` |
| `/services/backoff_state.py` | 82 | `update_one` | `users.update_one({"_id": "__global_state__"}, {"$set": payload}, upsert=True)` |
| `/services/community_library_service.py` | 119 | `insert_one` | `res = coll.insert_one(doc)` |
| `/services/community_library_service.py` | 137 | `update_one` | `res = coll.update_one(q, {"$set": {"status": "approved", "approved_at": datetime.now(timezone.utc), "approved_by": int(admin_id), "rejection_reason": None}})` |
| `/services/community_library_service.py` | 154 | `update_one` | `res = coll.update_one(q, {"$set": {"status": "rejected", "approved_at": None, "approved_by": int(admin_id), "rejection_reason": reason_s}})` |
| `/services/community_library_service.py` | 167 | `find` | `cursor = coll.find({"status": "pending"}, sort=[("submitted_at", 1)]) if coll is not None else []` |
| `/services/community_library_service.py` | 195 | `count_documents` | `total = int(coll.count_documents(match))` |
| `/services/community_library_service.py` | 202 | `find` | `cursor = coll.find(match, sort=sort).skip(skip).limit(per_page)` |
| `/services/community_library_service.py` | 233 | `find_one` | `return coll.find_one(query)` |
| `/services/job_tracker.py` | 343 | `update_one` | `self.db.client[self.db.db_name]["job_runs"].update_one(` |
| `/services/job_tracker.py` | 357 | `find_one` | `doc = self.db.client[self.db.db_name]["job_runs"].find_one({"run_id": run_id})` |
| `/services/job_tracker.py` | 368 | `find` | `self.db.client[self.db.db_name]["job_runs"]` |
| `/services/query_profiler_service.py` | 508 | `find` | `cursor = coll.find(query)` |
| `/services/query_profiler_service.py` | 1110 | `insert_one` | `db[self.COLLECTION_NAME].insert_one(doc)` |
| `/services/query_profiler_service.py` | 1136 | `find` | `cursor = db[self.COLLECTION_NAME].find(query, sort=[("execution_time_ms", -1)], limit=limit_n)` |
| `/services/query_profiler_service.py` | 1181 | `aggregate` | `return list(db[self.COLLECTION_NAME].aggregate(pipeline))` |
| `/services/query_profiler_service.py` | 1194 | `count_documents` | `total = int(db[self.COLLECTION_NAME].count_documents(query))` |
| `/services/query_profiler_service.py` | 1205 | `aggregate` | `db[self.COLLECTION_NAME].aggregate(` |
| `/services/rules_storage.py` | 68 | `update_one` | `self._collection.update_one(` |
| `/services/rules_storage.py` | 79 | `find_one` | `doc = self._collection.find_one({"rule_id": rule_id})` |
| `/services/rules_storage.py` | 86 | `find` | `cursor = self._collection.find({"enabled": True})` |
| `/services/rules_storage.py` | 112 | `find` | `self._collection.find(query)` |
| `/services/rules_storage.py` | 126 | `delete_one` | `result = self._collection.delete_one({"rule_id": rule_id})` |
| `/services/rules_storage.py` | 134 | `update_one` | `result = self._collection.update_one(` |
| `/services/rules_storage.py` | 143 | `count_documents` | `return self._collection.count_documents(query)` |
| `/services/snippet_library_service.py` | 74 | `find_one` | `return coll.find_one({"_id": key})` |
| `/services/snippet_library_service.py` | 134 | `find` | `cursor = coll.find(query, {"title": 1})` |
| `/src/infrastructure/composition/files_facade.py` | 455 | `insert_one` | `res = coll.insert_one(doc)` |
| `/src/infrastructure/composition/files_facade.py` | 505 | `find_one` | `raw = coll.find_one({"_id": _to_object_id(file_id), "user_id": int(user_id)})` |
| `/src/infrastructure/composition/files_facade.py` | 522 | `find_one` | `raw_large = large_coll.find_one({"_id": _to_object_id(file_id), "user_id": int(user_id)})` |
| `/tests/test_collections_manager_share_and_activity.py` | 202 | `insert_one` | `mgr.code_snippets.insert_one({"user_id": 20, "file_name": "a.py", "is_active": True})  # type: ignore[attr-defined]` |
| `/tests/test_collections_manager_share_and_activity.py` | 203 | `insert_one` | `mgr.large_files.insert_one({"user_id": 20, "file_name": "b.big", "is_active": True})  # type: ignore[attr-defined]` |
| `/tests/test_collections_manager_share_and_activity.py` | 223 | `insert_one` | `mgr.code_snippets.insert_one({"user_id": 20, "file_name": "b.big", "is_active": True})  # type: ignore[attr-defined]` |
| `/tests/test_collections_manager_share_and_activity.py` | 246 | `insert_one` | `mgr.code_snippets.insert_one({` |
| `/tests/test_collections_manager_share_and_activity.py` | 281 | `insert_one` | `mgr.large_files.insert_one({` |
| `/tests/test_database_noop.py` | 22 | `find_one` | `assert users.find_one({}) is None` |
| `/tests/test_database_noop.py` | 23 | `delete_one` | `assert getattr(users.delete_one({}), "deleted_count", 0) == 0` |
| `/tests/test_repository_favorites.py` | 154 | `insert_one` | `repo.manager.collection.insert_one(_base_doc(is_favorite=True, favorited_at=datetime.now(timezone.utc)))` |
| `/tests/test_repository_favorites.py` | 173 | `insert_one` | `repo.manager.collection.insert_one(_base_doc(is_favorite=False))` |
| `/tests/test_repository_favorites_count_distinct_versions.py` | 35 | `insert_one` | `repo.manager.collection.insert_one({'_id': 'a-1', 'user_id': 1, 'file_name': 'a.py', 'version': 1, 'programming_language': 'python', 'is_favorite': True, 'favorited_at': now})` |
| `/tests/test_repository_favorites_count_distinct_versions.py` | 36 | `insert_one` | `repo.manager.collection.insert_one({'_id': 'a-2', 'user_id': 1, 'file_name': 'a.py', 'version': 2, 'programming_language': 'python', 'is_favorite': True, 'favorited_at': now})` |
| `/tests/test_repository_favorites_count_distinct_versions.py` | 38 | `insert_one` | `repo.manager.collection.insert_one({'_id': 'b-1', 'user_id': 1, 'file_name': 'b.js', 'version': 1, 'programming_language': 'javascript', 'is_favorite': True, 'favorited_at': now})` |
| `/tests/test_repository_favorites_count_distinct_versions.py` | 40 | `insert_one` | `repo.manager.collection.insert_one({'_id': 'c-1', 'user_id': 1, 'file_name': 'c.py', 'version': 1, 'programming_language': 'python', 'is_favorite': True, 'favorited_at': now, 'is_active': False})` |
| `/tests/test_repository_favorites_filter_language_limit.py` | 34 | `insert_one` | `repo.manager.collection.insert_one({'_id': 'a-1', 'user_id': 1, 'file_name': 'a.py', 'version': 1, 'programming_language': 'python', 'is_favorite': True, 'favorited_at': now})` |
| `/tests/test_repository_favorites_filter_language_limit.py` | 35 | `insert_one` | `repo.manager.collection.insert_one({'_id': 'b-1', 'user_id': 1, 'file_name': 'b.py', 'version': 1, 'programming_language': 'python', 'is_favorite': True, 'favorited_at': now})` |
| `/tests/test_repository_favorites_filter_language_limit.py` | 36 | `insert_one` | `repo.manager.collection.insert_one({'_id': 'c-1', 'user_id': 1, 'file_name': 'c.js', 'version': 1, 'programming_language': 'javascript', 'is_favorite': True, 'favorited_at': now})` |
| `/tests/test_repository_favorites_ignore_inactive.py` | 97 | `insert_one` | `repo.manager.collection.insert_one({` |
| `/tests/test_repository_favorites_ignore_inactive.py` | 103 | `insert_one` | `repo.manager.collection.insert_one({` |
| `/tests/test_repository_favorites_ignore_inactive.py` | 109 | `insert_one` | `repo.manager.collection.insert_one({` |
| `/tests/test_repository_favorites_language_sort_ties.py` | 35 | `insert_one` | `repo.manager.collection.insert_one({'_id': 'a-1', 'user_id': 1, 'file_name': 'a.py', 'version': 1, 'code': '1', 'programming_language': 'python', 'is_favorite': True, 'favorited_at': now})` |
| `/tests/test_repository_favorites_language_sort_ties.py` | 36 | `insert_one` | `repo.manager.collection.insert_one({'_id': 'c-1', 'user_id': 1, 'file_name': 'c.py', 'version': 1, 'code': '2', 'programming_language': 'python', 'is_favorite': True, 'favorited_at': now})` |
| `/tests/test_repository_favorites_language_sort_ties.py` | 37 | `insert_one` | `repo.manager.collection.insert_one({'_id': 'b-1', 'user_id': 1, 'file_name': 'b.js', 'version': 1, 'code': '3', 'programming_language': 'javascript', 'is_favorite': True, 'favorited_at': now})` |
| `/tests/test_repository_favorites_limit.py` | 35 | `insert_one` | `repo.manager.collection.insert_one({'_id': 'a-1', 'user_id': 1, 'file_name': 'a.py', 'version': 1, 'code': '1', 'programming_language': 'python', 'is_favorite': True, 'favorited_at': now})` |
| `/tests/test_repository_favorites_limit.py` | 36 | `insert_one` | `repo.manager.collection.insert_one({'_id': 'b-1', 'user_id': 1, 'file_name': 'b.py', 'version': 1, 'code': '2', 'programming_language': 'python', 'is_favorite': True, 'favorited_at': now})` |
| `/tests/test_repository_favorites_limit.py` | 37 | `insert_one` | `repo.manager.collection.insert_one({'_id': 'c-1', 'user_id': 1, 'file_name': 'c.py', 'version': 1, 'code': '3', 'programming_language': 'python', 'is_favorite': True, 'favorited_at': now})` |
| `/tests/test_repository_favorites_sort_filter.py` | 123 | `insert_one` | `repo.manager.collection.insert_one(d)` |
| `/tests/test_repository_favorites_toggle_sequence.py` | 34 | `insert_one` | `repo.manager.collection.insert_one({'_id': 'x-1', 'user_id': 1, 'file_name': 'x.py', 'version': 1, 'code': '1', 'programming_language': 'python', 'is_favorite': False, 'favorited_at': None, 'is_active': True})` |
| `/tests/test_repository_get_favorites_count_empty_and_mixed.py` | 39 | `insert_one` | `repo.manager.collection.insert_one({'_id': 'a-1', 'user_id': 1, 'file_name': 'a.py', 'version': 1, 'is_favorite': True, 'favorited_at': now, 'is_active': True})` |
| `/tests/test_repository_get_favorites_count_empty_and_mixed.py` | 40 | `insert_one` | `repo.manager.collection.insert_one({'_id': 'a-2', 'user_id': 1, 'file_name': 'a.py', 'version': 2, 'is_favorite': True, 'favorited_at': now, 'is_active': True})` |
| `/tests/test_repository_get_favorites_count_empty_and_mixed.py` | 42 | `insert_one` | `repo.manager.collection.insert_one({'_id': 'b-1', 'user_id': 1, 'file_name': 'b.js', 'version': 1, 'is_favorite': True, 'favorited_at': now, 'is_active': False})` |
| `/tests/test_repository_get_favorites_count_empty_and_mixed.py` | 44 | `insert_one` | `repo.manager.collection.insert_one({'_id': 'c-1', 'user_id': 1, 'file_name': 'c.py', 'version': 1, 'is_favorite': False, 'is_active': True})` |
| `/tests/test_repository_get_favorites_fallback_docs.py` | 38 | `insert_one` | `repo.manager.collection.insert_one({'_id': 'fa-1', 'user_id': 42, 'file_name': 'fav1.py', 'version': 1, 'programming_language': 'python', 'is_favorite': True, 'favorited_at': now})` |
| `/tests/test_repository_get_favorites_fallback_docs.py` | 39 | `insert_one` | `repo.manager.collection.insert_one({'_id': 'fa-2', 'user_id': 42, 'file_name': 'fav2.js', 'version': 1, 'programming_language': 'javascript', 'is_favorite': True, 'favorited_at': now})` |
| `/tests/test_repository_get_favorites_fallback_docs.py` | 40 | `insert_one` | `repo.manager.collection.insert_one({'_id': 'fa-3', 'user_id': 42, 'file_name': 'old.py', 'version': 1, 'programming_language': 'python', 'is_favorite': False})` |
| `/tests/test_repository_get_favorites_limit_zero_none.py` | 35 | `insert_one` | `repo.manager.collection.insert_one({'_id': 'a-1', 'user_id': 7, 'file_name': 'a.py', 'version': 1, 'programming_language': 'python', 'is_favorite': True, 'favorited_at': now})` |
| `/tests/test_repository_get_favorites_limit_zero_none.py` | 36 | `insert_one` | `repo.manager.collection.insert_one({'_id': 'b-1', 'user_id': 7, 'file_name': 'b.py', 'version': 1, 'programming_language': 'python', 'is_favorite': True, 'favorited_at': now})` |
| `/tests/test_repository_get_favorites_unknown_sort.py` | 34 | `insert_one` | `repo.manager.collection.insert_one({'_id': 'a-1', 'user_id': 10, 'file_name': 'a.py', 'version': 1, 'programming_language': 'python', 'is_favorite': True, 'favorited_at': now})` |
| `/tests/test_repository_get_favorites_unknown_sort.py` | 35 | `insert_one` | `repo.manager.collection.insert_one({'_id': 'b-1', 'user_id': 10, 'file_name': 'b.js', 'version': 1, 'programming_language': 'javascript', 'is_favorite': True, 'favorited_at': now})` |
| `/tools/analyze_queries.py` | 41 | `find` | `cur = db.system.profile.find({"millis": {"$gt": int(min_ms)}}).sort("millis", -1).limit(50)` |
| `/tools/analyze_queries.py` | 64 | `find` | `return await db[collection].find(query).explain()` |
| `/user_stats.py` | 26 | `update_one` | `users_collection.update_one(` |
| `/user_stats.py` | 62 | `find` | `users = users_collection.find({` |
| `/user_stats.py` | 93 | `count_documents` | `total_users = users_collection.count_documents({})` |
| `/user_stats.py` | 97 | `count_documents` | `active_today = users_collection.count_documents({"last_seen": today})` |
| `/user_stats.py` | 101 | `count_documents` | `active_week = users_collection.count_documents({` |
| `/webapp/app.py` | 1363 | `find_one` | `user_doc = db_ref.users.find_one({'user_id': user_id}) or {}` |
| `/webapp/app.py` | 1593 | `update_one` | `result = db_ref.users.update_one(` |
| `/webapp/app.py` | 1626 | `update_one` | `db_ref.users.update_one(` |
| `/webapp/app.py` | 1632 | `update_one` | `result2 = db_ref.users.update_one(` |
| `/webapp/app.py` | 1641 | `update_one` | `db_ref.users.update_one({"user_id": user_id}, {"$set": {"ui_prefs.theme": "classic", "updated_at": now_utc}})` |
| `/webapp/app.py` | 1656 | `find_one` | `user_doc = db_ref.users.find_one(` |
| `/webapp/app.py` | 1697 | `find_one` | `udoc = dbref.users.find_one({'user_id': uid}) or {}` |
| `/webapp/app.py` | 1999 | `find_one` | `doc = db_ref.code_snippets.find_one({'_id': obj_id, 'user_id': user_id})` |
| `/webapp/app.py` | 2008 | `find_one` | `doc = large_coll.find_one({` |
| `/webapp/app.py` | 2439 | `find_one` | `doc = coll.find_one({"share_id": share_id}, projection=projection)` |
| `/webapp/app.py` | 2442 | `find_one` | `doc = coll.find_one({"share_id": share_id})` |
| `/webapp/app.py` | 2461 | `update_one` | `coll.update_one({"_id": doc["_id"]}, {"$inc": {"views": 1}})` |
| `/webapp/app.py` | 2680 | `find_one` | `doc = db.remember_tokens.find_one({` |
| `/webapp/app.py` | 2699 | `find_one` | `user = db.users.find_one({'user_id': user_id}) or {}` |
| `/webapp/app.py` | 4529 | `aggregate` | `for row in db.job_runs.aggregate(pipeline):` |
| `/webapp/app.py` | 4551 | `find` | `running_cursor = db.job_runs.find({"status": "running"}).sort("started_at", DESCENDING).limit(20)` |
| `/webapp/app.py` | 4555 | `find` | `recent_cursor = db.job_runs.find({` |
| `/webapp/app.py` | 4617 | `find` | `db.job_runs.find({"job_id": job_id, "status": "running"}).sort("started_at", DESCENDING).limit(20)` |
| `/webapp/app.py` | 4620 | `find` | `db.job_runs.find({"job_id": job_id}).sort("started_at", DESCENDING).limit(20)` |
| `/webapp/app.py` | 4641 | `find_one` | `doc = db.job_runs.find_one({"run_id": run_id})` |
| `/webapp/app.py` | 4736 | `insert_one` | `db.job_trigger_requests.insert_one(doc)` |
| `/webapp/app.py` | 4750 | `find` | `cursor = db.job_trigger_requests.find(` |
| `/webapp/app.py` | 4814 | `count_documents` | `stats["approved"] = int(coll.count_documents({"status": "approved"}))` |
| `/webapp/app.py` | 4818 | `count_documents` | `stats["pending"] = int(coll.count_documents({"status": "pending"}))` |
| `/webapp/app.py` | 4822 | `count_documents` | `stats["total"] = int(coll.count_documents({}))` |
| `/webapp/app.py` | 4838 | `find` | `cursor = coll.find(` |
| `/webapp/app.py` | 4975 | `update_one` | `result = coll.update_one({'_id': normalized_id}, {'$set': updates})` |
| `/webapp/app.py` | 5021 | `find_one` | `doc = coll.find_one({'_id': normalized_id}) if (normalized_id is not None and coll is not None) else None` |
| `/webapp/app.py` | 5038 | `find_one` | `post_doc = coll.find_one({'_id': normalized_id}) if (normalized_id is not None and coll is not None) else None` |
| `/webapp/app.py` | 5100 | `find_one` | `pre_doc = coll.find_one({'_id': normalized_id}) if (normalized_id is not None and coll is not None) else None` |
| `/webapp/app.py` | 5116 | `find_one` | `post_doc = coll.find_one({'_id': normalized_id}) if (normalized_id is not None and coll is not None) else None` |
| `/webapp/app.py` | 5177 | `find_one` | `raw = coll.find_one({'_id': normalized_id})` |
| `/webapp/app.py` | 5205 | `delete_one` | `coll.delete_one({'_id': normalized_id})` |
| `/webapp/app.py` | 5250 | `find_one` | `doc = coll.find_one(q) if coll is not None else None` |
| `/webapp/app.py` | 5270 | `find_one` | `post_doc = coll.find_one(q) if coll is not None else None` |
| `/webapp/app.py` | 5331 | `find_one` | `doc = coll.find_one(q) if coll is not None else None` |
| `/webapp/app.py` | 5351 | `find_one` | `post_doc = coll.find_one(q) if coll is not None else None` |
| `/webapp/app.py` | 5406 | `update_one` | `coll.update_one({'_id': normalized_id}, {'$set': upd})` |
| `/webapp/app.py` | 5414 | `find_one` | `raw = coll.find_one({'_id': normalized_id})` |
| `/webapp/app.py` | 5635 | `find_one` | `doc = coll.find_one(q)` |
| `/webapp/app.py` | 5786 | `delete_one` | `coll.delete_one(q)` |
| `/webapp/app.py` | 5813 | `update_one` | `coll.update_one(q, {'$set': upd})` |
| `/webapp/app.py` | 5822 | `find_one` | `raw = coll.find_one(q)` |
| `/webapp/app.py` | 5954 | `find_one` | `doc = _db.announcements.find_one({'is_active': True}, sort=[('updated_at', DESCENDING)])` |
| `/webapp/app.py` | 6003 | `find` | `cur = _db.announcements.find({}, sort=[('created_at', DESCENDING)])` |
| `/webapp/app.py` | 6046 | `update_many` | `_db.announcements.update_many({'is_active': True}, {'$set': {'is_active': False, 'updated_at': now}})` |
| `/webapp/app.py` | 6058 | `insert_one` | `_db.announcements.insert_one(doc)` |
| `/webapp/app.py` | 6087 | `update_many` | `_db.announcements.update_many({'is_active': True, '_id': {'$ne': ObjectId(item_id)}}, {'$set': {'is_active': False, 'updated_at': now}})` |
| `/webapp/app.py` | 6090 | `update_one` | `_db.announcements.update_one(` |
| `/webapp/app.py` | 6106 | `find_one` | `doc = _db.announcements.find_one({'_id': ObjectId(item_id)})` |
| `/webapp/app.py` | 6132 | `delete_one` | `_db.announcements.delete_one({'_id': ObjectId(item_id)})` |
| `/webapp/app.py` | 6151 | `update_many` | `_db.announcements.update_many({'is_active': True}, {'$set': {'is_active': False, 'updated_at': now}})` |
| `/webapp/app.py` | 6152 | `update_one` | `_db.announcements.update_one({'_id': ObjectId(item_id)}, {'$set': {'is_active': True, 'updated_at': now}})` |
| `/webapp/app.py` | 6327 | `count_documents` | `missing_count_before = collection.count_documents({"is_active": {"$exists": False}})` |
| `/webapp/app.py` | 6328 | `count_documents` | `total_count = collection.count_documents({})` |
| `/webapp/app.py` | 6341 | `find` | `docs_to_update = list(collection.find(` |
| `/webapp/app.py` | 6350 | `update_many` | `result = collection.update_many(` |
| `/webapp/app.py` | 6365 | `count_documents` | `missing_count_after = collection.count_documents({"is_active": {"$exists": False}})` |
| `/webapp/app.py` | 6366 | `count_documents` | `has_is_active_count = collection.count_documents({"is_active": {"$exists": True}})` |
| `/webapp/app.py` | 6431 | `count_documents` | `missing_is_active = collection.count_documents({"is_active": {"$exists": False}})` |
| `/webapp/app.py` | 6432 | `count_documents` | `total = collection.count_documents({})` |
| `/webapp/app.py` | 6535 | `count_documents` | `missing_before = collection.count_documents({"is_active": {"$exists": False}})` |
| `/webapp/app.py` | 6538 | `update_many` | `result = collection.update_many(` |
| `/webapp/app.py` | 6623 | `count_documents` | `missing_code_snippets = db.code_snippets.count_documents({"is_active": {"$exists": False}})` |
| `/webapp/app.py` | 6624 | `count_documents` | `missing_large_files = db.large_files.count_documents({"is_active": {"$exists": False}})` |
| `/webapp/app.py` | 7134 | `aggregate` | `docs = list(db.code_snippets.aggregate(pipeline, allowDiskUse=True))` |
| `/webapp/app.py` | 7172 | `aggregate` | `docs = list(db.code_snippets.aggregate(old_pipeline, allowDiskUse=True))` |
| `/webapp/app.py` | 7453 | `find_one` | `return dict(db.code_snippets.find_one(` |
| `/webapp/app.py` | 7948 | `find_one` | `user_doc = db.users.find_one({'user_id': user_id}) or {}` |
| `/webapp/app.py` | 7952 | `update_one` | `db.users.update_one(` |
| `/webapp/app.py` | 8006 | `find_one` | `token_doc = db.webapp_tokens.find_one({` |
| `/webapp/app.py` | 8019 | `delete_one` | `db.webapp_tokens.delete_one({'_id': token_doc['_id']})` |
| `/webapp/app.py` | 8025 | `delete_one` | `db.webapp_tokens.delete_one({'_id': token_doc['_id']})` |
| `/webapp/app.py` | 8029 | `find_one` | `user = db.users.find_one({'user_id': int(user_id)}) or {}` |
| `/webapp/app.py` | 8031 | `update_one` | `db.users.update_one(` |
| `/webapp/app.py` | 8090 | `delete_one` | `db.remember_tokens.delete_one({'token': token})` |
| `/webapp/app.py` | 8188 | `find` | `cursor = db.sticky_notes.find({'_id': {'$in': object_ids}, 'user_id': int(user_id)}, projection)` |
| `/webapp/app.py` | 8195 | `find` | `cursor = db.sticky_notes.find({'_id': {'$in': plain_ids}, 'user_id': int(user_id)}, projection)` |
| `/webapp/app.py` | 8223 | `find` | `cursor = db.code_snippets.find({'_id': {'$in': object_ids}}, {'file_name': 1})` |
| `/webapp/app.py` | 8278 | `find` | `cursor = db.code_snippets.find(` |
| `/webapp/app.py` | 8321 | `find` | `cursor = db.note_reminders.find(` |
| `/webapp/app.py` | 8416 | `count_documents` | `subs_count = db.push_subscriptions.count_documents({'user_id': {'$in': variants}})` |
| `/webapp/app.py` | 8423 | `find` | `cur = db.push_subscriptions.find({'user_id': {'$in': variants}}, {'updated_at': 1}).sort('updated_at', DESCENDING).limit(1)` |
| `/webapp/app.py` | 8431 | `count_documents` | `pending_count = db.note_reminders.count_documents({'user_id': user_id, 'status': {'$in': ['pending', 'snoozed']}})` |
| `/webapp/app.py` | 8437 | `find` | `cur = db.note_reminders.find(` |
| `/webapp/app.py` | 8449 | `find` | `cur = db.note_reminders.find(` |
| `/webapp/app.py` | 8526 | `count_documents` | `total_notes = db.sticky_notes.count_documents({'user_id': user_id})` |
| `/webapp/app.py` | 8530 | `find` | `cursor = db.sticky_notes.find({'user_id': user_id}).sort('updated_at', DESCENDING).limit(limit)` |
| `/webapp/app.py` | 8572 | `count_documents` | `total_files = db.code_snippets.count_documents(active_query)` |
| `/webapp/app.py` | 8597 | `aggregate` | `size_result = list(db.code_snippets.aggregate(pipeline))` |
| `/webapp/app.py` | 8613 | `aggregate` | `top_languages = list(db.code_snippets.aggregate(languages_pipeline))` |
| `/webapp/app.py` | 8616 | `find` | `recent_files = list(db.code_snippets.find(` |
| `/webapp/app.py` | 8841 | `aggregate` | `repos_raw = list(db.code_snippets.aggregate(repo_pipeline))` |
| `/webapp/app.py` | 8852 | `distinct` | `languages = db.code_snippets.distinct(` |
| `/webapp/app.py` | 8905 | `count_documents` | `total_count = int(large_coll.count_documents(query) or 0)` |
| `/webapp/app.py` | 8909 | `find` | `cursor = large_coll.find(query, LIST_EXCLUDE_HEAVY_PROJECTION)` |
| `/webapp/app.py` | 8922 | `aggregate` | `files_cursor = db.code_snippets.aggregate(pipeline + [` |
| `/webapp/app.py` | 8928 | `aggregate` | `count_result = list(db.code_snippets.aggregate(pipeline + [{'$count': 'total'}]))` |
| `/webapp/app.py` | 8958 | `aggregate` | `count_result = list(db.code_snippets.aggregate(count_pipeline))` |
| `/webapp/app.py` | 8969 | `aggregate` | `count_result = list(db.code_snippets.aggregate(count_pipeline))` |
| `/webapp/app.py` | 8972 | `count_documents` | `total_count = db.code_snippets.count_documents(query)` |
| `/webapp/app.py` | 8982 | `find` | `recent_docs = list(db.recent_opens.find({'user_id': user_id}, {'file_name': 1, 'last_opened_at': 1, '_id': 0}))` |
| `/webapp/app.py` | 8988 | `distinct` | `languages = db.code_snippets.distinct(` |
| `/webapp/app.py` | 9078 | `aggregate` | `latest_items = list(db.code_snippets.aggregate(pipeline))` |
| `/webapp/app.py` | 9123 | `distinct` | `languages = db.code_snippets.distinct(` |
| `/webapp/app.py` | 9197 | `aggregate` | `docs = list(db.code_snippets.aggregate(pipeline))` |
| `/webapp/app.py` | 9211 | `aggregate` | `files_cursor = db.code_snippets.aggregate(pipeline)` |
| `/webapp/app.py` | 9215 | `aggregate` | `files_cursor = db.code_snippets.aggregate([` |
| `/webapp/app.py` | 9241 | `aggregate` | `files_cursor = db.code_snippets.aggregate(pipeline)` |
| `/webapp/app.py` | 9272 | `distinct` | `languages = large_coll.distinct(` |
| `/webapp/app.py` | 9282 | `distinct` | `languages = db.code_snippets.distinct(` |
| `/webapp/app.py` | 9342 | `find` | `reg_docs = list(db.code_snippets.find(` |
| `/webapp/app.py` | 9361 | `find` | `large_docs = list(large_coll.find(` |
| `/webapp/app.py` | 9464 | `update_one` | `coll.update_one(` |
| `/webapp/app.py` | 9619 | `find` | `cursor = db.markdown_images.find(` |
| `/webapp/app.py` | 9759 | `find_one` | `image_doc = db.markdown_images.find_one({` |
| `/webapp/app.py` | 9799 | `find_one` | `return db_ref.code_snippets.find_one({'_id': obj_id, 'user_id': user_id})` |
| `/webapp/app.py` | 10257 | `find` | `docs = list(db.code_snippets.find(` |
| `/webapp/app.py` | 10340 | `find_one` | `version_doc = db.code_snippets.find_one({` |
| `/webapp/app.py` | 10351 | `find_one` | `latest_doc = db.code_snippets.find_one(` |
| `/webapp/app.py` | 10411 | `insert_one` | `res = db.code_snippets.insert_one(new_doc)` |
| `/webapp/app.py` | 10457 | `update_many` | `res = db.code_snippets.update_many(` |
| `/webapp/app.py` | 10507 | `update_many` | `res = db.code_snippets.update_many(` |
| `/webapp/app.py` | 10520 | `update_many` | `res2 = large_coll.update_many(` |
| `/webapp/app.py` | 10555 | `delete_many` | `res = db.code_snippets.delete_many({'_id': oid, 'user_id': user_id, 'is_active': False})` |
| `/webapp/app.py` | 10564 | `delete_many` | `res2 = large_coll.delete_many({'_id': oid, 'user_id': user_id, 'is_active': False})` |
| `/webapp/app.py` | 10595 | `find` | `raw_cursor = db.recent_opens.find(` |
| `/webapp/app.py` | 10625 | `find_one` | `file_doc = db.code_snippets.find_one(` |
| `/webapp/app.py` | 10640 | `find_one` | `file_doc = db.code_snippets.find_one(` |
| `/webapp/app.py` | 10717 | `find_one` | `doc = db.code_snippets.find_one(` |
| `/webapp/app.py` | 10731 | `find_one` | `trashed_doc = db.code_snippets.find_one(` |
| `/webapp/app.py` | 10774 | `update_many` | `coll.update_many(` |
| `/webapp/app.py` | 10803 | `find_one` | `file = db.code_snippets.find_one({'_id': ObjectId(file_id), 'user_id': user_id})` |
| `/webapp/app.py` | 10991 | `find_one` | `prev = db.code_snippets.find_one(` |
| `/webapp/app.py` | 11030 | `find` | `cursor = db.markdown_images.find(query).sort('order', 1)` |
| `/webapp/app.py` | 11115 | `insert_one` | `res = db.code_snippets.insert_one(new_doc)` |
| `/webapp/app.py` | 11140 | `distinct` | `user_langs = db.code_snippets.distinct('programming_language', {'user_id': user_id}) if db is not None else []` |
| `/webapp/app.py` | 11160 | `find` | `cursor = db.markdown_images.find(` |
| `/webapp/app.py` | 11464 | `find_one` | `file = db.code_snippets.find_one({` |
| `/webapp/app.py` | 11523 | `aggregate` | `agg = list(db.code_snippets.aggregate([` |
| `/webapp/app.py` | 11589 | `insert_one` | `coll.insert_one(doc)` |
| `/webapp/app.py` | 11650 | `find_one` | `prev = db.code_snippets.find_one(` |
| `/webapp/app.py` | 11682 | `insert_one` | `res = db.code_snippets.insert_one(snippet_doc)` |
| `/webapp/app.py` | 11728 | `insert_many` | `db.markdown_images.insert_many(docs)` |
| `/webapp/app.py` | 12009 | `find_one` | `prev = db.code_snippets.find_one(` |
| `/webapp/app.py` | 12054 | `insert_one` | `res = db.code_snippets.insert_one(doc)` |
| `/webapp/app.py` | 12072 | `distinct` | `raw_languages = db.code_snippets.distinct('programming_language', {'user_id': user_id}) if db is not None else []` |
| `/webapp/app.py` | 12101 | `find_one` | `src = db.code_snippets.find_one({'_id': ObjectId(file_id), 'user_id': user_id})` |
| `/webapp/app.py` | 12122 | `update_many` | `db.code_snippets.update_many(q, {` |
| `/webapp/app.py` | 12163 | `update_many` | `res = db.code_snippets.update_many(q, {` |
| `/webapp/app.py` | 12201 | `update_many` | `res = db.code_snippets.update_many(q, {` |
| `/webapp/app.py` | 12254 | `update_many` | `res = db.code_snippets.update_many(q, {` |
| `/webapp/app.py` | 12284 | `find` | `cursor = db.code_snippets.find({` |
| `/webapp/app.py` | 12336 | `count_documents` | `owned_count = db.code_snippets.count_documents({` |
| `/webapp/app.py` | 12347 | `insert_one` | `db.share_links.insert_one({` |
| `/webapp/app.py` | 12407 | `find` | `docs = list(db.code_snippets.find(` |
| `/webapp/app.py` | 12425 | `update_many` | `res = db.code_snippets.update_many(q, {` |
| `/webapp/app.py` | 12487 | `count_documents` | `'total_files': db.code_snippets.count_documents(active_query),` |
| `/webapp/app.py` | 12488 | `distinct` | `'languages': list(db.code_snippets.distinct('programming_language', active_query)),` |
| `/webapp/app.py` | 12492 | `find` | `recent = db.code_snippets.find(` |
| `/webapp/app.py` | 12613 | `find_one` | `doc = db.remember_tokens.find_one({'token': token, 'user_id': user_id})` |
| `/webapp/app.py` | 12734 | `count_documents` | `'total_files': db.code_snippets.count_documents(active_query),` |
| `/webapp/app.py` | 12735 | `distinct` | `'languages': list(db.code_snippets.distinct('programming_language', active_query)),` |
| `/webapp/app.py` | 12738 | `find` | `recent = db.code_snippets.find(active_query, {'file_name': 1, 'created_at': 1}).sort('created_at', DESCENDING).limit(10)` |
| `/webapp/app.py` | 12809 | `update_one` | `db.remember_tokens.update_one(` |
| `/webapp/app.py` | 12827 | `delete_one` | `db.remember_tokens.delete_one({'user_id': user_id, 'token': token})` |
| `/webapp/app.py` | 12934 | `update_one` | `db.users.update_one(` |
| `/webapp/app.py` | 12979 | `find_one` | `user_doc = db_ref.users.find_one({"user_id": user_id}, {"custom_themes": 1}) or {}` |
| `/webapp/app.py` | 13025 | `find_one` | `user_doc = db_ref.users.find_one(` |
| `/webapp/app.py` | 13072 | `find_one` | `user_doc = db_ref.users.find_one({"user_id": user_id}, {"custom_themes": 1}) or {}` |
| `/webapp/app.py` | 13123 | `update_one` | `db_ref.users.update_one(` |
| `/webapp/app.py` | 13153 | `find_one` | `user_doc = db_ref.users.find_one(` |
| `/webapp/app.py` | 13194 | `update_one` | `result = db_ref.users.update_one(` |
| `/webapp/app.py` | 13219 | `find_one` | `user_doc = db_ref.users.find_one(` |
| `/webapp/app.py` | 13248 | `update_one` | `db_ref.users.update_one(` |
| `/webapp/app.py` | 13253 | `update_one` | `db_ref.users.update_one(` |
| `/webapp/app.py` | 13275 | `find_one` | `user_doc = db_ref.users.find_one(` |
| `/webapp/app.py` | 13288 | `update_one` | `db_ref.users.update_one(` |
| `/webapp/app.py` | 13295 | `update_one` | `db_ref.users.update_one(` |
| `/webapp/app.py` | 13355 | `update_one` | `db.users.update_one(` |
| `/webapp/app.py` | 13363 | `update_one` | `db.users.update_one(` |
| `/webapp/app.py` | 13387 | `update_one` | `db.users.update_one(` |
| `/webapp/app.py` | 13720 | `find` | `global_tags = list(coll.find(` |
| `/webapp/app.py` | 13726 | `find` | `signature_tags = list(coll.find(` |
| `/webapp/app.py` | 13732 | `find` | `instance_tags = list(coll.find(` |
| `/webapp/app.py` | 14210 | `find_one` | `prev = db_ref.code_snippets.find_one(` |
| `/webapp/app.py` | 14259 | `insert_one` | `res = db_ref.code_snippets.insert_one(doc)` |
| `/webapp/app.py` | 14338 | `update_one` | `db.users.update_one(` |
| `/webapp/app.py` | 14377 | `update_one` | `db.users.update_one(` |
| `/webapp/app.py` | 14411 | `count_documents` | `total_users = int(db.users.count_documents({}))` |
| `/webapp/app.py` | 14415 | `count_documents` | `active_users_24h = int(db.users.count_documents({"updated_at": {"$gte": last_24h}}))` |
| `/webapp/app.py` | 14436 | `aggregate` | `res = list(db.code_snippets.aggregate(pipeline, allowDiskUse=True))` |
| `/webapp/app.py` | 14475 | `find_one` | `u = _db.users.find_one({'user_id': session['user_id']}) or {}` |
| `/webapp/app.py` | 14665 | `find_one` | `doc = db.share_links.find_one({'token': token})` |
| `/webapp/app.py` | 14690 | `find` | `cursor = db.code_snippets.find(` |
| `/webapp/app.py` | 14703 | `find` | `cursor = db.code_snippets.find({'_id': {'$in': file_ids}})` |
| `/webapp/bookmarks_api.py` | 61 | `find_one` | `doc = db.code_snippets.find_one({'_id': _ObjectId(file_id)})` |
| `/webapp/bookmarks_api.py` | 684 | `find_one` | `user = db.users.find_one({'user_id': user_id}) or {}` |
| `/webapp/bookmarks_api.py` | 726 | `update_one` | `db.users.update_one(` |
| `/webapp/bookmarks_api.py` | 765 | `find_one` | `doc = db.code_snippets.find_one({'_id': ObjectId(file_id)})` |
| `/webapp/push_api.py` | 385 | `update_one` | `db.push_subscriptions.update_one(` |
| `/webapp/push_api.py` | 429 | `delete_many` | `db.push_subscriptions.delete_many({"user_id": {"$in": _user_id_variants(user_id)}, "endpoint": endpoint})` |
| `/webapp/push_api.py` | 510 | `aggregate` | `due = list(db.note_reminders.aggregate(pipeline))` |
| `/webapp/push_api.py` | 563 | `update_one` | `res = db.note_reminders.update_one(filt, upd)` |
| `/webapp/push_api.py` | 571 | `find` | `subs = list(db.push_subscriptions.find({"user_id": {"$in": _user_id_variants(user_id)}}))` |
| `/webapp/push_api.py` | 756 | `update_one` | `db.note_reminders.update_one(` |
| `/webapp/push_api.py` | 766 | `delete_many` | `db.push_subscriptions.delete_many({"user_id": {"$in": _user_id_variants(user_id)}, "endpoint": {"$in": list(endpoints_to_delete)}})` |
| `/webapp/push_api.py` | 798 | `find_one` | `note = db.sticky_notes.find_one({"_id": oid})` |
| `/webapp/push_api.py` | 803 | `find_one` | `note = db.sticky_notes.find_one({"_id": note_id})` |
| `/webapp/push_api.py` | 833 | `find` | `subs = list(db.push_subscriptions.find({"user_id": {"$in": _user_id_variants(user_id)}}))` |
| `/webapp/push_api.py` | 995 | `find` | `subs = list(db.push_subscriptions.find({"user_id": {"$in": _user_id_variants(user_id)}}))` |
| `/webapp/push_api.py` | 1061 | `count_documents` | `count_before = db.push_subscriptions.count_documents({"user_id": {"$in": _user_id_variants(user_id)}})` |
| `/webapp/push_api.py` | 1062 | `delete_many` | `result = db.push_subscriptions.delete_many(filt)` |
| `/webapp/push_api.py` | 1064 | `count_documents` | `count_after = db.push_subscriptions.count_documents({"user_id": {"$in": _user_id_variants(user_id)}})` |
| `/webapp/push_api.py` | 1099 | `delete_many` | `result = db.push_subscriptions.delete_many({"user_id": {"$in": _user_id_variants(user_id)}})` |
| `/webapp/sticky_notes_api.py` | 347 | `find_one` | `doc = db.code_snippets.find_one({'_id': oid, 'user_id': user_id}, {'file_name': 1})` |
| `/webapp/sticky_notes_api.py` | 355 | `find` | `cursor = db.code_snippets.find({'user_id': user_id, 'file_name': file_name}, {'_id': 1})` |
| `/webapp/sticky_notes_api.py` | 433 | `find` | `cursor = db.sticky_notes.find(query).sort('created_at', 1)` |
| `/webapp/sticky_notes_api.py` | 445 | `update_many` | `db.sticky_notes.update_many({'_id': {'$in': missing_ids}}, {'$set': update_payload})` |
| `/webapp/sticky_notes_api.py` | 563 | `find_one` | `note = db.sticky_notes.find_one({'_id': candidate, 'user_id': int(user_id)})` |
| `/webapp/sticky_notes_api.py` | 583 | `find_one` | `r = db.note_reminders.find_one({'user_id': user_id, 'note_id': str(note_id), 'status': {'$in': ['pending', 'snoozed']}})` |
| `/webapp/sticky_notes_api.py` | 630 | `update_one` | `db.note_reminders.update_one(` |
| `/webapp/sticky_notes_api.py` | 660 | `delete_one` | `db.note_reminders.delete_one({'user_id': user_id, 'note_id': str(note_id)})` |
| `/webapp/sticky_notes_api.py` | 679 | `update_one` | `r = db.note_reminders.update_one(` |
| `/webapp/sticky_notes_api.py` | 706 | `find` | `cursor = db.note_reminders.find({` |
| `/webapp/sticky_notes_api.py` | 762 | `find` | `db.note_reminders` |
| `/webapp/sticky_notes_api.py` | 808 | `find_one` | `note_doc = db.sticky_notes.find_one({'_id': oid, 'user_id': user_id})` |
| `/webapp/sticky_notes_api.py` | 813 | `find_one` | `note_doc = db.sticky_notes.find_one({'_id': note_id, 'user_id': user_id})` |
| `/webapp/sticky_notes_api.py` | 860 | `update_one` | `r = db.note_reminders.update_one(` |
| `/webapp/sticky_notes_api.py` | 914 | `insert_one` | `res = db.sticky_notes.insert_one(doc)` |
| `/webapp/sticky_notes_api.py` | 988 | `find_one` | `note = db.sticky_notes.find_one({'_id': oid, 'user_id': user_id})` |
| `/webapp/sticky_notes_api.py` | 1009 | `update_one` | `db.sticky_notes.update_one({'_id': oid, 'user_id': user_id}, {'$set': updates})` |
| `/webapp/sticky_notes_api.py` | 1046 | `delete_one` | `res = db.sticky_notes.delete_one({'_id': oid, 'user_id': user_id})` |
| `/webapp/sticky_notes_api.py` | 1124 | `find_one` | `note = db.sticky_notes.find_one({'_id': oid, 'user_id': user_id})` |
| `/webapp/sticky_notes_api.py` | 1186 | `update_one` | `db.sticky_notes.update_one({'_id': oid, 'user_id': user_id}, {'$set': updates})` |
