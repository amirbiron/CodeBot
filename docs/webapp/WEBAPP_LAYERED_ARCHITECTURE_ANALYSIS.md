# ניתוח ארכיטקטורת שכבות: WebApp מול FilesFacade

## סקירה כללית

מסמך זה מתעד את ניתוח הפערים בין ה-WebApp לתשתית השכבות הקיימת (FilesFacade, SnippetService),
ומגדיר תוכנית להחלפה הדרגתית של גישות DB ישירות.

**תאריך:** ינואר 2026  
**גרסה:** 1.0

---

## מצב נוכחי (ינואר 2026)

### קריאות `get_db()` ב-WebApp

| קובץ | קריאות `get_db()` | גישות ישירות לאוספים | ייבואים ישירים מ-database |
|------|-------------------|----------------------|---------------------------|
| `webapp/app.py` | ~93 | `db.code_snippets`, `db.users`, `db.large_files`, ועוד | כן - `database.repository` |
| `webapp/themes_api.py` | ~17 | `db.users` (custom_themes, ui_prefs) | לא |
| `webapp/sticky_notes_api.py` | ~15 | `db.sticky_notes`, `db.note_reminders`, `db.code_snippets` | לא |
| `webapp/push_api.py` | ~13 | `db.push_subscriptions`, `db.note_reminders`, `db.sticky_notes` | לא |
| `webapp/rules_api.py` | ~8 | (דרך RulesStorage) | לא |
| `webapp/bookmarks_api.py` | ~7 | `db.code_snippets`, `db.users` | **כן** - `database.bookmarks_manager`, `database.bookmark` |
| `webapp/collections_api.py` | ~5 | (דרך CollectionsManager) | **כן** - `database.collections_manager` |
| `webapp/routes/repo_browser.py` | ~5 | `db.repo_files`, `db.repo_metadata` | **כן** - `database.db_manager` |
| `webapp/routes/webhooks.py` | ~1 | | **כן** - `database.db_manager` |
| **סה"כ** | **~174** | | |

### שימוש ב-Facade/Services

| שירות | שימוש ב-WebApp? | הערות |
|-------|-----------------|-------|
| `get_files_facade()` | ❌ **אפס** | לא בשימוש כלל |
| `get_snippet_service()` | ❌ **אפס** | לא בשימוש כלל |
| `BookmarksManager` | ✅ דרך ייבוא ישיר | צריך עטיפה ב-Facade |
| `CollectionsManager` | ✅ דרך ייבוא ישיר | צריך עטיפה ב-Facade |
| `RulesStorage` | ✅ דרך service | כבר מופרד |

---

## פעולות קיימות ב-FilesFacade

### פעולות קבצים (✅ קיים)
- `get_user_files()` - עם pagination
- `get_user_file_names()`
- `get_file()`, `get_file_by_id()`
- `get_latest_version()`, `get_version()`, `get_all_versions()`
- `save_file()`, `save_code_snippet()`
- `delete_file()`, `delete_file_by_id()`
- `rename_file()`
- `get_user_document_by_id()`

### קבצים גדולים (✅ קיים)
- `get_user_large_files()`
- `get_large_file()`, `get_large_file_by_id()`
- `save_large_file()`
- `delete_large_file()`
- `get_all_user_files_combined()`

### מועדפים (✅ קיים)
- `toggle_favorite()`
- `get_favorites()`
- `get_favorites_count()`
- `is_favorite()`

### GitHub/Drive (✅ קיים)
- `get_github_token()`, `delete_github_token()`
- `get_selected_repo()`, `save_selected_repo()`
- `get_selected_folder()`, `save_selected_folder()`
- `get_drive_tokens()`, `delete_drive_tokens()`
- `get_drive_prefs()`, `save_drive_prefs()`

### העדפות תמונה (✅ קיים)
- `get_image_prefs()`
- `save_image_prefs()`

### חיפוש ו-Tags (✅ קיים)
- `search_code()`
- `get_user_files_by_repo()`
- `get_repo_tags_with_counts()`

### פעולות אשפה/שחזור (✅ קיים)
- `list_deleted_files()`
- `restore_file_by_id()`
- `purge_file_by_id()`

### גיבויים (✅ קיים)
- `get_backup_rating()`, `save_backup_rating()`
- `get_backup_note()`, `save_backup_note()`
- `delete_backup_ratings()`

### משתמשים ואדמין (✅ קיים)
- `save_user()`
- `list_active_user_ids()`
- `mark_user_blocked()`, `mark_users_blocked()`
- `find_user_id_by_username()`

### פעולות עזר (✅ קיים)
- `get_mongo_db()`
- `insert_webapp_login_token()`
- `insert_temp_document()`
- `insert_refactor_metadata()`
- `get_regular_files_paginated()`

---

## פעולות חסרות ב-FilesFacade

### 1. העדפות משתמש (User Preferences)
```python
# חסר:
get_user_prefs(user_id: int) -> Dict[str, Any]
save_user_prefs(user_id: int, prefs: Dict[str, Any]) -> bool
get_ui_prefs(user_id: int) -> Dict[str, Any]
save_ui_prefs(user_id: int, prefs: Dict[str, Any]) -> bool
```

### 2. ערכות נושא (Custom Themes)
```python
# חסר:
get_user_themes(user_id: int) -> List[Dict]
get_user_theme(user_id: int, theme_id: str) -> Optional[Dict]
save_user_theme(user_id: int, theme_doc: Dict) -> str
update_user_theme(user_id: int, theme_id: str, updates: Dict) -> bool
delete_user_theme(user_id: int, theme_id: str) -> bool
activate_user_theme(user_id: int, theme_id: str) -> bool
```

### 3. Bookmarks (עטיפה ל-BookmarksManager)
```python
# חסר - צריך עטיפה:
get_bookmarks_manager() -> BookmarksManager
```

### 4. Collections (עטיפה ל-CollectionsManager)
```python
# חסר - צריך עטיפה:
get_collections_manager() -> CollectionsManager
```

### 5. פתקים דביקים (Sticky Notes)
```python
# חסר לחלוטין:
get_sticky_notes(user_id: int, file_id: str) -> List[Dict]
create_sticky_note(user_id: int, file_id: str, data: Dict) -> str
update_sticky_note(user_id: int, note_id: str, data: Dict) -> bool
delete_sticky_note(user_id: int, note_id: str) -> bool
```

### 6. תזכורות לפתקים (Note Reminders)
```python
# חסר לחלוטין:
get_note_reminder(user_id: int, note_id: str) -> Optional[Dict]
set_note_reminder(user_id: int, note_id: str, data: Dict) -> bool
delete_note_reminder(user_id: int, note_id: str) -> bool
snooze_note_reminder(user_id: int, note_id: str, minutes: int) -> bool
```

### 7. Push Subscriptions
```python
# חסר לחלוטין:
get_push_subscriptions(user_id: int) -> List[Dict]
save_push_subscription(user_id: int, subscription: Dict) -> bool
delete_push_subscription(user_id: int, endpoint: str) -> bool
```

### 8. Rules (עטיפה ל-RulesStorage)
```python
# חסר - צריך עטיפה:
get_rules_storage() -> RulesStorage
```

---

## מיפוי Routes → שכבות

### פעולות שכבר יכולות לעבור ל-Facade (ללא שינוי)

| Route/Endpoint | מצב נוכחי | יעד Facade |
|----------------|-----------|------------|
| `GET /api/files` | `db.code_snippets.find()` | `get_files_facade().get_user_files()` |
| `GET /api/file/<id>` | `db.code_snippets.find_one()` | `get_files_facade().get_file_by_id()` |
| `POST /api/save` | `db.code_snippets.insert_one()` | `get_files_facade().save_file()` |
| `DELETE /api/file/<id>` | `db.delete_file_by_id()` | `get_files_facade().delete_file_by_id()` |
| `POST /api/favorite/<name>` | `db.toggle_favorite()` | `get_files_facade().toggle_favorite()` |
| `GET /api/favorites` | `db.get_favorites()` | `get_files_facade().get_favorites()` |
| `GET /api/versions/<name>` | `db.get_all_versions()` | `get_files_facade().get_all_versions()` |
| `GET /api/search` | `search_engine.search()` | `get_files_facade().search_code()` |
| `GET /api/trash` | `list_deleted_files()` | `get_files_facade().list_deleted_files()` |
| `POST /api/trash/restore` | `restore_file_by_id()` | `get_files_facade().restore_file_by_id()` |

### פעולות שדורשות הרחבת Facade

| Route/Endpoint | מצב נוכחי | נדרש |
|----------------|-----------|------|
| `GET /api/themes` | `db.users.find_one(custom_themes)` | `get_user_themes()` |
| `POST /api/themes` | `db.users.update_one($push)` | `save_user_theme()` |
| `GET /api/bookmarks/*` | `BookmarksManager(get_db())` | `get_bookmarks_manager()` |
| `GET /api/collections/*` | `CollectionsManager(get_db())` | `get_collections_manager()` |
| `GET /api/sticky-notes/*` | `db.sticky_notes.find()` | פעולות sticky notes |
| `POST /api/push/subscribe` | `db.push_subscriptions.update_one()` | `save_push_subscription()` |

---

## Roadmap ליישום

### שלב 1: ניתוח פערים ✅
- [x] סריקת כל קריאות `get_db()` ב-webapp
- [x] מיפוי כל קריאה → פעולה ב-Facade (או "חסר")
- [x] יצירת רשימת פעולות להוספה ל-Facade

### שלב 2: הרחבת Facade
- [ ] הוספת עטיפות לניהול Managers (Bookmarks, Collections, Rules)
- [ ] הוספת פעולות User Preferences / UI Prefs
- [ ] הוספת פעולות Custom Themes
- [ ] טסטים לעטיפות החדשות

### שלב 3: פיילוט
- [ ] בחירת endpoint פשוט (למשל `GET /api/files`)
- [ ] החלפת `get_db()` ב-`get_files_facade()`
- [ ] בדיקות ידניות + integration test

### שלב 4: החלפה הדרגתית ב-`webapp/app.py`
- [ ] החלפת קריאות `get_db()` הדרגתית
- [ ] חלוקה ל-PRים קטנים (10-20 קריאות כל PR)

### שלב 5: טיהור APIs נוספים
- [ ] `themes_api.py`
- [ ] `bookmarks_api.py` (+ הסרת ייבואים ישירים)
- [ ] `sticky_notes_api.py`
- [ ] `push_api.py`
- [ ] `collections_api.py` (+ הסרת ייבואים ישירים)
- [ ] `routes/repo_browser.py` (+ הסרת ייבואים ישירים)

### שלב 6: הקשחה ואכיפה
- [ ] טסט ארכיטקטוני ל-webapp
- [ ] הסרת `get_db()` מ-webapp (או deprecated)
- [ ] עדכון CI להריץ architecture tests

---

## דוגמה: לפני ואחרי

### לפני (מצב נוכחי)

```python
# webapp/app.py
@app.route('/api/files')
@require_auth
def api_get_files():
    user_id = session['user_id']
    db = get_db()
    
    # לוגיקה ב-route
    files = list(db.code_snippets.find(
        {'user_id': user_id, 'deleted': {'$ne': True}},
        {'code': 0}  # projection ידני
    ).sort('updated_at', -1).limit(50))
    
    # עיבוד ידני
    for f in files:
        f['_id'] = str(f['_id'])
        f['created_at'] = f.get('created_at', '').isoformat() if f.get('created_at') else None
    
    return jsonify({'ok': True, 'files': files})
```

### אחרי (עם Facade)

```python
# webapp/app.py
from src.infrastructure.composition import get_files_facade

@app.route('/api/files')
@require_auth
def api_get_files():
    user_id = session['user_id']
    facade = get_files_facade()
    
    # הכל עובר דרך Facade
    files = facade.get_user_files(user_id, limit=50)
    
    # Facade כבר מחזיר dicts מעובדים
    return jsonify({'ok': True, 'files': files})
```

---

## ROI צפוי

| תועלת | הסבר |
|-------|------|
| **קוד DRY** | אותה לוגיקה לבוט ול-WebApp |
| **בדיקות קלות** | Mock ל-Facade במקום DB אמיתי |
| **פחות באגים** | מקור אמת אחד (LanguageDetector, validation) |
| **Onboarding** | מפתח חדש לומד API אחד (Facade) |
| **Rollback בטוח** | PRים קטנים, שינויים הפיכים |

---

## קבצי עזר

- `src/infrastructure/composition/files_facade.py` – ה-Facade הקיים
- `src/infrastructure/composition/container.py` – Composition Root
- `tests/unit/architecture/test_layer_boundaries.py` – טסטים ארכיטקטוניים
- `docs/ARCHITECTURE_LAYER_RULES.md` – כללי שכבות
