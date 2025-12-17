# 🧭 WebApp Onboarding – Welcome Modal, Interactive Tour & Theme Wizard

תהליך ה-Onboarding של ה-WebApp מורכב משלושה רכיבים תלויים שמופעלים עבור משתמשים חדשים בלבד: Welcome Modal, סיור אינטראקטיבי מבוסס Driver.js וה-Theme Picker Wizard שמסיים את החוויה עם התאמה אישית. העמוד מרכז את ההסברים התפעוליים, מנגנוני האיפוס והנקודות החשובות למפתחים.

---

## רכיבים ומה הם עושים

| רכיב | מתי מופיע | דגל/מפתח | קבצי מקור |
| --- | --- | --- | --- |
| Welcome Modal | כניסה ראשונה אחרי התחברות | `has_seen_welcome_modal` (DB + sessionStorage) | `webapp/templates/base.html`, הקובץ `webapp/USER_GUIDE.md` |
| Interactive Tour (Driver.js) | אחרי שה-Welcome Modal נסגר ובנתיב `/files` | `localStorage["codekeeper_walkthrough_v1"]` | `initInteractiveWalkthrough()` בתוך `webapp/templates/base.html` |
| Theme Picker Wizard | בסיום הסיור או אחרי fallback של 9 שניות | `theme_wizard_seen`, `user_theme`, `dark_mode_preference` | רכיב `#themeWizard` + `initThemeWizard()` ב-`webapp/templates/base.html` |

---

## תרשים אינטראקציה

![תרשים זרימה – Onboarding](../images/onboarding-flow.svg)

**סדר טעינה:**
- Welcome Modal חייב להסיר את עצמו מה-DOM (MutationObserver) לפני שכל רכיב אחר מתחיל.
- Driver.js ממתין לנתיב `/files` ולסיום ה-Welcome Modal (`waitForWelcomeModal()`), ואז מפעיל את הסיור וכותב את הדגל `codekeeper_walkthrough_v1`.
- Theme Wizard מאזין ל-Driver באמצעות `ThemeWizard.watchDriver()` וכך נפתח מיד כשהסיור מסתיים. אם הסיור לא רץ, `scheduleFallback()` יפתח אותו לאחר ~9 שניות.

התלות הזו מונעת התנגשויות: Welcome Modal → Interactive Tour → Theme Wizard.

---

## Welcome Modal – רענון קצר

מודאל **Welcome** מוצג למשתמשים שמתחברים ל-WebApp בפעם הראשונה ומספק קישורים ישירים למדריכים המרכזיים מתוך `webapp/USER_GUIDE.md`. אחרי כל פעולה (Primary/Secondary/דלג) נשלחת בקשה ל-`POST /api/welcome/ack` והדגל `has_seen_welcome_modal` מסומן ב-DB וגם ב-session.

### מטרות
- להדריך משתמשים חדשים לשני מדריכים מרכזיים מהר ככל האפשר.
- למנוע חיכוך בכניסה הראשונה – מופיע פעם אחת בלבד.

### זרימת משתמש
1. `show_welcome_modal` בצד השרת מחזיר true → ה-template מייצר את ה-modal.
2. `welcomeModalInit()` מצמיד האזנות לכפתורים ולרקע.
3. הקשה על כל כפתור קוראת ל-`/api/welcome/ack` ומסירה את המודאל.
4. המסך פנוי להמשך – MutationObserver מסמן ליתר הרכיבים שאפשר להתחיל.

> לצורכי QA ניתן למחוק את הדגל ישירות ב-DB או לנקות `sessionStorage.has_seen_welcome_modal`.

### סנכרון למדריך העדכני
- `USER_GUIDE.md` הוא מקור האמת – אין שכפול ב-DB.
- `get_internal_share()` מחפש את המזהים `welcome` / `welcome-quickstart` (כולל המזהים ההיסטוריים) ומחזיר את תוכן הקובץ.
- אם הקובץ חסר, המודאל מוסתר ונרשמת התראה ב-log. ודאו שהקובץ קיים בכל Deploy.

#### איך לעדכן
1. ערכו את `webapp/USER_GUIDE.md` (לדוגמה: עדכון "מה חדש").
2. ודאו שהעמוד `/share/welcome?view=md` מציג את השינוי.
3. אין צורך להריץ Job נפרד – המודאל ימשוך את הטקסט אוטומטית.

### קישורי מדריכים (Anchors)
- Primary: `/share/welcome?view=md`
- Secondary: `/share/welcome-quickstart?view=md`

### Best Practices – סימון משתמשים חדשים
- סמנו `has_seen_welcome_modal` גם ב-session כדי למנוע הבהוב קליינט.
- ניתן לעשות reuse של הדגל עבור פיצ׳רים "חד פעמיים" נוספים.

```text
session: { has_seen_welcome_modal: true }
DB: users.has_seen_welcome_modal = true
```

### דוגמת JS – מודאל עם Ajax

```javascript
function welcomeModalInit() {
  const modal = document.getElementById('welcome-modal');
  if (!modal) return;

  async function ackAndHide() {
    try {
      const res = await fetch('/api/welcome/ack', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      });
      if (!res.ok) throw new Error('ack failed');
      try { sessionStorage.setItem('has_seen_welcome_modal', '1'); } catch (e) {}
      modal.style.display = 'none';
    } catch (e) {
      console.warn('welcome ack error', e);
    }
  }

  const primary = modal.querySelector('[data-action="primary"]');
  const secondary = modal.querySelector('[data-action="secondary"]');
  const skip = modal.querySelector('[data-action="skip"]');

  if (primary) primary.addEventListener('click', ackAndHide);
  if (secondary) secondary.addEventListener('click', ackAndHide);
  if (skip) skip.addEventListener('click', (ev) => {
    ev.preventDefault();
    ackAndHide();
  });
}

window.addEventListener('DOMContentLoaded', () => {
  try {
    if (sessionStorage.getItem('has_seen_welcome_modal') === '1') return;
  } catch (e) {}
  welcomeModalInit();
});
```

### API קשור
- `POST /api/welcome/ack` – מסמן את הדגל ומחזיר `{ "ok": true }`.
- `POST /api/shared/save` – לשיתוף והפצה של המדריכים עצמם.

---

## Interactive Tour (Driver.js)

הסיור האינטראקטיבי חי באותו קובץ (`webapp/templates/base.html`) תחת `initInteractiveWalkthrough()`. הוא מבוסס על Driver.js ומדגיש את הפעולות המרכזיות במסך הקבצים.

### מתי הסיור נפתח?
- משתמש מחובר (`session.user_id`).
- כתובת: `/files` (מוגדר ב-`AUTO_PATHS`).
- `localStorage["codekeeper_walkthrough_v1"] !== '1'`.
- קיימים אלמנטים פעילים (נבדק ע"י `buildSteps()` ו-`isElementTourVisible()`).
- ה-Welcome Modal כבר הוסר (MutationObserver).

### שלבי הסיור

| שלב | אלמנט (ID) | תיאור |
| --- | --- | --- |
| פתיח | — | מסר "ברוכים הבאים" והסבר קצר על מטרת הסיור. |
| יצירת קובץ חדש | `#tourCreateButton` (`webapp/templates/files.html`) | מציג את כפתור ההעלאה והוספת קבצים/קטעי קוד. |
| חיפוש גלובלי | `#globalSearchInput` | מסביר על החיפוש לפי שם, תוכן, תגיות ושפות. |
| האוספים שלי | `#tourCollectionsNav` (דלג במובייל) | מדגיש את תפריט האוספים ויתרונות השיתוף. |
| Outro | — | הודעת סיום עם רמז להפעלה חוזרת. |

להוספת שלב חדש – עדכנו את `buildSteps()` והקפידו שהאלמנט מקבל מזהה קבוע וגלוי.

### הפעלה ידנית ואיפוס
- **URL**: `?tour=restart` או `?tour=start` → מאפס את `codekeeper_walkthrough_v1`, מפעיל את הסיור ומוחק את הפרמטר מה-URL באמצעות `history.replaceState`.
- **Console API**:
  - `window.CodeKeeperTour.start()` – מפעיל את הסיור במקום.
  - `window.CodeKeeperTour.reset()` – מוחק את הדגל המקומי.
  - `window.CodeKeeperTour.hasSeen()` – שימושי ל-QA.
- **ניקוי ידני**: מחיקת `localStorage.codekeeper_walkthrough_v1` משיגה את אותו אפקט.

### תחזוקה למפתחים
- Driver.js נטען דרך `window.driver.js.driver`. אם הקובץ לא נטען – `getDriverFactory()` יחזיר `null` ותראו שגיאת קונסול.
- ההגדרות (`stageBackground`, טקסטי הכפתורים, smoothScroll) נמצאות באותו בלוק – אין צורך לשנות את Driver.js עצמו.
- `ThemeWizard.watchDriver(driver)` נקרא אחרי `driver.drive()` – אל תסירו את הקריאה כדי לשמור על הסדר מול הוויזארד.
- התאמות RTL מובנות בקובץ (`/* התאמות RTL ל-Driver.js */`). אם מוסיפים שלבים חדשים, ודאו שהטקסטים קצרים מספיק למסכים צרים.

### Troubleshooting – "למה הסיור לא מופיע?"
1. בדקו `localStorage.getItem('codekeeper_walkthrough_v1')`.
2. ודאו שאתם בנתיב `/files` ומחוברים.
3. וידאו שאין מודאלים אחרים פתוחים – ה-MutationObserver ימתין להיעלמות שלהם.
4. חפשו בקונסול הודעה לגבי `window.driver` – במידה והספרייה לא נטענה, הסיור לא יופעל.
5. Content blockers שחוסמים localStorage עלולים למנוע סימון דגל; במקרה כזה `?tour=restart` עשוי שלא לעבוד.

### צילומי מסך / GIF

![Interactive Tour Overlay](../images/interactive-tour-overview.svg)

התרשים מדגים את Driver.js בעת הדגשת כפתור יצירת הקובץ, יחד עם כפתורי "הבא" ו"דלג" בעברית.

---

## Theme Picker Wizard (Personalization)

ויזארד הפרסונליזציה משלים את תהליך ה-Onboarding ומאפשר לבחור Theme כבר בביקור הראשון, כולל תצוגה חיה וקריאה ל-API לשמירת ההעדפה.

### סקירה כללית
- מופעל רק למשתמשים מחוברים ובנתיב `/files`.
- `theme_wizard_seen` מונע הצגה חוזרת; שמירה או דלג שניהם מסמנים את הדגל.
- Live Preview מתבצע באמצעות עדכון `document.documentElement.dataset.theme` בזמן אמת.

### טריגרים והגנות
1. `waitForWelcome()` ממתין שהמודאל הראשי ייצא מה-DOM.
2. אם הסיור רץ – `ThemeWizard.watchDriver()` מאזין לאירוע `destroyed` של Driver.js ורק אז פותח את הוויזארד.
3. אם הסיור לא הופעל (אין אלמנטים/משתמש על מובייל) – `scheduleFallback()` פותח את הוויזארד לאחר ~9 שניות.
4. ניתן לפתוח בכפייה דרך `?theme_wizard=restart` או `window.ThemeWizard.open()`.

### ממשק וחוויית משתמש
- שלוש אפשרויות ברירת מחדל: **Nebula**, **Rose Pine Dawn**, **Classic** (`data-theme-option`).
- ריחוף/פוקוס/קליק מחליפים את ה-theme בזמן אמת.
- Live Preview ממוקם בצד ימין (תלות ב-CSS), והתוכן כולו תומך RTL.
- נגישות:
  - `Tab` נשמר בתוך ה-dialog (focus trap).
  - `Enter` / `Space` בוחרים Theme.
  - `Esc` סוגר את הוויזארד בלי לשמור.
- כפתורים:
  - **שמור והמשך** (`data-action="save"`) – מפעיל `persistTheme()` + קריאה ל-`POST /api/ui_prefs`.
  - **דלג** / אייקון הסגירה / קליק על הרקע – סוגרים ללא שמירה אך מסמנים `theme_wizard_seen`.

### התמדה וסנכרון שרת
- `localStorage.user_theme` – ערכת הנושא שנבחרה.
- `localStorage.dark_mode_preference` – נשמרת רק עבור ערכות כהות (`mapDarkModePreference`).
- בקשה ל-`POST /api/ui_prefs` שולחת `{ theme }` ומאפשרת לשרת לטעון את ה-theme כבר בשלב ה-render הבא.

### 🛠️ Debugging & Reset
- URL: `?theme_wizard=restart` (או `start`). הפרמטר נמחק מהכתובת אחרי הפתיחה.
- Console:
  - `window.ThemeWizard.open()` – פותח את הוויזארד.
  - `window.ThemeWizard.resetSeen()` – מוחק את הדגל.
  - `window.ThemeWizard.hasSeen()` – מחזיר סטטוס.
  - `window.ThemeWizard.scheduleFallback()` – מפעיל מחדש את מנגנון הזמן.
- ניקוי ידני: מחקו את `theme_wizard_seen`, `user_theme`, `dark_mode_preference` כדי לדמות משתמש חדש.

### מדריך בדיקות (QA)
1. פתחו חלון Incognito או נקו את כל מפתחות ה-onboarding ב-localStorage.
2. אפשרו ל-Welcome Modal להופיע ולהיסגר, ודאו שהסיור רץ. בסיום, צפו שהוויזארד נפתח אוטומטית.
3. בדקו Live Preview – כל בחירה צריכה לשנות את `data-theme` ואת ה-CSS.
4. לחצו "שמור והמשך" ובדקו ב-Network שהתקבלה תשובת 200 מ-`/api/ui_prefs`. רעננו כדי לוודא שהבחירה נשמרה.
5. לחצו "דלג" – ודאו שהוויזארד לא חוזר לאחר רענון (כי `theme_wizard_seen` סומן).
6. בדקו `?theme_wizard=restart` → אמור לפתוח בכפייה ולמחוק את הפרמטר מה-URL.
7. התנתקו (Guest) – וודאו שהוויזארד לא מוצג למשתמשים אנונימיים.

### צילומי מסך

![Theme Wizard Preview](../images/theme-wizard-preview.svg)

המחשה של הוויזארד עם שלוש ערכות הנושא, כפתורי הפעולה ו-Live Preview.

### קישורים רלוונטיים
- [webapp/overview.rst](overview.rst) – הסבר מלא על מסך ההגדרות (שינוי Theme ידני לאחר מכן).
- [webapp/static-checklist.rst](static-checklist.rst) – קווים מנחים לניגודיות ונגישות UI.
- [webapp/api-reference.rst](api-reference.rst) – פרטים נוספים על `POST /api/ui_prefs`.

---

## Troubleshooting מרוכז – "למה שום דבר לא קופץ לי?"

1. **בדקו localStorage** – `codekeeper_walkthrough_v1`, `theme_wizard_seen`, `user_theme`, `dark_mode_preference`. מחיקה תחזיר את ההרצה.
2. **נתיב וסטטוס כניסה** – שני הרכיבים רצים רק ב-`/files` ולמשתמש מחובר.
3. **מודאלים אחרים** – כל מודאל שחוסם את הדף יעכב את הסיור/הוויזארד עד להסרתו.
4. **Driver.js לא זמין** – ללא הספרייה לא יופעל סיור; Theme Wizard יופעל רק אחרי fallback.
5. **חוסמי תוכן** – הרחבות שמונעות גישה ל-localStorage או ל-MutationObserver עלולות לשבור את הרצף.
6. **בדיקת Console APIs** – `CodeKeeperTour.start()` ו-`ThemeWizard.open()` הן הדרך הקלה לוודא שהקוד טעון.

---

## מדיה והרחבות
- תרשים זרימה: `docs/images/onboarding-flow.svg`.
- צילום סיור Driver.js: `docs/images/interactive-tour-overview.svg`.
- צילום Theme Wizard: `docs/images/theme-wizard-preview.svg`.
- לאחר הוספת מדיה חדשה, הריצו `make html` בתוך `docs/` כדי לוודא שאין אזהרות Sphinx.
