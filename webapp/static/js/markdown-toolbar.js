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
      important: `::: important
חשוב! זה בלוק **important** — דגש על נקודה קריטית.
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
    this.moveToEditorRow(); // הוספה!
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
    if (!isMarkdown && this._dropdownOpen) {
      this.closeDropdown();
    }
  },

  updateOverflowState(isOpen) {
    const toolbar = document.querySelector('.md-toolbar-group');
    if (!toolbar) return;
    const host = toolbar.closest('.split-view');
    if (!host) return;
    host.classList.toggle('md-toolbar-open', !!isOpen);
  },

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

    // אל "נחטוף" קיצורים כשמשתמש מקליד בשדות אחרים (שם קובץ/תיאור/תגיות/בחירת שפה וכו').
    // הפעלת הקיצורים רק כשהפוקוס בתוך העורך עצמו.
    const target = e && e.target ? e.target : null;
    const tag = target && target.tagName ? String(target.tagName).toUpperCase() : '';
    const isOtherTextarea = tag === 'TEXTAREA' && target.id !== 'codeTextarea';
    const isOtherInput = tag === 'INPUT' || tag === 'SELECT';
    const isContentEditable = !!(target && target.isContentEditable);
    const isEditorFocus =
      (target && target.id === 'codeTextarea') ||
      (target && typeof target.closest === 'function' && (
        target.closest('#editorContainer') ||
        target.closest('.cm-editor')
      ));

    if (isOtherInput || isOtherTextarea || isContentEditable || !isEditorFocus) {
      return;
    }

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
    const trigger = document.querySelector('.md-toolbar-trigger');
    if (!dropdown) return;

    this._dropdownOpen = !this._dropdownOpen;
    dropdown.classList.toggle('is-open', this._dropdownOpen);
    this.updateOverflowState(this._dropdownOpen);

    // עדכון נגישות
    if (trigger) {
      trigger.setAttribute('aria-expanded', String(this._dropdownOpen));
    }

    // Focus על הפריט הראשון
    if (this._dropdownOpen) {
      const firstItem = dropdown.querySelector('.md-toolbar-item');
      if (firstItem) firstItem.focus();
    }
  },

  closeDropdown() {
    const dropdown = document.querySelector('.md-toolbar-dropdown');
    const trigger = document.querySelector('.md-toolbar-trigger');
    if (dropdown) {
      dropdown.classList.remove('is-open');
      this._dropdownOpen = false;
    }
    this.updateOverflowState(false);

    // עדכון נגישות (גם אם כבר סגור)
    if (trigger) {
      trigger.setAttribute('aria-expanded', 'false');
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
      const ok = !!window.editorManager.insertTextAtCursor(text);
      if (ok) {
        this.showStatus(`הוזרק: ${this.getTemplateLabel(key)}`);
        return;
      }
      // אם ההזרקה נכשלה (למשל מצב לא עקבי), ננסה fallback ל-textarea
    }

    // Fallback: הזרקה ישירה ל-textarea תוך שמירה על Undo/Redo
    const textarea = document.getElementById('codeTextarea');
    if (textarea) {
      textarea.focus();

      // אופציה א' (מודרנית ושומרת היסטוריה ברוב הדפדפנים):
      if (typeof textarea.setRangeText === 'function') {
        textarea.setRangeText(text, textarea.selectionStart, textarea.selectionEnd, 'end');
        // 'end' שם את הסמן בסוף הטקסט שהוזרק
      }
      // אופציה ב' (Legacy אבל עובדת מעולה ל-Undo):
      else if (document.execCommand && typeof document.execCommand === 'function') {
        document.execCommand('insertText', false, text);
      }
      // אופציה ג' (מוצא אחרון - שובר את Ctrl+Z):
      else {
        const start = textarea.selectionStart || 0;
        const end = textarea.selectionEnd || start;
        const value = textarea.value || '';
        textarea.value = value.slice(0, start) + text + value.slice(end);
        textarea.setSelectionRange(start + text.length, start + text.length);
      }

      // Dispatch input event לסנכרון (חשוב!)
      textarea.dispatchEvent(new Event('input', { bubbles: true }));
      this.showStatus(`הוזרק: ${this.getTemplateLabel(key)}`);
      return;
    }

    // אם אין יעד הזרקה בכלל
    this.showStatus('נכשל להזריק תבנית');
  },

  // ---------- קישור חכם ----------
  async handleSmartLink() {
    let selectedText = '';
    let clipboardUrl = '';

    // 🔑 חשוב: שומרים את מיקום הסלקציה עכשיו, לפני שהדיאלוגים יגרמו לאיבוד פוקוס!
    let savedStart = 0;
    let savedEnd = 0;
    const textarea = document.getElementById('codeTextarea');
    // גיבוי קואורדינטות מה-textarea (למקרה ש-editorManager קיים חלקית)
    let savedTextareaStart = 0;
    let savedTextareaEnd = 0;
    if (textarea) {
      savedTextareaStart = textarea.selectionStart || 0;
      savedTextareaEnd = textarea.selectionEnd || savedTextareaStart;
    }
    // גיבוי טווח מהעורך (CodeMirror/textarea) דרך editorManager כדי לשרוד prompt/blur
    let savedEditorFrom = null;
    let savedEditorTo = null;

    // קבלת טקסט מסומן + שמירת קואורדינטות
    if (window.editorManager && typeof window.editorManager.getSelectedTextOrAll === 'function') {
      if (typeof window.editorManager.getSelectionRange === 'function') {
        try {
          const r = window.editorManager.getSelectionRange();
          if (r && typeof r.from === 'number' && typeof r.to === 'number') {
            savedEditorFrom = r.from;
            savedEditorTo = r.to;
          }
        } catch (_) {}
      }
      const result = window.editorManager.getSelectedTextOrAll();
      if (result.usedSelection) {
        selectedText = result.text;
      }
      // editorManager ינהל את המיקום בעצמו
      savedStart = -1; // סימון שנשתמש ב-editorManager
    } else if (textarea) {
      savedStart = savedTextareaStart;
      savedEnd = savedTextareaEnd;
      if (savedEnd > savedStart) {
        selectedText = textarea.value.substring(savedStart, savedEnd);
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
      // אם אין גישה ללוח (חסימת הרשאות), נמשיך ונבקש מהמשתמש להזין ידנית
      console.log('[MarkdownToolbar] Clipboard access denied or failed, falling back to manual input');
      // לא מציגים שגיאה למשתמש - פשוט ממשיכים לזרימה הידנית
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

    // הזרקה / החלפה - משתמשים בקואורדינטות שנשמרו!
    if (savedStart === -1 && window.editorManager) {
      let handled = false;

      // העדפה: הזרקה בטווח שנשמר לפני prompt (כדי לא להכניס במקום שגוי אחרי blur)
      if (
        typeof window.editorManager.insertTextAtRange === 'function' &&
        typeof savedEditorFrom === 'number' &&
        typeof savedEditorTo === 'number'
      ) {
        const ok = !!window.editorManager.insertTextAtRange(linkText, savedEditorFrom, savedEditorTo);
        this.showStatus(ok ? 'קישור נוצר' : 'נכשל ליצור קישור');
        handled = true;
      } else if (typeof window.editorManager.insertTextAtCursor === 'function') {
        const ok = !!window.editorManager.insertTextAtCursor(linkText);
        this.showStatus(ok ? 'קישור נוצר' : 'נכשל ליצור קישור');
        handled = true;
      }

      // אם לא טיפלנו (editorManager קיים אבל חסרות פונקציות insert) — ננסה fallback ל-textarea למטה
      if (handled) {
        return;
      }
    }

    if (textarea) {
      textarea.focus();

      // אם editorManager היה זמין רק חלקית (getSelectedTextOrAll קיים אבל insertTextAtCursor לא),
      // savedStart עלול להיות -1. נשתמש בגיבוי מה-textarea כדי להימנע מאינדקסים שליליים/השחתת תוכן.
      const startForInsert = (savedStart === -1) ? savedTextareaStart : savedStart;
      const endForInsert = (savedStart === -1) ? savedTextareaEnd : savedEnd;
      const safeStart = Math.max(0, startForInsert || 0);
      const safeEnd = Math.max(safeStart, Math.max(0, endForInsert || 0));

      // שימוש בקואורדינטות שנשמרו (לא לקרוא selectionStart/End שוב!)
      if (typeof textarea.setRangeText === 'function') {
        textarea.setRangeText(linkText, safeStart, safeEnd, 'end');
      } else if (document.execCommand && typeof document.execCommand === 'function') {
        // צריך לשחזר את הסלקציה לפני execCommand
        textarea.setSelectionRange(safeStart, safeEnd);
        document.execCommand('insertText', false, linkText);
      } else {
        // Fallback אחרון
        const value = textarea.value || '';
        textarea.value = value.slice(0, safeStart) + linkText + value.slice(safeEnd);
        textarea.setSelectionRange(safeStart + linkText.length, safeStart + linkText.length);
      }

      textarea.dispatchEvent(new Event('input', { bubbles: true }));
      this.showStatus('קישור נוצר');
    } else {
      // אין יעד הזרקה — לא נטען עורך בדף/DOM לא זמין
      this.showStatus('נכשל ליצור קישור');
    }
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
      'alert:important': 'התראה - Important',
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

// ניסיון נוסף אם editor-switcher נוצר מאוחר יותר
const mdObserver = new MutationObserver((mutations) => {
  for (const mutation of mutations) {
    if (mutation.addedNodes.length) {
      const editorSwitcher = document.querySelector('.editor-switcher-actions');
      if (editorSwitcher && MarkdownToolbar._initialized) {
        MarkdownToolbar.moveToEditorRow();
        MarkdownToolbar.updateVisibility();
        mdObserver.disconnect(); // 🛑 חשוב: עוצרים את המעקב אחרי שמצאנו - חוסך משאבים!
      }
    }
  }
});

if (document.body) {
  mdObserver.observe(document.body, { childList: true, subtree: true });
}

