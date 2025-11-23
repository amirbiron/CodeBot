# תכנית בדיקות לבוט – Composition Root (Container) לשירות Snippet

מסמך זה מתאר בדיקות ידניות מהירות לבוט לאחר העברת יצירת התלויות ל־Container דומייני/אפליקטיבי. המטרה: לוודא שה־handlers צורכים את השירות מאותה נקודת אמת, בלי לשנות לוגיקה.

## איך לבדוק
- **מטרה**: שמירה עובדת, השפה מזוהה נכון, ותצוגה/עריכה ממשיכות כרגיל.
- **מה לחפש**:
  - ההודעה אחרי שמירה מציגה שפה נכונה.
  - תצוגת קוד (Preview) צובעת נכון.
  - עריכה לא שוברת את השפה השמורה.
  - לא מופיעות שגיאות ב־logs על יבוא/הקמה של השירות.

## סט דוגמאות לשמירה (Copy/Paste)

1) Bash – קובץ ללא סיומת (`run`)

```bash
#!/usr/bin/env bash
python main.py
```

- שם קובץ: `run`
- צפוי: שפה `bash`

2) Bash משודרג – `start`

```bash
#!/usr/bin/env bash
set -e
echo "🚀 Starting bot..."
python main.py
```

- שם קובץ: `start`
- צפוי: שפה `bash`

3) Taskfile – YAML ללא סיומת

```yaml
version: '3'
tasks:
  run:
    desc: Run the bot
    cmds:
      - python main.py
  install:
    desc: Install dependencies
    cmds:
      - pip install -r requirements.txt
```

- שם קובץ: `Taskfile`
- צפוי: שפה `yaml`

4) סביבה – `.env`

```ini
# === Bot Configuration ===
BOT_TOKEN=
OWNER_CHAT_ID=
```

- שם קובץ: `.env`
- צפוי: שפה `env`

5) Markdown רגיל – `doc.md`

```
# כותרת

- רשימה
- עוד פריט

קישור: [דוגמה](https://example.com)
```

- שם קובץ: `doc.md`
- צפוי: שפה `markdown`

6) Python בתוך `.md` – `Block.md` (תוכן פייתון מובהק)

```python
import os, asyncio

def main():
    print("hi")
```

- שם קובץ: `Block.md`
- צפוי: שפה `python` (אם אין סימני Markdown חזקים)

## בדיקות נוספות
- הצג קוד אחרי שמירה → וודא שה־preview צבוע לפי השפה.
- ערוך את אותו קובץ → שמירה חוזרת מציגה שפה עקבית.
- קבצים מיוחדים: `Dockerfile`, `Makefile`, `.gitignore`, `.dockerignore` → שפה תואמת שם הקובץ.

## תקלות שכדאי לעקוב אחריהן
- הבוט מציג `text` במקום שפה צפויה (בדוק shebang/שם/תוכן).
- חריגות Import על `src.infrastructure.composition`.
- זיהוי `.md` כפייתון למרות Markdown בולט (כותרות/רשימות/גדרות קוד).

---

## בדיקות זרימה מורחבות (לאחר מעבר ל-Facade/Container)

### 1) שמירה/תצוגה/עריכה (קבצים רגילים)
- שמור `doc.md` (Markdown רגיל) ו־`Taskfile`/`.env` (YAML/ENV) → הודעת הצלחה + שפה נכונה.
- תצוגת קוד: כפתורי “✏️ ערוך קוד”, “📝 ערוך שם/הערה”, “📚 היסטוריה”, “📥 הורד”, “🔗 שתף” עובדים.
- עריכת שם: שנה שם (למשל `Taskfile.v2`) → “👁️ הצג קוד/📚 היסטוריה” פועלים; מזהה (fid) מתעדכן אם קיים.
- עריכת הערה: הוסף “בדיקה ידנית” → מוצג ב־View; ערוך שוב ל”מחק” → ההערה מוסרת.
- מועדפים: הכפתור מחליף תווית (“⭐/💔”) ונשמר מצב.
- מחיקה: “🗑️ מחק” → “כן, העבר לסל מיחזור” → חזרה לרשימה.

### 2) קבצים גדולים
- שמור תוכן גדול (1000+ שורות) בשם `big.log`.
- עריכה מהזרימה של “קבצים גדולים” → זיהוי שפה דרך `code_service` ושמירה דרך Facade; הודעת הצלחה + “📚 חזרה לקבצים גדולים”.

### 3) מסמכים/העלאות
- העלה קובץ טקסט קטן → מתקבל fid; “הורד/ערוך/היסטוריה/שתף” עובדים.
- העלה ZIP → נשמר ב־backups; אם הפעלה רלוונטית, ניתן ליצור ריפו חדש ולשמור `selected_repo`.

### 4) Google Drive
- /drive → תפריט נפתח; בצע התחברות (Device Code) או בדיקת polling ידנית.
- בחירת ZIP בלבד: “drive_sel_zip” → “אישור” מעלה רק ZIPים שמורים; נשמר `last_selected_category`.
- בחירת הכל: “drive_sel_all” → “אישור” מעלה הכל; “drive_status” מציג סטטוס.
- Advanced: by_repo/large/other → עבור קטגוריה ללא פריטים מתקבלת הודעת “אין פריטים”; כאשר יש, ההעלאה מצליחה.
- Scheduling: קבע daily/weekly → “next run” מתעדכן; אחרי ריצה (אוטומטית/ידנית) “last_backup_at/next” מתעדכנים; ניתן לבטל (off).
- Logout: “drive_logout_do” מנקה טוקנים ומציג הודעת ניתוק.

### 5) ChatOps – זיהוי שפה (שקיפות ודיבוג)
- `/lang run` עם reply:
```bash
#!/usr/bin/env bash
python main.py
```
צפוי: `bash`; reason: `shebang`.

- `/lang Block.md` עם reply:
```python
import os, asyncio
def main(): pass
```
צפוי: `python`; reason: `override ל-.md`.

- `/lang_debug` באותו קלט → מוצגים shebang/ext/אותות Python וסימני Markdown.

### 6) רגרסיה כללית
- “📚 היסטוריה” → “👁 הצג גרסה” עובד; “↩️ שחזר לגרסה” מחזיר הודעת הצלחה (כאשר זמין).
- “📥 הורד” → מתקבל קובץ בשם תקין.
- “🔄 שכפול” → נוצר שם “(copy)”/“(copy n)”; הודעת הצלחה עם כפתורי View/History/Download.

