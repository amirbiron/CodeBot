# פרומפט: פיצול WebApp לשכבות (גרסה מעודכנת - ינואר 2026)

> **עדכון חשוב:** פרומפט זה עודכן לאחר השלמת פיצול שכבות הבוט.  
> קיימת כבר תשתית Domain/Application/Infrastructure מוכנה לשימוש משותף.

---

את/ה פועל/ת כ-Software Architect מנוסה לארכיטקטורה שכבתית (Layered Architecture) בפרויקטי Python Web (Flask), עם שילוב ושיתוף שכבת Domain/Services מול בוט Telegram.

## המטרה

לחבר את ה-WebApp לתשתית השכבות הקיימת (שנבנתה עבור הבוט), ולהסיר גישות DB ישירות מה-routes.  
**לא בונים ארכיטקטורה מאפס** – משתמשים בתשתית הקיימת ומרחיבים לפי הצורך.

---

## הקשר על הפרויקט

### תשתית קיימת (הושלמה)

הבוט עבר פיצול מלא לשכבות. קיימים:

```
src/
├── domain/                          # שכבת Domain (טהורה)
│   ├── entities/snippet.py          # Snippet entity
│   ├── interfaces/                  # Repository interfaces
│   └── services/
│       ├── language_detector.py     # מקור אמת לזיהוי שפה
│       └── code_normalizer.py       # נרמול קוד
│
├── application/                     # שכבת Application
│   ├── dto/create_snippet_dto.py    # DTOs
│   └── services/snippet_service.py  # SnippetService
│
└── infrastructure/                  # שכבת Infrastructure
    ├── composition/
    │   ├── container.py             # Composition Root: get_snippet_service()
    │   └── files_facade.py          # FilesFacade: 50+ פעולות DB
    └── database/mongodb/repositories/
        └── snippet_repository.py    # מימוש Repository
```

**נקודות כניסה זמינות:**
- `get_snippet_service()` – שירות מלא לניהול snippets (save, get, versions, language detection)
- `get_files_facade()` – facade ל-DB עם 50+ פעולות (favorites, large files, search, Drive/GitHub tokens, etc.)

**טסטים ארכיטקטוניים:** 6 טסטים ב-`tests/unit/architecture/test_layer_boundaries.py` אוכפים גבולות שכבות.

### מצב ה-WebApp כרגע (ינואר 2026)

| קובץ | קריאות `get_db()` | הערות |
|------|-------------------|-------|
| `webapp/app.py` | ~112 | קובץ ראשי, רוב הלוגיקה |
| `webapp/themes_api.py` | ~19 | ניהול themes |
| `webapp/sticky_notes_api.py` | ~18 | פתקים |
| `webapp/bookmarks_api.py` | ~7 | + ייבוא ישיר מ-`database.bookmarks_manager` |
| `webapp/push_api.py` | ~14 | Push notifications |
| שאר ה-APIs | ~19 | rules, collections, routes |
| **סה"כ** | **~189** | גישות DB ישירות |

**בעיות נוכחיות:**
- אפס שימוש ב-`get_files_facade()` או `get_snippet_service()`
- ייבואים ישירים מ-`database.*` בחלק מה-APIs
- לוגיקה עסקית מעורבבת ב-routes (validation, formatting, DB)
- אין DTOs/Schemas – עבודה ישירה עם dicts

---

## מה אני רוצה לקבל

### 1) ניתוח פערים: Facade מול צרכי WebApp

בדוק אילו פעולות DB נדרשות ב-WebApp ואילו כבר קיימות ב-`FilesFacade`:

| פעולה נדרשת | קיים ב-Facade? | הערות |
|-------------|----------------|-------|
| `get_user_files()` | ✅ | כולל pagination |
| `save_file()` | ✅ | |
| `toggle_favorite()` | ✅ | |
| `get_themes()` | ❓ | לבדוק |
| `save_bookmark()` | ❓ | יש BookmarksManager נפרד |
| ... | | |

**פלט מצופה:** רשימת פעולות חסרות שצריך להוסיף ל-Facade.

### 2) הרחבת FilesFacade (אם נדרש)

אם יש פעולות חסרות:
- הוסף עטיפות ל-`files_facade.py`
- שמור על אותו סגנון (lazy import, fallback בטוח, type hints)
- אל תשכפל לוגיקה – עטוף את הקיים

### 3) החלפה הדרגתית של `get_db()` ל-Facade

**לפני:**
```python
# webapp/app.py
def get_user_files():
    db = get_db()
    return list(db.code_snippets.find({'user_id': user_id}))
```

**אחרי:**
```python
# webapp/app.py
from src.infrastructure.composition import get_files_facade

def get_user_files():
    facade = get_files_facade()
    return facade.get_user_files(user_id)
```

### 4) מיפוי routes → שכבות

| Route/Endpoint | מצב נוכחי | יעד |
|----------------|-----------|-----|
| `GET /files` | `get_db().code_snippets.find()` | `get_files_facade().get_user_files()` |
| `POST /save` | validation + DB ב-route | schema → `get_snippet_service().save()` |
| `GET /api/bookmarks` | `BookmarksManager(get_db())` | `get_files_facade().get_bookmarks()` |
| ... | | |

### 5) Schemas (Pydantic) – אופציונלי בשלב ראשון

אם יש זמן, הוסף request/response schemas:

```python
# webapp/schemas/snippet_schemas.py
from pydantic import BaseModel

class SaveSnippetRequest(BaseModel):
    file_name: str
    code: str
    language: str | None = None

class SnippetResponse(BaseModel):
    id: str
    file_name: str
    language: str
    created_at: datetime
```

### 6) טסטים ארכיטקטוניים ל-WebApp

הרחב את `test_layer_boundaries.py` כך שיבדוק גם webapp:

```python
def test_webapp_does_not_import_database_directly():
    """WebApp routes must not import database directly."""
    files = list(_python_files_under("webapp"))
    # מותר: src.infrastructure.composition
    # אסור: database, database.*
    forbidden = ("database",)
    allowed = ("src.infrastructure.composition",)
    violations = _violations(files, forbidden, allowed)
    assert not violations
```

---

## מפת דרכים (Roadmap) מעודכנת

### שלב 1: מיפוי וניתוח (ללא שינוי קוד)
- [ ] סרוק את כל קריאות `get_db()` ב-webapp
- [ ] מפה כל קריאה → פעולה ב-Facade (או "חסר")
- [ ] צור רשימת פעולות להוספה ל-Facade
- **בדיקה:** אין שינוי, רק תיעוד
- **Rollback:** לא נדרש

### שלב 2: הרחבת Facade (אם נדרש)
- [ ] הוסף עטיפות חסרות ל-`files_facade.py`
- [ ] הוסף טסטים לעטיפות החדשות
- **בדיקה:** `pytest tests/unit/` + טסטים חדשים
- **Rollback:** `git revert` – הוספה בלבד, לא שובר קיים

### שלב 3: פיילוט – endpoint אחד
- [ ] בחר endpoint פשוט (למשל `GET /api/files`)
- [ ] החלף `get_db()` ב-`get_files_facade()`
- [ ] בדוק ידנית + הוסף integration test
- **בדיקה:** WebApp עולה, endpoint מחזיר תוצאות נכונות
- **Rollback:** `git revert` של commit בודד

### שלב 4: החלפה מלאה ב-`webapp/app.py`
- [ ] החלף את כל 112 קריאות `get_db()` הדרגתית
- [ ] חלק ל-PRים קטנים (10-20 קריאות כל PR)
- **בדיקה:** CI ירוק, בדיקות ידניות לפי `BOT_TEST_PLAN_CONTAINER.md`
- **Rollback:** PRים קטנים מאפשרים revert נקודתי

### שלב 5: טיהור APIs נוספים
- [ ] `themes_api.py` (19 קריאות)
- [ ] `bookmarks_api.py` (7 קריאות + ייבוא ישיר)
- [ ] `sticky_notes_api.py` (18 קריאות)
- [ ] שאר ה-APIs
- **בדיקה:** כל API בנפרד

### שלב 6: הקשחה ואכיפה
- [ ] הוסף טסט ארכיטקטוני ל-webapp
- [ ] הסר את `get_db()` מ-`webapp/app.py` (או הפוך ל-deprecated)
- [ ] עדכן CI להריץ architecture tests
- **בדיקה:** CI נכשל על הפרות שכבות

---

## דוגמה מלאה: GET /api/files

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

## אילוצים וסגנון

- **עברית** – שפה פשוטה וברורה
- **אין סודות/PII** – לא בקוד ולא בדוגמאות
- **תאימות לאחור** – שינויים הדרגתיים, Feature Flags לפי הצורך
- **אין Prettier על Jinja** – `webapp/templates/**` לא נוגעים בפורמט
- **מחיקות רק ב-tmp** – לפי כללי הפרויקט

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

## Self-check לפני מסירה

- [ ] יש ניתוח פערים: Facade מול צרכי WebApp
- [ ] יש רשימת פעולות להוספה (אם יש)
- [ ] יש דוגמת before/after ל-endpoint אחד
- [ ] יש Roadmap עם שלבים + בדיקות + Rollback
- [ ] נשמרת תאימות לאחור
- [ ] אין ייבואי `database` ישירים ב-routes (יעד סופי)

---

## קבצי עזר

- `src/infrastructure/composition/files_facade.py` – ה-Facade הקיים
- `src/infrastructure/composition/container.py` – Composition Root
- `tests/unit/architecture/test_layer_boundaries.py` – טסטים ארכיטקטוניים
- `docs/ARCHITECTURE_LAYER_RULES.md` – כללי שכבות
- `docs/BOT_TEST_PLAN_CONTAINER.md` – תרחישי בדיקה
