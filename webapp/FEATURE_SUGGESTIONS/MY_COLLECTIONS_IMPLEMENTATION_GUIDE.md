# 📚 מדריך מימוש: "האוספים שלי" (My Collections) לווב־אפליקציה

מסמך זה מפרט מימוש מלא של פיצ'ר "האוספים שלי" עבור CodeBot WebApp, מותאם למבנה הקוד הנוכחי ולתבניות הקיימות (Repository, cache_manager, Flask blueprints, Observability, Session auth).

קישור הקשר: ראו Issue GitHub `#1027`.
קישור לתיעוד הפרויקט: `https://amirbiron.github.io/CodeBot/`.

---

## 🔖 סטטוס המסמך
- **Canonical (Source of Truth)**: מסמך זה הוא הגרסה הקאנונית למימוש "האוספים שלי".
- **נספחים חיצוניים**: ישנו גיסט משלים לממשק ו-UX; ראו קישור ב"נספח" בתחתית. הגיסט אינו קאנוני.
- **PRs**: יש לצרף קישור למסמך זה בתיאור ה-PR ולהתיישר מולו.

## 🎯 מטרות וסקופ
- **יצירת אוספים ידניים** של קבצים (snippets): יצירה/שינוי/מחיקה, שם, תיאור, סדר מותאם.
- **אוספים חכמים (שמירת פילטרים)**: מבוססי חוקי חיפוש (query/tags/repo:*/language), מתעדכנים דינמית.
- **ניהול פריטים**: הוספה/הסרה/מיון/הצמדה (pin) של קבצים לאוסף.
- **סקירה וניווט**: עמוד "האוספים שלי" ורשימת פריטים לאוסף, עם דפדוף.
- **אבטחה ותצפיות**: `session['user_id']`, `require_auth`, `traced`, `emit_event`, `internal_alerts`.
- **ביצועים**: קאשינג עם `dynamic_cache` + אינהולידציה עקבית.

הערות מבניות בקוד קיימות שתומכות במימוש:
- DB: קבצים נשמרים ב־`code_snippets` (וגם `large_files`). קיימת לוגיקת "גרסה אחרונה לכל file_name" ב־`database/repository.py` (קיבוץ לפי `file_name`).
- Cache: שימוש ב־`cache_manager.dynamic_cache` וב־`cache.delete_pattern` (ראו `webapp/bookmarks_api.py`).
- Observability: `emit_event`, `internal_alerts`, ו־`@traced` (ראו `webapp/bookmarks_api.py`).
- Auth: דפוס `require_auth` + `session['user_id']`.

---

## 🗄️ מודל נתונים (MongoDB)
המלצה לשני אוספי DB חדשים, עם אינדקסים:

1) `user_collections`
- שדות עיקריים:
  - `_id` (ObjectId)
  - `user_id` (int)
  - `name` (str, עד 80 תווים)
  - `slug` (str, ייחודי למשתמש — נובע מ־name; אותיות/ספרות/מקף)
  - `description` (str, עד 500)
  - `icon` (str) — מתוך רשימת אייקונים מאושרת בלבד (whitelist)
  - `color` (str) — מתוך פלטת צבעים מצומצמת ל-UI עקבי
  - `is_favorite` (bool, אופציונלי) — סידור/הדגשה של אוספים מועדפים
  - `sort_order` (int, אופציונלי) — סדר ידני להצגה בסיידבר
  - `mode` (str: "manual" | "smart" | "mixed")
  - `rules` (dict, כאשר smart/mixed: `{query, programming_language, tags[], repo_tag}`)
  - `items_count` (int, נגזר/מעודכן; ניתן גם `files_count` כשם חלופי)
  - `pinned_count` (int, נגזר/מעודכן)
  - `is_active` (bool, ברירת־מחדל true; למחיקה רכה)
  - `created_at`, `updated_at` (datetime)
  - `share` (dict אופציונלי): `{enabled: bool, token: str, visibility: "private"|"link"}`

- אינדקסים מומלצים:
  - ייחודי: `(user_id, slug)`
  - חיפוש: `(user_id, is_active, updated_at)`

2) `collection_items`
- שדות עיקריים:
  - `_id` (ObjectId)
  - `collection_id` (ObjectId)
  - `user_id` (int) — כפילות מודעת לאכיפת ACL מהיר
  - `source` (str: "regular" | "large") — מקור הפריט (קוד רגיל או large_files)
  - `file_name` (str) — המפתח הקנוני אצלנו (versionless)
  - `note` (str, עד 500, אופציונלי)
  - `pinned` (bool, אופציונלי)
  - `custom_order` (int, אופציונלי) — למיון ידני
  - `added_at`, `updated_at` (datetime)

- אינדקסים מומלצים:
  - ייחודי: `(collection_id, source, file_name)`
  - חיפוש: `(collection_id, custom_order, pinned)`

בחירת מפתח פריט לפי `file_name` תואמת לוגיקת "גרסה אחרונה" ב־Repository. אם משתמש מבצע rename, נדרש עדכון בפריטי האוסף (ראו סעיף אינטגרציות/אינהולידציה בהמשך).

דוגמה סכמתית (Dataclasses, להמחשה בלבד):
```python
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List, Dict

@dataclass
class UserCollection:
    user_id: int
    name: str
    slug: str
    description: str = ""
    icon: str = ""         # אייקון מתוך רשימת ALLOWED_ICONS
    color: str = ""        # צבע מתוך פלטת COLLECTION_COLORS
    is_favorite: bool = False
    sort_order: int = 0
    mode: str = "manual"  # manual|smart|mixed
    rules: Dict = field(default_factory=dict)
    items_count: int = 0
    pinned_count: int = 0
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

@dataclass
class CollectionItem:
    collection_id: str
    user_id: int
    source: str  # regular|large
    file_name: str
    note: str = ""
    pinned: bool = False
    custom_order: Optional[int] = None
    added_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
```

### אייקונים וצבעים (בהשראת הגיסט)
- Whitelist לאייקונים מותריים בלבד, כדי למנוע XSS והזרקות לא צפויות. דוגמה:

```json
{"ALLOWED_ICONS": ["📂","📘","🎨","🧩","🐛","⚙️","📝","🧪","💡","⭐","🔖","🚀"]}
```

- פלטת צבעים קבועה לרקעים/תגיות של אוספים, לשמירה על נראות עקבית:

```json
{"COLLECTION_COLORS": ["blue","green","purple","orange","red","teal","pink","yellow"]}
```

- מפה לאייקוני ברירת־מחדל לפי שם (אופציונלי):

```json
{
  "DEFAULT_COLLECTION_ICONS": {
    "מדריכי קוד": "📘",
    "רעיונות עיצוב": "🎨",
    "פיצ'רים בבנייה": "🧩",
    "ברירת מחדל": "📂"
  }
}
```

---

## 🧩 שכבת DB/Service מוצעת
קובץ חדש: `database/collections_manager.py` (בדומה ל־`database/bookmarks_manager.py`).

ממשק מוצע (שמות/סגנון תואמים לקוד קיים):
- `class CollectionsManager:`
  - `__init__(db)` — קביעת קולקשנים והבטחת אינדקסים.
  - `create_collection(user_id, name, description="", mode="manual", rules=None) -> dict`
  - `update_collection(user_id, collection_id, **fields) -> dict`
  - `delete_collection(user_id, collection_id) -> dict` — מחיקה רכה (`is_active=False`).
  - `list_collections(user_id, limit=100, skip=0) -> dict` — כולל מונים.
  - `get_collection(user_id, collection_id) -> dict`
  - `add_items(user_id, collection_id, items: List[dict]) -> dict` — פריט: `{source, file_name, note?, pinned?}`.
  - `remove_items(user_id, collection_id, items: List[dict]) -> dict`
  - `reorder_items(user_id, collection_id, order: List[dict]) -> dict` — עדכון `custom_order`.
  - `get_collection_items(user_id, collection_id, page=1, per_page=20, include_computed=True) -> dict` — מאחד ידני + תוצאות חוקים חכמים.
  - `compute_smart_items(user_id, rules, limit=200) -> List[dict]` — שימוש ב־`Repository.search_code`, `get_user_file_names_by_repo`, `get_user_files`.

הערות חיבור ל־Repository (קיים ב־`database/repository.py`):
- לשם הצגת פריט, שלפו את הגרסה האחרונה לפי `file_name` ו־`user_id` (כפי שנעשה ב־`get_user_files`, `get_latest_version`).
- עבור חוקי repo (`repo:*`), ניתן להשתמש ב־`get_user_file_names_by_repo`/`get_user_files_by_repo`.
- עבור חיפוש חופשי: `search_code(user_id, query, programming_language, tags)`.

---

## 🔌 API (Flask Blueprint)
קובץ חדש: `webapp/collections_api.py`, בסגנון `webapp/bookmarks_api.py`:
- Blueprint: `collections_bp = Blueprint('collections', __name__, url_prefix='/api/collections')`
- כללית:
  - `@require_auth` בכל endpoint
  - `@traced("collections.<op>")`
  - `emit_event` ו־`emit_internal_alert` על שגיאות/חריגים קריטיים
  - סניטציה לקלט טקסטואלי: `sanitize_input` (בדומה לקיים ב־bookmarks)

Endpoints מוצעים (דוגמאות):

1) יצירה/רשימה/עדכון/מחיקה
- `POST /api/collections`
  - Body: `{"name": "📁 נבחרים", "description": "...", "mode": "manual"|"smart"|"mixed", "rules": {...}}`
  - Returns: `{ok, collection: {...}}`
- `GET /api/collections?limit=50&skip=0` — `@dynamic_cache(key_prefix='collections_list')`
  - Returns: `{ok, collections: [...], count: n}`
- `GET /api/collections/<id>` — `@dynamic_cache(key_prefix='collections_detail')`
  - Returns: `{ok, collection: {...}}`
- `PUT /api/collections/<id>` — עדכון שם/תיאור/חוקים/מוד.
- `DELETE /api/collections/<id>` — מחיקה רכה (`is_active=False`).

2) פריטים
- `GET /api/collections/<id>/items?page=1&per_page=20&include_computed=true` — `@dynamic_cache(key_prefix='collections_items')`
  - Returns: `{ok, items: [...], page, per_page, total_manual, total_computed}`
- `POST /api/collections/<id>/items`
  - Body: `{items: [{"source": "regular", "file_name": "algo.py", "note": ""}]}`
- `DELETE /api/collections/<id>/items`
  - Body: `{items: [{"source": "regular", "file_name": "algo.py"}]}`
- `PUT /api/collections/<id>/reorder`
  - Body: `{order: [{"source": "regular", "file_name": "a.py"}, ...]}` — יעדכן `custom_order` סידרתי.

3) ייצוא/שיתוף (Phase 2, אופציונלי)
- `GET /api/collections/<id>/export` — JSON/Markdown.
- `POST /api/collections/<id>/share` — `{enabled: bool}` (link-token).

דגשי ולידציה ו־HTTP 4xx:
- `name` 1..80, `description` ≤ 500, `slug` ייחודי (נגזר ומנורמל).
- מניעת כפילויות פריטים לפי `(collection_id, source, file_name)`.
- `per_page` תוחם (1..200), `page` ≥ 1.

Observability (דוגמאות):
- אירועים: `collections_create`, `collections_update`, `collections_delete_soft`, `collections_items_add`, `collections_items_remove`, `collections_reorder`, `collections_get_list`, `collections_get_items`.

Feature flag ורול־אאוט:
- עטפו את תצוגת ה-UI וה-Blueprint בדגל קונפיג (למשל `config.FEATURE_MY_COLLECTIONS`), והפעילו בהדרגה. ספקו fallback מלא כאשר הדגל כבוי.

---

## 🧠 Smart Collections — חוקים
- מבנה `rules` לדוגמה:
```json
{
  "query": "http client",
  "programming_language": "python",
  "tags": ["retry", "timeout"],
  "repo_tag": "repo:my-app"
}
```
- הפקה דינמית של פריטים:
  - `search_code` (query, language, tags)
  - `get_user_file_names_by_repo` / `get_user_files_by_repo` (לפי `repo_tag`)
- שילוב עם ידני (mode="mixed"): מאחדים ידני + חישוב דינמי; דה־דופליקציה לפי `(source, file_name)`; מיון: `pinned` > `custom_order` > `updated_at`.

---

## 🧠 קאשינג ואינהולידציה
שימוש ב־`dynamic_cache` והסרת מפתחות עם `cache.delete_pattern` (דומה ל־Bookmarks):
- מפתחות מוצעים:
  - `collections_list:{user_id}:*`
  - `collections_detail:{user_id}:-api-collections-<id>*`
  - `collections_items:{user_id}:-api-collections-<id>*`

אינהולידציה על:
- יצירה/עדכון/מחיקה של אוסף
- הוספה/הסרה/סידור פריטים
- שינויי קבצים שעשויים להשפיע על אוספים חכמים (שמירה, rename, מחיקה/שחזור):
  - בנקודות `Repository.save_code_snippet`, `rename_file`, `delete_file`, `restore_file_by_id` — מומלץ לקרוא `cache.invalidate_user_cache(user_id)` + מחיקה ספציפית של patterns `collections_*` למשתמש.

הערה: גם ללא אינטגרציה הדוקה, פריטי smart יחושבו מחדש על כל cache miss/פג תוקף.

TTL מומלץ (ניתן להתאמה):
- `collections_list` — 30-60 שניות
- `collections_detail` — 30 שניות
- `collections_items` — 20-30 שניות (מאחר שעלול להשתנות תדיר)

---

## 🎨 UI/Frontend
קבצים רלוונטיים קיימים: `webapp/templates/*`, `webapp/static/js/*`, `webapp/static/css/*`.

הצעות מסך/רכיבים:
1) ניווט
- הוספת קישור "האוספים שלי" לניווט העליון (`base.html`).
- יעד: `/collections` (דף חדש server-rendered).

2) דף "האוספים שלי" (`templates/collections.html`)
- צד שמאל: כפתור "צור אוסף", רשימת אוספים (שם, מונים, תאריך עדכון), חיפוש מקומי.
- תוכן: רשימת פריטים לאוסף נבחר עם פעולות: הסרה, הצמדה, סידור Drag&Drop (אופציונלי), דפדוף.
- Toolbar: "הוסף פריטים" (פותח מודל עם חיפוש לפי file_name/tags/repo_tag), "עריכת חוקים" (כשsmart/mixed).

3) שילוב בתוך רשימת קבצים וקובץ בודד
- ב־`files.html`: כפתור פעולה "הוסף לאוסף" לכל קובץ; תמיכה ב־bulk add (להשתמש בתבניות `bulk-actions.js`).
- ב־`view_file.html`: כפתור "הוסף לאוסף" לצד פעולות קובץ.

4) סטטיק
- `static/js/collections.js`: קריאות `fetch` ל־API (דומה ל־`bookmarks.js`).
- `static/css/collections.css`: סגנון לרשימות/מודלים.

נגישות (a11y): רכיבי כפתור/מודל מקלדתיים, contrast, aria-labels. ניתן להיעזר ב־`FEATURE_SUGGESTIONS/ACCESSIBLE_MARKDOWN_DISPLAY_GUIDE.md`.

---

## 🧭 הוראות הטמעה (תכל'ס)
1) Backend
- צור `database/collections_manager.py` והגדר אינדקסים עבור `user_collections` ו-`collection_items`.
- צור `webapp/collections_api.py` עם Blueprint, `@require_auth`, `@traced`, `emit_event`.
- רשום את ה-Blueprint ב-`webapp/app.py` (בלי לשבור קוד קיים, מאחורי feature flag אם צריך).

2) Frontend
- הוסף קבצים: `webapp/static/css/collections.css`, `webapp/static/js/collections.js`.
- עדכן `templates/base.html` בקישור ל"האוספים שלי"; הוסף מסך `templates/collections.html` לרשימות וניהול.
- בכותרת קובץ (`view_file.html`), הוסף כפתור "הוסף לאוסף" + מודל בחירה.

3) בדיקות
- בדיקות יחידה ל-Manager ול-API (happy + 4xx), אימות קאשינג ואינהולידציה.
- בדיקות smoke ל-UI דרך endpoints קיימים.

4) תצפיות ורול־אאוט
- הוסיפו אירועים לפי הסעיף לעיל; הפעילו בהדרגה עם feature flag.

---

## 🗃️ סכמת מסד נתונים (JSON דוגמתי)

`user_collections`
```json
{
  "_id": "ObjectId",
  "user_id": 123,
  "name": "📁 נבחרים",
  "slug": "favorites",
  "description": "קבצים חשובים",
  "icon": "📂",
  "color": "blue",
  "is_favorite": false,
  "sort_order": 0,
  "mode": "manual",
  "rules": {},
  "items_count": 12,
  "pinned_count": 2,
  "is_active": true,
  "created_at": "2025-10-23T05:00:00Z",
  "updated_at": "2025-10-23T05:00:00Z",
  "share": {"enabled": false, "token": null, "visibility": "private"}
}
```

`collection_items` (המקביל לשם `collection_files` בגיסט)
```json
{
  "_id": "ObjectId",
  "collection_id": "ObjectId",
  "user_id": 123,
  "source": "regular",
  "file_name": "algo.py",
  "note": "דוגמה",
  "pinned": false,
  "custom_order": 10,
  "added_at": "2025-10-23T05:00:00Z",
  "updated_at": "2025-10-23T05:00:00Z"
}
```

---

## 🔐 אבטחה וולידציה
- Auth: `require_auth` בכל endpoint.
- סניטציה: להשתמש ב־`sanitize_input` (escape + חיתוך אורכים) ל־`name`/`description`/`note`.
- מגבלות:
  - עד 100 אוספים למשתמש (קונפיגורבילי).
  - עד 5,000 פריטים ידניים בכלל האוספים למשתמש (קונפיגורבילי).
- מחיקה רכה בלבד (`is_active=False`).

שיפורי אבטחה (מהגיסט):
- השתמשו ב-`cache.invalidate_user_cache()` (אל תסמכו על פונקציות לא קיימות).
- ולידציית אייקונים מול `ALLOWED_ICONS` בלבד; בצד לקוח בצעו escape לכל טקסט שמוזרק ל-DOM.
- מניעת IDOR: סננו תמיד לפי `user_id` גם ב-`user_collections` וגם ב-`collection_items` בכל פעולה.

---

## 🧪 בדיקות (pytest)
כיסויים מומלצים:
- DB/Manager (`database/collections_manager.py`):
  - יצירה/עדכון/מחיקה של אוסף; אינדקסים ייחודיים (slug)
  - הוספה/הסרה/סידור פריטים; מניעת כפילות
  - הפקת smart items מול Repository stubs
- API (`webapp/collections_api.py`):
  - happy paths + 4xx שגיאות ולידציה
  - include_computed בדיקה
  - קאשינג: אימות שמפתחות מתבטלים אחרי פעולות כתיבה (בדומה ל־bookmarks)
- UI (אופציונלי): smoke דרך endpoints קיימים בדפי server-rendered

הנחיות כלליות לטסטים (בהתאם למדיניות העבודה):
- עבודה בתיקיות tmp בלבד לפעולות קבצים (אם יש). אין מחיקות מסוכנות.
- ללא `sudo`, ללא פקודות אינטראקטיביות.

---

## 🔀 אינטגרציות והשפעות הדדיות
- Rename קובץ (`Repository.rename_file`): לבצע עדכון `collection_items.file_name` בהתאם (רצוי טרנזקציונית ככל האפשר). אם לא חיבור ישיר — ניתן לבצע תיקון לוגי ב־CollectionsManager דרך קריאת rename adapter.
- מחיקה/שחזור קובץ: פריטים יישארו, אך בתצוגה יש לסמן פריט "לא פעיל" אם לא קיים קובץ פעיל תואם (fallback לתצוגה אפורה/disabled).
- מועדפים: אין תלות ישירה. ניתן להוסיף מסנן "הוסף את כל המועדפים" כאופציה בחוקי smart.

---

## 🧾 OpenAPI (טיוטה)
הוספה ל־`docs/openapi.yaml` (מבנה סכמטי):
```yaml
paths:
  /api/collections:
    get: { summary: List user collections }
    post: { summary: Create collection }
  /api/collections/{id}:
    get: { summary: Get collection }
    put: { summary: Update collection }
    delete: { summary: Soft delete collection }
  /api/collections/{id}/items:
    get: { summary: List items (manual+smart) }
    post: { summary: Add items }
    delete: { summary: Remove items }
  /api/collections/{id}/reorder:
    put: { summary: Reorder items }
```

---

## 🚀 תוכנית שלבים (MVP → Advanced)
1) MVP — ידני בלבד:
- DB + אינדקסים, CollectionsManager בסיסי
- API: create/list/get/update/delete, items add/remove/reorder/list
- UI: דף "האוספים שלי", הוספה מתוך רשימת קבצים
- Cache + Observability בסיסי

2) Smart Collections:
- הוספת `rules` + הפקה דינמית
- UI לעריכת חוקים ושיתוף

3) שיתוף/ייצוא, Pinning, Bulk add נוח, Drag&Drop, A11y polish

---

## ✅ צ'קליסט "מוכן לשילוב"
- DB: אינדקסים הוקמו, בדיקות יחידה ירוקות
- API: מוגן, מתועדת ב־OpenAPI, אירועים נרשמים
- Cache: מפתחות מוגדרים, אינהולידציה אחרי כתיבה
- UI: ניווט, יצירה/ניהול אוסף, הוספת פריטים
- טסטים: כיסוי בסיסי לשכבות DB+API
- Docs: עדכון `docs/` ועמוד זה מצורף ל־PR, קישור ל־project docs

---

## 📎 דוגמאות שימוש (cURL, סכמטי)
- יצירת אוסף ידני:
```bash
curl -X POST /api/collections \
  -H 'Content-Type: application/json' \
  -d '{"name":"📁 נבחרים","mode":"manual"}'
```
- הוספת פריט:
```bash
curl -X POST /api/collections/<id>/items \
  -H 'Content-Type: application/json' \
  -d '{"items":[{"source":"regular","file_name":"algo.py"}]}'
```
- קבלת פריטים (כולל smart):
```bash
curl '/api/collections/<id>/items?page=1&per_page=20&include_computed=true'
```

---

## 📝 הערות יישום קצרות
- שמרו על אחידות לוגים ו־tracing כמו ב־`webapp/bookmarks_api.py`.
- בצד ה־UI, עדיפות ל־fetch JSON ופשטות (כמו `bookmarks.js`).
- שמות וקוד באנגלית, טקסטים למשתמש בעברית.
- בעתיד: ניתן להרחיב לסוגי פריטים נוספים (למשל Saved searches עצמאיים).

## 🗒️ Changelog
- 2025-10-23: מיזוג תוספות מהגיסט והפיכת המסמך לקאנוני: whitelist לאייקונים, פלטת צבעים, Feature flag ורול־אאוט, TTL לקאש, הוראות הטמעה תכל'ס, סכמות DB מעודכנות.

## 📎 נספח: גיסט רפרנס
- מדריך UX/דוגמאות מורחבות: [Gist – Madrich.md](https://gist.github.com/amirbiron/ae7c92d9a68408af01e8c1b749d6370e)

בהצלחה! 🚀