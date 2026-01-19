# מדריך מימוש: ווידג'ט "קבצים שדורשים טיפול" בדשבורד (v2)

> **מטרה:** ווידג'ט בדשבורד שמרכז קבצים "בעייתיים" (חסרי תיאור/תגיות, או לא עודכנו זמן רב) עם אפשרות לתיקון מהיר ישירות מהדשבורד.
>
> **גרסה:** 2.0 | **עדכון אחרון:** 19/01/2026

---

## 1. סקירה כללית

### מה הווידג'ט עושה
- **מרכז קבצים שדורשים טיפול** בכרטיס אחד בדשבורד
- **מחולק לשתי קבוצות בלתי-חופפות:**
  1. **"חסר תיאור/תגיות"** — קבצים שאין להם `description` או שרשימת ה-`tags` ריקה/חסרה
  2. **"לא עודכן זמן רב"** — קבצים שה-`updated_at` שלהם ישן מ-X ימים (ברירת מחדל: 60), **ויש להם מטא-דאטה תקין**
- **מציע תיקון מהיר (Quick Fix):**
  - הוספת תיאור inline
  - הוספת תגיות (קלט טקסט מופרד בפסיקים)
  - פתיחה לעריכה מלאה
  - דחייה/הסתרה זמנית ("טפל מאוחר יותר")

### למה זה שימושי
- מצמצם "זיהום" של קבצים לא מתועדים
- עוזר לזכור קבצים שננטשו בלי לפתוח חיפוש ידני
- מקצר זמן: תיקון קטן (תיאור/תגיות) בלחיצה אחת

### הבהרה חשובה: "לא עודכן" vs "לא נפתח"
הווידג'ט מבוסס על שדה `updated_at` (מתי הקובץ נשמר/עודכן לאחרונה).
**אין לנו כרגע שדה `last_viewed_at`**, ולכן המונח הנכון הוא **"לא עודכן זמן רב"** ולא "לא נפתח".
אם בעתיד נרצה לעקוב אחרי צפיות, יש להוסיף שדה נפרד ולעדכן אותו ב-route `/file/<id>`.

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

### עיקרון מפתח: הפרדה לוגית מוחלטת בין הקבוצות

| קבוצה | תנאי הכללה | תנאי החרגה |
|-------|------------|------------|
| **חסר מטא-דאטה** | `description` ריק/חסר **או** `tags` ריק/חסר | - |
| **לא עודכן זמן רב** | `updated_at` < cutoff | קובץ שנמצא בקבוצה 1 (חסר מטא-דאטה) |

**המטרה:** קובץ יכול להופיע **רק בקבוצה אחת**.

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
        stale_days: מספר ימים לאחריהם קובץ נחשב "לא עודכן זמן רב"
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
        'shown_missing': 0,
        'shown_stale': 0,
        'has_items': False,
        'settings': {
            'stale_days': stale_days,
            'max_items': max_items
        }
    }
    
    # === בסיס שאילתה משותף ===
    base_query: Dict[str, Any] = {
        'user_id': user_id,
        'is_active': True
    }
    
    if dismissed_oids:
        base_query['_id'] = {'$nin': dismissed_oids}
    
    # === Projection קל (בלי code/content) ===
    projection = dict(HEAVY_FIELDS_EXCLUDE_PROJECTION)
    projection.update({
        'file_name': 1,
        'programming_language': 1,
        'description': 1,
        'tags': 1,
        'updated_at': 1,
        'created_at': 1
    })
    
    # =====================================================
    # קבוצה 1: קבצים חסרי תיאור או תגיות
    # =====================================================
    # תנאי: description ריק/חסר או tags ריק/חסר
    missing_query = dict(base_query)
    missing_query['$or'] = [
        # תיאור חסר או ריק
        {'description': {'$exists': False}},
        {'description': None},
        {'description': ''},
        # תגיות חסרות או ריקות
        {'tags': {'$exists': False}},
        {'tags': None},
        {'tags': []},
    ]
    
    # ספירה כוללת
    result['total_missing'] = db.code_snippets.count_documents(missing_query)
    
    # שליפה מוגבלת
    missing_docs = list(db.code_snippets.find(
        missing_query,
        projection
    ).sort('updated_at', -1).limit(max_items))
    
    result['shown_missing'] = len(missing_docs)
    
    for doc in missing_docs:
        reasons = []
        desc = (doc.get('description') or '').strip()
        tags = doc.get('tags') or []
        
        if not desc:
            reasons.append('חסר תיאור')
        if not tags:
            reasons.append('חסרות תגיות')
        
        result['missing_metadata'].append({
            'id': str(doc['_id']),
            'file_name': doc.get('file_name', ''),
            'language': doc.get('programming_language', 'text'),
            'icon': get_language_icon(doc.get('programming_language', '')),
            'description': desc[:100],
            'tags': tags[:5],  # לתצוגה ברשימה בלבד
            'tags_full': tags,  # כל התגיות - לשימוש ב-quick edit
            'tags_count': len(tags),
            'updated_at': doc.get('updated_at'),
            'reasons': reasons,
            'reason_text': ' + '.join(reasons) if reasons else 'חסר מידע'
        })
    
    # =====================================================
    # קבוצה 2: קבצים שלא עודכנו זמן רב
    # =====================================================
    # תנאי מפתח: רק קבצים עם מטא-דאטה תקין!
    # קובץ נחשב "stale" רק אם:
    #   - updated_at ישן
    #   - description קיים ולא ריק
    #   - tags קיים ויש בו לפחות איבר אחד
    
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=stale_days)
    
    stale_query = dict(base_query)
    stale_query['updated_at'] = {'$lt': cutoff_date}
    
    # החרגה מפורשת של קבצים חסרי מטא-דאטה
    # שימוש ב-$and כדי לוודא שגם description וגם tags תקינים
    stale_query['$and'] = [
        # description קיים ולא ריק
        {'description': {'$exists': True}},
        {'description': {'$ne': None}},
        {'description': {'$ne': ''}},
        # tags קיים ויש לפחות איבר אחד (pattern מומלץ למונגו)
        {'tags.0': {'$exists': True}}
    ]
    
    # ספירה כוללת
    result['total_stale'] = db.code_snippets.count_documents(stale_query)
    
    # שליפה מוגבלת - הישנים קודם
    stale_docs = list(db.code_snippets.find(
        stale_query,
        projection
    ).sort('updated_at', 1).limit(max_items))
    
    result['shown_stale'] = len(stale_docs)
    
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

### 3.2 פונקציית עזר לשליפת Dismissals

```python
def _get_active_dismissals(db, user_id: int) -> List[str]:
    """
    שולף את רשימת ה-file_ids שהמשתמש דחה ועדיין לא פגו.
    
    Returns:
        רשימת מזהי קבצים (כ-strings)
    """
    from datetime import datetime, timezone
    
    now = datetime.now(timezone.utc)
    
    try:
        # שליפת כל הדחיות שעדיין בתוקף
        dismissals = db.attention_dismissals.find(
            {
                'user_id': user_id,
                'expires_at': {'$gt': now}
            },
            {'file_id': 1}
        )
        
        return [str(d['file_id']) for d in dismissals if d.get('file_id')]
    except Exception as e:
        logger.warning(f"Failed to get dismissals for user {user_id}: {e}")
        return []
```

### 3.3 עדכון route של `/dashboard`

בפונקציית `dashboard()` (בסביבות שורה 10048), הוסף קריאה לפונקציות החדשות:

```python
# === ווידג'ט: קבצים שדורשים טיפול ===
# שליפת דחיות פעילות
dismissed_ids = _get_active_dismissals(db, user_id)

# בניית נתוני הווידג'ט
files_need_attention = _build_files_need_attention(
    db,
    user_id,
    max_items=10,
    stale_days=60,  # ניתן לקרוא מהעדפות המשתמש בעתיד
    dismissed_ids=dismissed_ids
)

return render_template('dashboard.html',
    # ... שאר הפרמטרים הקיימים ...
    files_need_attention=files_need_attention,
)
```

### 3.4 API Endpoints חדשים

#### 3.4.1 Quick Update (עדכון מהיר של תיאור/תגיות)

```python
@app.route('/api/file/<file_id>/quick-update', methods=['POST'])
@login_required
def api_file_quick_update(file_id):
    """
    עדכון מהיר של תיאור ו/או תגיות לקובץ.
    Body: { "description": "...", "tags": ["tag1", "tag2"] }
    
    הערה: עדכון מוצלח גם מעדכן את updated_at, מה שיגרום לקובץ
    לצאת מרשימת "לא עודכן זמן רב" (וזו התנהגות רצויה).
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
                # תמיכה בקלט comma-separated
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
    
    אפשרויות מומלצות: 7, 30, 90 ימים.
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
        
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=days)
        
        # שמירה ב-collection ייעודי
        db.attention_dismissals.update_one(
            {'user_id': user_id, 'file_id': oid},
            {
                '$set': {
                    'dismissed_at': now,
                    'expires_at': expires_at,
                    'days': days
                }
            },
            upsert=True
        )
        
        return jsonify({
            'ok': True,
            'dismissed_until': expires_at.isoformat(),
            'days': days
        })
        
    except Exception as e:
        logger.exception(f"Error in dismiss attention: {e}")
        return jsonify({'ok': False, 'error': 'שגיאה בדחייה'}), 500
```

---

## 4. שינויים ב-Frontend (HTML)

### 4.1 הוספה ל-`webapp/templates/dashboard.html`

הוסף את הקוד הבא **לפני** סגירת ה-`</div>` של `dashboard-grid` (בסביבות שורה 250):

**שים לב:** שימוש ב-`tojson` עבור ערכי `data-*` למניעת בעיות escaping.

```html
{# === ווידג'ט: קבצים שדורשים טיפול === #}
{% if files_need_attention and files_need_attention.has_items %}
<article class="glass-card attention-card widget-attention" data-attention-widget>
    <header class="attention-header">
        <h2 class="section-title">
            <i class="fas fa-exclamation-triangle"></i>
            קבצים שדורשים טיפול
        </h2>
        <span class="badge badge-warning" data-attention-total-badge>
            {{ files_need_attention.total_missing + files_need_attention.total_stale }}
        </span>
    </header>

    {# --- קבוצה 1: חסר תיאור/תגיות --- #}
    {% if files_need_attention.missing_metadata %}
    <section class="attention-group" data-group="missing">
        <h3 class="attention-group__title">
            <span class="attention-group__icon">📝</span>
            חסר תיאור או תגיות
            <span class="attention-group__count" data-group-count="missing">
                ({{ files_need_attention.shown_missing }}{% if files_need_attention.total_missing > files_need_attention.shown_missing %}/{{ files_need_attention.total_missing }}{% endif %})
            </span>
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
                            data-file-name="{{ file.file_name | e }}"
                            data-current-desc={{ file.description | tojson }}
                            data-current-tags={{ (file.tags_full | join(',')) | tojson }}
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
        {% if files_need_attention.total_missing > files_need_attention.shown_missing %}
        <p class="attention-more">
            ועוד {{ files_need_attention.total_missing - files_need_attention.shown_missing }} קבצים נוספים...
            <a href="/files?filter=missing_metadata" class="attention-more-link">הצג הכל</a>
        </p>
        {% endif %}
    </section>
    {% endif %}

    {# --- קבוצה 2: לא עודכן זמן רב --- #}
    {% if files_need_attention.stale_files %}
    <section class="attention-group" data-group="stale">
        <h3 class="attention-group__title">
            <span class="attention-group__icon">⏰</span>
            לא עודכן זמן רב
            <span class="attention-group__count" data-group-count="stale">
                ({{ files_need_attention.shown_stale }}{% if files_need_attention.total_stale > files_need_attention.shown_stale %}/{{ files_need_attention.total_stale }}{% endif %})
            </span>
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
        {% if files_need_attention.total_stale > files_need_attention.shown_stale %}
        <p class="attention-more">
            ועוד {{ files_need_attention.total_stale - files_need_attention.shown_stale }} קבצים נוספים...
            <a href="/files?filter=stale&days={{ files_need_attention.settings.stale_days }}" class="attention-more-link">הצג הכל</a>
        </p>
        {% endif %}
    </section>
    {% endif %}

    {# --- הגדרות --- #}
    <footer class="attention-footer">
        <span class="attention-footer-hint">
            ⚙️ קובץ נחשב "ישן" אחרי {{ files_need_attention.settings.stale_days }} ימים
        </span>
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
            <p class="quick-edit-file-name" data-field="file_name_display"></p>
            <div class="form-group">
                <label for="quickEditDescription">תיאור</label>
                <input type="text" 
                       id="quickEditDescription" 
                       name="description" 
                       class="form-field"
                       maxlength="500"
                       placeholder="מה הקובץ עושה? (תיאור קצר)">
            </div>
            <div class="form-group">
                <label for="quickEditTags">תגיות</label>
                <input type="text" 
                       id="quickEditTags" 
                       name="tags" 
                       class="form-field"
                       placeholder="utils, helper, api">
                <small class="form-hint">הפרד תגיות בפסיקים (Comma-separated)</small>
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

{# --- מודל דחייה (Dismiss Modal) --- #}
<div class="modal attention-modal" id="attentionDismissModal" data-dismiss-modal hidden>
    <div class="modal-backdrop" data-modal-close></div>
    <div class="modal-content glass-card modal-content--small">
        <header class="modal-header">
            <h3>דחה לטיפול מאוחר</h3>
            <button type="button" class="modal-close" data-modal-close aria-label="סגור">
                <i class="fas fa-times"></i>
            </button>
        </header>
        <div class="modal-body">
            <input type="hidden" data-field="dismiss_file_id">
            <p>הסתר קובץ זה מהרשימה למשך:</p>
            <div class="dismiss-options">
                <button type="button" class="btn btn-secondary dismiss-option" data-days="7">שבוע</button>
                <button type="button" class="btn btn-secondary dismiss-option" data-days="30">חודש</button>
                <button type="button" class="btn btn-secondary dismiss-option" data-days="90">3 חודשים</button>
            </div>
        </div>
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

.attention-more-link {
    color: #fbbf24;
    margin-right: 0.5rem;
}

.attention-footer {
    margin-top: 1rem;
    padding-top: 1rem;
    border-top: 1px solid rgba(255, 255, 255, 0.1);
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.5rem;
}

.attention-footer-hint {
    font-size: 0.8rem;
    opacity: 0.6;
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

.attention-modal .modal-content--small {
    max-width: 320px;
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

.quick-edit-file-name {
    font-weight: 600;
    margin: 0 0 1rem;
    padding-bottom: 0.75rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    font-family: monospace;
}

/* Dismiss Modal */
.dismiss-options {
    display: flex;
    gap: 0.75rem;
    margin-top: 1rem;
}

.dismiss-option {
    flex: 1;
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
:root[data-theme="rose-pine-dawn"] .attention-settings-link:hover,
:root[data-theme="rose-pine-dawn"] .attention-more-link {
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
    
    .dismiss-options {
        flex-direction: column;
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

    const quickEditModal = document.getElementById('attentionQuickEditModal');
    const dismissModal = document.getElementById('attentionDismissModal');
    const quickEditForm = quickEditModal?.querySelector('[data-quick-edit-form]');
    const saveBtn = quickEditModal?.querySelector('[data-action="save-quick-edit"]');

    // === פתיחת מודל עריכה מהירה ===
    // משתנים לשמירת הערכים המקוריים (למניעת איבוד נתונים)
    // חשוב: אם המשתמש לא שינה שדה, לא נשלח אותו לשרת
    let originalDescription = '';
    let originalTags = '';

    widget.addEventListener('click', (e) => {
        const editBtn = e.target.closest('[data-action="quick-edit"]');
        if (editBtn && quickEditModal && quickEditForm) {
            const fileId = editBtn.dataset.fileId;
            const fileName = editBtn.dataset.fileName || '';
            // הערכים מגיעים כ-JSON escaped, צריך לפרסר
            let currentDesc = '';
            let currentTags = '';
            try {
                currentDesc = JSON.parse(editBtn.dataset.currentDesc || '""');
            } catch { currentDesc = ''; }
            try {
                // כאן מגיעות כל התגיות (tags_full), לא רק 5 הראשונות
                currentTags = JSON.parse(editBtn.dataset.currentTags || '""');
            } catch { currentTags = ''; }

            // שמירת הערכים המקוריים להשוואה בעת שמירה
            originalDescription = currentDesc;
            originalTags = currentTags;

            quickEditForm.querySelector('[data-field="file_id"]').value = fileId;
            quickEditForm.querySelector('[data-field="file_name_display"]').textContent = fileName;
            quickEditForm.querySelector('#quickEditDescription').value = currentDesc;
            quickEditForm.querySelector('#quickEditTags').value = currentTags;

            quickEditModal.hidden = false;
            quickEditForm.querySelector('#quickEditDescription').focus();
        }
    });

    // === סגירת מודלים ===
    [quickEditModal, dismissModal].forEach(modal => {
        modal?.querySelectorAll('[data-modal-close]').forEach(btn => {
            btn.addEventListener('click', () => {
                modal.hidden = true;
            });
        });
    });

    // === ESC לסגירת מודלים ===
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            if (quickEditModal && !quickEditModal.hidden) quickEditModal.hidden = true;
            if (dismissModal && !dismissModal.hidden) dismissModal.hidden = true;
        }
    });

    // === שמירה מהירה ===
    saveBtn?.addEventListener('click', async () => {
        if (!quickEditForm) return;

        const fileId = quickEditForm.querySelector('[data-field="file_id"]').value;
        const newDescription = quickEditForm.querySelector('#quickEditDescription').value.trim();
        const newTagsRaw = quickEditForm.querySelector('#quickEditTags').value.trim();

        // בניית payload - שולחים רק שדות שהשתנו!
        // זה מונע איבוד נתונים (למשל תגיות שלא הוצגו במלואן)
        const payload = {};
        
        if (newDescription !== originalDescription) {
            payload.description = newDescription;
        }
        
        if (newTagsRaw !== originalTags) {
            payload.tags = newTagsRaw ? newTagsRaw.split(',').map(t => t.trim()).filter(Boolean) : [];
        }

        // אם לא השתנה כלום, אין מה לשמור
        if (Object.keys(payload).length === 0) {
            quickEditModal.hidden = true;
            showToast('לא בוצעו שינויים', 'info');
            return;
        }

        saveBtn.disabled = true;
        saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> שומר...';

        try {
            const resp = await fetch(`/api/file/${fileId}/quick-update`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await resp.json();

            if (!resp.ok || !data.ok) {
                throw new Error(data.error || 'שגיאה בשמירה');
            }

            // הסרת הפריט מהרשימה (ויזואלית)
            removeAttentionItem(fileId);
            quickEditModal.hidden = true;

            showToast('נשמר בהצלחה!', 'success');

        } catch (err) {
            console.error('Quick update failed:', err);
            showToast(err.message || 'שגיאה בשמירה', 'error');
        } finally {
            saveBtn.disabled = false;
            saveBtn.innerHTML = '<i class="fas fa-save"></i> שמור';
        }
    });

    // === פתיחת מודל דחייה ===
    widget.addEventListener('click', (e) => {
        const dismissBtn = e.target.closest('[data-action="dismiss"]');
        if (!dismissBtn || !dismissModal) return;

        const fileId = dismissBtn.dataset.fileId;
        dismissModal.querySelector('[data-field="dismiss_file_id"]').value = fileId;
        dismissModal.hidden = false;
    });

    // === בחירת תקופת דחייה ===
    dismissModal?.querySelectorAll('.dismiss-option[data-days]').forEach(btn => {
        btn.addEventListener('click', async () => {
            const fileId = dismissModal.querySelector('[data-field="dismiss_file_id"]').value;
            const days = parseInt(btn.dataset.days, 10) || 30;

            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

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
                dismissModal.hidden = true;
                
                const daysText = days === 7 ? 'שבוע' : days === 30 ? 'חודש' : `${days} ימים`;
                showToast(`נדחה ל-${daysText}`, 'info');

            } catch (err) {
                console.error('Dismiss failed:', err);
                showToast(err.message || 'שגיאה בדחייה', 'error');
            } finally {
                btn.disabled = false;
                // Reset button text based on days
                const daysMap = { 7: 'שבוע', 30: 'חודש', 90: '3 חודשים' };
                btn.textContent = daysMap[btn.dataset.days] || `${btn.dataset.days} ימים`;
            }
        });
    });

    /**
     * הסרת פריט מהרשימה (ויזואלית בלבד).
     * 
     * הערה חשובה: הספירות (total) שמגיעות מהשרת לא מתעדכנות כאן.
     * ה-Badge הכולל מופחת ויזואלית, אבל הספירות בכותרות הקבוצות
     * נשארות כפי שהיו (או מציגות "מוצגים X מתוך Y").
     * לסנכרון מלא יש לרענן את הדף.
     */
    function removeAttentionItem(fileId) {
        const item = widget.querySelector(`.attention-item[data-file-id="${fileId}"]`);
        if (item) {
            item.classList.add('is-removing');
            setTimeout(() => {
                item.remove();
                updateVisualCounts();
            }, 300);
        }
    }

    /**
     * עדכון ספירות ויזואלי בלבד.
     * מעדכן את ה-Badge הכולל בהתבסס על מספר הפריטים שנותרו ב-DOM.
     * הספירות בכותרות הקבוצות לא משתנות (כי הן מציגות total מהשרת).
     */
    function updateVisualCounts() {
        const allItems = widget.querySelectorAll('.attention-item:not(.is-removing)');
        const totalBadge = widget.querySelector('[data-attention-total-badge]');
        
        if (totalBadge) {
            totalBadge.textContent = allItems.length;
        }

        // הסתר קבוצה ריקה
        widget.querySelectorAll('[data-attention-list]').forEach(list => {
            const group = list.closest('.attention-group');
            const items = list.querySelectorAll('.attention-item:not(.is-removing)');
            
            if (items.length === 0 && group) {
                group.style.display = 'none';
            }
        });

        // הסתר את כל הווידג'ט אם אין פריטים
        if (allItems.length === 0) {
            widget.style.display = 'none';
        }
    }

    function showToast(message, type = 'info') {
        // שימוש במערכת Toast קיימת אם יש
        if (typeof window.showNotification === 'function') {
            window.showNotification(message, type);
        } else if (typeof window.Toastify === 'function') {
            Toastify({
                text: message,
                duration: 3000,
                gravity: 'bottom',
                position: 'right',
                className: `toast-${type}`
            }).showToast();
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
    'stale_days': 60,                   # מספר ימים לקובץ "לא עודכן"
    'max_items_per_group': 10,          # מקסימום פריטים לכל קבוצה
    'show_missing_description': True,   # הצג קבצים חסרי תיאור
    'show_missing_tags': True,          # הצג קבצים חסרי תגיות
    'show_stale_files': True            # הצג קבצים שלא עודכנו
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
# הערה: אינדקס על שדות אופציונליים עם $or לא תמיד יעיל.
# מומלץ לבדוק עם explain() ולשקול הוספת שדה מחושב בעתיד.
db.code_snippets.create_index(
    [
        ('user_id', 1),
        ('is_active', 1),
        ('updated_at', -1)
    ],
    name='idx_attention_base'
)

# אינדקס לשאילתת קבצים שלא עודכנו (כולל תנאי tags.0)
db.code_snippets.create_index(
    [
        ('user_id', 1),
        ('is_active', 1),
        ('updated_at', 1),
        ('tags.0', 1)
    ],
    name='idx_attention_stale_with_tags'
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

# TTL index - מחיקה אוטומטית כש-expires_at עובר
db.attention_dismissals.create_index(
    [('expires_at', 1)],
    expireAfterSeconds=0,
    name='idx_attention_dismissals_ttl'
)
```

### הערה לגבי ביצועי שאילתות

השאילתה של `missing_metadata` משתמשת ב-`$or` על שדות אופציונליים, מה שלא תמיד מנצל אינדקסים ביעילות.

**אופציה לשיפור עתידי:** הוספת שדה מחושב `has_complete_metadata: true/false` שמתעדכן בעת שמירה:

```python
# בזמן save/update של קובץ:
has_complete_metadata = bool(
    (doc.get('description') or '').strip() and 
    (doc.get('tags') or [])
)
doc['has_complete_metadata'] = has_complete_metadata
```

אז השאילתה הופכת לפשוטה:
```python
{'has_complete_metadata': False}  # קבצים חסרי מטא-דאטה
{'has_complete_metadata': True, 'updated_at': {'$lt': cutoff}}  # קבצים ישנים
```

---

## 7. זרימת עבודה לדוגמה

1. **משתמש נכנס לדשבורד** → רואה כרטיס "קבצים שדורשים טיפול"
2. **רואה 3 קבצים "חסרי תיאור/תגיות"** ו-2 קבצים "לא עודכנו זמן רב"
3. **לוחץ על כפתור העריכה המהירה** (עיפרון) על קובץ חסר תיאור
4. **נפתח מודל** → מוסיף תיאור ותגיות → לוחץ "שמור"
5. **הקובץ נעלם מהרשימה** → ה-Badge יורד ב-1
6. **לוחץ על כפתור "שעון"** על קובץ אחר → נפתח מודל בחירת תקופה
7. **בוחר "חודש"** → הקובץ נדחה ל-30 ימים ונעלם מהרשימה
8. **ממשיך לקובץ הבא** — הכל בלי לעזוב את הדשבורד

---

## 8. סיכום שינויים נדרשים

| קובץ | סוג שינוי | תיאור |
|------|-----------|--------|
| `webapp/app.py` | פונקציה חדשה | `_build_files_need_attention()` |
| `webapp/app.py` | פונקציה חדשה | `_get_active_dismissals()` |
| `webapp/app.py` | עדכון route | `/dashboard` - הוספת נתוני הווידג'ט |
| `webapp/app.py` | API חדש | `/api/file/<id>/quick-update` |
| `webapp/app.py` | API חדש | `/api/file/<id>/dismiss-attention` |
| `webapp/templates/dashboard.html` | HTML חדש | תבנית הווידג'ט + 2 מודלים |
| `webapp/templates/dashboard.html` | CSS חדש | סגנונות לווידג'ט |
| `webapp/templates/dashboard.html` | JS חדש | לוגיקת Quick Edit + Dismiss |
| MongoDB | אינדקסים | 4 אינדקסים חדשים |
| MongoDB | Collection חדש | `attention_dismissals` |

---

## 9. נקודות חשובות למימוש

### 9.1 הפרדה לוגית בין הקבוצות
- קובץ **לא יכול להופיע בשתי הקבוצות** בו-זמנית
- קבוצת "לא עודכן" כוללת **רק** קבצים עם מטא-דאטה מלא
- השימוש ב-`{'tags.0': {'$exists': True}}` מבטיח שיש לפחות תגית אחת

### 9.2 Escaping ב-Template
- כל ערך שמוזרק ל-`data-*` attribute עובר דרך `| tojson`
- זה מונע שבירת HTML מתווים מיוחדים (גרשיים, סוגריים וכו')

### 9.3 ספירות ב-UI
- ה-Badge הכולל מתעדכן ויזואלית בעת הסרת פריטים
- הספירות בכותרות הקבוצות מציגות "מוצגים X מתוך Y"
- לסנכרון מלא של הספירות יש לרענן את הדף

### 9.4 "לא עודכן" vs "לא נפתח"
- הווידג'ט מבוסס על `updated_at` בלבד
- המונח הנכון הוא **"לא עודכן זמן רב"**
- אם נרצה לעקוב אחרי צפיות בעתיד, יש להוסיף שדה `last_viewed_at` נפרד

### 9.5 תגיות
- הקלט הוא **טקסט מופרד בפסיקים** (Comma-separated)
- לא chip UI מלא בשלב זה
- התגיות מנורמלות ל-lowercase ומוגבלות ל-20 תגיות, 50 תווים כל אחת

### 9.6 מניעת איבוד נתונים ב-Quick Edit
**בעיה פוטנציאלית:** אם המשתמש פותח עריכה מהירה על קובץ עם 10 תגיות, משנה רק את התיאור ושומר, התגיות עלולות להיחתך.

**הפתרון המיושם:**
1. **Backend:** שולח את **כל** התגיות (`tags_full`) ב-data attribute, לא רק 5 לתצוגה
2. **Frontend:** שומר את הערכים המקוריים (`originalDescription`, `originalTags`) בעת פתיחת המודל
3. **בעת שמירה:** משווה את הערכים החדשים למקוריים ושולח **רק שדות שהשתנו**
4. אם המשתמש שינה רק את התיאור — התגיות לא נשלחות ולא נפגעות

```javascript
// דוגמה: payload נבנה רק משדות שהשתנו
const payload = {};
if (newDescription !== originalDescription) {
    payload.description = newDescription;
}
if (newTagsRaw !== originalTags) {
    payload.tags = newTagsRaw.split(',').map(t => t.trim()).filter(Boolean);
}
// אם payload ריק — לא נשלח כלום
```

---

## 10. שדרוגים עתידיים אפשריים

1. **Chip Input אמיתי** — רכיב UI מתקדם לבחירת תגיות
2. **שדה `last_viewed_at`** — מעקב אחרי צפיות ולא רק עדכונים
3. **שדה `has_complete_metadata`** — לשיפור ביצועי שאילתות
4. **Auto-suggest לתיאור** — הצעה אוטומטית על בסיס שם הקובץ
5. **Bulk actions** — תיקון מהיר של מספר קבצים בבת אחת
6. **סינון לפי שפה** — הצגת קבצים חסרי מטא-דאטה לפי שפת תכנות

---

*מסמך זה (v2) נוצר ב-19/01/2026 ומותאם לארכיטקטורה הקיימת של CodeBot.*
*עודכן על בסיס ביקורת ארכיטקטורה.*
