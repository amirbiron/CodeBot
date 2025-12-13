# 💡 Feature Suggestions ל־WebApp (ממוקד Focus Areas)

מסמך זה מציע רעיונות *חדשים בלבד* עבור `webapp/` (Observability / Dev Tools / Visualization / Admin / UI), תוך הימנעות מכפילויות מול המסמכים הקיימים בתיקייה (למשל: חיפוש גלובלי, כלי השוואה, מצבי תצוגה, תפריט קיצורים, ניטור זמינות).

---

## Observability

### 🔥 SLO Burn-Rate Panel
**תיאור:** תצוגה קצרה וברורה של SLO/SLI לכל משפחת Endpoints (latency / error-rate), כולל Burn‑Rate ומד “כמה זמן עד שנשרוף את התקציב”.
**קטגוריה:** Observability
**מורכבות:** מורכבת

### 📍 Deploy Markers Overlay
**תיאור:** שכבת “סימוני דיפלוימנט” על גרפים קיימים (alerts/latency) עם hover לפרטי גרסה, ויכולת לסנן “לפני/אחרי דיפלוימנט”.
**קטגוריה:** Observability
**מורכבות:** בינונית

### 🧩 Alert-to-Endpoint Drilldown
**תיאור:** קליק על התראה פותח פאנל צד שמרכז: endpoints שנפגעו, rate/latency טרנד בחלון סביב ההתראה, והקישורים הרלוונטיים (replay/runbook).
**קטגוריה:** Observability
**מורכבות:** בינונית

### 🌡️ Endpoint Latency Heatmap
**תיאור:** Heatmap אינטראקטיבי שמראה “איפה כואב” לפי שעה×endpoint (או minute buckets) עם צבע לפי p95/p99.
**קטגוריה:** Observability
**מורכבות:** בינונית

### 🧯 Error Budget “What-If” Simulator
**תיאור:** סימולטור קטן שמאפשר להזין יעד SLO ולקבל “אם נמשיך בקצב הזה” מה הצפי לשבירה, כולל תרחישים (פי 2 שגיאות, פי 1.5 latency).
**קטגוריה:** Observability
**מורכבות:** מורכבת

---

## Visualization

### 🛣️ Incident Swimlane Timeline
**תיאור:** תצוגה אחת של “מסלולים” (swimlanes) שמחברת התראות, deployments, פעולות ChatOps, וסיפורי אירוע על ציר זמן משותף, עם zoom/brush.
**קטגוריה:** Visualization
**מורכבות:** מורכבת

### 📈 Before/After Range Diff
**תיאור:** בחירת שני טווחי זמן והשוואה ויזואלית של דלתא במדדים מרכזיים (alerts, avg/p95 latency, error rate) עם “מה השתנה הכי הרבה”.
**קטגוריה:** Visualization
**מורכבות:** בינונית

### 🧭 Alert Cluster Map
**תיאור:** Bubble chart/treemap שמקבץ התראות לפי קטגוריה/חתימה/endpoint ומדגיש hotspots לפי נפח/חומרה.
**קטגוריה:** Visualization
**מורכבות:** בינונית

### 🧷 Runbook Progress Timeline
**תיאור:** לכל אירוע/Runbook: ציר זמן של השלבים שסומנו כבוצעו, זמן בין צעדים, ותצוגת “היכן נתקענו” (bottleneck).
**קטגוריה:** Visualization
**מורכבות:** בינונית

### 🧨 Blast-Radius Graph
**תיאור:** גרף קשרים קטן שמראה “מה מושפע ממה” (endpoint → קטגוריית שגיאה → פיקס מהיר/Runbook) כדי להבין השפעה והקשרים בזמן תחקור.
**קטגוריה:** Visualization
**מורכבות:** מורכבת

---

## Dev Tool

### 🪲 In‑App Fetch Inspector
**תיאור:** שכבת דיבוג (מופעלת רק למנהלים/מצב dev) שמציגה את 20 הקריאות האחרונות ל־API: סטטוס, משך, גודל, payload קצר, וכפתור “העתק כ‑cURL”.
**קטגוריה:** Dev Tool
**מורכבות:** בינונית

### 🧾 UI State Snapshot (Export/Import)
**תיאור:** כפתור שמייצא את מצב ה־UI הנוכחי (theme, פילטרים, טווחי זמן, עמוד פעיל) ל־JSON, וכפתור Import לשחזור מצב לצורך דיבוג ושחזור בעיות.
**קטגוריה:** Dev Tool
**מורכבות:** קל

### 🧪 Mock Data Mode
**תיאור:** מתג שמאפשר להזין fixtures מקומיים (JSON) לדפי Observability כדי לפתח/לדבג UI בלי תלות בנתונים אמיתיים.
**קטגוריה:** Dev Tool
**מורכבות:** בינונית

### 🧰 “Copy Diagnostics” Button
**תיאור:** כפתור אחד שמעתיק ללוח “חבילת דיאגנוסטיקה” (UA, theme, timezone, last errors, request ids אם יש) לשיתוף מהיר בבאגים.
**קטגוריה:** Dev Tool
**מורכבות:** קל

### 🧱 Frontend Performance HUD
**תיאור:** רכיב קטן שמציג מדדי UX בסיסיים (LCP/CLS/INP) בזמן אמת בתוך האפליקציה, עם “שמור snapshot” להשוואה אחרי שינוי UI.
**קטגוריה:** Dev Tool
**מורכבות:** בינונית

---

## Admin

### 📡 Config Radar Dashboard
**תיאור:** דף אדמין שמציג snapshot של קבצי config קריטיים (alerts/signatures/runbooks/quick-fixes), כולל validation issues, מידע git, ויכולת “השווה לגרסה קודמת”.
**קטגוריה:** Admin
**מורכבות:** בינונית

### 🧯 Quick‑Fix Safety Console
**תיאור:** ניהול מרוכז של פעולות Quick Fix: סטטיסטיקת שימוש, דירוג “סיכון”, אפשרות להשבית פעולה מסוכנת, והצגת “מי הריץ ומתי”.
**קטגוריה:** Admin
**מורכבות:** מורכבת

### 🧾 Incident Postmortem Builder
**תיאור:** בונה postmortem אינטראקטיבי שמושך נתונים מה־Incident Story/Replay ומרכיב Markdown מסודר (מה קרה/ציר זמן/מה עשינו/Follow‑ups) בלי AI.
**קטגוריה:** Admin
**מורכבות:** בינונית

### 🧹 Admin “Data Hygiene” Dashboard
**תיאור:** דשבורד שמדגיש נתונים בעייתיים (קבצים גדולים חריגים, tags לא תקינים, שיתופים ישנים), עם פעולות “ניקוי בטוח” שמבוססות allowlist.
**קטגוריה:** Admin
**מורכבות:** בינונית

### 🧷 Feature Flags Panel (UI‑Only)
**תיאור:** מסך אדמין קטן להפעלה/כיבוי של פיצ’רים בצד לקוח (למשל: פאנל דיבוג, רכיבי גרפים חדשים), כדי לבדוק דברים בלי דיפלוי.
**קטגוריה:** Admin
**מורכבות:** קל

---

## UI

### 🧲 Dockable Side Panel (Reusable)
**תיאור:** פאנל צד “עגינה” שניתן לפתוח/לסגור ולהשתמש בו בכל דף (פרטי קובץ, פרטי התראה, פרטי runbook) בלי להחליף מסך.
**קטגוריה:** UI
**מורכבות:** בינונית

### 🧭 Mini‑Map Navigation for Long Pages
**תיאור:** “מיני‑מפה” קטנה בצד שמציגה מקטעים בדף (כמו admin observability), עם קפיצה מהירה ו-highlight של החלק הנוכחי.
**קטגוריה:** UI
**מורכבות:** בינונית

### 🧷 Persistent Layout Presets
**תיאור:** פריסטים לשמירת Layout (רוחבי עמודות, מצב גרפים, טווח ברירת מחדל) לכל דף מרכזי, עם “שחזר לברירת מחדל”.
**קטגוריה:** UI
**מורכבות:** בינונית

### 🧾 Smart “Copy Everywhere” Components
**תיאור:** קומפוננטה אחידה להעתקה (עם tooltip/feedback) לכל מקום שיש טקסט טכני: endpoint, query params, ids, פקודות runbook.
**קטגוריה:** UI
**מורכבות:** קל

### 🧯 Sticky “Context Bar”
**תיאור:** בר קטן שנדבק למעלה ומציג את ההקשר הנוכחי (טווח זמן, פילטר חומרה, endpoint נבחר), עם כפתור “נקה פילטרים” אחד.
**קטגוריה:** UI
**מורכבות:** קל
