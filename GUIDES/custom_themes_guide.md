# 🎨 Custom Themes – מדריך מקיף

> **מדריך זה מתאר את הרחבת מערכת ערכות הנושא הקיימת** עם יכולות ייבוא מ-VS Code, ערכות פופולריות מוכנות, וייבוא ידני של קבצי JSON.

---

## 📑 תוכן עניינים

1. [סקירת המערכת הקיימת](#סקירת-המערכת-הקיימת)
2. [ארכיטקטורה מורחבת](#ארכיטקטורה-מורחבת)
3. [ערכות פופולריות מוכנות (Presets)](#ערכות-פופולריות-מוכנות-presets)
4. [ייבוא ערכות מ-VS Code](#ייבוא-ערכות-מ-vs-code)
5. [ייבוא ידני של קובץ JSON](#ייבוא-ידני-של-קובץ-json)
6. [עורך ערכות נושא משופר](#עורך-ערכות-נושא-משופר)
7. [API Endpoints](#api-endpoints)
8. [Frontend Implementation](#frontend-implementation)
9. [בדיקות](#בדיקות)
10. [נגישות ו-UX](#נגישות-ו-ux)

---

## סקירת המערכת הקיימת

### מבנה CSS Variables

המערכת הקיימת מבוססת על CSS Variables המוגדרים ב-`base.html`:

```css
:root {
    --bg-primary: #ffffff;
    --bg-secondary: #f8f9fa;
    --text-primary: #1a1a2e;
    --text-secondary: #4a5568;
    --primary: #6366f1;
    --primary-hover: #4f46e5;
    --border-color: #e2e8f0;
    --shadow-color: rgba(0, 0, 0, 0.1);
    /* ... ועוד */
}

[data-theme="dark"] {
    --bg-primary: #0d1117;
    --bg-secondary: #161b22;
    /* ... */
}
```

### Theme Builder קיים

ממוקם ב-`webapp/templates/settings/theme_builder.html` ומספק:
- עריכת צבעים עם Pickr
- תצוגה מקדימה חיה
- שמירה ל-MongoDB
- תמיכה במספר ערכות מותאמות אישית

### סכמת MongoDB

```javascript
// מבנה חדש - מערך של ערכות
custom_themes: [
    {
        id: "uuid-string",
        name: "My Theme",
        description: "Optional description",
        is_active: true,
        source: "manual", // או "vscode", "preset", "import"
        created_at: ISODate(),
        updated_at: ISODate(),
        variables: {
            "--bg-primary": "#ffffff",
            "--text-primary": "#1a1a2e",
            // ...
        }
    }
]
```

---

## ארכיטקטורה מורחבת

### תרשים רכיבים

```
┌─────────────────────────────────────────────────────────────────┐
│                    Theme Management System                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │   Theme      │  │   VS Code    │  │    Preset Theme     │  │
│  │   Editor     │  │   Importer   │  │      Gallery        │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         │                 │                      │              │
│         └─────────────────┼──────────────────────┘              │
│                           ▼                                      │
│              ┌────────────────────────┐                         │
│              │   Theme Parser Service  │                         │
│              │   (services/theme_*)    │                         │
│              └───────────┬────────────┘                         │
│                          │                                       │
│                          ▼                                       │
│              ┌────────────────────────┐                         │
│              │    Theme API Routes     │                         │
│              │   (/api/themes/*)       │                         │
│              └───────────┬────────────┘                         │
│                          │                                       │
│                          ▼                                       │
│              ┌────────────────────────┐                         │
│              │      MongoDB           │                         │
│              │   (custom_themes[])    │                         │
│              └────────────────────────┘                         │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### קבצים חדשים

```
services/
├── theme_parser_service.py      # פרסור VS Code / JSON themes
├── theme_presets_service.py     # ניהול ערכות מוכנות

webapp/
├── themes_api.py                # API routes לערכות נושא
├── static/
│   ├── data/
│   │   └── theme_presets.json   # ערכות מוכנות
│   └── js/
│       └── theme-importer.js    # לוגיקת ייבוא
└── templates/
    └── settings/
        ├── theme_builder.html   # קיים - יש להרחיב
        └── theme_gallery.html   # חדש - גלריית ערכות
```

---

## ערכות פופולריות מוכנות (Presets)

### רשימת ערכות מומלצות

| שם הערכה | סגנון | מקור השראה |
|----------|-------|------------|
| **Dracula** | Dark | [draculatheme.com](https://draculatheme.com) |
| **Monokai** | Dark | Sublime Text |
| **One Dark** | Dark | Atom |
| **GitHub Light** | Light | GitHub.com |
| **GitHub Dark** | Dark | GitHub.com |
| **StackOverflow Light** | Light | stackoverflow.com |
| **StackOverflow Dark** | Dark | stackoverflow.com |
| **Solarized Light** | Light | ethanschoonover.com/solarized |
| **Solarized Dark** | Dark | ethanschoonover.com/solarized |
| **Nord** | Dark | nordtheme.com |
| **Gruvbox** | Dark | github.com/morhetz/gruvbox |
| **Material** | Dark | material.io |

### קובץ Presets

**`webapp/static/data/theme_presets.json`:**

```json
{
  "version": "1.0.0",
  "presets": [
    {
      "id": "github-light",
      "name": "GitHub Light",
      "description": "סגנון GitHub קלאסי - בהיר ונקי",
      "category": "light",
      "preview_colors": ["#ffffff", "#24292f", "#0969da"],
      "variables": {
        "--bg-primary": "#ffffff",
        "--bg-secondary": "#f6f8fa",
        "--bg-tertiary": "#eaeef2",
        "--text-primary": "#24292f",
        "--text-secondary": "#57606a",
        "--text-muted": "#8b949e",
        "--primary": "#0969da",
        "--primary-hover": "#0860c7",
        "--primary-light": "#ddf4ff",
        "--border-color": "#d0d7de",
        "--shadow-color": "rgba(31, 35, 40, 0.12)",
        "--success": "#1a7f37",
        "--warning": "#bf8700",
        "--error": "#cf222e",
        "--danger-bg": "#cf222e",
        "--danger-border": "#a40e26",
        "--code-bg": "#f6f8fa",
        "--code-text": "#24292f",
        "--link-color": "#0969da",
        "--navbar-bg": "#f6f8fa",
        "--card-bg": "#ffffff",
        "--card-border": "#d0d7de",
        "--input-bg": "#ffffff",
        "--input-border": "#d0d7de",
        "--btn-primary-bg": "#2da44e",
        "--btn-primary-color": "#ffffff",
        "--btn-primary-border": "#2da44e",
        "--btn-primary-hover-bg": "#2c974b",
        "--md-surface": "#24292f",
        "--md-text": "#e6edf3"
      }
    },
    {
      "id": "github-dark",
      "name": "GitHub Dark",
      "description": "סגנון GitHub כהה - מודרני וקריא",
      "category": "dark",
      "preview_colors": ["#0d1117", "#c9d1d9", "#58a6ff"],
      "variables": {
        "--bg-primary": "#0d1117",
        "--bg-secondary": "#161b22",
        "--bg-tertiary": "#21262d",
        "--text-primary": "#c9d1d9",
        "--text-secondary": "#8b949e",
        "--text-muted": "#6e7681",
        "--primary": "#58a6ff",
        "--primary-hover": "#79c0ff",
        "--primary-light": "#388bfd26",
        "--border-color": "#30363d",
        "--shadow-color": "rgba(0, 0, 0, 0.3)",
        "--success": "#3fb950",
        "--warning": "#d29922",
        "--error": "#f85149",
        "--danger-bg": "#f85149",
        "--danger-border": "#da3633",
        "--code-bg": "#161b22",
        "--code-text": "#c9d1d9",
        "--link-color": "#58a6ff",
        "--navbar-bg": "#161b22",
        "--card-bg": "#161b22",
        "--card-border": "#30363d",
        "--input-bg": "#0d1117",
        "--input-border": "#30363d",
        "--btn-primary-bg": "#238636",
        "--btn-primary-color": "#ffffff",
        "--btn-primary-border": "#238636",
        "--btn-primary-hover-bg": "#2ea043",
        "--md-surface": "#0d1117",
        "--md-text": "#c9d1d9"
      }
    },
    {
      "id": "stackoverflow-light",
      "name": "StackOverflow Light",
      "description": "סגנון StackOverflow קלאסי",
      "category": "light",
      "preview_colors": ["#ffffff", "#232629", "#f48024"],
      "variables": {
        "--bg-primary": "#ffffff",
        "--bg-secondary": "#f1f2f3",
        "--bg-tertiary": "#e3e6e8",
        "--text-primary": "#232629",
        "--text-secondary": "#3b4045",
        "--text-muted": "#6a737c",
        "--primary": "#f48024",
        "--primary-hover": "#da680b",
        "--primary-light": "#fff4e6",
        "--border-color": "#d6d9dc",
        "--shadow-color": "rgba(0, 0, 0, 0.08)",
        "--success": "#45a163",
        "--warning": "#c58329",
        "--error": "#c02d2e",
        "--danger-bg": "#c02d2e",
        "--danger-border": "#a52526",
        "--code-bg": "#f6f6f6",
        "--code-text": "#2d2d2d",
        "--link-color": "#0074cc",
        "--navbar-bg": "#f8f9f9",
        "--card-bg": "#ffffff",
        "--card-border": "#d6d9dc",
        "--input-bg": "#ffffff",
        "--input-border": "#babfc4",
        "--btn-primary-bg": "#0a95ff",
        "--btn-primary-color": "#ffffff",
        "--btn-primary-border": "#0a95ff",
        "--btn-primary-hover-bg": "#0074cc",
        "--md-surface": "#2d2d2d",
        "--md-text": "#e3e6e8"
      }
    },
    {
      "id": "stackoverflow-dark",
      "name": "StackOverflow Dark",
      "description": "סגנון StackOverflow כהה",
      "category": "dark",
      "preview_colors": ["#1c1e21", "#e7e8eb", "#f48024"],
      "variables": {
        "--bg-primary": "#1c1e21",
        "--bg-secondary": "#2d2f33",
        "--bg-tertiary": "#393c40",
        "--text-primary": "#e7e8eb",
        "--text-secondary": "#b5b5b5",
        "--text-muted": "#9199a1",
        "--primary": "#f48024",
        "--primary-hover": "#ff922e",
        "--primary-light": "#3d3200",
        "--border-color": "#4a4e51",
        "--shadow-color": "rgba(0, 0, 0, 0.4)",
        "--success": "#48a868",
        "--warning": "#e4a23a",
        "--error": "#de4f54",
        "--danger-bg": "#de4f54",
        "--danger-border": "#c74145",
        "--code-bg": "#2d2f33",
        "--code-text": "#e7e8eb",
        "--link-color": "#6cbbf7",
        "--navbar-bg": "#2d2f33",
        "--card-bg": "#2d2f33",
        "--card-border": "#4a4e51",
        "--input-bg": "#2d2f33",
        "--input-border": "#4a4e51",
        "--btn-primary-bg": "#378ad3",
        "--btn-primary-color": "#ffffff",
        "--btn-primary-border": "#378ad3",
        "--btn-primary-hover-bg": "#4a9ae1",
        "--md-surface": "#1c1e21",
        "--md-text": "#e7e8eb"
      }
    },
    {
      "id": "dracula",
      "name": "Dracula",
      "description": "ערכת Dracula הפופולרית - צבעים חיים על רקע כהה",
      "category": "dark",
      "preview_colors": ["#282a36", "#f8f8f2", "#bd93f9"],
      "variables": {
        "--bg-primary": "#282a36",
        "--bg-secondary": "#21222c",
        "--bg-tertiary": "#343746",
        "--text-primary": "#f8f8f2",
        "--text-secondary": "#6272a4",
        "--text-muted": "#44475a",
        "--primary": "#bd93f9",
        "--primary-hover": "#d4b9ff",
        "--primary-light": "#bd93f926",
        "--border-color": "#44475a",
        "--shadow-color": "rgba(0, 0, 0, 0.5)",
        "--success": "#50fa7b",
        "--warning": "#f1fa8c",
        "--error": "#ff5555",
        "--danger-bg": "#ff5555",
        "--danger-border": "#ff4444",
        "--code-bg": "#21222c",
        "--code-text": "#f8f8f2",
        "--link-color": "#8be9fd",
        "--navbar-bg": "#21222c",
        "--card-bg": "#21222c",
        "--card-border": "#44475a",
        "--input-bg": "#282a36",
        "--input-border": "#44475a",
        "--btn-primary-bg": "#bd93f9",
        "--btn-primary-color": "#282a36",
        "--btn-primary-border": "#bd93f9",
        "--btn-primary-hover-bg": "#d4b9ff",
        "--md-surface": "#282a36",
        "--md-text": "#f8f8f2",
        "--accent-pink": "#ff79c6",
        "--accent-cyan": "#8be9fd",
        "--accent-green": "#50fa7b",
        "--accent-orange": "#ffb86c",
        "--accent-yellow": "#f1fa8c"
      }
    },
    {
      "id": "monokai",
      "name": "Monokai",
      "description": "ערכת Monokai הקלאסית מ-Sublime Text",
      "category": "dark",
      "preview_colors": ["#272822", "#f8f8f2", "#a6e22e"],
      "variables": {
        "--bg-primary": "#272822",
        "--bg-secondary": "#1e1f1c",
        "--bg-tertiary": "#3e3d32",
        "--text-primary": "#f8f8f2",
        "--text-secondary": "#a59f85",
        "--text-muted": "#75715e",
        "--primary": "#a6e22e",
        "--primary-hover": "#b9e84a",
        "--primary-light": "#a6e22e26",
        "--border-color": "#3e3d32",
        "--shadow-color": "rgba(0, 0, 0, 0.5)",
        "--success": "#a6e22e",
        "--warning": "#e6db74",
        "--error": "#f92672",
        "--danger-bg": "#f92672",
        "--danger-border": "#e01860",
        "--code-bg": "#1e1f1c",
        "--code-text": "#f8f8f2",
        "--link-color": "#66d9ef",
        "--navbar-bg": "#1e1f1c",
        "--card-bg": "#1e1f1c",
        "--card-border": "#3e3d32",
        "--input-bg": "#272822",
        "--input-border": "#3e3d32",
        "--btn-primary-bg": "#a6e22e",
        "--btn-primary-color": "#272822",
        "--btn-primary-border": "#a6e22e",
        "--btn-primary-hover-bg": "#b9e84a",
        "--md-surface": "#272822",
        "--md-text": "#f8f8f2",
        "--accent-pink": "#f92672",
        "--accent-cyan": "#66d9ef",
        "--accent-orange": "#fd971f",
        "--accent-purple": "#ae81ff"
      }
    },
    {
      "id": "one-dark",
      "name": "One Dark",
      "description": "ערכת One Dark מ-Atom Editor",
      "category": "dark",
      "preview_colors": ["#282c34", "#abb2bf", "#61afef"],
      "variables": {
        "--bg-primary": "#282c34",
        "--bg-secondary": "#21252b",
        "--bg-tertiary": "#2c323c",
        "--text-primary": "#abb2bf",
        "--text-secondary": "#828997",
        "--text-muted": "#5c6370",
        "--primary": "#61afef",
        "--primary-hover": "#7ec0f5",
        "--primary-light": "#61afef26",
        "--border-color": "#3e4451",
        "--shadow-color": "rgba(0, 0, 0, 0.4)",
        "--success": "#98c379",
        "--warning": "#e5c07b",
        "--error": "#e06c75",
        "--danger-bg": "#e06c75",
        "--danger-border": "#be5046",
        "--code-bg": "#21252b",
        "--code-text": "#abb2bf",
        "--link-color": "#61afef",
        "--navbar-bg": "#21252b",
        "--card-bg": "#21252b",
        "--card-border": "#3e4451",
        "--input-bg": "#282c34",
        "--input-border": "#3e4451",
        "--btn-primary-bg": "#61afef",
        "--btn-primary-color": "#282c34",
        "--btn-primary-border": "#61afef",
        "--btn-primary-hover-bg": "#7ec0f5",
        "--md-surface": "#282c34",
        "--md-text": "#abb2bf",
        "--accent-red": "#e06c75",
        "--accent-green": "#98c379",
        "--accent-yellow": "#e5c07b",
        "--accent-purple": "#c678dd",
        "--accent-cyan": "#56b6c2"
      }
    },
    {
      "id": "nord",
      "name": "Nord",
      "description": "ערכת Nord - גוונים קרירים וקריאים",
      "category": "dark",
      "preview_colors": ["#2e3440", "#eceff4", "#88c0d0"],
      "variables": {
        "--bg-primary": "#2e3440",
        "--bg-secondary": "#3b4252",
        "--bg-tertiary": "#434c5e",
        "--text-primary": "#eceff4",
        "--text-secondary": "#d8dee9",
        "--text-muted": "#4c566a",
        "--primary": "#88c0d0",
        "--primary-hover": "#8fbcbb",
        "--primary-light": "#88c0d026",
        "--border-color": "#4c566a",
        "--shadow-color": "rgba(0, 0, 0, 0.35)",
        "--success": "#a3be8c",
        "--warning": "#ebcb8b",
        "--error": "#bf616a",
        "--danger-bg": "#bf616a",
        "--danger-border": "#a5545c",
        "--code-bg": "#3b4252",
        "--code-text": "#eceff4",
        "--link-color": "#81a1c1",
        "--navbar-bg": "#3b4252",
        "--card-bg": "#3b4252",
        "--card-border": "#4c566a",
        "--input-bg": "#2e3440",
        "--input-border": "#4c566a",
        "--btn-primary-bg": "#5e81ac",
        "--btn-primary-color": "#eceff4",
        "--btn-primary-border": "#5e81ac",
        "--btn-primary-hover-bg": "#81a1c1",
        "--md-surface": "#2e3440",
        "--md-text": "#eceff4"
      }
    },
    {
      "id": "solarized-light",
      "name": "Solarized Light",
      "description": "ערכת Solarized הבהירה",
      "category": "light",
      "preview_colors": ["#fdf6e3", "#657b83", "#268bd2"],
      "variables": {
        "--bg-primary": "#fdf6e3",
        "--bg-secondary": "#eee8d5",
        "--bg-tertiary": "#e4ddc8",
        "--text-primary": "#657b83",
        "--text-secondary": "#839496",
        "--text-muted": "#93a1a1",
        "--primary": "#268bd2",
        "--primary-hover": "#1a6da3",
        "--primary-light": "#268bd226",
        "--border-color": "#93a1a1",
        "--shadow-color": "rgba(0, 0, 0, 0.1)",
        "--success": "#859900",
        "--warning": "#b58900",
        "--error": "#dc322f",
        "--danger-bg": "#dc322f",
        "--danger-border": "#c72626",
        "--code-bg": "#eee8d5",
        "--code-text": "#657b83",
        "--link-color": "#268bd2",
        "--navbar-bg": "#eee8d5",
        "--card-bg": "#fdf6e3",
        "--card-border": "#93a1a1",
        "--input-bg": "#fdf6e3",
        "--input-border": "#93a1a1",
        "--btn-primary-bg": "#268bd2",
        "--btn-primary-color": "#fdf6e3",
        "--btn-primary-border": "#268bd2",
        "--btn-primary-hover-bg": "#1a6da3",
        "--md-surface": "#073642",
        "--md-text": "#93a1a1"
      }
    },
    {
      "id": "solarized-dark",
      "name": "Solarized Dark",
      "description": "ערכת Solarized הכהה",
      "category": "dark",
      "preview_colors": ["#002b36", "#839496", "#268bd2"],
      "variables": {
        "--bg-primary": "#002b36",
        "--bg-secondary": "#073642",
        "--bg-tertiary": "#0a4051",
        "--text-primary": "#839496",
        "--text-secondary": "#93a1a1",
        "--text-muted": "#586e75",
        "--primary": "#268bd2",
        "--primary-hover": "#2aa0f0",
        "--primary-light": "#268bd226",
        "--border-color": "#586e75",
        "--shadow-color": "rgba(0, 0, 0, 0.4)",
        "--success": "#859900",
        "--warning": "#b58900",
        "--error": "#dc322f",
        "--danger-bg": "#dc322f",
        "--danger-border": "#c72626",
        "--code-bg": "#073642",
        "--code-text": "#839496",
        "--link-color": "#268bd2",
        "--navbar-bg": "#073642",
        "--card-bg": "#073642",
        "--card-border": "#586e75",
        "--input-bg": "#002b36",
        "--input-border": "#586e75",
        "--btn-primary-bg": "#268bd2",
        "--btn-primary-color": "#fdf6e3",
        "--btn-primary-border": "#268bd2",
        "--btn-primary-hover-bg": "#2aa0f0",
        "--md-surface": "#002b36",
        "--md-text": "#839496"
      }
    },
    {
      "id": "gruvbox-dark",
      "name": "Gruvbox Dark",
      "description": "ערכת Gruvbox - צבעים חמים ורטרו",
      "category": "dark",
      "preview_colors": ["#282828", "#ebdbb2", "#b8bb26"],
      "variables": {
        "--bg-primary": "#282828",
        "--bg-secondary": "#1d2021",
        "--bg-tertiary": "#3c3836",
        "--text-primary": "#ebdbb2",
        "--text-secondary": "#d5c4a1",
        "--text-muted": "#928374",
        "--primary": "#b8bb26",
        "--primary-hover": "#c9cc39",
        "--primary-light": "#b8bb2626",
        "--border-color": "#504945",
        "--shadow-color": "rgba(0, 0, 0, 0.4)",
        "--success": "#b8bb26",
        "--warning": "#fabd2f",
        "--error": "#fb4934",
        "--danger-bg": "#fb4934",
        "--danger-border": "#cc241d",
        "--code-bg": "#1d2021",
        "--code-text": "#ebdbb2",
        "--link-color": "#83a598",
        "--navbar-bg": "#1d2021",
        "--card-bg": "#1d2021",
        "--card-border": "#504945",
        "--input-bg": "#282828",
        "--input-border": "#504945",
        "--btn-primary-bg": "#b8bb26",
        "--btn-primary-color": "#282828",
        "--btn-primary-border": "#b8bb26",
        "--btn-primary-hover-bg": "#c9cc39",
        "--md-surface": "#282828",
        "--md-text": "#ebdbb2",
        "--accent-red": "#fb4934",
        "--accent-green": "#b8bb26",
        "--accent-yellow": "#fabd2f",
        "--accent-blue": "#83a598",
        "--accent-purple": "#d3869b",
        "--accent-aqua": "#8ec07c",
        "--accent-orange": "#fe8019"
      }
    },
    {
      "id": "material-dark",
      "name": "Material Dark",
      "description": "ערכת Material Design כהה",
      "category": "dark",
      "preview_colors": ["#263238", "#eeffff", "#82aaff"],
      "variables": {
        "--bg-primary": "#263238",
        "--bg-secondary": "#1e272c",
        "--bg-tertiary": "#314549",
        "--text-primary": "#eeffff",
        "--text-secondary": "#b0bec5",
        "--text-muted": "#546e7a",
        "--primary": "#82aaff",
        "--primary-hover": "#9cc4ff",
        "--primary-light": "#82aaff26",
        "--border-color": "#37474f",
        "--shadow-color": "rgba(0, 0, 0, 0.4)",
        "--success": "#c3e88d",
        "--warning": "#ffcb6b",
        "--error": "#ff5370",
        "--danger-bg": "#ff5370",
        "--danger-border": "#e04560",
        "--code-bg": "#1e272c",
        "--code-text": "#eeffff",
        "--link-color": "#82aaff",
        "--navbar-bg": "#1e272c",
        "--card-bg": "#1e272c",
        "--card-border": "#37474f",
        "--input-bg": "#263238",
        "--input-border": "#37474f",
        "--btn-primary-bg": "#82aaff",
        "--btn-primary-color": "#263238",
        "--btn-primary-border": "#82aaff",
        "--btn-primary-hover-bg": "#9cc4ff",
        "--md-surface": "#263238",
        "--md-text": "#eeffff",
        "--accent-pink": "#f07178",
        "--accent-cyan": "#89ddff",
        "--accent-orange": "#f78c6c",
        "--accent-purple": "#c792ea"
      }
    }
  ]
}
```

### Service לטעינת Presets

**`services/theme_presets_service.py`:**

```python
"""
Theme Presets Service
טוען ומנהל ערכות נושא מוכנות מראש
"""
import json
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# נתיב לקובץ ה-presets
PRESETS_FILE = Path(__file__).parent.parent / "webapp" / "static" / "data" / "theme_presets.json"

# מטמון בזיכרון
_presets_cache: dict | None = None


def load_presets(force_reload: bool = False) -> dict:
    """
    טוען את ערכות הנושא המוכנות מהקובץ.
    
    Args:
        force_reload: אם True, טוען מחדש גם אם יש מטמון
        
    Returns:
        מילון עם כל הערכות
    """
    global _presets_cache
    
    if _presets_cache is not None and not force_reload:
        return _presets_cache
    
    try:
        with open(PRESETS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            _presets_cache = data
            logger.info(f"Loaded {len(data.get('presets', []))} theme presets")
            return data
    except FileNotFoundError:
        logger.warning(f"Presets file not found: {PRESETS_FILE}")
        return {"version": "1.0.0", "presets": []}
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in presets file: {e}")
        return {"version": "1.0.0", "presets": []}


def get_preset_by_id(preset_id: str) -> Optional[dict]:
    """
    מחזיר ערכת נושא לפי ID.
    
    Args:
        preset_id: מזהה הערכה (לדוגמה: "dracula", "github-light")
        
    Returns:
        מילון עם פרטי הערכה או None
    """
    data = load_presets()
    for preset in data.get("presets", []):
        if preset.get("id") == preset_id:
            return preset
    return None


def list_presets(category: Optional[str] = None) -> list[dict]:
    """
    מחזיר רשימת ערכות, אופציונלית לפי קטגוריה.
    
    Args:
        category: "light" או "dark" לסינון, או None לכל הערכות
        
    Returns:
        רשימה של ערכות (ללא המשתנים - רק מטא-דאטה)
    """
    data = load_presets()
    presets = data.get("presets", [])
    
    if category:
        presets = [p for p in presets if p.get("category") == category]
    
    # מחזירים רק מטא-דאטה, לא את כל המשתנים
    return [
        {
            "id": p["id"],
            "name": p["name"],
            "description": p.get("description", ""),
            "category": p.get("category", "dark"),
            "preview_colors": p.get("preview_colors", [])
        }
        for p in presets
    ]


def apply_preset_to_user(user_id: str, preset_id: str, db) -> dict:
    """
    יוצר ערכה מותאמת אישית חדשה מתוך preset.
    
    Args:
        user_id: מזהה המשתמש
        preset_id: מזהה ה-preset
        db: חיבור MongoDB
        
    Returns:
        מילון עם הערכה החדשה שנוצרה
    """
    import uuid
    from datetime import datetime
    
    preset = get_preset_by_id(preset_id)
    if not preset:
        raise ValueError(f"Preset not found: {preset_id}")
    
    new_theme = {
        "id": str(uuid.uuid4()),
        "name": preset["name"],
        "description": f"Based on {preset['name']} preset",
        "is_active": False,
        "source": "preset",
        "source_preset_id": preset_id,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "variables": preset["variables"].copy()
    }
    
    # מוסיפים למערך custom_themes של המשתמש
    db.users.update_one(
        {"_id": user_id},
        {"$push": {"custom_themes": new_theme}}
    )
    
    return new_theme
```

---

## ייבוא ערכות מ-VS Code

### מבנה ערכת VS Code (TextMate)

ערכות VS Code מגיעות בפורמט JSON עם מבנה מסוים:

```json
{
  "name": "Dracula",
  "type": "dark",
  "colors": {
    "editor.background": "#282a36",
    "editor.foreground": "#f8f8f2",
    "activityBar.background": "#21222c",
    "sideBar.background": "#21222c",
    "statusBar.background": "#191a21",
    "tab.activeBackground": "#282a36",
    "tab.inactiveBackground": "#21222c",
    "terminal.background": "#282a36",
    "terminal.foreground": "#f8f8f2",
    "button.background": "#bd93f9",
    "button.foreground": "#f8f8f2",
    "input.background": "#21222c",
    "input.foreground": "#f8f8f2",
    "input.border": "#44475a",
    "focusBorder": "#bd93f9",
    "list.activeSelectionBackground": "#44475a",
    "list.hoverBackground": "#343746"
  },
  "tokenColors": [
    {
      "scope": ["comment"],
      "settings": { "foreground": "#6272a4" }
    },
    {
      "scope": ["string"],
      "settings": { "foreground": "#f1fa8c" }
    }
  ]
}
```

### מבנה tokenColors (Syntax Highlighting)

ערכות VS Code כוללות גם מערך `tokenColors` שמגדיר צבעים ל-Syntax Highlighting:

```json
{
  "tokenColors": [
    {
      "scope": ["comment", "punctuation.definition.comment"],
      "settings": { "foreground": "#6272a4", "fontStyle": "italic" }
    },
    {
      "scope": ["string", "string.quoted"],
      "settings": { "foreground": "#f1fa8c" }
    },
    {
      "scope": ["keyword", "storage.type"],
      "settings": { "foreground": "#ff79c6" }
    },
    {
      "scope": ["entity.name.function", "support.function"],
      "settings": { "foreground": "#50fa7b" }
    },
    {
      "scope": ["variable", "variable.parameter"],
      "settings": { "foreground": "#f8f8f2" }
    },
    {
      "scope": ["constant.numeric"],
      "settings": { "foreground": "#bd93f9" }
    }
  ]
}
```

#### מיפוי tokenColors ל-CodeMirror

אם ה-Web App משתמש ב-CodeMirror, יש למפות את ה-scopes ל-CSS classes של CodeMirror:

```python
# מיפוי בין VS Code scopes ל-CodeMirror classes
TOKEN_TO_CODEMIRROR_MAP = {
    # Comments
    "comment": ".cm-comment",
    "punctuation.definition.comment": ".cm-comment",
    
    # Strings
    "string": ".cm-string",
    "string.quoted": ".cm-string",
    
    # Keywords
    "keyword": ".cm-keyword",
    "storage.type": ".cm-keyword",
    "storage.modifier": ".cm-keyword",
    
    # Functions
    "entity.name.function": ".cm-def",
    "support.function": ".cm-builtin",
    
    # Variables
    "variable": ".cm-variable",
    "variable.parameter": ".cm-variable-2",
    "variable.other": ".cm-variable-3",
    
    # Constants
    "constant.numeric": ".cm-number",
    "constant.language": ".cm-atom",
    
    # Types
    "entity.name.type": ".cm-type",
    "support.type": ".cm-type",
    
    # Operators
    "keyword.operator": ".cm-operator",
    
    # Properties
    "entity.other.attribute-name": ".cm-attribute",
    "support.type.property-name": ".cm-property",
    
    # Tags (HTML/XML)
    "entity.name.tag": ".cm-tag",
    
    # Errors
    "invalid": ".cm-error"
}
```

#### יצירת CSS מ-tokenColors

```python
def generate_codemirror_css_from_tokens(token_colors: list[dict]) -> str:
    """
    ממיר tokenColors של VS Code ל-CSS עבור CodeMirror.
    
    Args:
        token_colors: מערך tokenColors מערכת VS Code
        
    Returns:
        מחרוזת CSS
    """
    css_rules = []
    
    for token in token_colors:
        scopes = token.get("scope", [])
        if isinstance(scopes, str):
            scopes = [scopes]
        
        settings = token.get("settings", {})
        foreground = settings.get("foreground")
        font_style = settings.get("fontStyle", "")
        
        if not foreground:
            continue
        
        # מיפוי כל scope ל-CodeMirror class
        for scope in scopes:
            cm_class = _find_codemirror_class(scope)
            if cm_class:
                rule_parts = [f"color: {foreground}"]
                
                if "italic" in font_style:
                    rule_parts.append("font-style: italic")
                if "bold" in font_style:
                    rule_parts.append("font-weight: bold")
                if "underline" in font_style:
                    rule_parts.append("text-decoration: underline")
                
                css_rules.append(
                    f":root[data-theme=\"custom\"] {cm_class} {{ {'; '.join(rule_parts)}; }}"
                )
    
    return "\n".join(css_rules)


def _find_codemirror_class(scope: str) -> str | None:
    """
    מוצא את ה-CodeMirror class המתאים ל-scope.
    תומך בהתאמה חלקית (prefix matching).
    """
    # התאמה מדויקת
    if scope in TOKEN_TO_CODEMIRROR_MAP:
        return TOKEN_TO_CODEMIRROR_MAP[scope]
    
    # התאמה לפי prefix
    for vs_scope, cm_class in TOKEN_TO_CODEMIRROR_MAP.items():
        if scope.startswith(vs_scope) or vs_scope.startswith(scope):
            return cm_class
    
    return None
```

#### שמירת Syntax Theme ב-MongoDB

```javascript
// מבנה מורחב של ערכה מותאמת אישית
{
    "id": "uuid",
    "name": "Dracula",
    "variables": {
        "--bg-primary": "#282a36",
        // ... UI variables
    },
    "syntax_css": ":root[data-theme=\"custom\"] .cm-comment { color: #6272a4; font-style: italic; }\n...",
    "source": "vscode"
}
```

#### הזרקת Syntax CSS ב-base.html

```html
{% if custom_theme and custom_theme.is_active %}
<!-- User Custom Theme Override -->
<style id="user-custom-theme">
:root[data-theme="custom"] {
    {% for var_name, var_value in custom_theme.variables.items() %}
    {{ var_name }}: {{ var_value }};
    {% endfor %}
}
</style>
{% if custom_theme.syntax_css %}
<!-- Syntax Highlighting Override -->
<style id="user-custom-syntax">
{{ custom_theme.syntax_css | safe }}
</style>
{% endif %}
{% endif %}
```

> ⚠️ **שים לב:** יש לוודא שה-`syntax_css` עבר sanitization לפני שמירה ב-DB כדי למנוע CSS injection.

---

### Service למיפוי VS Code → CSS Variables

**`services/theme_parser_service.py`:**

```python
"""
Theme Parser Service
מפרסר ערכות נושא מפורמטים שונים ומייצר CSS Variables
"""
import json
import re
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# מיפוי בין VS Code keys לבין CSS Variables שלנו
# ⚠️ הערה: חלק מהמפתחות ממופים לרשימה של משתנים (כאשר ערך אחד צריך למלא כמה טוקנים)
VSCODE_TO_CSS_MAP = {
    # רקעים - editor.background ממלא גם את --md-surface למניעת "לבן מסנוור" ב-Markdown
    "editor.background": ["--bg-primary", "--md-surface"],
    "sideBar.background": "--bg-secondary",
    "activityBar.background": "--bg-tertiary",
    "tab.activeBackground": "--bg-primary",
    "input.background": "--input-bg",
    "dropdown.background": "--bg-secondary",
    "panel.background": "--bg-secondary",
    
    # טקסט - editor.foreground ממלא גם את --md-text לעקביות ב-Markdown Preview
    "editor.foreground": ["--text-primary", "--md-text"],
    "sideBar.foreground": "--text-secondary",
    "descriptionForeground": "--text-muted",
    "input.foreground": "--text-primary",
    
    # כפתורים (Level 2 Tokens) - לא משתמשים ב---primary הגנרי!
    "button.background": "--btn-primary-bg",
    "button.foreground": "--btn-primary-color",
    "button.hoverBackground": "--btn-primary-hover-bg",
    "focusBorder": "--primary",
    "textLink.foreground": "--link-color",
    "textLink.activeForeground": "--primary-hover",
    
    # גבולות
    "input.border": "--input-border",
    "panel.border": "--border-color",
    "sideBar.border": "--border-color",
    "tab.border": "--border-color",
    "activityBar.border": "--border-color",
    
    # סטטוסים ושגיאות - שימוש ב---danger-bg לפי ארכיטקטורת הטוקנים
    "notificationsErrorIcon.foreground": ["--error", "--danger-bg"],
    "notificationsWarningIcon.foreground": "--warning",
    "notificationsInfoIcon.foreground": "--primary",
    "testing.iconPassed": "--success",
    "testing.iconFailed": "--error",
    "editorError.foreground": "--error",
    "editorWarning.foreground": "--warning",
    
    # קוד
    "terminal.background": "--code-bg",
    "terminal.foreground": "--code-text",
    
    # Navbar / Header
    "titleBar.activeBackground": "--navbar-bg",
    "titleBar.inactiveBackground": "--navbar-bg",
    "statusBar.background": "--navbar-bg",
    
    # Cards
    "editorWidget.background": "--card-bg",
    "editorHoverWidget.background": "--card-bg"
}

# ערכי fallback למקרה שחסרים
# מסונכרן עם מסמך הארכיטקטורה: docs/webapp/theming_and_css.rst
FALLBACK_DARK = {
    # רקעים וטקסט
    "--bg-primary": "#1e1e1e",
    "--bg-secondary": "#252526",
    "--bg-tertiary": "#333333",
    "--text-primary": "#d4d4d4",
    "--text-secondary": "#9d9d9d",
    "--text-muted": "#6d6d6d",
    
    # צבעי מותג
    "--primary": "#569cd6",
    "--primary-hover": "#6cb6ff",
    "--primary-light": "#569cd626",
    
    # גבולות וצללים
    "--border-color": "#474747",
    "--shadow-color": "rgba(0, 0, 0, 0.4)",
    
    # סטטוסים (Level 1)
    "--success": "#4ec9b0",
    "--warning": "#dcdcaa",
    "--error": "#f44747",
    "--danger-bg": "#f44747",
    "--danger-border": "#d32f2f",
    "--text-on-warning": "#1a1a1a",
    
    # קוד
    "--code-bg": "#1e1e1e",
    "--code-text": "#d4d4d4",
    "--code-border": "#474747",
    
    # UI elements
    "--link-color": "#569cd6",
    "--navbar-bg": "#323233",
    "--card-bg": "#252526",
    "--card-border": "#474747",
    "--input-bg": "#3c3c3c",
    "--input-border": "#474747",
    
    # כפתורים (Level 2)
    "--btn-primary-bg": "#569cd6",
    "--btn-primary-color": "#ffffff",
    "--btn-primary-border": "#569cd6",
    "--btn-primary-shadow": "rgba(86, 156, 214, 0.3)",
    "--btn-primary-hover-bg": "#6cb6ff",
    "--btn-primary-hover-color": "#ffffff",
    
    # Markdown & Split View (Level 2)
    "--md-surface": "#1e1e1e",
    "--md-text": "#d4d4d4",
    
    # Glass (Level 1)
    "--glass": "rgba(255, 255, 255, 0.05)",
    "--glass-border": "rgba(255, 255, 255, 0.1)",
    "--glass-hover": "rgba(255, 255, 255, 0.08)"
}

FALLBACK_LIGHT = {
    # רקעים וטקסט
    "--bg-primary": "#ffffff",
    "--bg-secondary": "#f3f3f3",
    "--bg-tertiary": "#e5e5e5",
    "--text-primary": "#333333",
    "--text-secondary": "#616161",
    "--text-muted": "#9e9e9e",
    
    # צבעי מותג
    "--primary": "#007acc",
    "--primary-hover": "#005a9e",
    "--primary-light": "#007acc26",
    
    # גבולות וצללים
    "--border-color": "#d4d4d4",
    "--shadow-color": "rgba(0, 0, 0, 0.1)",
    
    # סטטוסים (Level 1)
    "--success": "#388a34",
    "--warning": "#bf8803",
    "--error": "#e51400",
    "--danger-bg": "#e51400",
    "--danger-border": "#c62828",
    "--text-on-warning": "#1a1a1a",
    
    # קוד
    "--code-bg": "#f3f3f3",
    "--code-text": "#333333",
    "--code-border": "#d4d4d4",
    
    # UI elements
    "--link-color": "#007acc",
    "--navbar-bg": "#dddddd",
    "--card-bg": "#ffffff",
    "--card-border": "#d4d4d4",
    "--input-bg": "#ffffff",
    "--input-border": "#cecece",
    
    # כפתורים (Level 2)
    "--btn-primary-bg": "#007acc",
    "--btn-primary-color": "#ffffff",
    "--btn-primary-border": "#007acc",
    "--btn-primary-shadow": "rgba(0, 122, 204, 0.3)",
    "--btn-primary-hover-bg": "#005a9e",
    "--btn-primary-hover-color": "#ffffff",
    
    # Markdown & Split View - נשאר כהה גם בתמה בהירה!
    "--md-surface": "#1e1e1e",
    "--md-text": "#d4d4d4",
    
    # Glass (Level 1)
    "--glass": "rgba(0, 0, 0, 0.02)",
    "--glass-border": "rgba(0, 0, 0, 0.05)",
    "--glass-hover": "rgba(0, 0, 0, 0.04)"
}

# ==========================================
# 🔒 SECURITY: Regex לוולידציה של צבעים
# ==========================================
# ⚠️ אזהרה חשובה: ה-Regex הזה מכוון להיות **מגביל**.
# אל תרחיב אותו לקבל פורמטים נוספים ללא בדיקה קפדנית!
# 
# CSS מאפשר ערכים מסוכנים כמו:
#   - url('https://evil.com/track.gif')  → מעקב/XSS
#   - expression(alert())                → JS injection (IE)
#   - var(--user-input)                  → injection דרך משתנים
#   - calc(...)                          → עלול לשמש לעקיפות
#
# ה-Regex הנוכחי מאפשר **רק**:
#   - Hex: #fff, #ffffff, #ffffff80
#   - RGB: rgb(r, g, b)
#   - RGBA: rgba(r, g, b, a)
#
# זה מספיק לכל צורך תקין של ערכות נושא.
# ==========================================

VALID_COLOR_REGEX = re.compile(
    r'^#[0-9a-fA-F]{3,8}$|'  # hex (3, 4, 6, or 8 chars)
    r'^rgb\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\)$|'  # rgb
    r'^rgba\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*[\d.]+\s*\)$'  # rgba
)

# רשימה לבנה של משתני CSS מותרים - אל תוסיף משתנים ללא בדיקה
# ⚠️ הרשימה מסונכרנת עם מסמך הארכיטקטורה: docs/webapp/theming_and_css.rst
ALLOWED_VARIABLES_WHITELIST = frozenset([
    # Level 1 - Primitives
    "--primary", "--primary-hover", "--primary-light",
    "--secondary",
    "--success", "--warning", "--error",
    "--danger-bg", "--danger-border", "--text-on-warning",
    "--glass", "--glass-blur", "--glass-border", "--glass-hover",
    
    # Level 2 - Semantic Tokens (רקעים וטקסט)
    "--bg-primary", "--bg-secondary", "--bg-tertiary",
    "--text-primary", "--text-secondary", "--text-muted",
    "--border-color", "--shadow-color",
    "--card-bg", "--card-border",
    "--navbar-bg",
    "--input-bg", "--input-border",
    "--link-color",
    "--code-bg", "--code-text", "--code-border",
    
    # Level 2 - כפתורים (Button Tokens)
    "--btn-primary-bg", "--btn-primary-color", "--btn-primary-border", "--btn-primary-shadow",
    "--btn-primary-hover-bg", "--btn-primary-hover-color",
    
    # Level 2 - Markdown & Split View
    "--md-surface", "--md-text",
    "--split-preview-bg", "--split-preview-meta", "--split-preview-placeholder"
])


def sanitize_css_value(value: str) -> str | None:
    """
    מנקה ומוודא שערך CSS בטוח לשימוש.
    
    ⚠️ מחזיר None אם הערך לא בטוח!
    
    Args:
        value: ערך CSS לבדיקה
        
    Returns:
        הערך המנוקה, או None אם לא בטוח
    """
    if not value or not isinstance(value, str):
        return None
    
    value = value.strip().lower()
    
    # חסימת ערכים מסוכנים במפורש
    dangerous_patterns = [
        'url(', 'expression(', 'javascript:', 
        'data:', 'behavior:', 'binding:',
        '@import', '@charset', '<', '>', 
        '/*', '*/', '\\', '\n', '\r'
    ]
    
    for pattern in dangerous_patterns:
        if pattern in value:
            logger.warning(f"Blocked dangerous CSS value: {value[:50]}...")
            return None
    
    # וולידציה כצבע
    if VALID_COLOR_REGEX.match(value):
        return value
    
    return None


def validate_and_sanitize_theme_variables(variables: dict) -> dict:
    """
    מוודא ומנקה את כל המשתנים בערכה.
    
    Args:
        variables: מילון של משתני CSS
        
    Returns:
        מילון מנוקה עם רק משתנים בטוחים
    """
    sanitized = {}
    
    for key, value in variables.items():
        # בדיקה שהמפתח ברשימה הלבנה
        if key not in ALLOWED_VARIABLES_WHITELIST:
            logger.warning(f"Skipped unknown variable: {key}")
            continue
        
        # ניקוי הערך
        clean_value = sanitize_css_value(value)
        if clean_value:
            sanitized[key] = clean_value
        else:
            logger.warning(f"Skipped invalid value for {key}: {value[:30]}...")
    
    return sanitized


def is_valid_color(value: str) -> bool:
    """בודק אם הערך הוא צבע תקני."""
    if not value:
        return False
    return bool(VALID_COLOR_REGEX.match(value.strip()))


def parse_vscode_theme(json_content: str | dict) -> dict:
    """
    מפרסר ערכת VS Code ומייצר מילון של CSS Variables.
    
    Args:
        json_content: תוכן JSON כמחרוזת או כמילון
        
    Returns:
        מילון עם CSS Variables
        
    Raises:
        ValueError: אם ה-JSON לא תקין או חסרים שדות חובה
    """
    # פרסור JSON אם מגיע כמחרוזת
    if isinstance(json_content, str):
        try:
            theme_data = json.loads(json_content)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}")
    else:
        theme_data = json_content
    
    # בדיקת מבנה בסיסי
    if not isinstance(theme_data, dict):
        raise ValueError("Theme must be a JSON object")
    
    colors = theme_data.get("colors", {})
    if not colors:
        raise ValueError("Theme must contain a 'colors' object")
    
    # קביעת סוג הערכה
    theme_type = theme_data.get("type", "dark").lower()
    fallback = FALLBACK_DARK if theme_type == "dark" else FALLBACK_LIGHT
    
    # מיפוי הצבעים
    result = fallback.copy()
    
    for vscode_key, css_vars in VSCODE_TO_CSS_MAP.items():
        if vscode_key in colors:
            color_value = colors[vscode_key]
            if is_valid_color(color_value):
                # תמיכה במיפוי לרשימה של משתנים (כשמפתח אחד ממלא כמה טוקנים)
                if isinstance(css_vars, list):
                    for css_var in css_vars:
                        result[css_var] = color_value
                else:
                    result[css_vars] = color_value
            else:
                logger.warning(f"Invalid color value for {vscode_key}: {color_value}")
    
    # חישוב צבעים נגזרים
    result = _compute_derived_colors(result)
    
    return {
        "name": theme_data.get("name", "Imported Theme"),
        "type": theme_type,
        "variables": result
    }


def _compute_derived_colors(variables: dict) -> dict:
    """
    מחשב צבעים נגזרים שלא קיימים ישירות ב-VS Code.
    """
    result = variables.copy()
    
    # primary-light מבוסס על primary
    if "--primary" in result and "--primary-light" not in result:
        primary = result["--primary"]
        # המרה בטוחה ל-RGBA עם שקיפות
        result["--primary-light"] = color_with_opacity(primary, 0.15)
    
    # shadow-color מבוסס על סוג הערכה
    if "--shadow-color" not in result:
        bg = result.get("--bg-primary", "#000")
        if _is_dark_color(bg):
            result["--shadow-color"] = "rgba(0, 0, 0, 0.4)"
        else:
            result["--shadow-color"] = "rgba(0, 0, 0, 0.1)"
    
    return result


# ==========================================
# פונקציות עזר למניפולציית צבעים בטוחה
# ==========================================

def normalize_color_to_rgba(color: str) -> tuple[int, int, int, float] | None:
    """
    ממיר כל פורמט צבע תקני ל-tuple של (R, G, B, A).
    
    תומך ב:
    - Hex מקוצר: #fff
    - Hex מלא: #ffffff
    - Hex עם alpha: #ffffff80
    - RGB: rgb(255, 255, 255)
    - RGBA: rgba(255, 255, 255, 0.5)
    
    Returns:
        tuple (r, g, b, a) כאשר r,g,b הם 0-255 ו-a הוא 0-1
        או None אם הצבע לא תקין
    """
    if not color:
        return None
    
    color = color.strip().lower()
    
    # Hex format
    if color.startswith("#"):
        hex_val = color[1:]
        
        # #fff -> #ffffff
        if len(hex_val) == 3:
            hex_val = "".join(c * 2 for c in hex_val)
            alpha = 1.0
        # #ffff -> #ffffffff (עם alpha)
        elif len(hex_val) == 4:
            hex_val = "".join(c * 2 for c in hex_val[:3])
            alpha = int(color[4] * 2, 16) / 255
        # #ffffff
        elif len(hex_val) == 6:
            alpha = 1.0
        # #ffffff80 (עם alpha)
        elif len(hex_val) == 8:
            alpha = int(hex_val[6:8], 16) / 255
            hex_val = hex_val[:6]
        else:
            return None
        
        try:
            r = int(hex_val[0:2], 16)
            g = int(hex_val[2:4], 16)
            b = int(hex_val[4:6], 16)
            return (r, g, b, alpha)
        except ValueError:
            return None
    
    # RGB format
    rgb_match = re.match(r'rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)', color)
    if rgb_match:
        r, g, b = map(int, rgb_match.groups())
        if all(0 <= c <= 255 for c in (r, g, b)):
            return (r, g, b, 1.0)
        return None
    
    # RGBA format
    rgba_match = re.match(
        r'rgba\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*([\d.]+)\s*\)', 
        color
    )
    if rgba_match:
        r, g, b = map(int, rgba_match.groups()[:3])
        a = float(rgba_match.group(4))
        if all(0 <= c <= 255 for c in (r, g, b)) and 0 <= a <= 1:
            return (r, g, b, a)
        return None
    
    return None


def rgba_to_css(r: int, g: int, b: int, a: float) -> str:
    """
    ממיר RGBA tuple למחרוזת CSS.
    """
    if a >= 0.999:
        # ללא שקיפות - מחזיר hex
        return f"#{r:02x}{g:02x}{b:02x}"
    else:
        return f"rgba({r}, {g}, {b}, {a:.2f})"


def color_with_opacity(color: str, opacity: float) -> str:
    """
    מחזיר צבע עם שקיפות חדשה.
    
    Args:
        color: צבע בכל פורמט תקני
        opacity: שקיפות חדשה (0-1)
        
    Returns:
        צבע בפורמט rgba()
        
    Example:
        >>> color_with_opacity("#ff0000", 0.5)
        'rgba(255, 0, 0, 0.50)'
        >>> color_with_opacity("rgb(255, 0, 0)", 0.15)
        'rgba(255, 0, 0, 0.15)'
    """
    rgba = normalize_color_to_rgba(color)
    if rgba is None:
        # fallback - מחזיר צבע שקוף
        return "rgba(128, 128, 128, 0.15)"
    
    r, g, b, _ = rgba
    return rgba_to_css(r, g, b, opacity)


def lighten_color(color: str, amount: float = 0.2) -> str:
    """
    מבהיר צבע.
    
    Args:
        color: צבע בכל פורמט
        amount: כמה להבהיר (0-1)
    """
    rgba = normalize_color_to_rgba(color)
    if rgba is None:
        return color
    
    r, g, b, a = rgba
    r = min(255, int(r + (255 - r) * amount))
    g = min(255, int(g + (255 - g) * amount))
    b = min(255, int(b + (255 - b) * amount))
    
    return rgba_to_css(r, g, b, a)


def darken_color(color: str, amount: float = 0.2) -> str:
    """
    מכהה צבע.
    
    Args:
        color: צבע בכל פורמט
        amount: כמה להכהות (0-1)
    """
    rgba = normalize_color_to_rgba(color)
    if rgba is None:
        return color
    
    r, g, b, a = rgba
    r = max(0, int(r * (1 - amount)))
    g = max(0, int(g * (1 - amount)))
    b = max(0, int(b * (1 - amount)))
    
    return rgba_to_css(r, g, b, a)


def _is_dark_color(hex_color: str) -> bool:
    """
    בודק אם צבע hex הוא כהה (luminance נמוך).
    """
    if not hex_color.startswith("#"):
        return True  # default to dark
    
    hex_val = hex_color.lstrip("#")
    if len(hex_val) == 3:
        hex_val = "".join(c*2 for c in hex_val)
    
    try:
        r = int(hex_val[0:2], 16)
        g = int(hex_val[2:4], 16)
        b = int(hex_val[4:6], 16)
        
        # חישוב luminance
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return luminance < 0.5
    except (ValueError, IndexError):
        return True


def validate_theme_json(json_content: str) -> tuple[bool, str]:
    """
    מוודא שקובץ JSON הוא ערכת נושא תקינה.
    
    Returns:
        tuple של (האם_תקין, הודעת_שגיאה_אם_לא)
    """
    try:
        data = json.loads(json_content)
    except json.JSONDecodeError as e:
        return False, f"קובץ JSON לא תקין: {e}"
    
    if not isinstance(data, dict):
        return False, "הקובץ חייב להיות אובייקט JSON"
    
    # בדיקה אם זו ערכת VS Code
    if "colors" in data:
        if not isinstance(data["colors"], dict):
            return False, "'colors' חייב להיות אובייקט"
        if len(data["colors"]) < 3:
            return False, "ערכת VS Code חייבת להכיל לפחות 3 צבעים"
        return True, ""
    
    # בדיקה אם זו ערכה בפורמט שלנו
    if "variables" in data:
        if not isinstance(data["variables"], dict):
            return False, "'variables' חייב להיות אובייקט"
        
        # בדיקת צבעים
        for key, value in data["variables"].items():
            if not key.startswith("--"):
                return False, f"משתנה CSS חייב להתחיל ב---: {key}"
            if not is_valid_color(value):
                return False, f"ערך צבע לא תקין: {key}={value}"
        
        return True, ""
    
    return False, "הקובץ חייב להכיל 'colors' (VS Code) או 'variables' (פורמט מקומי)"


def parse_native_theme(json_content: str | dict) -> dict:
    """
    מפרסר ערכה בפורמט המקומי שלנו.
    
    Args:
        json_content: JSON עם name ו-variables
        
    Returns:
        מילון מוכן להכנסה ל-DB
    """
    if isinstance(json_content, str):
        data = json.loads(json_content)
    else:
        data = json_content
    
    # וולידציה
    variables = data.get("variables", {})
    validated_vars = {}
    
    for key, value in variables.items():
        if key.startswith("--") and is_valid_color(value):
            validated_vars[key] = value
    
    return {
        "name": data.get("name", "Imported Theme"),
        "description": data.get("description", ""),
        "variables": validated_vars
    }


def export_theme_to_json(theme: dict) -> str:
    """
    מייצא ערכה לפורמט JSON להורדה.
    
    Args:
        theme: מילון הערכה מה-DB
        
    Returns:
        מחרוזת JSON מפורמטת
    """
    export_data = {
        "name": theme.get("name", "Exported Theme"),
        "description": theme.get("description", ""),
        "version": "1.0",
        "variables": theme.get("variables", {})
    }
    
    return json.dumps(export_data, indent=2, ensure_ascii=False)
```

### זרימת ייבוא VS Code

```
┌──────────────────┐
│  קובץ .json      │
│  (VS Code theme) │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ validate_theme_  │
│ json()           │
└────────┬─────────┘
         │ תקין?
         ▼
┌──────────────────┐
│ parse_vscode_    │
│ theme()          │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ VSCODE_TO_CSS_   │
│ MAP mapping      │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ נשמר ב-MongoDB   │
│ custom_themes[]  │
└──────────────────┘
```

---

## ייבוא ידני של קובץ JSON

### API Endpoint לייבוא

**`webapp/themes_api.py`** (חלק מהקובץ):

```python
from flask import Blueprint, request, jsonify
from services.theme_parser_service import (
    parse_vscode_theme, 
    parse_native_theme,
    validate_theme_json,
    export_theme_to_json
)
import uuid
from datetime import datetime

themes_bp = Blueprint('themes', __name__, url_prefix='/api/themes')

MAX_THEME_FILE_SIZE = 512 * 1024  # 512KB מקסימום
MAX_THEMES_PER_USER = 10

# רשימת משתני CSS מותרים - מסונכרנת עם ALLOWED_VARIABLES_WHITELIST ב-theme_parser_service.py
ALLOWED_VARIABLES = [
    # Level 1 - Primitives
    "--primary", "--primary-hover", "--primary-light",
    "--secondary",
    "--success", "--warning", "--error",
    "--danger-bg", "--danger-border", "--text-on-warning",
    "--glass", "--glass-blur", "--glass-border", "--glass-hover",
    
    # Level 2 - Semantic Tokens
    "--bg-primary", "--bg-secondary", "--bg-tertiary",
    "--text-primary", "--text-secondary", "--text-muted",
    "--border-color", "--shadow-color",
    "--card-bg", "--card-border",
    "--navbar-bg",
    "--input-bg", "--input-border",
    "--link-color",
    "--code-bg", "--code-text", "--code-border",
    
    # Level 2 - Button Tokens
    "--btn-primary-bg", "--btn-primary-color", "--btn-primary-border", "--btn-primary-shadow",
    "--btn-primary-hover-bg", "--btn-primary-hover-color",
    
    # Level 2 - Markdown & Split View
    "--md-surface", "--md-text",
    "--split-preview-bg", "--split-preview-meta", "--split-preview-placeholder"
]


@themes_bp.route('/import', methods=['POST'])
@login_required
def import_theme():
    """
    ייבוא ערכת נושא מקובץ JSON.
    
    תומך בשני פורמטים:
    1. VS Code theme (עם colors)
    2. פורמט מקומי (עם variables)
    
    Request:
        - file: קובץ JSON (multipart/form-data)
        או
        - json_content: תוכן JSON כמחרוזת (application/json)
    
    Response:
        - success: true/false
        - theme: הערכה שנוצרה (אם הצליח)
        - error: הודעת שגיאה (אם נכשל)
    """
    user_id = get_current_user_id()
    
    # בדיקת מגבלת ערכות
    user = db.users.find_one({"_id": user_id})
    current_themes = user.get("custom_themes", [])
    if len(current_themes) >= MAX_THEMES_PER_USER:
        return jsonify({
            "success": False,
            "error": f"הגעת למגבלה של {MAX_THEMES_PER_USER} ערכות מותאמות אישית"
        }), 400
    
    # קבלת התוכן
    json_content = None
    
    if 'file' in request.files:
        file = request.files['file']
        if file.filename == '':
            return jsonify({"success": False, "error": "לא נבחר קובץ"}), 400
        
        if not file.filename.endswith('.json'):
            return jsonify({"success": False, "error": "הקובץ חייב להיות בסיומת .json"}), 400
        
        # בדיקת גודל
        file.seek(0, 2)
        size = file.tell()
        file.seek(0)
        
        if size > MAX_THEME_FILE_SIZE:
            return jsonify({
                "success": False, 
                "error": f"הקובץ גדול מדי (מקסימום {MAX_THEME_FILE_SIZE // 1024}KB)"
            }), 400
        
        json_content = file.read().decode('utf-8')
    
    elif request.is_json:
        json_content = request.json.get('json_content', '')
    
    if not json_content:
        return jsonify({"success": False, "error": "לא התקבל תוכן"}), 400
    
    # וולידציה
    is_valid, error_msg = validate_theme_json(json_content)
    if not is_valid:
        return jsonify({"success": False, "error": error_msg}), 400
    
    # פרסור
    try:
        data = json.loads(json_content)
        
        if "colors" in data:
            # VS Code format
            parsed = parse_vscode_theme(data)
            source = "vscode"
        else:
            # Native format
            parsed = parse_native_theme(data)
            source = "import"
        
        # סינון רק משתנים מותרים
        filtered_vars = {
            k: v for k, v in parsed.get("variables", {}).items()
            if k in ALLOWED_VARIABLES
        }
        
        # יצירת ערכה חדשה
        new_theme = {
            "id": str(uuid.uuid4()),
            "name": parsed.get("name", "Imported Theme"),
            "description": parsed.get("description", f"Imported from {source}"),
            "is_active": False,
            "source": source,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "variables": filtered_vars
        }
        
        # שמירה
        db.users.update_one(
            {"_id": user_id},
            {"$push": {"custom_themes": new_theme}}
        )
        
        return jsonify({
            "success": True,
            "theme": {
                "id": new_theme["id"],
                "name": new_theme["name"],
                "source": source
            },
            "message": "הערכה יובאה בהצלחה!"
        })
        
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("Theme import error")
        return jsonify({"success": False, "error": "שגיאה בייבוא הערכה"}), 500


@themes_bp.route('/<theme_id>/export', methods=['GET'])
@login_required
def export_theme(theme_id):
    """
    ייצוא ערכה לקובץ JSON.
    """
    user_id = get_current_user_id()
    user = db.users.find_one({"_id": user_id})
    
    theme = next(
        (t for t in user.get("custom_themes", []) if t["id"] == theme_id),
        None
    )
    
    if not theme:
        return jsonify({"success": False, "error": "ערכה לא נמצאה"}), 404
    
    json_content = export_theme_to_json(theme)
    
    return Response(
        json_content,
        mimetype='application/json',
        headers={
            'Content-Disposition': f'attachment; filename="{theme["name"]}.json"'
        }
    )
```

---

## עורך ערכות נושא משופר

### UI להעלאת קובץ ובחירת Preset

להוסיף ל-`theme_builder.html` (בתוך הסיידבר או כטאבים):

```html
<!-- קטע חדש בתוך theme-builder-sidebar -->
<div class="theme-source-tabs">
    <button class="tab-btn active" data-tab="my-themes">
        <i class="fas fa-palette"></i>
        הערכות שלי
    </button>
    <button class="tab-btn" data-tab="presets">
        <i class="fas fa-star"></i>
        ערכות פופולריות
    </button>
    <button class="tab-btn" data-tab="import">
        <i class="fas fa-file-import"></i>
        ייבוא
    </button>
</div>

<!-- תוכן טאב: הערכות שלי -->
<div class="tab-content active" id="my-themes-tab">
    <div id="themesList" class="themes-list">
        <!-- נטען דינמית -->
    </div>
    <button id="createNewThemeBtn" class="btn btn-outline-primary w-100 mt-3">
        <i class="fas fa-plus"></i> ערכה חדשה
    </button>
</div>

<!-- תוכן טאב: ערכות פופולריות -->
<div class="tab-content" id="presets-tab">
    <div class="presets-filter mb-3">
        <button class="filter-btn active" data-filter="all">הכל</button>
        <button class="filter-btn" data-filter="light">בהירות</button>
        <button class="filter-btn" data-filter="dark">כהות</button>
    </div>
    <div id="presetsList" class="presets-gallery">
        <!-- נטען דינמית -->
    </div>
</div>

<!-- תוכן טאב: ייבוא -->
<div class="tab-content" id="import-tab">
    <div class="import-section">
        <h4>ייבוא מ-VS Code</h4>
        <p class="text-muted small">
            העלה קובץ JSON של ערכת VS Code (למשל מ-
            <a href="https://vscodethemes.com" target="_blank">vscodethemes.com</a>)
        </p>
        
        <div class="upload-area" id="uploadArea">
            <i class="fas fa-cloud-upload-alt fa-3x mb-3"></i>
            <p>גרור קובץ לכאן או לחץ לבחירה</p>
            <input type="file" id="themeFileInput" accept=".json" hidden>
        </div>
        
        <div class="upload-status mt-3" id="uploadStatus" style="display: none;">
            <div class="spinner-border spinner-border-sm me-2"></div>
            <span>מייבא...</span>
        </div>
    </div>
    
    <hr class="my-4">
    
    <div class="import-section">
        <h4>ייבוא מ-JSON</h4>
        <p class="text-muted small">
            הדבק את תוכן הערכה בפורמט JSON
        </p>
        <textarea 
            id="jsonInput" 
            class="form-control" 
            rows="6" 
            placeholder='{"name": "My Theme", "variables": {...}}'
        ></textarea>
        <button id="importJsonBtn" class="btn btn-primary mt-2 w-100">
            <i class="fas fa-file-import"></i> ייבוא
        </button>
    </div>
</div>
```

### CSS לקטעים החדשים

```css
/* טאבים */
.theme-source-tabs {
    display: flex;
    gap: 0.25rem;
    padding: 0.5rem;
    background: var(--bg-tertiary);
    border-radius: 8px;
    margin-bottom: 1rem;
}

.tab-btn {
    flex: 1;
    padding: 0.5rem;
    border: none;
    background: transparent;
    color: var(--text-secondary);
    border-radius: 6px;
    font-size: 0.85rem;
    cursor: pointer;
    transition: all 0.2s;
}

.tab-btn.active {
    background: var(--primary);
    color: white;
}

.tab-btn:hover:not(.active) {
    background: var(--bg-secondary);
}

.tab-content {
    display: none;
}

.tab-content.active {
    display: block;
}

/* גלריית Presets */
.presets-gallery {
    display: grid;
    gap: 0.75rem;
}

.preset-card {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.75rem;
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.2s;
}

.preset-card:hover {
    border-color: var(--primary);
    transform: translateX(-2px);
}

.preset-preview {
    display: flex;
    gap: 2px;
    border-radius: 4px;
    overflow: hidden;
}

.preset-preview-color {
    width: 20px;
    height: 36px;
}

.preset-info {
    flex: 1;
}

.preset-name {
    font-weight: 600;
    font-size: 0.9rem;
    color: var(--text-primary);
}

.preset-desc {
    font-size: 0.75rem;
    color: var(--text-muted);
}

/* אזור העלאה */
.upload-area {
    border: 2px dashed var(--border-color);
    border-radius: 12px;
    padding: 2rem;
    text-align: center;
    cursor: pointer;
    transition: all 0.3s;
    color: var(--text-muted);
}

.upload-area:hover,
.upload-area.drag-over {
    border-color: var(--primary);
    background: var(--primary-light);
}

.upload-area.drag-over {
    transform: scale(1.02);
}

/* סינון */
.presets-filter {
    display: flex;
    gap: 0.5rem;
}

.filter-btn {
    padding: 0.25rem 0.75rem;
    border: 1px solid var(--border-color);
    background: transparent;
    color: var(--text-secondary);
    border-radius: 20px;
    font-size: 0.8rem;
    cursor: pointer;
    transition: all 0.2s;
}

.filter-btn.active {
    background: var(--primary);
    color: white;
    border-color: var(--primary);
}

/* כפתור Revert Preview */
.revert-preview-btn {
    position: absolute;
    top: 1rem;
    left: 1rem;
    z-index: 10;
    display: none;
    align-items: center;
    gap: 0.5rem;
    animation: fadeIn 0.2s ease-in;
}

@keyframes fadeIn {
    from { opacity: 0; transform: translateY(-5px); }
    to { opacity: 1; transform: translateY(0); }
}
```

### JavaScript לייבוא ו-Presets

**`webapp/static/js/theme-importer.js`:**

```javascript
/**
 * Theme Importer Module
 * מנהל ייבוא ערכות מ-VS Code ו-JSON, וגלריית Presets
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

    // === Tab Navigation ===
    function initTabs() {
        tabBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const tabId = btn.dataset.tab;
                
                // עדכון כפתורים
                tabBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                
                // עדכון תוכן
                tabContents.forEach(content => {
                    content.classList.toggle('active', content.id === `${tabId}-tab`);
                });
                
                // טעינת presets אם נדרש
                if (tabId === 'presets' && presets.length === 0) {
                    loadPresets();
                }
            });
        });
    }

    // === Presets Gallery ===
    async function loadPresets() {
        try {
            const response = await fetch('/api/themes/presets');
            const data = await response.json();
            presets = data.presets || [];
            renderPresets();
        } catch (error) {
            console.error('Failed to load presets:', error);
            presetsList.innerHTML = '<p class="text-danger">שגיאה בטעינת הערכות</p>';
        }
    }

    function renderPresets() {
        const filtered = currentFilter === 'all' 
            ? presets 
            : presets.filter(p => p.category === currentFilter);
        
        presetsList.innerHTML = filtered.map(preset => `
            <div class="preset-card" data-preset-id="${preset.id}">
                <div class="preset-preview">
                    ${preset.preview_colors.map(c => 
                        `<div class="preset-preview-color" style="background: ${c}"></div>`
                    ).join('')}
                </div>
                <div class="preset-info">
                    <div class="preset-name">${preset.name}</div>
                    <div class="preset-desc">${preset.description}</div>
                </div>
                <button class="btn btn-sm btn-outline-primary apply-preset-btn">
                    <i class="fas fa-plus"></i>
                </button>
            </div>
        `).join('');
        
        // Event listeners לכפתורי Apply
        presetsList.querySelectorAll('.apply-preset-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const card = btn.closest('.preset-card');
                applyPreset(card.dataset.presetId);
            });
        });
        
        // לחיצה על כרטיס לתצוגה מקדימה
        presetsList.querySelectorAll('.preset-card').forEach(card => {
            card.addEventListener('click', () => {
                previewPreset(card.dataset.presetId);
            });
        });
    }

    async function applyPreset(presetId) {
        try {
            const response = await fetch(`/api/themes/presets/${presetId}/apply`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            
            const data = await response.json();
            
            if (data.success) {
                showToast('הערכה נוספה בהצלחה!', 'success');
                // רענון רשימת הערכות
                if (typeof fetchThemes === 'function') {
                    fetchThemes();
                }
                // מעבר לטאב "הערכות שלי"
                document.querySelector('[data-tab="my-themes"]').click();
            } else {
                showToast(data.error || 'שגיאה בהוספת הערכה', 'error');
            }
        } catch (error) {
            console.error('Apply preset error:', error);
            showToast('שגיאה בהוספת הערכה', 'error');
        }
    }

    // === Preview State Management ===
    let originalPreviewStyles = null;  // שומר את המצב המקורי לפני preview
    let isPreviewActive = false;

    function saveOriginalPreviewState() {
        /**
         * שומר את כל ה-CSS variables הנוכחיים של אזור התצוגה המקדימה.
         */
        const preview = document.getElementById('theme-preview-container');
        if (!preview || originalPreviewStyles !== null) return;
        
        originalPreviewStyles = {};
        const computedStyle = getComputedStyle(preview);
        
        // שומר את כל המשתנים הרלוונטיים
        // רשימה מסונכרנת עם ALLOWED_VARIABLES_WHITELIST
        const varsToSave = [
            // Level 1 & 2 - Semantic
            '--bg-primary', '--bg-secondary', '--bg-tertiary',
            '--text-primary', '--text-secondary', '--text-muted',
            '--primary', '--primary-hover', '--primary-light',
            '--border-color', '--shadow-color',
            '--success', '--warning', '--error',
            '--danger-bg', '--danger-border',
            '--code-bg', '--code-text', '--link-color',
            '--navbar-bg', '--card-bg', '--card-border',
            '--input-bg', '--input-border',
            // Level 2 - Button Tokens
            '--btn-primary-bg', '--btn-primary-color',
            '--btn-primary-border', '--btn-primary-hover-bg',
            // Level 2 - Markdown & Split View
            '--md-surface', '--md-text'
        ];
        
        varsToSave.forEach(varName => {
            const value = preview.style.getPropertyValue(varName) || 
                          computedStyle.getPropertyValue(varName);
            if (value) {
                originalPreviewStyles[varName] = value.trim();
            }
        });
    }

    function revertPreview() {
        /**
         * מחזיר את אזור התצוגה המקדימה למצב המקורי.
         */
        const preview = document.getElementById('theme-preview-container');
        if (!preview || !originalPreviewStyles) return;
        
        // מנקה את כל הסגנונות שהוחלו
        Object.keys(originalPreviewStyles).forEach(varName => {
            preview.style.removeProperty(varName);
        });
        
        // מחיל מחדש את המצב המקורי אם יש ערכה נבחרת
        if (selectedThemeId && !isNewTheme) {
            // טוען מחדש את הערכה הנוכחית
            fetchThemeDetails(selectedThemeId).then(theme => {
                if (theme && theme.variables) {
                    Object.entries(theme.variables).forEach(([key, value]) => {
                        preview.style.setProperty(key, value);
                    });
                }
            });
        }
        
        originalPreviewStyles = null;
        isPreviewActive = false;
        
        // מסתיר כפתור Revert
        const revertBtn = document.getElementById('revertPreviewBtn');
        if (revertBtn) {
            revertBtn.style.display = 'none';
        }
    }

    function previewPreset(presetId) {
        const preset = presets.find(p => p.id === presetId);
        if (!preset) return;
        
        // שומר את המצב המקורי לפני ה-preview
        saveOriginalPreviewState();
        
        // הבאת פרטי הערכה המלאים
        fetch(`/api/themes/presets/${presetId}`)
            .then(r => r.json())
            .then(data => {
                if (data.variables) {
                    // החלת תצוגה מקדימה
                    const preview = document.getElementById('theme-preview-container');
                    if (preview) {
                        Object.entries(data.variables).forEach(([key, value]) => {
                            preview.style.setProperty(key, value);
                        });
                    }
                    
                    isPreviewActive = true;
                    
                    // מציג כפתור Revert
                    showRevertButton();
                }
            });
    }

    function showRevertButton() {
        /**
         * מציג כפתור לביטול התצוגה המקדימה.
         */
        let revertBtn = document.getElementById('revertPreviewBtn');
        
        if (!revertBtn) {
            // יוצר את הכפתור אם לא קיים
            revertBtn = document.createElement('button');
            revertBtn.id = 'revertPreviewBtn';
            revertBtn.className = 'btn btn-outline-secondary btn-sm revert-preview-btn';
            revertBtn.innerHTML = '<i class="fas fa-undo"></i> בטל תצוגה מקדימה';
            revertBtn.addEventListener('click', revertPreview);
            
            // מוסיף ליד אזור התצוגה המקדימה
            const previewContainer = document.querySelector('.preview-header') ||
                                    document.getElementById('theme-preview-container')?.parentElement;
            if (previewContainer) {
                previewContainer.appendChild(revertBtn);
            }
        }
        
        revertBtn.style.display = 'inline-flex';
    }

    // מאזין ל-mouseleave מהגלריה לביטול אוטומטי (אופציונלי)
    function initPreviewAutoRevert() {
        const gallery = document.getElementById('presetsList');
        if (gallery) {
            gallery.addEventListener('mouseleave', () => {
                // ביטול אוטומטי אחרי 3 שניות אם לא נבחרה ערכה
                if (isPreviewActive) {
                    setTimeout(() => {
                        if (isPreviewActive) {
                            revertPreview();
                        }
                    }, 3000);
                }
            });
        }
    }

    // Filters
    function initFilters() {
        filterBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                currentFilter = btn.dataset.filter;
                filterBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                renderPresets();
            });
        });
    }

    // === File Upload ===
    function initUpload() {
        // Click to upload
        uploadArea.addEventListener('click', () => fileInput.click());
        
        // Drag & Drop
        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.classList.add('drag-over');
        });
        
        uploadArea.addEventListener('dragleave', () => {
            uploadArea.classList.remove('drag-over');
        });
        
        uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadArea.classList.remove('drag-over');
            
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                handleFileUpload(files[0]);
            }
        });
        
        // File input change
        fileInput.addEventListener('change', () => {
            if (fileInput.files.length > 0) {
                handleFileUpload(fileInput.files[0]);
            }
        });
    }

    async function handleFileUpload(file) {
        if (!file.name.endsWith('.json')) {
            showToast('יש לבחור קובץ JSON', 'error');
            return;
        }
        
        if (file.size > 512 * 1024) {
            showToast('הקובץ גדול מדי (מקסימום 512KB)', 'error');
            return;
        }
        
        uploadStatus.style.display = 'flex';
        
        const formData = new FormData();
        formData.append('file', file);
        
        try {
            const response = await fetch('/api/themes/import', {
                method: 'POST',
                body: formData
            });
            
            const data = await response.json();
            
            if (data.success) {
                showToast(`הערכה "${data.theme.name}" יובאה בהצלחה!`, 'success');
                if (typeof fetchThemes === 'function') {
                    fetchThemes();
                }
                document.querySelector('[data-tab="my-themes"]').click();
            } else {
                showToast(data.error || 'שגיאה בייבוא', 'error');
            }
        } catch (error) {
            console.error('Upload error:', error);
            showToast('שגיאה בייבוא הקובץ', 'error');
        } finally {
            uploadStatus.style.display = 'none';
            fileInput.value = '';
        }
    }

    // === JSON Import ===
    function initJsonImport() {
        importJsonBtn.addEventListener('click', async () => {
            const content = jsonInput.value.trim();
            
            if (!content) {
                showToast('יש להזין תוכן JSON', 'error');
                return;
            }
            
            // בדיקה בסיסית
            try {
                JSON.parse(content);
            } catch (e) {
                showToast('JSON לא תקין', 'error');
                return;
            }
            
            importJsonBtn.disabled = true;
            importJsonBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
            
            try {
                const response = await fetch('/api/themes/import', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ json_content: content })
                });
                
                const data = await response.json();
                
                if (data.success) {
                    showToast('הערכה יובאה בהצלחה!', 'success');
                    jsonInput.value = '';
                    if (typeof fetchThemes === 'function') {
                        fetchThemes();
                    }
                    document.querySelector('[data-tab="my-themes"]').click();
                } else {
                    showToast(data.error || 'שגיאה בייבוא', 'error');
                }
            } catch (error) {
                console.error('JSON import error:', error);
                showToast('שגיאה בייבוא', 'error');
            } finally {
                importJsonBtn.disabled = false;
                importJsonBtn.innerHTML = '<i class="fas fa-file-import"></i> ייבוא';
            }
        });
    }

    // === Toast Helper ===
    function showToast(message, type = 'info') {
        // משתמש בפונקציה הקיימת מ-theme_builder.html
        if (typeof window.showToast === 'function') {
            window.showToast(message, type);
        } else {
            console.log(`[${type}] ${message}`);
        }
    }

    // === Init ===
    function init() {
        initTabs();
        initFilters();
        initUpload();
        initJsonImport();
        initPreviewAutoRevert();  // מנגנון ביטול אוטומטי של preview
    }

    // התחלה כשה-DOM מוכן
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
```

---

## API Endpoints

### סיכום כל ה-Endpoints

| Method | Endpoint | תיאור |
|--------|----------|-------|
| `GET` | `/api/themes` | רשימת ערכות המשתמש |
| `GET` | `/api/themes/<id>` | פרטי ערכה ספציפית |
| `POST` | `/api/themes` | יצירת ערכה חדשה |
| `PUT` | `/api/themes/<id>` | עדכון ערכה |
| `DELETE` | `/api/themes/<id>` | מחיקת ערכה |
| `POST` | `/api/themes/<id>/activate` | הפעלת ערכה |
| `POST` | `/api/themes/deactivate` | ביטול ערכה מותאמת |
| `POST` | `/api/themes/import` | ייבוא ערכה מקובץ |
| `GET` | `/api/themes/<id>/export` | ייצוא ערכה |
| `GET` | `/api/themes/presets` | רשימת ערכות מוכנות |
| `GET` | `/api/themes/presets/<id>` | פרטי preset |
| `POST` | `/api/themes/presets/<id>/apply` | החלת preset למשתמש |

### דוגמאות Request/Response

#### ייבוא ערכה

**Request:**
```http
POST /api/themes/import
Content-Type: multipart/form-data

file: dracula.json
```

**Response (Success):**
```json
{
    "success": true,
    "theme": {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "name": "Dracula",
        "source": "vscode"
    },
    "message": "הערכה יובאה בהצלחה!"
}
```

**Response (Error):**
```json
{
    "success": false,
    "error": "קובץ JSON לא תקין: Expecting property name: line 5"
}
```

#### החלת Preset

**Request:**
```http
POST /api/themes/presets/github-dark/apply
Content-Type: application/json
```

**Response:**
```json
{
    "success": true,
    "theme": {
        "id": "660e8400-e29b-41d4-a716-446655440001",
        "name": "GitHub Dark"
    }
}
```

---

## בדיקות

### Unit Tests

**`tests/services/test_theme_parser_service.py`:**

```python
import pytest
from services.theme_parser_service import (
    parse_vscode_theme,
    parse_native_theme,
    validate_theme_json,
    is_valid_color,
    export_theme_to_json,
    # פונקציות עזר לצבעים
    normalize_color_to_rgba,
    color_with_opacity,
    # פונקציות אבטחה
    sanitize_css_value,
    validate_and_sanitize_theme_variables
)


class TestIsValidColor:
    def test_valid_hex_short(self):
        assert is_valid_color("#fff")
        assert is_valid_color("#FFF")
        
    def test_valid_hex_full(self):
        assert is_valid_color("#ffffff")
        assert is_valid_color("#282a36")
        
    def test_valid_hex_with_alpha(self):
        assert is_valid_color("#ffffff26")
        assert is_valid_color("#000000ff")
        
    def test_valid_rgb(self):
        assert is_valid_color("rgb(255, 255, 255)")
        assert is_valid_color("rgb(0,0,0)")
        
    def test_valid_rgba(self):
        assert is_valid_color("rgba(0, 0, 0, 0.5)")
        assert is_valid_color("rgba(255,255,255,1)")
        
    def test_invalid_colors(self):
        assert not is_valid_color("")
        assert not is_valid_color("red")  # named colors not allowed
        assert not is_valid_color("#gggggg")
        assert not is_valid_color("expression(alert())")


class TestColorNormalization:
    """בדיקות לפונקציות המרת צבעים."""
    
    def test_hex_short_to_rgba(self):
        result = normalize_color_to_rgba("#fff")
        assert result == (255, 255, 255, 1.0)
        
    def test_hex_full_to_rgba(self):
        result = normalize_color_to_rgba("#ff0000")
        assert result == (255, 0, 0, 1.0)
        
    def test_hex_with_alpha_to_rgba(self):
        result = normalize_color_to_rgba("#ff000080")
        assert result[0] == 255
        assert result[1] == 0
        assert result[2] == 0
        assert 0.49 < result[3] < 0.51  # ~0.5
        
    def test_rgb_to_rgba(self):
        result = normalize_color_to_rgba("rgb(100, 150, 200)")
        assert result == (100, 150, 200, 1.0)
        
    def test_rgba_to_rgba(self):
        result = normalize_color_to_rgba("rgba(100, 150, 200, 0.75)")
        assert result == (100, 150, 200, 0.75)
        
    def test_invalid_returns_none(self):
        assert normalize_color_to_rgba("red") is None
        assert normalize_color_to_rgba("url(...)") is None
        assert normalize_color_to_rgba("") is None


class TestColorWithOpacity:
    """בדיקות להוספת שקיפות לצבע."""
    
    def test_hex_with_opacity(self):
        result = color_with_opacity("#ff0000", 0.5)
        assert "rgba(255, 0, 0, 0.50)" == result
        
    def test_rgb_with_opacity(self):
        result = color_with_opacity("rgb(255, 0, 0)", 0.15)
        assert "rgba(255, 0, 0, 0.15)" == result
        
    def test_short_hex_with_opacity(self):
        result = color_with_opacity("#f00", 0.25)
        assert "rgba(255, 0, 0, 0.25)" == result
        
    def test_invalid_color_returns_fallback(self):
        result = color_with_opacity("invalid", 0.5)
        assert "rgba" in result  # יחזיר fallback


class TestSanitization:
    """בדיקות אבטחה לניקוי ערכי CSS."""
    
    def test_blocks_url(self):
        assert sanitize_css_value("url('https://evil.com')") is None
        
    def test_blocks_expression(self):
        assert sanitize_css_value("expression(alert(1))") is None
        
    def test_blocks_javascript(self):
        assert sanitize_css_value("javascript:alert(1)") is None
        
    def test_blocks_data_uri(self):
        assert sanitize_css_value("data:text/html,<script>") is None
        
    def test_blocks_html_tags(self):
        assert sanitize_css_value("<script>") is None
        assert sanitize_css_value("</style>") is None
        
    def test_allows_valid_colors(self):
        assert sanitize_css_value("#ff0000") == "#ff0000"
        assert sanitize_css_value("rgb(255,0,0)") == "rgb(255,0,0)"
        
    def test_validate_theme_variables_filters_unknown(self):
        variables = {
            "--bg-primary": "#000",
            "--unknown-var": "#fff",
            "--text-primary": "url(evil)"
        }
        result = validate_and_sanitize_theme_variables(variables)
        
        assert "--bg-primary" in result
        assert "--unknown-var" not in result
        assert "--text-primary" not in result  # blocked due to url


class TestValidateThemeJson:
    def test_valid_vscode_theme(self):
        json_content = '''
        {
            "name": "Test",
            "colors": {
                "editor.background": "#282a36",
                "editor.foreground": "#f8f8f2",
                "button.background": "#bd93f9"
            }
        }
        '''
        is_valid, error = validate_theme_json(json_content)
        assert is_valid
        assert error == ""
    
    def test_valid_native_theme(self):
        json_content = '''
        {
            "name": "Test",
            "variables": {
                "--bg-primary": "#282a36",
                "--text-primary": "#f8f8f2"
            }
        }
        '''
        is_valid, error = validate_theme_json(json_content)
        assert is_valid
        
    def test_invalid_json(self):
        is_valid, error = validate_theme_json("{invalid json}")
        assert not is_valid
        assert "JSON" in error
        
    def test_missing_colors_and_variables(self):
        is_valid, error = validate_theme_json('{"name": "Test"}')
        assert not is_valid
        assert "colors" in error or "variables" in error


class TestParseVscodeTheme:
    def test_basic_parsing(self):
        theme = {
            "name": "Dracula",
            "type": "dark",
            "colors": {
                "editor.background": "#282a36",
                "editor.foreground": "#f8f8f2",
                "button.background": "#bd93f9",
                "button.foreground": "#f8f8f2"
            }
        }
        result = parse_vscode_theme(theme)
        
        assert result["name"] == "Dracula"
        assert result["type"] == "dark"
        # מיפויים עם רשימות - editor.background ממלא גם --md-surface
        assert result["variables"]["--bg-primary"] == "#282a36"
        assert result["variables"]["--md-surface"] == "#282a36"
        # editor.foreground ממלא גם --md-text
        assert result["variables"]["--text-primary"] == "#f8f8f2"
        assert result["variables"]["--md-text"] == "#f8f8f2"
        # כפתורים ממופים לטוקנים הייעודיים (לא ל---primary!)
        assert result["variables"]["--btn-primary-bg"] == "#bd93f9"
        assert result["variables"]["--btn-primary-color"] == "#f8f8f2"
    
    def test_uses_fallback_for_missing(self):
        theme = {
            "name": "Minimal",
            "type": "dark",
            "colors": {
                "editor.background": "#000"
            }
        }
        result = parse_vscode_theme(theme)
        
        # Should have fallback values
        assert "--success" in result["variables"]
        assert "--error" in result["variables"]
        
    def test_filters_invalid_colors(self):
        theme = {
            "name": "Test",
            "colors": {
                "editor.background": "expression()",
                "editor.foreground": "#f8f8f2"
            }
        }
        result = parse_vscode_theme(theme)
        
        # Invalid color should be fallback, not the injected value
        assert "expression" not in result["variables"]["--bg-primary"]


class TestParseNativeTheme:
    def test_basic_parsing(self):
        theme = {
            "name": "My Theme",
            "description": "A test theme",
            "variables": {
                "--bg-primary": "#123456",
                "--text-primary": "#abcdef"
            }
        }
        result = parse_native_theme(theme)
        
        assert result["name"] == "My Theme"
        assert result["variables"]["--bg-primary"] == "#123456"
        
    def test_filters_invalid_vars(self):
        theme = {
            "name": "Test",
            "variables": {
                "--bg-primary": "#valid",
                "invalid-var": "#000",  # missing --
                "--text-primary": "not-a-color"
            }
        }
        result = parse_native_theme(theme)
        
        # Only valid variable should be included
        assert "--bg-primary" not in result["variables"] or result["variables"]["--bg-primary"] == "#valid"
        assert "invalid-var" not in result["variables"]


class TestExportThemeToJson:
    def test_export_format(self):
        theme = {
            "name": "Exported",
            "description": "Test export",
            "variables": {
                "--bg-primary": "#000"
            }
        }
        json_str = export_theme_to_json(theme)
        
        import json
        data = json.loads(json_str)
        
        assert data["name"] == "Exported"
        assert data["version"] == "1.0"
        assert data["variables"]["--bg-primary"] == "#000"
```

### Integration Tests

**`tests/webapp/test_themes_api.py`:**

```python
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_headers(client):
    # Login and return headers with session
    # (implementation depends on your auth system)
    pass


class TestThemesImportAPI:
    def test_import_vscode_theme_success(self, client, auth_headers):
        vscode_theme = {
            "name": "Test Theme",
            "type": "dark",
            "colors": {
                "editor.background": "#1e1e1e",
                "editor.foreground": "#d4d4d4",
                "button.background": "#007acc"
            }
        }
        
        response = client.post(
            '/api/themes/import',
            json={"json_content": json.dumps(vscode_theme)},
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"]
        assert data["theme"]["source"] == "vscode"
    
    def test_import_rejects_invalid_json(self, client, auth_headers):
        response = client.post(
            '/api/themes/import',
            json={"json_content": "not valid json {"},
            headers=auth_headers
        )
        
        assert response.status_code == 400
        data = response.get_json()
        assert not data["success"]
        assert "JSON" in data["error"]
    
    def test_import_file_upload(self, client, auth_headers, tmp_path):
        theme_file = tmp_path / "theme.json"
        theme_file.write_text('{"name":"File Theme","colors":{"editor.background":"#000"}}')
        
        with open(theme_file, 'rb') as f:
            response = client.post(
                '/api/themes/import',
                data={"file": (f, "theme.json")},
                headers=auth_headers,
                content_type='multipart/form-data'
            )
        
        assert response.status_code == 200


class TestPresetsAPI:
    def test_list_presets(self, client, auth_headers):
        response = client.get('/api/themes/presets', headers=auth_headers)
        
        assert response.status_code == 200
        data = response.get_json()
        assert "presets" in data
        assert len(data["presets"]) > 0
        
        # Check structure
        preset = data["presets"][0]
        assert "id" in preset
        assert "name" in preset
        assert "category" in preset
    
    def test_get_preset_details(self, client, auth_headers):
        response = client.get('/api/themes/presets/dracula', headers=auth_headers)
        
        assert response.status_code == 200
        data = response.get_json()
        assert data["name"] == "Dracula"
        assert "variables" in data
    
    def test_apply_preset(self, client, auth_headers):
        response = client.post(
            '/api/themes/presets/github-light/apply',
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"]
        assert data["theme"]["name"] == "GitHub Light"
```

---

## נגישות ו-UX

### בדיקת ניגודיות (WCAG 2.1)

המערכת כוללת בדיקת ניגודיות אוטומטית:

```javascript
/**
 * בודק יחס ניגודיות בין שני צבעים
 * @returns {number} יחס הניגודיות (1-21)
 */
function getContrastRatio(color1, color2) {
    const lum1 = getLuminance(color1);
    const lum2 = getLuminance(color2);
    const lighter = Math.max(lum1, lum2);
    const darker = Math.min(lum1, lum2);
    return (lighter + 0.05) / (darker + 0.05);
}

function getLuminance(hex) {
    const rgb = hexToRgb(hex);
    const [r, g, b] = rgb.map(c => {
        c = c / 255;
        return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/**
 * בודק האם הערכה עומדת בתקני WCAG
 */
function checkThemeAccessibility(variables) {
    const issues = [];
    
    // טקסט רגיל: יחס מינימלי 4.5:1
    const textRatio = getContrastRatio(
        variables['--text-primary'],
        variables['--bg-primary']
    );
    if (textRatio < 4.5) {
        issues.push({
            type: 'error',
            message: `יחס ניגודיות טקסט נמוך (${textRatio.toFixed(2)}:1). מומלץ לפחות 4.5:1`
        });
    }
    
    // כפתורים: יחס מינימלי 4.5:1 בין צבע הטקסט לרקע הכפתור
    const buttonRatio = getContrastRatio(
        variables['--btn-primary-color'],
        variables['--btn-primary-bg']
    );
    if (buttonRatio < 4.5) {
        issues.push({
            type: 'warning',
            message: `יחס ניגודיות כפתורים נמוך (${buttonRatio.toFixed(2)}:1). מומלץ לפחות 4.5:1`
        });
    }
    
    // Markdown Preview: יחס ניגודיות בין טקסט לרקע
    const mdRatio = getContrastRatio(
        variables['--md-text'],
        variables['--md-surface']
    );
    if (mdRatio < 4.5) {
        issues.push({
            type: 'error',
            message: `יחס ניגודיות ב-Markdown Preview נמוך (${mdRatio.toFixed(2)}:1). חובה לפחות 4.5:1`
        });
    }
    
    return issues;
}
```

### המלצות UX

1. **תצוגה מקדימה חיה** - כל שינוי מוחל מיד על אזור התצוגה המקדימה

2. **אזהרות ניגודיות** - הצגת אזהרה כשהניגודיות נמוכה מדי

3. **Undo/Redo** - אפשרות לבטל שינויים:
   ```javascript
   const history = [];
   let historyIndex = -1;
   
   function saveState() {
       history.splice(historyIndex + 1);
       history.push(getCurrentVariables());
       historyIndex = history.length - 1;
   }
   
   function undo() {
       if (historyIndex > 0) {
           historyIndex--;
           applyVariables(history[historyIndex]);
       }
   }
   ```

4. **שמירה אוטומטית** - שמירת טיוטה ב-localStorage למקרה של סגירת החלון

5. **קיצורי מקלדת**:
   - `Ctrl+S` - שמירה
   - `Ctrl+Z` - ביטול
   - `Ctrl+Shift+Z` - חזרה

---

---

## ⚠️ נקודות חשובות למימוש

### 0. סנכרון עם מסמך הארכיטקטורה

> ⚠️ **חשוב:** כל השמות והמיפויים במדריך זה מסונכרנים עם מסמך הארכיטקטורה הרשמי:
> `docs/webapp/theming_and_css.rst`

**טוקנים חובה לכל ערכה מותאמת אישית** (כפי שמוגדר במסמך הארכיטקטורה):
- `--primary`, `--secondary`
- `--bg-primary`, `--bg-secondary`
- `--text-primary`, `--text-secondary`
- `--btn-primary-bg`, `--btn-primary-color` (ולא `--primary` לכפתורים!)
- `--glass`
- `--md-surface`, `--md-text` (לתמיכה ב-Markdown Preview)

**מיפויים רבים-לאחד** - שים לב שמפתחות VS Code מסוימים ממלאים כמה טוקנים:
```python
# editor.background → גם --bg-primary וגם --md-surface
# editor.foreground → גם --text-primary וגם --md-text
# notificationsErrorIcon.foreground → גם --error וגם --danger-bg
```

### 1. Syntax Highlighting (tokenColors)

ערכות VS Code כוללות `tokenColors` שמגדיר צבעים לקוד. **חובה** לטפל בזה:

- מפה את ה-scopes ל-CodeMirror classes
- יצר CSS נפרד ושמור אותו בשדה `syntax_css` ב-MongoDB
- הזריק את ה-CSS בנפרד מה-UI variables

### 2. מניפולציית צבעים בטוחה

**אל תניח** שצבע מגיע בפורמט Hex מלא!

```python
# ❌ לא בטוח - יישבר על #fff או rgb(...)
result["--primary-light"] = primary + "26"

# ✅ בטוח - משתמש בהמרה
result["--primary-light"] = color_with_opacity(primary, 0.15)
```

### 3. Preview State Management

**חובה** לשמור מצב מקורי לפני preview:

```javascript
// שמירת מצב
saveOriginalPreviewState();

// החלת preview
applyPreviewVariables(newVars);

// כפתור revert
<button onclick="revertPreview()">בטל תצוגה מקדימה</button>
```

### 4. Security - CSS Sanitization

ה-Regex לצבעים **מכוון להיות מגביל**. אל תרחיב אותו!

```python
# ❌ מסוכן - לא להוסיף!
r'url\([^)]+\)'      # מאפשר מעקב/XSS
r'expression\(.*\)'  # JS injection
r'.*'                # הכל מותר

# ✅ בטוח - רק hex/rgb/rgba
VALID_COLOR_REGEX = re.compile(
    r'^#[0-9a-fA-F]{3,8}$|'
    r'^rgb\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\)$|'
    r'^rgba\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*[\d.]+\s*\)$'
)
```

---

## סיכום

### רשימת משימות למימוש

**שירותי Backend:**
- [ ] יצירת `services/theme_parser_service.py`
  - [ ] פונקציות המרת צבעים (`normalize_color_to_rgba`, `color_with_opacity`)
  - [ ] פרסור VS Code themes (`parse_vscode_theme`) **עם תמיכה במיפויים רבים-לאחד**
  - [ ] פרסור tokenColors ל-CodeMirror CSS (`generate_codemirror_css_from_tokens`)
  - [ ] Sanitization (`sanitize_css_value`, `validate_and_sanitize_theme_variables`)
- [ ] יצירת `services/theme_presets_service.py`
- [ ] יצירת `webapp/static/data/theme_presets.json` **עם כל הטוקנים הנדרשים**
- [ ] הרחבת `webapp/themes_api.py` עם endpoints חדשים

**Frontend:**
- [ ] עדכון `theme_builder.html` עם UI לייבוא ו-presets
- [ ] יצירת `webapp/static/js/theme-importer.js`
- [ ] מנגנון Preview/Revert לגלריית Presets
- [ ] CSS לכפתור Revert ואנימציות
- [ ] בדיקת ניגודיות עבור **`--btn-primary-bg`/`--btn-primary-color`** ו-**`--md-surface`/`--md-text`**

**בדיקות:**
- [ ] Unit tests לפונקציות צבע
- [ ] Unit tests לסניטיזציה (חשוב לאבטחה!)
- [ ] **Unit tests למיפויים רבים-לאחד** (editor.background → --bg-primary + --md-surface)
- [ ] Integration tests ל-API
- [ ] בדיקות ידניות עם ערכות VS Code אמיתיות

**תיעוד:**
- [ ] עדכון documentation
- [ ] הוספת דוגמאות לייבוא
- [ ] **סנכרון עם `docs/webapp/theming_and_css.rst` בכל שינוי**

### קבצים קיימים לעדכון

| קובץ | שינוי נדרש |
|------|------------|
| `webapp/templates/settings/theme_builder.html` | הוספת טאבים, גלריה, אזור העלאה |
| `webapp/themes_api.py` או קובץ API קיים | endpoints חדשים |
| `webapp/templates/base.html` | ללא שינוי (כבר תומך ב-custom themes) |

### תלויות חדשות

אין תלויות חיצוניות חדשות נדרשות - הכל מבוסס על Flask, MongoDB וJavaScript vanilla.

---

## קישורים שימושיים

- [VS Code Theme Color Reference](https://code.visualstudio.com/api/references/theme-color)
- [WCAG 2.1 Contrast Guidelines](https://www.w3.org/WAI/WCAG21/Understanding/contrast-minimum.html)
- [Dracula Theme](https://draculatheme.com/)
- [Nord Theme](https://www.nordtheme.com/)
- [Gruvbox](https://github.com/morhetz/gruvbox)
