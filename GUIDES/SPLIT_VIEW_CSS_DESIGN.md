# מדריך עיצוב: Split View למובייל וטאבלט 📱💻

> **תיאור**: מדריך CSS לעיצוב מצב עריכה מפוצל (Split Compose / Live Preview) במכשירים ניידים.
>
> **הקשר**: Feature מתוכנן להוספת תצוגה מקדימה בזמן אמת לצד העורך.
>
> **⚠️ שים לב**: מדריך זה מתמקד **רק בעיצוב** – לא במימוש הלוגיקה או ה-API.

---

## תוכן עניינים

- [Breakpoints קיימים בפרויקט](#breakpoints-קיימים-בפרויקט)
- [אסטרטגיית Layout](#אסטרטגיית-layout)
- [מבנה HTML מוצע](#מבנה-html-מוצע)
- [CSS Core – Split Container](#css-core--split-container)
- [CSS Mobile First](#css-mobile-first)
- [CSS Tablet](#css-tablet)
- [CSS Desktop](#css-desktop)
- [התאמה ל-Telegram Mini App](#התאמה-ל-telegram-mini-app)
- [RTL Support](#rtl-support)
- [אנימציות ומעברים](#אנימציות-ומעברים)
- [CSS Variables מומלצים](#css-variables-מומלצים)
- [נגישות (A11y)](#נגישות-a11y)
- [דוגמה מלאה](#דוגמה-מלאה)

---

## Breakpoints קיימים בפרויקט

הפרויקט משתמש ב-breakpoints הבאים (מ-`base.html`, `view_file.html`, `md_preview.html`):

| Breakpoint | שימוש עיקרי | הערות |
|------------|-------------|-------|
| `480px` | מובייל קטן | טלפונים צרים, Telegram Mini App |
| `520px` | מובייל בינוני | כפתורי upload |
| `600px` | מובייל רחב | סטטיסטיקות, טבלאות |
| `700px` | מובייל גדול / טאבלט קטן | פאנלים צרים |
| `768px` | **טאבלט** | **נקודת המעבר העיקרית** |
| `900px` | טאבלט רחב | Grid layouts |
| `1024px` | דסקטופ קטן | TOC, פאנלים צפים |

**המלצה ל-Split View**:
- `< 768px` → מצב **אנכי** (Tabs או Stacked)
- `≥ 768px` → מצב **אופקי** (Side-by-Side)

---

## אסטרטגיית Layout

### מובייל (< 768px)

```
┌─────────────────────┐
│      Toolbar        │  ← כפתור Toggle + מצב
├─────────────────────┤
│                     │
│    [Tab: עורך]      │  ← Tab אקטיבי
│   [Tab: תצוגה]      │
│                     │
├─────────────────────┤
│                     │
│                     │
│   תוכן Tab נבחר     │  ← גובה מלא
│                     │
│                     │
└─────────────────────┘
```

**אפשרות חלופית – Stacked**:
```
┌─────────────────────┐
│      עורך (50%)     │
├─────────────────────┤
│    תצוגה (50%)      │
└─────────────────────┘
```

### טאבלט ודסקטופ (≥ 768px)

```
┌───────────────┬───────────────┐
│               │               │
│    עורך       │    תצוגה      │
│    (50%)      │    (50%)      │
│               │               │
│               │               │
└───────────────┴───────────────┘
```

**עם Resizer**:
```
┌──────────┬─┬──────────┐
│          │░│          │
│  עורך    │░│  תצוגה   │
│          │░│          │
└──────────┴─┴──────────┘
           ↑
        Resizer (גרירה)
```

---

## מבנה HTML מוצע

```html
<!-- Container ראשי -->
<div class="split-view" data-mode="side-by-side">
  
  <!-- Toolbar -->
  <div class="split-toolbar">
    <button class="split-toggle" aria-pressed="true" aria-label="מצב מפוצל">
      <i class="fas fa-columns"></i>
      <span class="split-toggle__text">Live Preview</span>
    </button>
    <div class="split-tabs" role="tablist">
      <button role="tab" aria-selected="true" data-panel="editor">עורך</button>
      <button role="tab" aria-selected="false" data-panel="preview">תצוגה</button>
    </div>
  </div>
  
  <!-- Panels Container -->
  <div class="split-panels">
    
    <!-- Editor Panel -->
    <div class="split-panel split-panel--editor" 
         id="panel-editor" 
         role="tabpanel"
         aria-label="עורך קוד">
      <div id="editorContainer">
        <!-- CodeMirror יוכנס כאן -->
      </div>
    </div>
    
    <!-- Resizer (רק בדסקטופ/טאבלט) -->
    <div class="split-resizer" 
         role="separator" 
         aria-orientation="vertical"
         aria-label="שנה גודל פאנלים"
         tabindex="0">
      <div class="split-resizer__handle"></div>
    </div>
    
    <!-- Preview Panel -->
    <div class="split-panel split-panel--preview" 
         id="panel-preview" 
         role="tabpanel"
         aria-label="תצוגה מקדימה">
      <div class="split-preview-content">
        <!-- iframe או div לרינדור -->
      </div>
    </div>
    
  </div>
</div>
```

---

## CSS Core – Split Container

```css
/* =============================================
   Split View – Core Styles
   ============================================= */

.split-view {
  --split-gap: 0;
  --split-resizer-width: 8px;
  --split-toolbar-height: 48px;
  --split-transition-duration: 0.25s;
  --split-editor-ratio: 0.5;  /* 50% ברירת מחדל */
  
  display: flex;
  flex-direction: column;
  height: calc(100vh - var(--navbar-height, 60px) - 2rem);
  min-height: 400px;
  position: relative;
}

/* Toolbar */
.split-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.5rem 0.75rem;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 8px 8px 0 0;
  min-height: var(--split-toolbar-height);
  flex-shrink: 0;
}

/* Toggle Button */
.split-toggle {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  background: rgba(100, 100, 255, 0.2);
  border: 1px solid rgba(100, 100, 255, 0.5);
  border-radius: 6px;
  color: #fff;
  font-size: 0.9rem;
  cursor: pointer;
  transition: background 0.2s ease, transform 0.15s ease;
}

.split-toggle:hover {
  background: rgba(100, 100, 255, 0.3);
}

.split-toggle:active {
  transform: scale(0.97);
}

.split-toggle[aria-pressed="true"] {
  background: rgba(100, 255, 100, 0.2);
  border-color: rgba(100, 255, 100, 0.5);
}

/* Tabs (מובייל בלבד) */
.split-tabs {
  display: none;  /* מוסתר בדסקטופ */
  gap: 0;
  background: rgba(255, 255, 255, 0.08);
  border-radius: 6px;
  overflow: hidden;
}

.split-tabs [role="tab"] {
  padding: 0.5rem 1rem;
  background: transparent;
  border: none;
  color: rgba(255, 255, 255, 0.7);
  font-size: 0.85rem;
  cursor: pointer;
  transition: background 0.2s ease, color 0.2s ease;
}

.split-tabs [role="tab"][aria-selected="true"] {
  background: rgba(255, 255, 255, 0.15);
  color: #fff;
}

.split-tabs [role="tab"]:hover:not([aria-selected="true"]) {
  background: rgba(255, 255, 255, 0.08);
}

/* Panels Container */
.split-panels {
  display: flex;
  flex: 1;
  min-height: 0;  /* חשוב ל-flexbox overflow */
  overflow: hidden;
  border-radius: 0 0 8px 8px;
}

/* Individual Panel */
.split-panel {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.05);
  transition: flex 0.2s ease;
}

.split-panel--editor {
  flex: var(--split-editor-ratio);
}

.split-panel--preview {
  flex: calc(1 - var(--split-editor-ratio));
}

/* Editor Container */
.split-panel--editor #editorContainer {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.split-panel--editor .cm-editor {
  flex: 1;
  max-height: none;  /* Override default max-height */
}

/* Preview Content */
.split-preview-content {
  flex: 1;
  overflow: auto;
  background: #ffffff;
  color: #111111;
}

/* Preview iframe */
.split-preview-content iframe {
  width: 100%;
  height: 100%;
  border: none;
}

/* Resizer */
.split-resizer {
  flex-shrink: 0;
  width: var(--split-resizer-width);
  background: rgba(255, 255, 255, 0.1);
  cursor: col-resize;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s ease;
  touch-action: none;  /* מניעת scroll בזמן גרירה */
}

.split-resizer:hover,
.split-resizer:focus {
  background: rgba(100, 100, 255, 0.3);
}

.split-resizer:active,
.split-resizer.is-dragging {
  background: rgba(100, 100, 255, 0.5);
}

.split-resizer__handle {
  width: 4px;
  height: 40px;
  background: rgba(255, 255, 255, 0.3);
  border-radius: 2px;
  transition: background 0.2s ease;
}

.split-resizer:hover .split-resizer__handle,
.split-resizer:focus .split-resizer__handle {
  background: rgba(255, 255, 255, 0.6);
}

/* Focus Styles */
.split-resizer:focus {
  outline: 2px solid rgba(100, 100, 255, 0.5);
  outline-offset: -2px;
}

.split-resizer:focus:not(:focus-visible) {
  outline: none;
}
```

---

## CSS Mobile First

```css
/* =============================================
   Mobile (< 768px) – Tabbed/Stacked Layout
   ============================================= */

@media (max-width: 767px) {
  .split-view {
    --split-toolbar-height: 44px;
    height: calc(100vh - var(--navbar-height, 56px) - 1rem);
    height: calc(100dvh - var(--navbar-height, 56px) - 1rem);  /* Dynamic viewport */
  }
  
  .split-toolbar {
    flex-wrap: wrap;
    padding: 0.4rem 0.5rem;
    gap: 0.5rem;
  }
  
  .split-toggle {
    padding: 0.4rem 0.75rem;
    font-size: 0.85rem;
  }
  
  .split-toggle__text {
    display: none;  /* הסתר טקסט, השאר רק אייקון */
  }
  
  /* הצג Tabs במובייל */
  .split-tabs {
    display: flex;
    flex: 1;
    justify-content: center;
  }
  
  .split-tabs [role="tab"] {
    flex: 1;
    text-align: center;
    padding: 0.4rem 0.75rem;
  }
  
  /* Panels – Stacked או Tabbed */
  .split-panels {
    flex-direction: column;
  }
  
  /* ========== אפשרות 1: Tabbed Mode ========== */
  .split-view[data-mode="tabs"] .split-panel {
    position: absolute;
    inset: 0;
    top: var(--split-toolbar-height);
    opacity: 0;
    visibility: hidden;
    transition: opacity 0.2s ease, visibility 0.2s ease;
  }
  
  .split-view[data-mode="tabs"] .split-panel.is-active {
    position: relative;
    opacity: 1;
    visibility: visible;
    flex: 1;
  }
  
  /* ========== אפשרות 2: Stacked Mode ========== */
  .split-view[data-mode="stacked"] .split-panel {
    flex: 1;
    min-height: 0;
  }
  
  .split-view[data-mode="stacked"] .split-panel--editor {
    flex: 1;
    max-height: 45vh;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  }
  
  .split-view[data-mode="stacked"] .split-panel--preview {
    flex: 1;
  }
  
  /* הסתר Resizer במובייל */
  .split-resizer {
    display: none;
  }
  
  /* CodeMirror adjustments */
  .split-panel--editor .cm-editor {
    max-height: 100%;
    font-size: 14px;
  }
  
  /* Preview – מותאם לגובה */
  .split-preview-content {
    min-height: 200px;
  }
}

/* מובייל קטן מאוד */
@media (max-width: 480px) {
  .split-toolbar {
    padding: 0.35rem;
  }
  
  .split-toggle {
    padding: 0.35rem 0.6rem;
  }
  
  .split-tabs [role="tab"] {
    font-size: 0.8rem;
    padding: 0.35rem 0.5rem;
  }
}
```

---

## CSS Tablet

```css
/* =============================================
   Tablet (768px - 1023px) – Side-by-Side
   ============================================= */

@media (min-width: 768px) and (max-width: 1023px) {
  .split-view {
    height: calc(100vh - var(--navbar-height, 60px) - 1.5rem);
  }
  
  /* הסתר Tabs בטאבלט */
  .split-tabs {
    display: none;
  }
  
  /* Panels – אופקי */
  .split-panels {
    flex-direction: row;
  }
  
  .split-panel {
    flex: 1;
  }
  
  /* הצג Resizer */
  .split-resizer {
    display: flex;
    width: 6px;
  }
  
  /* Preview Content */
  .split-preview-content {
    padding: 1rem;
  }
  
  /* CodeMirror */
  .split-panel--editor .cm-editor {
    max-height: none;
    min-height: 100%;
  }
}
```

---

## CSS Desktop

```css
/* =============================================
   Desktop (≥ 1024px) – Full Side-by-Side
   ============================================= */

@media (min-width: 1024px) {
  .split-view {
    height: calc(100vh - var(--navbar-height, 60px) - 2rem);
    max-width: 1800px;
    margin: 0 auto;
  }
  
  .split-toolbar {
    padding: 0.65rem 1rem;
  }
  
  .split-toggle__text {
    display: inline;  /* הצג טקסט בדסקטופ */
  }
  
  /* Resizer רחב יותר לגרירה נוחה */
  .split-resizer {
    width: var(--split-resizer-width);
  }
  
  /* Preview Content */
  .split-preview-content {
    padding: 1.5rem;
  }
  
  /* Keyboard shortcut hint */
  .split-toolbar::after {
    content: 'Ctrl+Shift+Enter';
    font-size: 0.75rem;
    opacity: 0.6;
    padding: 0.25rem 0.5rem;
    background: rgba(255, 255, 255, 0.08);
    border-radius: 4px;
    font-family: monospace;
  }
}

/* דסקטופ רחב */
@media (min-width: 1400px) {
  .split-view {
    --split-resizer-width: 10px;
  }
  
  .split-preview-content {
    padding: 2rem;
  }
}
```

---

## התאמה ל-Telegram Mini App

```css
/* =============================================
   Telegram Mini App – Special Adjustments
   ============================================= */

/* Telegram Mini App detection מתבצע ב-base.html:
   if (window.Telegram && window.Telegram.WebApp) {
     document.body.classList.add('telegram-mini-app');
   }
*/

body.telegram-mini-app .split-view {
  /* גובה מותאם לחלון Telegram */
  height: calc(100vh - 48px);
  height: calc(100dvh - 48px);
  margin: 0;
  border-radius: 0;
}

body.telegram-mini-app .split-toolbar {
  padding: 0.35rem 0.5rem;
  border-radius: 0;
  background: rgba(255, 255, 255, 0.03);
}

body.telegram-mini-app .split-toggle {
  padding: 0.35rem 0.6rem;
  font-size: 0.8rem;
}

body.telegram-mini-app .split-panels {
  border-radius: 0;
}

body.telegram-mini-app .split-panel {
  background: rgba(255, 255, 255, 0.02);
}

/* במובייל Telegram – תמיד Tabs */
@media (max-width: 767px) {
  body.telegram-mini-app .split-view {
    --split-toolbar-height: 40px;
  }
  
  body.telegram-mini-app .split-view[data-mode="stacked"] {
    /* אין מקום ל-stacked ב-Mini App, עבור ל-tabs */
  }
  
  body.telegram-mini-app .split-tabs [role="tab"] {
    font-size: 0.75rem;
    padding: 0.3rem 0.4rem;
  }
}

/* טאבלט ב-Telegram (landscape) */
@media (min-width: 768px) {
  body.telegram-mini-app .split-view {
    height: calc(100vh - 52px);
  }
  
  body.telegram-mini-app .split-resizer {
    width: 5px;
  }
}
```

---

## RTL Support

```css
/* =============================================
   RTL (Right-to-Left) Support
   ============================================= */

/* הפרויקט כבר מוגדר RTL ב-base.html:
   html { direction: rtl; }
*/

/* Panels order – לא משנה ב-RTL */
html[dir="rtl"] .split-panels {
  /* flex-direction נשאר row, הסדר מתהפך אוטומטית */
}

/* Resizer cursor */
html[dir="rtl"] .split-resizer {
  cursor: col-resize;  /* אותו cursor */
}

/* Toolbar alignment */
html[dir="rtl"] .split-toolbar {
  /* flex justify-content מתהפך אוטומטית */
}

/* Keyboard hint position */
html[dir="rtl"] .split-toolbar::after {
  margin-inline-start: auto;
  margin-inline-end: 0;
}

/* Editor – תמיד LTR (קוד) */
html[dir="rtl"] .split-panel--editor {
  direction: ltr;  /* קוד תמיד LTR */
}

html[dir="rtl"] .split-panel--editor .cm-editor {
  direction: ltr;
  text-align: left;
}

/* Preview – לפי התוכן */
html[dir="rtl"] .split-preview-content {
  direction: rtl;  /* Markdown בעברית */
}

/* אם התוכן קוד – LTR */
html[dir="rtl"] .split-preview-content[data-content-type="code"] {
  direction: ltr;
}
```

---

## אנימציות ומעברים

```css
/* =============================================
   Animations & Transitions
   ============================================= */

/* הגדרת משתנים */
:root {
  --split-transition-fast: 0.15s ease;
  --split-transition-normal: 0.25s ease;
  --split-transition-slow: 0.35s ease-out;
}

/* Toggle Animation */
.split-toggle {
  transition: 
    background var(--split-transition-fast),
    transform var(--split-transition-fast),
    box-shadow var(--split-transition-fast);
}

.split-toggle:active {
  transform: scale(0.97);
}

/* Panel Transitions */
.split-panel {
  transition: 
    flex var(--split-transition-normal),
    opacity var(--split-transition-normal);
}

/* Tab Switch Animation */
.split-view[data-mode="tabs"] .split-panel {
  transition: 
    opacity var(--split-transition-normal),
    visibility var(--split-transition-normal),
    transform var(--split-transition-normal);
  transform: translateY(10px);
}

.split-view[data-mode="tabs"] .split-panel.is-active {
  transform: translateY(0);
}

/* Resizer Feedback */
.split-resizer {
  transition: background var(--split-transition-fast);
}

.split-resizer.is-dragging {
  transition: none;  /* ביטול transition בזמן גרירה */
}

/* Preview Loading */
.split-preview-content.is-loading {
  opacity: 0.6;
  pointer-events: none;
}

.split-preview-content.is-loading::after {
  content: '';
  position: absolute;
  top: 50%;
  left: 50%;
  width: 24px;
  height: 24px;
  margin: -12px 0 0 -12px;
  border: 2px solid rgba(100, 100, 255, 0.3);
  border-top-color: rgba(100, 100, 255, 0.8);
  border-radius: 50%;
  animation: split-spinner 0.8s linear infinite;
}

@keyframes split-spinner {
  to { transform: rotate(360deg); }
}

/* Reduced Motion */
@media (prefers-reduced-motion: reduce) {
  .split-panel,
  .split-toggle,
  .split-resizer,
  .split-preview-content {
    transition: none !important;
    animation: none !important;
  }
  
  .split-view[data-mode="tabs"] .split-panel {
    transform: none;
  }
}
```

---

## CSS Variables מומלצים

```css
/* =============================================
   CSS Variables – הוסף ל-:root או base.html
   ============================================= */

:root {
  /* Split View Dimensions */
  --split-gap: 0;
  --split-resizer-width: 8px;
  --split-toolbar-height: 48px;
  --split-min-panel-width: 280px;
  --split-max-panel-ratio: 0.75;
  --split-min-panel-ratio: 0.25;
  
  /* Split View Colors */
  --split-bg: rgba(255, 255, 255, 0.05);
  --split-border: rgba(255, 255, 255, 0.1);
  --split-resizer-bg: rgba(255, 255, 255, 0.1);
  --split-resizer-hover: rgba(100, 100, 255, 0.3);
  --split-resizer-active: rgba(100, 100, 255, 0.5);
  --split-toggle-bg: rgba(100, 100, 255, 0.2);
  --split-toggle-active: rgba(100, 255, 100, 0.2);
  
  /* Timing */
  --split-transition-fast: 0.15s ease;
  --split-transition-normal: 0.25s ease;
}

/* Dark Theme Overrides */
[data-theme="dark"] {
  --split-bg: rgba(0, 0, 0, 0.2);
  --split-border: rgba(255, 255, 255, 0.08);
}

/* Rose Pine Dawn */
:root[data-theme="rose-pine-dawn"] {
  --split-bg: color-mix(in srgb, var(--bg-secondary) 70%, #ffffff 30%);
  --split-border: var(--glass-border);
  --split-toggle-bg: var(--bg-secondary);
  --split-resizer-bg: rgba(180, 99, 122, 0.1);
  --split-resizer-hover: rgba(180, 99, 122, 0.25);
}
```

---

## נגישות (A11y)

```css
/* =============================================
   Accessibility Enhancements
   ============================================= */

/* Focus Visible */
.split-toggle:focus-visible,
.split-tabs [role="tab"]:focus-visible {
  outline: 2px solid var(--primary, #9775fa);
  outline-offset: 2px;
}

/* Skip Link (אופציונלי) */
.split-skip-link {
  position: absolute;
  top: -100%;
  left: 0;
  padding: 0.5rem 1rem;
  background: var(--primary, #9775fa);
  color: #fff;
  z-index: 100;
  transition: top 0.2s ease;
}

.split-skip-link:focus {
  top: 0;
}

/* High Contrast Mode */
@media (prefers-contrast: high) {
  .split-resizer {
    background: #fff;
    border: 1px solid #000;
  }
  
  .split-toggle {
    border-width: 2px;
  }
  
  .split-tabs [role="tab"][aria-selected="true"] {
    border: 2px solid currentColor;
  }
}

/* Screen Reader Only */
.split-sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
```

---

## דוגמה מלאה

קובץ CSS מאוחד מוכן לשימוש:

```css
/* =============================================
   SPLIT VIEW – Complete Stylesheet
   File: webapp/static/css/split-view.css
   ============================================= */

/* ---------- Variables ---------- */
:root {
  --split-resizer-width: 8px;
  --split-toolbar-height: 48px;
  --split-editor-ratio: 0.5;
  --split-transition: 0.25s ease;
}

/* ---------- Core ---------- */
.split-view {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 60px - 2rem);
  min-height: 400px;
}

.split-toolbar {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.5rem 0.75rem;
  background: rgba(255,255,255,0.05);
  border-radius: 8px 8px 0 0;
  min-height: var(--split-toolbar-height);
}

.split-toggle {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  background: rgba(100,100,255,0.2);
  border: 1px solid rgba(100,100,255,0.5);
  border-radius: 6px;
  color: #fff;
  cursor: pointer;
}

.split-tabs { display: none; }

.split-panels {
  display: flex;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  border-radius: 0 0 8px 8px;
}

.split-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: rgba(255,255,255,0.05);
}

.split-resizer {
  width: var(--split-resizer-width);
  background: rgba(255,255,255,0.1);
  cursor: col-resize;
  display: flex;
  align-items: center;
  justify-content: center;
}

.split-resizer:hover { background: rgba(100,100,255,0.3); }

.split-preview-content {
  flex: 1;
  overflow: auto;
  background: #fff;
  color: #111;
  padding: 1rem;
}

/* ---------- Mobile < 768px ---------- */
@media (max-width: 767px) {
  .split-view { height: calc(100dvh - 56px - 1rem); }
  .split-toggle__text { display: none; }
  .split-tabs { display: flex; flex: 1; justify-content: center; }
  .split-tabs [role="tab"] { flex: 1; text-align: center; padding: 0.4rem; }
  .split-panels { flex-direction: column; }
  .split-resizer { display: none; }
  
  /* Tabs mode */
  .split-view[data-mode="tabs"] .split-panel { display: none; }
  .split-view[data-mode="tabs"] .split-panel.is-active { display: flex; flex: 1; }
}

/* ---------- Tablet 768-1023px ---------- */
@media (min-width: 768px) and (max-width: 1023px) {
  .split-panels { flex-direction: row; }
  .split-resizer { width: 6px; }
}

/* ---------- Desktop ≥ 1024px ---------- */
@media (min-width: 1024px) {
  .split-view { max-width: 1800px; margin: 0 auto; }
  .split-toggle__text { display: inline; }
}

/* ---------- Telegram Mini App ---------- */
body.telegram-mini-app .split-view {
  height: calc(100dvh - 48px);
  border-radius: 0;
}

/* ---------- RTL ---------- */
html[dir="rtl"] .split-panel--editor { direction: ltr; }

/* ---------- Reduced Motion ---------- */
@media (prefers-reduced-motion: reduce) {
  .split-panel, .split-toggle, .split-resizer { transition: none !important; }
}
```

---

## קבצים רלוונטיים בפרויקט

| קובץ | תיאור |
|------|-------|
| `webapp/templates/edit_file.html` | עמוד העריכה הנוכחי |
| `webapp/static/css/codemirror-custom.css` | סגנונות CodeMirror |
| `webapp/templates/md_preview.html` | תצוגת Markdown (לייבוא סגנונות) |
| `webapp/templates/html_preview.html` | תצוגת HTML (לייבוא סגנונות) |
| `webapp/templates/base.html` | breakpoints ו-Telegram detection |

---

## סיכום Checklist לעיצוב

- [ ] **Mobile (< 768px)**: Tabs או Stacked layout
- [ ] **Tablet (768-1023px)**: Side-by-side עם resizer צר
- [ ] **Desktop (≥ 1024px)**: Side-by-side מלא עם keyboard hint
- [ ] **Telegram Mini App**: התאמות גובה ו-padding
- [ ] **RTL**: Editor ב-LTR, Preview לפי תוכן
- [ ] **Reduced Motion**: ביטול אנימציות
- [ ] **High Contrast**: גבולות ברורים
- [ ] **Touch**: `touch-action: none` על resizer

---

## קישורים שימושיים

- [CSS Container Queries](https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_Container_Queries) – לעתיד
- [Dynamic Viewport Units](https://web.dev/viewport-units/) – `dvh` למובייל
- [Telegram Mini Apps](https://core.telegram.org/bots/webapps)
- [CodeMirror Styling](https://codemirror.net/docs/styling/)
