/**
 * FileCompareView
 * ---------------
 * מודול קטן לשימוש חוזר בין מסך השוואת גרסאות ומסך השוואת קבצים.
 */

(function () {
    const state = {
        mode: 'versions',
        fileId: null,
        fileName: '',
        leftVersion: null,
        rightVersion: null,
        leftFileId: null,
        rightFileId: null,
        viewMode: 'side-by-side',
        diffData: null,
        loading: false,
        preload: false,
    };

    const elements = {};

    function init(config) {
        Object.assign(state, config || {});
        state.viewMode = state.viewMode || 'side-by-side';
        cacheElements();
        bindEvents();

        if (state.mode === 'versions' && state.fileId) {
            loadVersionsDiff();
        } else if (state.mode === 'files' && state.leftFileId && state.rightFileId) {
            loadFilesDiff();
        } else {
            togglePlaceholder(true);
        }
    }

    function cacheElements() {
        elements.versionLeft = document.getElementById('version-left');
        elements.versionRight = document.getElementById('version-right');
        elements.swapVersions = document.getElementById('swap-versions');

        elements.fileLeft = document.getElementById('file-left');
        elements.fileRight = document.getElementById('file-right');
        elements.swapFiles = document.getElementById('swap-files');
        elements.compareButton = document.getElementById('load-files-diff');

        elements.viewButtons = document.querySelectorAll('[data-view-mode]');
        elements.leftMeta = document.getElementById('diff-left-meta');
        elements.rightMeta = document.getElementById('diff-right-meta');
        elements.statAdded = document.getElementById('stat-added');
        elements.statRemoved = document.getElementById('stat-removed');
        elements.statModified = document.getElementById('stat-modified');
        elements.statUnchanged = document.getElementById('stat-unchanged');
        elements.errorBox = document.getElementById('diff-error');
        elements.loadingBox = document.getElementById('diff-loading');
        elements.placeholder = document.getElementById('diff-placeholder');
        elements.viewsWrapper = document.getElementById('diff-views');
        elements.sideBySide = document.getElementById('diff-side-by-side');
        elements.unified = document.getElementById('diff-unified');
        elements.leftColumn = document.getElementById('diff-left');
        elements.rightColumn = document.getElementById('diff-right');
        elements.unifiedContent = document.getElementById('diff-unified-content');
    }

    function bindEvents() {
        if (elements.versionLeft) {
            elements.versionLeft.addEventListener('change', () => {
                state.leftVersion = parseInt(elements.versionLeft.value, 10);
                loadVersionsDiff();
            });
        }
        if (elements.versionRight) {
            elements.versionRight.addEventListener('change', () => {
                state.rightVersion = parseInt(elements.versionRight.value, 10);
                loadVersionsDiff();
            });
        }
        if (elements.swapVersions) {
            elements.swapVersions.addEventListener('click', () => {
                const temp = elements.versionLeft.value;
                elements.versionLeft.value = elements.versionRight.value;
                elements.versionRight.value = temp;
                state.leftVersion = parseInt(elements.versionLeft.value, 10);
                state.rightVersion = parseInt(elements.versionRight.value, 10);
                loadVersionsDiff();
            });
        }

        if (elements.swapFiles) {
            elements.swapFiles.addEventListener('click', () => {
                const temp = elements.fileLeft.value;
                elements.fileLeft.value = elements.fileRight.value;
                elements.fileRight.value = temp;
            });
        }

        if (elements.compareButton) {
            elements.compareButton.addEventListener('click', () => {
                state.leftFileId = elements.fileLeft.value;
                state.rightFileId = elements.fileRight.value;
                loadFilesDiff();
            });
        }

        if (elements.viewButtons) {
            elements.viewButtons.forEach((button) => {
                button.addEventListener('click', () => {
                    const mode = button.getAttribute('data-view-mode');
                    if (!mode || mode === state.viewMode) {
                        return;
                    }
                    state.viewMode = mode;
                    updateViewModeButtons();
                });
            });
        }
    }

    function updateViewModeButtons() {
        if (!elements.viewButtons) {
            return;
        }
        elements.viewButtons.forEach((button) => {
            const mode = button.getAttribute('data-view-mode');
            button.classList.toggle('active', mode === state.viewMode);
        });
        if (elements.sideBySide && elements.unified) {
            elements.sideBySide.classList.toggle('active', state.viewMode === 'side-by-side');
            elements.unified.classList.toggle('active', state.viewMode === 'unified');
        }
    }

    async function loadVersionsDiff() {
        if (!state.fileId || !state.leftVersion || !state.rightVersion) {
            return;
        }
        setLoading(true);
        clearError();
        try {
            const url = `/api/compare/versions/${state.fileId}?left=${state.leftVersion}&right=${state.rightVersion}`;
            const response = await fetch(url, { headers: { 'Accept': 'application/json' } });
            if (!response.ok) {
                throw new Error('שגיאה בטעינת הנתונים');
            }
            state.diffData = await response.json();
            renderDiff();
        } catch (err) {
            showError('לא ניתן לטעון את ההשוואה כרגע.');
            console.error(err);
        } finally {
            setLoading(false);
        }
    }

    async function loadFilesDiff() {
        if (!state.leftFileId || !state.rightFileId) {
            showError('בחרו קובץ מקור וקובץ יעד.');
            return;
        }
        setLoading(true);
        clearError();
        try {
            const response = await fetch('/api/compare/files', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    left_file_id: state.leftFileId,
                    right_file_id: state.rightFileId,
                }),
            });
            if (!response.ok) {
                throw new Error('diff_failed');
            }
            state.diffData = await response.json();
            renderDiff();
        } catch (err) {
            showError('לא הצלחנו לחשב את ההבדלים. נסו שנית.');
            console.error(err);
        } finally {
            setLoading(false);
        }
    }

    function renderDiff() {
        if (!state.diffData || !Array.isArray(state.diffData.lines)) {
            togglePlaceholder(true);
            return;
        }
        togglePlaceholder(false);
        updateViewModeButtons();
        renderSideBySide();
        renderUnified();
        updateStats();
        updateMeta();
    }

    function renderSideBySide() {
        if (!elements.leftColumn || !elements.rightColumn) {
            return;
        }
        const leftLines = [];
        const rightLines = [];

        state.diffData.lines.forEach((line) => {
            leftLines.push(buildLine(line.line_num_left, line.content_left, deriveClass(line.change_type, 'left')));
            rightLines.push(buildLine(line.line_num_right, line.content_right, deriveClass(line.change_type, 'right')));
        });

        elements.leftColumn.innerHTML = leftLines.join('');
        elements.rightColumn.innerHTML = rightLines.join('');
    }

    function renderUnified() {
        if (!elements.unifiedContent) {
            return;
        }
        const rows = state.diffData.lines.map((line) => {
            const numbers = [
                line.line_num_left != null ? line.line_num_left : '',
                line.line_num_right != null ? line.line_num_right : '',
            ];
            const content = line.content_right ?? line.content_left ?? '';
            return `
                <div class="diff-line ${line.change_type}">
                    <div class="line-number">${numbers.map(escapeHtml).join(' | ')}</div>
                    <div class="line-content">${escapeHtml(content)}</div>
                </div>
            `;
        });
        elements.unifiedContent.innerHTML = rows.join('');
    }

    function updateStats() {
        const stats = state.diffData.stats || {};
        if (elements.statAdded) elements.statAdded.textContent = stats.added ?? 0;
        if (elements.statRemoved) elements.statRemoved.textContent = stats.removed ?? 0;
        if (elements.statModified) elements.statModified.textContent = stats.modified ?? 0;
        if (elements.statUnchanged) elements.statUnchanged.textContent = stats.unchanged ?? 0;
    }

    function updateMeta() {
        const leftInfo = state.diffData.left_info || {};
        const rightInfo = state.diffData.right_info || {};
        if (elements.leftMeta) elements.leftMeta.textContent = buildMetaLabel(leftInfo);
        if (elements.rightMeta) elements.rightMeta.textContent = buildMetaLabel(rightInfo);
    }

    function buildMetaLabel(info) {
        const parts = [];
        if (info.file_name) {
            parts.push(info.file_name);
        }
        if (info.version) {
            parts.push(`גרסה ${info.version}`);
        }
        if (info.updated_at) {
            parts.push(info.updated_at);
        }
        return parts.join(' · ') || '—';
    }

    function buildLine(lineNumber, content, cssClass) {
        const number = lineNumber != null ? lineNumber : '';
        const text = content != null ? content : '';
        return `
            <div class="diff-line ${cssClass}">
                <div class="line-number">${escapeHtml(number)}</div>
                <div class="line-content">${escapeHtml(text)}</div>
            </div>
        `;
    }

    function deriveClass(changeType, side) {
        if (changeType === 'added') {
            return side === 'left' ? 'empty' : 'added';
        }
        if (changeType === 'removed') {
            return side === 'right' ? 'empty' : 'removed';
        }
        if (changeType === 'modified') {
            return 'modified';
        }
        return 'unchanged';
    }

    function setLoading(isLoading) {
        state.loading = isLoading;
        if (elements.loadingBox) {
            elements.loadingBox.classList.toggle('d-none', !isLoading);
        }
    }

    function togglePlaceholder(show) {
        if (elements.placeholder) {
            elements.placeholder.classList.toggle('d-none', !show);
        }
        if (elements.viewsWrapper) {
            elements.viewsWrapper.classList.toggle('d-none', show);
        }
    }

    function showError(message) {
        if (!elements.errorBox) {
            return;
        }
        elements.errorBox.textContent = message;
        elements.errorBox.classList.remove('d-none');
    }

    function clearError() {
        if (elements.errorBox) {
            elements.errorBox.classList.add('d-none');
            elements.errorBox.textContent = '';
        }
    }

    function escapeHtml(value) {
        if (value === null || value === undefined) {
            return '';
        }
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    window.FileCompareView = { init };
})();
