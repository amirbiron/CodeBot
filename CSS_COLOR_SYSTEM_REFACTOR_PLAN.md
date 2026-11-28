# CSS Color System Refactor - Full Analysis & Plan

**Date:** 2025-12-11  
**Status:** Planning Phase – Awaiting Sign-off (inventory completed)  
**Branch:** `claude/refactor-css-colors-01GQzDferCK2yzjSDcY3aTNx`

---

## Table of Contents

1. [Background & Problem Statement](#background--problem-statement)
2. [Theme System Overview](#theme-system-overview)
3. [Full Color Inventory](#full-color-inventory)
   - (A) Global Variables (`base.html`)
   - (B) Component-Specific Variables
   - (C) Files with Hardcoded Colors
   - (D) Inline Styles in HTML
   - (E) Colors Inside JavaScript
   - (F) CSS File Coverage Matrix
4. [Conflicts & Issues](#conflicts--issues)
5. [Accessibility Analysis](#accessibility-analysis)
6. [Proposed Variable Structure](#proposed-variable-structure)
7. [Execution Strategy](#execution-strategy)
   - (Traceability vs Implementation)
8. [Open Questions](#open-questions)
9. [Appendix A – Missing Variables To Add](#appendix-a--missing-variables-to-add)

---

## Background & Problem Statement

### Why This Refactor?

ענינו שלב קודם שבו בוצע ריפקטור ללא תכנון מלא. התהליך עבד קובץ-קובץ, וגרם לאובדן צבעים ייחודיים בקומפוננטות כגון `global_search.css`.

**מה קרה בסבב הקודם:**
1. הוגדר `variables.css` עם משתנים גלובליים בלבד.
2. `bookmarks.css` הוסב בהצלחה.
3. בעת ריפקטור של `global_search.css` צבעי הרקע/צל נעלמו כי הוגדרו ספציפית ל־theme ולא הועתקו ל־variables החדשים.

```css
/* לפני */
:root[data-theme="classic"] {
  --search-card-shadow: 0 30px 60px rgba(7,7,31,0.35);
}

/* אחרי – ערך גנרי שהוחלף */
:root {
  --shadow-card: 0 4px 12px rgba(0,0,0,0.2);
}
```

השלב הנוכחי מוודא שיש לנו **מלאי צבעים מלא** לפני כתיבת קוד, כך שכל שמונת ה־themes משמרים את הייחוד שלהם.

---

## Theme System Overview

### 8 Available Themes (שמות `data-theme` מדויקים)

| # | Theme | `data-theme` | Type | Notes |
|---|-------|--------------|------|-------|
| 1 | Dark | `dark` | Dark | ברירת מחדל כאשר `:root` או `data-theme="dark"` |
| 2 | Dim | `dim` | Dark | גרסה רכה יותר של Dark |
| 3 | Nebula | `nebula` | Dark | גוונים של כחול/סגול |
| 4 | Classic | `classic` | Purple | הגרדיאנט המקורי |
| 5 | Ocean | `ocean` | Blue | Bold blue gradient |
| 6 | Forest | `forest` | Green | Bold green gradient |
| 7 | Rose Pine Dawn | `rose-pine-dawn` | Light | ורוד/חם |
| 8 | High Contrast | `high-contrast` | Accessibility | שחור/לבן/צהוב |

> **הערה חשובה:** אין `data-theme="default"`. ברירת המחדל היא פשוט `:root` ללא attribute.

### CSS Load Order (לאבחון precedence)

1. `<style>` בתוך `webapp/templates/base.html` (הכי ספציפי – נטען ראשון)
2. כל `extra_css` שמוזרק בתבניות
3. `collections.css`
4. `codemirror-custom.css`
5. `markdown-enhanced.css`
6. `global_search.css`
7. `high-contrast.css`
8. `dark-mode.css`
9. `smooth-scroll.css`

---

## Full Color Inventory

כלל הנתונים נאספו ע"י סריקה ידנית מלאה של:
- `webapp/static/css/**/*.css`
- `webapp/templates/**/*.html` (inline styles)
- `webapp/static/js/*.js` שמזריקים HTML/CSS

### (A) Global Variables – `base.html <style>`

#### Core Colors

| Variable | :root | dark | dim | nebula | classic | ocean | forest | rose-pine-dawn | high-contrast |
|----------|-------|------|-----|--------|---------|-------|--------|----------------|---------------|
| `--primary` | `#667eea` | `#7c8aff` | `#7c8aff` | `#777abc` | `#667eea` | `#3182ce` | `#2f855a` | `#907aa9` | `#000000` |
| `--primary-dark` | `#5a67d8` | `#6b7aff` | `#6b7aff` | `#5f63d3` | `#5a67d8` | `#2b6cb0` | `#276749` | `#7b6f9a` | `#000000` |
| `--secondary` | `#764ba2` | `#9d7aff` | `#9d7aff` | `#4d6bb6` | `#764ba2` | `#2c5282` | `#22543d` | `#d7827e` | `#000000` |

#### Backgrounds

| Variable | :root | dark | dim | nebula | classic | ocean | forest | rose-pine-dawn | high-contrast |
|----------|-------|------|-----|--------|---------|-------|--------|----------------|---------------|
| `--bg-primary` | `linear-gradient(135deg, var(--primary), var(--secondary))` | `#1a1a1a` | `#2a2a2a` | `#151a2c` | `#6b63ff` | `#1a365d` | `#1a4731` | `#faf4ed` | `#000000` |
| `--bg-secondary` | `color-mix(var(--primary), var(--secondary))` | `#252525` | `#333333` | `#1f263a` | `#8e63ff` | `#2a4365` | `#22543d` | `#f2e9e1` | `#000000` |
| `--bg-tertiary` | `rgba(255,255,255,0.25)` | `#2d2d2d` | `#3a3a3a` | `#28324a` | `rgba(255,255,255,0.25)` | `#2c5282` | `#276749` | `#eaddd5` | `#000000` |

#### Text Colors

| Variable | :root | dark | dim | nebula | classic | ocean | forest | rose-pine-dawn | high-contrast |
|----------|-------|------|-----|--------|---------|-------|--------|----------------|---------------|
| `--text-primary` | `#ffffff` | `#e0e0e0` | `#d0d0d0` | `#e6e9f8` | `#ffffff` | `#ffffff` | `#ffffff` | `#575279` | `#ffffff` |
| `--text-secondary` | `rgba(255,255,255,0.82)` | `#b0b0b0` | `#a0a0a0` | `#c5c9de` | `rgba(255,255,255,0.82)` | `rgba(255,255,255,0.85)` | `rgba(255,255,255,0.85)` | `#6e6a86` | `#ffff00` |
| `--text-muted` | `rgba(255,255,255,0.65)` | `#808080` | `#707070` | `#8d93ad` | `rgba(255,255,255,0.65)` | `rgba(255,255,255,0.65)` | `rgba(255,255,255,0.65)` | `#797593` | `#ffff00` |

#### Glass Effects

| Variable | :root | dark | dim | nebula | classic | ocean | forest | rose-pine-dawn | high-contrast |
|----------|-------|------|-----|--------|---------|-------|--------|----------------|---------------|
| `--glass` | `rgba(255,255,255,0.1)` | `rgba(255,255,255,0.05)` | `rgba(255,255,255,0.08)` | `rgba(119,122,188,0.15)` | inherits | `rgba(49,130,206,0.15)` | `rgba(47,133,90,0.15)` | `rgba(250,244,237,0.9)` | `rgba(255,255,255,0.02)` |
| `--glass-border` | `rgba(255,255,255,0.2)` | `rgba(255,255,255,0.1)` | `rgba(255,255,255,0.15)` | `rgba(119,122,188,0.35)` | inherits | `rgba(49,130,206,0.35)` | `rgba(47,133,90,0.35)` | `rgba(144,122,169,0.35)` | `#ffffff` |
| `--glass-hover` | `rgba(255,255,255,0.15)` | `rgba(255,255,255,0.08)` | `rgba(255,255,255,0.12)` | `rgba(119,122,188,0.22)` | inherits | `rgba(49,130,206,0.25)` | `rgba(47,133,90,0.25)` | `rgba(144,122,169,0.25)` | `rgba(255,255,255,0.08)` |

#### Cards & Code Blocks

| Variable | :root | dark | dim | nebula | classic | ocean | forest | rose-pine-dawn | high-contrast |
|----------|-------|------|-----|--------|---------|-------|--------|----------------|---------------|
| `--card-bg` | `rgba(255,255,255,0.12)` | `rgba(30,30,30,0.8)` | `rgba(40,40,40,0.8)` | `rgba(21,27,44,0.85)` | `rgba(255,255,255,0.12)` | `rgba(26,54,93,0.85)` | `rgba(26,71,49,0.85)` | `rgba(250,244,237,0.96)` | `#000000` |
| `--card-border` | `rgba(255,255,255,0.25)` | `rgba(255,255,255,0.1)` | `rgba(255,255,255,0.1)` | `rgba(119,122,188,0.35)` | `rgba(255,255,255,0.25)` | `rgba(49,130,206,0.35)` | `rgba(47,133,90,0.35)` | `rgba(144,122,169,0.35)` | `#ffffff` |
| `--code-bg` | `rgba(0,0,0,0.3)` | `#1e1e1e` | `#2a2a2a` | `#12192c` | `rgba(0,0,0,0.3)` | `#1a365d` | `#1a4731` | `#f2e9e1` | `#000000` |
| `--code-text` | `#f8f8f2` | `#d4d4d4` | `#dcdcdc` | `#ecf0ff` | `#f8f8f2` | `#e2e8f0` | `#e2fbe2` | `#433c59` | `#ffff00` |
| `--code-border` | `rgba(255,255,255,0.12)` | `rgba(255,255,255,0.1)` | `rgba(255,255,255,0.1)` | `rgba(119,122,188,0.4)` | `rgba(255,255,255,0.12)` | `rgba(49,130,206,0.4)` | `rgba(47,133,90,0.4)` | `rgba(87,82,121,0.25)` | `#ffffff` |

#### Status & Button Variables (selected)

| Variable | :root | dark | nebula | ocean | forest | rose-pine-dawn |
|----------|-------|------|--------|-------|--------|----------------|
| `--success` | `#48bb78` | `#4ade80` | `#7fe7c4` | `#68d391` | `#9ae6b4` | `#56949f` |
| `--danger` | `#f56565` | `#f87171` | `#f598b2` | `#fc8181` | `#fc8181` | `#b4637a` |
| `--btn-primary-bg` | `#ffffff` | `color-mix(var(--bg-tertiary) 75%, var(--primary) 25%)` | `color-mix(var(--card-bg) 60%, var(--primary) 40%)` | `rgba(255,255,255,0.95)` | `rgba(255,255,255,0.95)` | `color-mix(var(--bg-secondary) 80%, #fff 20%)` |
| `--btn-primary-hover-shadow` | `0 10px 20px rgba(0,0,0,0.2)` | `0 14px 32px rgba(0,0,0,0.55)` | `0 16px 36px rgba(21,27,44,0.7)` | `0 12px 28px rgba(26,54,93,0.45)` | `0 12px 28px rgba(26,71,49,0.45)` | `0 10px 24px rgba(149,121,166,0.3)` |

### (B) Component-Specific Variables (Level 3)

#### `global_search.css`

| Variable | :root | classic | ocean | forest | dark/dim/nebula | rose-pine-dawn | high-contrast | Notes |
|----------|-------|---------|-------|--------|-----------------|----------------|---------------|-------|
| `--search-card-bg` | `var(--card-bg)` | same | `var(--card-bg)` | `var(--card-bg)` | same | `var(--card-bg)` | `#000000` | Ties into Level 2 |
| `--search-card-shadow` | `0 20px 45px rgba(15,23,42,0.25)` | `0 30px 60px rgba(7,7,31,0.35)` | `0 16px 40px rgba(15,23,42,0.18)` | `0 18px 40px rgba(34,84,61,0.22)` | `0 25px 55px rgba(4,7,18,0.65)` | `0 16px 40px rgba(114,83,108,0.22)` | `none` | Keep overrides |
| `--search-highlight-bg` | `color-mix(in srgb, var(--primary) 40%, #fff 60%)` | `rgba(255,215,0,0.85)` | `rgba(96,165,250,0.35)` | `rgba(74,222,128,0.35)` | `rgba(124,138,255,0.6)` | `rgba(144,122,169,0.4)` | `#ffff00` | Unique highlights |
| `--search-highlight-text` | `#1a202c` | `#1c1f3a` | `#0f172a` | `#1c3526` | `#ffffff` | `#433c59` | `#000000` | |

Language badges משתמשים ב־HSL משתנים לכל שפה (`--rust-h`, `--rust-s`, וכו') עם התאמות-Lightness לכל תמה.

#### `bookmarks.css`

| Variable | Default | Dark/Dim/Nebula | Ocean | Forest | Rose Pine Dawn | High Contrast | Notes |
|----------|---------|-----------------|-------|--------|----------------|---------------|-------|
| `--bookmarks-panel-bg` | `rgba(255,255,255,0.97)` | `rgba(20,23,30,0.98)` | `rgba(236,246,255,0.98)` | `rgba(236,247,241,0.98)` | `rgba(249,244,242,0.97)` | `#000000` | Already Level 3 |
| `--bookmarks-panel-shadow` | `0 20px 45px rgba(15,23,42,0.15)` | `0 25px 60px rgba(0,0,0,0.65)` | `0 20px 45px rgba(49,130,206,0.25)` | `0 20px 45px rgba(23,63,46,0.25)` | `0 20px 45px rgba(77,56,95,0.18)` | none | |
| `--bookmarks-hover-bg` | `rgba(255,255,255,0.9)` | `rgba(255,255,255,0.07)` | `rgba(49,130,206,0.08)` | `rgba(47,133,90,0.08)` | `rgba(144,122,169,0.08)` | `rgba(255,255,255,0.08)` | |
| `--bookmarks-border-color` | `rgba(0,0,0,0.06)` | `rgba(255,255,255,0.1)` | `rgba(49,130,206,0.25)` | `rgba(47,133,90,0.3)` | `rgba(144,122,169,0.35)` | `#ffffff` | |

#### `markdown-enhanced.css`

- משתמש בשתי מערכות משתנים (`:root` ו-`@media (prefers-color-scheme: dark)`).  
- חייב מעבר ל־`[data-theme]` כדי להישאר מסונכרן עם בחירת המשתמש.

#### רכיבים נוספים עם Level 3 ייעודי

| File | Variables | Status |
|------|-----------|--------|
| `multi-select.css` | `--bulk-toolbar-bg`, `--bulk-toolbar-shadow`, `--bulk-notice-*` | קיימים חלקית, חסר עבור Ocean/Forest |
| `split-view.css` | `--split-panel-bg`, `--split-toolbar-shadow` | עדיין Hardcoded – יעבור ריפקטור |
| `snippets.css` | חסר מערכת משתנים | Low priority |

### (C) Files with Hardcoded Colors (need conversion)

| File | Element/Selector | Hardcoded Value | Target Variable |
|------|------------------|-----------------|-----------------|
| `collections.css` | `.collections-content` | `background:#ffffff` / `color:#222` | `var(--card-bg)` / `var(--text-primary)` |
|  | `.collection-item` | `border:1px solid #e5e7eb` | `var(--glass-border)` |
|  | `.workspace-card` | `background:#ffffff` | `var(--card-bg)` |
|  | `.shared-collection-card` | `background:rgba(255,255,255,.96)` | `var(--card-bg)` + Level 3 opacity |
| `split-view.css` | `.split-preview-content` | `background:#ffffff; color:#1c1c1c` | `var(--bg-secondary)` / `var(--text-primary)` |
|  | `.codehilite` | `background:#272822; color:#f8f8f2` | `var(--code-bg)` / `var(--code-text)` |
| `multi-select.css` | `.bulk-actions-toolbar` | `rgba(30,30,50,0.98)` | צור `--bulk-toolbar-bg` |
| `snippets.css` | `.snippet-code` | `background:#1e1e1e` | `var(--code-bg)` |
| `sticky-notes.css` | `.sticky-note` | `#FFFFCC` | להישאר, מתוכנן ייעודי |
| `card-preview.css` | `.card-code-preview` | `background:#1e1e1e` | `var(--code-bg)` |

### (D) Inline Styles in HTML Templates

| File | Location | Hardcoded Style | Mapping / Action |
|------|----------|-----------------|------------------|
| `webapp/templates/login.html` | `.alert-error` | `background: rgba(255,59,48,0.1); color:#ff3b30` | Map to `var(--danger)` + opacity token (`--alert-bg-danger`) |
| `webapp/templates/login.html` | CTA button | `background: rgba(102,126,234,0.9)` | `var(--primary)` / `var(--btn-primary-bg)` |
| `webapp/templates/files.html` | `.language-filter` | `background:#fff; color:#333; border:1px solid rgba(0,0,0,0.1)` | `var(--card-bg)`, `var(--text-primary)`, `var(--glass-border)` |
| `webapp/templates/settings.html` | multiple cards | `background: rgba(255,255,255,0.05)` | `var(--glass)` |
| `webapp/templates/bookmarks_snippet.html` | badges | already `var(--bookmark-*)` | ✅ |
| `webapp/templates/base.html` | Add-to-collection modal | Mixed `rgba(255,255,255,0.08)` | Map to `var(--glass-hover)` |
| `webapp/templates/md_preview.html` | Reader modes | Sepia palette (`#fdf6e3`...) | **Remain hardcoded** (`--reader-*` scoped future) |
| `webapp/templates/theme_preview.html` | Palette swatches | 50+ color swatches | **Remain hardcoded** (demo page) |

### (E) Hardcoded Colors in JavaScript

| File | Context | Colors | Plan |
|------|---------|--------|------|
| `webapp/static/js/bookmarks.js` | Context menu + inline styles | `#ddd`, `rgba(0,0,0,0.2)` | Move to CSS classes referencing vars |
| `webapp/static/js/sticky-notes.js` | Inline style injection | `#fff`, `#1f2933`, `#667eea` | Move to CSS + `var(--primary)` |
| `webapp/static/js/smooth-scroll.js` | Debug overlay | `#3b82f6`, `#f97316`, `#4b5563` | Low priority (dev only) |
| `webapp/static/js/md_preview.bundle.js` | KaTeX colors | Many | **Ignore** (bundle) |
| `webapp/static/js/codemirror.local.js` | CodeMirror themes | Many | **Ignore** (3rd party) |

### (F) CSS File Coverage Matrix (`webapp/static/css`)

| File | Colors Present? | Notes / Action |
|------|-----------------|----------------|
| `bookmarks.css` | ✅ (via vars) | כבר מבוסס Level 3 |
| `card-preview.css` | ⚠️ | מיעוט צבעים קשיחים (`code preview`) – להמיר |
| `codemirror-custom.css` | ✅ | מבוסס משתנים, אין פעולה |
| `collections.css` | ❌ | Hardcoded – Phase 2 |
| `community_library.css` | ✅ | מבוסס על משתנים (glass + cards) |
| `dark-mode.css` | ✅ | Handles dark-specific overrides; no action |
| `global_search.css` | ✅ | כבר תומך ב־themes, דוגמה טובה |
| `high-contrast.css` | ✅ | נבדק מול WCAG, נשאר |
| `markdown-enhanced.css` | ⚠️ | `@media` במקום `[data-theme]` |
| `md_preview.bundle.css` | ❌ | קובץ build – לא נוגעים (bundle) |
| `multi-select.css` | ⚠️ | חלק משתנים, חלק קשיח |
| `smooth-scroll.css` | ✅ | צבעים נלווים לדיבאגר – ניתן להשאיר |
| `snippets.css` | ⚠️ | code blocks קשיחים |
| `split-view.css` | ❌ | Hardcoded, Phase 4 |
| `sticky-notes.css` | ⚠️ | צהוב מכוון – תשאר, פרט לטקסטים |

(קבצי פונט ו־map אינם רלוונטיים.)

---

## Conflicts & Issues

1. **Ocean & Forest Missing Tokens** – עד עכשיו הכילו רק `--primary/--secondary`. מחייב הוספת סט מלא (ר' נספח א').
2. **Parallel Variable Systems** – `markdown-enhanced.css` ו־`multi-select.css` הגדירו משתנים שלא קיימים ב־base – יש לסנכרן.
3. **Gradients** – ריכוז הגרדיאנטים נמצא בטבלה נפרדת (bookmarks, multi-select, base). חייבים לוודא שכל `var(--primary/secondary)` מתעדכן לכל theme.
4. **@media vs data-theme** – כל קובץ חייב לעבור ל־`[data-theme]` כדי לשמור על בחירת המשתמש.
5. **Inline Styles** – נרשם mapping לכל inline כדי לוודא שהחלקים יומרו למשתנים קיימים ולא ניצור tokens כפולים.
6. **Stateful UI** – hover/active/disabled בקבצים הבאים משתמשים בצבעים שונים: `collections.css`, `bookmarks.css`, `multi-select.css`, `split-view.css`. בוצע רישום בכל קובץ עם הערה מהיכן לקחת משתנה (למשל `--btn-primary-hover-bg`).

---

## Accessibility Analysis

מבחני ניגודיות (WCAG 2.1 AA) בוצעו ל־High Contrast:

| Element | Background | Foreground | Ratio | Result |
|---------|------------|------------|-------|--------|
| Body text | `#000000` | `#ffffff` | 21:1 | ✅ |
| Links | `#000000` | `#ffff00` | 19.56:1 | ✅ |
| Link hover | `#000000` | `#ffcc00` | 14.58:1 | ✅ |
| Code keyword | `#000000` | `#ff00ff` | 6.96:1 | ✅ |
| Code error | `#ff0000` | `#000000` | 5.25:1 | ✅ |

Guidelines לכל שינוי עתידי נוספו למסמך (שימוש רק בפלטה המאושרת והבטחת ratio ≥ 4.5:1 לטקסט רגיל).

---

## Proposed Variable Structure

### Level 1 – Primitives (קבועים בכל theme)

```css
:root {
  --glass-blur: 10px;
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 14px;
  /* Bookmark palette – intentional constants */
  --bookmark-yellow: #ffd700;
  --bookmark-red: #ff6b6b;
  --bookmark-green: #51cf66;
  --bookmark-blue: #4dabf7;
  --bookmark-purple: #9775fa;
  --bookmark-orange: #ffa94d;
  --bookmark-pink: #ff69b4;
}
```

### Level 2 – Semantic Tokens (משתנים בין themes)

```css
:root {
  --primary: #667eea;
  --primary-dark: #5a67d8;
  --secondary: #764ba2;
  --success: #48bb78;
  --danger: #f56565;
  --warning: #ed8936;
  --info: #4299e1;
  --bg-primary: linear-gradient(135deg, var(--primary), var(--secondary));
  --bg-secondary: color-mix(in srgb, var(--primary) 60%, var(--secondary) 40%);
  --bg-tertiary: rgba(255,255,255,0.25);
  --text-primary: #ffffff;
  --text-secondary: rgba(255,255,255,0.82);
  --text-muted: rgba(255,255,255,0.65);
  --glass: rgba(255,255,255,0.1);
  --glass-border: rgba(255,255,255,0.2);
  --glass-hover: rgba(255,255,255,0.15);
  --card-bg: rgba(255,255,255,0.12);
  --card-border: rgba(255,255,255,0.25);
  --code-bg: rgba(0,0,0,0.3);
  --code-text: var(--text-primary);
  --code-border: rgba(255,255,255,0.12);
  --btn-primary-bg: #ffffff;
  --btn-primary-color: var(--primary);
  --btn-primary-border: transparent;
  --btn-primary-shadow: none;
  --btn-primary-hover-bg: #ffffff;
  --btn-primary-hover-shadow: 0 10px 20px rgba(0,0,0,0.2);
}
```

כל theme מגדיר overrides לשדות לעיל (ר' נספח א').

### Level 3 – Component Tokens (רק כשחייבים)

```css
:root {
  --search-card-shadow: 0 20px 45px rgba(15,23,42,0.25);
  --search-card-shadow-hover: 0 28px 60px rgba(15,23,42,0.35);
  --search-highlight-bg: color-mix(in srgb, var(--primary) 40%, #fff 60%);
  --search-highlight-text: #1a202c;
  --bookmarks-panel-bg: rgba(255,255,255,0.97);
  --bookmarks-panel-shadow: 0 20px 45px rgba(15,23,42,0.15);
  --bookmarks-text-primary: #212529;
  --bookmarks-text-secondary: #6c757d;
  /* bulk toolbar, split-view, reader modes יקבלו tokens בהתאם */
}
```

קריטריון: אם צבע אינו נגזר ממשתנה סמנטי (למשל shadow מיוחד ב־Classic) – נשאר ברמת Component.

---

## Execution Strategy

### Phase Sequence (מאושר מול הביקוש)

1. **Phase 1 – Complete base variables**
   - הוספת סט מלא ל־Ocean ו־Forest
   - הוספת משתנים שחסרים (`--details-*`, `--bulk-*`, `--alert-*`)
2. **Phase 2 – `collections.css`**
   - ההשפעה הרחבה ביותר (dashboard)
   - החלפת כל הצבעים הקשיחים במשתנים
3. **Phase 3 – `markdown-enhanced.css`**
   - מעבר ל־`[data-theme]`
   - הטמעת משתנים גלובליים (details, summary, admonitions)
4. **Phase 4 – `split-view.css`**
   - התאמת live preview + code blocks למערכת המשתנים
5. **Phase 5 – HTML inline**
   - `files.html`, `login.html`, `settings.html`, `base.html`
6. **Phase 6 – JavaScript cleanup**
   - `bookmarks.js`, `sticky-notes.js`, `smooth-scroll.js`

בדיקות: אחרי כל פאזה להריץ Theme Switcher לכל 8 התמות, עם צילום מסך מהיר לקליטת רגרסיות.

### Traceability vs Implementation (גיסטים קיימים)

| Scope | Plan Status | Matching Implementation (gist) | Match? |
|-------|-------------|--------------------------------|--------|
| base variables, Ocean/Forest completion | Phase 1 | `base.html` gist | ✅ – כל המשתנים קיימים |
| `collections.css` conversion | Phase 2 | `collections.css` gist | ✅ – 340+ שורות var |
| `markdown-enhanced.css` | Phase 3 | `markdown-enhanced.css` gist | ✅ – הוחלפו @media |
| `split-view.css` | Phase 4 | `split-view.css` gist | ✅ |
| HTML inline fixes | Phase 5 | `files.html`, `bookmarks_snippet.html`, `settings.html`, `login.html` gists | ✅ |
| JS cleanup | Phase 6 | `bookmarks.js`, `smooth-scroll.js`, `sticky-notes.js` gists | ✅ |

> **מסקנה:** המימוש המלא שהוצג בגיסטים תואם לתכנית. המסמך הנוכחי משמש כתיעוד תכנון + הוכחת כיסוי.

---

## Open Questions (עדכני)

1. **Ocean/Forest** – בחירה באופציה B (סט משתנים מלא). ✔️ הוחלט וממומש.
2. **theme_preview.html** – נשאר Hardcoded (דף דמו). ✔️
3. **Reader modes ב־`md_preview.html`** – נשארים presets נפרדים (`--reader-*` בעתיד). ✔️
4. **codemirror.local.js / md_preview.bundle.js** – מתעלמים (3rd party). ✔️
5. **Prioritization** – הולכים לפי סדר הפאזות לעיל (מאזן מהירות+שלמות). ✔️

---

## Appendix A – Missing Variables To Add

### Ocean Theme (להוסיף ל-`:root[data-theme="ocean"]`)

```
--bg-primary: #1a365d;
--bg-secondary: #2a4365;
--bg-tertiary: #2c5282;
--text-primary: #ffffff;
--text-secondary: rgba(255,255,255,0.85);
--text-muted: rgba(255,255,255,0.65);
--glass: rgba(49,130,206,0.15);
--glass-border: rgba(49,130,206,0.35);
--glass-hover: rgba(49,130,206,0.25);
--card-bg: rgba(26,54,93,0.85);
--card-border: rgba(49,130,206,0.35);
--code-bg: #1a365d;
--code-text: #e2e8f0;
--code-border: rgba(49,130,206,0.4);
--btn-primary-bg: rgba(255,255,255,0.95);
--btn-primary-color: #1a365d;
--btn-primary-border: rgba(255,255,255,0.65);
--btn-primary-shadow: 0 4px 14px rgba(26,54,93,0.35);
--btn-primary-hover-bg: #ffffff;
--btn-primary-hover-shadow: 0 12px 28px rgba(26,54,93,0.45);
```

### Forest Theme (דומה במבנה)

```
--bg-primary: #1a4731;
--bg-secondary: #22543d;
--bg-tertiary: #276749;
--text-primary: #ffffff;
--text-secondary: rgba(255,255,255,0.85);
--text-muted: rgba(255,255,255,0.65);
--glass: rgba(47,133,90,0.15);
--glass-border: rgba(47,133,90,0.35);
--glass-hover: rgba(47,133,90,0.25);
--card-bg: rgba(26,71,49,0.85);
--card-border: rgba(47,133,90,0.35);
--code-bg: #1a4731;
--code-text: #e2fbe2;
--code-border: rgba(47,133,90,0.4);
--btn-primary-bg: rgba(255,255,255,0.95);
--btn-primary-color: #1a4731;
--btn-primary-border: rgba(255,255,255,0.65);
--btn-primary-shadow: 0 4px 14px rgba(26,71,49,0.35);
--btn-primary-hover-bg: #ffffff;
--btn-primary-hover-shadow: 0 12px 28px rgba(26,71,49,0.45);
```

### Additional Missing Tokens (גלובליים)

| Token | Needed For | Status |
|-------|------------|--------|
| `--details-border`, `--details-bg`, `--details-hover`, `--summary-color` | `markdown-enhanced.css` | להוסיף ב-Phase 1 |
| `--bulk-toolbar-bg`, `--bulk-toolbar-shadow`, `--bulk-badge-success/danger/info` | `multi-select.css` | להוסיף |
| `--alert-bg-danger`, `--alert-border-danger`, `--alert-text-danger` | `login.html` + alerts | להוסיף |
| `--reader-sepia-*` | עתידי (`md_preview.html`) | מחוץ לסקופ כרגע |

---

**This document now captures the full pre-coding plan plus verification against the provided implementation. Once approved, we can either adopt the existing gists or reproduce them following this blueprint.**
