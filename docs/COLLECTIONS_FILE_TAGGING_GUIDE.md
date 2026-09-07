# מדריך למימוש תיוג קבצים ב"אוספים שלי" 🏷️

## תוכן עניינים
1. [סקירה כללית](#סקירה-כללית)
2. [התגים המוצעים](#התגים-המוצעים)
3. [ארכיטקטורה ומבנה נתונים](#ארכיטקטורה-ומבנה-נתונים)
4. [שינויים נדרשים ב-Backend](#שינויים-נדרשים-ב-backend)
5. [שינויים נדרשים ב-Frontend](#שינויים-נדרשים-ב-frontend)
6. [UI/UX Components](#uiux-components)
7. [דוגמאות קוד](#דוגמאות-קוד)
8. [שלבי מימוש מומלצים](#שלבי-מימוש-מומלצים)
9. [שיקולים נוספים](#שיקולים-נוספים)

---

## סקירה כללית

מטרת המדריך היא להוסיף יכולת תיוג של קבצים באוספים באמצעות **אימוג'ים** שיאפשרו:
- **סימון עדיפויות** (דחוף/לא דחוף)
- **קטגוריות פונקציונליות** (באג, דאטה-בייס, ניסיוני)
- **סטטוס וסנטימנט** (מועדף, קסום, רעיון)
- **סדר טיפול** (תיוג מספרי 1️⃣2️⃣3️⃣)

התיוג יהיה **ברמת הפריט בתוך האוסף** (collection item) - כלומר, אותו קובץ יכול לקבל תגיות שונות באוספים שונים.

---

## התגים המוצעים

### רשימת התגים

| אימוג'י | שם | תיאור | קטגוריה |
|---------|-----|--------|----------|
| 🐢 | לא דחוף | משימה ללא לחץ זמן | עדיפות |
| 🔥 | דחוף | דורש טיפול מיידי | עדיפות |
| 🔮 | קסום | קוד מיוחד/מעניין | סנטימנט |
| ♥️ | מועדף | קובץ חשוב במיוחד | סנטימנט |
| 🔐 | סודי | מידע רגיש | אבטחה |
| 💭 | רעיון/idea | רעיון לפיתוח עתידי | סטטוס |
| ⏸️ | מושהה/paused | עבודה זמנית מושהית | סטטוס |
| 🎯 | מטרה/goal | יעד לביצוע | סטטוס |
| 🐛 | תיקון באג | תיקון שגיאה | קטגוריה |
| 🗄️ | דאטה-בייס | קשור למסד נתונים | קטגוריה |
| 🧪 | ניסיוני/testing | קוד בשלב בדיקה | קטגוריה |
| 1️⃣ | סדר ראשון | קובץ ראשון בסדר הטיפול | סדר |
| 2️⃣ | סדר שני | קובץ שני בסדר הטיפול | סדר |
| 3️⃣ | סדר שלישי | קובץ שלישי בסדר הטיפול | סדר |

### ארגון לפי קטגוריות

```python
TAG_CATEGORIES = {
    'priority': ['🐢', '🔥'],              # עדיפות
    'sentiment': ['🔮', '♥️'],            # סנטימנט
    'security': ['🔐'],                   # אבטחה
    'status': ['💭', '⏸️', '🎯'],          # סטטוס
    'category': ['🐛', '🗄️', '🧪'],       # קטגוריה פונקציונלית
    'order': ['1️⃣', '2️⃣', '3️⃣']          # סדר טיפול
}
```

---

## ארכיטקטורה ומבנה נתונים

### מבנה נתונים קיים

כרגע, בקולקציה `collection_items` יש את המבנה הבא:

```javascript
{
  "_id": ObjectId,
  "collection_id": ObjectId,
  "user_id": int,
  "source": str,              // "regular" | "large"
  "file_name": str,
  "note": str,                // עד 500 תווים
  "pinned": bool,
  "custom_order": int,
  "workspace_state": str,     // "todo" | "in_progress" | "done"
  "added_at": datetime,
  "updated_at": datetime
}
```

### שינוי מוצע: הוספת שדה `tags`

```javascript
{
  "_id": ObjectId,
  "collection_id": ObjectId,
  "user_id": int,
  "source": str,
  "file_name": str,
  "note": str,
  "pinned": bool,
  "custom_order": int,
  "workspace_state": str,
  "tags": [str],              // ✨ שדה חדש - רשימת אימוג'י תגיות
  "added_at": datetime,
  "updated_at": datetime
}
```

### דוגמאות למסמכים עם תגיות

```javascript
// דוגמה 1: קובץ עם באג דחוף
{
  "file_name": "auth_service.py",
  "tags": ["🐛", "🔥", "1️⃣"],  // באג דחוף, ראשון בתור
  "note": "תיקון בעיית התחברות"
}

// דוגמה 2: רעיון לעתיד
{
  "file_name": "ml_model.py",
  "tags": ["💭", "🔮", "🧪"],   // רעיון קסום וניסיוני
  "note": "מודל ML חדש לניסוי"
}

// דוגמה 3: דאטה-בייס סודי
{
  "file_name": "migration_001.sql",
  "tags": ["🗄️", "🔐"],        // דאטה-בייס רגיש
  "note": "מיגרציה לסכמה חדשה"
}
```

---

## שינויים נדרשים ב-Backend

### 1. קבועים ו-Validation

**קובץ:** `database/collections_manager.py`

הוסף בתחילת הקובץ:

```python
# תגיות מותרות (whitelist)
ALLOWED_TAGS = [
    # עדיפות
    '🐢',  # לא דחוף
    '🔥',  # דחוף

    # סנטימנט
    '🔮',  # קסום
    '♥️',  # מועדף

    # אבטחה
    '🔐',  # סודי

    # סטטוס
    '💭',  # רעיון
    '⏸️',  # מושהה
    '🎯',  # מטרה

    # קטגוריה
    '🐛',  # באג
    '🗄️',  # דאטה-בייס
    '🧪',  # ניסיוני

    # סדר
    '1️⃣',  # ראשון
    '2️⃣',  # שני
    '3️⃣',  # שלישי
]

# קטגוריות תגיות
TAG_CATEGORIES = {
    'priority': ['🐢', '🔥'],
    'sentiment': ['🔮', '♥️'],
    'security': ['🔐'],
    'status': ['💭', '⏸️', '🎯'],
    'category': ['🐛', '🗄️', '🧪'],
    'order': ['1️⃣', '2️⃣', '3️⃣']
}

# מטאדאטה לכל תגית
TAG_METADATA = {
    '🐢': {'name_he': 'לא דחוף', 'name_en': 'low priority', 'category': 'priority'},
    '🔥': {'name_he': 'דחוף', 'name_en': 'urgent', 'category': 'priority'},
    '🔮': {'name_he': 'קסום', 'name_en': 'magic', 'category': 'sentiment'},
    '♥️': {'name_he': 'מועדף', 'name_en': 'favorite', 'category': 'sentiment'},
    '🔐': {'name_he': 'סודי', 'name_en': 'secret', 'category': 'security'},
    '💭': {'name_he': 'רעיון', 'name_en': 'idea', 'category': 'status'},
    '⏸️': {'name_he': 'מושהה', 'name_en': 'paused', 'category': 'status'},
    '🎯': {'name_he': 'מטרה', 'name_en': 'goal', 'category': 'status'},
    '🐛': {'name_he': 'באג', 'name_en': 'bug', 'category': 'category'},
    '🗄️': {'name_he': 'דאטה-בייס', 'name_en': 'database', 'category': 'category'},
    '🧪': {'name_he': 'ניסיוני', 'name_en': 'experimental', 'category': 'category'},
    '1️⃣': {'name_he': 'ראשון', 'name_en': 'first', 'category': 'order'},
    '2️⃣': {'name_he': 'שני', 'name_en': 'second', 'category': 'order'},
    '3️⃣': {'name_he': 'שלישי', 'name_en': 'third', 'category': 'order'},
}

# מגבלות
MAX_TAGS_PER_ITEM = 10  # מקסימום תגיות לפריט
```

### 2. פונקציית Validation

הוסף פונקציה ל-`CollectionsManager`:

```python
def _validate_tags(self, tags):
    """
    מוודא שרשימת התגיות תקינה.

    Args:
        tags: רשימת תגיות (אימוג'ים)

    Returns:
        tuple: (is_valid, error_message)
    """
    if tags is None:
        return True, None

    if not isinstance(tags, list):
        return False, "tags must be a list"

    if len(tags) > MAX_TAGS_PER_ITEM:
        return False, f"maximum {MAX_TAGS_PER_ITEM} tags allowed per item"

    # בדיקת uniqueness
    if len(tags) != len(set(tags)):
        return False, "duplicate tags not allowed"

    # בדיקת whitelist
    for tag in tags:
        if tag not in ALLOWED_TAGS:
            return False, f"invalid tag: {tag}"

    return True, None
```

### 3. עדכון `add_items()` לתמיכה בתגיות

עדכן את המתודה `add_items()` ב-`CollectionsManager`:

```python
def add_items(self, user_id, collection_id, items):
    """
    הוספת פריטים לאוסף (מצב manual או mixed).

    Args:
        items: רשימה של דיקטים עם source, file_name, note (אופציונלי), tags (אופציונלי)
    """
    # ... קוד קיים לפני ...

    for item_dict in items:
        source = item_dict.get('source', 'regular')
        file_name = item_dict.get('file_name')
        note = (item_dict.get('note') or '').strip()[:500]
        tags = item_dict.get('tags', [])  # ✨ קריאת תגיות

        # ולידציית תגיות
        is_valid, error = self._validate_tags(tags)
        if not is_valid:
            raise ValueError(f"Invalid tags for {file_name}: {error}")

        # ... קוד קיים ...

        # יצירת המסמך
        item_doc = {
            'collection_id': oid,
            'user_id': user_id,
            'source': source,
            'file_name': file_name,
            'note': note,
            'tags': tags,  # ✨ שמירת תגיות
            'pinned': False,
            'custom_order': 0,
            'workspace_state': None,
            'added_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        }

        # ... המשך קוד קיים ...
```

### 4. פונקציה חדשה: `update_item_tags()`

הוסף מתודה חדשה ל-`CollectionsManager`:

```python
def update_item_tags(self, user_id, item_id, tags):
    """
    עדכון תגיות של פריט קיים באוסף.

    Args:
        user_id: מזהה משתמש
        item_id: מזהה הפריט (collection_item _id)
        tags: רשימת תגיות חדשה

    Returns:
        dict: הפריט המעודכן או None
    """
    # ולידציה
    is_valid, error = self._validate_tags(tags)
    if not is_valid:
        raise ValueError(f"Invalid tags: {error}")

    try:
        item_id_obj = ObjectId(item_id)
    except:
        return None

    # עדכון במסד הנתונים
    result = self.db.collection_items.update_one(
        {
            '_id': item_id_obj,
            'user_id': user_id  # ACL check
        },
        {
            '$set': {
                'tags': tags,
                'updated_at': datetime.utcnow()
            }
        }
    )

    if result.matched_count == 0:
        return None

    # קריאת הפריט המעודכן
    item = self.db.collection_items.find_one({'_id': item_id_obj})

    # ביטול cache
    if item:
        cid = item['collection_id']
        cache.delete_pattern(f"collections_items:{user_id}:{cid}:*")
        cache.delete_pattern(f"collections_detail:{user_id}:{cid}")

    emit_event('collections_item_tags_update', {
        'user_id': user_id,
        'item_id': str(item_id),
        'tags': tags
    })

    return self._public_item(item) if item else None
```

### 5. עדכון `_public_item()` להחזרת תגיות

וודא ש-`_public_item()` מחזירה את שדה ה-`tags`:

```python
def _public_item(self, doc):
    """המרת מסמך פריט למבנה ציבורי"""
    if not doc:
        return None

    return {
        'id': str(doc['_id']),
        'source': doc.get('source', 'regular'),
        'file_name': doc.get('file_name'),
        'note': doc.get('note', ''),
        'tags': doc.get('tags', []),  # ✨ החזרת תגיות
        'pinned': doc.get('pinned', False),
        'custom_order': doc.get('custom_order', 0),
        'workspace_state': doc.get('workspace_state'),
        'added_at': doc.get('added_at'),
        'updated_at': doc.get('updated_at')
    }
```

### 6. פונקציה לקבלת מטאדאטה של תגיות

```python
def get_tags_metadata(self):
    """
    החזרת מטאדאטה על כל התגיות הזמינות.

    Returns:
        dict: {
            'allowed_tags': [...],
            'categories': {...},
            'metadata': {...}
        }
    """
    return {
        'allowed_tags': ALLOWED_TAGS,
        'categories': TAG_CATEGORIES,
        'metadata': TAG_METADATA
    }
```

### 7. אינדקס במסד הנתונים

הוסף אינדקס לשדה `tags` לצורך חיפוש מהיר:

```python
# בפונקציה ensure_indexes() או ב-migration script
self.db.collection_items.create_index([
    ('collection_id', 1),
    ('tags', 1)
])
```

---

## שינויים נדרשים ב-Frontend

### 1. API Functions

**קובץ:** `webapp/static/js/collections.js`

הוסף בתוך אובייקט ה-`api`:

```javascript
const api = {
    // ... פונקציות קיימות ...

    /**
     * עדכון תגיות של פריט באוסף
     */
    updateItemTags(itemId, tags) {
        return fetch(`/api/collections/items/${itemId}/tags`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tags })
        }).then(r => r.json());
    },

    /**
     * קבלת מטאדאטה של תגיות זמינות
     */
    getTagsMetadata() {
        return fetch('/api/collections/tags/metadata')
            .then(r => r.json());
    }
};
```

### 2. קבועים גלובליים

הוסף בתחילת הקובץ:

```javascript
// תגיות זמינות (יטען מהשרת)
let TAGS_METADATA = null;

// מטא-מידע על תגיות (default עד שיטען מהשרת)
const DEFAULT_TAGS_METADATA = {
    allowed_tags: [
        '🐢', '🔥', '🔮', '♥️', '🔐', '💭',
        '⏸️', '🎯', '🐛', '🗄️', '🧪',
        '1️⃣', '2️⃣', '3️⃣'
    ],
    categories: {
        priority: ['🐢', '🔥'],
        sentiment: ['🔮', '♥️'],
        security: ['🔐'],
        status: ['💭', '⏸️', '🎯'],
        category: ['🐛', '🗄️', '🧪'],
        order: ['1️⃣', '2️⃣', '3️⃣']
    },
    metadata: {
        '🐢': { name_he: 'לא דחוף', name_en: 'low priority', category: 'priority' },
        '🔥': { name_he: 'דחוף', name_en: 'urgent', category: 'priority' },
        '🔮': { name_he: 'קסום', name_en: 'magic', category: 'sentiment' },
        '♥️': { name_he: 'מועדף', name_en: 'favorite', category: 'sentiment' },
        '🔐': { name_he: 'סודי', name_en: 'secret', category: 'security' },
        '💭': { name_he: 'רעיון', name_en: 'idea', category: 'status' },
        '⏸️': { name_he: 'מושהה', name_en: 'paused', category: 'status' },
        '🎯': { name_he: 'מטרה', name_en: 'goal', category: 'status' },
        '🐛': { name_he: 'באג', name_en: 'bug', category: 'category' },
        '🗄️': { name_he: 'דאטה-בייס', name_en: 'database', category: 'category' },
        '🧪': { name_he: 'ניסיוני', name_en: 'experimental', category: 'category' },
        '1️⃣': { name_he: 'ראשון', name_en: 'first', category: 'order' },
        '2️⃣': { name_he: 'שני', name_en: 'second', category: 'order' },
        '3️⃣': { name_he: 'שלישי', name_en: 'third', category: 'order' }
    }
};
```

### 3. טעינת מטאדאטה בעת אתחול

```javascript
/**
 * אתחול מטאדאטה של תגיות
 */
async function initTagsMetadata() {
    try {
        const resp = await api.getTagsMetadata();
        if (resp.ok) {
            TAGS_METADATA = resp;
        } else {
            TAGS_METADATA = DEFAULT_TAGS_METADATA;
        }
    } catch (err) {
        console.error('Failed to load tags metadata:', err);
        TAGS_METADATA = DEFAULT_TAGS_METADATA;
    }
}

// קריאה באתחול
document.addEventListener('DOMContentLoaded', async () => {
    await initTagsMetadata();
    // ... המשך אתחול קיים ...
});
```

### 4. רינדור תגיות בפריט

הוסף פונקציה לרינדור תגיות:

```javascript
/**
 * בניית HTML לתגיות של פריט
 * @param {Array} tags - רשימת תגיות (אימוג'ים)
 * @param {String} itemId - מזהה הפריט
 * @returns {String} HTML
 */
function buildItemTagsHtml(tags, itemId) {
    if (!tags || tags.length === 0) {
        return `<span class="item-tags-empty" data-item-id="${itemId}">אין תגיות</span>`;
    }

    const meta = TAGS_METADATA || DEFAULT_TAGS_METADATA;

    const tagsHtml = tags.map(tag => {
        const info = meta.metadata[tag] || {};
        const tooltip = info.name_he || tag;
        return `<span class="item-tag" data-tag="${tag}" title="${tooltip}">${tag}</span>`;
    }).join('');

    return `<div class="item-tags" data-item-id="${itemId}">${tagsHtml}</div>`;
}
```

### 5. עדכון רינדור פריט בליסטה

עדכן את הפונקציה שמרנדרת פריטים כדי לכלול תגיות:

```javascript
/**
 * רינדור פריט בודד ברשימה (עדכון לקוד קיים)
 */
function renderCollectionItem(item) {
    const { id, file_name, source, pinned, tags = [] } = item;

    const tagsHtml = buildItemTagsHtml(tags, id);

    return `
        <div class="collection-item"
             data-item-id="${id}"
             data-source="${source}"
             data-name="${file_name}"
             data-pinned="${pinned ? '1' : '0'}">
            <span class="drag-handle">⋮⋮</span>
            <a class="item-file-name" href="#">${file_name}</a>
            ${tagsHtml}
            <div class="item-actions">
                <button class="btn-tag-edit" data-item-id="${id}" title="ערוך תגיות">🏷️</button>
                <button class="btn-preview" data-item-id="${id}" title="תצוגה מקדימה">🧾</button>
                <button class="btn-remove" data-item-id="${id}" title="הסר">✕</button>
            </div>
        </div>
    `;
}
```

### 6. מודל עריכת תגיות

צור פונקציה לפתיחת מודל עריכת תגיות:

```javascript
/**
 * פתיחת מודל לעריכת תגיות של פריט
 * @param {String} itemId - מזהה הפריט
 * @param {Array} currentTags - תגיות נוכחיות
 */
function openTagsEditorModal(itemId, currentTags = []) {
    const meta = TAGS_METADATA || DEFAULT_TAGS_METADATA;

    // בניית HTML של בוחר תגיות לפי קטגוריות
    let categoriesHtml = '';

    Object.entries(meta.categories).forEach(([catKey, catTags]) => {
        const categoryNames = {
            priority: 'עדיפות',
            sentiment: 'סנטימנט',
            security: 'אבטחה',
            status: 'סטטוס',
            category: 'קטגוריה',
            order: 'סדר'
        };

        const catName = categoryNames[catKey] || catKey;

        const tagsHtml = catTags.map(tag => {
            const info = meta.metadata[tag] || {};
            const selected = currentTags.includes(tag) ? 'selected' : '';
            return `
                <button class="tag-option ${selected}"
                        data-tag="${tag}"
                        title="${info.name_he || tag}">
                    ${tag}
                    <span class="tag-name">${info.name_he || ''}</span>
                </button>
            `;
        }).join('');

        categoriesHtml += `
            <div class="tag-category">
                <h4 class="tag-category-title">${catName}</h4>
                <div class="tag-category-options">
                    ${tagsHtml}
                </div>
            </div>
        `;
    });

    const modalHtml = `
        <div class="modal tags-editor-modal" id="tagsEditorModal">
            <div class="modal-content">
                <div class="modal-header">
                    <h3>עריכת תגיות</h3>
                    <button class="modal-close">&times;</button>
                </div>
                <div class="modal-body">
                    <div class="tags-selected-preview">
                        <strong>תגיות נבחרות:</strong>
                        <div class="selected-tags-container">
                            ${currentTags.length > 0
                                ? currentTags.map(t => `<span class="selected-tag">${t}</span>`).join('')
                                : '<span class="no-tags">לא נבחרו תגיות</span>'}
                        </div>
                    </div>
                    <div class="tags-categories">
                        ${categoriesHtml}
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-primary" id="saveTagsBtn">שמור</button>
                    <button class="btn btn-secondary modal-close">ביטול</button>
                </div>
            </div>
        </div>
    `;

    // הוספת המודל ל-DOM
    const existingModal = document.getElementById('tagsEditorModal');
    if (existingModal) existingModal.remove();

    document.body.insertAdjacentHTML('beforeend', modalHtml);
    const modal = document.getElementById('tagsEditorModal');

    // Selected tags state
    let selectedTags = [...currentTags];

    // Event listeners לבחירת תגיות
    modal.querySelectorAll('.tag-option').forEach(btn => {
        btn.addEventListener('click', () => {
            const tag = btn.dataset.tag;

            if (selectedTags.includes(tag)) {
                // הסרת תגית
                selectedTags = selectedTags.filter(t => t !== tag);
                btn.classList.remove('selected');
            } else {
                // הוספת תגית
                if (selectedTags.length >= 10) {
                    showToast('ניתן לבחור עד 10 תגיות', 'warning');
                    return;
                }
                selectedTags.push(tag);
                btn.classList.add('selected');
            }

            // עדכון תצוגת תגיות נבחרות
            updateSelectedTagsPreview();
        });
    });

    // עדכון תצוגה
    function updateSelectedTagsPreview() {
        const container = modal.querySelector('.selected-tags-container');
        if (selectedTags.length === 0) {
            container.innerHTML = '<span class="no-tags">לא נבחרו תגיות</span>';
        } else {
            container.innerHTML = selectedTags
                .map(t => `<span class="selected-tag">${t}</span>`)
                .join('');
        }
    }

    // שמירת תגיות
    document.getElementById('saveTagsBtn').addEventListener('click', async () => {
        try {
            const resp = await api.updateItemTags(itemId, selectedTags);
            if (resp.ok) {
                showToast('התגיות עודכנו בהצלחה', 'success');
                modal.remove();

                // רענון תצוגת הפריט
                await renderCollectionItems(currentCollectionId);
            } else {
                showToast(resp.error || 'שגיאה בעדכון תגיות', 'error');
            }
        } catch (err) {
            console.error('Error updating tags:', err);
            showToast('שגיאה בעדכון תגיות', 'error');
        }
    });

    // סגירת מודל
    modal.querySelectorAll('.modal-close').forEach(btn => {
        btn.addEventListener('click', () => modal.remove());
    });

    // סגירה בלחיצה מחוץ למודל
    modal.addEventListener('click', (e) => {
        if (e.target === modal) modal.remove();
    });

    // הצגת המודל
    modal.style.display = 'flex';
}
```

### 7. Event Listeners לכפתור עריכת תגיות

הוסף event delegation לכפתור עריכת התגיות:

```javascript
/**
 * Wire up tags editor button clicks
 */
function wireTagsEditorButtons(container) {
    container.addEventListener('click', (e) => {
        const btn = e.target.closest('.btn-tag-edit');
        if (!btn) return;

        e.preventDefault();
        e.stopPropagation();

        const itemId = btn.dataset.itemId;
        const itemEl = container.querySelector(`[data-item-id="${itemId}"]`);

        // מציאת תגיות נוכחיות
        let currentTags = [];
        const tagsContainer = itemEl.querySelector('.item-tags');
        if (tagsContainer) {
            currentTags = Array.from(tagsContainer.querySelectorAll('.item-tag'))
                .map(el => el.dataset.tag);
        }

        openTagsEditorModal(itemId, currentTags);
    });
}

// קריאה לפונקציה זו בעת רינדור האוסף
function renderCollectionItems(collectionId) {
    // ... קוד קיים ...

    const contentArea = document.querySelector('.collections-content');
    wireTagsEditorButtons(contentArea);

    // ... המשך קוד ...
}
```

---

## UI/UX Components

### 1. סטיילינג CSS

**קובץ:** `webapp/static/css/collections.css`

הוסף CSS עבור תגיות:

```css
/* ========== Item Tags Styling ========== */

.item-tags {
    display: inline-flex;
    gap: 4px;
    align-items: center;
    margin: 0 8px;
    flex-wrap: wrap;
}

.item-tag {
    display: inline-flex;
    align-items: center;
    font-size: 16px;
    padding: 2px 4px;
    border-radius: 4px;
    background: var(--bg-secondary, #f0f0f0);
    cursor: help;
    transition: transform 0.15s;
}

.item-tag:hover {
    transform: scale(1.15);
}

.item-tags-empty {
    font-size: 12px;
    color: var(--text-muted, #999);
    font-style: italic;
}

/* ========== Tags Editor Modal ========== */

.tags-editor-modal .modal-content {
    max-width: 600px;
    max-height: 80vh;
    overflow-y: auto;
}

.tags-selected-preview {
    margin-bottom: 20px;
    padding: 12px;
    background: var(--bg-secondary, #f5f5f5);
    border-radius: 8px;
}

.selected-tags-container {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    margin-top: 8px;
}

.selected-tag {
    font-size: 20px;
    padding: 4px 8px;
    background: var(--color-primary, #4a90e2);
    color: white;
    border-radius: 6px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

.no-tags {
    font-size: 13px;
    color: var(--text-muted, #999);
    font-style: italic;
}

/* ========== Tag Categories ========== */

.tags-categories {
    display: flex;
    flex-direction: column;
    gap: 20px;
}

.tag-category {
    border: 1px solid var(--border-color, #e0e0e0);
    border-radius: 8px;
    padding: 12px;
    background: var(--bg-primary, white);
}

.tag-category-title {
    font-size: 14px;
    font-weight: 600;
    margin: 0 0 10px 0;
    color: var(--text-primary, #333);
}

.tag-category-options {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
}

.tag-option {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 6px 10px;
    font-size: 18px;
    border: 2px solid var(--border-color, #ddd);
    border-radius: 8px;
    background: var(--bg-primary, white);
    cursor: pointer;
    transition: all 0.2s;
}

.tag-option:hover {
    border-color: var(--color-primary, #4a90e2);
    transform: scale(1.05);
}

.tag-option.selected {
    border-color: var(--color-primary, #4a90e2);
    background: var(--color-primary-light, #e3f2fd);
    box-shadow: 0 0 0 3px rgba(74, 144, 226, 0.2);
}

.tag-name {
    font-size: 12px;
    color: var(--text-secondary, #666);
}

/* ========== Item Actions with Tag Button ========== */

.item-actions {
    display: flex;
    gap: 4px;
    align-items: center;
    margin-right: auto;
}

.btn-tag-edit {
    padding: 4px 8px;
    font-size: 16px;
    border: none;
    background: transparent;
    cursor: pointer;
    border-radius: 4px;
    transition: background 0.2s;
}

.btn-tag-edit:hover {
    background: var(--bg-hover, #f0f0f0);
}

/* ========== Dark Mode Support ========== */

[data-theme="dark"] .item-tag {
    background: var(--bg-tertiary, #2a2a2a);
}

[data-theme="dark"] .tags-selected-preview {
    background: var(--bg-tertiary, #2a2a2a);
}

[data-theme="dark"] .tag-category {
    background: var(--bg-secondary, #1e1e1e);
    border-color: var(--border-color, #444);
}

[data-theme="dark"] .tag-option {
    background: var(--bg-secondary, #1e1e1e);
    border-color: var(--border-color, #444);
}

[data-theme="dark"] .tag-option.selected {
    background: var(--color-primary-dark, #1e4d7b);
}
```

### 2. עדכון מבנה HTML של פריט

המבנה המעודכן של פריט ברשימה:

```html
<div class="collection-item" data-item-id="ABC123" data-source="regular" data-name="file.py">
    <span class="drag-handle">⋮⋮</span>
    <a class="item-file-name" href="#">file.py</a>

    <!-- תגיות -->
    <div class="item-tags" data-item-id="ABC123">
        <span class="item-tag" data-tag="🔥" title="דחוף">🔥</span>
        <span class="item-tag" data-tag="🐛" title="באג">🐛</span>
        <span class="item-tag" data-tag="1️⃣" title="ראשון">1️⃣</span>
    </div>

    <!-- פעולות -->
    <div class="item-actions">
        <button class="btn-tag-edit" data-item-id="ABC123" title="ערוך תגיות">🏷️</button>
        <button class="btn-preview" data-item-id="ABC123" title="תצוגה מקדימה">🧾</button>
        <button class="btn-remove" data-item-id="ABC123" title="הסר">✕</button>
    </div>
</div>
```

### 3. תמיכה ב-Workspace Kanban

עדכון כרטיסי הקנבן כדי להציג תגיות:

```javascript
function buildWorkspaceCardHtml(item) {
    const { id, file_name, tags = [] } = item;
    const tagsHtml = buildItemTagsHtml(tags, id);

    return `
        <div class="workspace-card" data-item-id="${id}">
            <button class="workspace-card__drag">⋮⋮</button>
            <div class="workspace-card__body">
                <div class="workspace-card__name">${file_name}</div>
                ${tagsHtml}
                <div class="workspace-card__meta">נוסף ${formatDate(item.added_at)}</div>
            </div>
            <div class="workspace-card__actions">
                <button class="btn-tag-edit" data-item-id="${id}">🏷️</button>
                <button class="btn-preview" data-item-id="${id}">🧾</button>
                <button class="btn-remove" data-item-id="${id}">✕</button>
            </div>
        </div>
    `;
}
```

---

## דוגמאות קוד

### Backend API Endpoint

**קובץ:** `webapp/collections_api.py`

```python
@collections_bp.route('/items/<item_id>/tags', methods=['PATCH'])
@require_auth
@traced()
def update_item_tags(item_id):
    """
    עדכון תגיות של פריט באוסף.

    Body: {"tags": ["🔥", "🐛"]}
    """
    user_id = session['user_id']
    data = request.get_json() or {}
    tags = data.get('tags', [])

    mgr = CollectionsManager()

    try:
        updated_item = mgr.update_item_tags(user_id, item_id, tags)

        if not updated_item:
            return jsonify({'ok': False, 'error': 'Item not found'}), 404

        return jsonify({
            'ok': True,
            'item': updated_item
        })

    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:
        logger.exception(f'Error updating item tags: {e}')
        emit_event('collections_item_tags_update_error', {
            'user_id': user_id,
            'item_id': item_id,
            'error': str(e)
        })
        return jsonify({'ok': False, 'error': 'Internal error'}), 500


@collections_bp.route('/tags/metadata', methods=['GET'])
@traced()
def get_tags_metadata():
    """
    קבלת מטאדאטה של תגיות זמינות.
    """
    mgr = CollectionsManager()
    metadata = mgr.get_tags_metadata()

    return jsonify({
        'ok': True,
        **metadata
    })
```

### Frontend - הוספת פריט עם תגיות

```javascript
async function addFileToCollection(collectionId, fileName, tags = []) {
    const resp = await api.addItems(collectionId, [
        {
            source: 'regular',
            file_name: fileName,
            note: '',
            tags: tags  // ✨ תגיות
        }
    ]);

    if (resp.ok) {
        showToast('הקובץ נוסף בהצלחה', 'success');
        await renderCollectionItems(collectionId);
    } else {
        showToast(resp.error || 'שגיאה בהוספת קובץ', 'error');
    }
}

// דוגמת שימוש
addFileToCollection('collection123', 'auth.py', ['🔥', '🐛', '1️⃣']);
```

### סינון פריטים לפי תגיות (Frontend)

```javascript
/**
 * סינון פריטים לפי תגיות
 * @param {Array} items - כל הפריטים
 * @param {Array} filterTags - תגיות לסינון
 * @returns {Array} פריטים מסוננים
 */
function filterItemsByTags(items, filterTags) {
    if (!filterTags || filterTags.length === 0) {
        return items;
    }

    return items.filter(item => {
        const itemTags = item.tags || [];
        // בדיקה אם הפריט מכיל לפחות אחת מהתגיות
        return filterTags.some(tag => itemTags.includes(tag));
    });
}

// דוגמה: הצגת רק פריטים דחופים
const urgentItems = filterItemsByTags(allItems, ['🔥']);
```

---

## שלבי מימוש מומלצים

### שלב 1: Backend Infrastructure (יום 1)

1. **עדכון `collections_manager.py`:**
   - ✅ הוספת קבועים: `ALLOWED_TAGS`, `TAG_CATEGORIES`, `TAG_METADATA`
   - ✅ פונקציית `_validate_tags()`
   - ✅ עדכון `add_items()` לתמיכה בתגיות
   - ✅ פונקציה חדשה `update_item_tags()`
   - ✅ עדכון `_public_item()` להחזרת tags
   - ✅ פונקציה `get_tags_metadata()`

2. **אינדקס במסד נתונים:**
   ```bash
   # הרצת script ליצירת אינדקס
   python -c "from database.collections_manager import CollectionsManager; mgr = CollectionsManager(); mgr.db.collection_items.create_index([('collection_id', 1), ('tags', 1)])"
   ```

3. **יחידות בדיקה:**
   - בדיקת validation של תגיות
   - בדיקת הוספת פריט עם תגיות
   - בדיקת עדכון תגיות
   - בדיקת החזרת metadata

### שלב 2: API Layer (יום 1-2)

1. **עדכון `collections_api.py`:**
   - ✅ Endpoint: `PATCH /api/collections/items/<item_id>/tags`
   - ✅ Endpoint: `GET /api/collections/tags/metadata`
   - ✅ עדכון response של `GET /api/collections/<id>/items` להחזיר tags

2. **בדיקות API:**
   ```bash
   # בדיקה ידנית עם curl
   curl -X PATCH http://localhost:5000/api/collections/items/ABC123/tags \
     -H "Content-Type: application/json" \
     -d '{"tags": ["🔥", "🐛"]}'
   ```

### שלב 3: Frontend - Core Functionality (יום 2-3)

1. **עדכון `collections.js`:**
   - ✅ הוספת `api.updateItemTags()`
   - ✅ הוספת `api.getTagsMetadata()`
   - ✅ פונקציה `initTagsMetadata()`
   - ✅ פונקציה `buildItemTagsHtml()`
   - ✅ עדכון `renderCollectionItem()` להצגת תגיות

2. **בדיקות ידניות:**
   - פתיחת דף Collections
   - וידוא טעינת metadata
   - וידוא הצגת תגיות בפריטים קיימים

### שלב 4: Tags Editor UI (יום 3-4)

1. **פיתוח מודל עריכה:**
   - ✅ פונקציה `openTagsEditorModal()`
   - ✅ Event listeners לבחירת תגיות
   - ✅ עדכון תצוגה בזמן אמת
   - ✅ שמירת תגיות

2. **Wire up כפתור עריכה:**
   - ✅ פונקציה `wireTagsEditorButtons()`
   - ✅ הוספת כפתור 🏷️ בכל פריט

### שלב 5: CSS Styling (יום 4)

1. **עדכון `collections.css`:**
   - ✅ סטיילינג `.item-tags`, `.item-tag`
   - ✅ סטיילינג `.tags-editor-modal`
   - ✅ סטיילינג `.tag-category`, `.tag-option`
   - ✅ תמיכה ב-Dark Mode

2. **בדיקות UI:**
   - תצוגה תקינה במצב Light/Dark
   - Responsive design (<900px)
   - Accessibility (keyboard navigation)

### שלב 6: Workspace Integration (יום 5)

1. **עדכון Kanban Board:**
   - ✅ עדכון `buildWorkspaceCardHtml()` להצגת תגיות
   - ✅ Wire up כפתור עריכה בכרטיסים
   - ✅ תמיכה ב-drag & drop עם תגיות

### שלב 7: Advanced Features (אופציונלי, יום 6-7)

1. **סינון לפי תגיות:**
   - פונקציה `filterItemsByTags()`
   - UI dropdown לסינון
   - Cache תוצאות סינון

2. **מיון לפי תגיות:**
   - מיון לפי עדיפות (🔥 לפני 🐢)
   - מיון לפי סדר (1️⃣ → 2️⃣ → 3️⃣)

3. **Bulk operations:**
   - בחירת מספר פריטים
   - עדכון תגיות מרובות בבת אחת

### שלב 8: Testing & Polish (יום 7-8)

1. **בדיקות אוטומטיות:**
   - Unit tests ל-Backend
   - Integration tests ל-API
   - E2E tests עם Playwright/Selenium

2. **בדיקות ידניות:**
   - Flow מלא: יצירה → עריכה → מחיקה
   - Edge cases (10 tags, Unicode, RTL)
   - Performance (1000+ items)

3. **דוקומנטציה:**
   - עדכון `docs/user/my_collections.rst`
   - Changelog
   - Screenshots

---

## שיקולים נוספים

### 1. ביצועים (Performance)

**אופטימיזציות:**
- אינדקס על שדה `tags` לחיפוש מהיר
- Cache metadata של תגיות (TTL 1 hour)
- Lazy loading של פריטים עם pagination
- Debounce על עדכוני tags (300ms)

**מדדים לניטור:**
```python
# Time to fetch items with tags
# Time to update tags
# Cache hit rate for metadata
```

### 2. אבטחה (Security)

**וולידציות:**
- ✅ Whitelist קפדנית של תגיות
- ✅ מגבלה של 10 tags per item
- ✅ ACL check - user_id filtering
- ✅ Sanitization של input
- ✅ Rate limiting על API endpoints

**מניעת XSS:**
```javascript
// כבר מטופל - אימוג'ים הם Unicode safe
// אך וודא שלא מאפשרים HTML/JavaScript בתגיות
```

### 3. נגישות (Accessibility)

**WCAG 2.1 AA:**
- Keyboard navigation במודל התגיות (Tab, Enter, Escape)
- ARIA labels לכפתורים
- Focus management בפתיחת/סגירת מודל
- Screen reader support (alt text לאימוג'ים)

```html
<button class="tag-option"
        role="checkbox"
        aria-checked="false"
        aria-label="תגית דחוף">
    🔥 <span class="sr-only">דחוף</span>
</button>
```

### 4. Internationalization (i18n)

התגיות כבר דו-לשוניות (`name_he`, `name_en`):

```javascript
const lang = document.documentElement.lang || 'he';
const tagName = TAG_METADATA[tag][`name_${lang}`];
```

### 5. Analytics & Observability

**אירועים לניטור:**
```python
emit_event('collections_tags_added', {
    'user_id': user_id,
    'item_id': item_id,
    'tags': tags,
    'count': len(tags)
})

emit_event('collections_tags_removed', {...})
emit_event('collections_tags_filtered', {...})
```

**מטריקות:**
- כמה משתמשים משתמשים בתיוג?
- מהן התגיות הפופולריות ביותר?
- כמה תגיות בממוצע לפריט?

### 6. Migration של נתונים קיימים

אם יש פריטים קיימים ב-DB:

```python
# Migration script
def migrate_existing_items_add_tags_field():
    """הוספת שדה tags ריק לפריטים קיימים"""
    from database.collections_manager import CollectionsManager

    mgr = CollectionsManager()
    result = mgr.db.collection_items.update_many(
        {'tags': {'$exists': False}},
        {'$set': {'tags': []}}
    )

    print(f"Updated {result.modified_count} items with empty tags field")

# הרצה
if __name__ == '__main__':
    migrate_existing_items_add_tags_field()
```

### 7. Feature Flags

**שלבי rollout:**
```python
# config.py
FEATURE_COLLECTIONS_TAGS = os.getenv('FEATURE_COLLECTIONS_TAGS', 'true').lower() == 'true'

# בקוד
if FEATURE_COLLECTIONS_TAGS:
    # הצגת UI של תגיות
    pass
```

### 8. חיפוש ע"י תגיות (Smart Collections)

הרחבה עתידית - אפשר להוסיף לחיפוש של Smart Collections:

```python
# ב-CollectionsManager
def compute_smart_items(self, user_id, rules, limit=200):
    # ... קוד קיים ...

    # הוספת חיפוש לפי תגיות
    if rules.get('tags'):
        pipeline.append({
            '$match': {
                'tags': {'$all': rules['tags']}  # כל התגיות חייבות להתאים
            }
        })
```

### 9. Export/Import של תגיות

תמיכה ב-export ל-JSON/CSV:

```javascript
function exportCollectionWithTags(collectionId) {
    const items = await api.getItems(collectionId);

    const csv = items.map(item => {
        return `${item.file_name},"${(item.tags || []).join(',')}",${item.note}`;
    }).join('\n');

    downloadFile('collection_export.csv', csv);
}
```

---

## סיכום

### מה כלול במדריך זה:

✅ **ארכיטקטורה מפורטת** של My Collections הקיים
✅ **מבנה נתונים** מוצע לתיוג עם 14 אימוג'ים
✅ **שינויים Backend** - validation, CRUD, API endpoints
✅ **שינויים Frontend** - UI components, מודל עריכה, רינדור
✅ **CSS Styling** מלא עם תמיכה ב-Dark Mode
✅ **דוגמאות קוד** מוכנות לשימוש
✅ **שלבי מימוש** צעד-אחר-צעד (8 ימים)
✅ **שיקולים** - ביצועים, אבטחה, נגישות

### הצעדים הבאים:

1. **תחילת פיתוח** - התחל בשלב 1 (Backend Infrastructure)
2. **סקירת קוד** - וודא שכל שינוי עובר code review
3. **בדיקות** - כתוב tests לכל שכבה
4. **דוקומנטציה** - עדכן את תיעוד המשתמש
5. **Rollout** - השק בהדרגה עם feature flag

---

**נוצר עבור:** פרויקט CodeBot
**גרסה:** 1.0
**תאריך:** 2026-01-29
**כותב:** Claude Code Assistant
