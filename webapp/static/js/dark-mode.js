/**
 * Dark Mode Manager
 * ניהול מצב חשוך/בהיר עם תמיכה ב-Auto mode
 */

(function() {
    'use strict';

    const DARK_MODE_KEY = 'dark_mode_preference';
    const THEME_ATTRIBUTE = 'data-theme';

    function getSystemPreference() {
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            return 'dark';
        }
        return 'light';
    }

    function loadPreference() {
        try {
            const saved = localStorage.getItem(DARK_MODE_KEY);
            if (saved && typeof saved === 'string' && saved.trim().length > 0) {
                return saved;
            }
        } catch (e) {
            console.warn('Failed to load dark mode preference:', e);
        }
        return null;
    }

    function savePreference(mode) {
        try {
            localStorage.setItem(DARK_MODE_KEY, mode);
        } catch (e) {
            console.warn('Failed to save dark mode preference:', e);
        }
    }

    function applyTheme(theme) {
        const html = document.documentElement;
        if (theme && theme !== 'auto') {
            html.setAttribute(THEME_ATTRIBUTE, theme);
        } else {
            const systemPref = getSystemPreference();
            html.setAttribute(THEME_ATTRIBUTE, systemPref === 'dark' ? 'dark' : 'classic');
        }
    }

    let __systemMediaQuery = null;
    let __systemListenerAttached = false;
    function updateTheme() {
        const preference = loadPreference();
        if (!preference) {
            // אין העדפה שמורה — נכבד את ערך השרת/HTML
            return;
        }
        if (preference === 'auto') {
            applyTheme('auto');
            if (window.matchMedia) {
                if (!__systemMediaQuery) {
                    __systemMediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
                }
                if (!__systemListenerAttached && __systemMediaQuery) {
                    const handler = () => applyTheme('auto');
                    try { __systemMediaQuery.addEventListener('change', handler); } catch(_) {}
                    __systemListenerAttached = true;
                }
            }
        } else {
            applyTheme(preference);
        }
    }

    function toggleDarkMode() {
        const current = loadPreference();
        let next;
        switch (current) {
            case 'auto': next = 'dark'; break;
            case 'dark': next = 'dim'; break;
            case 'dim': next = 'light'; break;
            case 'light':
            default: next = 'auto'; break;
        }
        savePreference(next);
        if (loadPreference()) { updateTheme(); }
        updateToggleButton(next);
        syncToServer(next);
    }

    function updateToggleButton(mode) {
        const toggleBtn = document.getElementById('darkModeToggle');
        const icon = document.getElementById('darkModeIcon');
        const text = toggleBtn?.querySelector('.btn-text');
        if (!toggleBtn || !icon) return;
        const icons = {
            'auto': 'fa-adjust', 'dark': 'fa-moon', 'dim': 'fa-cloud-moon', 'light': 'fa-sun',
            'classic': 'fa-code', 'ocean': 'fa-water', 'forest': 'fa-tree',
            'rose-pine-dawn': 'fa-seedling', 'nebula': 'fa-meteor', 'high-contrast': 'fa-eye'
        };
        const labels = {
            'auto': 'אוטומטי', 'dark': 'חשוך', 'dim': 'מעומעם', 'light': 'בהיר',
            'classic': 'קלאסי', 'ocean': 'אוקיינוס', 'forest': 'יער',
            'rose-pine-dawn': 'Rose Pine', 'nebula': 'Nebula', 'high-contrast': 'ניגודיות'
        };
        icon.className = 'fas ' + (icons[mode] || icons.auto);
        if (text) text.textContent = labels[mode] || labels.auto;
        toggleBtn.setAttribute('title', `מצב: ${labels[mode] || labels.auto}`);
    }

    async function syncToServer(theme) {
        try {
            let themeName = theme;
            if (theme === 'auto') {
                themeName = getSystemPreference() === 'dark' ? 'dark' : 'classic';
            } else if (theme === 'light') {
                themeName = 'classic';
            }
            await fetch('/api/ui_prefs', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ theme: themeName })
            });
        } catch (e) {
            console.warn('Failed to sync theme to server:', e);
        }
    }

    function init() {
        if (loadPreference()) { updateTheme(); }
        const toggleBtn = document.getElementById('darkModeToggle');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', toggleDarkMode);
            const current = loadPreference() || (document.documentElement.getAttribute('data-theme') || 'classic');
            updateToggleButton(current);
        }
        const themeSelect = document.getElementById('themeSelect');
        if (themeSelect) {
            const preference = loadPreference();
            if (preference !== 'auto' && preference !== 'light') {
                const themeValue = preference === 'light' ? 'classic' : preference;
                if (themeSelect.querySelector(`option[value="${themeValue}"]`)) {
                    themeSelect.value = themeValue;
                }
            }
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    window.DarkMode = {
        toggle: toggleDarkMode,
        set: function(mode) {
            savePreference(mode);
            updateTheme();
            updateToggleButton(mode);
            syncToServer(mode);
        },
        get: loadPreference
    };
})();
