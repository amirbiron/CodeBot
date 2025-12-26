/**
 * Code Tools Integration
 * ======================
 * אינטגרציה של כלי עיצוב/lint עם עורך הקבצים הקיים.
 */

const CodeToolsIntegration = {
  /**
   * אתחול - נקרא מתוך FileFormManager
   */
  init(editorInstance, languageSelect) {
    this.editor = editorInstance;
    this.languageSelect = languageSelect;
    this.bindEvents();
    this.updateToolsVisibility();
  },

  /**
   * קישור אירועים
   */
  bindEvents() {
    // כפתורי Toolbar
    document.getElementById('btn-format-code')?.addEventListener('click', () => this.formatCode());
    document.getElementById('btn-lint-code')?.addEventListener('click', () => this.lintCode());

    // תפריט תיקון
    document.querySelectorAll('[data-level]').forEach((btn) => {
      btn.addEventListener('click', () => this.autoFix(btn.dataset.level));
    });

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
  },

  /**
   * הצגת/הסתרת כלים לפי שפה
   */
  updateToolsVisibility() {
    const rawLanguage = this.languageSelect?.value || 'text';
    const language = String(rawLanguage).toLowerCase().trim();
    const toolsGroup = document.querySelector('.code-tools-group');

    if (toolsGroup) {
      // כרגע תומכים רק ב-Python (case-insensitive)
      const isPython = language === 'python' || language === 'py';
      toolsGroup.style.display = isPython ? 'flex' : 'none';
    }
  },

  /**
   * קבלת קוד מה-editor
   */
  getCode() {
    if (this.editor && typeof this.editor.getValue === 'function') {
      return this.editor.getValue();
    }
    return document.getElementById('codeTextarea')?.value || '';
  },

  /**
   * עדכון קוד ב-editor
   */
  setCode(code) {
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
      this.showStatus('אין קוד לעיצוב', 'warning');
      return;
    }

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
            this.showStatus(`עוצב בהצלחה (${result.lines_changed} שורות)`, 'success');
          }
        } else {
          this.showStatus('הקוד כבר מעוצב', 'info');
        }
      } else {
        this.showStatus(result.error || 'שגיאה בעיצוב', 'error');
      }
    } catch (error) {
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
      this.showStatus('אין קוד לבדיקה', 'warning');
      return;
    }

    this.showStatus('בודק...', 'loading');

    try {
      const response = await fetch('/api/code/lint', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code, language: 'python' }),
      });

      const result = await response.json();

      if (result.success) {
        this.showLintResults(result);
      } else {
        this.showStatus(result.error || 'שגיאה בבדיקה', 'error');
      }
    } catch (error) {
      this.showStatus('שגיאה בתקשורת', 'error');
      console.error('Lint error:', error);
    }
  },

  /**
   * תיקון אוטומטי
   */
  async autoFix(level) {
    const code = this.getCode();
    if (!code.trim()) {
      this.showStatus('אין קוד לתיקון', 'warning');
      return;
    }

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
            result.fixes_applied
          );

          if (confirmed) {
            this.setCode(result.fixed_code);
            this.showStatus(`תוקן: ${result.fixes_applied.join(', ')}`, 'success');
          }
        } else {
          this.showStatus('אין תיקונים נדרשים', 'info');
        }
      } else {
        this.showStatus(result.error || 'שגיאה בתיקון', 'error');
      }
    } catch (error) {
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
  async showDiffConfirmation(original, modified, changesCount, fixesList = null) {
    return new Promise((resolve) => {
      // חישוב diff
      const diffLines = this.computeDiff(original, modified);

      let html = `
                <div class="diff-preview">
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
   * הצגת modal
   */
  showModal(title, content, buttons) {
    // שימוש במנגנון modal קיים או יצירת אחד פשוט
    const modal = document.createElement('div');
    modal.className = 'code-tools-modal';
    modal.innerHTML = `
            <div class="modal-backdrop"></div>
            <div class="modal-content">
                <div class="modal-header">
                    <h3>${title}</h3>
                    <button class="modal-close">&times;</button>
                </div>
                <div class="modal-body">${content}</div>
                <div class="modal-footer">
                    ${buttons
                      .map(
                        (b) => `
                        <button class="btn ${b.primary ? 'btn-primary' : 'btn-outline'}"
                                data-action="${b.action === 'close' ? 'close' : 'custom'}">
                            ${b.text}
                        </button>
                    `
                      )
                      .join('')}
                </div>
            </div>
        `;

    document.body.appendChild(modal);

    // Bind events
    modal.querySelector('.modal-close').onclick = () => modal.remove();
    modal.querySelector('.modal-backdrop').onclick = () => modal.remove();

    buttons.forEach((btn, i) => {
      const btnEl = modal.querySelectorAll('.modal-footer button')[i];
      if (btnEl && typeof btn.action === 'function') {
        btnEl.onclick = () => {
          btn.action();
          modal.remove();
        };
      } else if (btnEl) {
        btnEl.onclick = () => modal.remove();
      }
    });
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

