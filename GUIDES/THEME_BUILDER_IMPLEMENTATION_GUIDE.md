# מדריך מימוש Theme Builder – הנחיות צעד אחר צעד

> **תאריך:** דצמבר 2024  
> **גרסת אישו:** #2097 – Theme Builder Interface  
> **תאימות:** Python 3.11+, Flask, MongoDB, Pickr.js  

---

## תוכן עניינים

1. [סקירה כללית](#1-סקירה-כללית)
2. [ארכיטקטורת הטוקנים הקיימת](#2-ארכיטקטורת-הטוקנים-הקיימת)
3. [צעדי המימוש – שלב א: Backend](#3-צעדי-המימוש--שלב-א-backend)
4. [צעדי המימוש – שלב ב: Frontend](#4-צעדי-המימוש--שלב-ב-frontend)
5. [צעדי המימוש – שלב ג: Live Preview](#5-צעדי-המימוש--שלב-ג-live-preview)
6. [צעדי המימוש – שלב ד: Integration](#6-צעדי-המימוש--שלב-ד-integration)
7. [בדיקות ונגישות](#7-בדיקות-ונגישות)
8. [FAQ ופתרון בעיות](#8-faq-ופתרון-בעיות)

---

## 1. סקירה כללית

### 1.1 מטרות הפיצ׳ר

Theme Builder מאפשר למשתמשים:
- ✅ לבנות ערכת נושא מותאמת אישית מהממשק
- ✅ לראות תצוגה מקדימה חיה (Live Preview) ללא השפעה על שאר ה-UI
- ✅ לשמור Theme יחיד ב-`users.custom_theme` במסד הנתונים
- ✅ להחיל את הנושא אוטומטית דרך `<style id="user-custom-theme">`
- ✅ לשלוט בשקיפות וב-blur של Glass effects

### 1.2 מה כבר קיים בפרויקט?

הפרויקט כולל כבר:
- **מערכת טוקנים:** טוקנים מוגדרים ב-`base.html` עבור 8 תמות (classic, ocean, forest, dark, dim, nebula, rose-pine-dawn, high-contrast)
- **API להעדפות UI:** `/api/ui_prefs` מטפל כבר בשמירת theme ו-font_scale
- **דף הגדרות:** `settings.html` מאפשר בחירת תמה קיימת דרך dropdown
- **תיעוד מפורט:** `docs/webapp/theming_and_css.rst` מתאר את מערכת הטוקנים

### 1.3 מה נוסיף?

- ✨ דף חדש: `/settings/theme-builder` עם פאנלים 50/50 (Controls + Live Preview)
- ✨ API חדש: `/api/themes/save` (POST) ו-`/api/themes/custom` (DELETE)
- ✨ תמיכה ב-Pickr.js עם RGBA + סליידרים לשקיפות ו-blur
- ✨ הזרקה דינמית של `<style id="user-custom-theme">` ב-`base.html`

---

## 2. ארכיטקטורת הטוקנים הקיימת

### 2.1 טוקנים במיקוד

הטוקנים שה-Theme Builder יאפשר לערוך:

| קבוצה | טוקנים | תיאור |
|-------|---------|--------|
| **רקעים** | `--bg-primary`, `--bg-secondary`, `--card-bg` | רקעי הדף, כרטיסים |
| **אקסנטים** | `--primary`, `--secondary` | צבעי מותג |
| **טקסט** | `--text-primary`, `--text-secondary` | טקסט ראשי ומשני |
| **Glass** | `--glass`, `--glass-border`, `--glass-hover`, `--glass-blur` | אפקט זכוכית |
| **Markdown** | `--md-surface`, `--md-text` | רקע וטקסט ב-Markdown Viewer |

### 2.2 איפה הטוקנים מוגדרים?

ב-`webapp/templates/base.html`, בתוך `<style>` ב-`<head>`:

```html
<style>
    :root {
        --primary: #667eea;
        --secondary: #764ba2;
        --glass: rgba(255, 255, 255, 0.1);
        /* ... */
    }
    
    :root[data-theme="classic"] {
        --bg-primary: #6b63ff;
        --text-primary: #ffffff;
        /* ... */
    }
</style>
```

### 2.3 איך התמה נקבעת?

1. **localStorage:** שמור בדפדפן תחת `dark_mode_preference`
2. **סקריפט מוקדם:** ב-`base.html` קובע `data-theme` על `<html>` לפני טעינת CSS
3. **שרת:** שומר ב-`db.users` תחת `ui_prefs.theme`

---

## 3. צעדי המימוש – שלב א: Backend

### 3.1 הוספת תמיכה ב-custom_theme במודל המשתמש

**קובץ:** `webapp/app.py` (לא נדרש שינוי במבנה, MongoDB גמיש)

המסמך ב-`db.users` יכלול:

```python
{
    "user_id": 123,
    "ui_prefs": {
        "theme": "custom",  # או שם תמה אחר
        "font_scale": 1.0
    },
    "custom_theme": {
        "name": "My Theme",
        "description": "תיאור התמה",
        "is_active": True,
        "updated_at": ISODate("2024-12-12T10:00:00Z"),
        "variables": {
            "--bg-primary": "#1a1a2e",
            "--bg-secondary": "#16213e",
            "--card-bg": "rgba(255,255,255,0.08)",
            "--primary": "#667eea",
            "--secondary": "#764ba2",
            "--text-primary": "#f5f5f5",
            "--text-secondary": "rgba(255,255,255,0.8)",
            "--glass": "rgba(255,255,255,0.1)",
            "--glass-border": "rgba(255,255,255,0.2)",
            "--glass-hover": "rgba(255,255,255,0.15)",
            "--glass-blur": "20px",
            "--md-surface": "#1b1e24",
            "--md-text": "#f0f0f0"
        }
    }
}
```

### 3.2 הוספת נתיב `/settings/theme-builder`

**קובץ:** `webapp/app.py`

```python
@app.route('/settings/theme-builder')
@login_required
def theme_builder():
    """דף Theme Builder עם Live Preview"""
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

**הערות:**
- `@login_required` – רק משתמשים מחוברים
- מחזיר את ה-theme השמור (אם קיים) כדי למלא את הטופס

### 3.3 הוספת API לשמירת Theme

**קובץ:** `webapp/app.py`

```python
import re
from datetime import datetime, timezone

# קבועים לולידציה
VALID_COLOR_REGEX = r'^(#[0-9a-fA-F]{6}|rgba?\(.+\))$'
MAX_THEME_NAME_LENGTH = 50
REQUIRED_THEME_TOKENS = {
    "--bg-primary", "--bg-secondary", "--card-bg",
    "--primary", "--secondary",
    "--text-primary", "--text-secondary",
    "--glass", "--glass-border", "--glass-hover", "--glass-blur",
    "--md-surface", "--md-text"
}

@app.route('/api/themes/save', methods=['POST'])
@login_required
def save_custom_theme():
    """
    שמירת Theme מותאם אישית.
    
    Body (JSON):
    {
        "name": "My Theme",
        "description": "תיאור",
        "set_as_default": true,
        "colors": {
            "background": "#1a1a2e",
            "background_alt": "#16213e",
            "card_bg": "rgba(255,255,255,0.08)",
            "primary": "#667eea",
            "secondary": "#764ba2",
            "text": "#f5f5f5",
            "text_secondary": "rgba(255,255,255,0.8)"
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
    }
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
        
        # בדיקת צבעים
        def validate_color(val):
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
        
        return jsonify({
            "ok": True,
            "message": "התמה נשמרה בהצלחה",
            "theme": theme
        })
        
    except Exception as e:
        logger.error(f"Error saving custom theme: {e}", exc_info=True)
        return jsonify({
            "ok": False,
            "error": "שגיאה בשמירת התמה"
        }), 500
```

### 3.4 הוספת API למחיקת Theme

**קובץ:** `webapp/app.py`

```python
@app.route('/api/themes/custom', methods=['DELETE'])
@login_required
def delete_custom_theme():
    """מחיקת Theme מותאם אישית והחזרה לתמה ברירת מחדל"""
    try:
        db = get_db()
        user_id = session['user_id']
        
        # מחיקת custom_theme והחזרת theme לברירת מחדל
        db.users.update_one(
            {"user_id": user_id},
            {
                "$unset": {"custom_theme": ""},
                "$set": {"ui_prefs.theme": "classic"}
            }
        )
        
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

## 4. צעדי המימוש – שלב ב: Frontend

### 4.1 יצירת תבנית `/settings/theme_builder.html`

**קובץ:** `webapp/templates/settings/theme_builder.html`

```html
{% extends "base.html" %}
{% block title %}בונה ערכות נושא - Code Keeper Bot{% endblock %}

{% block content %}
<div class="theme-builder-container">
    <h1 class="page-title">
        <i class="fas fa-palette"></i>
        בונה ערכות נושא
    </h1>
    
    <!-- הסבר קצר -->
    <div class="glass-card info-card">
        <p>
            צור ערכת נושא מותאמת אישית עם צבעים, שקיפות ו-blur.
            התצוגה המקדימה משקפת את השינויים בזמן אמת, אך לא משפיעה על שאר הדף עד לשמירה.
        </p>
    </div>
    
    <!-- Layout: שני פאנלים -->
    <div class="builder-layout">
        
        <!-- פאנל שמאל: Controls -->
        <div class="builder-panel controls-panel">
            <h2><i class="fas fa-sliders-h"></i> הגדרות</h2>
            
            <!-- שם ותיאור -->
            <div class="form-group">
                <label for="themeName">שם התמה</label>
                <input 
                    type="text" 
                    id="themeName" 
                    class="form-input" 
                    placeholder="התמה שלי"
                    maxlength="50"
                    aria-describedby="themeNameHelp"
                />
                <small id="themeNameHelp" class="form-help">עד 50 תווים</small>
            </div>
            
            <div class="form-group">
                <label for="themeDesc">תיאור (אופציונלי)</label>
                <textarea 
                    id="themeDesc" 
                    class="form-input" 
                    rows="2" 
                    placeholder="תיאור קצר"
                    maxlength="200"
                ></textarea>
            </div>
            
            <!-- קבוצת רקעים -->
            <div class="color-section">
                <h3><i class="fas fa-image"></i> רקעים</h3>
                <div class="color-grid">
                    <div class="color-item">
                        <label for="bgPrimary">רקע ראשי</label>
                        <input type="text" id="bgPrimary" class="color-input" />
                    </div>
                    <div class="color-item">
                        <label for="bgSecondary">רקע משני</label>
                        <input type="text" id="bgSecondary" class="color-input" />
                    </div>
                    <div class="color-item">
                        <label for="cardBg">רקע כרטיסים</label>
                        <input type="text" id="cardBg" class="color-input" />
                    </div>
                </div>
            </div>
            
            <!-- קבוצת אקסנטים -->
            <div class="color-section">
                <h3><i class="fas fa-star"></i> צבעי מותג</h3>
                <div class="color-grid">
                    <div class="color-item">
                        <label for="primary">צבע ראשי</label>
                        <input type="text" id="primary" class="color-input" />
                    </div>
                    <div class="color-item">
                        <label for="secondary">צבע משני</label>
                        <input type="text" id="secondary" class="color-input" />
                    </div>
                </div>
            </div>
            
            <!-- קבוצת טקסט -->
            <div class="color-section">
                <h3><i class="fas fa-font"></i> טקסט</h3>
                <div class="color-grid">
                    <div class="color-item">
                        <label for="textPrimary">טקסט ראשי</label>
                        <input type="text" id="textPrimary" class="color-input" />
                    </div>
                    <div class="color-item">
                        <label for="textSecondary">טקסט משני</label>
                        <input type="text" id="textSecondary" class="color-input" />
                    </div>
                </div>
            </div>
            
            <!-- קבוצת Glass -->
            <div class="color-section">
                <h3><i class="fas fa-glasses"></i> Glass Effects</h3>
                <div class="color-grid">
                    <div class="color-item">
                        <label for="glass">Glass Base</label>
                        <input type="text" id="glass" class="color-input" />
                    </div>
                    <div class="color-item">
                        <label for="glassBorder">Glass Border</label>
                        <input type="text" id="glassBorder" class="color-input" />
                    </div>
                    <div class="color-item">
                        <label for="glassHover">Glass Hover</label>
                        <input type="text" id="glassHover" class="color-input" />
                    </div>
                </div>
                
                <!-- סליידר Blur -->
                <div class="slider-group">
                    <label for="glassBlur">
                        Blur:
                        <span id="glassBlurValue">20px</span>
                    </label>
                    <input 
                        type="range" 
                        id="glassBlur" 
                        min="0" 
                        max="50" 
                        step="1" 
                        value="20"
                        aria-describedby="glassBlurHelp"
                    />
                    <small id="glassBlurHelp" class="form-help">עוצמת הטשטוש</small>
                </div>
            </div>
            
            <!-- קבוצת Markdown -->
            <div class="color-section">
                <h3><i class="fab fa-markdown"></i> Markdown Viewer</h3>
                <div class="color-grid">
                    <div class="color-item">
                        <label for="mdSurface">רקע Markdown</label>
                        <input type="text" id="mdSurface" class="color-input" />
                    </div>
                    <div class="color-item">
                        <label for="mdText">טקסט Markdown</label>
                        <input type="text" id="mdText" class="color-input" />
                    </div>
                </div>
            </div>
            
            <!-- אפשרויות שמירה -->
            <div class="form-group">
                <label>
                    <input type="checkbox" id="setAsDefault" />
                    הפעל כתמה ברירת מחדל
                </label>
            </div>
            
            <!-- כפתורי פעולה -->
            <div class="action-buttons">
                <button id="saveThemeBtn" class="btn btn-primary btn-icon">
                    <i class="fas fa-save"></i>
                    שמור תמה
                </button>
                <button id="resetThemeBtn" class="btn btn-secondary btn-icon">
                    <i class="fas fa-undo"></i>
                    איפוס
                </button>
                <button id="deleteThemeBtn" class="btn btn-danger btn-icon">
                    <i class="fas fa-trash"></i>
                    מחק תמה מותאמת
                </button>
            </div>
        </div>
        
        <!-- פאנל ימין: Live Preview -->
        <div class="builder-panel preview-panel" id="livePreview">
            <h2><i class="fas fa-eye"></i> תצוגה מקדימה</h2>
            
            <div class="preview-content">
                <!-- Navbar דמה -->
                <div class="preview-navbar">
                    <div class="preview-logo">Code Keeper</div>
                    <div class="preview-nav-links">
                        <a href="#" class="preview-link">דף הבית</a>
                        <a href="#" class="preview-link">הקבצים שלי</a>
                    </div>
                </div>
                
                <!-- כרטיס קובץ דמה -->
                <div class="preview-card">
                    <div class="preview-card-header">
                        <i class="fas fa-file-code"></i>
                        example.py
                    </div>
                    <div class="preview-card-body">
                        <pre class="preview-code">def hello():
    print("Hello World!")</pre>
                    </div>
                    <div class="preview-card-footer">
                        <button class="preview-btn preview-btn-primary">
                            <i class="fas fa-eye"></i>
                            צפה
                        </button>
                        <button class="preview-btn preview-btn-secondary">
                            <i class="fas fa-edit"></i>
                            ערוך
                        </button>
                    </div>
                </div>
                
                <!-- בלוק טקסט -->
                <div class="preview-text">
                    <p class="preview-text-primary">זהו טקסט ראשי</p>
                    <p class="preview-text-secondary">זהו טקסט משני</p>
                </div>
            </div>
        </div>
    </div>
</div>

<!-- Toast להודעות -->
<div id="toast" class="toast" role="alert"></div>

<style>
/* Theme Builder Styles */
.theme-builder-container {
    max-width: 100%;
    margin: 0 auto;
    padding: 2rem 1rem;
}

.info-card {
    margin-bottom: 2rem;
    padding: 1rem 1.5rem;
}

.builder-layout {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 2rem;
}

@media (max-width: 1024px) {
    .builder-layout {
        grid-template-columns: 1fr;
    }
}

.builder-panel {
    background: var(--card-bg);
    border: 1px solid var(--glass-border);
    border-radius: 16px;
    padding: 2rem;
    min-height: 600px;
}

.builder-panel h2 {
    margin-bottom: 1.5rem;
    display: flex;
    align-items: center;
    gap: 0.75rem;
    color: var(--text-primary);
}

.form-group {
    margin-bottom: 1.5rem;
}

.form-group label {
    display: block;
    margin-bottom: 0.5rem;
    font-weight: 500;
    color: var(--text-primary);
}

.form-input {
    width: 100%;
    padding: 0.75rem;
    border-radius: 8px;
    border: 1px solid var(--glass-border);
    background: var(--bg-tertiary, rgba(255,255,255,0.05));
    color: var(--text-primary);
    font-family: inherit;
    font-size: 1rem;
}

.form-help {
    display: block;
    margin-top: 0.25rem;
    opacity: 0.7;
    font-size: 0.875rem;
}

.color-section {
    margin-bottom: 2rem;
    padding-bottom: 1.5rem;
    border-bottom: 1px solid var(--glass-border);
}

.color-section:last-of-type {
    border-bottom: none;
}

.color-section h3 {
    margin-bottom: 1rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 1.1rem;
    color: var(--text-primary);
}

.color-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 1rem;
}

.color-item label {
    display: block;
    margin-bottom: 0.5rem;
    font-size: 0.9rem;
    color: var(--text-secondary);
}

.color-input {
    width: 100%;
    padding: 0.5rem;
    border-radius: 6px;
    border: 1px solid var(--glass-border);
    background: var(--bg-tertiary, rgba(255,255,255,0.05));
    color: var(--text-primary);
    cursor: pointer;
}

.slider-group {
    margin-top: 1rem;
}

.slider-group label {
    display: flex;
    justify-content: space-between;
    margin-bottom: 0.5rem;
    font-weight: 500;
}

.slider-group input[type="range"] {
    width: 100%;
}

.action-buttons {
    display: flex;
    gap: 0.75rem;
    flex-wrap: wrap;
    margin-top: 2rem;
}

.btn-danger {
    background: var(--danger, #f56565);
    color: white;
}

.btn-danger:hover {
    opacity: 0.9;
}

/* Preview Panel */
.preview-panel {
    background: var(--bg-primary);
    position: sticky;
    top: 2rem;
}

.preview-content {
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
}

.preview-navbar {
    background: var(--glass);
    backdrop-filter: blur(var(--glass-blur, 20px));
    border: 1px solid var(--glass-border);
    border-radius: 12px;
    padding: 1rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.preview-logo {
    font-weight: 600;
    font-size: 1.1rem;
    color: var(--text-primary);
}

.preview-nav-links {
    display: flex;
    gap: 1rem;
}

.preview-link {
    color: var(--text-primary);
    text-decoration: none;
    opacity: 0.85;
    transition: opacity 0.2s;
}

.preview-link:hover {
    opacity: 1;
}

.preview-card {
    background: var(--card-bg);
    border: 1px solid var(--glass-border);
    border-radius: 12px;
    overflow: hidden;
}

.preview-card-header {
    background: var(--glass);
    padding: 1rem;
    font-weight: 500;
    color: var(--text-primary);
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.preview-card-body {
    padding: 1.5rem;
}

.preview-code {
    background: var(--md-surface);
    color: var(--md-text);
    padding: 1rem;
    border-radius: 8px;
    font-family: 'Courier New', monospace;
    font-size: 0.9rem;
    overflow-x: auto;
}

.preview-card-footer {
    padding: 1rem;
    display: flex;
    gap: 0.5rem;
    border-top: 1px solid var(--glass-border);
}

.preview-btn {
    padding: 0.5rem 1rem;
    border-radius: 8px;
    border: none;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-family: inherit;
    transition: all 0.2s;
}

.preview-btn-primary {
    background: var(--primary);
    color: white;
}

.preview-btn-secondary {
    background: var(--glass);
    border: 1px solid var(--glass-border);
    color: var(--text-primary);
}

.preview-btn:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
}

.preview-text {
    padding: 1rem;
}

.preview-text-primary {
    color: var(--text-primary);
    font-size: 1rem;
    margin-bottom: 0.5rem;
}

.preview-text-secondary {
    color: var(--text-secondary);
    font-size: 0.9rem;
}

/* Toast */
.toast {
    position: fixed;
    bottom: 2rem;
    left: 50%;
    transform: translateX(-50%) translateY(100px);
    background: var(--card-bg);
    color: var(--text-primary);
    padding: 1rem 1.5rem;
    border-radius: 8px;
    border: 1px solid var(--glass-border);
    box-shadow: 0 8px 24px rgba(0,0,0,0.25);
    z-index: 10000;
    opacity: 0;
    transition: all 0.3s ease;
}

.toast.show {
    opacity: 1;
    transform: translateX(-50%) translateY(0);
}

.toast.error {
    border-color: var(--danger);
    background: var(--danger-bg);
}

.toast.success {
    border-color: var(--success);
    background: rgba(74, 222, 128, 0.15);
}
</style>

<script src="https://cdn.jsdelivr.net/npm/@simonwep/pickr/dist/pickr.min.js"></script>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@simonwep/pickr/dist/themes/nano.min.css"/>

<script>
(function() {
    'use strict';
    
    // תצוגה מקדימה
    const preview = document.getElementById('livePreview');
    
    // Pickr instances
    const pickers = {};
    
    // ערכי ברירת מחדל
    const defaults = {
        bgPrimary: '#1a1a2e',
        bgSecondary: '#16213e',
        cardBg: 'rgba(255,255,255,0.08)',
        primary: '#667eea',
        secondary: '#764ba2',
        textPrimary: '#f5f5f5',
        textSecondary: 'rgba(255,255,255,0.8)',
        glass: 'rgba(255,255,255,0.1)',
        glassBorder: 'rgba(255,255,255,0.2)',
        glassHover: 'rgba(255,255,255,0.15)',
        glassBlur: 20,
        mdSurface: '#1b1e24',
        mdText: '#f0f0f0'
    };
    
    // אתחול Pickr לכל קלט צבע
    function initPicker(id, defaultColor) {
        const el = document.getElementById(id);
        if (!el) return;
        
        const pickr = Pickr.create({
            el: el,
            theme: 'nano',
            default: defaultColor,
            swatches: [
                '#667eea', '#764ba2', '#f56565', '#48bb78',
                '#ed8936', '#4299e1', '#2d3748', '#f7fafc'
            ],
            components: {
                preview: true,
                opacity: true,
                hue: true,
                interaction: {
                    hex: true,
                    rgba: true,
                    input: true,
                    save: true
                }
            }
        });
        
        pickr.on('change', (color) => {
            updatePreview(id, color.toRGBA().toString());
        });
        
        pickers[id] = pickr;
    }
    
    // עדכון תצוגה מקדימה
    function updatePreview(varName, value) {
        const tokenMap = {
            'bgPrimary': '--bg-primary',
            'bgSecondary': '--bg-secondary',
            'cardBg': '--card-bg',
            'primary': '--primary',
            'secondary': '--secondary',
            'textPrimary': '--text-primary',
            'textSecondary': '--text-secondary',
            'glass': '--glass',
            'glassBorder': '--glass-border',
            'glassHover': '--glass-hover',
            'mdSurface': '--md-surface',
            'mdText': '--md-text'
        };
        
        const token = tokenMap[varName];
        if (token && preview) {
            preview.style.setProperty(token, value);
        }
    }
    
    // אתחול סליידר Blur
    const blurSlider = document.getElementById('glassBlur');
    const blurValue = document.getElementById('glassBlurValue');
    
    if (blurSlider && blurValue) {
        blurSlider.addEventListener('input', (e) => {
            const val = e.target.value;
            blurValue.textContent = val + 'px';
            if (preview) {
                preview.style.setProperty('--glass-blur', val + 'px');
            }
        });
    }
    
    // אתחול Pickers
    Object.keys(defaults).forEach(key => {
        if (key !== 'glassBlur') {
            initPicker(key, defaults[key]);
        }
    });
    
    // טעינת Theme שמור
    const savedTheme = {{ saved_theme|tojson if saved_theme else 'null' }};
    if (savedTheme && savedTheme.variables) {
        // TODO: מלא את הטופס עם ערכים שמורים
    }
    
    // שמירת Theme
    document.getElementById('saveThemeBtn')?.addEventListener('click', async () => {
        const name = document.getElementById('themeName').value.trim();
        if (!name) {
            showToast('נא להזין שם לתמה', 'error');
            return;
        }
        
        const data = {
            name: name,
            description: document.getElementById('themeDesc').value.trim(),
            set_as_default: document.getElementById('setAsDefault').checked,
            colors: {
                background: pickers.bgPrimary.getColor().toRGBA().toString(),
                background_alt: pickers.bgSecondary.getColor().toRGBA().toString(),
                card_bg: pickers.cardBg.getColor().toRGBA().toString(),
                primary: pickers.primary.getColor().toRGBA().toString(),
                secondary: pickers.secondary.getColor().toRGBA().toString(),
                text: pickers.textPrimary.getColor().toRGBA().toString(),
                text_secondary: pickers.textSecondary.getColor().toRGBA().toString()
            },
            glass: {
                rgba: pickers.glass.getColor().toRGBA().toString(),
                border: pickers.glassBorder.getColor().toRGBA().toString(),
                hover: pickers.glassHover.getColor().toRGBA().toString(),
                blur: parseInt(blurSlider.value)
            },
            markdown: {
                surface: pickers.mdSurface.getColor().toRGBA().toString(),
                text: pickers.mdText.getColor().toRGBA().toString()
            }
        };
        
        try {
            const res = await fetch('/api/themes/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            
            const result = await res.json();
            
            if (result.ok) {
                showToast('התמה נשמרה בהצלחה! רענן את הדף כדי לראות את השינויים', 'success');
            } else {
                showToast(result.error || 'שגיאה בשמירה', 'error');
            }
        } catch (e) {
            showToast('שגיאת רשת', 'error');
        }
    });
    
    // איפוס
    document.getElementById('resetThemeBtn')?.addEventListener('click', () => {
        Object.keys(defaults).forEach(key => {
            if (key === 'glassBlur') {
                blurSlider.value = defaults[key];
                blurValue.textContent = defaults[key] + 'px';
                preview.style.setProperty('--glass-blur', defaults[key] + 'px');
            } else if (pickers[key]) {
                pickers[key].setColor(defaults[key]);
                updatePreview(key, defaults[key]);
            }
        });
        showToast('הערכים אופסו לברירת מחדל', 'success');
    });
    
    // מחיקת Theme
    document.getElementById('deleteThemeBtn')?.addEventListener('click', async () => {
        if (!confirm('האם אתה בטוח שברצונך למחוק את התמה המותאמת?')) return;
        
        try {
            const res = await fetch('/api/themes/custom', {
                method: 'DELETE'
            });
            
            const result = await res.json();
            
            if (result.ok) {
                showToast('התמה נמחקה', 'success');
                setTimeout(() => location.reload(), 1500);
            } else {
                showToast(result.error || 'שגיאה במחיקה', 'error');
            }
        } catch (e) {
            showToast('שגיאת רשת', 'error');
        }
    });
    
    // Toast
    function showToast(message, type = 'info') {
        const toast = document.getElementById('toast');
        if (!toast) return;
        
        toast.textContent = message;
        toast.className = 'toast show ' + type;
        
        setTimeout(() => {
            toast.classList.remove('show');
        }, 4000);
    }
})();
</script>
{% endblock %}
```

---

## 5. צעדי המימוש – שלב ג: Live Preview

### 5.1 עקרון עבודה

ה-Live Preview עובד על ידי:
1. **בידוד:** פאנל Preview מקבל `id="livePreview"`
2. **עדכון דינמי:** כל שינוי ב-Pickr מעדכן את `preview.style.setProperty(token, value)`
3. **לא משפיע על שאר הדף:** רק הפאנל Preview מעודכן, שאר הדף ממשיך לעבוד עם התמה הנוכחית

### 5.2 מיפוי טוקנים

הטבלה הזו מסבירה את המיפוי בין שדות הטופס לטוקנים:

| שדה בטופס | טוקן CSS | דוגמה |
|-----------|----------|--------|
| `bgPrimary` | `--bg-primary` | `#1a1a2e` |
| `bgSecondary` | `--bg-secondary` | `#16213e` |
| `cardBg` | `--card-bg` | `rgba(255,255,255,0.08)` |
| `primary` | `--primary` | `#667eea` |
| `secondary` | `--secondary` | `#764ba2` |
| `textPrimary` | `--text-primary` | `#f5f5f5` |
| `textSecondary` | `--text-secondary` | `rgba(255,255,255,0.8)` |
| `glass` | `--glass` | `rgba(255,255,255,0.1)` |
| `glassBorder` | `--glass-border` | `rgba(255,255,255,0.2)` |
| `glassHover` | `--glass-hover` | `rgba(255,255,255,0.15)` |
| `glassBlur` | `--glass-blur` | `20px` |
| `mdSurface` | `--md-surface` | `#1b1e24` |
| `mdText` | `--md-text` | `#f0f0f0` |

---

## 6. צעדי המימוש – שלב ד: Integration

### 6.1 הוספת לינק בדף ההגדרות

**קובץ:** `webapp/templates/settings.html`

הוסף קטע חדש אחרי "העדפות תצוגה":

```html
<div class="glass-card">
  <h2 class="section-title">
    <i class="fas fa-palette"></i>
    בונה ערכות נושא
  </h2>
  <div class="glass-card" style="background: rgba(255, 255, 255, 0.05)">
    <div style="display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap;">
      <div style="display: flex; align-items: center; gap: 1rem;">
        <i class="fas fa-paint-brush" style="font-size: 1.5rem;"></i>
        <div>
          <div style="font-weight: 600;">יצירת תמה מותאמת אישית</div>
          <div style="opacity: 0.8; font-size: 0.95rem;">
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
```

### 6.2 הזרקת custom_theme ב-base.html

**קובץ:** `webapp/templates/base.html`

הוסף בתוך `<head>`, אחרי הגדרת הטוקנים הקיימת:

```html
<!-- Custom User Theme -->
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
        } catch(_) {}
    })();
</script>
{% endif %}
{% endif %}
```

**הערה חשובה:** הקוד הזה דורש גישה ל-`db` בתבנית. צריך לוודא שה-context מכיל את `db`:

```python
# ב-webapp/app.py, בתחילת הקובץ או בפונקציה @app.before_request
@app.context_processor
def inject_db():
    """הזרקת db לכל התבניות"""
    return dict(db=get_db())
```

### 6.3 עדכון ALLOWED_UI_THEMES

**קובץ:** `webapp/app.py`

הוסף `"custom"` לרשימת התמות המותרות:

```python
ALLOWED_UI_THEMES = {
    "classic", "ocean", "forest", "high-contrast", 
    "dark", "dim", "rose-pine-dawn", "nebula",
    "custom"  # ← הוסף את זה
}
```

---

## 7. בדיקות ונגישות

### 7.1 בדיקות פונקציונליות

**צ'קליסט:**

- [ ] דף `/settings/theme-builder` נטען כראוי
- [ ] כל ה-Pickr instances נפתחים ומאפשרים בחירת צבע
- [ ] סליידר Blur עובד ומעדכן את הערך בזמן אמת
- [ ] Live Preview מתעדכן מיד עם כל שינוי
- [ ] שאר הדף לא מושפע מהשינויים בזמן העריכה
- [ ] לחיצה על "שמור תמה" שומרת ב-DB
- [ ] לחיצה על "איפוס" מחזירה לערכים הדיפולטיים
- [ ] לחיצה על "מחק תמה" מסירה את custom_theme מה-DB
- [ ] אם `set_as_default=true`, התמה מופעלת אוטומטית
- [ ] רענון הדף אחרי שמירה מציג את התמה החדשה

### 7.2 בדיקות נגישות

**WCAG 2.1 AA:**

- [ ] יחס ניגודיות ≥ 4.5:1 בין טקסט לרקע
- [ ] כל קלט צבע כולל `aria-describedby` ו-label ברור
- [ ] Toast מכיל `role="alert"`
- [ ] ניתן לנווט בין שדות עם Tab
- [ ] כפתורים כוללים אייקונים וטקסט ברור
- [ ] מסכים קוראי-מסך יכולים לקרוא את כל הפקדים

### 7.3 בדיקת Contrast (אופציונלי אבל מומלץ)

הוסף בדיקת ניגודיות ב-API:

```python
def check_contrast_ratio(fg_color, bg_color):
    """
    מחשב יחס ניגודיות בין צבע טקסט לרקע.
    מחזיר True אם עובר WCAG AA (≥4.5:1)
    """
    # TODO: פיתוח מלא עם ספריית colour או colorsys
    # לצורך הדוגמה, נניח שהפונקציה קיימת
    return True  # placeholder
```

---

## 8. FAQ ופתרון בעיות

### 8.1 שאלות נפוצות

**ש: האם אפשר לשמור יותר מתמה אחת?**  
ת: לא בגרסה הנוכחית. ה-spec מגדיר שמירת Theme יחיד בלבד. ניתן להרחיב בעתיד ל-`custom_themes` (מערך).

**ש: איך מחזירים לתמה ברירת מחדל?**  
ת: לחץ על "מחק תמה מותאמת" או בחר תמה אחרת מ-dropdown ב-`/settings`.

**ש: האם Pickr תומך ב-RTL?**  
ת: Pickr עצמו לא תומך ב-RTL מלא, אבל הפאנל נפתח תקין. אם יש בעיה, אפשר להוסיף CSS Override.

**ש: מה קורה אם המשתמש שומר צבעים לא תקינים?**  
ת: הולידציה ב-`/api/themes/save` דוחה ערכים שלא עוברים את `VALID_COLOR_REGEX`.

**ש: איך מוודאים שה-Theme נטען לפני כל שאר ה-CSS?**  
ת: `<style id="user-custom-theme">` מוזרק מיד אחרי הטוקנים הגלובליים ב-`<head>`, כך שהוא גובר עליהם.

### 8.2 פתרון בעיות נפוצות

**בעיה:** Live Preview לא מתעדכן  
**פתרון:** ודא ש-`preview.style.setProperty()` מקבל את הטוקן הנכון (עם `--`)

**בעיה:** Pickr לא נטען  
**פתרון:** ודא שה-CDN של Pickr זמין ושהסקריפט רץ אחרי טעינת הדף (`DOMContentLoaded`)

**בעיה:** התמה המותאמת לא מופיעה אחרי רענון  
**פתרון:** ודא ש-`is_active=true` ושה-context processor `inject_db()` פועל

**בעיה:** Toast לא מופיע  
**פתרון:** ודא שה-CSS של Toast כולל `z-index: 10000` ושהוא נמצא מחוץ לכל `overflow: hidden`

---

## סיכום

מדריך זה מכסה את כל השלבים הנדרשים למימוש Theme Builder:

1. **Backend:** API endpoints, ולידציה, שמירה ב-MongoDB
2. **Frontend:** תבנית HTML/CSS, Pickr integration, Live Preview
3. **Integration:** חיבור ל-base.html, הגדרות, context processor
4. **Testing:** בדיקות פונקציונליות ונגישות

**הצעדים הבאים:**
- [ ] פיתוח הקוד לפי המדריך
- [ ] בדיקות מקיפות על כל הדפדפנים
- [ ] בדיקת נגישות עם קורא מסך
- [ ] עדכון התיעוד ב-`docs/webapp/theming_and_css.rst`
- [ ] הוספת דוגמאות צילומי מסך ל-README

---

**מחבר המדריך:** AI Assistant  
**תאריך:** דצמבר 2024  
**לשאלות ותמיכה:** פנה לצוות הפיתוח או פתח Issue ב-GitHub
