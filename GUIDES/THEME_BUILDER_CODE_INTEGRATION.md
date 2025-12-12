# התאמת Theme Builder לקוד הקיים

> **מסמך טכני:** נקודות שילוב מדויקות בקוד הקיים  
> **קהל יעד:** מפתחים המבצעים את המימוש  
> **עדכון אחרון:** דצמבר 2024

---

## 📍 מבנה הפרויקט הרלוונטי

```
/workspace/
├── webapp/
│   ├── app.py                          ← הוספת routes + API
│   ├── templates/
│   │   ├── base.html                   ← הזרקת custom theme
│   │   ├── settings.html               ← הוספת לינק
│   │   └── settings/
│   │       └── theme_builder.html      ← קובץ חדש!
│   └── static/
│       └── css/
│           ├── dark-mode.css           ← קיים, לא נוגעים
│           └── high-contrast.css       ← קיים, לא נוגעים
├── database/
│   └── models.py                       ← לא צריך שינויים
└── docs/
    └── webapp/
        └── theming_and_css.rst         ← עדכון לאחר מימוש
```

---

## 🔧 שינויים ב-`webapp/app.py`

### מיקום 1: קבועים (בתחילת הקובץ, אחרי imports)

**שורה משוערת:** ~86 (אחרי `DEFAULT_LANGUAGE_CHOICES`)

```python
# קבועים קיימים (לא לשנות)
DEFAULT_LANGUAGE_CHOICES = [...]

# ← הוסף כאן:
# קבועים עבור Theme Builder
VALID_COLOR_REGEX = r'^(#[0-9a-fA-F]{6}|rgba?\(.+\))$'
MAX_THEME_NAME_LENGTH = 50
REQUIRED_THEME_TOKENS = {
    "--bg-primary", "--bg-secondary", "--card-bg",
    "--primary", "--secondary",
    "--text-primary", "--text-secondary",
    "--glass", "--glass-border", "--glass-hover", "--glass-blur",
    "--md-surface", "--md-text"
}
```

---

### מיקום 2: עדכון ALLOWED_UI_THEMES

**איפה למצוא:** חפש `ALLOWED_UI_THEMES` בקובץ

**לפני:**
```python
ALLOWED_UI_THEMES = {
    "classic", "ocean", "forest", "high-contrast", 
    "dark", "dim", "rose-pine-dawn", "nebula"
}
```

**אחרי:**
```python
ALLOWED_UI_THEMES = {
    "classic", "ocean", "forest", "high-contrast", 
    "dark", "dim", "rose-pine-dawn", "nebula",
    "custom"  # ← הוסף
}
```

---

### מיקום 3: Context Processor (לפני route הראשון)

**שורה משוערת:** ~400-500 (חפש `@app.before_request` או route ראשון)

```python
@app.context_processor
def inject_db():
    """
    הזרקת db לכל התבניות כדי לאפשר גישה ל-custom_theme.
    נדרש ל-base.html להציג את התמה המותאמת.
    """
    return dict(db=get_db())
```

**הערה:** אם כבר קיים `@app.context_processor`, הוסף את `db` לתוך ה-dict שמוחזר.

---

### מיקום 4: נתיב Theme Builder

**איפה להוסיף:** אחרי הנתיב `/settings` (שורה ~8886)

```python
@app.route('/settings')
@login_required
def settings():
    # ... קוד קיים ...
    pass

# ← הוסף כאן:
@app.route('/settings/theme-builder')
@login_required
def theme_builder():
    """
    דף בונה ערכות נושא מותאמות אישית.
    מאפשר למשתמשים לערוך טוקנים, לראות Live Preview ולשמור Theme יחיד.
    """
    user_id = session['user_id']
    db = get_db()
    
    # טעינת Theme שמור (אם קיים)
    user_doc = db.users.find_one({"user_id": user_id}, {"custom_theme": 1})
    saved_theme = user_doc.get("custom_theme") if user_doc else None
    
    return render_template(
        'settings/theme_builder.html',
        saved_theme=saved_theme,
        static_version=_STATIC_VERSION
    )
```

---

### מיקום 5: API לשמירת Theme

**איפה להוסיף:** אחרי `/api/ui_prefs` (שורה ~9113)

```python
@app.route('/api/ui_prefs', methods=['POST'])
# ... קוד קיים ...

# ← הוסף כאן:
@app.route('/api/themes/save', methods=['POST'])
@login_required
def save_custom_theme():
    """
    שמירת Theme מותאם אישית במסד הנתונים.
    
    Request Body (JSON):
    {
        "name": str (1-50 תווים),
        "description": str (אופציונלי, עד 200 תווים),
        "set_as_default": bool,
        "colors": {
            "background": str (HEX או RGBA),
            "background_alt": str (אופציונלי),
            "card_bg": str,
            "primary": str,
            "secondary": str,
            "text": str,
            "text_secondary": str (אופציונלי)
        },
        "glass": {
            "rgba": str,
            "border": str,
            "hover": str,
            "blur": int (0-100)
        },
        "markdown": {
            "surface": str,
            "text": str
        }
    }
    
    Returns:
        JSON: {"ok": bool, "message": str, "theme": dict}
    """
    try:
        data = request.get_json(silent=True) or {}
        
        # ולידציה: שם
        name = (data.get("name") or "").strip()
        if not name or len(name) > MAX_THEME_NAME_LENGTH:
            return jsonify({
                "ok": False,
                "error": f"שם התמה חייב להיות בין 1-{MAX_THEME_NAME_LENGTH} תווים"
            }), 400
        
        description = (data.get("description") or "").strip()[:200]
        
        # ולידציה: צבעים
        colors = data.get("colors", {})
        glass = data.get("glass", {})
        markdown = data.get("markdown", {})
        
        def validate_color(val):
            """בדיקה שהצבע בפורמט תקין (HEX או RGBA)"""
            if not val:
                return False
            return bool(re.match(VALID_COLOR_REGEX, str(val).strip()))
        
        # צבעים חובה
        required_colors = ["background", "card_bg", "primary", "secondary", "text"]
        for key in required_colors:
            if not validate_color(colors.get(key)):
                return jsonify({
                    "ok": False,
                    "error": f"צבע לא תקין: {key}"
                }), 400
        
        # Glass חובה
        if not validate_color(glass.get("rgba")) or \
           not validate_color(glass.get("border")) or \
           not validate_color(glass.get("hover")):
            return jsonify({
                "ok": False,
                "error": "ערכי Glass לא תקינים"
            }), 400
        
        # Blur חייב להיות מספר
        try:
            blur_value = float(glass.get("blur", 20))
            if blur_value < 0 or blur_value > 100:
                blur_value = 20
        except:
            blur_value = 20
        
        # Markdown חובה
        if not validate_color(markdown.get("surface")) or \
           not validate_color(markdown.get("text")):
            return jsonify({
                "ok": False,
                "error": "ערכי Markdown לא תקינים"
            }), 400
        
        # בניית אובייקט Theme
        theme = {
            "name": name,
            "description": description,
            "is_active": bool(data.get("set_as_default", False)),
            "updated_at": datetime.now(timezone.utc),
            "variables": {
                "--bg-primary": colors["background"],
                "--bg-secondary": colors.get("background_alt", colors["background"]),
                "--card-bg": colors["card_bg"],
                "--primary": colors["primary"],
                "--secondary": colors["secondary"],
                "--text-primary": colors["text"],
                "--text-secondary": colors.get("text_secondary", "rgba(255,255,255,0.8)"),
                "--glass": glass["rgba"],
                "--glass-border": glass["border"],
                "--glass-hover": glass["hover"],
                "--glass-blur": f"{blur_value}px",
                "--md-surface": markdown["surface"],
                "--md-text": markdown["text"]
            }
        }
        
        # שמירה ב-DB
        db = get_db()
        user_id = session['user_id']
        
        update_doc = {"custom_theme": theme}
        
        # אם set_as_default=true, עדכן גם את ui_prefs.theme
        if theme["is_active"]:
            update_doc["ui_prefs.theme"] = "custom"
        
        db.users.update_one(
            {"user_id": user_id},
            {"$set": update_doc},
            upsert=True
        )
        
        logger.info(f"User {user_id} saved custom theme: {name}")
        
        return jsonify({
            "ok": True,
            "message": "התמה נשמרה בהצלחה",
            "theme": theme
        })
        
    except Exception as e:
        logger.error(f"Error saving custom theme: {e}", exc_info=True)
        return jsonify({
            "ok": False,
            "error": "שגיאה פנימית בשמירת התמה"
        }), 500
```

---

### מיקום 6: API למחיקת Theme

**איפה להוסיף:** מיד אחרי `/api/themes/save`

```python
@app.route('/api/themes/custom', methods=['DELETE'])
@login_required
def delete_custom_theme():
    """
    מחיקת Theme מותאם אישית והחזרה לתמה ברירת מחדל (classic).
    
    Returns:
        JSON: {"ok": bool, "message": str}
    """
    try:
        db = get_db()
        user_id = session['user_id']
        
        # מחיקת custom_theme והחזרת theme לברירת מחדל
        result = db.users.update_one(
            {"user_id": user_id},
            {
                "$unset": {"custom_theme": ""},
                "$set": {"ui_prefs.theme": "classic"}
            }
        )
        
        logger.info(f"User {user_id} deleted custom theme")
        
        return jsonify({
            "ok": True,
            "message": "התמה המותאמת נמחקה, חזרה לברירת מחדל"
        })
        
    except Exception as e:
        logger.error(f"Error deleting custom theme: {e}", exc_info=True)
        return jsonify({
            "ok": False,
            "error": "שגיאה במחיקת התמה"
        }), 500
```

---

## 🎨 שינויים ב-`webapp/templates/base.html`

### מיקום: בתוך `<head>`, אחרי הגדרות הטוקנים

**איפה למצוא:** חפש את `</style>` (סוף הגדרת הטוקנים הקיימת)

**שורה משוערת:** ~3100 (סוף הטוקנים)

```html
    </style>
    
    <!-- ← הוסף כאן: Custom User Theme -->
    {% if current_user and current_user.is_authenticated %}
    {% set user_doc = db.users.find_one({"user_id": session.user_id}, {"custom_theme": 1}) %}
    {% if user_doc and user_doc.custom_theme and user_doc.custom_theme.is_active %}
    <style id="user-custom-theme">
        :root[data-theme="custom"] {
            {% for token, value in user_doc.custom_theme.variables.items() %}
            {{ token }}: {{ value }};
            {% endfor %}
        }
    </style>
    <script>
        // קביעת data-theme="custom" אם התמה המותאמת פעילה
        (function() {
            try {
                document.documentElement.setAttribute('data-theme', 'custom');
                localStorage.setItem('dark_mode_preference', 'custom');
            } catch(_) {
                // שגיאה בגישה ל-localStorage, התעלם
            }
        })();
    </script>
    {% endif %}
    {% endif %}
    <!-- סוף Custom User Theme -->
```

**הערה חשובה:** קוד זה דורש ש-`inject_db()` context processor פועל (ראה מיקום 3).

---

## ⚙️ שינויים ב-`webapp/templates/settings.html`

### מיקום: אחרי קטע "העדפות תצוגה"

**איפה למצוא:** חפש `<h2>העדפות תצוגה</h2>` (שורה ~391)

**שורה משוערת:** ~481 (אחרי סגירת ה-card של העדפות תצוגה)

```html
</div>
<!-- סוף העדפות תצוגה -->

<!-- ← הוסף כאן: -->
<div class="glass-card">
  <h2 class="section-title">
    <i class="fas fa-palette"></i>
    בונה ערכות נושא
  </h2>
  <div class="glass-card" style="background: rgba(255, 255, 255, 0.05)">
    <div
      style="
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 1rem;
        flex-wrap: wrap;
      "
    >
      <div style="display: flex; align-items: center; gap: 1rem">
        <i class="fas fa-paint-brush" style="font-size: 1.5rem"></i>
        <div>
          <div style="font-weight: 600">יצירת תמה מותאמת אישית</div>
          <div style="opacity: 0.8; font-size: 0.95rem">
            בנה ערכת צבעים ייחודית עם בקרה מלאה על כל האלמנטים
          </div>
        </div>
      </div>
      <a href="/settings/theme-builder" class="btn btn-primary btn-icon">
        <i class="fas fa-arrow-left"></i>
        פתח את הבונה
      </a>
    </div>
  </div>
</div>
<!-- סוף בונה ערכות נושא -->
```

---

## 📄 קובץ חדש: `webapp/templates/settings/theme_builder.html`

**צור תיקייה חדשה:** `webapp/templates/settings/` (אם לא קיימת)

**צור קובץ:** `theme_builder.html`

**תוכן:** ראה את הקוד המלא ב-[THEME_BUILDER_IMPLEMENTATION_GUIDE.md](./THEME_BUILDER_IMPLEMENTATION_GUIDE.md), סעיף 4.1.

**גודל משוער:** ~500 שורות (HTML + CSS + JS)

---

## 🗂️ מבנה MongoDB – לא דורש שינויים

MongoDB הוא schema-less, לכן פשוט נוסיף שדות חדשים:

```json
{
  "_id": ObjectId("..."),
  "user_id": 123,
  "ui_prefs": {
    "theme": "custom",      ← אם התמה המותאמת פעילה
    "font_scale": 1.0
  },
  "custom_theme": {          ← שדה חדש!
    "name": "My Dark Theme",
    "description": "...",
    "is_active": true,
    "updated_at": ISODate("..."),
    "variables": {
      "--bg-primary": "#1a1a2e",
      "--primary": "#667eea",
      ...
    }
  }
}
```

**אין צורך ליצור מיגרציה.**

---

## 🧪 בדיקות Integration

### בדיקה 1: Context Processor עובד

**בדוק:**
```python
# ב-Flask shell:
with app.app_context():
    with app.test_request_context():
        result = inject_db()
        assert 'db' in result
        print("✅ Context processor עובד")
```

### בדיקה 2: נתיב Theme Builder נטען

**בדוק:**
```bash
curl -I http://localhost:5000/settings/theme-builder
# צריך להחזיר 200 (או 302 redirect ל-login)
```

### בדיקה 3: API לשמירה עובד

**בדוק:**
```bash
curl -X POST http://localhost:5000/api/themes/save \
  -H "Content-Type: application/json" \
  -H "Cookie: session=<YOUR_SESSION>" \
  -d '{
    "name": "Test",
    "colors": {
      "background": "#1a1a2e",
      "card_bg": "rgba(255,255,255,0.1)",
      "primary": "#667eea",
      "secondary": "#764ba2",
      "text": "#f5f5f5"
    },
    "glass": {
      "rgba": "rgba(255,255,255,0.1)",
      "border": "rgba(255,255,255,0.2)",
      "hover": "rgba(255,255,255,0.15)",
      "blur": 20
    },
    "markdown": {
      "surface": "#1b1e24",
      "text": "#f0f0f0"
    }
  }'
```

### בדיקה 4: Theme מוזרק ב-base.html

**בדוק:**
1. שמור Theme דרך ה-API
2. רענן דף כלשהו (למשל `/settings`)
3. פתח DevTools → Elements → `<head>`
4. וודא שיש `<style id="user-custom-theme">`

---

## ⚠️ נקודות תשומת לב

### 1. Session ו-Authentication
וודא שה-endpoints מוגנים עם `@login_required` כדי למנוע גישה לא מורשית.

### 2. Performance
הזרקת התמה ב-`base.html` עושה שאילתה ל-MongoDB בכל בקשה. במידת הצורך, שקול caching:
```python
# דוגמה פשוטה (לא לייצור):
from flask_caching import Cache
cache = Cache(app, config={'CACHE_TYPE': 'simple'})

@cache.memoize(timeout=300)  # 5 דקות
def get_user_custom_theme(user_id):
    db = get_db()
    user_doc = db.users.find_one({"user_id": user_id}, {"custom_theme": 1})
    return user_doc.get("custom_theme") if user_doc else None
```

### 3. XSS Protection
הטוקנים עוברים דרך Jinja2 שמבצע escaping אוטומטי, אך וודא שהולידציה ב-API תקינה.

### 4. CORS (אם רלוונטי)
אם יש frontend נפרד, וודא ש-CORS מאפשר POST/DELETE ל-`/api/themes/*`.

---

## 📚 התייחסות למסמכים אחרים

- **מדריך מלא:** [THEME_BUILDER_IMPLEMENTATION_GUIDE.md](./THEME_BUILDER_IMPLEMENTATION_GUIDE.md)
- **התחלה מהירה:** [THEME_BUILDER_QUICK_START.md](./THEME_BUILDER_QUICK_START.md)
- **תיעוד טוקנים:** `docs/webapp/theming_and_css.rst`

---

**סיימת? עבור לבדיקות!** ✅
