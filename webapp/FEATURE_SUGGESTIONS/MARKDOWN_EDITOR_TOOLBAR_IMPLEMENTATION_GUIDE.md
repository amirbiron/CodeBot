# 🛠️ מדריך מימוש: סרגל כלים מהיר לעריכת Markdown

## 📋 סקירה כללית

מדריך זה מתאר כיצד להוסיף סרגל כלים מהיר לקבצי Markdown ב-WebApp. הסרגל יופיע אוטומטית כשמזהים קובץ Markdown (לפי סיומת `.md`/`.markdown` או בחירת שפת Markdown), ויכיל כלים שמקלים על כתיבת Markdown.

---

## 🎯 יעדי הפיצ'ר

1. **זיהוי אוטומטי**: הסרגל יופיע רק בעת עריכת קבצי Markdown
2. **הזרקת תבניות**: כל כלי יזריק שלד מוכן למיקום הסמן
3. **חווית משתמש נעימה**: אייקון קטן → Dropdown עם כלים → לחיצה = הזרקה
4. **תמיכה בשני הדפים**: `upload.html` ו-`edit_file.html`

---

## ✨ הכלים המוצעים

| כלי | אייקון | קיצור מקלדת | תיאור |
|-----|--------|-------------|--------|
| טבלה | 📊 | `Ctrl+Shift+T` | הזרקת שלד טבלה |
| התראות (Alerts) | 🔔 | — | תפריט משנה עם 13 סוגים |
| קיפול (Details) | 📁 | `Ctrl+Shift+D` | הזרקת בלוק מתקפל |
| קישור חכם | 🔗 | `Ctrl+K` | עטיפת טקסט מסומן עם URL מהלוח |
| מארקר | 🎨 | `Ctrl+Shift+H` | הזרקת `==טקסט מודגש==` |
| רשימת משימות | ✅ | `Ctrl+Shift+C` | הזרקת Checkbox list |

---

## 🏗️ ארכיטקטורה

### מבנה הקבצים

```
webapp/
├── static/
│   ├── js/
│   │   └── markdown-toolbar.js          # חדש - לוגיקת הסרגל
│   └── css/
│       └── markdown-toolbar.css         # חדש - עיצוב הסרגל
├── templates/
│   ├── components/
│   │   └── editor_components.html       # עדכון - הוספת מאקרו חדש
│   ├── edit_file.html                   # עדכון - הוספת הסרגל
│   └── upload.html                      # עדכון - הוספת הסרגל
```

### תלויות קיימות

הפיצ'ר נשען על קוד קיים:

1. **`file-form-manager.js`** - מכיל כבר לוגיקת זיהוי Markdown:
   ```javascript
   // שורות 40-48 - פונקציות עזר קיימות!
   function isMarkdownLanguage(value) {
     const v = String(value || '').trim().toLowerCase();
     return v === 'markdown' || v === 'md';
   }

   function isMarkdownFilename(name) {
     const n = String(name || '').trim().toLowerCase();
     return /\.(md|markdown)$/i.test(n);
   }
   ```

2. **`editor-manager.js`** - מספק API להזרקת טקסט:
   ```javascript
   // שורה 705 - פונקציה קיימת!
   insertTextAtCursor(nextText)
   ```

3. **`code-tools.js`** - תבנית לאינטגרציה של סרגל כלים (Event Delegation)

---

## 💻 מימוש שלב-אחר-שלב

### שלב 1: יצירת קובץ CSS - `static/css/markdown-toolbar.css`

```css
/* ============================================
   סרגל כלים Markdown
   ============================================ */

/* הסרגל הראשי */
.md-toolbar-group {
  display: none; /* מוסתר בברירת מחדל */
  align-items: center;
  gap: 0.25rem;
  margin-inline-start: auto; /* דחיפה ימינה (RTL) */
  padding-inline-start: 0.75rem;
  border-inline-start: 1px solid rgba(255, 255, 255, 0.15);
}

/* כשמזהים Markdown */
.md-toolbar-group.is-visible {
  display: flex;
}

/* כפתור ראשי */
.md-toolbar-trigger {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.4rem 0.65rem;
  font-size: 0.85rem;
  background: rgba(100, 200, 150, 0.15);
  border: 1px solid rgba(100, 200, 150, 0.4);
  border-radius: 6px;
  color: var(--text-color, #e0e0e0);
  cursor: pointer;
  transition: all 0.2s ease;
}

.md-toolbar-trigger:hover {
  background: rgba(100, 200, 150, 0.25);
  border-color: rgba(100, 200, 150, 0.6);
}

.md-toolbar-trigger:focus-visible {
  outline: 2px solid rgba(100, 200, 150, 0.6);
  outline-offset: 2px;
}

.md-toolbar-trigger i {
  font-size: 1rem;
}

/* Dropdown ראשי */
.md-toolbar-dropdown {
  position: absolute;
  top: 100%;
  inset-inline-end: 0;
  min-width: 220px;
  margin-top: 4px;
  padding: 0.5rem 0;
  background: rgba(30, 30, 40, 0.98);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 10px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
  z-index: 1000;
  opacity: 0;
  visibility: hidden;
  transform: translateY(-8px);
  transition: all 0.2s ease;
}

.md-toolbar-dropdown.is-open {
  opacity: 1;
  visibility: visible;
  transform: translateY(0);
}

/* פריטי תפריט */
.md-toolbar-item {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  width: 100%;
  padding: 0.55rem 1rem;
  font-size: 0.9rem;
  background: transparent;
  border: none;
  color: var(--text-color, #e0e0e0);
  cursor: pointer;
  text-align: start;
  transition: background 0.15s ease;
}

.md-toolbar-item:hover {
  background: rgba(100, 200, 150, 0.15);
}

.md-toolbar-item:focus-visible {
  background: rgba(100, 200, 150, 0.2);
  outline: none;
}

.md-toolbar-item .item-icon {
  width: 1.5rem;
  text-align: center;
  font-size: 1.1rem;
}

.md-toolbar-item .item-label {
  flex: 1;
}

.md-toolbar-item .item-shortcut {
  font-size: 0.75rem;
  opacity: 0.6;
  font-family: monospace;
}

/* מפריד */
.md-toolbar-divider {
  height: 1px;
  margin: 0.4rem 0.75rem;
  background: rgba(255, 255, 255, 0.1);
}

/* תפריט משנה (Alerts) */
.md-toolbar-submenu-trigger {
  position: relative;
}

.md-toolbar-submenu-trigger::after {
  content: '◀';
  margin-inline-start: auto;
  font-size: 0.65rem;
  opacity: 0.6;
}

.md-toolbar-submenu {
  position: absolute;
  top: 0;
  inset-inline-end: 100%;
  min-width: 200px;
  margin-inline-end: 4px;
  padding: 0.5rem 0;
  background: rgba(30, 30, 40, 0.98);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 10px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
  opacity: 0;
  visibility: hidden;
  transform: translateX(8px);
  transition: all 0.2s ease;
  max-height: 400px;
  overflow-y: auto;
}

/* התאמה ל-RTL */
[dir="rtl"] .md-toolbar-submenu,
:root[dir="rtl"] .md-toolbar-submenu {
  inset-inline-end: auto;
  inset-inline-start: 100%;
  margin-inline-end: 0;
  margin-inline-start: 4px;
  transform: translateX(-8px);
}

.md-toolbar-submenu-trigger:hover .md-toolbar-submenu,
.md-toolbar-submenu-trigger:focus-within .md-toolbar-submenu {
  opacity: 1;
  visibility: visible;
  transform: translateX(0);
}

/* רספונסיביות - מובייל */
@media (max-width: 640px) {
  .md-toolbar-dropdown {
    position: fixed;
    top: auto;
    bottom: 0;
    left: 0;
    right: 0;
    min-width: 100%;
    border-radius: 16px 16px 0 0;
    max-height: 60vh;
    overflow-y: auto;
  }

  .md-toolbar-submenu {
    position: static;
    min-width: 100%;
    margin: 0;
    padding: 0 0.5rem;
    border: none;
    box-shadow: none;
    background: transparent;
    opacity: 1;
    visibility: visible;
    transform: none;
    max-height: none;
  }

  .md-toolbar-submenu-trigger::after {
    content: '▼';
  }
}
```

---

### שלב 2: יצירת קובץ JavaScript - `static/js/markdown-toolbar.js`

```javascript
/**
 * Markdown Toolbar
 * ================
 * סרגל כלים מהיר להזרקת תבניות Markdown.
 * תומך בשני הדפים: upload.html ו-edit_file.html
 */

const MarkdownToolbar = {
  // ---------- הגדרות תבניות ----------
  templates: {
    table: `| כותרת 1 | כותרת 2 |
|-----------|-----------|
| תוכן      | תוכן      |
`,

    details: `::: details לחצו כאן לתוכן מוסתר

### כותרת פנימית

תוכן שמוסתר עד ללחיצה.

:::
`,

    highlight: '==טקסט מודגש==',

    taskList: `- [ ] משימה ראשונה
- [ ] משימה שנייה
- [x] משימה שהושלמה
`,

    // Alerts / Callouts
    alerts: {
      note: `::: note
זהו בלוק מסוג **note** — טיפים כלליים או תזכורות חשובות 🧭
:::
`,
      tip: `::: tip
טיפ חכם 💡
נסה ללחוץ על הקיפול ולראות איך הוא מתנהג!
:::
`,
      warning: `::: warning
⚠️ זה בלוק אזהרה — משהו שכדאי לשים לב אליו במיוחד.
:::
`,
      danger: `::: danger
🚨 זה בלוק **סכנה** — שימוש בזהירות!
:::
`,
      info: `::: info
בלוק מידע כללי 📘 — יכול לשמש להסברים טכניים או הערות מערכת.
:::
`,
      success: `::: success
🎯 הצלחה! הפעולה הושלמה בהצלחה.
:::
`,
      question: `::: question
❓ שאלה פתוחה — אפשר להוסיף תשובות מתחת.
:::
`,
      example: `::: example
🧩 דוגמה לשימוש בפיצ'ר חדש.
:::
`,
      quote: `::: quote
> "הדמיון חשוב מהידע." — איינשטיין
:::
`,
      experimental: `::: experimental
🧪 פיצ'ר ניסיוני — לבדיקה בלבד.
:::
`,
      deprecated: `::: deprecated
🚫 בלוק שהוכרז כמיושן — לא לשימוש יותר.
:::
`,
      todo: `::: todo
📝 משימה לביצוע בהמשך.
:::
`,
      abstract: `::: abstract
סיכום קצר של רעיון או פרק במסמך.
:::
`
    }
  },

  // ---------- מצב פנימי ----------
  _initialized: false,
  _dropdownOpen: false,

  // ---------- אתחול ----------
  init() {
    if (this._initialized) return;

    this.bindEvents();
    this.updateVisibility();
    this._initialized = true;

    // האזנה לשינויים בשם קובץ ושפה
    const filenameInput = document.getElementById('fileNameInput');
    const languageSelect = document.getElementById('languageSelect');

    if (filenameInput) {
      filenameInput.addEventListener('input', () => this.updateVisibility());
      filenameInput.addEventListener('blur', () => this.updateVisibility());
    }
    if (languageSelect) {
      languageSelect.addEventListener('change', () => this.updateVisibility());
    }
  },

  // ---------- בדיקה אם Markdown ----------
  isMarkdownContext() {
    const filenameInput = document.getElementById('fileNameInput');
    const languageSelect = document.getElementById('languageSelect');

    const filename = filenameInput ? filenameInput.value : '';
    const language = languageSelect ? languageSelect.value : '';

    // בדיקת סיומת קובץ
    const filenameIsMarkdown = /\.(md|markdown)$/i.test(String(filename || '').trim());

    // בדיקת שפה
    const langLower = String(language || '').trim().toLowerCase();
    const languageIsMarkdown = langLower === 'markdown' || langLower === 'md';

    return filenameIsMarkdown || languageIsMarkdown;
  },

  // ---------- הצגת/הסתרת הסרגל ----------
  updateVisibility() {
    const toolbar = document.querySelector('.md-toolbar-group');
    if (!toolbar) return;

    const isMarkdown = this.isMarkdownContext();
    toolbar.classList.toggle('is-visible', isMarkdown);
  },

  // ---------- קישור אירועים ----------
  bindEvents() {
    // Event Delegation על הסרגל
    document.addEventListener('click', (e) => this.handleClick(e));

    // סגירת dropdown בלחיצה מחוץ
    document.addEventListener('click', (e) => {
      if (!e.target.closest('.md-toolbar-group')) {
        this.closeDropdown();
      }
    });

    // קיצורי מקלדת
    document.addEventListener('keydown', (e) => this.handleKeydown(e));

    // סגירה ב-Escape
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        this.closeDropdown();
      }
    });
  },

  // ---------- טיפול בלחיצות ----------
  handleClick(e) {
    // כפתור פתיחת Dropdown
    const trigger = e.target.closest('[data-md-action="toggle-dropdown"]');
    if (trigger) {
      e.preventDefault();
      this.toggleDropdown();
      return;
    }

    // כפתורי הזרקה
    const actionBtn = e.target.closest('[data-md-insert]');
    if (actionBtn) {
      e.preventDefault();
      const templateKey = actionBtn.getAttribute('data-md-insert');
      this.insertTemplate(templateKey);
      this.closeDropdown();
      return;
    }

    // כפתור קישור חכם (מיוחד)
    const smartLinkBtn = e.target.closest('[data-md-action="smart-link"]');
    if (smartLinkBtn) {
      e.preventDefault();
      this.handleSmartLink();
      this.closeDropdown();
      return;
    }
  },

  // ---------- קיצורי מקלדת ----------
  handleKeydown(e) {
    // רק אם במצב Markdown
    if (!this.isMarkdownContext()) return;

    const isMod = e.ctrlKey || e.metaKey;
    const isShift = e.shiftKey;

    // Ctrl+Shift+T = טבלה
    if (isMod && isShift && e.key.toUpperCase() === 'T') {
      e.preventDefault();
      this.insertTemplate('table');
      return;
    }

    // Ctrl+Shift+D = Details
    if (isMod && isShift && e.key.toUpperCase() === 'D') {
      e.preventDefault();
      this.insertTemplate('details');
      return;
    }

    // Ctrl+K = קישור חכם
    if (isMod && !isShift && e.key.toUpperCase() === 'K') {
      e.preventDefault();
      this.handleSmartLink();
      return;
    }

    // Ctrl+Shift+H = Highlight
    if (isMod && isShift && e.key.toUpperCase() === 'H') {
      e.preventDefault();
      this.insertTemplate('highlight');
      return;
    }

    // Ctrl+Shift+C = Checklist
    if (isMod && isShift && e.key.toUpperCase() === 'C') {
      e.preventDefault();
      this.insertTemplate('taskList');
      return;
    }
  },

  // ---------- פתיחה/סגירה של Dropdown ----------
  toggleDropdown() {
    const dropdown = document.querySelector('.md-toolbar-dropdown');
    if (!dropdown) return;

    this._dropdownOpen = !this._dropdownOpen;
    dropdown.classList.toggle('is-open', this._dropdownOpen);

    // Focus על הפריט הראשון
    if (this._dropdownOpen) {
      const firstItem = dropdown.querySelector('.md-toolbar-item');
      if (firstItem) firstItem.focus();
    }
  },

  closeDropdown() {
    const dropdown = document.querySelector('.md-toolbar-dropdown');
    if (dropdown) {
      dropdown.classList.remove('is-open');
      this._dropdownOpen = false;
    }
  },

  // ---------- הזרקת תבנית ----------
  insertTemplate(key) {
    let text = '';

    // בדיקה אם זה Alert
    if (key.startsWith('alert:')) {
      const alertType = key.replace('alert:', '');
      text = this.templates.alerts[alertType] || '';
    } else {
      text = this.templates[key] || '';
    }

    if (!text) {
      console.warn(`[MarkdownToolbar] Unknown template: ${key}`);
      return;
    }

    // שימוש ב-editorManager אם קיים
    if (window.editorManager && typeof window.editorManager.insertTextAtCursor === 'function') {
      window.editorManager.insertTextAtCursor(text);
      this.showStatus(`הוזרק: ${this.getTemplateLabel(key)}`);
      return;
    }

    // Fallback: הזרקה ישירה ל-textarea
    const textarea = document.getElementById('codeTextarea');
    if (textarea) {
      const start = textarea.selectionStart || 0;
      const end = textarea.selectionEnd || start;
      const value = textarea.value || '';

      textarea.value = value.slice(0, start) + text + value.slice(end);
      textarea.focus();
      textarea.setSelectionRange(start + text.length, start + text.length);

      // Dispatch input event לסנכרון
      textarea.dispatchEvent(new Event('input', { bubbles: true }));
      this.showStatus(`הוזרק: ${this.getTemplateLabel(key)}`);
    }
  },

  // ---------- קישור חכם ----------
  async handleSmartLink() {
    let selectedText = '';
    let clipboardUrl = '';

    // קבלת טקסט מסומן
    if (window.editorManager && typeof window.editorManager.getSelectedTextOrAll === 'function') {
      const result = window.editorManager.getSelectedTextOrAll();
      if (result.usedSelection) {
        selectedText = result.text;
      }
    } else {
      const textarea = document.getElementById('codeTextarea');
      if (textarea) {
        const start = textarea.selectionStart || 0;
        const end = textarea.selectionEnd || start;
        if (end > start) {
          selectedText = textarea.value.substring(start, end);
        }
      }
    }

    // קבלת URL מהלוח
    try {
      if (navigator.clipboard && navigator.clipboard.readText) {
        const clipText = await navigator.clipboard.readText();
        // בדיקה אם זה URL תקין
        if (clipText && /^https?:\/\/.+/.test(clipText.trim())) {
          clipboardUrl = clipText.trim();
        }
      }
    } catch (err) {
      console.warn('[MarkdownToolbar] Clipboard read failed:', err);
    }

    // בניית הקישור
    let linkText = '';
    if (selectedText && clipboardUrl) {
      // יש גם טקסט וגם URL - מושלם!
      linkText = `[${selectedText}](${clipboardUrl})`;
    } else if (selectedText) {
      // יש רק טקסט - נבקש URL
      const url = window.prompt('הזן כתובת URL:', 'https://');
      if (url && url !== 'https://') {
        linkText = `[${selectedText}](${url})`;
      } else {
        this.showStatus('בוטל - לא הוזן URL');
        return;
      }
    } else if (clipboardUrl) {
      // יש רק URL - נבקש טקסט
      const text = window.prompt('הזן טקסט לקישור:', 'לחץ כאן');
      if (text) {
        linkText = `[${text}](${clipboardUrl})`;
      } else {
        // רק URL בלי טקסט
        linkText = clipboardUrl;
      }
    } else {
      // אין כלום - נפתח prompt
      const url = window.prompt('הזן כתובת URL:', 'https://');
      if (url && url !== 'https://') {
        const text = window.prompt('הזן טקסט לקישור:', 'לחץ כאן');
        linkText = text ? `[${text}](${url})` : url;
      } else {
        this.showStatus('בוטל');
        return;
      }
    }

    if (!linkText) return;

    // הזרקה / החלפה
    if (window.editorManager && typeof window.editorManager.insertTextAtCursor === 'function') {
      window.editorManager.insertTextAtCursor(linkText);
    } else {
      const textarea = document.getElementById('codeTextarea');
      if (textarea) {
        const start = textarea.selectionStart || 0;
        const end = textarea.selectionEnd || start;
        const value = textarea.value || '';

        textarea.value = value.slice(0, start) + linkText + value.slice(end);
        textarea.focus();
        const newPos = start + linkText.length;
        textarea.setSelectionRange(newPos, newPos);
        textarea.dispatchEvent(new Event('input', { bubbles: true }));
      }
    }

    this.showStatus('קישור נוצר');
  },

  // ---------- הצגת סטטוס ----------
  showStatus(message) {
    const statusEl = document.querySelector('.editor-info-status');
    if (!statusEl) return;

    statusEl.textContent = message;

    // ניקוי אחרי 2 שניות
    setTimeout(() => {
      if (statusEl.textContent === message) {
        statusEl.textContent = '';
      }
    }, 2000);
  },

  // ---------- תרגום מפתח לתווית ----------
  getTemplateLabel(key) {
    const labels = {
      table: 'טבלה',
      details: 'קיפול',
      highlight: 'מארקר',
      taskList: 'רשימת משימות',
      'alert:note': 'התראה - Note',
      'alert:tip': 'התראה - Tip',
      'alert:warning': 'התראה - Warning',
      'alert:danger': 'התראה - Danger',
      'alert:info': 'התראה - Info',
      'alert:success': 'התראה - Success',
      'alert:question': 'התראה - Question',
      'alert:example': 'התראה - Example',
      'alert:quote': 'התראה - Quote',
      'alert:experimental': 'התראה - Experimental',
      'alert:deprecated': 'התראה - Deprecated',
      'alert:todo': 'התראה - Todo',
      'alert:abstract': 'התראה - Abstract'
    };
    return labels[key] || key;
  }
};

// אתחול אוטומטי
document.addEventListener('DOMContentLoaded', () => {
  MarkdownToolbar.init();
});

// ייצוא גלובלי
window.MarkdownToolbar = MarkdownToolbar;
```

---

### שלב 3: עדכון `templates/components/editor_components.html` - הוספת מאקרו

הוסף את המאקרו הבא **בסוף הקובץ**, לפני התגית `</output>`:

```jinja2
{% macro markdown_toolbar() %}
{# Markdown Toolbar - סרגל כלים מהיר להזרקת תבניות #}
<div class="md-toolbar-group" data-component="markdown-toolbar">
  <button
    type="button"
    class="md-toolbar-trigger"
    data-md-action="toggle-dropdown"
    title="כלי Markdown"
    aria-expanded="false"
    aria-haspopup="true"
  >
    <i class="fas fa-pen-fancy"></i>
    <span>MD</span>
  </button>

  <div class="md-toolbar-dropdown" role="menu" aria-label="כלי Markdown">
    {# טבלה #}
    <button type="button" class="md-toolbar-item" data-md-insert="table" role="menuitem">
      <span class="item-icon">📊</span>
      <span class="item-label">טבלה</span>
      <span class="item-shortcut">Ctrl+Shift+T</span>
    </button>

    {# קישור חכם #}
    <button type="button" class="md-toolbar-item" data-md-action="smart-link" role="menuitem">
      <span class="item-icon">🔗</span>
      <span class="item-label">קישור חכם</span>
      <span class="item-shortcut">Ctrl+K</span>
    </button>

    {# מארקר #}
    <button type="button" class="md-toolbar-item" data-md-insert="highlight" role="menuitem">
      <span class="item-icon">🎨</span>
      <span class="item-label">מארקר</span>
      <span class="item-shortcut">Ctrl+Shift+H</span>
    </button>

    {# קיפול #}
    <button type="button" class="md-toolbar-item" data-md-insert="details" role="menuitem">
      <span class="item-icon">📁</span>
      <span class="item-label">קיפול</span>
      <span class="item-shortcut">Ctrl+Shift+D</span>
    </button>

    {# רשימת משימות #}
    <button type="button" class="md-toolbar-item" data-md-insert="taskList" role="menuitem">
      <span class="item-icon">✅</span>
      <span class="item-label">רשימת משימות</span>
      <span class="item-shortcut">Ctrl+Shift+C</span>
    </button>

    <div class="md-toolbar-divider" role="separator"></div>

    {# תפריט משנה - התראות #}
    <div class="md-toolbar-submenu-trigger">
      <button type="button" class="md-toolbar-item" role="menuitem" aria-haspopup="true">
        <span class="item-icon">🔔</span>
        <span class="item-label">התראות (Alerts)</span>
      </button>
      <div class="md-toolbar-submenu" role="menu" aria-label="סוגי התראות">
        <button type="button" class="md-toolbar-item" data-md-insert="alert:note" role="menuitem">
          <span class="item-icon">🧭</span>
          <span class="item-label">Note</span>
        </button>
        <button type="button" class="md-toolbar-item" data-md-insert="alert:tip" role="menuitem">
          <span class="item-icon">💡</span>
          <span class="item-label">Tip</span>
        </button>
        <button type="button" class="md-toolbar-item" data-md-insert="alert:warning" role="menuitem">
          <span class="item-icon">⚠️</span>
          <span class="item-label">Warning</span>
        </button>
        <button type="button" class="md-toolbar-item" data-md-insert="alert:danger" role="menuitem">
          <span class="item-icon">🚨</span>
          <span class="item-label">Danger</span>
        </button>
        <button type="button" class="md-toolbar-item" data-md-insert="alert:info" role="menuitem">
          <span class="item-icon">📘</span>
          <span class="item-label">Info</span>
        </button>
        <button type="button" class="md-toolbar-item" data-md-insert="alert:success" role="menuitem">
          <span class="item-icon">🎯</span>
          <span class="item-label">Success</span>
        </button>
        <button type="button" class="md-toolbar-item" data-md-insert="alert:question" role="menuitem">
          <span class="item-icon">❓</span>
          <span class="item-label">Question</span>
        </button>
        <button type="button" class="md-toolbar-item" data-md-insert="alert:example" role="menuitem">
          <span class="item-icon">🧩</span>
          <span class="item-label">Example</span>
        </button>
        <button type="button" class="md-toolbar-item" data-md-insert="alert:quote" role="menuitem">
          <span class="item-icon">💬</span>
          <span class="item-label">Quote</span>
        </button>
        <button type="button" class="md-toolbar-item" data-md-insert="alert:experimental" role="menuitem">
          <span class="item-icon">🧪</span>
          <span class="item-label">Experimental</span>
        </button>
        <button type="button" class="md-toolbar-item" data-md-insert="alert:deprecated" role="menuitem">
          <span class="item-icon">🚫</span>
          <span class="item-label">Deprecated</span>
        </button>
        <button type="button" class="md-toolbar-item" data-md-insert="alert:todo" role="menuitem">
          <span class="item-icon">📝</span>
          <span class="item-label">Todo</span>
        </button>
        <button type="button" class="md-toolbar-item" data-md-insert="alert:abstract" role="menuitem">
          <span class="item-icon">📄</span>
          <span class="item-label">Abstract</span>
        </button>
      </div>
    </div>
  </div>
</div>
{% endmacro %}
```

---

### שלב 4: עדכון `upload.html` ו-`edit_file.html`

#### 4.1 עדכון ה-Import בראש הקובץ

בשני הקבצים, עדכן את שורת ה-import (בערך שורה 5):

**לפני:**
```jinja2
{% from "components/editor_components.html" import image_uploader, code_tools_toolbar, code_tools_modal %}
```

**אחרי:**
```jinja2
{% from "components/editor_components.html" import image_uploader, code_tools_toolbar, code_tools_modal, markdown_toolbar %}
```

#### 4.2 הוספת ה-CSS ב-block extra_css

בשני הקבצים, הוסף את השורה הבאה בתוך `{% block extra_css %}`:

```jinja2
<link rel="stylesheet" href="{{ url_for('static', filename='css/markdown-toolbar.css') }}?v={{ static_version }}">
```

#### 4.3 הוספת הסרגל ליד code_tools_toolbar

בשני הקבצים, מצא את השורה:
```jinja2
{{ code_tools_toolbar(user_is_admin=user_is_admin) }}
```

והוסף **מתחתיה**:
```jinja2
{{ markdown_toolbar() }}
```

#### 4.4 הוספת ה-JS ב-block extra_js

בשני הקבצים, הוסף את השורה הבאה בתוך `{% block extra_js %}`:

```jinja2
<script src="{{ url_for('static', filename='js/markdown-toolbar.js') }}?v={{ static_version }}" defer></script>
```

---

### שלב 5: עדכון מיקום הסרגל ב-DOM

כדי שהסרגל יופיע **בשורת כפתורי העורך** (ליד "העתק", "בחר הכל", "הדבק"), צריך להוסיף לוגיקה ב-`markdown-toolbar.js` שמזיזה את הסרגל למיקום הנכון.

הוסף את הפונקציה הבאה ל-`MarkdownToolbar`:

```javascript
// ---------- העברת הסרגל לשורת העורך ----------
moveToEditorRow() {
  const toolbar = document.querySelector('.md-toolbar-group');
  const editorActions = document.querySelector('.editor-switcher-actions');

  if (toolbar && editorActions) {
    // בדוק אם כבר הועבר
    if (toolbar.parentElement === editorActions) return;

    // הכנס אחרי editor-clipboard-actions או code-tools-group
    const codeTools = editorActions.querySelector('.code-tools-group');
    const clipboardActions = editorActions.querySelector('.editor-clipboard-actions');

    if (codeTools) {
      codeTools.after(toolbar);
    } else if (clipboardActions) {
      clipboardActions.after(toolbar);
    } else {
      editorActions.appendChild(toolbar);
    }
  }
},
```

ועדכן את `init()`:

```javascript
init() {
  if (this._initialized) return;

  this.bindEvents();
  this.updateVisibility();
  this.moveToEditorRow(); // הוספה!
  this._initialized = true;

  // ... שאר הקוד
}
```

גם הוסף MutationObserver כמו ב-`code-tools.js` למקרה שה-editor-switcher נוצר מאוחר:

```javascript
// בסוף הקובץ, אחרי window.MarkdownToolbar = MarkdownToolbar;

// ניסיון נוסף אם editor-switcher נוצר מאוחר יותר
const mdObserver = new MutationObserver((mutations) => {
  for (const mutation of mutations) {
    if (mutation.addedNodes.length) {
      const editorSwitcher = document.querySelector('.editor-switcher-actions');
      if (editorSwitcher && MarkdownToolbar._initialized) {
        MarkdownToolbar.moveToEditorRow();
        MarkdownToolbar.updateVisibility();
      }
    }
  }
});

if (document.body) {
  mdObserver.observe(document.body, { childList: true, subtree: true });
}
```

---

## 🧪 בדיקות

### בדיקה ידנית

1. **בדיקת הופעה אוטומטית:**
   - גש לעמוד העלאת קובץ (`/upload`)
   - שנה את שם הקובץ ל-`test.md` → הסרגל צריך להופיע
   - שנה את השפה ל-"Markdown" → הסרגל צריך להופיע
   - שנה בחזרה ל-`.py` או שפה אחרת → הסרגל צריך להיעלם

2. **בדיקת הזרקת תבניות:**
   - לחץ על כפתור ה-MD → Dropdown נפתח
   - לחץ על "טבלה" → טבלה מוזרקת למיקום הסמן
   - לחץ על "התראות" → תפריט משנה נפתח
   - לחץ על "Warning" → Alert מוזרק

3. **בדיקת קיצורי מקלדת:**
   - `Ctrl+Shift+T` → טבלה
   - `Ctrl+K` → קישור חכם (עם/בלי טקסט מסומן)
   - `Ctrl+Shift+H` → מארקר

4. **בדיקת קישור חכם:**
   - העתק URL ללוח (`Ctrl+C` על כתובת)
   - סמן טקסט בעורך
   - לחץ `Ctrl+K` → הטקסט נעטף עם ה-URL

### בדיקות אוטומטיות (Jest/Playwright)

```javascript
// tests/markdown-toolbar.test.js
describe('MarkdownToolbar', () => {
  test('isMarkdownContext returns true for .md files', () => {
    document.body.innerHTML = '<input id="fileNameInput" value="test.md">';
    expect(MarkdownToolbar.isMarkdownContext()).toBe(true);
  });

  test('isMarkdownContext returns true for Markdown language', () => {
    document.body.innerHTML = `
      <input id="fileNameInput" value="test.txt">
      <select id="languageSelect"><option value="markdown" selected>Markdown</option></select>
    `;
    expect(MarkdownToolbar.isMarkdownContext()).toBe(true);
  });

  test('isMarkdownContext returns false for non-markdown', () => {
    document.body.innerHTML = `
      <input id="fileNameInput" value="test.py">
      <select id="languageSelect"><option value="python" selected>Python</option></select>
    `;
    expect(MarkdownToolbar.isMarkdownContext()).toBe(false);
  });
});
```

---

## 📈 שיפורים עתידיים

### שלב 2 - תכונות מתקדמות

- [ ] **היסטוריית תבניות**: לזכור תבניות שהמשתמש השתמש בהן לאחרונה (localStorage)
- [ ] **תבניות מותאמות אישית**: לאפשר למשתמש לשמור תבניות משלו
- [ ] **עורך טבלאות ויזואלי**: GUI להגדרת מספר עמודות/שורות לפני הזרקה
- [ ] **תצוגה מקדימה**: הצגת Preview של התבנית לפני הזרקה
- [ ] **Undo/Redo**: אפשרות לבטל הזרקה אחרונה

### שלב 3 - אינטגרציות

- [ ] **אינטגרציה עם Live Preview**: רענון אוטומטי של התצוגה המקדימה
- [ ] **שמירת העדפות בשרת**: סנכרון תבניות מותאמות בין מכשירים
- [ ] **ייבוא/ייצוא תבניות**: שיתוף תבניות עם משתמשים אחרים

---

## 🚀 הוראות Deploy

```bash
# 1. יצירת branch חדש
git checkout -b feature/markdown-toolbar

# 2. יצירת הקבצים
touch webapp/static/css/markdown-toolbar.css
touch webapp/static/js/markdown-toolbar.js

# 3. העתקת התוכן מהמדריך לקבצים

# 4. עדכון הקבצים הקיימים:
#    - templates/components/editor_components.html
#    - templates/upload.html
#    - templates/edit_file.html

# 5. בדיקה מקומית
cd webapp && python -m http.server 8000
# או הרצת השרת המלא

# 6. Commit
git add -A
git commit -m "feat(webapp): add Markdown toolbar for quick template injection

- Add CSS for toolbar styling (dropdown, submenu, responsive)
- Add JS for template injection logic and keyboard shortcuts
- Add Jinja macro for toolbar HTML
- Integrate with upload.html and edit_file.html
- Support 6 main tools: table, alerts (13 types), details, smart link, highlight, task list
- Auto-show toolbar only for Markdown files

Closes #XXX"

# 7. Push ו-PR
git push origin feature/markdown-toolbar
gh pr create --title "הוספת סרגל כלים Markdown" \
  --body "## Summary
- סרגל כלים חדש לקבצי Markdown
- 6 כלים: טבלה, התראות, קיפול, קישור חכם, מארקר, רשימת משימות
- קיצורי מקלדת
- זיהוי אוטומטי לפי סיומת/שפה

## Test Plan
- [ ] בדיקת הופעה אוטומטית ב-upload.html
- [ ] בדיקת הופעה אוטומטית ב-edit_file.html
- [ ] בדיקת הזרקת כל התבניות
- [ ] בדיקת קיצורי מקלדת
- [ ] בדיקת קישור חכם עם/בלי clipboard
- [ ] בדיקה במובייל"
```

---

## 📚 סיכום

מדריך זה מספק תשתית מלאה להוספת סרגל כלים Markdown ל-WebApp. הפיצ'ר:

✅ **משתלב בארכיטקטורה הקיימת** - משתמש ב-editorManager, file-form-manager, ובתבניות Jinja הקיימות

✅ **עוקב אחר הקונבנציות** - Event Delegation, CSS variables, ARIA attributes

✅ **תומך בשני הדפים** - upload.html ו-edit_file.html

✅ **רספונסיבי** - תמיכה במובייל עם התאמות UI

✅ **נגיש** - תמיכה במקלדת, ARIA roles, focus management

בהצלחה במימוש! 🚀
