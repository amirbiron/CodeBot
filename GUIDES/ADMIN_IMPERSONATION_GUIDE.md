# מדריך מימוש: Admin Impersonation (כניסה כמשתמש)

> **מטרה:** לאפשר לאדמינים לצפות במערכת מנקודת מבטו של משתמש רגיל, ללא גישה לנתונים פרטיים, אלא רק לצורך בדיקת UI/UX.

> **גרסה:** 1.1 (Production Grade)

---

## ⚠️ עקרונות ארכיטקטוניים קריטיים

לפני שמתחילים, חשוב להבין שלושה כללים שמבדילים בין מימוש שיעבוד לבין מימוש שיגרום לבאגים:

### 1. אל תיגע ב-`session['user_data']`! 🚫

**הבעיה:** שינוי `session['user_data']['is_admin'] = False` הוא מתכון לאסון. אם המשתמש יעשה לוגין מחדש או רענון שידרוס את ה-Session, המצב ישבר.

**הפתרון:** ה-Session מחזיק **רק** את הדגל `is_impersonating`, והלוגיקה קורית בזמן אמת ב-Context Processor.

### 2. מנגנון מילוט (Fail-Safe) 🆘

**הבעיה:** מה קורה אם יש באג ב-JS והבאנר הכתום לא מופיע? האדמין תקוע לנצח כמשתמש רגיל.

**הפתרון:** תמיד לאפשר עקיפה דרך `?force_admin=1` ב-URL.

### 3. Cache ו-CSRF 🔄

**הבעיה:** אם הדפדפן ישמור Cache, האדמין ילחץ על "צפה כמשתמש" ושום דבר לא יקרה ויזואלית.

**הפתרון:** הוספת `Cache-Control: no-store` ו-CSRF token לכל הבקשות.

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

def is_impersonating_raw() -> bool:
    """
    בודק אם הדגל הגולמי של Impersonation פעיל בסשן.
    
    ⚠️ לא לשימוש ישיר ב-UI! השתמש ב-is_impersonating_safe() שכולל Fail-Safe.
    """
    return bool(session.get(IMPERSONATION_SESSION_KEY, False))


def is_impersonating_safe() -> bool:
    """
    בודק אם מצב Impersonation פעיל, עם מנגנון מילוט (Fail-Safe).
    
    - אם ?force_admin=1 ב-URL → תמיד מחזיר False (עקיפה לשעת חירום)
    - אם הדגל פעיל אבל המשתמש לא אדמין באמת → מחזיר False (הגנה)
    - אחרת → מחזיר את מצב הדגל
    """
    # 🆘 Fail-Safe: עקיפה דרך URL לשעת חירום
    if request.args.get('force_admin') == '1':
        return False
    
    # בדיקה שהדגל פעיל
    if not is_impersonating_raw():
        return False
    
    # הגנה: וידוא שהמשתמש אכן אדמין (מונע מניפולציה בסשן)
    user_id = session.get('user_id')
    if user_id is None:
        return False
    
    try:
        if not is_admin(int(user_id)):
            # משתמש לא-אדמין עם דגל Impersonation? משהו לא בסדר - נקה
            session.pop(IMPERSONATION_SESSION_KEY, None)
            return False
    except Exception:
        return False
    
    return True


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
    """
    מפעיל מצב Impersonation. מחזיר True אם הצליח.
    
    ⚠️ חשוב: לא נוגעים ב-session['user_data']!
    כל הלוגיקה מחושבת בזמן אמת ב-Context Processor.
    """
    if not can_impersonate():
        return False
    
    user_id = session.get('user_id')
    
    # שומרים רק את הדגל - לא משנים user_data!
    session[IMPERSONATION_SESSION_KEY] = True
    session[IMPERSONATION_ORIGINAL_ADMIN_KEY] = user_id
    session['impersonation_started_at'] = time.time()
    
    return True


def stop_impersonation() -> bool:
    """
    מפסיק מצב Impersonation ומחזיר לסטטוס רגיל.
    
    ⚠️ חשוב: לא נוגעים ב-session['user_data']!
    """
    if not is_impersonating_raw():
        return False
    
    # ניקוי דגלי Impersonation בלבד
    session.pop(IMPERSONATION_SESSION_KEY, None)
    session.pop(IMPERSONATION_ORIGINAL_ADMIN_KEY, None)
    session.pop('impersonation_started_at', None)
    
    return True
```

> **🔑 נקודה קריטית:** שים לב שהפונקציות `start_impersonation()` ו-`stop_impersonation()` **לא נוגעות** ב-`session['user_data']`. זה מכוון! כל הלוגיקה של "מה להציג" מחושבת בזמן אמת ב-Context Processor (שלב 3).

### שלב 3: עדכון Context Processor (הלב של המימוש) ⭐

**קובץ:** `webapp/app.py`  
**פונקציה:** `inject_template_globals()`

זהו השלב הקריטי ביותר. כל הלוגיקה של "מה להציג" מחושבת כאן בזמן אמת, **בלי לגעת ב-session['user_data']**.

מצא את השורות שמגדירות `user_is_admin` והחלף את כל הבלוק:

```python
# =====================================================
# ADMIN IMPERSONATION - חישוב בזמן אמת
# =====================================================

# 1. שליפת האמת האבסולוטית (לא תלויה ב-Impersonation)
actual_is_admin = False
actual_is_premium = False
try:
    if user_id:
        actual_is_admin = bool(is_admin(int(user_id)))
        actual_is_premium = bool(is_premium(int(user_id)))
except Exception:
    pass

# 2. בדיקת מצב Impersonation עם Fail-Safe
#    - ?force_admin=1 → עקיפה לשעת חירום
#    - דגל פעיל + המשתמש אדמין באמת → מצב פעיל
force_admin_override = request.args.get('force_admin') == '1'
impersonation_flag = session.get(IMPERSONATION_SESSION_KEY, False)

if force_admin_override:
    # 🆘 מנגנון מילוט: האדמין הוסיף ?force_admin=1 ל-URL
    user_is_impersonating = False
else:
    # מצב Impersonation פעיל רק אם:
    # א. הדגל פעיל בסשן
    # ב. המשתמש אכן אדמין (הגנה מפני מניפולציה)
    user_is_impersonating = bool(impersonation_flag and actual_is_admin)

# 3. חישוב הסטטוס האפקטיבי לתצוגה
#    - אם מתחזים → לא אדמין, לא פרימיום (רואים כמשתמש רגיל)
#    - אחרת → הסטטוס האמיתי
if user_is_impersonating:
    effective_is_admin = False
    effective_is_premium = False
else:
    effective_is_admin = actual_is_admin
    effective_is_premium = actual_is_premium

# 4. user_is_admin משמש את ה-UI (מקבל את הערך האפקטיבי)
user_is_admin = effective_is_admin
```

ובסוף ה-return dict:

```python
return {
    'bot_username': BOT_USERNAME_CLEAN,
    # ... משתנים קיימים ...
    
    # הרשאות (אפקטיביות - לשימוש ה-UI)
    'user_is_admin': user_is_admin,           # ה-UI יתנהג לפי זה
    'user_is_premium': effective_is_premium,   # גם פרימיום מושפע
    
    # --- Admin Impersonation ---
    'user_is_impersonating': user_is_impersonating,  # להצגת הבאנר הכתום
    'actual_is_admin': actual_is_admin,              # כפתור היציאה יתנהג לפי זה
    'can_impersonate': actual_is_admin,              # מי רשאי לראות את הכפתור מלכתחילה
    
    # ... שאר המשתנים ...
}
```

> **💡 למה זה עובד?** הסטטוס האפקטיבי מחושב בכל בקשה מחדש, מהדגל הגולמי בסשן. אם הסשן מתרענן (לוגין מחדש), הדגל עדיין שם והחישוב ימשיך לעבוד. אם הסשן נמחק, המשתמש פשוט חוזר למצב רגיל.

### שלב 4: עדכון הדקורטורים (עם Fail-Safe)

**קובץ:** `webapp/app.py`  
**פונקציה:** `admin_required()`

עדכן את הדקורטור לתמוך ב-Impersonation עם מנגנון מילוט:

```python
def admin_required(f):
    """
    דקורטור לבדיקת הרשאות אדמין.
    
    - חוסם גישה במצב Impersonation (למעט Fail-Safe)
    - מאפשר עקיפה דרך ?force_admin=1
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        
        # בדיקה אם המשתמש הוא אדמין (הסטטוס האמיתי)
        try:
            uid = int(session['user_id'])
        except Exception:
            abort(403)
            
        if not is_admin(uid):
            abort(403)
        
        # 🆘 Fail-Safe: עקיפה דרך URL
        force_admin = request.args.get('force_admin') == '1'
        
        # במצב Impersonation - חסום גישה לעמודי אדמין (אלא אם Fail-Safe)
        if is_impersonating_safe() and not force_admin:
            flash('מצב צפייה כמשתמש פעיל - אין גישה לעמודי אדמין. לעקיפה: הוסף ?force_admin=1', 'warning')
            return redirect(url_for('dashboard'))
        
        return f(*args, **kwargs)
    return decorated_function
```

> **🆘 מנגנון מילוט:** אם האדמין "נתקע" במצב Impersonation ואין לו גישה לכפתור היציאה (בגלל באג ב-JS או CSS), הוא יכול תמיד לגשת ל-`/admin/stats?force_admin=1` ולחזור לשלוט.

### שלב 5: Routes להפעלה/כיבוי (עם Cache-Control)

**קובץ:** `webapp/app.py`

הוסף routes חדשים עם כותרות נגד Cache:

```python
from flask import make_response

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
        # 🔄 Cache-Control: מונע בעיות Cache בדפדפן
        resp = make_response(jsonify({'ok': True, 'message': 'מצב צפייה כמשתמש הופעל'}))
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
        return resp
    
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
        # 🔄 Cache-Control
        resp = make_response(jsonify({'ok': True, 'message': 'מצב צפייה כמשתמש הופסק'}))
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
        return resp
    
    return jsonify({'ok': False, 'error': 'לא במצב צפייה'}), 400


@app.route('/admin/impersonate/status', methods=['GET'])
@login_required
def admin_impersonate_status():
    """מחזיר סטטוס מצב ה-Impersonation הנוכחי."""
    actual_admin = can_impersonate()
    currently_impersonating = is_impersonating_safe()
    
    return jsonify({
        'ok': True,
        'is_impersonating': currently_impersonating,
        'can_impersonate': actual_admin,
        'actual_is_admin': actual_admin,
        # effective = actual אם לא מתחזים, אחרת False
        'effective_admin': False if currently_impersonating else actual_admin,
    })
```

> **🔄 למה Cache-Control?** בלי זה, הדפדפן עלול לשמור את התגובה ב-cache. המשתמש ילחץ על "צפה כמשתמש", יקבל תגובה מ-cache של בקשה קודמת, ושום דבר לא ישתנה ויזואלית.

### שלב 6: רכיב UI בתבנית הבסיס (עם Fail-Safe Link)

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
            <!-- 🆘 Fail-Safe Link: תמיד גלוי למקרה שה-JS לא עובד -->
            <a href="?force_admin=1" class="impersonation-failsafe" title="לחץ כאן אם הכפתור לא עובד">
                <i class="fas fa-life-ring"></i>
            </a>
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

> **🆘 Fail-Safe Link:** הקישור `?force_admin=1` תמיד גלוי בבאנר. אם הכפתור "חזור למצב אדמין" לא עובד (JS מושבת, באג, וכו'), האדמין יכול ללחוץ על האייקון הקטן ולחזור לשלוט.

### שלב 7: JavaScript לטוגל (עם CSRF ו-Force Reload)

**קובץ:** `webapp/static/js/impersonation.js` (חדש)

```javascript
/**
 * Admin Impersonation Toggle
 * מאפשר לאדמינים לצפות במערכת כמשתמש רגיל
 * 
 * גרסה: 1.1 - כולל תמיכה ב-CSRF ו-Force Reload
 */

(function() {
    'use strict';
    
    const API_START = '/admin/impersonate/start';
    const API_STOP = '/admin/impersonate/stop';
    
    /**
     * מקבל את ה-CSRF Token מה-meta tag (אם קיים).
     * נדרש אם המערכת משתמשת ב-Flask-WTF או הגנת CSRF אחרת.
     */
    function getCsrfToken() {
        const metaTag = document.querySelector('meta[name="csrf-token"]');
        return metaTag ? metaTag.getAttribute('content') : null;
    }
    
    /**
     * בונה את ה-headers לבקשה, כולל CSRF אם קיים.
     */
    function buildHeaders() {
        const headers = {
            'Content-Type': 'application/json',
        };
        
        const csrfToken = getCsrfToken();
        if (csrfToken) {
            headers['X-CSRFToken'] = csrfToken;
        }
        
        return headers;
    }
    
    /**
     * רענון "קשה" של הדף - מתעלם מ-cache.
     * משתמש ב-location.reload(true) שעובד ברוב הדפדפנים,
     * עם fallback לשינוי ה-URL אם לא עובד.
     */
    function forceReload() {
        // נסיון 1: reload(true) - deprecated אבל עדיין עובד בחלק מהדפדפנים
        try {
            window.location.reload(true);
        } catch (e) {
            // נסיון 2: הוספת timestamp ל-URL למניעת cache
            const url = new URL(window.location.href);
            url.searchParams.set('_t', Date.now());
            window.location.href = url.toString();
        }
    }
    
    function startImpersonation() {
        fetch(API_START, {
            method: 'POST',
            headers: buildHeaders(),
            credentials: 'same-origin',
            cache: 'no-store',  // 🔄 מונע cache ברמת הבקשה
        })
        .then(response => response.json())
        .then(data => {
            if (data.ok) {
                // 🔄 Force Reload - וידוא שאין cache
                forceReload();
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
            headers: buildHeaders(),
            credentials: 'same-origin',
            cache: 'no-store',
        })
        .then(response => response.json())
        .then(data => {
            if (data.ok) {
                forceReload();
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
                if (confirm('האם להפעיל מצב צפייה כמשתמש רגיל?\n\nבמצב זה לא תראה אפשרויות אדמין.\n\n💡 טיפ: אם תתקע, הוסף ?force_admin=1 ל-URL')) {
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

> **🔐 הערה על CSRF:** אם המערכת משתמשת ב-Flask-WTF, חובה להוסיף ל-`base.html`:
> ```html
> <meta name="csrf-token" content="{{ csrf_token() }}">
> ```
> אם אין הגנת CSRF, הקוד יעבוד גם בלי זה (הפונקציה `getCsrfToken` תחזיר `null`).

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

/* 🆘 Fail-Safe Link */
.impersonation-failsafe {
    color: rgba(0, 0, 0, 0.4);
    font-size: 14px;
    padding: 4px 8px;
    text-decoration: none;
    transition: color 0.2s;
}

.impersonation-failsafe:hover {
    color: rgba(0, 0, 0, 0.8);
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
    
    def test_force_admin_bypasses_impersonation(self, client, admin_user_session):
        """🆘 Fail-Safe: ?force_admin=1 עוקף את מצב Impersonation."""
        client.post('/admin/impersonate/start')
        
        # בלי force_admin - חסום
        response = client.get('/admin/stats')
        assert response.status_code in (302, 403)
        
        # עם force_admin - מותר
        response = client.get('/admin/stats?force_admin=1')
        assert response.status_code == 200
    
    def test_impersonation_does_not_modify_user_data(self, client, admin_user_session):
        """וידוא ש-session['user_data'] לא משתנה במצב Impersonation."""
        with client.session_transaction() as sess:
            original_user_data = dict(sess.get('user_data', {}))
        
        client.post('/admin/impersonate/start')
        
        with client.session_transaction() as sess:
            current_user_data = dict(sess.get('user_data', {}))
            # user_data לא אמור להשתנות - רק הדגל הנפרד
            assert current_user_data.get('is_admin') == original_user_data.get('is_admin')
    
    def test_context_processor_calculates_effective_status(self, client, admin_user_session):
        """בדיקה שה-Context Processor מחשב נכון את הסטטוס האפקטיבי."""
        # לפני Impersonation
        response = client.get('/dashboard')
        # בדוק שיש אלמנטי אדמין ב-HTML
        assert b'actual_is_admin' in response.data or b'admin-menu' in response.data
        
        # אחרי הפעלת Impersonation
        client.post('/admin/impersonate/start')
        response = client.get('/dashboard')
        # בדוק שאין אלמנטי אדמין ב-HTML (למעט כפתור היציאה)
        assert b'impersonation-banner' in response.data
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
| Session Keys | `webapp/app.py` | 2 קבועים חדשים |
| פונקציות עזר | `webapp/app.py` | 5 פונקציות חדשות |
| Context Processor | `webapp/app.py` | חישוב בזמן אמת + 4 משתנים חדשים |
| דקורטור `admin_required` | `webapp/app.py` | תמיכה ב-Fail-Safe |
| Routes | `webapp/app.py` | 3 endpoints + Cache-Control |
| UI Component | `webapp/templates/base.html` | באנר + כפתור + Fail-Safe link |
| JavaScript | `webapp/static/js/impersonation.js` | קובץ חדש (CSRF + Force Reload) |
| CSS | `webapp/static/css/impersonation.css` | קובץ חדש |
| טסטים | `tests/test_admin_impersonation.py` | קובץ חדש |

---

## ✅ צ'קליסט לפני Production

- [ ] הפונקציות `start_impersonation()` ו-`stop_impersonation()` **לא נוגעות** ב-`session['user_data']`
- [ ] ה-Context Processor מחשב הכל בזמן אמת מהדגל `IMPERSONATION_SESSION_KEY`
- [ ] מנגנון Fail-Safe (`?force_admin=1`) עובד ומאפשר עקיפה
- [ ] קישור Fail-Safe גלוי בבאנר הכתום
- [ ] `Cache-Control: no-store` מוגדר בכל ה-routes
- [ ] CSRF Token מועבר בבקשות JS (אם רלוונטי)
- [ ] `window.location.reload(true)` או force reload אחרי toggle
- [ ] טסטים עוברים (כולל Fail-Safe)

---

**נכתב:** ינואר 2026  
**גרסה:** 1.1 (Production Grade)  
**תואם ל:** CodeBot WebApp (Flask-based)
