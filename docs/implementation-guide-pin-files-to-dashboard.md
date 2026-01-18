# מדריך מימוש: נעיצת קבצים לדשבורד

## סקירה כללית

מדריך זה מתאר את השלבים למימוש פיצ'ר "נעץ לדשבורד" - אפשרות לנעוץ קבצים חשובים לדשבורד לגישה מהירה קבועה.

**מיקום הכפתור:** עמוד תצוגת קובץ, בתוך תפריט 3 הנקודות

---

## ארכיטקטורה

```
┌─────────────────────────────────────────────────────────────┐
│                    Dashboard Template                        │
│         webapp/templates/dashboard.html                      │
│    ┌──────────────────────────────────────┐                 │
│    │     📌 קבצים נעוצים (חדש)            │                 │
│    │  ┌────┐ ┌────┐ ┌────┐ ┌────┐        │                 │
│    │  │File│ │File│ │File│ │ +  │        │                 │
│    │  └────┘ └────┘ └────┘ └────┘        │                 │
│    └──────────────────────────────────────┘                 │
└─────────────────────────────────────────────────────────────┘
                           ▲
                           │ GET /api/dashboard/pinned-files
                           │
┌─────────────────────────────────────────────────────────────┐
│                    Flask Backend                             │
│                    webapp/app.py                             │
│                                                              │
│  POST /api/files/pin-to-dashboard                           │
│  POST /api/files/unpin-from-dashboard                       │
│  GET  /api/dashboard/pinned-files                           │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    MongoDB                                   │
│            code_snippets / large_files                       │
│                                                              │
│  + is_pinned_to_dashboard: Boolean                          │
│  + pinned_to_dashboard_at: DateTime                         │
│  + pinned_to_dashboard_order: Integer                       │
└─────────────────────────────────────────────────────────────┘
```

---

## שלב 1: עדכון מודל הנתונים

### קובץ: `database/models.py`

הוסף את השדות הבאים למודלים `CodeSnippet` ו-`LargeFile`:

```python
@dataclass
class CodeSnippet:
    # ... שדות קיימים ...

    # שדות חדשים לנעיצה לדשבורד
    is_pinned_to_dashboard: bool = False
    pinned_to_dashboard_at: Optional[datetime] = None
    pinned_to_dashboard_order: int = 0  # לסידור הקבצים הנעוצים
```

### הסבר השדות:

| שדה | סוג | תיאור |
|-----|-----|-------|
| `is_pinned_to_dashboard` | `bool` | האם הקובץ נעוץ לדשבורד |
| `pinned_to_dashboard_at` | `datetime` | מתי נעוץ (לסינון ומיון) |
| `pinned_to_dashboard_order` | `int` | סדר התצוגה (0 = ראשון) |

---

## שלב 2: יצירת API Endpoints

### קובץ: `webapp/app.py`

הוסף את ה-endpoints הבאים (מומלץ באזור שורות 13750+, ליד endpoints של favorites):

### 2.1 נעיצה לדשבורד

```python
@app.route('/api/files/pin-to-dashboard', methods=['POST'])
@login_required
@traced("files.pin_to_dashboard")
def pin_files_to_dashboard():
    """נעיצת קבצים לדשבורד"""
    try:
        user_id = session['user_id']
        data = request.get_json()

        if not data or 'file_ids' not in data:
            return jsonify({'success': False, 'error': 'file_ids נדרש'}), 400

        file_ids = data['file_ids']

        if not isinstance(file_ids, list) or len(file_ids) == 0:
            return jsonify({'success': False, 'error': 'file_ids חייב להיות רשימה לא ריקה'}), 400

        if len(file_ids) > 20:  # הגבלה - מקסימום 20 קבצים נעוצים
            return jsonify({'success': False, 'error': 'ניתן לנעוץ עד 20 קבצים'}), 400

        db = get_db()
        now = datetime.now(timezone.utc)

        # המרת IDs ל-ObjectId
        try:
            object_ids = [ObjectId(fid) for fid in file_ids]
        except Exception:
            return jsonify({'success': False, 'error': 'ID קובץ לא תקין'}), 400

        # בדיקת כמה קבצים כבר נעוצים
        current_pinned_count = db.code_snippets.count_documents({
            'user_id': user_id,
            'is_pinned_to_dashboard': True
        })

        if current_pinned_count + len(file_ids) > 20:
            return jsonify({
                'success': False,
                'error': f'חריגה ממגבלת 20 קבצים נעוצים. כרגע נעוצים: {current_pinned_count}'
            }), 400

        # חישוב הסדר הבא
        max_order_doc = db.code_snippets.find_one(
            {'user_id': user_id, 'is_pinned_to_dashboard': True},
            sort=[('pinned_to_dashboard_order', -1)]
        )
        next_order = (max_order_doc.get('pinned_to_dashboard_order', 0) + 1) if max_order_doc else 0

        # עדכון code_snippets
        updated_snippets = 0
        for i, oid in enumerate(object_ids):
            result = db.code_snippets.update_one(
                {'_id': oid, 'user_id': user_id},
                {
                    '$set': {
                        'is_pinned_to_dashboard': True,
                        'pinned_to_dashboard_at': now,
                        'pinned_to_dashboard_order': next_order + i,
                        'updated_at': now
                    }
                }
            )
            updated_snippets += result.modified_count

        # עדכון large_files
        updated_large = 0
        for i, oid in enumerate(object_ids):
            result = db.large_files.update_one(
                {'_id': oid, 'user_id': user_id},
                {
                    '$set': {
                        'is_pinned_to_dashboard': True,
                        'pinned_to_dashboard_at': now,
                        'pinned_to_dashboard_order': next_order + i,
                        'updated_at': now
                    }
                }
            )
            updated_large += result.modified_count

        total_updated = updated_snippets + updated_large

        # ניקוי cache
        cache.delete_pattern(f"dashboard:pinned:{user_id}:*")

        return jsonify({
            'success': True,
            'updated': total_updated,
            'message': f'{total_updated} קבצים נעוצו לדשבורד'
        })

    except Exception as e:
        logger.error(f"Error pinning files to dashboard: {e}")
        return jsonify({'success': False, 'error': 'שגיאה בנעיצת קבצים'}), 500
```

### 2.2 הסרת נעיצה

```python
@app.route('/api/files/unpin-from-dashboard', methods=['POST'])
@login_required
@traced("files.unpin_from_dashboard")
def unpin_files_from_dashboard():
    """הסרת נעיצה מדשבורד"""
    try:
        user_id = session['user_id']
        data = request.get_json()

        if not data or 'file_ids' not in data:
            return jsonify({'success': False, 'error': 'file_ids נדרש'}), 400

        file_ids = data['file_ids']

        if not isinstance(file_ids, list) or len(file_ids) == 0:
            return jsonify({'success': False, 'error': 'file_ids חייב להיות רשימה לא ריקה'}), 400

        db = get_db()
        now = datetime.now(timezone.utc)

        try:
            object_ids = [ObjectId(fid) for fid in file_ids]
        except Exception:
            return jsonify({'success': False, 'error': 'ID קובץ לא תקין'}), 400

        # עדכון code_snippets
        result_snippets = db.code_snippets.update_many(
            {'_id': {'$in': object_ids}, 'user_id': user_id},
            {
                '$set': {
                    'is_pinned_to_dashboard': False,
                    'pinned_to_dashboard_at': None,
                    'pinned_to_dashboard_order': 0,
                    'updated_at': now
                }
            }
        )

        # עדכון large_files
        result_large = db.large_files.update_many(
            {'_id': {'$in': object_ids}, 'user_id': user_id},
            {
                '$set': {
                    'is_pinned_to_dashboard': False,
                    'pinned_to_dashboard_at': None,
                    'pinned_to_dashboard_order': 0,
                    'updated_at': now
                }
            }
        )

        total_updated = result_snippets.modified_count + result_large.modified_count

        cache.delete_pattern(f"dashboard:pinned:{user_id}:*")

        return jsonify({
            'success': True,
            'updated': total_updated,
            'message': f'{total_updated} קבצים הוסרו מהנעיצה'
        })

    except Exception as e:
        logger.error(f"Error unpinning files from dashboard: {e}")
        return jsonify({'success': False, 'error': 'שגיאה בהסרת נעיצה'}), 500
```

### 2.3 שליפת קבצים נעוצים

```python
@app.route('/api/dashboard/pinned-files', methods=['GET'])
@login_required
@traced("dashboard.pinned_files")
@dynamic_cache(timeout=300, key_prefix="dashboard:pinned")
def get_pinned_files():
    """שליפת קבצים נעוצים לדשבורד"""
    try:
        user_id = session['user_id']
        db = get_db()

        # שליפה מ-code_snippets
        pinned_snippets = list(db.code_snippets.find(
            {'user_id': user_id, 'is_pinned_to_dashboard': True},
            {
                '_id': 1,
                'file_name': 1,
                'programming_language': 1,
                'pinned_to_dashboard_order': 1,
                'pinned_to_dashboard_at': 1,
                'updated_at': 1
            }
        ).sort('pinned_to_dashboard_order', 1))

        # שליפה מ-large_files
        pinned_large = list(db.large_files.find(
            {'user_id': user_id, 'is_pinned_to_dashboard': True},
            {
                '_id': 1,
                'file_name': 1,
                'programming_language': 1,
                'pinned_to_dashboard_order': 1,
                'pinned_to_dashboard_at': 1,
                'updated_at': 1
            }
        ).sort('pinned_to_dashboard_order', 1))

        # איחוד ומיון
        all_pinned = []

        for doc in pinned_snippets:
            all_pinned.append({
                'id': str(doc['_id']),
                'file_name': doc.get('file_name', 'ללא שם'),
                'language': doc.get('programming_language', 'unknown'),
                'order': doc.get('pinned_to_dashboard_order', 0),
                'pinned_at': doc.get('pinned_to_dashboard_at').isoformat() if doc.get('pinned_to_dashboard_at') else None,
                'type': 'snippet'
            })

        for doc in pinned_large:
            all_pinned.append({
                'id': str(doc['_id']),
                'file_name': doc.get('file_name', 'ללא שם'),
                'language': doc.get('programming_language', 'unknown'),
                'order': doc.get('pinned_to_dashboard_order', 0),
                'pinned_at': doc.get('pinned_to_dashboard_at').isoformat() if doc.get('pinned_to_dashboard_at') else None,
                'type': 'large_file'
            })

        # מיון לפי order
        all_pinned.sort(key=lambda x: x['order'])

        return jsonify({
            'success': True,
            'pinned_files': all_pinned,
            'count': len(all_pinned)
        })

    except Exception as e:
        logger.error(f"Error fetching pinned files: {e}")
        return jsonify({'success': False, 'error': 'שגיאה בשליפת קבצים נעוצים'}), 500
```

---

## שלב 3: עדכון תפריט 3 הנקודות בעמוד הקובץ

### קובץ: `webapp/templates/files.html`

מצא את תפריט 3 הנקודות (סביב שורות 370-385) והוסף אפשרות נעיצה:

```html
<!-- תפריט 3 נקודות לקובץ -->
<div class="dropdown">
    <button class="btn btn-sm btn-outline-secondary dropdown-toggle"
            type="button"
            data-bs-toggle="dropdown"
            aria-expanded="false">
        <i class="bi bi-three-dots-vertical"></i>
    </button>
    <ul class="dropdown-menu dropdown-menu-end">
        <!-- אפשרויות קיימות -->
        <li>
            <a class="dropdown-item" href="#" onclick="viewFile('{{ file.id }}')">
                <i class="bi bi-eye me-2"></i>צפייה
            </a>
        </li>
        <li>
            <a class="dropdown-item" href="#" onclick="downloadFile('{{ file.id }}')">
                <i class="bi bi-download me-2"></i>הורדה
            </a>
        </li>
        <li><hr class="dropdown-divider"></li>

        <!-- כפתור נעיצה חדש -->
        <li>
            <a class="dropdown-item pin-to-dashboard-btn"
               href="#"
               onclick="togglePinToDashboard('{{ file.id }}', this)"
               data-pinned="{{ 'true' if file.is_pinned_to_dashboard else 'false' }}">
                <i class="bi {{ 'bi-pin-fill' if file.is_pinned_to_dashboard else 'bi-pin' }} me-2"></i>
                <span class="pin-text">
                    {{ 'הסר מדשבורד' if file.is_pinned_to_dashboard else 'נעץ לדשבורד' }}
                </span>
            </a>
        </li>

        <li><hr class="dropdown-divider"></li>
        <li>
            <a class="dropdown-item text-danger" href="#" onclick="deleteFile('{{ file.id }}')">
                <i class="bi bi-trash me-2"></i>מחיקה
            </a>
        </li>
    </ul>
</div>
```

---

## שלב 4: JavaScript לטיפול בנעיצה

### קובץ: `webapp/static/js/bulk-actions.js` או קובץ JS חדש

```javascript
/**
 * נעיצה/הסרת נעיצה של קובץ מהדשבורד
 * @param {string} fileId - ID הקובץ
 * @param {HTMLElement} buttonElement - האלמנט שנלחץ
 */
async function togglePinToDashboard(fileId, buttonElement) {
    const isPinned = buttonElement.dataset.pinned === 'true';
    const endpoint = isPinned ? '/api/files/unpin-from-dashboard' : '/api/files/pin-to-dashboard';

    try {
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ file_ids: [fileId] })
        });

        const data = await response.json();

        if (data.success) {
            // עדכון ה-UI
            const newPinned = !isPinned;
            buttonElement.dataset.pinned = newPinned.toString();

            const icon = buttonElement.querySelector('i');
            const text = buttonElement.querySelector('.pin-text');

            if (newPinned) {
                icon.classList.remove('bi-pin');
                icon.classList.add('bi-pin-fill');
                text.textContent = 'הסר מדשבורד';
                showNotification('הקובץ נעוץ לדשבורד', 'success');
            } else {
                icon.classList.remove('bi-pin-fill');
                icon.classList.add('bi-pin');
                text.textContent = 'נעץ לדשבורד';
                showNotification('הקובץ הוסר מהדשבורד', 'info');
            }
        } else {
            showNotification(data.error || 'שגיאה בעדכון', 'error');
        }
    } catch (error) {
        console.error('Error toggling pin:', error);
        showNotification('שגיאה בתקשורת עם השרת', 'error');
    }
}

/**
 * נעיצה מרובה (bulk) לדשבורד
 */
async function bulkPinToDashboard() {
    const selectedIds = getSelectedFileIds(); // פונקציה קיימת

    if (selectedIds.length === 0) {
        showNotification('יש לבחור קבצים', 'warning');
        return;
    }

    if (selectedIds.length > 20) {
        showNotification('ניתן לנעוץ עד 20 קבצים', 'warning');
        return;
    }

    try {
        const response = await fetch('/api/files/pin-to-dashboard', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ file_ids: selectedIds })
        });

        const data = await response.json();

        if (data.success) {
            showNotification(data.message, 'success');
            refreshFileList(); // רענון הרשימה
        } else {
            showNotification(data.error || 'שגיאה בנעיצה', 'error');
        }
    } catch (error) {
        console.error('Error bulk pinning:', error);
        showNotification('שגיאה בתקשורת עם השרת', 'error');
    }
}

/**
 * הצגת התראה למשתמש
 */
function showNotification(message, type = 'info') {
    // שימוש במערכת ההתראות הקיימת
    if (window.bulkActions && window.bulkActions.showNotification) {
        window.bulkActions.showNotification(message, type);
    } else {
        // fallback
        alert(message);
    }
}
```

---

## שלב 5: הצגת קבצים נעוצים בדשבורד

### קובץ: `webapp/templates/dashboard.html`

הוסף את הסקשן הבא (מומלץ לפני "What's New", סביב שורה 69):

```html
<!-- קבצים נעוצים -->
<div class="card mb-4 shadow-sm" id="pinned-files-card">
    <div class="card-header d-flex justify-content-between align-items-center">
        <h5 class="mb-0">
            <i class="bi bi-pin-fill text-primary me-2"></i>
            קבצים נעוצים
        </h5>
        <span class="badge bg-secondary" id="pinned-count">0</span>
    </div>
    <div class="card-body">
        <div id="pinned-files-container" class="row g-3">
            <!-- יטען דינמית -->
            <div class="col-12 text-center text-muted" id="no-pinned-message">
                <i class="bi bi-pin fs-1 d-block mb-2"></i>
                <p>אין קבצים נעוצים</p>
                <small>נעץ קבצים חשובים מעמוד הקבצים לגישה מהירה</small>
            </div>
        </div>
    </div>
</div>
```

### JavaScript לטעינת קבצים נעוצים בדשבורד:

```html
<script>
document.addEventListener('DOMContentLoaded', function() {
    loadPinnedFiles();
});

async function loadPinnedFiles() {
    try {
        const response = await fetch('/api/dashboard/pinned-files');
        const data = await response.json();

        if (data.success) {
            renderPinnedFiles(data.pinned_files);
            document.getElementById('pinned-count').textContent = data.count;
        }
    } catch (error) {
        console.error('Error loading pinned files:', error);
    }
}

function renderPinnedFiles(files) {
    const container = document.getElementById('pinned-files-container');
    const noMessage = document.getElementById('no-pinned-message');

    if (files.length === 0) {
        noMessage.style.display = 'block';
        return;
    }

    noMessage.style.display = 'none';

    const html = files.map(file => `
        <div class="col-6 col-md-4 col-lg-3">
            <div class="card h-100 pinned-file-card" data-file-id="${file.id}">
                <div class="card-body p-3">
                    <div class="d-flex justify-content-between align-items-start">
                        <div class="flex-grow-1 overflow-hidden">
                            <h6 class="card-title text-truncate mb-1" title="${file.file_name}">
                                ${file.file_name}
                            </h6>
                            <span class="badge bg-light text-dark">
                                ${file.language}
                            </span>
                        </div>
                        <button class="btn btn-sm btn-link text-muted p-0"
                                onclick="unpinFromDashboard('${file.id}')"
                                title="הסר נעיצה">
                            <i class="bi bi-x"></i>
                        </button>
                    </div>
                </div>
                <div class="card-footer p-2">
                    <a href="/files/${file.id}" class="btn btn-sm btn-primary w-100">
                        <i class="bi bi-eye me-1"></i>פתח
                    </a>
                </div>
            </div>
        </div>
    `).join('');

    container.innerHTML = html;
}

async function unpinFromDashboard(fileId) {
    try {
        const response = await fetch('/api/files/unpin-from-dashboard', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ file_ids: [fileId] })
        });

        const data = await response.json();

        if (data.success) {
            // הסרה מה-DOM עם אנימציה
            const card = document.querySelector(`[data-file-id="${fileId}"]`);
            if (card) {
                card.parentElement.style.transition = 'opacity 0.3s';
                card.parentElement.style.opacity = '0';
                setTimeout(() => {
                    card.parentElement.remove();
                    // עדכון הספירה
                    const countEl = document.getElementById('pinned-count');
                    countEl.textContent = parseInt(countEl.textContent) - 1;

                    // בדיקה אם אין עוד קבצים
                    if (parseInt(countEl.textContent) === 0) {
                        document.getElementById('no-pinned-message').style.display = 'block';
                    }
                }, 300);
            }
        }
    } catch (error) {
        console.error('Error unpinning:', error);
    }
}
</script>
```

---

## שלב 6: CSS לעיצוב

### קובץ: `webapp/static/css/style.css` (או קובץ CSS רלוונטי)

```css
/* קבצים נעוצים בדשבורד */
.pinned-file-card {
    transition: transform 0.2s, box-shadow 0.2s;
    border: 1px solid #e0e0e0;
}

.pinned-file-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.pinned-file-card .card-title {
    font-size: 0.9rem;
    font-weight: 600;
}

.pinned-file-card .card-footer {
    background: transparent;
    border-top: 1px solid #f0f0f0;
}

/* כפתור נעיצה בתפריט */
.pin-to-dashboard-btn[data-pinned="true"] {
    color: #0d6efd;
    font-weight: 500;
}

.pin-to-dashboard-btn[data-pinned="true"] i {
    color: #0d6efd;
}

/* אנימציה לנעיצה */
@keyframes pinPulse {
    0% { transform: scale(1); }
    50% { transform: scale(1.2); }
    100% { transform: scale(1); }
}

.pin-to-dashboard-btn.just-pinned i {
    animation: pinPulse 0.3s ease;
}

/* Drag and Drop לסידור מחדש (אופציונלי) */
.pinned-file-card.dragging {
    opacity: 0.5;
    cursor: move;
}

.pinned-files-container.drag-over .pinned-file-card {
    pointer-events: none;
}
```

---

## שלב 7: אינדקסים ב-MongoDB

### הוספת אינדקס לשיפור ביצועים

הרץ את הפקודות הבאות ב-MongoDB shell או הוסף לקובץ migrations:

```javascript
// אינדקס לשליפת קבצים נעוצים
db.code_snippets.createIndex(
    { "user_id": 1, "is_pinned_to_dashboard": 1, "pinned_to_dashboard_order": 1 },
    { name: "idx_pinned_dashboard" }
);

db.large_files.createIndex(
    { "user_id": 1, "is_pinned_to_dashboard": 1, "pinned_to_dashboard_order": 1 },
    { name: "idx_pinned_dashboard" }
);
```

---

## שלב 8: בדיקות (Tests)

### קובץ: `tests/test_pin_to_dashboard.py`

```python
import pytest
from flask import session
from bson import ObjectId
from datetime import datetime, timezone

class TestPinToDashboard:
    """בדיקות לפיצ'ר נעיצה לדשבורד"""

    def test_pin_single_file(self, client, auth_user, test_file):
        """בדיקת נעיצת קובץ בודד"""
        response = client.post('/api/files/pin-to-dashboard',
            json={'file_ids': [str(test_file['_id'])]})

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] == True
        assert data['updated'] == 1

    def test_pin_multiple_files(self, client, auth_user, test_files):
        """בדיקת נעיצת מספר קבצים"""
        file_ids = [str(f['_id']) for f in test_files[:5]]
        response = client.post('/api/files/pin-to-dashboard',
            json={'file_ids': file_ids})

        assert response.status_code == 200
        data = response.get_json()
        assert data['updated'] == 5

    def test_pin_limit_exceeded(self, client, auth_user, many_pinned_files):
        """בדיקת חריגה ממגבלת 20 קבצים"""
        response = client.post('/api/files/pin-to-dashboard',
            json={'file_ids': ['new_file_id']})

        assert response.status_code == 400
        data = response.get_json()
        assert 'מגבלת 20' in data['error']

    def test_unpin_file(self, client, auth_user, pinned_file):
        """בדיקת הסרת נעיצה"""
        response = client.post('/api/files/unpin-from-dashboard',
            json={'file_ids': [str(pinned_file['_id'])]})

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] == True

    def test_get_pinned_files(self, client, auth_user, pinned_files):
        """בדיקת שליפת קבצים נעוצים"""
        response = client.get('/api/dashboard/pinned-files')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] == True
        assert len(data['pinned_files']) == len(pinned_files)

    def test_pinned_files_order(self, client, auth_user, pinned_files):
        """בדיקת סדר הקבצים הנעוצים"""
        response = client.get('/api/dashboard/pinned-files')
        data = response.get_json()

        orders = [f['order'] for f in data['pinned_files']]
        assert orders == sorted(orders)  # וידוא שממוין

    def test_pin_unauthorized(self, client, test_file):
        """בדיקת נעיצה ללא התחברות"""
        response = client.post('/api/files/pin-to-dashboard',
            json={'file_ids': [str(test_file['_id'])]})

        assert response.status_code == 401

    def test_pin_other_user_file(self, client, auth_user, other_user_file):
        """בדיקת נעיצת קובץ של משתמש אחר"""
        response = client.post('/api/files/pin-to-dashboard',
            json={'file_ids': [str(other_user_file['_id'])]})

        data = response.get_json()
        assert data['updated'] == 0  # לא אמור לעדכן קובץ של אחר
```

---

## סיכום שלבי המימוש

| שלב | תיאור | קבצים לעריכה |
|-----|-------|--------------|
| 1 | עדכון מודל הנתונים | `database/models.py` |
| 2 | יצירת API endpoints | `webapp/app.py` |
| 3 | עדכון תפריט 3 הנקודות | `webapp/templates/files.html` |
| 4 | JavaScript לטיפול בנעיצה | `webapp/static/js/bulk-actions.js` |
| 5 | הצגה בדשבורד | `webapp/templates/dashboard.html` |
| 6 | עיצוב CSS | `webapp/static/css/style.css` |
| 7 | אינדקסים MongoDB | Migration script |
| 8 | בדיקות | `tests/test_pin_to_dashboard.py` |

---

## הרחבות אפשריות לעתיד

1. **Drag & Drop** - סידור מחדש של הקבצים הנעוצים
2. **קטגוריות נעיצה** - נעיצה לאזורים שונים בדשבורד
3. **תזכורות** - התראה על קבצים נעוצים שלא נצפו זמן רב
4. **שיתוף** - נעיצת קבצים משותפים לצוות
5. **Widget מותאם** - גודל ומיקום מותאמים אישית לכל קובץ נעוץ

---

## קבצי עזר קיימים במערכת

| קובץ | רלוונטיות |
|------|-----------|
| `webapp/app.py:13675-13750` | דוגמה ל-bulk favorites API |
| `database/collections_manager.py:90-145` | מימוש pinning קיים לקולקציות |
| `webapp/static/js/bulk-actions.js` | דפוסי JavaScript לפעולות bulk |
| `webapp/templates/files.html:612-618` | פונקציות favorites קיימות |

---

*מסמך זה נוצר אוטומטית. תאריך: {{ current_date }}*
