# 🤖 שליחת משימות ל‑Claude Code דרך הבוט

מדריך לפיצ'ר `/claude` — שליחת משימות קוד אמיתיות על הריפו, מהטלגרם.

---

## מה זה עושה

שולחים בטלגרם `/claude תקן את הבאג בשמירת קבצים גדולים`, והבוט פותח Issue בריפו
עם מנשן `@claude`. GitHub Actions מריץ את Claude Code על הקוד האמיתי, הוא פותח PR,
וכשהוא מסיים ההודעה חוזרת אליכם לטלגרם — כתשובה להודעה המקורית.

זה לא צ'אט. זה משימת עבודה שרצה ברקע ולוקחת דקות.

> **הכיוון ההפוך כבר קיים:** `/connect_claude` מנפיק טוקן MCP שמאפשר ל‑Claude
> *לקרוא* את הקבצים שלכם. הפיצ'ר הזה הוא הכיוון השני — לתת ל‑Claude *לעבוד*.

---

## הזרימה

```
טלגרם: /claude <משימה>
   ↓  בדיקת אדמין + סניטציה + מכסה
   ↓  preview עם כפתור אישור  ← כאן אפשר עוד להתחרט
   ↓
GitHub Issue עם @claude ו-label claude-task
   ↓
.github/workflows/claude.yml  →  anthropics/claude-code-action
   ↓
Claude עובד, פותח branch + PR, מגיב ב-Issue
   ↓
טלגרם: "✅ Claude סיים — PR #45" + תקציר התשובה
```

יש שלוש נקודות עדכון: אישור השליחה, "Claude התחיל", ו‑"סיים/נכשל".
אם אחרי 3 דקות לא זוהתה ריצה בכלל — הבוט שולח אזהרה במקום להשאיר אתכם מחכים.

---

## הפקודות

| פקודה | מה היא עושה |
|---|---|
| `/claude <משימה>` | פותח preview, ואחרי אישור שולח את המשימה |
| `/claude_status [מספר]` | מצב משימה (ברירת מחדל: האחרונה) |
| `/claude_tasks` | 10 המשימות האחרונות |
| `/claude_cancel [מספר]` | סוגר את ה‑Issue ועוצר את העבודה |

כל הפקודות זמינות **למנהלים בלבד ובצ'אט פרטי בלבד**.

---

## התקנה

### 1. בצד GitHub

**א. מזגו את `.github/workflows/claude.yml` ל‑`main`.**
זה לא אופציונלי: workflow שקיים רק בענף פיצ'ר לא מופעל ע"י אירועי
`issues`/`issue_comment`. זו התקלה הכי מבלבלת בפיצ'ר הזה.

**ב. צרו את ה‑label `claude-task`** בריפו. בלעדיו ה‑workflow לא ירוץ,
וה‑API יחזיר 422 כשהבוט ינסה לפתוח Issue.

**ג. הוסיפו secrets:**

| Secret | למה | חובה? |
|---|---|---|
| `ANTHROPIC_API_KEY` | הרצת Claude | ✅ |
| `BOT_TOKEN` | שליחת ההודעות לטלגרם | ✅ (כבר קיים) |
| `CHAT_ID` | אימות היעד + fallback | ✅ (כבר קיים) |
| `CLAUDE_PAT` | כדי שה‑PR של Claude יפעיל CI | מומלץ |

**ד. צרו PAT (fine‑grained) מוגבל לריפו הזה בלבד**, עם:
`Issues: Read & Write`, `Contents: Read`, `Actions: Read`, `Pull requests: Read`.

> ⚠️ **הגיטצ'ה הכי חשובה:** ה‑Issue חייב להיפתח עם PAT אישי.
> Issue שנוצר עם `GITHUB_TOKEN` של Actions **לא מפעיל workflows** — זו הגנה
> מובנית של GitHub נגד לולאות. אם תשתמשו בטוקן הלא נכון, ה‑Issue ייפתח יפה
> וכלום לא יקרה אחריו.

### 2. בצד הבוט (Render)

```bash
CLAUDE_DISPATCH_ENABLED=true
CLAUDE_DISPATCH_REPO=amirbiron/CodeBot
CLAUDE_DISPATCH_TOKEN=<ה-PAT מסעיף ד>
CLAUDE_TASK_LABEL=claude-task
ADMIN_USER_IDS=<מזהה הטלגרם שלכם>
```

אופציונלי: `CLAUDE_MAX_PROMPT_LEN` (1500), `CLAUDE_MAX_TASKS_PER_DAY` (10),
`CLAUDE_WATCHDOG_SEC` (180).

### 3. סדר ההפעלה

1. מזגו את ה‑workflow ל‑`main`.
2. **בדקו אותו ידנית**: פתחו Issue מהדפדפן עם label `claude-task` וטקסט
   שמתחיל ב‑`@claude`. ודאו שהריצה מתחילה ושההודעה מגיעה לטלגרם.
3. רק אחר כך הדליקו `CLAUDE_DISPATCH_ENABLED=true`.

הסדר הזה מפריד בין "הבוט לא פותח Issue" לבין "ה‑workflow לא רץ" — שתי תקלות
שנראות זהות מהצ'אט אבל הפתרון שלהן שונה לגמרי.

---

## אבטחה

Claude Code כאן מקבל הרשאת כתיבה לריפו, אז יש כמה שכבות:

**בבוט:**
- אדמינים בלבד (`ADMIN_USER_IDS`), וצ'אט פרטי בלבד.
- אם `ADMIN_USER_IDS` ריקה — הפקודה חסומה לכולם, גם אם
  `CHATOPS_ALLOW_ALL_IF_NO_ADMINS` דלוק.
- מכסה יומית + מקסימום 3 משימות פעילות + cooldown בין פקודות.
- אישור בכפתור לפני כל שליחה (כל ריצה עולה טוקנים).
- **סניטציה של הטקסט**: נטרול `<!--`/`-->` כדי שלא ניתן לזייף את בלוק ה‑meta,
  נטרול התג התוחם, נטרול מנשנים (`@`), והסרת תווי בקרה.
- **חסימת סודות**: טקסט שנראה כמו טוקן/מפתח נדחה ולא נשלח. לא מרדקטים —
  חוסמים, כי Issue ב‑GitHub נשמר לצמיתות גם אחרי מחיקה.

**ב‑workflow:**
- רץ רק אם יש `@claude` **וגם** label `claude-task` **וגם** לכותב יש הרשאת
  write/admin על הריפו (נבדק מול ה‑API, לא לפי רשימת שמות).
- חסימת בוטים (`sender.type != 'Bot'`) — בלי זה התגובה של Claude מפעילה את
  ה‑workflow שוב, בלולאה.
- `concurrency` לפי מספר Issue, ו‑`timeout-minutes: 30`.
- `permissions` ברמת ה‑workflow הוא `contents: read`; רק ה‑job של Claude מקבל write.

**על prompt injection:** הטקסט של המשתמש נכנס בתוך `<task-from-telegram>`
עם משפט מסגור מפורש. זו לא הגנה מוחלטת — ההגנה האמיתית היא ה‑permissions
ו‑branch protection על `main`. גם אם המודל "משתכנע", הוא לא יכול לדחוף ל‑main מוגן.

---

## קבצים

| קובץ | תפקיד |
|---|---|
| `chatops/claude_commands.py` | סניטציה, ולידציה, בניית טקסטים (בלי I/O) |
| `services/claude_dispatch_service.py` | קריאות GitHub API, בניית ה‑Issue |
| `services/claude_tasks_store.py` | מעקב מצב ב‑Mongo (`claude_tasks`) |
| `claude_task_handlers.py` | ה‑handlers של טלגרם |
| `.github/workflows/claude.yml` | הריצה עצמה + ההודעות חזרה |

---

## תקלות נפוצות

| תסמין | סיבה סבירה |
|---|---|
| ה‑Issue נפתח אבל שום דבר לא קורה | ה‑workflow לא ב‑`main`, או שהטוקן הוא GITHUB_TOKEN של Actions |
| "GitHub דחה את הבקשה (422)" | ה‑label `claude-task` לא קיים בריפו |
| "הטוקן של GitHub לא תקין (401)" | `CLAUDE_DISPATCH_TOKEN` שגוי או פג |
| ה‑PR של Claude נפתח בלי checks | חסר `CLAUDE_PAT` (או התקנת Claude GitHub App) |
| ההודעה לא חוזרת לטלגרם | `BOT_TOKEN`/`CHAT_ID` חסרים ב‑secrets של הריפו |
