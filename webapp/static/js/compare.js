/**
 * Compare View - מודול השוואת קבצים וגרסאות (משולב)
 * 
 * תומך ב-2 מצבים:
 * 1. השוואת גרסאות (versions) - של אותו קובץ
 * 2. השוואת קבצים (files) - בין שני קבצים שונים
 * 
 * @version 2.0.0
 */

window.CompareView = (function() {
    'use strict';

    // =================================================================
    // State Management
    // =================================================================
    
    const state = {
        // Common state
        mode: 'versions', // 'versions' | 'files'
        viewMode: 'side-by-side', // 'side-by-side' | 'unified' | 'inline'
        diffData: null,
        syncScroll: true,
        isLoading: false,
        
        // Versions mode
        fileId: null,
        fileName: null,
        language: 'text',
        currentVersion: 1,
        leftVersion: null,
        rightVersion: null,
        
        // Files mode
        leftFileId: null,
        rightFileId: null,
        leftFileName: null,
        rightFileName: null,
        filesData: [],
    };

    // DOM Elements cache
    let elements = {};
    
    // Scroll sync state
    let scrollSyncState = {
        isScrolling: false,
        scrollTimeout: null,
        rowHeights: new Map(), // מפה של גבהי שורות מסונכרנים
    };

    // =================================================================
    // Initialization
    // =================================================================
    
    /**
     * אתחול מצב השוואת גרסאות
     */
    function init(config) {
        state.mode = 'versions';
        Object.assign(state, config);
        state.leftVersion = Math.max(1, state.currentVersion - 1);
        state.rightVersion = state.currentVersion;

        cacheElements();
        bindCommonEvents();
        bindVersionsEvents();
        loadDiff();
    }

    /**
     * אתחול מצב השוואת קבצים
     */
    function initFilesMode(config) {
        state.mode = 'files';
        state.filesData = config.files || [];
        state.leftFileId = config.selectedLeft;
        state.rightFileId = config.selectedRight;

        cacheElements();
        bindCommonEvents();
        bindFilesEvents();
        
        // אם יש קבצים נבחרים מראש, טען השוואה
        if (state.leftFileId && state.rightFileId) {
            loadFilesDiff();
        }
        
        updateCompareButtonState();
    }

    /**
     * שמירת הפניות ל-DOM elements
     */
    function cacheElements() {
        elements = {
            // Common elements
            modeButtons: document.querySelectorAll('[data-mode]'),
            viewModeToggle: document.getElementById('view-mode-toggle'),
            
            // Views
            sideBySideView: document.getElementById('side-by-side-view'),
            unifiedView: document.getElementById('unified-view'),
            inlineView: document.getElementById('inline-view'),
            
            // Content containers
            leftContent: document.getElementById('left-content'),
            rightContent: document.getElementById('right-content'),
            unifiedContent: document.getElementById('unified-content'),
            inlineContent: document.getElementById('inline-content'),
            
            // Diff container
            diffContainer: document.getElementById('diff-container'),
            
            // Stats
            statsBar: document.getElementById('stats-bar'),
            statAdded: document.querySelector('#stat-added span'),
            statRemoved: document.querySelector('#stat-removed span'),
            statModified: document.querySelector('#stat-modified span'),
            statUnchanged: document.querySelector('#stat-unchanged span'),
            
            // Actions
            copyDiffBtn: document.getElementById('btn-copy-diff'),
            downloadDiffBtn: document.getElementById('btn-download-diff'),
            resultActions: document.getElementById('result-actions'),
            
            // Version mode specific
            versionLeft: document.getElementById('version-left'),
            versionRight: document.getElementById('version-right'),
            swapVersionsBtn: document.getElementById('swap-versions'),
            leftVersionLabel: document.getElementById('left-version-label'),
            rightVersionLabel: document.getElementById('right-version-label'),
            restoreBtn: document.getElementById('btn-restore'),
            confirmRestoreBtn: document.getElementById('confirm-restore'),
            restoreVersionSpan: document.getElementById('restore-version'),
            
            // Files mode specific
            compareForm: document.getElementById('compare-form'),
            fileLeft: document.getElementById('file-left'),
            fileRight: document.getElementById('file-right'),
            swapFilesBtn: document.getElementById('swap-files'),
            compareBtn: document.getElementById('btn-compare'),
            newCompareBtn: document.getElementById('btn-new-compare'),
            leftFileLabel: document.getElementById('left-file-label'),
            rightFileLabel: document.getElementById('right-file-label'),
            searchLeft: document.getElementById('search-left'),
            searchRight: document.getElementById('search-right'),
            previewLeft: document.getElementById('preview-left'),
            previewRight: document.getElementById('preview-right'),
            filterChips: document.querySelectorAll('.filter-chip'),
        };
    }

    // =================================================================
    // Event Binding
    // =================================================================
    
    /**
     * אירועים משותפים לשני המצבים
     */
    function bindCommonEvents() {
        // מצבי תצוגה
        elements.modeButtons?.forEach(btn => {
            btn.addEventListener('click', () => setViewMode(btn.dataset.mode));
        });

        // סנכרון גלילה עם יישור מדויק
        if (elements.leftContent && elements.rightContent) {
            setupSyncScroll();
        }

        // פעולות
        elements.copyDiffBtn?.addEventListener('click', copyDiffToClipboard);
        elements.downloadDiffBtn?.addEventListener('click', downloadPatch);
    }

    /**
     * אירועים ייחודיים למצב גרסאות
     */
    function bindVersionsEvents() {
        elements.versionLeft?.addEventListener('change', () => {
            state.leftVersion = parseInt(elements.versionLeft.value, 10);
            loadDiff();
        });

        elements.versionRight?.addEventListener('change', () => {
            state.rightVersion = parseInt(elements.versionRight.value, 10);
            loadDiff();
        });

        elements.swapVersionsBtn?.addEventListener('click', swapVersions);
        elements.confirmRestoreBtn?.addEventListener('click', restoreVersion);
    }

    /**
     * אירועים ייחודיים למצב קבצים
     */
    function bindFilesEvents() {
        // בחירת קבצים
        elements.fileLeft?.addEventListener('change', (e) => {
            state.leftFileId = e.target.value;
            updateFilePreview('left');
            updateCompareButtonState();
        });

        elements.fileRight?.addEventListener('change', (e) => {
            state.rightFileId = e.target.value;
            updateFilePreview('right');
            updateCompareButtonState();
        });

        // החלפת קבצים
        elements.swapFilesBtn?.addEventListener('click', swapFiles);

        // שליחת טופס
        elements.compareForm?.addEventListener('submit', handleCompareSubmit);

        // השוואה חדשה
        elements.newCompareBtn?.addEventListener('click', resetComparison);

        // חיפוש בתוך הselects
        elements.searchLeft?.addEventListener('input', (e) => filterSelect('left', e.target.value));
        elements.searchRight?.addEventListener('input', (e) => filterSelect('right', e.target.value));

        // סינון לפי שפה
        elements.filterChips?.forEach(chip => {
            chip.addEventListener('click', () => handleLanguageFilter(chip));
        });

        // הצגת preview ראשוני אם יש בחירה
        if (state.leftFileId) updateFilePreview('left');
        if (state.rightFileId) updateFilePreview('right');
    }

    // =================================================================
    // Synchronized Scrolling with Pixel-Perfect Alignment
    // =================================================================
    
    /**
     * הגדרת סנכרון גלילה עם יישור מושלם
     */
    function setupSyncScroll() {
        const leftPane = elements.leftContent;
        const rightPane = elements.rightContent;
        
        if (!leftPane || !rightPane) return;

        // Event handler עם debounce
        function handleScroll(source, target) {
            if (scrollSyncState.isScrolling) return;
            
            scrollSyncState.isScrolling = true;
            
            // סנכרון לפי אחוז גלילה (לתמיכה בגבהים שונים)
            const scrollRatio = source.scrollTop / (source.scrollHeight - source.clientHeight || 1);
            const targetScrollTop = scrollRatio * (target.scrollHeight - target.clientHeight);
            
            target.scrollTop = targetScrollTop;
            
            // איפוס הדגל אחרי frame אחד
            requestAnimationFrame(() => {
                scrollSyncState.isScrolling = false;
            });
        }

        leftPane.addEventListener('scroll', () => {
            if (state.syncScroll) handleScroll(leftPane, rightPane);
        }, { passive: true });

        rightPane.addEventListener('scroll', () => {
            if (state.syncScroll) handleScroll(rightPane, leftPane);
        }, { passive: true });
    }

    /**
     * יישור גבהי שורות - מבטיח שכל שורה תהיה באותו גובה בשני הצדדים
     */
    function alignRowHeights() {
        if (state.viewMode !== 'side-by-side') return;
        
        const leftRows = elements.leftContent?.querySelectorAll('.diff-line');
        const rightRows = elements.rightContent?.querySelectorAll('.diff-line');
        
        if (!leftRows || !rightRows) return;
        
        const rowCount = Math.max(leftRows.length, rightRows.length);
        
        for (let i = 0; i < rowCount; i++) {
            const leftRow = leftRows[i];
            const rightRow = rightRows[i];
            
            if (!leftRow || !rightRow) continue;
            
            // איפוס גובה קודם
            leftRow.style.minHeight = '';
            rightRow.style.minHeight = '';
            
            // חישוב הגובה הטבעי
            const leftHeight = leftRow.getBoundingClientRect().height;
            const rightHeight = rightRow.getBoundingClientRect().height;
            
            // קביעת הגובה המקסימלי לשתי השורות
            const maxHeight = Math.max(leftHeight, rightHeight);
            
            if (leftHeight !== rightHeight) {
                leftRow.style.minHeight = `${maxHeight}px`;
                rightRow.style.minHeight = `${maxHeight}px`;
            }
        }
        
        // שמירת מצב היישור
        scrollSyncState.rowHeights.clear();
    }

    /**
     * יישור מחדש בשינוי גודל חלון
     */
    function setupResizeHandler() {
        let resizeTimeout;
        
        window.addEventListener('resize', () => {
            clearTimeout(resizeTimeout);
            resizeTimeout = setTimeout(() => {
                alignRowHeights();
            }, 150);
        });
    }

    // =================================================================
    // Data Loading
    // =================================================================
    
    /**
     * טעינת diff של גרסאות (מצב versions)
     */
    async function loadDiff() {
        if (state.mode !== 'versions') return;
        
        try {
            setLoading(true);

            const url = `/api/compare/versions/${state.fileId}?left=${state.leftVersion}&right=${state.rightVersion}`;
            const response = await fetch(url);
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            state.diffData = await response.json();
            renderDiff();
            updateStats();
            updateVersionLabels();

        } catch (error) {
            console.error('Error loading diff:', error);
            showError('שגיאה בטעינת ההשוואה');
        } finally {
            setLoading(false);
        }
    }

    /**
     * טעינת diff של קבצים (מצב files)
     */
    async function loadFilesDiff() {
        if (state.mode !== 'files') return;
        if (!state.leftFileId || !state.rightFileId) return;
        
        try {
            setLoading(true);

            const response = await fetch('/api/compare/files', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    left_file_id: state.leftFileId,
                    right_file_id: state.rightFileId,
                }),
            });
            
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.error || `HTTP ${response.status}`);
            }

            state.diffData = await response.json();
            
            // עדכון שמות הקבצים
            state.leftFileName = state.diffData.left_info?.file_name || 'קובץ שמאלי';
            state.rightFileName = state.diffData.right_info?.file_name || 'קובץ ימני';
            
            showComparisonResult();
            renderDiff();
            updateStats();
            updateFileLabels();

        } catch (error) {
            console.error('Error loading files diff:', error);
            showError('שגיאה בטעינת ההשוואה: ' + error.message);
        } finally {
            setLoading(false);
        }
    }

    // =================================================================
    // Rendering
    // =================================================================
    
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
        
        // יישור שורות אחרי רינדור
        requestAnimationFrame(() => {
            alignRowHeights();
            setupResizeHandler();
        });
    }

    /**
     * רינדור תצוגה צד-לצד עם תמיכה ביישור מושלם
     */
    function renderSideBySide() {
        const leftLines = [];
        const rightLines = [];

        state.diffData.lines.forEach((line, index) => {
            const rowId = `row-${index}`;
            
            // צד שמאל
            leftLines.push(createDiffLineHTML(
                line.line_num_left,
                line.content_left,
                getLeftChangeClass(line.change_type),
                rowId
            ));

            // צד ימין
            rightLines.push(createDiffLineHTML(
                line.line_num_right,
                line.content_right,
                getRightChangeClass(line.change_type),
                rowId
            ));
        });

        elements.leftContent.innerHTML = leftLines.join('');
        elements.rightContent.innerHTML = rightLines.join('');
    }

    /**
     * קביעת מחלקת CSS לצד שמאל
     */
    function getLeftChangeClass(changeType) {
        switch (changeType) {
            case 'removed': return 'removed';
            case 'modified': return 'modified';
            case 'added': return 'empty';
            default: return '';
        }
    }

    /**
     * קביעת מחלקת CSS לצד ימין
     */
    function getRightChangeClass(changeType) {
        switch (changeType) {
            case 'added': return 'added';
            case 'modified': return 'modified';
            case 'removed': return 'empty';
            default: return '';
        }
    }

    /**
     * רינדור תצוגה אחודה
     */
    function renderUnified() {
        const lines = [];

        state.diffData.lines.forEach(line => {
            const cssClass = line.change_type !== 'unchanged' ? line.change_type : '';
            const content = line.change_type === 'removed' ? line.content_left : 
                           line.change_type === 'added' ? line.content_right :
                           line.content_left ?? line.content_right ?? '';
            
            lines.push(`
                <div class="unified-line ${cssClass}">
                    <div class="line-numbers">
                        <span>${line.line_num_left ?? ''}</span>
                        <span>${line.line_num_right ?? ''}</span>
                    </div>
                    <div class="line-content">${escapeHtml(content)}</div>
                </div>
            `);
        });

        elements.unifiedContent.innerHTML = lines.join('');
    }

    /**
     * רינדור תצוגת inline עם הדגשה ברמת תווים
     */
    function renderInline() {
        const lines = [];

        state.diffData.lines.forEach(line => {
            if (line.change_type === 'modified' && line.content_left && line.content_right) {
                // הדגשת ההבדלים בתוך השורה
                const highlighted = highlightInlineDiff(
                    line.content_left,
                    line.content_right
                );
                lines.push(`
                    <div class="diff-line modified">
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
     * יצירת HTML לשורת diff עם תמיכה ב-wrap נכון
     */
    function createDiffLineHTML(lineNum, content, cssClass = '', rowId = '') {
        const dataRow = rowId ? `data-row="${rowId}"` : '';
        const escapedContent = escapeHtml(content ?? '');
        
        // שורות ריקות מקבלות תו מיוחד לשמירת הגובה
        const displayContent = escapedContent || '&nbsp;';
        
        return `
            <div class="diff-line ${cssClass}" ${dataRow}>
                <div class="line-number">${lineNum ?? ''}</div>
                <div class="line-content"><pre>${displayContent}</pre></div>
            </div>
        `;
    }

    /**
     * הדגשת הבדלים בתוך שורה (character-level diff)
     */
    function highlightInlineDiff(oldText, newText) {
        const result = [];
        const oldChars = [...oldText];
        const newChars = [...newText];
        
        // אלגוריתם LCS פשוט להשוואה
        const lcs = computeLCS(oldChars, newChars);
        
        let oldIdx = 0;
        let newIdx = 0;
        let lcsIdx = 0;
        
        while (oldIdx < oldChars.length || newIdx < newChars.length) {
            if (lcsIdx < lcs.length) {
                // הוספת תווים שנמחקו (קיימים ב-old אבל לא ב-LCS)
                while (oldIdx < oldChars.length && oldChars[oldIdx] !== lcs[lcsIdx]) {
                    result.push(`<span class="inline-removed">${escapeHtml(oldChars[oldIdx])}</span>`);
                    oldIdx++;
                }
                
                // הוספת תווים שנוספו (קיימים ב-new אבל לא ב-LCS)
                while (newIdx < newChars.length && newChars[newIdx] !== lcs[lcsIdx]) {
                    result.push(`<span class="inline-added">${escapeHtml(newChars[newIdx])}</span>`);
                    newIdx++;
                }
                
                // תו משותף
                if (oldIdx < oldChars.length && newIdx < newChars.length) {
                    result.push(escapeHtml(newChars[newIdx]));
                    oldIdx++;
                    newIdx++;
                    lcsIdx++;
                }
            } else {
                // שאר התווים שנמחקו
                while (oldIdx < oldChars.length) {
                    result.push(`<span class="inline-removed">${escapeHtml(oldChars[oldIdx])}</span>`);
                    oldIdx++;
                }
                // שאר התווים שנוספו
                while (newIdx < newChars.length) {
                    result.push(`<span class="inline-added">${escapeHtml(newChars[newIdx])}</span>`);
                    newIdx++;
                }
            }
        }
        
        return result.join('');
    }

    /**
     * חישוב Longest Common Subsequence
     */
    function computeLCS(arr1, arr2) {
        const m = arr1.length;
        const n = arr2.length;
        const dp = Array(m + 1).fill(null).map(() => Array(n + 1).fill(0));
        
        for (let i = 1; i <= m; i++) {
            for (let j = 1; j <= n; j++) {
                if (arr1[i - 1] === arr2[j - 1]) {
                    dp[i][j] = dp[i - 1][j - 1] + 1;
                } else {
                    dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
                }
            }
        }
        
        // Backtrack to find LCS
        const lcs = [];
        let i = m, j = n;
        while (i > 0 && j > 0) {
            if (arr1[i - 1] === arr2[j - 1]) {
                lcs.unshift(arr1[i - 1]);
                i--;
                j--;
            } else if (dp[i - 1][j] > dp[i][j - 1]) {
                i--;
            } else {
                j--;
            }
        }
        
        return lcs;
    }

    // =================================================================
    // UI Updates
    // =================================================================
    
    /**
     * עדכון סטטיסטיקות
     */
    function updateStats() {
        if (!state.diffData?.stats) return;

        const stats = state.diffData.stats;
        
        if (elements.statAdded) elements.statAdded.textContent = stats.added || 0;
        if (elements.statRemoved) elements.statRemoved.textContent = stats.removed || 0;
        if (elements.statModified) elements.statModified.textContent = stats.modified || 0;
        if (elements.statUnchanged) elements.statUnchanged.textContent = stats.unchanged || 0;
        
        // הצגת הסטטיסטיקות
        elements.statsBar?.classList.remove('d-none');
    }

    /**
     * עדכון תוויות גרסאות (מצב versions)
     */
    function updateVersionLabels() {
        if (elements.leftVersionLabel) {
            elements.leftVersionLabel.textContent = state.leftVersion;
        }
        if (elements.rightVersionLabel) {
            elements.rightVersionLabel.textContent = state.rightVersion;
        }
    }

    /**
     * עדכון תוויות קבצים (מצב files)
     */
    function updateFileLabels() {
        if (elements.leftFileLabel) {
            elements.leftFileLabel.textContent = state.leftFileName || 'קובץ שמאלי';
        }
        if (elements.rightFileLabel) {
            elements.rightFileLabel.textContent = state.rightFileName || 'קובץ ימני';
        }
    }

    /**
     * עדכון תצוגת preview של קובץ נבחר
     */
    function updateFilePreview(side) {
        const fileId = side === 'left' ? state.leftFileId : state.rightFileId;
        const previewEl = side === 'left' ? elements.previewLeft : elements.previewRight;
        
        if (!previewEl) return;
        
        if (!fileId) {
            previewEl.classList.remove('visible');
            return;
        }
        
        // מציאת הקובץ בנתונים
        const file = state.filesData.find(f => String(f._id) === String(fileId));
        
        if (!file) {
            previewEl.classList.remove('visible');
            return;
        }
        
        // עדכון המטאדאטה
        const langEl = previewEl.querySelector('.lang-text');
        const sizeEl = previewEl.querySelector('.size-text');
        const linesEl = previewEl.querySelector('.lines-text');
        const dateEl = previewEl.querySelector('.date-text');
        
        if (langEl) langEl.textContent = file.programming_language || '-';
        if (sizeEl) sizeEl.textContent = formatFileSize(file.file_size || 0);
        if (linesEl) linesEl.textContent = `${file.lines_count || 0} שורות`;
        if (dateEl) dateEl.textContent = formatDate(file.updated_at);
        
        previewEl.classList.add('visible');
    }

    /**
     * עדכון מצב כפתור ההשוואה
     */
    function updateCompareButtonState() {
        if (!elements.compareBtn) return;
        
        const canCompare = state.leftFileId && state.rightFileId && 
                          state.leftFileId !== state.rightFileId;
        
        elements.compareBtn.disabled = !canCompare;
    }

    /**
     * הצגת תוצאות השוואה (מצב files)
     */
    function showComparisonResult() {
        elements.diffContainer?.classList.remove('d-none');
        elements.resultActions?.classList.remove('d-none');
        elements.viewModeToggle?.classList.remove('d-none');
    }

    /**
     * איפוס ההשוואה (מצב files)
     */
    function resetComparison() {
        state.diffData = null;
        state.leftFileId = null;
        state.rightFileId = null;
        
        if (elements.fileLeft) elements.fileLeft.value = '';
        if (elements.fileRight) elements.fileRight.value = '';
        
        elements.diffContainer?.classList.add('d-none');
        elements.resultActions?.classList.add('d-none');
        elements.statsBar?.classList.add('d-none');
        elements.viewModeToggle?.classList.add('d-none');
        
        elements.previewLeft?.classList.remove('visible');
        elements.previewRight?.classList.remove('visible');
        
        updateCompareButtonState();
    }

    /**
     * שינוי מצב תצוגה
     */
    function setViewMode(mode) {
        state.viewMode = mode;

        // עדכון כפתורים
        elements.modeButtons?.forEach(btn => {
            btn.classList.toggle('active', btn.dataset.mode === mode);
        });

        // הצגת התצוגה המתאימה
        elements.sideBySideView?.classList.toggle('active', mode === 'side-by-side');
        elements.unifiedView?.classList.toggle('active', mode === 'unified');
        elements.inlineView?.classList.toggle('active', mode === 'inline');

        renderDiff();
    }

    /**
     * מצב טעינה
     */
    function setLoading(isLoading) {
        state.isLoading = isLoading;
        
        if (elements.compareBtn) {
            elements.compareBtn.classList.toggle('loading', isLoading);
            elements.compareBtn.disabled = isLoading;
        }
    }

    // =================================================================
    // Actions
    // =================================================================
    
    /**
     * החלפת גרסאות
     */
    function swapVersions() {
        const temp = state.leftVersion;
        state.leftVersion = state.rightVersion;
        state.rightVersion = temp;

        if (elements.versionLeft) elements.versionLeft.value = state.leftVersion;
        if (elements.versionRight) elements.versionRight.value = state.rightVersion;

        loadDiff();
    }

    /**
     * החלפת קבצים
     */
    function swapFiles() {
        const temp = state.leftFileId;
        state.leftFileId = state.rightFileId;
        state.rightFileId = temp;

        if (elements.fileLeft) elements.fileLeft.value = state.leftFileId || '';
        if (elements.fileRight) elements.fileRight.value = state.rightFileId || '';

        updateFilePreview('left');
        updateFilePreview('right');
        
        if (state.diffData) {
            loadFilesDiff();
        }
    }

    /**
     * טיפול בשליחת טופס השוואה
     */
    function handleCompareSubmit(e) {
        e.preventDefault();
        
        if (!state.leftFileId || !state.rightFileId) return;
        if (state.leftFileId === state.rightFileId) {
            showError('יש לבחור שני קבצים שונים');
            return;
        }
        
        loadFilesDiff();
    }

    /**
     * סינון select לפי טקסט חיפוש
     */
    function filterSelect(side, searchText) {
        const selectEl = side === 'left' ? elements.fileLeft : elements.fileRight;
        if (!selectEl) return;
        
        const options = selectEl.querySelectorAll('option');
        const lowerSearch = searchText.toLowerCase();
        
        options.forEach(opt => {
            if (!opt.value) return; // skip placeholder
            
            const text = opt.textContent.toLowerCase();
            opt.style.display = text.includes(lowerSearch) ? '' : 'none';
        });
    }

    /**
     * סינון לפי שפת תכנות
     */
    function handleLanguageFilter(chip) {
        const filter = chip.dataset.filter;
        
        // עדכון מצב הכפתורים
        elements.filterChips?.forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        
        // סינון ה-selects
        [elements.fileLeft, elements.fileRight].forEach(selectEl => {
            if (!selectEl) return;
            
            selectEl.querySelectorAll('option').forEach(opt => {
                if (!opt.value) return;
                
                const lang = opt.dataset.language?.toLowerCase() || '';
                const show = filter === 'all' || lang === filter.toLowerCase();
                opt.style.display = show ? '' : 'none';
            });
        });
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
            // Fallback
            fallbackCopy(text);
        }
    }

    /**
     * יצירת טקסט diff בפורמט unified
     */
    function generateUnifiedDiffText() {
        const leftName = state.mode === 'versions' 
            ? `${state.fileName} (v${state.leftVersion})`
            : state.leftFileName || 'left';
        const rightName = state.mode === 'versions'
            ? `${state.fileName} (v${state.rightVersion})`
            : state.rightFileName || 'right';
            
        const lines = [`--- ${leftName}`, `+++ ${rightName}`];

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
     * Fallback להעתקה
     */
    function fallbackCopy(text) {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        
        try {
            document.execCommand('copy');
            showToast('ה-Diff הועתק ללוח!', 'success');
        } catch (e) {
            showToast('שגיאה בהעתקה', 'error');
        }
        
        document.body.removeChild(textarea);
    }

    /**
     * הורדת קובץ patch
     */
    function downloadPatch() {
        const text = generateUnifiedDiffText();
        const blob = new Blob([text], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        
        let filename;
        if (state.mode === 'versions') {
            filename = `${state.fileName}.v${state.leftVersion}-v${state.rightVersion}.patch`;
        } else {
            const leftSafe = (state.leftFileName || 'left').replace(/[^a-zA-Z0-9_.-]/g, '_');
            const rightSafe = (state.rightFileName || 'right').replace(/[^a-zA-Z0-9_.-]/g, '_');
            filename = `${leftSafe}-vs-${rightSafe}.patch`;
        }
        
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        
        showToast('הקובץ הורד בהצלחה', 'success');
    }

    /**
     * שחזור גרסה (מצב versions בלבד)
     */
    async function restoreVersion() {
        if (state.mode !== 'versions') return;
        
        const versionToRestore = state.leftVersion;
        
        if (elements.restoreVersionSpan) {
            elements.restoreVersionSpan.textContent = versionToRestore;
        }

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
            
            // סגירת המודל
            const modal = bootstrap.Modal.getInstance(document.getElementById('restoreModal'));
            modal?.hide();
            
            // רענון הדף אחרי שחזור
            setTimeout(() => window.location.reload(), 1500);

        } catch (error) {
            console.error('Restore failed:', error);
            showToast('שגיאה בשחזור הגרסה', 'error');
        }
    }

    // =================================================================
    // Utility Functions
    // =================================================================
    
    function escapeHtml(text) {
        if (text == null) return '';
        const div = document.createElement('div');
        div.textContent = String(text);
        return div.innerHTML;
    }

    function formatFileSize(bytes) {
        if (!bytes || bytes === 0) return '0 B';
        const units = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(1024));
        return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
    }

    function formatDate(dateStr) {
        if (!dateStr) return '-';
        try {
            const date = new Date(dateStr);
            return date.toLocaleDateString('he-IL', {
                day: '2-digit',
                month: '2-digit',
                year: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
            });
        } catch {
            return dateStr;
        }
    }

    function showError(message) {
        showToast(message, 'error');
    }

    function showToast(message, type = 'info') {
        // שימוש במערכת ה-toasts הקיימת אם יש
        if (window.Toast && typeof window.Toast.show === 'function') {
            window.Toast.show(message, type);
            return;
        }
        
        // Fallback - יצירת toast פשוט
        const toast = document.createElement('div');
        toast.className = `toast-notification toast-${type}`;
        toast.innerHTML = `
            <i class="fas fa-${type === 'success' ? 'check-circle' : type === 'error' ? 'exclamation-circle' : 'info-circle'}"></i>
            <span>${escapeHtml(message)}</span>
        `;
        toast.style.cssText = `
            position: fixed;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            padding: 12px 24px;
            background: ${type === 'success' ? '#28a745' : type === 'error' ? '#dc3545' : '#6366f1'};
            color: white;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            z-index: 9999;
            display: flex;
            align-items: center;
            gap: 8px;
            animation: slideUp 0.3s ease;
        `;
        
        document.body.appendChild(toast);
        
        setTimeout(() => {
            toast.style.animation = 'slideDown 0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }

    // =================================================================
    // Public API
    // =================================================================
    
    return {
        init,
        initFilesMode,
        setViewMode,
        swapVersions,
        swapFiles,
        loadDiff,
        loadFilesDiff,
        alignRowHeights, // חשיפה לשימוש חיצוני אם צריך
    };
})();

// CSS Animation for toasts
const style = document.createElement('style');
style.textContent = `
@keyframes slideUp {
    from { transform: translateX(-50%) translateY(100%); opacity: 0; }
    to { transform: translateX(-50%) translateY(0); opacity: 1; }
}
@keyframes slideDown {
    from { transform: translateX(-50%) translateY(0); opacity: 1; }
    to { transform: translateX(-50%) translateY(100%); opacity: 0; }
}
`;
document.head.appendChild(style);
