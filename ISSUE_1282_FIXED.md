# 🖥️ יצירת אוסף קבוע "שולחן עבודה" לכל משתמש

## 📋 תיאור

יצירת אוסף מובנה (built-in collection) בשם "שולחן עבודה" שיהיה זמין אוטומטית לכל משתמש, עם קיצור דרך בממשק והצגה מודגשת במודל "הוסף לאוסף".

---

## 🎯 דרישות

### 1. אוסף מובנה

- [ ] יצירת אוסף אוטומטי בשם "שולחן עבודה" לכל משתמש חדש
- [ ] האוסף יווצר באתחול ראשון (first login/signup)
- [ ] סוג: `manual` (הוספה והסרה ידנית של קבצים)
- [ ] אייקון: 🖥️ (מתוך רשימת ALLOWED_ICONS המורחבת)
- [ ] צבע: `purple` (מתוך COLLECTION_COLORS)
- [ ] `is_favorite: true` (להצגה מודגשת ברשימות)
- [ ] `sort_order: -1` (להצגה בראש הרשימה)

### 2. הרחבת רשימת אייקונים מותרים

- [ ] הוספת אייקונים חדשים ל-`ALLOWED_ICONS` ב-`database/collections_manager.py`:
  ```python
  ALLOWED_ICONS: List[str] = [
      "📂","📘","🎨","🧩","🐛","⚙️","📝","🧪","💡","⭐","🔖","🚀",
      "🖥️","💼","🖱️","⌨️","📱","💻","🖨️","📊","📈","📉","🔧","🛠️"
  ]
  ```

### 3. קיצור דרך בממשק

**אופציה מומלצת: כפתור ב-`files.html`**

הוסף כפתור בשורת הקטגוריות (אחרי "מועדפים", שורה ~114):

```html
<a href="#" 
   onclick="navigateToWorkspace(); return false;" 
   class="btn btn-secondary btn-icon workspace-btn">
    <i class="fas fa-desktop"></i>
    שולחן עבודה
    {% if workspace_count > 0 %}
    <span class="badge">{{ workspace_count }}</span>
    {% endif %}
</a>
```

**JavaScript Helper** (להוסיף ב-`base.html` או ב-`files.html`):

```javascript
async function navigateToWorkspace() {
    try {
        const res = await fetch('/api/collections?limit=100');
        const data = await res.json();
        if (!data || !data.ok) throw new Error('שגיאה בטעינת אוספים');
        
        const workspace = data.collections.find(c => 
            c.name === 'שולחן עבודה'
        );
        
        if (workspace) {
            window.location.href = `/collections/${workspace.id}`;
        } else {
            alert('אוסף שולחן עבודה לא נמצא');
        }
    } catch (e) {
        console.error('Error navigating to workspace:', e);
        alert('שגיאה בטעינת שולחן העבודה');
    }
}
```

### 4. הצגה מודגשת במודל "הוסף לאוסף"

- [ ] עדכון `openAddToCollectionModal` ו-`openBulkAddToCollectionModal` ב-`base.html`:
  - מצא את אוסף "שולחן עבודה"
  - הצג אותו בראש הרשימה עם הדגשה ויזואלית
  - אם לא נבחר אוסף אחר, סמן אותו כברירת מחדל (אחרי `last_collection_id`)

**דוגמת קוד לעדכון** (שורות 1022, 1040):

```javascript
// שלב 1: מצא את שולחן העבודה והפרד אותו מהשאר
const workspace = (data.collections||[]).find(c => c.name === 'שולחן עבודה');
const otherCollections = (data.collections||[]).filter(c => c.name !== 'שולחן עבודה');

// שלב 2: בנה HTML עם שולחן עבודה בראש (עם הדגשה)
let items = '';
if (workspace) {
    const isSelected = String(workspace.id) === String(last) || !last;
    items += `<label style="display:flex;align-items:center;gap:.5rem;margin:.5rem 0;padding:.5rem;background:rgba(102,126,234,0.1);border-radius:8px;border:1px solid rgba(102,126,234,0.3);">
        <input type="radio" name="collectionId" value="${workspace.id}" ${isSelected?'checked':''}>
        <span style="font-weight:600;">🖥️ ${escapeHtml(workspace.name)}</span>
    </label>`;
    if (otherCollections.length > 0) {
        items += '<div style="margin:.75rem 0 .5rem;font-size:.85rem;color:#666;border-top:1px solid #ddd;padding-top:.5rem;">אוספים אחרים:</div>';
    }
}
items += otherCollections.map(c => 
    `<label style="display:flex;align-items:center;gap:.5rem;margin:.25rem 0;">
        <input type="radio" name="collectionId" value="${c.id}" ${String(c.id)===String(last)?'checked':''}>
        <span>${escapeHtml(c.name||'')}</span>
    </label>`
).join('');

body.innerHTML = items || '<div class="empty">אין אוספים. צור אוסף חדש במסך "האוספים שלי"</div>';
```

---

## 🛠️ שינויים טכניים

### Backend

**1. הרחבת אייקונים (`database/collections_manager.py` - שורה 46)**

```python
ALLOWED_ICONS: List[str] = [
    "📂","📘","🎨","🧩","🐛","⚙️","📝","🧪","💡","⭐","🔖","🚀",
    "🖥️","💼","🖱️","⌨️","📱","💻","🖨️","📊","📈","📉","🔧","🛠️"
]
```

**2. יצירת פונקציה ליצירת אוספים מובנים (`database/collections_manager.py`)**

```python
def ensure_default_collections(self, user_id: int) -> None:
    """
    יצירת אוספים מובנים לכל משתמש חדש.
    נקרא באתחול ראשון (login/signup).
    """
    # אוסף "שולחן עבודה"
    existing = self.collections.find_one({
        'user_id': user_id,
        'name': 'שולחן עבודה'
    })
    
    if not existing:
        self.create_collection(
            user_id=user_id,
            name='שולחן עבודה',
            description='קבצים שאני עובד עליהם כרגע',
            mode='manual',
            icon='🖥️',
            color='purple',
            is_favorite=True,
            sort_order=-1  # להצגה בראש הרשימה
        )
```

**3. קריאה באתחול (`webapp/app.py`)**

**בפונקציה `telegram_auth()` (אחרי שורה 2278):**

```python
# אחרי עדכון/יצירת המשתמש ב-DB
try:
    from database.collections_manager import CollectionsManager
    collections_mgr = CollectionsManager(db)
    collections_mgr.ensure_default_collections(user_id)
except Exception:
    # לא לכשיל התחברות אם יש בעיה ביצירת אוספים
    pass
```

**בפונקציה `token_auth()` (אחרי שורה ~2330, אחרי עדכון המשתמש):**

```python
# אחרי עדכון/יצירת המשתמש ב-DB
try:
    from database.collections_manager import CollectionsManager
    collections_mgr = CollectionsManager(db)
    collections_mgr.ensure_default_collections(user_id)
except Exception:
    # לא לכשיל התחברות אם יש בעיה ביצירת אוספים
    pass
```

### Frontend

**1. כפתור ב-`files.html` (שורה ~114, אחרי כפתור "מועדפים")**

```html
<a href="#" 
   onclick="navigateToWorkspace(); return false;" 
   class="btn btn-secondary btn-icon workspace-btn">
    <i class="fas fa-desktop"></i>
    שולחן עבודה
    {% if workspace_count > 0 %}
    <span class="badge">{{ workspace_count }}</span>
    {% endif %}
</a>
```

**2. JavaScript Helper (`base.html` או `files.html`)**

```javascript
async function navigateToWorkspace() {
    try {
        const res = await fetch('/api/collections?limit=100');
        const data = await res.json();
        if (!data || !data.ok) throw new Error('שגיאה בטעינת אוספים');
        
        const workspace = data.collections.find(c => 
            c.name === 'שולחן עבודה'
        );
        
        if (workspace) {
            window.location.href = `/collections/${workspace.id}`;
        } else {
            alert('אוסף שולחן עבודה לא נמצא');
        }
    } catch (e) {
        console.error('Error navigating to workspace:', e);
        alert('שגיאה בטעינת שולחן העבודה');
    }
}
```

**3. עדכון מודל "הוסף לאוסף" (`base.html` - שורות 1012-1027, 1029-1045)**

עדכן את `openAddToCollectionModal` ו-`openBulkAddToCollectionModal` כפי שמוצג בסעיף 4 למעלה.

**4. סגנונות CSS (`webapp/static/css/collections.css` או `base.html`)**

```css
.workspace-btn {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    border: none;
    position: relative;
}

.workspace-btn:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(102, 126, 234, 0.4);
}

.workspace-btn .badge {
    background: rgba(255, 255, 255, 0.3);
    color: white;
    margin-inline-start: 6px;
}
```

---

## ✅ Checklist

### Backend
- [ ] הרחבת `ALLOWED_ICONS` ב-`collections_manager.py`
- [ ] יצירת `ensure_default_collections()` ב-`CollectionsManager`
- [ ] קריאה ל-`ensure_default_collections()` ב-`telegram_auth()`
- [ ] קריאה ל-`ensure_default_collections()` ב-`token_auth()`
- [ ] וידוא שהאוסף נוצר עם `is_favorite=True`, `sort_order=-1`

### Frontend
- [ ] הוספת כפתור "שולחן עבודה" ב-`files.html`
- [ ] הוספת פונקציה `navigateToWorkspace()` ב-`base.html` או `files.html`
- [ ] עדכון `openAddToCollectionModal` להצגת שולחן עבודה בראש
- [ ] עדכון `openBulkAddToCollectionModal` להצגת שולחן עבודה בראש
- [ ] הוספת סגנונות CSS לכפתור
- [ ] (אופציונלי) הוספת `workspace_count` ב-context של `files.html` route

### Migration
- [ ] יצירת migration script למשתמשים קיימים (ראה למטה)
- [ ] הרצת migration בפרודקשן

### בדיקות
- [ ] משתמש חדש מקבל את האוסף אוטומטית בהתחברות ראשונה
- [ ] הכפתור "שולחן עבודה" מוביל לאוסף הנכון
- [ ] שולחן עבודה מוצג בראש מודל "הוסף לאוסף"
- [ ] הוספה/הסרת קבצים עובדת תקין
- [ ] תצוגה נכונה במובייל
- [ ] משתמשים קיימים מקבלים את האוסף אחרי migration

---

## 🔄 Migration למשתמשים קיימים

```python
# scripts/migrate_workspace_collections.py
"""
Migration script: יצירת אוסף "שולחן עבודה" למשתמשים קיימים.
להרצה חד-פעמית.
"""
from database.collections_manager import CollectionsManager
from webapp.app import get_db

def migrate_existing_users():
    """
    יצירת אוסף שולחן עבודה למשתמשים קיימים.
    """
    try:
        db = get_db()
        collections_mgr = CollectionsManager(db)
        
        # מצא את כל המשתמשים
        users = db.users.find({}, {'user_id': 1})
        count = 0
        
        for user in users:
            user_id = user.get('user_id')
            if not user_id:
                continue
            
            # בדוק אם כבר יש אוסף "שולחן עבודה"
            existing = db.user_collections.find_one({
                'user_id': user_id,
                'name': 'שולחן עבודה'
            })
            
            if not existing:
                result = collections_mgr.create_collection(
                    user_id=user_id,
                    name='שולחן עבודה',
                    description='קבצים שאני עובד עליהם כרגע',
                    mode='manual',
                    icon='🖥️',
                    color='purple',
                    is_favorite=True,
                    sort_order=-1
                )
                if result.get('ok'):
                    count += 1
                    print(f"✓ Created for user {user_id}")
                else:
                    print(f"✗ Failed for user {user_id}: {result.get('error')}")
        
        print(f"\n✅ Migration complete: Created workspace collections for {count} users")
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        raise

if __name__ == '__main__':
    migrate_existing_users()
```

**הרצה:**
```bash
python scripts/migrate_workspace_collections.py
```

---

## 📝 הערות והחלטות עיצוב

### החלטות עיצוב

1. **אייקון**: 🖥️ (מתוך רשימת ALLOWED_ICONS המורחבת)
2. **צבע**: `purple` (מתוך COLLECTION_COLORS הקיימים)
3. **מיקום כפתור**: ב-`files.html` בשורת הקטגוריות, אחרי "מועדפים"
4. **הצגה במודל**: בראש הרשימה עם הדגשה ויזואלית, נבחר כברירת מחדל אם לא נבחר אוסף אחר
5. **זיהוי אוסף**: לפי שם קבוע `name == 'שולחן עבודה'` (לא נדרש שדה `is_system`)

### שיקולים טכניים

- **אל תמחק אוטומטית**: המשתמש מחליט מתי לנקות את שולחן העבודה
- **אייקון עקבי**: השתמש ב-🖥️ בכל מקום (אוסף, מודל, כפתור)
- **טיפול בשגיאות**: אם יצירת האוסף נכשלת, לא לכשיל את תהליך ההתחברות
- **Cache invalidation**: לאחר יצירת האוסף, אין צורך לעדכן cache כי זה נקרא רק באתחול ראשון

---

## 🎬 תוצאה צפויה

### במסך הקבצים (`/files`):
```
[כל הקבצים] [נפתחו לאחרונה] [מועדפים] [🖥️ שולחן עבודה (3)] [לפי ריפו]
                                              ↑ כפתור חדש
```

לחיצה על הכפתור → מעבר לאוסף "שולחן עבודה" ב-`/collections/{id}`

### במודל "הוסף לאוסף":
```
┌─────────────────────────────────┐
│  הוסף לאוסף                     │
├─────────────────────────────────┤
│  ☑ 🖥️ שולחן עבודה              │ ← הדגשה, נבחר כברירת מחדל
│     ─────────────────────────   │
│  אוספים אחרים:                  │
│  ○ אוסף שלי                     │
│  ○ אוסף אחר                     │
├─────────────────────────────────┤
│  [בטל]  [הוסף]                  │
└─────────────────────────────────┘
```

---

## 📚 קבצים לשינוי

1. `database/collections_manager.py` - הרחבת אייקונים + `ensure_default_collections()`
2. `webapp/app.py` - קריאה ל-`ensure_default_collections()` ב-auth endpoints
3. `webapp/templates/files.html` - כפתור "שולחן עבודה"
4. `webapp/templates/base.html` - עדכון מודל "הוסף לאוסף" + JavaScript helper
5. `webapp/static/css/collections.css` (או `base.html`) - סגנונות לכפתור
6. `scripts/migrate_workspace_collections.py` - migration script (חדש)

---

## 🔗 קישורים רלוונטיים

- [CodeBot – Project Docs](https://amirbiron.github.io/CodeBot/)
- Issue: #1282
