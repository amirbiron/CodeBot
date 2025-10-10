# 📝 מדריך מימוש: עורך קוד CodeMirror ב-WebApp

## 📋 סקירה כללית

מדריך זה מתאר כיצד להוסיף עורך קוד מתקדם מבוסס CodeMirror 6 לצד העורך הקיים (textarea פשוט) ב-WebApp של CodeBot. המטרה היא לתת למשתמשים אפשרות בחירה בין עורך פשוט לעורך מתקדם עם יכולות עריכה משופרות.

## 🎯 יעדי הפיצ'ר

1. **שמירת העורך הקיים**: העורך הנוכחי (textarea) יישאר כברירת מחדל
2. **הוספת CodeMirror 6**: עורך מודרני עם תמיכה מלאה בשפות תכנות
3. **מעבר חלק**: כפתור החלפה בין העורכים בזמן אמת
4. **שמירת העדפה**: זכירת בחירת העורך למשתמש
5. **תכונות מתקדמות**: הדגשת תחביר, השלמה אוטומטית, מיני-מפה, ועוד

---

## 🌟 תכונות CodeMirror שיוטמעו

### תכונות בסיס
- ✅ הדגשת תחביר לכל השפות הנתמכות
- ✅ מספרי שורות דינאמיים
- ✅ קיפול קוד (Code Folding)
- ✅ סוגריים מתאימים (Bracket Matching)
- ✅ הזחה אוטומטית
- ✅ בחירת מספר עמודות (Multi-cursor)

### תכונות מתקדמות
- ✅ השלמה אוטומטית (Autocomplete)
- ✅ חיפוש והחלפה מתקדמים (Ctrl+F / Ctrl+H)
- ✅ מיני-מפה (Minimap)
- ✅ תמיכה ב-RTL/LTR
- ✅ ערכות נושא (Themes) - כהה/בהיר
- ✅ קיצורי מקלדת מותאמים אישית

---

## 🏗️ ארכיטקטורה

### מבנה הקומפוננטה

```
webapp/
├── static/
│   ├── js/
│   │   ├── editor-manager.js      # מנהל העורכים
│   │   ├── codemirror-setup.js    # הגדרות CodeMirror
│   │   └── editor-switcher.js     # לוגיקת המעבר
│   └── css/
│       └── codemirror-custom.css  # עיצוב מותאם
├── templates/
│   ├── edit_file.html            # עדכון לתמיכה בשני עורכים
│   └── upload.html               # עדכון לתמיכה בשני עורכים
└── app.py                        # תמיכה בשמירת העדפות
```

---

## 📦 התקנה ותלויות

### 1. הוספת CDN לבסיס התבנית

ב-`templates/base.html`, בתוך ה-`<head>`:

```html
<!-- CodeMirror 6 - טעינה מותנית -->
{% if use_codemirror %}
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@codemirror/view@6/dist/codemirror.min.css">
<script type="module">
  import { EditorState } from 'https://cdn.jsdelivr.net/npm/@codemirror/state@6/dist/index.js';
  import { EditorView } from 'https://cdn.jsdelivr.net/npm/@codemirror/view@6/dist/index.js';
  import { basicSetup } from 'https://cdn.jsdelivr.net/npm/codemirror@6/dist/index.js';
  // ... יתר ההגדרות
  window.CodeMirror6 = { EditorState, EditorView, basicSetup };
</script>
{% endif %}
```

### 2. חבילות CodeMirror נדרשות

```javascript
// רשימת החבילות הנדרשות מ-npm/CDN:
const requiredPackages = [
  '@codemirror/state',           // ניהול מצב העורך
  '@codemirror/view',            // תצוגת העורך
  '@codemirror/commands',        // פקודות עורך
  '@codemirror/language',        // תמיכת שפות
  '@codemirror/search',          // חיפוש והחלפה
  '@codemirror/autocomplete',   // השלמה אוטומטית
  '@codemirror/lint',           // בדיקת שגיאות
  'codemirror',                 // חבילת הבסיס
  
  // תמיכת שפות (לפי צורך):
  '@codemirror/lang-python',
  '@codemirror/lang-javascript',
  '@codemirror/lang-html',
  '@codemirror/lang-css',
  '@codemirror/lang-markdown',
  '@codemirror/lang-sql',
  '@codemirror/lang-json',
  '@codemirror/lang-xml',
  '@codemirror/lang-cpp',
  '@codemirror/lang-java',
  '@codemirror/lang-rust',
  '@codemirror/lang-php'
];
```

---

## 💻 מימוש Frontend

### 1. מנהל העורכים - `static/js/editor-manager.js`

```javascript
class EditorManager {
  constructor() {
    this.currentEditor = 'simple'; // 'simple' או 'codemirror'
    this.cmInstance = null;
    this.textarea = null;
    this.loadPreference();
  }
  
  // טעינת העדפת משתמש
  loadPreference() {
    const saved = localStorage.getItem('preferredEditor');
    if (saved && ['simple', 'codemirror'].includes(saved)) {
      this.currentEditor = saved;
    }
  }
  
  // שמירת העדפה
  savePreference(editorType) {
    localStorage.setItem('preferredEditor', editorType);
    // שליחה לשרת (אופציונלי)
    fetch('/api/user/preferences', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({editor_type: editorType})
    }).catch(err => console.warn('Failed to save preference:', err));
  }
  
  // אתחול העורך
  async initEditor(container, options = {}) {
    const {
      language = 'python',
      theme = 'dark',
      value = '',
      readOnly = false
    } = options;
    
    this.textarea = container.querySelector('textarea[name="code"]');
    
    if (this.currentEditor === 'codemirror') {
      await this.initCodeMirror(container, options);
    } else {
      this.initSimpleEditor(container, options);
    }
    
    this.addSwitcherButton(container);
  }
  
  // אתחול עורך פשוט
  initSimpleEditor(container, options) {
    if (this.cmInstance) {
      // העתקת התוכן מ-CodeMirror
      this.textarea.value = this.cmInstance.state.doc.toString();
      this.cmInstance.destroy();
      this.cmInstance = null;
    }
    
    this.textarea.style.display = 'block';
    container.querySelector('.cm-editor')?.remove();
  }
  
  // אתחול CodeMirror
  async initCodeMirror(container, options) {
    // הסתרת textarea
    this.textarea.style.display = 'none';
    
    // יצירת container ל-CodeMirror
    const cmContainer = document.createElement('div');
    cmContainer.className = 'codemirror-container';
    this.textarea.parentNode.insertBefore(cmContainer, this.textarea.nextSibling);
    
    // טעינת CodeMirror
    if (!window.CodeMirror6) {
      await this.loadCodeMirror();
    }
    
    const { EditorState, EditorView, basicSetup } = window.CodeMirror6;
    const langSupport = await this.getLanguageSupport(options.language);
    const themeExtension = await this.getTheme(options.theme);
    
    // הגדרת העורך
    const state = EditorState.create({
      doc: this.textarea.value || options.value,
      extensions: [
        basicSetup,
        langSupport,
        themeExtension,
        EditorView.lineWrapping,
        EditorView.updateListener.of(update => {
          if (update.docChanged) {
            // סנכרון עם textarea
            this.textarea.value = update.state.doc.toString();
            // הפעלת אירוע change
            this.textarea.dispatchEvent(new Event('input', {bubbles: true}));
          }
        }),
        // הגדרות נוספות
        this.getCustomExtensions(options)
      ]
    });
    
    // יצירת העורך
    this.cmInstance = new EditorView({
      state,
      parent: cmContainer
    });
  }
  
  // הוספת כפתור מעבר
  addSwitcherButton(container) {
    if (container.querySelector('.editor-switcher')) return;
    
    const switcher = document.createElement('div');
    switcher.className = 'editor-switcher';
    switcher.innerHTML = `
      <button type="button" class="btn-switch-editor" title="החלף עורך">
        <i class="fas fa-exchange-alt"></i>
        <span>${this.currentEditor === 'simple' ? 'עורך מתקדם' : 'עורך פשוט'}</span>
      </button>
      <div class="editor-info">
        ${this.currentEditor === 'codemirror' ? 
          '<span><i class="fas fa-keyboard"></i> Ctrl+F לחיפוש | Ctrl+Space להשלמה</span>' : 
          '<span><i class="fas fa-info-circle"></i> עורך טקסט בסיסי</span>'
        }
      </div>
    `;
    
    const label = container.querySelector('label:has(+ textarea[name="code"])') || 
                  container.querySelector('label');
    if (label) {
      label.parentNode.insertBefore(switcher, label.nextSibling);
    }
    
    // אירוע לחיצה
    switcher.querySelector('.btn-switch-editor').addEventListener('click', () => {
      this.toggleEditor(container);
    });
  }
  
  // החלפת עורך
  async toggleEditor(container) {
    const newEditor = this.currentEditor === 'simple' ? 'codemirror' : 'simple';
    const currentValue = this.getValue();
    
    this.currentEditor = newEditor;
    this.savePreference(newEditor);
    
    // אתחול מחדש
    await this.initEditor(container, {
      value: currentValue,
      language: this.detectLanguage(currentValue),
      theme: this.getThemePreference()
    });
  }
  
  // קבלת הערך הנוכחי
  getValue() {
    if (this.cmInstance) {
      return this.cmInstance.state.doc.toString();
    }
    return this.textarea.value;
  }
  
  // הגדרת ערך
  setValue(value) {
    if (this.cmInstance) {
      this.cmInstance.dispatch({
        changes: {from: 0, to: this.cmInstance.state.doc.length, insert: value}
      });
    } else {
      this.textarea.value = value;
    }
  }
  
  // זיהוי שפה
  detectLanguage(code) {
    // זיהוי בסיסי לפי תוכן
    if (code.includes('def ') || code.includes('import ')) return 'python';
    if (code.includes('function ') || code.includes('const ')) return 'javascript';
    if (code.includes('<html') || code.includes('<div')) return 'html';
    if (code.includes('SELECT ') || code.includes('CREATE TABLE')) return 'sql';
    return 'text';
  }
  
  // טעינת תמיכת שפה
  async getLanguageSupport(lang) {
    const langMap = {
      'python': () => import('@codemirror/lang-python').then(m => m.python()),
      'javascript': () => import('@codemirror/lang-javascript').then(m => m.javascript()),
      'html': () => import('@codemirror/lang-html').then(m => m.html()),
      'css': () => import('@codemirror/lang-css').then(m => m.css()),
      'sql': () => import('@codemirror/lang-sql').then(m => m.sql()),
      'json': () => import('@codemirror/lang-json').then(m => m.json()),
      'markdown': () => import('@codemirror/lang-markdown').then(m => m.markdown()),
      'xml': () => import('@codemirror/lang-xml').then(m => m.xml()),
      'java': () => import('@codemirror/lang-java').then(m => m.java()),
      'cpp': () => import('@codemirror/lang-cpp').then(m => m.cpp()),
      'rust': () => import('@codemirror/lang-rust').then(m => m.rust()),
      'php': () => import('@codemirror/lang-php').then(m => m.php())
    };
    
    if (langMap[lang]) {
      try {
        return await langMap[lang]();
      } catch (e) {
        console.warn(`Language ${lang} not available, using default`);
      }
    }
    return [];
  }
  
  // קבלת ערכת נושא
  async getTheme(themeName) {
    if (themeName === 'dark') {
      const { oneDark } = await import('@codemirror/theme-one-dark');
      return oneDark;
    }
    return []; // ברירת מחדל - בהיר
  }
  
  // הרחבות מותאמות
  getCustomExtensions(options) {
    const extensions = [];
    
    // תמיכה ב-RTL לטקסט עברי/ערבי
    if (this.detectRTL(options.value)) {
      extensions.push(EditorView.baseTheme({
        ".cm-line": { direction: "rtl", textAlign: "right" }
      }));
    }
    
    // הגבלת גודל קובץ
    if (options.maxSize) {
      extensions.push(EditorState.changeFilter.of((tr) => {
        return tr.newDoc.length <= options.maxSize;
      }));
    }
    
    return extensions;
  }
  
  // זיהוי RTL
  detectRTL(text) {
    const rtlChars = /[\u0590-\u05FF\u0600-\u06FF]/;
    return rtlChars.test(text?.slice(0, 100) || '');
  }
  
  // טעינת CodeMirror (אם לא נטען)
  async loadCodeMirror() {
    // יש להטמיע את הטעינה הדינמית כאן
    // או להשתמש ב-dynamic imports
    console.log('Loading CodeMirror...');
  }
  
  // העדפת ערכת נושא
  getThemePreference() {
    return localStorage.getItem('editorTheme') || 'dark';
  }
}

// יצירת instance גלובלי
window.editorManager = new EditorManager();
```

### 2. עדכון `templates/edit_file.html`

```html
{% extends "base.html" %}

{% block title %}עריכת {{ file.file_name }} - Code Keeper Bot{% endblock %}

{% block head %}
<style>
  /* סגנון לעורך CodeMirror */
  .codemirror-container {
    border-radius: 10px;
    border: 1px solid rgba(255,255,255,0.2);
    background: rgba(255,255,255,0.1);
    overflow: hidden;
  }
  
  .cm-editor {
    min-height: 400px;
    max-height: 600px;
    font-family: 'Fira Code', 'Consolas', monospace;
  }
  
  .editor-switcher {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin: 0.5rem 0;
    padding: 0.5rem;
    background: rgba(255,255,255,0.05);
    border-radius: 8px;
  }
  
  .btn-switch-editor {
    padding: 0.5rem 1rem;
    background: rgba(100,100,255,0.2);
    border: 1px solid rgba(100,100,255,0.5);
    border-radius: 6px;
    color: white;
    cursor: pointer;
    transition: all 0.3s;
  }
  
  .btn-switch-editor:hover {
    background: rgba(100,100,255,0.3);
    transform: translateY(-1px);
  }
  
  .editor-info {
    font-size: 0.85rem;
    opacity: 0.8;
  }
  
  /* אנימציית מעבר */
  .editor-transitioning {
    opacity: 0.5;
    pointer-events: none;
  }
</style>
{% endblock %}

{% block content %}
<h1 class="page-title">עריכת קובץ</h1>

<div class="glass-card">
  {% if error %}
  <div class="alert alert-error">{{ error }}</div>
  {% endif %}
  {% if success %}
  <div class="alert alert-success">{{ success }}</div>
  {% endif %}

  <form method="post" style="display: grid; gap: 1rem;">
    <div>
      <label>שם קובץ</label>
      <input type="text" name="file_name" value="{{ file.file_name }}" 
             style="width: 100%; padding: .75rem; border-radius: 10px; border: 1px solid rgba(255,255,255,0.2); background: rgba(255,255,255,0.1); color: white;">
    </div>
    <div>
      <label>שפה</label>
      <select name="language" id="languageSelect" 
              style="width: 100%; padding: .75rem; border-radius: 10px; border: 1px solid rgba(255,255,255,0.2); background: rgba(255,255,255,0.1); color: white;">
        <option value="{{ file.language }}">— {{ file.language }} (נוכחית) —</option>
        <option value="text">זהה לפי סיומת/תוכן</option>
        {% for lang in languages %}
        <option value="{{ lang }}">{{ lang }}</option>
        {% endfor %}
      </select>
    </div>
    <div>
      <label>תיאור</label>
      <input type="text" name="description" value="{{ file.description }}" 
             style="width: 100%; padding: .75rem; border-radius: 10px; border: 1px solid rgba(255,255,255,0.2); background: rgba(255,255,255,0.1); color: white;">
    </div>
    <div>
      <label>תגיות</label>
      <input type="text" name="tags" value="{{ file.tags | join(', ') }}" 
             placeholder="#utils, #repo:owner/name" 
             style="width: 100%; padding: .75rem; border-radius: 10px; border: 1px solid rgba(255,255,255,0.2); background: rgba(255,255,255,0.1); color: white;">
    </div>
    <div id="editorContainer">
      <label>קוד</label>
      <!-- העורך יוכנס כאן דינמית -->
      <textarea name="code" rows="18" 
                style="width: 100%; padding: .75rem; border-radius: 10px; border: 1px solid rgba(255,255,255,0.2); background: rgba(255,255,255,0.1); color: white; font-family: 'Fira Code', 'Consolas', monospace;">{{ code_value }}</textarea>
    </div>
    <div style="display: flex; gap: 1rem;">
      <button type="submit" class="btn btn-primary btn-icon">
        <i class="fas fa-save"></i> שמור גרסה חדשה
      </button>
      <a href="/file/{{ file.id }}" class="btn btn-secondary btn-icon">
        <i class="fas fa-times"></i> ביטול
      </a>
    </div>
  </form>
</div>

<script type="module">
// אתחול עורך הקוד
document.addEventListener('DOMContentLoaded', async () => {
  const container = document.getElementById('editorContainer');
  const languageSelect = document.getElementById('languageSelect');
  
  // אתחול העורך
  await window.editorManager.initEditor(container, {
    language: '{{ file.language }}',
    value: {{ code_value | tojson }},
    theme: 'dark'
  });
  
  // עדכון שפה בעת שינוי
  languageSelect.addEventListener('change', async (e) => {
    const lang = e.target.value;
    if (window.editorManager.cmInstance) {
      // עדכון הדגשת תחביר ב-CodeMirror
      const langSupport = await window.editorManager.getLanguageSupport(lang);
      window.editorManager.cmInstance.dispatch({
        effects: window.editorManager.cmInstance.state.reconfigure.of([langSupport])
      });
    }
  });
});
</script>
{% endblock %}
```

### 3. עדכון `templates/upload.html` באופן דומה

```html
<!-- אותן תוספות כמו ב-edit_file.html -->
```

---

## 🔧 מימוש Backend

### 1. שמירת העדפות משתמש

ב-`app.py`, הוסף endpoint:

```python
@app.route('/api/user/preferences', methods=['POST'])
def update_user_preferences():
    """עדכון העדפות משתמש"""
    if not session.get('user_id'):
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        data = request.json
        editor_type = data.get('editor_type')
        
        if editor_type not in ['simple', 'codemirror']:
            return jsonify({'error': 'Invalid editor type'}), 400
        
        # שמירה ב-session או DB
        session['preferred_editor'] = editor_type
        
        # אופציונלי: שמירה ב-DB
        users_collection.update_one(
            {'user_id': session['user_id']},
            {'$set': {'preferences.editor': editor_type}},
            upsert=True
        )
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
```

### 2. העברת העדפה לתבניות

```python
@app.route('/edit/<file_id>')
def edit_file(file_id):
    # ... קוד קיים ...
    
    # קבלת העדפת עורך
    preferred_editor = session.get('preferred_editor', 'simple')
    
    return render_template('edit_file.html',
                         file=file_data,
                         code_value=code,
                         languages=SUPPORTED_LANGUAGES,
                         use_codemirror=(preferred_editor == 'codemirror'))
```

---

## 🎨 עיצוב CSS מותאם

צור `static/css/codemirror-custom.css`:

```css
/* התאמות לעורך CodeMirror */
.cm-editor {
  direction: ltr;
  text-align: left;
}

.cm-editor.cm-rtl {
  direction: rtl;
  text-align: right;
}

/* התאמה לנושא הכהה של האתר */
.cm-editor.cm-focused {
  outline: 2px solid rgba(100,100,255,0.5);
}

.cm-selectionBackground {
  background-color: rgba(100,100,255,0.3) !important;
}

/* מספרי שורות */
.cm-gutters {
  background: rgba(0,0,0,0.3);
  border-right: 1px solid rgba(255,255,255,0.1);
}

.cm-activeLineGutter {
  background: rgba(100,100,255,0.2);
}

/* חיפוש והדגשה */
.cm-searchMatch {
  background-color: rgba(255,200,0,0.3);
  border: 1px solid rgba(255,200,0,0.8);
}

.cm-searchMatch.cm-searchMatch-selected {
  background-color: rgba(255,150,0,0.5);
}

/* השלמה אוטומטית */
.cm-tooltip.cm-autocomplete {
  background: rgba(30,30,40,0.95);
  backdrop-filter: blur(10px);
  border: 1px solid rgba(100,100,255,0.3);
  border-radius: 8px;
}

.cm-tooltip.cm-autocomplete > ul > li[aria-selected] {
  background: rgba(100,100,255,0.2);
}

/* מיני-מפה */
.cm-minimap {
  position: fixed;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
  width: 100px;
  background: rgba(0,0,0,0.5);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 8px;
  padding: 5px;
}

/* אנימציות */
.cm-editor {
  transition: outline 0.3s ease;
}

@keyframes highlight-flash {
  0% { background: rgba(255,255,100,0.5); }
  100% { background: transparent; }
}

.cm-line.flash {
  animation: highlight-flash 0.5s ease;
}

/* רספונסיביות */
@media (max-width: 768px) {
  .cm-editor {
    font-size: 14px;
  }
  
  .cm-minimap {
    display: none;
  }
  
  .editor-switcher {
    flex-direction: column;
    gap: 0.5rem;
  }
}
```

---

## 🧪 בדיקות ואימות

### בדיקות פונקציונליות

1. **בדיקת טעינה**:
   - ודא ש-CodeMirror נטען רק כשנבחר
   - ודא שה-fallback לעורך פשוט עובד

2. **בדיקת תכונות**:
   - הדגשת תחביר לכל השפות
   - חיפוש והחלפה (Ctrl+F, Ctrl+H)
   - השלמה אוטומטית (Ctrl+Space)
   - קיפול קוד
   - מספרי שורות

3. **בדיקת ביצועים**:
   - טעינת קבצים גדולים (>1MB)
   - עריכה בזמן אמת
   - זכרון ו-CPU

4. **בדיקת תאימות**:
   - דפדפנים שונים (Chrome, Firefox, Safari, Edge)
   - מובייל ו-טאבלט
   - מצב offline

### סקריפט בדיקה אוטומטי

```javascript
// tests/editor.test.js
describe('CodeMirror Editor Tests', () => {
  let editor;
  
  beforeEach(() => {
    editor = new EditorManager();
  });
  
  test('Toggle between editors', async () => {
    // אתחול עורך פשוט
    await editor.initEditor(container, {value: 'test'});
    expect(editor.currentEditor).toBe('simple');
    
    // מעבר ל-CodeMirror
    await editor.toggleEditor(container);
    expect(editor.currentEditor).toBe('codemirror');
    expect(editor.getValue()).toBe('test');
  });
  
  test('Language detection', () => {
    expect(editor.detectLanguage('def main():')).toBe('python');
    expect(editor.detectLanguage('function test() {}')).toBe('javascript');
    expect(editor.detectLanguage('<html>')).toBe('html');
  });
  
  test('RTL detection', () => {
    expect(editor.detectRTL('שלום עולם')).toBe(true);
    expect(editor.detectRTL('Hello World')).toBe(false);
  });
  
  test('Preference persistence', () => {
    editor.savePreference('codemirror');
    expect(localStorage.getItem('preferredEditor')).toBe('codemirror');
  });
});
```

---

## 📈 שיפורים עתידיים

### שלב 1 - תכונות בסיס (Sprint 1)
- [x] עורך בסיסי עם הדגשת תחביר
- [x] מעבר בין עורכים
- [x] שמירת העדפות

### שלב 2 - תכונות מתקדמות (Sprint 2)
- [ ] Linting והצעות תיקון
- [ ] Git diff בצד העורך
- [ ] Multi-cursor editing
- [ ] Snippets מותאמים אישית
- [ ] עבודה משותפת (Collaborative editing)

### שלב 3 - אינטגרציות (Sprint 3)
- [ ] אינטגרציה עם AI להצעות קוד
- [ ] Terminal מובנה
- [ ] Debugger
- [ ] תצוגה מקדימה (Preview panel)
- [ ] Version control מובנה

---

## 🚀 הוראות הטמעה

### שלב 1: הכנה
```bash
# יצירת branch חדש
git checkout -b feature/codemirror-editor

# יצירת הקבצים החדשים
touch webapp/static/js/editor-manager.js
touch webapp/static/js/codemirror-setup.js
touch webapp/static/css/codemirror-custom.css
```

### שלב 2: הטמעת הקוד
1. העתק את הקוד מהמדריך לקבצים המתאימים
2. עדכן את `base.html` עם הטעינה המותנית
3. עדכן את `edit_file.html` ו-`upload.html`
4. הוסף את ה-endpoint ב-`app.py`

### שלב 3: בדיקות
```bash
# הרצה מקומית
cd webapp
python app.py

# בדיקה ידנית
# 1. גש ל-http://localhost:5000
# 2. ערוך קובץ קיים
# 3. נסה להחליף בין העורכים
# 4. ודא ששמירה עובדת
```

### שלב 4: Deployment
```bash
# קומיט ו-push
git add -A
git commit -m "feat: Add CodeMirror editor option alongside simple textarea"
git push origin feature/codemirror-editor

# יצירת PR
gh pr create --title "הוספת אפשרות עורך CodeMirror" \
  --body "הוספת עורך קוד מתקדם CodeMirror 6 כאופציה לצד העורך הפשוט הקיים"
```

---

## 📚 משאבים

### תיעוד רשמי
- [CodeMirror 6 Documentation](https://codemirror.net/docs/)
- [CodeMirror 6 Examples](https://codemirror.net/examples/)
- [Migration from CodeMirror 5](https://codemirror.net/docs/migration/)

### מדריכים מומלצים
- [Building a Code Editor with CodeMirror 6](https://www.digitalocean.com/community/tutorials/codemirror-6-getting-started)
- [CodeMirror 6 Architecture](https://marijnhaverbeke.nl/blog/codemirror-6-architecture.html)

### קהילה ותמיכה
- [CodeMirror Forum](https://discuss.codemirror.net/)
- [GitHub Issues](https://github.com/codemirror/codemirror.next/issues)
- [Stack Overflow - codemirror-6 tag](https://stackoverflow.com/questions/tagged/codemirror-6)

---

## 🔒 אבטחה

### המלצות אבטחה
1. **סינון קלט**: ודא סינון XSS בכל קלט
2. **הגבלת גודל**: הגבל גודל מסמכים ל-10MB
3. **Rate limiting**: הגבל מספר שמירות לדקה
4. **CSP Headers**: הוסף Content-Security-Policy
5. **Sanitization**: נקה HTML בתצוגה מקדימה

### דוגמת הגנה
```python
# ב-app.py
from markupsafe import Markup, escape

def sanitize_code(code):
    """ניקוי קוד מתגי HTML מסוכנים"""
    # רק בתצוגה, לא בשמירה!
    if '<script' in code.lower():
        return escape(code)
    return code
```

---

## ✅ צ'קליסט להטמעה

- [ ] קריאת המדריך במלואו
- [ ] יצירת branch חדש
- [ ] הטמעת הקבצים החדשים
- [ ] עדכון התבניות הקיימות
- [ ] הוספת endpoint להעדפות
- [ ] בדיקות מקומיות
- [ ] בדיקת ביצועים
- [ ] בדיקת אבטחה
- [ ] כתיבת בדיקות אוטומטיות
- [ ] יצירת PR עם תיאור מלא
- [ ] עדכון תיעוד המשתמש

---

## 📝 הערות סיום

מדריך זה מספק תשתית מלאה להטמעת עורך CodeMirror 6 ב-WebApp. העורך מתוכנן לעבוד לצד העורך הקיים כך שמשתמשים יוכלו לבחור את החוויה המועדפת עליהם.

**חשוב לזכור**:
- העורך הפשוט נשאר ברירת המחדל
- המעבר בין העורכים חייב להיות חלק
- התוכן חייב להישמר במעבר
- ביצועים חשובים - טען CodeMirror רק בעת הצורך

בהצלחה בהטמעה! 🚀