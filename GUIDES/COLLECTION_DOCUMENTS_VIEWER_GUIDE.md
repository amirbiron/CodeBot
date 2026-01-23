# מדריך מימוש צפייה במסמכי Collection

מסמך טכני למימוש תכונה חדשה: **צפייה במסמכים בתוך Collection** בדשבורד Database Health.

---

## 📦 מצב נוכחי

| רכיב | מה קיים | מה חסר |
|:---|:---|:---|
| **Backend** | `db_health_service.py` - סטטיסטיקות collections | Endpoint לשליפת מסמכים |
| **API** | `GET /api/db/collections` - רשימת שמות וגדלים | `GET /api/db/:collection/documents` |
| **Frontend** | טבלת collections עם מספרים | לחיצה על שורה → תצוגת מסמכים |
| **UI** | CodeMirror קיים בפרויקט | חיבור לתצוגת JSON של מסמכים |

---

## 🏗️ תוכנית הבנייה (4 שלבים)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          שלב 1: Backend (API)                           │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  GET /api/db/{collection}/documents?limit=20&skip=0             │   │
│  │  → db.collection(name).find().skip(skip).limit(limit)           │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        שלב 2: Service Layer                             │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  async def get_documents(collection, skip, limit) -> List[dict] │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      שלב 3: Frontend (לוגיקה)                           │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  לחיצה על collection → fetch → שמירה ב-state → הצגה             │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     שלב 4: תצוגה (CodeMirror)                           │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  JSON מעוצב + קיפול שורות + כפתורי דפדוף [הקודם] [הבא]          │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## שלב 1: Backend - הוספת Service Method

### 1.1 הוספה ל-`services/db_health_service.py`

הוסף את המתודה הבאה ל-`AsyncDatabaseHealthService`:

```python
# הוסף בראש הקובץ
from bson import ObjectId
from bson.json_util import dumps as bson_dumps

# מגבלות ברירת מחדל
DEFAULT_DOCUMENTS_LIMIT = 20
MAX_DOCUMENTS_LIMIT = 100


class AsyncDatabaseHealthService:
    # ... קוד קיים ...

    async def get_documents(
        self,
        collection_name: str,
        skip: int = 0,
        limit: int = DEFAULT_DOCUMENTS_LIMIT,
    ) -> Dict[str, Any]:
        """שליפת מסמכים מ-collection עם pagination.

        Args:
            collection_name: שם ה-collection
            skip: כמה מסמכים לדלג (ברירת מחדל: 0)
            limit: כמה מסמכים להחזיר (ברירת מחדל: 20, מקסימום: 100)

        Returns:
            מילון עם:
            - documents: רשימת המסמכים (כ-JSON-serializable dicts)
            - total: סה"כ מסמכים ב-collection
            - skip: ה-skip שהתקבל
            - limit: ה-limit שהתקבל
            - has_more: האם יש עוד מסמכים אחרי

        Raises:
            RuntimeError: אם אין חיבור פעיל למסד
            ValueError: אם ה-collection לא קיים
        """
        if self._db is None:
            raise RuntimeError("No MongoDB database available - call connect() first")

        # וולידציה של ה-collection name (מניעת injection)
        if not collection_name or not isinstance(collection_name, str):
            raise ValueError("Invalid collection name")
        
        # סניטציה: רק אותיות, מספרים וקו תחתון
        if not re.match(r'^[a-zA-Z0-9_]+$', collection_name):
            raise ValueError("Collection name contains invalid characters")

        # הגבלת limit למניעת עומס
        limit = min(max(1, limit), MAX_DOCUMENTS_LIMIT)
        skip = max(0, skip)

        try:
            # בדיקה שה-collection קיים
            existing = await self._db.list_collection_names()
            if collection_name not in existing:
                raise ValueError(f"Collection '{collection_name}' does not exist")

            collection = self._db[collection_name]

            # ספירת סה"כ (לפני סינון)
            total = await collection.count_documents({})

            # שליפת מסמכים עם pagination
            cursor = collection.find({}).skip(skip).limit(limit)
            documents = await cursor.to_list(length=limit)

            # המרת ObjectId ו-datetime לפורמט JSON-safe
            # bson_dumps מטפל ב-ObjectId, datetime, bytes וכו'
            serialized = json.loads(bson_dumps(documents))

            return {
                "documents": serialized,
                "total": total,
                "skip": skip,
                "limit": limit,
                "has_more": (skip + len(documents)) < total,
                "returned_count": len(documents),
            }

        except ValueError:
            raise  # העבר הלאה את שגיאות הוולידציה
        except Exception as e:
            logger.error(f"Failed to get documents from {collection_name}: {e}")
            raise RuntimeError(f"get_documents failed: {e}") from e
```

### 1.2 הוספה ל-`ThreadPoolDatabaseHealthService` (אם משתמשים ב-PyMongo)

```python
class SyncDatabaseHealthService:
    # ... קוד קיים ...

    def get_documents_sync(
        self,
        collection_name: str,
        skip: int = 0,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """גרסה סינכרונית - לא לקרוא ישירות מ-aiohttp!"""
        db = self._db
        if db is None:
            raise RuntimeError("No MongoDB database available")

        # וולידציה
        if not collection_name or not re.match(r'^[a-zA-Z0-9_]+$', collection_name):
            raise ValueError("Invalid collection name")

        limit = min(max(1, limit), 100)
        skip = max(0, skip)

        # בדיקה שה-collection קיים
        existing = db.list_collection_names()
        if collection_name not in existing:
            raise ValueError(f"Collection '{collection_name}' does not exist")

        collection = db[collection_name]
        total = collection.count_documents({})
        documents = list(collection.find({}).skip(skip).limit(limit))

        # סריאליזציה
        from bson.json_util import dumps as bson_dumps
        serialized = json.loads(bson_dumps(documents))

        return {
            "documents": serialized,
            "total": total,
            "skip": skip,
            "limit": limit,
            "has_more": (skip + len(documents)) < total,
            "returned_count": len(documents),
        }


class ThreadPoolDatabaseHealthService:
    # ... קוד קיים ...

    async def get_documents(
        self,
        collection_name: str,
        skip: int = 0,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """שליפת מסמכים - רץ ב-thread pool."""
        return await asyncio.to_thread(
            self._sync_service.get_documents_sync,
            collection_name,
            skip,
            limit,
        )
```

---

## שלב 2: Backend - הוספת API Endpoint

### 2.1 הוספה ל-`services/webserver.py`

```python
# הוסף את ה-handler הזה בתוך create_app():

async def db_collection_documents_view(request: web.Request) -> web.Response:
    """GET /api/db/{collection}/documents - שליפת מסמכים מ-collection.

    Query Parameters:
        skip: מספר מסמכים לדלג (ברירת מחדל: 0)
        limit: מספר מסמכים להחזיר (ברירת מחדל: 20, מקסימום: 100)

    Returns:
        JSON עם:
        - documents: מערך המסמכים
        - total: סה"כ מסמכים ב-collection
        - skip, limit, has_more: מידע pagination

    Errors:
        400: פרמטרים לא תקינים
        404: collection לא קיים
        500: שגיאת שרת
    """
    try:
        collection_name = request.match_info.get("collection", "")

        # פרסור פרמטרים עם ברירות מחדל
        try:
            skip = int(request.query.get("skip", "0"))
            limit = int(request.query.get("limit", "20"))
        except ValueError:
            return web.json_response(
                {"error": "invalid_params", "message": "skip and limit must be integers"},
                status=400,
            )

        # וולידציה בסיסית
        if skip < 0 or limit < 1:
            return web.json_response(
                {"error": "invalid_params", "message": "skip >= 0, limit >= 1"},
                status=400,
            )

        svc = await get_db_health_service()
        result = await svc.get_documents(
            collection_name=collection_name,
            skip=skip,
            limit=limit,
        )

        return web.json_response(result)

    except ValueError as e:
        # Collection לא קיים או שם לא תקין
        return web.json_response(
            {"error": "not_found", "message": str(e)},
            status=404,
        )
    except Exception as e:
        logger.error(f"db_collection_documents error: {e}")
        return web.json_response(
            {"error": "failed", "message": "internal_error"},
            status=500,
        )


# הוסף את ה-route בסוף create_app(), אחרי ה-routes האחרים של /api/db/:
app.router.add_get("/api/db/{collection}/documents", db_collection_documents_view)
```

### 2.2 API Reference

| Endpoint | Method | תיאור |
|:---|:---:|:---|
| `/api/db/{collection}/documents` | GET | שליפת מסמכים מ-collection |

**Query Parameters:**

| פרמטר | סוג | ברירת מחדל | תיאור |
|:---|:---:|:---:|:---|
| `skip` | int | 0 | כמה מסמכים לדלג |
| `limit` | int | 20 | כמה מסמכים להחזיר (מקס: 100) |

**Response Example:**

```json
{
  "documents": [
    {"_id": {"$oid": "507f1f77bcf86cd799439011"}, "name": "Alice", "age": 30},
    {"_id": {"$oid": "507f1f77bcf86cd799439012"}, "name": "Bob", "age": 25}
  ],
  "total": 150,
  "skip": 0,
  "limit": 20,
  "has_more": true,
  "returned_count": 20
}
```

**Error Responses:**

| Status | error | מתי |
|:---:|:---|:---|
| 400 | `invalid_params` | skip/limit לא תקינים |
| 404 | `not_found` | collection לא קיים |
| 500 | `failed` | שגיאת שרת |

---

## שלב 3: Frontend - לוגיקת JavaScript

### 3.1 הוספת State ופונקציות ל-`db_health.html`

הוסף את הקוד הבא ב-`<script>` של התבנית:

```javascript
// ========== State לצפייה במסמכים ==========
let currentCollection = null;
let currentSkip = 0;
const DOCS_LIMIT = 20;

// ========== פונקציות טעינה ==========

/**
 * טעינת מסמכים מ-collection.
 * @param {string} collectionName - שם ה-collection
 * @param {number} skip - כמה מסמכים לדלג (ברירת מחדל: 0)
 */
async function loadDocuments(collectionName, skip = 0) {
    const viewer = document.getElementById('documents-viewer');
    const codeContainer = document.getElementById('documents-code');
    const paginationInfo = document.getElementById('pagination-info');
    const prevBtn = document.getElementById('prev-btn');
    const nextBtn = document.getElementById('next-btn');

    // הצג loading
    viewer.style.display = 'block';
    codeContainer.textContent = 'טוען מסמכים...';
    paginationInfo.textContent = '';
    prevBtn.disabled = true;
    nextBtn.disabled = true;

    try {
        const url = `/api/db/${encodeURIComponent(collectionName)}/documents?skip=${skip}&limit=${DOCS_LIMIT}`;
        const resp = await fetch(url, { headers: authHeaders() });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.message || `HTTP ${resp.status}`);
        }

        const data = await resp.json();

        // עדכון state
        currentCollection = collectionName;
        currentSkip = skip;

        // הצגת JSON מעוצב
        const formatted = JSON.stringify(data.documents, null, 2);
        codeContainer.textContent = formatted;

        // עדכון מידע pagination
        const startDoc = skip + 1;
        const endDoc = skip + data.returned_count;
        paginationInfo.textContent = `מציג ${startDoc}-${endDoc} מתוך ${data.total} מסמכים`;

        // עדכון כפתורים
        prevBtn.disabled = skip === 0;
        nextBtn.disabled = !data.has_more;

        // הדגשת השורה הנבחרת בטבלה
        highlightSelectedCollection(collectionName);

        // אם יש CodeMirror, עדכן אותו
        if (window.documentsEditor) {
            window.documentsEditor.setValue(formatted);
        }

    } catch (e) {
        console.error('loadDocuments error:', e);
        codeContainer.textContent = `שגיאה בטעינת מסמכים: ${e.message}`;
    }
}

/**
 * דפדוף לעמוד הקודם.
 */
function prevPage() {
    if (!currentCollection || currentSkip === 0) return;
    const newSkip = Math.max(0, currentSkip - DOCS_LIMIT);
    loadDocuments(currentCollection, newSkip);
}

/**
 * דפדוף לעמוד הבא.
 */
function nextPage() {
    if (!currentCollection) return;
    loadDocuments(currentCollection, currentSkip + DOCS_LIMIT);
}

/**
 * הדגשת השורה הנבחרת בטבלת ה-collections.
 */
function highlightSelectedCollection(collectionName) {
    // הסר הדגשה קודמת
    document.querySelectorAll('.collections-table tr.selected').forEach(tr => {
        tr.classList.remove('selected');
    });

    // הוסף הדגשה לשורה הנוכחית
    document.querySelectorAll('.collections-table tbody tr').forEach(tr => {
        const nameCell = tr.querySelector('td:first-child');
        if (nameCell && nameCell.textContent === collectionName) {
            tr.classList.add('selected');
        }
    });
}

/**
 * סגירת חלון הצפייה במסמכים.
 */
function closeDocumentsViewer() {
    document.getElementById('documents-viewer').style.display = 'none';
    currentCollection = null;
    currentSkip = 0;

    // הסר הדגשה
    document.querySelectorAll('.collections-table tr.selected').forEach(tr => {
        tr.classList.remove('selected');
    });
}
```

### 3.2 עדכון פונקציית `loadCollections`

עדכן את פונקציית `loadCollections` כדי להוסיף לחיצה על שורות:

```javascript
async function loadCollections() {
    const btn = document.getElementById('load-collections-btn');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> טוען...';

    let rateLimited = false;
    try {
        const resp = await fetch('/api/db/collections', { headers: authHeaders() });
        const data = await resp.json().catch(() => ({}));

        if (resp.status === 429) {
            rateLimited = true;
            const retryAfter = parseInt(data.retry_after_sec || '1', 10) || 1;
            setCollectionsNotice(`נא להמתין ${retryAfter} שניות.`, 'warning');
            startCollectionsCooldown(retryAfter);
            return;
        }
        if (!resp.ok) {
            throw new Error(data.error || 'request_failed');
        }

        const tbody = document.getElementById('collections-tbody');
        tbody.innerHTML = '';

        (data.collections || []).forEach(c => {
            const tr = document.createElement('tr');
            
            // הוספת אירוע לחיצה
            tr.style.cursor = 'pointer';
            tr.addEventListener('click', () => loadDocuments(c.name));
            tr.title = 'לחץ לצפייה במסמכים';

            const cells = [
                c.name,
                c.count.toLocaleString(),
                c.size_mb,
                c.storage_size_mb,
                c.index_count,
                c.total_index_size_mb
            ];

            cells.forEach(value => {
                const td = document.createElement('td');
                td.textContent = value;
                tr.appendChild(td);
            });

            tbody.appendChild(tr);
        });

        document.getElementById('collections-wrapper').style.display = 'block';
        setCollectionsNotice('לחץ על שורה לצפייה במסמכים', 'muted');
        btn.innerHTML = getCollectionsBaseLabel();
    } catch (e) {
        console.error('loadCollections error:', e);
        setCollectionsNotice('שגיאה בטעינת סטטיסטיקות.', 'error');
        btn.innerHTML = '<i class="fas fa-exclamation-triangle"></i> שגיאה';
    } finally {
        if (!rateLimited) {
            btn.disabled = false;
        }
    }
}
```

---

## שלב 4: Frontend - תצוגת UI

### 4.1 הוספת HTML לחלון הצפייה

הוסף את ה-HTML הבא **אחרי** ה-`collections-card`:

```html
<!-- Documents Viewer (נפתח בלחיצה על collection) -->
<div class="glass-card documents-viewer" id="documents-viewer" style="display: none; margin-top: 2rem;">
    <div class="card-header">
        <div class="card-title">
            <span class="card-icon">📄</span>
            <h2>צפייה במסמכים</h2>
        </div>
        <button class="btn btn-secondary btn-icon" onclick="closeDocumentsViewer()">
            <i class="fas fa-times"></i>
            סגור
        </button>
    </div>

    <!-- Pagination Controls -->
    <div class="pagination-controls">
        <button class="btn btn-secondary" id="prev-btn" onclick="prevPage()" disabled>
            <i class="fas fa-chevron-right"></i>
            הקודם
        </button>
        <span class="pagination-info" id="pagination-info">-</span>
        <button class="btn btn-secondary" id="next-btn" onclick="nextPage()" disabled>
            הבא
            <i class="fas fa-chevron-left"></i>
        </button>
    </div>

    <!-- Code Display (CodeMirror או pre) -->
    <div class="documents-code-wrapper">
        <pre class="documents-code" id="documents-code">בחר collection מהטבלה למעלה</pre>
    </div>
</div>
```

### 4.2 הוספת CSS

הוסף את ה-CSS הבא ב-`<style>`:

```css
/* ========== Documents Viewer ========== */
.documents-viewer {
    padding: 1.5rem;
}

.pagination-controls {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 1rem;
    margin-bottom: 1rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.pagination-info {
    font-size: 0.9rem;
    opacity: 0.8;
    min-width: 200px;
    text-align: center;
}

.documents-code-wrapper {
    max-height: 500px;
    overflow: auto;
    border-radius: 8px;
    background: rgba(0, 0, 0, 0.3);
}

.documents-code {
    margin: 0;
    padding: 1rem;
    font-family: 'Fira Code', 'JetBrains Mono', ui-monospace, monospace;
    font-size: 0.85rem;
    line-height: 1.5;
    white-space: pre-wrap;
    word-break: break-word;
    color: #e2e8f0;
    tab-size: 2;
}

/* הדגשת שורה נבחרת בטבלה */
.collections-table tr.selected {
    background: rgba(59, 130, 246, 0.2) !important;
}

.collections-table tr:hover {
    background: rgba(255, 255, 255, 0.05);
}

/* Rose Pine Dawn overrides */
:root[data-theme="rose-pine-dawn"] .documents-code-wrapper {
    background: rgba(242, 233, 225, 0.5);
}

:root[data-theme="rose-pine-dawn"] .documents-code {
    color: #575279;
}

:root[data-theme="rose-pine-dawn"] .collections-table tr.selected {
    background: rgba(215, 130, 126, 0.15) !important;
}

:root[data-theme="rose-pine-dawn"] .pagination-controls {
    border-bottom-color: rgba(87, 82, 121, 0.15);
}
```

---

## שלב 5 (אופציונלי): שילוב CodeMirror

אם רוצים תצוגה יותר מתקדמת עם syntax highlighting ו-code folding:

### 5.1 בדיקה שיש CodeMirror בפרויקט

```bash
ls webapp/static/js/codemirror*
```

### 5.2 הוספת CodeMirror לחלון הצפייה

החלף את ה-`<pre>` ב-textarea:

```html
<div class="documents-code-wrapper">
    <textarea id="documents-code-editor" style="display: none;"></textarea>
</div>
```

### 5.3 אתחול CodeMirror

```javascript
// אתחול CodeMirror בטעינת הדף
document.addEventListener('DOMContentLoaded', () => {
    // ... קוד קיים ...

    // אתחול CodeMirror לתצוגת מסמכים
    if (typeof CodeMirror !== 'undefined') {
        window.documentsEditor = CodeMirror.fromTextArea(
            document.getElementById('documents-code-editor'),
            {
                mode: { name: 'javascript', json: true },
                theme: 'dracula',  // או הנושא שלך
                readOnly: true,
                lineNumbers: true,
                foldGutter: true,
                gutters: ['CodeMirror-linenumbers', 'CodeMirror-foldgutter'],
                lineWrapping: true,
            }
        );
        
        // הסתר את ה-pre הרגיל
        document.getElementById('documents-code').style.display = 'none';
    }
});
```

---

## 🔒 אבטחה

### שיקולים שכבר מיושמים:

1. **Token Authentication** - כל ה-endpoints של `/api/db/*` מוגנים ב-`db_health_auth_middleware`
2. **Input Validation** - שם collection עובר regex validation
3. **Limit Capping** - `limit` מוגבל ל-100 מקסימום
4. **XSS Prevention** - שימוש ב-`textContent` במקום `innerHTML`

### המלצות נוספות:

```python
# הוסף רשימת collections מותרים (whitelist) אם רלוונטי:
ALLOWED_COLLECTIONS_PATTERN = r'^(users|logs|snippets|configs)$'

# בתוך get_documents:
if not re.match(ALLOWED_COLLECTIONS_PATTERN, collection_name):
    raise ValueError("Collection access denied")
```

---

## 🧪 בדיקות יחידה

### 5.1 הוספה ל-`tests/test_db_health_service.py`

```python
@pytest.mark.asyncio
class TestGetDocuments:
    """בדיקות לפונקציית get_documents."""

    @pytest.fixture
    async def service_with_mock_db(self):
        """Service עם DB מוק."""
        svc = AsyncDatabaseHealthService.__new__(AsyncDatabaseHealthService)
        svc._client = AsyncMock()
        svc._db = AsyncMock()
        return svc

    async def test_get_documents_success(self, service_with_mock_db):
        """בדיקת שליפה תקינה."""
        svc = service_with_mock_db
        
        # Mock list_collection_names
        svc._db.list_collection_names = AsyncMock(return_value=['users', 'logs'])
        
        # Mock collection
        mock_collection = AsyncMock()
        mock_collection.count_documents = AsyncMock(return_value=100)
        
        # Mock cursor
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[
            {'_id': ObjectId(), 'name': 'Alice'},
            {'_id': ObjectId(), 'name': 'Bob'},
        ])
        mock_collection.find.return_value.skip.return_value.limit.return_value = mock_cursor
        
        svc._db.__getitem__ = MagicMock(return_value=mock_collection)

        result = await svc.get_documents('users', skip=0, limit=20)

        assert result['total'] == 100
        assert len(result['documents']) == 2
        assert result['has_more'] is True
        assert result['skip'] == 0
        assert result['limit'] == 20

    async def test_get_documents_invalid_collection_name(self, service_with_mock_db):
        """בדיקת שגיאה עם שם collection לא תקין."""
        svc = service_with_mock_db

        with pytest.raises(ValueError, match="invalid characters"):
            await svc.get_documents("users; drop table", skip=0, limit=20)

    async def test_get_documents_collection_not_found(self, service_with_mock_db):
        """בדיקת שגיאה כש-collection לא קיים."""
        svc = service_with_mock_db
        svc._db.list_collection_names = AsyncMock(return_value=['logs'])

        with pytest.raises(ValueError, match="does not exist"):
            await svc.get_documents('users', skip=0, limit=20)

    async def test_get_documents_limit_capping(self, service_with_mock_db):
        """בדיקה שה-limit מוגבל ל-100."""
        svc = service_with_mock_db
        svc._db.list_collection_names = AsyncMock(return_value=['users'])
        
        mock_collection = AsyncMock()
        mock_collection.count_documents = AsyncMock(return_value=500)
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_collection.find.return_value.skip.return_value.limit.return_value = mock_cursor
        svc._db.__getitem__ = MagicMock(return_value=mock_collection)

        result = await svc.get_documents('users', skip=0, limit=500)

        # וודא שה-limit הוגבל ל-100
        assert result['limit'] == 100
```

---

## 📋 רשימת תיוג למימוש

- [ ] **Backend:**
  - [ ] הוסף `get_documents()` ל-`AsyncDatabaseHealthService`
  - [ ] הוסף `get_documents_sync()` ל-`SyncDatabaseHealthService`
  - [ ] הוסף `get_documents()` async wrapper ל-`ThreadPoolDatabaseHealthService`
  - [ ] הוסף import של `re` ו-`bson.json_util` בראש הקובץ

- [ ] **API:**
  - [ ] הוסף `db_collection_documents_view` handler ל-webserver
  - [ ] הוסף route: `app.router.add_get("/api/db/{collection}/documents", ...)`

- [ ] **Frontend:**
  - [ ] הוסף HTML ל-documents viewer
  - [ ] הוסף CSS עיצוב
  - [ ] הוסף JavaScript לטעינה ודפדוף
  - [ ] עדכן `loadCollections()` להוספת לחיצה על שורות

- [ ] **בדיקות:**
  - [ ] הוסף unit tests ל-`get_documents()`
  - [ ] בדוק ידנית בדפדפן

- [ ] **תיעוד:**
  - [ ] עדכן `DATABASE_HEALTH_DASHBOARD_GUIDE.md` עם הפיצ'ר החדש

---

## 🔗 קישורים רלוונטיים

- [DATABASE_HEALTH_DASHBOARD_GUIDE.md](./DATABASE_HEALTH_DASHBOARD_GUIDE.md) - מדריך הדשבורד הקיים
- [services/db_health_service.py](/services/db_health_service.py) - קוד השירות
- [services/webserver.py](/services/webserver.py) - ה-API endpoints
- [webapp/templates/db_health.html](/webapp/templates/db_health.html) - התבנית הקיימת
