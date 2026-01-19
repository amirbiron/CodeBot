# מדריך מימוש: ווידג'ט "קבצים שדורשים טיפול" בדשבורד

> **מטרה:** ווידג'ט בדשבורד שמרכז קבצים "בעייתיים" (חסרי תיאור/תגיות, או לא נפתחו זמן רב) עם אפשרות לתיקון מהיר ישירות מהדשבורד.

---

## 1. סקירה כללית

### מה הווידג'ט עושה
- **מרכז קבצים שדורשים טיפול** בכרטיס אחד בדשבורד
- **מחולק לשתי קבוצות:**
  1. "חסר תיאור/תגיות" — קבצים שאין להם `description` או שרשימת ה-`tags` ריקה
  2. "לא נפתח זמן רב" — קבצים שה-`updated_at` שלהם ישן מ-X ימים (ברירת מחדל: 60)
- **מציע תיקון מהיר (Quick Fix):**
  - הוספת תיאור inline
  - הוספת תגיות (chip input)
  - פתיחה לעריכה מלאה
  - דחייה/הסתרה זמנית ("טפל מאוחר יותר")

### למה זה שימושי
- מצמצם "זיהום" של קבצים לא מתועדים
- עוזר לזכור קבצים שננטשו בלי לפתוח חיפוש ידני
- מקצר זמן: תיקון קטן (תיאור/תגיות) בלחיצה אחת

---

## 2. ארכיטקטורה ותכנון

### מיקום בדשבורד
הווידג'ט יתווסף ל-**dashboard-grid** כ-card חדש:
- **Desktop (≥1200px):** שורה נוספת מתחת ל-pinned/whatsnew/lastcommit
- **Tablet (769–1199px):** כרטיס שלם בשורה חדשה או לצד languages-top
- **Mobile:** כרטיס מתחת ל-activity-section

### מבנה נתונים קיים (מתוך `database/models.py`)

```python
@dataclass
class CodeSnippet:
    # ... שדות קיימים ...
    description: str = ""
    tags: Optional[List[str]] = None
    updated_at: Optional[datetime] = None
    # ... שאר השדות ...
```

### שאילתות DB נדרשות

#### 2.1 קבצים חסרי תיאור או תגיות

```python
# שאילתה לקבצים חסרי תיאור או תגיות
missing_metadata_query = {
    'user_id': user_id,
    'is_active': True,
    '$or': [
        {'description': {'$in': [None, '']}},
        {'tags': {'$in': [None, []]}},
        {'tags': {'$exists': False}}
    ]
}
```

#### 2.2 קבצים ישנים (לא עודכנו זמן רב)

```python
from datetime import datetime, timezone, timedelta

stale_days = 60  # ניתן להגדרה ע"י המשתמש
cutoff_date = datetime.now(timezone.utc) - timedelta(days=stale_days)

stale_files_query = {
    'user_id': user_id,
    'is_active': True,
    'updated_at': {'$lt': cutoff_date}
}
```

---

## 3. שינויים נדרשים ב-Backend

### 3.1 פונקציית עזר חדשה ב-`webapp/app.py`

הוסף את הפונקציה הבאה ליד הפונקציות הקיימות של הדשבורד (`_build_activity_timeline`, `_build_push_card`, וכו'):

```python
def _build_files_need_attention(
    db,
    user_id: int,
    max_items: int = 10,
    stale_days: int = 60,
    dismissed_ids: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    בונה נתונים עבור ווידג'ט "קבצים שדורשים טיפול".
    
    Args:
        db: חיבור למסד הנתונים
        user_id: מזהה המשתמש
        max_items: מקסימום פריטים להצגה בכל קבוצה
        stale_days: מספר ימים לאחריהם קובץ נחשב "ישן"
        dismissed_ids: רשימת מזהים שהמשתמש דחה (להסתרה זמנית)
    
    Returns:
        מילון עם נתוני הווידג'ט
    """
    from datetime import datetime, timezone, timedelta
    from database.repository import HEAVY_FIELDS_EXCLUDE_PROJECTION
    
    dismissed_ids = dismissed_ids or []
    dismissed_oids = []
    for did in dismissed_ids:
        try:
            dismissed_oids.append(ObjectId(did))
        except Exception:
            pass
    
    result = {
        'missing_metadata': [],
        'stale_files': [],
        'total_missing': 0,
        'total_stale': 0,
        'has_items': False,
        'settings': {
            'stale_days': stale_days,
            'max_items': max_items
        }
    }
    
    # === קבצים חסרי תיאור או תגיות ===
    base_query = {
        'user_id': user_id,
        'is_active': True
    }
    
    if dismissed_oids:
        base_query['_id'] = {'$nin': dismissed_oids}
    
    missing_query = dict(base_query)
    missing_query['$or'] = [
        {'description': {'$in': [None, '']}},
        {'tags': {'$in': [None, []]}},
        {'tags': {'$exists': False}}
    ]
    
    # ספירה
    result['total_missing'] = db.code_snippets.count_documents(missing_query)
    
    # שליפה עם projection קל (בלי code/content)
    projection = dict(HEAVY_FIELDS_EXCLUDE_PROJECTION)
    projection.update({
        'file_name': 1,
        'programming_language': 1,
        'description': 1,
        'tags': 1,
        'updated_at': 1,
        'created_at': 1
    })
    
    missing_docs = list(db.code_snippets.find(
        missing_query,
        projection
    ).sort('updated_at', -1).limit(max_items))
    
    for doc in missing_docs:
        reasons = []
        if not (doc.get('description') or '').strip():
            reasons.append('חסר תיאור')
        tags = doc.get('tags') or []
        if not tags:
            reasons.append('חסרות תגיות')
        
        result['missing_metadata'].append({
            'id': str(doc['_id']),
            'file_name': doc.get('file_name', ''),
            'language': doc.get('programming_language', 'text'),
            'icon': get_language_icon(doc.get('programming_language', '')),
            'description': (doc.get('description') or '')[:100],
            'tags': tags[:5],
            'updated_at': doc.get('updated_at'),
            'reasons': reasons,
            'reason_text': ' + '.join(reasons)
        })
    
    # === קבצים ישנים ===
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=stale_days)
    
    stale_query = dict(base_query)
    stale_query['updated_at'] = {'$lt': cutoff_date}
    # לא להציג קבצים שכבר נספרו כ"חסרי מטא-דאטה"
    stale_query['$and'] = [
        {'description': {'$nin': [None, '']}},
        {'tags': {'$nin': [None, []]}}
    ]
    
    result['total_stale'] = db.code_snippets.count_documents(stale_query)
    
    stale_docs = list(db.code_snippets.find(
        stale_query,
        projection
    ).sort('updated_at', 1).limit(max_items))  # הישנים קודם
    
    for doc in stale_docs:
        updated = doc.get('updated_at')
        days_ago = 0
        if updated:
            try:
                delta = datetime.now(timezone.utc) - updated
                days_ago = delta.days
            except Exception:
                days_ago = stale_days
        
        result['stale_files'].append({
            'id': str(doc['_id']),
            'file_name': doc.get('file_name', ''),
            'language': doc.get('programming_language', 'text'),
            'icon': get_language_icon(doc.get('programming_language', '')),
            'description': (doc.get('description') or '')[:100],
            'tags': (doc.get('tags') or [])[:5],
            'updated_at': updated,
            'days_ago': days_ago,
            'reason_text': f'לא עודכן {days_ago} ימים'
        })
    
    result['has_items'] = bool(result['missing_metadata'] or result['stale_files'])
    
    return result
```

### 3.2 עדכון route של `/dashboard`

בפונקציית `dashboard()` (בסביבות שורה 10048), הוסף קריאה לפונקציה החדשה:

```python
# לפני הקריאה ל-render_template:
files_need_attention = _build_files_need_attention(
    db,
    user_id,
    max_items=10,
    stale_days=60,  # TODO: לקרוא מהעדפות המשתמש
    dismissed_ids=[]  # TODO: לקרוא מ-session או DB
)

return render_template('dashboard.html',
    # ... שאר הפרמטרים הקיימים ...
    files_need_attention=files_need_attention,
)
```

### 3.3 API Endpoints חדשים

#### 3.3.1 Quick Update (עדכון מהיר של תיאור/תגיות)

```python
@app.route('/api/file/<file_id>/quick-update', methods=['POST'])
@login_required
def api_file_quick_update(file_id):
    """
    עדכון מהיר של תיאור ו/או תגיות לקובץ.
    Body: { "description": "...", "tags": ["tag1", "tag2"] }
    """
    try:
        user_id = session['user_id']
        db = get_db()
        
        try:
            oid = ObjectId(file_id)
        except Exception:
            return jsonify({'ok': False, 'error': 'מזהה לא תקין'}), 400
        
        # וידוא בעלות
        doc = db.code_snippets.find_one({
            '_id': oid,
            'user_id': user_id,
            'is_active': True
        }, {'_id': 1})
        
        if not doc:
            return jsonify({'ok': False, 'error': 'הקובץ לא נמצא'}), 404
        
        data = request.get_json() or {}
        updates = {'updated_at': datetime.now(timezone.utc)}
        
        if 'description' in data:
            desc = (data.get('description') or '').strip()[:500]
            updates['description'] = desc
        
        if 'tags' in data:
            raw_tags = data.get('tags') or []
            if isinstance(raw_tags, str):
                raw_tags = [t.strip() for t in raw_tags.split(',') if t.strip()]
            # ניקוי ונורמליזציה
            clean_tags = []
            for t in raw_tags[:20]:  # מקסימום 20 תגיות
                tag = str(t).strip().lower()[:50]
                if tag and tag not in clean_tags:
                    clean_tags.append(tag)
            updates['tags'] = clean_tags
        
        if len(updates) <= 1:  # רק updated_at
            return jsonify({'ok': False, 'error': 'לא סופקו שדות לעדכון'}), 400
        
        db.code_snippets.update_one({'_id': oid}, {'$set': updates})
        
        # Invalidate cache
        try:
            cache.invalidate_file_related(file_id, user_id)
        except Exception:
            pass
        
        return jsonify({
            'ok': True,
            'updated_fields': list(updates.keys())
        })
        
    except Exception as e:
        logger.exception(f"Error in quick update: {e}")
        return jsonify({'ok': False, 'error': 'שגיאה בעדכון'}), 500


@app.route('/api/file/<file_id>/dismiss-attention', methods=['POST'])
@login_required
def api_file_dismiss_attention(file_id):
    """
    דוחה קובץ מרשימת "דורש טיפול" (הסתרה זמנית).
    Body: { "days": 30 } - מספר ימים להסתרה (ברירת מחדל: 30)
    """
    try:
        user_id = session['user_id']
        db = get_db()
        
        try:
            oid = ObjectId(file_id)
        except Exception:
            return jsonify({'ok': False, 'error': 'מזהה לא תקין'}), 400
        
        # וידוא בעלות
        doc = db.code_snippets.find_one({
            '_id': oid,
            'user_id': user_id,
            'is_active': True
        }, {'_id': 1})
        
        if not doc:
            return jsonify({'ok': False, 'error': 'הקובץ לא נמצא'}), 404
        
        data = request.get_json() or {}
        days = min(max(int(data.get('days', 30)), 1), 365)  # 1-365 ימים
        
        expires_at = datetime.now(timezone.utc) + timedelta(days=days)
        
        # שמירה ב-collection ייעודי (או כשדה על המשתמש)
        db.attention_dismissals.update_one(
            {'user_id': user_id, 'file_id': oid},
            {
                '$set': {
                    'dismissed_at': datetime.now(timezone.utc),
                    'expires_at': expires_at
                }
            },
            upsert=True
        )
        
        return jsonify({
            'ok': True,
            'dismissed_until': expires_at.isoformat()
        })
        
    except Exception as e:
        logger.exception(f"Error in dismiss attention: {e}")
        return jsonify({'ok': False, 'error': 'שגיאה בדחייה'}), 500
```

---

## 4. שינויים ב-Frontend (HTML)

### 4.1 הוספה ל-`webapp/templates/dashboard.html`

הוסף את הקוד הבא **לפני** סגירת ה-`</div>` של `dashboard-grid` (בסביבות שורה 250):

```html
{# === ווידג'ט: קבצים שדורשים טיפול === #}
{% if files_need_attention and files_need_attention.has_items %}
<article class="glass-card attention-card widget-attention" data-attention-widget>
    <header class="attention-header">
        <h2 class="section-title">
            <i class="fas fa-exclamation-triangle"></i>
            קבצים שדורשים טיפול
        </h2>
        <span class="badge badge-warning">
            {{ files_need_attention.total_missing + files_need_attention.total_stale }}
        </span>
    </header>

    {# --- קבוצה 1: חסר תיאור/תגיות --- #}
    {% if files_need_attention.missing_metadata %}
    <section class="attention-group" data-group="missing">
        <h3 class="attention-group__title">
            <span class="attention-group__icon">📝</span>
            חסר תיאור או תגיות
            <span class="attention-group__count">({{ files_need_attention.total_missing }})</span>
        </h3>
        <ul class="attention-list" data-attention-list="missing">
            {% for file in files_need_attention.missing_metadata %}
            <li class="attention-item" data-file-id="{{ file.id }}">
                <div class="attention-item__info">
                    <span class="attention-item__icon">{{ file.icon }}</span>
                    <div class="attention-item__details">
                        <a href="/file/{{ file.id }}" class="attention-item__name">{{ file.file_name }}</a>
                        <span class="attention-item__reason">{{ file.reason_text }}</span>
                    </div>
                </div>
                <div class="attention-item__actions">
                    <button type="button" 
                            class="btn btn-sm btn-icon attention-quick-edit"
                            data-action="quick-edit"
                            data-file-id="{{ file.id }}"
                            data-current-desc="{{ file.description }}"
                            data-current-tags="{{ file.tags | join(',') }}"
                            title="עריכה מהירה">
                        <i class="fas fa-edit"></i>
                    </button>
                    <button type="button"
                            class="btn btn-sm btn-icon attention-dismiss"
                            data-action="dismiss"
                            data-file-id="{{ file.id }}"
                            title="טפל מאוחר יותר">
                        <i class="fas fa-clock"></i>
                    </button>
                </div>
            </li>
            {% endfor %}
        </ul>
        {% if files_need_attention.total_missing > files_need_attention.missing_metadata|length %}
        <p class="attention-more">
            ועוד {{ files_need_attention.total_missing - files_need_attention.missing_metadata|length }} קבצים נוספים...
        </p>
        {% endif %}
    </section>
    {% endif %}

    {# --- קבוצה 2: לא נפתח זמן רב --- #}
    {% if files_need_attention.stale_files %}
    <section class="attention-group" data-group="stale">
        <h3 class="attention-group__title">
            <span class="attention-group__icon">⏰</span>
            לא עודכן זמן רב
            <span class="attention-group__count">({{ files_need_attention.total_stale }})</span>
        </h3>
        <ul class="attention-list" data-attention-list="stale">
            {% for file in files_need_attention.stale_files %}
            <li class="attention-item" data-file-id="{{ file.id }}">
                <div class="attention-item__info">
                    <span class="attention-item__icon">{{ file.icon }}</span>
                    <div class="attention-item__details">
                        <a href="/file/{{ file.id }}" class="attention-item__name">{{ file.file_name }}</a>
                        <span class="attention-item__reason">{{ file.reason_text }}</span>
                    </div>
                </div>
                <div class="attention-item__actions">
                    <a href="/edit/{{ file.id }}" 
                       class="btn btn-sm btn-icon"
                       title="פתח לעריכה">
                        <i class="fas fa-external-link-alt"></i>
                    </a>
                    <button type="button"
                            class="btn btn-sm btn-icon attention-dismiss"
                            data-action="dismiss"
                            data-file-id="{{ file.id }}"
                            title="טפל מאוחר יותר">
                        <i class="fas fa-clock"></i>
                    </button>
                </div>
            </li>
            {% endfor %}
        </ul>
        {% if files_need_attention.total_stale > files_need_attention.stale_files|length %}
        <p class="attention-more">
            ועוד {{ files_need_attention.total_stale - files_need_attention.stale_files|length }} קבצים נוספים...
        </p>
        {% endif %}
    </section>
    {% endif %}

    {# --- הגדרות (אופציונלי) --- #}
    <footer class="attention-footer">
        <a href="/settings#attention" class="attention-settings-link">
            <i class="fas fa-cog"></i>
            הגדרות
        </a>
    </footer>
</article>

{# --- מודל עריכה מהירה (Quick Edit Modal) --- #}
<div class="modal attention-modal" id="attentionQuickEditModal" data-quick-edit-modal hidden>
    <div class="modal-backdrop" data-modal-close></div>
    <div class="modal-content glass-card">
        <header class="modal-header">
            <h3>עריכה מהירה</h3>
            <button type="button" class="modal-close" data-modal-close aria-label="סגור">
                <i class="fas fa-times"></i>
            </button>
        </header>
        <form class="modal-body" data-quick-edit-form>
            <input type="hidden" name="file_id" data-field="file_id">
            <div class="form-group">
                <label for="quickEditDescription">תיאור</label>
                <input type="text" 
                       id="quickEditDescription" 
                       name="description" 
                       class="form-field"
                       maxlength="500"
                       placeholder="תיאור קצר של הקובץ...">
            </div>
            <div class="form-group">
                <label for="quickEditTags">תגיות</label>
                <input type="text" 
                       id="quickEditTags" 
                       name="tags" 
                       class="form-field"
                       placeholder="tag1, tag2, tag3">
                <small class="form-hint">הפרד תגיות בפסיקים</small>
            </div>
        </form>
        <footer class="modal-footer">
            <button type="button" class="btn btn-secondary" data-modal-close>ביטול</button>
            <button type="button" class="btn btn-primary" data-action="save-quick-edit">
                <i class="fas fa-save"></i>
                שמור
            </button>
        </footer>
    </div>
</div>
{% endif %}
```

### 4.2 סגנונות CSS

הוסף את הסגנונות הבאים בתוך בלוק ה-`<style>` הקיים ב-`dashboard.html`:

```css
/* === Attention Widget === */
.attention-card {
    border-right: 3px solid #f59e0b;
}

.attention-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1.5rem;
}

.attention-header .section-title {
    margin: 0;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.attention-header .section-title i {
    color: #f59e0b;
}

.badge-warning {
    background: rgba(245, 158, 11, 0.2);
    color: #fbbf24;
    padding: 0.25rem 0.75rem;
    border-radius: 999px;
    font-size: 0.85rem;
    font-weight: 600;
}

.attention-group {
    margin-bottom: 1.5rem;
}

.attention-group:last-of-type {
    margin-bottom: 0.5rem;
}

.attention-group__title {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 1rem;
    font-weight: 600;
    margin-bottom: 0.75rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.attention-group__icon {
    font-size: 1.2rem;
}

.attention-group__count {
    font-weight: 400;
    opacity: 0.7;
    font-size: 0.9rem;
}

.attention-list {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
}

.attention-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.75rem;
    background: rgba(255, 255, 255, 0.03);
    border-radius: 10px;
    border: 1px solid rgba(255, 255, 255, 0.08);
    transition: all 0.2s ease;
}

.attention-item:hover {
    background: rgba(255, 255, 255, 0.06);
    border-color: rgba(245, 158, 11, 0.3);
}

.attention-item__info {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex: 1;
    min-width: 0;
}

.attention-item__icon {
    font-size: 1.5rem;
    flex-shrink: 0;
}

.attention-item__details {
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
    min-width: 0;
}

.attention-item__name {
    font-weight: 500;
    color: inherit;
    text-decoration: none;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.attention-item__name:hover {
    color: #fbbf24;
}

.attention-item__reason {
    font-size: 0.8rem;
    opacity: 0.7;
    color: #f59e0b;
}

.attention-item__actions {
    display: flex;
    gap: 0.5rem;
    flex-shrink: 0;
}

.attention-item__actions .btn {
    padding: 0.4rem 0.6rem;
    opacity: 0.7;
    transition: opacity 0.2s;
}

.attention-item:hover .attention-item__actions .btn {
    opacity: 1;
}

.attention-more {
    font-size: 0.85rem;
    opacity: 0.7;
    text-align: center;
    margin-top: 0.75rem;
}

.attention-footer {
    margin-top: 1rem;
    padding-top: 1rem;
    border-top: 1px solid rgba(255, 255, 255, 0.1);
    text-align: center;
}

.attention-settings-link {
    font-size: 0.85rem;
    color: inherit;
    opacity: 0.7;
    text-decoration: none;
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
}

.attention-settings-link:hover {
    opacity: 1;
    color: #fbbf24;
}

/* Quick Edit Modal */
.attention-modal {
    position: fixed;
    inset: 0;
    z-index: 1000;
    display: flex;
    align-items: center;
    justify-content: center;
}

.attention-modal[hidden] {
    display: none;
}

.attention-modal .modal-backdrop {
    position: absolute;
    inset: 0;
    background: rgba(0, 0, 0, 0.6);
    backdrop-filter: blur(4px);
}

.attention-modal .modal-content {
    position: relative;
    width: 90%;
    max-width: 450px;
    max-height: 90vh;
    overflow-y: auto;
    padding: 0;
}

.attention-modal .modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1rem 1.5rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.attention-modal .modal-header h3 {
    margin: 0;
    font-size: 1.1rem;
}

.attention-modal .modal-close {
    background: none;
    border: none;
    color: inherit;
    font-size: 1.2rem;
    cursor: pointer;
    opacity: 0.7;
}

.attention-modal .modal-close:hover {
    opacity: 1;
}

.attention-modal .modal-body {
    padding: 1.5rem;
}

.attention-modal .form-group {
    margin-bottom: 1rem;
}

.attention-modal .form-group:last-child {
    margin-bottom: 0;
}

.attention-modal .form-group label {
    display: block;
    margin-bottom: 0.4rem;
    font-weight: 500;
}

.attention-modal .form-hint {
    display: block;
    margin-top: 0.3rem;
    font-size: 0.8rem;
    opacity: 0.7;
}

.attention-modal .modal-footer {
    display: flex;
    justify-content: flex-end;
    gap: 0.75rem;
    padding: 1rem 1.5rem;
    border-top: 1px solid rgba(255, 255, 255, 0.1);
}

/* Rose Pine Dawn overrides */
:root[data-theme="rose-pine-dawn"] .attention-card {
    border-right-color: #ea9d34;
}

:root[data-theme="rose-pine-dawn"] .attention-header .section-title i {
    color: #ea9d34;
}

:root[data-theme="rose-pine-dawn"] .badge-warning {
    background: rgba(234, 157, 52, 0.15);
    color: #ea9d34;
}

:root[data-theme="rose-pine-dawn"] .attention-item {
    background: rgba(255, 255, 255, 0.4);
    border-color: rgba(87, 82, 121, 0.15);
}

:root[data-theme="rose-pine-dawn"] .attention-item:hover {
    background: rgba(255, 255, 255, 0.5);
    border-color: rgba(234, 157, 52, 0.4);
}

:root[data-theme="rose-pine-dawn"] .attention-item__reason {
    color: #ea9d34;
}

:root[data-theme="rose-pine-dawn"] .attention-item__name:hover,
:root[data-theme="rose-pine-dawn"] .attention-settings-link:hover {
    color: #ea9d34;
}

/* Animation for item removal */
.attention-item.is-removing {
    opacity: 0;
    transform: translateX(-10px);
    transition: opacity 0.3s, transform 0.3s;
}

/* Grid placement */
.widget-attention {
    grid-area: attention;
}

@media (min-width: 769px) {
    .dashboard-grid.has-attention {
        grid-template-areas:
            "pinned whatsnew lastcommit"
            "attention attention attention";
    }
    
    .dashboard-grid.no-last-commit.has-attention {
        grid-template-areas:
            "pinned whatsnew languages-top"
            "attention attention attention";
    }
}

@media (max-width: 768px) {
    .attention-item {
        flex-direction: column;
        align-items: flex-start;
        gap: 0.75rem;
    }
    
    .attention-item__actions {
        width: 100%;
        justify-content: flex-end;
    }
}
```

### 4.3 JavaScript

הוסף את הקוד הבא בסוף בלוק ה-`<script>` ב-`dashboard.html`:

```javascript
// === Attention Widget: Quick Edit & Dismiss ===
document.addEventListener('DOMContentLoaded', () => {
    const widget = document.querySelector('[data-attention-widget]');
    if (!widget) return;

    const modal = document.getElementById('attentionQuickEditModal');
    const form = modal?.querySelector('[data-quick-edit-form]');
    const saveBtn = modal?.querySelector('[data-action="save-quick-edit"]');

    // פתיחת מודל עריכה מהירה
    widget.addEventListener('click', (e) => {
        const editBtn = e.target.closest('[data-action="quick-edit"]');
        if (editBtn && modal && form) {
            const fileId = editBtn.dataset.fileId;
            const currentDesc = editBtn.dataset.currentDesc || '';
            const currentTags = editBtn.dataset.currentTags || '';

            form.querySelector('[data-field="file_id"]').value = fileId;
            form.querySelector('#quickEditDescription').value = currentDesc;
            form.querySelector('#quickEditTags').value = currentTags;

            modal.hidden = false;
            form.querySelector('#quickEditDescription').focus();
        }
    });

    // סגירת מודל
    modal?.querySelectorAll('[data-modal-close]').forEach(btn => {
        btn.addEventListener('click', () => {
            modal.hidden = true;
        });
    });

    // שמירה מהירה
    saveBtn?.addEventListener('click', async () => {
        if (!form) return;

        const fileId = form.querySelector('[data-field="file_id"]').value;
        const description = form.querySelector('#quickEditDescription').value.trim();
        const tagsRaw = form.querySelector('#quickEditTags').value.trim();
        const tags = tagsRaw ? tagsRaw.split(',').map(t => t.trim()).filter(Boolean) : [];

        saveBtn.disabled = true;
        saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> שומר...';

        try {
            const resp = await fetch(`/api/file/${fileId}/quick-update`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ description, tags })
            });
            const data = await resp.json();

            if (!resp.ok || !data.ok) {
                throw new Error(data.error || 'שגיאה בשמירה');
            }

            // הסרת הפריט מהרשימה
            removeAttentionItem(fileId);
            modal.hidden = true;

            // הודעת הצלחה
            showToast('נשמר בהצלחה!', 'success');

        } catch (err) {
            console.error('Quick update failed:', err);
            showToast(err.message || 'שגיאה בשמירה', 'error');
        } finally {
            saveBtn.disabled = false;
            saveBtn.innerHTML = '<i class="fas fa-save"></i> שמור';
        }
    });

    // דחייה (Dismiss)
    widget.addEventListener('click', async (e) => {
        const dismissBtn = e.target.closest('[data-action="dismiss"]');
        if (!dismissBtn) return;

        const fileId = dismissBtn.dataset.fileId;
        const days = 30; // ברירת מחדל

        dismissBtn.disabled = true;
        dismissBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

        try {
            const resp = await fetch(`/api/file/${fileId}/dismiss-attention`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ days })
            });
            const data = await resp.json();

            if (!resp.ok || !data.ok) {
                throw new Error(data.error || 'שגיאה בדחייה');
            }

            removeAttentionItem(fileId);
            showToast('נדחה ל-30 ימים', 'info');

        } catch (err) {
            console.error('Dismiss failed:', err);
            showToast(err.message || 'שגיאה בדחייה', 'error');
            dismissBtn.disabled = false;
            dismissBtn.innerHTML = '<i class="fas fa-clock"></i>';
        }
    });

    function removeAttentionItem(fileId) {
        const item = widget.querySelector(`.attention-item[data-file-id="${fileId}"]`);
        if (item) {
            item.classList.add('is-removing');
            setTimeout(() => {
                item.remove();
                updateCounts();
            }, 300);
        }
    }

    function updateCounts() {
        // עדכון ספירות
        widget.querySelectorAll('[data-attention-list]').forEach(list => {
            const group = list.closest('.attention-group');
            const countEl = group?.querySelector('.attention-group__count');
            const items = list.querySelectorAll('.attention-item:not(.is-removing)');
            
            if (countEl) {
                countEl.textContent = `(${items.length})`;
            }
            
            // הסתר קבוצה ריקה
            if (items.length === 0 && group) {
                group.style.display = 'none';
            }
        });

        // עדכון badge בכותרת
        const totalBadge = widget.querySelector('.attention-header .badge');
        const allItems = widget.querySelectorAll('.attention-item:not(.is-removing)');
        if (totalBadge) {
            totalBadge.textContent = allItems.length;
        }

        // הסתר את כל הווידג'ט אם אין פריטים
        if (allItems.length === 0) {
            widget.style.display = 'none';
        }
    }

    function showToast(message, type = 'info') {
        // שימוש במערכת Toast קיימת אם יש, אחרת fallback
        if (typeof window.showNotification === 'function') {
            window.showNotification(message, type);
        } else {
            console.log(`[${type}] ${message}`);
        }
    }
});
```

---

## 5. הגדרות משתמש (אופציונלי)

### 5.1 שדות הגדרה חדשים

ניתן להוסיף לעמוד ההגדרות (`/settings`) סעיף חדש:

```python
# ב-user preferences / settings:
attention_settings = {
    'enabled': True,                    # הפעלה/כיבוי הווידג'ט
    'stale_days': 60,                   # מספר ימים לקובץ "ישן"
    'max_items_per_group': 10,          # מקסימום פריטים לכל קבוצה
    'show_missing_description': True,   # הצג קבצים חסרי תיאור
    'show_missing_tags': True,          # הצג קבצים חסרי תגיות
    'show_stale_files': True            # הצג קבצים ישנים
}
```

### 5.2 API לעדכון הגדרות

```python
@app.route('/api/settings/attention', methods=['PUT'])
@login_required
def api_update_attention_settings():
    """עדכון הגדרות ווידג'ט 'קבצים שדורשים טיפול'"""
    user_id = session['user_id']
    data = request.get_json() or {}
    
    allowed_fields = {
        'enabled', 'stale_days', 'max_items_per_group',
        'show_missing_description', 'show_missing_tags', 'show_stale_files'
    }
    
    updates = {}
    for field in allowed_fields:
        if field in data:
            value = data[field]
            if field == 'stale_days':
                value = min(max(int(value), 7), 365)
            elif field == 'max_items_per_group':
                value = min(max(int(value), 3), 50)
            elif field in ('enabled', 'show_missing_description', 'show_missing_tags', 'show_stale_files'):
                value = bool(value)
            updates[f'attention_settings.{field}'] = value
    
    if updates:
        db = get_db()
        db.user_preferences.update_one(
            {'user_id': user_id},
            {'$set': updates},
            upsert=True
        )
    
    return jsonify({'ok': True})
```

---

## 6. אינדקסים מומלצים (MongoDB)

הוסף את האינדקסים הבאים לשיפור ביצועים:

```python
# ב-scripts/create_repo_indexes.py או בסקריפט אתחול

# אינדקס לשאילתת קבצים חסרי מטא-דאטה
db.code_snippets.create_index(
    [
        ('user_id', 1),
        ('is_active', 1),
        ('description', 1),
        ('tags', 1)
    ],
    name='idx_attention_missing_metadata'
)

# אינדקס לשאילתת קבצים ישנים
db.code_snippets.create_index(
    [
        ('user_id', 1),
        ('is_active', 1),
        ('updated_at', 1)
    ],
    name='idx_attention_stale_files'
)

# אינדקס ל-dismissals
db.attention_dismissals.create_index(
    [
        ('user_id', 1),
        ('file_id', 1)
    ],
    unique=True,
    name='idx_attention_dismissals_unique'
)

db.attention_dismissals.create_index(
    [('expires_at', 1)],
    expireAfterSeconds=0,  # TTL index - מחיקה אוטומטית כש-expires_at עובר
    name='idx_attention_dismissals_ttl'
)
```

---

## 7. זרימת עבודה לדוגמה

1. **משתמש נכנס לדשבורד** → רואה 5 קבצים "חסרי תיאור/תגיות"
2. **לוחץ על כפתור העריכה המהירה** (עיפרון) → נפתח מודל
3. **מוסיף תיאור קצר** → לוחץ "שמור"
4. **הקובץ נעלם מהרשימה** → התצוגה מתעדכנת בזמן אמת
5. **לוחץ על כפתור "שעון"** על קובץ אחר → הקובץ נדחה ל-30 ימים
6. **ממשיך לקובץ הבא** — הכל בלי לעזוב את הדשבורד

---

## 8. סיכום שינויים נדרשים

| קובץ | סוג שינוי | תיאור |
|------|-----------|--------|
| `webapp/app.py` | פונקציה חדשה | `_build_files_need_attention()` |
| `webapp/app.py` | עדכון route | `/dashboard` - הוספת נתוני הווידג'ט |
| `webapp/app.py` | API חדש | `/api/file/<id>/quick-update` |
| `webapp/app.py` | API חדש | `/api/file/<id>/dismiss-attention` |
| `webapp/templates/dashboard.html` | HTML חדש | תבנית הווידג'ט + מודל |
| `webapp/templates/dashboard.html` | CSS חדש | סגנונות לווידג'ט |
| `webapp/templates/dashboard.html` | JS חדש | לוגיקת Quick Edit + Dismiss |
| MongoDB | אינדקסים | 3 אינדקסים חדשים |
| MongoDB | Collection חדש | `attention_dismissals` |

---

## 9. הערות נוספות

### שיקולי ביצועים
- השאילתות משתמשות ב-`HEAVY_FIELDS_EXCLUDE_PROJECTION` כדי לא לשלוף את תוכן הקבצים
- מומלץ להגביל את מספר הפריטים ל-10-15 לכל קבוצה
- ה-TTL index על `attention_dismissals` מנקה אוטומטית רשומות שפג תוקפן

### נגישות
- כל הכפתורים כוללים `title` ו-`aria-label`
- המודל ניתן לסגירה עם ESC
- תמיכה בניווט מקלדת

### Mobile
- הווידג'ט responsive ומותאם למסכים קטנים
- בגרסת mobile הכפתורים מוצגים בשורה נפרדת

---

*מסמך זה נוצר ב-19/01/2026 ומותאם לארכיטקטורה הקיימת של CodeBot.*
