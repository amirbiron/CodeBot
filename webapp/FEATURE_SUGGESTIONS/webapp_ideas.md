# 🌟 רעיונות ממוקדי משתמש ל‑WebApp (דצמבר 2025)

תאריך: 29/11/2025  
מטרה: להציע פיצ'רים יעילים שמוסיפים ערך למשתמשי ה‑WebApp בלי לחזור על רעיונות שכבר מרוכזים ב‑`FEATURE_SUGGESTIONS`. לא כללתי שיתופי קהילה או "סוכן AI".

## כיסוי הסריקה
- `webapp/app.py` – לרבות מנגנון `static_version`, מדדי ביצועים ו־Flask routes.
- `webapp/sticky_notes_api.py` + `webapp/static/js/sticky-notes.js` – לוגיקה ליצירה/סנכרון פתקים ותזכורות.
- קבצי JS מרכזיים: `static/js/editor-manager.js`, `bookmarks.js`, `multi-select.js`, `bulk-actions.js`, `global_search.js`, `dark-mode.js`.
- `webapp/static_build/` (סקריפטי esbuild), `webapp/static/sw.js`, `manifest.json`, וכל תיקיית `static/`.
- `webapp/templates/` (במיוחד `base.html`, `files.html`, `dashboard.html`, `md_preview.html`), כדי להבין אילוצי UI קיימים.
- `config/alerts.yml`, `config/error_signatures.yml` והגדרות נוספות שה-WebApp כבר מכיר.
- כל קבצי `webapp/FEATURE_SUGGESTIONS` כדי לוודא שההצעות חדשות.

## תוכן העניינים
1. [Sticky Notes Mission Control](#1-sticky-notes-mission-control)
2. [Session Rescue לעורך הקבצים](#2-session-rescue-לעורך-הקבצים)
3. [Bulk Action Recipes & Queue](#3-bulk-action-recipes--queue)
4. [Markdown Focus Queue & Heading Trails](#4-markdown-focus-queue--heading-trails)
5. [Offline Pin Sets + Delta Sync](#5-offline-pin-sets--delta-sync)
6. [Config Radar בתוך הדשבורד](#6-config-radar-בתוך-הדשבורד)
7. [Keyboard Palette + Modal Framework](#7-keyboard-palette--modal-framework)

---

### 1. Sticky Notes Mission Control
**למה עכשיו:** ממשק הפתקים פועל רק בתוך קובץ יחיד, עם מטמון מקומי פר־קובץ ואין נקודת מבט שמשלבת תזכורות, סטטוס וטיפול מרוכז.

```101:114:webapp/static/js/sticky-notes.js
class StickyNotesManager {
  constructor(fileId){
    this.fileId = fileId;
    this.notes = new Map();
    this._saveDebounced = debounce(this._performSaveBatch.bind(this), AUTO_SAVE_DEBOUNCE_MS);
    this._pending = new Map();
    this._inFlight = new Map();
    this._autoFlushTimer = null;
    this._autoFlushBusy = false;
    this._lineIndex = new Map(); // lineNumber -> pageY
    this._cacheKey = `sticky-notes:${String(fileId)}`;
    this._renderedFromCache = false;
    this._pendingSeq = new Map(); // noteId -> monotonic version of pending edits
    this._init();
  }
```

**מה מציעים:**  
- לוח `/notes/board` עם טבלת פתקים, פילטר לפי קובץ/עוגן/סטטוס תזכורת, quick actions (סימון "טופל", דחיית תזכורות, מחיקה מרוכזת).  
- גרף קטן (mini heatmap) שמראה באילו קבצים מרוכזים רוב הפתקים.  
- תצוגת "מסך תזכורות" שמחברת בין sticky notes לבין התראות הדפדפן שכבר מופעלות.

**כיווני מימוש:**  
- הרחבת `sticky_notes_api.py` עם endpoint מצטבר (`/api/sticky-notes/all`) שעושה reuse לאינדקסים שכבר מוקמים (`user_id + file_id`).  
- תבנית חדשה תחת `templates/sticky_notes_board.html` שממחזרת את ה־components הקיימים (צבעים, פקד עיגון) ומחברת ל־`sticky-notes.js` במוד של read-only + bulk.  
- מדדי observability קיימים (`emit_event`) יכולים להזין counters ללוח.

**השפעה צפויה:** פחות ניהול ידני של פתקים ישנים, קל יותר לסגור חובות כתיבה ולנהל תזכורות פתוחות.

---

### 2. Session Rescue לעורך הקבצים
**למה עכשיו:** `EditorManager` מתעד רק את סוג העורך המועדף, אך לא משחזר טיוטות, לשוניות או מצב הקוד אחרי רענון.

```48:75:webapp/static/js/editor-manager.js
 loadPreference() {
   try {
     const saved = localStorage.getItem('preferredEditor');
     if (saved === 'codemirror' || saved === 'simple') return saved;
     const serverPref = (window.__serverPreferredEditor || '').toLowerCase();
     if (serverPref === 'codemirror' || serverPref === 'simple') return serverPref;
   } catch(_) {}
   return 'codemirror';
 }

 savePreference(editorType) {
   try { localStorage.setItem('preferredEditor', editorType); } catch(_) {}
   fetch('/api/ui_prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ editor: editorType }) }).catch(()=>{});
   fetch('/api/user/preferences', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ editor_type: editorType }) }).catch(()=>{});
 }
```

**מה מציעים:**  
- Snapshot מקומי אוטומטי לכל טיוטה (Crypt hash by file_id + timestamp) עם diff viewer קטן לפני שחזור.  
- "Session timeline" שמופיע בצד ימין ומאפשר לחזור לאחת משלוש הטיוטות האחרונות בכל קובץ.  
- אינדיקציית autosave + אפשרות ידנית "שמור כטיוטה" שמאחסנת ב־Mongo באותו אוסף שבו נשמרים `ui_prefs`.

**כיווני מימוש:**  
- reuse ל־`cmInstance.updateListener` כדי לירות אירוע throttled ל־IndexedDB.  
- API זעיר ב־`bookmarks_manager.py` או מודול ייעודי שיכתוב טיוטות (`drafts` collection).  
- UI: badge על כפתור השמירה + modal שמציג את ה־timeline.

**השפעה צפויה:** פחות אובדן עבודה, מאפשר לעבור בין מכשירים בלי חשש.

---

### 3. Bulk Action Recipes & Queue
**למה עכשיו:** פעולות מרובות קיימות אבל הן סדרת קריאות fetch אחת אחת, ללא pipeline, ללא רקורדינג ולא ניתן להגדיר "מתכון" שחוזר על עצמו.

```71:123:webapp/static/js/bulk-actions.js
async addToFavorites() {
    const fileIds = window.multiSelect.getSelectedFiles().map(f => f.id);
    if (fileIds.length === 0) {
        this.showNotification('לא נבחרו קבצים', 'warning');
        return;
    }
    this.showProcessing(`מוסיף ${fileIds.length} קבצים למועדפים...`);
    try {
        const response = await fetch('/api/files/bulk-favorite', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ file_ids: fileIds })
        });
        const result = await response.json();
        if (result.success) {
            this.showNotification(`${result.updated} קבצים נוספו למועדפים`, 'success', { icon: 'star' });
            // ...
            window.multiSelect.clearSelection();
        }
    } finally {
        this.hideProcessing();
    }
}
```

**מה מציעים:**  
- "Recipes" שמגדירים סדרת צעדים (לדוגמה: הוסף תג "Share", גרוס ZIP, שלח לשיתוף) ושומרים אותם למשתמש.  
- 큐 ברקע שמדווח התקדמות פר־קובץ (progress bar שכבר קיים ב־overlay).  
- מנגנון retry אוטומטי לפריטים שנכשלו, עם export של דו"ח JSON.

**כיווני מימוש:**  
- Endpoint חדש `/api/files/bulk-run` שמקבל JSON recipe ומייצר job (אפשר להשתמש ב־Mongo או Redis אם יוחזר).  
- הרחבת `multi-select.js` לשמור בחירה אחרי רענון כדי להריץ מתכון מאוחר יותר.  
- UI: modal builder (נראה ברעיון 7) שבו בוחרים צעדים מתוך allowlist.

**השפעה צפויה:** חיסכון בזמן בביצוע פעולות חוזרות, בסיס אוטומציה פנימי בלי לסבך משתמשי קצה.

---

### 4. Markdown Focus Queue & Heading Trails
**למה עכשיו:** עמוד `md_preview.html` כבר הוסיף חיפוש, צבעי רקע ו‑copy, אך אין "מצב קריאה" שמנהל תור כותרות, track progress או מסנכרן בין sticky notes לבין תוכן.

```139:205:webapp/templates/md_preview.html
#md-search {
  position: relative;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
  padding: 0.25rem 0;
  /* ... */
}
#md-search input {
  flex: 1 1 220px;
  border-radius: 8px;
  background: var(--md-search-input-bg, var(--bg-terטיary, rgba(255, 255, 255, 0.85)));
  border: 1px solid var(--md-search-input-border, var(--glass-border, rgba(0, 0, 0, 0.1)));
  /* ... */
}
```

**מה מציעים:**  
- "Focus Queue" – בחירה של כותרות H2/H3 להפוך ל"תור קריאה" עם progress (checkbox + keyboard nav).  
- תצוגת mini-map צפה (בדומה ל־floating TOC) שמראה גם איפה מוצבים sticky notes.  
- מצב "Guided Review": הפעלת פילטר שמציג רק כותרות עם notes/bookmarks פתוחים.

**כיווני מימוש:**  
- לנצל את ה־heading metadata שכבר נבנית ב־`markdown-it-anchor` (bundle קיים ב־`static_build/md-preview-entry.js`).  
- layer JS קל מעל `#md-search` שמייצר רשימת anchors + שימוש ב־IntersectionObserver לסימון אלו שנקראו.  
- שיתוף מידע עם `sticky-notes.js` באמצעות `window.dispatchEvent(new CustomEvent('md-heading-focus', {detail}))`.

**השפעה צפויה:** קריאה מסודרת למסמכי מדיניות ארוכים, הקטנת "פספוס" של סעיפים עם הערות.

---

### 5. Offline Pin Sets + Delta Sync
**למה עכשיו:** Service Worker מטפל רק ב‑push לתזכורות, למרות שיש כבר מנגנון cache-busting ב־`app.py` וחבילות esbuild. אין אפשרות "לנעוץ" קבצים לצפייה אופליין.

```1:44:webapp/static/sw.js
self.addEventListener('install', (event) => {
  try { self.skipWaiting(); } catch (_) {}
});
self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    try { await self.clients.claim(); } catch (_) {}
  })());
});
self.addEventListener('push', (event) => {
  const json = event.data ? (() => { try { return event.data.json(); } catch(_) { return {}; } })() : {};
  const title = json.title || (json.notification && json.notification.title) || (json.data && json.data.title) || '🔔 יש פתק ממתין';
  /* ... */
});
```

```232:256:webapp/app.py
def _compute_static_version() -> str:
    """Return a short version string to bust caches for static assets."""
    v = os.getenv("ASSET_VERSION") or os.getenv("APP_VERSION")
    if v:
        return str(v)
    try:
        p = _MANIFEST_PATH
        if p.is_file():
            h = hashlib.sha1(p.read_bytes()).hexdigest()
            return h[:8]
    except Exception:
        pass
    return str(int(_time.time() // 3600))
```

```1:31:webapp/static_build/build-cm.mjs
import { build } from 'esbuild';
const entry = resolve(__dirname, 'codemirror.bundle.entry.mjs');
const outfile = resolve(__dirname, '../static/js/codemirror.local.js');
await build({ entryPoints: [entry], bundle: true, format: 'iife', target: ['es2018'], outfile, /* ... */ });
```

**מה מציעים:**  
- UI (כפתור "נעץ אופליין") בכל כרטיס קובץ/Markdown שמוסיף את ה־fileId לרשימת Pin ב־IndexedDB.  
- Service Worker מורחב עם Cache Storage נפרד (חבילות Markdown, assets חיוניים ונתונים מ־`/api/files/<id>`).  
- Delta sync: בזמן שהאפליקציה אונליין, השוואה ל־ETag/Last-Modified (כבר קיימים ב־`app.py`) כדי לעדכן את הקבצים המנוצבים.

**כיווני מימוש:**  
- להרחיב את סקריפטי esbuild כך שייצרו bundle קטן ל‑offline viewer (למשל `offline-reader.bundle.js`).  
- Service worker: נתיב `pin-assets` שמגיב ל־`postMessage` ומעדכן caches.  
- מסך הגדרות: טבלה של קבצים נעוצים + נפח שתופסים.

**השפעה צפויה:** חוויית קריאה ללא תלות ברשת (בעיקר לטלגרם Mini App), מוכנות טובה יותר להפסקות חיבור.

---

### 6. Config Radar בתוך הדשבורד
**למה עכשיו:** יש קבצי קונפיגורציה מפורטים (`config/alerts.yml`, `config/error_signatures.yml`) אך המשתמשים לא רואים בזמן אמת אילו התרעות/דפוסי שגיאה פעילים.

```1:7:config/alerts.yml
window_minutes: 5
min_count_default: 3
cooldown_minutes: 20
immediate_categories:
  - config
  - critical
```

```4:18:config/error_signatures.yml
categories:
  config:
    description: תקלות קונפיגורציה/תשתית שיש לתקן מיד
    default_severity: critical
    default_policy: escalate
    signatures:
      - id: oom_killed
        summary: תהליך סיים בזיכרון נגמר
        pattern: 'Out of memory|OOMKilled|memory limit exceeded'
```

**מה מציעים:**  
- Widget חדש בדשבורד שמציג "Config Radar": התרעות חמות, חתימות שגיאה שחזרו באותו חלון, וכמה זמן נשאר ב־cooldown.  
- Drill-down לכרטיס פר אירוע (קישור ל־docs או לפיצ'רים הבאים).  
- אפשרות "סטטוס חי" שמופיע גם ב־`base.html` כ־badge קטן אם יש קטגוריה immediate.

**כיווני מימוש:**  
- קריאת הקבצים קיימת כבר בצד השרת; אפשר להמיר אותם ל־JSON חשוף ב־`/api/config/alerts`.  
- דשבורד: reuse של cards קיימים כדי להציג severity + CTA "פתח בוט" (מאותת להפעיל ChatOps).  
- hooks ל־observability events (כבר בשימוש ב־sticky notes) כדי להזין נתונים מה־worker.

**השפעה צפויה:** שקיפות תפעולית גם למשתמשים טכניים, גילוי מהיר של תקלות קונפיגורציה.

---

### 7. Keyboard Palette + Modal Framework
**למה עכשיו:** קיצורי המקלדת מפוזרים בכל קובץ JS, אין שכבת ניהול אחת, ואין `modals.js` או `shortcuts.js` אחיד – בדיוק השמות שהמשתמש ביקש לסרוק. הפונקציונליות קיימת למשל במערכת הסימניות:

```120:141:webapp/static/js/bookmarks.js
setupKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'b') {
            e.preventDefault();
            const currentLine = this.getCurrentLine FromSelection();
            if (currentLine) {
                this.toggleBookmark(currentLine);
            }
        }
        if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'B') {
            e.preventDefault();
            this.ui.togglePanel();
        }
        if (e.key === 'Escape' && this.ui.isPanelOpen()) {
            this.ui.closePanel();
        }
    });
}
```

**מה מציעים:**  
- יצירת `static/js/shortcuts.js` שמנהל רישום גלובלי של כל הקיצורים, מציג palette (בדומה ל־Cmd+K) ומזהיר על התנגשויות.  
- יצירת `static/js/modals.js` שמנהל stacking, focus trap, והחיים של modalים (Sticky reminders, bulk dialogs, וכו').  
- הצגת overlay קומפקטי (כמו Command Palette) שמאפשר לחפש פעולה לפי שם ולראות את הקיצור שלה.

**כיווני מימוש:**  
- refactor: להחליף קריאות `document.addEventListener('keydown'...)` בשכבה חדשה שמקבלת `registerShortcut({combo, scope, handler})`.  
- מודלים: שילוב של MutationObserver כדי לסגור מודלים כשהנתיב מתחלף, טיפול ב־ARIA.  
- שיתוף פעולה עם רעיון 3 (מתכוני bulk) ורעיון 1 (Mission Control) – כולם ירוויחו ממסגרת מודלים אחידה.

**השפעה צפויה:** UX אחיד ונקי, פחות התנגשויות בקיצורי הדרך, בסיס נוח להוספת פעולות מתקדמות.

---

## טבלת מאמץ / השפעה משוערת
| # | רעיון | מאמץ (מו"פ) | השפעה על המשתמש |
|---|-------|-------------|------------------|
| 1 | Sticky Notes Mission Control | בינוני | גבוה – שליטה בתזכורות ובפתקים |
| 2 | Session Rescue לעורך | בינוני | גבוה – אין אובדן טיוטות |
| 3 | Bulk Action Recipes | בינוני‑גבוה | בינוני‑גבוה – אוטומציה של זרימות קבועות |
| 4 | Markdown Focus Queue | בינוני | בינוני – קריאה מודרכת למסמכים ארוכים |
| 5 | Offline Pin Sets | גבוה | גבוה – עבודה חלקה בלי רשת |
| 6 | Config Radar | נמוך‑בינוני | בינוני – שקיפות תפעולית בזמן אמת |
| 7 | Keyboard Palette + Modal Framework | בינוני | בינוני – UX אחיד ותחזוקה קלה |

---

### צעדי המשך מוצעים
1. לבחור 1‑2 רעיונות "מהירים" (למשל Config Radar + Keyboard Palette) כדי לבנות מומנטום.  
2. לקבוע POC ל־Mission Control ולבדוק האם צריך אופטימיזציות ב־Mongo לפני שחזור פתקים גלובלי.  
3. לעדכן את CodeBot Docs עם ההחלטות ברגע שמתחילים ליישם, בהתאם למדיניות התיעוד.

אני זמין לכל העמקה או פירוט נוסף.
