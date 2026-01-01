# 🔍 דו"ח Audit פורנזי - Data Layer MongoDB

**תאריך:** January 1, 2026  
**סקר:** כל נקודות הגישה ל-MongoDB בפרויקט  
**מטרה:** זיהוי צווארי בקבוק, חוסר באינדקסים, ושימוש לא יעיל

---

## 📊 סיכום מנהלים

| דרגת חומרה | כמות ממצאים |
|-----------|-------------|
| 🔴 P0 - קריטי | 4 |
| 🟠 P1 - גבוה | 8 |
| 🟡 P2 - בינוני | 6 |
| 🟢 מידע | הרבה |

### Top 3 בעיות קריטיות:
1. **`$or` על `is_active`** - שובר אינדקסים בשאילתות הכי נפוצות
2. **`$regex` ללא עוגן `^`** - Full Collection Scan בחיפושים
3. **`get_regular_files_paginated` עם `$or` מורכב** - Pipeline כבד ביותר

---

## 🏗️ ארכיטקטורת ה-DAL

### קבצים ראשיים:
| קובץ | תפקיד | Collections |
|------|-------|-------------|
| `database/manager.py` | חיבור + אינדקסים | כל ה-collections |
| `database/repository.py` | CRUD ראשי | code_snippets, large_files, users |
| `database/collections_manager.py` | אוספים/שיתופים | user_collections, collection_items |
| `database/bookmarks_manager.py` | סימניות | file_bookmarks |
| `reminders/database.py` | תזכורות | reminders |
| `monitoring/alerts_storage.py` | התרעות | alerts_log |

### אינדקסים קיימים (database/manager.py):
```python
# code_snippets collection
- (user_id, ASCENDING)
- (file_name, ASCENDING)
- (user_id, is_favorite, favorited_at DESC) - "user_favorites_idx"
- (user_id, is_active, file_name, version DESC) - "user_active_file_latest_idx"  ✅
- (user_id, is_active, updated_at DESC) - "user_active_recent_idx"  ✅
- TEXT index on (code, description, file_name)
- TTL on deleted_expires_at
```

---

## 🔴 P0 - ממצאים קריטיים (COLLSCAN צפוי)

### P0-1: `$or` על `is_active` בשאילתות תכופות

**מיקום:** `cache_commands.py:117-123`
```python
active_query = {
    'user_id': user_id,
    '$or': [
        {'is_active': True},
        {'is_active': {'$exists': False}}
    ]
}
```

| שדה | ערך |
|-----|-----|
| **הסכנה** | `$or` שובר את האינדקס `user_active_file_latest_idx`. MongoDB יבצע OR stage במקום IXSCAN אחד |
| **תדירות** | כל בקשת `/stats`, webhook, polling |
| **Explain צפוי** | `winningPlan.stage: "OR"` עם 2 IXSCAN או COLLSCAN |
| **השפעה** | O(n) על כל המסמכים של המשתמש |

**✅ המלצה:**
```javascript
// מיגרציה חד-פעמית
db.code_snippets.updateMany(
  { is_active: { $exists: false } },
  { $set: { is_active: true } }
);

// שאילתה חדשה
{ user_id: X, is_active: true }
```
> ⚠️ **סיכון:** Write overhead זניח (חד-פעמי)

---

### P0-2: `$or` + `$regex` בחיפוש קבצים

**מיקום:** `webapp/app.py:8791-8797`
```python
query['$and'].append(
    {'$or': [
        {'file_name': {'$regex': search_query, '$options': 'i'}},
        {'description': {'$regex': search_query, '$options': 'i'}},
        {'tags': {'$in': [search_query.lower()]}}
    ]}
)
```

| שדה | ערך |
|-----|-----|
| **הסכנה** | `$regex` ללא עוגן `^` = COLLSCAN. `$or` על 3 שדות = 3 COLLSCAN |
| **תדירות** | כל חיפוש ב-Webapp |
| **Explain צפוי** | `winningPlan.stage: "OR"` עם `COLLSCAN` תחתיו |
| **השפעה** | O(n × m) כאשר n = מסמכים, m = אורך הטקסט |

**✅ המלצות:**
```javascript
// 1. השתמש ב-TEXT Index הקיים
{ user_id: X, $text: { $search: "query" } }

// 2. אם חייבים regex, הוסף עוגן:
{ file_name: { $regex: "^prefix" } }  // IXSCAN

// 3. אינדקס חדש (אם TEXT לא מספיק):
db.code_snippets.createIndex(
  { user_id: 1, file_name: 1 },
  { name: "user_filename_search_idx" }
);
```

---

### P0-3: `get_regular_files_paginated` - Pipeline הרסני

**מיקום:** `database/repository.py:1013-1064`
```python
count_pipeline = [
    {"$match": {"user_id": user_id, "is_active": True}},
    {"$sort": {"file_name": 1, "version": -1}},
    {"$group": {"_id": "$file_name", "latest": {"$first": "$$ROOT"}}},
    {"$replaceRoot": {"newRoot": "$latest"}},
    {"$match": {
        "$or": [
            {"tags": {"$exists": False}},
            {"tags": {"$eq": []}},
            {"tags": {"$not": {"$elemMatch": {"$regex": "^repo:"}}}},
        ]
    }},
    {"$group": {"_id": "$file_name"}},
    {"$count": "count"},
]
```

| שדה | ערך |
|-----|-----|
| **הסכנה** | `$or` עם `$regex` על `tags` **אחרי** `$group` = Full COLLSCAN |
| **תדירות** | כל טעינת רשימת "קבצים רגילים" בעמוד הראשי |
| **Explain צפוי** | `$or` stage + `COLLSCAN` + in-memory `$sort` |
| **זיכרון** | 100MB+ limit ל-aggregation בלי `allowDiskUse` |

**✅ המלצות:**
```javascript
// 1. הוסף שדה computed מראש: has_repo_tag: Boolean
db.code_snippets.updateMany(
  {},
  [{ $set: { has_repo_tag: { $anyElementTrue: { 
    $map: { input: "$tags", as: "t", in: { $regexMatch: { input: "$$t", regex: "^repo:" } } } 
  } } } }]
);

// 2. אינדקס על השדה החדש:
db.code_snippets.createIndex(
  { user_id: 1, is_active: 1, has_repo_tag: 1, updated_at: -1 },
  { name: "user_regular_files_idx" }
);

// 3. שאילתה חדשה:
{ user_id: X, is_active: true, has_repo_tag: false }
```
> ⚠️ **סיכון:** Write overhead על כל save (צריך לעדכן has_repo_tag)

---

### P0-4: `get_users_with_active_drive_schedule` - `$or` על 6 תנאים

**מיקום:** `database/repository.py:1885-1895`
```python
query = {
    "$or": [
        {"drive_prefs.schedule": {"$in": sched_keys}},
        {"drive_prefs.schedule.key": {"$in": sched_keys}},
        {"drive_prefs.schedule.value": {"$in": sched_keys}},
        {"drive_prefs.schedule.name": {"$in": sched_keys}},
        {"drive_prefs.schedule_key": {"$in": sched_keys}},
        {"drive_prefs.scheduleKey": {"$in": sched_keys}},
    ]
}
```

| שדה | ערך |
|-----|-----|
| **הסכנה** | 6-way `$or` על שדות nested = COLLSCAN מוחלט |
| **תדירות** | Startup של Bot + Scheduler |
| **Explain צפוי** | `winningPlan.stage: "OR"` עם 6 COLLSCAN |
| **השפעה** | Startup איטי משמעותית |

**✅ המלצות:**
```javascript
// 1. נרמל את המבנה לשדה אחיד:
db.users.updateMany(
  { "drive_prefs": { $exists: true } },
  [{ $set: { "drive_prefs.normalized_schedule": { 
    $switch: {
      branches: [
        { case: { $in: ["$drive_prefs.schedule", sched_keys] }, then: "$drive_prefs.schedule" },
        { case: { $in: ["$drive_prefs.schedule.key", sched_keys] }, then: "$drive_prefs.schedule.key" },
        // ... etc
      ],
      default: null
    }
  }}}]
);

// 2. אינדקס:
db.users.createIndex(
  { "drive_prefs.normalized_schedule": 1 },
  { name: "drive_schedule_idx", partialFilterExpression: { "drive_prefs.normalized_schedule": { $ne: null } } }
);
```

---

## 🟠 P1 - ממצאים בעדיפות גבוהה

### P1-1: `distinct` ללא אינדקס מתאים

**מיקום:** `webapp/app.py:8852-8858`, `8988`, `9123`, `9272`, `9282`
```python
languages = db.code_snippets.distinct(
    'programming_language',
    {'user_id': user_id, 'is_active': {'$ne': False}}
)
```

| שדה | ערך |
|-----|-----|
| **הסכנה** | `distinct` סורק את כל המסמכים התואמים. אין אינדקס על `programming_language` בלבד |
| **תדירות** | כל טעינת דף קבצים |
| **Explain צפוי** | `IXSCAN` או `COLLSCAN` + DISTINCT_SCAN |

**✅ המלצה:**
```javascript
db.code_snippets.createIndex(
  { user_id: 1, is_active: 1, programming_language: 1 },
  { name: "user_active_lang_distinct_idx" }
);
```
> אינדקס קיים `user_active_lang_idx` קרוב אבל לא מכסה `is_active: { $ne: False }`

---

### P1-2: חיפוש קוד עם `$regexFind`

**מיקום:** `webapp/app.py:7068-7101`
```python
match_stage = {
    'user_id': user_id,
    'is_active': True,
    'code': {
        '$regex': pattern,
        '$options': 'i',
    },
}
# Later:
{'$addFields': {
    '_m': {'$regexFind': {'input': '$code', 'regex': pattern, 'options': 'i'}},
}}
```

| שדה | ערך |
|-----|-----|
| **הסכנה** | `$regex` על שדה `code` (כבד!) ללא עוגן. `$regexFind` ב-pipeline מכביד יותר |
| **תדירות** | כל חיפוש בקוד |
| **Explain צפוי** | `COLLSCAN` על כל הקבצים, קריאת כל תוכן הקוד |

**✅ המלצות:**
1. השתמש ב-TEXT Index הקיים: `{ $text: { $search: "query" } }`
2. אם צריך regex: **הגבל ל-100 קבצים** ראשונים ואז סנן בפייתון
3. שקול Atlas Search או Elasticsearch לחיפוש קוד

---

### P1-3: `list_public_snippets` עם `$or` + `$regex`

**מיקום:** `database/repository.py:2163-2166`
```python
if q:
    regex = {"$regex": q, "$options": "i"}
    match["$or"] = [{"title": regex}, {"description": regex}, {"code": regex}]
```

| שדה | ערך |
|-----|-----|
| **הסכנה** | `$or` על 3 שדות עם `$regex` case-insensitive |
| **תדירות** | כל חיפוש בספריית ה-Snippets הציבורית |
| **Collection** | `snippets` (ציבורי) |

**✅ המלצה:**
```javascript
// TEXT index כבר קיים על snippets:
// IndexModel([("title", TEXT), ("description", TEXT), ("code", TEXT)])
// השתמש ב-$text:
{ status: "approved", $text: { $search: q } }
```

---

### P1-4: `sort` ללא `limit` בכמה מקומות

**מיקום:** `webapp/app.py:8908-8911`
```python
cursor = large_coll.find(query, LIST_EXCLUDE_HEAVY_PROJECTION)
cursor = cursor.sort(sort_field_local, sort_dir)
cursor = cursor.skip((page - 1) * per_page).limit(per_page)
```

> **הערה:** למרות שיש limit, יש כאן sort **לפני** skip. MongoDB צריך לסדר את כל התוצאות לפני הדילוג.

| שדה | ערך |
|-----|-----|
| **הסכנה** | `sort` על כמות גדולה של מסמכים → in-memory sort |
| **תדירות** | כל דפדוף בקבצים גדולים |
| **Explain צפוי** | `SORT` stage עם `memLimit` |

**✅ המלצה:**
```javascript
// ודא שיש אינדקס שמכסה את ה-sort:
db.large_files.createIndex(
  { user_id: 1, is_active: 1, created_at: -1 },
  { name: "user_large_sorted_idx" }
);
```

---

### P1-5: `get_repo_tags_with_counts` עם `$regex` ב-pipeline

**מיקום:** `database/repository.py:1492-1496`
```python
pipeline = [
    {"$match": {"user_id": user_id}},
    {"$project": {"tags": 1, "file_name": 1, "is_active": 1}},
    {"$unwind": {"path": "$tags", "preserveNullAndEmptyArrays": False}},
    {"$match": {"tags": {"$regex": "^repo:"}}},
    ...
]
```

| שדה | ערך |
|-----|-----|
| **הסכנה** | `$regex` על `tags` **אחרי** `$unwind` = בדיקה על כל אלמנט |
| **תדירות** | טעינת תפריט ריפוזיטוריות |
| **Explain צפוי** | `COLLSCAN` על כל המסמכים של המשתמש |

**✅ המלצה:**
```javascript
// הוסף אינדקס על tags:
db.code_snippets.createIndex(
  { user_id: 1, tags: 1 },
  { name: "user_tags_multikey_idx" }
);

// בשאילתה, סנן tags לפני unwind:
{ user_id: X, tags: { $elemMatch: { $regex: "^repo:" } } }
```

---

### P1-6: `monitoring/alerts_storage.py` - `$regex` על `alert_type`

**מיקום:** `monitoring/alerts_storage.py:999-1003`
```python
safe_pattern = re.escape(normalized_type)
match = {
    "alert_type": {"$regex": f"^{safe_pattern}$", "$options": "i"},
    ...
}
```

| שדה | ערך |
|-----|-----|
| **הסכנה** | `$regex` עם `$options: "i"` מונע שימוש באינדקס |
| **תדירות** | שאילתות סטטיסטיקה |
| **Collection** | `alerts_log` |

**✅ המלצה:**
```javascript
// נרמל את alert_type ל-lowercase בזמן כתיבה
// ואז השתמש בשאילתה ישירה:
{ alert_type: normalized_type.lower() }
```

---

### P1-7: `push_api.py` - `$or` עם `$expr`

**מיקום:** `webapp/push_api.py:496-502`
```python
{
    "ack_at": None,
    "remind_at": {"$lte": now},
    "$expr": {
        "$or": [
            {"$eq": ["$last_push_success_at", None]},
            {"$lt": ["$last_push_success_at", "$remind_at"]},
        ]
    }
}
```

| שדה | ערך |
|-----|-----|
| **הסכנה** | `$expr` עם `$or` אינו יכול להשתמש באינדקס רגיל |
| **תדירות** | Push notification polling |
| **Collection** | `note_reminders` |

**✅ המלצות:**
```javascript
// 1. הוסף שדה computed: needs_push
// 2. אינדקס:
db.note_reminders.createIndex(
  { status: 1, remind_at: 1, needs_push: 1 },
  { name: "push_polling_idx" }
);
```

---

### P1-8: `push_api.py` - שאילתה נוספת עם `$or`

**מיקום:** `webapp/push_api.py:548-554`
```python
{
    "ack_at": None,
    "status": {"$in": ["pending", "snoozed"]},
    "$or": [
        {"push_claimed_until": {"$exists": False}},
        {"push_claimed_until": {"$lte": now}},
    ],
}
```

| שדה | ערך |
|-----|-----|
| **הסכנה** | `$or` על `$exists` שובר אינדקסים |
| **תדירות** | Push claim polling |

**✅ המלצה:**
```javascript
// מיגרציה: קבע ערך ברירת מחדל
db.note_reminders.updateMany(
  { push_claimed_until: { $exists: false } },
  { $set: { push_claimed_until: new Date(0) } }
);

// שאילתה חדשה:
{ push_claimed_until: { $lte: now } }
```

---

## 🟡 P2 - ממצאים בעדיפות בינונית

### P2-1: `collections_manager.py` - `count_documents` תכופים

**מיקום:** `database/collections_manager.py:262`, `438`, `474`
```python
total = int(self.collections.count_documents({"user_id": int(user_id), "is_active": True}))
```

| שדה | ערך |
|-----|-----|
| **הסכנה** | `count_documents` יקר יותר מ-`estimated_document_count` |
| **תדירות** | כל יצירת אוסף / בדיקת מגבלות |

**✅ המלצה:** שקול `estimated_document_count()` כשלא צריך דיוק מלא.

---

### P2-2: `aggregate` עם `$group` על `file_name` חוזר

**מיקום:** רבים - `repository.py`, `app.py`
```python
pipeline = [
    {"$match": {...}},
    {"$sort": {"file_name": 1, "version": -1}},
    {"$group": {"_id": "$file_name", "latest": {"$first": "$$ROOT"}}},
    {"$replaceRoot": {"newRoot": "$latest"}},
    ...
]
```

| שדה | ערך |
|-----|-----|
| **הסכנה** | `$group` על שדה לא-אינדקסי דורש in-memory aggregation |
| **תדירות** | רוב השאילתות |

**✅ המלצה:** ודא שהאינדקס `user_active_file_latest_idx` מכסה את ה-`$sort` שלפני ה-`$group`.

---

### P2-3: `bookmarks_manager.py` - `aggregate` עם `$group`

**מיקום:** `database/bookmarks_manager.py:300-320`
```python
pipeline = [
    {"$match": {"user_id": user_id, "valid": {"$ne": False}}},
    {"$sort": {"created_at": -1}},
    {"$skip": skip},
    {"$limit": limit},
    {"$group": {...}},
    {"$sort": {"count": -1}}
]
```

| שדה | ערך |
|-----|-----|
| **הסכנה** | שני `$sort` stages + `$group` |
| **תדירות** | דף סימניות של משתמש |
| **Collection** | `file_bookmarks` |

**✅ המלצה:** האינדקס `user_recent_bookmarks` אמור לכסות.

---

### P2-4: `snippet_library_service.py` - `$or` + `$regex`

**מיקום:** `services/snippet_library_service.py:117-127`
```python
if q:
    regex = {"$regex": q, "$options": "i"}
    match_filters.append({
        "$or": [
            {"title": regex},
            {"description": regex},
            {"code": regex},
        ]
    })
match_filters.append({"$or": title_filters})
```

| שדה | ערך |
|-----|-----|
| **הסכנה** | `$or` כפול עם `$regex` |
| **תדירות** | חיפוש בספרייה |
| **Collection** | `snippets` |

**✅ המלצה:** השתמש ב-TEXT index.

---

### P2-5: `community_library_service.py` - `$or` + `$regex`

**מיקום:** `services/community_library_service.py:187-190`
```python
if q:
    regex = {"$regex": q, "$options": "i"}
    match["$or"] = [{"title": regex}, {"description": regex}]
```

| שדה | ערך |
|-----|-----|
| **הסכנה** | `$regex` case-insensitive |
| **Collection** | `community_library_items` |

---

### P2-6: `alert_tags_storage.py` - `$regex` ב-aggregation

**מיקום:** `monitoring/alert_tags_storage.py:385-391`
```python
pipeline = [
    {"$unwind": "$tags"},
    {"$match": {"tags": {"$regex": f"^{safe_prefix}", "$options": "i"}}},
    {"$group": {"_id": "$tags", "count": {"$sum": 1}}},
    ...
]
```

| שדה | ערך |
|-----|-----|
| **הסכנה** | `$regex` אחרי `$unwind` על כל אלמנט |
| **Collection** | alerts |

---

## 📋 אינדקסים מומלצים - סיכום

### code_snippets collection
```javascript
// חדש - לשאילתות regular files
db.code_snippets.createIndex(
  { user_id: 1, is_active: 1, has_repo_tag: 1, updated_at: -1 },
  { name: "user_regular_files_idx" }
);

// חדש - לחיפוש שמות קבצים
db.code_snippets.createIndex(
  { user_id: 1, file_name: 1 },
  { name: "user_filename_search_idx" }
);

// שיפור distinct
db.code_snippets.createIndex(
  { user_id: 1, is_active: 1, programming_language: 1 },
  { name: "user_active_lang_distinct_idx" }
);
```

### users collection
```javascript
// לשאילתת drive schedule
db.users.createIndex(
  { "drive_prefs.normalized_schedule": 1 },
  { 
    name: "drive_schedule_idx",
    partialFilterExpression: { "drive_prefs.normalized_schedule": { $ne: null } }
  }
);
```

### note_reminders collection
```javascript
// ל-push polling
db.note_reminders.createIndex(
  { status: 1, remind_at: 1, push_claimed_until: 1 },
  { name: "push_polling_idx" }
);
```

---

## 🔧 פעולות מיגרציה מומלצות

### 1. תיקון `is_active` (חד-פעמי)
```javascript
// הרץ על כל ה-collections הרלוונטיים
db.code_snippets.updateMany(
  { is_active: { $exists: false } },
  { $set: { is_active: true } }
);
db.large_files.updateMany(
  { is_active: { $exists: false } },
  { $set: { is_active: true } }
);
```

### 2. הוספת `has_repo_tag`
```javascript
db.code_snippets.updateMany(
  {},
  [{
    $set: {
      has_repo_tag: {
        $cond: {
          if: { $isArray: "$tags" },
          then: {
            $anyElementTrue: {
              $map: {
                input: "$tags",
                as: "t",
                in: { $regexMatch: { input: "$$t", regex: /^repo:/ } }
              }
            }
          },
          else: false
        }
      }
    }
  }]
);
```

### 3. נרמול `push_claimed_until`
```javascript
db.note_reminders.updateMany(
  { push_claimed_until: { $exists: false } },
  { $set: { push_claimed_until: new Date(0) } }
);
```

---

## 📊 Explain Queries - כיצד לבדוק

```javascript
// בדיקת שאילתה ספציפית
db.code_snippets.find({
  user_id: 12345,
  is_active: true
}).explain("executionStats");

// בדיקת pipeline
db.code_snippets.explain("executionStats").aggregate([
  { $match: { user_id: 12345, is_active: true } },
  { $sort: { file_name: 1, version: -1 } },
  { $group: { _id: "$file_name", latest: { $first: "$$ROOT" } } }
]);

// מה לחפש בתוצאות:
// - winningPlan.stage: "COLLSCAN" ❌ (רע)
// - winningPlan.stage: "IXSCAN" ✅ (טוב)
// - winningPlan.stage: "OR" ⚠️ (בעייתי)
// - executionStats.totalDocsExamined >> totalDocsReturned ❌
// - executionStats.memUsage > 100MB ❌
```

---

## 📅 סדר עדיפויות לתיקון

| עדיפות | משימה | השפעה צפויה |
|--------|-------|-------------|
| 1️⃣ | מיגרציית `is_active` | -50% זמן שאילתות בסיסיות |
| 2️⃣ | הוספת `has_repo_tag` | -80% זמן `get_regular_files` |
| 3️⃣ | החלפת `$regex` ב-`$text` | -70% זמן חיפוש |
| 4️⃣ | נרמול `drive_prefs.schedule` | -90% זמן startup |
| 5️⃣ | אינדקסים חדשים | -30% overall |

---

**נערך על ידי:** Audit אוטומטי  
**גרסה:** 1.0  
**הערה:** יש להריץ `explain()` על כל שאילתה בסביבת production לאימות הממצאים.
