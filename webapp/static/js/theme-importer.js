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
    const preview = document.getElementById('theme-preview-container');
    const myThemesList = document.getElementById('myThemesList');
    let myThemes = [];

    // === History (Undo/Redo) + Drafts (Autosave) ===
    class ThemeHistory {
        constructor(maxSize = 50) {
            this.maxSize = Math.max(5, Number(maxSize) || 50);
            this.stack = [];
            this.index = -1;
        }

        pushState(state) {
            if (!state || typeof state !== 'object') return;
            const cloned = {};
            Object.keys(state).forEach((k) => {
                cloned[k] = String(state[k]);
            });
            const fingerprint = JSON.stringify(cloned);
            const current = this.stack[this.index];
            const currentFp = current ? JSON.stringify(current) : null;
            if (currentFp === fingerprint) return;

            // אם עשינו undo ואז שינינו – מוחקים את כל מה שאחרי האינדקס
            if (this.index < this.stack.length - 1) {
                this.stack = this.stack.slice(0, this.index + 1);
            }

            this.stack.push(cloned);
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
        const toast = document.getElementById('theme-toast');
        if (!toast) return;

        // הודעה קבועה (לא מציגים תוכן טיוטה כדי להימנע מהזרקת HTML)
        toast.className = 'theme-toast visible info';
        toast.innerHTML = `
            <div style="display:flex; align-items:center; gap:0.75rem; flex-wrap:wrap;">
                <div style="flex:1; min-width: 200px;">
                    נמצאה טיוטה שלא נשמרה. לשחזר?
                </div>
                <div style="display:flex; gap:0.5rem;">
                    <button type="button" class="btn btn-sm btn-primary" data-action="restore-draft">שחזר</button>
                    <button type="button" class="btn btn-sm btn-outline-light" data-action="dismiss-draft">לא</button>
                </div>
            </div>
        `;

        const onClick = async (e) => {
            const btn = e.target && e.target.closest ? e.target.closest('button[data-action]') : null;
            if (!btn) return;
            const action = btn.dataset.action;
            if (action === 'dismiss-draft') {
                clearDraftFromLocalStorage();
                toast.classList.remove('visible');
                toast.innerHTML = '';
                toast.removeEventListener('click', onClick);
                return;
            }
            if (action === 'restore-draft') {
                try {
                    if (draft && typeof draft.json_input === 'string' && jsonInput) {
                        jsonInput.value = draft.json_input;
                    }
                    if (draft && draft.preview_state && typeof draft.preview_state === 'object' && preview) {
                        saveOriginalPreviewState();
                        applyPreviewState(draft.preview_state);
                        isPreviewActive = true;
                        if (revertBtn) revertBtn.style.display = 'inline-flex';
                        history = new ThemeHistory(HISTORY_MAX);
                        history.pushState(getPreviewState());
                    }
                    showToast('הטיוטה שוחזרה', 'success');
                } finally {
                    toast.classList.remove('visible');
                    toast.innerHTML = '';
                    toast.removeEventListener('click', onClick);
                }
            }
        };

        toast.addEventListener('click', onClick);

        // נסגר אוטומטית אחרי 10 שניות (אבל הטיוטה נשארת)
        setTimeout(() => {
            try {
                toast.classList.remove('visible');
                toast.innerHTML = '';
                toast.removeEventListener('click', onClick);
            } catch (e) {}
        }, 10000);
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
                const state = history.undo();
                if (state) {
                    saveOriginalPreviewState();
                    applyPreviewState(state);
                    isPreviewActive = true;
                    if (revertBtn) revertBtn.style.display = 'inline-flex';
                    saveDraftToLocalStorage();
                }
                e.preventDefault();
                return;
            }

            // Redo: Ctrl+Y or Ctrl+Shift+Z
            if (e.key === 'y' || e.key === 'Y' || ((e.key === 'z' || e.key === 'Z') && e.shiftKey)) {
                const state = history.redo();
                if (state) {
                    saveOriginalPreviewState();
                    applyPreviewState(state);
                    isPreviewActive = true;
                    if (revertBtn) revertBtn.style.display = 'inline-flex';
                    saveDraftToLocalStorage();
                }
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
            toast.textContent = message;
            toast.className = 'theme-toast visible ' + type;
            setTimeout(() => {
                toast.classList.remove('visible');
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
            history.pushState(getPreviewState());
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
            history.pushState(getPreviewState());
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
                history = new ThemeHistory(HISTORY_MAX);
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
                history = new ThemeHistory(HISTORY_MAX);
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

    function init() {
        initTabs();
        initFilters();
        initImport();
        initRevertButton();
        initKeyboardShortcuts();
        // מצב בסיס ל-Undo/Redo (לפני כל preview)
        try {
            if (preview) history.pushState(getPreviewState());
        } catch (e) {}
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

