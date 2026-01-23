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
│  │  → db[name].find().sort(_id).skip(skip).limit(limit)            │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        שלב 2: Service Layer                             │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  async def get_documents(collection, skip, limit) -> Dict       │   │
│  │  + sort(_id) + redaction + whitelist                            │   │
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
│  │  JSON מעוצב + קיפול + Copy + כפתורי דפדוף [הקודם] [הבא]         │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## ⚠️ מגבלות ושיקולי עיצוב

### Pagination עם `skip` (MVP)

המימוש הנוכחי משתמש ב-`skip/limit` שהוא פשוט אבל **לא סקיילבילי** לאוספים גדולים מאוד.  
MongoDB צריך לדלג על N מסמכים בכל בקשה, מה שנהיה איטי בעמודים עמוקים.

**למה זה בסדר לעכשיו:**
- זהו כלי admin פנימי עם שימוש מוגבל
- רוב ה-collections קטנים יחסית
- המשתמשים לרוב צופים בעמודים הראשונים

**שדרוג עתידי (Cursor-based Pagination):**
```python
# במקום skip, שמור את ה-_id האחרון:
# GET /api/db/users/documents?after=507f1f77bcf86cd799439011&limit=20
cursor = collection.find({"_id": {"$gt": ObjectId(after_id)}}).sort("_id", 1).limit(limit)
```

---

## שלב 1: Backend - הוספת Service Method

### 1.1 Imports נדרשים

הוסף בראש `services/db_health_service.py`:

```python
# ========== Imports חדשים (הוסף בראש הקובץ) ==========
import json
import re
from typing import Any, Dict, List, Optional, Set

from bson import ObjectId
from bson.json_util import dumps as bson_dumps

# מגבלות Pagination
DEFAULT_DOCUMENTS_LIMIT = 20
MAX_DOCUMENTS_LIMIT = 100

# ========== הגדרות אבטחה ==========

# רשימת collections מותרים לצפייה (None = הכל מותר)
# שנה לפי הצורך שלך!
ALLOWED_COLLECTIONS: Optional[Set[str]] = None
# דוגמה להגבלה: ALLOWED_COLLECTIONS = {"users", "logs", "snippets", "configs"}

# רשימת collections חסומים (אם ALLOWED_COLLECTIONS הוא None)
DENIED_COLLECTIONS: Set[str] = {
    "sessions",
    "tokens",
    "api_keys",
    "secrets",
}

# שדות רגישים שיוסתרו מהתצוגה (redaction)
SENSITIVE_FIELDS: Set[str] = {
    "password",
    "password_hash",
    "hashed_password",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "apiKey",
    "secret",
    "secret_key",
    "private_key",
    "credentials",
}
```

### 1.2 Custom Exceptions

הוסף מחלקות שגיאה ייעודיות להבחנה בין סוגי שגיאות:

```python
# ========== Custom Exceptions ==========

class CollectionAccessDeniedError(Exception):
    """נזרקת כשגישה ל-collection חסומה."""
    pass


class CollectionNotFoundError(Exception):
    """נזרקת כש-collection לא קיים."""
    pass


class InvalidCollectionNameError(Exception):
    """נזרקת כששם collection לא תקין."""
    pass
```

### 1.3 פונקציית Redaction

```python
def _redact_sensitive_fields(doc: Dict[str, Any], sensitive: Set[str] = SENSITIVE_FIELDS) -> Dict[str, Any]:
    """הסתרת שדות רגישים ממסמך (רקורסיבי).
    
    Args:
        doc: המסמך המקורי
        sensitive: קבוצת שמות שדות להסתרה
        
    Returns:
        עותק של המסמך עם שדות רגישים מוחלפים ב-"[REDACTED]"
    """
    if not isinstance(doc, dict):
        return doc
    
    result = {}
    for key, value in doc.items():
        if key.lower() in {s.lower() for s in sensitive}:
            result[key] = "[REDACTED]"
        elif isinstance(value, dict):
            result[key] = _redact_sensitive_fields(value, sensitive)
        elif isinstance(value, list):
            result[key] = [
                _redact_sensitive_fields(item, sensitive) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = value
    return result
```

### 1.4 פונקציית Validation

```python
def _validate_collection_name(name: str) -> None:
    """וולידציה של שם collection.
    
    MongoDB naming rules:
    - לא יכול להתחיל ב-$ או להכיל \0
    - לא יכול להיות ריק
    - מומלץ להימנע מ-.. או תווים מיוחדים
    
    Raises:
        InvalidCollectionNameError: אם השם לא תקין
        CollectionAccessDeniedError: אם הגישה חסומה
    """
    if not name or not isinstance(name, str):
        raise InvalidCollectionNameError("Collection name cannot be empty")
    
    # תווים אסורים ב-MongoDB
    if name.startswith("$"):
        raise InvalidCollectionNameError("Collection name cannot start with $")
    if "\0" in name or ".." in name:
        raise InvalidCollectionNameError("Collection name contains invalid characters")
    
    # הגבלת אורך סבירה
    if len(name) > 120:
        raise InvalidCollectionNameError("Collection name too long")
    
    # בדיקת whitelist/denylist
    if ALLOWED_COLLECTIONS is not None:
        if name not in ALLOWED_COLLECTIONS:
            raise CollectionAccessDeniedError(f"Access to collection '{name}' is not allowed")
    elif name in DENIED_COLLECTIONS:
        raise CollectionAccessDeniedError(f"Access to collection '{name}' is denied")
```

### 1.5 הוספת המתודה ל-`AsyncDatabaseHealthService`

```python
class AsyncDatabaseHealthService:
    # ... קוד קיים ...

    async def get_documents(
        self,
        collection_name: str,
        skip: int = 0,
        limit: int = DEFAULT_DOCUMENTS_LIMIT,
        redact_sensitive: bool = True,
    ) -> Dict[str, Any]:
        """שליפת מסמכים מ-collection עם pagination.

        Args:
            collection_name: שם ה-collection
            skip: כמה מסמכים לדלג (ברירת מחדל: 0)
            limit: כמה מסמכים להחזיר (ברירת מחדל: 20, מקסימום: 100)
            redact_sensitive: האם להסתיר שדות רגישים (ברירת מחדל: True)

        Returns:
            מילון עם:
            - collection: שם ה-collection
            - documents: רשימת המסמכים (כ-JSON-serializable dicts)
            - total: סה"כ מסמכים ב-collection
            - skip: ה-skip שהתקבל
            - limit: ה-limit שהתקבל
            - has_more: האם יש עוד מסמכים אחרי
            - returned_count: כמה מסמכים הוחזרו בפועל

        Raises:
            RuntimeError: אם אין חיבור פעיל למסד
            InvalidCollectionNameError: אם שם ה-collection לא תקין
            CollectionAccessDeniedError: אם הגישה ל-collection חסומה
            CollectionNotFoundError: אם ה-collection לא קיים
        """
        if self._db is None:
            raise RuntimeError("No MongoDB database available - call connect() first")

        # וולידציה של שם ה-collection (כולל whitelist/denylist)
        _validate_collection_name(collection_name)

        # הגבלת limit למניעת עומס
        limit = min(max(1, limit), MAX_DOCUMENTS_LIMIT)
        skip = max(0, skip)

        try:
            collection = self._db[collection_name]

            # ספירת סה"כ מסמכים
            # הערה: count_documents({}) יחזיר 0 אם ה-collection לא קיים (זה בסדר)
            total = await collection.count_documents({})

            # שליפת מסמכים עם pagination + SORT לדטרמיניזם!
            # ⚠️ חשוב: sort(_id) מבטיח סדר עקבי בין עמודים
            cursor = collection.find({}).sort("_id", 1).skip(skip).limit(limit)
            documents = await cursor.to_list(length=limit)

            # המרת ObjectId ו-datetime לפורמט JSON-safe
            serialized = json.loads(bson_dumps(documents))

            # הסתרת שדות רגישים
            if redact_sensitive:
                serialized = [_redact_sensitive_fields(doc) for doc in serialized]

            # ⚠️ חישוב has_more: בודקים אם קיבלנו עמוד מלא
            # זה יותר אמין מ-(skip + len) < total כי count יכול להשתנות
            # בין הקריאה ל-count_documents לבין ה-find
            has_more = len(documents) == limit

            return {
                "collection": collection_name,
                "documents": serialized,
                "total": total,
                "skip": skip,
                "limit": limit,
                "has_more": has_more,
                "returned_count": len(documents),
            }

        except (InvalidCollectionNameError, CollectionAccessDeniedError, CollectionNotFoundError):
            raise  # העבר הלאה שגיאות ספציפיות
        except Exception as e:
            logger.error(f"Failed to get documents from {collection_name}: {e}")
            raise RuntimeError(f"get_documents failed: {e}") from e
```

### 1.6 הוספה ל-`ThreadPoolDatabaseHealthService`

```python
class SyncDatabaseHealthService:
    # ... קוד קיים ...

    def get_documents_sync(
        self,
        collection_name: str,
        skip: int = 0,
        limit: int = DEFAULT_DOCUMENTS_LIMIT,
        redact_sensitive: bool = True,
    ) -> Dict[str, Any]:
        """גרסה סינכרונית - לא לקרוא ישירות מ-aiohttp!"""
        db = self._db
        if db is None:
            raise RuntimeError("No MongoDB database available")

        # וולידציה
        _validate_collection_name(collection_name)

        limit = min(max(1, limit), MAX_DOCUMENTS_LIMIT)
        skip = max(0, skip)

        collection = db[collection_name]
        total = collection.count_documents({})
        
        # ⚠️ חשוב: sort(_id) לדטרמיניזם!
        documents = list(collection.find({}).sort("_id", 1).skip(skip).limit(limit))

        # סריאליזציה
        serialized = json.loads(bson_dumps(documents))

        # הסתרת שדות רגישים
        if redact_sensitive:
            serialized = [_redact_sensitive_fields(doc) for doc in serialized]

        # ⚠️ חישוב has_more: בודקים אם קיבלנו עמוד מלא
        has_more = len(documents) == limit

        return {
            "collection": collection_name,
            "documents": serialized,
            "total": total,
            "skip": skip,
            "limit": limit,
            "has_more": has_more,
            "returned_count": len(documents),
        }


class ThreadPoolDatabaseHealthService:
    # ... קוד קיים ...

    async def get_documents(
        self,
        collection_name: str,
        skip: int = 0,
        limit: int = DEFAULT_DOCUMENTS_LIMIT,
        redact_sensitive: bool = True,
    ) -> Dict[str, Any]:
        """שליפת מסמכים - רץ ב-thread pool."""
        return await asyncio.to_thread(
            self._sync_service.get_documents_sync,
            collection_name,
            skip,
            limit,
            redact_sensitive,
        )
```

---

## שלב 2: Backend - הוספת API Endpoint

### 2.1 הוספה ל-`services/webserver.py`

```python
# הוסף import בראש הקובץ:
from services.db_health_service import (
    get_db_health_service,
    InvalidCollectionNameError,
    CollectionAccessDeniedError,
    CollectionNotFoundError,
)


# הוסף את ה-handler הזה בתוך create_app():

async def db_collection_documents_view(request: web.Request) -> web.Response:
    """GET /api/db/{collection}/documents - שליפת מסמכים מ-collection.

    Query Parameters:
        skip: מספר מסמכים לדלג (ברירת מחדל: 0)
        limit: מספר מסמכים להחזיר (ברירת מחדל: 20, מקסימום: 100)

    Returns:
        JSON עם documents, total, skip, limit, has_more

    Status Codes:
        200: הצלחה
        400: פרמטרים לא תקינים / שם collection לא תקין
        403: גישה ל-collection חסומה
        404: collection לא קיים (או ריק - מחזיר total=0)
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

    except InvalidCollectionNameError as e:
        # שם collection לא תקין → 400 Bad Request
        return web.json_response(
            {"error": "invalid_collection_name", "message": str(e)},
            status=400,
        )
    except CollectionAccessDeniedError as e:
        # גישה חסומה → 403 Forbidden
        return web.json_response(
            {"error": "access_denied", "message": str(e)},
            status=403,
        )
    except CollectionNotFoundError as e:
        # Collection לא קיים → 404 Not Found
        return web.json_response(
            {"error": "not_found", "message": str(e)},
            status=404,
        )
    except Exception as e:
        logger.error(f"db_collection_documents error: {e}")
        return web.json_response(
            {"error": "internal_error", "message": "An unexpected error occurred"},
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

**Response Example (200 OK):**

```json
{
  "collection": "users",
  "documents": [
    {"_id": {"$oid": "507f1f77bcf86cd799439011"}, "name": "Alice", "password": "[REDACTED]"},
    {"_id": {"$oid": "507f1f77bcf86cd799439012"}, "name": "Bob", "password": "[REDACTED]"}
  ],
  "total": 150,
  "skip": 0,
  "limit": 20,
  "has_more": true,
  "returned_count": 20
}
```

**Empty Collection (200 OK):**

```json
{
  "collection": "empty_collection",
  "documents": [],
  "total": 0,
  "skip": 0,
  "limit": 20,
  "has_more": false,
  "returned_count": 0
}
```

**Error Responses:**

| Status | error | מתי |
|:---:|:---|:---|
| 400 | `invalid_params` | skip/limit לא תקינים |
| 400 | `invalid_collection_name` | שם collection מכיל תווים אסורים |
| 403 | `access_denied` | collection ב-denylist או לא ב-whitelist |
| 404 | `not_found` | collection לא קיים (אופציונלי - ראה הערה) |
| 500 | `internal_error` | שגיאת שרת |

> **הערה:** ב-MongoDB, `find()` על collection שלא קיים מחזיר 0 תוצאות.  
> המימוש הנוכחי מחזיר 200 עם `total=0` במקום 404, מה שמפשט את הלוגיקה.

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
    const viewerTitle = document.getElementById('viewer-collection-name');
    const codeContainer = document.getElementById('documents-code');
    const paginationInfo = document.getElementById('pagination-info');
    const prevBtn = document.getElementById('prev-btn');
    const nextBtn = document.getElementById('next-btn');
    const copyBtn = document.getElementById('copy-json-btn');
    const emptyState = document.getElementById('documents-empty-state');

    // הצג loading
    viewer.style.display = 'block';
    viewerTitle.textContent = collectionName;
    codeContainer.textContent = 'טוען מסמכים...';
    codeContainer.style.display = 'block';
    emptyState.style.display = 'none';
    paginationInfo.textContent = '';
    prevBtn.disabled = true;
    nextBtn.disabled = true;
    copyBtn.disabled = true;

    try {
        const url = `/api/db/${encodeURIComponent(collectionName)}/documents?skip=${skip}&limit=${DOCS_LIMIT}`;
        const resp = await fetch(url, { headers: authHeaders() });
        
        // פרסור JSON עם טיפול בשגיאות
        let data;
        try {
            data = await resp.json();
        } catch (parseError) {
            throw new Error('תשובה לא תקינה מהשרת');
        }

        if (!resp.ok) {
            // הצגת שגיאה מתאימה לפי סטטוס
            let errorMsg = data?.message || `שגיאה ${resp.status}`;
            if (resp.status === 403) {
                errorMsg = `גישה ל-${collectionName} חסומה`;
            } else if (resp.status === 400) {
                errorMsg = `שם collection לא תקין: ${collectionName}`;
            }
            throw new Error(errorMsg);
        }

        // וולידציה של מבנה התשובה
        if (typeof data?.total !== 'number' || !Array.isArray(data?.documents)) {
            throw new Error('מבנה תשובה לא תקין מהשרת');
        }

        // עדכון state
        currentCollection = collectionName;
        currentSkip = skip;

        const total = data.total;
        const returnedCount = data.returned_count ?? data.documents.length;

        // בדיקת empty state
        if (total === 0 || returnedCount === 0) {
            codeContainer.style.display = 'none';
            emptyState.style.display = 'block';
            emptyState.textContent = `אין מסמכים ב-${collectionName}`;
            paginationInfo.textContent = '0 מסמכים';
            copyBtn.disabled = true;
        } else {
            // הצגת JSON מעוצב
            const formatted = JSON.stringify(data.documents, null, 2);
            codeContainer.textContent = formatted;
            codeContainer.style.display = 'block';
            emptyState.style.display = 'none';

            // עדכון מידע pagination
            const startDoc = skip + 1;
            const endDoc = skip + returnedCount;
            paginationInfo.textContent = `מציג ${startDoc}-${endDoc} מתוך ${total.toLocaleString()} מסמכים`;

            // עדכון כפתורים - has_more מבוסס על האם קיבלנו עמוד מלא
            prevBtn.disabled = skip === 0;
            nextBtn.disabled = returnedCount < DOCS_LIMIT;
            copyBtn.disabled = false;

            // אם יש CodeMirror, עדכן אותו
            if (window.documentsEditor) {
                window.documentsEditor.setValue(formatted);
            }
        }

        // הדגשת השורה הנבחרת בטבלה
        highlightSelectedCollection(collectionName);

    } catch (e) {
        console.error('loadDocuments error:', e);
        codeContainer.textContent = `שגיאה: ${e.message}`;
        codeContainer.style.display = 'block';
        emptyState.style.display = 'none';
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
 * העתקת ה-JSON ל-clipboard.
 */
async function copyJsonToClipboard() {
    const codeContainer = document.getElementById('documents-code');
    const copyBtn = document.getElementById('copy-json-btn');
    
    try {
        const text = window.documentsEditor 
            ? window.documentsEditor.getValue() 
            : codeContainer.textContent;
        
        await navigator.clipboard.writeText(text);
        
        // פידבק ויזואלי
        const originalText = copyBtn.innerHTML;
        copyBtn.innerHTML = '<i class="fas fa-check"></i> הועתק!';
        copyBtn.classList.add('btn-success');
        
        setTimeout(() => {
            copyBtn.innerHTML = originalText;
            copyBtn.classList.remove('btn-success');
        }, 2000);
    } catch (e) {
        console.error('Copy failed:', e);
        alert('ההעתקה נכשלה');
    }
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
        setCollectionsNotice('💡 לחץ על שורה לצפייה במסמכים', 'muted');
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
            <h2>צפייה במסמכים — <code id="viewer-collection-name">-</code></h2>
        </div>
        <div class="card-actions">
            <button class="btn btn-secondary btn-icon" id="copy-json-btn" onclick="copyJsonToClipboard()" disabled>
                <i class="fas fa-copy"></i>
                העתק JSON
            </button>
            <button class="btn btn-secondary btn-icon" onclick="closeDocumentsViewer()">
                <i class="fas fa-times"></i>
                סגור
            </button>
        </div>
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

    <!-- Code Display -->
    <div class="documents-code-wrapper">
        <!-- Empty State -->
        <div class="documents-empty-state" id="documents-empty-state" style="display: none;">
            אין מסמכים להצגה
        </div>
        
        <!-- Fallback: pre element (ללא CodeMirror) -->
        <pre class="documents-code" id="documents-code">בחר collection מהטבלה למעלה</pre>
        
        <!-- CodeMirror container (אם זמין) -->
        <textarea id="documents-code-editor" style="display: none;"></textarea>
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

.card-actions {
    display: flex;
    gap: 0.5rem;
}

.card-header code {
    font-family: 'Fira Code', ui-monospace, monospace;
    background: rgba(0, 0, 0, 0.2);
    padding: 0.2rem 0.5rem;
    border-radius: 4px;
    font-size: 0.9em;
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
    min-width: 220px;
    text-align: center;
    font-variant-numeric: tabular-nums;
}

.documents-code-wrapper {
    max-height: 500px;
    overflow: auto;
    border-radius: 8px;
    background: rgba(0, 0, 0, 0.3);
    position: relative;
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

.documents-empty-state {
    text-align: center;
    padding: 3rem;
    opacity: 0.6;
    font-size: 1.1rem;
}

/* כפתור Copy - מצב הצלחה */
.btn-success {
    background: rgba(34, 197, 94, 0.3) !important;
    border-color: #22c55e !important;
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

:root[data-theme="rose-pine-dawn"] .card-header code {
    background: rgba(87, 82, 121, 0.1);
}

:root[data-theme="rose-pine-dawn"] .collections-table tr.selected {
    background: rgba(215, 130, 126, 0.15) !important;
}

:root[data-theme="rose-pine-dawn"] .pagination-controls {
    border-bottom-color: rgba(87, 82, 121, 0.15);
}

/* CodeMirror container styling */
.documents-code-wrapper .CodeMirror {
    height: 100%;
    max-height: 500px;
    font-family: 'Fira Code', ui-monospace, monospace;
    font-size: 0.85rem;
}

@media (max-width: 768px) {
    .card-actions {
        flex-direction: column;
        gap: 0.25rem;
    }
    
    .pagination-controls {
        flex-wrap: wrap;
    }
}
```

---

## שלב 5 (אופציונלי): שילוב CodeMirror

### 5.1 בדיקה שיש CodeMirror בפרויקט

```bash
ls webapp/static/js/codemirror*
```

### 5.2 אתחול CodeMirror עם תמיכה ב-theme דינמי

הוסף בתוך `DOMContentLoaded`:

```javascript
// אתחול CodeMirror בטעינת הדף
document.addEventListener('DOMContentLoaded', () => {
    // ... קוד קיים ...

    // אתחול CodeMirror לתצוגת מסמכים (אם זמין)
    initDocumentsEditor();
});

/**
 * אתחול CodeMirror לתצוגת מסמכים.
 */
function initDocumentsEditor() {
    if (typeof CodeMirror === 'undefined') {
        console.log('CodeMirror not available, using fallback <pre>');
        return;
    }

    const textarea = document.getElementById('documents-code-editor');
    const preFallback = document.getElementById('documents-code');
    
    if (!textarea) return;

    // קבע theme לפי ה-theme הנוכחי של הדף
    const currentTheme = document.documentElement.dataset.theme || 'dark';
    const cmTheme = currentTheme.includes('dawn') || currentTheme.includes('light') 
        ? 'default'  // או theme בהיר אחר שיש לך
        : 'dracula'; // או theme כהה אחר

    textarea.style.display = 'block';
    
    window.documentsEditor = CodeMirror.fromTextArea(textarea, {
        mode: { name: 'javascript', json: true },
        theme: cmTheme,
        readOnly: true,
        lineNumbers: true,
        foldGutter: true,
        gutters: ['CodeMirror-linenumbers', 'CodeMirror-foldgutter'],
        lineWrapping: true,
        matchBrackets: true,
    });

    // הסתר את ה-pre fallback
    if (preFallback) {
        preFallback.style.display = 'none';
    }

    // עדכן theme כש-theme הדף משתנה
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            if (mutation.attributeName === 'data-theme') {
                const newTheme = document.documentElement.dataset.theme || 'dark';
                const newCmTheme = newTheme.includes('dawn') || newTheme.includes('light')
                    ? 'default'
                    : 'dracula';
                window.documentsEditor.setOption('theme', newCmTheme);
            }
        });
    });
    observer.observe(document.documentElement, { attributes: true });
}
```

---

## 🔒 אבטחה - סיכום

### מה מיושם:

| שכבה | מנגנון | תיאור |
|:---|:---|:---|
| **Authentication** | `db_health_auth_middleware` | Token נדרש לכל `/api/db/*` |
| **Authorization** | Whitelist/Denylist | הגדרת collections מותרים/חסומים |
| **Input Validation** | `_validate_collection_name()` | מניעת injection |
| **Data Protection** | `_redact_sensitive_fields()` | הסתרת שדות רגישים |
| **Rate Limiting** | `limit` capping | מקסימום 100 מסמכים לבקשה |
| **XSS Prevention** | `textContent` | לא משתמשים ב-innerHTML |

### התאמה אישית:

```python
# ב-services/db_health_service.py:

# אפשרות 1: רק collections ספציפיים מותרים
ALLOWED_COLLECTIONS = {"users", "snippets", "logs", "configs"}

# אפשרות 2: הכל מותר חוץ מרשימה שחורה
ALLOWED_COLLECTIONS = None
DENIED_COLLECTIONS = {"sessions", "tokens", "api_keys", "secrets", "password_resets"}

# שדות רגישים להסתרה
SENSITIVE_FIELDS = {
    "password", "password_hash", "token", "api_key", 
    "secret", "private_key", "credentials", "refresh_token",
}
```

---

## 🧪 בדיקות יחידה

### הוספה ל-`tests/test_db_health_service.py`

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId

from services.db_health_service import (
    AsyncDatabaseHealthService,
    _redact_sensitive_fields,
    _validate_collection_name,
    InvalidCollectionNameError,
    CollectionAccessDeniedError,
    SENSITIVE_FIELDS,
)


class TestRedactSensitiveFields:
    """בדיקות לפונקציית _redact_sensitive_fields."""

    def test_redacts_password_field(self):
        doc = {"name": "Alice", "password": "secret123"}
        result = _redact_sensitive_fields(doc)
        assert result["name"] == "Alice"
        assert result["password"] == "[REDACTED]"

    def test_redacts_nested_fields(self):
        doc = {"user": {"name": "Bob", "api_key": "key123"}}
        result = _redact_sensitive_fields(doc)
        assert result["user"]["name"] == "Bob"
        assert result["user"]["api_key"] == "[REDACTED]"

    def test_redacts_in_arrays(self):
        doc = {"users": [{"name": "A", "token": "t1"}, {"name": "B", "token": "t2"}]}
        result = _redact_sensitive_fields(doc)
        assert result["users"][0]["token"] == "[REDACTED]"
        assert result["users"][1]["token"] == "[REDACTED]"

    def test_case_insensitive_redaction(self):
        doc = {"Password": "secret", "API_KEY": "key"}
        result = _redact_sensitive_fields(doc)
        assert result["Password"] == "[REDACTED]"
        assert result["API_KEY"] == "[REDACTED]"


class TestValidateCollectionName:
    """בדיקות לפונקציית _validate_collection_name."""

    def test_valid_name_passes(self):
        _validate_collection_name("users")  # לא זורק

    def test_empty_name_raises(self):
        with pytest.raises(InvalidCollectionNameError):
            _validate_collection_name("")

    def test_dollar_prefix_raises(self):
        with pytest.raises(InvalidCollectionNameError):
            _validate_collection_name("$system")

    def test_null_char_raises(self):
        with pytest.raises(InvalidCollectionNameError):
            _validate_collection_name("users\0test")

    def test_double_dot_raises(self):
        with pytest.raises(InvalidCollectionNameError):
            _validate_collection_name("users..test")


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

    async def test_get_documents_success_with_more_pages(self, service_with_mock_db):
        """בדיקת שליפה תקינה עם עמודים נוספים (עמוד מלא)."""
        svc = service_with_mock_db

        # Mock collection
        mock_collection = AsyncMock()
        mock_collection.count_documents = AsyncMock(return_value=100)

        # Mock cursor with sort - מחזיר עמוד מלא (20 מסמכים)
        mock_cursor = AsyncMock()
        mock_docs = [{'_id': ObjectId(), 'name': f'User{i}'} for i in range(20)]
        mock_cursor.to_list = AsyncMock(return_value=mock_docs)
        mock_collection.find.return_value.sort.return_value.skip.return_value.limit.return_value = mock_cursor

        svc._db.__getitem__ = MagicMock(return_value=mock_collection)

        result = await svc.get_documents('users', skip=0, limit=20)

        assert result['collection'] == 'users'
        assert result['total'] == 100
        assert len(result['documents']) == 20
        # has_more=True כי קיבלנו עמוד מלא (len == limit)
        assert result['has_more'] is True
        assert result['skip'] == 0
        assert result['limit'] == 20

    async def test_get_documents_last_page(self, service_with_mock_db):
        """בדיקת שליפה בעמוד האחרון (עמוד חלקי)."""
        svc = service_with_mock_db

        mock_collection = AsyncMock()
        mock_collection.count_documents = AsyncMock(return_value=25)

        # Mock cursor - מחזיר רק 5 מסמכים (עמוד חלקי)
        mock_cursor = AsyncMock()
        mock_docs = [{'_id': ObjectId(), 'name': f'User{i}'} for i in range(5)]
        mock_cursor.to_list = AsyncMock(return_value=mock_docs)
        mock_collection.find.return_value.sort.return_value.skip.return_value.limit.return_value = mock_cursor

        svc._db.__getitem__ = MagicMock(return_value=mock_collection)

        result = await svc.get_documents('users', skip=20, limit=20)

        assert len(result['documents']) == 5
        # has_more=False כי קיבלנו פחות מ-limit
        assert result['has_more'] is False
        assert result['returned_count'] == 5

    async def test_get_documents_with_redaction(self, service_with_mock_db):
        """בדיקה שהשדות הרגישים מוסתרים."""
        svc = service_with_mock_db

        mock_collection = AsyncMock()
        mock_collection.count_documents = AsyncMock(return_value=1)

        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[
            {'_id': ObjectId(), 'name': 'Alice', 'password': 'secret123'},
        ])
        mock_collection.find.return_value.sort.return_value.skip.return_value.limit.return_value = mock_cursor

        svc._db.__getitem__ = MagicMock(return_value=mock_collection)

        result = await svc.get_documents('users', skip=0, limit=20, redact_sensitive=True)

        assert result['documents'][0]['name'] == 'Alice'
        assert result['documents'][0]['password'] == '[REDACTED]'

    async def test_get_documents_invalid_name(self, service_with_mock_db):
        """בדיקת שגיאה עם שם collection לא תקין."""
        svc = service_with_mock_db

        with pytest.raises(InvalidCollectionNameError):
            await svc.get_documents("$system", skip=0, limit=20)

    async def test_get_documents_limit_capping(self, service_with_mock_db):
        """בדיקה שה-limit מוגבל ל-100."""
        svc = service_with_mock_db

        mock_collection = AsyncMock()
        mock_collection.count_documents = AsyncMock(return_value=500)
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_collection.find.return_value.sort.return_value.skip.return_value.limit.return_value = mock_cursor
        svc._db.__getitem__ = MagicMock(return_value=mock_collection)

        result = await svc.get_documents('users', skip=0, limit=500)

        # וודא שה-limit הוגבל ל-100
        assert result['limit'] == 100

    async def test_get_documents_empty_collection(self, service_with_mock_db):
        """בדיקה של collection ריק."""
        svc = service_with_mock_db

        mock_collection = AsyncMock()
        mock_collection.count_documents = AsyncMock(return_value=0)
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_collection.find.return_value.sort.return_value.skip.return_value.limit.return_value = mock_cursor
        svc._db.__getitem__ = MagicMock(return_value=mock_collection)

        result = await svc.get_documents('empty_collection', skip=0, limit=20)

        assert result['total'] == 0
        assert result['documents'] == []
        assert result['has_more'] is False
        assert result['returned_count'] == 0


@pytest.mark.asyncio
class TestDocumentsEndpoint:
    """בדיקות ל-API endpoint."""

    async def test_invalid_skip_returns_400(self, aiohttp_client, app):
        """skip שלילי מחזיר 400."""
        client = await aiohttp_client(app)
        resp = await client.get(
            '/api/db/users/documents?skip=-1',
            headers={'Authorization': 'Bearer test-token'}
        )
        assert resp.status == 400

    async def test_access_denied_returns_403(self, aiohttp_client, app):
        """גישה ל-collection חסום מחזירה 403."""
        # TODO: מימוש עם mock של DENIED_COLLECTIONS
        pass
```

---

## 📋 רשימת תיוג למימוש

### Backend:
- [ ] הוסף imports חדשים (`re`, `json`, `bson.json_util`, `Set`)
- [ ] הוסף קבועים (`DEFAULT_DOCUMENTS_LIMIT`, `MAX_DOCUMENTS_LIMIT`, `SENSITIVE_FIELDS`, `ALLOWED_COLLECTIONS`, `DENIED_COLLECTIONS`)
- [ ] הוסף Custom Exceptions (`InvalidCollectionNameError`, `CollectionAccessDeniedError`, `CollectionNotFoundError`)
- [ ] הוסף `_redact_sensitive_fields()`
- [ ] הוסף `_validate_collection_name()`
- [ ] הוסף `get_documents()` ל-`AsyncDatabaseHealthService` **עם `sort("_id", 1)`**
- [ ] הוסף `get_documents_sync()` ל-`SyncDatabaseHealthService`
- [ ] הוסף `get_documents()` async wrapper ל-`ThreadPoolDatabaseHealthService`

### API:
- [ ] הוסף import של Exceptions ל-webserver
- [ ] הוסף `db_collection_documents_view` handler **עם טיפול נפרד ב-400/403/404**
- [ ] הוסף route: `app.router.add_get("/api/db/{collection}/documents", ...)`

### Frontend:
- [ ] הוסף HTML ל-documents viewer **עם כותרת דינמית**
- [ ] הוסף CSS עיצוב **כולל empty state**
- [ ] הוסף JavaScript לטעינה ודפדוף **עם Copy JSON**
- [ ] עדכן `loadCollections()` להוספת לחיצה על שורות
- [ ] (אופציונלי) הוסף CodeMirror **עם theme דינמי**

### בדיקות:
- [ ] הוסף בדיקות ל-`_redact_sensitive_fields()`
- [ ] הוסף בדיקות ל-`_validate_collection_name()`
- [ ] הוסף בדיקות ל-`get_documents()`
- [ ] בדוק ידנית בדפדפן

### תיעוד:
- [ ] עדכן `DATABASE_HEALTH_DASHBOARD_GUIDE.md` עם הפיצ'ר החדש

---

## 🔗 קישורים רלוונטיים

- [DATABASE_HEALTH_DASHBOARD_GUIDE.md](./DATABASE_HEALTH_DASHBOARD_GUIDE.md) - מדריך הדשבורד הקיים
- [services/db_health_service.py](/services/db_health_service.py) - קוד השירות
- [services/webserver.py](/services/webserver.py) - ה-API endpoints
- [webapp/templates/db_health.html](/webapp/templates/db_health.html) - התבנית הקיימת
