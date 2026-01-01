/**
 * Theme Importer Module
 * מנהל ייבוא ערכות מ-VS Code ו-JSON, וגלריית Presets
 *
 * מבוסס על GUIDES/custom_themes_guide.md
 */
(function() {
    'use strict';

    // === State ===
    let presets = [];
    let currentFilter = 'all';

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
            });
        });
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
                try {
                    if (window.__themeBuilderApi && typeof window.__themeBuilderApi.fetchThemes === 'function') {
                        window.__themeBuilderApi.fetchThemes();
                    }
                } catch (e) {}

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
                try {
                    if (window.__themeBuilderApi && typeof window.__themeBuilderApi.fetchThemes === 'function') {
                        window.__themeBuilderApi.fetchThemes();
                    }
                } catch (e) {}
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
                try {
                    if (window.__themeBuilderApi && typeof window.__themeBuilderApi.fetchThemes === 'function') {
                        window.__themeBuilderApi.fetchThemes();
                    }
                } catch (e) {}
                const myTab = document.querySelector('[data-tab="my-themes"]');
                if (myTab) myTab.click();
                if (jsonInput) jsonInput.value = '';
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
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
