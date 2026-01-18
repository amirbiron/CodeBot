# מדריך מימוש: מודאל בחירת ערכת נושא מתפריט קיצורי הדרך

## 📋 סקירה כללית

מדריך זה מפרט כיצד להוסיף כפתור 🎨 לתפריט קיצורי הדרך (🚀) בנבאבר, שיפתח מודאל מעוצב לבחירת ערכת נושא מכל הסוגים הקיימים.

### התוצאה הסופית
- כפתור שישי בתפריט הקיצורים עם אייקון 🎨
- מודאל עם רשימה מאורגנת של ערכות:
  - **מובנות (Built-in)**: nebula, dark, dim, classic, ocean, high-contrast, rose-pine-dawn
  - **ציבוריות (Shared)**: ערכות שפורסמו ע"י מנהלים
  - **אישיות (Custom)**: ערכות שהמשתמש יצר או ייבא
  - **מיובאות (Imported)**: ערכות שיובאו מ-VS Code או JSON

---

## 🗂️ מבנה הקוד הקיים

### 1. תפריט קיצורי הדרך (base.html)

```html
<!-- שורות 1687-1715 -->
<div class="quick-access-menu">
    <button class="quick-access-toggle" onclick="toggleQuickAccess(event)" aria-label="תפריט קיצורי דרך" title="קיצורי דרך">
        <i class="fas fa-rocket"></i>
    </button>
    <div class="quick-access-dropdown" id="quickAccessDropdown">
        <a href="/upload" class="quick-access-item" title="צור קטע קוד חדש">
            <span class="qa-icon">➕</span>
            <span class="qa-label">צור קטע קוד חדש</span>
        </a>
        <button class="quick-access-item" onclick="openGlobalSearch()" title="חיפוש בכל הקבצים">
            <span class="qa-icon">🔍</span>
            <span class="qa-label">חיפוש גלובלי</span>
        </button>
        <a href="/files?category=favorites#results" class="quick-access-item" title="קבצים מועדפים">
            <span class="qa-icon">⭐</span>
            <span class="qa-label">מועדפים</span>
        </a>
        <button class="quick-access-item" onclick="toggleQuickAccess(event); navigateToWorkspace(); return false;" title="שולחן עבודה">
            <span class="qa-icon">🖥️</span>
            <span class="qa-label">שולחן עבודה</span>
        </button>
        <button class="quick-access-item" onclick="showRecentFiles()" title="קבצים שנפתחו לאחרונה">
            <span class="qa-icon">🕓</span>
            <span class="qa-label">נפתחו לאחרונה</span>
        </button>
        <!-- 🆕 הכפתור החדש יתווסף כאן -->
    </div>
</div>
```

### 2. API Endpoints קיימים

| Endpoint | Method | תיאור |
|----------|--------|-------|
| `/api/themes/list` | GET | רשימה משולבת של כל הערכות (built-in, shared, custom) |
| `/api/themes/presets` | GET | רשימת Presets זמינים |
| `/api/themes/<id>/activate` | POST | הפעלת ערכה אישית |
| `/api/themes/shared/<id>/apply` | POST | החלת ערכה ציבורית |
| `/api/themes/deactivate` | POST | חזרה לערכה רגילה (classic) |

### 3. סגנון Theme Wizard הקיים (להשראה)

הפרויקט כבר מכיל `#themeWizard` (שורות 1345-1486 ב-base.html) עם עיצוב מודרני שניתן להתבסס עליו.

---

## 📝 שלבי המימוש

### שלב 1: הוספת הכפתור ל-Dropdown

**קובץ:** `webapp/templates/base.html`

מצא את ה-comment `<!-- הוסר: כפתור הגדרות בתוך חלונית קיצורי הדרך -->` (שורה 1713) והוסף לפניו:

```html
<button class="quick-access-item" onclick="openThemePickerModal()" title="ערכת נושא">
    <span class="qa-icon">🎨</span>
    <span class="qa-label">ערכת נושא</span>
</button>
```

---

### שלב 2: הוספת ה-HTML של המודאל

**קובץ:** `webapp/templates/base.html`

הוסף לפני סגירת `</body>` (או אחרי `#themeWizard`):

```html
<!-- Theme Picker Modal -->
<div id="themePickerModal" class="theme-picker-modal" role="dialog" aria-modal="true" aria-hidden="true" aria-labelledby="themePickerTitle">
  <div class="theme-picker__backdrop" data-theme-picker-dismiss></div>
  <div class="theme-picker__dialog">
    <button type="button" class="theme-picker__close" data-action="close-picker" aria-label="סגור בוחר ערכות נושא">
      <i class="fas fa-times"></i>
    </button>
    
    <div class="theme-picker__header">
      <h2 id="themePickerTitle" class="theme-picker__title">
        <span class="theme-picker__icon">🎨</span>
        בחר ערכת נושא
      </h2>
      <p class="theme-picker__subtitle">בחר מתוך הערכות המובנות, הציבוריות או האישיות שלך</p>
    </div>
    
    <!-- Filter Tabs -->
    <div class="theme-picker__tabs" role="tablist">
      <button type="button" class="theme-picker__tab active" data-filter="all" role="tab" aria-selected="true">
        <i class="fas fa-th-large"></i> הכל
      </button>
      <button type="button" class="theme-picker__tab" data-filter="builtin" role="tab" aria-selected="false">
        <i class="fas fa-cube"></i> מובנות
      </button>
      <button type="button" class="theme-picker__tab" data-filter="shared" role="tab" aria-selected="false">
        <i class="fas fa-globe"></i> ציבוריות
      </button>
      <button type="button" class="theme-picker__tab" data-filter="custom" role="tab" aria-selected="false">
        <i class="fas fa-user"></i> אישיות
      </button>
    </div>
    
    <!-- Themes Grid -->
    <div class="theme-picker__grid" id="themePickerGrid" role="listbox" aria-label="רשימת ערכות נושא">
      <!-- Themes will be loaded dynamically -->
      <div class="theme-picker__loading">
        <i class="fas fa-spinner fa-spin"></i>
        <span>טוען ערכות...</span>
      </div>
    </div>
    
    <!-- Current Theme Indicator -->
    <div class="theme-picker__current">
      <span class="theme-picker__current-label">ערכה נוכחית:</span>
      <span class="theme-picker__current-name" id="currentThemeName">--</span>
    </div>
    
    <!-- Actions -->
    <div class="theme-picker__actions">
      <a href="/settings#appearance" class="btn btn-secondary btn-sm">
        <i class="fas fa-cog"></i> הגדרות מתקדמות
      </a>
      <button type="button" class="btn btn-outline-secondary btn-sm" data-action="close-picker">
        סגור
      </button>
    </div>
  </div>
</div>
```

---

### שלב 3: הוספת ה-CSS

**קובץ:** `webapp/templates/base.html` (בתוך `<style>` הקיים) או קובץ CSS נפרד

```css
/* ========================================
   Theme Picker Modal Styles
   ======================================== */

body.theme-picker-open {
    overflow: hidden;
}

#themePickerModal {
    position: fixed;
    inset: 0;
    display: none;
    align-items: center;
    justify-content: center;
    z-index: 15000;
    padding: 1rem;
}

#themePickerModal.is-open {
    display: flex;
}

.theme-picker__backdrop {
    position: absolute;
    inset: 0;
    background: rgba(7, 12, 24, 0.65);
    backdrop-filter: blur(8px);
}

.theme-picker__dialog {
    position: relative;
    width: min(720px, 95%);
    max-height: 85vh;
    background: var(--card-bg, rgba(15, 23, 42, 0.96));
    color: var(--text-primary, #f8fafc);
    border-radius: 24px;
    padding: 1.75rem 2rem 2rem;
    border: 1px solid var(--glass-border, rgba(255, 255, 255, 0.2));
    box-shadow: 0 25px 50px rgba(3, 6, 23, 0.5);
    display: flex;
    flex-direction: column;
    overflow: hidden;
}

/* התאמה לערכות בהירות */
:root[data-theme="rose-pine-dawn"] .theme-picker__dialog,
:root[data-theme="classic"] .theme-picker__dialog {
    background: rgba(250, 244, 237, 0.98);
    color: var(--text-primary, #433c59);
    border-color: rgba(144, 122, 169, 0.3);
}

.theme-picker__close {
    position: absolute;
    top: 1rem;
    left: 1rem;
    border: none;
    background: rgba(255, 255, 255, 0.1);
    color: inherit;
    font-size: 1.1rem;
    width: 36px;
    height: 36px;
    border-radius: 50%;
    cursor: pointer;
    transition: all 0.2s ease;
    display: flex;
    align-items: center;
    justify-content: center;
}

.theme-picker__close:hover {
    background: rgba(255, 255, 255, 0.2);
    transform: scale(1.1);
}

.theme-picker__header {
    text-align: right;
    margin-bottom: 1.25rem;
}

.theme-picker__title {
    font-size: 1.5rem;
    margin: 0 0 0.5rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    justify-content: flex-end;
}

.theme-picker__icon {
    font-size: 1.3rem;
}

.theme-picker__subtitle {
    margin: 0;
    color: var(--text-secondary, rgba(255, 255, 255, 0.75));
    font-size: 0.95rem;
}

/* Tabs */
.theme-picker__tabs {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 1.25rem;
    flex-wrap: wrap;
    justify-content: flex-end;
}

.theme-picker__tab {
    padding: 0.5rem 1rem;
    border: 1px solid rgba(255, 255, 255, 0.15);
    background: rgba(255, 255, 255, 0.05);
    color: var(--text-secondary, rgba(255, 255, 255, 0.7));
    border-radius: 10px;
    cursor: pointer;
    transition: all 0.2s ease;
    font-size: 0.9rem;
    display: flex;
    align-items: center;
    gap: 0.4rem;
}

.theme-picker__tab:hover {
    background: rgba(255, 255, 255, 0.1);
    border-color: rgba(255, 255, 255, 0.25);
}

.theme-picker__tab.active {
    background: var(--primary, #7c3aed);
    border-color: var(--primary, #7c3aed);
    color: #fff;
}

/* Grid */
.theme-picker__grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 0.875rem;
    overflow-y: auto;
    max-height: 45vh;
    padding: 0.25rem;
    margin: 0 -0.25rem;
}

.theme-picker__grid::-webkit-scrollbar {
    width: 6px;
}

.theme-picker__grid::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.2);
    border-radius: 3px;
}

/* Theme Card */
.theme-picker__card {
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 14px;
    padding: 1rem;
    cursor: pointer;
    transition: all 0.2s ease;
    text-align: right;
    position: relative;
}

.theme-picker__card:hover {
    transform: translateY(-3px);
    border-color: rgba(255, 255, 255, 0.3);
    background: rgba(255, 255, 255, 0.1);
    box-shadow: 0 8px 20px rgba(0, 0, 0, 0.15);
}

.theme-picker__card.is-active {
    border-color: var(--primary, #7c3aed);
    background: rgba(124, 58, 237, 0.15);
}

.theme-picker__card.is-active::after {
    content: '✓';
    position: absolute;
    top: 0.5rem;
    left: 0.5rem;
    width: 22px;
    height: 22px;
    background: var(--primary, #7c3aed);
    color: #fff;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.75rem;
    font-weight: bold;
}

/* Color Preview */
.theme-picker__preview {
    display: flex;
    gap: 4px;
    margin-bottom: 0.75rem;
    height: 24px;
    border-radius: 6px;
    overflow: hidden;
}

.theme-picker__preview-color {
    flex: 1;
    min-width: 0;
}

.theme-picker__name {
    font-weight: 600;
    font-size: 0.95rem;
    margin-bottom: 0.25rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.theme-picker__type {
    font-size: 0.75rem;
    color: var(--text-muted, rgba(255, 255, 255, 0.5));
    display: flex;
    align-items: center;
    gap: 0.3rem;
    justify-content: flex-end;
}

.theme-picker__type i {
    font-size: 0.7rem;
}

/* Loading State */
.theme-picker__loading {
    grid-column: 1 / -1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0.75rem;
    padding: 3rem;
    color: var(--text-secondary);
}

.theme-picker__loading i {
    font-size: 1.5rem;
}

/* Empty State */
.theme-picker__empty {
    grid-column: 1 / -1;
    text-align: center;
    padding: 2rem;
    color: var(--text-muted);
}

/* Current Theme */
.theme-picker__current {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 0.5rem;
    margin-top: 1rem;
    padding-top: 1rem;
    border-top: 1px solid rgba(255, 255, 255, 0.1);
    font-size: 0.9rem;
}

.theme-picker__current-label {
    color: var(--text-muted);
}

.theme-picker__current-name {
    font-weight: 600;
    color: var(--primary, #7c3aed);
}

/* Actions */
.theme-picker__actions {
    display: flex;
    gap: 0.75rem;
    margin-top: 1rem;
    justify-content: flex-end;
}

/* Responsive */
@media (max-width: 640px) {
    .theme-picker__dialog {
        padding: 1.25rem 1rem 1.5rem;
        max-height: 90vh;
    }
    
    .theme-picker__title {
        font-size: 1.25rem;
    }
    
    .theme-picker__grid {
        grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
        gap: 0.625rem;
    }
    
    .theme-picker__tabs {
        gap: 0.375rem;
    }
    
    .theme-picker__tab {
        padding: 0.4rem 0.75rem;
        font-size: 0.8rem;
    }
}
```

---

### שלב 4: הוספת ה-JavaScript

**קובץ:** `webapp/templates/base.html` (בתוך `<script>` הקיים) או קובץ JS נפרד

```javascript
/**
 * Theme Picker Modal
 * מודאל בחירת ערכות נושא מתפריט קיצורי הדרך
 */
(function initThemePicker() {
    'use strict';

    const modalEl = document.getElementById('themePickerModal');
    if (!modalEl) return;

    // State
    let allThemes = [];
    let currentFilter = 'all';
    let isLoading = false;
    let currentActiveTheme = null;

    // DOM Elements
    const gridEl = document.getElementById('themePickerGrid');
    const currentNameEl = document.getElementById('currentThemeName');
    const backdropEl = modalEl.querySelector('[data-theme-picker-dismiss]');
    const closeBtn = modalEl.querySelector('[data-action="close-picker"]');
    const closeBtnFooter = modalEl.querySelector('.theme-picker__actions [data-action="close-picker"]');
    const tabBtns = modalEl.querySelectorAll('.theme-picker__tab');

    // ערכות מובנות (Built-in) עם צבעים לתצוגה מקדימה
    const BUILTIN_THEMES = [
        { id: 'nebula', name: 'Nebula', type: 'builtin', emoji: '🌌', colors: ['#1a1b26', '#7aa2f7', '#bb9af7', '#f7768e'] },
        { id: 'dark', name: 'Dark', type: 'builtin', emoji: '🌙', colors: ['#1e1e2e', '#cdd6f4', '#89b4fa', '#f38ba8'] },
        { id: 'dim', name: 'Dim', type: 'builtin', emoji: '🌆', colors: ['#2d2d3a', '#e0e0e0', '#8ab4f8', '#f28b82'] },
        { id: 'classic', name: 'Classic', type: 'builtin', emoji: '🏛️', colors: ['#ffffff', '#333333', '#667eea', '#48bb78'] },
        { id: 'ocean', name: 'Ocean', type: 'builtin', emoji: '🌊', colors: ['#0d1b2a', '#e0e1dd', '#3d5a80', '#ee6c4d'] },
        { id: 'high-contrast', name: 'High Contrast', type: 'builtin', emoji: '⚫️', colors: ['#000000', '#ffffff', '#ffcc00', '#00ff00'] },
        { id: 'rose-pine-dawn', name: 'Rose Pine Dawn', type: 'builtin', emoji: '🌹', colors: ['#faf4ed', '#575279', '#907aa9', '#d7827e'] }
    ];

    /**
     * פתיחת המודאל
     */
    function open() {
        modalEl.classList.add('is-open');
        modalEl.setAttribute('aria-hidden', 'false');
        document.body.classList.add('theme-picker-open');
        
        // סגור את תפריט הקיצורים
        const quickDropdown = document.getElementById('quickAccessDropdown');
        const quickToggle = document.querySelector('.quick-access-toggle');
        if (quickDropdown) quickDropdown.classList.remove('active');
        if (quickToggle) quickToggle.classList.remove('active');
        
        // טען ערכות אם עדיין לא נטענו
        if (allThemes.length === 0) {
            loadThemes();
        } else {
            renderThemes();
        }
        
        // זיהוי ערכה נוכחית
        detectCurrentTheme();
    }

    /**
     * סגירת המודאל
     */
    function close() {
        modalEl.classList.remove('is-open');
        modalEl.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('theme-picker-open');
    }

    /**
     * טעינת כל הערכות מה-API
     */
    async function loadThemes() {
        if (isLoading) return;
        isLoading = true;
        
        gridEl.innerHTML = `
            <div class="theme-picker__loading">
                <i class="fas fa-spinner fa-spin"></i>
                <span>טוען ערכות...</span>
            </div>
        `;

        try {
            // טען ערכות מה-API
            const response = await fetch('/api/themes/list', {
                headers: { 'Accept': 'application/json' }
            });
            
            if (!response.ok) throw new Error('Failed to load themes');
            
            const data = await response.json();
            
            if (data.ok && Array.isArray(data.themes)) {
                // מיזוג עם ערכות מובנות
                allThemes = [...BUILTIN_THEMES];
                
                // הוסף ערכות מה-API (shared + custom)
                data.themes.forEach(theme => {
                    // בדוק שזו לא ערכה מובנית כפולה
                    const isBuiltin = BUILTIN_THEMES.some(b => b.id === theme.id || b.id === theme.slug);
                    if (!isBuiltin) {
                        allThemes.push({
                            id: theme.id || theme.slug,
                            name: theme.name,
                            type: theme.type || (theme.source === 'shared' ? 'shared' : 'custom'),
                            colors: theme.preview_colors || theme.colors || [],
                            source: theme.source,
                            is_active: theme.is_active
                        });
                    }
                });
            }
            
            renderThemes();
        } catch (error) {
            console.error('Error loading themes:', error);
            gridEl.innerHTML = `
                <div class="theme-picker__empty">
                    <i class="fas fa-exclamation-triangle"></i>
                    <p>שגיאה בטעינת ערכות</p>
                    <button class="btn btn-sm btn-outline-primary" onclick="window.__themePicker.reload()">נסה שוב</button>
                </div>
            `;
        } finally {
            isLoading = false;
        }
    }

    /**
     * רינדור הערכות לפי הפילטר הנוכחי
     */
    function renderThemes() {
        let filtered = allThemes;
        
        if (currentFilter !== 'all') {
            filtered = allThemes.filter(t => t.type === currentFilter);
        }
        
        if (filtered.length === 0) {
            gridEl.innerHTML = `
                <div class="theme-picker__empty">
                    <i class="fas fa-palette"></i>
                    <p>אין ערכות בקטגוריה זו</p>
                </div>
            `;
            return;
        }
        
        gridEl.innerHTML = filtered.map(theme => {
            const isActive = isThemeActive(theme);
            const typeLabel = getTypeLabel(theme.type);
            const typeIcon = getTypeIcon(theme.type);
            const colors = getPreviewColors(theme);
            
            return `
                <div class="theme-picker__card ${isActive ? 'is-active' : ''}" 
                     role="option" 
                     aria-selected="${isActive}"
                     data-theme-id="${theme.id}"
                     data-theme-type="${theme.type}"
                     tabindex="0">
                    <div class="theme-picker__preview">
                        ${colors.map(c => `<div class="theme-picker__preview-color" style="background: ${c}"></div>`).join('')}
                    </div>
                    <div class="theme-picker__name">${theme.emoji || ''} ${theme.name}</div>
                    <div class="theme-picker__type">
                        <i class="${typeIcon}"></i>
                        ${typeLabel}
                    </div>
                </div>
            `;
        }).join('');
        
        // הוסף event listeners לכרטיסים
        gridEl.querySelectorAll('.theme-picker__card').forEach(card => {
            card.addEventListener('click', () => selectTheme(card.dataset.themeId, card.dataset.themeType));
            card.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    selectTheme(card.dataset.themeId, card.dataset.themeType);
                }
            });
        });
    }

    /**
     * קבלת צבעים לתצוגה מקדימה
     */
    function getPreviewColors(theme) {
        if (Array.isArray(theme.colors) && theme.colors.length > 0) {
            return theme.colors.slice(0, 4);
        }
        // צבעי ברירת מחדל
        return ['#1a1b26', '#7aa2f7', '#bb9af7', '#f7768e'];
    }

    /**
     * קבלת תווית סוג הערכה
     */
    function getTypeLabel(type) {
        const labels = {
            builtin: 'מובנית',
            shared: 'ציבורית',
            custom: 'אישית',
            imported: 'מיובאת'
        };
        return labels[type] || type;
    }

    /**
     * קבלת אייקון סוג הערכה
     */
    function getTypeIcon(type) {
        const icons = {
            builtin: 'fas fa-cube',
            shared: 'fas fa-globe',
            custom: 'fas fa-user',
            imported: 'fas fa-file-import'
        };
        return icons[type] || 'fas fa-palette';
    }

    /**
     * בדיקה האם ערכה פעילה
     */
    function isThemeActive(theme) {
        if (theme.is_active) return true;
        if (currentActiveTheme === theme.id) return true;
        
        // בדוק לפי data-theme על html
        const htmlTheme = document.documentElement.getAttribute('data-theme');
        return htmlTheme === theme.id;
    }

    /**
     * זיהוי הערכה הנוכחית
     */
    function detectCurrentTheme() {
        const htmlTheme = document.documentElement.getAttribute('data-theme') || 'nebula';
        currentActiveTheme = htmlTheme;
        
        // מצא את שם הערכה
        const theme = allThemes.find(t => t.id === htmlTheme);
        if (theme && currentNameEl) {
            currentNameEl.textContent = theme.name;
        } else if (currentNameEl) {
            currentNameEl.textContent = htmlTheme;
        }
    }

    /**
     * בחירת ערכה והחלתה
     */
    async function selectTheme(themeId, themeType) {
        if (!themeId) return;
        
        // הצג מצב טעינה על הכרטיס
        const card = gridEl.querySelector(`[data-theme-id="${themeId}"]`);
        if (card) {
            card.style.opacity = '0.7';
            card.style.pointerEvents = 'none';
        }
        
        try {
            let endpoint = '';
            let method = 'POST';
            
            if (themeType === 'builtin') {
                // עדכון ישיר של data-theme ושמירה ב-localStorage
                document.documentElement.setAttribute('data-theme', themeId);
                localStorage.setItem('user_theme', themeId);
                localStorage.setItem('dark_mode_preference', themeId);
                
                // עדכן בשרת (אופציונלי - אם יש endpoint)
                try {
                    await fetch('/api/user/preferences', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ theme: themeId })
                    });
                } catch (e) {
                    // best-effort
                }
                
                currentActiveTheme = themeId;
                renderThemes();
                detectCurrentTheme();
                showToast(`ערכת ${themeId} הופעלה!`, 'success');
                return;
            }
            
            if (themeType === 'shared') {
                endpoint = `/api/themes/shared/${themeId}/apply`;
            } else {
                // custom theme
                endpoint = `/api/themes/${themeId}/activate`;
            }
            
            const response = await fetch(endpoint, {
                method: method,
                headers: { 'Accept': 'application/json' }
            });
            
            const data = await response.json();
            
            if (data.ok || data.success) {
                currentActiveTheme = themeId;
                showToast('הערכה הופעלה בהצלחה!', 'success');
                
                // רענן את הדף כדי להחיל את הערכה
                setTimeout(() => {
                    window.location.reload();
                }, 500);
            } else {
                throw new Error(data.error || data.message || 'Failed to apply theme');
            }
        } catch (error) {
            console.error('Error applying theme:', error);
            showToast('שגיאה בהחלת הערכה', 'error');
        } finally {
            if (card) {
                card.style.opacity = '';
                card.style.pointerEvents = '';
            }
        }
    }

    /**
     * הצגת Toast
     */
    function showToast(message, type = 'info') {
        // נסה להשתמש ב-toast קיים
        if (window.showNotification) {
            window.showNotification(message, type);
            return;
        }
        
        // fallback פשוט
        const toast = document.createElement('div');
        toast.className = `simple-toast simple-toast--${type}`;
        toast.textContent = message;
        toast.style.cssText = `
            position: fixed;
            bottom: 2rem;
            left: 50%;
            transform: translateX(-50%);
            padding: 0.75rem 1.5rem;
            background: ${type === 'success' ? '#10b981' : type === 'error' ? '#ef4444' : '#3b82f6'};
            color: white;
            border-radius: 8px;
            z-index: 20000;
            font-size: 0.9rem;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        `;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 3000);
    }

    // === Event Listeners ===
    
    // סגירה בלחיצה על backdrop
    if (backdropEl) {
        backdropEl.addEventListener('click', close);
    }
    
    // כפתורי סגירה
    if (closeBtn) closeBtn.addEventListener('click', close);
    if (closeBtnFooter) closeBtnFooter.addEventListener('click', close);
    
    // סגירה ב-Escape
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && modalEl.classList.contains('is-open')) {
            close();
        }
    });
    
    // טאבים לסינון
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            currentFilter = btn.dataset.filter || 'all';
            tabBtns.forEach(b => {
                b.classList.toggle('active', b === btn);
                b.setAttribute('aria-selected', b === btn ? 'true' : 'false');
            });
            renderThemes();
        });
    });

    // === Public API ===
    window.__themePicker = {
        open: open,
        close: close,
        reload: loadThemes
    };
    
    // פונקציה גלובלית לפתיחה מהכפתור
    window.openThemePickerModal = open;

})();
```

---

## 🔌 אינטגרציה עם מערכת הערכות הקיימת

### מבנה התשובה מ-`/api/themes/list`

```json
{
    "ok": true,
    "themes": [
        {
            "id": "uuid-or-slug",
            "name": "Theme Name",
            "type": "shared|custom|builtin",
            "source": "manual|vscode|import|preset",
            "preview_colors": ["#color1", "#color2", "#color3", "#color4"],
            "is_active": false,
            "description": "תיאור אופציונלי"
        }
    ],
    "count": 15
}
```

### שילוב עם localStorage

המערכת הקיימת משתמשת ב-keys הבאים:
- `user_theme` - מזהה הערכה הנבחרת
- `dark_mode_preference` - העדפת מצב כהה/בהיר

המודאל מעדכן את שניהם בעת בחירת ערכה מובנית.

---

## 🧪 בדיקות

### בדיקות ידניות מומלצות

1. **פתיחה וסגירה:**
   - לחיצה על 🚀 ואז על 🎨
   - סגירה ב-X, בלחיצה על הרקע, וב-Escape

2. **טעינת ערכות:**
   - וודא שכל הסוגים מופיעים
   - בדוק סינון לפי קטגוריות

3. **החלת ערכה:**
   - בחר ערכה מובנית ← שינוי מיידי
   - בחר ערכה ציבורית ← רענון דף
   - בחר ערכה אישית ← רענון דף

4. **רספונסיביות:**
   - בדוק במובייל ובטאבלט
   - וודא שהגלילה עובדת

### טסטים אוטומטיים (לשקול)

```python
# tests/test_theme_picker_api.py

def test_themes_list_endpoint(client, auth_headers):
    """בדיקת endpoint רשימת הערכות"""
    response = client.get('/api/themes/list', headers=auth_headers)
    assert response.status_code == 200
    data = response.json
    assert data['ok'] is True
    assert 'themes' in data
    assert isinstance(data['themes'], list)
```

---

## 📁 קבצים לעריכה (סיכום)

| קובץ | סוג שינוי |
|------|-----------|
| `webapp/templates/base.html` | הוספת כפתור, HTML של מודאל, CSS, JavaScript |
| `webapp/static/css/theme-picker.css` | (אופציונלי) קובץ CSS נפרד |
| `webapp/static/js/theme-picker.js` | (אופציונלי) קובץ JS נפרד |

---

## 🎨 התאמות אופציונליות

### 1. הוספת אנימציה לכפתור

```css
.quick-access-item[title="ערכת נושא"] .qa-icon {
    animation: colorShift 3s infinite;
}

@keyframes colorShift {
    0%, 100% { filter: hue-rotate(0deg); }
    50% { filter: hue-rotate(180deg); }
}
```

### 2. תמיכה ב-Keyboard Navigation

```javascript
// הוסף ל-event listeners
gridEl.addEventListener('keydown', (e) => {
    const cards = Array.from(gridEl.querySelectorAll('.theme-picker__card'));
    const current = document.activeElement;
    const idx = cards.indexOf(current);
    
    if (e.key === 'ArrowRight' && idx > 0) {
        cards[idx - 1].focus();
    } else if (e.key === 'ArrowLeft' && idx < cards.length - 1) {
        cards[idx + 1].focus();
    }
});
```

### 3. שמירת מצב הפילטר

```javascript
// שמור את הפילטר ב-sessionStorage
function setFilter(filter) {
    currentFilter = filter;
    sessionStorage.setItem('theme_picker_filter', filter);
    renderThemes();
}

// שחזר בעת פתיחה
function restoreFilter() {
    const saved = sessionStorage.getItem('theme_picker_filter');
    if (saved) {
        currentFilter = saved;
        tabBtns.forEach(btn => {
            btn.classList.toggle('active', btn.dataset.filter === saved);
        });
    }
}
```

---

## ✅ צ'קליסט למימוש

- [ ] הוספת הכפתור 🎨 ל-quick-access-dropdown
- [ ] הוספת HTML של המודאל
- [ ] הוספת ה-CSS (inline או קובץ נפרד)
- [ ] הוספת ה-JavaScript
- [ ] בדיקת תאימות לערכות בהירות (classic, rose-pine-dawn)
- [ ] בדיקת רספונסיביות
- [ ] בדיקת נגישות (keyboard, aria)
- [ ] בדיקת אינטגרציה עם API הקיים

---

## 📚 קישורים רלוונטיים

- [GUIDES/custom_themes_guide.md](/workspace/GUIDES/custom_themes_guide.md) - מדריך ערכות מותאמות אישית
- [GUIDES/SHARED_THEME_LIBRARY_GUIDE.md](/workspace/GUIDES/SHARED_THEME_LIBRARY_GUIDE.md) - מדריך ספריית ערכות ציבוריות
- [webapp/themes_api.py](/workspace/webapp/themes_api.py) - ה-API של ערכות נושא
- [webapp/static/js/theme-importer.js](/workspace/webapp/static/js/theme-importer.js) - מייבא ערכות קיים
