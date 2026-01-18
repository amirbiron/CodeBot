# מדריך מימוש: Admin Impersonation (כניסה כמשתמש)

> **מטרה:** לאפשר לאדמינים לצפות במערכת מנקודת מבטו של משתמש רגיל, ללא גישה לנתונים פרטיים, אלא רק לצורך בדיקת UI/UX.

---

## 📋 סקירת המצב הקיים

### מערכת האימות הנוכחית

המערכת מבוססת על Flask עם Session-based authentication:

```python
# webapp/app.py - מבנה הסשן הנוכחי
session['user_id'] = user_id                    # מזהה Telegram
session['user_data'] = {
    'id': user_id,
    'first_name': user.get('first_name', ''),
    'last_name': user.get('last_name', ''),
    'username': user.get('username', ''),
    'photo_url': '',
    'has_seen_welcome_modal': bool(...),
    'is_admin': is_admin(user_id),
    'is_premium': is_premium(user_id),
}
```

### פונקציות בדיקת הרשאות קיימות

```python
# webapp/app.py שורות 3522-3534
def is_admin(user_id: int) -> bool:
    """בודק אם משתמש הוא אדמין"""
    admin_ids_env = os.getenv('ADMIN_USER_IDS', '')
    admin_ids_list = admin_ids_env.split(',') if admin_ids_env else []
    admin_ids = [int(x.strip()) for x in admin_ids_list if x.strip().isdigit()]
    return user_id in admin_ids

def is_premium(user_id: int) -> bool:
    """בודק אם משתמש הוא פרימיום"""
    premium_ids_env = os.getenv('PREMIUM_USER_IDS', '')
    ...
```

### Context Processor

```python
# webapp/app.py - inject_template_globals()
# מעביר לכל התבניות:
{
    'user_is_admin': user_is_admin,  # bool
    ...
}
```

---

## 🎯 עקרונות מימוש

### מה כן?
- ✅ שינוי **תצוגת הרשאות** בלבד (האדמין רואה UI כאילו הוא לא אדמין)
- ✅ הפעלה/כיבוי דרך Toggle פשוט בממשק
- ✅ שמירת ה-`user_id` האמיתי (לא מתחזים למשתמש אחר)
- ✅ שימוש בדגל `is_impersonating` נפרד בסשן

### מה לא?
- ❌ לא מאפשרים כניסה לנתונים של משתמש אחר
- ❌ לא משנים את ה-`user_id` בסשן
- ❌ לא פוגעים בלוגים/אודיט (כל הפעולות מתועדות תחת האדמין האמיתי)

---

## 🛠️ שלבי המימוש

### שלב 1: הגדרת Session Keys חדשים

**קובץ:** `webapp/app.py`

הוסף קבועים בתחילת הקובץ (ליד שאר הקבועים):

```python
# --- Admin Impersonation ---
IMPERSONATION_SESSION_KEY = 'admin_impersonation_active'
IMPERSONATION_ORIGINAL_ADMIN_KEY = 'admin_impersonation_original_user_id'
```

### שלב 2: פונקציות עזר ל-Impersonation

**קובץ:** `webapp/app.py`

הוסף אחרי הפונקציה `is_premium()`:

```python
# --- Admin Impersonation Functions ---

def is_impersonating() -> bool:
    """בודק אם האדמין כרגע במצב Impersonation (צפייה כמשתמש רגיל)."""
    return bool(session.get(IMPERSONATION_SESSION_KEY, False))


def get_effective_admin_status() -> bool:
    """
    מחזיר את סטטוס האדמין *האפקטיבי* לצורכי UI.
    
    - אם במצב Impersonation: מחזיר False (האדמין רואה כמשתמש רגיל)
    - אחרת: מחזיר את הסטטוס האמיתי
    """
    if is_impersonating():
        return False
    
    user_id = session.get('user_id')
    if user_id is None:
        return False
    
    try:
        return is_admin(int(user_id))
    except Exception:
        return False


def get_effective_premium_status() -> bool:
    """
    מחזיר את סטטוס הפרימיום *האפקטיבי* לצורכי UI.
    
    - אם במצב Impersonation: מחזיר False
    - אחרת: מחזיר את הסטטוס האמיתי
    """
    if is_impersonating():
        return False
    
    user_id = session.get('user_id')
    if user_id is None:
        return False
    
    try:
        return is_premium(int(user_id))
    except Exception:
        return False


def can_impersonate() -> bool:
    """בודק אם המשתמש הנוכחי יכול להפעיל מצב Impersonation (רק אדמינים)."""
    user_id = session.get('user_id')
    if user_id is None:
        return False
    
    try:
        # בודק את הסטטוס האמיתי (לא האפקטיבי!)
        return is_admin(int(user_id))
    except Exception:
        return False


def start_impersonation() -> bool:
    """מפעיל מצב Impersonation. מחזיר True אם הצליח."""
    if not can_impersonate():
        return False
    
    user_id = session.get('user_id')
    session[IMPERSONATION_SESSION_KEY] = True
    session[IMPERSONATION_ORIGINAL_ADMIN_KEY] = user_id
    
    # עדכון user_data (לצורך התבניות)
    user_data = session.get('user_data', {})
    user_data['is_admin'] = False
    user_data['is_premium'] = False
    user_data['is_impersonating'] = True
    session['user_data'] = user_data
    
    return True


def stop_impersonation() -> bool:
    """מפסיק מצב Impersonation ומחזיר לסטטוס רגיל."""
    if not is_impersonating():
        return False
    
    original_user_id = session.get(IMPERSONATION_ORIGINAL_ADMIN_KEY)
    
    # ניקוי דגלי Impersonation
    session.pop(IMPERSONATION_SESSION_KEY, None)
    session.pop(IMPERSONATION_ORIGINAL_ADMIN_KEY, None)
    
    # שחזור user_data
    user_data = session.get('user_data', {})
    if original_user_id:
        user_data['is_admin'] = is_admin(int(original_user_id))
        user_data['is_premium'] = is_premium(int(original_user_id))
    user_data.pop('is_impersonating', None)
    session['user_data'] = user_data
    
    return True
```

### שלב 3: עדכון Context Processor

**קובץ:** `webapp/app.py`  
**פונקציה:** `inject_template_globals()`

מצא את השורות שמגדירות `user_is_admin`:

```python
# לפני:
user_is_admin = False
try:
    if user_id:
        user_is_admin = bool(is_admin(int(user_id)))
except Exception:
    user_is_admin = False
```

והחלף ל:

```python
# אחרי - תמיכה ב-Impersonation:
user_is_admin = False
user_is_impersonating = is_impersonating()
actual_is_admin = False

try:
    if user_id:
        actual_is_admin = bool(is_admin(int(user_id)))
        user_is_admin = get_effective_admin_status()
except Exception:
    user_is_admin = False
    actual_is_admin = False
```

ובסוף ה-return dict, הוסף:

```python
return {
    'bot_username': BOT_USERNAME_CLEAN,
    # ...
    'user_is_admin': user_is_admin,
    # --- חדש: Impersonation ---
    'user_is_impersonating': user_is_impersonating,
    'actual_is_admin': actual_is_admin,  # הסטטוס האמיתי (לכפתור יציאה)
    'can_impersonate': actual_is_admin,   # האם להציג כפתור כניסה/יציאה
    # ...
}
```

### שלב 4: עדכון הדקורטורים (אופציונלי)

אם רוצים ש-`admin_required` יחסום גם במצב Impersonation, עדכן:

**קובץ:** `webapp/app.py`  
**פונקציה:** `admin_required()`

```python
def admin_required(f):
    """דקורטור לבדיקת הרשאות אדמין"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        
        # במצב Impersonation - חסום גישה לעמודי אדמין
        if is_impersonating():
            # אפשרות א': הפנייה לדף הבית
            flash('מצב צפייה כמשתמש פעיל - אין גישה לעמודי אדמין', 'warning')
            return redirect(url_for('dashboard'))
            
            # אפשרות ב': 403 (פחות ידידותי)
            # abort(403)
        
        # בדיקה אם המשתמש הוא אדמין (הסטטוס האמיתי)
        try:
            uid = int(session['user_id'])
        except Exception:
            abort(403)
            
        if not is_admin(uid):
            abort(403)
        
        return f(*args, **kwargs)
    return decorated_function
```

### שלב 5: Routes להפעלה/כיבוי

**קובץ:** `webapp/app.py`

הוסף routes חדשים:

```python
@app.route('/admin/impersonate/start', methods=['POST'])
@login_required
def admin_impersonate_start():
    """הפעלת מצב צפייה כמשתמש רגיל (Impersonation)."""
    if not can_impersonate():
        return jsonify({'ok': False, 'error': 'לא מורשה'}), 403
    
    if start_impersonation():
        emit_event(
            'admin_impersonation_started',
            severity='info',
            user_id=session.get('user_id'),
        )
        return jsonify({'ok': True, 'message': 'מצב צפייה כמשתמש הופעל'})
    
    return jsonify({'ok': False, 'error': 'לא ניתן להפעיל מצב צפייה'}), 400


@app.route('/admin/impersonate/stop', methods=['POST'])
@login_required
def admin_impersonate_stop():
    """כיבוי מצב צפייה כמשתמש רגיל."""
    if stop_impersonation():
        emit_event(
            'admin_impersonation_stopped',
            severity='info',
            user_id=session.get('user_id'),
        )
        return jsonify({'ok': True, 'message': 'מצב צפייה כמשתמש הופסק'})
    
    return jsonify({'ok': False, 'error': 'לא במצב צפייה'}), 400


@app.route('/admin/impersonate/status', methods=['GET'])
@login_required
def admin_impersonate_status():
    """מחזיר סטטוס מצב ה-Impersonation הנוכחי."""
    return jsonify({
        'ok': True,
        'is_impersonating': is_impersonating(),
        'can_impersonate': can_impersonate(),
        'effective_admin': get_effective_admin_status(),
        'effective_premium': get_effective_premium_status(),
    })
```

### שלב 6: רכיב UI בתבנית הבסיס

**קובץ:** `webapp/templates/base.html`

הוסף בתוך ה-navbar או בפינה קבועה:

```html
{% if can_impersonate %}
<div id="impersonation-toggle" class="impersonation-control">
    {% if user_is_impersonating %}
        <!-- מצב פעיל - באנר צף -->
        <div class="impersonation-banner">
            <span class="impersonation-icon">👁️</span>
            <span class="impersonation-text">מצב צפייה כמשתמש פעיל</span>
            <button id="btn-stop-impersonation" class="btn btn-sm btn-warning">
                <i class="fas fa-user-shield"></i> חזור למצב אדמין
            </button>
        </div>
    {% else %}
        <!-- כפתור הפעלה (רק לאדמינים) -->
        <button id="btn-start-impersonation" class="btn btn-sm btn-outline-secondary" title="צפה במערכת כמשתמש רגיל">
            <i class="fas fa-eye"></i> צפה כמשתמש
        </button>
    {% endif %}
</div>
{% endif %}
```

### שלב 7: JavaScript לטוגל

**קובץ:** `webapp/static/js/impersonation.js` (חדש)

```javascript
/**
 * Admin Impersonation Toggle
 * מאפשר לאדמינים לצפות במערכת כמשתמש רגיל
 */

(function() {
    'use strict';
    
    const API_START = '/admin/impersonate/start';
    const API_STOP = '/admin/impersonate/stop';
    
    function startImpersonation() {
        fetch(API_START, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            credentials: 'same-origin',
        })
        .then(response => response.json())
        .then(data => {
            if (data.ok) {
                // רענון הדף להחלת השינוי
                window.location.reload();
            } else {
                alert(data.error || 'שגיאה בהפעלת מצב צפייה');
            }
        })
        .catch(err => {
            console.error('Impersonation start error:', err);
            alert('שגיאת תקשורת');
        });
    }
    
    function stopImpersonation() {
        fetch(API_STOP, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            credentials: 'same-origin',
        })
        .then(response => response.json())
        .then(data => {
            if (data.ok) {
                window.location.reload();
            } else {
                alert(data.error || 'שגיאה בכיבוי מצב צפייה');
            }
        })
        .catch(err => {
            console.error('Impersonation stop error:', err);
            alert('שגיאת תקשורת');
        });
    }
    
    // Event Listeners
    document.addEventListener('DOMContentLoaded', function() {
        const btnStart = document.getElementById('btn-start-impersonation');
        const btnStop = document.getElementById('btn-stop-impersonation');
        
        if (btnStart) {
            btnStart.addEventListener('click', function(e) {
                e.preventDefault();
                if (confirm('האם להפעיל מצב צפייה כמשתמש רגיל?\n\nבמצב זה לא תראה אפשרויות אדמין.')) {
                    startImpersonation();
                }
            });
        }
        
        if (btnStop) {
            btnStop.addEventListener('click', function(e) {
                e.preventDefault();
                stopImpersonation();
            });
        }
    });
})();
```

### שלב 8: CSS לבאנר Impersonation

**קובץ:** `webapp/static/css/impersonation.css` (חדש)

```css
/* Admin Impersonation Banner & Controls */

.impersonation-control {
    position: relative;
    z-index: 1050;
}

/* באנר צף כשמצב פעיל */
.impersonation-banner {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    background: linear-gradient(90deg, #f59e0b 0%, #d97706 100%);
    color: #1a1a1a;
    padding: 8px 16px;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
    font-weight: 600;
    font-size: 14px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.2);
    z-index: 9999;
    animation: slideDown 0.3s ease-out;
}

@keyframes slideDown {
    from {
        transform: translateY(-100%);
    }
    to {
        transform: translateY(0);
    }
}

.impersonation-banner .impersonation-icon {
    font-size: 18px;
}

.impersonation-banner .btn {
    margin-right: 8px;
}

/* כפתור הפעלה (כשלא פעיל) */
#btn-start-impersonation {
    font-size: 12px;
    padding: 4px 8px;
    opacity: 0.8;
    transition: opacity 0.2s;
}

#btn-start-impersonation:hover {
    opacity: 1;
}

/* התאמה כשיש באנר - הזז את ה-body למטה */
body.impersonation-active {
    padding-top: 48px;
}
```

### שלב 9: הוספת Class ל-Body

**קובץ:** `webapp/templates/base.html`

עדכן את תג ה-`<body>`:

```html
<body class="{% if user_is_impersonating %}impersonation-active{% endif %}">
```

### שלב 10: טעינת הקבצים

**קובץ:** `webapp/templates/base.html`

הוסף בסוף ה-`<head>`:

```html
{% if can_impersonate %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/impersonation.css') }}?v={{ static_version }}">
{% endif %}
```

ובסוף ה-`<body>` (לפני `</body>`):

```html
{% if can_impersonate %}
<script src="{{ url_for('static', filename='js/impersonation.js') }}?v={{ static_version }}"></script>
{% endif %}
```

---

## 🔒 שיקולי אבטחה

### אודיט ולוגים

כל הפעולות במצב Impersonation **עדיין מתועדות** תחת ה-`user_id` האמיתי של האדמין:

```python
# דוגמה לשימוש בלוג:
emit_event(
    'file_edited',
    severity='info',
    user_id=session.get('user_id'),  # האדמין האמיתי
    is_impersonating=is_impersonating(),
    file_id=file_id,
)
```

### הגבלות

1. **אין גישה לנתוני משתמשים אחרים** - ה-`user_id` בסשן לא משתנה
2. **אין שינוי בבסיס הנתונים** - Impersonation משפיע רק על ה-UI
3. **עמודי אדמין חסומים** - הדקורטור `admin_required` מונע גישה
4. **תיעוד מלא** - כל הפעלה/כיבוי נרשמים ב-observability

### Timeout אוטומטי (אופציונלי)

ניתן להוסיף timeout אוטומטי שיכבה את מצב ה-Impersonation אחרי X דקות:

```python
IMPERSONATION_TIMEOUT_SECONDS = 30 * 60  # 30 דקות

def check_impersonation_timeout():
    """בדיקה אם פג תוקף ה-Impersonation."""
    if not is_impersonating():
        return
    
    started_at = session.get('impersonation_started_at')
    if started_at:
        elapsed = time.time() - started_at
        if elapsed > IMPERSONATION_TIMEOUT_SECONDS:
            stop_impersonation()
            flash('מצב צפייה כמשתמש הסתיים אוטומטית (timeout)', 'info')
```

---

## 🧪 בדיקות

### טסט יחידה לפונקציות

**קובץ:** `tests/test_admin_impersonation.py`

```python
import pytest
from flask import session

class TestAdminImpersonation:
    """טסטים למצב Admin Impersonation."""
    
    def test_non_admin_cannot_impersonate(self, client, regular_user_session):
        """משתמש רגיל לא יכול להפעיל Impersonation."""
        response = client.post('/admin/impersonate/start')
        assert response.status_code == 403
    
    def test_admin_can_start_impersonation(self, client, admin_user_session):
        """אדמין יכול להפעיל Impersonation."""
        response = client.post('/admin/impersonate/start')
        assert response.status_code == 200
        data = response.get_json()
        assert data['ok'] is True
    
    def test_impersonation_hides_admin_ui(self, client, admin_user_session):
        """במצב Impersonation, אלמנטי אדמין נעלמים."""
        # הפעלת Impersonation
        client.post('/admin/impersonate/start')
        
        # בדיקת עמוד הבית
        response = client.get('/dashboard')
        assert b'admin-menu' not in response.data
    
    def test_impersonation_blocks_admin_pages(self, client, admin_user_session):
        """במצב Impersonation, עמודי אדמין חסומים."""
        client.post('/admin/impersonate/start')
        
        response = client.get('/admin/stats')
        assert response.status_code in (302, 403)  # redirect או forbidden
    
    def test_stop_impersonation_restores_admin(self, client, admin_user_session):
        """יציאה מ-Impersonation מחזירה הרשאות אדמין."""
        client.post('/admin/impersonate/start')
        client.post('/admin/impersonate/stop')
        
        response = client.get('/admin/stats')
        assert response.status_code == 200
```

---

## 📊 מעקב ותצפית (Observability)

### אירועים לתיעוד

```python
# הפעלת Impersonation
emit_event(
    'admin_impersonation_started',
    severity='info',
    user_id=session.get('user_id'),
    request_id=generate_request_id(),
)

# כיבוי Impersonation
emit_event(
    'admin_impersonation_stopped',
    severity='info',
    user_id=session.get('user_id'),
    duration_seconds=elapsed_time,
)

# פעולה במצב Impersonation
emit_event(
    'action_performed_while_impersonating',
    severity='info',
    user_id=session.get('user_id'),
    action='file_edit',
    target_id=file_id,
)
```

### מטריקות (Prometheus)

```python
impersonation_sessions_total = Counter(
    'admin_impersonation_sessions_total',
    'Total admin impersonation sessions started',
    ['admin_id']
)

impersonation_duration_seconds = Histogram(
    'admin_impersonation_duration_seconds',
    'Duration of admin impersonation sessions',
    buckets=[60, 300, 600, 1800, 3600]
)
```

---

## 🎨 שיפורים עתידיים (אופציונלי)

### 1. בחירת משתמש ספציפי
אפשרות לבחור משתמש ספציפי ולראות את התצוגה שלו (בלי גישה לנתונים):

```python
# מעבר ל-view של משתמש ספציפי
session['impersonation_view_user_id'] = target_user_id
```

### 2. סימולציית הרשאות
בחירת רמת הרשאות לסימולציה:
- משתמש רגיל
- משתמש פרימיום
- משתמש חדש (ללא קבצים)

### 3. תיעוד פעולות
הקלטת כל הפעולות שבוצעו במצב Impersonation לצורך ניתוח:

```python
impersonation_log.append({
    'timestamp': datetime.now(timezone.utc),
    'action': 'page_view',
    'path': request.path,
    'query': dict(request.args),
})
```

---

## 📝 סיכום

| רכיב | קובץ | שינוי |
|------|------|-------|
| Session Keys | `webapp/app.py` | קבועים חדשים |
| פונקציות עזר | `webapp/app.py` | 6 פונקציות חדשות |
| Context Processor | `webapp/app.py` | 3 משתנים חדשים |
| Routes | `webapp/app.py` | 3 endpoints חדשים |
| UI Component | `webapp/templates/base.html` | באנר + כפתור |
| JavaScript | `webapp/static/js/impersonation.js` | קובץ חדש |
| CSS | `webapp/static/css/impersonation.css` | קובץ חדש |
| טסטים | `tests/test_admin_impersonation.py` | קובץ חדש |

---

**נכתב:** ינואר 2026  
**גרסה:** 1.0  
**תואם ל:** CodeBot WebApp (Flask-based)
