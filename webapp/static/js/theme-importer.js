/**
 * Theme Importer Module
 * מנהל ייבוא ערכות מ-VS Code ו-JSON, וגלריית Presets
 *
 * מבוסס על GUIDES/custom_themes_guide.md
 */
(function() {
    'use strict';

    function escapeHtml(str) {
        try {
            const div = document.createElement('div');
            div.textContent = String(str || '');
            return div.innerHTML;
        } catch (e) {
            return String(str || '');
        }
    }

    function formatDate(isoString) {
        try {
            const date = new Date(isoString);
            return date.toLocaleDateString('he-IL', { day: 'numeric', month: 'short' });
        } catch (e) {
            return '';
        }
    }

    // === State ===
    let presets = [];
    let currentFilter = 'all';
    const HISTORY_MAX = 50;
    const DRAFT_STORAGE_KEY = 'theme_gallery_draft_v1';

    // רשימה מסונכרנת עם ALLOWED_VARIABLES_WHITELIST (וגם עם saveOriginalPreviewState)
    const ALLOWED_VARS = [
        '--bg-primary', '--bg-secondary', '--bg-tertiary',
        '--text-primary', '--text-secondary', '--text-muted',
        '--primary', '--primary-hover', '--primary-light',
        '--secondary',
        '--border-color', '--shadow-color',
        '--success', '--warning', '--error',
        '--danger-bg', '--danger-border', '--text-on-warning',
        '--code-bg', '--code-text', '--code-border',
        '--link-color',
        '--navbar-bg', '--card-bg', '--card-border',
        '--input-bg', '--input-border',
        '--btn-primary-bg', '--btn-primary-color',
        '--btn-primary-border', '--btn-primary-shadow',
        '--btn-primary-hover-bg', '--btn-primary-hover-color',
        '--glass', '--glass-border', '--glass-hover', '--glass-blur',
        '--md-surface', '--md-text',
        '--split-preview-bg', '--split-preview-meta', '--split-preview-placeholder'
    ];

    // === DOM Elements ===
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');
    const presetsList = document.getElementById('presetsList');
    const filterBtns = document.querySelectorAll('.filter-btn');
    const uploadArea = document.getElementById('uploadArea');
    const fileInput = document.getElementById('themeFileInput');
    const jsonInput = document.getElementById('jsonInput');
    const importJsonBtn = document.getElementById('importJsonBtn');
    const uploadStatus = document.getElementById('uploadStatus');
    const revertBtn = document.getElementById('revertPreviewBtn');
    const undoBtn = document.getElementById('undoPreviewBtn');
    const redoBtn = document.getElementById('redoPreviewBtn');
    const preview = document.getElementById('theme-preview-container');
    const myThemesList = document.getElementById('myThemesList');
    let myThemes = [];
    const confirmModal = document.getElementById('historyConfirmModal');
    const confirmTextEl = document.getElementById('historyConfirmText');

    // === History (Undo/Redo) + Drafts (Autosave) ===
    class ThemeHistory {
        constructor(maxSize = 50) {
            this.maxSize = Math.max(5, Number(maxSize) || 50);
            this.stack = [];
            this.index = -1;
        }

        pushState(state, meta = null) {
            if (!state || typeof state !== 'object') return;

            const cloned = {
                preview_active: !!state.preview_active,
                preview_state: null
            };
            if (state.preview_state && typeof state.preview_state === 'object') {
                const ps = {};
                Object.keys(state.preview_state).forEach((k) => {
                    ps[k] = String(state.preview_state[k]);
                });
                cloned.preview_state = ps;
            }

            const fingerprint = JSON.stringify(cloned);
            const current = this.stack[this.index];
            const currentFp = current ? JSON.stringify(current.state) : null;
            if (currentFp === fingerprint) return;

            // אם עשינו undo ואז שינינו – מוחקים את כל מה שאחרי האינדקס
            if (this.index < this.stack.length - 1) {
                this.stack = this.stack.slice(0, this.index + 1);
            }

            this.stack.push({
                state: cloned,
                meta: meta && typeof meta === 'object' ? meta : { kind: 'simple' }
            });
            this.index = this.stack.length - 1;

            // מגבלת גודל
            if (this.stack.length > this.maxSize) {
                const toDrop = this.stack.length - this.maxSize;
                this.stack = this.stack.slice(toDrop);
                this.index = this.stack.length - 1;
            }
        }

        undo() {
            if (this.index <= 0) return null;
            this.index -= 1;
            return this.stack[this.index] || null;
        }

        redo() {
            if (this.index >= this.stack.length - 1) return null;
            this.index += 1;
            return this.stack[this.index] || null;
        }
    }

    let history = new ThemeHistory(HISTORY_MAX);
    let _draftDebounceTimer = null;
    let _jsonHistoryDebounceTimer = null;
    let _isApplyingHistory = false;
    let _toastActionHandler = null;
    let _toastAutoCloseTimer = null;
    let _recentMajorAction = null; // { label: string, ts: number }

    function markRecentMajorAction(label) {
        try {
            _recentMajorAction = { label: String(label || ''), ts: Date.now() };
        } catch (e) {
            _recentMajorAction = { label: '', ts: Date.now() };
        }
    }

    function getRecentMajorActionLabel() {
        try {
            if (!_recentMajorAction || typeof _recentMajorAction.ts !== 'number') return null;
            // חלון זמן קצר כדי למנוע חלונות אישור "דביקים"
            if ((Date.now() - _recentMajorAction.ts) > 30000) return null;
            return _recentMajorAction.label || 'פעולה גדולה';
        } catch (e) {
            return null;
        }
    }

    function _safeJsonParse(str) {
        try {
            return JSON.parse(str);
        } catch (e) {
            return null;
        }
    }

    function getPreviewState() {
        if (!preview) return {};
        const computed = getComputedStyle(preview);
        const out = {};
        ALLOWED_VARS.forEach((varName) => {
            const v = (preview.style.getPropertyValue(varName) || computed.getPropertyValue(varName) || '').trim();
            if (v) out[varName] = v;
        });
        return out;
    }

    function applyPreviewState(state) {
        if (!preview || !state) return;
        // מנקים קודם כדי למנוע "שאריות" ממשתנים קודמים
        ALLOWED_VARS.forEach((varName) => preview.style.removeProperty(varName));
        Object.entries(state).forEach(([k, v]) => {
            if (ALLOWED_VARS.includes(k)) {
                preview.style.setProperty(k, String(v));
            }
        });
    }

    function getGalleryState() {
        return {
            preview_active: !!isPreviewActive,
            preview_state: isPreviewActive ? getPreviewState() : null
        };
    }

    function clearPreviewStylesOnly() {
        try {
            if (!preview) return;
            ALLOWED_VARS.forEach((varName) => preview.style.removeProperty(varName));
        } catch (e) {}
    }

    function applyGalleryState(state) {
        if (!state || typeof state !== 'object') return;
        _isApplyingHistory = true;
        try {
            const wantPreview = !!state.preview_active && state.preview_state && typeof state.preview_state === 'object';
            if (wantPreview) {
                saveOriginalPreviewState();
                isPreviewActive = true;
                if (revertBtn) revertBtn.style.display = 'inline-flex';
                applyPreviewState(state.preview_state);
            } else {
                clearPreviewStylesOnly();
                isPreviewActive = false;
                if (revertBtn) revertBtn.style.display = 'none';
            }

            saveDraftToLocalStorage();
            updateUndoRedoButtons();
        } finally {
            _isApplyingHistory = false;
        }
    }

    function updateUndoRedoButtons() {
        try {
            if (undoBtn) undoBtn.disabled = !(history && history.index > 0);
            if (redoBtn) redoBtn.disabled = !(history && history.index < (history.stack.length - 1));
        } catch (e) {}
    }

    function setToastHtml(html, onClick, autoCloseMs = 5000) {
        const toast = document.getElementById('theme-toast');
        if (!toast) return;
        try {
            if (_toastAutoCloseTimer) clearTimeout(_toastAutoCloseTimer);
            _toastAutoCloseTimer = null;
            if (_toastActionHandler) toast.removeEventListener('click', _toastActionHandler);
            _toastActionHandler = null;
        } catch (e) {}

        toast.className = 'theme-toast visible info';
        toast.innerHTML = html;

        if (typeof onClick === 'function') {
            _toastActionHandler = onClick;
            toast.addEventListener('click', _toastActionHandler);
        }

        if (autoCloseMs && autoCloseMs > 0) {
            _toastAutoCloseTimer = setTimeout(() => {
                try {
                    toast.classList.remove('visible');
                    toast.innerHTML = '';
                    if (_toastActionHandler) toast.removeEventListener('click', _toastActionHandler);
                    _toastActionHandler = null;
                } catch (e) {}
            }, autoCloseMs);
        }
    }

    function openConfirmModal(message, onConfirm) {
        if (!confirmModal) {
            if (confirm(message)) onConfirm();
            return;
        }
        try {
            if (confirmTextEl) confirmTextEl.textContent = message;
            confirmModal.classList.add('open');
            confirmModal.setAttribute('aria-hidden', 'false');

            const close = () => {
                try {
                    confirmModal.classList.remove('open');
                    confirmModal.setAttribute('aria-hidden', 'true');
                    confirmModal.removeEventListener('click', onClick);
                    document.removeEventListener('keydown', onKey);
                } catch (e) {}
            };

            const onKey = (e) => {
                if (e && e.key === 'Escape') close();
            };

            const onClick = (e) => {
                const el = e.target && e.target.closest ? e.target.closest('[data-action]') : null;
                const action = el && el.dataset ? el.dataset.action : null;
                if (!action) return;
                e.preventDefault();
                e.stopPropagation();
                if (action === 'confirm') {
                    close();
                    onConfirm();
                    return;
                }
                if (action === 'cancel' || action === 'close') {
                    close();
                }
            };

            confirmModal.addEventListener('click', onClick);
            document.addEventListener('keydown', onKey);
        } catch (e) {
            if (confirm(message)) onConfirm();
        }
    }

    function showUndoRedoToast(kind) {
        const isUndo = kind === 'undo';
        const label = isUndo ? 'בוצע Undo' : 'בוצע Redo';
        const actionLabel = isUndo ? 'החזר' : 'בטל';
        const actionKey = isUndo ? 'toast-redo' : 'toast-undo';
        setToastHtml(
            `
                <div style="display:flex; align-items:center; gap:0.75rem; flex-wrap:wrap;">
                    <div style="flex:1; min-width: 160px;">${label}</div>
                    <button type="button" class="btn btn-sm btn-primary" data-action="${actionKey}">${actionLabel}</button>
                </div>
            `,
            (e) => {
                const btn = e.target && e.target.closest ? e.target.closest('button[data-action]') : null;
                if (!btn) return;
                const action = btn.dataset.action;
                if (action === 'toast-redo') performRedo('Toast');
                if (action === 'toast-undo') requestUndo('Toast');
            },
            5000
        );
    }

    function requestUndo(sourceLabel) {
        if (!(history && history.index > 0)) {
            showToast('אין יותר Undo', 'info');
            return;
        }
        try {
            const currentEntry = history && history.stack ? history.stack[history.index] : null;
            const isMajor = !!(currentEntry && currentEntry.meta && currentEntry.meta.kind === 'major');
            const recentMajorLabel = getRecentMajorActionLabel();
            if (isMajor || recentMajorLabel) {
                const label = (isMajor && currentEntry && currentEntry.meta && currentEntry.meta.label)
                    ? currentEntry.meta.label
                    : recentMajorLabel;
                openConfirmModal(
                    `אתה עומד לבצע Undo על פעולה גדולה${label ? `: ${label}` : ''}. להמשיך?`,
                    () => performUndo(sourceLabel)
                );
                return;
            }
        } catch (e) {}
        performUndo(sourceLabel);
    }

    function performUndo(sourceLabel) {
        const entry = history.undo();
        if (entry && entry.state) {
            applyGalleryState(entry.state);
            showUndoRedoToast('undo');
        } else {
            showToast('אין יותר Undo', 'info');
        }
    }

    function performRedo(sourceLabel) {
        const entry = history.redo();
        if (entry && entry.state) {
            applyGalleryState(entry.state);
            showUndoRedoToast('redo');
        } else {
            showToast('אין יותר Redo', 'info');
        }
    }

    function saveDraftToLocalStorageNow() {
        try {
            if (!window.localStorage) return;

            const jsonDraft = (jsonInput && jsonInput.value) ? String(jsonInput.value) : '';
            const hasJsonDraft = jsonDraft.trim().length > 0;
            const previewState = isPreviewActive ? getPreviewState() : null;
            const hasPreviewDraft = !!(previewState && Object.keys(previewState).length);

            // אין מה לשמור
            if (!hasJsonDraft && !hasPreviewDraft) {
                localStorage.removeItem(DRAFT_STORAGE_KEY);
                return;
            }

            const payload = {
                v: 1,
                ts: Date.now(),
                json_input: jsonDraft,
                preview_active: !!isPreviewActive,
                preview_state: previewState,
            };
            localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(payload));
        } catch (e) {
            // ignore
        }
    }

    function saveDraftToLocalStorage() {
        try {
            if (_draftDebounceTimer) clearTimeout(_draftDebounceTimer);
            _draftDebounceTimer = setTimeout(() => {
                _draftDebounceTimer = null;
                saveDraftToLocalStorageNow();
            }, 2000);
        } catch (e) {}
    }

    function clearDraftFromLocalStorage() {
        try {
            if (!window.localStorage) return;
            localStorage.removeItem(DRAFT_STORAGE_KEY);
        } catch (e) {}
    }

    function showRestoreDraftToast(draft) {
        setToastHtml(
            `
                <div style="display:flex; align-items:center; gap:0.75rem; flex-wrap:wrap;">
                    <div style="flex:1; min-width: 200px;">
                        נמצאה טיוטה שלא נשמרה. לשחזר?
                    </div>
                    <div style="display:flex; gap:0.5rem;">
                        <button type="button" class="btn btn-sm btn-primary" data-action="restore-draft">שחזר</button>
                        <button type="button" class="btn btn-sm btn-outline-light" data-action="dismiss-draft">לא</button>
                    </div>
                </div>
            `,
            async (e) => {
                const btn = e.target && e.target.closest ? e.target.closest('button[data-action]') : null;
                if (!btn) return;
                const action = btn.dataset.action;
                if (action === 'dismiss-draft') {
                    clearDraftFromLocalStorage();
                    const toast = document.getElementById('theme-toast');
                    if (toast) { toast.classList.remove('visible'); toast.innerHTML = ''; }
                    return;
                }
                if (action === 'restore-draft') {
                    if (draft && typeof draft.json_input === 'string' && jsonInput) {
                        jsonInput.value = draft.json_input;
                    }
                    if (draft && draft.preview_state && typeof draft.preview_state === 'object' && preview) {
                        saveOriginalPreviewState();
                        applyPreviewState(draft.preview_state);
                        isPreviewActive = true;
                        if (revertBtn) revertBtn.style.display = 'inline-flex';
                    }
                    history = new ThemeHistory(HISTORY_MAX);
                    history.pushState(getGalleryState(), { kind: 'major', label: 'שחזור טיוטה' });
                    updateUndoRedoButtons();
                    showToast('הטיוטה שוחזרה', 'success');
                    return;
                }
            },
            10000
        );
    }

    function maybeOfferDraftRestore() {
        try {
            if (!window.localStorage) return;
            const raw = localStorage.getItem(DRAFT_STORAGE_KEY);
            if (!raw) return;
            const draft = _safeJsonParse(raw);
            if (!draft || (!draft.json_input && !draft.preview_state)) return;
            showRestoreDraftToast(draft);
        } catch (e) {}
    }

    function isEditableTarget(target) {
        try {
            if (!target) return false;
            const el = target.closest ? target.closest('input, textarea, select, [contenteditable="true"]') : null;
            return !!el;
        } catch (e) {
            return false;
        }
    }

    function initKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            if (!e) return;
            if (isEditableTarget(e.target)) return; // לא שוברים Undo טבעי ב-textarea

            const isCtrl = !!(e.ctrlKey || e.metaKey);
            if (!isCtrl) return;

            // Undo: Ctrl+Z
            if ((e.key === 'z' || e.key === 'Z') && !e.shiftKey) {
                requestUndo('קיצור מקלדת');
                e.preventDefault();
                return;
            }

            // Redo: Ctrl+Y or Ctrl+Shift+Z
            if (e.key === 'y' || e.key === 'Y' || ((e.key === 'z' || e.key === 'Z') && e.shiftKey)) {
                performRedo('קיצור מקלדת');
                e.preventDefault();
            }
        });
    }

    function showToast(message, type = 'info') {
        try {
            if (window.__themeBuilderApi && typeof window.__themeBuilderApi.showToast === 'function') {
                window.__themeBuilderApi.showToast(message, type);
                return;
            }
        } catch (e) {}

        try {
            const toast = document.getElementById('theme-toast');
            if (!toast) return;
            try {
                if (_toastAutoCloseTimer) clearTimeout(_toastAutoCloseTimer);
                _toastAutoCloseTimer = null;
                if (_toastActionHandler) toast.removeEventListener('click', _toastActionHandler);
                _toastActionHandler = null;
            } catch (e) {}
            toast.textContent = message;
            toast.className = 'theme-toast visible ' + type;
            setTimeout(() => {
                toast.classList.remove('visible');
                try { toast.innerHTML = ''; } catch (e) {}
            }, 3000);
        } catch (e) {}
    }

    // === Tab Navigation ===
    function initTabs() {
        if (!tabBtns || !tabBtns.length) return;
        tabBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const tabId = btn.dataset.tab;

                tabBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');

                tabContents.forEach(content => {
                    content.classList.toggle('active', content.id === `${tabId}-tab`);
                });

                if (tabId === 'presets' && presets.length === 0) {
                    loadPresets();
                }
                if (tabId === 'my-themes') {
                    loadMyThemes();
                }
            });
        });
    }

    // === My Themes (saved themes list) ===
    async function loadMyThemes() {
        if (!myThemesList) return;
        try {
            myThemesList.innerHTML = `
                <div class="themes-loading">
                    <i class="fas fa-spinner fa-spin"></i>
                    טוען...
                </div>
            `;
            const res = await fetch('/api/themes', { headers: { 'Accept': 'application/json' } });
            const data = await res.json();
            if (!res.ok || !data || !data.ok) {
                throw new Error((data && data.error) || 'fetch_failed');
            }
            myThemes = data.themes || [];
            renderMyThemes();
        } catch (e) {
            console.error('Failed to load my themes:', e);
            myThemesList.innerHTML = '<p class="text-danger">שגיאה בטעינת הערכות שלך</p>';
        }
    }

    function renderMyThemes() {
        if (!myThemesList) return;
        if (!myThemes || !myThemes.length) {
            myThemesList.innerHTML = `
                <div class="themes-loading">
                    <i class="fas fa-palette"></i>
                    <p style="margin-top: 0.75rem;">עדיין אין לך ערכות מותאמות</p>
                    <p class="text-muted small">אפשר ליצור חדשה בבונה הערכות או להוסיף Preset/ייבוא</p>
                </div>
            `;
            return;
        }

        myThemesList.innerHTML = myThemes.map(t => `
            <div class="my-theme-card" data-theme-id="${t.id}">
                <div class="my-theme-left">
                    <div class="my-theme-title">
                        <span class="my-theme-badge ${t.is_active ? 'active' : ''}">
                            ${t.is_active ? 'פעילה' : 'שמורה'}
                        </span>
                        <span title="${escapeHtml(t.name || '')}">${escapeHtml(t.name || '')}</span>
                    </div>
                    <div class="my-theme-meta">
                        ${t.description ? escapeHtml(t.description) : ''}
                        ${t.updated_at ? ` • עודכן: ${formatDate(t.updated_at)}` : ''}
                    </div>
                </div>
                <div class="my-theme-actions">
                    <a class="btn btn-sm btn-outline-primary" href="/settings/theme-builder?theme_id=${encodeURIComponent(t.id)}" title="עריכה בבונה הערכות">
                        <i class="fas fa-edit"></i>
                    </a>
                    ${!t.is_active ? `
                        <button type="button" class="btn btn-sm btn-success" data-action="activate" title="הפעל">
                            <i class="fas fa-check"></i>
                        </button>
                    ` : ''}
                    <button type="button" class="btn btn-sm btn-danger" data-action="delete" title="מחק">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </div>
        `).join('');

        myThemesList.querySelectorAll('.my-theme-card').forEach(card => {
            card.addEventListener('click', async (e) => {
                // Clicking edit link should navigate normally (no preview)
                const link = e.target && e.target.closest ? e.target.closest('a') : null;
                if (link) return;

                const action = e.target && e.target.closest ? e.target.closest('[data-action]') : null;
                const themeId = card.dataset.themeId;
                if (!themeId) return;
                if (action && action.dataset && action.dataset.action === 'activate') {
                    e.preventDefault();
                    e.stopPropagation();
                    await activateTheme(themeId);
                    return;
                }
                if (action && action.dataset && action.dataset.action === 'delete') {
                    e.preventDefault();
                    e.stopPropagation();
                    await deleteTheme(themeId);
                    return;
                }
                // Click on card: preview
                await previewTheme(themeId);
            });
        });
    }

    async function previewTheme(themeId) {
        if (!themeId || !preview) return;
        saveOriginalPreviewState();
        isPreviewActive = true;
        if (revertBtn) revertBtn.style.display = 'inline-flex';

        try {
            const res = await fetch(`/api/themes/${encodeURIComponent(themeId)}`, { headers: { 'Accept': 'application/json' } });
            const data = await res.json();
            if (!res.ok || !data || !data.ok || !data.theme) throw new Error('fetch_failed');
            const vars = data.theme.variables || {};
            Object.entries(vars).forEach(([k, v]) => {
                preview.style.setProperty(k, String(v));
            });
            history.pushState(getGalleryState(), { kind: 'major', label: 'תצוגה מקדימה (ערכה שמורה)' });
            updateUndoRedoButtons();
            saveDraftToLocalStorage();
        } catch (e) {
            console.error('Preview theme error:', e);
            showToast('שגיאה בתצוגה מקדימה', 'error');
        }
    }

    async function activateTheme(themeId) {
        try {
            const res = await fetch(`/api/themes/${encodeURIComponent(themeId)}/activate`, { method: 'POST', headers: { 'Accept': 'application/json' } });
            const data = await res.json();
            if (!res.ok || !data || !data.ok) throw new Error((data && data.error) || 'activate_failed');
            showToast('הערכה הופעלה! מרענן...', 'success');
            setTimeout(() => location.reload(), 800);
        } catch (e) {
            console.error('Activate theme error:', e);
            showToast('שגיאה בהפעלת הערכה', 'error');
        }
    }

    async function deleteTheme(themeId) {
        if (!confirm('האם למחוק את הערכה? פעולה זו אינה ניתנת לביטול.')) return;
        try {
            const res = await fetch(`/api/themes/${encodeURIComponent(themeId)}`, { method: 'DELETE', headers: { 'Accept': 'application/json' } });
            const data = await res.json();
            if (!res.ok || !data || !data.ok) throw new Error((data && data.error) || 'delete_failed');
            showToast('הערכה נמחקה', 'success');
            await loadMyThemes();
        } catch (e) {
            console.error('Delete theme error:', e);
            showToast('שגיאה במחיקת הערכה', 'error');
        }
    }

    // === Presets Gallery ===
    async function loadPresets() {
        if (!presetsList) return;
        try {
            const response = await fetch('/api/themes/presets', { headers: { 'Accept': 'application/json' } });
            const data = await response.json();
            presets = data.presets || [];
            renderPresets();
        } catch (error) {
            console.error('Failed to load presets:', error);
            presetsList.innerHTML = '<p class="text-danger">שגיאה בטעינת הערכות</p>';
        }
    }

    function renderPresets() {
        if (!presetsList) return;
        const filtered = currentFilter === 'all'
            ? presets
            : presets.filter(p => p.category === currentFilter);

        presetsList.innerHTML = filtered.map(preset => `
            <div class="preset-card" data-preset-id="${preset.id}">
                <div class="preset-info">
                    <div class="preset-preview">
                        ${(preset.preview_colors || []).map(c =>
                            `<div class="preset-preview-color" style="background: ${c}"></div>`
                        ).join('')}
                    </div>
                    <div class="preset-name">${preset.name}</div>
                    <div class="preset-desc">${preset.description || ''}</div>
                </div>
                <button type="button" class="btn btn-sm btn-outline-primary apply-preset-btn" title="הוסף לערכות שלי">
                    <i class="fas fa-plus"></i>
                </button>
            </div>
        `).join('');

        presetsList.querySelectorAll('.apply-preset-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const card = btn.closest('.preset-card');
                applyPreset(card && card.dataset && card.dataset.presetId);
            });
        });

        presetsList.querySelectorAll('.preset-card').forEach(card => {
            card.addEventListener('click', () => {
                previewPreset(card.dataset.presetId);
            });
        });
    }

    async function applyPreset(presetId) {
        if (!presetId) return;
        try {
            const response = await fetch(`/api/themes/presets/${presetId}/apply`, {
                method: 'POST',
                headers: { 'Accept': 'application/json' }
            });
            const data = await response.json();

            if (data.success) {
                showToast('הערכה נוספה בהצלחה!', 'success');
                await loadMyThemes();
                markRecentMajorAction('החלת Preset');

                // מעבר לטאב "הערכות שלי"
                const myTab = document.querySelector('[data-tab="my-themes"]');
                if (myTab) myTab.click();
            } else {
                showToast(data.error || 'שגיאה בהוספת הערכה', 'error');
            }
        } catch (error) {
            console.error('Apply preset error:', error);
            showToast('שגיאה בהוספת הערכה', 'error');
        }
    }

    // === Preview State Management ===
    let originalPreviewStyles = null; // שומר את המצב המקורי לפני preview
    let isPreviewActive = false;

    function saveOriginalPreviewState() {
        /**
         * שומר את כל ה-CSS variables הנוכחיים של אזור התצוגה המקדימה.
         */
        if (!preview || originalPreviewStyles !== null) return;

        originalPreviewStyles = {};
        const computedStyle = getComputedStyle(preview);

        // רשימה מסונכרנת עם ALLOWED_VARIABLES_WHITELIST
        const varsToSave = [
            '--bg-primary', '--bg-secondary', '--bg-tertiary',
            '--text-primary', '--text-secondary', '--text-muted',
            '--primary', '--primary-hover', '--primary-light',
            '--secondary',
            '--border-color', '--shadow-color',
            '--success', '--warning', '--error',
            '--danger-bg', '--danger-border', '--text-on-warning',
            '--code-bg', '--code-text', '--code-border',
            '--link-color',
            '--navbar-bg', '--card-bg', '--card-border',
            '--input-bg', '--input-border',
            '--btn-primary-bg', '--btn-primary-color',
            '--btn-primary-border', '--btn-primary-shadow',
            '--btn-primary-hover-bg', '--btn-primary-hover-color',
            '--glass', '--glass-border', '--glass-hover', '--glass-blur',
            '--md-surface', '--md-text',
            '--split-preview-bg', '--split-preview-meta', '--split-preview-placeholder'
        ];

        varsToSave.forEach(varName => {
            const value = preview.style.getPropertyValue(varName) ||
                computedStyle.getPropertyValue(varName);
            if (value) {
                originalPreviewStyles[varName] = value.trim();
            }
        });
    }

    function getSelectedThemeIdFromDom() {
        try {
            const selected = document.querySelector('#themesList .theme-item.selected');
            return selected && selected.dataset ? selected.dataset.themeId : null;
        } catch (e) {
            return null;
        }
    }

    function isNewThemeFromDom() {
        // אם אין ערכה נבחרת - זה "ערכה חדשה"
        return !getSelectedThemeIdFromDom();
    }

    async function revertPreview() {
        /**
         * מחזיר את אזור התצוגה המקדימה למצב המקורי.
         */
        if (!preview || !originalPreviewStyles) return;

        // מנקה את כל הסגנונות שהוחלו
        Object.keys(originalPreviewStyles).forEach(varName => {
            preview.style.removeProperty(varName);
        });

        // מחיל מחדש את הערכה הנוכחית אם יש ערכה נבחרת
        const selectedThemeId = getSelectedThemeIdFromDom();
        const isNewTheme = isNewThemeFromDom();
        if (selectedThemeId && !isNewTheme) {
            try {
                if (window.__themeBuilderApi && typeof window.__themeBuilderApi.fetchThemeDetails === 'function') {
                    const theme = await window.__themeBuilderApi.fetchThemeDetails(selectedThemeId);
                    if (theme && theme.variables) {
                        Object.entries(theme.variables).forEach(([key, value]) => {
                            preview.style.setProperty(key, String(value));
                        });
                    }
                } else {
                    const res = await fetch(`/api/themes/${selectedThemeId}`);
                    const data = await res.json();
                    const theme = (data && data.theme) ? data.theme : null;
                    if (theme && theme.variables) {
                        Object.entries(theme.variables).forEach(([key, value]) => {
                            preview.style.setProperty(key, String(value));
                        });
                    }
                }
            } catch (e) {}
        }

        originalPreviewStyles = null;
        isPreviewActive = false;
        history = new ThemeHistory(HISTORY_MAX);
        clearDraftFromLocalStorage();
        try {
            history.pushState(getGalleryState(), { kind: 'simple', label: 'אחרי ביטול תצוגה מקדימה' });
        } catch (e) {}
        updateUndoRedoButtons();

        if (revertBtn) {
            revertBtn.style.display = 'none';
        }
    }

    async function previewPreset(presetId) {
        if (!presetId || !preview) return;

        saveOriginalPreviewState();
        isPreviewActive = true;
        if (revertBtn) {
            revertBtn.style.display = 'inline-flex';
        }

        try {
            const res = await fetch(`/api/themes/presets/${presetId}`, { headers: { 'Accept': 'application/json' } });
            const data = await res.json();
            const vars = (data && data.variables) ? data.variables : {};
            Object.entries(vars).forEach(([k, v]) => {
                preview.style.setProperty(k, String(v));
            });
            history.pushState(getGalleryState(), { kind: 'major', label: 'תצוגה מקדימה (Preset)' });
            updateUndoRedoButtons();
            saveDraftToLocalStorage();
        } catch (e) {
            showToast('שגיאה בתצוגה מקדימה', 'error');
        }
    }

    // === Import (Drag & Drop + JSON paste) ===
    function initImport() {
        if (uploadArea && fileInput) {
            uploadArea.addEventListener('click', () => fileInput.click());

            uploadArea.addEventListener('dragover', (e) => {
                e.preventDefault();
                uploadArea.classList.add('dragover');
            });

            uploadArea.addEventListener('dragleave', () => {
                uploadArea.classList.remove('dragover');
            });

            uploadArea.addEventListener('drop', (e) => {
                e.preventDefault();
                uploadArea.classList.remove('dragover');
                const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
                if (file) uploadThemeFile(file);
            });

            fileInput.addEventListener('change', () => {
                const file = fileInput.files && fileInput.files[0];
                if (file) uploadThemeFile(file);
                try { fileInput.value = ''; } catch (e) {}
            });
        }

        if (importJsonBtn) {
            importJsonBtn.addEventListener('click', () => {
                const content = (jsonInput && jsonInput.value) ? jsonInput.value.trim() : '';
                if (!content) {
                    showToast('נא להדביק JSON', 'error');
                    return;
                }
                importThemeFromJson(content);
            });
        }

        if (jsonInput) {
            jsonInput.addEventListener('input', () => {
                saveDraftToLocalStorage();
            });
        }
    }

    async function uploadThemeFile(file) {
        if (!file) return;
        try {
            if (uploadStatus) uploadStatus.style.display = 'block';
            const formData = new FormData();
            formData.append('file', file, file.name || 'theme.json');

            const res = await fetch('/api/themes/import', {
                method: 'POST',
                body: formData
            });
            const data = await res.json();

            if (data.success) {
                showToast('הערכה יובאה בהצלחה!', 'success');
                await loadMyThemes();
                clearDraftFromLocalStorage();
                markRecentMajorAction('ייבוא קובץ');
                const myTab = document.querySelector('[data-tab="my-themes"]');
                if (myTab) myTab.click();
            } else {
                showToast(data.error || 'שגיאה בייבוא הערכה', 'error');
            }
        } catch (e) {
            console.error('Upload theme file error:', e);
            showToast('שגיאה בייבוא הערכה', 'error');
        } finally {
            if (uploadStatus) uploadStatus.style.display = 'none';
        }
    }

    async function importThemeFromJson(jsonContent) {
        try {
            if (uploadStatus) uploadStatus.style.display = 'block';
            const res = await fetch('/api/themes/import', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
                body: JSON.stringify({ json_content: jsonContent })
            });
            const data = await res.json();

            if (data.success) {
                showToast('הערכה יובאה בהצלחה!', 'success');
                await loadMyThemes();
                const myTab = document.querySelector('[data-tab="my-themes"]');
                if (myTab) myTab.click();
                if (jsonInput) jsonInput.value = '';
                clearDraftFromLocalStorage();
                markRecentMajorAction('ייבוא JSON');
            } else {
                showToast(data.error || 'שגיאה בייבוא הערכה', 'error');
            }
        } catch (e) {
            console.error('Import JSON error:', e);
            showToast('שגיאה בייבוא הערכה', 'error');
        } finally {
            if (uploadStatus) uploadStatus.style.display = 'none';
        }
    }

    function initFilters() {
        if (!filterBtns || !filterBtns.length) return;
        filterBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const f = btn.dataset.filter || 'all';
                currentFilter = f;
                filterBtns.forEach(b => b.classList.toggle('active', b === btn));
                renderPresets();
            });
        });
    }

    function initRevertButton() {
        if (!revertBtn) return;
        revertBtn.addEventListener('click', () => {
            if (isPreviewActive) {
                revertPreview();
            }
        });
    }

    function initUndoRedoButtons() {
        if (undoBtn) {
            undoBtn.addEventListener('click', () => requestUndo('כפתור'));
        }
        if (redoBtn) {
            redoBtn.addEventListener('click', () => performRedo('כפתור'));
        }
        updateUndoRedoButtons();
    }

    function init() {
        initTabs();
        initFilters();
        initImport();
        initRevertButton();
        initUndoRedoButtons();
        initKeyboardShortcuts();
        // מצב בסיס ל-Undo/Redo (לפני כל preview)
        try {
            if (preview) history.pushState(getGalleryState(), { kind: 'simple', label: 'מצב התחלתי' });
        } catch (e) {}
        updateUndoRedoButtons();
        maybeOfferDraftRestore();
        // Load my themes immediately if section exists
        loadMyThemes();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();

