# מדריך מימוש מתוקן: הרחבת כרטיסים (Expanded Card)

> **תאריך עדכון:** 2025-01-27  
> **מקור:** [Issue #1155](https://github.com/amirbiron/CodeBot/issues/1155)  
> **סטטוס:** מוכן למימוש - מתוקן

---

## 🎯 מה הפיצר הזה?

**תצוגת כרטיס מורחבת** – לחיצה על כפתור בתחתית הכרטיס בעמוד `/files` תרחיב את הכרטיס במקום (accordion-style) ותציג 15-20 שורות קוד ראשונות עם highlighting, ללא צורך לעבור לדף מלא.

### למה זה שימושי?

- **חיסכון בזמן** – לעיתים רוצים רק להציץ בקוד מהר
- **חוויית משתמש משופרת** – פחות טעינות דפים
- **זרימה טובה יותר** – הקשר נשמר באותו עמוד

---

## 🏗️ ארכיטקטורה כללית

```
┌─────────────────┐
│   files.html    │  ← כרטיסים עם כפתור "👁️ הצץ"
└────────┬────────┘
         │ (לחיצה)
         ↓
┌─────────────────┐
│   AJAX Call     │  → GET /api/file/<file_id>/preview
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│    app.py       │  ← מחזיר 20 שורות מודגשות (Pygments)
│  preview route  │
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│  JavaScript     │  ← מרחיב כרטיס + הצגת קוד
│  card-preview.js│
└─────────────────┘
```

---

## 📂 קבצים שצריך ליצור/לערוך

### ✅ קבצים חדשים
1. `webapp/static/js/card-preview.js` – לוגיקת הרחבת כרטיסים
2. `webapp/static/css/card-preview.css` – עיצוב הכרטיס המורחב

### ✏️ קבצים לעריכה
1. `webapp/app.py` – הוספת route חדש `/api/file/<file_id>/preview`
2. `webapp/templates/files.html` – הוספת כפתור "הצץ" וקישור לסקריפטים

---

## 🔧 שלב 1: יצירת API Endpoint

### `webapp/app.py` – הוספת Route חדש

**מיקום נכון:** הוסף את ה-route אחרי ה-function `view_file` (אחרי שורה ~3100), לא אחרי שורה 2997.

```python
@app.route('/api/file/<file_id>/preview')
@login_required
@traced("file.preview")
def file_preview(file_id):
    """
    מחזיר preview של הקוד (20 שורות ראשונות) עם syntax highlighting.
    משמש להצגת תוכן מקדים בתוך כרטיס מורחב.
    """
    db = get_db()
    user_id = session['user_id']
    
    # שליפת הקובץ מהמסד
    try:
        file = db.code_snippets.find_one({
            '_id': ObjectId(file_id),
            'user_id': user_id
        })
    except (InvalidId, TypeError):
        return jsonify({'ok': False, 'error': 'Invalid file ID'}), 400
    except PyMongoError as e:
        logger.exception("DB error fetching file preview", extra={
            "file_id": file_id,
            "user_id": user_id,
            "error": str(e)
        })
        return jsonify({'ok': False, 'error': 'Database error'}), 500
    
    if not file:
        return jsonify({'ok': False, 'error': 'File not found'}), 404
    
    # חילוץ קוד ושפה
    code = file.get('code', '')
    language = (file.get('programming_language') or 'text').lower()
    
    # בדיקה אם הקובץ ריק
    if not code or not code.strip():
        return jsonify({
            'ok': False, 
            'error': 'File is empty'
        }), 400
    
    # תיקון: אם הקובץ .md אך מתוייג כ-text
    try:
        if (not language or language == 'text') and str(file.get('file_name', '')).lower().endswith('.md'):
            language = 'markdown'
    except Exception:
        pass
    
    # בדיקה אם קובץ גדול או בינארי
    MAX_PREVIEW_SIZE = 100 * 1024  # 100KB
    if len(code.encode('utf-8')) > MAX_PREVIEW_SIZE:
        return jsonify({
            'ok': False,
            'error': 'File too large for preview',
            'size': len(code.encode('utf-8'))
        }), 413
    
    if is_binary_file(code, file.get('file_name', '')):
        return jsonify({
            'ok': False,
            'error': 'Binary file cannot be previewed'
        }), 400
    
    # חילוץ 20 שורות ראשונות
    lines = code.split('\n')
    total_lines = len(lines)
    preview_lines = min(20, total_lines)
    preview_code = '\n'.join(lines[:preview_lines])
    
    # Syntax highlighting עם Pygments
    try:
        lexer = get_lexer_by_name(language, stripall=True)
    except ClassNotFound:
        try:
            lexer = guess_lexer(preview_code)
        except ClassNotFound:
            lexer = get_lexer_by_name('text')
    
    # Formatter: ללא מספרי שורות (כדי לחסוך מקום בכרטיס)
    formatter = HtmlFormatter(
        style='github-dark',
        linenos=False,  # ללא מספרי שורות בתצוגה מקדימה
        cssclass='preview-highlight',
        nowrap=False
    )
    
    highlighted_html = highlight(preview_code, lexer, formatter)
    css = formatter.get_style_defs('.preview-highlight')
    
    return jsonify({
        'ok': True,
        'highlighted_html': highlighted_html,
        'syntax_css': css,
        'total_lines': total_lines,
        'preview_lines': preview_lines,
        'language': language,
        'has_more': total_lines > preview_lines
    })
```

**הערות חשובות:**
- ה-route משתמש ב-`@login_required` – רק משתמשים מחוברים יכולים לראות
- משתמש באותו מנגנון Pygments שקיים ב-`/file/<file_id>`
- מחזיר JSON עם HTML מוכן להזרקה
- יש הגבלת גודל (100KB) כדי לא לעמוס את הדפדפן
- **מיקום נכון:** אחרי ה-function `view_file` (אחרי שורה ~3100)

---

## 🎨 שלב 2: עיצוב CSS

### `webapp/static/css/card-preview.css` – קובץ חדש

```css
/* ========================================
   Card Preview Styles - מתוקן
   ======================================== */

/* מצב מורחב של הכרטיס - שימוש ב-class ייחודי למניעת התנגשות */
.file-card.card-preview-expanded {
    max-height: none !important;
    box-shadow: 0 8px 30px rgba(0, 0, 0, 0.3);
    background: rgba(255, 255, 255, 0.12) !important; /* הדגשה קלה */
    transition: all 0.3s ease-in-out, max-height 0.5s ease-in-out;
}

.file-card.card-preview-expanding {
    opacity: 0.7;
    pointer-events: none; /* מניעת לחיצות במהלך טעינה */
    transition: all 0.3s ease-in-out;
}

/* מיכל התצוגה המקדימה */
.card-code-preview {
    margin-top: 1.5rem;
    padding: 1rem;
    background: #1e1e1e;
    border-radius: 8px;
    font-family: 'Fira Code', 'Consolas', 'Monaco', monospace;
    font-size: 13px;
    line-height: 1.6;
    max-height: 400px;
    overflow-y: auto;
    overflow-x: auto;
    animation: slideDown 0.4s ease-in-out;
    direction: ltr;
    text-align: left;
}

/* אנימציית פתיחה חלקה */
@keyframes slideDown {
    from {
        max-height: 0;
        opacity: 0;
        transform: translateY(-10px);
    }
    to {
        max-height: 400px;
        opacity: 1;
        transform: translateY(0);
    }
}

/* עיצוב הקוד המודגש (תואם ל-Pygments) */
.card-code-preview .preview-highlight {
    background: transparent !important;
    padding: 0;
}

.card-code-preview pre {
    margin: 0;
    padding: 0;
    background: transparent;
    color: #d4d4d4;
    white-space: pre;
    word-wrap: normal;
}

/* כפתורי פעולה בתוך הכרטיס המורחב */
.preview-actions {
    display: flex;
    gap: 0.5rem;
    margin-top: 1rem;
    flex-wrap: wrap;
    justify-content: flex-start;
}

.preview-actions .btn {
    font-size: 0.9rem;
    padding: 0.4rem 0.8rem;
}

/* ספינר טעינה */
.preview-spinner {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 2rem;
    color: rgba(255, 255, 255, 0.7);
    gap: 0.5rem;
}

.preview-spinner i {
    animation: spin 1s linear infinite;
}

@keyframes spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
}

/* הודעת שגיאה */
.preview-error {
    padding: 1.5rem;
    background: rgba(220, 53, 69, 0.1);
    border: 1px solid rgba(220, 53, 69, 0.3);
    border-radius: 8px;
    color: #ff6b6b;
    text-align: center;
    margin-top: 1rem;
}

/* מותאם למובייל */
@media (max-width: 768px) {
    .card-code-preview {
        font-size: 11px;
        padding: 0.75rem;
        max-height: 300px;
    }
    
    .preview-actions {
        justify-content: stretch;
    }
    
    .preview-actions .btn {
        flex: 1;
        text-align: center;
    }
}

/* תמיכה ב-high contrast mode */
body.high-contrast .card-code-preview {
    background: #000;
    border: 2px solid #fff;
}

body.high-contrast .file-card.card-preview-expanded {
    border: 3px solid #ffeb3b;
}
```

---

## 💻 שלב 3: JavaScript – לוגיקת הרחבה

### `webapp/static/js/card-preview.js` – קובץ חדש

```javascript
/**
 * מערכת הרחבת כרטיסים (Expanded Card Preview) - מתוקן
 * מאפשרת תצוגה מהירה של 20 שורות קוד בתוך הכרטיס ללא ניווט
 */

(function() {
    'use strict';
    
    // מצב כרטיסים פתוחים (למניעת פתיחה כפולה)
    const expandedCards = new Set();
    
    /**
     * טוען ומציג תצוגה מקדימה של קובץ
     * @param {string} fileId - מזהה הקובץ
     * @param {HTMLElement} cardElement - אלמנט הכרטיס
     */
    async function expandCard(fileId, cardElement) {
        // בדיקה שהכרטיס לא בטעינה
        if (cardElement.classList.contains('card-preview-expanding')) {
            return; // מניעת לחיצות כפולות
        }
        
        // אם הכרטיס כבר מורחב – קפל אותו
        if (expandedCards.has(fileId)) {
            collapseCard(fileId, cardElement);
            return;
        }
        
        // סימון שהכרטיס בטעינה
        cardElement.classList.add('card-preview-expanding');
        
        // יצירת מיכל לתצוגה המקדימה (אם לא קיים)
        let previewContainer = cardElement.querySelector('.card-code-preview-wrapper');
        if (!previewContainer) {
            previewContainer = document.createElement('div');
            previewContainer.className = 'card-code-preview-wrapper';
            cardElement.appendChild(previewContainer);
        }
        
        // הצגת ספינר
        previewContainer.innerHTML = `
            <div class="preview-spinner">
                <i class="fas fa-circle-notch"></i>
                <span>טוען תצוגה מקדימה...</span>
            </div>
        `;
        
        try {
            // קריאת API
            const response = await fetch(`/api/file/${fileId}/preview`, {
                method: 'GET',
                headers: {
                    'Accept': 'application/json'
                }
            });
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            
            const data = await response.json();
            
            if (!data.ok) {
                throw new Error(data.error || 'Unknown error');
            }
            
            // בניית HTML לתצוגה
            const previewHtml = buildPreviewHTML(data, fileId);
            previewContainer.innerHTML = previewHtml;
            
            // הזרקת CSS של Pygments (רק פעם אחת)
            injectSyntaxCSS(data.syntax_css);
            
            // סימון שהכרטיס מורחב
            cardElement.classList.remove('card-preview-expanding');
            cardElement.classList.add('card-preview-expanded');
            expandedCards.add(fileId);
            
            // גלילה חלקה לתצוגה המקדימה
            setTimeout(() => {
                previewContainer.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }, 100);
            
        } catch (error) {
            console.error('Failed to load preview:', error);
            
            // הצגת הודעת שגיאה
            previewContainer.innerHTML = `
                <div class="preview-error">
                    <i class="fas fa-exclamation-triangle"></i>
                    <p>לא הצלחנו לטעון את התצוגה המקדימה</p>
                    <p style="font-size: 0.9rem; opacity: 0.8; margin-top: 0.5rem;">
                        ${error.message}
                    </p>
                    <button class="btn btn-secondary btn-icon" 
                            style="margin-top: 1rem;"
                            onclick="window.location.href='/file/${fileId}'">
                        <i class="fas fa-eye"></i> פתח דף מלא
                    </button>
                </div>
            `;
            
            cardElement.classList.remove('card-preview-expanding');
            cardElement.classList.add('card-preview-expanded');
        }
    }
    
    /**
     * קיפול כרטיס (סגירת התצוגה המקדימה)
     */
    function collapseCard(fileId, cardElement) {
        const previewContainer = cardElement.querySelector('.card-code-preview-wrapper');
        if (previewContainer) {
            // אנימציית סגירה
            previewContainer.style.animation = 'slideDown 0.3s ease-in-out reverse';
            setTimeout(() => {
                previewContainer.remove();
            }, 300);
        }
        
        cardElement.classList.remove('card-preview-expanded');
        expandedCards.delete(fileId);
    }
    
    /**
     * בניית HTML לתצוגה המקדימה
     */
    function buildPreviewHTML(data, fileId) {
        const moreIndicator = data.has_more 
            ? `<p style="opacity: 0.7; font-size: 0.9rem; margin-top: 1rem;">
                 <i class="fas fa-info-circle"></i>
                 מציג ${data.preview_lines} מתוך ${data.total_lines} שורות
               </p>` 
            : '';
        
        return `
            <div class="card-code-preview">
                ${data.highlighted_html}
            </div>
            ${moreIndicator}
            <div class="preview-actions">
                <button class="btn btn-primary btn-icon" 
                        onclick="window.location.href='/file/${fileId}'">
                    <i class="fas fa-expand-alt"></i>
                    <span class="btn-text">פתח דף מלא</span>
                </button>
                <button class="btn btn-secondary btn-icon" 
                        onclick="window.cardPreview.copyPreviewCode(this)">
                    <i class="fas fa-copy"></i>
                    <span class="btn-text">העתק</span>
                </button>
                <button class="btn btn-secondary btn-icon" 
                        onclick="window.cardPreview.collapse('${fileId}', this.closest('.file-card'))">
                    <i class="fas fa-times"></i>
                    <span class="btn-text">סגור</span>
                </button>
            </div>
        `;
    }
    
    /**
     * הזרקת CSS של Pygments (רק פעם אחת)
     */
    function injectSyntaxCSS(css) {
        if (!css || document.getElementById('preview-syntax-css')) {
            return;
        }
        
        const styleEl = document.createElement('style');
        styleEl.id = 'preview-syntax-css';
        styleEl.textContent = css;
        document.head.appendChild(styleEl);
    }
    
    /**
     * העתקת קוד מהתצוגה המקדימה
     */
    function copyPreviewCode(buttonElement) {
        const previewDiv = buttonElement.closest('.card-code-preview-wrapper');
        const codeElement = previewDiv.querySelector('.card-code-preview pre');
        
        if (!codeElement) {
            alert('לא נמצא קוד להעתקה');
            return;
        }
        
        const code = codeElement.textContent;
        
        navigator.clipboard.writeText(code).then(() => {
            // חיווי ויזואלי
            const originalHTML = buttonElement.innerHTML;
            buttonElement.innerHTML = '<i class="fas fa-check"></i> הועתק!';
            buttonElement.classList.add('btn-success');
            
            setTimeout(() => {
                buttonElement.innerHTML = originalHTML;
                buttonElement.classList.remove('btn-success');
            }, 2000);
        }).catch(err => {
            console.error('Copy failed:', err);
            alert('לא הצלחנו להעתיק את הקוד');
        });
    }
    
    // חשיפת API ציבורי
    window.cardPreview = {
        expand: expandCard,
        collapse: collapseCard,
        copyPreviewCode: copyPreviewCode
    };
    
    console.log('✅ Card Preview system loaded');
})();
```

---

## 🔗 שלב 4: שילוב ב-files.html

### `webapp/templates/files.html` – עריכות נדרשות

#### 1. הוספת ה-CSS (בסוף ה-`{% block extra_css %}`)

```html
{% block extra_css %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/multi-select.css') }}">
<!-- הוסף את זה כאן -->
<link rel="stylesheet" href="{{ url_for('static', filename='css/card-preview.css') }}">
{% endblock %}
```

#### 2. הוספת כפתור "הצץ" לכל כרטיס

**מיקום נכון:** הוסף **לפני** כפתור "צפה" (שורה 308):

```html
<div style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
    <!-- הוסף כפתור "הצץ" כאן -->
    <button class="btn btn-secondary btn-icon" 
            style="padding: 0.5rem 1rem;" 
            title="הצץ בקוד"
            onclick="window.cardPreview.expand('{{ file.id }}', this.closest('.file-card'))">
        <i class="fas fa-eye" aria-hidden="true"></i>
        <span class="btn-text">👁️ הצץ</span>
    </button>
    
    <a href="/file/{{ file.id }}" class="btn btn-secondary btn-icon" style="padding: 0.5rem 1rem;" title="צפה">
        <i class="fas fa-eye" aria-hidden="true"></i><span class="btn-text"> צפה</span>
    </a>
    <!-- ... שאר הכפתורים ... -->
</div>
```

#### 3. טעינת הסקריפט (בסוף `{% block extra_js %}`)

```html
{% block extra_js %}
<script src="{{ url_for('static', filename='js/multi-select.js') }}" defer></script>
<script src="{{ url_for('static', filename='js/bulk-actions.js') }}" defer></script>
<!-- הוסף את זה כאן -->
<script src="{{ url_for('static', filename='js/card-preview.js') }}" defer></script>
<!-- ... שאר הסקריפטים ... -->
{% endblock %}
```

---

## 🧪 שלב 5: בדיקות

### בדיקות ידניות

1. **בדיקה בסיסית:**
   - היכנס ל-`/files`
   - לחץ על כפתור "👁️ הצץ" באחד הכרטיסים
   - וודא שהכרטיס מתרחב ומציג קוד מודגש

2. **בדיקת קבצים שונים:**
   - קובץ Python
   - קובץ JavaScript
   - קובץ Markdown
   - קובץ גדול (>100KB) – צריך להציג שגיאה
   - קובץ ריק – צריך להציג שגיאה

3. **בדיקת פעולות:**
   - לחיצה על "העתק" – הקוד מועתק
   - לחיצה על "פתח דף מלא" – ניווט ל-`/file/<id>`
   - לחיצה על "סגור" – הכרטיס מתקפל

4. **בדיקה במובייל:**
   - פתח בדפדפן מובייל או במצב responsive
   - וודא שהתצוגה מתאימה

### בדיקות אוטומטיות (pytest)

צור קובץ `tests/test_card_preview.py`:

```python
"""
בדיקות לפיצר Card Preview - מתוקן
"""
import pytest
from webapp.app import app
from bson import ObjectId


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_preview_endpoint_requires_login(client):
    """בדיקה שה-endpoint דורש התחברות"""
    response = client.get('/api/file/507f1f77bcf86cd799439011/preview')
    assert response.status_code in [302, 401]  # redirect to login


def test_preview_invalid_file_id(client, logged_in_client):
    """בדיקה עם file_id לא תקין"""
    response = logged_in_client.get('/api/file/invalid_id/preview')
    assert response.status_code == 400
    data = response.get_json()
    assert data['ok'] is False


def test_preview_file_not_found(client, logged_in_client):
    """בדיקה עם file_id שלא קיים"""
    fake_id = str(ObjectId())
    response = logged_in_client.get(f'/api/file/{fake_id}/preview')
    assert response.status_code == 404


def test_preview_empty_file(client, logged_in_client, sample_file):
    """בדיקה עם קובץ ריק"""
    # עדכון הקובץ להיות ריק
    from webapp.app import get_db
    db = get_db()
    db.code_snippets.update_one(
        {'_id': sample_file['_id']},
        {'$set': {'code': ''}}
    )
    
    file_id = str(sample_file['_id'])
    response = logged_in_client.get(f'/api/file/{file_id}/preview')
    
    assert response.status_code == 400
    data = response.get_json()
    assert data['ok'] is False
    assert 'empty' in data['error'].lower()


def test_preview_success(client, logged_in_client, sample_file):
    """בדיקה עם קובץ קיים"""
    file_id = str(sample_file['_id'])
    response = logged_in_client.get(f'/api/file/{file_id}/preview')
    
    assert response.status_code == 200
    data = response.get_json()
    
    assert data['ok'] is True
    assert 'highlighted_html' in data
    assert 'syntax_css' in data
    assert 'total_lines' in data
    assert 'preview_lines' in data
    assert data['preview_lines'] <= 20
```

---

## 🎨 שלב 6: שיפורים נוספים (אופציונלי)

### 1. הגדרות משתמש

אפשר למשתמשים להפעיל/לבטל את הפיצר דרך `/settings`:

```python
# webapp/app.py - בעת שמירת הגדרות
user_settings['card_preview_enabled'] = request.form.get('card_preview_enabled') == 'on'
```

```html
<!-- webapp/templates/settings.html -->
<div class="form-check">
    <input type="checkbox" class="form-check-input" 
           id="cardPreviewEnabled" 
           name="card_preview_enabled"
           {% if settings.card_preview_enabled %}checked{% endif %}>
    <label class="form-check-label" for="cardPreviewEnabled">
        הפעל תצוגה מקדימה בכרטיסים
    </label>
</div>
```

ב-`card-preview.js`, בדוק את ההגדרה לפני הרחבה:

```javascript
async function expandCard(fileId, cardElement) {
    const settings = window.userSettings || {};
    if (settings.card_preview_enabled === false) {
        // נווט ישירות לדף מלא
        window.location.href = `/file/${fileId}`;
        return;
    }
    // ... המשך לוגיקה
}
```

### 2. קיצורי מקלדת

הוסף תמיכה בקיצור `Ctrl+E` להצצה:

```javascript
// בסוף card-preview.js
document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'e') {
        // מצא את הכרטיס שמעליו העכבר
        const hoveredCard = document.querySelector('.file-card:hover');
        if (hoveredCard) {
            const fileId = hoveredCard.dataset.fileId;
            if (fileId) {
                expandCard(fileId, hoveredCard);
            }
        }
    }
});
```

---

## ✅ סיכום התיקונים

### מה תוקן במדריך:

1. **מיקום הוספת ה-CSS** - הוספה נכונה ב-`{% block extra_css %}`
2. **מיקום הוספת הכפתור** - הוספה לפני כפתור "צפה"
3. **מיקום ה-API Route** - הוספה אחרי ה-function `view_file`
4. **מניעת התנגשות CSS** - שימוש ב-`.card-preview-expanded` במקום `.expanded`
5. **הוספת בדיקת קובץ ריק** - בדיקה נוספת ב-API
6. **מניעת לחיצות כפולות** - בדיקה שהכרטיס לא בטעינה
7. **שיפור ה-JavaScript** - טיפול טוב יותר בשגיאות

### המדריך המתוקן מוכן למימוש! 🚀