/**
 * Compare View - מודול השוואת קבצים
 */

window.CompareView = (function() {
    'use strict';

    // State
    let state = {
        fileId: null,
        fileName: null,
        language: 'text',
        currentVersion: 1,
        leftVersion: null,
        rightVersion: null,
        diffData: null,
        viewMode: 'side-by-side', // side-by-side, unified, inline
        syncScroll: true,
    };

    // DOM Elements
    let elements = {};

    /**
     * אתחול המודול
     */
    function init(config) {
        Object.assign(state, config);
        state.leftVersion = Math.max(1, state.currentVersion - 1);
        state.rightVersion = state.currentVersion;

        cacheElements();
        bindEvents();
        loadDiff();
    }

    /**
     * שמירת הפניות ל-DOM elements
     */
    function cacheElements() {
        elements = {
            versionLeft: document.getElementById('version-left'),
            versionRight: document.getElementById('version-right'),
            swapBtn: document.getElementById('swap-versions'),
            modeButtons: document.querySelectorAll('[data-mode]'),
            
            // Views
            sideBySideView: document.getElementById('side-by-side-view'),
            unifiedView: document.getElementById('unified-view'),
            inlineView: document.getElementById('inline-view'),
            
            // Content containers
            leftContent: document.getElementById('left-content'),
            rightContent: document.getElementById('right-content'),
            unifiedContent: document.getElementById('unified-content'),
            inlineContent: document.getElementById('inline-content'),
            
            // Labels
            leftVersionLabel: document.getElementById('left-version-label'),
            rightVersionLabel: document.getElementById('right-version-label'),
            
            // Stats
            statAdded: document.querySelector('#stat-added span'),
            statRemoved: document.querySelector('#stat-removed span'),
            statModified: document.querySelector('#stat-modified span'),
            statUnchanged: document.querySelector('#stat-unchanged span'),
            
            // Actions
            copyDiffBtn: document.getElementById('btn-copy-diff'),
            downloadDiffBtn: document.getElementById('btn-download-diff'),
            restoreBtn: document.getElementById('btn-restore'),
            confirmRestoreBtn: document.getElementById('confirm-restore'),
            restoreVersionSpan: document.getElementById('restore-version'),
        };
    }

    /**
     * קישור אירועים
     */
    function bindEvents() {
        // שינוי גרסאות
        elements.versionLeft?.addEventListener('change', () => {
            state.leftVersion = parseInt(elements.versionLeft.value, 10);
            loadDiff();
        });

        elements.versionRight?.addEventListener('change', () => {
            state.rightVersion = parseInt(elements.versionRight.value, 10);
            loadDiff();
        });

        // החלפת גרסאות
        elements.swapBtn?.addEventListener('click', swapVersions);

        // מצבי תצוגה
        elements.modeButtons?.forEach(btn => {
            btn.addEventListener('click', () => setViewMode(btn.dataset.mode));
        });

        // סנכרון גלילה
        if (elements.leftContent && elements.rightContent) {
            elements.leftContent.addEventListener('scroll', () => {
                if (state.syncScroll) {
                    elements.rightContent.scrollTop = elements.leftContent.scrollTop;
                }
            });
            elements.rightContent.addEventListener('scroll', () => {
                if (state.syncScroll) {
                    elements.leftContent.scrollTop = elements.rightContent.scrollTop;
                }
            });
        }

        // פעולות
        elements.copyDiffBtn?.addEventListener('click', copyDiffToClipboard);
        elements.downloadDiffBtn?.addEventListener('click', downloadPatch);
        elements.confirmRestoreBtn?.addEventListener('click', restoreVersion);
    }

    /**
     * טעינת נתוני ההשוואה מהשרת
     */
    async function loadDiff() {
        try {
            showLoading();

            const url = `/api/compare/versions/${state.fileId}?left=${state.leftVersion}&right=${state.rightVersion}`;
            const response = await fetch(url);
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            state.diffData = await response.json();
            renderDiff();
            updateStats();
            updateLabels();

        } catch (error) {
            console.error('Error loading diff:', error);
            showError('שגיאה בטעינת ההשוואה');
        }
    }

    /**
     * רינדור ההשוואה בהתאם למצב התצוגה
     */
    function renderDiff() {
        if (!state.diffData) return;

        switch (state.viewMode) {
            case 'side-by-side':
                renderSideBySide();
                break;
            case 'unified':
                renderUnified();
                break;
            case 'inline':
                renderInline();
                break;
        }
    }

    /**
     * רינדור תצוגה צד-לצד
     */
    function renderSideBySide() {
        const leftLines = [];
        const rightLines = [];

        state.diffData.lines.forEach(line => {
            // צד שמאל
            leftLines.push(createDiffLineHTML(
                line.line_num_left,
                line.content_left,
                line.change_type === 'removed' ? 'removed' : 
                line.change_type === 'modified' ? 'modified' : 
                line.change_type === 'added' ? 'empty' : ''
            ));

            // צד ימין
            rightLines.push(createDiffLineHTML(
                line.line_num_right,
                line.content_right,
                line.change_type === 'added' ? 'added' : 
                line.change_type === 'modified' ? 'modified' : 
                line.change_type === 'removed' ? 'empty' : ''
            ));
        });

        elements.leftContent.innerHTML = leftLines.join('');
        elements.rightContent.innerHTML = rightLines.join('');
    }

    /**
     * רינדור תצוגה אחודה
     */
    function renderUnified() {
        const lines = [];

        state.diffData.lines.forEach(line => {
            const cssClass = line.change_type !== 'unchanged' ? line.change_type : '';
            
            lines.push(`
                <div class="unified-line ${cssClass}">
                    <div class="line-numbers">
                        <span>${line.line_num_left ?? ''}</span>
                        <span>${line.line_num_right ?? ''}</span>
                    </div>
                    <div class="line-content">${escapeHtml(
                        line.change_type === 'removed' ? line.content_left : 
                        line.change_type === 'added' ? line.content_right :
                        line.content_left ?? line.content_right ?? ''
                    )}</div>
                </div>
            `);
        });

        elements.unifiedContent.innerHTML = lines.join('');
    }

    /**
     * רינדור תצוגת inline
     */
    function renderInline() {
        const lines = [];

        state.diffData.lines.forEach(line => {
            if (line.change_type === 'modified') {
                // הדגשת ההבדלים בתוך השורה
                const highlighted = highlightInlineDiff(
                    line.content_left || '',
                    line.content_right || ''
                );
                lines.push(`
                    <div class="diff-line">
                        <div class="line-number">${line.line_num_right ?? ''}</div>
                        <div class="line-content">${highlighted}</div>
                    </div>
                `);
            } else {
                lines.push(createDiffLineHTML(
                    line.line_num_left ?? line.line_num_right,
                    line.content_left ?? line.content_right,
                    line.change_type
                ));
            }
        });

        elements.inlineContent.innerHTML = lines.join('');
    }

    /**
     * יצירת HTML לשורת diff
     */
    function createDiffLineHTML(lineNum, content, cssClass = '') {
        return `
            <div class="diff-line ${cssClass}">
                <div class="line-number">${lineNum ?? ''}</div>
                <div class="line-content">${escapeHtml(content ?? '')}</div>
            </div>
        `;
    }

    /**
     * הדגשת הבדלים בתוך שורה
     */
    function highlightInlineDiff(oldText, newText) {
        // אלגוריתם פשוט להדגשת הבדלים ברמת תווים
        let result = '';
        let i = 0, j = 0;

        while (i < oldText.length || j < newText.length) {
            if (i < oldText.length && j < newText.length && oldText[i] === newText[j]) {
                result += escapeHtml(newText[j]);
                i++;
                j++;
            } else if (i < oldText.length && (j >= newText.length || oldText[i] !== newText[j])) {
                result += `<span class="inline-removed">${escapeHtml(oldText[i])}</span>`;
                i++;
            } else if (j < newText.length) {
                result += `<span class="inline-added">${escapeHtml(newText[j])}</span>`;
                j++;
            }
        }

        return result;
    }

    /**
     * עדכון סטטיסטיקות
     */
    function updateStats() {
        if (!state.diffData?.stats) return;

        const stats = state.diffData.stats;
        elements.statAdded.textContent = stats.added || 0;
        elements.statRemoved.textContent = stats.removed || 0;
        elements.statModified.textContent = stats.modified || 0;
        elements.statUnchanged.textContent = stats.unchanged || 0;
    }

    /**
     * עדכון תוויות הגרסאות
     */
    function updateLabels() {
        elements.leftVersionLabel.textContent = state.leftVersion;
        elements.rightVersionLabel.textContent = state.rightVersion;
    }

    /**
     * החלפת גרסאות
     */
    function swapVersions() {
        const temp = state.leftVersion;
        state.leftVersion = state.rightVersion;
        state.rightVersion = temp;

        elements.versionLeft.value = state.leftVersion;
        elements.versionRight.value = state.rightVersion;

        loadDiff();
    }

    /**
     * שינוי מצב תצוגה
     */
    function setViewMode(mode) {
        state.viewMode = mode;

        // עדכון כפתורים
        elements.modeButtons.forEach(btn => {
            btn.classList.toggle('active', btn.dataset.mode === mode);
        });

        // הצגת התצוגה המתאימה
        elements.sideBySideView.classList.toggle('active', mode === 'side-by-side');
        elements.unifiedView.classList.toggle('active', mode === 'unified');
        elements.inlineView.classList.toggle('active', mode === 'inline');

        renderDiff();
    }

    /**
     * העתקת ה-diff ללוח
     */
    async function copyDiffToClipboard() {
        if (!state.diffData) return;

        const text = generateUnifiedDiffText();
        
        try {
            await navigator.clipboard.writeText(text);
            showToast('ה-Diff הועתק ללוח!', 'success');
        } catch (error) {
            console.error('Copy failed:', error);
            showToast('שגיאה בהעתקה', 'error');
        }
    }

    /**
     * יצירת טקסט diff בפורמט unified
     */
    function generateUnifiedDiffText() {
        const lines = [`--- ${state.fileName} (v${state.leftVersion})`, `+++ ${state.fileName} (v${state.rightVersion})`];

        state.diffData.lines.forEach(line => {
            if (line.change_type === 'unchanged') {
                lines.push(` ${line.content_left || ''}`);
            } else if (line.change_type === 'removed') {
                lines.push(`-${line.content_left || ''}`);
            } else if (line.change_type === 'added') {
                lines.push(`+${line.content_right || ''}`);
            } else if (line.change_type === 'modified') {
                lines.push(`-${line.content_left || ''}`);
                lines.push(`+${line.content_right || ''}`);
            }
        });

        return lines.join('\n');
    }

    /**
     * הורדת קובץ patch
     */
    function downloadPatch() {
        const text = generateUnifiedDiffText();
        const blob = new Blob([text], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        
        const a = document.createElement('a');
        a.href = url;
        a.download = `${state.fileName}.v${state.leftVersion}-v${state.rightVersion}.patch`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    /**
     * שחזור גרסה
     */
    async function restoreVersion() {
        const versionToRestore = state.leftVersion;
        elements.restoreVersionSpan.textContent = versionToRestore;

        try {
            const response = await fetch(`/api/file/${state.fileId}/restore`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ version: versionToRestore }),
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            showToast(`גרסה ${versionToRestore} שוחזרה בהצלחה!`, 'success');
            
            // רענון הדף אחרי שחזור
            setTimeout(() => window.location.reload(), 1500);

        } catch (error) {
            console.error('Restore failed:', error);
            showToast('שגיאה בשחזור הגרסה', 'error');
        }
    }

    // Utility functions
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function showLoading() {
        // הצגת אינדיקטור טעינה
    }

    function showError(message) {
        showToast(message, 'error');
    }

    function showToast(message, type = 'info') {
        // שימוש במערכת ה-toasts הקיימת אם יש
        if (window.Toast) {
            window.Toast.show(message, type);
        } else {
            alert(message);
        }
    }

    // Public API
    return {
        init,
        setViewMode,
        swapVersions,
        loadDiff,
    };
})();

