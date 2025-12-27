/**
 * Code Tools Integration
 * ======================
 * אינטגרציה של כלי עיצוב/lint עם עורך הקבצים הקיים.
 * תומך בדפים: edit_file.html ו-upload.html
 */

const CodeToolsIntegration = {
  /**
   * אתחול - נקרא מתוך FileFormManager או אוטומטית ב-DOMContentLoaded
   */
  init(editorInstance, languageSelect) {
    this.editor = editorInstance;
    this.languageSelect = languageSelect || document.getElementById('languageSelect');
    this.bindEvents();
    this.updateToolsVisibility();
    this.moveToolsToEditorRow();
  },

  /**
   * אתחול אוטומטי כשהדף נטען (fallback אם FileFormManager לא קורא ל-init)
   */
  autoInit() {
    // אם כבר אותחל, לא לעשות כלום
    if (this._initialized) return;
    
    const languageSelect = document.getElementById('languageSelect');
    const toolsGroup = document.querySelector('.code-tools-group');
    
    if (toolsGroup) {
      this.languageSelect = languageSelect;
      this.bindEvents();
      this.updateToolsVisibility();
      this.moveToolsToEditorRow();
      this._initialized = true;
    }
  },

  /**
   * העברת סרגל הכלים לתוך שורת העורך (ליד כפתורי העתק/בחר הכל/הדבק)
   */
  moveToolsToEditorRow() {
    const toolsGroup = document.querySelector('.code-tools-group');
    const editorActions = document.querySelector('.editor-switcher-actions');
    
    if (toolsGroup && editorActions) {
      // בדוק אם כבר הועבר
      if (toolsGroup.parentElement === editorActions) return;
      
      // הוסף רווח מפריד לפני כפתורי Code Tools
      toolsGroup.classList.add('code-tools-inline');
      
      // הכנס אחרי editor-clipboard-actions
      const clipboardActions = editorActions.querySelector('.editor-clipboard-actions');
      if (clipboardActions) {
        clipboardActions.after(toolsGroup);
      } else {
        editorActions.appendChild(toolsGroup);
      }
    }
  },

  /**
   * קישור אירועים
   */
  bindEvents() {
    // Toolbar (Event Delegation) — לא מסתמך על IDs שעלולים להשתנות במקרו
    const toolsGroup = document.querySelector('.code-tools-group');
    if (toolsGroup && !toolsGroup.__codeToolsBound) {
      toolsGroup.addEventListener('click', (e) => this.handleToolbarClick(e));
      toolsGroup.__codeToolsBound = true;
    }

    // Bootstrap dropdown עשוי להעביר את התפריט לגוף המסמך - נאזין גם שם
    // לכפתורי fix-level בתוך dropdown-menu
    if (!document.__codeToolsDropdownBound) {
      document.addEventListener('click', (e) => {
        const btn = e.target && typeof e.target.closest === 'function' 
          ? e.target.closest('[data-action="fix-level"]') 
          : null;
        if (btn) {
          e.preventDefault();
          const level = String(btn.dataset.level || '').trim();
          if (level) {
            this.prepareFix(level);
          }
        }
      });
      document.__codeToolsDropdownBound = true;
    }

    // קיצורי מקלדת
    document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey) {
        if (e.key === 'F') {
          e.preventDefault();
          this.formatCode();
        } else if (e.key === 'L') {
          e.preventDefault();
          this.lintCode();
        }
      }
    });

    // עדכון כשמשתנה השפה
    this.languageSelect?.addEventListener('change', () => this.updateToolsVisibility());

    // אם המשתמש משנה את הקוד אחרי שחישבנו תיקון — נבטל את ה"החל" כדי לא לדרוס בטעות
    const textarea = document.getElementById('codeTextarea');
    if (textarea && !textarea.__codeToolsBound) {
      textarea.addEventListener('input', () => this.clearPendingFix('code_changed'));
      textarea.__codeToolsBound = true;
    }
  },

  handleToolbarClick(e) {
    const btn = e.target && typeof e.target.closest === 'function' ? e.target.closest('[data-action]') : null;
    if (!btn) {
      console.log('[CodeToolsIntegration] No button with data-action found');
      return;
    }

    const action = String(btn.dataset.action || '').trim();
    console.log('[CodeToolsIntegration] Toolbar click, action:', action);
    if (!action) return;

    if (action === 'format') {
      e.preventDefault();
      console.log('[CodeToolsIntegration] Calling formatCode()');
      this.formatCode();
      return;
    }

    if (action === 'lint') {
      e.preventDefault();
      console.log('[CodeToolsIntegration] Calling lintCode()');
      this.lintCode();
      return;
    }

    if (action === 'fix-level') {
      e.preventDefault();
      const level = String(btn.dataset.level || '').trim();
      console.log('[CodeToolsIntegration] Calling prepareFix with level:', level);
      if (!level) return;
      this.prepareFix(level);
      return;
    }

    if (action === 'apply-fix') {
      e.preventDefault();
      console.log('[CodeToolsIntegration] Calling applyPendingFix()');
      this.applyPendingFix();
      return;
    }

    // action === 'fix-menu' / אחרים: לא עושים כלום כאן
    console.log('[CodeToolsIntegration] Unknown action:', action);
  },

  setApplyEnabled(enabled) {
    const applyBtn = document.querySelector('.code-tools-group [data-action="apply-fix"]');
    if (applyBtn) applyBtn.disabled = !enabled;
  },

  clearPendingFix(reason) {
    if (this._pendingFix) {
      this._pendingFix = null;
      this.setApplyEnabled(false);
      if (reason === 'code_changed') {
        this.showInlineStatus('הקוד השתנה — הרץ "תיקון" שוב לפני החלה', 'info');
      }
    }
  },

  /**
   * שלב 1: חישוב תיקון לפי רמה (לא מחיל על העורך)
   * אחרי שהשרת מחזיר, מפעילים כפתור "החל".
   */
  async prepareFix(level) {
    const code = this.getCode();
    if (!code.trim()) {
      this.showInlineStatus('אין קוד לתיקון', 'warning');
      this.showStatus('אין קוד לתיקון', 'warning');
      return;
    }

    // invalidate קודם (במקרה שהמשתמש מריץ שוב)
    this._pendingFix = null;
    this.setApplyEnabled(false);

    this.showInlineStatus('מתקן...', 'loading');
    this.showStatus('מתקן...', 'loading');

    try {
      const response = await fetch('/api/code/fix', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code, level, language: 'python' }),
      });

      const result = await response.json();

      if (result.success) {
        const fixed = result.fixed_code || '';
        const fixesApplied = Array.isArray(result.fixes_applied) ? result.fixes_applied : [];

        if (!fixed || fixed === code) {
          this._pendingFix = null;
          this.setApplyEnabled(false);
          this.showInlineStatus('אין תיקונים נדרשים', 'success');
          this.showStatus('אין תיקונים נדרשים', 'info');
          return;
        }

        this._pendingFix = {
          level,
          original: code,
          fixed,
          fixesApplied,
        };
        this.setApplyEnabled(true);
        this.showInlineStatus('תיקון מוכן. לחץ "החל" כדי להמשיך', 'success');
        this.showStatus('תיקון מוכן. לחץ "החל" כדי להמשיך', 'success');
      } else {
        this._pendingFix = null;
        this.setApplyEnabled(false);
        this.showInlineStatus((result && result.error) || 'שגיאה בתיקון', 'error');
        this.showStatus(result.error || 'שגיאה בתיקון', 'error');
      }
    } catch (error) {
      this._pendingFix = null;
      this.setApplyEnabled(false);
      this.showInlineStatus('שגיאה בתקשורת', 'error');
      this.showStatus('שגיאה בתקשורת', 'error');
      console.error('Fix error:', error);
    }
  },

  /**
   * שלב 2: החלה (עם אישור) של תיקון שחושב
   */
  async applyPendingFix() {
    const pending = this._pendingFix;
    if (!pending || !pending.fixed) {
      this.showInlineStatus('אין תיקון מוכן להחלה. בחר רמת תיקון קודם', 'warning');
      return;
    }

    // הגנה: אם התוכן בעורך השתנה מאז החישוב — לא מחילים אוטומטית
    const current = this.getCode();
    if (current !== pending.original) {
      this.clearPendingFix('code_changed');
      return;
    }

    const confirmed = await this.showDiffConfirmation(
      pending.original,
      pending.fixed,
      (pending.fixesApplied && pending.fixesApplied.length) || 1,
      pending.fixesApplied && pending.fixesApplied.length ? pending.fixesApplied : null,
      'נמצאו תיקונים. האם להחיל אותם על הקובץ?'
    );

    if (confirmed) {
      this.setCode(pending.fixed);
      this.showInlineStatus('הוחלו התיקונים על הקובץ', 'success');
      this.showStatus('הוחלו התיקונים על הקובץ', 'success');
    } else {
      this.showInlineStatus('ההחלה בוטלה', 'info');
    }

    // בכל מקרה, מנקים מצב "מוכן להחלה" כדי לא לדרוס בטעות שוב
    this._pendingFix = null;
    this.setApplyEnabled(false);
  },

  /**
   * הצגת/הסתרת כלים לפי שפה
   * לוגיקה הפוכה: הכפתורים גלויים כברירת מחדל, ומוסתרים רק אם השפה לא Python.
   * כך אם ה-JS נכשל, הכפתורים עדיין יופיעו.
   */
  updateToolsVisibility() {
    const rawLanguage = this.languageSelect?.value || 'text';
    const language = String(rawLanguage).toLowerCase().trim();
    const toolsGroup = document.querySelector('.code-tools-group');

    if (toolsGroup) {
      // כרגע תומכים רק ב-Python (case-insensitive)
      const isPython = language === 'python' || language === 'py';
      
      // לוגיקה הפוכה: מסתירים רק אם לא פייתון
      if (!isPython) {
        toolsGroup.style.display = 'none';
      } else {
        // אם פייתון - מבטיחים שהכפתורים גלויים (מוחקים display inline style אם יש)
        toolsGroup.style.removeProperty('display');
      }
    } else {
      console.warn('[CodeToolsIntegration] .code-tools-group element not found in DOM');
    }
  },

  /**
   * קבלת קוד מה-editor
   */
  getCode() {
    // fallback חזק: גם אם init לא קיבל editorInstance (או נכשל), נעדיף את editorManager אם קיים
    try {
      if (window.editorManager && typeof window.editorManager.getEditorContent === 'function') {
        const v = window.editorManager.getEditorContent();
        if (typeof v === 'string') return v;
      }
    } catch (_) {}
    if (this.editor && typeof this.editor.getValue === 'function') {
      return this.editor.getValue();
    }
    return document.getElementById('codeTextarea')?.value || '';
  },

  /**
   * עדכון קוד ב-editor
   */
  setCode(code) {
    // fallback חזק: עדכון מפורש של העורך (CodeMirror/textarea) דרך editorManager
    try {
      if (window.editorManager && typeof window.editorManager.setEditorContent === 'function') {
        window.editorManager.setEditorContent(code);
        return;
      }
    } catch (_) {}
    if (this.editor && typeof this.editor.setValue === 'function') {
      this.editor.setValue(code);
    } else {
      const textarea = document.getElementById('codeTextarea');
      if (textarea) textarea.value = code;
    }
  },

  /**
   * עיצוב קוד
   */
  async formatCode() {
    const code = this.getCode();
    if (!code.trim()) {
      this.showInlineStatus('אין קוד לעיצוב', 'warning');
      this.showStatus('אין קוד לעיצוב', 'warning');
      return;
    }

    // אותו טקסט כמו /tools/code
    this.showInlineStatus('מעצב...', 'loading');
    this.showStatus('מעצב...', 'loading');

    try {
      const response = await fetch('/api/code/format', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          code,
          tool: 'black',
          language: 'python',
        }),
      });

      const result = await response.json();

      if (result.success) {
        if (result.has_changes) {
          // הצג diff ובקש אישור
          const confirmed = await this.showDiffConfirmation(code, result.formatted_code, result.lines_changed);

          if (confirmed) {
            this.setCode(result.formatted_code);
            this.showInlineStatus(
              result.has_changes ? `עיצוב הסתיים (${result.lines_changed} שורות)` : 'הקוד כבר מעוצב',
              'success'
            );
            this.showStatus(`עוצב בהצלחה (${result.lines_changed} שורות)`, 'success');
          }
        } else {
          this.showInlineStatus('הקוד כבר מעוצב', 'success');
          this.showStatus('הקוד כבר מעוצב', 'info');
        }
      } else {
        this.showInlineStatus((result && result.error) || 'שגיאה בעיצוב', 'error');
        this.showStatus(result.error || 'שגיאה בעיצוב', 'error');
      }
    } catch (error) {
      this.showInlineStatus('שגיאה בתקשורת', 'error');
      this.showStatus('שגיאה בתקשורת', 'error');
      console.error('Format error:', error);
    }
  },

  /**
   * בדיקת lint
   */
  async lintCode() {
    const code = this.getCode();
    if (!code.trim()) {
      this.showInlineStatus('אין קוד לבדיקה', 'warning');
      this.showStatus('אין קוד לבדיקה', 'warning');
      return;
    }

    // אותו טקסט כמו /tools/code
    this.showInlineStatus('בודק...', 'loading');
    this.showStatus('בודק...', 'loading');

    try {
      const response = await fetch('/api/code/lint', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code, language: 'python' }),
      });

      const result = await response.json();

      if (result.success) {
        this.showInlineStatus('בדיקת Lint הסתיימה', 'success');
        this.showLintResults(result);
      } else {
        this.showInlineStatus((result && result.error) || 'שגיאה בבדיקה', 'error');
        this.showStatus(result.error || 'שגיאה בבדיקה', 'error');
      }
    } catch (error) {
      this.showInlineStatus('שגיאה בתקשורת', 'error');
      this.showStatus('שגיאה בתקשורת', 'error');
      console.error('Lint error:', error);
    }
  },

  /**
   * תיקון אוטומטי
   */
  async autoFix(level) {
    // נשמר לתאימות אחורה (אם יש קריאות ישנות).
    // בפועל, הזרימה בעורך היא: prepareFix -> applyPendingFix.
    const code = this.getCode();
    if (!code.trim()) {
      this.showInlineStatus('אין קוד לתיקון', 'warning');
      this.showStatus('אין קוד לתיקון', 'warning');
      return;
    }

    // אותו טקסט כמו /tools/code
    this.showInlineStatus('מתקן...', 'loading');
    this.showStatus('מתקן...', 'loading');

    try {
      const response = await fetch('/api/code/fix', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code, level, language: 'python' }),
      });

      const result = await response.json();

      if (result.success) {
        if (result.fixes_applied.length > 0) {
          const confirmed = await this.showDiffConfirmation(
            code,
            result.fixed_code,
            result.fixes_applied.length,
            result.fixes_applied,
            'נמצאו תיקונים. האם להחיל אותם על הקובץ?'
          );

          if (confirmed) {
            this.setCode(result.fixed_code);
            this.showInlineStatus(
              result.fixes_applied && result.fixes_applied.length
                ? `תוקן: ${result.fixes_applied.join(', ')}`
                : 'אין תיקונים נדרשים',
              'success'
            );
            this.showStatus(`תוקן: ${result.fixes_applied.join(', ')}`, 'success');
          }
        } else {
          this.showInlineStatus('אין תיקונים נדרשים', 'success');
          this.showStatus('אין תיקונים נדרשים', 'info');
        }
      } else {
        this.showInlineStatus((result && result.error) || 'שגיאה בתיקון', 'error');
        this.showStatus(result.error || 'שגיאה בתיקון', 'error');
      }
    } catch (error) {
      this.showInlineStatus('שגיאה בתקשורת', 'error');
      this.showStatus('שגיאה בתקשורת', 'error');
      console.error('Fix error:', error);
    }
  },

  /**
   * הצגת תוצאות lint
   */
  showLintResults(result) {
    const { score, issues, fixable_count } = result;

    // יצירת modal או panel לתוצאות
    let html = `
            <div class="lint-results">
                <div class="lint-score ${score >= 8 ? 'good' : score >= 5 ? 'medium' : 'bad'}">
                    <span class="score-value">${score}</span>
                    <span class="score-max">/10</span>
                </div>
        `;

    if (issues.length === 0) {
      html += '<p class="no-issues">✅ לא נמצאו בעיות!</p>';
    } else {
      html += `
                <div class="issues-summary">
                    ${issues.length} בעיות נמצאו
                    ${fixable_count > 0 ? `(${fixable_count} ניתנות לתיקון אוטומטי)` : ''}
                </div>
                <ul class="issues-list">
            `;

      for (const issue of issues.slice(0, 10)) {
        html += `
                    <li class="issue-item ${issue.severity}">
                        <span class="issue-location">שורה ${issue.line}</span>
                        <span class="issue-code">${issue.code}</span>
                        <span class="issue-message">${issue.message}</span>
                        ${issue.fixable ? '<span class="issue-fixable">🔧</span>' : ''}
                    </li>
                `;
      }

      if (issues.length > 10) {
        html += `<li class="more-issues">...ועוד ${issues.length - 10} בעיות</li>`;
      }

      html += '</ul>';
    }

    html += '</div>';

    // הצג ב-modal או toast
    this.showModal(
      'תוצאות Lint',
      html,
      fixable_count > 0
        ? [
            { text: 'תקן אוטומטית', action: () => this.autoFix('safe'), primary: true },
            { text: 'סגור', action: 'close' },
          ]
        : [{ text: 'סגור', action: 'close' }]
    );
  },

  /**
   * הצגת diff לאישור
   */
  async showDiffConfirmation(original, modified, changesCount, fixesList = null, promptText = null) {
    return new Promise((resolve) => {
      // חישוב diff
      const diffLines = this.computeDiff(original, modified);

      let html = `
                <div class="diff-preview">
                    ${promptText ? `<div class="diff-prompt" style="margin-bottom: .75rem; font-weight: 600;">${this.escapeHtml(promptText)}</div>` : ''}
                    <div class="diff-stats">
                        ${changesCount} שינויים
                        ${fixesList ? `<br><small>${fixesList.join(', ')}</small>` : ''}
                    </div>
                    <pre class="diff-content">${this.escapeHtml(diffLines)}</pre>
                </div>
            `;

      this.showModal('אישור שינויים', html, [
        { text: 'החל', action: () => resolve(true), primary: true },
        { text: 'ביטול', action: () => resolve(false) },
      ]);
    });
  },

  /**
   * חישוב diff
   *
   * הערה: לגרסת Production מומלץ להשתמש בספריות מקצועיות:
   * - diff-match-patch של Google (קל ומהיר)
   * - merge-view של CodeMirror (כבר קיים בפרויקט!)
   *
   * דוגמה עם CodeMirror MergeView:
   * ```javascript
   * import { MergeView } from '@codemirror/merge';
   * const view = new MergeView({
   *     a: { doc: original },
   *     b: { doc: modified },
   *     parent: container
   * });
   * ```
   */
  computeDiff(original, modified) {
    // גרסה בסיסית - לגרסה 2.0 החלף בספרייה מקצועית
    const origLines = original.split('\n');
    const modLines = modified.split('\n');
    let diff = '';

    const maxLines = Math.max(origLines.length, modLines.length);
    for (let i = 0; i < Math.min(maxLines, 50); i++) {
      const orig = origLines[i] || '';
      const mod = modLines[i] || '';

      if (orig !== mod) {
        if (orig) diff += `- ${orig}\n`;
        if (mod) diff += `+ ${mod}\n`;
      }
    }

    if (maxLines > 50) {
      diff += `\n... (${maxLines - 50} שורות נוספות)`;
    }

    return diff || '(אין שינויים)';
  },

  /**
   * הצגת הודעת סטטוס
   */
  showStatus(message, type) {
    // שימוש במנגנון Toast הקיים
    if (window.showToast) {
      window.showToast(message, type);
    } else {
      console.log(`[${type}] ${message}`);
    }
  },

  /**
   * הודעת סטטוס קצרה באזור הסטטוס מתחת לעורך (כמו "כל הקוד סומן")
   */
  showInlineStatus(message, type) {
    const msg = typeof message === 'string' ? message : '';
    const statusEl =
      document.querySelector('.editor-switcher .editor-info-status') || document.querySelector('.editor-info-status');
    if (!statusEl) return;

    statusEl.textContent = msg;

    if (!this._inlineStatusTimers) this._inlineStatusTimers = new WeakMap();
    const prev = this._inlineStatusTimers.get(statusEl);
    if (prev) clearTimeout(prev);

    // בזמן loading נשאיר את ההודעה עד שתוחלף ב-success/error
    if (type === 'loading') {
      this._inlineStatusTimers.delete(statusEl);
      return;
    }

    // תצוגה קצרה (לא "נתקע" על המסך)
    const timer = setTimeout(() => {
      try {
        // נקה רק אם לא הוחלף בינתיים
        if (statusEl.textContent === msg) statusEl.textContent = '';
      } catch (_) {}
      try {
        this._inlineStatusTimers.delete(statusEl);
      } catch (_) {}
    }, 1800);
    this._inlineStatusTimers.set(statusEl, timer);
  },

  /**
   * הצגת modal באמצעות Bootstrap Modal
   */
  showModal(title, content, buttons) {
    const modalEl = document.getElementById('codeToolsModal');
    const modalTitle = document.getElementById('codeToolsModalLabel');
    const modalBody = document.getElementById('codeToolsModalBody');
    const modalFooter = document.getElementById('codeToolsModalFooter');

    if (!modalEl || !modalTitle || !modalBody || !modalFooter) {
      // Fallback: אם אין Bootstrap Modal בדף, נשתמש ב-confirm/alert
      console.warn('[CodeToolsIntegration] Bootstrap Modal not found, using fallback');
      const plainText = content.replace(/<[^>]*>/g, '');
      
      // אם יש actions (דיאלוג אישור), נשתמש ב-confirm ונפעיל את ה-callbacks
      if (buttons && buttons.length > 0) {
        const hasActionCallbacks = buttons.some(b => typeof b.action === 'function');
        
        if (hasActionCallbacks) {
          // שימוש ב-confirm כדי לקבל תשובה מהמשתמש
          if (confirm(title + '\n\n' + plainText)) {
            // המשתמש לחץ OK - מפעיל את הפעולה הראשית (primary)
            const primaryBtn = buttons.find(b => b.primary && typeof b.action === 'function');
            if (primaryBtn) {
              primaryBtn.action();
            } else if (typeof buttons[0].action === 'function') {
              buttons[0].action();
            }
          } else {
            // המשתמש לחץ Cancel - מפעיל את הפעולה המשנית
            const secondaryBtn = buttons.find(b => !b.primary && typeof b.action === 'function');
            if (secondaryBtn) {
              secondaryBtn.action();
            }
          }
        } else {
          // אין callbacks - רק הודעה
          alert(title + '\n\n' + plainText);
        }
      } else {
        // אין כפתורים - רק הודעה
        alert(title + '\n\n' + plainText);
      }
      return;
    }

    // עדכון תוכן המודל
    modalTitle.textContent = title;
    modalBody.innerHTML = content;

    // יצירת כפתורי הפעולה
    modalFooter.innerHTML = buttons
      .map(
        (b, i) => `
        <button type="button" 
                class="btn ${b.primary ? 'btn-primary' : 'btn-secondary'}"
                data-btn-index="${i}"
                ${b.action === 'close' ? 'data-bs-dismiss="modal"' : ''}>
            ${b.text}
        </button>
      `
      )
      .join('');

    // יצירת instance של Bootstrap Modal
    const bsModal = new bootstrap.Modal(modalEl);

    // קישור אירועים לכפתורים עם פעולות מותאמות
    buttons.forEach((btn, i) => {
      if (typeof btn.action === 'function') {
        const btnEl = modalFooter.querySelector(`[data-btn-index="${i}"]`);
        if (btnEl) {
          btnEl.addEventListener('click', () => {
            btn.action();
            bsModal.hide();
          }, { once: true });
        }
      }
    });

    // הצגת המודל
    bsModal.show();
  },

  /**
   * Escape HTML
   */
  escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  },
};

// Export
window.CodeToolsIntegration = CodeToolsIntegration;

// אתחול אוטומטי כשהדף נטען
document.addEventListener('DOMContentLoaded', () => {
  // המתן מעט כדי לתת ל-editor-manager ליצור את ה-editor-switcher
  setTimeout(() => {
    CodeToolsIntegration.autoInit();
  }, 100);
});

// ניסיון נוסף אם editor-switcher נוצר מאוחר יותר
const observer = new MutationObserver((mutations) => {
  for (const mutation of mutations) {
    if (mutation.addedNodes.length) {
      const editorSwitcher = document.querySelector('.editor-switcher-actions');
      if (editorSwitcher && !CodeToolsIntegration._initialized) {
        CodeToolsIntegration.autoInit();
        // נסה להעביר שוב כי editor-switcher נוצר עכשיו
        CodeToolsIntegration.moveToolsToEditorRow();
      }
    }
  }
});

// צפה בשינויים ב-DOM
if (document.body) {
  observer.observe(document.body, { childList: true, subtree: true });
}

