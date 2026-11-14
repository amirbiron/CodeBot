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
    // ערכת המסמך (לשונית הייבוא): ערכה שחלה רק על תצוגת ה-Markdown של הקבצים. השמירה ב-/api/ui_prefs
    // (md_doc_theme + md_doc_theme_scope), והבחירה הנוכחית מגיעה מהשרת ב-data-current / data-scope.
    const docThemeSection = document.getElementById('mdDocThemeSection');
    const docThemeSelect = document.getElementById('mdDocThemeSelect');
    const docThemeScope = document.getElementById('mdDocThemeScope');
    const docThemeApply = document.getElementById('mdDocThemeApply');
    const docThemeStatus = document.getElementById('mdDocThemeStatus');
    const importAsDocTheme = document.getElementById('importAsDocTheme');
    let docThemeCurrent = docThemeSection ? (docThemeSection.dataset.current || '') : '';
    // ``custom:<id>`` / ``shared:<slug>`` ← שם הערכה, לשורת המצב.
    const docThemeNames = new Map();

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

        // המשתנים שהתצוגה המקדימה שומרת לפני preview ומסירה ב-revertPreview. זו אינה העתקה של
        // ALLOWED_VARIABLES_WHITELIST: ווי הדריסה (‏--*-override) ומשתני ה-Markdown המורחבים
        // (‏--md-inline-code-*, ‏--md-table-*, ‏--md-mermaid-bg) נמצאים שם ולא כאן.
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

    // === ערכת המסמך ===
    function renderDocThemeStatus() {
        if (!docThemeStatus) return;
        if (!docThemeCurrent) {
            docThemeStatus.textContent = 'אין ערכת מסמך — המסמך מוצג בערכת הממשק.';
            return;
        }
        const name = docThemeNames.get(docThemeCurrent);
        // מצביע לערכה שלא ברשימה: היא נמחקה, או ערכה ציבורית שכובתה. המסמך מוצג אז בערכת הממשק.
        docThemeStatus.textContent = name
            ? `ערכת המסמך: ${name}`
            : 'הערכה שנבחרה לתצוגת המסמך כבר לא קיימת — המסמך מוצג בערכת הממשק.';
    }

    function addDocThemeGroup(label, items) {
        if (!items.length) return;
        const group = document.createElement('optgroup');
        group.label = label;
        items.forEach(item => {
            const option = document.createElement('option');
            option.value = item.token;
            option.textContent = item.name;
            group.appendChild(option);
        });
        docThemeSelect.appendChild(group);
    }

    async function loadDocThemeChoices() {
        if (!docThemeSelect) return;
        try {
            const res = await fetch('/api/themes/list', { headers: { 'Accept': 'application/json' } });
            const data = await res.json();
            if (!res.ok || !data || !data.ok || !Array.isArray(data.themes)) {
                throw new Error((data && data.error) || 'themes_list_failed');
            }
            const mine = [];
            const shared = [];
            docThemeNames.clear();
            data.themes.forEach(theme => {
                if (!theme || typeof theme.id !== 'string' || !theme.id) return;
                if (theme.type !== 'custom' && theme.type !== 'shared') return;
                const token = `${theme.type}:${theme.id}`.toLowerCase();
                const name = (typeof theme.name === 'string' && theme.name) ? theme.name : theme.id;
                docThemeNames.set(token, name);
                (theme.type === 'custom' ? mine : shared).push({ token, name });
            });
            // הקבוצות נבנות מחדש — גם אחרי ייבוא, כשנוספה ערכה. האפשרות "ללא" אינה בקבוצה, ולכן נשארת.
            docThemeSelect.querySelectorAll('optgroup').forEach(group => group.remove());
            addDocThemeGroup('הערכות שלי', mine);
            addDocThemeGroup('ערכות ציבוריות', shared);
            docThemeSelect.value = docThemeNames.has(docThemeCurrent) ? docThemeCurrent : '';
        } catch (error) {
            console.error('Failed to load document theme choices:', error);
            if (docThemeStatus) docThemeStatus.textContent = 'שגיאה בטעינת רשימת הערכות';
            return;
        }
        renderDocThemeStatus();
    }

    /**
     * שומר את ערכת המסמך ומחזיר את מה שהשרת שמר (``custom:<id>`` / ``shared:<slug>`` / ``''``).
     * זורק בכל כשל — הקורא מציג שגיאה ולא הצלחה.
     */
    async function saveDocTheme(token, scope) {
        const res = await fetch('/api/ui_prefs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ md_doc_theme: token || null, md_doc_theme_scope: scope }),
        });
        const data = await res.json().catch(() => null);
        // ``data.ok`` ולא רק ``res.ok``: האנדפוינט מחזיר גם 200 עם ``ok:false`` בחלק ממסלולי הכשל.
        if (!res.ok || !data || data.ok !== true) {
            throw new Error((data && data.error) || 'md_doc_theme_save_failed');
        }
        const saved = typeof data.md_doc_theme === 'string' ? data.md_doc_theme : '';
        docThemeCurrent = saved;
        return saved;
    }

    function initDocTheme() {
        if (!docThemeSection || !docThemeSelect || !docThemeApply) return;
        if (docThemeScope) {
            docThemeScope.value = docThemeSection.dataset.scope === 'device' ? 'device' : 'global';
        }
        docThemeApply.addEventListener('click', async () => {
            const token = docThemeSelect.value || '';
            docThemeApply.disabled = true;
            try {
                const saved = await saveDocTheme(token, docThemeScope ? docThemeScope.value : 'global');
                renderDocThemeStatus();
                showToast(saved ? 'ערכת המסמך הוחלה' : 'ערכת המסמך כובתה', 'success');
            } catch (error) {
                console.error('Save document theme error:', error);
                showToast('שגיאה בשמירת ערכת המסמך', 'error');
            } finally {
                docThemeApply.disabled = false;
            }
        });
        loadDocThemeChoices();
    }

    /**
     * אחרי ייבוא מוצלח: אם סומן "רק על תצוגת המסמך" — הערכה החדשה נבחרת כערכת המסמך, ונשארים בלשונית הייבוא כדי
     * שהמצב ייראה. מחזיר ``true`` כשזה המסלול, ואז הקורא לא עובר ללשונית "הערכות שלי".
     */
    async function afterImport(theme) {
        if (!importAsDocTheme || !importAsDocTheme.checked || !theme || !theme.id) {
            showToast('הערכה יובאה בהצלחה!', 'success');
            return false;
        }
        try {
            await saveDocTheme(`custom:${theme.id}`, docThemeScope ? docThemeScope.value : 'global');
            showToast('הערכה יובאה והוחלה על תצוגת המסמך', 'success');
        } catch (error) {
            console.error('Apply imported theme to document error:', error);
            showToast('הערכה יובאה, אבל לא הוחלה על תצוגת המסמך', 'error');
        }
        await loadDocThemeChoices();
        return true;
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
                const appliedToDocument = await afterImport(data.theme);
                try {
                    if (window.__themeBuilderApi && typeof window.__themeBuilderApi.fetchThemes === 'function') {
                        window.__themeBuilderApi.fetchThemes();
                    }
                } catch (e) {}
                const myTab = document.querySelector('[data-tab="my-themes"]');
                if (myTab && !appliedToDocument) myTab.click();
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
                const appliedToDocument = await afterImport(data.theme);
                try {
                    if (window.__themeBuilderApi && typeof window.__themeBuilderApi.fetchThemes === 'function') {
                        window.__themeBuilderApi.fetchThemes();
                    }
                } catch (e) {}
                const myTab = document.querySelector('[data-tab="my-themes"]');
                if (myTab && !appliedToDocument) myTab.click();
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
        initDocTheme();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();

