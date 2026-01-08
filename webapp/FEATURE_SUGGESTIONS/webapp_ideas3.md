# 💡 WebApp Feature Suggestions (UI-First)
**תאריך:** ינואר 2026  
**מיקוד:** ויזואלי/מעוצב, דשבורדים ותצוגות מידע, כלים פרקטיים עם UI כיפי, RTL ועברית ברמה גבוהה.  

> הערה קטנה: כבר קיימים בפועל ב-WebApp פיצ׳רים כמו **Theme Builder + Gallery**, **Incident Replay**, **Jobs Monitor**, ו-**Query Profiler**. ההצעות כאן בנויות כדי *להעצים* אותם או להוסיף שכבות UI חדשות—בלי להיגרר ל-“backend heavy”.

---

### 🎨 RTL Typography Studio
**Visual Appeal:** ⭐⭐⭐⭐⭐  
**תיאור:** “מעבדה” לטיפוגרפיה בעברית: בחירת פונטים, line-height, letter-spacing, grid/baseline, עם תצוגה מקדימה חיה על כרטיסים, טבלאות וקוד.  
**למה מתאים:** RTL מושקע + UI ויזואלי + כיף לשחק ולראות תוצאות מיידיות.  
**Inspiration:** דומה ל-Tailwind Typography Playground / Figma type panel.  
**מורכבות:** בינונית  

---

### 🌈 Gradient + Mesh Background Builder
**Visual Appeal:** ⭐⭐⭐⭐⭐  
**תיאור:** כלי בתוך Theme Builder ליצירת gradients ו-“mesh” רקע (עם נקודות צבע) כולל “randomize”, שמירה כ-preset, ו-preview על דפים שונים.  
**למה מתאים:** ויזואלי חזק + Themes + Glassmorphism/gradients.  
**Inspiration:** דומה ל-Mesh Gradients generators + Webflow background controls.  
**מורכבות:** בינונית  

---

### 🧊 Glassmorphism Component Playground
**Visual Appeal:** ⭐⭐⭐⭐⭐  
**תיאור:** דף “קומפוננטים” שמציג cards, buttons, badges, tables, modals, toasts — עם sliders ל-glass opacity/blur והחלפת theme בזמן אמת.  
**למה מתאים:** UI components מגניבים + מיקרו-אינטראקציות + הכי כיף לבנות.  
**Inspiration:** דומה ל-Storybook, אבל קליל ובלי React.  
**מורכבות:** בינונית  

---

### 🧪 Theme Compare (Side-by-Side) + “Token Diff”
**Visual Appeal:** ⭐⭐⭐⭐  
**תיאור:** השוואה צד-לצד בין שתי ערכות: preview זהה בשתי עמודות + רשימת “מה השתנה” (CSS variables) עם הדגשה צבעונית.  
**למה מתאים:** ויזואליזציה פרקטית + Themes + כלי שימושי למעצבים/מפתחים.  
**Inspiration:** דומה ל-Git diff אבל לטוקנים של עיצוב.  
**מורכבות:** בינונית  

---

### 🧭 Motion Playground (Easing / Duration / Stagger)
**Visual Appeal:** ⭐⭐⭐⭐  
**תיאור:** פאנל שמאפשר לכוון easing/duration/stagger ולהדגים אותם על רשימות/כרטיסים/מודאלים (כולל prefers-reduced-motion).  
**למה מתאים:** אנימציות + מיקרו-אינטראקציות + בנייה מהנה.  
**Inspiration:** דומה ל-easings.net + Framer motion playground.  
**מורכבות:** קלה  

---

### ⏱️ Incident Replay: Zoom + Scrubber + Mini-Map
**Visual Appeal:** ⭐⭐⭐⭐⭐  
**תיאור:** שדרוג ל-Incident Replay עם zoom/pan בציר הזמן, scrubber שמריץ “סרט” של אירועים, ו-mini-map צפוף/דליל לאורך הטווח.  
**למה מתאים:** timeline אינטראקטיבי + דשבורד + פיצ׳ר ויזואלי “וואו”.  
**Inspiration:** דומה ל-Sentry issue replay / Grafana explore timeline.  
**מורכבות:** מורכב  

---

### 🔥 Incident Replay: Event Density Heat Strip
**Visual Appeal:** ⭐⭐⭐⭐  
**תיאור:** פס חום/צבע דק מעל הרשימה שמראה צפיפות אירועים לאורך הזמן (קליק על אזור קופץ אליו).  
**למה מתאים:** ויזואליזציה קצרה ומגניבה + שימושי לניווט מהיר.  
**Inspiration:** דומה ל-minimap של diff / heat-strip ב-IDE.  
**מורכבות:** בינונית  

---

### 📋 Runbook Builder Lite (UI-First)
**Visual Appeal:** ⭐⭐⭐⭐  
**תיאור:** עורך ויזואלי לצעדי Runbook: drag & drop סדר צעדים, תבניות כרטיסים, ו-preview איך זה נראה בתוך Incident Replay.  
**למה מתאים:** כלי שימושי עם UI יפה + תצוגת מידע + פחות “מערכת כבדה” ויותר חוויית בנייה.  
**Inspiration:** דומה ל-Notion checklist builder / Linear templates.  
**מורכבות:** מורכב  

---

### 📊 Jobs Monitor: Gantt Timeline View
**Visual Appeal:** ⭐⭐⭐⭐  
**תיאור:** תצוגת “גאנט” להרצות Jobs לפי זמן (רצים/הסתיימו/נכשלו) עם zoom ו-tooltip לפרטים.  
**למה מתאים:** דשבורד/גרף + real-time feel + כיף לראות תנועה.  
**Inspiration:** דומה ל-CI timeline ב-GitHub Actions.  
**מורכבות:** בינונית  

---

### 🧵 Jobs Logs Highlighter (Client-Side)
**Visual Appeal:** ⭐⭐⭐  
**תיאור:** בתוך מודאל הלוגים: פילטרים צבעוניים לפי keyword (error/warn/timeout), קפיצה בין “אירועים חשובים”, ו-copy “קטע לוג” מעוצב.  
**למה מתאים:** שימושי ביום-יום + UI קטן ומדויק.  
**Inspiration:** דומה ל-Kibana log highlights / VS Code search decorations.  
**מורכבות:** קלה  

---

### 🧩 CSS Token Inspector Overlay
**Visual Appeal:** ⭐⭐⭐⭐  
**תיאור:** מצב “Inspect” שמראה על hover איזה component-token/CSS-variable משפיע על האלמנט (עם bubble קטן והעתקה).  
**למה מתאים:** כלי פרקטי עם UI מגניב + Themes + חוסך זמן.  
**Inspiration:** דומה ל-Chrome DevTools, אבל ממוקד בטוקנים.  
**מורכבות:** בינונית  

---

### 📏 RTL Layout Debug Grid (Toggle)
**Visual Appeal:** ⭐⭐⭐  
**תיאור:** שכבת grid/baseline שניתנת להדלקה/כיבוי כדי ליישר spacing בעברית (padding/margins), כולל safe-area במובייל.  
**למה מתאים:** RTL מושקע + שימושי לפיתוח UI נקי.  
**Inspiration:** דומה ל-layout grids ב-Figma.  
**מורכבות:** קלה  

---

### 📦 static_build Bundle Size Dashboard
**Visual Appeal:** ⭐⭐⭐⭐  
**תיאור:** דשבורד ויזואלי שמציג את גודל הבאנדלים (treemap + trend קטן לאורך זמן) כדי להבין “מה שוקל”.  
**למה מתאים:** ויזואליזציה + כלי פרקטי + לא דורש אינטגרציות מסובכות.  
**Inspiration:** דומה ל-webpack bundle analyzer / Vite visualizer.  
**מורכבות:** בינונית  

---

### 🧷 Sticky Notes: Canvas / Board Mode
**Visual Appeal:** ⭐⭐⭐⭐  
**תיאור:** מצב לוח לפתקיות (גרירה חופשית/סידור אוטומטי/קיבוץ לפי צבע), עם אנימציות עדינות ושמירה אוטומטית.  
**למה מתאים:** UI כיפי + מיקרו-אינטראקציות + “משהו שמשתמשים בו באמת”.  
**Inspiration:** דומה ל-Miro sticky notes / macOS Stickies.  
**מורכבות:** בינונית  

---

### 🖼️ “Theme Showcase” – Gallery במבנה Masonry
**Visual Appeal:** ⭐⭐⭐⭐  
**תיאור:** שדרוג גלריית ערכות: masonry cards עם preview אמיתי (לא רק נקודות צבע), תגיות (dark/light/contrast), וסינון מהיר.  
**למה מתאים:** ויזואלי + Themes + חוויית שימוש יותר “וואו”.  
**Inspiration:** דומה ל-theme galleries של VS Code / Dribbble boards.  
**מורכבות:** בינונית  

---

### 🧠 Activity Timeline: “Story Cards”
**Visual Appeal:** ⭐⭐⭐⭐  
**תיאור:** בדשבורד: מעבר מ-feed טקסטואלי ל-“story cards” צבעוניים עם קיבוץ חכם (שמירה/פוש/תזכורות) ומעבר עם swipe במובייל.  
**למה מתאים:** ויזואלי + מידע שימושי + מתאים לעברית/RTL.  
**Inspiration:** דומה ל-Instagram stories UI (בלי סושיאל), רק למידע מערכת.  
**מורכבות:** בינונית  

---

### 🎛️ Quick Theme Switcher (Preview-Only)
**Visual Appeal:** ⭐⭐⭐  
**תיאור:** מתג קטן שמאפשר “לצפות” בערכה זמנית (preview-only) בלי לשמור—מעולה כשמסתכלים על דף ומנסים 4-5 themes במהירות.  
**למה מתאים:** Themes + micro-interaction שימושית מאוד + בנייה מהירה.  
**Inspiration:** דומה ל-theme switchers של docs מודרניים (Docusaurus/Nextra).  
**מורכבות:** קלה  

---

> נוצר אחרי סריקה של `webapp/` (templates/static/static_build) והצלבה מול מסמכי `webapp/FEATURE_SUGGESTIONS/` כדי להימנע מכפילויות.
