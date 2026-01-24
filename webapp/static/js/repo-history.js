// webapp/static/js/repo-history.js

/**
 * מודול להיסטוריית Git ותצוגת Diff
 *
 * תיקונים מרכזיים:
 * 1. encodeURIComponent לא משמש על paths - במקום זה file מועבר כ-query param
 * 2. addEventListener במקום inline onclick
 * 3. תמיכה ב-Compare Mode (בחירת 2 commits)
 */
const RepoHistory = (function() {
    'use strict';

    // State
    const state = {
        currentFile: null,
        commits: [],
        isLoading: false,
        hasMore: true,
        skip: 0,
        limit: 20,
        // Compare mode
        compareMode: false,
        compareBase: null,    // commit ישן (אדום)
        compareTarget: null,  // commit חדש (ירוק)
        // Diff view mode
        diffViewMode: 'basic',  // 'basic' | 'advanced'
        mergeViewInstance: null,  // CodeMirror MergeView instance
        lastDiffData: null  // שמירת נתוני ה-diff האחרונים למעבר בין תצוגות
    };

    // DOM Elements
    let historyPanel = null;
    let diffModal = null;
    let overlay = null;

    // ============================================
    // Utility Functions
    // ============================================

    function escapeHtml(text) {
        if (!text) return '';
        return String(text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function getFileName(path) {
        return path ? path.split('/').pop() : '';
    }

    function truncate(text, maxLength) {
        if (!text || text.length <= maxLength) return text;
        return text.substring(0, maxLength) + '...';
    }

    function formatRelativeDate(timestamp) {
        if (!timestamp) return '';
        const now = Date.now() / 1000;
        const diff = now - timestamp;

        if (diff < 60) return 'הרגע';
        if (diff < 3600) return `לפני ${Math.floor(diff / 60)} דקות`;
        if (diff < 86400) return `לפני ${Math.floor(diff / 3600)} שעות`;
        if (diff < 604800) return `לפני ${Math.floor(diff / 86400)} ימים`;
        if (diff < 2592000) return `לפני ${Math.floor(diff / 604800)} שבועות`;
        if (diff < 31536000) return `לפני ${Math.floor(diff / 2592000)} חודשים`;
        return `לפני ${Math.floor(diff / 31536000)} שנים`;
    }

    function formatFullDate(timestamp) {
        if (!timestamp) return '';
        return new Date(timestamp * 1000).toLocaleString('he-IL', {
            year: 'numeric',
            month: 'long',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    }

    /**
     * בניית URL עם file כ-query parameter
     * פותר את בעיית ה-encodeURIComponent עם slashes
     */
    function buildApiUrl(endpoint, params = {}) {
        const url = new URL(endpoint, window.location.origin);
        Object.entries(params).forEach(([key, value]) => {
            if (value !== undefined && value !== null) {
                url.searchParams.set(key, value);
            }
        });
        return url.toString();
    }

    function showToast(message, type = 'error', duration = 5000) {
        const toast = document.createElement('div');
        toast.className = type === 'error' ? 'error-toast' : 'success-toast';
        toast.innerHTML = `
            <i class="bi bi-${type === 'error' ? 'exclamation-triangle' : 'check-circle'}"></i>
            <span>${escapeHtml(message)}</span>
        `;
        document.body.appendChild(toast);

        setTimeout(() => {
            toast.classList.add('fade-out');
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }

    async function copyToClipboard(text) {
        try {
            await navigator.clipboard.writeText(text);
            showToast('הועתק ללוח', 'success', 2000);
        } catch (err) {
            showToast('שגיאה בהעתקה', 'error');
        }
    }

    // ============================================
    // Initialization
    // ============================================

    function init() {
        createHistoryPanel();
        createDiffModal();
        createOverlay();
        bindGlobalEvents();
    }

    function createHistoryPanel() {
        historyPanel = document.createElement('div');
        historyPanel.className = 'history-panel';
        historyPanel.innerHTML = `
            <div class="history-panel-header">
                <h3>
                    <i class="bi bi-clock-history"></i>
                    <span class="history-title-text">היסטוריית קובץ</span>
                </h3>
                <button class="history-panel-close" aria-label="סגור">
                    <i class="bi bi-x-lg"></i>
                </button>
            </div>
            <div class="compare-mode-banner" style="display: none;">
                <span class="instructions">בחר שני commits להשוואה</span>
                <div class="selection">
                    <span class="commit-badge base">-</span>
                    <i class="bi bi-arrow-left"></i>
                    <span class="commit-badge target">-</span>
                </div>
                <button class="compare-execute-btn" disabled>השווה</button>
                <button class="compare-cancel-btn">ביטול</button>
            </div>
            <div class="history-commits"></div>
        `;
        document.body.appendChild(historyPanel);

        // Event listeners - NO inline onclick
        historyPanel.querySelector('.history-panel-close')
            .addEventListener('click', closeHistoryPanel);

        historyPanel.querySelector('.compare-execute-btn')
            .addEventListener('click', executeCompare);

        historyPanel.querySelector('.compare-cancel-btn')
            .addEventListener('click', cancelCompareMode);
    }

    function createDiffModal() {
        diffModal = document.createElement('div');
        diffModal.className = 'diff-modal';
        diffModal.innerHTML = `
            <div class="diff-modal-content">
                <div class="diff-modal-header">
                    <div class="diff-modal-title">
                        <h3>
                            <i class="bi bi-file-diff"></i>
                            השוואת שינויים
                        </h3>
                        <div class="diff-commits-info">
                            <div class="commit-info old">
                                <span class="commit-badge old"></span>
                                <span class="commit-message-preview"></span>
                            </div>
                            <span class="arrow">→</span>
                            <div class="commit-info new">
                                <span class="commit-badge new"></span>
                                <span class="commit-message-preview"></span>
                            </div>
                        </div>
                    </div>
                    <div class="diff-view-toggle">
                        <button class="diff-view-btn active" data-view="basic" title="תצוגה בסיסית">
                            <i class="bi bi-file-diff"></i>
                        </button>
                        <button class="diff-view-btn" data-view="advanced" title="תצוגה מתקדמת">
                            <i class="bi bi-code-square"></i>
                        </button>
                    </div>
                    <button class="diff-modal-close" aria-label="סגור">
                        <i class="bi bi-x-lg"></i>
                    </button>
                </div>
                <div class="diff-stats"></div>
                <div class="diff-content"></div>
                <div class="diff-advanced-content" style="display: none;"></div>
            </div>
        `;
        document.body.appendChild(diffModal);

        // Event listeners
        diffModal.querySelector('.diff-modal-close')
            .addEventListener('click', closeDiffModal);

        diffModal.addEventListener('click', (e) => {
            if (e.target === diffModal) closeDiffModal();
        });

        // Toggle view buttons
        diffModal.querySelectorAll('.diff-view-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const view = btn.dataset.view;
                if (view === state.diffViewMode) return;
                switchDiffView(view);
            });
        });
    }

    function createOverlay() {
        overlay = document.createElement('div');
        overlay.className = 'panel-overlay';
        overlay.addEventListener('click', closeHistoryPanel);
        document.body.appendChild(overlay);
    }

    function bindGlobalEvents() {
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                if (diffModal.classList.contains('open')) {
                    closeDiffModal();
                } else if (historyPanel.classList.contains('open')) {
                    closeHistoryPanel();
                }
            }
        });
    }

    // ============================================
    // History Panel
    // ============================================

    async function openHistoryPanel(filePath) {
        state.currentFile = filePath;
        state.commits = [];
        state.skip = 0;
        state.hasMore = true;
        state.isLoading = false;  // חשוב! מאפשר טעינה מחדש
        state.compareMode = false;
        state.compareBase = null;
        state.compareTarget = null;

        historyPanel.classList.add('open');
        overlay.classList.add('visible');

        // Update title
        const titleText = historyPanel.querySelector('.history-title-text');
        titleText.textContent = `היסטוריית: ${getFileName(filePath)}`;
        titleText.title = filePath;

        // Hide compare banner
        historyPanel.querySelector('.compare-mode-banner').style.display = 'none';

        await loadHistory();
    }

    function closeHistoryPanel() {
        historyPanel.classList.remove('open');
        overlay.classList.remove('visible');
        cancelCompareMode();
    }

    async function loadHistory(append = false) {
        if (state.isLoading) return;
        state.isLoading = true;

        const container = historyPanel.querySelector('.history-commits');
        // שמירת הקובץ הנוכחי לבדיקת race condition
        const requestedFile = state.currentFile;

        if (!append) {
            container.innerHTML = `
                <div class="history-loading">
                    <div class="spinner"></div>
                    <span>טוען היסטוריה...</span>
                </div>
            `;
        }

        try {
            // בניית URL עם file כ-query param
            const url = buildApiUrl('/repo/api/history', {
                file: requestedFile,
                limit: state.limit,
                skip: state.skip
            });

            const response = await fetch(url);

            // בדיקת race condition: האם המשתמש עבר לקובץ אחר?
            if (state.currentFile !== requestedFile) {
                console.log('Race condition avoided: user switched to different file');
                return;  // התעלם מהתגובה - כבר לא רלוונטית
            }

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.message || `HTTP ${response.status}`);
            }

            const data = await response.json();

            // בדיקת race condition נוספת אחרי parse
            if (state.currentFile !== requestedFile) {
                console.log('Race condition avoided: user switched to different file');
                return;
            }

            if (!data.success) {
                throw new Error(data.message || 'שגיאה בטעינת היסטוריה');
            }

            // שמירת מספר ה-commits הקודם לפני הוספה
            const previousCount = state.commits.length;
            state.commits = append ? [...state.commits, ...data.commits] : data.commits;
            state.hasMore = data.has_more;
            state.skip += data.commits.length;

            renderCommits(container, append, previousCount);

        } catch (error) {
            console.error('Error loading history:', error);

            if (append) {
                // במצב append - לא למחוק commits קיימים, רק להציג toast
                showToast(error.message, 'error');

                // הסרת כפתור "טען עוד" הקודם והוספת כפתור retry
                const loadMoreBtn = container.querySelector('.history-load-more');
                if (loadMoreBtn) loadMoreBtn.remove();

                const retryBtn = document.createElement('button');
                retryBtn.className = 'history-load-more error';
                retryBtn.innerHTML = `
                    <i class="bi bi-arrow-clockwise"></i>
                    נסה שוב לטעון
                `;
                retryBtn.addEventListener('click', () => loadHistory(true));
                container.appendChild(retryBtn);
            } else {
                // טעינה ראשונית - הצג שגיאה מלאה
                container.innerHTML = `
                    <div class="history-error">
                        <i class="bi bi-exclamation-triangle"></i>
                        <p>${escapeHtml(error.message)}</p>
                        <button class="retry-btn">נסה שוב</button>
                    </div>
                `;
                container.querySelector('.retry-btn')
                    .addEventListener('click', () => loadHistory());
            }
        } finally {
            // אפס isLoading רק אם זה עדיין אותו קובץ
            // (אם המשתמש עבר לקובץ אחר, openHistoryPanel כבר איפס)
            if (state.currentFile === requestedFile) {
                state.isLoading = false;
            }
        }
    }

    function renderCommits(container, append = false, previousCount = 0) {
        if (!append) {
            container.innerHTML = '';
        } else {
            const loadMoreBtn = container.querySelector('.history-load-more');
            if (loadMoreBtn) loadMoreBtn.remove();
        }

        // כשמוסיפים - רנדר רק את ה-commits החדשים (מ-previousCount והלאה)
        const startIndex = append ? previousCount : 0;
        const commitsToRender = state.commits.slice(startIndex);

        commitsToRender.forEach((commit, index) => {
            const globalIndex = startIndex + index;
            const commitEl = createCommitElement(commit, globalIndex, state.commits.length);
            container.appendChild(commitEl);
        });

        if (append) {
            ensurePrevButtonForIndex(previousCount - 1);
        }

        // Add load more button
        if (state.hasMore) {
            const loadMoreBtn = document.createElement('button');
            loadMoreBtn.className = 'history-load-more';
            loadMoreBtn.innerHTML = `
                <i class="bi bi-arrow-down-circle"></i>
                טען עוד commits
            `;
            loadMoreBtn.addEventListener('click', () => loadHistory(true));
            container.appendChild(loadMoreBtn);
        }
    }

    function ensurePrevButtonForIndex(index) {
        if (index < 0 || index >= state.commits.length - 1) return;
        const commitEl = historyPanel.querySelector(`.history-commit[data-index="${index}"]`);
        if (!commitEl) return;
        if (commitEl.querySelector('.diff-prev-btn')) return;

        const actions = commitEl.querySelector('.commit-actions');
        if (!actions) return;

        const button = document.createElement('button');
        button.className = 'commit-action-btn diff-prev-btn';
        button.title = 'השווה ל-commit הקודם';
        button.innerHTML = `
            <i class="bi bi-arrow-left-right"></i>
            VS קודם
        `;
        button.addEventListener('click', (e) => {
            e.stopPropagation();
            const prevCommit = state.commits[index + 1];
            if (prevCommit) {
                const currentCommit = state.commits[index];
                showDiff(prevCommit.hash, currentCommit.hash, prevCommit.message, currentCommit.message);
            }
        });

        const compareBtn = actions.querySelector('.compare-select-btn');
        if (compareBtn) {
            actions.insertBefore(button, compareBtn);
        } else {
            actions.appendChild(button);
        }
    }

    function createCommitElement(commit, index, totalCommits) {
        const el = document.createElement('div');
        el.className = 'history-commit';
        const hasParent = index < totalCommits - 1;  // יש commit ישן יותר במערך
        el.dataset.hash = commit.hash;
        el.dataset.index = index;

        const relativeDate = formatRelativeDate(commit.timestamp);
        const fullDate = formatFullDate(commit.timestamp);

        el.innerHTML = `
            <div class="commit-header">
                <span class="commit-hash" title="לחץ להעתקה">${escapeHtml(commit.short_hash)}</span>
                <span class="commit-date" title="${fullDate}">${relativeDate}</span>
            </div>
            <div class="commit-message">${escapeHtml(commit.message)}</div>
            <div class="commit-author">
                <i class="bi bi-person-circle"></i>
                ${escapeHtml(commit.author)}
            </div>
            <div class="commit-actions">
                <button class="commit-action-btn view-btn" title="צפה בגרסה זו">
                    <i class="bi bi-eye"></i>
                    צפה
                </button>
                <button class="commit-action-btn diff-head-btn" title="השווה לגרסה הנוכחית">
                    <i class="bi bi-file-diff"></i>
                    VS HEAD
                </button>
                ${hasParent ? `
                    <button class="commit-action-btn diff-prev-btn" title="השווה ל-commit הקודם">
                        <i class="bi bi-arrow-left-right"></i>
                        VS קודם
                    </button>
                ` : ''}
                <button class="commit-action-btn compare-select-btn" title="בחר להשוואה">
                    <i class="bi bi-ui-checks"></i>
                    השווה...
                </button>
            </div>
        `;

        // Event listeners - NO inline onclick
        el.querySelector('.commit-hash').addEventListener('click', (e) => {
            e.stopPropagation();
            copyToClipboard(commit.hash);
        });

        el.querySelector('.view-btn').addEventListener('click', (e) => {
            e.stopPropagation();
            viewFileAtCommit(commit.hash);
        });

        el.querySelector('.diff-head-btn').addEventListener('click', (e) => {
            e.stopPropagation();
            showDiff(commit.hash, 'HEAD', commit.message, 'HEAD');
        });

        const diffPrevBtn = el.querySelector('.diff-prev-btn');
        if (diffPrevBtn) {
            diffPrevBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                const prevCommit = state.commits[index + 1];
                if (prevCommit) {
                    showDiff(prevCommit.hash, commit.hash, prevCommit.message, commit.message);
                }
            });
        }

        el.querySelector('.compare-select-btn').addEventListener('click', (e) => {
            e.stopPropagation();
            selectForCompare(commit, el);
        });

        return el;
    }

    // ============================================
    // Compare Mode
    // ============================================

    function selectForCompare(commit, element) {
        if (!state.compareMode) {
            // First selection - enter compare mode
            state.compareMode = true;
            state.compareBase = commit;
            element.classList.add('compare-selected-base');

            const banner = historyPanel.querySelector('.compare-mode-banner');
            banner.style.display = 'flex';
            banner.querySelector('.commit-badge.base').textContent = commit.short_hash;
            banner.querySelector('.commit-badge.target').textContent = '-';
            banner.querySelector('.compare-execute-btn').disabled = true;

        } else if (!state.compareTarget && commit.hash !== state.compareBase.hash) {
            // Second selection
            state.compareTarget = commit;
            element.classList.add('compare-selected-target');

            const banner = historyPanel.querySelector('.compare-mode-banner');
            banner.querySelector('.commit-badge.target').textContent = commit.short_hash;
            banner.querySelector('.compare-execute-btn').disabled = false;
        }
    }

    function cancelCompareMode() {
        state.compareMode = false;
        state.compareBase = null;
        state.compareTarget = null;

        historyPanel.querySelector('.compare-mode-banner').style.display = 'none';
        historyPanel.querySelectorAll('.compare-selected-base, .compare-selected-target')
            .forEach(el => el.classList.remove('compare-selected-base', 'compare-selected-target'));
    }

    function executeCompare() {
        if (state.compareBase && state.compareTarget) {
            // Determine order: older commit first
            const baseTime = state.compareBase.timestamp;
            const targetTime = state.compareTarget.timestamp;

            const [older, newer] = baseTime < targetTime
                ? [state.compareBase, state.compareTarget]
                : [state.compareTarget, state.compareBase];

            showDiff(older.hash, newer.hash, older.message, newer.message);
            cancelCompareMode();
        }
    }

    // ============================================
    // File Viewer at Commit
    // ============================================

    async function viewFileAtCommit(commit) {
        try {
            const url = buildApiUrl(`/repo/api/file-at-commit/${encodeURIComponent(commit)}`, {
                file: state.currentFile
            });

            const response = await fetch(url);
            const data = await response.json();

            if (!data.success) {
                throw new Error(data.message || 'שגיאה בטעינת קובץ');
            }

            if (data.is_binary) {
                showToast('זהו קובץ בינארי שלא ניתן להציג', 'error');
                return;
            }

            // Update editor content
            if (window.RepoState && window.RepoState.editor) {
                window.RepoState.editor.setValue(data.content);
            }

            // Update file info
            const fileHeader = document.querySelector('.file-header .file-info');
            if (fileHeader) {
                const shortHash = commit.substring(0, 7);
                const safeShortHash = escapeHtml(shortHash);

                // Add version indicator
                const versionBadge = document.createElement('span');
                versionBadge.className = 'version-badge';
                versionBadge.innerHTML = `
                    <span class="badge">@ ${safeShortHash}</span>
                    <button class="back-to-head-btn">חזור ל-HEAD</button>
                `;

                const existingBadge = fileHeader.querySelector('.version-badge');
                if (existingBadge) existingBadge.remove();
                fileHeader.appendChild(versionBadge);

                versionBadge.querySelector('.back-to-head-btn')
                    .addEventListener('click', backToHead);
            }

        } catch (error) {
            console.error('Error viewing file at commit:', error);
            showToast(error.message, 'error');
        }
    }

    function backToHead() {
        if (!state.currentFile) return;

        // וידוא שניתן לטעון את הקובץ לפני הסרת ה-badge
        if (!window.selectFile) {
            showToast('לא ניתן לטעון מחדש - רענן את הדף', 'error');
            return;
        }

        // הסרת badge וטעינה מחדש - רק אם שניהם אפשריים
        const badge = document.querySelector('.version-badge');
        if (badge) badge.remove();

        window.selectFile(state.currentFile);
    }

    // ============================================
    // Diff Modal
    // ============================================

    async function showDiff(commit1, commit2, message1 = '', message2 = '') {
        diffModal.classList.add('open');

        const content = diffModal.querySelector('.diff-content');
        const advancedContent = diffModal.querySelector('.diff-advanced-content');
        const stats = diffModal.querySelector('.diff-stats');
        const commitsInfo = diffModal.querySelector('.diff-commits-info');

        // Update header
        const shortHash1 = commit1.substring(0, 7);
        const shortHash2 = commit2 === 'HEAD' ? 'HEAD' : commit2.substring(0, 7);

        commitsInfo.querySelector('.commit-badge.old').textContent = shortHash1;
        commitsInfo.querySelector('.commit-badge.new').textContent = shortHash2;
        commitsInfo.querySelector('.commit-info.old .commit-message-preview').textContent =
            truncate(message1, 40);
        commitsInfo.querySelector('.commit-info.new .commit-message-preview').textContent =
            truncate(message2, 40);

        // איפוס תצוגה
        content.style.display = state.diffViewMode === 'basic' ? '' : 'none';
        advancedContent.style.display = state.diffViewMode === 'advanced' ? '' : 'none';

        content.innerHTML = `
            <div class="diff-loading">
                <div class="spinner"></div>
                <span>טוען השוואה...</span>
            </div>
        `;
        if (state.diffViewMode === 'advanced') {
            advancedContent.innerHTML = `
                <div class="diff-loading">
                    <div class="spinner"></div>
                    <span>טוען השוואה...</span>
                </div>
            `;
        }
        stats.innerHTML = '';

        try {
            // טעינת diff + תוכן הקבצים במקביל
            const [diffResponse, oldContentResponse, newContentResponse] = await Promise.all([
                fetch(buildApiUrl(`/repo/api/diff/${encodeURIComponent(commit1)}/${encodeURIComponent(commit2)}`, {
                    file: state.currentFile,
                    format: 'both'
                })),
                fetch(buildApiUrl(`/repo/api/file-at-commit/${encodeURIComponent(commit1)}`, {
                    file: state.currentFile
                })),
                commit2 === 'HEAD' 
                    ? fetch(buildApiUrl(`/repo/api/file-at-commit/HEAD`, { file: state.currentFile }))
                    : fetch(buildApiUrl(`/repo/api/file-at-commit/${encodeURIComponent(commit2)}`, { file: state.currentFile }))
            ]);

            const data = await diffResponse.json();
            const oldData = await oldContentResponse.json();
            const newData = await newContentResponse.json();

            if (!data.success) {
                throw new Error(data.message || 'שגיאה בטעינת diff');
            }

            // שמירת נתונים ל-state עבור מעבר בין תצוגות
            state.lastDiffData = {
                parsed: data.parsed,
                stats: data.stats,
                is_truncated: data.is_truncated,
                old_content: oldData.success && !oldData.is_binary ? oldData.content : '',
                new_content: newData.success && !newData.is_binary ? newData.content : ''
            };

            renderDiffStats(stats, data.stats, data.is_truncated);
            renderDiff(content, data.parsed);

            // אם במצב מתקדם - יצירת MergeView
            if (state.diffViewMode === 'advanced') {
                createMergeView(state.lastDiffData);
            }

        } catch (error) {
            console.error('Error loading diff:', error);
            content.innerHTML = `
                <div class="diff-error">
                    <i class="bi bi-exclamation-triangle"></i>
                    <p>${escapeHtml(error.message)}</p>
                </div>
            `;
            if (state.diffViewMode === 'advanced') {
                advancedContent.innerHTML = `
                    <div class="diff-error">
                        <i class="bi bi-exclamation-triangle"></i>
                        <p>${escapeHtml(error.message)}</p>
                    </div>
                `;
            }
        }
    }

    function closeDiffModal() {
        diffModal.classList.remove('open');
        destroyMergeView();
        // איפוס state
        state.diffViewMode = 'basic';
        state.lastDiffData = null;
        // איפוס כפתורי Toggle
        const buttons = diffModal.querySelectorAll('.diff-view-btn');
        buttons.forEach(btn => {
            btn.classList.toggle('active', btn.dataset.view === 'basic');
        });
        // הצגת תצוגה בסיסית, הסתרת מתקדמת
        const basicContent = diffModal.querySelector('.diff-content');
        const advancedContent = diffModal.querySelector('.diff-advanced-content');
        if (basicContent) basicContent.style.display = '';
        if (advancedContent) advancedContent.style.display = 'none';
    }

    /**
     * מעבר בין תצוגה בסיסית למתקדמת
     */
    function switchDiffView(view) {
        if (view === state.diffViewMode) return;
        state.diffViewMode = view;

        // עדכון כפתורים
        const buttons = diffModal.querySelectorAll('.diff-view-btn');
        buttons.forEach(btn => {
            btn.classList.toggle('active', btn.dataset.view === view);
        });

        const basicContent = diffModal.querySelector('.diff-content');
        const advancedContent = diffModal.querySelector('.diff-advanced-content');

        if (view === 'advanced') {
            // מעבר לתצוגה מתקדמת
            basicContent.style.display = 'none';
            advancedContent.style.display = '';
            
            if (state.lastDiffData) {
                createMergeView(state.lastDiffData);
            } else {
                // אם אין נתונים (למשל אחרי שגיאת API) - הצג הודעה
                showAdvancedFallback('אין נתונים להצגה. נסה לרענן את ההשוואה.');
            }
        } else {
            // מעבר לתצוגה בסיסית
            destroyMergeView();
            advancedContent.style.display = 'none';
            basicContent.style.display = '';
        }
    }

    /**
     * יצירת CodeMirror MergeView
     */
    function createMergeView(diffData) {
        const CM = window.CodeMirror6;
        if (!CM || !CM.MergeView) {
            console.warn('CodeMirror MergeView not available');
            showAdvancedFallback('CodeMirror MergeView לא זמין');
            return;
        }

        destroyMergeView();

        const container = diffModal.querySelector('.diff-advanced-content');
        if (!container) return;

        // ניקוי הקונטיינר
        container.innerHTML = '';

        // בדיקה אם יש תוכן להשוואה
        if (!diffData.old_content && !diffData.new_content) {
            showAdvancedFallback('אין תוכן טקסטואלי להשוואה');
            return;
        }

        try {
            // בדיקת רוחב מסך - במובייל נציג Unified (שורה אחת מתחת לשנייה)
            const isMobile = window.innerWidth < 768;
            
            // יצירת theme extensions
            const themeExtensions = [];
            const htmlTheme = document.documentElement.getAttribute('data-theme');
            if (htmlTheme === 'dark' || htmlTheme === 'dim') {
                const darkTheme = CM.getTheme ? CM.getTheme('dark') : [];
                if (darkTheme && darkTheme.length) themeExtensions.push(...darkTheme);
            }

            // הגדרת שפה לפי סיומת הקובץ
            const langSupport = getLanguageSupportForFile(state.currentFile);
            if (langSupport) themeExtensions.push(langSupport);

            // יצירת MergeView עם basicSetup (מספרי שורות, bracket matching וכו')
            const editorExtensions = [
                ...(CM.basicSetup || []),
                CM.EditorView.editable.of(false),
                CM.EditorState.readOnly.of(true),
                ...themeExtensions
            ];

            state.mergeViewInstance = new CM.MergeView({
                parent: container,
                a: {
                    doc: diffData.old_content || '',
                    extensions: editorExtensions
                },
                b: {
                    doc: diffData.new_content || '',
                    extensions: [...editorExtensions]  // clone לכל צד
                },
                orientation: isMobile ? 'a-b' : 'a-b',  // תמיד side-by-side, CSS ידאג למובייל
                revertControls: null,  // ללא כפתורי revert
                highlightChanges: true,
                gutter: true
            });

            // הוספת class למובייל
            if (isMobile) {
                container.classList.add('merge-view-mobile');
            } else {
                container.classList.remove('merge-view-mobile');
            }

            // האזנה לשינוי גודל מסך
            window.addEventListener('resize', handleMergeViewResize);

        } catch (error) {
            console.error('Error creating MergeView:', error);
            showAdvancedFallback('שגיאה ביצירת תצוגה מתקדמת: ' + error.message);
        }
    }

    /**
     * קבלת language support לפי שם הקובץ
     */
    function getLanguageSupportForFile(filePath) {
        if (!filePath) return null;
        const CM = window.CodeMirror6;
        if (!CM || !CM.getLanguageSupport) return null;

        const ext = filePath.split('.').pop()?.toLowerCase();
        const langMap = {
            'py': 'python',
            'js': 'javascript',
            'mjs': 'javascript',
            'ts': 'typescript',
            'tsx': 'typescript',
            'html': 'html',
            'htm': 'html',
            'css': 'css',
            'json': 'json',
            'md': 'markdown',
            'sql': 'sql',
            'xml': 'xml'
        };
        const lang = langMap[ext];
        return lang ? CM.getLanguageSupport(lang) : null;
    }

    /**
     * הצגת הודעת fallback בתצוגה מתקדמת
     */
    function showAdvancedFallback(message) {
        const container = diffModal.querySelector('.diff-advanced-content');
        if (!container) return;
        container.innerHTML = `
            <div class="diff-advanced-fallback">
                <i class="bi bi-info-circle"></i>
                <p>${escapeHtml(message)}</p>
                <button class="switch-to-basic-btn">עבור לתצוגה בסיסית</button>
            </div>
        `;
        container.querySelector('.switch-to-basic-btn')?.addEventListener('click', () => {
            switchDiffView('basic');
        });
    }

    /**
     * ניקוי MergeView instance
     */
    function destroyMergeView() {
        window.removeEventListener('resize', handleMergeViewResize);
        
        if (state.mergeViewInstance) {
            try {
                state.mergeViewInstance.destroy();
            } catch (e) {
                console.warn('Error destroying MergeView:', e);
            }
            state.mergeViewInstance = null;
        }

        // ניקוי הקונטיינר
        const container = diffModal?.querySelector('.diff-advanced-content');
        if (container) {
            container.innerHTML = '';
            container.classList.remove('merge-view-mobile');
        }
    }

    /**
     * טיפול בשינוי גודל מסך - עדכון תצוגת MergeView
     */
    let resizeTimeout = null;
    function handleMergeViewResize() {
        if (resizeTimeout) clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(() => {
            const container = diffModal?.querySelector('.diff-advanced-content');
            if (!container) return;
            
            const isMobile = window.innerWidth < 768;
            if (isMobile) {
                container.classList.add('merge-view-mobile');
            } else {
                container.classList.remove('merge-view-mobile');
            }
        }, 150);
    }

    function renderDiffStats(container, stats, isTruncated) {
        container.innerHTML = `
            <div class="diff-stat files">
                <i class="bi bi-file-earmark"></i>
                <span>${stats.files_changed} קבצים שונו</span>
            </div>
            <div class="diff-stat additions">
                <i class="bi bi-plus-lg"></i>
                <span>${stats.additions} שורות נוספו</span>
            </div>
            <div class="diff-stat deletions">
                <i class="bi bi-dash-lg"></i>
                <span>${stats.deletions} שורות נמחקו</span>
            </div>
            ${isTruncated ? `
                <div class="diff-stat truncated">
                    <i class="bi bi-exclamation-triangle"></i>
                    <span>התוצאה קוצצה בגלל גודל</span>
                </div>
            ` : ''}
        `;
    }

    function renderDiff(container, parsed) {
        if (!parsed.files || parsed.files.length === 0) {
            container.innerHTML = `
                <div class="diff-empty">
                    <i class="bi bi-check-circle"></i>
                    <p>אין שינויים</p>
                </div>
            `;
            return;
        }

        const html = parsed.files.map(file => renderFileDiff(file)).join('');
        container.innerHTML = `<div class="diff-unified">${html}</div>`;
    }

    function renderFileDiff(file) {
        const statusClass = file.status || 'modified';
        const statusText = {
            added: 'חדש',
            modified: 'שונה',
            deleted: 'נמחק',
            renamed: 'שונה שם',
            copied: 'הועתק',
            binary: 'בינארי'
        }[statusClass] || statusClass;

        // Rename/copy info
        let renameInfo = '';
        if (file.status === 'renamed' && file.rename_from) {
            renameInfo = `
                <span class="diff-file-rename-info">
                    ${escapeHtml(file.rename_from)} → ${escapeHtml(file.rename_to || file.new_path)}
                    ${file.similarity ? `<span class="similarity">(${file.similarity}%)</span>` : ''}
                </span>
            `;
        }

        let hunksHtml = '';

        if (file.is_binary) {
            hunksHtml = `
                <div class="diff-binary-notice">
                    <i class="bi bi-file-binary"></i>
                    קובץ בינארי - לא ניתן להציג שינויים
                </div>
            `;
        } else if (file.hunks && file.hunks.length > 0) {
            hunksHtml = file.hunks.map(hunk => {
                let oldLine = hunk.old_start;
                let newLine = hunk.new_start;

                const linesHtml = hunk.lines.map(line => {
                    let oldNum = '';
                    let newNum = '';

                    if (line.type === 'context') {
                        oldNum = oldLine++;
                        newNum = newLine++;
                    } else if (line.type === 'deletion') {
                        oldNum = oldLine++;
                    } else if (line.type === 'addition') {
                        newNum = newLine++;
                    }

                    return `
                        <div class="diff-line ${line.type}">
                            <span class="diff-line-number old">${oldNum}</span>
                            <span class="diff-line-number new">${newNum}</span>
                            <span class="diff-line-content">${escapeHtml(line.content)}</span>
                        </div>
                    `;
                }).join('');

                const headerInfo = hunk.header ? ` ${escapeHtml(hunk.header)}` : '';

                return `
                    <div class="diff-hunk">
                        <div class="diff-hunk-header">
                            @@ -${hunk.old_start},${hunk.old_count} +${hunk.new_start},${hunk.new_count} @@${headerInfo}
                        </div>
                        ${linesHtml}
                    </div>
                `;
            }).join('');
        }

        const filePath = file.new_path || file.old_path;

        return `
            <div class="diff-file">
                <div class="diff-file-header">
                    <span class="diff-file-status ${statusClass}">${statusText}</span>
                    <span class="diff-file-path">${escapeHtml(filePath)}</span>
                    ${renameInfo}
                    <div class="diff-file-stats">
                        <span class="additions">+${file.additions}</span>
                        <span class="deletions">-${file.deletions}</span>
                    </div>
                </div>
                ${hunksHtml}
            </div>
        `;
    }

    // ============================================
    // Public API
    // ============================================

    return {
        init,
        openHistoryPanel,
        closeHistoryPanel,
        showDiff,
        closeDiffModal,
        viewFileAtCommit,
        backToHead,
        loadHistory,
        get state() { return { ...state }; }
    };
})();

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    RepoHistory.init();
});

// Export for use in other modules
window.RepoHistory = RepoHistory;
